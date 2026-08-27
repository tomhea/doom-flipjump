"""Price the V4 SELECTION POLICY oracle-side (seconds, not a 10-minute build).

Varies MIN_SPRITE_H and the two budgets, and reports for each viewpoint: things projected, how many
MONSTERS made it, and how far the frame moves from the reference policy. That is the whole decision
-- "does a monster ever get dropped" and "what does the picture lose" -- without an fj build.

    python scratchpad/policy_probe.py
"""
import sys
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, THING_SPRITE, ReferenceModel,  # noqa: E402
                                    SimState, build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402

cfg = Config()
rm = ReferenceModel(cfg)
mw = WadFile.from_path('tests/fixtures/freedoom_e1m1.wad')
art = WadFile.from_path('assets/freedoom1.wad')
scene = build_scene(mw, mw, "E1M1")
sp = spawn_state(mw, "E1M1")
VPS = [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle, "spawn"),
       (1400, 1200, 0, "courtyard"), (2432, 1344, 3221225472, "tree"), (-309, -44, 0, "worst")]
KW = dict(wall_mode="WPX", floor_mode_ft1=True, plane_near=True, wall_noise=True, sky=True,
          near_steps=True, things=True, sprite_wad=art)
at = {}
for t in mw.things("E1M1"):
    at.setdefault((t.x, t.y), t)
_real = RM.ReferenceModel.project_thing
LOG: list = []


def spy(self, vx, vy, va, vz, tx, ty, fh, a, min_h=None):
    r = _real(self, vx, vy, va, vz, tx, ty, fh, a, min_h)
    LOG.append((at.get((tx, ty)), r))
    return r


RM.ReferenceModel.project_thing = spy


def run(vx, vy, va, min_h, budget, mon_budget):
    RM.MIN_SPRITE_H, RM.THING_BUDGET, RM.MONSTER_BUDGET = min_h, budget, mon_budget
    rm._tzmin_cache.clear()
    LOG.clear()
    fb = rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"),
                              scene, **KW)
    drew = [t for t, r in LOG if r is not None]
    return bytes(fb), len(LOG), len(drew), sum(1 for t in drew if t.type in MONSTER_TYPES)


# the reference: every sprite, however tiny, and no budget at all
POLICIES = [("reference (every sprite, no cap)", 1, 10_000, 10_000),
            ("scenery min 2, monsters always", 2, 16, 64),
            ("scenery min 3, monsters always", 3, 16, 64),
            ("scenery min 4, monsters always", 4, 16, 64),
            ("scenery min 6, monsters always", 6, 16, 64),
            ("scenery min 4, budget 8", 4, 8, 64)]
for vx, vy, va, tag in VPS:
    base, _n, base_d, base_m = run(vx, vy, va, 1, 10_000, 10_000)
    print(f"\n=== {tag} ({vx},{vy})  -- reference draws {base_d} things, {base_m} monsters")
    print(f"    {'policy':32s} {'projected':>10s} {'monsters':>9s} {'calls':>7s} {'px vs ref':>10s}")
    for name, mh, b, mb in POLICIES:
        fb, calls, drew, mons = run(vx, vy, va, mh, b, mb)
        px = sum(1 for i in range(len(fb)) if fb[i] != base[i])
        print(f"    {name:32s} {drew:10d} {mons:9d} {calls:7d} {px:10d}")
RM.ReferenceModel.project_thing = _real
