"""M12rr — the SHARED runtime wall-renderer emitter. Extracted from the M12nn capstone test so the SHIPPED
`build_doom` binary and the byte-exact golden test emit the *same* renderer (R6 single-source) — every
space optimization (M12oo pass-2 trampoline, M12pp/qq xor_by + xor-involution walk) is baked into this one
emitter, so build_doom inherits them for free.

`emit_wall_renderer(wad, mapname, cfg)` returns the renderer `main` fj text; assemble it with the fixed
include set [fj_consts, fixed_point, present, projection, frame_render, <main>]. The viewpoint is read from
stdin at runtime (`vx vy va`, signed decimal) so ONE assembled binary renders any E1M1 viewpoint — exactly
the two-pass runtime renderer (B'): a runtime BSP-walk pass 1 fills the per-column param arrays, then the
unrolled pass 2 rasters them through the shared-compare trampoline.
"""
from __future__ import annotations

from doomfj.lut_generator import (
    generate_dispatch_table_fj,
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj, generate_slopediv_recip_lut_fj,
    generate_slopediv_recip8_lut_fj,
    generate_yslope_lut_fj, generate_zlight_lut_fj, generate_distscale_lut_fj,
    generate_emit_dispatch_table_fj, generate_yslope_packed_lut_fj, generate_zlight_packed_lut_fj,
    generate_zlight_cuts_fj,
)
from doomfj.reference_model import ANG90
from doomfj.mapcompiler import (bake_bsp, _bsp_as_code, _bsp_descend_code, _bytes_stream,
                                NF_SUBSECTOR, seg_affine_coeffs)
from doomfj.reference_model import (ReferenceModel, WALL_BG, WPX_RUN_CAP,
                                    COLORMAP_LIGHTS, LIGHT_SHIFT, SLOPERANGE, build_scene)
from doomfj.texturecompiler import (compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table, downscale_canvas,
                                    colormap_values, _index_nibbles, generate_colormap_packed_table_fj)
from doomfj.coarse_cull import generate_coarse_bounds_fj
from doomfj.tables import tantoangle_table, slopediv_recip8_table
from doomfj.config import PNEAR_SEG_BUDGET


NLJ = chr(10)   # newline constant for generated .fj text


def _pfx(mapname: str) -> str:
    """The BSP-as-code label prefix for a map (lowercased, flipjump-legal)."""
    return mapname.lower().replace("-", "_")


def _seg_xorby_block(idx, fields):
    """The shared seg{idx}_xorby block (emitted ONCE, fcall'd twice per visible seg — SET then CLEAR). M12pp:
    replaces the per-seg baked `hex.set` (each pays an @-dispatch to zero a reg it overwrites) with `hex.xor_by`
    (no @), kept correct by xor-INVOLUTION self-zeroing. `fields` = list of (regname, width, value) PURE
    compile-time constants. Correct ONLY on a zero register, so the zero-init seg regs self-restore each call."""
    lines = [f"  seg{idx}_xorby:"]
    for reg, wdt, val in fields:
        lines.append(f"    hex.xor_by {wdt}, {reg}, {val}")
    lines.append("    stl.fret xb_ret")
    return lines


def _seg_xorby_use(idx, clear=True):
    """The SET / USE / CLEAR fcall sequence at the call site. `clear=False` drops the involution CLEAR (a TDD
    FAIL stub: seg regs accumulate across segs -> wrong values for every seg after the first)."""
    seq = [f"    stl.fcall seg{idx}_xorby, xb_ret",      # SET  (0 -> vals)
           "    stl.fcall seg_pass1_leaf, seg_ret"]      # USE  (the leaf READS the seg regs)
    if clear:
        seq.append(f"    stl.fcall seg{idx}_xorby, xb_ret")   # CLEAR (vals -> 0, the xor involution)
    return seq


_ABLATE_MODES = frozenset({"planes", "pass2", "pass1", "segstub", "xrstub", "wedgestub",
                           "tsprobe", "tsmark", "pnearprune", "pnearcol", "pnearwalk", "tsfull",
                           "emitnopair", "emitnowalk", "atantwice",
                           "slopetwice", "tabletwice", "noflush", "colstub",
                           "noprescan", "noproj"})

# M13-lines5: xorby fields the LINES leaf never reads (the device prints raw lines; fj's own emit
# uses seg_lit + the flat bases, not the texture machinery). SET+CLEAR runs for every walk-reached
# seg, so each dead field costs twice per seg. Keep in sync with seg_pass1_leaf_body_lines's `<`
# list. (ceilfix/floorfix STAY: column_render_params_stream reads them.)
_LINES_DEAD_FIELDS = frozenset({"seg_texoff", "seg_texbase", "seg_texheight", "seg_tw",
                                "seg_hm", "seg_light", "seg_ceil", "seg_floor", "seg_plight",
                                "seg_ceilbase", "seg_floorbase"})

DW_BITS = 64                   # `dw` in address units at w=32 (2w), for baked dw-offsets
TS_ECAP = 24                   # M13-2S rung 3b: buffered REGIONS per column per side,
                               # 5 bytes each ([kind][arg:2][y1][yend]). Measured worst
                               # over 30 E1M1 viewpoints: 14 top / 10 bottom.
MAX_BANDS = 64                    # M13pS2c: band-list slots/column/region. Bound: a monotone half-window's
                                  # zidx walk gives <=32 distinct zrow runs (zlight[lvl][zidx] is monotone in
                                  # zidx with values in [0,31]); a horizon-STRADDLING window (negative-viewz
                                  # areas) is built as TWO half-window walks appended -> <=64 entries.
BAND_STRIDE = MAX_BANDS * 3        # packed bytes per column per region (run-length, base, zrow each entry)


def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False,
                       ablate: frozenset = frozenset(), floor_mode: str = "textured",
                       wall_mode: str = "textured", raster_mode: str = "framebuffer",
                       plane_near: bool = False, two_sided: bool = False) -> str:
    """Emit the full runtime wall+floor/ceiling renderer for `mapname` as the fj `main` text (everything after
    the fixed includes). Uses the optimized SHARED macros (pixel_tramp/compare_y wall trampoline, the
    xor_by-involution walk, and the M13c3 plane_tramp visplane raster), so this is the single source both
    `build_doom` and the golden test render through. The viewpoint `(vx,vy,va)` is read from stdin (signed
    decimal) at runtime. Geometry comes from `map_wad`; textures/colormap/palette/flats from `asset_wad`
    (defaults to `map_wad` — E1M1 is self-contained; the square-room test passes a separate asset wad).
    `over_align` pads dispatch tables to a 2^n boundary (test layout); pass False for the production
    (build_doom) layout.

    `ablate` (M13p0, measurement-only — NEVER set for build_doom/the golden tests) drops components so
    `scripts/measure_frame.py` can isolate their ops/frame cost by delta:
      - "planes"  — drop the floor/ceiling visplane pass (pass 2b) from the mainline.
      - "pass2"   — drop the wall raster (pass 2a, the per-column trampoline) from the mainline.
      - "pass1"   — skip the BSP-walk jump entirely (pass-1 never runs; col arrays stay zero-init),
                    isolating init/input-parse/present residue. Valid ONLY combined with "planes"+"pass2"
                    (ablating pass1 alone leaves pass2/planes rendering garbage zero-filled columns).
      - "segstub" — the per-seg leaf `stl.fret`s immediately (no full-flag check, no wall_x_range) =
                    the bare walk skeleton (node side tests + subsector dispatch + the SET/CLEAR xorby
                    call overhead), isolating the walk from every per-seg cost.
      - "xrstub"  — the per-seg leaf keeps the `full`-flag pre-check but replaces `wall_x_range` with an
                    immediate cull-fail (no atans, no cull math) = walk + per-seg entry overhead only.
    "segstub"/"xrstub" are mutually exclusive and independent of "planes"/"pass2"/"pass1".

    `floor_mode` (M13p1): "textured" (default, M13b/M13d2 perspective u,v floors) or "flat" (M13a/M13p1
    flat-colored floors — no per-span DDA seed, no per-pixel sample; `seg_ceilbase`/`seg_floorbase` bake
    the flat's 2-nibble BASE palette index instead of a 5-nibble combined-table slice offset, and the
    combined flat texel table is not emitted at all).

    `wall_mode` "WPX" (M13-WPX, the lines-mode SHIPPING tier) is different in kind: the wall texels
    never enter the combined table at all (it stays at the W1 tier — see `tex_mode`). Instead
    `_lines_wall_pix_bank` bakes a per-(texture,light) × per-exact-height RUN-LIST bank, giving one
    texture texel per screen pixel down each column for one add per colour run at runtime.

    `wall_mode` (M13p4a): "textured" (default, the real per-seg wall texture) or "W1"/"W2" — every wall
    texture is reduced to a tiny synthetic canvas (`ReferenceModel._tiny_wall_canvas`, the SAME helper
    the oracle uses, R6) before it enters the combined table: W1 = 1×1 (the mode texel), W2 = 1×16 (a
    vertical band strip). `column_render_params`/pass-2/`leaf_body_w` are UNCHANGED — they just sample a
    much smaller table (793,344 texels → tens-to-low-hundreds).

    `plane_near` (M13-2S rung 3a, lines mode only): attribute each column's floor/ceiling surface to
    the nearest MARKING seg -- two-sided included -- instead of to the one-sided wall that claims the
    column. That claiming wall is generally in another room, which is the owner's "the close floor in
    the middle is gray, yet the sides are yellow" bug (docs/handoff-m13-2s.md §2). Marking = DOOM's
    R_StoreWallRange markfloor/markceiling test: the two sides differ in the band-bank key
    (height, light, flat). It CHANGES rendered output, so it is opt-in: without it every tier renders
    byte-identically to before (the `pnear` compile-time flag emits none of the added ops and the bank
    keeps the old shared-key layout; the only residue is +4.7k ops/frame of address-layout tax from
    the added per-column arrays, measured on E1M1 spawn: 23,204,595 -> 23,209,289).

    `raster_mode` (M13pS2): "framebuffer" (default, the UNCHANGED pass-1/pass-2/plane-pass pipeline
    above) or "stream" — THE COLUMN-STREAM COMPOSITE. Pass-1 builds each claimed column's ceiling/
    floor packed-byte BAND LISTS (`plane.build_bands`, `src/fj/plane_bands.fj`) and bakes the W1
    wall's fully-constant lit BYTE (`seg_lit`, computed here at Python emit time from the real
    colormap — no runtime lookup needed), storing them in `col_ceil_bands`/`col_ceil_n`/
    `col_floor_bands`/`col_floor_n`/`col_lit`; then, instead of any framebuffer raster, the frame is
    EMITTED as the device run-stream (`present.begin_frame_stream` + an unrolled
    `rep(VIEW_W,x) stream.emit_column ...` — `src/fj/stream_render.fj`, which the assemble include
    list must therefore contain in this mode), decoded by `StreamScreen`. The framebuffer, the pass-2
    wall trampoline, and ALL plane-pass machinery (`render_planes_spans`/`draw_span*`/`clear_planes`)
    are NOT EMITTED in this mode; the `cm`-label table is the EMIT dispatch table (`cm.emit`, run
    colours) plus the `byte.emit` identity table, replacing `compile_colormap`'s `cm.apply` table
    (same label — they cannot coexist, and nothing calls `cm.apply` here). Requires `wall_mode="W1"`
    and `floor_mode="flat"` (the only combination pS2 targets — W2's per-band wall lighting and
    textured floors are out of scope). ⚠ every column must be CLAIMED by pass-1 (a closed level
    always does) — an unclaimed column would emit 0 of its VIEW_H rows and stall the device's
    pixel count."""
    assert ablate <= _ABLATE_MODES, f"unknown ablate mode(s): {ablate - _ABLATE_MODES}"
    assert not ({"segstub", "xrstub"} <= ablate), "segstub and xrstub are mutually exclusive"
    assert floor_mode in ("textured", "flat", "FT1"), f"unknown floor_mode: {floor_mode!r}"
    assert wall_mode in ("textured", "W1", "W2", "W2S", "WPX"), f"unknown wall_mode: {wall_mode!r}"
    # M13-WPX carries its real texels in its OWN per-height bank, so the shared combined table
    # (and `seg_lit`) stays at the W1 tier -- one mode texel per texture, not the 793k-texel one.
    tex_mode = "W1" if wall_mode == "WPX" else wall_mode
    assert raster_mode in ("framebuffer", "stream", "spans", "raster", "proj", "lines"), \
        f"unknown raster_mode: {raster_mode!r}"
    # M13-spanfill: "spans" shares the ENTIRE stream pipeline (pass-1 band lists + col_struct + the
    # planesproto band buffers) and differs ONLY in the final present_tail: instead of the 0x09
    # planes protocol (device does the per-column clip), it emits explicit fillCol spans over the 0x0A
    # dumb-screen protocol (fj does the clip, device just fills). `stream` gates the shared pipeline.
    stream = raster_mode in ("stream", "spans")
    # M13-raster: the DEVICE RASTERIZER. fj stays the brain (walk/occlusion/projection-setup); the
    # device does the per-column wall DDA + first-wins fill + distance-light shade from compact
    # per-seg/per-visplane records emitted INLINE during the walk (no col_struct/band-list buffering
    # at all -- see frame.seg_pass1_leaf_body_raster). Shares the "no framebuffer/pass2/planes,
    # cvp_ids/fvp_ids, until-full abort" plumbing with stream/spans (the `stream or raster` checks
    # below) but has its OWN present_tail/decls/leaf-body.
    raster = raster_mode == "raster"
    # M13-proj (Path B LAB MODE, NOT a shipped default): the device holds the whole static per-seg
    # geometry table (0x0E) and does the vertex->column projection itself; fj keeps the walk + the
    # wedge and back-face culls and emits a 2-byte compact seg id per survivor. Built behind this
    # flag per the bake-off precedent ("keep building ladder infra behind mode flags; only the final
    # default-flip needs the owner's pick") -- flipping any default remains the owner's call.
    projm = raster_mode == "proj"
    # M13-lines: the DUMB-DEVICE mode (owner ruling 2026-07-27: the device may only print explicit
    # lines/pixels). fj does EVERYTHING -- projection, per-column clip, occlusion, band boundaries,
    # colormap -- and emits raw fillCol [x][y1][y2][colour] records (the 0x0A spans protocol)
    # inline at column-claim time. No col_struct, no present-tail pass.
    lines = raster_mode == "lines"
    assert not plane_near or lines, "plane_near is a lines-mode tier (M13-2S rung 3a)"
    # M13-2S rung 3b: the TWO-SIDED renderer -- DOOM's R_RenderSegLoop window per column, upper
    # and lower wall runs, and one plane region per bounding SEG. It supersedes plane_near (whose
    # attribution it includes) and targets ReferenceModel.render_frame_2s.
    assert not two_sided or lines, "two_sided is a lines-mode tier (M13-2S rung 3b)"
    assert not (two_sided and plane_near), "two_sided already includes plane_near's attribution"
    plane_near = plane_near or two_sided
    # ablate "pnearcol" prices the emit half alone (per-column attribution OFF, the two-sided claim
    # walk still emitted); "pnearwalk" prices the walk alone (claim sites dropped, per-column ON).
    # Both render wrong on purpose -- measurement only.
    pnear_flag = 1 if (plane_near and "pnearcol" not in ablate) else 0
    # M13-EMIT rung 1 (measurement only): 1 = walk the baked band lists but emit no pairs (prices the
    # two byte.emit dispatches), 2 = skip the band walks entirely (prices the whole per-pair path:
    # two hex.read_byte_and_inc pointer reads + the loop + the dispatches). Renders wrong on purpose.
    eabl_flag = 2 if "emitnowalk" in ablate else (1 if "emitnopair" in ablate else 0)
    # M13-EMIT rung 3 (measurement only): run each seg's two vertex atans TWICE, the second time
    # into a dead register. Everything downstream stays bit-identical (the frames must still come
    # out byte-exact), so the delta IS the frame's point_to_angle cost.
    atan_dbl = 1 if "atantwice" in ablate else 0
    # ... and the same trick INSIDE point_to_angle_m, to split the atan into its two halves: the
    # slope divide vs the packed tantoangle LUT read (4 pointer byte-reads).
    slope_dbl = 1 if "slopetwice" in ablate else 0
    table_dbl = 1 if "tabletwice" in ablate else 0
    w2s_flag = 1 if wall_mode == "W2S" else 0   # M13-W2S tier select for the lines leaf
    wpx_flag = 1 if wall_mode == "WPX" else 0   # M13-WPX (1x1 vertical) tier select
    if stream or raster or projm or lines:
        assert wall_mode in ("W1", "W2S", "WPX") and floor_mode in ("flat", "FT1"), \
            "the run-stream modes support wall_mode='W1'/'W2S'/'WPX' + floor_mode='flat'/'FT1'"
        assert wall_mode == "W1" or lines, f"wall_mode={wall_mode!r} is a lines-mode tier"
        assert floor_mode != "FT1" or lines, "floor_mode='FT1' is a lines-mode tier"
    asset_wad = asset_wad or map_wad
    rm = ReferenceModel(cfg)                                  # REAL textures (no _wall_texture override)
    cmap = bake_bsp(map_wad, mapname)
    verts = cmap.vertexes
    lds = map_wad.linedefs(mapname); sds = map_wad.sidedefs(mapname); secs = map_wad.sectors(mapname)
    scene = build_scene(map_wad, asset_wad, mapname)
    colormap = scene.asset_wad.colormap()
    proj = cfg.PROJECTION << 16
    defs = {d.name.upper(): d for d in asset_wad.texture_defs("TEXTURE1")}

    def _ts_draws_wall_early(seg) -> bool:
        """_seg_draws_wall, needed by the texture/WPX bakes that run before it is defined."""
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return False
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return fs_.ceil_h > bs_.ceil_h or bs_.floor_h > fs_.floor_h

    # the combined dispatch table over every distinct wall texture the one-sided segs use (downscaled to match
    # the oracle's _wall_texture), plus the 1x1 WALL_BG sentinel; per-seg texinfo precomputed via the oracle rule.
    cache = {}
    seg_texinfo = {}                                         # si -> (texbase, texheight, texwidth)
    names = set()
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1 and not ("tsfull" in ablate and secs and _ts_draws_wall_early(seg)):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        if rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=tex_mode) is not None:
            names.add(sd.middle.upper())
    combined, info = [], {}
    for nm in sorted(names) + [None]:
        key = nm if nm else "__WALLBG__"
        if nm is None:
            th, tw, texels = 1, 1, [WALL_BG]
        else:
            c = downscale_canvas(composite_texture(asset_wad, defs[nm]), rm.downscale)
            th, tw, texels = len(c), len(c[0]), texture_texels(c)
            if tex_mode != "textured":                         # M13p4a: shrink to the tiny synthetic canvas
                texels, th, tw = rm._tiny_wall_canvas(texels, th, tex_mode)
        while len(combined) % th != 0:                        # align the slice to its texheight (the OR-trick)
            combined.append(0)
        info[key] = (len(combined), th, tw)
        combined += texels
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1 and not ("tsfull" in ablate and _ts_draws_wall_early(seg)):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        t = rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=tex_mode)
        seg_texinfo[si] = info[sd.middle.upper()] if t is not None else info["__WALLBG__"]

    tex = _texel_table("tex", combined, "per_entry", over_align=over_align)

    # M13-proj: compact one-sided-seg ids (walk-independent, seg-index order) for the 2-byte wire
    # records + the device-resident geometry table (30 B/row packed bytes via _bytes_stream --
    # stream_screen.PROJ_ROW_BYTES must match this layout).
    proj_sid = {}
    proj_geom_txt = ""
    if projm:
        for si, seg in enumerate(cmap.segs):
            if lds[seg.linedef].back == -1:
                proj_sid[si] = len(proj_sid)

    # M13d2 — the combined FLAT texel table over every distinct ceil/floor flat the one-sided seg sectors use
    # (64x64 RAW, NO downscale; the `&63` wraps). Each flat gets a SLICE offset; the textured span pass samples
    # `flat[slice_offset + (v&63)*64 + (u&63)]`. Missing flats (e.g. the sky placeholder before M16) become a
    # uniform WALL_BG tile via _flat_texels — identical to the oracle. Per-seg bakes the ceil/floor slice offset.
    # M13p1: floor_mode="flat" bakes the flat's 2-nibble BASE palette index instead (M13a tier, `_flat_base`)
    # and skips the combined flat table entirely (not sampled by draw_span_flat).
    flat_texcache: dict = {}
    flat_basecache: dict = {}
    flat_slice: dict = {}
    flat_table = ""
    if floor_mode == "textured":
        flat_names = set()
        for si, seg in enumerate(cmap.segs):
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            fsec = rm._seg_sector(lds, sds, secs, seg)
            flat_names.add(fsec.ceil_tex.upper()); flat_names.add(fsec.floor_tex.upper())
        flat_combined = []
        for nm in sorted(flat_names):
            flat_slice[nm] = len(flat_combined)
            flat_combined += list(rm._flat_texels(asset_wad, nm, flat_texcache))
        flat_table = _texel_table("flat", flat_combined, "per_entry", over_align=over_align)

    def _flatval(name: str) -> int:
        return (flat_slice[name.upper()] if floor_mode == "textured"
                else rm._flat_base(asset_wad, name, flat_basecache))
    # M13-proj: the device-resident geometry rows (needs _flatval, hence built here)
    if projm:
            rows = []
            for si in proj_sid:
                seg = cmap.segs[si]
                v1x, v1y = verts[seg.v1]
                v2x, v2y = verts[seg.v2]
                sa, sb, sc = seg_affine_coeffs(seg, verts)
                gsec = rm._seg_sector(lds, sds, secs, seg)
                gtb = seg_texinfo[si][0]
                rows.append((v1x & 0xFFFF, v1y & 0xFFFF, v2x & 0xFFFF, v2y & 0xFFFF, seg.angle,
                             sa, sb, sc, gsec.ceil_h & 0xFFFF, gsec.floor_h & 0xFFFF,
                             gsec.light & 0xFF,
                             colormap[max(0, min(COLORMAP_LIGHTS - 1, gsec.light >> LIGHT_SHIFT))][combined[gtb]],
                             _flatval(gsec.ceil_tex), _flatval(gsec.floor_tex)))
            proj_geom_txt = _bytes_stream("seg_geom", rows, (2, 2, 2, 2, 2, 4, 4, 4, 2, 2, 1, 1, 1, 1))

    if stream or lines:
        # M13pS2: nothing calls `cm.apply` in stream mode -- the `cm` label carries the EMIT dispatch
        # table instead (`cm.emit`, band-run colours; same flattened light<<8|colour values), plus the
        # `byte.emit` identity table (run counts + the baked col_lit wall bytes). Same label as
        # compile_colormap's table, so the two are mutually exclusive per program.
        cmv = colormap_values(asset_wad, lights=COLORMAP_LIGHTS)
        cm = "\n".join([
            generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
            generate_emit_dispatch_table_fj("cm", cmv, index_nibbles=_index_nibbles(len(cmv)),
                                            over_align=True),
        ])
    elif raster or projm:
        # M13-raster/proj: nothing calls cm.emit OR cm.apply -- the device does its OWN colormap
        # lookup from the raw packed colormap table (present.load_raster_tables); only byte.emit
        # (runtime-byte emit: record fields / header bytes / seg ids) is needed.
        cm = generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2)
    else:
        cm = compile_colormap("cm", asset_wad, lights=COLORMAP_LIGHTS, over_align=over_align)
    palette = compile_palette("palette", asset_wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    # M13-ATANDISP (lines mode): the SAME tantoangle values as a D4 per-entry dispatch table, so
    # point_to_angle_m can trade its ~289@ packed read (4x read_byte_and_inc + a mul_const, per the
    # stl's documented complexities) for a ~20@ lookup. Byte-exact by construction: same values.
    # M13-2S rung 3b: entry index -> byte offset (5 bytes per region entry), by dispatch. The
    # multiply it replaces is 9 shifts of w/4 and the append path runs ~1,600 times a frame.
    entoff = (generate_dispatch_table_fj("entoff", [5 * i * DW_BITS for i in range(TS_ECAP + 2)],
                                         index_nibbles=2, result_nibbles=8) if two_sided else "")
    ttang = (generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE),
                                        index_nibbles=3, result_nibbles=8) if lines else "")
    sdrecip = (generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(),
                                          index_nibbles=3, result_nibbles=6) if lines else "")
    slopediv_recip = generate_slopediv_recip_lut_fj("slopediv_recip")   # perf #13
    slopediv_recip8 = generate_slopediv_recip8_lut_fj("slopediv_recip8")  # M13-coarseslope
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

    # M13-bakedbands (the 12M campaign's LUT play): in lines mode EVERY POSSIBLE band list is
    # baked at compile time -- one list per (viewz class) x (height, light, flat-base) key, with
    # the FINAL palette colour folded in (colormap[zrow][base]) and CUMULATIVE absolute y2 per
    # entry -- so the runtime build machinery (build_bands, recip32, built-flags, planeheight)
    # vanishes entirely. Adjacent zrows sharing a final colour merge, so baked lists are also
    # SHORTER than the runtime-built ones (identical pixels). Layout: vpbank +
    # class_idx*(nkeys*130*dw) + key_idx*130*dw; each list = [nA][(y2,colour)xnA] at +0 and the
    # desc half at +65*dw, mirroring the old half-buffer layout.
    # M13-2S rung 3a: does this seg MARK its front sector's planes? One-sided always does; a
    # two-sided one only when its two sides differ in a band-bank key (height, light, flat) --
    # DOOM's R_StoreWallRange markfloor/markceiling test. Equal on both sides => attributing the
    # plane to either sector renders identically, so skipping it is free of error BY CONSTRUCTION.
    def _seg_marks(seg) -> bool:
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return True
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return ((fs_.ceil_h, fs_.light & 0xFF, fs_.ceil_tex.upper())
                != (bs_.ceil_h, bs_.light & 0xFF, bs_.ceil_tex.upper())
                or (fs_.floor_h, fs_.light & 0xFF, fs_.floor_tex.upper())
                != (bs_.floor_h, bs_.light & 0xFF, bs_.floor_tex.upper()))

    def _seg_draws_wall(seg) -> bool:
        """M13-2S rung 3b (ablate "tsfull", measurement only): would this two-sided seg draw an
        upper or a lower wall run? (front ceiling above back ceiling / back floor above front
        floor). "tsfull" routes exactly these through the ONE-SIDED emission path -- full projection,
        scale setup, per-column params, WPX emit -- to price rung 3b's walk+emit BEFORE building it
        (R23/R32: the coarse-cull pre-pass was built before being priced and cost +24.7M). It emits
        FULL-HEIGHT walls instead of upper/lower slices, so it over-emits pixels and does NOT include
        rung 3b's per-column pair BUFFERING: read it as the projection/emit floor, not a bound."""
        ld_ = lds[seg.linedef]
        if ld_.back == -1:
            return False
        fs_ = secs[sds[ld_.front if seg.side == 0 else ld_.back].sector]
        bs_ = secs[sds[ld_.back if seg.side == 0 else ld_.front].sector]
        return fs_.ceil_h > bs_.ceil_h or bs_.floor_h > fs_.floor_h

    def _seg_as_solid(seg) -> bool:
        """Does this seg go down the one-sided (wall-emitting) path?"""
        return lds[seg.linedef].back == -1 or ("tsfull" in ablate and _seg_draws_wall(seg))

    def _seg_in_walk(seg) -> bool:
        """Does the emitted walk do per-seg work for this seg? (the prune predicate's unit)

        ablate "pnearprune" (measurement only): keep the PRE-rung-3a one-sided prune rule while
        still emitting the two-sided claim sites, to price what the wider prune costs. Renders
        wrong (claims inside pruned subtrees are lost) -- never ship it."""
        if "pnearprune" in ablate:
            return lds[seg.linedef].back == -1
        return (_seg_as_solid(seg) or (plane_near and _seg_marks(seg))
                or lds[seg.linedef].back == -1)

    lines_key_ids: dict = {}
    lines_vz_classes: dict = {}
    lines_pid: dict = {}                       # M13-2S rung 3a: (ceil key, floor key) -> pid (1-based)
    lines_bank_keys: list = []                 # the bank's key order (a LIST: pid pairs repeat keys)

    def _plane_keys(sec):
        return ((sec.ceil_h, sec.light & 0xFF, _flatval(sec.ceil_tex), sec.ceil_tex.upper()),
                (sec.floor_h, sec.light & 0xFF, _flatval(sec.floor_tex), sec.floor_tex.upper()))

    if lines:
        for _ss in cmap.subsectors:
            _sec = rm._seg_sector(lds, sds, secs, cmap.segs[_ss.firstseg])
            lines_vz_classes.setdefault(rm.view_z(_sec.floor_h), len(lines_vz_classes))
        for _seg in cmap.segs:
            # M13-2S rung 3a: a marking two-sided seg attributes ITS front sector's planes, so that
            # sector's two band lists must be in the bank too (E1M1: 159 -> 227 distinct keys).
            if not _seg_in_walk(_seg):
                continue
            _ck, _fk = _plane_keys(rm._seg_sector(lds, sds, secs, _seg))
            lines_key_ids.setdefault(_ck, len(lines_key_ids))
            lines_key_ids.setdefault(_fk, len(lines_key_ids))
            if (_ck, _fk) not in lines_pid:
                lines_pid[(_ck, _fk)] = len(lines_pid) + 1     # 1-based: 0 == "not attributed yet"
        # M13-2S rung 3a — the bank LAYOUT. With per-column attribution the emit half has to recover
        # a column's two band lists from ONE byte, so `plane_near` lays the bank out per SECTOR PLANE
        # PAIR (pid): pid p's ceiling list is slot 2(p-1), its floor list 2(p-1)+1, hence
        #   ceil = vzbank + (p-1)*4*half_slots*dw   and   floor = ceil + 2*half_slots*dw
        # -- one mul_const plus adds. The alternative (per-column address cells read back with
        # hex.ptr_index + hex.read_hex 8) measured ~780 dispatches per column, +5M/frame. Keys stop
        # being shared between pids, so the bank grows (E1M1 1.42M -> 1.91M words); without
        # plane_near the layout is EXACTLY the old shared-key one.
        lines_bank_keys = ([k for pair in lines_pid for k in pair] if plane_near
                           else list(lines_key_ids))
    n_bank_keys = max(1, len(lines_bank_keys))

    # M13-prune (lines): count one-sided segs below every subtree; zero => the subtree can be
    # skipped by the main walk entirely (byte-exact -- it would emit nothing and touch nothing).
    # M13-2S rung 3a: two counts now -- `_walk_below` (segs the walk does ANY work for, the compile-
    # time prune) and `_solid_below` (one-sided segs only: zero => the subtree can only ATTRIBUTE
    # planes, so it is dead once `tsstop` and gets the runtime tsstop gate instead).
    lines_walk_below: dict = {}
    lines_solid_below: dict = {}
    if lines:
        def _cnt(child, pred, memo):
            if child & NF_SUBSECTOR:
                _ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
                return sum(1 for _si in range(_ss.firstseg, _ss.firstseg + _ss.numsegs)
                           if pred(cmap.segs[_si]))
            _n = cmap.nodes[child]
            tot = _cnt(_n.left, pred, memo) + _cnt(_n.right, pred, memo)
            memo[child] = tot
            return tot
        import sys as _sys
        _old_rl = _sys.getrecursionlimit()
        _sys.setrecursionlimit(20000)
        _cnt(cmap.root, _seg_in_walk, lines_walk_below)
        _cnt(cmap.root, _seg_as_solid, lines_solid_below)
        _sys.setrecursionlimit(_old_rl)

    def _lines_prune(child):
        if child & NF_SUBSECTOR:
            _ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
            return not any(_seg_in_walk(cmap.segs[_si])
                           for _si in range(_ss.firstseg, _ss.firstseg + _ss.numsegs))
        return lines_walk_below.get(child, 1) == 0

    def _lines_plane_gate(node_i):
        """Node blocks whose subtree holds no one-sided seg: skippable at runtime once tsstop."""
        return lines_solid_below.get(node_i, 1) == 0

    def _lines_descend_leaf(s):
        # the descend pre-walk's landing action: bake this subsector's viewz + band-bank pointer
        _sec = rm._seg_sector(lds, sds, secs, cmap.segs[cmap.subsectors[s].firstseg])
        _vz = rm.view_z(_sec.floor_h)
        return [f"    hex.set 8, viewz, {_vz & 0xFFFFFFFF}",
                f"    hex.set w/4, vzbank, vpbank + "
                f"{lines_vz_classes[_vz] * n_bank_keys * 130}*dw"]

    # M13-W2S: the per-seg wall colour strips (only when the lines mode asks for the W2S tier)
    lines_wstrip_off, lines_wstrip_txt = {}, ""
    if lines and wall_mode == "W2S":
        lines_wstrip_off, lines_wstrip_txt = _lines_wall_strips(
            rm, asset_wad, cmap, lds, sds, secs, wall_mode, colormap, lrow)
    elif lines and wall_mode == "WPX":
        lines_wstrip_off, lines_wstrip_txt = _lines_wall_pix_bank(
            rm, asset_wad, cmap, lds, sds, secs, colormap, verts, cfg.VIEW_H,
            solid=_ts_draws_wall_early if "tsfull" in ablate else None,
            two_sided=_seg_marks if two_sided else None)

    _cid = [0]
    xorby_blocks = {}                                        # M12pp: seg{si}_xorby blocks, emitted once each
    # M13pS2-crush2b: per-seg VISPLANE ids -- segs sharing (plane height, light, flat base) share ONE
    # full-range band list per frame (built on first claim, sliced per column at emit). Keyed on the
    # BAKED triple (planeheight derives from height+runtime viewz identically for equal heights).
    cvp_ids: dict = {}
    fvp_ids: dict = {}

    def subsector_action(s):
        ss = cmap.subsectors[s]
        cid = _cid[0]; _cid[0] += 1
        psec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        viewz_val = rm.view_z(psec.floor_h)
        if lines:
            # M13-prune: viewz/vzbank are set by the descend pre-walk, so leaves carry ONLY the
            # per-seg emission (and empty leaves nothing at all).
            out = []
            for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
                seg = cmap.segs[si]
                ld = lds[seg.linedef]
                if ld.back != -1 and two_sided and not _seg_marks(seg):
                    continue                     # the compile-time cull (DOOM's R_AddLine reject)
                if ld.back != -1 and not _seg_as_solid(seg) and not two_sided:
                    # M13-2S probe (ablate "tsprobe"): walk the DRAWABLE two-sided segs through the
                    # cheap cull only -- GEOM block + pass 1, no emit. This prices the one thing that
                    # decides whether any two-sided emit design can fit the ops ceiling: what it
                    # costs merely to VISIT 1284 segs instead of 432. A two-sided seg whose sectors
                    # share BOTH ceiling and floor can never draw (773 of E1M1's 1482) and is
                    # excluded, exactly as the real implementation will exclude it via a baked flag.
                    # M13-2S rung 3a (ablate "tsmark"): the same probe, but with the cull the PLANE
                    # attribution actually needs. "Can never draw a WALL" (tsprobe) is too strong for
                    # planes: it drops the boundary between two sectors of equal heights but
                    # different flats/lights, which is precisely where the near floor changes
                    # surface -- measured at spawn, tsprobe's cull left 3 flats claiming the near
                    # floor, this one leaves exactly 1. It is DOOM's R_AddLine/R_StoreWallRange
                    # markfloor/markceiling test: skip only when BOTH band-bank keys
                    # (height, light, flat) are equal on the two sides, in which case attributing
                    # the plane to the back sector renders identically anyway.
                    if plane_near:
                        # M13-2S rung 3a — THE REAL THING (not a probe): a marking two-sided seg
                        # attributes the near floor/ceiling surface of the columns it covers. Guarded
                        # by `tsstop` BEFORE the xorby block, so once attribution can no longer
                        # change anything (every column attributed, or the per-frame seg BUDGET spent)
                        # each remaining two-sided seg costs one 1-nibble test -- 1386 of E1M1 spawn's
                        # 1445 land there, and visiting them all costs +11.9M, over the ceiling.
                        # Writes only the attribution state -- never drawn/n_drawn/full.
                        if not _seg_marks(seg) or "pnearwalk" in ablate:
                            continue                     # the compile-time cull (see _seg_marks)
                        _v1x, _v1y = verts[seg.v1]
                        _v2x, _v2y = verts[seg.v2]
                        _sa, _sb, _sc = seg_affine_coeffs(seg, verts)
                        xorby_blocks[si] = _seg_xorby_block(f"{si}T", [
                            ("seg_v1x", 8, (_v1x << 16) & 0xFFFFFFFF),
                            ("seg_v1y", 8, (_v1y << 16) & 0xFFFFFFFF),
                            ("seg_v2x", 8, (_v2x << 16) & 0xFFFFFFFF),
                            ("seg_v2y", 8, (_v2y << 16) & 0xFFFFFFFF),
                            ("seg_a", 8, _sa), ("seg_b", 8, _sb), ("seg_c", 8, _sc),
                            ("seg_pid", 2,
                             lines_pid[_plane_keys(rm._seg_sector(lds, sds, secs, seg))])])
                        out += [f"    hex.if0 1, tsstop, e2go{cid}_{si}",
                                f"    ;e2sk{cid}_{si}",
                                f"  e2go{cid}_{si}:",
                                f"    stl.fcall seg{si}T_xorby, xb_ret",
                                "    stl.fcall seg_pass1_ts_leaf, seg_ret",
                                f"    stl.fcall seg{si}T_xorby, xb_ret",
                                f"  e2sk{cid}_{si}:"]
                        continue
                    if not (ablate & {"tsprobe", "tsmark"}):
                        continue
                    _fs = secs[sds[ld.front if seg.side == 0 else ld.back].sector]
                    _bs = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                    if "tsmark" in ablate:
                        if ((_fs.ceil_h, _fs.light & 0xFF, _fs.ceil_tex.upper())
                                == (_bs.ceil_h, _bs.light & 0xFF, _bs.ceil_tex.upper())
                                and (_fs.floor_h, _fs.light & 0xFF, _fs.floor_tex.upper())
                                == (_bs.floor_h, _bs.light & 0xFF, _bs.floor_tex.upper())):
                            continue
                    elif not (_fs.ceil_h > _bs.ceil_h or _bs.floor_h > _fs.floor_h):
                        continue
                    _v1x, _v1y = verts[seg.v1]
                    _v2x, _v2y = verts[seg.v2]
                    _sa, _sb, _sc = seg_affine_coeffs(seg, verts)
                    xorby_blocks[si] = _seg_xorby_block(f"{si}G", [
                        ("seg_v1x", 8, (_v1x << 16) & 0xFFFFFFFF),
                        ("seg_v1y", 8, (_v1y << 16) & 0xFFFFFFFF),
                        ("seg_v2x", 8, (_v2x << 16) & 0xFFFFFFFF),
                        ("seg_v2y", 8, (_v2y << 16) & 0xFFFFFFFF),
                        ("seg_a", 8, _sa), ("seg_b", 8, _sb), ("seg_c", 8, _sc)])
                    out += [f"    stl.fcall seg{si}G_xorby, xb_ret",
                            "    stl.fcall seg_pass1_leaf, seg_ret",
                            f"    stl.fcall seg{si}G_xorby, xb_ret"]
                    continue
                v1x, v1y = verts[seg.v1]
                v2x, v2y = verts[seg.v2]
                ssec = rm._seg_sector(lds, sds, secs, seg)
                tb, th, tw = seg_texinfo.get(si, (0, 1, 1))
                sa, sb, sc = seg_affine_coeffs(seg, verts)
                # the band-bank key carries the flat NAME too, so M13-FT1 can sample its texels
                ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex),
                        ssec.ceil_tex.upper())
                fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex),
                        ssec.floor_tex.upper())
                # M13-splitxb: GEOM block (part 1's cull inputs) vs REST block (part 2 only) --
                # 375 of 432 walked segs stop in part 1, never paying the rest block's SET+CLEAR.
                gfields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                           ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                           ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc)]
                if two_sided:
                    # M13-2S rung 3b: the seg's own geometry PLUS its back sector's two heights and
                    # its upper/lower WPX blocks. seg_flags nibble 0 = two-sided, 1 = has upper,
                    # 2 = has lower -- all compile-time facts, so the leaf's branches are 1-nibble
                    # tests on baked constants. A one-sided seg bakes zeros for the back fields, and
                    # xor_by of 0 emits nothing, so it costs what it did before.
                    _mid, _up, _lo = lines_wstrip_off[si]
                    _bs = (secs[sds[ld.back if seg.side == 0 else ld.front].sector]
                           if ld.back != -1 else ssec)
                    _two = 1 if ld.back != -1 else 0
                    _hasu = 1 if (_two and ssec.ceil_h > _bs.ceil_h) else 0
                    _hasl = 1 if (_two and _bs.floor_h > ssec.floor_h) else 0
                    rfields = [("seg_segangle", 8, seg.angle),
                               ("seg_wstrip", 4, _mid),          # WPX bank BLOCK INDICES: a
                               ("seg_wsupper", 4, _up),          # buffered region entry carries
                               ("seg_wslower", 4, _lo),          # the index in two bytes
                               ("seg_flags", 3, _two | (_hasu << 4) | (_hasl << 8)),
                               ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                               ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                               ("bceilfix", 8, (_bs.ceil_h << 16) & 0xFFFFFFFF),
                               ("bfloorfix", 8, (_bs.floor_h << 16) & 0xFFFFFFFF),
                               ("seg_pid", 4, lines_pid[_plane_keys(ssec)])]
                    xorby_blocks[si] = (_seg_xorby_block(f"{si}G", gfields)
                                        + _seg_xorby_block(f"{si}R", rfields))
                    out += [f"    stl.fcall seg{si}G_xorby, xb_ret",
                            "    stl.fcall seg_pass1_leaf, seg_ret",
                            f"    hex.if0 1, proceed, e1sk{cid}_{si}",
                            f"    stl.fcall seg{si}R_xorby, xb_ret",
                            "    stl.fcall seg_pass2_leaf, seg_ret2",
                            f"    stl.fcall seg{si}R_xorby, xb_ret",
                            f"  e1sk{cid}_{si}:",
                            f"    stl.fcall seg{si}G_xorby, xb_ret"]
                    continue
                rfields = [("seg_segangle", 8, seg.angle),
                           *([("seg_wstrip", "w/4", f"{lines_wstrip_off[si]}*dw")]
                             if wall_mode in ("W2S", "WPX") else []),
                           ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                           ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                           ("seg_lit", 2, colormap[lrow(ssec.light)][combined[tb]]),
                           # M13-2S rung 3a: the emit half derives both list addresses from the
                           # column's plane-pair id, so ONE 2-nibble bake replaces the two offsets
                           # (and the same byte is what this seg writes when it claims a column).
                           *([("seg_pid", 2, lines_pid[(ckey, fkey)])] if plane_near else
                             [("seg_cvpidx", "w/4", f"{lines_key_ids[ckey] * 130}*dw"),
                              ("seg_fvpidx", "w/4", f"{lines_key_ids[fkey] * 130}*dw")])]
                xorby_blocks[si] = (_seg_xorby_block(f"{si}G", gfields)
                                    + _seg_xorby_block(f"{si}R", rfields))
                # e1sk label keyed by the per-EMISSION counter (cid): _bsp_as_code emits each
                # leaf's action once per parent branch, so seg-index labels would collide (R6m).
                out += [f"    stl.fcall seg{si}G_xorby, xb_ret",
                        "    stl.fcall seg_pass1_leaf, seg_ret",
                        f"    hex.if0 1, proceed, e1sk{cid}_{si}",
                        f"    stl.fcall seg{si}R_xorby, xb_ret",
                        "    stl.fcall seg_pass2_leaf, seg_ret2",
                        f"    stl.fcall seg{si}R_xorby, xb_ret",
                        f"  e1sk{cid}_{si}:",
                        f"    stl.fcall seg{si}G_xorby, xb_ret"]
            if out:
                out = ([f"    hex.if0 1, full, e1sact{cid}", f"    ;e1sskip{cid}", f"  e1sact{cid}:"]
                       + out + [f"  e1sskip{cid}:"])
            return out
        # player-subsector setup (runs only at the FIRST subsector visited = order[0] = the player's): set the
        # runtime viewz (player sector floor + VIEWHEIGHT) that every seg's worldtop + ceil/floor planeheight use.
        out = [
            f"    hex.if0 1, vz_set, e1pset{cid}",
            f"    ;e1psegs{cid}",
            f"  e1pset{cid}:",
            f"    hex.set 8, viewz, {viewz_val & 0xFFFFFFFF}",
            f"    hex.set 8, viewzw, {(viewz_val >> 16) & 0xFFFFFFFF}",
            # M13-proj: the device's positional framing expects viewz right after the 8-byte header,
            # before any seg id -- the first visited subsector's block runs before its segs emit.
            *(["    stream.emit_bytes4 viewz"] if projm else []),
            # M13-bakedbands: aim the frame's band-list bank at this subsector's viewz class
            *([f"    hex.set w/4, vzbank, vpbank + "
               f"{lines_vz_classes[viewz_val] * n_bank_keys * 130}*dw"] if lines else []),
            "    hex.set 1, vz_set, 1",
            f"  e1psegs{cid}:",
        ]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            v1x, v1y = verts[seg.v1]
            v2x, v2y = verts[seg.v2]
            sd = sds[ld.front if seg.side == 0 else ld.back]
            texoff = (seg.offset + sd.x_off) << 16
            ssec = rm._seg_sector(lds, sds, secs, seg)
            tb, th, tw = seg_texinfo[si]
            sa, sb, sc = seg_affine_coeffs(seg, verts)   # perf #9: baked affine rw_distance coeffs (SSOT)
            if projm:
                # M13-proj: the leaf only needs the wedge + back-face inputs and the wire id --
                # everything else lives in the device-resident geometry table.
                fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                          ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                          ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc),
                          ("seg_sid", 4, proj_sid[si])]
                xorby_blocks[si] = _seg_xorby_block(si, fields)
                out += _seg_xorby_use(si)
                continue
            fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                      ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                      ("seg_segangle", 8, seg.angle), ("seg_a", 8, sa), ("seg_b", 8, sb), ("seg_c", 8, sc),
                      ("seg_texoff", 8, texoff & 0xFFFFFFFF),
                      ("seg_texbase", 5, tb), ("seg_texheight", 4, th), ("seg_tw", 8, tw),
                      ("seg_hm", 3, th - 1), ("seg_light", 2, lrow(ssec.light)),
                      ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                      ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                      ("seg_ceil", 8, ssec.ceil_h & 0xFFFFFFFF),   # M12pp: worldtop = seg_ceil - viewzw in-leaf
                      ("seg_floor", 8, ssec.floor_h & 0xFFFFFFFF),  # M13c3: floor planeheight = |floor_h<<16 - viewz|
                      ("seg_plight", 2, ssec.light & 0xFF),         # RAW sector light (zlight does >>4)
                      ("seg_ceilbase", 5, _flatval(ssec.ceil_tex)),   # M13d2 slice offset / M13p1 base index
                      ("seg_floorbase", 5, _flatval(ssec.floor_tex))]
            if stream or raster or lines:
                # M13pS2c: the W1 wall's lit colour is fully constant (one texel, one light row) --
                # bake the FINAL palette byte at Python emit time (no runtime colormap lookup at all).
                fields.append(("seg_lit", 2, colormap[lrow(ssec.light)][combined[tb]]))
                # M13pS2-crush2b: the seg's ceiling/floor visplane indices (shared band lists in
                # stream mode; shared device-side row->colour arrays in raster mode)
                # M13-lines2: lines mode keys visplanes on (height, light) ONLY -- the flat
                # base colour is applied at emit time from the seg's own register, so planes
                # differing only in flat share one band list.
                if lines:
                    # baked DW-OFFSETS into the frame's viewz bank (list stride 130 dw)
                    ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex),
                            ssec.ceil_tex.upper())
                    fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex),
                            ssec.floor_tex.upper())
                    fields.append(("seg_cvpidx", "w/4", f"{lines_key_ids[ckey] * 130}*dw"))
                    fields.append(("seg_fvpidx", "w/4", f"{lines_key_ids[fkey] * 130}*dw"))
                else:
                    ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex),
                            ssec.ceil_tex.upper())
                    fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex),
                            ssec.floor_tex.upper())
                    fields.append(("seg_cvpidx", 8, cvp_ids.setdefault(ckey, len(cvp_ids))))
                    fields.append(("seg_fvpidx", 8, fvp_ids.setdefault(fkey, len(fvp_ids))))
            if lines:
                fields = [f for f in fields if f[0] not in _LINES_DEAD_FIELDS]
            xorby_blocks[si] = _seg_xorby_block(si, fields)
            out += _seg_xorby_use(si)
        if stream or raster or lines:
            # M13pG1: skip the whole action (incl. every seg's xorby SET/CLEAR pair) once the screen
            # is full -- the leaf would fret per seg anyway, but the involution flips aren't free.
            out = ([f"    hex.if0 1, full, e1sact{cid}", f"    ;e1sskip{cid}", f"  e1sact{cid}:"]
                   + out + [f"  e1sskip{cid}:"])
        return out

    bsp = _bsp_as_code(_pfx(mapname), cmap, done_label="bsp_done", subsector_action=subsector_action,
                       full_abort_label="full" if (stream or raster or lines) else None,   # M13pG1
                       # inline_side=True measured +0.42M on E1M1 (code bloat beats the
                       # fcall savings -- the layout tax again); kept available, OFF.
                       prune=_lines_prune if lines else None, inline_side=False,
                       plane_gate=_lines_plane_gate if (lines and plane_near) else None,
                       plane_gate_label="tsstop")
    if lines:
        bsp += _bsp_descend_code(_pfx(mapname), cmap, _lines_descend_leaf, done_label="dsc_done")
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # the shared per-seg xorby blocks (once)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        # M13-absmul: per-frame |viewx|/|viewy| + sign flags. fixed_mul_lo's cost is one schoolbook
        # row per nonzero nibble of the MULTIPLIER, and a negative 16.16 view coord sign-extends to
        # a dense pattern -- so the per-seg affine cull multiplies by these sparse abs values and
        # negates the product on the flag (bit-identical; see proj.wall_x_range).
        "hex.mov 8, viewxa, viewx", "hex.set 1, viewxs, 0", "hex.sign 8, viewxa, wxn, wxp",
        "wxn:", "hex.neg 8, viewxa", "hex.set 1, viewxs, 1", "wxp:",
        "hex.mov 8, viewya, viewy", "hex.set 1, viewys, 0", "hex.sign 8, viewya, wyn, wyp",
        "wyn:", "hex.neg 8, viewya", "hex.set 1, viewys, 1", "wyp:",
        "hex.zero 2, n_drawn", "hex.zero 1, full",   # M13opt-P1: reset the drawn-column counter + full flag per frame
    ]
    if stream or raster:
        # M13pS2-crush2b: per-frame reset of the visplane built-flags (compile-time-unrolled zeroing)
        pass1 += [f"rep({max(1, len(cvp_ids))}, v) hex.zero 1, vpc_flags + v*dw",
                  f"rep({max(1, len(fvp_ids))}, v) hex.zero 1, vpf_flags + v*dw"]
    # M13-bakedbands: lines mode has NO per-frame band state to reset (the lists are static data)
    if raster:
        # M13-wedge: the per-frame half-plane descriptors for the conservative FOV pre-cull (the
        # outward-rounded 45-degree wedge that strictly contains the FOV). Once per frame; the
        # per-seg test that uses them is multiply-free.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1.append("present.begin_frame_raster")   # M13-raster: starts the per-frame record stream;
                                                       # the walk below emits vp/seg records INLINE
    if projm:
        # M13-proj: same per-frame wedge descriptors, then the 0x0F frame + the positional 8-byte
        # header (viewx/viewy as signed 16-bit map units -- exactly the parsed vx/vy low bytes --
        # then the 4-byte viewangle); viewz follows from the player-subsector block inside the walk.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1 += ["present.begin_frame_proj",
                  "byte.emit vx", "byte.emit vx + 2*dw",
                  "byte.emit vy", "byte.emit vy + 2*dw",
                  "stream.emit_bytes4 viewangle"]
    if lines:
        # M13-lines: wedge descriptors, the descend pre-walk (viewz + band bank), then the 0x0B
        # frame opens BEFORE the walk -- the leaf emits records inline at column-claim time.
        pass1.append("proj.wedge_setup wqa, wna, wqb, wnb, wex, wey, weyx, wexy, viewangle, viewx, viewy")
        pass1 += [f";{_pfx(mapname)}_dsc_walk", "dsc_done:"]
        if wall_mode == "W2S":
            pass1.append("hex.set w/4, wstripbase, wstrips")
        elif wall_mode == "WPX":
            pass1.append("hex.set w/4, wstripbase, wpxstrips")
        pass1.append("present.begin_frame_collines")
    if "pass1" in ablate:                              # M13p0: skip the walk entirely (residue-only measurement)
        pass1.append("bsp_done:")
    else:
        pass1 += [f";{_pfx(mapname)}_bspcode_walk", "bsp_done:"]
    pass2 = []                                            # pass 2a: walls (M12oo shared-compare trampoline)
    if "pass2" not in ablate and not (stream or raster or projm or lines):   # M13p0 ablate / M13pS2: stream/raster have NO fb raster
        for x in range(cfg.VIEW_W):
            pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                         f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                         f"col_heightmask + {8 * x}*dw")
            for y in range(cfg.H):                                # M12oo: the shared-compare trampoline (y runtime)
                pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")
    # pass 2b: floor/ceiling visplanes (M13d2) — the per-frame clear_planes seeds + the runtime per-ROW
    # R_MakeSpans textured span pass (replaces the M13c3 per-column plane_tramp unroll).
    plane_pass = []
    if two_sided and "noflush" not in ablate:
        # M13-2S rung 3b: the record assembler. One unrolled pass over the columns AFTER the walk --
        # the walk cannot emit any more, because a column's pairs arrive from both ends.
        plane_pass = [f"stream.flush_frame {cfg.VIEW_W}, {TS_ECAP}, colst, colbuf"]
    if "planes" not in ablate and not (stream or raster or projm or lines):   # M13pS2/raster: planes render via bands/device instead
        plane_pass = ["stl.fcall clear_leaf, clear_ret",
                      f"frame.render_planes_spans {cfg.VIEW_W}, {cfg.VIEW_H}"]

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    distscale = generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N)

    # M13pS2: the stream present -- the frame leaves the program AS the emitted run bytes (device
    # DMA decode); one unrolled emit_column per screen column, every col_* read at a compile-time
    # address. Replaces update_screen_reg + the whole fb/pass-2/plane-pass raster.
    # M13-planesproto: the frame leaves as SHARED per-visplane band lists (each entry's colour
    # cm.emit-mapped ONCE) + one 5-byte record per column -- the device does the per-column
    # prefix/suffix clipping that stream.emit_column paid ~15M fj ops/frame for.
    # col_struct's per-column stride is 11 dw: offset 0 = drawn (packed byte, not read here),
    # 1-10 = cexcl/fstart/lit/cvp/fvp each a 2-nibble-vec pair -- the emit reads each pair's LOW-nibble
    # address (idx/idx+1*dw are its two nibbles).
    _cell = lambda x: (f"col_struct + {11 * x + 1}*dw, col_struct + {11 * x + 3}*dw, "
                       f"col_struct + {11 * x + 5}*dw, col_struct + {11 * x + 7}*dw, col_struct + {11 * x + 9}*dw")
    if raster_mode == "stream":
        present_tail = ["present.begin_frame_planes",
                        f"stl.output_char {max(1, len(cvp_ids))}",
                        f"stream.emit_vp_bank vpc_bufs, {max(1, len(cvp_ids))}, {BAND_STRIDE}",
                        f"stl.output_char {max(1, len(fvp_ids))}",
                        f"stream.emit_vp_bank vpf_bufs, {max(1, len(fvp_ids))}, {BAND_STRIDE}",
                        *(f"stream.emit_column_rec {_cell(x)}" for x in range(cfg.VIEW_W))]
    elif raster_mode == "spans":
        # M13-spanfill: the DUMB-screen present -- fj does the per-column clip itself and emits explicit
        # fillCol [x][y1][y2][colour] records over 0x0A; the device just fills straight vertical strips.
        # Terminated by ONE 0xFF-x sentinel record (VIEW_W=160 < 0xFF, so x is never 0xFF for real).
        present_tail = ["present.begin_frame_spans",
                        *(f"stream.emit_column_spans {x}, {_cell(x)}, vpc_bufs, vpf_bufs, "
                          f"{BAND_STRIDE}" for x in range(cfg.VIEW_W)),
                        "stl.output_char 0xFF"]
    elif raster:
        # M13-raster: the per-seg/per-visplane records were ALREADY emitted inline during the walk
        # (present.begin_frame_raster was prepended to pass1, before the walk jump); present_tail here
        # is JUST the frame terminator (a seg record's own x1 is always < RASTER_TAG_FLOOR_VP=0xFD, so
        # 0xFF can never collide with real data).
        present_tail = ["stl.output_char 0xFF"]
    elif projm:
        # M13-proj: seg ids were emitted inline during the walk; the terminator is [0xFF][0xFF]
        # (a compact id's hi byte is never 0xFF).
        present_tail = ["stl.output_char 0xFF", "stl.output_char 0xFF"]
    elif lines:
        # M13-lines: fillCol records were emitted inline during the walk; one 0xFF x-sentinel
        # ends the frame (x is never 0xFF for real: VIEW_W = 160).
        present_tail = ["stl.output_char 0xFF"]
    else:
        present_tail = ["present.update_screen_reg framebuffer"]
    fb_leaves = [] if (stream or raster or projm or lines) else [          # the fb-raster shared leaves -- stream/raster emit none
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "span_leaf:",
        (f"plane.draw_span framebuffer, {cfg.VIEW_W}" if floor_mode == "textured"      # M13d2 textured u,v span
         else f"plane.draw_span_flat framebuffer, {cfg.VIEW_W}"),                      # M13p1 flat-colored span
        "clear_leaf:", f"plane.clear_planes {cfg.CENTERX << 16}, {ANG90}",  # M13d2 per-frame R_ClearPlanes seeds
    ]
    # M13-hotdata (stream only, R20): pointer-deref/dispatch wflip cost scales with the ADDRESS's
    # set bits, so the hot pointer-walked data (per-visplane band buffers, the packed LUTs, the
    # cm/byte EMIT tables) moves from the ~20M-word program tail to just after startup, behind a
    # jump guard (the static tables' own `;end` headers only matter on fall-through, which the
    # guard prevents). Measured: 78.54M -> 76.39M ops/frame, frame byte-identical.
    if stream:
        hotdata = ([";__hot_end"]
                  + _stream_mode_decls(cfg, max(1, len(cvp_ids)), max(1, len(fvp_ids)))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, "__hot_end:"])
    elif raster:
        hotdata = ([";__hot_end"]
                  + _raster_mode_decls(cfg, asset_wad, max(1, len(cvp_ids)), max(1, len(fvp_ids)))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, "__hot_end:"])
    elif projm:
        hotdata = ([";__hot_end"]
                  + _proj_mode_decls(cfg, asset_wad, proj_geom_txt)
                  + [cm, "__hot_end:"])
    elif lines:
        hotdata = ([";__hot_end"]
                  + _lines_mode_decls(cfg, rm, asset_wad, lines_vz_classes, lines_bank_keys,
                                      wall_mode in ("W2S", "WPX"))
                  + [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle,
                     tex, cm, ttang, sdrecip, entoff, "__hot_end:"])
    else:
        hotdata = []
    # M13-raster: the walk EMITS records inline (present.begin_frame_raster is prepended to pass1,
    # before the walk jump), so present.set_palette + the NEW load_raster_tables address handoff MUST
    # run before pass1 -- otherwise their command bytes would land INSIDE the interleaved raster
    # stream and corrupt it (every other mode buffers-then-emits in present_tail, safely after
    # set_palette). All other modes keep set_palette in its original post-pass1 position.
    if raster:
        yslope_packed_addr, zlight_packed_addr, colormap_packed_addr = (
            "yslope_packed", "zlight_packed", "colormap_packed")
        prelude = ["present.set_palette palette",
                  f"present.load_raster_tables {yslope_packed_addr}, {zlight_packed_addr}, {colormap_packed_addr}"]
        postlude_palette = []
    elif projm:
        # M13-proj: same inline-emission constraint as raster -- palette + BOTH DMA handoffs must
        # precede pass1's begin_frame_proj.
        prelude = ["present.set_palette palette",
                  "present.load_raster_tables yslope_packed, zlight_packed, colormap_packed",
                  f"present.load_proj_tables seg_geom, {len(proj_sid)}"]
        postlude_palette = []
    elif lines:
        # M13-lines: inline emission during the walk => palette must precede pass1.
        prelude = ["present.set_palette palette"]
        postlude_palette = []
    else:
        prelude = []
        postlude_palette = ["present.set_palette palette"]
    main = "\n".join([
        "stl.startup_and_init_all",
        *hotdata,
        "present.init_screen_stream 0" if (stream or raster or projm or lines) else "present.init_screen",
        *prelude,
        *pass1, *pass2, *plane_pass,
        *postlude_palette, *present_tail, "stl.loop",
        "bad: stl.loop",
        *fb_leaves,
        *((["seg_pass1_leaf:", "stl.fret seg_ret"]
           + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "segstub" in ablate else
          # M13-wedge attribution: segstub + the wedge test only. (segstub - wedgestub)/segs gives the
          # test's true in-context unit cost; both walk the WHOLE tree (`full` is never set).
          (["seg_pass1_leaf:",
            "proj.wedge_reject wrej, seg_v1x, seg_v1y, seg_v2x, seg_v2y, wqa, wna, wqb, wnb, wex, wey, weyx, wexy",
            "stl.fret seg_ret"]
           + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "wedgestub" in ablate else
          (["seg_pass1_leaf:", "hex.if0 1, full, xrs_work", "stl.fret seg_ret",
            "xrs_work:", "hex.zero 1, visible", "stl.fret seg_ret"]
           # lines mode fcalls a pass-2 leaf too, so the stub ladder has to define one (it is never
           # reached: part 1 always leaves `proceed` = 0 here).
           + (["seg_pass2_leaf:", "stl.fret seg_ret2"] if lines else [])) if "xrstub" in ablate else
          ["seg_pass1_leaf:", f"frame.seg_pass1_leaf_body_raster {proj}"]
          if raster else
          ["seg_pass1_leaf:", "frame.seg_pass1_leaf_body_proj"]
          if projm else
          ["seg_pass1_leaf:", f"frame.seg_pass1_leaf_body_lines {atan_dbl}, {slope_dbl}, {table_dbl}, "
           f"{1 if 'noprescan' in ablate else 0}",
           *(["expand_leaf:",
              f"stream.entry_expand_body {cfg.CENTERY}, {LINES_HALF_SLOTS}, "
              f"{2 * WPX_RUN_CAP}, {(cfg.VIEW_H + 1) * 2 * WPX_RUN_CAP}"] if two_sided else []),
           *(["seg_pass1_ts_leaf:",
              f"frame.seg_pass1_leaf_body_ts {PNEAR_SEG_BUDGET}, {atan_dbl}, {slope_dbl}, "
              f"{table_dbl}"] if plane_near else []),
           "seg_pass2_leaf:",
           (f"frame.seg_pass2_leaf_body_2s {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, "
            f"{LINES_HALF_SLOTS}, {TS_ECAP}, {1 if 'colstub' in ablate else 0}") if two_sided else
           (f"frame.seg_pass2_leaf_body_lines {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, "
            f"{LINES_HALF_SLOTS}, {w2s_flag}, {wpx_flag}, {2 * WPX_RUN_CAP}, {pnear_flag}, "
            f"{eabl_flag}, {1 if 'noproj' in ablate else 0}")]
          if lines else
          ["seg_pass1_leaf:",
           f"frame.seg_pass1_leaf_body_stream {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, {BAND_STRIDE}"]
          if stream else
          ["seg_pass1_leaf:",
           f"frame.seg_pass1_leaf_body_mtlwp {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}"]),
        # the stub ablations replace the lines leaves wholesale, so the two-sided claim leaf the
        # plane_near call sites jump to has to be stubbed alongside them (measurement only).
        *(["seg_pass1_ts_leaf:", "stl.fret seg_ret"]
          if (plane_near and (ablate & {"segstub", "xrstub", "wedgestub"})) else []),
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        *([] if (stream or raster or projm or lines) else [f"framebuffer: hex.vec {2 * cfg.FB_SIZE}"]),   # no fb in stream/raster/proj mode
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        # M13-absmul: the per-frame abs/sign forms of the view coords + the shared affine-distance
        # output of wall_x_range (consumed by wall_setup_sgn as rw_distance-pre-abs)
        "viewxa: hex.vec 8", "viewxs: hex.vec 1", "viewya: hex.vec 8", "viewys: hex.vec 1",
        "sgn_aff: hex.vec 8",
        "viewz: hex.vec 8", "viewzw: hex.vec 8", "vz_set: hex.vec 1",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_a: hex.vec 8", "seg_b: hex.vec 8", "seg_c: hex.vec 8",  # perf #9
        "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: xorby block fcall/fret return register
        "ceilfix: hex.vec 8", "floorfix: hex.vec 8",
        "seg_ceil: hex.vec 8", "worldtop: hex.vec 8",     # M12pp: seg_ceil baked (pure); worldtop leaf-computed
        "seg_floor: hex.vec 8", "seg_plight: hex.vec 2",  # M13d2 plane bakes (pure floor_h + raw light + flat slices)
        "seg_ceilbase: hex.vec 5", "seg_floorbase: hex.vec 5",   # 5-nib flat slice offsets
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 5",
        "seg_ret: ;0",
        "top: hex.vec 8", "bottom: hex.vec 8",
        "y: hex.vec 2", "ret_reg: ;0",                    # M12oo trampoline: runtime row counter + shared return reg
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 5", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 5", "step: hex.vec 4",
        "heightmask: hex.vec 3", "pixel_ret: ;0",
        # M13d2 pass-2b textured-plane registers (render_planes_spans sets these per span; draw_span reads them)
        "planeheight: hex.vec 8", "light: hex.vec 2", "flatbase: hex.vec 5",
        "basexscale: hex.vec 8", "baseyscale: hex.vec 8",   # per-frame R_ClearPlanes seeds (clear_leaf)
        "span_ret: ;0", "clear_ret: ;0",
        # M13opt2 span-scan state + classify scratch (globals shared by render_planes_spans + plane_col)
        "inspan: hex.vec 1", "spanR: hex.vec 2", "spanph: hex.vec 8", "spanfb: hex.vec 5",
        "spanlt: hex.vec 2", "spanx1: hex.vec 2", "cR: hex.vec 2", "cph: hex.vec 8", "cfb: hex.vec 5",
        "clt: hex.vec 2", "cexcl: hex.vec 2", "fstart: hex.vec 2",
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 8, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        # M13c3 per-column plane param arrays (8-nibble stride, written by store_col_field/8)
        f"col_cexcl: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_fstart: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_ceil_ph: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_floor_ph: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_plight: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_ceilbase: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_floorbase: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        # M13-raster/lines declare their OWN packed-byte `drawn` (stride 1, in their hotdata decls)
        # -- this shared nibble-vec (stride 4) declaration is for fb-mode/stream-mode only.
        *([] if (raster or lines) else [f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0"]),
        # M13opt-P1 byte-exact early-out: count claimed columns; `full` short-circuits later (occluded) segs.
        "n_drawn: hex.vec 2", "full: hex.vec 1", f"vieww: hex.vec 2, {cfg.VIEW_W}",
        # M13-2S rung 3a: the per-column PLANE ATTRIBUTION state -- ONE byte per column holding the
        # claiming seg's plane-pair id (0 = not attributed yet), a stride-1 packed-byte array walked
        # in lockstep with `drawn`. `tsstop` = attribution can no longer change (every column done,
        # or the seg budget spent) -- the early-out that makes
        # the extra two-sided walk affordable.
        # M13-2S rung 3b: per column [chi][flo][tcnt][bcnt] (the window's exclusive-end row bounds
        # and the bytes used in its two pair buffers), plus the buffers themselves -- tcap bytes of
        # TOP pairs then bcap of BOTTOM blocks. A column can never hold more than VIEW_H pairs in
        # total (each pair advances the fill cursor by >= 1 row), so 2*VIEW_H bytes per side plus a
        # length trailer per block is a hard bound, not a guess.
        *([f"colst:{NLJ}" + NLJ.join(NLJ.join([";0x0 * dw", f";{cfg.VIEW_H:#x} * dw",
                                               ";0x0 * dw", ";0x0 * dw"])
                                     for _ in range(cfg.VIEW_W)),
           f"colbuf:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W * 10 * TS_ECAP)),
           "cstp: hex.vec w/4", "cbfp: hex.vec w/4", "tptr: hex.vec w/4", "bptr: hex.vec w/4",
           "chi: hex.vec 2", "flo: hex.vec 2", "tcnt: hex.vec 2", "bcnt: hex.vec 2",
           "bcnt0: hex.vec 2", "seg_flags: hex.vec 3",
           "bceilfix: hex.vec 8", "bfloorfix: hex.vec 8",
           "seg_wsupper: hex.vec 4", "seg_wslower: hex.vec 4",
           "eptr: hex.vec w/4", "exp_ret: ;0",
           "cbufa: hex.vec w/4", "cbufd: hex.vec w/4",
           "fbufa: hex.vec w/4", "fbufd: hex.vec w/4"] if two_sided else []),
        *([f"pclm:{NLJ}" + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W)),
           "pbase: hex.vec w/4", "pptr: hex.vec w/4", "pval8: hex.vec 2",
           "n_claimed: hex.vec 2", "n_tsv: hex.vec 2", "tsstop: hex.vec 1",
           "viewh_stub: hex.vec 2, 100",
           "cpid: hex.vec 2",
           # the UNATTRIBUTED-COLUMN WINDOW: every column < pmin or > pmax is attributed already
           "pmin: hex.vec 2, 0", f"pmax: hex.vec 2, {cfg.VIEW_W - 1}"] if lines else []),
        *([_lines_bake_bank(rm, cfg, asset_wad, lines_vz_classes, lines_bank_keys,
                            floor_mode == "FT1")] if lines else []),
        *([lines_wstrip_txt] if lines_wstrip_txt else []),
        *([] if (stream or raster or projm or lines) else      # M13-hotdata: in stream/raster/proj mode these sit up front
          [tantoangle, slopediv_recip, slopediv_recip8, finesine, finetangent, viewangletox, xtoviewangle, tex, cm]),
        palette,
        yslope, zlight, distscale, flat_table,        # M13d2 textured-floor LUTs + combined flat table
    ])
    return main


def _raster_mode_decls(cfg, asset_wad, nvpc: int, nvpf: int) -> list[str]:
    """M13-raster: the raster_mode="raster" per-frame scratch + the THREE static tables the DEVICE
    DMA-reads once via `present.load_raster_tables` (yslope_packed/zlight_packed/colormap_packed --
    all raw PACKED BYTE, 1 dw-slot/entry, exactly what `InMemoryScreen._read_packed_bytes` expects;
    NOT the nibble-vec forms `generate_yslope_lut_fj`/`generate_zlight_lut_fj` emit for fb/stream mode's
    OWN in-fj read_table use). No band buffers, no col_struct -- build_bands and the whole per-column
    param/store machinery are GONE from fj; `drawn` is a lone packed byte per column (colstruct-style,
    stride 1) used only for the walk's until-full abort + the occlusion pre-scan, never emitted (so it
    stays packed-byte, unlike col_struct's emit'd fields which had to be nibble-vec, R21)."""
    return [
        "seg_lit: hex.vec 2",                          # the W1 wall's fully-baked constant lit byte
        "seg_cvpidx: hex.vec 8", "seg_fvpidx: hex.vec 8",   # the seg's visplane indices (baked)
        # M13-wedge: the conservative FOV pre-cull's per-frame half-plane descriptors + per-seg verdict
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
        "drawn:\n" + "\n".join(";0 * dw" for _ in range(cfg.VIEW_W)),
        f"vpc_flags: rep({nvpc}, i) hex.vec 1, 0", f"vpf_flags: rep({nvpf}, i) hex.vec 1, 0",
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
        generate_zlight_packed_lut_fj("zlight_packed", cfg.VIEW_W, COLORMAP_LIGHTS),
        generate_colormap_packed_table_fj("colormap_packed", asset_wad, lights=COLORMAP_LIGHTS),
    ]


def _proj_mode_decls(cfg, asset_wad, seg_geom_txt: str) -> list[str]:
    """M13-proj (Path B lab mode): the per-frame scratch + the DEVICE-resident tables -- the same
    three packed shade tables as raster mode (0x0C) plus the static per-seg geometry table (0x0E,
    30 B/row via mapcompiler._bytes_stream; stream_screen.PROJ_ROW_BYTES matches). No drawn[], no
    vp flags, no col_struct: fj emits only 2-byte seg ids."""
    return [
        "seg_sid: hex.vec 4",                          # the seg's compact wire id (baked per seg)
        # the wedge pre-cull's per-frame half-plane descriptors + per-seg verdict (shared w/ raster)
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
        seg_geom_txt,
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
        generate_zlight_packed_lut_fj("zlight_packed", cfg.VIEW_W, COLORMAP_LIGHTS),
        generate_colormap_packed_table_fj("colormap_packed", asset_wad, lights=COLORMAP_LIGHTS),
    ]


LINES_HALF_SLOTS = 1 + 2 * (MAX_BANDS // 2)   # per half-window list: [count] + <=32 x 2-byte pairs


def _lines_bake_bank(rm, cfg, asset_wad, vz_classes: dict, key_ids: dict,
                     ft1: bool = False) -> str:
    """M13-bakedbands: the compile-time band-list bank. For every (viewz class, (h,light,base))
    pair, both half-window lists ([0,centery) asc + [centery,H) desc) with entries
    [y2_absolute:1B][final_colour:1B], grouped by FINAL colour (adjacent zrows sharing a colour
    merge -- identical pixels, fewer pairs). Values from the SAME host walk the fj runtime build
    mirrored (rm._zidx_band_walk + zlight + colormap), so frames are byte-identical to the
    runtime-built ones. Layout: list (class,key) at (class*len(keys)+key)*130 dw; asc half at +0
    ([n][pairs]), desc half at +65 dw."""
    from doomfj.fixedpoint import _signed as _sgn
    colormap = asset_wad.colormap()
    flatcache: dict = {}
    H, CY = cfg.VIEW_H, cfg.CENTERY
    half = LINES_HALF_SLOTS
    out = [f"// M13-bakedbands: {len(vz_classes)} viewz classes x {len(key_ids)} keys, 130 dw/list",
           "vpbank:"]
    for vz in vz_classes:                                    # insertion order == class index
        vzs = _sgn(vz, 32)
        for (h, light, base, flatname) in key_ids:            # insertion order == key index
            ph = abs((h << 16) - vzs)
            lvl = max(0, min(15, light >> 4))
            # M13-FT1: the flat's DIAGONAL texels -- band ordinal j takes texel strip[j & 63]
            # instead of every band sharing the flat's single base texel. Costs ZERO runtime ops
            # (it only changes which byte is baked), and gives the floor real depth-varying texel
            # colour on top of the distance shading. Sampling by band ORDINAL (not world u,v) is
            # what keeps it free -- see docs/plan-w2-ft1.md for the honest scope statement.
            strip = None
            if ft1:
                tx = rm._flat_texels(asset_wad, flatname, flatcache)
                strip = [tx[(i * 64 + i) % len(tx)] for i in range(64)]
            for rows in (list(range(0, CY)), list(range(CY, H))):
                zidx = rm._zidx_band_walk(ph, rows)
                zrows = [rm.zlight[lvl][z] for z in zidx]
                pairs, ordinal, prev_z = [], 0, None
                for k, zr in enumerate(zrows):
                    y2 = rows[k] + 1
                    if prev_z is not None and zr != prev_z:
                        ordinal += 1
                    prev_z = zr
                    colr = (colormap[zr][strip[ordinal & 63]] if ft1 else colormap[zr][base])
                    if pairs and pairs[-1][1] == colr:
                        pairs[-1][0] = y2
                    else:
                        pairs.append([y2, colr])
                assert len(pairs) <= MAX_BANDS // 2, f"half list overflow: {len(pairs)}"
                cell = [len(pairs)] + [b for pr in pairs for b in pr]
                for b in cell:
                    out.append(f";{b:#x} * dw")
                for _ in range(half - len(cell)):
                    out.append(";0 * dw")
    return NLJ.join(out) + NLJ


def _lines_wall_strips(rm, asset_wad, cmap, lds, sds, secs, wall_mode, colormap, lrow):
    """M13-W2S: per-seg RUN-MERGED wall colour strips + their bank text.

    Each one-sided seg's 16-texel strip (the shared `_tiny_wall_canvas` reduction, R6) is
    colormapped at its sector's light level and then run-merged into entries
    `[cum_band:1][colour:1]` -- cum_band is the CUMULATIVE band index (1..16) at which the colour
    changes, so the emit computes `y2 = top + ((cum*h) >> 4)` with no divide. Segs whose strip is
    one flat colour (83 of 575 on E1M1) collapse to a single entry, i.e. exactly today's W1 cost.
    Returns (offsets_by_seg, bank_text); STRIDE dw per seg keeps the offsets baked constants."""
    STRIDE = 1 + 2 * 16                       # [n][ (cum,colour) x <=16 ]
    cache = {}
    off_by_seg, lines_out, k = {}, ["// M13-W2S: per-seg run-merged wall colour strips", "wstrips:"], 0
    for si, seg in enumerate(cmap.segs):
        if lds[seg.linedef].back != -1:
            continue
        sd = sds[lds[seg.linedef].front if seg.side == 0 else lds[seg.linedef].back]
        sec = rm._seg_sector(lds, sds, secs, seg)
        lr = lrow(sec.light)
        tex = rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=wall_mode)
        if tex is None:
            cols = [colormap[lr][WALL_BG]]
        else:
            texels, th, _tw = tex
            cols = [colormap[lr][texels[i]] for i in range(min(16, len(texels)))]
        runs = []
        for j, c in enumerate(cols):
            if runs and runs[-1][1] == c:
                runs[-1][0] = j + 1
            else:
                runs.append([j + 1, c])
        runs[-1][0] = 16                      # the last run always reaches the wall bottom
        off_by_seg[si] = k * STRIDE
        body = [len(runs)] + [b for r in runs for b in r]
        for b in body:
            lines_out.append(f";{b:#x} * dw")
        for _ in range(STRIDE - len(body)):
            lines_out.append(";0 * dw")
        k += 1
    return off_by_seg, NLJ.join(lines_out) + NLJ


def _lines_wall_pix_bank(rm, asset_wad, cmap, lds, sds, secs, colormap, verts, view_h,
                         cap: int = WPX_RUN_CAP, solid=None, two_sided=None):
    """M13-WPX: the fully-baked 1×1 wall bank + its per-seg block offsets.

    One BLOCK per distinct (wall texture, seg light level, sector wall span) — 575 E1M1 segs collapse
    to ~185 blocks, since those three determine every column the seg can ever draw. A block holds one
    run-list per possible wall height h (0..view_h) at a UNIFORM stride of `2*cap` words, so the
    fj emit indexes it with a single `mul_const` by the height: no offset table, no search.

    Each list is `[(rel, colour) × n][0][last_colour]` where `rel` is the run's end row measured
    from the wall's top. The final run always ends exactly at the wall bottom, which fj already
    holds, so its `rel` is never stored — which frees `rel == 0` to be the list TERMINATOR (every
    real run ends at row >= 1), so the fj loop needs no counter and no per-run compare. Baking per
    EXACT height is what makes this true 1×1: every boundary is pixel-exact, and a short wall's list
    is short (a 5px wall can hold at most 5 runs), so far geometry costs almost nothing.

    M13-2S rung 3b (`two_sided`): a marking two-sided seg gets TWO more blocks -- its UPPER
    (texture `sd.upper`, span front.ceil - back.ceil) and its LOWER (`sd.lower`, span
    back.floor - front.floor) -- keyed exactly like the middle one, so a step face and a wall of the
    same texture, light and span share a block. Returns `(offsets_by_seg, bank_text)` where each
    offset entry is `(middle, upper, lower)` when `two_sided` is given, else the bare middle offset.

    The run-lists come from `ReferenceModel.wpx_strip` — the same call the oracle paints from, so
    the two cannot drift (R6)."""
    STRIDE = 2 * cap                              # [n] + (cap-1) pairs + [last_colour]
    cache, blocks, off_by_seg = {}, {}, {}
    out = [f"// M13-WPX: 1x1 wall run-lists, per (texture,light) block x wall height "
           f"(stride {STRIDE} dw, run cap {cap})", "wpxstrips:"]

    def block_for(texname, lightnum, wall_units):
        """the bank offset of the block for this (texture, light, span), baking it on first use."""
        tex = rm._wall_texture(asset_wad, texname, cache, wall_mode="WPX")
        key = (texname.upper() if tex is not None else None, lightnum, wall_units)
        if key not in blocks:
            # M13-2S rung 3b buffers a block INDEX (one byte pair in a region entry); the
            # shipped tier bakes the dw OFFSET straight into the seg's register.
            blocks[key] = (len(blocks) if two_sided is not None
                           else len(blocks) * (view_h + 1) * STRIDE)
            texels, th, tw = tex if tex is not None else (None, 0, 0)
            for h in range(view_h + 1):
                lr = rm.wall_light_row(lightnum, max(1, h), max(1, wall_units))
                runs = rm.wpx_strip(texels, th, tw, colormap, lr, max(1, h), cap=cap)
                body = []
                for rel, c in runs[:-1]:
                    body += [rel, c]
                body += [0, runs[-1][1]]                  # rel==0 sentinel, then the last colour
                assert len(body) <= STRIDE, f"WPX list overflows its stride: {len(body)} > {STRIDE}"
                out.extend([f";{v:#x} * dw" for v in body] + [";0 * dw"] * (STRIDE - len(body)))
        return blocks[key]

    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        two = ld.back != -1
        if two and not ((solid is not None and solid(seg))
                        or (two_sided is not None and two_sided(seg))):
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        sec = rm._seg_sector(lds, sds, secs, seg)
        # M13-WPXLIGHT: the block key carries the seg's DOOM light level (sector level + FAKE
        # CONTRAST, both per-seg constants) and the wall's span in map units -- the span is what lets
        # each baked height h recover its own projection scale, and hence its scalelight row. So
        # distance lighting and fake contrast are pure BAKE: zero runtime ops.
        lightnum = rm.wall_lightnum(sec.light, rm.wall_fake_contrast(verts[seg.v1], verts[seg.v2]))
        mid = block_for(sd.middle, lightnum, sec.ceil_h - sec.floor_h)
        if two_sided is None:
            off_by_seg[si] = mid
            continue
        up = lo = mid
        if two:
            bsec = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
            if sec.ceil_h > bsec.ceil_h:
                up = block_for(sd.upper, lightnum, sec.ceil_h - bsec.ceil_h)
            if bsec.floor_h > sec.floor_h:
                lo = block_for(sd.lower, lightnum, bsec.floor_h - sec.floor_h)
        off_by_seg[si] = (mid, up, lo)
    return off_by_seg, NLJ.join(out) + NLJ


def _lines_mode_decls(cfg, rm, asset_wad, vz_classes: dict, key_ids: dict,
                      w2s: bool = False) -> list[str]:
    """M13-lines decls, post-bakedbands: the baked bank + the frame's bank pointer. No
    build_bands, no recip32, no built-flags, no planeheight math, no yslope table -- the lists
    are static data. `drawn` stays the stride-1 packed byte; wedge registers shared-named with
    raster/proj."""
    return [
        "seg_lit: hex.vec 2",                          # the W1 wall's fully-baked constant lit byte
        "seg_wstrip: hex.vec w/4", "wstripbase: hex.vec w/4",   # M13-W2S strip bank
        "seg_cvpidx: hex.vec w/4", "seg_fvpidx: hex.vec w/4",   # baked dw-offsets into the bank
        "seg_pid: hex.vec 2",                          # M13-2S rung 3a: baked plane-pair id (1-based)
        "vzbank: hex.vec w/4",                         # set per frame by the player-subsector block
        # M13-splitxb: part-1/part-2 shared state + the rest-block gate
        "proceed: hex.vec 1", "dbase: hex.vec w/4", "dptr: hex.vec w/4", "dval8: hex.vec 2",
        "seg_ret2: ;0",
        "drawn:" + NLJ + NLJ.join(";0 * dw" for _ in range(cfg.VIEW_W)),
        "wrej: hex.vec 1", "wqa: hex.vec 1", "wna: hex.vec 1", "wqb: hex.vec 1", "wnb: hex.vec 1",
        "wex: hex.vec 8", "wey: hex.vec 8", "weyx: hex.vec 8", "wexy: hex.vec 8",
    ]

def _stream_mode_decls(cfg, nvpc: int, nvpf: int) -> list[str]:
    """M13pS2-crush2b: the raster_mode="stream" per-VISPLANE band storage + the shared band-building
    leaves' scratch registers. Each of the map's nvpc ceiling / nvpf floor visplanes gets ONE
    full-range packed-byte buffer (slot 0 = the entry count n, then up to MAX_BANDS 3-byte entries)
    built at most once per frame (`vpc_flags`/`vpf_flags`, reset in pass-1).

    M13-colstruct: each claimed column's fields (drawn flag, clipped cexcl/fstart rows, the baked W1
    lit byte, the ceiling/floor visplane indices) live PACKED in ONE combined struct `col_struct`
    (stride 11 dw/column) instead of 6 separate arrays (the shared `drawn` array + col_cexcl/
    col_fstart, still declared elsewhere for the fb-mode leaf, goes unused here). Layout: offset 0 =
    drawn, a single PACKED byte (1 dw slot) -- it's only ever read/written internally (read_byte/
    write_byte_and_inc), never emitted. Offsets 1-10 = cexcl,fstart,lit,cvp,fvp, each a 2-NIBBLE-VEC
    pair (2 dw slots: low nibble then high nibble) -- NOT a packed byte, because present_tail's
    `byte.emit`/`cm.emit` dispatch reads its cell as idx/idx+1*dw (two separate nibble dw-slots) by
    XORing those two ADDRESSES directly into the dispatch op; it never dereferences through a register,
    so the address it's given must actually hold nibble-vec data, matching the OLD col_cexcl-style
    hex.vec arrays' low 2 nibbles. One struct load lets the stream leaf walk all 6 fields with a single
    held pointer instead of a fresh ptr_index per field per column (ptr_index's cost scales with the
    address width, ptr_add's doesn't -- R20/fj-lessons). fvp's 0xFF sentinel (UNCLAIMED, both nibbles
    0xF) sits at offsets 9-10 of each column's slot."""
    vp_slots = 1 + 3 * MAX_BANDS
    vpc_zeros = "\n".join(";0 * dw" for _ in range(nvpc * vp_slots))
    vpf_zeros = "\n".join(";0 * dw" for _ in range(nvpf * vp_slots))
    # per-column init: [drawn=0 (packed byte), cexcl=00, fstart=00, lit=00, cvp=00, fvp=FF] as nibbles
    _COL_SLOT_NIBBLES = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0xF, 0xF]   # 1 packed byte + 5 nibble-vec pairs
    col_struct_zeros = "\n".join(
        f";{v:#x} * dw"
        for _ in range(cfg.VIEW_W) for v in _COL_SLOT_NIBBLES)
    return [
        "seg_lit: hex.vec 2",                          # M13pS2c: the W1 wall's fully-baked constant lit byte
        "seg_cvpidx: hex.vec 8", "seg_fvpidx: hex.vec 8",   # crush2b: the seg's visplane indices (baked)
        f"col_struct:\n{col_struct_zeros}",
        f"vpc_flags: rep({nvpc}, i) hex.vec 1, 0", f"vpf_flags: rep({nvpf}, i) hex.vec 1, 0",
        f"vpc_bufs:\n{vpc_zeros}", f"vpf_bufs:\n{vpf_zeros}",
        "bb_ph: hex.vec 8", "bb_light: hex.vec 2", "bb_base: hex.vec 2", "bb_y0: hex.vec 2",
        "bb_count: hex.vec 2", "bb_ascending: hex.vec 2", "bb_arr: hex.vec w/4", "bb_n: hex.vec 2",
        "bb_recip_ph: hex.vec 8", "bb_recip_out: hex.vec 8",   # plane.recip32's own I/O globals
        "plane_recip_ret: ;0", "plane_band_ret: ;0",
        "recip32_leaf: plane.recip32", "build_bands_leaf: plane.build_bands 1",
        # M13pS2-crush2a: build_bands walks yslope through ONE incrementing packed-byte pointer
        # (3 bytes/row) instead of a per-row read_table 8 -- the packed twin of the 8-nib table.
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
    ]
