"""W1R-FACES proto: textured step faces (oracle) -- look + pair pricing.

Renders W1 (flat faces, flat walls) / W1R shipped (textured walls, FLAT faces -- reproduced by
painting faces the old way) / W1R+faces (this proto) and counts colour-change pairs.
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
VPS = [(sx, sy, sp.angle, "spawn"), (1272, -724, 1073741824, "(1272,-724)"),
       (1869, 479, 2147483648, "(1869,479,W)"), (1400, 1200, 0, "courtyard")]


def render(mode):
    def f(vx, vy, va):
        st = SimState(vx << 16, vy << 16, va, "E1M1")
        return bytearray(rm.render_wall_frame(
            st, scene, wall_mode=mode, floor_mode_ft1=True, plane_near=True,
            wall_noise=True, sky=True, near_steps=True, things=True,
            sprite_wad=art, bbox_cull=True))
    return f


def count_pairs(fb):
    n = 0
    for x in range(W):
        prev = None
        for y in range(H):
            c = fb[y * W + x]
            if c != prev:
                n += 1
                prev = fb[y * W + x]
    return n


ROWS = [("W1 (flat everything)", render("W1")), ("W1R + textured faces (proto)", render("W1R"))]
S = 3
sheet = Image.new("RGB", (W * S * len(VPS), (H * S + 22) * len(ROWS)), (14, 14, 16))
d = ImageDraw.Draw(sheet)
for r, (lab, f) in enumerate(ROWS):
    tot = 0
    for c, (vx, vy, va, tag) in enumerate(VPS):
        fb = f(vx, vy, va)
        pairs = count_pairs(fb)
        tot += pairs
        im = Image.new("RGB", (W, H))
        im.putdata([pal[p] for p in fb])
        sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (c * W * S, r * (H * S + 22) + 22))
        print(f"{lab:30s} {tag:14s} pairs {pairs}")
    d.text((6, r * (H * S + 22) + 5), f"{lab}   pairs avg {tot // len(VPS)}", fill=(235, 235, 240))
for c, (_, _, _, tag) in enumerate(VPS):
    d.text((c * W * S + 6, 12), tag, fill=(180, 200, 180))
sheet.save(ROOT / "scratchpad/w1r_faces_proto.png")
print("scratchpad/w1r_faces_proto.png written")
