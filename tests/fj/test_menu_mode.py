"""M3 — the MODE BRANCH: one program, two frame producers, chosen by a persisted cell.

This is the shape `emit_wall_renderer(menu=True)` emits, in a program that assembles in a second
instead of an hour: poll the keyboard, branch on `mode`, and either paint the baked menu or fall
through to the world path -- both ending at ONE shared tail whose last line is the
`stl.output_char 0xFF` that `selfreset.emit_reset_part` asserts on.

The world path here is a stub (a single flat column-run frame), because what is under test is the
BRANCH, not the renderer. If the branch is wrong the two pictures swap, merge, or the stream
desynchronises -- all of which show up as a wrong frame.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.interpreter.io_devices.pygame_window import PcIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import fj as menu_fj, pixels

CFG = Config()
VW, VH = CFG.VIEW_W, CFG.VIEW_H
LINES = ["DOOM ON FLIPJUMP", "", "NEW GAME", "QUIT"]
COLOURS = (0, 4, 176)
STUB = 7                     # the world stub paints every column this colour
SRC = [Path("src/fj") / "present.fj", Path("src/fj") / "input.fj"]


def _program(mode_init):
    world = []
    for x in range(VW):                       # the world STUB: one flat frame, no renderer
        world += ["    stl.output_char %d" % x, "    stl.output_char %d" % VH,
                  "    stl.output_char %d" % STUB, "    stl.output_char 0xFF"]
    return "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        "rep(4, i) kb.poll kbstat, kbcode, kb_f, kb_b, kb_l, kb_r, mode, bad",
        "hex.if0 1, mode, do_world",
        menu_fj(VW, VH, LINES, 2, COLOURS, label="menu_frame", end_marker=False),
        "    ;frame_end",
        "do_world:",
        "    stl.output_char 0x0B",
        *world,
        "frame_end:",
        "stl.output_char 0xFF",
        "stl.loop",
        "bad: stl.output_char 0x21",
        "     stl.loop",
        "mode: hex.vec 1, %d" % mode_init,
        "kbstat: hex.vec 1", "kbcode: hex.vec 2",
        "kb_f: hex.vec 1", "kb_b: hex.vec 1", "kb_l: hex.vec 1", "kb_r: hex.vec 1",
    ]) + "\n"


def _run(tmp, mode_init):
    src = tmp / ("mode%d.fj" % mode_init)
    src.write_text(_program(mode_init), encoding="utf-8")
    out = tmp / ("mode%d.fjm" % mode_init)
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()],
                out, memory_width=W, print_time=False)
    screen = InMemoryScreen()
    io = PcIO(screen, KeyboardIO(ScriptedKeyEventSource([KeyEvent(0, True, 0x77)])))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return screen


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("mode")


def test_mode_1_paints_the_menu(tmp):
    screen = _run(tmp, 1)
    assert screen.frame_count == 1
    assert screen.pixel_indices == pixels(VW, VH, LINES, 2, COLOURS)


def test_mode_0_paints_the_world_and_never_the_menu(tmp):
    screen = _run(tmp, 0)
    assert screen.frame_count == 1
    assert screen.pixel_indices == [STUB] * (VW * VH)


def test_the_two_producers_really_differ(tmp):
    """R9 vacuity control: a branch that always took the same path would pass both tests above if
    the two pictures happened to match. They must not."""
    assert pixels(VW, VH, LINES, 2, COLOURS) != [STUB] * (VW * VH)


def test_the_tail_shape_the_reset_asserts_on_is_intact():
    """`selfreset.emit_reset_part` refuses unless the line before the bare `stl.loop` is
    `stl.output_char 0xFF`. The menu branch must not disturb that -- so the shared frame-end label
    goes BEFORE the tail, not after it."""
    lines = [l.strip() for l in _program(1).split("\n")]
    loop_at = lines.index("stl.loop")
    assert lines[loop_at - 1] == "stl.output_char 0xFF"
    assert lines[loop_at - 2] == "frame_end:"
