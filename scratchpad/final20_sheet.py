"""The SHIPPED 20M-recovery look vs the pre-recovery look, four frames."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image
from doomfj.config import Config
import doomfj.reference_model as RM
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

# the PRE-recovery constants (the 22.78M/22.41M state) -- the sheet's left column
PRE = dict(DEG_SOFT_SCENERY=8, DEG_MINH2_SCENERY=12, DEG_SOFT_MON=8, DEG_MINH2_MON=6,
           STEP_SEG_BUDGET=12, DEG_SLIVER_W=2, DEG_PNEAR=96, DEG_SPR_LOWRES_H=0,
           DEG_SPR_MID_CAP=12, DEG_STACK_SCALE=16384)

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal()

VPS = [(1613, 1503, 0x80000000, "far-strips"),
       (1869, 479, 0x80000000, "crowd"),
       (1101, -545, 0xc0000000, "stairs"),
       (1453, 1450, 0xc0000000, "pool-bank")]


def render(vx, vy, va):
    return rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                                scene, wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, sky=True, near_steps=True, things=True,
                                sprite_wad=art, bbox_cull=True, stack_steps=True, degrade=True)


S = 3
sheet = Image.new("RGB", ((W * S + 8) * 2 + 8, (H * S + 10) * len(VPS) + 8), (24, 24, 24))
shipped = {k: getattr(RM, k) for k in PRE}
for i, (vx, vy, va, tag) in enumerate(VPS):
    for k, v in PRE.items():
        setattr(RM, k, v)
    pre_fb = render(vx, vy, va)
    for k, v in shipped.items():
        setattr(RM, k, v)
    new_fb = render(vx, vy, va)
    for j, fb in enumerate((pre_fb, new_fb)):
        im = Image.new("RGB", (W, H))
        im.putdata([pal[b] for b in fb])
        sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (8 + j * (W * S + 8),
                                                               8 + i * (H * S + 10)))
    d = sum(1 for a, b in zip(pre_fb, new_fb) if a != b)
    print(f"{tag}: px-diff {d}", flush=True)
sheet.save(ROOT / "scratchpad" / "final20_sheet.png")
print("ok")
