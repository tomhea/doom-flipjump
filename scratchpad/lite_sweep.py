"""Final certification sweep: ops over WALKABLE viewpoints, native engine, one cached build.

    python scratchpad/lite_sweep.py <cached.fjm> [--step 256] [--angles 4]

Walkable = the stock ray oracle finds a sector and the point is not on a boundary. This replaces
the old bbox-grid sweep whose 'worst' point (-309,-44) turned out to be VOID.
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from nb_validate import true_sector, _near_any_line                       # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad",
                help="walkability reference (stock: lite never moves walls)")
args = ap.parse_args()

w = WadFile.from_path(args.wad)
M = "E1M1"
verts = [(v.x, v.y) for v in w.vertexes(M)]
lds, sds = w.linedefs(M), w.sidedefs(M)
xs = [v[0] for v in verts]
ys = [v[1] for v in verts]
pts = []
for x in range(min(xs) + 13, max(xs), args.step):
    for y in range(min(ys) + 7, max(ys), args.step):
        if _near_any_line(verts, lds, x, y, 24.0):
            continue                              # not somewhere a player fits anyway
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))
print(f"{len(pts)} walkable grid points x {args.angles} angles")

r = FjmRunner(args.fjm)
allops = []
worst = (0, None)
for i, (x, y) in enumerate(pts):
    for k in range(args.angles):
        va = (k << 30) & 0xFFFFFFFF
        scr = StreamScreen(stdin=f"{x}\n{y}\n{va}\n".encode())
        ops = r.run(scr)
        allops.append(ops)
        if ops > worst[0]:
            worst = (ops, (x, y, va))
            print(f"  new worst {ops:,} @ ({x},{y},{va:#x})", flush=True)
    if (i + 1) % 25 == 0:
        print(f"  ...{i+1}/{len(pts)} done, worst so far {worst[0]:,}", flush=True)

allops.sort()
n = len(allops)
print(f"\nframes: {n}")
print(f"min / median / mean : {allops[0]:,} / {allops[n//2]:,} / {int(statistics.mean(allops)):,}")
print(f"p90 / p99 / WORST   : {allops[int(n*0.9)]:,} / {allops[int(n*0.99)]:,} / {worst[0]:,} @ {worst[1]}")
under = sum(1 for o in allops if o < 15_000_000)
print(f"under 15M: {under}/{n} = {100*under/n:.0f}%   under 20M: "
      f"{sum(1 for o in allops if o < 20_000_000)}/{n} = {100*sum(1 for o in allops if o < 20_000_000)/n:.0f}%")
