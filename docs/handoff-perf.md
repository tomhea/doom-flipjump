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

## 0. ⚠ THE EVIDENCE RULE — the gate on all work below

**Owner directive, verbatim (2026-08-14):**

> Before proposing any optimization, produce a measured cost breakdown: run the profiler, print the
> raw output, and attribute ops/frame to each subsystem with the arithmetic shown. Mark every number
> as MEASURED (with the command) or ESTIMATED (with the assumption). **I will reject any plan built
> on ESTIMATED numbers.**

What this means in practice, and it is not negotiable:

1. **No optimisation is proposed before its subsystem has a measured breakdown.** Not "probably the
   biggest", not "should be around" — a profile, printed.
2. **Print the RAW output**, not a summary of it. The owner reads the tool's own words.
3. **Show the arithmetic.** If a subsystem's cost is derived from other numbers, write the sum out so
   the derivation can be checked. A residual is not an attribution (§2).
4. **Tag every figure.** `MEASURED (python scratchpad/… , 2026-08-14)` or
   `ESTIMATED (assumes …)`. A number with no tag is a defect in the report.
5. **A plan resting on an ESTIMATED number will be rejected**, so do not build one. Convert the
   estimate to a measurement first (§3), or state plainly that the lever cannot yet be justified.

⚠ **This document already complies**: §1 is the measured ledger with provenance, §2 is the explicit
list of what is NOT measured, and §5's levers deliberately carry **no saving figures at all** — they
are hypotheses awaiting §0's breakdown. Earlier drafts violated the rule and are the reason it
exists: they carried a per-lever saving table, a "~117 things/frame" that was a residual divided by
the cost it was used to corroborate, and an extrapolated §4b figure.


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
| ~~certified, pre-M14 (`sweep_crfix2.csv`)~~ | ~~22.94M~~ | ~~22.58M~~ | — | ~~48.46M~~ | — |
| **THE BASELINE (`sweep_base_today.csv`)** — today's source, `deg_gate`'s config, no M14 wire | **28.19M** | 28.72M | — | 53.70M | 6.30M |
| M14-e as first shipped | 60.29M | 62.01M | 82.52M | 97.01M | 32.25M |
| + binding round-trip (`1202393`) | 38.48M | 40.21M | 60.36M | 74.78M | 11.54M |
| + clear & per-leaf reads deleted (`f54300e`) | **36.68M** | 38.17M | 58.08M | 71.67M | 9.67M |

⚠ **THE `sweep_crfix2.csv` ROW IS STRUCK OUT, AND WITH IT THE OLD "+13.7M".** Its binary
(`b_272d37507ca58434.fjm`) **is not byte-exact against today's oracle**: 1091 / 844 / 3256 / 5300 of
16000 pixels at the four gate viewpoints, while today's M14 binary is byte-exact at all four.
MEASURED (`python scratchpad/m14_vp_ops.py --m14 … --dec … --oracle`, 2026-08-14). A baseline that
draws a different picture prices the feature *plus* the picture change with no way to separate them.
`scratchpad/m14_baseline_id.py` ruled out sky, `bbox_cull`, `degrade` and the lite map as the cause;
the binary also fails to match the deg_gate op counts `fda6de4` recorded for its own era.

**THE REPLACEMENT** is `scratchpad/m14_basegate.py`: `deg_gate.py`'s emit call verbatim (i.e.
`m14_gate.py`'s minus `state_wire="bin"`, `player_sim`, `moving_things`), built from today's source,
and it **refuses to emit a number unless the binary is byte-exact against today's oracle** at all
four viewpoints. It passes. So both sides of the subtraction below draw the same frame.

**M14 costs +8.49M at the median, measured against a baseline with identical pixels.**

| viewpoint | M14 | baseline (same picture) | Δ = M14 alone |
|---|---|---|---|
| (664,291,0x18000000) | 68,195,203 | 51,688,913 | +16,506,290 |
| (1272,−724,0x40000000) | 57,299,613 | 41,978,565 | +15,321,048 |
| (1869,479,0x80000000) | 64,492,369 | 48,915,900 | +15,576,469 |
| spawn (−416,256,0x0) | 55,757,155 | 39,594,303 | +16,162,852 |

Per frame across the whole grid (`python scratchpad/m14_delta_join.py`, the two CSVs joined on
(x,y,angle); all 260 keys match, so it is like-for-like):

| | min | MEDIAN | mean | max |
|---|---|---|---|---|
| baseline | 6,301,043 | 28,193,396 | 28,722,064 | 53,703,412 |
| M14 | 9,669,185 | 36,683,119 | 38,173,813 | 71,674,642 |
| **per-frame Δ** | 3,255,052 | **8,376,784** | 9,451,749 | 21,141,717 |

(The difference of the two medians is 8,489,723; the median of the per-frame differences is
8,376,784. Different statistics of the same data — both are given rather than one being passed off
as the other.)

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

### 1.2b THE PROFILE — §0's breakdown, and it reconciles with §1.1

`python scratchpad/opprof.py --m14 [--vp X,Y,ANG]`, 2026-08-14. The `--m14` mode emits
`m14_gate.py --things`'s kwargs verbatim and feeds `m14_sweep.py`'s wire (state + 251 spawn
positions + WARM bindings, keys=0). **Its control**: it sha256-compares its own binary against
`m14_bin_things.fjm` and prints the verdict — `IDENTICAL -- profiling the measured binary`. A
profile of a lookalike would be worthless, so the tool says which it has.

The roll-up table is the only one that sums to the frame (direct ops **plus** the wflip-area blame,
which is ~74% of every frame). Both totals below equal the native runner's op count for the same
feed, to the op.

| | spawn (−416,256,0x0) | crowded (664,291,0x18000000) |
|---|---|---|
| **frame total** | **55,757,155** | **68,195,203** |
| `<base renderer — not M14>` | 40,461,019 (72.57%) | 53,369,133 (78.26%) |
| `sim.thing_pass` | 12,001,248 (21.52%) | 11,531,182 (16.91%) |
| `sim.bind_things` | 3,294,888 (5.91%) | 3,294,888 (4.83%) |
| … of which `sim.thing_load` | 9,654,291 | 9,284,652 |
| … `sim.thing_pass`'s own | 2,092,711 | 2,001,952 |
| … `sim.fix16` | 254,246 | 244,578 |

**`sim.bind_things` is 3,294,888 at BOTH viewpoints, to the op** — it is a pure frame-constant, as
its shape predicts (251 things, warm, the same walk every frame).

**THE RECONCILIATION**, and it is three-way. Fit the 260 per-frame deltas of §1.1 against the M5
counts of §1.5 (`delta = a + b·calls`): **a = 3,490,161, b = 69,991, R² = 0.991**, residual sd
408,602. Against the profile:

| | 260-frame A/B regression | profile of one frame | agreement |
|---|---|---|---|
| frame-constant | a = 3,490,161 | `sim.bind_things` 3,294,888 | 5.9% |
| per `thing_load` call | b = 69,991 | `sim.thing_pass` 12,001,248 ÷ 183 = 65,581 | 6.7% |
| `thing_load` alone | — | 9,654,291 ÷ 183 = 52,755 vs §1.2's k-sweep 45,934 | 14.8% |

Two unrelated instruments — a 260-frame binary A/B and a per-macro runtime profile — agree on both
coefficients within 7%. ⚠ **R² was 0.774 against the OLD baseline and 0.991 against this one**: the
old baseline's scatter *was* the picture difference.

⚠ **THE ONE ATTRIBUTION LIMIT, stated rather than hidden.** Ops executed inside a shared
`stl.fcall` leaf carry that leaf's label, not its caller's, so `frame.thing_record_body` (3,127,430
at spawn) sits under "base renderer" although `sim.thing_pass` drives it. It is not M14-*added* —
the pre-M14 baked path called the same leaf equally often, and the baseline binary pays it too — but
the `sim.*` column is therefore a LOWER bound. The measured A/B delta (16,162,852 at spawn) exceeds
the profiled `sim.*` total (15,296,136) by 866,716 = 5.4%; at the crowded viewpoint the gap is
1,680,220 = 10.2%. **That remainder is unattributed, and naming it here as "the wire" would be
exactly the residual-as-attribution §0.3 forbids.**

### 1.2c THE BASE RENDERER — the decomposition §6 said it needed

Same profile, the base-renderer 40,461,019 at spawn, direct + wflip blame:

| macro | ops | share of frame |
|---|---|---|
| `frame.seg_pass1_leaf_body_lines` | 13,029,418 | 23.4% |
| `frame.seg_pass2_leaf_body_lines` | 10,475,621 | 18.8% |
| `frame.seg_pass1_leaf_body_ts` | 6,108,694 | 11.0% |
| `frame.thing_record_body` | 3,127,430 | 5.6% |
| `proj.point_on_side_leaf` | 3,056,362 | 5.5% |
| `stl.startup_and_init_all` | 1,956,573 | 3.5% |
| **sum** | **37,754,098** | **93.3% of the base renderer** |

Inside the biggest one, `proj.wall_x_range_m` is 2,411,018 direct ops — §5d's subject.

⚠ **THIS IS ONE HEAVY FRAME (55.76M against a 36.68M median), so read the SHARES, not the
absolutes, and price anything load-bearing with M1 at the median.**

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

### 1.5 THE PER-FRAME COUNTS — M5, oracle-side, no build

`python scratchpad/m14_m5_counts.py --csv scratchpad/m5_counts.csv`, 2026-08-14. The sweep's own 260
frames, rendered through `ReferenceModel.render_wall_frame` itself with wrappers around
`project_thing`/`sprite_art` installed from the probe — no oracle file edited (§12.5).

```
subsectors 682 | with segs 682 | carrying >=1 thing 132 | EMPTY of things 550 (80.6%)

leaves entered before `full`  LOW bound  min 0  MEDIAN 215  max 680   (of 682 in the walk order)
                              HIGH bound min 1  MEDIAN 222  max 681
thing_load calls/frame                   min 0  MEDIAN  71  mean 85   max 249
accepted sprites/frame                   min 0  MEDIAN   6  mean  5   max  10

arrived 44,234 -> claim-stopped 22,088 (49.9%) -> LOADED 22,146 -> ACCEPTED 1,314 = 5.9% of loaded
```

`full` is monotone, so the leaves entered before it latches are a PREFIX of the walk order — which
is what makes the leaf count exact (bracketed) rather than modelled.

⚠ **A CORRECTION TO §5c AND §7.2.** `THING_BUDGET` and `MONSTER_BUDGET` are both **255** against 251
drawable things, so **neither can ever bind on this map**. The first cut in the ladder is the `full`
claim-stop, not a budget. §5c's "reject-before-spend, in the same order" warning still holds for
`degfl` graduated acceptance and the monotone `tstop`, but not for the count budgets; and §7.2's
"lower `THING_BUDGET`" is a *visible* change from 255 with nothing free before it.

## 2. ⚠ What is NOT measured

Everything this section used to list has been measured (§1.1–§1.5). What remains open:

* **How `sim.thing_pass`'s own 2,092,711 ops split** between the per-leaf preamble and the per-thing
  loop step. A two-predictor fit (`delta = a + b·calls + c·leaves`) returns c = 330 ops/leaf but
  does **not** improve R² (0.991 either way) or the residual (408,369 vs 408,602), so `c` is not
  identified — `leaves` and `calls` are collinear across the grid. What IS bounded: the whole of
  `thing_pass`'s own cost is 2.09M, and only the empty-leaf share of it is reachable. An M2 k-sweep
  of `thing_pass` with an empty vs a populated list would settle it in minutes.
* **The 5.4%–10.2% remainder** between the A/B delta and the profiled `sim.*` total (§1.2b). It is
  named as a remainder, not attributed.
* **§4b's full-precision `wall_x_range_m` cost at the median.** The "+9–10%" came from four gate
  viewpoints at a different milestone. The profile gives 2,411,018 direct ops at ONE heavy frame.
* **`bind_things`' cost inside a real frame** — now measured at 3,294,888 (§1.2b), so the old
  5,197,749 figure (which included the probe's own dump loop) is superseded.
* **What broke the picture between `b_272d37507ca58434` and today** (§12.8). It does not block this
  campaign — the new baseline sidesteps it — but it is unexplained.

## 3. THE METHODS — how to turn §2 into evidence

These are the eight instruments this repo has, M0 first because §0 names it. Each entry says what it can price and what it costs.

**M0 — THE PROFILER. The instrument §0 names, and the one to run first.**
`scratchpad/opprof.py` attributes ops **directly** to the macro that burned them: it assembles with
`debugging_file_path`, runs the interpreter's featured loop with `profile=True` (monkeypatching
`register_op_address` into a histogram), maps each executed address to the nearest label at or below
it, and aggregates by macro path. Output is a BY-OUTERMOST-MACRO table and a BY-DEPTH-2 table —
exactly the "attribute ops/frame to each subsystem" the rule asks for.

```bash
python scratchpad/opprof.py --wad tests/fixtures/freedoom_e1m1.wad --map E1M1 --vp X,Y,ANG
```

⚠ **THREE THINGS BEFORE TRUSTING IT.**
* **It cannot drive an M14 binary yet.** It emits with the default `state_wire="dec"` and feeds
  `f"{vx}
{vy}
{va}
"` on stdin (line ~110). It needs the same change `m14_sweep.py` got: bin
  wire, `player_sim`, `moving_things`, and the position + binding blocks appended. **That extension
  is task one of this campaign**, because §0 depends on it.
* **The featured loop is pure Python, ~200× slower than the native engine.** A previously saved E1M1
  profile (`scratchpad/prof_tree_full.txt`) took 111s for 36.4M ops — feasible, but profile ONE
  viewpoint, not the 260-frame sweep.
* **~72% of ops land in wflip AREAS and are blamed on their CALLER** (that saved run: "wflip-area
  ops: 26,074,620 (71.6%)"). That is the tool's attribution model, and it is the right one — the
  flips are where work physically happens, the caller is who asked — but it means the tables are
  *caller* attribution, so read them as "this macro caused N ops", not "these ops are inside it".

**M0 prices ONE VIEWPOINT by subsystem. M1 prices ONE SUBSYSTEM at the median.** They answer
different questions and a complete case usually needs both: M0 to find where the ops are, M1 to
confirm the saving on the metric the target is stated in.

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

## 4. The arithmetic of the band — ⚠ THE CONCLUSION HAS FLIPPED

Both inputs are measured against a byte-identical picture (§1.1), so this is arithmetic:

| | |
|---|---|
| today (`m14_bin_things`) | 36,683,119 |
| **the base renderer TODAY, same picture** | **28,193,396** |
| M14's cost | **+8,489,723** |

* **To reach 25M** (top of the band): remove **11,683,119**.
* **M14's ENTIRE cost is 8,489,723.** Deleting M14 outright — no wire, no runtime things, a feature
  the milestone exists to provide — lands at **28,193,396, still 3,193,396 ABOVE the band's top.**
* **To reach 20M** (bottom): remove 16,683,119 — all of M14 plus ~8.2M of base renderer.

> ⚠ **The previous draft's central claim — "its top is reachable by removing M14 waste alone" — is
> FALSE, and measured to be false.** It followed from the 22.94M baseline, which was a different
> picture (§1.1). The true base renderer is 28.19M, which is 3.19M over the band's top *by itself*.

**So every route into the band goes through the base renderer**, and §6 stops being optional. The
realistic M14 recovery is bounded by §5: ~3.29M frame-constant (5b) + ~2.0M (5c) ≈ 5.3M, landing
around **31.4M** — 6.4M short. That is not a reason to skip §5; those are the cheapest ops in the
program to remove and they are pure waste. It is a reason not to promise the band from them.

**The largest single item in the base renderer is now identified and measured**: M14-c's
full-precision `proj.wall_x_range_m`, **+5.47M..+6.02M (+13.2%..+16.0%)** at the four gate
viewpoints (§5d, §12.8). It is a correctness fix and is not up for reversal. ⚠ **Its obvious
recovery — a conditional narrow path for integer view positions — is a BENCHMARK ARTEFACT that
would fire on 260 of 260 swept frames and ~0 played ones (§5e). Do not take it without reading
§5e.** The legitimate version is to make the full-precision form itself cheaper.

⚠ **THIS IS AN OWNER DECISION, not an engineering one.** §7 permits removing some sprites and
permits *suggesting* other picture trades. The band as stated now requires either base-renderer work
with no picture cost (only one candidate identified, and it is not free), or a picture trade. Both
belong to the owner.

## 5. Phase 1 — the levers against M14's +8.49M, NOW WITH NUMBERS

§0's breakdown exists (§1.2b), so these are proposals rather than notes. Each carries its measured
ceiling and says which part of that ceiling is actually reachable.

**Ranked by measured ceiling:**

| lever | what it targets | MEASURED ceiling | reachable |
|---|---|---|---|
| 5b lists round-trip | the frame-constant `a` | **3,294,888/frame** (bind_things, identical at both viewpoints) | most of it, minus new wire cost |
| 5c lazy `thing_load` | the per-call `b` | **4.91M/frame at the median** (69,130 × 71) | ~2.0M — see 5c |
| 5a baked head check | `thing_pass`'s own | **≤2.09M/frame**, and the leaf-proportional part is not even identifiable | **not the lever — drop it** |
| 5d `wall_x_range_m` | base renderer | 2,411,018 direct ops at one heavy frame | unknown; Phase 2 |

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
⚠ **PRICED AND REJECTED (2026-08-14).** M5 says 550 of 682 leaves (80.6%) are empty and the median
frame enters 215–222 leaves before `full` latches — so the lever's *count* is real. Its *unit cost*
is not: `sim.thing_pass`'s own ops (everything except `thing_load`/`fix16`) are **2,092,711** at
spawn and **2,001,952** at the crowded viewpoint, and that is the whole preamble-plus-loop-step
budget. Adding `leaves` to the 260-frame regression moves neither R² (0.991) nor the residual
(408,369 vs 408,602), so the leaf-proportional component cannot even be separated from the per-thing
one. **Against the 11.68M the band needs, a ≤2.09M ceiling whose reachable fraction is unmeasurable
is not worth a build.** Reopen only if an M2 k-sweep of `thing_pass` shows the preamble dominating.

### 5b. The leaf lists round-trip, as the bindings already do
A frame with nothing moving would then do no binding work; a moved thing costs one unlink + one
sorted insert — DOOM's `P_UnsetThingPosition`/`P_SetThingPosition`.
**PRICED — this is the strongest lever. MEASURED ceiling 3,294,888 ops/frame**, the profiled
`sim.bind_things`, which came out **bit-identical at both profiled viewpoints** and is corroborated
by the regression's frame-constant a = 3,490,161 (§1.2b). At the median frame that is **39% of
M14's whole 8.49M**. The warm cache already skips *point location*; what remains is the list
REBUILD — 251 things walked and re-inserted every frame, whether or not anything moved.
⚠ The saving is bounded below by the new wire cost (the lists must round-trip), which is why the
ceiling is not the estimate. Price the residue with M1 after building.
⚠ **THE INSERT MUST BE SORTED, NOT A PREPEND.** Lists are built descending so traversal is ascending,
and ascending order is what makes a static thing claim the same front-to-back sprite slot. A prepend
reorders sprites and moves pixels. ⚠ Wire cost is real and must be counted against the saving; the
cold frame gets worse — report `--cold` alongside.

### 5c. `thing_load` becomes lazy
Load position first, let `frame.thing_record_body`'s existing rejects fire, load the rest only for
survivors.

**PRICED, and the survivor rate is now measured: 5.9%.** Of 22,146 things loaded across the 260
frames, **20,832 (94.1%) are rejected after being loaded** (§1.5). The per-call cost is
69,130 (regression) / 65,581 (profile ÷ calls), of which §1.2's k-sweep attributes **29,938 to the
22-byte row read and its 13 field extractions** and 16,995 to the position accessor — and the
position is the only part the reject needs.

**DERIVED saving at the median frame** (three MEASURED inputs, so tagged DERIVED, not measured):
`29,938 ops × 94.1% rejected × 71 calls = 2,000,148 ops/frame` ≈ **2.0M**. Confirm with M1 after
building; do not quote it as measured before that.
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

**MEASURED SIZE (2026-08-14): the fix cost +5.47M..+6.02M, i.e. +13.2%..+16.0%**, per `110cfd6`'s
own evidence, and `m14_basegate.py` reproduces its post-fix column to the digit (§12.8). That makes
it **the largest single identified item in the base renderer** — bigger than every M14 lever
combined.

### 5e. ⚠ THE CONDITIONAL NARROW PATH — and why it is a BENCHMARK ARTEFACT, not a lever

`110cfd6` names the obvious recovery itself: *"the map-slice path is still valid whenever the
position's low nibbles are zero, so a per-frame test could pick the narrow path for integer
positions"*. It would be correct, byte-exact, and picture-neutral.

⚠ **AND IT WOULD BUY ALMOST NOTHING IN PLAY, WHILE LOOKING LIKE A ~5.5M WIN ON THIS DOCUMENT'S
TARGET METRIC.** Every sweep here feeds `encode_feed_mapunits`, i.e. `viewx = vx << 16` — **integer
positions, so the narrow path would fire on 260 of 260 frames.** The player sim moves in 16.16 and
is at an exact integer essentially never, which is the whole reason M14-c had to widen the macro.
So the conditional would fire on ~100% of benchmark frames and ~0% of real ones.

**Anyone proposing it must report the sweep median AND a fractional-position sweep**, or they are
reporting a number that exists only because the harness stands on whole map units. The honest
version of this lever is to make the FULL-precision form cheaper (the row rule: cost ∝ nonzero
nibbles of the *second* operand, so operand order and width are worth an audit) — that helps every
frame, benchmark and played alike.

⚠ **THIS GENERALISES BEYOND 5e**: the 260-frame sweep is an integer-position metric, and M14 made
the program fractional. Before the campaign closes, the target metric itself should be re-examined
(§12.10).

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

## 7b. The work order

1. ~~Extend `opprof.py` to the M14 binary~~ **DONE** — `--m14`, with a sha256 control against
   `m14_bin_things.fjm` (`IDENTICAL -- profiling the measured binary`).
2. ~~Profile spawn + one crowded viewpoint~~ **DONE** — §1.2b. Both totals equal the native
   runner's op count to the op.
3. ~~Attribute M14's cost, reconciled~~ **DONE** — §1.2b, three-way, within 7%. ⚠ It reconciled
   only after §1.1's baseline was replaced; against the old one the fit was R² 0.774.
4. ~~Answer §2's open counts with M5~~ **DONE** — §1.5.
5. ~~Propose levers with measured numbers~~ **DONE** — §5. 5a priced and **rejected**; 5b and 5c
   carry ceilings.
6. **← YOU ARE HERE, AND IT NEEDS THE OWNER FIRST.** §4's conclusion flipped: the band is not
   reachable by removing M14 alone, because the base renderer alone is 28.19M against a 25M ceiling.
   5b + 5c are still worth building (≈5.3M of pure waste), but they land at ~31.4M, not in the band.
   **The owner chooses**: (a) build 5b+5c and accept ~31M; (b) open Phase 2 on the base renderer
   (§1.2c is its decomposition, and it now exists); (c) take a picture trade under §7.
7. Then: build → gate → sweep after **each** lever, one self-contained commit each.

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
| `scratchpad/opprof.py --m14 [--vp X,Y,ANG] [--reuse]` | 68 min build + ~4 min/frame | **§0's PROFILER.** per-macro attribution of one frame; sha256-controls its binary against the swept one. ⚠ ~8GB RSS — run it alone and kill it after. |
| `scratchpad/m14_basegate.py` | ~16 min build | **THE BASELINE.** today's source, `deg_gate`'s config, no M14 wire; refuses to emit a number unless byte-exact vs today's oracle |
| `scratchpad/m14_vp_ops.py --m14 F --dec F [--oracle]` | ~5 min | ops at named viewpoints on two binaries **with a pixel-identity column** — the control §11.5 exists for |
| `scratchpad/m14_m5_counts.py [--csv F]` | ~12 min | M5: leaves entered before `full`, `thing_load` calls, the reject ladder, over the 260-frame grid |
| `scratchpad/m14_delta_join.py [baseline.csv]` | seconds | joins the two sweeps + the M5 counts on (x,y,angle); per-frame deltas and the a/b/c fit |
| `scratchpad/m14_baseline_id.py [fjm]` | ~8 min | which config an archived `b_*` binary is (§12.8) |
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

5. ⚠ **A BASELINE IS NOT A BASELINE UNTIL ITS PIXELS ARE CHECKED. (2026-08-14, and it invalidated
   this document's headline number.)** §1.1 subtracted an archived binary's sweep median from
   today's and called the difference "M14's cost, measured". Both sides were real measurements; the
   *subtraction* was not, because the two binaries draw different frames (up to 5300 of 16000 px).
   The tells were all visible in advance and none was checked: the archived binary came from a
   different tool (`bench.py`, whose flags differ from the gates'), it did not match the deg_gate op
   counts recorded in its own era's commit message, and its per-viewpoint deltas ranged +19M..+38M
   around a claimed +13.7M median. **Any A/B across two builds must carry a pixel-identity column**
   — `m14_vp_ops.py --oracle` is that column, and `m14_basegate.py` refuses to emit a number from a
   binary that is not byte-exact against today's oracle.
   The corroborating tell, worth remembering on its own: **R² 0.774 → 0.991** on the same regression
   when the baseline was fixed. Unexplained scatter in a cost model is often a broken control, not
   noise.

6. **The profiler's own control is cheap and it is not optional.** `opprof.py --m14` sha256-compares
   its binary against the swept one. It cost 3 lines and it is the only reason the profile can be
   quoted against the sweep at all. Note the assemble with `debugging_file_path` is **4073s** (vs
   ~980s without) and produces 24.4M labels / 62MB / ~8GB RSS — profile with nothing else running,
   and kill the process afterwards or the next tool OOMs (it did).

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

**12.8 ~~The base renderer may have grown ~6M during M14-b..e~~ — ANSWERED, and it is not a
regression.** It is **M14-c (`110cfd6`)**, whose own evidence block records the deg_gate cost of
making `proj.wall_x_range_m` full 16.16:

```
(664,291)    45,664,661 -> 51,688,913   +6,024,252  (+13.2%)
(1272,-724)  36,423,780 -> 41,978,565   +5,554,785  (+15.2%)
(1869,479)   43,030,266 -> 48,915,900   +5,885,634  (+13.7%)
(-416,256)   34,119,621 -> 39,594,303   +5,474,682  (+16.0%)
```

⚠ **`m14_basegate.py` reproduces the right-hand column to the digit** — 51,688,913 / 41,978,565 /
48,915,900 / 39,594,303 — from a build that had never seen those numbers. That is an independent
validation of the new baseline, and it retires this item: the ~6M is a **priced correctness fix**,
paid deliberately, not a regression to hunt.

⚠ It does NOT explain `b_272d37507ca58434`'s pixels, which remain unexplained: the closest
configuration is the gate's own (5300 px at spawn), and `m14_baseline_id.py` has now also ruled out
every `wall_mode` × `stack_steps` × `degrade` combination. It is a pre-`54da396` artefact and the
campaign no longer depends on it. **Do not resurrect it as a baseline.**

**12.9 The certified artefacts are stale in a NEW way.** `deg_gate.py` and the `b_*` cache are the
only record of the pre-M14 picture, and §12.8 says that record disagrees with today's oracle. Until
12.8 is answered, treat `scratchpad/fjmcache/b_*.fjm` as **undated artefacts of unknown
configuration**, not as baselines. `scratchpad/fjmcache/base_dec_today.fjm` is the one binary in the
cache whose config and picture are both known and checked.

**12.10 ⚠ THE TARGET METRIC IS AN INTEGER-POSITION METRIC, AND THE PROGRAM IS NO LONGER INTEGER.**
Every sweep in this document feeds `encode_feed_mapunits` (`viewx = vx << 16`). M14's sim moves the
player in 16.16, so **no frame the player actually sees is at a swept position.** M14-c exists
precisely because the renderer was wrong between whole map units, and §5e is a lever that would
score ~5.5M on this metric while doing nothing in play. The median is still the right *shape* of
target — it is deterministic and it diffs — but before the campaign closes, either re-run the sweep
at fractional positions or state plainly that the number is an integer-grid proxy. ⚠ Neither is
done, and until one is, **every median in this document is an integer-grid median.**

**12.7 fps has never been measured in this campaign.** Ops/frame is a proxy chosen because it diffs
deterministically. If frame rate is what actually matters, measure it before declaring anything.
