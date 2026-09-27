"""M2-R4 — the door state machine and its trigger, as emitted fj.

This is a TRANSLITERATION of `doomfj.doors.door_tic` and `doors.in_use_box`, line for line and
branch for branch. Both mirrors have to walk the same nibble through the same sequence or the
picture diverges on the frame they disagree, so the Python is the specification and this file is
the only place it is written twice. Read them side by side; every label below names the branch of
`door_tic` it implements.

WHY IT IS ALL INCREMENTS, DECREMENTS AND ZERO-TESTS. fj has `hex.inc`, `hex.dec` and `hex.if0`
cheaply; comparing a register against a bound costs a constant register plus a `hex.cmp`. So the
counters run DOWN to zero (`dsub`, `dwait`), and the one genuine bound -- "is the door fully
open?" -- is tested by xoring the last state's value in and asking whether the result is zero, an
idiom that costs two dispatch-free `hex.xor_by`s. An IDLE door with no timer running therefore
costs exactly two 1-nibble tests per frame, which is what keeps 13 doors off the frame budget.

⚠ A TIC IS A FRAME (see `doors.SPEED`): both tiers simulate once per frame.

⚠ THE USE KEY IS LEVEL-TRIGGERED, not edge-triggered. DOOM uses the press edge; holding the key
here just keeps re-triggering, which on an open door means the wait restarts and on a closed one
means it opens. Remembering the previous frame's bit would cost a persisted cell in both mirrors
and one more thing for them to disagree about, and "holding use holds the door open" is a
defensible door.
"""
from __future__ import annotations

from doomfj.doors import CLOSING, OPENING, SPEED, WAIT

# `dwait` counts frames and needs to hold WAIT; two nibbles is 0..255.
WAIT_NIBBLES = 2
assert 0 < WAIT < (1 << (4 * WAIT_NIBBLES)), f"WAIT={WAIT} does not fit {WAIT_NIBBLES} nibbles"
assert 0 < SPEED < 16, f"SPEED={SPEED} does not fit the one-nibble `dsub`"


def door_decls(ndoors: int) -> list:
    """The per-door runtime state. `dstate` is R3's -- the renderer's switches dispatch on it --
    and the three below drive it.

    All four are baked to the level's initial condition (shut, idle, no timers), which is what
    `doors.initial_states` hands the oracle. They are also exactly the cells that must SURVIVE the
    M1 reset in a standalone build: a door that re-shuts every frame is the same class of bug as a
    player who teleports back to spawn."""
    return [
        f"dstate: hex.vec {ndoors}, 0",                  # height index, per door (R3)
        f"ddir: hex.vec {ndoors}, 0",                    # 0 idle / 1 opening / 2 closing
        f"dsub: hex.vec {ndoors}, 0",                    # frames until the next height step
        f"dwait: hex.vec {WAIT_NIBBLES * ndoors}, 0",    # frames left fully open
        "duse: hex.vec 1, 0",                            # the use key, this frame
        "dbox: hex.vec 8, 0",                            # the trigger box compare's constant
    ]


def _box_test(d: int, box, hit: str, miss: str) -> list:
    """`in_use_box` in fj: four signed compares of the 16.16 player position against baked corners.

    The box is axis-aligned precisely so this needs no multiply and no line side test -- see the
    compromise noted in `doors.use_boxes`."""
    x0, y0, x1, y1 = box
    out = []
    for k, (reg, val, want_ge) in enumerate((("viewx", x0, True), ("viewx", x1, False),
                                             ("viewy", y0, True), ("viewy", y1, False))):
        tag = f"dub{d}_{k}"
        out.append(f"    hex.set 8, dbox, {(val << 16) & 0xFFFFFFFF:#x}")
        if want_ge:                    # miss when reg < val
            out.append(f"    hex.scmp 8, {reg}, dbox, {miss}, {tag}, {tag}")
        else:                          # miss when reg > val
            out.append(f"    hex.scmp 8, {reg}, dbox, {tag}, {tag}, {miss}")
        out.append(f"  {tag}:")
    out.append(f"    ;{hit}")
    return out


def door_tic_lines(slots, nstates, boxes) -> list:
    """One frame of every door. `slots` is the emitter's door order (`sorted(door sectors)`),
    `nstates[si]` how many stops that door has, `boxes[si]` its use box in map units.

    Nothing here touches collision: a door's lines read its `dstate` when they are tested
    (`collision.collision_cells_fj`), so the state this walks IS the door's collision too.

    The label prefix is `dr{slot}_`, so the emitted names say which door they belong to.
    """
    out = ["// == M2-R4: the doors, one tic each ==================================",
           "//   dr<d>_*  door <d> (index into sorted(door sectors))",
           "//   the mirror of doomfj.doors.door_tic -- read them together"]
    for d, si in enumerate(slots):
        n = nstates[si]
        last = n - 1
        st = f"dstate + {d}*dw"
        dr = f"ddir + {d}*dw"
        sub = f"dsub + {d}*dw"
        wt = f"dwait + {WAIT_NIBBLES * d}*dw"
        p = f"dr{d}"
        out += [f"  // ---- door {d} (sector {si}): {n} states ----",
                # ---- the trigger: `if used and dr != OPENING` -------------------------------
                f"    hex.if0 1, duse, {p}_moved",
                *_box_test(d, boxes[si], f"{p}_press", f"{p}_moved"),
                f"  {p}_press:",
                # dir != OPENING, tested by xoring OPENING in and asking for zero. The xor is an
                # involution, so both branches put it back.
                f"    hex.xor_by 1, {dr}, {OPENING}",
                f"    hex.if0 1, {dr}, {p}_already",
                f"    hex.xor_by 1, {dr}, {OPENING}",
                f"    hex.set 1, {dr}, {OPENING}",
                f"    hex.set 1, {sub}, {SPEED}",
                f"    hex.zero {WAIT_NIBBLES}, {wt}",
                # ...and `if state == nstates - 1` on a press: an already-open door goes back to
                # IDLE with a full wait rather than trying to open past its last state.
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.if0 1, {st}, {p}_pressopen",
                f"    hex.xor_by 1, {st}, {last}",
                f"    ;{p}_moved",
                f"  {p}_pressopen:",
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.zero 1, {dr}",
                f"    hex.set {WAIT_NIBBLES}, {wt}, {WAIT}",
                f"    ;{p}_moved",
                f"  {p}_already:",
                f"    hex.xor_by 1, {dr}, {OPENING}",
                f"  {p}_moved:",
                # ---- the motion --------------------------------------------------------------
                # THE IDLE COST IS THIS LINE. A door standing still with no timer pays this test
                # and the `dwait` one below, and nothing else.
                f"    hex.if0 1, {dr}, {p}_idle",
                f"    hex.dec 1, {sub}",
                f"    hex.if0 1, {sub}, {p}_step",
                f"    ;{p}_done",
                f"  {p}_step:",
                f"    hex.set 1, {sub}, {SPEED}",
                f"    hex.xor_by 1, {dr}, {OPENING}",
                f"    hex.if0 1, {dr}, {p}_up",
                f"    hex.xor_by 1, {dr}, {OPENING}",
                # closing: one step down, and IDLE when it reaches shut
                f"    hex.dec 1, {st}",
                f"    hex.if0 1, {st}, {p}_shut",
                f"    ;{p}_done",
                f"  {p}_shut:",
                f"    hex.zero 1, {dr}",
                f"    ;{p}_done",
                f"  {p}_up:",
                f"    hex.xor_by 1, {dr}, {OPENING}",
                f"    hex.inc 1, {st}",
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.if0 1, {st}, {p}_open",
                f"    hex.xor_by 1, {st}, {last}",
                f"    ;{p}_done",
                f"  {p}_open:",
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.zero 1, {dr}",
                f"    hex.set {WAIT_NIBBLES}, {wt}, {WAIT}",
                f"    ;{p}_done",
                # ---- idle: run the open-wait down --------------------------------------------
                f"  {p}_idle:",
                f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_done",
                f"    hex.dec {WAIT_NIBBLES}, {wt}",
                f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_close",
                f"    ;{p}_done",
                f"  {p}_close:",
                f"    hex.set 1, {dr}, {CLOSING}",
                f"    hex.set 1, {sub}, {SPEED}",
                f"  {p}_done:"]
    return out


# ---------------------------------------------------------------------------------------------
# M2-R4 — the COLLISION half: a door's lines read the door's state.
#
# A door's collision opening is baked at its OPEN height (`collision.line_rows`), and while the door
# is below `doors.pass_state` -- the first height whose opening clears DOOM's 56-unit gap -- its
# two-sided lines refuse like a wall. Since M7 P1.2 a door line's stub in the collision cells
# (`collision.collision_cells_fj`) decides that when the line is TESTED: one `hex.if_flags` on
# `dstate` against the states below the pass state, xoring FLAG_BLOCKING into the line's flags for
# the test. The oracle's `blocked_lines` is the same predicate.
#
# Before P1.2 the bit lived in the packed `lnrow` table and this file's `_cross` flipped it with a
# `wflip` on the two animation steps that cross the threshold. That was a SECOND copy of the door's
# state -- one that had to survive the M1 reset by staying out of the restore set, and that the
# hosted M2 gates had to relay between frames. Reading `dstate` leaves one copy, which persists
# the way every other door register does (`build.DOOR_PERSIST`).
#
# What the threshold gives up: while the door is between passable and fully open, the player's
# ceiling reads as fully open rather than as the true height. Nothing reads it by then -- `cp_ceil`
# feeds the gap test and the step logic, both already decided -- and the alternative is a per-state
# opening in every door line's stub.
# ---------------------------------------------------------------------------------------------


def door_line_ids(secs, lds, sds, doors) -> dict:
    """`{door sector: [linedef index, ...]}` -- the door's TWO-SIDED lines, the ones with an
    opening a player could pass through. Its one-sided track walls have no opening at any state
    and stay ordinary walls."""
    out: dict = {}
    for li, ld in enumerate(lds):
        if ld.back == -1 or ld.back == 0xFFFF or ld.back >= len(sds):
            continue
        for si in (sds[ld.front].sector, sds[ld.back].sector):
            if si in doors and li not in out.get(si, ()):
                out.setdefault(si, []).append(li)
    return out


def door_rooms(lds, sds, doors, lines_of) -> dict:
    """`{door sector: [(linedef, near room, [far rooms]), ...]}` -- what is on each SIDE of a door.

    A DOOM door sector is the thin moving sector BETWEEN two rooms, and both of its two-sided
    linedefs carry it on their BACK side (E1M1: all 25 of them). So `sds[ld.back].sector` is the
    door itself, never "the room behind the door" -- the room beyond, seen through the door from
    room F, is the FRONT sector of the door's other linedef(s).

    ⚠ Getting this backwards is not a hypothetical. `scratchpad/12m/leakcheck.py` perturbed
    `sds[ld.back].sector` to ask whether a shut door occludes, which moved the shut door's own
    ceiling from one shut position to another; both frames drew an occluding door and the tool
    reported a confident "0 px leak" that a door made of glass would also have earned. This
    function exists so the occlusion test and the tool cannot hold two opinions about which
    sector is behind a door.

    A door with a single two-sided line (E1M1 sector 84, a closet) has NO far room; its entry
    carries an empty list, and a caller that needs one must report it, not skip it silently."""
    out: dict = {}
    for si in sorted(doors):
        pairs = [(li, sds[lds[li].front].sector)
                 for li in sorted(lines_of.get(si, ()))
                 if lds[li].back != -1 and lds[li].back != 0xFFFF]
        rooms = {r for _, r in pairs}
        out[si] = [(li, near, sorted(rooms - {near})) for li, near in pairs]
    return out
