# The measurement process

Every performance claim in this project is produced by `scratchpad/12m/msframe.py` and recorded
in `scratchpad/12m/msframe_ledger.jsonl`. A number that did not come through this process is not
a measurement; it is an anecdote, and CLAUDE.md's Performance Claims rule already forbids
quoting it.

This exists because 2026-09-12 produced, for the SAME binary doing the SAME work, readings from
53 to 125 M fj/s, and a +19% huge-page result that three alternated repeats showed to be noise.
None of that was the engine. All of it was process: single samples, a process free to migrate
between P- and E-cores, two runaway `find` commands of the session's own making pegging cores
for hours, and a warm-vs-cold file cache. The instrument closes each of those doors, and the
protocol below says when it may be used and what its output means.

## The metric

**ms per frame**, sustained, on a fixed key script. Not ops per frame, not ops per second.

    ms/frame  =  ops/frame  ÷  ops/s

Both factors are reported, but neither is the objective: the blocking campaign measured
`b26` at +45% ops and +45% ops/s for an IDENTICAL 452 ms/frame, and `menu` at 1.85× the ops of
`blocked25` for a comparable frame time. A change is judged on the product, and only on the
product.

## What the instrument guarantees

| door | how it is closed |
|---|---|
| core migration, clock drift | the child is pinned to one logical P-core at HIGH priority; the pin's return value is checked and `GetLastError` printed on refusal |
| a busy machine | every process's CPU time is sampled twice, 1 s apart; anything over half a core is listed and the run is REFUSED unless `--ignore-busy` is passed (and the note must say why) |
| clock / core-type shifts mid-run | an L1-resident C yardstick runs before and after every measurement; a low reading is flagged as "E-core or throttled?" |
| order effects | arms alternate, counterbalanced: A,B on even reps, B,A on odd |
| cross-contamination | every measurement is a fresh process (the image load is per-process) |
| wrong program | presented frames must be byte-identical across arms and reps; speed is refused otherwise |
| single samples | N reps (default 5); the report is a median, a range, and a verdict |
| untraceable numbers | the ledger records both binaries' hashes, the engine `.pyd` hash, both repos' git heads, the power plan, the busy-process list, the full env, and every rep |

## The verdict rule, stated so it cannot drift

With N alternated pairs, arm B is **FASTER** (or **SLOWER**) only if

1. every pair agrees in sign, and
2. the median A/B ratio differs from 1.0 by more than the resolution floor (default **3%**).

Otherwise the verdict is **NOT SEPARATED**. Five pairs all agreeing by chance is 1/16 one-sided;
that is the confidence you get by default and no more. NOT SEPARATED means *measure more, use
more frames, or give up* — it never means "probably fine".

The resolution floor is not arbitrary: `--selftest` runs the same binary against itself and
prints the worst pair's deviation. That IS the machine's noise. An effect below it is not
measurable on this box today, whatever the theory says.

## The protocol for a change

**0. Prove the instrument, once per machine state.** `msframe.py --selftest`. It must call
A-vs-A NOT SEPARATED and A-vs-A+20 ms SLOWER with the delta within tolerance. If the negative
control separates, the machine is too noisy; fix that (busy processes, power plan) before
measuring anything.

**1. Freeze the baseline BEFORE the change.**
`msframe.py --a build/<shipped>.fjm --save-baseline <name>`. The baseline stores the binary's
hash and the engine's hash; `--against` refuses to run if the binary on disk has changed.

**2. Correctness gates before speed.** In this order, and a failure stops the process:
- engine change: `tests/wheel_smoke.py` op-counts bit-identical; flipjump-151's
  `tests/unit/test_native_memory.py` and `test_interpreter.py` (storage mode, freeze/reset,
  garbage detection); a Linux rebuild if the change touched a platform path.
- emitter or layout change: `alpha_check`, `emit_baseline --check`, `ritual.py freeze` against
  the shipped label table (it says exactly which addresses moved), the M1 restore set updated
  (CLAUDE.md: a feature is not done until the set carries its labels), `narrow_arm_window`.
- anything touching state, doors or the reset: `m2_std_gate` (cumulative across resets).
- anything that changes WHAT is rendered (temporal coherence, PVS): the 260-frame `ca2_sweep`,
  not the 4-viewpoint gate — a subtly wrong frame hides from four viewpoints.
- always: the size gate, `word_pct` ≤ 35% of 2²⁷.

**3. Measure.** `msframe.py --a build/<new>.fjm --against <name> --note "<what changed>"`.
Default 200 frames × 5 reps. Report the ledger line, not a retyped number.

**4. Decide by the rule.**
- FASTER → adopt, record the ledger line in the commit message.
- SLOWER → drop, and record that too; a measured negative is worth as much as a positive.
- NOT SEPARATED → 10 reps or 400 frames. Still not separated → the change is below this
  machine's resolution; drop it or park it. Do not adopt on hope.

**5. Kill criteria are declared before the work starts**, per item in
`handoff-throughput-plan.md`: e.g. "block execution only if the fall-through census shows
≥ 60% of ops fall through", "drop leaf inlining if the instruction-stream footprint grows past
the L2 size measured in 1a". A lever without a kill criterion gets a day of work it may not
deserve; 2026-09-12 spent three of those.

## What is NOT a measurement

- a number from a run while a build, gate, or stray process was active
- a comparison between binaries of different vintage or feature set ("`menu` vs `blocked25`"
  conflates two weeks of code changes with the knob under test — same-source builds only)
- a prediction from a synthetic curve (`latprobe.c` bounds the pure chase; the game has reuse
  the chase does not, and three predictions from it were wrong)
- anything with N = 1
- a speed number whose pixels were not checked

## Known biases of the instrument (measured 2026-09-13, handoff-throughput-plan section 10.6)

- **Fixed setup inside `core.run`.** The engine allocates, fills and copies the flat array on the
  first `run()` call: 0.96-2.16 s per fresh process (2-frame vs 14-frame runs). At 200 frames
  that is 5-10% of the reported ms/frame. A/B verdicts are unaffected (both sides pay it); the
  ABSOLUTE ms/frame is high by that much. Fix when msframe is next touched: subtract a 2-frame
  calibration per binary, or have the engine report the loop's own time.
- **Fresh-process spread is +-8% on a quiet box** (the same 421M-op loop: 1.72-2.16 s across five
  processes, yardstick steady). Physical page placement of the 512 MB flat array is the likely
  cause. This is why the instrument runs five fresh processes and decides by the 3% rule on
  medians; a single run is not a number.
- **An L3-streaming neighbour costs 15-31%** (`scratchpad/12m/hog.py` on another P-core), and a
  video render on the box cost ~10%. The busy-machine refusal is not optional.
- **The clock is 3.5-3.7 GHz under this load on the i7-12700H, not the 4.7 GHz turbo.** Quote
  ns/op or ms/frame; a cycles/op figure needs the clock read from the
  `\Processor Information(0,N)\% Processor Performance` counter during the run.

## Where things live

| what | where |
|---|---|
| the instrument | `scratchpad/12m/msframe.py` |
| the ledger (append-only, the source of truth) | `scratchpad/12m/msframe_ledger.jsonl` |
| frozen baselines | `scratchpad/12m/msframe_baselines/<name>.json` |
| the plan the measurements serve | `docs/handoff-throughput-plan.md` |
