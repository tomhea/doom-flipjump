"""Host counts that size the 12M-campaign levers at E1M1 spawn.

1. DISTINCT VERTICES among the ~290 point_to_angle calls  -> the per-vertex angle cache lever.
2. EMPTY SUBTREES: how many of the 467 visited nodes lead to ZERO one-sided segs -> the walk
   pruning lever (a subtree with no one-sided segs emits nothing and touches nothing: skipping
   it at EMIT TIME is byte-exact).
3. BAKED BAND-LIST LUT size: distinct viewz classes x (h, light, base) keys -> the table that
   replaces every runtime build_bands call with static data.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.mapcompiler import NF_SUBSECTOR, bake_bsp, _point_side, seg_affine_coeffs
from doomfj.reference_model import ReferenceModel, ANGLE_MASK, spawn_state
from doomfj.wad import WadFile

cfg = Config()
wad = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
rm = ReferenceModel(cfg)
cmap = bake_bsp(wad, "E1M1")
lds = wad.linedefs("E1M1"); sds = wad.sidedefs("E1M1"); secs = wad.sectors("E1M1")
sp = spawn_state(wad, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
W = cfg.VIEW_W
verts = cmap.vertexes
sys.setrecursionlimit(20000)

# ---------------------------------------------------------------- 1. distinct atan vertices
# replicate the leaf funnel: wedge cull -> affine cull -> atans
sys.path.insert(0, str(ROOT / "scratchpad"))
from wedge45 import wedge_planes, halfplane_in

pA, pB = wedge_planes(sp.angle)
atan_verts = []
drawn = bytearray(W)
full = False

def seg_funnel(seg):
    v1, v2 = verts[seg.v1], verts[seg.v2]
    d1 = (v1[0] - spx, v1[1] - spy); d2 = (v2[0] - spx, v2[1] - spy)
    for m in (pA, pB):
        if not halfplane_in(m, *d1) and not halfplane_in(m, *d2):
            return None
    a, b, c = seg_affine_coeffs(seg, verts)
    if _signed((fixed_mul(a, sp.x, 8, 4) + fixed_mul(b, sp.y, 8, 4) + c) & ANGLE_MASK, 32) <= 0:
        return None
    return True

def visit(child):
    global full
    if full:
        return
    if child & NF_SUBSECTOR:
        ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            if full:
                return
            seg = cmap.segs[si]
            if lds[seg.linedef].back != -1:
                continue
            if seg_funnel(seg) is None:
                continue
            atan_verts.append(seg.v1)
            atan_verts.append(seg.v2)
            rng = rm.wall_x_range(sp.x, sp.y, sp.angle, seg, verts)
            if rng is None:
                continue
            x1, x2, _ = rng
            for x in range(max(0, x1), min(W, x2)):
                if not drawn[x]:
                    drawn[x] = 1
                    if sum(drawn) >= W:
                        full = True
        return
    n = cmap.nodes[child]
    back = _point_side(n.x, n.y, n.dx, n.dy, spx, spy) > 0
    near, far = (n.left, n.right) if back else (n.right, n.left)
    visit(near); visit(far)

visit(cmap.root)
print(f"1. atan calls: {len(atan_verts)}  distinct vertices: {len(set(atan_verts))}  "
      f"-> cacheable repeats: {len(atan_verts) - len(set(atan_verts))}")

# ---------------------------------------------------------------- 2. empty subtrees
onesided_below = {}

def count_onesided(child):
    if child & NF_SUBSECTOR:
        ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
        return sum(1 for si in range(ss.firstseg, ss.firstseg + ss.numsegs)
                   if lds[cmap.segs[si].linedef].back == -1)
    n = cmap.nodes[child]
    tot = count_onesided(n.left) + count_onesided(n.right)
    onesided_below[child] = tot
    return tot

count_onesided(cmap.root)

visited_nodes = 0
prunable_nodes = 0
full = False
drawn = bytearray(W)

def visit2(child, pruned_parent=False):
    global full, visited_nodes, prunable_nodes
    if full:
        return
    if child & NF_SUBSECTOR:
        ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
        for si in range(ss.firstseg, ss.firstseg + ss.numsegs):
            if full:
                return
            seg = cmap.segs[si]
            if lds[seg.linedef].back != -1:
                continue
            rng = rm.wall_x_range(sp.x, sp.y, sp.angle, seg, verts)
            if rng is None:
                continue
            x1, x2, _ = rng
            for x in range(max(0, x1), min(W, x2)):
                if not drawn[x]:
                    drawn[x] = 1
                    if sum(drawn) >= W:
                        full = True
        return
    visited_nodes += 1
    if onesided_below.get(child, 0) == 0:
        prunable_nodes += 1
        # a pruned subtree is not descended -- count how many nodes THAT skips too
        return
    n = cmap.nodes[child]
    back = _point_side(n.x, n.y, n.dx, n.dy, spx, spy) > 0
    near, far = (n.left, n.right) if back else (n.right, n.left)
    visit2(near); visit2(far)

visit2(cmap.root)
total_zero = sum(1 for v in onesided_below.values() if v == 0)
print(f"2. nodes visited with empty-subtree pruning: {visited_nodes} (was 467); "
      f"pruned-at-entry: {prunable_nodes}; map-wide zero-1s subtrees: {total_zero}/681")

# ---------------------------------------------------------------- 3. baked band-list LUT size
viewz_vals = set()
for ss in cmap.subsectors:
    sec = rm._seg_sector(lds, sds, secs, cmap.segs[ss.firstseg])
    viewz_vals.add(rm.view_z(sec.floor_h))
keys = set()
for seg in cmap.segs:
    if lds[seg.linedef].back != -1:
        continue
    sec = rm._seg_sector(lds, sds, secs, seg)
    fb = {}
    keys.add(("C", sec.ceil_h, sec.light & 0xFF, rm._flat_base(wad, sec.ceil_tex, fb)))
    keys.add(("F", sec.floor_h, sec.light & 0xFF, rm._flat_base(wad, sec.floor_tex, fb)))
print(f"3. distinct viewz classes: {len(viewz_vals)}   distinct (region,h,light,base) keys: {len(keys)}")
half_slots = 65
total_dw = len(viewz_vals) * len(keys) * 2 * half_slots
print(f"   baked LUT size = {len(viewz_vals)} x {len(keys)} x 2x{half_slots} dw = {total_dw:,} dw "
      f"({total_dw * 8 / 1e6:.1f} MB at dw=64b)")
