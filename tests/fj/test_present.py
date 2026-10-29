"""The present-layer macros (src/fj/present.fj) against the screen API (flipjump io_devices/README.md): each macro is
PURE EMIT, so the program's captured output must be exactly the bytes doomfj.screenwire -- the repo's one copy of the
API's numbers -- encodes for the same command. And the device itself must accept a whole boot + frame the macros
print (a stream the API refuses would raise there), which is the check that screenwire and the device agree."""
from pathlib import Path

import flipjump as fj
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import screenwire as SW
from doomfj.config import Config
from doomfj.harness import W

PRESENT_FJ = Path("src/fj/present.fj")


def _run(tmp_path, name, body, expected: bytes):
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [consts.resolve(), PRESENT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: present output != the API's bytes"


def test_init_screen_command_bytes(tmp_path):
    """init_screen: [0x01][W:2 LE][H:2 LE][format = BPP:1] from the config SSOT"""
    c = Config()
    assert c.BPP == SW.FORMAT
    _run(tmp_path, "init_screen", ["present.init_screen"], SW.init_screen(c.W, c.H))


def test_select_palette_command(tmp_path):
    _run(tmp_path, "select_palette", ["present.select_palette 0", "present.select_palette 13"],
         SW.select_palette(0) + SW.select_palette(13))


def test_draw_collines_and_end_frame(tmp_path):
    """draw_collines opens the command; end_frame closes it (END_CMD) and presents"""
    _run(tmp_path, "frame", ["present.draw_collines", "present.end_frame"],
         bytes([SW.OP_DRAW_COLLINES]) + SW.FRAME_TAIL)
    assert SW.FRAME_TAIL == bytes([SW.END_CMD, SW.OP_PRESENT])


def test_window_chrome_commands(tmp_path):
    title = "DOOM"
    big = sum(ch << (8 * i) for i, ch in enumerate(title.encode()))
    _run(tmp_path, "chrome", [f"present.set_window_title {big}, {len(title)}", "present.set_max_fps 35",
                              "present.set_window_icon_header 2, 1", "stl.output_char 7", "stl.output_char 0"],
         SW.set_window_title(title) + SW.set_max_fps(35) + SW.set_window_icon(2, 1, [7, 0]))


def test_the_device_accepts_a_boot_and_a_frame_the_macros_print(tmp_path):
    """the macros' stream through the REAL device: init, a palette, the chrome, one column, end_frame -- presented"""
    c = Config()
    pal = [(k, k, k) for k in range(256)]
    column = SW.column(0, [("fill", c.H, 5)], c.H)
    body = (["present.init_screen", *SW.fj_lines(SW.define_palette(0, pal)), "present.set_max_fps 35",
             "present.draw_collines", *SW.fj_lines(column), "present.end_frame", "present.select_palette 0",
             "present.draw_collines", "present.end_frame"])
    consts = c.emit_fj_consts(tmp_path / "fj_consts.fj")
    src = tmp_path / "boot.fj"
    src.write_text("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n", encoding="utf-8")
    out = tmp_path / "boot.fjm"
    fj.assemble([consts.resolve(), PRESENT_FJ.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    assert screen.frame_count == 2 and screen.max_fps == 35
    want = [0] * (c.W * c.H)
    for y in range(c.H):
        want[y * c.W] = 5
    assert list(screen.pixel_indices) == want
