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
from doomfj.mapcompiler import (
    NF_SUBSECTOR, MASK40, CompiledMap, Node, SubSector, bake_bsp, compile_map, _bsp_as_code,
)
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile, WadSeg, WadSubSector, WadNode

ROOM = Path("tests/fixtures/square_room.wad")            # pre-baked DOOM-wound square room
E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")          # full real level (baked node tree)
PROJECTION_FJ = Path("src/fj/projection.fj")             # provides proj.point_on_side (the side test)


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


# ── BSP-as-code WALK: emitted front-to-back order byte-exact vs bsp_render_order (M12ff) ──
# _bsp_as_code emits the BSP traversal as fj CODE (opt #7): per node a proj.point_on_side test ->
# branch to the NEAR child subtree first (per-node stl.fcall/fret recursion), leaves emit their
# subsector index (4 hex digits + newline). The emitted walk reads the viewer from globals vx,vy and
# halts via `bsp_done`. Verified on small hand-built trees: convex (no nodes), a single partition node,
# and a 2-level tree (root node -> two child nodes -> 4 leaves) that exercises the fcall recursion +
# return. The printed order must match reference_model.bsp_render_order exactly, from several viewpoints.

def _convex_map():
    """No nodes — the whole map is subsector 0 (like the square room). Order is always [0]."""
    return CompiledMap(vertexes=[(0, 0)], segs=[], subsectors=[SubSector(1, 0)], nodes=[], root=0 | NF_SUBSECTOR)


def _two_leaf_map():
    """One vertical partition (x=0, dir +y) over two leaf subsectors. side>0 (x<0) -> left."""
    node = Node(x=0, y=0, dx=0, dy=1, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)
    return CompiledMap(vertexes=[(0, 0)], segs=[], subsectors=[SubSector(1, 0), SubSector(1, 1)],
                       nodes=[node], root=0)


def _deep_map():
    """A 2-level tree exercising recursion: root (node 2, vertical x=0) -> node 0 (front, horizontal
    y=10) over subsectors 0/1 and node 1 (back, horizontal y=-10) over subsectors 2/3."""
    n0 = Node(x=0, y=10,  dx=1, dy=0, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)
    n1 = Node(x=0, y=-10, dx=1, dy=0, right=2 | NF_SUBSECTOR, left=3 | NF_SUBSECTOR)
    root = Node(x=0, y=0, dx=0, dy=1, right=0, left=1)   # right=node0, left=node1
    return CompiledMap(vertexes=[(0, 0)], segs=[],
                       subsectors=[SubSector(1, i) for i in range(4)], nodes=[n0, n1, root], root=2)


def _run_bsp_walk(tmp_path, name, cmap, vx, vy):
    """Emit cmap's BSP-as-code, run the walk from (vx,vy), assert the printed subsector order matches
    reference_model.bsp_render_order byte-exact."""
    code = _bsp_as_code(name, cmap, done_label="bsp_done")
    prog = "\n".join([
        "stl.startup_and_init_all",
        f"hex.set 10, vx, {vx & MASK40}", f"hex.set 10, vy, {vy & MASK40}",
        f";{name}_bspcode_walk",
        "bsp_done:", "stl.loop",
        "vx: hex.vec 10", "vy: hex.vec 10",
        code,
    ]) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    expected = "".join(f"{ss:04x}\n" for ss in ReferenceModel().bsp_render_order(cmap, vx, vy)).encode()
    ok = fj.assemble_and_run_test_output(
        [PROJECTION_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name} @ ({vx},{vy}): emitted BSP order != bsp_render_order"


VIEWPOINTS = [(5, 20), (-5, -20), (5, -20), (-5, 20), (0, 0), (5, 0)]


def test_bsp_code_convex_walk(tmp_path):
    for vx, vy in VIEWPOINTS:
        _run_bsp_walk(tmp_path, "cvx", _convex_map(), vx, vy)


def test_bsp_code_two_leaf_walk(tmp_path):
    for vx, vy in VIEWPOINTS:
        _run_bsp_walk(tmp_path, "two", _two_leaf_map(), vx, vy)


def test_bsp_code_deep_walk(tmp_path):
    """The 2-level tree: exercises stl.fcall into a child node + fret return, both near/far branches."""
    for vx, vy in VIEWPOINTS:
        _run_bsp_walk(tmp_path, "deep", _deep_map(), vx, vy)


def test_bsp_code_e1m1_order_byte_exact_vs_oracle(tmp_path):
    """The full real E1M1 bake (681 nodes, 682 subsectors): _bsp_as_code emits the whole BSP walk as
    code; the shared proj.point_on_side_leaf fcall leaf (mantra #9) keeps it assemblable (~10s, ~0.6MB
    .fjm — vs the >10-min blow-up of unrolling the side math per node). The emitted front-to-back
    subsector order is byte-exact vs reference_model.bsp_render_order from several viewpoints. Assembled
    ONCE (the viewer is read from stdin as signed decimal) and re-run per viewpoint."""
    import time
    cmap = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    assert len(cmap.nodes) == 681 and len(cmap.subsectors) == 682
    code = _bsp_as_code("e1m1", cmap, done_label="bsp_done")
    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.input_dec_int 10, vx, bad", "hex.input_dec_int 10, vy, bad",
        ";e1m1_bspcode_walk", "bsp_done:", "stl.loop", "bad:", "stl.loop",
        "vx: hex.vec 10", "vy: hex.vec 10", code,
    ]) + "\n"
    p = tmp_path / "e1m1_bsp.fj"
    p.write_text(prog, encoding="utf-8")
    out = tmp_path / "e1m1_bsp.fjm"
    t = time.perf_counter()
    fj.assemble([PROJECTION_FJ.resolve(), p.resolve()], out, memory_width=W, print_time=False)
    assemble_s = time.perf_counter() - t
    assert assemble_s < 120, f"E1M1 BSP-as-code assemble {assemble_s:.0f}s exceeds the R-2 CI guard"
    rm = ReferenceModel()
    for vx, vy in [(-416, 256), (0, 256), (256, -256), (2048, -3680)]:
        expected = "".join(f"{s:04x}\n" for s in rm.bsp_render_order(cmap, vx, vy)).encode()
        ok = fj.run_test_output(out, f"{vx}\n{vy}\n".encode(), expected,
                                should_raise_assertion_error=False)
        assert ok, f"E1M1 BSP-as-code order @ ({vx},{vy}) != bsp_render_order"


def test_bsp_code_node_consts_self_zero_after_walk(tmp_path):
    """M12qq — the node partition consts (cpx/cpy/cdx/cdy) are baked with hex.xor_by + xor-INVOLUTION
    self-zeroing: each node SETs them (0->vals), the side test READS them, then a second fcall CLEARs them
    (vals->0) before recursing. So after the whole walk every partition reg must be back to 0 — the
    involution invariant. A missing CLEAR would leave them at the XOR-accumulation of every visited node's
    consts (nonzero for the deep tree: cpy = 10 ^ -10 ^ 0, cdy = 0 ^ 0 ^ 1), so this directly catches a
    broken/absent involution (the M12qq regression). Distinct from the order tests (which catch the WRONG
    side test) — this asserts the post-walk zero state."""
    cmap = _deep_map()                                       # 3 nodes with distinct partition consts
    # empty subsector action: the nodes still run their SET/USE/CLEAR (what we test), but the leaves print
    # nothing, so the only output is the post-walk partition-reg dump below.
    code = _bsp_as_code("z", cmap, done_label="bsp_done", subsector_action=lambda s: [])
    prog = "\n".join([
        "stl.startup_and_init_all",
        "hex.set 10, vx, 5", "hex.set 10, vy, 20",
        ";z_bspcode_walk", "bsp_done:",
        # after the walk, the involution must have returned every partition reg to 0 (40 '0' digits total).
        # the shared partition-const regs are {pfx}_bspcode_{cpx,cpy,cdx,cdy} (here pfx="z").
        "hex.print_as_digit 10, z_bspcode_cpx, 0", "hex.print_as_digit 10, z_bspcode_cpy, 0",
        "hex.print_as_digit 10, z_bspcode_cdx, 0", "hex.print_as_digit 10, z_bspcode_cdy, 0",
        "stl.loop",
        "vx: hex.vec 10", "vy: hex.vec 10", code,
    ]) + "\n"
    p = tmp_path / "selfzero.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [PROJECTION_FJ.resolve(), p.resolve()], b"", b"0" * 40,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, "node partition consts did not self-zero after the walk (broken xor-involution)"
