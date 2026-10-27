# Whole-stl audit, batch 5: hex/pointers/* (origin/1.6.0 = 287f28b)

Reviewed at 287f28b in the read-only worktree C:/Users/tomhe/Documents/flipjump-audit2 (its `_fjcore.pyd` is 287f28b's).

**Files covered (every `def`, 88):**

- hex/pointers/basic_pointers.fj (9): ptr_init, wide_table_init, set_flip_and_jump_pointers, set_jump_pointer,
  set_flip_pointer, advance, advance_bit, stack_init, ptr_jump.
- pointer_arithmetics.fj (10): ptr_inc / dec / add / sub, ptr_index, ptr_index n, pointers.ptr_index, ptr_index_narrow,
  ptr_index_wide, shl_index.
- read_pointers.fj (16): read_hex / byte / cell, the _and_inc and n forms, read_nth_*, read_back, read_entry / _byte /
  _packed, both entry_address.
- write_pointers.fj (16): write_hex / byte / cell, zero_ptr, zero_cell_ptr, the _and_inc and n forms, write_nth_*,
  write_back, write_cells, advance_and_write_cell, write_cell h.
- xor_from_pointer.fj (9): xor_*_from_ptr and the chained read (xor_cells_from_inners_ptrs, read_cell_step,
  read_cell_chained, read_byte_ / read_wide_ / read_cell_from_inners_ptrs).
- xor_to_pointer.fj (16): ptr_flip, ptr_flip_dbit, xor_*_to_ptr (single and n), advance_and_xor_to_flip_ptr,
  xor_*_to_ptr_and_inc, both xor_hex_to_flip_ptr, xor_byte_to_flip_ptr, xor_cell_to_flip_ptr, ptr_wflip,
  advance_by_one_and_flip__ptr_wflip, ptr_wflip_2nd_word.
- stack.fj (12).
- Also: ptrlib.fj's stl.call (both forms), stl.return, stl.ptr_init and stl.stack_init (depth, time, the empty stack),
  and runlib.fj's PTR_CELL_BITS / PTR_WIDE_BITS knobs.
- bit/pointers.fj only where it shares code: stl.ptr_init lays bit.pointers.ptr_init right after hex.pointers.ptr_init.
  The two families share no label, register or table (bit.ptr_wflip copies the hex design; it is not shared code), so
  nothing there crosses into this batch.

Changed vs origin/main: all seven files (232f737 one shadow; ab44bb3 / 22e540d the cell-width tables; 8672d7d / 051b4ba
the n-cell ops; 47115cc / 74fcc24 ptr_index n and read_entry*; f0d3c7c read_back / write_back; the Complexity rounds).

## Tools

All in this folder. Every run went through `heavy.py audit5 --light`, one process at a time (chains `run1.sh` ..
`run5.sh`, progress in `run*.progress`).

- **`edge5.py`**: edge values, one program per (group, w, knobs).
  - Each case is `cs#K: <code> ce#K:`. The program runs in a python tracer; at ce#K the tracer reads the case's words
    straight from memory (no output encoding) and compares them with python's values.
  - Every result is preset dirty and sits between guard words. Every cell array has a guard cell on each side. The
    pointer variable is checked too: unchanged, or moved by exactly what the op documents.
  - **STATE, after every case:** to_flip's first word == to_jump's second word == to_ptr_var (the one-shadow
    invariant). to_flip+w, to_jump's flip word, ret_after_read_byte / _wide, hex.tables.res / ret, hex.add / sub /
    cmp.dst, hex.mul.dst / ret and bit.pointers.to_flip / to_jump must equal their image words. At the end of each run
    the whole decoder table(s) must equal the image.
  - Groups: single; seq (the n forms); arith (ptr_inc .. ptr_index n, entry_address, read_entry*); stack (push / pop at
    depth, call / return recursion to depth 12, call with parameters, a stale byte under a call); top (cells in a
    `segment` that ends at the LAST op of memory); probe (one program a case: the constant-0 forms, the empty stack,
    misaligned pointers, a cell holding more than PTR_CELL_BITS bits); selftest.
  - `--cell N --wide N` assemble with the knobs (a defines file, as `fj -D` writes it).
  - `selftest` (R9): a wrong expected value, a write into a guard cell, and two state-dirtying ops (`hex.not` on
    to_ptr_var, a wflip into to_flip+w) must all be reported. PASS at w=64 and w=32 (`edge_selftest.log`).
- **`m5specs.py`**: batch 5's specs for the checker's `cxm.py` (`cxm.py --selftest` PASS, `cxm_selftest.log`).
  - Pointer-op time depends on the pointer's VALUE, so every pointer spec runs at three placements of its cells:
    - **LO**: op 2^20, so the pointer has one on-bit;
    - **MID**: `segment 0x5a5a..`, 1.5 on-bits a hex;
    - **HI**: `segment (1<<w) - 64*dw`, the top of memory, about 3.4 on-bits a hex.
  - Before each call the setup arms the same pointer once, so the arm clears the same value it sets. The stack specs
    move hex.pointers.sp into LO / MID / HI.
  - Its `--selftest` (R9): the arm's plain ops must equal the prediction from the pointer's hexes EXACTLY (per pass and
    hex h: 1 + 3*popcount(h), 2 for h = 0), and a prediction one op off must be rejected. EXACT at all three placements
    (`m5_selftest.log`: LO 32@-60, MID 32@+56, HI 32@+216).
  - Rows: `m_SING_w64/32.json` (37 single ops x 3 placements), `m_SEQ` (6 n forms x n = 1, 4, 16 x 3), `m_IX`
    (ptr_index n, entry_address, read_entry*), `m_STK` (the stack, stl.call / return), `m_X` (ptr_jump, ptr_wflip with
    half the bits set, idx_n = 16).
- **`lines5.py`** (every measured row against the code's Complexity line, at @ = 18.5) and **`slopes5.py`** (n = 4 -> 16
  slopes).
- **`emptystack.py`**: stl.return on an empty stack under the real interpreter (flipjump.run), on 287f28b and on a fixed
  copy, in a small and a larger program.
- **`fixstl.py`**: the fixed stl copies (`fix/fix_stack`, `fix/fix_ptradd`, and `fix/fix_all` = both + batch 3's B2
  guard), and the identity check of the ptr_add fix.
- **`mutants5.py`**: batch 3's runner with batch 5's table, in `mtree/` (= `git archive 287f28b` + the engine).
  - It runs pytest with `-x` and a bounded program set: 53 of the 183 programs that reach a pointer macro.
  - `UNIT` mutants run `tests/unit/test_ptr_cell_bits.py --unit-tests`.
  - Each mutated file is restored after its run. `verify_call.py` re-ran one verdict without `-x`.

## Edge runs

The groups ran at these widths and knobs:

- single, seq, arith, stack and top at w=64 and w=32;
- single and seq at w=16, one case a program;
- single, seq, stack and top at the knobs (PTR_CELL_BITS, PTR_WIDE_BITS) = (12, 0), (16, 0), (8, 16) and (12, 16), at
  w=64 and w=32;
- top at (20, 0) at w=32 and w=64, single at (20, 0) at w=32, and top and single at (8, 20) at w=32.

Everything not listed under BLOCKING / MINOR passed. STATE was clean after every case, and the tables were intact at
the end of every run. Among the cases that passed:

- **single** (142 cases a w):
  - read / xor-from / write / zero / xor-to of hex, byte and cell, at cells 0, 3 and 7, with dirty dsts;
  - ptr_flip of value bits 0, 3 and 7; ptr_flip_dbit; ptr_wflip at the 2nd word; ptr_wflip_2nd_word;
  - every _and_inc form (the value, and ptr + 2w);
  - read_back after a read, and write_back after an _and_inc (armed before the inc);
  - read_nth / write_nth at index 0, +2 and -3; ptr_jump.
  - Aliases that work: read_hex p, p (a dw-aligned pointer's low hex is 0), xor_byte_from_ptr p, p, write_byte p, p (src
    is read after the arm), and read_nth_byte i, p, i.
- **seq** (73 cases):
  - every n form at n = 1, 2, 3, 5 and 8, offsets 0 and 1, with dirty dsts;
  - write_byte n across a 4096-op boundary (the advance carries through 12 bits);
  - read_back after read_byte n (it reads the last cell);
  - read_byte after write_hex 3 (read_byte's stale high hexes never leak).
- **arith** (178 cases at w=64, 166 at w=32):
  - ptr_inc / dec at 0, dw, 0x7f*dw, 0xfff*dw and the last op (it wraps both ways);
  - ptr_add / sub of 1, 5, 255, 256 and 4097 at low and wrapping bases;
  - ptr_index at index 0, +1, -1, 3, MAX, MIN and random;
  - ptr_index n at n = 1, 2, the last narrow n, the first wide n, w/4 - 1 and w/4 (both paths, dst preset to all ones,
    a guard after index[:n]);
  - **ptr_index n with dst == index on the wide path (74fcc24's fix): passes at every n.** The repo's test runs it at
    n = 7, 8 and 16 (`test_ptr_index_self` in ptr_index_n.fj; only n >= 7 takes the wide path at w=64).
  - entry_address at sizes 1, 2, 3 and 5 (shift and mul_const paths), idx_n 1 and 2;
  - read_entry n = 1, 2, 3 (and dst == idx), read_entry_byte (and dst == idx), read_entry_packed.
- **stack** (34 cases):
  - six pushes of mixed hex / byte to depth 6 and back; sp and every cell checked (push_hex keeps the high hex of a
    stale byte, as documented);
  - push / pop n at n = 1, 2, 3 and 5; sp_inc / dec / add / sub;
  - push_ret_address + pop_ret_address by hand;
  - **a stale byte under a call** (push_byte, pop_byte, stl.call, push_hex, pop_byte): zero_ptr clears the byte;
  - **stl.call recursion to depth 1, 5 and 12**: the max sp, sp after, the returns counted, and a hex pushed at each
    level popped back;
  - stl.call g, 1 with g reading its parameter at sp-1; stl.call g, 3; stl.get_sp.
- **top** (9 cases):
  - read_byte / write_byte of the LAST op of memory, and read_byte 3 / write_byte 3 ending at it;
  - xor_byte_to_ptr 6 over the whole top segment;
  - ptr_inc and read_byte_and_inc of the last op (ptr wraps to 0); read_nth_byte -1 from 0;
  - ptr_flip of bit 2^w - 1.
- **knobs**: everything above at (12, 0), (16, 0), (8, 16) and (12, 16). That covers read_cell / write_cell /
  zero_cell_ptr through the wide table on narrow cells, write_byte keeping the top of a 12 / 16-bit cell, and the stack
  on wider cells. At 20 bits: top at (20, 0) at w=32 and w=64, top and single at (8, 20) at w=32, and the 124 non-alias
  single cases at (20, 0) at w=32.
- **w=16**: every single op passes. The n forms pass at n = 1 and 2; at n >= 3 they do not fit (47 probes hit the
  assembler's "Unknown exception ... please report": the image is over 2^16 bits, batch 1's MINOR 1).
- **probe**: `sp_add 0`, `ptr_add p, 0`, `push 0`, `pop 0`, `ptr_wflip p, 0` and `ptr_wflip_2nd_word p, 0` run.
  `read_hex 0` / `read_byte 0` are refused at assemble time (by design).

## BLOCKING

### B1. `stl.return` on an empty stack never reaches the error handler: the run stops silently

Where: basic_pointers.fj:176 (`hex.hex stack_error_handler`, in hex.pointers.stack_init). main has the same line.

- **Cause:** stack[-1] is meant to jump to `stack_error_handler` (basic_pointers.fj:179-181), which prints "ERROR: You
  returned on an empty stack."
  - But `hex.hex val` clamps its value to 0..15 (memory.fj:10-12; batch 4 MINOR 5), so stack[-1] is `;15*dw`.
  - A return on the empty stack therefore jumps to **op 15**, inside ptr_init's `pad 1<<PTR_CELL_BITS`.
- **Reproducer** (`emptystack.py`, the real interpreter):

  | program | 287f28b | stack[-1] = `;stack_error_handler` |
  |---|---|---|
  | `stl.startup_and_init_all`, `stl.return` (w=64) | output `b''`; ends `ip<2w` after 439 ops (stack[-1]'s jump word 0x780 = op 15, and op 15 is `0;0`) | `b'\n\nERROR: You returned on an empty stack.\n'`, 767 ops |
  | the same at w=32 | `b''`, 183 ops (op 15) | the message, 511 ops |
  | 180 pointer ops, `stl.output "before"`, `stl.return`, `stl.output "after"` (w=64 and w=32) | `b'before'` only | `b'before'` + the message |

  Here op 15 is an empty pad op, so the run ends at once, and the documented diagnostic never prints. (A pad slot that
  held a wflip-chain op would instead flip a bit and carry on elsewhere.)
- **Untested:** no test returns on an empty stack. The mutant `empty_stack_message_changed` passes every test.
- **Smallest fix (1 line, basic_pointers.fj:176):** `;stack_error_handler`, in place of `hex.hex stack_error_handler`.
  - Verified (`fix/fix_stack`, `emptystack.log`): the message prints at w=64 and w=32. The stack group (34 cases, depth
    12) still passes (`fix_stack.log`).
  - Side effects: every program with a stack changes stack[-1]'s word, so it is not byte-identical (`fixstl.log`). A pop
    on an EMPTY stack now jumps through stack[-1] too (`fix_probe.log`); it silently read 0xf before. That is a user
    error either way.
- **Test to add:** a program that returns on an empty stack and expects the message (the run then ends at `ip<2w`).

### B2. `hex.ptr_add` / `ptr_sub` (and sp_add / sp_sub / `stl.call f, k`): a negative value moves the pointer the wrong way, and a value*2w >= 2^w writes past the pointer

Where: pointer_arithmetics.fj:27 and :36 (`hex.add_constant w/4, ptr, value * dw` and the sub_constant twin). main has
the same lines.

- **Cause:** add_constant / sub_constant need a non-negative constant that fits dst (batch 3 MINOR 5 and B1). The docs
  of ptr_add / ptr_sub say only "ptr[:w/4] += value * 2w" / "-=", with no range.
- **Reproducer** (`edge5.py <stl> arith 64 32`, `edge_arith2.log`):

  | call | p before | got | right (mod 2^w) |
  |---|---|---|---|
  | `hex.ptr_add p, -1` (w=64) | 7*dw = 0x380 | 0x400 (+1 cell) | 0x300 |
  | `hex.ptr_add p, -3` (w=64) | 0x380 | 0x1200 (+29 cells) | 0x200 |
  | `hex.ptr_sub p, -2` (w=64) | 0x380 | 0xfffffffffffff480 | 0x480 |
  | `hex.ptr_add p, 1<<57` (w=64; 1<<26 at w=32) | 0x380 | p is right, but **the hex AFTER p changes, 5 -> 6** | p unchanged, guard 5 |
  | `hex.ptr_sub p, 1<<57` | 0x380 | **the hex after p: 5 -> 4** | guard 5 |

  The same at w=32. sp_add / sp_sub / `stl.call f, k` are ptr_add / ptr_sub on sp. Also confirmed: `hex.ptr_sub p, 0`,
  `hex.sp_sub 0` and `stl.call f, 0` do not assemble (`edge_probe.log`: `negative shift count`; batch 3's B2).
- **Smallest fix (2 lines):** `hex.add_constant w/4, ptr, (value * dw) & ((1<<w)-1)`, and the same in ptr_sub.
  - A non-negative in-range value assembles to the same constant, so every existing program is byte-identical.
    `fixstl.log`: a program with ptr_add, ptr_sub, sp_add, sp_sub, push, `stl.call f, 2` and read_byte, at w=64 and
    w=32: "fix_ptradd .fjm identical to 287f28b: True".
  - Verified together with batch 3's sub_constant guard (`fix/fix_all`): `fix_arith.log` passes every NEG and BIG case
    (only the ALIAS cases of MINOR 2 remain), and `fix_probe.log` assembles and runs `ptr_sub p, 0`, `sp_sub 0` and
    `stl.call f, 0`.
  - Cost: a negative value now adds 2^w - |value|*2w (about w/4 hexes of add_constant). ptr_sub of |value| is the cheap
    spelling, which the doc can say.
  - Doc-only alternative: "value >= 0 and value*2w < 2^w (use ptr_sub to move back)" on ptr_add / ptr_sub / sp_add /
    sp_sub.
- **Tests to add:** ptr_add p, -1 and ptr_sub p, -1; the guard after p for a value*2w >= 2^w; `stl.call f, 0`.

## MINOR

1. **Single read_byte / read_cell: dst must not overlap ptr, undocumented** (read_pointers.fj:18, :29).
   - They zero dst before arming ptr, so `hex.read_byte p, p` reads the cell at (p with its low byte cleared).
   - Wrong whenever the pointer's low byte is not 0: `edge_single.log` k=2 at w=64 (got 0x4506a04, want 0x4506ab1), and
     k=2, 3 at w=32. At PTR_CELL_BITS 12 / 16 and with the wide table, read_cell p, p fails at every k. At w=16 and at
     20-bit cells it reads an unmapped word.
   - read_hex p, p works (a dw-aligned pointer's low hex is 0), and so do xor_*_from_ptr, write_* and read_nth_*. The n
     forms already say "dst does not overlap ptr".
   - Fix: the same sentence on read_byte and read_cell (and on read_hex, for clarity).
2. **`hex.ptr_index dst, ptr, index`: dst must not alias ptr, undocumented** (pointer_arithmetics.fj:39-46).
   - `mov dst, index` overwrites ptr first, so `ptr_index p, p, i` gives 2*i*2w (0x500 for base 0x2000 and i = 5).
   - The n form documents it ("dst must not alias ptr"; its narrow path happens to support it, the wide path does not).
   - Fix: copy that sentence.
3. **A cell must hold a dw multiple below 2^PTR_CELL_BITS * dw, and a pointer must be dw-aligned. Otherwise the result
   is a wild jump, not a wrong value.** Every read / write doc says only "dw-aligned".
   - `edge_probe.log`: read_byte of a cell `;0x1ff*dw` jumps to a null ip.
   - read_byte / write_byte with p = cell + 1, cell + w or cell + dw/2 + 7 jump to a misaligned ip.
   - A user array of `;label` or 16-bit values hits this.
   - Fix: one line in ptr_init's doc (and in read_hex's): "*ptr must be a hex / byte cell, a value below
     2^PTR_CELL_BITS times dw; anything else jumps outside the table".
4. **xor_cell_to_flip_ptr's doc says PTR_CELL_BITS/4 hexes, but the code xors PTR_WIDE/4** (xor_to_pointer.fj:126-128
   against :136). With a wide table it covers the wide cell. Fix: PTR_WIDE/4 in the three lines.
5. **read_back / write_back after a wide-cell op is a wild jump** (read_pointers.fj:136-137): they run the NARROW dance on
   the armed cell. Add to the @Assumes: "and the armed cell is a narrow one (not after read_cell / write_cell /
   zero_cell_ptr with a wide table)".
6. **The knobs' comment (runlib.fj:7-45): batch 1's MINOR 6 is still open at 287f28b.** The maxima, measured:
   - The stated ceiling "25 at w=32 and 56 at w=64" ignores the multiple-of-4 rule: it is 24 at w=32. At w=16 it is 8,
     and no wide table is possible (12 is over dw - dbit - 1 = 10).
   - PTR_CELL_BITS >= 8 and PTR_WIDE_BITS > PTR_CELL_BITS are enforced (basic_pointers.fj:29, :82) but not stated.
   - The practical ceiling is the assembler, not dw. 20 bits works (a 2^20-op table: (20, 0) at w=32 and w=64, (8, 20)
     at w=32). 24 at w=32 means a 2^24-op table, which was not built here (an assembly of that size is a heavy job).
     56 at w=64 cannot be assembled.
7. **The time of every pointer op depends on the pointer's value, and no doc says so** (batch 1's MINOR 9,
   quantified).
   - An arm (set_flip_and_jump_pointers) is w/2 pad-16 wflips plus, per pass and hex h, 1 + 3*popcount(h) plain ops (2
     for h = 0), exactly (`m5_selftest.log`).
   - That is w(0.5@-0.94) at LO, w(0.5@+0.88) at MID, w(0.5@+3.4) at HI and w(0.5@+4.5) for all-f hexes. The lines
     charge w(0.5@+4), which rev 7 section 3 calls "the dense case".
   - stl.call + stl.return with sp at LO / MID / HI: 175@+274.5 / 175@+733.5 / 169@+1372.5, that is 3512 / 3971 / 4499
     ops at @ = 18.5 (w=64, `m_STK_w64.json`).
   - ptr_inc / ptr_dec run a carry / borrow chain. ptr_dec of 0x8000000 (LO) borrows through 6 hexes: 11@+22.5 against
     the line's 7@+37. ptr_inc with no carry is 6@+5.5. The lines are averages, as main's "on average" note said.
   - Fix (doc): one sentence in ptr_init's doc: "every macro that arms a pointer costs, per arm, w/2 table wflips plus
     1 + 3*popcount(h) a hex and pass (2 for a 0 hex): the lines charge the dense w(0.5@+4)".
8. **Asymmetries between the read side and the write side:**
   - `hex.xor_cell_to_ptr` is missing. The read side has xor_cell_from_ptr; the write side has only the internal
     hex.pointers.xor_cell_to_flip_ptr.
   - `xor_hex_from_ptr n` / `xor_byte_from_ptr n` are missing, while xor_hex_to_ptr n / xor_byte_to_ptr n exist. (The
     chain hex.pointers.xor_cells_from_inners_ptrs is there; read_hex n / read_byte n zero first.)
   - `xor_hex_to_ptr_and_inc` / `xor_byte_to_ptr_and_inc` live in hex.pointers (xor_to_pointer.fj:85-103), while every
     other _and_inc is in hex. There is no xor_*_from_ptr_and_inc.
   - read_entry / read_entry_byte / read_entry_packed have no write_entry twin. The array is a constant ADDRESS, not
     constant data, so writing an entry is meaningful.
   - Symmetric, as they should be: read_hex / byte / cell and write_hex / byte / cell, the _and_inc and n forms of hex and
     byte, read_nth_* and write_nth_*, read_back and write_back, zero_ptr / zero_cell_ptr, push_* and pop_*.
9. **Undocumented requirements:**
   - the read / write / xor / flip / jump macros need stl.ptr_init (only the nth and read_entry docs say so);
   - the _and_inc forms also need hex.add.init (ptr_inc);
   - stack.fj's macros need stl.stack_init and hex.add / sub.init (only ptrlib.fj says "@requires the stack_init");
   - entry_address with a size*2w that is not a power of 2 runs hex.mul_const.
10. **Small doc errors:**
    - "For w=32/16, add 0.25@/0.5@ in both complexities" (read_nth_*, write_nth_* and ptr_index: 5 lines) means inside
      the w(...) term. Measured at w=32: ptr_index is 75@ = w(2.25@) + 3@, not 67.25@; read_nth_hex is 96@ =
      w(2.75@) + 8@. Say "w(2.25@+...) at w=32".
    - ptr_flip_dbit's "@+6" (xor_to_pointer.fj:19) is w=32's 2*popcount(dbit). At w=64 it is +8 (measured 33@+64,
      against ptr_flip's 33@+56).
    - "dst is a hex[2:]" (xor_from_pointer.fj:15) and "the byte hex[2:]" (xor_to_pointer.fj:118) mean hex[:2].
    - ptr_init's "@output-param read_byte: hex[:2] variable. You want to zero it before jumping into ptr_jump"
      (basic_pointers.fj:10): it is hex[:PTR_WIDE/4], and the read dance zeroes it itself.
    - ptr_init's Space line leaves out the wide table: + 2^PTR_WIDE_BITS + 1 + (PTR_WIDE - PTR_CELL_BITS)/4 when
      PTR_WIDE_BITS > 0.
    - push n / pop n (stack.fj:74, :110) assume n is even. n = 1 costs a whole push_hex / pop_hex, twice the line's
      n(w(0.25@+2) + 11@+39) (measured 47@ against 27@ at w=64). Within Rule A at n = 16.
    - ptr_wflip / ptr_wflip_2nd_word (xor_to_pointer.fj:179, :202): w(1.5@+7) is the case where every bit of value is
      set (measured 96@+484 at HI). In general the cost is w(0.5@+6) + popcount(value)(@+1): measured 64@ for half the
      bits set. Worth saying, because the callers below pass addresses.
11. **Untested macros** (no program reaches them): hex.read_hex_and_inc, hex.write_hex_and_inc,
    hex.pointers.xor_hex_to_ptr_and_inc and hex.pointers.xor_byte_to_ptr_and_inc. Each passes `edge5.py single`.

### The code's doc against the owner-reviewed table (frontline rev 7)

Every pointer row of rev 7 equals the code at 287f28b, except two:

| macro | code | rev 7 table |
|---|---|---|
| read_hex n | n(4@+28) / n((w-#w)(@+18) + 2@+49) | n(5@+28) / ... + 3@+61 |
| write_hex n | n(10@+38) / ... + 8@+110 | n(11@+38) / ... + 9@+122 |

051b4ba ("the n-cell ops zero only the h read_byte hexes they read") came after rev 7. The measurement agrees with the
CODE (slopes n = 4 -> 16 at w=64: read_hex n 3.83@+24.5, write_hex n 9.83@+37.2). The table, not the code, is stale.

## Front-line table

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

## Mutants

Run with mutants5.py through test_fj (`mutants5.log`), on the programs whose text reaches each macro (53 at most).
The control, CTRL_read_table_bit (decoder-table entry d flips hex-bit #d instead of #d-1), was caught by
hexlib-read_entry. The UNIT control (the `PTR_CELL_BITS < 8` guard removed) was caught by test_ptr_cell_bits.

**MISSED by the current tests:**

| mutant | change | evidence |
|---|---|---|
| `empty_stack_message_changed` | stack_error_handler prints "?" (basic_pointers.fj:180) | 53 programs pass: nothing returns on an empty stack (B1: the handler is unreachable today) |
| `ptr_add_negative_masked` (B2's fix) | `(value * dw) & ((1<<w)-1)` in ptr_add | 53 programs pass: no test passes a negative or overflowing value (and B2's fix changes no existing binary) |
| `advance_skips_top_bit` | the advance never carries into bit w-1 (`rep(w-#w-1, i)`, basic_pointers.fj:149) | 53 programs pass: no n-cell op crosses address 2^(w-1) or wraps the top of memory |
| `ptr_index_narrow_no_zero_scaled` | ptr_index_narrow without `..zero sw, scaled` (pointer_arithmetics.fj:84) | hexlib-ptr_index_n passes: each of its sites runs once, so the stale `scaled` of a second run at the same site (a loop) is never seen |
| `entry_address_no_zero_scaled` | entry_address without `..zero sw, scaled` (read_pointers.fj:212) | hexlib-read_entry passes: the same, no read_entry site runs twice |
| `xor_hex_to_ptr_and_inc_no_inc`, `read_hex_and_inc_no_inc`, `write_hex_and_inc_no_inc` | the _and_inc without its ptr_inc | no program reaches these macros (MINOR 11) |
| `UNIT cell_bits_dw_guard_removed`, `UNIT wide_bits_dw_guard_removed` | the `dbit + bits >= dw` guards deleted (basic_pointers.fj:31, :80) | test_ptr_cell_bits passes (31 passed): its bad widths 4, 7, 10 / (8, 8), (8, 10), (16, 12) never reach the dw bound |

**Caught:**

- read_byte_zeroes_1_hex (cat_ptr_write_at_offset, hex_func7), read_hex_no_zero (hexlib-nth_pointers),
  read_hex_n_zero_short / read_byte_n_zero_short (hexlib-read_entry), read_back_zero_1_hex (hexlib-read_write_back);
- push_ret_address_no_zero_ptr (cat_fibonacci_recursive, hex_func7), pop_n_byte_order_reversed (the same);
- ptr_flip_dbit_xor_dbit_plus_1 (hex_func4), ptr_wflip_2nd_word_first_word (cat_fibonacci_recursive, hex_func7);
- UNIT read_cell_zeroes_2_hexes (5 failed), UNIT zero_cell_ptr_narrow_dance (3 failed).
- `call_params_no_sp_sub` is not a valid mutant: deleting the sp_sub leaves a parameter unused, which fails to parse
  (`verify_call.py`: the baseline passes, the mutant fails test_compile). hex_func6 / hex_func7 do reach
  `stl.call f, k`.

**No test reaches** (shown by edge5 or the probes, not by a mutant):

- a return on an empty stack (B1); ptr_add / ptr_sub with a negative or overflowing value, and the constant-0 forms
  (B2);
- dst overlapping ptr in the single reads, and dst == ptr in ptr_index (MINORs 1 and 2);
- a cell value >= 2^PTR_CELL_BITS, a misaligned pointer (MINOR 3);
- pointers at the top of memory and across 2^(w-1); a narrow ptr_index / entry_address site run twice;
- read_back after a wide op; the knobs' dw bound and 20-bit tables; w=16.

**Tests to add:**

- B1's empty-stack program; B2's ptr_add / ptr_sub -1, an overflowing value with a guard after p, and `stl.call f, 0`;
- read_byte p, p with a pointer whose low byte is not 0 (if MINOR 1 is fixed in code rather than doc);
- a loop over one ptr_index n (narrow) and one read_entry site with two different indexes;
- read_byte n / write_byte n across 2^(w-1) (a `segment` there);
- PTR_CELL_BITS = 60 at w=64 (or 28 at w=32) must be refused: the dw guard's own test.
