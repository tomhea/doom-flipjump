"""M8 F1.3: P_ChangeSector (`monstercode.p32b_change_sector_lines`) on E1M2's movers, on the real flipjump engine
against the model's `World._door_phase_scene` -- tests/fj/test_change_sector_fj.py's harness on E1M2: five lifts and
ELEVEN floor groups (`mh_prev` now holds the lifts' states and every group's state, `monstercode.mh_width`; the floors
from `movers.mover_table`), a monster in each of a group's sectors and on each lift (every other one inactive), sector
ids three nibbles wide. The script steps the lifts and the groups frame by frame -- a group alone, a lift alone,
nothing -- and ends the level on some frames (an lvdone frame changes nothing).

R9: a compare that reads only the FIRST floor group's state (E1M1's one-nibble width), and one that never updates
`mh_prev`, must each part from the model.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import movers as MV
from doomfj.config import Config
from doomfj.harness import W
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FRAMES = 40


def _point_in(w, si: int, rnd) -> tuple:
    vs = w.cmap.vertexes
    pts = [vs[v] for ld in w.lds if si in (w.sds[ld.front].sector,
                                           w.sds[ld.back].sector if 0 <= ld.back < len(w.sds) else -1)
           for v in (ld.v1, ld.v2)]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    for _ in range(20000):
        x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        if w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)] == si:
            return x, y
    raise AssertionError("no point found in sector %d" % si)


def _world():
    w = World(WadFile.from_path(FIX), "E1M2", skill=gd.SK_HARD, monsters="chase", sight_rule="seen")
    rnd = random.Random(7)
    movers = sorted(w.mover_table)
    act = [m for m in range(w.layout.nmon) if w.ws.mon_active[m]]
    assert len(act) >= len(movers) + 4
    for j, si in enumerate(movers):
        m = act[j]
        w.teleport_monster(m, *_point_in(w, si, rnd))
        assert w._mon_sector(m) == si
        if j % 3 == 2:
            w.ws.mon_active[m] = 0
    watch = act[:len(movers)] + act[len(movers):len(movers) + 2]
    return w, sorted(watch)


def _script(w):
    """per frame: (lift states, group states, lvdone)"""
    rnd = random.Random(13)
    nl, ng = len(w.lift_order), len(w.floor_groups)
    ls, gs = [0] * nl, [0] * ng
    out = []
    for f in range(FRAMES):
        kind = rnd.choice(("lift", "group", "group", "none"))
        if kind == "lift":
            k = rnd.randrange(nl)
            ls[k] = rnd.randrange(len(w.lift_stops[w.lift_order[k]]))
        elif kind == "group":
            g = rnd.randrange(1, ng) if f % 2 else rnd.randrange(ng)
            gs[g] = rnd.randrange(w.floor_groups[g].n)
        out.append((tuple(ls), tuple(gs), int(rnd.random() < 0.2)))
    return out


def _expected(script) -> bytes:
    w, watch = _world()
    ws, nl, ng = w.ws, len(w.lift_order), len(w.floor_groups)
    prev = (0,) * (nl + ng)
    lines = []
    for ls, gs, done in script:
        if not done:
            for k in range(nl):
                ws.l_state[k] = ls[k]
            for g in range(ng):
                ws.f_switch[g] = gs[g]
            w._door_phase_scene()
            prev = tuple(ls) + tuple(gs)
        lines.append("".join("%04x" % (ws.mon_floorz[m] & 0xFFFF) for m in watch)
                     + "".join("%x" % v for v in prev))
    return ("\n".join(lines) + "\n").encode()


def _parts(w, mut=None):
    n, schema, ws, nl = w.layout.nmon, w.schema, w.ws, len(w.lift_order)
    nf = MC.mh_width(w) - nl
    text = "\n".join(MC.p32b_change_sector_lines(w, n, exit_guard=True)) + "\n"
    if mut == "one_group":
        old = "    hex.cmp %d, mh_prev + %d*dw, fswitch, mcs_chg, mcs_skip, mcs_chg\n" % (nf, nl)
        assert text.count(old) == 1
        text = text.replace(old, old.replace("hex.cmp %d," % nf, "hex.cmp 1,"))
    elif mut == "nomh":
        for old in ("    hex.mov %d, mh_prev, lstate\n" % nl, "    hex.mov %d, mh_prev + %d*dw, fswitch\n" % (nf, nl)):
            assert text.count(old) == 1, old
            text = text.replace(old, "")
    decls = (MC.monster_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS})
             + MC.p32b_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in MC.P32B_FIELDS},
                             [w._mon_sector(m) for m in range(n)], w.sec_nibbles)
             + ["lstate: hex.vec %d" % nl, "fswitch: hex.vec %d" % MV.fswitch_nibbles(w.floor_groups),
                "lvdone: hex.vec 1", "mh_prev: hex.vec %d" % MC.mh_width(w), "mcf_val: hex.vec 4",
                "mcf_hit: hex.vec 1", "mcf_ret: hex.vec w/4", "cs_ret: hex.vec w/4"])
    return decls, ["cs_leaf:", text, "    stl.fret cs_ret"]


def _run(tmp_path, name, mut=None) -> bool:
    w, watch = _world()
    nl, ng = len(w.lift_order), len(w.floor_groups)
    script = _script(w)
    body = ["stl.startup_and_init_all"]
    for ls, gs, done in script:
        body += ["hex.set %d, lstate, %d" % (nl, sum(v << (4 * k) for k, v in enumerate(ls))),
                 "hex.set %d, fswitch, %d" % (ng, sum(v << (4 * g) for g, v in enumerate(gs))),
                 "hex.set 1, lvdone, %d" % done, "stl.fcall cs_leaf, cs_ret"]
        body += ["hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m) for m in watch]
        body += ["hex.print_as_digit 1, mh_prev + %d*dw, 0" % k for k in range(nl + ng)]
        body += ["stl.output 10"]
    body.append("stl.loop")
    decls, code = _parts(w, mut)
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + decls + code) + "\n", encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(script), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_script_moves_floors_under_monsters():
    w, watch = _world()
    exp = _expected(_script(w)).decode().split("\n")
    floors = {ln[:4 * len(watch)] for ln in exp if ln}
    assert len(floors) >= FRAMES // 3, "the watched monsters' floors change often"
    assert MC.mh_width(w) == len(w.lift_order) + len(w.floor_groups) == 16


def test_change_sector_is_the_model_on_e1m2(tmp_path):
    assert _run(tmp_path, "cs2"), "P_ChangeSector parted from the model on E1M2's movers"


@pytest.mark.parametrize("mut", ["one_group", "nomh"])
def test_control_broken_change_sector_parts(tmp_path, mut):
    assert not _run(tmp_path, "cs2_" + mut, mut), "%s passed: the comparison is vacuous" % mut
