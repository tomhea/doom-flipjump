# Whole-stl audit, batch 1: runlib, ptrlib, casting, bit/casting, bit/memory (stl-additions fcdba7f)

Written from the reviewer's report (the harness blocked its own write). The data and scripts are in this folder.

## BLOCKING

**B1. `bit.ascii2hex` corrupts its INPUT `ascii`** (bit/casting.fj:141; main has the same body).
- The cause: `.inc 3, ascii` is never undone.
- The effect: for the 16 inputs 0x40–0x47 and 0x60–0x67 the low 3 bits stay incremented, so 'A' comes back as 'B',
  'f' as 'g', and 'G' as '@'. The `hex` and `error` results are right for all 256 inputs.
- Repro: `edge.py <stl> ascii_all 64` gives 16 FAIL of 768; w=16 and w=32 fail the same.
- **Smallest fix (6 lines, `fix_ascii2hex.diff`):** compare the low 3 bits with 1 and 6 instead of incrementing and
  comparing with 2 and 7; on success, `.xor 3, hex, ascii; .inc 3, hex; .not hex+3*dw`. The labels become
  `six3: .vec 3, 6` and `one3: .vec 3, 1`.
- Verified: all 256 inputs at w=64, plus the w=16/32 subsets.
- Cost: success paths unchanged (±15, placement noise); the 'G' error path is cheaper; space +1.5 ops.
- Test: the 256-input sweep catches the old body (16 FAIL) and a mutant of the fix (2 FAIL).

## MINOR

1. runlib.fj:91/98/107: `startup_and_init_all` cannot build at w=16 (the init is ~7k ops, more than 2^16 bits),
   but the doc still quotes "6890 for w=16". At w=16 the assembler reports "Unknown exception … please report"
   (OverflowError), which is M9 of the pool hunt and already fixed on pool-relocatable.
2. ptrlib.fj:91–105: `fcall`/`fret`'s preconditions are undocumented: `ret_reg` must hold jump 0 between calls;
   `fret` executes the `ret_reg` op (it must be harmless, like `;0`); it is not re-entrant with the same `ret_reg`.
3. bit/casting.fj: no macro documents that its outputs must not overlap its inputs (`bin2ascii a, a` with bin=1
   gives '0').
4. bit/casting.fj:28: `dec2ascii` of 10–15 gives ':'..'?', undocumented.
5. bit/memory.fj:274: `swap n` with a and b partly overlapping silently rotates bits (a == b works).
6. runlib.fj:7–45: the pointer knobs' comment leaves out two enforced rules (PTR_CELL_BITS ≥ 8, PTR_WIDE_BITS >
   PTR_CELL_BITS). The usable maximum at w=32 is 24, not the stated 25.
7. `startup`'s "Complexity: 2" is its space; only 1 op runs.
8. Typo "(end error=0)" → "(and error=0)" at bit/casting.fj:67, :91 and :118.
9. `stl.call`/`return` time depends on the stack pointer's value (3380 vs 3674 ops deep); this is batch 5's
   hex.pointers.
10. README.md:79: a wflip costs the on-bits of the VALUE (measured: 0xff*dw → 8, 0 → 1, an address → @/2+1.8).

## Front-line table (old = origin/main; space without shared tails, pads not counted)

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

## Mutants the tests miss

- the B1 bug itself;
- `ascii2hex` two3→1;
- `bin2ascii` / `dec2ascii` / `hex2ascii` with `.zero 8`→7;
- `bit2hex` without `hex.zero`;
- `bit2hex n` zeroing n/4 instead of (n+3)/4;
- `bit.mov n` without its dst==src check;
- `swap` (1,1)→(0,0);
- `get_sp` copying w/4−1.

The common cause: every test starts with a clean dst. A dst preset to all ones catches all the zeroing mutants.
