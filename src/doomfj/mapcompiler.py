"""H3 — map compiler (M7 build → M12i BAKE). The level's BSP is **baked**: real DOOM levels ship the
node tree precomputed in the NODES/SSECTORS/SEGS lumps (the engine never built them at runtime either),
so we parse those lumps into the `CompiledMap` the oracle (H5) and the fj renderer walk — we no longer
build the BSP ourselves. (Owner decision 2026-06-22, reversing the M7 "build not bake" amendment; the
M7 recursive builder crashed on real E1M1 geometry anyway. Scope: Freedoom Phase 1, E1M1–E1M9.)

Pipeline:  WadFile.{segs,subsectors,nodes}  ->  bake_bsp  ->  CompiledMap  ->  compile_map (.fj streams)

- `bake_bsp` reads the three baked lumps into `CompiledMap` (segs/subsectors/nodes/vertexes + the root
  child ref). The WAD's segs follow DOOM's standard winding (sector on the seg's right/front), so the
  oracle uses DOOM's native conventions (rw_normalangle = seg.angle + ANG90; v1 is the seg's right
  screen vertex) — no winding patches. DOOM's root is the LAST node (or subsector 0 if there are none).
- `compile_map` emits the baked level as sequential packed-byte streams (VERTEXES/LINEDEFS/SIDEDEFS/
  SECTORS from the WAD + SEGS/SSECTORS/NODES from the bake) plus the root-node entry; `mode="code"`
  emits the BSP as code (opt #7). LINEDEFS+VERTEXES double as F6's line-collision data (no tile grid, D1).

flipjump parses `.fj` as UTF-8; emitted text is ASCII.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence, Tuple

NF_SUBSECTOR = 0x8000  # high bit of a BSP child ref ⇒ it points to a subsector, not a node
MASK40 = (1 << 40) - 1  # proj.point_on_side's 10-nibble working width (int16 coords ⇒ cross product < 2^39)


@dataclass(frozen=True)
class Seg:
    v1: int          # start vertex index
    v2: int          # end vertex index
    angle: int       # BAM >> 16 (0..0xFFFF), direction v1->v2
    linedef: int     # source linedef index
    side: int        # 0 = front/right, 1 = back/left (the SEGS "direction" field)
    offset: int      # distance along the linedef from its start to this seg's start


@dataclass(frozen=True)
class SubSector:
    numsegs: int
    firstseg: int    # index into the seg order


@dataclass(frozen=True)
class Node:
    x: int           # partition line start
    y: int
    dx: int          # partition line direction
    dy: int
    right: int       # child ref (| NF_SUBSECTOR if a subsector)
    left: int
    bbr: tuple = None    # right child's bbox (top, bottom, left, right) — M13-15M bbox wedge cull
    bbl: tuple = None


@dataclass(frozen=True)
class CompiledMap:
    vertexes: List[Tuple[int, int]]  # the level's vertices (16.0 map coords)
    segs: List[Seg]
    subsectors: List[SubSector]
    nodes: List[Node]
    root: int        # child ref of the root (| NF_SUBSECTOR when the whole map is one subsector)


# ── geometry ──

def _point_side(px: int, py: int, dx: int, dy: int, x: int, y: int) -> int:
    """Which side of the partition line (px,py)+t(dx,dy) the point (x,y) is on.
    Returns >0 (back/left), <0 (front/right), 0 (on the line) — DOOM's right=front convention."""
    return dx * (y - py) - dy * (x - px)


def seg_affine_coeffs(seg: "Seg", verts: Sequence[Tuple[int, int]]) -> Tuple[int, int, int]:
    """The SSOT affine coefficients (a, b, c) for a seg's signed perpendicular view→wall-line distance
    (perf #9, [re-bless]). The signed distance, in 16.16 map units, is

        signed_dist = fixed_mul(a, viewx) + fixed_mul(b, viewy) + c        (32-bit wrap)

    where a = segdy/seglen, b = -segdx/seglen are the unit-normal components and c = -(a·v1x + b·v1y)
    references the line through v1. This is the cross product ((view−v1)×segdir)/seglen — exact integer
    affine in the viewpoint, with the same value the divide path (point_to_dist·sin) approximates, but
    without the atan/divide. For a FRONT-facing seg (those that survive wall_x_range's span<ANG180 cull)
    signed_dist > 0, so rw_distance = signed_dist directly (abs is a no-op); the SIGN is what perf #10's
    back-face cull tests. Returned a/b/c are raw 32-bit two's-complement words ready to bake — both the
    oracle and the fj emitter consume THIS function so they cannot drift (R6). `c` is the perpendicular
    distance from the origin to the wall line; encode_fixed_point raises if it exceeds the signed 16.16
    range (|c| < 32768 map units), which would need a wider representation."""
    from doomfj.fixedpoint import encode_fixed_point   # local import: avoid a module cycle
    v1x, v1y = verts[seg.v1]
    v2x, v2y = verts[seg.v2]
    segdx, segdy = v2x - v1x, v2y - v1y
    seglen = (segdx * segdx + segdy * segdy) ** 0.5
    if seglen == 0:
        return 0, 0, 0                                   # degenerate zero-length seg
    af, bf = segdy / seglen, -segdx / seglen
    a = encode_fixed_point(af, 16, 32)
    b = encode_fixed_point(bf, 16, 32)
    c = encode_fixed_point(-(af * v1x + bf * v1y), 16, 32)
    return a, b, c


# ── M13-15M: the BBOX WEDGE CULL's SSOT (shared by the oracle mirror AND the fj emitter) ──

ANG45_BAM = 0x20000000


def wedge_planes_bam(viewangle: int) -> tuple:
    """The two half-plane direction indices (0..7) proj.wedge_setup picks for this view angle —
    MIRRORED EXACTLY, mod-2^32 BAM arithmetic included: lo = ((va - ANG45) mod 2^32) >> 29,
    hi = ((va + ANG45 + ANG45-1) mod 2^32) >> 29 (the ceil identity), plane B = (hi + 4) & 7."""
    lo = ((viewangle - ANG45_BAM) & 0xFFFFFFFF) >> 29
    hi = ((viewangle + ANG45_BAM + (ANG45_BAM - 1)) & 0xFFFFFFFF) >> 29
    return lo, (hi + 4) & 7


def bbox_wedge_miss(m: int, box: tuple, vx: int, vy: int) -> bool:
    """True when the whole box (top, bottom, left, right — the NODES lump order) lies OUTSIDE
    half-plane m, i.e. max over the box of the plane's signed test value is negative. The maximizing
    corner is a pure function of m: x = left for m<4 else right; y = top for m in {0,1,6,7} else
    bottom (equivalently, in fj's (q=m&3, n=2<=m<=5) encoding: y = top iff n==0, x = left iff
    (q<2) == (n==0)). All in raw 16.0 map units. ⚠ WIDTH CONTRACT (CR-2026-08): the fj side
    (proj.wedge_bbox_plane) evaluates Q on 4-nibble slices, so every true Q — including the
    dx+dy / dy-dx combinations — must fit SIGNED 16 BITS. That is NOT free for "int16 maps":
    Q reaches ±(span_x + span_y), ~2^17 on a map spanning the full int16 range. The bound is
    ENFORCED per map by the assert in `bbox_gate_boxes` (span_x + span_y + slack < 2^15);
    a map that trips it needs the fj slices widened, not the assert loosened."""
    top, bottom, left, right = box
    cx = left if m < 4 else right
    cy = top if m in (0, 1, 6, 7) else bottom
    dx, dy = cx - vx, cy - vy
    q = (dy, dy - dx, dx, dx + dy)[m & 3]
    if 2 <= m <= 5:
        q = -q
    return q < 0


def bbox_gate_boxes(cmap: "CompiledMap", *, min_segs: int = 32,
                    thing_subsectors=(), inflate: int = 96) -> dict:
    # min_segs tuning (E1M1-lite, measured): 8 gated 325 of 470 nodes and the per-visit test cost
    # showed up as +0.83M at a high-reach viewpoint ((-309,636) keeps 86% of segs); 32 keeps the
    # big-subtree culls (tree -1.54M, courtyard -0.78M) at roughly a third of the overhead.
    """Which nodes get a runtime bbox wedge gate, and with what box: {node_index: (T, B, L, R)}.
    The box is the UNION of the node's two child boxes. Only subtrees holding >= min_segs segs are
    worth the ~2.5k-op runtime test; a subtree holding any THING-carrying leaf gets its box
    inflated by `inflate` map units so a sprite whose center sits just outside the wedge cannot
    lose its (up to ~sprite-half-width) on-screen columns. The ORACLE and the fj emitter must both
    use THIS function — the gate changes which marking segs spend budget, so the two sides have to
    agree on the gated set exactly."""
    if not cmap.nodes or cmap.nodes[0].bbr is None:
        return {}
    segs_below: dict = {}
    things_below: dict = {}
    thing_ss = set(thing_subsectors)

    def walk(child):
        if child & NF_SUBSECTOR:
            s = child & (NF_SUBSECTOR - 1)
            return cmap.subsectors[s].numsegs, (s in thing_ss)
        n = cmap.nodes[child]
        sr, tr = walk(n.right)
        sl, tl = walk(n.left)
        segs_below[child] = sr + sl
        things_below[child] = tr or tl
        return sr + sl, tr or tl

    import sys as _sys
    _old = _sys.getrecursionlimit()
    _sys.setrecursionlimit(20000)
    try:
        walk(cmap.root)
    finally:
        _sys.setrecursionlimit(_old)

    out = {}
    for i, n in enumerate(cmap.nodes):
        if segs_below.get(i, 0) < min_segs:
            continue
        (rt, rb, rl, rr), (lt, lb, ll, lr) = n.bbr, n.bbl
        box = (max(rt, lt), min(rb, lb), min(rl, ll), max(rr, lr))
        if things_below.get(i):
            box = (box[0] + inflate, box[1] - inflate, box[2] - inflate, box[3] + inflate)
        out[i] = box
    # CR-2026-08: bbox_wedge_miss's WIDTH CONTRACT (see its docstring) -- the fj evaluates Q
    # on signed-16-bit slices, and Q reaches +/-(span_x + span_y) for the dx+dy / dy-dx
    # planes. Bound the spans over everything a Q can be built from: gated-box corners and
    # the map's vertexes (the view position stays inside the map), + 256 slack for a view
    # nudged past the walls.
    if out:
        xs = [v for b in out.values() for v in (b[2], b[3])] + [x for x, _ in cmap.vertexes]
        ys = [v for b in out.values() for v in (b[0], b[1])] + [y for _, y in cmap.vertexes]
        span = (max(xs) - min(xs)) + (max(ys) - min(ys))
        assert span + 512 < (1 << 15), (
            f"bbox wedge cull: map spans {span} units; Q would overflow the fj signed-16-bit "
            "slices -- widen proj.wedge_bbox_plane before gating this map")
    return out


# ── BSP bake (parse the WAD's precompiled NODES/SSECTORS/SEGS) ──

def bake_bsp(wad, mapname: str) -> CompiledMap:
    """Parse the level's precompiled BSP (the SEGS/SSECTORS/NODES lumps) into a `CompiledMap`. The
    WAD's node tool emitted these with DOOM-standard winding/child encoding (0x8000 ⇒ subsector), so
    the records map straight onto our dataclasses. The root is DOOM's last node (numnodes-1); a map with
    no nodes is a single convex subsector (root = 0 | NF_SUBSECTOR)."""
    verts = [(v.x, v.y) for v in wad.vertexes(mapname)]
    segs = [Seg(s.v1, s.v2, s.angle, s.linedef, s.direction, s.offset) for s in wad.segs(mapname)]
    subsectors = [SubSector(ss.numsegs, ss.firstseg) for ss in wad.subsectors(mapname)]
    bboxes = wad.nodes_bbox(mapname)
    nodes = [Node(n.x, n.y, n.dx, n.dy, n.right, n.left, bb[0], bb[1])
             for n, bb in zip(wad.nodes(mapname), bboxes)]
    root = (len(nodes) - 1) if nodes else (0 | NF_SUBSECTOR)
    return CompiledMap(verts, segs, subsectors, nodes, root)


# ── .fj emission ──

def _bytes_stream(label: str, records: Sequence[Sequence[int]], widths: Sequence[int]) -> str:
    """Emit a packed-byte stream `label:` — each record's fields little-endian, low byte first
    (`;byte*dw` ops, read by hex.read_byte_and_inc). `widths` = byte-width per field."""
    lines = [f'// stream "{label}": {len(records)} records (doomfj.mapcompiler)', f"{label}:"]
    for rec in records:
        for value, wbytes in zip(rec, widths):
            for b in range(wbytes):
                lines.append(f"    ;{hex((value >> (8 * b)) & 0xFF)} * dw")
    return "\n".join(lines) + "\n"


_LUMP_SPECS = {
    "LINEDEFS": (lambda m: [(l.v1, l.v2, l.flags, l.special, l.tag, l.front & 0xFFFF, l.back & 0xFFFF)
                            for l in m], (2, 2, 2, 2, 2, 2, 2)),
    "SIDEDEFS": (lambda m: [(s.x_off, s.y_off, s.sector) for s in m], (2, 2, 2)),
    "SECTORS": (lambda m: [(s.floor_h, s.ceil_h, s.light, s.special, s.tag) for s in m],
                (2, 2, 2, 2, 2)),
}


def compile_map(wad, mapname: str, *, mode: str = "streams") -> str:
    """Compile a WAD level to baked `.fj`. `mode="streams"` (default) emits packed-byte streams for
    VERTEXES/LINEDEFS/SIDEDEFS/SECTORS/SEGS/SSECTORS/NODES + a `<map>_root` constant; `mode="code"`
    emits the BSP traversal as code (opt #7). LINEDEFS+VERTEXES are also F6's collision data (D1)."""
    if mode not in ("streams", "code"):
        raise ValueError(f"unknown mode {mode!r} (streams | code)")
    bsp = bake_bsp(wad, mapname)
    pfx = mapname.lower()
    out = [f"// compiled map \"{mapname}\" ({mode} mode) — BSP baked by doomfj.mapcompiler (M12i)"]

    out.append(_bytes_stream(f"{pfx}_vertexes",
                             [(x & 0xFFFF, y & 0xFFFF) for x, y in bsp.vertexes], (2, 2)))
    # remaining geometry + collision streams (LINEDEFS doubles as collision data, D1)
    for lump, (getter, widths) in _LUMP_SPECS.items():
        records = getter(getattr(wad, lump.lower())(mapname))
        out.append(_bytes_stream(f"{pfx}_{lump.lower()}", records, widths))

    # baked BSP streams
    out.append(_bytes_stream(f"{pfx}_segs",
                             [(s.v1, s.v2, s.angle, s.linedef, s.side, s.offset) for s in bsp.segs],
                             (2, 2, 2, 2, 2, 2)))
    out.append(_bytes_stream(f"{pfx}_ssectors",
                             [(ss.numsegs, ss.firstseg) for ss in bsp.subsectors], (2, 2)))
    out.append(_bytes_stream(f"{pfx}_nodes",
                             [(n.x & 0xFFFF, n.y & 0xFFFF, n.dx & 0xFFFF, n.dy & 0xFFFF,
                               n.right, n.left) for n in bsp.nodes],
                             (2, 2, 2, 2, 2, 2)))
    out.append(f"{pfx}_root = {hex(bsp.root)}    // BSP root child ref (| 0x8000 ⇒ subsector)\n")

    if mode == "code":
        out.append(_bsp_as_code(pfx, bsp))
    return "\n".join(out)


def compile_geometry_streams(wad, mapname: str) -> str:
    """Emit ONLY the raw WAD geometry streams (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS) as packed-byte data
    — the F6 line-collision data (D1) and the map's data-span contribution — WITHOUT the BSP streams.
    This is the M10/R0 map contribution: a conservative span term used by build_doom."""
    pfx = mapname.lower()
    out = [f"// {mapname!r} geometry streams (collision data, D1; BSP streams via compile_map)"]
    out.append(_bytes_stream(f"{pfx}_vertexes",
                             [(v.x & 0xFFFF, v.y & 0xFFFF) for v in wad.vertexes(mapname)], (2, 2)))
    for lump, (getter, widths) in _LUMP_SPECS.items():
        records = getter(getattr(wad, lump.lower())(mapname))
        out.append(_bytes_stream(f"{pfx}_{lump.lower()}", records, widths))
    return "\n".join(out)


def _bsp_descend_code(pfx: str, bsp: CompiledMap, leaf_action, *, done_label: str) -> str:
    """M13-prune: a DESCEND-ONLY point-location walk (R_PointInSubsector): from the root, take the
    NEAR child at every node and never visit the far side -- the leaf reached is the subsector
    containing the eye. Runs BEFORE the main walk to set the per-frame player-subsector state
    (viewz + the baked band-bank pointer), so the main walk needs no per-leaf guard blocks and
    empty subtrees can be pruned from it safely. Reuses the main walk's shared xb{i} const blocks
    and pos_leaf (same labels); path length ~tree depth (~10-20 nodes), once per frame.
    `leaf_action(s)` returns the fj lines for landing in subsector s (must end by falling
    through); the emitted code jumps to `done_label` afterwards."""
    L = f"{pfx}_bspcode"
    D = f"{pfx}_dsc"
    lines = [f"// descend-only point-location pre-walk ({len(bsp.nodes)} node blocks)"]
    lines.append(f"{D}_walk:")
    root = bsp.root
    if root & NF_SUBSECTOR:
        lines += list(leaf_action(root & (NF_SUBSECTOR - 1)))
        lines.append(f"    ;{done_label}")
        return chr(10).join(lines) + chr(10)
    lines.append(f"    ;{D}_node{root}")
    for i, n in enumerate(bsp.nodes):
        lines.append(f"{D}_node{i}:")
        lines.append(f"    stl.fcall {L}_node{i}_partition, {L}_xbret")     # SET the shared partition consts
        lines.append(f"    stl.fcall {L}_pos_leaf, {L}_pos_ret")
        lines.append(f"    stl.fcall {L}_node{i}_partition, {L}_xbret")     # CLEAR (involution)
        lines.append(f"    hex.if0 2, {L}_side, {D}_node{i}_far")
        for child, tag in ((n.left, ""), (n.right, "f")):       # back -> left is near; front -> right
            if tag == "f":
                lines.append(f"{D}_node{i}_far:")
            if child & NF_SUBSECTOR:
                lines += ["  " + ln if not ln.startswith(" ") else ln
                          for ln in leaf_action(child & (NF_SUBSECTOR - 1))]
                lines.append(f"    ;{done_label}")
            else:
                lines.append(f"    ;{D}_node{child}")
    return chr(10).join(lines) + chr(10)


def _bsp_as_code(pfx: str, bsp: CompiledMap, *, done_label: str = "bsp_done",
                 subsector_action=None, full_abort_label: str = None, prune=None,
                 inline_side: bool = False, plane_gate=None,
                 plane_gate_label: str = "tsstop", extra_gate=None) -> str:
    """BSP-as-code (opt #7): emit the front-to-back BSP walk as fj CODE. Each node becomes a code block
    whose partition line is baked as compile-time constants, so the side test is `proj.point_on_side`
    (no per-node stream read). The block visits the NEAR child subtree first (the side the viewer is on),
    then the FAR, so subsectors come out nearest-first — byte-exact vs reference_model.bsp_render_order
    (R_RenderBSPNode). Recursion uses a per-node `stl.fcall`/`stl.fret` return register: the baked tree is
    finite and each node is entered exactly once (by its single parent), so one ret reg per node suffices —
    no runtime stack. A LEAF visit runs `subsector_action(s)` — a caller-supplied callback returning the fj
    lines emitted when subsector `s` is visited (front-to-back). The DEFAULT action (None) emits the
    subsector index (4 hex digits + newline) — the M12ff order-verification action; the wall renderer (M12ll+)
    passes an action that fills the per-column param arrays for that subsector's one-sided segs (the
    walk-driven pass 1). The walk reads the viewer's 16.0 map coords from globals `vx`,`vy` and jumps to
    `done_label` when finished. Flat labels prefixed `<pfx>_bspcode_` (self-contained but for vx/vy/done_label
    + whatever the action references). px,py,dx,dy are passed to point_on_side as their 10-nibble two's-
    complement patterns. @requires hex.init (+ proj in scope)."""
    L = f"{pfx}_bspcode"
    lines = [f'// BSP-as-code for "{pfx}" (opt #7): {len(bsp.nodes)} node blocks, '
             f"{len(bsp.subsectors)} subsector leaves; walk reads vx,vy -> front-to-back subsector visits"]

    def visit(child: int) -> list:
        # M13-prune (the 12M campaign): a subtree that can contribute NOTHING to the frame (zero
        # one-sided segs anywhere below, per the caller's `prune` predicate) is skipped ENTIRELY --
        # no fcall, no node block. Byte-exact: such a subtree emits nothing and never touches
        # drawn[]/full, so removing its traversal cannot change any later decision. (The player-
        # subsector viewz setup must NOT rely on the walk when pruning -- see _bsp_descend_code.)
        if prune is not None and prune(child):
            return []
        if child & NF_SUBSECTOR:                          # leaf: run the subsector action (front-to-back)
            s = child & (NF_SUBSECTOR - 1)
            if subsector_action is None:                  # default: emit the subsector index (M12ff order)
                return [f"    hex.set 4, {L}_ss, {s}", f"    hex.print_as_digit 4, {L}_ss, 0",
                        f"    stl.output 10    // subsector {s}"]
            return list(subsector_action(s))              # M12ll+: the caller's per-subsector fj lines
        return [f"    stl.fcall {L}_node{child}, {L}_node{child}_ret"]   # interior node: recurse

    # entry: visit the root, then halt via done_label
    lines.append(f"{L}_walk:")
    lines += visit(bsp.root)
    lines.append(f"    ;{done_label}")

    # the side test is a SHARED fcall leaf (mantra #9): emit the heavy point_on_side math ONCE, not
    # unrolled per node (681 copies of two hex.mul 10 blow up the assemble). Each node sets the partition
    # const regs then fcalls it; the leaf writes `_side` and returns.
    if bsp.nodes:
        lines.append(f"{L}_pos_leaf:")
        lines.append(f"    proj.point_on_side_leaf {L}_side, vx, vy, "
                     f"{L}_cpx, {L}_cpy, {L}_cdx_mag, {L}_cdy_mag, {L}_sign_dx, {L}_sign_dy, {L}_pos_ret")

    # one code block per node: SET the partition consts (M12qq: via xor_by + xor-involution self-zeroing,
    # NOT hex.set -- the per-node hex.set 10 each paid an @-dispatch to zero a reg it overwrites; xor_by has
    # no @) -> fcall the side test -> CLEAR (xor_by again cancels, cpx..cdy back to 0) -> branch on the already-
    # computed side -> NEAR child first, FAR second. The CLEAR happens BEFORE recursion, so the children SET
    # cpx..cdy from a known-zero state (the involution's zero invariant). point_on_side_leaf only READS
    # cpx..cdy (verified), so the CLEAR exactly cancels the SET. The xb{i} block is emitted once and fcall'd
    # twice (SET + CLEAR); {L}_xbret is its shared fcall/fret return reg (dead after each fret, like pos_ret).
    for i, n in enumerate(bsp.nodes):
        if prune is not None and prune(i):                 # pruned subtree: no walk block (its xb
            lines.append(f"{L}_node{i}_partition:    // (pruned walk block; xb kept for the descend pre-walk)")
            lines.append(f"    hex.xor_by 10, {L}_cpx, {n.x & MASK40}")
            lines.append(f"    hex.xor_by 10, {L}_cpy, {n.y & MASK40}")
            lines.append(f"    hex.xor_by 8, {L}_cdx_mag, {abs(n.dx)}")
            lines.append(f"    hex.xor_by 8, {L}_cdy_mag, {abs(n.dy)}")
            lines.append(f"    hex.xor_by 1, {L}_sign_dx, {1 if n.dx < 0 else 0}")
            lines.append(f"    hex.xor_by 1, {L}_sign_dy, {1 if n.dy < 0 else 0}")
            lines.append(f"    stl.fret {L}_xbret")
            continue
        lines.append(f"{L}_node{i}:    // partition ({n.x},{n.y})+t({n.dx},{n.dy})")
        if full_abort_label:                               # M13pG1: the screen is full -> the whole subtree
            lines.append(f"    hex.if0 1, {full_abort_label}, {L}_node{i}_open")   # paints nothing (front-to-back
            lines.append(f"    stl.fret {L}_node{i}_ret")         # occlusion) -> prune it. Byte-exact: the per-seg
            lines.append(f"{L}_node{i}_open:")                    # leaf would have fret'd on `full` for every seg.
        if extra_gate is not None:
            # M13-15M: the caller's bbox wedge gate (or any other subtree-level runtime cull).
            # The callback owns the register/leaf names; it receives the node index and this
            # node's fret register so a miss can abandon the whole subtree.
            g = extra_gate(i, f"{L}_node{i}_ret")
            if g:
                lines += g
        _pg = plane_gate(i) if plane_gate is not None else 0
        if _pg:
            # M13-2S rung 3a: this subtree has NO one-sided segs, so it can only contribute PLANE
            # ATTRIBUTION and (V5) boundary PIECES. Once nothing below can write, one runtime test
            # skips it whole. This restores the M13-prune win that including two-sided segs in the
            # walk removed: those 145 E1M1 subtrees are no longer prunable at COMPILE time, so
            # they are pruned at RUNTIME instead.
            # CR-2026-08: the gate MODE comes from the callback -- mode 1 (light-only subtree)
            # tests plain tsstop (dead at claim-completion); mode 2 (the subtree holds
            # PIECE-carrying segs) tests tsbstop|(tsstop&fbspent), the same compound the
            # seg-level call sites use: pieces still record into attributed-but-undrawn columns,
            # so plain tsstop here dropped riser/lip pieces the oracle records.
            if _pg == 1:
                lines.append(f"    hex.if0 1, {plane_gate_label}, {L}_node{i}_planes_live")
                lines.append(f"    stl.fret {L}_node{i}_ret")
                lines.append(f"{L}_node{i}_planes_live:")
            else:
                lines.append(f"    hex.if1 1, tsbstop, {L}_node{i}_planes_dead")
                lines.append(f"    hex.if0 1, {plane_gate_label}, {L}_node{i}_planes_live")
                lines.append(f"    hex.if0 1, fbspent, {L}_node{i}_planes_live")
                lines.append(f"{L}_node{i}_planes_dead:")
                lines.append(f"    stl.fret {L}_node{i}_ret")
                lines.append(f"{L}_node{i}_planes_live:")
        if inline_side:
            # M13-inlinenodes: the side test SPECIALIZED per node -- baked-const subtracts and
            # baked-magnitude multiplies, no shared-leaf fcalls, no xor_by SET/CLEAR involution.
            # Same fold/compare structure as point_on_side_leaf at the same widths -> byte-exact.
            # is1/is2 = the two product terms' signs (sign_d XOR sign_partition-delta); the 4-way
            # sign-pair compare mirrors the leaf verbatim. xb{i}/pos_leaf stay emitted for the
            # descend pre-walk, which still routes through them.
            e = lines.append
            e(f"    hex.mov 10, {L}_idyv, vy")
            e(f"    hex.add_constant 10, {L}_idyv, {(-n.y) & MASK40}")   # dyv = vy - py
            e(f"    hex.sign 10, {L}_idyv, {L}_iyn{i}, {L}_iyp{i}")
            e(f"{L}_iyn{i}:")                                 # dyv < 0: |dyv| via the 5-nibble identity
            e(f"    hex.neg 5, {L}_idyv")
            e(f"    hex.zero 3, {L}_idyv + 5*dw")             # clear the sign-extension for the mul
            e(f"    hex.set 1, {L}_is1, {0 if n.dx < 0 else 1}")   # is1 = 1 XOR sign_dx
            e(f"    ;{L}_imy{i}")
            e(f"{L}_iyp{i}:")                                 # dyv >= 0: already a clean magnitude
            e(f"    hex.set 1, {L}_is1, {1 if n.dx < 0 else 0}")   # is1 = sign_dx
            e(f"{L}_imy{i}:")
            e(f"    hex.mul_const 8, {L}_ip1, {L}_idyv, {abs(n.dx)}")   # p1 = |dx| * |dyv|
            e(f"    hex.mov 10, {L}_idxv, vx")
            e(f"    hex.add_constant 10, {L}_idxv, {(-n.x) & MASK40}")   # dxv = vx - px
            e(f"    hex.sign 10, {L}_idxv, {L}_ixn{i}, {L}_ixp{i}")
            e(f"{L}_ixn{i}:")
            e(f"    hex.neg 5, {L}_idxv")
            e(f"    hex.zero 3, {L}_idxv + 5*dw")
            e(f"    hex.set 1, {L}_is2, {0 if n.dy < 0 else 1}")   # is2 = 1 XOR sign_dy
            e(f"    ;{L}_imx{i}")
            e(f"{L}_ixp{i}:")
            e(f"    hex.set 1, {L}_is2, {1 if n.dy < 0 else 0}")   # is2 = sign_dy
            e(f"{L}_imx{i}:")
            e(f"    hex.mul_const 8, {L}_ip2, {L}_idxv, {abs(n.dy)}")   # p2 = |dy| * |dxv|
            e(f"    hex.if 1, {L}_is1, {L}_ia0{i}, {L}_ia1{i}")
            e(f"{L}_ia0{i}:")                                 # p1 term positive
            e(f"    hex.if 1, {L}_is2, {L}_ipp{i}, {L}_ipm{i}")
            e(f"{L}_ipp{i}:")                                 # (+,+): back = p1 > p2
            e(f"    hex.cmp 8, {L}_ip1, {L}_ip2, {L}_node{i}_far, {L}_node{i}_far, {L}_ib{i}")
            e(f"{L}_ipm{i}:")                                 # (+,-): back unless both magnitudes 0
            e(f"    hex.if0 8, {L}_ip1, {L}_ipz{i}")
            e(f"    ;{L}_ib{i}")
            e(f"{L}_ipz{i}:")
            e(f"    hex.if0 8, {L}_ip2, {L}_node{i}_far")
            e(f"    ;{L}_ib{i}")
            e(f"{L}_ia1{i}:")                                 # p1 term negative
            e(f"    hex.if 1, {L}_is2, {L}_node{i}_far, {L}_imm{i}")     # (-,+): always front
            e(f"{L}_imm{i}:")                                 # (-,-): back = p2 > p1
            e(f"    hex.cmp 8, {L}_ip1, {L}_ip2, {L}_ib{i}, {L}_node{i}_far, {L}_node{i}_far")
            e(f"{L}_ib{i}:")                                  # back path falls through
        else:
            lines.append(f"    stl.fcall {L}_node{i}_partition, {L}_xbret")  # SET cpx/cpy/cdx/cdy (0 -> vals via xor_by)
            lines.append(f"    stl.fcall {L}_pos_leaf, {L}_pos_ret")
            lines.append(f"    stl.fcall {L}_node{i}_partition, {L}_xbret")  # CLEAR (vals -> 0, the xor involution)
            lines.append(f"    hex.if0 2, {L}_side, {L}_node{i}_far")   # back==0 (front) -> jump; else fall to back path
        lines += visit(n.left)                             # back (side>0): near=left, far=right
        lines += visit(n.right)
        lines.append(f"    stl.fret {L}_node{i}_ret")
        lines.append(f"{L}_node{i}_far:")                         # front: near=right, far=left
        lines += visit(n.right)
        lines += visit(n.left)
        lines.append(f"    stl.fret {L}_node{i}_ret")
        lines.append(f"{L}_node{i}_partition:    // the node's partition-const xor_by block (emitted once, fcall'd SET+CLEAR)")
        lines.append(f"    hex.xor_by 10, {L}_cpx, {n.x & MASK40}")
        lines.append(f"    hex.xor_by 10, {L}_cpy, {n.y & MASK40}")
        # M13-possignmag: dx/dy never re-enter a subtract (only a product), so bake them as an
        # 8-nibble zero-extended MAGNITUDE + a 1-nibble sign flag instead of a 10-nibble two's-comp
        # pattern -- lets point_on_side_leaf's cross-product run at 8 nibbles, not 10.
        lines.append(f"    hex.xor_by 8, {L}_cdx_mag, {abs(n.dx)}")
        lines.append(f"    hex.xor_by 8, {L}_cdy_mag, {abs(n.dy)}")
        lines.append(f"    hex.xor_by 1, {L}_sign_dx, {1 if n.dx < 0 else 0}")
        lines.append(f"    hex.xor_by 1, {L}_sign_dy, {1 if n.dy < 0 else 0}")
        lines.append(f"    stl.fret {L}_xbret")

    # data — never fallen into (every code path above ends in stl.fret or `;done_label`)
    if bsp.nodes:
        for nm in ("cpx", "cpy"):
            lines.append(f"{L}_{nm}: hex.vec 10")          # shared per-node partition const regs
        for nm in ("cdx_mag", "cdy_mag"):
            lines.append(f"{L}_{nm}: hex.vec 8")           # shared per-node partition magnitude regs
        for nm in ("sign_dx", "sign_dy"):
            lines.append(f"{L}_{nm}: hex.vec 1")           # shared per-node partition sign flags
        lines.append(f"{L}_side: hex.vec 2")
        if inline_side:                                    # M13-inlinenodes shared scratch
            for nm, wd in (("idxv", 10), ("idyv", 10), ("ip1", 8), ("ip2", 8), ("is1", 1), ("is2", 1)):
                lines.append(f"{L}_{nm}: hex.vec {wd}")
        lines.append(f"{L}_pos_ret: ;0")                   # the side-test leaf's fcall/fret return register
        lines.append(f"{L}_xbret: ;0")                     # the node xor_by block's fcall/fret return register (M12qq)
    lines.append(f"{L}_ss: hex.vec 4")
    for i in range(len(bsp.nodes)):
        lines.append(f"{L}_node{i}_ret: ;0")                      # per-node fcall/fret return register
    return "\n".join(lines) + "\n"
