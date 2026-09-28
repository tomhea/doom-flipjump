"""M7 P2a.1 -- the new door code RUN in fj against doomfj.doors: the door tic with every E1M1 kind (the
card, the walk-over requests, the blazing stride, the stay), the walk-over triggers, and the blue
card's pickup (the box and the reach). Nothing here is modelled: each program is the emitter's own
text (doorcode.door_tic_lines, walkover_lines, card_pickup_lines) on E1M1's real doors, triggers
and card, fed records and read back; the expectation is doomfj.doors.DoorPhase and the model's
touch rule (combat.ITEM_RADIUS + PLAYER_R, REACH_UP / REACH_DOWN).

R9: MUTANTS -- one real edit of the emitted text each -- must each make its program disagree.
"""
import random
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import doors as D
from doomfj.combat import ITEM_RADIUS, PLAYER_R, REACH_DOWN, REACH_UP
from doomfj.doorcode import WAIT_NIBBLES, card_pickup_lines, door_decls, door_tic_lines, walkover_lines
from doomfj.harness import W
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

FIX = "tests/fixtures/freedoom_e1m1.wad"
M32 = 0xFFFFFFFF
CARD = (2192, 576)
CARD_Z = 136                       # sector 35's floor (the card's ONFLOORZ)


@pytest.fixture(scope="module")
def lvl():
    mw = WadFile.from_path(FIX)
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    boxes = D.use_boxes_xy(secs, lds, sds, bake_bsp(mw, "E1M1").vertexes)
    dp = D.DoorPhase(secs, lds, sds, mw.vertexes("E1M1"), boxes)
    return dp


def _run(tmp, name, program, feed):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode().split()


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


# ---- 1. the door tic ----------------------------------------------------------------------------------

def door_program(dp, text=None):
    nd = len(dp.order)
    tic = text if text is not None else door_tic_lines(dp.order, dp.nstates, dp.boxes, dp.kinds)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 1, rbyte", "hex.mov 1, duse, rbyte",
            "hex.input 1, rbyte", "hex.mov 1, pcard, rbyte"]
    for d in range(nd):
        body += ["hex.input 1, rbyte", f"hex.mov 1, dreq + {d}*dw, rbyte"]
    body += list(tic)
    for d in range(nd):
        body += _pr(f"dstate + {d}*dw", 1) + _pr(f"ddir + {d}*dw", 1) + _pr(f"dsub + {d}*dw", 1)
        body += _pr(f"dwait + {WAIT_NIBBLES * d}*dw", WAIT_NIBBLES) + _pr(f"dreq + {d}*dw", 1)
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "viewx: hex.vec 8", "viewy: hex.vec 8", *door_decls(nd, len(dp.triggers))]
    return "\n".join(body) + "\n"


def door_schedule(dp, seed=5):
    """every boxed door visited twice -- without the card, then with it -- pressed from its box
    centre and watched for 14 frames; the walk-over doors requested now and then throughout"""
    rng = random.Random(seed)
    targets = [si for si in dp.order if si in dp.boxes]
    out = []
    for card in (0, 1):
        for si in targets:
            x0, y0, x1, y1 = dp.boxes[si]
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            for f in range(14):
                x, y = (cx, cy) if f < 3 else (rng.randint(x0 - 4, x1 + 4), rng.randint(y0 - 4, y1 + 4))
                use = f < 2 or rng.random() < 0.05
                req = {s for s in dp.order if dp.kinds[s] == "walkover" and rng.random() < 0.03}
                out.append((x << 16, y << 16, use, card, req))
    return out


def door_expect(dp, sched):
    st, want = dp.initial(), []
    for x16, y16, use, card, req in sched:
        st = (st[0], st[1], frozenset(req), st[3])
        st = dp.tic(st, use, x16, y16, has_blue=bool(card))
        for si in dp.order:
            want += [*(v for v in st[0][si]), 0]
    return want


def door_feed(dp, sched):
    out = b""
    for x16, y16, use, card, req in sched:
        out += bytes([1]) + struct.pack("<II", x16 & M32, y16 & M32) + bytes([int(use), card])
        out += bytes(int(si in req) for si in dp.order)
    return out


def _ints(tokens):
    return [int(t, 16) for t in tokens]


def test_the_door_tic_runs_every_kind_as_DoorPhase(tmp_path, lvl):
    sched = door_schedule(lvl)
    got = _ints(_run(tmp_path, "doors", door_program(lvl), door_feed(lvl, sched)))
    want = door_expect(lvl, sched)
    assert len(got) == len(want)
    bad = [i for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, (len(bad), bad[:5])
    # not vacuous: the blazing door, a walk-over door and a blue door each moved
    per = 5 * len(lvl.order)
    moved = {si for f in range(len(sched)) for d, si in enumerate(lvl.order) if want[f * per + 5 * d]}
    assert {84, 51, 71} <= moved and moved & {77, 145}, sorted(moved)


# ---- 2. the walk-over triggers ------------------------------------------------------------------------

def walk_program(dp, text=None):
    nd, nw = len(dp.order), len(dp.triggers)
    lines = text if text is not None else walkover_lines(dp.triggers, dp.order, PLAYER_R)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 1, rmagic", "hex.if0 2, rmagic, keep", f"hex.zero {max(nw, 1)}, wfired", "keep:",
            *lines]
    body += sum((_pr(f"wfired + {k}*dw", 1) for k in range(nw)), [])
    body += sum((_pr(f"dreq + {d}*dw", 1) for d in range(nd)), [])
    body += [f"hex.zero {nd}, dreq", ";loop", "done:", "stl.loop", "rmagic: hex.vec 2",
             "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "viewx: hex.vec 8", "viewy: hex.vec 8",
             *door_decls(nd, nw)]
    return "\n".join(body) + "\n"


def walk_moves(dp, seed=11):
    rng = random.Random(seed)
    out = []
    for _si, axis, coord, lo, hi in dp.triggers:
        for _ in range(60):
            a0 = coord + rng.randint(-20, 20)
            a1 = a0 + rng.choice((-16, -9, -1, 1, 9, 16, 0))
            o = rng.choice((lo - 17, lo - 16, lo - 15, lo, (lo + hi) // 2, hi, hi + 15, hi + 16, hi + 17,
                            rng.randint(lo - 30, hi + 30)))
            frac = rng.choice((0, 1, 0x8000, 0xFFFF))
            old = ((o << 16) + frac, (a0 << 16) + frac) if axis == "x" else None
            if axis == "y":
                old, new = ((o << 16), (a0 << 16) + frac), ((o << 16), (a1 << 16) + frac)
            else:
                old, new = ((a0 << 16) + frac, (o << 16)), ((a1 << 16) + frac, (o << 16))
            out.append((old, new))
    # the edges, deterministically: onto / off the line on the crossing axis, and the inflated
    # extent's ends (strict) on the other
    for _si, axis, coord, lo, hi in dp.triggers:
        L = coord << 16
        for o in (lo - PLAYER_R, lo - PLAYER_R + 1, (lo + hi) // 2, hi + PLAYER_R - 1, hi + PLAYER_R):
            for a_old, a_new in ((L, L - 1), (L, L - (8 << 16)), (L + 1, L), (L + (8 << 16), L),
                                 (L - (8 << 16), L + (8 << 16)), (L + (8 << 16), L - (8 << 16))):
                of = o << 16
                if axis == "y":
                    out.append(((of, a_old), (of, a_new)))
                else:
                    out.append(((a_old, of), (a_new, of)))
    rng.shuffle(out)
    return out


def walk_expect(dp, moves, fresh=True):
    """`fresh`: every move from unfired triggers (each probe independent); else W1 latches"""
    st, want = dp.initial(), []
    for old, new in moves:
        if fresh:
            st = dp.initial()
        st = dp.after_move(st, old, new, PLAYER_R)
        want += list(st[1]) + [int(si in st[2]) for si in dp.order]
        st = (st[0], st[1], frozenset(), st[3])
    return want


def walk_feed(moves, fresh=True):
    return b"".join(bytes([1]) + struct.pack("<IIII", old[0] & M32, old[1] & M32, new[0] & M32, new[1] & M32)
                    + bytes([int(fresh)]) for old, new in moves)


def test_the_walkover_triggers_fire_as_DoorPhase(tmp_path, lvl):
    moves = walk_moves(lvl)
    got = _ints(_run(tmp_path, "walk", walk_program(lvl), walk_feed(moves)))
    want = walk_expect(lvl, moves)
    assert got == want, [i for i, (g, w) in enumerate(zip(got, want)) if g != w][:5]
    assert want.count(1) >= 40, "both triggers must fire on many probes"


def test_a_walkover_trigger_fires_once(tmp_path, lvl):
    """W1: the second crossing of a fired trigger presses nothing"""
    _si, _axis, coord, lo, hi = lvl.triggers[0]
    x = ((lo + hi) // 2) << 16
    there, back = ((x, (coord + 8) << 16), (x, (coord - 8) << 16)), ((x, (coord - 8) << 16), (x, (coord + 8) << 16))
    moves = [there, back, there]
    got = _ints(_run(tmp_path, "walk1", walk_program(lvl), walk_feed(moves, fresh=False)))
    want = walk_expect(lvl, moves, fresh=False)
    nw = len(lvl.triggers)
    per = nw + len(lvl.order)
    presses = sum(sum(want[k * per + nw:(k + 1) * per]) for k in range(len(moves)))
    assert got == want and presses == 1, (got, want)          # the door pressed once


# ---- 3. the card's pickup --------------------------------------------------------------------------------

def card_program(text=None):
    lines = text if text is not None else card_pickup_lines(
        "t_", CARD, "cslot", CARD_Z - (REACH_UP), CARD_Z + REACH_DOWN, ITEM_RADIUS + PLAYER_R)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cpx", "hex.input 4, cpy", "hex.input 4, cm_hf",
            "hex.input 1, rmagic", "hex.if0 2, rmagic, keep", "hex.zero 1, pcard", "hex.set 2, cslot, 1",
            "keep:", *lines,
            *_pr("pcard", 1), *_pr("cslot", 2),
            ";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "cpx: hex.vec 8", "cpy: hex.vec 8",
            "cm_hf: hex.vec 8", "cslot: hex.vec 2, 1", *door_decls(1, 1)]
    return "\n".join(body) + "\n"


def card_tries(seed=3):
    rng = random.Random(seed)
    bd = ITEM_RADIUS + PLAYER_R
    kx, ky = CARD
    out = []
    for z in (24, 79, 80, 136, 144, 145):
        for dx in (-bd - 1, -bd, -bd + 1, 0, bd - 1, bd, bd + 1):
            out.append((((kx + dx) << 16) + rng.choice((0, 1, 0xFFFF)), (ky << 16), z))
            out.append(((kx << 16), ((ky + dx) << 16) + rng.choice((0, 1, 0xFFFF)), z))
    # the edges exactly: each axis at +-bd and +-(bd - 1) with the other at the centre, every reach
    for z in (79, 80, 144, 145):
        for d in (-bd, -bd + 1, bd - 1, bd):
            out.append((((kx + d) << 16), (ky << 16), z))
            out.append(((kx << 16), ((ky + d) << 16), z))
    rng.shuffle(out)
    return out


def card_expect(tries, fresh=True):
    """the model's touch rule; `fresh`: each try with the card untaken, else it latches"""
    bd = (ITEM_RADIUS + PLAYER_R) << 16
    taken, want = 0, []
    for x16, y16, z in tries:
        if fresh:
            taken = 0
        if not taken and abs((CARD[0] << 16) - x16) < bd and abs((CARD[1] << 16) - y16) < bd \
                and -REACH_DOWN <= CARD_Z - z <= REACH_UP:
            taken = 1
        want += [taken, 0 if taken else 1]
    return want


def card_feed(tries, fresh=True):
    return b"".join(bytes([1]) + struct.pack("<III", x & M32, y & M32, z & M32) + bytes([int(fresh)])
                    for x, y, z in tries)


def test_the_card_is_taken_by_the_models_box_and_reach(tmp_path):
    tries = card_tries()
    got = _ints(_run(tmp_path, "card", card_program(), card_feed(tries)))
    assert got == card_expect(tries)


def test_the_card_stays_taken(tmp_path):
    """the latch: once taken, a try from out of reach leaves it taken and the slot hidden"""
    tries = [((CARD[0] << 16), (CARD[1] << 16), CARD_Z), ((CARD[0] << 16), (CARD[1] << 16), 24)]
    got = _ints(_run(tmp_path, "card1", card_program(), card_feed(tries, fresh=False)))
    assert got == card_expect(tries, fresh=False) == [1, 0, 1, 0]


def test_the_card_is_not_taken_from_below():
    """the model's rule, one level up: sector 124 (floor 24) inside the card's box is out of reach"""
    assert card_expect([((CARD[0] << 16), ((CARD[1] + 34) << 16), 24)]) == [0, 1]


# ---- R9 ----------------------------------------------------------------------------------------------------

def _mutated(lines, old, new):
    text = "\n".join(lines)
    assert text.count(old) >= 1, old
    return text.replace(old, new, 1).split("\n")


MUTANTS = [
    ("the card box inclusive at its low edge", "card", "hex.scmp 8, cpx, dbox, t_ck_no, t_ck_no, t_ck0a",
     "hex.scmp 8, cpx, dbox, t_ck_no, t_ck0a, t_ck0a"),
    ("the reach one unit short", "card", "t_cky, t_cky, t_ck_no", "t_ck_no, t_cky, t_ck_no"),
    ("the walk-over side test counts a point on the line as high", "walk",
     "hex.scmp 8, cm_oy, dbox, wo0_ol, wo0_ol, wo0_og", "hex.scmp 8, cm_oy, dbox, wo0_ol, wo0_og, wo0_og"),
    ("the walk-over extent inclusive", "walk", "wo1_fire, wo1_no, wo1_no", "wo1_fire, wo1_fire, wo1_no"),
    ("the walk-over fires twice", "walk", "    hex.set 1, wfired + 0*dw, 1", "    hex.zero 1, wfired + 0*dw"),
    ("the blazing door one stride short", "doors", "    hex.inc 1, dstate + 8*dw\n", ""),
    ("the blue door's card check dropped", "doors", "    hex.if0 1, pcard, dr", "    hex.if0 1, duse, dr"),
]


@pytest.mark.parametrize("label, prog, old, new", MUTANTS, ids=[m[0] for m in MUTANTS])
def test_a_mutated_block_fails(tmp_path, lvl, label, prog, old, new):
    if prog == "card":
        tries = card_tries()
        lines = card_pickup_lines("t_", CARD, "cslot", CARD_Z - REACH_UP, CARD_Z + REACH_DOWN,
                                  ITEM_RADIUS + PLAYER_R)
        got = _ints(_run(tmp_path, "m", card_program(_mutated(lines, old, new)), card_feed(tries)))
        assert got != card_expect(tries), label
    elif prog == "walk":
        moves = walk_moves(lvl)
        lines = walkover_lines(lvl.triggers, lvl.order, PLAYER_R)
        got = _ints(_run(tmp_path, "m", walk_program(lvl, _mutated(lines, old, new)), walk_feed(moves)))
        assert got != walk_expect(lvl, moves), label
    else:
        sched = door_schedule(lvl)
        lines = door_tic_lines(lvl.order, lvl.nstates, lvl.boxes, lvl.kinds)
        got = _ints(_run(tmp_path, "m", door_program(lvl, _mutated(lines, old, new)), door_feed(lvl, sched)))
        assert got != door_expect(lvl, sched), label
