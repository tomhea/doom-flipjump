"""M8 wave 1 / 2 gate fixes (m8-gatefix): the harness reasons four gates failed on E1M3 / E1M4 / E1M5 b4 binaries that
were state-, pixel- and palette-exact on every frame -- each with a control (R9):

  - hurt_gate's `momentum` control moves the table the fireball spawn READS (`missile_mom`, since M8 C8) -- it moved
    only `fireball_mom`, a list nothing read, and parted on no frame of any map; control: the pre-C8-only rebinding
    leaves `missile_mom` as it was;
  - hurt_gate places off E1M1 through more than 12 candidates (E1M4's H3 first places at 64); E1M1 keeps 12;
  - fight_gate: a puff is a barrel counter (a map with no barrel does not owe it); control: one barrel row running
    keeps it owed; an empty candidate list of a RULE scenario off E1M1 is N/A with its reason (E1M1 never);
  - scenarios_map's planner leaves the refused parameter sets out of scenarios_v2.plan_run (the hashed checker
    untouched): control -- nothing refused calls it unchanged, and PARAMS is restored after.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT / "scratchpad" / "gp", ROOT / "tests"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def test_momentum_control_moves_the_table_the_spawn_reads():
    import hurt_gate as H
    from doomfj import combat as C
    from doomfj import world as W
    name = C.FIREBALL_INFO.name
    w0 = W.World(skill=3, strict=True)
    base = list(w0.missile_mom[name])
    assert w0.missile_mom[name] is w0.fireball_mom                      # the spawn reads this very list
    with H.control("momentum"):
        w1 = W.World(skill=3, strict=True)
    assert w1.missile_mom[name] is w1.fireball_mom
    assert list(w1.missile_mom[name]) != base                           # the mutation reaches the spawn's table
    assert list(w1.missile_mom[name]) == base[1:] + base[:1]            # one fine angle off, nothing else
    # control: the rebinding alone (the control before this fix) leaves the spawn's table as it was
    w2 = W.World(skill=3, strict=True)
    t = w2.fireball_mom
    w2.fireball_mom = [t[(i + 1) % len(t)] for i in range(len(t))]
    assert list(w2.missile_mom[name]) == base


def test_hurt_place_limit_deeper_only_off_e1m1():
    import hurt_gate as H
    assert H.place_limit("E1M1") == 12                                  # control: E1M1 tries what it always tried
    assert H.place_limit("E1M4") > 64 and H.place_limit("E1M2") == H.DEEP_LIMIT


def test_puffs_are_a_barrel_counter():
    import fight_gate as FG
    tags = ["F6", "F6d", "F6p", "F7", "S2", "S4", "F8b"]
    barrels = {"F6", "F6d", "F6p", "F7", "S2", "S4"}
    assert "puffs" in FG.unowed(("puffs", "fx_spawns"), tags, barrels)
    assert FG.unowed(("puffs",), tags, barrels - {"F6p"}) == []        # control: the punched barrel runs -> owed
    assert "fx_spawns" not in FG.unowed(("puffs", "fx_spawns"), tags, barrels)   # no barrel owner -> still owed


def test_empty_rule_scenarios_na_reason():
    import fight_gate as FG

    class _W:
        barrel_things = []
    assert FG.empty_na("K3", _W(), "E1M5") == "E1M5 has no barrel"
    assert FG.empty_na("I6", _W(), "E1M5").startswith("no imp of E1M5")
    _W.barrel_things = [object()]
    assert "within 96 units" in FG.empty_na("K3", _W(), "E1M4")
    assert FG.empty_na("ZZ", _W(), "E1M4") == "no candidate placed from E1M4's things"
    # control: the main loop's empty-list N/A is never taken on E1M1 (its source names the map)
    src = (ROOT / "scratchpad" / "gp" / "fight_gate.py").read_text(encoding="ascii")
    i = src.index("empty_na(sc[\"name\"]")
    assert 'dsim.mapname != "E1M1"' in src[i - 900:i]


def test_plan_run_without_refused_sets():
    import scenarios_map as SM

    class _S:
        PARAMS = ({"name": "aggressive"}, {"name": "steady"}, {"name": "cautious"})

        @staticmethod
        def plan_run(cp, setup, nav):
            sets = tuple(cp.get("params", ())) + _S.PARAMS
            return [], sets[0]["name"], [p["name"] for p in sets]
    orig = _S.PARAMS
    assert SM._plan_run_without(_S, {}, None, None, [])[1] == "aggressive"          # control: nothing refused
    _keys, pname, tried = SM._plan_run_without(_S, {"params": ({"name": "aggressive"},)}, None, None, ["aggressive"])
    assert pname == "steady" and "aggressive" not in tried
    assert _S.PARAMS is orig                                                         # restored
