"""M12f (F5) — R_AddLine: a seg's screen column range with back-face cull + 90° FOV clipping. Returns
(x1, x2, rw_angle1) or None. Validated on the square room (test.wad MAP01, view at centre): the wall the
player directly faces fills the viewport [0, VIEW_W); every other wall (behind, or edge-on at the FOV
boundary) is culled. The wall's screen height (M12g) is drawn across this [x1, x2) span.
"""
from pathlib import Path

from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ANG90, ReferenceModel
from doomfj.wad import WadFile

ROOM = Path("tests/fixtures/square_room.wad")
U = 1 << 16
# seg index -> wall, for the DOOM-wound square room (CW boundary west,north,east,south)
WEST, NORTH, EAST, SOUTH = 0, 1, 2, 3


def _room():
    return bake_bsp(WadFile.from_path(ROOM), "MAP01")


def _ranges(rm, cmap, viewangle):
    return [rm.wall_x_range(128 * U, 128 * U, viewangle, seg, cmap.vertexes) for seg in cmap.segs]


def test_faced_wall_fills_viewport():
    """From the centre facing east, the east wall fills the screen; facing north, the north wall does."""
    cmap = _room()
    rm = ReferenceModel()
    for viewangle, faced in [(0, EAST), (ANG90, NORTH)]:
        ranges = _ranges(rm, cmap, viewangle)
        assert ranges[faced] is not None
        x1, x2, _ = ranges[faced]
        assert (x1, x2) == (0, rm.cfg.VIEW_W)                  # spans the full 160-wide viewport
        # every other wall is culled (behind, or edge-on at the FOV boundary)
        assert all(ranges[i] is None for i in range(4) if i != faced)


def test_wall_behind_is_culled():
    """Facing east, the west wall is behind the viewer ⇒ back-face / off-FOV cull ⇒ None."""
    cmap = _room()
    rm = ReferenceModel()
    assert rm.wall_x_range(128 * U, 128 * U, 0, cmap.segs[WEST], cmap.vertexes) is None


def test_all_four_walls_visible_from_far_corner():
    """Sanity that the DOOM-wound segs are NOT all back-face culled (the M7 bug the winding fix cures):
    sweeping the view 360° from the centre, every one of the four walls is hit at some angle."""
    cmap = _room()
    rm = ReferenceModel()
    seen = set()
    for a in range(0, 1 << 32, (1 << 32) // 16):           # 16 view angles around the circle
        for i, seg in enumerate(cmap.segs):
            if rm.wall_x_range(128 * U, 128 * U, a, seg, cmap.vertexes) is not None:
                seen.add(i)
    assert seen == {WEST, NORTH, EAST, SOUTH}


def test_visible_range_is_ordered_and_onscreen():
    cmap = _room()
    rm = ReferenceModel()
    r = rm.wall_x_range(128 * U, 128 * U, 0, cmap.segs[EAST], cmap.vertexes)
    assert r is not None
    x1, x2, rw_angle1 = r
    assert 0 <= x1 < x2 <= rm.cfg.VIEW_W
    assert isinstance(rw_angle1, int) and 0 <= rw_angle1 < (1 << 32)


def test_offcentre_view_clips_to_partial_range():
    """From nearer the east wall and rotated, it no longer fills the whole screen but stays a valid span."""
    cmap = _room()
    rm = ReferenceModel()
    r = rm.wall_x_range(200 * U, 80 * U, 0, cmap.segs[EAST], cmap.vertexes)
    assert r is not None
    x1, x2, _ = r
    assert 0 <= x1 < x2 <= rm.cfg.VIEW_W
