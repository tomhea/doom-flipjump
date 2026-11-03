"""M8 C6 -- THE PLASMA RIFLE in the model (doomfj.combat's M8 C6 conventions; gamedata's MT_PLASMA / S_PLASMA* /
S_PLASBALL* / S_PLASEXP* and the state GHOSTS), on tests/fixtures/plasma_wad.py's E1M1 with a rifle (no real plasma map
builds yet: E1M6 and E1M9 wait for the runtime ids, cluster C1). The fj's side is tests/fj/test_plasma_fj.py."""
import pytest

from doomfj import combat as C
from doomfj import gamedata as gd
from doomfj import projcode as PC
from doomfj.reference_model import ReferenceModel
from doomfj.world import FIREBALL_POOL, KEYS, WEAPON_TICS, TicEvents, World
from tests.fixtures.plasma_wad import plasma_e1m1


def _keys(**on):
    return {k: bool(on.get(k)) for k in KEYS}


@pytest.fixture(scope="module")
def world():
    return World(plasma_e1m1(), "E1M1", monsters="final", player="final")


def _fresh(w):
    w.reset(gd.SK_HARD)
    return w


def _ready_rifle(w, cells=40):
    """the rifle up and ready with `cells`, the player at his start (no monster awake near)"""
    ws = _fresh(w).ws
    ws.p_owned[gd.WP_PLASMA] = 1
    ws.p_ammo[gd.AM_CELL] = cells
    ws.p_ready, ws.p_pending = gd.WP_PLASMA, gd.WP_NOCHANGE
    ws.p_wpn_state, ws.p_wpn_tics = gd.STATE_INDEX["S_PLASMA"], 1
    ws.p_wpn_sy, ws.p_attackdown = gd.WEAPONTOP >> 16, 0
    return ws


# ---- the tables and the GHOSTS --------------------------------------------------------------------------------------
def test_the_tables_hold_doom_s_plasma_rifle():
    p = C.PLASMA_INFO
    assert (p.speed, p.radius, p.height, p.damage) == (25 << 16, 13 << 16, 8 << 16, 5)
    assert (p.spawnstate, p.deathstate) == ("S_PLASBALL", "S_PLASEXP")
    w = gd.WEAPONINFO[gd.WP_PLASMA]
    assert (w.ammo, w.upstate, w.downstate, w.readystate, w.atkstate, w.flashstate) == (
        gd.AM_CELL, "S_PLASMAUP", "S_PLASMADOWN", "S_PLASMA", "S_PLASMA1", "S_PLASMAFLASH1")
    s = gd.STATES
    assert [s[n].tics for n in C._state_chain("S_PLASEXP")] == [4] * 5 and s["S_PLASBALL"].next == "S_PLASBALL2"
    # info.c's S_PLASMA2 (20 tics, A_ReFire) is two states of 10: one picture, one A_ReFire, 20 tics
    assert (s["S_PLASMA2"].tics + s["S_PLASMA2B"].tics, s["S_PLASMA2"].action, s["S_PLASMA2B"].action) == (
        20, "A_ReFire", None) and s["S_PLASMA2"].frame == s["S_PLASMA2B"].frame == 1
    assert C.PLASMA_R == C.FIREBALL_R == 6 and not gd.check_integrity()


def plasma_damage_ok(table) -> bool:
    """the ball's impact table is DOOM's ((P_Random()%8)+1)*5: exactly the values 5..40 in fives"""
    return sorted(set(table)) == list(range(5, 45, 5))


def test_the_ball_s_damage_table_is_fives():
    w_sites = C.Sites(ReferenceModel())
    assert plasma_damage_ok(w_sites.plasma_hit[1]) and w_sites.plasma_hit[0] == 1
    assert C.site_formulas(lambda v: 0)["plasma_hit"][1](13) == (13 % 8 + 1) * 5
    assert sorted(set(w_sites.plasma_flash[1])) == [0, 1]


def test_r9_the_rocket_s_table_is_not_the_ball_s():
    assert not plasma_damage_ok(C.Sites(ReferenceModel()).rocket_hit[1])


def test_the_plasma_states_take_the_ghost_indices_and_nothing_else_moved():
    """the 15 states sit on the raise states' indices; every live index before them is what it was (the frozen runs'
    state cells keep their meaning) and the decode table still fits a byte"""
    assert len(gd.STATE_NAMES) == 246 and len(gd.STATE_GHOSTS) == 15
    for ghost, live in gd.STATE_GHOSTS.items():
        assert "_RAISE" in ghost and gd.STATE_INDEX[ghost] == gd.STATE_INDEX[live]
        assert gd.STATE_NAMES[gd.STATE_INDEX[live]] == live
    assert gd.STATE_INDEX["S_SHOT"] == 211 and gd.STATE_INDEX["S_ROCKET"] == 222 and gd.STATE_INDEX["S_TFOG"] == 0xEA
    assert gd.STATE_INDEX["S_POSS_RAISE1"] == 0x69 and gd.STATE_NAMES[0x69] == "S_PLASMA"


def _domains():
    """every table domain a state index keys (the fj's tables and the model's cells), with the plasma on"""
    from doomfj import monstercode as MC
    from doomfj import weaponcode as WC
    from doomfj.barrelcode import barrel_states
    return {"monster": MC.monster_states(), "pool": PC.pool_states(True, True, True, plasma=True),
            "weapon": WC.weapon_states(plasma=True), "barrel": barrel_states(),
            "player": [n for n in gd.STATE_NAMES if n.startswith("S_PLAY")]}


def domain_collisions(domains, index=None):
    """[(domain, index, names)] where two states of ONE domain share an index (a table keyed by the index would hold
    two rows in one place); `index` the name -> index map (gamedata's by default: the controls plant another)"""
    index = gd.STATE_INDEX if index is None else index
    bad = []
    for d, names in domains.items():
        by = {}
        for n in names:
            by.setdefault(index[n], []).append(n)
        bad += [(d, i, ns) for i, ns in by.items() if len(ns) > 1]
    return bad


def test_every_table_domain_is_injective_and_no_ghost_is_live():
    dom = _domains()
    assert not domain_collisions(dom)
    live = {n for d in ("pool", "weapon", "barrel", "player") for n in dom[d]}
    assert not live & set(gd.STATE_GHOSTS), "a ghost reachable outside the monster tables"
    assert set(gd.STATE_GHOSTS.values()) <= live, "every plasma state lives in a pool or weapon table"
    assert set(gd.STATE_GHOSTS) <= set(dom["monster"]), "the ghosts' rows stay in the monster table (E1M1's text)"


def test_r9_a_plasma_state_on_a_live_index_of_its_domain_is_caught():
    """R9: the ball moved onto the rocket's index collides in the POOL domain; the rifle's ready state onto the
    pistol's in the WEAPON domain -- both caught"""
    idx = dict(gd.STATE_INDEX)
    idx["S_PLASBALL"] = idx["S_ROCKET"]
    assert domain_collisions(_domains(), idx)
    idx2 = dict(gd.STATE_INDEX)
    idx2["S_PLASMA"] = idx2["S_PISTOL"]
    assert domain_collisions(_domains(), idx2)


# ---- the map rule and key 6 -------------------------------------------------------------------------------------------
def test_plasma_is_on_exactly_where_a_rifle_lies(world):
    assert world.layout.plasma == 1 and "kb_w6" in {f.name for f in world.schema}
    e1m1 = World(monsters="final", player="final")
    assert e1m1.layout.plasma == 0 and "kb_w6" not in {f.name for f in e1m1.schema}
    assert not C.plasma_on(e1m1.mw.things("E1M1")) and C.plasma_on(world.mw.things("E1M1"))
    assert "kb_w6" not in world.restart_fields, "key 6 is input state: the restart leaves it"
    names = [f.name for f in e1m1.schema]
    assert names[names.index("kb_w5") + 1] == "px", "E1M1's schema is the one every frozen digest was recorded with"


def test_key_6_brings_the_rifle_up(world):
    ws = _fresh(world).ws
    world.tic(_keys(w6=True))
    assert ws.p_pending == gd.WP_NOCHANGE, "not owned: nothing"
    ws.p_owned[gd.WP_PLASMA], ws.p_ammo[gd.AM_CELL] = 1, 40
    world.tic(_keys(w6=True))
    assert ws.p_pending == gd.WP_PLASMA
    for _ in range(40):
        world.tic(_keys())
    assert ws.p_ready == gd.WP_PLASMA and gd.STATE_NAMES[ws.p_wpn_state] == "S_PLASMA"
    ws2 = _fresh(world).ws
    ws2.p_owned[gd.WP_PLASMA] = ws2.p_owned[gd.WP_SHOTGUN] = 1
    world.tic(_keys(w3=True, w6=True))                 # the LOWEST held key names the weapon
    assert ws2.p_pending == gd.WP_SHOTGUN


# ---- the pickups ---------------------------------------------------------------------------------------------------
def test_the_rifle_gives_forty_cells_and_comes_up(world):
    ws = _fresh(world).ws
    assert world._touch(2004, False, 0, 0)
    assert ws.p_owned[gd.WP_PLASMA] and ws.p_ammo[gd.AM_CELL] == 40 and ws.p_pending == gd.WP_PLASMA
    ws.p_pending = gd.WP_NOCHANGE
    assert world._touch(2004, False, 0, 0) and ws.p_ammo[gd.AM_CELL] == 80 and ws.p_pending == gd.WP_NOCHANGE
    ws.p_ammo[gd.AM_CELL] = world.max_ammo(gd.AM_CELL)
    assert not world._touch(2004, False, 0, 0), "owned and full: nothing to take"


def test_cells_from_empty_bring_the_rifle_up_from_the_fist_or_the_pistol(world):
    ws = _fresh(world).ws
    assert world._touch(2047, False, 0, 0) and ws.p_ammo[gd.AM_CELL] == 20 and ws.p_pending == gd.WP_NOCHANGE
    for ready in (gd.WP_FIST, gd.WP_PISTOL, gd.WP_SHOTGUN):
        ws = _fresh(world).ws
        ws.p_owned[gd.WP_PLASMA] = ws.p_owned[gd.WP_SHOTGUN] = 1
        ws.p_ready = ready
        assert world._touch(17, False, 0, 0) and ws.p_ammo[gd.AM_CELL] == 100
        assert ws.p_pending == (gd.WP_PLASMA if ready != gd.WP_SHOTGUN else gd.WP_NOCHANGE), ready


def test_walking_onto_the_rifle_takes_it(world):
    ws = _fresh(world).ws
    got = []
    for _ in range(8):
        got += world.tic(_keys(forward=True)).pickups
    assert any(k == 2004 for _w, _i, k in got) and ws.p_owned[gd.WP_PLASMA] and ws.p_ammo[gd.AM_CELL] >= 40, got


# ---- the firing ---------------------------------------------------------------------------------------------------------
def test_a_held_trigger_fires_a_ball_every_three_tics(world):
    ws = _ready_rifle(world)
    shots = []
    for f in range(12):
        ev = world.tic(_keys(fire=True))
        shots.append(len(ev.plasma_spawns))
    assert WEAPON_TICS == 2
    # S_PLASMA1's 3 tics, then A_ReFire on entering S_PLASMA2 fires again: a ball every 3 weapon tics, 2 tics a frame
    assert sum(shots) == 8 and ws.p_ammo[gd.AM_CELL] == 32, shots


def test_a_released_trigger_waits_twenty_tics(world):
    """S_PLASMA2 + S_PLASMA2B: 20 tics of PLSG B after a release before S_PLASMA's A_WeaponReady fires again"""
    ws = _ready_rifle(world)
    fired = [bool(world.tic(_keys(fire=True)).plasma_spawns)]           # tic 0 fires (S_PLASMA1, tics 0..2)
    for f in range(1, 20):
        fired.append(bool(world.tic(_keys(fire=f >= 2)).plasma_spawns))
    # frame 1 (tics 2, 3): S_PLASMA2 entered at tic 3, fire released -- 20 tics; S_PLASMA at tic 23 (frame 11) fires
    assert fired.index(True, 1) == 11, fired
    assert gd.STATE_NAMES[ws.p_wpn_state] in ("S_PLASMA1", "S_PLASMA2", "S_PLASMA2B")


def test_the_flash_is_flashstate_plus_a_player_draw(world):
    ws = _ready_rifle(world)
    flashes = set()
    for _ in range(40):
        rng0 = ws.rng_player
        ev = world.tic(_keys(fire=True))
        if ev.plasma_spawns:
            flashes.add(gd.STATE_NAMES[ws.p_flash_state])
            assert ws.rng_player != rng0, "A_FirePlasma draws on the player's stream"
    assert flashes == {"S_PLASMAFLASH1", "S_PLASMAFLASH2"}


def test_out_of_cells_the_next_weapon_comes_up(world):
    ws = _ready_rifle(world, cells=1)
    for _ in range(40):
        world.tic(_keys(fire=True))
    assert ws.p_ammo[gd.AM_CELL] == 0 and ws.p_ready == gd.WP_PISTOL       # the pistol, with its 50 bullets


def test_with_cells_the_rifle_is_doom_s_first_preference(world):
    ws = _fresh(world).ws
    ws.p_owned[gd.WP_PLASMA], ws.p_ammo[gd.AM_CELL] = 1, 20
    ws.p_ammo[gd.AM_CLIP] = 0
    for _ in range(40):                                # the pistol, no bullets: P_CheckAmmo picks
        world.tic(_keys(fire=True))
    assert ws.p_ready == gd.WP_PLASMA and ws.p_ammo[gd.AM_CELL] < 20


# ---- the ball ---------------------------------------------------------------------------------------------------------
def _spawn_at(w, px, py, angle):
    ws = w.ws
    ws.px, ws.py, ws.pangle = px, py, angle
    ev = TicEvents(0)
    w._spawn_plasma(ev)
    return ev


def test_the_ball_spawns_at_the_player_with_twenty_five_along_the_view(world):
    rm = ReferenceModel()
    for ang in (0, 0x40000000, 0x12345678):
        ws = _fresh(world).ws
        rng0 = ws.rng_fx
        ev = _spawn_at(world, -416 << 16, 256 << 16, ang)
        s = ev.plasma_spawns[0]
        i = ang >> rm.angle_shift
        mx, my = world.plasma_mom[i]
        assert (mx, my) == PC.momentum_values(rm, C.PLASMA_INFO)[i]
        assert ws.proj_src[s] == 0 and gd.STATE_NAMES[ws.proj_state[s]] == "S_PLASBALL" and 3 <= ws.proj_tics[s] <= 6
        assert ws.rng_fx == (rng0 + 1) & 0xFF
        assert ws.proj_x[s] == C._signed((-416 << 16) + (mx >> 1), 32)


def test_a_full_pool_fizzles_the_ball(world):
    ws = _fresh(world).ws
    for s in range(FIREBALL_POOL):
        ws.proj_active[s] = 1
    assert _spawn_at(world, -416 << 16, 256 << 16, 0).plasma_spawns == [-1]


def _monster_east_of(w, gap):
    """an imp, the player put `gap` units west of it facing east, nothing else shootable or solid"""
    ws = w.ws
    m = next(j for j in range(w.layout.nmon) if ws.mon_active[j] and w.mon_things[j].type == 3001)
    for j in range(w.layout.nmon):
        if j != m:
            ws.mon_solid[j] = ws.mon_shootable[j] = 0
    for b in range(len(w.barrel_things)):
        ws.bar_state[b] = ws.bar_solid[b] = 0
    return m, ((ws.mon_x[m] - gap) << 16, ws.mon_y[m] << 16)


def test_the_ball_hits_a_monster_with_fives_and_does_not_blast(world):
    ws = _fresh(world).ws
    m, (px, py) = _monster_east_of(world, 60)
    hp0 = ws.mon_health[m]
    ev = _spawn_at(world, px, py, 0)
    for _ in range(4):
        if ev.plasma_hits:
            break
        world._projectiles_phase(ev)
    assert ev.plasma_hits and ev.plasma_hits[0][:2] == ("mon", m), ev.plasma_hits
    dmg = ev.plasma_hits[0][2]
    assert dmg % 5 == 0 and 5 <= dmg <= 40 and ws.mon_health[m] == hp0 - dmg
    assert not ev.rocket_blasts and not ev.rocket_hits
    s = ev.plasma_spawns[0]
    assert gd.STATE_NAMES[ws.proj_state[s]] == "S_PLASEXP" and 1 <= ws.proj_tics[s] <= 4
    assert ws.mon_target[m] == 1, "hurt by the player: the player is its target"


def test_the_explosion_runs_its_five_states_and_frees_the_slot(world):
    ws = _fresh(world).ws
    ev = _spawn_at(world, -416 << 16, 256 << 16, 0x80000000)        # west, into the start room's wall
    s = ev.plasma_spawns[0]
    seen = []
    for _ in range(80):
        world._projectiles_phase(ev)
        if not ws.proj_active[s]:
            break
        seen.append(gd.STATE_NAMES[ws.proj_state[s]])
    assert not ws.proj_active[s] and s in ev.proj_walls
    assert [n for n in dict.fromkeys(seen) if n.startswith("S_PLASEXP")] == list(C._state_chain("S_PLASEXP"))


def test_the_ghost_indices_are_the_plasma_s_and_no_thing_alias_may_borrow_them():
    """GHOST_INDICES: the raise rows the monster tables keep -- exactly the plasma states' indices; a thing-domain alias
    (M8 C8's THING_STATE_INDEX, when merged) must take none of them"""
    assert gd.GHOST_INDICES == {gd.STATE_INDEX[n] for n in gd.STATE_GHOSTS.values()}
    alias = getattr(gd, "THING_STATE_INDEX", None)
    if alias is not None:
        ext = [n for n in alias if n not in gd.STATE_INDEX]
        assert not {alias[n] for n in ext} & gd.GHOST_INDICES
