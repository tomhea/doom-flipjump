"""Strafe (plan section 2, input; added for the combat scenario set v2, 2026-09-26).

DOOM's P_MovePlayer thrusts `sidemove` along `angle - ANG90`: a strafe to the RIGHT of a player
facing east moves it south. The model steps STRAFE_MOVE (13 units, DOOM's running
sidemove/forwardmove ratio 40/50 of the 16-unit FORWARD_MOVE) per tic, as a FixedMul like the
forward step, through the same three collision candidates.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import pytest                                   # noqa: E402

from doomfj import combat as C                  # noqa: E402
from doomfj import gamedata as gd               # noqa: E402
from doomfj import world as W                   # noqa: E402

EAST, NORTH = 0, 0x40000000                     # BAM


def s32(v):
    """A 32-bit field as a signed int (the schema may hold either form)."""
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def _world(angle):
    w = W.World(skill=gd.SK_HARD)
    w.ws.pangle = angle
    return w


def _step(w, **keys):
    x0, y0 = w.ws.px, w.ws.py
    w.tic(keys)
    return s32(w.ws.px) - s32(x0), s32(w.ws.py) - s32(y0)


def test_the_strafe_constant_is_doom_s_ratio_of_the_forward_step():
    assert W.STRAFE_MOVE == C.STRAFE_MOVE == 13 << 16
    assert abs((W.STRAFE_MOVE >> 16) - 16 * 40 / 50) < 0.5


@pytest.mark.parametrize("key, want", [("strafe_right", (0, -13 << 16)), ("strafe_left", (0, 13 << 16))])
def test_a_strafe_facing_east_moves_south_for_right_and_north_for_left(key, want):
    assert _step(_world(EAST), **{key: True}) == want


def test_a_strafe_facing_north_moves_east_for_right():
    assert _step(_world(NORTH), strafe_right=True) == (13 << 16, 0)


def test_both_strafe_keys_cancel():
    assert _step(_world(EAST), strafe_left=True, strafe_right=True) == (0, 0)


def test_forward_and_strafe_add():
    assert _step(_world(EAST), forward=True, strafe_right=True) == (16 << 16, -13 << 16)


def test_negative_control_a_zero_strafe_is_caught(monkeypatch):
    """Control: with the side step switched off, the east-facing strafe test's expectation fails."""
    monkeypatch.setattr(C, "STRAFE_MOVE", 0)
    assert _step(_world(EAST), strafe_right=True) != (0, -13 << 16)


def test_strafing_into_a_wall_is_refused_like_a_forward_step():
    """Walk east (forward) until a wall stops the player, then face north and strafe RIGHT -- which
    is east, into the same wall: the player must not pass it."""
    w = _world(EAST)
    for _ in range(400):                         # forward east until blocked
        before = (w.ws.px, w.ws.py)
        w.tic({"forward": True})
        if (w.ws.px, w.ws.py) == before:
            break
    else:
        pytest.skip("no wall reached east of the spawn")
    stop_x = s32(w.ws.px)
    w.ws.pangle = NORTH
    for _ in range(20):
        w.tic({"strafe_right": True})            # facing north, right is east: into the wall
    assert s32(w.ws.px) <= stop_x + (1 << 16)
