"""M8 (E1M7): a leg the route's dependency closure left without a path gets legs to what it needs (level_route.legs,
CLOSURE_LEGS).

E1M7's lift 440 is called down from its SR switch (line 2541, x = -800) at the west end of a strip reached only through
a 64-unit corridor (x -576..-512) whose mouth is shut by the pillar door 439 (a 32x32 sector, floor = ceiling -112,
raised by the S1 switch 283 in sector 433's niche at y 1888). The flood raised it at epoch 3 and walked to the lift's
switch at epoch 4 -- but its path passes BESIDE the pillar (within the player's radius) and never across its lines, so
`needs_of_path` did not count it and the closure (the route) has no door:439. The lift leg was then planned in the
flood's whole world (door:284 / 305 / 439 / 695 assumed open), and every bot play stalled against the pillar
(`playthrough_gate --model-only --search`, 2 hours: no seed past the lift:440 leg).
NOW: of the flood's mechanisms the leg can do without, each is dropped; what is left (door:439 alone) gets a leg of its
own before the lift's, and the lift's leg is planned again after it.
  CONTROL (R9): CLOSURE_LEGS off -> no door:439 leg, the lift's leg planned in the flood's world (the old route).
Every other map's route is unchanged by the rule (none has a closure gap; their routes compared whole, 2026-10-30).
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
def lr():
    return _load("level_route", "scripts/level_route.py")


def _leg(r, to):
    return next(i for i, g in enumerate(r["legs"]) if g["to"] == to)


def test_e1m7_pillar_door_before_lift_440(lr):
    r = lr.plan("E1M7", "easy")
    assert r["ok"], r.get("why")
    assert "door:439" not in [n["id"] for n in r["needs"]]      # the closure still misses it ...
    k = _leg(r, "lift:440")
    assert r["legs"][k]["closure_gap"] == ["door:439"] and r["legs"][k].get("closure_legs")
    d = _leg(r, "door:439")                                        # ... and the legs visit its switch first
    assert d < k and r["legs"][d]["action"] == "use"
    x0, y0, x1, y1 = r["legs"][d]["box"]                           # the S1 switch 283's use box, in sector 433's niche
    gx, gy = r["legs"][d]["goal"]
    assert x0 <= gx <= x1 and y0 <= gy <= y1 and (x0, y0, x1, y1) == (-512, 1824, -320, 1952)
    assert all(g["path"] for g in r["legs"]) and not any(g.get("closure_gap") and not g.get("closure_legs")
                                                       for g in r["legs"])


def test_control_no_closure_legs(lr, monkeypatch):
    monkeypatch.setattr(lr, "CLOSURE_LEGS", False)
    r = lr.plan("E1M7", "easy")
    assert "door:439" not in [g["to"] for g in r["legs"]], "CONTROL: the pillar's switch is a leg without the rule"
    g = r["legs"][_leg(r, "lift:440")]
    assert "door:439" in g["closure_gap"] and not g.get("closure_legs")
