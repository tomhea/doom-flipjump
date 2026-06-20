"""M7 (H3) — map compiler / BSP node builder tests.

Builds the BSP from raw geometry (owner decision: build, not bake). Covers: seg construction, the
convex base case (the square-room fixture -> 1 subsector, 0 nodes), the recursive split path on a
concave (L-shaped) loop (point->subsector traversal stays consistent; linedef coverage preserved),
and the .fj emitter (packed streams round-trip + counts, BSP-as-code mode, collision data, assembles
flat — R4)."""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.harness import W
from doomfj.wad import WadFile, Linedef, Sidedef
from doomfj.mapcompiler import (
    NF_SUBSECTOR,
    Seg,
    bam16,
    build_bsp,
    build_segs,
    compile_bsp,
    compile_map,
)

FIXTURE = Path("tests/fixtures/test.wad")


def _wad():
    return WadFile.from_path(FIXTURE)


# ── segs + convex base case ──

def test_build_segs_square_room():
    wad = _wad()
    verts = [(v.x, v.y) for v in wad.vertexes("MAP01")]
    segs = build_segs(verts, wad.linedefs("MAP01"), wad.sidedefs("MAP01"))
    assert len(segs) == 4  # 4 one-sided linedefs -> 4 front segs
    # axis-aligned angles: E=0, N=0x4000, W=0x8000, S=0xC000
    assert [s.angle for s in segs] == [0, 0x4000, 0x8000, 0xC000]
    assert all(s.side == 0 and s.offset == 0 for s in segs)
    assert [s.linedef for s in segs] == [0, 1, 2, 3]


def test_bam16_cardinals():
    assert bam16(1, 0) == 0
    assert bam16(0, 1) == 0x4000
    assert bam16(-1, 0) == 0x8000
    assert bam16(0, -1) == 0xC000


def test_convex_room_one_subsector():
    bsp = compile_bsp(_wad(), "MAP01")
    assert len(bsp.subsectors) == 1
    assert bsp.subsectors[0].numsegs == 4 and bsp.subsectors[0].firstseg == 0
    assert bsp.nodes == []
    assert bsp.root == (0 | NF_SUBSECTOR)  # whole map is subsector 0


# ── recursive split path (concave L-shape) ──

def _l_shape_segs():
    # concave hexagon (an L): concave at v3=(1,1). CCW loop.
    verts = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    loop = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]
    segs = [Seg(a, b, 0, i, 0, 0) for i, (a, b) in enumerate(loop)]
    return verts, segs


def _traverse(bsp, verts, x, y):
    """Walk the node tree to the subsector containing (x,y) — right=front (side<0), left=back."""
    ref = bsp.root
    while not (ref & NF_SUBSECTOR):
        n = bsp.nodes[ref]
        side = n.dx * (y - n.y) - n.dy * (x - n.x)
        ref = n.right if side < 0 else n.left
    return ref & ~NF_SUBSECTOR


def test_concave_l_shape_splits():
    verts, segs = _l_shape_segs()
    bsp = build_bsp(verts, segs)
    # a concave loop cannot be one subsector -> at least one partition node + >= 2 subsectors
    assert len(bsp.nodes) >= 1
    assert len(bsp.subsectors) >= 2


def test_traversal_lands_in_valid_subsector():
    verts, segs = _l_shape_segs()
    bsp = build_bsp(verts, segs)
    # every interior sample point traverses to an in-range subsector (deterministic, terminates)
    for x in range(3):
        for y in range(3):
            ss = _traverse(bsp, verts, x + 0.5, y + 0.5)
            assert 0 <= ss < len(bsp.subsectors)


def test_split_preserves_linedef_coverage():
    verts, segs = _l_shape_segs()
    bsp = build_bsp(verts, segs)
    # splitting subdivides segs but keeps their linedef — every original line still represented
    assert {s.linedef for s in bsp.segs} == {s.linedef for s in segs}


# ── .fj emission ──

def test_compile_map_streams_counts_and_roundtrip():
    src = compile_map(_wad(), "MAP01", mode="streams")
    assert "map01_segs:" in src and "map01_ssectors:" in src and "map01_nodes:" in src
    assert "map01_root = 0x8000" in src
    # collision data (D1): LINEDEFS + VERTEXES streams present
    assert "map01_linedefs:" in src and "map01_vertexes:" in src
    # round-trip the VERTEXES stream: 4 verts x 2 fields x 2 bytes = 16 packed-byte ops
    vtx_block = src.split("map01_vertexes:")[1].split("map01_")[0]
    assert vtx_block.count("* dw") == 4 * 2 * 2


def test_compile_map_code_mode():
    src = compile_map(_wad(), "MAP01", mode="code")
    assert "map01_bspcode" in src
    assert "subsector 0" in src


def test_compile_map_unknown_mode_rejected():
    with pytest.raises(ValueError):
        compile_map(_wad(), "MAP01", mode="bogus")


def test_compiled_streams_assemble_flat(tmp_path):
    src = compile_map(_wad(), "MAP01", mode="streams")
    prog = "stl.startup_and_init_all\nstl.loop\n" + src + "\n"
    p = tmp_path / "map.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp_path / "map.fjm"
    fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
    term = fj.run(out, print_time=False, print_termination=False)
    assert str(term.storage_mode) == "flat"  # R4
