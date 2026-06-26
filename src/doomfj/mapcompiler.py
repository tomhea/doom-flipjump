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


def _bsp_as_code(pfx: str, bsp: CompiledMap, *, done_label: str = "bsp_done",
                 subsector_action=None) -> str:
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
        if child & NF_SUBSECTOR:                          # leaf: run the subsector action (front-to-back)
            s = child & (NF_SUBSECTOR - 1)
            if subsector_action is None:                  # default: emit the subsector index (M12ff order)
                return [f"    hex.set 4, {L}_ss, {s}", f"    hex.print_as_digit 4, {L}_ss, 0",
                        f"    stl.output 10    // subsector {s}"]
            return list(subsector_action(s))              # M12ll+: the caller's per-subsector fj lines
        return [f"    stl.fcall {L}_n{child}, {L}_r{child}"]   # interior node: recurse

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
                     f"{L}_cpx, {L}_cpy, {L}_cdx, {L}_cdy, {L}_pos_ret")

    # one code block per node: SET the partition consts (M12qq: via xor_by + xor-involution self-zeroing,
    # NOT hex.set -- the per-node hex.set 10 each paid an @-dispatch to zero a reg it overwrites; xor_by has
    # no @) -> fcall the side test -> CLEAR (xor_by again cancels, cpx..cdy back to 0) -> branch on the already-
    # computed side -> NEAR child first, FAR second. The CLEAR happens BEFORE recursion, so the children SET
    # cpx..cdy from a known-zero state (the involution's zero invariant). point_on_side_leaf only READS
    # cpx..cdy (verified), so the CLEAR exactly cancels the SET. The xb{i} block is emitted once and fcall'd
    # twice (SET + CLEAR); {L}_xbret is its shared fcall/fret return reg (dead after each fret, like pos_ret).
    for i, n in enumerate(bsp.nodes):
        lines.append(f"{L}_n{i}:    // partition ({n.x},{n.y})+t({n.dx},{n.dy})")
        lines.append(f"    stl.fcall {L}_xb{i}, {L}_xbret")  # SET cpx/cpy/cdx/cdy (0 -> vals via xor_by)
        lines.append(f"    stl.fcall {L}_pos_leaf, {L}_pos_ret")
        lines.append(f"    stl.fcall {L}_xb{i}, {L}_xbret")  # CLEAR (vals -> 0, the xor involution)
        lines.append(f"    hex.if0 2, {L}_side, {L}_nf{i}")   # back==0 (front) -> jump; else fall to back path
        lines += visit(n.left)                             # back (side>0): near=left, far=right
        lines += visit(n.right)
        lines.append(f"    stl.fret {L}_r{i}")
        lines.append(f"{L}_nf{i}:")                         # front: near=right, far=left
        lines += visit(n.right)
        lines += visit(n.left)
        lines.append(f"    stl.fret {L}_r{i}")
        lines.append(f"{L}_xb{i}:    // the node's partition-const xor_by block (emitted once, fcall'd SET+CLEAR)")
        lines.append(f"    hex.xor_by 10, {L}_cpx, {n.x & MASK40}")
        lines.append(f"    hex.xor_by 10, {L}_cpy, {n.y & MASK40}")
        lines.append(f"    hex.xor_by 10, {L}_cdx, {n.dx & MASK40}")
        lines.append(f"    hex.xor_by 10, {L}_cdy, {n.dy & MASK40}")
        lines.append(f"    stl.fret {L}_xbret")

    # data — never fallen into (every code path above ends in stl.fret or `;done_label`)
    if bsp.nodes:
        for nm in ("cpx", "cpy", "cdx", "cdy"):
            lines.append(f"{L}_{nm}: hex.vec 10")          # shared per-node partition const regs
        lines.append(f"{L}_side: hex.vec 2")
        lines.append(f"{L}_pos_ret: ;0")                   # the side-test leaf's fcall/fret return register
        lines.append(f"{L}_xbret: ;0")                     # the node xor_by block's fcall/fret return register (M12qq)
    lines.append(f"{L}_ss: hex.vec 4")
    for i in range(len(bsp.nodes)):
        lines.append(f"{L}_r{i}: ;0")                      # per-node fcall/fret return register
    return "\n".join(lines) + "\n"
