"""Attribute the phantom paint: dump steps_out (face/stacked pieces) + planes_out (per-column
plane records) for the FAR frame at the suspicious columns."""
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
WATCH = set(range(96, 114)) | set(range(73, 96))

for tag, (vx, vy) in {"FAR": (1698, 892), "NEAR": (1715, 909)}.items():
    steps, planes = [], []
    rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                         wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                         things=True, sprite_wad=art, degrade=True,
                         steps_out=steps, planes_out=planes)
    print(f"\n=== {tag} ({vx},{vy}) ===")
    print("steps_out entries:", len(steps))
    for e in steps:
        # entry format unknown -- print raw, filtered to watch columns when x present
        s = repr(e)
        if any(f"({x}," in s or f" {x}," in s for x in (75, 100, 108)):
            print("  ", s[:220])
    if steps and len(steps) < 30:
        for e in steps:
            print("  ALL:", repr(e)[:220])
    if planes:
        print("planes_out sample (x=75,100,108):")
        pl = planes[0] if isinstance(planes[0], (list, tuple)) and len(planes) == 1 else planes
        try:
            for x in (75, 100, 108):
                print(f"  x={x}:", repr(pl[x])[:200])
        except Exception as ex:
            print("  planes format:", type(pl), len(pl), repr(pl[:2])[:300], ex)
