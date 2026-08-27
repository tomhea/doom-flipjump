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
