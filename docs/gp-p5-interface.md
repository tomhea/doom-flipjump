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
