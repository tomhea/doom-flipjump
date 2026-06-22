"""M12i (H3) — map compiler / BSP **bake** tests.

The BSP is no longer built; it is parsed from the WAD's precompiled SEGS/SSECTORS/NODES lumps (the
M7 recursive builder is gone). Covers: the raw lump parsers (wad.segs/subsectors/nodes), bake_bsp on
the pre-baked square room (convex ⇒ 1 subsector / 4 segs / 0 nodes / root 0x8000) and on the full
real E1M1 (counts + a node-tree root + a render-order permutation invariant), the precondition
(a map without baked BSP lumps raises), and the .fj emitter (baked streams round-trip + counts,
BSP-as-code mode, assembles flat — R4).
"""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.harness import W
from doomfj.mapcompiler import NF_SUBSECTOR, bake_bsp, compile_map
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile, WadSeg, WadSubSector, WadNode

ROOM = Path("tests/fixtures/square_room.wad")            # pre-baked DOOM-wound square room
E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")          # full real level (baked node tree)


def _room():
    return WadFile.from_path(ROOM)


# ── raw lump parsers ─────────────────────────────────────────────────────────

def test_wad_segs_parser():
    segs = _room().segs("MAP01")
    assert len(segs) == 4 and all(isinstance(s, WadSeg) for s in segs)
    # one seg per one-sided linedef; DOOM-wound (interior on the seg's right), all front-direction
    assert [s.angle for s in segs] == [0x4000, 0x0000, 0xC000, 0x8000]
    assert [(s.v1, s.v2) for s in segs] == [(0, 3), (3, 2), (2, 1), (1, 0)]
    assert all(s.direction == 0 and s.offset == 0 for s in segs)
    assert [s.linedef for s in segs] == [0, 1, 2, 3]


def test_wad_subsectors_and_nodes_parser():
    wad = _room()
    ss = wad.subsectors("MAP01")
    assert ss == [WadSubSector(numsegs=4, firstseg=0)]
    assert wad.nodes("MAP01") == []                       # convex room ⇒ no partition nodes


def test_square_room_fixture_is_reproducible():
    """The committed pre-baked fixture is exactly what its builder emits (not opaque/tampered)."""
    from tests.fixtures.make_square_room_wad import build_square_room_wad
    assert ROOM.read_bytes() == build_square_room_wad()


# ── bake on the convex square room ───────────────────────────────────────────

def test_bake_square_room_one_subsector():
    bsp = bake_bsp(_room(), "MAP01")
    assert len(bsp.segs) == 4
    assert bsp.subsectors == bsp.subsectors[:1] and bsp.subsectors[0].numsegs == 4
    assert bsp.subsectors[0].firstseg == 0
    assert bsp.nodes == []
    assert bsp.root == (0 | NF_SUBSECTOR)                 # whole map is subsector 0
    assert bsp.vertexes == [(0, 0), (256, 0), (256, 256), (0, 256)]


# ── bake on the full real E1M1 (the strong test bed) ─────────────────────────

def test_bake_e1m1_counts_and_node_root():
    bsp = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    assert len(bsp.segs) == 2057
    assert len(bsp.subsectors) == 682
    assert len(bsp.nodes) == 681
    # a real multi-node tree: DOOM's root is the LAST node (not a subsector leaf)
    assert bsp.root == 680 and not (bsp.root & NF_SUBSECTOR)
    # every subsector's seg run stays inside the seg list
    assert all(0 <= ss.firstseg and ss.firstseg + ss.numsegs <= len(bsp.segs)
               for ss in bsp.subsectors)
    # every seg references a real vertex / linedef
    assert all(0 <= s.v1 < len(bsp.vertexes) and 0 <= s.v2 < len(bsp.vertexes) for s in bsp.segs)


def test_bake_e1m1_render_order_is_permutation():
    """The baked node tree walks: from the spawn the BSP visits every subsector exactly once."""
    bsp = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    order = ReferenceModel().bsp_render_order(bsp, -416, 256)   # E1M1 player-1 start
    assert sorted(order) == list(range(len(bsp.subsectors)))


def test_bake_missing_bsp_lumps_raises():
    """Precondition: baking a map whose WAD lacks the baked SEGS/SSECTORS/NODES is an error (the M3
    test.wad carries no BSP — only baked WADs are bakeable, by design)."""
    with pytest.raises(KeyError):
        bake_bsp(WadFile.from_path("tests/fixtures/test.wad"), "MAP01")


# ── .fj emission ─────────────────────────────────────────────────────────────

def test_compile_map_streams_counts_and_roundtrip():
    src = compile_map(_room(), "MAP01", mode="streams")
    assert "map01_segs:" in src and "map01_ssectors:" in src and "map01_nodes:" in src
    assert "map01_root = 0x8000" in src
    assert "map01_linedefs:" in src and "map01_vertexes:" in src    # collision data (D1)
    # round-trip the VERTEXES stream: 4 verts x 2 fields x 2 bytes = 16 packed-byte ops
    vtx_block = src.split("map01_vertexes:")[1].split("map01_")[0]
    assert vtx_block.count("* dw") == 4 * 2 * 2
    # the baked SEGS stream: 4 segs x 6 fields x 2 bytes
    seg_block = src.split("map01_segs:")[1].split("map01_")[0]
    assert seg_block.count("* dw") == 4 * 6 * 2


def test_compile_map_code_mode():
    src = compile_map(_room(), "MAP01", mode="code")
    assert "map01_bspcode" in src
    assert "subsector 0" in src


def test_compile_map_unknown_mode_rejected():
    with pytest.raises(ValueError):
        compile_map(_room(), "MAP01", mode="bogus")


def test_compiled_streams_assemble_flat(tmp_path):
    src = compile_map(_room(), "MAP01", mode="streams")
    prog = "stl.startup_and_init_all\nstl.loop\n" + src + "\n"
    p = tmp_path / "map.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp_path / "map.fjm"
    fj.assemble([p.resolve()], out, memory_width=W, print_time=False)
    term = fj.run(out, print_time=False, print_termination=False)
    assert str(term.storage_mode) == "flat"  # R4
