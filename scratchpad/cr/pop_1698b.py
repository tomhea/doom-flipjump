"""Column-level structure of the two frames: run lists (y-range -> palette byte) mid-screen."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
W, H = cfg.VIEW_W, cfg.VIEW_H
VA = 0x20000000

def runs(fb, x):
    col = [fb[y * W + x] for y in range(H)]
    out, s = [], 0
    for y in range(1, H + 1):
        if y == H or col[y] != col[s]:
            out.append((s, y - 1, col[s]))
            s = y
    return out

for tag, (vx, vy) in {"FAR (1698,892) [buggy per owner]": (1698, 892),
                      "NEAR (1715,909) [correct per owner]": (1715, 909)}.items():
    fb = bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                                    wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                    wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                                    things=True, sprite_wad=art, degrade=True))
    print(f"\n=== {tag} ===")
    for x in (70, 75, 80, 85, 90, 93, 100, 105, 108, 112):
        r = runs(fb, x)
        compact = " ".join(f"[{a}-{b}]:{c}" for a, b, c in r[:8])
        print(f"  x={x:3}: {len(r):2} runs  {compact}{' ...' if len(r) > 8 else ''}")
