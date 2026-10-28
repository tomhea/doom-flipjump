# Whole-stl audit, batch 2: bit/ logics, math, mul, div, shifts, cond_jumps, input, output, pointers (stl-additions cd310f1)

None of the nine files differs from origin/main (`git diff --stat origin/main HEAD -- flipjump/stl/bit/` is empty): every
line below is main's line, and every finding is on main too.

Tools (this folder; every run through `heavy.py audit2 --light`, one process at a time; worktree C:/Users/tomhe/Documents/flipjump-audit2):
- `edge2.py` - edge values; every result label preset dirty; outputs compared bit for bit with Python.
  `selftest` (R9): a wrong expected value must FAIL, for a bit result and for a printed one: PASS (w=64, w=32).
- `probe_n0.py` - n = 0, times = 0, times > n, with guard bits on both sides.
- `m2specs.py` - batch 2's specs for the checker's `cxm.py` (its `--selftest` PASS on this tree). w=64 at pattern 1 and 5:
  `shiftcheck.py` - 234 of 245 rows move by exactly At / As; the other 11 are pointer macros whose T moves by +1/+2 more
  because the POINTER VALUE gains an on-bit (one more `dst1; dst2;` path in double_exact_xor): explained. w=32 for the
  pointer and math rows.
- `mutants2.py` - batch 1's runner with batch 2's table, in the scratch copy `mtree/` (restored and diffed clean after).

Edge runs: logic, math, mul, div, shift, jump, io, out, ptr, alias at w=64 and w=32; logic, jump, shift, io, ptr at w=16
(one case per program). Every failure is listed below; everything else passed, including print_dec_uint / print_dec_int
at n = 1..5, 7, 8, 10, 16, 32, 64 (0, 1, 9, 10, max, min, 10^k), print_hex_(u)int at n = 4..64 (both prefixes), all 20
cmp_sub_10 inputs, div / div_loop / idiv / idiv_loop at n = 1..13 (b = 0 leaves q, r unchanged; MIN/-1, MIN/1, MIN/3),
mul / mul_loop at n = 1..16 (squaring through `mul`), every shift count 0..n, every pointer macro at w = 16 / 32 / 64,
mul_loop and print_dec_uint re-run in a loop.

## BLOCKING

**B1. `bit.input n` reads a BIG-endian number; the doc says little endian** (input.fj:24).
- Code: `rep(n, i) .input dst+8*(n-1-i)*dw` - the first byte read lands in the TOP byte (`hex.input n` is the opposite).
- Repro: `edge2.py <stl> io 64` - bytes a3 34 into `bit.input 2, d` give d = 0xa334 (the doc: 0x34a3); n = 3 the same;
  w = 16 / 32 the same.
- The test `segments` pins the big-endian order (mutant CTRL_input_n_order caught), so the code stays.
- **Smallest fix (1 line):** `//   Effectively inputs an 8*n bits big endian number into dst[:8n] (the first byte read is
  the most significant: dst[8(n-1):8n]).`

**B2. `bit.print_as_digit n` prints msb first; the doc says lsb first** (output.fj:57).
- Code: `rep(n, i) .print_as_digit x+(n-1-i)*dw`. Repro: `edge2.py out` - x = 0b0011, n = 4 prints "0011".
- The test `casting` pins msb first (mutant print_as_digit_n_lsb_first caught).
- **Smallest fix (2 lines):** `('0's and '1's, msb first)`; and output.fj:56 `Complexity: @+9` -> `n(@+9)` (row F15).

**B3. `bit.idiv` / `bit.idiv_loop`: wrong sign when q or r aliases a, or q aliases b** (div.fj:52-64, :148-160).
- Cause: after the unsigned division writes q, r, the macro negates a, r, b, q in place (restoring the inputs and fixing
  the signs); on aliased memory a restore negates a result.
- Repro: `edge2.py div` n = 8: `idiv 8, a, b, a, r` (x = x / y), a = -100, b = 7 -> q = +14 (want -14);
  `idiv 8, a, b, q, a` -> r = +2 (want -2); `idiv 8, a, b, b, r`, b = -7 -> q = +14. idiv_loop the same (6 FAIL a w).
  The unsigned div / div_loop are right on the same three calls, so `x = x / y` silently breaks when switching to signed.
  a == b is right (the two restores cancel).
- **Smallest fix (1 doc line a macro):** `// @Assumes: q and r overlap neither a nor b (a and b are negated and restored in
  place).` Code alternative (4 lines a macro, exact aliasing only): wrap `.neg n, a` in `stl.comp_if1 (q==a)|(r==a),
  skip_a` and `.neg n, b` in `stl.comp_if1 (q==b)|(r==b), skip_b`.

## MINOR

1. `bit.sub n, x, x` gives 2x, not 0 (math.fj:91): `.not n, src` also flips dst. Repro `edge2.py math`: n = 2/4/8/16
   (4 FAIL a w). Fix: `// @Assumes: dst and src do not overlap.` (or `stl.comp_if1 dst==src` -> `.zero n, dst`).
2. Partial overlap in xor / or / and / add / sub n is undocumented (logics.fj:12, :83, :100; math.fj:77, :88). dst =
   src + dw gives wrong results for xor / or / and / add (bit i of dst is bit i+1 of src, overwritten before it is
   read); dst = src - dw works for those four and fails for sub. `edge2.py alias`: 11 FAIL of 34 at w = 64 and 32.
   bit.mov n already says "doesn't work if dst and src overlap. works if dst==src": the same sentence on xor n, or n,
   and n, add n (sub n: item 1).
3. `bit.mul10 n` needs n >= 2 (mul.fj:5): `.shl n, 2, x` zeroes 2 bits; n = 1 zeroes x+dw (edge2 mul: 2 FAIL a w),
   n = 0 zeroes x and x+dw. Fix: `// @Assumes: n >= 2.`
4. n = 0 is undefined in the macros built on `rep(n-1, ...)` (probe_n0): if / if0 / if1 n jump by x-dw (the bit BEFORE
   x); cmp n reads a-dw / b-dw; ror / rol 0 clobber x-dw / x; mul_loop 0 clobbers x and the next bit; div_loop 0 and
   print_dec_uint 0 jump to address 0 (`ip<2w`). Fix: "n >= 1" at cond_jumps.fj:18, :34, :50, :73; shifts.fj:46, :58;
   mul.fj:18; div.fj:196; output.fj:144.
5. `bit.neg n` documents `x[:n]--` (math.fj:55); it computes x = -x. Fix: `//   x[:n] = -x[:n]`.
6. `bit.mul`'s b is the 1-bits of DST, not src (mul.fj:54) - the flags are dst+i*dw. Measured n = 16: dst 0 / src all
   ones 112@-77 (no add); dst all ones / src 0 1408@+691 (16 adds); n = 4, 8 the same shape. Fix: `// b is the number of
   1-bits in dst.` (mul_loop's b is src's: `.if0 src, after_add`.)
7. `bit.cmp n` is unsigned; the doc does not say (cond_jumps.fj:73-79; 0x80 vs 0x7f -> gt). Fix: `(unsigned)`.
8. pointers.fj:25 `Complexity: 2n@` (n is not a parameter) -> `2w@`; pointers.fj:186 `ptr[:n] -= 2w` -> `ptr[:w] -= dw`.
9. div.fj:17 `if (val > 10)` -> `if (val >= 10)` (the macro subtracts at 10; all 20 inputs verified).
10. `bit.xor_zero x, x` leaves x (the flips cancel; the doc reads "dst ^= src; src = 0"); `bit.div10 n, x, x` gives 0.
    Fix: "dst and src must differ" (logics.fj:57, div.fj:3).
11. shr / shl with times > n (and their n = 0 forms) clobber neighbours: already `@Assumes: times <= n`. No change.

## Front-line table (old = origin/main = stl-additions; only macros whose OWN line is wrong)

T / S from cxm.py (executed ops; no-sharing space, pads excluded) as a@+b, every address-valued wflip at @/2 less its
pad's k/2; w = 64 unless noted, at two placements (pattern 1 and 5, identical conv values), w = 32 for the w rows.
"with F1": also assuming row F1, since every bit/ conditional is built on bit.if.

| # | macro | file:line | current (main) | old derivation | proposed | new derivation | measured | reason |
|---|---|---|---|---|---|---|---|---|
| F1 | `bit.if` | cond_jumps.fj:5 | @+2 | xor @-1 + the 3 ops label_ptr, `;l0`, `label_ptr+dbit;l1` (= the space) | T: @+1 / S: @+2 | a run executes label_ptr and ONE target: @-1+2; space @-1+3 | T 1@+1 (x = 0, 1), S 1@+2; if0 / if1 the same | one of two exits runs |
| F2 | `bit.and` | logics.fj:91 | 2@+2 | copied from `or` (if0 @+2 + one @) | 2@+1 (T 2@ with F1) | if1 @+2 + zero @-1 | T 2@+0 (src 0), 1@+1 (src 1); S 2@+1 | zero is @-1, one is @ |
| F3 | `bit.inc n` | math.fj:30 | T: 5@+12 in average | one @ + two inc1 at 2@+6 | T: 6@+8 on average; 4@+5 + t(2@+3) for t trailing 1-bits (t < n-1) | one @; a carry iteration if0 @+1, not 1, if0 dst @+1 = 2@+3 (t+1 of them); not carry 1; the stop test if0 carry @+1. E[t] = 1-2^-n. The old line left out the stop test | n=16: t=0 4@+5, 1 6@+8, 3 10@+14, 7 18@+26; n=4: t=0 4@+5, t=3 9@+14 (no stop test at the top bit); all ones n=16 33@+49; S 33@+98 = n(2@+6)+@+2 (doc right) | stop test runs |
| F4 | `bit.dec n` | math.fj:44 | S: n(2@+6) | inc n's space | S: n(2@+8) (T 2n + 6@+8 by F3) | inc + two `not n` | S n=16 33@+130 = 16(2@+8)+@+2; T t=0 4@+37 | its two not n |
| F5 | `bit.neg n` | math.fj:54 | S: n(2@+6) | inc n's space | S: n(2@+7) (T n + 6@+8 by F3) | inc + one `not n` | S n=16 33@+114; T t=0 4@+21, t=3 10@+30 | its not n |
| F6 | `bit.add1` | math.fj:64 | 8@+14 | mov 2@-1 + 2 inc1 2@+6 + or 2@+2 + skip (time) | T: 8@+14 / S: 8@+15 | the space adds the `_src` bit | S 8@+15 at all 5 (d,s,c) measured; T worst 8@+8 (1,1,1) | data bit is space |
| F7 | `bit.mul10 n` | mul.fj:2 | n(14@+10) | shl + mov + shl 2 + add (time) | T: n(14@+10) / S: n(14@+11) | space adds `twice` (n bits) | S n=4 54@+51, 8 110@+99, 16 222@+195 = n(14@+12)-2@+3 (the last +n: F6) | data is space |
| F8 | `bit.mul` | mul.fj:51, :54 | T n*b(8@+14), b = 1-bits of src | one add n per flag | T n*b(8@+14), b = 1-bits of DST | flags are dst+i*dw | n=16: dst 0/src F 112@-77, dst F/src 0 1408@+691, dst F/src F 1769@+1294 | MINOR 6 |
| F9 | `bit.shr n, times` | shifts.fj:11 | n(2@-1) | n movs | (n-times)(2@-1) + times(@-1) | n-times movs + `zero times` | n=16 t=8 T=S 24@-16; n=4 t=2 6@-4; n=16 t=1 31@-16 | a zeroed bit is @-1 |
| F10 | `bit.shl n, times` | shifts.fj:36 | n(2@-1) | as F9 | (n-times)(2@-1) + times(@-1) | as F9 | n=16 t=8 24@-16; n=4 t=2 6@-4 | as F9 |
| F11 | `bit.div10 n` | div.fj:2 | n(5@+11) | zero n + n windows at 4@+12 | T: (n-3)(4@+12) + n(@-1) / S: (n-3)(5@+18) + n(@-1) (n>=4; n(@-1) for n<=3) | n-3 windows, not n (3(4@+12) is 18% of the line at 16: kept); a window's space is F12 | S = (n-3)(5@+18)+n(@-1)+4 exactly: n=4 9@+18, 8 33@+86, 16 81@+222. T is a worst-case composition (max value: 7@+4, 21@+16, 49@+40) | n-3 windows; F12 |
| F12 | `bit.div10.cmp_sub_10` | div.fj:16 | 4@+12 | 4 ifs of the worst path + 4 ops (time) | T: 4@+12 (4@+8 with F1) / S: 5@+18 | the body has FIVE ifs + 8 single ops | T v=12,13 4@+8; v=0 2@+2; v=16,19 2@+6; S 5@+18 at every v | space has every if |
| F13 | `bit.div_loop` | div.fj:197 | S: n(25@+22) | matches no composition | S: n(29@+17) (idiv_loop S n(37@+58) -> n(41@+53) follows) | if0 n b n(@+2), zero R,Q,i n(3@-3), mov A n(2@-2), if0 n i n(@+2), shl R n(2@-1), cmp n(3@+6), sub n(8@+16), xor n n(@-1), shr i + shl A n(4@-2), mov r,q n(4@-4), A,R,Q,i 4n | n=4 115@+79, 8 231@+151, 16 463@+295 = n(29@+18)-@+7 (+n: sub's space via F6) | ~4@ a bit missing |
| F14 | `bit.output` | output.fj:2 | @+2 | xor @-1 + label_ptr + IO+1 + not (time, x=1) | T: @+2 / S: @+3 | space adds `IO+0;end` | T 1@+1 (0), 1@+2 (1); S 1@+3 | both exits are space |
| F15 | `bit.print_as_digit n` | output.fj:56 | @+9 | one digit | T: n(@+9) / S: n(@+10) | n digits | n=1 1@+8/1@+9, 4 4@+35, 16 16@+133 (random bits); S n(@+10) | n left out |
| F16 | `bit.print_hex_uint n` | output.fj:70 | n(7@+11) | cannot be reconstructed (n/4 x print_digit's 29@+34 = 7.25@+8.5) | T: n(7.25@+8.5) / S: n(8.75@+16.5) (both follow batch 1's hex2ascii row) | n/4 x print_digit (T 29@+34, S F17 35@+66); there was no space line | digits all B: T n(7.75@+5)+2@+1 (n=4,16,64), S n(11.25@+23); all 7: T n(6@+2)+2@+1; all F: n(7.28@+4.8) | n/4 digits; S missing |
| F17 | `bit.print_hex_uint.print_digit` | output.fj:95 | S: 35@+57 | - | S: 35@+66 | if1 4 4(@+2), if1 @+2, one @, hex2ascii 21@+30, print 8@+16, 2 jumps, the 8-bit `ascii` | S 45@+91 (hex2ascii measured here S 31@+47, T B 21@+8, 7 14@-7; print S 8@+24 by F14); T B 31@+20, 7 24@+8, skipped 0 5@+6 | buffer + jumps |
| F18 | `bit.print_dec_int` | output.fj:224 | S: n(16@+23) | print_dec_uint + ONE neg | S: n(18@+28) (n(18@+30) with F5) | print_dec_uint n(14@+16) + TWO neg n(2@+6) | n=4 81@+140, 16 300@+581, 64 1227@+2402 = n(19.3@+37.9) (print_dec_uint's own S measures n(15.1@+23), via F12) | it negates twice |
| F19 | `bit.pointers.set_jump_pointer` | pointers.fj:25 | 2n@ | (n unbound) | 2w@ | 2w double_exact_xor at @ | S exactly 2w@ (64@+0 w=32, 128@+0 w=64); T 2w(@-1) + ones(old) + ones(ptr): 64@-57, 128@-119 | n is w |
| F20 | `bit.ptr_flip_dbit` | pointers.fj:82 | 2w@ + 2@ | ptr_flip + 2 passes "much less than @/2" | 2w@ + @ + 2#dbit | each `comp_flip_if` pass emits and runs #dbit ops (also for 0-bits) | S = ptr_flip's + 2#dbit exactly: 129@+12 vs 129@-2 (w=64, #dbit 7), 65@+10 vs 65@-2 (w=32, 6) | comp_flip_if is always 1 op |
| F21 | `bit.ptr_wflip` | pointers.fj:105 | 3w@ (actually a bit smaller, 3w@+3w) | set_flip 2w@ + w advances with a wflip pair each | T: 2w@ + 3w - 2 + ones(value)(@+1) / S: 3w@ + 3w - 2 | time: set_flip 2w@, w comp_if jumps, the advances flip 2w-2 bits, a wflip pair + the to_flip op only for value's 1-bits; space: all w pairs | S exactly 3w@+3w-2 (192@+190 w=64, 96@+94 w=32); T value dw vs arr: +8@+11 for 8 more 1-bits (w=64), +10@+10 for 10 (w=32) | 3w@ is the space |
| F22 | `bit.ptr_inc` | pointers.fj:179 | S: w(2@+6) | inc n at n = w | S: (w-#w)(2@+6) (T 6@+8 by F3) | it increments w-#w bits (as hex.ptr_inc's (w-#w)(@+18)) | S 115@+344 = 57(2@+6)+@+2 (w=64), 53@+158 = 26(2@+6)+@+2 (w=32) | n is w-#w |
| F23 | `bit.ptr_dec` | pointers.fj:184 | T: 2w + 5@+12 / S: w(2@+6) | dec n at n = w | T: 2(w-#w) + 6@+8 / S: (w-#w)(2@+8) | as F22 with dec's two not | T 4@+119 (w=64, t=0: 4@+5+2*57), 8@+63 (w=32, t=2: 8@+11+2*26); S 115@+458, 53@+210 | n is w-#w; F4 |

Consistent with their docs (no row): xor (n), exact_xor, double_exact_xor, address_and_variable_xor, xor_zero (n), or
(n) (T 2@+1 with F1), not (n), exact_not; inc1 / inc1_with_carry0_jump (T 2@+4 worst with F1, S 2@+6); add n, sub n
(S n(8@+15) / n(8@+17) via F6; T worst n(8@+8) / n(8@+10)); mul_loop (T n^2(6@+2) composes worst cases that cannot all
happen - the two if0 n scans total n+1 tests an iteration, so the true worst is n^2(5@-1); kept as a worst case by the
convention; S n(21@+11) composes exactly); mul_add_if; div, div_step, idiv; idiv_loop (via F13); shr n, shl n, shra,
ror, rol (ror / rol's extra 2@-1 is 6%); cond_jumps beyond F1 (if n n(@+1), cmp 2@+2 / 3@+6, cmp n n(2@+2) / n(3@+6));
input_bit, input, input n; print, print n, print_str, print_as_digit (space via F14); print_hex_int (= print_hex_uint
+ 2n, via F16); print_dec_uint (T n^2(2@+4) / "nd(7@+12)" compose div10's worst windows; measured at n = 64: value max
5935@+1515, value 1 499@-59, about nd(4.5@); S n(14@+16) composes); div10_step, print_char (5@+12 = the measured worst
digit 7); ptr_init, set_flip_pointer, ptr_jump, ptr_flip; xor_to_ptr, ptr_wflip_2nd_word, xor_from_ptr,
exact_xor_from_ptr (via F20 / F21; xor_from_ptr: T 6w@ + 6w + 2 ones(label)(@+1) + 2, S 8w@ + 6w; measured S 512@+387
w=64, 256@+195 w=32).

Dependents to re-derive once rows are accepted (direct callers in this batch): F1 -> if0, if1, if n, if0 n, if1 n, cmp,
cmp n, cmp_next_eq, or, or n, and n, inc1, inc1_with_carry0_jump, add1, cmp_sub_10, print_str_one_char, print_char,
mul_add_if, div_step; F3 -> dec, neg, ptr_inc, ptr_dec; F6 -> add n, sub n, mul10, mul, mul_loop, div, div_loop;
F12 -> div10 -> print_dec_uint -> print_dec_int; F13 -> idiv_loop; F14 -> print, print n, print_str, print_as_digit,
print_hex_uint; F16 -> print_hex_int; F21 -> ptr_wflip_2nd_word -> exact_xor_from_ptr -> xor_from_ptr; F20 ->
xor_to_ptr. Other files call bit.if / bit.output / bit.inc too (the dependency-closure tool has them).

## Mutants (mutants2.py; controls CTRL_cmp_sub_10_12 and CTRL_input_n_order caught)

Missed by the tests:
- `idiv_no_b_restore` - idiv leaves b negated (17 programs, all pass);
- `idiv_loop_no_b_restore` (14);
- `div_no_b0_check` - div without `.if0 n, b, end` (99 programs: no test divides by 0);
- `div_loop_no_b0_check` (14);
- `mul_no_res_zero`, `mul_loop_no_res_zero` - res not cleared (no test calls the same mul twice);
- `div10_n4_skips` - div10 skips the division at n = 4 (204 programs: no test runs div10 / print_dec at n = 4);
- `print_str_7bits` - print_str tests only bits 0..6 for the terminator (hello_world_with_str only).
Caught only by a hang: `shr_zero_short` (`.zero times-1`) makes a div_loop program loop forever; the suite has no
per-test timeout, so the run was killed at 15 min with no verdict.
Caught: idiv_no_a_restore (by 1 catalog program only), mul_loop_no_src_restore, print_hex_int_no_restore,
print_dec_int_no_restore, print_dec_uint_no_zero_flag_reset / _flags_reset, input_bit_no_zero, ptr_wflip_2nd_no_restore,
ptr_flip_dbit_no_restore, shra_short, if_n_skips_bit_n-2, ptr_dec_as_inc, xor_to_ptr_always, mul10_n_shl3, neg_as_dec,
sub_no_src_restore, print_as_digit_n_lsb_first.
No test exercises: the aliasing of B3 / MINOR 1-2, n = 0 / mul10 n = 1, b = 0 in any divide, input n's order beyond
`segments`. Tests to add with the fixes: idiv / idiv_loop with b < 0 checking b afterwards, x / 0 for all four divides,
mul / mul_loop called twice, print_dec_uint at n = 4, a print_str whose terminator check needs bit 7.
