"""V4 — does the THINGS oracle render, and what does it cost?

Renders WITHOUT / WITH at three viewpoints and writes a PNG strip, plus the populations the fj
price depends on: things projected (vs THING_BUDGET), columns carrying a fragment, and the emit
PAIR delta -- the only unit the 0x0B protocol actually charges for (~330 ops each).
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from PIL import Image
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (SPRITE_HEIGHT_BUCKETS, THING_BUDGET, THING_SPRITE,
                                    ReferenceModel, SimState, build_scene, spawn_state)
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
scene = build_scene(mw, mw, "E1M1")
pal = mw.playpal()
W, H = cfg.VIEW_W, cfg.VIEW_H
sp = spawn_state(mw, "E1M1")
sx, sy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(sx, sy, sp.angle, "spawn"), (1400, 1200, 0, "courtyard"),
       (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]

KW = dict(wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True, sky=True,
          near_steps=True)


def pairs(fb):
    """[y2][colour] pairs the frame costs, and how many columns ditto (copy their left neighbour)."""
    n = d = 0
    for x in range(W):
        if x and all(fb[y * W + x] == fb[y * W + x - 1] for y in range(H)):
            d += 1
            continue
        prev = None
        for y in range(H):
            c = fb[y * W + x]
            if c != prev:
                n += 1
                prev = c
    return n, d


tiles = []
print(f"THING_BUDGET={THING_BUDGET}  SPRITE_HEIGHT_BUCKETS={SPRITE_HEIGHT_BUCKETS}  "
      f"sprite types mapped={len(THING_SPRITE)}")
for vx, vy, va, tag in VPS:
    st = SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1")
    a = rm.render_wall_frame(st, scene, **KW)
    b = rm.render_wall_frame(st, scene, **KW, things=True, sprite_wad=art)
    npx = sum(1 for i in range(len(a)) if a[i] != b[i])
    cols = len({i % W for i in range(len(a)) if a[i] != b[i]})
    pa, da = pairs(a)
    pb, db = pairs(b)
    print(f"{tag:10s} ({vx:5d},{vy:5d}): {npx:5d} px change in {cols:3d} columns   "
          f"pairs {pa:5d} -> {pb:5d} ({pb - pa:+5d})   ditto {da:3d} -> {db:3d} ({db - da:+d})   "
          f"emit {(pb - pa) * 330 / 1e6:+.2f}M")
    for f in (a, b):
        im = Image.new("RGB", (W, H))
        im.putdata([pal[p] for p in f])
        tiles.append(im)

s = 3
sheet = Image.new("RGB", (W * 2 * s + 12, len(VPS) * H * s + (len(VPS) - 1) * 6), (20, 20, 24))
for i, im in enumerate(tiles):
    r, c = divmod(i, 2)
    sheet.paste(im.resize((W * s, H * s), Image.NEAREST), (c * (W * s + 12), r * (H * s + 6)))
out = ROOT / "scratchpad/v4_things.png"
sheet.save(out)
print("wrote", out)
