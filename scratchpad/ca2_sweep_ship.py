"""The 260-frame sweep on the SHIPPED tier (sim + collision + moving things, self_reset=False).

`scratchpad/ca2_sweep.py` drives deg_gate binaries, which take a bare 3-line stdin. The shipped
binary takes the full wire (`encode_feed` + things + bindings + visibility), exactly as
`scratchpad/m1_sweep.py` builds it -- so that construction is reused here verbatim rather than
re-derived, and the viewpoint set is the same 65 walkable grid points x 4 angles the repo reports.

CONTROLS (R9)
  * BYTE-EXACTNESS over all 260 frames between the two binaries, not 4.
  * Both binaries measured in ONE interleaved run, frame by frame (this machine's wall clock drifts
    ~70%; op counts are deterministic, but interleaving removes any doubt about which tree produced
    which column).
  * FRAME-COUNT control: each run must present exactly 1 frame (these are non-looping binaries; a
    binary presenting 0 or 2 would otherwise compare "byte-exact" against an empty buffer).
  * VACUITY: the 260 pictures must not collapse to a handful of distinct frames.
  * Both binaries printed with sha256 (R2).

    python scratchpad/ca2_sweep_ship.py --a <base.fjm> --b <new.fjm>
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

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from nb_validate import true_sector, _near_any_line                       # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True, help="baseline fjm")
ap.add_argument("--b", required=True, help="new fjm")
ap.add_argument("--step", type=int, default=256)      # m1_sweep default: 65 pts x 4 = 260 frames
ap.add_argument("--angles", type=int, default=4)
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

# the shipped wire -- the SAME construction as scratchpad/m1_sweep.py:88-101
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, M)
dr = [t for t in w.things(M) if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])
THINGS = encode_things([(t.x << 16, t.y << 16) for t in RT])
VIS = encode_visibility([1] * NVIS)


def wire(vx, vy, va):
    return encode_feed(vx << 16, vy << 16, va, 0) + THINGS + BINDS + VIS


class MF(StreamScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


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
    scr = MF(stdin=wire(vx, vy, va), n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops, scr.frames


opsA, opsB, bad, nframe_bad, pics = [], [], 0, 0, set()
t0 = time.perf_counter()
for k, (vx, vy, va) in enumerate(VPS):
    oa, fa = run(RA, vx, vy, va)
    ob, fb = run(RB, vx, vy, va)
    if len(fa) != 1 or len(fb) != 1:
        nframe_bad += 1
        continue
    opsA.append(oa)
    opsB.append(ob)
    pics.add(hashlib.sha256(fa[0]).hexdigest())
    if fa[0] != fb[0]:
        bad += 1
        if bad <= 3:
            d = sum(1 for u, v in zip(fa[0], fb[0]) if u != v)
            print("  !! (%d,%d,%#x): %d px DIFFER" % (vx, vy, va, d), flush=True)
    if (k + 1) % 40 == 0:
        print("   %d/%d frames (%.0fs)" % (k + 1, len(VPS), time.perf_counter() - t0), flush=True)


def stats(v):
    return statistics.median(v), sum(v) / len(v), min(v), max(v)


ma, aa, na, xa = stats(opsA)
mb, ab, nb, xb = stats(opsB)
print("")
print("=" * 92)
print("SHIPPED TIER (self_reset=False, sim + collision + moving things)")
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
print("FRAME-COUNT ctl : %d viewpoints presented != 1 frame  %s"
      % (nframe_bad, "ok" if nframe_bad == 0 else "!! a run did not present exactly one frame"))
print("PICTURE CONTROL : %d of %d frames byte-exact between A and B  %s"
      % (len(opsA) - bad, len(opsA), "ok" if bad == 0 else "!! %d DIFFER" % bad))
print("VACUITY CONTROL : %d distinct pictures across %d frames  %s"
      % (len(pics), len(opsA), "ok" if len(pics) > len(opsA) // 4 else "!! too few distinct"))
ok = bad == 0 and nframe_bad == 0 and len(pics) > len(opsA) // 4
print("")
print("ca2_sweep_ship: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
