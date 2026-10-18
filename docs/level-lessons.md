# Level lessons: what E1M1 and E1M2 paid for, and where each lesson now lives (M8, 2026-10-19)

**The owner's words:** "all the levels should learn from each other mistakes" (`docs/episode-plan.md` 6). One line a
lesson: what happened, the evidence, and WHERE it now lives. A lesson that is only prose is unfinished: every PROSE ONLY
row below says why nothing computable catches it yet.

**Where, cheapest first:**

| where | cost | what it is |
|---|---|---|
| SURVEY | seconds | `scripts/level_survey.py` -- a row (the model's own functions, no emission); `Survey.lessons` holds the rows this file added |
| EMIT | minutes | `scripts/emit_check.py` -- the game tier's emission with asserts ON, its hot-block count, its reset composition, its stand-in refusal |
| BUILD | hours in | a refusal inside `build_wall_renderer` / `build_blocked` (the PREFLIGHT, `hot_window_violation`, `sprbank_misalignment`, the pool base) |
| GATE | hours | `m2_std_gate`, `m3_gate`, `p2a` / `hurt` / `fight` / `die`, B0, `gamespeed[_trail]`, `deg_gate`, msframe |
| TEST | seconds .. minutes | a tests/host or tests/fj file (named) |
| TOOL | -- | the process tooling (`scripts/heavy.py`, `mapprofile`, the generators) |
| PROSE ONLY | -- | nothing catches it; the reason is given |

New in this file's commit (each with a host test and a negative control in `tests/host/test_level_lessons.py`): the
survey rows marked **NEW**, and emit_check's stale stand-in refusal.

## 1. The level lessons (E1M2's development: L0 .. L6, F1 .. F7, the playtest, the polish)

| # | what happened | evidence | where it lives now |
|---|---|---|---|
| L01 | every cap was sized on E1M1 and asserted only at emit time: E1M2 found its blockers one 12 GB / 30-minute emission at a time (pid width, band index, sector ids, reset prefix, two movers on a seg) | `docs/level-pipeline.md` 1; handoff-e1m2 6 (13 emissions) | SURVEY (the whole script) + EMIT |
| L02 | `build_blocked.py` hard-wired 682 subsectors and the one-byte pid in the pin veto: an E1M2 build would have died in `selfreset.byte_arrays` | level-pipeline 1 | BUILD (derived from `--wad/--map`); SURVEY row "build_blocked --subsectors" |
| L03 | `aim_sid` was a 7-bit field with no fj guard (E1M2: 129 monsters) | level-pipeline 1; F1.1 | SURVEY "monsters + barrels -> aim_sid"; `world.py` asserts the byte |
| L04 | LEVEL COMPLETE's kill total was two digits (E1M2's 129 overflow it) | level-pipeline 1; F1.1 | SURVEY "monsters on LEVEL COMPLETE", "COUNTITEM pickups ...", "secret sectors ..." |
| L05 | `probe.game_cells` sized `msec`, `snd_alert`, the drop / barrel cells from a DEFAULT-map `World()`: every gate on E1M2 would have read E1M1's widths | level-pipeline 1, 3 | TOOL `mapprofile` (default-map fallbacks refused while a profile is active); TEST `test_take_map_arg.py` (control: probe imported on another map is refused) |
| L06 | gamespeed's tours opened every use-box door, key doors included | level-pipeline 1 | TOOL `gamespeed._tour_plan`'s key-door filter (`combat.KEY_DOOR_CARDS`) |
| L07 | `doors.door_sectors` made ANY special line with a shut sector behind it a plain DR door: keyed / D1 / SR / S1 doors opened without a key and re-closed | level-pipeline 1; handoff-e1m2 11 | SURVEY "door behind special N" (WRONG); TEST `test_doors_e1m2.py` (E1M1's classification frozen) |
| L08 | plane-pair ids 376 > 255 at `PID_NIBBLES=2`, found by an emission | handoff-e1m2 1, 4 (A) | SURVEY "plane pairs" -- **NEW: a WARN** (not a footnote) when estimate x1.5 >= 16^PID_NIBBLES (measured real/estimate: E1M1 1.46, E1M2 1.25); exact: `scratchpad/m4_bands.py` |
| L09 | the band index needed `BAND_NIBBLES=5` | handoff-e1m2 2a | PROSE ONLY: the band lists exist only part-way through an emission; `scratchpad/m4_bands.py` (a light emission) measures them |
| L10 | the one-pass reset registered `e1m1_bspcode_side`; E1M2 declares `e1m2_bspcode_side` | handoff-e1m2 2a | EMIT `reset_check` (the reset composed over the emitted parts); BUILD (selfreset refuses) |
| L11 | the reset registry missed `mc_don`: found 7 minutes into a build | 729eebe8; handoff-e1m2 9 | EMIT `reset_check` |
| L12 | a seg between TWO movers (linedef 1460: 240 / 241) -- one state nibble per seg | handoff-e1m2 5 | EMIT (`_seg_movers` / the pair switch); TEST `tests/fj/test_pair_switch_fj.py`; SURVEY **NEW** "dynamic segs the renderer can gate" (a door and a mover on one seg, a door on both sides: REFUSED) |
| L13 | sector ids past 255 (E1M2: 380 sectors) | handoff-e1m2 4 (B) | derived (`World.sec_nibbles`); SURVEY "sector-id nibbles"; TEST `tests/fj/test_sector_width_fj.py` (5 controls). Open (#143): 3-nibble ids untested in `mcf_leaf` and statcode's `sc_sec` |
| L14 | E1M2's floor-switch sectors border each other: one machine on two sectors | handoff-e1m2 6 | SURVEY "lines between two dynamic sectors: ... (one cell)"; the readers through `movers.mover_table` |
| L15 | a lift line with ML_BLOCKMONSTERS must block before any opening (P_CheckPosition) | handoff-e1m2 6 | the monsters' cells (V_MONLINE first); PROSE ONLY as a check: the rule is general code now, nothing map-specific to compute |
| L16 | a baked thing some skill lacks (lamp 2028) needs a `thvis` slot | handoff-e1m2 6 | `things.vanishable_slots` (one rule, every mirror); SURVEY "solid decorations some skill lacks" |
| L17 | the CR of #142 BLOCKER: the oracle's `MonsterViews.vis_state` mapped every slot to a pickup or barrel -- KeyError on E1M2's lamp; every gate reading thvis would crash | cd969f2; PR #142 | TEST `test_vis_state_skills.py`; SURVEY **NEW** "the oracle's thvis mirror reads every slot at every skill" + "World things with sprite art" (control: the pre-fix mirror raises on E1M2) |
| L18 | the plain size build (66.85%) is NOT comparable with a blocked build's size: the fast build's binding resource is the table pool | handoff-e1m2 7 | PROSE ONLY (a reading rule); `docs/ship-gate.md` 5 records the blocked build's numbers |
| L19 | E1M2's pool overflowed at spread 2 (PREFLIGHT 134.6%: one 97,647-table group); a projection of 75-85M was UNVERIFIED and low (90.3M) | handoff-e1m2 8; ce0073a7 | BUILD PREFLIGHT; poolmap `probe_pool` on the census; SURVEY **NEW** "pool demand (ESTIMATE by segs)": the spread to build at, WARN when even spread 1 overflows |
| L20 | E1M2's assembly peaked at 17.2-19.8 GB on this 15.6 GB box (0.02 GB left) | ship-gate 5; handoff-e1m2 7 | TOOL `heavy.py` (rule 1); SURVEY **NEW** "assembly peak RAM (ESTIMATE by segs)": WARN past the largest assembly finished here |
| L21 | the hot data block outgrew `frame.arm5`'s 16^5-bit window by 96 ops: NullIP on the first world frame, after a 97-minute build (`sfslot` +2,560, `thss_rt`, `sshead` ...) | handoff-e1m2 9; 729eebe8 | EMIT `hot_block_check` (TEST `test_emit_check_hot.py`, the boundary is the control); BUILD `build.hot_window_violation`. Open (#145 F1/F2): `hot_window_violation` has no test, and only the one-pass path calls it |
| L22 | a first diagnosis of L21 was WRONG (`thing_record_body`'s slot shift: `SPR_SLOT_STRIDE` must NOT scale with the pid) | handoff-e1m2 9 | a warning comment in `wall_renderer.py`; TEST `tests/fj/test_slot_layouts_fj.py` |
| L23 | the wide pid layout (`PID_NIBBLES=3`) was never built on a map with gates until E1M1 was forced to it (`m2_std_gate` 421 frames) | handoff-e1m2 9 | GATE (the forced E1M1 build, `emit_check --map-config`); PROSE ONLY as a rule: a width path the shipped map never takes is unproven until a gate runs it |
| L24 | E1M2's first size measurement ran under `python -O`: the `mc_don` guard it skipped became an undefined label 98 minutes later | level-pipeline 8 | EMIT (`assert __debug__`: it refuses -O); `heavy.py` brief rule 1 ("Never python -O") |
| L25 | three stand-ins (`stats-digits`, `far-los`, `attacker-7bit`) were obsolete after F1.1, so the 66.85% measured a program unlike the map's | CR of #142 item 3; #145 F10 | EMIT **NEW**: `STANDIN_ROWS` -- a stand-in none of whose survey rows refuses is STALE and refused (all six are stale on E1M2; `far-los` on every map E1M3..E1M9) |
| L26 | a stand-in patched AFTER a module bound the name at import would silently not apply | the P9 census lesson (bc25935); emit_check's registry order | EMIT (stand-ins applied before the emitter's imports; the survey for the stale check runs in a CHILD process) |
| L27 | the survey's marking-seg count took only door states (the emitter takes lift and switch states too): it could report OK where the emitter refuses | CR of #142 item 5 | SURVEY `_marking` (every door, lift and floor-group state) |
| L28 | the survey's "lines between two dynamic sectors" note was hand-written ("both refused") and wrong for E1M2 | CR of #142 item 4 | SURVEY **NEW**: the readers' own `collision.mover_line_states` (max, min) and `monstersight.line_states` over every dynamic line (control: a two-cell opening is REFUSED) |
| L29 | the survey's matrix dropped every row starting "World(strict" -- it hid the FILTERED World's own refusal (E1M6 / E1M7 leaf lists, E1M7's teleport destination, E1M9's door 135) | this commit | SURVEY matrix **NEW**: "World(strict=True) without the unknown thing types" shown with its reason (control in the test) |
| L30 | the survey's runtime-ids row retries `World()` without the unknown-type filter: REFUSED with a misleading note where the filtered World failed for another reason | #143 | PROSE ONLY: left to the C1 (runtime ids) branch, which owns that row |
| L31 | `docs/levels/*.md` / `matrix.md` went stale after F1.1 (OVER rows that were fixed) | CR of #142 item 6 | PROSE ONLY: regenerate after every rung (level-pipeline 8); a test against a frozen doc would fight every parallel branch |
| L32 | the CR of #144 BLOCKER: `p6_restart_parts` took EASY's barrel lines as the common restart: NEW GAME at HARD restored easy's barrels and the world stream 8 for 9 | d5daa08; PR #144 | TEST `test_barrelcode.py` (asserts through `p6_restart_parts`; the old composition is its control) |
| L33 | the CR of #144 wrong test: it tested `barrelcode.restart_lines`, not the restart the emitter composes | PR #144 B2 | TEST (as L32); rule: test the composition the emitter calls (`compose_restart`, `p6_restart_parts`) |
| L34 | `bar_solid` reads `w.ws` after the per-skill loop: right only because `SKILLS[-1]` is the boot skill | #145 F6 | PROSE ONLY: a code-order fact, not a map fact (fix in code: compute at `boot_skill`) |
| L35 | the CR of #146 BLOCKER: four E1M2 lines (2033 / 2062 tag 10, 2050 / 2075 tag 41) shut at EVERY floor state took the marking path in fj and the solid one in the oracle; no gate looked there | 9b8ef2c0; p2a S15 (fails on r2, passes on r3) | EMIT (`_seg_closed_moving`; `_seg_dual_cell` refuses open-then-shut); GATE p2a S15; SURVEY **NEW** "dynamic segs the renderer can gate" (the emitter's classification over every two-sided line; E1M2's four lines reported as the solid path) |
| L36 | `restart_lines` zeroes `fswitch` only when the map has a lift: a map with floor groups and no lift keeps its floors moved after NEW GAME | #147 (latent) | SURVEY **NEW** "NEW GAME restarts the floor groups" (calls `restart_lines`): was WRONG on E1M8 (3 groups, 0 lifts); FIXED by C4 (`nfloor=`), with a control |
| L37 | `_map_persist` persists `pcard_y` / `pcard_r` / `p_rct` for any standalone tier, declared only where loot / teleports are on | #147 (latent) | PROSE ONLY: only the game tier builds a level; a tier-matrix fact, not a map fact |
| L38 | the soulsphere give (`hex.cmp 3, p_hp`) on a signed cell: safe only because a dead player picks nothing up | #147; CR of #146 item 4 | PROSE ONLY (code review); not map-dependent |
| L39 | two rules for crossing a slanted walk-over line: doors by DOOM's spechit straddle, W1 floors by the grown box -- each mirror matches its own model, so no gate sees it | #147 | SURVEY **NEW** "slanted W1 floor lines": WARN with the linedefs to play-test (E1M2 1972 / 1974 / 2011; E1M7 3760; E1M8 894) |
| L40 | the playtest's BLOCKER: blue door 54 opened 12 units over its floor (the legacy rule read a one-sided line's back as the last sidedef's sector) and could never be passed | a0af8d4f; `docs/playtest-e1m2.md` | SURVEY **NEW** "doors the player can pass when open" (`doors.pass_state`; control: the legacy rule on E1M2 traps door 54 at 148); TEST `test_door_heights.py` |
| L41 | `LEGACY_NEIGHBOUR_MAPS` picks E1M1's door rule by a (sectors, linedefs, sidedefs) fingerprint: another map matching it would silently take it | #149 item 1 | SURVEY **NEW** "door neighbour rule": WRONG for a non-E1M1 map that matches (control in the test) |
| L42 | getNextSector has two definitions: `lights` tests ML_TWOSIDED, `doors.two_sided_neighbours` the back side | #149 item 1 | SURVEY **NEW** "lines with a back side but no ML_TWOSIDED" (none on E1M1..E1M9 today) |
| L43 | E1M2's polish runs model asserts only E1M2 has passed (one exit switch line, no light on a door or mover, light states in a nibble, the map page's fit) -- a new map turning a flag on hits them at emission | `docs/handoff-e1m2.md` 3; `switches.map_switches`; `emit_wall_renderer`'s light assert | SURVEY **NEW** "animated lights", "switch textures", "the MAP page": REFUSED when the map's flag is on, WARN for the day it is (E1M1 lights, E1M5 lights, E1M7 switches) |
| L44 | the scrolling wall was INVISIBLE in the game tier (a W1R wall has no texture u): a feature priced and built before anyone looked | 77df744f; handoff-e1m2 3 | PROSE ONLY: probe a feature's visibility in the game tier before building it (`scratchpad/p48_scroll_probe.py`) |
| L45 | the gates on a second map: p2a asked E1M2 for `swtm` (no SR switch: never declared) | a48390a6 | GATE (`Probe.read_cells` skips an OPTIONAL cell the binary lacks) |
| L46 | p2a / hurt / B0 drew the oracle without the world's animated lights | 25663875 | GATE (the harness passes `World` lights to the render) |
| L47 | m2_std / m3 took `--map` after probe had read its defaults | CR of #146 item 6; 4e20830b | TOOL `mapprofile.take_map_arg`; TEST `test_take_map_arg.py` |
| L48 | m2_std's door at hard had a monster in its use box; m3 could not tell the skills apart by picture | 2e00f152 | GATE (m2_std picks a door with monsters on its ground; m3 reads `g_skill`) |
| L49 | a B0 checkpoint must lie INSIDE the level | cc7e0bc2 | TOOL `gp/scenarios_map.py` (checkpoints planned per map) |
| L50 | E1M2's key doors (S1y/S3r ...), the card on a mover floor and teleports in B0 are N/A in the gates: proven only by tests/fj | #147 | TEST `tests/fj/test_doors_e1m2_fj.py`, `test_give_cards_fj.py`; PROSE ONLY on the binary: a gate role for them is the gate-tools agent's (`gp/gate_targets.py` lists the N/A roles with reasons) |
| L51 | a telefrag inside the player's KNOCK move never ran with the real damage / thrust code | #149 item 4 | PROSE ONLY: an fj harness to write (`tests/fj/test_telefrag_fj.py` covers the walk copy) |
| L52 | `tests/fj/test_noise_block_fj.py` takes ~24 minutes: a CI shard of its own | #147 | PROSE ONLY (CI layout; plan G9) |
| L53 | `emit_baseline.json` was last saved at P8a, so a `--check` against it differed everywhere and proved nothing (a claimed identity was UNVERIFIED) | handoff-e1m2 5 | PROSE ONLY: re-freeze the baseline at the merge base in a clean worktree before `--check` (the tool cannot know which commit it should match) |
| L54 | an E1M2 S1 door switch's latch is not kept: its doors must be open-stay | handoff-e1m2 11 | SURVEY guard "door switches (SR 63 / S1 103)" (`switch_door_triggers` asserts) |
| L55 | a closing door some box fits inside needs a centre-inside test doorcode does not run | handoff-e1m2 11 | SURVEY "closing doors a box fits inside" (REFUSED: E1M4 102) |
| L56 | one teleport per move: a destination within a teleport line's reach | handoff-e1m2 3; `teleport.check_one_per_move` | SURVEY (the filtered World refuses; now visible in the matrix: **E1M7 line 516's destination within line 52**) |
| L57 | (C4) the movers' READERS refused only at emission: `projcode.missile_rows` ("lift line shuts a missile": E1M3 261, E1M4 1933), `lootcode.nukage_lines` (any mover inside the UNION box of every damaging sector: E1M3 mover 4, E1M4 63) -- 30 minutes into an emission each | m8-c-movers | SURVEY **NEW** (`Survey._readers`: missile cells, nukage vs the movers, sight segments, sound edges, the dynamic pairs through `line_states`); FIXED: a lift line is shut below a pass state like a door's; only an INSTANT floor group is kept apart, per damaging sector |
| L58 | (C4) a NEW mover makes a NEW two-cell line: E1M6's 20 / 22 pool (142) beside SR lift 363 -- its collision floor needs both cells | m8-c-movers | SURVEY (`collision.mover_line_states` row: REFUSED until fixed); FIXED: `collision_cells_fj`'s PAIR dispatch, `monstersight.line_states` answers by the readers' thresholds; TEST `tests/fj/test_episode_movers_fj.py` (the pair dispatch vs the model, 2 mutants) |
| L59 | (C4) a damaging sector can BE a mover (20 / 22 clear the special): every "a mover is never a hurt sector" assert becomes a rule (damage until the group fires) | m8-c-movers | EMIT (`lootcode.nukage_clear_lines` + `nkgrp`; asserts the S1 line's box apart from the sector); TEST tests/fj `test_the_nukage_clear_is_the_models` + 2 mutants |
| L60 | (C4) the seg gate was `hex.if0` (shut EXACTLY at state 0): a lift shut while near its top, or a door in front of a lift, was refused | m8-c-movers | EMIT `wall_renderer.seg_shut_gate` / `dual_gate_lines` (one rule: the survey calls it); TEST `test_level_lessons.py::test_shut_gate_is_the_emitters_rule` |
| L61 | (C4) a lift whose low equals its high (E1M3's 180: its tag's other sector is its only lower neighbour) ran the door machine with ONE state -- its closing step wrapped state 0 to 15 in fj; no survey row or emission would have shown it, only a running harness | m8-c-movers d34ba15d | EMIT/MODEL (`movers.lift_sectors` drops it: it never moves); TEST `test_episode_movers.py::test_every_lift_has_two_states` (E1M1..E1M9), tests/fj `test_the_tic_is_movers[E1M3]` (found it) |

## 2. E1M1's gameplay lessons (M7) a new level's features can hit again

| # | what happened | evidence | where it lives now |
|---|---|---|---|
| G-01 | blocked41 NullIP: `rec_seen_mark`'s `hex.write_hex` armed the pointer library outside the hot window; arm5 moves five hexes only | gp-ledger P3.2a | the re-arm rule in `frame_render.fj` / `selfreset.py`; TEST (the record harness runs the mark with the flags a window away); BUILD `hot_window_violation` |
| G-02 | blocked42 looped: `--pin-state-cells` pre-arms every cell at its reader's base; a pointer write left a redirect bit in `thseen` | gp-ledger P3.2a | the pin veto; TEST `test_monstercode.py`, `test_pin_veto.py` |
| G-03 | a built binary that presents no frame wastes every gate after it | gp-ledger P3.2a | GATE `scratchpad/12m/_smoke_frames.py` before any gate (under a timeout) |
| G-04 | blocked44 r0 / blocked52 r0: the program ran into the table pool (the counting pass lays code out unrelocated; one tic inlined 8,056 compares) | gp-ledger P3.2b, P8a | BUILD (the assembler refuses; the pool base moved to 0x80000000) |
| G-05 | the reset asserted the persisted `sshead` was still in the set it had removed it from (P1.5) | gp-ledger P1.5 | BUILD (selfreset); EMIT `reset_check` |
| G-06 | the P4 re-key stopped at `m5_setfile`: the standalone restore set lacked the screen's persisted cells | 3bfe5ed, 02993d7 | TEST `test_restore_set_shipped.py` (every `persist_labels` name) |
| G-07 | `init_screen` ran every frame (the M1 reset re-enters at `__hot_end`), blanking the bar | 7dd242a, fc11467 | boot-only code in the entry part; PROSE ONLY as a check (a review rule for new boot-time code) |
| G-08 | the probe's hand-kept READ list missed every P4 cell: p2a FAILED with pixels exact | f045865 | GATE (the probe reads every game cell) |
| G-09 | a dead player's number keys changed `wp_pend` | 45441c4 | TEST `tests/fj/test_weapon_fj.py` (`deadkeys` mutant) |
| G-10 | `combat._player_move` compared a MASKED candidate with the SIGNED position (negative coordinates) | a1da51a | TEST `tests/fj/test_player_move_fj.py` (`still_signed` mutant) |
| G-11 | `monsters.walkover_segments` split a walk at y -416 at 65120 (unsigned vs signed 16.16) | 8ae4459 | GATE p2a S7 / S12 |
| G-12 | `dr_live` decremented twice: two packages wrote one cell | bb2c516 | PROSE ONLY: one writer per cell is a review rule (no tool lists a cell's writers) |
| G-13 | `mh_prev` never restarted; P5's restart RESTORED `pal_cur`, a device shadow | 0ce1cf1 | TEST `tests/fj/test_restart_fj.py`; `restartcode.DEVICE_SHADOWS` |
| G-14 | P8a: blood's `fx_spawn_leaf` ran the shared `mm_octant` and clobbered `mm_fa` (the shooter's facing) | 3c6dc06 | TEST `tests/fj/test_monster_hitscan_fj.py` (`facing_lost` mutant) |
| G-15 | P8a: `barrel_parts` emitted `bl_los` without `fight=`: a blast saw through door 145 | 0c8a93c | TEST `test_barrelcode.py::test_barrel_parts_wires_the_blast_los_in_its_own_mode` |
| G-16 | P8a: `pt_thing` kept the pool window across `dm_go`: a fireball's kill linked a drop wrongly | 99609f3 | TEST `tests/fj/test_fireball_pool_fj.py` (`window_lost` mutant) |
| G-17 | why G-14..G-16 hid: every fj harness stubbed `dm_go` as a print; the production `*_parts` wiring never ran; B0's chance octants agreed | gp-ledger P8a; #125 | PROSE ONLY (#125): a stub must do to the shared registers what the callee does -- no tool compares a stub's clobbers with its callee's |
| G-18 | the census drew live monsters as SCENERY: `DRAW_ACTOR_TYPES` was derived at import, the census patched only `MONSTER_TYPES` | bc25935 | TEST (its recalibrated control); the same trap for emit_check's stand-ins (L26) |
| G-19 | `sight.SeenHook` drew the World's 160x100 view, not the game's 84 rows | 9ff90a4 | TEST (pinned to the binary's flags) |
| G-20 | the model exported a rocket's `pj_src` as 1, the binary stores 0 | 5489ddc | GATE fight R1-R3 |
| G-21 | `heat_rekey.py` overwrote its rename record; pinreport left a pinned word UNRESOLVED | gp-ledger P3.1 | TOOL (R9 control in `heat_rekey`) |
| G-22 | any change to the table counts re-rolls the blocking pass's pins: three builds cut 25% of ops and measured SLOWER | ship-gate 2-3 | GATE msframe (class S: B SLOWER never ships) |
| G-23 | the deg_gate op-count criterion was mis-specified for a rung that adds things to the map | gp-ledger P9 | PROSE ONLY: declare kill criteria per rung (a rung that adds things moves deg_gate's ops; attribute them) |

## 3. Process lessons: the episode plan's gaps (`docs/episode-plan.md` 11) and the rules learned

| # | gap / lesson | where it lives now |
|---|---|---|
| G1 | the lock ordered only heavy jobs; light tests during a ~17 GB build can kill it silently | TOOL `heavy.py --build` marks a build; `heavy.py NAME --light -- ...` waits while a BUILD holds the lock |
| G2 | no priority: ~14 agents x one emit_baseline (~33 min) can starve the critical path | TOOL `heavy.py --prio N` (integrator 8, C1 9, the E1M7 probe 7, the rest 5); emit_baseline once per agent, at its end |
| G3 | 14 branches over the same core files, each proving E1M1 identity alone | PROSE ONLY (the integrator's merge order + `emit_baseline --check` + E1M2's part hashes + `emit_check` per wave map after each batch) |
| G4 | C2 (wide thing lists) had no owner | PROSE ONLY (assigned when C1 lands) |
| G5 | the 22M binding-speed cap per level (E1M2 at 20.6M; E1M4 / E1M6 / E1M7 larger) | GATE `gamespeed` per level; a level over 22M is reported, never shipped silently |
| G6 | 2^27 words is the hard limit and every new sprite may grow every map's bank | PROSE ONLY (each sprite-adding agent reports words per map; the integrator re-measures E1M2) -- the SURVEY's pool projection (L19) is the cheap first look |
| G7 | E1M7 may not fit 2^27 or build in this RAM | SURVEY **NEW** (L19 / L20): E1M7 pool 157% at spread 1, ~32.8 GB projected -- WARN both; the C11 emission probe measures it |
| G8 | disk: C: 96% full; each build writes ~0.3-0.5 GB; 46 worktrees | PROSE ONLY until `heavy.py --build` refuses under 15 GB free (to add) |
| G9 | CI near the 6 h job cap | PROSE ONLY (short fj tests, `slow` markers, shards re-balanced per wave; L52) |
| G10 | each level's sets need the owner's approval: 7 interruptions | PROSE ONLY (one approval request per wave) |
| G11 | where a level starts from was undecided | DECIDED: a PISTOL START per binary (the plan, 11) |
| G12 | the playthrough gate's cost and skill are unknown | PROSE ONLY (measured on E1M1 / E1M2 by the playthrough agent) |
| G13 | the profiling tools are E1M1-shaped | PROSE ONLY (profx / heat `--map`: the gate-tools agent) |
| G14 | features meet only at the level gates (a lost soul through a blaze door) | GATE (generated combat sets include each map's new monsters / weapons); EMIT per wave map |
| G15 | per-map fixture wads are missing for E1M3..E1M9 | TOOL `tests/fixtures/make_e1m1_wad.py E1Mn` (the gate-tools agent) |
| G16 | PR #148 unmerged under `m8-episode` | PROSE ONLY (merge on green first) |
| G17 | an agent can stop mid-work | PROSE ONLY (push in steps; the integrator re-launches from the pushed branch) |
| P1 | ONE heavy job at a time: two E1M2-sized assemblies are 2x the box's RAM; a subagent's heavy run is a heavy run | TOOL `heavy.py` (the lock; `Documents/HEAVY.lock`) |
| P2 | "the build printed its results" is not "the build released its memory" | PROSE ONLY (CLAUDE.md rule 1: check the process is gone) |
| P3 | never assemble with asserts off (L24) | EMIT (refuses -O) |
| P4 | a verification tool used as evidence ships a negative control (R9); a control that compares a mutant with the same function's output is vacuous (#145 F8) | TEST discipline (`docs/cr-rules.md` R9); every row added here has one in `test_level_lessons.py` |
| P5 | prove an fj layout by RUNNING fj, never a Python model of fj ops | the brief, rule 4 (tests/fj harnesses + mutants) |
| P6 | a guard that adds a row only when it refuses makes "row present = OK" tests vacuous (CR of #142 item 9) | SURVEY: the new checks write an OK row when they pass (`collision.mover_line_states` included) |
| P7 | a number quoted from a doc is UNVERIFIED until re-measured (E1M2's pool projection was 75-85M; the census said 90.3M) | PROSE ONLY (CLAUDE.md "Performance Claims"); the survey's projections say ESTIMATE and name their source builds |

## 4. What the new checks find on the coming maps (2026-10-19, `--matrix E1M3 .. E1M9`, assets/freedoom1.wad)

| map | finding (the row) | the lesson that caught it | owner |
|---|---|---|---|
| E1M3 | ~~REFUSED: 5 dynamic segs the renderer cannot gate -- 515 (shut at states 0-4 of 105), 519 (door 106 + mover 105), 827, 1077 (door 213 + mover 163), 1314~~ FIXED (C4: the mask gate, the door + mover pair) | L35 / L12 / L60 | C4 |
| E1M3, E1M4, E1M6, E1M7, E1M9 | WARN: plane pairs 249 / 237 / 328 / 545 / 264 -- `PID_NIBBLES 3` in MAP_CONFIG likely | L08 | the level rung (MAP_CONFIG) |
| E1M3, E1M4, E1M9 | pool at spread 2 110% / 129% / 117%: build at `--spread 1` (E1M5, E1M8: spread 2) | L19 | the level rung |
| E1M5 | WARN (if SECTOR_LIGHTS on): a fire flicker in sector 31 with maxlight 256 -- a light state past the byte | L43 | the lights, if E1M5 gets them |
| E1M6 | ~~REFUSED: 2 segs (1254, 1348: shut at states 0-7 of 182)~~ FIXED (C4); pool 100% at spread 1 (at the edge); RAM ~20.8 GB projected | L35, L19, L20 | the E1M6 probe |
| E1M6, E1M7 | the filtered World refuses: "leaf lists store mobile index + 1 in a byte" (was hidden by the matrix) | L29 | C1 / C2 |
| E1M7 | the filtered World refuses: line 516's teleport destination (1568, 1312) lies within line 52 (one teleport per move; was hidden) | L29, L56 | C5 (teleports) |
| E1M7 | REFUSED: 7 segs (269, 272, 2579, 3461, 3469, 3489, ...); pool 157% at spread 1 and ~32.8 GB RAM projected (WARN both); two exit switch lines (WARN if SWITCH_TEX) | L35, L19, L20, L43 | C11's feasibility probe; C9 |
| E1M8 | ~~WRONG: NEW GAME keeps the floors moved -- 3 floor groups, 0 lifts~~ FIXED (C4: `restart_lines(nfloor=)`; the model's restart already reset them) | L36 | C4 |
| E1M8 | REFUSED: the cell charge pack (17) is a World pickup with NO sprite art -- never drawn, and the oracle's thvis mirror raises KeyError (every gate on E1M8 would crash) | L17 | C6 (pickups: the plasma rifle's ammo) |
| E1M7, E1M8 | WARN: slanted W1 floor lines 3760, 894 -- play-test their crossing | L39 | the playtests |
| E1M9 | ~~REFUSED: 12 segs (511, 749, 758, 924, 1856, 1857, ...)~~ FIXED (C4: the mask gate) | L35, L60 | C4 |
| E1M9 | the filtered World refuses: door 135 is asked two motions (plain, stay) | L29 | C3 |
| E1M1..E1M9 | OK on every map: door clearance (L40), ML_TWOSIDED (L42), the neighbour rule (L41), `collision.mover_line_states` (L28); `monstersight.line_states` OK wherever the World builds (E1M6 / E1M7 / E1M9: not run) | -- | -- |

The REFUSED segs mirror `_seg_dual_cell`'s asserts from the model's tables (the same `door_states`, `mover_table`,
`mover_secs` calls as the emitter); E1M1 and E1M2 (both emit) show none. The prediction on E1M3..E1M9 is not yet
confirmed by an emission (each map's World refuses first).

## 5. Adding a lesson

A new mistake gets a row here in the commit that fixes it: what happened, the evidence (commit / PR / doc), and where it
lives. If a computable check over the WAD and the model could have caught it before a build, it goes into
`Survey.lessons` (or `emit_check`) with a host test and a negative control in `tests/host/test_level_lessons.py`;
otherwise the row says PROSE ONLY and why.
