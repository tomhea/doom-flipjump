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

**1a. Split the trace by access type.** *DONE 09-13 -- section 8.* Histogram instruction-stream touches (`ip` fetches) and
flip-target touches SEPARATELY. The dependent chain depends only on the former. If the
instruction stream is a small fraction of the 16 MB, making *it* resident is the lever and the
flip targets can stay scattered — they overlap. `mkprof.py` needs one extra `PROF_HIT` bucket.

**1b. Cost per object, not touches per object.** *DONE 09-13 -- section 7.* For every named object: touches, distinct
lines, and touches-per-line. High touches on few lines is cheap (L1); modest touches spread
thinly is expensive. `nameheat.py` + the word dump already hold the inputs. This replaces the
touch-count ranking, which put `cb_bx` (490 lines, L1-resident) at #1 and is therefore the wrong
list to optimise from.

**1c. Jump-distance distribution.** *DONE 09-13 -- section 8.* What fraction of ops have `j == ip + 2w` (fall-through)?
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

## 7. Measured 09-13: cost per object (1b) -- the ranking the plan is now built on

`scratchpad/12m/heatcost.py` over the word-level trace of `b26` (842,328,561 touches, 14 frames)
joined to its own label table. Footprint = distinct 64 B lines at 4-byte cells, the engine today.

```
BY FOOTPRINT (what fills the cache)
 rank   lines@4B      MB   touches%   reuse T/L   object
    0    129,921    7.93      6.61%         428   m1_reset
    1     22,110    1.35      8.42%       3,208   seg_pass2_leaf
    2     20,196    1.23     13.01%       5,427   simcollide_skip
    3     15,495    0.95      2.98%       1,618   e1m1_bspcode_pos_leaf
    4     14,627    0.89      2.09%       1,202   cma_vyd
    5     14,619    0.89      2.21%       1,275   cmh_vyd
    6     11,404    0.70      5.63%       4,156   thing_pass_leaf
    7      9,532    0.58      4.13%       3,651   seg_pass1_ts_leaf
total touched: 301,248 lines = 18.39 MB; the top 25 objects hold 88.3% of them
```

**`m1_reset` is 43% of the entire touched footprint (7.93 of 18.39 MB) for 6.6% of the touches,
with the lowest reuse of any large object.** It runs as one bulk walk at the start of every
frame, before the render -- so every frame begins with the caches flushed of the previous
frame's hot set. It is CODE, not data: the m1 restore set names 12,238 cells and the object
spans 585,878 words, ~48 words of wflip chain per restored cell. The lever is therefore FEWER
CELLS RESTORED PER FRAME (a dirty set, or not self-modifying what must be restored), not a
packed table.

The touch-count leaders the old ranking put first -- `hex.tables.ret`, `hex.tables.res`, the
temp word at address 0 -- are ONE cache line each with 43-53M touches: L1-resident and free,
exactly as section 6 predicted. `cb_bx` does not appear in the top 25 by footprint at all.

**Re-rank:** 3c (the M1 reset) moves to #1 among program-side levers. The rendering leaves
(`seg_pass2_leaf`, `simcollide_skip`, `e1m1_bspcode_pos_leaf`, `cma/cmh_vyd`, `thing_pass_leaf`)
are the next ~6 MB and are instruction stream -- what 1a decides.

## 8. Measured 09-13: the split trace (1a) and the jump census (1c) -- the plan is now facts

One instrumented run of `b26`, 14 frames, 421,164,280 ops (`mkprof2.py`, `splitanalyze.py`).

**1c. Jumps:** fall-through (`j == ip+2w`) **6.38%**, loop 0%, near (within +-64 words) **50.82%**,
far **42.79%**.
- KILLED by their own kill criteria: **5.1** (predict fall-through -- it would mispredict 94% of
  the time) and **2b** (block execution -- there are no fall-through runs to amortise over).
- The 50.8% near jumps land within +-4 cache lines and are likely already L1 hits via the
  adjacent-line prefetcher. The **42.8% far jumps are the expensive chain loads.**
- ~~**2a** (read `j` before the flip, prefetch the next fetch) is now the only engine lever aimed
  at the chain~~ -- **KILLED in section 10 (measured: the flip store costs 0.02 ns/op).**

**1a. The two streams** (units are 8 words = 32 B at 4-byte cells, so the MB figures are ~2x
high; the ratios are exact):

```
IP-STREAM      499,032 units    50% in 10,441   90% in 93,366   95% in 142,644   (~2.9 MB true at 90%)
FLIP-TARGETS     9,219 units    50% in     15   90% in    363   99% in     981   (~10 KB at 90%)
overlap 9,217   ip-only 489,815   flip-only 2
```

- **The flip targets are L1-resident. The instruction stream is 98% of the footprint.** The chain
  IS the footprint. Everything framed around "scattered flip targets" is retired: data
  relocation (already measured weak) and **table co-location (5.3)** -- the flips are already
  cheap.
- The chain's working set: 90% of instruction fetches in ~2.9 MB -- just past the L2 knee, which
  is exactly where the latency curve put the game. Consistent.
- ~~Because the instruction stream is the footprint and 1b says `m1_reset` is 43% of it: shrinking
  the reset code is THE lever.~~ **WRONG -- footprint is not time; section 10 measures the reset
  at 14.3% of the time for 13.2% of the ops.** 12,238 cells restored per frame at ~48 words of wflip chain each.
- **3a (inline the hot leaves) GROWS the instruction stream** -- the interaction section 6 warned
  about is now measured to point the wrong way. Demoted; only with a footprint gate.
- **5.6** (padding census) and **5.7** (static jump threading) shrink the instruction stream and
  are promoted.
- NEW LEVER, from 1c + the 3.12-words-per-line density: ~63% of ops are wflips and their chains
  live in the assembler's wflip area, where `insert_wflip_ops` SHARES chain tails between values
  (its "found-statistic"). Sharing makes chains DAGs -- near-but-not-adjacent jumps (the 50.8%)
  and half-empty lines. The trade between chain SHARING (less code) and chain CONTIGUITY (denser
  lines, more fall-through) has never been measured. It is the assembler's, not the emitter's.

## 9. ~~THE PLAN, RE-RANKED BY MEASUREMENT~~ -- SUPERSEDED BY SECTION 11 the same afternoon (ranked by footprint, which section 10 shows is not time)

| # | lever | why it is here | gate |
|---|---|---|---|
| 1 | **M1 reset: restore fewer cells per frame** (dirty set) | 43% of the touched footprint, lowest reuse, a cache flush before every render; it is code | restore-set labels; `m2_std_gate`; `msframe --against shipped` |
| 2 | **2a: read `j` before the flip, prefetch `flat[j>>ww]`** | the only engine lever on the 42.8% far jumps | op counts + pixels; `msframe` |
| 3 | **wflip-area layout: chain contiguity vs sharing** | 63% of ops; density is 3.12/8 words per line; never measured | assembler; byte-exact; `msframe` |
| 4 | **5.6 padding census + 5.7 static jump threading** | both shrink the instruction stream, which is 98% of the footprint | assembler; byte-exact |
| 5 | **3b collision ops** | `simcollide_skip` is a hot leaf (reuse 5,427): its cost is OPS, not misses -- an ops/frame lever | emitter; byte-exact |
| 6 | **4: knob re-sweep vs ms/frame** | still valid; needs same-source builds (45 min each) | `msframe` |
| 7 | 5.8 per-byte IO (small, certain); 5.10 viewport (product decision) | | |
| -- | **KILLED:** 5.1, 2b (6.4% fall-through); 5.3 co-location (flips L1-resident); data relocation | | |
| -- | **DEMOTED:** 3a leaf inlining -- grows the instruction stream; only behind a footprint gate | | |

Ceiling unchanged: ~2-3x end to end, an upper bound. Expected in-game today: ~99 ms/frame,
~200 M fj/s, ~10 FPS (pinned baseline `shipped`).

## 10. Measured 09-13, afternoon: TIME per op, and where it goes -- the cost model

Section 9 ranked levers by cache footprint. Footprint is not time. Five more instruments, all in
`scratchpad/12m/` (`mkprof3.py` builds two instrumented engines; `timeobj.py`, `cachemodel.py`
read them; `micro/storewait.c`, `micro/tlbcost.c` are the microbenchmarks; `prof3run.py` /
`sieverun.py` are the pinned runners), all on the i7-12700H P-core 2 at 3.5-3.7 GHz (read from
the `% Processor Performance` counter during each run -- NOT the 4.7 GHz turbo), 4-byte cells.

**10.1 Time by object** (rdtsc every 64 ops, b26, 14 frames, quiet box):

```
kept 421,013,056 ops in 1.907 s -> 4.53 ns/op = 220.8 M ops/s = 16.4 cycles/op at 3.62 GHz
 rank   time%    ops%   ns/op  cyc/op  object
    0  20.88%  24.96%   3.79    13.7   simcollide_skip
    1  16.38%  14.53%   5.11    18.5   seg_pass2_leaf
    2  14.31%  13.24%   4.89    17.7   m1_reset
    3  10.61%   8.59%   5.59    20.3   thing_pass_leaf
    4   6.42%   5.93%   4.90    17.7   e1m1_bspcode_pos_leaf
    5   6.35%   7.64%   3.76    13.6   seg_pass1_ts_leaf
    6   6.29%   6.25%   4.56    16.5   seg_pass1_leaf          top 7 = 81.4% of the time
   ...  cma_vyd / cmh_vyd 3.26 ns/op (the fastest big objects), thing_pass_leaf 5.59 (the slowest)
```

**ns/op spans only 3.26-5.59 across every object with >= 1% of the ops.** Time share tracks ops
share within +-30% everywhere. `m1_reset` -- 43% of the footprint -- is 14.3% of the time for
13.2% of the ops. **Per-op cost is nearly uniform, so ops/frame IS the currency after all**, at
~4.5 ns per op; what varies is a modest memory term on top of a large fixed one.

**10.2 The engine floor.** The prime sieve (`sieverun.py`, N=1,000,000, 527,179,628 ops, ip
stream 99.39% L1-resident by the model, TLB 100%): **378.2 M ops/s pinned on the shipped engine**
(the owner's "300M+" confirmed) = 2.68 ns/op = **9.2 cycles/op at 3.45 GHz**. A bare dependent
chase of the same shape in L1 (`storewait.c` V0) is 1.57 ns = ~5.7 cycles. **The engine loop
spends ~3.5 cycles/op on itself** -- eleven branch micro-ops per op (unaligned check, two span
checks, three garbage checks, two IO checks, looping, null-ip, the back-edge), which at two
branches per cycle is a 5.5-cycle throughput floor that overlaps the chase only partially.

**10.3 The memory term.** `mkprof3.py S` runs both access streams through a simulated Golden Cove
hierarchy (L1D 48K/12-way, L2 1.25M/10, L3 24M/12 exclusive) and a DTLB(96)/STLB(2048) model,
with latencies MEASURED by `tlbcost.c`'s packed chase: L1 1.2 ns, L2 3.45 ns, **L3 26.5 ns**
(~98 cycles -- twice the textbook figure), DRAM ~100 ns.

```
ip stream   L1 83.48%   L2 12.62%   L3 3.77%   DRAM 0.13%     -> +5.1 cycles/op over the L1 floor
flip stream L1 99.64%                                          -> L1-resident, as 1a said
TLB (ip)    DTLB hit 97.55%   STLB hit 2.25%   page walk 0.195%   -> +0.3 cycles/op
LRU what-if: a 1.25 MB cache serves ~97% of fetches, 2 MB serves 98.2%, 4 MB 99.0%
pages: 50% of fetches in 215 pages, 90% in 1,934 (STLB is 2,048), 10,993 touched
```

**10.4 The model closes.** floor 9.2 + cache 5.1 + TLB 0.3 = **14.6 cycles/op predicted vs 16.4
measured** (-11%). The residual is the size of the run-to-run spread (10.6), so the model is
trusted to price levers. In shares of the frame: **engine floor 56% (chase 35%, loop overhead
21%), cache misses 31% (L2 hits 6%, L3 hits 22%, DRAM 3%), TLB 2%, unexplained ~10%.**

**10.5 Killed by measurement.**
- **2a (read `j` before the flip / prefetch): the flip store costs nothing.** `storewait.c`:
  engine order vs bare chase +0.02 ns at L1, +0.3 ns at L2; d=1 self-modification (the flipped
  word is the next op's word: 4.1% of the game's ops, 5.5% of the sieve's) adds 0.04 ns; the
  loads-first variant is SLOWER (+0.2 ns). Memory disambiguation handles this pattern. Dead.
- **The TLB: 2%.** The program is already TLB-friendly (97.55% L1-DTLB hits; 90% of fetches inside
  the STLB's reach). Large pages on any OS are worth <= 2-3%. The owner's question is answered:
  there is no TLB lever here, with or without privileges. (The 09-12 WSL2 THP test could not have
  shown one anyway -- a guest 2 MB page over 4 KB host backing yields 4 KB TLB entries -- but the
  model closes the question by itself.)
- **Footprint as a ranking.** The L3-served 3.77% of fetches cost 3.5 cycles/op: the ENTIRE
  "make it fit L2" lever is a 22% ceiling, and `m1_reset`'s 34% share of those misses caps its
  cache lever at ~7%. Sections 7-9's ordering is withdrawn.

**10.6 Measurement facts that change the process.**
- **Fresh-process variance is +-8% on a quiet box**: five runs of the same 421M-op loop took
  1.72-2.16 s (4.08-5.12 ns/op) with the yardstick steady at 3.2-3.6 G. Physical page placement
  of the 512 MB flat array (L2/L3 are physically indexed) is the likely cause. msframe's five
  fresh processes + median is the right shape; nothing below its 3% rule is decidable anyway.
- **An L3-streaming neighbour costs 15-31%** (`hog.py` on another P-core: 2.25 s vs 1.72-1.94 s);
  the owner's video render cost ~10% while it ran. The busy-machine refusal stays, and in-game
  FPS will drop with other apps open.
- **`core.run` carries 0.96-2.16 s of fixed setup per process** (flat allocation, garbage fill,
  segment copy -- measured by 2-frame vs 14-frame runs), so msframe's absolute ms/frame is
  5-10% high at 200 frames. A/B verdicts are unaffected (same setup both sides). Fix: subtract a
  2-frame calibration per binary, or have the engine report the loop's own time.
- **The clock is 3.5-3.7 GHz under this load, not 4.7.** Every cycles/op above is at the measured
  clock; ns/op is the portable number.

## 11. THE PLAN, v3 -- ranked by the measured cost model

Per op today (b26, quiet, 3.6 GHz): **16.4 cycles = 4.5 ns.** Target 300 M ops/s = 12.1 cycles at
this clock, i.e. -4.3 cycles.

| # | lever | measured size | what to do | gate |
|---|---|---|---|---|
| 1 | **Engine loop: 11 branches/op -> ~5** | ceiling 3.5 cyc (21%); expect ~2 (12%) | (a) when `cell32 && flat_count == 2^27` at w=32 every 32-bit address is in span -- drop BOTH span checks in that specialisation, provably; (b) fold the three garbage compares into one branch (`((f^M)==0)\|((v^M)==0)\|((j^M)==0)`); (c) fold the two IO tests into one; (d) fold `j==ip` / `j<dw`; (e) strip-mine `ops++` | ops + pixels identical (`m2_std_gate`), then `msframe --against shipped`; per-step A/B, keep only separated wins |
| 2 | **ops/frame** (4.5 ns each, uniform) | proportional | the 12M-campaign toolbox, ranked by 10.1's ops%: `simcollide_skip` 25% (88% L1 -- pure op count: 3b, with the concrete hypothesis from section 6), `seg_pass2_leaf` 14.5%, `m1_reset` 13.2% (restore fewer cells), `thing_pass_leaf` 8.6%, `seg_pass1_ts` 7.6%, `seg_pass1` 6.3%, bspcode 5.9% | byte-exact gates; `msframe` for the ms |
| 3 | **The L3 tail** (3.77% of fetches at 26 ns) | ceiling 3.5 cyc (22%); expect 1-1.5 | m1_reset holds 34% of the L3-served fetches: order its restore walk by address so the stream prefetches (ceiling 7%); then pack the 90-99% band of the ip stream (47K -> 157K lines) -- the what-if curve says the working set is only slightly past L2, so the TAIL is the target, not the hot core | `cachemodel.py` predicts before a build; `msframe` decides |
| 4 | **Clock / power** (outside the program) | +20-30% | the P-core ran at 3.5-3.7 GHz; plugged in on a performance plan it turbos to 4.7. Record the plan (msframe does) and the clock (the counter) with every number | -- |
| 5 | **msframe setup bias** | 5-10% of absolute ms/frame | subtract a 2-frame calibration, or report engine loop time | `--selftest` |
| -- | **CLOSED:** TLB / large pages (2%); 2a, 2b, 5.1, 5.3 (engine chain tricks); footprint as a metric; "L2 capacity is the bottleneck" (it is 22%, behind the engine's own 56%) | | | |

**Expectation for the owner.** Quiet machine, this laptop: ~220 M fj/s in-loop on b26's mix today
(~200-230 M on the shipped binary), 3.6 GHz. Levers 1+3 landing at their expected values give
~12.5-13 cycles/op = **~280-300 M fj/s at 3.6 GHz -- the 300 M target is reachable, barely, and
only on a quiet box**; at 4.7 GHz the same program would already exceed it. Frame time is that
rate times ops/frame: at the 20 M-ops/frame goal and 3.4 ns/op that is ~68 ms = **~15 FPS**
(~19 at 4.7 GHz). The earlier "2-3x end to end" was a guess; this is a sum of measured parts.

**Sequencing.** Lever 1 first (one engine session, no builds, the largest measured piece, gated
by op counts + pixels + msframe); lever 3's reset ordering second (one emitter session; the
restore set is regenerated, R-reset-set applies); lever 2 continuously with the existing
toolbox; lever 5 when msframe is next touched.

**Verdict on the plan: satisfied.** Every lever is sized by a measurement on this machine, the
cost model that sizes them reproduces the measured per-op time within the run-to-run spread, the
two largest earlier candidates (TLB, footprint) are closed by numbers rather than by argument,
and each lever names its gate.
