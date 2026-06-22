"""M12e (F5) — the perspective scale: R_StoreWallRange setup (`wall_setup` → rw_normalangle + rw_distance)
+ `R_ScaleFromGlobalAngle` (the per-column wall scale, 16.16 pixels per world unit). Validated on the
committed square room (test.wad MAP01, view at centre): each wall's perpendicular distance is the room
half-width, and a perpendicular wall straight ahead scales to exactly PROJECTION/distance. This scale
turns into wall screen heights in M12f; the fj renderer reproduces it (R6/D12).
"""
from pathlib import Path

from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ANG90, ANGLE_MASK, SCALE_MIN, SCALE_MAX, ReferenceModel
from doomfj.wad import WadFile

ROOM = Path("tests/fixtures/square_room.wad")
U = 1 << 16
# seg index -> wall, for the DOOM-wound square room (CW boundary: west,north,east,south)
WEST, NORTH, EAST, SOUTH = 0, 1, 2, 3


def _room():
    return bake_bsp(WadFile.from_path(ROOM), "MAP01")   # 256x256 square, verts (0,0)..(256,256)


# ── R_StoreWallRange setup: rw_normalangle + rw_distance ────────────────────

def test_rw_distance_is_perpendicular():
    """From the room centre (128,128) every wall is 128 units away (perpendicular), within finesine
    quantization; rw_normalangle = seg.angle_BAM + ANG90 (DOOM's native winding, baked segs)."""
    cmap = _room()
    rm = ReferenceModel()
    for seg in cmap.segs:
        nrm, rwd = rm.wall_setup(128 * U, 128 * U, seg, cmap.vertexes)
        assert nrm == ((seg.angle << 16) + ANG90) & ANGLE_MASK
        assert abs(rwd - 128 * U) <= U                     # ~128, <=1 map unit (LUT quantization)


# ── R_ScaleFromGlobalAngle ──────────────────────────────────────────────────

def test_scale_perpendicular_centre_exact():
    """East wall straight ahead from centre (dist 128), centre column: scale = PROJECTION/dist = 80/128 =
    0.625 exactly (all sines are 1.0 = 65536, no quantization). The east wall (x=256) is seg EAST(2);
    its DOOM-wound seg angle 0xC000 (pointing south) + ANG90 ⇒ normal 0 (points +x, toward the viewer)."""
    cmap = _room()
    rm = ReferenceModel()
    seg = cmap.segs[EAST]                                   # (256,256)->(256,0), angle 0xC000 -> normal 0
    nrm, rwd = rm.wall_setup(128 * U, 128 * U, seg, cmap.vertexes)
    assert nrm == 0 and abs(rwd - 128 * U) <= 4            # 128, within finesine quantization (~1 ULP)
    assert rm.scale_from_global_angle(0, 0, nrm, rwd) == 40960   # 0.625 in 16.16 (exact: all sines 1.0)


def test_scale_increases_when_closer():
    cmap = _room()
    rm = ReferenceModel()
    seg = cmap.segs[EAST]                                   # east wall
    n1, d1 = rm.wall_setup(128 * U, 128 * U, seg, cmap.vertexes)   # dist 128
    n2, d2 = rm.wall_setup(200 * U, 128 * U, seg, cmap.vertexes)   # dist 56 (closer to the east wall)
    assert rm.scale_from_global_angle(0, 0, n2, d2) > rm.scale_from_global_angle(0, 0, n1, d1)


def test_scale_clamps_to_bounds():
    rm = ReferenceModel()
    assert rm.scale_from_global_angle(0, 0, 0, 0) == SCALE_MAX          # den 0 -> ceiling
    assert rm.scale_from_global_angle(0, 0, 0, 1 * U) == SCALE_MAX      # very close -> clamped up
    assert rm.scale_from_global_angle(0, 0, 0, 30000 * U) == SCALE_MIN   # very far -> clamped down
