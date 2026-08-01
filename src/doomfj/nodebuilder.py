"""A DOOM BSP node builder — the tooling gap EXP-12 named as the 15M blocker.

`bake_bsp` READS the wad's precompiled SEGS/SSECTORS/NODES; nothing in the repo could WRITE them,
so the only fast maps were convex rings (scratchpad/make_arena.py). This builds the three lumps for
ARBITRARY geometry, which is what lets E1M1 itself be simplified and re-noded.

Conventions (must mirror the walk in reference_model / mapcompiler exactly):
  * `_point_side(px,py,dx,dy, x,y) = dx*(y-py) - dy*(x-px)`; **< 0 is FRONT/RIGHT** (DOOM's
    right=front), > 0 is BACK/LEFT, on-the-line counts as front. Node.right is the front child.
  * A collinear seg goes to the side its DIRECTION faces: dot(seg_dir, part_dir) > 0 -> front.
  * The root is the LAST node record. Child refs carry NF_SUBSECTOR (0x8000) for leaves.
  * SEGS records: (v1, v2, angle: BAM>>16 of v1->v2, linedef, direction 0=front/1=back,
    offset: map units along the linedef from its start vertex — v1 for direction 0, v2 for 1).

Quality target is OUR cost model, not vanilla's: frame ops scale with total segs (walk skeleton +
per-seg xorby), one-sided segs (the per-frame wedge cull) and node count, so the partition score
punishes SPLITS hard and balance only breaks ties.

Precision: endpoints live as floats during recursion (splits land exactly on the partition line);
vertices are rounded to the integer grid only at emit, deduplicated by rounded coordinate. That is
what the classic node tools did; the renderer's column-claim occlusion is insensitive to the
sub-unit seams this can create.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, replace
from pathlib import Path

NF_SUBSECTOR = 0x8000
SPLIT_COST = 32         # one split = one extra seg forever; balance is only a tie-break
                        # (tuned on stock E1M1: 8/16/32 -> 2126/2106/2057 segs)
MAX_CANDIDATES = 64     # partition candidates sampled per recursion level
DIAG_PENALTY = 4        # slight preference for axis-aligned partitions (fewer splits measured)


@dataclass
class BSeg:
    x1: float
    y1: float
    x2: float
    y2: float
    linedef: int
    side: int            # 0 = front (same direction as the linedef), 1 = back
    offset: float        # along the linedef from ITS OWN start vertex for this side
    sector: int          # the sector this seg FRONTS (from its sidedef) — leaf sanity check
    angle: int           # BAM>>16, direction v1->v2, inherited unchanged through splits
    # the seg's ORIGINAL linedef line, oriented seg-wise, in EXACT integer coordinates. Partitions
    # must come from THIS, never from split-fragment endpoints: a short rounded fragment's
    # direction is quantized, which rotates the node plane off the true wall line and
    # misclassifies points near walls (measured: point_in_subsector landed (-309,-44) in the
    # wrong sector). Splits inherit it unchanged.
    lx: int = 0
    ly: int = 0
    ldx: int = 0
    ldy: int = 0


def _bam(dx: float, dy: float) -> int:
    return round(math.atan2(dy, dx) / (2 * math.pi) * 65536) & 0xFFFF


def initial_segs(verts, linedefs, sidedefs) -> list[BSeg]:
    segs = []
    for li, ld in enumerate(linedefs):
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        if ld.front != -1:
            segs.append(BSeg(x1, y1, x2, y2, li, 0, 0.0,
                             sidedefs[ld.front].sector, _bam(x2 - x1, y2 - y1),
                             x1, y1, x2 - x1, y2 - y1))
        if ld.back != -1:
            segs.append(BSeg(x2, y2, x1, y1, li, 1, 0.0,
                             sidedefs[ld.back].sector, _bam(x1 - x2, y1 - y2),
                             x2, y2, x1 - x2, y1 - y2))
    return segs


# ── classification against a partition line ──

FRONT, BACK, SPAN, COL_F, COL_B = range(5)


def _classify(s: BSeg, px, py, pdx, pdy, eps_cross):
    c1 = pdx * (s.y1 - py) - pdy * (s.x1 - px)      # < 0 front (mapcompiler._point_side)
    c2 = pdx * (s.y2 - py) - pdy * (s.x2 - px)
    on1, on2 = abs(c1) <= eps_cross, abs(c2) <= eps_cross
    if on1 and on2:
        dot = pdx * (s.x2 - s.x1) + pdy * (s.y2 - s.y1)
        return (COL_F if dot > 0 else COL_B), c1, c2
    if (c1 < 0 or on1) and (c2 < 0 or on2):
        return FRONT, c1, c2
    if (c1 > 0 or on1) and (c2 > 0 or on2):
        return BACK, c1, c2
    return SPAN, c1, c2


def _split(s: BSeg, c1: float, c2: float) -> tuple[BSeg, BSeg]:
    """Split s at the point where the partition's cross value passes 0. Returns (near_part_from_v1,
    far_part_to_v2); the caller routes each by the sign of its half's cross value."""
    t = c1 / (c1 - c2)
    mx, my = s.x1 + t * (s.x2 - s.x1), s.y1 + t * (s.y2 - s.y1)
    run = math.hypot(mx - s.x1, my - s.y1)
    a = replace(s, x2=mx, y2=my)
    b = replace(s, x1=mx, y1=my, offset=s.offset + run)
    return a, b


class NodeBuilder:
    def __init__(self, verts, linedefs, sidedefs, *, split_cost=SPLIT_COST):
        self.split_cost = split_cost
        self.segs_in = initial_segs(verts, linedefs, sidedefs)
        self.out_verts: list[tuple[int, int]] = [(v[0], v[1]) for v in verts]
        self._vidx = {v: i for i, v in enumerate(self.out_verts)}
        self.out_segs: list[tuple] = []      # raw SEGS records
        self.out_ss: list[tuple] = []        # (numsegs, firstseg)
        self.out_nodes: list[tuple] = []     # (x, y, dx, dy, bbR, bbL, right, left)
        self.mixed_leaves = 0

    # ── emit helpers ──
    def _vert(self, x: float, y: float) -> int:
        key = (round(x), round(y))
        i = self._vidx.get(key)
        if i is None:
            i = len(self.out_verts)
            self.out_verts.append(key)
            self._vidx[key] = i
        return i

    def _emit_leaf(self, segs: list[BSeg]) -> int:
        first = len(self.out_segs)
        if len({s.sector for s in segs}) > 1:
            self.mixed_leaves += 1
        for s in segs:
            self.out_segs.append((self._vert(s.x1, s.y1), self._vert(s.x2, s.y2),
                                  s.angle, s.linedef, s.side,
                                  round(s.offset) & 0xFFFF))
        self.out_ss.append((len(segs), first))
        return (len(self.out_ss) - 1) | NF_SUBSECTOR

    # ── partitioning ──
    def _score(self, cand: BSeg, segs: list[BSeg]):
        px, py, pdx, pdy = cand.lx, cand.ly, cand.ldx, cand.ldy
        eps = 0.4 * math.hypot(pdx, pdy)
        nf = nb = sp = 0
        for s in segs:
            cls, _, _ = _classify(s, px, py, pdx, pdy, eps)
            if cls == SPAN:
                sp += 1
                nf += 1
                nb += 1
            elif cls in (FRONT, COL_F):
                nf += 1
            else:
                nb += 1
        if nb == 0 and sp == 0:
            return None                      # does not separate anything
        cost = sp * self.split_cost + abs(nf - nb)
        if pdx and pdy:
            cost += DIAG_PENALTY
        return cost, sp

    def _partition(self, segs: list[BSeg], cand: BSeg):
        px, py, pdx, pdy = cand.lx, cand.ly, cand.ldx, cand.ldy
        eps = 0.4 * math.hypot(pdx, pdy)
        front, back = [], []
        for s in segs:
            cls, c1, c2 = _classify(s, px, py, pdx, pdy, eps)
            if cls in (FRONT, COL_F):
                front.append(s)
            elif cls in (BACK, COL_B):
                back.append(s)
            else:
                a, b = _split(s, c1, c2)
                (front if c1 < 0 else back).append(a)
                (back if c1 < 0 else front).append(b)
        return front, back

    def _build(self, segs: list[BSeg]) -> int:
        # candidate sample: spread evenly; ALL segs when small (leaf detection must be exhaustive)
        if len(segs) <= MAX_CANDIDATES:
            cands = segs
        else:
            step = len(segs) / MAX_CANDIDATES
            cands = [segs[int(i * step)] for i in range(MAX_CANDIDATES)]
        best, best_seg = None, None
        for c in cands:
            sc = self._score(c, segs)
            if sc is not None and (best is None or sc < best):
                best, best_seg = sc, c
        if best is None and len(segs) > MAX_CANDIDATES:
            for c in segs:                    # sampled miss — exhaustive before declaring a leaf
                sc = self._score(c, segs)
                if sc is not None and (best is None or sc < best):
                    best, best_seg = sc, c
        if best is None:
            return self._emit_leaf(segs)

        front, back = self._partition(segs, best_seg)
        assert front and back, f"degenerate partition: {len(front)}/{len(back)} of {len(segs)}"
        r = self._build(front)
        l = self._build(back)
        bbr, bbl = self._bbox(front), self._bbox(back)
        self.out_nodes.append((best_seg.lx, best_seg.ly, best_seg.ldx, best_seg.ldy,
                               bbr, bbl, r, l))
        return len(self.out_nodes) - 1

    @staticmethod
    def _bbox(segs: list[BSeg]):
        xs = [c for s in segs for c in (s.x1, s.x2)]
        ys = [c for s in segs for c in (s.y1, s.y2)]
        # DOOM bbox order: top (max y), bottom, left (min x), right
        return (round(max(ys)), round(min(ys)), round(min(xs)), round(max(xs)))

    def build(self):
        import sys
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(10000)
        try:
            root = self._build(self.segs_in)
        finally:
            sys.setrecursionlimit(old)
        assert len(self.out_segs) < 32768 and len(self.out_nodes) < 32768
        assert len(self.out_verts) < 65536
        # a map so simple it is one convex leaf: NODES stays empty (the square-room shape)
        return root


# ── lump serialization ──

def lumps(nb: NodeBuilder) -> dict[str, bytes]:
    segs = b"".join(struct.pack("<6H", v1, v2, ang, ld, side, off)
                    for v1, v2, ang, ld, side, off in nb.out_segs)
    ss = b"".join(struct.pack("<2H", n, f) for n, f in nb.out_ss)
    nodes = b"".join(struct.pack("<4h8h2H", x, y, dx, dy, *bbr, *bbl, r, l)
                     for x, y, dx, dy, bbr, bbl, r, l in nb.out_nodes)
    verts = b"".join(struct.pack("<2h", x, y) for x, y in nb.out_verts)
    return {"VERTEXES": verts, "SEGS": segs, "SSECTORS": ss, "NODES": nodes}


def write_map_wad(out_path: str | Path, mapname: str, lump_dict: dict[str, bytes]):
    """Write a PWAD holding one map. `lump_dict` must contain THINGS/LINEDEFS/SIDEDEFS/VERTEXES/
    SEGS/SSECTORS/NODES/SECTORS (the order DOOM requires is imposed here)."""
    order = ["THINGS", "LINEDEFS", "SIDEDEFS", "VERTEXES", "SEGS", "SSECTORS", "NODES", "SECTORS"]
    entries = [(mapname, b"")] + [(n, lump_dict[n]) for n in order]
    data, direntries, off = b"", [], 12
    for name, payload in entries:
        direntries.append((off, len(payload), name))
        data += payload
        off += len(payload)
    header = struct.pack("<4sii", b"PWAD", len(entries), 12 + len(data))
    directory = b"".join(struct.pack("<ii8s", o, sz, nm.encode().ljust(8, b"\0"))
                         for o, sz, nm in direntries)
    Path(out_path).write_bytes(header + data + directory)


def rebuild_wad(in_path: str | Path, mapname: str, out_path: str | Path,
                *, things=None, linedefs=None, sidedefs=None, vertexes=None, sectors=None):
    """Re-node a map: copy THINGS/LINEDEFS/SIDEDEFS/SECTORS (or the given replacements) and build
    fresh VERTEXES/SEGS/SSECTORS/NODES. Returns the NodeBuilder for stats."""
    from doomfj.wad import WadFile
    w = WadFile.from_path(str(in_path))
    verts = vertexes if vertexes is not None else [(v.x, v.y) for v in w.vertexes(mapname)]
    lds = linedefs if linedefs is not None else w.linedefs(mapname)
    sds = sidedefs if sidedefs is not None else w.sidedefs(mapname)
    secs = sectors if sectors is not None else w.sectors(mapname)
    ths = things if things is not None else w.things(mapname)

    nb = NodeBuilder(verts, lds, sds)
    nb.build()
    ld_b = b"".join(struct.pack("<7h", ld.v1, ld.v2, ld.flags, ld.special, ld.tag,
                                ld.front, ld.back) for ld in lds)
    sd_b = b"".join(struct.pack("<2h8s8s8sh", sd.x_off, sd.y_off,
                                _tex8(sd.upper), _tex8(sd.lower), _tex8(sd.middle),
                                sd.sector) for sd in sds)
    sec_b = b"".join(struct.pack("<2h8s8s3h", s.floor_h, s.ceil_h, _tex8(s.floor_tex),
                                 _tex8(s.ceil_tex), s.light, s.special, s.tag) for s in secs)
    th_b = b"".join(struct.pack("<5h", t.x, t.y, t.angle, t.type, t.flags) for t in ths)
    ld = lumps(nb)
    ld.update({"THINGS": th_b, "LINEDEFS": ld_b, "SIDEDEFS": sd_b, "SECTORS": sec_b})
    write_map_wad(out_path, mapname, ld)
    return nb


def _tex8(name: str) -> bytes:
    return name.encode().ljust(8, b"\0")
