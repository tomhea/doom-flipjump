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
from flipjump.fjm.fjm_reader import Reader

from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.fixedpoint import fixed_mul, fixed_div, _signed
from doomfj.harness import W
from types import SimpleNamespace

from doomfj.lut_generator import (
    generate_xtoviewangle_lut_fj, generate_finetangent_lut_fj, generate_trig_idioms_fj,
    generate_tantoangle_lut_fj, generate_viewangletox_lut_fj,
)
from doomfj.mapcompiler import bake_bsp, _bsp_as_code, Seg, SubSector, Node, CompiledMap, NF_SUBSECTOR
from doomfj.reference_model import (ReferenceModel, ANGLE_MASK, SLOPERANGE, WALL_BG,
                                    CEIL_BG, FLOOR_BG, COLORMAP_LIGHTS, LIGHT_SHIFT,
                                    SimState, build_scene, spawn_state, frame_hash)
from doomfj.texturecompiler import (compile_texture, compile_colormap, compile_palette, composite_texture,
                                    texture_texels, _texel_table, downscale_canvas)
from doomfj.wad import WadFile

PRESENT_FJ = Path("src/fj/present.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PROJECTION_FJ = Path("src/fj/projection.fj")
FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")
ROOM = Path("tests/fixtures/square_room.wad")
ASSET = "tests/fixtures/freedoom_assets.wad"
TEX = "STEP4"   # 32x16 -> texheight 16 (pow2, >=16 so the leaf heightmask is exact), texwidth 32


# ── M12pp: walk xor_by + xor-involution self-zeroing ──────────────────────────────────────────────
# Replace the per-seg baked `hex.set` constants (each pays an @-dispatch to zero a register it overwrites)
# with `hex.xor_by` (no @). Correct ONLY on a zero register, so the per-seg consts live in ONE shared block
# fcall'd BEFORE (0 -> vals) and AFTER (vals -> 0) the leaf — `xor_by val` twice cancels (involution), and
# the seg regs (declared hex.vec, zero-init) self-restore to 0 each iteration. The leaf only READS those regs
# (verified: wall_x_range/wall_setup/wall_offset/column_render_params take them as read-only operands), and
# every baked field is a PURE compile-time constant (worldtop = seg_ceil - viewzw is NOT pure -> seg_ceil is
# baked here and worldtop is computed inside the leaf). The block label is keyed on the seg index (each seg is
# in one subsector) so the BSP double-emission (R7b) fcalls it twice but emits it once.

def _seg_xorby_block(idx, fields):
    """The shared seg{idx}_xorby block (emitted ONCE, fcall'd twice per visible seg). `fields` = list of
    (regname, width, value) PURE compile-time constants."""
    lines = [f"  seg{idx}_xorby:"]
    for reg, wdt, val in fields:
        lines.append(f"    hex.xor_by {wdt}, {reg}, {val}")
    lines.append("    stl.fret xb_ret")
    return lines


def _seg_xorby_use(idx, clear=True):
    """The SET / USE / CLEAR fcall sequence at the call site. `clear=False` drops the involution CLEAR (the
    M12pp TDD FAIL stub: seg regs accumulate across segs -> wrong values for every seg after the first)."""
    seq = [f"    stl.fcall seg{idx}_xorby, xb_ret",      # SET  (0 -> vals)
           "    stl.fcall seg_pass1_leaf, seg_ret"]      # USE  (leaf reads the seg regs)
    if clear:
        seq.append(f"    stl.fcall seg{idx}_xorby, xb_ret")   # CLEAR (vals -> 0, the xor involution)
    return seq


# Toggle for the M12pp TDD FAIL evidence: when False, the involution CLEAR is dropped (regs accumulate).
_M12PP_CLEAR = True


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


def _oracle_multilight_frame(rm, cmap, lds, sds, seg_tex, seg_light, texinfo, texdata, colormap,
                             ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va):
    """render_wall_frame for the square room with PER-SEG TEXTURES *and* PER-SEG LIGHT (seg_light[si] = the
    colormap row for seg si). Each seg's textured column is colormapped at its OWN light; a None (WALL_BG)
    seg flat-fills colormap[seg_light][WALL_BG]. Background stays the compile-time two-band fill (runtime bg
    is M12nn-b). Shared drawn[] (convex => no clipping). texdata[name]=(texels,th,tw)."""
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
        lt = seg_light[si]                                    # the seg's own colormap row
        tw = texinfo[name if name else "__WALLBG__"][2]
        flat = colormap[lt][WALL_BG]
        for i in range(x2 - x1):
            x = x1 + i
            if not drawn[x]:
                scale = (s1 + i * sstep) & ANGLE_MASK
                top, bottom, texcol, frac0, step = _col_params(rm, scale, rca, rw_off, rwd, x, tw,
                                                               ceil_h, floor_h, viewz, worldtop)
                if top <= bottom:
                    if name is None:
                        for y in range(top, bottom + 1):
                            want[y * cfg.W + x] = flat
                    else:
                        texels, th, _ = texdata[name]
                        col = rm.render_textured_column(texels, th, texcol, colormap, lt,
                                                        count=bottom - top + 1, frac0=frac0, step=step)
                        for r in range(bottom - top + 1):
                            want[(top + r) * cfg.W + x] = col[r]
                drawn[x] = 1
    return want


def test_wall_render_multilight_byte_exact(tmp_path):
    """M12nn-a — PER-SEG MULTI-LIGHT: each wall is colormapped at its OWN sector light (the cmidx high byte /
    colormap row varies per column, not one baked value). Built on the M12mm2 multi-texture path: pass 1 now
    stores col_light[x] = the seg's baked light row (seg_pass1_leaf_body_mtl), and pass 2 reads col_light[x]
    into cmidx's high byte (load_col_mt's light_src) instead of a single light_baked. The square room is one
    sector, so per-seg lights are OVERRIDDEN in the test (seg_light = [1,9,17,25]) exactly as M12mm2 overrode
    per-seg textures; the WALL_BG fallback is colormapped at the seg's light too. ONE assemble, several stdin
    viewpoints showing different wall pairs (so different light pairs are exercised), byte-exact vs the oracle's
    per-seg-light render_wall_frame path. This isolates the col_light store/load contract that full E1M1 needs."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    colormap = wad.colormap()
    lds = WadFile.from_path(ROOM).linedefs("MAP01")
    sds = WadFile.from_path(ROOM).sidedefs("MAP01")

    seg_tex = ["STEP4", "A-YELLOW", "STEP4", None]            # per-seg texture (None = '-' -> WALL_BG)
    seg_light = [1, 9, 17, 25]                                # per-seg colormap row (OVERRIDDEN; one-sector room)
    combined, texinfo = _build_combined_textures(wad, ["STEP4", "A-YELLOW", None])
    texdata = {nm: (texture_texels(c := composite_texture(wad, {t.name: t for t in wad.texture_defs()}[nm])),
                    len(c), len(c[0])) for nm in ("STEP4", "A-YELLOW")}

    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A45, A135, A225, A315 = 0x20000000, 0x60000000, 0xA0000000, 0xE0000000

    VIEWPOINTS = [
        (128, 128, A45),     # walls {1,2} -> lights {9,17}
        (128, 128, A135),    # walls {0,1} -> lights {1,9}
        (128, 128, A225),    # walls {3,0} -> lights {25,1}: WALL_BG flat fill at light 25
        (128, 128, A315),    # walls {2,3} -> lights {17,25}
        (200, 128, A45),     # walls {1,2}, uneven split: lights {9,17} at different scales
    ]

    tex = _texel_table("tex", combined, "per_entry", over_align=True)
    cm = compile_colormap("cm", wad, lights=32, over_align=True)   # 32 light rows (per-seg lights span them)
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
                    f"    hex.set 2, seg_light, {seg_light[si]}",
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
                     f"col_light + {4 * x}*dw, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw, "
                     f"col_heightmask + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtl {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 4", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2",
        f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}", f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}",
        f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}", f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}",
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        "seg_ret: ;0",
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        "heightmask: hex.vec 3", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "multilight.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "multilight.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = _oracle_multilight_frame(rm, cmap, lds, sds, seg_tex, seg_light, texinfo, texdata, colormap,
                                        ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12nn-a @ ({vx},{vy},{va}) != oracle"


def test_wall_render_runtimebg_byte_exact(tmp_path):
    """M12nn-b — RUNTIME BACKGROUND COLORS: the two-band ceiling/floor background is colormapped at the PLAYER's
    sector light at RUNTIME (render_frame's path), not baked at compile time. fj computes the bg bytes per frame:
    row = player_light >> LIGHT_SHIFT (clamped), then cm.apply at CEIL_BG / FLOOR_BG -> two runtime registers ->
    frame.render_background_reg fills the framebuffer with them. To ISOLATE the runtime lookup+fill on the fast
    square room (one sector => the BSP-derived player light wouldn't vary), the player light is fed as a 4th
    stdin value and VARIED across viewpoints (=> the bg band color varies); the full E1M1 rung replaces the
    stdin read with the BSP walk's order[0] subsector -> sector light. Walls keep the M12nn-a per-seg multi-light
    overlay. ONE assemble, several stdin viewpoints (different player lights => different bg), byte-exact vs the
    oracle (render_frame bg colors + the per-seg-light wall overlay)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    colormap = wad.colormap()
    lds = WadFile.from_path(ROOM).linedefs("MAP01")
    sds = WadFile.from_path(ROOM).sidedefs("MAP01")

    seg_tex = ["STEP4", "A-YELLOW", "STEP4", None]
    seg_light = [1, 9, 17, 25]
    combined, texinfo = _build_combined_textures(wad, ["STEP4", "A-YELLOW", None])
    texdata = {nm: (texture_texels(c := composite_texture(wad, {t.name: t for t in wad.texture_defs()}[nm])),
                    len(c), len(c[0])) for nm in ("STEP4", "A-YELLOW")}

    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A45, A135, A225, A315 = 0x20000000, 0x60000000, 0xA0000000, 0xE0000000

    # (vx, vy, va, player_light): player_light varies -> bg row = light>>3 varies (8->1, 80->10, 160->20,
    # 248->31, 16->2), so the runtime bg-color path is exercised across viewpoints.
    VIEWPOINTS = [
        (128, 128, A45, 8),
        (128, 128, A135, 80),
        (128, 128, A225, 160),
        (128, 128, A315, 248),
        (200, 128, A45, 16),
    ]

    tex = _texel_table("tex", combined, "per_entry", over_align=True)
    cm = compile_colormap("cm", wad, lights=COLORMAP_LIGHTS, over_align=True)
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
                    f"    hex.set 2, seg_light, {seg_light[si]}",
                    "    stl.fcall seg_pass1_leaf, seg_ret"]
        return out

    bsp = _bsp_as_code("room", cmap, done_label="bsp_done", subsector_action=subsector_action)

    # runtime bg: read player_light (4th stdin), row = light>>3, cm.apply at CEIL_BG / FLOOR_BG -> regs -> fill.
    pass1 = [
        "hex.input_dec_int 8, vx_raw, bad", "hex.input_dec_int 8, vy_raw, bad",
        "hex.input_dec_uint 8, viewangle, bad", "hex.input_dec_uint 8, player_light, bad",
        "hex.mov 8, viewx, vx_raw", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy_raw", "hex.shl_hex 8, 4, viewy",
        "hex.mov 2, bgrow, player_light",
        f"rep({LIGHT_SHIFT}, i) hex.shr_bit 2, bgrow",   # row = light >> LIGHT_SHIFT (single source of truth)
        "hex.zero 4, bgidx", "hex.mov 2, bgidx + 2*dw, bgrow",                     # bgidx = row<<8 | 0(CEIL_BG)
        f"hex.set 2, bgidx, {CEIL_BG}", "cm.apply bgceil, bgidx",
        f"hex.set 2, bgidx, {FLOOR_BG}", "cm.apply bgfloor, bgidx",               # bgidx hi byte still = row
        f"frame.render_background_reg framebuffer, bgceil, bgfloor, {cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        ";room_bspcode_walk", "bsp_done:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col_mt col_top + {4 * x}*dw, col_bottom + {4 * x}*dw, col_base + {4 * x}*dw, "
                     f"col_light + {4 * x}*dw, col_step + {4 * x}*dw, col_frac0 + {4 * x}*dw, "
                     f"col_heightmask + {4 * x}*dw")
        for y in range(cfg.H):
            pass2.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top, bottom")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtl {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "player_light: hex.vec 8", "bgrow: hex.vec 2", "bgidx: hex.vec 4", "bgceil: hex.vec 2", "bgfloor: hex.vec 2",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 4", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2",
        f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}", f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}",
        f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}", f"worldtop: hex.vec 8, {worldtop & 0xFFFFFFFF}",
        "visible: hex.vec 1", "x1: hex.vec 8", "x2: hex.vec 8", "rwa: hex.vec 8",
        "normalangle: hex.vec 8", "rw_distance: hex.vec 8", "scale: hex.vec 8", "scalestep: hex.vec 8",
        "rw_offset: hex.vec 8", "rw_centerangle: hex.vec 8", "x: hex.vec 8",
        "texcol: hex.vec 8", "cfrac0: hex.vec 4", "stepv: hex.vec 4", "base: hex.vec 4",
        "seg_ret: ;0",
        "top: hex.vec 8", "bottom: hex.vec 8",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        "heightmask: hex.vec 3", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i",
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 4, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 4, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "runtimebg.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "runtimebg.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va, plight in VIEWPOINTS:
        row = max(0, min(COLORMAP_LIGHTS - 1, plight >> LIGHT_SHIFT))
        ceil_color, floor_color = colormap[row][CEIL_BG], colormap[row][FLOOR_BG]
        want = _oracle_multilight_frame(rm, cmap, lds, sds, seg_tex, seg_light, texinfo, texdata, colormap,
                                        ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n{plight}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12nn-b @ ({vx},{vy},{va},L{plight}) != oracle"


def test_wall_render_wideindex_byte_exact(tmp_path):
    """M12nn-c — WIDE TEXEL INDEX: for a full E1M1-scale COMBINED texture table the absolute texel index
    (col_base[x] = seg_texbase + texcol*texheight) reaches ~793k = 5 nibbles, too wide for the M12mm2 3-nibble
    leaf / 4-nibble col_base element. This rung adds the WIDE renderer variants — seg_pass1_leaf_body_mtlw
    (8-nibble col-array stride, 5-nibble base via store_col_field5), load_col_mtw (5-nibble base_reg), and
    leaf_body_w (5-nibble idx) — all additive (the narrow macros + their tests are untouched). To exercise the
    5th nibble GENUINELY on the fast square room, the combined table is PADDED with 65536 leading texels so
    every seg_texbase > 65535 (needs 5 nibbles); the narrow 3-nibble path would truncate the base and read the
    padding (=> wrong texels). Per-seg textures + per-seg light as in M12nn-a; byte-exact vs the same oracle
    across 5 viewpoints (the oracle samples the standalone texels, so the pad is invisible to it)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    cmap = bake_bsp(WadFile.from_path(ROOM), "MAP01")
    verts = cmap.vertexes
    wad = WadFile.from_path(ASSET)
    colormap = wad.colormap()
    lds = WadFile.from_path(ROOM).linedefs("MAP01")
    sds = WadFile.from_path(ROOM).sidedefs("MAP01")

    seg_tex = ["STEP4", "A-YELLOW", "STEP4", None]
    seg_light = [1, 9, 17, 25]
    combined, texinfo = _build_combined_textures(wad, ["STEP4", "A-YELLOW", None])
    PAD = 65536                                               # prepend so every texbase > 65535 (=> 5 nibbles)
    combined = [0] * PAD + combined                          # PAD is a power of 2 => slice alignment unchanged
    texinfo = {k: (b + PAD, th, tw) for k, (b, th, tw) in texinfo.items()}
    texdata = {nm: (texture_texels(c := composite_texture(wad, {t.name: t for t in wad.texture_defs()}[nm])),
                    len(c), len(c[0])) for nm in ("STEP4", "A-YELLOW")}

    ceil_h, floor_h = 128, 0
    viewz = (floor_h + 41) << 16
    worldtop = ceil_h - (viewz >> 16)
    ceil_color, floor_color = 5, 109
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    A45, A135, A225, A315 = 0x20000000, 0x60000000, 0xA0000000, 0xE0000000

    VIEWPOINTS = [
        (128, 128, A45), (128, 128, A135), (128, 128, A225), (128, 128, A315), (200, 128, A45),
    ]

    tex = _texel_table("tex", combined, "per_entry", over_align=True)
    cm = compile_colormap("cm", wad, lights=COLORMAP_LIGHTS, over_align=True)
    palette = compile_palette("palette", wad)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    xorby_blocks = {}                                        # M12pp: seg{si}_xorby blocks, emitted once each

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
            fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                      ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                      ("seg_segangle", 8, seg.angle), ("seg_texoff", 8, texoff & 0xFFFFFFFF),
                      ("seg_texbase", 5, texbase), ("seg_texheight", 4, th_s), ("seg_tw", 8, tw_s),
                      ("seg_hm", 3, th_s - 1), ("seg_light", 2, seg_light[si])]
            xorby_blocks[si] = _seg_xorby_block(si, fields)  # ceilfix/floorfix/seg_ceil/viewzw are static (1 sector)
            out += _seg_xorby_use(si, clear=_M12PP_CLEAR)
        return out

    bsp = _bsp_as_code("room", cmap, done_label="bsp_done", subsector_action=subsector_action)
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # the shared per-seg xorby blocks (emitted once)

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
        pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                     f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                     f"col_heightmask + {8 * x}*dw")
        for y in range(cfg.H):                            # M12oo: the shared-compare trampoline (y runtime, set by load_col)
            pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtlw {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx_raw: hex.vec 8", "vy_raw: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: the xorby block's fcall/fret return register
        f"ceilfix: hex.vec 8, {(ceil_h << 16) & 0xFFFFFFFF}", f"floorfix: hex.vec 8, {(floor_h << 16) & 0xFFFFFFFF}",
        f"viewz: hex.vec 8, {viewz & 0xFFFFFFFF}", f"viewzw: hex.vec 8, {(viewz >> 16) & 0xFFFFFFFF}",
        f"seg_ceil: hex.vec 8, {ceil_h & 0xFFFFFFFF}", "worldtop: hex.vec 8",   # M12pp: worldtop now leaf-computed
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
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 8, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "wideindex.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "wideindex.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = _oracle_multilight_frame(rm, cmap, lds, sds, seg_tex, seg_light, texinfo, texdata, colormap,
                                        ceil_h, floor_h, viewz, worldtop, ceil_color, floor_color, vx, vy, va)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12nn-c @ ({vx},{vy},{va}) != oracle"


E1M1_WAD = "tests/fixtures/freedoom_e1m1.wad"


def test_wall_render_e1m1_geometry_wallbg_byte_exact(tmp_path):
    """M12nn-d — FULL E1M1 GEOMETRY runtime frame (proxy for the capstone): the REAL 681-node BSP walk drives
    pass 1 over ALL 575 one-sided segs of E1M1, with the runtime player-subsector logic that the square room
    couldn't exercise — at the FIRST subsector visited (= the player's subsector, order[0]) it sets the runtime
    viewz (player sector floor + VIEWHEIGHT) used by every seg's worldtop/span AND fills the two-band background
    at that subsector's sector light (a shared fcall bg-fill leaf = render_background_reg, guarded by a runtime
    bg_done flag). Each seg uses its OWN baked sector ceil/floor/light with worldtop = seg_ceil - viewz_world
    (runtime). drawn[] now CLIPS real occlusion across 575 segs. To keep the assemble fast (the real 793k-texel
    table is the FINAL capstone rung), every wall is the flat WALL_BG sentinel (1x1) and the oracle's
    _wall_texture is forced to None — so this validates the whole walk/viewz/bg/light/occlusion INTEGRATION on
    real geometry, byte-exact, without the big texture table. Several viewpoints (spawn + rotations + other
    sectors => the player-subsector viewz/light/bg vary)."""
    cfg = Config()
    mw = WadFile.from_path(E1M1_WAD)
    cmap = bake_bsp(mw, "E1M1")
    verts = cmap.vertexes
    lds = mw.linedefs("E1M1"); sds = mw.sidedefs("E1M1"); secs = mw.sectors("E1M1")
    scene = build_scene(mw, mw, "E1M1")
    rm = ReferenceModel(cfg)
    rm._wall_texture = lambda *a, **k: None                  # proxy: every wall flat-fills WALL_BG

    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16

    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    things = mw.things("E1M1")
    VIEWPOINTS = [(spx, spy, sp.angle),
                  (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    seen = {(spx, spy)}
    for t in things:                                          # other sectors -> player viewz/light/bg vary
        if (t.x, t.y) not in seen:
            seen.add((t.x, t.y)); VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break

    combined = [WALL_BG]                                      # the 1x1 WALL_BG sentinel (the only texel)
    tex = _texel_table("tex", combined, "per_entry", over_align=True)
    cm = compile_colormap("cm", mw, lights=COLORMAP_LIGHTS, over_align=True)
    palette = compile_palette("palette", mw)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

    colormap = scene.asset_wad.colormap()
    _cid = [0]                                                # unique label id per EMISSION (a leaf is emitted
    #                                                           twice by _bsp_as_code — once per node branch)
    xorby_blocks = {}                                         # M12pp: seg{si}_xorby blocks, emitted once each

    def subsector_action(s):
        ss = cmap.subsectors[s]
        cid = _cid[0]; _cid[0] += 1
        # player-subsector setup (runs only at the FIRST subsector visited = order[0] = the player's):
        psec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        viewz_val = rm.view_z(psec.floor_h)
        viewzw_val = viewz_val >> 16
        prow = lrow(psec.light)
        out = [
            f"    hex.if0 1, bg_done, e1pset{cid}",          # bg_done==0 (first/player subsector) -> set player state
            f"    ;e1psegs{cid}",
            f"  e1pset{cid}:",
            f"    hex.set 8, viewz, {viewz_val & 0xFFFFFFFF}",
            f"    hex.set 8, viewzw, {viewzw_val & 0xFFFFFFFF}",
            f"    hex.set 2, bgceil, {colormap[prow][CEIL_BG]}",
            f"    hex.set 2, bgfloor, {colormap[prow][FLOOR_BG]}",
            "    stl.fcall bg_fill_leaf, bg_ret",
            "    hex.set 1, bg_done, 1",
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
            fields = [("seg_v1x", 8, (v1x << 16) & 0xFFFFFFFF), ("seg_v1y", 8, (v1y << 16) & 0xFFFFFFFF),
                      ("seg_v2x", 8, (v2x << 16) & 0xFFFFFFFF), ("seg_v2y", 8, (v2y << 16) & 0xFFFFFFFF),
                      ("seg_segangle", 8, seg.angle), ("seg_texoff", 8, texoff & 0xFFFFFFFF),
                      ("seg_texbase", 5, 0), ("seg_texheight", 4, 1), ("seg_tw", 8, 1), ("seg_hm", 3, 0),
                      ("seg_light", 2, lrow(ssec.light)),                # WALL_BG sentinel (proxy) tex fields
                      ("ceilfix", 8, (ssec.ceil_h << 16) & 0xFFFFFFFF),
                      ("floorfix", 8, (ssec.floor_h << 16) & 0xFFFFFFFF),
                      ("seg_ceil", 8, ssec.ceil_h & 0xFFFFFFFF)]        # M12pp: worldtop = seg_ceil - viewzw in-leaf
            xorby_blocks[si] = _seg_xorby_block(si, fields)
            out += _seg_xorby_use(si, clear=_M12PP_CLEAR)
        return out

    bsp = _bsp_as_code("e1", cmap, done_label="bsp_done", subsector_action=subsector_action)
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # M12pp: the shared per-seg xorby blocks (once)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",   # viewx = (low 8 of the map coord) << 16 (16.16)
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        ";e1_bspcode_walk", "bsp_done:",                      # the walk fills col arrays + (player ss) the bg
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                     f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                     f"col_heightmask + {8 * x}*dw")
        for y in range(cfg.H):                            # M12oo: the shared-compare trampoline (y runtime, set by load_col)
            pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtlw {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        "bg_fill_leaf:",
        f"frame.render_background_reg framebuffer, bgceil, bgfloor, {cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        "stl.fret bg_ret",
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "viewz: hex.vec 8", "viewzw: hex.vec 8", "bgceil: hex.vec 2", "bgfloor: hex.vec 2",
        "bg_done: hex.vec 1", "bg_ret: ;0",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: xorby block fcall/fret return register
        "ceilfix: hex.vec 8", "floorfix: hex.vec 8",
        "seg_ceil: hex.vec 8", "worldtop: hex.vec 8",     # M12pp: seg_ceil baked (pure); worldtop leaf-computed
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
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 8, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "e1m1geo.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "e1m1geo.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    for vx, vy, va in VIEWPOINTS:
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        fj.run(out, io_device=screen, print_time=False, print_termination=False)
        assert bytes(screen.pixel_indices) == bytes(want), f"M12nn-d @ ({vx},{vy},{va}) != oracle"


E1M1_GOLDEN = "0b817e4a126026207f40327cb32b68685efd47572f79661ff7136e752e566c0e"


def test_wall_render_e1m1_full_frame_golden(tmp_path):
    """M12nn — THE CAPSTONE: the full E1M1 runtime wall frame with REAL textures, byte-exact vs the oracle and
    matching the published spawn golden hash. Everything from M12nn-d (the 681-node walk over 575 one-sided
    segs, runtime player-subsector viewz + walk-driven background, per-seg worldtop, drawn[] occlusion,
    per-seg multi-light, the off-screen-wall sentinel) NOW with each wall sampling its OWN texture out of a
    single COMBINED dispatch table of ALL 70 E1M1 wall textures (downscaled like the oracle's _wall_texture;
    ~198k texels => the 5-nibble wide-index path from M12nn-c). One assemble (the big 198k texel table; watch
    the time), several stdin viewpoints byte-exact vs render_wall_frame, and the spawn frame hashes to the
    golden test_wall_frame.py key. The real playable wall renderer."""
    cfg = Config()
    rm = ReferenceModel(cfg)                                  # REAL textures (no _wall_texture override)
    mw = WadFile.from_path(E1M1_WAD)
    cmap = bake_bsp(mw, "E1M1")
    verts = cmap.vertexes
    lds = mw.linedefs("E1M1"); sds = mw.sidedefs("E1M1"); secs = mw.sectors("E1M1")
    scene = build_scene(mw, mw, "E1M1")
    colormap = scene.asset_wad.colormap()
    horizon = cfg.VIEW_H // 2
    proj = cfg.PROJECTION << 16
    defs = {d.name.upper(): d for d in mw.texture_defs("TEXTURE1")}

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
        if rm._wall_texture(mw, sd.middle, cache) is not None:
            names.add(sd.middle.upper())
    combined, info = [], {}
    for nm in sorted(names) + [None]:
        key = nm if nm else "__WALLBG__"
        if nm is None:
            th, tw, texels = 1, 1, [WALL_BG]
        else:
            c = downscale_canvas(composite_texture(mw, defs[nm]), rm.downscale)
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
        t = rm._wall_texture(mw, sd.middle, cache)
        seg_texinfo[si] = info[sd.middle.upper()] if t is not None else info["__WALLBG__"]

    sp = spawn_state(mw, "E1M1")
    spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
    things = mw.things("E1M1")
    VIEWPOINTS = [(spx, spy, sp.angle),                       # the golden viewpoint FIRST
                  (spx, spy, (sp.angle + 0x40000000) & 0xFFFFFFFF)]
    seen = {(spx, spy)}
    for t in things:
        if (t.x, t.y) not in seen:
            seen.add((t.x, t.y)); VIEWPOINTS.append((t.x, t.y, sp.angle))
        if len(VIEWPOINTS) >= 4:
            break

    # PRODUCTION layout (over_align=False, like build_doom): drops the 2^n table padding so the whole renderer
    # (table + framebuffer + LUTs + the 16K-pixel pass-2 unroll) fits the 2**23 flat budget (asserted below, R4).
    tex = _texel_table("tex", combined, "per_entry", over_align=False)
    cm = compile_colormap("cm", mw, lights=COLORMAP_LIGHTS, over_align=False)
    palette = compile_palette("palette", mw)
    tantoangle = generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)
    finesine = generate_trig_idioms_fj("finesine", cfg.TRIG_N, 16)
    finetangent = generate_finetangent_lut_fj("finetangent", cfg.TRIG_N)
    viewangletox = generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N)
    xtoviewangle = generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N)

    def lrow(light):
        return max(0, min(COLORMAP_LIGHTS - 1, light >> LIGHT_SHIFT))

    _cid = [0]
    xorby_blocks = {}                                         # M12pp: seg{si}_xorby blocks, emitted once each

    def subsector_action(s):
        ss = cmap.subsectors[s]
        cid = _cid[0]; _cid[0] += 1
        psec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        viewz_val = rm.view_z(psec.floor_h)
        prow = lrow(psec.light)
        out = [
            f"    hex.if0 1, bg_done, e1pset{cid}",
            f"    ;e1psegs{cid}",
            f"  e1pset{cid}:",
            f"    hex.set 8, viewz, {viewz_val & 0xFFFFFFFF}",
            f"    hex.set 8, viewzw, {(viewz_val >> 16) & 0xFFFFFFFF}",
            f"    hex.set 2, bgceil, {colormap[prow][CEIL_BG]}",
            f"    hex.set 2, bgfloor, {colormap[prow][FLOOR_BG]}",
            "    stl.fcall bg_fill_leaf, bg_ret",
            "    hex.set 1, bg_done, 1",
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
                      ("seg_ceil", 8, ssec.ceil_h & 0xFFFFFFFF)]   # M12pp: worldtop = seg_ceil - viewzw in-leaf
            xorby_blocks[si] = _seg_xorby_block(si, fields)
            out += _seg_xorby_use(si, clear=_M12PP_CLEAR)
        return out

    bsp = _bsp_as_code("e1", cmap, done_label="bsp_done", subsector_action=subsector_action)
    xorby = [ln for blk in xorby_blocks.values() for ln in blk]   # M12pp: the shared per-seg xorby blocks (once)

    pass1 = [
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        "hex.input_dec_uint 8, viewangle, bad",
        "hex.mov 8, viewx, vx", "hex.shl_hex 8, 4, viewx",
        "hex.mov 8, viewy, vy", "hex.shl_hex 8, 4, viewy",
        ";e1_bspcode_walk", "bsp_done:",
    ]
    pass2 = []
    for x in range(cfg.VIEW_W):
        pass2.append(f"frame.load_col_mtw col_top + {8 * x}*dw, col_bottom + {8 * x}*dw, col_base + {8 * x}*dw, "
                     f"col_light + {8 * x}*dw, col_step + {8 * x}*dw, col_frac0 + {8 * x}*dw, "
                     f"col_heightmask + {8 * x}*dw")
        for y in range(cfg.H):                            # M12oo: the shared-compare trampoline (y runtime, set by load_col)
            pass2.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")

    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *pass1, *pass2,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "bad: stl.loop",
        "pixel_leaf:", "frame.leaf_body_w",
        "compare_y:", "frame.compare_y_body",             # M12oo shared pass-2 clip (emitted once)
        "seg_pass1_leaf:",
        f"frame.seg_pass1_leaf_body_mtlw {cfg.CENTERY}, {cfg.TEXTURE_DOWNSCALE}, {cfg.VIEW_H - 1}, {proj}",
        "bg_fill_leaf:",
        f"frame.render_background_reg framebuffer, bgceil, bgfloor, {cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        "stl.fret bg_ret",
        *xorby,                                           # M12pp: the shared per-seg xorby blocks (fcall'd SET/CLEAR)
        bsp,
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "vx: hex.vec 10", "vy: hex.vec 10", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "viewz: hex.vec 8", "viewzw: hex.vec 8", "bgceil: hex.vec 2", "bgfloor: hex.vec 2",
        "bg_done: hex.vec 1", "bg_ret: ;0",
        "seg_v1x: hex.vec 8", "seg_v1y: hex.vec 8", "seg_v2x: hex.vec 8", "seg_v2y: hex.vec 8",
        "seg_segangle: hex.vec 8", "seg_texoff: hex.vec 8",
        "seg_texbase: hex.vec 5", "seg_texheight: hex.vec 4", "seg_tw: hex.vec 8", "seg_hm: hex.vec 3",
        "seg_light: hex.vec 2", "xb_ret: ;0",             # M12pp: xorby block fcall/fret return register
        "ceilfix: hex.vec 8", "floorfix: hex.vec 8",
        "seg_ceil: hex.vec 8", "worldtop: hex.vec 8",     # M12pp: seg_ceil baked (pure); worldtop leaf-computed
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
        f"col_top: rep({cfg.VIEW_W}, i) hex.vec 8, 1", f"col_bottom: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_base: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_step: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_frac0: rep({cfg.VIEW_W}, i) hex.vec 8, 0", f"col_heightmask: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"col_light: rep({cfg.VIEW_W}, i) hex.vec 8, 0",
        f"drawn: rep({cfg.VIEW_W}, i) hex.vec 4, 0",
        tantoangle, finesine, finetangent, viewangletox, xtoviewangle, tex, cm, palette,
    ])
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    p = tmp_path / "e1m1full.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "e1m1full.fjm"
    fj.assemble([consts.resolve(), FIXED_POINT_FJ.resolve(), PRESENT_FJ.resolve(),
                 PROJECTION_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)

    # R4: the WHOLE runtime renderer (the 198k-texel combined table + framebuffer + LUTs + the fully unrolled
    # 16K-pixel pass 2 + the 681-node walk) MUST run on the FLAT path -- a silent paged/hybrid fallback would
    # otherwise pass. Its span exceeds the DEFAULT 2**23 budget (the renderer ADDS the per-pixel unroll on top of
    # the table set build_doom's ledger measures), so per DESIGN §1.2 the flat limit is RAISED (RAM-only cost);
    # asserted over a build that actually CONTAINS the renderer footprint (cf. build.py:35), production layout.
    span = max(s.segment_start + s.segment_length for s in Reader(out).memory_segments)
    print(f"\nM12nn renderer flat span = {span:,} words ({span / (1 << 20):.2f}M; "
          f"default FLAT_MAX_WORDS = {FLAT_MAX_WORDS:,} = 2**23)")
    # SPAN BREAKDOWN (bisected via Reader.memory_segments, corrected -- the combined table is NOT the dominant
    # chunk, an earlier wrong guess): the ~40M pre-M12oo span was ~21M the BSP WALK (575 segs' baked per-seg/
    # per-node hex.set constants, emitted twice per leaf) + ~16M the fully-unrolled 16K-pixel PASS-2 clip + only
    # ~3.5M the combined texel table. M12oo replaced the inlined per-pixel pass-2 clip (two hex.cmp x 16K) with
    # the SHARED-COMPARE TRAMPOLINE (one compare_y body + a cheap per-pixel wflip): 40.3M -> 31.2M (-9M / ~23%).
    # M12pp then replaced the per-seg baked hex.set walk constants (each pays an @-dispatch) with hex.xor_by +
    # xor-INVOLUTION self-zeroing (no @): 31.2M -> 23.4M (-7.8M / ~25%), and the assemble 1090s -> 262s (the @
    # dispatches were super-linearly expensive). Cumulative since M12nn: 40.3M -> 23.4M (-42%). Remaining levers:
    # the BSP NODE consts + skeleton (M12qq single-emission, M12rr shrink) + the table; flat limit stays RAISED
    # (RAM-only cost) until those land. (Don't promise a number -- MEASURE.)
    RENDER_FLAT_WORDS = 1 << 26
    for k, (vx, vy, va) in enumerate(VIEWPOINTS):
        want = rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene)
        screen = _ScreenWithInput(f"{vx}\n{vy}\n{va}\n".encode())
        term = fj.run(out, io_device=screen, print_time=False, print_termination=False,
                      flat_max_words=RENDER_FLAT_WORDS)
        assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} not flat @ {span} words"
        got = bytes(screen.pixel_indices)
        assert got == bytes(want), f"M12nn @ ({vx},{vy},{va}) != oracle"
        if k == 0:                                            # the spawn viewpoint must hash to the golden
            assert frame_hash(got) == E1M1_GOLDEN, f"M12nn spawn hash {frame_hash(got)} != golden"
