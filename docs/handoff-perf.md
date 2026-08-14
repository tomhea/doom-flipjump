# HANDOFF: the performance campaign — target band 20–25M median

Owner directive (2026-08-14, superseding both the 26M and 15M framings):

* **Baseline is TODAY.** The current renderer (P2b field-flip, SPR-NEAR, smudge fix) *and* the M14
  work are the starting point. **Do not go back to the 15M-era build** — those numbers were taken
  before correctness fixes that the repo itself calls the end of "cheating" (hidden sprites,
  invisible drop-offs).
* **Target: median anywhere in 20–25M.**
* **Graphics stay as they are.** You *may* remove some sprites. You *may* **suggest** optimisations
  that trade picture — suggest, priced, for the owner to accept or veto. Never apply one silently.
* **⚠ NO NUMBER WITHOUT EVIDENCE.** If a figure is not measured, it does not appear in this document
  as a figure. §2 is the ledger of what is measured and what is not; §3 is how to measure the rest.

---

## 1. What is measured, and how

Everything in this section was produced by a named tool this campaign, and the provenance is given
so it can be re-run or disbelieved.

### 1.1 The sweep — the target metric

`scratchpad/m14_sweep.py <fjm> --things [--cold] [--csv f]`. 260 frames: 65 walkable grid points
(step 256, the stock ray oracle, 24-unit boundary reject) × 4 angles, on the binary wire.

**⚠ The grid is VERIFIED identical to the pre-M14 certification sweep** — the coordinate sets of
`sweep_crfix2.csv` and `sweep_m14e_b1.csv` compare equal, so the before/after below is like-for-like
and not an assumption.

| build | median | mean | p90 | worst | min |
|---|---|---|---|---|---|
| certified, pre-M14 (`sweep_crfix2.csv`) | **22.94M** | 22.58M | — | 48.46M | — |
| M14-e as first shipped | 60.29M | 62.01M | 82.52M | 97.01M | 32.25M |
| + binding round-trip (`1202393`) | 38.48M | 40.21M | 60.36M | 74.78M | 11.54M |
| + clear & per-leaf reads deleted (`f54300e`) | **36.68M** | 38.17M | 58.08M | 71.67M | 9.67M |

**So M14 costs +13.7M at the median, measured.** That and the two endpoint medians are the only
whole-frame numbers in this document that are directly measured.

⚠ Two caveats on the metric itself, both real:
* The sweep runs **keys=0**, so the player sim is a no-op and **collision never runs**. The median
  excludes M14-d's collision cost entirely.
* `m14_sweep.py` reports `allops[n//2]`, which on an even-length list is the upper middle, not the
  arithmetic median (36.68M vs 36.66M here). Harmless, but pick one convention and keep it.

### 1.2 Per-call costs — k-sweep with controls

`m14_thload_cost.py` / `m14_thload_split.py`. Same body assembled at k = 1/17/33; the **marginal**
cost cancels startup and table bakes. Controls: marginals must be linear in k (reported, <10% drift),
and in the split, the parts must sum to the whole (measured 101.4% — no interaction).

| | ops/call |
|---|---|
| `sim.thing_load`, as it was | 69,503 |
| … the 22-byte row read + its 13 field extractions | 29,938 |
| … the position accessor | 16,995 |
| … `sp_z`/`sp_lt`, 3 table reads — **since removed** (`f54300e`) | 23,569 |
| **`sim.thing_load` today** | **45,934** |

Also measured, earlier in M14: baked point location **105,715 ops mean per lookup** (min 10,661,
max 298,411); an `fcall` BSP descent ~2.9M; collision **+11,602,784 ops on a moving tic**.

### 1.3 Whole-subsystem deltas — A/B on one binary

The gate reports cold vs warm bindings at four viewpoints: **−24,808,725 ops, identical to the op at
all four**, with byte-identical pixels. `_bind.py` reports `bind_things` COLD 28,687,917 / WARM
5,197,749 in isolation.

### 1.4 The map

| | segs | nodes | leaves | drawable things |
|---|---|---|---|---|
| `freedoom_e1m1.wad` — what every gate and sweep here builds | 2057 | 681 | 682 | 251 |
| `e1m1_lite.wad` — what `walk_e1m1.py` ships by default | 1378 | 470 | 471 | 197 |

**Every number in this document is the stock map.** That is the harder of the two and the one the
gates certify, so it is the safe place to work. ⚠ **If the deliverable is what `walk_e1m1.py` runs,
the target should be measured on lite and every number here must be re-measured** — do not mix them
in one report.

## 2. ⚠ What is NOT measured

These were carried as figures in earlier drafts of this plan. They are **removed** and listed here as
open questions, because none of them has evidence behind it:

* **How many `thing_load` calls happen per frame.** Earlier drafts said "~117"; that was a residual
  divided by a per-call cost, i.e. circular with the model it was used to confirm.
* **How many leaves the BSP walk VISITS per frame.** 682 are emitted; the walk stops when the frame
  is claimed, so the visited count is lower by an unknown factor.
* **What the unattributed remainder of M14's +13.7M is.** Subtracting the measured pieces leaves a
  gap that was previously *labelled* "the per-leaf walk" without evidence.
* **§4b's full-precision `wall_x_range_m` cost at the median.** The "+9–10%" came from four gate
  viewpoints at a different milestone.
* **`bind_things`' cost inside a real frame.** The 5,197,749 above includes the probe's own dump loop.
* **What any proposed lever would save.** All previous per-lever figures were estimates.
* **Where the base 22.94M goes today.** The repo has older ablation research, but it predates several
  correctness fixes.

## 3. THE METHODS — how to turn §2 into evidence

These are the seven instruments this repo has. Each entry says what it can price and what it costs.

**M1 — ablation sweep.** Build with a feature off, sweep, diff the medians against the same grid.
Prices a whole feature at the median, including all its second-order effects. `emit_wall_renderer`
already takes `ablate={…}`; existing members: `colstub`, `noprescan`, `noproj`, `projtwice`,
`scaletwice`, `skyall`, `sprnoemit`, `thingtwice`. Cost: one ~25-min build + one ~5-min sweep each.
**This is the only method that prices something at the median**, which is the target metric — prefer
it for anything load-bearing.

**M2 — k-sweep marginal cost.** Assemble the same body at k = 1/17/33 in a small program; the
marginal cancels fixed costs. Requires a **linearity control** (report the drift between the two
marginals) and, when splitting, a **sum control**. Prices a macro per call. Cost: minutes, no heavy
build. ⚠ Must use the emitter's real parameters — a probe with invented index widths measures a
program nobody builds.

**M3 — counter instrumentation.** Add a counting cell and a print to a throwaway build; run the 260
viewpoints; report the distribution. **This is the method for every "how many per frame" question in
§2** and none of them have been answered because nobody has run it. Cost: one build.

**M4 — stub diff.** Replace a leaf body with `stl.fret` and diff the sweep. Prices a subsystem
*including* its call overhead, which M2 cannot see. The `ablate` set above is largely this.

**M5 — oracle-side counting.** Count events in Python across the 260 viewpoints. **No build at all.**
Works for anything the oracle mirrors: how many things pass each projection reject, how many things
per leaf, how many leaves carry things. **Always try M5 before M3.**

**M6 — the two-sided gate.** `m14_gate.py` — the correctness instrument, not a cost one. Phase 1
byte-exact ×4 plus cold-vs-warm identical pixels; phase 2 N relayed tics with frame, state and
bindings all checked; and **two-sided vacuity controls** (something must change AND it must reach a
pixel). §11 says why a one-sided control is worthless.

**M7 — knob patch.** `bench.py --knob NAME=VALUE` patches a constant in **both** mirrors and folds
the knobs into the binary cache key. The instrument for pricing a fidelity option before proposing
it.

## 4. The arithmetic of the band

Both inputs are measured (§1.1), so this is arithmetic rather than estimate:

| | |
|---|---|
| today | 36.68M |
| the base renderer, pre-M14 | 22.94M |
| M14's cost | +13.7M |

* **To reach 25M** (top of the band): M14's overhead must fall from 13.7M to **≤2.06M** — an ~85%
  reduction. The base renderer is then untouched, and the graphics are unchanged by construction.
* **To reach 20M** (bottom of the band): M14's overhead to ~0 **and** ~3M out of the base renderer as
  well.

**So the band is well chosen: its top is reachable by removing M14 waste alone, and its bottom
requires touching the base renderer.** Work the top first; it needs no picture compromise at all.

Whether 25M is actually reachable depends entirely on the §2 unknowns — that is not a hedge, it is
the reason §3 exists.

## 5. Phase 1 — candidate levers against M14's +13.7M

**Each is a HYPOTHESIS with a method, and deliberately carries no saving figure.** Price with the
named method, then decide.

### 5a. The per-leaf head check at a baked address
`s` is a compile-time constant at each leaf's call site, so `sshead + s*2*dw` is a compile-time
ADDRESS. The leaf can test its own list head with no pointer math and no `fcall`:
```
hex.if0 2, sshead + {s}*2*dw, ss{cid}_nothings     // 0 = empty (see §7)
hex.set w/4, cur_ss, {s}
hex.set 4, ss_flr, {floor}
hex.set 4, ss_ltb, {ltbase}
stl.fcall thing_pass_leaf, tp_ret
ss{cid}_nothings:
```
**Price it with M5 then M4**: M5 counts how many visited leaves are empty (if few are, the lever is
worthless); M4 stubs `thing_pass_leaf` to bound the whole subsystem.
⚠ `subsector_action` is shared with the static path — keep this strictly inside the `moving_things`
branch and run `cr/emit_hash_vs_head.py` after it.

### 5b. The leaf lists round-trip, as the bindings already do
A frame with nothing moving would then do no binding work; a moved thing costs one unlink + one
sorted insert — DOOM's `P_UnsetThingPosition`/`P_SetThingPosition`.
**Price it with M4** (stub `bind_things` to bound what it can possibly save) **then M1**.
⚠ **THE INSERT MUST BE SORTED, NOT A PREPEND.** Lists are built descending so traversal is ascending,
and ascending order is what makes a static thing claim the same front-to-back sprite slot. A prepend
reorders sprites and moves pixels. ⚠ Wire cost is real and must be counted against the saving; the
cold frame gets worse — report `--cold` alongside.

### 5c. `thing_load` becomes lazy
Load position first, let `frame.thing_record_body`'s existing rejects fire, load the rest only for
survivors. The per-call split is measured (§1.2); **what is not measured is the survivor rate, and
the lever is worth exactly that rate.**
**Price it with M5 first** — count, on the oracle across the 260 viewpoints, how many things reach
each reject. If most survive, **this lever does not exist**; say so and move on.
⚠ **IT CAN MOVE PIXELS THROUGH THE BUDGETS.** `thing_record_body` does not only reject, it *spends*:
`n_thing`/`n_mon` against their budgets, `degfl` graduated acceptance, `n_hd`, and the monotone
`tstop` — all consumed **in visit order**. Any split must be **reject-before-spend, in the same
order**. The crowded gate viewpoint (664, 291, 0x18000000) is what catches a mistake.

### 5d. §4b's precision cost
`proj.wall_x_range_m` runs at full 16.16 because the old narrowing read the view position's integer
map slice — bit-identical only while `viewx = m<<16`, which the sim violates from the player's second
step. **The fix is correct; do not re-litigate it.** Open question is whether the full-precision form
can be cheaper — the row rule says cost ∝ nonzero nibbles of the *second* operand, so operand order
and width are worth an audit.
**Price it with M1**: one build with the map-slice form restored, swept. ⚠ **Measurement only, never
committed** — it is byte-exact at integer view positions only.

## 6. Phase 2 — the base renderer, only if the band's bottom is wanted

Needed only for 20M, not for 25M (§4). **It has no plan, and it should not get one until §2's base
decomposition exists.** First task: re-derive where 22.94M goes *today* with M1 — things off, stack
off, steps off, planes off, one sweep each. The repo's older decomposition predates several
correctness fixes and should not be trusted as current.

## 7. The picture: what is permitted, and how to propose the rest

The owner's position, in their words: **graphics stay as they are; some sprites may be removed; other
graphics compromises may be *suggested*.**

**Permitted now — removing some sprites.** The honest ways, in increasing visible cost:
1. **Drop decor classes** that carry no gameplay meaning, by thing type, at emit time. This is a data
   change in `thing_rows` + the oracle's `_drawable` filter — **both mirrors, one commit**, or the
   gate fails immediately (which is the safety net working).
2. **A per-frame count budget**, lowering `THING_BUDGET`/`MONSTER_BUDGET`. ⚠ CLAUDE.md's cost model
   is explicit that **a budget that binds paints wrong pixels** — surviving budgets are either
   provably never-binding or shed only invisible work. A binding count budget is a *visible* change
   and must be treated as one, not slipped in as an optimisation.
3. **Distance/size gates** (the `DEG_*` family). These already exist and are already tuned; the owner
   has previously declined harsher settings.

**Method for any of them: price with M7/M1 first, then bring the owner the picture.** Render the same
viewpoint before and after (`scratchpad/opt_sheet.py` and the `*_sheet.png` precedents) so the
decision is made on an image, not on a description.

**To suggest — not apply.** Anything else that trades picture goes to the owner as a priced option
with its visible consequence named, and stays unapplied until answered.

## 8. Acceptance criteria

1. `m14_sweep.py … --things` median **within 20–25M** on the stock map, reported with min / mean /
   p90 / worst and the share under 25M.
2. `m14_gate.py 10 --things` **PASS** — byte-exact ×4, cold-vs-warm identical pixels, 10/10 relayed
   tics, **both** vacuity controls non-zero.
3. `m14_gate.py 10 --things --collide` **PASS** — never gated once during this work (§12.3).
4. `pytest tests/host -q --deselect …test_build_wall_renderer_e1m1_flat` → 242 passed.
5. `cr/emit_hash_vs_head.py` → 14/14 parts identical, unless a lever deliberately changes the shipped
   path, in which case re-certify instead.
6. `--cold` sweep reported, so level-load cost is visible.
7. Any sprite removal or picture change named explicitly in the commit **and** shown as a
   before/after image.
8. ⚠ **The tail reported alongside the median.** Worst is 71.67M today and no lever above targets it.
   A median inside the band can still coexist with large spikes; that is the owner's call, made on
   the number, not hidden.

## 9. The instruments (reference)

| tool | cost | what it answers |
|---|---|---|
| `scratchpad/m14_sweep.py <fjm> --things [--cold] [--csv f]` | ~5 min | **THE TARGET METRIC.** 260-frame median on the binary wire. `--cold` feeds all-dirty bindings (a cold start) instead of the steady state. |
| `scratchpad/m14_gate.py 10 --things [--collide]` | ~25 min build + ~10 min | **THE PROOF.** phase 1 byte-exact ×4 + cold-vs-warm identical pixels; phase 2 N relayed tics, frame AND state AND bindings vs the oracle; two-sided vacuity controls. |
| `scratchpad/cr/emit_hash_vs_head.py [--selftest]` | ~15 min | the shipped path is unchanged (14/14 parts hash-identical, certified + shipped configs) |
| `scratchpad/_bind.py` | ~3 min | `bind_things` COLD vs WARM: identical lists, and the cache is actually taken |
| `scratchpad/_tpass.py` | ~2 min | every leaf visits exactly its things, in ascending order |
| `scratchpad/m14_thload_split.py` | ~5 min | where `thing_load`'s ops go, by ablation, with a linearity control and a sum check |
| `scratchpad/m14_thload_cost.py` | ~3 min | `thing_load` per-call cost, k-sweep |
| `scratchpad/_ptrunit.py` / `_ptrunit2.py` | seconds | the pointer/accessor semantics in §4 |
| `pytest tests/host -q --deselect …e1m1_flat` | 93s | 242 host tests |

⚠ **ONE HEAVY BUILD AT A TIME** (CLAUDE.md rule 1). Two concurrent E1M1 builds die silently — exit
255, empty output, no error. The `--things` build is ~18.6MB and takes ~25 minutes; it is cached at
`scratchpad/fjmcache/m14_bin[_coll][_things].fjm` and the gate reuses it unless you pass `--rebuild`.
**The cache key must name every flag that changes the binary** — that was a real bug.

## 10. ⚠ fj traps this campaign paid for — read before writing pointer or `rep` code

Every one of these cost at least one wasted build or probe cycle.

1. **`hex.input` does NOT fill an array that `ptr_index` + `read_byte` addresses.** The wire writes a
   hex.vec (nibble per slot); read_byte addresses something else. `scratchpad/_ptrunit.py` shows a
   write_byte/read_byte array round-tripping while a wire-filled one reads back garbage. The
   accessor that works — and the only one proven on a wire-filled array — is in `_ptrunit2.py`:
   **nibble offset = index × 16 via `shl_hex 1`, then `read_hex` / `write_hex`.** This is the same
   trap the POSITION array hit; it is now four instances.
2. **`hex.write_hex 4, ptr, src` DOES round-trip.** This corrects the older `fj-lessons` note that
   the 3-arg overload writes a single nibble — verified in `_ptrunit2.py`.
3. **`rep(n, i)` with `n` a macro PARAMETER silently expands to NOTHING.** `rep` needs a literal.
   The tell is the assembled binary getting SMALLER after you add unrolled work.
4. **`rep(c, i) ;label` is a syntax error.** There is no compile-time `if` built that way.
5. **Running pointers KILL THE PROGRAM** — `hex.add w/4, ptr, k` per iteration then `read_byte`
   through it. Reproduced in `_ptrunit.py`.
6. **`ptr + n*dw` offsets the POINTER CELL's own address**, not the address it points to. It cannot
   reach a field inside a pointed-to record.
7. **UNROLLING IS A TRAP AT THIS SCALE.** 251 inlined copies of a ~25-line macro, or 682 unrolled
   `hex.set`s, or 682 baked `hex.vec` lines, each took a probe from seconds to **30–40+ minutes** to
   assemble. The assembler is ~cubic in unrolled ops; heavy code belongs in a shared `stl.fcall`
   leaf. **This killed two otherwise-correct optimisations.**
8. **`read_table_packed`'s cost barely depends on the index width** — 69,503 ops at the emitter's
   real widths vs 68,571 at a hard-coded 4. Do not optimise the width; do reduce the number of reads.
9. **Anything handed to a `w/4`-wide `mov` must itself be `w/4`.** `ptr_index` does `mov w/4` out of
   its index. Three defects of this one family in M14-e alone.

## 11. ⚠ Method traps — these cost more than the fj ones

1. **A STALE BASELINE IS NOT A CONTROL.** `cr/emit_hash.py` compares against a *stored* hash; after
   a run of milestones it reports DIFF for every config regardless of the change under review, so it
   reads as evidence and is noise. Use **`cr/emit_hash_vs_head.py`**, which self-baselines (emits
   the certified AND shipped config twice in one process, worktree vs HEAD) and ships an R9
   `--selftest`. It caught a real defect the day it was written: an unconditional `""` appended to a
   parts list still costs a newline.
2. **VACUITY CONTROLS MUST BE TWO-SIDED.** The M14-e gate counts BOTH leaf re-bindings AND tics whose
   pixels changed. Counting bindings alone passed a mover set (`i % 8 == 0`) whose 31 things were all
   off-screen — 22 leaf changes, 0 frames changed. Movers are now the 30 things nearest spawn.
3. **`python -m pytest tests/host -q` IS NOT the ~1-minute run the ladder claims.** Nothing deselects
   `test_build_wall_renderer_e1m1_flat`, so a bare run sits on a ~70-minute build at test 45 and
   looks exactly like a hang. Use:
   `--deselect tests/host/test_e1m1_integration.py::test_build_wall_renderer_e1m1_flat` → **242
   passed in 93s**. (This is written down in the `m14-handoff` memory too, and I still lost 40
   minutes to it.)
4. **A probe must use the EMITTER's real parameters.** The first `thing_load` breakdown hard-coded a
   4-nibble index width where the emitter passes 2 and 3 — it was measuring a program nobody builds.
   It happened not to matter; next time it will.

## 12. ⚠ The debts and the gaps

**12.1 THE CR.** 36 commits unreviewed since `54da396` (2026-08-12) — all of M14 plus this campaign.
Deferred on the owner's instruction, not forgotten, and this campaign will add to it. M14 is well
*gated*, which is not the same as reviewed: gates prove the mirrors agree, CR catches what a passing
gate is happy to ship.

**12.2 Every number here is the STOCK map.** §1.4. If the deliverable is what `walk_e1m1.py` runs,
they must all be re-measured on lite. The structure of this plan survives that; the figures do not.

**12.3 `--collide` has never been gated in this campaign.** Every candidate lever touches
`bind_things`, `thing_pass` or `subsector_action`, and collision rides the same binary through
`player_sim`. `m14_bin_coll.fjm` does not currently exist, and **`m14_bin.fjm` is STALE** — built
04:20, the §4b fix landed 04:49. Delete it rather than baseline against it.

**12.4 No lever targets the TAIL.** Worst is 71.67M (measured). §8.8.

**12.5 The oracle must not be edited to make a lever work.** It defines byte-exactness. The one
legitimate both-mirrors change on the table is a deliberate picture decision (§7), made in one
commit, with the gate as the check that they moved together.

**12.6 Nothing here re-blesses the certified artefacts.** `deg_gate.py`'s header still carries
pre-M14-a op counts and no certified binary hash has been published since `b_272d37507ca58434`.
Part of closing the campaign, not part of any lever.

**12.7 fps has never been measured in this campaign.** Ops/frame is a proxy chosen because it diffs
deterministically. If frame rate is what actually matters, measure it before declaring anything.
