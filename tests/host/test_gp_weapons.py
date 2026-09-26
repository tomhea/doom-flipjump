"""S3b: the player's weapon state machine (`doomfj.combat`, DOOM's p_pspr.c) -- timings, ammo,
switching, the out-of-ammo auto-switch, the number keys and berserk.

The expected numbers are DOOM's, stated here and derived from info.c's tics where they come from:
the pistol comes up 15 tics after the level starts and fires every 14 tics while held, the shotgun
every 37, the fist every 17, the chainsaw every 4; a switch is 16 tics down and 16 up. Each timing
test has a negative control: the same check on a state table with one tic changed must fail."""
import dataclasses

import pytest

from doomfj import gamedata as gd
from doomfj import world as W


def _world(skill=gd.SK_HARD, **kw):
    return W.World(skill=skill, strict=True, **kw)


def _run(w, keys, tics):
    return [w.tic(dict(keys)) for _ in range(tics)]


def _state(w):
    return gd.STATE_NAMES[w.ws.p_wpn_state]


def _ready(w, limit=60):
    """Tick with no keys until the weapon sits in its ready state."""
    for _ in range(limit):
        if _state(w) == gd.WEAPONINFO[w.ws.p_ready].readystate:
            return
        w.tic({})
    raise AssertionError("weapon never became ready: %s" % _state(w))


def _give(w, weapon, ammo=None):
    ws = w.ws
    ws.p_owned[weapon] = 1
    if ammo is not None:
        ws.p_ammo[gd.WEAPONINFO[weapon].ammo] = ammo


def _switch_to(w, weapon):
    key = W.WEAPON_KEYS[0 if weapon == gd.WP_CHAINSAW else weapon]
    w.tic({key: True})
    _ready(w)
    assert w.ws.p_ready == weapon


def _attack_tics(evs, weapon):
    return [ev.tic for ev in evs for s in ev.shots if s[0] == weapon]


# ---- level start: P_SetupPsprites -------------------------------------------------------------
def test_the_pistol_comes_up_like_p_setuppsprites():
    """sy starts at WEAPONBOTTOM - RAISESPEED (the raise already ran once) and rises 6 a tic; the
    ready state is entered on tic 14 (15 A_Raise calls from 128 to 32)."""
    w = _world()
    trace = []
    for _ in range(15):
        w.tic({})
        trace.append((w.ws.p_wpn_sy, _state(w)))
    assert [sy for sy, _ in trace] == list(range(116, 31, -6))
    assert [s for _, s in trace] == ["S_PISTOLUP"] * 14 + ["S_PISTOL"]


# ---- fire rates ----------------------------------------------------------------------------------
def test_the_pistol_fires_every_14_tics_and_only_the_first_shot_is_accurate():
    w = _world()
    evs = _run(w, {"fire": True}, 61)
    shots = [(ev.tic, s) for ev in evs for s in ev.shots]
    assert [t for t, _ in shots] == [18, 32, 46, 60]        # ready at 14, S_PISTOL1 is 4 tics
    assert shots[0][1][1] == w.aim_centre                    # P_GunShot (mo, !refire)
    assert [ev.tic for ev in evs if ev.fired] == [14, 28, 42, 56]      # P_FireWeapon: the noise
    assert w.ws.p_ammo[gd.AM_CLIP] == 50 - 4 and w.ws.p_refire == 3
    w.tic({})                                                # release: A_ReFire clears refire
    for _ in range(20):
        w.tic({})
    assert w.ws.p_refire == 0


def test_the_timing_check_fails_on_a_changed_state_table(monkeypatch):
    """R9: one tic more in S_PISTOL3 must move every later shot."""
    monkeypatch.setitem(gd.STATES, "S_PISTOL3",
                        dataclasses.replace(gd.STATES["S_PISTOL3"], tics=5))
    w = _world()
    assert _attack_tics(_run(w, {"fire": True}, 61), "pistol") != [18, 32, 46, 60]


def test_the_shotgun_fires_7_pellets_every_37_tics_for_one_shell():
    w = _world()
    _give(w, gd.WP_SHOTGUN, ammo=10)
    _switch_to(w, gd.WP_SHOTGUN)
    evs = _run(w, {"fire": True}, 80)
    blasts = sorted({t for t in _attack_tics(evs, "shotgun")})
    assert len(blasts) >= 2 and {b - a for a, b in zip(blasts, blasts[1:])} == {37}
    assert all(len(ev.shots) == 7 for ev in evs if ev.shots)
    assert w.ws.p_ammo[gd.AM_SHELL] == 10 - len(blasts)


def test_the_fist_punches_every_17_tics_and_the_chainsaw_cuts_every_4():
    w = _world()
    _switch_to(w, gd.WP_FIST)
    punches = _attack_tics(_run(w, {"fire": True}, 60), "fist")
    assert len(punches) >= 3 and {b - a for a, b in zip(punches, punches[1:])} == {17}
    w = _world()
    _give(w, gd.WP_CHAINSAW)
    _switch_to(w, gd.WP_CHAINSAW)
    cuts = _attack_tics(_run(w, {"fire": True}, 30), "chainsaw")
    assert len(cuts) >= 6 and {b - a for a, b in zip(cuts, cuts[1:])} == {4}


# ---- switching -----------------------------------------------------------------------------------
def test_a_switch_is_16_tics_down_and_16_up():
    """The key sets pendingweapon on tic t; A_WeaponReady sends the pistol down the same tic; A_Lower
    reaches the bottom on tic t+15, where P_BringUpWeapon raises the fist at once (A_Raise runs on
    entering S_PUNCHUP), and A_Raise tops out on t+30."""
    w = _world()
    _ready(w)
    t0 = w.tic_count
    w.tic({"w1": True})
    sys_ = [w.ws.p_wpn_sy]
    states = [_state(w)]
    while _state(w) != "S_PUNCH":
        w.tic({})
        sys_.append(w.ws.p_wpn_sy)
        states.append(_state(w))
    assert w.tic_count - 1 - t0 == 30
    assert sys_[:15] == list(range(38, 123, 6))                         # down, 6 a tic
    assert sys_[15:] == list(range(122, 31, -6))                        # ... and up again
    assert states[15] == "S_PUNCHUP" and w.ws.p_ready == gd.WP_FIST


def test_the_number_keys_pick_only_owned_weapons():
    w = _world()
    _ready(w)
    ws = w.ws
    w.tic({"w3": True})
    assert ws.p_pending == gd.WP_NOCHANGE                   # no shotgun yet
    w.tic({"w4": True})
    assert ws.p_pending == gd.WP_NOCHANGE                   # no chaingun on E1M1
    _give(w, gd.WP_SHOTGUN, ammo=4)
    w.tic({"w3": True, "w1": True})                         # the LOWEST key wins: 1, the fist
    assert ws.p_pending == gd.WP_FIST


def test_key_1_prefers_the_chainsaw_unless_holding_it_with_berserk():
    w = _world()
    _give(w, gd.WP_CHAINSAW)
    _switch_to(w, gd.WP_CHAINSAW)                           # "1" gives the saw
    w.tic({"w1": True})
    assert w.ws.p_pending == gd.WP_NOCHANGE                 # already holding it
    w.ws.p_strength = 1
    w.tic({"w1": True})
    assert w.ws.p_pending == gd.WP_FIST                     # saw + berserk: "1" is the fist


def test_running_dry_switches_by_dooms_preference():
    """P_CheckAmmo from A_ReFire: no bullets -> the shotgun if it has shells, else the chainsaw if
    owned, else the fist. Checked for each branch (the negative control is the other branches)."""
    for extra, want in (({}, gd.WP_FIST), ({gd.WP_CHAINSAW: None}, gd.WP_CHAINSAW),
                        ({gd.WP_CHAINSAW: None, gd.WP_SHOTGUN: 4}, gd.WP_SHOTGUN)):
        w = _world()
        _ready(w)
        w.ws.p_ammo[gd.AM_CLIP] = 1
        for wp, ammo in extra.items():
            _give(w, wp, ammo)
        _run(w, {"fire": True}, 80)
        assert w.ws.p_ready == want and w.ws.p_ammo[gd.AM_CLIP] == 0, (extra, w.ws.p_ready)


# ---- berserk -------------------------------------------------------------------------------------
@pytest.mark.parametrize("skill,present", [(gd.SK_EASY, True), (gd.SK_MEDIUM, True),
                                           (gd.SK_HARD, False)])
def test_berserk_is_on_easy_and_medium_only(skill, present):
    w = _world(skill)
    idx = [i for i, t in enumerate(w.pickup_things) if t.type == 2023]
    assert len(idx) == 1
    assert (w.ws.pickup_taken[idx[0]] == 0) == present      # other skills: born "taken"


def test_berserk_heals_switches_to_the_fist_and_multiplies_punches_by_ten():
    w = _world(gd.SK_MEDIUM)
    ws = w.ws
    ws.p_health = 40
    assert w._touch(2023, False, 0, 0)
    assert ws.p_health == 100 and ws.p_strength == 1 and ws.p_pending == gd.WP_FIST
    _ready(w)
    assert ws.p_ready == gd.WP_FIST
    got = []
    w.aim = lambda world, col: None                         # nothing to hit: just read the roll
    for ev in _run(w, {"fire": True}, 40):
        got += [s[3] for s in ev.shots]
    k, table = w.sites.punch
    assert got and all(d % 10 == 0 and 20 <= d <= 200 for d in got)
    assert set(d // 10 for d in got) <= {v[0] for v in table}      # 10 x the punch table


# ---- the shot's noise (supersedes S3a's `fire`-is-noise placeholder) --------------------------------
def _open_all_doors(w):
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = w.door_nstates[si] - 1
    w._door_phase_scene()


def test_the_shot_is_the_noise_a_monster_hears():
    """P_FireWeapon's P_NoiseAlert: no noise while the pistol rises, the first at tic 14 (the fire
    decision), and it wakes monsters by SOUND once doors let it carry. At the spawn the doors are
    shut and the three monsters in the start region see the player first (tics 0 and 5), which is
    why S3a's 12-tic version of this test cannot hold under DOOM's weapon timing. Control: the same
    tics without fire wake no one by sound."""
    w = _world()
    _open_all_doors(w)
    evs = _run(w, {"fire": True}, 60)
    assert [ev.tic for ev in evs if ev.noise][:1] == [14]
    assert any(how == "sound" for ev in evs for _m, how in ev.wakes)
    w = _world()
    _open_all_doors(w)
    assert not any(how == "sound" for ev in _run(w, {}, 60) for _m, how in ev.wakes)


def test_the_aim_box_is_doom_s_diagonal_width():
    """aim_radius (docs/gp-aim-window.md 1.7): r on an axis, round(1.414 r) at 45 degrees, from the
    view angle's top AIM_REFF_BITS bits. Control: a plain radius would read r at 45 degrees too."""
    from doomfj import combat as C
    rm = _world().rm
    for r in (10, 20, 30):
        assert C.CombatMixin.aim_radius(rm, 0, r) == r
        assert C.CombatMixin.aim_radius(rm, 0x40000000, r) == r
        assert C.CombatMixin.aim_radius(rm, 0x20000000, r) == round(r * 2 ** 0.5)
        assert C.CombatMixin.aim_radius(rm, 0x20000000, r) != r            # the control
    # the lookup quantizes: every angle in one top-bits bucket gives the same width
    lo = 0x20000000
    assert {C.CombatMixin.aim_radius(rm, lo + d, 20) for d in (0, 1, 1 << 23, (1 << 24) - 1)} == {28}

