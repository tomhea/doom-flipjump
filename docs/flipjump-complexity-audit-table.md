# The whole-stl audit: Complexity changes for the owner's review

**Written 2026-10-27, against flipjump 1.6.0 = 287f28b.** The audit reviewed every macro of the stl in six batches
(`docs/flipjump-audit-batch{1..6}.md`). These are the rows whose OWN Complexity line is wrong. No line is changed
in the code until you accept it. Accepted rows are then applied with their dependents, each dependent re-measured.

**The conventions** (rev 7, section 1 of `docs/flipjump-complexity-frontline.md`): origin/main is the baseline; a
wflip costs the popcount of its value (@/2 for an address, @/2 - k/2 for a pad-2^k one, 2 for the chained step);
no shared tails; pads not counted; no "~"; n-terms only; **Rule A**: drop a term at or below 15% of the line at size
16 (every size 16, w = 64, @ = 18.5), except the leading term; fixed-size lines keep every term. All numbers are
measured with `cxm.py` (exact executed ops; space without shared tails), whose selftest passed before every batch.

## Where your decision is needed beyond accept / reject

1. **Batch 5, F1-F5 (`stl.call`, `stl.return`, `push_ret_address`, `pop_ret_address`):** the reviewer's lines
   keep every term and two still say "~" / "(exact: ...)". Under Rule A they become:

   | row | macro | full line (measured 0.99-1.04) | Rule A (terms at size 16) |
   |---|---|---|---|
   | F1 | push_ret_address T | w(@+10) + 0.5@^2 + 20.5@ + 80 | **w(@+10) + 20.5@** (1824 + 379 of 2454; drops 171, 80) |
   | F2 | pop_ret_address T | w(0.5@+6) + 0.5@^2 + 7.5@ + 39 | **w(0.5@+6)** (976 of 1325; drops 171, 139, 39 = 26% together) |
   | F3 | stl.call T | w(@+10) + 0.5@^2 + 20.5@ + 81 | **w(@+10) + 20.5@** |
   | F4 | stl.call address, params T | w(@+10) + 0.5@^2 + 30.5@ + 132 | **w(@+10) + 30.5@** |
   | F5 | stl.return T | w(@+10) + 0.5@^2 + 7.5@ + 41 | **w(@+10)** |

   My recommendation: the Rule A column, as every other line. The `@^2` term is real: a return address has @/2
   on-bits, and each costs @+1 to write.
2. **Batch 5, F6 (`ptr_index n`'s narrow branch):** Rule A dropped its constants at n = 16, where the branch never
   runs (it runs for n <= 6 at w = 64). Measured at n = 6, the time constant is 19.6%: restore it. The space
   constant is 15.2% by derivation and 14.0% by measurement: **on the rule's edge, your call.**
3. **Batch 1 and batch 5 both touch `stl.call` / `stl.return`:** batch 1 their SPACE (and get_sp, fret), batch 5
   their TIME. They do not conflict; take both.
4. **Part B is not here yet:** the fix round now running will add the `hex.mul` row (its loop by non-zero hexes),
   the 28 macros with no Complexity line (batch 6 (a)), and the style-only rows (batch 6 (d3): "~", "exact",
   "on average", "Size Complexity"). They come as an addendum to this file.

## Count

| batch | files | rows |
|---|---|---|
| 1 | runlib, ptrlib, casting, bit/casting, bit/memory | 11 |
| 2 | bit/ (logics, math, mul, div, shifts, cond_jumps, input, output, pointers) | 23 |
| 3 | hex/ logics, math_basic, math, shifts, tables_init | 4 |
| 4 | hex/ mul, div, cond_jumps, memory, input, output, strings | 4 |
| 5 | hex/pointers, stl.call / return | 7 |
| 6 | screen.fj + cross-cutting | 0 |
| | **total** | **49** |

## Batch 1

| macro | current (main) | proposed | why |
|---|---|---|---|
| stl.wflip_macro | @ | @/2 (popcount of the value; 1 for 0) | measured at 3 values: the value's popcount |
| startup_and_init_all | ~7000 (6894 w=16) | 7159+2.75w+@ (does not fit w=16) | the n=100 form, below |
| startup_and_init_all n | 6725+2.75w+@+n | 7059+2.75w+@+n | the stack's 330 was left out; measured exactly 7064+2.75w+n |
| stl.stack_init | n+w/4 | n+w/4+330 | the error-message string (= hex.pointers.stack_init) |
| stl.call (space) | w(2.625@+49)+20@+231 | w(4.25@+78)+25@+298 | the call site emits push AND pop; 0.97–1.01 of measured |
| stl.call addr, params | T w(2.25@+10)+37@+57; S w(2.625@+49)+43@+251 | T w(2@+11)+37@+86; S w(4.63@+81)+32.5@+404 | the composition fixed (push + sp_sub; the space adds pop) |
| stl.return (space) | w(2.375@+34)+5@+67 | w(0.5@+22) | it is ptr_jump's space; the pop belongs to the call site |
| stl.get_sp | n(2@) / n(2@+24) | w(0.5@) / w(0.5@+6) | n was never bound |
| stl.fret | 1 | 2 | the landing op runs too |
| bit.hex2ascii | T 15@+7; S 21@+30 | T 14@-5 (0–7), at most 22@+21 (A, B); S 30@+39 | data-dependent; the old line cannot be reconstructed |
| bit.ascii2hex | 53@+86 | 41@+62 (a lower-case letter, the worst path) | the doc summed every compare at full width, a path no input takes |

Consistent with their docs, no row needed: fj, comp_if*, skip, output*, startup_and_init_pointers, ptr_init, fcall,
bit2hex(n), hex2bit(n), bin2ascii, dec2ascii, ascii2bin, ascii2dec, and all of bit/memory.

## Batch 2

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

## Batch 3

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

## Batch 4

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

## Batch 5

- Old = origin/main's line; the line at 287f28b (rev 7, owner-reviewed) is given too.
- Only macros whose OWN line is wrong.
- Measured with cxm.py through m5specs.py (convT / convS: each in-region address-valued wflip counts @/2 - k/2, a
  constant its popcount, pads not counted, no shared tails).
- Values at size 16 (w = 64, @ = 18.5). The arm's constant follows the pointer (MINOR 7), so the lines are compared
  with HI, the dense placement the convention charges.

| # | macro | file:line | main | 287f28b | old derivation | proposed | new derivation (numbers) | measured | reason |
|---|---|---|---|---|---|---|---|---|---|
| F1 | `hex.push_ret_address` | stack.fj:33 | T: w(2.25@+10) + 9@+51 | T: w(2@+11) + 20@+78 (S w(2.38@+50) + 16@+247 stays) | sp_inc 7@+29 + zero_ptr w(0.5@+4) + 13@+49 + ptr_wflip_2nd_word w(1.5@+7) (its two flips of ptr left out) | T: w(@+10) + 0.5@^2 + 20.5@ + 80 | ptr_wflip(v) = its arm w(0.5@+4) + the w advances 2w + popcount(v)(@+1). The w(1.5@+7) line is popcount(v) = w; here v is a return ADDRESS: @/2 on-bits by the value rule. So ptr_wflip_2nd_word = w(0.5@+6) + (@/2)(@+1) + 2, and + sp_inc + zero_ptr: w(@+10) + 0.5@^2 + 20.5@ + 80. Size 16: 1824 + 171 + 379 + 80 = 2454 (was 3520). | w=64 LO / MID / HI: 92@+200 / 92@+436 / 93@+760 (HI 2480.5: new 0.99, old 1.42). At/2 = 92 = 64 (two arms) + 6 (sp_inc) + 13 (zero_ptr) + 9 (the return address's popcount). w=32 HI: 63@+377 = 1542.5; new 1542 (1.00), old 84@+430 = 1984 (1.29). S: 168@+3460 (line 1.00). | the composition charges every bit of a value that is an address |
| F2 | `hex.pop_ret_address` | stack.fj:45 | T: w(1.5@+5) + 9@+23 | T: w(1.5@+7) + 7@+37 | ptr_wflip_2nd_word w(1.5@+7) + sp_dec 7@+37 | T: w(0.5@+6) + 0.5@^2 + 7.5@ + 39 | ptr_wflip_2nd_word of a return address w(0.5@+6) + (@/2)(@+1) + 2, + sp_dec 7@+37. Size 16: 976 + 171 + 139 + 39 = 1325 (was 2390.5). | w=64 LO / MID / HI: 49@+164.5 / 47@+280.5 / 48@+439.5 (HI 1327.5: new 1.00, old 1.80). w=32 HI 31@+209.5 = 783: new 837 (1.07), old 1278.5 (1.63). S 123@+1873.5 (line 1.00). | as F1 |
| F3 | `stl.call address` | ptrlib.fj:27 | T: ~2.5w@ (exact: w(2.25@+10) + 24@+51) | T: ~2.5w@ (exact: w(2@+11) + 20@+78) | push_ret_address's line | T: ~w@ (exact: w(@+10) + 0.5@^2 + 20.5@ + 81) | F1 + the jump op. | call + return run together (the return is outside the measured region but executes inside it): w=64 HI 169@+1372.5 = 4499; new call + new return (F5) w(2@+20) + @^2 + 28@ + 122 = 4630 (1.03); the 287f28b lines 283@+1523 = 6758.5 (1.50). The @ coefficient: 128 (four arms) + 2 x 9 (the measured return address's on-bits) + 27 (sp_inc, zero_ptr, sp_dec) = 173; measured 169 .. 175. | as F1 |
| F4 | `stl.call address, params_stack_length` | ptrlib.fj:44 | T: <3w@ (exact: w(2.25@+10) + 37@+57) | T: <3w@ (exact: w(2@+11) + 30@+100) | push 20@+78 + sp_sub 10@+51 = 30@+129 (+100 does not reconstruct) | T: ~w@ (exact: w(@+10) + 0.5@^2 + 30.5@ + 132) | F1 + the jump + sp_sub 10@+51. Size 16: 2691 (was 3727). | call g, 2 + return: w=64 HI 177@+1385 = 4659.5; new + F5 4866 (1.04); 287f28b's 293@+1545 = 6965.5 (1.49). | as F1 |
| F5 | `stl.return` | ptrlib.fj:63 | T: w(2@+7) + 9@+23 | T: w(2@+11) + 7@+37 | ptr_jump w(0.5@+4) + pop_ret_address w(1.5@+7) + 7@+37 | T: w(@+10) + 0.5@^2 + 7.5@ + 41 | ptr_jump w(0.5@+4) + 2 (the jump and to_jump's op) + F2. Size 16: 2175 (was 3238.5). | inside F3 / F4's rows | as F1 |
| F6 | `hex.ptr_index n`, its narrow branch | pointer_arithmetics.fj:54-55 | (new: 47115cc) | T: n(8@+23) + w(0.5@) (if n+2 <= w/8 ...); S: n(6.5@+149) + w(0.875@+9.25) (if ...) | 013491f: T n(8@+23) + w(0.5@) + 18@+61 / S ... + 15@+302; Rule A dropped both ("11% / 9% at n=16") | T: n(8@+23) + w(0.5@) + 18@+61 (if n+2 <= w/8; else as now). S: as now, or + 15@+302 (borderline, below) | Rule A was evaluated at n = 16, where this branch never runs: it is taken only for n+2 <= w/8 (n <= 6 at w=64, n <= 2 at w=32). At its largest n (6, w=64) the time constant is 394 of 2012 (19.6%): kept. (It is the 2 hexes sw has beyond n, 2(7@+23), + 4@+15.) The space constant is 580 of 3823 (15.2%) by the derivation and 14.0% by the measured intercept (14@+269): on the rule's edge, the owner's call. | w=64, n = 1 / 2 / 4 / 6, T at HI: 57@-23 / 77@+15 / 91@+36 / 105@+60 (MID 57@-49 .. 97@+11). The line gives 0.74 / 0.65 / 0.74 / 0.81 of HI (0.76 .. 0.90 of MID); restored 1.12 / 0.92 / 0.97 / 1.00 of HI (the @ part: 58 against 57 at n = 1, 98 against 105 at n = 6). S n=1 76.5@+1008, n=6 109@+1744: the line 0.78 / 0.86, with the constant 1.01 / 1.02. w=32 n=1: T 41@-21 at HI (line 0.63), S 48.5@+729 (line 0.67). | Rule A applied outside the branch's domain |
| F7 | `hex.pointers.entry_address` | read_pointers.fj:200 (and the 6-parameter form) | (new: 47115cc) | S: sw(5.5@+137) + w(0.625@+7.25) | zero sw + xor idx_n + shl_index sw(3@+84) + set w/4 + add_shifted w/4, sw: the power-of-2 path only | S: sw(5.5@+137) + w(0.625@+7.25) (size*2w a power of 2; else hex.mul_const's for sw(3@+84)) | The time line already says "else hex.mul_const's for sw(3@+9)"; the space line leaves the mul_const path out. With mul_const's own line at c = 6w (on = 2, #c = 9: sw(14@+332)) in place of shl_index: sw(16.5@+385) + w(0.625@+7.25) = 106@+2004 at sw = 4. | size 3, w=64, idx_n = 1 / 2 / 4 (sw 4 / 5 / 7): S 128@+2198 / 148.5@+2627 / 189.5@+3500 (slope 20.5@+433 a sw hex). The line 0.47 / 0.45 / 0.41; w=32 0.43 / 0.41 / 0.38. With mul_const: 0.87 at sw = 4 (mul_const's own space line is about 17% under for a small c, batch 4). | a callee left out |

**Dependents if accepted:**

- F1-F5: the stl's callers of stl.call / return. None in the stl; the strings and screen code do not call.
  read_back's "not the ptr+w of ... stl.call / stl.return" note is unaffected.
- F6: none (the n form has no stl caller).
- F7: read_entry, read_entry_packed (their "sw(7@+23) (sw: entry_address's)" names the shift path only; a non-power-of-2
  entry size takes mul_const's), read_entry_byte (size 1: unaffected).
- ptr_wflip's own line stays: w(1.5@+7) is its every-bit-set case, kept as a worst case by the conventions. The doc
  sentence is MINOR 10.

### Owner-reviewed lines checked (rev 7): the code's doc equals the table, and the measurement agrees within the conventions

At w=64 and w=32, three placements each (`lines5.py`, `slopes5.py`):

| family | line | measured |
|---|---|---|
| the arm, set_flip_and_jump_pointers / set_jump_pointer / set_flip_pointer | w(0.5@+4) / w(0.5@+22) | exactly 1 + 3*popcount(h) a hex and pass (selftest); 32@-60 / 32@+56 / 32@+216 at LO / MID / HI; S 32@+1408 exact |
| the 37 single ops (read / xor-from / write / zero / xor-to of hex, byte, cell; the _and_inc forms; nth; ptr_flip(_dbit); ptr_wflip(_2nd_word); ptr_jump; read_back / write_back; ptr_index) | e.g. read_byte w(0.5@+4) + 7@+25 | the @ coefficient equals the line's in every row (read_hex 37@, read_byte 39@, write_byte 47@, zero_ptr 45@, write_nth_byte 178@, ptr_index 131@, read_back 7@, write_back 15@ at w=64). The constant follows the arm: HI 0.97 .. 1.12 of the line, MID 1.05 .. 1.31, LO up to 1.59. Space within 2% in every row (convS equal to the line to about 15 ops, 75 for nth / ptr_index) |
| the read dance, read_byte_ / read_wide_ / read_cell_from_inners_ptrs | 3@+25 at 8 bits | read_back 7@+14.5 .. 7@+23.5 against 7@+25; write_back 15@+50.5 .. +57.5 against 15@+49 |
| the n forms (read_hex / read_byte / write_hex / write_byte / xor_hex_to_ptr / xor_byte_to_ptr n) | n(4@+28), n(6@+32), n(10@+38), n(17@+50), n(7@+18), n(12@+30) (+ the arm, except write_byte n, which Rule A dropped at 12.7%) | n = 4 -> 16 slopes, w=64: 3.83@+24.5, 5.83@+19.8, 9.83@+37.2, 16.83@+47.9, 6.83@+21.0, 11.83@+36.5; S slopes 59@+1074, 61@+1112, 65@+1136, 72@+1235, 62@+1102, 67@+1177 against (w-#w)(@+18) + 2@+49 .. 10@+152 = 59@+1075 .. 67@+1178. w=32 the same @ slopes; S 28@+514 .. 36@+611 |
| ptr_index n, the wide branch | n(4@+9) + w(@+3.5) | n=7 101@+80 (1.02), n=16 131@+129 (1.07); slope n 8 -> 16 3.25@+5.2 (4@+9). S 1.00 at n=16 |
| entry_address (power of 2), read_entry, read_entry_byte, read_entry_packed | sw(7@+23); n(4@+28) + w(0.75@+5) + sw(7@+23); idx_n(8@+23) + w(0.75@+5); nb(6@+32) + ... | entry_address idx_n=16 (sw 16): 147@+96 (line 0.87); read_entry slope 4.17@+24.9; read_entry_byte slope 8@-8.5, idx_n=16: 186@-34.5 at MID (the line 176@+688: 1.16, its constant is the dense arm's); read_entry_packed slope 6.17@+19.6. At idx_n = 1 the dropped Rule-A terms show (0.6 .. 0.9), as the rule intends |
| push_hex / push_byte / pop_hex / pop_byte / push n / pop n | the setter + write / read + sp_inc / sp_dec | @ exact (47@, 53@, 43@, 45@ at w=64); push n slope 26.75@ (27@), pop n 22.75@ (23@); HI 1.04 .. 1.08 |
| ptr_inc / dec / add / sub, sp_* | 7@+29, 7@+37, 10@+43, 10@+51 | without a carry: 6@+5.5, 6@+7.5 .. 11@+22.5 (a 6-hex borrow), 9@+6.5, 9@+11.5 .. 13@+28.5: average lines (MINOR 7) |
| xor_hex_to_flip_ptr / xor_byte_to_flip_ptr / xor_cell_to_flip_ptr, advance / advance_bit, the chained read, write_cell h | by composition | inside the n-form and single rows above |
| ptr_init / stack_init | 0.5w + 2^PTR_CELL_BITS + PTR_CELL_BITS/4 + 3; n + w/4 + 330 | by count (the wide table: MINOR 10) |

## Batch 6

No row: all 13 `screen.fj` lines are exact in time and space (`define_palette`'s line drops two terms of 11% under
Rule A, as reviewed).
