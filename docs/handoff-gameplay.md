# Handoff: the fully playable E1M1, under 22M ops/frame

**Status (2026-09-26): phase 0 is DONE; phase 1 is NEXT and not started.** Everything below is the
whole plan, as the owner approved it, updated with phase 0's measurements. It replaces nothing:
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
| **speed** | **(mean + p80)/2 of per-run ops/frame <= 22,000,000** | the FROZEN combat scenario set v2 (`scratchpad/gp/scenarios/combat_scenarios_v2.json`): 11 runs x 100 frames at skill hard, starting from checkpoints across the level, driven by `scratchpad/gp/b0_scenarios.py` (the binary) against the model (the oracle) |
| **size** | <= 35% of 2^27 words (46,976,204) | `scratchpad/12m/poolmap.py` / gamespeed's size line |
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
- a BEHAVIOUR change (anything that moves a replay: a rule, a fix, a picture rule): a NEW VERSION in
  a new file -- `--plan --file <new>` (the planner refuses a frozen file), B0 re-measured on it
  (`b0_scenarios.py --file <new>`), then `--freeze --file <new> --approver "the owner"` with the
  owner's words (a first freeze refuses any other approver).

The refusals are `--selftest` controls: R1 the untouched set is accepted with nothing to re-record;
the rehash refuses R2 a behaviour change (strafe 13 -> 12) and R3 a checker change; the re-freeze
refuses R4 a picture-rule change (DEG_SOFT_MON 4 -> 2); R5 a clean re-freeze keeps the owner's
approval and names its own approver; R6 a first freeze by anyone but the owner is refused; R7
`--plan` refuses the frozen file.

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
| D4 | one DOOM tic per frame (fights run at ~32-38% of DOOM's real-time speed, consistently) |
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
| **P1.1 pin protection** | flipjump (a branch off 1.5.1): BlockPool takes a `heat=` list -- hot groups placed first, heat-ordered indices, always pinned; inert without it (`docs/gp-pin-protection.md`). Doom: `build_blocked.py --pin-heat <profx hot list>`; rebuild blocked27's program with it | S (same program, same pixels) | ESTIMATE -1.27M (heat-ordered indices); the point is stability | 1-2 |
| **P1.2 player collision cells** | 32-unit cells, candidate lists (interval arithmetic over closed cells at 16.16), D4 rows, SAFE jump macros; exact against today's line tests | S | -1.0 .. -1.4M | 1-2 |
| **P1.3 persistent leaf lists** | `sshead`/`thnext`/positions persistent (baked to the spawn lists), per-move rebind, `bind_things` deleted; monsters still inert | S | -0.44M | 1 |
| **P1.4 the v2 sprite column** | `docs/gp-sprite-column.md` (v2; needs `sprbank` 4096-bit aligned -- add the build check) | S | with P1.5: -1.40M on the frozen set (S5, (iii) -> (iv)) | 1 |
| **P1.5 skill filter + skill menu** | the build spawns per skill; NEW GAME asks easy / medium / hard and starts from that skill's level-start state (the full restart block is P7) | F | -0.3M | 1 |
| **P1.6 the native-list sprite bank** | all monster frames and rotations; the rowmap as a dispatch (it must not break v2's narrow reads) | F if any pixel moves | size -0.97M words | 1-2 |

P1 ends when all six ship. The ship gate's standing number moves with P1.1-P1.4 (class S). A class-S
rung that measures NOT SEPARATED may still ship with the stated reason "foundation for P3" (the
ship gate's own clause) -- never one that measures SLOWER.

### P2a -- doors, keys, exit
The blue-key check (and the key's sprite and pickup), walk-over and blazing doors, the exit switch
and the "level complete" frame, NEW GAME resetting the level. Class F. Budget +0.05M.

### P2b -- lifts and the floor switch
`docs/gp-lift-spike.md`'s rung plan: host-only work and FAIL-first tests, 1-3 render-tier builds,
then two game builds. Budget: ops <= +0.1M, size <= +0.35M words, plane ids <= 243.

### P3 -- monsters alive
First a build that EMITS every new table and calls none of it -- its delta is the pure placement tax.
Then the state machine, K-slot scheduler, RNG, animation and rotation, waking, chase on the cells,
thing collision, per-move rebind in use, doors opened by monsters and reversing on them, D3's
compositor rules. Gate: `fight` (partial), fuzz. Budget +0.3M.

### P4 -- the player's combat
Input (fire, 1-4, strafe; the device already sends the keys), the weapon state machine, the aim
window, monster pain/death/corpses/drops, the weapon overlay and the status bar (the flipjump
device PR: the partial-ditto tokens and the bar's ditto). Gate: `fight`. Budget +0.6M.

### P5 -- monster attacks
Hitscan with real sight, melee, the fireball pool, player health and armor, palette flashes.
Gate: `hurt`, saturation. Budget +0.3M plus the fight sprites.

### P6 -- pickups and barrels. Gate `fight`. Budget +0.1M.
### P7 -- death, restart, exit. Gate `die`. Budget ~0.
### P8 -- ship
CAP-22 on the frozen set, stress, size, every gate, the class-F rule, docs (CLAUDE.md, ship-gate.md,
gamespeed's target -> 22M), re-frozen baselines.

**Build time paces everything**: a game build is ~2 h, and every rung that changes a source file
under `src/doomfj/` or `src/fj/` misses the counts cache and recounts (~34 min). ~15-20 builds in
all, strictly one at a time.

---

## 11. Watch items

- **Placement** (section 8): read the pin report on every build before judging a rung.
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
| measure | `scratchpad/12m/profx/README.md`; `scratchpad/gp/b0_scenarios.py`; `scratchpad/gp/scenarios/README.md` |
