"""M3 — the baked menu frame, emitted as REAL fj and presented by the REAL device.

`tests/host/test_menu.py` proves the generator's two mirrors agree. This proves the third thing:
that the fj text `doomfj.menu.fj()` emits actually puts that picture on the screen, assembled and
run. It costs seconds, because a menu frame is a constant byte stream and needs no renderer, no
map and no tables — which is the whole reason M3 is cheap.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import fj as menu_fj, pixels, stream

CFG = Config()
VW, VH = CFG.VIEW_W, CFG.VIEW_H
LINES = ["DOOM ON FLIPJUMP", "", "NEW GAME", "LEVEL 1", "QUIT"]
COLOURS = (0, 4, 176)
SRC = [Path("src/fj") / "present.fj"]


class _Screen(InMemoryScreen):
    """the stock device, plus an empty input stream so the program can halt on its own."""

    def read_bit(self):
        from flipjump.utils.exceptions import IOReadOnEOF
        raise IOReadOnEOF("no input")


def _program(selected):
    return "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        menu_fj(VW, VH, LINES, selected, COLOURS, label="menu_frame"),
        "stl.loop",
    ]) + "\n"


@pytest.fixture(scope="module")
def tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("menu")


@pytest.mark.parametrize("selected", [0, 2, 4])
def test_the_emitted_fj_paints_the_oracle_picture(tmp, selected):
    src = tmp / ("menu%d.fj" % selected)
    src.write_text(_program(selected), encoding="utf-8")
    out = tmp / ("menu%d.fjm" % selected)
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()],
                out, memory_width=W, print_time=False)
    screen = _Screen()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    assert screen.frame_count == 1, "the menu frame never presented"
    assert screen.pixel_indices == pixels(VW, VH, LINES, selected, COLOURS)


def test_the_frame_is_a_constant_stream(tmp):
    """Every byte is a compile-time operand -- no register, no table, no dispatch. That is what
    makes the menu ~11,900x cheaper than a world frame."""
    text = menu_fj(VW, VH, LINES, 0, COLOURS)
    assert "hex." not in text and "stl.fcall" not in text
    assert text.count("stl.output_char") == len(stream(VW, VH, LINES, 0, COLOURS))
