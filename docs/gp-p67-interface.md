# P6 + P7 -- pickups, barrels, death and restart: the shared interface (planner, 2026-10-05)

**Status: PLAN, before any P6/P7 code** (branch `m7-p67`, off the P5 branch at fe754a0; blocked48 is the standing
binary). Written in the shape of `docs/gp-p5-interface.md`. The coordinator copies section 9 into
`docs/gp-ledger.md` as the rung's declaration BEFORE its build, and appends "As built" here after the ship.

**Summary.**
- **Recommendation: ONE united build.** The target is `PLAYER_MODE = "full"` (`MONSTER_MODE` stays "full"). It is
  split into four parallel packages:
  - **A**: the model, the oracle and the gates (Python).
  - **B**: the player's side in fj: pickups, blocking, nukage, berserk and bonus, and the dead player's guards.
  - **C**: the world's side in fj: barrels, drops, puffs, gibs, and the new things drawn.
  - **D**: the restart and persistence (P7).

  A fallback mode `"loot"` (section 2) exists in case D lags behind.
- **Owner decisions needed (section 10):**
  - O1: the death VIEW DROP is out. The model omits it, and the renderer bakes the eye height per leaf class, so a
    view drop would need a new renderer feature.
  - O2: drops and barrels do not take D3 a/b. They follow P5's precedent and are recorded as such.
  - O3: gamespeed's runs 0 and 2 now stop at a zombie, so its trails must be re-recorded and its number is not
    like-for-like.
- **The biggest risks (section 8):**
  - the restart must restore every persisted cell from P1 to P6, and must leave the device shadows alone;
  - the "dead at the start of the tic" latch;
  - gamespeed's change of route;
  - the cost of a barrel chain in a stress frame;
  - the aim window must record BAKED barrels, which no baked thing does today.

Every claim about existing code cites `file:function`. Numbers marked MEASURED were measured in this session by light
model-only Python (no build, no fj run). Every other number is an ESTIMATE, with its method stated.

---

## 1. Scope, from the model: "fx" -> "full"

The game tier is today at `wall_renderer.PLAYER_MODE = "fx"` and `MONSTER_MODE = "full"`.

The model has two kinds of gating:
- Its explicit mode gates are `combat.CombatMixin._combat_init`'s `_p_resolve`, `_p_noise`, `_p_fx` and `_p_full`
  (`world.player_resolves` / `player_hears` / `player_bleeds`).
- Its pickups and its blocking are NOT mode-gated in the code. `World._player_move` touches specials and refuses
  solid things in EVERY mode. They are left out of "fx" only because the gates never call the model's player phase:
  `monsters.MonsterPhase` runs `_monsters_phase`, the pools and `weapon`, and the gates move the player with
  `ReferenceModel.step_sim` (`p2a_gate.Mirror.run`, `m2_std_gate`, `m3_gate`, `b0_scenarios`/`scenarios_v2.BinaryMirror`).

**This is the first thing to know about P6:** the gate oracles must start running the model's own player move.

### 1.1 What P6 builds in fj (each line: the behaviour, then the model function that defines it)

| # | behaviour | model |
|---|---|---|
| P6-a | **Pickups** at EVERY tried candidate of the move (up to 3: full step, x only, y only), before the solid-thing and line tests. A refused move can still pick up. Map things are touched in pickup index order, then drops in monster-slot order. Each is a box overlap (item radius 20 + 16, strict, 16.16), then the reach test `item_z - here_z` in [-8, 56] (`here_z` = the floor at the TIC-START position). | `combat._player_move`, `_touch_specials`, `_touch` |
| P6-b | **Every give routine, with DOOM's caps**: ARM1 / ARM2 (refused at >= 100 / 200); BON1 +1 health, cap 200; BON2 +1 armor, cap 200, type green if none; STIM / MEDI (+10 / +25, refused at >= 100, cap 100); BKEY (`pcard`; bonus SET to 6, then the common +6 = 12); PSTR berserk (P_GiveBody 100, strength = 1, the fist pending if it is not ready); CLIP (10; a dropped one 5); AMMO 50; SHEL 4; SBOX 20; ROCK 1; CELL 20; BPAK (doubles the caps, then one clip of each ammo in AM_* order); CSAW; SHOT (2 clips found, 1 dropped; a new weapon becomes pending). P_GiveAmmo auto-switches from an empty ammo. A taken item: `bonuscount = min(bc + 6, 255)` and the item vanishes. | `_touch`, `_give_ammo`, `_give_weapon`, `_give_body`, `_give_armor`, `max_ammo` |
| P6-c | **The bonus palette**: palettes 9..12 when the damage count is 0, `min(3, (bc + 7) >> 3) + 9`. bc fades by 1 a tic in the ALIVE branch only. | `combat.palette_index`, `_player_phase` |
| P6-d | **Berserk**: `p_strength` +1 a tic, saturating at 0xFFFF (alive branch only); the red tint `cnt = max(dc, 12 - (str >> 6))`; the fist's damage x10; key 1 stays on the fist while the chainsaw is ready and berserk runs. | `palette_index`, `_a_melee`, `_weapon_keys` |
| P6-e | **Drops**: a killed zombieman drops a clip and a killed sergeant a shotgun (`mon_drop` 0 -> 1, at P_KillMobj, gibs too). The drop sits at the corpse's position, its z the floor of the corpse's leaf sector at touch time (mover-aware). A taken drop: `mon_drop` 2. | `_kill_monster` (`self.dropper`), `_touch_specials` |
| P6-f | **Barrels in the aim**: shootable while `bar_state != 0 and bar_health > 0`, radius 10, after the monsters. A shot that names a barrel spawns a PUFF (the fx pool; the fist's puff S_PUFF3) and then damages it. | `shootable_targets`, `_line_attack`, `_spawn_fx_at_target`, `_spawn_fx` |
| P6-g | **Barrel damage**: health saturates at -128. The killing blow sets S_BEXP plus a tics roll on `rng_world`. A non-lethal hit DRAWS `rng_world` once (painchance 0: the roll never fires). | `damage_barrel` |
| P6-h | **The barrel state machine**: S_BAR1 <-> S_BAR2 (6 tics each; the level-start phase roll is on `rng_world`), then S_BEXP .. S_BEXP5 (5, 5, 5, 10, 10). A_Explode runs on ENTERING S_BEXP4. S_NULL removes the barrel (state, tics, solid all 0). Barrels go by index; a barrel a blast killed this tic with a HIGHER index ticks in the same pass. | `_barrel_set_state`, `_barrels_phase`, `World._reset_state` |
| P6-i | **P_RadiusAttack** (128): the living player, then monsters by slot (active, shootable, health > 0), then the other barrels by index. Each takes `128 - d`, where d = max(0, Chebyshev(centre, spot) - radius), when d < 128 and the 2D LOS (`los_points`) holds. A monster's damage has source "player": no reach test, no blood, the target switch. | `_radius_attack`, `World.los_points`, `damage_monster`, `damage_player` |
| P6-j | **The player is blocked by solid things**: monsters (`mon_active and mon_solid`), barrels (`bar_solid`), the skill's solid decor. A strict box overlap at each candidate; any blocker refuses that candidate. | `_solid_thing_at`, `_player_move` |
| P6-k | **Nukage**: at the TIC-START position, before anything else in the alive branch. If `leveltime & 31 == 0`, the player's sector is special 7 (sectors 23, 38, 173; 5 damage), and the box's floorz (`check_position`) equals the sector's floor -> `damage_player(5)`. | `_special_sector`, `SECTOR_HURT` |
| P6-l | **Gibs**: a monster whose health falls below `-spawnhealth` takes its xdeath state (zombieman, sergeant, imp; the demon and the spectre have none). Barrels (128) and berserk (up to 200) reach it. | `_kill_monster` |
| P6-m | `leveltime` +1 at the end of every non-frozen tic (nukage reads it). | `World.tic` |

### 1.2 What P7 builds in fj

| # | behaviour | model |
|---|---|---|
| P7-a | **The dead branch is chosen ONCE**, on `p_dead` as the tic found it, at the player phase's start. Dead: the death think only, then the move is skipped. **A nukage kill inside the alive branch does not stop that tic**: the weapon keys, the use lines, the psprites, the fades and the move (without pickups: "dead thing touching") all still run. The fj must LATCH the tic-start `p_dead` (P5's weapon-key skip, `weaponcode.weapon_lines(hurt=True)`, reads `p_dead` live and must read the latch). | `_player_phase` |
| P7-b | **The death think**: P_MovePsprites (the weapon stays at the bottom), `p_dc` -1. While `use` is HELD, `g_restart = 1`. bc does not fade, strength does not grow, there is no move or turn, no nukage, no weapon keys, and no use lines. | `_death_think` |
| P7-c | **A dead player presses no door**, does not hold a closing door, does not press the exit / SR lifts / the switch, and does not walk or turn. These are P5's follow-up F3 (#121 item 2). | `World._doors_phase` (`alive`), `World.door_touched` (`player_alive`), `_player_phase` (`_use_lines` only alive) |
| P7-d | **THE RESTART BLOCK**, at the START of the next world tic: every schema field except `RESTART_KEEP` (skill, mode, held keys) goes back to its level start for `ws.skill`. Then that tic runs with the frame's keys. Level start has `p_usedown = p_attackdown = 1`, so held use or fire does nothing. | `World.tic`, `_restart`, `level_start`, `RESTART_KEEP` |
| P7-e | **NEW GAME after death**: the menu's skill choice sets the skill and restarts. The P1.5 block runs on the menu frame. | `new_game`; `wall_renderer.menu_state_lines` |

### 1.3 In "full" but OUT of scope

| what | why |
|---|---|
| The player THING's states (S_PLAY*, its pain, attack and death frames: `_set_player_mobj`, `_player_mobj_tick`, the `_p_full` lines in `_fire_weapon` / `_a_fire_bullets`) | First person never shows them, and nothing reads them. No fj cell holds them, and the gates do not compare `p_mobj_state`. The only RNG they touch, the death's tics roll, is already P5's. |
| Sounds (A_Scream, A_XScream, A_Pain) | D5 |
| `lastlook`'s P_Random in P_SpawnMobj (drops) | The model makes no draw (world.py docstring: "No `lastlook`"). The spec is the model. |
| D3 a (drops and effects drawn before monsters) and D3 b (barrels exempt from the soft budgets) | P5 did not implement them for its mobiles, and recorded it (`gp-p5-interface.md`). P6 follows P5 (section 5) -> owner item O2. |

### 1.4 MODEL GAPS -- in the handoff's scope or the coordinator's brief, but NOT in the model

**G1 -- THE VIEW DROP (and the turn to the killer).** P_DeathThink lowers `viewheight` to 6 units and turns the dead
view toward the attacker by ANG5 a tic. `combat._death_think` says "without the view drop or the turn to the
killer", and keeps P_DeathThink's damage-count fade unconditional (consistent with having no turn). It cannot just
be added:
- the renderer BAKES the eye height per leaf (`wall_renderer` `_lines_descend_leaf`: `viewz` and `vzcbase` per viewz
  class);
- the plane bands are baked per (viewz class, key) (`_band_pair_lists`);
- P2b left 254 of 255 plane ids used.

So a 35-step view drop is a renderer feature (runtime viewz classes), not a P7 line. **Recommendation:** keep the
model's convention -- the dead view stays at eye height, the weapon down, and the red palette fades -- and record it
as a D5 simplification. **OWNER DECISION O1.** The turn to the killer is cheap in fj, but it is also absent from the
model, so it waits on the same decision. Adding it is a BEHAVIOUR change of "full" on a path v5 never reaches, so it
needs only a rehash (section 6.4).

**G2 -- the exit frame's order (model vs binary).**
- `World.tic` checks `g_leveldone` only at the tic's start, so after an exit press in the player phase it still runs
  the monsters, projectiles, barrels, fx and `leveltime` that tic.
- The binary skips them on `lvdone` (`p2a_gate.Mirror.run`: "the binary's tic runs after the player and skips on
  lvdone"; `wall_renderer.p5_tic_lines`: each pool phase "skipping itself while `lvdone`").

The mirrors agree only because no gate compares World.tic's own exit frame. **Fix in the model (package A):** after
`_player_phase`, `if ws.g_leveldone: skip to the seen hook`. v5 never exits (`level_done` 0 in all 11 runs, the
frozen totals), so this is a rehash (section 6.4).

**G3 -- drops are not in the model's leaf lists.** `World.leaf_lists` holds the mobiles: monsters, fireballs, fx. A
drop is drawn only through the oracle's row order (section 5). Nothing in the model needs it in a list, but any gate
that compares `sshead` / `thnext` must add the drop rows. Not a behaviour gap; a bookkeeping one.

Not gaps (checked): `pickup_z` is static and exact, because no pickup and no barrel stands in a door or mover sector
(MEASURED: 0 of 95, 0 of 22). Drops read `_floor_at` from the current `secs_c` (mover-aware), and fj gets the same
from the corpse leaf's seed (section 4, B).

---

## 2. United or split? -- UNITED, with a defined fallback

**Recommendation: ONE build, `PLAYER_MODE = "full"`.** Reasons:
1. **P7's fj is small and its budget ~0.** It is the dead latch and its guards, the restart trigger, `g_skill` and
   `g_rs`: perhaps 1-3K words. A separate build costs ~6 h for it: the build ~2.5 h, the counts-cache recount ~34 min
   (every `src/doomfj` change misses it), evidence ~1.5 h, then CR and CI.
2. **The restart audit should run ONCE, after P6's cells exist.** P6 adds ~15 persisted cells, ~180 nibbles (section
   4.5). Restarting before them means a second re-key and a second audit of the whole restart block.
3. **The `die` gate's best scenarios need P6**: death in nukage, death by a barrel.
4. **One model mode change**, fx -> full. No intermediate mode has to be threaded through `world.py`, `combat.py`,
   `monsters.py` and every gate.
5. The owner's 2026-10-04 rule ("merge small rungs") and the P4 and P5 precedents (each one build).

**The cost of uniting:** a failing gate has a wider blast radius. **Mitigation:**
- every package ships its fj harnesses with strict mutants BEFORE integration (criterion 2);
- `fight_gate.py` / `die_gate.py --oracle-only` pass, controls parting, BEFORE the build is started.

**THE FALLBACK (only if package D is not ready when A-C are): ship P6 alone at a new mode `"loot"`.**
- `PLAYER_MODES = ("walk", "fire", "shoot", "hit", "fx", "loot", "full")`, with two new ONE-rule helpers beside
  `player_resolves` / `player_hears` / `player_bleeds`:
  - `world.player_loots(mode)`, for ("loot", "full"): pickups and gives, drops, bonuscount, berserk, barrels in the
    aim / damage / blasts / puffs, blocking by things, nukage, gibs, `leveltime`;
  - `world.player_mortal(mode)`, for ("full",): the restart request and the dead guards (P7-a..e).
- "loot" must DRAW every random number "full" draws (the P3.2c rule). It does, because P7 adds no draw: the death's
  one `rng_pl` roll is P5's.
- In "loot", as in P5's "fx", no gate may reach a death (assert deaths == 0). A dead player would walk in the binary
  but not in the model, which is F3's mismatch.
- `combat._p_full` would then split into `_p_loot` (every P6 line in section 1.1) and `_p_mortal`. Because
  `_player_move` today touches and blocks unconditionally, "loot" vs "fx" must gate `_touch_specials` /
  `_solid_thing_at` explicitly for the first time, behind `player_loots`. `test_player_modes` gains the "loot" ==
  "full" stream check.

---

## 3. Streams (D10: one draw = one outcome-table lookup; the P3.2c rule)

| stream (fj cell) | new draws in P6/P7 | order |
|---|---|---|
| `rng_world` (NEW fj cell `rng_wd`, 2 nibbles) | `damage_barrel`: +1 on EVERY hit that lands on a live barrel -- the tics roll of S_BEXP on the killing blow, else the pain roll (painchance 0, the outcome never fires: a plain `hex.inc`). The level-start phase rolls of the 22 barrels stay BAKED per skill, as today; all 22 stand on every skill. | the player's shot (weapon phase), then the blasts in the barrel phase: the player, monsters by slot, barrels by index |
| `rng_pl` (P4.1's) | none new. Barrel and nukage damage to the player go through `dp_go` (P5: exactly one draw per hit that lands -- the pain roll, or the death's tics roll). The berserk punch is P4's 3 draws. | |
| `rng_fx` (P5's) | the PUFF spawn's tics roll (1 draw), exactly as blood's. A puff skipped by a full pool draws NOTHING. | in `_line_attack`, before the barrel's damage (P5's dm_leaf order: reach, fx, then the target checks) |
| `mon_rng[m]` (P3's) | a blast on a monster: ONE draw (the pain roll, or the death or gib tics roll), P4.2a's `dmrnd` | the monster's turn in the blast's slot order |
| pickups, drops, the death think, nukage's test, the restart | NO draws. The restart RE-SEEDS every stream to its level start (`World._reset_state`: `stream_seed` per stream, then the monsters' and barrels' level-start rolls). | |

---

## 4. fj labels and cells, with OWNERS

### 4.1 Package A -- the model, the oracle, the gates (Python; no fj)

- **Model** (`world.py`, `combat.py`):
  - `wall_renderer.PLAYER_MODE = "full"` in the game tier;
  - G2's exit-frame fix;
  - the helpers of section 2, only if the fallback is taken;
  - nothing else in "full" may change behaviour (section 6.4).
- **`monsters.MonsterPhase` grows a PLAYER half** -- the model's own code, not a re-implementation:
  - `move(kd, x16, y16, angle)` runs `World._player_move` + `_walkover` on the world `sync` already put the gate's
    doors and movers into (`World._door_phase_scene` -> `scene_c`). It returns the landing, and the events carry the
    pickups and blocks;
  - `nukage()` runs `_special_sector`, at the tic-start pose, before `weapon`;
  - `weapon()`'s dead branch adds the restart request (`use` -> `g_restart`), and `weapon()` takes the TIC-START dead
    latch (P7-a);
  - `restart()` runs `_restart`;
  - `state()` adds `loot_state()` (p_bc, p_str, p_bp, am_misl, am_cell, mdrop), `barrel_state()` (bar_st, bar_ti,
    bar_hp, bar_solid, rng_wd) and `game_state()` (lvtime, g_rs, g_skill), in the cells' units (4.5);
  - `mobiles()` appends the drops (section 5);
  - `barrel_views()` and `hidden()` are new (section 5);
  - `palette()` is unchanged (`combat.palette_index` already reads bc and strength).
- **`MonsterViews`**: `aim_things` adds the live barrels (`sid = 1 + nmon + b`, radius class 10). `rt_state` adds
  the 25 drop rows (nt + 10 + k). `combat.window_aim` maps `sid > nmon` to `("bar", sid - 1 - nmon)`.
- **The oracle** (`reference_model.render_wall_frame`), ALL OPT-IN so the default picture is today's (and census_lib's,
  F4):
  - `barrel_views={drawable index: lump}`;
  - `mobiles` entries may carry a 4th element, `z` above the floor (default `MISSILE_Z` = 32: P5's tuples unchanged;
    drops pass 0);
  - `aim_things` accepts radius 10.

  `scratchpad/gp/p67_identity.py` re-runs `p5_mobiles_identity.py`'s proof: v5 R0-west-hall, 60 frames,
  `GAME_RENDER_KW`, byte-identical with every new keyword absent.
- **Gates**:
  - `p2a_gate.Mirror.run` under "full": the move is `MonsterPhase.move`, not `step_sim` + `DoorPhase.touch`. The
    card is the World's `p_cards[IT_BLUECARD]`, so `pcard` stays its fj cell and the card's +12 bonus comes with it.
    The door phase's use press and the closing-door contact exclude a dead player (P7-c: `DoorPhase.tic`'s `use`
    and `others`). The restart runs at the next world frame's start. NEW GAME sets `g_skill`;
  - the same player step in EVERY gate that drives a prebuilt game-tier binary: `m2_std_gate`, `m3_gate`,
    `m2_r4_gate`, `gatestate_check`, `hurt_gate` (`MMODE, PMODE = "full", "full"`; it asserts them against
    `wall_renderer`), and `scenarios_v2.BinaryMirror` (B0). A host test in the style of `test_oracle_calls_in_step`
    refuses a bare `rm.step_sim` in a gate's game-tier path (rule 5, fan-out);
  - `probe.game_cells` gains the optional groups of 4.5, and `gatestate.STATE_NAMES` the new state cells;
  - `fight_gate.py` and `die_gate.py` (section 6), in `hurt_gate.py`'s shape, reusing its `Run` / `place` /
    `parts` / `control`.
- **Host tests**:
  - `test_player_modes` ("full" is the target; "loot" too, if split);
  - `test_p67_model` (the dead latch on a nukage death; the exit-frame order; the restart covers every field but
    `RESTART_KEEP`);
  - `test_mobiles_oracle` (drops at z 0);
  - `test_barrel_tables` (section 4.3's static chain, with a control);
  - the gamespeed model prediction of section 8.3.

### 4.2 Package B -- the player's side in fj (`doomfj/lootcode.py` NEW; edits to `doorcode`, `collision`, `weaponcode`, `hurtcode`, `movercode`)

- **The pickups** (`lootcode`), in `collision.move_with_collision_lines(pickup=...)` at each candidate (`cpx`, `cpy`,
  16.16; `cm_hf` the tic-start floor). This generalises P2a.1's `doorcode.card_pickup_lines`; the card becomes one
  item.
  - `pk_go` / `pk_ret`: a jump on the candidate's PICKUP CELL. The grid's size is the package's choice (the handoff
    suggests 64 units), proven exact on the host by interval arithmetic over closed cells at 16.16 with a mutated
    entry as the control (rule 4).
  - The jump lands on a cell's list of item stubs `pk<i>`, in pickup index order. Each stub does: present
    (`thvis` slot != 0) -> box test -> reach test (`item_z` baked) -> `stl.fcall give_<type>, gv_ret` ->
    `gv_ok` ? (vanish + `p_bc` += 6, sat 255).
  - Then the drops: if `dr_live` != 0, for each dropper k with `mdrop[k] == 1`: box test against the corpse's
    row (`thpos_rt` row of its monster), then reach against the corpse leaf's floor (`ptss` <- `thss_rt`,
    `stl.fcall ms_seed_leaf` -> `cp_seedf`, P3.2b's mover-aware seed).
  - One give routine per type, `give_<type>` (section 1.1 P6-b). The caps come from ONE D4 table `amcap` indexed by
    (backpack, ammo), with no runtime multiply (rule 3). P_GiveAmmo's auto-switch writes `wp_pend`.
- **The vanish**:
  - a BAKED pickup: `hex.zero 2, thvis + slot*2*dw` (as P2a.1);
  - a RUNTIME pickup (10 of the 68 runtime things: 4 SHEL, 4 BON1, SBOX, CELL -- MEASURED): unlinked from its leaf
    list (`rt_unlink`, owner C) AND its own `thvis` slot zeroed. Package B gives the runtime pickups slots too, so the
    probe reads "taken" for all 95 pickups the same way.
- **Player blocking**:
  - the static blockers (22 barrels with presence `bar_solid`, the 57 solid decor with `mc_don` per skill) go into
    the PLAYER's collision cells through `collision.collision_cells_fj(things=...)`. This is the mechanism P3.2b built
    for the monsters (`monstermove.static_blockers`, `sim.thing_test`), with the cell lists recomputed for radius
    16 + the thing's radius;
  - the monsters through `pb_mon`, `monstermove.things_leaf_lines`' shape: per slot `if0 mon_solid`, then
    |dx| < r + 16 and |dy| < r + 16, at the candidate's integer part against `thpos_rt` -- but strict and in 16.16
    against the player (the model compares `mon_x << 16` with the 16.16 candidate);
  - optional: a once-per-tic prefilter (the monsters within Chebyshev 67 of the tic-start pose: 46 box + 21 the
    largest step), if the probe shows the plain scan above ~8K a candidate.
- **Nukage** (`nk_go`, before the weapon, alive only):
  - `lvtime & 31 == 0` -> `ptloc_walk` on the player's integer position -> a leaf -> D4 table `nkleaf`
    (1 = sector special 7) -> the cells' floor query at the tic-start position (`cp_*`, the move's own) ->
    `== sector floor` -> `dp_dmg = 5`, `stl.fcall dp_go, dp_ret`;
  - computed on demand: nothing derived persists.
- **Bonus and berserk**:
  - `p_bc` and `p_str` fade or grow after `p_dc` in the alive tic (`hurtcode`'s `hp_tic` grows);
  - `palidx` becomes the ST_doPaletteStuff rule over (dc, strength, bc): red 1..8 (2..8 reachable), gold 9..12;
    `playpal9..12` are emitted (P5 emitted 0..8);
  - `weaponcode`: the fist's damage x10 while `p_str != 0` (a second field in `wpo`'s row, or a D4 table `bk10`;
    `dm_dmg` <= 200), and key 1's rule `not (wp_rdy == chainsaw and p_str != 0)` (`weapon_lines`' `wk_saw`).
- **P7's player side**:
  - `p_dd0` (1 nibble, scratch) = `p_dead` at the player phase's start;
  - dead -> `dt_go`: psprites, the `p_dc` fade, `kb_u` -> `g_rs = 1`; then jump past nukage, the keys, the
    strength / bonus and the move (`simcollide`, turning included);
  - guards on `p_dd0` (the TIC-START state): the door tic's use press (`doorcode`'s trigger lines), the closing door's
    player contact (P2b's reversal), the use lines (the exit, `movercode`'s SR lifts, the floor switch), and
    `weapon_lines(hurt=True)`'s key skip.

### 4.3 Package C -- the world's side in fj (`doomfj/barrelcode.py` NEW; edits to `damagecode`, `projcode`, `monstercode`, `monstersight`, `wall_renderer`'s thing emission)

- **The barrel phase** `bar_phase` / `bar_pret`, ONE fcall after `pj_phase` and before `fx_phase` (world.tic's order),
  skipping itself while `lvdone`. Per barrel b, a fixed stub (rule 1):
  - `bar_st[b] == 0` -> skip;
  - `bar_ti[b] -= 1`; at 0 -> the next state by a D4 `barnext` on the local state;
  - entering S_BEXP4 -> `stl.fcall bl_go<b>` (A_Explode); S_NULL -> state, tics and `bar_solid` all 0, the sprite
    hidden (`thvis` 0, or `rt_unlink` for the 2 runtime barrels).
- **The blast** `bl_go<b>` -> ONE shared leaf `bl_leaf` with the barrel's spot in `bl_px` / `bl_py` (integer
  constants):
  1. the player, if alive: Chebyshev in 16.16 minus 16 -> `d` (integer, `>> 16` of the non-negative part) ->
     `d < 128` -> LOS -> `dp_dmg = 128 - d`, `dp_go`;
  2. the 53 monster slots in order, one shared loop body per slot stub: active and shootable and health > 0 ->
     Chebyshev minus radius (20 or 30) -> LOS -> the dm path in BLAST mode (below);
  3. the other barrels, BAKED: barrel b's static list of (c, damage), in c order, is `if bar_st[c] != 0 and
     bar_hp[c] > 0: damage_barrel(c, const)`.
     - MEASURED: 96 in-range ordered pairs, ALL with a statically clear LOS (no wall and no door segment touches the
       segment), so the pair's damage and verdict are compile-time constants.
     - An emit-time assert holds both; its control moves one barrel by 200 units, or adds a blocking segment, and
       must be refused.
- **The blast's LOS** `bl_los`: a NEW ENTRY into P3.2c's machinery (`monstersight.near_los_lines`).
  - P = the barrel (integer). Q = the target in 16.16, `bl_qx` / `bl_qy` (the player's viewx / viewy, or a monster's
    `thpos_rt` row).
  - It sets up the registers `sl_los`' prologue sets (`sl_p*`, `sl_u*`, the box). Instead of the cell tree it jumps
    to barrel b's STATIC list of `sg<k>` segment blocks: every sight segment whose box meets the barrel's box grown
    by 128 + 30 + 1.
  - It reuses the shared `sl_seg` and the dynamic-door reads unchanged.
  - The fj ABI is frozen (rule 4), so this is a new entry, never a changed `sl_los`.
  - `monstersight._bounds` must re-prove its 48-bit products for traces up to Chebyshev 159 (NEAR_MARGIN is 129
    today).
  - `segments_touch(p, q, ...)` vs `(q, p)`: the model calls `los_points(target, spot)`; a host test holds the
    symmetry (or the fj passes the model's order).
- **damagecode** (`dm_go` / `dm_leaf`):
  - the id space grows to `1 + nmon + nbarrel` (76 <= 0x7F: `aim_sid` and `dm_id` stay 2 nibbles). A barrel id jumps
    to `dmb<b>`: the reach test, the PUFF (`fx_spawn` with `fxs_kind`), then `damage_barrel`;
  - `dm_melee` value 2 = BLAST: no reach, no fx, source the player;
  - THE GIB: `health < -spawnhealth` and xdeath != S_NULL -> the xdeath state, with the same one tics draw.
    `check_model_rules`' "no gib" assert (`max_dmg <= spawnhealth + 1`, with DM_MAX 20) is replaced by the gib
    branch's own asserts: every xdeath state >= 4 tics (MEASURED: 5); A_Fall in each xdeath chain (the imp's
    S_TROO_XDIE chain: assert it reaches A_Fall further down, else `mon_solid` never clears); DM_MAX 200 (the berserk
    fist); `mon_health`'s 12 bits hold 60 - 200;
  - a kill on a DROPPER slot -> `stl.fcall drop_link<k>`: `mdrop[k] = 1`; row nt + 10 + k = the corpse's row; the
    leaf = its `thss_rt`; inserted in index order (P1.3 / P3.2b list code); `dr_live` += 1.
- **projcode**: `fx_spawn` takes `fxs_kind` (0 blood by damage, 1 puff, 2 the fist's puff -> S_PUFF3). The puff states
  S_PUFF1..4 (gamedata 42..45, 4 tics each) join `fx_st` and `mobview`.
- **Drawing (owner C; the rules are section 5)**:
  - the barrel views by state;
  - the drop rows and their view rows `CLIPA0` / `SHOTA0`;
  - the puff view rows `PUFFA0..D0`;
  - the barrels' aim record -- a baked thing never records today: `aimcode` docstring, `projection.fj`
    `project_thing`'s `aim` parameter, "1 for the runtime monsters' projections only".
- **`rt_unlink`** (shared, owner C): remove runtime thing t from its leaf list. It is used by a taken runtime pickup,
  a removed runtime barrel and a taken drop.

### 4.4 Package D -- the restart and persistence (P7; `wall_renderer.restart_lines`, `build`, `scratchpad/m5_setfile.py`)

- **`g_skill`** (1 nibble, the SKILLS index like `menu_sel`), set by NEW GAME. `menu_sel` cannot serve: the skill
  screen's up / down move it even when esc backs out.
- **`g_rs`** (1 nibble) = `g_restart`.
- **The restart**: at `do_world`, before the frozen-level guard and the door tic: `hex.if1 1, g_rs` -> dispatch on
  `g_skill` into the SAME per-skill blocks NEW GAME runs. Refactor `restart_lines`' inline per-skill halves into
  fcall'd `rs_skill<k>` + `restart_common`, called from both. Model: restart, then the tic.
- **Every persisted cell gets its level-start line.** The ones P6 / P7 add:
  - `bar_st` / `bar_ti` (the BAKED phase rolls), `bar_hp` 20, `bar_solid`, `rng_wd` (its seed after the 22 rolls);
  - `mdrop` 0, the drop rows (0, 0), `dr_live` 0;
  - `p_bc` 0, `p_str` 0, `p_bp` 0, `am_misl` / `am_cell` 0, `lvtime` 0, `g_rs` 0;
  - `thvis` for all 95 pickups, per skill.

  P1-P5's cells must also be checked; the audit is the test below, not a list.
- **NEVER the device shadows.**
  - `pal_cur`: a death restart goes world frame -> world frame, with no menu frame between. Zeroed while the device
    shows red, the palette would never be re-sent.
  - `hud_s`: the bar's screen copy.

  NEW GAME is safe today only because menu frames force palette 0 and redraw the bar.
- **`test_restart_coverage`** (host):
  - for each skill, the cell values the fj restart writes == `World.level_start(skill)` mapped through the probe's
    units, for EVERY label in `build.persist_labels(standalone=True, ...)` minus the input / menu / device ones;
  - controls: one restart line dropped; and one line restoring `pal_cur`.
- **`test_restart_fj`**: run the real block on a messy state and read every cell, with a mutant.
- **Persist sets** (`build`):
  - `LOOT_PERSIST` = (p_bc, p_str, p_bp, am_misl, am_cell, mdrop, dr_live);
  - `BARREL_PERSIST` = (bar_st, bar_ti, bar_hp, rng_wd) (`bar_solid` is already in `MONSTER_PERSIST`);
  - `GAME_PERSIST` = (lvtime, g_rs, g_skill);
  - all added to `persist_labels` AND to `game_screen_persisted_decls` (P5's lesson 35fc488: the standalone set gets
    them only through it);
  - confirm how `thvis` survives the M1 reset today (it is in no `*_PERSIST` tuple, yet P2a.1's card stays gone), and
    that the drop rows ride `THING_PERSIST`'s `thpos_rt` / `thss_rt`;
  - re-key `m1_` / `m5_restore_set.json.gz`; `test_restore_set_shipped`.

**As built (package D, branch `p67-d`):**
- `doomfj/restartcode.py` owns `g_skill` / `g_rs` / `lvtime` (`PERSIST` = `build.GAME_PERSIST`). They are declared in
  `wall_renderer.MENU_STATE_DECLS` (the standalone globals, like `lvdone` / `pusedn`), so m5_setfile re-attaches them
  through `STANDALONE_SCRATCH_DECLS` -- NOT through `game_screen_persisted_decls`, which would declare them twice.
- ONE sequence: `restartcode.call_lines` = `stl.fcall restart_common` + a dispatch on `g_skill` into fcall'd
  `rs_skill<k>` (`routine_lines`). NEW GAME = `hex.mov 1, g_skill, menu_sel` + it (`new_game_lines`); the restart on
  use = `if g_rs` + it (`tic_lines`, at the world frame's start, emitted when `restartcode.mortal(PLAYER_MODE)`).
  `wall_renderer.compose_restart` is the one composition the emitter calls and tests/fj/test_restart_fj.py runs.
- `lvtime` +1 is `p5_tic_lines`' first line inside its `lvdone` guard.
- The audit (`test_restart_fj`, two dirty images, every nibble of every `persist_labels` cell) found TWO gaps in P1-P5
  and they are fixed: `mh_prev` (P3.2b) was never restarted (now zeroed in monstercode's per-skill restart), and the
  P5 restart RESTORED `pal_cur` (hurtcode.restart_lines no longer writes it).
- `thvis` and `thnext` survive the M1 reset by being in NO restore set (`PERSIST_BY_ABSENCE`); the restart writes both,
  and the audit checks them. The drop rows ride `thpos_rt` / `thss_rt` (THING_PERSIST); their extent is the label's.
- The dead view's turn to the killer (section 10, O1): `p_atk`, `pj_src`, `dt_turn` -- see there.
- INTEGRATION HOOKS (B / C): `build.LOOT_PERSIST` / `BARREL_PERSIST` (empty until the modules land), their decls in
  `game_screen_persisted_decls`, and their level start into `compose_restart(p6_common=, p6_skills=)` from
  `restartcode.level_start_lines` (section 4.5's units transcribed in `p6_cell_values`; held equal to package A's
  `MonsterPhase.*_state` by `test_the_p6_units_are_package_as` once those exist). `test_every_p6_module_persist_is_wired`
  fails while a module exists unwired.

### 4.5 The new cells and their units (what the probe reads; one definition: `MonsterPhase.loot_state` / `barrel_state` / `game_state`)

Hex cells, nibbles little-endian, read UNSIGNED unless said.

| fj cell | nibbles x count | model field | units |
|---|---|---|---|
| `p_bc` | 2 | p_bonuscount | 0..255, +6 per take (the card: set 6, then +6), saturating |
| `p_str` | 4 | p_strength | 0..0xFFFF, 1 at the berserk, +1 a live tic, saturating |
| `p_bp` | 1 | p_backpack | 0/1 |
| `am_misl`, `am_cell` | 3 each | p_ammo[AM_MISL], p_ammo[AM_CELL] | 0 .. 2 x maxammo. Kept although no E1M1 weapon reads them: `_give_ammo` refuses at the cap, so the counts decide whether an item is taken. |
| `thvis` | 2 x (vis slots + the 10 runtime pickups) | 1 - pickup_taken | 1 present, 0 taken or not on this skill |
| `mdrop` | 1 x 25 (one per DROPPER k, the monster slots `dropper[m]` is not None for, in slot order: 12 clips, 13 shotguns -- MEASURED) | mon_drop[slot] | 0 none, 1 dropped, 2 taken |
| `dr_live` | 2 | (derived) | the count of `mdrop == 1`: a fast skip; scratch-checked against the model |
| `bar_st` | 2 x 22 | bar_state | the gamedata index: S_BAR1 203, S_BAR2 204, S_BEXP..5 205..209; 0 removed |
| `bar_ti` | 1 x 22 | bar_tics | 1..10 |
| `bar_hp` | 2 x 22 | bar_health & 0xFF | 8-bit two's complement, 20 at the start, saturating at -128 |
| `rng_wd` | 2 | rng_world | the stream index |
| `lvtime` | 4 | leveltime | 16 bits, wraps |
| `g_rs` | 1 | g_restart | 0/1 |
| `g_skill` | 1 | skill | the SKILLS index (0 easy, 1 medium, 2 hard); the probe maps it to gd.SK_* |
| `p_atk` (P7, hurtcode.CELLS) | 2 | p_attacker (NEW schema field, phase "P7") | player->attacker: 0 none (sector damage; a barrel's blast -- its source is the player who set it off), else 1 + the monster slot of the last hit that LANDED (hitscan, claw, bite, or the fireball's shooter). Restarted to 0. |
| `pj_src` (P7, projcode.PJ_FIELDS) | 2 x 8 | proj_src | the fireball's shooter, 1 + its slot while the slot is live, 0 free |
| `fx_st` (P5) | -- | fx_state | adds S_PUFF1..4 = 42..45 |
| `aim_sid` (P4.2a) | -- | aim_sid | 1..53 a monster slot + 1; **54..75 barrel b + 54** |
| `thpos_rt` / `thss_rt` rows nt+10 .. nt+34 | -- | (drops) | dropper k's row: the corpse's whole-unit row and leaf while `mdrop[k] == 1`, else (0, 0) and in no list. nt = 68 MEASURED, so rows <= 103 <= `things.LIST_MAX_THINGS` 254. |

Probe OPTIONAL_GROUPS (each whole or not at all):
- {p_bc p_str p_bp am_misl am_cell} (B);
- {bar_st bar_ti bar_hp rng_wd} (C);
- {mdrop dr_live} (C);
- {lvtime g_rs g_skill} (D).

### 4.6 Tables and shared leaves (NEW; each jump/dispatch macro declared SAFE in `build_blocked.py`'s `SAFE_TABLE_MACROS`, rule 5)

| table | owner |
|---|---|
| pickup grid tree + `pk<i>` stubs | B |
| `give_<type>` (17 types on E1M1) | B |
| `amcap` (backpack x ammo -> cap) | B |
| `nkleaf` (leaf -> nukage) | B |
| `palidx` widened (dc, strength, bc) + `playpal9..12` | B |
| `bk10` (berserk punch) | B |
| `pb_mon` | B |
| `barnext` (barrel local state -> next, tics, action) | C |
| `bl_go<b>`, `bl_leaf` | C |
| the per-barrel LOS lists | C |
| the barrel chain lists | C |
| `dmb<b>`, the gib profile rows | C |
| `drop_link<k>` / `drop_take<k>` | C |
| the barrel view constants (section 5) | C |
| `mobview` + 6 states (puffs, drops) | C |
| `aimr` + radius class 10 | C |
| `rs_skill<k>` | D |

The leaves new code CALLS:
- `dp_go` (P5), `dm_go` / `dm_leaf` (P4.2a), `fx_spawn` (P5);
- `ptloc_walk`, `ms_seed_leaf` (P3.2b);
- `sl_seg`, `sg<k>` (P3.2c);
- the leaf-list insert (P1.3 / P3.2b);
- the cells' `sim.thing_test` (P3.2b);
- `restart_common` (P1.5).

No new macro carries an `@`-local data cell (rule 7).

### 4.7 THE FRAME ORDER (fj), new pieces in bold

1. The menu state machine. NEW GAME: the restart block, **`g_skill` = the chosen skill**.
2. `do_world`: **`if g_rs: restart(g_skill)`** (the model's tic start).
3. The frozen-level guard (`lvdone`).
4. The door tic: the use press needs **`!p_dd0`**; the closing door's player contact needs **`!p_dd0`**.
5. The movers.
6. The use lines (exit, SR lifts, the switch) **`!p_dd0`**.
7. **`p_dd0 = p_dead`**. If dead: **the death think** (psprites, `p_dc` -1, held use -> `g_rs`) and go to 9.
   Note: step 4 runs before step 7 sets `p_dd0`; between the tic's start and here nothing writes `p_dead`, so the
   coordinator places the latch at the frame's tic start.
8. Alive:
   - **nukage**;
   - the weapon keys (berserk's key-1 rule) -- skipped on `p_dd0`, NOT on a live `p_dead`;
   - the psprites (the berserk fist x10);
   - **`p_str` +1**; `p_dc` -1; **`p_bc` -1**;
   - the move: at each candidate, **pickups (map things, then drops)**, **the solid things (`pb_mon`, the static
     blockers in the cells)**, the lines; then the walk-overs.
9. The monsters (K slots, `tic_after_eye`).
10. Then:
    - `pj_phase`;
    - **`bar_phase`** (A_Explode -> `bl_leaf`);
    - `fx_phase` (blood and **puffs**);
    - **`lvtime` +1**;

    all inside the `lvdone` guard. G2: the model is aligned to this.
11. `hp_bar`.
12. The palette: **`palidx` with bonus and berserk**.
13. The render:
    - **barrel views by state**, **hidden pickups and barrels**, **drops**, **puffs**, gib frames;
    - the aim window **with barrels**;
    - `seen`.
14. Present.

The model's order differs in two places, both COMMUTING:
- `_use_lines` runs after the weapon keys in the model. The keys write only `p_pending`; the use lines write only
  `g_leveldone` / `l_req` / `f_switch`.
- Nukage runs before the use lines in the model. Nukage reads neither; the use lines read neither health nor `p_dead`.

Host tests hold both (`test_p67_model`).

---

## 5. Rendering

All new oracle rules are OPT-IN keywords (section 4.1), so `census_lib`, v5's F4 drawn populations and every
existing picture stay byte-identical. That is proven by `p67_identity.py`, as P5 proved `mobiles=`.

- **Pickups vanishing.**
  - P2a.1 hid the taken card: the gate passed `hidden_extra=(card_di,)`, the oracle's `thing_hidden`, and the fj
    zeroed the card's `thvis` slot, so the baked projection's `hex.if0 1, thvis + slot*2*dw` skips it
    (`wall_renderer`'s baked-thing emission, M14.5 section 3.3).
  - Generalised: the oracle hides EVERY pickup with `pickup_taken` (`MonsterPhase.hidden()` maps pickup index ->
    drawable index by (type, x, y, angle, flags), `MonsterViews`' key) and every barrel with `bar_state == 0`.
  - The fj: baked -> `thvis` 0; runtime (10 pickups, 2 barrels) -> `rt_unlink`. `render_wall_frame(thing_hidden=)`
    already accepts runtime absences, but only the skill's (`docs/gp-skill-menu.md`: "the runtime things named must
    be exactly the ones one skill does not spawn"). Package A widens that assert to "the skill's, plus the taken or
    removed ones the model names".
- **Barrels by state.** Each barrel's lump is its state's frame at rotation 0: BAR1A0 / BAR1B0 / BEXPA0..E0
  (`monsters.mobile_lump`'s rule).
  - **Oracle**: `barrel_views={drawable index: lump}`. The class and both depth bounds are recomputed from the
    lump's art, exactly as the fj bakes them.
  - **fj, baked barrels (20 of 22)**: the barrel's thing call site jumps on its local state (`sim.jump16`, rule 5)
    into ONE of 7 xor-constants blocks. Each block is the baked thing's `THING_XORBY_FIELDS` for that lump --
    `sp_z`, `sp_left`, `sp_w`, `sp_hh`, `sp_tzmax`, `sp_tzmax2`, `sp_base`, `sp_dw`, `sp_lt` all follow the art --
    plus, for the two live views, the aim id (`sp_sid` = 54 + b, `sp_rc` = class 10).
  - The schema check that ties the xor block to `sim.thing_pass`'s clears (`THING_XORBY_FIELDS`) grows with
    `sp_sid` / `sp_rc` if the baked path is to record aim. C chooses, by a probe:
    - (i) `aim = 1` on the shared baked projection, `sp_sid` 0 for every other baked thing (~25 ops per baked
      projection, a test that skips);
    - (ii) a second instantiation of the baked leaf with `aim = 1`, for barrels only (size).
  - **fj, the 2 runtime barrels**: row-select stubs into view rows by state (the monsters' `thsel` pattern), with
    `sp_sid` set while alive.
  - The class stays SCENERY, with the graduated bounds of today. This is NOT D3 b (O2).
- **Drops**: mobile rows nt + 10 + k, drawn as P5's mobiles are, EXCEPT standing on the floor:
  - the art's top + 0, not + `MISSILE_Z`;
  - the oracle's `mobiles` entry (x, y, "CLIPA0" / "SHOTA0", 0), appended after the fireballs and the blood in
    dropper order;
  - scenery class, the base minimum height in both bounds (P5's mobile rule), never seen, never aimed;
  - a drop and its corpse tie on the aprox depth key, and the row order breaks it: the corpse (a WAD row < nt) first.

  D3 a would draw drops BEFORE monsters; P5 sorted its mobiles by depth instead, and P6 follows (O2).
- **Puffs**: P5's fx rows, `mobview` + S_PUFF1..4 -> PUFFA0..D0, at `MISSILE_Z`, like blood.
- **Explosions**: the barrel's own views BEXPA0..E0 (above). No pool slot.
- **Gibs**: the monsters' views follow `mon_state` (`MonsterPhase.views`), and P1.6's bank holds every entry state's
  frames, xdeath included (`wall_renderer.anim_frames` follows `MobjInfo.entry_states`, which lists `xdeathstate`).
  C asserts at emit time that `monstercode.p31_parts`' `view_rows` cover every xdeath state's views.
- **The dead player's view**: unchanged geometry (G1). The weapon at WEAPONBOTTOM (P5), and the palette fades.

---

## 6. Gates

`fight_gate.py` (P6) and `die_gate.py` (P7) take `hurt_gate.py`'s shape:
- p2a_gate's `Mirror` in the "full" modes;
- frame-0 pokes of every cell a setup moved (`poke_cells`; every poked cell must be persisted);
- candidates placed on the oracle until the claim holds;
- STATE-, PIXEL- and PALETTE-exact on every frame;
- every event counter nonzero;
- each R9 control an ORACLE MUTATION that must part on some frame of its scenario, else the gate FAILS as vacuous.

Both have `--oracle-only` and `--only`. Both must pass `--oracle-only` before the build is started.

### 6.1 `fight` (deaths must be 0: a death FAILS it, loudly)

| id | scenario | claim | controls |
|---|---|---|---|
| F1 | pickups at hard, from a pose beside a cluster: health bonus, armor bonus, a stimpack below 100, a clip, a shell box | pickups >= 4, bonus palette frames >= 1 | `bonus_cap` (BON1 capped at 100), `bonus_round` (gold without the +7), `reach` (the z window dropped), `order` (drops before map things -- with F4's corpse in reach) |
| F2 | refused pickups: a medikit at 100 health, a clip at max ammo (poke) | item stays (thvis 1, drawn), no bonus | `give_always` |
| F3 | the chainsaw (sector 139): owned, pending, raised; key 1 keeps it | `wp_own` chainsaw, `wp_rdy` 3 | `no_pending` (a new weapon is not made pending) |
| F4 | drops: kill a zombieman (clip) and a sergeant (shotgun at hard, the only shotgun); see each drop drawn; walk over them | 2 drops drawn, 2 taken, `am_clip` +5, the shotgun owned | `no_drop`, `drop_full_clip`, `drop_z` (the drop at MISSILE_Z) |
| F5 | berserk at MEDIUM (the menu's NEW GAME medium in the first frames, `MonsterPhase.reset`): take PSTR; red tint fades; punch a zombieman -> gib (x10) | `p_str` > 0, a gib, berserk palette frames | `berserk_x10`, `strength_pal`, `gib` (the gib branch dropped) |
| F6 | barrels: shoot a barrel near a monster: puff, BEXP drawn, the blast kills (gib) the monster, which drops; the player inside 128 and hurt (armor poked so that he lives) | barrel_blasts >= 1, puffs >= 1, a blast kill, player_hurt by a barrel | `blast_los`, `blast_cheb` (aprox instead of Chebyshev), `blast_order` (barrels before monsters), `barrel_pain_draw` (no rng_world on a non-lethal hit), `puff_melee` |
| F7 | THE CHAIN: the cluster of barrels 14-18 (8 in-range neighbours each, MEASURED) set off by one shot | barrel_blasts >= 3 | `chain_same_tic` (a killed higher-index barrel not ticked this pass) |
| F8 | blocking: walk into a barrel, a solid decor, a live monster, a corpse (passes) | player_blocked >= 3, the slide | `walk_through` (`player_blocking=False`), `corpse_blocks` (mon_active instead of mon_solid), `decor_skill` |
| F9 | nukage: stand in sector 23 for 70 frames; once on a ledge over it (no damage: the floor test) | nukage hits >= 2 | `nuk_period` (every 16), `nuk_floor` |
| F10 | the card: walk onto it | `pcard` 1, `p_bc` 12, gold palette | `card_bonus` (+6 only) |
| S2 | stress: the chain of F7 in view, every barrel of the cluster | recorded ops/frame (no claim on ops) | -- |

### 6.2 `die` (every scenario must reach a death: deaths >= 1 per scenario; a scenario that does not die FAILS)

| id | scenario | claim | controls |
|---|---|---|---|
| D1 | `p_hp` poked to 6 in front of a zombieman; after death hold forward / turn / fire / 1-4 | pose and angle frozen after death, weapon at bottom, `wp_pend` unchanged, red fades | `dead_walks`, `dead_turns`, `dead_keys` |
| D2 | die in a doorway while the door closes | the door does NOT reverse on the dead player | `dead_holds_door` |
| D3 | die beside a door / in the exit box, then press use | no door press, no level end: the RESTART next frame | `dead_uses` (door), `dead_exits` |
| D4 | the restart: after D1, use -> the next frame is the level start at the same skill (every cell, drawn) | restarts 1, state == `level_start(skill)` + this tic | `restart_partial` (one cell kept: `pickup_taken`, `mdrop`, `bar_st` each a control), `restart_skill` (restarts at hard), `use_edge` (needs a press, not held) |
| D5 | NEW GAME after death: esc, NEW GAME, easy | the easy level start (monsters, berserk and backpack present) | `ng_skill` |
| D6 | death by nukage (`p_hp` 5, in sector 23): the NUKAGE-DEATH TIC still runs the weapon keys and the move | the latch | `latch` (the dead branch re-read after nukage) |
| D7 | death by a barrel blast (and a gib-depth one, < -100) | deaths 1 | -- |
| D8 | death while the gold flash runs: bc frozen while dead | the gold palette after the red fades | `dead_bonus_fade` |

### 6.3 Every other gate

- `hurt_gate` re-points to "full": H1-H6 and S1, deaths still 0.
- m2_std_gate, m3_gate, p2a_gate, m2_r4_gate, gatestate_check: each now PRINTS a deaths counter and asserts its
  expectation (their walks expect 0). No gate may silently skip a death: a dead player is now a different trajectory
  in both mirrors.
- deg_gate stays BYTE-EXACT with op counts equal to blocked48's. It runs the visual tier, which takes none of this
  code: the game tier alone emits the new code, behind `PLAYER_MODE`.
- The label-coverage report (handoff section 9) must show these run in some gate: the restart, NEW GAME after death,
  the exit refusal while dead, a full fx pool skipping a puff, a barrel chain, a gib, nukage, a refused pickup, the
  backpack (easy only) and berserk (easy / medium only).

### 6.4 v5 and B0

**The frozen set already covers P6.** The frozen model is "full" (`scenarios_v2.new_world`'s World defaults). Its
recorded totals (MEASURED from `combat_scenarios_v5.json`): pickups 17, barrel_blasts 4 (R0-imp-court 2,
R2-barrel-hall 2), player_blocked 120, kills 17, nukage 0, deaths 0, level_done 0, fx_skipped 6. Its drawn
populations already count drops and barrels by state (`pop_fields` `d_drop`, `d_barrel`; `census_picture` "rec: a +
c + d + e; b for projectiles and barrels").

**So the freeze rule binds the model work:**
- "full" must not change on any path v5 reaches.
- P6/P7's model edits are G2 (exit frame), the gate-facing helpers, and anything on the death / restart path, which
  v5 never reaches (deaths 0, restarts 0).
- After them, `scenarios_v2.py --validate` must show F1/F3/F4/F5 holding, and `--rehash "<reason>"` records the
  hashes.
- **If F3 or F4 moves: STOP. That is a behaviour change, a v6, and the owner's.**

**B0** (`b0_scenarios.py`):
- It keeps injecting the pose, doors, movers and P5's F2 (`p_hp` / `p_ar` / `p_at`) from the frozen model's pre-tic
  state. It injects NOTHING NEW.
- The binary's pickups, drops, barrels, blocking and inventory are its own, and are checked state- and pixel-exact
  against `BinaryMirror` -- which now steps the "full" player (`MonsterPhase.move`), not `step_sim`.
- Health and armor pickups are absorbed by F2's per-frame pin.
- A new per-run counter reports the frames whose loot cells differ from the frozen model's. It is recorded, not
  judged, as B0 already counts camera / door partings.
- A death in a B0 mirror still FAILS the run (e8d3683's rule): v5 has none.

---

## 7. Budget and size (ESTIMATES; their basis)

**Ops on v5 ((mean + p80) / 2), against blocked48's 16,037,431.**
- Unit costs: handoff section 5 (a jump on an index 68-102; a D4 lookup 47-100; a point location 5.9K from a cell
  start; a runtime sprite 30-54K end to end; a baked one ~15K) and `monstermove.things_leaf_lines`' per-slot shape.
- Frequencies: the frozen totals above. v5 moves on 87.5% of frames (handoff section 8).

| line | per frame |
|---|---|
| fixed tic | the barrel phase (22 stubs x ~70) ~1.5K; strength / bonus / `lvtime` / latch / restart test / palette ~0.5K. Total **~2K** |
| moving frames | pickups (a cell jump ~150, ~0.5 listed item at ~600, ~1.2 candidates) ~0.6K; `pb_mon` (~46 solid slots x ~150, ~1.1 candidates) ~7.5K; static blockers in the cells ~0.2K. Total **~7-9K** |
| nukage | 6-16K every 32 tics, and only in a nukage leaf: **~0.1K** |
| blasts | 4 in 1,100 frames x ~0.1-0.25M: **~0.5K** |
| drawing | barrel view dispatch ~0.1K per reached barrel; drops in view (+30-54K per drop per frame, after the run's dropper kills); taken pickups not drawn (-15K per vanished baked item in view, collect runs). Net **-10K .. +20K** |
| **P6 + P7, before placement** | **~0 .. +0.04M** |
| placement (the pins re-roll) | **+/- ~0.1M** -- P5 moved the walk's segment lines +/-55K with 19 of 20 bases moved |

**Declared: v5 +0.0 .. +0.15M -> 16.04 .. 16.19M**, under 22M with 5.8M headroom.

**gamespeed**: NOT comparable. The routes change (section 8.3), so the delta is recorded, not judged. The standing
target is 20M until P8 moves it to 22M.

**Size** (35.16% = ~47.19M words of 2^27; the ceiling is now **42%** = 56,371,445):
- The component count of section 4.6:
  - pickups ~40-55K words (stubs, gives, the grid);
  - barrels ~45-60K (7 view blocks x 22, phase stubs, `bl_leaf`, the LOS lists, the chain);
  - drops ~10K; gibs ~3K; palettes 9-12 ~3K (P5: 9 palettes ~7K);
  - player blocking ~15K; P7 ~3K; restart lines ~5K;

  ~130-200K words of code and tables.
- x P5's measured-over-probe ratio and its below-pool growth (P5: probe 1.05M -> measured 1.21M, most of it below
  the pool) gives **+0.2 .. +0.6M words, i.e. 35.3 .. 35.6%**.
- Redesign trigger: **> +1.5M words** (2.5x the upper estimate).

**Kill criteria** (for the ledger; any one -> the binary does not ship):
1. **Host**:
   - `test_player_modes`, `test_p67_model`, `test_restart_coverage`, `test_mobiles_oracle`, `test_barrel_tables`, the
     pickup grid's interval proof, and the gates' step-check;
   - `p67_identity.py`;
   - the restore-set tests, re-keyed.
2. **fj** (the real emitted text against the model, every mutant caught):
   - `test_pickup_fj`, `test_give_fj`, `test_player_block_fj`, `test_nukage_fj`, `test_barrel_fj` (phase, blast,
     chain, LOS), `test_drop_fj`, `test_fx_pool_fj` (puffs);
   - `test_monster_damage_fj` (barrel ids, blast mode, gib), `test_palette_fj` (bonus, berserk), `test_weapon_fj`
     (berserk, latch), `test_dead_guards_fj`, `test_restart_fj`;
   - run SOLO where heavy (P5: `test_monster_wake_fj` reached 3.2 GB).
3. **Gates**, byte- / state- / palette-exact:
   - m2_std, m3, p2a, m2_r4, hurt (H1-H6, S1), fight (F1-F10, S2), die (D1-D8), B0 v5;
   - their selftests rejected where they must be; every control parting; every event counter nonzero;
   - deaths 0 where declared;
   - deg_gate unchanged.
4. **CAP-22 and size**: v5 binding <= 22,000,000. profx-attributed P6 + P7 ops <= 0.125M on v5 (1.25 x the +0.1M
   phase budget) else REDESIGN. Size <= 42%. msframe recorded (D8: class F; ~90 ms a tripwire to explain).
5. **Housekeeping**:
   - pinreport 20/20 (the heat list re-keyed if a macro's arity moved);
   - the restore sets re-keyed;
   - `gamespeed_trail.py` re-recorded on the candidate (`BINARY_ENDS` / `BINARY_DOORS`; `--selftest` N6e passes);
   - `scenarios_v2.py --validate` PASS after `--rehash` (F1/F3/F4/F5 held).

---

## 8. Risks and unknowns

1. **Restart coverage (P7's real risk).**
   - The restart must return EVERY persisted cell of P1-P6 to the chosen skill's level start: doors, lifts, lists,
     rows, monsters (every `MONSTER_PERSIST` cell), hurt, pools, weapon, aim, loot, barrels, streams.
   - It must NOT touch the device shadows (`pal_cur`, `hud_s`).
   - A missed cell is a post-restart divergence that only D4's state check sees. `test_restart_coverage` is the net,
     and its controls must prove it can fail.
2. **The dead latch.** A nukage death mid-tic keeps the rest of the alive branch (P7-a). P5's live `p_dead` key skip
   is wrong once nukage exists. D6 + `latch` is its only gate.
3. **gamespeed changes route (MEASURED on the model).** gamespeed's 10 scripts were replayed on
   `World(player="full", monsters="full", sight_rule="los")`. That is an approximation: the binary uses the "seen"
   rule and the window aim.
   - Runs 0 and 2 are blocked by monster slot 23 (60 and 34 refusals, from tic 66 / 73). They end at (635, 303) and
     (615, 303), not `BINARY_ENDS` (831, 653) and (780, 427).
   - With `player_blocking=False` the model reproduces both `BINARY_ENDS` exactly.
   - No run dies or touches nukage; runs 4, 5, 6 and 8 pick up 1-2 items.

   So P6 must re-record `gamespeed.BINARY_ENDS` / `BINARY_DOORS` with `gamespeed_trail.py` (handoff section 11
   foresaw it). The binding number is no longer like-for-like with blocked48 (O3).
4. **The aim window on BAKED barrels.** No baked thing records today (`aimcode`; `project_thing`'s `aim` is 1 for
   runtime monsters only). Adding it to the baked path touches the shared baked projection or adds an instantiation.
   That is a placement and size risk; C probes both.
5. **The barrel blast's cost in a stress frame.** Per blast: 53 slots x ~200 ops + the player's LOS + 1-3 monster
   LOS (each tens of K: the P3.2c segment blocks) ~0.1-0.25M. A chain of 8 inside a 3-tic window, plus big BEXP
   sprites, puts ~+1-2M on a single frame (UNVERIFIED; S2 records it). Single frames are not capped (D1). S1 is
   already ~21.7M/frame averaged over 30 frames.
6. **The 22M cap.** blocked48's v5 binding is 16,037,431, so 5.96M of headroom against an estimate of +0.0-0.15M.
   The cap is not threatened by P6/P7. The threat is placement (+/- several 100K, pinreport).
7. **The freeze.** Any edit that moves "full" on a path v5 reaches is a v6 (the owner). The planned edits are all on
   paths v5 never reaches: exits, deaths, restarts. `--validate` decides.
8. **Gate fan-out.** Every gate that steps the player with `step_sim` must switch to the model's move (rule 5). A
   missed one shows a pickup or a block as a mismatch and costs a build. The static step-check test is the net.
9. **The counts-cache recount** (~34 min). Every `src/doomfj` / `src/fj` edit misses it. Keep sources LF (a CRLF
   copy recounts too).
10. **LOS bounds.** `monstersight._bounds` proves its products for NEAR 129. Blast traces reach Chebyshev 159
    (radius 30 + 128 + 1); re-prove them, or the 48-bit products may overflow silently.
11. **D3 a/b not taken** (O2): a recorded deviation, like P5's. Taking them later moves pictures (and census F4:
    v6).
12. **Model / binary drift on the exit frame (G2).** It is fixed in the model by this plan. Until then, no gate may
    compare `World.tic`'s exit frame.

---

## 9. The ledger declaration (draft, for `docs/gp-ledger.md`, BEFORE the build)

**P6 + P7 pickups, barrels, death and restart (class F) -- declared <date>, before the build.**

**What**: this file. ONE rung, `PLAYER_MODE = "full"`:
- P6-a..m and P7-a..e of section 1;
- the frame order of section 4.7;
- the cells of section 4.5.

**Budget**: section 7.
- v5 +0.0 .. +0.15M;
- gamespeed recorded, not judged (routes change);
- size +0.2 .. +0.6M words, redesign above +1.5M.

The phase budgets are P6 +0.1M and P7 ~0.

**Kill criteria**: section 7, 1-5.

---

## 10. Owner decisions

- **O1 -- the death view drop and the turn to the killer: OUT** (G1). The model omits both. The eye height is baked
  per leaf class, so a view drop needs runtime viewz classes. Recommend: record it as a D5 simplification.
- **O2 -- D3 a (drops before monsters) and D3 b (barrels exempt from the soft budgets): NOT taken.** This follows
  P5's recorded deviation for its mobiles. Taking them moves pictures in v5's frames, and census F4, so a v6.
- **O3 -- gamespeed is not like-for-like after P6.** A blocking player stops at a zombie on runs 0 and 2. Recommend:
  re-record the trails and report the number with that note. Re-planning the routes (a gen 4) would be a metric change.

**TAKEN (coordinator, 2026-10-05, under the owner's standing "be autonomous: take the recommended option, record it,
report it" -- reported to the owner the same morning):** O1 OUT (a D5 simplification: the dead view stays at eye
height, the weapon down, the red palette fades); O2 NOT taken (P5's deviation stands, v5's pictures do not move); O3
re-record the trails and report gamespeed with the route note. The rung is UNITED (section 2), the fallback "loot"
mode kept in reserve.

**O1 RE-OPENED BY THE OWNER (2026-10-05, relayed by the coordinator to package D).** The owner played blocked48 and at
0% "it doesn't die (no dead screen, no restart, it should do something close (but cheap) to what the original doom
does)". Package D evaluated the cheapest view drops against the coordinator's bar (<= ~0.3% of 2^27 in size, no
visible ops on normal frames, byte-exact with the oracle). Units: `docs/gp-lift-spike.md` section 2 (MEASURED on
blocked27: 8.0 words per band id, 44.0 per unique band body, 48 viewz classes + 5 for the lifts, 52,284 band ids
against the 4-nibble index's 65,536) and E1M1's 48 distinct floor heights (MEASURED from the WAD).

| option | what it costs | verdict |
|---|---|---|
| DOOM's drop, 41 -> 6 units at 1 a tic | 35 eye heights per floor: 35 x 48 viewz classes | out |
| ONE dead eye (floor + 6) per floor, exact | +48 viewz classes (none coincides with a live one: f + 6 = f' + 41 has no pair on E1M1). Band ids x2 (~+52K x 8 words = +0.42M), the band index past 65,536 -> 5 nibbles (pad +65,536 words, and one more `hex.xor` per `vpb_walk`: <= ~12.5K ops on EVERY frame), new band bodies (est. +5-9K x 44 = +0.2-0.4M). **~+0.7-0.9M words = 0.5-0.67%**, plus the every-frame ops | out (over both bars) |
| a few sinking steps | a multiple of the row above | out |
| geometry-only drop: walls and sprites at floor + 6 (`viewz` is runtime), planes still coloured from the live class's band lists | ~0 words; one `if p_dead` at the eye's landing (~20 ops a frame) | NOT exact by construction and not provable here: a floor between the dead and the live eye (a step of 8-34 units) lies on the other side of the horizon from the side its live band list was built for -- the "rows the emitter never asks for" hazard (`plane_bands.fj`). Needs an oracle `plane_viewz` split and a RENDER gate at dead eyes, i.e. a build. The cheapest drop if the owner wants one: a renderer rung, not a P7 line |
| a screen-level shift of the 84-row view | the device draws baked / computed rows: a device change (flipjump's ScreenIO, outside this repo) or an offset on every record (ops on every frame) | out |
| the turn to the killer (P_DeathThink's ANG5 a tic) | `viewangle` is runtime, so exact by construction; ~1-2K words, ~0 ops alive. But it needs the ATTACKER: a cell written at every damage source (P5's hitscan, melee and fireballs, C's blasts; nukage has none), and the model's `_death_think` gains the turn and the damagecount fade only once facing | cheap and DOOM's, but it touches three packages' damage paths: recommended as the follow-up rung |

**OUTCOME (package D): the FALLBACK** -- the weapon drops (P5), the red palette fades (P5), the view is frozen (P7-a/b/c,
package B's dead guards), and use restarts at the skill being played (P7-d, package D: `restartcode.tic_lines`). No
view drop is in this rung: every exact drop is over the size bar and costs ops on every frame, and the one cheap drop
is not provably byte-exact without a build. The turn to the killer is the recommended next step.

---

## 11. Owner requests: tempo x2 and monster visibility (package E, 2026-10-05)

**The owner, after playing blocked48:** "the enemies shooting and walking feels slow ... maybe run 2 ticks each time?";
"make sure monsters are almost always seen"; and (forwarded later the same day) "sometimes [the fireball] doesn't show
at all ... you must always show the fireballs" and "monsters get off-rendered when I move a little bit to some side
... a really small part of them is behind a corpse ... monsters should always be shown". Package E is (T) the tempo and
(V) the visibility. Branch `p67-e`; every number below says MEASURED (with its command) or ESTIMATE.

### 11.1 (T) THE TEMPO -- what runs twice, and in what order

ONE definition: `world.MONSTER_TICS_PER_FRAME = 2` (`World(monster_tics=...)` defaults to it; the emitter imports it).
`World._monster_world(ev)` is the monsters' world, run `monster_tics` times in a row; `World.tic` and the gates'
mirror `MonsterPhase.tic` both call it, so a gate cannot step a different count than the model.

| the frame (World.tic / the fj frame) | tics a frame |
|---|---|
| 0. the restart block; the frozen-level guard (`g_leveldone`) | once |
| 1. doors (the use press; monster presses `d_monreq` from LAST frame), 2. movers | once |
| 3. the PLAYER: nukage, weapon keys, use lines, psprites (the shot through the LAST picture's aim window, its noise flood), the `p_dc` / `p_bc` fades, berserk, the move with pickups and blocking | once |
| **4. THE MONSTERS' WORLD x2:** [the monsters from `sched_cursor` (A_Look, A_Chase, the attacks -- hitscan, claw, bite, the fireball's spawn -- and the damage they deal through `damage_player`), the fireballs (`_projectiles_phase`), the barrels (`_barrels_phase`, package C), the puffs and blood (`_fx_phase`)], then the same four again | **2** |
| 5. `leveltime` +1 (nukage's clock: the player's) | once |
| 6. the picture: the `seen` marks (`seen_hook`), the aim window, the palette | once |

Consequences, each by construction:
- **Seen marks.** Both monster tics read the marks of the picture the player last saw (fj: `thseen` is zeroed ONCE,
  after the loop; the model: `seen_hook` runs once, after `World.tic`). A monster that moved in the first tic keeps
  last picture's mark in the second -- the staleness every mark already had, now up to two tics.
- **Aim window and noise.** The player's shot resolves in step 3, before both tics, through last picture's window;
  its noise floods there, so the FIRST monster tic hears it. Unchanged.
- **RNG.** Every stream a monster tic, a fireball or an effect draws (`mon_rng[m]`, `rng_fx`, `rng_pl` for hits on
  the player, `rng_world` for barrels) draws twice as often per frame -- the same calls in the same order, two tics'
  worth. The player's own draws (P4's shot) stay once a frame.
- **Damage and death.** Damage from both tics accumulates into `p_health` / `p_dc`; the damage count fades once a
  frame (the player phase), so a hit's red flash lasts as many frames as before, and hits arrive twice as often. A
  player killed in tic 1 is a dead target in tic 2 (P5's rule: lost as a target, blocks nothing).
- **Doors and movers.** Both tics see the frame's doors and lifts. A monster's door press (`d_monreq`) or lift trigger
  in either tic lands on the next frame's door / mover phase (idempotent if set twice). P_ChangeSector runs once,
  before the loop (fj: `p32b_change_sector_lines` outside it; the model: `_door_phase_scene`).
- **K = 6 heavy actions is per DOOM tic**, so a frame can run 12. Each phase keeps its own `lvdone` guard.
- **G2 (package A's exit-frame fix)** wraps `_monster_world` and `leveltime` exactly as it wrapped the four phases.

**fj** (`wall_renderer.world_tic_lines`, ONE composer, no per-slot code duplicated): `[P_ChangeSector] wt_rep = 2;
wt_loop: [mt_tic .. mt_skip] [stl.fcall pj_phase] [(C: bar_phase)] [stl.fcall fx_phase]; wt_rep -= 1; if wt_rep: goto
wt_loop; [thseen = 0] [the bar]`. `wt_rep` is one nibble (`WT_DECLS`), set every frame and 0 at every frame's end (its
declared value: nothing for the M1 reset to restore). At tempo 1 the composer returns blocked48's text unchanged. It
takes the pools' fcalls as every `stl.fcall` line before `hex.if1 1, lvdone, p5_bar_skip`, so package C's
`stl.fcall bar_phase, bar_pret` inserted among them lands inside the loop with no edit here.

### 11.2 (V) VISIBILITY -- what the budgets did, the ROOT CAUSES, and the actors rule

**The sprite budgets as blocked48 has them (every tier):** `THING_BUDGET` / `MONSTER_BUDGET` 255 (never bind on
E1M1: hard backstops, KEPT); the soft raise `DEG_SOFT_SCENERY` 3 -> 24 rows and `DEG_SOFT_MON` 4 -> 10 rows; the base
bounds `MIN_SPRITE_H` 3 (scenery) and `MIN_SPRITE_H_MONSTER` 1; two write-once fragment slots per column, slot A
first come, slot B only for a sprite at least `DEG_SPRB_MINH` 32 rows tall (the B-gate). P5's mobiles were SCENERY at
`MIN_SPRITE_H`, exempt from the soft raise only.

**The causes, reproduced in the ORACLE** (blocked48 draws the same pixels; `scratchpad/gp/p67e_visibility_probe.py`
attributes every fragment slot to the thing that wrote it):
1. **THE CORPSE (the owner's "a small part behind a corpse") -- ROOT CAUSE: a sprite with no row inside the view
   still records fragments.** v5 R0-aftermath frame 57: the player stands on a corpse (tz 4 units). Its sprite is
   under the view (its feet-planted rows all below row 84) yet spans every column, so it took slot A everywhere; every
   monster behind it then needed slot B and was B-gated (a sergeant at 438 units, an imp at 1016, both under 32 rows):
   they vanished WHOLE while in view and in a fight. Moving sideways changes the columns the corpse spans -- "when I
   move a little bit to some side". In DOOM no sprite removes another; here an invisible one did.
2. **THE FIREBALL -- the scenery base bound, and the B-gate.** A fireball (BAL1, ~15 px of art) farther than ~400
   units projects under `MIN_SPRITE_H` = 3 rows: not drawn at all until it comes near; its explosion frames are
   bigger, so "only the explosion is shown". MEASURED (`tests/host/test_actors_rule.py`): a fireball 500 units up the
   open courtyard from v5's R0-courtyard pose draws 0 px under blocked48's rule, and draws under the new one. A
   fireball in front of the imp that fired it also B-gates the imp out of those columns (the corpse's mechanism).
3. **THE CROWD (the owner's "too much") -- the soft raise:** after 4 accepted monsters a monster needs 10 rows (~450
   units on this 84-row view), so far monsters drop out exactly on the busy frames.

**THE ACTORS RULE** (`render_wall_frame(exempt_actors=True)`, set in `GAME_RENDER_KW` only; `HOSTED_RENDER_KW` and
deg_gate's keyword set keep blocked48's picture). An ACTOR is a monster (live or corpse) or a mobile:
- (1) no soft raise for monsters: their soft count is the hard `MONSTER_BUDGET` (the hard budget stays the backstop);
- (2) a mobile is an actor: the monster class (counted in `n_mon`) at the monster base bound
  (`monstercode.mobile_view_rows`: `sp_mon` 1, both depth bounds at `MIN_SPRITE_H_MONSTER`);
- (3) no B-gate for an actor: it takes slot B behind a nearer sprite at any height;
- (4) EVERY thing: a sprite whose drawn bucket `[ytop_b, ytop_b + hb)` has no row in `[0, VIEW_H)` records nothing
  (pixel-neutral for itself; still counted; a thing with a seen flag still goes through the seen probe, because the
  oracle's seen test has no vertical part).
The scenery keeps the soft raise and the B-gate. The two fragment slots stay (a structural limit, below).

**fj, with no macro arity change:** the game tier passes `dsoftm = monbudget` (= `MONSTER_BUDGET`, from
`GAME_RENDER_KW["exempt_actors"]`) to `frame.thing_record_body`, and inside it the ONE equality `dsoftm==monbudget`
gates (4) (six rep-lines after the bucket's `trb_y0`, then `.rec_goto seen_probe` or `ret`) and (3) (`hex.if0 2,
sp_mon, bslot_gate`, else `.rec_goto bslot_done`). Every other tier binds `dsoftm = DEG_SOFT_MON` (4 != 255), so the
lines expand to nothing and its ops are unchanged (deg_gate). New @-locals only: `bslot_gate, offv_top, offv_out,
offv_ok`.

**MEASURED visibility on v5's frames** (`PYTHONPATH="src;." python scratchpad/gp/p67e_visibility_probe.py --every 2
[--tempo 2]`, logs `scratchpad/gp/scenarios/p67e_vis_tempo1.log` / `_tempo2.log`: every 2nd frame of the 11 runs, 550 frames; "should show" = a live monster with an open column at its
base size AND a row inside the view):

| | tempo 1 (v5 as recorded) | tempo 2 (v5's keys replayed at x2) |
|---|---|---|
| live monster-frames that should show | 1,249 | 1,083 |
| MISSING under blocked48's rule | 390 on 172 of 550 frames (soft raise 187, slots 203) | 327 on 164 frames (151 / 176) |
| MISSING under the actors rule | **109 on 71 frames**: both slots taken 57; a 1-2 px speck whose sampled bank column is empty 52 | **63 on 53 frames** (both slots 23, specks 40) |
| mobiles drawn with a row in the view (of all alive, in view or not) | 101 of 360 -> **167** | 71 of 269 -> **106** |
| things recorded past every reject | +2.04 / frame | +1.71 / frame |
| fragment columns recorded | **-6.9 / frame** (off-view sprites stop holding columns) | **-10.6 / frame** |

What is left: (a) far specks (1-2 columns at ~2000 units, the low-res bank's sampled column empty) and (b) three sprites
over the same columns (two slots). (b) is the next lever if the owner still sees it -- a third slot, or a per-column
"no visible row in THIS column" test in the record loop (~0.3K ops per sprite column); not done here.

### 11.3 Cost (ops/frame) and size

**(T), the second monster-world tic.** MEASURED on blocked48 (profx `games_blocked48.marks.bin`, the run in
`docs/ship-evidence/blocked48_profx_games.log`): the span from marker 18 (`dsc_done`) to marker 19
(`e1m1_bspcode_walk`) over the 1,000 game frames (`phases.frames()`) -- it holds P_ChangeSector, the monster tic,
`pj_phase`, `fx_phase`, the bar, the aim prologue and the palette: **mean 166,290, median 153,807, p80 247,923, p95
416,172, p99 729,977, max 1,142,154, min 18,114 ops/frame.** The second tic repeats all of it but P_ChangeSector, the
bar, the aim prologue and the palette (a few K). ESTIMATE: **+0.15M on the mean frame, +0.25M on the p80 frame, up to
+1.1M on the worst frame** of gamespeed's games. v5's fights are denser, and twice-as-fast monsters fire more
fireballs (P5's UNVERIFIED ~0.1-0.15M per flying fireball per tic): **v5/v6 binding +0.15 .. +0.4M**. Against the
cap: blocked48's v5 binding 16,037,431 + P6/P7's +0.0-0.15M + (T) -> **~16.2 .. 16.6M, under 22M with >= 5.4M of
headroom.** The stress case S1 (21.7M/frame over 30 frames, 8 fireballs in flight) gets the second tic of 8 fireballs:
**~+0.8 .. +1.2M -> ~22.5 .. 23M on S1's average** (a scenario: CAP-22 binds v5's (mean + p80)/2, D1). v5's
single-frame maximum, 26.2M (+/- 2^18), may rise by up to the measured 1.14M span.

**(V), the actors rule.** Its record test costs ~0.7K ops per recorded thing (a `hex.scmp 8` ~250; set, mov, add, dec,
sign 8) and ~40 for the actor test: ~10-15K/frame at ~15 recorded things. Against that, the probe's deltas: +2.04
things recorded (~5-10K each past the projection every thing already pays) and -6.9 fragment columns (each a record
slot and its stream emit, ~10-20K: `an_fam.txt`'s ~30K sprite column on blocked27 x the v2 column's ~0.6). ESTIMATE
**-0.15 .. +0.05M on v5**: the off-view test frees more work than the newly drawn actors cost. UNVERIFIED until B0.

**Size.** (V): the transplanted section assembled with the game binding vs another tier's: **+7,296 words per
`thing_record_body` instantiation** (MEASURED: `tests/fj/test_actor_record_fj.py`'s program with one call, 19,170 ->
26,466 words); the game tier instantiates it twice (`thing_leaf`, `thing_leaf_b`): **~+14.6K words**. The mobile rows
change values, not size. (T): the loop is six lines and one nibble, **< 0.1K words**. Total **~+15K words, +0.011% of
2^27** (35.16% -> ~35.17% before P6/P7's own). Placement can move ops either way (the pins re-roll: pinreport).

### 11.4 The frozen set: v6

v5's replays MOVE under (T) and its drawn populations under (V) (the census picture is `GAME_RENDER_KW`), so F3 and
F4 fail: a behaviour change, a **v6**, the owner's freeze.
- **How v6 is made** (`scratchpad/gp/p67e_v6_record.py`, oracle-only, never freezes): v5's 11 runs -- names, setups,
  checkpoints and KEYS byte for byte (the keys hash `794fa332d21c447e` is asserted unchanged) -- with `monster_tics:
  2` and v5's sight rule "seen", replayed with the census; the poses, final digests, totals, drawn populations and the
  CAP-22 criteria are recorded; status PLANNED, no B0, no approval. Its result: section 11.6.
- **A set file names its tempo.** `scenarios_v2.use_sight_rule(doc)` also applies `doc["monster_tics"]` (absent = 1:
  v1-v5 were recorded at one tic a frame) to every world it makes (`apply_sight_rule`), so `--validate`, B0's model
  replay and the census replay each set under its own model; `--plan` records the game's tempo in a new set. (The
  grown-schema witness `state_dump.py` calls `new_world()` without `use_sight_rule`: v5's tempo 1 is its default, and
  it already ran v5 at the "los" rule -- a pre-existing gap, noted, not changed.)
- **B0 injects nothing new.** It replays the set's model (v6: tempo 2) for the pre-tic pose, doors, movers and P5's
  health / armor pin; the BINARY's monsters are its own, mirrored by `MonsterPhase` at `MONSTER_TICS_PER_FRAME` (the
  binary's tempo). B0 on v5 still runs on a tempo-2 binary (v5 replays at 1, the binary's monsters run at 2); only the
  injected health is the slower model's, so a mirror death there is possible.
- **The freeze's catch:** `scenarios_v2.py --freeze` RE-PLANS and requires identical keys; v6's keys are v5's by
  decision, not re-planned at tempo 2. The first freeze of v6 needs the owner AND a freeze path that accepts inherited
  keys (or a re-plan, which is a different set) -- the coordinator's call.
- **gamespeed**'s routes move too (monsters arrive sooner): its trails are package A's re-record (O3) anyway.

### 11.5 Files the integrator merges (overlaps with A and C)

- `src/doomfj/world.py`: `World.tic` (A's G2 wraps `_monster_world`).
- `src/doomfj/monsters.py`: `MonsterPhase.tic` (A adds the player half).
- `src/doomfj/wall_renderer.py`: `world_tic_lines` and its splice (C edits `p5_tic_lines`, which the composer reads
  unchanged); the `_DSOFTM` binding beside `_thing_leaf_body`; `_p5_model_asserts`' mobile row class.
- `src/doomfj/reference_model.py`: `exempt_actors` and the `act` lines in the thing loop (C adds the barrels to the aim
  window and a `z` to `mobiles` there).
- `src/fj/frame_render.fj`: `thing_record_body`'s two blocks (C's baked-barrel aim option (i) touches the same macro's
  projection).
- `src/doomfj/monstercode.py`: `mobile_view_rows` -- C's puffs join the pool states and become actors with no edit.
  **Drops and barrel explosions are C's call**: drops look like pickups, so scenery is the D3-consistent choice;
  barrels stay baked scenery (O2).
- `scratchpad/gp/scenarios_v2.py` (`use_sight_rule`, `apply_sight_rule`, `--plan`; A edits `BinaryMirror`) and
  `scratchpad/gp/census_lib.py` (the key-set copy check).
- Tests that script single DOOM tics now pin `monster_tics=1`: `test_gp_combat`, `test_gp_restart`,
  `test_gp_scheduler`, `test_gp_strafe`, `test_player_modes`, `test_p5_hurt_model`, and tests/fj `test_monster_tic_fj`,
  `test_player_shot_fj`, `test_weapon_fj`. The tempo itself is `tests/host/test_monster_tempo.py` and
  `tests/fj/test_monster_tempo_fj.py`; the actors rule `tests/host/test_actors_rule.py` and
  `tests/fj/test_actor_record_fj.py` (and `test_sprite_bank_fj`'s record harness binds the non-game tier).

### 11.6 v6, as recorded (oracle only; NOT frozen)

**v6 with v5's scripts** (`PYTHONPATH="src;." python scratchpad/gp/p67e_v6_record.py` -> `combat_scenarios_v6.json`,
keys `794fa332d21c447e` = v5's, `--check` OK; log `scratchpad/gp/scenarios/v6_record.log`, 373 s): **the criteria
FAIL.** v5's keys were planned against tempo-1 monsters, and at tempo 2 the fixed keys aim and dodge where the monsters
no longer are:
- every run survives -- **FAIL**: R0-imp-court and R2-east-yard die (v5: 0 deaths);
- >= 8 kills -- **FAIL**: 3 monsters (v5: 17 kills in the totals);
- every run moves on >= 60% of its movement frames -- **FAIL**: R2-east-yard 39% (the dead player);
- B0's camera reconstruction -- **FAIL**: 56 frames part (the dead runs' frames);
- the rest PASS. Poses part from v5 at frames 12-98 (3 runs never: the player's path is the same, only the world
  differs). Player hurt 43 times (v5: 10).
So a v6 that keeps v5's SCRIPTS is not a valid combat set: B0 would fail it (a mirror death fails a run, e8d3683).

**The alternative, measured: v6 RE-PLANNED** (`scenarios_v2.py --plan --sight seen --file
scratchpad/gp/scenarios/combat_scenarios_v6_replan.json` -- the same 11 CHECKPOINTS, the autopilot playing the
tempo-2 model; keys `05744a5d5167bd84`; log `v6_replan.log`, 938 s): every criterion PASSES but one -- **>= 8 kills:
6** (and 2 barrels) -- with 0 deaths, the lowest end health 40, 69.2% of frames with an awake monster DRAWN, all
three attack kinds (hitscan 59, melee 2, fireball 15), 20 pickups, 3 player doors, 50 of 52 fireball-threat frames
dodged, B0's camera 0 frames apart. The faster monsters make the aggressive autopilot kill less inside 100 frames.

**Recommendation (the coordinator's / owner's call):** freeze the RE-PLANNED v6, after either relaxing ">= 8 kills"
to >= 6 for tempo 2 or tuning the autopilot's engage range; it keeps v5's checkpoints, and its keys are the autopilot's
answer to the new tempo, which is what the set was always meant to be (a player, not a replay). B0 measures the
binding on the built binary (`b0_scenarios.py --file <v6>`); there is no oracle op model for a whole frame, so no
oracle binding estimate exists -- section 11.3's +0.15 .. +0.4M (T) and -0.15 .. +0.05M (V) on top of blocked48's v5
16,037,431 is the estimate until then.

---

## 12. Owner requests: aim at range, turn, fire rate, help spacing (package F, 2026-10-05)

The owner played blocked48 on 2026-10-05 and asked for four things. They are on branch `p67-f`, off `m7-p67` b866606.

### 12.1 "It's kind of hard to kill from afar, maybe too hard" -- MEASURED: the window matches DOOM; the TURN does not

`scratchpad/gp/aim_range.py` measures the chance that one shot hits one monster at distance D. Its results are in
`scratchpad/gp/aim_range.txt`, and `--selftest` is its R9 control. The target stands in the open, with no walls and
no heights. DOOM's autoaim is vertical only, so it changes nothing here.
- **Ours** is the model's own `CombatMixin.aim_geometric`, called per column on a one-target world. This is the
  window's box formula; the window agrees with it on 99.94% of fight frames (`gp-aim-window.md`).
  - The pistol's accurate shot is tested at column 80.
  - A refire bullet or a pellet is tested at the column `Sites.gunshot` names, over all 256 stream states.
  - A shotgun blast is 7 pellets from each start state.
- **DOOM** is the 2D trace at view + (P_SubRandom() << 18), with the SAME draws. It tests PIT_AddThingIntercepts'
  diagonal (chosen by the sign of dx ^ dy), and the crossing must lie within 2048 along the ray.
- **The residual.** The player turns in whole steps, and the target's bearing is uniform against that lattice. So the
  residual between the bearing and the nearest reachable view angle is uniform over ONE TURN STEP.
  - The measure uses 32 bearings round the circle and a grid of 4 x 2^16 BAM.
  - The player aims by the PICTURE, so each rule is centred on its own accurate-shot interval (see 12.1.3).

Monsters: r 20 is the zombieman, the imp and the sergeant; r 30 is the demon. All numbers are MEASURED (32 views,
grid 4).

**12.1.1 The rule alone, at the same step (640 << 16 = 3.516 deg)** -- P(hit), ours / DOOM:

| r | D | angular width | pistol 1st shot | refire bullet | shotgun P(>= 1 pellet) | pellets of 7 |
|---|---|---|---|---|---|---|
| 20 | 512 | 4.47 deg | 1.000 / 1.000 | 0.733 / 0.742 | 1.000 / 1.000 | 5.13 / 5.20 |
| 20 | 768 | 2.98 deg | 0.984 / 0.981 | 0.551 / 0.543 | 0.996 / 0.997 | 3.86 / 3.80 |
| 20 | 1024 | 2.24 deg | 0.816 / 0.806 | 0.430 / 0.420 | 0.983 / 0.986 | 3.01 / 2.94 |
| 20 | 1536 | 1.49 deg | 0.544 / 0.539 | 0.295 / 0.289 | 0.919 / 0.928 | 2.06 / 2.02 |
| 20 | 1920 | 1.19 deg | 0.428 / 0.432 | 0.236 / 0.234 | 0.851 / 0.869 | 1.65 / 1.64 |
| 30 | 1024 | 3.36 deg | 1.000 / 1.000 | 0.605 / 0.598 | 0.998 / 0.998 | 4.23 / 4.18 |
| 30 | 1536 | 2.24 deg | 0.813 / 0.806 | 0.430 / 0.420 | 0.983 / 0.986 | 3.01 / 2.94 |
| 30 | 1920 | 1.79 deg | 0.644 / 0.647 | 0.349 / 0.343 | 0.956 / 0.961 | 2.44 / 2.40 |

At 128 and 256 units every cell is 1.000, except the r-20 refire bullet at 256 (0.972 / 0.981).

**The 17-column window is NOT harder than DOOM at range.** Every cell is within 0.02 of DOOM's.
- The largest gap is the shotgun's P(>= 1) at 1920: 0.851 / 0.869. Pellets that land in one column share one answer,
  so a blast's 7 pellets are slightly more correlated than DOOM's 7 rays.
- A far box being only 1-2 columns wide costs nothing. The box's edges move continuously with the view angle:
  `x1 = (cx + P - Q) >> 16` is an exact containment test of screen position c + 1.
- r_eff (`gp-aim-window.md` 1.7) is DOOM's diagonal width.

**So, per the brief: no window change.**

**12.1.2 With the turn.** The table gives the pistol's accurate shot and the shotgun's P(>= 1) for four step sizes:
- ours at 640, the shipped step;
- ours at 960, the owner's x1.5 (12.2);
- ours at 320, the proposed slow first frame (below);
- DOOM's keyboard TAP: the slow turn, 320 << 16 = 1.758 deg.

| r | D | pistol: ours 640 | ours 960 | ours 320 | DOOM tap | shotgun: ours 640 | ours 960 | ours 320 | DOOM tap |
|---|---|---|---|---|---|---|---|---|---|
| 20 | 512 | 1.000 | 0.946 | 1.000 | 1.000 | 1.000 | 0.997 | 1.000 | 1.000 |
| 20 | 768 | 0.984 | 0.723 | 1.000 | 1.000 | 0.996 | 0.985 | 1.000 | 1.000 |
| 20 | 1024 | 0.816 | 0.544 | 1.000 | 1.000 | 0.983 | 0.962 | 0.993 | 0.994 |
| 20 | 1536 | 0.544 | 0.363 | 0.981 | 0.981 | 0.919 | 0.875 | 0.934 | 0.941 |
| 20 | 1920 | 0.428 | 0.285 | 0.856 | 0.861 | 0.851 | 0.807 | 0.852 | 0.878 |
| 30 | 1024 | 1.000 | 0.810 | 1.000 | 1.000 | 0.998 | 0.990 | 1.000 | 1.000 |
| 30 | 1536 | 0.813 | 0.542 | 1.000 | 1.000 | 0.983 | 0.962 | 0.993 | 0.994 |
| 30 | 1920 | 0.644 | 0.429 | 1.000 | 1.000 | 0.956 | 0.926 | 0.972 | 0.974 |

**This is the owner's "hard from afar".**
- A frame is one tic (D4), and one frame of a held arrow is the smallest turn: 640 << 16. That is TWICE DOOM's tap.
- DOOM turns at angleturn[2] = 320 << 16 for the first SLOWTURNTICS = 6 tics a key is held, then at 640 (1280
  running).
- Past ~768 units a zombieman is narrower than one of our turn steps. The first pistol shot then hits a uniformly
  placed target 0.43-0.82 of the time, where DOOM's tap gives 0.86-1.00.
- **The owner's x1.5 turn (12.2) makes this worse**: 0.29-0.54.
- The shotgun hides most of it, because its spread covers the step.

Strafing is a fine control the game already has. A 13-unit side step moves a target at distance D by 13 / D rad:
0.73 deg at 1024, 0.39 deg at 1920. That is finer than DOOM's tap, so a player who strafes to line up loses nothing.

**PROPOSED, NOT BUILT -- DOOM's own rule, one frame long.**
- **The rule**: the FIRST frame a turn key is held turns 320 << 16; every later frame of the hold turns ANGLE_TURN
  (960).
- **What it gives**: the "ours 320" columns above. That is DOOM's tap odds exactly, since the rule is DOOM's. A held
  turn keeps the owner's x1.5 after its first frame.
- **What it costs**:
  - one persisted nibble `p_tnh` (a turn key was held last frame);
  - ~8 fj lines in `wall_renderer._player_sim_lines(strafe=True)`;
  - in the model, a `p_turnheld` schema field read in `combat._player_move`;
  - every gate that steps the game tier's player through `rm.step_sim(strafe=True)` must carry it.
- **Who must do it**: the gate side is package A's switch to `MonsterPhase.move` (World._player_move). After that
  switch, the model side is one field in one function. The change also moves v5/v6 and the restart set (package D).
- **Why not here**: it would be a third concurrent edit of the gates' player step. The coordinator must decide.

**12.1.3 The window's 1-column bias (MEASURED, harmless).**
- Our accurate shot's hit interval is centred 0.73-0.78 deg (~1.06 columns) LEFT of the true bearing.
- The cause: column c is tested at screen position c + 1 (R_ProjectSprite's `x2 = (... >> 16) - 1` convention),
  while the view's centre ray is at position 80.0.
- The DRAWN sprite follows the same convention. A player who centres the picture is therefore centred on the hit
  interval, and never sees the bias.
- Centred on the true bearing instead, the pistol at 640 would read 0.688 / 0.804 (r 20, 1024).
- DOOM has the same convention at 320 wide, at half the angle. 12.1.1 centres DOOM on the true bearing, which flatters
  DOOM slightly.

### 12.2 "Turning feels a bit slow during a fight, might need to x1.5 it" -- DONE

`reference_model.ANGLE_TURN` goes from 640 << 16 to **960 << 16** (5.27 deg a frame).
- It is the ONE definition. The model's `step_sim` and `combat._player_move` read it, and so does the fj's
  `wall_renderer._player_sim_lines` (`hex.add_constant 8, viewangle, ...`). Every tier turns at the new rate.
- The model has no slow turn and no run turn (DOOM's angleturn is {640, 1280, 320}). It has one rate, now x1.5. 12.1.2
  shows what that costs at range, and proposes the slow first frame.
- The reachable angles are now multiples of 2^22 BAM, 1024 a circle (they were multiples of 2^23).

### 12.3 "My firing speed is slow ... fire at x2 speed" -- DONE

The player's WEAPON runs **`world.WEAPON_TICS = 2`** DOOM tics a frame:
- P_MovePsprites runs twice: the weapon state machine, the flash, A_ReFire, the raise and the lower.
- The number keys run once, before it; the bar runs once, after it.
- This deviates from D4 (one DOOM tic per frame) for the weapon alone. Package E builds the monsters' tempo the same
  way, and the two constants should sit side by side in `world.py` (merge note, 12.6).

**The model**: `combat.CombatMixin._weapon_tics` loops `_move_psprites` WEAPON_TICS times. Three places call it:
`_player_phase`, `_death_think`, and both branches of the gates' `monsters.MonsterPhase.weapon`. Nothing else calls
`_move_psprites`.

**The fj**: `weaponcode.weapon_lines(tics=)` (default WEAPON_TICS) loops its ONE P_MovePsprites block. No code is
duplicated.
- The loop runs on a scratch nibble `wp_pass`: `wp_ptic:` ... `wp_ploop:` inc,
  `hex.if_flags wp_pass, 1<<tics, wp_ptic, wp_pdone`, then `wp_pdone:` zeroes it.
- At `tics=1` the text is P5's to the byte.
- `wp_pass` is declared in `weapon_decls`. It is 0 at the end of every frame (the harness prints it), so the
  restore-set re-key may either persist it or restore it.

**The effect**: every weapon cycle takes half the frames.
- Fire held, the pistol refires every 14 tics, the shotgun every 37, the fist every 17 and the saw every 8. These now
  take 7, 18.5, 8.5 and 4 frames.
- A weapon switch (16 tics down, 16 up) is also halved.

**Ops (MEASURED in the tests/fj harness by `scratchpad/gp/weapon_tics_cost.py`; NOT in game):**
- The second pass costs +403 ops/frame idle and +274 when firing; the harness's whole loop is 1.7-2.2K a frame.
  So the second pass is ~0.3-0.4K a frame.
- On top of that, the shots themselves double while the trigger is held. P4's read side costs ~0.1-0.15K a pistol
  shot and ~1.9K a blast, plus `dm_go` per hit.
- Estimate on v5: well under +0.01M/frame before placement. Placement (new labels and a new cell) re-rolls the pins,
  as any change does.

**Proof**: `tests/fj/test_weapon_fj.py` runs the real emitted text against `World`, tic by tic.
- It covers 600 frames with both inventories.
- It runs the P5 hurt scripts: kill, ready, refire and deadkeys. The "dead before A_Lower reaches the bottom" poke now
  comes at 9 // WEAPON_TICS frames.
- New: `test_the_weapon_runs_the_model_s_tics_per_frame`, plus R9 tempo mutants. The block run once a frame (tics=1,
  the P5 text) is caught at frame 0; run three times, it is also caught at frame 0.
- The eight P4/P5 mutants are still caught.

### 12.4 "Use a bit more space between different categories" (the HELP screen) -- DONE

`menu.py` changes four spacings:
- the items of a row sit further apart, and each description nearer its own caps: `HELP_ITEM_GAP` 8 -> 12 and
  `HELP_DESC_GAP` 6 -> 4, giving "[CTRL] FIRE    [1][2][3][4] WEAPONS";
- the key rows are 2 px apart instead of 1 (`HELP_ROW_PITCH` = cap + 2);
- that is paid for by the use description's second line, now at the legend's pitch (`HELP_LINE_PITCH` = glyph + 1);
- the cluster legend is level with the caps' top.

Nothing else fits: the screen is 100 rows, and the last row's HELP now ends 1 px above the credit.
- Renders: `docs/gp-p67/help_before.png` and `docs/gp-p67/help_after.png`, made by `scratchpad/gp/help_shot.py`.
- `tests/host/test_menu.py` re-pins every cap and string. Its R9 control now also rejects each of the four old
  spacings.
- `tests/fj/test_menu_screens.py` and `test_keyboard_input.py` pass unchanged, because the fj screens come from the
  same `help_pixels`.
- The help stream's size changes, so `probe.RECORDED_CALIBRATION` and the size are re-recorded on the build, as in
  P3.4.

### 12.5 What moves v5

- **12.2 (the turn) and 12.3 (the weapon's tempo) MOVE v5.** Both are behaviour changes the owner asked for, and
  package E's v6 carries them. Nothing was re-frozen here. MEASURED (`scenarios_v2.py --validate --no-census` on this
  branch):
  - F3 is stale on all 11 runs;
  - the criteria FAIL ">= 8 kills": **1 kill**, down from the frozen 17. With the weapon's tempo alone (the turn put
    back to 640) it is 5 kills, also stale on all 11 runs. v5's recorded keys were aimed with 640-BAM turns and
    timed to one weapon tic a frame, so they now point past their targets and fire at other moments. **A v6 must
    RE-PLAN the routes' aiming and firing, not only re-record the same keys.**
  - B0's camera check parts on 2 frames;
  - every other criterion holds: no deaths, 9 pickups, 3 doors, the three attack kinds, the dodges.
- 12.4 (the help) moves no world frame. It changes only the help picture (class F, as in P3.4).
- 12.1 changes nothing.

**The host tests (MEASURED, `pytest tests/host`: 15 failed before the fixes below; each failure attributed by running
it with one change reverted):**
- **Fixed on this branch** (model unit tests whose scripts or timings the change moved):
  - `test_gp_weapons` -- five DOOM-tic timing tests and the noise test. They now run at one weapon tic a frame (an
    autouse fixture: they pin DOOM's tics). The new `test_the_game_runs_the_weapon_at_x2` pins the shipped tempo: the
    pistol's shots in frames 9, 16, 23, 30, a switch in 15 frames, with the DOOM tempo as its control.
  - `test_gp_restart` -- the weapon tempo: at x2 the imp died before it clawed, so `mon_melee` was 0 and the
    claw-table control moved nothing. The imp now stands at (60, 60), and the player wears blue armor.
  - `test_player_modes` (hit / shoot noise) -- the turn: seed 3's walk woke no monster by sound. The seed is now 8
    (7 sound wakes, 63 noises; "shoot" parts at tic 172).
  - `test_reference_model.test_step_turn_left` -- the pinned angle, 0x43C00000.
- **Left failing, for package E's v6 / package A's trail re-record** (they replay v5 or a recorded trail; nothing
  was re-frozen here):
  - `test_aim_window_oracle::test_window_agrees_with_geometric_aim_on_the_slice` (both changes);
  - `test_b0_scenarios_frames` (2 tests; the turn: "the model no longer reproduces the set's pose");
  - `test_depth_order::test_depth_order_changes_the_overlap` (the turn: v5's R0-aftermath frame 96 moved);
  - `test_gamespeed_validate::test_validate_replays_the_door_run_0_opens` (the turn: run 0 now ends at (671, 318),
    not `BINARY_ENDS` (831, 653)).

### 12.6 Merge notes for the integrator

- **`world.py`**: `WEAPON_TICS` sits above `FIREBALL_POOL`. E's monster tempo constant belongs beside it.
- **`combat.py`**: `_player_phase` and `_death_think` now call `_weapon_tics`. A and B edit both functions (the dead
  latch, the restart); keep the call. `monsters.MonsterPhase.weapon` calls it too, and A adds the restart request and
  the latch there.
- **`weaponcode.py`**: `weapon_lines` gains `tics=`. When it loops, the flash section's three exits go to `wp_ploop`.
  - B's weaponcode edits (berserk's x10, key 1's rule, the `p_dd0` latch on the key skip) touch the keys and the
    actions, not the loop.
  - The latch must sit BEFORE `wp_ptic:`, in the keys section, which runs once a frame.
- **Gates and trails**: every gate that hard-codes a turn count and every recorded trail (`gamespeed.BINARY_ENDS`)
  moves with 12.2. A/E re-record them together with O3's re-record. (`m2_std_gate`'s steering reads ANGLE_TURN
  symbolically, so it adapts.)

---

## Package A as built (agent A, 2026-10-05; branch `p67-a`)

The names packages B / C / D and the integrator read. Everything below is Python; no fj emitter was touched.

**Model** (`world.py`, `combat.py`): G2 -- `World.tic` skips the monsters, projectiles, barrels, fx and `leveltime`
on the tic whose player phase pressed the exit. The ONE-rule helpers `world.player_loots(mode)` and
`world.player_mortal(mode)` exist ("full" alone; the fallback's "loot" would join `player_loots`); the model's own code
does not read them -- the gates and `MonsterPhase` do. `combat.window_aim` maps sid > nmon to `("bar", sid - 1 - nmon)`.
`doors.DoorPhase.tic(player=False)`: a dead player holds no closing door. The dead latch needed no model change:
`combat._player_phase` already chooses its branch once.

**`monsters.MonsterPhase`** (the gates' oracle): `dead_latch()` (the tic-start `p_dead`), `restart_due()`,
`restart()` (the model's `_restart`), `nukage(x, y, a, dead=)`, `weapon(keys, x, y, a, dead=)` (dead in "full": the
model's `_death_think` -- psprites, the damage fade, a HELD use sets `g_restart`; alive: keys, psprites, then
`p_str` +1, `p_dc` -1, `p_bc` -1), `move(keys, x, y, a, dead=, scene=)` (the model's `_player_move` on `sync`'s scene;
the world's own walk-over cells are put back -- the gates' DoorPhase / MoverPhase own the walk-overs; before "full"
it is step_sim with `self.touch`), `card()` / `set_card()`, `taken()`, `barrel_lumps()`; `tic()` advances
`leveltime`. `state()` adds, in "full": `loot_state()` (= `monsters.loot_cells(world)`), `barrel_state()`,
`game_state()` -- their units are 4.5's (docstrings). `mobiles()` appends the lying drops `(x, y, lump, 0)` in
dropper order (`monsters.droppers(world)`, `drop_lump`).

**`monsters.MonsterViews`**: `aim_things` adds the live barrels `(1 + nmon + b, 10)`; `rt_state` adds the 25 drop
rows (row `nt + 10 + k` = the corpse's whole-unit row and `mon_leaf` while `mdrop[k] == 1`, else 0) AND the `thvis`
cell (`vis_state`); `nrows` counts them; `hidden()` (render's `thing_removed`), `barrel_views()`.
**THE thvis LAYOUT (B and D must match):** the baked vanishable slots in `things.vanishable_slots` order (105 on
E1M1: 85 pickups, 20 barrels; a pickup is `1 - pickup_taken`, a baked barrel `bar_state != 0`), THEN one slot per
RUNTIME pickup (10) in runtime-thing order (`MonsterViews.rt_pickups`) -- 115 slots, 2 nibbles each.

**The oracle** (`reference_model.render_wall_frame`), opt-in: `mobiles` 4-tuples (z above the floor),
`barrel_views={drawable: lump}`, and `thing_removed=` -- a NEW keyword rather than a widened `thing_hidden` assert:
`thing_hidden` keeps its "one skill's absent set" check for runtime things, `thing_removed` names what the game removed
(each a VANISHABLE type; a baked one needs a thvis slot). `scratchpad/gp/p67_identity.py` holds every existing
picture byte-identical with them absent or empty.

**The probe** (`probe.game_cells(..., nthvis=)`): the cells of 4.5 in groups {p_bc p_str p_bp am_misl am_cell},
{bar_st bar_ti bar_hp rng_wd}, {mdrop dr_live}, {lvtime g_rs g_skill}, and {bar_solid} on its own (P3.2b's label,
read for the first time); `thvis` only with its count. `Oracle.player_mode` / `nthvis`; `gatestate.STATE_NAMES` and
`run_reading_state(nthvis=)`.

**The gates' frame order** (p2a_gate.Mirror, m2_std_gate, m3_gate, B0's BinaryMirror): [a due restart] -> the latch
-> the door tic (press and contact need alive) -> the movers -> the use block (SKIPPED while dead: no exit, no SR
lift, no switch, and **`pusedn` is not written** -- the model's death think leaves `p_usedown` alone; package B must
match) -> `sync` -> `nukage` -> `weapon` -> `move` (dead: no move, no turn) -> the walk-overs -> the monsters' tic
(not on the exit frame). The weapon now runs after the use press in every gate (it commutes with it).

**Gates**: `fight_gate.py` (F1..F10, S2) and `die_gate.py` (D1..D8), hurt_gate at "full"/"full", m2_std/m3 print and
fail on a death, `b0_scenarios.py --oracle-only` (the frozen replay plus the mirror, no binary; a per-run loot-parting
counter). m2_r4_gate (the hosted tier) and gatestate_check (a pre-P1.5 mechanics check) keep step_sim, by design
(`tests/host/test_gates_step_the_model.py` names why).

**OUTCOME (package D): the FALLBACK + THE TURN TO THE KILLER** (the coordinator took the turn into this rung the same
day). The weapon drops (P5), the red palette fades (P5), use restarts at the skill being played (P7-d, package D:
`restartcode.tic_lines`), the dead player neither walks nor turns by keys (P7-a/b/c, package B's dead guards) -- and
the dead view TURNS TO THE KILLER, as P_DeathThink does. No view drop is in this rung: every exact drop is over the
size bar and costs ops on every frame, and the one cheap drop is not provably byte-exact without a build.

THE TURN, as built (package D):
- **Model** ("full" only; "fx" keeps P5's plain fade): `World.p_attacker` (a NEW schema field: v5 needs the SCHEMA
  GROWTH re-freeze, `--grown-from`, since v5's hurt frames now write it), set by `combat.damage_player` on every hit
  that lands -- 1 + the monster slot for a `("mon", m)` source (hitscan, claw, bite; a fireball's impact carries its
  shooter), 0 for sector damage (NULL) and a barrel's blast (its source is the player himself, which turns nothing).
  `_death_think` -> `_turn_to_attacker`: angle = R_PointToAngle2 (`rm.point_to_angle`) from the player to the
  attacker's CURRENT position; delta < ANG5 or > -ANG5 -> snap and the flash fades, else +-ANG5 the short way (minus at
  exactly ANG180); no attacker -> the flash fades. Host: tests/host/test_death_turn_model.py.
- **fj**: `p_atk` (hurtcode.CELLS, so it persists, restarts and reaches the restore set with the hurt cells);
  `dp_go` writes it from `dp_src` and zeroes `dp_src` on every exit (a caller that names none = no attacker); the
  monster slot stubs set `md_src` = 1 + slot before `md_attack`, which copies it into `dp_src` before each of its
  `dp_go` calls; `pj_spawn` stores it in the fireball's `pj_src`, the impact hands it to `dp_go`, P_RemoveMobj zeroes
  it. `hurtcode.turn_lines` = the leaf `dt_turn`: a two-level dispatch on `p_atk` to the attacker's thpos_rt row,
  two 4-nibble pointer reads of its integer x / y, then the monsters' own `mon_rot_leaf` for the angle (one shared
  `proj.point_to_angle`), then the compare / turn / snap / fade.
- **HOOKS**: package B's death think calls `stl.fcall dt_turn, dt_tret` IN PLACE of its plain `p_dc` fade (after the
  psprites, before the use test). Package C's barrel blast and package B's nukage call `dp_go` WITHOUT setting
  `dp_src` (0: DOOM turns nothing for either) -- nothing to add, but nothing may set it either.
- **Cost (MEASURED in the harness, tests/fj/test_death_turn_fj.py's program):** the leaf is +48,820 words (0.036% of
  2^27; a first cut that read the whole 16-nibble row and carried its own point_to_angle was +145,852). A dead tic
  costs ~14.5K ops (turning or facing), 259 with no attacker; dead frames only. Alive frames pay one 2-nibble move or
  zero per landed hit, per attack action and per live fireball slot (the copy-in / out): tens of ops, and only when
  something attacks (ESTIMATE). The alive-side size (dp_go's two lines, eight pool stubs' extra field, the slot stubs'
  `hex.set`) is not measured; ESTIMATE ~10K words.
- **Proof**: tests/fj/test_death_turn_fj.py (the leaf against `_death_think`, 55 cases x 40 tics: every octant, the
  attacker on the viewer, delta at +-ANG5 / +-ANG5 +- 1 / ANG180 / just under, long turns, no attacker; every id
  level of the dispatch) with R9 mutants "no turn", "the turn's direction flipped", "the turn never stops", "the flash
  fades while turning" -- each caught; test_player_damage_fj (+ `noatk`, `srcstale`), test_monster_attack_fj
  (+ `bulnosrc`, `meleenosrc`), test_fireball_pool_fj (+ `nosrc`, `srcfree`), test_restart_fj (p_atk / pj_src
  restored) -- all against the model.
