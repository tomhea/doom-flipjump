"""M14-d — line collision, the oracle mirror (`ReferenceModel.check_position` / `try_move` /
`move_with_collision`), before any fj exists for it (R1: the failing test comes first).

This is DOOM's P_CheckPosition / PIT_CheckLine / P_BoxOnLineSide, minus the blockmap: the whole
line list is tested and the per-line bbox reject does the blockmap's job. Two deliberate,
documented departures from vanilla, both of them stated in the methods' docstrings and both
mirrored identically on the fj side:

  * the "don't stand over a dropoff" test is not implemented (it only ever refuses moves, so
    omitting it is the permissive direction);
  * a blocked move retries the two axis-separated halves instead of running `P_SlideMove`.

⚠ `test_collision_actually_blocks_something` is the CONTROL. Every other test here would pass if
`check_position` returned "fine" unconditionally -- a walker that never collides never walks into a
wall either. That test requires the collision trajectory to DIFFER from the collision-free one, so
a no-op mirror fails loudly instead of looking perfect.
"""
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (ML_BLOCKING, PLAYER_RADIUS, ReferenceModel, SimState,
                                    build_scene, spawn_state)
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
U = 1 << 16
F, B, L, R = "forward", "back", "turn_left", "turn_right"


@pytest.fixture(scope="module")
def level():
    wad = WadFile.from_path(E1M1)
    return ReferenceModel(Config()), build_scene(wad, wad, "E1M1"), spawn_state(wad, "E1M1")


def keys(*names):
    return {n: True for n in names}


# ── the geometry primitives ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("x,y,want", [
    (5 * U, 1 * U, 0),        # right of a north-pointing line is the FRONT side
    (5 * U, -1 * U, 0),
    (-5 * U, 1 * U, 1),
    (0, 5 * U, 1),            # ON the line: DOOM's `x <= v1x` branch answers `dy > 0`, i.e. 1
])
def test_point_on_line_side_vertical(level, x, y, want):
    """A vertical line (dx == 0) takes DOOM's axis shortcut, not the cross product."""
    rm, _scene, _sp = level
    assert rm.point_on_line_side(x, y, 0, 0, 0, 10 * U) == want


@pytest.mark.parametrize("x,y,want", [
    (1 * U, 5 * U, 1),
    (1 * U, -5 * U, 0),
    (-1 * U, -5 * U, 0),
])
def test_point_on_line_side_horizontal(level, x, y, want):
    rm, _scene, _sp = level
    assert rm.point_on_line_side(x, y, 0, 0, 10 * U, 0) == want


def test_point_on_line_side_diagonal_agrees_with_the_cross_product(level):
    """Off the axes the sign of the 2D cross product is the answer, so the fixed-point path must
    agree with exact integer arithmetic everywhere it is not truncating a boundary."""
    rm, _scene, _sp = level
    v1, v2 = (0, 0), (100, 70)
    for px in range(-120, 121, 17):
        for py in range(-120, 121, 13):
            cross = (v2[0] - v1[0]) * (py - v1[1]) - (v2[1] - v1[1]) * (px - v1[0])
            if cross == 0:
                continue                                    # exactly on the line: boundary, skip
            want = 1 if cross > 0 else 0
            got = rm.point_on_line_side(px * U, py * U, 0, 0, v2[0] * U, v2[1] * U)
            assert got == want, f"({px},{py}) cross={cross} -> {got}"


def test_box_on_line_side_detects_straddling(level):
    """-1 (straddling) is the only answer that lets a line block, so it is the answer that must be
    right: a box centred on the line straddles, one clear of it does not."""
    rm, _scene, _sp = level
    line = (0, 0, 0, 100 * U)                                # vertical
    assert rm.box_on_line_side((10 * U, -10 * U, -10 * U, 10 * U), *line) == -1
    assert rm.box_on_line_side((10 * U, -10 * U, 20 * U, 40 * U), *line) != -1
    assert rm.box_on_line_side((10 * U, -10 * U, -40 * U, -20 * U), *line) != -1
    diag = (0, 0, 100 * U, 100 * U)
    assert rm.box_on_line_side((60 * U, 40 * U, 40 * U, 60 * U), *diag) == -1
    assert rm.box_on_line_side((90 * U, 80 * U, 10 * U, 20 * U), *diag) != -1


# ── the level ──────────────────────────────────────────────────────────────────────────────────

def test_the_spawn_point_is_a_legal_position(level):
    """If the player does not fit where the level puts them, everything downstream is noise."""
    rm, scene, sp = level
    ok, floorz, ceilingz = rm.check_position(scene, _signed(sp.x, 32), _signed(sp.y, 32))
    assert ok, "the E1M1 player start is rejected by check_position"
    assert ceilingz - floorz >= 56, f"opening at spawn is {ceilingz - floorz} units"


def test_a_position_deep_outside_the_map_is_not_reachable(level):
    """Outside the level no linedef bbox overlaps the player box, so nothing REFUSES the position
    -- it is the subsector seed that does, via the zero opening of the solid space out there. This
    test exists because the first draft omitted that seed and happily teleported the player to
    (30000, 30000)."""
    rm, scene, sp = level
    far = 30000 << 16
    assert not rm.try_move(scene, _signed(sp.x, 32), _signed(sp.y, 32), far, far)


def _walk(rm, scene, sp, script, *, collide):
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    out = []
    for i in range(len(script)):
        st = rm.step_sim(st, keys(*script[i]), scene=scene if collide else None)
        out.append((_signed(st.x, 32), _signed(st.y, 32), st.angle))
    return out


SCRIPT = ([[F]] * 40 + [[L]] * 6 + [[F]] * 30 + [[R]] * 10 + [[F]] * 30
          + [[F, L]] * 12 + [[B]] * 12)


def test_walking_never_ends_up_inside_geometry(level):
    """The invariant that matters: every position the sim produces must itself be legal. A
    collision that lets the player through a wall shows up here as a rejected position."""
    rm, scene, sp = level
    for tic, (x, y, _a) in enumerate(_walk(rm, scene, sp, SCRIPT, collide=True)):
        ok, _f, _c = rm.check_position(scene, x, y)
        assert ok, f"tic {tic}: the sim moved the player to ({x / U:.2f}, {y / U:.2f}), " \
                   "which check_position rejects"


def test_collision_actually_blocks_something(level):
    """⚠ THE CONTROL. Everything above passes trivially if collision never blocks -- so require
    the collided walk to DIVERGE from the free walk, and require the free walk to visit a position
    collision would have refused. Without this, a `return True` mirror looks perfect."""
    rm, scene, sp = level
    collided = _walk(rm, scene, sp, SCRIPT, collide=True)
    free = _walk(rm, scene, sp, SCRIPT, collide=False)
    assert collided != free, "collision changed nothing -- it is not running"
    illegal = [t for t, (x, y, _a) in enumerate(free) if not rm.check_position(scene, x, y)[0]]
    assert illegal, "the free walk never leaves legal space, so this script proves nothing"


def test_a_blocked_move_keeps_the_player_exactly_put(level):
    """When all three candidates fail, the position must be bit-identical to the old one -- not
    'nearly'. A sim that nudges on a blocked tic drifts through walls over hundreds of frames."""
    rm, scene, sp = level
    # face a one-sided wall by walking into it until the position stops changing
    st = SimState(sp.x, sp.y, sp.angle, "E1M1")
    prev = None
    for _ in range(200):
        st = rm.step_sim(st, keys(F), scene=scene)
        if prev == (st.x, st.y):
            break
        prev = (st.x, st.y)
    else:
        pytest.skip("this heading never reaches a wall in 200 tics")
    after = rm.step_sim(st, keys(F), scene=scene)
    assert (after.x, after.y) == (st.x, st.y), "a fully blocked tic moved the player"


def test_one_sided_and_blocking_lines_both_stop_the_player(level):
    """The two hard refusals in PIT_CheckLine. E1M1 has both kinds; assert each is exercised by
    finding a line of each kind and testing a position straddling it."""
    rm, scene, sp = level
    lds = scene.map_wad.linedefs("E1M1")
    verts = scene.cmap.vertexes
    kinds = {"one-sided": [ld for ld in lds if ld.back == -1],
             "ML_BLOCKING": [ld for ld in lds if ld.back != -1 and ld.flags & ML_BLOCKING]}
    for kind, group in kinds.items():
        if not group:
            pytest.skip(f"E1M1 has no {kind} linedef")
        ld = group[0]
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        mid = ((x1 + x2) // 2 << 16, (y1 + y2) // 2 << 16)     # a box centred ON the line straddles
        ok, _f, _c = rm.check_position(scene, mid[0], mid[1], radius=PLAYER_RADIUS)
        assert not ok, f"a {kind} line did not refuse a position straddling it"


def test_a_masked_and_a_signed_simstate_are_the_same_state(level):
    """⚠ REGRESSION, found by M14's multi-frame gate. `spawn_state` builds x/y SIGNED; `step_sim`
    used to return them MASKED; the projection reads `state.x` raw while everything else goes
    through `_signed`. So feeding a simulated state back into the renderer -- which nothing did
    before M14, every gate having hand-built `SimState(vx << 16, ...)` -- rendered a different
    frame from the identical hand-built one: 14,845 of 16,000 pixels, with the fj side correct.
    SimState now normalises on construction, so the two spellings cannot part again."""
    _rm, _scene, sp = level
    signed = SimState(-416 << 16, 256 << 16, 0x02800000, "E1M1")
    masked = SimState((-416 << 16) & 0xFFFFFFFF, (256 << 16) & 0xFFFFFFFF, 0x02800000, "E1M1")
    assert (signed.x, signed.y) == (masked.x, masked.y) == (-416 << 16, 256 << 16)
    assert SimState(sp.x, sp.y, sp.angle, "E1M1").x == _signed(sp.x, 32)
    # and an angle past the wrap is the same angle
    assert SimState(0, 0, 1 << 32, "E1M1").angle == 0
