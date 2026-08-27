"""Does `hex.input`'s layout match what `ptr_index` + `read_byte` addresses?

That is the ONE question. `sim.bind_things` reads its per-leaf lists with ptr_index + read_byte and
those are written by write_byte, so they round-trip through the same layout and work (132/132). The
new `thss` cache is filled by `hex.input` instead, and it reads back garbage -- the dirty test never
fires, so COLD came out CHEAPER than WARM.

Two arrays, same declaration, filled two different ways, read the same way:
  A  written by ptr_index + write_byte      (what sshead/thnext do today)
  B  filled by `hex.input n, arrB`          (what the wire does)

If A round-trips and B does not, the wire's layout is not the byte-array layout, which is the same
class of bug as the position array needing a hex.vec rather than a packed table.

    python scratchpad/_ptrunit.py
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT): sys.path.insert(0, str(q))

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.harness import W

N = 5
FED = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4]

lines = ["stl.startup_and_init_all", "hex.input 1, magic", f"hex.input {N}, arrB"]
# A: write 0xB0+i at index i, through ptr_index + write_byte
for i in range(N):
    lines += [f"hex.set w/4, q, arrA", f"hex.set w/4, ix, {i}", "hex.ptr_index p, q, ix",
              f"hex.set 2, v, {0xB0 + i}", "hex.write_byte p, v"]
# ... then read both arrays back the same way
for name in ("arrA", "arrB"):
    for i in range(N):
        lines += [f"hex.set w/4, q, {name}", f"hex.set w/4, ix, {i}", "hex.ptr_index p, q, ix",
                  "hex.zero 2, v", "hex.read_byte v, p",
                  "hex.print_as_digit 2, v, 0", "stl.output 10"]
lines += ["stl.loop",
          "magic: hex.vec 2", "q: hex.vec w/4", "p: hex.vec w/4", "ix: hex.vec w/4", "v: hex.vec 2",
          f"arrA: hex.vec {2*N}", f"arrB: hex.vec {2*N}"]

tmp = Path(tempfile.mkdtemp()); src = tmp / "p.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "p.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]) + bytes(FED))
fj.run(out, io_device=io, print_time=False, print_termination=False)
vals = [v for v in io.get_output(allow_incomplete_output=True).decode().split("\n") if v]
a, b = vals[:N], vals[N:2 * N]
wa = [f"{0xB0 + i:02x}" for i in range(N)]
wb = [f"{v:02x}" for v in FED]
print(f"A  write_byte -> read_byte : {a}  want {wa}  {'OK' if a == wa else 'MISMATCH'}")
print(f"B  hex.input  -> read_byte : {b}  want {wb}  {'OK' if b == wb else 'MISMATCH'}")
print()
if a == wa and b != wb:
    print("=> CONFIRMED: write_byte/read_byte round-trip, but hex.input writes a DIFFERENT layout.")
    print("   The wire cannot fill an array that ptr_index + read_byte will address.")
elif a == wa and b == wb:
    print("=> both layouts agree; the bind bug is elsewhere.")
else:
    print("=> even the write_byte round-trip fails; ptr_index indexing is not entry-wise here.")
