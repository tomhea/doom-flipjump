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
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj,
    generate_yslope_lut_fj, generate_zlight_lut_fj,
)
from doomfj.mapcompiler import bake_bsp, _bsp_as_code
from doomfj.reference_model import (ReferenceModel, WALL_BG,
                                    COLORMAP_LIGHTS, LIGHT_SHIFT, SLOPERANGE, build_scene)
from doomfj.texturecompiler import (compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table, downscale_canvas)


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


def emit_wall_renderer(map_wad, mapname, cfg, *, asset_wad=None, over_align=False) -> str:
    """Emit the full runtime wall+floor/ceiling renderer for `mapname` as the fj `main` text (everything after
    the fixed includes). Uses the optimized SHARED macros (pixel_tramp/compare_y wall trampoline, the
    xor_by-involution walk, and the M13c3 plane_tramp visplane raster), so this is the single source both
    `build_doom` and the golden test render through. The viewpoint `(vx,vy,va)` is read from stdin (signed
    decimal) at runtime. Geometry comes from `map_wad`; textures/colormap/palette/flats from `asset_wad`
    (defaults to `map_wad` — E1M1 is self-contained; the square-room test passes a separate asset wad).
    `over_align` pads dispatch tables to a 2^n boundary (test layout); pass False for the production
    (build_doom) layout."""
    asset_wad = asset_wad or map_wad
    rm = ReferenceModel(cfg)                                  # REAL textures (no _wall_texture override)
    cmap = bake_bsp(map_wad, mapname)
    verts = cmap.vertexes
    lds = map_wad.linedefs(mapname); sds = map_wad.sidedefs(mapname); secs = map_wad.sectors(mapname)
    scene = build_scene(map_wad, asset_wad, mapname)
    colormap = scene.asset_wad.colormap()
    proj = cfg.PROJECTION << 16
    flatcache: dict = {}                                      # _flat_base per-frame cache (the flat's [0] texel)
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
        if rm._wall_texture(asset_wad, sd.middle, cache) is not None:
            names.add(sd.middle.upper())
    combined, info = [], {}
    for nm in sorted(names) + [None]:
        key = nm if nm else "__WALLBG__"
        if nm is None:
            th, tw, texels = 1, 1, [WALL_BG]
        else:
            c = downscale_canvas(composite_texture(asset_wad, defs[nm]), rm.downscale)
            th, tw, texels = len(c), len(c[0]), texture_texels(c)
        while len(combined) % th != 0:                        # align the slice to its texheight (the OR-trick)
            combined.append(0)
        info[key] = (len(combined), th, tw)
        combined += texels
    for si, seg in enumerate(cmap.segs):
        ld = lds[seg.linedef]
        if ld.back != -1:
            continue
        sd = sds[ld.front if seg.side == 0 else ld.back]
        t = rm._wall_texture(asset_wad, sd.middle, cache)
        seg_texinfo[si] = info[sd.middle.upper()] if t is not None else info["__WALLBG__"]

    tex = _texel_table("tex", combined, "per_entry", over_align=over_align)
    cm = compile_colormap("cm", asset_wad, lights=COLORMAP_LIGHTS, over_align=over_align)
    palette = compile_palette("palette", asset_wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

    _cid = [0]
    xorby_blocks = {}                                        # M12pp: seg{si}_xorby blocks, emitted once each

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
            fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                      ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                      ("seg_segangle", 8, seg.angle), ("seg_texoff", 8, texoff & 0xFFFFFFFF),
                      ("seg_texbase", 5, tb), ("seg_texheight", 4, th), ("seg_tw", 8, tw),
                      ("seg_hm", 3, th - 1), ("seg_light", 2, lrow(ssec.light)),
                      ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                      ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                      ("seg_ceil", 8, ssec.ceil_h & 0xFFFFFFFF),   # M12pp: worldtop = seg_ceil - viewzw in-leaf
                      ("seg_floor", 8, ssec.floor_h & 0xFFFFFFFF),  # M13c3: floor planeheight = |floor_h<<16 - viewz|
                      ("seg_plight", 2, ssec.light & 0xFF),         # RAW sector light (plane.draw_pixel does >>4)
                      ("seg_ceilbase", 2, rm._flat_base(asset_wad, ssec.ceil_tex, flatcache)),
                      ("seg_floorbase", 2, rm._flat_base(asset_wad, ssec.floor_tex, flatcache))]
            xorby_blocks[si] = _seg_xorby_block(si, fields)
            out += _seg_xorby_use(si)
        return out

    bsp = _bsp_as_code(_pfx(mapname), cmap, done_label="bsp_done", subsector_action=subsector_action)
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # the shared per-seg xorby blocks (once)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        f";{_pfx(mapname)}_bspcode_walk", "bsp_done:",
    ]
    pass2 = []                                            # pass 2a: walls (M12oo shared-compare trampoline)
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                     f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                     f"col_heightmask + {8 * x}*dw")
        for y in range(cfg.H):                                # M12oo: the shared-compare trampoline (y runtime)
            pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")
    plane_pass = []                                       # pass 2b: floor/ceiling visplanes (M13c3 plane_tramp)
    for x in range(cfg.VIEW_W):
        plane_pass.append(f"frame.load_col_plane col_cexcl + {8 * x}*dw, col_fstart + {8 * x}*dw, "
                          f"col_ceil_ph + {8 * x}*dw, col_floor_ph + {8 * x}*dw, col_plight + {8 * x}*dw, "
                          f"col_ceilbase + {8 * x}*dw, col_floorbase + {8 * x}*dw")
        for y in range(cfg.H):
            plane_pass.append(f"frame.plane_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")

    yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
    zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2, *plane_pass,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "plane_leaf:", "plane.draw_pixel",                # M13c3 the distance-lit flat-colored plane pixel
        "plane_compare:", "frame.plane_compare_body",     # M13c3 shared floor/ceiling/skip select (emitted once)
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtlwp {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {cfg.VIEW_H}, {proj}",
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "viewz: hex.vec 8", "viewzw: hex.vec 8", "vz_set: hex.vec 1",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: xorby block fcall/fret return register
        "ceilfix: hex.vec 8", "floorfix: hex.vec 8",
        "seg_ceil: hex.vec 8", "worldtop: hex.vec 8",     # M12pp: seg_ceil baked (pure); worldtop leaf-computed
        "seg_floor: hex.vec 8", "seg_plight: hex.vec 2",  # M13c3 plane bakes (pure floor_h + raw light + flat bases)
        "seg_ceilbase: hex.vec 2", "seg_floorbase: hex.vec 2",
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
        # M13c3 pass-2 plane registers (load_col_plane fills these per column; plane_compare/plane.draw_pixel read them)
        "planeheight: hex.vec 8", "light: hex.vec 2", "pbase: hex.vec 2",
        "cexcl: hex.vec 2", "fstart: hex.vec 2", "ceil_ph: hex.vec 8", "floor_ph: hex.vec 8",
        "ceil_base: hex.vec 2", "floor_base: hex.vec 2", "plane_ret: ;0",
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
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette, yslope, zlight,
    ])
    return main
