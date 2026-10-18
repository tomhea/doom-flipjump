"""M8 C4 -- the EPISODE'S MOVERS in the model (docs/episode-plan.md 2, C4), on the maps that have them
(`assets/freedoom1.wad`): 36 W1 turbo lower (E1M4, E1M7), 20 S1 / 22 W1 raise to the next higher floor + texture (E1M3,
E1M6), 7 S1 stairs (E1M3), 53 W1 perpetual lift (E1M7), 138 SR light 255 (E1M3); the lines between a door and a mover,
two movers on two cells, a lift line that shuts a fireball, the renderer's seg gate and NEW GAME with floor groups and
no lift.

Each is checked against DOOM's own rule written out here (p_floor.c / p_plats.c / p_lights.c), not against the
module's code; each family carries an R9 control that a mutation of the rule must fail.
"""
import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest

from doomfj import gamedata as gd
from doomfj import movers as MV

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")


@pytest.fixture(scope="module")
def wad():
    from doomfj.wad import WadFile
    return WadFile.from_path(ART)


def _map(wad, m):
    return wad.sectors(m), wad.linedefs(m), wad.sidedefs(m), wad.vertexes(m)


def _group(groups, tag):
    return next(g for g in groups if g.tag == tag)


def _world(wad, m, monkeypatch):
    """the map's World, the thing types gamedata lacks left out (the survey's construction: C6 / C7 / C8 add them)"""
    unknown = {t.type for t in wad.things(m)} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    monkeypatch.setattr(gd, "NOT_THINGS", frozenset(gd.NOT_THINGS | unknown))
    from doomfj.world import World
    return World(wad, m, strict=True)


def _events():
    from doomfj.world import TicEvents
    return TicEvents(0)


# ---- 36 W1 turbo lower -----------------------------------------------------------------------------------------
def test_36_turbo_lower_e1m4(wad):
    secs, lds, sds, verts = _map(wad, "E1M4")
    g = _group(MV.floor_groups(secs, lds, sds), 4)
    assert g.special == 36 and not g.use and g.sub == MV.FLOOR_TURBO_SUB == 1
    # turboLower: the highest surrounding floor, + 8 when it differs from the sector's own
    want = {}
    for si in (43, 265):
        h = max(secs[n].floor_h for n in MV.two_sided_neighbours(lds, sds)[si])
        want[si] = h + 8 if h != secs[si].floor_h else h
    assert want == {43: -40, 265: -48}
    assert {si: hts[-1] for si, hts in g.heights} == want
    # its four W1 lines (1884..1887) each fire it
    mp = MV.MoverPhase(secs, lds, sds, verts)
    gi = mp.groups.index(g)
    assert [k for k, _s in mp.floor_walk].count(gi) == 4


def test_control_36_without_its_plus_8(wad, monkeypatch):
    secs, lds, sds, _v = _map(wad, "E1M4")
    real = MV.floor_destination
    monkeypatch.setattr(MV, "floor_destination", lambda s, l, d, si, rule: (
        MV.highest_surrounding(s, l, d, si) if rule == "turbo" else real(s, l, d, si, rule)))
    g = _group(MV.floor_groups(secs, lds, sds), 4)
    assert {si: hts[-1] for si, hts in g.heights} != {43: -40, 265: -48}


# ---- 20 / 22: raise to the next higher floor, change the flat, clear the special --------------------------------
def test_20_next_higher_and_change_e1m3(wad):
    secs, lds, sds, _v = _map(wad, "E1M3")
    g = _group(MV.floor_groups(secs, lds, sds), 16)
    assert g.special == 20 and g.use and g.sub == 8 and g.sectors == (146,)
    # P_FindNextHighestFloor: the least neighbour floor above its own (-104 -> 0); PLATSPEED/2 on the 16 grid
    nb = [secs[n].floor_h for n in MV.two_sided_neighbours(lds, sds)[146]]
    assert min(h for h in nb if h > secs[146].floor_h) == 0
    assert g.heights[0][1] == (-104, -96, -80, -64, -48, -32, -16, 0)
    # the flat: the FIRING line's front sector's (933's front, 195: FLOOR5_2); the sector's special 5 (nukage)
    assert g.change == ((146, secs[sds[lds[933].front].sector].floor_tex),) == ((146, "FLOOR5_2"),)
    assert secs[146].special == 5 and secs[146].floor_tex == "NUKAGE1"


def test_change_flats_read_off_the_height(wad):
    secs, lds, sds, _v = _map(wad, "E1M3")
    groups = MV.floor_groups(secs, lds, sds)
    tbl = MV.change_table(groups)
    assert MV.apply_change_flats(secs, tbl) is secs                          # stored: nothing to do, no copy
    from doomfj.reference_model import apply_sector_heights, build_scene, scene_sectors
    moved = apply_sector_heights(secs, {146: (-96, secs[146].ceil_h)})
    out = MV.apply_change_flats(moved, tbl)
    assert out[146].floor_tex == "FLOOR5_2" and moved[146].floor_tex == "NUKAGE1"
    assert all(out[i] is moved[i] for i in range(len(secs)) if i != 146)
    # the per-state lists the emitter bakes (mover_secs) carry it from the first stop on, as the oracle's scene_sectors
    msecs = MV.mover_secs(MV.mover_table(secs, lds, sds), secs, tbl)
    assert [sv[146].floor_tex for sv in msecs[146]] == ["NUKAGE1"] + ["FLOOR5_2"] * 7
    sc = build_scene(wad, wad, "E1M3", {146: (-80, secs[146].ceil_h)})
    assert scene_sectors(sc)[146].floor_tex == "FLOOR5_2"
    assert scene_sectors(build_scene(wad, wad, "E1M3"))[146].floor_tex == "NUKAGE1"
    # E1M1 / E1M2: no table, their lists untouched
    assert MV.map_change_table(wad, "E1M1") == {} == MV.map_change_table(wad, "E1M2")


def test_e1m6_one_tag_two_triggers(wad):
    """E1M6's tag 1: a 22 W1 line (295) and a 20 S1 line (1530) -- one group; either fires it"""
    secs, lds, sds, verts = _map(wad, "E1M6")
    mp = MV.MoverPhase(secs, lds, sds, verts)
    g = next(k for k, grp in enumerate(mp.groups) if grp.tag == 1)
    assert mp.groups[g].change == ((142, "FLAT5_4"),) and mp.groups[g].heights[0][1][-1] == 0
    assert [k for k, _s in mp.floor_walk].count(g) == 1 and [k for k, _b in mp.floor_use].count(g) == 1


def test_control_change_lines_disagreeing_on_the_flat_refused(wad):
    secs, lds, sds, _v = _map(wad, "E1M6")
    secs = list(secs)
    s = sds[lds[1530].front].sector
    secs[s] = dataclasses.replace(secs[s], floor_tex="FLAT20")
    with pytest.raises(AssertionError, match="texture-change lines give the flats"):
        MV.floor_groups(secs, lds, sds)


def test_20_clears_the_nukage_at_the_trigger(wad, monkeypatch):
    """EV_DoPlat: `sec->special = 0` at the trigger -- the model's damage stops when the group FIRES (its timer set),
    before its floor moves"""
    w = _world(wad, "E1M3", monkeypatch)
    g = next(k for k, grp in enumerate(w.floor_groups) if grp.tag == 16)
    ss = w.cmap.subsectors[w.leaf_sector.index(146)]
    pts = [w.cmap.vertexes[w.lds[w.cmap.segs[ss.firstseg + i].linedef].v1] for i in range(ss.numsegs)]
    x, y = sum(p[0] for p in pts) // len(pts), sum(p[1] for p in pts) // len(pts)

    def hurt():
        ws = w.ws
        ws.px, ws.py, ws.leveltime, ws.p_health = x << 16, y << 16, 0, 100
        assert w.player_sector() == 146
        w._special_sector(_events())
        return 100 - ws.p_health
    assert not w.floor_special_cleared(146) and hurt() == 10                 # special 5: 10 a hit
    w.floor_fire(g)
    assert w.floor_state(g) == 0 and w.floor_sub(g) == 8                     # fired: moving, still at its floor
    assert w.floor_special_cleared(146) and hurt() == 0
    assert not w.floor_special_cleared(2)                                    # another nukage sector keeps it


# ---- 7 S1 stairs ---------------------------------------------------------------------------------------------------
def _doom_stairs(secs, lds, sds, tag, size=8):
    """EV_BuildStairs written out once more, from p_floor.c (its two loops, the tag search resumed after the last step,
    `height += stairsize` before the busy test)"""
    sec_lines = {}
    for i, ld in enumerate(lds):
        f = sds[ld.front].sector
        sec_lines.setdefault(f, []).append(i)
        if ld.back >= 0 and sds[ld.back].sector != f:
            sec_lines.setdefault(sds[ld.back].sector, []).append(i)
    busy, secnum = {}, -1
    while True:
        secnum = next((i for i in range(secnum + 1, len(secs)) if secs[i].tag == tag), -1)
        if secnum < 0:
            return busy
        if secnum in busy:
            continue
        sec = secnum
        height = secs[sec].floor_h + size
        busy[sec] = height
        texture = secs[sec].floor_tex
        ok = 1
        while ok:
            ok = 0
            for li in sec_lines[sec]:
                ld = lds[li]
                if not ld.flags & 4 or sds[ld.front].sector != sec:
                    continue
                t = sds[ld.back].sector
                if secs[t].floor_tex != texture:
                    continue
                height += size
                if t in busy:
                    continue
                sec = secnum = t
                busy[sec] = height
                ok = 1
                break


def test_7_stairs_e1m3(wad):
    secs, lds, sds, _v = _map(wad, "E1M3")
    want = _doom_stairs(secs, lds, sds, 18)
    assert want == {208: 104, 207: 112, 206: 120, 205: 128, 204: 136}
    assert MV.stair_destinations(secs, lds, sds, 18) == want
    g = _group(MV.floor_groups(secs, lds, sds), 18)
    assert g.special == 7 and g.use and g.sub == MV.STAIR_SUB == 8 and g.sectors == (204, 205, 206, 207, 208)
    hts = dict(g.heights)
    assert hts[204] == (96, 104, 112, 120, 128, 136) and hts[208] == (96, 104, 104, 104, 104, 104)   # 8-unit stops


def test_control_stairs_without_the_texture_rule(wad):
    """R9: a stair chain that ignored the floor flat would climb on past the stairs"""
    secs, lds, sds, _v = _map(wad, "E1M3")
    secs2 = [dataclasses.replace(s, floor_tex="FLOOR5_3") for s in secs]
    assert MV.stair_destinations(secs2, lds, sds, 18) != MV.stair_destinations(secs, lds, sds, 18)


# ---- 53 W1 perpetual lift ------------------------------------------------------------------------------------------
def _doom_perpetual(n, frames, trig_at):
    """T_PlatRaise's perpetualRaise in frames, stepped by hand: (state) per frame -- down first; a stop every PERP_SUB
    frames; LIFT_WAIT frames at each end; never stops"""
    out, state, mode, sub, wait, started = [], 0, "idle", 0, 0, False
    for f in range(frames):
        if f in trig_at and not started:
            started, mode, sub = True, "down", MV.PERP_SUB
        if mode in ("down", "up"):
            sub -= 1
            if not sub:
                state += 1 if mode == "down" else -1
                sub = MV.PERP_SUB
                if state in (0, n - 1):
                    mode, sub, wait = "wait", 0, MV.LIFT_WAIT
        elif mode == "wait":
            wait -= 1
            if not wait:
                mode, sub = ("up" if state else "down"), MV.PERP_SUB
        out.append(state)
    return out


def test_53_perpetual_lift(wad):
    secs, lds, sds, verts = _map(wad, "E1M7")
    st = MV.lift_states(secs, lds, sds)
    assert st[563] == [216, 208, 192, 176, 160, 144, 136] and MV.lift_perpetual(secs, lds, 563)
    assert not any(MV.lift_perpetual(secs, lds, si) for si in st if si != 563)
    assert any(t[0] == 563 for t in MV.lift_walk_triggers(secs, lds, sds, verts))           # its W1 line
    assert not any(t[0] == 563 for t in MV.lift_walk_triggers(secs, lds, sds, verts, MV.LIFT_MONSTER_SPECIALS))
    n = len(st[563])
    for trig in ((5,), (0, 30, 90), (3, 4, 200)):
        s, got = (0, 0, 0, 0), []
        for f in range(400):
            s = MV.perpetual_tic(s, n, f in trig)
            got.append(s[0])
        assert got == _doom_perpetual(n, 400, trig), trig
    assert max(got) == n - 1 and got[-150:].count(0) < 150                  # it keeps going
    mp = MV.MoverPhase(secs, lds, sds, verts)
    assert mp.perpetual[563] and sum(mp.perpetual.values()) == 1


def test_control_perpetual_retriggered():
    """R9: a perpetual lift that a later trigger restarted would leave DOOM's cycle"""
    n = 7

    def bad(st, nst, trig):
        if trig and st[1] == 0:
            return MV.perpetual_tic((st[0], 0, 0, 0), nst, True)
        return MV.perpetual_tic(st, nst, trig)
    s, got = (0, 0, 0, 0), []
    for f in range(400):
        s = bad(s, n, f in (5, 60, 130))
        got.append(s[0])
    assert got != _doom_perpetual(n, 400, (5, 60, 130))


# ---- 138 SR light 255 ----------------------------------------------------------------------------------------------
def test_138_light_switch_e1m3(wad, monkeypatch):
    from doomfj import lights as L
    secs, lds, sds, _v = _map(wad, "E1M3")
    sw = L.switch_thinkers(secs, lds)
    assert [(t.sector, t.kind, t.levels) for t in sw] == [(321, "switch", (112, 255))]
    assert L.game_thinkers(secs, lds, sds, animate=False) == sw
    th = L.game_thinkers(secs, lds, sds, animate=True)
    assert [t.sector for t in th] == sorted(t.sector for t in th) and sw[0] in th
    assert L.tic(sw[0], 1, 0, 7) == (1, 0, 7) and L.level_start(sw)[:2] == ([0], [0])
    w = _world(wad, "E1M3", monkeypatch)
    k = w.light_thinkers.index(sw[0])
    (box, ks), = w.light_uses
    assert ks == (k,) and w.lights_now()[321] == 112
    ws = w.ws
    ws.px, ws.py = (box[0] + 1) << 16, (box[1] + 1) << 16
    w._use_lines(_events())
    assert w.lights_now()[321] == 255


def test_e1m1_e1m2_have_no_light_switch(wad):
    from doomfj import lights as L
    for m in ("E1M1", "E1M2"):
        secs, lds, sds, _v = _map(wad, m)
        assert L.switch_thinkers(secs, lds) == []
        assert L.game_thinkers(secs, lds, sds, m == "E1M2") == (L.thinkers(secs, lds, sds) if m == "E1M2" else [])


def test_control_light_switch_without_its_special(wad, monkeypatch):
    from doomfj import lights as L
    monkeypatch.setattr(L, "SWITCH_LIGHT_SPECIALS", {})
    secs, lds, _s, _v = _map(wad, "E1M3")
    assert L.switch_thinkers(secs, lds) == []


# ---- the readers: a lift line shut for a fireball, a door beside a lift, two movers on two cells -------------------
def test_lift_line_shut_below_a_pass_state_e1m3(wad, monkeypatch):
    from doomfj import projcode
    from doomfj.combat import FIREBALL_H
    w = _world(wad, "E1M3", monkeypatch)
    _rows, doors = projcode.missile_rows(w)
    lift_lines = {li: v for li, v in doors.items() if isinstance(v[0][0], str) and v[0][0].startswith("lstate")}
    assert 261 in lift_lines
    (cell, p), = lift_lines[261]
    ld = w.lds[261]
    a, b = w.sds[ld.front].sector, w.sds[ld.back].sector
    lift = a if a in w.lift_stops else b
    other = b if lift == a else a
    assert cell == "lstate + %d*dw" % w.lift_order.index(lift)
    for k, h in enumerate(w.lift_stops[lift]):        # shut exactly at the states whose opening is under a fireball
        shut = (min(w.secs[lift].ceil_h, w.secs[other].ceil_h) - max(h, w.secs[other].floor_h)) < FIREBALL_H
        assert shut == (k < p), (k, h, p)


def _ns(secs, lds, sds):
    from doomfj import doors
    tab = MV.mover_table(secs, lds, sds)
    return SimpleNamespace(secs=secs, lds=lds, sds=sds, mover_table=tab,
                           door_order=sorted(doors.door_states(secs, lds, sds)), mover_order=sorted(set(tab)))


def test_two_cell_line_e1m6(wad):
    """E1M6's line 512: SR lift 363 lowering into the pool 142 its 20 / 22 raises -- the collision's opening floor needs
    both cells (a PAIR grid); sight / sound / missiles read it as never shut (`monstersight.line_states`)"""
    from doomfj import collision, monstersight
    secs, lds, sds, _v = _map(wad, "E1M6")
    tab = MV.mover_table(secs, lds, sds)
    msecs = MV.mover_secs(tab, secs, MV.change_table(MV.floor_groups(secs, lds, sds)))
    mcell = {si: c for si, (c, _h) in tab.items()}
    e = collision.mover_line_states(lds, sds, msecs, mcell, max)[512]
    f, b = sds[lds[512].front].sector, sds[lds[512].back].sector
    hf, hb = tab[f][1], tab[b][1]
    assert e[0] == "pair" and e[1:3] == (mcell[f], mcell[b]) and e[3] == [[max(x, y) for y in hb] for x in hf]
    _cell, _n, pairs = monstersight.line_states(_ns(secs, lds, sds), f, b)
    assert all(min(c1, c2) - max(f1, f2) > 8 for (f1, c1), (f2, c2) in pairs)


def test_control_two_cell_line_shut_somewhere_refused(wad):
    """R9: the same line with the pool's ceiling brought down near the lift's top -- shut at some pairs and open at
    others: no one cell answers sight -- refused"""
    from doomfj import monstersight
    secs, lds, sds, _v = _map(wad, "E1M6")
    secs = list(secs)
    secs[142] = dataclasses.replace(secs[142], ceil_h=4)
    with pytest.raises(AssertionError, match="whose opening needs both"):
        monstersight.line_states(_ns(secs, lds, sds), 142, 363)


def test_door_beside_a_lift_collision_e1m3(wad, monkeypatch):
    """E1M3's 519: DR door 106 in front of lift 105 -- the opening floor never moves with the lift (the door's floor is
    the higher), the low floor does (the monsters' drop-off)"""
    from doomfj import collision
    w = _world(wad, "E1M3", monkeypatch)
    msecs = MV.mover_secs(w.mover_table, w.secs, w.floor_change)
    mcell = {si: c for si, (c, _h) in w.mover_table.items()}
    ob = collision.mover_line_states(w.lds, w.sds, msecs, mcell, max)[519]
    lf = collision.mover_line_states(w.lds, w.sds, msecs, mcell, min)[519]
    assert ob[0] == lf[0] == mcell[105] and set(ob[1]) == {104} and lf[1] == w.lift_stops[105]


# ---- the renderer's gate and NEW GAME --------------------------------------------------------------------------------
def test_dual_gate_lines():
    from doomfj.wall_renderer import dual_gate_lines, seg_shut_gate
    assert dual_gate_lines("dstate + 3*dw", "o", "s") == ["    hex.if0 1, dstate + 3*dw, s"]       # E1M1's text
    g = seg_shut_gate([True] * 5 + [False] * 5, [10])
    assert g == (0, 0b11111)
    assert dual_gate_lines(("lstate + 6*dw", g[1]), "o", "s") == [
        "    hex.if_flags lstate + 6*dw, 0x001f, o, s", "  o:"]


def test_restart_zeroes_floor_groups_without_lifts():
    from doomfj.wall_renderer import restart_lines
    sp = SimpleNamespace(x=0, y=0, angle=0)
    common, _ = restart_lines(sp, 0, [], [], 0, [], nlift=0, nfs=6, nfloor=3)
    assert "    hex.zero 6, fswitch" in common
    common0, _ = restart_lines(sp, 0, [], [], 0, [], nlift=0, nfs=6)               # R9: the old call: no zeroing
    assert not any("fswitch" in ln for ln in common0)
    with_lift, _ = restart_lines(sp, 0, [], [], 0, [], nlift=2, nfs=6, nfloor=3)
    assert with_lift.count("    hex.zero 6, fswitch") == 1                          # once, as before


def test_the_gates_press_the_light_switch(wad, monkeypatch):
    """the gates step the movers through MoverPhase and the switches through `MonsterPhase.switch_uses` on the press
    edge -- the light switch rides the latter (World.light_presses), so every gate's picture lights the sector"""
    from doomfj.monsters import MonsterPhase
    w = _world(wad, "E1M3", monkeypatch)
    (box, _ks), = w.light_uses
    MonsterPhase.switch_uses(SimpleNamespace(world=w), ((), frozenset(), ()), (box[0] - 5) << 16, box[1] << 16)
    assert w.lights_now()[321] == 112                                         # outside the box: nothing
    MonsterPhase.switch_uses(SimpleNamespace(world=w), ((), frozenset(), ()), (box[0] + 5) << 16, box[1] << 16)
    assert w.lights_now()[321] == 255


def test_every_lift_has_two_states(wad):
    """a one-state lift is no machine (E1M3's 180 moves 0 units): the fj door machine would wrap its state below 0"""
    for m in ("E1M%d" % i for i in range(1, 10)):
        secs, lds, sds, _v = _map(wad, m)
        st = MV.lift_states(secs, lds, sds)
        assert all(len(v) >= 2 for v in st.values()), m
    secs, lds, sds, _v = _map(wad, "E1M3")
    assert 180 not in MV.lift_states(secs, lds, sds) and 256 in MV.lift_states(secs, lds, sds)
    assert secs[180].tag == secs[256].tag == 15


def _survey(m, wad):
    import importlib.util
    spec = importlib.util.spec_from_file_location("level_survey_c4", ROOT / "scripts" / "level_survey.py")
    ls = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ls)
    return ls.Survey(wad, m, wad)


READERS = ("missile cells", "nukage vs the movers", "sight segments", "sound edges",
           "lines between two dynamic sectors (monstersight", "collision cells: mover lines' opening")


def test_the_survey_runs_the_readers(wad):
    """the survey runs the movers' readers (each an emit-time refusal before C4) and says OK when they pass"""
    sv = _survey("E1M3", wad).run()
    rows = {r[1]: r[0] for r in sv.rows}
    for name in READERS:
        hit = [st for chk, st in rows.items() if chk.startswith(name)]
        assert hit == ["OK"], (name, hit)


def test_control_a_refusing_reader_is_refused(wad, monkeypatch):
    """R9: the missile cells' old rule (a lift line that shuts a fireball refused) -- the survey says REFUSED"""
    from doomfj import projcode
    real = projcode.missile_rows

    def old(w):
        rows, doors = real(w)
        assert not any(isinstance(v[0][0], str) and v[0][0].startswith("lstate") for v in doors.values()), (
            "lift line shuts a missile")
        return rows, doors
    monkeypatch.setattr(projcode, "missile_rows", old)
    sv = _survey("E1M3", wad).run()
    assert [r[0] for r in sv.rows if r[1].startswith("missile cells")] == ["REFUSED"]
