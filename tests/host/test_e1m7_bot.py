"""M8 (E1M7 at easy): the bot's map tactic SKIP_ITEMS (scripts/play.py Steer, via MAP_TACTICS).

E1M7's chaingun (352, 1504) is a 127-cell route pickup leg (level_route's PICKUP_BUDGET 150) into a room of imps,
demons and sergeants; with the lift 440 leg fixed (test_e1m7_route.py), every play of the model search (seeds 0..4 and
their schedules) died there, or on the health detour beside it, at 23..48 health. SKIP_ITEMS drops the route's pickup
legs of the listed types when the Steer is built; the leg after one re-plans from where the player is ("the leg
starts elsewhere"). A MAP TACTIC: E1M7's alone (class default (), every other map's legs as the route planned them).
CONTROL (R9): SKIP_ITEMS () -> the same route keeps the chaingun leg.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
pytestmark = pytest.mark.skipif(not (FIX / "freedoom_e1m7.wad").exists(), reason="needs the E1M7 fixture wad")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def mods():
    lr = _load("level_route", "scripts/level_route.py")
    return lr, _load("play", "scripts/play.py"), lr.plan("E1M7", "easy")


def test_e1m7_skips_the_chaingun_leg(mods):
    _lr, play, route = mods
    assert "item:2002" in [g["to"] for g in route["legs"]]          # the route still plans it ...
    st = play.Steer(route, log=lambda s: None, seed=0)
    assert st.SKIP_ITEMS == (2002,)
    to = [g["to"] for g in st.legs]
    assert "item:2002" not in to                                     # ... and the E1M7 bot does not walk it
    assert to == [g["to"] for g in route["legs"] if g["to"] != "item:2002"]


def test_control_no_skip(mods, monkeypatch):
    _lr, play, route = mods
    monkeypatch.setitem(play.Steer.MAP_TACTICS, "E1M7", {})
    st = play.Steer(route, log=lambda s: None, seed=0)
    assert "item:2002" in [g["to"] for g in st.legs], "CONTROL: the chaingun leg dropped with no tactic"


def test_map_tactics_are_e1m7s_alone(mods):
    _lr, play, _route = mods
    # E1M7's tactic is its own: no other map skips an item (E1M4 has tactics of its own, none of them SKIP_ITEMS)
    assert play.Steer.MAP_TACTICS["E1M7"] == {"SKIP_ITEMS": (2002,)} and play.Steer.SKIP_ITEMS == ()
    assert all("SKIP_ITEMS" not in t for m, t in play.Steer.MAP_TACTICS.items() if m != "E1M7")
