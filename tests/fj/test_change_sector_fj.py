"""M7 P3.2b review F1: P_ChangeSector (`monstercode.p32b_change_sector_lines`) on the real flipjump engine against the
model's `World._door_phase_scene` -- the watched monsters' `mon_floorz` (every one standing in a mover's sector, an
inactive one elsewhere, two active ones elsewhere) and the movers' last state `mh_prev` after every frame.

The world: E1M1's two lifts and three floor-switch sectors, two monsters teleported into each (the second made
inactive), the rest where they spawn (some inactive by skill). The script steps `lstate` / `fswitch` frame by frame --
lift-only changes, switch-only changes, frames that change nothing -- and ends the level (`lvdone`) on some frames,
changes included: the gates' mirrors skip the whole monster frame then (p2a_gate: `if not lvdone: mph.frame`), so an
lvdone frame changes nothing and `mh_prev` keeps the last live frame's state.

R9: a change-sector that never updates `mh_prev`, one blind to the switch, one that moves inactive monsters, and one
without the lvdone guard must each part from the model.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import monstercode as MC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
TAIL = 14                                    # random frames after the scripted cases


def _point_in(w, si: int, rnd) -> tuple:
    """an integer map point whose leaf is in sector `si`"""
    vs = w.cmap.vertexes                              # the WAD's VERTEXES, as (x, y)
    pts = [vs[v] for ld in w.lds if si in (w.sds[ld.front].sector,
                                           w.sds[ld.back].sector if 0 <= ld.back < len(w.sds) else -1)
           for v in (ld.v1, ld.v2)]
    x0, x1 = min(p[0] for p in pts), max(p[0] for p in pts)
    y0, y1 = min(p[1] for p in pts), max(p[1] for p in pts)
    for _ in range(10000):
        x, y = rnd.randint(x0, x1), rnd.randint(y0, y1)
        if w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)] == si:
            return x, y
    raise AssertionError("no point found in sector %d" % si)


def _world():
    """two monsters in each mover's sector (the second inactive) -> (world, the movers' sectors, the slots watched:
    those, an inactive one elsewhere if the skill has one, and two active ones elsewhere)"""
    w = World(monsters="chase", sight_rule="seen")
    rnd = random.Random(7)
    movers = list(w.lift_order) + sorted(w.switch)
    act = [m for m in range(w.layout.nmon) if w.ws.mon_active[m]]
    assert len(act) >= 2 * len(movers) + 4
    for j, si in enumerate(movers):
        for m in act[2 * j:2 * j + 2]:
            w.teleport_monster(m, *_point_in(w, si, rnd))
            assert w._mon_sector(m) == si
        w.ws.mon_active[act[2 * j + 1]] = 0
    placed = act[:2 * len(movers)]
    rest = [m for m in range(w.layout.nmon) if m not in placed]
    watch = placed + [m for m in rest if not w.ws.mon_active[m]][:1] + [m for m in rest if w.ws.mon_active[m]][:2]
    return w, movers, sorted(watch)


def _script(w):
    """per frame: (lift states, fswitch, lvdone) -- the cases first (E1M1's two lifts), then a random tail"""
    assert len(w.lift_order) == 2 and all(len(w.lift_stops[si]) >= 6 for si in w.lift_order)
    out = [((0, 0), 0, 0),        # nothing moved
           ((3, 0), 0, 0),        # one lift
           ((3, 0), 1, 0),        # the switch alone
           ((3, 0), 1, 0),        # nothing
           ((3, 4), 1, 0),        # the other lift
           ((3, 4), 0, 1),        # the level done, the switch back: nothing may change
           ((5, 4), 0, 1),        # ...and a lift: nothing
           ((5, 4), 0, 0),        # live again: both catch up at once
           ((5, 4), 1, 0),        # the switch alone
           ((0, 0), 1, 0),        # both lifts back to their stored floors
           ((0, 0), 0, 0)]        # the switch alone, back
    rnd = random.Random(11)
    nst = [len(w.lift_stops[si]) for si in w.lift_order]
    ls, sw = list(out[-1][0]), out[-1][1]
    for f in range(TAIL):
        kind = rnd.choice(("lift", "lift", "switch", "none"))
        if kind == "lift":
            k = rnd.randrange(len(nst))
            ls[k] = rnd.randrange(nst[k])
        elif kind == "switch":
            sw ^= 1
        out.append((tuple(ls), sw, int(rnd.random() < 0.25)))
    return out


def _expected(script) -> bytes:
    w, _, watch = _world()
    ws, nl = w.ws, len(w.lift_order)
    prev = (0,) * nl + (0,)
    lines = []
    for ls, sw, done in script:
        if not done:                                  # the gates' mirrors: no monster frame on an lvdone frame
            for k in range(nl):
                ws.l_state[k] = ls[k]
            ws.f_switch = sw
            w._door_phase_scene()
            prev = tuple(ls) + (sw,)
        lines.append("".join("%04x" % (ws.mon_floorz[m] & 0xFFFF) for m in watch)
                     + "".join("%x" % v for v in prev))
    return ("\n".join(lines) + "\n").encode()


def _parts(w, mut=None):
    n, schema, ws, nl = w.layout.nmon, w.schema, w.ws, len(w.lift_order)
    lines = MC.p32b_change_sector_lines(w, n, exit_guard=mut != "nolvdone")
    text = "\n".join(lines) + "\n"
    if mut == "nomh":
        for old in ("    hex.mov %d, mh_prev, lstate\n" % nl, "    hex.mov 1, mh_prev + %d*dw, fswitch\n" % nl):
            assert text.count(old) == 1, old
            text = text.replace(old, "")
    elif mut == "noswitch":
        old = "    hex.cmp 1, mh_prev + %d*dw, fswitch, mcs_chg, mcs_skip, mcs_chg\n" % nl
        assert text.count(old) == 1
        text = text.replace(old, "    ;mcs_skip\n")
    elif mut == "noactive":
        text, k = re.subn(r"    hex\.if0 1, mon_active \+ \d+\*dw, mcs_m\d+\n", "", text)
        assert k == n, k
    decls = (MC.monster_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS})
             + MC.p32b_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in MC.P32B_FIELDS},
                             [w._mon_sector(m) for m in range(n)])
             + ["lstate: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1", "lvdone: hex.vec 1",
                "mh_prev: hex.vec %d" % (nl + 1), "mcf_val: hex.vec 4", "mcf_hit: hex.vec 1",
                "mcf_ret: hex.vec w/4", "cs_ret: hex.vec w/4"])
    return decls, ["cs_leaf:", text, "    stl.fret cs_ret"]


def _run(tmp_path, name, mut=None) -> bool:
    w, _, watch = _world()
    nl = len(w.lift_order)
    script = _script(w)
    body = ["stl.startup_and_init_all"]
    for ls, sw, done in script:
        body += ["hex.set %d, lstate, %d" % (nl, sum(v << (4 * k) for k, v in enumerate(ls))),
                 "hex.set 1, fswitch, %d" % sw, "hex.set 1, lvdone, %d" % done,
                 "stl.fcall cs_leaf, cs_ret"]
        body += ["hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m) for m in watch]
        body += ["hex.print_as_digit 1, mh_prev + %d*dw, 0" % k for k in range(nl + 1)]
        body += ["stl.output 10"]
    body.append("stl.loop")
    decls, code = _parts(w, mut)
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + decls + code) + "\n", encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(script), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_script_exercises_every_path():
    """the model's own view of the script: floors change through a lift and through the switch ALONE, an inactive
    monster in a mover's sector would have moved, an lvdone frame carries a change, and some frames change nothing"""
    w, movers, watch = _world()
    ws, n, nl = w.ws, w.layout.nmon, len(w.lift_order)
    script = _script(w)
    lift_moves = switch_moves = switch_alone = lv_changes = idle = 0
    inactive_in_mover = [m for m in range(n) if not ws.mon_active[m] and w._mon_sector(m) in movers]
    assert len(inactive_in_mover) >= len(movers), inactive_in_mover
    prev = ((0,) * nl, 0)
    for ls, sw, done in script:
        changed = (tuple(ls), sw) != prev
        if done:
            lv_changes += changed
            continue
        before = list(ws.mon_floorz[:n])
        for k in range(nl):
            ws.l_state[k] = ls[k]
        ws.f_switch = sw
        w._door_phase_scene()
        moved = {w._mon_sector(m) for m in range(n) if ws.mon_floorz[m] != before[m]}
        lift_moves += bool(moved & set(w.lift_order))
        switch_moves += bool(moved & set(w.switch))
        idle += not changed
        switch_alone += changed and tuple(ls) == prev[0]
        prev = (tuple(ls), sw)
    assert set(inactive_in_mover) <= set(watch)
    assert lift_moves >= 3 and switch_moves >= 2 and switch_alone >= 2 and lv_changes >= 2 and idle >= 2, (
        lift_moves, switch_moves, switch_alone, lv_changes, idle)


def test_change_sector_follows_the_model(tmp_path):
    assert _run(tmp_path, "mcs"), "the fj P_ChangeSector parted from the model's"


@pytest.mark.parametrize("mut", ["nomh", "noswitch", "noactive", "nolvdone"])
def test_control_a_broken_change_sector_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mcs_" + mut, mut), "%s passed: the comparison is vacuous" % mut
