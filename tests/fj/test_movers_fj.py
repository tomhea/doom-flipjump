"""M7 P2b -- the movers' fj RUN against doomfj.movers (docs/gp-lifts.md): the lift tic
(`movercode.lift_tic_lines`, the doors' machine on the lifts' cells) over trigger schedules, the WR
lines after a move (`lift_walk_lines`) and the SR / S1 lines on a press (`use_line_lines`) on E1M1's
real lifts, lines and switch, fed records and read back. The expectation is `movers.lift_tic` and
`movers.MoverPhase` -- the model's rules (tests/host/test_movers_model.py holds them to the model).

R9: MUTANTS -- one real edit of the emitted text each -- must each make their program disagree.
"""
import random
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj import movers as MV
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.harness import W
from doomfj.movercode import lift_tic_lines, lift_walk_lines, mover_decls, use_line_lines
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"
M32 = 0xFFFFFFFF
PLAYER_R = 16


@pytest.fixture(scope="module")
def mp():
    mw = WadFile.from_path(FIX)
    return MV.MoverPhase(mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1"),
                         mw.vertexes("E1M1"))


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


# ---- 1. the lift tic ----------------------------------------------------------------------------------

def tic_program(mp, text=None):
    nl = len(mp.order)
    tic = text if text is not None else lift_tic_lines(mp.order, {si: len(v) for si, v in mp.stops.items()})
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done"]
    for k in range(nl):
        body += ["hex.input 1, rbyte", f"hex.mov 1, lreq + {k}*dw, rbyte"]
    body += list(tic)
    for k in range(nl):
        body += _pr(f"lstate + {k}*dw", 1) + _pr(f"ldir + {k}*dw", 1) + _pr(f"lsub + {k}*dw", 1)
        body += _pr(f"lwait + {WAIT_NIBBLES * k}*dw", WAIT_NIBBLES) + _pr(f"lreq + {k}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", *mover_decls(nl)]
    return "\n".join(body) + "\n"


def tic_schedule(mp, seed=3, frames=240):
    """per frame, the lifts triggered: the first trigger at rest, triggers while moving and while
    waiting (ignored), one on the frame it comes back to rest, and a random rest"""
    rng = random.Random(seed)
    out = []
    for f in range(frames):
        out.append([int(f in (0, 5, 20, 44, 45, 46, 47, 60, 100) or rng.random() < 0.04)
                    for _ in mp.order])
    return out


def tic_expect(mp, sched):
    st, want = mp.initial(), []
    for trig in sched:
        req = frozenset(si for si, t in zip(mp.order, trig) if t)
        st = mp.tic((st[0], req, st[2]))
        for s in st[0]:
            want += list(s) + [0]
    return want


def tic_feed(sched):
    return b"".join(bytes([1] + trig) for trig in sched)


def test_the_lift_tic_is_movers_lift_tic(tmp_path, mp):
    sched = tic_schedule(mp)
    want = tic_expect(mp, sched)
    assert _run(tmp_path, "tic", tic_program(mp), tic_feed(sched)) == want
    assert max(want[0::5]) == 9 and max(want[5::5]) == 9, "both lifts ride all the way down"


# ---- 2. the WR lines after a move ---------------------------------------------------------------------

def walk_program(mp, text=None):
    lines = text if text is not None else lift_walk_lines(mp.walk, mp.order, PLAYER_R)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            f"hex.zero {len(mp.order)}, lreq", *lines]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "cm_ox: hex.vec 8", "cm_oy: hex.vec 8",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "dbox: hex.vec 8, 0", *mover_decls(len(mp.order))]
    return "\n".join(body) + "\n"


def walk_moves(mp):
    """every WR line crossed and not: onto / off the line, and at the inflated extent's ends"""
    out = []
    for _si, axis, coord, lo, hi in mp.walk:
        L = coord << 16
        for o in (lo - PLAYER_R, lo - PLAYER_R + 1, (lo + hi) // 2, hi + PLAYER_R - 1, hi + PLAYER_R):
            for a_old, a_new in ((L, L - 1), (L + 1, L), (L - (8 << 16), L + (8 << 16)),
                                 (L + (8 << 16), L - (8 << 16)), (L + (8 << 16), L + (2 << 16))):
                of = o << 16
                out.append(((of, a_old), (of, a_new)) if axis == "y" else ((a_old, of), (a_new, of)))
    random.Random(7).shuffle(out)
    return out


def walk_expect(mp, moves):
    want = []
    for old, new in moves:
        st = mp.after_move(mp.initial(), old, new, PLAYER_R)
        want += [int(si in st[1]) for si in mp.order]
    return want


def walk_feed(moves):
    return b"".join(bytes([1]) + struct.pack("<IIII", o[0] & M32, o[1] & M32, n[0] & M32, n[1] & M32)
                    for o, n in moves)


def test_the_wr_lines_are_movers_after_move(tmp_path, mp):
    moves = walk_moves(mp)
    want = walk_expect(mp, moves)
    assert _run(tmp_path, "walk", walk_program(mp), walk_feed(moves)) == want
    assert 20 <= sum(want) < len(moves), "crossings and misses"


# ---- 3. the SR / S1 lines on a press -------------------------------------------------------------------

def use_program(mp, text=None):
    of_tag = {t: mp.order.index(si) for t, si in mp.of_tag.items()}
    lines = text if text is not None else use_line_lines(mp.use, mp.switch_boxes, of_tag)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte", "hex.mov 1, fswitch, rbyte",
            f"hex.zero {len(mp.order)}, lreq", *lines]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += _pr("fswitch", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "viewx: hex.vec 8",
             "viewy: hex.vec 8", "dbox: hex.vec 8, 0", *mover_decls(len(mp.order))]
    return "\n".join(body) + "\n"


def use_points(mp):
    pts = []
    for box in [b for _t, b in mp.use] + mp.switch_boxes:
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for x, y in ((cx, cy), (x0, cy), (x1, cy), (cx, y0), (cx, y1)):
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                pts.append(((x << 16) + dx, (y << 16) + dy))
    return [(x, y, sw) for x, y in pts for sw in (0, 1)]


def use_expect(mp, recs):
    want = []
    for x, y, sw in recs:
        lifts, req, s = mp.initial()
        st = mp.use_press((lifts, req, sw), x, y)
        want += [int(si in st[1]) for si in mp.order] + [st[2]]
    return want


def use_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) + bytes([sw]) for x, y, sw in recs)


def test_the_use_lines_are_movers_use_press(tmp_path, mp):
    recs = use_points(mp)
    want = use_expect(mp, recs)
    assert _run(tmp_path, "use", use_program(mp), use_feed(recs)) == want
    n = len(mp.order) + 1
    assert any(want[i * n + n - 1] and not recs[i][2] for i in range(len(recs))), "the switch fires"


# ---- R9: mutants -------------------------------------------------------------------------------------------

def _first(lines, pred, repl):
    out, done = [], False
    for ln in lines:
        if not done and pred(ln):
            ln, done = repl(ln), True
        out.append(ln)
    assert done
    return out


MUTANTS = {
    "a trigger on a moving lift presses": ("tic", lambda ls: _first(
        ls, lambda l: "hex.if0 1, lstate + 0*dw, lf0_press" in l, lambda l: "    ;lf0_press")),
    "the request is not cleared": ("tic", lambda ls: _first(
        ls, lambda l: l.strip() == "hex.zero 1, lreq + 0*dw", lambda l: "")),
    "the bottom wait is the doors'": ("tic", lambda ls: [l.replace(f", {MV.LIFT_WAIT}", f", {D.WAIT}")
                                                         if "hex.set 2, lwait" in l else l for l in ls]),
    "a WR crossing asks nothing": ("walk", lambda ls: _first(
        ls, lambda l: "hex.set 1, lreq +" in l, lambda l: "")),
    "an SR press asks nothing": ("use", lambda ls: _first(
        ls, lambda l: "hex.set 1, lreq +" in l, lambda l: "")),
    "the switch never fires": ("use", lambda ls: _first(
        ls, lambda l: l.strip() == "hex.set 1, fswitch, 1", lambda l: "")),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_mutated_mover_block_fails(tmp_path, mp, name):
    which, fn = MUTANTS[name]
    if which == "tic":
        good = lift_tic_lines(mp.order, {si: len(v) for si, v in mp.stops.items()})
        sched = tic_schedule(mp)
        prog, feed, want = tic_program(mp, fn(good)), tic_feed(sched), tic_expect(mp, sched)
    elif which == "walk":
        good = lift_walk_lines(mp.walk, mp.order, PLAYER_R)
        moves = walk_moves(mp)
        prog, feed, want = walk_program(mp, fn(good)), walk_feed(moves), walk_expect(mp, moves)
    else:
        good = use_line_lines(mp.use, mp.switch_boxes, {t: mp.order.index(si) for t, si in mp.of_tag.items()})
        recs = use_points(mp)
        prog, feed, want = use_program(mp, fn(good)), use_feed(recs), use_expect(mp, recs)
    assert fn(good) != good, "the mutant changed nothing"
    assert _run(tmp_path, "mut", prog, feed) != want, name
