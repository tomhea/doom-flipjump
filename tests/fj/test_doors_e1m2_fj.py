"""M8 L2 -- E1M2's door kinds RUN in fj against doomfj.doors (the model every gate steps): the door tic with the key
doors (pcard_y / pcard_r), the SR / S1 switches (a press only at rest), the D1 / W1 open-stay doors and the blazing
open-stay; the walk-over lines per line (E1M2's tag 16 opening two doors; E1M3's ring of six, two slanted); and the
slanted door contact (`door_contact_lines` on E1M2's non-rectangular doors). Nothing here is modelled: each program is
the emitter's own text (doorcode.door_tic_lines / walkover_lines / door_contact_lines), fed records and read back; the
expectation is doomfj.doors.DoorPhase / touches_door.

The card cells `pcard_y` / `pcard_r` belong to the pickups (lootcode.card_cells); these programs declare them locally.

R9: MUTANTS -- one real edit of the emitted text each -- must each make their program disagree.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.doorcode import WAIT_NIBBLES, door_contact_lines, door_decls, door_tic_lines, walkover_lines
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FULL = ROOT / "assets" / "freedoom1.wad"
M32 = 0xFFFFFFFF
CARDS = ("pcard", "pcard_y", "pcard_r")


def _phase(path, m):
    mw = WadFile.from_path(str(path))
    secs, lds, sds = mw.sectors(m), mw.linedefs(m), mw.sidedefs(m)
    boxes = D.use_boxes_xy(secs, lds, sds, bake_bsp(mw, m).vertexes)
    dp = D.DoorPhase(secs, lds, sds, mw.vertexes(m), boxes)
    dp.secs, dp.lds, dp.sds, dp.verts = secs, lds, sds, mw.vertexes(m)
    return dp


@pytest.fixture(scope="module")
def lvl():
    return _phase(FIX, "E1M2")


@pytest.fixture(scope="module")
def e1m3():
    if not FULL.exists():
        pytest.skip("the full episode wad is not present")
    return _phase(FULL, "E1M3")


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def _mutated(lines, old, new):
    text = "\n".join(lines)
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1).split("\n")


# ---- 1. the door tic ----------------------------------------------------------------------------------------------

def tic_lines(dp):
    return door_tic_lines(dp.order, dp.nstates, dp.boxes, dp.kinds, contact=dp.contact, passes=dp.passes,
                          switches=dp.switches, walked={t[0] for t in dp.triggers})


def door_program(dp, text=None):
    nd = len(dp.order)
    tic = text if text is not None else tic_lines(dp)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rbyte", "hex.mov 1, duse, rbyte"]
    for c in CARDS:
        body += ["hex.input 1, rbyte", f"hex.mov 1, {c}, rbyte"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dreq + {d}*dw, rbyte"]
    body += list(tic)
    for d in range(nd):
        body += _pr(f"dstate + {d}*dw", 1) + _pr(f"ddir + {d}*dw", 1) + _pr(f"dsub + {d}*dw", 1)
        body += _pr(f"dwait + {WAIT_NIBBLES * d}*dw", WAIT_NIBBLES) + _pr(f"dreq + {d}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "pcard_y: hex.vec 1, 0", "pcard_r: hex.vec 1, 0",
             *door_decls(nd, len(dp.triggers))]
    return "\n".join(body) + "\n"


def door_schedule(dp, seed=7):
    """every boxed door (its own box) and every switch box visited with no card, its card, every card -- pressed
    from the box centre, then 12 frames inside it with use now and then (a switch pressed while its door moves or
    waits: refused); the walk-over doors requested now and then throughout"""
    rng = random.Random(seed)
    visits = [(si, dp.boxes[si]) for si in dp.order if si in dp.boxes]
    visits += [(si, b) for si in dp.order for b in dp.switches.get(si, ())]
    walked = sorted({t[0] for t in dp.triggers})
    out = []
    for cards in ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 1)):
        for si, (x0, y0, x1, y1) in visits:
            if cards not in ((0, 0, 0), (1, 1, 1)) and dp.kinds[si] not in ("blue", "yellow", "red"):
                continue
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            for f in range(12):
                x, y = (cx, cy) if f < 3 else (rng.randint(x0 - 4, x1 + 4), rng.randint(y0 - 4, y1 + 4))
                use = f < 2 or rng.random() < 0.15
                req = {s for s in walked if rng.random() < 0.03}
                out.append((x << 16, y << 16, use, cards, req))
    return out


def door_expect(dp, sched):
    st, want = dp.initial(), []
    for x16, y16, use, (b, yl, r), req in sched:
        st = (st[0], st[1], frozenset(req), st[3])
        st = dp.tic(st, use, x16, y16, has_blue=bool(b), has_yellow=bool(yl), has_red=bool(r))
        for si in dp.order:
            want += [*(v for v in st[0][si]), 0]
    return want


def door_feed(dp, sched):
    out = b""
    for x16, y16, use, cards, req in sched:
        out += bytes([1]) + struct.pack("<II", x16 & M32, y16 & M32) + bytes([int(use), *cards])
        out += bytes(int(si in req) for si in dp.order)
    return out


def test_the_door_tic_runs_every_e1m2_kind_as_DoorPhase(tmp_path, lvl):
    sched = door_schedule(lvl)
    got = _run(tmp_path, "doors", door_program(lvl), door_feed(lvl, sched))
    want = door_expect(lvl, sched)
    assert len(got) == len(want)
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, (len(bad), bad[:5])
    # not vacuous: every door moved -- the key doors, the switch doors, the D1 and W1 open-stay doors
    per = 5 * len(lvl.order)
    moved = {si for f in range(len(sched)) for d, si in enumerate(lvl.order) if want[f * per + 5 * d]}
    assert moved == set(lvl.order), sorted(set(lvl.order) - moved)


# ---- 2. the walk-over lines ----------------------------------------------------------------------------------------

def walk_program(dp, text=None):
    nd, nw = len(dp.order), len(dp.triggers)
    lines = text if text is not None else walkover_lines(dp.triggers, dp.order, PLAYER_R)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            f"hex.zero {max(nw, 1)}, wfired", *lines]
    body += sum((_pr(f"wfired + {k}*dw", 1) for k in range(nw)), [])
    body += sum((_pr(f"dreq + {d}*dw", 1) for d in range(nd)), [])
    body += [f"hex.zero {nd}, dreq", ";loop", "done:", "stl.loop", "rmagic: hex.vec 2",
             "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8",
             *door_decls(nd, nw)]
    return "\n".join(body) + "\n"


def walk_moves(dp, seed=11, per=80):
    """moves of at most 16 units around every trigger line, from random fractional points along and beside it"""
    rng = random.Random(seed)
    out = []
    for geo in sorted({t[1:] for t in dp.triggers}):
        if geo[0] == "d":
            _d, x1, y1, x2, y2 = geo
        elif geo[0] == "y":
            _a, c, lo, hi = geo
            x1, y1, x2, y2 = lo, c, hi, c
        else:
            _a, c, lo, hi = geo
            x1, y1, x2, y2 = c, lo, c, hi
        for _ in range(per):
            t = rng.uniform(-0.3, 1.3)
            px = (x1 + (x2 - x1) * t + rng.uniform(-20, 20)) * 65536
            py = (y1 + (y2 - y1) * t + rng.uniform(-20, 20)) * 65536
            old = (int(px), int(py))
            new = (old[0] + rng.randint(-16 << 16, 16 << 16), old[1] + rng.randint(-16 << 16, 16 << 16))
            if rng.random() < 0.2:                     # on a vertex / the line's grid, exactly
                old = ((x1 + rng.randint(-16, 16)) << 16, (y1 + rng.randint(-16, 16)) << 16)
                new = ((x1 + rng.randint(-16, 16)) << 16, (y1 + rng.randint(-16, 16)) << 16)
            out.append((old, new))
    return out


def walk_expect(dp, moves):
    want = []
    for old, new in moves:
        st = dp.after_move(dp.initial(), old, new, PLAYER_R)
        want += list(st[1]) + [int(si in st[2]) for si in dp.order]
    return want


def walk_feed(moves):
    return b"".join(bytes([1]) + struct.pack("<IIII", o[0] & M32, o[1] & M32, n[0] & M32, n[1] & M32)
                    for o, n in moves)


def _walk_check(tmp_path, dp, name):
    moves = walk_moves(dp)
    got = _run(tmp_path, name, walk_program(dp), walk_feed(moves))
    want = walk_expect(dp, moves)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    return moves, want


def test_e1m2_walkover_lines_fire_as_DoorPhase(tmp_path, lvl):
    moves, want = _walk_check(tmp_path, lvl, "walk2")
    nw, nd = len(lvl.triggers), len(lvl.order)
    rows = [want[i * (nw + nd):(i + 1) * (nw + nd)] for i in range(len(moves))]
    both = [lvl.order.index(30), lvl.order.index(266)]
    assert sum(r[nw + both[0]] and r[nw + both[1]] for r in rows) >= 5       # tag 16 opens both, together
    assert all(r[nw + both[0]] == r[nw + both[1]] for r in rows)


def test_e1m3s_slanted_ring_fires_as_DoorPhase(tmp_path, e1m3):
    assert sum(t[1] == "d" for t in e1m3.triggers) >= 4
    moves, want = _walk_check(tmp_path, e1m3, "walk3")
    nw = len(e1m3.triggers)
    per = nw + len(e1m3.order)
    dk = [k for k, t in enumerate(e1m3.triggers) if t[1] == "d"]
    assert sum(want[i * per + k] for i in range(len(moves)) for k in dk) >= 20   # the slanted lines fire


# ---- 3. the slanted door contact -------------------------------------------------------------------------------------

def _poly_doors(dp):
    return [si for si in dp.order if dp.contact[si][0][0] == "poly" and not dp.contact[si][0][2]]


def contact_program(dp, doors, radius, texts=None):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy"]
    for j, si in enumerate(doors):
        lines = texts[j] if texts else door_contact_lines(f"ct{si}", dp.contact[si], radius, f"ct{si}_y", f"ct{si}_n")
        body += [*lines, f"  ct{si}_y:", "    stl.output '1'", f"    ;ct{si}_e", f"  ct{si}_n:",
                 "    stl.output '0'", f"  ct{si}_e:"]
    body += ["    stl.output 32", ";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "viewx: hex.vec 8",
             "viewy: hex.vec 8", *door_decls(1, 1)]
    return "\n".join(body) + "\n"


def contact_points(dp, doors, seed=2, step=3):
    rng = random.Random(seed)
    pts = []
    for si in doors:
        e = dp.contact[si][0][1]
        xs, ys = [p for q in e for p in (q[0], q[2])], [p for q in e for p in (q[1], q[3])]
        for gx in range(min(xs) - 34, max(xs) + 35, step):
            for gy in range(min(ys) - 34, max(ys) + 35, step):
                pts.append(((gx << 16) + rng.choice((0, 1, -1, 0x8000)), (gy << 16) + rng.choice((0, 1, -1))))
        # every slanted line's inflated bbox edges EXACTLY (the strict overlap's boundary), both radii
        for ax, ay, bx, by in e:
            if ax == bx or ay == by:
                continue
            for r in (PLAYER_R, 30):
                for gx in (min(ax, bx) - r, max(ax, bx) + r):
                    pts += [(gx << 16, gy << 16) for gy in range(min(ay, by) - r, max(ay, by) + r + 1, 2)]
                for gy in (min(ay, by) - r, max(ay, by) + r):
                    pts += [(gx << 16, gy << 16) for gx in range(min(ax, bx) - r, max(ax, bx) + r + 1, 2)]
    return pts


def contact_expect(dp, doors, radius, pts):
    return "".join("".join(str(int(D.touches_door(dp.contact[si], x, y, radius << 16))) for si in doors) + " "
                   for x, y in pts)


def _contact_run(tmp_path, dp, doors, radius, pts, texts=None):
    feed = b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) for x, y in pts)
    src = tmp_path / "ct.fj"
    src.write_text(contact_program(dp, doors, radius, texts), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / "ct.fjm"
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode()


@pytest.mark.parametrize("radius", [PLAYER_R, 30])
def test_the_slanted_contact_is_touches_door(tmp_path, lvl, radius):
    doors = _poly_doors(lvl)
    assert set(doors) == {30, 299, 318}
    pts = contact_points(lvl, doors, step=4 if radius == PLAYER_R else 6)
    want = contact_expect(lvl, doors, radius, pts)
    got = _contact_run(tmp_path, lvl, doors, radius, pts)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    assert want.count("1") > 200 and want.count("0") > 200


def test_a_door_a_box_fits_inside_is_refused(lvl):
    with pytest.raises(AssertionError):
        door_contact_lines("x", lvl.contact[208], PLAYER_R, "y", "n")


# ---- R9 --------------------------------------------------------------------------------------------------------------

def _d(dp, si):
    return dp.order.index(si)


TIC_MUTANTS = [
    ("the yellow door's card check dropped", lambda dp: ("    hex.if0 1, pcard_y, ", "    hex.if0 1, duse, ")),
    ("the red door reads the yellow card", lambda dp: ("    hex.if0 1, pcard_r, ", "    hex.if0 1, pcard_y, ")),
    ("the switch presses a moving door", lambda dp: (
        f"    hex.if0 1, ddir + {_d(dp, 258)}*dw, dr{_d(dp, 258)}_swi", f"    ;dr{_d(dp, 258)}_swi")),
    ("the switch presses a door waiting open", lambda dp: (
        f"    hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * _d(dp, 258)}*dw, dr{_d(dp, 258)}_swt",
        f"    ;dr{_d(dp, 258)}_swt")),
    ("the blazing open-stay one stride short", lambda dp: (
        f"    hex.inc 1, dstate + {_d(dp, 30)}*dw\n", "")),
]


@pytest.mark.parametrize("label, mk", TIC_MUTANTS, ids=[m[0] for m in TIC_MUTANTS])
def test_a_mutated_door_tic_fails(tmp_path, lvl, label, mk):
    old, new = mk(lvl)
    sched = door_schedule(lvl)
    got = _run(tmp_path, "m", door_program(lvl, _mutated(tic_lines(lvl), old, new)), door_feed(lvl, sched))
    assert got != door_expect(lvl, sched), label


def test_control_a_tag_firing_one_of_its_two_doors(tmp_path, lvl):
    lines = walkover_lines(lvl.triggers, lvl.order, PLAYER_R)
    old = f"    hex.set 1, dreq + {_d(lvl, 266)}*dw, 1"
    moves = walk_moves(lvl)
    got = _run(tmp_path, "m", walk_program(lvl, _mutated(lines, old, "")), walk_feed(moves))
    assert got != walk_expect(lvl, moves)


def test_control_the_slanted_crossing_ignores_the_side(tmp_path, e1m3):
    k = next(k for k, t in enumerate(e1m3.triggers) if t[1] == "d")
    lines = walkover_lines(e1m3.triggers, e1m3.order, PLAYER_R)
    old = f", wo{k}_x, wo{k}_no, wo{k}_x"
    moves = walk_moves(e1m3)
    got = _run(tmp_path, "m", walk_program(e1m3, _mutated(lines, old, f", wo{k}_x, wo{k}_x, wo{k}_x")),
               walk_feed(moves))
    assert got != walk_expect(e1m3, moves)


CONTACT_MUTANTS = [
    ("the slanted straddle ignores the corners' sides", "_s2, ct318_y, ct318_dn0, ct318_y", "_s2, ct318_y, ct318_y, ct318_y"),
    ("the slanted bbox inclusive", "ct299_d0_b0b, ct299_dn0, ct299_dn0", "ct299_d0_b0b, ct299_d0_b0b, ct299_dn0"),
    ("a split door's axis line dropped", "    ;ct30_y\n  ct30_n0:", "    ;ct30_n0\n  ct30_n0:"),
]


@pytest.mark.parametrize("label, old, new", CONTACT_MUTANTS, ids=[m[0] for m in CONTACT_MUTANTS])
def test_a_mutated_contact_fails(tmp_path, lvl, label, old, new):
    doors = _poly_doors(lvl)
    pts = contact_points(lvl, doors, step=4)
    texts = []
    for si in doors:
        lines = door_contact_lines(f"ct{si}", lvl.contact[si], PLAYER_R, f"ct{si}_y", f"ct{si}_n")
        text = "\n".join(lines)
        if old in text:
            lines = _mutated(lines, old, new)
        texts.append(lines)
    assert any("\n".join(t) != "\n".join(door_contact_lines(f"ct{si}", lvl.contact[si], PLAYER_R, f"ct{si}_y",
                                                            f"ct{si}_n")) for t, si in zip(texts, doors)), label
    got = _contact_run(tmp_path, lvl, doors, PLAYER_R, pts, texts)
    assert got != contact_expect(lvl, doors, PLAYER_R, pts), label
