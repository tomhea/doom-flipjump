"""M14.5 section 3.2 — is `sshead + s*2*dw` the address `ptr_index` + `read_byte` reaches?

The leaf wants to test its own list head at a COMPILE-TIME address instead of building a pointer,
because it knows `s`. That is an ASSUMED STRIDE, and handoff-m14_5.md trap 2 records the last time
one was assumed: `thnext + i*2*dw` failed the gate. So this writes the array exactly the way
`sim.bind_things` writes it -- `hex.set` the base, `hex.ptr_index` by the subsector index,
`hex.write_byte` -- and then reads every entry back through the BAKED form the emitter would emit:

    hex.if0 2, arr + s*2*dw, <empty>

A mismatch here is a 25-minute build and a gate failure; a match is 10 seconds.

    python scratchpad/_ssheadunit.py
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

N = 8
HEADS = [0, 3, 0, 1, 0, 0, 12, 5]        # what bind_things would leave: 0 = empty, else t+1

lines = ["stl.startup_and_init_all", "hex.input 1, magic"]
# write the array the way sim.bind_things does: base + ptr_index(index) + write_byte
for i, v in enumerate(HEADS):
    if not v:
        continue                          # 0 is the zero-init sentinel; bind_things never writes it
    lines += [f"hex.set w/4, ix, {i}",
              "hex.set w/4, base, arr",
              "hex.ptr_index ptr, base, ix",
              f"hex.set 2, val, {v}",
              "hex.write_byte ptr, val"]
# ... and read every entry back at the BAKED address the leaf would use
for i in range(N):
    lines += [f"hex.if0 2, arr + {i}*2*dw, empty{i}",
              "stl.output 49", f";done{i}",          # '1' = the leaf has a list
              f"empty{i}:", "stl.output 48",         # '0' = empty, skip the whole pass
              f"done{i}:"]
lines += ["stl.output 10", "stl.loop",
          "magic: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
          "val: hex.vec 2", f"arr: hex.vec {2 * N}"]

tmp = Path(tempfile.mkdtemp())
src = tmp / "s.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "s.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]))
fj.run(out, io_device=io, print_time=False, print_termination=False)
got = io.get_output().decode().strip()
want = "".join("1" if v else "0" for v in HEADS)
print(f"heads {HEADS}\nwant  {want}\nread  {got}   {'OK' if got == want else '!! MISMATCH'}")
sys.exit(0 if got == want else 1)
