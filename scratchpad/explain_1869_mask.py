"""Color-coded pixel attribution for (1869,479,W): which FEATURE owns each pixel?

wall (sentinel trick) = red | floor/ceiling bands (flat sentinel) = green | sprites = blue
| step faces = yellow | sky = cyan. Overlaid next to the real frame.
"""
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
VX, VY, VA = 1869, 479, 2147483648


def render(mode="W1R", things=True, steps=True, sky=True):
    st = SimState(VX << 16, VY << 16, VA, "E1M1")
    return bytearray(rm.render_wall_frame(
        st, scene, wall_mode=mode, floor_mode_ft1=True, plane_near=True,
        wall_noise=True, sky=sky, near_steps=steps, things=things,
        sprite_wad=art if things else None, bbox_cull=True))


full = render()

# wall mask: sentinel the wall texture twice (explain_view.py's exact-mask trick)
_orig = ReferenceModel._wall_texture
masks = []
for val in (4, 200):
    ReferenceModel._wall_texture = (lambda v: (lambda self, aw_, nm, cache, *, wall_mode="textured":
                                               ([v], 1, 1)))(val)
    masks.append(render())
ReferenceModel._wall_texture = _orig
wall = [a != b for a, b in zip(*masks)]

# plane mask: sentinel the flat base twice
_origf = ReferenceModel._flat_base
pmasks = []
for val in (4, 200):
    ReferenceModel._flat_base = (lambda v: (lambda self, aw_, nm, cache: v))(val)
    pmasks.append(render())
ReferenceModel._flat_base = _origf
plane = [a != b for a, b in zip(*pmasks)]

spr = [a != b for a, b in zip(full, render(things=False))]
stp = [a != b for a, b in zip(full, render(steps=False))]
sky = [a != b for a, b in zip(full, render(sky=False))]

print(f"wall {sum(wall):,} | planes {sum(plane):,} | sprites {sum(spr):,} "
      f"| steps {sum(stp):,} | sky {sum(sky):,}  of {W*H:,}")

att = Image.new("RGB", (W, H))
px = []
for i in range(W * H):
    if spr[i]:
        px.append((60, 90, 255))       # sprite -> blue
    elif stp[i]:
        px.append((255, 220, 40))      # step face -> yellow
    elif sky[i]:
        px.append((40, 220, 220))      # sky -> cyan
    elif wall[i]:
        px.append((230, 60, 60))       # wall -> red
    elif plane[i]:
        px.append((60, 200, 60))       # floor/ceiling band -> green
    else:
        px.append((30, 30, 30))
att.putdata(px)

im = Image.new("RGB", (W, H))
im.putdata([pal[p] for p in full])
S = 4
sheet = Image.new("RGB", (W * S * 2, H * S + 22), (14, 14, 16))
d = ImageDraw.Draw(sheet)
sheet.paste(im.resize((W * S, H * S), Image.NEAREST), (0, 22))
sheet.paste(att.resize((W * S, H * S), Image.NEAREST), (W * S, 22))
d.text((6, 5), "the frame (W1R)", fill=(235, 235, 240))
d.text((W * S + 6, 5),
       "who owns each pixel: red=wall  green=floor/ceiling band  blue=sprite  yellow=step face  cyan=sky",
       fill=(235, 235, 240))
sheet.save(ROOT / "scratchpad/explain_1869_mask.png")
print("scratchpad/explain_1869_mask.png written")
