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

| | measured | target | verdict |
|---|---:|---:|---|
| game binary words | **125,492,170 = 93.5% of 2^27** | ≤35% | **FAIL — and no room for new levels** |
| game binary file | 36.4 MB | — | (fast-LZMA; 13.8× vs deg's 26.2×) |
| full-game ops/frame | **~33.4M** (1,504,887,174 ops / 45 frames, `m2_std_gate`) | ≤20M @ p80 | **FAIL — needs ~40% off** |

⚠ **The ~33.4M is a trajectory average from the play-test, not the new metric.** It is the only
full-game number that exists. The first job of this campaign is to replace it with a real
`gamespeed` baseline.

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

## 2. THE INSTRUMENT — build this first, it does not exist yet

`scratchpad/12m/gamespeed.py` is **drafted to the owner's spec but NOT RUNNABLE.** Finish it before
anything else; every claim in this campaign is measured with it.

* **`word_pct()` — DONE and correct.** Decompresses the `.fjm` (LZMA2 raw, 64-byte header) and
  returns `(words, 100*words/2^27)`.
* **`measure_speed()` — the one thing to fix.** It needs the scripted-keyboard device the shipped
  binary actually uses. The placeholder `from flipjump.interpreter.io_devices.pc_io import PcIO`
  with `key_script=`/`frame_limit=` kwargs is a GUESS. **Read `scratchpad/m2_std_gate.py` and
  `scratchpad/m5_gate.py`** — they build the stock `--io pc` device plus a screen that EOFs the
  keyboard once N frames have been presented (`m2_std_gate` lines ~74–95). Reuse that object; do
  not invent one. The point of the gates' device is that it is the same thing a human runs.
* **Why one `run()` per game is enough:** `FjmRunner.run()` returns the run's total op count, and
  the game self-resets internally, so a 100-frame key script is ONE native run. No per-frame
  capture is needed — which is exactly why the owner asked for per-RUN percentiles.
* **The 10 games** are deterministic index-driven key patterns (`script(seed)`), no RNG, so a
  re-measure is reproducible.

**R9 (a tool used as evidence needs a negative control): `gamespeed.py` has none yet.** Add one —
e.g. a `--selftest` that measures a binary twice and requires identical run averages (determinism),
and that a deliberately shortened frame limit changes the totals. A metric that cannot fail is not
a metric.

---

## 3. THE PLAN

### Rung 0 — REVERT THE PADDING. It meets the size target on its own.

The P10-5 selective padding is **~83M of the game's 125.5M words**. Reverting it:

* size **93.5% → ~31% of 2^27** (the pre-pad game base is ~42M words, measured by
  `scratchpad/12m/overflow_probe.py game`) — **the SIZE metric PASSES**;
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
| `scratchpad/12m/gamespeed.py` | **the new success metric** — ⚠ speed half unfinished, no negative control yet |
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
