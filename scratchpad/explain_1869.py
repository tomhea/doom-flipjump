"""What is on screen at (1869,479,W) -- the worst 'everything-at-once' frame?

Attributes each region by feature ablation (things / steps off) and lists the map objects
near the eye, then writes a labeled strip: full | no-things | no-steps | flat-W1.
"""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image, ImageDraw
from doomfj.config import Config
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
VX, VY, VA = 1869, 479, 2147483648   # looking WEST

# -- what's physically near the eye?
print("things within 400 units:")
for t in mw.things("E1M1"):
    d = math.hypot(t.x - VX, t.y - VY)
    if d < 400:
        print(f"  type {t.type:5d} at ({t.x},{t.y})  dist {d:.0f}")

lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
verts = [(v.x, v.y) for v in mw.vertexes("E1M1")]
print("one-sided walls within 300 units (their middle texture):")
for ld in lds:
    if ld.back != -1:
        continue
    (x1, y1), (x2, y2) = verts[ld.v1], verts[ld.v2]
    mxx, mxy = (x1 + x2) / 2, (y1 + y2) / 2
    d = math.hypot(mxx - VX, mxy - VY)
    if d < 300:
        sd = sds[ld.front]
        sec = secs[sd.sector]
        print(f"  ({x1},{y1})-({x2},{y2})  dist {d:.0f}  tex {sd.middle!r} "
              f"light {sec.light} ceil {sec.ceil_h} floor {sec.floor_h}")


def render(mode="W1R", things=True, steps=True, sky=True):
    st = SimState(VX << 16, VY << 16, VA, "E1M1")
    return bytearray(rm.render_wall_frame(
        st, scene, wall_mode=mode, floor_mode_ft1=True, plane_near=True,
        wall_noise=True, sky=sky, near_steps=steps, things=things,
        sprite_wad=art if things else None, bbox_cull=True))


variants = [("full W1R", render()),
            ("V4 things OFF", render(things=False)),
            ("V3 steps OFF", render(steps=False)),
            ("flat W1", render(mode="W1"))]
S = 4
sheet = Image.new("RGB", (W * S * len(variants), H * S + 22), (14, 14, 16))
d = ImageDraw.Draw(sheet)
for c, (lab, fb) in enumerate(variants):
    im = Image.new("RGB", (W, H))
    im.putdata([pal[p] for p in fb])
    sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (c * W * S, 22))
    d.text((c * W * S + 6, 5), lab, fill=(235, 235, 240))
    # difference count vs full frame
    if c:
        diff = sum(1 for a, b in zip(variants[0][1], fb) if a != b)
        print(f"{lab}: {diff:,} px differ from the full frame")
sheet.save(ROOT / "scratchpad/explain_1869.png")
print("scratchpad/explain_1869.png written")
