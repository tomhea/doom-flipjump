"""The owner's popping walk: (1210,1187) ang=0xf8000000, then +1 step, then +2 more.
Render all four frames + diff counts + test whether the LIP far gate causes the green pop."""
import math
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

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal()

ANG = 0xf8000000
rad = ANG / 2**32 * 2 * math.pi
dx, dy = round(math.cos(rad) * 24), round(math.sin(rad) * 24)
P = [(1210, 1187)]
for _ in range(3):
    P.append((P[-1][0] + dx, P[-1][1] + dy))
print(f"step vector ({dx},{dy}); path {P}")


def render(vx, vy):
    return rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=ANG, level="E1M1"),
                                scene, wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
                                wall_noise=True, sky=True, near_steps=True, things=True,
                                sprite_wad=art, bbox_cull=True, stack_steps=True, degrade=True)


S = 3
sheet = Image.new("RGB", ((W * S + 8) * 4 + 8, (H * S + 10) * 2 + 8), (24, 24, 24))
prev = None
frames = []
for j, (vx, vy) in enumerate(P):
    fb = render(vx, vy)
    frames.append(fb)
    im = Image.new("RGB", (W, H))
    im.putdata([pal[b] for b in fb])
    sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (8 + j * (W * S + 8), 8))
    if prev is not None:
        d = sum(1 for a, b in zip(prev, fb) if a != b)
        print(f"step {j}: ({vx},{vy}) px-diff vs prev {d}")
    prev = fb

# second row: the same path with the LIP FAR GATE OFF (deg_lip_scale huge->0 disables gating)
_orig_lip_scale = RM.DEG_LIP_SCALE
RM.DEG_LIP_SCALE = 0
for j, (vx, vy) in enumerate(P):
    fb = render(vx, vy)
    im = Image.new("RGB", (W, H))
    im.putdata([pal[b] for b in fb])
    sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (8 + j * (W * S + 8),
                                                           8 + (H * S + 10)))
    d = sum(1 for a, b in zip(frames[j], fb) if a != b)
    print(f"step {j} gate-off px-diff vs gated {d}")
RM.DEG_LIP_SCALE = _orig_lip_scale
sheet.save(ROOT / "scratchpad" / "pop_probe.png")
print("ok")
