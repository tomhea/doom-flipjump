"""lite_sweep with per-frame recording: same 260-frame grid, writes (x, y, angle, ops) CSV.

    python scratchpad/lite_sweep_csv.py <cached.fjm> --out scratchpad/sweep_frames.csv
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
ap.add_argument("--out", default="scratchpad/sweep_frames.csv")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
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
            continue
        if true_sector(verts, lds, sds, x, y) == -1:
            continue
        pts.append((x, y))
print(f"{len(pts)} walkable grid points x {args.angles} angles")

r = FjmRunner(args.fjm)
rows = []
for i, (x, y) in enumerate(pts):
    for k in range(args.angles):
        va = (k << 30) & 0xFFFFFFFF
        scr = StreamScreen(stdin=f"{x}\n{y}\n{va}\n".encode())
        rows.append((x, y, va, r.run(scr)))
    if (i + 1) % 25 == 0:
        print(f"  ...{i+1}/{len(pts)}", flush=True)

with open(args.out, "w", encoding="utf-8") as f:
    f.write("x,y,angle,ops\n")
    for x, y, va, ops in rows:
        f.write(f"{x},{y},{va},{ops}\n")

allops = sorted(o for _x, _y, _a, o in rows)
n = len(allops)
over25 = [(x, y, a, o) for x, y, a, o in rows if o > 25_000_000]
print(f"\nframes: {n}  median {allops[n//2]:,}  mean {int(statistics.mean(allops)):,}"
      f"  worst {allops[-1]:,}")
print(f"over 25M: {len(over25)}/{n} = {100*len(over25)/n:.0f}%")
for x, y, a, o in sorted(over25, key=lambda t: -t[3])[:15]:
    print(f"  {o:12,} @ ({x},{y},{a:#x})")
