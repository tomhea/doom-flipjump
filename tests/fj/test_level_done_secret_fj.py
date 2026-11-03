"""M8 C9: LEVEL COMPLETE after the SECRET exit (51) -- SECRET EXIT under the title, the picture of both mirrors from
one layout (menu.secret_exit_origin): the oracle's `level_done_pixels(secret=True)` against the program's bytes -- the
baked frame, the digit records, then `level_done_secret_records` -- decoded through the REAL screen device
(InMemoryScreen, as tests/host/test_menu.py does for the frame), and statcode.frame_lines' guarded block RUN in fj:
`lvsec` 1 sends exactly those records, 0 sends nothing; a map without a secret exit (E1M1) has no block at all.
CONTROLS (R9): the records drawn one line lower, or in the highlight colour, miss the oracle's picture; the frame
without them is the plain LEVEL COMPLETE (secret=False), which differs.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import menu as MN
from doomfj import screenwire as SW
from doomfj import statcode
from doomfj.config import Config
from doomfj.harness import W as MEMW
from doomfj.menu import (level_done_digit_records, level_done_pixels, level_done_secret_records, level_done_stream,
                         stats_digits)

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
CFG = Config()
W, H = CFG.VIEW_W, CFG.VIEW_H
COLOURS = (0, 4, 176, 101)
DIGITS = stats_digits(7, 46, 12, 48, 2, 83)


def _feed(device, data: bytes):
    for byte in data:
        for i in range(8):
            device.write_bit(bool((byte >> i) & 1))


def _present(data: bytes):
    screen = InMemoryScreen()
    _feed(screen, SW.init_screen(W, H))
    _feed(screen, data)
    return screen


def _program_bytes(secret_records: bytes, nsecret=3):
    data = bytearray(SW.strip_frame_tail(level_done_stream(W, H, COLOURS, nsecret)))
    for slot, d in enumerate(DIGITS):
        data += level_done_digit_records(W, H, COLOURS, nsecret, slot, d)
    return bytes(data) + secret_records + SW.FRAME_TAIL


def test_secret_exit_paints_exactly_the_oracle_picture():
    rec = level_done_secret_records(W, H, COLOURS, 3)
    assert len(rec) > 100
    got = _present(_program_bytes(rec)).pixel_indices
    assert got == level_done_pixels(W, H, COLOURS, 3, DIGITS, secret=True)
    assert got != level_done_pixels(W, H, COLOURS, 3, DIGITS)                       # it is drawn at all
    assert _present(_program_bytes(b"")).pixel_indices == level_done_pixels(W, H, COLOURS, 3, DIGITS)


@pytest.mark.parametrize("ctl", ["one_line_lower", "highlight_colour"])
def test_control_a_misplaced_secret_line_parts(ctl, monkeypatch):
    want = level_done_pixels(W, H, COLOURS, 3, DIGITS, secret=True)
    if ctl == "one_line_lower":
        real = MN.secret_exit_origin
        monkeypatch.setattr(MN, "secret_exit_origin", lambda *a, **k: (real(*a, **k)[0], real(*a, **k)[1] + 1))
        rec = level_done_secret_records(W, H, COLOURS, 3)
    else:
        rec = level_done_secret_records(W, H, (COLOURS[0], COLOURS[2], COLOURS[2], COLOURS[3]), 3)
    assert _present(_program_bytes(rec)).pixel_indices != want


# ---- statcode.frame_lines' block, run in fj --------------------------------------------------------------------------
class _Lay:
    def __init__(self, secexit):
        self.secexit = secexit


def _block(secexit=1):
    """frame_lines' lines after the digit slots (the secret block, if any), on a stand-in world of E1M1's shape"""
    from doomfj.wad import WadFile
    from doomfj.world import World
    w = World(WadFile.from_path(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"), "E1M1")
    lines = statcode.frame_lines(W, H, COLOURS, w)
    if not secexit:
        return lines, w
    w.layout = _Lay(1)
    return statcode.frame_lines(W, H, COLOURS, w), w


def test_e1m1_has_no_secret_block():
    lines, _w = _block(0)
    assert not any("lvsec" in ln for ln in lines)


@pytest.mark.parametrize("lvsec", [0, 1])
def test_the_secret_block_sends_its_records_on_lvsec(tmp_path, lvsec):
    lines, w = _block(1)
    k = lines.index("    hex.if0 1, lvsec, lvd_sx")
    block = lines[k:]
    assert block[-1] == "  lvd_sx:"
    text = "\n".join(["stl.startup_and_init_all", f"hex.set 1, lvsec, {lvsec}", *block, "stl.loop",
                      "lvsec: hex.vec 1"]) + "\n"
    src = tmp_path / "sec.fj"
    src.write_text(text, encoding="utf-8")
    out = tmp_path / "sec.fjm"
    fj.assemble([src.resolve()], out, memory_width=MEMW, print_time=False)
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    nsec, nd = len(w.secret_sectors), statcode.count_digits(w)
    want = level_done_secret_records(W, H, COLOURS, nsec, nd) if lvsec else b""
    assert io.get_output(allow_incomplete_output=True) == want
