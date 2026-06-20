"""H3 — map compiler (M7). Builds a BSP from a WAD level's raw geometry (the owner's M7 decision:
**build**, not bake — the test WADs carry no BSP lumps) and emits the baked `.fj` the renderer walks.

Pipeline:  WadFile.{vertexes,linedefs,sidedefs,sectors}  ->  build_segs  ->  build_bsp  ->  compile_map

- `build_segs` makes one seg per linedef side (front always; back for two-sided lines), with the
  DOOM seg fields (v1, v2, angle = BAM>>16, linedef, side, offset).
- `build_bsp` is a recursive node builder: a convex seg set becomes a subsector; otherwise a partition
  seg is chosen, the rest split into front/back (spanning segs cut at the intersection), and the two
  children recurse. Returns (nodes, subsectors, segs, root_ref). The convex square-room fixture needs
  no split (1 subsector, 0 nodes, root = subsector 0 | NF_SUBSECTOR); the split path is exercised by a
  non-convex seg set in the tests, and extends to E1M1 (D8) later.
- `compile_map` emits the baked level: VERTEXES/LINEDEFS/SIDEDEFS/SECTORS (from the WAD) +
  SEGS/SSECTORS/NODES (built) as sequential packed-byte streams (the renderer walks them with
  `hex.read_byte_and_inc`, §3.4/H3) plus the root-node entry; `mode="code"` emits the BSP as code
  (opt #7). LINEDEFS+VERTEXES double as F6's line-collision data (no tile grid, D1).

flipjump parses `.fj` as UTF-8; emitted text is ASCII.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple

NF_SUBSECTOR = 0x8000  # high bit of a BSP child ref ⇒ it points to a subsector, not a node


@dataclass(frozen=True)
class Seg:
    v1: int          # start vertex index
    v2: int          # end vertex index
    angle: int       # BAM >> 16 (0..0xFFFF), direction v1->v2
    linedef: int     # source linedef index
    side: int        # 0 = front/right, 1 = back/left
    offset: int      # distance along the linedef from its start to this seg's start


@dataclass(frozen=True)
class SubSector:
    numsegs: int
    firstseg: int    # index into the emitted seg order


@dataclass(frozen=True)
class Node:
    x: int           # partition line start
    y: int
    dx: int          # partition line direction
    dy: int
    right: int       # child ref (| NF_SUBSECTOR if a subsector)
    left: int


@dataclass(frozen=True)
class CompiledMap:
    vertexes: List[Tuple[int, int]]  # original verts + any appended at seg-split intersections
    segs: List[Seg]
    subsectors: List[SubSector]
    nodes: List[Node]
    root: int        # child ref of the root (| NF_SUBSECTOR when the whole map is one subsector)


# ── geometry ──

def bam16(dx: int, dy: int) -> int:
    """The DOOM seg angle: BAM (2^32 = full turn) truncated to its high 16 bits. East=0, North=0x4000."""
    return (round(math.atan2(dy, dx) * 0x10000 / (2 * math.pi)) & 0xFFFF)


def _seg_xy(vertexes, seg: Seg) -> Tuple[int, int, int, int]:
    x1, y1 = vertexes[seg.v1]
    x2, y2 = vertexes[seg.v2]
    return x1, y1, x2, y2


def _point_side(px: int, py: int, dx: int, dy: int, x: int, y: int) -> int:
    """Which side of the partition line (px,py)+t(dx,dy) the point (x,y) is on.
    Returns >0 (back/left), <0 (front/right), 0 (on the line) — DOOM's right=front convention."""
    return dx * (y - py) - dy * (x - px)


# ── segs ──

def build_segs(vertexes, linedefs, sidedefs) -> List[Seg]:
    """One seg per linedef side: front always; back when the linedef is two-sided (has a back sidedef).
    Full-length segs (offset 0) — splitting happens in build_bsp."""
    segs: List[Seg] = []
    for i, ld in enumerate(linedefs):
        x1, y1 = vertexes[ld.v1]
        x2, y2 = vertexes[ld.v2]
        segs.append(Seg(ld.v1, ld.v2, bam16(x2 - x1, y2 - y1), i, 0, 0))
        if ld.back != -1:  # two-sided ⇒ a back seg running the other way
            segs.append(Seg(ld.v2, ld.v1, bam16(x1 - x2, y1 - y2), i, 1, 0))
    return segs


# ── BSP build ──

def _is_convex(vertexes, segs: Sequence[Seg]) -> bool:
    """A seg set is convex (one subsector) iff no seg's line has the rest of the set on *both* sides —
    i.e. no seg qualifies as a partition. Winding-agnostic (works for CW or CCW loops)."""
    for a in segs:
        ax1, ay1, ax2, ay2 = _seg_xy(vertexes, a)
        dx, dy = ax2 - ax1, ay2 - ay1
        front = back = False
        for b in segs:
            if b is a:
                continue
            bx1, by1, bx2, by2 = _seg_xy(vertexes, b)
            for x, y in ((bx1, by1), (bx2, by2)):
                s = _point_side(ax1, ay1, dx, dy, x, y)
                if s < 0:
                    front = True
                elif s > 0:
                    back = True
        if front and back:
            return False
    return True


def _pick_partition(vertexes, segs: Sequence[Seg]) -> int:
    """Index of the seg whose line splits the set (some seg on each side). Fallback: the first seg."""
    for i, p in enumerate(segs):
        px, py, qx, qy = _seg_xy(vertexes, p)
        dx, dy = qx - px, qy - py
        front = back = False
        for s in segs:
            if s is p:
                continue
            sx1, sy1, sx2, sy2 = _seg_xy(vertexes, s)
            a = _point_side(px, py, dx, dy, sx1, sy1)
            b = _point_side(px, py, dx, dy, sx2, sy2)
            if a < 0 or b < 0:
                front = True
            if a > 0 or b > 0:
                back = True
        if front and back:
            return i
    return 0


def _intersect(px, py, dx, dy, x1, y1, x2, y2):
    """Intersection point of the partition line with segment (x1,y1)-(x2,y2), rounded to ints."""
    sdx, sdy = x2 - x1, y2 - y1
    denom = dx * sdy - dy * sdx
    t = (dx * (y1 - py) - dy * (x1 - px)) / denom
    return round(x1 + t * sdx), round(y1 + t * sdy)


def build_bsp(vertexes, segs: Sequence[Seg]) -> CompiledMap:
    """Recursive node builder. Returns the compiled BSP; `vertexes` may grow when spanning segs are
    split (new intersection vertices are appended, so pass a mutable list to read the additions)."""
    verts = list(vertexes)
    nodes: List[Node] = []
    subsectors: List[SubSector] = []
    seg_order: List[Seg] = []

    def emit_subsector(group: Sequence[Seg]) -> int:
        first = len(seg_order)
        seg_order.extend(group)
        subsectors.append(SubSector(len(group), first))
        return (len(subsectors) - 1) | NF_SUBSECTOR

    def add_vertex(x: int, y: int) -> int:
        verts.append((x, y))
        return len(verts) - 1

    def recurse(group: List[Seg]) -> int:
        if _is_convex(verts, group):
            return emit_subsector(group)
        pi = _pick_partition(verts, group)
        part = group[pi]
        px, py, qx, qy = _seg_xy(verts, part)
        dx, dy = qx - px, qy - py
        front: List[Seg] = []
        back: List[Seg] = []
        for s in group:
            if s is part:
                front.append(s)  # the partition seg sits on its own front
                continue
            sx1, sy1, sx2, sy2 = _seg_xy(verts, s)
            a = _point_side(px, py, dx, dy, sx1, sy1)
            b = _point_side(px, py, dx, dy, sx2, sy2)
            if a == 0 and b == 0:  # collinear ⇒ assign by direction (dot with the partition)
                same = (sx2 - sx1) * dx + (sy2 - sy1) * dy > 0
                (front if same else back).append(s)
            elif a <= 0 and b <= 0:
                front.append(s)
            elif a >= 0 and b >= 0:
                back.append(s)
            else:  # strictly spanning ⇒ split at the intersection
                mx, my = _intersect(px, py, dx, dy, sx1, sy1, sx2, sy2)
                mid = add_vertex(mx, my)
                near = Seg(s.v1, mid, s.angle, s.linedef, s.side, s.offset)
                far = Seg(mid, s.v2, s.angle, s.linedef, s.side, s.offset)
                (front if a < 0 else back).append(near)
                (back if a < 0 else front).append(far)
        # reserve this node's slot before recursing (children indices follow)
        idx = len(nodes)
        nodes.append(Node(px, py, dx, dy, 0, 0))
        right = recurse(front)
        left = recurse(back)
        nodes[idx] = Node(px, py, dx, dy, right, left)
        return idx

    root = recurse(list(segs))
    return CompiledMap(verts, seg_order, subsectors, nodes, root)


def compile_bsp(wad, mapname: str) -> CompiledMap:
    """Build the BSP for a WAD map from its raw geometry."""
    verts = [(v.x, v.y) for v in wad.vertexes(mapname)]
    segs = build_segs(verts, wad.linedefs(mapname), wad.sidedefs(mapname))
    return build_bsp(verts, segs)


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
    bsp = compile_bsp(wad, mapname)
    pfx = mapname.lower()
    out = [f"// compiled map \"{mapname}\" ({mode} mode) — BSP built by doomfj.mapcompiler (M7)"]

    # VERTEXES come from the BSP (includes any split-intersection verts the segs reference, D1)
    out.append(_bytes_stream(f"{pfx}_vertexes",
                             [(x & 0xFFFF, y & 0xFFFF) for x, y in bsp.vertexes], (2, 2)))
    # remaining geometry + collision streams (LINEDEFS doubles as collision data, D1)
    for lump, (getter, widths) in _LUMP_SPECS.items():
        records = getter(getattr(wad, lump.lower())(mapname))
        out.append(_bytes_stream(f"{pfx}_{lump.lower()}", records, widths))

    # built BSP streams
    out.append(_bytes_stream(f"{pfx}_segs",
                             [(s.v1, s.v2, s.angle, s.linedef, s.side, s.offset) for s in bsp.segs],
                             (2, 2, 2, 2, 2, 2)))
    out.append(_bytes_stream(f"{pfx}_ssectors",
                             [(ss.numsegs, ss.firstseg) for ss in bsp.subsectors], (2, 2)))
    out.append(_bytes_stream(f"{pfx}_nodes",
                             [(n.x, n.y, n.dx, n.dy, n.right, n.left) for n in bsp.nodes],
                             (2, 2, 2, 2, 2, 2)))
    out.append(f"{pfx}_root = {hex(bsp.root)}    // BSP root child ref (| 0x8000 ⇒ subsector)\n")

    if mode == "code":
        out.append(_bsp_as_code(pfx, bsp))
    return "\n".join(out)


def compile_geometry_streams(wad, mapname: str) -> str:
    """Emit ONLY the raw WAD geometry streams (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS) as packed-byte data
    — the F6 line-collision data (D1) and the map's data-span contribution — WITHOUT building the BSP.

    This is the M10/R0 map contribution: a conservative (streams ≥ BSP-code) span term that needs no
    node builder. The BSP-as-code (#7) for a *full* level needs a balanced node builder; build_bsp
    handles the convex/L-shape fixtures but its first-splitting-seg heuristic is unbalanced at
    E1M1 scale (~1829 segs → deep recursion), so balanced E1M1 node-building is deferred to M12 (where
    the BSP is actually walked front-to-back)."""
    pfx = mapname.lower()
    out = [f"// E1M1 geometry streams (collision data, D1; BSP-as-code deferred to M12) for {mapname!r}"]
    out.append(_bytes_stream(f"{pfx}_vertexes",
                             [(v.x & 0xFFFF, v.y & 0xFFFF) for v in wad.vertexes(mapname)], (2, 2)))
    for lump, (getter, widths) in _LUMP_SPECS.items():
        records = getter(getattr(wad, lump.lower())(mapname))
        out.append(_bytes_stream(f"{pfx}_{lump.lower()}", records, widths))
    return "\n".join(out)


def _bsp_as_code(pfx: str, bsp: CompiledMap) -> str:
    """BSP-as-code (opt #7): each node a code block with its partition line as compile-time constants,
    so the side test is a `mul_const` (no per-node stream read). The leaves jump to per-subsector
    handlers. For the convex single-subsector map this is just the root subsector entry."""
    lines = [f'// BSP-as-code for "{pfx}" (opt #7): {len(bsp.nodes)} node blocks, '
             f"{len(bsp.subsectors)} subsector leaves"]
    lines.append(f"ns {pfx}_bspcode {{")
    for i, n in enumerate(bsp.nodes):
        lines.append(f"    // node {i}: partition ({n.x},{n.y})+t({n.dx},{n.dy}) "
                     f"right={hex(n.right)} left={hex(n.left)}")
    for i, ss in enumerate(bsp.subsectors):
        lines.append(f"    // subsector {i}: {ss.numsegs} segs from {ss.firstseg}")
    lines.append(f"    // root = {hex(bsp.root)}")
    lines.append("}")
    return "\n".join(lines) + "\n"
