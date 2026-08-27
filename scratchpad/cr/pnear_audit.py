"""Sweep-wide attribution audit (oracle-side): render the 260-frame grid at deg_mark 64 /
96 / 128 vs UNLIMITED; report frames + pixels diverging per budget. Finds every frame that
suffers the (1698,892) phantom class."""
import sys
import time
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

gw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
verts = [(v.x, v.y) for v in gw.vertexes("E1M1")]
lds, sds = gw.linedefs("E1M1"), gw.sidedefs("E1M1")
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
print(f"{len(pts)} grid points x 4 angles")

BUDGETS = (64, 96, 128)
stats = {b: [0, 0, []] for b in BUDGETS}      # bad frames, bad px, worst list
t0 = time.time()
n = 0
for i, (x, y) in enumerate(pts):
    for k in range(4):
        va = (k << 30) & 0xFFFFFFFF
        st = SimState(x << 16, y << 16, va, "E1M1")
        kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                  near_steps=True, stack_steps=True, sky=True, things=True,
                  sprite_wad=art, degrade=True)
        base = bytes(rm.render_wall_frame(st, scene, deg_mark=9999, **kw))
        for b in BUDGETS:
            fb = bytes(rm.render_wall_frame(st, scene, deg_mark=b, **kw))
            d = sum(1 for j in range(len(base)) if fb[j] != base[j])
            if d:
                stats[b][0] += 1
                stats[b][1] += d
                stats[b][2].append((d, x, y, va))
        n += 1
    if (i + 1) % 10 == 0:
        el = time.time() - t0
        print(f"  {n} frames, {el:.0f}s", flush=True)

print(f"\n=== attribution divergence vs unlimited ({n} frames) ===")
for b in BUDGETS:
    bad, px, lst = stats[b]
    lst.sort(reverse=True)
    print(f"deg_mark={b:4}: {bad} frames diverge, {px} px total")
    for d, x, y, va in lst[:6]:
        print(f"    {d:6} px @ ({x},{y},{hex(va)})")
