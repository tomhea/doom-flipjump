"""Where does `ptr_index` + `write_byte` actually PUT the byte? Print the array nibble by nibble.

`_ssheadunit.py` says the baked form `sshead + s*2*dw` does not read what bind_things wrote, while
bind_things' own comment proposes exactly that address for a compile-time clear. One of the two is
wrong, and guessing again is how trap 2 happened. So: write ONE known value at ONE known index and
dump every nibble of the array.

    python scratchpad/_ssheadprobe.py
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

N = 8            # entries
IDX = 5          # write here
VAL = 0x12

lines = ["stl.startup_and_init_all", "hex.input 1, magic",
         f"hex.set w/4, ix, {IDX}",
         "hex.set w/4, base, arr",
         "hex.ptr_index ptr, base, ix",
         f"hex.set 2, val, {VAL}",
         "hex.write_byte ptr, val",
         # dump every nibble as a hex digit (VAL is chosen so both nibbles are digits)
         f"rep({2 * N}, i) hex.print_as_digit 1, arr + i*dw, 0",
         "stl.output 10", "stl.loop",
         "magic: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
         "val: hex.vec 2", f"arr: hex.vec {2 * N}"]

tmp = Path(tempfile.mkdtemp())
src = tmp / "p.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "p.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]))
fj.run(out, io_device=io, print_time=False, print_termination=False)
dump = io.get_output().decode().strip().splitlines()[0]
back = "-"
print(f"wrote {VAL} at index {IDX} via ptr_index+write_byte")
print(f"array nibbles : {dump}")
print(f"read back     : {back}")
at = [i for i, c in enumerate(dump) if c != "0"]
print(f"non-zero nibble offsets: {at}")
if at:
    print(f"=> the entry stride is {at[0] / IDX if IDX else '?'} nibble(s) per index "
          f"(baked form would be `arr + s*{at[0] // IDX if IDX else 1}*dw`)")
