"""Behavioural properties of `doomfj.nodebuilder` that the characterization suite leaves open.

`test_nodebuilder.py` pins the builder's STRUCTURE on two hand-made rooms plus two golden lump
hashes. This file pins what the shipped program actually depends on, and does it on a map with
real recursion (`tests/fixtures/e1m1_lite.wad`: 836 linedefs -> 470 nodes / 471 leaves):

  * POINT LOCATION. `reference_model.point_in_subsector` descends this tree to pick viewz and
    thing leaf ownership, and it reads ONLY `segs[firstseg]` to name a leaf's sector. So the
    tree must agree with an independent oracle (nearest +x ray crossing over raw LINEDEFS /
    SIDEDEFS) on every walkable point, and no leaf may front two sectors. The failure this
    hunts is on record: a partition line extended through open space sliced a seg-less sliver
    off a sector, (-309,-44) landed in a decorative island's leaf, floor 16 vs 0 -> wrong
    viewz -> 8,450 wrong pixels. Nothing in tests/ checked point location at all.
  * TREE SHAPE. Every subsector reached EXACTLY once (the existing invariant only checks set
    equality, so a child ref emitted into two branches passes today) and the (firstseg,
    numsegs) spans tiling [0, len(out_segs)) with no gap or overlap.
  * PARTITION PROVENANCE. Every node plane is one of the INPUT linedefs' exact integer lines --
    BSeg.lx/ly/ldx/ldy exist precisely because a split fragment's rounded endpoints quantize
    the direction and rotate the plane off the true wall.
  * SEG OFFSETS. `offset` must accumulate ALONG the linedef, not restart per fragment, or a
    re-split seg gets the wrong wall-texture u-offset. Only re-split fragments discriminate,
    and the existing offset test has none.
  * VERTEX EMISSION. Splits land on floats and are rounded (and deduplicated) at emit only.
    e1m1_lite never exercises `_vert`'s append path, so two constructed maps do.
  * CANDIDATE SAMPLING. Above MAX_CANDIDATES the builder samples candidates by stride; the
    exhaustive rescan behind it is what stops a concave region being emitted as ONE leaf.
  * BBOXES. `wad.nodes_bbox` feeds the renderer's wedge cull; a transposed box silently culls
    geometry that should be drawn.
  * SERIALIZATION. `rebuild_wad` / `write_map_wad` / `lumps` round-trip, including the signed
    fields (e1m1_lite has x = -704, which a '<2H' slip would wrap to 64832).

Nothing here builds or assembles a FlipJump program; the whole file is pure host geometry.
"""
import math
from collections import Counter, defaultdict
from types import SimpleNamespace

import pytest

from doomfj.mapcompiler import _point_side
from doomfj.nodebuilder import (MAX_CANDIDATES, NF_SUBSECTOR, NodeBuilder,
                                initial_segs, rebuild_wad)
from doomfj.wad import Linedef, Sector, Sidedef, Thing, WadFile

E1M1_LITE = "tests/fixtures/e1m1_lite.wad"
MAPNAME = "E1M1"

# linedef flags: 1 = impassable (one-sided), 4 = two-sided
_1S, _2S = 1, 4


def _sd(sector):
    return Sidedef(0, 0, "-", "-", "WALL", sector)


def _ld(v1, v2, front, back=-1, flags=_1S):
    return Linedef(v1, v2, flags, 0, 0, front, back)


# -- the one shared e1m1_lite build (module-scoped: ~0.22 s, and eight tests read it) --

@pytest.fixture(scope="module")
def lite():
    w = WadFile.from_path(E1M1_LITE)
    verts = [(v.x, v.y) for v in w.vertexes(MAPNAME)]
    lds, sds = w.linedefs(MAPNAME), w.sidedefs(MAPNAME)
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    return SimpleNamespace(wad=w, verts=verts, lds=lds, sds=sds, nb=nb, root=root)


# -- tree walking (iterative: e1m1_lite's tree is deeper than a test wants on the stack) --

def _child_refs(nb, root):
    """Yield every child ref reachable from `root`, including `root` itself."""
    stack = [root]
    while stack:
        ref = stack.pop()
        yield ref
        if not ref & NF_SUBSECTOR:
            node = nb.out_nodes[ref]
            stack.append(node[6])
            stack.append(node[7])


def _leaf_segs(nb, ss_idx):
    numsegs, first = nb.out_ss[ss_idx]
    return nb.out_segs[first:first + numsegs]


def _descend(nb, root, x, y):
    """point_in_subsector's walk: `_point_side` > 0 (BACK/LEFT) takes the left child."""
    ref = root
    while not ref & NF_SUBSECTOR:
        node = nb.out_nodes[ref]
        ref = node[7] if _point_side(node[0], node[1], node[2], node[3], x, y) > 0 else node[6]
    return ref & ~NF_SUBSECTOR


def _tree_sector(nb, root, lds, sds, x, y):
    """The sector the engine would report at (x, y) -- firstseg only, exactly as
    reference_model's callers and mapcompiler read it."""
    _, _, _, linedef, side, _ = _leaf_segs(nb, _descend(nb, root, x, y))[0]
    ld = lds[linedef]
    return sds[ld.back if side else ld.front].sector


# -- the independent oracle: nearest +x ray crossing over the RAW lumps (no BSP involved) --

def _ray_sector(verts, lds, sds, x, y):
    """Sector at (x, y) from the nearest linedef crossing the +x ray. -1 = void."""
    best_t, best = None, -1
    for ld in lds:
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        if (y1 > y) == (y2 > y):
            continue                                     # does not cross the horizontal at y
        tx = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        if tx <= x or (best_t is not None and tx >= best_t):
            continue
        sd = ld.back if _point_side(x1, y1, x2 - x1, y2 - y1, x, y) > 0 else ld.front
        best_t, best = tx, (sds[sd].sector if sd != -1 else -1)
    return best


def _near_any_line(verts, lds, x, y, eps=2.0):
    """A point sitting ON a boundary is ambiguous for BOTH locators, so it is not evidence."""
    for ld in lds:
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        if not (min(x1, x2) - eps <= x <= max(x1, x2) + eps
                and min(y1, y2) - eps <= y <= max(y1, y2) + eps):
            continue
        dx, dy = x2 - x1, y2 - y1
        l2 = dx * dx + dy * dy
        if l2 and (dx * (y - y1) - dy * (x - x1)) ** 2 <= eps * eps * l2:
            return True
    return False


def test_point_location_matches_ray_cast_sector_oracle(lite):
    """Walking the built tree resolves every walkable sample to the SAME sector as the ray
    oracle. Negative controls measured this session on this fixture: routing the two split
    halves by the wrong sign in `_partition` gives 10 mismatches, widening `_classify`'s eps
    from 0.4 to 8.0 gives 22, and HEAD gives 0."""
    nb, root, verts, lds, sds = lite.nb, lite.root, lite.verts, lite.lds, lite.sds
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    sampled = 0
    misses = []
    # +13/+7 jitter off a 96-unit stride: the geometry sits on an 8/16-unit lattice, so an
    # unjittered grid would keep landing exactly on boundaries and skip itself away.
    for x in range(min(xs) + 13, max(xs), 96):
        for y in range(min(ys) + 7, max(ys), 96):
            if _near_any_line(verts, lds, x, y):
                continue
            want = _ray_sector(verts, lds, sds, x, y)
            if want == -1:
                continue                                 # void: the player can never stand here
            sampled += 1
            got = _tree_sector(nb, root, lds, sds, x, y)
            if got != want:
                misses.append((x, y, want, got))
    # guard against the test going vacuous if the fixture or the stride ever changes
    assert sampled >= 600, f"only {sampled} walkable samples -- the grid stopped covering the map"
    assert misses == [], (f"{len(misses)} of {sampled} points located in the wrong sector: "
                          f"{misses[:5]}")


def test_no_leaf_fronts_two_sectors(lite):
    """`mixed_leaves` is only a counter in the builder -- nothing asserts it. It matters because
    the sector of a leaf is read off `segs[firstseg]` ALONE, so a mixed leaf makes that read
    arbitrary. Measured this session: 0 on HEAD, non-zero under both the reversed-split-routing
    mutant and a `_classify` eps widened from 0.4 to 8.0."""
    assert lite.nb.mixed_leaves == 0, \
        f"{lite.nb.mixed_leaves} leaves front more than one sector"


def test_every_subsector_is_reached_exactly_once_and_spans_tile(lite):
    """Stronger than the existing `_leaf_side_invariant`, which only checks that the SET of
    reached leaves is complete: a child ref emitted into two branches (a subtree grafted twice)
    satisfies set equality but draws a leaf twice and breaks point location for half of it."""
    nb = lite.nb
    reached = Counter()
    for ref in _child_refs(nb, lite.root):
        if ref & NF_SUBSECTOR:
            reached[ref & ~NF_SUBSECTOR] += 1
        else:
            assert ref < len(nb.out_nodes)
    assert set(reached) == set(range(len(nb.out_ss)))
    dupes = {ss: n for ss, n in reached.items() if n != 1}
    assert dupes == {}, f"subsectors reached more than once: {dupes}"

    # (firstseg, numsegs) must tile [0, len(out_segs)) exactly -- no gap, no overlap, no empty
    cursor = 0
    for numsegs, first in sorted(nb.out_ss, key=lambda s: s[1]):
        assert numsegs > 0, "an empty subsector has no firstseg to read a sector from"
        assert first == cursor, f"seg span starts at {first}, expected {cursor}"
        cursor += numsegs
    assert cursor == len(nb.out_segs)


def test_partition_planes_are_exact_input_linedef_lines(lite):
    """Every node's (x, y, dx, dy) is one of the input linedefs' integer lines, oriented for one
    of its two sides -- never a rounded split-fragment endpoint pair. This is BSeg.lx/ly/ldx/ldy's
    whole reason for existing ("Splits inherit it unchanged"): a short fragment's direction is
    quantized by the emit-time rounding, which rotates the plane off the true wall and
    misclassifies points near it.

    Measured negative control: emitting `(round(x1), round(y1), round(x2-x1), round(y2-y1))` of
    the chosen split FRAGMENT instead of its BSeg.l* line puts 52 of the 470 node planes off the
    true wall -- and the point-location test above still passes on that mutant, so this is the
    only check in the suite that sees it."""
    allowed = set()
    for ld in lite.lds:
        (x1, y1), (x2, y2) = lite.verts[ld.v1], lite.verts[ld.v2]
        allowed.add((x1, y1, x2 - x1, y2 - y1))          # side 0 orientation
        allowed.add((x2, y2, x1 - x2, y1 - y2))          # side 1 orientation
    bad = [n[:4] for n in lite.nb.out_nodes if n[:4] not in allowed]
    assert bad == [], f"{len(bad)} node planes are not input linedef lines: {bad[:4]}"
    # a plane taken from a rounded fragment would most likely show up as a diagonal, so make
    # sure diagonals are actually present and the check is not just covering axis-aligned lines
    assert sum(1 for n in lite.nb.out_nodes if n[2] and n[3]) > 100


def _fragment_groups(nb):
    groups = defaultdict(list)
    for rec in nb.out_segs:
        groups[(rec[3], rec[4])].append(rec)             # (linedef, side)
    return groups


def test_seg_offsets_accumulate_along_the_linedef(lite):
    """`offset` is the distance from the LINEDEF'S OWN start vertex (v1 for side 0, v2 for side
    1) to the fragment's start -- `_split` writes `s.offset + run`, not `run`. First-generation
    splits cannot tell those two apart (s.offset is 0 there), which is why the existing offset
    test misses the mutant; only re-split fragments discriminate. Measured negative control on
    this fixture: the `offset = run` mutant puts one record 512 map units out (offset 640 -> 128)
    -- the wrong wall-texture u-offset on a re-split seg in the shipped program."""
    nb, verts, lds = lite.nb, lite.verts, lite.lds
    worst, worst_rec = 0.0, None
    for rec in nb.out_segs:
        v1, _, _, linedef, side, off = rec
        ld = lds[linedef]
        sx, sy = verts[ld.v1] if side == 0 else verts[ld.v2]
        ex, ey = nb.out_verts[v1]
        dev = abs(math.hypot(ex - sx, ey - sy) - off)
        if dev > worst:
            worst, worst_rec = dev, rec
    # not 0: `offset` is round()ed and the fragment's start VERTEX is rounded too, so the
    # reconstructed distance can differ by up to 0.5 + sqrt(0.5) ~= 1.21 (measured worst on
    # this fixture: 0.849). A restarted offset is off by a whole earlier fragment's length.
    assert worst <= 1.5, f"offset deviates by {worst:.3f} on {worst_rec}"

    # the property is only interesting where fragments were split MORE THAN ONCE
    deep = [k for k, v in _fragment_groups(nb).items() if len(v) >= 3]
    assert deep, "no re-split fragments on this fixture -- the accumulation is untested"


def test_fragments_chain_through_shared_vertex_indices(lite):
    """Sorted by offset, the fragments of one (linedef, side) share vertex INDICES at their
    seams: fragment k's v2 is fragment k+1's v1. A seam that does not share an index is one
    physical corner recorded twice -- a hairline crack in the renderer, and a VERTEXES count
    that drifts toward `build`'s 65536 assert on a full map.

    Measured negative control: the `offset = run` mutant from the previous test breaks 12 seams
    here (restarted offsets reorder the chain), so this is a second, independently-shaped
    witness to that defect. Measured LIMITATION, stated so nobody over-claims it: a `_vert`
    keyed on the raw float instead of the rounded pair is NOT caught, because Python hashes
    250.0 and 250 to the same dict key -- that mutant is a no-op on exact split points."""
    groups = _fragment_groups(lite.nb)
    breaks = []
    for key, frags in groups.items():
        frags = sorted(frags, key=lambda r: r[5])
        for a, b in zip(frags, frags[1:]):
            if a[1] != b[0]:
                breaks.append((key, a, b))
    assert breaks == [], f"{len(breaks)} broken fragment seams: {breaks[:3]}"
    assert len(groups) > 1000, "fixture shrank -- this stopped being a real chain test"


def test_child_bboxes_tightly_bound_their_subtree(lite):
    """`_bbox` returns DOOM order (top = max y, bottom, left = min x, right) and `wad.nodes_bbox`
    hands it straight to the wedge cull. A swapped left/right or top/bottom still satisfies the
    existing `top >= bottom and right >= left` check on the split room, but silently empties the
    box and culls geometry that should be drawn. Asserted TIGHT, not merely containing: the
    subtree's extreme emitted vertices and the stored box round to the same integers, so a box
    that grew is as much a defect as one that shrank."""
    nb = lite.nb

    def subtree_points(child):
        pts = []
        for ref in _child_refs(nb, child):
            if ref & NF_SUBSECTOR:
                for rec in _leaf_segs(nb, ref & ~NF_SUBSECTOR):
                    pts.append(nb.out_verts[rec[0]])
                    pts.append(nb.out_verts[rec[1]])
        return pts

    assert nb.out_nodes, "no nodes -- nothing to check"
    for idx, node in enumerate(nb.out_nodes):
        for box, child, which in ((node[4], node[6], "right/front"),
                                  (node[5], node[7], "left/back")):
            pts = subtree_points(child)
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            assert box == (max(ys), min(ys), min(xs), max(xs)), \
                f"node {idx} {which} bbox {box} != (top,bottom,left,right) of its subtree"


# -- constructed geometry: `_vert`'s append path (e1m1_lite never takes it: 847 -> 847) --

def test_extended_partition_cut_appends_and_dedupes_a_new_vertex():
    """A 384x128 room with an interior two-sided line at x=250, y in [32,96]. That island line is
    the only separating candidate, so its plane EXTENDS to the room's walls and cuts them at
    (250,128) and (250,0) -- points that are not existing vertices, so `_vert` must append them.
    Both fragments of a cut wall must reference the SAME new index (the dedup path: `_vert` is
    called twice at that point, once as fragment A's v2 and once as fragment B's v1).

    Measured negative controls: a `_vert` that always appends (no dedup) fails here, and so does
    one that returns a stale index for a freshly appended vertex."""
    verts = [(0, 0), (0, 128), (384, 128), (384, 0), (250, 32), (250, 96)]
    lds = [_ld(0, 1, 0), _ld(1, 2, 1), _ld(2, 3, 2), _ld(3, 0, 3), _ld(4, 5, 4, 5, _2S)]
    nb = NodeBuilder(verts, lds, [_sd(0)] * 6)
    root = nb.build()

    assert len(nb.out_nodes) == 1 and nb.out_nodes[0][:4] == (250, 32, 0, 64)
    assert nb.out_verts[:6] == verts, "input vertices must be copied through unchanged"
    assert sorted(nb.out_verts[6:]) == [(250, 0), (250, 128)]
    for cut in ((250, 0), (250, 128)):
        assert nb.out_verts.count(cut) == 1, f"{cut} was appended twice instead of deduped"

    # the top wall (linedef 1) is split at (250,128): its two fragments must share that index
    top = sorted((r for r in nb.out_segs if r[3] == 1), key=lambda r: r[5])
    assert len(top) == 2 and top[0][1] == top[1][0] == nb.out_verts.index((250, 128))
    assert [r[5] for r in top] == [0, 250]               # offsets along the linedef
    assert nb.mixed_leaves == 0
    assert {r & ~NF_SUBSECTOR for r in _child_refs(nb, root) if r & NF_SUBSECTOR} == {0, 1}


def test_offgrid_cut_is_rounded_only_at_emit():
    """Same island, but the bottom wall is a diagonal from (384,0) to (0,128), so the x=250 plane
    cuts it at y = 128*(384-250)/384 = 44.666..., not on the lattice. The docstring's contract is
    that endpoints live as FLOATS during recursion and are rounded to the integer grid only at
    emit: the appended vertex must be (250,45). Measured negative control: a `_vert` that
    truncates with int() instead of round() emits (250,44) and fails here -- which is the whole
    half-unit the on-grid fixtures can never expose."""
    verts = [(0, 128), (384, 128), (384, 0), (250, 64), (250, 112)]
    lds = [_ld(0, 1, 0), _ld(1, 2, 1), _ld(2, 0, 2), _ld(3, 4, 3, 4, _2S)]
    nb = NodeBuilder(verts, lds, [_sd(0)] * 5)
    nb.build()
    assert len(nb.out_nodes) == 1
    assert nb.out_verts[:5] == verts
    assert sorted(nb.out_verts[5:]) == [(250, 45), (250, 128)]


# -- constructed geometry: the >MAX_CANDIDATES stride sample and the rescan behind it --

def _zonogon(half=42):
    """A convex integer polygon with 2*(2*half+1) edges, wound CLOCKWISE so that DOOM's
    right=front puts the interior on every wall's FRONT side.

    Zonogon construction: chain angle-sorted vectors, then their negations. The chain closes
    EXACTLY and is convex by construction, so no rounding can dent a corner -- which matters
    because the property under test (a big convex region stays ONE leaf) goes vacuous the
    moment one reflex corner sneaks in and gives the builder something real to split on.
    """
    vecs = [(32, k - half) for k in range(2 * half + 1)]   # distinct slopes, ascending angle
    pts, x, y = [], 0, 0
    for dx, dy in vecs + [(-a, -b) for a, b in vecs]:
        pts.append((x, y))
        x, y = x + dx, y + dy
    assert (x, y) == (0, 0), "zonogon failed to close"
    return list(reversed(pts))                            # CCW chain reversed = clockwise


def _polygon_map(poly, island=None, island_at=3):
    """One-sided walls around `poly`, plus an optional interior two-sided line whose LINEDEF is
    inserted at `island_at` -- which is what places its two segs at seg indices 3 and 4."""
    verts = list(poly)
    entries = [("w", i, (i + 1) % len(poly)) for i in range(len(poly))]
    if island is not None:
        entries.insert(island_at, ("i", len(verts), len(verts) + 1))
        verts += list(island)
    lds, sds = [], []
    for kind, a, b in entries:
        if kind == "w":
            lds.append(_ld(a, b, len(sds)))
            sds.append(_sd(0))
        else:
            lds.append(_ld(a, b, len(sds), len(sds) + 1, _2S))
            sds += [_sd(0), _sd(0)]
    return verts, lds, sds


def test_convex_region_above_max_candidates_is_one_leaf():
    """170 convex edges: no candidate separates anything, so the stride sample AND the exhaustive
    rescan behind it must both come up empty and the region be emitted as a single subsector.
    This is the `len(segs) > MAX_CANDIDATES` arm -- the hand-made rooms in the existing suite are
    all far below MAX_CANDIDATES and never reach it."""
    verts, lds, sds = _polygon_map(_zonogon())
    assert len(initial_segs(verts, lds, sds)) > MAX_CANDIDATES
    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    assert nb.out_nodes == []
    assert nb.out_ss == [(len(verts), 0)]
    assert root == (0 | NF_SUBSECTOR)
    assert nb.mixed_leaves == 0


def test_candidate_missed_by_the_stride_sample_is_found_by_the_exhaustive_rescan():
    """The same zonogon with ONE interior two-sided line -- the only separating candidate there
    is. Its linedef sits at index 3, so its two segs are seg indices 3 and 4, which the stride
    sample for 172 segs skips (0, 2, 5, 8, 10, 13, ...). Without the "sampled miss -- exhaustive
    before declaring a leaf" rescan the builder emits the whole CONCAVE region as one subsector,
    which makes point location and leaf-sector ownership wrong for everything in it. Measured
    this session with the rescan removed: 0 nodes / 1 leaf; on HEAD: 1 node / 2 leaves."""
    verts, lds, sds = _polygon_map(_zonogon(), island=((1360, -200), (1360, 200)))
    segs_in = initial_segs(verts, lds, sds)
    assert [(s.linedef, s.side) for s in segs_in[3:5]] == [(3, 0), (3, 1)]

    # assert the PRECONDITION, so a changed MAX_CANDIDATES or stride formula fails loudly here
    # instead of quietly turning this into a re-run of the previous test
    step = len(segs_in) / MAX_CANDIDATES
    sampled = {int(i * step) for i in range(MAX_CANDIDATES)}
    assert len(segs_in) > MAX_CANDIDATES
    assert not ({3, 4} & sampled), "the island segs are now sampled -- the rescan is not exercised"

    nb = NodeBuilder(verts, lds, sds)
    root = nb.build()
    assert len(nb.out_nodes) == 1, "the separating candidate was never found"
    assert nb.out_nodes[0][:4] == (1360, -200, 0, 400)
    assert len(nb.out_ss) == 2
    assert {r & ~NF_SUBSECTOR for r in _child_refs(nb, root) if r & NF_SUBSECTOR} == {0, 1}


# -- serialization --

def test_rebuild_wad_roundtrips_the_built_lumps_and_passes_geometry_through(tmp_path, lite):
    """`rebuild_wad` -> `lumps` -> `write_map_wad` -> `WadFile` must return exactly what the
    builder held, and leave THINGS/LINEDEFS/SIDEDEFS/SECTORS field-for-field identical. This is
    the only cover `write_map_wad` has: it catches wrong directory offsets, a wrong lump ORDER,
    and struct-format slips -- e1m1_lite has a vertex at x = -704, which a '<2H' would read back
    as 64832, and the node format mixes signed partition/bbox fields with UNSIGNED child refs
    (NF_SUBSECTOR sets the high bit, so a signed slip turns every leaf ref negative)."""
    out = tmp_path / "renode.wad"
    nb = rebuild_wad(E1M1_LITE, MAPNAME, out)

    w = WadFile.from_path(out)
    assert w.wad_type == "PWAD"
    assert w.names() == [MAPNAME, "THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES",
                         "SEGS", "SSECTORS", "NODES", "SECTORS"]

    src = lite.wad
    for acc in ("things", "linedefs", "sidedefs", "sectors"):
        assert getattr(w, acc)(MAPNAME) == getattr(src, acc)(MAPNAME), \
            f"{acc} did not pass through unchanged"

    assert [(v.x, v.y) for v in w.vertexes(MAPNAME)] == nb.out_verts
    assert min(v.x for v in w.vertexes(MAPNAME)) < 0, "signedness is untested without a negative x"
    assert [(s.v1, s.v2, s.angle, s.linedef, s.direction, s.offset)
            for s in w.segs(MAPNAME)] == nb.out_segs
    assert [(s.numsegs, s.firstseg) for s in w.subsectors(MAPNAME)] == nb.out_ss
    assert [(n.x, n.y, n.dx, n.dy, n.right, n.left) for n in w.nodes(MAPNAME)] == \
           [(x, y, dx, dy, r, l) for x, y, dx, dy, _, _, r, l in nb.out_nodes]
    assert w.nodes_bbox(MAPNAME) == [(bbr, bbl) for *_, bbr, bbl, _, _ in nb.out_nodes]
    assert any(n.right & NF_SUBSECTOR for n in w.nodes(MAPNAME)), "no leaf ref survived the pack"


def test_rebuild_wad_overrides_reach_the_output(tmp_path):
    """Each of the things= / linedefs= / sidedefs= / vertexes= / sectors= overrides must actually
    reach the written lumps -- that is the entire point of the keyword (mapsimplify hands
    `rebuild_wad` simplified geometry, and an override silently ignored would discard it with no
    symptom at all). Also guards the '<2h8s8s3h' SECTORS and '<2h8s8s8sh' SIDEDEFS packs: a field
    dropped from either shifts every LATER record, so the check is field-for-field over all 118
    sectors / 1228 sidedefs, not just the first."""
    src = WadFile.from_path(E1M1_LITE)
    # a rigid translation keeps the map valid (so the build still succeeds) while making every
    # vertex distinguishable from the source's
    verts = [(v.x + 16, v.y - 8) for v in src.vertexes(MAPNAME)]
    lds = list(src.linedefs(MAPNAME))
    lds[0] = Linedef(lds[0].v1, lds[0].v2, lds[0].flags ^ _2S, 77, 5, lds[0].front, lds[0].back)
    sds = list(src.sidedefs(MAPNAME))
    sds[0] = Sidedef(-9, 23, "UP", "LO", "MID", sds[0].sector)
    secs = [Sector(s.floor_h + 13, s.ceil_h - 5, s.floor_tex, s.ceil_tex,
                   s.light, s.special, s.tag) for s in src.sectors(MAPNAME)]
    things = [Thing(-704, 96, 90, 1, 7), Thing(64, -32, 180, 2035, 7)]

    out = tmp_path / "override.wad"
    nb = rebuild_wad(E1M1_LITE, MAPNAME, out,
                     things=things, linedefs=lds, sidedefs=sds, vertexes=verts, sectors=secs)
    w = WadFile.from_path(out)

    assert w.things(MAPNAME) == things
    assert w.linedefs(MAPNAME) == lds
    assert w.sidedefs(MAPNAME) == sds
    assert w.sectors(MAPNAME) == secs
    assert [(v.x, v.y) for v in w.vertexes(MAPNAME)][:len(verts)] == verts
    # and the BSP really was built on the overridden vertices, not the source's
    assert nb.out_verts[:len(verts)] == verts


# -- reproducibility and the one tuning knob --

def test_build_is_deterministic(lite):
    """Two runs over identical input must produce byte-identical lumps. Candidate selection or
    leaf grouping that ever iterated a set or an identity-keyed dict would make
    tests/fixtures/e1m1_lite.wad -- and therefore every downstream emitted program and golden
    hash -- differ between runs.

    Run 2 is only evidence if run 1 left the caller's geometry alone, so the input lists are
    checked as well: `rebuild_wad` and `mapsimplify` keep holding the lists they hand the
    builder, and a `NodeBuilder` that wrote THROUGH to them (`self.out_verts = verts` rather
    than a copy) would seed run N+1 with run N's split vertices. R9 negative control, measured
    this session: that exact aliasing defect leaves the e1m1_lite half of this test green --
    e1m1_lite appends no vertices at all (847 -> 847), so nothing writes through, and the two
    builds then share ONE list object and compare equal to themselves. The island map below
    appends two vertices and is what makes the defect visible."""
    again = NodeBuilder(lite.verts, lite.lds, lite.sds)
    again.build()
    assert (again.out_verts, again.out_segs, again.out_ss, again.out_nodes) == \
           (lite.nb.out_verts, lite.nb.out_segs, lite.nb.out_ss, lite.nb.out_nodes)

    # the `_vert` append path (the room + interior island of the extended-cut test above)
    verts = [(0, 0), (0, 128), (384, 128), (384, 0), (250, 32), (250, 96)]
    lds = [_ld(0, 1, 0), _ld(1, 2, 1), _ld(2, 3, 2), _ld(3, 0, 3), _ld(4, 5, 4, 5, _2S)]
    sds = [_sd(0)] * 6
    before = ([*verts], [*lds], [*sds])

    first = NodeBuilder(verts, lds, sds)
    first.build()
    # without this the input-unchanged check below is vacuous: nothing was ever appended
    assert len(first.out_verts) > len(before[0]), "the split-vertex append path did not run"
    assert (verts, lds, sds) == before, "the build wrote through to its caller's input lists"

    second = NodeBuilder(verts, lds, sds)
    second.build()
    assert (second.out_verts, second.out_segs, second.out_ss, second.out_nodes) == \
           (first.out_verts, first.out_segs, first.out_ss, first.out_nodes)


def test_split_cost_keyword_reaches_the_score(lite):
    """`split_cost` is the builder's only quality knob and `_score` must read SELF's copy, not the
    module-level SPLIT_COST. With splits free the builder stops avoiding them, so the seg count
    rises -- if a refactor read the constant instead, the knob would be silently dead and the
    docstring's tuning record (8/16/32 -> 2126/2106/2057 segs) would stop being reproducible."""
    free = NodeBuilder(lite.verts, lite.lds, lite.sds, split_cost=0)
    free.build()
    assert len(free.out_segs) > len(lite.nb.out_segs)
    assert sum(n for n, _ in free.out_ss) == len(free.out_segs)
