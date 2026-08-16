"""M14.5 section 3.2 — HOW BIG IS THE EMPTY-LEAF SKIP, before anything is built?

Every visited leaf runs `hex.set cur_ss / ss_flr / ss_ltb` + `stl.fcall thing_pass_leaf`, and
thing_pass then builds a pointer and reads a byte only to find the list empty. Baking the test
(`hex.if0 2, sshead + s*2*dw`) would skip all of it -- and after the split, most leaves HAVE no
runtime list, because only a leaf holding a monster does.

The plan priced this once and could not separate it from the per-thing cost. It is worth pricing
again, but the first question is a COUNT, and that is free: over the sweep's frames, how many leaf
visits would the skip actually catch?

    python scratchpad/m145_leafcost.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import MONSTER_TYPES, ReferenceModel          # noqa: E402
from doomfj.things import baked_thing_mask, drawable_things              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

rm = ReferenceModel(Config())
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cmap = bake_bsp(mw, "E1M1")

drawable, _ = drawable_things(rm, mw.things("E1M1"), art, {})
baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
runtime_leaves = {rm.point_in_subsector(cmap, t.x, t.y)
                  for t, b in zip(drawable, baked) if not b}
print(f"{len(drawable)} drawable = {sum(baked)} baked + {len(drawable) - sum(baked)} runtime")
print(f"leaves with a RUNTIME list: {len(runtime_leaves)} of {len(cmap.subsectors)} subsectors")

rows = [ln.split(",") for ln in
        (ROOT / "scratchpad/m5_counts.csv").read_text().strip().splitlines()[1:]]
tot_visits = tot_empty = 0
for r in rows:
    x, y, prefix = int(r[0]), int(r[1]), int(r[10])
    visited = rm.bsp_render_order(cmap, x, y)[:prefix]
    seen = [s for s in visited if cmap.subsectors[s].numsegs]
    tot_visits += len(seen)
    tot_empty += sum(1 for s in seen if s not in runtime_leaves)
n = len(rows)
print(f"\nover {n} frames: {tot_visits/n:.1f} leaf visits per frame, "
      f"{tot_empty/n:.1f} of them with an EMPTY runtime list ({100*tot_empty/tot_visits:.0f}%)")
print("\nthe skip is worth (per-leaf cost) x (empty visits). At a plausible ~1k-3k ops for")
print("3 hex.set + fcall + ptr_index + read_byte + fret, that is:")
for c in (1000, 2000, 3000):
    print(f"   {c:,} ops/leaf -> {int(c*tot_empty/n):,} ops/frame "
          f"= {100*c*tot_empty/n/29_394_592:.2f}% of the 29,394,592 median")
