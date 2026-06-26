"""M12h/M12j (F5) — the full wall-frame oracle: composite every visible wall into a W*H frame (the first
rendered 3D frame), now TEXTURED (M12j). Ties together the M12a–g projection primitives, the M12i baked
BSP, and the M8 textures. Validated on the pre-baked square room (head-on perpendicular wall ⇒ constant
scale ⇒ the wall covers an exact, hand-derivable row band, textured with STEP4) and on the full real
E1M1 (invariants + golden hash). Only ONE-SIDED walls are solid + textured; two-sided openings are
skipped (their upper/lower textures + visplanes are M13). The fj wall renderer diffs this byte-for-byte.
"""
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.reference_model import (
    ReferenceModel, SimState, build_scene, spawn_state, frame_hash, WALL_BG,
)
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
U = 1 << 16
WALL_TOP, WALL_BOT = 0, 75   # the head-on wall's hand-derived row band (see the docstring below)


@pytest.fixture
def rm():
    return ReferenceModel()


@pytest.fixture
def scene():
    return build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")


# ── square room: a head-on wall covers an exact, hand-derived row band ────────

def test_spawn_frame_head_on_wall_band(rm, scene):
    """Spawn at the centre (128,128) facing north (ANG90): the north wall is perpendicular and fills the
    whole viewport. A perpendicular wall head-on has CONSTANT scale (anglea==angleb ⇒ the sines cancel ⇒
    scale = PROJECTION/dist = 80/128 = 0.625), so it covers the same rows in every column.
    wall_screen_span(ceil 128, floor 0, viewz=(0+41)<<16, 0.625): top = 50 - 87*0.625 = -5 (clip 0),
    bottom = 50 + 41*0.625 = 75. So rows [0, 75] are the (textured) wall and [76, 99] are the floor
    visplane (M13: a distance-lit flat, no longer the two-band background) — in EVERY column."""
    cfg = Config()
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    bg = rm.render_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    assert len(frame) == cfg.FB_SIZE
    W, H = cfg.VIEW_W, cfg.VIEW_H
    for x in range(W):
        # floor band below the wall is the M13 floor visplane (differs from the M9 two-band bg)
        assert any(frame[y * W + x] != bg[y * W + x] for y in range(WALL_BOT + 1, H))
        # the wall band differs from the background (it was drawn over)
        assert any(frame[y * W + x] != bg[y * W + x] for y in range(WALL_TOP, WALL_BOT + 1))


def test_spawn_frame_wall_is_textured_not_flat(rm, scene):
    """The wall band is real texture (STEP4), not a single flat shade: the band holds several palette
    indices, and at least some differ from the flat WALL_BG fallback shade."""
    cfg = Config()
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    W = cfg.VIEW_W
    band = [frame[y * W + x] for y in range(WALL_TOP, WALL_BOT + 1) for x in range(W)]
    assert len(set(band)) >= 3                                 # textured (not a constant fill)
    flat = WadFile.from_path(ASSET).colormap()[20][WALL_BG]
    assert any(v != flat for v in band)


def test_spawn_frame_golden_hash(rm, scene):
    """Byte-exact textured golden (the key the fj renderer diffs against, D12). Re-blessed at M13b:
    floors/ceilings are now full-res perspective-textured visplanes (R_DrawPlanes) over the M13a flat tier."""
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    assert frame_hash(frame) == "00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12"


def test_only_faced_wall_drawn_others_culled(rm, scene):
    """Facing east from the centre, the east wall fills every column's wall band; the other three walls
    are back-face/FOV culled, so the same [0,75] band is covered in every column."""
    cfg = Config()
    frame = rm.render_wall_frame(SimState(128 * U, 128 * U, 0, "MAP01"), scene)   # facing east
    bg = rm.render_frame(SimState(128 * U, 128 * U, 0, "MAP01"), scene)
    W = cfg.VIEW_W
    for x in range(W):
        assert any(frame[y * W + x] != bg[y * W + x] for y in range(WALL_TOP, WALL_BOT + 1))


def test_offcentre_view_still_fills_and_clips(rm, scene):
    """From nearer the east wall (200,128) facing east, the wall still covers every column and all rows
    stay within [0, VIEW_H); the frame is well-formed (valid palette indices)."""
    cfg = Config()
    frame = rm.render_wall_frame(SimState(200 * U, 128 * U, 0, "MAP01"), scene)
    bg = rm.render_frame(SimState(200 * U, 128 * U, 0, "MAP01"), scene)
    assert len(frame) == cfg.FB_SIZE and all(0 <= b < 256 for b in frame)
    W, H = cfg.VIEW_W, cfg.VIEW_H
    cols_with_wall = sum(1 for x in range(W)
                         if any(frame[y * W + x] != bg[y * W + x] for y in range(H)))
    assert cols_with_wall == W                                 # close perpendicular wall fills the screen


# ── full real E1M1 (invariants + golden) ────────────────────────────────────

def test_e1m1_wall_frame_textured_and_deterministic():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")             # E1M1 fixture carries PLAYPAL+COLORMAP too
    state = spawn_state(map_wad, "E1M1")
    frame = rm.render_wall_frame(state, scene)
    bg = rm.render_frame(state, scene)
    assert len(frame) == Config().FB_SIZE
    assert sum(1 for a, b in zip(frame, bg) if a != b) > 1000  # walls composited over the background
    assert len(set(frame)) >= 8                                # many palette indices ⇒ real textures
    assert frame == rm.render_wall_frame(state, scene)         # deterministic (D12)
    assert frame_hash(frame) == "db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2"


def test_e1m1_every_pixel_is_a_valid_palette_index():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene)
    assert all(0 <= b < 256 for b in frame)
