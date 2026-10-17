"""M8 F1.3 -- E1M2's movers' fj RUN against doomfj.movers (docs/f1-big-map-widths.md 10, docs/handoff-e1m2.md L3):
every moving floor E1M2 has, on its real lines and sectors, fed records and read back --

  1. the tic: the lifts (`movercode.lift_tic_lines` with each lift's stride -- the blazing 120 / 123 lifts stride 2)
     and the eleven floor groups (`floor_tic_lines`: 19, 38, 58, 71, 102 moving, the two 23 groups instant), fired by
     `_fire_lines` on a schedule, against `movers.MoverPhase.tic` + `floor_trigger`;
  2. the walk-overs after a move: the WR lift lines (a tag starting TWO lifts: 47 and 209) and the W1 floor lines --
     axis-aligned and the three SLANTED ones (1972, 1974, 2011) -- over crossings, misses, the line itself and a
     random fuzz, from untouched and fired groups, against `MoverPhase.after_move`;
  3. the use presses: the SR lifts (a blazing one) and the five S1 floor lines, each tag its own group (item 10:
     E1M2's 23 lines have two tags) against `MoverPhase.use_press`.

R9: MUTANTS -- one real edit of the emitted text each (the blazing stride dropped, the floor timer not reloaded, a
slanted side's sign flipped, the fired-once guard dropped, every group's cell read as `fswitch`, a tag's second lift
not requested) -- must each make their program disagree.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import movers as MV
from doomfj.collision import point_location_decls
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.harness import W
from doomfj.movercode import (_fire_lines, floor_tic_lines, floor_walk_lines, lift_tic_lines, lift_walk_lines,
                              mover_decls, use_line_lines)
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
PLAYER_R = 16


@pytest.fixture(scope="module")
def mp():
    mw = WadFile.from_path(FIX)
    return MV.MoverPhase(mw.sectors("E1M2"), mw.linedefs("E1M2"), mw.sidedefs("E1M2"), mw.vertexes("E1M2"))


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([(FJ / "fixed_point.fj").resolve(), src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def _decls(mp):
    return ["rmagic: hex.vec 2", "rbyte: hex.vec 2", "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "viewx: hex.vec 8",
            "viewy: hex.vec 8", "dbox: hex.vec 8, 0", *point_location_decls(),
            *mover_decls(len(mp.order), MV.fswitch_nibbles(mp.groups))]


def _nfs(mp):
    return MV.fswitch_nibbles(mp.groups)


def _in_fswitch(mp):
    out = []
    for i in range(_nfs(mp)):
        out += ["hex.input 1, rbyte", f"hex.mov 1, fswitch + {i}*dw, rbyte"]
    return out


def _out_fswitch(mp):
    return [ln for i in range(_nfs(mp)) for ln in _pr(f"fswitch + {i}*dw", 1)]


def test_e1m2_has_every_mover_kind(mp):
    assert mp.wide and len(mp.groups) == 11
    assert {g.special for g in mp.groups} == {19, 23, 38, 58, 71, 102}
    assert sorted(mp.stride.values()) == [1, 2, 2, 2, 2]
    assert any(len(v) == 2 for v in mp.lifts_of_tag.values()), "a tag starting two lifts"
    assert sum(s[0] == "d" for _g, s in mp.floor_walk) == 3, "three slanted W1 lines"
    assert len({g for g, _b in mp.floor_use}) == 5, "the S1 floor lines: five groups"


# ---- 1. the tic --------------------------------------------------------------------------------------------------

def tic_text(mp):
    return (lift_tic_lines(mp.order, {si: len(v) for si, v in mp.stops.items()}, mp.stride)
            + floor_tic_lines(mp.groups))


def tic_program(mp, text=None):
    nl, ng = len(mp.order), len(mp.groups)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done"]
    for k in range(nl):
        body += ["hex.input 1, rbyte", f"hex.mov 1, lreq + {k}*dw, rbyte"]
    body += list(tic_text(mp) if text is None else text)
    for g in range(ng):                                  # the player's fires, after the tic (the frame's order)
        body += ["hex.input 1, rbyte", "hex.if0 1, rbyte, tf%d_skip" % g]
        body += [ln.replace(";tf%d_fired" % g, ";tf%d_skip" % g) for ln in _fire_lines("tf%d" % g, g, mp.groups)]
        body += ["tf%d_skip:" % g]
    for k in range(nl):
        body += _pr(f"lstate + {k}*dw", 1) + _pr(f"ldir + {k}*dw", 1) + _pr(f"lsub + {k}*dw", 1)
        body += _pr(f"lwait + {WAIT_NIBBLES * k}*dw", WAIT_NIBBLES) + _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def tic_schedule(mp, seed=5, frames=160):
    rng = random.Random(seed)
    out = []
    for f in range(frames):
        lifts = [int(f in (0, 3, 30, 31, 70) or rng.random() < 0.05) for _ in mp.order]
        fires = [int(f == 2 * g or rng.random() < 0.03) for g in range(len(mp.groups))]
        out.append((lifts, fires))
    return out


def tic_expect(mp, sched):
    st, want = mp.initial(), []
    for lifts, fires in sched:
        req = frozenset(si for si, t in zip(mp.order, lifts) if t)
        st = mp.tic((st[0], req, st[2]))
        fs = mp._fs(st[2])
        for g, on in enumerate(fires):
            if on:
                fs[g] = MV.floor_trigger(*fs[g], mp.groups[g].sub)
        st = (st[0], st[1], mp._sw(fs))
        for s in st[0]:
            want += list(s) + [0]
        want += list(st[2])
    return want


def tic_feed(sched):
    return b"".join(bytes([1] + lifts + fires) for lifts, fires in sched)


def test_the_tic_is_movers(tmp_path, mp):
    sched = tic_schedule(mp)
    want = tic_expect(mp, sched)
    assert _run(tmp_path, "tic", tic_program(mp), tic_feed(sched)) == want
    ng, nl = len(mp.groups), len(mp.order)
    last = want[-2 * ng:-ng]
    assert last == [g.n - 1 for g in mp.groups], "every floor group reached its destination"
    assert nl == 5


# ---- 2. the walk-overs after a move -----------------------------------------------------------------------------

def walk_text(mp):
    return lift_walk_lines(mp.walk, mp.order, PLAYER_R) + floor_walk_lines(mp.groups, mp.floor_walk, PLAYER_R)


def walk_program(mp, text=None):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            *_in_fswitch(mp), f"hex.zero {len(mp.order)}, lreq", *(walk_text(mp) if text is None else text)]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def _shape_moves(shape, rng):
    out = []
    if shape[0] == "d":
        _d, x1, y1, x2, y2 = shape
        dx, dy = x2 - x1, y2 - y1
        nlen = max(abs(dx), abs(dy))
        nx, ny = (-dy << 16) // nlen, (dx << 16) // nlen               # ~unit normal, 16.16
        for t in (-0.3, -0.1, 0.0, 0.25, 0.5, 1.0, 1.1, 1.3):
            px, py = (x1 << 16) + int(t * (dx << 16)), (y1 << 16) + int(t * (dy << 16))
            for a, b in ((8, -8), (-8, 8), (1, -1), (-3, 5), (12, 2), (8, 0), (0, 8)):
                out.append(((px + a * nx, py + a * ny), (px + b * nx, py + b * ny)))
        for _ in range(60):                                             # the fuzz: steps near the line, fractions
            t = rng.uniform(-0.4, 1.4)
            px, py = (x1 << 16) + int(t * (dx << 16)), (y1 << 16) + int(t * (dy << 16))
            new = (px + rng.randint(-20 << 16, 20 << 16), py + rng.randint(-20 << 16, 20 << 16))
            old = (new[0] + rng.randint(-24 << 16, 24 << 16), new[1] + rng.randint(-24 << 16, 24 << 16))
            out.append((old, new))
    else:
        axis, coord, lo, hi = shape
        L = coord << 16
        for o in (lo - PLAYER_R, lo - PLAYER_R + 1, (lo + hi) // 2, hi + PLAYER_R - 1, hi + PLAYER_R):
            for a_old, a_new in ((L, L - 1), (L + 1, L), (L - (8 << 16), L + (8 << 16)),
                                 (L + (8 << 16), L - (8 << 16)), (L + (8 << 16), L + (2 << 16))):
                of = o << 16
                out.append(((of, a_old), (of, a_new)) if axis == "y" else ((a_old, of), (a_new, of)))
    return out


def _fired(mp, done=False):
    """a fswitch vector with every group fired: instant ones at 1, moving ones mid-way (state 1, timer running) or,
    `done`, at their destination (the last state, the timer 0)"""
    fs = [(1, 0) if not g.sub else ((g.n - 1, 0) if done else (1, g.sub)) for g in mp.groups]
    return mp._sw(fs)


def walk_recs(mp):
    rng = random.Random(11)
    recs = []
    shapes = [(t[1], t[2], t[3], t[4]) for t in mp.walk] + [s for _g, s in mp.floor_walk]
    for shape in shapes:
        for old, new in _shape_moves(shape, rng):
            recs.append((old, new, mp.initial()[2]))
    for old, new, _sw in recs[::5]:
        recs.append((old, new, _fired(mp)))
    for old, new, _sw in recs[2::7]:
        recs.append((old, new, _fired(mp, done=True)))
    rng.shuffle(recs)
    return recs


def walk_expect(mp, recs):
    want = []
    for old, new, sw in recs:
        lifts, _req, _ = mp.initial()
        st = mp.after_move((lifts, frozenset(), sw), old, new, PLAYER_R)
        want += [int(si in st[1]) for si in mp.order] + list(st[2])
    return want


def walk_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<IIII", o[0] & M32, o[1] & M32, n[0] & M32, n[1] & M32)
                    + bytes(sw) for o, n, sw in recs)


def test_the_walk_overs_are_movers_after_move(tmp_path, mp):
    recs = walk_recs(mp)
    want = walk_expect(mp, recs)
    got = _run(tmp_path, "walk", walk_program(mp), walk_feed(recs))
    assert got == want
    n = len(mp.order) + _nfs(mp)
    fires = [i for i in range(len(recs)) if want[i * n:(i + 1) * n] != [0] * len(mp.order) + list(recs[i][2])]
    assert len(fires) > 50, "crossings fire"
    # every W1 floor line (the slanted ones too) is crossed and missed in the records
    for _g, s in mp.floor_walk:
        hit = [MV.crossed_shape(s, o, nw, PLAYER_R) for o, nw, _sw in recs]
        assert any(hit) and not all(hit), s


# ---- 3. the use presses ------------------------------------------------------------------------------------------

def use_text(mp):
    return use_line_lines(mp.use, [], MV.lift_slots_of_tag(mp.secs, mp.order), mp.groups, mp.floor_use)


def use_program(mp, text=None):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", *_in_fswitch(mp),
            f"hex.zero {len(mp.order)}, lreq", *(use_text(mp) if text is None else text)]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def use_recs(mp):
    pts = []
    for box in [b for _t, b in mp.use] + [b for _g, b in mp.floor_use]:
        x0, y0, x1, y1 = box
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for x, y in ((cx, cy), (x0, cy), (x1, cy), (cx, y0), (cx, y1)):
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                pts.append(((x << 16) + dx, (y << 16) + dy))
    return [(x, y, sw) for x, y in pts for sw in (mp.initial()[2], _fired(mp), _fired(mp, done=True))]


def use_expect(mp, recs):
    want = []
    for x, y, sw in recs:
        lifts, _req, _ = mp.initial()
        st = mp.use_press((lifts, frozenset(), sw), x, y)
        want += [int(si in st[1]) for si in mp.order] + list(st[2])
    return want


def use_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) + bytes(sw) for x, y, sw in recs)


def test_the_use_presses_are_movers_use_press(tmp_path, mp):
    recs = use_recs(mp)
    want = use_expect(mp, recs)
    assert _run(tmp_path, "use", use_program(mp), use_feed(recs)) == want
    n = len(mp.order) + _nfs(mp)
    fired = {g for i in range(len(recs)) for g in range(len(mp.groups))
             if want[i * n + len(mp.order) + g] != recs[i][2][g] or
             want[i * n + len(mp.order) + len(mp.groups) + g] != recs[i][2][len(mp.groups) + g]}
    assert fired == {g for g, _b in mp.floor_use}, "each S1 group fires by its own lines"


# ---- R9: mutants -------------------------------------------------------------------------------------------------

def _first(lines, pred, repl):
    out, done = [], False
    for ln in lines:
        if not done and pred(ln):
            ln, done = repl(ln), True
        out.append(ln)
    assert done
    return out


def _nth_slanted_sign(ls):
    """flip the first slanted side test's branches (its side 1 and side 0 swapped)"""
    def repl(l):
        head, a, b = l.rsplit(",", 2)
        return f"{head},{b},{a}"
    return _first(ls, lambda l: l.strip().startswith("hex.sign 10, ptlocp,"), repl)


MUTANTS = {
    "the blazing lift strides one": ("tic", lambda mp: lift_tic_lines(
        mp.order, {si: len(v) for si, v in mp.stops.items()}, None) + floor_tic_lines(mp.groups)),
    "the floor timer is not reloaded": ("tic", lambda mp: _first(
        tic_text(mp), lambda l: l.strip().startswith("hex.set 1, fswitch +") and "fg" not in l,
        lambda l: "")),
    "a slanted side's sign flipped": ("walk", lambda mp: _nth_slanted_sign(walk_text(mp))),
    # every test of group 1's STATE in its W1 lines (the guard before the crossing and the fire's own): a group at
    # its destination fires again
    "the W1 fired-once guard dropped": ("walk", lambda mp: [
        "    ;" + l.strip().rsplit(", ", 1)[1] if l.strip().startswith("hex.if0 1, fswitch + 1*dw,") else l
        for l in walk_text(mp)]),
    "a tag's second lift not requested": ("walk", lambda mp: _first(
        walk_text(mp), lambda l: "hex.set 1, lreq + 4*dw, 1" in l, lambda l: "")),
    "every group's cell is fswitch": ("use", lambda mp: [
        l.replace("fswitch + 1*dw", "fswitch").replace("fswitch + 2*dw", "fswitch")
         .replace("fswitch + 7*dw", "fswitch").replace("fswitch + 8*dw", "fswitch")
         .replace("fswitch + 9*dw", "fswitch") for l in use_text(mp)]),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_mutated_mover_block_fails(tmp_path, mp, name):
    which, fn = MUTANTS[name]
    if which == "tic":
        good, sched = tic_text(mp), tic_schedule(mp)
        prog, feed, want = tic_program(mp, fn(mp)), tic_feed(sched), tic_expect(mp, sched)
    elif which == "walk":
        good, recs = walk_text(mp), walk_recs(mp)
        prog, feed, want = walk_program(mp, fn(mp)), walk_feed(recs), walk_expect(mp, recs)
    else:
        good, recs = use_text(mp), use_recs(mp)
        prog, feed, want = use_program(mp, fn(mp)), use_feed(recs), use_expect(mp, recs)
    assert fn(mp) != good, "the mutant changed nothing"
    assert _run(tmp_path, "mut", prog, feed) != want, name
