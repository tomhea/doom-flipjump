"""Final attribution check: shipped defaults (DEG_PNEAR=1024 + piece-seg idle stop) vs
unlimited -- must be 0 px over the whole sweep grid."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile
from nb_validate import true_sector, _near_any_line

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
verts = [(v.x, v.y) for v in aw.vertexes("E1M1")]
lds, sds = aw.linedefs("E1M1"), aw.sidedefs("E1M1")
xs = [v[0] for v in verts]
ys = [v[1] for v in verts]
pts = []
for x in range(min(xs) + 13, max(xs), 256):
    for y in range(min(ys) + 7, max(ys), 256):
        if _near_any_line(verts, lds, x, y, 24.0):
            continue
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))

kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
          near_steps=True, stack_steps=True, sky=True, things=True,
          sprite_wad=art, degrade=True)
bad_f = bad_px = 0
n = 0
for (x, y) in pts:
    for k in range(4):
        st = SimState(x << 16, y << 16, (k << 30) & 0xFFFFFFFF, "E1M1")
        a = bytes(rm.render_wall_frame(st, scene, **kw))                 # shipped defaults
        b = bytes(rm.render_wall_frame(st, scene, deg_mark=9999, **kw))  # unlimited
        d = sum(1 for j in range(len(a)) if a[j] != b[j])
        if d:
            bad_f += 1
            bad_px += d
            print(f"  DIVERGES {d} px @ ({x},{y},{hex((k << 30) & 0xFFFFFFFF)})")
        n += 1
print(f"{n} frames: {bad_f} diverge ({bad_px} px) -- expect 0")
