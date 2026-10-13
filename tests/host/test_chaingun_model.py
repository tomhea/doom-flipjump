"""P10 (the owner, 2026-10-12: "add them both [the shotgun and the chaingun], its fun to play with") -- THE CHAINGUN in
the model (gamedata's S_CHAIN* / S_CHAINFLASH* / A_FireCGun / MT_CHAINGUN, combat._a_fire_cgun / CGUN_FLASH, the
SINGLE_PLAYER_EXTRA shotgun #41 and chaingun #40). The fj's side is tests/fj/test_weapon_fj.py (the firing) and
test_give_fj.py (the pickup)."""
import pytest

from doomfj import gamedata as gd
from doomfj import combat as C
from doomfj.things import SINGLE_PLAYER_EXTRA, single_player
from doomfj.world import KEYS, WEAPON_TICS, World

CHAINGUN = (2288, 1024)
SHOTGUN = (864, 896)


def _keys(**on):
    return {k: bool(on.get(k)) for k in KEYS}


@pytest.fixture(scope="module")
def world():
    return World(monsters="final", player="final")


def _fresh(w):
    w.reset(gd.SK_HARD)
    return w


def _ready_chaingun(w, bullets=50):
    """the chaingun up and ready with `bullets`, at the player start (no monster awake near)"""
    ws = _fresh(w).ws
    ws.p_owned[gd.WP_CHAINGUN] = 1
    ws.p_ammo[gd.AM_CLIP] = bullets
    ws.p_ready, ws.p_pending = gd.WP_CHAINGUN, gd.WP_NOCHANGE
    ws.p_wpn_state, ws.p_wpn_tics = gd.STATE_INDEX["S_CHAIN"], 1
    ws.p_wpn_sy, ws.p_attackdown = gd.WEAPONTOP >> 16, 0
    return ws


# ---- the map and the tables -----------------------------------------------------------------------------------------
def test_the_shotgun_and_the_chaingun_are_single_player_things_on_every_skill(world):
    mp = {(t.type, t.x, t.y): t for t in world.mw.things("E1M1") if t.flags & gd.MTF_NOTSINGLE}
    for key in ((2001,) + SHOTGUN, (2002,) + CHAINGUN):
        assert key in SINGLE_PLAYER_EXTRA and key in mp and single_player(mp[key]) and mp[key].flags & 7 == 7
    for sk in (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD):
        world.reset(sk)
        picks = {(t.type, t.x, t.y) for t, taken in zip(world.pickup_things, world.ws.pickup_taken) if not taken}
        assert (2001,) + SHOTGUN in picks and (2002,) + CHAINGUN in picks, sk


def test_the_tables_hold_the_chaingun():
    info = gd.WEAPONINFO[gd.WP_CHAINGUN]
    assert (info.ammo, info.readystate, info.atkstate, info.flashstate) == (gd.AM_CLIP, "S_CHAIN", "S_CHAIN1",
                                                                           "S_CHAINFLASH1")
    assert [gd.STATES[s].tics for s in ("S_CHAIN1", "S_CHAIN2", "S_CHAIN3")] == [4, 4, 0]
    assert C.CGUN_FLASH == {"S_CHAIN1": "S_CHAINFLASH1", "S_CHAIN2": "S_CHAINFLASH2"}
    assert not gd.check_integrity()
    # appended: every state index before P10 is what it was (the frozen runs' state cells keep their meaning)
    assert gd.STATE_INDEX["S_SHOT"] == 211 and gd.STATE_INDEX["S_ROCKET"] == 222 and gd.STATE_INDEX["S_CHAIN"] == 226


# ---- the pickup ---------------------------------------------------------------------------------------------------
def test_the_chaingun_gives_twenty_bullets_and_comes_up(world):
    ws = _fresh(world).ws
    before = ws.p_ammo[gd.AM_CLIP]
    assert world._touch(2002, False, 0, 0)
    assert ws.p_owned[gd.WP_CHAINGUN] and ws.p_ammo[gd.AM_CLIP] == before + 20 and ws.p_pending == gd.WP_CHAINGUN
    ws.p_pending = gd.WP_NOCHANGE
    assert world._touch(2002, False, 0, 0) and ws.p_ammo[gd.AM_CLIP] == before + 40 and ws.p_pending == gd.WP_NOCHANGE
    ws.p_ammo[gd.AM_CLIP] = world.max_ammo(gd.AM_CLIP)
    assert not world._touch(2002, False, 0, 0), "owned and full: nothing to take"


def test_bullets_from_empty_bring_the_chaingun_up_from_the_fist(world):
    ws = _fresh(world).ws
    ws.p_ready, ws.p_ammo[gd.AM_CLIP] = gd.WP_FIST, 0
    assert world._touch(2007, False, 0, 0) and ws.p_pending == gd.WP_PISTOL       # no chaingun: the pistol
    ws.p_pending, ws.p_ammo[gd.AM_CLIP], ws.p_owned[gd.WP_CHAINGUN] = gd.WP_NOCHANGE, 0, 1
    assert world._touch(2007, False, 0, 0) and ws.p_pending == gd.WP_CHAINGUN     # owned: the chaingun


def test_walking_onto_the_chaingun_takes_it(world):
    ws = _fresh(world).ws
    ws.px, ws.py, ws.pangle = (CHAINGUN[0] - 40) << 16, CHAINGUN[1] << 16, 0
    got = []
    for _ in range(4):
        got += world.tic(_keys(forward=True)).pickups
    assert any(k == 2002 for _w, _i, k in got) and ws.p_owned[gd.WP_CHAINGUN]


# ---- key 4 and the firing -------------------------------------------------------------------------------------------
def test_key_4_brings_the_chaingun_up(world):
    ws = _fresh(world).ws
    ws.p_owned[gd.WP_CHAINGUN] = 1
    world.tic(_keys(w4=True))
    assert ws.p_pending == gd.WP_CHAINGUN
    for _ in range(40):
        world.tic(_keys())
    assert ws.p_ready == gd.WP_CHAINGUN and gd.STATE_NAMES[ws.p_wpn_state] == "S_CHAIN"


def test_a_held_trigger_fires_two_bullets_every_four_frames(world):
    """S_CHAIN1 (4 tics) + S_CHAIN2 (4 tics), each A_FireCGun, then A_ReFire: 8 DOOM tics a burst of two, at the weapon's
    two tics a frame"""
    ws = _ready_chaingun(world)
    shots, flashes = [], []
    for f in range(24):
        ev = world.tic(_keys(fire=True))
        shots += [f] * sum(1 for w, *_r in ev.shots if w == "chaingun")
        flashes.append(gd.STATE_NAMES[ws.p_flash_state])
    assert WEAPON_TICS == 2
    assert len(shots) >= 10 and ws.p_ammo[gd.AM_CLIP] == 50 - len(shots)
    per4 = [sum(1 for s in shots if s // 4 == k) for k in range(1, 5)]
    assert per4 == [2, 2, 2, 2], (shots, per4)
    assert {"S_CHAINFLASH1", "S_CHAINFLASH2"} <= set(flashes), "each burst frame shows its own flash frame"


def test_the_first_burst_is_accurate_and_the_held_ones_spread(world):
    ws = _ready_chaingun(world)
    cols = []
    for _ in range(20):
        ev = world.tic(_keys(fire=True))
        cols += [col for w, col, *_r in ev.shots if w == "chaingun"]
    assert cols[0] == cols[1] == world.aim_centre, cols[:4]           # refire 0: both bullets down the middle
    assert len(set(cols[2:])) > 1, "held bursts spread (P_GunShot inaccurate)"


def test_out_of_bullets_the_next_weapon_comes_up(world):
    ws = _ready_chaingun(world, bullets=1)
    ws.p_owned[gd.WP_SHOTGUN], ws.p_ammo[gd.AM_SHELL] = 1, 4
    fired = 0
    for _ in range(40):
        ev = world.tic(_keys(fire=True))
        fired += sum(1 for w, *_r in ev.shots if w == "chaingun")
    assert fired == 1 and ws.p_ammo[gd.AM_CLIP] == 0
    assert ws.p_ready == gd.WP_SHOTGUN, "P_CheckAmmo: the shotgun with shells after the chaingun runs dry"


# ---- the controls (R9) ----------------------------------------------------------------------------------------------
def test_control_a_chaingun_with_one_flash_is_caught(world, monkeypatch):
    """the flash-per-burst check above must see a chaingun whose second burst reuses the first flash"""
    monkeypatch.setitem(C.CGUN_FLASH, "S_CHAIN2", "S_CHAINFLASH1")
    ws = _ready_chaingun(world)
    flashes = set()
    for _ in range(24):
        world.tic(_keys(fire=True))
        flashes.add(gd.STATE_NAMES[ws.p_flash_state])
    assert "S_CHAINFLASH2" not in flashes
