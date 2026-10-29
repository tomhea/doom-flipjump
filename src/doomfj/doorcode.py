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
from doomfj.doors import door_card_cell, poly_edges                     # M8 L2
from doomfj.doors import STAY_MARK                                      # M8 C3

M32 = 0xFFFFFFFF

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


def _box_test(d: int, box, hit: str, miss: str, regs=("viewx", "viewy"), tag=None) -> list:
    """`in_use_box` in fj: four signed compares of the 16.16 player position against baked corners (M7 P3.2b:
    `regs` -- a monster's position, `monstermove.move_leaf_lines`' door boxes). M8 L2: `tag` -- the labels' prefix
    (default `dub<d>`; a door's switch boxes take their own).

    The box is axis-aligned precisely so this needs no multiply and no line side test -- see the
    compromise noted in `doors.use_boxes`."""
    x0, y0, x1, y1 = box
    out = []
    rx, ry = regs
    pre = f"dub{d}" if tag is None else tag
    for k, (reg, val, want_ge) in enumerate(((rx, x0, True), (rx, x1, False),
                                             (ry, y0, True), (ry, y1, False))):
        tag = f"{pre}_{k}"
        out.append(f"    hex.set 8, dbox, {(val << 16) & 0xFFFFFFFF:#x}")
        if want_ge:                    # miss when reg < val
            out.append(f"    hex.scmp 8, {reg}, dbox, {miss}, {tag}, {tag}")
        else:                          # miss when reg > val
            out.append(f"    hex.scmp 8, {reg}, dbox, {tag}, {tag}, {miss}")
        out.append(f"  {tag}:")
    out.append(f"    ;{hit}")
    return out


def machine_lines(p: str, st: str, dr: str, sub: str, wt: str, last: int, trigger: list, *,
                  stride: int = 1, top_wait: int = WAIT, reverse=None, down_stride=None, hold: bool = False,
                  spress: bool = False, top_clamp: bool = True) -> list:
    """ONE door machine's frame, after its trigger lines (which fall into `<p>_press` to press and
    jump to `<p>_moved` not to): `doors.door_tic` in fj, on the cells `st`/`dr`/`sub`/`wt` (the
    last a WAIT_NIBBLES counter), `last` = nstates - 1. `top_wait` is the wait set on reaching the
    top (0: a stay door; M7 P2b: LIFT_WAIT for a lift, whose "top" is its bottom floor).
    The doors (`door_tic_lines`) and the lifts (`movercode.lift_tic_lines`) both emit from here.
    `reverse` (M7 P2b, `doors.door_tic`'s reversal): `(mask, contact)` -- on a CLOSING step from a
    state in `mask` (the states whose step leaves the pass state), `contact(yes, no)`'s lines decide
    whether a thing touches the door; touched, the door turns to OPENING without stepping.

    M8 C3 (`doors.door_tic`'s close_stride / hold / stay_press): `down_stride` the closing step's stops (a WR close
    line's); `hold` -- touched, a closing door stays where it is, still closing; `spress` -- the label `<p>_spress`, a
    STAY PRESS (OPENING with STAY_MARK in the wait), and the top then sets no wait after one.

    M8 w2fix: `top_clamp` -- a door that reverses AT its top (its reversal mask holds `last`: its pass state is its top)
    is OPENING at `last`, and its next step is the top again (`<p>_open`), not the equality step past it. False keeps
    the old step (config.DOOR_TOP_STEP_LEGACY: E1M1's emission)."""
    set_wait = ([f"    hex.zero {WAIT_NIBBLES}, {wt}"] if not top_wait else
                [f"    hex.set {WAIT_NIBBLES}, {wt}, {top_wait}"])
    # the top's wait: after a stay press (STAY_MARK in the wait while opening) none, else top_wait
    top_set = set_wait if not spress else [
        f"    hex.xor_by {WAIT_NIBBLES}, {wt}, {STAY_MARK}",
        f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_done",
        *set_wait]
    up = []
    if top_clamp and reverse is not None and reverse[0] >> last & 1:
        # M8 w2fix (E1M5's door 1, sector 12; E1M3's 167 / 213 / 228): a door whose pass state is its TOP reverses
        # there -- OPENING at `last` -- and its next step is the top again (doors.door_tic's `state >= nstates - 1`,
        # T_VerticalDoor: up, at once at its top, the wait): the equality test below would step it past the top
        up += [f"    hex.xor_by 1, {st}, {last}",
               f"    hex.if0 1, {st}, {p}_open",
               f"    hex.xor_by 1, {st}, {last}"]
    for k in range(stride):                             # `state += stride`, clamped at the top
        up += [f"    hex.inc 1, {st}",
               f"    hex.xor_by 1, {st}, {last}",
               f"    hex.if0 1, {st}, {p}_open",
               f"    hex.xor_by 1, {st}, {last}"]
    down = []
    for k in range(stride if down_stride is None else down_stride):   # `state -= stride`, clamped at shut
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
        *([] if not spress else [
            # M8 C3: a stay press (a switch's, on a door at rest): opening, the mark in the wait
            f"  {p}_spress:",
            f"    hex.set 1, {dr}, {OPENING}",
            f"    hex.set 1, {sub}, {SPEED}",
            f"    hex.set {WAIT_NIBBLES}, {wt}, {STAY_MARK}",
            f"    ;{p}_moved"]),
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
        *([] if reverse is None else [
            # M7 P2b: reversal -- the pass step of a closing door, a thing in it: back up, no step
            f"    hex.if_flags {st}, {reverse[0]:#06x}, {p}_dn, {p}_rv",
            f"  {p}_rv:",
            *reverse[1](f"{p}_rev", f"{p}_dn"),
            f"  {p}_rev:",
            *([] if hold else [f"    hex.set 1, {dr}, {OPENING}"]),     # M8 C3: a close line's door holds
            f"    ;{p}_done",
            f"  {p}_dn:"]),
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
        *top_set,
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


def door_contact_lines(tag: str, geo, radius: int, yes: str, no: str, regs=("viewx", "viewy")) -> list:
    """`doors.touches_door` in fj for the player at (`viewx`, `viewy`), box half-width `radius`:
    the centre strictly inside the door's rectangle, or the box straddling one of its two-sided
    lines (strict, both axes) -> `yes`; else `no`. M7 P3.2b: `regs` -- a monster's 16.16 position (thpos_rt).

    M8 L2: a non-rectangular door (`poly`) -- the box straddling ANY of its boundary lines, an
    axis-aligned one as above, a slanted one by check_position's test (`_straddle_d_lines`).
    M8 C3: a door some box FITS inside (`door_contact_geo`'s flag; E1M4 102, a 45-degree square that closes) runs the
    centre-inside test first -- for a CONVEX polygon (asserted): P_PointOnLineSide on the front side of every edge,
    each edge oriented with the inside in front (`convex_inside_lines`). It is not `_inside_poly`'s exact crossing
    count, and need not be: the two disagree only within 1/|edge| of a unit of an edge, where the box (radius >= 16)
    straddles it -- the contact is the same (tests/fj/test_doors_c3_fj.py runs it against touches_door)."""
    area, lines = geo
    rx, ry = regs
    r = radius << 16
    out = []

    def between(t, reg, lo16, hi16, fail):
        return (_scmp_const(reg, lo16, fail, fail, f"{t}a") + [f"  {t}a:"]
                + _scmp_const(reg, hi16, f"{t}b", fail, fail) + [f"  {t}b:"])
    if area[0] == "poly":
        tests, lines = [], poly_edges(area)
        if area[2]:                                     # M8 C3: the centre strictly inside (a convex polygon)
            out += convex_inside_lines(f"{tag}_in", area[1], rx, ry, yes, f"{tag}_out") + [f"  {tag}_out:"]
    else:
        assert all(ln[0] != "d" for ln in lines), "a rectangle's lines lie on its box"
        x0, y0, x1, y1 = area
        tests = [(((rx, x0 << 16, x1 << 16), (ry, y0 << 16, y1 << 16)))]
    for axis, coord, lo, hi in (ln for ln in lines if ln[0] != "d"):
        across, along = (ry, rx) if axis == "y" else (rx, ry)
        tests.append(((across, (coord << 16) - r, (coord << 16) + r),
                      (along, (lo << 16) - r, (hi << 16) + r)))
    for k, pair in enumerate(tests):
        fail = f"{tag}_n{k}"
        for j, (reg, lo16, hi16) in enumerate(pair):
            out += between(f"{tag}_{k}{j}", reg, lo16 & 0xFFFFFFFF, hi16 & 0xFFFFFFFF, fail)
        out += [f"    ;{yes}", f"  {fail}:"]
    for j, ln in enumerate(ln for ln in lines if ln[0] == "d"):
        fail = f"{tag}_dn{j}"
        out += _straddle_d_lines(f"{tag}_d{j}", ln[1:], rx, ry, r, yes, fail) + [f"  {fail}:"]
    return out + [f"    ;{no}"]


def convex_edges(edges) -> list:
    """M8 C3: a CONVEX polygon's edges (x1, y1, x2, y2), each oriented so the inside is in FRONT (P_PointOnLineSide 0,
    the right of v1 -> v2): by the exact cross product of the vertices' mean. Asserts convexity: every vertex is in
    front of or on every oriented edge."""
    pts = sorted({(e[0], e[1]) for e in edges} | {(e[2], e[3]) for e in edges})
    n = len(pts)
    sx, sy = sum(p[0] for p in pts), sum(p[1] for p in pts)

    def cross(ax, ay, bx, by, px, py, scale=1):      # (b - a) x (p - a), p scaled by `scale`
        return (bx - ax) * (py - ay * scale) - (by - ay) * (px - ax * scale)
    out = []
    for ax, ay, bx, by in edges:
        if cross(ax, ay, bx, by, sx, sy, n) > 0:     # the mean on the LEFT: swap the ends
            ax, ay, bx, by = bx, by, ax, ay
        assert cross(ax, ay, bx, by, sx, sy, n) < 0, ("a degenerate polygon", edges)
        assert all(cross(ax, ay, bx, by, px, py) <= 0 for px, py in pts), ("the door is not convex", edges)
        out.append((ax, ay, bx, by))
    return out


def convex_inside_lines(t: str, edges, rx: str, ry: str, yes: str, no: str) -> list:
    """M8 C3: the 16.16 point (`rx`, `ry`) strictly inside the convex polygon `edges` -> `yes`, else `no`: on the
    front side (P_PointOnLineSide 0) of every edge as `convex_edges` orients it -- a slanted edge by `sim.point_side`
    (its FixedMul case), an axis-aligned one by DOOM's own shortcut (a vertical line: x <= v1x is side dy > 0; a
    horizontal one: y <= v1y is side dx < 0)"""
    out = []
    for j, (ax, ay, bx, by) in enumerate(convex_edges(edges)):
        e = f"{t}{j}"
        nxt = f"{e}_ok"
        if ax == bx:                                   # front (0): dy > 0 -> x > v1x; dy < 0 -> x <= v1x
            out += (_scmp_const(rx, ax << 16, no, no, nxt) if by > ay else _scmp_const(rx, ax << 16, nxt, nxt, no))
        elif ay == by:                                 # front (0): dx > 0 -> y <= v1y; dx < 0 -> y > v1y
            out += (_scmp_const(ry, ay << 16, nxt, nxt, no) if bx > ax else _scmp_const(ry, ay << 16, no, no, nxt))
        else:
            data, (v1x, v1y, dx, dy) = _line_consts(e, (ax, ay, bx, by))
            out += [*data, f"    ;{e}_g", f"  {e}_s: hex.vec 1", f"  {e}_g:",
                    f"    sim.point_side {e}_s, {rx}, {ry}, {v1x}, {v1y}, {dx}, {dy}",
                    f"    hex.if0 1, {e}_s, {nxt}", f"    ;{no}"]
        out += [f"  {nxt}:"]
    return out + [f"    ;{yes}"]


def _line_consts(t: str, seg) -> tuple:
    """`(lines, (v1x, v1y, dx, dy))` -- a slanted line's constants for `sim.point_side` as baked cells, jumped
    over (never written: nothing for the reset to restore): v1 in 16.16, the deltas as signed 8-nibble integers"""
    ax, ay, bx, by = seg
    names = (f"{t}_v1x", f"{t}_v1y", f"{t}_dx", f"{t}_dy")
    vals = (ax << 16, ay << 16, bx - ax, by - ay)
    return ([f"    ;{t}_go"] + [f"  {n}: hex.vec 8, {v & M32:#x}" for n, v in zip(names, vals)]
            + [f"  {t}_go:"]), names


def _straddle_d_lines(t: str, seg, rx: str, ry: str, r16: int, yes: str, no: str, consts=None) -> list:
    """`doors.straddles_d` in fj: the box of half-width `r16` at (`rx`, `ry`) (16.16 registers) against the slanted
    line `seg` = (x1, y1, x2, y2) in map units -> `yes` / `no`. The boxes overlap, strict (`min - r < centre < max +
    r` on both axes is `right > min`, `left < max`), then P_BoxOnLineSide's two extreme corners through
    `sim.point_side` (P_PointOnLineSide's FixedMul case) differ. `consts`: the line's cells from `_line_consts`
    (made here when None)."""
    ax, ay, bx, by = seg
    out = []
    if consts is None:
        data, consts = _line_consts(t, seg)
        out += data
    v1x, v1y, dx, dy = consts
    out += [f"    ;{t}_g2", f"  {t}_cx: hex.vec 8", f"  {t}_cy: hex.vec 8", f"  {t}_s1: hex.vec 1",
            f"  {t}_s2: hex.vec 1", f"  {t}_g2:"]
    for k, (reg, lo, hi) in enumerate(((rx, min(ax, bx), max(ax, bx)), (ry, min(ay, by), max(ay, by)))):
        out += _scmp_const(reg, (lo << 16) - r16, no, no, f"{t}_b{k}a") + [f"  {t}_b{k}a:"]
        out += _scmp_const(reg, (hi << 16) + r16, f"{t}_b{k}b", no, no) + [f"  {t}_b{k}b:"]
    pos = (by - ay > 0) == (bx - ax > 0)               # ST_POSITIVE: (left, top) / (right, bottom)
    corners = ((-r16, r16), (r16, -r16)) if pos else ((r16, r16), (-r16, -r16))
    for side, (cx, cy) in zip((f"{t}_s1", f"{t}_s2"), corners):
        for cell, reg, c in ((f"{t}_cx", rx, cx), (f"{t}_cy", ry, cy)):
            out += [f"    hex.mov 8, {cell}, {reg}",
                    f"    hex.add_constant 8, {cell}, {c:#x}" if c > 0 else f"    hex.sub_constant 8, {cell}, {-c:#x}"]
        out += [f"    sim.point_side {side}, {t}_cx, {t}_cy, {v1x}, {v1y}, {dx}, {dy}"]
    out += [f"    hex.cmp 1, {t}_s1, {t}_s2, {yes}, {no}, {yes}"]
    return out


def reverse_mask(pass_at: int, stride: int, nstates: int) -> int:
    """the states whose CLOSING step (`stride` stops) leaves `pass_at` -- `doors.door_tic`'s
    `state >= pass_at > state - stride` -- as an `hex.if_flags` value mask"""
    return sum(1 << s for s in range(nstates) if s >= pass_at > s - stride)


def door_tic_lines(slots, nstates, boxes, kinds=None, contact=None, passes=None, radius=16, mon_press=frozenset(),
                   mon_contact=(), dead=None, switches=None, walked=None, keyed=None, switch_info=None, nwalk=0,
                   close=None, top_clamp: bool = True) -> list:
    """One frame of every door. `slots` is the emitter's door order (`sorted(door sectors)`),
    `nstates[si]` how many stops that door has, `boxes[si]` its use box in map units (none for a
    walk-over door), `kinds[si]` its `doors.door_kinds` kind (all "plain" when omitted).

    M7 P2a.1, each kind the mirror of `doors.door_tic` / `DoorPhase.tic`: a blue door's use press
    needs `pcard`; a door's `dreq` (set by a walk-over crossing) presses it and is cleared; the
    blazing door steps `door_stride` stops, clamped (the one-stop step unrolled); a stay door's top
    sets no wait.

    Nothing here touches collision: a door's lines read its `dstate` when they are tested
    (`collision.collision_cells_fj`), so the state this walks IS the door's collision too.

    M7 P2b: `contact` (`doors.door_contact_geo`) and `passes` (each door's pass state) arm the
    reversal on every door that closes -- the player touching it (`door_contact_lines`).

    The label prefix is `dr{slot}_`, so the emitted names say which door they belong to.

    M7 P7 (doomfj.lootcode): `dead` -- the cell holding the player's death at the tic's START (`p_dd0`): set, the
    player's use press opens no door and his box holds no closing door (World._doors_phase's `alive`,
    World.door_touched's `player_alive`). Without it the text is P5's.

    M8 L2 (E1M2), each the mirror of `doors.DoorPhase.tic` / World._doors_phase: a yellow / red door's
    use press needs `pcard_y` / `pcard_r` (`doors.door_card_cell`; declared by the pickups);
    `switches` (`doors.switch_boxes`: {door: [box]}) -- after the door's own use box misses, the
    player's use in a switch box presses the door when it is at rest (`doors.switch_ready`: `ddir`
    and `dwait` zero, EV_DoDoor's no-thinker test); `walked` -- the doors a walk-over line opens
    (their `dreq`), by default the walk-over kinds. Without them the text is P8a's.

    M8 C3 (E1M3..E1M9), each the mirror of `doors.DoorPhase.tic` / World._doors_phase: `keyed` (`doors.keyed_boxes_xy`:
    {door: [(box, card)]}) -- a mixed door's keyed front boxes, after its own box misses, each with its card;
    `switch_info` (`doors.switch_entries` without the boxes: {door: [(card, latch, stay)]}, parallel to `switches`) --
    a locked switch's card, a latched S1 switch's W1 bit (`wfired + (nwalk + latch)`: tested, set on its press) and a
    stay press (`machine_lines(spress=)`); `close` (`doors.close_strides`: {door: stride}) -- a close line's door
    closes at its stride and HOLDS on a thing (its contact armed though it stays open). Without them the text is L2's.
    """
    out = ["// == M2-R4: the doors, one tic each ==================================",
           "//   dr<d>_*  door <d> (index into sorted(door sectors))",
           "//   the mirror of doomfj.doors.door_tic -- read them together"]
    # M7 P3.2b: `mon_press` -- the doors a MONSTER presses (its refused step in the door's monster box sets `dreq`,
    # monstermove.move_leaf_lines), taken like a walk-over request; `mon_contact` -- [(x16 cell, y16 cell, radius,
    # active cell)] per monster, a closing door reversing on a live one as on the player (World.door_touched)
    kinds = kinds or {si: "plain" for si in slots}
    switches = switches or {}
    keyed, switch_info, close = keyed or {}, switch_info or {}, close or {}
    walked = (set(walked) if walked is not None else
              {si for si in slots if kinds[si] in ("walkover", "blazestay")})
    # the monsters' contact tests are SHARED: one leaf per (door, radius) on the registers dc_x / dc_y -- inline they
    # were one signed constant compare (1,808 ops) per bound, door and monster, ~14.6M ops for E1M1's 53 monsters
    leaves: dict = {}
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
        if si in walked or si in mon_press:         # walk-over requests (P2a) and monster presses (P3.2b)
            trigger = [f"    hex.if0 1, {rq}, {p}_use",   # so an idle plain door still costs 3 ops
                       f"    hex.zero 1, {rq}",           # ... pressed once
                       f"    ;{p}_press",
                       f"  {p}_use:"]
        sw = switches.get(si, ())
        if box is None and not sw:
            trigger += [f"    ;{p}_moved"]                  # a walk-over door has no use line
        else:
            trigger += [f"    hex.if0 1, duse, {p}_moved"]
            if dead is not None:
                trigger += [f"    hex.if1 1, {dead}, {p}_moved"]        # M7 P7: a dead player presses nothing
            after = f"{p}_sw" if sw else f"{p}_moved"
            kb = keyed.get(si, ())
            miss = f"{p}_k0" if kb else after
            if box is not None:
                card = door_card_cell(kind)
                if card:
                    trigger += [f"    hex.if0 1, {card}, {miss}"]   # EV_VerticalDoor: the key door's card
                trigger += _box_test(d, box, f"{p}_press", miss)
            for j, (b, c) in enumerate(kb):                     # M8 C3: a mixed door's keyed front boxes
                nxt = f"{p}_k{j + 1}" if j + 1 < len(kb) else after
                trigger += [f"  {p}_k{j}:", f"    hex.if0 1, {door_card_cell(c)}, {nxt}"]
                trigger += _box_test(d, b, f"{p}_press", nxt, tag=f"dky{d}_{j}")
            if sw:
                # M8 L2: a switch (P_UseSpecialLine -> EV_DoDoor) presses a door at rest: no thinker (`ddir`, `dwait`)
                trigger += [f"  {p}_sw:",
                            f"    hex.if0 1, {dr}, {p}_swi", f"    ;{p}_moved", f"  {p}_swi:",
                            f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_swt", f"    ;{p}_moved", f"  {p}_swt:"]
                info = switch_info.get(si, [(None, None, False)] * len(sw))
                assert len(info) == len(sw), (si, info, sw)
                hits = []
                for j, b in enumerate(sw):
                    nxt = f"{p}_sw{j + 1}" if j + 1 < len(sw) else f"{p}_moved"
                    c, lt, sp = info[j]
                    # M8 C3: a locked switch's card (EV_DoLockedDoor), a latched S1's W1 bit
                    if c is not None:
                        trigger += [f"    hex.if0 1, {door_card_cell(c)}, {nxt}"]
                    if lt is not None:
                        trigger += [f"    hex.if1 1, wfired + {nwalk + lt}*dw, {nxt}"]
                    hit = f"{p}_press" if lt is None and not sp else f"{p}_sh{j}"
                    trigger += _box_test(d, b, hit, nxt, tag=f"dsw{d}_{j}")
                    if hit != f"{p}_press":
                        hits += [f"  {hit}:"] + ([f"    hex.set 1, wfired + {nwalk + lt}*dw, 1"] if lt is not None
                                                 else []) + [f"    ;{p}_spress" if sp else f"    ;{p}_press"]
                    if j + 1 < len(sw):
                        trigger += [f"  {nxt}:"]
                if hits:                                        # the hit stubs, jumped over by `_moved`'s path
                    trigger += [f"    ;{p}_moved"] + hits
        rev = None
        down = close.get(si)
        if contact is not None and (not stay or down is not None):
            def _rev(yes, no, _g=contact[si], _p=p):
                # M7 P7: a dead player's box holds nothing open -- on to the monsters' contact (or `no`)
                out_ = [f"    hex.if1 1, {dead}, {_p}_cm0" if mon_contact else f"    hex.if1 1, {dead}, {no}"]                     if dead is not None else []
                out_ += door_contact_lines(f"{_p}_ct", _g, radius, yes, f"{_p}_cm0" if mon_contact else no)
                for j, (xr, yr, rad, act) in enumerate(mon_contact):
                    nx_ = f"{_p}_cm{j + 1}" if j + 1 < len(mon_contact) else no
                    leaf = leaves.setdefault((_p, rad), (f"{_p}_mc{rad}", _g, rad))[0]
                    out_ += [f"  {_p}_cm{j}:", f"    hex.if0 1, {act}, {nx_}",
                             f"    hex.mov 8, dc_x, {xr}", f"    hex.mov 8, dc_y, {yr}",
                             f"    stl.fcall {leaf}, dc_ret",
                             f"    hex.if1 1, dc_hit, {yes}", f"    ;{nx_}"]
                return out_
            rev = (reverse_mask(passes[si], stride if down is None else down, n), _rev)
        spress = any(sp for _c, _l, sp in switch_info.get(si, ()))
        out += [f"  // ---- door {d} (sector {si}, {kind}): {n} states ----",
                *machine_lines(p, st, dr, sub, wt, last, trigger, stride=stride,
                               top_wait=0 if stay else WAIT, reverse=rev, down_stride=down,
                               hold=down is not None, spress=spress, top_clamp=top_clamp)]
    if leaves:                           # the contact leaves and their registers, jumped over
        out += ["    ;dc_leaves_end"]
        for lab, geo, rad in leaves.values():
            out += [f"{lab}:", *door_contact_lines(f"{lab}_t", geo, rad, f"{lab}_y", f"{lab}_n", regs=("dc_x", "dc_y")),
                    f"  {lab}_y:", "    hex.set 1, dc_hit, 1", "    stl.fret dc_ret",
                    f"  {lab}_n:", "    hex.zero 1, dc_hit", "    stl.fret dc_ret"]
        out += ["dc_x: hex.vec 8", "dc_y: hex.vec 8", "dc_hit: hex.vec 1", "dc_ret: hex.vec w/4",
                "dc_leaves_end:"]
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


def walkover_lines(triggers, slots, radius: int, prefix: str = "wo") -> list:
    """`DoorPhase.after_move` in fj: after an ACCEPTED move from (`cm_ox`, `cm_oy`) to (`viewx`,
    `viewy`), each unfired trigger whose axis the centre crossed (`c <= L` differs) with the new
    centre strictly inside the segment's extent inflated by the radius fires: `wfired` 1 and its
    door's `dreq` 1 -- the press lands on the next frame's door tic. `prefix` (M7 P8a): the labels'
    (fj labels are global: a second copy -- the knock move's, doomfj.knockcode -- takes its own).

    M8 L2: the entries of ONE line (a tag opening several doors: `doors.walkover_triggers` gives one
    entry per door) share one crossing test and fire together -- the first entry's `wfired` stands for
    all (they are only ever set together); a slanted line ("d") crosses by `_crossed_d_lines`."""
    out = ["  // M7 P2a.1: the walk-over triggers (doomfj.doors.crossed)"]
    groups: dict = {}
    for k, trig in enumerate(triggers):
        groups.setdefault(tuple(trig[1:]), []).append(k)
    for geo, ks in groups.items():
        k = ks[0]
        p = f"{prefix}{k}"
        fire = []
        for kk in ks:
            fire += [f"    hex.set 1, wfired + {kk}*dw, 1",
                     f"    hex.set 1, dreq + {slots.index(triggers[kk][0])}*dw, 1"]
        out += [f"    hex.if0 1, wfired + {k}*dw, {p}_try", f"    ;{p}_no", f"  {p}_try:"]
        if geo[0] == "d":
            out += _crossed_d_lines(p, geo[1:], radius, fire)
        else:
            out += _crossed_lines(p, *geo, radius, fire)
    return out


def repeat_walk_lines(repeats, slots, radius: int, prefix: str = "wor") -> list:
    """M8 C3: the WR door lines in fj (`doors.repeat_triggers` / `repeat_act`; World._walkover after the W1 ones): after
    an ACCEPTED move each entry whose line the centre crossed (`doors.crossed`) acts on its door when it is at rest
    (`ddir` and `dwait` zero): "open" sets its `dreq` (a press on the next door tic), "close" -- unless shut (`dstate`
    0) -- starts it closing (`ddir` CLOSING, `dsub` SPEED: doors.close_state). No latch. Labels `<prefix><k>_`."""
    out = ["  // M8 C3: the WR door lines (doomfj.doors.repeat_triggers)"]
    for k, trig in enumerate(repeats):
        si, act, geo = trig[0], trig[1], tuple(trig[2:])
        d = slots.index(si)
        p = f"{prefix}{k}"
        fire = [f"    hex.if0 1, ddir + {d}*dw, {p}_rd", f"    ;{p}_no", f"  {p}_rd:",
                f"    hex.if0 {WAIT_NIBBLES}, dwait + {WAIT_NIBBLES * d}*dw, {p}_rw", f"    ;{p}_no", f"  {p}_rw:"]
        if act == "open":
            fire += [f"    hex.set 1, dreq + {d}*dw, 1"]
        else:
            assert act == "close", act
            fire += [f"    hex.if0 1, dstate + {d}*dw, {p}_no",
                     f"    hex.set 1, ddir + {d}*dw, {CLOSING}", f"    hex.set 1, dsub + {d}*dw, {SPEED}"]
        if geo[0] == "d":
            out += _crossed_d_lines(p, geo[1:], radius, fire)
        else:
            out += _crossed_lines(p, *geo, radius, fire)
    return out


def _crossed_d_lines(p: str, seg, radius: int, fire, regs=("cm_ox", "cm_oy", "viewx", "viewy")) -> list:
    """M8 L2: `doors.crossed` for a SLANTED trigger in fj, on the move (old x, old y) -> (new x, new y) (`regs`,
    16.16): P_PointOnLineSide of the two centres differ (`sim.point_side`), and the new box is in the move's spechit
    (`_straddle_d_lines`) -> the `fire` lines; either way on to `<p>_no`."""
    ox, oy, nx, ny = regs
    data, consts = _line_consts(p, seg)
    v1x, v1y, dx, dy = consts
    return [*data, f"    ;{p}_sg", f"  {p}_so: hex.vec 1", f"  {p}_sn: hex.vec 1", f"  {p}_sg:",
            f"    sim.point_side {p}_so, {ox}, {oy}, {v1x}, {v1y}, {dx}, {dy}",
            f"    sim.point_side {p}_sn, {nx}, {ny}, {v1x}, {v1y}, {dx}, {dy}",
            f"    hex.cmp 1, {p}_so, {p}_sn, {p}_x, {p}_no, {p}_x",
            f"  {p}_x:",
            *_straddle_d_lines(f"{p}_b", seg, nx, ny, radius << 16, f"{p}_fire", f"{p}_no", consts=consts),
            f"  {p}_fire:", *fire, f"  {p}_no:"]


def _crossed_lines(p: str, axis: str, coord: int, lo: int, hi: int, radius: int, fire,
                   regs=("cm_ox", "cm_oy", "viewx", "viewy")) -> list:
    """`doors.crossed` in fj on the move (`cm_ox`, `cm_oy`) -> (`viewx`, `viewy`): the centre
    changed side of the axis line (`c <= L`) and the new centre is strictly inside the segment's
    extent inflated by `radius` -> the `fire` lines; either way on to `<p>_no`. The walk-over doors
    (`walkover_lines`, behind their W1 latch) and the WR lifts (`movercode.lift_walk_lines`). M7 P3.2b: `regs` =
    (old x, old y, new x, new y), 16.16 -- a monster's step (`monstermove.move_leaf_lines`)."""
    ox, oy, nx, ny = regs
    a_old, a_new, o_new = (oy, ny, nx) if axis == "y" else (ox, nx, ny)
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
