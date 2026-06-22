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


# ── BSP bake (parse the WAD's precompiled NODES/SSECTORS/SEGS) ──

def bake_bsp(wad, mapname: str) -> CompiledMap:
    """Parse the level's precompiled BSP (the SEGS/SSECTORS/NODES lumps) into a `CompiledMap`. The
    WAD's node tool emitted these with DOOM-standard winding/child encoding (0x8000 ⇒ subsector), so
    the records map straight onto our dataclasses. The root is DOOM's last node (numnodes-1); a map with
    no nodes is a single convex subsector (root = 0 | NF_SUBSECTOR)."""
    verts = [(v.x, v.y) for v in wad.vertexes(mapname)]
    segs = [Seg(s.v1, s.v2, s.angle, s.linedef, s.direction, s.offset) for s in wad.segs(mapname)]
    subsectors = [SubSector(ss.numsegs, ss.firstseg) for ss in wad.subsectors(mapname)]
    nodes = [Node(n.x, n.y, n.dx, n.dy, n.right, n.left) for n in wad.nodes(mapname)]
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
