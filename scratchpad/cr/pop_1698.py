"""Owner's phantom columns: (1698,892) vs (1715,909), both ang=0x20000000.
Render both on the certified oracle config, save side-by-side PNG + a column-diff report."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal(0)
W, H = cfg.VIEW_W, cfg.VIEW_H

VA = 0x20000000
frames = {}
for tag, (vx, vy) in {"far": (1698, 892), "near": (1715, 909)}.items():
    fb = rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                              wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                              wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                              things=True, sprite_wad=art, degrade=True)
    frames[tag] = bytes(fb)

img = Image.new("RGB", (W * 2 + 8, H))
for i, tag in enumerate(("far", "near")):
    t = Image.new("RGB", (W, H))
    t.putdata([pal[b] for b in frames[tag]])
    img.paste(t, (i * (W + 8), 0))
img = img.resize(((W * 2 + 8) * 4, H * 4), Image.NEAREST)
img.save(ROOT / "scratchpad" / "cr" / "pop1698_pair.png")
print("saved scratchpad/cr/pop1698_pair.png  (left=far 1698,892  right=near 1715,909)")

# column report of the FAR frame: for each column, the run structure (top colours)
fb = frames["far"]
runs_per_col = []
for x in range(W):
    col = [fb[y * W + x] for y in range(H)]
    runs = 1
    for y in range(1, H):
        if col[y] != col[y - 1]:
            runs += 1
    runs_per_col.append(runs)
low = [x for x in range(W) if runs_per_col[x] <= 3]
print(f"far frame: columns with <=3 colour runs (suspiciously flat): {len(low)}")
if low:
    # group consecutive
    groups, s = [], low[0]
    for a, b in zip(low, low[1:]):
        if b != a + 1:
            groups.append((s, a)); s = b
    groups.append((s, low[-1]))
    print("  flat column groups:", groups)
