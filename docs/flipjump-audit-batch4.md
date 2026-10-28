# Whole-stl audit, batch 4: hex/ mul, div, cond_jumps, memory, input, output, strings (origin/1.6.0 = 287f28b)

Reviewed at 287f28b in the read-only worktree C:/Users/tomhe/Documents/flipjump-audit2. Its `_fjcore.c` equals
flipjump-160's, so flipjump-160's `_fjcore.pyd` was copied next to it.

**Files covered (every `def`):** hex/mul.fj (17 defs), hex/div.fj (3), hex/cond_jumps.fj (18, switch and its
`__relocatable__` table included), hex/memory.fj (13), hex/input.fj (12, poll_key included), hex/output.fj (11),
hex/strings.fj (5). Every other hex/*.fj is batch 3 (logics, math_basic, math, shifts, tables_init) or batch 5
(pointers/).

Changed vs origin/main: mul.fj (the chained add_mul; new mul_low, fixed_mul(_low), mul_const), div.fj (new fixed_div),
cond_jumps.fj (new switch), input.fj (new poll_key; input_dec lines), strings.fj (lines only). memory.fj and output.fj
are main's.

## Tools

All in this folder. Every run went through `heavy.py audit4 --light`, one process at a time.

- **`edge4.py`**: edge values, one program per (group, w).
  - Every result is preset dirty and sits between two guard hexes, checked unchanged. Input cases read their own
    bytes from one FixedIO stream; printing cases check the printed bytes, then the result hexes.
  - The `state` group runs each op alone in the checker's tracer and compares every shared table cell with its image
    value: hex.tables.res / .ret, hex.mul.dst / .ret / .add_carry_dst, hex.add.dst, hex.sub.dst, hex.cmp.dst.
  - `selftest` (R9): a wrong expected value, a wrong printed value and an op that dirties hex.mul.dst must all be
    reported. PASS at w=64 and w=32.
  - `mulalias` runs one case a program (a dirtied hex.mul.dst would fail every later case).
- **`strmem.py`**: fill_bytes / copy_bytes. The byte buffers (one byte a cell) and their guard cells are read from
  memory by the tracer. Its selftest (a wrong expected buffer must FAIL) PASSes at w=64 and w=32.
- **`m4specs.py`**: batch 4's specs for the checker's `cxm.py`. `cxm.py --selftest` and `m4specs.py --selftest` PASS.
  - 623 rows: w=64 at patterns 1 and 5 (align 18), w=32 at pattern 1 (`run_m.sh`, logs `m_*_w*_p*.log`).
  - `shift4.py` (R9 cross-check): pattern 1 -> 5 moves T by exactly At and S by exactly As, and w=32's convT / convS
    equal w=64's, on every row except the strings rows (pointer ops: their cost depends on w and on the pointer, by
    design) and two rows holding one `prev ^ return` wflip (mul_const 16, fixed_mul_low_neg 16: 1 op of 396 / 1260).
- **`mulcmp.py` / `mulcmp2.py`**: hex.mul's operand choice under three stl variants (`fix_mul*/`), exact ops by cxm.
- **`main_idiv.py`**: the div group on origin/main's stl (`mainstl/`).
- **`probe0.py`**: n = 0 / nb = 0 probes, one program each, guards around every vector.
- **`mutants4.py`**: batch 3's runner with batch 4's table, in `mtree/` (= `git archive 287f28b` + the engine).
  Each mutated file is restored after its run.

## Edge runs

mul, div, cond, mem, io, out, str and state ran at w=64 and w=32; cond, mem, io and out also at w=16 (one case a
program, every 8th case). Everything not listed under BLOCKING / MINOR passed, among others:

- **mul**: add_mul n at n = 0..3 and 16 (b = 0, 1, f, random; all-f operands); the single add_mul in its documented
  protocol; mul10 (0, max, random); mul and mul_low at n = 1..4 and 8 over {0, 1, max, 8..0} squared, random, a == b;
  fixed_mul and fixed_mul_low at n = 1..4, f in {1, n/2, n}, over {0, 1, -1, MIN, MAX} squared, random, 1.0 x 1.0,
  dst == a, dst == b, a == b == dst; mul_const with c = 0, 1, 2, 3, 10, 15, 16, 255, 16^n - 1, 16^n, 16^n + 1,
  3*16^n + 7, 0x8001, and dst == src.
- **div**: div at (n, nb) = (1,1) (2,1) (2,2) (4,2) (3,3) (2,4): 0 / x, max / 1, max / max, a < b, b = 0 (q, r
  untouched), and q == a, r == b, q == b, r == a; idiv with rem_opt 1 everywhere, rem_opt 3 / -1 -> div0;
  fixed_div at n = 1..4, f in {1, n/2, n}, MIN, MIN / -1, b = 0, dst == a, dst == b.
- **cond**: if_flags (5 flag sets x 16 values), if / if0 / if1, if n / if0 n / if1 n at n = 1, 2, 3, 5, sign n,
  switch (16 values; x unchanged and disarmed), cmp (all 256 pairs), scmp 1 (all 256 pairs), cmp n / scmp n at
  n = 1..4 (equal, MIN / MAX, one-bit differences), min / max n.
- **mem**: zero / mov / swap / set / xor_by, single (16 x 3 values) and n = 0, 1, 2, 5; mov x, x and swap x, x.
- **io**: input_hex, input, input n; input_as_hex on all 256 bytes; input_as_hex 2; input_dec_uint(_until) and
  input_dec_int(_until) at n = 1, 2, 4 on 24 strings (wrap, "007", empty, '\0', "-", "--5", "+5", "-0", MIN, MIN - 1).
- **out**: output, print, print n, print_as_digit (16 values x upper / lower), print_as_digit n, print_uint / print_int
  with every prefix / case flag, print_dec_uint / print_dec_int at n = 1, 2, 4, 16 (0, 1, MAX, MIN, random); x kept.
- **str**: input_ptr_line + print_ptr_text ('\n', '\0', empty, 12 bytes), print_ptr_line ('\n' / '\0' terminated,
  empty), print_ptr_text of 0 bytes; fill_bytes / copy_bytes at counts 0, 1, 5, 8 (guards, ptr, count, value kept).
- **state**: 19 ops (the mul / div / cmp / print / input families) leave every shared table cell clean, except
  add_mul with b inside res (B2).
- **w=16**: cond, mem, io pass; out passes except print_uint / print_int n = 16 and print_dec n = 4, which hit the
  assembler's "Unknown exception" at w=16 (the image does not fit; batch 1's MINOR 1).

## BLOCKING

### B1. `hex.idiv`, rem_opt 0 or 2: a ZERO remainder is "corrected" anyway - q is off by one and r = b

Where: div.fj:121-131 (`fix_rem`, `update_rem_opt_0`, `update_rem_opt_2`). main behaves the same (`main_idiv.py`:
the same 67 rem_opt failures on origin/main's stl).

- **Cause:** opt 0 adds b to r (and decrements q) whenever a and b have different signs; opt 2 adjusts whenever a < 0.
  Neither checks r != 0, so every exact division with those signs is "corrected" too.
- **Reproducer** (`edge4.py <stl> div 64 32`: 67 failing cases at each w, at every (n, nb); opt 1 and div pass):

  | call (n = nb = 1 shown) | got q, r | right q, r |
  |---|---|---|
  | idiv opt0, 0 / -5 | -1, -5 | 0, 0 |
  | idiv opt0, -6 / 3 | -3, 3 | -2, 0 |
  | idiv opt0, 6 / -3 | -3, -3 | -2, 0 |
  | idiv opt0 / opt2, -8 / 1 | 7, 1 | -8, 0 |
  | idiv opt2, -6 / -3 | 3, 3 | 2, 0 |
  | idiv opt2, -1 / -1 | 2, 1 | 1, 0 |

  The doc: r = a % b with sign(r) == sign(b) (opt 0) or r positive (opt 2). r = b is out of range, and 0 / -5 = -1.
  (a == q*b + r still holds, which is why it looks plausible.)
- **Untested:** test_idiv.fj passes |a| and |b| (its `test_idiv` macro takes the absolute values before test_div),
  and test_idiv_cases.fj divides only +-20 by +-12. The mutant that applies the fix below passes every test.
- **Smallest fix (1 line, right after `fix_rem:`):** `rep(rem_opt != 1, i) .if0 nb, r, end`
  Verified (`fix_idiv/`, `edge4.py div 64 32`): all 67 pass at both w; only the alias cases of MINOR 3 remain.
  Cost, opt 0 / 2 only: nb(@+15) space, at most nb(@-1) time (3.7% of the nb term: no line changes).
- **Tests to add:** idiv at rem_opt 0 and 2 with r == 0 and mixed signs (0 / -5, -6 / 3, 6 / -3, -6 / -3), MIN / 1.

### B2. `hex.add_mul n, res, a, b` with b one of res's hexes leaves hex.mul.dst dirty: every later multiply is wrong

Where: mul.fj:23-26 / hex.mul.chain mul.fj:102-114. main behaves the same (`edge4.py mulalias` on main's stl: the
same 3 failures).

- **Cause:** b is xored into hex.mul.dst at the start and out again at the end (`..xor .dst, b`, mul.fj:113). When b
  is a hex of res and the call changed it, the second xor leaves (old b ^ new b) in hex.mul.dst. The call's own result
  is right; every later add_mul / mul / mul10 / mul_low / fixed_mul / mul_const / input_dec multiplies by a wrong b.
- **Reproducer** (`edge4.py <stl> mulalias 64 32 --probe`, one case a program): `hex.add_mul 2, x, a, x` (a = 3), then
  `hex.add_mul 1, y, c, d` with y = 1, c = 2, d = 3 gives y = 1, not 7 (n = 1, 2, 4 at b = res[0]; at w=32 also
  b = res[1]). The `state` group shows `hex.mul.dst: jump 0x60000 -> 0x60780` after `hex.add_mul 4, r, a, r+dw`.
  The control (b outside res) passes.
- **Smallest fix (doc, 1 line on add_mul n and mul.chain):** `// b must not be one of res's hexes (it is read again at the end).`
  No cheap code fix: `.dst`'s jump word holds the table address, so it cannot be cleared with hex.zero; it needs b.

## MINOR

1. **hex.mul picks its loop operand by the VALUES of the low hexes, and computes two count_bits it never reads; the
   doc's "b" is wrong** (mul.fj:48, :56-58).
   - `.cmp ((#(n*4))+3)/4, a, b, ...` compares a and b on their low ((#(4n))+3)/4 hexes; a_1bits / b_1bits (two
     count_bits n) are never read. The doc: "b is the minimum of #on-bits in a,b (b<n/2 on average, e.g. b=7 for
     n=16)". In fact the loop runs once per hex up to the loop operand's top non-zero hex, and add_mul runs on its
     non-zero hexes: b is that count (about 15 for random 16-hex values), and n^2 is the worst case.
   - Measured (`mulcmp.py`, exact ops, w=64, 20 operand pairs a size, 12 of them random):

     | variant | n=4 mean T | n=8 | n=16 | space a call, n=16 | 0x8000000000000001 * 7 |
     |---|---|---|---|---|---|
     | 287f28b: the low hexes' values | 2522 | 7485 | 28040 | 14677 | 17370 |
     | `a_1bits, b_1bits` (the doc's intent) | 2534 | 7505 | 28078 | 14677 | 17368 |
     | no count_bits, `.cmp n, a, b` (the smaller value loops) | 2165 (-14%) | 6485 (-13%) | 21990 (-22%) | 8973 (-39%) | 3790 (x4.6) |

     The doc's own intent (on-bit counts) is no faster. The value compare is faster on 49 of 60 pairs (slower when
     the smaller value has more non-zero hexes, e.g. 0x365d * 0x8600: 2373 -> 2867). Both variants pass
     `edge4.py mul` (the same alias failures only). fixed_mul (hex.mul at 2n): mean T 9341 -> 7146 (-24%) at n = 4 and 32428 -> 25292 (-22%) at n = 8 over 20 pairs (`mulcmp2.log`); with mixed signs the non-negative operand now always loops (n iterations, not 2n): up to x2.1 (0x3a096533 * -0x5ed34fe6: 34551 -> 16646); both negative is 5-13% slower (0x9f6f7bfa * 0xe46be0bc: 38815 -> 43567).
   - **Smallest fix (speed, 3 lines):** delete the two `.count_bits` lines (and the two `*_1bits` vectors), and
     `.cmp n, a, b, a_less_1bits, a_less_1bits, b_less_1bits`. Doc: "the smaller of a, b (unsigned) is the loop
     operand: n^2 is the worst case (its top hex non-zero); b is its non-zero hexes". Doc-only alternative: describe
     the low-hex compare and b as they are.
2. **Undocumented aliasing in the multiplies** (`edge4.py mul`):
   - hex.mul's res must not alias a or b (mul.fj:46-49): `.zero n, res` runs before a and b are read, so
     `hex.mul n, a, a, b` gives 0 at n = 1..8. mul_low documents it; mul does not. Fix: copy mul_low's sentence.
   - add_mul n with res = a + k*dw (k >= 1) is wrong (n = 2, 4); res == a (mul10 relies on it) and res = a - k*dw are
     right. Fix: "res must not overlap a, except res == a" (with B2's sentence).
   - Optional: `.zero n, src` (mul.fj:52) is dead: src is 0 at load and at every exit of the loop (n@ a call).
3. **hex.idiv: q / r must not alias a / b, and a must not alias b** (div.fj:84). idiv negates a and b in place and
   negates them back at the end, so the restore also negates an aliased q or r (`edge4.py div`, n = 2, 4, rem_opt 1):
   q == a: -6 / 3 gives 2; r == b: 7 / -2 gives r = -1; q == a or a == b: -5 / -5 gives -1. div supports all four
   aliases. Fix: `// q,r must not alias a,b; a must not alias b (a and b are negated in place, then restored).`
4. **n = 0 is unguarded** (`probe0.py`): each call alone, between guards (`probe0.log`, `probe0b.log`, w=64):

   | call | effect |
   |---|---|
   | `if 0, x` / `sign 0, x` | read the hex BEFORE x: x[-1] = 8 jumps to l1 / neg (the empty vector is 0 and non-negative) |
   | `scmp 0` | `xor_by ba-dw` flips a bit of its own code: the run ends at `ip<2w` |
   | `mul 0`, `mul_const 0, d, s, 7` | the run ends at `ip<2w` |
   | `mul10 0, x` | shl_bit 0 shifts x[-1] (8 -> 0) |
   | `div 0, 1` | never ends (`.set #0, i, -1` / `.sign #n, i`: the tracer stopped at 50M ops), x[-1] zeroed |
   | `div 1, 0` / `idiv 1, 0` | `.if0 0, b` reads b[-1]: jumps to div0 here, by the neighbour's value |
   | `print_int 0` | sign reads x[-1]: prints '-' for "-0" |
   | `print_dec_uint 0`, `input_dec_uint_until 0` | jump to address 0 (`null ip`); the latter also writes x[-1] and the stop byte |
   | `cmp 0` | compares one hex (a[0], b[0]) |

   Safe at n = 0: mul_low, min / max, add_mul (clear_carry only), print_uint (prints "0"), zero / mov / swap / set /
   xor_by n, input n, print n, input_as_hex n.
   Fix: `// @Assumes: n >= 1.` (nb >= 1 for div / idiv), as in batches 2 and 3.
5. **Out-of-range constants: the single-hex forms clamp, the n forms wrap** (memory.fj:10-12, :73-75, :86-89;
   `edge4.py mem`). `hex.hex -1` is 0 and `hex.hex 16` is f, but `hex.vec 1, -1` is f and `hex.vec 1, 16` is 0;
   `hex.set x, (0-1)` gives 0 while `hex.set 1, x, (0-1)` gives f; `hex.xor_by x, 16` flips f. The docs say
   "hex = val". Fix: `// val is clamped to 0..15 (the n forms take val's hex digits).` on hex, set and xor_by.
6. **Data-dependent time lines that do not say which case they give** (no row: within the conventions):
   - cmp 3@+8 (cond_jumps.fj:126): all 256 pairs measure 3@+0..3@+15, mean 3@+6.2 (an average; worst a == b == f).
   - scmp n(7@+8)+8 (:255) is cmp's worst case m = n (measured n(7@+0.4)); add "(m = n: cmp's worst case)".
   - div / idiv (div.fj:2, :72) are the worst case ("every compare full and every subtract taken", as fixed_div's own
     doc says); random operands measure 2705@-834 at n = 16 against the line's 8192@+27648.
   - input_hex 2@+7, input 4@+14, input_as_hex 7@+11 are worst cases (input bits all 1 / a digit; 2@+3 for a 0 nibble).
   - print_int n(2@+10): see F3.
7. **hex.input_ptr_line has no length bound** (strings.fj:5-9): it writes until '\n' or a 0-byte, so the buffer must
   hold the whole line, and the stored line is not 0-terminated. Fix: say both in its doc.
8. **Test nit:** programs/hexlib_tests/basics1/if.fj:12 masks with `((i<<20)-1)`, meaning `((1<<20)-1)`. Harmless:
   if_flags reads only 16 flag bits.

### Checked, no finding

- switch (new): every value reaches its target; x is unchanged and disarmed (a later if_flags on x is right).
  T @-2 / S 8.5@-18 are exact.
- poll_key (new): its unit tests carry negative controls. Idle is exactly 3@+3 (the status nibble is 0, so input_hex
  costs 2@+3), an event 7@+15..7@+19; the line 3@+6 / 7@+20 composes input_hex's worst 2@+7 and if0's @-1 (the
  convention). S 7@+64.5 measured against 7@+69.
- fixed_mul / fixed_mul_low / mul_low / mul_const: right at every edge, aliases included; fixed_mul is floor((a*b) /
  16^f), fixed_div truncates toward zero, as documented.
- div: q, r untouched on div0; MIN / -1 wraps; nb > n works.
- print_int / print_dec_int negate x in place and restore it; MIN prints "-8000" / "-32768".
- input_dec_int: "-" alone and "-0" give 0; "+5" stops at '+' with 0 (documented); "--5" stops at the second '-'.

## Front-line table

Old = origin/main's line. Only macros whose OWN line is wrong. Measured with cxm.py through m4specs.py (convT / convS:
each address-valued wflip counts @/2 - k/2); w=64 at patterns 1 and 5 and w=32 give the same convT / convS.

| # | macro | file:line | current (main) | old derivation | proposed | new derivation | measured | reason |
|---|---|---|---|---|---|---|---|---|
| F1 | `hex.if_flags`, `hex.if` (and `if0` / `if1`), `hex.sign` | cond_jumps.fj:5, :28, :118 | T: @-1 | 2 pad-16 wflips (@-4) + 3 plain ops | T: @ (S @+15 stays) | 2 pad-16 wflips (@-4) + 4 plain ops: the hex op, the table entry, `return: ;finish`, the finish op | convT 1@+0 at every value 0..15 (if_flags at 4 values, if at 0 and f, sign n = 1, 4, 16 at 4 values); if n worst n(@) (zero: 4@+0, 16@+0) | one plain op left out |
| F2 | `hex.output`, `print`, `print n`, `print_as_digit`, `print_as_digit n` | output.fj:6, :60, :68, :80, :146 | T: @ / 2@ / n(2@) / @+4 / n(@+4) | cannot be reconstructed (2 wflips at @/2 = @, the output ops left out?) | T: @+1 / 2@+2 / n(2@+2) / @+5 / n(@+5) (S stays) | output: 2 pad-16 wflips (@-4) + the hex op + the table entry (bit 0) + 3 print ops (bits 1..3) = @+1; print_as_digit: the same with 7 print ops = @+5 | output 1@+1 at all 5 values; print 2@+2; print n=16 32@+32; print_as_digit 1@+5 at 10 values (upper and lower), n=16 16@+80 | the plain ops |
| F3 | `hex.print_int n` | output.fj:192 | T: n(2@+10) / S: n(4.5@+71) | print_uint (n(2@+6) / n(3@+54)) + ONE neg n (4n / n(1.5@+17)) | T: n(2@+14) (x < 0; n(2@+6) when x >= 0) / S: n(6@+88) | print_uint + TWO neg n: it negates x, prints, and negates x back | S n=4 29@+407, n=16 101@+1463: n(6@+88) a hex, exact; T x < 0: n=4 16@+64, n=16 40@+236 = n(2@+14.3); x >= 0: n(2@+6) | it negates twice (as batch 2's F18 for bit.print_dec_int) |
| F4 | `hex.print_dec_uint n` | output.fj:217 | S: n(56@+64) | bit.print_dec_uint 4n's n(14@+16) x 4; hex2bit n left out (its time n(5@-4) IS in the time line) | S: n(61@+72) | + hex2bit n's n(5@+8) | n=4 251@+388, n=16 1046@+1681: 66.25@+107.75 a hex (the rest is bit.print_dec_uint's own space, above its line: batch 2) | a callee left out |

**Dependents if accepted:** F1 -> if0 / if1 / if n / if0 n / if1 n (n(@)), cmp's and the conventions' "if @-1",
and every line that composes if (input_as_hex, poll_key, mul, div, the strings...). F2 -> print_uint.print_digit,
print_uint, print_int, the strings that print. F3 -> none in the stl. F4 -> print_dec_int S n(59@+98) -> n(64@+106).

### Owner-reviewed lines (frontline rev 7): the code's doc equals the table; the measurement agrees within the conventions

| macro | line | measured (w=64, @ about 18.5-19.9) |
|---|---|---|
| add_mul (one hex) | 4@+34 / 4@+50 | 4@+36 / 4@+49 |
| add_mul n, mul.chain | n(3@+38) / n(3@+54) | slope n=4 -> 16: random b 3@+37.3 (b = 0: 3@+23, all f: 3@+46) / 3@+52.8 |
| mul.clear_carry | 3@+24 / 3@+9 | 3@+23 / 3@+8 |
| mul10 n | n(4@+39) / n(4@+82) | slope 4@+31.4 / 4@+80.8 |
| mul | n^2(3@+7) + n*b(3@+38) / n(20@+481) | every hex non-zero, n=16: 1593@+7737, 7% under the line; S slope n=8 -> 16 20@+478 (but b's definition: MINOR 1) |
| mul_low | n^2(1.5@+19) + n(10.5@+73) / n^2(1.5@+27) + n(10.5@+102) | b without a zero hex, n=16: 552@+5804 (line 552@+6032) / 552@+8447 (line 552@+8544) |
| fixed_mul | n^2(12@+28) + n*b(6@+76) / n(48@+1066) | both negative (2n iterations), n=8: 42077 ops-equivalent vs the line's 42055 (0.05%); S slope 48@+1065 |
| fixed_mul_low | (n^2/2 + nf)(3@+38) (+ f^2(1.5@+19), b < 0) / (n+f)^2(1.5@+27) | f = n = 16: T 8% (b >= 0) and 9% (b < 0) over the line; S 1954@+31560 against 1536@+27648, 17% over: Rule A dropped n(14.5@+150) and f(11.5@+118) separately (11.9% and 9.4%), together 21% |
| mul_const | on*n(3@+14) + (#c-1)n(@+1) / on*n(3@+54) + (#c-1)n(@+28) | c = 255, n = 16: 4% from the line; c = 10: 17% over (the dropped mov + zero n(3@)) |
| div / idiv / fixed_div | worst-case lines | all-f / 1, n=16: 9083@+1969 = 5% under n^2(32@+108); S div n(19@+326) 1.4%, idiv n(38@+577) 6%, fixed_div n(54.5@+799) 4.6% |
| input_dec_uint / int (_until) | nd(7@+53) / n(9@+161), n(10.5@+178) | n=16: 130@+425 a digit = 3% from 16(7@+53); n=4: 46@+179 a digit, 41% over the line: its d(18@+97) term (Rule A dropped it at size 16). S slopes 9@+159 / 10.5@+176 |
| the strings | worst-case lines (dense pointer) | S within 1-12.5%; T 24-55% under with a sparse pointer and counts < 16 (MINOR 6) |

### Consistent with their docs (no row)

switch (exact), cmp n m(3@+8) (equal values: 48@+94 at n = 16, 3@+5.9 a hex), min / max (worst n=16 80@+79 =
n(5@+4.9); S n(6@+66) exact), scmp S, zero (@-2..@+1 by value), mov (worst 2@+1), mov n, swap (worst 3@+0), swap n,
set (@+0..@+3 from 3), set n, xor_by (popcount; 1 op for 0), input_hex / input / input n (worst), poll_key (by
composition), input_as_hex (worst 7@+11; S 8.5@+89 vs @+92), input_as_hex n, output S, print_uint (T n(2@+6) slope
exact for all-non-zero hexes; leading zeros 2@+1; S n(3@+54) exact), print_dec_uint T (d = 1: 1%; at many digits the
line composes bit.print_dec_uint's worst windows - batch 2), print_dec_int (two negs counted).

## Mutants

Run with mutants4.py through test_fj (`mutants4.log`), on the programs whose text reaches each macro. The control,
CTRL_switch_r15 (switch's entry 15 jumps to t14), was caught by hexlib-switch.

**MISSED by the current tests:**

| mutant | change | evidence |
|---|---|---|
| `idiv_fix_rem0 (the proposed fix)` | B1's fix line added after `fix_rem:` | 10 programs, 20 passed: no test divides exactly with mixed signs (B1 untested) |
| `idiv_no_restore_a` | idiv does not negate a back (div.fj:112 deleted) | 10 programs, 20 passed: no test reads a after idiv with a < 0 |
| `print_dec_int_no_restore` | print_dec_int leaves x negated (output.fj:240 deleted) | hex_print_dec, hexlib-input_dec_until pass: nothing reads x after printing a negative |
| `input_dec_uint_no_nul_terminator` | input_dec_uint accepts only '\n' (input.fj:182 `(1<<0xA)`) | 3 programs pass: no test ends a number with a 0-byte |
| `input_dec_int_plus_negates` | a leading '+' negates like '-' (input.fj:148 `(1<<0xD)\|(1<<0xB)`) | 2 programs pass: no test reads a '+' |
| `input_ptr_line_ignores_nul` | input_ptr_line does not stop at a 0-byte (strings.fj:14 deleted) | hexlib-strings and cat_echo_bot pass: no input line holds a 0-byte |
| `mov_no_self_guard` / `mov_n_no_self_guard` | mov x, x without its `comp_if1 dst==src` (it then zeroes x) | 4 programs pass: no test movs a variable onto itself |

**Caught:** sign_8_nonnegative (hex_print_dec, hexlib-basic_math), if_n_skips_hex_n-2 (div-4_2, fixed_point, idiv,
strings), cmp_n_skips_hex_1 (div, fixed_point), swap_no_self_guard (macro_hex_comp only), idiv_no_restore_b
(idiv-cases only), print_int_no_restore (hexlib-print_int), print_as_digit_no_upper (49 programs),
fixed_mul_low_neg_rows_same_offset (hexlib-fixed_point).

**No test reaches** (shown by edge4 / probe0, not by a mutant): idiv with r == 0 and mixed signs (B1); add_mul with b
inside res (B2) or res overlapping a; mul with res == a; idiv's aliases; n = 0 of every n macro; out-of-range
constants of hex / set / xor_by; hex.mul's operand choice (a speed property: every variant gives the same product).

**Tests to add:** B1's idiv cases; `hex.add_mul n, x, a, x+k*dw` followed by another multiply (if the doc fix is
taken, a test is not needed); `hex.mov x, x`; idiv / print_dec_int with a < 0 then reading a / x; input_dec_uint
with a '\0' terminator and input_dec_int with a leading '+'; input_ptr_line on a line holding a 0-byte.
