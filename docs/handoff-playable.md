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
| **per-frame image reset (the floor)** | **52.5-61.5 ms**, independent of ops | `core.reset()` x5 on a 68M-word image |
| effective engine rate incl. reset | 144.6M / 186.3M fj/s | `FjmRunner.run()`, frames 2-3 |

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

> ### ✅ A0.2 DONE — BOTH CONFIRMED (2026-08-17) AND BOTH FIXED + GATED (2026-08-18).
>
> `scratchpad/_pj1_probe.py` and `scratchpad/_pj2_probe.py`, each with two-sided controls (R9),
> each ~30 seconds, no build:
>
> | | as shipped | the proposed fix |
> |---|---|---|
> | **PJ-1** `wedge_bbox_plane` vs `bbox_wedge_miss`, 8 planes × 5 positions × Qtrue∈{-1,0,+1} | 110 agree / **10 DIFFER** | 120 agree / 0 DIFFER |
> | **PJ-2** absmul vs `fixed_mul`, 10 (a, viewx) cases | 5 agree / **5 DIFFER** (all +1 ULP) | 10 agree / 0 DIFFER |
>
> **They are not merely latent.** PJ-1's dangerous direction reproduces exactly as predicted
> (`fy<fx, m=5, Qtrue=0`: the oracle keeps the box, fj culls the whole BSP subtree — its walls,
> plane claims, step faces and things). Controls that make this quotable rather than suggestive:
> integer positions agree in both modes; PJ-1's q=0/q=2 planes agree everywhere; PJ-2's even-`a`-at-
> a-half-unit agrees while odd-`a` at the same offset differs, which is the R17 vacuity the finding
> predicted, now asserted instead of assumed.
>
> **BOTH ARE NOW FIXED (2026-08-18).** Owner directed the fixes before B0, which was the right call:
> B0 makes fractional positions the shipped path, so after it they would be live bugs in the game.
>
> * **PJ-1 — THE ORACLE MOVED, NOT fj.** `mapcompiler.bbox_wedge_miss` now floors AFTER combining
>   (16.16 eye threaded through `visible_segs`/`bsp_render_order`). ⚠ The first attempt went the
>   OTHER way, on a stated-but-false claim that both rounding forms are conservative. They are not:
>   only floor-after-combining has error `frac(E) ∈ [0,1)` on all four q, so only it can never
>   over-cull. Per-axis flooring gives q=3 error `fx+fy ∈ [0,2)`, culling boxes that are genuinely
>   INSIDE — and the wedge's angular slack is ZERO at view angles that are exact multiples of 45°,
>   two of which are certified gate angles. **fj emission is UNCHANGED by PJ-1 — zero op cost.**
> * **PJ-2 — fj moved to the oracle's signed multiply, at THREE sites**, the third
>   (`frame_render.fj` `seg_pass1_leaf_body_proj`) not listed in the finding. flipjump warns on an
>   unused macro parameter under `--werror`, so the four dead abs/sign params forced a fan-out
>   through 7 files; safe on rule 4 because no Python f-string emits those calls.
>
> **⇒ NEW GATE CAPABILITY: `m14_gate` PHASE 1b — six FRACTIONAL viewpoints, byte-exact.** Before it,
> no gate in this repo could fail on either bug, which is exactly why both survived. One offset
> (`0x8000`) is labelled PARTLY VACUOUS in place: PJ-2 only diverges at a half unit for an ODD seg
> coefficient (R17). PJ-3 is therefore partly discharged — the *class* is now gated, though the
> per-macro kernel tests it asks for are still missing.
>
> ⚠ It proves AGREEMENT, not absence: both bugs need a boundary condition on top of the fraction,
> so **the probes remain the proof** and phase 1b is the regression net. No per-frame incidence was
> measured for PJ-1; do not quote one.
>
> **COST, both sides measured in one session:** median **27,722,912 → 27,850,134 (+0.46%)**; the four
> gate viewpoints moved ~2%, which is itself a demonstration of §0 (worst cases are not the frame).
> ALL of it is PJ-2's operand order — filed as **PJ-2b** with the weighted cost model and the
> exact-and-cheaper form `fixed_mul_lo(-a, |viewx|)`, DEFERRED TO BATCH 2 so it shares a build.
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

**The stop rule — OWNER OVERRIDE (2026-08-17): there isn't one on size.** "0.5% of the median is
alright too, small advances can reach bigger results when accumulated." So work the backlog to the
end; a 0.3% win is banked, not discarded. What still gets rationed is *build time*, not win size:

* **batch aggressively at the small end.** Below ~1% a finding does not deserve its own 25-minute
  build — collect ten of them into one batch and attribute with the emit-hash/nnls harness.
* **keep a cumulative ledger** so the accumulation is visible: a column of 0.3%s that reaches 4%
  is the argument for continuing, and the only way to see it is to record every one.
* **the real stop condition is the per-frame FLOOR, not the finding size** — see §4. Below roughly
  15M ops/frame the fixed image-reset cost dominates and further op wins stop converting into fps.
  Keep banking them (they still help a faster reset path later), but re-read §4 before spending a
  week on the last 2%.

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

## §4 THE BUDGET — AND THE PER-FRAME FLOOR THAT CAPS IT

Step A *saves*; Steps B and C *spend*. Without a ledger, A's wins vanish into B and C and nobody can
say where. So **every rung in B and C reports its median delta** the same way A's do, and a running
ledger tracks A-saves / B-spend / C-spend / net.

### 4.1 The target machine

Owner (2026-08-17): **"I plan on running it on a 300 fj/second machine."** Read throughout this
document as **300M fj/s** — the native C engine measures 144.6M–186.3M effective on this machine
today, so 300M is a plausible faster box. ⚠ If 300 ops/second was meant literally, a 29.4M-op frame
takes ~27 HOURS and nothing in this plan applies; confirm before relying on §4.2.

> ### ✅ MEASURED 2026-08-17 (B4.1 step 1) — THE FLOOR IS NOT PERMANENT. §4.2 BELOW IS SUPERSEDED.
>
> `scratchpad/dirty_census.py --m14 --things --exact --gatevps`, on the certified A0.3 binary. Exact
> walk of all 68,223,650 words, no sampling; its negative control (two pristine images, full walk)
> reports 0 differ; the four frames' op counts reproduce the certified gate figures to the digit.
>
> | frame | dirty words |
> |---|---|
> | (664,291) / (1272,−724) / (1869,479) / spawn | 5,366 / 3,910 / 4,323 / 3,891 |
> | **UNION of all four** | **6,685 of 68,223,650 = 0.0098% (~0.05 MB of 546 MB)** |
>
> Coalesced: **216 ranges covering 0.22 MB** (gap 256), or 41 ranges / 28 MB at gap 65536. The
> union is far below the sum (6,685 vs 17,490 if disjoint), so each frame dirties largely the SAME
> region — what a static bound needs. **The blanket memcpy is ~99.99% waste.**
>
> ⇒ At 300M fj/s with a free reset, the A0.3 median of 27.72M is ~92 ms ≈ **10.8 fps**, and 30 fps
> needs roughly a 10M-op frame. **Ops, not the floor, are what stand between this and 30 fps** —
> so Step A's long tail is worth working, which is exactly what §8 asked this measurement to decide.
>
> ⚠ NOT ESTABLISHED: this measured the dirty SET, not a working restore. The sub-millisecond reset
> is arithmetic from bytes-moved; per-range overhead is unmodelled. That is **B4.1 step 2** (change
> `fastrun`'s reset path and re-time it) and it is now the highest-value item in the document.
> ⚠ ALSO NOT COVERED: all four frames are `keys=0`. A MOVING tic runs the sim and writes player
> state and may dirty more — 6 seconds per frame to check, do it before designing the mechanism.
> ⚠ TOOL NOTE: the exact walk costs 6 SECONDS per pass. The sampler and its confidence interval
> were never necessary; prefer `--exact`.

### 4.2 ⚠ THE FLOOR: a fixed ~52 ms per frame that no amount of Step A removes

**MEASURED this session**, on a 68M-word image via `FjmRunner`'s C `freeze()`/`reset()` path:

```
core.reset() alone:  52.5 - 61.5 ms      <- fixed, independent of ops/frame
frame 2:  0.357s  51,653,980 ops  -> 144.6M fj/s effective
frame 3:  0.262s  48,876,228 ops  -> 186.3M fj/s effective
```

The program SELF-MODIFIES, so the host must restore the image before every run — run 2 on a dirty
image halts after ~9 ops. That restore is a ~545 MB memcpy and is memory-bandwidth-bound.
Consequences, at 300M fj/s:

| ops/frame | run | + reset | fps |
|---|---|---|---|
| 29.4M (median today, UNVERIFIED) | 98.0 ms | 52.5 ms | **6.6** |
| 20.9M (base-renderer floor, UNVERIFIED) | 69.7 ms | 52.5 ms | **8.2** |
| 13.0M | 43.3 ms | 52.5 ms | **10.4** |
| 10.0M | 33.3 ms | 52.5 ms | **11.7** |
| 0 (free frame) | 0 ms | 52.5 ms | **19.0 — THE CEILING** |

**Read that last row before planning Step A's tail.** There is a hard ~19 fps ceiling on this
machine's reset path, and below roughly 15M ops/frame the reset is more than half the frame:
halving 20.9M → 10M buys 8.2 → 11.7 fps, not 8.2 → 30. Op wins are still worth banking (they
convert fully once the floor moves), but **the floor, not the op count, is what stands between this
and a 30 fps game.**

### 4.3 THE LEVER — and it is a new work item nobody had costed

Reset copies the WHOLE image. The program only dirties part of it, and M12pp's xor-involution work
already exists to make per-seg constant blocks **self-restoring** — that is, much of the image
provably comes back on its own. So:

**B4.1 (NEW, high priority) — measure the dirty set, then restore only it.**
1. After one frame, diff the live image against the frozen snapshot and **count the differing
   words**. That number is the whole feasibility question and it is a cheap experiment.
2. If the dirty set is small and its extent is statically bounded, replace the blanket memcpy with a
   dirty-range restore (or extend the involution so the frame restores itself, which is the same
   idea one level down).
3. If it is large, the ceiling is real and the fidelity/resolution decision at A3 has to carry the
   whole fps gap on its own.

⚠ Do NOT start Step A's long tail before step 1 of this is done. It costs an afternoon and it
decides whether the tail converts into frames per second or into nothing.

### 4.4 The fidelity decision, still owed at A3

If the floor cannot move, 30 fps needs the frame to be free, which it will not be — so the honest
options are a lower resolution, a cheaper texture tier, a smaller sprite budget, or accepting
~10 fps. Make that call **explicitly, with numbers, at the A3 exit gate.** Do not let it emerge as a
disappointment in Step C.

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

## §6.5 GAPS FOUND AUDITING THIS PLAN AGAINST ITSELF (2026-08-17)

Beyond §4.2's floor, seven things this document needed and did not have:

**G1 — Nothing guards a win once it lands.** WR-1 happened because a correct widening silently
disabled a gate and no check noticed for months. Step A will create ~150 such opportunities. Add a
CHEAP, emit-time regression guard, run on every commit, no build required:
* the **stop census** — count gated nodes / pruned leaves / never-binding budgets
  (`scratchpad/_cr_wr1b.py` is the prototype) and fail if a count drops unexpectedly;
* the **emit hash** for the shipped config (`scratchpad/cr/emit_hash.py`, now with `--selftest`);
* a tracked `perf-ledger.json` holding the current median, the four gate viewpoints, assemble time
  and `.fjm` size, updated by whoever lands a rung.
Without G1, Step A is a bucket with a hole in it.

**G2 — Assemble time is an unbudgeted Step-A cost.** Builds are 21–25 min and the assembler is
~cubic in unrolled ops, so a plan with dozens of batches is dominated by assembly, not by thinking.
Two consequences: **track assemble time as a first-class metric per batch** (some findings —
SI-5's shared `fcall` leaf, anything moving unrolled code into a leaf — REDUCE it, so do those
early and make every later batch cheaper), and reuse the walker's `.fjm` cache so sweeps never
rebuild.

**G3 — A5 and B3 compete for the same span budget.** Batch 5 buys ops by *spending span* on dispatch
tables; B3 needs span for 9 levels of baked geometry against the flat limit (R4). These are the same
scarce resource and the document had them in different sections pretending otherwise. **Keep ONE
span ledger in DESIGN.md §1.2 across A and B, and price one extra level's span BEFORE Step A spends
span on tables.**

**G4 — No way to bisect a batch that regresses.** If a 10-finding batch comes back worse, you have
one number and ten suspects. Land each finding as its own commit inside the batch branch, with an
emit hash per commit, so a regression bisects by emission instead of by rebuild.

**G5 — Step C has no regression harness for BEHAVIOUR.** Byte-exactness gates a *frame*; it says
nothing about whether a monster chased you correctly. DESIGN's H7 already scopes a **replay**
facility at M14. Build it in B (a recorded input stream + expected end state), because by C the
oracle must simulate AI too and "the picture matches" stops being sufficient.

**G6 — The oracle becomes the bottleneck.** Every gate runs the Python oracle, and C makes it
simulate AI per tic. This session's `wad.py` fix bought 549× on one call and `RM-2`/`RM-4`/`RM-5`
are still open. **Treat oracle speed as a shipping constraint from B onward**, not as housekeeping.

**G7 — "Playable" has no acceptance test.** Define one in B, concretely, or the step cannot be
called done: *walk from spawn to the exit in real time, on the target machine, at ≥ N fps, with no
visual artefact and no host-side simulation.* Pick N at the A3 fidelity gate (§4.4).

Two smaller ones, recorded so they are not rediscovered:
* **DEG popping becomes visible once the player really moves.** The degradation knobs shed far
  detail adaptively; this repo has already fought smudge and pop bugs (the 73/260-frame owner-smudge
  class). With continuous motion, re-audit the knobs against motion, not against still frames.
* **Two-sided walls vs doors.** `--two-sided` is what makes door frames and ledge fronts read
  correctly, and it is byte-exact but ~6× slower. B2 ships doors; decide then whether door frames
  need it, and price it against §4.2's floor rather than against the op count alone.

**Explicitly OUT of scope** (named so nobody assumes them): sound, multiplayer, save/load games,
and 320×200. Skill levels are nearly free — thing flags already carry the skill bits — so fold them
into C2 if wanted.

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
| **a fixed ~52 ms per-frame image reset caps fps at ~19** | **§4.2** | measured; below ~15M ops it dominates, and Step A's tail stops converting to fps |
| restore only the DIRTY words instead of the whole image | **B4.1** (new) | the one lever that moves the ceiling; costs an afternoon to test |
| a perf regression guard (stop census + emit hash + ledger) | G1 | WR-1 is exactly what happens without it |
| assemble time as a tracked, budgeted metric | G2 | dozens of 25-min builds dominate Step A |
| ONE span ledger shared by A5's tables and B3's levels | G3 | they compete for the same scarce resource |
| per-finding commits + emit hash so a batch can bisect | G4 | otherwise a regressed batch has ten suspects |
| a replay/demo harness for BEHAVIOUR | G5 | byte-exactness cannot gate "did the monster chase me" |
| oracle speed as a shipping constraint | G6 | every gate runs it; C makes it simulate AI |
| a concrete acceptance test for "playable" | G7 | otherwise Step B has no done |
| DEG popping under real continuous motion | §6.5 | knobs were tuned against still frames |
| sound / multiplayer / save-load / 320x200 | §6.5 | named OUT of scope so they are not assumed |

---

## §8 SUGGESTED ORDER

`A0.1 → A0.3 → B4.1(step 1: count the dirty words) → A0.2 → B0` **then** `G1 (the guard)` **then**
`A2 batches 1–4` **then** `B1, B2` **then** `A2 batches 5–9` **then** `B3, B4` **then**
`C1 → C2 → C3 → C5 → C4 → C6`.

Rationale for the interleave:
* **B4.1 step 1 comes third**, right after the baseline. Counting the dirty words is an afternoon and
  it decides whether Step A's long tail converts into frames per second or into nothing (§4.2).
* **G1 before the batches**, because the guard is what stops a later rung silently undoing an
  earlier one — the WR-1 failure, which cost more than any single finding on the list is worth.
* **B0 before the optimization batches**, because the M14 tier is what Step A must optimize and B0
  is what makes it the real tier (§0).
* **C4 late**, because AI is the only item that can single-handedly blow the budget, and it should
  meet a frame Step A has already made as cheap as it is going to get.

---

## §9 STATE AT HANDOFF (end of session 2026-08-17)

### Committed and pushed on `m13opt3-early-out`

| commit | what |
|---|---|
| `4ff4d51` | CLAUDE.md's four working rules |
| `0b67376` | **CR round 1** — the WR-1 plane-gate fix (gated byte-exact ×4), the drawable-SSOT mirror fix, the TS-2 control rewrite, `THING_XORBY_FIELDS`, `--selftest` for `expand_check` + `emit_hash`, `wad.py` memoisation, the `slow` pytest marker |
| `540bccc` | this document |
| `6175cc2` | §4.2's measured per-frame floor + §6.5's seven gaps |

Verified at `0b67376`: `deg_gate` PASS byte-exact ×4; `pytest tests/host -q` = 245 passed,
1 deselected, 54.70 s; `alpha_check`/`expand_check`/`emit_hash` `--selftest` all pass.

### ✅ A0.1 IS DONE AND CERTIFIED (commit `b478897`)

The three (in fact **FOUR**) build configurations are now one. `src/doomfj/build.py` ships the
walker's picture — `wall_mode` WPX→**W1R** (the fourth divergence, and the most expensive: WPX is
+2–6M/frame) plus `stack_steps=True, bbox_cull=True, deg=True` — and `scratchpad/deg_gate.py`
certifies that same picture, with `bbox_cull=True` added so the wedge subtree cull is finally
covered by the repo's own proof.

`deg_gate` **PASS, byte-exact ×4**, measured 2026-08-17. Unifying did not cost ops, it SAVED them,
because the gate had never been running the cull the walker ships:

| viewpoint | before (gate without `bbox_cull`) | after | delta |
|---|---|---|---|
| (664,291,0x18000000) | 51,186,631 | **49,384,173** | −1,802,458 |
| (1272,−724,0x40000000) | 40,843,272 | **39,825,528** | −1,017,744 |
| (1869,479,0x80000000) | 48,666,231 | **45,917,740** | −2,748,491 |
| (−416,256,0x0) | 38,931,760 | **37,898,025** | −1,033,735 |

Emission grew as expected for the added gate code: walk 72,109→73,957 lines, main 55→58,
state 101→107.

**⇒ THESE FOUR ARE NOW THE WORST-CASE ANCHOR.** The pre-`bbox_cull` numbers elsewhere in this
document are retired: they belong to a picture nothing ships.

⚠ **STILL OWED for A0.1:** `build.py`'s span changed (W1R + the cull + V5), so
`python -m pytest tests/host -m slow` (~70 min, `test_build_wall_renderer_e1m1_flat`) must run and
assert `storage_mode == flat` under the raised limit. **It has NOT been run.** Do it before trusting
the shipped artifact.

### ⚠ NOT RUN: `scratchpad/dirty_census.py`

New, unrun: the §4.2/B4.1 dirty-word sampler with its R9 negative control (a pristine core compared
against itself must report 0% dirty). See step 2 below.

### ✅ SESSION 2026-08-17 (second): steps 1-3 below are DONE. State after them:

* **A0.1's owed span gate: PASSED.** `pytest tests/host -m slow` = `1 passed, 245 deselected in
  1783.21s (0:29:43)`. Flat, under 2^26, inside the sanity band, and the tier/features assertions
  now check all seven emit flags. ⚠ 29:43, not ~70 min — that figure was the pre-A0.1 WPX build.
  ⚠ The run proved the BOUNDS, not the span figure: the test asserted and printed nothing. A
  metrics print was added so the next run records span / `.fjm` bytes / assemble seconds.
* **A0.1 had a FAN-OUT MISS.** `deg_gate` got `bbox_cull=True`; `tests/host/test_e1m1_integration.py`
  (still asserting `WPX`), `m14_gate.py`, `m14_basegate.py` and `opprof.py` did not — the last two
  while their docstrings claim to mirror `deg_gate` "VERBATIM". All fixed, M14 cache key bumped to
  `m14_bin_things_cull.fjm` so the pre-A0.1 binary cannot be silently reused. `build.py`'s metrics
  now report all seven flags, so the next divergence is visible in `metrics.json`.
* **A0.3 — THE BASELINE EXISTS.** See the table below and `scratchpad/perf-ledger.json`.
* **B4.1 step 1 — DONE, exactly.** See the §4.2 banner: the floor is ~99.99% waste and removable.
* **A0.2 — DONE. Both PJ-1 and PJ-2 CONFIRMED as real bugs** (see the A0.2 banner in §1). Neither
  is fixed, and neither CAN be certified until the gate has a fractional viewpoint.

**THE A0.3 BASELINE — the number every Step-A rung is scored against:**

| metric | value | how |
|---|---|---|
| **median (warm)** | **27,722,912** | `m14_sweep.py <m14_bin_things_cull.fjm> --things`, 260 frames |
| mean / p90 / p99 / worst | 28,180,748 / 42,959,278 / 52,237,021 / 56,379,978 @ (2637,1247,0x80000000) | same |
| tail | under 20M 45/260 · under 26M 110/260 · under 30M 159/260 | same |
| median (cold) | 32,657,488 | same, `--cold` |
| 4 gate viewpoints (worst case) | 52,194,203 / 44,260,279 / 47,671,745 / 41,812,643 | `m14_gate.py --things 8`, PASS byte-exact ×3 phases |

Three things this baseline establishes that change how the backlog reads:

1. **The gate viewpoints sit between p90 and p99.** They overstate the typical frame by ~1.5–1.9×.
   With a 2.0× median-to-worst spread, **track median AND p90** — one number cannot represent it.
2. **The binding cache is worth exactly 4,934,576 ops on EVERY frame** — identical to the digit at
   min, median, worst and all four gate viewpoints. It is a fixed prologue over 75 runtime things
   (65,794 ops each), paid per THING and not per VISIBLE thing. That is ~18% of the median and it
   is the same shape as Batch 8's SI-1 empty-leaf skip — **re-price SI-1 against this** before
   accepting the reviewers' modelled 0.7–2.2%.
3. **The sweep's worst frame (2637,1247) is not a gate viewpoint.** The gate's worst is 52.2M; the
   sweep found 56.4M elsewhere. Consider adding it to the gate set.

### Then, in order (§8)

1. ~~**A0.3**~~ DONE. 2. ~~**B4.1 step 1**~~ DONE. 3. ~~**A0.2**~~ DONE (both CONFIRMED).
4. ~~**PJ-1/PJ-2 decision**~~ RESOLVED: owner chose fix-before-B0. Both fixed, gated byte-exact
   (`deg_gate` ×4, `m14_gate` phases 1/1b/2/3), median cost +0.46%. `m14_gate` phase 1b is the new
   fractional-viewpoint net. Open follow-up: **PJ-2b** (operand order, ~2% at gate viewpoints /
   0.46% at the median) → Batch 2.
5. **B4.1 step 2** — the dirty-range restore. Highest-value item in the document: it is what makes
   every Step-A op win convert into fps.
6. **B0** — wire the sim. 7. **G1** — the regression guard (`scratchpad/perf-ledger.json` started).

### Where everything lives

* findings: `scratchpad/cr2/findings/*.md` (158; round 1 closed 8)
* the gate: `scratchpad/deg_gate.py` · the median: `scratchpad/m14_sweep.py` · the static gate:
  `scratchpad/m14_basegate.py` · attribution: `scratchpad/opprof.py`
* stop census prototype: `scratchpad/_cr_wr1b.py` · TS-2's mutation control:
  `scratchpad/_cr_ts2_neg.py` · CR tools: `scratchpad/cr/{alpha,expand}_check.py`, `emit_hash.py`
* memory: `cr-round-2026-08.md` (the backlog), `m145-handoff.md`, `perf-campaign.md`, `fj-lessons.md`
