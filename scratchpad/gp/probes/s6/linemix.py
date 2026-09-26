"""Per-try line mix for the PLAYER on 32-unit collision cells (radius 16), E1M1: of the candidate
lines listed for the cell a walkable point is in, how many does the box at that point reject by
bbox, how many survive as axis-aligned, how many as diagonal. Priced with the S6 probe's MEASURED
pooled per-case costs."""
import sys, random
sys.path.insert(0, r"C:/Users/tomhe/Documents/doom-flipjump/src")
from doomfj.config import DEFAULT_MAP_WAD
from doomfj.wad import WadFile
from doomfj.mapcompiler import bake_bsp, NF_SUBSECTOR, _point_side, seg_sector
w = WadFile.from_path(DEFAULT_MAP_WAD); M = "E1M1"
cmap = bake_bsp(w, M); lds, sds, secs = w.linedefs(M), w.sidedefs(M), w.sectors(M)
V = cmap.vertexes
xs = [v[0] for v in V]; ys = [v[1] for v in V]
X0, X1, Y0, Y1 = min(xs), max(xs), min(ys), max(ys)
def leaf_sector(ss):
    s = cmap.subsectors[ss]; return seg_sector(lds, sds, secs, cmap.segs[s.firstseg])
live = {ss for ss in range(len(cmap.subsectors))
        if cmap.subsectors[ss].numsegs and leaf_sector(ss).ceil_h > leaf_sector(ss).floor_h}
def descend(x, y):
    node = cmap.root
    while not node & NF_SUBSECTOR:
        n = cmap.nodes[node]
        node = n.left if _point_side(n.x, n.y, n.dx, n.dy, x, y) > 0 else n.right
    return node & (NF_SUBSECTOR - 1)
# lines the player can collide with: one-sided, blocking, or a height change (inert 2-sided out)
rel = []
for li, ld in enumerate(lds):
    if ld.back == -1 or ld.flags & 1:
        rel.append(li); continue
    fs, bs = secs[sds[ld.front].sector], secs[sds[ld.back].sector]
    if fs.floor_h == bs.floor_h and fs.ceil_h == bs.ceil_h:
        continue
    rel.append(li)
bb, diag = {}, {}
for li in rel:
    a, b = V[lds[li].v1], V[lds[li].v2]
    bb[li] = (min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]))
    diag[li] = a[0] != b[0] and a[1] != b[1]
random.seed(3)
S, R = 32, 16
cells = {}
n = rej = ax = dg = 0
for _ in range(200000):
    x, y = random.randint(X0, X1), random.randint(Y0, Y1)
    if descend(x, y) not in live:
        continue
    cx, cy = x >> 5, y >> 5
    if (cx, cy) not in cells:
        a0, a1, b0, b1 = cx * S - R - 1, cx * S + S - 1 + R + 1, cy * S - R - 1, cy * S + S - 1 + R + 1
        cells[(cx, cy)] = [li for li in rel if a1 > bb[li][0] and a0 < bb[li][1]
                           and b1 > bb[li][2] and b0 < bb[li][3]]
    n += 1
    for li in cells[(cx, cy)]:
        mnx, mxx, mny, mxy = bb[li]
        if x + R <= mnx or x - R >= mxx or y + R <= mny or y - R >= mxy:
            rej += 1
        elif diag[li]:
            dg += 1
        else:
            ax += 1
    if n >= 20000:
        break
print("points %d; per try: candidates %.2f = bbox-rejected %.2f + axis survivors %.2f + diagonal survivors %.2f"
      % (n, (rej + ax + dg) / n, rej / n, ax / n, dg / n))
REJ, AX, DG = (238 + 1042) / 2, 1568, (14594 + 15912) / 2   # S6 MEASURED pooled, per case
print("priced with S6 pooled per-case costs (reject %.0f, axis %.0f, diag %.0f): %.0f ops per position test"
      % (REJ, AX, DG, (rej * REJ + ax * AX + dg * DG) / n))
