"""20M-recovery option sheets: shipped baseline (left) vs option (right) on four frames.

    python scratchpad/opt20_sheet.py S1|S1H|K1|K2
"""
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

OPT = sys.argv[1]
# the shipped state has DEG_SPR_LOWRES_H=16 in source already -- the BASELINE for the sheets
# is the pre-recovery look, so baseline pins it OFF (H=0) and each option turns levers on.
BASE = dict(DEG_SPR_LOWRES_H=0)
KNOBS = {
    "S1": dict(DEG_SPR_LOWRES_H=16, DEG_SPR_LOWRES_CAP=3),
    "S1H": dict(DEG_SPR_LOWRES_H=24, DEG_SPR_LOWRES_CAP=2),
    "K1": dict(DEG_SPR_LOWRES_H=16, DEG_SPR_LOWRES_CAP=3, DEG_SOFT_SCENERY=6,
               DEG_MINH2_SCENERY=14, STEP_SEG_BUDGET=10, DEG_SLIVER_W=3, DEG_PNEAR=80),
    "K2": dict(DEG_SPR_LOWRES_H=16, DEG_SPR_LOWRES_CAP=3, DEG_SOFT_SCENERY=4,
               DEG_MINH2_SCENERY=20, DEG_SOFT_MON=4, DEG_MINH2_MON=10,
               STEP_SEG_BUDGET=8, DEG_SLIVER_W=3, DEG_PNEAR=64),
}[OPT]

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
saved = {k: getattr(RM, k) for k in set(BASE) | set(KNOBS)}
for i, (vx, vy, va, tag) in enumerate(VPS):
    for k in saved:
        setattr(RM, k, BASE.get(k, saved[k]))
    base_fb = render(vx, vy, va)
    for k in saved:
        setattr(RM, k, KNOBS.get(k, saved[k] if k not in BASE else BASE[k]))
    for k, v in KNOBS.items():
        setattr(RM, k, v)
    opt_fb = render(vx, vy, va)
    for j, fb in enumerate((base_fb, opt_fb)):
        im = Image.new("RGB", (W, H))
        im.putdata([pal[b] for b in fb])
        sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (8 + j * (W * S + 8),
                                                               8 + i * (H * S + 10)))
    d = sum(1 for a, b in zip(base_fb, opt_fb) if a != b)
    print(f"{tag}: px-diff {d}", flush=True)
for k, v in saved.items():
    setattr(RM, k, v)
outp = ROOT / "scratchpad" / f"opt20_{OPT}_sheet.png"
sheet.save(outp)
print(f"ok {outp}")
