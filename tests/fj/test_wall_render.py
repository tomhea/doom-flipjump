"""M12cc (F5) — the per-seg WALL RENDER integration: compose the projection pipeline (wall_scale_setup +
the per-column frame.wall_column = column_render_params + base + leaf setup) with the M11c shared leaf
(frame.pixel_clipped) to rasterize a real seg's columns into the hex.vec2 framebuffer, byte-exact vs the
oracle. The first end-to-end params->pixels render of real square-room geometry; the full frame (all segs
+ BSP walk) follows.

Geometry (scale, screen-span, texture-u angle) is the REAL square-room east wall from (200,128) (an oblique
view -> a varying per-column scale, exercising the scale accumulation). Texture is STEP4 (32x16, texheight
16 -> the M11c leaf heightmask is exact) + a synthetic rw_offset + a chosen light, so the test is
self-contained (like M12z/M12aa). Only the first N columns are rendered (column_render_params is inlined
per column here; the full-width renderer routes it through a shared fcall column-leaf). NOTE: `tw` is passed
as a REGISTER (it is a hex.div memory operand in texture_u), not a compile-time literal."""
import math
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed
from doomfj.harness import W
from types import SimpleNamespace

from doomfj.lut_generator import (
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj,
)
from doomfj.mapcompiler import bake_bsp, _bsp_as_code, Seg, SubSector, Node, CompiledMap, NF_SUBSECTOR
from doomfj.reference_model import ReferenceModel, ANGLE_MASK, SLOPERANGE, WALL_BG
from doomfj.texturecompiler import (compile_texture, compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table)
from doomfj.wad import WadFile

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
ROOM = Path("tests/fixtures/square_room.wad")
ASSET = "tests/fixtures/freedoom_assets.wad"
TEX = "STEP4"   # 32x16 -> texheight 16 (pow2, >=16 so the leaf heightmask is exact), texwidth 32


def _col_params(rm, scale, rca, rw_off, rwd, x, tw, ceil_h, floor_h, viewz, worldtop):
    """The oracle per-column params (render_wall_frame 540-559), mirrored: clipped (top,bottom) + texcol +
    8.8 (frac0, step)."""
    cfg = rm.cfg
    ds = cfg.TEXTURE_DOWNSCALE
    top, bottom = rm.wall_screen_span(ceil_h, floor_h, viewz, scale & ANGLE_MASK)
    top = max(0, top)
    bottom = min(cfg.VIEW_H - 1, bottom)
    ang = (rca + rm.xtoviewangle[x]) & ANGLE_MASK
    ft = rm.finetangent[(ang >> rm.angle_shift) & (cfg.TRIG_N - 1)]
    texcol = (_signed((rw_off - fixed_mul(ft, rwd, 8, 4)) & ANGLE_MASK, 32) >> 16) % tw
    iscale = fixed_div(1 << 16, scale & ANGLE_MASK, 8, 4) // ds
    texturemid = (worldtop << 16) // ds
    frac = texturemid + (top - cfg.CENTERY) * iscale
    return top, bottom, texcol, (frac >> 8) & 0xFFFF, (iscale >> 8) & 0xFFFF


def test_wall_render_seg_columns_byte_exact(tmp_path):
    cfg = Config()
    rm = ReferenceModel(cfg)
    U = 1 << 16
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])   # 16, 32
    colormap = wad.colormap()

    seg = cmap.segs[2]                                   # east wall
    vx, vy, va = 200, 128, 0
    x1, x2, _ = rm.wall_x_range(vx * U, vy * U, va, seg, cmap.vertexes)
    nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, cmap.vertexes)
    ANG90 = 0x40000000
    rca = (ANG90 + va - nrm) & ANGLE_MASK
    rw_off = 0x80000                                     # synthetic texture u-origin (self-contained)
    light = 1                                            # chosen (colormap built with 2 lights)
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16                         # view_z (VIEWHEIGHT 41)
    worldtop = ceil_h - (viewz >> 16)                    # 87
    N = 4                                                # render the first N columns of the seg
    proj = cfg.PROJECTION << 16

    # scale seed + step (the oracle's lines 521-527)
    s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
    s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
    diff, span = s2 - s1, x2 - x1
    sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0

    # expected device frame: zeros except the N rendered columns
    want = bytearray(cfg.FB_SIZE)
    for i in range(N):
        x = x1 + i
        scale = (s1 + i * sstep) & ANGLE_MASK
        top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                        ceil_h, floor_h, viewz, worldtop)
        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                        count=bottom - top + 1, frac0=frac0, step=step)
        for r in range(bottom - top + 1):
            want[(top + r) * cfg.W + x] = col[r]

    # the fj renderer: seed scale, then per column wall_column (params + leaf setup) + clipped row loop +
    # accumulate scale.  (Full-width routes wall_column through a top-level fcall column-leaf, like pixel_leaf.)
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)

    render = [f"proj.wall_scale_setup scale, scalestep, va_in, nrm_in, rwd_in, x1_in, x2_in, {proj}"]
    for i in range(N):
        render.append(f"frame.wall_column top, bottom, scale, x_in, rca_in, rwoff_in, rwd_in, light_in, "
                      f"cf_in, ff_in, vz_in, wt_in, tw_in, {th}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}")
        for y in range(cfg.H):
            render.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + (x1 + i))}*dw, top, bottom")
        render.append("hex.inc 2, x_in")
        render.append("hex.add 8, scale, scalestep")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "scale: hex.vec 8", "scalestep: hex.vec 8", "top: hex.vec 8", "bottom: hex.vec 8",
        f"va_in: hex.vec 8, {va & 0xFFFFFFFF}", f"nrm_in: hex.vec 8, {nrm & 0xFFFFFFFF}",
        f"rwd_in: hex.vec 8, {rwd & 0xFFFFFFFF}", f"x1_in: hex.vec 8, {x1}", f"x2_in: hex.vec 8, {x2}",
        f"rca_in: hex.vec 8, {rca & 0xFFFFFFFF}", f"rwoff_in: hex.vec 8, {rw_off & 0xFFFFFFFF}",
        f"light_in: hex.vec 2, {light}", f"cf_in: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}",
        f"ff_in: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}", f"vz_in: hex.vec 8, {viewz & 0xFFFFFFFF}",
        f"wt_in: hex.vec 8, {worldtop & 0xFFFFFFFF}", f"x_in: hex.vec 2, {x1}", f"tw_in: hex.vec 8, {tw}",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",   # row-constant table for pixel_clipped (rows[k]=k)
        tex, cm, palette, xtoviewangle, finetangent, finesine,
    ])
    p = tmp_path / "wallrender.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "wallrender.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    assert bytes(screen.pixel_indices) == bytes(want)


def test_wall_render_full_width_via_column_leaf(tmp_path):
    """M12dd: render the FULL column range [x1,x2) of a real seg via the shared fcall COLUMN-LEAF
    (frame.column_leaf_body) — column_render_params is inlined ONCE in the leaf, not WIDTH× (the assemble
    lever). Per column: fcall column_leaf -> the leaf sets top/bottom + the pixel-leaf regs; then the
    clipped row loop. Byte-exact vs the oracle's textured columns for the whole wall."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    U = 1 << 16
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()

    seg = cmap.segs[2]
    vx, vy, va = 200, 128, 0
    x1, x2, _ = rm.wall_x_range(vx * U, vy * U, va, seg, cmap.vertexes)
    nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, cmap.vertexes)
    ANG90 = 0x40000000
    rca = (ANG90 + va - nrm) & ANGLE_MASK
    rw_off = 0x80000
    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    proj = cfg.PROJECTION << 16

    s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
    s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
    diff, span = s2 - s1, x2 - x1
    sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0

    want = bytearray(cfg.FB_SIZE)
    for i in range(x2 - x1):
        x = x1 + i
        scale = (s1 + i * sstep) & ANGLE_MASK
        top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                        ceil_h, floor_h, viewz, worldtop)
        if top > bottom:
            continue
        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                        count=bottom - top + 1, frac0=frac0, step=step)
        for r in range(bottom - top + 1):
            want[(top + r) * cfg.W + x] = col[r]

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)

    # register names must match column_leaf_body's `<` extern clause exactly (x, rw_centerangle, ...)
    render = [f"proj.wall_scale_setup scale, scalestep, viewangle, normalangle, rw_distance, x1_in, x2_in, {proj}"]
    for i in range(x2 - x1):
        render.append("stl.fcall column_leaf, col_ret")    # the shared per-column leaf
        for y in range(cfg.H):
            render.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + (x1 + i))}*dw, top, bottom")
        render.append("hex.inc 2, x")
        render.append("hex.add 8, scale, scalestep")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"column_leaf:", f"frame.column_leaf_body {th}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "scale: hex.vec 8", "scalestep: hex.vec 8", "top: hex.vec 8", "bottom: hex.vec 8",
        f"x: hex.vec 2, {x1}",
        f"viewangle: hex.vec 8, {va & 0xFFFFFFFF}", f"normalangle: hex.vec 8, {nrm & 0xFFFFFFFF}",
        f"rw_distance: hex.vec 8, {rwd & 0xFFFFFFFF}", f"x1_in: hex.vec 8, {x1}", f"x2_in: hex.vec 8, {x2}",
        f"rw_centerangle: hex.vec 8, {rca & 0xFFFFFFFF}", f"rw_offset: hex.vec 8, {rw_off & 0xFFFFFFFF}",
        f"light: hex.vec 2, {light}", f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}",
        f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}", f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}",
        f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}", f"tw: hex.vec 8, {tw}",
        "col_ret: ;0",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",   # row-constant table for pixel_clipped (rows[k]=k)
        tex, cm, palette, xtoviewangle, finetangent, finesine,
    ])
    p = tmp_path / "wallfull.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "wallfull.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    assert bytes(screen.pixel_indices) == bytes(want)


def test_wall_render_array_bridge_byte_exact(tmp_path):
    """M12jj — THE ARRAY BRIDGE (pass 2 of the two-pass renderer, B'). Same seg/geometry as the M12dd
    full-width test, but the per-column params are NOT computed at runtime in fj (no column_leaf): they are
    Python-FILLED into per-column param ARRAYS (col_top/col_bottom/col_base/col_light/col_step/col_frac0,
    indexed by screen column x) and pass 2 reads col_*[x] at COMPILE-TIME addresses (x = the unroll index,
    a constant -> zero pointers) via frame.load_col, then runs the clipped row loop. This isolates the
    pass-1<->pass-2 contract + the hoisting (per-column read once, per-pixel write) BEFORE the runtime
    pass-1 fill (M12kk). Arrays Python-filled => fixed viewpoint, NO runtime-write infra yet. Byte-exact vs
    the same oracle golden the M12dd full-width raster matches. No projection/LUTs needed in pass 2."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    U = 1 << 16
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()

    seg = cmap.segs[2]
    vx, vy, va = 200, 128, 0
    x1, x2, _ = rm.wall_x_range(vx * U, vy * U, va, seg, cmap.vertexes)
    nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, cmap.vertexes)
    ANG90 = 0x40000000
    rca = (ANG90 + va - nrm) & ANGLE_MASK
    rw_off = 0x80000
    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)

    s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
    s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
    diff, span = s2 - s1, x2 - x1
    sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0

    # Python pass 1: per-column params -> the arrays (indexed by absolute screen column x), + the golden.
    VW = cfg.VIEW_W
    col_top = [0] * VW
    col_bottom = [0] * VW
    col_base = [0] * VW
    col_light = [light] * VW
    col_step = [0] * VW
    col_frac0 = [0] * VW
    want = bytearray(cfg.FB_SIZE)
    for i in range(x2 - x1):
        x = x1 + i
        scale = (s1 + i * sstep) & ANGLE_MASK
        top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                        ceil_h, floor_h, viewz, worldtop)
        col_top[x], col_bottom[x] = top, bottom          # CLAIM even if top>bottom (pixel_clipped skips it)
        col_base[x] = texcol * th                         # base_reg = texcol*texheight (column-major M8)
        col_step[x], col_frac0[x] = step, frac0
        if top > bottom:
            continue
        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                        count=bottom - top + 1, frac0=frac0, step=step)
        for r in range(bottom - top + 1):
            want[(top + r) * cfg.W + x] = col[r]

    def _arr(label, nibbles, values):
        lines = [f"{label}: hex.vec {nibbles}, {values[0]}"]
        lines += [f"hex.vec {nibbles}, {v}" for v in values[1:]]
        return "\n".join(lines)

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)

    # pass 2: per column, load col_*[x] at compile-time addresses (x is the rep index), then the row loop.
    render = []
    for i in range(x2 - x1):
        x = x1 + i
        render.append(f"frame.load_col col_top + {2 * x}*dw, col_bottom + {2 * x}*dw, "
                      f"col_base + {3 * x}*dw, col_light + {2 * x}*dw, "
                      f"col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw")
        for y in range(cfg.H):
            render.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "top: hex.vec 2", "bottom: hex.vec 2",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        _arr("col_top", 2, col_top), _arr("col_bottom", 2, col_bottom),
        _arr("col_base", 3, col_base), _arr("col_light", 2, col_light),
        _arr("col_step", 4, col_step), _arr("col_frac0", 4, col_frac0),
        tex, cm, palette,
    ])
    p = tmp_path / "arraybridge.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "arraybridge.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    assert bytes(screen.pixel_indices) == bytes(want)


def test_wall_render_composes_over_background(tmp_path):
    """M12ii: render a seg's columns OVER a filled two-band background (frame.render_background), the way
    render_wall_frame composites walls over the M9 background — NOT over zeros. This needs the wall pixel
    write to OVERWRITE the (non-zero) background cell, not XOR into it. Byte-exact vs the expected
    composite: the two-band background everywhere, with the wall rows of columns [x1, x1+N) overwritten by
    the oracle's textured column. (Same seg/geometry as the full-width test, via the shared column-leaf.)"""
    cfg = Config()
    rm = ReferenceModel(cfg)
    U = 1 << 16
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()

    seg = cmap.segs[2]
    vx, vy, va = 200, 128, 0
    x1, x2, _ = rm.wall_x_range(vx * U, vy * U, va, seg, cmap.vertexes)
    nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, cmap.vertexes)
    ANG90 = 0x40000000
    rca = (ANG90 + va - nrm) & ANGLE_MASK
    rw_off = 0x80000
    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    proj = cfg.PROJECTION << 16
    N = 8                                                 # render the first N columns over the background

    s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
    s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
    diff, span = s2 - s1, x2 - x1
    sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0

    ceil_color, floor_color = 5, 109                      # two distinct non-zero background bytes
    horizon = cfg.VIEW_H // 2
    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):                           # the two-band background (composited UNDER the wall)
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c
    for i in range(N):                                    # the wall, OVERWRITING the background in its rows
        x = x1 + i
        scale = (s1 + i * sstep) & ANGLE_MASK
        top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                        ceil_h, floor_h, viewz, worldtop)
        if top > bottom:
            continue
        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                        count=bottom - top + 1, frac0=frac0, step=step)
        for r in range(bottom - top + 1):
            want[(top + r) * cfg.W + x] = col[r]

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)

    # register names must match column_leaf_body's `<` extern clause exactly (as in the full-width test)
    render = [f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
              f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
              f"proj.wall_scale_setup scale, scalestep, viewangle, normalangle, rw_distance, x1_in, x2_in, {proj}"]
    for i in range(N):
        render.append("stl.fcall column_leaf, col_ret")
        for y in range(cfg.H):
            render.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + (x1 + i))}*dw, top, bottom")
        render.append("hex.inc 2, x")
        render.append("hex.add 8, scale, scalestep")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"column_leaf:", f"frame.column_leaf_body {th}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "scale: hex.vec 8", "scalestep: hex.vec 8", "top: hex.vec 8", "bottom: hex.vec 8",
        f"x: hex.vec 2, {x1}",
        f"viewangle: hex.vec 8, {va & 0xFFFFFFFF}", f"normalangle: hex.vec 8, {nrm & 0xFFFFFFFF}",
        f"rw_distance: hex.vec 8, {rwd & 0xFFFFFFFF}", f"x1_in: hex.vec 8, {x1}", f"x2_in: hex.vec 8, {x2}",
        f"rw_centerangle: hex.vec 8, {rca & 0xFFFFFFFF}", f"rw_offset: hex.vec 8, {rw_off & 0xFFFFFFFF}",
        f"light: hex.vec 2, {light}", f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}",
        f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}", f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}",
        f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}", f"tw: hex.vec 8, {tw}",
        "col_ret: ;0",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        tex, cm, palette, xtoviewangle, finetangent, finesine,
    ])
    p = tmp_path / "wallcompose.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "wallcompose.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    assert bytes(screen.pixel_indices) == bytes(want)


class _ScreenWithInput(InMemoryScreen):
    """An InMemoryScreen that ALSO feeds stdin (the runtime viewpoint), so one assembled binary can be
    re-run over several stdin viewpoints. read_bit mirrors FixedIO (lsb-first from a bytes buffer)."""
    def __init__(self, stdin: bytes):
        super().__init__()
        self._inp = stdin
        self._byte = 0
        self._bits = 0

    def read_bit(self) -> bool:
        if self._bits == 0:
            if not self._inp:
                from flipjump.utils.exceptions import IOReadOnEOF
                raise IOReadOnEOF("EOF on _ScreenWithInput")
            self._byte, self._inp = self._inp[0], self._inp[1:]
            self._bits = 8
        bit = (self._byte & 1) == 1
        self._byte >>= 1
        self._bits -= 1
        return bit


def _oracle_single_seg_frame(rm, cmap, seg, verts, tw, th, texels, colormap, light,
                             ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va):
    """Build the byte-exact expected frame for ONE seg at runtime viewpoint (vx,vy,va) over the M9 two-band
    background — the oracle's render_wall_frame per-seg path for a single seg (no occlusion). Returns None's
    background-only frame when the seg is culled."""
    cfg = rm.cfg
    U = 1 << 16
    horizon = cfg.VIEW_H // 2
    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):                                  # the two-band background
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c
    rng = rm.wall_x_range(vx * U, vy * U, va, seg, verts)
    if rng is None:
        return want                                              # culled -> background only
    x1, x2, rwa = rng
    nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, verts)
    s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
    s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
    diff, span = s2 - s1, x2 - x1
    sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0
    rw_off, rca = rm._wall_offset(vx * U, vy * U, va, seg, verts, nrm, rwa, SimpleNamespace(x_off=0))
    for i in range(x2 - x1):
        x = x1 + i
        scale = (s1 + i * sstep) & ANGLE_MASK
        top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                        ceil_h, floor_h, viewz, worldtop)
        if top > bottom:
            continue
        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                        count=bottom - top + 1, frac0=frac0, step=step)
        for r in range(bottom - top + 1):
            want[(top + r) * cfg.W + x] = col[r]
    return want


def test_wall_render_pass1_runtime_fill_byte_exact(tmp_path):
    """M12kk — PASS 1 FILLS THE ARRAYS AT RUNTIME (single seg, runtime viewpoint from stdin). This is the
    first TRULY-runtime wall render: the projection front-end (wall_x_range cull / wall_setup / wall_scale_
    setup / wall_offset / column_render_params) runs in fj from a stdin viewpoint over BAKED seg consts,
    and a RUNTIME per-column loop writes col_*[x] via the runtime-indexed write (frame.store_col). Pass 2
    is the M12jj unrolled raster (load_col + pixel_clipped over ALL columns; unfilled columns skip via the
    compile-time top=1/bottom=0 sentinel). ONE assemble, re-run over SEVERAL stdin viewpoints chosen so the
    x-range / scale / offset all VARY (incl. partial-width segs that exercise the skip sentinel, and a
    CULLED viewpoint -> background only), each byte-exact vs the oracle's single-seg render_wall_frame
    path. Proves the renderer is runtime (not a baked fixed frame)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    U = 1 << 16
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()
    verts = cmap.vertexes

    seg = cmap.segs[2]                                           # east wall (256,256)->(256,0)
    v1x, v1y = verts[seg.v1]
    v2x, v2y = verts[seg.v2]
    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)                           # 87
    texoff = (seg.offset) << 16                                  # sd.x_off taken 0 (self-contained)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    ANG90 = 0x40000000

    VIEWPOINTS = [
        (128, 128, 0),          # full width, baseline scale
        (200, 128, 0),          # closer: same x-range, much larger scale
        (110, 128, 0),          # partial [10,150): exercises the skip sentinel both sides
        (60, 128, 0),           # partial [28,132): different x-range + scale
        (128, 128, ANG90),      # CULLED (facing north) -> background only
    ]

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    pass1 = [
        "hex.input_dec_int 8, vx_raw, bad", "hex.input_dec_int 8, vy_raw, bad",
        "hex.input_dec_uint 8, viewangle, bad",                  # va = BAM (unsigned)
        "hex.mov 8, viewx, vx_raw", "hex.shl_hex 8, 4, viewx",   # viewx = vx << 16
        "hex.mov 8, viewy, vy_raw", "hex.shl_hex 8, 4, viewy",
        f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
        f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        "proj.wall_x_range visible, x1, x2, rwa, viewx, viewy, viewangle, v1x, v1y, v2x, v2y",
        "hex.if0 1, visible, pass2",                             # culled -> pass 2 (background only)
        "proj.wall_setup normalangle, rw_distance, viewx, viewy, segangle, v1x, v1y",
        f"proj.wall_scale_setup scale, scalestep, viewangle, normalangle, rw_distance, x1, x2, {proj}",
        "proj.wall_offset rw_offset, rw_centerangle, viewx, viewy, viewangle, normalangle, rwa, "
        "v1x, v1y, texoff",   # texoff is a hex.add MEMORY operand -> must be a register (lesson #1)
        "hex.mov 8, x, x1",
        "p1loop:",
        "hex.scmp 8, x, x2, p1body, pass2, pass2",               # x < x2 ? body, else done
        "p1body:",
        "proj.column_render_params top, bottom, texcol, cfrac0, stepv, scale, rw_centerangle, rw_offset, "
        f"rw_distance, x, tw, ceilfix, floorfix, viewz, worldtop, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}",
        f"hex.mul_const 4, base, texcol, {th}",                  # base = texcol*texheight
        "frame.store_col x, col_top, col_bottom, col_base, col_step, col_frac0, top, bottom, base, stepv, cfrac0",
        "hex.inc 8, x", "hex.add 8, scale, scalestep",
        ";p1loop",
        "pass2:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col col_top + {4 * x}*dw, col_bottom + {4 * x}*dw, col_base + {4 * x}*dw, "
                     f"light_baked, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        # pass-1 input + temps
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8",
        "viewangle: hex.vec 8", "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        # baked seg consts
        f"v1x: hex.vec 8, {(v1x << 16) & 0xFFFFFFFF}", f"v1y: hex.vec 8, {(v1y << 16) & 0xFFFFFFFF}",
        f"v2x: hex.vec 8, {(v2x << 16) & 0xFFFFFFFF}", f"v2y: hex.vec 8, {(v2y << 16) & 0xFFFFFFFF}",
        f"segangle: hex.vec 8, {seg.angle}", f"tw: hex.vec 8, {tw}", f"texoff: hex.vec 8, {texoff & 0xFFFFFFFF}",
        f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}", f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}",
        f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}", f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}",
        f"light_baked: hex.vec 2, {light}",
        # pass-2 leaf scratch (top/bottom shared; reloaded by load_col)
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        # the 5 per-column param arrays (uniform 4-nibble; skip-sentinel init top=1, bottom=0)
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    p = tmp_path / "pass1fill.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "pass1fill.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:                                # one binary, many runtime viewpoints
        want = _oracle_single_seg_frame(rm, cmap, seg, verts, tw, th, texels, colormap, light,
                                        ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12kk @ ({vx},{vy},{va}) != oracle"


def _oracle_multi_seg_frame(rm, cmap, lds, sds, one_sided, tw, th, texels, colormap, light,
                            ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va):
    """The oracle's render_wall_frame per-seg loop for ALL one-sided segs of the (convex) square room, over
    the M9 two-band background, with a SHARED front-to-back `drawn[]` clip — the multi-seg golden. Mirrors
    render_wall_frame 510-563 limited to the square room's one-sided segs (single texture/light/sector)."""
    cfg = rm.cfg
    U = 1 << 16
    verts = cmap.vertexes
    horizon = cfg.VIEW_H // 2
    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c
    drawn = bytearray(cfg.VIEW_W)
    for si in one_sided:                                       # subsector seg order (front-to-back)
        seg = cmap.segs[si]
        rng = rm.wall_x_range(vx * U, vy * U, va, seg, verts)
        if rng is None:
            continue
        x1, x2, rwa = rng
        nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, verts)
        s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
        s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
        diff, span = s2 - s1, x2 - x1
        sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0
        ld = lds[seg.linedef]
        sd = sds[ld.front if seg.side == 0 else ld.back]
        rw_off, rca = rm._wall_offset(vx * U, vy * U, va, seg, verts, nrm, rwa, sd)
        for i in range(x2 - x1):
            x = x1 + i
            if not drawn[x]:                                  # claimed by a nearer seg? (convex -> never)
                scale = (s1 + i * sstep) & ANGLE_MASK
                top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                               ceil_h, floor_h, viewz, worldtop)
                if top <= bottom:
                    col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                                    count=bottom - top + 1, frac0=frac0, step=step)
                    for r in range(bottom - top + 1):
                        want[(top + r) * cfg.W + x] = col[r]
                drawn[x] = 1
    return want


def test_wall_render_multi_seg_walk_driven_byte_exact(tmp_path):
    """M12ll — the BSP WALK DRIVES MULTI-SEG fill + runtime drawn[] (square room, convex, no occlusion yet).
    Pass 1 is now driven by the M12gg `_bsp_as_code` walk: visiting a subsector runs a subsector_action that,
    for each one-sided seg, sets the seg's BAKED consts and fcalls the shared `frame.seg_pass1_leaf_body`,
    which RELOADS the projection front-end for that seg from the runtime viewpoint and runs the per-column
    loop with the runtime `drawn[]` clip. Convex => drawn[] never blocks, but the mechanism + per-seg RELOAD
    + walk-drive all RUN (the per-seg-reload/walk-integration bugs that hide on single-seg). ONE assemble,
    several stdin viewpoints chosen so a DIFFERENT set of walls is visible / a different split, each
    byte-exact vs the oracle's multi-seg render_wall_frame path."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()
    lds = WadFile.from_path(ROOM).linedefs("MAP01")
    sds = WadFile.from_path(ROOM).sidedefs("MAP01")

    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A45, A135, A225 = 0x20000000, 0x60000000, 0xA0000000

    one_sided = [si for si in range(len(cmap.segs)) if lds[cmap.segs[si].linedef].back == -1]

    VIEWPOINTS = [
        (128, 128, A45),     # walls {1,2}, even split [0,80)/[80,160)
        (128, 128, A135),    # walls {0,1} — different set
        (128, 128, A225),    # walls {3,0} — different set
        (200, 128, A45),     # walls {1,2}, UNEVEN split [0,49)/[49,160) — different scales
        (128, 128, 0),       # single wall {2} head-on (segs 0/1/3 culled in the leaf)
    ]

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def subsector_action(s):
        """Emit, for subsector s, the per-(one-sided-)seg baked-const loads + fcall the shared pass-1 leaf."""
        ss = cmap.subsectors[s]
        out = []
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            ld = lds[seg.linedef]
            if ld.back != -1:                                 # two-sided (window/opening) -> not a solid wall
                continue
            v1x, v1y = verts[seg.v1]
            v2x, v2y = verts[seg.v2]
            sd = sds[ld.front if seg.side == 0 else ld.back]
            texoff = (seg.offset + sd.x_off) << 16
            out += [f"    hex.set 8, seg_v1x, {(v1x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v1y, {(v1y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2x, {(v2x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2y, {(v2y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_segangle, {seg.angle}",
                    f"    hex.set 8, seg_texoff, {texoff & 0xFFFFFFFF}",
                    "    stl.fcall seg_pass1_leaf, seg_ret"]
        return out

    bsp = _bsp_as_code("room", cmap, done_label="bsp_done", subsector_action=subsector_action)

    pass1 = [
        "hex.input_dec_int 8, vx_raw, bad", "hex.input_dec_int 8, vy_raw, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx_raw", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy_raw", "hex.shl_hex 8, 4, viewy",
        f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
        f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        ";room_bspcode_walk",                                 # pass 1: the walk drives the multi-seg fill
        "bsp_done:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col col_top + {4 * x}*dw, col_bottom + {4 * x}*dw, col_base + {4 * x}*dw, "
                     f"light_baked, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body {th}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        # per-seg baked consts (set by the walk's subsector_action before each fcall)
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        # scene consts (single sector -> baked once)
        f"tw: hex.vec 8, {tw}", f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}",
        f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}", f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}",
        f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}", f"light_baked: hex.vec 2, {light}",
        # pass-1 temps
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        "seg_ret: ;0",
        # pass-2 leaf scratch (top/bottom shared; reloaded by load_col)
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        # per-column param arrays + drawn (uniform 4-nibble; col_top skip-sentinel=1, rest + drawn = 0)
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    p = tmp_path / "multiseg.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "multiseg.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = _oracle_multi_seg_frame(rm, cmap, lds, sds, one_sided, tw, th, texels, colormap, light,
                                       ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12ll @ ({vx},{vy},{va}) != oracle"


def _seg_bam(verts, a, b):
    """The 16-bit seg angle (BAM>>16) of the v[a]->v[b] direction — DOOM's seg.angle (matches the bake)."""
    dx, dy = verts[b][0] - verts[a][0], verts[b][1] - verts[a][1]
    return (int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & 0xFFFFFFFF) >> 16


def _occluder_map():
    """A hand-built 2-seg / 1-node CompiledMap (no WAD) — two CROSSING one-sided walls with a vertical BSP
    partition, so `point_on_side` orders them at runtime: from the right seg0 is nearer (occludes seg1),
    from the left seg1 is nearer (occludes seg0). Both front faces point toward the -y viewer region. This
    is the minimal scene where `drawn[]` actually CLIPS (the convex square room never did) AND the BSP NODE
    walk (point_on_side_leaf) runs."""
    verts = [(-90, 210), (30, 90), (-30, 90), (90, 210)]
    segs = [Seg(0, 1, _seg_bam(verts, 0, 1), 0, 0, 0),   # crossing walls, wound to face the -y viewer
            Seg(2, 3, _seg_bam(verts, 2, 3), 0, 0, 0)]
    subs = [SubSector(1, 0), SubSector(1, 1)]
    node = Node(x=0, y=0, dx=0, dy=1, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)   # vertical x=0
    return CompiledMap(vertexes=verts, segs=segs, subsectors=subs, nodes=[node], root=0)


def _oracle_occlusion_frame(rm, cmap, tw, th, texels, colormap, light, ceil_h, floor_h, viewz, worldtop,
                            ceil_color, floor_color, vx, vy, va):
    """The oracle's render_wall_frame path for the hand-built occluder: walk the BSP front-to-back
    (bsp_render_order), render each subsector's (one-sided) segs over the M9 background with a SHARED
    `drawn[]` clip. All segs are one-sided (solid); texoff = 0 (fake sidedef). The drawn[] actually clips."""
    cfg = rm.cfg
    U = 1 << 16
    verts = cmap.vertexes
    horizon = cfg.VIEW_H // 2
    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c
    drawn = bytearray(cfg.VIEW_W)
    for ssi in rm.bsp_render_order(cmap, vx, vy):              # front-to-back subsector order
        ss = cmap.subsectors[ssi]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            rng = rm.wall_x_range(vx * U, vy * U, va, seg, verts)
            if rng is None:
                continue
            x1, x2, rwa = rng
            nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, verts)
            s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
            s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
            diff, span = s2 - s1, x2 - x1
            sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0
            rw_off, rca = rm._wall_offset(vx * U, vy * U, va, seg, verts, nrm, rwa, SimpleNamespace(x_off=0))
            for i in range(x2 - x1):
                x = x1 + i
                if not drawn[x]:                              # CLAIMED by a nearer seg -> clipped here
                    scale = (s1 + i * sstep) & ANGLE_MASK
                    top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                                   ceil_h, floor_h, viewz, worldtop)
                    if top <= bottom:
                        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                                        count=bottom - top + 1, frac0=frac0, step=step)
                        for r in range(bottom - top + 1):
                            want[(top + r) * cfg.W + x] = col[r]
                    drawn[x] = 1
    return want


def test_wall_render_occlusion_drawn_clips_byte_exact(tmp_path):
    """M12mm — OCCLUSION: `drawn[]` actually CLIPS, driven by a real BSP NODE walk (the convex square room
    never exercised either). A hand-built 2-seg / 1-node occluder (two crossing one-sided walls + a vertical
    partition) — `point_on_side` orders the segs at runtime, so a nearer seg CLAIMS its columns (drawn[]) and
    the farther seg is clipped there; the scale still advances over the clipped columns. ONE assemble, 5 stdin
    viewpoints chosen so BOTH orderings occur (seg0 occludes seg1 from the right, seg1 occludes seg0 from the
    left) and the occluded-column pattern varies, each byte-exact vs the oracle's bsp_render_order + drawn[]
    path. (Single texture/light; per-seg textures are a later rung.)"""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = _occluder_map()
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    texels, th, tw = texture_texels(canvas), len(canvas), len(canvas[0])
    colormap = wad.colormap()

    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A90 = 0x40000000

    VIEWPOINTS = [
        (50, 0, A90),     # order [seg0, seg1]: seg0 occludes seg1 (~35 cols)
        (-50, 0, A90),    # order [seg1, seg0]: seg1 occludes seg0 (the SWAP)
        (0, 0, A90),      # order [seg0, seg1]: larger overlap (~54 cols)
        (90, 20, A90),    # order [seg0, seg1]: small overlap (~8 cols)
        (-90, 20, A90),   # order [seg1, seg0]: small overlap (swap, ~7 cols)
    ]

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def subsector_action(s):
        """Per subsector: for each seg (all one-sided here), set baked consts + fcall the shared pass-1 leaf."""
        ss = cmap.subsectors[s]
        out = []
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            v1x, v1y = verts[seg.v1]
            v2x, v2y = verts[seg.v2]
            out += [f"    hex.set 8, seg_v1x, {(v1x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v1y, {(v1y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2x, {(v2x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2y, {(v2y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_segangle, {seg.angle}",
                    "    hex.set 8, seg_texoff, 0",
                    "    stl.fcall seg_pass1_leaf, seg_ret"]
        return out

    bsp = _bsp_as_code("occ", cmap, done_label="bsp_done", subsector_action=subsector_action)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",   # 10-nibble map coords (for the walk)
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",                  # viewx = vx << 16 (16.16 for projection)
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
        f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        ";occ_bspcode_walk",                                                # the walk (with a NODE) drives pass 1
        "bsp_done:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col col_top + {4 * x}*dw, col_bottom + {4 * x}*dw, col_base + {4 * x}*dw, "
                     f"light_baked, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body {th}, {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        f"tw: hex.vec 8, {tw}", f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}",
        f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}", f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}",
        f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}", f"light_baked: hex.vec 2, {light}",
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        "seg_ret: ;0",
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    p = tmp_path / "occlusion.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "occlusion.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = _oracle_occlusion_frame(rm, cmap, tw, th, texels, colormap, light, ceil_h, floor_h, viewz,
                                       worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12mm @ ({vx},{vy},{va}) != oracle"


def _build_combined_textures(wad, names):
    """Concatenate the given textures into ONE combined texel list (the single dispatch table the multi-
    texture leaf samples). Each slice's offset is aligned UP to its texheight so the leaf's base|v OR ==
    base+v. `names`: texture names, or None for a 1x1 WALL_BG sentinel slice. Returns (combined_texels,
    info) where info[name_or_'__WALLBG__'] = (texbase, texheight, texwidth)."""
    defs = {d.name: d for d in wad.texture_defs()}
    combined, info = [], {}
    for nm in names:
        key = nm if nm else "__WALLBG__"
        if key in info:
            continue
        if nm is None:
            th, tw, texels = 1, 1, [WALL_BG]
        else:
            canvas = composite_texture(wad, defs[nm])
            th, tw, texels = len(canvas), len(canvas[0]), texture_texels(canvas)
        while len(combined) % th != 0:                        # align the slice to its texheight (OR-trick)
            combined.append(0)
        info[key] = (len(combined), th, tw)
        combined += texels
    return combined, info


def _oracle_multitex_frame(rm, cmap, lds, sds, seg_tex, texinfo, texdata, colormap, light,
                           ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va):
    """render_wall_frame for the square room with PER-SEG textures (seg_tex[si] = a name or None=WALL_BG):
    textured segs sample their own texture/texheight; a None seg flat-fills colormap[light][WALL_BG]. Shared
    drawn[] (convex => no clipping). texdata[name]=(texels,th,tw)."""
    cfg = rm.cfg
    U = 1 << 16
    verts = cmap.vertexes
    horizon = cfg.VIEW_H // 2
    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c
    flat = colormap[light][WALL_BG]
    drawn = bytearray(cfg.VIEW_W)
    one_sided = [si for si in range(len(cmap.segs)) if lds[cmap.segs[si].linedef].back == -1]
    for si in one_sided:
        seg = cmap.segs[si]
        rng = rm.wall_x_range(vx * U, vy * U, va, seg, verts)
        if rng is None:
            continue
        x1, x2, rwa = rng
        nrm, rwd = rm.wall_setup(vx * U, vy * U, seg, verts)
        s1 = rm.scale_from_global_angle((va + rm.xtoviewangle[x1]) & ANGLE_MASK, va, nrm, rwd)
        s2 = rm.scale_from_global_angle((va + rm.xtoviewangle[x2]) & ANGLE_MASK, va, nrm, rwd)
        diff, span = s2 - s1, x2 - x1
        sstep = (-(abs(diff) // span) if diff < 0 else diff // span) if x2 > x1 else 0
        ld = lds[seg.linedef]
        sd = sds[ld.front if seg.side == 0 else ld.back]
        rw_off, rca = rm._wall_offset(vx * U, vy * U, va, seg, verts, nrm, rwa, sd)
        name = seg_tex[si]
        tw = texinfo[name if name else "__WALLBG__"][2]       # the seg's texture width (1 for WALL_BG)
        for i in range(x2 - x1):
            x = x1 + i
            if not drawn[x]:
                scale = (s1 + i * sstep) & ANGLE_MASK
                top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                               ceil_h, floor_h, viewz, worldtop)
                if top <= bottom:
                    if name is None:                          # '-' texture -> flat WALL_BG fill
                        for y in range(top, bottom + 1):
                            want[y * cfg.W + x] = flat
                    else:
                        texels, th, _ = texdata[name]
                        col = rm.render_textured_column(texels, th, texcol, colormap, light,
                                                        count=bottom - top + 1, frac0=frac0, step=step)
                        for r in range(bottom - top + 1):
                            want[(top + r) * cfg.W + x] = col[r]
                drawn[x] = 1
    return want


def test_wall_render_multitexture_byte_exact(tmp_path):
    """M12mm2 — PER-SEG TEXTURES: each wall samples its OWN texture (different texheights, incl. <16) out of a
    single COMBINED dispatch table, plus the flat WALL_BG fallback for a '-' wall. The square room's 4 walls
    are assigned STEP4 (32x16) / A-YELLOW (16x8, exercises the heightmask<16 fix) / STEP4 / '-' (WALL_BG). Pass
    1 computes base = seg_texbase + texcol*texheight at RUNTIME (per-seg texheight) into col_base[x] (the
    absolute combined-table texel index) + col_heightmask[x]; the per-pixel leaf is UNCHANGED (one tex.sample
    over the combined table) and now masks v with the full 2-nibble heightmask (correct for texheight<16). A
    '-' wall is a 1x1 WALL_BG sentinel slice (texheight 1, v->0) so the SAME path flat-fills it. ONE assemble,
    several stdin viewpoints showing different wall pairs (so all 3 textures incl. WALL_BG are exercised),
    byte-exact vs the oracle's per-seg-texture render_wall_frame path."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    colormap = wad.colormap()
    lds = WadFile.from_path(ROOM).linedefs("MAP01")
    sds = WadFile.from_path(ROOM).sidedefs("MAP01")

    seg_tex = ["STEP4", "A-YELLOW", "STEP4", None]            # per-seg texture (None = '-' -> WALL_BG)
    combined, texinfo = _build_combined_textures(wad, ["STEP4", "A-YELLOW", None])
    texdata = {nm: (texture_texels(c := composite_texture(wad, {t.name: t for t in wad.texture_defs()}[nm])),
                    len(c), len(c[0])) for nm in ("STEP4", "A-YELLOW")}

    light = 1
    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A45, A135, A225, A315 = 0x20000000, 0x60000000, 0xA0000000, 0xE0000000

    VIEWPOINTS = [
        (128, 128, A45),     # walls {1,2} = A-YELLOW(h8) + STEP4(h16): multi-texture + heightmask<16
        (128, 128, A135),    # walls {0,1} = STEP4 + A-YELLOW
        (128, 128, A225),    # walls {3,0} = WALL_BG('-') + STEP4: the flat fallback
        (128, 128, A315),    # walls {2,3} = STEP4 + WALL_BG
        (200, 128, A45),     # walls {1,2}, uneven split: A-YELLOW + STEP4 at different scales
    ]

    tex = _texel_table("tex", combined, "per_entry", over_align=True)   # the single COMBINED dispatch table
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    palette = compile_palette("palette", wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def subsector_action(s):
        ss = cmap.subsectors[s]
        out = []
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            seg = cmap.segs[si]
            ld = lds[seg.linedef]
            if ld.back != -1:
                continue
            v1x, v1y = verts[seg.v1]
            v2x, v2y = verts[seg.v2]
            sd = sds[ld.front if seg.side == 0 else ld.back]
            texoff = (seg.offset + sd.x_off) << 16
            name = seg_tex[si]
            texbase, th_s, tw_s = texinfo[name if name else "__WALLBG__"]
            out += [f"    hex.set 8, seg_v1x, {(v1x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v1y, {(v1y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2x, {(v2x << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_v2y, {(v2y << 16) & 0xFFFFFFFF}",
                    f"    hex.set 8, seg_segangle, {seg.angle}",
                    f"    hex.set 8, seg_texoff, {texoff & 0xFFFFFFFF}",
                    f"    hex.set 4, seg_texbase, {texbase}", f"    hex.set 4, seg_texheight, {th_s}",
                    f"    hex.set 8, seg_tw, {tw_s}", f"    hex.set 3, seg_hm, {th_s - 1}",
                    "    stl.fcall seg_pass1_leaf, seg_ret"]
        return out

    bsp = _bsp_as_code("room", cmap, done_label="bsp_done", subsector_action=subsector_action)

    pass1 = [
        "hex.input_dec_int 8, vx_raw, bad", "hex.input_dec_int 8, vy_raw, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx_raw", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy_raw", "hex.shl_hex 8, 4, viewy",
        f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
        f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        ";room_bspcode_walk", "bsp_done:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col_mt col_top + {4 * x}*dw, col_bottom + {4 * x}*dw, col_base + {4 * x}*dw, "
                     f"light_baked, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw, col_heightmask + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mt {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 4", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}", f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}",
        f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}", f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}",
        f"light_baked: hex.vec 2, {light}",
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        "seg_ret: ;0",
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        "heightmask: hex.vec 3", "pixel_ret: ;0",                  # heightmask now set per-column by load_col_mt
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "multitex.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "multitex.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = _oracle_multitex_frame(rm, cmap, lds, sds, seg_tex, texinfo, texdata, colormap, light,
                                      ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12mm2 @ ({vx},{vy},{va}) != oracle"
