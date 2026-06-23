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
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed
from doomfj.harness import W
from doomfj.lut_generator import (
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
)
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel, ANGLE_MASK
from doomfj.texturecompiler import compile_texture, compile_colormap, compile_palette, composite_texture, texture_texels
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
