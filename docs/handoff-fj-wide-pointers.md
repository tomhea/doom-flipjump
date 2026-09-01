# Handoff — WIDE POINTER READS for the FlipJump stl

**Phase 0 of the current M4 work.** Written 2026-09-01. Researched by six agents (two of them
adversarial refuters, both returning `refuted=False`), then **re-derived by hand at the owner's
insistence** — which was the right call, because the hand trace CORRECTED two of the agents'
conclusions. Nothing is implemented.

---

## 1. HOW THE POINTER READ ACTUALLY WORKS

Read this section before touching anything. Everything else follows from it.

### 1.1 A pointed-to value is an OPCODE, and the value IS its jump address

There is no "memory" to fetch from. A data slot is emitted as

    ;V * dw            // "flip nothing, then jump to V*dw"

so the value `V` lives in the opcode's **second word** (the jump address), scaled by `dw`. doom's own
emitter writes exactly this (`mapcompiler.py:398`), and so does `hex.hex` (`stl/hex/memory.fj:8`).

**This is why there is no "fetch width".** Reading is not moving bits out of a cell — it is *jumping
to the cell and letting it jump onward to a place that identifies its value*.

### 1.2 The decoder table turns "where we landed" into bits

`ptr_init` (`basic_pointers.fj:18-27`) lays a 256-entry table at op index **exactly 256**:

    pad 256
  read_ptr_byte_table:
    rep(256, d) stl.fj         d==0 ? 0 : (#d)<=4 ? (.read_byte    + dbit + (#d)-1)      // top set bit -> nibble 0
                           : (.read_byte+dw + dbit + (#d)-5),     //             -> nibble 1
        (d == ((1<<(#d))>>1)) ? .ret_after_read_byte              // that was the last bit: done
                              : read_ptr_byte_table + (d ^ ((1<<(#d))>>1))*dw

`#d` is d's bit-length, so `(#d)-1` is the index of d's **top set bit**. Entry `d` therefore:

  * flips that one bit into the shared `read_byte` register (nibble 0 for bits 0-3, nibble 1 via
    `+dw` for bits 4-7), and
  * jumps to entry `d` with that bit cleared — or to `ret_after_read_byte` if nothing is left.

**Landing on entry V xors V into `read_byte` in `popcount(V)` steps.** That is the "4/8" in the
table's own complexity note: 4 steps for a 4-bit memory, 8 for an 8-bit one — *the same table serving
two different widths*, which is the internal proof that 8 is not a width.

### 1.3 The trick: temporarily rewrite the slot so it jumps INTO the table

Table entry V sits at `(256 + V) * dw`. The slot jumps to `V * dw`. So if you can add `256*dw` to
the slot's jump word, the slot jumps to its own decoder entry.

`dbit = w + #w` (`runlib.fj:3`) is the offset from an opcode's start to its value bits. Flipping bit
`dbit + 8` of the slot touches bit `#w + 8` of its **second** word, which adds

    2^(#w+8) = 2^#w * 2^8 = dw * 256          (at w=32: bit 46, adding 16384 = 256*dw)

i.e. exactly `V -> V + 256`. **This is the owner's sentence — "making the pointer you want to read
from point to 256+val, and there is a table from address 256" — and it is literally true.**

### 1.4 The dance, step by step (`xor_from_pointer.fj:29-54`)

`set_flip_and_jump_pointers ptr` first writes the slot's address `P` into two globals:
`to_flip`'s **first** word (a flip target) and `to_jump`'s **second** word (a jump target). Then:

    1.  hex.zero 2, read_byte                                  clear the destination
    2.  wflip to_flip, dbit+8                  to_flip's flip address becomes P + dbit+8
    3.  wflip to_flip+w, read_ptr_and_flip_back, to_flip
                                               ... point to_flip's jump at (4), then JUMP to it.
                                               EXECUTING to_flip flips bit dbit+8 AT ADDRESS P --
                                               the data slot is now `;(V+256)*dw` -- and control
                                               continues to (4).
    4.  read_ptr_and_flip_back:
          wflip to_flip+w, read_ptr_and_flip_back^cleanup      re-aim to_flip's jump at (7)
          wflip ret_after_read_byte+w, to_flip, to_jump
                                               ... make the table's exit land on to_flip, then
                                               JUMP to to_jump -> jumps to P -> the (armed) slot
                                               executes -> jumps to (V+256)*dw = TABLE ENTRY V
    5.  the table walks popcount(V) entries, xoring V's bits into read_byte, then jumps to
        ret_after_read_byte
    6.  ret_after_read_byte jumps to to_flip -- THE SECOND VISIT -- which flips bit dbit+8 at P
        BACK, restoring the slot to `;V*dw`, and continues to (7)
    7.  cleanup: undo the three redirections

**`to_flip` is visited twice: once to arm the slot, once to disarm it.** The program rewrites the
data it is about to read, reads it by executing it, and puts it back. That symmetry is why the
setup survives (see 2.2) and why the whole thing is re-entrancy-hostile (`read_byte`, `to_flip`,
`to_jump` and `ret_after_read_byte` are single shared globals — this is doom's R42 rule).

### 1.5 What that costs

    set_flip_and_jump_pointers    w(0.75@+5)  = 24@+160 at w=32   <- PER DEREFERENCE, the whole cost
    the dance above               5@+13
    xor n, dst, read_byte         n@                              <- the only part that scales

which is why `read_hex` (1 nibble) and `read_byte` (2 nibbles) differ by 2@ out of ~33@, and why
`hex.read_byte 2, dst, ptr` — being `rep(2)` of the single form (`read_pointers.fj:63-66`) — pays
the **entire dereference twice**: 84@+374 against ~39@+173 for one wider read.

---

## 2. THE TWO PRIZES

### 2.1 A wider table — the owner's idea. FEASIBLE.

Nothing in section 1 knows how many bits `V` has. Widen it by changing **one constant in two
places** and building a bigger table:

    k     flip      adds        table must begin at op   entries    words
    8     dbit+8    256*dw      256                      256        512        (today)
    12    dbit+12   4096*dw     4096                     4,096      8,192
    16    dbit+16   65536*dw    65536                    65,536     131,072    (+0.26% of a 50M image)

The two `wflip to_flip, dbit+8` sites (`xor_from_pointer.fj:36` arming and `:52` disarming) must
agree; the decode-walk generalises to `read_word + (b>>2)*dw + dbit + (b&3)` for bit b; the shared
destination becomes `hex.vec 4`.

**Constraints, all verified by hand:**

  * **The table must begin at op index EXACTLY 2^k** — the flip adds exactly `2^k*dw` and entry V
    must land at `(2^k+V)*dw`. `pad 2^k` reaches exactly 2^k only if everything before it fits in
    2^k ops.
  * **Alignment is fine.** `P ^ (dbit+k) == P + (dbit+k)` needs P's low bits clear through
    `dbit+k = 38+k`, and dw-alignment gives 6 zero bits with `dw = 64`. **The hard ceiling is
    `dbit+k < dw`, i.e. k <= 25 at w=32 — so 16 is comfortable and 32 bits is impossible.**
  * **One table serves every width.** The walk strictly clears bits downward, so entries 0..255 of a
    2^16 table decode a byte exactly as today. With 16-bit slots, ONE primitive covers 1-, 2-, 3-
    and 4-nibble reads at one dereference each.
  * **The decode gets marginally cheaper**, not dearer: `popcount(16-bit)` equals
    `popcount(lo)+popcount(hi)`, and you pay one terminal return instead of two.

⚠⚠ **I MUST CORRECT THE RESEARCH HERE, AND IT INVERTS ITS CONCLUSION.** An agent reported that a
2^12 table "must sit below op 4096, which is BELOW `stl.startup_and_init_all`'s ~7,000 ops, so it
would force splitting that macro", and concluded 12-bit was the harder width. **That is wrong.**
`startup_and_init_pointers` is:

    stl.startup code_start      // Complexity: 2   <- TWO OPS
    stl.ptr_init                // pad 256; the table

**Only two ops precede the table.** `hex.init`'s ~6,725 ops come *after* it. So any power-of-two
size is placeable, and a *bigger* table is if anything easier. The real cost is the opposite one:
the table occupies `[2^k, 2^(k+1))` and pushes **the entire rest of the program above it** — for
k=16 the program starts near op 131,072 instead of ~512.

**⚠ WHERE `ptr_init` LIVES IS PART OF THE CONTRACT — do not "fix" it.** (Owner's clarification,
2026-09-01.) `ptr_init` is invoked BY `startup_and_init_all`, not before it and not after it:

    startup_and_init_all
        -> startup_and_init_pointers   = stl.startup (2 ops) + stl.ptr_init   <- the table
        -> hex.init                    (~6,725 ops, all AFTER the table)
        -> stl.stack_init

**and it should stay that way.** The table's address is not chosen, it is a consequence of this
nesting: `stl.startup` emits 2 ops, then `pad 2^k` rounds up to exactly `2^k`. A wider table is
therefore a change to `ptr_init`'s SIZE, never to its position — nothing needs to be hoisted,
split, or reordered, and moving `ptr_init` out of the startup chain would break the address the
whole mechanism depends on.

This is also what makes `-D ptr16` a clean opt-in: one macro's body grows, and everything after it
shifts up uniformly.

That last point is the genuine risk, and it is measurable rather than theoretical: doom's
M13-hotdata pass moved the hot pointer-walked arrays to low addresses *because wflip cost scales
with an address's set bits*, worth a **measured** 78.54M -> 76.39M ops/frame
(`wall_renderer.py:1756-1770`). Pushing everything above 2^17 perturbs exactly that. **Measure it;
do not assume it is small, and do not assume it is fatal either.**

### 2.2 Amortising the setup — a second prize, no table needed. FEASIBLE.

The owner did not ask for this and it may be the better first move.

Section 1.4 shows the dance **restores every piece of state it touches**: `:51-53` exactly undo
`:36`, `:39` and `:47`, and `to_jump`/`to_flip_var`/`to_jump_var` are never written at all. The
write side is symmetric (`xor_to_pointer.fj:141`, `:146`).

**So after a fetch, the setup is still valid — and `read_byte n` throws it away and rebuilds it,
paying `24@+160` per byte for state that was already correct.**

The cheap advance is `wflip to_flip, delta`, costing `popcount(delta)` ops (1-2). ⚠ But it is an
XOR, not an add: `base + i*dw == base XOR i*dw` only when the base is `2^ceil(log2 n) * dw`-aligned.
So this is exact for **straight-line, compile-time-offset, power-of-two-aligned runs** — which is
precisely `read_table_packed nb`, `read_table n` and `read_byte n`.

Needs no new table, no new data format, and no address relayout. It is the cheaper hypothesis to
test, and it tests the same load-bearing assumption (that the setup is reusable).

---

## 3. THE OPT-IN — `-D ptr12` / `-D ptr16`

The owner's suggestion, and the mechanism already exists: **`fj -D NAME=VALUE` is commit `6cd2b4f`
on `origin/1.5.1`.**

⚠ **The LOCAL `1.5.1` branch is 8 commits STALE and does not have it.** `git fetch` and work from
`origin/1.5.1`, or the flag will appear to be missing — this cost me a wrong conclusion while
writing this document.

Design sketch, to be settled with the maintainer:

    default (no -D)   pad 256   + 256-entry table     exactly today's behaviour, byte-identical
    -D ptr12          pad 4096  + 4,096-entry table   12-bit slots
    -D ptr16          pad 65536 + 65,536-entry table  16-bit slots; INCLUDES the 12-bit case,
                                                      since one table serves every width

`ptr_init` reads the define and picks `k`, the table size and the two `dbit+k` constants. **It stays
exactly where it is** — inside `startup_and_init_all`, as section 2.1 records — so the change is to
one macro's body and nothing relocates. The default path must be **provably unchanged**: that is
the first gate, and it is cheap — assemble any existing program with and without the flag and diff
the `.fjm`.

⚠ **A define that silently changes a data format is dangerous.** Slots written as 8-bit and read as
16-bit are not compatible. Whatever emits pointed-to data must agree with `k`, so the define has to
reach the *emitter* too, not just the stl. Decide early whether `-D ptr16` widens ALL slots or only
those the caller opts into.

---

## 4. WHAT IT IS WORTH — banded honestly

    removable dereferences   ~1,500 (2-byte primitive)   ~2,400 (4-byte)
    each worth               set_flip_and_jump_pointers + the ptr_inc it carries = 33@ + 174
    =>                       1.1M-1.6M ops/frame (2-byte) or 1.9M-2.6M (4-byte)
                             against a ~29.4M spawn frame  =  3.6% - 8.7%

**Cross-checked against a MEASURED datum:** `set_flip_and_jump_pointers` is 7,078,474 ops =
**12.7% of the frame** (`docs/handoff-m14_5.md:69`), 11.4% in a later profile. Removable/total is
1,510/6,700 = 22.5% (2-byte) or 36% (4-byte). The two routes agree within 15%.

⚠ **Do not quote the top of the band.** This repo has measured one stl-docstring prediction and
found it **45%** of its documented cost (`read_table_packed 4` documented ~289@, measured ~125@ —
`docs/handoff-m13-2s-fast.md:294-296`). Honest band:

    0.5M - 2.5M ops/frame, most likely ~1.0-1.5M  =  2% - 8.5%, middle 3.5% - 5%

⚠ **"Pointers are 50% of the time" overstates the REACHABLE part.** Of ~6,700 dereferences/frame,
**~78% are single-byte RANDOM-index reads** (`drawn[x]`, `pclm[x]`, `sfflag[x]`, `sprflag[x]`) that
neither prize helps — the largest single population is pass-1's occlusion prescan at ~840
`read_byte`s/frame. The win lives only in multi-byte **runs**. Also: of 225 pointer call sites in
`src/fj/*.fj`, only ~150 are live in the shipped `game` tier.

---

## 5. NAMING — `read_word` is not available

* `read_hex n, dst, ptr` and `read_byte n, dst, ptr` are **both taken**, and a FlipJump MacroName is
  `(name, param_count)` — a 3-parameter `read_hex` collides.
* **`word` means w bits in this codebase.** `hex.read_word` would name a 16-bit read "word" in a
  repo where a word is 32.

Two candidates with stl precedent, neither unambiguously native:
  (a) a count-led plural after `fill_bytes`/`copy_bytes` — e.g. `hex.read_nibbles n, dst, ptr`;
  (b) a shape-infix name after `read_nth_hex`, naming the mechanism rather than the width.

**Put both in the PR and let the maintainer choose.** CONTRIBUTING says *"Don't change the stl-api,
only offer new options"*, so the name is the one irreversible decision here.

---

## 6. HOW stl CODE IS WRITTEN AND TESTED

**stl macros have NO Python unit test** — they are proven by a small `.fj` program whose stdout is
diffed against a recorded fixture. Commit **`953ddd9`** (`ptr_index` + `read_nth_hex/byte` +
`write_nth_hex/byte`) is the exact template:

    1. the stl edit
    2. programs/hexlib_tests/<group>/<name>.fj
    3. two rows: tests/tests_tables/test_compile_hexlib.csv and test_run_hexlib.csv
    4. one recorded .out fixture

The doc block is rigid, immediately above the `def`, in this order and with no blank lines:

    //  Time Complexity: <expr in @ and w>      (two spaces, so Time/Space right-align)
    // Space Complexity: <expr>
    // @note: ...                               (only if the numbers assume a particular w)
    //   like:  dst[:4] = *ptr                  (three spaces)
    // <one prose line naming every parameter's TYPE and what is preserved>
    // @Assumes: <non-obvious precondition>
    // @requires hex.init and stl.ptr_init (or stl.startup_and_init_all).

Plus: live in `ns hex`, internals in a nested `ns pointers`; `.`/`..` for same/parent ns; **every
global the body touches must be listed after `<`** or the label collector misses it; a body of 4-5
lines calling descriptive macros; new shared cells or tables exported from `ptr_init`'s `>` list and
documented with `// @output-param`.

**Two doc steps `953ddd9` MISSED — do not inherit the miss:** add the macro to the
`flipjump/stl/hex/README.md` pointers table, and if it introduces a new invariant ("a pointed unit
is k bits in one dw cell") add a bullet to that README's Conventions section.

⚠ **The write side is already half-done and is the cheaper half.** `xor_byte_to_flip_ptr` is
`rep(2, i) .xor_hex_to_flip_ptr hex+i*dw, 4*i` (`xor_to_pointer.fj:106-108`) — two nibbles after
**one** `set_flip_pointer`. A wide WRITE is a rep-count change; only the wide READ needs a bigger
table.

---

## 7. THE PLAN — four gated phases

### P1. Prove the amortised setup on ONE call site. No stl change, no table.

Cheapest test of the load-bearing assumption. Target `hex.read_table_packed 4`
(`projection.fj:593`, `:852`, `plane_render.fj:146`) — nb=4 is a power of two, so the XOR-advance is
exact.

  * add `pad 4` to those tables in the emitter so the base is `4*dw`-aligned;
  * restore constant is **`nb*dw`, NOT `(nb-1)*dw`**;
  * **PREDICT FIRST:** 3 saved setups per call, ~3 x 781 = ~2.3k ops per executed call. If the
    measured delta is not within a few percent of `call_count x 2.3k`, the model is wrong — stop and
    find out why instead of banking it;
  * gate: `deg_gate` byte-exact x4 with op counts matching the prediction, then `ca2_sweep` on a
    matched pair for the governing median;
  * **R9 negative control, free here:** set the restore constant back to `(nb-1)*dw` and require the
    gate to REJECT. If it does not, the gate is not covering the invariant and no result counts.

### P2. Resolve a contradiction before spending on the bigger target.

`hex.read_table 8` (`plane_render.fj:140/144/258`) is n full setups per row and needs **no table
relayout** (stride `8*dw`, already pow2) — plausibly the larger prize. ⚠ **But the census called
`plane_render.fj` and `plane_bands.fj` DEAD in the `game` tier and then cited `plane_bands.fj:144`
as hot (~10k of ~12.6k ops/row). Both cannot be true.** Grep the generated parts and settle it
before spending anything.

### P3. The stl primitive, on `origin/1.5.1` (fetch first — local 1.5.1 is stale).

Build the **16-bit** form only; one 2^16 table serves every width, and 12-bit buys nothing extra.
Follow `953ddd9`'s template in full, take the naming decision first, and gate the default path as
byte-identical with and without `-D`.

### P4. Convert doom's multi-byte runs, one at a time, each gated.

First candidate: `lines_steps_load2` (`frame_render.fj:1440-1480`) reads four 4-byte piece records in
sequence, and the slot bytes are always initialised (`sfslot:` is `;0 * dw` padded,
`wall_renderer.py:2031-2032`), so reading all 16 speculatively in aligned pair-reads should be
value-identical. **If that holds it goes from ~108 to ~648 removable dereferences — the largest
single item — and needs no relayout.**

---

## 8. WHAT NOT TO DO

* **Do not generalise before one call site is gated.** The coarse-cull pre-pass was built before
  being priced and cost +24.7M (R23/R32).
* **Do not quote the derived @ figures as results.** The one measured conversion came in at 45% of
  the stl prediction.
* **Do not touch an existing stl signature.** Add names, never change them.
* **Do not trust `deg_gate` alone.** This session twice saw four viewpoints pass a build that the
  260-frame `ca2_sweep` then failed. For anything touching pointers, the sweep is the picture proof.
* **Do not believe "12-bit is the harder width".** That was an agent's conclusion and the hand trace
  refuted it — only two ops precede the table.

---

## 9. PROVENANCE, and what the hand trace changed

Six agents: four research angles, two adversarial refuters aimed at the feasibility verdicts. Both
refutations returned `refuted=False` after line-by-line traces. Full output:
`scratchpad/_fjptr_findings.txt` — read it for the sixth objection the refuter did not fully close
and for every open question.

**The owner then required a hand re-derivation before this document was written, and it changed two
things:** the 2^12 placement claim was inverted (only two ops precede the table, not ~7,000), and
`-D` was found to be on `origin/1.5.1` after the stale local branch made it look absent. Both errors
would have gone straight into the plan.
