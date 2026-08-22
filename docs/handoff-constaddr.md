# The constant-address lever — a full-program survey

**One sentence.** M1 replaced a runtime-address byte clear with a constant-address one and got 10x;
this is the survey of everywhere else that argument applies, run as seven parallel audits with a
measured price list underneath.

## 1. The price list — MEASURED this session, with controls

`scratchpad/ptr_price_list.py`, log `scratchpad/_ptr_price.log`. Every cost is a slope over FOUR
program sizes (32/96/160/224 unrolled reps), so fixed startup cannot be smuggled in. Vacuity control
on every row (memory read back), a body-removed control, and a `--selftest` negative control that
mutates the macros and requires rejection — re-run and passing.

| primitive | ops/call | constant-address form | ops/call | ratio |
|---|---:|---|---:|---:|
| `hex.ptr_index` | **1554.2** | *none while the index is runtime* | — | — |
| `hex.write_byte_and_inc` | 978.4 | `m1.writebyte` | 110.3 | 8.9x |
| `hex.write_byte` | 805.6 | `m1.writebyte` | 110.3 | **7.3x** |
| `hex.zero_ptr` | 795.9 | `m1.zerobyte` (ships) | 79.6 | **10.0x** |
| `hex.read_byte_and_inc` | 780.9 | `m1.readbyte` | 111.4 | 7.0x |
| `hex.read_byte` | 628.0 | `m1.readbyte` | 111.4 | **5.6x** |
| `hex.ptr_add 1` / `ptr_sub 1` | 141.2 / 145.6 | folded into the op | 0 | — |
| a 5-byte RECORD read (`set` + 5x`read_byte_and_inc`) | **4569.6** | 5x `m1.readbyte` | 620.4 | **7.4x** |

**The address plumbing is 82-86% of every byte access.** That is the M1 thesis, now measured across
the whole primitive set rather than one macro.

⚠ **CORRECTION TO THE M1 FIGURES.** `docs/handoff-m1-reset.md` and this repo's commit messages quote
`943 -> 91.1 ops/cell (10.3x)`. Those are **not isolated per-call costs**: the 943 bundles a
`ptr_inc` (measured: `zero_ptr + ptr_inc` = 937.0) and the 91.1 bundles the per-cell raw-`wflip`
plant (~11 ops). Isolated: **795.9 -> 79.6, 10.0x**. The M1 conclusion is unaffected — the reset's
real cost was measured end-to-end at 250,789 ops/frame — but do not quote 943/91.1 as per-call.

## 2. The lever that generalises it — PROTOTYPED AND MEASURED

M1 needed the address constant. The program's dominant pattern is a **constant base with a runtime
index**, which `ptr_index` charges 1554.2 for and which no constant-address macro can touch.

A **dispatch whose handlers are constant-address reads** does touch it. Prototyped, 256 entries,
4-op handlers, correctness controls passing (two values planted, both nibbles correct, source cells
left restored):

| today | ops | dispatch | ratio |
|---|---:|---:|---:|
| `hex.set w/4` + `ptr_index` + `read_byte` | **2,188** | **153.6** | **14.2x** |
| `ptr_add 1` + `read_byte` (walked pointer) | 704 | 153.6 | 4.6x |

Span: one 256-entry dispatch is about 3,072 words, roughly **0.006%** of the 48.7M-word headroom.
And the baked byte-write form measured **5.8x SMALLER** than `hex.write_byte` per instance (58.9 vs
340.8 fjm bytes) — so this trades ops for span in the *good* direction, the opposite of an unroll.

## 3. The finding that reframes the whole search

**Most pointer sites are dead on the shipped tier.** Four agents found this independently:

| file | pointer sites | live in `raster_mode="lines"` |
|---|---:|---:|
| `frame_render.fj` 1-1700 | 84 | 40 |
| `stream_render.fj` | 70 | **10** |
| `plane_bands.fj` + `plane_render.fj` | 16 | **0** |

`plane_render.fj` and `plane_bands.fj` contribute **zero ops** to the shipped frame — verified
against the emitted program (grepping their macros in `build/generated_loop/*.fj` returns nothing).
One agent nearly costed a ~2M-op win on `wpx_wall`, which `rep`-expands to nothing.

**Before optimising anything here, check it is instantiated.**

## 4. Ranked candidates

Op figures are the measured price list x oracle-measured populations. **They are estimates of a
frame delta, not measured frame deltas.** Nothing below has been built.

| # | candidate | est. ops/frame | conf. | span |
|---|---|---:|---|---|
| 1 | per-column arrays (`drawn`/`pclm`/`sfflag`/`sprflag`/`spslot`/`sfslot`) -> constant-address dispatch | **~2.2M** | HIGH (read half prototyped) | +18k words |
| 2 | `ttang` + `sdrecip`: emitted, never called; live path still pays `read_table_packed` | ~1.4-1.7M | **HIGH (grep-verified)** | **negative** |
| 3 | `ts_piece_wr` / `lines_spr_load` 7-byte record stores -> baked handlers | ~0.8-1.0M | MEDIUM | +66k words |
| 4 | `sim.thing_load`: 17-byte row + 16-nibble pos -> dispatched xor_by block | ~0.4-0.8M | MEDIUM-HIGH | +5k words |
| 5 | `check_line`: hot/cold split the 22-byte row (93% die on the bbox test, MEASURED) | ~0.3-0.6M | HIGH mechanism | ~0 |
| 6 | `step_shade` -> D4 dispatch (**found independently by two agents**) | ~0.25-0.7M | MEDIUM | check entry count |
| 7 | move `sshead`/`thnext`/`thss_rt`/`pclm`/`sfflag`/`sprflag` into hotdata (R20) | ~0.2-0.4M | HIGH mechanism | **zero** |
| 8 | `sprite_runs`: counter -> `rel==0` sentinel (idiom already ships in `wpx_wall`) | ~0.03-0.5M | **HIGH** | **negative** |
| 9 | delete the redundant `ptr_index` at `frame_render.fj:2660` | ~0.2M | MEDIUM-HIGH | negative |
| 10 | bake `seg_normalangle` (a pure function of `seg.angle`, which is already baked) | ~25-45k | HIGH | zero |
| 11 | `hex.add 8, X, cang90` -> `hex.add_constant` (one nonzero nibble, ~8 sites/seg) | ~870k | HIGH | negative |

## 5. Two rejections that are now STALE, and one that is not

**STALE — the assembler changed under them.** `sim.fj:411-415` rejects unrolling `bind_things`
("over 40 MINUTES TO ASSEMBLE — the assembler is ~cubic in unrolled ops") and `sim.fj:12-14` rejects
baking the blockmap ("~57k lines that did not finish assembling in 50 minutes"). Both verdicts
predate 2026-08-20: the assembler is **memory-bound and pages, measured exponent 1.12, not cubic**,
and the same program went 6,332 s -> 559 s. The *benefit* side of those trades never changed.
**Re-test before believing either rejection.** Other "measured and rejected" notes in this repo may
be in the same state.

**NOT STALE — a genuine dead end.** "Arm the pointer once, then step it by `dw`" would fix every
`read_table_packed` in the program. It does not work: stepping an armed pointer means xoring
`old ^ new` into the address fields, and computing that delta costs ~900 ops — *more* than the
~400-op re-arm it replaces. The constant-address dispatch is the right way to get that win.

## 6. What binds

* **`ptr_index` is 32% of all pointer spend** (44 sites x 1554.2) and constant addressing cannot
  touch it. Only the dispatch can. Audit which of those 44 indices are secretly compile-time first.
* **`rep` needs a LITERAL count** — a `rep` over a macro parameter silently expands to nothing.
  Every unroll lives in the emitter, where the count is a Python int.
* **Byte cell vs nibble cell (R57).** `drawn` is a byte array on the `lines` tier and a `hex.vec 4`
  nibble array elsewhere. A byte op on a nibble cell corrupts (0xA5 -> 0x22A5). Gate on the tier.
* **`hex.pointers.read_byte` is a SHARED global.** A handler that runs while another read is in
  flight corrupts it — the R42 hazard `generate_bands_walk_fj` documents. Check every call site.
* **The M1 restore set bakes absolute addresses.** Any layout change (candidate 7 especially) trips
  the two-pass assert and needs the set regenerated. That is the control working, but it makes a
  one-line move a two-step change.
* **`deg_gate` op counts WILL change.** Byte-exactness of the four frames is the contract; the
  op-count delta is the measurement. Price by ADDING (the ablate discipline), never by stubbing.

## 7. What to do first

**Candidate 2**, because it is nearly free: two dispatch tables are already in the binary, already
correct, already the right shape, and the replacement lines already exist verbatim at
`projection.fj:1835` and `:1916`. It removes span. It is a grep-verifiable, few-line change.

Then **candidate 1**, because it is the largest and its read half is prototyped and measured. Port
`m1.readbyte`/`m1.writebyte` into `src/fj/` first — they exist only in the measurement harness — and
build the write-half dispatch, which is the one piece nobody has prototyped.

## 8. MEASURED RESULTS — and two candidates the gate rejected

`scratchpad/deg_gate.py`, 4 viewpoints, every run BYTE-EXACT. Baseline is the tree at `c4d2e8e`.

| | (664,291) | (1272,-724) | (1869,479) | spawn |
|---|---:|---:|---:|---:|
| baseline | 50,186,307 | 40,950,575 | 45,534,466 | 39,057,903 |
| **C2 + C8 (SHIPPED)** | **44,573,453** | **36,087,127** | **39,842,687** | **34,648,801** |
| | **-11.2%** | **-11.9%** | **-12.5%** | **-11.3%** |
| C9 alone (rejected) | +239,388 | +102,679 | +337,586 | +84,086 |
| C11 alone (rejected) | +203,882 | -200,834 | +320,818 | -332,386 |
| C9 + C11 (rejected) | +92,675 | -254,101 | +112,528 | -439,955 |

**C2 + C8 came in ~3x BETTER than estimated** (survey said ~1.5-2.2M combined; measured 4.4-5.7M).

**C9 REJECTED — worse at all four.** The pre-scan walks `drawn[]` on far more segs than ever reach
pass 2, so paying one `hex.mov w/4` per pre-scan seg to save one `hex.ptr_index` per pass-2 seg is a
net loss. Back-solving (664,291): ~870 pre-scan segs against ~99 pass-2 segs. There is no cheap
winning variant — moving the copy to the `occproc` path costs a `ptr_index` there instead, which is
exactly what it was trying to remove. **Do not retry without changing pass 2's start column**, which
is a behaviour change, not an optimisation.

**C11 REJECTED — a wash, net -8,520 ops over four viewpoints**, with near-symmetric +-200-330k
swings. The swings are the finding: **`hex.add n, dst, src`'s cost is DATA-DEPENDENT** (the carry
chain does different work for different operand values), so replacing it with `hex.add_constant`
does not buy a fixed per-call saving -- it buys a different data-dependence, and which one wins
varies by viewpoint. This candidate was rated HIGH confidence at ~870k from a static op-count model.
**A static model cannot price a carry chain.**

⚠ **METHOD NOTE, learned the hard way here.** These three changes are NOT ADDITIVE: C9 and C11 each
regress against the baseline, yet C9 *appears* to help when measured as the marginal step from
C11-alone to C11+C9. **A marginal delta does not give you a candidate's sign.** Isolate against the
committed baseline, one candidate at a time, or the arithmetic will tell you a confident story about
the wrong change -- which it did here, twice, in opposite directions.
