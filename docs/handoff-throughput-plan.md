# Throughput plan: the angles not yet tried

Written 2026-09-13 after a day that explained the engine's speed gap but did not close it. This
records what is settled, what was measured to be weak, and — the point of the document — the
angles that were never examined.

## What the numbers pin down

```
frame time  =  ops/frame  ÷  ops/s
            =  19,855,016 ÷ ~200,000,000/s  ≈   99 ms  ≈ 10 FPS      (shipped binary, msframe baseline 09-13)
engine ceiling: ~420 M ops/s  (benchmark_loop.fj, 16 KB working set)
```

Per op the interpreter touches memory **twice**: the instruction pair at `ip` (one line — `f` and
`j` are adjacent) and the flip target. Only the first is on the critical path: the next `ip` is
`j`, so each op is one **dependent load**. At the pinned baseline of ~200 M ops/s that load averages ~2.5 ns — between L1 and L2.
Reaching 420 M would need ~1.2 ns, i.e. L1 for essentially every instruction fetch. The touched
set is 16 MB at 4-byte cells. So the realistic optimistic case is not 420M:

| lever | from | to | basis |
|---|---|---|---|
| ops/s | 200 M | ~300 M | hot 90% inside L2 |
| ops/frame | 19.9 M | ~14 M | the 12M target was nearly reached once |
| **frame time** | 99 ms | **~47 ms → ~21 FPS** | both together; neither alone; an UPPER BOUND |

## Measured weak — do not revisit without new evidence

| lever | result | why |
|---|---|---|
| huge pages (real THP, alternated ×3) | +1.9%, noise | hot set is ~683 pages, already TLB-resident |
| pinning to a P-core + HIGH priority | ~3%, NOT SEPARATED | unpinned 102.4 vs pinned 99.3 ms/frame (09-13); the earlier 118→200 M fj/s gap was an unrecorded machine state, not the scheduler |
| relocating hot objects | weak | caches index by address; footprint is in the big objects, not the distance between small ones |
| 4-byte cells | 5–10% on the shipped binary, sustained | shipped anyway: half the memory, gate PASS |
| the latency curve as a predictor | wrong three times | it measures a pure chase; the game has reuse |
| compiler flags | already `/O2 /GL /LTCG` | nothing left on the table |

## 1. Three measurements never made (cost: minutes; they direct everything below)

**1a. Split the trace by access type.** Histogram instruction-stream touches (`ip` fetches) and
flip-target touches SEPARATELY. The dependent chain depends only on the former. If the
instruction stream is a small fraction of the 16 MB, making *it* resident is the lever and the
flip targets can stay scattered — they overlap. `mkprof.py` needs one extra `PROF_HIT` bucket.

**1b. Cost per object, not touches per object.** For every named object: touches, distinct
lines, and touches-per-line. High touches on few lines is cheap (L1); modest touches spread
thinly is expensive. `nameheat.py` + the word dump already hold the inputs. This replaces the
touch-count ranking, which put `cb_bx` (490 lines, L1-resident) at #1 and is therefore the wrong
list to optimise from.

**1c. Jump-distance distribution.** What fraction of ops have `j == ip + 2w` (fall-through)?
Long fall-through runs mean the hardware prefetcher already covers the instruction stream and
that a block-execution fast path (2b) is viable; short runs mean neither.

## 2. Engine: attack the dependency chain (never tried)

**2a. Read `j` before the flip, prefetch the next instruction.** Today `j` is re-read *after* the
flip because the flip may alias it. Read it first, do the flip, re-read only if
`flip_word_address == word_address + 1`, and issue `_mm_prefetch(&flat[j >> ww])` before the
flip's RMW. That lets the next fetch overlap the current store: memory-level parallelism 1 → ~2.
Audit estimate 1.05–1.2×. Cheap. Gate: op counts + pixels, as for the cell change.

**2b. Block execution for fall-through runs** (only if 1c shows them long). Read K consecutive
ops' words in one go, execute their flips, and bail to the slow path if any flip lands inside the
block's own words (self-modification). Amortises the dependent load over K ops. The one idea here
with a ceiling above 2×; medium complexity; correctness lives in the bail-out condition.

## 3. Program: the hot objects, by COST (after 1b), three candidates already visible

**3a. The shared-leaf return trampoline.** `hex.tables.ret` is **4 words and 10.77% of all
touches**; `hex.mul.ret` 7 words, 2.51%. Every leaf call pays a dispatch and a table-driven
return. Inline the N hottest leaves: fewer ops/frame *and* fewer scattered touches. Emitter
change, byte-exact gate. This is the ops/frame lever most likely to also raise ops/s.

**3b. Collision is 28% of all touches** (`cb_bx` 15.28% + `simcollide_skip` 12.94%). The named
runs are `sim.bind_things → hex.sparse_mov/sparse_zero`. Whether that is 28% of *cost* is what
1b answers; if it is, ask why collision is that expensive at all — per-frame work that could be
per-move, or a sparse-mov that could be narrower. Algorithmic, potentially the largest ops/frame
cut available.

**3c. The M1 reset.** `m1_reset` restores 799,272 words per frame (4.31% of touches over a huge
sparse footprint — likely a high miss rate). Two options: restore only cells that changed (a
dirty set), or pack the restore set contiguously. Note this is the ONE case where relocation
does help: the reset walks its set *linearly*, and a packed sequential walk is what the hardware
prefetcher is built for.

## 4. Process: re-sweep the build knobs against ms/frame

Every knob in `build_blocked.py` — `--spread`, `--max-slot-ops`, `--width-buckets`,
`--pool-base`, padding — was tuned against **ops/frame**. Measured on the same engine:

```
blocked25   245,712,309 ops @ 45.3M/s  → 452 ms/frame
b26         356,224,821 ops @ 65.6M/s  → 452 ms/frame      +45% ops, +45% ops/s, same time
menu        1.85× the ops of blocked25  → comparable ms/frame
```

The op-count campaign has been running in place. Eight existing binaries span 164–1140 ms/frame
at similar work, so the knobs matter ~2× and were tuned on the wrong axis. Sweep them against
ms/frame: existing binaries first (free), then 2–3 targeted builds. Cheap relative to everything
else here, and the win may already be sitting in a config that was rejected for its op count.

## Sequencing

1. **1a–1c** — one session, no builds. Everything else is ranked by what they say.
2. **2a** — one session, engine only, gated like the cell change.
3. **4** — existing binaries immediately; then targeted builds as background work.
4. **3a / 3b / 3c** in the order 1b ranks them; **2b** only if 1c justifies it.

Discipline that today proved necessary: no single-sample numbers; alternate A,B,A,B; read the
cell width / page state back from the object, never infer it from the env var; and check that no
stray process of your own is pegging a core before trusting any measurement.

## 5. Ten more angles, each a different mechanism from the above

Ranked roughly by expected value ÷ cost.

1. **Turn the data dependency into a control dependency.** `ip = j` makes the next fetch wait on
   the load's VALUE. If most ops fall through, write `if (j == ip+2w) ip += 2w; else ip = j;`:
   the branch predictor speculates fall-through, computes `ip+2w` with no dependency on `j`, and
   issues the next fetch immediately; `j` arriving merely confirms. Mispredict ~15 cycles; a
   correct prediction hides the whole load. Potential 1.5–2× on the chain, three lines of C.
   ⚠ The compiler will emit `cmov`, which is a data dependency again and defeats it — the branch
   must be forced. Gated by the jump-distance census (1c).
2. **Hardware performance counters instead of inference.** VTune (free) or `perf`: L1/L2/L3
   misses, DTLB walks, branch mispredicts PER OP on the real binary. Every prediction on 09-12
   came from synthetic curves and three were wrong; counters would have settled the TLB question
   in ten minutes. Should run FIRST.
3. **Co-locate each table with its arming site.** For a table with a single arming site, place it
   adjacent to the ops that arm it: the flip then hits the line the instruction fetch already
   brought in, and touches/op → ~1 for those ops. Trades pool-blocking (cheap ARM) for locality
   (cheap TOUCH) — the tradeoff nobody has priced on ms/frame. Census first: how many tables
   have one arming site?
4. **Temporal coherence.** If view state (position, angle, doors, things) is unchanged the frame
   is a copy: near-zero ops for idle frames, which are common in play. The trivial case is cheap
   and the oracle can mirror it exactly; partial forms (sky/floor columns) are harder.
5. **Actually pin to a P-core, raise priority, set the power plan.** The pin attempt on 09-12
   FAILED (wrong ctypes signature) and was never retried; on a 6P+8E laptop the scheduler
   migrates freely and the yardstick swung 2.9–3.6 GHz. Likely +10–20% mean, far less variance.
   Free. **MEASURED 09-13: ~3%, NOT SEPARATED** (unpinned 102.4 vs pinned 99.3 ms/frame).
   The scheduler was NOT the source of the earlier 118→200 gap; keep the pin for variance only.
6. **Census the padding inside the instruction stream.** `pad 16`, `pad 16384`, `rep(N) stl.fj
   0,0` fillers exist for address arithmetic; every gap in the instruction stream is a wasted
   line on the critical path. Measure what fraction of the chain's footprint is padding.
7. **Static jump threading in the assembler.** A pure jump (flip=0) landing on another pure jump
   is two dependent loads to go nowhere; where the target is STATIC, rewrite A→B→C as A→C.
   Dynamic trampolines (`hex.tables.ret`, wflipped return addresses) cannot be threaded, but the
   static chains have never been counted.
8. **Batch screen IO per byte instead of per bit.** Measured 4.4% of wall time, one Python call
   per BIT (44,738/frame). Per-byte batching cuts it ~8×. Small, certain, site already located.
9. **Precomputed visibility per subsector (PVS).** `seg_pass1/2_leaf` + `e1m1_bspcode_pos_leaf`
   are ~20% of touches; a baked potentially-visible-set prunes the BSP walk to what can be seen.
   Big ops/frame cut on an open level; price the table size first.
10. **Viewport width as an explicit product knob.** ops/frame scales with columns. `VIEW_W=160`
    today; 120 is a 25% cut at zero engineering risk. Not an optimisation — a PRODUCT decision
    that needs the owner's sign-off — but it is the largest lever available today.

Considered and dropped: a separate compact code cache with write-invalidation (every flip pays a
range check; #3 gets most of the benefit without it), and 2 MB-aligned allocation against
cache-set conflicts (unmeasurable under current variance; do #5 and #2 first).

## 6. Gaps in this plan (found by reading it as a reviewer)

**Critical — the plan cannot succeed as written without these**

- **It has no instrument for its own metric.** The thesis is "optimise ms/frame, not ops/frame",
  and the project has NO reproducible ms/frame harness: `gamespeed.py` measures ops only, and
  the ad-hoc runs on 09-12 varied 2× on identical work. Every item above will be judged by noise
  until a harness exists that pins the core, alternates A/B/A/B, runs N reps, and reports
  ms/frame WITH a spread. Build this before anything in sections 2–5.
- **The shipped engine change is under-verified.** flipjump-151's own unit tests
  (`tests/unit/test_native_memory.py`, `test_interpreter.py` — storage mode, freeze/reset,
  garbage detection) were NEVER RUN after the 4-byte-cell change, and they test exactly what
  changed. The Linux build was last made before stages A–C. `pytest tests/host` on the doom side
  was not run either. `m2_std_gate` PASS is necessary, not sufficient.
- **The "free" knob sweep on existing binaries is confounded.** `menu` is two weeks older than
  `blocked25` with different features; comparing them conflates knob settings with code changes.
  That is the same mistake made on 09-12 with the "blocking made it 50% slower" claim. A real
  sweep needs same-source builds — 45 minutes each, so it is not free.

**Structural — the reasoning has holes**

- **Levers interact, and some conflict.** Inlining hot leaves (3a) GROWS the instruction stream;
  if 1a shows the chain is footprint-bound, 3a makes it worse. Block execution (2b) and
  co-location (5.3) change which words are self-modified. The plan lists them as independent.
- **The ~18 FPS ceiling multiplies two factors that trade against each other.** Cutting
  ops/frame by removing cheap ops raises the average cost of the remaining ones — the exact
  mechanism section 4 identifies. Treat 18 FPS as an upper bound, not an estimate.
- **Jump layout is a LEVER, not just a measurement.** 1c measures fall-through on the current
  binary, but the emitter could be changed to maximise it (hot-path block ordering, as compilers
  do) — which makes both 5.1 and 2b more effective. Missing entirely.
- **The M1 restore set is not mentioned.** 2b, 3a, 3c and 5.3 all change what is self-modified
  and where; CLAUDE.md's rule is that a feature is not done until the restore set carries its
  labels. Every emitter change here needs that step.
- **No kill criteria or decision thresholds.** 2b is "gated on 1c" but with no number; 1a has no
  "if the instruction stream is under X MB then…". Most of 09-12 went on levers that measured
  weak; explicit "stop if" rules would have saved hours.

**Correctness — risk of shipping wrong pixels**

- **Temporal coherence (5.4) and PVS (5.9) change what is computed.** A bug there produces
  subtly wrong frames the 4-viewpoint deg gate can miss; PVS needs a conservativeness proof or a
  many-viewpoint sweep (ca2_sweep's 260 frames is the right shape).
- **No baseline freeze before emitter changes.** 3a, 3c, 5.3, 5.6, 5.7 all move addresses;
  without `ritual.py freeze` on the current shipped binary first, regressions cannot be
  attributed.
- **The build_blocked.py warning fix is untested code.** It changed a check inside a 45-minute
  build and has not been run through one.

**Scope**

- **3b (collision) has no hypothesis.** "Ask why" is not a first step. A concrete one: does
  `sim.bind_things` iterate every thing every frame, and could it iterate only the moved ones?
- **The size metric is untracked.** 3a, 5.9 and a code cache all add words; the ship gate is
  35% of 2²⁷ and the plan never mentions it.
- **The profiler is fragile scratch tooling.** `mkprof.py` patches `_fjcore.c` by string
  anchors and broke once already when the source moved. Every measurement in sections 1–5
  depends on it. It should become a compile-time `FJPROF` flag in the engine itself.
