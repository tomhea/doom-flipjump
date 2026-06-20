"""M9 — tests for the H5 reference model / oracle (src/doomfj/reference_model.py).

The oracle is the golden truth M11+ diffs against (D12), so every expected value here is
hand-derived from the shared kernels (tables.py / fixedpoint.py) and the committed fixtures —
not lifted from the implementation. See docs/m9-oracle.txt for the worked derivations.
"""
import hashlib

import pytest

from doomfj.config import Config
from doomfj.mapcompiler import Node, SubSector, CompiledMap, NF_SUBSECTOR
from doomfj.reference_model import (
    ReferenceModel, SimState, Scene, spawn_state, build_scene, frame_hash,
    ANG90, FORWARD_MOVE, ANGLE_TURN, CEIL_BG, FLOOR_BG,
)
from doomfj.wad import WadFile

MAP_WAD = "tests/fixtures/test.wad"        # geometry only (square room, DOOM names)
ASSET_WAD = "tests/fixtures/freedoom_assets.wad"  # PLAYPAL + COLORMAP (graphics)


@pytest.fixture
def rm():
    return ReferenceModel()


@pytest.fixture
def scene():
    return build_scene(WadFile.from_path(MAP_WAD), WadFile.from_path(ASSET_WAD), "MAP01")


# ── spawn + sim ────────────────────────────────────────────────────────────

def test_spawn_state():
    """THINGS player-1 start at (128,128) facing 90deg => 16.16 pos + ANG90 (BAM)."""
    st = spawn_state(WadFile.from_path(MAP_WAD), "MAP01")
    assert st == SimState(x=128 << 16, y=128 << 16, angle=ANG90, level="MAP01")
    assert ANG90 == 0x40000000  # 90deg as BAM (full circle = 2**32)


def test_read_sin_cos(rm):
    """read_sin/read_cos over the shared finesine table; cosine shares the table (+N/4, M6)."""
    one = 1 << 16  # 1.0 in 16.16
    assert rm.read_sin(0) == 0 and rm.read_cos(0) == one          # sin0=0, cos0=1
    assert rm.read_sin(ANG90) == one and rm.read_cos(ANG90) == 0  # sin90=1, cos90=0
    assert rm.read_cos(3 * ANG90) == 0                            # cos270=0 (wrap mod N)


def test_step_forward_at_spawn(rm):
    """Forward at spawn (facing +y): dx=FixedMul(M,cos90)=0, dy=FixedMul(M,sin90)=M; angle unchanged."""
    st = spawn_state(WadFile.from_path(MAP_WAD), "MAP01")
    out = rm.step_sim(st, {"forward": True})
    assert out.x == 128 << 16                       # cos90==0 => x unchanged
    assert out.y == (128 << 16) + FORWARD_MOVE      # 0xB20000 (178<<16)
    assert out.y == 0x00B20000
    assert out.angle == ANG90


def test_step_back_at_spawn(rm):
    """Back at spawn: dy=FixedMul(-M,sin90)=-M => y decreases by one move step (signed multiply)."""
    st = spawn_state(WadFile.from_path(MAP_WAD), "MAP01")
    out = rm.step_sim(st, {"back": True})
    assert out.x == 128 << 16
    assert out.y == (128 << 16) - FORWARD_MOVE      # 0x4E0000 (78<<16)


def test_step_turn_left(rm):
    """Turn-left adds ANGLE_TURN (BAM); position unchanged when not moving."""
    st = spawn_state(WadFile.from_path(MAP_WAD), "MAP01")
    out = rm.step_sim(st, {"turn_left": True})
    assert out.angle == (ANG90 + ANGLE_TURN) & 0xFFFFFFFF  # 0x42800000
    assert out.angle == 0x42800000
    assert (out.x, out.y) == (st.x, st.y)


# ── BSP point location (permanent renderer/sim primitive) ───────────────────

def test_point_in_subsector_square(rm, scene):
    """The convex square room is one subsector (root=0x8000): every interior point maps to 0."""
    assert rm.point_in_subsector(scene.cmap, 128, 128) == 0
    assert rm.point_in_subsector(scene.cmap, 10, 240) == 0


def test_point_in_subsector_node_walk(rm):
    """One hand-built node: partition line (0,0)+t(0,1). side = -x => x>0 front/right(0), x<0 back/left(1),
    x==0 on-line counts as front/right (DOOM convention). Exercises the signed side test + walk order."""
    node = Node(x=0, y=0, dx=0, dy=1, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)
    cmap = CompiledMap(vertexes=[], segs=[], subsectors=[SubSector(0, 0), SubSector(0, 0)],
                       nodes=[node], root=0)
    assert rm.point_in_subsector(cmap, 10, 5) == 0    # right / front
    assert rm.point_in_subsector(cmap, -10, 5) == 1   # left / back
    assert rm.point_in_subsector(cmap, 0, 5) == 0     # on the line => front


# ── render: the spawn frame (hand-checked) ──────────────────────────────────

def test_render_frame_spawn(rm, scene):
    """Spawn frame: ceiling band (top VIEW_H/2 rows) and floor band, each colormap-shaded at the
    spawn sector light (160 => row 160>>3=20). Byte-exact vs an independently built expectation."""
    cfg = Config()
    cm = WadFile.from_path(ASSET_WAD).colormap()
    ceil, floor = cm[20][CEIL_BG], cm[20][FLOOR_BG]
    assert (ceil, floor) == (0, 109)  # cm[20][0]=0, cm[20][96]=109 (ground-truthed)

    frame = rm.render_frame(spawn_state(WadFile.from_path(MAP_WAD), "MAP01"), scene)
    assert len(frame) == cfg.FB_SIZE == 16000

    horizon = cfg.VIEW_H // 2
    expected = bytearray(cfg.FB_SIZE)
    for y in range(cfg.VIEW_H):
        val = ceil if y < horizon else floor
        for x in range(cfg.VIEW_W):
            expected[y * cfg.VIEW_W + x] = val
    assert frame == bytes(expected)


def test_frame_hash_is_sha256(rm, scene):
    """frame_hash is the sha256 the present layer logs per frame (D12)."""
    frame = rm.render_frame(spawn_state(WadFile.from_path(MAP_WAD), "MAP01"), scene)
    assert frame_hash(frame) == hashlib.sha256(frame).hexdigest()
    assert len(frame_hash(frame)) == 64
