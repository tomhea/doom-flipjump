# Handoff — WIDE POINTER READS for the FlipJump stl

**Phase 0 of the current M4 work.** Written 2026-09-01 from a six-agent research pass whose two
feasibility verdicts were sent to adversarial refuters; **both survived (`refuted=False`)**. Nothing
has been implemented. Every claim below cites the source it came from, and the cost figures are
labelled MEASURED or DERIVED — the derived ones come from stl docstrings, which this repo has
already caught over-predicting by 2x once.

---

## 1. The owner's idea, and why it is bigger than it looks

> *"see how the hex.read_hex and hex.read_byte are almost identical in time complexity costs? maybe
> create a hex.read_12bits / hex.read_word that reads both 3 nibbles and 4 nibbles from a pointer,
> for about the same time and space costs? ... pointers might be more than 50% of the times, so this
> have a very big potential."*

The observation is exactly right, and the stl's own numbers say so:

    read_hex  (1 nibble)   w(0.75@+5) + 7@+13
    read_byte (2 nibbles)  w(0.75@+5) + 9@+13     <- +2@ for DOUBLE the data

A read decomposes into three steps, and only the last one scales with width:

    set_flip_and_jump_pointers ptr    w(0.75@+5) = 24@+160 at w=32   <- THE COST, per dereference
    read_byte_from_inners_ptrs        5@+13                          <- the fetch
    xor n, dst, read_byte             n@                             <- extract n nibbles

At w=32 one dereference costs ~33@ while `hex.mov` costs 2@ per nibble: **a pointer read is worth
more than sixteen nibble-moves.** And the n-forms are `rep(n)` of the single form
(`read_pointers.fj:63-66`), so `hex.read_byte 2, dst, ptr` pays the whole dereference TWICE:

    today            2 x (w(0.75@+5) + 18@+27)  =  84@ + 374
    single-deref 4n              w(0.75@+5) + 11@+13  =  39@ + 173      ~2.16x, flat in @

---

## 2. What the research established

Two INDEPENDENT prizes. Only the first is what the owner literally described; the second may be
larger and needs no data-layout change at all.

### A — a wider fetch. FEASIBLE. (refutation: survived)

**The `8` in `wflip hex.pointers.to_flip, dbit+8` is NOT a fetch width.** FlipJump has no fetch
width: the dereference is a *jump to the data opcode*, whose jump-word IS the value. The `8` is
`log2(table base index)`.

* `dbit = w + #w` (`runlib.fj:3`); a data slot is `;V * dw` (`hex/memory.fj:8`), so the stored word
  is `V<<#w`. Flipping bit `dbit+8` adds `2^(#w+8) = 256*dw` — logically `V += 256`, which is
  exactly where `read_ptr_byte_table` sits (`pad 256`, `basic_pointers.fj:19-23`).
* Control therefore lands on table entry V, which walks down flipping V's set bits into the shared
  `read_byte` register. Cost `popcount(V)+1`.
* **The stl proves the point against itself:** `basic_pointers.fj:20-21` says *"4/8 ... (4 is for
  reading from an hex memory, 8 is for byte memory)"* — the SAME constant and table already serve a
  4-bit memory and an 8-bit one. It cannot be a width.

So **k bits per dereference costs a 2^k-entry decoder table based at exactly 2^k*dw**, and nothing
else in the mechanism is width-dependent. The two `wflip to_flip, dbit+k` sites
(`xor_from_pointer.fj:36` and `:52`) merely have to agree.

* **One table serves every width.** Entry d walks strictly downward, so entries 0..255 of a 2^16
  table decode a byte correctly. With 16-bit slots, one primitive covers 1-, 2-, 3- and 4-nibble
  reads at one dereference each.
* **Alignment is unchanged.** `P^(dbit+k) == P+dbit+k` needs `P & (dbit+k) == 0`; dw-alignment
  zeroes P's low `#w` bits and `dbit+k = 38+k < 64` for k <= 25. The hard ceiling is
  `k < w - #w = 26` at w=32 — so **32 bits is impossible**, 16 is comfortable.
* **The decode gets marginally CHEAPER**, not dearer: `popcount(16-bit)` = `popcount(lo)+popcount(hi)`
  and you pay one terminal return instead of two.

### B — amortise the setup across consecutive fetches. FEASIBLE. (refutation: survived)

Independent of A, needs no layout change, and helps every multi-byte access in the codebase.

**Nothing in the fetch destroys the pointer setup.** `set_flip_and_jump_pointers` leaves four pieces
of state, and `read_byte_from_inners_ptrs` restores every one before returning
(`xor_from_pointer.fj:51-53` exactly undo `:36`, `:39`, `:47`; `to_jump` and both shadows are never
written). The write inner is symmetric (`xor_to_pointer.fj:141`, `:146`). So `read_byte n` pays
`24@+160` per byte **to rebuild state that was already correct**.

⚠ The cheap advance is NOT a general `+dw`. `to_flip`/`to_jump` hold raw address words, so
`wflip to_flip, delta` costs `popcount(delta)` ops (~1-2) — but `base + i*dw == base XOR i*dw` only
when the base is `2^ceil(log2 n) * dw`-aligned. That makes the amortised walk exact for
**straight-line, compile-time-offset, power-of-two-aligned runs** — which is precisely what
`read_table_packed nb`, `read_table n` and `read_byte n` are.


---

## 3. What it is worth — banded honestly

The census found **225 pointer call sites** in `src/fj/*.fj`, of which only **~150 are live in the
shipped `game` tier** (`plane_bands.fj` entirely, `plane_render.fj`, and ~32 of `stream_render.fj`'s
40 are rep-gated to zero by `ascode=1`/`stack=1`/`w2s=wpx=0`).

⚠ **Roughly 78% of the ~6,700 dereferences per frame are SINGLE-byte random-index reads**
(`drawn[x]`, `pclm[x]`, `sfflag[x]`, `sprflag[x]`) that neither prize can help — the largest single
population is pass-1's occlusion prescan at ~840 `read_byte`s/frame. **The win is only in
multi-byte RUNS**, and there are fewer of those than "pointers are 50% of the time" suggests.

    removable dereferences    ~1,500 with a 2-byte primitive
                              ~2,400 with a 4-byte one
    each worth                set_flip_and_jump_pointers + the ptr_inc it carries = 33@ + 174

    => 1.1M - 1.6M ops/frame (2-byte)   or   1.9M - 2.6M (4-byte)
       against a ~29.4M shipped spawn frame  =  3.6% - 8.7%

**INDEPENDENT CROSS-CHECK, and it is the reason to believe the order of magnitude.**
`set_flip_and_jump_pointers` is **MEASURED** at 7,078,474 ops = **12.7% of the frame**
(`docs/handoff-m14_5.md:69`), and 11.4% in the later lines profile (`docs/opt-experiments.md:760`).
Removable/total is 1,510/6,700 = 22.5% (2-byte) or 2,390/6,700 = 36% (4-byte). The two routes agree
within 15%.

⚠⚠ **DO NOT QUOTE THE TOP OF THAT BAND.** This repo has already measured one stl-docstring
prediction and found it 2x optimistic: *"`read_table_packed 4` is documented at ~289@; converting it
away measured ~125@"* (`docs/handoff-m13-2s-fast.md:294-296`) — a realisation factor of **45%**.
Combining that with the @-calibration spread gives an honest band of:

    0.5M - 2.5M ops/frame, most likely ~1.0-1.5M  =  2% - 8.5% of the frame, middle 3.5% - 5%

For scale: that middle is comparable to the entire pid widening this session spent (+6.74%), and
would pay it back.

---

## 4. ⚠ The name `read_word` is wrong, and naming is a real blocker

* `read_hex n, dst, ptr` and `read_byte n, dst, ptr` are **both already taken** — and a FlipJump
  MacroName is `(name, param_count)`, so a 3-parameter `read_hex` collides.
* **`word` is reserved for w bits** in this codebase. `hex.read_word` would name a 16-bit read
  "word" in a repo where a word is 32.

The two defensible options, both following existing stl precedent:

  (a) a plural/count name, after `fill_bytes` / `copy_bytes` — e.g. `hex.read_nibbles n, dst, ptr`;
  (b) a shape-infix name after `read_nth_hex` / `read_nth_byte`, naming the MECHANISM not the width.

⚠ Neither reads as unambiguously native. **Put both in the PR and let the maintainer choose** —
CONTRIBUTING says *"Don't change the stl-api, only offer new options"*, so the name is the one
irreversible decision here.

---

## 5. How stl code is written and tested — the checklist

**stl macros have NO Python unit test.** They are proven by a small `.fj` program whose stdout is
diffed against a recorded fixture. **Commit `953ddd9`** (which added `ptr_index` + `read_nth_hex/byte`
+ `write_nth_hex/byte`) is the exact template:

    1. the stl edit
    2. programs/hexlib_tests/<group>/<name>.fj
    3. two rows: tests/tests_tables/test_compile_hexlib.csv and test_run_hexlib.csv
    4. one recorded .out fixture

**The doc block is rigid** and goes immediately above the `def`, in this order with no blank lines:

    //  Time Complexity: <expr in @ and w>        (two spaces, so Time/Space right-align)
    // Space Complexity: <expr>
    // @note: ...                                 (only if the numbers assume a particular w)
    //   like:  dst[:4] = *ptr                    (three spaces)
    // <one prose line naming every parameter's TYPE and what is preserved>
    // @Assumes: <non-obvious precondition>
    // @requires hex.init and stl.ptr_init (or stl.startup_and_init_all).

Plus: live in `ns hex`, internals in a nested `ns pointers`; `.`/`..` for same/parent ns; every
global the body touches listed after `<` or the label collector misses it; a body of 4-5 lines
calling descriptive macros; a new shared cell or table exported from `ptr_init`'s `>` list and
documented with `// @output-param`.

**Two doc steps `953ddd9` MISSED — do not inherit the miss:**
  * add the macro to the `flipjump/stl/hex/README.md` pointers table (row for its file, line 30);
  * if it introduces a new invariant ("a pointed unit is N bits packed in one dw cell"), add a
    bullet to that README's Conventions section.

**The branch.** `1.5.1` is 3 commits ahead of `main` and 0 behind, and `flipjump/stl/` is
**byte-identical across `main`, `1.5.1` and `perf-asm-10min`** — so 1.5.1 is a correct base and
there is no merge risk in the stl tree itself.

---

## 6. ⚠ THE HAZARD THAT COULD SINK OPTION A: it collides with M13-hotdata

A 2^k decoder table must occupy opcodes `[2^k, 2^(k+1))` — it is pinned by the address arithmetic,
not placed freely. That runs straight into an optimisation this repo already measured and banked:

`wall_renderer.py:1756-1770` moved the hot pointer-walked arrays (`pclm`, `sfflag`, `sprflag`, the
packed LUTs, the cm/byte EMIT tables) to just after startup **precisely because wflip cost scales
with the address's set bits — measured 78.54M -> 76.39M ops/frame.**

    a 2^16 table occupies ops [65536, 131072)
      -> put it BEFORE the hot data and the hot data is pushed above 2^17, perturbing that win
      -> put it AFTER and the hot block must END below op 65536   (its size is UNMEASURED)

    a 2^12 table is WORSE, not better: it must sit below op 4096, which is below
    `stl.startup_and_init_all`'s ~7,000 ops -- forcing that macro to be split into
    `startup_and_init_pointers` + `hex.init` + `stl.stack_init`

**So `read_12bits` is the harder of the two widths, not the easier one.** Measure the hot block's
size before committing to any table.

Space cost itself is minor: 2^16 entries = 131,072 words, ~0.26% of a ~50M image, and the `pad`
slots are consumed as real wflip ops by the assembler's `padding_ops_indices` free-list.

---

## 7. THE PLAN — four phases, each gated before the next

### P1. Prove the amortised setup on ONE call site. No stl change yet.

**Start with B, not A** — it needs no table, no relayout, and no new data format, so it tests the
expensive assumption (that the setup is safely reusable) at the lowest cost.

Target `hex.read_table_packed 4` (`projection.fj:593` tantoangle, `:852` viewangletox,
`plane_render.fj:146` xtoviewangle) — nb=4 is a power of two, so the XOR-advance is exact.

  * add `pad 4` to those tables in the emitter so the base is `4*dw`-aligned;
  * write the amortised walk with the restore constant **`nb*dw`, NOT `(nb-1)*dw`**;
  * **PREDICT FIRST**: 3 saved setups per call, ~3 x 781 = ~2.3k ops per executed call. If the
    measured delta is not within a few percent of `call_count x 2.3k`, the model is wrong — stop
    and find out why rather than banking the win.
  * gate: `scratchpad/deg_gate.py` byte-exact x4 AND op counts matching the prediction; then
    `ca2_sweep` on a matched pair for the governing median.
  * **R9 negative control, free here:** set the restore constant back to `(nb-1)*dw` and require the
    gate to REJECT. If it does not, the gate is not covering the invariant and no result counts.

### P2. Price the bigger amortisation target before generalising.

`hex.read_table 8` (`plane_render.fj:140/144/258`) is n full setups per row and needs **no table
relayout at all** (stride `8*dw`, already a power of two). It is plausibly the larger prize.

⚠ **The research contradicted itself here and it must be resolved first:** the census called
`plane_render.fj` and `plane_bands.fj` DEAD in the `game` tier, then cited `plane_bands.fj:144` as a
hot site (~10k of ~12.6k ops/row). **Both cannot be true.** Check which tier actually emits these
before spending anything on them — `grep` the generated parts, do not trust either claim.

### P3. Only then, the stl primitive itself (option A), on branch `1.5.1`.

Follow the `953ddd9` template in full (macro + `.fj` program + 2 CSV rows + `.out` fixture + the two
README updates it missed). Take the maintainer's naming decision first. Build the 16-bit form only —
12-bit is the harder table placement for no extra benefit, since one 2^16 table serves every width.

### P4. Convert doom's multi-byte runs, one at a time, each gated.

Ranked by the census. The one to check first is `lines_steps_load2` (`frame_render.fj:1440-1480`):
it reads four 4-byte piece records in sequence, and the slot bytes are always initialised
(`sfslot:` is `;0 * dw` padded, `wall_renderer.py:2031-2032`), so reading all 16 bytes speculatively
in aligned pair-reads should be value-identical. **If that holds it jumps from ~108 to ~648
removable dereferences and becomes the single largest item — and it needs no relayout.**

---

## 8. What NOT to do

* **Do not generalise before one call site is gated.** The repo's own history is that the coarse-cull
  pre-pass was built before being priced and cost +24.7M (R23/R32).
* **Do not quote the derived @ figures as results.** The one measured conversion came in at 45% of
  the stl prediction. Predict, then measure, then quote the measurement.
* **Do not touch an existing stl signature.** CONTRIBUTING is explicit; add names, never change them.
* **Do not assume `deg_gate` is sufficient.** This session proved twice that four viewpoints pass
  builds the 260-frame `ca2_sweep` then fails. For anything touching pointers — which is to say
  everything here — the sweep is the picture proof.
* **Do not start with the 12-bit width.** Its table placement is strictly harder than 16-bit's.

---

## 9. Provenance

Six agents: four research angles (wider fetch, amortised setup, call-site census, stl conventions)
and two adversarial refuters aimed at the feasibility verdicts. **Both refutations returned
`refuted=False`** after line-by-line traces of `xor_from_pointer.fj:29-54` and
`xor_to_pointer.fj:120-146`; the refuter's own summary was *"I tried to break it on six fronts and it
held on five"* — read `scratchpad/_fjptr_findings.txt` for the sixth and for every open question
before implementing.
