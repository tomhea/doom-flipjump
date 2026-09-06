"""The FRAME POPULATION of a binary: op cost of every one of the sweep's 260 frames, dumped so
the atlas can profile a spanning handful instead of guessing which frames are representative.

frame_costs.py did this for 65 points at angle 0 and printed six percentiles. The sweep median --
the campaign's only ship criterion -- is over 65 points x 4 ANGLES, so the population that matters
is 260 wide; this writes all of it and then names the picks.

    python scratchpad/12m/frames.py --fjm scratchpad/12m/atlas/BASE.fjm --pick 8

Output: atlas/<stem>.frames.json  {"rows": [[ops, x, y, angle], ...] sorted by ops, "picks": [...]}
The picks are evenly spaced in RANK (not in ops), so the profiled set spans the population by
population share -- which is what a median-driven campaign needs.
"""
import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore                                    # noqa: E402
from doomfj.wireformat import encode_feed_mapunits                               # noqa: E402
from doomfj.wad import WadFile                                                   # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory     # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                             # noqa: E402
from nb_validate import true_sector, _near_any_line                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", required=True)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--pick", type=int, default=8)
ap.add_argument("--out", default="")
args = ap.parse_args()

w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
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
VPS = [(x, y, (a * (1 << 32) // args.angles) & 0xFFFFFFFF)
       for x, y in pts for a in range(args.angles)]
print("%d walkable points x %d angles = %d frames" % (len(pts), args.angles, len(VPS)), flush=True)

R = FjmRunner(Path(args.fjm))
rows = []
t0 = time.perf_counter()
for i, (x, y, a) in enumerate(VPS):
    core = _fjcore.Memory(R.width, flat_max_words=R.flat_max_words)
    for s, n in R._segments:
        core.add_segment(s, n)
    for st, vals in R._runs:
        core.set_words(st, vals)
    scr = StreamScreen(stdin=encode_feed_mapunits(x, y, a))
    scr.attach_memory(NativeDeviceMemory(core, R.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    rows.append((ops, x, y, a))
    if (i + 1) % 40 == 0:
        print("  %d/%d (%.0fs)" % (i + 1, len(VPS), time.perf_counter() - t0), flush=True)
rows.sort()
ops_only = [r[0] for r in rows]
print("")
print("population: min %s  p25 %s  MEDIAN %s  p75 %s  max %s"
      % tuple(format(int(v), ",") for v in
              (ops_only[0], ops_only[len(rows) // 4], statistics.median(ops_only),
               ops_only[3 * len(rows) // 4], ops_only[-1])))

picks = []
for k in range(args.pick):
    idx = round(k * (len(rows) - 1) / (args.pick - 1))
    picks.append({"rank": idx, "pct": round(100.0 * idx / (len(rows) - 1), 1),
                  "ops": rows[idx][0], "vx": rows[idx][1], "vy": rows[idx][2],
                  "va": rows[idx][3]})
print("")
print("picks (evenly spaced in RANK -- they span the population by share):")
for p in picks:
    print("  p%-5.1f rank %3d  %13s ops  (%d,%d,%#x)"
          % (p["pct"], p["rank"], format(p["ops"], ","), p["vx"], p["vy"], p["va"]))

out = Path(args.out) if args.out else Path(args.fjm).with_suffix(".frames.json")
json.dump({"fjm": args.fjm, "angles": args.angles, "step": args.step,
           "median": int(statistics.median(ops_only)), "rows": rows, "picks": picks},
          open(out, "w"), indent=1)
print("")
print("-> %s" % out)
