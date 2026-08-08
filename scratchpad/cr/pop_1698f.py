"""Dump ups[x]/los[x] piece lists at the phantom columns, both frames."""
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
VA = 0x20000000

for tag, (vx, vy) in {"FAR": (1698, 892), "NEAR": (1715, 909)}.items():
    steps = []
    rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                         wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                         wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                         things=True, sprite_wad=art, degrade=True, steps_out=steps)
    ups, los = steps[0]
    print(f"\n=== {tag} ({vx},{vy}) ===")
    for x in (73, 75, 80, 90, 93, 100, 105, 108, 112):
        def fmt(lst):
            return " | ".join(
                f"y[{e[0]},{e[1]}] lt={e[2].light} fh={getattr(e[4], 'floor_h', '?')}"
                f"/ch={getattr(e[4], 'ceil_h', '?')} bf={getattr(e[4], 'floor_tex', '?')}"
                for e in lst) or "-"
        print(f"  x={x:3}: UP {fmt(ups[x])}")
        print(f"         LO {fmt(los[x])}")
