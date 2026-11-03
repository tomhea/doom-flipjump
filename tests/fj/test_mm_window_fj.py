"""E1M6 v2's cut: monstermove.things_leaf_lines(window=True) -- mm_things testing the slots against per-call windows
(two early-exit compares an axis) -- against World._thing_blocker's monster and player tests, on the real flipjump
engine, and the slot loop it falls back to (window=False) on the same records.

The records are synthetic: slots of the three radius classes (20, 30 and a lost soul's 16), candidates on both sides of
both axes and within a box of them (where a window straddles zero and the fast path must hand over to the loop), and
things on the boxes' edges (|dx| = bd - 1, bd, bd + 1).
R9: the fast path without its straddle test, and a window whose high end lets |dx| = bd through, must each part.
"""
import random

import flipjump as fj
import pytest

from doomfj import monstermove as MM
from doomfj.harness import W

M32 = 0xFFFFFFFF
RADII = (20, 30, 20, 16, 30, 20, 20, 30, 16, 20, 30, 20)
RECORDS = 160


def _records():
    rnd = random.Random(0xE1606)
    out = []
    for k in range(RECORDS):
        r = rnd.choice((20, 30, 16))
        if k % 4 == 0:                                   # within a box of an axis: some window straddles zero
            nx, ny = rnd.randrange(-70, 71), rnd.choice((rnd.randrange(-70, 71), rnd.randrange(-3000, 3000)))
            if k % 8 == 4:
                nx, ny = ny, nx
        else:
            nx, ny = rnd.randrange(-3000, 3000), rnd.randrange(-3000, 3000)
        things = []
        for rad in RADII:
            bd = r + rad
            if rnd.random() < 0.5:                       # near: inside, on, or just past the box's edges
                dx = rnd.choice([rnd.randrange(-bd + 1, bd), -bd, bd, -bd + 1, bd - 1, bd + 1, -bd - 1])
                dy = rnd.choice([rnd.randrange(-bd + 1, bd), -bd, bd, -bd + 1, bd - 1, bd + 1, -bd - 1])
            else:
                dx, dy = rnd.randrange(-400, 401), rnd.randrange(-400, 401)
            things.append((nx + dx, ny + dy, int(rnd.random() < 0.8)))
        lim = (r + 16) << 16
        px = (nx << 16) + rnd.choice([rnd.randrange(-3 * lim, 3 * lim), -lim, lim])
        py = (ny << 16) + rnd.randrange(-2 * lim, 2 * lim)
        out.append((r, nx, ny, things, px, py, int(rnd.random() < 0.2)))
    return out


def _expected(recs) -> bytes:
    """World._thing_blocker's monster and player tests: abs(dx) < bd on both axes, the player at 16.16 unless dead"""
    out = []
    for r, nx, ny, things, px, py, dead in recs:
        hit = any(s and abs(x - nx) < r + rad and abs(y - ny) < r + rad for (x, y, s), rad in zip(things, RADII))
        lim = (r + 16) << 16
        hit = hit or (not dead and abs(px - (nx << 16)) < lim and abs(py - (ny << 16)) < lim)
        out.append("%d" % hit)
    return ("\n".join(out) + "\n").encode()


def _leaf(window: bool, mut: str = "") -> str:
    leaf = "\n".join(MM.things_leaf_lines([(j, rad) for j, rad in enumerate(RADII)], solid="mon_solid", hurt=True,
                                          window=window))
    if mut == "nostraddle":                              # a straddling window stays on the fast path
        assert leaf.count(", mm_slow") == 6
        leaf = leaf.replace(", mm_slow", ", mm_player")
    elif mut == "hi_eq":                                 # |dx| = bd passes the high end of the x windows
        lines = leaf.split("\n")
        for i, ln in enumerate(lines):
            if ln.startswith("    hex.cmp 4, thpos_rt") and "mm_wh" in ln and "x, mm_f" in ln:
                a = ln.split(", ")
                a[4] = a[3]                              # eq -> the lt target (the y test)
                lines[i] = ", ".join(a)
        leaf = "\n".join(lines)
    return leaf


def _run(tmp_path, name, window: bool, mut: str = "") -> bool:
    recs = _records()
    n = len(RADII)
    body = ["stl.startup_and_init_all"]
    for r, nx, ny, things, px, py, dead in recs:
        pos = sum((((x << 16) & M32) | (((y << 16) & M32) << 32)) << (64 * j) for j, (x, y, _s) in enumerate(things))
        body += ["hex.set %d, mon_solid, %d" % (n, sum(s << (4 * j) for j, (_x, _y, s) in enumerate(things))),
                 "hex.set %d, thpos_rt, %d" % (16 * n, pos),
                 "hex.set 4, mm_nx, %d" % (nx & 0xFFFF), "hex.set 4, mm_ny, %d" % (ny & 0xFFFF),
                 "hex.set 8, cpx, %d" % ((nx << 16) & M32), "hex.set 8, cpy, %d" % ((ny << 16) & M32),
                 "hex.set 2, mm_r, %d" % r,
                 "hex.set 8, viewx, %d" % (px & M32), "hex.set 8, viewy, %d" % (py & M32),
                 "hex.set 1, p_dead, %d" % dead,
                 "stl.fcall mm_things, mm_tret", "hex.print_as_digit 1, mm_blk, 0", "stl.output 10"]
    body.append("stl.loop")
    decls = ["mon_solid: hex.vec %d" % n, "p_dead: hex.vec 1", "viewx: hex.vec 8", "viewy: hex.vec 8",
             "cpx: hex.vec 8", "cpy: hex.vec 8", "ct_a: hex.vec 4", "thpos_rt: hex.vec %d" % (16 * n),
             "mm_bd16: hex.vec 4"]
    decls += [d for d in MM.p32b_context(2) if d.split(":")[0] in ("mm_nx", "mm_ny", "mm_r", "mm_blk", "mm_bd20",
                                                                  "mm_bd30", "mm_bdp", "mm_c", "mm_tret")]
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + decls) + "\n" + _leaf(window, mut) + "\n", encoding="utf-8")
    return fj.assemble_and_run_test_output([p.resolve()], b"", _expected(recs), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_records_decide_something():
    """hits and misses both, edge things, and candidates whose windows straddle zero"""
    recs = _records()
    got = _expected(recs).split()
    assert b"1" in got and b"0" in got
    assert sum(1 for r in recs if min(abs(r[1]), abs(r[2])) < r[0] + 30) >= 20


def test_the_slot_loop_matches_the_model(tmp_path):
    assert _run(tmp_path, "mmloop", window=False), "mm_things (the slot loop) parted from World._thing_blocker"


def test_the_windowed_test_matches_the_model(tmp_path):
    assert _run(tmp_path, "mmwin", window=True), "mm_things (windowed) parted from World._thing_blocker"


def test_window_off_is_the_text_before():
    """window=False emits the leaf's text unchanged: the other maps' binaries keep their recorded sha256"""
    slots = [(j, rad) for j, rad in enumerate(RADII)]
    assert "mm_slow" not in "\n".join(MM.things_leaf_lines(slots, solid="mon_solid", hurt=True))
    assert MM.things_leaf_lines(slots, solid="mon_solid", hurt=True) == \
        MM.things_leaf_lines(slots, solid="mon_solid", hurt=True, window=False)


@pytest.mark.parametrize("mut", ["nostraddle", "hi_eq"])
def test_control_a_broken_window_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mmwin_" + mut, window=True, mut=mut), "%s passed: the comparison is vacuous" % mut
