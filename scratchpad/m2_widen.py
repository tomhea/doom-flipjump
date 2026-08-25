"""M2 rung 1 -- can the bands walk address MORE THAN 65,536 half-lists?

`generate_bands_walk_fj(lists, *, index_nibbles=4)` is the only thing that fixes the "65,536
band-index cap" both M2 (doors) and M4 (three levels) are budgeted against: it raises when
`4*index_nibbles` cannot address `pad`. This builds a REAL walk past that cap with 5 nibbles,
assembles it, and DISPATCHES INTO IT -- because "it should work" is not evidence.

    python scratchpad/m2_widen.py [--n 70000]

CONTROLS
  C1  the same list count at index_nibbles=4 must RAISE (the cap is real, not imagined).
  C2  a dispatch to an id ABOVE 65,535 must return that id's OWN pairs, not another's -- the
      failure mode of a too-narrow index is aliasing, which is silent. The DISCRIMINATING pair is
      65,535 vs 65,536: they are given different shapes, so a 4-nibble truncation would turn
      65,536 into id 0 and emit id 0's list. Probing only ids above the cap would not show that.
  C3  a dispatch to a LOW id must still be right afterwards, so the widening did not just move
      the breakage.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402
from doomfj.config import Config                                          # noqa: E402
from doomfj.harness import W                                              # noqa: E402
from doomfj.lut_generator import generate_bands_walk_fj                   # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--n", type=int, default=70000, help="half-lists to bake (must exceed 65,536)")
ap.add_argument("--nibbles", type=int, default=5)
args = ap.parse_args()
assert args.n > 65536, "the point is to pass the 4-nibble cap"

# a handful of distinct shapes, cycled: the SWITCH TABLE and the per-id thunks scale with n (what
# the cap is about), while the handler BODIES stay few (what would make this slow to assemble).
SHAPES = [[(10, 0x41)], [(20, 0x42), (40, 0x43)], [(30, 0x44)],
          [(15, 0x45), (25, 0x46), (35, 0x47)], [(50, 0x48)], [(60, 0x49), (70, 0x4A)]]
lists = [SHAPES[k % len(SHAPES)] for k in range(args.n)]

# ---- C1: the cap is real ----------------------------------------------------------------------
try:
    generate_bands_walk_fj(lists, index_nibbles=4)
    print("C1 index_nibbles=4 at n=%d -> ACCEPTED  !! the cap is not where we think it is" % args.n)
    c1 = False
except ValueError as e:
    print("C1 index_nibbles=4 at n=%d -> refused: %s" % (args.n, e))
    c1 = True

t = time.perf_counter()
code = generate_bands_walk_fj(lists, index_nibbles=args.nibbles)
print("   generated %d half-lists at %d nibbles: %.1f MB of fj, %.0f s"
      % (args.n, args.nibbles, len(code) / 1e6, time.perf_counter() - t))

PROBE_IDS = [args.n - 1, 65536, 65535, 7, 0]


def program(idx):
    return "\n".join([
        "stl.startup_and_init_all",
        "vql_load qlo",
        "vqh_load qhi",
        "vpb_walk pidx",
        "stl.loop",
        "qlo: hex.vec 2, 0",            # window [0, 200): every pair emits unclamped
        "qhi: hex.vec 2, 200",
        "pidx: hex.vec %d, %d" % (args.nibbles, idx),
        code,
    ]) + "\n"


ok = True
tmp = Path(ROOT / "build" / "m2widen"); tmp.mkdir(parents=True, exist_ok=True)
for idx in PROBE_IDS:
    src = tmp / ("w%d.fj" % idx)
    src.write_text(program(idx), encoding="utf-8")
    out = tmp / ("w%d.fjm" % idx)
    t = time.perf_counter()
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
    asm = time.perf_counter() - t
    io = FixedIO(b"")
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True)
    want = bytes(b for pair in lists[idx] for b in pair)
    same = got == want
    ok &= same
    print("   id %6d -> %-22s want %-22s %s   (asm %.0f s)"
          % (idx, got.hex(), want.hex(), "ok" if same else "!! WRONG LIST", asm))

print("")
print("C2 an id above 65,535 dispatches to its OWN list ... %s"
      % ("ok" if ok else "!! FAILED -- the widening does not work"))
print("C3 a low id is still right afterwards ............. %s" % ("ok" if ok else "!! FAILED"))
print("")
print("VERDICT: %s" % ("PASS -- the 65,536 cap is index_nibbles, and 5 nibbles clears it"
                       if (ok and c1) else "FAIL"))
sys.exit(0 if (ok and c1) else 1)
