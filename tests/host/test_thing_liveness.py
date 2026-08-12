"""M14-a — the prune, settled: a leaf a thing could EVER enter must survive both prunes.

Background (docs/handoff-m14.md section 3). A leaf with no walk-relevant seg is dropped twice --
`_lines_prune` at compile time and the `tsstop` node gate at runtime -- and both used to be taught
liveness from `things_by_ss`, i.e. from where the things happen to STAND when the program is
emitted. That is correct only while nothing moves. Under a simulation a monster walks into a leaf
pruned as empty and vanishes with no error, no warning and no assertion.

The replacement is `mapcompiler.thing_live_subsectors` -- a predicate that reads no thing position
at all, so no simulation can invalidate it -- plus `assert_thing_live_survives_prune`, which walks
the tree exactly as the emitter does and refuses to emit when a thing-live leaf is unreachable.

⚠ R9: `test_guard_rejects_the_old_emit_time_predicate` is this file's NEGATIVE CONTROL. A guard
that never fires proves nothing, so that test re-runs the guard with the OLD occupancy predicate
and requires it to REJECT -- if it ever passes, the guard has stopped detecting the bug it exists
for and every other test here is worthless.
"""
from pathlib import Path

import pytest

from doomfj.config import Config
from doomfj.mapcompiler import (
    NF_SUBSECTOR, bake_bsp, bbox_gate_boxes, seg_sector, thing_live_subsectors,
    assert_thing_live_survives_prune,
)
from doomfj.reference_model import ReferenceModel, THING_SPRITE
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
MAPNAME = "E1M1"


@pytest.fixture(scope="module")
def level():
    wad = WadFile.from_path(E1M1)
    cmap = bake_bsp(wad, MAPNAME)
    return (wad, cmap, wad.linedefs(MAPNAME), wad.sidedefs(MAPNAME), wad.sectors(MAPNAME),
            ReferenceModel(Config()))


def _spawn_occupancy(wad, cmap, rm):
    """The OLD, unsound predicate: the subsectors things stand in at emit time."""
    return frozenset(rm.point_in_subsector(cmap, t.x, t.y)
                     for t in wad.things(MAPNAME) if THING_SPRITE.get(t.type) is not None)


def _prune_closures(cmap, lds, sds, secs, live):
    """The emitter's two prune callables, rebuilt over an arbitrary liveness set.

    `_seg_in_walk` / `_seg_as_solid` here are the shipped lines tier's rules (plane_near=True):
    a seg is walked if it is one-sided or MARKS its sector's planes, and only one-sided segs stop a
    subtree being tsstop-gatable."""
    def marks(seg):
        ld = lds[seg.linedef]
        if ld.back == -1:
            return True
        fs = secs[sds[ld.front if seg.side == 0 else ld.back].sector]
        bs = secs[sds[ld.back if seg.side == 0 else ld.front].sector]
        return ((fs.ceil_h, fs.light & 0xFF, fs.ceil_tex.upper())
                != (bs.ceil_h, bs.light & 0xFF, bs.ceil_tex.upper())
                or (fs.floor_h, fs.light & 0xFF, fs.floor_tex.upper())
                != (bs.floor_h, bs.light & 0xFF, bs.floor_tex.upper()))

    def solid(seg):
        return lds[seg.linedef].back == -1

    def in_walk(seg):
        return solid(seg) or marks(seg)

    below: dict = {}

    def cnt(child, pred, memo):
        if child & NF_SUBSECTOR:
            si0 = child & (NF_SUBSECTOR - 1)
            if si0 in live:
                return 1
            ss = cmap.subsectors[si0]
            return sum(1 for si in range(ss.firstseg, ss.firstseg + ss.numsegs)
                       if pred(cmap.segs[si]))
        n = cmap.nodes[child]
        tot = cnt(n.left, pred, memo) + cnt(n.right, pred, memo)
        memo[child] = tot
        return tot

    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(20000)
    try:
        walk_below: dict = {}
        solid_below: dict = {}
        cnt(cmap.root, in_walk, walk_below)
        cnt(cmap.root, solid, solid_below)
    finally:
        sys.setrecursionlimit(old)
    below.update(walk_below)

    def prune(child):
        if child & NF_SUBSECTOR:
            si0 = child & (NF_SUBSECTOR - 1)
            if si0 in live:
                return False
            ss = cmap.subsectors[si0]
            return not any(in_walk(cmap.segs[si])
                           for si in range(ss.firstseg, ss.firstseg + ss.numsegs))
        return walk_below.get(child, 1) == 0

    def plane_gate(node_i):
        return 0 if solid_below.get(node_i, 1) != 0 else 1

    return prune, plane_gate


def test_thing_live_reads_no_thing_position(level):
    """The predicate's soundness IS its independence from where things are: it takes the map's
    geometry and nothing else, so moving every thing cannot change its answer."""
    wad, cmap, lds, sds, secs, rm = level
    live = thing_live_subsectors(cmap, lds, sds, secs)
    assert live == thing_live_subsectors(cmap, lds, sds, secs)
    # it is strictly wider than the spawn occupancy it replaces, and covers nearly the whole map
    occupancy = _spawn_occupancy(wad, cmap, rm)
    assert occupancy < live, "the widened predicate must contain the old one, strictly"
    assert len(live) >= 0.95 * sum(1 for ss in cmap.subsectors if ss.numsegs)


def test_the_only_excluded_leaves_have_no_room_to_stand_in(level):
    """The exclusions must be justifiable one at a time, not statistically."""
    _wad, cmap, lds, sds, secs, _rm = level
    live = thing_live_subsectors(cmap, lds, sds, secs)
    for si, ss in enumerate(cmap.subsectors):
        if not ss.numsegs or si in live:
            continue
        sec = seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
        assert sec.ceil_h <= sec.floor_h, (
            f"ss{si} is excluded from thing_live_subsectors but its sector has "
            f"{sec.ceil_h - sec.floor_h} units of headroom -- a thing could stand there")


def test_prune_and_node_gate_keep_every_thing_live_leaf(level):
    """The shipped predicate: no thing-live leaf is dropped by either prune."""
    _wad, cmap, lds, sds, secs, _rm = level
    live = thing_live_subsectors(cmap, lds, sds, secs)
    prune, plane_gate = _prune_closures(cmap, lds, sds, secs, live)
    assert_thing_live_survives_prune(cmap, thing_live=live, prune=prune, plane_gate=plane_gate,
                                     where=f"{MAPNAME}: ")


def test_guard_rejects_the_old_emit_time_predicate(level):
    """⚠ THE NEGATIVE CONTROL (R9). Rebuild the prunes the way they were built before M14-a --
    liveness = the subsectors things stand in at spawn -- and require the guard to REJECT that
    tree for the thing-live leaves. This is the bug the guard exists to catch; if this test ever
    passes, the guard has gone blind and every other assertion in this file is worthless."""
    wad, cmap, lds, sds, secs, rm = level
    live = thing_live_subsectors(cmap, lds, sds, secs)
    occupancy = _spawn_occupancy(wad, cmap, rm)
    prune, plane_gate = _prune_closures(cmap, lds, sds, secs, occupancy)
    with pytest.raises(AssertionError, match="vanish with no other symptom"):
        assert_thing_live_survives_prune(cmap, thing_live=live, prune=prune,
                                         plane_gate=plane_gate, where=f"{MAPNAME}: ")


def test_bbox_wedge_boxes_are_inflated_for_every_thing_live_subtree(level):
    """The third compile-time structure that keyed off spawn positions: the wedge cull's inflated
    boxes. Widening can only RELAX the cull, so every box must be at least as large as before."""
    wad, cmap, lds, sds, secs, rm = level
    old = bbox_gate_boxes(cmap, thing_subsectors=_spawn_occupancy(wad, cmap, rm))
    new = bbox_gate_boxes(cmap, thing_subsectors=thing_live_subsectors(cmap, lds, sds, secs))
    assert set(old) == set(new), "widening must not change WHICH nodes are gated, only their boxes"
    for i, (t, b, left, right) in old.items():
        nt, nb, nl, nr = new[i]
        assert nt >= t and nb <= b and nl <= left and nr >= right, (
            f"node {i}: the widened box {new[i]} is not a superset of {old[i]} -- "
            "a relaxed cull can only grow boxes")
    assert any(new[i] != old[i] for i in old), (
        "no box changed at all: the widened set is not reaching bbox_gate_boxes")
