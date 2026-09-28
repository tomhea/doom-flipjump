"""M7 P2a.2 -- the exit switch RUN in fj (docs/gp-exit.md): `wall_renderer.exit_lines` on E1M1's own
exit box (`doors.exit_boxes`, linedef 407), fed records -- use held this tic, use held last tic
(`pusedn`), the 16.16 position -- and read back: `pusedn`, `lvdone`, `mode`, `menu_scr`. The
expectation is the model's rule (P_UseLines on a use PRESS inside the box; the box test is the doors'
inclusive `in_use_box_fixed`), which tests/host/test_exit_p2a2.py holds to the model itself.

R9: MUTANTS -- one real edit of the emitted text each -- must each make the program disagree.
"""
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.harness import W
from doomfj.menu import LEVEL_DONE_SCR
from doomfj.wad import WadFile
from doomfj.wall_renderer import exit_lines

FIX = "tests/fixtures/freedoom_e1m1.wad"
M32 = 0xFFFFFFFF


@pytest.fixture(scope="module")
def boxes():
    mw = WadFile.from_path(FIX)
    out = D.exit_boxes(mw.linedefs("E1M1"), mw.vertexes("E1M1"))
    assert len(out) == 1
    return out


def program(lines) -> str:
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, rbyte", "hex.mov 1, duse, rbyte",
            "hex.input 1, rbyte", "hex.mov 1, pusedn, rbyte",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.zero 1, lvdone", "hex.zero 1, mode", "hex.zero 1, menu_scr",
            *lines]
    for reg in ("pusedn", "lvdone", "mode", "menu_scr"):
        body += [f"    hex.print_as_digit 1, {reg}, 0", "    stl.output 32"]
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "duse: hex.vec 1", "dbox: hex.vec 8, 0",
             "pusedn: hex.vec 1", "lvdone: hex.vec 1", "mode: hex.vec 1", "menu_scr: hex.vec 1"]
    return "\n".join(body) + "\n"


def _run(tmp, name, text, feed) -> list:
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def probes(boxes) -> list:
    """every (use, use last tic) pair at the box's edges -- on, one 16.16 step inside and outside
    each side, both axes -- and at its centre and far outside"""
    x0, y0, x1, y1 = boxes[0]
    cx, cy = (x0 + x1) // 2 << 16, (y0 + y1) // 2 << 16
    pts = [(cx, cy), (cx + (500 << 16), cy), (cx, cy - (500 << 16))]
    for e in (x0 << 16, x1 << 16):
        pts += [(e + d, cy) for d in (-1, 0, 1)]
    for e in (y0 << 16, y1 << 16):
        pts += [(cx, e + d) for d in (-1, 0, 1)]
    return [(u, p, x, y) for u in (0, 1) for p in (0, 1) for x, y in pts]


def expect(boxes, recs) -> list:
    """the model's rule: use released clears `pusedn`; a press (use, `pusedn` clear) sets it, and
    inside a box ends the level and opens LEVEL COMPLETE"""
    out = []
    for use, was, x, y in recs:
        hit = use and not was and any(D.in_use_box_fixed(b, x, y) for b in boxes)
        out += [int(bool(use)), int(hit), int(hit), LEVEL_DONE_SCR if hit else 0]
    return out


def feed(recs) -> bytes:
    return b"".join(bytes([1, u, p]) + struct.pack("<II", x & M32, y & M32) for u, p, x, y in recs)


def test_the_exit_press_is_the_models(tmp_path, boxes):
    recs = probes(boxes)
    want = expect(boxes, recs)
    assert _run(tmp_path, "exit", program(exit_lines(boxes)), feed(recs)) == want
    assert sum(want[1::4]) >= 8 and sum(want[1::4]) < len(recs) // 4   # hits, and misses


MUTANTS = {
    "a held use presses again": lambda ls: [";ex_press" if ln == "hex.if0 1, pusedn, ex_press" else ln
                                            for ln in ls],
    "release does not clear pusedn": lambda ls: [ln for ln in ls if ln != "hex.zero 1, pusedn"],
    "the hit does not open the screen": lambda ls: [ln for ln in ls if "menu_scr" not in ln],
    "the hit does not end the level": lambda ls: [ln for ln in ls if ln != "hex.set 1, lvdone, 1"],
    "the box's west edge one unit in": lambda ls: _shift_first_edge(ls),
}


def _shift_first_edge(ls):
    out, done = [], False
    for ln in ls:
        if not done and ln.strip().startswith("hex.set 8, dbox,"):
            v = int(ln.split(",")[-1], 16)
            ln = "    hex.set 8, dbox, %#x" % ((v + (1 << 16)) & M32)
            done = True
        out.append(ln)
    assert done
    return out


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_mutated_exit_fails(tmp_path, boxes, name):
    good = exit_lines(boxes)
    bad = MUTANTS[name](good)
    assert bad != good, "the mutant changed nothing"
    recs = probes(boxes)
    assert _run(tmp_path, "mut", program(bad), feed(recs)) != expect(boxes, recs), name
