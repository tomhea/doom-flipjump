"""WHICH SPRITE CLASSES ARE CHEAP? — loads per class over the 260 frames, no build.

The 27M budget buys a fixed number of OPS, not a fixed number of things, and cost per thing is NOT
uniform: a thing only costs anything on frames where the walk actually reaches its leaf before
`full` latches. A barrel in a corridor nobody looks down is nearly free; a bonus dot in the opening
courtyard is loaded on most of the 260 frames.

So this counts, per thing TYPE, how many (frame, thing) LOADS it causes -- i.e. how many times its
leaf falls in the walk's pre-`full` prefix -- and divides the measured sprite bill by the total.
That turns "which sprites can I afford" into a ranked list instead of a guess.

INPUTS (both already measured):
  scratchpad/m5_counts.csv     per-frame `leaves_lo` = the pre-`full` prefix length
  the sprite bill              9,439,503 ops at the median for the 198 dropped things

⚠ A PROXY, AND LABELLED ONE. Loads dominate (94.1% of things are rejected after loading) but an
ACCEPTED thing also pays to draw, and big classes get accepted more often -- so this understates
large sprites. Use it to rank, then MEASURE the chosen set with a build + sweep.

    python scratchpad/m14_class_cost.py
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.reference_model import MONSTER_TYPES, ReferenceModel          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
cmap = bake_bsp(mw, "E1M1")

# every thing the FULL table would draw, with its leaf
RM.THING_SPRITE = RM.THING_SPRITE_ALL
allt = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
leaf = [rm.point_in_subsector(cmap, t.x, t.y) for t in allt]
print(f"{len(allt)} drawable things with every class enabled")

rows = [ln.split(",") for ln in
        (ROOT / "scratchpad/m5_counts.csv").read_text().strip().splitlines()[1:]]
loads = collections.Counter()
present = collections.Counter()
for r in rows:
    x, y, prefix = int(r[0]), int(r[1]), int(r[10])       # leaves_lo
    order = rm.bsp_render_order(cmap, x, y)
    reached = set(order[:prefix])
    for t, ss in zip(allt, leaf):
        if ss in reached:
            loads[t.type] += 1
for t in allt:
    present[t.type] += 1

BILL = 9_439_503                       # MEASURED: the 198 dropped things' median cost
drop_loads = sum(n for ty, n in loads.items() if ty not in MONSTER_TYPES)
# ⚠ BILL is a PER-FRAME cost, so the divisor must be loads PER FRAME. Dividing by the
# 260-frame TOTAL understates every figure by exactly 260x -- the tell is that the
# cumulative column must sum to BILL, and it summed to 36,306.
per_load = BILL / max(1e-9, drop_loads / len(rows))
print(f"loads over {len(rows)} frames by dropped things: {drop_loads:,}  "
      f"=> ~{per_load:,.0f} ops per load (median-frame equivalent)\n")

print(f"{'type':>6} {'sprite':>6} {'n':>4} {'loads':>8} {'loads/frame':>12} "
      f"{'~ops/frame':>11}   {'cumulative':>10}")
cum = 0
cand = [(ty, n) for ty, n in loads.items() if ty not in MONSTER_TYPES]
for ty, n in sorted(cand, key=lambda kv: kv[1] / max(1, present[kv[0]])):
    ops = n / len(rows) * per_load
    cum += ops
    print(f"{ty:6d} {RM.THING_SPRITE_ALL.get(ty, '?'):>6} {present[ty]:4d} {n:8d} "
          f"{n/len(rows):12.2f} {ops:11,.0f}   {cum:10,.0f}")
print("\nranked CHEAPEST-PER-THING first. `cumulative` is what restoring everything down to that "
      "row costs at the median, on top of the monsters-only 25,853,174.")
