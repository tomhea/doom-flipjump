"""M12k (F5) — isolated unit tests for the per-pixel render macros (src/fj/wall_render.fj, frame_render.fj)
over a real (tiny) M8 texture + colormap. These are the core per-pixel pipeline the M12 wall renderer is
built on; here they are driven directly (not via build.py) and checked byte-exact against the H5 oracle
(render_textured_column / render_unroll_frame), which is the same golden the integration paths use (D12).
No precondition/@Assumes on these emit-and-advance macros ⇒ sanity + edge (DDA wrap, multi-pixel), no
should-fail."""
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj.config import Config
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, CEIL_BG, FLOOR_BG
from doomfj.texturecompiler import compile_colormap, compile_texture, composite_texture, texture_texels
from doomfj.wad import WadFile

WALL_FJ = Path("src/fj/wall_render.fj")
FRAME_FJ = Path("src/fj/frame_render.fj")
PRESENT_FJ = Path("src/fj/present.fj")
ASSET = "tests/fixtures/freedoom_assets.wad"
TEX = "A-YELLOW"   # 16x8 (downscale 1) ⇒ texheight 8 (pow2), texwidth 16


def _texels(downscale=1):
    wad = WadFile.from_path(ASSET)
    d = {t.name: t for t in wad.texture_defs()}[TEX]
    canvas = composite_texture(wad, d)
    return texture_texels(canvas), len(canvas), len(canvas[0])   # texels, height, width


# ── wall.column_step (M11b textured column, text-output form) ────────────────

def test_wall_column_step_byte_exact_vs_oracle(tmp_path):
    """Drive `count` rows of wall.column_step over A-YELLOW + a 2-light colormap; the emitted lit bytes
    match the oracle's render_textured_column exactly (the DDA + texel sample + colormap apply pipeline)."""
    wad = WadFile.from_path(ASSET)
    texels, th, _tw = _texels()
    colormap = wad.colormap()
    texcol, light, count, step, frac0 = 3, 1, 12, 0x0140, 0x0000   # 8.8 step 1.25, start at texel 0
    base = texcol * th

    tex = compile_texture("tex", wad, TEX, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=False)
    body = [f"hex.set 4, frac, {frac0}", f"rep({count}, r) wall.column_step {base}, {light}"]
    data = ["frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "pal: hex.vec 2",
            "cmidx: hex.vec 4", "lit: hex.vec 2", f"step: hex.vec 4, {step}",
            f"heightmask: hex.vec 3, {th - 1}", tex, cm]
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / "wall_col.fj"
    p.write_text(prog, encoding="utf-8")

    expected = b"".join(f"{b:02x}\n".encode() for b in ReferenceModel().render_textured_column(
        texels, th, texcol, colormap, light, count=count, frac0=frac0, step=step))
    out = tmp_path / "wall_col.fjm"
    fj.assemble([WALL_FJ.resolve(), p.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    assert io.get_output(allow_incomplete_output=True) == expected


# ── frame.setup_col + frame.pixel + frame.leaf_body (M11c, register framebuffer) ──

def test_frame_pixel_leaf_byte_exact_vs_oracle(tmp_path):
    """A tiny full-unroll frame (width x count) through the shared-fcall leaf, written into the hex.vec2
    register framebuffer and presented (0x06); the device pixels match the oracle's render_unroll_frame."""
    cfg = Config()
    wad = WadFile.from_path(ASSET)
    texels, th, tw = _texels()
    colormap = wad.colormap()
    light, width, count, step, frac0 = 1, 4, 5, 0x0140, 0x0000

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    from doomfj.texturecompiler import compile_palette
    palette = compile_palette("palette", wad)

    render = []
    for x in range(width):
        render.append(f"frame.setup_col {(x % tw) * th}, {light}, {step}, {frac0}")
        for row in range(count):
            render.append(f"frame.pixel framebuffer + {2 * (row * cfg.W + x)}*dw")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0", tex, cm, palette,
    ])
    p = tmp_path / "frame.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "frame.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    want = ReferenceModel().render_unroll_frame(texels, th, tw, colormap, light,
                                                width=width, count=count, frac0=frac0, step=step)
    assert bytes(screen.pixel_indices) == want


# ── frame.setup_col_reg: RUNTIME per-column params -> framebuffer (M12aa) ──

def test_frame_setup_col_reg_runtime_column(tmp_path):
    """Render ONE wall column with RUNTIME params (base/light/step/frac0 sourced from memory registers via
    frame.setup_col_reg, as the M12 renderer will) into column `x` rows [top, top+count) of the register
    framebuffer, then present (0x06). The device pixels match the oracle's render_textured_column placed at
    that column — proving the shared leaf works with runtime (not compile-time-inlined) per-column params."""
    cfg = Config()
    wad = WadFile.from_path(ASSET)
    texels, th, _tw = _texels()
    colormap = wad.colormap()
    # step 0.5/row over 16 rows keeps the texel-v in [0,7] for the th=8 test texture (the M11c leaf masks
    # the heightmask in nibble 1, valid for texheight>=16 or v<th; real wall textures are >=16 tall).
    texcol, light, count, step, frac0, top, x = 3, 1, 16, 0x0080, 0x0000, 20, 5
    base = texcol * th                                   # = texcol*texheight (the renderer's base_reg)

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    from doomfj.texturecompiler import compile_palette
    palette = compile_palette("palette", wad)

    # base/light/step/frac0 live in memory (runtime), moved into the leaf regs by setup_col_reg.
    render = ["frame.setup_col_reg base_in, light_in, step_in, frac0_in"]
    for row in range(count):
        render.append(f"frame.pixel framebuffer + {2 * ((top + row) * cfg.W + x)}*dw")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        f"base_in: hex.vec 3, {base}", f"light_in: hex.vec 2, {light}",
        f"step_in: hex.vec 4, {step}", f"frac0_in: hex.vec 4, {frac0}",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0", tex, cm, palette,
    ])
    p = tmp_path / "rtcol.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "rtcol.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    col = ReferenceModel().render_textured_column(texels, th, texcol, colormap, light,
                                                  count=count, frac0=frac0, step=step)
    want = bytearray(cfg.FB_SIZE)
    for r in range(count):
        want[(top + r) * cfg.W + x] = col[r]
    assert bytes(screen.pixel_indices) == bytes(want)


# ── frame.pixel_clipped: RUNTIME [top,bottom] row clip over a full unrolled column (M12bb) ──

def test_frame_pixel_clipped_runtime_span(tmp_path):
    """Unroll ALL screen rows of one column through frame.pixel_clipped with a RUNTIME [top,bottom] span
    (in registers); only rows top..bottom render (the leaf advances the DDA only there, frac0 at `top`).
    The device frame matches render_textured_column placed at [top,bottom], everything else background 0."""
    cfg = Config()
    wad = WadFile.from_path(ASSET)
    texels, th, _tw = _texels()
    colormap = wad.colormap()
    texcol, light, step, frac0, x = 3, 1, 0x0080, 0x0000, 5
    top, bottom = 20, 35                                  # runtime span; count = 16 rows, texel-v in [0,7]
    count = bottom - top + 1
    base = texcol * th

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    from doomfj.texturecompiler import compile_palette
    palette = compile_palette("palette", wad)

    render = ["frame.setup_col_reg base_in, light_in, step_in, frac0_in"]
    for y in range(cfg.H):                               # unroll EVERY row; the clip picks [top,bottom]
        render.append(f"frame.pixel_clipped {y}, framebuffer + {2 * (y * cfg.W + x)}*dw, top_in, bottom_in")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        f"base_in: hex.vec 3, {base}", f"light_in: hex.vec 2, {light}",
        f"step_in: hex.vec 4, {step}", f"frac0_in: hex.vec 4, {frac0}",
        f"top_in: hex.vec 8, {top}", f"bottom_in: hex.vec 8, {bottom}",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        f"rows: rep({cfg.H}, i) hex.vec 2, i", tex, cm, palette,   # row-constant table for pixel_clipped
    ])
    p = tmp_path / "clipcol.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "clipcol.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    col = ReferenceModel().render_textured_column(texels, th, texcol, colormap, light,
                                                  count=count, frac0=frac0, step=step)
    want = bytearray(cfg.FB_SIZE)
    for r in range(count):
        want[(top + r) * cfg.W + x] = col[r]
    assert bytes(screen.pixel_indices) == bytes(want)


# ── frame.pixel_tramp + compare_y: the M12oo SHARED-COMPARE TRAMPOLINE clip (replaces pixel_clipped) ──

def test_frame_pixel_tramp_runtime_span(tmp_path):
    """Unroll ALL screen rows of one column through frame.pixel_tramp (the M12oo trampoline) with a RUNTIME
    [top,bottom] span — only rows top..bottom render, the rest skip via the shared compare_y body. y is a
    runtime register zeroed before the column and incremented at the end of each pixel; top/bottom live in
    registers the shared compare_y reads. Byte-exact vs the SAME render_textured_column placement the
    pixel_clipped twin checks (proves the trampoline clip == the inlined clip). Also exercises the off-screen
    sentinel: with top=1,bottom=0 every row must skip (blank column)."""
    cfg = Config()
    wad = WadFile.from_path(ASSET)
    texels, th, _tw = _texels()
    colormap = wad.colormap()
    texcol, light, step, frac0, x = 3, 1, 0x0080, 0x0000, 5
    top, bottom = 20, 35                                  # runtime span; count = 16 rows, texel-v in [0,7]
    count = bottom - top + 1
    base = texcol * th

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    tex = compile_texture("tex", wad, TEX, over_align=True, downscale=1)
    cm = compile_colormap("cm", wad, lights=2, over_align=True)
    from doomfj.texturecompiler import compile_palette
    palette = compile_palette("palette", wad)

    render = ["frame.setup_col_reg base_in, light_in, step_in, frac0_in",
              "hex.zero 2, y"]                            # reset the trampoline row counter for this column
    for y in range(cfg.H):                                # unroll EVERY row; the trampoline clip picks [top,bottom]
        render.append(f"frame.pixel_tramp framebuffer + {2 * (y * cfg.W + x)}*dw")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen", *render,
        "present.set_palette palette", "present.update_screen_reg framebuffer", "stl.loop",
        "pixel_leaf:", "frame.leaf_body",
        "compare_y:", "frame.compare_y_body",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
        f"base_in: hex.vec 3, {base}", f"light_in: hex.vec 2, {light}",
        f"step_in: hex.vec 4, {step}", f"frac0_in: hex.vec 4, {frac0}",
        f"top: hex.vec 2, {top}", f"bottom: hex.vec 2, {bottom}",
        "y: hex.vec 2", "ret_reg: ;0",
        "frac: hex.vec 4", "v3: hex.vec 3", "idx: hex.vec 3", "cmidx: hex.vec 4",
        "lit: hex.vec 2", "base_reg: hex.vec 3", "step: hex.vec 4",
        f"heightmask: hex.vec 3, {th - 1}", "pixel_ret: ;0",
        tex, cm, palette,
    ])
    p = tmp_path / "tramp.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "tramp.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)

    col = ReferenceModel().render_textured_column(texels, th, texcol, colormap, light,
                                                  count=count, frac0=frac0, step=step)
    want = bytearray(cfg.FB_SIZE)
    for r in range(count):
        want[(top + r) * cfg.W + x] = col[r]
    assert bytes(screen.pixel_indices) == bytes(want)


# ── frame.render_background (M12hh): the M9 two-band background fill, byte-exact vs render_frame ──

def test_render_background_two_band_byte_exact(tmp_path):
    """frame.render_background fills the hex.vec2 framebuffer's top `horizon` rows with the (already
    colormapped) ceiling byte and the rest with the floor byte — the empty-view two-band clear the wall
    renderer paints over. Byte-exact vs the band layout of reference_model.render_frame (top VIEW_H//2
    rows ceil, the rest floor), using real colormapped band colors at a chosen light row."""
    cfg = Config()
    colormap = WadFile.from_path(ASSET).colormap()
    row = 1                                   # a valid colormap light row (CEIL_BG/FLOOR_BG from the oracle)
    ceil_color, floor_color = colormap[row][CEIL_BG], colormap[row][FLOOR_BG]
    assert ceil_color != floor_color          # the bands must be distinguishable
    horizon = cfg.VIEW_H // 2

    want = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):
        c = ceil_color if y < horizon else floor_color
        for x in range(cfg.VIEW_W):
            want[y * cfg.VIEW_W + x] = c

    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    main = "\n".join([
        "stl.startup_and_init_all", "present.init_screen",
        f"frame.render_background framebuffer, {ceil_color}, {floor_color}, "
        f"{cfg.VIEW_W}, {cfg.VIEW_H}, {horizon}",
        "present.update_screen_reg framebuffer", "stl.loop",
        f"framebuffer: hex.vec {2 * cfg.FB_SIZE}",
    ]) + "\n"
    p = tmp_path / "bg.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp_path / "bg.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), FRAME_FJ.resolve(), p.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    assert bytes(screen.pixel_indices) == bytes(want)
