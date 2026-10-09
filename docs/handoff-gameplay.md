# Handoff: the fully playable E1M1, under 22M ops/frame

**Status ({{SHIP_DATE}}): THE MILESTONE IS DONE -- the fully playable E1M1 SHIPPED as `build/doom_e1m1_blocked53.fjm`
(sha256 `324e3d2281d5c7e1`; M7 P8a + P8, one build, PR {{PR}}).** Phases 0-7 shipped as before (P3.3 + P3.4 as
blocked46, P4 as blocked47, P5 as blocked48, P6 + P7 as blocked51); P8a (the dying view sinks, knockback, infighting, D3
a / b, the follow-ups) and P8 (the ship) as blocked53. The frozen set is **v7** (15,825,592, 6,174,408 under CAP-22);
the 22M cap replaced the 20M target (D1). What stays open is `{{NEW_ISSUE}}`; the next milestones are M6 (ship) and M4
(more levels, 1-3, deferred) -- `CLAUDE.md`. Everything below is the whole plan, as the owner approved it, updated with
phase 0's measurements. It replaces nothing:
`docs/plan-gameplay.md` is the record of how the plan was made (research missions, red team,
decision rounds); this file is what to execute. Phase 0's evidence is committed on branch `gameplay-p0`
(merged into main by the phase-0 PR).

Read first, in this order: this file; `docs/ship-gate.md` (the standing number and the ship
procedure); `CLAUDE.md` (the five rules). Then the design notes of the rung you are on (section 12).

---

## 1. The goal, and how it is measured

The owner, 2026-09-26: moving monsters, chasing, fighting, shooting, damage and health, dying --
**the fully playable game -- at no more than 22M ops/frame, "it can't be above it"**, designed with
FlipJump-specific knowledge.

| | target | how it is measured |
|---|---|---|
| **speed** | **(mean + p80)/2 of per-run ops/frame <= 22,000,000** | the FROZEN combat scenario set -- v2 (`scratchpad/gp/scenarios/combat_scenarios_v2.json`) at the start, re-planned through v3 .. v6 as the rules grew, **v7 at the ship** (`combat_scenarios_v7.json`, keys `33f95fdbbd684f53`, frozen by the owner on blocked53's B0, 06be25f): 11 runs x 100 frames at skill hard, starting from checkpoints across the level, driven by `scratchpad/gp/b0_scenarios.py` (the binary) against the model (the oracle) |
| **size** | <= 42% of 2^27 words (56,371,445) -- 35% at the start, 40% from P4.0 (`docs/gp-combat.md` C2), 42% after P5 (the owner, 2026-10-04) | `scratchpad/12m/poolmap.py` / gamespeed's size line |
| **correctness** | byte-exact AND state-exact against the oracle, on every frame of every gate | the state probe (`scratchpad/gp/probe.py`) + the gates (section 9) |
| **scope** | the fully playable level of section 3 | the gates' event counters |

The baseline B0 -- blocked27, the shipped binary, driven along the same routes in a static world --
is **17,760,774** on v2 -- and **18,107,313** once the collision of strafe frames is priced (blocked27
cannot strafe; a forward-step proxy measures it) -- the honest baseline. (v1, which moved on only
29% of frames, was 14,972,920.) The owner froze v2 and B0 on 2026-09-26: nobody
building the game re-grades the set; a new version needs the owner.

**The freeze rule, when the model changes** (it will: P1.6, P3-P7 edit the model files the set
hashes). The freeze pins the KEYS, the B0 and what they reproduce -- not source bytes.
- CAP-22 drives the candidate binary with the frozen keys and checks it state-exact against the
  CURRENT model, the oracle that binary mirrors.

By what changed (the tool is `python scratchpad/gp/scenarios_v2.py`; the same rule is in
`scratchpad/gp/scenarios/README.md`):
- a pure refactor of a hashed model or census file: `--rehash "<reason>"` re-records the hashes,
  only while the replay still reproduces every frozen pose, digest and drawn population
  (F1/F3/F4/F5 hold) AND the checker (`scenarios_v2.py`) is unchanged; each rehash is logged in
  `rehash_log`;
- a CHECKER change (`scenarios_v2.py` itself): `--freeze --approver "<its reviewer>"
  --approval-record "<where>"`, only when the re-plan gives identical keys AND the current code
  reproduces every recorded pose, digest and drawn population (F1/F3/F4/F5) -- a reviewable event.
  The owner's approval of the set (`owner_approval`) is never re-stamped; the previous freeze record
  goes to `freeze_history`;
- SCHEMA GROWTH (the owner, 2026-09-28, "Allow growth"): a change that ADDS state cells moves the
  final digest (it hashes every field) and nothing else. `--freeze --grown-from <the git ref the set
  was frozen at> --approver "<its reviewer>" --approval-record "<where>"` records the new digests
  only when every pose and drawn population reproduces (F1/F4/F5, F3's poses), and THE WITNESS
  (`scratchpad/gp/state_dump.py`) holds every PRE-EXISTING cell equal after every frame: it steps
  every run on the tree at the ref (`git archive`d) and on this one, re-keys a door field by door
  sector and a sound field by sector, and requires the ref's tree to reproduce the recorded digests
  (it is the frozen model). The added fields, the re-keyed ones and the previous digests go into the
  freeze record (`schema_growth`). As for any re-freeze, the re-plan must give identical keys. A
  changed old cell is a BEHAVIOUR change, as above;
- a BEHAVIOUR change (anything that moves a replay: a rule, a fix, a picture rule): a NEW VERSION in
  a new file -- `--plan --file <new>` (the planner refuses a frozen file), B0 re-measured on it
  (`b0_scenarios.py --file <new>`), then `--freeze --file <new> --approver "the owner"` with the
  owner's words (a first freeze refuses any other approver).

The refusals are `--selftest` controls: R1 the untouched set is accepted with nothing to re-record;
the rehash refuses R2 a behaviour change (strafe 13 -> 12) and R3 a checker change; the re-freeze
refuses R4 a picture-rule change (DEG_SOFT_MON 4 -> 2); R5 a clean re-freeze keeps the owner's
approval and names its own approver; R6 a first freeze by anyone but the owner is refused; R7
`--plan` refuses the frozen file. The growth comparison's controls: SG1-SG2 accept the same state and a grown cell with
the doors and sound nodes renumbered; SG3-SG7 refuse an old cell changed on one frame, an old door's
cell changed, an old field gone, a non-door field reshaped, a sound alert moved to another sector.

There is no "same keys, new poses" path: F3 and `b0_scenarios` both compare against the frozen
poses, so CAP-22 cannot run on a model whose behaviour moved until the new version exists.

Single frames are NOT capped (decision D1): blocked27 already has frames at 32.4M (two-sided wall
storms), and the frozen set's heaviest run, R0-west-hall, averages 22,018,124 on blocked27 alone
(`scratchpad/gp/scenarios/b0_v2.log`); they are reported as stress, not gated.

---

## 2. Every decision, in one table

| id | decision (owner, 2026-09-26) |
|---|---|
| D1 | the cap is on (mean + p80)/2 of the combat set, not per frame; the 22M replaces the 20M target in CLAUDE.md, ship-gate.md and gamespeed's `SPEED_TARGET` when the combat game ships |
| D2 | runs start from CHECKPOINTS across the level (injected states); the set and B0 are frozen by the owner |
| D3 | compositor rules for gameplay: **a** drops and effects ordered before monsters; **c** corpses count as scenery; **d** runtime things inside a leaf drawn in depth order; **e** "seen" and the aim window recorded at column-open time, before the degradation budgets; **b** only for projectiles and barrels (exempt from the soft budgets) |
| D4 | one DOOM tic per frame (fights run at ~32-38% of DOOM's real-time speed, consistently) -- **changed by the owner's playtest (2026-10-05) for the monsters (with their pools) and the player's weapon: 2 tics a frame** (`world.MONSTER_TICS_PER_FRAME`, `WEAPON_TICS`; P6 + P7) |
| D5 | the simplifications: no knockback; no infighting (monster shots and fireballs pass through monsters and barrels); 2D projectiles; P_NewChaseDir capped at a few tries (the owner's words; the model uses 6); rounded diagonals (8/6, 10/7); **K = 6** heavy monster actions per tic (raised from 3), deterministic deferral; monsters open plain doors when a move fails in the door's use box; a fireball pool of 8 (a full pool fizzles); puffs/blood capped at 2; nukage 5 damage every 32 tics; no sound, no spectre fuzz, no weapon bob or raise/lower animation (the timing stays), no whole-screen fire light, no status-bar face |
| D6 | the native-list sprite bank; option A for the HUD: **the screen stays 160x100, a 16-row status bar at the bottom, a 160x84 3D view** (DOOM's layout at half resolution), with a flipjump device option so dittos do not copy the bar |
| D7 | skills easy 17 / medium 29 / hard 46 monsters, chosen in the menu as in DOOM; the image holds the union (53); the budget is sized on hard |
| D8 | the ship rule (written into `docs/ship-gate.md` section 2a): class S (pixels identical) = today's ship gate, B SLOWER never ships; class F (a feature) = byte- and state-exact gates + CAP-22 + size, msframe recorded as the price, ~90 ms/frame a tripwire that must be explained |
| D9 | flipjump changes: a branch off `1.5.1`, a PR, merged into `1.5.1`; `1.5.1` is NOT merged to main and not published |
| D10 | DOOM's original rndtable, folded into each call site's outcome table (measured the cheapest RNG, 82-96 ops) |
| D11 | every map mechanic in scope: lifts, the floor switch, key doors, walk-over and blazing doors, the exit; the lift spike's DEFAULTS, which the owner did not overrule (not an explicit decision): door-style timing 9/26/9 frames, an instant floor switch, 16-unit steps |
| D12 | E1M1 only |

---

## 3. The scope: what "fully playable" means

**Monsters** (Freedoom E1M1; per skill easy / medium / hard): zombieman 9/4/5, shotgun guy 2/10/13,
imp 4/10/18, demon 2/5/9, spectre 0/0/1 -- 17/29/46. Plus 22 barrels. Waking by sight and by sound
(ambush monsters need sight); chasing; melee and missile decisions; the attacks of all five types;
pain; death, corpses, drops (the clip; the shotgun, which on hard is the only shotgun); gib deaths
are in the model, drawing their frames is optional (plan section 2, C list).

**The player**: fist, pistol, shotgun (from drops), chainsaw (sector 139); berserk (easy and medium
only); ammo and its caps; switching on keys 1-4; fire on ctrl (held: refire reads it); strafe on
`,` / `.`; blocked by solid things (monsters, barrels, solid decor -- today the player walks through
everything); every pickup with DOOM's caps; armor; damage and pickup palette flashes; death, then
use restarts the level; NEW GAME from the menu resets the level with the chosen skill.

**The map**: the 13 existing doors plus the blue-key check on the two blue doors (sectors 51, 71;
today they open without the key), the blazing door (84), the two walk-over doors (77, 145, stored
shut today), two lifts (98, 103; they gate 31 sectors with 16 of the hard monsters, 16 barrels and
the blue key), the floor switch (linedef 753: sectors 76, 126, 129), the exit switch (linedef 407,
then a "level complete" frame, then the menu), nukage (3 sectors), doors reversing on a thing.

**The screen**: a 16-row status bar (health, armor, ammo, key), redrawn only when a value changes;
the weapon drawn over the 3D view; animated, rotated monsters; fireballs, puffs, blood.

---

## 4. What phase 0 built (all committed; each tool has a --selftest with a negative control)

| tool | what it is | run |
|---|---|---|
| `scratchpad/12m/profx/` | the attributing profiler: an instrumented `_fjcore` charging every wflip-chain, pool, stl and data-read op to the doom code that called it | `python scratchpad/12m/profx/profx.py --selftest`; README reproduces the cost sheet |
| `scratchpad/12m/pinreport.py` | per build: are the 20 hottest shared words still pinned; pool declines | `python scratchpad/12m/pinreport.py --fjm build/<x>.fjm ...` (see its --help) |
| `scratchpad/gp/probe.py` | reads/writes named cells of the RUNNING binary each frame (state-exact gates, injection) | `python scratchpad/gp/probe.py --selftest --demo` |
| `scratchpad/gp/b0.py`, `b0_scenarios.py` | drives a binary through viewpoints or the scenario set, per-frame ops, state and pixel checks | `python scratchpad/gp/b0_scenarios.py --selftest` |
| `src/doomfj/gamedata.py`, `rng.py`, `world.py`, `combat.py` | THE MODEL = the oracle of the gameplay: DOOM's data (Chocolate Doom 895f581c, cross-checked against linuxdoom-1.10), the rndtable, a schema-first world state, monster AI, combat | `python -m pytest tests/host -q -k gp` (140 tests) |
| `scratchpad/gp/model_run.py` | runs the model with scripted keys, dumps per-tic state | `--help` |
| `scratchpad/gp/scenarios_v2.py` | the autopilot and the FROZEN set v2: `--validate` (the criteria and the freeze check), `--rehash` and `--freeze --approver` (the freeze rule, section 1) | `python scratchpad/gp/scenarios_v2.py --validate` (`scenarios.py` is v1's, kept as the record) |
| `scratchpad/gp/census*.py` | the model wired into the oracle renderer; the compositor census and the fight line | `python scratchpad/gp/census_control.py` |
| `scratchpad/gp/probes/s6/` | fj micro-probes of the primitives | `python scratchpad/gp/probes/s6/fjprobe.py --selftest` |
| `scratchpad/gp/probes/sprite/` | the cheaper sprite column (v1/v2), pixel checks and costs | `python t2_emit.py`, `t8_pipeline.py <frame>` |
| `scratchpad/gp/lift/` | the lift budget (reproduces blocked27's 222 plane ids first) | `python scratchpad/gp/lift/lift_budget.py --fast` |

Design notes written in phase 0 (section 12 lists them by rung): `docs/gp-pin-protection.md`,
`docs/gp-sprite-column.md`, `docs/gp-partial-ditto.md`, `docs/gp-lift-spike.md`,
`docs/gp-aim-window.md`.

---

## 5. The measured basis (blocked27, MEASURED 2026-09-26 by `profx`)

Per frame over gamespeed's 1,000 frames: the render walk 12,986,630 (85.4%); **collision
1,475,186** (9.7%; one player move try ~613K); sim.bind_things 438,808; m1_reset 249,325; the rest
~50K. Per call: `hex.ptr_index` 846; pointer `read_byte`/`write_byte` 260/504; `read_table_packed`
~404/byte; `hex.mul_lo 8` 825; `fixed_mul_lo 8,4` 3,381; `hex.div 8` 157K; point location 30.7K
mean (180K max); `thing_load` 19.5K; project+record a runtime sprite 30.2K (baked 15.4K); a sprite
column's EMISSION ~30K, and end to end (record + load + emission) ~42-54K; one full column of
output 15.9K (~159 ops/pixel).

Phase 0's probes (pooled like the ship build; 0.79-1.06x of in-game costs): a jump on an index into
per-entity stubs **68-102 ops** (vs 0.9-2.9K by pointer); a D4 lookup 47-100; a 27-nibble window
copy 403; the rndtable composed per call site 82-96; a baked candidate-line test 238-1,568 (a
diagonal line past its box 14-16K); a 32-unit cell of a 16.16 position 137 (46 when the jump macro
is declared SAFE); point location from a cell's start node 5.9K (8x cheaper than a full descent);
the octant classifier 3.2K; AproxDistance 1.0K; an aim-window write 27-62.

---

## 6. The FlipJump rules for gameplay code

1. **A compile-time address is cheap; a runtime index is not.** Per-entity state lives in fixed
   cells with per-entity code stubs; a runtime index selects CODE (a jump through a table into the
   entity's stub, ~70 ops), never DATA through `ptr_index` + `read_byte` (~1.1K).
2. **Constant data in D4 dispatch tables**, never `read_table_packed`.
3. **No runtime multiply or divide in gameplay code**: octant comparisons, AproxDistance, per-call-site
   outcome tables. `hex.div` and `fixed_mul_lo` stay out.
4. **Spatial questions are precomputed grids** (collision cells, the point-location start node,
   pickup cells, projectile wall cells), each proven exact on the host by interval arithmetic over
   closed cells at 16.16, with a mutated-entry negative control.
5. **Every new jump/dispatch macro is declared SAFE in `build_blocked.py`'s `SAFE_TABLE_MACROS`**,
   or the pool pins its cell and makes it dearer than no pool at all (measured: 137 vs 46).
6. **Bounded by construction**: K = 6 heavy acts per tic, fixed pools, a per-act line-test budget;
   the simulation's worst case is asserted at emit time.
7. **One schema** (`world.py`) drives the fj declarations, the M1 persist set and the probe; new
   macros carry NO `@`-local data cells (checked statically -- a restore-set hole hangs the game).
8. **One source per table**: the emitter and the oracle read the same Python tables.
9. **A blocked build's state cell holds `base | v<<6`**, not `v<<6` (the probe writes only the
   value field); every gate that runs a prebuilt game-tier binary (m1, m2_std, m3, m5, m2_r3, m2_r4 gates,
   m2_pass_probe) and every phase-0 tool renders the oracle through `reference_model.GAME_RENDER_KW`
   (sky included -- five gates lacked
   it until PR #87), and `tests/host/test_oracle_calls_in_step.py` scans every gate for it.

---

## 7. The design, by subsystem

**7.1 World state and scheduling** (`world.py`). Per monster ~27 nibbles at fixed addresses. Each
tic one slot per monster: tics != 0 decrements; a READY monster's cheap action (A_Look, A_Fall...)
runs in its slot; a heavy one (A_Chase, attacks) takes one of K = 6 slots via a rotating cursor --
copy the monster's cells into a fixed window (403 ops each way), run one shared leaf, copy back.
The rndtable is a D4 table, one index cell per stream (world, player, fx, one per monster).

**7.2 Waking and sight.** Sight = "seen" recorded by the renderer at column-open time (D3 e), or
REJECT-visible within 128 units for waking only. Attacking needs real sight: "seen", or for a near
monster the renderer did not draw, a short trace over the collision cells between it and the
player. Sound: precomputed regions, doors as runtime edges.

**7.3 Movement, collision, leaf lists.** 32-unit collision cells per radius class (player 16,
monsters 20 and 30): candidate line lists (E1M1: ~0.99 lines per position test, `scratchpad/gp/probes/s6/linemix.py` ->
`linemix_out.txt`; the ~10K per try below is derived from it, UNVERIFIED) in D4 rows, plus
per-direction "no line can block" verdicts for the monsters' 8 directions; solid things as boxes in
the cells. One player try ~10K derived vs 613K today. Point location jumps to the cell's start node
(5.9K). Leaf lists (`sshead`/`thnext`) become persistent and per-move: a thing that changes leaf is
unlinked and re-inserted in the list's order; `bind_things` goes.

**7.4 Combat** (`combat.py`). The player's shot reads the AIM WINDOW (columns 72-88), which records
per column the nearest shootable living thing whose RADIUS BOX covers the column and is not behind a
nearer wall (`docs/gp-aim-window.md`); pellets and refire take their column and damage from
per-call-site tables; a hit jumps into the target's stub. Monster hitscan: sight + distance + a
precomputed spread table. Fireballs in an 8-slot pool (64-unit wall cells). Damage, pain, death,
drops, pickups (a 64-unit pickup grid), barrels (radius damage, chains), the blue key.

**7.5 Map mechanics.** Doors as today plus the key check, walk-over and blazing doors; lifts and
the floor switch as runtime FLOORS (`docs/gp-lift-spike.md`: 243 of 255 plane ids, +0.02-0.1M ops (UNVERIFIED),
0.18% size -- `scratchpad/gp/lift/lift_budget_out.txt` prints 243 pids and ~241K words = 0.179%;
lifts cannot crush on E1M1); door reversal on things; the exit.

**7.6 Drawing.** The v2 sprite column (`docs/gp-sprite-column.md`: pixel-identical, ~40% cheaper
end to end); the native-list sprite bank (all frames, 8 rotations, ~1.96M words replacing 2.92M -- UNVERIFIED:
`art_budget_out.txt` prints the static bank 124,768, the monsters 1,065,120 and the effects 25,312;
the rowmap/patch tables ~0.15M, the weapons ~0.4M and the HUD ~0.19M are the sprites/HUD mission's
estimates, recorded only in the session transcript);
rotation by the octant classifier; D3's compositor rules; the weapon drawn over the view with the
partial-ditto device option and the status bar with its ditto option (`docs/gp-partial-ditto.md`:
two additive 0x0B tokens); the HUD digits from a 512-entry table, redrawn on change.

**7.7 Restart, NEW GAME, exit.** A second reset block returns every persisted cell except mode and
held keys to its level-start value for the chosen skill; the lnrow bits M2 patches (door blocking)
must be driven back too.

---

## 8. The budget (combat set v2, (mean + p80)/2)

| line | effect on (mean + p80)/2 | source |
|---|---|---|
| B0 v2: blocked27 along the same routes, static world | **17,760,774**; **18,107,313** with strafe's collision (proxy) | MEASURED (S4) |
| the sprite side: decided D3 + the v2 column + the skill filter | **-1.13M** (fights alone +0.27M; the v2 column and the filter pay for them) | S5 on v2 (census_out/s4v2) |
| the aim window | +0.04M (UNVERIFIED) | gp-aim-window: measured unit costs x measured counts |
| fireballs drawn (the set draws none; a drawn one is ~1.8M in its frame) | reserve +0.1 .. +0.3M | S5 staged fights |
| monster AI (1.83 heavy acts/frame measured on v2 x the model's cost) | +0.08 .. +0.1M | S4, S3a, S6 |
| combat logic, the weapon overlay, effects, lifts, the HUD | +0.2 .. +0.4M | models (S3b, S6b, S7) |
| reclaim: persistent lists / per-move rebind | -0.44M | MEASURED cost of bind_things |
| reclaim: player collision on the cells (v2 moves on 87.5% of frames) | -1.0 .. -1.4M | S6 derived |
| reclaim: heat-ordered pool indices | -1.27M | ESTIMATE (S8); a build must confirm |
| **projected, before placement** | **~14.3 .. ~16.4M** from the proxy baseline; ~17.8M without P1's reclaims; ~19.4M with no reclaim at all and today's sprite column | |
| placement (the blocking pass re-rolling its pins) | +/- up to ~6M unless pins are protected | S8 |

**The reading.** The gameplay's own cost is ~1M on the frozen set, and the sprite work is more
than paid for by the v2 column and the skill filter: every projection is under 22M, most under 17M.
The cap is not tight. The one threat that can consume the
margin is placement (the blocking pass re-rolling its pins, up to ~6M), so pin protection is P1's
first rung.

Size: 32.23% today; the native bank takes it to ~31.5% (UNVERIFIED, from the ~1.96M above); the AI, combat, collision cells and lifts
add ~1.5-2.4M words (AI 0.6-0.8, combat 0.5-1.0, collision cells 0.1-0.3, lifts ~0.26):
**~32.6-33.3%**, under 35%.

---

## 9. Verification and measurement

- **Gates**: `m2_std_gate`, `m3_gate` (both now with `sky=True`), and the new `combat_gate.py`
  (P3-P7) in their style, state-exact through the probe, with three scripts -- `fight`, `hurt`,
  `die` -- whose event counters must be non-zero and whose `--selftest=rng|order|damage` must fail
  at a stated frame.
- **CAP-22**: `b0_scenarios.py` drives the candidate binary through the frozen v2 set; the binding
  statistic must be <= 22,000,000; every 10th frame's state must equal the model's.
- **Every build**: the pin report (`pinreport.py`) and pool declines; a label-coverage report across
  gates and fuzz (rare paths -- restart, exit, a full pool, barrel chains, deferral -- must run in
  some gate); the static no-`@`-local-data check on new macros.
- **The ship rule** (D8): class S (pixels identical) through `docs/ship-gate.md` as today; class F
  on the exactness gates + CAP-22 + size, msframe recorded.

---

## 10. The phases

Every rung: FAIL-first tests (R1); its gate; a ledger row (ops attributed to its own code by
`profx`, the binding delta on v2, size, ms/frame, the pin report); kill criteria DECLARED BEFORE it
starts (attributed ops > 1.25x its budget -> redesign; the cumulative projection > 22M minus the
remaining budgets minus a 15% reserve -> stop for a scope decision). A PR per unit of work, the
crist CR loop, CI, merge. Naming (cr-rules R7): this milestone is **M7** -- branches
`m7-<rung-slug>` (e.g. `m7-pin-protection`), PR titles `M7: <feature>`.

### P1 -- reclaim and foundations (NEXT)

| rung | what | class | budget | builds |
|---|---|---|---|---|
| **P1.1 pin protection** -- DONE 2026-09-27 (blocked28 ships; `docs/gp-ledger.md`) | flipjump (a branch off 1.5.1): BlockPool takes a `heat=` list -- hot groups placed first, heat-ordered indices, always pinned; inert without it (`docs/gp-pin-protection.md`). Doom: `build_blocked.py --pin-heat <profx hot list>`; rebuild blocked27's program with it | S (same program, same pixels) | ESTIMATE -1.27M (heat-ordered indices); the point is stability | 1-2 |
| **P1.2 player collision cells** -- DONE 2026-09-27 (blocked29 ships; `docs/gp-ledger.md`) | 32-unit cells, candidate lists (interval arithmetic over closed cells at 16.16), line stubs that xor each row's constants around ONE shared line test (not D4 rows: `docs/gp-collision-cells.md`), SAFE jump macros; exact against today's line tests | S | -1.0 .. -1.4M (MEASURED -1.58M) | 1-2 |
| **P1.3 persistent leaf lists** -- DONE 2026-09-27 (blocked30 ships, NOT SEPARATED: foundation for P3; `docs/gp-ledger.md`) | `sshead`/`thnext`/positions persistent (baked to the spawn lists), per-move rebind, `bind_things` deleted; monsters still inert | S | -0.44M | 1 |
| **P1.4 the v2 sprite column** -- DONE 2026-09-27 (blocked31 ships, -0.60M on v2: under kill criterion 5's 0.8M, shipped by the owner's decision with a follow-up after phase 1; `docs/gp-ledger.md`) | `docs/gp-sprite-column.md` (v2; needs `sprbank` 4096-bit aligned -- add the build check) | S | with P1.5: -1.40M on the frozen set (S5, (iii) -> (iv)) | 1 |
| **P1.5 skill filter + skill menu** -- DONE 2026-09-28 (blocked32 ships, class F: -0.42M on v2, the gates byte- and state-exact; `docs/gp-ledger.md`) | the build spawns per skill; NEW GAME asks easy / medium / hard and starts from that skill's level-start state (the full restart block is P7) | F | -0.3M | 1 |
| **P1.6 the native-list sprite bank** -- DONE 2026-09-28 (blocked33 ships, class F: +0.14M on v2, inside its estimate; combat set v3 frozen by the owner; `docs/gp-ledger.md`) | all monster frames and rotations; the rowmap as a dispatch (it must not break v2's narrow reads) | F if any pixel moves | size -0.97M words | 1-2 |

P1 ends when all six ship -- **P1 DONE 2026-09-28** (blocked33 is the shipped binary; the frozen set is v3). The ship gate's standing number moves with P1.1-P1.4 (class S). A class-S
rung that measures NOT SEPARATED may still ship with the stated reason "foundation for P3" (the
ship gate's own clause) -- never one that measures SLOWER.

### P2a -- doors, keys, exit
The blue-key check (and the key's sprite and pickup), walk-over and blazing doors, the exit switch
and the "level complete" frame, NEW GAME resetting the level. Class F. Budget +0.05M.
**P2a.1 doors and keys DONE 2026-09-29** (blocked34 ships: v3 +426, `docs/gp-ledger.md`).
**P2a.2 the exit and LEVEL COMPLETE DONE 2026-09-29** (blocked35 ships: v3 +59,973, all placement,
msframe NOT SEPARATED; `docs/gp-exit.md`). **P2a is done**; P2b (lifts, the floor switch, door
reversal; `docs/gp-lifts.md`) next.

### P2b -- lifts and the floor switch
`docs/gp-lift-spike.md`'s rung plan: host-only work and FAIL-first tests, 1-3 render-tier builds,
then two game builds. Budget: ops <= +0.1M, size <= +0.35M words, plane ids <= 243.
**P2b DONE 2026-09-30** (blocked37 ships; `docs/gp-lifts.md`, `docs/gp-ledger.md`): gamespeed
-102,887, plane ids 254, size +1.37M words (OVER the +0.35M budget; the owner: ship). **The CAP-22
set is v4 from here** (v3 but R2-spectre-corridor, which rides lift 103), frozen by the owner.
**Phase 2 is done**; P3 (monsters alive) next.

### P3 -- monsters alive
First a build that EMITS every new table and calls none of it -- its delta is the pure placement tax.
**P3.0 DONE 2026-09-30** (blocked38 ships, class S: the tables' placement tax +54,098 on gamespeed, msframe NOT
SEPARATED; `docs/gp-monsters.md`, `docs/gp-ledger.md`).
**P3.1 DONE 2026-09-30** (blocked40 ships, class F: the monsters' state machine and views in the `idle` mode;
+243,680 on gamespeed -- over its +0.15M budget, the per-drawn-monster row select -- msframe NOT SEPARATED).
The owner chose the "seen" sight rule and the set v5 (`docs/gp-monsters.md` 8.2); P3.2 ships in three rungs, each a
model mode (8.3). **P3.2a DONE 2026-10-01** (blocked43, class F: the monsters wake and turn; +146,045 on gamespeed,
size +1.33M words -- over its budget, the unrolled slots' tables -- msframe NOT SEPARATED; v5 FROZEN, the CAP-22 set
from here). **P3.2b DONE 2026-10-02** (blocked44, class F: the monsters move -- P_Move on their own cells, NewChaseDir, the relink, P_ChangeSector, monster doors; +366,657 on gamespeed, size +5,017,552 words -- over its +2.5M budget -- now **33.38% of the 35% target**; msframe B SLOWER: median x0.934). **P3.2c DONE 2026-10-02** (blocked45, class F: the monsters decide to attack -- the melee and missile decisions, A_FaceTarget, the attack states' draws without damage, the exact near LOS; +9,795 on gamespeed, -211,944 on v5, size +726,572 words -- now **33.92% of the 35% target**; msframe NOT SEPARATED: median x1.000; P_ChangeSector inside the `lvdone` guard, 796cdcc). **P3.3 + P3.4 DONE 2026-10-03, one rung** (blocked46, class F, the owner united them: a leaf's runtime things drawn nearest first, `sim.thing_pass_depth`; the key-map HELP screen from the main menu's HELP item or H, E a second use key; +780,607 on gamespeed, +472,852 on v5, size +355,886 words -- now **34.19% of the 35% target**; msframe NOT SEPARATED: median x0.958). **PHASE 3 IS COMPLETE**: summed from the ledger's rows, +1,600,882 on gamespeed against its +0.3M budget (`docs/gp-ledger.md`, Phase 3 summed). D3 a (drops and effects before monsters) moves to P4/P5, which create them. **P4 (the player's combat) is next**, with the owner's key map (approved 2026-10-02, P4 below).
**P3.4 the key-map HELP screen** (the owner, 2026-10-02; `docs/gp-help.md`, class F, kill criteria in
`docs/gp-ledger.md`): a baked help frame listing only the keys that work today, opened from the main
menu's new HELP item (or h) and from the world (h); 'e' a second use key. P4 updates it (below). SHIPPED 2026-10-03 with P3.3 as blocked46 (`docs/gp-ledger.md` P3.4).
Then the state machine, K-slot scheduler, RNG, animation and rotation, waking, chase on the cells,
thing collision, per-move rebind in use, doors opened by monsters and reversing on them, D3's
compositor rules. Gate: `fight` (partial), fuzz. Budget +0.3M. (Summed at the phase's end: +1,600,882, OVER -- `docs/gp-ledger.md`, Phase 3 summed.)

### P4 -- the player's combat
Input (fire, 1-4, strafe; the device already sends the keys), the weapon state machine, the aim
window, monster pain/death/corpses/drops, the weapon overlay and the status bar (the flipjump
device PR: the partial-ditto tokens and the bar's ditto). Gate: `fight`. Budget +0.6M.
**The owner's target key map (approved 2026-10-02)**: move W / S and UP / DOWN; turn the LEFT / RIGHT
arrows; strafe A / D and , / . (**A / D move from turn to strafe in P4**); use SPACE or E (E landed in
P3.4); fire CTRL; weapons 1-4; menu ESC / ENTER; help H. P4 re-binds `kb.poll` to it and updates the
help screen with it (`menu.HELP_CLUSTERS` / `HELP_ROWS` / `HELP_KEYCODES`; `test_keyboard_input.py`'s
`test_the_help_screen_lists_exactly_the_keys_that_work` holds the screen and the poll together, both
directions) -- `docs/gp-help.md` section 4.
**P4 DONE 2026-10-04, one rung** (blocked47, class F; `docs/gp-combat.md`, `docs/gp-ledger.md` "P4 united"): the owner's
"merge small rungs" put P4.0 (the 160x84 view under a 16-row status bar, the weapon drawn; flipjump#364's partial
dittos, 1.5.1 >= `1cd6e0c`), P4.1 (the key map above, strafe, the psprite machine for fist / pistol / shotgun /
chainsaw, ammo), P4.2a (the aim window, the shots, monster damage, pain, death, A_Fall) and P4.2b (the noise alert,
A_Look's sound branch, ambush) into ONE build. +160,368 on gamespeed (15,403,663), +291,097 on v5 (15,851,173) --
both inside the phase's +0.6M, but P4.0's own kill criterion 4 (v5 not to rise by more than 0.1M: the 84-row view's
saving was the premise) is EXCEEDED and recorded; size +86,672 words, **34.25% against the size target, now 40%**
(raised in P4.0, gp-combat C2); msframe NOT SEPARATED (x1.000, taken beside the owner's fullscan.py with
`--ignore-busy`). Drops are not in P4 (P6, per the P4.2a declaration), nor effects (P5); D3 a (drops and effects
before monsters) waits for the rungs that create them.

### P5 -- monster attacks
Hitscan with real sight, melee, the fireball pool, player health and armor, palette flashes.
Gate: `hurt`, saturation. Budget +0.3M plus the fight sprites.
**P5 DONE 2026-10-04, one rung** (blocked48, class F; `docs/gp-p5-interface.md`, `docs/gp-ledger.md` "P5 the monsters'
attacks"): `MONSTER_MODE = "full"`, `PLAYER_MODE = "fx"`. The zombiemen's and sergeants' hitscan, the imp's claw and
the demon's bite hurt the player through green / blue armor (`hurtcode`, one `dp_go`); the bar shows health and armor
and the screen takes DOOM's red damage palettes; the death MOMENT only (p_dead, the weapon down, the monsters losing a
dead target) -- the death think and restart are P7, and no gate reaches a death. The imp's fireball is an 8-slot pool
(flight, the missile cells, impact, the explosion drawn, a fizzle when full) and the player's hits spawn blood from a
2-slot pool (`projcode`). The gate is `scratchpad/gp/hurt_gate.py`: H1-H6 and the saturation case S1, 7 of 7 state-,
pixel- and palette-exact, deaths 0; S1 (8 fireballs in flight) averaged ~21.7M ops/frame over its 30 frames -- the
stress case, recorded. +127,652 on gamespeed (15,531,315), +186,258 on v5 (16,037,431) -- both inside the phase's
+0.3M; size +1,212,406 words, **35.16% against the 40% target** (above the old 35%); msframe NOT SEPARATED (x0.982,
beside the owner's fullscan.py with `--ignore-busy`). No kill criterion exceeded; some fj runs were owed at ship (the
ledger lists them with the pre-review's follow-ups). P5's effects (fireballs, blood) are drawn as runtime things of their
leaf, sorted WITH the monsters by the aprox depth key (`docs/gp-p5-interface.md`), not ordered before them as D3 a
reads; drops come in P6.

### P6 -- pickups and barrels. Gate `fight`. Budget +0.1M.
### P7 -- death, restart, exit. Gate `die`. Budget ~0.
**P6 + P7 DONE 2026-10-07, one rung** (blocked51, class F; `docs/gp-p67-interface.md`, `docs/gp-ledger.md` "P6 + P7
pickups, barrels, death and restart"): `PLAYER_MODE = "full"`, `MONSTER_MODE = "full"`, integrated on `m7-p67` from
six packages (A the model / oracle / gates, B `lootcode`, C `barrelcode`, D `restartcode` and the death turn, E the
monsters' tempo and the actors rule, F the owner's turn / fire / help requests). Every pickup with DOOM's caps, berserk,
the chainsaw, the drops; barrels (the puff, the blast, gibs, the chain, the aim window); blocking by barrels, solid
decor and live monsters; nukage; the dead latch and the dead player's guards, the dead view turning to the killer
(O1 re-opened by the owner: no view drop), and use restarting at the skill being played, one sequence with NEW GAME.
The owner's 2026-10-05 playtest: the monsters 2 tics a frame (D4 above), the ACTORS rule (monsters and fireballs
always drawn), the weapon x2, the turn's tap then x1.5 (far aim measured equal to DOOM's), the help's spacing. The
frozen set is now **v6** (v5's checkpoints re-planned at the new tempo; the owner approved it 2026-10-06, frozen at
30f9fd1): **14,699,526 on blocked51, every frame state- and pixel-exact, 7,300,474 under CAP-22**. The gates are
`scratchpad/gp/fight_gate.py` (F1-F10, the chain stress S2; 19/19) and `die_gate.py` (D1-D8; 11/11, 11 deaths, 5
restarts), plus every earlier gate, all exact. gamespeed 12,528,769 PASS is NOT comparable with blocked48's (O3: the
tours stop at monsters, take other routes and reach no door); size 36.24% against the 42% target (+1,457,356 words,
above the rung's +0.8 .. +1.2M estimate); msframe NOT SEPARATED (x0.980, quiet box). Three builds: blocked49 (a
pickup's bar a frame late) and blocked50 (a baked barrel's light class truncated; the oracle drew drops as actors)
were superseded. No kill criterion exceeded; the full tests/fj run at the head was owed at ship (the ledger lists it
with the follow-ups).
### P8a -- the final gameplay (the owner's 2026-10-07 request)
The dying view, knockback, infighting, D3 a / b and the follow-up issues #119 / #121 / #123 -- `docs/gp-final-plan.md`
(the plan, its owner decisions as taken, its As built), `docs/gp-ledger.md` "P8a". Class F.
**P8a DONE {{SHIP_DATE}}, one build with P8** (blocked53; the model modes `PLAYER_MODE = MONSTER_MODE = "final"`):
- **the dying view sinks** (O-A1 S0): DOOM's P_DeathThink drop, 1 unit a tic to 6 above the floor (`p_vd` 0..35); the
  walls, sprites and step faces sink exactly; floors and ceilings keep the standing eye's distance shading (the oracle's
  `view_drop` split does the same);
- **knockback**: P_DamageMobj's thrust with its inflictor (the shooter, the missile, the barrel), P_XYMovement for the
  player's knock (once a frame) and every monster and corpse (twice a frame, O-B3), MAXMOVE, friction, STOPSPEED, the
  corpse rule, the falling-forward reversal; a refused knock stops (O-B4); barrels are not pushed (O-B1); a drop stays
  where its owner died;
- **infighting**: targets name a thing, DOOM's switch and threshold, the far line of sight at any range (O-B2), monster
  bullets hit the nearest thing in their line (O-B5), fireballs hit monsters and barrels (the species rule, the shooter
  passed), a barrel's blast blames its first damager (`bar_src`);
- **D3 a** (drops and effects drawn before monsters in a leaf) and **D3 b** (barrels exempt from the soft raise);
- every DO row of the follow-up triage (`docs/gp-final-plan.md` 1.4).
Three builds: blocked52 r0 overflowed the table pool at 0x60000000 (the pool base is 0x80000000 since, 9070b02);
blocked52's gates found three fj bugs B0 missed (3c6dc06 `md_fa`, 0c8a93c `bl_los`, 99609f3 the pool window); blocked53
ships. v7 (planned at the final model, approved by the owner 2026-10-08) 15,825,592; size 38.22%
(+2,660,740 words); the gates p2a 13/13, hurt 7/7, fight 39/39 (K1-K7, I1-I6, C1-C3, the
stress S2-S4), die 17/17 (D9-D11: the sink) all exact; msframe 78.6 ms/frame, B SLOWER against
blocked51 (x0.917).

### P8 -- ship
CAP-22 on the frozen set, stress, size, every gate, the class-F rule, docs (CLAUDE.md, ship-gate.md, gamespeed's target
-> 22M), re-frozen baselines. **P8 DONE {{SHIP_DATE}} on blocked53** (`docs/gp-ledger.md` "P8 the ship",
`docs/gp-final-plan.md` 5.4): CAP-22 on v7 15,825,592, every frame of all 11 runs state- and pixel-exact; the stress
cases per frame (max / p95 / mean / frames over 22M), recorded under O-E1's tripwire (any frame over 44M or a scenario
averaging over 30M must be explained) -- hurt S1 25,165,824 / 24,379,392 / 23,173,529 / 30 of 30, fight S3 (the brawl)
17,039,360 / 17,039,360 / 15,645,627 / 0 of 60, S4 (the push storm) 15,466,496 / 14,942,208 / 12,679,491 / 0 of 76, die
D9 (the sink) 19,398,656 / 19,398,656 / 19,051,315 / 0 of 40, B0 v7's maximum 27,000,832 (R0-aftermath);
`gamespeed.SPEED_TARGET` 20M -> 22M (D1, 6dea24d) -- binding 12,490,840 PASS, `gamespeed_trail` TRAIL PASS, CONTROL-POSE
PASS, the tours still reach no door (O-E2); the msframe `shipped` baseline re-frozen on blocked53 (blocked44's retired);
#119 / #121 / #123 closed, `{{NEW_ISSUE}}` opened for what stays open.

**For the next session** (the milestone is done; read this before touching the game):
- **The standing binary** is `build/doom_e1m1_blocked53.fjm`; its number, provenance, build command (the 1b line now
  carries `--pool-base 0x80000000 --span-bits 0x7fffffe0` and `heat_blocked27_p8a`) and the four-step gate a new binary
  must pass are in `docs/ship-gate.md`. A new game binary is class F (D8) unless its pixels are identical (class S: B
  SLOWER never ships).
- **To play**: `fj --run build/doom_e1m1_blocked53.fjm --io pc --flat-max-words 134217728`. The menu: enter on NEW GAME
  opens the skill screen (w / s pick easy / medium / hard, enter starts, esc backs out); the HELP item or h opens the
  key-map help. In the game: W / S or UP / DOWN move,
  the LEFT / RIGHT arrows turn, A / D or , / . strafe, SPACE or E use (doors, switches, lifts), CTRL fires, 1-4 pick a
  weapon, ESC opens the menu, H the help. Dead: use (or NEW GAME) restarts the level at the skill being played; the exit
  switch ends the level.
- **The frozen set is v7**: a model change that moves a replay is a NEW version (section 1's freeze rule); CAP-22 is
  judged on it with `b0_scenarios.py --file scratchpad/gp/scenarios/combat_scenarios_v7.json --pixel-every 1 --proxy`.
- **The gates** a game build must pass: `m2_std_gate`, `m3_gate` (and their selftests), `scratchpad/gp/p2a_gate.py`,
  `hurt_gate.py`, `fight_gate.py`, `die_gate.py` (each with `--frame-ops` for the stress rows), B0 on v7, deg_gate with
  blocked51's op counts (the visual tier took none of M7's code), pinreport, the host suite and `tests/fj` solo -- one
  at a time (CLAUDE.md rule 1), stopping at the first failure.
- **Open** (`{{NEW_ISSUE}}`): the harness-completeness lessons of blocked52 (a stub must do to the shared registers what
  the callee does; the production `*_parts` wiring needs its own test; B0 cannot see a rule whose outcome agreed by
  chance; the label-coverage report section 9 asks for is still unbuilt); gamespeed's tours reach no door (O-E2 kept);
  the recorded levers and deviations; for M4: `hp_bar` inside the `lvdone` guard (#123-4) and the span at
  88.94% of 2^27 after the pool base moved.

**Build time paces everything**: a game build is ~2 h, and every rung that changes a source file
under `src/doomfj/` or `src/fj/` misses the counts cache and recounts (~34 min). ~15-20 builds in
all, strictly one at a time.

---

## 11. Watch items

- **Placement** (section 8): read the pin report on every build before judging a rung.
- **The pool base** is 0x80000000 (span 0x7fffffe0) since blocked52 r0 overflowed 0x60000000 (9070b02). Every tool that
  reconstructs the pool reads it (`poolmap.SHIP_GATE`, `profx/pool.KNOBS`, `profx/common.POOL_BASE_WORD`); a new tool
  that does must too. The span is 88.94% of 2^27.
- **A stub in a tests/fj harness** must do to every shared register and window what the callee it replaces does
  (blocked52: `dm_go` stubbed as a print hid `mm_fa` and `pw_t` / `pw_leaf` being rewritten), and a harness that proves
  an emitter function does not prove the `*_parts` call that wires it (blocked52: `bl_los` without `fight=`).
- **The counts cache** is signed from `src/doomfj/*.py` and `src/fj/*.fj` BYTES on disk: phase 0's
  model files already changed the signature, so the first P1 build recounts; a CRLF working copy
  also recounts (keep sources LF).
- **The narrow sprite reads (v2)** fail silently if anything re-points the reader; only the pixel
  gate sees it. The v2 slot ids are one byte (<= 255 things a frame).
- **New scratch cells** (the v2 slot cursor, the aim window, the monster window) must be in the
  reset set or persist set -- a surviving cursor paints the next frame wrong with no crash.
- **B0 and strafe**: blocked27 has no strafe. B0 re-injects the pose blocked27's own tic lands on
  the model's; its 390 strafe-only frames run no collision tic, so B0 undercounts by 346,539 --
  judge against the proxy baseline, 18,107,313.
- **`gamespeed --validate`** steps the doors since fix/gamespeed-validate-doors: its own
  per-frame record (pose and every door) equals blocked27 on every frame of all ten runs
  (`docs/ship-evidence/blocked27_gamespeed_trail.log`). When the gameplay binary changes how the
  player moves (monsters that block, strafe), re-run `gamespeed_trail.py` on it and re-record
  `gamespeed.BINARY_ENDS` / `BINARY_DOORS`; `--selftest` N6e fails until then.
  Done for P6 + P7: re-recorded from the game's model (f3acab8) and confirmed on blocked51 by `gamespeed_trail.py`
  (TRAIL PASS, `blocked51_gamespeed_trail.log`). Done for P8a: knockback moved run 0's end to (529, 208) (564861e, from
  the final model), confirmed on blocked52 and blocked53 (TRAIL PASS, CONTROL-POSE PASS,
  `blocked53_gamespeed_trail.log`). No run opens a door, so CONTROL-DOORS reads N/A (7739a72) until one does.
- **Unit costs** from standalone probes carry a layout factor (0.79-1.06x pooled; the sprite
  pipeline's 1.70 is UNVERIFIED) -- re-measure in-game with `profx` after each build.

---

## 12. Where everything is

| rung | read |
|---|---|
| all | this file; `docs/plan-gameplay.md` (the record, sections 13-16); `docs/ship-gate.md` |
| P1.1 | `docs/gp-pin-protection.md`; `scratchpad/12m/pinreport.py`; `scratchpad/12m/profx/hotwords_blocked27.json` |
| P1.2 | plan 6.3; `scratchpad/gp/probes/s6/` (line, cell, ptloc groups) |
| P1.3 | plan 6.3; `src/fj/sim.fj` `bind_things`; `world.py` leaf bookkeeping |
| P1.4 | `docs/gp-sprite-column.md`; `scratchpad/gp/probes/sprite/` |
| P1.6 | plan 6.6; `scratchpad/gp/render/art_budget.py` -> `art_budget_out.txt` (the 1.96M-word bank) |
| P2b | `docs/gp-lift-spike.md`; `scratchpad/gp/lift/` |
| P3-P7 | `src/doomfj/world.py`, `combat.py` (the model = the oracle); `docs/gp-aim-window.md`; `docs/gp-partial-ditto.md`; `scratchpad/gp/census*.py` |
| P8a / P8 | `docs/gp-final-plan.md` (plan, decisions, As built); `docs/gp-ledger.md` P8a / M7 summed / P8; `src/doomfj/knockcode.py`, `monsterdecide.py`, `monstersight.py`, `projcode.py`, `barrelcode.py`; `scratchpad/gp/fight_gate.py`, `die_gate.py`, `p8a_lib.py` |
| measure | `scratchpad/12m/profx/README.md`; `scratchpad/gp/b0_scenarios.py`; `scratchpad/gp/scenarios/README.md` |
