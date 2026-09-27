# M7 P1.2 -- the player's collision cells

The handoff's rung P1.2 (`docs/handoff-gameplay.md` section 10, plan section 6.3): the player's
`check_position` stops walking the blockmap through packed tables and runs a precomputed CELL.
Class S: the same pixels and the same trajectory, cheaper. Kill criteria: `docs/gp-ledger.md`.

## The problem it removes

M14-d's `sim.check_position` walked the 256-unit blockmap: each of the box's four corners indexed
a block (`bkoff`), walked its line list (`bklin`, ~20 lines), and read every candidate's row from
packed tables (`lnbox`, `lnrow`) with `hex.read_table_packed` -- ~6.8K ops a line, **576K ops a
check**, MEASURED on blocked27 (`docs/plan-gameplay.md` section 3). A player move checks the
standing position and up to three candidates, so collision was **1,475,186 ops/frame on
gamespeed's 10 games -- 9.7% of the frame**, the largest non-render cost.

## The design

**Cells.** 32 map units (`collision.CELL_SHIFT = 21`: `floor(c16 / 2^21)` of a 16.16 coordinate).
`cell_lists(rows, radius)` lists, per cell, every linedef whose bbox a box of the player's radius
centred ANYWHERE in the cell does not reject:

    check_position's reject:  right <= minx  or  left >= maxx  or  top <= miny  or  bottom >= maxy
    a centre escapes the x half  <=>  x in the OPEN interval (minx - r, maxx + r)
    a cell xa..xb has one        <=>  xb > minx - r  and  xa < maxx + r        (and the same in y)

The two halves are independent, so this is EXACT, not conservative: every listed line is touched
by some box in the cell, and every unlisted one is rejected everywhere in it. A candidate list that
contains every line the bbox test can pass cannot change a verdict -- the rest of PIT_CheckLine
only ever runs on lines that pass it. So the cells give the oracle's all-lines answer by
construction; they are not an approximation of the blockmap.

On E1M1 (freedoom, 1,175 linedefs): **6,052 non-empty cells, 1,760 distinct lists, 11,667 (cell,
line) pairs, mean 1.93 lines a cell, max 13.**

**The routine** (`collision.collision_cells_fj`, emitted into the walk part):

1. A TREE of `sim.jump16` on the centre's hex nibbles 7, 6, 5 -- x first, then y -- reaches the
   cell's stub in six 16-way jumps. The nibble split resolves 16-unit steps; both halves of a cell
   jump to the same place. Identical subtrees are shared (hash-consed): **1,118 nodes**. A position
   in no listed cell lands on `_none`, which is exact for the same reason the lists are.
2. A CELL STUB per distinct list `stl.fcall`s one LINE STUB per listed line.
3. A LINE STUB `hex.xor_by`s its row's constants into the argument cells (`ca_*`, `CELL_DECLS`),
   calls the ONE shared `sim.line_test`, and xors them out again. It xors only what its path reads
   (`collision.line_constants`): the bbox always; v1y for a horizontal line, v1x for a vertical
   one, both plus the sign-extended deltas for a diagonal; the slope and static flags; the opening
   only for a line that can be passable. An xor of a constant is one op per set bit, and every
   argument cell is zero between lines.
4. `sim.line_test` is M14-d's PIT_CheckLine with the table reads and conversions gone -- every value
   arrives in its working form.

**A wall latches.** `sim.line_test` runs two calls deep, and both return registers must unwind, so a
wall cannot jump out: it sets `cp_ok = 0` and returns, and the cell's remaining lines still run.
`sim.check_cells` then restores the SEED openings when the latch is set -- exactly what the old
jump out did, and the verdict is order-independent (a latch, and max/min for the openings).

**Doors.** A door's lines bake their opening OPEN (M2-R4, unchanged). Their blocking used to be a
bit in `lnrow`, patched with a `wflip` on the two animation steps that cross `doors.pass_state` --
a second copy of the door's state, kept alive across the M1 reset only by staying out of the
restore set. Now a door line's stub reads `dstate` when the line is tested:
`hex.if_flags dstate + slot*dw, <the states below the pass state>, go, shut`, and the shut path
xors FLAG_BLOCKING in around its call. A line on two doors (between two door sectors) chains one
test per door and refuses while EITHER is shut, which is the oracle's union (`blocked_lines`); the
old xor patch would have cancelled there. No E1M1 line is on two doors. The door tic writes only
its own registers now, and the hosted M2 gates relay only those.

**Placement.** `sim.jump16` is declared SAFE in `build_blocked.py`'s `SAFE_TABLE_MACROS` (the
handoff's rule 5): its `pad 16` table is jump-only, and undeclared the pool pins the cell instead
(S6: 137 ops for six levels against 46).

**The reset.** `CELL_DECLS` (the argument cells and three return registers) are zero at every stub
exit and are not in the restore set -- as `cs_ret`, the seed descent's return register, never was.
They are declared LAST, after `CHECK_SCRATCH_DECLS`: the restore sets fingerprint the spans of the
labels they name, and nothing may land between those. The retired walk's scratch (`cb_*`, most
`cl_*`) was dead but stayed declared, because both shipped restore sets named it; M7 P1.4 re-keyed
the sets against its own label table and dropped it (`CHECK_SCRATCH_DECLS` is `cl_side1` /
`cl_side2` now). Until then it cost the reset ~41 ops a nibble.

## Exactness -- what proves it, and the controls

| claim | test | control |
|---|---|---|
| every line a box in the cell can touch is listed, and nothing else | `test_collision_cells.py::test_every_line_a_box_in_the_cell_can_touch_is_listed` -- an unlisted line must be rejected at all four corners (sound while the box is at least a cell wide, which `cell_lists` asserts) | one needed line dropped from one list is named, exactly |
| the Python model is the oracle | `test_the_cell_model_is_the_oracle` (random, fractional, cell corners, off the map; doors shut and open), `test_a_door_line_follows_its_doors_state` (every door state, others random) | the sample holds 300+ refusals; door lines must change verdict with their door |
| the emitted text is the model | the tree walked by an interpreter of its own text for four points of every cell; every stub's xors balanced; each stub's xors spell `line_constants(row)`; door stubs read their own door | a swapped tree target and a dropped xor are both caught |
| the emitted fj is the oracle | `tests/fj/test_collision_fj.py`: the E1M1 routine assembled (5 s) and run on ~700 positions, door states, a walk and try_move -- all in ONE image per test, so a dirty argument cell or return register would corrupt the next call | refusals required; door verdicts must move; a routine missing one line is assembled and caught |

## Cost (MEASURED in game)

On gamespeed's ten games (profx, `docs/ship-evidence/blocked29_phases.log`): collision 122,218 ops a
frame at 2.40 player tries a frame -- a try 50,818 ops, of which the unchanged seed walk
(`dsccs_walk`) is 31,838, so the cell routine with `sim.try_move` around it is ~19.0K a try,
against 576K a check before (MEASURED on blocked27, above). The seed walk is now the larger part of
a try; the cells' start node could replace it (plan 6.3's point-location item), which is left for
when P3 needs point location for monsters.

One line, before the build (`python scratchpad/gp/probes/s6/probes.py line`, exact executed-op
deltas, every call verified; `docs/ship-evidence/p12_s6_line.log`): the shared `sim.line_test`
costs 0.5-18.5% more than the same line baked as constants, under the ship pool (L1-L5: 282 vs 238
... 16,019 vs 15,912 ops) -- the price of one shared test instead of a stub per line. (A whole-routine
estimate from an uncommitted probe stood here until PR #91's review; the in-game number replaces
it.)

## As built

`build/doom_e1m1_blocked29.fjm`, sha256 `a90f172ee718be63`, from the ship-gate 1b line unchanged (the heat list
is still blocked27's) with a fresh counting pass: the source changed, so the cache recounted (20,835
groups, 337,465 tables, 2,060 s) and the build took 7,894 s. Rebuilt from the same line at the
rebased head, HITting the cache that count wrote: the same sha256 and the same label table
(`blocked29r_build.log`, 4814 s). The row and the verdict are in `docs/gp-ledger.md`.

- **Gates**: m2_std_gate PASS (154 route frames; door 10 through 9 states across the reset; the
  path crosses the door's own line segment, so the door line's stub had to read the door open --
  its `dstate` against the pass state; the old blocking bit is gone), m3_gate PASS
  (`blocked29_gates.log`). gamespeed's trail -- the binary's per-frame pose and door states against
  `--validate`'s own record, all ten runs -- PASS with both negative controls rejected
  (`blocked29_gamespeed_trail.log`): the same trajectories, which is the class-S claim for a change
  that moved the collision code.
- **Ops**: collision fell from 1,475,186 to 122,218 ops a frame on the same ten games (profx
  `blocked29_phases.log`): a try is 50,818 ops, 31,838 of them the unchanged seed walk -- now the
  larger part, as the S6 harness predicted; replacing it with the cells' start node is left for P3.
  The binding fell 1,577,073 (-9.6%).
- **Size**: 36,706,788 words, 27.35% of 2^27 (was 32.21%): the old walk's code and packed-table
  groups are gone -- the inline program is 2,315,650 words smaller and the pool's payload 4,206,720
  (`blocked29_poolmap.log`); the counting pass found 20,835 groups and 337,465 tables against
  blocked27's 32,066 and 432,164.
- **Pins**: 20 of 20 hot words pinned (`blocked29_pinreport.log`); four hot words' labels moved lines
  with the edit, and pinreport now resolves those by their heat key -- the name the pool matched
  them by -- instead of calling them unresolved. 14,198 of the list's 35,894 hot sites matched:
  the rest were the retired walk's.
