"""M14.5 §4b PRE-CHECK — how much picture is actually at risk from the merged iteration order?

Splitting a leaf into "baked statics, then dynamic monsters" cannot reproduce today's WAD-order
interleaving. That matters only where a leaf holds BOTH kinds, so this bounds the exposure BEFORE
anything is built (M5: oracle-side, no build).

Reports:
  * leaves holding both a static and a dynamic thing
  * the PAIRS inside them that would actually swap (static's wad index > monster's), since a pair
    already in statics-first order is unaffected
  * how often such a leaf is REACHED before the `full` latch, over the sweep's 260 frames -- a leaf
    the walk never enters cannot show the difference

⚠ Swapping only shows where the two overlap in the same COLUMN, so this is an UPPER BOUND on the
visible effect, not a prediction of it.

    python scratchpad/m145_order_check.py
"""
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.reference_model import MONSTER_TYPES, ReferenceModel          # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmap = bake_bsp(mw, "E1M1")

# M14.5 intends every class back (statics as baked glyphs), so evaluate the FULL set
RM.THING_SPRITE = RM.THING_SPRITE_ALL
allt = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
leaf = [rm.point_in_subsector(cmap, t.x, t.y) for t in allt]

by_leaf = collections.defaultdict(list)
for i, (t, ss) in enumerate(zip(allt, leaf)):
    by_leaf[ss].append((i, t.type in MONSTER_TYPES))

both, swap_pairs = [], 0
for ss, items in by_leaf.items():
    mons = [i for i, m in items if m]
    stat = [i for i, m in items if not m]
    if mons and stat:
        both.append(ss)
        # statics-first reorders exactly the pairs where the static came LATER in wad order
        swap_pairs += sum(1 for s in stat for m in mons if s > m)

print(f"drawable things              : {len(allt)}   monsters {sum(1 for t in allt if t.type in MONSTER_TYPES)}")
print(f"leaves holding things        : {len(by_leaf)}")
print(f"leaves holding BOTH kinds    : {len(both)}")
print(f"static/monster pairs that SWAP under statics-first: {swap_pairs}")

rows = [ln.split(",") for ln in
        (ROOT / "scratchpad/m5_counts.csv").read_text().strip().splitlines()[1:]]
reach = collections.Counter()
for r in rows:
    x, y, prefix = int(r[0]), int(r[1]), int(r[10])
    reached = set(rm.bsp_render_order(cmap, x, y)[:prefix])
    for ss in both:
        if ss in reached:
            reach[ss] += 1
tot = sum(reach.values())
print(f"\nover {len(rows)} sweep frames:")
print(f"  frames reaching >=1 both-kind leaf : "
      f"{sum(1 for r in rows if any(ss in set(rm.bsp_render_order(cmap, int(r[0]), int(r[1]))[:int(r[10])]) for ss in both))}"
      f" / {len(rows)}")
print(f"  (leaf, frame) reach events         : {tot}  = {tot/len(rows):.2f} per frame")
if both:
    print("\n  most-reached both-kind leaves:")
    for ss, n in reach.most_common(6):
        items = by_leaf[ss]
        print(f"    ss{ss:4d} reached {n:4d}/{len(rows)} frames  "
              f"({sum(1 for _, m in items if m)} monsters, {sum(1 for _, m in items if not m)} statics)")
print("\n⚠ UPPER BOUND: a swap is only visible where the two sprites overlap in the same column.")
