"""P9 (the owner, 2026-10-10: "choose a cool different weapon") -- THE ROCKET LAUNCHER in the model (doomfj.combat's
P9 conventions, gamedata's MT_ROCKET / S_MISSILE* / S_ROCKET / S_EXPLODE*, things.SINGLE_PLAYER_EXTRA). The fj's side
is tests/fj/test_rocket_fj.py (the flight, the things, the blast), test_weapon_fj.py (the firing), test_give_fj.py /
test_pickup_fj.py (the pickups) and test_keyboard_input.py (key 5)."""
import pytest

from doomfj import gamedata as gd
from doomfj import combat as C
from doomfj import projcode as PC
from doomfj.reference_model import ReferenceModel
from doomfj.things import SINGLE_PLAYER_EXTRA, single_player
from doomfj.world import FIREBALL_POOL, KEYS, WEAPON_TICS, TicEvents, World

LAUNCHER = (976, -544)


def _keys(**on):
    return {k: bool(on.get(k)) for k in KEYS}


@pytest.fixture(scope="module")
def world():
    return World(monsters="final", player="final")


def _fresh(w):
    w.reset(gd.SK_HARD)
    return w


def _ready_launcher(w, rockets=10):
    """the launcher up and ready, `rockets` of ammo, the player somewhere open (no monster awake near)"""
    ws = _fresh(w).ws
    ws.p_owned[gd.WP_MISSILE] = 1
    ws.p_ammo[gd.AM_MISL] = rockets
    ws.p_ready, ws.p_pending = gd.WP_MISSILE, gd.WP_NOCHANGE
    ws.p_wpn_state, ws.p_wpn_tics = gd.STATE_INDEX["S_MISSILE"], 1
    ws.p_wpn_sy, ws.p_attackdown = gd.WEAPONTOP >> 16, 0
    return ws


# ---- the map: the launcher and its rockets in single player ---------------------------------------------------------
def test_the_launcher_and_its_rockets_are_single_player_things(world):
    mp = [t for t in world.mw.things("E1M1") if t.flags & gd.MTF_NOTSINGLE]
    extra = [t for t in mp if single_player(t)]
    assert sorted((t.type, t.x, t.y) for t in extra) == sorted(SINGLE_PLAYER_EXTRA)
    assert len(extra) == 5 and all(t.flags & 7 == 7 for t in extra)                  # every skill
    assert not any(single_player(t) for t in mp if (t.type, t.x, t.y) not in SINGLE_PLAYER_EXTRA)
    picks = [(t.type, t.x, t.y) for t in world.pickup_things]
    assert (2003,) + LAUNCHER in picks and sum(1 for p in picks if p[0] == 2010) == 5   # + E1M1's own #279


def test_the_tables_hold_the_launcher():
    assert gd.WEAPONINFO[gd.WP_MISSILE].ammo == gd.AM_MISL and gd.STATES["S_ROCKET"].tics == 1
    assert C.ROCKET_INFO.speed == 20 << 16 and C.ROCKET_INFO.damage == 20 and C.ROCKET_INFO.radius == 11 << 16
    assert C.ROCKET_R == C.FIREBALL_R == 6, "the 2D convention: the rocket meets lines and things at 6"
    assert not gd.check_integrity()
    # appended: every state index before P9 is what it was (the frozen runs' state cells keep their meaning)
    assert gd.STATE_INDEX["S_SHOT"] == 211 and gd.STATE_INDEX["S_ROCKET"] == 222


# ---- the pickups ----------------------------------------------------------------------------------------------------
def test_the_launcher_gives_two_rockets_and_comes_up(world):
    ws = _fresh(world).ws
    assert world._touch(2003, False, 0, 0)
    assert ws.p_owned[gd.WP_MISSILE] and ws.p_ammo[gd.AM_MISL] == 2 and ws.p_pending == gd.WP_MISSILE
    ws.p_pending = gd.WP_NOCHANGE
    assert world._touch(2003, False, 0, 0) and ws.p_ammo[gd.AM_MISL] == 4 and ws.p_pending == gd.WP_NOCHANGE
    ws.p_ammo[gd.AM_MISL] = world.max_ammo(gd.AM_MISL)
    assert not world._touch(2003, False, 0, 0), "owned and full: nothing to take"


def test_rockets_from_empty_bring_the_launcher_up_from_the_fist(world):
    ws = _fresh(world).ws
    ws.p_ready = gd.WP_FIST
    assert world._touch(2010, False, 0, 0) and ws.p_pending == gd.WP_NOCHANGE      # no launcher: no switch
    ws.p_ammo[gd.AM_MISL], ws.p_owned[gd.WP_MISSILE] = 0, 1
    assert world._touch(2046, False, 0, 0) and ws.p_ammo[gd.AM_MISL] == 5 and ws.p_pending == gd.WP_MISSILE


def test_walking_onto_the_launcher_takes_it(world):
    ws = _fresh(world).ws
    ws.px, ws.py, ws.pangle = (LAUNCHER[0] - 40) << 16, LAUNCHER[1] << 16, 0
    got = []
    for _ in range(4):
        got += world.tic(_keys(forward=True)).pickups
    assert any(k == 2003 for _w, _i, k in got) and ws.p_owned[gd.WP_MISSILE]
    assert ws.p_ammo[gd.AM_MISL] >= 2


# ---- key 5 and the firing ---------------------------------------------------------------------------------------------
def test_key_5_brings_the_launcher_up(world):
    ws = _fresh(world).ws
    ws.p_owned[gd.WP_MISSILE], ws.p_ammo[gd.AM_MISL] = 1, 3
    world.tic(_keys(w5=True))
    assert ws.p_pending == gd.WP_MISSILE
    for _ in range(40):
        world.tic(_keys())
    assert ws.p_ready == gd.WP_MISSILE and gd.STATE_NAMES[ws.p_wpn_state] == "S_MISSILE"
    ws2 = _fresh(world).ws
    world.tic(_keys(w4=True, w5=True))                 # the LOWEST held key names the weapon: 4, never owned
    assert ws2.p_pending == gd.WP_NOCHANGE


def test_a_held_trigger_fires_a_rocket_every_ten_frames(world):
    ws = _ready_launcher(world)
    frames = []
    for f in range(45):
        ev = world.tic(_keys(fire=True))
        if any(s >= 0 for s in ev.rocket_spawns):
            frames.append(f)
    assert WEAPON_TICS == 2
    # S_MISSILE1 8 + S_MISSILE2 12 tics + A_ReFire: 20 DOOM tics a rocket, at the weapon's two tics a frame
    assert len(frames) >= 4 and {b - a for a, b in zip(frames, frames[1:])} == {10}, frames
    assert ws.p_ammo[gd.AM_MISL] == 10 - len(frames)


def test_the_launcher_does_not_auto_fire_from_its_ready_state(world):
    """DOOM's A_WeaponReady: fire held with attackdown set does not fire the launcher (A_ReFire still refires it)"""
    ws = _ready_launcher(world)
    ws.p_attackdown = 1
    spawned = sum(len(world.tic(_keys(fire=True)).rocket_spawns) for _ in range(12))
    assert spawned == 0 and ws.p_ammo[gd.AM_MISL] == 10
    world.tic(_keys())                                 # released: attackdown off
    assert any(s >= 0 for _ in range(6) for s in world.tic(_keys(fire=True)).rocket_spawns)


def test_out_of_rockets_the_next_weapon_comes_up(world):
    ws = _ready_launcher(world, rockets=1)
    for _ in range(40):
        world.tic(_keys(fire=True))
    assert ws.p_ammo[gd.AM_MISL] == 0 and ws.p_ready == gd.WP_PISTOL       # the pistol, with its 50 bullets


# ---- the rocket ---------------------------------------------------------------------------------------------------------
def _spawn_at(w, px, py, angle):
    ws = w.ws
    ws.px, ws.py, ws.pangle = px, py, angle
    ev = TicEvents(0)
    w._spawn_rocket(ev)
    return ev


def test_the_rocket_spawns_at_the_player_with_twenty_along_the_view(world):
    ws = _fresh(world).ws
    for m in range(world.layout.nmon):                     # nothing in the way
        ws.mon_solid[m] = ws.mon_shootable[m] = 0
    rm = world.rm
    px, py = ws.px + 0x1234, ws.py - 0x8765
    for angle in (0, 0x40000000, 0x12345678, 0xC0000000 + 77):
        ws2 = _fresh(world).ws
        for m in range(world.layout.nmon):
            ws2.mon_solid[m] = ws2.mon_shootable[m] = 0
        ev = _spawn_at(world, px, py, angle)
        s = ev.rocket_spawns[0]
        mx, my = C.fireball_momentum_table(rm, C.ROCKET_INFO)[angle >> rm.angle_shift]
        assert (ws2.proj_momx[s], ws2.proj_momy[s]) == (mx, my)
        assert (mx, my) == PC.momentum_values(rm, C.ROCKET_INFO)[angle >> rm.angle_shift]     # 20 * finecos / finesine
        assert ws2.proj_x[s] == px + (mx >> 1) and ws2.proj_y[s] == py + (my >> 1)
        assert gd.STATE_NAMES[ws2.proj_state[s]] == "S_ROCKET" and ws2.proj_tics[s] == 1
        assert ws2.proj_z[s] == world._knock_z(("player", -1)) + 32 and world._is_rocket(s)


def test_a_full_pool_fizzles_the_rocket_but_spends_it(world):
    ws = _ready_launcher(world)
    for s in range(FIREBALL_POOL):
        ws.proj_active[s] = 1
    ev = TicEvents(0)
    world._a_fire_missile(ev)
    assert ev.rocket_spawns == [-1] and ws.p_ammo[gd.AM_MISL] == 9


def test_the_rocket_hits_a_monster_with_twenties_and_blasts_it(world):
    """a rocket on a monster: the impact ((v % 8) + 1) * 20 on rng_fx, then the explosion's 128 - d -- both blamed on
    the player (infighting's switch turns the monster on him), the rocket the inflictor (the thrust pushes it)"""
    ws = _fresh(world).ws
    m = next(j for j in range(world.layout.nmon) if ws.mon_active[j] and world.mon_info[j].spawnhealth == 150)
    x, y = ws.mon_x[m], ws.mon_y[m]
    ws.px, ws.py = (x - 200) << 16, y << 16
    hits = []
    real_dm = world.damage_monster

    def record_dm(j, dmg, source, inflictor, ev):
        hits.append((j, dmg, source, inflictor))
        real_dm(j, dmg, source, inflictor, ev)
    world.damage_monster = record_dm
    s = 0
    ws.proj_active[s], ws.proj_state[s], ws.proj_tics[s], ws.proj_src[s] = 1, gd.STATE_INDEX["S_ROCKET"], 1, 0
    ws.proj_x[s], ws.proj_y[s] = (x - 40) << 16, y << 16
    ws.proj_momx[s], ws.proj_momy[s] = 20 << 16, 0
    ev = TicEvents(0)
    world._projectiles_phase(ev)
    del world.damage_monster
    assert ev.rocket_hits and ev.rocket_hits[0][:2] == ("mon", m) and ev.rocket_blasts == [s]
    impact, blast = hits[0], hits[1]
    assert impact[0] == m and impact[1] % 20 == 0 and 20 <= impact[1] <= 160
    sx, sy = ws.proj_x[s] >> 16, ws.proj_y[s] >> 16                     # the spot: where the impact stopped it
    assert blast[0] == m and blast[1] == C.BOMB_DAMAGE - max(0, max(abs(x - sx), abs(y - sy)) - world.mon_radius[m])
    assert impact[2] == blast[2] == ("player", -1) and impact[3] == blast[3] == ("proj", s)
    assert ws.mon_target[m] == 1 or ws.mon_health[m] <= 0
    assert gd.STATE_NAMES[ws.proj_state[s]] == "S_EXPLODE1" and not ws.proj_momx[s]


def test_a_point_blank_rocket_hurts_its_shooter(world):
    """DOOM's P_RadiusAttack spares no one: a rocket fired into a wall at point blank blasts the player -- no attacker
    named (himself), the rocket the inflictor (the thrust pushes him back)"""
    ws = _ready_launcher(world)
    for m in range(world.layout.nmon):
        ws.mon_solid[m] = ws.mon_shootable[m] = 0
    # the player 8 units short of the first wall EAST of a monster's spawn point, facing it
    for m in range(world.layout.nmon):
        x, y = world.mon_things[m].x, world.mon_things[m].y
        d = next((k for k in range(0, 600) if world.missile_lines_block((x + k) << 16, y << 16)), None)
        if d and d > 40:
            break
    ws.px, ws.py, ws.pangle = (x + d - 8) << 16, y << 16, 0
    hurt = []
    ev = TicEvents(0)
    real_dp = world.damage_player

    def record_dp(dmg, source, inflictor, e):
        hurt.append((dmg, source, inflictor))
        real_dp(dmg, source, inflictor, e)
    world.damage_player = record_dp
    world._a_fire_missile(ev)
    del world.damage_player
    assert ev.rocket_blasts and hurt and hurt[0][1] == ("player", -1) and hurt[0][2][0] == "proj"
    assert ws.p_health < 100 and ws.p_attacker == 0
    assert ws.p_momx < 0, "the blast at the wall east of him pushes him west"


def test_a_rocket_sets_off_barrels_and_they_blame_the_player(world):
    ws = _fresh(world).ws
    b = 0
    t = world.barrel_things[b]
    s = 0
    ws.proj_active[s], ws.proj_state[s], ws.proj_tics[s] = 1, gd.STATE_INDEX["S_ROCKET"], 1
    ws.proj_x[s], ws.proj_y[s] = (t.x - 30) << 16, t.y << 16
    ws.proj_momx[s] = 20 << 16
    ws.px, ws.py = (t.x - 600) << 16, t.y << 16
    ev = TicEvents(0)
    world._projectiles_phase(ev)
    assert ("bar", b) == ev.rocket_hits[0][:2] or ev.rocket_hits[0][0] == "bar"
    assert ws.bar_health[b] <= 0 and gd.STATE_NAMES[ws.bar_state[b]].startswith("S_BEXP")
    chained = [c for c in range(len(world.barrel_things)) if c != b and ws.bar_health[c] < 20]
    for c in chained:
        assert ws.bar_src[c] in (0, 1)


# ---- R9: the checks above catch a wrong rule ---------------------------------------------------------------------------
def test_control_the_fireballs_damage_on_a_rocket_is_caught(world, monkeypatch):
    sites = world.sites
    monkeypatch.setattr(sites, "rocket_hit", sites.fireball_hit)
    with pytest.raises(AssertionError):
        test_the_rocket_hits_a_monster_with_twenties_and_blasts_it(world)


def test_control_a_launcher_that_auto_fires_is_caught(world, monkeypatch):
    orig = C.CombatMixin._a_weapon_ready

    def autofire(self, keys, ev):
        self.ws.p_attackdown = 0
        orig(self, keys, ev)
    monkeypatch.setattr(C.CombatMixin, "_a_weapon_ready", autofire)
    with pytest.raises(AssertionError):
        test_the_launcher_does_not_auto_fire_from_its_ready_state(world)


def test_control_a_shooter_spared_by_its_blast_is_caught(world, monkeypatch):
    monkeypatch.setattr(World, "player_alive", lambda self: False)
    with pytest.raises(AssertionError):
        test_a_point_blank_rocket_hurts_its_shooter(world)


def test_the_state_export_holds_0_as_a_rockets_shooter():
    # projcode stores pj_src 0 for the player's rocket (its STATE marks it); the oracle's export said 1 -- "monster
    # slot 0" -- because combat stores proj_src 0 for it and the export added 1 to every live slot (fight_gate R1-R3
    # on blocked54 found it). A fireball's slot still exports 1 + its shooter's slot.
    from doomfj.config import GAME_CFG
    from doomfj.monsters import MonsterPhase
    from doomfj.wad import WadFile
    mw = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
    mph = MonsterPhase(mw, "E1M1", gd.SK_HARD, rm=ReferenceModel(GAME_CFG), mode="final", player="final")
    w = mph.world
    ws = w.ws
    ev = _spawn_at(w, ws.px, ws.py, 0x40000000)
    s = ev.rocket_spawns[0]
    assert w._is_rocket(s) and ws.proj_active[s]
    assert mph.proj_state()["pj_src"][s] == 0
    f = next(i for i in range(len(ws.proj_active)) if not ws.proj_active[i])   # a fireball by monster slot 3
    ws.proj_active[f], ws.proj_src[f], ws.proj_state[f] = 1, 3, gd.STATE_INDEX["S_TBALL1"]
    assert mph.proj_state()["pj_src"][f] == 4
