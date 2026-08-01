"""Validate a BSP tree's POINT LOCATION against an exact ray-cast sector oracle.

The engine trusts point_in_subsector for viewz (eye height) and thing leaf ownership, so a rebuilt
tree must resolve walkable points to the right sector. The failure mode being hunted: partition
lines EXTENDED through open space slice seg-less slivers off a sector, and those slivers glue onto
whatever leaf the recursion finishes there (measured: (-309,-44) landed in a decorative island's
leaf, floor 16 vs 0 -> wrong viewz -> 8,450 px).

Exact oracle: cast a +x ray, find the NEAREST linedef crossing, take that linedef's sector on the
side facing the point. Points with no crossing are void (skipped).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.mapcompiler import bake_bsp, _point_side, NF_SUBSECTOR   # noqa: E402
from doomfj.wad import WadFile                                       # noqa: E402


def true_sector(verts, lds, sds, x, y):
    """Sector at (x,y) via the nearest +x ray crossing. Returns -1 for void/indeterminate."""
    best_t, best = None, -1
    for ld in lds:
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        if (y1 > y) == (y2 > y):
            continue                                    # no crossing of the horizontal at y
        t = x1 + (y - y1) * (x2 - x1) / (y2 - y1)       # x of the crossing
        if t <= x:
            continue
        if best_t is None or t < best_t:
            # the point is left of the crossing; which side of the line is it on?
            side = _point_side(x1, y1, x2 - x1, y2 - y1, x, y)
            sd = ld.back if side > 0 else ld.front
            best_t, best = t, (sds[sd].sector if sd != -1 else -1)
    return best


def _near_any_line(verts, lds, x, y, eps):
    for ld in lds:
        (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
        if min(x1, x2) - eps <= x <= max(x1, x2) + eps and \
           min(y1, y2) - eps <= y <= max(y1, y2) + eps:
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            if L2 == 0:
                continue
            c = dx * (y - y1) - dy * (x - x1)
            if c * c <= eps * eps * L2:
                return True
    return False


def tree_sector(cmap, lds, sds, x, y):
    node = cmap.root
    while not node & NF_SUBSECTOR:
        n = cmap.nodes[node]
        node = n.left if _point_side(n.x, n.y, n.dx, n.dy, x, y) > 0 else n.right
    ss = cmap.subsectors[node & (NF_SUBSECTOR - 1)]
    seg = cmap.segs[ss.firstseg]
    ld = lds[seg.linedef]
    sd = ld.back if seg.side else ld.front
    return sds[sd].sector


def validate(wad_path, mapname, *, step=64, ref_wad=None):
    w = WadFile.from_path(str(wad_path))
    rw = WadFile.from_path(str(ref_wad)) if ref_wad else w
    verts = [(v.x, v.y) for v in rw.vertexes(mapname)]
    lds, sds = rw.linedefs(mapname), rw.sidedefs(mapname)
    secs = rw.sectors(mapname)
    cmap = bake_bsp(w, mapname)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    n = bad = badz = 0
    misses = []
    # +13/+7 jitter: the map's geometry sits on an 8/16-unit lattice, and a grid point exactly ON
    # a boundary line is ambiguous for BOTH locators — not a real mismatch.
    for x in range(min(xs) + 13, max(xs), step):
        for y in range(min(ys) + 7, max(ys), step):
            if _near_any_line(verts, lds, x, y, 2.0):
                continue
            ts = true_sector(verts, lds, sds, x, y)
            if ts == -1:
                continue
            got = tree_sector(cmap, lds, sds, x, y)
            n += 1
            if got != ts:
                bad += 1
                if (secs[got].floor_h, secs[got].light) != (secs[ts].floor_h, secs[ts].light):
                    badz += 1                       # the mismatch CHANGES viewz/light: gameplay-real
                    misses.append((x, y, ts, got))
    return n, bad, badz, misses


if __name__ == "__main__":
    wad = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/e1m1_renode.wad"
    ref = sys.argv[2] if len(sys.argv) > 2 else "tests/fixtures/freedoom_e1m1.wad"
    for name, path, refp in [("stock", ref, None), ("rebuilt", wad, ref)]:
        n, bad, badz, misses = validate(path, "E1M1", step=48, ref_wad=refp)
        print(f"{name:8s}: {n} walkable points, {bad} sector mismatches, "
              f"{badz} with WRONG floor/light")
        for m in misses[:8]:
            print(f"    ({m[0]},{m[1]}) true sec {m[2]} got {m[3]}")
