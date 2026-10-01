"""M7 P3.3 (D3 d): `sim.thing_pass_depth` on the real engine -- a leaf's runtime things handed to `thing_leaf`
NEAREST FIRST, against the oracle's rule (`render_wall_frame(rt_depth_order="aprox")`: the leaf's runtime part
sorted by P_AproxDistance from the player's integer position, stably over the list's ascending order).

The real macro runs on baked per-leaf lists (one thing, two, three, four) with every thing's position and the
player's fed per record; `thing_leaf` is a stub that prints the index `thing_load` handed it (sp_ti). The records
hold equal keys (the tie rule), negative coordinates and fractional player positions. After every leaf the sprite
registers must be clear (sp_x printed: thing_pass's own contract for the next leaf's baked xor_by).

⚠ ONE IMAGE, MANY RECORDS: a walk that leaves a register dirty corrupts the next record.
⚠ THE CONTROLS (R9): the first candidate taken instead of the least, the key without its y component, and the tie
broken toward the LATER index must each part from the oracle's order.
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
from doomfj.things import byte_array_decl, spawn_leaf_lists

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
BINDS = [0, 1, 1, 2, 2, 2, 3, 3, 3, 3]               # thing -> leaf: one, two, three and four things
NT, NLEAF = len(BINDS), 4
N = 160


def aprox(dx, dy):
    dx, dy = abs(dx), abs(dy)
    return dx + dy - (min(dx, dy) >> 1)


def _s32(v):
    return v - (1 << 32) if v >> 31 else v


def expect_order(rec):
    px16, py16, pos = rec
    out = []
    for leaf in range(NLEAF):
        ts = [t for t in range(NT) if BINDS[t] == leaf]
        out.append(sorted(ts, key=lambda t: aprox(pos[t][0] - (_s32(px16) >> 16), pos[t][1] - (_s32(py16) >> 16))))
    return out


def records():
    rnd = random.Random(0x33D)
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
        out.append((px16, py16, pos))
    return out


def _dist_leaf():
    lines = MC.p32a_leaves()
    return lines[:lines.index("mt_psec_leaf:")]


def _program(mut=None):
    head, nxt = spawn_leaf_lists(BINDS, NLEAF)
    sim = (FJ / "sim.fj").read_text(encoding="utf-8")
    muts = {"first": ("        hex.cmp 4, mt_d, td_bk, take, next, next   // equal key, later t: not better (the scan is ascending)",
                      "        ;next"),
            "nody": ("        hex.mov 4, mt_dy, sp_y + 4*dw", "        hex.mov 4, mt_dy, viewy + 4*dw"),   # dy = 0
            "tie": ("        hex.cmp 4, mt_d, td_bk, take, next, next",
                    "        hex.cmp 4, mt_d, td_bk, take, take, next")}
    if mut:
        old, new = muts[mut]
        sim_c = sim.replace("\r\n", "\n")
        assert sim_c.count(old) == 1, mut
        sim = sim_c.replace(old, new)
    body = ["stl.startup_and_init_all",
            "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy"]
    for t in range(NT):
        body += ["hex.input 4, thpos_rt + %d*dw" % (16 * t), "hex.input 4, thpos_rt + %d*dw" % (16 * t + 8)]
    for leaf in range(NLEAF):
        body += ["hex.set w/4, cur_ss, %d" % leaf, "stl.fcall tpd_leaf, tp_ret",
                 "hex.print_as_digit 8, sp_x, 0", "stl.output 59"]
    body += ["stl.output 10", ";loop", "done:", "stl.loop",
             "tpd_leaf:", "sim.thing_pass_depth throw, 1, thpos_rt, 0, 0, 0, 0", "stl.fret tp_ret",
             "thing_leaf:", "hex.print_as_digit 2, sp_ti, 0", "stl.output 44", "stl.fret thing_ret",
             *_dist_leaf(),
             "throw:", *[";0"] * (17 * 16),
             byte_array_decl("sshead", head, NLEAF + 1), byte_array_decl("thnext", nxt, NT + 1),
             "thpos_rt: hex.vec %d" % (16 * NT),
             "rmagic: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "cur_ss: hex.vec w/4",
             "tp_ret: ;0", "thing_ret: ;0", "tstop: hex.vec 1", "ss_flr: hex.vec 4", "sp_ti: hex.vec w/4",
             "sp_x: hex.vec 8", "sp_y: hex.vec 8", "sp_z: hex.vec 8", "sp_left: hex.vec 8", "sp_w: hex.vec 8",
             "sp_hh: hex.vec 8", "sp_tzmax: hex.vec 8", "sp_tzmax2: hex.vec 8", "sp_mon: hex.vec 2",
             "sp_base: hex.vec 4", "sp_base2: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",
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
    for px16, py16, pos in records():
        feed += bytes([1]) + struct.pack("<II", px16, py16)
        for x, y in pos:
            feed += struct.pack("<II", (x << 16) & M32, (y << 16) & M32)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = []
    for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:N]:
        leaves = []
        for part in line.split(";")[:NLEAF]:
            order, sx = part[:-8], part[-8:]
            leaves.append(([int(v, 16) for v in order.split(",") if v], sx))
        got.append(leaves)
    return got


def test_the_records_hold_ties_and_reorders():
    recs = records()
    ties = sum(1 for px16, py16, pos in recs for leaf in range(1, NLEAF)
               if len({aprox(pos[t][0] - (_s32(px16) >> 16), pos[t][1] - (_s32(py16) >> 16))
                       for t in range(NT) if BINDS[t] == leaf}) < BINDS.count(leaf))
    moved = sum(1 for r in recs for leaf, o in enumerate(expect_order(r)) if o != sorted(o))
    assert ties >= 20 and moved >= 100, (ties, moved)


def test_the_walk_draws_nearest_first(tmp_path):
    got = _run(tmp_path, "tpd")
    want = expect_order
    bad = []
    for k, (g, r) in enumerate(zip(got, records())):
        for leaf in range(NLEAF):
            order, sx = g[leaf]
            if order != want(r)[leaf] or sx != "00000000":
                bad.append((k, leaf, order, want(r)[leaf], sx))
    assert len(got) == N and not bad, "%d parted, first %s" % (len(bad), bad[:3])


@pytest.mark.parametrize("mut", ["first", "nody", "tie"])
def test_control_a_broken_walk_is_caught(tmp_path, mut):
    got = _run(tmp_path, "tpd_" + mut, mut)
    want = [[(o, "00000000") for o in expect_order(r)] for r in records()]
    assert got != want, "%s passed: the comparison is vacuous" % mut
