"""The GOVERNING metric for the M13-VTXDISP / M13-SINADISP / M13-SINPERENTRY round: the 260-frame
sweep median, measured on TWO binaries and compared frame by frame.

Why not deg_gate alone: deg_gate's four viewpoints are WORST CASES. The repo's cost model is the
median over the sweep's 65 walkable grid points x 4 angles, and the two disagree by ~40%.

Why this needs no build: both binaries already exist -- deg_gate assembles one per run and leaves
it in a temp dir. Point --a and --b at them.

CONTROLS (R9)
  * BYTE-EXACTNESS over all 260 frames, not 4. Every frame of A is compared to the same frame of B;
    the run FAILS on any mismatch. This is a strictly stronger picture proof than the gate.
  * BOTH SIDES MEASURED IN THIS RUN, interleaved point by point, because this machine's wall clock
    drifts ~70%; op counts are deterministic, but interleaving also removes any doubt about which
    tree produced which column.
  * The binaries are printed with their sha256, so the log says what it measured (R2).
  * A VACUITY check: the 260 frames must not all be identical to each other (a binary that painted
    one constant picture would otherwise pass byte-exactness trivially).

    python scratchpad/ca2_sweep.py --a <base.fjm> --b <new.fjm> [--angles 4] [--step 192]
"""
import argparse
import hashlib
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.wireformat import encode_feed_mapunits
from doomfj.wad import WadFile                                           # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                     # noqa: E402
from nb_validate import true_sector, _near_any_line                      # noqa: E402
from tests.fj.stream_screen import StreamScreen                          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True, help="baseline fjm")
ap.add_argument("--b", required=True, help="new fjm")
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--step", type=int, default=256)   # m1_sweep default: 65 pts x 4 = 260
ap.add_argument("--limit", type=int, default=0)
args = ap.parse_args()


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


print("A (baseline): %s  sha256 %s" % (args.a, _sha(args.a)))
print("B (new)     : %s  sha256 %s" % (args.b, _sha(args.b)))
print("")

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
if args.limit:
    VPS = VPS[:args.limit]
print("%d walkable grid points x %d angles = %d frames" % (len(pts), args.angles, len(VPS)),
      flush=True)

RA, RB = FjmRunner(Path(args.a)), FjmRunner(Path(args.b))


def image(r):
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for st, vals in r._runs:
        c.set_words(st, vals)
    return c


def run(r, vx, vy, va):
    core = image(r)
    scr = StreamScreen(stdin=encode_feed_mapunits(vx, vy, va))
    # the screen device must be attached to THIS core's memory (m1_sweep.py:132 does the same);
    # without it ScreenIO raises "the screen device is not attached to the interpreter memory".
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops, bytes(scr.pixel_indices)


opsA, opsB, bad, pics = [], [], 0, set()
t0 = time.perf_counter()
for k, (vx, vy, va) in enumerate(VPS):
    oa, pa = run(RA, vx, vy, va)          # interleaved: A then B for the SAME viewpoint
    ob, pb = run(RB, vx, vy, va)
    opsA.append(oa)
    opsB.append(ob)
    pics.add(hashlib.sha256(pa).hexdigest())
    if pa != pb:
        bad += 1
        if bad <= 3:
            d = sum(1 for u, v in zip(pa, pb) if u != v)
            print("  !! (%d,%d,%#x): %d px DIFFER" % (vx, vy, va, d), flush=True)
    if (k + 1) % 40 == 0:
        print("   %d/%d frames (%.0fs)" % (k + 1, len(VPS), time.perf_counter() - t0), flush=True)


def stats(v):
    return statistics.median(v), sum(v) / len(v), min(v), max(v)


ma, aa, na, xa = stats(opsA)
mb, ab, nb, xb = stats(opsB)
print("")
print("=" * 92)
print("%-10s %14s %14s %14s %14s" % ("", "median", "mean", "min", "max"))
print("%-10s %14s %14s %14s %14s" % ("A base", format(int(ma), ","), format(int(aa), ","),
                                     format(na, ","), format(xa, ",")))
print("%-10s %14s %14s %14s %14s" % ("B new", format(int(mb), ","), format(int(ab), ","),
                                     format(nb, ","), format(xb, ",")))
print("%-10s %14s %14s %14s %14s" % ("delta", format(int(mb - ma), ","),
                                     format(int(ab - aa), ","), format(nb - na, ","),
                                     format(xb - xa, ",")))
print("%-10s %13.2f%% %13.2f%%" % ("pct", 100 * (mb - ma) / ma, 100 * (ab - aa) / aa))
print("=" * 92)
print("PICTURE CONTROL : %d of %d frames byte-exact between A and B  %s"
      % (len(VPS) - bad, len(VPS), "ok" if bad == 0 else "!! %d DIFFER" % bad))
print("VACUITY CONTROL : %d distinct pictures across %d frames  %s"
      % (len(pics), len(VPS), "ok" if len(pics) > len(VPS) // 4 else "!! too few distinct frames"))
ok = bad == 0 and len(pics) > len(VPS) // 4
print("")
print("ca2_sweep: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
