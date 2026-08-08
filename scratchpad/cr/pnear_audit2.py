"""Find the deg_mark saturation point: 160/192/256 vs unlimited over the sweep grid."""
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
stats = {b: [0, 0] for b in (160, 192, 256)}
for (x, y) in pts:
    for k in range(4):
        st = SimState(x << 16, y << 16, (k << 30) & 0xFFFFFFFF, "E1M1")
        base = bytes(rm.render_wall_frame(st, scene, deg_mark=9999, **kw))
        for b in stats:
            fb = bytes(rm.render_wall_frame(st, scene, deg_mark=b, **kw))
            d = sum(1 for j in range(len(base)) if fb[j] != base[j])
            if d:
                stats[b][0] += 1
                stats[b][1] += d
for b, (f, p) in sorted(stats.items()):
    print(f"deg_mark={b}: {f} frames diverge, {p} px")
