"""M8 (gates-ready, the gate-tool audit): the gameplay gates host a map that lacks what E1M1 has, N/A by name instead of
crashing or failing a counter -- and change nothing on E1M1 (gate_roles_check.py --ref: 80 scenarios IDENTICAL).

  - p2a S8 / die D3x need exactly one SWITCH exit: E1M8 (W1 exits 52 only) is N/A with why; E1M1 places it (control);
  - fight / die: a counter is not owed when EVERY present scenario raising it is N/A (a map with no barrel: the five
    barrel counters); control: one barrel row running keeps them owed, and a counter no scenario owns stays owed;
  - hurt: off E1M1 a scenario with no candidate from the map's monsters is N/A, never on E1M1 (control); its counters
    follow the same rule;
  - die D4 on a map without a baked barrel drops the barrel's poke and control (E1M5); E1M1 keeps both (control).
E1M5 / E1M8's thing types the model lacks (C6 / C7 / C8) are dropped (gen_dryrun's `unknown-things`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT / "scratchpad" / "gp", ROOT / "tests"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def _drop_unknown(monkeypatch):
    from doomfj import gamedata as gd
    from doomfj.wad import WadFile
    orig = WadFile.things
    monkeypatch.setattr(WadFile, "things", lambda self, name: [
        t for t in orig(self, name) if t.type in gd.THING_TYPES or t.type in gd.NOT_THINGS])


def _dsim(m):
    import onewalk
    return onewalk.DoorSim("tests/fixtures/freedoom_%s.wad" % m.lower(), m)


def test_exit_scenarios_na_without_one_switch_exit():
    import p2a_gate as G
    assert G.exit_na(_dsim("E1M1")) is None                                # control: E1M1 hosts S8 / D3x
    why = G.exit_na(_dsim("E1M8"))
    assert why and "0 switch exits" in why and "52" in why, why


def test_fight_counters_owed_unless_every_owner_is_na():
    import fight_gate as FG
    tags = ["F1", "F5", "F6", "F6d", "F6p", "F7", "F8a", "S2", "S4"]
    need = ("pickups", "barrel_blasts", "bexp_frames", "gibs", "berserk_frames", "player_blocked")
    barrels = {"F6", "F6d", "F6p", "F7", "S2", "S4"}
    assert set(FG.unowed(need, tags, barrels)) == {"barrel_blasts", "bexp_frames"}      # gibs: F5 still runs
    assert set(FG.unowed(need, tags, barrels | {"F5"})) == {"barrel_blasts", "bexp_frames", "gibs", "berserk_frames"}
    assert FG.unowed(need, tags, barrels - {"F7"}) == []                  # control: one barrel row runs -> owed
    assert "pickups" not in FG.unowed(need, tags, set(tags))              # control: no owner -> always owed


def test_hurt_na_only_off_e1m1():
    import hurt_gate as H
    sc = {"name": "H4 a demon's bite", "cands": []}
    assert H.na_why(sc, "E1M1") is None                                   # control: E1M1 FAILS an empty list
    assert "no candidate" in H.na_why(sc, "E1M5")
    assert H.na_why({"name": "H1 x", "cands": [1]}, "E1M5") is None
    tags = list(H.OWNS)
    assert H.unowed(("mon_melee", "player_hurt"), tags, {"H4"}) == ["mon_melee"]   # player_hurt: H1/H2/H5 run


def test_die_d4_without_a_baked_barrel(monkeypatch):
    import die_gate as DG
    from doomfj import gamedata as gd
    from doomfj.monsters import MonsterPhase
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE

    def d4(m):
        ds = _dsim(m)
        w = MonsterPhase(ds.mw, m, BOOT_SKILL, rm=ds.rm, mode=MONSTER_MODE, player=PLAYER_MODE).world
        if hasattr(DG._baked_pickup, "mv"):
            del DG._baked_pickup.mv
        pk = [i for i, t in enumerate(w.pickup_things) if t.type == 2014 and t.flags & gd.skill_bit(gd.SK_HARD)]
        return DG._has_baked(w, pk), w
    (pk1, bar1), _w = d4("E1M1")
    assert pk1 and bar1                                                   # control: E1M1's D4 as it was
    _drop_unknown(monkeypatch)
    (pk5, bar5), w5 = d4("E1M5")
    assert not w5.barrel_things and not bar5
    if hasattr(DG._baked_pickup, "mv"):
        del DG._baked_pickup.mv
