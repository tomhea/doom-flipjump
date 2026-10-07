"""M7 P7 -- the dead view TURNS TO THE KILLER, in the model (owner, 2026-10-05; docs/gp-p67-interface.md section 10,
O1). P_DeathThink (p_user.c): with `player->attacker` set and not the player himself, the angle to it
(R_PointToAngle2) is approached ANG5 a tic the short way; within ANG5 either way the view snaps to it and the damage
flash fades; with no attacker the flash fades. `player->attacker` is P_DamageMobj's `source` of the last hit that
landed: a monster (its hitscan, claw, bite, or its fireball -- the missile's shooter), else none (sector damage's
NULL; a barrel's blast carries the barrel's target, the player who set it off: the player himself turns nothing).
Only the "full" player mode turns (P7); before it the flash fades every dead tic, as P5's model did. The fj's mirror
is tests/fj/test_death_turn_fj.py."""
import pytest

from doomfj import gamedata as gd
from doomfj import world as W
from doomfj.combat import ANG5

M32 = 0xFFFFFFFF
NOKEYS = dict.fromkeys(W.KEYS, False)


def _world(player="full"):
    return W.World(skill=gd.SK_HARD, monsters="full", player=player)


@pytest.mark.parametrize("source,want", [(("mon", 0), 1), (("mon", 52), 53), (("sector", 23), 0), (("bar", 4), 0),
                                         (("test", 0), 0)])
def test_the_attacker_is_the_last_landed_hits_source(source, want):
    w = _world()
    ws = w.ws
    assert ws.p_attacker == 0                                   # the level start: none
    w.damage_player(5, ("mon", 9), ("mon", 9), W.TicEvents(0))
    assert ws.p_attacker == 10
    w.damage_player(5, source, source, W.TicEvents(0))
    assert ws.p_attacker == want


def test_a_hit_that_does_not_land_names_no_attacker():
    w = _world()
    ws = w.ws
    w.damage_player(200, ("mon", 3), ("mon", 3), W.TicEvents(0))           # the kill
    assert ws.p_dead and ws.p_attacker == 4
    w.damage_player(5, ("mon", 7), ("mon", 7), W.TicEvents(0))             # a dead player takes nothing
    assert ws.p_attacker == 4


def test_the_monsters_real_attacks_name_their_slot():
    """a played fight (test_gp_restart's scenario): every tic whose last landed hit came from a monster leaves that
    monster's slot (the fireball's SHOOTER for an impact) as the attacker"""
    from tests.host.test_gp_restart import scenario
    w, keys = scenario(W, gd)
    kinds = set()
    for k in keys:
        ev = w.tic(k)
        if ev.player_hurt:
            src = ev.player_hurt[-1][0]
            assert w.ws.p_attacker == (src[1] + 1 if src[0] == "mon" else 0), (src, w.ws.p_attacker)
            kinds.add(src[0])
    assert "mon" in kinds and w.event_totals()["player_hurt"]


def _dead_with(w, ang, dc, atk, at=(0, 0)):
    ws = w.ws
    ws.p_dead, ws.pangle, ws.p_damagecount, ws.p_attacker = 1, ang, dc, atk
    if atk:
        ws.mon_x[atk - 1], ws.mon_y[atk - 1] = at
    return ws


def test_the_dead_view_turns_the_short_way_then_snaps_and_fades():
    w = _world()
    px, py = w.ws.px >> 16, w.ws.py >> 16
    for (dx, dy), turns in (((300, 0), 9), ((-300, 1), 17)):
        target = w.rm.point_to_angle(w.ws.px, w.ws.py, (px + dx) << 16, (py + dy) << 16)
        for sign in (1, -1):
            start = (target - sign * (ANG5 * turns + ANG5 // 2)) & M32
            ws = _dead_with(w, start, 60, 5, (px + dx, py + dy))
            seen = []
            for _ in range(turns + 3):
                w._death_think(NOKEYS, W.TicEvents(0))
                seen.append((ws.pangle, ws.p_damagecount))
            for t in range(turns):                               # ANG5 a tic toward it; the flash held
                assert seen[t] == ((start + sign * ANG5 * (t + 1)) & M32, 60), (t, sign, seen[t])
            assert seen[turns] == (target, 59)                  # within ANG5: the snap, and the fade
            assert seen[turns + 2] == (target, 57)


def test_exactly_half_a_turn_away_turns_the_minus_way_and_the_boundaries_are_strict():
    w = _world()
    px, py = w.ws.px >> 16, w.ws.py >> 16
    a = w.rm.point_to_angle(w.ws.px, w.ws.py, (px + 40) << 16, (py + 90) << 16)
    for d, want in ((0x80000000, -ANG5), (0x7FFFFFFF, ANG5), (ANG5, ANG5), (ANG5 - 1, None), (-ANG5 & M32, -ANG5),
                    ((-ANG5 + 1) & M32, None)):
        ws = _dead_with(w, (a - d) & M32, 10, 1, (px + 40, py + 90))
        w._death_think(NOKEYS, W.TicEvents(0))
        if want is None:
            assert (ws.pangle, ws.p_damagecount) == (a, 9), hex(d)
        else:
            assert (ws.pangle, ws.p_damagecount) == ((a - d + want) & M32, 10), hex(d)


def test_no_attacker_fades_and_does_not_turn():
    w = _world()
    ws = _dead_with(w, 0x1234, 3, 0)
    for k in range(5):
        w._death_think(NOKEYS, W.TicEvents(0))
    assert (ws.pangle, ws.p_damagecount) == (0x1234, 0)


def test_before_full_the_dead_view_never_turned():
    """R9 for the gate: the "fx" mode keeps P5's death think (the flash fades, nothing turns), so the turn is the
    "full" mode's alone -- and "full" does turn on the same state"""
    for mode, turned in (("fx", False), ("full", True)):
        w = _world(mode)
        px, py = w.ws.px >> 16, w.ws.py >> 16
        ws = _dead_with(w, 0, 50, 2, (px - 200, py + 200))
        w._death_think(NOKEYS, W.TicEvents(0))
        assert (ws.pangle != 0) == turned and ws.p_damagecount == (50 if turned else 49), mode


def test_the_restart_forgets_the_attacker():
    w = _world()
    w.damage_player(250, ("mon", 11), ("mon", 11), W.TicEvents(0))
    assert w.ws.p_attacker == 12
    w._restart(W.TicEvents(0))
    assert w.ws.p_attacker == 0 and "p_attacker" in w.restart_fields
