"""THE PICTURE the 25M sprite package costs — before/after, side by side.

docs/handoff-perf.md §7: a sprite removal must be priced AND brought to the owner as an IMAGE, so
the decision is made on what it looks like, not on a description. This renders the same viewpoints
twice through the oracle — once with every sprite class (`THING_SPRITE_ALL`) and once with
`DROPPED_SPRITE_TYPES` applied — and writes a stacked PNG per viewpoint plus one contact sheet.

⚠ ORACLE-RENDERED, deliberately. The oracle IS the definition of the frame and the fj binary is
gated byte-exact against it, so the two are the same picture; rendering here costs seconds instead
of a 25-minute build per variant.

    python scratchpad/spr25_sheet.py [--out scratchpad/spr25_sheet.png]
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from PIL import Image                                                     # noqa: E402

from doomfj.config import Config                                          # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="scratchpad/spr27c_sheet.png")
ap.add_argument("--scale", type=int, default=3)
args = ap.parse_args()

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000, "crowded"), (1272, -724, 1073741824, "stairs"),
       (1869, 479, 2147483648, "everything"), (spx, spy, sp.angle, "spawn")]
KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
          near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

pal = mw.playpal() if hasattr(mw, "playpal") else None
if pal is None:                                   # the palette lives in the asset wad on lite
    pal = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_assets.wad")).playpal()


def render(vx, vy, va, full: bool):
    """One frame. `full` restores every sprite class; otherwise the shipped (cut) set is used."""
    saved = RM.THING_SPRITE
    if full:
        RM.THING_SPRITE = RM.THING_SPRITE_ALL     # the module-level dict all three filters read
    try:
        rm._spr_cache = {}
        return bytes(rm.render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene, **KW))
    finally:
        RM.THING_SPRITE = saved


# playpal() hands back 256 (r,g,b) TUPLES; putpalette wants 768 flat bytes
FLAT = bytes(c for rgb in list(pal)[:256] for c in rgb)
W, H, S = cfg.VIEW_W, cfg.VIEW_H, args.scale
sheet = Image.new("RGB", (W * S * 2 + 12, (H * S + 4) * len(VPS)), (24, 24, 24))
for row, (vx, vy, va, name) in enumerate(VPS):
    for col, full in enumerate((True, False)):
        fb = render(vx, vy, va, full)
        im = Image.frombytes("P", (W, H), fb)
        im.putpalette(FLAT)
        im = im.convert("RGB")
        im = im.resize((W * S, H * S), Image.NEAREST)
        sheet.paste(im, (col * (W * S + 12), row * (H * S + 4)))
    print(f"  {name} ({vx},{vy},{va:#x})  left = all 251 things, right = the shipped 27M set",
          flush=True)
out = ROOT / args.out
sheet.save(out)
print(f"\nwrote {out}   LEFT = every sprite (251) | RIGHT = the shipped 27M set (monsters + 6 props + shotguns + medikits)")
print(f"dropped {len(RM.DROPPED_SPRITE_TYPES)} classes / 198 of E1M1's 251 things")
