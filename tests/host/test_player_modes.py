"""M7 P4.1 -- the player's model modes (docs/gp-combat.md section 1): "fire" runs the weapon keys, the psprite machine,
ammo, refire and every `rng_player` draw of the full model, and applies nothing. So with the monsters idle (nothing
hurts the player), "fire" and "full" must agree on EVERY weapon field and on the player's stream at EVERY tic of a
script that switches weapons, taps and holds the trigger, runs a gun dry and punches -- the full model's hits land on
the monsters' own streams, never the player's. The next rung adds effects without moving a roll (the P3.2c rule).

R9: a "fire" mode whose shots draw nothing parts on `rng_player` at the first shot.
"""
import random

import pytest

from doomfj import gamedata as gd
from doomfj.world import KEYS, World

WEAPON_FIELDS = ("p_ready", "p_pending", "p_wpn_state", "p_wpn_tics", "p_wpn_sy", "p_flash_state", "p_flash_tics",
                 "p_refire", "p_attackdown", "rng_player")


def _script(seed=4, n=400):
    rng = random.Random(seed)
    keys, fire = [], False
    for t in range(n):
        if rng.random() < 0.08:
            fire = not fire                                   # hold the trigger for a while, then let go
        k = {name: False for name in KEYS}
        k["fire"] = fire or rng.random() < 0.05               # and taps
        if rng.random() < 0.04:
            k[rng.choice(("w1", "w2", "w3", "w4"))] = True
        k["turn_left"] = rng.random() < 0.1
        keys.append(k)
    return keys


def _world(player):
    w = World(skill=gd.SK_HARD, monsters="idle", player=player)
    ws = w.ws
    ws.p_owned[gd.WP_SHOTGUN] = 1                             # every E1M1 weapon reachable from the keys
    ws.p_owned[gd.WP_CHAINSAW] = 1
    ws.p_ammo[gd.AM_SHELL] = 9
    ws.p_ammo[gd.AM_CLIP] = 30                                # so the pistol runs dry inside the script
    return w


def _snap(w):
    ws = w.ws
    return {f: getattr(ws, f) for f in WEAPON_FIELDS} | {"ammo": tuple(ws.p_ammo)}


def test_fire_mode_is_the_full_weapon():
    a, b = _world("fire"), _world("full")
    shots = 0
    for t, k in enumerate(_script()):
        ea, eb = a.tic(k), b.tic(k)
        assert _snap(a) == _snap(b), "tic %d: %s" % (t, {f: (_snap(a)[f], _snap(b)[f]) for f in _snap(a)
                                                         if _snap(a)[f] != _snap(b)[f]})
        assert [s[:2] + s[3:] for s in ea.shots] == [s[:2] + s[3:] for s in eb.shots], t   # same column + damage
        shots += len(ea.shots)
    assert shots > 20, "the script fired only %d shots" % shots
    assert all(s[2] is None for e in a.events for s in e.shots), "a fire-mode shot resolved a target"


def test_fire_mode_applies_nothing():
    """no noise, no hit, no player-thing state: the monsters and the player thing are the walk mode's"""
    a, b = _world("fire"), _world("walk")
    for k in _script(seed=9, n=200):
        a.tic(k), b.tic(k)
    assert [list(getattr(a.ws, f)) for f in ("mon_state", "mon_health", "mon_target")] == \
           [list(getattr(b.ws, f)) for f in ("mon_state", "mon_health", "mon_target")]
    assert a.ws.p_mobj_state == b.ws.p_mobj_state


def test_walk_mode_has_no_weapon():
    w = _world("walk")
    s0 = _snap(w)
    for k in _script(seed=2, n=100):
        w.tic(k)
    assert _snap(w) == s0


def test_the_control_a_silent_gun_parts_on_the_stream(monkeypatch):
    """R9: the shot's draws are what this test pins -- a fire mode that rolls nothing must part"""
    from doomfj.combat import CombatMixin
    orig = CombatMixin._roll

    def silent(self, stream, site, idx=None):
        if self.player == "fire" and stream == "rng_player":
            return (5, self.aim_centre) if site[0] == 3 else 5   # the outcome, without advancing the stream
        return orig(self, stream, site, idx)
    monkeypatch.setattr(CombatMixin, "_roll", silent)
    a, b = _world("fire"), _world("full")
    parted = None
    for t, k in enumerate(_script()):
        a.tic(k), b.tic(k)
        if a.ws.rng_player != b.ws.rng_player:
            parted = t
            break
    assert parted is not None, "a gun that draws nothing went unnoticed"
