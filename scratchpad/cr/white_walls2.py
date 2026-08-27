"""Second candidate: walls whose TWO W1R colour bytes bake EQUAL (pattern contrast collapses)."""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, COLORMAP_LIGHTS, LIGHT_SHIFT
from doomfj.texturecompiler import colormap_values
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
scene = build_scene(mw, aw, "E1M1")
lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
colormap = aw.colormap()
cache = {}

eq = Counter()      # (texture, light) of walls whose two baked bytes are EQUAL
neq = 0
pal = aw.playpal(0)
seen_rgb = {}
for si, seg in enumerate(scene.cmap.segs):
    ld = lds[seg.linedef]
    if ld.back != -1 and ld.front != -1:
        continue
    front = ld.front if seg.side == 0 else ld.back
    if front == -1:
        continue
    sd = sds[front]
    sec = secs[sd.sector]
    t = rm._wall_texture(aw, sd.middle, cache, wall_mode="W1R")
    if t is None or sd.middle.upper().startswith("SKY"):
        continue
    texels, th, tw = t
    row = max(0, min(COLORMAP_LIGHTS - 1, sec.light >> LIGHT_SHIFT))
    row = max(0, row - rm.W1R_BASE_BRIGHTEN)
    b1, b2 = colormap[row][texels[0]], colormap[row][texels[1]]
    if b1 == b2:
        eq[(sd.middle.upper(), sec.light)] += 1
        seen_rgb[(sd.middle.upper(), sec.light)] = (b1, pal[b1])
    else:
        neq += 1

print(f"contrast-COLLAPSED walls (both W1R bytes equal): {sum(eq.values())} segs "
      f"vs {neq} with contrast")
for (nm, l), c in eq.most_common(15):
    b, rgb = seen_rgb[(nm, l)]
    print(f"  {nm} light={l}: {c} segs -> byte {b} rgb {rgb}")
