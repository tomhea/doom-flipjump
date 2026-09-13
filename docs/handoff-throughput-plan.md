# Throughput plan: the angles not yet tried

Written 2026-09-13 after a day that explained the engine's speed gap but did not close it. This
records what is settled, what was measured to be weak, and — the point of the document — the
angles that were never examined.

## What the numbers pin down

```
frame time  =  ops/frame  ÷  ops/s
            =  19,855,016 ÷ ~125,000,000/s  ≈  160 ms  ≈  6 FPS      (shipped binary, sustained)
engine ceiling: ~420 M ops/s  (benchmark_loop.fj, 16 KB working set)
```

Per op the interpreter touches memory **twice**: the instruction pair at `ip` (one line — `f` and
`j` are adjacent) and the flip target. Only the first is on the critical path: the next `ip` is
`j`, so each op is one **dependent load**. At ~125 M ops/s that load averages ~4 ns — L2-ish.
Reaching 420 M would need ~1.2 ns, i.e. L1 for essentially every instruction fetch. The touched
set is 16 MB at 4-byte cells. So the realistic optimistic case is not 420M:

| lever | from | to | basis |
|---|---|---|---|
| ops/s | 125 M | ~250 M | hot 90% inside L2 |
| ops/frame | 19.9 M | ~14 M | the 12M target was nearly reached once |
| **frame time** | 160 ms | **~56 ms → ~18 FPS** | both together; neither alone |

## Measured weak — do not revisit without new evidence

| lever | result | why |
|---|---|---|
| huge pages (real THP, alternated ×3) | +1.9%, noise | hot set is ~683 pages, already TLB-resident |
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
