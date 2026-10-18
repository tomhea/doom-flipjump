"""M8 C8 -- the Baron of Hell in the MODEL (doomfj.world / combat), on E1M8's own four Barons: A_BruisAttack (the claw
(P_Random()%8+1)*10 in melee range, else MT_BRUISERSHOT: speed 15, damage 8, BAL7 -- and NO A_FaceTarget), the
thing-domain state cells (gamedata.THING_STATE_INDEX), the pain chance 50, and A_BossDeath (the last Baron's death,
the player alive, fires E1M8's tag-666 floor group).

E1M8 holds thing types other clusters build (45, 46, 2046, 2004): the World here leaves them out (as level_survey
does when it counts), which changes nothing a Baron reads.

R9: each rule is held by a check that a broken variant of the model fails (`test_control_*`)."""
from pathlib import Path

import pytest

from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.wad import WadFile
from doomfj.world import TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
_MW = WadFile.from_path(ROOT / "assets" / "freedoom1.wad")


@pytest.fixture
def e1m8(monkeypatch):
    unknown = {t.type for t in _MW.things("E1M8")} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    monkeypatch.setattr(gd, "NOT_THINGS", frozenset(gd.NOT_THINGS | unknown))

    def make(skill=gd.SK_HARD, **kw):
        kw.setdefault("monsters", "final")
        kw.setdefault("player", "final")
        return World(_MW, "E1M8", skill, sight_rule="los", **kw)
    return make


def test_e1m8_spawns_its_barons_in_the_thing_domain(e1m8):
    w = e1m8()
    assert [mi.name for mi in w.mon_info] == ["MT_BRUISER"] * 4
    assert w.mon_radius == [24] * 4 and w.mon_height == [64] * 4
    ws = w.ws
    assert all(gd.THING_STATE_NAMES[ws.mon_state[m]] == "S_BOSS_STND" for m in range(4))
    assert all(ws.mon_state[m] == gd.THING_STATE_INDEX["S_BOSS_STND"] < 256 for m in range(4))
    assert list(ws.mon_health[:4]) == [1000] * 4
    # the skills: easy 2, medium 3, hard 4 (the WAD's flags 6, 7, 4, 7)
    assert [sum(e1m8(sk).ws.mon_active[:4]) for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)] == [2, 3, 4]
    assert w.boss_group is not None and w.floor_groups[w.boss_group].tag == 666


def _face(w, m, dx, dy):
    ws = w.ws
    ws.px, ws.py = (ws.mon_x[m] + dx) << 16, (ws.mon_y[m] + dy) << 16
    ws.mon_target[m] = 1


def _attack(w, m):
    ev = TicEvents(0)
    w._run_action(m, "A_BruisAttack", ev)
    return ev


def test_the_claw_in_melee_range(e1m8):
    w = e1m8()
    ws = w.ws
    m = 1
    _face(w, m, 30, 20)                                   # within MELEERANGE - 20 + 16
    ws.mon_facing[m] = 5
    st0, hp0 = ws.mon_rng[m], ws.p_health
    ev = _attack(w, m)
    v, _ = R.p_random(st0)
    assert ev.mon_melee == [(m, (v % 8 + 1) * 10)], ev.mon_melee
    assert ws.mon_facing[m] == 5, "A_BruisAttack must not face its target"
    assert not ev.proj_spawns and ws.p_health < hp0


def test_the_green_fireball_beyond_melee(e1m8):
    w = e1m8()
    ws = w.ws
    m = 1
    _face(w, m, -400, 0)                                  # a clear line west of slot 1 (east is a wall)
    ev = _attack(w, m)
    assert ev.proj_spawns == [(0, m)] and not ev.mon_melee
    assert gd.THING_STATE_NAMES[ws.proj_state[0]] == "S_BRBALL1"
    an = w.rm.point_to_angle(ws.mon_x[m] << 16, ws.mon_y[m] << 16, ws.px, ws.py)
    assert (ws.proj_momx[0], ws.proj_momy[0]) == C.fireball_momentum_table(w.rm, C.BRUISERSHOT_INFO)[
        an >> w.rm.angle_shift]
    assert ws.proj_momx[0] < -(14 << 16), "speed 15, the imp's is 10"
    # fly it into the player: the impact is (P_Random()%8+1)*8 on the effects stream
    hits = []
    for _ in range(40):
        st = ws.rng_fx
        ev = TicEvents(0)
        w._projectiles_phase(ev)
        if ev.proj_impacts:
            v, _ = R.p_random(st)
            hits.append((ev.proj_impacts[0][1], (v % 8 + 1) * 8))
            break
    assert hits and hits[0][0] == hits[0][1], hits
    assert gd.THING_STATE_NAMES[ws.proj_state[0]] == "S_BRBALLX1"


def test_a_barons_fireball_spares_a_baron(e1m8):
    """PIT_CheckThing's species rule: the shot explodes on another Baron with no damage"""
    w = e1m8()
    ws = w.ws
    a, b = 1, 3
    ws.mon_x[b], ws.mon_y[b] = ws.mon_x[a] - 120, ws.mon_y[a]
    _face(w, a, -400, 0)
    _attack(w, a)
    hp = ws.mon_health[b]
    seen = []
    for _ in range(20):
        ev = TicEvents(0)
        w._projectiles_phase(ev)
        seen += ev.mon_hits
        if not ws.proj_momx[0]:
            break
    assert seen and seen[0][2] == "species" and ws.mon_health[b] == hp, seen


def test_the_pain_chance_is_50(e1m8):
    w = e1m8()
    ws = w.ws
    pains = 0
    for k in range(256):
        ws.mon_rng[0], ws.mon_health[0] = k, 1000
        ws.mon_state[0] = gd.THING_STATE_INDEX["S_BOSS_RUN1"]
        ws.mon_justhit[0] = 0
        w.damage_monster(0, 5, ("player", -1), None, TicEvents(0))
        pains += ws.mon_justhit[0]
    # P_Random() < 50 over the stream's 256 states: DOOM's rndtable holds 43 such values
    assert pains == sum(R.p_random(k)[0] < 50 for k in range(256)) == 43, pains


def _kill(w, m):
    ws = w.ws
    ws.mon_health[m] = 1
    w.damage_monster(m, 10, ("player", -1), None, TicEvents(0))
    assert gd.THING_STATE_NAMES[ws.mon_state[m]] == "S_BOSS_DIE1"


def _run_until_dead(w, frames=40):
    for _ in range(frames):
        w.tic({})


def test_boss_death_fires_on_the_last_baron(e1m8):
    w = e1m8()
    g = w.boss_group
    for m in (0, 1, 2):
        _kill(w, m)
    _run_until_dead(w)
    assert all(gd.THING_STATE_NAMES[w.ws.mon_state[m]] == "S_BOSS_DIE7" for m in (0, 1, 2))
    assert w.floor_state(g) == 0 and w.floor_sub(g) == 0 and not w.boss_log, "a Baron lives: nothing fires"
    _kill(w, 3)
    _run_until_dead(w)
    assert w.boss_log and w.boss_log[0][1] == 3
    assert w.floor_state(g) > 0 or w.floor_sub(g) > 0
    for _ in range(60):
        w.tic({})
    grp = w.floor_groups[g]
    assert w.floor_state(g) == grp.n - 1 and w.mover_heights_now()[3][0] == 0, "sector 3 down to its lowest (0)"


def test_boss_death_counts_only_this_skills_barons(e1m8):
    """medium has three Barons: the hard-only one (inactive, health 1000 in its cell) does not hold the floor"""
    w = e1m8(gd.SK_MEDIUM)
    live = [m for m in range(4) if w.ws.mon_active[m]]
    assert len(live) == 3
    for m in live:
        _kill(w, m)
    _run_until_dead(w)
    assert w.boss_log


def test_boss_death_needs_a_live_player(e1m8):
    w = e1m8()
    for m in range(4):
        _kill(w, m)
    w.ws.p_health = 0
    w.ws.p_dead = 1
    _run_until_dead(w)
    assert not w.boss_log and w.floor_sub(w.boss_group) == 0 and w.floor_state(w.boss_group) == 0


def test_no_boss_death_off_e1m8():
    w = World()                                          # E1M1: no Baron, no boss map
    assert w.boss_group is None


def test_melee_reach_is_the_players(e1m8):
    """P_CheckMeleeRange on the player: the Baron's reach is the imp's (MELEERANGE - 20 + 16), not its own radius"""
    w = e1m8()
    m = 1
    _face(w, m, 59, 0)
    assert w._check_melee_range(m)
    _face(w, m, 60, 0)
    assert aprox_distance(60, 0) == 60 and not w._check_melee_range(m)


# ---- R9: each rule above, broken in the model, must be caught -------------------------------------------------
def test_control_a_facing_baron_is_caught(e1m8, monkeypatch):
    monkeypatch.setattr(C, "NO_FACE_ATTACKS", frozenset())
    with pytest.raises(AssertionError):
        test_the_claw_in_melee_range(e1m8)


def test_control_the_imps_fireball_is_caught(e1m8, monkeypatch):
    monkeypatch.setitem(C.MONSTER_MISSILES, "MT_BRUISER", C.FIREBALL_INFO)
    with pytest.raises((AssertionError, KeyError)):
        test_the_green_fireball_beyond_melee(e1m8)


def test_control_a_wrong_claw_is_caught(e1m8, monkeypatch):
    monkeypatch.setitem(C.CLAW_SITES, "A_BruisAttack", "troop_claw")
    with pytest.raises(AssertionError):
        test_the_claw_in_melee_range(e1m8)


def test_control_a_boss_death_that_ignores_the_others_is_caught(e1m8, monkeypatch):
    def broken(self, m, ev):
        if self.ws.p_health > 0:
            self.boss_log.append((self.tic_count, m))
            self.floor_fire(self.boss_group)
    monkeypatch.setattr(World, "_a_boss_death", broken)
    with pytest.raises(AssertionError):
        test_boss_death_fires_on_the_last_baron(e1m8)


def test_control_a_boss_death_that_counts_absent_barons_is_caught(e1m8, monkeypatch):
    def broken(self, m, ev):
        ws = self.ws
        if ws.p_health > 0 and all(ws.mon_health[j] <= 0 for j in range(self.layout.nmon) if j != m):
            self.boss_log.append((self.tic_count, m))
            self.floor_fire(self.boss_group)
    monkeypatch.setattr(World, "_a_boss_death", broken)
    with pytest.raises(AssertionError):
        test_boss_death_counts_only_this_skills_barons(e1m8)


def test_control_a_boss_death_without_the_player_check_is_caught(e1m8, monkeypatch):
    def broken(self, m, ev):
        ws = self.ws
        if not any(j != m and ws.mon_active[j] and ws.mon_health[j] > 0 for j in range(self.layout.nmon)):
            self.boss_log.append((self.tic_count, m))
            self.floor_fire(self.boss_group)
    monkeypatch.setattr(World, "_a_boss_death", broken)
    with pytest.raises(AssertionError):
        test_boss_death_needs_a_live_player(e1m8)


def test_the_radius_classes_hold_30_and_one_other():
    """M8 C8 (world.radius_classes): class 0 is 20 on every core map, E1M8's 24; a third radius (a lost soul's 16 beside
    an imp's 20) is refused -- the survey's radius row reports it"""
    from doomfj.world import radius_classes
    assert radius_classes([20, 30, 20]) == (20, 30) == radius_classes([30]) == radius_classes([])
    assert radius_classes([24, 24]) == (24, 30) == radius_classes([24, 30])
    for bad in ([16, 20, 30], [16, 24], [20, 24]):
        with pytest.raises(AssertionError):
            radius_classes(bad)
