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
