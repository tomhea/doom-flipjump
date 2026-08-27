"""M2 rung 1 -- can the bands walk address MORE THAN 65,536 half-lists?

`generate_bands_walk_fj(lists, *, index_nibbles=4)` is the only thing that fixes the "65,536
band-index cap" both M2 (doors) and M4 (three levels) are budgeted against: it raises when
`4*index_nibbles` cannot address `pad`. This builds a REAL walk past that cap with 5 nibbles,
assembles it, and DISPATCHES INTO IT -- because "it should work" is not evidence.

R5: EVERY ENTRY, AND TWICE EACH. The first version of this probe dispatched five hand-picked ids
and stopped. R5 exists because a generated table's failure modes are per-entry (a wrong handler
body) and per-REPEAT (a result register or in-table jumper that is not cleaned, so the SECOND
dispatch to an id misbehaves while the first looks perfect). A five-id single-shot probe cannot see
either, and this probe is the whole evidence for a cap that two milestones' budgets now rest on.
So the program walks the entire id space in a runtime loop, calling `vpb_walk` TWICE per id, and
every emitted byte is checked.

    python scratchpad/m2_widen.py [--n 70000]

CONTROLS
  C1  the same list count at index_nibbles=4 must RAISE (the cap is real, not imagined).
  C2  every id's FIRST dispatch emits that id's own pairs -- the failure mode of a too-narrow
      index is aliasing, which is silent. The ids either side of the boundary (65,535 / 65,536)
      carry DIFFERENT shapes on purpose: a 4-nibble truncation would turn 65,536 into id 0.
  C3  every id's SECOND dispatch emits the same again -- computed independently of C2, over the
      repeat half of the stream. (The first version printed C2's own verdict under a C3 label, so
      it could not fail on its own. That is the defect R9 exists to catch, in the file whose job
      is to carry a negative control.)
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

# ---- the program: EVERY id, dispatched TWICE ---------------------------------------------------
# a runtime loop, so one assemble covers the whole id space. `vq_lo`/`vq_hi` open the window wide
# so every pair emits unclamped, and the two dispatches per id are adjacent -- if the table does
# not clean itself, the second one is where it shows.
program = "\n".join([
    "stl.startup_and_init_all",
    "vql_load qlo",
    "vqh_load qhi",
    "hex.set %d, pidx, 0" % args.nibbles,
    "hex.set 8, cnt, 0",
    "hex.set 8, lim, %d" % args.n,
    "loop:", "hex.cmp 8, cnt, lim, body, done, done",
    "body:",
    "    vpb_walk pidx",            # first dispatch
    "    vpb_walk pidx",            # ... and again, same id: the call-twice check
    "    hex.inc %d, pidx" % args.nibbles,
    "    hex.inc 8, cnt",
    "    ;loop",
    "done:", "stl.loop",
    "qlo: hex.vec 2, 0",
    "qhi: hex.vec 2, 200",
    "pidx: hex.vec %d" % args.nibbles,
    "cnt: hex.vec 8", "lim: hex.vec 8",
    code,
]) + "\n"

tmp = ROOT / "build" / "m2widen"
tmp.mkdir(parents=True, exist_ok=True)
src = tmp / "widen.fj"
src.write_text(program, encoding="utf-8")
out = tmp / "widen.fjm"
consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
t = time.perf_counter()
fj.assemble([consts.resolve(), src.resolve()], out, memory_width=W, print_time=False)
print("   assembled in %.0f s; running %d ids x 2 dispatches ..." % (time.perf_counter() - t, args.n))
io = FixedIO(b"")
t = time.perf_counter()
fj.run(out, io_device=io, print_time=False, print_termination=False)
got = io.get_output(allow_incomplete_output=True)
print("   ran in %.0f s, %s bytes emitted" % (time.perf_counter() - t, format(len(got), ",")))

# ---- C2 / C3: split the stream into the FIRST and SECOND dispatch of each id -------------------
first_bad, second_bad, at = [], [], 0
for k, pairs in enumerate(lists):
    want = bytes(b for pair in pairs for b in pair)
    got_1 = got[at:at + len(want)]; at += len(want)
    got_2 = got[at:at + len(want)]; at += len(want)
    if got_1 != want:
        first_bad.append(k)
    if got_2 != want:
        second_bad.append(k)

complete = at == len(got)
print("")
print("C2 every id's FIRST dispatch emits its own list ... %s"
      % ("ok -- all %d" % args.n if not first_bad
         else "!! %d WRONG, e.g. %s" % (len(first_bad), first_bad[:5])))
print("C3 every id's SECOND dispatch emits it again ..... %s"
      % ("ok -- all %d" % args.n if not second_bad
         else "!! %d WRONG on the REPEAT, e.g. %s" % (len(second_bad), second_bad[:5])))
print("   (C3 is computed from the repeat half of the stream, independently of C2)")
print("   stream length accounted for exactly: %s" % ("yes" if complete else "NO -- %d left" % (len(got) - at)))
print("   boundary ids 65,535 and 65,536 carry DIFFERENT shapes: %s"
      % ("yes" if lists[65535] != lists[65536] else "NO -- C2 cannot see a 4-nibble truncation"))

ok = c1 and not first_bad and not second_bad and complete and lists[65535] != lists[65536]
print("")
print("VERDICT: %s" % ("PASS -- the 65,536 cap is index_nibbles, and 5 nibbles clears it"
                       if ok else "FAIL"))
sys.exit(0 if ok else 1)
