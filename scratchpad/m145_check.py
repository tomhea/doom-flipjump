"""M14.5 — the CHEAP controls for the baked/runtime split. No build, ~1 min.

Three things, in the order a failure is cheapest to diagnose:

  1. THE CENSUS. How many things bake, how many stay runtime, and -- the property the whole design
     rests on -- that every leaf is HOMOGENEOUS at spawn (all baked or all runtime). If that breaks,
     the per-leaf visit order stops being wad order in both mirrors and the picture moves.

  2. ORDER NEUTRALITY, at spawn. The oracle now visits a leaf BAKED-FIRST-THEN-RUNTIME. Rendered
     against a forced WAD-order oracle at the four gate viewpoints, every pixel must agree -- that
     is what makes the fj split pixel-neutral rather than "a deliberate picture change".

  3. THE TWO-SIDED HALF of the same control, because (2) alone would pass if the reordering were
     never reachable: move a RUNTIME thing into a leaf that holds baked things and require the two
     orders to DISAGREE there. That is the case the baked-first rule exists for.

    python scratchpad/m145_check.py
"""
import collections
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, ReferenceModel,        # noqa: E402
                                    SimState, build_scene, spawn_state)
from doomfj.things import baked_thing_mask, drawable_things              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
spx, spy = RM._signed(sp.x, 32) >> 16, RM._signed(sp.y, 32) >> 16
VPS = [(664, 291, 0x18000000), (1272, -724, 1073741824),
       (1869, 479, 2147483648), (spx, spy, sp.angle)]
KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
          near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

drawable, _ = drawable_things(rm, mw.things("E1M1"), art, {})
baked = baked_thing_mask(rm, scene.cmap, drawable, MONSTER_TYPES)
leaf = [rm.point_in_subsector(scene.cmap, t.x, t.y) for t in drawable]

# ── 1. the census ────────────────────────────────────────────────────────────────────────────
by_leaf = collections.defaultdict(list)
for i, ss in enumerate(leaf):
    by_leaf[ss].append(i)
mixed = [ss for ss, ii in by_leaf.items() if 0 < sum(baked[i] for i in ii) < len(ii)]
print(f"drawable {len(drawable)}  BAKED {sum(baked)}  runtime {len(drawable) - sum(baked)}  "
      f"(monsters {sum(1 for t in drawable if t.type in MONSTER_TYPES)})")
print(f"leaves holding things {len(by_leaf)}   MIXED at spawn {len(mixed)}")
ok = not mixed
if mixed:
    print(f"  !! leaves {mixed[:8]} hold both kinds -- the split rule is broken")

# ── 2/3. the ordering control ────────────────────────────────────────────────────────────────
_real_mask = baked_thing_mask


def _all_runtime(rm_, cmap, things, mt):
    """forced WAD order: with nothing baked, the oracle appends in wad order exactly as before"""
    return (False,) * len(things)


def render(vp, positions=None, wad_order=False):
    RM.baked_thing_mask = _all_runtime if wad_order else _real_mask
    try:
        return bytes(rm.render_wall_frame(SimState(vp[0] << 16, vp[1] << 16, vp[2], "E1M1"),
                                          scene, thing_positions=positions, **KW))
    finally:
        RM.baked_thing_mask = _real_mask


print("\n2. ORDER NEUTRALITY at spawn positions (baked-first vs wad order)")
for vp in VPS:
    a, b = render(vp), render(vp, wad_order=True)
    same = a == b
    ok &= same
    print(f"  ({vp[0]},{vp[1]},{vp[2]:#x}): "
          f"{'IDENTICAL' if same else f'!! {sum(x != y for x, y in zip(a, b)) } px DIFFER'}")

print("\n3. TWO-SIDED: a runtime thing moved INTO a baked leaf must reorder the frame")
# The case the baked-first rule exists for: drop a runtime thing (low wad index) exactly on top of
# a baked thing (higher wad index) in an all-baked leaf. Wad order would visit the runtime one
# first; baked-first visits it last, so the two claim the near sprite slot differently.
spawn_pos = [(t.x, t.y) for t in drawable]
runtime_lo = min((i for i, b in enumerate(baked) if not b), default=None)
cands = [(vp, ii[-1]) for vp in VPS for ss, ii in by_leaf.items()
         if all(baked[i] for i in ii) and ii[-1] > runtime_lo]
# nearest first: a thing across the map from the eye cannot show a slot swap
cands.sort(key=lambda c: (spawn_pos[c[1]][0] - c[0][0]) ** 2 + (spawn_pos[c[1]][1] - c[0][1]) ** 2)
found = False
for vp, host in cands[:6]:
    pos = list(spawn_pos)
    pos[runtime_lo] = spawn_pos[host]        # same spot -> same leaf, same columns
    a, c = render(vp, positions=pos), render(vp, positions=pos, wad_order=True)
    n = sum(x != y for x, y in zip(a, c))
    print(f"  ({vp[0]},{vp[1]},{vp[2]:#x}) runtime {runtime_lo} -> onto baked {host}: {n} px differ")
    if n:
        found = True
        break
ok &= found
if not found:
    print("  !! VACUOUS: no reordering was ever observable -- control 2 proves nothing")

print("\nPASS" if ok else "\nFAIL")
sys.exit(0 if ok else 1)
