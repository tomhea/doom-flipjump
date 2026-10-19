"""M8 (docs/level-pipeline.md 3, gen_dryrun's audit): a `World()` with no map wad builds E1M1's -- REFUSED while the
process measures another map (mapprofile.ACTIVE), so no gate silently measures E1M1 on a new level.

  - World() refuses under ACTIVE=E1M3 (and builds under E1M1: control); an explicit E1M1 world still builds;
  - fight_gate._world_at (F5's medium level start) is the scenario world's MAP (it was E1M1's: the bug), control: the
    E1M2 world it returns differs from E1M1's;
  - p8a_lib.packages(), the model-feature probes, still find every package under another active map (they name E1M1
    explicitly: a refusal inside their `except Exception` would have read as "package not in" -- silently).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad", ROOT / "scratchpad" / "12m", ROOT / "scratchpad" / "gp"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def _wad(m):
    from doomfj.wad import WadFile
    return WadFile.from_path(str(ROOT / "tests" / "fixtures" / ("freedoom_%s.wad" % m.lower())))


def test_no_map_world_refused_off_e1m1(monkeypatch):
    from doomfj import mapprofile as MP
    from doomfj.world import World
    monkeypatch.setattr(MP, "ACTIVE", "E1M1")
    assert World(monsters="idle").mapname == "E1M1"                        # control: E1M1 unchanged
    monkeypatch.setattr(MP, "ACTIVE", "E1M3")
    with pytest.raises(AssertionError, match="measures E1M3"):
        World(monsters="idle")
    assert World(_wad("E1M1"), "E1M1", monsters="idle").mapname == "E1M1"  # deliberate E1M1: allowed


def test_fight_gate_medium_world_is_the_maps():
    import fight_gate as FG
    from doomfj import gamedata as gd
    from doomfj.world import World
    w2 = World(_wad("E1M2"), "E1M2", monsters="idle")
    wm = FG._world_at(gd.SK_MEDIUM, w2)
    assert wm.mapname == "E1M2" and wm.ws.skill == gd.SK_MEDIUM
    w1 = World(_wad("E1M1"), "E1M1", monsters="idle")
    assert len(wm.mon_things) == len(w2.mon_things) != len(FG._world_at(gd.SK_MEDIUM, w1).mon_things)


def test_p8a_packages_probe_e1m1_under_another_map(monkeypatch):
    import p8a_lib as P8
    from doomfj import mapprofile as MP
    monkeypatch.setattr(MP, "ACTIVE", "E1M3")
    monkeypatch.setattr(P8, "_PKG", None)
    pk = P8.packages()
    assert all(ok for ok, _why in pk.values()), pk


def test_a_tool_refuses_another_checkouts_doomfj(tmp_path):
    """mapprofile.check_checkout: a tool whose checkout is not its doomfj's refuses (the installed doomfj points at the
    main repo -- a worktree tool without PYTHONPATH=src measured the main repo's model). CONTROL: this checkout's tool
    passes"""
    from doomfj.mapprofile import check_checkout
    check_checkout(ROOT / "scratchpad" / "gp" / "probe.py")
    other = tmp_path / "otherrepo"
    (other / "src" / "doomfj").mkdir(parents=True)
    (other / "scratchpad").mkdir()
    with pytest.raises(SystemExit, match="PYTHONPATH"):
        check_checkout(other / "scratchpad" / "tool.py")
