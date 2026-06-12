# doom-flipjump

DOOM-related FlipJump tooling, moved out of the [flipjump](https://github.com/tomhea/flipjump)
core repo to keep that one purely about the language and toolchain.

## Contents

- **`lut_generator.py`** — a host-side generator that emits FlipJump source for lookup
  tables (sine tables, byte LUTs, ...). Pure Python (`math` + `typing` only), no FlipJump
  runtime dependency. Tested by `tests/unit/test_lut_generator.py` (host-reference
  fixtures over many indices, including the first/last entries and wrap boundaries).

- **`stl/hex/fixed_point.fj`** — signed Q-format fixed-point STL macros
  (`hex.fixed_mul` / `hex.fixed_div` / `hex.mul_const`, and `hex.read_table` /
  `hex.read_table_byte` for LUT access). These build on the flipjump standard library's
  `hex.*` macros, so assembling them needs flipjump's stl alongside this file. The
  `hex.read_table` / `hex.read_table_byte` *entry-layout contract* is documented on the
  macros themselves.

- **`programs/hexlib_tests/fixed_point/`** + **`tests/inout/hexlib_tests/fixed_point/`** —
  the compile/run tests for those macros (program + expected output), in the flipjump
  hexlib-test format.

All of this was developed in the flipjump repo during the 1.5.0 work and relocated here
verbatim; wire it into this repo's own test harness as needed.
