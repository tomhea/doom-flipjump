"""A PNG of what the SHIPPED program draws -- proof by picture, not by op count.

Every gate in this repo compares bytes; none of them ever shows you the frame. This runs the same
binary `scripts/walk_e1m1.py` plays, on the same binary wire (sim on), and writes a PNG. It takes
KEYS, so it can also show the world one tic AFTER a move -- i.e. that the program simulated.

    python scratchpad/shot.py <fjm> [--out shot.png] [--keys 0] [--tics 0] [--wad ...]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image                                                     # noqa: E402

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--out", default="scratchpad/shot.png")
ap.add_argument("--keys", type=int, default=0)
ap.add_argument("--tics", type=int, default=0, help="run N tics with --keys before the shot")
ap.add_argument("--wad", default="tests/fixtures/e1m1_lite.wad")
ap.add_argument("--art", default="assets/freedoom1.wad")
ap.add_argument("--map", default="E1M1")
ap.add_argument("--scale", type=int, default=4)
args = ap.parse_args()

cfg = Config()
mw = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / args.art))
rm = ReferenceModel(cfg)
cmap = bake_bsp(mw, args.map)
drawable = [t for t in mw.things(args.map) if rm.sprite_art(art, t.type, {}) is not None]
baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
rt = [t for t, b in zip(drawable, baked) if not b]
POS = encode_things([(t.x << 16, t.y << 16) for t in rt])
VIS = encode_visibility([1] * nvis)
binds = [rm.point_in_subsector(cmap, t.x, t.y) for t in rt]

sp = spawn_state(mw, args.map)
st = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
r = FjmRunner(ROOT / args.fjm)
print(f"{Path(args.fjm).name}: native={r.native}, {len(rt)} runtime things", flush=True)

scr = None
for tic in range(args.tics + 1):
    keys = args.keys if tic < args.tics else 0        # the SHOT itself is a still frame
    scr = StreamScreen(stdin=encode_feed(st[0], st[1], st[2], keys) + POS
                       + encode_bindings(binds) + VIS, n_things=len(rt))
    ops = r.run(scr)
    st = scr.state
    if scr.bindings:
        binds = list(scr.bindings)
    print(f"  tic {tic}: keys={keys:04b} {ops:,} ops -> "
          f"({st[0] / 65536:.3f},{st[1] / 65536:.3f}) ang={st[2]:#010x}", flush=True)

pal = art.playpal()
img = Image.new("RGB", (cfg.VIEW_W, cfg.VIEW_H))
img.putdata([tuple(pal[i]) for i in scr.pixel_indices])
if args.scale > 1:
    img = img.resize((cfg.VIEW_W * args.scale, cfg.VIEW_H * args.scale), Image.NEAREST)
out = ROOT / args.out
img.save(out)
print(f"wrote {out} ({img.size[0]}x{img.size[1]})")
