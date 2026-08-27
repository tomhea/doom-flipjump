"""WHICH compile-time address holds `sshead[s]`? Scan for it instead of assuming.

`bind_things` writes the head with `hex.set base; hex.ptr_index ptr, base, s; hex.write_byte ptr`.
The leaf wants to test the same entry at a BAKED address. Two earlier probes disagreed about the
stride, so this writes one entry and then tests EVERY candidate nibble offset with the exact form
the emitter would bake (`hex.if0 2, arr + k*dw`), printing one aligned character per offset.

The answer is the offset that lights up, divided by the index written.

    python scratchpad/_ssheadaddr.py
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

IDX, VAL, SCAN = 5, 9, 24

lines = ["stl.startup_and_init_all", "hex.input 1, magic",
         f"hex.set w/4, ix, {IDX}", "hex.set w/4, base, arr",
         "hex.ptr_index ptr, base, ix",
         f"hex.set 2, val, {VAL}", "hex.write_byte ptr, val"]
for k in range(SCAN):
    lines += [f"hex.if0 2, arr + {k}*dw, z{k}", "stl.output 49", f";n{k}",
              f"z{k}:", "stl.output 48", f"n{k}:"]
lines += ["stl.output 10", "stl.loop",
          "magic: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
          "val: hex.vec 2", f"arr: hex.vec {SCAN + 8}"]

tmp = Path(tempfile.mkdtemp())
src = tmp / "a.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "a.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]))
fj.run(out, io_device=io, print_time=False, print_termination=False)
got = io.get_output().decode().strip()
hits = [k for k, c in enumerate(got) if c == "1"]
print(f"wrote {VAL} at index {IDX}; `hex.if0 2, arr + k*dw` sees it at k = {hits}")
print(f"scan: {got}")
if hits:
    print(f"=> baked form is `sshead + s*{hits[0] // IDX}*dw`  (stride {hits[0] / IDX} nibbles)")
