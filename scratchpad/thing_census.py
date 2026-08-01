"""What the THING_BUDGET actually turns away, thing by thing.

⚠ The naive version of this script (replay the selection loop standalone) OVER-COUNTS badly: the
oracle's things loop has TWO stop conditions and the one that usually fires first is
`n_claimed == VIEW_W` -- every column already owned by a wall -- not the budget. At spawn that
stops the walk before a single thing is reached, which is why EXP-8 measured "0 projectable" there
while a standalone replay finds 118.

So instrument the REAL render: run `render_wall_frame` with the budget lifted, with
`project_thing` wrapped to log every call and its verdict. The log is then exactly the ordered list
of things the frame considered, under the real stop conditions.

    python scratchpad/thing_census.py
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path('.').resolve()
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import doomfj.reference_model as RM                                       # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.reference_model import (THING_SPRITE, ReferenceModel, SimState,  # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402

MONSTERS = {9, 58, 64, 65, 66, 67, 68, 69, 71, 84, 3001, 3002, 3003, 3004, 3005, 3006, 7, 16, 88}
PICKUPS = {8, 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2010, 2011, 2012, 2013, 2014, 2015,
           2018, 2019, 2022, 2023, 2024, 2025, 2026, 2045, 2046, 2047, 2048, 2049}
STARTS = {1, 2, 3, 4, 11, 14}


def category(t):
    return ("MONSTER" if t in MONSTERS else "pickup" if t in PICKUPS else
            "start" if t in STARTS else "decor")


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

allt = mw.things("E1M1")
at_xy = {}
for t in allt:
    at_xy.setdefault((t.x, t.y), t)
print(f"E1M1 carries {len(allt)} things")
by_cat = Counter(category(t.type) for t in allt)
draw = Counter(category(t.type) for t in allt if THING_SPRITE.get(t.type) is not None)
print(f"{'category':10s} {'in level':>9s} {'V4 can draw':>12s}")
for c in ("MONSTER", "pickup", "decor", "start"):
    print(f"{c:10s} {by_cat.get(c, 0):9d} {draw.get(c, 0):12d}")
miss = sorted({t.type for t in allt if THING_SPRITE.get(t.type) is None})
print(f"unmapped types (never drawn): {miss}"
      f"  -- of which monsters: {sorted(t for t in miss if t in MONSTERS)}")

_real = RM.ReferenceModel.project_thing
LOG: list = []


def spy(self, viewx, viewy, viewangle, viewz, tx, ty, fh, a):
    r = _real(self, viewx, viewy, viewangle, viewz, tx, ty, fh, a)
    LOG.append((at_xy.get((tx, ty)), r))
    return r


RM.ReferenceModel.project_thing = spy
for vx, vy, va, tag in VPS:
    RM.THING_BUDGET = 10_000                       # lift it: log everything the frame considers
    LOG.clear()
    rm.render_wall_frame(SimState(x=vx << 16, y=vy << 16, angle=va, level="E1M1"), scene, **KW)
    hits = [(t, r) for t, r in LOG if r is not None]
    print(f"\n=== {tag} ({vx},{vy}): {len(LOG)} things REACHED before the walk stopped, "
          f"{len(hits)} PROJECT")
    for n, (t, r) in enumerate(hits, 1):
        tx1, tx2, _yt, h, _is = r
        d = max(abs((_signed(t.x, 32)) - vx), abs((_signed(t.y, 32)) - vy))
        flag = ("" if n <= 16 else "   <-- dropped at 16" if n <= 24 else
                "   <-- dropped at 16 AND 24")
        print(f"  #{n:3d} {category(t.type):8s} {THING_SPRITE[t.type]} ({t.type:5d})"
              f"  x[{tx1:4d},{tx2:4d}] h={h:3d}px  dist~{d:5d}{flag}")
    lost = [t for n, (t, _r) in enumerate(hits, 1) if n > 16]
    print(f"  budget 16 turns away {len(lost)}: {dict(Counter(category(t.type) for t in lost))}"
          if lost else "  budget 16 turns away nothing")
RM.ReferenceModel.project_thing = _real
