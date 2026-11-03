# C2 -- monster / barrel slot ids past the byte (M8, 2026-10-19)

E1M6 has 294 monster slots (its 3 lost souls among them) and 7 barrels, E1M7 289 (8 souls) and 16 -- the union of
the skills. (Re-implemented 2026-10-21 on m8-episode, branch m8-c2b, over every merged feature: the first attempt,
origin/m8-c2-slots ef23469d, sat on an old base and was never merged.) Every fj register and cell that names a monster or barrel SLOT held it in TWO nibbles, so the survey refused
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
| soulcode (C8) | sk_hj, sw_me, sw_id, sz_tg (`scratch(sn)`); the slam's dm_src / dm_id / dp_src; the float's and the charge's mm_tg; kb_live | 2 | 3 |
| projcode (C6) | the plasma ball's pw_src (pl_spawn_leaf) | 2 | 3 |
| shotcode (C3) | the GR shot lines' ids count down from 0xFF: a wide map with a shot line is REFUSED (world.aim_bits, weaponcode) -- none on E1M6 / E1M7; combat.window_aim reads a shot id only where nshot > 0 | 2 | refused |
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

## 4. Proof (m8-c2b, 2026-10-21 .. 23; every heavy run through scripts/heavy.py)

- **E1M1 / E1M2 emission identity**: `scratchpad/cr/emit_baseline.py --check` -- E1M1 21 / 21 parts SAME (certified,
  hosted_doors, standalone); `--check --map E1M2 --baseline scratchpad/cr/emit_baseline_e1m2.json` -- 7 / 7 SAME;
  "EMISSION IDENTICAL" both. (The later monstercode change -- a static slot at x or y 0 subtracts nothing -- emits
  the same text for every non-zero coordinate, and a zero one never assembled: hex.sub_constant refuses 0.)
- **RUN in fj at E1M6** (tests/fj/wide_maps.py: E1M6 from the asset wad, 294 + 7 slots), each against the MODEL, each
  with its wide control: `test_monster_damage_fj` 20 passed at E1M6 (shoot and fight; control: dm_go's third level
  dropped, both modes), `test_monster_hitscan_fj` 12 (control: mt_load's third level), `test_death_turn_fj` 12 (+2
  E1M1 skips of the wide mutants), `test_monster_wake_fj` 6 at E1M6 (the cursor across 256; controls: the third
  level, mt_n in two nibbles), `test_knock_fj` 4 at E1M6 (THE THRUST; control: kb_go's third level), `test_level_done_fj`
  19 (3-nibble kills 255 / 256 / 257 / 270; control: the low-byte division), `test_aim_record_fj` 15 (sp_sidw;
  controls: a 2-nibble write, a 2-nibble empty test), `test_wide_slots_fj` 4 (the tree at 300 targets; controls: the
  two-level tree, a swapped 256-block).
- **Host**: `tests/host/test_wide_slots.py`, `test_level_survey.py`, `test_survey_widths.py`, `test_p8a_interface.py`
  -- 48 passed (controls: the width without its MAP_CONFIG entry OVER / refused, a narrow map claiming 12 refused, the
  narrow tree = the old text, E1M1's schema = the old formulas, a GR shot line on a wide map refused).
- **Survey**: `--matrix E1M6 E1M7` shows no slot-id, aim_sid, LEVEL COMPLETE or runtime-ids row.

The harnesses leave E1M6's 3 lost souls (287, 288, 290) out of the damage and thrust targets: a soul's hit and thrust
are C8's (damage_parts / go_lines(souls=): the flight, sk_z, no kill count), cells these harnesses do not declare.

## 5. Open

- Not run in fj at E1M6: soulcode's wide registers (sk_hj, sw_me, sw_id, sz_tg: test_lostsoul_fj runs E1M8's narrow
  souls), projcode's pt_lines / the rocket / the plasma ball (pt codes, pw_src), barrelcode's blast sources (bl_src's
  nibble-2 tests, bar_src cells), the weapon's aim_sid -> dm_id reads, teleportcode's stomp. Each is a `%d` of the same
  `sn` in text the narrow maps keep byte for byte; test_fireball_pool_fj / test_barrel_fj / test_player_shot_fj /
  test_telefrag_fj / test_lostsoul_fj take the map parameter the same way (tests/fj/wide_maps.py) when a level rung
  needs them.
- E1M6's first emission: the survey still REFUSES it on "lost souls beside teleport lines" (C8 x C5: EV_Teleport's
  soul z is unwired in fj; wall_renderer refuses the map), so `scripts/emit_check.py E1M6` was not run.
- Per-frame cost: a wide map pays one more `sim.jump16` per id dispatch (dm_go, kb_go, mt_load, dt_turn, the wake
  tic) and 3-nibble instead of 2-nibble moves on the ids -- not measured (no E1M6 binary exists); E1M1 / E1M2 pay
  nothing (identical text).
