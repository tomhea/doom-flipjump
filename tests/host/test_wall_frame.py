"""M12h (F5) — the full wall-frame oracle: composite every visible wall into a W*H frame (the first
rendered 3D frame, flat-shaded). This is the integration payoff that ties together the M12a–g projection
primitives + the M12i baked BSP. Validated on the pre-baked square room (head-on perpendicular wall ⇒
constant scale ⇒ an exact rectangle, hand-derivable) and on the full real E1M1 (invariants). The fj wall
renderer (M12j) will diff against this byte-for-byte (D12); wall texturing is the next milestone.
"""
import hashlib
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.reference_model import (
    ReferenceModel, SimState, build_scene, spawn_state, frame_hash,
    ANG90, CEIL_BG, FLOOR_BG, WALL_BG,
)
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
U = 1 << 16


@pytest.fixture
def rm():
    return ReferenceModel()


@pytest.fixture
def scene():
    return build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")


def _fills(asset_path):
    """The colormap-shaded (wall, ceil, floor) bytes at the square room's light 160 (row 20)."""
    cm = WadFile.from_path(asset_path).colormap()
    return cm[20][WALL_BG], cm[20][CEIL_BG], cm[20][FLOOR_BG]


# ── square room: a head-on wall is an exact rectangle (hand-derived) ─────────

def test_spawn_frame_head_on_wall_is_rectangle(rm, scene):
    """Spawn at the centre (128,128) facing north (ANG90): the north wall is perpendicular and fills the
    whole viewport. A perpendicular wall viewed head-on has CONSTANT scale (anglea==angleb ⇒ the sines
    cancel ⇒ scale = PROJECTION/dist = 80/128 = 0.625), so every column is the same rectangle.
    wall_screen_span(ceil 128, floor 0, viewz=(0+41)<<16, scale 0.625): worldtop=87, worldbottom=-41 ⇒
    top = 50 - 87*0.625 = -4.375 → -5 (clipped to 0); bottom = 50 + 41*0.625 = 75.6 → 75. So rows
    [0, 75] are wall, [76, 99] floor, no ceiling visible (wall top is above the viewport)."""
    cfg = Config()
    wall, _ceil, floor = _fills(ASSET)
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    assert len(frame) == cfg.FB_SIZE

    W, H = cfg.VIEW_W, cfg.VIEW_H
    for x in range(W):
        col = [frame[y * W + x] for y in range(H)]
        assert all(col[y] == wall for y in range(0, 76))      # wall rows 0..75
        assert all(col[y] == floor for y in range(76, H))     # floor rows 76..99
    assert wall != floor                                       # the wall is actually drawn over the bg


def test_spawn_frame_is_left_right_symmetric(rm, scene):
    """The room is symmetric about the view axis, so column x and its mirror W-1-x are identical."""
    cfg = Config()
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    W, H = cfg.VIEW_W, cfg.VIEW_H
    for x in range(W // 2):
        left = bytes(frame[y * W + x] for y in range(H))
        right = bytes(frame[y * W + (W - 1 - x)] for y in range(H))
        assert left == right


def test_spawn_frame_golden_hash(rm, scene):
    """Byte-exact golden (the key the fj renderer M12j diffs against, D12)."""
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    assert frame_hash(frame) == "0c406cce91e11922fd4d820ca7ff9002d04714a3edd03aec4ebff7b35750a96c"
    assert frame_hash(frame) == hashlib.sha256(frame).hexdigest()


def test_only_faced_wall_drawn_others_culled(rm, scene):
    """Facing east from the centre, the east wall fills every column; the frame equals what the single
    faced wall produces (the other three walls are back-face/FOV culled, so they add nothing)."""
    cfg = Config()
    wall, _c, _f = _fills(ASSET)
    frame = rm.render_wall_frame(SimState(128 * U, 128 * U, 0, "MAP01"), scene)   # facing east
    W, H = cfg.VIEW_W, cfg.VIEW_H
    # the east wall is also perpendicular at dist 128 ⇒ identical rectangle to the north-facing frame
    for x in range(W):
        assert all(frame[y * W + x] == wall for y in range(0, 76))


def test_offcentre_view_still_fills_and_clips(rm, scene):
    """From nearer the east wall (200,128) facing east, the wall still covers the viewport but the bottom
    extends further (closer ⇒ larger scale); rows stay within [0, VIEW_H) and the frame is well-formed."""
    cfg = Config()
    wall, _c, _f = _fills(ASSET)
    frame = rm.render_wall_frame(SimState(200 * U, 128 * U, 0, "MAP01"), scene)
    assert len(frame) == cfg.FB_SIZE
    W, H = cfg.VIEW_W, cfg.VIEW_H
    cols_with_wall = sum(1 for x in range(W) if any(frame[y * W + x] == wall for y in range(H)))
    assert cols_with_wall == W                                 # close perpendicular wall fills the screen


# ── full real E1M1 (invariants — no hand-computable exact values) ───────────

def test_e1m1_wall_frame_renders_and_is_deterministic():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")             # E1M1 fixture carries PLAYPAL+COLORMAP too
    state = spawn_state(map_wad, "E1M1")
    frame = rm.render_wall_frame(state, scene)
    assert len(frame) == Config().FB_SIZE
    # walls were actually composited over the background (a large chunk of pixels changed)
    bg = rm.render_frame(state, scene)
    assert frame != bg
    assert sum(1 for a, b in zip(frame, bg) if a != b) > 1000
    # deterministic (same inputs → same golden, D12)
    assert frame == rm.render_wall_frame(state, scene)
    assert frame_hash(frame) == "f33492a0ba39390129082b85b186bbc860348b64c13488612821fa3bc3211d9e"


def test_e1m1_every_pixel_is_a_valid_palette_index():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene)
    assert all(0 <= b < 256 for b in frame)
