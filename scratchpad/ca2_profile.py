"""WHERE DO THE OPS GO? A per-op instruction-pointer histogram for one frame.

The repo can price primitives in isolation (`scratchpad/ptr_price_list.py`) and count whole frames
(`scratchpad/m1_sweep.py`), and has nothing in between -- so every "why did this get faster/slower"
question has been answered by argument. This answers it by measurement: FlipJump has ONE
instruction form and every op executes at an address, so a histogram of the instruction pointer,
diffed between two binaries, says WHERE the ops went.

HOW. `flipjump.interpreter.fjm_run._run_featured` calls `breakpoint_handler.should_break(ip,
op_counter)` on every op. This passes a handler that records `ip` and always returns False -- a
per-op hook with no interpreter changes. Selecting a breakpoint_handler forces the featured
(pure-python) loop, ~0.5-1M ops/s, so this is a ONE-FRAME tool: ~30-60 s for a median 29M-op
frame, ~2 min for the 58M worst case. A 260-frame sweep would be 7.5G ops and is not the point.

CONTROLS (R9)
  * the op total the histogram sums to MUST equal the interpreter's own op_counter -- if the hook
    misses ops, every bucket is wrong and the run is reported VACUOUS;
  * the frame produced under instrumentation must be byte-identical to the same frame produced by
    the fast engine, so the profiler cannot be changing what it measures;
  * bucket counts are printed as raw ops, never as percentages of an unstated total.

    python scratchpad/ca2_profile.py --fjm <a.fjm> [--vx -416 --vy 256 --va 0] [--out h.json]
"""
import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS                   # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.fjm_run import run as fjm_run_run               # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", required=True)
ap.add_argument("--vx", type=int, default=-416)
ap.add_argument("--vy", type=int, default=256)
ap.add_argument("--va", type=lambda s: int(s, 0), default=0)
ap.add_argument("--bucket-bits", type=int, default=20,
                help="histogram bucket width in BIT-address bits (20 = 32k words/bucket)")
ap.add_argument("--out", default="")
ap.add_argument("--top", type=int, default=25)
args = ap.parse_args()

W = 32
BSHIFT = args.bucket_bits


class IPHistogram:
    """Duck-types BreakpointHandler. Records the instruction pointer of every executed op and
    never breaks. `should_break` is called once per op by `_run_featured`."""

    def __init__(self, shift):
        self.shift = shift
        self.hist = Counter()
        self.n = 0

    def should_break(self, ip, op_counter):
        self.hist[ip >> self.shift] += 1
        self.n += 1
        return False


# ---- the shipped wire (same construction as scratchpad/m1_sweep.py) --------------------------
w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
WIRE = (encode_feed(args.vx << 16, args.vy << 16, args.va, 0)
        + encode_things([(t.x << 16, t.y << 16) for t in RT])
        + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])
        + encode_visibility([1] * NVIS))

path = Path(args.fjm)
print("fjm    : %s  sha256 %s" % (path, hashlib.sha256(path.read_bytes()).hexdigest()))
print("frame  : (%d, %d, %#x)" % (args.vx, args.vy, args.va))
print("")

# ---- CONTROL: the same frame on the FAST engine, for the picture and the op count -------------
t0 = time.perf_counter()
r = FjmRunner(path)
core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
for s, n in r._segments:
    core.add_segment(s, n)
for st, vals in r._runs:
    core.set_words(st, vals)
scr = StreamScreen(stdin=WIRE, n_things=len(RT))
scr.attach_memory(NativeDeviceMemory(core, r.width))
_c, fast_ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
fast_pic = bytes(scr.pixel_indices)
print("fast engine  : %s ops in %.1fs   picture sha %s"
      % (format(fast_ops, ","), time.perf_counter() - t0,
         hashlib.sha256(fast_pic).hexdigest()[:16]), flush=True)
del core, scr

# ---- the instrumented run --------------------------------------------------------------------
print("profiling (pure-python featured loop, ~0.5-1M ops/s) ...", flush=True)
t0 = time.perf_counter()
h = IPHistogram(BSHIFT)
scr2 = StreamScreen(stdin=WIRE, n_things=len(RT))
# the PUBLIC fj.run does not expose breakpoint_handler -- that hook lives on the interpreter's
# own entry point, which is also what selects the featured (instrumented) loop.
term = fjm_run_run(path, io_device=scr2, breakpoint_handler=h, print_time=False,
                   flat_max_words=RENDER_FLAT_MAX_WORDS)
dt = time.perf_counter() - t0
slow_pic = bytes(scr2.pixel_indices)
print("profiled     : %s ops in %.0fs  (%.2fM ops/s)"
      % (format(term.op_counter, ","), dt, term.op_counter / dt / 1e6))
print("")

# ---- controls ---------------------------------------------------------------------------------
tot = sum(h.hist.values())
ok_sum = tot == term.op_counter
ok_pic = slow_pic == fast_pic
ok_ops = term.op_counter == fast_ops
print("CONTROL 1 (hook saw every op): %s recorded vs %s executed  %s"
      % (format(tot, ","), format(term.op_counter, ","), "ok" if ok_sum else "!! VACUOUS"))
print("CONTROL 2 (same op count)    : profiled %s vs fast %s  %s"
      % (format(term.op_counter, ","), format(fast_ops, ","), "ok" if ok_ops else "!! DIFFER"))
print("CONTROL 3 (same picture)     : %s"
      % ("BYTE-EXACT  ok" if ok_pic else "!! the profiler CHANGED the frame"))
print("")

wpb = (1 << BSHIFT) // W
print("top %d buckets (%s words each), by ops executed:" % (args.top, format(wpb, ",")))
print("%-14s %-14s %14s %8s" % ("bucket", "word range", "ops", "share"))
for b, n in h.hist.most_common(args.top):
    lo = (b << BSHIFT) // W
    print("%-14s %-14s %14s %7.2f%%"
          % (hex(b << BSHIFT), "%s.." % format(lo, ","), format(n, ","), 100.0 * n / tot))
print("")
print("buckets touched: %s   (ops are spread over %s of the image)"
      % (format(len(h.hist), ","), format(len(h.hist) * wpb, ",") + " words"))

if args.out:
    Path(args.out).write_text(json.dumps({
        "fjm": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "viewpoint": [args.vx, args.vy, args.va], "bucket_bits": BSHIFT,
        "op_counter": term.op_counter, "hist": {str(k): v for k, v in h.hist.items()},
    }), encoding="utf-8")
    print("histogram -> %s" % args.out)

ok = ok_sum and ok_pic and ok_ops
print("")
print("ca2_profile: %s" % ("PASS" if ok else "FAIL (a control failed)"))
sys.exit(0 if ok else 1)
