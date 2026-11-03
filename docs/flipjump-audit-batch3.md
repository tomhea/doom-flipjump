# Whole-stl audit, batch 3: hex/ logics, math_basic, math, shifts, tables_init (origin/1.6.0 = 4117b02)

Reviewed at 4117b02 in the read-only worktree C:/Users/tomhe/Documents/flipjump-audit2. Its `_fjcore.c` equals
flipjump-160's, so flipjump-160's `_fjcore.pyd` was copied next to it. Changed vs origin/main: logics.fj, math.fj,
shifts.fj and tables_init.fj (the chained dance, the `__relocatable__` tables, the new triple_exact_xor and the
sparse_* family). math_basic.fj is the same as on main.

## Tools

All in this folder. Every run went through `heavy.py audit3 --light`, one process at a time.

- **`edge3.py`**: edge values, one program per (group, w).
  - Every result is preset dirty, and every vector sits between two guard hexes that are checked unchanged.
  - The `state` group runs each op alone. The checker's tracer then compares every shared table cell with its image
    value: hex.tables.res and .ret, and the add/sub/or/and jumpers (flip and jump words).
  - `selftest` (R9): a wrong expected value and a dirty state (a set carry) must both be reported. PASS at w=64 and w=32.
- **`exact_mem.py`**: address_and_variable_{,triple_,double_}xor n at n = 3 and 13 (6 at w=32).
  - The address side is read from memory by the tracer, because hex.output cannot read a nibble that is not op-aligned.
  - Negative control: the first run had a 1-bit value shift and reported 26 FAIL per w. After the fix: 0 FAIL.
- **`m3specs.py`**: batch 3's specs for the checker's `cxm.py`. Its `--selftest` PASSes on this tree.
  - 455 rows at w=64, patterns 1 and 5 (align 18). Every row moves by exactly At / As.
  - At w=32 (pattern 1), every convT / convS is equal to w=64's.
  - `show3.py` prints the rows to `show3.txt`.
- **`inits.py`**: the no-sharing space of each init table.
- **`restart_probe.py`**: see "Checked, no finding".
- **`mutants3.py`**: batch 2's runner with batch 3's table, run in `mtree/` (= `git archive 4117b02`).
  - Each mutated file is restored after its run. The tree was verified equal to 4117b02 except for CRLF line endings.
- **`mutants3_unit.py`**: the same mutants run against tests/unit's pool tests.

## Edge runs

- logic, exact, sparse, math, basic, shift and state ran at w=64 and w=32.
- exact, sparse, basic and shift also ran at w=16 (sampled, one case per program).

Everything else passed, among others:

- **Logic**
  - or / and: all 256 (dst, src) pairs.
  - exact_xor with the bit order reversed, and the double / triple / quadrupled_exact_xor forms.
  - The sparse_* family at PAD 16, 32 and 64, at n = 0, 1 and 4, including self-moves.
- **Add / sub**
  - Single add / sub: 10 pairs x carry-in 0/1, checking the result and the carry out.
  - add n / sub n at n = 0, 1, 2, 4 and 16: random values, a carry through every nibble, and 0 - 1.
    - Each case was entered with a SET carry: it was ignored, and the carry was 0 afterwards.
    - Also x + x and x - x.
  - add_shifted / sub_shifted: 8 shapes, including src_n = 0, shift 7, and a carry into and through the inc tail.
  - add_constant / sub_constant: 9 (n, const) pairs x 3 dst values.
  - Every carry macro.
- **Basic and shift**
  - inc / dec / neg / abs at n = 1, 2, 4 and 16; the inc1 / dec1 jumps.
  - sign_extend with dirty high hexes.
  - count_bits at n = 1..16 with a dirty dst; the add_count_bits carries.
  - shl/shr at every shift count 0..n.
- **State**: 16 ops, and every table cell was clean after each one.

## BLOCKING

### B1. add_shifted / sub_shifted / add_constant / sub_constant write PAST dst when the source does not fit

Where: math.fj:26-36, :196-206, :38-47, :208-215, and both `*_hex_shifted_constant` (:55-66, :223-234).

**Cause:**

- The chain adds src_n hexes at dst+hex_shift*dw, whatever dst_n is.
- The tail `rep(dst_n - (src_n + hex_shift), i)` is silently empty when its count is negative.
- main behaves the same.

**Reproducer** (`edge3.py probe 64 32`, with a guard hex after dst):

| call | result |
|---|---|
| `hex.add_constant 2, d, 0x100` | the next hex changes from a to b |
| `hex.sub_constant 2, d, 0x100` | the next hex changes to 9 |
| `hex.sub_constant 4, d, 0x10000` (= 0 mod 16^4) | the next hex changes to 9 |
| `hex.add_shifted 2, 2, d, s, 1` | the next hex changes from a to d |
| `hex.add_constant 2, d, 0x1000` | the run ends in a runtime memory error |

The docs read "dst[:dst_n] += src[:src_n] << (4*hex_shift)" and "dst[:n] += const". hexlib-add_shifted covers only
shapes that fit.

**Smallest fix** (one doc line per macro):

- add_shifted / sub_shifted: `// @Assumes: src_n + hex_shift <= dst_n.`
- the four constant macros: `// @Assumes: const < 16^n.`
- Code alternative for the constant macros: pass `const & ((1<<(4*n))-1)`. It is byte-identical for every const that
  fits.

### B2. `hex.sub_constant n, x, 0` does not assemble, and neither does anything that reaches it

Affected: `stl.call f, 0` (ptrlib.fj:59 sp_sub), `hex.ptr_sub p, 0` and `hex.sp_sub 0` (math.fj:213-215).

- **Cause:** add_constant guards its body with `rep(const!=0, _)`; sub_constant does not.
- **Reproducer** (`edge3.py probe2 64 32`), for all four calls:
  `FlipJumpExprException: ValueError('negative shift count') ... (const >> (leading_lsb_const_zeros & -4))`.
  The controls `stl.call f, 1` and `hex.ptr_add p, 0` run.
- **Smallest fix (1 line):**
  `rep(const!=0, _) .sub.sub_constant_with_leading_zeros n, dst, const, (#(const&(0-const)))-1`,
  plus the doc sentence add_constant already has about the constant.
- **Tests to add:** `hex.sub_constant 4, x, 0` and `stl.call f, 0`.

## MINOR

1. **`xor_zero x, x` leaves x unchanged.**
   - Where: logics.fj:60-68; also xor_zero n, sparse_xor_zero and sparse_xor_zero n.
   - The doc says "dst ^= src; src = 0".
   - Repro: `logic` gives 5 -> 5 and f -> f; `probe3` shows xor_zero 4, x, x keeps 0x1234.
   - Related: double_xor reads src once. `double_xor d, d, s` leaves d; `double_xor s, e, s` gives s = 0 and
     e ^= the old s.
   - Fix: `// dst and src must differ (xor_zero x, x leaves x).`
2. **Partial overlap is undocumented.**
   - Where: xor n, or n, and n, add n, sub n (logics.fj:15-20, :389-395, :439-445; math.fj:16-24, :186-194), and
     sparse_xor n / sparse_mov n (:491-498, :650-660).
   - dst = src + dw is wrong for all five tested ops (`logic`: 5 FAIL per w). sparse_mov 16, 4, b+dw, b turns
     0x12345 into 0x55555.
   - dst = src - dw and dst == src are right, sub included. main behaves the same.
   - Fix: copy hex.mov n's sentence, "Unsafe if dst and src overlap! but safe if they are the exact same address."
3. **n = 0 is unguarded** (`probe`, with guards):

   | call | effect |
   |---|---|
   | `shl_bit 0, d` | shifts the hex BEFORE d (a -> 4) |
   | `shr_bit 0, d` | shifts d[0] |
   | `shl_hex 0, d` / `shr_hex 0, d` | zero a neighbour (only the 3-argument forms state times <= n) |
   | `add_count_bits 0` | adds into d |
   | `sign_extend 4, 0, x` | takes the sign from the hex before x, giving ffff |

   Fix: `// @Assumes: n >= 1.` at shifts.fj:5, :14, :23, :42 and math_basic.fj:10, and
   `// @Assumes: signed_n >= 1.` at math_basic.fj:211.
4. **`count_bits n, dst, x` with dst overlapping x** (math_basic.fj:77-86).
   - Repro (`probe3`): count_bits 4, x, x on 0x00ff gives 0x0000.
   - With dst = x + 2dw, the run ends by jumping below 2w (`ip<2w`), at w=64 and w=32.
   - add_count_bits documents its own alias rule; count_bits does not.
   - Fix: `// @Assumes: dst and x do not overlap.`
5. **add_constant / sub_constant docs use `hex_shift` and `dst_n`, which are not their parameters** (math.fj:39, :209).
   - Define them: hex_shift is the number of least-significant zero hexes of const, and dst_n is n.
   - A negative const silently adds |const|: `hex.ptr_add p, -1` advances by +1 cell (`probe2`).
   - add_constant says "positive"; sub_constant does not, and neither do ptr_add / ptr_sub (batch 5).
6. **tables_init.fj:39**: `it must be (1<<n)-padded` should be `n-padded`. **tables_init.fj:42**: `overage` should be
   `average`.
7. **Public helpers with no doc or Complexity line** (for batch 6): hex.inc.step, hex.dec.step,
   hex.add.add_constant_with_leading_zeros, hex.add.add_hex_shifted_constant (4 parameters), and the two sub.* twins.

### Checked, no finding

- **The shifted-out bit.** shl_bit / shr_bit xor it into op 0's jump word (address 0 + dbit, +3 for shr). This is
  harmless: op 0 never runs again, because a jump below 2w ends the run (`restart_probe.py`, controls included).
- **w=16.** `hex.add.init` / `hex.or.init` alone, each with its op, assemble and run (`probe16`). Only the full hex.init
  does not fit (batch 1's MINOR 1). `count_bits 16` at w=16 hits that same "Unknown exception".
- **Init spaces** (`inits.py`, w=64 and w=32): or 595, and 595, cmp 514, add 1570, mul 1624 at @ = 13.1 (mul is
  batch 4). hex.init's 6464+@ holds.

## Front-line table

Old = origin/main's line. Only macros whose own line is wrong are listed.

Measured with cxm.py via m3specs.py (convT / convS: each address-valued wflip counts @/2 - k/2). w=64 at patterns 1 and
5; w=32 is identical.

| # | macro | file:line | current (main) | old derivation | proposed | new derivation | measured | reason |
|---|---|---|---|---|---|---|---|---|
| F1 | `hex.shl_hex n, times` | shifts.fj:31 | S: n(@+28) | n x xor_zero @+28, as if every hex moved | S: (n-times)(@+28) + times(@+12). T n(@+4) stays. | times zeroed hexes at @+12, plus n-times xor_zero at @+28. Exact: (n-times)(@+27) + times(@+12) + 1, because xor_zero's second table has 15 entries. | S: n=2 t=1 2@+40; n=4 t=2 4@+79; n=16 t=8 16@+313 (formula 2@+40, 4@+80, 16@+320). The old line gives 16@+448: +22% at @ = 18.5, and +52% at times = n. T at n=16 t=8: ones 16@+49, random 16@+0, zero 16@-31; the old T 16@+64 stays a valid worst case. | zeroed hexes cost a zero, not an xor_zero |
| F2 | `hex.shr_hex n, times` | shifts.fj:50 | S: n(@+28) | as F1 | S: (n-times)(@+28) + times(@+12) | as F1 | as F1 | as F1 |
| F3 | `hex.neg n` | math_basic.fj:189 | T: ~@+4n | not n (4n) + inc n (1.067@ on average) | T: 4n + 1.067@ (on average, see hex.inc; n(@+5) when x = 0) | The same sum without "~". At size 16 the @ term is 23% of the line, so rule A keeps it. | n=16: random 1@+62, x = -1 1@+62, x = 0 16@+80. n=4: random 1@+14, x = 0 4@+20. S 24@+272 = n(1.5@+17); the space line is right. | "~" is not allowed |
| F4 | `hex.sub.clear_carry c0, c1` (and `sub.clear_carry`) | math.fj:247 (:238) | T: 2@+5 | cannot be reconstructed | T: 2@+3 (2@+11 when the borrow was set) | Set and clear .ret (@), the jumper op, its entry (1 op; 4 when set: res ^= f), the clean entry, the .ret op, if0 @-1. When set, also not_carry (1) and `wflip res, 0xf*dw` (4). | T 2@+4 clear / 2@+12 set, in both forms. S 2@+20; the space line is right. | the borrow-set path is 7 ops over |

### Owner-reviewed lines

The code matches frontline rev 7, and both match the measurement within the conventions:

| macro | measured |
|---|---|
| or n / and n | n=16: T 49@+122 random, 49@+210 all f; S 49@+842 |
| add n / sub n | n=16: T 51@+184.5 / 51@+168.5; S 51@+875.5 / 51@+886.5; the 3@ chain constant is 5% |
| add_shifted / sub_shifted and the constant macros | within 2-5% at 16. A 1-hex const costs 6@+6: the constant rule A dropped. |
| the tables chain macros | jump_to_table_entries / tables.chain: n=16 49@+108 / 49@+842. chained_jump, chained_jump_to_table_entry and chain_step compose exactly. |
| add.chain / sub.chain | as add n / sub n |

### Consistent with their docs (no row)

- **The xor family.**
  - Time follows a "worst - 1" pattern: xor @ (measured @-2..@+1), double @+4 (@-2..@+5), triple @+8 (@-2..@+9),
    quadrupled @+12 (@-2..@+13).
  - Space is exact, except the double family's @+28, which is @+27. One op, and it is the owner's composed callee
    cost, so it is left.
- **Shifts.** shl/shr_bit(_once): S n(@+28) is exact. shl/shr_hex n (times = 1): within 4%.
- **inc1, dec1, inc n, dec n, abs, sign_extend.**
- **add_count_bits.** S is exact. T is an average, 13% over the measured 1/8 carry rate.
- **count_bits.** S n(3.5@+135) composes exactly.
- **sparse_\*.** PAD 16 and PAD 64 give equal convT. sparse_mov: T 2@+1 worst, S 2@+25 exact. sparse_mov n: 32@+385 at
  n = 16.
- **The add carry macros and sub.set_carry.** Within 3-5 ops of their lines; not proposed.
- **The init tables.**

**Dependents if a row is accepted:**

- F3: abs, and batch 4's callers.
- F4: sub.set_carry, and the sub chains' constants (dropped by rule A).
- F1 / F2: none here; mul and div use the times = 1 forms.

## Mutants

Run with mutants3.py through test_fj, on the hexlib (+ func / prime) programs that reach each macro. The control,
CTRL_triple_third_entry3, was caught by hexlib-triple_exact_xor.

**MISSED by the current tests:**

| mutant | change | evidence |
|---|---|---|
| `quadrupled_fourth_entry3` | a wrong bit in quadrupled_exact_xor's fourth table | No test_fj program or unit test reaches quadrupled_exact_xor / address_and_variable_double_xor (unit pool tests: 183 passed). |
| `sparse_mov_no_zero` | sparse_mov without its zero, so dst ^= src | No program uses it; the unit pool tests still pass. |
| `sparse_xor_zero_n_short` | sparse_xor_zero n skips the last hex | Same. |
| `add_constant_skips_1` | `rep(const>1, ...)`: adding 1 does nothing | 76 programs passed. No program in the repo adds the constant 1. |
| `sparse_double_first_entry1` | wrong first entry in sparse_double_exact_xor | Caught only by the tests/unit pool tests. No test_fj program checks a sparse_* result. |

**Caught:**

- add_chain_no_head_zero and sub_chain_no_head_not_carry (by hexlib-chain_n only).
- sub_shifted_tail_inc and add_shifted_tail_short.
- count_bits_zero_one_hex and add_count_bits_no_top_inc.
- sign_extend_no_zero (by hex_func7 only) and sign_extend_not_short.
- abs_never_neg, shl_hex_times_zero_short and shr_bit_once_entry13.
- xor_zero_n_short (by hexlib-basic_memory only).
- add_clear_carry_c_swapped.

**No test reaches:**

- xor_zero x, x aliasing.
- Partial overlap.
- n = 0.
- sub_constant 0, and sub_constant directly (only through ptr_dec / ptr_sub).
- Constants or shifted sources wider than dst.
- quadrupled_exact_xor and address_and_variable_double_xor.
- The results of the sparse_* macros.

**Tests to add:**

- A semantic sparse_* test (sparse_mov (n), sparse_xor_zero (n)).
- A 16-value quadrupled_exact_xor test, like triple_exact_xor.fj.
- `hex.add_constant n, x, 1`.
- sub_constant 0 and `stl.call f, 0`.
