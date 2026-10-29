"""M8 F1.3 10b (docs/f1-big-map-widths.md 10): E1M2's ONE line between two state cells -- linedef 1199, blazing lift 47
(`lstate`) beside S1 floor 206 (its group's `fswitch` cell) -- in the MONSTERS' collision cells on the real engine:
its opening floor reads 206's cell and its low floor (the drop-off) 47's, through `collision_cells_fj`'s split dispatch
(three `hex.switch`s: the opening floor in, the low floor in around the shared test, the opening floor out), against
the model's `World.try_move_lines` at every pair of the two movers' states.

The cells are `monster_cells_fj`'s construction (`line_rows` with ML_BLOCKMONSTERS, `mover_line_states` max / min,
`line_lowfloors`) with the LISTS kept to the cells around the line -- every record's box lies inside them, so the kept
lists are exact for it -- which keeps the image small (E1M2's whole cell routine is ~4.4M characters).

R9 (MUTANTS), each must part: the low floor read through 206's cell (one cell for both, the pre-F1.3 shape), the
opening floor read through the lift's, the split's undo dispatch dropped (a dirty ca_ob for the next record).
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import movers as MV
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, MONSTER_CELL_RADIUS, cell_lists,
                              collision_cells_fj, line_lowfloors, line_rows, mover_line_states)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.monstermove import world_cell_inputs
from doomfj.reference_model import ML_BLOCKING
from doomfj.wad import WadFile
from doomfj.world import DROPOFF_MAX, OK, STEP_UP, World

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
LINE = 1199
KEEP = 200               # map units round the line's middle: the kept cells
REACH = 90               # the records' centres round it (+ a 30-unit box + a 32-unit cell < KEEP)
N = 360


class Level:
    def __init__(self):
        self.w = w = World(WadFile.from_path(FIX), "E1M2", skill=gd.SK_HARD, monsters="chase", sight_rule="seen")
        ld = w.lds[LINE]
        self.a, self.b = w.sds[ld.front].sector, w.sds[ld.back].sector
        (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        self.mid = ((x1 + x2) // 2, (y1 + y2) // 2)
        self.k47 = w.lift_order.index(47)
        self.g206 = next(g for g, grp in enumerate(w.floor_groups) if 206 in grp.sectors)
        self.kw = world_cell_inputs(w, 16)
        self.m = next(m for m in range(w.layout.nmon) if w.mon_radius[m] == 20 and w.mon_height[m] == 56)

    def movers(self, mut=None):
        w, kw = self.w, self.kw
        obs = mover_line_states(w.lds, w.sds, kw["msecs"], kw["mcell"], max)
        lfs = mover_line_states(w.lds, w.sds, kw["msecs"], kw["mcell"], min)
        out = {li: (obs[li][0], obs[li][1], lfs[li][1]) + ((lfs[li][0],) if lfs[li][0] != obs[li][0] else ())
               for li in obs}
        assert len(out[LINE]) == 4, out[LINE]
        cell, ob, lf, lfcell = out[LINE]
        if mut == "lf_on_ob_cell":            # the low floor read through 206's cell: one cell for both
            out[LINE] = (cell, ob, [lf[min(k, len(lf) - 1)] for k in range(len(ob))])
        elif mut == "ob_on_lift":             # the opening floor read through the lift's cell
            out[LINE] = (lfcell, [ob[min(k, len(ob) - 1)] for k in range(len(lf))], lf)
        return out

    def cells(self, mut=None):
        w, kw = self.w, self.kw
        rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING | gd.ML_BLOCKMONSTERS,
                         secs_open=kw["secs_open"], door_line_ids=kw["door_line_ids"])
        mx, my = self.mid
        lists = {c: v for c, v in cell_lists(rows, MONSTER_CELL_RADIUS).items()
                 if abs(c[0] * 32 + 16 - mx) < KEEP and abs(c[1] * 32 + 16 - my) < KEEP}
        assert any(LINE in v for v in lists.values())
        text, root = collision_cells_fj("e1m2", rows, lists, doors=kw["doors"], movers=self.movers(mut), tag="mc",
                                        lowfloor=line_lowfloors(w.lds, w.sds, w.secs))
        if mut == "no_undo":
            import re
            text, n = re.subn(r"(  e1m2_mc_l%d_mc:\n)    hex\.switch [^\n]*\n" % LINE, r"\1    ;e1m2_mc_l%d_mout\n" % LINE,
                              text)
            assert n == 1
        return text, root


@pytest.fixture(scope="module")
def level():
    return Level()


def _samples(lvl):
    w, rng = lvl.w, random.Random(0x1199)
    n47, n206 = len(w.lift_stops[47]), w.floor_groups[lvl.g206].n
    out = []
    for k in range(N):
        i, j = k % n47, (k // n47) % n206
        if rng.random() < 0.6:            # the box ON the line (horizontal, y = mid): both cells read
            nx, ny = lvl.mid[0] + rng.randint(-40, 40), lvl.mid[1] + rng.randint(-19, 19)
        else:
            nx, ny = lvl.mid[0] + rng.randint(-REACH, REACH), lvl.mid[1] + rng.randint(-REACH, REACH)
        z = rng.choice((w.lift_stops[47][i], w.lift_stops[47][i], w.floor_groups[lvl.g206].floor(206, j),
                        w.floor_groups[lvl.g206].floor(206, j), 240, 304, rng.randint(200, 400)))
        out.append((nx, ny, z, i, j))
    return out


def _model(lvl, s):
    w = lvl.w
    nx, ny, z, i, j = s
    w.ws.l_state[lvl.k47], w.ws.f_switch[lvl.g206] = i, j
    w._mh_last = None
    w._door_phase_scene()
    w.ws.mon_floorz[lvl.m] = z
    leaf = w.rm.point_in_subsector(w.cmap, nx, ny)
    seed = w.secs_c[w.leaf_sector[leaf]]
    v, fz = w.try_move_lines(lvl.m, nx, ny)
    return (seed.floor_h, seed.ceil_h), (v == OK, fz if v == OK else None)


def _run(tmp, lvl, name, mut=None):
    w = lvl.w
    text, root = lvl.cells(mut)
    nd, nl, nfs = len(w.door_order), len(w.lift_order), MV.fswitch_nibbles(w.floor_groups)
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        *["hex.input 4, %s" % r for r in ("cpx", "cpy", "cprad", "cp_seedf", "cp_seedc", "herf")],
        "hex.input 1, rbyte", "hex.mov 1, lstate + %d*dw, rbyte" % lvl.k47,
        "hex.input 1, rbyte", "hex.mov 1, %s, rbyte" % MV.switch_cell(lvl.g206),
        "sim.try_move_mon %s, 56, %d, herf, %d" % (root, STEP_UP, DROPOFF_MAX),
        "hex.print_as_digit 1, mv_ok, 0", "hex.print_as_digit 8, cp_floor, 0", "stl.output 10",
        ";loop", "done:", "stl.loop", text,
        "wmagic: hex.vec 2", "rbyte: hex.vec 2", "herf: hex.vec 8",
        "dstate: hex.vec %d, %d" % (nd, sum((w.door_nstates[si] - 1) << (4 * d) for d, si in enumerate(w.door_order))),
        "lstate: hex.vec %d" % nl, "fswitch: hex.vec %d" % nfs, *COLLISION_STATE_DECLS, *MON_CELL_DECLS]) + "\n"
    src = tmp / ("%s.fj" % name)
    src.write_text(prog, encoding="utf-8")
    out = tmp / ("%s.fjm" % name)
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    # every door fully open in the model too (the fj's dstate)
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = w.door_nstates[si] - 1
    feed, want = b"", []
    for s in _samples(lvl):
        (sf, sc), res = _model(lvl, s)
        nx, ny, z, i, j = s
        feed += bytes([0xD0]) + struct.pack("<IIIIII", (nx << 16) & M32, (ny << 16) & M32, (20 << 16) & M32,
                                            sf & M32, sc & M32, z & M32) + bytes([i, j])
        want.append(res)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    lines = io.get_output(allow_incomplete_output=True).decode().split("\n")
    got = []
    for k in range(len(want)):
        ok = lines[k][0] == "1"
        f = int(lines[k][1:9], 16)
        got.append((ok, (f - (1 << 32) if f >> 31 else f) if ok else None))
    return got, want


def test_the_samples_cross_the_line_in_every_pair(level):
    w = level.w
    s = _samples(level)
    pairs = {(x[3], x[4]) for x in s}
    assert len(pairs) == len(w.lift_stops[47]) * w.floor_groups[level.g206].n
    res = [_model(level, x)[1] for x in s]
    assert 0.1 < sum(r[0] for r in res) / len(res) < 0.9, "refusals and accepts"
    ld = w.lds[LINE]
    (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
    assert y1 == y2, "line 1199 is horizontal (the samples straddle it so)"
    on = [x for x in s if abs(x[1] - y1) < 20 and min(x1, x2) - 20 < x[0] < max(x1, x2) + 20]
    assert len(on) > N // 3
    on_res = [_model(level, x)[1][0] for x in on]
    assert any(on_res) and not all(on_res), "accepts and refusals ON the line"


def test_the_split_dispatch_is_the_model(tmp_path, level):
    got, want = _run(tmp_path, level, "split")
    bad = [(k, g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])


@pytest.mark.parametrize("mut", ["lf_on_ob_cell", "ob_on_lift", "no_undo"])
def test_control_a_broken_split_parts(tmp_path, level, mut):
    got, want = _run(tmp_path, level, "split_" + mut, mut)
    assert got != want, "%s passed: the comparison is vacuous" % mut
