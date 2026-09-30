"""M7 P3.2b (docs/gp-monsters.md 8.4, piece 1): the MONSTERS' collision cells and `sim.try_move_mon` on the real
engine, against the model's `World.try_move_lines` -- the verdict and the new floor, for both radii (20 and 30),
with every door, both lifts and the floor switch in random states.

`collision.monster_cells_fj` is the one construction (the emitter calls it too): the player's rows with
ML_BLOCKMONSTERS folded into blocking, the lists at radius 30, and every line's low floor for the drop-off through
`sim.line_test 1, ca_lf, cp_drop`. The seed heights come from the model in the first run, and from fj in the
second (piece 2, `monstermove.monster_seed_fj`: `ptloc_walk` finds the leaf, its stub sets the heights -- a mover's
leaf by the mover's state), which must also leave the model's leaf in `ptss`.

⚠ ONE IMAGE, MANY RECORDS: a stub that leaves a cell dirty corrupts the next record.
⚠ THE CONTROLS (R9): the sample must hold refusals of every rule the model exercises on v5 (wall, monster line,
step, drop-off) and legal moves; the cells with the drop-off turned off (`sim.line_test 0, 0, 0`), the rows
without ML_BLOCKMONSTERS, and seeds that ignore the movers' states must each part from the model.

The third run adds the STATIC blockers (the barrels and the solid decorations, piece 3a) and compares against the
whole `try_move_monster` with every other monster inactive and the player far away -- each record a random skill
(which decorations stand) and random barrels gone (P5 destroys them); a cell set built without the things must
part.
"""
import random
import struct
from collections import Counter
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, generate_point_location_fj,
                              monster_cells_fj, point_location_decls)
from doomfj.monstermove import monster_seed_decls, monster_seed_fj
from doomfj.config import Config
from doomfj.doors import pass_state
from doomfj.harness import W
from doomfj.movers import lift_states, switch_sectors
from doomfj.reference_model import ML_BLOCKING, apply_sector_heights
from doomfj.world import DROPOFF_MAX, OK, STEP_UP, World

FIXP = Path("src/fj/fixed_point.fj")
SIM = Path("src/fj/sim.fj")
M32 = 0xFFFFFFFF
N = 700


class Level:
    def __init__(self):
        self.w = w = World(monsters="chase", sight_rule="seen")
        from doomfj.wall_renderer import DOOR_QUANT
        secs, lds, sds, verts = w.secs, w.lds, w.sds, w.cmap.vertexes
        self.order = list(w.door_order)
        lines = w.door_lines
        self.doors = {}
        for d, si in enumerate(self.order):
            for li in lines.get(si, ()):
                self.doors.setdefault(li, []).append((d, pass_state(secs, lds, sds, si)))
        ls = lift_states(secs, lds, sds, DOOR_QUANT)
        assert sorted(ls) == list(w.lift_order), (sorted(ls), w.lift_order)
        sw = switch_sectors(secs, lds, sds)
        msecs = {si: [apply_sector_heights(secs, {si: (h, secs[si].ceil_h)}) for h in st] for si, st in ls.items()}
        msecs.update({si: [secs, apply_sector_heights(secs, {si: (low, secs[si].ceil_h)})]
                      for si, (low, _h) in sw.items()})
        mcell = {si: "lstate + %d*dw" % k for k, si in enumerate(sorted(ls))}
        mcell.update({si: "fswitch" for si in sw})
        self.msecs, self.mcell, self.secs_open = msecs, mcell, apply_sector_heights(secs, w.open_h)
        self.nlift = len(ls)
        self.lift_n = [len(ls[si]) for si in sorted(ls)]
        self.kw = dict(secs_open=apply_sector_heights(secs, w.open_h),
                       door_line_ids={li for v in lines.values() for li in v}, doors=self.doors,
                       msecs=msecs, mcell=mcell, ml_blocking=ML_BLOCKING, ml_blockmonsters=gd.ML_BLOCKMONSTERS)

    def seed(self, movers=True):
        w = self.w
        return monster_seed_fj(w.cmap, w.lds, w.sds, self.secs_open, self.msecs if movers else {},
                               self.mcell if movers else {})

    def cells(self, **over):
        w = self.w
        kw = dict(self.kw, **over)
        return monster_cells_fj("e1m1", w.lds, w.cmap.vertexes, w.secs, w.sds, **kw)

    def static_things(self):
        """[(x, y, radius, presence cell)] -- the barrels (`bar_solid`), then the solid decorations (a flag each
        where some skill lacks it: `mc_don`); `self.var` lists the decorations that carry one"""
        w = self.w
        br = gd.THING_TYPES[2035].radius
        out = [(t.x, t.y, br, "bar_solid + %d*dw" % b) for b, t in enumerate(w.barrel_things)]
        allsk = [gd.skill_bit(sk) for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)]
        self.var = [k for k, t in enumerate(w.decor_solid) if not all(t.flags & b for b in allsk)]
        out += [(t.x, t.y, gd.THING_TYPES[t.type].radius,
                 ("mc_don + %d*dw" % self.var.index(k)) if k in self.var else None)
                for k, t in enumerate(w.decor_solid)]
        return out


@pytest.fixture(scope="module")
def level():
    return Level()


def _nib_bytes(vals, n):
    v = list(vals) + [0] * (2 * ((n + 1) // 2) - len(vals))
    return bytes(v[2 * i] | (v[2 * i + 1] << 4) for i in range(len(v) // 2))


def _assemble(tmp, lvl, text, root, name, seed=None):
    """one image over every record; `seed` (monster_seed_fj's lines): the seed from fj, the record's pair ignored"""
    nd, nl = len(lvl.order), lvl.nlift
    nb, nv = len(lvl.w.barrel_things), len(getattr(lvl, "var", []))
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        *["hex.input 4, %s" % r for r in ("cpx", "cpy", "cprad", "cp_seedf", "cp_seedc", "herf")],
        "hex.input 5, ptx", "hex.input 5, pty",
        "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
        "hex.input 1, rbyte", "hex.mov 1, fswitch, rbyte",
        "hex.input %d, bar_solid" % ((nb + 1) // 2), "hex.input %d, mc_don" % max(1, (nv + 1) // 2),
        *(["stl.fcall ptloc_walk, ptloc_ret", "stl.fcall ms_seed_leaf, ms_seed_ret"] if seed else []),
        "sim.try_move_mon %s, 56, %d, herf, %d" % (root, STEP_UP, DROPOFF_MAX),
        "hex.print_as_digit 1, mv_ok, 0", "hex.print_as_digit 8, cp_floor, 0", "hex.print_as_digit 3, ptss, 0",
        "stl.output 10",
        ";loop", "done:", "stl.loop", text,
        *((seed or []) + [generate_point_location_fj(lvl.w.cmap)]),
        *point_location_decls(), *monster_seed_decls(),
        "wmagic: hex.vec 2", "rbyte: hex.vec 2", "herf: hex.vec 8",
        "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)), "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)),
        "fswitch: hex.vec 1", "bar_solid: hex.vec %d" % (2 * ((nb + 1) // 2)),
        "mc_don: hex.vec %d" % (2 * max(1, (nv + 1) // 2)), *COLLISION_STATE_DECLS, *MON_CELL_DECLS]) + "\n"
    src = tmp / ("%s.fj" % name)
    src.write_text(prog, encoding="utf-8")
    out = tmp / ("%s.fjm" % name)
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), FIXP.resolve(), SIM.resolve(), src.resolve()], out, memory_width=W,
                print_time=False)
    return out


def _samples(lvl):
    """[(slot, nx, ny, z, door states, lift states, switch)] around the monsters' spawns and along random steps"""
    w, rng = lvl.w, random.Random(0x32B)
    n = w.layout.nmon
    bm = [li for li, ld in enumerate(w.lds) if ld.flags & gd.ML_BLOCKMONSTERS]
    assert bm, "E1M1 has no ML_BLOCKMONSTERS line: the monster-line control has nothing to find"
    movers = set(lvl.msecs)
    ml = [li for li, ld in enumerate(w.lds) if ld.back != -1
          and {w.sds[ld.front].sector, w.sds[ld.back].sector} & movers]
    out = []
    for k in range(N):
        m = k % n
        doors = [rng.choice((0, 0, w.door_nstates[si] - 1, rng.randrange(w.door_nstates[si])))
                 for si in lvl.order]
        lifts = [rng.randrange(c) for c in lvl.lift_n]
        sw = rng.randrange(2)
        r = rng.random()
        if r < 0.5:                                         # a monster-sized step from its spawn, any direction
            d = rng.randrange(8)
            dx, dy = (rng.choice((8, 10, 30, 64)) * c for c in ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0),
                                                                  (-1, -1), (0, -1), (1, -1))[d])
            nx, ny = w.ws.mon_x[m] + dx, w.ws.mon_y[m] + dy
        else:                                               # near a random line -- a monster-only one in 4
            li = rng.choice(bm) if r < 0.625 else rng.choice(ml) if r < 0.85 else rng.randrange(len(w.lds))
            (x1, y1), (x2, y2) = w.cmap.vertexes[w.lds[li].v1], w.cmap.vertexes[w.lds[li].v2]
            t = rng.random()
            nx, ny = int(x1 + t * (x2 - x1)) + rng.randint(-40, 40), int(y1 + t * (y2 - y1)) + rng.randint(-40, 40)
        z = rng.choice((w.ws.mon_floorz[m], w.ws.mon_floorz[m] - 30, w.ws.mon_floorz[m] + 20, 0, -24, 72))
        out.append((m, nx, ny, z, doors, lifts, sw))
    return out


def _model(lvl, s, things=None):
    """-> (seed, verdict, floorz, leaf); `things` = (skill, barrel bits) runs the whole try_move_monster with only the
    static blockers able to refuse (every other monster inactive, the player far away)"""
    w = lvl.w
    m, nx, ny, z, doors, lifts, sw = s
    for d, v in enumerate(doors):
        w.ws.d_state[d] = v
    for k, v in enumerate(lifts):
        w.ws.l_state[k] = v
    w.ws.f_switch = sw
    w._mh_last = None
    w._door_phase_scene()
    w.ws.mon_floorz[m] = z
    leaf = w.rm.point_in_subsector(w.cmap, nx, ny)
    seed = w.secs_c[w.leaf_sector[leaf]]
    if things is None:
        verdict, fz = w.try_move_lines(m, nx, ny)
    else:
        sk, bars = things
        for j in range(w.layout.nmon):
            w.ws.mon_active[j] = 0
        w.ws.px, w.ws.py = -30000 << 16, -30000 << 16
        w._decor_now = w._decor_for(sk)
        for b, v in enumerate(bars):
            w.ws.bar_solid[b] = v
        verdict, fz = w.try_move_monster(m, nx, ny)
    return (seed.floor_h, seed.ceil_h), verdict, fz, leaf


def _presence(lvl, k):
    """record k's (skill, barrel bits) for the static-blocker run"""
    rng = random.Random(k * 7919)
    return (rng.choice((gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)),
            [int(rng.random() < 0.8) for _ in lvl.w.barrel_things])


def _run(fjm, lvl, samples, things=False):
    feed, want, verdicts = b"", [], []
    for k, s in enumerate(samples):
        pres = _presence(lvl, k) if things else None
        (sf, sc), v, fz, leaf = _model(lvl, s, pres)
        m, nx, ny, z, doors, lifts, sw = s
        feed += bytes([0xD0]) + struct.pack("<IIIIII", (nx << 16) & M32, (ny << 16) & M32,
                                            (lvl.w.mon_radius[m] << 16) & M32, sf & M32, sc & M32, z & M32)
        feed += (nx & (16 ** 10 - 1)).to_bytes(5, "little") + (ny & (16 ** 10 - 1)).to_bytes(5, "little")
        feed += _nib_bytes(doors, len(lvl.order)) + _nib_bytes(lifts, lvl.nlift) + bytes([sw])
        nb, nv = len(lvl.w.barrel_things), len(getattr(lvl, "var", []))
        if pres:
            sk, bars = pres
            don = [int(bool(lvl.w.decor_solid[j].flags & gd.skill_bit(sk))) for j in lvl.var]
        else:
            bars, don = [0] * nb, [0] * nv
        feed += _nib_bytes(bars, nb) + _nib_bytes(don, max(2, nv) if nv else 2)
        want.append((v == OK, fz if v == OK else None, leaf))
        verdicts.append(v)
    io = FixedIO(feed + bytes([0]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    out = io.get_output(allow_incomplete_output=True).decode().split("\n")
    got = []
    for k in range(len(samples)):
        ok = out[k][0] == "1"
        f = int(out[k][1:9], 16)
        got.append((ok, (f - (1 << 32) if f >> 31 else f) if ok else None, int(out[k][9:12], 16)))
    return got, want, verdicts


@pytest.fixture(scope="module")
def run_shipped(tmp_path_factory, level):
    """the cells with the model's seeds (the leaf column is ptss, which nothing sets here: compared as 0)"""
    text, root = level.cells()
    fjm = _assemble(tmp_path_factory.mktemp("moncells"), level, text, root, "mc")
    got, want, verdicts = _run(fjm, level, _samples(level))
    return [g[:2] for g in got], [w_[:2] for w_ in want], verdicts


def test_the_seed_and_the_leaf_from_fj_follow_the_model(tmp_path, level):
    """piece 2: the same moves with the seed found in fj -- the verdict, the new floor AND the leaf"""
    text, root = level.cells()
    fjm = _assemble(tmp_path, level, text, root, "mcseed", seed=level.seed())
    got, want, verdicts = _run(fjm, level, _samples(level))
    bad = [(k, g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])
    mover_leaves = sum(1 for s in _samples(level) if level.w.leaf_sector[level.w.rm.point_in_subsector(
        level.w.cmap, s[1], s[2])] in level.msecs)
    assert mover_leaves >= 20, "only %d moves land in a mover's leaf" % mover_leaves


def _thing_samples(lvl):
    """moves beside every static blocker (and the usual sample)"""
    w, rng = lvl.w, random.Random(0x7B)
    out = list(_samples(lvl))
    stat = lvl.static_things()
    for k, (tx, ty, tr, _f) in enumerate(stat):
        for _ in range(3):
            m = rng.randrange(w.layout.nmon)
            reach = w.mon_radius[m] + tr
            nx, ny = tx + rng.randint(-reach - 3, reach + 3), ty + rng.randint(-reach - 3, reach + 3)
            out.append((m, nx, ny, w.ws.mon_floorz[m], [w.door_nstates[si] - 1 for si in lvl.order],
                        [0] * lvl.nlift, 0))
    return out


def test_the_static_blockers_follow_the_model(tmp_path, level):
    text, root = level.cells(things=level.static_things())
    fjm = _assemble(tmp_path, level, text, root, "mcthings", seed=level.seed())
    samples = _thing_samples(level)
    got, want, verdicts = _run(fjm, level, samples, things=True)
    bad = [(k, samples[k][:3], g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])
    assert Counter(verdicts)["thing"] >= 50, dict(Counter(verdicts))
    fjm2 = _assemble(tmp_path, level, *level.cells(), "mcnothings", seed=level.seed())
    got2, _w, _v = _run(fjm2, level, samples, things=True)
    assert got2 != want, "cells without the static blockers passed: the comparison is vacuous"


def test_control_seeds_that_ignore_the_movers_are_caught(tmp_path, level):
    text, root = level.cells()
    fjm = _assemble(tmp_path, level, text, root, "mcseedmut", seed=level.seed(movers=False))
    got, want, _v = _run(fjm, level, _samples(level))
    assert got != want, "seeds without the movers' states passed: the comparison is vacuous"


def test_the_monster_cells_follow_the_model(run_shipped, level):
    got, want, verdicts = run_shipped
    bad = [(k, _samples(level)[k][:4], g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])
    c = Counter(verdicts)
    for v in ("wall", "monsterline", "step", "dropoff", OK):
        assert c[v] >= 5, "the sample holds only %d '%s' verdicts: %s" % (c[v], v, dict(c))


@pytest.mark.parametrize("mut", ["no-dropoff", "no-blockmonsters"])
def test_control_a_broken_construction_is_caught(tmp_path, level, mut):
    if mut == "no-dropoff":
        text, root = level.cells()
        assert text.count("sim.line_test 1, ca_lf, cp_drop") == 1
        text = text.replace("sim.line_test 1, ca_lf, cp_drop", "sim.line_test 0, 0, 0")
    else:
        text, root = level.cells(ml_blockmonsters=0)
    fjm = _assemble(tmp_path, level, text, root, "mut")
    got, want, _v = _run(fjm, level, _samples(level))
    assert got != want, "%s passed: the comparison is vacuous" % mut
