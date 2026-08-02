"""V5 proto sheet: stacked boundary pieces + true regions behind them (oracle, stack_steps=True)
vs the shipped tier. Counts second-piece columns and repainted region pixels for pricing.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image, ImageDraw
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
W, H = cfg.VIEW_W, cfg.VIEW_H
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, aw, "E1M1")
pal = aw.playpal()

sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1272, -724, 1073741824, "stairs (1272,-724)"),
       (1869, 479, 2147483648, "(1869,479,W)"), (1400, 1200, 0, "courtyard"),
       (664, 291, 0x18000000, "corridor")]


def render(stack):
    def f(vx, vy, va):
        st = SimState(vx << 16, vy << 16, va, "E1M1")
        return bytearray(rm.render_wall_frame(
            st, scene, wall_mode="W1R", floor_mode_ft1=True, plane_near=True,
            wall_noise=True, sky=True, near_steps=True, things=True,
            sprite_wad=art, bbox_cull=True, stack_steps=stack))
    return f


ROWS = [("shipped (V3 K=1, no regions)", render(False)),
        ("V5: stacked pieces + true regions behind boundaries", render(True))]
S = 3
sheet = Image.new("RGB", (W * S * len(VPS), (H * S + 22) * len(ROWS)), (14, 14, 16))
d = ImageDraw.Draw(sheet)
for r, (lab, f) in enumerate(ROWS):
    for c, (vx, vy, va, tag) in enumerate(VPS):
        fb = f(vx, vy, va)
        im = Image.new("RGB", (W, H))
        im.putdata([pal[p] for p in fb])
        sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (c * W * S, r * (H * S + 22) + 22))
        if r == 1:
            base = ROWS[0][1](vx, vy, va)
            diff = sum(1 for a, b in zip(base, fb) if a != b)
            print(f"{tag:20s} V5 changes {diff:,} px", flush=True)
    d.text((6, r * (H * S + 22) + 5), lab, fill=(235, 235, 240))
for c, (_, _, _, tag) in enumerate(VPS):
    d.text((c * W * S + 6, 12), tag, fill=(180, 200, 180))
sheet.save(ROOT / "scratchpad/v5_proto.png")
print("scratchpad/v5_proto.png written")
