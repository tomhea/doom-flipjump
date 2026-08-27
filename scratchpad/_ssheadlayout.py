"""THE `sshead` LAYOUT, settled: stride AND write width, in one aligned scan.

Two earlier probes disagreed. `_ssheadaddr.py` (2-nibble tests) put a value written at index 5 on
nibble 5 -- a ONE-nibble stride, which would make neighbouring entries overlap. `_ssheadoverlap.py`
(read_byte at the neighbour) saw no overlap. Both cannot be true, and the difference decides what a
leaf may bake, so this measures the two facts separately and with the SAME aligned output method:

  * write a 1-NIBBLE value (9) at index 5  -> which nibbles light up?
  * write a 2-NIBBLE value (0x12) at index 5 -> which nibbles light up?

The first answers "where does entry s START", the second answers "how wide is it", and together
they give the stride. Every probe line is `hex.if0 1, arr + k*dw` -- the exact form a baked leaf
test would use -- and prints one whole character, so FixedIO never sees a partial byte (which is
what made the print_as_digit version of this fail).

    python scratchpad/_ssheadlayout.py
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

SCAN = 24


def scan(idx, val):
    """write `val` at `idx` through bind_things' accessor, then report every non-zero nibble"""
    lines = ["stl.startup_and_init_all", "hex.input 1, magic",
             f"hex.set w/4, ix, {idx}", "hex.set w/4, base, arr",
             "hex.ptr_index ptr, base, ix",
             f"hex.set 2, val, {val}", "hex.write_byte ptr, val"]
    for k in range(SCAN):
        lines += [f"hex.if0 1, arr + {k}*dw, z{k}", "stl.output 49", f";n{k}",
                  f"z{k}:", "stl.output 48", f"n{k}:"]
    lines += ["stl.output 10", "stl.loop",
              "magic: hex.vec 2", "ix: hex.vec w/4", "base: hex.vec w/4", "ptr: hex.vec w/4",
              "val: hex.vec 2", f"arr: hex.vec {SCAN + 8}"]
    tmp = Path(tempfile.mkdtemp())
    src = tmp / "l.fj"
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = tmp / "l.fjm"
    fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
                memory_width=W, print_time=False)
    io = FixedIO(bytes([0xD0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    s = io.get_output().decode().strip()
    return s, [k for k, c in enumerate(s) if c == "1"]


for idx in (0, 1, 5):
    s1, at1 = scan(idx, 0x9)          # one nibble set (low only)
    s2, at2 = scan(idx, 0x12)         # both nibbles set
    print(f"index {idx}: 1-nibble value 0x09 -> nibbles {at1}")
    print(f"index {idx}: 2-nibble value 0x12 -> nibbles {at2}")
    if at1 and at2:
        print(f"   entry starts at nibble {min(at2)}, occupies {len(at2)} nibble(s) "
              f"=> stride {min(at2) / idx if idx else 'n/a'} per index")
