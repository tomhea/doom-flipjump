"""Host counts for the two remaining lines-mode levers at E1M1 spawn:

A. DITTO columns: a claimed column whose (ctake, fstart, cvp, fvp, lit) equal the PREVIOUS
   x (also claimed, same seg) emits one tiny "same as previous" record instead of walking and
   emitting its whole pair list. Rectangles in disguise (widen the previous column's lines by 1).

B. Coarse occlusion pre-cull: could a conservative column bracket (sector-granular, no atan)
   skip the 2 point_to_angle calls of fully-occluded segs?
"""
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
lds = wad.linedefs("E1M1"); sds = wad.sidedefs("E1M1"); secs = wad.sectors("E1M1")
sp = spawn_state(wad, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
H, W = cfg.VIEW_H, cfg.VIEW_W
verts = cmap.vertexes
pss = cmap.subsectors[rm.point_in_subsector(cmap, spx, spy)]
viewz = rm.view_z(rm._seg_sector(lds, sds, secs, cmap.segs[pss.firstseg]).floor_h)

drawn = bytearray(W)
ditto = 0
claims = 0
occ_culled_segs = 0
occ_culled_atans_bracketable = 0

for seg_i in rm.visible_segs(cmap, spx, spy):
    seg = cmap.segs[seg_i]
    if lds[seg.linedef].back != -1:
        continue
    rng = rm.wall_x_range(sp.x, sp.y, sp.angle, seg, verts)
    if rng is None:
        continue
    x1, x2, rwa = rng
    x1c, x2c = max(0, x1), min(W, x2)
    if all(drawn[x] for x in range(x1c, x2c)):
        occ_culled_segs += 1
        continue
    nrm, rwd = rm.wall_setup(sp.x, sp.y, seg, verts)
    scale = rm.scale_from_global_angle((sp.angle + rm.xtoviewangle[x1]) & ANGLE_MASK,
                                       sp.angle, nrm, rwd)
    if x2 > x1:
        s2 = rm.scale_from_global_angle((sp.angle + rm.xtoviewangle[x2]) & ANGLE_MASK,
                                        sp.angle, nrm, rwd)
        d, span = s2 - scale, x2 - x1
        step = -(abs(d) // span) if d < 0 else d // span
    else:
        step = 0
    sec = rm._seg_sector(lds, sds, secs, seg)
    prev = None
    for x in range(x1c, x2c):
        if not drawn[x]:
            top, bottom = rm.wall_screen_span(sec.ceil_h, sec.floor_h, viewz,
                                              (scale + (x - x1) * step) & ANGLE_MASK)
            ctake = min(max(0, top), H)
            fstart = max(bottom + 1, 0)
            claims += 1
            key = (ctake, fstart)
            if prev is not None and prev[0] == x - 1 and prev[1] == key:
                ditto += 1
            prev = (x, key)
            drawn[x] = 1
        else:
            prev = None

print(f"claimed columns: {claims}   DITTO-eligible: {ditto}  ({100*ditto/claims:.0f}%)")
print(f"occlusion-culled segs (post-xrange): {occ_culled_segs}")
