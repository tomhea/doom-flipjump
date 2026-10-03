"""M7 P3.3 (D3 d): `sim.thing_pass_depth` on the real engine -- a leaf's runtime things handed to `thing_leaf`
NEAREST FIRST, against the oracle's rule (`render_wall_frame(rt_depth_order="aprox")`: the leaf's runtime part
sorted by `reference_model.aprox_depth_key` -- P_AproxDistance from the player's integer position -- stably over
the list's ascending order). The harness calls the oracle's key; it does not restate the formula.

The real macro runs on baked per-leaf lists (one thing, two, three, four) with every thing's position and the
player's fed per record; `thing_leaf` is a stub that prints the index `thing_load` handed it (sp_ti), then DIRTIES
every register the walk must clear (what thing_load_cold and the record body leave behind). The records hold equal
keys (the tie rule), negative coordinates and fractional player positions.

THE BUDGET STOP (`tstop`): each record carries k, the draws after which the stub sets `tstop` (thing_record_body's
budget). tstop is zeroed at the start of each record and stays set for the record's later leaves, so the drawn
sequence must be the oracle's per-leaf orders, concatenated in the walk's leaf order (WALK), cut to its first k --
thing_pass's budget counts across leaves the same way. k = 0 stops before the first draw; some records never stop.
WALK puts the one-thing leaf third, so a stop reaches both the multi-thing rounds and the one-thing path.

THE CLEAR: after every leaf ALL THIRTEEN registers the walk clears (REGS, sp_x .. sp_lt) are printed and must be
zero -- thing_pass's own contract for the next leaf's baked xor_by.

⚠ ONE IMAGE, MANY RECORDS: a walk that leaves a register dirty corrupts the next record.
⚠ THE CONTROLS (R9), each STRICT -- all N records present and exactly the named symptom:
  first / nody / tie (the first candidate taken instead of the least, the key without its dy, the tie toward the
  later index) and nostop / nostop1 (the rounds' and the one-thing path's tstop test removed): the ORDER parts from
  the oracle's while every register still clears; narrow (sp_lt's clear narrowed to one nibble): the order still
  matches and sp_lt, alone, is left dirty.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import monstercode as MC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.reference_model import aprox_depth_key
from doomfj.things import byte_array_decl, spawn_leaf_lists

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
BINDS = [0, 1, 1, 2, 2, 2, 3, 3, 3, 3]               # thing -> leaf: one, two, three and four things
NT, NLEAF = len(BINDS), 4
WALK = (1, 3, 0, 2)                                   # the leaf order the program walks: the one-thing leaf third
N = 160
NO_STOP = 0xFF                                        # k past every draw (NT < 255): the record never stops
# the registers sim.thing_pass_depth clears, at their declared widths (nibbles), in print order
REGS = (("sp_x", 8), ("sp_y", 8), ("sp_z", 8), ("sp_left", 8), ("sp_w", 8), ("sp_hh", 8), ("sp_tzmax", 8),
        ("sp_tzmax2", 8), ("sp_mon", 2), ("sp_base", 4), ("sp_base2", 4), ("sp_dw", 2), ("sp_lt", 2))
CLEAR = "0" * sum(n for _, n in REGS)


def key(rec, t):
    """the oracle's depth key of thing t in record rec"""
    px16, py16, pos, _k = rec
    return aprox_depth_key(px16, py16, *pos[t])


def full_order(rec):
    """the oracle's order of each leaf's things, the leaves in WALK order"""
    return [sorted((t for t in range(NT) if BINDS[t] == leaf), key=lambda t: key(rec, t)) for leaf in WALK]


def expect_drawn(rec):
    """what the walk draws in each leaf (WALK order): the oracle's orders concatenated, cut to the first k"""
    left, out = rec[3], []
    for o in full_order(rec):
        out.append(o[:max(0, left)])
        left -= len(o)
    return out


def records():
    rnd = random.Random(0x33D)
    krnd = random.Random(0x33E)                       # the stops: their own stream, the positions unchanged
    out = []
    for k in range(N):
        px, py = rnd.randint(-900, 2500), rnd.randint(-900, 2500)
        px16 = ((px << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        py16 = ((py << 16) | rnd.choice((0, 0x8000, rnd.randrange(1 << 16)))) & M32
        pos = []
        for t in range(NT):
            if k % 3 == 0 and t % 2 == 1:             # ties: mirror the previous thing about the player
                qx, qy = pos[-1]
                pos.append((2 * px - qx, 2 * py - qy) if rnd.random() < 0.5 else (2 * px - qx, qy))
            else:
                pos.append((px + rnd.randint(-300, 300), py + rnd.randint(-300, 300)))
        stop = NO_STOP if krnd.random() < 0.4 else krnd.randint(0, NT)
        out.append((px16, py16, pos, stop))
    return out


def _dist_leaf():
    lines = MC.p32a_leaves()
    return lines[:lines.index("mt_psec_leaf:")]


MUTS = {
    "first": ("        hex.cmp 4, mt_d, td_bk, take, next, next   // equal key, later t: not better (the scan is ascending)\n",
              "        ;next\n"),
    "nody": ("        hex.mov 4, mt_dy, sp_y + 4*dw\n", "        hex.mov 4, mt_dy, viewy + 4*dw\n"),   # dy = 0
    "tie": ("        hex.cmp 4, mt_d, td_bk, take, next, next   //", "        hex.cmp 4, mt_d, td_bk, take, take, next   //"),
    "nostop": ("      round:\n        hex.if1 1, tstop, done\n", "      round:\n"),
    "nostop1": ("      single:                                  // one thing: as thing_pass\n"
                "        hex.if1 1, tstop, done\n",
                "      single:                                  // one thing: as thing_pass\n"),
    # a clear narrower than the declared width (thing_pass's own warning): sp_lt's high nibble survives. (Removing
    # the clear outright does not assemble -- sp_lt would be an unused label of the macro.)
    "narrow": ("        hex.sparse_zero HOT_PAD, 2, sp_lt\n        rep(anim, k) hex.zero 2, lthi\n      empty:\n",
               "        hex.sparse_zero HOT_PAD, 1, sp_lt\n        rep(anim, k) hex.zero 2, lthi\n      empty:\n"),
}
# what each control must break: the ORDER (registers still clear), or the CLEAR of sp_lt alone (order intact)
CONTROLS = {"first": "order", "nody": "order", "tie": "order", "nostop": "order", "nostop1": "order",
            "narrow": "clear"}


def _dirty(n):
    return int(("a5" * n)[:n], 16)


def _program(mut=None):
    head, nxt = spawn_leaf_lists(BINDS, NLEAF)
    sim = (FJ / "sim.fj").read_text(encoding="utf-8").replace("\r\n", "\n")
    if mut:
        old, new = MUTS[mut]
        assert sim.count(old) == 1, mut
        sim = sim.replace(old, new)
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, tpd_k",
            "hex.zero 1, tstop",                       # the budget re-arms per record
            "hex.if0 2, tpd_k, tpd_stop0", ";tpd_go", "tpd_stop0:", "hex.set 1, tstop, 1", "tpd_go:"]
    for t in range(NT):
        body += ["hex.input 4, thpos_rt + %d*dw" % (16 * t), "hex.input 4, thpos_rt + %d*dw" % (16 * t + 8)]
    for leaf in WALK:
        body += ["hex.set w/4, cur_ss, %d" % leaf, "stl.fcall tpd_leaf, tp_ret", "stl.output 124",
                 *["hex.print_as_digit %d, %s, 0" % (n, r) for r, n in REGS], "stl.output 59"]
    body += ["stl.output 10", ";loop", "done:", "stl.loop",
             "tpd_leaf:", "sim.thing_pass_depth throw, 1, thpos_rt, 0, 0, 0, 0", "stl.fret tp_ret",
             # the stub: print the drawn index, dirty every register the walk clears, count the budget down
             "thing_leaf:", "hex.print_as_digit 2, sp_ti, 0", "stl.output 44",
             *["hex.set %d, %s, %d" % (n, r, _dirty(n)) for r, n in REGS],
             "hex.dec 2, tpd_k", "hex.if0 2, tpd_k, tpd_stopk", "stl.fret thing_ret",
             "tpd_stopk:", "hex.set 1, tstop, 1", "stl.fret thing_ret",
             *_dist_leaf(),
             "throw:", *[";0"] * (17 * 16),
             byte_array_decl("sshead", head, NLEAF + 1), byte_array_decl("thnext", nxt, NT + 1),
             "thpos_rt: hex.vec %d" % (16 * NT),
             "rmagic: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "cur_ss: hex.vec w/4", "tpd_k: hex.vec 2",
             "tp_ret: ;0", "thing_ret: ;0", "tstop: hex.vec 1", "ss_flr: hex.vec 4", "sp_ti: hex.vec w/4",
             *["%s: hex.vec %d" % (r, n) for r, n in REGS],
             *MC.P33_DECLS,
             "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
             "mt_t: hex.vec 4", "mt_ret: hex.vec w/4"]
    return "\n".join(body) + "\n", sim


def _run(tmp, name, mut=None):
    prog, sim = _program(mut)
    p = tmp / (name + ".fj")
    p.write_text(prog, encoding="utf-8")
    s = tmp / (name + "_sim.fj")
    s.write_text(sim, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), s.resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    feed = b""
    for px16, py16, pos, stop in records():
        feed += bytes([1]) + struct.pack("<II", px16, py16) + bytes([stop])
        for x, y in pos:
            feed += struct.pack("<II", (x << 16) & M32, (y << 16) & M32)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = []
    for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]:
        leaves = []
        for part in line.split(";")[:NLEAF]:
            order, _, regs = part.partition("|")
            leaves.append(([int(v, 16) for v in order.split(",") if v], regs))
        got.append(leaves)
    return got


def _verdict(got):
    """(records, the (record, leaf) whose drawn order parts from the oracle's, those whose registers are not clear)"""
    order_bad, reg_bad = [], []
    for k, (g, r) in enumerate(zip(got, records())):
        want = expect_drawn(r)
        for j, leaf in enumerate(WALK):
            order, regs = g[j] if j < len(g) else (None, None)
            if order != want[j]:
                order_bad.append((k, leaf, order, want[j], r[3]))
            if regs != CLEAR:
                reg_bad.append((k, leaf, regs))
    return len(got), order_bad, reg_bad


def test_the_records_hold_ties_reorders_and_stops():
    recs = records()
    ties = sum(1 for r in recs for leaf in range(1, NLEAF)
               if len({key(r, t) for t in range(NT) if BINDS[t] == leaf}) < BINDS.count(leaf))
    # (record, leaf) whose DRAWN part differs from index order's: what the order check bites on
    moved = sum(1 for r in recs for o, d in zip(full_order(r), expect_drawn(r)) if d != sorted(o)[:len(d)])
    # a stop INSIDE a multi-thing leaf, where the depth-order prefix differs from the index-order one
    cut = sum(1 for r in recs for o, d in zip(full_order(r), expect_drawn(r))
              if 0 < len(d) < len(o) and d != sorted(o)[:len(d)])
    stops = [r[3] for r in recs]
    before_single = sum(1 for s in stops if s <= sum(BINDS.count(lf) for lf in WALK[:WALK.index(0)]))
    counts = dict(ties=ties, moved=moved, cut=cut, zero=stops.count(0), never=stops.count(NO_STOP),
                  before_single=before_single)
    assert (ties >= 20 and moved >= 100 and cut >= 20 and counts["zero"] >= 3 and counts["never"] >= 40
            and before_single >= 30), counts


def test_the_walk_draws_nearest_first(tmp_path):
    n, order_bad, reg_bad = _verdict(_run(tmp_path, "tpd"))
    assert n == N, "%d of %d records" % (n, N)
    assert not order_bad, "%d (record, leaf) parted, first %s" % (len(order_bad), order_bad[:3])
    assert not reg_bad, "%d (record, leaf) left registers dirty, first %s" % (len(reg_bad), reg_bad[:3])


@pytest.mark.parametrize("mut", sorted(CONTROLS))
def test_control_a_broken_walk_is_caught(tmp_path, mut):
    n, order_bad, reg_bad = _verdict(_run(tmp_path, "tpd_" + mut, mut))
    assert n == N, "%s: %d of %d records -- the run broke instead of being caught" % (mut, n, N)
    if CONTROLS[mut] == "order":
        assert order_bad, "%s passed: the order comparison is vacuous" % mut
        assert not reg_bad, "%s: registers dirty too, first %s -- not the symptom it plants" % (mut, reg_bad[:3])
    else:
        assert not order_bad, "%s: the order parted, first %s -- not the symptom it plants" % (mut, order_bad[:3])
        assert reg_bad, "%s passed: the register check is vacuous" % mut
        assert all(regs[:-2] == CLEAR[:-2] and regs[-2:] != "00" for _, _, regs in reg_bad), reg_bad[:3]
