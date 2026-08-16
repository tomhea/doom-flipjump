"""THE M14 SWEEP — the certification sweep, on the binary wire.

`lite_sweep.py` feeds three decimals and so cannot drive an M14 binary at all. Same walkable-point
generation (the stock ray oracle, the 24-unit boundary reject), same statistics, but the feed is
`wireformat.encode_feed` plus, for a `--things` build, the thing block.

WHY THIS EXISTS: every M14 number in the repo is the FOUR `deg_gate` viewpoints, which are hard
frames near the top of the distribution (33.5-45.2M when the certified sweep median was 22.94M).
Quoting a gate viewpoint against a remembered median compares two different things. This measures
the median.

⚠ keys=0 throughout, so the player sim is a no-op and COLLISION NEVER RUNS. That is the honest
shape of a "median frame" for a renderer sweep, and it means this number does NOT include M14-d's
~11.6M-per-moving-tic. Report both or neither.

    python scratchpad/m14_sweep.py <cached.fjm> [--step 256] [--angles 4] [--things] [--csv out]
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.reference_model import ReferenceModel                         # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed_mapunits,   # noqa: E402
                              encode_things, encode_visibility)
from nb_validate import true_sector, _near_any_line                       # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--things", action="store_true", help="the build reads a runtime thing block")
ap.add_argument("--cold", action="store_true",
                help="feed all-dirty bindings (a cold start) instead of the steady state")
ap.add_argument("--csv", default=None)
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()

w = WadFile.from_path(str(ROOT / args.wad))
M = "E1M1"
verts = [(v.x, v.y) for v in w.vertexes(M)]
lds, sds = w.linedefs(M), w.sidedefs(M)
xs, ys = [v[0] for v in verts], [v[1] for v in verts]
pts = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if _near_any_line(verts, lds, x, y, 24.0):
            continue
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))
print(f"{len(pts)} walkable grid points x {args.angles} angles", flush=True)

# the SPAWN thing block -- the same positions the baked path had, so this sweep measures the cost
# of the runtime table and not the cost of having moved anything
# ⚠ and the WARM bindings with it. A median frame during play has almost nothing moving, so the
# steady state is what the median should measure; feeding all-dirty would measure a cold start,
# which happens once. `--cold` measures that instead, and both are worth reporting.
THINGS = b""
NTH = 0
if args.things:
    from doomfj.mapcompiler import bake_bsp
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    rm = ReferenceModel(Config())
    cmap = bake_bsp(w, M)
    from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES
    from doomfj.things import baked_thing_mask, vanishable_slots
    drawable = [t for t in w.things(M) if rm.sprite_art(art, t.type, {}) is not None]
    # M14.5: only the RUNTIME half is on the wire -- the baked half is code inside its leaf.
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    # M14.5: every baked vanishable thing is VISIBLE for the sweep -- the median frame is the one
    # the player sees at level load, with nothing picked up yet.
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    drawable = [t for t, b in zip(drawable, baked) if not b]
    THINGS = encode_things([(t.x << 16, t.y << 16) for t in drawable])
    binds = ([0xFFFF] * len(drawable) if args.cold
             else [rm.point_in_subsector(cmap, t.x, t.y) for t in drawable])
    THINGS += encode_bindings(binds)
    THINGS += encode_visibility([1] * nvis)
    NTH = len(drawable)
    print(f"thing block: {len(drawable)} runtime things ({sum(baked)} baked), {len(THINGS)} bytes "
          f"({'COLD -- all dirty' if args.cold else 'WARM -- steady state'})", flush=True)

r = FjmRunner(str(ROOT / args.fjm) if not Path(args.fjm).is_absolute() else args.fjm)
rows, allops = [], []
worst = (0, None)
for i, (x, y) in enumerate(pts):
    for k in range(args.angles):
        va = (k << 30) & 0xFFFFFFFF
        ops = r.run(StreamScreen(stdin=encode_feed_mapunits(x, y, va) + THINGS,
                                 n_things=NTH))
        allops.append(ops)
        rows.append((x, y, va, ops))
        if ops > worst[0]:
            worst = (ops, (x, y, va))
            print(f"  new worst {ops:,} @ ({x},{y},{va:#x})", flush=True)
    if (i + 1) % 25 == 0:
        print(f"  ...{i+1}/{len(pts)} done, worst so far {worst[0]:,}", flush=True)

allops.sort()
n = len(allops)
print(f"\nframes: {n}")
print(f"min / MEDIAN / mean : {allops[0]:,} / {allops[n//2]:,} / {int(statistics.mean(allops)):,}")
print(f"p90 / p99 / WORST   : {allops[int(n*0.9)]:,} / {allops[int(n*0.99)]:,} / "
      f"{worst[0]:,} @ {worst[1]}")
for bar in (20_000_000, 26_000_000, 30_000_000):
    u = sum(1 for o in allops if o < bar)
    print(f"under {bar//1_000_000}M: {u}/{n} = {100*u/n:.0f}%")
if args.csv:
    out = ROOT / args.csv
    out.write_text("x,y,va,ops\n" + "\n".join(f"{a},{b},{c},{d}" for a, b, c, d in rows))
    print(f"wrote {out}")
