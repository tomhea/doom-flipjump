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

from doomfj.doors import CLOSING, OPENING, SPEED, WAIT, door_stay, door_stride

# `dwait` counts frames and needs to hold WAIT; two nibbles is 0..255.
WAIT_NIBBLES = 2
assert 0 < WAIT < (1 << (4 * WAIT_NIBBLES)), f"WAIT={WAIT} does not fit {WAIT_NIBBLES} nibbles"
assert 0 < SPEED < 16, f"SPEED={SPEED} does not fit the one-nibble `dsub`"


def door_decls(ndoors: int, nwalk: int = 0) -> list:
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
        # M7 P2a.1 -- persisted like the doors: a press requested for the next door tic (a walk-over
        # crossing), the blue card, and each walk-over trigger's W1 bit
        f"dreq: hex.vec {ndoors}, 0",
        "pcard: hex.vec 1, 0",
        f"wfired: hex.vec {max(nwalk, 1)}, 0",
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


def machine_lines(p: str, st: str, dr: str, sub: str, wt: str, last: int, trigger: list, *,
                  stride: int = 1, top_wait: int = WAIT) -> list:
    """ONE door machine's frame, after its trigger lines (which fall into `<p>_press` to press and
    jump to `<p>_moved` not to): `doors.door_tic` in fj, on the cells `st`/`dr`/`sub`/`wt` (the
    last a WAIT_NIBBLES counter), `last` = nstates - 1. `top_wait` is the wait set on reaching the
    top (0: a stay door; M7 P2b: LIFT_WAIT for a lift, whose "top" is its bottom floor).
    The doors (`door_tic_lines`) and the lifts (`movercode.lift_tic_lines`) both emit from here."""
    set_wait = ([f"    hex.zero {WAIT_NIBBLES}, {wt}"] if not top_wait else
                [f"    hex.set {WAIT_NIBBLES}, {wt}, {top_wait}"])
    up = []
    for k in range(stride):                             # `state += stride`, clamped at the top
        up += [f"    hex.inc 1, {st}",
               f"    hex.xor_by 1, {st}, {last}",
               f"    hex.if0 1, {st}, {p}_open",
               f"    hex.xor_by 1, {st}, {last}"]
    down = []
    for k in range(stride):                             # `state -= stride`, clamped at shut
        down += [f"    hex.dec 1, {st}",
                 f"    hex.if0 1, {st}, {p}_shut"]
    return [
        # ---- the trigger: `if used and dr != OPENING` -------------------------------
        *trigger,
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
        *set_wait,
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
        # closing: `stride` steps down, and IDLE when it reaches shut
        *down,
        f"    ;{p}_done",
        f"  {p}_shut:",
        f"    hex.zero 1, {dr}",
        f"    ;{p}_done",
        f"  {p}_up:",
        f"    hex.xor_by 1, {dr}, {OPENING}",
        *up,
        f"    ;{p}_done",
        f"  {p}_open:",
        f"    hex.xor_by 1, {st}, {last}",
        f"    hex.zero 1, {dr}",
        *set_wait,
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


def door_tic_lines(slots, nstates, boxes, kinds=None) -> list:
    """One frame of every door. `slots` is the emitter's door order (`sorted(door sectors)`),
    `nstates[si]` how many stops that door has, `boxes[si]` its use box in map units (none for a
    walk-over door), `kinds[si]` its `doors.door_kinds` kind (all "plain" when omitted).

    M7 P2a.1, each kind the mirror of `doors.door_tic` / `DoorPhase.tic`: a blue door's use press
    needs `pcard`; a door's `dreq` (set by a walk-over crossing) presses it and is cleared; the
    blazing door steps `door_stride` stops, clamped (the one-stop step unrolled); a stay door's top
    sets no wait.

    Nothing here touches collision: a door's lines read its `dstate` when they are tested
    (`collision.collision_cells_fj`), so the state this walks IS the door's collision too.

    The label prefix is `dr{slot}_`, so the emitted names say which door they belong to.
    """
    out = ["// == M2-R4: the doors, one tic each ==================================",
           "//   dr<d>_*  door <d> (index into sorted(door sectors))",
           "//   the mirror of doomfj.doors.door_tic -- read them together"]
    kinds = kinds or {si: "plain" for si in slots}
    for d, si in enumerate(slots):
        n = nstates[si]
        last = n - 1
        kind = kinds[si]
        stride, stay = door_stride(kind), door_stay(kind)
        rq = f"dreq + {d}*dw"
        st = f"dstate + {d}*dw"
        dr = f"ddir + {d}*dw"
        sub = f"dsub + {d}*dw"
        wt = f"dwait + {WAIT_NIBBLES * d}*dw"
        p = f"dr{d}"
        box = boxes.get(si)
        trigger = []
        if kind == "walkover":            # only these get requests in P2a (monsters' come with P3),
            trigger = [f"    hex.if0 1, {rq}, {p}_use",   # so an idle plain door still costs 3 ops
                       f"    hex.zero 1, {rq}",           # ... pressed once
                       f"    ;{p}_press",
                       f"  {p}_use:"]
        if box is None:
            trigger += [f"    ;{p}_moved"]                  # a walk-over door has no use line
        else:
            trigger += [f"    hex.if0 1, duse, {p}_moved"]
            if kind == "blue":
                trigger += [f"    hex.if0 1, pcard, {p}_moved"]   # EV_VerticalDoor: the blue card
            trigger += _box_test(d, box, f"{p}_press", f"{p}_moved")
        out += [f"  // ---- door {d} (sector {si}, {kind}): {n} states ----",
                *machine_lines(p, st, dr, sub, wt, last, trigger, stride=stride,
                               top_wait=0 if stay else WAIT)]
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


# ---- M7 P2a.1: the card's pickup and the walk-over triggers, in the player's move -----------------------

def _scmp_const(reg, val, lt, eq, gt, scratch="dbox") -> list:
    """signed compare of an 8-nibble register against a baked constant"""
    return [f"    hex.set 8, {scratch}, {val & 0xFFFFFFFF:#x}",
            f"    hex.scmp 8, {reg}, {scratch}, {lt}, {eq}, {gt}"]


def card_pickup_lines(tag: str, card, slot_addr: str, reach_lo: int, reach_hi: int,
                      radius: int) -> list:
    """The blue card's `_touch_specials` at ONE tried candidate (`cpx`, `cpy`), with the floor the
    player stands on (`cm_hf`): while it is untaken (`pcard` 0), a box overlap -- |item - cand| <
    item radius + player radius on both axes, strict, in 16.16 -- and the reach `reach_lo <= cm_hf
    <= reach_hi` take it: `pcard` 1 and the card's `thvis` slot (`slot_addr`) 0."""
    kx, ky = card
    bd = radius
    miss = f"{tag}ck_no"
    out = [f"    hex.if0 1, pcard, {tag}ck_try", f"    ;{miss}", f"  {tag}ck_try:"]
    for k, (reg, lo, hi) in enumerate((("cpx", kx - bd, kx + bd), ("cpy", ky - bd, ky + bd))):
        # lo < reg < hi, strict both ends
        out += _scmp_const(reg, lo << 16, miss, miss, f"{tag}ck{k}a")
        out += [f"  {tag}ck{k}a:"]
        out += _scmp_const(reg, hi << 16, f"{tag}ck{k}b", miss, miss)
        out += [f"  {tag}ck{k}b:"]
    out += _scmp_const("cm_hf", reach_lo, miss, f"{tag}ckr", f"{tag}ckr")
    out += [f"  {tag}ckr:"]
    out += _scmp_const("cm_hf", reach_hi, f"{tag}cky", f"{tag}cky", miss)
    out += [f"  {tag}cky:",
            "    hex.set 1, pcard, 1",
            f"    hex.zero 2, {slot_addr}",
            f"  {miss}:"]
    return out


def walkover_lines(triggers, slots, radius: int) -> list:
    """`DoorPhase.after_move` in fj: after an ACCEPTED move from (`cm_ox`, `cm_oy`) to (`viewx`,
    `viewy`), each unfired trigger whose axis the centre crossed (`c <= L` differs) with the new
    centre strictly inside the segment's extent inflated by the radius fires: `wfired` 1 and its
    door's `dreq` 1 -- the press lands on the next frame's door tic."""
    out = ["  // M7 P2a.1: the walk-over triggers (doomfj.doors.crossed)"]
    for k, (si, axis, coord, lo, hi) in enumerate(triggers):
        d = slots.index(si)
        p = f"wo{k}"
        out += [f"    hex.if0 1, wfired + {k}*dw, {p}_try", f"    ;{p}_no", f"  {p}_try:"]
        out += _crossed_lines(p, axis, coord, lo, hi, radius,
                              [f"    hex.set 1, wfired + {k}*dw, 1",
                               f"    hex.set 1, dreq + {d}*dw, 1"])
    return out


def _crossed_lines(p: str, axis: str, coord: int, lo: int, hi: int, radius: int, fire) -> list:
    """`doors.crossed` in fj on the move (`cm_ox`, `cm_oy`) -> (`viewx`, `viewy`): the centre
    changed side of the axis line (`c <= L`) and the new centre is strictly inside the segment's
    extent inflated by `radius` -> the `fire` lines; either way on to `<p>_no`. The walk-over doors
    (`walkover_lines`, behind their W1 latch) and the WR lifts (`movercode.lift_walk_lines`)."""
    a_old, a_new, o_new = (("cm_oy", "viewy", "viewx") if axis == "y" else
                           ("cm_ox", "viewx", "viewy"))
    L = coord << 16
    out = []
    # old side: le_old = old <= L  -> {p}_ol (le) / {p}_og (gt)
    out += _scmp_const(a_old, L, f"{p}_ol", f"{p}_ol", f"{p}_og")
    out += [f"  {p}_ol:"]                                  # old on the low side: new must be above
    out += _scmp_const(a_new, L, f"{p}_no", f"{p}_no", f"{p}_x")
    out += [f"  {p}_og:"]                                  # old above: new must be low
    out += _scmp_const(a_new, L, f"{p}_x", f"{p}_x", f"{p}_no")
    out += [f"  {p}_x:"]
    out += _scmp_const(o_new, (lo - radius) << 16, f"{p}_no", f"{p}_no", f"{p}_x1")
    out += [f"  {p}_x1:"]
    out += _scmp_const(o_new, (hi + radius) << 16, f"{p}_fire", f"{p}_no", f"{p}_no")
    out += [f"  {p}_fire:", *fire, f"  {p}_no:"]
    return out
