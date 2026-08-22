"""How often does check_line's BBOX test actually reject? C5's entire value rides on this.

`hex.read_table_packed nb` pays a fixed per-call staging preamble (zero w/4 + mov + mul_const w/4 +
add w/4) BEFORE any byte is read. Splitting the 22-byte linedef row into an 8-byte bbox half and a
14-byte remainder therefore trades:

    saving = reject_rate x 14 byte-reads
    cost   = (1 - reject_rate) x one extra staging preamble

The survey measured 93% rejection on a FIXTURE wad with uniformly-sampled in-map points, and
flagged that it needed re-measuring on real walk positions. This does that on the shipped map.

    python scratchpad/ca_bbox_rate.py [--points 40]
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.mapcompiler import bake_bsp, build_blockmap, blockmap_candidates   # noqa: E402
from doomfj.reference_model import PLAYER_RADIUS                                # noqa: E402

# PLAYER_RADIUS is 16.16 FIXED (1,048,576); blockmap_candidates and the bbox test both want
# WHOLE MAP UNITS. Passing the fixed value makes the query box span the whole map -- every
# linedef becomes a candidate (measured: 1,175 per position against a true ~22) and nothing
# can be rejected, which reads as '0% rejected' and looks like a finding. It is not.
RADIUS = PLAYER_RADIUS >> 16
from doomfj.wad import WadFile                                                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--points", type=int, default=40)
args = ap.parse_args()

t0 = time.perf_counter()
w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
cmap = bake_bsp(w, "E1M1")
lds = w.linedefs("E1M1")
verts = cmap.vertexes
print("bake_bsp: %.1fs" % (time.perf_counter() - t0), flush=True)
t0 = time.perf_counter()
grid = build_blockmap(cmap, lds)
print("build_blockmap: %.1fs" % (time.perf_counter() - t0), flush=True)

box = [(min(verts[l.v1][0], verts[l.v2][0]), max(verts[l.v1][0], verts[l.v2][0]),
        min(verts[l.v1][1], verts[l.v2][1]), max(verts[l.v1][1], verts[l.v2][1])) for l in lds]

pts, tested, rejected = 0, 0, 0
t0 = time.perf_counter()
for x in range(-2048, 3072, 512):
    for y in range(-2048, 2048, 512):
        if pts >= args.points:
            break
        c = list(blockmap_candidates(grid, x, y, RADIUS))
        if not c:
            continue
        pts += 1
        for li in c:
            minx, maxx, miny, maxy = box[li]
            tested += 1
            if (x + RADIUS <= minx or x - RADIUS >= maxx
                    or y + RADIUS <= miny or y - RADIUS >= maxy):
                rejected += 1
        if pts % 10 == 0:
            print("  %d points, %d candidates, %.1f%% rejected (%.0fs)"
                  % (pts, tested, 100 * rejected / max(1, tested), time.perf_counter() - t0),
                  flush=True)

r = 100 * rejected / max(1, tested)
print("")
print("positions sampled      : %d" % pts)
print("check_line candidates  : %s  (%.1f per position)" % (format(tested, ","), tested / max(1, pts)))
print("BBOX-rejected          : %s  (%.1f%%)" % (format(rejected, ","), r))
print("survivors, paying BOTH staging preambles: %.1f%%" % (100 - r))
print("")
print("the survey assumed 93%% rejection; measured here: %.1f%%" % r)
