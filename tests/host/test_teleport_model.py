"""M8 L4: the model's WR teleports (doomfj.teleport; combat._teleport_player, world._teleport_monster, the player's
reactiontime) on E1M2's four lines of special 97 -- the rules DOOM states (p_telept.c EV_Teleport, P_TeleportMove;
p_spec.c P_CrossSpecialLine; p_user.c P_PlayerThink), each through the World's own move:

- the four lines baked: their axes, their FRONT sides (from the vertices, by hand), their destinations (EV_Teleport's
  sector-then-thinker search), the destination angle, leaf and floor; E1M1 has none -- no Layout count, no schema
  field (its digests unchanged);
- the player WALKING across a line from its front teleports (position, angle, reactiontime 18, knock momentum 0),
  from its back does not, and WR fires again on the next crossing; the 18 frozen frames (no turn, no walk) and the
  walk after them; a monster at the destination refuses the teleport (NO TELEFRAG: the simplification);
- the KNOCK move (combat._xy_move) across a line: the destination, the loop going on from it, the momentum stopped;
- a MONSTER's accepted move across a line: the destination, its floorz, its facing, its leaf list relinked (the
  incremental lists equal the from-scratch build), the momentum and the fraction 0; the living player or another
  monster at the destination refuses it (P_TeleportMove's PIT_StompThing), a dead player does not;
- the restart forgets the reactiontime.
CONTROL (R9): the side test inverted (front_le flipped) teleports from the back -- the walk test parts.
"""
import dataclasses
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj.teleport import REACTION_TICS, crossed_front, teleporters
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


def test_a_monster_at_the_destination_refuses_the_player(w):
    ws = w.ws
    m = next(m for m in range(w.layout.nmon) if w.mon_radius[m] == 20)
    ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 1
    ws.mon_x[m], ws.mon_y[m] = 1504 + 35, -1440                                 # blockdist 36: inside
    tr = _walk(w, 1740, -1680, 0, 1, forward=True)
    assert tr[0] == (1756 << 16, -1680 << 16, 0, 0)                            # the move stays, no teleport
    ws.mon_x[m] = 1504 + 36                                                     # exactly the blockdist: outside
    tr = _walk(w, 1740, -1680, 0, 1, forward=True)
    assert tr[0][:2] == (1504 << 16, -1440 << 16)


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
