"""THING_BUDGET, visualised: what the knob actually drops, and what it buys.

Renders the same viewpoint at several budgets through the ORACLE (so it is seconds, not builds),
and reports for each: how many things were projected, how many the budget turned away, and how many
pixels of the unbounded frame are lost. Writes a labelled contact sheet.

    python scratchpad/thing_budget_demo.py
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
from PIL import Image, ImageDraw
import doomfj.reference_model as RM
from doomfj.config import Config
from doomfj.fixedpoint import _signed
from doomfj.reference_model import (THING_SPRITE, ReferenceModel, SimState, build_scene,
                                    spawn_state)
from doomfj.wad import WadFile

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
scene = build_scene(mw, mw, "E1M1")
pal = mw.playpal()
W, H = cfg.VIEW_W, cfg.VIEW_H
sp = spawn_state(mw, "E1M1")
VPS = [(2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst"), (1400, 1200, 0, "courtyard"),
       (_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn")]
BUDGETS = [96, 24, 16, 8]
KW = dict(wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True, sky=True,
          near_steps=True, things=True, sprite_wad=art)


def render(vx, vy, va, budget):
    RM.THING_BUDGET = budget                       # the oracle reads the module global
    out: list = []
    fb = rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene,
                              things_out=out, **KW)
    cols = sum(1 for f in out[0] if f is not None)
    return bytes(fb), out[1], cols                 # things PROJECTED, and the columns they cover


def img(fb, s=3):
    im = Image.new("RGB", (W, H))
    im.putdata([pal[p] for p in fb])
    return im.resize((W * s, H * s), Image.NEAREST)


S, PADX, PADY, LBL = 3, 10, 26, 22
sheet = Image.new("RGB", (len(BUDGETS) * (W * S + PADX), len(VPS) * (H * S + PADY) + LBL),
                  (18, 18, 22))
d = ImageDraw.Draw(sheet)
print(f"{'viewpoint':11s} " + "".join(f"{'budget ' + str(b):>30s}" for b in BUDGETS))
for r, (vx, vy, va, tag) in enumerate(VPS):
    base, base_n, base_c = render(vx, vy, va, BUDGETS[0])
    row = []
    for c, b in enumerate(BUDGETS):
        fb, n, ncol = render(vx, vy, va, b)
        lost = sum(1 for i in range(len(fb)) if fb[i] != base[i])
        row.append(f"{n:2d} things/{ncol:3d} cols, {lost:4d} px")
        x0, y0 = c * (W * S + PADX), LBL + r * (H * S + PADY)
        sheet.paste(img(fb, S), (x0, y0))
        d.text((x0 + 3, y0 + H * S + 4),
               f"{tag}  budget {b}: {n} things projected, {ncol} sprite columns"
               + ("" if b == BUDGETS[0] else f"   --  {lost} px lost"), fill=(210, 210, 215))
    print(f"{tag:11s} " + "".join(f"{t:>30s}" for t in row))
for c, b in enumerate(BUDGETS):
    d.text((c * (W * S + PADX) + 3, 5), f"THING_BUDGET = {b}"
           + ("  (unbounded on E1M1)" if b == 96 else ""), fill=(255, 220, 120))
out = ROOT / "scratchpad/thing_budget.png"
sheet.save(out)
print("\nwrote", out)
