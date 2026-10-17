# F1 -- big-map widths: the design (M8, 2026-10-16)

A read-only design of feature rung F1 (`docs/level-pipeline.md` 6), made while E1M2's size assembly held the machine.
Nothing was run: every op / word figure is an UNVERIFIED estimate to be measured before it is quoted.

## 0. Findings that change F1

1. **Two items are smaller than their survey rows.** The fj side already holds the wider values:
   - attacker ids (`aim_sid`, `sp_sid`, `dm_id`, `p_atk`, `mon_target`, `bar_src`) are TWO nibbles in fj with
     two-level `sim.jump16` dispatches; only the model's schema field (`world.build_schema`: `aim_sid` 7 bits) and
     `hurtcode.turn_lines`' self-imposed `n + 1 <= 0x80` bind;
   - the far LOS loop (`monstersight.far_los_lines`) has NO piece cap: it halves the step until every piece is
     <= PIECE. `FAR_PIECES` appears only in asserts, and `FAR_PIECES <= 1 << 5` is over-strict: the 6-nibble walk
     needs the step's low 16 bits zero (s = d << (24 - h)), exact for N <= 256; `sf_n` (2 nibbles) holds N <= 128;
     `_bounds`' 2^13 needs at most N = 128.
2. **NEW GAME already has per-skill barrel lines** (`barrelcode.restart_lines(w, skill)`, monstercode's per-skill
   `bar_solid`, the per-skill `thvis` and leaf lists). Item 7 is mostly the `check_model_rules` assert and the
   missing `mc_don` cell.
3. **An unlisted cap: runtime thing ids > 254.** The survey's "runtime things" row omits mobiles and drops; the bound
   is `nt + FIREBALL_POOL + FX_POOL + ndrop <= 254` (`monstercode` / `LIST_MAX_THINGS`). E1M3: 240 + 10 + ~87
   droppers = ~337; E1M4 and E1M5 similar. Ids live in the byte leaf lists (`sshead`, `thnext`, `mob_next`), the
   2-nibble `sp_ti` row select and `TD_KEY_ROWS`. **Item 12, with its own design before F1.3 ends**; the survey must
   compute the full sum now.

**E1M1 stays byte-identical by one of three mechanisms per item:** (a) the text is a function of map facts that are
the same on E1M1 (one switch group, no skill-dependent decor, >= 1 barrel, totals <= 99); (b) hand-written fj switches
on a Config constant via `fj_consts.fj` and `rep(X, k)` (the `SLOT_BIT` precedent: X = 0 on E1M1); (c) a model rule
that cannot apply on E1M1, asserted at emit time. Proof after every sub-rung: `scratchpad/cr/emit_baseline.py --check`
(+ `--selftest`); `deg_gate` when the oracle's renderer changed. Recommended new cheap tool before F1.2:
`scratchpad/cr/model_digest.py --save/--check/--selftest` (E1M1's World on the frozen v10 scripts, the WorldState
digest every tic; R9 control: `BOMB_DAMAGE += 1` rejected).

## 1. Fragment slot ids past 255

A slot id is a **per-frame** counter (`gps_nslot`, incremented per ACCEPTED thing, zeroed every frame), written as
fragment byte 0 and read by `frame.lines_spr_load` and `stream.frag_derive`. The true bound is "things accepted in one
frame"; `check_slot_ids(len(_drawable))` is sufficient, not necessary, and omits the runtime pools.
- **A. two-byte ids** (high bytes in the free bytes 12-14 of the 16-byte column slot): hot path per column, est.
  +0.3..0.8 M ops/frame, +20..40 k words.
- **DECIDED (the owner, 2026-10-17: "Go with your way"): B.** The accepted-count sweep is still measured and recorded
  with F1.4, as the cap's evidence.
- **B. (recommended) a per-frame accepted-thing cap of 255, mirrored in the oracle** -- DOOM's own rule
  (MAXVISSPRITES = 128 drops the rest), front-to-back so only the farthest drop; a hard budget mirrored like
  `THING_BUDGET` / `MONSTER_BUDGET`. **Needs the owner's decision** (it conflicts with "monsters always shown" when a
  frame accepts >= 255); show it with the accepted-count sweep. A is the fallback.
Change (B): `Config.SPR_SLOT_CAP` (0 = no cap, asserted < 256) + `SPR_SLOT_CAP_ON` in the fj consts, `MAP_CONFIG` 255
for E1M2/3/4/5/9; `check_slot_ids(n_drawable, n_pools, n_drops, cfg)` (fan-out); in `frame.thing_record_body` a
`rep(SPR_SLOT_CAP_ON, k)` compare of `gps_nslot` against the cap before the scenery budget (a capped-out monster takes
`seen_probe` as a budget-failed one does); the oracle's `render_wall_frame` an `n_slots` counter at fj's increment
point, ORed into both hard-budget tests. Proof: `test_slot_layouts_fj` with cap 4 in a room of more things; controls:
oracle cap 5 vs fj cap 4, and the fj compare moved after the increment. Est. 40-60 ops per thing reaching the record
body. Half a day + the sweep + the decision. Retires `slot-ids`.

## 2. Attacker / thing ids past 7 bits

`world.build_schema`: `aim_sid` width `max(7, (nmon + nbarrel).bit_length())` via one helper `aim_bits(lay)` the
survey calls too; `hurtcode.turn_lines`: `n + 1 <= 0xFF`; new emit-time guards on the 8-bit fj cells
(`monsterdecide.scan_lines` `2 + nmon + nbar - 1 <= 0xFF`, the baked/runtime barrel stubs `1 + nmon + b <= 0xFF`,
`world._code_bits` `nmon + 2 <= 256`); the survey's literal 127 -> the schema width. E1M1: 7 bits kept, text unchanged.
Proof: `test_death_turn_fj` parameterized to 190 slots, ids from all 12 high groups; control: the stand-in's
`slot_rows[:0x7E]` must part on an id >= 0x80. ~3 h. Retires `attacker-7bit`.

## 3. LEVEL COMPLETE counts past 99

One width for both mirrors: `statcode.count_digits(w) -> 2 | 3` (3 when any skill's totals or the monster slots
exceed 99; cells stay 8 bits, <= 255 asserted). `menu.level_done_rows(nsecret, digits)`, `stats_digits` with a
3-digit form (blank hundreds, blank tens when hundreds are 0), `level_done_layout/_stream/_digit_records(digits)`,
and an assert that the block fits the screen (a `max(0, ...)` clamps silently today). `statcode`: `digit_slots(d)`,
`_split3_lines` (two `lvd_dec`s), `_digit_set_lines(digits)`, `digit_lines`/`frame_lines` by `count_digits`; the
oracle's `stats_of` the same width. E1M1: 2 digits, text unchanged. Proof: `test_level_done_fj` 3-digit case (0, 9,
10, 99, 100, 109, 110, 189, 255) + `test_menu` decode; controls: hundreds never blanked; a 2-digit template on a
3-digit World refused. Half a day. Retires `stats-digits`; add a survey row for COUNTITEM items.

## 4. Far line of sight past 32 x 127 units

`FAR_PIECES = 128`; the line-447 assert -> `FAR_PIECES <= 1 << 8` and `< 256` with its comment corrected;
`far_margin` asserts `ext <= FAR_PIECES * PIECE` and `ext < 1 << 13`; the survey's 4064 ->
`min(FAR_PIECES * PIECE, 8191)`. No emitted text uses FAR_PIECES: E1M1 unchanged. Proof: `test_far_los_fj` on E1M2
(4,952 wide, N = 64 needed; a test that some sample reaches 64 pieces); new control "walk5" (a 5-nibble add, exact
only for N <= 16) must part. Est. +5..10 k ops on the longest checks, 0 words. ~3 h. Retires `far-los`.

## 5. Lifts with more than 16 stops

Widening `l_state` (every reader a two-level dispatch, 19 blocks a seg) is rejected. **Per-lift quant:**
`movers.lift_quant(low, high, base)` = the least q >= 16 giving <= 16 stops; every caller reads `lift_states`, so
model and fj cannot drift; `doors.geometry_stamp` records `lift_quant` only where q differs. The lift then crosses
its travel in <= 15 frames (~1.2x faster) -- a simplification to record in handoff-e1m2 3. E1M1's lifts fit at 16:
unchanged. Proof: host `lift_quant` on synthetic travels + E1M1 frozen stops + E1M3/E1M4 <= 16; `test_movers_fj`
q = 20; control: q = 16 forced is refused, not wrapped. Half a day.

## 6. Maps with no barrel (E1M5, E1M8)

The rocket's blast reuses `bl_leaf` / `bl_mon10` / `kbbz` / `bl_los`, so the barrel package stays and becomes total
over nbar = 0: asserts `0 <= n <= 255`; `blast_los_lines` with n = 0 (the `bl_b` dispatch all `bl_ldone`); widths
`nib * max(1, n)` (restart_lines' `hex.set` too); phase/damage/shot lines emit entry + fret; `kbbz` and `aimcode`'s
`barrels=` a one-row placeholder. E1M1 (n >= 1) unchanged. Proof: `test_barrel_fj` / `test_rocket_fj` with no
barrels; `test_emit_every_tier` on a no-barrel World; control: `bl_b`'s targets swapped. Half a day.

## 7. NEW GAME per skill: barrels (7a) and `mc_don` (7b)

7a: delete `check_model_rules`' per-skill equality; assert `things.skill_level_start` filters runtime barrels by
skill as `World._reset_state` does. 7b: in monstercode's chase branch replace `assert not var` with the decl
`mc_don: hex.vec len(var), <decor_presence(boot)>`, a per-skill `hex.set` in each skill's block, `mc_don` persisted
only when `var` is non-empty (`build.persist_labels(extra=)` fan-out, or the parts dict's `"persist"` as barrel_parts
does), registered in the reset registry and `probe.game_cells`. E1M1 unchanged (barrels equal across skills, `var`
empty). Proof: `test_restart_fj` parameterized by map (E1M2 with other rungs' stand-ins): COVERAGE (every persisted
cell written by every skill) + VALUES vs `World._restart`; controls: the `mc_don` line dropped from easy; the easy
barrel block replaced by hard's; `mc_don` left out of persist (`test_restart_coverage`). Half a day. Retires
`barrels-one-skill`, `decor-every-skill`.

## 8. Barrel chains a dynamic line touches

`chain_pairs` returns `(c, damage, dyn)`: a static segment touching the trace drops the pair; only dynamic segments ->
`dyn`. For a `dyn` pair the chain calls the EXISTING `bl_los` (trace barrel b -> barrel c) and skips on `sl_hit` --
valid because b's spot list covers `blast_margin`, `segments_touch` is symmetric, and the dynamic blocks read the same
cells as `sight_segments`. E1M1 has no `dyn` pair: unchanged. Proof: `test_barrel_fj` on an E1M2 `dyn` pair with the
door/lift open and shut (or a synthetic E1M1 barrel across door 145); controls: the `bl_los` call removed; the test
inverted. Half a day. Retires `barrel-chains-static`.

## 9. A pickup on a door or mover floor

A door's floor never moves (static z right, only the assert wrong); a mover's does (P_ChangeSector carries the item).
Model: `pickup_on_mover[i]`, `_touch_specials` reads `_floor_at` for those. fj simulation: mover pickups' stubs call a
shared `pk_mbox` (pkxyz x/y, `ptss` = the pickup's leaf, `ms_seed_leaf`, `pk_tz` from `cp_seedf`, `pk_boxz`).
**fj render -- a real bug the stand-in hides:** a BAKED thing bakes `sp_z` from the stored floor while the oracle draws
it at the current one; `things.baked_thing_mask(..., mover_leaves)` must make mover-leaf things runtime, through ONE
helper `things.mover_leaves(w)` every caller uses. E1M1: a host test that its mask is unchanged (if it fails, an E1M1
thing stands on a lift today -- a class F fix with its own record). Proof: `test_pickup_fj` on E1M2's card before
and after the switch; control: the static z read must part after the switch; the render half under deg_gate in F1.4.
One day. Retires `pickup-static-z`.

## 10. Floor switches per tag

`movers.switch_sectors` gains a group (the tag's index); schema `f_switch` counted only when groups > 1 (E1M1's
schema identical); `mover_heights(switched=set of groups)`; `MoverPhase.sw` a bitmask. fj: ONE helper
`movers.switch_cell(g)` (`"fswitch"` for g = 0) for `closed_states`, `world_cell_inputs`, `_seg_cell`/`_msecs`,
noise/proj/collision, `movercode.use_line_lines` (`fs_hit<g>`); `fswitch: hex.vec max(1, ng)`. **Measure first:** if
E1M2's 10 switch-switch lines join DIFFERENT groups they become two-cell lines, refused by sight/noise/missiles/
collision (the renderer's pair switch handles them) -> sub-item 10b (a two-cell shut set over the 2x2 states, two
nested `hex.if_flags`), +0.5..1 day. Proof: `test_movers_fj` two groups; sight/noise on E1M2 in all four
combinations; controls: every `switch_cell` -> "fswitch"; `fs_hit<g>` wired to group 0. One day (+10b).

## 11. A walk-over tag opening two doors

**MEASURED 2026-10-17 -- larger than designed:** E1M3's tag 11 is SIX W1 lines forming a closed ring (linedefs 547,
571, 593, 602, 1570, 1574 around (404..468, 2576..2640)), two of them SLANTED (571, 593), opening doors 82 and 83. One
entry per door with one shared segment is not enough: each LINE is its own trigger (DOOM's W1 per line), with a
slanted crossing test in the model (`doors.crossed`) and the fj (`doorcode.walkover_lines`) -- the same machinery F2
builds for slanted door lines (`'d'` lines). Move item 11 to F2 (doors), with the per-line triggers.


`doors.walkover_triggers` returns one entry per target door with the same segment (`w_fired` one bit per entry,
everything downstream unchanged; both fire in the same call = EV_DoDoor on every tagged sector); optionally fuse
identical segments in `doorcode.walkover_lines`. E1M1 unchanged. Proof: `test_doors_p2a_fj` on E1M3's tag 11 (or a
synthetic two-door tag); control: the fused fire setting one door only. ~3 h. Check the lifts' twin
(`lift_walk_triggers` one target) in the survey too.

## 12. Order: four sub-rungs

| sub-rung | items | gates beyond host + the new tests/fj | stand-ins retired | effort |
|---|---|---|---|---|
| **F1.1 widths, no rule change** | 2, 4, 3 (+ the survey's literals -> module constants) | -- | attacker-7bit, far-los, stats-digits | ~1 day |
| **F1.2 barrels and skills** | 6, 7, 8 | `model_digest --check`, `test_restart_fj` E1M1 + E1M2 | barrels-one-skill, decor-every-skill, barrel-chains-static | ~1.5 days |
| **F1.3 movers and triggers** | 5, 10 (+10b), 11, 9-sim | `model_digest`; tests/fj movers/doors/sight/noise on E1M2/E1M3 | pickup-static-z (sim half) | ~2-3 days |
| **F1.4 the picture** | 1, 9-render | `deg_gate` (E1M1 byte-exact, ops to the digit); `test_slot_layouts_fj` with the cap | slot-ids, pickup-static-z (render) | ~1.5 days + decision |

Every sub-rung ends with `emit_baseline --check` (+ `--selftest`), the survey matrix re-run and `emit_check.py E1M2`
with the retired stand-ins removed (heavy: one at a time). Ask the owner the slot-cap question at F1.1's PR.
**Total ~6-8 days, before item 12 (runtime ids past 254, ~2-3 days).**

## 13. Pipeline changes this assumes

- a `standins` pytest fixture (importing `scripts/emit_check.STANDINS`) so an F1 harness can run on E1M2/E1M3 before
  F2-F4; a harness using one prints which;
- survey: `nt + FIREBALL_POOL + FX_POOL + len(droppers(w))` vs 254 (item 12), a COUNTITEM row, "switch-switch lines
  across groups" (10b), the lifts' WR multi-target check (11), the per-lift quant (5), the slot-cap requirement (1);
- item 12's own design note before F1.3 ends (3-nibble ids in 2-byte list cells behind a Config width, or a smaller
  drop pool -- less faithful: DOOM has no drop limit).

Critical files: `src/fj/frame_render.fj` (`thing_record_body`), `src/doomfj/reference_model.py` (the oracle's
hard budgets), `barrelcode.py` (6, 7a, 8), `movers.py` (5, 10), `doors.py` (11), `world.py` / `combat.py` (2, 9).
