# HANDOFF — the road to a playable game (M14.7 → M15 → M16)

Three steps, owner-defined (2026-08-17):

* **Step A / M14.7** — work the CR optimization backlog, best first, measured, keep only what helps.
* **Step B / M15** — make it a *game*: menu + level selection, the sim wired in, wall collisions,
  every "off" feature on, doors.
* **Step C / M16** — AI monsters that move, weapons, damage, HUD.

This document is the plan. §0 is the part that decides whether the rest is trustworthy; §7 lists
what the three-step brief did **not** mention and where each missing piece was inserted.

---

## §0 THE METRIC, AND THE MISTAKE THAT MAKES THIS SECTION FIRST

**The number that describes the game is the SWEEP MEDIAN, not a gate viewpoint.**

`scratchpad/m14_sweep.py` exists because of exactly this confusion, and its docstring says so: the
four `deg_gate` viewpoints are *hard frames near the top of the distribution* (the docstring records
33.5–45.2M when the certified sweep median was 22.94M). In this very session I quoted the four gate
viewpoints as though they were the frame rate; the owner corrected it. **Do not repeat it.** Every
Step-A claim is a median over the 260-frame walk, and a gate viewpoint is only ever quoted as a
*worst case*, labelled as such.

Corollaries, all of them learned the expensive way in this repo:

1. **Both sides of a comparison get measured in the same session, on the same harness.** A stale
   baseline is not a control (`docs/handoff-perf.md` §0).
2. **A `deg_gate` PASS is the correctness proof, never the perf proof.** It proves byte-exactness
   and pins op counts to the digit at four points. It says nothing about the median.
3. **A vanished STOP is invisible to a byte-exactness gate — by construction.** A stop only ever
   skips provably-dead work, so deleting one is byte-exact and pure cost. This is not theory: this
   session found the `tsstop` plane gate had been silently switched off across the whole map
   (MEASURED: 128 gated nodes → **0** of 681 on stock E1M1), and no gate in the repo could see it.
   **If a change touches the input of a stop/prune predicate, COUNT THE STOPS before and after.**
   Nothing else will tell you.
4. **A budget that binds paints wrong pixels.** Stops are safe, budgets are not. Any budget added in
   Step B or C needs an emit-time never-binds assert or a proof it sheds only invisible work.

### The numbers you are inheriting

MEASURED THIS SESSION (2026-08-17, commit `0b67376`):

| what | value | how |
|---|---|---|
| shipped static tier, 4 gate viewpoints (worst-case, **not** the median) | 51,186,631 / 40,843,272 / 48,666,231 / 38,931,760 | `scratchpad/deg_gate.py`, byte-exact ×4 |
| the same four before the WR-1 fix | 51,653,980 / 41,936,825 / 48,876,228 / 39,596,401 | same, on a worktree at `4ff4d51` |
| runtime plane gates, stock / lite | 128→0 (pre-fix), restored on static builds | `scratchpad/_cr_wr1b.py` |
| leaves a mover can REACH vs "any leaf with headroom" | 538 of 657 (stock), 314 of 446 (lite) | flood fill, this session |
| `check_position` geometry lookups | 3,577.7 µs → 6.5 µs (549×) | in-process A/B |
| host suite | 245 passed, 1 deselected, 54.70 s | `pytest tests/host -q` |

⚠ **UNVERIFIED — re-measure before acting on any of these.** They come from docs/memory, not from a
harness run in this session: sweep median ≈ **29.39M** (M14.5 rung 2, the *moving* build); base
renderer floor ≈ 20.94M; walker engine ≈ 96–127M fj/s; M14-d ≈ 11.6M per *moving* tic; M14-e ≈ +43M.

### The one that reframes Step A

The 29.39M median belongs to the **moving** build. This session's plane-gate fix narrows the gate
set only when `moving_things=False`, so **it buys the static tier and buys the M14 tier nothing** —
on a moving build the wide set is still required, because things really can move. Step B turns the
moving build into the shipped one. **So the M14 tier's cost profile is the one Step A must
optimize, and much of what looks like a win on `deg_gate` may not survive the transition.**

⇒ **A0.3 below (baseline on the M14 tier) is not optional bookkeeping. It is the thing that decides
which of the 150 findings are worth doing at all.**

---

## §1 STEP A / M14.7 — the optimization backlog

**Source of truth: `scratchpad/cr2/findings/*.md` — 158 findings across 10 units, of which round 1
(commit `0b67376`) closed 8.** They are NOT 150 independent rungs and must not be run as 150 gates:
at ~25 min per build that is weeks of wall-clock, and most LOW findings are worth single-digit
thousands of ops against a ~30M frame.

### A0 — PRECONDITIONS. Do not start measuring until these are true.

**A0.1 — Unify the three pictures (CR finding IN-3). BLOCKING.**
Today three entry points build three different renderers:

| flag | `build.py` (the shipped artifact) | `scripts/walk_e1m1.py` (what a human sees) | `deg_gate` (what is certified) |
|---|---|---|---|
| `stack_steps` | **off** (default) | on | on |
| `bbox_cull` | **off** (default) | on | **off** (default) |
| `deg` | **off** (default) | on | on |

You cannot optimize "the game" while the artifact you ship, the artifact you certify and the
artifact you look at are three different programs. Pick ONE configuration — it should be the
walker's, because that is the one a player sees — make `build.py` emit it, make the gate certify it,
and delete the divergence. Everything after this point assumes one picture.

**A0.2 — Resolve the two open correctness claims. BLOCKING for anything touching projection.**
`PJ-1` (`wedge_bbox_plane` reads a 4-nibble slice while its oracle mirror `bbox_wedge_miss` uses
integer coords) and `PJ-2` (the M13-absmul "multiply |viewx|, negate the product" identity holds only
when the product's low 16 bits are zero). Both are *premise deaths* from M14 making view positions
fractional — the same class as the M14-c bug. The M14 gate exercises fractional positions and
passes, so they are latent at worst; **latent is not resolved.** Settle each with a 10-second fj unit
probe with a negative control, the way `_visunit.py` / `_ssheadaddr.py` were used — not with a
25-minute build, and not by reading the comment, because in both cases the comment states the dead
premise as proven.

**A0.3 — Establish the baseline on the tier that will ship.**
Build the M14 tier (`state_wire="bin"`, `player_sim=True`, `moving_things=True`, things on) at the
A0.1 configuration, cache the `.fjm`, and run `m14_sweep.py` for a median + mean + worst + the
>25M tail count. Record the four `deg_gate` viewpoints alongside as the worst-case anchor. **This
single number is what every Step-A rung is scored against.** Also run it with `--cold` (all-dirty
bindings) so the binding-cache steady state is not silently doing the work.

**A0.4 — Make the profiler answer "where does the median frame go".**
`scratchpad/opprof.py` already attributes ops to `sim.*` vs the base renderer. Extend it to the
per-macro level on a MEDIAN frame (not a gate viewpoint). Without this, the ranking in A2 is a
hypothesis order derived from stl `Time Complexity` annotations — which is what it currently is, and
which the reviewers themselves labelled UNVERIFIED.

### A1 — METHODOLOGY: how to measure 150 things without 150 builds

**Batch, don't serialize.** Group findings into batches that are *mechanically independent* — they
touch different macros, different loops, different registers. Emit and assemble ONE binary per
batch, sweep it, and attribute. Interactions inside a batch are the risk; the rules:

* **Two findings interact if either changes how OFTEN the other's code runs.** A stop/gate finding
  (changes the population) NEVER shares a batch with a per-op cost finding (changes the price). Put
  every population-changing finding in its own rung.
* **Findings that only change the price of disjoint macros are additive** and belong in one batch.
  The repo has measured this before: `fj-cost-model` records that frame ops are the sum of primitive
  costs with **no super-linear program-scale effect**, which is precisely the licence to batch.
* **When a batch under-delivers vs the sum of its parts, split it and re-measure.** Do not explain
  the gap; measure it. The repo has an `nnls` pricing harness for exactly this attribution.
* **Byte-exactness is the accept/reject gate for every batch**, and op-count-identical-but-byte-exact
  still means structure moved — investigate it (CLAUDE.md rule 2).
* **Keep a rejected-findings log with its number.** A measured negative result closes a direction
  permanently and is worth as much as a win; this repo has lost days re-deriving them.

**The stop rule.** Work the batches best-first and stop when a whole batch returns **< 0.5% of the
median**. The tail of the backlog is dominated by LOW findings worth low-thousands of ops against a
~30M frame; grinding them is how a perf campaign eats a month for 1%.

### A2 — THE BATCHES, best first

Every op figure below is **UNVERIFIED** — modelled by the reviewers from stl `Time Complexity`
annotations at `@=27`, never measured. They set the ORDER, not the forecast.

**Batch 1 — `fixed_point.fj` primitives.** Highest leverage in the repo: every other file calls
these, so a win multiplies. `PM-1` `fixed_div` divides at `2n` nibbles where `n+f+1` suffice
(~20–25% off the frame's dearest primitive; needs `n+f+1`, not `n+f`, to keep `idiv`'s most-negative
`.neg` edge safe) · `PM-2` `mul_const` strength-reduces with one `shl_bit` per bit, but
`shl_hex n,times` costs the same as ONE bit shift — the shift chain is ~4× too expensive in every
`mul_const` and all three `read_table*` macros.
⚠ `PM-4`: `fixed_mul_lo` (48 call sites) has **no direct unit test** while the *tested* `fixed_mul`
has zero production callers. Fix the test coverage in the same rung — this batch is the one place
where a silent arithmetic change would poison every frame.

**Batch 2 — free ROW-RULE operand swaps.** `PM-3` (`fixed_mul_lo dist, planeheight, ys` passes the
dense operand second; also `xstep`/`ystep`), `SR-8` (`w2s_wall:382`). A multiply costs one schoolbook
row per nonzero nibble of the SECOND operand, so putting the sparser operand second is
**bit-identical and free**. Cheapest possible batch; do it early to bank a clean win.

**Batch 3 — pointer arithmetic in monotone loops.** `FR-1` 2–4 `hex.ptr_index` (~2.1k ops each) per
claimed column where the same loop already walks siblings with `ptr_add` · `FR-7` `do_store` ·
`SI-6` seven loop-invariant `hex.set w/4, <ptr>, <label>` deletable via a data initializer.

**Batch 4 — cheap extracts and widths.** `FR-2` (`hex.mov 8` + `shr_hex 8,4` ≈1.1k where
`hex.mov 2` ≈200 is bit-identical) · `FR-9`/`FR-11` over-wide registers · `PJ-10` `hex.zero` before a
same-width `hex.mov` (548 calls/frame) · `PJ-15` `hex.cmp 8, x, czero` → `hex.if0 8, x`.

**Batch 5 — dispatch tables replacing runtime multiplies.** `PJ-5` `scale_from_global_angle`'s
`anglea` is identically `ANG90 + xtoviewangle[x]` (the viewangle cancels) so its `sinv` is a
per-column constant → a baked `xtasin[x]` table · `SR-1` `lines_pid_ids` (~5.6k, up to 4×/column,
half its output dead at every call site) · `SR-3` WPX height→block `mul_const` · `PJ-8` `hex.div 8,8`
by a power-of-two `ds`.
⚠ These trade span for ops. R4: each new table adds its line to the DESIGN.md §1.2 span ledger and
the build asserts `storage_mode == flat`.

**Batch 6 — loop-invariant hoists.** `FR-3` (per-SEG lip test recomputed 4×/column) · `FR-6`
(`blk`/`blk_ofs`/`tbl_p`/`run_r0`/`run_last` are functions of `u` alone) · `PJ-7` (`wedge_qt`'s
q-dispatch is per-frame invariant, re-taken 4×/seg) · `PM-7` (`bb_ascending` re-tested per row).

**Batch 7 — POPULATION changes. One rung each, never batched.** `FR-4`/`FR-5` gated zeroes ·
`SR-5` sprite run-loop window in `rel` space · `SR-9` dead `win_*` setup · `SR-2` dead clamp chains ·
`SI-4` `check_line` hot/cold split · `SI-5` `check_line` emitted 16× inline vs a shared leaf.
Each changes how often code runs ⇒ each needs its own before/after sweep.

**Batch 8 — `sim.fj` / the M14 tier specifically.** This is the batch that matters most once Step B
ships, and the one A0.3 will re-rank. `SI-1` — **now unblocked**: the stl says `hex.ptr_index` is
`ptr + index*2w` (one `dw` slot) and 2-arg `hex.read_byte` reads one slot; the `i*2*dw` that blocked
this was the *destination register* stride in the multi-byte form. So entry `i` is at `base + i*dw`,
`hex.vec 2*nss` / `hex.vec 2*nt` **over-allocate 2×**, and the empty-leaf skip (worth 0.7–2.2%) is
available. ⚠ Still write the negative-controlled fj probe before touching gated binding code —
three probes disagreed here once already. Also `ST-5` (`move_with_collision_lines` runs the expensive
`_bsp_descend_code` 4×/tic next to the cheap exact walk M14-e built and M14-d never adopted) and
`IN-11` (`_bsp_descend_code` still uses the generic 2-fcall cross product where a baked-partition
form is multiply-free on 61% of E1M1 nodes).

**Batch 9 — the reachability refinement, priced honestly.** Once Step B makes the moving build the
shipped one, `thing_live_subsectors` (every leaf with headroom, 657 of 682) is what keeps the plane
gate dead. Reachability shrinks it to **538 (stock) / 314 (lite)** — MEASURED this session, but with
a crude flood fill that ignores drop-offs, ledges and door specials, so the true set is between the
two. 538 of 682 is still 79% of the map, so **this probably does NOT restore many gates on stock
E1M1 and may be worth ~nothing.** Price it with the cheap emit-time stop-count probe
(`scratchpad/_cr_wr1b.py`) BEFORE building anything.

**Not a batch — the host-side wins.** `RM-2`/`RM-4`/`RM-5` (the oracle recomputes frame-invariant
data per frame; `try_move` recomputes the current position 3×/tic; the blockmap accelerator is
unreachable from `try_move` because `**kw` would `TypeError`). These cost no fj ops but make every
gate and test faster — and this session's `wad.py` memoisation already bought 549× on one call. Do
them whenever a build is occupying the machine.

### A3 — EXIT CRITERIA for Step A

1. One configuration, built + certified + played (A0.1).
2. PJ-1 and PJ-2 resolved with negative-controlled probes (A0.2).
3. A measured median on the M14 tier, before and after, from `m14_sweep` in one session.
4. `deg_gate` byte-exact ×4 at the final state.
5. A rejected-findings log with numbers.
6. Stop when a whole batch returns < 0.5%.

---

## §2 STEP B / M15 — make it a game

### B0 — WIRE WHAT ALREADY EXISTS. This is the biggest single win in the document.

**M14 and M14.5 are built, gated and byte-exact — and unreachable from anything a human runs.**
`sim.fj`, `player_sim`, `collide`, `moving_things` and `state_wire` appear ONLY in `scratchpad/`
gates and `tests/`. `scripts/walk_e1m1.py`'s `SRC` list does not include `sim.fj`, and its docstring
still says "There is no fj-side input/simulation yet (that's M14)". Today the fj program renders a
frame from a host-supplied viewpoint and **the host still does movement and collision in Python**.

So "wall collisions" and "simulator" from the brief are **mostly wiring, not construction**:

* add `sim.fj` to the walker's and `build.py`'s source lists;
* pass `state_wire="bin"`, `player_sim=True`, `collide=True`, `moving_things=True`;
* feed the binary wire (`wireformat.encode_feed` + the thing block + bindings + visibility) instead
  of three decimals;
* read the player's new position back out of the frame instead of computing it host-side;
* delete the host-side movement stand-ins.

⚠ Do this FIRST in Step B, before doors or menus. It is the step that converts "a renderer driven by
a Python loop" into "a game running in FlipJump", and every later feature is cheaper to reason about
once the state actually lives in the program. Exit: the walker moves, turns and collides with the
host doing no simulation at all, and `m14_sweep` gives the median for the real tier.

### B1 — TURN ON THE FEATURES THAT ARE OFF

The owner's item (2): make `build.py` ship what the walker shows. That is A0.1, and if A0.1 was done
properly this is already true. Verify per CLAUDE.md's Feature Wiring Checklist — grep the entry
point and paste the enabling line. Candidates beyond the three: `--two-sided` (byte-exact but
~6× slower, so a *look-at* flag, not a ship flag, until Step A says otherwise) and `wall_mode=WPX`
(true 1×1 texels, +2–6M/frame).

### B2 — DOORS AND LIFTS

Nothing opens today. `mapsimplify.py` deliberately PRESERVES door and lift sectors and any line with
a special or the impassable flag (`protected[sds[ld.back].sector]`), so the geometry is there and the
tags survive — but there is no `P_UseLines`, no sector-height thinker, no animation.

This is the first genuinely NEW subsystem and it is where the two-mirror cost lands hardest:

* **a moving sector height changes the picture every tic**, so per-sector floor/ceiling heights stop
  being baked constants and become runtime state. Grep for every baked `floor_h`/`ceil_h` — the
  seg constant blocks, `subsector_tables`' `ssfloor`, the plane bands, the thing `sp_z` derivation —
  and decide which become table reads. **This is an M12pp-scale change to the baked-constant model,
  not a feature bolt-on.** Budget it as its own ladder of rungs, each gated.
* **the oracle must model it too**, in the same commit, or byte-exactness is gone (rule 2).
* the trigger path needs `P_UseLines` (a use ray from the player against nearby linedefs) — the
  collision code in `sim.fj` already walks the blockmap and can be reused.
* ⚠ a closed door has `ceil_h <= floor_h`, which is exactly the condition
  `thing_live_subsectors` uses to EXCLUDE a leaf. **Once doors open, that predicate is wrong** and a
  thing behind a door can vanish. Fix the predicate in the same rung that makes doors move.

### B3 — LEVELS, MENU, SELECTION

DESIGN.md already scopes this as M15's R2 deliverable: *9 E1 levels + a level table + `goto_level` +
state reset*, built from Freedoom so the artifact is redistributable, and it explicitly requires
**re-validating `@`/fps at full-program scale** (U7 — the M11c slice `@` was only a lower bound, and
`@` grows with program size). Add to the brief's "menu level-selection":

* the level table and `goto_level` are a *memory-map* problem before they are a UI problem — nine
  levels of baked geometry against the flat-span limit (R4). Measure one extra level's span before
  designing the menu.
* **state reset** between levels: the program self-modifies, so "restart a level" means restoring a
  clean image, not jumping to a label.
* the menu itself is a rendering mode (text/glyphs) — DESIGN's F8 notes the current leaning is a
  compact text HUD rather than downscaled `STBAR`/`M_*` patches.
* level completion needs the exit switch/teleport special, which is B2's trigger machinery.

### B4 — THE LOOP, AND THE HONEST ARCHITECTURAL CONSTRAINT

**One run = one frame.** The fj program self-modifies; running it twice on a dirty image dies after
~9 ops. That is why the loop is host-side and why `fastrun` restores the image per frame. A
self-contained playable `.fjm` — one process, its own loop — is a *separate architectural question*,
not a feature, and the brief should decide explicitly whether "playable" means:

* **(a) playable via the host loop** (what the walker does today, and what B0–B3 deliver), or
* **(b) a standalone `.fjm` you hand someone.**

(b) requires the program to restore its own mutated state per frame — an M12pp-style involution
applied to the whole frame, not just per-seg constants. **Do not let this be discovered in Step C.**

### B5 — EXIT CRITERIA for Step B

Host does no simulation; walls collide in fj; every shipped feature on; doors open and the oracle
agrees byte-for-byte; a menu selects among ≥2 levels and state resets cleanly; span flat and under
the limit with the level table in; median re-measured and reported against A3's number.

---

## §3 STEP C / M16 — monsters, combat, HUD

Ordered by how much new *state* each adds, because state is what the oracle has to mirror.

**C1 — Pickups (half-built already).** M14.5 §3.3 shipped `thvis`: a 1-nibble visibility flag per
baked VANISHABLE thing (armour, health, ammo, weapons, keys, barrels) at a fixed address, read by a
compile-time-constant `hex.if0`. **The rendering half of "the medikit disappears when you take it"
already exists and is gated.** What is missing is the pickup *test* (player radius vs thing radius)
and the inventory it feeds. This is the cheapest real gameplay in the document — do it first.

**C2 — Damage, health, inventory.** Player state grows: health, armour, ammo per type, weapons
owned, keys. The wire already carries a `keys` byte. Mostly host-side bookkeeping mirrored into fj
state cells.

**C3 — Weapons and hitscan.** A hitscan is a ray against the blockmap — the same traversal
`sim.fj`'s collision already does, with a different accept test. Projectiles are moving things, which
M14-e's runtime thing table already supports. ⚠ The weapon sprite is a **fixed-size** bitmap, not
world-scaled — DESIGN calls this out as the trap: it needs a 2× downscale shared bit-exactly with
the host, or the mirrors diverge.

**C4 — Monster AI.** The most expensive item in the document and the one most likely to blow the
frame budget:

* every moving monster is a `check_position` per tic, and M14-d's collision is **UNVERIFIED
  ~11.6M ops per moving tic** — for ONE mover. Price a single AI tic BEFORE writing the AI.
* the AI needs line-of-sight (`P_CheckSight`), which is another BSP traversal per monster per tic.
* monsters moving is what `thing_live_subsectors` was widened for, so Step A batch 9's reachability
  work and this land on the same predicate.
* state per monster (target, state frame, tics-to-next-state) multiplies the runtime thing row.

**C5 — HUD.** DESIGN F8, re-sized for 160×100: current leaning is a compact text/number HUD over
downscaled `STBAR`. A status bar is a `VIEW_H` change, which moves every projection constant — do it
as its own gated rung, not as a garnish on C2.

**C6 — Death, corpses, level exit.** Falls out of C2+C4; corpses are things with a different sprite.

---

## §4 THE BUDGET THREAD THAT RUNS THROUGH ALL THREE

Step A *saves*; Steps B and C *spend*. Without a ledger, A's wins vanish into B and C and nobody can
say where. So:

* **every rung in B and C reports its median delta**, the same way A's do;
* **maintain a running ledger** — A's savings, B's spend, C's spend, and the net;
* **set the target before spending.** DOOM runs at 35 tics/s. At the UNVERIFIED ~100–200M fj/s
  engine rate, 30 fps needs ~3–7M ops/frame and 15 fps needs ~7–13M. Against a ~29.4M median
  (UNVERIFIED) and an UNVERIFIED ~20.94M base-renderer floor, **single-digit fps is the realistic
  landing zone for the current fidelity**, and a genuinely playable frame rate needs a fidelity
  decision (resolution, texture tier, sprite budget) — not just Step A. **Make that decision
  explicitly, with numbers, at the A3 exit gate. Do not let it emerge as a disappointment in C.**

---

## §5 THE TESTING DEBT THAT WILL BITE ALL THREE STEPS

From `scratchpad/cr2/findings/tests.md`, still open after round 1:

* **`sim.thing_load` / `bind_things` / `thing_pass` have no test at all** (TS-1) — M14.5's entire
  runtime-thing mechanism is gated only by a 20-minute build. Step B makes this the shipped path.
* **`wireformat`'s encoders/decoders are entirely untested** (TS-7) and the composite frame feed is
  open-coded in four harnesses (ST-2). Step B sends far more over that wire.
* **`write_program_files` — "ORDER IS THE CONTRACT" — has zero tests** (TS-5).
* **37 of 41 `stream_render.fj` macros and 16 of 31 `projection.fj` macros have no unit test**
  (SR-18, PJ-3); the tested set is the retired framebuffer tier. PJ-3 notes this is *how the M14-c
  bug survived*.
* **R5's "every LUT entry" half fails** — several LUTs are sampled, not exhaustive (PJ-4, TS-8).

⚠ **Write the fj unit probe before the build, every time.** This session, the two address questions
that cost the most were each settled in ~10 seconds by a probe and would have cost 25 minutes each
by build. `_visunit.py` (passed) and `_ssheadaddr.py` (failed) are the pattern.

---

## §6 THE RULES THAT DO NOT CHANGE

CLAUDE.md's five, plus the three this session added or sharpened:

* **one heavy build at a time** — concurrent builds die silently, exit 255, empty output;
* **byte-exactness is the contract** — both mirrors move in the same commit, then re-certify;
* **trust the gate, distrust the pre-gate** — and a tool used as evidence ships a negative control
  (R9). All three `cr/` tools now have `--selftest`; a stale fixture is now a hard failure, because
  `alpha_check` used to print `SKIP` and still conclude "all mutations rejected";
* **the emitter ABI is frozen** — fj global labels, macro names, positional parameter lists;
* **a shared-helper change is a FAN-OUT edit** — grep `src/`, `scratchpad/` AND `tests/`;
* **count the stops** when touching a prune/gate predicate (§0 corollary 3);
* **`pytest tests/host` now means what the doc says** — `slow` is a registered marker excluded by
  `addopts`; check the "N deselected" line. It used to walk into a ~70-minute build test at 17%.

---

## §7 WHAT THE THREE-STEP BRIEF DID NOT MENTION, AND WHERE IT WENT

| missing piece | inserted at | why it cannot wait |
|---|---|---|
| the median vs gate-viewpoint metric | §0 | every Step-A number is meaningless without it |
| unify the three build configurations | **A0.1** (blocking) | otherwise you optimize a program nobody ships |
| PJ-1 / PJ-2 open correctness claims | **A0.2** (blocking) | latent fractional-position bugs under the code A optimizes |
| baseline on the M14 tier, not the static one | **A0.3** | the static-tier wins may not transfer; this re-ranks the backlog |
| a median-frame profiler | A0.4 | the current ranking is modelled, not measured |
| batching + interaction rules + a stop rule | A1 | 150 findings × 25 min is weeks |
| a rejected-findings log | A3 | measured negatives are as valuable as wins here |
| **M14/M14.5 are not wired into any entry point** | **B0** | the sim exists and is unreachable; biggest single win |
| moving sector heights break the baked-constant model | B2 | doors are an M12pp-scale change, not a feature |
| a closed door is exactly `thing_live_subsectors`' exclusion test | B2 | opening doors makes the predicate wrong; things vanish |
| level table / span budget before menu UI | B3 | 9 levels vs the flat-span limit is a memory-map problem |
| state reset between levels | B3 | the program self-modifies; "restart" ≠ jump to a label |
| **host loop vs standalone `.fjm`** | **B4** | decide what "playable" means before C, not during it |
| pickups — the rendering half already ships (`thvis`) | **C1** | cheapest real gameplay available |
| the weapon sprite is fixed-size, not world-scaled | C3 | a known mirror-divergence trap |
| price ONE AI tic before writing AI | C4 | collision is UNVERIFIED ~11.6M/moving tic for one mover |
| a status bar is a `VIEW_H` change | C5 | moves every projection constant |
| the A-saves/B-spends/C-spends ledger + an fps target | §4 | otherwise A's wins silently vanish into B and C |
| the untested surfaces B and C are about to depend on | §5 | `sim.fj`'s thing path and the whole wire are untested |

---

## §8 SUGGESTED ORDER

`A0.1 → A0.2 → A0.3 → B0` **then** `A1–A2 batches 1–4` **then** `B1, B2` **then** `A2 batches 5–9`
**then** `B3, B4` **then** `C1 → C2 → C3 → C5 → C4 → C6`.

Rationale for the interleave: **B0 before the optimization batches**, because the M14 tier is what
Step A must optimize and B0 is what makes it the real tier (§0). **C4 late**, because AI is the only
item that can single-handedly blow the budget, and it should meet a frame that Step A has already
made as cheap as it is going to get.
