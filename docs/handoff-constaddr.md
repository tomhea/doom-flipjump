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

## 9. C1: the dispatch generator — ATTEMPTED, NOT LANDED, and why

The primitives are in and proven (`src/fj/m1_reset.fj`: `m1.readbyte`, `m1.readbyte_reg`,
`m1.writebyte`; all 256 values, guards, non-destructive read, 2 mutations). What is NOT in is the
piece that makes them reach a RUNTIME index: a dispatch whose handlers are constant-address reads.

**Two bugs found, one fixed, one fatal-as-designed.**

1. **`wflip <dst>, <a full address>` is NOT one op.** The first version computed each handler's
   return label as `handlers + d*4*dw + 2*dw`, assuming a 4-op handler. The marker bit was then
   never undone and every source cell came back with **+256** in it (`arr[0] = 269` for a planted
   13) — a beautifully specific symptom. Fixed by giving each handler a REAL label and using `pad`
   to force the uniform stride the switch indexes by.

2. **The round trip cannot nest inside a dispatch handler.** After the fix the reads still do not
   complete, and the cost column gives it away: 0.0 ops/call at both program sizes, i.e. the reads
   are not executing at all. The handler jumps INTO an array cell and returns via
   `hex.pointers.ret_after_read_byte`, while the dispatch returns via `hex.tables.ret` — two
   wflip-based return mechanisms in flight at once. **This is exactly the R42 hazard
   `generate_bands_walk_fj` already documents**: *"handlers contain NO `hex.*` macros (they would
   corrupt the shared dispatch return)"*. The byte-table read is such a macro.

**So the survey's C1 — and with it C3, C4 and C6, which all assumed the same dispatch — rests on a
mechanism that the repo's own existing generator says does not work.** The emitter agent reported
prototyping it at 153.6 ops/call; that measurement should be re-examined, because it disagrees with
both R42 and with what happens when the shape is built on `hex.tables`.

**A viable route probably exists** — a dispatch that does NOT use `hex.tables`, hand-rolling its own
return so only one wflip-return is live — but that is a new mechanism, not an application of an
existing one, and it needs its own correctness proof before any op count from it is quoted.

`scratchpad/constrd_probe.py` is the probe, with its controls and its negative control (which does
reject a broken handler). The generator itself was BACKED OUT of `src/doomfj/lut_generator.py`
rather than left in unused — an unproven, unreachable generator is dead code.

## 10. C7 KEPT, C10 REJECTED — and the row rule in disguise

**C7 (hot/cold array move) KEPT.** deg_gate, byte-exact, better at all four:

| | (664,291) | (1272,-724) | (1869,479) | spawn |
|---|---:|---:|---:|---:|
| C2+C8 | 44,573,453 | 36,087,127 | 39,842,687 | 34,648,801 |
| **+C7** | **44,494,846** | **36,031,157** | **39,771,895** | **34,598,353** |
| | -78,607 | -55,970 | -70,792 | -50,448 |

...and that is only THREE of the six arrays -- deg_gate has no `moving_things`, so `sshead`/
`thnext`/`thss_rt` are not even in that build. Span unchanged: this is placement, not duplication.

**C10 (bake `seg_normalangle`) REJECTED** -- mixed, net **+26,553 WORSE**:
+69,165 / -20,900 / +105,694 / -127,406.

**Why, and it is worth internalising.** The macro built `((segangle & 0xFFFF) << 16) + ANG90` from
`hex.zero 8` + `hex.mov 4` of a SPARSE 4-nibble angle + `hex.add 8` against `0x40000000` -- a
constant with exactly ONE nonzero nibble. Baking it replaces all that with `hex.mov 8` of a DENSE
32-bit value. Cost follows the NONZERO NIBBLES OF THE SOURCE, so the add being deleted was already
nearly free and the mov being added is not.

**BAKING A CONSTANT IS NOT AUTOMATICALLY CHEAPER. It is cheaper only when the baked value is no
DENSER than the pieces it replaces.** This is [[fj-cost-model]]'s ROW RULE reappearing outside
multiplication, and it is the second candidate (after C11) that a static op-count model rated HIGH
and the gate rejected. Both were about operand DENSITY, which such a model does not represent.

⚠ Note the shape of the C10 and C11 results: mixed sign across viewpoints, roughly symmetric
magnitudes. That signature means "the cost is data-dependent and I changed which data it depends
on", not "small win". Treat it as a rejection, not as noise to average away.

## 11. A THIRD stale assembler verdict — 13 tests skipped for a reason that may not hold

`tests/fj/test_collision_fj.py` skips **13 tests** with:

> `bake-as-code does not assemble at this scale (>50 min)`

That is the same verdict as `sim.fj:12-14` (bake the blockmap) and `sim.fj:411-415` (unroll
`bind_things`) — all three predate 2026-08-20, when the assembler stopped being "~cubic in unrolled
ops" and turned out to be MEMORY-BOUND with a measured exponent of 1.12, taking the shipped program
from 6,332 s to 559 s.

So the repo currently has **three decisions and thirteen skipped tests** resting on a cost model
that no longer describes the tool. None of them is necessarily wrong now — the sizes involved are
large — but none has been re-measured either. **Re-time one before trusting any of them.** The
cheapest is the skipped tests: they either run or they do not, and finding out costs one run.

## 12. C5 and C7 isolated — and the sweep cannot see collision at all

**The methodological finding first, because it invalidates a class of measurement.**
`scratchpad/m1_sweep.py:101` feeds `encode_feed(vx << 16, vy << 16, va, 0)` -- **keys = 0**. The
player never moves across all 260 frames, so `try_move` / `check_position` / `check_line` never run.
**The repo's headline metric describes a STATIONARY player.** That is fine for renderer work, which
is what it was built for, but a collision optimisation is invisible to it by construction -- and
reading the sweep alone would have rejected C5.

Measured on the shipped tier, all runs byte-exact:

| build | sweep (stationary) | play (100 frames, moving) |
|---|---:|---:|
| C2+C8 | 29,395,682 | 48,615,435 |
| + C5 | 29,817,038 (+421,356) | 47,375,658 (**-1,239,777**) |
| + C5 + C7 | 29,737,004 | 47,277,611 |
| **C7 alone contributes** | **-80,034** | **-98,047** |

**C7 is kept: it helps BOTH workloads and costs no span** (85,523,458 vs 85,523,360 words -- 98
words, i.e. nothing). An earlier revert of C7 was WRONG; it was never the regression.

**C5 is kept on the movement asymmetry**: +421k stationary against -1.24M moving, ~3:1, and real
play moves. It does cost ~414k span and ~1,700 s of assemble time, which C2/C8/C7 did not.

⚠ **C5's stationary cost is NOT explained.** With `keys=0` the collision path should barely execute,
and the +176 superset cells account for only ~3.5k of the 421k. Either `check_position` runs more
than expected on a stationary frame, or the split costs something outside `check_line`. **Do not
quote a mechanism for it; it has not been found.**

**And C5's premise had to be re-measured twice.** `scratchpad/ca_bbox_rate.py` first reported
**0.0% rejected**, which looked like the premise collapsing. `PLAYER_RADIUS` is 16.16 FIXED
(1,048,576) while `blockmap_candidates` and the bbox test take WHOLE MAP UNITS, so the query box
spanned the entire map. The tell was not the rate but the candidate count: **1,175 per position
against a true ~34**. Corrected: **98.8% rejected**, better than the 93% the survey assumed.
