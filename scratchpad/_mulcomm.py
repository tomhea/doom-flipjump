"""IS `hex.fixed_mul_lo 8, 4` ACTUALLY COMMUTATIVE? A direct test, seconds not minutes.

The M14-perf row-rule swaps assumed it is -- the macro sign-extends BOTH operands to n+f and the
truncated schoolbook rows compute (a*b) mod 16^(n+f), which is symmetric on paper. The gate says
otherwise (1766 / 17 / 8 px differ), so the assumption gets tested rather than re-argued.

Feeds real operand pairs of the shape the swapped call sites use:
  world_h = ceil_h<<16 - viewz   (integer<<16, low 4 nibbles zero, often NEGATIVE)
  scale                          (a dense positive 16.16)
and prints fixed_mul_lo(a,b) vs fixed_mul_lo(b,a) for each.
"""
import struct
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj                                                     # noqa: E402
from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402
from doomfj.harness import W                                              # noqa: E402

# (a, b) pairs: world_h-like (integer<<16, signed) x scale-like (dense positive 16.16)
PAIRS = [
    ((-104 << 16) & 0xFFFFFFFF, 0x00012345),
    ((-104 << 16) & 0xFFFFFFFF, 0x0004ABCD),
    ((56 << 16) & 0xFFFFFFFF, 0x00012345),
    ((-8 << 16) & 0xFFFFFFFF, 0x7FFF0000),
    ((-8 << 16) & 0xFFFFFFFF, 0x0000FFFF),
    ((128 << 16) & 0xFFFFFFFF, 0x00034567),
    (0xFFFFFFFF, 0x00012345),
    ((-1 << 16) & 0xFFFFFFFF, 0x80000001),
]

lines = ["stl.startup_and_init_all", "hex.input 1, wmagic"]
for i, (a, b) in enumerate(PAIRS):
    lines += [f"hex.set 8, ca{i}, {a}", f"hex.set 8, cb{i}, {b}",
              f"hex.fixed_mul_lo 8, 4, r{i}, ca{i}, cb{i}",     # as written today
              f"hex.fixed_mul_lo 8, 4, s{i}, cb{i}, ca{i}",     # operands swapped
              f"hex.print_as_digit 8, r{i}, 0", "stl.output 10",
              f"hex.print_as_digit 8, s{i}, 0", "stl.output 10"]
lines.append("stl.loop")
lines.append("wmagic: hex.vec 2")
for i in range(len(PAIRS)):
    lines += [f"ca{i}: hex.vec 8", f"cb{i}: hex.vec 8", f"r{i}: hex.vec 8", f"s{i}: hex.vec 8"]

tmp = Path(tempfile.mkdtemp())
src = tmp / "m.fj"
src.write_text("\n".join(lines) + "\n", encoding="utf-8")
out = tmp / "m.fjm"
fj.assemble([(ROOT / "src/fj/fixed_point.fj").resolve(), src.resolve()], out,
            memory_width=W, print_time=False)
io = FixedIO(bytes([0xD0]))
fj.run(out, io_device=io, print_time=False, print_termination=False)
vals = [v for v in io.get_output(allow_incomplete_output=True).decode().split("\n") if v]

bad = 0
print(f"{'a':>10} {'b':>10} {'fml(a,b)':>10} {'fml(b,a)':>10}")
for i, (a, b) in enumerate(PAIRS):
    r, s = vals[2 * i], vals[2 * i + 1]
    same = r == s
    bad += not same
    print(f"{a:#010x} {b:#010x} {r:>10} {s:>10}  {'same' if same else '!! DIFFER'}")
print(f"\n{'COMMUTATIVE on all pairs' if not bad else f'!! NOT COMMUTATIVE on {bad}/{len(PAIRS)}'}")
