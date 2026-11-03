"""M8 wave 3: `scratchpad/m2_std_gate.py`'s door picker takes a door from its FAR side when no walk from the spawn
reaches the spawn-side approach (E1M6: every candidate refused "no walkable path to the approach" at every skill,
in both passes, because the walk reaches doors 393 and 180 from the side facing away from the spawn).

The rule (`choose_approach`): the spawn's straight-line side FIRST, kept whenever it is reached -- so every candidate
the old rule accepted, or refused for any other reason, is judged as before -- and the other side only when it is not.
The negative controls run the same property checks against the two wrong rules (the pre-fix "spawn side only" and a
"far side always") and require each to be REJECTED."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# E1M6's door 393: its first two-sided line (2714) and the player start
SEGS = [((-1232, 288), (-1328, 288)), ((-1328, 272), (-1232, 272))]
SPAWN = (0, -160)
NEAR_SIDE = (-1280.0, 232.0)        # 56 short of the line on the spawn's side (south)
FAR_SIDE = (-1280.0, 344.0)         # 56 past it, the side the walk really reaches (north)


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("m2_std_gate_mod", ROOT / "scratchpad/m2_std_gate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _reach_only(*pts):
    """a `reach` that finds a (dummy) path to exactly the given points"""
    return lambda p: [p] if tuple(round(v) for v in p) in {tuple(round(v) for v in q) for q in pts} else None


def _violations(choose):
    """every way `choose` breaks the rule -> [] for a correct one"""
    bad = []
    a, b, far, path = choose(SEGS, *SPAWN, _reach_only(NEAR_SIDE, FAR_SIDE))
    if (tuple(a), far) != (NEAR_SIDE, False) or not path:
        bad.append("both sides reached: not the spawn side (%s, far=%s)" % (a, far))
    a, b, far, path = choose(SEGS, *SPAWN, _reach_only(FAR_SIDE))
    if (tuple(a), far) != (FAR_SIDE, True) or not path:
        bad.append("only the far side reached: not taken (%s, far=%s)" % (a, far))
    elif b[1] >= 272:
        bad.append("far side: `beyond` %s is not back across the door, on the spawn's side" % (b,))
    a, b, far, path = choose(SEGS, *SPAWN, _reach_only())
    if path is not None:
        bad.append("neither side reached, yet a path")
    return bad


def test_door_approach_spawn_side_is_the_old_geometry(gate):
    """`door_approach` with far=False is the arithmetic the gate always had: 56 short on the spawn's side, 88 past"""
    a, b = gate.door_approach(SEGS, *SPAWN)
    assert (a, b) == (NEAR_SIDE, (-1280.0, 376.0))
    a, b = gate.door_approach(SEGS, *SPAWN, depth=40, far=True)
    assert (a, b) == (FAR_SIDE, (-1280.0, 248.0))


def test_choose_approach_keeps_the_spawn_side_and_falls_back_to_the_far_side(gate):
    assert _violations(gate.choose_approach) == []


def test_negative_control_the_pre_fix_rule_is_rejected(gate):
    def spawn_side_only(segs, sx, sy, reach):
        a, b = gate.door_approach(segs, sx, sy)
        return a, b, False, reach(a)
    assert any("only the far side" in v for v in _violations(spawn_side_only))


def test_negative_control_far_side_always_is_rejected(gate):
    """a rule that moved every door to its far side would change the picks of E1M1..E1M5 / E1M9"""
    def far_side_always(segs, sx, sy, reach):
        a, b = gate.door_approach(segs, sx, sy, far=True)
        return a, b, True, reach(a)
    assert any("both sides reached" in v for v in _violations(far_side_always))
