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

**The address plumbing is 82-90% of every byte access.** That is the M1 thesis, now measured across
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
| `hex.set w/4` + `ptr_index` + `read_byte` | **2,188** | **153.6** ⚠ | **14.2x** ⚠ |
| `ptr_add 1` + `read_byte` (walked pointer) | 704 | 153.6 ⚠ | 4.6x ⚠ |

⚠ **The 153.6 column is RETRACTED — do not quote it.** It came from the C1 dispatch prototype,
and §9 shows that dispatch does not execute at all. Worse (CR-2026-08): the probe's own
CONTROL — the known-good `hex.set` + `ptr_index` + `read_byte` idiom — also reads ~0 ops/call
in that harness, so the harness, not the mechanism, is what those numbers measure. The
MEASURED constant-address prices in this table (the `m1.*` rows, from
`scratchpad/ptr_price_list.py`) are unaffected.

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
frame delta, not measured frame deltas.**

⚠ **STALE HEADER (CR-2026-08).** This said "Nothing below has been built". Seven of the eleven
rows have since been built and measured; the confidence ratings in this table are the
PRE-BUILD guesses and are kept only to show how far off they were. For what actually happened
see §8 (C2/C8/C9/C11), §10 (C7/C10) and §12 (C5/C7). C9, C10 and C11 were REJECTED despite
"HIGH"/"MEDIUM-HIGH" ratings here.

| # | candidate | est. ops/frame | conf. | span |
|---|---|---:|---|---|
| 1 | per-column arrays (`drawn`/`pclm`/`sfflag`/`sprflag`/`spslot`/`sfslot`) -> constant-address dispatch | **~2.2M** | HIGH (read half prototyped) | +18k words |
| 2 | `ttang` + `sdrecip`: emitted, never called; live path still pays `read_table_packed` | ~1.4-1.7M | **HIGH (grep-verified)** | **negative** |
| 3 | `ts_piece_wr` / `lines_spr_load` 7-byte record stores -> baked handlers | ~0.8-1.0M | MEDIUM | +66k words |
| 4 | `sim.thing_load`: 17-byte row + 16-nibble pos -> dispatched xor_by block | ~0.4-0.8M | MEDIUM-HIGH | +5k words |
| 5 | `check_line`: hot/cold split the 22-byte row (92.8% die on the bbox test, MEASURED) | ~0.3-0.6M | HIGH mechanism | ~0 |
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

`scratchpad/deg_gate.py`, 4 viewpoints, every run BYTE-EXACT. Baseline is the tree at
`c4d2e8e` for the C2 and C8 rows. ⚠ **The C9 and C11 rows below are deltas against C2+C8**
(the committed baseline they were isolated from, `17a90f6`), NOT against `c4d2e8e` — the
isolation logs are `_ca_A4` (C9 alone), `_ca_A3` (C11 alone) and `_ca_A2` (C9+C11).

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

⚠ **TWO CORRECTIONS (CR-2026-08).**

**(1) The probe could not be run by anyone but its author.** `d89d488` committed it and backed the
generator out in the SAME commit, so `generate_const_read_dispatch_fj` exists at no commit and the
probe died on `ImportError`. It has been made SELF-CONTAINED: the generator is RECONSTRUCTED inside
the probe from the shape of `lut_generator._per_entry_table` (the dispatch half) and
`src/fj/m1_reset.fj::m1.readbyte` (the handler half, inlined so the negative control can break one
handler's undo-flip). It is a faithful reconstruction of the MECHANISM, not the original text — do
not quote it as the original. It reproduces both documented failures: source cells come back +256
(bug 1) and the reads show 0.0 ops/call (bug 2).

**(2) The 0.0 ops/call figure is NOT evidence about the dispatch.** Running the probe's own CONTROL
arm — `hex.set` + `hex.ptr_index` + `hex.read_byte`, the idiom the whole program uses and which
demonstrably works — gives the SAME reading:

```
control n=8   term=3  ops=3,378   read back [0,0,0,0,0,0]  want [13,180,91,2,169,80]
control n=24  term=3  ops=3,318   read back [0,0,0,0,0,0]  want [13,180,91,2,169,80]
```

`term=3` is an error termination, and the probe DISCARDED the termination cause. So the harness
never executed either arm, and "0.0 ops/call, i.e. the reads are not executing" describes the
harness, not the mechanism. **The R42 argument above is structural and stands on its own; the
measurement does not.** Do not cite the ops/call figure until the probe's control reads back its
planted values. (`scratchpad/ca2_price.py`, written for §13, is the shape to copy: it refuses any
arm whose destination register does not hold the table's value, and that control caught three real
harness bugs in one afternoon.)

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

⚠ **COLUMN LABEL CORRECTED (CR-2026-08).** The first column is NOT the sweep median. Every number
in it is `m1_sweep.py`'s **"loop binary, per frame"** line — the LOOPING binary's total ops divided
by 260, i.e. a MEAN, and one that INCLUDES the ~250k/frame M1 reset. It was labelled "sweep", which
reads as the median. The comparable reference is the same log's **"reference build, per frame"**
(a mean of the same 260 frames, one frame per run) = **30,929,878** — NOT the median 30,191,585,
which is a different statistic of a different binary. Comparing across those two lines is the
median-vs-mean error this campaign was already burned by once.

| build | loop binary, MEAN ops/frame (stationary, incl. reset) | play (100 frames, moving) |
|---|---:|---:|
| reference `_rssprobe.fjm` (no reset in the program) | 30,929,878 | — |
| C2+C8 | 29,395,682 | 48,615,435 |
| + C5 | 29,817,038 (+421,356) | 47,375,658 (**-1,239,777**) |
| + C5 + C7 | 29,737,005 | 47,277,611 |

⚠ The 30,929,878 → 29,737,005 gap (**-1,192,873**) is **round 1's saving MINUS the reset it now
pays**, not round 1's saving. `_rssprobe.fjm` (sha `3c13ec21…`) is unchanged across the whole
campaign, so it is a valid fixed reference — but it has no self-reset, and the loop binary does.
Do not read -1,192,873 as what C2+C8+C5+C7 are worth.
| **C7 alone contributes** | **-80,034** ⚠ | **-98,047** ⚠ |

⚠ **That row is a MARGINAL delta (C5-alone → C5+C7), which is the comparison §8's own METHOD
NOTE forbids** — the same error that produced the wrong C9 verdict. C7 *was* isolated properly,
but on deg_gate against C2+C8 (§10, −50k…−79k on all four viewpoints); its SHIPPED-TIER
contribution has never been measured against a C7-less build of this tree. Treat the two
numbers above as "C7 on top of C5", not as "what C7 is worth".

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
against a true 12.6-19.6**. ⚠ **Corrected AGAIN (CR-2026-08).** The 98.8% figure was
measured on a uniform 512-unit grid over the map bounding box -- including points in no
sector at all -- while the docstring claimed "real walk positions". Re-measured on two point
sets that mean something (`scratchpad/ca_bbox_rate.py --selftest`, log
`scratchpad/_ca2_bbox2.log`):

| point set | positions | candidates/position | bbox-rejected |
|---|---:|---:|---:|
| **SWEEP** — the sweep's own walkable grid (the governing metric's positions) | 40 | 12.6 | **99.6%** |
| **CONTACT** — in a sector, within 24 units of a line (where a moving player is) | 40 | 19.6 | **92.8%** |

The two sets differ because the sweep grid DROPS every point within 24 units of a line and
PLAYER_RADIUS is 16 — so on the sweep set no candidate can touch the player box at all, and
the rate is near 100% by construction. CONTACT is the honest number for C5: **92.8%**, which
is the survey's 93% almost exactly. The probe now ships three negative controls (force the
reject always-false, force it always-true, restore the 16.16 radius bug) and an INDEPENDENT
soundness check (Liang–Barsky segment-vs-square, not a restatement of the four bbox
compares); the always-true control finds 53 unsound rejections, which is what proves the
soundness check can fire at all. Its first version could not — it re-ran the same four
comparisons inside the `if rejected:` branch.

---

## 13. ROUND 2 — the four candidates the consolidation DROPPED

The eleven-candidate table in §4 was consolidated from seven agent surveys, and it lost four
findings from the one survey whose estimates later proved accurate. None of them was blocked by
R42; all four use `generate_dispatch_table_fj`, the *value-lookup* dispatch that `srdisp`/`xtadisp`
already ship — a different mechanism from the byte-read handler §9 shows does not work.

| # | change | status |
|---|---|---|
| 1 | `proj.angle_to_x`: `viewangletox` as a per-entry dispatch (`vtxdisp`) | SHIPPED |
| 2 | `proj.scale_from_global_angle`: the `anglea` sine is COLUMN-ONLY (`sinadisp`) | SHIPPED |
| 3 | `finesine`: `per_result_nibble` -> `per_entry` | SHIPPED |
| 4 | `cproj` baked; 22 redundant `hex.zero` before `hex.mov` deleted | SHIPPED |

### 13.1 What it is worth — MEASURED, both sides, in one session

deg_gate, 4 viewpoints, **every run BYTE-EXACT**. The baseline is a pristine `f7a8ac7` worktree
built in the same session (`scratchpad/_ca2_gate_base.log`), not a log from a previous tree — and
it reproduces `_ca_c7.log` to the digit, which retroactively confirms that C5 instantiates nothing
in this tier.

| viewpoint | base `f7a8ac7` | + round 2 | delta |
|---|---:|---:|---:|
| (664,291,0x18000000) | 44,494,846 | 42,705,614 | **-1,789,232** (-4.02%) |
| (1272,-724,0x40000000) | 36,031,157 | 34,382,519 | **-1,648,638** (-4.58%) |
| (1869,479,0x80000000) | 39,771,895 | 37,977,716 | **-1,794,179** (-4.51%) |
| (-416,256,0x0) | 34,598,353 | 32,579,930 | **-2,018,423** (-5.83%) |

⚠ **Those four are WORST CASES.** The governing metric is the 260-frame sweep median. Both
binaries were swept in ONE interleaved run (`scratchpad/ca2_sweep.py`, log
`scratchpad/_ca2_sweep.log`) — which needed no extra build, because deg_gate leaves its binary in
a temp dir:

| | median | mean | min | max |
|---|---:|---:|---:|---:|
| base `f7a8ac7` | 24,795,197 | 24,964,916 | 6,245,371 | 49,614,388 |
| + round 2 | 24,060,771 | 24,116,889 | 6,084,776 | 47,835,191 |
| **delta** | **-734,426** | **-848,027** | -160,595 | -1,779,197 |
| pct | **-2.96%** | -3.40% | | |

**PICTURE CONTROL: 260 of 260 frames byte-exact between the two binaries** — a strictly stronger
proof than deg_gate's four. VACUITY CONTROL: 254 distinct pictures across 260 frames.

⚠ The two tables above are **deg-tier** (`scratchpad/deg_gate.py`'s config). `deg_gate` passes no
`state_wire`, no `player_sim`, no `collide` and no `moving_things`, so it builds a program without
the whole M14 layer and its median runs ~4.3M below the shipped tier's. Their absolute values are
not comparable to anything in §12.

### 13.1a The SHIPPED tier — the same measurement on the program that actually ships

Two `self_reset=False` builds (`scratchpad/ca2_shipbuild.py`), one from a pristine `f7a8ac7`
worktree and one from this tree, swept interleaved over the same 260 viewpoints with the same
`encode_feed` + things + bindings + visibility wire `m1_sweep.py` uses
(`scratchpad/ca2_sweep_ship.py`, log `docs/constaddr-evidence/sweep_ship.log`):

| | median | mean | min | max |
|---|---:|---:|---:|---:|
| base `f7a8ac7` | 29,054,107 | 29,490,018 | 7,597,552 | 58,353,520 |
| + round 2 | 27,932,265 | 28,302,045 | 7,569,883 | 56,112,295 |
| **delta** | **-1,121,842** | **-1,187,973** | -27,669 | -2,241,225 |
| pct | **-3.86%** | -4.03% | | |

**260 of 260 frames byte-exact**, 0 viewpoints presenting != 1 frame, 254 distinct pictures.

⚠ **The shipped delta is LARGER than the deg delta (-1.12M vs -734k), not equal to it.** The
shipped tier carries `moving_things`, so more segs survive per frame and `angle_to_x` /
`scale_from_global_angle` run more often. **A saving measured on a reduced tier is a LOWER BOUND on
the shipped one when the change is per-seg work** — the reduced tier has fewer segs. Do not assume
a deg-tier delta transfers 1:1 in either direction; it is a different scene load.

### 13.1b The campaign on ONE metric, for the first time

§12's numbers are loop-binary MEANS including the reset; these are shipped-tier MEDIANS of
`self_reset=False` builds, which is what the cost model actually reports:

| build | shipped-tier median | delta |
|---|---:|---:|
| `_rssprobe.fjm`, pre-campaign (sha `3c13ec21…`) | 30,191,585 | — |
| `f7a8ac7` — round 1 (C2/C5/C7/C8) | 29,054,107 | -1,137,478 |
| this tree — + round 2 | **27,932,265** | -1,121,842 |
| | | **-2,259,320 total (-7.48%)** |

⚠ The first row is the ONE number here not re-measured in the round-2 session: it comes from
`scratchpad/_ca_sweepF.log` / `docs/m1-evidence/m1_sweep6.log`, produced by the same tool over the
same 260 viewpoints with the same wire. Corroboration: its span is 84,823,030 and the `f7a8ac7`
baseline built here is 84,883,902 — a difference of 60,872 words, which is round 1's span add.
Re-run it before quoting the -7.48% as certified.

**Round 2 is worth about as much as all of round 1.** That is the price of the consolidation slip
described at the top of this section.

### 13.2 Prices, and one that had to be corrected

`scratchpad/ca2_price.py` builds each arm from `src/fj/projection.fj` itself with the real tables,
prices it as a DIFFERENCE of two program sizes, and refuses any arm whose destination register
does not read back the table's value (see §13.4).

| arm | ops/call |
|---|---:|
| `proj.angle_to_x`, `disp=0` (packed read, as shipped) | 8,827.7 |
| `proj.angle_to_x`, `disp=1` (the same macro, dispatch) | 1,809.5 |
| **saved** | **7,018.2** ⚠ |
| `finesine.read_sin`, `per_result_nibble` (as shipped) | 983.2 |
| `finesine.read_sin`, `per_entry` | 452.6 |
| **saved** | **530.6** ⚠ |

⚠ **These are ISOLATED-PROBE prices and they do NOT reconcile against the whole-program
delta — see §13.8. Do not estimate from them.**

⚠ **The first run of that probe said 8,404.7 for `angle_to_x`, and it was wrong.** Arm B was a
BARE `vtxdisp.lookup` rather than the macro with `disp=1`, so `A-B` credited the change with
`angle_to_x`'s whole prologue (`mov 8` + `add 8` + `shr_hex 8,5` + `mov 3` + `cmp 3`) — work the
change keeps. **Measure a rep-gated macro by flipping its flag, never against the inner call the
flag selects.** The corrected 7,018.2 is what the source comments carry.

### 13.3 ⚠ WITHDRAWN — this section fitted a coincidence and the numbers refute it

This section used to explain the -734,426 deg-tier median as "~105 calls x 7,018 = 737k". That was
a NUMBER THAT HAPPENED TO MATCH, not a mechanism: the call count was inferred by dividing the
answer by the price, so of course it reproduced the answer. The one lesson worth keeping is the
statistical one — **a per-call price times a MEDIAN call count is not a median saving**, because
the median of the call-count distribution is a different frame from the median of the ops
distribution. Everything else here was retro-fitting; see §13.8.

### 13.4 What the probes now refuse to do

Both new probes ship two-sided controls, because §9's C1 probe did not and its central number was
an artifact:

* `ca2_price.py` reads the destination register back after every run and reports the arm VACUOUS if
  it does not hold the table's value. That control caught three real harness bugs in this round —
  a data table placed BEFORE `stl.startup_and_init_all` (op 0 became a data word; the program
  halted in 2 ops and every arm read 0), and two arms silently off by one.
* `ca2_callcount.py` requires the instrumented frame to stay byte-exact against an uninstrumented
  one AND every counted name to fire at least once.
* `ca_bbox_rate.py` (rewritten, §12) now has three negative controls and an INDEPENDENT
  Liang-Barsky soundness check.
* `tests/host/test_dispatch_tables.py` decodes every entry of `ttang`, `sdrecip`, `xtadisp`,
  `vtxdisp`, `sinadisp` and `finesine` back out of the emitted handler text and compares to the
  shared kernel, with a mutation control. 0.25 s, and it closes CR-2026-08 R5.

### 13.5 The premise behind #2, and where it is pinned

`anglea = ANG90 + (visangle - viewangle)`, and every caller builds `visangle` as
`viewangle + xtoviewangle[col]`, so `viewangle` cancels EXACTLY (mod 2^32) and `anglea` is a
function of the screen column alone. All four fj call sites
(`wall_scale_setup` x2, `wall_scale_setup_m` x2) have the column in scope.

That premise is the whole change, so it is pinned in three places: an identity check over 966
(column, viewangle) pairs with a negative control that perturbs `visangle` off the column;
`test_sinadisp_every_entry_is_the_sine_of_that_columns_angle` (host, every column); and
`test_scale_from_global_angle_column_cases_byte_exact_vs_oracle`, which drives ONLY
column-derived cases through BOTH arms. A future caller that builds `visangle` some other way
fails that last test — deg_gate would only show moved pixels with no indication why.

### 13.6 What was checked and NOT taken

* **`proj.point_to_dist`** reads `tantoangle` with a packed read and `ttang` already exists — but
  it has NO fj caller; the shipped path uses `wall_setup_sgn`. The oracle calls it 88x/frame,
  which is exactly the trap: an oracle call count is not proof the fj macro is live.
* **`texture_u`, `column_setup`, `wall_scale_setup` (non-`_m`), `plane_render.draw_span`,
  `plane_bands.recip32`** all still use packed reads of tables that have dispatches. They are on
  the non-`lines` paths, which the shipped `e1m1_02_main.fj` does not instantiate (it calls
  `frame.seg_pass1_leaf_body_lines`, `..._ts` and `frame.seg_pass2_leaf_body_lines`). Dead in the
  shipped tier; live in tests.
* **`finetangent`** in `texture_u` has no dispatch and is on the same dead path.

### 13.8 ⚠ THE ATTRIBUTION IS UNVERIFIED — the RESULT is not

**What is measured and certain:** the shipped-tier median falls 29,054,107 -> 27,932,265
(-1,121,842, -3.86%), 260 of 260 frames byte-exact, span down 127,226 words. Nothing below
qualifies any of that.

**What is NOT established: that this saving is the four changes.** Profiling one shipped-tier frame
(`scratchpad/ca2_profile.py`, viewpoint (-416,256,0x0), both binaries, byte-exact and every op
accounted for) gives 42,464,060 -> 39,899,775, a saving of 2,564,285. But at that viewpoint
`scratchpad/ca2_callcount.py` counts `angle_to_x` running **430** times, and §13.2 prices the
change at **7,018.2 ops/call**:

    angle_to_x alone : 430 x 7,018.2  = 3,017,826 predicted
    the WHOLE frame  :                  2,564,285 measured

**One of four changes predicts more saving than the entire frame achieved**, before `sinadisp`,
`finesine`, `cproj` and the 22 deleted `hex.zero` calls, which together add roughly another 1.1M.
So the per-call price, the call count, or both are wrong by about 2x, or something in the change
costs ~1.6M that is unaccounted for. **Which of those is true is NOT KNOWN.**

Two attempts to resolve it failed, and both failures are worth recording:

* **A padding experiment** — rebuild without C5 but with 413,668 words of dead padding — was
  proposed and rejected. It would construct a configuration that never ships, and even a perfect
  match would only be CONSISTENT with a placement story, never identify a cause. Owner's call, and
  correct: that is not how you find out where time went.
* **A per-address profile diff** was built and run, and is useless for this. The two binaries differ
  in span by 127,226 words, so every region past the divergence sits at a different address in
  each; the diff shows 223 buckets losing 26.7M ops and 219 gaining 24.1M against a net of 2.56M.
  That is the image RELOCATING, not work disappearing. **Matching buckets by address across two
  builds of different size compares unrelated code.**

**What would settle it:** ablate. Every one of the four changes is behind a `rep` gate or a
one-line emitter switch, so building with each flipped in turn and measuring ONE frame each gives
an exact split on the real program, with no attribution machinery — the repo's own rule, *price a
rep-gated macro by flipping its flag*. One wrinkle first: `scale_from_global_angle`'s `disp`
currently gates BOTH `sinadisp` and `srdisp`, so it needs splitting before it can isolate either.

A per-LABEL profiler was also considered and is NOT the answer here: the mangled labels do carry
the full macro chain (6,811,602 of them on this program), but the heavy code lives in shared
`stl.fcall` leaves emitted once and jumped into, so the chain records where code was EMITTED, not
who called it — and `hex.pointers.read_byte`, which is exactly where `read_table_packed`'s cost
sits, collapses into a single row serving every table in the program.

### 13.7 Span

| table | lines | note |
|---|---:|---|
| `vtxdisp` | 20,503 | 2,048 entries x 8 nibbles |
| `sinadisp` | 2,583 | 161 entries, one per column |
| `finesine` per_entry vs per_result_nibble | +8,117 | 65,536 -> 81,920 words |

The emitted `tables` part goes 300,177 -> 331,382 lines (+31,205), i.e. the TABLES add ~62k words.

⚠ **But the total span went DOWN.** MEASURED on the two shipped builds:

| | span_words | sha256 |
|---|---:|---|
| base `f7a8ac7` | 84,883,902 | `204ae314d710619c…` |
| + round 2 | **84,756,676** | `49d35b84ddd81ea7…` |
| | **-127,226** | |

An earlier draft of this section said "+62k words, +0.07%" — it counted the new TABLES and forgot
that the change also DELETES code at every expansion: `finesine` per_entry is ~790k characters
smaller than eight per-result-nibble tables, `angle_to_x` and `scale_from_global_angle` each shed
instructions from every instantiation, and 22 `hex.zero` calls are gone. Net, the program is both
faster and smaller. **A span estimate built from the data you added is not a span measurement**;
`headroom` went 1.581 -> 1.584.
