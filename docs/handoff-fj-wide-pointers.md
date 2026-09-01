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

### 3a. FIRST, `-D` MUST OVERRIDE — today it is a hard error, and that blocks this design

**Owner's requirement (2026-09-01): a `-D` define must SUPERSEDE an in-source declaration of the
same constant.** If the code says `PTRSIZE = 8` on line 873 and the build passes `-D PTRSIZE=12`,
the compiler must behave **as if line 873 were never written** — not error, not warn.

**That is not what it does today.** `fj_parser.py:714-718`:

    @_('ID "=" expr')
    def statement(self, p):
        name = self.ns_full_name(p.ID)
        if name in self.consts:
            syntax_error(p.lineno, f'Can't redeclare the variable "{name}".')

and `-D`'s own help text documents this as intended: *"redefining an stl constant is an assembly
error, not a silent override"*. Measured on the real `fj` this session, with a control:

    A  source declares PTRSIZE = 8, no -D                assembles
    B  source declares PTRSIZE = 8, -D "PTRSIZE = 12"    Syntax Error in file _dtest.fj (line 1):
                                                           Can't redeclare the variable "PTRSIZE".
    C  source declares nothing,     -D "PTRSIZE = 12"    assembles   <- so -D works; B is the collision

B is the whole problem: the error is raised **at the user's line**, and the only way to use `-D`
today is to DELETE the in-source default first. A constant nobody can ship a default for is not an
opt-in. **So this is a prerequisite of P3, not a footnote.**

**The minimal change.** `_defines.fj` is inserted first among the user files, so a `-D` name is
already in `self.consts` when the source line is parsed. Record which names came from that file,
and make a later assignment to one of them a silent no-op instead of an error:

    if name in self.consts:
        if name in self.cmdline_defined:   # -D wins; the source line is as if unwritten
            return
        syntax_error(...)

⚠ **The skip must not swallow the defines file's own line** — that line is what puts the name in
`cmdline_defined` in the first place, and a naive "name in set -> return" makes every `-D` silently
do nothing. Gate on the assignment's own `CodePosition` file, or seed the consts before parsing.

⚠ **The source expression stops being evaluated at all.** `PTRSIZE = <something unresolvable>` on
line 873 would no longer raise. That is the intended semantics ("as if not written"), but it is a
real behaviour change and belongs in the commit message.

⚠ **And the help text must change**, because it currently promises the opposite. Leaving it turns
the documentation into a false statement about the tool's contract.

### 3b. A NAMESPACED CONSTANT IS ADDRESSED AS `a.b.name`, AND ONLY THAT WAY

**Owner's requirement (2026-09-01).** `-D hex.PTRSIZE = 16` overrides the constant declared inside
`ns hex`. A bare `-D PTRSIZE = 16` must **not** reach it — the fully-qualified spelling is the only
one that works.

**Today the qualified spelling does not parse at all.** Measured:

    -D "hex.PTRSIZE = 12"     FlipJumpParsingException in _defines.fj

because the assignment rule is `ID "=" expr` and a dotted name lexes as `DOT_ID`, a different token.
(The error also points at a temp file the user never wrote — the same complaint `6cd2b4f` raised
about a bare `-D NAME`.)

**The fix is small and already has a template in the file.** The `id` nonterminal
(`fj_parser.py:676-682`) accepts both spellings and routes `DOT_ID` through
`base_name_to_ns_full_name`, which resolves leading dots and returns an already-qualified name
unchanged. Add the mirror rule for assignment:

    @_('DOT_ID "=" expr')     ->  name = self.base_name_to_ns_full_name(p.DOT_ID, p.lineno)

⚠ Add it as its **own rule**; do not widen `ID "=" expr` to `id "=" expr`, which risks an LALR
conflict with the macro-call rules that already consume `id`.

⚠ Note the two helpers differ, and the difference is the correct behaviour here:
`ns_full_name` prefixes the *current* namespace; `base_name_to_ns_full_name` does not. So a
qualified name means the same thing wherever it is written, which is what makes it usable from a
defines file that is always at top level.

### 3c. `-D` MAY ONLY OVERRIDE — NEVER DEFINE

**Owner's requirement (2026-09-01): if the program does not declare the constant itself, `-D` is a
parse error — "override of non-defined constant".** `-D` stops being a way to inject a name and
becomes strictly a way to supersede one.

**This is what makes 3b safe.** Probe E was the dangerous case: `ns hex { PTRSIZE = 8 }` plus a
top-level `-D "PTRSIZE = 12"` produced **no error and byte-identical output** — the define silently
did nothing, because `hex.PTRSIZE` and `PTRSIZE` never collide. Under this rule that same command
now fails loudly with *override of non-defined constant: PTRSIZE*, and the correct spelling from 3b
is the one that works. **The two requirements together turn the one silent failure mode in this
design into a loud one.**

**⚠ The check CANNOT run when the define is parsed.** The declaration it is looking for may be on
line 873 of the last file. It is an **end-of-parse** check, after `_parse_files_into_parser`
returns and before `parse_macro_tree` hands back the macro tree.

**⚠ And "was a later assignment skipped?" is the WRONG predicate** — it misses the case where the
declaration came *first*. An stl constant is declared before `_defines.fj` (which is inserted first
among the USER files, i.e. after the stl), so nothing later is ever skipped and a legitimate
override would be rejected. **The cache-safe predicate:** a define is backed by a real declaration
iff the name was **already in `self.consts` when the defines line was parsed**, *or* a later
assignment to it was skipped. Record the first at define time.

⚠ **Why "cache-safe" matters:** `_parse_files_into_parser` can *skip re-parsing the stl* and restore
a snapshot, and that snapshot carries **`consts` and nothing else** (`fj_parser.py:955-957`,
`:970-972`). Any new tracking set added to the parser is **not** restored on a cache hit, so a
predicate that depends on having *observed* the stl's assignments breaks intermittently — passing on
a cold cache and failing on a warm one. Testing `name in self.consts` depends only on what the
snapshot does carry. (`_defines.fj` lives in a temp dir, so it breaks the stl prefix and is never
itself cached — but do not move it before the stl without adding the defines to the cache key.)

**⚠ FAN-OUT: this breaks all four shipped `-D` tests.** `tests/unit/test_cli.py`'s `DEFINE_PROG`
*uses* `GREET` and never declares it, so every one of them becomes an *override of non-defined
constant* error. They need a `GREET = 0` line added. Nothing in doom passes `-D` today, so the
blast radius is exactly those four.

### 3d. The table selection itself

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

**P3.0 comes first, is separable, and is three requirements in one commit — `-D` becomes an
OVERRIDE-ONLY mechanism.** Sections 3a/3b/3c. Today `-D X=…` against a source that declares `X` is a
hard `Can't redeclare the variable` error at the USER's line, so the opt-in cannot ship a default at
all. Touches `fj_parser.py:714-718`, one new grammar rule, and one end-of-parse check. Tests:

  * **override** — source `X = 8` + `-D "X = 12"` assembles to the **same bytes** as source
    `X = 12` with no `-D`;
  * **negative control** — the same source with no `-D` must produce **different** bytes, or the
    first assertion is equally true of a define that did nothing (that is literally probe E);
  * **qualified name** — `ns hex { PTRSIZE = 8 }` + `-D "hex.PTRSIZE = 12"` moves the bytes;
  * **bare name is refused** — the same program + `-D "PTRSIZE = 12"` is now an *override of
    non-defined constant* error, NOT a silent no-op;
  * **undeclared is refused** — `-D "NEVER_DECLARED = 1"` errors;
  * **declaration-first still works** — overriding a constant the stl declared *before* the defines
    file must succeed, and must keep succeeding on a **warm stl-prefix cache** (3c: the snapshot
    carries `consts` only);
  * the defines file's own line still takes effect — the naive fix silently disables every `-D`;
  * **fix the four shipped `-D` tests** (3c): `DEFINE_PROG` never declares `GREET`;
  * update the `-D` help text, which currently promises the opposite of all of this.

Then the primitive itself: build the **16-bit** form only; one 2^16 table serves every width, and
12-bit buys nothing extra. Follow `953ddd9`'s template in full, take the naming decision first,
declare the width constant **top level** (section 3b: a name inside `ns hex` is silently
unreachable from `-D`), and gate the default path as byte-identical with and without `-D`.

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

---

## 10. GAPS IN THIS PLAN — found by auditing it against the stl source

Written after the plan, by reading `basic_pointers.fj`, `read_pointers.fj`, `xor_from_pointer.fj`
and doom's `fixed_point.fj`. **Two of these are errors in sections 2 and 7, not omissions.** Ordered
by what would hurt most.

### G1 (CORRECTION). Section 2.2's advance recipe is INCOMPLETE — it would read the wrong address

`set_flip_and_jump_pointers` (`basic_pointers.fj:75-79`) sets **two** things from the pointer:

    address_and_variable_xor        w/4, to_flip,   to_flip_var, to_flip_var
    address_and_variable_xor        w/4, to_jump+w, to_jump_var, to_jump_var
    address_and_variable_double_xor w/4, to_flip, to_flip_var, to_jump+w, to_jump_var, ptr

Section 2.2 says the advance is `wflip to_flip, delta`. **`to_jump+w` must advance too**, or the
code arms slot *k+1* and jumps to slot *k*. Cost is still trivial (two wflips, `popcount(delta)`
each) — but as written the recipe is a bug, not an optimisation.

### G2 (CORRECTION). The restore is mandatory for a reason the plan does not state: SHADOW COHERENCE

`to_flip_var` / `to_jump_var` are shadow copies that `address_and_variable_xor` uses to **xor out the
previous value**. Advancing `to_flip`/`to_jump` with a raw `wflip` leaves the shadows stale, so **the
next genuine `set_flip_and_jump_pointers` xors out a value that is no longer there and produces a
corrupt address** — at some later, unrelated call site.

P1 already says "restore constant is `nb*dw`, not `(nb-1)*dw`", but frames it as returning the
pointer. The real invariant is: **`to_flip`/`to_jump` must be back to what the shadows believe before
any other dereference happens.** State it that way, or the R9 negative control tests the wrong thing.

### G3. The amortised span must contain NO other dereference — an unstated PRECONDITION

`to_flip`, `to_jump`, `to_flip_var`, `to_jump_var` and `read_byte` are **global singletons**
(`ptr_init` declares them once). Any dereference between the first setup and the last read clobbers
all of it. `read_table_packed` is straight-line and safe (`fixed_point.fj:186-197`), but **P4's
`lines_steps_load2` is not obviously so**, and the plan never says this must be checked per site.
It is a correctness precondition, not a performance note.

### G4 (THE BIG ONE). At P1's own call sites, a LARGER win sits next to the one I planned

`read_table_packed nb` (`fixed_point.fj:186-197`) is not just `nb` dereferences. Its own complexity
comment prices the address arithmetic at `#(n*dw)(w/4(1.5@+10))`. Decomposed at **w=32, @=25**
(the model reproduces the stl's published `read_hex`=948 and `read_byte`=998 exactly, which is what
says the decomposition is right):

    4x read_byte_and_inc      4,948   55%
    mul_const + add           3,420   38%   <- NO PHASE IN THIS PLAN TOUCHES IT
    fixed tail                  610
    TOTAL                     8,978

`mul_const n, dst, src, c` is doom's own macro and loops `#c` times shifting by one bit. For
`c = nb*dw = 256` that is **nine `shl_bit` passes to multiply by 2^8** — when `256` is two whole hex
digits, i.e. a lane relabel: `mov` 6 hexes + `zero` 2 = 14@ = **~350 ops**.

    P1 amortise the setup      saves ~3,224   (36% of the call)
    + 16-bit reads             saves ~3,508   cumulative
    + shift instead of mul     saves ~3,070   <- LARGEST SINGLE ITEM, and the simplest
    all three:  8,978 -> ~2,400  (-73%)

**The plan optimises the 55% and ignores a 38% that is cheaper to fix.** These are DERIVED from the
macros' own complexity comments, not measured — but they are derived from the same comments the plan
already trusts, and they reorder the work.

The `.add w/4, ptr, table_address` is the same story: adding a compile-time constant base to an
offset is an XOR when the table is aligned to its own size, and an XOR of a constant is a `wflip`.

### G5. `-D ptr16` TAXES every narrow read, and the plan presents it as free

Step 1 of the dance is `hex.zero 2, hex.pointers.read_byte` — **inside** the read. A 16-bit table
needs `read_byte: hex.vec 4` and a four-branch entry expression, so that zero becomes `hex.zero 4`
and **every existing byte read pays +2@ (~50 ops on ~998, +5%)** for a width it does not use.

Avoidable — but only if the width is a **per-call-site parameter**, not a global define. That is a
real design fork the plan never surfaces: `-D ptr16` sizes the *table*, and the *macro* must still
choose how many hexes to clear.

### G6. A speculative read of an uninitialised slot does not read garbage — it EXECUTES garbage

P4 proposes reading all 16 slot bytes speculatively and argues the slots are always initialised. But
section 1's whole point is that **a pointed-to value IS a jump address**. Arming a slot that holds
junk `G` makes the program jump to `(G+256)*dw` — outside the table, into arbitrary code. The failure
is not a wrong pixel, it is an unbounded jump.

So "the slots are always initialised" is a **hard safety precondition**, not a value-correctness
nicety, and it must be proven for the whole speculative range — not sampled.

### G7. Nothing in the plan carries the new state into the M1 restore set

Standing repo rule: a feature is not complete until the M1 self-reset loop carries its labels.
A wider `read_byte`, any new shadow, and any new scratch are **global singletons in `ptr_init`** and
therefore exactly the kind of thing the restore set exists for. No phase mentions it. Add it to P3
and P4's definition of done, and check `build.STANDALONE_PERSIST` / the `m5_` set.

### G8. The write side is not in the plan at all

`xor_to_pointer.fj` is symmetric and section 6 even notes the write side already does two nibbles per
setup. Doom has 36 pointer-macro call sites; the plan's four phases are all reads. Either the same
two prizes apply to writes (and the plan is under-scoped by half), or they do not and the plan should
say why.

### G9. Ordering: P1's target was chosen using the census P2 exists to fix

Section 4's value estimate and P1's choice of `read_table_packed 4` both rest on a census that
**P2 itself says contradicts itself** (`plane_render`/`plane_bands` called dead and hot). Running P1
first is defensible — it is a mechanism test and its own op counts are self-validating — but the
plan should say plainly that *the target selection is not yet evidence-backed*, and re-run the census
before P4 picks sites.

### G10. Smaller, but each would cost a session

* **No abort threshold.** The plan predicts, but never says what result kills it. Given the repo's
  history (a pre-pass built before it was priced, +24.7M), P1 needs a number below which P3/P4 do not
  start.
* **No compile-time guard on `k`.** Section 2.1 has the `dbit+k < dw` ceiling but no phase asserts it.
  The stl is general-purpose: at small `w` a 16-bit table is impossible, and it must fail loudly at
  assembly time rather than silently corrupt.
* **`bit.pointers.ptr_init` exists too** (`ptrlib.fj:7-9` calls both). A second table, never mentioned.
* **`@` is `log2(total ops)`, so it is program-size dependent.** Adding 65,536 table ops to a ~42M-op
  image moves `@` by ~0.002 — negligible, and worth one line to close rather than leave as a doubt.
* **No named measurement command** for P1's before/after, in a repo whose rules forbid quoting an
  unmeasured number.
* **The plan only makes dereferences cheaper, never fewer.** G4 is one instance of the wider miss:
  no phase asks which pointed-to reads could become fixed-address reads through the specialisation
  doom already does elsewhere (BSP-as-code). For a repo whose cost model says *stops beat budgets*,
  that is the missing question.

### What I would change in the plan

1. **Fix G1 and G2 in section 2.2 and P1 before anyone implements from this document.**
2. **Add the `mul_const`-to-shift change as P0** — largest single item, simplest, no stl change, no
   table, and it is gated by the same `deg_gate`+sweep run as P1.
3. **Make G3's "no dereference inside the amortised span" an explicit per-site checklist item.**
4. Fold G7 (restore set) into the definition of done for P3 and P4.
5. Decide G5's fork — global table width vs per-call-site clear width — before writing the macro.

---

## 11. SHARING `set_flip_and_jump_pointers` — the deep dive

The owner's question: the setup is the slow part; **where else can it be shared?** Answered by taking
it apart. Everything below is **DERIVED** from the stl's own published complexity comments at
**w=32, @=25** (`@` is `log2(total ops)`, README line 75), and the decomposition reproduces
`read_hex`=948 and `read_byte`=998 exactly. **Nothing here is measured. No build was run.**

### 11.1 What the setup actually is: three passes over the pointer's hexes

    address_and_variable_xor        w/4, to_flip,   to_flip_var, to_flip_var   (w/4)(@+4) = 232
    address_and_variable_xor        w/4, to_jump+w, to_jump_var, to_jump_var   (w/4)(@+4) = 232
    address_and_variable_double_xor w/4, to_flip, to_flip_var,
                                         to_jump+w, to_jump_var, ptr           (w/4)(@+12) = 296
                                                                               ------------------
                                                                               w(0.75@+5) = 760

`logics.fj:88-93,149-156`: each pass is `rep(n, i) <exact_xor over one hex>`, priced `@+4` for two
destinations and `@+12` for four — **+4 per extra destination**. So the setup is **exactly linear in
the number of pointer hexes: 95 ops per hex.** That single fact drives everything below.

**Passes 1 and 2 are pure bookkeeping** — they exist only to xor out the *previous* pointer. They are
**464 of 760, i.e. 61% of the setup**, and they do no work related to the read at hand.

### 11.2 S1 — merge the two shadows. −232 ops on EVERY dereference, no call-site changes.

`to_flip_var` and `to_jump_var` are two `hex.vec w/4` registers, and inside
`set_flip_and_jump_pointers` they are **always assigned the same value and always zeroed together**.
With one shared shadow and a three-destination `exact_xor` (`@+8`, by the +4-per-destination rule):

    clear to_flip, to_jump+w, shadow    (w/4)(@+8) = 264
    set   to_flip, to_jump+w, shadow    (w/4)(@+8) = 264
                                        ---------------
                                                     528     vs 760  ->  -30.5%

Setup is 80% of a `read_hex`, so this is **≈ −24% on every pointer read and write in any FlipJump
program**, with no change at any call site.

⚠ **The catch, and it is checkable:** the shadows are *not* always equal, because
`xor_to_pointer.fj:10,37,46,155` and `basic_pointers.fj:114` use the one-sided `set_flip_pointer` /
`set_jump_pointer`. Under a merged shadow those must maintain both fields, costing them
`528` vs `464` (**+14%**). **In doom that is a near-pure win:** the census below shows doom's traffic
is 57 sites through `set_flip_and_jump_pointers` and none through the one-sided pair.

### 11.3 REFUTED — fusing `to_flip` and `to_jump` into one op

Tempting: one op `(ptr+dbit+8) ; ptr` both arms the slot and jumps into it, which would delete pass 2
(232 ops). **It does not work.** The dance uses the flip op **twice** — once to arm (jumping onward
to the slot) and once to disarm (jumping onward to `cleanup`). The current design keeps every jump
field a **compile-time code label**, so retargeting between the two uses is a constant `wflip`.
Putting the runtime address `ptr` in a jump field makes that retarget a runtime xor, and you still
need two address-bearing ops. Recorded so nobody re-derives it.

### 11.4 The census says the setup is NOT doom's biggest pointer cost

Call sites in `src/fj/*.fj`:

    read_byte   38     ptr_index   35     write_byte  13     ptr_sub  6     read_hex  5     write_hex 1

**`ptr_index` is as common as `read_byte`.** And an indexed read is priced `w(3@+10.25) + 7@+13`,
against `read_hex`'s `w(0.75@+5) + 7@+13` — so `ptr_index` alone is `w(2.25@+5.25)` ≈ **1,968 ops,
2.6x the setup.** For doom's most common pointer pattern the split is roughly

    address arithmetic  ~1,968   (~60%)
    setup                  760   (~23%)
    the actual read        238   ( ~7%)

**Sharing the setup is optimising the 23%.** That is worth doing — but it is not where the money is.

### 11.5 S2 — the base is a COMPILE-TIME CONSTANT, and doom pays runtime for it

`frame_render.fj:629-632`, four consecutive lines:

    hex.set     w/4, trb_drawn_b,   drawn                  // materialise a LABEL into 8 hexes
    hex.ptr_index     trb_drawn_p,  trb_drawn_b, trb_col_x // then a runtime 8-hex ADD of it
    hex.set     w/4, trb_sprflag_b, sprflag                // again
    hex.ptr_index     trb_sprflag_p, trb_sprflag_b, trb_col_x

`ptr_index` (`pointer_arithmetics.fj:46-52`) is `mov w/4` + two `shl_hex` + `rep(8-#w) shr_bit` +
**`add w/4, dst, ptr`**. When `ptr` is a constant and the array is aligned to its own size,
`base + offset == base XOR offset`, so **the whole runtime add — and the `hex.set` that existed only
to feed it — collapse to a compile-time constant.** The shifts then only need to cover the hexes a
bounded index can reach, not all eight.

`read_table_packed` has the identical shape: `table_address: .vec w/4, table` is a compile-time
label stored in a register purely so a runtime `add` can consume it (§10 G4).

### 11.6 S3 — one index, several arrays: share the arithmetic, not the setup

Lines 630 and 632 index **two different arrays with the same `trb_col_x`**. Same at `:967/:969`
(`tsf_drawn_p`, `tsf_sfflag_p` from `tsf_col_x`). Since both bases are compile-time constants,

    second_ptr = first_ptr + (base2 - base1)      // a COMPILE-TIME constant

so the second `ptr_index` **and** its `hex.set` are entirely redundant — one shift feeds every array
indexed by that column. This is the owner's "share it more often" applied one level up from the
dereference, and it is visible in four lines of one macro.

### 11.7 The sharing taxonomy, with what each is worth

    S1  merged shadow                    -232 per dereference    ALL 57 doom sites, no call-site edit
    S2  constant base -> xor, not add    ~-1,968 (+ the set)     the 35 ptr_index sites
    S3  one index, N arrays              a whole ptr_index each  pairs at :630/:632, :967/:969
    S4  adjacent cells, one setup        -760 and -239 (ptr_inc) read_byte n, read_table_packed  (P1)
    S5  16-bit read instead of 2 bytes   ~-898 per byte pair     wherever 2 adjacent bytes are read

**S4 is the only one the plan had.** S1 is the one that needs no call-site change at all, and S2/S3
are larger than everything else combined.

### 11.8 Writes: already shared, and they pay the full setup

`write_hex` (`write_pointers.fj:9-14`) is `set_flip_and_jump_pointers` -> `read_byte_from_inners_ptrs`
-> `xor` -> `xor_hex_to_flip_ptr`. **A write IS a read plus a flip-back, through ONE setup** — already
optimal, no win there. But two consequences the plan missed: a write costs a full 760-op setup like a
read, so S1/S2/S4 apply to doom's 13 `write_byte` sites too; and **a read of `*p` and a later write to
`*p` at two separate call sites do NOT share** — the write redoes the setup. Fusing those is another
760.

### 11.9 CORRECTION — `to_flip` and `to_jump` are NOT the same pointer. The owner is right.

My §11.2 headline was too strong. Enumerating **every** write to the two address fields:

**`to_jump+w` is written by exactly two macros** — `set_jump_pointer` and
`set_flip_and_jump_pointers` — and is **never** offset.

**`to_flip` is written by those setups AND transiently offset by a compile-time constant in three
separate macros**, each of which restores it:

    xor_from_pointer.fj:36 / :52    wflip to_flip, dbit+8        arm / disarm  <- the owner's example
    xor_to_pointer.fj:26 / :28      wflip to_flip, dbit          ptr_flip_dbit
    xor_to_pointer.fj:123-141       dbit+0 -> +1 -> +3 -> +2 -> 0   a GRAY-CODE WALK in
                                                                    xor_hex_to_flip_ptr

So **inside the dance, `to_flip` = ptr+dbit+8 while `to_jump+w` = ptr** — exactly as the owner said —
and `xor_hex_to_flip_ptr` walks `to_flip` through four offsets on a data-dependent path. The design
does this deliberately: offsetting `to_flip` by a compile-time constant is a `wflip` costing
`popcount`, which is why the *flip* field is the one that gets perturbed and the *jump* field never is.

**And they differ DURABLY too, not just transiently** — the stronger case. `xor_hex_to_ptr`,
`xor_byte_to_ptr` and `ptr_flip` (`xor_to_pointer.fj:10,37,46,155`) call **`set_flip_pointer`**, which
advances `to_flip`+`to_flip_var` and leaves `to_jump`/`to_jump_var` pointing at an **older, unrelated
address**; `ptr_jump` (`basic_pointers.fj:114`) does the mirror image. `xor_hex_to_flip_ptr` even
documents it: *"use after: .pointers.set_flip_pointer ptr"*.

**What this does to S1.** It does not refute it, but it renames the precondition, and the difference
is the whole point:

    today   each address field equals ITS OWN shadow at setup entry   -- two independent invariants,
            and the one-sided setters keep each field self-consistent
    S1      both address fields equal THE SAME shadow                 -- strictly stronger

The three transient offsets are all restored before their macro exits, so they do not violate the
stronger invariant *at a setup call* — **but S1 converts "three macros each happen to restore
`to_flip`" from an incidental property into a load-bearing one, spread across two files, asserted
nowhere.** The one-sided setters violate it outright, which is the +14% already priced in §11.2.

**Therefore, if S1 is attempted:**

* state the invariant explicitly — `to_flip == to_jump+w` at every entry to the setup — and give it a
  test that a mutation must break (R9);
* the one-sided setters must maintain **both** fields, or be deleted;
* ⚠ **and it forbids the obvious S4 micro-optimisation**: skipping the `dbit+8` restore between
  consecutive amortised reads would leave `to_flip` permanently offset. (That already breaks today's
  weaker invariant too — worth knowing before someone "saves" two wflips per read.)

**§11.2 should be read as:** the two shadows are equal *on the path doom actually uses* — 57 sites
through `set_flip_and_jump_pointers`, none through the one-sided pair — not as a property of the stl.
That is what makes S1 attractive **for doom** and a much bigger question for the stl in general.

### 11.10 The owner's structural point — one shadow, because the two fields are different PARTS

*"They can be the same variable, as one is in the flip part and one is in the jump part."*

This is the right way to see it, and it **removes** my §11.9 objection instead of working around it.

`to_flip: 0;0` holds its address in the **flip part** — word 0, at `to_flip+0`.
`to_jump:  ;0` holds its address in the **jump part** — word 1, at `to_jump+w`.

They are two distinct *destinations*, but they always hold **one value: the address being pointed at**.
Being in different parts is exactly why a single shadow can serve both — there is no aliasing to
worry about, only two places to write the same number. The current pair of shadows is not required by
the structure; **the structure is the reason one is enough.**

**The arithmetic checks out against the family that already exists** (`logics.fj`):

    exact_xor            1 destination group    @
    double_exact_xor     2                      @+4
    quadrupled_exact_xor 4                      @+12          ->  @ + 4(k-1)

so a three-destination form is `@+8`. It does not exist yet, but it is an interpolation of a template
already written three times. With one shadow:

    clear   to_flip, to_jump+w, shadow     (w/4)(@+8)
    set     to_flip, to_jump+w, shadow     (w/4)(@+8)
                                           ------------
                                           w(0.5@+4)  = 528     vs  w(0.75@+5) = 760

**In the stl's own notation the setup goes `w(0.75@+5)` -> `w(0.5@+4)`.** At w=32, @=25:

    read_hex    948 -> 716   (-24.5%)
    read_byte   998 -> 766   (-23.2%)

### 11.11 So why are there two shadows? For a capability doom never uses.

Two shadows exist for exactly one reason: `set_flip_pointer` and `set_jump_pointer` let the two fields
hold **two different live pointers at once** — one address armed for flipping, another for jumping.
That is a real capability. Its users:

    stl    set_flip_pointer  at xor_to_pointer.fj:10,37,46,155   (xor_*_to_ptr, ptr_flip)
           set_jump_pointer  at basic_pointers.fj:114            (ptr_jump)
    doom   xor_hex_to_ptr 0   xor_byte_to_ptr 0   ptr_flip 0   ptr_jump 0
           set_flip_pointer 0   set_jump_pointer 0   xor_hex_to_flip_ptr 0

**Zero.** All 57 of doom's pointer sites go through `set_flip_and_jump_pointers`. And even in the stl,
each one-sided setter is used only by its own standalone macro — nothing depends on the *other* field
surviving across it.

So the two-shadow design buys a capability nothing in doom uses, and charges **232 ops for it on every
single dereference**.

**The consequence for §11.9's objection.** With one shadow there is one setter, and "both address
fields equal the same shadow" stops being an emergent property spread across two files — it becomes a
**single macro's postcondition**. The durable-divergence case disappears *by construction*, not by
assertion. What remains is only the transient requirement, unchanged: the three macros that offset
`to_flip` by a compile-time constant (`dbit+8`, `dbit`, and the Gray walk) must restore it, which they
already do.

One-sided callers, if kept, pay `w(0.5@+4)` = 528 instead of `w(0.5@+2)` = 464 — **+64, +13.8%**, on
paths doom does not have.

⚠ **Scope, honestly:** this is ~24% off an isolated read, and isolated reads are where §4 says most
dereferences are. But at doom's 35 `ptr_index` sites the setup is only ~23% of the cost, so there it
is ~7%. **S2 and S3 remain the larger prizes; S1 is the one that costs no call-site changes.**
