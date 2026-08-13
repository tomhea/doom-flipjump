"""The two things bind_things still needs to know, on a WIRE-FILLED array.

`hex.input` fills a hex.vec (nibble-per-slot); `ptr_index` + `read_byte` addresses something else
(_ptrunit.py). Positions already dodge this: nibble offset = index*16 via `shl_hex 1`, then
`read_hex`. So:

  Q1  does `ptr_index` at a NIBBLE offset + `read_hex 4` read entry i of a wire-filled array?
  Q2  does `write_hex 4, ptr, src` write it back so `read_hex 4` returns it?
      (fj-lessons says the 3-arg overload once wrote a SINGLE nibble -- verify, do not assume.)

Entries are 16 nibbles / 8 bytes, so the offset is `shl_hex 1` -- the exact accessor thing_load
uses and phase 1 proved byte-exact.

    python scratchpad/_ptrunit2.py
"""
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT): sys.path.insert(0, str(q))

import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.harness import W

N = 4
FED = [0x0111, 0x0222, 0xFFFF, 0x0444]          # 16-bit values, 8 bytes per entry on the wire


def acc(i_reg):
    """the proven accessor: nibble offset = index * 16, then ptr_index"""
    return [f"hex.mov w/4, off, {i_reg}", "hex.shl_hex w/4, 1, off",
            "hex.set w/4, base, arr", "hex.ptr_index ptr, base, off"]


lines = ["stl.startup_and_init_all", "hex.input 1, magic", f"hex.input {8*N}, arr"]
# Q1: read each entry's low 4 nibbles
for i in range(N):
    lines += [f"hex.set w/4, ix, {i}"] + acc("ix") + [
        "hex.zero 4, v", "hex.read_hex 4, v, ptr",
        "hex.print_as_digit 4, v, 0", "stl.output 10"]
# Q2: write 0x1234 into entry 2, then read every entry again
lines += [f"hex.set w/4, ix, 2"] + acc("ix") + [
    "hex.set 4, v, 0x1234", "hex.write_hex 4, ptr, v"]
for i in range(N):
    lines += [f"hex.set w/4, ix, {i}"] + acc("ix") + [
        "hex.zero 4, v", "hex.read_hex 4, v, ptr",
        "hex.print_as_digit 4, v, 0", "stl.output 10"]
lines += ["stl.loop",
          "magic: hex.vec 2", "off: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
          "ix: hex.vec w/4", "v: hex.vec 4", f"arr: hex.vec {16*N}"]

tmp = Path(tempfile.mkdtemp()); src = tmp / "p.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "p.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]) + b"".join(struct.pack("<Q", v) for v in FED))
fj.run(out, io_device=io, print_time=False, print_termination=False)
vals = [v for v in io.get_output(allow_incomplete_output=True).decode().split("\n") if v]
before, after = vals[:N], vals[N:2 * N]
want = [f"{v:04x}" for v in FED]
want_after = list(want); want_after[2] = "1234"
print(f"Q1 read  : {before}")
print(f"   want  : {want}   {'OK' if before == want else 'MISMATCH'}")
print(f"Q2 after : {after}")
print(f"   want  : {want_after}   {'OK' if after == want_after else 'MISMATCH'}")
print()
if before == want and after == want_after:
    print("=> both work: nibble-offset ptr_index + read_hex/write_hex is the accessor to use")
elif before == want:
    print("=> READ works, WRITE does not -- write_hex cannot be used for the round-trip write-back")
else:
    print("=> READ does not work either; the wire array needs a different accessor entirely")
