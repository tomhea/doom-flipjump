# Handoff — the FULL-GAME campaign: 35% of the address space, 20M ops/frame

**Owner's goal, set 2026-09-06, and it REPLACES the old target.** The 12M-ops campaign measured the
*renderer* on the *deg tier*. That number never described the thing a player runs. From now on there
are exactly two success metrics, both measured on the **combined full game** (collision, sim, thing
movement, input and the M1 self-reset all included):

| metric | how it is measured | target |
|---|---|---|
| **SPEED** | play **10 different games of 100 frames each**; each RUN's stat is `total_ops / 100` = that run's average ops/frame. Report the **mean run-average** and the **80th-percentile RUN** (the run at the 80%-high mark, by its average), showing that run's average-per-frame. | **80th-pct run ≤ 20,000,000 ops/frame** |
| **SIZE** | the game binary's **decompressed word count as a percentage of 2^27** (134,217,728 words — the w=32 address ceiling) | **≤ 35%** |

Nothing else is the criterion. In particular the `ca2_sweep` deg-tier median — the number the whole
12M campaign optimised — is **no longer the goal**. It stays useful as a cheap per-idea pre-gate,
but a change is judged by the two metrics above.

---

## 0. OWNER DECISIONS (2026-09-06) — these settle G1 and G8

**G1 — what the size target means: "pick the N that fits."** w=32 stays. Nine levels was never
achievable at this width (the M4 budget of 357,978,424 words is **2.67x** the hard ceiling of
2^27 = 134,217,728, so they do not fit at any usage %), and the width change is not being taken on
now. The size goal is therefore **not** "make room for nine levels" but: *keep the binary small
enough that levels can be added, and find the N that actually fits.* Concretely — at the
post-Phase-A measured one-level span of 74,091,162 words, exactly ONE level fits. Making a level
cheap enough that several fit is a real engineering goal; "nine levels" is not one at w=32.

**G8 — arbitration between the two metrics: SPEED is the binding one, size must stay sane.**
The owner's words: *"Speed is the more important one, but keep size at a sane size as more levels
should enter the binary at later stage."* So:

* an idea that cuts ops and grows the image is **acceptable while size stays under target**;
* size is a **budget to spend on speed**, not a co-equal threshold — but it is a budget with a
  purpose (levels land in this binary later), so spending it to zero is not "sane";
* an idea that grows the image and does **not** cut ops needs a size reason of its own.

⚠ This makes the SIZE instrument load-bearing rather than decorative, which is why
CR-2026-09-06's finding on `word_pct` mattered. The dangerous failure is the one that reads LOW:
the old reader's `data[64:]` offset, on a file with more than one segment, slices into the segment
table and measures **zero words** — 0% of the ceiling, a silent PASS, and a budget the campaign
would then spend without having it. (Its other constant, `// 4`, fails the *other* way — it
over-counts 2x at w=64, which is a loud false FAIL. CR round 2 caught this description stated
backwards in four places; both directions are now named separately.)

---

## 1. Where the tree stands (2026-09-06)

`main` is at **4218d27** (PR #82 merged, crist-APPROVED). It carries:

* **S2** — shared vpb pair-blocks (`generate_bands_walk_fj`): one `vpb_pb_<y2>_<c>` per DISTINCT
  pair via a 3-lane fcall instead of one per instance (40,567 → 5,326). deg fjm 15,168,954 →
  7,923,027 bytes (−47.8%) at +0.11% median, 260/260 byte-exact.
* **P10-5 selective padding** (stl, `flipjump-151` branch `1.5.1` commit **dc9ff1a**) — the fix that
  made the game tier assemble again after the P7 pad round broke it.
* Regenerated `m1`/`m5` restore sets (474 entries each), the mapbake test-bundle fix, and the
  campaign records in `scratchpad/12m/`.
* `tests/host`: **485 passed, 0 failed**.

### The measured baseline, and why it fails BOTH metrics

✅ **MEASURED 2026-09-06 with the controlled instrument.** The earlier estimates in this section
have been replaced by a real `gamespeed` run — the first end-to-end execution of the actual success
criterion. Command, verbatim:

```
python scratchpad/12m/gamespeed.py --fjm build/doom_e1m1_menu_p105.fjm --runs 10 --frames 100
```

```
SIZE: w=32  segments=1  data=125,492,170 words (93.50% of 2^27)  span=125,492,170 words (93.50%)  file=36,442,805 bytes
calibration: startup + 2 menu frames = 538,417 ops (subtracted from every run)
  run  0: 3,320,303,411 ops / 102 presented -> game-only 33,197,649 ops/frame
  run  1: 2,558,390,067 ops / 102 presented -> game-only 25,578,516 ops/frame
  run  2: 1,309,995,795 ops / 102 presented -> game-only 13,094,573 ops/frame
  run  3: 3,209,977,696 ops / 102 presented -> game-only 32,094,392 ops/frame
  run  4: 2,600,683,332 ops / 102 presented -> game-only 26,001,449 ops/frame
  run  5: 1,562,531,076 ops / 102 presented -> game-only 15,619,926 ops/frame
  run  6: 2,033,497,481 ops / 102 presented -> game-only 20,329,590 ops/frame
  run  7: 1,431,574,147 ops / 102 presented -> game-only 14,310,357 ops/frame
  run  8: 1,928,924,602 ops / 102 presented -> game-only 19,283,861 ops/frame
  run  9: 1,457,554,661 ops / 102 presented -> game-only 14,570,162 ops/frame

SPEED  mean run-average   : 21,408,048 ops/frame
SPEED  80th-pct run avg   : 26,001,449 ops/frame   (target <= 20,000,000)  OVER
SPEED  spread lo..hi      : 13,094,573 .. 33,197,649 ops/frame
SPEED  raw (menu included): mean 20,993,561, 80th-pct 25,496,895 ops/frame
SIZE   words              : 125,492,170 = 93.50% of 2^27   (target <= 35%)  OVER
SIZE   span / file        : 125,492,170 words (93.50%) / 36,442,805 bytes
```

⚠ Still UNVERIFIED and NOT replaced by this run: `overflow_probe`'s pass-1 numbers (the 45.6%
overflow, the pre-pad ~42M words) and the 1.184 pass-1→decompressed ratio. Those need an
`overflow_probe game` run of their own, which rung 0 will produce anyway.

| | measured | target | verdict |
|---|---:|---:|---|
| game binary words (DATA) | **125,492,170 = 93.50% of 2^27** | ≤35% | **FAIL** |
| game binary words (SPAN) | 125,492,170 = 93.50% | — | equal to DATA: one segment, nothing sparse |
| game binary file | 36,442,805 bytes | — | |
| **80th-pct run** | **26,001,449 ops/frame** | ≤20M | **FAIL — needs −23.1%** |
| mean run-average | 21,408,048 ops/frame | — | |
| run spread | 13,094,573 .. 33,197,649 | — | **2.54×** — why the metric is a percentile, not a mean |

### ⚠ The old ~33.4M figure was NOT representative, and the gap is half what §7's G3 assumed

This handoff carried **~33.4M ops/frame**, taken from `m2_std_gate`'s single door-route trajectory.
Measured across ten diverse runs, that route sits near the TOP of the range: the 80th-percentile
run is **26.0M**. So the gap to target is **6.0M, not 13.4M**.

That matters for G3, which concluded "the plan as written does not reach the target" by pricing
rungs against 33.4M. Against 26.0M the arithmetic is far more comfortable — collision alone
(~11.6M/frame, never optimised) is nearly twice the whole remaining gap.

⚠ Two cautions before anyone celebrates. First, the mean (21.4M) is *just* above target while the
p80 (26.0M) is 30% over — a mean-based reading of this same data would have flattered the binary,
which is exactly the failure the owner's percentile spec prevents. Second, this is the PADDED
binary; rung 0 reverts that padding and gives some speed back (LEDGER P10-1 vs P10-5: deg median
17,135,838 vs 16,584,954, +3.3%), so expect the baseline to move to roughly 26.5M.

### Why the full game costs ~2× the render

The deg/visual tier renders and stops. The game also runs, per frame:

| component | ~ops/frame | source |
|---|---:|---|
| render (walls/floors/things) | ~16M | the ca2_sweep median |
| **collision** | **~11.6M** | FINDINGS: "M14-d's four descents cost 11,602,784 ops" |
| sim + thing movement + input | few M | |
| M1 self-reset | per-frame overhead | the game loops and restores state every frame |

**Collision is ~35% of the full frame and the 12M campaign never touched it.** That is the single
biggest untouched lever and the reason 20M is plausible at all.

---

## 2. THE INSTRUMENT — `scratchpad/12m/gamespeed.py`, and it now runs

Finished 2026-09-06 after CR-2026-09-06 (PR #83) found the draft's `measure_speed()` was a guess.

* **`word_pct()` now delegates to `scratchpad/12m/fjmsize.py`.** The draft did
  `lzma.decompress(data[64:])` then `len(raw) // 4`. Both constants were unasserted assumptions:
  `64` is `20 + 12 + 32*segment_num` and holds only at `segment_num == 1`, and `// 4` is
  `memory_width // 8` and holds only at w=32. They fail in OPPOSITE directions and only one is
  dangerous: `// 4` over-counts 2x at w=64 (a loud false FAIL), while `data[64:]` on a
  multi-segment file measures **zero words** — a silent false PASS. Controls C2 and C3. `fjmsize` derives both from the header and reports DATA words (the metric) and SPAN
  words = `max(start+len)` (what must fit under the ceiling) separately.
* **`measure_speed()` imports the real device.** It does not construct one: it calls
  `m2_std_gate.run_fj`, the `Recording`/`Stopper`/`PcIO`/`NativeDeviceMemory` composition that
  `fj --io pc` builds. The draft's `flipjump.interpreter.io_devices.pc_io` does not exist.
* **The menu is measured and subtracted.** A run is `MENU_FRAMES` near-free menu frames plus
  one-time startup, then the game; leaving them in the numerator deflates the average for a
  reason that has nothing to do with the renderer. One calibration run measures the constant and
  every run subtracts it — and BOTH figures print, so the choice is visible (gap G8).
* **G6 is closed at the boundary.** `_demand_full_length` runs on every runner's result inside
  `measure_speed`, not inside `one_run` — the first version put it in `one_run` and its own
  negative control walked straight past it, reporting 250 ops/frame for a run that lost a frame.
* **G5 — closed, RE-OPENED by CR-2026-09-06 on PR #84, and closed again properly.** The first
  attempt was open-loop key patterns plus a `travelled >= 64` check, and it was wrong in both
  halves: a fixed key pattern cannot know where the walls are, so nine of ten runs were pinned
  against geometry for the majority of their movement frames — the 80th-percentile run, the
  headline number of the whole campaign, **moved on 5 of its 92 movement frames** — and the
  aggregate distance check passed them anyway, because a player scraping a wall still accumulates
  distance. `script()` now GENERATES each run by stepping the oracle (walk; turn when the geometry
  refuses), and `--validate` counts blocked frames PER FRAME. Measured after the fix: **every run
  moves on 100% of its movement frames**, 9 distinct end cells of 10, 2,258-unit spread. The
  control is mutation-tested against the old scripts and rejects them at 95% blocked.

  ⚠ The lesson is the one CLAUDE.md rule 3 already states, in the file that states it: an
  aggregate check is not a control. "Total distance > 0" and "the player is playing" are different
  claims, and only the second one is the metric's premise.
* **R9 is satisfied: `--selftest`, 13 controls, and they have already caught two real bugs**
  (the misplaced frame assertion above, and `emit_sizes` measuring `repr()`). `--selftest --fjm
  <path>` adds determinism on a real binary.

## 3. THE PLAN

### Rung 0 — REVERT THE PADDING. It meets the size target on its own.

The P10-5 selective padding is **~83M of the game's 125.5M words**. Reverting it:

* size **93.5% → ~31% of 2^27** (the pre-pad game base is ~42M words — UNVERIFIED, `scratchpad/12m/overflow_probe.py game`
  before it had a control) — **the SIZE metric PASSES**;
* the image drops ~36MB → ~10–12MB and ~9.5GB → ~3GB of RAM, which is what makes a 10×100-frame
  measurement runnable at all (the current image thrashes; a 1,000-frame run would take hours);
* it costs the padding's speed (deg median ~16.6M → ~17.6M), which **does not matter** under the
  new metric — the padding buys ~1M on the *render*, while the target needs ~13M off the *game*.

Do this first. It is one stl change (`flipjump-151` `1.5.1`: revert to the pre-pad widths, i.e. the
state at `0dcda77`, keeping the `sparse_*` macros as an unused tool), one rebuild, one measurement.

⚠ It changes what is on `main`, so it goes through the normal gate + a small PR.

### Rung 1 — the baseline

Rebuild the game (`python scratchpad/m5_build.py --menu --doors --out build/<name>.fjm`), then
`python scratchpad/12m/gamespeed.py --fjm build/<name>.fjm`. Record `mean / 80th-pct-run
avg-per-frame / word%` in `scratchpad/12m/LEDGER.md`. **Everything after this is judged against it.**

Expected: size ~31% **PASS**; speed ~33–35M **OVER by ~13M**.

### Rung 2 — COLLISION (the big lever, ~11.6M/frame, never optimised)

Read `src/doomfj/collision.py` and `src/fj/sim.fj`. What is already known:

* `generate_collision_move_fj` emits **four** candidate blocks — `cmh_` (`sim.check_position`) plus
  `cma_`/`cmb_`/`cmc_` (`sim.try_move`) — each ~2.16M words pre-pad, inlined at the call site.
  The seed descent (`{map}_dsccs_walk`) is ALREADY shared via `stl.fcall`; the four bodies are not.
* `generate_point_location_fj` bakes point-location as code (M14-e, "27× cheaper", 209 vertical +
  209 horizontal + 263 diagonal of 681 nodes).

Ideas, in the order the evidence favours:

1. **Share `try_move`** the way S2 shared the pair-blocks — 3 identical inlined copies → one fcall
   body with the candidate's x/y expressions passed in. Saves ~4.3M **words**; the *op* saving is
   whatever the redundant descents cost, which must be measured, not assumed.
2. **Skip candidates that cannot matter.** `cma/cmb/cmc` are the classic DOOM slide-response trio
   (try both axes, then each alone). If the full move succeeds, the other two are dead work — check
   whether the emitted code already early-exits (`hex.if0 1, mv_ok, {nxt}` suggests it does) and, if
   so, where the ops actually go instead.
3. **The seed descent per candidate.** Each candidate runs `dsccs_walk` again for its own position.
   If two candidates land in the same subsector, the second descent is redundant — a cheap
   compile-time or runtime memo may pay.

### Rung 3 — render op-count (the 12M campaign's unfinished business)

`hex.exact_xor` is 39.86% of the render as **471,786 calls/frame** spread over 120 callers — so the
lever is **fewer hex operations**, not cheaper ones (padding is exhausted; see FINDINGS AU). The
width doctrine (`FINDINGS H`/`I` audits) is the main unshipped source: narrow 8-nibble chains to 5–6
where the values provably fit. Each narrowing deletes exact_xor calls outright.

### Rung 4 — the self-reset overhead

The game restores 474 entries / 12,400 words **every frame**. Nobody has ever measured what that
costs per frame. Measure it before optimising it; it may be small, or it may be a rung of its own.

---

## 4. Doctrine for this campaign

* **The two metrics are the ship criterion.** `ca2_sweep`'s deg median and `deg_gate` remain as
  *cheap pre-gates* (they catch pixel changes in minutes), but an idea ships on `gamespeed`.
* **Byte-exactness still governs.** Every idea is still gated 4/4 deg + 260/260 sweep, and the
  full-game play-test (`m2_std_gate`) must still PASS — it is the only check that exercises
  collision, doors, the menu and the reset together.
* **One heavy build at a time** (CLAUDE.md rule 1), and check the PROCESS is gone, not the log.
* **Rule 3 the hard way, learned this session:** three analyses were built on the unmeasured premise
  "padding is absorbed, so it is free". A single label-diff falsified it (12% absorbed, not 100%)
  and the pad campaign that followed cost a KILL and a broken game tier. *A mechanism argument is
  not a measurement.* Run the cheap check that could falsify the premise BEFORE building on it.
* **Watch the tier you are optimising.** The pad round drove the deg median down while making the
  shipped game un-assemblable, and no gate noticed for weeks because every gate built deg. Any
  change to the stl or to shared emitters must be probed on the GAME tier
  (`scratchpad/12m/overflow_probe.py game`) before it is believed.

---

## 5. Instruments that exist (all with R9 self-tests unless noted)

| tool | what it gives |
|---|---|
| `scratchpad/12m/gamespeed.py` | **the success metric** — mean + 80th-pct-run avg/frame + word%; `--validate`, `--selftest` (13 controls) |
| `scratchpad/12m/fjmsize.py` | the ONE definition of the address ceiling `(1<<w)//w` and of an .fjm's word count; `--selftest` |
| `scratchpad/12m/overflow_probe.py <tier>` | peak wflip address vs the 2^27 ceiling; says whether a tier assembles |
| `scratchpad/12m/region_probe.py <tier>` | words per top-level region (label-gap attribution) — names WHERE the size is |
| `scratchpad/12m/emit_sizes.py <tier>` | emitted source chars per program part |
| `scratchpad/12m/wprof.py` | wflip cost attributed to the ISSUING site (`--level inner\|doom`, `--only <macro>`) |
| `scratchpad/12m/padrank.py` | pads ranked by ops-per-byte (**the pad pool is CLOSED — see FINDINGS AU**) |
| `scratchpad/12m/micro.py` | exact executed-ops-per-call and emitted space for a macro |
| `scratchpad/12m/ritual.py` | the per-idea gate: build → freeze → deg → 260-frame sweep → ledger row |
| `scratchpad/m2_std_gate.py` | **the full-game play-test** — menu, walk, door, survives 2 resets, byte-exact |
| `scratchpad/12m/repack.py` | LZMA 9\|EXTREME repack (retired: only −1.6% after S2; re-measure per image) |

## 6. Findings that will save you a week

`scratchpad/12m/FINDINGS.md`, sections AA–AU. The five that matter most here:

* **AU** — below-16M render is NOT reachable by padding: exact_xor 256 (the −1.33M lever) needs the
  game base under 29M words, a 13M cut — larger than the entire ~10M collision bake.
* **AO/AN** — the P7 pad round broke the game tier (exact_xor 256 ⇒ ~4.6× code ⇒ 195M words). Root
  cause found by REVERTING the optimisation, which is the technique to reach for.
* **AI** — padding is ~12% absorbed, ~88% real image growth; image growth costs ~0.3 executed
  ops/frame per op of growth. The "padding is free" premise is dead.
* **AC** — `hex.exact_xor` is 39.86% of the render, but spread over 120 callers with none above
  3.71%: there is no caller-side fix, only fewer calls.
* **AJ/AQ** — sparse-on-hot padding under-delivers (width beats coverage; the residual lives in
  other stl macros). Do not re-open it.

---

## 6b. BRANCH, COMMIT, CHECK AND CR RULES for this campaign

The process this campaign runs under. `docs/cr-rules.md` (R1-R9) is the contract; this pins how it
applies here.

### Branch

* **Start from `main`** (currently **4218d27**), not from `m4-nine-levels`. That branch is merged
  and its remaining purpose is M4 groundwork; carrying its 100+ commits again is how a 2,214-line
  PR happened, and it is what made review expensive.
* **One branch per rung**, named per R7: `m6-fullgame-metrics` for the campaign's milestone work,
  `s-<topic>` for a spike (e.g. `s-collision-descents` to measure before committing to a design),
  `fix/<slug>` for a hotfix. **Not** a single long-lived branch accumulating the whole campaign.
* ⚠ **`flipjump-151` is a SECOND repo** on branch `1.5.1`, wired in as an editable install. An stl
  change is a separate commit there with its own message, and the doom PR body must name the stl
  commit it depends on (this campaign's baseline needs **dc9ff1a**). **As of 2026-09-06 that repo
  has 9 unpushed commits, including the one `main` already depends on** — settle that before
  building on it, or a fresh clone silently builds the wrong stl and hits the game-tier overflow.

### Commit

* **One idea per commit**, message carrying the PROOF NUMBERS (op counts, word counts, byte-exact
  frame counts, test names) and no adjectives — CLAUDE.md's housekeeping rule.
* **Never `git add -A scratchpad/`.** Stage named files only; `scratchpad/` holds hundreds of
  untracked artifacts and one careless add swept 204 MB of label tables this session.
* A KILLED idea still gets a commit or a LEDGER row with its measured numbers. The killed rungs
  (P3-2b, P7-12, P8-1, P10-2, P10-6) are why the pad pool is closed rather than re-tried.
* Never write "verified"/"identical" for a property no gate actually ran on (R9's last line).

### Check — what must pass before a PR

| check | cost | when |
|---|---|---|
| `python -m pytest tests/host -q` | ~1 min | every change |
| `python -m pytest tests/fj/<touched>.py -q` | seconds | emitter changes |
| `scratchpad/12m/ritual.py all --id <ID> --base <BASE>` | heavy | any change that can move a pixel or an op — gives deg 4/4 + sweep 260/260 + the ledger row |
| `scratchpad/12m/overflow_probe.py game` | heavy | **any stl or shared-emitter change** — the pad round broke the shipped game for weeks because every gate built deg |
| `scratchpad/m2_std_gate.py --fjm <game>` | heavy | before any merge — the only check that exercises collision, doors, menu and the reset together |
| `scratchpad/12m/gamespeed.py --fjm <game>` | heavy | **the ship criterion**: mean + 80th-pct-run avg-per-frame + word% |

⚠ **One heavy build at a time** (CLAUDE.md rule 1), and check the PROCESS is gone
(`Get-Process python`), not that the log looks finished.

### CR

* **Every merge to `main` goes through a PR reviewed by `crist`** (`Agent(subagent_type="crist")`,
  invoke with the PR number). It reviews against R1-R9 and posts the verdict with `gh`.
* **Loop until APPROVED**, then merge. The PR #82 round is the worked example: CHANGES_REQUESTED
  with 3 findings (R5 missing a call-twice reentrancy test, R1 missing FAIL/PASS fences, R7 title
  and headers), fixed, re-reviewed, APPROVED, merged.
* **PR body shape is not optional** (R1/R7): a fenced **FAIL** log (the test red before the change)
  and a fenced **PASS** log (after), under `## TDD evidence (R1)`, plus `## Integration evidence
  (R2)` carrying the measured whole-program numbers. Prose summaries do not satisfy R1 — that was
  a finding this session.
* **R9 applies to this campaign's own instrument.** `gamespeed.py` is quoted as the success metric,
  so it may not be cited until it has a negative control (§2, and gap G6).
* **Docs-only changes still go through a PR** — small, but the handoff is the thing the next
  session reads, and it belongs on `main` rather than on a branch.

---

## 7. GAPS IN THIS PLAN — read before executing it

Written by the author of the plan, immediately after writing it. Two are load-bearing enough to
change what rung 0 means.

### G1 — ANSWERED 2026-09-06, see §0: "pick the N that fits", w=32 stays.

*The analysis that raised it, kept because the arithmetic is the reason for the ruling:*

#### G1 (STRATEGIC, the biggest). The size target cannot serve its stated purpose at w=32.

The owner set the size goal because 93.5% "doesn't allow adding of new levels". But
`docs/handoff-m4-nine-levels.md` §2 budgets nine levels at **~358M words** and says "the cap goes
to 2^29 = 536,870,912; the owner is fine raising it".

**At w=32 that is impossible.** An address is 32 bits, a word is 32 bits, so the program cannot
exceed `2^32 bits / 32 = 2^27 = 134,217,728 words`. This is not a tunable cap: it is the assembler's
`array('I')`, and it is exactly the `OverflowError` this session hit. `flat_max_words` (2^27, and
M4's proposed 2^29) is a RUNTIME allocation limit and a DIFFERENT thing — raising it does not widen
the address space.

**Nine levels at ~358M words is 2.67x the entire w=32 ceiling.** Even at 0% usage they do not fit.
So the honest position is one of:
* nine levels needs **w=64** (a memory-width change, with its own large cost), or
* levels must get ~8x cheaper than the M4 budget assumed, or
* ship fewer levels (M4 already lists "drop levels, keep full detail" as the fallback).

**This must be settled with the owner before the campaign optimises for a 35% target whose purpose
is undeliverable at w=32.** The 35% goal is still worth hitting — headroom is good, RAM is real,
and it keeps the tier assemblable — but it should be adopted for its own sake, not as "room for
nine levels", until the width question is answered.

### G2 (QUANTIFIED). Rung 0 probably does NOT pass the size metric on its own.

§3 claims reverting the padding takes size to "~31%". That number came from the pass-1 overflow
probe's `first_address` (42,034,242 words) — which is **not** what the metric measures. The metric
is the DECOMPRESSED IMAGE, and the probe aborts before pass 2 adds the reset part.

Calibrated on the padded build, where both numbers exist — ⚠ both from the pre-control tools,
so the ratio is a planning estimate and not a measurement:

| | pass-1 probe | decompressed | ratio |
|---|---:|---:|---:|
| padded game | 105,989,350 | 125,492,170 | **1.184** |

Applying that ratio to the pre-pad probe: **42,034,242 x 1.184 = ~49.8M words = ~37.1%** — over the
35% target by ~2.8M words. So rung 0 gets *close* and does not finish the job. Expect to need one
more size lever (the obvious candidate: S2-style sharing of the collision `try_move`, worth ~4.3M
words, which would land it at ~34%). **Measure the real decompressed number the moment the pre-pad
game is built; do not carry the 31% estimate forward.**

### G3. The arithmetic to 20M ops/frame does not close. — INPUT UNDER RE-MEASUREMENT

⚠ G3 prices every rung against a baseline of ~33.4M, which came from `m2_std_gate`'s single
door-route trajectory **including its menu frames over 45 frames**. Like-for-like against the
metric (menu subtracted, per-frame) that route is **34,984,855 ops/frame**. Whether the
ten-run 80th percentile is above or below it is a measured question, not an assumed one, and the
first attempt to answer it used broken scripts (see G5). Do not treat either number as the
baseline until a `gamespeed` run whose `--validate` output is attached says so.

Baseline ~33.4M, target 20M — a 13.4M cut. The rungs, generously priced: collision ~11.6M, of which
maybe half is redundant (~5.8M); render width doctrine (~1-2M, unmeasured); self-reset (unknown).
That is ~8M and leaves ~25M. **The plan as written does not reach the target**, and no rung is
sized from a measurement. Either a fourth large lever exists (the per-frame self-reset is the only
unmeasured candidate big enough) or 20M needs the renderer to do less work — fewer columns, coarser
spans — which is a fidelity decision, not an optimisation. Do rung 1, then re-price every rung
against the real baseline before promising the target.

### G4. Rung 2 conflates a SIZE lever with a SPEED lever.

"Share `try_move` the way S2 shared the pair-blocks" saves ~4.3M **words**. It does not save ops —
S2 itself cost +0.11% ops. Under the SPEED metric the collision win must come from **eliminating
redundant work** (the repeated seed descents, dead candidates after an early exit), not from
sharing. Sharing belongs to the SIZE metric (and see G2 — it is likely needed there). Split the
rung in two and price each against its own metric.

### G5 — RAISED, IGNORED, AND THEN VINDICATED. Read this before writing any harness here.

**This gap was written, then closed on a control that could not fail, and the CR that caught it
had to run the very dump this section names.** The paragraph below is unchanged from when it was
written; it predicted the exact failure that occurred. Its instruction — *"dump each run's end
position and a frame or two, and require the 10 to differ meaningfully"* — was not carried out
before the first baseline was taken and promoted into `CLAUDE.md`. §2 records the fix.

Note also what this section says about `m2_std_gate`'s route: *"the play-test's oracle-planned
route is the model — it walks somewhere real"*. That was correct. The first baseline PR called that
route "unrepresentative" while its own scripts were the broken ones.

`script(seed)` emits deterministic key patterns, but nothing checks that they explore anything: a
script that walks into a wall for 100 frames measures a cheap corner. The render alone spans
**2.96M to 33.4M ops/frame across viewpoints (11x)**, so the answer is dominated by where the 10
games go. Before trusting any baseline: dump each run's end position and a frame or two, and require
the 10 to differ meaningfully (the play-test's oracle-planned route is the model — it walks
somewhere real). The 80th-percentile-of-runs choice partly defends against this, but only if the
runs actually differ.

### G6. `gamespeed.py` has no vacuity control.

A run that dies early returns a small op total and looks like a *win*. The device must report the
number of frames actually presented and the harness must assert it equals 100. Add that with the R9
negative control (§2) before any number from this tool is quoted.

### G7. No before/after comparison at the metric.

The plan reverts the padding (rung 0) and then baselines (rung 1), so the padded state is never
measured under the new metric. That forfeits the one clean data point on what the padding actually
costs/buys the FULL GAME. If it is affordable, take a short measurement (fewer runs) on the current
padded binary first — it thrashes, so cost it before committing.

### G8. Smaller, but real.
* The 100 frames include ~2 near-free menu frames (~2,344 ops each) and the one-time startup, both
  of which bias the run average — state whether the metric includes them (currently: it does).
* The metric is defined on E1M1 with `--menu --doors`. Pin that as the measured configuration, or
  the number silently changes when the shipped config does.
* ~~No rule for an idea that improves one metric and worsens the other~~ — **ANSWERED, see §0:
  speed binds, size is a budget to spend on it while staying sane.**
