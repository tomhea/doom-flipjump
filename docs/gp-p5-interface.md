# P5 -- the monsters' attacks: the shared interface (coordinator, 2026-10-04)

ONE rung (the plan: the session's P5 planner; carries nothing else -- P4.2b rides in P4's build). The model mode:
`MONSTER_MODE = "full"`, `PLAYER_MODE = "fx"` -- a NEW player mode = "hit" + the player's shot spawning BLOOD on a
monster (`_spawn_fx_at_target`, today behind `_p_full`). `PLAYER_MODES = (walk, fire, shoot, hit, fx, full)`; replace the
literal tuples ("shoot","hit","full") everywhere with ONE helper `world.player_resolves(mode)` (and `player_hears` for
("hit","fx","full")). Left OUT of "fx" (the full model keeps them): barrels (aim, damage, blasts), puffs, drops,
pickups, bonuscount, berserk, player blocking by things, nukage (`_special_sector` behind `_p_full`), the player's
death think and restart (P7). The player CAN die in the model; P5 builds the death MOMENT only (p_dead, the weapon's
downstate, the +1 rng_player tics draw) and the AI's target loss; no gate may reach a death (assert deaths == 0).

## Streams
- mon_rng: bullets 3 draws each, claw 1, bite 1 (decide already draws them; P5 applies the outcomes)
- rng_player (fj `rng_pl`): +1 per damage that lands (pain roll, or the death tics roll)
- rng_fx (NEW fj cell `rng_fx`, 2 nibbles): fireball spawn tics, impact damage, explode tics, blood spawn tics; a full
  pool (fizzle / skip) draws nothing

## fj labels and cells (owners)
- hurtcode.py (agent B): `dp_go` / `dp_ret` with arg `dp_dmg` (2 nibbles) -- combat.damage_player exactly; cells
  `p_hp` (3, signed), `p_ar` (2), `p_at` (1), `p_dc` (2), `p_dead` (1), `pal_cur` (1); the monster hitscan / claw /
  bite apply path in monsterdecide's attack leaf (`mbul`, `trclaw`, `sgbite` tables); `hp_bar` (health/armor into
  hud_v+3..8 every tic); the palette (`palidx`, `present.set_palette playpal<k>` only on change; menus force 0).
- projcode.py (agent C): the fireball pool -- `pj_spawn` / `pj_sret` with args `mm_x`, `mm_y` (the monster's map
  position, 4 nibbles each, integer) -- fireball slot s = runtime thing `nt + s` (s < 8), cells `pj_act[8]`, `pj_x/pj_y`
  (8 nibbles 16.16), `pj_mx/pj_my` (8), `pj_st` (2), `pj_ti` (1); `pj_phase` (per tic); the missile cells
  (collision_cells_fj tag "mc6"); the fx (blood) pool -- `fx_spawn` / `fx_sret` with args `fxs_x`, `fxs_y` (4 nibbles,
  integer), `fxs_dmg` (2) -- blood slot s = runtime thing `nt + 8 + s` (s < 2), cells `fx_act[2]`, `fx_x/fx_y`, `fx_st`,
  `fx_ti`; `fx_phase`; damagecode's reorder (reach, then the fx spawn, then the shootable/health checks).
- Python/oracle/gates (agent A): combat.py / world.py modes; monsters.MonsterPhase (weapon: damagecount/bonuscount
  decrement; tic: _projectiles_phase/_barrels_phase/_fx_phase; state: p_hp p_ar p_at p_dc p_dead rng_pl rng_fx + the
  pj_*/fx_* cells; MonsterViews.rt_state + the 10 mobile rows); reference_model.render_wall_frame(mobiles=[(x, y,
  lump)]) -- drawn as runtime things in their leaf after the wad ones, scenery class, base min height, z = floor + 32,
  never seen or aimed; MonsterPhase.mobiles(); combat.palette_index(ws); the probe/gatestate cells; B0: inject
  p_health/p_armor/p_armortype per frame from the frozen model (F2), palettes compared; hurt_gate.py (H1-H6, S1 +
  controls); the host tests (player modes "fx" vs "full", the tables).
- Integration (the coordinator): p31_parts mobile rows and stubs, the lists grown by 10, restart lines, wall_renderer
  placement, persist and restore sets, emit-time asserts, the ledger.

## The cells' units (agent A, 2026-10-04) -- what the probe reads and the oracle expects

The ONE definition is `monsters.MonsterPhase.hurt_state` / `proj_state` / `fx_state` and `MonsterViews.rt_state` (the
gates merge them into the state check through `MonsterPhase.state()`, which adds the hurt and fireball cells when the
monster mode is "full", and the blood pool with `rng_fx` when the monsters are "full" or the player bleeds). The
probe's cells are `probe.game_cells`, in three OPTIONAL_GROUPS that come whole or not at all:
{p_hp p_ar p_at p_dc p_dead pal_cur} (B), {pj_act pj_x pj_y pj_mx pj_my pj_st pj_ti} (C),
{fx_act fx_x fx_y fx_st fx_ti rng_fx} (C). Every one is a hex cell, nibbles little-endian, read UNSIGNED.

hurtcode (B):
- `p_hp` 3 nibbles: the model's `p_health` as 12-bit two's complement (`p_health & 0xFFF`; level start 100 = 0x064).
  A killing blow takes it to or below 0 (below -100: the gib state). "Alive" everywhere = p_hp > 0 (signed) and not
  p_dead (`World.player_alive`).
- `p_ar` 2 nibbles: armor points 0..200. `p_at` 1 nibble: 0 none, 1 green (saves dmg / 3), 2 blue (saves dmg / 2);
  when `p_ar <= saved` the save is p_ar and p_at falls to 0 (`combat.damage_player`, DOOM's order).
- `p_dc` 2 nibbles: the damage count, `min(100, p_dc + the damage after armor)`; it fades by 1 once per world tic
  AFTER the psprites (MonsterPhase.weapon: the weapon keys, P_MovePsprites, then p_dc -= 1 -- and the bonus count,
  which "fx" never raises: no cell). A dead player's tic only moves the psprites and fades p_dc.
- `p_dead` 1 nibble 0/1. THE DEATH MOMENT (P_KillMobj): p_dead = 1, the weapon set to its downstate (P_DropWeapon:
  A_Lower runs once; with p_dead a weapon at the bottom stays there), the player thing's death (or gib) state, and
  ONE rng_pl draw (its tics roll) -- no pain roll. A dead player takes no damage and draws nothing more; a monster's
  A_Chase on a dead target clears its threshold and returns to its spawn state; a fireball passes through him.
- `rng_pl` (P4.1's cell): +1 per damage that lands on a living player -- the pain roll, or the death's tics roll.
- `pal_cur` 1 nibble: the PLAYPAL index the last present showed. A WORLD frame shows `combat.palette_index(ws)` taken
  after the whole frame (weapon, move, monsters, fireballs, blood): ST_doPaletteStuff -- cnt = p_dc (raised to
  `12 - (strength >> 6)` while berserk runs: never in "fx"), red `min(7, (cnt + 7) >> 3) + 1`, else bonus
  `min(3, (bc + 7) >> 3) + 9`, else 0 -- in "fx" that is 0 or 2..8 (the rule never shows 1 or 9). A MENU frame shows
  0. The palettes are the ASSET wad's (`assets/freedoom1.wad`, 14 of them; the fixture map wad carries palette 0
  alone, byte-identical): the gates compare sha1[:12] of the device's palette at every present against
  `probe.palette_sha(art, index)`.

projcode (C) -- the fireball pool, slot s < 8 (FIREBALL_POOL), runtime-thing row nt + s:
- `pj_act[s]` 1 nibble 0/1.
- `pj_x[s]`, `pj_y[s]` 8 nibbles each: the 16.16 position, 32-bit two's complement (`& 0xFFFFFFFF`). Spawn: the
  monster (whole units) << 16 plus the momentum >> 1 (arithmetic), then P_CheckMissileSpawn at that point.
- `pj_mx[s]`, `pj_my[s]` 8 nibbles each: the 16.16 momentum per tic (`combat.fireball_momentum_table` at the fine
  angle of R_PointToAngle2 monster -> player), zeroed when it explodes.
- `pj_st[s]` 2 nibbles: the GAMEDATA state index -- S_TBALL1 46, S_TBALL2 47 (flight, 4 tics each), S_TBALLX1 48,
  S_TBALLX2 49, S_TBALLX3 50 (the explosion, 6 tics each). `pj_ti[s]` 1 nibble: tics left (the spawn's and the
  explosion's `max(1, tics - (P_Random() & 3))` on rng_fx).
- a FREE slot is all zeros (P_RemoveMobj zeroes it; so does the level start).

fx (blood), slot s < 2 (FX_POOL), row nt + 8 + s: `fx_act[s]`; `fx_x[s]`, `fx_y[s]` (8 nibbles, 16.16 -- always whole
units: the spawn point is FX_OFFSET in front of the monster, by octant); `fx_st[s]` (2 nibbles, gamedata index:
S_BLOOD1 39, S_BLOOD2 40, S_BLOOD3 41 -- after the tics roll a hit of 9..12 sets S_BLOOD2 and one under 9 S_BLOOD3,
each with the state's own 8 tics); `fx_ti[s]` (1 nibble). "fx" never makes a puff.

- `rng_fx` 2 nibbles: the fireball's spawn tics roll, its impact damage, its explode tics roll, the blood's tics roll.
  A full pool -- a fizzle, a skipped blood -- draws NOTHING.
- THE MOBILE ROWS of `thpos_rt` / `thss_rt` (the probe reads nt + 10 rows when the modes have mobiles:
  `monsters.mobile_rows`, `MonsterViews.nrows`): a live slot's row holds its WHOLE-UNIT position -- 16.16 with the
  FRACTION CLEARED, `((pj_x >> 16) << 16) | ((pj_y >> 16) << 16) << 32` (the floor: an arithmetic shift) -- and its
  leaf, `point_in_subsector(x >> 16, y >> 16)` (the model's proj_leaf / fx_leaf, relinked whenever it changes); a free
  row is (0, 0) and in no leaf list. The renderer draws a mobile from its row, so a row that kept pj_x's fraction
  would draw a different picture.

How the oracle draws them (`reference_model.render_wall_frame(mobiles=[(x, y, lump)])`, rows in order, from
`MonsterPhase.mobiles()`): a runtime thing of its leaf, AFTER the leaf's WAD runtime things (row order), and under
`rt_depth_order="aprox"` sorted with them by `aprox_depth_key` (stable: the row order breaks ties); the SCENERY class
(it counts against THING_BUDGET, never MONSTER_BUDGET); always the BASE minimum height MIN_SPRITE_H (3 rows: the
graduated acceptance's raise never applies to it); standing MISSILE_Z = 32 above its leaf's floor (the leaf's sector,
as for every thing) and lit by that sector (no fullbright); NEVER seen, NEVER aimed; its lump is its state's frame at
rotation 0, never mirrored (`monsters.mobile_lump`: BAL1A0 / BAL1B0 in flight, BAL1C0 .. BAL1E0 exploding,
BLUDA0 .. BLUDC0). That no existing picture moved: scratchpad/gp/p5_mobiles_identity.py (60 frames of v5 R0-west-hall
against the UNMODIFIED oracle from git -- 60/60 identical with mobiles=[] and with None; 15 of its frames with a live
mobile draw it).

The gates' frame order (MonsterPhase): the door tic -> `weapon` (keys, psprites, the p_dc / bonus fade) -> the
player's move -> `tic` (the monsters, then the fireballs, the barrels, the blood: world.tic's order) -> the render
(seen, aim, the mobiles) -> the present's palette. B0 injects p_hp / p_ar / p_at at every frame start from the frozen
model's PRE-tic values (as it injects the pose; p_dc is the binary's own) and fails a run whose mirror reaches p_dead.
hurt_gate.py pokes at frame 0 every cell its setup moved from the boot level start -- MEASURED (its --oracle-only log
prints them): mon_state, mon_tics, mon_target, mon_reaction, p_ar, p_at, wp_own, am_shell -- so each must be a
persisted cell the probe can write; no scenario teleports a monster (no leaf list is poked).
