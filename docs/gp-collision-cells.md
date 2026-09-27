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

## Cost (MEASURED by the S6 harness, not yet in game)

`sim.check_cells` over the emitted E1M1 routine, 256 walkable positions, every iteration's
verdict checked against the oracle (`scratchpad/gp/probes/s6/fjprobe.py`, ship pool knobs):

| sample | plain | ship pool |
|---|---|---|
| 256 walkable positions (mean 0.92 listed lines) | 20,755 | **11,519** |
| cells with no line (the fixed part: box, tree, epilogue) | 5,848 | 2,226 |
| cells with lines (mean 1.90) | 31,979 | 18,101 (~8.4K a listed line; diagonals dominate) |

Against 576K a check. The seed walk (`dsccs_walk`, 35.4K a try) is unchanged and now the larger
part of a try; the cells' start node could replace it (plan 6.3's point-location item), which is
left for when P3 needs point location for monsters.

## As built

(filled after the build: the binary, the gates, the ledger row, size, the pin report.)
