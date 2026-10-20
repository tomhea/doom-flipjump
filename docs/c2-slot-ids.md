# C2 -- monster / barrel slot ids past the byte (M8, 2026-10-19)

E1M6 has 291 monster slots and 7 barrels, E1M7 281 and 16 (the union of the skills, without the lost souls C8 adds:
+3 / +8). Every fj register and cell that names a monster or barrel SLOT held it in TWO nibbles, so the survey refused
E1M6's World on `aim_sid` and the emitters asserted < 255 in a dozen places. C1 (docs/f1-runtime-ids.md) widened the
runtime THING ids (the leaf lists); this widens the SLOT ids.

## 1. The width

`world.slot_nibbles(layout)` -- DERIVED from the counts, as `World.sec_nibbles`: 2 while nmon + nbarrel <=
`SLOT_IDS_NARROW` (254: the tightest old bound, the bullets' scan code 2 + nmon + b and dm_go's id space), else 3 (to
`SLOT_IDS_WIDE`, 4093). `Config.SLOT_ID_BITS` (8 / 12, MAP_CONFIG E1M6 / E1M7: 12) names what the map's emission
expects; `wall_renderer.check_slot_bits` refuses a mismatch at emission. Not an fj constant: fj_consts.fj and the fj
library are unchanged.

E1M1 (75 slots) and E1M2 (138) are narrow: their schema and every emitted line are as before (proof: 4).

## 2. What widens (the inventory)

| where | the id / code | narrow | wide |
|---|---|---|---|
| world.build_schema | aim_sid, mon_target (fight), bar_src, p_attacker, sched_cursor, proj_src | their old formulas | 12 bits each |
| world.build_schema | p_killcount, p_itemcount (`count_bits`: max(nmon, npickup) past a byte) | 8 | 12 |
| aimcode | aim_sid's cells; the row-select id (`sid_reg`, `sid_set_lines`) | sp_sid, 2 nibbles | `sp_sidw` 3 nibbles, `sp_sid` the 2-nibble AIMABLE flag (projection.fj's `proj.aim_hook` tests `hex.if0 2, sp_sid`: the library is untouched, and an id 0x100 would read as 0 there) |
| monstercode | the thsel stubs' aim ids (monsters, barrels); md_src; mm_tg loads; the wake tic's sched_cursor / mt_fdef / mt_n (`p32a_scratch`) | 2 | 3 |
| monstercode.id_jump_lines | THE dispatch tree on an id (dm_go, kb_go, mt_load, dt_turn, the wake tic) | two levels: the old text | a third level (nibble 2) first |
| damagecode | dm_id, dm_src, dm_me, dm_tg (fight), kb_tg (`fight_decls(sn)`) | 2 | 3 |
| weaponcode | dm_id (`dm_cells(sn)`), the shot's aim_sid reads | 2 | 3 |
| hurtcode | p_atk (`cells(sn)`), dp_src, md_src, kb_tg; dt_t is a runtime ROW: `row_nibbles` (3 past row 255) | 2 | 3 |
| knockcode | kb_tg, kb_live (`interface_decls`, `persisted_decls(sn=)`) | 2 | 3 |
| monsterdecide | mm_tg, md_me, md_c1, hs_vic, hs_id (`fight_decls(sn)`), dp_src / dm_src / dm_id moves | 2 | 3 |
| barrelcode | bar_src, bd_src, bl_src, bw_sr; bl_src's "a monster" tests read nibble 2 too | 2 | 3 |
| projcode | pj_src / pw_src (`pj_fields(sn)`), pt_me / pt_j, dp_src, dm_src, dm_id, the rocket's sources | 2 | 3 |
| teleportcode | the stomp's dm_id | 2 | 3 |
| statcode / lootcode | st_kill / st_item (`count_nibbles`); the first decimal split of a 3-nibble count (inline `hex.div 3, 1`) | 2 | 3 |
| build.game_screen_persisted_decls, p8a_persisted_decls | the restore set's widths | 2 | 3 |
| scratchpad/gp/probe.py | the gates' cells (`_slot_nibbles`, `_count_nibbles`) | 2 | 3 |

No other id width exists: every `assert ... < 256 / <= 255 / < 255` in the emitters was read; the rest bound states,
damages, radii, tables or the barrels' and droppers' own counts (all < 256 on every surveyed map).

## 3. Survey

`scripts/level_survey.py`: "monster slots + barrels (slot ids, Config.SLOT_ID_BITS ...)" caps against the map's width
(254 / 4093) with an INFO "slot id bits needed"; the aim_sid and LEVEL COMPLETE rows read the schema's widths; the
drawable-things row reads the map's `SPR_SLOT_CAP` (it was OVER on E1M2, which emits and ships); when the filtered
World refuses for another reason (E1M7: C5's teleport) the slot rows come from the WAD's things (`world.level_things`)
and the runtime-ids row counts the droppers from them. `--matrix E1M6 E1M7`: no id-width row left.

## 4. Proof

- **E1M1 / E1M2 emission identity**: `scratchpad/cr/emit_baseline.py --check` (E1M1, 3 configs) and
  `--map E1M2 --baseline scratchpad/cr/emit_baseline_e1m2.json`.
- **RUN in fj at E1M6** (tests/fj/wide_maps.py: E1M6 from the asset wad, its unknown types filtered), each against the
  MODEL, each with a wide control: `test_monster_damage_fj` (dm_go and dm_leaf, shoot and fight: dm_src / dm_me /
  dm_tg past 255; control: the third level dropped), `test_monster_hitscan_fj` (mt_load, md_attack, hs_scan; shooters
  past 255; control: mt_load's third level), `test_death_turn_fj` (dt_turn: p_atk past 255, rows past 255; controls:
  third level, dt_t two nibbles), `test_monster_wake_fj` (the cursor from 250 across 256; controls: third level,
  mt_n in two nibbles), `test_knock_fj` THE THRUST (kb_go; control: third level), `test_level_done_fj` (3-nibble
  kills 255 / 256 / 291; control: the low-byte division), `test_aim_record_fj` (sp_sidw, 3-nibble cells around 0x100;
  controls: a 2-nibble write, a 2-nibble empty test), `test_wide_slots_fj` (the tree itself at 300 targets; controls:
  the two-level tree, a swapped 256-block).
- **Host**: `tests/host/test_wide_slots.py` (the widths, the narrow schema = the old formulas, the narrow trees = the
  old text, the emitter's refusal -- each with its control), `tests/host/test_level_survey.py` (the slot rows at both
  configs, the E1M7 fallback, the drawable row's cap -- controls the pairs).

## 5. Open

- Not run in fj at E1M6: projcode's pt_lines / the rocket (pt codes, pw_src), barrelcode's blast sources (bl_src's
  nibble-2 tests, bar_src cells), the weapon's aim_sid -> dm_id reads, teleportcode's stomp. Each is a `%d` of the same
  `sn` in text the narrow maps keep byte for byte; test_fireball_pool_fj / test_barrel_fj / test_player_shot_fj /
  test_telefrag_fj take the map parameter the same way (tests/fj/wide_maps.py) when a level rung needs them.
- E1M6's first emission is blocked by other clusters (lost souls, doors, movers ...); the gates' probe widths are
  ready (scratchpad/gp/probe.py).
- Per-frame cost: a wide map pays one more `sim.jump16` per id dispatch (dm_go, kb_go, mt_load, dt_turn, the wake
  tic: ~5 dispatches a hit, one per monster tic) and 3-nibble instead of 2-nibble moves on the ids -- not measured
  (no E1M6 binary exists); E1M1 / E1M2 pay nothing (identical text).
