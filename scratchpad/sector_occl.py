"""Host check: the sector-occlusion pre-cull's catch rate at E1M1 spawn.

Frame setup bakes K angular sector boundaries (45-degree-family directions, integer-compare
classifiable) -> per-frame column boundaries via angle_to_x. Per claimed column: find its sector,
bump a counter. Per seg BEFORE the atans: classify both vertices' sectors cheaply; if every sector
the seg's conservative bracket touches is FULL, the seg is provably occluded -> skip both atans.
Conservative: never wrongly culls (superset of the true column range).
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, ANGLE_MASK, spawn_state
from doomfj.mapcompiler import bake_bsp
from doomfj.wad import WadFile

cfg = Config()
wad = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
rm = ReferenceModel(cfg)
cmap = bake_bsp(wad, "E1M1")
lds = wad.linedefs("E1M1")
sp = spawn_state(wad, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
W = cfg.VIEW_W
verts = cmap.vertexes
va = sp.angle

# sector boundary directions: the D16 family (slopes 0, +-1/2, +-1, +-2, inf) = 16 directions;
# classification per vertex = a handful of integer compares on (dx, dy, 2dy vs dx, dy vs 2dx...).
DIRS = sorted(math.atan2(dy, dx) % (2 * math.pi)
              for dx, dy in [(1, 0), (2, 1), (1, 1), (1, 2), (0, 1), (-1, 2), (-1, 1), (-2, 1),
                             (-1, 0), (-2, -1), (-1, -1), (-1, -2), (0, -1), (1, -2), (1, -1), (2, -1)])
BAMS = [int(a / (2 * math.pi) * (1 << 32)) & ANGLE_MASK for a in DIRS]

def vsector(px, py):
    """index i such that angle(v-eye) in [BAMS[i], BAMS[i+1])."""
    ang = rm.point_to_angle(sp.x, sp.y, px << 16, py << 16)
    best = None
    for i, b in enumerate(BAMS):
        if ((ang - b) & ANGLE_MASK) < ((ang - BAMS[best]) & ANGLE_MASK) if best is not None else True:
            pass
    # simpler: find i with (ang - BAMS[i]) mod 2^32 minimal among those where ang >= BAMS[i] going ccw
    diffs = [((ang - b) & ANGLE_MASK) for b in BAMS]
    return diffs.index(min(diffs))

# per-frame: column of each boundary (clamped into [0, W])
def bound_col(bam):
    rel = (bam - va) & ANGLE_MASK
    srel = rel - (1 << 32) if rel > (1 << 31) else rel
    if srel > 0x20000000:
        return 0
    if srel < -0x20000000:
        return W
    return max(0, min(W, rm.angle_to_x(rel)))

cols = [bound_col(b) for b in BAMS]
# sector i covers columns [min(c_i, c_{i+1}), max(...)) -- angles decrease left->right on screen
sec_range = []
for i in range(16):
    c1, c2 = cols[i], cols[(i + 1) % 16]
    lo, hi = min(c1, c2), max(c1, c2)
    sec_range.append((lo, hi))

drawn = bytearray(W)
counts = [0] * 16
widths = [hi - lo for lo, hi in sec_range]

skipped_atans = 0
occ_total = 0
checked = 0
for seg_i in rm.visible_segs(cmap, spx, spy):
    seg = cmap.segs[seg_i]
    if lds[seg.linedef].back != -1:
        continue
    if sum(drawn) >= W:
        break
    # only front-facing segs reach the atans (affine cull first)
    from doomfj.mapcompiler import seg_affine_coeffs
    from doomfj.fixedpoint import fixed_mul
    a, b, c = seg_affine_coeffs(seg, verts)
    if _signed((fixed_mul(a, sp.x, 8, 4) + fixed_mul(b, sp.y, 8, 4) + c) & ANGLE_MASK, 32) <= 0:
        continue
    checked += 1
    s1 = vsector(*verts[seg.v1])
    s2 = vsector(*verts[seg.v2])
    # the seg's conservative sector set: the ccw arc from s2 to s1 (v1 left of v2 on screen);
    # conservatively take both orderings' smaller arc <= 8 sectors
    arc = {s1, s2}
    i = s2
    steps = 0
    while i != s1 and steps < 16:
        i = (i + 1) % 16
        arc.add(i)
        steps += 1
    if steps >= 8:                       # wide arc: fall back (no cull attempt)
        arc = None
    provably_occ = False
    if arc is not None:
        provably_occ = all(
            widths[s] == 0 or counts[s] >= widths[s]
            for s in arc)
        # a sector overlapping the frustum edge partially... widths are clamped so ok
    rng = rm.wall_x_range(sp.x, sp.y, va, seg, verts)
    if rng is None:
        continue
    x1, x2, _ = rng
    x1c, x2c = max(0, x1), min(W, x2)
    fully = all(drawn[x] for x in range(x1c, x2c))
    if fully:
        occ_total += 1
        if provably_occ:
            skipped_atans += 2
    assert not (provably_occ and not fully), "WRONG CULL -- must never happen"
    for x in range(x1c, x2c):
        if not drawn[x]:
            drawn[x] = 1
            for s, (lo, hi) in enumerate(sec_range):
                if lo <= x < hi:
                    counts[s] += 1
                    break

print(f"front-facing segs checked: {checked}")
print(f"occlusion-culled segs: {occ_total} -> provably-occluded (atans skippable): {skipped_atans // 2}")
print(f"atan calls saved: {skipped_atans} of {2 * checked}")
