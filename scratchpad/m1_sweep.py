"""M1 — the reset's cost against THE METRIC (the sweep median), not against gate viewpoints.

⚠ WHY THIS EXISTS. I reported the reset as "7.47% of a 47.5M-op frame". 47.5M was the mean of eight
HAND-PICKED gate-style viewpoints, and `docs/handoff-complete-game.md` §4 says in as many words:
"The sweep median over 260 frames is THE metric. Gate viewpoints overstate the typical frame by
1.5-1.9x." So that percentage used the wrong denominator and flattered the result.

This rebuilds the sweep's own viewpoint set (the walkable grid `m14_sweep.py` uses) and measures:
  * the MEDIAN per-frame cost, one frame per run on the OLD binary -- the repo's metric, re-measured
    in this session rather than quoted from a commit message;
  * the same frames in ONE run on the LOOPING binary, giving the reset's per-frame cost at sweep
    scale rather than on four worst cases.

⚠ CONTROL: the two paths must render the same picture, frame for frame. A cheaper number from a
program drawing something else is not a cheaper number.

    python scratchpad/m1_sweep.py [--step 256] [--angles 4] [--limit N]
"""
import argparse
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
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
ap.add_argument("--loop-fjm", default="scratchpad/fjmcache/_m1loop.fjm")
ap.add_argument("--old-fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--step", type=int, default=256)
ap.add_argument("--angles", type=int, default=4)
ap.add_argument("--limit", type=int, default=0, help="cap the frame count (0 = all)")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# R2 (CR round 6): a verdict that names no artifact cannot be attributed to one. Print the images
# this run is about, with hashes, so the log says what it measured.
for _lbl, _pth in (("loop", args.loop_fjm), ("old ", args.old_fjm)):
    print("%s : %s  sha256 %s" % (_lbl, _pth, _sha(_pth)))
print("")


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
VPS = [(x, y, (a * (1 << 32) // args.angles) & 0xFFFFFFFF)
       for x, y in pts for a in range(args.angles)]
if args.limit:
    VPS = VPS[:args.limit]
print(f"{len(pts)} walkable grid points x {args.angles} angles = {len(VPS)} frames", flush=True)

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


def image(r):
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for st, vals in r._runs:
        c.set_words(st, vals)
    return c


R_OLD = FjmRunner(Path(args.old_fjm))
R_NEW = FjmRunner(Path(args.loop_fjm))

print("sweeping the OLD binary, one frame per run (the repo's metric) ...", flush=True)
t0 = time.perf_counter()
ops_each, pics = [], []
for k, v in enumerate(VPS):
    core = image(R_OLD)
    scr = MF(stdin=wire(*v), n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, R_OLD.width))
    _c, o, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    assert len(scr.frames) == 1, f"old binary presented {len(scr.frames)} frames"
    ops_each.append(o)
    pics.append(scr.frames[0])
    del core, scr
    if (k + 1) % 40 == 0:
        print(f"   {k+1}/{len(VPS)} frames ({time.perf_counter()-t0:.0f}s)", flush=True)
med = statistics.median(ops_each)
print(f"SWEEP over {len(VPS)} frames, OLD binary (no reset in the program):")
print(f"  median {med:,.0f}   mean {statistics.mean(ops_each):,.0f}   "
      f"min {min(ops_each):,}   max {max(ops_each):,}")

print("the same frames in ONE run on the LOOPING binary ...", flush=True)
t1 = time.perf_counter()
core = image(R_NEW)
scr = MF(stdin=b"".join(wire(*v) for v in VPS), n_things=len(RT))
scr.attach_memory(NativeDeviceMemory(core, R_NEW.width))
_c, loop_ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
loop_pics = list(scr.frames)
del core, scr
print(f"  {loop_ops:,} ops, {len(loop_pics)} frames ({time.perf_counter()-t1:.0f}s)")
assert len(loop_pics) == len(VPS), f"CONTROL: {len(loop_pics)} frames != {len(VPS)}"
bad = sum(1 for a, b in zip(loop_pics, pics) if a != b)
print(f"  CONTROL (same pictures): {len(VPS)-bad}/{len(VPS)} byte-exact  "
      f"{'ok' if not bad else '!! %d FRAMES DIFFER' % bad}")

extra = loop_ops - sum(ops_each)
per = extra / len(VPS)
print("=" * 88)
print(f"  sweep MEDIAN frame          : {med:,.0f} ops")
print(f"  in-program reset, per frame : {per:,.0f} ops")
print(f"  => the reset is {100*per/med:.1f}% OF THE MEDIAN FRAME")
print("     (previously reported as 7.47%, against a 47.5M mean of GATE viewpoints -- the wrong")
print("      denominator. Gate frames overstate the typical frame, exactly as the handoff says.)")
print("=" * 88)
