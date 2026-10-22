"""M8 (docs/episode-plan.md 5): `scripts/level_route.py` -- the route planner the playthrough gate steers.

The two shipped maps must PLAN: E1M1 from its start through doors 10, 34 and 64 to the S1 exit (line 407), no key;
E1M2 through its three keys in the order the level forces (blue on sector 45 after the S1 floor switch lowers it, red
from below its 32-unit alcove, yellow) to the exit (line 737). Every leg must end where its action happens (the exit
leg inside the exit's use box).

R9: the planner is evidence only if it can say NO. CONTROL 1 removes E1M2's red key from the map: the red door
(sector 29) can then never open, and the planner must report NO ROUTE rather than walk through it. CONTROL 2 lifts
E1M2's floor switch out of the model's movers: the blue card then stays out of reach on its raised floor, and the
planner must fail too (the key's floor dependency is real, not decoration).
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests" / "fixtures"
pytestmark = pytest.mark.skipif(not (FIX / "freedoom_e1m2.wad").exists(), reason="needs the E1M1 / E1M2 fixture wads")


@pytest.fixture(scope="module")
def lr():
    spec = importlib.util.spec_from_file_location("level_route", ROOT / "scripts" / "level_route.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _in_box(p, box):
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]


def test_e1m1_route(lr):
    r = lr.plan("E1M1", "easy")
    assert r["ok"], r.get("why")
    assert r["exit"]["line"] == 407 and r["exit"]["special"] == 11 and r["exit"]["model"]
    assert r["keys_order"] == []
    assert [n["id"] for n in r["needs"]] == ["door:10", "door:34", "door:64"]
    leg = r["legs"][-1]
    assert leg["to"] == "exit" and _in_box(leg["path"][-1], r["exit"]["box"])
    assert r["legs"][0]["path"][0] == list(lr.centre(lr.cell_of(*r["start"])))
    for g0, g1 in zip(r["legs"], r["legs"][1:]):                  # the legs chain: each starts where the last ended
        assert g1["path"][0] == g0["path"][-1]


def test_e1m2_route(lr):
    r = lr.plan("E1M2", "easy")
    assert r["ok"], r.get("why")
    assert r["exit"]["line"] == 737
    assert r["keys_order"] == ["blue", "red", "yellow"]
    ids = [n["id"] for n in r["needs"]]
    assert ids.index("floor:0") < ids.index("key:blue")          # the S1 switch lowers the card's floor first
    assert {"door:54", "door:29", "door:100"} <= set(ids)          # the blue, red and yellow doors
    assert all(g["path"] for g in r["legs"]) and r["legs"][-1]["to"] == "exit"
    assert _in_box(r["legs"][-1]["path"][-1], r["exit"]["box"])
    red = next(g for g in r["legs"] if g["to"] == "key:red")
    kx, ky = red["key_at"]
    assert abs(red["goal"][0] - kx) < 36 and abs(red["goal"][1] - ky) < 36   # the touch point, below the alcove


def test_control_no_red_key(lr):
    r = lr.plan("E1M2", "easy", drop_keys=("red",), with_legs=False)
    assert not r["ok"], "CONTROL: with no red key the planner still found a route -- it walks through key doors"
    assert "red" not in r["flood"]["keys"]


def test_control_no_floor_switch(lr, monkeypatch):
    import doomfj.movers as MV
    real = MV.MoverPhase.__init__

    def init(self, *a, **kw):
        real(self, *a, **kw)
        self.floor_use = [(g, b) for g, b in self.floor_use if g != 0]     # floor group 0: E1M2's S1 switch 34
    monkeypatch.setattr(MV.MoverPhase, "__init__", init)
    r = lr.plan("E1M2", "easy", with_legs=False)
    assert not r["ok"], "CONTROL: the blue card was taken with its floor never lowered"
    assert "blue" not in r["flood"]["keys"]


# ---- M8 wave 1 (the auto-gameplay agent): E1M3's mixed-card door and the pickups' order, on the full Freedoom wad
WAD = ROOT / "assets" / "freedoom1.wad"
needs_wad = pytest.mark.skipif(not WAD.exists(), reason="needs assets/freedoom1.wad (E1M3..E1M9)")


@needs_wad
def test_e1m3_route_through_the_blue_side_of_door_150(lr):
    """E1M3's door 150 is D1 31 on its west side and D1 32 BLUE on its east (doors.keyed_boxes_xy): the whole west of
    the map, the exit with it, is behind its blue side. The planner presses the keyed box once the blue card is held,
    and the card becomes the door's dependency"""
    r = lr.plan("E1M3", "easy", with_legs=False)
    assert r["ok"], r.get("why")
    assert r["exit"]["special"] == 11 and r["exit"]["line"] == 1367
    row = {n["id"]: n for n in r["needs"]}
    assert "door:150" in row and row["door:150"]["key"] == "blue"
    assert r["keys_order"] == ["blue"]


@needs_wad
def test_control_e1m3_without_keyed_boxes(lr, monkeypatch):
    """CONTROL: the keyed boxes taken out of the model's DoorPhase -- the west is unreachable, the planner must say so"""
    import doomfj.doors as D
    real = D.DoorPhase.__init__

    def init(self, *a, **kw):
        real(self, *a, **kw)
        self.keyed = {}
    monkeypatch.setattr(D.DoorPhase, "__init__", init)
    r = lr.plan("E1M3", "easy", with_legs=False)
    assert not r["ok"], "CONTROL: E1M3 planned with no way through door 150's blue side"


@needs_wad
def test_control_e1m3_without_the_blue_card(lr):
    r = lr.plan("E1M3", "easy", drop_keys=("blue",), with_legs=False)
    assert not r["ok"], "CONTROL: E1M3 planned through the blue side of door 150 with no blue card"


@needs_wad
def test_pickups_nearest_first(lr, monkeypatch):
    """E1M5: the shotgun 24 cells from the start is the first leg (nearest first); CONTROL: the old cheapest-detour
    order takes the chaingun on the path first and never comes back for the shotgun"""
    r = lr.plan("E1M5", "easy")
    assert r["ok"] and r["legs"][0]["to"] == "item:2001"
    monkeypatch.setattr(lr, "PICKUP_ORDER", "cheapest")
    r = lr.plan("E1M5", "easy")
    assert r["legs"][0]["to"] != "item:2001", "CONTROL: the pickups' order made no difference"
    assert "item:2001" not in [g["to"] for g in r["legs"]]
