"""M8 L4: the model's WR teleports (doomfj.teleport; combat._teleport_player, world._teleport_monster, the player's
reactiontime) on E1M2's four lines of special 97 -- the rules DOOM states (p_telept.c EV_Teleport, P_TeleportMove;
p_spec.c P_CrossSpecialLine; p_user.c P_PlayerThink), each through the World's own move:

- the four lines baked: their axes, their FRONT sides (from the vertices, by hand), their destinations (EV_Teleport's
  sector-then-thinker search), the destination angle, leaf and floor; E1M1 has none -- no Layout count, no schema
  field (its digests unchanged);
- the player WALKING across a line from its front teleports (position, angle, reactiontime 18, knock momentum 0),
  from its back does not, and WR fires again on the next crossing; the 18 frozen frames (no turn, no walk) and the
  walk after them; every shootable monster at the destination is TELEFRAGGED (P_TeleportMove's P_DamageMobj 10000
  from the player: the thrust away from where his move left him, the health at the cell's floor, the gib or the
  death, the tics roll, the kill count, the drop) and the teleport goes on; one exactly at the blockdist is untouched;
- the KNOCK move (combat._xy_move) across a line: the destination, the loop going on from it, the momentum stopped;
- a MONSTER's accepted move across a line: the destination, its floorz, its facing, its leaf list relinked (the
  incremental lists equal the from-scratch build), the momentum and the fraction 0; the living player or another
  monster at the destination refuses it (P_TeleportMove's PIT_StompThing), a dead player does not;
- the restart forgets the reactiontime;
- M8 THE TELEPORT FOG: two MT_TFOG per teleport that happens (where the mover's move left it, then 20 units
  ahead of the destination), none for a refused one, through the effects pool: 72 tics over the twelve states,
  no P_Random, A FOG YIELDS (blood and puffs take a fog's slot; a fog never takes one), only where fog_on.
CONTROL (R9): the side test inverted (front_le flipped) teleports from the back -- the walk test parts; the old rule
(the player's teleport refused at an occupied destination) parts from the telefrag test.
"""
import dataclasses
import math
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import teleport as TP
from doomfj.combat import MON_HEALTH_MIN
from doomfj.teleport import REACTION_TICS, TELEFRAG_DAMAGE, crossed_front, teleporters
from doomfj.wad import WadFile
from doomfj.world import KEYS, TicEvents, World, build_schema, p8a_schema

FIX = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def mw2():
    return WadFile.from_path(FIX / "freedoom_e1m2.wad")


def _world(mw2):
    w = World(mw2, "E1M2", skill=gd.SK_HARD, player="final", monsters="final")
    ws = w.ws
    # the pad's sides (201, 210) down to their floor: the pad can be left -- M8 F1.3: E1M2's one-shot floors are a group
    # per tag (`fswitch` a vector), so the group holding 201 / 210 at its last state (its destination)
    (g,) = [k for k, gr in enumerate(w.floor_groups) if {si for si, _h in gr.heights} >= {201, 210}]
    ws.f_switch[g] = w.floor_groups[g].n - 1
    for m in range(w.layout.nmon):              # nothing in the way (the pad's own monsters stand on it)
        if ws.mon_active[m]:
            w._list_remove(m, ws.mon_leaf[m])
        ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 0
    w._door_phase_scene()
    return w


@pytest.fixture
def w(mw2):
    return _world(mw2)


def _keys(**on):
    k = dict.fromkeys(KEYS, False)
    k.update(on)
    return k


def test_e1m2s_four_lines_and_their_destinations(mw2):
    tels = teleporters(mw2, "E1M2")
    got = [(t.line, t.tag, t.axis, t.coord, t.lo, t.hi, t.front_le, t.dest, t.angle, t.dest_sector, t.dest_floor)
           for t in tels]
    assert got == [
        (126, 20, "x", 2816, 0, 320, False, (1832, 488), 0x80000000, 153, -56),     # v1 (2816,0) -> (2816,320)
        (1215, 18, "x", 1624, -1744, -1616, False, (1504, -1440), 0, 198, 240),    # v1 y -1744 -> -1616
        (1219, 18, "x", 1752, -1744, -1616, True, (1504, -1440), 0, 198, 240),     # v1 y -1616 -> -1744
        (1910, 20, "x", 2800, 0, 320, True, (1832, 488), 0x80000000, 153, -56)]    # v1 y 320 -> 0
    w = World(mw2, "E1M2")
    for t in tels:
        assert w.rm.point_in_subsector(w.cmap, *t.dest) == t.dest_leaf
        assert w.leaf_sector[t.dest_leaf] == t.dest_sector
        assert t.facing == (4 if t.angle else 0)


def test_e1m1_has_no_teleporter_and_no_new_cell():
    w = World(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1")
    assert w.teleports == [] and w.layout.ntele == 0
    names = [f.name for f in w.schema]
    assert "p_reaction" not in names
    lay = dataclasses.replace(w.layout, ntele=4)
    with_tele = [f.name for f in build_schema(lay, **p8a_schema(w.player, w.monsters))]
    assert "p_reaction" in with_tele and [n for n in with_tele if n != "p_reaction"] == names


def _walk(w, x, y, angle, frames, **keys):
    ws, out = w.ws, []
    ws.px, ws.py, ws.pangle = x << 16, y << 16, angle
    for _ in range(frames):
        w._player_move(_keys(**keys), TicEvents(0))
        out.append((ws.px, ws.py, ws.pangle, ws.p_reaction))
    return out


def test_walking_out_of_the_pad_from_the_front_teleports(w):
    """the tag-18 pad (sector 51, x 1624..1752): line 1219's front is the pad; walking east off it teleports to
    (1504, -1440) facing east, frozen 18 frames (the keys held: no walk, no turn), then walking on"""
    ws = w.ws
    ws.p_momx, ws.p_momy = 5 << 16, -3 << 16
    tr = _walk(w, 1740, -1680, 0, 22, forward=True, turn_left=True)
    assert tr[0] == (1504 << 16, -1440 << 16, 0, REACTION_TICS)
    assert (ws.p_momx, ws.p_momy) == (0, 0)
    for f in range(1, 19):
        assert tr[f] == (1504 << 16, -1440 << 16, 0, REACTION_TICS - f), f
    assert tr[19][3] == 0 and tr[19][2] != 0 and tr[19][:2] != tr[18][:2]       # turning and walking again


def test_walking_onto_the_pad_from_the_back_does_not(w):
    tr = _walk(w, 1770, -1680, 0x80000000, 3, forward=True)
    assert [p[0] >> 16 for p in tr] == [1754, 1738, 1722] and all(p[3] == 0 for p in tr)
    tr = _walk(w, 1606, -1680, 0, 3, forward=True)                              # west of 1624, walking east
    assert [p[0] >> 16 for p in tr] == [1622, 1638, 1654] and all(p[3] == 0 for p in tr)


def test_wr_teleports_on_every_crossing(w):
    for _ in range(3):
        w.ws.p_reaction = 0
        tr = _walk(w, 1630, -1700, 0x80000000, 1, forward=True)                 # line 1215, westward off the pad
        assert tr[0][:2] == (1504 << 16, -1440 << 16)


def _at_dest(w, m, x, y, health):
    ws = w.ws
    ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 1
    ws.mon_x[m], ws.mon_y[m], ws.mon_health[m] = x, y, health
    ws.mon_momx[m] = ws.mon_momy[m] = 0


def _telefrag_scene(w):
    """P_TeleportMove for the player: every shootable thing whose box overlaps the destination's dies (10000 from the
    player) and the teleport goes on; one exactly at the blockdist (|dx| = r + 16) is outside and untouched. Slot by
    slot: an imp (gibs: -2048 < -60), a demon (no xdeath state: the death), a zombieman (gibs, drops its clip); the
    thrust pushes each away from where the player's move left him (1756, -1680), the mass 400 a quarter as far.
    -> the list of the expectations that FAILED (empty: the rule holds)"""
    ws = w.ws
    kinds = {}
    for m in range(w.layout.nmon):
        kinds.setdefault(w.mon_info[m].name, []).append(m)
    imp, demon, zomb, far = kinds["MT_TROOP"][0], kinds["MT_SERGEANT"][0], kinds["MT_POSSESSED"][0], kinds["MT_TROOP"][1]
    _at_dest(w, imp, 1504 + 35, -1440 + 3, 60)                                  # blockdist 36: inside
    _at_dest(w, demon, 1504 - 40, -1440 - 45, 150)                              # blockdist 46: inside
    _at_dest(w, zomb, 1504 + 10, -1440, 1)
    _at_dest(w, far, 1504 + 36, -1440, 60)                                      # exactly the blockdist: outside
    kc, rng0 = ws.p_killcount, {m: ws.mon_rng[m] for m in (imp, demon, zomb)}
    tr = _walk(w, 1740, -1680, 0, 1, forward=True)
    bad = []

    def want(name, ok):
        if not ok:
            bad.append(name)
    want("teleported", tr[0] == (1504 << 16, -1440 << 16, 0, REACTION_TICS))   # the teleport is NOT refused
    for m, st in ((imp, "S_TROO_XDIE1"), (demon, "S_SARG_DIE1"), (zomb, "S_POSS_XDIE1")):
        want("dead%d" % m, ws.mon_health[m] == MON_HEALTH_MIN and not ws.mon_shootable[m])
        want("state%d" % m, gd.STATE_NAMES[ws.mon_state[m]] == st)
        want("roll%d" % m, ws.mon_rng[m] != rng0[m])                           # the tics roll
    want("killcount", ws.p_killcount == kc + 3)
    want("drop", ws.mon_drop[zomb] == 1 and (ws.drop_x[zomb], ws.drop_y[zomb]) == (1504 + 10, -1440))
    want("far", ws.mon_health[far] == 60 and ws.mon_shootable[far] and (ws.mon_momx[far], ws.mon_momy[far]) == (0, 0))
    # the thrust: from the player's whole-unit position after his move to the victim -- away from him (all three
    # north-west of him) -- 10000 * trig >> 3 (mass 100) or >> 5 (400)
    want("thrust_dir", all(ws.mon_momx[m] < 0 < ws.mon_momy[m] for m in (imp, demon, zomb)))
    size = {m: math.hypot(ws.mon_momx[m], ws.mon_momy[m]) for m in (imp, demon)}
    want("thrust_size", abs(size[imp] - (TELEFRAG_DAMAGE << 13)) < 0.01 * (TELEFRAG_DAMAGE << 13)
         and abs(4 * size[demon] - size[imp]) < 0.01 * size[imp])
    return bad


def test_the_player_telefrags_what_stands_at_the_destination(w):
    assert _telefrag_scene(w) == []


def test_the_telefrag_is_p_damagemobj_10000_from_the_player(w, monkeypatch):
    """the model's telefrag IS damage_monster(slot, 10000, player, player) -- the one rule every kill takes"""
    calls = []
    real = w.damage_monster
    monkeypatch.setattr(w, "damage_monster", lambda m, d, s, i, ev: (calls.append((m, d, s, i)), real(m, d, s, i, ev)))
    m = next(m for m in range(w.layout.nmon) if w.mon_radius[m] == 20)
    _at_dest(w, m, 1504, -1440, 20)
    _walk(w, 1740, -1680, 0, 1, forward=True)
    assert calls == [(m, TELEFRAG_DAMAGE, ("player", -1), ("player", -1))]


def test_control_the_old_refusal_parts_from_the_telefrag(w, monkeypatch):
    """R9: the player's teleport refused at an occupied destination (the rule before the owner's 2026-10-18 change),
    and a telefrag that hurts without killing (10000 not held at the cell's floor: the 12-bit cell wraps) -- each
    makes the telefrag scene fail"""
    import doomfj.combat as C
    real = C.CombatMixin._teleport_player

    def refuse(self, x, y, cx, cy, ev=None):
        tel = next((t for t in self.teleports if crossed_front(t, (x, y), (cx, cy), 16)), None)
        if tel is not None and TP.stomp_victims(self, tel.dest, 16):
            return
        return real(self, x, y, cx, cy, ev)
    monkeypatch.setattr(C.CombatMixin, "_teleport_player", refuse)
    assert "teleported" in _telefrag_scene(w)


def test_control_an_unheld_health_parts_from_the_telefrag(mw2, monkeypatch):
    import doomfj.combat as C
    monkeypatch.setattr(C, "MON_HEALTH_MIN", -(1 << 20))
    bad = _telefrag_scene(_world(mw2))
    assert any(b.startswith("dead") for b in bad), bad


def test_the_knock_move_teleports_and_stops(w):
    ws = w.ws
    ws.px, ws.py = 1740 << 16, -1680 << 16
    ws.p_momx, ws.p_momy = 30 << 16, 0                                         # MAXMOVE: two half steps of 15
    w._xy_move(("player", -1), TicEvents(0))
    # the first half step (1755) crosses line 1219 from the front: the destination, then the second half from it
    assert (ws.px, ws.py) == ((1504 + 15) << 16, -1440 << 16)
    assert (ws.p_momx, ws.p_momy, ws.p_reaction) == (0, 0, REACTION_TICS)


def _mover(w, radius):
    ws = w.ws
    m = next(m for m in range(w.layout.nmon) if w.mon_radius[m] == radius)
    ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 1
    ws.mon_x[m], ws.mon_y[m] = 1745, -1680
    leaf = w.rm.point_in_subsector(w.cmap, 1745, -1680)
    ws.mon_leaf[m] = leaf
    w._list_insert(m, leaf)
    ws.mon_facing[m], ws.mon_momx[m], ws.mon_fx[m] = 3, 7 << 16, 0x1234
    return m


@pytest.mark.parametrize("radius", [20, 30])
def test_a_monster_crossing_from_the_front_teleports(w, radius):
    ws = w.ws
    m = _mover(w, radius)
    w._move_monster(m, 1753, -1680, 240, TicEvents(0))
    assert (ws.mon_x[m], ws.mon_y[m], ws.mon_floorz[m], ws.mon_facing[m]) == (1504, -1440, 240, 0)
    assert (ws.mon_momx[m], ws.mon_fx[m]) == (0, 0)
    assert ws.mon_leaf[m] == w.teleports[2].dest_leaf
    assert w.leaf_lists() == w.leaf_lists_from_scratch()
    # and back across from the back: nothing
    ws.mon_x[m], ws.mon_y[m] = 1760, -1680
    w._move_monster(m, 1752, -1680, 240, TicEvents(0))
    assert (ws.mon_x[m], ws.mon_y[m]) == (1752, -1680)


def test_a_monster_is_refused_by_the_living_player_only(w):
    ws = w.ws
    m = _mover(w, 20)
    ws.px, ws.py = (1504 + 35) << 16, -1440 << 16                              # blockdist 20 + 16: inside
    w._move_monster(m, 1753, -1680, 240, TicEvents(0))
    assert (ws.mon_x[m], ws.mon_y[m]) == (1753, -1680) and ws.mon_facing[m] == 3
    ws.p_dead, ws.p_health = 1, 0                                               # a corpse is not shootable
    ws.mon_x[m] = 1745
    w._move_monster(m, 1753, -1680, 240, TicEvents(0))
    assert (ws.mon_x[m], ws.mon_y[m]) == (1504, -1440)


def test_the_restart_forgets_the_reactiontime(w):
    ws = w.ws
    ws.p_reaction = 11
    w._restart(TicEvents(0))
    assert ws.p_reaction == 0


def test_control_a_flipped_side_teleports_from_the_back(w):
    """R9: the rule with front_le inverted -- the back-side walk of the test above teleports"""
    w.teleports = [dataclasses.replace(t, front_le=not t.front_le) for t in w.teleports]
    tr = _walk(w, 1770, -1680, 0x80000000, 2, forward=True)                 # 1754, then across x 1752
    assert tr[1][:2] == (1504 << 16, -1440 << 16)


def test_the_tag_20_strip_is_a_step_too_high_until_its_floor_moves(w):
    """the record of a dependency: line 1910's strip (sector 351, floor -15) is 25 above its sides (sector 150,
    -40) -- P_TryMove refuses the step, so the tag-20 teleporter needs 351 lowered (line 1972, special 38: the floors
    rung, L3). Crossing tests of these lines run on the rule (crossed_front), not on a walk"""
    tr = _walk(w, 2780, 160, 0, 3, forward=True)
    assert all(p[0] >> 16 < 2800 + 16 for p in tr) and all(p[3] == 0 for p in tr)
    tel = w.teleports[3]
    assert crossed_front(tel, (2795 << 16, 160 << 16), (2805 << 16, 160 << 16), 16)


# ---- M8: THE TELEPORT FOG (doomfj.teleport; combat._teleport_fogs / _spawn_fx) ------------------------------------

def _fogs(w):
    ws = w.ws
    return [(gd.STATE_NAMES[ws.fx_state[s]], ws.fx_tics[s], ws.fx_x[s] >> 16, ws.fx_y[s] >> 16, ws.fx_leaf[s])
            for s in range(len(ws.fx_active)) if ws.fx_active[s]]


def test_the_destination_fogs_are_20_units_ahead():
    """EV_Teleport: m->x + 20*finecosine[an] -- east of (1504, -1440) facing east, west of (1832, 488) facing west"""
    tels = teleporters(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2")
    assert [t.fog for t in tels] == [(1812, 488), (1524, -1440), (1524, -1440), (1812, 488)]


def test_a_player_teleport_spawns_two_fogs(w):
    """the source fog where his move left him (whole units), then the destination's; S_TFOG with its 6 tics (no draw:
    rng_fx untouched), each linked into its leaf as an effect"""
    ws = w.ws
    rng0 = ws.rng_fx
    tr = _walk(w, 1740, -1680, 0, 1, forward=True)
    assert tr[0][:2] == (1504 << 16, -1440 << 16)
    leaf = w.rm.point_in_subsector
    assert _fogs(w) == [("S_TFOG", 6, 1756, -1680, leaf(w.cmap, 1756, -1680)),
                        ("S_TFOG", 6, 1524, -1440, leaf(w.cmap, 1524, -1440))]
    assert ws.rng_fx == rng0 and w.leaf_lists() == w.leaf_lists_from_scratch()


def test_a_monster_teleport_spawns_two_fogs_and_a_refused_one_none(w):
    ws = w.ws
    m = _mover(w, 20)
    w._move_monster(m, 1753, -1680, 240, TicEvents(0))
    assert [f[:4] for f in _fogs(w)] == [("S_TFOG", 6, 1753, -1680), ("S_TFOG", 6, 1524, -1440)]
    for s in range(2):                                                      # the pool emptied again
        w._list_remove(w._mobile_fx(s), ws.fx_leaf[s])
        ws.fx_active[s] = ws.fx_state[s] = ws.fx_tics[s] = ws.fx_x[s] = ws.fx_y[s] = ws.fx_leaf[s] = 0
    m2 = _mover(w, 30)                                                      # refused: m stands on the destination
    w._move_monster(m2, 1753, -1680, 240, TicEvents(0))
    assert _fogs(w) == [] and (ws.mon_x[m2], ws.mon_y[m2]) == (1753, -1680)


def test_a_fog_lives_72_tics_through_its_twelve_states(w):
    ws = w.ws
    _walk(w, 1740, -1680, 0, 1, forward=True)
    seen = []
    for _ in range(72):
        seen.append(gd.STATE_NAMES[ws.fx_state[0]])
        w._fx_phase(TicEvents(0))
    assert not ws.fx_active[0] and not ws.fx_active[1]
    assert seen[::6] == ["S_TFOG", "S_TFOG01", "S_TFOG02"] + ["S_TFOG%d" % k for k in range(2, 11)]
    assert [gd.STATES[s].frame_index for s in seen[::6]] == [0, 1, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert w.leaf_lists() == w.leaf_lists_from_scratch()


def test_a_fog_yields_its_slot_to_blood_and_never_takes_one(w):
    """A FOG YIELDS: blood takes the first slot that is free or a fog's (the fog unlinked), so blood spawns as with no
    fog; a fog never evicts (the pool full of blood: skipped)"""
    ws = w.ws
    _walk(w, 1740, -1680, 0, 1, forward=True)                               # two fogs: the pool is full
    ev = TicEvents(0)
    w._spawn_fx("blood", 100 << 16, 200 << 16, 10, False, ev)
    assert ev.fx_spawns == [(0, "blood")] and ev.fx_skipped == 0
    assert [f[0] for f in _fogs(w)] == ["S_BLOOD2", "S_TFOG"]
    w._spawn_fx("puff", 300 << 16, 200 << 16, 0, False, ev)
    assert ev.fx_spawns[-1] == (1, "puff") and [f[0] for f in _fogs(w)] == ["S_BLOOD2", "S_PUFF1"]
    w._spawn_fx("fog", 500 << 16, 500 << 16, 0, False, ev)
    assert ev.fx_skipped == 1 and [f[0] for f in _fogs(w)] == ["S_BLOOD2", "S_PUFF1"]
    assert w.leaf_lists() == w.leaf_lists_from_scratch()


def test_no_fog_without_a_looting_player(mw2):
    """teleport.fog_on: the game tier's modes only (the fj's teleports exist there); a "walk" player teleports
    without one"""
    from doomfj.teleport import fog_on
    w = World(mw2, "E1M2", skill=gd.SK_HARD, player="walk", monsters="full")
    assert not fog_on(w) and fog_on(_world(mw2))
    assert not fog_on(World(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1", player="final", monsters="final"))


def test_control_a_fog_that_takes_blood_s_slot_parts(w, monkeypatch):
    """R9: the yield inverted (a fog evicts a fog or blood like blood does) -- the yield test's last spawn parts"""
    real = w._spawn_fx

    def greedy(kind, x16, y16, dmg, melee, ev):
        if kind == "fog" and all(w.ws.fx_active):
            w._list_remove(w._mobile_fx(0), w.ws.fx_leaf[0])
            w.ws.fx_active[0] = 0
        return real(kind, x16, y16, dmg, melee, ev)
    monkeypatch.setattr(w, "_spawn_fx", greedy)
    with pytest.raises(AssertionError):
        test_a_fog_yields_its_slot_to_blood_and_never_takes_one(w)
