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
| **P3.3** | D3's compositor rules for moving things (depth order inside a leaf, drops/effects before monsters) | F | awake | B0 pixel-exact on the set |

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
  front of the viewer and at least one of its columns is still OPEN (no wall drawn there yet) when the walk reaches
  its leaf, tested BEFORE the thing budgets and the minimum-size cull (D3 e: sight must not depend on degradation).
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
  turn away; per runtime thing `thseen[t]`, which the monster's slot code reads at a compile-time address), A_Look's
  wake (seen, or the REJECT row and <= 128 -- sound waits for P4's shots), the K = 6 scheduler with the window and
  the shared A_Chase leaf -- whose counters, turn and target run but whose MOVE and attack decisions wait (mode
  `wake`: awake monsters turn toward the player in place).
- **P3.2b "chase"**: P_Move / P_TryMove on the monster cells (radius 30 lists with ML_BLOCKMONSTERS, the step,
  height and drop-off rules, the things as boxes), P_NewChaseDir with `mrnd`, the relink (`sim.leaf_unlink` /
  `leaf_link`), `thpos_rt` written, monster doors (`dreq`) and WR lifts.
- **P3.2c "decide"**: the melee and missile decisions and their states (A_FaceTarget; the attacks' EFFECTS are P5,
  so the mode runs the attack states without damage).
The frozen set v5 is the full model; B0 on it is exact from P3.2c on, when the mode's tic equals the model's for
everything v5 exercises but damage.
