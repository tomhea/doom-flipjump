# M7 P3 -- monsters alive (design)

`docs/handoff-gameplay.md` section 10, "P3 -- monsters alive": first a build that EMITS every new table and calls none
of it (its delta is the pure placement tax); then the state machine, the K-slot scheduler, the RNG, animation and
rotation, waking, chase on the cells, thing collision, per-move rebind, doors opened by monsters, D3's compositor
rules. Budget +0.3M on the binding metric. This document is the rung plan and the rules every rung keeps.

## 0. Where we start (measured on blocked36, 2026-09-29)

Nothing in fj runs a monster. The 68 RUNTIME things (every monster of the union image plus the things sharing a
monster's spawn leaf, WAD order, index `t`) are drawn from `thpos_rt` through the leaf lists `sshead`/`thnext`, each
with ONE baked sprite view (frame A, rotation 1, per type: `things.thing_rows`). Nothing writes those cells during
play; NEW GAME's `restart_lines` puts them back. The model (`doomfj.world`) runs all 53 monsters.

Pieces that exist and P3 uses (the fj side is mapped in `scratchpad/gp/probes` and the modules named):

| piece | where | state |
|---|---|---|
| D4 dispatch tables | `lut_generator.generate_dispatch_table_fj` -> `<label>.lookup dst, idx` | used by the renderer |
| a 1-nibble jump into code | `sim.jump16` (SAFE in `build_blocked.SAFE_TABLE_MACROS`) | used by collision, movers |
| per-state blocks | `lut_generator.generate_state_switch_fj` -> `<name>_go idx` | used by door segs |
| leaf relink | `sim.leaf_link` / `sim.leaf_unlink` (P1.3) | tested, not emitted |
| point location | `ptloc_walk` (emitted, uncalled); the seed descent `e1m1_dsccs_walk` | |
| collision cells | `collision.cell_lists(rows, radius)` | player radius 16 only |
| the sprite bank | `_lines_sprite_bank` -> `anim_index {(sprite, frame, rot): view}` (306 views) | bound, unread |
| RNG, octants, AproxDistance, the window copy | probes only (`scratchpad/gp/probes/s6/probes.py`) | |

## 1. The rule that makes partial rungs shippable: a MODEL MODE per rung

A rung ships a binary that is byte- and state-exact against the model -- so a rung that implements only part of the
monsters must be exact against a model that does only that part. Every rung adds a named mode to the model itself
(`World(monsters=...)`: `"static"` today, `"idle"` P3.1, `"awake"` P3.2), never a re-implementation in an oracle: the
gate oracles run the model's own monster phase through a `MonsterPhase` frame (as `DoorPhase`/`MoverPhase`), with the
mode as a parameter. The FULL model is the last mode; B0 on the frozen set is exact only from the rung whose mode
equals everything the set exercises (section 5).

## 2. Architecture (FlipJump rules, handoff section 6)

- **Per-monster cells at fixed addresses, per-monster code stubs.** Slot `m` = the model's monster slot (0..52, the
  union image); `t(m)` its runtime-thing row. A runtime index selects CODE, never data.
- **One schema.** The new monster cells' fj declarations are GENERATED from `world.build_schema`'s monster fields
  (widths, counts, level-start values) -- rule 7 made real for P3's cells -- and the persist set, `m5_setfile`, the
  probe's `game_cells` and the gate state read the same generator.
- **The state table** is one D4 lookup on the 2-nibble state index: next (2 nibbles), tics (1), action id (1), view
  group (2). 127 monster-reachable states, 77 (sprite, frame) groups, tics in {2..10, forever}.
- **The scheduler**: the unrolled 53-slot chain entered at `sched_cursor` through a jump table; per slot a tic test
  and decrement (cheap), a READY slot's state step (the lookup, the zero-tic chain bounded as the model's), cheap
  actions inline, heavy ones through the window: the slot's cells copied into one fixed window, ONE shared leaf per
  action, copied back; `used` counts heavy acts against K = 6, the first deferred slot is the next cursor.
- **The RNG** (D10): the rndtable folded into outcome tables -- the monster stream's four P3 call sites into one
  (`mrnd`) -- one index cell per stream.
- **Animation and rotation**: the drawn view = (the state's view group, the rotation from the viewer angle against
  `mon_facing`) -> the thing's sprite rows read through the view (not baked per thing); mirrored views need the column
  DDA to walk `u` downward. The ORACLE draws the same: `reference_model` gains per-thing (frame, rotation) input, one
  rotation rule for both sides.
- **Movement** (P3.2): monster collision cells for radius 20 and 30 with `ML_BLOCKMONSTERS` and the drop-off rule,
  solid things as boxes; `P_Move`/`P_TryMove` on them; the relink by `sim.leaf_link`/`leaf_unlink`; `thpos_rt` written.

## 3. The rungs

| rung | what | class | model mode | gate |
|---|---|---|---|---|
| **P3.0** | every new TABLE emitted, nothing calls it | S (no pixel moves) | static | all gates byte-exact, ops unchanged but placement; the tables run in `tests/fj` against their Python source |
| **P3.1** | idle life: the scheduler, the state machine, animation and rotation of monsters that never wake | F | idle (A_Look sees and hears nothing) | + a monster gate: poked states, N frames, state- and byte-exact |
| **P3.2** | awake: sight (section 4), sound, A_Chase, P_Move on the cells, P_NewChaseDir + RNG, relink, monster doors and lifts, the attack DECISIONS (effects are P5) | F | awake | + fights: B0 on the frozen set with the monsters injected per frame |
| **P3.3** | D3's compositor rules for moving things (depth order inside a leaf, drops/effects before monsters) -- the depth order SHIPPED 2026-10-03 as blocked46 with P3.4 (8.6); drops/effects wait for P4/P5 | F | awake | B0 pixel-exact on the set |

## 4. Open decision for P3.2 (the owner's, with numbers before any code): the sight rule

The model's sight is exact 2D line of sight (`World.los_to_player`: the segment against one-sided, statically closed
and shut-door lines, on 16.16 integers). The handoff (7.2) plans the fj on "seen" -- drawn at column-open time (D3 e)
-- plus a near-trace. The phase-0 census (`census_out/s4v1`) measured the two disagree on 0.19 monsters per fight
frame with sight but not drawn (mostly BEHIND the player: a seen-rule monster would not wake on a player who walks
past with his back turned) and 0.02 drawn without sight. Two ways:
- keep LOS in fj: a segment test against the candidate lines of the cells between monster and player; cross products
  of 16.16 numbers are runtime multiplies (rule 3) -- price it with the probes before choosing;
- move the model to "seen" + near-trace: a behaviour change, so a NEW set version (v5) and the owner's approval.
Measured before P3.2 starts; the owner decides.

## 5. Measurement across the rungs

gamespeed and deg_gate on every build; msframe A/B against the shipped binary; B0 on the frozen set v4 is the CAP
number from P3.2 (monsters injected from the full model each frame); until then B0 v4 stays the static-world number
it is today, recorded per rung.

## 6. P3.0 -- the tables, uncalled (as BUILT; the kill criteria are `docs/gp-ledger.md`'s)

Emitted in the game tier only, reachable by nothing (`doomfj.monstercode.p30_tables_fj`):
1. `mstate` -- the monster state table over `gamedata.STATE_INDEX`: next, tics (15 = forever), action id, view group
   (127 monster-reachable states, 77 view groups). The 127 include the types' `raisestate` chains (20 `*_RAISE*`
   states) that the model never enters -- no Arch-vile; harmless, and P3.1 may drop them.
2. `mturn` -- `world.turn_toward` over (movedir << 4 | facing), movedir 8 keeping the facing.
3. `mopp` -- P_NewChaseDir's opposite direction, `gamedata.OPPOSITE`. (`mdiag`, the diagonal table, is NOT built:
   `gamedata.DIAGS` is indexed by two sign bits the chase code computes, so P3.2 bakes it as code.)
4. `mrnd` -- ONE outcome table for the monster stream's four P3 call sites, folded (D10): the value (A_Chase's
   missile roll), `> 200` and `& 1` (P_NewChaseDir), `& 15` (the walk's movecount), indexed by the post-increment
   state.
The monster collision cells (radius 20 / 30 with ML_BLOCKMONSTERS) are NOT in P3.0 -- their stubs are shaped by
P3.2's rules (BLOCKMONSTERS, the drop-off); priced for P3.2 at a player-sized cell set each.
Kill criteria as declared: each table on the engine over every entry against its source, a mutant caught; every
gate byte-exact, ops equal to blocked37's but for placement; size <= +0.1M words; msframe not B SLOWER (class S).

## 7. P3.1 -- idle life (as BUILT; the kill criteria are `docs/gp-ledger.md`'s)

**Model**: `World(monsters="idle")` -- A_Look returns at once (nothing wakes); every other rule is the full model's.
In idle every monster loops its spawn states (a `STND` pair, 10 tics each, on E1M1's types). The gate oracles step it
through `doomfj.monsters.MonsterPhase` (the model's `_monsters_phase`, once per game frame after the player).

**The one view rule** (`doomfj.monsters`): the drawn view is the state's frame at DOOM's rotation
`((R_PointToAngle(viewer -> thing) + 0x90000000) >> 29) - facing, mod 8, + 1`, read off the WAD's lump names
(`wall_renderer.anim_patches`); a second-half lump is drawn MIRRORED. The oracle takes it through
`render_wall_frame(thing_views=...)` (the view's art; a mirrored view's column is `dw - 1 - u`).

**fj**, each piece with a `tests/fj` harness against the Python rule before it joins the program:
1. **The cells**: `mon_state` (2 nibbles), `mon_tics` (1), `mon_facing` (1), `mon_active` (1) per monster slot of the
   union image, generated from `world.build_schema` (rule 7), persisted (`MONSTER_PERSIST`), reset by NEW GAME to the
   skill's spawn values.
2. **The tic** (`monstercode.mon_tic_lines`): per slot, unrolled -- inactive or forever: nothing; else decrement, and
   at 0 (READY) two `mstate` lookups: the current state's next, then that state's tics. It runs NO action: a
   monster state never has 0 tics (asserted, so a step is one state) and idle reaches no action but A_Look, a no-op
   there (asserted). Idle has no heavy action, so the K-slot scheduler comes with P3.2.
3. **The rotation** (`monstercode.rotation_leaf_lines`, `mon_rot_leaf`): `proj.point_to_angle` viewer -> thing
   (16.16, exact), then ONE 2-nibble lookup `mrot` on (the angle's top nibble, facing) -> the rotation index. The
   `+ 0x90000000` is folded into `mrot` (its low nibbles are 0, so it only moves the top one); there is no add.
4. **Per-view sprite rows**: the thing row tables (`throw` hot / `throwc` cold) gain one row per distinct monster VIEW
   (lump, mirrored) after today's per-thing rows; the cold row carries the mirror flag. A runtime thing's row index is
   no longer `ti`: a jump on `ti` into its stub (rule 1) sets it -- a static thing its own row, a monster
   `VIEWBASE + mview[group, rot]` from its slot's cells. `sprlt` widens to every row's heights.
5. **Mirroring** in `frame.thing_record_body` (`rec_mirror_flag`, `rec_mirror_u`; the record's `mir, mirf, miru`):
   a mirrored row (dw bit 7) takes column `dw - 1 - u`.
6. **Two-byte light classes** in the animated tier (`ltw` = 2; the high byte `sp_lt_hi`, passed to the thing pass as
   `lthi`): the monsters' views need 540 (light, height) classes, past one byte.
Gates: every gate's oracle runs `MonsterPhase` and draws `thing_views`, byte- and state-exact (the monster cells read
at every present). There is NO separate monster gate: the controls are the fj harnesses' mutants (tic, `mrot`,
`mview`, the tables).

## 8. P3.2 -- awake (the plan; the sight decision comes first)

**What wakes and moves** (the model's `full` mode, `world.py`): A_Look (sound by region -- `snd_alert` per sound node,
shots only until P4 fires; sight by `self.sight`), then A_Chase every chase state: reaction and threshold count down,
the facing turns toward movedir (`mturn`), melee/missile DECISIONS (the attack states run; their effects are P5), and
P_Move one step along movedir (speed per type, `step_delta`'s 8/6 and 10/7 diagonals), P_NewChaseDir with the RNG
(`mrnd`) on a blocked or spent move, capped at 6 tries (D5). A step goes through P_TryMove: lines (with
ML_BLOCKMONSTERS), the step-up/height/drop-off rules, solid things as boxes; a failed step in a door's monster use box
presses the door (`dreq`, D5); a WR line crossed triggers its lift. The leaf lists relink per move (P1.3's
`sim.leaf_unlink`/`leaf_link`), `thpos_rt` takes the new position.

**Cost and structure**: every heavy act (A_Chase, A_FaceTarget, an attack state) takes one of K = 6 slots per tic in
the model's cursor order; the slot's cells copy into one fixed window, ONE shared leaf runs the act on the window
(compile-time addresses, rule 1), the cells copy back. The monster collision is its own cell set: radius 30 lists
(a superset of 20's, measured 17,666 entries against the player's 11,667) with the BLOCKMONSTERS rows.

**The open decision -- the sight rule** (section 4): exact 2D LOS in fj needs 16.16 cross products per candidate line,
runtime multiplies against rule 3; the handoff's "seen" rule is cheap but a behaviour change (a new set version, the
owner). To be decided with the owner on measured numbers: the LOS probe's price per check, and the seen rule's effect
on the frozen set (how many v4 runs part, their criteria).

### 8.1 The sight decision's numbers (MEASURED 2026-09-30, `docs/ship-evidence/p32_sight_census_v4.log`)

The full model replaying the frozen set v4 (11 runs, 1,100 frames, `scratchpad/gp/sight_census.py`):
- **4.32 sight checks a frame** (p80 6, max 10) -- nearly all A_Look of sleeping monsters, each every 10 tics;
- **83.5 candidate lines per check** after the bounding-box reject (p80 139, max 406): **361 line tests a frame**;
- only 6% of checks come back true (295 of 4,757).
An exact 2D LOS in fj tests each candidate with 16.16 orientation products: up to four per line, two multiplies
each, at `hex.mul 8` ~7K ops (the cost model, UNVERIFIED this session) -- order 10M ops a frame as the model tests
today, ~1-4M even if a cell walk cut the candidates tenfold: an order of magnitude past P3's +0.3M. The "seen" rule
(handoff 7.2, D3 e) costs a flag write per drawn monster; its behaviour differs from LOS for 0.19 monsters per fight
frame with sight but not drawn (mostly behind the player) and 0.02 drawn without sight (phase 0's census, s4v1). It
is a behaviour change: a new set version (v5) and the owner's approval before any P3.2 binary is measured.

### 8.2 The sight rule, DECIDED (the owner, 2026-09-30: "Seen rule + set v5")

The model's sight moves from exact 2D LOS to the handoff's rule (7.2, D3 e); the frozen set is re-planned as v5
under it and put to the owner with its criteria and B0 before it is frozen.
- **seen** (`mon_seen`, per monster): set by the picture of the PREVIOUS frame -- the monster's sprite projects in
  front of the viewer at the BASE monster size cull (`MIN_SPRITE_H_MONSTER`; the soft budgets' raise does not
  apply) and at least one of its columns is still OPEN (no wall drawn there yet) when the walk reaches its leaf,
  tested BEFORE the count budgets (D3 e: sight must not depend on degradation). The fixed base cull stays: it is not
  a degradation, and keeping it lets the fj reuse the draw path's projection (a `fixed_div`, ~38.5K) -- an extra
  projection only when a count budget is spent or the soft raise rejected the monster.
  `reference_model.render_wall_frame(seen_out=)` records it; the fj records it in the thing pass. Level start: none.
- **waking sight** (A_Look's ambush test and P_LookForPlayers, A_Chase's re-acquire included): seen, or the
  monster's sector REJECT-visible from the player's (E1M1's REJECT lump, `assets/freedoom1.wad`) AND
  P_AproxDistance <= 128. The facing test (behind and beyond MELEERANGE: not seen) applies as before.
- **attack sight** (the melee and missile range checks): seen, or within 128 units and the exact 2D LOS
  (`World.los_points`) -- the handoff's "short trace over the collision cells" for a near monster not drawn.
- The model steps it through a hook: after each tic, `doomfj.sight.SeenHook` renders the world as the binary draws
  it (positions, views, what is hidden) and writes `mon_seen`. A World without the hook sees nothing drawn.

### 8.3 P3.2's rungs (each a model mode, a build, its gates)

P3.2 is too large for one build, so it ships in three, each against a named model mode:
- **P3.2a "wake"**: `mon_seen` recorded by the fj thing pass (the monster's projection and one open column, before
  the budgets -- inside the column loop for a drawn monster, a short scan for one the budgets or the size cull
  turn away; per monster SLOT `thseen[m]`, which the monster's slot code reads at a compile-time address), A_Look's
  wake (seen, or the REJECT row and <= 128 -- sound waits for P4's shots), the K = 6 scheduler with the window and
  the shared A_Chase leaf -- whose counters, turn and target run but whose MOVE and attack decisions wait (mode
  `wake`: awake monsters run A_Chase's turn toward their movedir -- DI_EAST until P3.2b's NewChaseDir sets one --
  in place; they do not yet turn toward the player).
  SHIPPED 2026-10-01 as blocked43 (`docs/gp-ledger.md` P3.2a). As built: the mark is `frame.rec_seen_mark`, which
  re-arms the pointer library at its caller's next pointer (arm5 moves five hexes only), and `thseen` is in the pin
  veto `selfreset.POINTER_READ_CELLS` -- the two rules the dead builds blocked41 and blocked42 taught.
- **P3.2b "chase"**: P_Move / P_TryMove on the monster cells (radius 30 lists with ML_BLOCKMONSTERS, the step,
  height and drop-off rules, the things as boxes), P_NewChaseDir with `mrnd`, the relink (`sim.leaf_unlink` /
  `leaf_link`), `thpos_rt` written, monster doors (`dreq`) and WR lifts.
  SHIPPED 2026-10-02 as blocked44 (`docs/gp-ledger.md` P3.2b).
- **P3.2c "decide"**: the melee and missile decisions and their states (A_FaceTarget; the attacks' EFFECTS are P5,
  so the mode runs the attack states without damage).
  SHIPPED 2026-10-02 as blocked45 (`docs/gp-ledger.md` P3.2c).
- After the three: **P3.3**, the depth order inside a leaf (8.6) -- SHIPPED 2026-10-03 as blocked46, one build with P3.4
  (`docs/gp-ledger.md` P3.3, P3.4). Phase 3 is complete.
The frozen set v5 is the full model; B0 on it is exact from P3.2c on, when the mode's tic equals the model's for
everything v5 exercises but damage.

### 8.4 P3.2b "chase" -- the design (numbers first: `docs/ship-evidence/p32b_chase_census_v5.log`)

**The model mode** `chase`: A_Chase whole except the melee and missile decisions (P3.2c) -- the movecount, P_Move,
P_NewChaseDir (the D5 cap of 6 distinct tries), a failed step in a monster door's box pressing it, the WR lifts a
step crosses, the relink. It consumes no random numbers the decisions would (the missile range's `_rand`), so it
is its own model, gated like `idle` and `wake`.

**The numbers** (the full model on v5, 1,100 frames): P_Move position tests per frame mean 2.32, p80 4, max 17;
moves 1.70; relinks 0.10 (max 2); NewChaseDir 0.36 (capped 0.03); monster door presses 1 in 1,100 frames; 46
active monsters (53 slots: radius 20 x 43, 30 x 10; speed 8 / 10; height 56; none DROPOFF or FLOAT); 22 barrels
and 57 decorations block. Refusals by verdict: wall 224, dropoff 207, step 145, thing 83, monster line 19,
height 0 -- every rule is live, the drop-off one included.

**The pieces** (each on the engine against the model in a tests/fj harness, with mutants, before the build):
1. *The monster cells*: a second `collision_cells_fj` set at radius 30 (a superset of 20's lists; the box uses the
   slot's true radius at run time, so the test is exact for both), its rows with ML_BLOCKMONSTERS folded into
   blocking and each line's LOW floor (the drop-off), under its own prefix, testing through the one
   `sim.line_test drop, lf, dropc` -- the monster cells pass `1, ca_lf, cp_drop` (track the drop-off), the player's
   `0, 0, 0`, which adds no op to his expansion (`collision.collision_cells_fj`'s `lowfloor`). The rules of
   `try_move_monster` in a new `sim.try_move_mon`: ceil - floor < 56, ceil - z < 56, floor - z > 24, and
   floor - dropoff > 24.
2. *The seed and the leaf*: the baked point location every thing uses (`ptloc_walk`, integer position) and a
   three-nibble jump on its leaf to a stub that sets the seed heights -- a mover's leaf by the mover's state
   (`monstermove.monster_seed_fj`; standalone-testable, where a third BSP descent would run only inside the
   renderer). The leaf stays in `ptss` for the relink.
3. *The things*: the other monster slots unrolled (the mover's own `mon_active` cleared around its tries, so no
   run-time self test), the player's box at 16.16, and the static barrels and decorations as per-cell box lists
   in the monster cells' stubs (`thing_cell_lists`, the lines' exact-interval rule; a presence cell each where
   the thing can be absent -- `bar_solid` for a barrel, a per-skill flag for a decoration some skill lacks).
   A thing refusal latches `cp_ok` like a wall: fj reads only ok and the lines' floor, so the model's
   things-then-lines order is free.
4. *Positions at run time*: the slot code reads its monster's integer position from `thpos_rt` (P3.2a baked the
   spawn), keeps `mon_floorz`, `mon_movecount`, `mon_rng` and the monster's SECTOR per slot, and selects the REJECT
   row by that sector at run time (the rows of every sector a monster can stand in).
5. *NewChaseDir and P_Move* as shared leaves; the step table `step_delta(speed, dir)` compile-time.
6. *The relink*: `sim.leaf_unlink` / `sim.leaf_link` on the runtime thing index (the model links by mobile index:
   the emitter asserts the two orders agree), `thss_rt` and `thpos_rt` written.
7. *Triggers*: the lift walk-over test with the monster's old and new position and radius (`_crossed_lines` takes
   its registers as parameters -- a fan-out edit); a refused step inside a monster door's use box sets `dreq`, and
   the door tic takes it for those doors.
7b. *Doors and lifts react*: a closing door at its pass step reverses when a live MONSTER touches its lines
   (`World.door_touched` counts them; P2b's fj tests only the player -- sound while monsters stood still); and a
   moving lift sets the floor of every active monster standing in its sector (P_ChangeSector,
   `_door_phase_scene`), so each slot keeps its sector.
8. **Live leaves** -- ALREADY SOUND (checked 2026-09-30): the emitter asks `thing_live_subsectors` on the doors-OPEN
   map (`_dsecs_open`, M2-R3), so an opened door's leaves are live. The hazard it guards: on the stored map the
   predicate excludes a sector with no height AT SPAWN -- every closed door. A monster
   that walks through an opened door would stand in a pruned leaf and vanish with no error, the bug class that
   function exists to prevent. The tier with moving monsters keeps every door and lift sector live.

**Cost, estimated** (to be measured): a try is one descent (~32K, the player's measured seed walk), the cells
(~20K) and the thing loop (~30K) -- ~80K; 2.32 tries a frame is ~0.19M mean, 0.32M at p80.

**As built** (SHIPPED 2026-10-02 as blocked44, sha256 `06e8912c4d4d3b96`; `docs/gp-ledger.md` P3.2b): measured
+366,657 on gamespeed's binding (14,086,236 -> 14,452,893), +898,983 on v5's (15,299,168), +385,240 on profx's mean
frame; size +5,017,552 words (33.38% of 2^27). The door contacts are one leaf per (door, radius) on `dc_x` / `dc_y` --
inlined per monster they were 8,056 compares (~14.6M ops) and the first build overran the table pool (ee6761c).
P_ChangeSector runs outside the `lvdone` exit guard here; P3.2c's branch fixes it (796cdcc).


### 8.5 P3.2c "decide" -- the design (as written; numbers: `docs/ship-evidence/p32c_decide_census_v5.log`, by `scratchpad/gp/p32c_decide_census.py`)

**The model mode** `decide` (`World(monsters="decide")`): A_Chase whole -- `justattacked` -> clear it and
P_NewChaseDir; the melee decision (a melee state, P_AproxDistance < MELEE_REACH (60), the attack sight); the
missile decision (a missile state, movecount 0, the attack sight, reaction 0, then `P_Random < min(dist - bias,
200)` refuses); the decided state entered with its A_FaceTarget. The attack states' actions face and DRAW exactly
as the full model's (`combat._attack_rolls`: 3 draws per bullet, the claw's and the bite's one each when in melee
reach) and apply nothing -- damage and the imp's fireball (which draws from `rng_fx`) are P5, so the monster stream
is the full model's and P5 adds effects without moving a random number (`tests/host/test_monsters_decide.py`: the
decide mode runs in lockstep with the full model's monsters until the player dies; control: a decide mode without
the draws parts). `justhit` is 0 until damage (P4) and `ambush` matters only to sound (P4): neither is held in fj.

**The fj** (`doomfj.monsterdecide`, `doomfj.monstersight`, `monstercode.p32c_slot_lines`):
- `mm_decide` replaces `mm_chase` in the slot's move call, with the decision's inputs in the move's context; a
  decision returns `mm_dec` (1 melee, 2 missile) and the facing, and the slot enters the state (`mon_justattacked`
  per slot, persisted).
- The slot's action dispatch runs A_FaceTarget and its type's attack action through `md_attack` (the facing,
  then `mon_rng += draws`).
- `mm_as`, the attack sight: seen, or within NEAR and `sl_los` -- the exact 2D LOS of `World.los_points` from the
  monster's integer position to the player's 16.16 one. The candidates are a per-256-unit-cell list of the sight
  segments whose box reaches the cell grown by NEAR + 1 (a superset: `test_monster_sight_fj`'s
  `test_the_cell_lists_hold_every_candidate`, with the margin-0 control); a door's, a lift's or the switch's segment
  counts at the states its opening is shut (the model's height rules, one mask per segment); the touch is
  `segments_touch` on four orientation signs, each a 48-bit product difference (`hex.mul_lo 12`), the player's
  16.16 coordinates kept whole -- the operands are bounded at emit time from the map's extent (< 2^13 units).
- Harnesses: `tests/fj/test_monster_sight_fj.py` (900 traces, every door and lift state, touches and collinear
  traces; controls: the dynamic segments always shut, strict crossings only, no margin, o4 without its o3 term) and
  `tests/fj/test_monster_decide_fj.py` (120 frames against the decide mode; controls: no roll, no LOS, justattacked
  never read, no draws).

**As built** (SHIPPED 2026-10-02 as blocked45, sha256 `25957324521286dd`; `docs/gp-ledger.md` P3.2c): measured +9,795
on gamespeed's binding (14,452,893 -> 14,462,688), -211,944 on v5's (15,087,224), -12,572 on profx's mean frame; size
+726,572 words (33.92% of 2^27). The near LOS went from 5.52M to 0.19M ops before the build (e24ab75): a segment XORs
its constants into zeroed registers (`hex.xor_by`, one op a nibble) and the shared `sl_seg` does the box reject, the
ends and d, zeroing on every exit. P_ChangeSector runs inside the `lvdone` exit guard (796cdcc,
`tests/fj/test_change_sector_fj.py`).

### 8.6 P3.3 -- depth order inside a leaf (D3 d; numbers: `docs/ship-evidence/p33_depth_census_v5.log`)

The walk is front-to-back and a sprite pixel is written once, so inside one leaf the NEAR thing must be drawn
first. Until P3.3 a leaf's runtime things were drawn in the list's ascending index order (`sim.thing_pass`), which
once monsters move draws a far monster over a near one. The census on v5 (the full model, every frame drawn as the
binary draws it): depth order changes 25 of 1,100 frames (2.27%), 4,357 px, up to 915 px on one frame
(R0-aftermath 83-99); leaves holding 2+ active monsters: 12.5 a frame (they spawn in groups).

**The rule** (the oracle's `render_wall_frame(rt_depth_order="aprox")`, carried by `GAME_RENDER_KW` -- the emitter
reads THAT key): a leaf's baked things first as before, then its runtime things by P_AproxDistance from the
player's integer position, ties by ascending index. The true view depth `tz` would need four fixed multiplies per
thing and a per-thing store behind pointers (the pin veto and the arm windows that killed blocked41/42); the
aprox key orders differently from `tz` on 2 of the 1,100 frames (28 px) -- things overlap on screen only along
nearly one ray, where distance order IS depth order.

**Scoped to the game tier** (pre-review r1): the hosted tiers move runtime things too but still walk index order
(`sim.thing_pass`), so their gates (m1_gate, m2_r3_gate, m2_r4_gate, m2_pass_probe) ask the oracle for
`HOSTED_RENDER_KW` = `GAME_RENDER_KW` without the rule (`test_oracle_calls_in_step` pins which gate asks for which).
`monstercode.depth_walk` RAISES when the game setting asks for the order and the monster mode cannot emit the walk
(idle, wake); `render_wall_frame` refuses an unknown `rt_depth_order`. The key is `reference_model.aprox_depth_key`
over the ONE `fixedpoint.aprox_distance` (`world.aprox_distance` is the same function).

**The fj** (`sim.thing_pass_depth`, the game tier's walk): a leaf with one thing draws it as `thing_pass`; a longer
list is drawn in ROUNDS, each scanning the list for the least (key, index) above the last one drawn -- no
per-thing storage, pointer READS only, `td_*` named registers (monstercode.P33_DECLS). n things cost n^2 key
reads; the lists are short (2-5). Harness: `tests/fj/test_thing_pass_depth_fj.py` (160 records x 4 leaves of 1-4
things, ties and reorders, a budget stop `tstop` after k draws counted across leaves, all 13 cleared registers zero
after every leaf; strict controls: the first candidate taken, the key without dy, the tie toward the later index,
either tstop test removed -- the order parts, registers clear -- and sp_lt's clear narrowed -- the order holds,
sp_lt alone dirty); `tests/host/test_depth_order.py` (frame 96: the order changes the
picture, aprox = tz there). D3 a (drops and effects before monsters) waits for P4/P5, which create them.

**As built** (SHIPPED 2026-10-03 as blocked46, sha256 `b7c9e110be1494d8`, one build with P3.4; `docs/gp-ledger.md`
P3.3 / P3.4): measured +780,607 on gamespeed's binding (14,462,688 -> 15,243,295), +472,852 on v5's (15,560,076),
+590,176 on profx's mean frame -- P3.4's help screen is in the same numbers; size +355,886 words (34.19% of 2^27). The
walk's pointer register is the global `td_p`, so the heat list followed it (`heat_blocked27_p33`, 7e97a5a) after r0's
pin report left 3 hot words unresolved. v5's frozen record (its drawn census, F4) must be re-recorded under the rule
(`p33_v5_validate_depth.log`).
