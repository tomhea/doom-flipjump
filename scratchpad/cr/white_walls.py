"""Which walls draw as the FLAT (patternless) tier and why -- texture-less (WALL_BG) vs sky."""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, build_scene, WALL_BG
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/e1m1_lite.wad"))
aw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
scene = build_scene(mw, aw, "E1M1")
lds, sds = mw.linedefs("E1M1"), mw.sidedefs("E1M1")
cache = {}

no_tex = Counter()          # middle-texture NAME of walls that resolve to no texture
sky_tex = Counter()
examples = {}
total = 0
for si, seg in enumerate(scene.cmap.segs):
    ld = lds[seg.linedef]
    front = ld.front if seg.side == 0 else ld.back
    if front == -1:
        continue
    sd = sds[front]
    if ld.back != -1 and (ld.front == -1 or True):
        # two-sided segs draw no middle wall on the shipped tier; only one-sided walls matter
        if ld.back != -1 and ld.front != -1:
            continue
    total += 1
    t = rm._wall_texture(aw, sd.middle, cache, wall_mode="W1R")
    nm = (sd.middle or "-").upper()
    if t is None:
        no_tex[nm] += 1
        examples.setdefault(("notex", nm),
                            (scene.cmap.vertexes[seg.v1], scene.cmap.vertexes[seg.v2]))
    elif nm.startswith("SKY"):
        sky_tex[nm] += 1
        examples.setdefault(("sky", nm),
                            (scene.cmap.vertexes[seg.v1], scene.cmap.vertexes[seg.v2]))

print(f"one-sided walk segs: {total}")
print(f"\nTEXTURE-LESS (flat WALL_BG={WALL_BG}) segs: {sum(no_tex.values())}")
for nm, c in no_tex.most_common():
    print(f"  middle={nm!r}: {c} segs   e.g. {examples[('notex', nm)]}")
print(f"\nSKY-textured (flat by W1R-FLAT design) segs: {sum(sky_tex.values())}")
for nm, c in sky_tex.most_common():
    print(f"  middle={nm!r}: {c} segs   e.g. {examples[('sky', nm)]}")

# the final baked colour of a flat wall at a few light levels
cm = aw.colormap()
pal = aw.playpal(0)
for light in (255, 192, 160, 128):
    row = max(0, min(31, light >> 3))
    c = cm[row][WALL_BG]
    print(f"light {light}: colormap row {row} -> palette idx {c} rgb {pal[c]}")
