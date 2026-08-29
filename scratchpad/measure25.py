"""Measure a variant binary on the heavy (>25M) frames + the median guard, against the
baseline per-frame CSV.

    python scratchpad/measure25.py <variant.fjm> [--all]   (--all = full 260-frame sweep)
"""
import argparse
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner                                      # noqa: E402
from doomfj.wireformat import encode_feed_mapunits
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--all", action="store_true")
ap.add_argument("--csv", default="scratchpad/sweep_frames.csv")
args = ap.parse_args()

frames = []
with open(args.csv, encoding="utf-8") as f:
    next(f)
    for line in f:
        x, y, a, o = line.strip().split(",")
        frames.append((int(x), int(y), int(a), int(o)))

heavy = sorted((f for f in frames if f[3] > 25_000_000), key=lambda t: -t[3])
target = frames if args.all else heavy
r = FjmRunner(args.fjm)
res = []
for i, (x, y, a, base) in enumerate(target):
    scr = StreamScreen(stdin=encode_feed_mapunits(x, y, a))
    ops = r.run(scr)
    res.append((x, y, a, base, ops))
    if (i + 1) % 40 == 0:
        print(f"  ...{i+1}/{len(target)}", flush=True)

news = sorted(o for *_x, o in res)
n = len(news)
hv = [(x, y, a, b, o) for x, y, a, b, o in res if b > 25_000_000]
print(f"\n{len(res)} frames   heavy subset: {len(hv)}")
print(f"heavy worst {max(o for *_x, o in hv):,}   still>25M "
      f"{sum(1 for *_x, o in hv if o > 25_000_000)}/{len(hv)}")
print("top frames (base -> variant, delta):")
for x, y, a, b, o in sorted(hv, key=lambda t: -t[3])[:12]:
    print(f"  {b:12,} -> {o:12,}  ({(o-b)/1e6:+7.2f}M)  @ ({x},{y},{a:#x})")
if args.all:
    print(f"\nfull sweep: median {news[n//2]:,}  mean {int(statistics.mean(news)):,}  "
          f"worst {news[-1]:,}")
