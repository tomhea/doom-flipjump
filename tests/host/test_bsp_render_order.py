"""M12a (F5) — the BSP front-to-back traversal (R_RenderBSPNode), host oracle. From the viewpoint the
renderer descends the BSP visiting the NEAR child first (the side the viewer is on), so subsectors come
out ordered nearest-first — the order DOOM draws walls in (front-to-back, for solid-seg clipping). This
is the visibility backbone the M12 fj wall renderer reproduces; the oracle defines its golden order.

The traversal logic is exercised two ways: a tiny hand-built `CompiledMap` (a single partition node over
two subsectors — precise near/far ordering assertions), and the full real **baked** E1M1 node tree (the
permutation + viewer-first invariants on a deep tree). bake_bsp parses the WAD's precompiled node tree
(M12i); the M7 recursive builder that used to crash on E1M1 is gone.
"""
from pathlib import Path

from doomfj.mapcompiler import (
    NF_SUBSECTOR, CompiledMap, Node, Seg, SubSector, bake_bsp, _point_side,
)
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")


def _two_leaf_map():
    """A minimal BSP: one partition line (x=0, dir +y) splitting two subsectors. side>0 (x<0) ⇒ left,
    else right. Each leaf owns two segs (so visible_segs ordering is observable)."""
    seg = Seg(0, 1, 0, 0, 0, 0)
    node = Node(x=0, y=0, dx=0, dy=1, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)
    return CompiledMap(
        vertexes=[(0, 0), (1, 0)],
        segs=[seg, seg, seg, seg],
        subsectors=[SubSector(2, 0), SubSector(2, 2)],
        nodes=[node],
        root=0,
    )


# ── hand-built node: precise near/far ordering ───────────────────────────────

def test_render_order_is_permutation_handbuilt():
    cmap = _two_leaf_map()
    order = ReferenceModel().bsp_render_order(cmap, 5, 0)
    assert sorted(order) == list(range(len(cmap.subsectors)))


def test_viewer_side_drawn_first():
    """Right of the partition (x>0) ⇒ subsector 0 first; left (x<0) ⇒ subsector 1 first."""
    rm = ReferenceModel()
    cmap = _two_leaf_map()
    assert rm.bsp_render_order(cmap, 5, 0) == [0, 1]      # viewer on the right/front
    assert rm.bsp_render_order(cmap, -5, 0) == [1, 0]     # viewer on the left/back
    assert rm.bsp_render_order(cmap, 5, 0)[0] == rm.point_in_subsector(cmap, 5, 0)


def test_visible_segs_follow_subsector_order():
    rm = ReferenceModel()
    cmap = _two_leaf_map()
    order = rm.bsp_render_order(cmap, 5, 0)
    expected = []
    for ss in order:
        s = cmap.subsectors[ss]
        expected += list(range(s.firstseg, s.firstseg + s.numsegs))
    assert rm.visible_segs(cmap, 5, 0) == expected
    assert len(expected) == sum(s.numsegs for s in cmap.subsectors)


# ── full real baked E1M1 node tree ──────────────────────────────────────────

def test_e1m1_render_order_is_permutation():
    cmap = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    order = ReferenceModel().bsp_render_order(cmap, -416, 256)   # E1M1 player-1 start
    assert len(cmap.subsectors) == 682
    assert sorted(order) == list(range(len(cmap.subsectors)))


def test_e1m1_viewer_subsector_drawn_first():
    """The near-first walk lands in the viewer's own subsector before any other, at several points."""
    cmap = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    rm = ReferenceModel()
    for vx, vy in [(-416, 256), (-320, 256), (0, 256), (256, -256)]:
        order = rm.bsp_render_order(cmap, vx, vy)
        assert order[0] == rm.point_in_subsector(cmap, vx, vy)


def test_e1m1_near_subtree_before_far():
    """At the root the near subtree is fully drawn before the far subtree (front-to-back)."""
    cmap = bake_bsp(WadFile.from_path(E1M1), "E1M1")
    rm = ReferenceModel()
    vx, vy = -416, 256
    n = cmap.nodes[cmap.root]
    back = _point_side(n.x, n.y, n.dx, n.dy, vx, vy) > 0
    near, far = (n.left, n.right) if back else (n.right, n.left)

    def subtree(child):
        out, stack = set(), [child]
        while stack:
            c = stack.pop()
            if c & NF_SUBSECTOR:
                out.add(c & (NF_SUBSECTOR - 1))
            else:
                nn = cmap.nodes[c]
                stack += [nn.left, nn.right]
        return out

    near_ss, far_ss = subtree(near), subtree(far)
    order = rm.bsp_render_order(cmap, vx, vy)
    near_pos = [i for i, s in enumerate(order) if s in near_ss]
    far_pos = [i for i, s in enumerate(order) if s in far_ss]
    assert max(near_pos) < min(far_pos)
