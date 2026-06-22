"""M12a (F5) — the BSP front-to-back traversal (R_RenderBSPNode), host oracle. From the viewpoint the
renderer descends the BSP visiting the NEAR child first (the side the viewer is on), so subsectors come
out ordered nearest-first — the order DOOM draws walls in (front-to-back, for solid-seg clipping). This
is the visibility backbone the M12 fj wall renderer reproduces; the oracle defines its golden order.

Tested on the concave L-shape (≥2 subsectors + a partition node, deterministic — the same fixture the
mapcompiler split tests use). The traversal is iterative (the M7-built BSP is deep/unbalanced); building
the full E1M1 BSP currently overflows the M7 *recursive builder* (mapcompiler.compile_bsp) — fixing that
(iterative build) is the next M12 step before the renderer runs on E1M1.
"""
from doomfj.mapcompiler import NF_SUBSECTOR, Seg, _point_side, build_bsp
from doomfj.reference_model import ReferenceModel


def _l_shape():
    """Concave hexagon (an L), concave at v3=(1,1) — cannot be one subsector, so the BSP splits."""
    verts = [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)]
    loop = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 0)]
    segs = [Seg(a, b, 0, i, 0, 0) for i, (a, b) in enumerate(loop)]
    return build_bsp(verts, segs)


def _subtree_subsectors(cmap, child):
    """All subsector indices reachable under a BSP child ref (iterative)."""
    out, stack = set(), [child]
    while stack:
        c = stack.pop()
        if c & NF_SUBSECTOR:
            out.add(c & (NF_SUBSECTOR - 1))
        else:
            n = cmap.nodes[c]
            stack.append(n.left)
            stack.append(n.right)
    return out


def test_render_order_is_permutation():
    cmap = _l_shape()
    assert len(cmap.subsectors) >= 2 and len(cmap.nodes) >= 1
    order = ReferenceModel().bsp_render_order(cmap, 1, 0)
    assert sorted(order) == list(range(len(cmap.subsectors)))


def test_viewer_subsector_drawn_first():
    """The near-first walk lands in the viewer's own subsector before any other (front-to-back)."""
    cmap = _l_shape()
    rm = ReferenceModel()
    for vx, vy in [(1, 0), (0, 0), (2, 0), (0, 2)]:
        order = rm.bsp_render_order(cmap, vx, vy)
        assert order[0] == rm.point_in_subsector(cmap, vx, vy)


def test_near_subtree_before_far():
    """The root's near subtree is fully drawn before the far subtree (front-to-back ordering)."""
    cmap = _l_shape()
    rm = ReferenceModel()
    vx, vy = 1, 0
    root = cmap.root
    assert not (root & NF_SUBSECTOR)
    n = cmap.nodes[root]
    back = _point_side(n.x, n.y, n.dx, n.dy, vx, vy) > 0
    near, far = (n.left, n.right) if back else (n.right, n.left)
    near_ss, far_ss = _subtree_subsectors(cmap, near), _subtree_subsectors(cmap, far)
    order = rm.bsp_render_order(cmap, vx, vy)
    near_pos = [i for i, s in enumerate(order) if s in near_ss]
    far_pos = [i for i, s in enumerate(order) if s in far_ss]
    assert max(near_pos) < min(far_pos)


def test_visible_segs_follow_subsector_order():
    cmap = _l_shape()
    rm = ReferenceModel()
    vx, vy = 1, 0
    order = rm.bsp_render_order(cmap, vx, vy)
    expected = []
    for ss in order:
        s = cmap.subsectors[ss]
        expected += list(range(s.firstseg, s.firstseg + s.numsegs))
    assert rm.visible_segs(cmap, vx, vy) == expected
    assert len(expected) == sum(s.numsegs for s in cmap.subsectors)
