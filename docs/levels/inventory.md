# Level-pipeline inventory (2026-10-16)

Two read-only surveys of the doom-e1m2 worktree (branch m8-e1m2, uncommitted L1 included), made for
`docs/level-pipeline.md`. Line numbers are as of that tree; names outlive them. E1M2 marks: **HIT** (hit or fixed),
**LIKELY** (the code says it will fail on E1M2, no emission confirmed it), ok, ? (unknown).

## A. Capacity caps that depend on per-map counts

| # | where | quantity | limit | knob | computed without emitting by | E1M2 |
|---|---|---|---|---|---|---|
| 1 | `wall_renderer` lines_pid / skypid | distinct (ceiling key, floor key) plane pairs over walk segs, every door/mover state, back sectors | `< 16**PID_NIBBLES` | `MAP_CONFIG` | no function: inline loop with emitter closures -- `scratchpad/m4_bands.py` (spy on the band walk) | **HIT** 411 -> 3 nibbles |
| 2 | `wall_renderer` sfbase assert | PID bytes | `<= 2` | -- | from #1 | ok after L1 |
| 3 | `lut_generator.generate_bands_walk_fj` | band half-lists `2*vz_classes*bank_keys + sky lists` | `next_pow2 <= 16**BAND_NIBBLES` | `MAP_CONFIG` | `m4_bands.py` | **HIT** -> 5 |
| 4 | `World.sec_nibbles`; sectorcode / noisecode / statcode asserts | sectors | `<= 16**sec_nibbles` | derived | `len(wad.sectors)` | **HIT**, fixed (3) |
| 5 | doors / movers / switches, `d_state`/`l_state` 4 bits | stops per door or lift | `<= 16` | `DEFAULT_QUANT` | `doors.door_states`, `movers.lift_states` | ok |
| 6 | `things.LIST_MAX_THINGS` 254 | runtime things + mobiles; pools `nmon+10`; `nt+10+ndrop` | `<= 254` | -- | `drawable_things` + `baked_thing_mask`; `barrelcode.droppers(World)` | ok (227) |
| 7 | `monstercode.TD_KEY_ROWS` | runtime things + mobiles | `<= 256` | -- | as 6 | ok |
| 8 | `wall_renderer.check_slot_ids` | EVERY drawable thing, all skills | `< 256` | -- | `len(drawable_things(...)[0])` | **LIKELY** |
| 9 | barrelcode / damagecode / knockcode | `nmon + nbarrel` (dm_id, sp_sid 2 nibbles) | `< 255` | -- | World | ok |
| 10 | `world` schema `aim_sid` **7 bits** | `1 + nmon + nbarrel` | `<= 127` | -- (**no guard**; non-strict WorldState wraps) | World | **LIKELY, silent** |
| 11 | `statcode.check_world`; `p_killcount`/`p_itemcount` 8 bits, `p_secretcount` 4 | monsters; COUNTITEM pickups; secrets | `<= 99`, `<= 99`, `<= 9` | `COUNT_NIBBLES`, `DIGIT_SLOTS` | World + `statcode.counts_item` | **LIKELY** (129 monsters) |
| 12 | `lootcode` pkxyz | pickups | `< 256` | -- | `World.pickup_things` | ? |
| 13 | barrelcode drop row | `nt + 10 + k` | `< 256` | -- | 6 + droppers | ok |
| 14 | monstersight blast spots | barrels | `<= 255` | -- | World | ok |
| 15 | monstermove, `nkleaf`, `hex.mov 3 ... thss_rt/ptss`, sim.fj | subsectors | `<= 4096` | literals | `bake_bsp(...).subsectors` | ok (1,104) |
| 16 | `build_blocked.py --subsectors` | subsectors for the pin veto | was default 682 | **now derived** | as 15 | **HIT**, fixed |
| 17 | `selfreset` restore label prefix | `e1m1_bspcode_side` | -- | derived from mapname | -- | **HIT**, fixed |
| 18 | `_assert_pnear_unbound` | marking two-sided segs (union over door states) | `< 4095` | -- | `marking_seg_count` / `seg_marks_in` (m4_caps) | ok |
| 19 | `_lines_step_bank` | step-face classes | `<= 256` | -- | needs the seg_secs closure | ? |
| 20 | `_lines_sprite_light` | sprite light classes | `<= 256` / `65536` | -- | module-level | ? |
| 21 | `_lines_sprite_bank` | sprite bank blocks | `< 0x10000` | -- | `_lines_sprite_bank(rm, spr, cfg, wad, m)` | ? |
| 22 | `_lines_sky_bank` | runs per sky half-column | `<= 65` | `MAX_BANDS` | callable | ok |
| 23 | `_seg_xorby_block` | any baked constant vs its register | `< 16**w` | per register | emit time only | ? |
| 24 | far bound | widest sprite side | `SPR_REACH` 80 | Config | `things.tight_far_bound_ok` | ? |
| 25 | monstersight / mapcompiler / monstercode D3 / collision / lootcode | vertex extents (far LOS `<= 4064` the tightest) | various | -- | `wad.vertexes` | ? |
| 26 | 2^27 span, pool base 2^26, size 43% | span and size | -- | flags | assembly; estimated from #3 | the deciding risk |

Type-level caps (per new type, not per map): pain classes <= 4, damage profiles <= 16, view groups <= 256, all monsters
one height, every monster COUNTKILL.

### Features the emitter refuses
- Two-dynamic-sector lines: door|door, door|mover refused by the renderer; mover|mover rendered since M8 L1 (the pair
  switch) but **LIKELY** still refused by `collision` ("line touches two movers"), `monstersight` ("line between two
  dynamic sectors"), `noisecode` ("sound edge between two dynamic sectors"). A mover line that is also a door line;
  a lift the floor switch also lowers.
- Sound: `noisecode` refuses any ML_SOUNDBLOCK edge (E1M2: 54 lines; L5).
- Door/mover geometry: door state shape; a door with two kinds; a W1 tag must open ONE door and be one axis-aligned
  segment; a WR lift line axis-aligned and tagging one lift; a floor switch must lower; a mover needs neighbours.
- Things: every type in `gamedata.THING_TYPES`; no seg-less leaf; `lootcode.give_lines` KeyErrors on any pickup it
  lacks (E1M2: 6, 13, 2013, 2026); a pickup in a door/mover sector; the player start on a static blocker; a damaging
  floor that is or nears a mover; a barrel on a mover; at least one barrel, the same layout on every skill; no
  damaging sector or health/armor near the exit box.

### Where the supported sets live (outside them: silently inert)
Doors `doors.py` (blue {26}, blaze {117}, walk-over {2}, exit {11}; ⚠ `door_sectors` makes ANY special line with a
shut back sector a PLAIN DR door); movers `movers.py` (88, 62, 23 -- ⚠ every S1-23 shares ONE `fswitch` cell); monster
doors `world.py` {1}; keys: model `combat.KEY_DOOR_CARDS`, fj only the blue `pcard`; sector specials
`combat.SECTOR_HURT` {4,5,7,16} + secret 9 (lights static); things `gamedata` + `combat.GETTABLE` + `lootcode.give_lines`;
rendering `reference_model` (`THING_SPRITE`, `MONSTER_TYPES`), `exitsign.EXIT_SIGNS` (E1M1 only, optional).

## B. E1M1 hard-wiring in the ship pipeline

**The pattern:** the bottom layer already takes `wad`/`mapname` (`probe.Oracle`, `onewalk.DoorSim`, gamespeed's
`_oracle/_tour_plan/script`, `build_blocked --wad/--map`, `m2_std_gate`/`m3_gate --wad/--map`); the wiring breaks by
(1) callers passing no map (`P.Oracle()`, `DoorSim()`, `World()`, `GS.full_script()` -> E1M1), (2) counts hard-coded
or taken from a default-map model, (3) scenario poses, sectors and indices as E1M1 literals.

### Build path
- `build_blocked.py`: `--subsectors 682` and no `pid_bytes` to the pin veto -- **fixed** (derived). `--view-w` from
  `tier_cfg(map_cfg(...)).VIEW_W`. Defaults `--wad/--map` E1M1 (pass them).
- ship-gate 1b: `build/doom_e1m1_<name>`, `_census_game.json.gz`, `heat_blocked27_p10`, `atlas/<name>` -> per map.
- `build.py` restore sets (m1_/m5_) recorded on E1M1: the one-pass tiers use NAMES only, one map-named entry
  (`e1m1_bspcode_side`) remapped -- add a test that E1M2's registry has `e1m2_bspcode_side` and no `e1m1_` names; refuse
  the legacy two-pass path off E1M1.
- `DEFAULT_MAP_WAD`, `World()/MonsterPhase()` default E1M1: every gate must pass the map (optionally refuse defaults
  while a map profile is active).

### Correctness gates
- `deg_gate.py`: wad, map, prefix, the four viewpoints, op baselines -> `--map` + `viewpoints/deg_<map>.json`.
- `m2_std_gate.py`: `plan_route` uses `spawn_state(mw, "E1M1")`; only the blue card exists (filter keyless doors).
- `m3_gate.py`: `run_reading_state` without `nlift` (default 2 = E1M1's lifts) -> pass the mover count.
- `gp/probe.py`: `game_cells` sizes `mdrop`, `bar_*`, `st_secm`, `msec`, `snd_alert` from `World()` with NO map ->
  functions of `(wad, mapname)`; selftest pose `(1272,-724)`.
- `gp/p2a_gate.py`: blue door 71, blaze 84, walk-overs 77/145, card sector 124, lifts 98/103, the pose `(40,256)`,
  switch pillar 129, reversal door 10, card `(2192,576,136)`, `P.Oracle()` without map -> roles from
  `scenarios/<map>/gates.json`.
- `gp/hurt_gate.py`: only the missing map pass-through (scenarios derive from monster types).
- `gp/fight_gate.py`: walk poses in sectors 91/135/8, the barrel column `x == 2512`, `barrel_things[13]`, nukage
  sector 23, the brawl court, item scenarios needing the chainsaw / berserk / launcher -> roles + N/A with reason.
- `gp/die_gate.py`: door 10, nukage 23, lift 98's leaf -> roles.
- B0 (`gp/b0_scenarios.py`): `GameOracle(P.Oracle)`, `DoorSim()` without map; set files carry `"map"` but nothing
  reads it -> read `doc["map"]`.
- `gp/scenarios_v2.py`: model hash of the E1M1 fixture, 11 hand-placed `CHECKPOINTS`, `World()` without map ->
  map from the doc, `--suggest-checkpoints`. `gp/scenarios.py`: `LIFTS = (98, 103)`, blue specials only.
  `gp/census_lib.py`: `things("E1M1")`, `SimState/build_scene(..., "E1M1")`. `gp/gatestate.py`: `nlift=2` default.
- gamespeed `--validate` / `gamespeed_trail.py`: `BINARY_ENDS/DOORS`, recorded keys -> `scenarios/<map>/gamespeed.json`.
- host tests on E1M1 records: `test_gamespeed_validate`, `test_p67_model`, `test_aim_window_oracle`,
  `test_b0_setup_and_proxy`, `test_b0_scenarios_frames`, and `test_pin_heat` (all 1b lines must agree -- key by map).

### Speed and size
- `gamespeed.py`: no `--map` in `main`/`measure_speed`/`full_script`; tours are GENERATED (free once threaded);
  ⚠ `_tour_plan` opens every use-box door incl. key doors -> keyless kinds only (as `gp/p12_video.py`).
- `msframe.py`: baseline name per map (`shipped_<map>`); the timed script holds forward from spawn (a spawn facing a
  wall times a stuck view -> optional tour script).
- `pinreport.py` / `poolmap.py`: E1M1 hot list, census, knobs (`map`, `wad`, heat) -> per map.
- the p11 pose-replay routes live in a session temp dir -> generate and track per map.

### Per-map artifacts and generators
fixture (`make_e1m1_wad.py E1Mn`) | census, labels, stamp (the one-pass build writes them) | restore sets (reused; new
state cells join `registered_reset_names`; check with `onepass_check.py`) | heat list (try E1M1's: its keys are macro
paths; regenerate via profx drive + heatsites if pinreport shows hot groups unpinned) | tours (generated) |
gamespeed ends/doors/keys (`gamespeed_trail --map --record`) | combat set (suggest checkpoints -> plan -> B0 -> the
owner's freeze) | gate roles (`gp/gate_targets.py --map`) | deg viewpoints (pose sweep) | msframe baseline
(`--save-baseline shipped_<map>`) | playtest/video keys | replay routes.

### Other
`playtest.py` (E1M1 x5), `render_frames.py` (set from env, `GameOracle()`), `exitsign.EXIT_SIGNS` (E1M1 only),
`things.SINGLE_PLAYER_EXTRA` keyed by E1M1 `(type, x, y)` -> key by map, `projcode` `pfx="e1m1"` defaults (check
callers), `docs/ship-gate.md` one binary -> a section per map.
