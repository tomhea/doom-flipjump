"""Hypothesis test: does a bigger marking budget fix the FAR frame? Render FAR with
deg_mark 64 (shipped) / 96 / 128 / 9999 and diff columns 96-114."""
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
vx, vy = 1698, 892

frames = {}
for dm in (64, 96, 128, 9999):
    planes = []
    fb = rm.render_wall_frame(SimState(vx << 16, vy << 16, VA, "E1M1"), scene,
                              wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                              wall_noise=True, near_steps=True, stack_steps=True, sky=True,
                              things=True, sprite_wad=art, degrade=True, deg_mark=dm,
                              planes_out=planes)
    frames[dm] = bytes(fb)
    pl = planes[0]
    fh100, ff100 = pl[3][100], pl[6][100]
    fh108, ff108 = pl[3][108], pl[6][108]
    print(f"deg_mark={dm:5}: x=100 fh={fh100} ff={ff100} | x=108 fh={fh108} ff={ff108}")

base = frames[9999]
for dm in (64, 96, 128):
    d = sum(1 for i in range(W * H) if frames[dm][i] != base[i])
    print(f"deg_mark={dm:5}: {d} px differ vs unlimited")
