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


# ---- M7 P4.2a: "shoot" -- the shot resolves through the aim and hurts the monsters (damage, pain, death), with no
# noise, no effect, no barrel, no drop. With idle monsters (they hear nothing and chase nothing) and the player facing
# a monster, "shoot" equals "full" on the player's stream and EVERY monster cell damage touches, at every tic, until
# the first tic the full model's shot finds a barrel (none in these setups: asserted).
MON_FIELDS = ("mon_health", "mon_state", "mon_tics", "mon_rng", "mon_shootable", "mon_justhit", "mon_threshold",
              "mon_target", "mon_reaction")


def _facing(player, kind):
    """a world whose player stands 110 units from a monster of `kind`, facing it -- the first (monster, side) whose
    centre column the geometric aim names that monster in -- with the shotgun"""
    w = World(skill=gd.SK_HARD, monsters="idle", player=player)
    ws = w.ws
    for m in (i for i in range(w.layout.nmon) if ws.mon_active[i] and w.mon_info[i].name == kind):
        for dx, dy, ang in ((-110, 0, 0), (110, 0, 0x80000000), (0, -110, 0x40000000), (0, 110, 0xC0000000)):
            ws.px, ws.py, ws.pangle = (ws.mon_x[m] + dx) << 16, (ws.mon_y[m] + dy) << 16, ang
            if w.aim_geometric(w, w.aim_centre) == ("mon", m):
                ws.p_owned[gd.WP_SHOTGUN] = 1
                ws.p_ammo[gd.AM_SHELL] = 20
                return w, m
    raise AssertionError("no %s can be faced from 110 units" % kind)


def _trigger(n=320):
    out = []
    for t in range(n):
        k = {name: False for name in KEYS}
        k["fire"] = (t % 45) < 32
        k["w3"] = t == 120                                    # the shotgun for the second half
        out.append(k)
    return out


def _mon_snap(w):
    return {f: tuple(getattr(w.ws, f)) for f in MON_FIELDS} | {"rng_player": w.ws.rng_player}


@pytest.mark.parametrize("kind", ["MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP", "MT_SERGEANT"])
def test_shoot_mode_hurts_as_the_full_model(kind):
    a, m = _facing("shoot", kind)
    b, _ = _facing("full", kind)
    hits = 0
    for t, k in enumerate(_trigger()):
        ea, eb = a.tic(k), b.tic(k)
        assert not any(h[1] == "bar" for h in eb.hits), "tic %d: the full model shot a barrel" % t
        sa, sb = _mon_snap(a), _mon_snap(b)
        assert sa == sb, "tic %d: %s" % (t, sorted(f for f in sa if sa[f] != sb[f]))
        hits += len(ea.hits)
    assert hits >= 1 and a.ws.mon_health[m] <= 0, (kind, hits, a.ws.mon_health[m])   # it was hit, and it died
    assert not any(a.ws.mon_drop), "a shoot-mode kill dropped something (drops are P6's)"


def test_the_control_a_painless_shoot_mode_parts(monkeypatch):
    """R9: a "shoot" mode that never draws the pain roll parts from the full model on the monster's stream"""
    from doomfj.combat import CombatMixin
    orig = CombatMixin._roll

    def no_pain(self, stream, site, idx=None):
        if self.player == "shoot" and stream == "mon_rng" and site in self.sites.pain.values():
            return 0
        return orig(self, stream, site, idx)
    monkeypatch.setattr(CombatMixin, "_roll", no_pain)
    a, _m = _facing("shoot", "MT_SERGEANT")
    b, _ = _facing("full", "MT_SERGEANT")
    for t, k in enumerate(_trigger()):
        a.tic(k), b.tic(k)
        if _mon_snap(a) != _mon_snap(b):
            return
    raise AssertionError("a painless shoot mode went unnoticed")


# ---- M7 P4.2b: "hit" -- "shoot" plus the shot's NOISE (P_NoiseAlert, combat._fire_weapon). What "full" adds over "hit"
# is exactly: the player thing's states (S_PLAY_ATK1/2: no monster reads them), the effects (puffs and blood -- the
# rng_fx stream and the fx pool: no monster reads them), the BARRELS in the aim (a barrel shot, and its blast, hurts
# monsters) and the DROPS (an item the player may pick up, which moves his ammo and so his shots). So with monsters
# that hear and act (the decide mode: they wake, chase and decide, and apply nothing to the player), "hit" equals
# "full" on every monster cell and every alert at EVERY tic until the first tic the full model shoots a barrel, blasts
# one, or drops an item -- that tic itself not compared (its shot may already differ).
HIT_FIELDS = MON_FIELDS + ("mon_ambush", "mon_movedir", "mon_facing", "mon_x", "mon_y", "mon_movecount",
                           "mon_justattacked", "mon_active", "snd_alert")


def _noisy(seed=3, n=600):
    """walk about the start, turning, the trigger held for stretches"""
    rng = random.Random(seed)
    out, fire = [], False
    for t in range(n):
        k = {name: False for name in KEYS}
        if rng.random() < 0.1:
            fire = not fire
        k["fire"] = fire
        k["turn_left"] = rng.random() < 0.15
        k["forward"] = rng.random() < 0.3
        out.append(k)
    return out


def _hit_snap(w, fields=HIT_FIELDS):
    return {f: tuple(getattr(w.ws, f)) for f in fields} | {"rng_player": w.ws.rng_player}


def _full_left_hit(ev, w) -> bool:
    """the full model did something this tic that "hit" leaves out AND a monster can feel: a barrel shot or blasted, a
    drop made"""
    return any(h[1] == "bar" for h in ev.hits) or bool(ev.barrel_blasts) or any(w.ws.mon_drop)


def _hit_run(mode, keys):
    """(the first tic `mode` parts from "full" -- on the monster cells, and for "hit" the alerts too -- or None; the
    tics compared; the full model's sound wakes and noise tics over them)"""
    a = World(skill=gd.SK_HARD, monsters="decide", player=mode)
    b = World(skill=gd.SK_HARD, monsters="decide", player="full")
    fields = HIT_FIELDS if mode == "hit" else tuple(f for f in HIT_FIELDS if f != "snd_alert")
    wakes = noise = 0
    for t, k in enumerate(keys):
        a.tic(k)
        eb = b.tic(k)
        if _full_left_hit(eb, b):
            return None, t, wakes, noise
        wakes += sum(1 for _m, how in eb.wakes if how == "sound")
        noise += eb.noise
        if _hit_snap(a, fields) != _hit_snap(b, fields):
            return t, t, wakes, noise
    return None, len(keys), wakes, noise


def test_hit_mode_is_the_full_model_on_the_monsters():
    parted, upto, wakes, noise = _hit_run("hit", _noisy())
    assert parted is None, "tic %d: hit parted from full" % parted
    assert upto >= 300, "compared only %d tics" % upto
    assert noise >= 10 and wakes >= 3, "the script made %d noises that woke %d monsters" % (noise, wakes)


def test_the_control_shoot_without_the_noise_parts():
    """R9: the same script in "shoot" (no noise) parts from the full model on a MONSTER cell -- the noise is what the
    test above pins, not only the alerts it writes"""
    parted, _upto, _w, _n = _hit_run("shoot", _noisy())
    assert parted is not None, "a mode without the noise went unnoticed on the monster cells"
