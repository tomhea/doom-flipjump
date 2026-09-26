# Plan: a fully playable E1M1 at <= 22M ops/frame

**Status: PHASE 0 DONE 2026-09-26; execute from `docs/handoff-gameplay.md`** (the whole plan, final
numbers on the frozen set v2). This file is the RECORD of how the plan was made.

**(was) PHASE 0 STARTED 2026-09-26** on branch `gameplay-p0`. The owner approved the plan and
decided every item of section 11 on 2026-09-26 except D3 (the compositor rules), which waits for the
phase-0 census by design. Phase 0 is measurement, a Python model and design spikes only; its work
streams are in section 15.

How this plan was made: seven research missions (game spec, measurement, monster AI, combat,
sprites/HUD, verification, reclaim), a synthesis, and a red-team pass whose eleven findings are
folded in. **MEASURED** = the measurement mission's attributing profiler on
`build/doom_e1m1_blocked27.fjm` this session (section 12 says how it was validated). Everything
else is a model or an estimate and says so; a number carried from an older doc is UNVERIFIED.

**The verdict in one paragraph.** It fits, but not by default. What costs ops in a fight is DRAWING
monsters, corpses and effects (~30K per sprite column, MEASURED), not thinking for them (~0.1M a
frame, modelled). The budget closes only if three things happen first:
- the ops are reclaimed (player collision is 1.48M/frame MEASURED and is the biggest single
  reclaim);
- the build's table placement is protected, since one unlucky re-roll has cost 6.8M before;
- the sprite column gets cheaper.

And one design problem must be settled before any code: sight and hits read the picture, and the
picture is deliberately degraded in crowded frames (section 5).

---

## 1. The target, stated so it can be enforced

| | target | today (blocked27) |
|---|---|---|
| speed | the owner's binding metric, **(mean + p80) / 2 of per-run ops/frame <= 22,000,000**, on a NEW combat scenario set that the owner freezes (section 9) | 17,665,168 MEASURED (mean 15,200,279, p80 of runs 20,130,057), on today's combat-free games |
| size | <= 35% of 2^27 = 46,976,204 words | 43,253,668 words = 32.23% |
| correctness | byte-exact AND state-exact against the oracle, on every frame of every gate | byte-exact |
| scope | the fully playable level of section 2 | walk, doors, menu |

**Why the binding metric and not every frame (decision D1).** Today's individual frames, MEASURED over
gamespeed's 1,000 game frames: p50 17.24M, **p80 22.61M**, p90 24.22M, p99 28.16M, **max 32.42M**.
One frame in five is already above 22M before any monster moves. A per-frame cap would need a
renderer project first. The plan gates on the binding metric and REPORTS a stress frame.

**The baseline B0** is blocked27 run in TIC mode, the same keys as the combat set, from each run's
checkpoint start injected by the state probe (section 9). The scenario planner keeps every run's
player route inside what blocked27 can walk: no lift ride and no key door within a run, since the
checkpoint places the run in its area. So B0 prices the same routes with no gameplay.
Injecting only the viewpoint each frame is NOT a baseline: S2 measured that it skips the player's
collision tic and reads 1.36M / 1.91M ops/frame BELOW real play on gamespeed runs 0 / 1
(`scratchpad/gp/b0_gamespeed01_view.log`). The owner freezes the scenario set v1 and B0 before
phase 1, so the people building the game cannot re-grade it (D2).

---

## 2. What "fully playable" means (spec mission; [W] = verified in the WAD or repo)

**Things [W].** There are 292 in the WAD. By skill, excluding multiplayer-only:

| | easy | medium (HMP) | hard (UV) | built today |
|---|---|---|---|---|
| zombieman / shotgun guy / imp / demon / spectre | 9/2/4/2/0 | 4/10/10/5/0 | 5/13/18/9/1 | 12/13/18/9/1 |
| **monsters (ambush)** | **17 (8)** | **29 (13)** | **46 (24)** | **53, no skill filter** |
| barrels / decor | 22/81 | 22/80 | 22/80 | all, plus 26 multiplayer items |

- No code reads `Thing.flags` today, so the build spawns every skill's monsters plus 26
  multiplayer-only items.
- Weapons: on UV and HMP the shotgun comes ONLY from shotgun guys' drops, and berserk exists only
  on easy and HMP. The chainsaw sits in sector 139, probably a secret.

**Map mechanics missing today [W], all needed to reach the whole level:**
- **2 lifts** (sectors 98 and 103). They gate 31 sectors holding 16 of the 46 UV monsters, 16 of
  the 22 barrels and the blue key.
  - Lifts move FLOORS. Floors are baked per leaf in five places (eye height and band class, thing
    z, the collision seed floor, the step faces, and the line openings), so this is an M2-sized
    rung of its own, not door machinery (5.5).
- **The floor switch**, linedef 753: it lowers sectors 76, 126 and 129 toward secret sector 128,
  on the same machinery as the lifts.
- **2 blue-key doors** (sectors 51 and 71). Today they open WITHOUT the key; `doors.py`'s "no
  keys" is wrong. Also 1 blazing door (84) and 2 walk-over doors (77, 145), which are stored shut
  and never open.
- **The exit switch** (linedef 407), reachable through plain doors. Also 3 nukage sectors.
- **NEW GAME** from the menu must reset the level; today it resumes the old state.

**Mechanics, ranked** (the DOOM function names are in the spec report):
- **A, must-have:**
  - skill filter at build time;
  - waking by sight and sound (ambush monsters need sight);
  - chase (A_Chase, P_Move, P_NewChaseDir) and the melee / missile range checks;
  - the attacks of all 5 monster types;
  - damage (armor, pain chance) and death (death frames, corpses, drops);
  - imp fireballs; barrels with radius-damage chains;
  - every pickup type;
  - the weapon state machine (fist, pistol, shotgun, chainsaw) with ammo and switching;
  - damage and pickup palette flashes;
  - a HUD (health, armor, ammo, key);
  - player death and restart; the exit;
  - lifts, the floor switch, key doors, walk-over doors;
  - doors and lifts reversing on a thing (DOOM's P_ChangeSector), or chasing monsters get sealed
    inside doors;
  - the player BLOCKED by solid things -- monsters, barrels, solid decor (found by S3a: today's
    binary and oracle let the player walk through every thing). The player's collision cells carry
    the solid things' boxes, as the monsters' do (6.3);
  - the player's weapon acts before the player's move within a tic (DOOM moves first), so a shot
    resolves against the picture the player saw (the aim window, 6.4).
- **B, simplified (needs sign-off, D5):**
  - no knockback;
  - 2D projectiles;
  - P_NewChaseDir capped at a few tries;
  - rounded diagonal steps (8/6 and 10/7);
  - at most K = 3 heavy monster actions per frame. At ~12 awake that defers ~1.3 of the ~4.3
    wanted, and at the ~20 peak each monster acts ~40% as often;
  - monsters open plain doors when a move fails in the door's use box;
  - puffs and blood capped at 2 alive;
  - a fireball pool of 8, where a full pool makes the attack fizzle;
  - nukage as DOOM's 5 damage every 32 tics.
- **C, dropped (needs sign-off):**
  - infighting: monster bullets and fireballs pass through monsters and barrels;
  - sound;
  - spectre fuzz (drawn as a demon);
  - flickering lights;
  - weapon bob and the weapon raise/lower animation (the switch timing stays);
  - the whole-screen fire brightening;
  - gib deaths (optional, cheap in the native bank);
  - the status-bar face (D6).

**Time base (D4).** The player already moves in DOOM tics: 16 units/frame is DOOM's run speed per
tic, and the turn is DOOM's turn per tic. So the plan uses **one tic per frame**, with `info.c`
durations unchanged for monsters, projectiles and weapons. At 75-90 ms/frame that is ~32-38% of
DOOM's real-time speed, for the whole game consistently: a pistol shot every 1.05 s, a shotgun
blast every 2.8 s. Doors and lifts keep their frame tuning.

**Input [W].** The pc device already sends every ASCII key plus shift, ctrl and alt; `input.fj`
reads WASD, arrows, space, enter and esc, and bits 5-7 of the key byte are free. Needed:
- fire (ctrl, held: refire reads it);
- weapon select 1-4;
- strafe (`,` / `.`).

**No flipjump change** for input.

**Sizing (estimates, UV).**
- Monsters awake at once: typically 5-12, peak ~20.
- On screen in a fight: 2-5, peak ~10.
- Imp fireballs in flight: 1-3, peak ~6.
- Awake monsters (A_Chase) act about 0.36 times per tic each; dormant ones (A_Look) about once
  per 10 tics.

---

## 3. Where the ops go today (MEASURED, blocked27, gamespeed's 10 games = 1,000 frames)

| object | ops/frame | % |
|---|---|---|
| render walk, all | 12,986,630 | 85.4 |
| - seg_pass2_leaf (incl. column emission 1.64M) | 4,019,353 | 26.4 |
| - seg_pass1_ts_leaf (two-sided walls; 0 .. 14.67M per frame) | 2,723,647 | 17.9 |
| - seg_pass1_leaf | 2,641,860 | 17.4 |
| - BSP node side tests | 966,608 | 6.4 |
| - baked sprites / runtime sprites / thing_pass | 966,408 / 583,454 / 704,965 | 6.4 / 3.8 / 4.6 |
| **collision** (seed walks + try_move / check_position) | **1,475,186** | **9.7** |
| sim.bind_things | 438,808 | 2.9 |
| m1_reset | 249,325 | 1.6 |
| the rest (eye walk, move, view, doors, input) | ~50,000 | 0.3 |

(Exact phase spans from `scratchpad/12m/profx/an_phases.txt`; this table's first draft summed rounded
segments and read 1-2 ops higher.)

| primitive (per call) | ops | primitive | ops |
|---|---|---|---|
| hex.ptr_index (8 nibbles) | 846 | one player move try | ~613K |
| read_byte / write_byte via pointer | 260 / 504 | check_position (4 blocks) / per line tested | 576K / 6.8K |
| read_hex, per nibble | ~244-430 | point location mean / median / max | 30.7K / 8.9K / 180K |
| read_table_packed, per byte | ~404 | thing_load / project+record a runtime sprite | 19.5K / 30.2K |
| hex.mul_lo 8 / fixed_mul_lo 8,4 | 825 / 3,381 | project+record a baked sprite | 15.4K |
| hex.div 8 | 157K | **one sprite column** (sprite_runs 10.9K + split wall emission 19.3K) | **~30K** |
| hex.cmp 1 nibble / hex.scmp | 40 / 249 | present: one full 100-row column | 15.9K (~159 ops/pixel) |
| M1 reset per restored cell | ~41 | BSP node visited | ~4.1K |

**Three facts this establishes.**
1. **bind_things costs 0.44M, not the ~7.5M the docs said.** The docs' figure came from build b26, where
   later code's wflip chains landed inside bind_things' padding. Per-move rebind is therefore a small reclaim. It stays in the plan because
   moving monsters need exactly that machinery.
2. **Collision is the largest non-render cost, and today's routine cannot move monsters.** One try
   costs ~613K, so 5 monster steps a frame through it would be ~3M. A cell grid (6.3) makes the
   player's collision and the monsters' cheap, and it is the biggest reclaim.
3. **Fights are paid in sprite columns.** A column is ~30K. One imp at 128 units covers ~30 columns
   (~1M); its corpse is wider: POSSL0 is 50 px against POSSA1's 41, TROOM0 57 against TROOA1's 48.
   Every runtime thing in a visited leaf also pays ~35-50K (thing_load plus projection) before any
   column is drawn.

---

## 4. The FlipJump rules for gameplay code

1. **A compile-time address is cheap; a runtime index is not.**
   - Per-monster state lives in fixed cells with per-monster code stubs.
   - A runtime index selects CODE: a jump through a table into that entity's stub. It does not
     select DATA through `ptr_index` + `read_byte` (~1.1K per access MEASURED) or
     `read_table_packed` (~0.4K per byte MEASURED).
2. **Constant data goes in dispatch tables** (the repo's D4 tables).
3. **No runtime multiply or divide in gameplay** (`hex.div` is 157K MEASURED):
   - octant comparisons instead of angles;
   - AproxDistance built from abs, compare, shift and add;
   - per-call-site RNG outcome tables (damage, spread column, pain yes/no) instead of modulo.
4. **Spatial questions become precomputed grids:** collision cells, the point-location start node,
   pickup cells, projectile wall cells.
   - Each is proven exact on the host with interval arithmetic over closed cells at 16.16
     precision, plus a mutated-entry negative control.
5. **Bounded by construction.**
   - At most K heavy monster actions per frame, with a rotating cursor and deterministic deferral.
   - Fixed pools: 8 fireballs, 2 puffs/blood.
   - A per-act line-test budget.
   - The simulation's worst case is asserted at emit time. Drawing is the one part that cannot be
     bounded this way.
6. **One schema for persistent state.**
   - Declarations, the M1 persist set, the oracle's `WorldState` and the state probe all derive
     from it.
   - New macros carry NO `@`-local data cells, checked statically: M1's lesson is that a
     restore-set hole hangs the program instead of painting a wrong pixel.
7. **One source for every table.** The emitter and the oracle read the same Python tables: states,
   monster info, weapons, RNG, grids.

---

## 5. The design problem to settle first: the picture becomes the rules

Two proposals below reuse the renderer as a sensor, because it is by far the cheapest source of
truth:
- **Sight:** a monster the renderer drew last frame can see the player.
- **Hits:** the 17 centre columns record which target the shot would hit.

But the picture is built by a compositor with degradation ALWAYS on (`deg_flag = 1`), and its rules
were made for a static scene [W, `frame_render.fj` `thing_record_body`, `reference_model.py`]:
- Each column has two write-once sprite slots, filled in BSP-walk order. Slot B takes only
  fragments at least 32 rows tall (`DEG_SPRB_MINH`).
- After 4 accepted monsters, the rest need at least 10 rows (~450 units) (`DEG_SOFT_MON`). After 3
  scenery things, scenery needs at least 24 rows.
- Inside a leaf, baked things draw first, then runtime things in index order, not by depth.
- Corpses keep the monster flag, so they spend the monster budget.

**What that does to a game** (red-team analysis, to be quantified):
- Puffs, blood, a dropped clip, the dropped shotgun (the ONLY shotgun on UV) and fireballs are
  small. Where their monster or corpse already took slot A, they are invisible.
- A far monster behind four others is not drawn, so it is blind and unshootable.
- A farther monster in the same leaf can take the aim column ahead of a nearer one.

Both mirrors agree on all of this, so no gate can catch it.

**Phase 0 settles it:**
- an oracle census of these events along the combat scenarios;
- then compositor rules priced and put to the owner (D3). The candidates:
  - drops and effects ordered before monsters;
  - awake monsters, projectiles and barrels exempt from the soft budgets;
  - corpses counted as scenery;
  - depth order among runtime things inside a leaf;
  - "seen" and the aim window recorded when a column is still OPEN, before the budget test, so
    sight and hits stop depending on degradation. In a crowded frame you could then hit a monster
    that was degraded out.

---

## 6. Designs by subsystem (details and arithmetic in the mission reports)

**6.1 World state, scheduling, RNG (AI mission).**
- Per monster, at fixed addresses: state, tics, flags, movedir, facing octant, movecount,
  reactiontime, health, floor, leaf, sector (~27 nibbles).
- Each frame, one slot per monster:
  - tics != 0: decrement;
  - otherwise the monster is READY, and one D4 lookup gives next state / tics / action / frame.
- Cheap actions (none, A_Look, A_Fall) run inside the slot.
- Heavy actions (A_Chase, attacks) take one of K slots: copy the monster's cells into a fixed
  window (~3K), run one shared leaf, copy back. A ready monster without a slot waits a frame, and
  the oracle mirrors that.
- RNG: DOOM's 256-entry rndtable as a D4 table, with one index cell per stream.
- Modelled (UNVERIFIED): ~34K per heavy act, **~0.1M in a typical frame**, <= ~2.0M in the
  all-awake worst case at K = 3. That model priced `ptr_index` at 2.1K where the MEASURED cost is
  846, so it leans pessimistic.

**6.2 Waking and sight.**
- **Waking:** the monster was drawn (or seen, per section 5), or it is REJECT-visible within 128
  units, or it heard a shot.
  - REJECT comes from `freedoom1.wad`'s E1M1, the identical map; 70.9% of sector pairs are
    rejected there.
  - Sound uses precomputed regions with doors as runtime edges (E1M1 has no sound-blocking lines).
    The weapon code marks them (~30K per shot).
  - A sleeping monster is at its spawn point, so its region, ambush flag and field-of-view test
    are constants (~0.6K per look).
- **Attacking needs real line of sight.** REJECT alone would let monsters within 128 units shoot
  through walls. So an attack takes "seen", or, for a near monster the renderer did not draw, a
  short trace over the collision cells between it and the player: a few candidate lines, where
  one-sided lines and closed doors block. That trace is UNVERIFIED at ~50-100K and rare.

**6.3 Movement, collision, leaf lists.**
- **Collision cells, 32 units:**
  - Per cell and per radius class (player 16, monsters 20 and 30) there is a candidate line list:
    mean 1.9-2.3 lines, max 19-26, in D4 rows.
  - It covers monster-blocking lines, step and drop-off over 24, and gaps under 56. Door lines keep
    their runtime bit.
  - Monsters, which move in 8 directions, also get a static "no line can block" verdict per
    direction; 44.6-48.9% of their tries need no line test at all.
  - The player moves at arbitrary angles, so the player gets the lists only. The lists are built
    by interval arithmetic over the closed cell plus one unit, and tested at 16.16 points on cell
    edges.
  - A candidate superset cannot change a verdict, so this is exact against today's line tests.
  - **The player moves onto it first (phase 1): pixel- and trajectory-identical, reclaiming most of
    1.48M.**
- **Other things:** solid decor and sleeping monsters are boxes in the cell lists. Awake monsters
  and the player are scanned once per act into an 8-bit blocked-direction mask.
- **Point location:** each cell stores the deepest BSP node that no point of the cell straddles,
  and the lookup jumps into the existing baked node code from there. Today's walk is 30.7K mean
  MEASURED. The start-node lookup is modelled at "a few K" (UNVERIFIED: the model overpriced
  today's walk 2.4x). It also shortens today's seed and eye walks.
- **Leaf lists:**
  - `sshead`, `thnext` and the positions become persistent, baked to the spawn lists, and
    `bind_things` is deleted.
  - A thing that crosses into another leaf is unlinked and re-inserted in the list's order: 7.4% of
    8-unit monster steps, and most fireball tics.
  - With index order kept, every list equals today's from-scratch build. If D3 chooses depth order
    for runtime things, that becomes a per-frame sort of short lists, priced in phase 0.

**6.4 Combat (combat mission).**
- **The player's hitscan comes from the picture.** While drawing, a shootable living target writes
  its id into the 17-column aim window (columns 72-88, DOOM's full pellet spread), only where no
  nearer wall covers the column; section 5 governs which targets can write.
  - The next tic resolves the shot. The pistol uses column 80; refire shots and shotgun pellets
    take their column and damage from a per-call-site table.
  - A hit jumps into the target's own code: health, pain roll, death.
  - Fist and chainsaw use the same pick plus a 64-unit range.
  - Rejected: DOOM's exact line trace. It would cost ~4M ops per trace, so one shotgun blast would
    be ~30M.
- **Monster hitscan:** the attack's sight test, distance under 2048, and the spread against the
  player's width at that distance (a precomputed table, no multiply). Melee damage comes from a
  table.
- **Fireballs:** a pool of 8 slots with unrolled shells. Each tic a fireball moves, tests the
  player's box, and tests walls in a 64-unit cell grid (~2.5 candidate lines per non-empty cell).
  It re-links to the leaf lists when it changes leaf.
- **Damage and death:** 12-bit signed health. A kill sets the dead flag, checks the gib threshold
  and enables the drop; the drop sits at the corpse's position.
- **Pickups:** a 64-unit grid with each item's reach pre-inflated, so only the player's own cell is
  checked. Give routines carry DOOM's caps and auto-switch. `thvis` flags persist.
- **Barrels:** 20 HP, then an explosion countdown and radius damage by sight; barrel-to-barrel sight
  is precomputed.
- Modelled (UNVERIFIED): a quiet frame ~10K, firing 16-26K, a heavy fight 0.21-0.39M.

**6.5 Lifts and moving floors (the red team's scope correction).**
- This is a runtime-floor rung, the way M2 was a runtime-door rung:
  - the two lifts' floors (~10 stops each at quant 16) and the floor switch's three sectors;
  - each of the five baked floor sites made runtime for those sectors;
  - plane ids: 222 of 255 are already used;
  - monsters triggering the walk-over special;
  - reversal on a thing.
- Unknown cost until a phase-0 design spike prices ops, size and plane ids.
- Key doors and the blue key (a sprite plus a pickup), walk-over and blazing doors, the exit
  switch with a "level complete" frame then the menu, and nukage all stay on the door machinery.

**6.6 Drawing (sprites/HUD mission).**
- **Sprite bank to native run-lists (a picture change, D6).**
  - Each patch column gets run-lists at native resolution (full, half, coarse), scaled at draw time
    through one 8,192-entry `rowmap` table (32 height buckets x 256, the same buckets as today;
    exact heights cost +0.2M words more).
  - Today's format cannot hold the animations: all monster frames would take the image to 51.7%,
    and a lean set to 42.3%.
  - Native lists hold ALL frames, 8 rotations, effects, weapons and the HUD in 1.96M words, which
    replaces today's 2.92M bank: **31.51%**. The per-run `rowmap` lookup has to be priced against
    the column target.
- **Rotation without atan:** take the octant of the viewer-to-thing offset (compare `|dy|*106`
  against `|dx|*256`, plus two signs) against the monster's facing octant. This is exact for DOOM's
  multiples of 45 degrees. Mirrored rotations are free: negate the column step. ~5K per visible
  monster.
- **Cut the per-column sprite cost before fights land:**
  - the fragment record goes from 7 bytes to 3;
  - one region walk instead of two;
  - `DEG_HD_BUDGET` 2.
  - Target: a sprite column <= ~15K, from ~30K MEASURED.
- **Weapon sprite:** baked as code per (frame, column), with the world stopped at the weapon's top.
  - It breaks dittos: today 56.5 of 160 columns are dittoed, and each re-emitted column costs
    ~15.9K.
  - So **+0.2..0.5M on EVERY frame** (the weapon is always on screen), and 0.3-0.5M on firing
    frames with the flash.
- **HUD:**
  - The device keeps any pixel a frame does not mention.
  - A 160x16 bottom bar needs one additive device option in flipjump, because dittos must stop
    copying the bar. It also makes the 3D view 84 rows tall, which changes every 3D pixel and
    saves an estimated 0.1-0.3M.
  - The alternative without a device change is a 24-column side panel.
  - Digits come from a 512-entry table, redrawn on change only.
  - Palette flashes use the device's palette command.

**6.7 Death, restart, exit.**
- At 0 health the player is dead, and use requests a restart.
- Restart, and the menu's NEW GAME, is a second reset block: every persisted cell except mode and
  held keys goes back to its level-start value, taken from the pristine image the frame reset
  already uses.
- Exit: the proximity box on line 407 plus use, then the level-done frame, then the menu.

---

## 7. Budget

**Superseded by section 16 (phase 0's measured budget on the combat set).** Kept as the pre-P0 estimate.

**Speed, on the binding metric** (estimates; M = rests on MEASURED unit costs):

| line | effect on (mean+p80)/2 |
|---|---|
| B0 (phase 0 measures it by injector) | ~17.7M assumed |
| R1 player collision on the cells (M: 1.48M today) | -1.0 .. -1.3M |
| R2 persistent lists, per-move rebind (M: 0.44M today) | -0.35 .. -0.45M |
| R3 `hex.if_flags` tables into the pool (flipjump, as #362 did for the shifts; census) | -0.4 .. -1.0M, optional |
| R4 skill filter (UV): 7 zombies + 26 multiplayer items no longer drawn | -0.1 .. -0.2M |
| monster AI, all of it | +0.1 .. +0.6M |
| **fights: live monsters, corpses and runtime loads, after the column cut -- the phase-0 model's output** | **+0.8 .. +3.0M** |
| animation and rotation selection, effects | +0.1 .. +0.5M |
| combat logic | +0.06 .. +0.2M |
| weapon sprite, every frame (lost dittos) | +0.2 .. +0.5M |
| lifts, floor switch, key doors, HUD, persisted state | +0.1 .. +0.6M (lifts unpriced until the spike) |
| **projected, before placement effects** | **~16.1 .. ~21.7M (optimistic end includes R3); the cap is 22M** |
| placement (blocking pins), either direction | **+/- up to ~6M** unless pins are protected first |

- **Reading of the table:** the pessimistic case touches the cap, and unprotected placement alone
  can exceed it. So:
  - pin protection is a phase-1 PREREQUISITE, not a risk line;
  - the fight line is a phase-0 OUTPUT, not an input;
  - the fallbacks are ready (section 11): HMP, K = 2, degradation budgets, a smaller window, R3.
- The two-sided wall storms (up to 14.7M in one frame) are 3 of 1,000 frames, in runs below the p80
  run, so they do not move the binding metric; they belong to the stress report.

**Size:**

| line | words | % of 2^27 |
|---|---|---|
| today | 43,253,668 | 32.23 |
| sprite bank to native lists: ALL monster frames + effects + weapons + HUD | -0.97M | 31.51 |
| monster AI (stubs, leaf, grids, REJECT rows, tables) | +0.6 .. +0.8M | |
| combat (pickup and wall grids, pool, damage code, restart block, weapons) | +0.5 .. +1.0M | |
| player collision cells | +0.1 .. +0.3M | |
| lifts and moving floors | unpriced until the spike | |
| **projected** | | **~32.4 .. 33.1% + lifts, under 35%** |

This is E1M1 only. The owner's 1-3-level goal collides with it (D12):
- the 09-25 note: the 35% target already breaks at 2 levels;
- the byte-wide thing lists overflow on E1M3 (248 things) and E1M5 (250) once ~12 new pool things
  are added. The parked wide-thing-lists branch would be needed.

---

## 8. Phases

**Every rung carries:**
- R1 FAIL/PASS tests;
- the state-exact gates of section 9;
- a ledger row: ops attributed to the rung's own code by the profiler, the binding delta, size,
  ms/frame, the pin report, and pool declines.

**Kill criteria, declared before the rung starts:**
- attributed ops > 1.25x the rung's budget → redesign;
- the cumulative projection > 22M minus the remaining budgets minus a 15% reserve → stop for a
  scope decision.

| phase | content | gate | budget |
|---|---|---|---|
| **P0 instruments, model, spikes** | commit the attributing profiler (with its control); the state probe/injector; the Python gameplay model (`world.py`, `rng.py`, `gamedata.py`) on scripted fights, **including post-kill frames**, giving the fight line; **the compositor census (section 5)**; the combat scenario set v1 and B0 via the injector, frozen by the owner; fj micro-probes of every new primitive (seconds each); **the lift design spike**; a pin-report script | probe controls; model tests | none (it produces the budget) |
| **P1 reclaim and foundations** | **pin protection or a heat-ordered pool first** (a flipjump change); R1 player collision cells; R2 persistent lists + per-move rebind (monsters inert); R4 skill filter; the sprite bank to native lists + the per-column cut; optional R3 | R1, R2: pixel-identical, class S; R4 and the bank: picture changes, re-certified | -1.5 .. -2.9M |
| **P2a doors, keys, exit** | the blue key + key doors, walk-over and blazing doors, the exit + end frame, NEW GAME resets the level | extended m2/m3 gates | +0.05M |
| **P2b lifts and moving floors** | runtime floors for the lifts and the floor switch, reversal on things | a lift gate | from the spike |
| **P3 monsters alive** | state machine, K-slot scheduler, RNG, animation + rotation, waking, chase on the cells, thing collision, per-move rebind in use, monsters opening doors, door reversal | `fight` (partial), fuzz | +0.3M |
| **P4 player combat** | fire and weapon keys, weapon state machine, aim window, monster pain/death/corpses/drops, weapon sprite, HUD | `fight` | +0.6M |
| **P5 monster attacks** | hitscan with real sight, melee, the fireball pool, player health and armor, palette flashes | `hurt`, saturation | +0.3M plus fight sprites |
| **P6 pickups and barrels** | pickup grid, give routines, drops, barrel chains | `fight` | +0.1M |
| **P7 death, restart, exit** | death, the restart block | `die` | ~0 |
| **P8 ship** | the frozen scenario set, stress, size, every gate, the ship rule, docs, re-frozen baselines | everything | reserve >= 15% of headroom |

**The pacing item is build time.** A full game build takes ~2 h: 6,426 s with a counts-cache hit
and 7,254 s with a recount, MEASURED this week. Most rungs change the program, so most miss the
cache. Each pixel-identical reclaim ships alone. That makes **~15-20 full builds, ~30-40 hours of
machine time, strictly one at a time (rule 1)**. Everything that can happen in host tests,
`tests/fj` unit programs, the Python model or micro-probes happens there first.

---

## 9. Verification and measurement (verification mission, hardened by the red team)

- **State probe/injector.** The screen device holds `device_memory` while the program runs. A gate
  can therefore read every schema cell each frame through the build's label table and compare it
  with the oracle: state-exact, naming the first field that diverges. It can also write cells,
  which drives B0 and fuzzing. Its controls:
  - writing back unchanged state leaves ops and pixels identical;
  - a planted value reads back;
  - a label table shifted by one cell is rejected.
- **Completeness of the reset sets:**
  - an end-of-run memory walk against a clean image, as `m1_dirtymap` does;
  - the static no-`@`-local-data check on every new macro;
  - a per-rung LABEL-COVERAGE report across gates and fuzz. Rare paths -- restart, exit, a full
    fireball pool, barrel chains, deferral -- must be executed by some gate, or the walk proves
    nothing about them.
- **Gates.** `combat_gate.py` works in the `m2_std_gate` style, with three scripts:
  - `fight`: wake, chase, fire, pain, kill, pick up;
  - `hurt`: hitscan, melee, fireball, armor;
  - `die`: death, then restart equals a fresh boot.

  Their controls:
  - required event counters fail at zero;
  - `--selftest=rng|order|damage` must fail at a stated frame;
  - a memory poke at frame k must fail at k+1.

  Also `combat_fuzz.py`: injected states x key sets, one tic each.
- **The cap (CAP-22).**
  - The scenario set is 10 runs x 100 frames, key scripts frozen in `combat_scenarios_v1.json`,
    planned by an oracle autopilot. **How runs start is the owner's call (D2).** From spawn, 100
    frames cover at most ~1,600 units, so the 16 monsters behind the lifts are never reached.
    Checkpoint starts or longer runs fix that, and either changes what the metric means.
  - `--validate`: every run survives; at least 30% of frames have an awake monster in view; at
    least 5 kills, all three attack kinds and 3 pickups across the set.
  - Every 10th frame, the binary's state must equal the oracle's.
  - **Stress:** every monster awake around the costliest viewpoint with the pool full, reporting
    the per-frame maximum. The engine refreshes its op counter every 2^18 ops, so the maximum is
    accurate to +/-2^18.
- **The ship rule for features (D8).** msframe cannot judge a change whose pixels differ; it prints
  that the speed is meaningless.
  - Class S (pixels identical): the ship gate as today; B SLOWER never ships.
  - Class F (a feature): ships on the byte- and state-exact gates, CAP-22 and size. msframe's time
    is recorded as the price. An optional ceiling (~90 ms/frame = 22M at today's ~4.1 ns/op)
    catches a rate collapse the op cap cannot see.

---

## 10. Risks, and the cheapest experiment that retires each

| risk | experiment | cost |
|---|---|---|
| the picture's degradation becomes game rules (section 5) | the oracle compositor census on the scenario set | minutes, P0 |
| placement re-rolls the pins (6.8M once) | pin protection / a heat-ordered pool in flipjump; the pin report and pool declines on every build | a flipjump change, P1 first |
| fights cost more than modelled | the Python model on scripted fights, post-kill frames included, x MEASURED unit costs | minutes, P0 |
| the sprite column cannot get below ~20K | prototype the 3-byte fragment record in `tests/fj`, profile it | P1 |
| lifts are bigger than a rung | the lift design spike: floor sites, plane ids, size | days, P0 |
| modelled unit costs are wrong | fj micro-probes: jump-indexed access, D4 lookups, grid descent, octant classifier, rowmap lookup, aim-window write, target jump, one fireball tic | seconds each, P0 |
| collision cells are not exact | interval-arithmetic lists + exhaustive tests at 16.16 edge points + a mutated-entry control | P1 |
| a reset-set hole in a rare path hangs the game | no `@`-local data cells (static), label coverage per rung, the memory walk | P0/P1 |
| the HUD bar needs a device change | ~15 lines + a unit test in flipjump-151 (unpublished), or the side panel | P4 |

---

## 11. Owner decisions (they gate phase 1)

1. **D1 the cap -- DECIDED 2026-09-26 as recommended:**
   - (mean + p80)/2 on the combat scenario set <= 22M, with heavy frames reported (recommended);
   - or a per-frame maximum, which is not reachable without a renderer project first.

   The 22M cap replaces the 20M target in CLAUDE.md, `ship-gate.md` and gamespeed's
   `SPEED_TARGET`, for the game with combat.
2. **D2 the scenario set -- DECIDED 2026-09-26: runs start from CHECKPOINTS across the level**
   (injected states), so the lift areas are measured too. The owner freezes the set and B0 before
   phase 1. **v2 FROZEN 2026-09-26**: to the recommendation "plan a v2 [strafe, >= 50% movement,
   raised floors, an aftermath run, drawn = in view] ... then freeze v2 and its baseline", the
   owner answered "I agree with you on 1,2,3" (3 was that recommendation).
3. **D3 the compositor rules for gameplay -- DECIDED 2026-09-26 as recommended by the census (16):
   a + c + d + e, with b only for projectiles and barrels.** Drops and effects are ordered before
   monsters (a); corpses count as scenery (c); runtime things inside a leaf are drawn in depth order
   (d); "seen" and the aim window are recorded at column-open time, before the budgets (e);
   projectiles and barrels are exempt from the soft budgets (b, partly). Priced +0.11M on fight
   frames with the v2 column. **K raised from 3 to 6 the same day** (`world.K_HEAVY`).
4. **D4 time -- DECIDED 2026-09-26: one tic per frame**, so fights run at ~32-38% of DOOM's speed.
5. **D5 the simplifications of section 2 (B and C) -- APPROVED 2026-09-26:**
   - K = 3 and what it does to monster pace;
   - no infighting;
   - no weapon raise/lower animation;
   - the fireball pool of 8;
   - the rounded diagonals;
   - and the rest of the list.
6. **D6 the picture -- DECIDED 2026-09-26: the native-list sprite bank, and the HUD as a status bar
   at the bottom (with its flipjump device option; the 3D view becomes 84 rows).** Confirmed after a
   clarification as **option A, DOOM's layout: the SCREEN stays 160x100**; the bar takes its bottom
   16 rows and the 3D view is 160x84, as DOOM's 32-row bar leaves 320x168. Rejected: B, a bar added
   below a full 160x100 view (a 160x116 screen); C, numbers drawn over the picture every frame.
   The items were:
   - the native-list sprite bank, where every sprite pixel changes;
   - the HUD as a bottom bar (the view becomes 84 rows, so every 3D pixel changes, plus a flipjump
     device option) or a side panel;
   - the face;
   - palette flashes.
7. **D7 skill -- DECIDED 2026-09-26: all three, chosen in the menu as in DOOM:** easy 17 monsters
   (9 zombiemen, 2 shotgun guys, 4 imps, 2 demons), medium 29, hard 46. The budget is sized on hard.
   The image holds the union (53, as today); the restart block writes each skill's starting state.
   Berserk exists only on easy and medium.
8. **D8 -- DECIDED 2026-09-26: the class-F ship rule of section 9.** Features ship on the byte- and
   state-exact gates, CAP-22 and size; msframe's time is recorded as the price, and ~90 ms/frame is a
   tripwire (a rate collapse must be explained before shipping). Class S keeps "B SLOWER never ships".
9. **D9 flipjump changes -- DECIDED 2026-09-26:** a branch from `1.5.1`, a PR, merged into `1.5.1`.
   `1.5.1` is NOT merged to `main` and not published yet. The changes planned:
   - the HUD device option;
   - pin protection or a heat-ordered pool;
   - optionally the `if_flags` literal tables (R3).
10. **D10 the RNG -- DECIDED 2026-09-26:** DOOM's original 256-value table, unless another method is
    a medium-or-better speedup, in which case the cheaper one. The plan to make the original free:
    fold the table into each call site's outcome table at emit time (`outcome[i] = f(rndtable[i])`),
    so a call is one index increment plus ONE dispatch, the same as any generated RNG. A P0 probe
    compares it with an LFSR/xorshift in hex ops.
11. **D11 the map mechanics in scope -- DECIDED 2026-09-26: all of them.** The lift spike
    (`docs/gp-lift-spike.md`) set three defaults, which the owner did not overrule: door-style
    frame timing (9 up, 26 wait, 9 down), an instant floor switch (243 of 255 plane ids; animating
    it needs 259), and 16-unit lift steps. The mechanics: lifts, the floor switch, key doors, walk-over and blazing
    doors. They are needed to reach the whole level.
12. **D12 levels -- DECIDED 2026-09-26: E1M1 only.** Two or three levels would need the 35% target raised
    and the wide thing lists.

---

## 12. Evidence

- **MEASURED (blocked27, this session).** An instrumented copy of the flipjump-151 engine at
  73e09c0. It charges every wflip-chain, pool, stl-runtime and data-read op to the doom code that
  called it.
  - Validation: against an op-by-op trace of one frame's `bind_things`, per statement within
    +/-3.3%, and -0.13% over the whole sequence.
  - Negative control: attributing by address alone misses 80% of `ptr_index` (171 vs 894), so the
    check separates.
  - Op totals equal the stock engine's in every run, and the binding metric reproduced exactly
    (17,665,168).
  - Point location was measured by poking one thing's leaf cache dirty each frame, with pixels
    identical to an unpoked control.
  - Commands and outputs: session scratchpad `plan/measure/`, committed in P0.
- **Mission reports:** the conclusions are in this plan; the full reports are in this session's
  transcript
  (`C:\Users\tomhe\.claude\projects\C--Users-tomhe-Documents-doom-flipjump\29ddbecf-cbb7-4734-805a-36c0e391327d.jsonl`).
  Scripts are in the session scratchpad: `plan/spec`, `plan/ai`, `plan/combat`, `plan/render`,
  `plan/measure`. The reclaim and verification missions produced no scripts.

---

## 13. The top three might-be-problems, and how each is tackled in advance

1. **Placement re-roll.** The blocking pass re-picks which tables get the cheap pinned addresses
   whenever the table counts change. One deletion once cost ~6.8M ops/frame in lost pins, so any
   rung can swing by several million ops for reasons unrelated to its code. That would mask real
   costs, and could break the cap on its own.
   - **Measure it:** P0 builds a pin report. The profiler names the ~20 hottest shared words; every
     build then says whether their tables are still pinned, and how many tables the pool declined.
   - **Prevent it:** P0 designs, and P1 lands FIRST, pin protection in flipjump (a branch off 1.5.1):
     the pool places tables in heat order, or reserves the hot words' slots, so new tables cannot
     evict them.
   - **Price it before any feature:** the first gameplay build emits every new table and calls none
     of them. Its delta is the pure placement tax.
2. **The degraded picture becomes the rules of the game (section 5).** Sight and hits read a
   picture that is thinned out on purpose in crowded frames.
   - **Count it:** P0 runs a census on modelled fights.
   - **Decouple it:** sight and the aim window record at column-open time, BEFORE the degradation
     budgets, so degradation stays a pure drawing-cost tool.
   - **Protect what the player must see:** awake monsters, projectiles and drops are exempt from
     the soft budgets; corpses count as scenery.
   - Priced options go to the owner (D3).
3. **Fights cost more to draw than the budget holds.** A sprite column is ~30K, and corpses stay on
   screen for the rest of the run.
   - **Get the real number:** the fight line comes from the P0 model, post-kill frames included,
     not from assumptions.
   - **Cut the cost first:** the sprite column comes down (target <= 15K, section 14 #1) in P1,
     BEFORE any monster moves.
   - **Fallbacks agreed now:** the budget is sized on hard (46 monsters); easy (17) and medium (29)
     are the menu's other skills. Then K = 2, `DEG_HD_BUDGET`, and a smaller window. With sight and
     hits decoupled, degradation can cut drawing cost without changing the game.

Also watched: lifts are a bigger rung than they look (P0 spike); a reset-set hole in a rare path
hangs the game (static no-`@`-local check, label coverage); build time paces everything (15-20
builds).

---

## 14. The five costliest macros gameplay will lean on, and how each gets cheaper

Costs MEASURED on blocked27 (section 3); targets are estimates, each checked by a P0 micro-probe
before it is built.

| # | macro | cost today | why gameplay leans on it | how it gets cheaper | target |
|---|---|---|---|---|---|
| 1 | **the sprite column**: `sim.thing_record_body` + `sprite_runs` + the wall split in `seg_pass2_leaf` | ~30K per column (10.9K runs + 19.3K split emission) -- EMISSION ONLY; end to end (record + load + emission) ~42-54K in-game (S6b) | every monster, corpse, fireball and puff on screen; fights add 50-200 columns | a 3-byte fragment record with per-thing constants in slot registers written once per thing; one region walk instead of two; skip the wall split when the sprite covers the column's whole open window; run-lists precomputed per scale bucket, so a run is one lookup; `DEG_HD_BUDGET` 2 | ~~<= 15K~~ unreachable (a plain column is 15.9K); **v2: ~24-31K end to end, -40%, pixel-identical (S6b)** |
| 2 | **collision**: `sim.check_position` -> `check_block` -> `check_line` | 576K per call, 6.8K per line tested; ~613K per player try, 1.48M/frame | the player on every moving frame; every monster step | 32-unit cells with candidate lists (mean ~2 lines); line constants baked into D4 rows (no `read_table_packed`); static no-block verdicts for monsters' 8 directions; the cell lookup doubles as the point-location start | <= 40K per try |
| 3 | **runtime thing load + projection**: `sim.thing_load` + the projection in `thing_leaf` | 19.5K + ~11K (runtime 30.2K vs baked 15.4K) | every monster, corpse and fireball in a visited leaf, every frame | per-monster fixed cells and a jump into that monster's stub, instead of `ptr_index`/`read_hex` through `thpos` (a 16-nibble `read_hex` alone is ~7K); per-patch metrics via D4; a behind-the-viewer sign test before the full projection | <= 15K (baked parity) |
| 4 | **point location**: the BSP descent (`ptloc_walk`, and the collision seed walks) | 30.7K mean, 180K max; the seed walk 35.4K per try | every leaf change of a monster (7.4% of steps) or a fireball (most tics); every collision seed | a per-cell start node (the deepest node no point of the cell straddles), so the walk starts a few levels above the leaf; diagonal node constants multiplied by their absolute value (2.4 vs 10.7 schoolbook rows) | a few K mean |
| 5 | **column emission**: `emit_col_lines` | 15.9K per emitted column (~159 ops/pixel); 56.5 of 160 columns are dittoed today | the weapon sprite on EVERY frame, the HUD, more sprite columns -- each breaks a ditto | a "partial ditto" device option (a flipjump 1.5.1 PR): copy the top y rows from the previous column, emit only the rest, so a weapon column costs its bottom part; the HUD bar option; weapon columns as baked constant runs | weapon <= 0.1M/frame, from 0.2-0.5M |

Kept out of gameplay code entirely: `hex.div` (157K) and `fixed_mul_lo` (3.4K), by rule 3 of
section 4. The RNG is priced in D10 (one dispatch per call).

---

## 15. Phase 0 work streams (started 2026-09-26)

| stream | deliverable | where |
|---|---|---|
| S1 | the attributing profiler, committed, with its `--selftest` (the address-only attribution control) | `scratchpad/12m/profx/` |
| S2 | the state probe/injector with its three controls; then B0 by injector | `scratchpad/gp/probe.py`, `scratchpad/gp/b0.py` |
| S3 | the Python gameplay model: `gamedata.py` (DOOM tables), `rng.py`, `world.py` (monsters, weapons, damage, projectiles, pickups, barrels, K scheduler), host tests | `src/doomfj/`, `tests/host/` |
| S4 | the combat scenario set v1 (oracle autopilot), frozen by the owner (D2) | `scratchpad/gp/scenarios/` |
| S5 | the compositor census and the fight line (section 5, section 7) | `scratchpad/gp/census.py` |
| S6 | fj micro-probes: section 14's five cheaper versions, jump-indexed access, D4 lookups, the RNG variants, the octant classifier, one fireball tic | `scratchpad/gp/probes/` |
| S7 | the lift design spike: floor sites, plane ids, size, ops, rung plan | `docs/gp-lift-spike.md` |
| S8 | the pin report (hot words pinned or not; pool declines) with a control, and the pin-protection design for flipjump | `scratchpad/12m/pinreport.py` |

S4 and S5 wait for S2 and S3. Only one stream runs the game binary at a time.

---

## 16. Phase 0 results (2026-09-26)

Every stream's evidence is committed on `gameplay-p0`; the numbers below name their source.

| stream | result | commit |
|---|---|---|
| S1 profiler | `scratchpad/12m/profx/`, --selftest PASS (attribution vs an op trace, an address-only negative control); reproduces section 3 exactly | 98bd2d5 |
| S8 pin report | blocked27 keeps 20/20 hot pins; b26 lost 18/20 (its slowness explained); design `docs/gp-pin-protection.md`; ESTIMATE: heat-ordered indices in the top 20 groups cut their dispatch cost 2.54M -> 1.27M | 98bd2d5 |
| S2 probe/injector | `scratchpad/gp/probe.py`, `b0.py`, all controls PASS; a blocked build's cell holds `base | v<<6`; view-mode injection undercounts by the collision cost | 79bc691 |
| S3 model | `gamedata.py`, `rng.py`, `world.py`, `combat.py`; 129 gameplay host tests; DOOM data verified against two sources | 4849d3c, 78656db |
| S6 probes | jump-into-stub access 68-102 ops vs 0.9-2.9K by pointer; D4 lookup 47-100; the original rndtable composed per call site 82-96 (cheapest RNG, D10 settled); one player move try ~10K on 32-unit cells (derived) vs 613K today; point location from a cell's start node 5.9K; the jump macros must be declared SAFE in the pool | 44d0857 |
| S6b sprite column | v2 is pixel-identical on 1,648 columns and ~40% cheaper end to end; the <= 15K target is unreachable; partial ditto designed (`docs/gp-partial-ditto.md`); the weapon overlay 64-173K/frame | cea4c92 |
| S7 lifts | `docs/gp-lift-spike.md`: 243 of 255 plane ids, +0.02..0.1M ops, 0.18% size; lifts cannot crush on E1M1 | 3a23752 |
| S4 scenario set | v1 DRAFT: 10 checkpoints (hard), --validate PASS; **B0 on blocked27 = 14,972,920** (every frame state- and pixel-exact); found the gates' missing `sky=True` (fixed in a07e8b9) | 709682d |
| S5 census | the fight line and the D3 prices below | f2327b7 |

**The revised budget, on the combat set v1's run structure** ((mean + p80)/2 over 10 runs x 100 frames):

| line | effect | source |
|---|---|---|
| B0: blocked27 on the same routes, static world | **14,972,920** | MEASURED (S4) |
| the sprite side: fights with the recommended D3 + the v2 column + the skill filter | **-0.95M** (fights alone +0.52M; v2 and the filter pay for them) | S5, measured unit costs |
| monster AI (1.71 heavy acts/frame measured on the set x ~20-34K modelled, + per-monster slots) | +0.07 .. +0.1M | S4 population, S3a model, S6 primitives |
| combat logic, weapon overlay, effects, lifts, HUD | +0.2 .. +0.4M | models (S3b, S6b, S7) |
| reclaim: persistent lists / per-move rebind | -0.44M | MEASURED cost of bind_things (S1) |
| reclaim: player collision on the cells | -0.4 .. -0.8M (the set moves on 29% of frames; v2 >= 50%) | S6 derived |
| reclaim: heat-ordered pool indices | -1.27M | ESTIMATE (S8), a build must confirm |
| **projected, before placement** | **~12.2 .. ~14.3M** (and ~16.9M with NO reclaim at all, today's column, every model x1.11) | |
| placement re-roll | +/- up to ~6M unless pins are protected | S8 |

**What phase 0 changed.** The cap is not tight. The gameplay's own cost is ~1-2M on this set, and
the sprite work is more than paid for by the cheaper column and the skill filter. The only threat
left that could consume the margin is placement, which is why pin protection stays P1's first item.

**Recommendations that need the owner:**
1. **D3 (compositor rules): a + c + d + e, with b only for projectiles and barrels** (S5).
   - a: drops and effects before monsters;
   - c: corpses count as scenery;
   - d: depth order among runtime things in a leaf;
   - e: "seen" and the aim window recorded at column-open time, before the budgets.

   Priced at +0.11M on fight frames with the v2 column. It takes small things hidden from 0.62 to
   0.09 per frame, depth inversions from 5.53 to 1.12, and the seen-vs-sight gap from 0.19 to 0.
   (e) alone does not fix aim (17.0% of frames still differ at column 80): the aim window should
   record the radius box's span when the column opens (a design note for P4).
2. **K from 3 to 6.** On the set, K = 3 defers a monster on 195 of 1000 frames (166 of them behind
   the lifts). The average AI cost does not depend on K, because the demand is what it is (1.71
   heavy acts per frame); K only bounds the worst case, and the measured primitives shrank that
   bound. K = 6 covers the set's peak demand (~5 per tic at 14 awake), so monsters keep DOOM's pace.
3. **The scenario set v2 before freezing:**
   - strafe in the model;
   - movement on >= 50% of frames (v1: 29%, gamespeed 87%);
   - floors raised to >= 8 kills, >= 6 pickups, >= 3 doors;
   - one "aftermath" run that starts among corpses;
   - "in view" = drawn (the census wiring).

   Then the owner freezes v2 and its B0.

**Left in phase 0:** the scenario set v2 and its freeze; the aim-window design note; the D3 and K
decisions. Then P1, starting with pin protection.

**DONE 2026-09-26:** D3 and K = 6 decided; the aim note (`docs/gp-aim-window.md`, DOOM's diagonal
width adopted); the set v2 FROZEN (843f28a) with B0 17,760,774 (proxy 18,107,313); the final
census on v2 (bb7179c). The final budget is `docs/handoff-gameplay.md` section 8.
