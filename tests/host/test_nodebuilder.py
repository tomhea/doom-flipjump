"""Characterization tests for `doomfj.nodebuilder` (the EXP-12 BSP node builder).

The module had zero coverage; these tests pin its STRUCTURAL contract (the conventions its
docstring promises: every seg in exactly one subsector, front/back placement consistent with
`mapcompiler._point_side`, root = last node, NF_SUBSECTOR child encoding, split offsets and
vertex dedup) plus a golden-stability pin over serialized lumps. The golden hashes are
CHARACTERIZATION PINS of the current builder's output, not a spec — if the partition scoring
or serialization is deliberately changed, re-bless them.
"""
import hashlib

from doomfj.mapcompiler import _point_side
from doomfj.nodebuilder import NF_SUBSECTOR, NodeBuilder, initial_segs, lumps
from doomfj.wad import Linedef, Sidedef, WadFile

SQUARE_ROOM = "tests/fixtures/square_room.wad"

# flags: 1 = impassable (one-sided walls), 4 = two-sided
_1S, _2S = 1, 4


def _sd(sector):
    return Sidedef(0, 0, "-", "-", "WALL", sector)


def _ld(v1, v2, front, back=-1, flags=_1S):
    return Linedef(v1, v2, flags, 0, 0, front, back)


def _split_room():
    """Two convex cells side by side: x in [0,256] is sector 0, [256,384] is sector 1,
    separated by one two-sided vertical line at x=256. All one-sided walls front-face the
    interior (DOOM's right=front); the splitter's front faces sector 1 (x > 256)."""
    verts = [(0, 0), (0, 128), (256, 128), (384, 128), (384, 0), (256, 0)]
    sds = [_sd(0), _sd(0), _sd(1), _sd(1), _sd(1), _sd(0), _sd(1), _sd(0)]
    lds = [
        _ld(0, 1, 0),            # west          (sector 0)
        _ld(1, 2, 1),            # top-left      (sector 0)
        _ld(2, 3, 2),            # top-right     (sector 1)
        _ld(3, 4, 3),            # east          (sector 1)
        _ld(4, 5, 4),            # bottom-right  (sector 1)
        _ld(5, 0, 5),            # bottom-left   (sector 0)
        _ld(5, 2, 6, 7, _2S),    # splitter x=256: front=sector 1, back=sector 0
    ]
    return verts, lds, sds


def _convex_square():
    """One convex sector — the shape the builder's docstring promises emits NO nodes."""
    verts = [(0, 0), (0, 128), (128, 128), (128, 0)]
    sds = [_sd(0)] * 4
    lds = [_ld(0, 1, 0), _ld(1, 2, 1), _ld(2, 3, 2), _ld(3, 0, 3)]
    return verts, lds, sds


def _leaf_side_invariant(nb, root):
    """Walk the tree from the root; every subsector's segs must sit on the correct side of
    EVERY ancestor partition (front: _point_side <= 0 at the seg midpoint, back: >= 0 —
    on-the-line covers the collinear segs that ride the partition itself)."""
    seen_ss = set()

    def leaf_segs(ss_idx):
        n, first = nb.out_ss[ss_idx]
        return nb.out_segs[first:first + n]

    def check(child, constraints):
        if child & NF_SUBSECTOR:
            ss = child & ~NF_SUBSECTOR
            assert ss < len(nb.out_ss)
            seen_ss.add(ss)
            for v1, v2, *_ in leaf_segs(ss):
                (x1, y1), (x2, y2) = nb.out_verts[v1], nb.out_verts[v2]
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                for (px, py, pdx, pdy), front in constraints:
                    s = _point_side(px, py, pdx, pdy, mx, my)
                    assert (s <= 0) if front else (s >= 0), \
                        f"seg mid ({mx},{my}) on the wrong side of {(px, py, pdx, pdy)}"
        else:
            assert child < len(nb.out_nodes)
            x, y, dx, dy, _, _, r, l = nb.out_nodes[child]
            part = (x, y, dx, dy)
            check(r, constraints + [(part, True)])
            check(l, constraints + [(part, False)])

    check(root, [])
    assert seen_ss == set(range(len(nb.out_ss)))


def test_convex_room_is_one_leaf_no_nodes():
    verts, lds, sds = _convex_square()
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    assert root == (0 | NF_SUBSECTOR)          # the leaf ref, NF_SUBSECTOR-tagged
    assert nb.out_nodes == []                   # "NODES stays empty (the square-room shape)"
    assert nb.out_ss == [(4, 0)]
    assert len(nb.out_segs) == 4
    assert nb.mixed_leaves == 0


def test_split_room_structural_invariants():
    verts, lds, sds = _split_room()
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()

    # the splitter is the only separating candidate: exactly one node, root is its index
    # (and in general the root is the LAST node record)
    assert len(nb.out_nodes) == 1
    assert root == len(nb.out_nodes) - 1

    # every seg lands in exactly one subsector: firstseg/numsegs tile [0, len(out_segs))
    spans = sorted(nb.out_ss, key=lambda s: s[1])
    cursor = 0
    for n, first in spans:
        assert first == cursor and n > 0
        cursor += n
    assert cursor == len(nb.out_segs)

    # no split was needed: 6 one-sided + 2 splitter segs pass through intact, 4 per leaf
    assert len(nb.out_segs) == len(initial_segs(verts, lds, sds)) == 8
    assert sorted(n for n, _ in nb.out_ss) == [4, 4]
    assert nb.mixed_leaves == 0                 # each leaf single-sector

    # child encoding: leaf refs carry NF_SUBSECTOR with a valid low index; node refs (none
    # here) would have to be earlier records than their parent
    for *_, r, l in [nb.out_nodes[-1]]:
        for child in (r, l):
            if child & NF_SUBSECTOR:
                assert (child & ~NF_SUBSECTOR) < len(nb.out_ss)
            else:
                assert child < len(nb.out_nodes) - 1

    # bbox sanity: DOOM order (top, bottom, left, right)
    for _, _, _, _, bbr, bbl, _, _ in nb.out_nodes:
        for top, bottom, left, right in (bbr, bbl):
            assert top >= bottom and right >= left

    _leaf_side_invariant(nb, root)


def test_split_room_partition_sides_match_point_side():
    """The node's front (right) child holds exactly the sector-1 half (x > 256) — the
    documented `_point_side` < 0 = front convention, checked against real coordinates."""
    verts, lds, sds = _split_room()
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    x, y, dx, dy, _, _, r, l = nb.out_nodes[root]
    for child, front in ((r, True), (l, False)):
        n, first = nb.out_ss[child & ~NF_SUBSECTOR]
        for v1, v2, *_ in nb.out_segs[first:first + n]:
            (x1, y1), (x2, y2) = nb.out_verts[v1], nb.out_verts[v2]
            s = _point_side(x, y, dx, dy, (x1 + x2) / 2, (y1 + y2) / 2)
            assert (s <= 0) if front else (s >= 0)


def test_spanning_walls_are_split_with_exact_offsets_and_deduped_vertices():
    """Top and bottom walls span BOTH cells, so the x=256 partition must split them. The
    split fragments must carry the along-the-linedef offset from the linedef's own start,
    and the split vertices land exactly on the splitter's endpoints (vertex dedup: no new
    vertex records)."""
    verts = [(0, 0), (0, 128), (384, 128), (384, 0), (256, 0), (256, 128)]
    sds = [_sd(0), _sd(0), _sd(1), _sd(1), _sd(1), _sd(0)]
    lds = [
        _ld(0, 1, 0),            # west
        _ld(1, 2, 1),            # top, spans x=0..384
        _ld(2, 3, 2),            # east
        _ld(3, 0, 3),            # bottom, spans x=384..0
        _ld(4, 5, 4, 5, _2S),    # splitter at x=256
    ]
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    assert len(nb.out_nodes) == 1 and root == 0
    # 6 input segs (4 one-sided + 2-sided splitter), 2 splits -> 8 emitted
    assert len(initial_segs(verts, lds, sds)) == 6
    assert len(nb.out_segs) == 8
    # split points (256,128)/(256,0) dedupe onto the splitter's existing vertices
    assert len(nb.out_verts) == 6
    # offsets: distance along the linedef from ITS start — top splits at 256, bottom at 128
    offs = {}
    for _, _, _, ld, _, off in nb.out_segs:
        offs.setdefault(ld, set()).add(off)
    assert offs[1] == {0, 256}                  # top wall fragments
    assert offs[3] == {0, 128}                  # bottom wall (runs 384 -> 0, split after 128)
    assert offs[4] == {0}                       # splitter itself never split
    _leaf_side_invariant(nb, root)


# ── golden-stability pins (characterization, not spec — re-bless on deliberate change) ──

def _lump_hash(nb):
    d = lumps(nb)
    h = hashlib.sha256()
    for name in ("VERTEXES", "SEGS", "SSECTORS", "NODES"):
        h.update(name.encode() + b"\0" + d[name])
    return h.hexdigest()


# computed from the CURRENT builder (this session) and baked in as characterization pins
SPLIT_ROOM_GOLDEN = "04371eda1e3c02e8d1d732359995d767755a95731d769f332c6d5d9bbea8230e"
SQUARE_ROOM_GOLDEN = "974cb67bef35a96ff912020e6579ef9f56d0ac8b54f57caca6cd2256dcf94327"


def test_split_room_lumps_golden():
    verts, lds, sds = _split_room()
    nb = NodeBuilder(verts, lds, sds)
    nb.build()
    assert _lump_hash(nb) == SPLIT_ROOM_GOLDEN


def test_square_room_wad_lumps_golden():
    """Rebuild the BSP for the square_room fixture's geometry and pin the serialized lumps."""
    w = WadFile.from_path(SQUARE_ROOM)
    verts = [(v.x, v.y) for v in w.vertexes("MAP01")]
    nb = NodeBuilder(verts, w.linedefs("MAP01"), w.sidedefs("MAP01"))
    root = nb.build()
    _leaf_side_invariant(nb, root)
    assert _lump_hash(nb) == SQUARE_ROOM_GOLDEN
