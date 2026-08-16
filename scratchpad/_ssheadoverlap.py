"""Do `sshead` entries OVERLAP? A 2-nibble value at a 1-nibble stride says they must.

`_ssheadprobe.py` measured `hex.ptr_index` at ONE NIBBLE per index, and `hex.write_byte` writes a
2-nibble value. `sim.bind_things` indexes `sshead` by the raw subsector number, so entry s occupies
nibbles s and s+1 -- and entry s+1 starts at nibble s+1. If a head's value exceeds 15 (thing index
15 and up, since the lists store t+1), its HIGH nibble lands in its neighbour's slot.

This writes 0x10 (thing index 15) at index 3 and then reads index 4. A non-zero read there means a
leaf with no things is told it has one -- and the neighbour's list head is corrupted.

Output: two characters, "<entry3 non-zero><entry4 non-zero>". Expect "10" if entries are
independent, "11" if they overlap.

    python scratchpad/_ssheadoverlap.py
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


def probe(idx, val, read_idx):
    lines = ["stl.startup_and_init_all", "hex.input 1, magic",
             f"hex.set w/4, ix, {idx}", "hex.set w/4, base, arr",
             "hex.ptr_index ptr, base, ix",
             f"hex.set 2, val, {val}", "hex.write_byte ptr, val",
             # read entry `idx` back through the same accessor
             "hex.zero 2, val", "hex.read_byte val, ptr",
             "hex.if0 2, val, a0", "stl.output 49", ";a1", "a0:", "stl.output 48", "a1:",
             # ... and entry `read_idx`, which nothing wrote
             f"hex.set w/4, ix, {read_idx}", "hex.set w/4, base, arr",
             "hex.ptr_index ptr, base, ix",
             "hex.zero 2, val", "hex.read_byte val, ptr",
             "hex.if0 2, val, b0", "stl.output 49", ";b1", "b0:", "stl.output 48", "b1:",
             "stl.output 10", "stl.loop",
             "magic: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
             "val: hex.vec 2", "arr: hex.vec 32"]
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "o.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp / "o.fjm"
    fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(bytes([0xD0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output().decode().strip()


small = probe(3, 9, 4)          # one nibble: cannot spill
big = probe(3, 0x10, 4)         # two nibbles: spills iff the stride is 1
print(f"value 0x09 at index 3 -> entry3,entry4 non-zero = {small}")
print(f"value 0x10 at index 3 -> entry3,entry4 non-zero = {big}")
print("OVERLAP" if big.startswith("11") else "entries are independent")
