"""Does the reset NIBBLE-clear any cell that is really a BYTE cell?

THE RISK. In an array a byte written through `hex.write_byte` is ONE cell holding 8 bits at
dbit..dbit+7. A nibble op on such a cell does not clear it, it CORRUPTS it (measured 0xA5 -> 0x22A5)
-- and the result is pixel-identical for a frame or two, so no rendering gate can see it.

`selfreset.py` names three byte arrays explicitly. CR round 2 was right that the MEMBERSHIP of that
list is hand-written while the counts are derived, and that `src/fj/` has ten-plus other
`hex.write_byte` destinations -- all through POINTER registers, so no static rule can name the
arrays they reach.

So check it EMPIRICALLY and generally, over the cells that actually matter: run real frames, and for
every cell the reset would clear with a nibble op, read the value it is left holding. A byte cell
in the nibble set gives itself away by holding a value > 15.

CONTROLS (R9):
  1. VACUITY -- the three KNOWN byte arrays must themselves show values > 15 in the same run. If
     they do not, the probe is not reaching live data and its silence about everything else is
     worthless. This is the control that makes a clean result mean something.
  2. FRAME REALITY -- every frame must run > 1e6 ops, or the wire is wrong and nothing was written.
  3. Several viewpoints, because a cell can be untouched at one and live at another.

    python scratchpad/m1_bytecheck.py [--fjm build/doom_e1m1.fjm]
"""
import argparse
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj import selfreset                                          # noqa: E402
from doomfj.harness import W                                          # noqa: E402

VAL_SHIFT = (W + W.bit_length()) - W

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--view-w", type=int, default=160)
ap.add_argument("--nss", type=int, default=682)
args = ap.parse_args()

# Build the wire the same way m1_gate.py does, from the same repo helpers, so this probe and the
# gate cannot drift apart on what a frame IS.
from doomfj.config import Config                                      # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                         # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                  # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                       # noqa: E402
from doomfj.mapcompiler import bake_bsp                               # noqa: E402
from doomfj.fixedpoint import _signed                                 # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,  # noqa: E402
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots          # noqa: E402
from doomfj.wad import WadFile                                        # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,
                               encode_visibility)                     # noqa: E402

_w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
_art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
_rm = ReferenceModel(Config())
_cmap = bake_bsp(_w, "E1M1")
_dr = [t for t in _w.things("E1M1") if _rm.sprite_art(_art, t.type, {}) is not None]
_bkd = baked_thing_mask(_rm, _cmap, _dr, MONSTER_TYPES)
_NVIS = len(vanishable_slots(_dr, _bkd, VANISHABLE_TYPES))
_RT = [t for t, b in zip(_dr, _bkd) if not b]
_BINDS = encode_bindings([_rm.point_in_subsector(_cmap, t.x, t.y) for t in _RT])
_sp = spawn_state(_w, "E1M1")


def wire(vx, vy, va, keys=0):
    return (encode_feed(vx << 16, vy << 16, va, keys)
            + encode_things([(t.x << 16, t.y << 16) for t in _RT])
            + _BINDS + encode_visibility([1] * _NVIS))


bits = {}
for line in gzip.open(args.labels, "rt", encoding="utf-8"):
    a, t, v = line.rstrip("\n").partition("\t")
    if t:
        bits.setdefault(a, int(v))
words_sorted = sorted(v // W for v in bits.values())

# the cells the reset clears with a NIBBLE op = the set, minus the byte arrays
wset = selfreset.load_restore_set(args.set, bits)
byte_words, known = set(), {}
for name, n in selfreset.byte_arrays(bits, words_sorted, args.view_w, args.nss):
    base = bits[name] // W
    known[name] = [base + 2 * k + 1 for k in range(n)]
    byte_words.update(base + 2 * k + j for k in range(n) for j in (0, 1))
nib_val_words = sorted(x for x in (wset - byte_words) if x % 2)
print("checking %s nibble-cleared cells across %s known byte arrays as the control"
      % (format(len(nib_val_words), ","), len(known)), flush=True)

r = FjmRunner(Path(args.fjm))
assert r.native, "needs the native engine"


def fresh():
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        core.add_segment(s, n)
    for st, vals in r._runs:
        core.set_words(st, vals)
    return core


STATES = [(_signed(_sp.x, 32) >> 16, _signed(_sp.y, 32) >> 16, _sp.angle, 0),
          (664, 291, 0x18000000, 1),
          (1272, -724, 0x40000000, 5),
          (1869, 479, 0x80000000, 0)]

bad, ctl_hits, ok = {}, {k: 0 for k in known}, True
for st in STATES:
    core = fresh()
    scr = StreamScreen(stdin=wire(*st), n_things=len(_RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    t0 = time.perf_counter()
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    name = "(%d,%d,%#x,k=%d)" % st
    if ops <= 1_000_000:
        print("  CONTROL 2 FAILED at %s: only %s ops -- the wire is wrong" % (name, format(ops, ",")))
        ok = False
    for x in nib_val_words:
        v = core.get_word(x) >> VAL_SHIFT
        if v > 15:
            bad.setdefault(x, []).append((name, v))
    for k, ws in known.items():
        ctl_hits[k] += sum(1 for x in ws if (core.get_word(x) >> VAL_SHIFT) > 15)
    print("  %-22s %13s ops  %5.1fs  cells>15 so far: %d"
          % (name, format(ops, ","), time.perf_counter() - t0, len(bad)), flush=True)
    del core

print("")
print("CONTROL 1 (vacuity) -- the KNOWN byte arrays must themselves show values > 15:")
for k, n in ctl_hits.items():
    print("  %-8s %5d cells held a value > 15   %s"
          % (k, n, "ok" if n else "!! THE PROBE IS NOT REACHING LIVE DATA"))
    ok &= bool(n)

print("")
if bad:
    print("!! %d NIBBLE-CLEARED CELLS HELD A VALUE > 15 -- they are BYTE cells and the reset")
    print("   CORRUPTS them. e.g.:")
    for x in sorted(bad)[:8]:
        print("     word %d  %s" % (x, bad[x][:3]))
    ok = False
else:
    print("RESULT: no nibble-cleared cell ever held a value > 15 across %d viewpoints." % len(STATES))
    print("        The three named byte arrays are the only byte arrays in the restore set.")

print("")
print("m1_bytecheck: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
