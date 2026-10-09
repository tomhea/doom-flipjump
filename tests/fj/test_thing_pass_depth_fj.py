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

M7 P8a package C (D3 a / D3 b, docs/gp-final-plan.md 1.3) -- the 9-parameter walk `sim.thing_pass_depth ..., rk0, ex`
(the 7-parameter call above is its rk0 = ex = 0 form, the "full" game tier's):
  THE RANK (D3 a): runtime rows t >= rk0 (the effects and the drops) are drawn before the rows below it (the monsters
  and the fireballs) in their leaf, whatever the depth -- the oracle's `reference_model.rank_depth_key` (rt_rank),
  called here, stably over the list's ascending order. Two thresholds: RK0 4 (a three-thing leaf split 1 + 2, the
  four-thing leaf all rank 0) and RK0 8 (the four-thing leaf split 2 + 2, every other leaf all rank 1). #121-1: the
  rank records put a rank-0 thing EXACTLY on a rank-1 thing of its leaf (a drop on its corpse, blood on its monster:
  an aprox TIE that index order would hand to the monster).
  THE BARREL FLAG (D3 b): the stub also dirties `sp_ex` (a runtime barrel's select sets it); the walk must zero it after
  every record, so it is printed with the cleared registers and must read 0 after every leaf.
  Controls: rank_off (the rank line removed), rank_swap (the compare's arms swapped: the monsters ranked first) part
  the ORDER with every register clear; ex_round / ex_single (either sp_ex clear removed) leave sp_ex, alone, dirty.
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
from doomfj.reference_model import aprox_depth_key, rank_depth_key
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
# M7 P8a (C): the rank thresholds the 9-parameter walk runs at, and each one's #121-1 ties -- (rank-0 thing, the
# rank-1 thing of the same leaf it lands EXACTLY on)
RK0S = (4, 8)
RANK_TIES = {4: ((4, 3),), 8: ((8, 6), (9, 7))}
REGS_EX = REGS + (("sp_ex", 1),)                      # D3 b: the barrel flag, cleared per record
CLEAR_EX = "0" * sum(n for _, n in REGS_EX)


def key(rec, t, rk0=0):
    """the oracle's depth key of thing t in record rec -- with rk0, D3 a's (rank, key): rows >= rk0 rank 0"""
    px16, py16, pos, _k = rec
    if rk0:
        return rank_depth_key(px16, py16, *pos[t], 0 if t >= rk0 else 1)
    return aprox_depth_key(px16, py16, *pos[t])


def full_order(rec, rk0=0):
    """the oracle's order of each leaf's things, the leaves in WALK order (a stable sort of the ascending list)"""
    return [sorted((t for t in range(NT) if BINDS[t] == leaf), key=lambda t: key(rec, t, rk0)) for leaf in WALK]


def expect_drawn(rec, rk0=0):
    """what the walk draws in each leaf (WALK order): the oracle's orders concatenated, cut to the first k"""
    left, out = rec[3], []
    for o in full_order(rec, rk0):
        out.append(o[:max(0, left)])
        left -= len(o)
    return out


def records(rk0=0):
    rnd = random.Random(0x33D if not rk0 else 0x8A0 + rk0)
    krnd = random.Random(0x33E if not rk0 else 0x8B0 + rk0)   # the stops: their own stream, the positions unchanged
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
        if rk0 and k % 3 == 1:                        # #121-1: a drop on its corpse, blood on its monster
            for dst, src in RANK_TIES[rk0]:
                assert BINDS[dst] == BINDS[src] and dst >= rk0 > src
                pos[dst] = pos[src]
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
# M7 P8a (C): the 9-parameter walk's controls -- run at every RK0S threshold
_EXZ = "        rep(ex, k) hex.sparse_zero HOT_PAD, 1, sp_ex   // M7 P8a (D3 b): the barrel flag, consumed\n"
MUTS_D3 = {
    "rank_off": ("        rep(rk0>0, k) .rank_key                // M7 P8a (D3 a): rank 1 below rk0 -- bit 15 of the "
                 "key\n", ""),
    "rank_swap": ("        hex.cmp 2, td_t, td_rk, r1, r0, r0\n", "        hex.cmp 2, td_t, td_rk, r0, r1, r1\n"),
    "ex_round": ("        stl.fcall thing_leaf, thing_ret\n" + _EXZ + "        ;round\n",
                 "        stl.fcall thing_leaf, thing_ret\n        ;round\n"),
    "ex_single": ("        stl.fcall thing_leaf, thing_ret\n" + _EXZ + "        ;done\n",
                  "        stl.fcall thing_leaf, thing_ret\n        ;done\n"),
}
CONTROLS_D3 = {"rank_off": "order", "rank_swap": "order", "ex_round": "ex", "ex_single": "ex"}
# what each control must break: the ORDER (registers still clear), or the CLEAR of sp_lt alone (order intact)
CONTROLS = {"first": "order", "nody": "order", "tie": "order", "nostop": "order", "nostop1": "order",
            "narrow": "clear"}


def _dirty(n):
    return int(("a5" * n)[:n], 16)


def _program(mut=None, rk0=0):
    head, nxt = spawn_leaf_lists(BINDS, NLEAF)
    sim = (FJ / "sim.fj").read_text(encoding="utf-8").replace("\r\n", "\n")
    if mut:
        old, new = (MUTS_D3 if rk0 else MUTS)[mut]
        assert sim.count(old) == 1, mut
        sim = sim.replace(old, new)
    regs = REGS_EX if rk0 else REGS
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, tpd_k",
            "hex.zero 1, tstop",                       # the budget re-arms per record
            "hex.if0 2, tpd_k, tpd_stop0", ";tpd_go", "tpd_stop0:", "hex.set 1, tstop, 1", "tpd_go:"]
    for t in range(NT):
        body += ["hex.input 4, thpos_rt + %d*dw" % (16 * t), "hex.input 4, thpos_rt + %d*dw" % (16 * t + 8)]
    for leaf in WALK:
        body += ["hex.set w/4, cur_ss, %d" % leaf, "stl.fcall tpd_leaf, tp_ret", "stl.output 124",
                 *["hex.print_as_digit %d, %s, 0" % (n, r) for r, n in regs], "stl.output 59"]
    body += ["stl.output 10", ";loop", "done:", "stl.loop",
             "tpd_leaf:", "sim.thing_pass_depth throw, 1, thpos_rt, 0, 0, 0, 0" + (", %d, 1" % rk0 if rk0 else ""),
             "stl.fret tp_ret",
             # the stub: print the drawn index, dirty every register the walk clears (M7 P8a: sp_ex as a runtime
             # barrel's select leaves it, 1), count the budget down
             "thing_leaf:", "hex.print_as_digit 2, sp_ti, 0", "stl.output 44",
             *["hex.set %d, %s, %d" % (n, r, 1 if r == "sp_ex" else _dirty(n)) for r, n in regs],
             "hex.dec 2, tpd_k", "hex.if0 2, tpd_k, tpd_stopk", "stl.fret thing_ret",
             "tpd_stopk:", "hex.set 1, tstop, 1", "stl.fret thing_ret",
             *_dist_leaf(),
             "throw:", *[";0"] * (17 * 16),
             byte_array_decl("sshead", head, NLEAF + 1), byte_array_decl("thnext", nxt, NT + 1),
             "thpos_rt: hex.vec %d" % (16 * NT),
             "rmagic: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "cur_ss: hex.vec w/4", "tpd_k: hex.vec 2",
             "tp_ret: ;0", "thing_ret: ;0", "tstop: hex.vec 1", "ss_flr: hex.vec 4", "sp_ti: hex.vec w/4",
             *["%s: hex.vec %d" % (r, n) for r, n in regs],
             *MC.P33_DECLS, *(MC.D3_DECLS[:1] if rk0 else ()),        # td_rk (sp_ex is among `regs`)
             "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
             "mt_t: hex.vec 4", "mt_ret: hex.vec w/4"]
    return "\n".join(body) + "\n", sim


def _run(tmp, name, mut=None, rk0=0):
    prog, sim = _program(mut, rk0)
    p = tmp / (name + ".fj")
    p.write_text(prog, encoding="utf-8")
    s = tmp / (name + "_sim.fj")
    s.write_text(sim, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / (name + ".fjm")
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), s.resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    feed = b""
    for px16, py16, pos, stop in records(rk0):
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


def _verdict(got, rk0=0):
    """(records, the (record, leaf) whose drawn order parts from the oracle's, those whose registers are not clear)"""
    order_bad, reg_bad = [], []
    for k, (g, r) in enumerate(zip(got, records(rk0))):
        want = expect_drawn(r, rk0)
        for j, leaf in enumerate(WALK):
            order, regs = g[j] if j < len(g) else (None, None)
            if order != want[j]:
                order_bad.append((k, leaf, order, want[j], r[3]))
            if regs != (CLEAR_EX if rk0 else CLEAR):
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


# ---- M7 P8a package C (D3 a / D3 b): the 9-parameter walk ----------------------------------------------------------

@pytest.mark.parametrize("rk0", RK0S)
def test_the_rank_records_reach_every_case(rk0):
    """the rank records must CHANGE the order where it counts: (record, leaf) whose ranked order differs from the plain
    depth order (what rank_off bites on), the #121-1 exact ties across ranks (a rank-0 thing on its rank-1 thing, the
    rank-0 one drawn FIRST), and stops cutting a leaf inside its ranked order"""
    recs = records(rk0)
    moved = sum(1 for r in recs for a, b in zip(full_order(r, rk0), full_order(r)) if a != b)
    ties = [r for r in recs for dst, src in RANK_TIES[rk0] if r[2][dst] == r[2][src]]
    first = sum(1 for r in recs for dst, src in RANK_TIES[rk0] if r[2][dst] == r[2][src]
                and (lambda o: o.index(dst) < o.index(src))(sum(full_order(r, rk0), [])))
    cut = sum(1 for r in recs for o, p, d in zip(full_order(r, rk0), full_order(r), expect_drawn(r, rk0))
              if 0 < len(d) < len(o) and d != p[:len(d)])
    counts = dict(moved=moved, ties=len(ties), first=first, cut=cut)
    assert moved >= 40 and len(ties) >= 50 and first == len(ties) and cut >= 5, counts


@pytest.mark.parametrize("rk0", RK0S)
def test_the_ranked_walk_draws_effects_and_drops_first(tmp_path, rk0):
    n, order_bad, reg_bad = _verdict(_run(tmp_path, "tpd_rk%d" % rk0, rk0=rk0), rk0)
    assert n == N, "%d of %d records" % (n, N)
    assert not order_bad, "%d (record, leaf) parted, first %s" % (len(order_bad), order_bad[:3])
    assert not reg_bad, "%d (record, leaf) left registers dirty, first %s" % (len(reg_bad), reg_bad[:3])


@pytest.mark.parametrize("rk0", RK0S)
@pytest.mark.parametrize("mut", sorted(CONTROLS_D3))
def test_control_a_broken_rank_or_flag_is_caught(tmp_path, mut, rk0):
    n, order_bad, reg_bad = _verdict(_run(tmp_path, "tpd_%s_%d" % (mut, rk0), mut, rk0), rk0)
    assert n == N, "%s: %d of %d records -- the run broke instead of being caught" % (mut, n, N)
    if CONTROLS_D3[mut] == "order":
        assert order_bad, "%s passed: the rank comparison is vacuous" % mut
        assert not reg_bad, "%s: registers dirty too, first %s -- not the symptom it plants" % (mut, reg_bad[:3])
    else:
        assert not order_bad, "%s: the order parted, first %s -- not the symptom it plants" % (mut, order_bad[:3])
        assert reg_bad, "%s passed: the sp_ex check is vacuous" % mut
        assert all(regs[:-1] == CLEAR_EX[:-1] and regs[-1] != "0" for _, _, regs in reg_bad), reg_bad[:3]


def test_the_seven_parameter_form_is_the_unranked_walk():
    """the "full" game tier's call (7 parameters) expands the 9-parameter walk with both rules OFF, and every line of
    the 9-parameter body that names a P8a rule is rep()-gated on it -- so rk0 = ex = 0 is blocked51's walk, op for op
    (the emitted call is unchanged, so emit_baseline cannot see this body; this can)"""
    sim = (FJ / "sim.fj").read_text(encoding="utf-8").replace("\r\n", "\n")
    a = sim.index("    def thing_pass_depth throw, n_th, thpos, anim, sel, selret, lthi {\n")
    assert sim[a:].split("\n")[1].strip() == ".thing_pass_depth throw, n_th, thpos, anim, sel, selret, lthi, 0, 0"
    b = sim.index("    def thing_pass_depth throw, n_th, thpos, anim, sel, selret, lthi, rk0, ex \\\n")
    nine = sim[b:sim.index("\n    }\n", b)].split("\n")
    code = [ln.split("//")[0] for ln in nine[nine.index(next(ln for ln in nine if ln.endswith(" {"))) + 1:]]
    named = [ln.strip() for ln in code if "rk0" in ln or "sp_ex" in ln or "rank_key" in ln]
    assert named and all(ln.startswith(("rep(rk0>0, k)", "rep(ex, k)")) for ln in named), named
