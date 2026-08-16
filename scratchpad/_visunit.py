"""M14.5 §3.3 — does the VISIBILITY guard read the byte the host sent?

The guard the emitter now bakes at every vanishable call site is

    hex.if0 1, thvis + slot*2*dw, <skip>

against an array filled by `rep(n, i) hex.input 1, thvis + i*2*dw`. Two assumptions in that pair,
and CLAUDE.md rule 3 / handoff trap 2 both say a baked address is only safe where shipped code
already bakes the same stride:

  Q1  does `hex.input 1` at a COMPILE-TIME offset of `i*2*dw` land byte i in slot i?
  Q2  does a 1-NIBBLE test at that address see the byte's LOW nibble (so 1 = draw, 0 = hide)?

⚠ This is the whole reason it is checked in 10 seconds here rather than in a 25-minute build: get
the nibble order wrong and every vanishable sprite silently disappears.

    python scratchpad/_visunit.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402
from doomfj.harness import W                                              # noqa: E402

N = 6
FED = [1, 0, 1, 1, 0, 1]          # what the host sends: 1 = draw, 0 = hidden

lines = ["stl.startup_and_init_all", "hex.input 1, magic",
         f"rep({N}, i) hex.input 1, thvis + i*2*dw"]
for i in range(N):
    # exactly the shape subsector_action emits, printing which branch it took
    lines += [f"hex.if0 1, thvis + {i}*2*dw, hid{i}",
              f"stl.output 49", f";done{i}",                 # '1' = drew it
              f"hid{i}:", f"stl.output 48",                  # '0' = skipped it
              f"done{i}:"]
lines += ["stl.output 10", "stl.loop",
          "magic: hex.vec 2", f"thvis: hex.vec {2 * N}"]

tmp = Path(tempfile.mkdtemp())
src = tmp / "v.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "v.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]) + bytes(FED))
fj.run(out, io_device=io, print_time=False, print_termination=False)
got = io.get_output().decode().strip()
want = "".join(str(v) for v in FED)
print(f"fed  {want}\nread {got}   {'OK' if got == want else '!! MISMATCH'}")
sys.exit(0 if got == want else 1)
