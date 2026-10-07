# The final gameplay rung and the ship (P8a + P8): the plan (planner, 2026-10-07)

**Status: PLAN, before any code** (branch `m7-extras` = main 3fab6c1, P6 + P7 merged; blocked51 is the standing
binary). Written in the shape of `docs/gp-p67-interface.md`. The coordinator copies section 8 into
`docs/gp-ledger.md` as the rung's declaration BEFORE its build, and appends "As built" here after the ship.

**What the owner asked for (2026-10-07), all of it:**
- **(A)** the dying view SINKS -- DOOM's P_DeathThink view drop (viewheight to 6 units, 1 unit a tic), exact;
- **(B)** KNOCKBACK and INFIGHTING -- D5's two simplifications reversed;
- **(C)** the compositor rules D3 a and D3 b -- drops and effects ordered before monsters in a leaf; barrels (and
  projectiles) exempt from the soft budgets;
- **(D)** the open follow-up issues #119, #121 and #123, triaged;
- **(E)** P8, the SHIP, on the final binary: CAP-22 on the frozen set, stress, every gate, `SPEED_TARGET` -> 22M
  (D1), msframe's baseline re-frozen, docs.

**Summary.**
- **Rung structure: ONE feature build (P8a) carrying A + B + C + D's emitter-touching items, then P8 measured on the
  SAME binary (no build), one PR for both.** A v7 frozen set is planned ONCE, oracle-only, after all the behaviour
  work is in the model and before the build; the owner freezes it on the build's B0. Contingency: 1-2 rebuilds (P6 +
  P7 needed three builds). Section 2.
- **Seven packages**: 0 (the interface commit, first), then A (the view), K (knockback), I (infighting), C (the
  compositor), D (the follow-ups), V (v7 and the gates) in parallel; E (the ship docs) after the build. Section 3.
- **The view drop is cheap if it is defined right** (A, section 1.1): the walls and sprites already take a RUNTIME
  `viewz`; only the floor and ceiling band lists are baked per eye class. The recommended design S0 sinks the
  geometry exactly (one subtract at the eye's landing, dead frames only) and keeps the planes' band lists from the
  standing eye -- ~0 words and ~20 ops a frame alive, byte-exact by construction once the oracle splits its two
  `viewz` uses. S1 (exact planes at rest, +0.6 .. 0.9M words, zero alive ops by patching the band dispatch base)
  and S3 (exact planes at every step, runtime bands on dead frames) are the owner's upgrades (O-A1).
- **Knockback and infighting are mostly MODEL work** (section 1.2): the model has no momentum at all (the player
  steps 16 units a frame directly; monsters live on whole units), P_DamageMobj has no inflictor, every monster AI
  routine is player-relative, monster shots never trace things, fireballs hit only the player, and drops read the
  corpse's live position. All of it lands in the model first, behind new modes, then in fj.
- **The biggest risks** (section 7): infighting's target generalisation runs through the hottest monster fj; the
  far line of sight between two monsters (a new capability -- section 1.2.3 reuses the near-LOS cell lists in
  127-unit pieces, so it needs no new table); the corpse slide decoupling drops from corpses; the dead-eye render at
  eye heights the renderer has never drawn; v7's re-plan under knockback; placement.
- **Owner decisions** (section 9): O-A1 the plane rule (S0 recommended), O-A2 the sink's tempo, O-B1 barrels are not
  pushed, O-B2 the infighting sight rule, O-B3 the knock tempo with monsters at 2 tics a frame, O-B4 a refused knock
  stops (no P_SlideMove), O-V1 v7's criteria with infighting, O-E1 what "stress" must satisfy, O-E2 gamespeed's
  door-less tours.

Every claim about existing code cites `file:function`. Numbers marked MEASURED were measured in this session by
light model-only Python (no build, no fj run; the method is stated). Every other number is an ESTIMATE with its
basis, or copied from a ledger row and said so.

---

## 1. Scope, from the model: what exists, what is missing

### 1.1 (A) The dying view

**What exists.**
- The model: `combat.CombatMixin._death_think` -- the weapon's psprites (`_weapon_tics`), the turn to the killer
  (`_turn_to_attacker`, ANG5 a tic, P7), the damage flash fading only once facing him, use asks for the restart. Its
  docstring says "without the view drop" (`docs/gp-p67-interface.md` G1 / O1).
- The renderer: `wall_renderer._lines_descend_leaf` bakes, per leaf, `hex.set 8, viewz, <floor + 41>` and `hex.set
  w/4, vzcbase, <class base>` at the eye's landing (the descend pre-walk, `dsc_done`). `viewz` is a RUNTIME cell that
  every projection reads (`frame.ts_step_faces`, `sim.thing_load` -> `sp_z`, the wall spans); `vzcbase` selects the
  baked band lists: band id = (class * nkeys + key) * 2 + half (`wall_renderer._band_pair_lists`), each list built
  from `ph = |plane_h - vz|` of its class (`rm._zidx_band_walk`). 48 floor classes + 5 lift classes; 52,284 band ids
  of the 4-nibble index's 65,536 (`docs/gp-lift-spike.md` section 2).
- The oracle: `ReferenceModel.render_wall_frame` takes ONE `viewz` (`view_z(floor)`) for both the geometry
  (`wall_screen_span`, the step faces `_w4`, `project_thing`) and the planes (`_flat_row_colours(..., abs((h << 16)
  - viewz) ...)`).

**What is missing -- MODEL GAPS:**
- **G-A1: no view height in the model.** No schema field holds P_DeathThink's `viewheight`; `World` never lowers it.
- **G-A2: the oracle cannot render a sunk eye the way any cheap fj can.** Its one `viewz` feeds both the geometry
  and the band lists. Every cheap design keeps the planes on a BAKED class while the geometry sinks, so the oracle
  needs the split: `render_wall_frame(view_drop=d)` -> geometry from `view_z(floor) - (d << 16)`, band lists from
  the eye class (`view_z(floor)` for S0; the dead class for S1). Opt-in, default 0 = today's picture.

**DOOM's rule** (p_user.c P_DeathThink): after P_MovePsprites, `if (viewheight > 6*FRACUNIT) viewheight -= FRACUNIT;
if (viewheight < 6*FRACUNIT) viewheight = 6*FRACUNIT;` then P_CalcHeight (viewz = z + viewheight; no bob, D5), then
the attacker turn. 35 steps, 41 -> 6.

**The designs** (package D of P6 + P7 priced the first and the third rows in `gp-p67-interface.md` section 10; its
objections were size over a 0.3% bar it set itself and ops on EVERY frame -- the second objection is the one that
matters, and the base patch below removes it):

| design | the picture | size | ops | exact vs the oracle |
|---|---|---|---|---|
| DOOM's drop with exact planes at every step, baked | DOOM's | 35 classes x 48 floors: out | -- | -- |
| **S0 -- geometry sinks, planes stay on the standing eye's band lists** (RECOMMENDED) | walls, sprites, the horizon of every step and ledge sink exactly as DOOM's; the floor and ceiling DISTANCE SHADING stays as seen standing (the band lists are coloured by distance from floor + 41) | ~5-15K words (the cell, the death-think lines, the landing's subtract) | alive: one `hex.if0` after the landing, ~20 ops a frame; dead: + ~0.1-0.2K | by construction once G-A2's split exists; PROVEN by a tests/fj render harness at sunk eyes (section 5) |
| S1 -- S0, then the planes switch to a DEAD class (floor + 6, one per floor) at the drop's end | DOOM's exactly at rest; during the sink as S0 | a second band switch for 48 dead classes: 48 x 1,016 = 48,768 ids (fits 4 nibbles in its OWN table) x 8 words + its 65,536-entry pad + new unique bodies (est. +5-9K x 44): **~+0.6 .. 0.9M words** (ESTIMATE, gp-lift-spike's unit costs) | alive: 0 -- the dead table is chosen by XORing (dead base ^ live base) into `vpb_dsp`'s jump word ONCE at the death and once at the restart (the index already arrives by `hex.xor` into that word, `lut_generator.generate_bands_walk_fj`), so no `vpb_walk` call pays a wider index | as S0, plus the dead table's own render gate |
| S3 -- runtime band lists on dead frames (the M13 `plane.build_bands` + a data walk, selected by the same patch) | DOOM's at every step | small (~20-60K words: the revived builder, the data walk, a per-key FT1 strip table) | alive 0; a dead frame ~+2 .. 5M (ESTIMATE: the data walk's ~2.6K ops per emitted pair, `generate_bands_walk_fj`'s docstring, x ~1,300 pairs a frame; the builder ~0.2-0.4M) | needs the stale M13 builder brought up to FT1's ordinal strip and the colour merge: a renderer rung of its own |
| a screen-level shift of the 84-row view | not DOOM's (the horizon moves) | -- | a device change | out |

**Recommendation: S0.** It is the only design that costs nothing on a living frame and nothing in size, it reads
as DOOM's death (the world rises around a sinking eye; only the floor's distance shading lags), and S1 can be added
later on top of it without redoing anything (the split and the cell are S1's too). **OWNER DECISION O-A1.**

The model ("full" -> the new "final" mode, section 3.0) implements the same: `p_vdrop` 0..35 (0 at the level start
and at the restart), +1 per death-think tic after the psprites, capped at 35; the oracle renders with
`view_drop = p_vdrop`. The sink's tempo is one player tic a frame (D4; the death turn's tempo) -- 35 frames, ~2.5 s
at 71.6 ms/frame. Two units a frame (the weapon's `WEAPON_TICS`) would take ~1.25 s, closer to DOOM's 1 s:
**OWNER DECISION O-A2** (recommended: 1 a frame, the owner's own words "1 unit a tic").

What else reads the eye on a dead frame, checked: the aim window and the seen marks are recorded from the picture
(both mirrors use the geometry `viewz`; a dead player's aim is unused, and A_Look needs a live player); the sky
ignores the eye; the weapon is at the bottom; a corpse sliding to another floor (knockback, B) re-lands on that
floor's class and the drop rides on it -- in both mirrors.

### 1.2 (B) Knockback and infighting

What the model has today (D5, `combat.py`'s docstring, "THE APPROVED SIMPLIFICATIONS"): **"NO INFIGHTING. Monster
bullets and fireballs pass through monsters and barrels; only the player shoots monsters and barrels ... a monster's
target is always the player"** and **"NO KNOCKBACK. P_DamageMobj's thrust block is skipped -- with it its one
conditional `P_Random()&1`"**.

#### 1.2.1 MODEL GAPS (each must land in the model before any fj)

**Knockback:**
- **G-B1: there is no momentum anywhere.** `combat._player_move` steps the player by `FORWARD_MOVE` / `STRAFE_MOVE`
  directly (three candidates: full, x only, y only); monsters step whole units by `step_delta`. No `momx` / `momy`
  field exists for the player or any monster. `gamedata` has `MAXMOVE` but not `FRICTION` (0xE800) or `STOPSPEED`
  (0x1000).
- **G-B2: monster positions are whole map units** (`mon_x` / `mon_y`, 16 bits, "the integer half of thpos_rt's
  16.16"); a thrust is 16.16. A fraction must live somewhere.
- **G-B3: P_DamageMobj has no INFLICTOR.** `damage_monster(m, dmg, source, ev)` / `damage_player(dmg, source, ev)`
  take a source only (`("player", -1)`, `("mon", m)`, `("bar", b)`); DOOM's thrust angle is
  R_PointToAngle2(inflictor -> target): the shooter for hitscan and melee, the MISSILE for a fireball, the BARREL for
  a blast. `damage_barrel(b, dmg, ev)` takes neither.
- **G-B4: the falling-forward reversal needs z.** `damage < 40 && damage > health && target.z - inflictor.z > 64 &&
  (P_Random() & 1)` -> ang + ANG180, thrust x4. The model is 2D; a fireball has no z (`proj_*` has none).
- **G-B5: drops follow their corpse.** `combat._touch_specials` reads a drop at `mon_x[m], mon_y[m]` (the corpse's
  CURRENT position) and `monsters.MonsterPhase.mobiles()` draws it there. In DOOM the killing blow's thrust slides
  the corpse away from the item P_KillMobj dropped at the death position. (In the fj the drop rows nt + 10 + k are
  already copies, `barrelcode.drop_lines` -- the model is the one that must change.)
- **G-B6: no "moved by momentum" step in the tic**: DOOM's P_MobjThinker runs P_XYMovement before a thing's state
  tics; `World._monsters_phase` has no such step, and the player phase has no P_XYMovement after the walk.

**Infighting:**
- **G-I1: `mon_target` is ONE bit** ("has a target (always the player)", `world.build_schema`). It must name a
  thing: 0 none, 1 the player, 2 + slot a monster.
- **G-I2: every AI routine is player-relative**: `World._to_player`, `player_alive()` in `_a_chase` / `_a_look`,
  `_check_melee_range` (MELEE_REACH 60 is MELEERANGE - 20 + the PLAYER's radius 16; DOOM adds the target's radius),
  `_check_missile_range`, `_new_chase_dir`, `_a_face_target`, `combat._spawn_fireball` (aimed at `ws.px, ws.py`),
  `_mon_hitscan`.
- **G-I3: the attack sight sees only the player**: `sight.attack_sight` is "seen" (the player's picture) or the
  exact near LOS to the player. No monster-to-monster sight exists in fj.
- **G-I4: monster hitscan traces no thing**: `combat._mon_hitscan` tests `|spread| <= HWT[dist]` against the
  player's width only (`hurtcode.mbul` folds it).
- **G-I5: fireballs collide with the player only** (`combat._missile_try`): no monsters, no barrels, no same-species
  rule, no "passes its shooter".
- **G-I6: the target switch is player-only**: `damage_monster`'s `if not threshold and source[0] == "player"`.
- **G-I7: a barrel's blast always has the player as its source** (`_radius_attack` passes `("player", -1)` to
  monsters; `damage_player`'s comment: "no monster attack reaches a barrel"). DOOM: the blast's source is the
  barrel's `target`, set by the FIRST thing that damaged it (P_DamageMobj sets target and threshold 100 on a barrel,
  and nothing ever decrements a barrel's threshold) -- a monster's stray shot makes the monster the source.
- **G-I8: monster-on-monster hits spawn no blood** (convention "monster shots and hits on the player make none (not
  seen)" -- true of hits on the PLAYER; a hit on a monster is seen).

#### 1.2.2 The model rules to add (DOOM's, Chocolate Doom at `gamedata.SOURCE_COMMIT`; conventions marked)

**P_DamageMobj, in DOOM's order** (one shared `_damage_prologue(target, inflictor, source, dmg)` before the
existing per-kind bodies):
1. not shootable / health <= 0 -> nothing (as today);
2. **THE THRUST**, when an inflictor exists and not (source is the player and the ready weapon is the chainsaw):
   `ang = point_to_angle(inflictor -> target)` (the repo's `rm.point_to_angle`, its TRIG_N resolution);
   `thrust = dmg * (FRACUNIT >> 3) * 100 // mass` (mass: player 100, zombieman / sergeant / imp 100, demon /
   spectre 400 -- MEASURED from `gamedata.MOBJINFO`); the reversal of G-B4 when its four conditions hold (the coin
   drawn on the TARGET's stream: `rng_player` / `mon_rng[t]`, only when the first three hold -- C's short circuit);
   `momx += FixedMul(thrust, cos[ang])`, `momy += FixedMul(thrust, sin[ang])` with the RAW damage (before armor);
3. then the existing bodies (armor, health, kill / pain, `reactiontime`, the target switch).
- z for G-B4 (convention, the model is 2D): a thing's z is its floor -- the player's `check_position` floorz, a
  monster's `mon_floorz`, a barrel's sector floor (static); a fireball's z is its shooter's `mon_floorz + 32` at the
  spawn, kept in a new `proj_z` (DOOM's missile spawn height, no gravity).
- **Barrels are not pushed** (convention; 20 of 22 are BAKED things): their thrust is computed nowhere. **OWNER
  DECISION O-B1.**

**P_XYMovement** (one function `_xy_move(thing)`, DOOM's shape: the MAXMOVE clamp; the halving loop with DOOM's own
quirks -- halve only when `xmove > MAXMOVE/2 || ymove > MAXMOVE/2` (positive only), `ptry = x + xmove/2` with C's
truncating division and `xmove >>= 1` arithmetic; the friction `FixedMul(mom, FRICTION)` = floor(mom * 29 / 32);
the STOPSPEED stop):
- **Monsters and corpses**: in `_monsters_phase`, each slot's turn starts with `_xy_move` when its momentum is
  nonzero (P_MobjThinker's order: movement, then the state's tics). A refused step zeroes the momentum (DOOM's
  non-player rule). Convention (G-B2): **the collision test is the walk's, at the integer part** of the candidate
  (`try_move_monster` on floor(16.16)); a candidate whose integer part equals the current one is accepted untested
  (the integer position, which is all the walk's tests read, does not change). The fraction lives in new
  `mon_fx` / `mon_fy`; drawing, AI and collision use the integer part (as fireballs are drawn today). A CORPSE moves
  with DOOM's corpse flags: MF_DROPOFF (no 24-unit drop-off refusal), height >> 2, still blocked by solid things and
  blocking lines, and P_XYMovement's corpse rule (no friction while |mom| > 1/4 unit and its floorz differs from its
  leaf sector's floor). 2D convention: no airborne phase -- a pushed thing lands on the new floor at once, friction
  always (bar the corpse rule). The momentum move is NOT a heavy action (no K slot); its worst case is bounded at
  emit time by the slot count (53 x 2 tics).
- **The player**: a SEPARATE knock momentum `p_momx` / `p_momy` (the walk stays the direct step it is: frames with
  no knock are today's frames). After the walk (and on a dead tic too -- DOOM's corpse slides), `_xy_move(player)`
  moves by the knock momentum through the player's own `try_move` (16.16, the collision cells), halving as DOOM.
  Conventions: a refused step zeroes the knock momentum (no P_SlideMove: **OWNER DECISION O-B4**); the STOPSPEED
  stop ignores the walk keys (DOOM keeps a walking player's momentum below STOPSPEED decaying; here the walk has
  none); pickups are touched at every tried knock position (P_TryMove -> P_CheckPosition, as the walk does) while
  alive. The tempo: the player's knock moves once a frame (D4, the player's tic); the monsters' twice
  (`MONSTER_TICS_PER_FRAME`): **OWNER DECISION O-B3**.
- **Drops** get their own position (G-B5): `drop_x` / `drop_y` per dropper, written at the kill from the corpse's
  position at that instant (before its slide); `_touch_specials`, `MonsterPhase.mobiles()` and the drop's floor
  read them. The fj rows already hold exactly that (`drop_link<k>` copies the corpse's row at the kill).

**Infighting** (DOOM single player):
- **Targets**: `mon_target` = 0 / 1 player / 2 + slot. `_to_target(m)`, `target_alive(m)` (the player alive, or the
  monster active, shootable, health > 0) replace `_to_player` / `player_alive()` in A_Chase, the melee and missile
  ranges, P_NewChaseDir, A_FaceTarget and the attacks. A_Chase's "no target or a dead target -> P_LookForPlayers
  (allaround), else the spawn state" applies to a dead monster target too (DOOM's netgame-only re-look is out).
  P_LookForPlayers still looks only for the player. MELEE_REACH is MELEERANGE - 20 + the TARGET's radius (60 / 64 /
  74).
- **The switch** (`damage_monster`): `if not threshold and source exists and source != the target itself` ->
  target = source, threshold = BASETHRESHOLD, the spawn-state wake (as today's D-WAKE). Sources: the player; a
  monster (hitscan, melee, a fireball's shooter); a barrel's `bar_src`.
- **Barrels** (G-I7): `bar_src[b]` = 0 none / 1 player / 2 + slot, set by the first damage that lands on a live
  barrel; the blast passes it as the source of every damage it deals (`p_attacker` takes it too: a death by a
  monster-shot barrel turns the dead view to that monster).
- **The attack sight to a monster target**: the model's own `los_points` (the exact 2D trace with the frame's door
  heights) -- the "seen" picture is the player's, so it does not apply. **OWNER DECISION O-B2** (the fj's cost,
  section 1.2.3).
- **Monster hitscan** (G-I4), convention: the bullet's line is the shooter -> target bearing plus the spread (the
  outcome tables' `spread` as today). The nearest live shootable thing NEARER than the target (the player if alive,
  monsters, barrels; never the shooter) whose angular offset from that line is within its width
  (`|spread - delta_c| <= HWT_r[d_c >> HWT_SHIFT]`, `delta_c` = point_to_angle(shooter -> c) - point_to_angle(shooter
  -> target) in the spread's units; HWT tabled per radius 16 / 20 / 30 / 10 the way `combat.half_width_table` does
  the player's) takes the bullet; else the target by today's rule; else a miss. An intervening thing needs no sight
  test of its own (the shooter sees its target along nearly the same line). A hit on a monster spawns blood, on a
  barrel a puff (the fx pool, `rng_fx`), as the player's shots do (G-I8). **Recorded convention.**
- **Fireballs** (G-I5, DOOM's PIT_CheckThing for missiles, 2D): at each tried position, things in a fixed order --
  the living player, monsters by slot, barrels by index (convention; DOOM walks the blockmap); the shooter is passed
  through; another IMP explodes the fireball with no damage (same species); a corpse is passed; anything else
  shootable takes `((P_Random() % 8) + 1) * 3` on `rng_fx` (the existing `fireball_hit` site) with inflictor = the
  missile and source = its shooter, and the fireball explodes. Solid decor still passes (D5: under the fireball).
- **Melee** (the claw, the bite) hits the target only; a monster target is damaged with inflictor = source = the
  attacker.
- Nothing new makes noise (DOOM's monsters make none).

#### 1.2.3 The fj, in outline (the packages own the details)

- **Knockback** (`doomfj/knockcode.py`, NEW): ONE thrust leaf `kb_go` -- its arguments the target (player / slot
  id), the inflictor's integer position (and z when the reversal can apply), the damage, the mass class; the angle by
  the shared `proj.point_to_angle`; cos / sin from the projection's trig tables; `dmg * cos` by a `hex.mul_lo` or a
  shift-add (rule 3's one exception, ~1-2K ops a landed hit; the package's probe picks); `>> 3` (mass 100) or `>> 5`
  (mass 400). ONE player knock leaf (`collision.move_with_collision_lines` instantiated for the knock, pickups
  included) and ONE monster knock leaf (the walk's `move_leaf_lines` with a corpse variant), each with friction by
  shift-add (29/32) and the STOPSPEED test. A global `kb_live` (count of moving monsters, as `dr_live`) makes the
  monster tic's skip ~20 ops when nothing slides.
- **Infighting**: a target LOAD (`mt_tx`, `mt_ty` = the target's integer position: one nibble test for the player,
  else `dt_turn`'s two-level dispatch to the slot's thpos_rt row) feeding `monsterdecide`'s `mm_todist`,
  `mm_octant`, the decisions and `md_attack`, `projcode`'s spawn aim, the hitscan; the monster-source damage path
  into `dm_go` (a `dm_src`); the fireball's thing test (the player, a prefiltered monster scan, a STATIC per-missile-
  cell barrel list -- barrels never move); `bar_src`.
- **The far line of sight** (O-B2, the recommended design): a monster -> monster trace reuses P3.2c's near-LOS
  machinery unchanged. Cut the trace P -> Q into pieces of <= 127 units (Chebyshev) by power-of-two halving; every
  piece starts in some 256-unit sight cell whose list (`monstersight.cell_lists`, grown by NEAR_MARGIN 129) holds
  every segment a <= 128-unit trace from that cell can touch; test the WHOLE trace P -> Q (`sl_seg`) against the
  union of those lists, each cell's list once. A covering by construction, no new table. MEASURED (light probe:
  `MS.sight_segments(new_world())` binned by box): 593 sight segments (63 dynamic); ungrown 256-unit cells hold 795
  entries in 129 cells, mean 6.2, max 21 (and 128-unit cells 999 in 335, mean 3.0, max 13). ESTIMATE per trace: ~16
  pieces at 2048 units, a few distinct cells for a typical 300-600-unit fight, each list ~15-30 grown entries at
  ~0.3-1K ops per `sl_seg` box reject -> **~20-100K ops per check, ~5-10K words**. `monstersight._bounds` must be
  re-proven for |Q - P| up to 2048 units (u to 2^27 in 16.16; the products stay under 2^41 < 2^47 -- re-prove, do not
  take this line's arithmetic). The fallback, if the probe prices it over ~0.2M a check: within NEAR only (the
  existing `sl_los`) plus REJECT beyond -- not DOOM's (shots through walls), so the owner's.

### 1.3 (C) The compositor rules D3 a and D3 b

**What exists.**
- **D3 d** (P3.3): a leaf's RUNTIME things are drawn nearest first by `(P_AproxDistance key, index)`
  (`sim.thing_pass_depth`; the oracle's `rt_depth_order="aprox"` in `reference_model.render_wall_frame`'s thing
  loop), after the leaf's BAKED things ("BAKED FIRST, THEN THE RUNTIME LIST").
- **THE ACTORS RULE** (P6 + P7 package E, `GAME_RENDER_KW["exempt_actors"]`, `gp-p67-interface.md` 11.2): monsters
  (live or corpse) and MOBILES (fireballs, blood, puffs) are actors -- no soft raise (their soft count is the hard
  `MONSTER_BUDGET`), the monster base bound, no B-gate; a sprite with no row in the view records nothing. Drops are
  SCENERY (soft raise, `MIN_SPRITE_H`, B-gated; `monstercode.drop_view_rows`). Barrels are BAKED scenery (20) or
  runtime rows (2), scenery class.
- **So D3 b for PROJECTILES IS DONE -- and exceeded**: the actors rule exempts fireballs (and blood and puffs) from
  the soft raise AND the B-gate. **D3 c** (corpses count as scenery) is SUPERSEDED by the actors rule (the owner,
  2026-10-05: corpses are actors). Nothing to build for either.

**What is missing:**
- **D3 a is not implemented.** Effects and drops sort with the monsters by depth; a drop TIES with its corpse on the
  aprox key and the row order puts the corpse first (`gp-p67-interface.md` section 5), so the corpse takes slot A and
  the drop -- scenery, B-gated under 32 rows -- vanishes in those columns.
- **D3 b for barrels is not implemented**: after `DEG_SOFT_SCENERY` (3) accepted scenery things a barrel needs 24 rows.

**The rules to build:**
- **D3 a**: within a leaf's runtime list the key becomes `(rank, aprox, index)`, rank 0 for drops and effects
  (blood, puffs), rank 1 for monsters and fireballs. Strict, as D3 a reads (a drop farther than a monster in the
  SAME leaf is drawn in front of it -- a leaf is small; recorded). The baked list still comes first (a puff on a
  baked barrel stays behind the barrel: D3 a names monsters, not baked things -- **noted, not extended**). Oracle: the
  mobiles carry their kind (`MonsterPhase.mobiles()` -> the oracle), opt-in `rt_rank=True` in `GAME_RENDER_KW` only.
  fj: the rank as a high digit of `thing_pass_depth`'s key by runtime row range (fireballs nt .. nt+7 rank 1, fx
  nt+8, nt+9 and drops nt+10.. rank 0, monsters rank 1), or a per-row constant -- the package's probe picks.
- **D3 b for barrels**, as decided ("exempt from the soft budgets"): a barrel (every state, the explosion included)
  is accepted at its base bound whatever the scenery count, and does not count. NOT an actor: it keeps the scenery
  base bound and the B-gate. fj: a new `sp_ex` field set by the 7 barrel view blocks
  (`wall_renderer.barrel_state_fields`) and the 2 runtime barrels' row selects (`monstercode.barrel_select_lines`),
  read by `frame.thing_record_body`'s soft test (game-tier binding only, as the actors rule's `dsoftm==monbudget`
  lines; every other tier expands to nothing: deg_gate's op counts unchanged); `THING_XORBY_FIELDS` grows by it.
  (Making barrels actors instead would need no new field but changes more than D3 b: **owner's option**, not
  recommended.)

### 1.4 (D) The follow-up issues, triaged

Status: **DONE** (already, with the evidence), **DO** (in this rung: the package and the cheapest way), **N/A**
(nothing to do, with the reason), **RECORD** (a recorded deviation or exemption, no code), **E** (in P8's ship).

| item | status | the cheapest way / the evidence |
|---|---|---|
| #119-1 gates flood the noise through last tic's doors | **DONE** | in "full" every game-tier gate loads the frame's doors and lifts before the weapon: `m2_std_gate` / `m3_gate` / `p2a_gate` call `mph.sync(...)` then `mph.weapon(...)`; B0's `BinaryMirror.step(mph=)` runs the binary's order. The pre-"full" `else` branches keep the old order and no game-tier binary reaches them. V adds the order to `tests/host/test_gates_step_the_model.py` so it stays |
| #119-2 / #121-10 / #123-R1 PR bodies lacked R1 / R2 headings | **N/A** retroactively | E's PR body carries `## TDD evidence (R1)` FAIL/PASS blocks and `## Integration evidence (R2)` |
| #119-3 / #121-13 / #123-R4 DESIGN.md 1.2 span-ledger lines (aimr wpo dmrnd ammobcd hud; mbul trclaw sgbite dpsav palidx playpal0..12 fxrnd pjst mobview mc6; barnext bk10 bonpal amcap nkleaf pkxyz; the cells) | **DO** (D) | one table appended to DESIGN.md section 1.2, sizes from `scratchpad/12m/atlas/blocked51.labels.tsv.gz` by `scratchpad/gp/lift/label_sizes.py`; the P8a tables (kb, far LOS, hwt per radius, sp_ex) added from the P8a build's table |
| #119-4 `aimcode`'s unsigned `hex.cmp 8, pth_tz, ar_maxtz` on a signed value | **DO** (D) | a comment + an emit-time assert that project_thing's MINZ reject precedes it (no text change) |
| #119-5 / #121-14 / #123-R5b the LUTs value-checked on the host only | **DO** (D) | ONE harness `tests/fj/test_game_luts_fj.py` in `test_monster_tables_fj.py`'s shape (every entry looked up twice through its fj lookup, against its Python source, one mutated-entry R9 control per table) over aimr wpo dmrnd ammobcd mbul trclaw sgbite dpsav palidx fxrnd pjst mobview bk10 bonpal barnext amcap nkleaf pkxyz -- and P8a's new ones |
| #119-6 duplicated constants (the 17-column window and 72 in six places; `hud.VIEW_ROWS`; `hud.py`'s 160) | **DO** (D) | derive each from `combat.aim_window` / `config.GAME_CFG`; grep `src/`, `scratchpad/`, `tests/` (rule 5) |
| #119-7 `aimcode.leaf_lines` latent wrap | **DO** (D) | emit-time assert: every box is >= 1 column after clipping at MISSILERANGE on this screen |
| #119-8 stale comment in `b0_scenarios.drive` ("no fire, no number keys") | **DO** (D) | one comment |
| #119-9 profx attribution of the aim leaf (`bad/padding` 82K) | **DO** (D) | give the aim leaf its own phase label in `scratchpad/12m/profx/phases.py`'s map |
| #119-10 / #121-8 the msframe `shipped` baseline is still blocked44's | **E** | re-frozen on the final binary on a quiet box |
| #119-11 gp-ledger P3.1 "Row: (filled after the build)" | **DO** (D) | fill it from blocked40's evidence (`docs/ship-evidence/blocked40_*`) or mark it "never filled; see P3.2a's row" |
| #121-1 (F1) no small fj harness for mobile drawing | **partly DONE**, **DO** the rest (C) | `test_mobile_rowselect_fj` (rows), `test_actor_record_fj` (the record rule) and `test_thing_pass_depth_fj` (the depth order) exist; C extends `test_thing_pass_depth_fj` with mobile rows tying a monster in one leaf (it rewrites that key for D3 a anyway) |
| #121-2 (F3) the dead player walks / uses / holds doors | **DONE** | P7-c, `die_gate` D1-D3 (blocked51, 11/11 exact) |
| #121-3 (F4) the oracle's `_lst[_nb:]` assumes baked things first | **DO** (C) | an assert in the same loop C edits (true by construction today: baked drawables are appended first, mobiles last) |
| #121-4 (F5) `p31_parts` with player "walk" under "full" trips an assert | **DO** (D) | a clear assertion message naming the unsupported pair |
| #121-5 (F7) `_w5.reset(BOOT_SKILL)` mutates `p31_parts`' World after the parts were built | **DO** (D) | reset a copy |
| #121-6 / #123-L1 the fireball's per-tic cost and the chain's single frame UNVERIFIED (gates log totals) | **DO** (V) + **E** | V adds a per-frame op log (`--frame-ops`, B0's mechanism) to `hurt_gate`, `fight_gate`, `die_gate`; E judges S1 / S2 per frame |
| #121-7 the missile cells ~723K words | **RECORD** | not needed for size (section 6: ~37% of the 42% ceiling); the levers (share the relink leaves, fold into the player's cell tree) stay listed |
| #121-9 the gates' noise order applies to P5's gates | **DONE** | as #119-1 |
| #121-11 `hurtcode` re-declares STARTREDPALS, NUMREDPALS, DC_CAP | **DO** (D) | import them from `combat` |
| #121-12 `projcode`'s `pw_ang + 5*dw` hard-codes angle >> 20 | **DO** (D) | `assert rm.angle_shift == 20` in `projcode.check_model_rules` |
| #121-15 `p5_mobiles_identity.BASE_REF = "m7-p5"` | **DO** (D) | point it (and `p67_identity.BASE_REF = "m7-p67"`, also a merged branch) at a commit on main (3fab6c1), as P8a's own `p8_identity.py` does |
| #121-16 `monstermove`'s `hurt` branch (a dead player blocks nothing) has no fj test | **DO** (D) | one `p_dead = 1` record in the monster-move harness (`tests/fj/test_monster_chase_fj.py`), with its mutant |
| #121-17 `hurt_gate` H6 proves no blood is DRAWN | **DO** (V) | `blood_px` counter + a `blood_draw` control |
| #123-R5a `lootcode.nukage_lines` `hex.cmp` on signed floors | **DO** (D) | the use is an equality (sign-agnostic): a comment + an assert that only the `eq` arm is taken -- no text change |
| #123-4 `hp_bar` inside the `lvdone` guard (a stale bar on the exit frame) | **DO** (D) | an emit-time assert that E1M1's exit boxes touch no hurt sector and no health / armor item (MEASURED true in #123); no text change. Moving `hp_bar` out is for M4 |
| #123-5 `reference_model.move_with_collision` compares the masked candidate with the signed position | **RECORD** | it is the HOSTED tiers' policy, mirrored by their fj (no `skip_still`); changing it moves the hosted tiers at the player start (x -416) and needs a hosted rebuild that no ship gate runs. A host test pins that the two policies differ ONLY by the still-candidate rule (D) |
| #123-L2 B0 v6 frame max 24.1M and S1 ~23.2M, over 22M | **E** | O-E1 |
| #123-L3 gamespeed's tours reach no door | **E** | O-E2 |
| #123-L4 B0's strafe proxy refused on R2-spectre-corridor frame 0 | **RECORD** | 1 of 324 strafe-only frames; `b0_scenarios.py` prints it as a note (D, one line) |
| #123-L5 `p_tnh` not among the gates' compared cells | **DO** (V) | `gatestate.STATE_NAMES` and the probe |
| #123-L6 the death turn's alive-side size not measured | **E** | from the P8a build's label table (`label_sizes.py`), free |
| #123-L7 the counts cache misses at the head | **resolved by the build** | the P8a build recounts and its cache is the tracked one; no `src/` edit after the build, keep sources LF |
| #123-L8 blocked49 / blocked50 evidence not committed | **DONE** | e4e05e5 |
| #123-L9 O1, O2, G3, `state_dump.py`'s `new_world()` | O1 -> **A**; O2 -> **C**; G3 -> **K** (drops get positions; V's gates that compare `sshead` / `thnext` add the drop rows); `state_dump` -> **DO** (V: apply the set's sight rule and tempo, `use_sight_rule`) |
| #123-L10 P5's items re-checked | **this table** | |
| P6 + P7's criterion 4: the full `tests/fj` run at the head | **E** | run once, solo, at P8a's build commit |

After P8 the three issues are closed with this table; whatever is still open goes into one new follow-up issue.

### 1.5 (E) P8, the ship

The handoff's P8 entry and `docs/ship-gate.md` section 2a: CAP-22 on the frozen set (v7, section 2), the stress
cases judged (O-E1), every gate on the final binary, the class-F rule (msframe recorded, ~90 ms a tripwire),
`gamespeed.SPEED_TARGET` 20M -> 22M with CLAUDE.md and `docs/ship-gate.md` (D1), msframe's `shipped` baseline
re-frozen, B0 and gamespeed's trails re-recorded, the docs. Section 5.4 is its checklist.

---

## 2. The rung structure

The costs that decide it: a game build plus its gates is ~4-5 h; CI is ~5 h; a `src/doomfj` or `src/fj` edit
misses the counts cache (~34 min recount); a v7 re-plan is ~15-20 min of oracle time plus the owner's approval.

**What moves the frozen set v6:**
- (A) only on a death; v6 has none (0 deaths, the frozen totals), so A alone is SCHEMA GROWTH (`--grown-from`);
- (B) knockback moves every fight frame; infighting moves every frame a stray shot crosses a monster -> a behaviour
  change;
- (C) D3 a / b move v6's pictures and census F4's drawn populations -> a behaviour change;
- (D) nothing (harnesses, asserts, comments, docs).

So one re-plan is possible only if B and C share a build.

**RECOMMENDED: one feature build, then P8 on the same binary, one PR.**

| step | what | build? | time (ESTIMATE) |
|---|---|---|---|
| P8a-0 | the interface commit (package 0) | no | ~0.5 day |
| P8a-1 | packages A, K, I, C, D, V in parallel, each with host tests and fj harnesses whose mutants are caught BEFORE integration; integration on `m7-extras`; the oracle-only gates pass (`--oracle-only`, every control parting); v7 PLANNED oracle-only at the final model and shown to the owner (O-V1) | no (tests/fj only; heavy harnesses solo) | ~1.5-2 days of agent time |
| P8a-2 | **ONE game build** (blocked52, the 1b line with a fresh counting pass) + every gate + B0 on v7 + pinreport + profx | 1 | ~4-5 h |
| P8 | on blocked52: stress per frame, gamespeed at 22M, msframe (class F) then the baseline re-freeze, trails, size, docs; v7 frozen by the owner on blocked52's B0 | no | ~4-6 h |
| PR | P8a's ledger row + P8's verdict in one PR; crist one-pass review; CI | -- | ~5 h CI |

**Contingency**: 1-2 rebuilds (P6 + P7 needed three builds for one united rung). Every rebuild re-runs the gates
that can see the fix, and the per-rung process (owner, 2026-09-28) is kept: every gate, B0, gamespeed, msframe,
profx, PR, review, CI.

**The fallback (only if infighting lags behind):** ship MONSTER_MODE "push" (knockback without infighting) with A +
C + D, exactly as P6 + P7 kept "loot" in reserve. v7 is then planned under "push"; infighting becomes a later rung
with its own v8. The mode helpers (section 3.0) make the split one constant.

**The alternative the owner may prefer (risk isolation, +~10 h):** two builds -- P8a-1 = A + D (no v6 movement: a
schema growth; it proves the dead-eye render on a real binary early), then P8a-2 = K + I + C + v7 + P8. Not
recommended: A's render risk is pre-gated in tests/fj (section 5.1) without a build.

---

## 3. Work packages and file ownership

**Rule**: a package writes only the files and functions in its row; a hook another package needs is placed by
package 0 BEFORE the fan-out. Merge order at integration: 0, D, C, A, K, I, V.

### 3.0 Package 0 -- the interface commit (the coordinator, first)

- **Modes**: `world.PLAYER_MODES += ("final",)`, `MONSTER_MODES += ("push", "final")`; ONE-rule helpers beside
  `player_loots` / `player_mortal`: `player_sinks(mode)` (A), `knockback_on(player_mode, monster_mode)` (K),
  `infighting_on(monster_mode)` (I). "full" stays the v6 model, untouched (v6 must still replay under it: its B0
  file is the comparison record).
- **Schema** (`world.build_schema`, every field with phase "P8a", units in section 4.1): `p_vdrop`; `p_momx`,
  `p_momy`; `mon_momx`, `mon_momy`, `mon_fx`, `mon_fy`; `drop_x`, `drop_y`; `mon_target` widened; `bar_src`;
  `proj_z`. Declared, written by nobody yet. `gamedata.FRICTION`, `STOPSPEED`.
- **The damage signatures** (`combat.py`): `damage_monster(m, dmg, source, inflictor, ev)`,
  `damage_player(dmg, source, inflictor, ev)`, `damage_barrel(b, dmg, source, ev)`, every caller updated with the
  inflictor it has; an empty `_thrust(...)` hook (K fills it); `World.drop_pos(k)` (returns the corpse's position
  until K changes its body); `_xy_move` declared empty.
- **fj hooks** (each emitted only when its mode helper says so -- so "full" emits blocked51's text byte for byte,
  checked by `scratchpad/cr/emit_baseline.py --check`): the `kb_go` call sites with their inflictor registers set
  (`hurtcode.dp_lines`, `damagecode.leaf_lines`, `barrelcode.blast_lines`, `projcode.pj_lines`' impact) against a
  stub leaf `kb_go: stl.fret kb_ret`; the knock-move splice points (after `simmv_done` for the player, the top of
  `monstercode.mon_tic_lines`' slot body for the monsters); the landing's drop splice point after `dsc_done`;
  `build.KNOCK_PERSIST`, `FIGHT_PERSIST`, `VIEW_PERSIST` (empty) wired into `persist_labels` and
  `game_screen_persisted_decls`, with P6 + P7's `test_every_p6_module_persist_is_wired` extended.

**Package 0, as built** (the names the packages build on; `tests/host/test_p8a_interface.py` pins each):
- **Modes**: `world.P8A_PLAYER_MODES = ("final",)`, `P8A_MONSTER_MODES = ("push", "final")`. Each is a SUPERSET of
  "full": every pre-P8a rule names it beside "full" -- `player_resolves / hears / bleeds / loots / mortal`, the new
  `world.monster_attacks_land(mode)` (replaces the `== "full"` monster tests in `monsters.py` and the emitter),
  `hurtcode.HURT_PLAYER_MODES`, `lootcode.LOOT_PLAYER_MODES`, `restartcode.MORTAL_PLAYER_MODES`, every mode tuple of
  `monstercode` (`p31_parts`, `persisted_monster_decls`, `DEPTH_MODES`) and the emitter's `_SEEN`. A "final" run equals
  a "full" run on every pre-P8a cell, tic for tic, until a package lands. `World` refuses a P8a monster mode without
  the "final" player. Helpers: `player_sinks(pm)` = pm "final"; `knockback_on(pm, mm)` = mm in ("push", "final") and pm
  "final"; `infighting_on(mm)` = mm "final"; `p8a_schema(pm, mm)` -> `build_schema`'s keywords.
- **Schema**: `build_schema(lay, *, sinks, knock, fight)`; a World passes `p8a_schema(player, monsters)`, so a "full"
  World's schema (and v6's digests) is unchanged. `sinks`: `p_vdrop` (6 bits, label `p_vd`); `knock`: `p_momx`,
  `p_momy` (32 s, `p_kmx` / `p_kmy`), `mon_momx`, `mon_momy` (32 s x nmon, `mkx` / `mky`), `mon_fx`, `mon_fy` (16 u x
  nmon, `mfx` / `mfy`), `drop_x`, `drop_y` (16 s x nmon, INDEXED BY MONSTER SLOT like `mon_drop`, label `thpos_rt`),
  `proj_z` (16 s x FIREBALL_POOL, `pj_z`); `fight`: `mon_target` widened to `_index_bits(nmon + 2)` bits (0 / 1 the
  player / 2 + slot), `bar_src` (same width x nbarrel). All phase "P8a", all 0, written by nobody.
  `gamedata.FRICTION = 0xE800`, `STOPSPEED = 0x1000`.
- **Model**: `damage_monster(m, dmg, source, inflictor, ev)`, `damage_player(dmg, source, inflictor, ev)`,
  `damage_barrel(b, dmg, source, ev)`; inflictors are the source tuples plus `("proj", s)`; None = DOOM's NULL (sector
  damage, gate and test pokes). The model's sites: the player's shot ("player", -1); a monster's hitscan / melee
  ("mon", m); a fireball's impact ("proj", s); a blast ("bar", b) on the player and on monsters (its SOURCE stays
  ("player", -1) until I's `bar_src`). `CombatMixin._p_knock` = knockback_on; `_thrust(target, inflictor, source, dmg)`
  is called (when `_p_knock`) after the dead / not-shootable return and BEFORE the armor and the health -- empty;
  `_xy_move(thing, ev)` declared, called by nobody. `World.drop_pos(m)` (m = the monster SLOT) returns the corpse's
  position and is now the reader in `_touch_specials`, `MonsterPhase.mobiles` and `MonsterViews.rt_state` (K: its body
  and the drop row's LEAF, still `mon_leaf[m]` there). NOT routed (V / K): `scratchpad/gp/scenarios_v2.py`'s drop goal
  and `census_lib.py`'s drop rows still read `mon_x` / `mon_y`.
- **fj** (`doomfj.knockcode`, NEW -- package 0's interface, K's module): `kb_tg` (2: 0 the player, 1 + slot), `kb_dm`
  (2, the raw damage), `kb_on` (1: an inflictor is set; the damage leaf zeroes it on every exit), `kb_ix`, `kb_iy` (4,
  the inflictor's whole units), `kb_iz` (4, declared, K writes it), `kb_ret`; `stl.fcall kb_go, kb_ret` with the stub
  `kb_go: stl.fret kb_ret` (`knockcode.go_lines`); `inflictor_lines(x, y)` / `inflictor_const_lines`. Sites, each
  behind `knock=` (default off: P7's text): `hurtcode.dp_lines(knock)` (kb_tg 0, kb_dm = dp_dmg, kb_go after
  `dp_pos`'s checks, before the armor -- FJ-PROVEN in `tests/fj/test_player_damage_fj.py`'s knock test with a
  recording stub against the model's `_thrust`, three mutants caught); `damagecode.leaf_lines(knock)` (labels `dm_kbp`
  / `dm_kbgo`: the player's inflictor unless BLAST, then kb_go, before the health) and `go_lines(knock)` (each stub
  `dmg<m>` sets kb_tg = 1 + m); `barrelcode.blast_lines(knock)` (bl_px / bl_py before dp_go and each dmg<m>);
  `projcode.pj_lines(knock)` (pw_x / pw_y + 4*dw, unmoved, before the impact's dp_go); and -- NOT in the list above --
  `monsterdecide.attack_leaf_lines(full, knock)` / `decide_leaves(..., knock)` (mm_x / mm_y before each of md_attack's
  three dp_go calls: the monster's hitscan and melee on the player need an inflictor too). Plumbing: `p31_parts`
  computes `knock` (loot and knockback_on) and passes it to `damage_parts`, `barrel_parts`, `proj_parts` and the
  slots; `hurt_parts(knock)`; the emitter's `_SINK`, `_KNOCK`, `_FIGHT` (from the rules, after `_LOOT`'s last word),
  asserting `p31_parts`' knock agrees.
- **Splice points** (empty functions the packages fill): `knockcode.player_move_lines()` -> `_standalone_input_lines(
  knock_move=)`, right after `simmv_done` and before the bar's weapon slots (K); `knockcode.monster_slot_lines(m)` ->
  `monstercode.p32a_slot(knock=True)`, right after the slot's "not active" skip (K); `wall_renderer.
  landing_drop_lines()` right after `dsc_done:` behind `_SINK` (A; only the render reads viewz -- the monsters' world
  tic that follows does not).
- **Persist**: `build.VIEW_PERSIST = ()`, `KNOCK_PERSIST = knockcode.PERSIST (= ())`, `FIGHT_PERSIST = ()`;
  `build.p8a_persist(pm=None, mm=None)` adds each behind its rule at the game tier's modes, into `persist_labels` and
  `game_screen_persisted_decls` (whose candidates come from the hook `build.p8a_persisted_decls(map_wad, mapname)`,
  empty). `tests/host/test_restart_coverage.py::test_every_p8a_hook_is_wired` FAILS once a rule is on and its hook
  lacks a section-4.1 cell.

### 3.1 The packages

| pkg | writes (files / functions) | tests it ships (FAIL first, each fj harness with R9 mutants) |
|---|---|---|
| **A -- the view** | `combat._death_think` (the drop step only); `reference_model.render_wall_frame` (`view_drop=`: the geometry / band `viewz` split, around its `viewz =` line and the `_flat_row_colours` / `_render_plane*` calls); `wall_renderer` (the landing's drop lines at package 0's splice point); `hurtcode.turn_lines` (the drop inside `dt_turn`, the death think's leaf); `restartcode` (`p_vd` restart); `scratchpad/gp/p8_identity.py` (NEW: every existing picture byte-identical with `view_drop` 0 and every other new keyword absent) | host `test_view_drop_model.py` (35 steps, the cap, the restart, the order: psprites, drop, turn); `tests/fj/test_view_drop_fj.py` (the death think's drop and the landing's subtract vs the model; mutants `no_sink`, `sink_floor` (stops at 5 / 7), `sink_restart`); **`tests/fj/test_dead_eye_render_fj.py`** (section 5.1); `scratchpad/gp/dead_eye_census.py` (oracle: every leaf class x d in {1, 17, 34, 35} x 8 angles renders without an assert; ph never 0) |
| **K -- knockback** | `knockcode.py` (NEW: `kb_go`, the player and monster knock leaves, friction, `kb_live`); `combat._thrust`, `_xy_move`, `_player_knock_move`; `world._monster_knock_move` and its one call in `_monsters_phase`; `World.drop_pos` body + `_kill_monster`'s drop position; `monsters.MonsterViews.rt_state`'s drop rows; `monstermove` (the corpse try variant); the persist / restart lines of its cells | host `test_knockback_model.py` (DOOM's numbers: thrust per mass, the chainsaw's none, the reversal and its coin's stream, MAXMOVE's clamp and positive-only halving, `xmove/2` vs `>>= 1`, FRICTION, STOPSPEED, the corpse rule, the integer re-test convention, drops left behind); `tests/fj/test_knock_fj.py` (the thrust leaf vs `_thrust` over every angle octant x mass x damage edge; the moves vs `_xy_move`, a wall, a corpse over a ledge; mutants `no_thrust`, `thrust_sign`, `mass`, `saw_thrust`, `no_friction`, `stopspeed`, `no_clamp`, `no_halve`, `frac_drop`, `no_retest`, `reverse_rng`) |
| **I -- infighting** | `world` AI (`_to_target`, `target_alive`, `_a_chase`, `_check_melee_range`, `_check_missile_range`, `_new_chase_dir`, `_a_face_target`); `combat._mon_hitscan`, `_missile_try`, `_spawn_fireball`'s aim, `damage_monster`'s switch, `damage_barrel`'s `bar_src`, `_radius_attack`'s source; `sight.attack_sight` (a monster target); `monsterdecide` (the target load, the decisions, `md_attack`); `monstersight` (the far-LOS entry, `_bounds` re-proven); `hurtcode.tables_fj` (`mbul` per radius class); `projcode.pj_lines` (the thing test, the shooter, the species rule; package 0's `kb_go` call stays); `damagecode` (the monster-source path, `dm_src`); `barrelcode` (`bar_src`) | host `test_infighting_model.py` (the switch and threshold, a dead target -> the look, the species rule, the shooter passed, intervening things, `bar_src` the FIRST damager, the reach per target radius); `tests/fj/test_monster_target_fj.py`, `test_far_los_fj.py` (vs `los_points` on random pairs across the map, a mutated cell list caught), `test_monster_hitscan_fj.py`, extended `test_fireball_pool_fj.py` and `test_monster_damage_fj.py`; mutants `pass_through`, `no_switch`, `threshold_ignored`, `species`, `hits_shooter`, `bar_src_player`, `los_ignored`, `target_stale` |
| **C -- the compositor** | `reference_model.render_wall_frame`'s thing loop (`rt_rank`, the barrel soft exemption, the #121-3 assert); `src/fj/sim.fj` (`thing_pass_depth`'s key); `src/fj/frame_render.fj` (`thing_record_body`'s soft test, game binding only); `monstercode` (the rank of the view rows, `barrel_select_lines`' `sp_ex`); `wall_renderer.barrel_state_fields`, `THING_XORBY_FIELDS`, `GAME_RENDER_KW`; `monsters.MonsterPhase.mobiles()` (the kind) | host `test_d3_rules.py` (the oracle: a drop drawn before its corpse, blood before its monster, a far barrel after three scenery things drawn, deg_gate's keyword set unchanged); extended `tests/fj/test_thing_pass_depth_fj.py` (mutant `rank_off`, `rank_swap`; #121-1's mobile ties) and `test_actor_record_fj.py` (mutant `barrel_soft`) |
| **D -- the follow-ups** | section 1.4's DO rows marked D: `DESIGN.md`; `aimcode` (asserts), `lootcode.nukage_lines` (comment + assert), `hurtcode` (imports), `projcode.check_model_rules` (assert), `wall_renderer` (the hp_bar assert), `monstercode.p31_parts` (F5 message, F7 copy); `scratchpad/gp/p5_mobiles_identity.py`, `p67_identity.py`, `b0_scenarios.py` (comment, the proxy note), `scratchpad/12m/profx/phases.py`; `docs/gp-ledger.md` (P3.1) | `tests/fj/test_game_luts_fj.py` (NEW), the monster-move `p_dead` record, the move-policy pin test |
| **V -- v7 and the gates** | `scratchpad/gp/scenarios_v2.py` (the autopilot under knockback; the criteria of O-V1); `b0_scenarios.py` (`BinaryMirror` + injection of the player's knock momentum with the pose: P5's F2 pin grows); `monsters.MonsterPhase` (`state()` with the new cells, `move()` with the knock, `view_drop()`); `probe.game_cells`, `gatestate.STATE_NAMES` (+ `p_tnh`); `fight_gate.py`, `die_gate.py`, `hurt_gate.py` (the new scenarios of section 5, `--frame-ops`, `blood_px`); every game-tier gate's render call passes `view_drop` (a static host test, rule 5); `state_dump.py`; `gamespeed.GameSim` if it needs the new modes | `--selftest` of each gate (every new control parts on its scenario, else the gate FAILS as vacuous); `scenarios_v2.py --selftest`; v7 recorded (`--plan --file combat_scenarios_v7.json`) |
| **E -- the ship** (after the build) | `scratchpad/12m/gamespeed.py` (`SPEED_TARGET`), `scratchpad/12m/fencecheck.py` (it parses the "(target <= 20,000,000)" line); `docs/ship-gate.md`, `CLAUDE.md`, `docs/handoff-gameplay.md`, `docs/gp-ledger.md`, this file's "As built" | `gamespeed.py --selftest` |

**Known overlaps, resolved in advance:**
- `combat.py`: package 0 writes the damage signatures; K writes only new functions (`_thrust`, `_xy_move`,
  `_player_knock_move`), I writes the AI / hitscan / missile / switch bodies, A writes `_death_think`'s drop line.
- `hurtcode.py`: package 0 the `kb_go` hook in `dp_lines`; A `turn_lines`; I `tables_fj`; D the imports at the top.
- `reference_model.render_wall_frame`: A the `viewz` split (the eye block and the plane calls); C the thing loop.
  Different blocks of one function -- C merges after A.
- `monsters.py`: K `MonsterViews.rt_state`'s drop rows; C `MonsterPhase.mobiles()`; V the rest of `MonsterPhase`.
- `wall_renderer.py`: A the landing; C the barrel fields and `GAME_RENDER_KW`; D the hp_bar assert; package 0 the
  splices.

---

## 4. Cells, tables and the frame order

### 4.1 New and changed cells (persisted unless said; the probe's OPTIONAL_GROUPS, each whole or not at all)

| fj cell | nibbles x count | model field | units | owner |
|---|---|---|---|---|
| `p_vd` | 2 | p_vdrop | 0..35 (viewheight = 41 - it); 0 at the level start and the restart | A |
| `p_kmx`, `p_kmy` | 8 each | p_momx, p_momy | the player's KNOCK momentum, 16.16 per tic, signed (clamped to +-MAXMOVE when moved) | K |
| `mkx`, `mky` | 8 x 53 each | mon_momx, mon_momy | 16.16 per tic, signed | K |
| `mfx`, `mfy` | 4 x 53 each | mon_fx, mon_fy | the fraction of the 16.16 position (the row keeps the integer part; drawing, AI and collision read the integer) | K |
| `kb_live` | 2 | (derived) | the count of slots with nonzero momentum: the fast skip; scratch-checked against the model | K |
| `thpos_rt` rows nt+10+k | -- | drop_x, drop_y (NEW fields) | the drop's whole-unit position, written at the kill (unchanged in fj; the model catches up, G-B5) | K |
| `mon_tgt` (was the 1-nibble target flag) | 2 x 53 | mon_target | 0 none, 1 the player, 2 + slot | I |
| `bar_src` | 2 x 22 | bar_src | 0 none, 1 the player, 2 + slot: the first damager | I |
| `pj_z` | 4 x 8 | proj_z | the fireball's z (shooter floor + 32), for the reversal test | K |
| `dm_src`, `kb_*` scratch | -- | -- | arguments; not persisted, zero at every frame's end (asserted by their harnesses) | I, K |

Each new persisted cell gets: its level-start line in `restartcode` (per skill where it differs), its persist tuple
(package 0's), the restore-set re-key on the build, and `test_restart_fj`'s audit (it derives from `persist_labels`,
so a missed line FAILS there). Never the device shadows (`pal_cur`, `hud_s`).

### 4.2 New tables and shared leaves (every jump / dispatch macro declared SAFE in `build_blocked.py`'s `SAFE_TABLE_MACROS`, rule 5; no new macro carries an `@`-local data cell, rule 7)

| table / leaf | owner |
|---|---|
| `kb_go` (the thrust), `kb_pmove` (the player's knock), `kb_mmove` (a monster's / a corpse's knock), friction | K |
| the trig read for the thrust -- the projection's tables, or a `kbcs` D4 table if the probe says the shared read is too dear (~50K words) | K |
| the target load (`mt_tgt`: the player, or a two-level dispatch to the slot's row) | I |
| `mbul` per radius class (16 / 20 / 30 / 10), the hitscan's intervening scan | I |
| the far-LOS piece walk (`sl_far`, a new entry beside `sl_los` and `bl_los`) | I |
| the fireball's static barrel lists per missile cell | I |
| the depth key's rank | C |
| `sp_ex` in `THING_XORBY_FIELDS` | C |

### 4.3 The frame order (fj), new pieces in bold

1. The menu. NEW GAME: the restart block (**the new cells' level start**).
2. `do_world`: `if g_rs: restart(g_skill)`.
3. The frozen-level guard (`lvdone`).
4. The latch `p_dd0 = p_dead`; the door tic; the movers; the use lines (the P7 guards).
5. The player: dead -> the death think (psprites, **`p_vd` += 1 to 35**, `dt_turn`, use -> `g_rs`); alive ->
   nukage, the keys, the psprites (the player's shots: `dm_go` with **inflictor = the player**, `kb_go` on a hit
   unless the saw), the fades, the walk with pickups and blocking.
6. **The player's knock move** (after `simmv_done`, dead or alive -- the corpse slides): `if p_kmx|p_kmy` -> clamp,
   halving tries through the player's collision cells (pickups while alive), friction or the STOPSPEED stop.
7. The monsters' world x 2 (`wt_loop`): per slot, from the cursor: **`if kb_live and the slot's momentum` -> the
   knock move (integer re-test, the corpse variant, relink on a leaf change)**, then tics / the state / its action
   (A_Chase **toward the target**, the decisions with **the target's sight**, the attacks **at the target**: the
   hitscan **with intervening things**, melee **on the target**, the fireball **aimed at the target**); then
   `pj_phase` (**the thing test: the player, monsters, barrels; the shooter passed; the species rule**; the impact
   `kb_go` with **inflictor = the missile**), `bar_phase` (blasts with **source = `bar_src`**, `kb_go` with
   **inflictor = the barrel**), `fx_phase`.
8. `lvtime` +1; `hp_bar`; the palette.
9. The render: the landing -> **`viewz -= p_vd << 16`** (once, `if0` when alive); the leaves' things with **D3 a's
   rank** and **D3 b's barrel exemption**; the aim window; seen.
10. Present.

The model follows the same order (`World.tic`, `_player_phase`, `_monster_world`). Where they differ, the steps must
commute, and `test_p8a_model` holds it (as P6 + P7's `test_p67_model` did): the thrust lands during the monsters'
world and moves the player only in the next frame's step 6, in both mirrors.

---

## 5. Gates

All gates keep P6 + P7's shape: p2a_gate's `Mirror` in the "final" modes; frame-0 pokes of every cell a setup moved
(every poked cell persisted); STATE-, PIXEL- and PALETTE-exact on every frame; every event counter nonzero; each
R9 control an ORACLE MUTATION that must part on some frame of its scenario, or the gate FAILS as vacuous;
`--oracle-only` passing BEFORE the build.

### 5.1 The dead-eye render pre-gate (no game build)

`tests/fj/test_dead_eye_render_fj.py`, in `tests/fj/test_lines_render.py`'s `test_e1m1_lines_w1r_ft1_byte_exact_vs_
oracle` shape: the render tier of E1M1 with the game tier's drop line spliced in after its landing (the test
transplants the emitted text, as `test_actor_record_fj` does: no new tier row), `p_vd` poked, byte-exact vs the
oracle's `view_drop` at viewpoints chosen where the sink matters -- beside a 24-unit step, below a ledge, in a lift
leaf, under a low ceiling, the spawn -- at d in {1, 17, 35}. R9: the oracle with the bands from the SUNK eye (the
split removed) and with the geometry from the standing eye must each part. Heavy: run solo.

### 5.2 New scenarios

**`die_gate`** (A; deaths >= 1 each):

| id | scenario | claim | controls |
|---|---|---|---|
| D9 | die (poked health) and hold still 40 frames | `p_vd` 1..35 then 35, the picture exact at every step | `no_sink`, `sink_fast` (2 a frame), `sink_floor` (stops at 7), `band_eye` (planes from the sunk eye) |
| D10 | die beside a step / in lift 98's leaf / under a low ceiling | exact; the mover leaf's class dispatch then the drop | -- |
| D11 | die by a hitscan burst: the corpse slides while sinking, onto another floor | pose moves, class changes, exact | `dead_no_slide` |
| D4' | the restart after D9 | `p_vd` 0 at the level start | `sink_restart` |

**`fight_gate`** (K, I, C; deaths 0):

| id | scenario | claim | controls |
|---|---|---|---|
| K1 | a zombieman shoots the player in the open | the pose moves away from the shooter, decays, stops | `no_thrust`, `thrust_sign`, `no_friction`, `stopspeed` |
| K2 | pushed into a wall | the knock momentum zeroed | `wall_keeps` |
| K3 | a barrel blast near the player and a crowd | player and monsters thrown from the barrel | `blast_inflictor` (angle from the player) |
| K4 | the shotgun on a sergeant (7 thrusts) and on a demon (mass 400) | the fraction cells, the integer re-tests, a relink across a leaf | `mass`, `frac_drop`, `no_retest` |
| K5 | a kill by the shotgun: the corpse slides, its drop stays | the drop drawn and taken at the death position | `drop_follows` |
| K6 | the chainsaw on an imp | no thrust | `saw_thrust` |
| K7 | the reversal: (poked) a target on a ledge > 64 above its inflictor, damage < 40 > health | the coin drawn on the target's stream; reversed x4 when it lands | `no_reverse`, `reverse_rng` -- if no E1M1 position reaches it in a gate, `test_knock_fj` carries it on a forced state and the gate records N/A |
| I1 | a sergeant fires through an imp standing in the line | the imp hit, blood drawn, the imp targets the sergeant and fights it | `pass_through`, `no_switch`, `fx_none` |
| I2 | an imp's fireball through a zombieman and another imp | the zombieman damaged and switched; the other imp: explosion, no damage; the shooter passed | `species`, `hits_shooter` |
| I3 | a monster's stray shot kills a barrel | the blast's source is that monster: hurt monsters target it; the player's `p_atk` names it | `bar_src_player` |
| I4 | the target dies | the monster looks for the player (allaround) or returns to its spawn state | `target_stale` |
| I5 | a monster target behind a wall at range | no attack (the far LOS) | `los_ignored` |
| I6 | the threshold: a monster switched twice inside 100 tics | the second switch refused until its threshold runs out | `threshold_ignored` |
| C1 | a kill whose drop lies in the corpse's leaf | the drop drawn in front (D3 a) | `rank_off` |
| C2 | blood on a monster in one leaf | blood before the monster | `rank_swap` |
| C3 | a far barrel after three scenery things | drawn (D3 b) | `barrel_soft` |
| S2 | the chain in view (as P6) | **per-frame ops** (V's `--frame-ops`) | -- |
| S3 | **a brawl**: the hard courtyard's imps firing into a zombie crowd, infighting saturated | per-frame ops, exact | -- |
| S4 | **a push storm**: a barrel chain inside a crowd -- every knock move at once | per-frame ops, exact; the emit-time bound held | -- |

**`hurt_gate`**: H1-H6 and S1 re-run under "final" (knockback moves their poses: the scenarios re-place on the
oracle); H6 gains `blood_px` and `blood_draw` (#121-17); S1 per frame.

**Every earlier gate**: m2_std_gate, m3_gate, p2a_gate, the gate selftests, deg_gate BYTE-EXACT with op counts EQUAL
to blocked51's (the visual tier takes none of this: every new line is behind a game-tier mode helper or a game
binding), B0 on v7. The label-coverage report must show run, in some gate: the sink to 35, a knock refused by a wall,
a corpse slide, a monster switched to a monster, a far-LOS refusal, a fireball on an imp, a barrel with a monster
source, the restart clearing every new cell, NEW GAME after a death mid-sink.

### 5.3 v7

- `scenarios_v2.py --plan --file scratchpad/gp/scenarios/combat_scenarios_v7.json` from v6's 11 checkpoints at the
  final model (sight "seen", tempo 2, "final" / "final"); the autopilot must survive knockback (pushes off its path,
  into nukage, off ledges -- its replanning already handles a stuck move).
- The criteria table recorded, `--check` OK; B0's camera reconstruction 0 frames apart (B0 now injects the knock
  momentum with the pose).
- Status PLANNED until the owner freezes it on blocked52's B0 (`--freeze --file ... --approver "the owner"`, the
  owner's words in the record).
- v6 stays: its file and B0 log are the record; nobody re-grades it.

### 5.4 P8 -- the ship checklist (on blocked52, in this order; a failure stops it)

1. **Exactness**: m2_std_gate, m3_gate, p2a_gate, hurt_gate, fight_gate, die_gate, every selftest rejected where it
   must; deg_gate byte-exact with blocked51's op counts; B0 on v7 (`--pixel-every 1 --proxy`), every frame of every
   run state- and pixel-exact; pinreport exit 0 (20 of 20); host suite green; **the full `tests/fj` at the build's
   commit, solo** (owed since P6 + P7).
2. **CAP-22**: v7's (mean + p80) / 2 <= 22,000,000. The owner freezes v7 on this B0.
3. **Stress** (O-E1): S1, S2, S3, S4, and D9's dying frames, per frame (max, p95, mean, the frames over 22M), with
   B0 v7's per-frame maximum; every frame exact.
4. **Size** <= 42% (gamespeed's size line).
5. **gamespeed**: `SPEED_TARGET` 20,000,000 -> 22,000,000 (D1), with `fencecheck.py`'s parser, `docs/ship-gate.md`
   (section 1's table, section 2 step 3) and CLAUDE.md in the same commit; `gamespeed_trail.py` on blocked52 (TRAIL,
   CONTROL-POSE PASS; CONTROL-DOORS N/A while no tour opens a door, O-E2) and `BINARY_ENDS` / `BINARY_DOORS`
   re-recorded; `--validate`; `--selftest`; the binding number quoted only after TRAIL PASS.
6. **msframe** (class F, D8): `--a build/doom_e1m1_blocked51.fjm --b build/doom_e1m1_blocked52.fjm` recorded as
   the price; ~90 ms/frame is the tripwire. Then, on a quiet box (yardstick >= ~3.5 G), `--a
   build/doom_e1m1_blocked52.fjm --save-baseline shipped`: the baseline leaves blocked44 at last.
7. **Record**: `docs/ship-gate.md` section 1 (the standing number with its provenance) and 1b (the build command,
   the counts cache, the label table, the hashes, the play command); CLAUDE.md (the milestone done, the 22M cap in
   force, the standing binary); `docs/handoff-gameplay.md` (P8 DONE); `docs/gp-ledger.md` (P8a's row, its verdicts,
   "M7 summed", P8's verdict); this file's "As built"; #119 / #121 / #123 closed with section 1.4's table, one new
   issue for what stays open.
8. **PR**: R1 FAIL/PASS blocks, R2 integration evidence, the crist one-pass review (BLOCKING / FOLLOW-UP), CI green,
   merge.

---

## 6. Budget and size (ESTIMATES; their basis)

**Where it starts (blocked51, from `docs/ship-gate.md` section 1 and the ledger's P6 + P7 row, not re-measured
here):** v6 binding 14,699,526 (7,300,474 under CAP-22); per-frame maximum 24,117,248 (R0-courtyard); hurt_gate S1
~23.2M/frame averaged (696,858,304 over 30 frames); fight_gate S2 ~9.7M/frame averaged (1,026,624,325 over 106);
size 36.24% (48,643,954 words; 42% = 56,371,445, so 7,727,491 words of headroom); msframe 71.6 ms/frame; ~4.1 ms a
million ops on a quiet box (`fj-speed` memory, 2026-09-13).

**Unit costs used** (handoff section 5 and the P5 / P6 + P7 harness measurements): a jump on an index 68-102; a D4
lookup 47-100; `hex.mul_lo 8` ~825; point location 5.9K from a cell start; one player try ~10K (P1.2 derived; it
measured -1.58M against 613K tries); the death turn's leaf ~14.5K a dead tic (MEASURED in its harness); the monster
heavy window copy 403 each way.

**Ops on the frozen set ((mean + p80) / 2), per package, before placement:**

| package | basis | delta |
|---|---|---|
| A (S0) | one `hex.if0` a frame alive; nothing else on a living frame (v7 has no deaths) | **~0** |
| K | per landed hit: thrust ~5-10K (point_to_angle + trig + two multiplies); a pushed monster's slide ~35 tics of friction (~2-4K a tic) + ~10-20 integer re-tests at ~10-20K; the player's ~1 try a frame while sliding. ~60 player hits on monsters, ~40 hits on the player, ~16 blasts in a v6-like set of 1,100 frames | **+0.03 .. +0.15M** |
| I | the target fast path (a nibble test, ~3.7 heavy acts a frame at tempo 2); the hitscan's intervening prefilter ~5-15K a hitscan attack; the fireball's thing test ~6K a fireball tic; far-LOS checks only while a monster targets a monster (rare: ~20-100K each) | **+0.01 .. +0.08M** |
| C | the rank in the key ~50 ops per runtime thing in a leaf; `sp_ex` ~40 ops per recorded scenery thing; newly drawn barrels and drops ~15-50K each when they appear | **+0.01 .. +0.03M** |
| D | asserts, comments, harnesses | **~0** |
| placement | the pins re-roll on any change (P6 + P7: 19 of 20 bases moved) | **+/- 0.1 .. 0.3M** |
| **total** | | **+0.05 .. +0.26M before placement** |

**Declared: v7 binding ~14.7 .. 15.3M** -- with the P6 + P7 lesson attached: v7 is a RE-PLANNED set, so the
estimate's basis (v6 plus the rung's deltas) may not hold; the verdict is CAP-22 alone, with >= 6.5M of headroom
either way.

**Single frames and stress (recorded, not capped, D1):** S1 + the fireball's thing test x 2 tics x 8 fireballs:
**~+0.1 .. +0.2M/frame -> ~23.3 .. 23.5M averaged**; S4 (a push storm) up to ~53 knock moves x 2 tics x ~20K =
**~+2M on its worst frame** (ESTIMATE); S3 (the brawl) far-LOS checks up to K = 6 x 2 a frame x ~20-100K = **up
to ~+1.2M on its worst frame**; B0's per-frame maximum may rise by a few hundred K.

**Size** (words of code and tables, each package's estimate):
- A ~5-15K (S0; S1 would add ~0.6-0.9M);
- K ~100-300K (the thrust leaf, the two knock leaves with a collision instantiation and the corpse variant, the
  restart lines, the cells);
- I ~100-200K (the target load ~10K, the far-LOS walk ~5-10K, `mbul` x 3 ~20-60K, the hitscan scan ~20-40K, the
  fireball's thing test ~20-40K, `dm_src` and `bar_src` ~10K);
- C ~10-20K (two `thing_record_body` instantiations, the key, the flags);
- **~0.25 .. 0.55M words**, x P6 + P7's measured-over-estimate growth (1.457M measured against 0.8-1.2M declared:
  x1.2 .. 1.8) -> **+0.3 .. +1.0M words, 36.5 .. 37.0% of 2^27** (<= 42%). Redesign trigger: **> +2.0M**.

**Kill criteria**: section 8.

---

## 7. Risks

1. **Infighting runs through the hottest monster fj.** `mm_todist`, `mm_octant`, the decisions and `md_attack` all
   read the player's position today; every heavy act will load a target. Keep the player-target path ONE nibble test
   and the window copy unchanged for it; price it in `test_monster_target_fj` before integration. P3.2b's first build
   overflowed the table pool with unrolled per-slot code: no per-slot code (`damagecode`'s rule).
2. **The far LOS** is new. Its covering proof is the host test against `los_points` on random pairs with a
   mutated-list control; its cost the probe's (O-B2's fallback ready). `_bounds` must be re-proven for 2048-unit
   traces, or the 48-bit products may overflow silently (P6 + P7 risk 10, again).
3. **Fractional monsters.** G-B2's convention (the integer part drives everything) must hold in every reader of
   `mon_x` -- the model, the oracle's rows, the gates' mirrors, the probe. A missed reader shows as a 1-unit
   parting. Rule 5: grep `mon_x` / `thpos_rt` in `src/`, `scratchpad/`, `tests/`.
4. **Drops leave their corpse** (G-B5): the model, `MonsterViews`, the pickup's floor read and the gates must all
   take the drop's own position; P6's `dr_live` double-decrement (bb2c516) is the warning that drops are easy to
   get wrong.
5. **The dead-eye render** at eye heights the renderer never drew (6..40 above a floor: floors above the eye from
   the ground, step faces seen from below their top). The oracle is the spec; 5.1's harness proves the fj; the
   census proves the oracle never asserts. If a structural assumption breaks (a baked cull that assumes eye >= floor
   + 41), S0 needs that cull made eye-independent -- found before the build, not by it.
6. **v7 under knockback.** The autopilot is pushed off its plan, into nukage, off ledges; a mirror death fails a B0
   run (e8d3683). The criteria (O-V1) may need the owner, as v6's did.
7. **The RNG order.** The reversal coin draws only when its three conditions hold, BEFORE the armor and the pain or
   death draw; monster-on-monster blood draws `rng_fx`. A mis-ordered draw parts every later frame of the stream:
   the knock and fireball harnesses run long trajectories (P5's 600-tic style), not single hits.
8. **Gate fan-out** (rule 5): every gate's render call needs `view_drop`; every mirror needs the knock and the
   targets; B0 must inject the knock momentum with the pose. The static host tests are the net.
9. **The restore set**: ~12 new persisted cells; a missed one hangs or parts the game after the M1 reset. The
   restart audit derives from `persist_labels`; the re-key runs on the build.
10. **Placement**: +/- 0.1-0.3M, and the pinreport's 20 of 20 can fail on a moved hot site (P3.3's r0). Read the
    pin report before judging.
11. **The counts-cache recount** (~34 min) on the build: every package edits `src/`; keep sources LF.
12. **Uniting widens a failure's blast radius** (P6 + P7: three builds). Mitigation: every package's fj harness and
    mutants green, the oracle-only gates parting their controls, emit_baseline unchanged under "full", BEFORE the
    build.

---

## 8. The ledger declaration (draft, for `docs/gp-ledger.md`, BEFORE the build)

**P8a the final gameplay: the dying view, knockback, infighting, D3 a / b, the follow-ups (class F) -- declared
<date>, before the build.**

**What**: `docs/gp-final-plan.md` -- ONE rung, `PLAYER_MODE = "final"`, `MONSTER_MODE = "final"`:
- (A) the dying view sinks (S0, or the owner's O-A1 choice): `p_vd`, the oracle's `view_drop` split;
- (B) knockback (P_DamageMobj's thrust with its inflictor, P_XYMovement for the player's knock and every monster and
  corpse, the drops' own positions) and infighting (targets, the switch and threshold, the far LOS, intervening
  things on monster bullets, fireballs on monsters and barrels, `bar_src`);
- (C) D3 a (drops and effects before monsters in a leaf) and D3 b for barrels;
- (D) the follow-ups of section 1.4 marked DO;
- in the frame order of section 4.3 and the cells of section 4.1.

**Budget** (section 6, ESTIMATES): the v7 binding ~14.7 .. 15.3M (re-planned set, not comparable with v6's
14,699,526); the packages' own code +0.05 .. +0.26M before placement, placement +/- 0.1 .. 0.3M; size +0.3 .. +1.0M
words (36.5 .. 37.0%), redesign above +2.0M; single frames and stress recorded (S1 ~23.3 .. 23.5M averaged; S3 / S4
worst frames up to ~+1.2 / +2M).

**Kill criteria** (any one -> the binary does not ship; class F):
1. **CAP-22**: v7's (mean + p80) / 2 <= 22,000,000, every frame of all 11 runs state- and pixel-exact; v7 frozen by
   the owner on this build's B0.
2. **Size** <= 42% of 2^27 (56,371,445 words).
3. **Every gate exact**: m2_std_gate, m3_gate, p2a_gate, hurt_gate (H1-H6, S1), fight_gate (F1-F10, K1-K7, I1-I6,
   C1-C3, S2-S4), die_gate (D1-D11), B0 on v7; their selftests rejected where they must; every control parting;
   every event counter nonzero; deaths 0 where declared; deg_gate BYTE-EXACT with op counts EQUAL to blocked51's.
4. **Host and fj**: `python -m pytest tests/host` green (the restore-set tests after the re-key); the P8a harnesses
   (`test_view_drop_fj`, `test_dead_eye_render_fj`, `test_knock_fj`, `test_monster_target_fj`, `test_far_los_fj`,
   `test_monster_hitscan_fj`, `test_game_luts_fj`, the extended `test_fireball_pool_fj`, `test_monster_damage_fj`,
   `test_thing_pass_depth_fj`, `test_actor_record_fj`, `test_restart_fj`) -- every mutant caught; and ONE full
   `tests/fj` run at the build's commit, solo.
5. **Attribution**: profx-attributed ops of the new code (knock, targets, far LOS, hitscan scan, fireball thing test,
   the view, the rank, `sp_ex`) on v7 <= 0.33M (1.25 x the top of the +0.26M estimate), else REDESIGN.
6. **Housekeeping**: pinreport 20 of 20 (the heat list re-keyed for any macro whose arity moved); the restore sets
   re-keyed; gamespeed's trails re-recorded (TRAIL PASS before the number is quoted); `emit_baseline.py --check`
   unchanged for "full" (package 0's hooks inert); msframe recorded (class F; ~90 ms a tripwire to explain).

The phase budget: P8a has none in the handoff (it is the owner's 2026-10-07 request); the cap that binds is CAP-22.

**P8 ship (on the same binary)**: section 5.4, its verdicts recorded beside P8a's row.

---

## 9. Owner decisions

Under the owner's standing "be autonomous: take the recommended option, record it, report it" (2026-09-30), the
coordinator may take each RECOMMENDED option and report it; the ones marked **OWNER** change a goal-level rule or a
frozen-set criterion and need the owner's words.

| id | question | options | recommended |
|---|---|---|---|
| **O-A1** | the dying view's floors and ceilings | S0 (shading as standing; ~0 size, ~0 ops) / S1 (+ exact planes at rest; +0.6-0.9M words, 0 alive ops) / S3 (exact at every step; ~+2-5M ops a dead frame, a renderer rung) | **S0**; S1 as a later add-on if the owner sees the floor shading |
| O-A2 | the sink's tempo | 1 unit a frame (35 frames, ~2.5 s; D4, as the death turn) / 2 a frame (~1.25 s, as `WEAPON_TICS`) | 1 a frame (the owner's "1 unit a tic") |
| O-B1 | are barrels pushed? | no (20 of 22 are baked; moving them makes them runtime things) / yes | **no** -- a recorded D5 remnant |
| **O-B2** | infighting's sight | exact 2D LOS at any range (the piece walk over the near lists: ~20-100K a check, ~5-10K words) / NEAR only + REJECT beyond (shots through walls) | **exact**, if the probe holds ~0.2M a check |
| **O-B3** | knockback's tempo with monsters at 2 tics a frame | monsters slide in their own world (2 tics a frame), the player's knock once a frame (his tic) / the player's knock twice a frame | **monsters 2, player 1**: each thing on its own clock; the slide's DISTANCE is DOOM's either way |
| O-B4 | a refused knock step | zero the knock momentum (DOOM's non-player rule) / P_SlideMove (DOOM's player rule: a wall-slide model the 3-candidate walk does not have) | **zero** |
| O-B5 | monster bullets and things in the line | the nearest thing nearer than the target within its width, no sight test of its own; blood / puffs drawn / DOOM's full trace | **the first** (recorded convention) |
| **O-V1** | v7's criteria with infighting and knockback | keep v6's criteria; a monster killed BY A MONSTER counts in ">= 8 kills"; add ">= 1 infighting switch in the set" and ">= 1 knock refused by a wall" so the set exercises them; "every run survives" stays | **as stated** -- a criteria change is the owner's |
| **O-E1** | what "stress" must satisfy | D1 as written (recorded, not capped) / a tripwire / a cap per scenario | **recorded + exact + a TRIPWIRE**: any stress frame over 44M (2 x the cap, ~180 ms) or any scenario averaging over 30M must be attributed by profx and explained in the ledger before the ship; S1 at ~23.2-23.5M averaged and B0's ~24M frames ship as recorded |
| **O-E2** | gamespeed's tours reach no door since P6 | keep (the 22M target, with the note) / re-plan the routes (a gen 4: a metric change) | **keep** |
| O-C1 | D3 a's strength | a strict rank within a leaf (as D3 a reads) / a tie-break only | **strict rank** |
| O-C2 | D3 b for barrels | exempt from the soft raise only (as D3 b reads) / make barrels actors (no B-gate either) | **soft raise only** |

---

## As built

(To be appended after the ship: the builds, where they differed from this plan, the numbers.)

**TAKEN (coordinator, 2026-10-07, under the owner's standing "be autonomous: take the recommended option, record it,
report it"; the owner asked for A-D + P8 on 2026-10-07):** O-A1 S0 (the geometry sinks exactly; floors and ceilings
shaded as standing -- the model and the oracle do the same); O-B1 barrels not pushed; O-B2 exact 2D LOS at any range;
O-B3 monsters slide at their 2 tics a frame, the player at 1; O-V1 v6's criteria kept, monster kills count, plus >= 1
infighting episode and >= 1 knockback stopped by a wall; O-E1 stress recorded and exact, with a tripwire (any frame
> 44M or any scenario averaging > 30M must be explained before ship); O-E2 keep gamespeed's tours. The rung is ONE
feature build (P8a) with P8 measured on its binary, the infighting fallback mode kept in reserve.
