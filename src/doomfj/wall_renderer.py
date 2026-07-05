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
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj, generate_slopediv_recip_lut_fj,
    generate_yslope_lut_fj, generate_zlight_lut_fj, generate_distscale_lut_fj,
    generate_emit_dispatch_table_fj, generate_yslope_packed_lut_fj,
)
from doomfj.reference_model import ANG90
from doomfj.mapcompiler import bake_bsp, _bsp_as_code, seg_affine_coeffs
from doomfj.reference_model import (ReferenceModel, WALL_BG,
                                    COLORMAP_LIGHTS, LIGHT_SHIFT, SLOPERANGE, build_scene)
from doomfj.texturecompiler import (compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table, downscale_canvas,
                                    colormap_values, _index_nibbles)


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


_ABLATE_MODES = frozenset({"planes", "pass2", "pass1", "segstub", "xrstub"})

MAX_BANDS = 64                    # M13pS2c: band-list slots/column/region. Bound: a monotone half-window's
                                  # zidx walk gives <=32 distinct zrow runs (zlight[lvl][zidx] is monotone in
                                  # zidx with values in [0,31]); a horizon-STRADDLING window (negative-viewz
                                  # areas) is built as TWO half-window walks appended -> <=64 entries.
BAND_STRIDE = MAX_BANDS * 3        # packed bytes per column per region (run-length, base, zrow each entry)


def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False,
                       ablate: frozenset = frozenset(), floor_mode: str = "textured",
                       wall_mode: str = "textured", raster_mode: str = "framebuffer") -> str:
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

    `wall_mode` (M13p4a): "textured" (default, the real per-seg wall texture) or "W1"/"W2" — every wall
    texture is reduced to a tiny synthetic canvas (`ReferenceModel._tiny_wall_canvas`, the SAME helper
    the oracle uses, R6) before it enters the combined table: W1 = 1×1 (the mode texel), W2 = 1×16 (a
    vertical band strip). `column_render_params`/pass-2/`leaf_body_w` are UNCHANGED — they just sample a
    much smaller table (793,344 texels → tens-to-low-hundreds).

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
    assert floor_mode in ("textured", "flat"), f"unknown floor_mode: {floor_mode!r}"
    assert wall_mode in ("textured", "W1", "W2"), f"unknown wall_mode: {wall_mode!r}"
    assert raster_mode in ("framebuffer", "stream"), f"unknown raster_mode: {raster_mode!r}"
    if raster_mode == "stream":
        assert wall_mode == "W1" and floor_mode == "flat", \
            "raster_mode='stream' only supports wall_mode='W1' + floor_mode='flat' (pS2c scope)"
    asset_wad = asset_wad or map_wad
    rm = ReferenceModel(cfg)                                  # REAL textures (no _wall_texture override)
    cmap = bake_bsp(map_wad, mapname)
    verts = cmap.vertexes
    lds = map_wad.linedefs(mapname); sds = map_wad.sidedefs(mapname); secs = map_wad.sectors(mapname)
    scene = build_scene(map_wad, asset_wad, mapname)
    colormap = scene.asset_wad.colormap()
    proj = cfg.PROJECTION << 16
    defs = {d.name.upper(): d for d in asset_wad.texture_defs("TEXTURE1")}

    # the combined dispatch table over every distinct wall texture the one-sided segs use (downscaled to match
    # the oracle's _wall_texture), plus the 1x1 WALL_BG sentinel; per-seg texinfo precomputed via the oracle rule.
    cache = {}
    seg_texinfo = {}                                         # si -> (texbase, texheight, texwidth)
    names = set()
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1:
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        if rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=wall_mode) is not None:
            names.add(sd.middle.upper())
    combined, info = [], {}
    for nm in sorted(names) + [None]:
        key = nm if nm else "__WALLBG__"
        if nm is None:
            th, tw, texels = 1, 1, [WALL_BG]
        else:
            c = downscale_canvas(composite_texture(asset_wad, defs[nm]), rm.downscale)
            th, tw, texels = len(c), len(c[0]), texture_texels(c)
            if wall_mode != "textured":                        # M13p4a: shrink to the tiny synthetic canvas
                texels, th, tw = rm._tiny_wall_canvas(texels, th, wall_mode)
        while len(combined) % th != 0:                        # align the slice to its texheight (the OR-trick)
            combined.append(0)
        info[key] = (len(combined), th, tw)
        combined += texels
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1:
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        t = rm._wall_texture(asset_wad, sd.middle, cache, wall_mode=wall_mode)
        seg_texinfo[si] = info[sd.middle.upper()] if t is not None else info["__WALLBG__"]

    tex = _texel_table("tex", combined, "per_entry", over_align=over_align)

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

    if raster_mode == "stream":
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
    else:
        cm = compile_colormap("cm", asset_wad, lights=COLORMAP_LIGHTS, over_align=over_align)
    palette = compile_palette("palette", asset_wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    slopediv_recip = generate_slopediv_recip_lut_fj("slopediv_recip")   # perf #13
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

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
        # player-subsector setup (runs only at the FIRST subsector visited = order[0] = the player's): set the
        # runtime viewz (player sector floor + VIEWHEIGHT) that every seg's worldtop + ceil/floor planeheight use.
        out = [
            f"    hex.if0 1, vz_set, e1pset{cid}",
            f"    ;e1psegs{cid}",
            f"  e1pset{cid}:",
            f"    hex.set 8, viewz, {viewz_val & 0xFFFFFFFF}",
            f"    hex.set 8, viewzw, {(viewz_val >> 16) & 0xFFFFFFFF}",
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
            if raster_mode == "stream":
                # M13pS2c: the W1 wall's lit colour is fully constant (one texel, one light row) --
                # bake the FINAL palette byte at Python emit time (no runtime colormap lookup at all).
                fields.append(("seg_lit", 2, colormap[lrow(ssec.light)][combined[tb]]))
                # M13pS2-crush2b: the seg's ceiling/floor visplane indices (shared band lists)
                ckey = (ssec.ceil_h, ssec.light & 0xFF, _flatval(ssec.ceil_tex))
                fkey = (ssec.floor_h, ssec.light & 0xFF, _flatval(ssec.floor_tex))
                fields.append(("seg_cvpidx", 8, cvp_ids.setdefault(ckey, len(cvp_ids))))
                fields.append(("seg_fvpidx", 8, fvp_ids.setdefault(fkey, len(fvp_ids))))
            xorby_blocks[si] = _seg_xorby_block(si, fields)
            out += _seg_xorby_use(si)
        if raster_mode == "stream":
            # M13pG1: skip the whole action (incl. every seg's xorby SET/CLEAR pair) once the screen
            # is full -- the leaf would fret per seg anyway, but the involution flips aren't free.
            out = ([f"    hex.if0 1, full, e1sact{cid}", f"    ;e1sskip{cid}", f"  e1sact{cid}:"]
                   + out + [f"  e1sskip{cid}:"])
        return out

    bsp = _bsp_as_code(_pfx(mapname), cmap, done_label="bsp_done", subsector_action=subsector_action,
                       full_abort_label="full" if raster_mode == "stream" else None)   # M13pG1 (stream only)
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # the shared per-seg xorby blocks (once)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        "hex.zero 2, n_drawn", "hex.zero 1, full",   # M13opt-P1: reset the drawn-column counter + full flag per frame
    ]
    if raster_mode == "stream":
        # M13pS2-crush2b: per-frame reset of the visplane built-flags (compile-time-unrolled zeroing)
        pass1 += [f"rep({max(1, len(cvp_ids))}, v) hex.zero 1, vpc_flags + v*dw",
                  f"rep({max(1, len(fvp_ids))}, v) hex.zero 1, vpf_flags + v*dw"]
    if "pass1" in ablate:                              # M13p0: skip the walk entirely (residue-only measurement)
        pass1.append("bsp_done:")
    else:
        pass1 += [f";{_pfx(mapname)}_bspcode_walk", "bsp_done:"]
    pass2 = []                                            # pass 2a: walls (M12oo shared-compare trampoline)
    if "pass2" not in ablate and raster_mode != "stream":   # M13p0 ablate / M13pS2: stream has NO fb raster
        for x in range(cfg.VIEW_W):
            pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                         f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                         f"col_heightmask + {8 * x}*dw")
            for y in range(cfg.H):                                # M12oo: the shared-compare trampoline (y runtime)
                pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")
    # pass 2b: floor/ceiling visplanes (M13d2) — the per-frame clear_planes seeds + the runtime per-ROW
    # R_MakeSpans textured span pass (replaces the M13c3 per-column plane_tramp unroll).
    plane_pass = []
    if "planes" not in ablate and raster_mode != "stream":   # M13pS2: planes render via the band lists instead
        plane_pass = ["stl.fcall clear_leaf, clear_ret",
                      f"frame.render_planes_spans {cfg.VIEW_W}, {cfg.VIEW_H}"]

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
    distscale = generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N)

    stream = raster_mode == "stream"
    # M13pS2: the stream present -- the frame leaves the program AS the emitted run bytes (device
    # DMA decode); one unrolled emit_column per screen column, every col_* read at a compile-time
    # address. Replaces update_screen_reg + the whole fb/pass-2/plane-pass raster.
    present_tail = (["present.begin_frame_stream",
                     *(f"stream.emit_column col_cbands + {8 * x}*dw, col_cexcl + {8 * x}*dw, "
                       f"col_fstart + {8 * x}*dw, col_lit + {8 * x}*dw, col_fbands + {8 * x}*dw"
                       for x in range(cfg.VIEW_W))]
                    if stream else ["present.update_screen_reg framebuffer"])
    fb_leaves = [] if stream else [                      # the fb-raster shared leaves -- stream emits none of them
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "span_leaf:",
        (f"plane.draw_span framebuffer, {cfg.VIEW_W}" if floor_mode == "textured"      # M13d2 textured u,v span
         else f"plane.draw_span_flat framebuffer, {cfg.VIEW_W}"),                      # M13p1 flat-colored span
        "clear_leaf:", f"plane.clear_planes {cfg.CENTERX << 16}, {ANG90}",  # M13d2 per-frame R_ClearPlanes seeds
    ]
    main = "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen_stream 0" if stream else "present.init_screen",
        *pass1, *pass2, *plane_pass,
        "present.set_palette palette", *present_tail, "stl.loop",
        "bad: stl.loop",
        *fb_leaves,
        *(["seg_pass1_leaf:", "stl.fret seg_ret"] if "segstub" in ablate else
          ["seg_pass1_leaf:", "hex.if0 1, full, xrs_work", "stl.fret seg_ret",
           "xrs_work:", "hex.zero 1, visible", "stl.fret seg_ret"] if "xrstub" in ablate else
          ["seg_pass1_leaf:",
           f"frame.seg_pass1_leaf_body_stream {cfg.CENTERY}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}, {BAND_STRIDE}"]
          if raster_mode == "stream" else
          ["seg_pass1_leaf:",
           f"frame.seg_pass1_leaf_body_mtlwp {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}"]),
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        *([] if stream else [f"framebuffer: hex.vec {2 * cfg.FB_SIZE}"]),   # M13pS2: no fb in stream mode
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
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
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        # M13opt-P1 byte-exact early-out: count claimed columns; `full` short-circuits later (occluded) segs.
        "n_drawn: hex.vec 2", "full: hex.vec 1", f"vieww: hex.vec 2, {cfg.VIEW_W}",
        *(_stream_mode_decls(cfg, max(1, len(cvp_ids)), max(1, len(fvp_ids)))
          if raster_mode == "stream" else []),
        tantoangle, slopediv_recip, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
        yslope, zlight, distscale, flat_table,        # M13d2 textured-floor LUTs + combined flat table
    ])
    return main


def _stream_mode_decls(cfg, nvpc: int, nvpf: int) -> list[str]:
    """M13pS2-crush2b: the raster_mode="stream" per-VISPLANE band storage + the shared band-building
    leaves' scratch registers. Each of the map's nvpc ceiling / nvpf floor visplanes gets ONE
    full-range packed-byte buffer (slot 0 = the entry count n, then up to MAX_BANDS 3-byte entries)
    built at most once per frame (`vpc_flags`/`vpf_flags`, reset in pass-1); each claimed column
    stores its planes' buffer ADDRESSES in `col_cbands`/`col_fbands` and the emit pass slices the
    shared lists (prefix/suffix)."""
    vp_slots = 1 + 3 * MAX_BANDS
    vpc_zeros = "\n".join(";0 * dw" for _ in range(nvpc * vp_slots))
    vpf_zeros = "\n".join(";0 * dw" for _ in range(nvpf * vp_slots))
    return [
        "seg_lit: hex.vec 2",                          # M13pS2c: the W1 wall's fully-baked constant lit byte
        "seg_cvpidx: hex.vec 8", "seg_fvpidx: hex.vec 8",   # crush2b: the seg's visplane indices (baked)
        f"col_lit: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_cbands: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_fbands: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"vpc_flags: rep({nvpc}, i) hex.vec 1, 0", f"vpf_flags: rep({nvpf}, i) hex.vec 1, 0",
        f"vpc_bufs:\n{vpc_zeros}", f"vpf_bufs:\n{vpf_zeros}",
        "bb_ph: hex.vec 8", "bb_light: hex.vec 2", "bb_base: hex.vec 2", "bb_y0: hex.vec 2",
        "bb_count: hex.vec 2", "bb_ascending: hex.vec 2", "bb_arr: hex.vec w/4", "bb_n: hex.vec 2",
        "bb_recip_ph: hex.vec 8", "bb_recip_out: hex.vec 8",   # plane.recip32's own I/O globals
        "plane_recip_ret: ;0", "plane_band_ret: ;0",
        "recip32_leaf: plane.recip32", "build_bands_leaf: plane.build_bands",
        # M13pS2-crush2a: build_bands walks yslope through ONE incrementing packed-byte pointer
        # (3 bytes/row) instead of a per-row read_table 8 -- the packed twin of the 8-nib table.
        generate_yslope_packed_lut_fj("yslope_packed", cfg.VIEW_W, cfg.VIEW_H),
    ]
