"""Isolate the four pointer constructs sim.bind_things uses that its working siblings do not."""
import sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT/"src", ROOT): sys.path.insert(0, str(q))
import flipjump as fj
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from doomfj.harness import W
prog = "\n".join([
    "stl.startup_and_init_all",
    "hex.set 2, mk, 0x11", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    # 1. a pointer to a label, 2. ptr_index with a 4-NIBBLE index, 3. write_hex, 4. read_byte
    "hex.set 4, ix, 3",
    "hex.set 2, mk, 0x1a", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    "hex.set w/4, base, arr",
    "hex.set 2, mk, 0x1b", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    "hex.ptr_index ptr, base, ix",
    "hex.set 2, mk, 0x1c", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    "hex.set 2, val, 0xAB",
    "hex.set 2, mk, 0x1d", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    "hex.write_byte ptr, val",
    "hex.set 2, mk, 0x22", "hex.print_as_digit 2, mk, 0", "stl.output 10",
    "hex.set w/4, base, arr",
    "hex.ptr_index ptr, base, ix",
    "hex.read_byte got, ptr",
    "hex.print_as_digit 2, got, 0", "stl.output 10",
    "stl.loop",
    "mk: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
    "val: hex.vec 2", "got: hex.vec 2",
    "arr: hex.vec 16",
]) + "\n"
tmp = Path(tempfile.mkdtemp()); src = tmp/"p.fj"; src.write_text(prog, encoding="utf-8")
out = tmp/"p.fjm"
fj.assemble([(ROOT/"src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(b"")
t = fj.run(out, io_device=io, print_time=False, print_termination=False)
print("ops", t.op_counter, "OUT:", repr(io.get_output(allow_incomplete_output=True).decode()))
