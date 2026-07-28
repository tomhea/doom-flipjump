"""Host count for the planned raster_mode="lines": how many fillCol records does the E1M1 spawn
frame emit, and what is the projected ops budget?

Per claimed column: 1 wall record + one record per distance-light band intersecting the ceiling
prefix [0, ctake) and the floor suffix [fstart, H). Band lists are per-visplane (crush2b shared
full-range walks), sliced per column.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile

cfg = Config()
wad = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
rm = ReferenceModel(cfg)
scene = build_scene(wad, wad, "E1M1")
sp = spawn_state(wad, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

# Reuse the oracle's own plane machinery: render the frame, capturing the per-column regions the
# planes pass consumes (ceil_hi / floor_lo) plus each column's visplane key.
lds = wad.linedefs("E1M1")
sds = wad.sidedefs("E1M1")
secs = wad.sectors("E1M1")

H, W = cfg.VIEW_H, cfg.VIEW_W

# replicate render_wall_frame's pass-1 to get per-column ceil_hi/floor_lo + vp keys
verts = scene.cmap.vertexes
state = SimState(sp.x, sp.y, sp.angle, "E1M1")
viewx, viewy, viewangle = state.x, state.y, state.angle
pss = scene.cmap.subsectors[rm.point_in_subsector(scene.cmap, spx, spy)]
viewz = rm.view_z(rm._seg_sector(lds, sds, secs, scene.cmap.segs[pss.firstseg]).floor_h)

drawn = bytearray(W)
ceil_hi = [-1] * W
floor_lo = [H] * W
col_key = [None] * W        # (ph_ceil, ph_floor, light) per column -- for band-count purposes
from doomfj.reference_model import ANGLE_MASK

wall_records = 0
for seg_i in rm.visible_segs(scene.cmap, spx, spy):
    seg = scene.cmap.segs[seg_i]
    ld = lds[seg.linedef]
    if ld.back != -1:
        continue
    rng = rm.wall_x_range(viewx, viewy, viewangle, seg, verts)
    if rng is None:
        continue
    x1, x2, rw_angle1 = rng
    rw_normalangle, rw_distance = rm.wall_setup(viewx, viewy, seg, verts)
    scale = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x1]) & ANGLE_MASK,
                                       viewangle, rw_normalangle, rw_distance)
    if x2 > x1:
        scale2 = rm.scale_from_global_angle((viewangle + rm.xtoviewangle[x2]) & ANGLE_MASK,
                                            viewangle, rw_normalangle, rw_distance)
        diff, span = scale2 - scale, x2 - x1
        scalestep = -(abs(diff) // span) if diff < 0 else diff // span
    else:
        scalestep = 0
    sec = rm._seg_sector(lds, sds, secs, seg)
    for x in range(x1, x2):
        if 0 <= x < W and not drawn[x]:
            top, bottom = rm.wall_screen_span(sec.ceil_h, sec.floor_h, viewz, scale & ANGLE_MASK)
            top = max(0, top)
            bottom = min(H - 1, bottom)
            if top <= bottom:
                wall_records += 1
            ceil_hi[x] = min(top, H) - 1
            floor_lo[x] = max(bottom + 1, 0)
            vz = _signed(viewz, 32)
            col_key[x] = (abs((sec.ceil_h << 16) - vz), abs((sec.floor_h << 16) - vz), sec.light)
            drawn[x] = 1
        scale = (scale + scalestep) & ANGLE_MASK

# band lists per distinct (ph, light): the shared full-range walk
def band_rows(ph, light):
    rows = rm._zidx_band_walk(ph, light, 0, H, True) if hasattr(rm, "_zidx_band_walk") else None
    return rows

# count band records: per column, number of DISTINCT zrow runs intersecting the prefix/suffix
from collections import defaultdict
walks = {}
def full_walk(ph, light):
    """full-range per-row zidx -> grouped (count, zrow) runs, zrow via the zlight table."""
    if (ph, light) not in walks:
        zidx = rm._zidx_band_walk(ph, list(range(H)))
        lvl = max(0, min(15, light >> 4))
        zrows = [rm.zlight[lvl][z] for z in zidx]
        runs = []
        for zr in zrows:
            if runs and runs[-1][1] == zr:
                runs[-1][0] += 1
            else:
                runs.append([1, zr])
        walks[(ph, light)] = runs
    return walks[(ph, light)]

def runs_in(walk, y_lo, y_hi):
    """number of runs of `walk` (list of (rows..) runs starting at row 0) intersecting [y_lo, y_hi)"""
    n, y = 0, 0
    for entry in walk:
        cnt = entry[0]
        lo, hi = y, y + cnt
        if hi > y_lo and lo < y_hi:
            n += 1
        y = hi
        if y >= y_hi:
            break
    return n

ceil_records = floor_records = 0
for x in range(W):
    if col_key[x] is None:
        continue
    phc, phf, light = col_key[x]
    ctake = min(ceil_hi[x] + 1, floor_lo[x])
    if ctake > 0:
        ceil_records += runs_in(full_walk(phc, light), 0, ctake)
    if floor_lo[x] < H:
        floor_records += runs_in(full_walk(phf, light), floor_lo[x], H)

total = wall_records + ceil_records + floor_records
print(f"claimed columns: {sum(drawn)}")
print(f"wall records:  {wall_records}")
print(f"ceil records:  {ceil_records}")
print(f"floor records: {floor_records}")
print(f"TOTAL fillCol records: {total}  x 4 bytes = {4*total} emitted bytes")
print(f"emit budget @ ~1.15k/record + ~2.5k glue: {total * 3.6e3 / 1e6:.1f}M")
print(f"distinct visplane walks built: {len(walks)}")
