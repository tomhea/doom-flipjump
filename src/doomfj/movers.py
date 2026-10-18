"""M7 P2b -- E1M1's MOVERS, one module both mirrors run (docs/gp-lift-spike.md; the doors' twin,
doomfj.doors): the two lifts (special 88 WR / 62 SR, DOOM's "Plat Down-Wait-Up-Stay") and the floor
switch (23 S1, "Floor Lower to Lowest"). The model (doomfj.world / combat), every gate oracle and the
emitter take their rules from here. M8 F1.3 (E1M2): the blazing lifts (120 WR / 123 SR), a lift tag on two
sectors, and every ONE-SHOT FLOOR MOVER (EV_DoFloor: 19, 23, 38, 58, 71, 102) as a group per tag with its own
state cell (`floor_groups`, `switch_cell`) -- E1M1's lifts, switch, cells and emission unchanged.

THE LIFT IS THE DOOR MACHINE ON THE FLOOR. A lift's states are its floor heights from the stored
(top) one DOWN to the lowest surrounding floor, on the doors' zero-aligned grid (`doors.stops`),
state 0 the stored floor. `lift_tic` is `doors.door_tic` with the lift's wait at the bottom
(LIFT_WAIT) and a trigger taken only AT REST at the top: DOOM's active plat ignores new triggers
(EV_DoPlat's specialdata check), and "Down-Wait-Up-Stay" is removed once back up, so a new
trigger then starts a new cycle. Frame tuning (decision D-L1, the spike's default the owner did not
overrule, handoff D11): one 16-unit stop a frame, 26 frames at the bottom. A blazing lift strides two.

THE FLOOR SWITCH is instant (D-L2): two states, the stored floor and the lowest surrounding one,
fired once (S1) by a use PRESS in its line's box -- the exit's idiom (`doors.exit_boxes`). The other
one-shot floors move a stop every FLOOR_SUB frames (turboLower every frame) and stay at their destination.

TRIGGERS: a walk-over line (88) is `doors.crossed` on an accepted move, one axis-aligned segment
per LINE (a lift's lines face different ways); a use line (62, 23) is the doors' proximity box
around the line, taken on a use press. Both repeat for the lifts (WR / SR) -- a trigger on a
moving lift is ignored by `lift_tic` -- and the switch fires once. A W1 floor line may be SLANTED (E1M2's
1972, 1974): `crossed_shape`'s side test is P_PointOnLineSide's cross product, exact (no FixedMul truncation).

KNOWN SIMPLIFICATIONS (M8 F1.3, recorded in docs/handoff-e1m2.md 3): a floor's destination is computed from the
neighbours' STORED floors (EV_DoFloor reads them at the trigger: E1M2's sector 206 borders blazing lift 47, which
could be down then); the S1 switch textures do not change (M8: they do on a SWITCH_TEX map -- doomfj.switches); the
floors move on the doors' 16-unit grid.

M8 C4 (the episode, docs/episode-plan.md 2): 36 W1 turbo lower (71's rule, walked); 20 S1 / 22 W1 raise to the next
higher floor and change the flat (EV_DoPlat raiseToNearestAndChange: PLATSPEED/2, a stop every 8 frames; the
special -- the nukage -- cleared at the trigger, `floor_fired`; the new flat drawn from the first stop on,
`apply_change_flats`); 7 S1 stairs (EV_BuildStairs build8 line for line, `stair_destinations`: an 8-unit grid, a stop
every 8 frames, every step one group); 53 W1 perpetual lift (`perpetual_tic`). Their KNOWN SIMPLIFICATIONS: the
perpetual lift starts DOWN (DOOM rolls P_Random() & 1); the changed flat shows one stop (8 frames) after the trigger
(the damage stops at the trigger, exact); a stair step or a 20 / 22 floor is assumed still at the trigger (EV_* skip a
busy sector: none of E1M3 / E1M6's is a door or another mover -- asserted in `floor_groups`); a lift whose low equals
its high (E1M3's 180, tag 15's second sector) stays a one-state lift, as before.
"""
from __future__ import annotations

from dataclasses import dataclass

from doomfj.doors import (DEFAULT_QUANT, IDLE, MAX_STATES, USE_RANGE, door_tic, two_sided_neighbours,
                          stops)

LIFT_WALK_SPECIALS = frozenset({88, 120})     # WR Plat Down-Wait-Up-Stay (players; monsters: P3); M8: 120 blazing
LIFT_USE_SPECIALS = frozenset({62, 123})      # SR Plat Down-Wait-Up-Stay (players); M8: 123 blazing
# M8 F1.3: the BLAZING lifts (EV_DoPlat blazeDWUS: speed PLATSPEED*8, twice downWaitUpStay's PLATSPEED*4; the same
# wait) -- two stops a frame, clamped at both ends (door_tic's stride), as the blazing door's 4:1 is BLAZE_STRIDE
LIFT_FAST_SPECIALS = frozenset({120, 123})
LIFT_FAST_STRIDE = 2
# P_CrossSpecialLine's non-player list holds 88 and not 120: a monster crossing a blazing lift's WR line does nothing
LIFT_MONSTER_SPECIALS = frozenset({88})
FLOOR_SWITCH_SPECIALS = frozenset({23})       # S1 Floor Lower to Lowest
LIFT_WAIT = 26                                # frames at the bottom (D-L1: 37 x 105/150)
# M8 C4: the PERPETUAL lift (53 W1, EV_DoPlat perpetualRaise): between the lowest surrounding floor (or its own) and the
# highest (or its own) at PLATSPEED -- a quarter of the lift's PLATSPEED*4, a stop every PERP_SUB frames -- waiting
# LIFT_WAIT (PLATWAIT, the lift's) at BOTH ends, for ever once started (`perpetual_tic`). Its first direction is
# P_Random() & 1 in DOOM; here always DOWN (a recorded simplification: no roll, so no stream). A lift slot like the
# others (`lstate` ...), so every reader takes it from `mover_table`; its line is a W1 walk-over (players only: 53 is
# not on P_CrossSpecialLine's monster list).
LIFT_PERPETUAL_SPECIALS = frozenset({53})
PERP_SUB = 4

# M8 F1.3 -- the ONE-SHOT FLOOR MOVERS (EV_DoFloor), each line special's (trigger, destination, frames a stop):
#   * trigger "S" a use press in the line's box (S1), "W" an accepted player move crossing the line (W1);
#   * the destination, P_SpawnFloor's: "lowest" P_FindLowestFloorSurrounding (its own floor among them), "highest"
#     P_FindHighestFloorSurrounding (the neighbours'), "turbo" the highest + 8 when it differs, "up24" its floor + 24;
#   * the speed in frames per 16-unit stop: FLOORSPEED is a quarter of the lift's PLATSPEED*4, whose stop is one a
#     frame (D-L1), so 4; turboLower's FLOORSPEED*4 is the lift's, 1; 0 is INSTANT -- E1M1's floor switch 23 (D-L2:
#     its two states, set by the press), kept for every map so E1M1's binary cannot move.
# A tag's sectors move as ONE machine (a GROUP, `floor_groups`): one state cell `switch_cell(g)`, each sector at
# state k on its own stop (its own travel's grid, held at its destination once there) -- every sector of the tag
# starts at the same frame and moves at the same speed, as EV_DoFloor's thinkers do. The group fires ONCE: a
# one-shot line's special is cleared by its first use (S1/W1), and a second line of the tag finds the sectors busy
# or at their destination (EV_DoFloor's specialdata check) -- raiseFloor24 on one line only (asserted).
FLOOR_SUB = 4
FLOOR_TURBO_SUB = 1
FLOOR_PLAT_SUB = 8            # M8 C4: raiseToNearestAndChange's PLATSPEED/2 (below)
STAIR_SUB = 8                 # M8 C4: build8's FLOORSPEED/4 on its 8-unit grid (below)
FLOOR_SPECIALS = {23: ("S", "lowest", 0),                # S1 Floor Lower to Lowest (E1M1: instant)
                  19: ("W", "highest", FLOOR_SUB),       # W1 Floor Lower to Highest neighbour floor
                  38: ("W", "lowest", FLOOR_SUB),        # W1 Floor Lower to Lowest
                  58: ("W", "up24", FLOOR_SUB),          # W1 Floor Raise 24
                  71: ("S", "turbo", FLOOR_TURBO_SUB),   # S1 Floor Turbo Lower (8 above the highest neighbour)
                  102: ("S", "highest", FLOOR_SUB),      # S1 Floor Lower to Highest neighbour floor
                  # M8 C4 (the episode's movers, docs/episode-plan.md 2):
                  36: ("W", "turbo", FLOOR_TURBO_SUB),   # W1 Floor Turbo Lower (71's, walked over)
                  20: ("S", "nexthigher", FLOOR_PLAT_SUB),   # S1 Raise Plat to the next higher floor + texture
                  22: ("W", "nexthigher", FLOOR_PLAT_SUB),   # W1 the same
                  7: ("S", "stairs8", STAIR_SUB)}            # S1 Build Stairs, 8 a step
# M8 C4: EV_DoPlat raiseToNearestAndChange (20 / 22) moves at PLATSPEED/2, an eighth of the lift's PLATSPEED*4: a
# 16-unit stop every 8 frames. EV_BuildStairs build8 (7) moves at FLOORSPEED/4, one unit a frame: an 8-unit stop (its
# stairsize, `FLOOR_QUANT`) every 8 frames -- on the 16-unit grid it would need 16, past the step timer's nibble.
STAIR_SIZE = 8
FLOOR_QUANT = {7: STAIR_SIZE}                 # a group's grid when it is not the doors' DEFAULT_QUANT
# M8 C4: EV_DoPlat raiseToNearestAndChange -- at the trigger every tagged sector takes the floor flat of the line's
# FRONT sector, and its special is cleared ("NO MORE DAMAGE, IF APPLICABLE"). Here: the damage stops AT THE TRIGGER
# (the group fired: `floor_fired`) -- exact; the flat shows from the group's FIRST STOP on (a recorded simplification:
# `apply_change_flats` reads it off the floor height, so every sector list the mirrors build -- the oracle's
# `scene_sectors`, the emitter's per-state `mover_secs` -- takes it with no state of its own).
FLOOR_CHANGE_SPECIALS = frozenset({20, 22})
FLOOR_WALK_SPECIALS = frozenset(s for s, v in FLOOR_SPECIALS.items() if v[0] == "W")
FLOOR_USE_SPECIALS = frozenset(s for s, v in FLOOR_SPECIALS.items() if v[0] == "S")


def _tagged(secs, lds, specials) -> list:
    """the sectors the lines with `specials` tag, sorted"""
    tags = {ld.tag for ld in lds if ld.special in specials and ld.tag}
    return sorted(si for si, s in enumerate(secs) if s.tag in tags)


def lowest_surrounding(secs, lds, sds, si: int) -> int:
    """P_FindLowestFloorSurrounding: the lowest floor among `si`'s neighbours"""
    nb = two_sided_neighbours(lds, sds).get(si)
    assert nb, "sector %d has no neighbours" % si
    return min(secs[n].floor_h for n in nb)


def highest_surrounding(secs, lds, sds, si: int) -> int:
    """P_FindHighestFloorSurrounding: the highest floor among `si`'s neighbours"""
    nb = two_sided_neighbours(lds, sds).get(si)
    assert nb, "sector %d has no neighbours" % si
    return max(secs[n].floor_h for n in nb)


def lift_sectors(secs, lds, sds) -> dict:
    """`{sector: (low, high)}` for every lift: `high` its stored floor, `low` the lowest surrounding
    floor but never above its own (EV_DoPlat's `low`). M8 C4: a PERPETUAL lift's (53) `high` is the highest
    surrounding floor or its own -- asserted to be its own, so state 0 is still the stored floor (E1M7's 563)."""
    out = {}
    perp = set(_tagged(secs, lds, LIFT_PERPETUAL_SPECIALS))
    for si in _tagged(secs, lds, LIFT_WALK_SPECIALS | LIFT_USE_SPECIALS | LIFT_PERPETUAL_SPECIALS):
        high = secs[si].floor_h
        if si in perp:
            assert highest_surrounding(secs, lds, sds, si) <= high, (
                "perpetual lift %d starts below its highest neighbour: its state 0 would not be its stored floor" % si)
        out[si] = (min(high, lowest_surrounding(secs, lds, sds, si)), high)
    return out


def lift_perpetual(secs, lds, si: int) -> bool:
    """M8 C4: is lift `si` a perpetual one (53)? A sector a perpetual line and another lift line both tag is refused
    (which machine runs it would depend on which line fired first; no map has one)"""
    kinds = {ld.special in LIFT_PERPETUAL_SPECIALS for ld in lds
             if ld.special in (LIFT_WALK_SPECIALS | LIFT_USE_SPECIALS | LIFT_PERPETUAL_SPECIALS)
             and ld.tag and ld.tag == secs[si].tag}
    assert len(kinds) == 1, ("lift %d: perpetual and plain lines tag it" % si, kinds)
    return kinds.pop()


def lift_quant(low: int, high: int, base: int = DEFAULT_QUANT) -> int:
    """M8 F1.3 (docs/f1-big-map-widths.md 5): the least quant >= `base` whose zero-aligned grid gives the lift at most
    MAX_STATES stops -- `base` itself for every E1M1 lift (their stops unchanged); a longer travel (E1M3's lift 84: 19
    stops at 16, E1M4's 33: 17) a coarser one, so its 4-bit state still holds it. The lift then crosses its travel in
    fewer frames -- the same kind of trade as the doors' quant (a simplification: docs/handoff-e1m2.md 3). Every
    caller reads `lift_states`, so the model and the fj cannot disagree about it."""
    q = base
    while len(stops(low, high, q)) > MAX_STATES:
        q += 1
        assert q <= 4 * base, ("no quant up to %d fits the lift %d..%d in %d stops" % (q, low, high, MAX_STATES))
    return q


def lift_states(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: [top, ..., bottom]}`: every floor each lift stops at, state 0 the stored one -- at `quant`, or the
    lift's own coarser `lift_quant` where `quant` would give it more than MAX_STATES stops (M8 F1.3)"""
    out = {}
    for si, (low, high) in lift_sectors(secs, lds, sds).items():
        q = lift_quant(low, high, quant)
        st = stops(low, high, q)[::-1]
        assert len(st) <= MAX_STATES, "lift %d has %d stops at quant %d" % (si, len(st), q)
        out[si] = st
    return out


def lift_stride(secs, lds, si: int) -> int:
    """M8 F1.3: stops a frame for lift `si` -- LIFT_FAST_STRIDE when its tag's lift lines are blazing (120 / 123), 1
    for 88 / 62. A sector both kinds tag would take the speed of the line that fired it: refused (no map has one)."""
    kinds = {ld.special in LIFT_FAST_SPECIALS for ld in lds
             if ld.special in (LIFT_WALK_SPECIALS | LIFT_USE_SPECIALS | LIFT_PERPETUAL_SPECIALS)
             and ld.tag and ld.tag == secs[si].tag}
    assert len(kinds) == 1, ("lift %d: blazing and plain lines tag it" % si, kinds)
    return LIFT_FAST_STRIDE if kinds.pop() else 1


def switch_sectors(secs, lds, sds) -> dict:
    """`{sector: (low, high)}` for the floor switch's sectors: stored floor -> lowest surrounding"""
    out = {}
    for si in _tagged(secs, lds, FLOOR_SWITCH_SPECIALS):
        high = secs[si].floor_h
        low = lowest_surrounding(secs, lds, sds, si)
        assert low < high, "floor switch sector %d would not lower (%d -> %d)" % (si, high, low)
        out[si] = (low, high)
    return out


def lift_tic(st: tuple, nstates: int, triggered: bool, stride: int = 1) -> tuple:
    """One frame of one lift, `st` = (state, dir, sub, wait) as a door's: a trigger at rest at the
    top starts the cycle; any other trigger is ignored. AT REST IS STATE 0: a lift at its top is
    always idle with no wait -- a triggered one steps off 0 on the trigger frame (SPEED 1), a
    returning one goes idle the frame it arrives, and the wait belongs to the bottom -- so the fj
    tests one nibble (tests/fj/test_movers_fj.py's schedules reach every one of these). M8 F1.3: `stride`
    (`lift_stride`) for a blazing lift."""
    return door_tic(st, nstates, bool(triggered and st[0] == 0), stride=stride, wait_frames=LIFT_WAIT)


def perpetual_tic(st: tuple, nstates: int, triggered: bool) -> tuple:
    """M8 C4: one frame of a PERPETUAL lift (53, T_PlatRaise's perpetualRaise), `st` = (state, dir, sub, wait) on the
    lift's cells. NEVER STARTED is (0, IDLE, 0, 0): a trigger then sets it going DOWN (OPENING: state up). Moving, `sub`
    counts PERP_SUB frames a stop; reaching an end it goes IDLE with LIFT_WAIT, its sub 0; the wait run out, it moves
    again -- UP (CLOSING) from the bottom, DOWN from the top -- so once started it is never (0, IDLE, 0, 0) again and
    every later trigger is ignored. Increments, decrements and zero tests only, as `doors.door_tic`."""
    from doomfj.doors import CLOSING, OPENING
    state, dr, sub, wait = st
    assert nstates >= 2, nstates
    if dr == IDLE and not wait:
        if not triggered:
            return st
        dr, sub = OPENING, PERP_SUB
    if dr == OPENING:
        sub -= 1
        if sub == 0:
            state, sub = state + 1, PERP_SUB
            if state == nstates - 1:
                dr, sub, wait = IDLE, 0, LIFT_WAIT
    elif dr == CLOSING:
        sub -= 1
        if sub == 0:
            state, sub = state - 1, PERP_SUB
            if state == 0:
                dr, sub, wait = IDLE, 0, LIFT_WAIT
    else:
        wait -= 1
        if wait == 0:
            dr, sub = (CLOSING if state else OPENING), PERP_SUB
    return (state, dr, sub, wait)


def lift_machine_tic(st: tuple, nstates: int, triggered: bool, stride: int, perpetual: bool) -> tuple:
    """M8 C4: one frame of a lift of either machine -- the ONE dispatch the model and the gates' MoverPhase take"""
    if perpetual:
        assert stride == 1
        return perpetual_tic(st, nstates, triggered)
    return lift_tic(st, nstates, triggered, stride)


def _xy(v):
    return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])


def lift_walk_triggers(secs, lds, sds, verts, specials=LIFT_WALK_SPECIALS | LIFT_PERPETUAL_SPECIALS) -> list:
    """`[(lift sector, axis, coord, lo, hi)]`, one per WR line in linedef order (the shape of
    `doors.walkover_triggers`, so `doors.crossed` tests it). M8 F1.3: one per (line, lift) when the line's tag
    lowers two lifts (E1M2's tag 5: sectors 47 and 209), in sector order -- EV_DoPlat starts every tagged sector;
    `specials` (LIFT_MONSTER_SPECIALS: the lines a monster triggers). M8 C4: the perpetual lift's W1 line (53) too -- a
    request to a running perpetual lift changes nothing (`perpetual_tic`), so W1 needs no latch."""
    lifts = lift_sectors(secs, lds, sds)
    out = []
    for ld in lds:
        if ld.special not in (LIFT_WALK_SPECIALS | LIFT_PERPETUAL_SPECIALS) or ld.special not in specials:
            continue
        (ax, ay), (bx, by) = _xy(verts[ld.v1]), _xy(verts[ld.v2])
        target = [si for si in sorted(lifts) if secs[si].tag == ld.tag]
        assert target, ld
        for si in target:
            if ay == by:
                out.append((si, "y", ay, min(ax, bx), max(ax, bx)))
            else:
                assert ax == bx, "lift trigger line is not axis-aligned"
                out.append((si, "x", ax, min(ay, by), max(ay, by)))
    return out


def lift_slots_of_tag(secs, order) -> dict:
    """M8 F1.3: `{tag: (slot, ...)}` -- every lift a lift line's tag starts (`order` the lifts' sector order)"""
    out: dict = {}
    for k, si in enumerate(order):
        out.setdefault(secs[si].tag, []).append(k)
    return {t: tuple(v) for t, v in out.items()}


def use_line_boxes(secs, lds, verts, specials, rng: int = USE_RANGE) -> list:
    """`[(tag, (x0, y0, x1, y1))]`: the doors' proximity box around each line with `specials`"""
    out = []
    for ld in lds:
        if ld.special in specials:
            (ax, ay), (bx, by) = _xy(verts[ld.v1]), _xy(verts[ld.v2])
            out.append((ld.tag, (min(ax, bx) - rng, min(ay, by) - rng,
                                 max(ax, bx) + rng, max(ay, by) + rng)))
    return out


def mover_heights(secs, lifts: dict, lstates: dict, switch: dict, switched: bool) -> dict:
    """`{sector: (floor, ceil)}` for every mover NOT at its stored floor -- the override
    `reference_model.build_scene(sector_heights=...)` takes, merged with the doors'"""
    out = {}
    for si, k in lstates.items():
        if k:
            out[si] = (lifts[si][k], secs[si].ceil_h)
    if switched:
        for si, (low, _high) in switch.items():
            out[si] = (low, secs[si].ceil_h)
    return out


# ---- M8 F1.3: the one-shot floor movers, a group per tag ---------------------------------------------------------

@dataclass(frozen=True)
class FloorGroup:
    """One tag's floor machine: `heights` = ((sector, (its floor at state 0, 1, ..., n - 1)), ...) in sector order,
    each sector's list padded with its destination; `sub` frames a stop (0: instant); `use` an S1 group (else W1)."""
    tag: int
    special: int
    use: bool
    sub: int
    heights: tuple
    change: tuple = ()          # M8 C4: ((sector, its new floor flat), ...) -- a 20 / 22 group (FLOOR_CHANGE_SPECIALS)

    @property
    def n(self) -> int:
        return len(self.heights[0][1])

    @property
    def sectors(self) -> tuple:
        return tuple(si for si, _h in self.heights)

    def floor(self, si: int, k: int) -> int:
        return dict(self.heights)[si][k]


def floor_destination(secs, lds, sds, si: int, rule: str) -> int:
    """P_SpawnFloor's floordestheight for sector `si` (FLOOR_SPECIALS' rule names)"""
    own = secs[si].floor_h
    if rule == "lowest":
        return min(own, lowest_surrounding(secs, lds, sds, si))
    if rule == "highest":
        return highest_surrounding(secs, lds, sds, si)
    if rule == "turbo":
        h = highest_surrounding(secs, lds, sds, si)
        return h + 8 if h != own else h
    if rule == "up24":
        return own + 24
    if rule == "nexthigher":
        return next_higher_floor(secs, lds, sds, si)
    raise ValueError(rule)


def next_higher_floor(secs, lds, sds, si: int) -> int:
    """M8 C4: P_FindNextHighestFloor(sec, its floor): the least neighbour floor above its own, or its own (none)"""
    own = secs[si].floor_h
    up = [secs[n].floor_h for n in two_sided_neighbours(lds, sds).get(si, ()) if secs[n].floor_h > own]
    return min(up) if up else own


def _sector_lines(secs, lds, sds) -> dict:
    """{sector: [linedef, ...]} in linedef order -- P_GroupLines' `sec->lines` (a line in its front sector's list, and
    in its back sector's when that differs)"""
    out: dict = {}
    for i, ld in enumerate(lds):
        f = sds[ld.front].sector
        out.setdefault(f, []).append(i)
        if 0 <= ld.back < len(sds) and sds[ld.back].sector != f:
            out.setdefault(sds[ld.back].sector, []).append(i)
    return out


ML_TWOSIDED = 4


def stair_destinations(secs, lds, sds, tag: int, size: int = STAIR_SIZE) -> dict:
    """M8 C4: EV_BuildStairs, line for line -> {sector: its destination floor} for every step the line `tag` builds:
    each tagged sector (P_FindSectorFromLineTag's order -- which, as in DOOM, resumes after the LAST step built) rises
    `size`; then, while one of the step's two-sided lines has the step as its FRONT and a back sector with the step's
    floor flat, the height grows by `size` (BEFORE the busy test, DOOM's own order) and that sector, unless already
    rising, is the next step. Every sector is assumed still at the trigger (asserted by the caller: no step is a door
    or another mover)."""
    lines_of = _sector_lines(secs, lds, sds)
    out: dict = {}
    secnum = -1
    while True:
        nxt = [si for si in range(secnum + 1, len(secs)) if secs[si].tag == tag]
        if not nxt:
            return out
        secnum = nxt[0]
        if secnum in out:
            continue
        sec, height, tex = secnum, secs[secnum].floor_h + size, secs[secnum].floor_tex
        out[sec] = height
        ok = True
        while ok:
            ok = False
            for i in lines_of.get(sec, ()):
                ld = lds[i]
                if not ld.flags & ML_TWOSIDED or sds[ld.front].sector != sec or not 0 <= ld.back < len(sds):
                    continue
                t = sds[ld.back].sector
                if secs[t].floor_tex != tex:
                    continue
                height += size
                if t in out:
                    continue
                sec = secnum = t
                out[sec] = height
                ok = True
                break


def floor_groups(secs, lds, sds, quant: int = DEFAULT_QUANT) -> list:
    """Every one-shot floor machine of the map, one per TAG of its lines, in tag order (E1M1: one, the switch's tag 3
    -- `switch_cell(0)` is "fswitch"). Each sector's states run from its stored floor to its destination on the
    zero-aligned grid (`doors.stops`) at the group's quant (`lift_quant` over its sectors: a long travel coarser), or
    -- INSTANT, sub 0 -- the two floors themselves (E1M1's 23, `switch_sectors`' heights)."""
    by_tag: dict = {}
    for ld in lds:
        if ld.special in FLOOR_SPECIALS and ld.tag:
            by_tag.setdefault(ld.tag, []).append(ld.special)
    lifts = set(lift_sectors(secs, lds, sds))
    from doomfj.doors import door_sectors
    taken = set(lifts) | set(door_sectors(secs, lds, sds))    # M8 C4: a sector in one machine only
    out = []
    for tag in sorted(by_tag):
        sps = set(by_tag[tag])
        # M8 C4: one tag, one rule -- a W1 and an S1 line of the same machine may share it (E1M6's tag 1: 22 and 20);
        # the first to fire runs it, the other then finds its sectors busy or arrived (EV_DoPlat's specialdata)
        assert len({FLOOR_SPECIALS[s][1:] for s in sps}) == 1, "tag %d: floor specials %s on one tag" % (tag, sorted(sps))
        sp = min(sps)
        use, rule, sub = FLOOR_SPECIALS[sp]
        assert not (rule == "up24" and len(by_tag[tag]) > 1), "tag %d: raiseFloor24 on two lines" % tag
        if rule == "stairs8":
            dests = stair_destinations(secs, lds, sds, tag)
            sectors = sorted(dests)
        else:
            dests = None
            sectors = [si for si, s in enumerate(secs) if s.tag == tag]
        assert sectors and not set(sectors) & lifts, (tag, sectors)
        assert not set(sectors) & taken, ("tag %d: floor sectors %s already move by another machine"
                                          % (tag, sorted(set(sectors) & taken)))
        taken |= set(sectors)
        travel = {}
        for si in sectors:
            start = secs[si].floor_h
            dest = dests[si] if dests is not None else floor_destination(secs, lds, sds, si, rule)
            assert dest != start, "floor mover sector %d (tag %d) would not move (%d)" % (si, tag, start)
            if sp in FLOOR_SWITCH_SPECIALS:
                assert dest < start, (si, start, dest)            # switch_sectors' assert, the same rule
            travel[si] = (start, dest)
        change = ()
        if sps & FLOOR_CHANGE_SPECIALS:
            # EV_DoPlat: `sec->floorpic = sides[line->sidenum[0]].sector->floorpic` -- the FIRING line's front sector;
            # every line of the tag must agree, or which fired first would matter
            assert sps <= FLOOR_CHANGE_SPECIALS, (tag, sorted(sps))
            flats = {secs[sds[ld.front].sector].floor_tex for ld in lds if ld.tag == tag and ld.special in sps}
            assert len(flats) == 1, ("tag %d: its texture-change lines give the flats %s" % (tag, sorted(flats)))
            flat = flats.pop()
            change = tuple((si, flat) for si in sorted(sectors))
        if sub:
            q = max(lift_quant(min(a, b), max(a, b), FLOOR_QUANT.get(sp, quant)) for a, b in travel.values())
            seqs = {}
            for si, (a, b) in travel.items():
                st = stops(min(a, b), max(a, b), q)
                seqs[si] = st[::-1] if b < a else st
        else:
            seqs = {si: [a, b] for si, (a, b) in travel.items()}
        n = max(len(v) for v in seqs.values())
        assert n <= MAX_STATES, (tag, n)
        heights = tuple((si, tuple(v + [v[-1]] * (n - len(v)))) for si, v in sorted(seqs.items()))
        out.append(FloorGroup(tag, sp, use == "S", sub, heights, change))
    return out


def floor_wide(groups) -> bool:
    """the fswitch layout: E1M1's (one instant group: `fswitch: hex.vec 1`, the model's 1-bit `f_switch`) or the
    WIDE one (two or more groups, or a moving one): `fswitch: hex.vec 2*ng` -- each group's state, then its step
    timer -- and the model's `f_switch` / `f_sub` per group"""
    return len(groups) > 1 or any(g.sub for g in groups)


def switch_cell(g: int) -> str:
    """M8 F1.3 (docs/f1-big-map-widths.md 10): group `g`'s state cell -- THE one name every reader takes"""
    return "fswitch" if g == 0 else "fswitch + %d*dw" % g


def floor_sub_cell(g: int, ng: int) -> str:
    """group `g`'s step timer in the wide layout (0: still)"""
    return "fswitch + %d*dw" % (ng + g)


def fswitch_nibbles(groups) -> int:
    return 2 * len(groups) if floor_wide(groups) else 1


def fswitch_states(groups) -> int:
    """the fswitch vector's STATE cells (its first): one per group in the wide layout, else E1M1's one"""
    return len(groups) if floor_wide(groups) else 1


def floor_trigger(state: int, sub: int, speed: int) -> tuple:
    """a one-shot floor's line used / crossed: an untouched group (state 0, still) starts -- instant to state 1, or
    its step timer set (it steps `speed` frames later, then every `speed`); else nothing (fired once)"""
    if state or sub:
        return state, sub
    return (1, 0) if not speed else (0, speed)


def floor_tic(state: int, sub: int, n: int, speed: int) -> tuple:
    """one frame of a moving floor group: the timer runs down; at 0 it steps, and is set again unless that step
    reached the last state (it stays there for good)"""
    if not sub:
        return state, sub
    sub -= 1
    if sub:
        return state, sub
    state += 1
    return state, (speed if state < n - 1 else 0)


def floor_heights(secs, groups, gstates) -> dict:
    """`{sector: (floor, ceil)}` for every floor-group sector off its stored floor, `gstates[g]` group g's state"""
    out = {}
    for grp, k in zip(groups, gstates):
        if k:
            for si, hts in grp.heights:
                if hts[k] != secs[si].floor_h:
                    out[si] = (hts[k], secs[si].ceil_h)
    return out


def floor_fired(state: int, sub: int) -> bool:
    """M8 C4: has a group's line fired -- its state off 0 or its timer running (`floor_trigger`'s converse)"""
    return bool(state or sub)


def change_table(groups) -> dict:
    """M8 C4: `{sector: (its stored floor, its new flat, group index)}` for every texture-change group's sector"""
    out = {}
    for g, grp in enumerate(groups):
        for si, flat in grp.change:
            out[si] = (dict(grp.heights)[si][0], flat, g)
    return out


def apply_change_flats(secs_now, table: dict):
    """M8 C4: THE flat override of the texture-change floors (FLOOR_CHANGE_SPECIALS) -- `secs_now` (a sector list with
    the movers' heights applied) with each change sector OFF its stored floor wearing its new flat. The group's floors
    only ever rise from the stored one, so "off its stored floor" is "past its first stop". With no table, or no such
    sector moved, the list itself comes back (no copy): E1M1 / E1M2 draw exactly what they drew."""
    if not table:
        return secs_now
    import dataclasses
    out = None
    for si, (h0, flat, _g) in table.items():
        s = secs_now[si]
        if s.floor_h != h0 and s.floor_tex != flat:
            if out is None:
                out = list(secs_now)
            out[si] = dataclasses.replace(s, floor_tex=flat)
    return secs_now if out is None else out


_MAP_CHANGE: dict = {}


def map_change_table(map_wad, mapname: str) -> dict:
    """M8 C4: `change_table` of a map's floor groups, cached per (wad, map) -- {} without a texture-change line (the
    groups are not even built then, so a map whose movers the model refuses still renders its other frames)"""
    key = (id(map_wad), mapname)
    hit = _MAP_CHANGE.get(key)
    if hit is None or hit[0] is not map_wad:
        lds = map_wad.linedefs(mapname)
        tbl = {}
        if any(ld.special in FLOOR_CHANGE_SPECIALS for ld in lds):
            tbl = change_table(floor_groups(map_wad.sectors(mapname), lds, map_wad.sidedefs(mapname)))
        hit = _MAP_CHANGE[key] = (map_wad, tbl)
    return hit[1]


def floor_walk_triggers(lds, verts, groups) -> list:
    """`[(group, shape)]`, one per W1 floor line in linedef order: `shape` ("y", y, x0, x1) / ("x", x, y0, y1) for an
    axis-aligned line (`doors.crossed`'s), ("d", x1, y1, x2, y2) for a slanted one (`crossed_shape`)"""
    gi = {g.tag: k for k, g in enumerate(groups)}
    out = []
    for ld in lds:
        if ld.special not in FLOOR_WALK_SPECIALS or not ld.tag:
            continue
        (ax, ay), (bx, by) = _xy(verts[ld.v1]), _xy(verts[ld.v2])
        if ay == by:
            shape = ("y", ay, min(ax, bx), max(ax, bx))
        elif ax == bx:
            shape = ("x", ax, min(ay, by), max(ay, by))
        else:
            shape = ("d", ax, ay, bx, by)
        out.append((gi[ld.tag], shape))
    return out


def floor_use_boxes(lds, verts, groups, rng: int = USE_RANGE) -> list:
    """`[(group, box)]`, one per S1 floor line in linedef order (`use_line_boxes`' box)"""
    gi = {g.tag: k for k, g in enumerate(groups)}
    return [(gi[t], b) for t, b in use_line_boxes(None, lds, verts, FLOOR_USE_SPECIALS, rng) if t in gi]


def line_side(shape, x16: int, y16: int) -> int:
    """a slanted line's P_PointOnLineSide, exact: 1 (back) when (y - y1)*dx - (x - x1)*dy >= 0, else 0"""
    _d, x1, y1, x2, y2 = shape
    s = (y16 - (y1 << 16)) * (x2 - x1) - (x16 - (x1 << 16)) * (y2 - y1)
    return int(s >= 0)


def crossed_shape(shape, old16: tuple, new16: tuple, radius: int) -> bool:
    """did a tic's move cross a walk-over line: an axis-aligned one by `doors.crossed`; a slanted one when the centre
    changed side (`line_side`) and the new centre is strictly inside the line's bounding box grown by `radius` (the
    axis rule's extent test on both axes -- the same once-per-tic deviation as `doors.crossed`)"""
    from doomfj.doors import crossed
    if shape[0] != "d":
        return crossed((None,) + tuple(shape), old16, new16, radius)
    _d, x1, y1, x2, y2 = shape
    if not (((min(x1, x2) - radius) << 16) < new16[0] < ((max(x1, x2) + radius) << 16)
            and ((min(y1, y2) - radius) << 16) < new16[1] < ((max(y1, y2) + radius) << 16)):
        return False
    return line_side(shape, *old16) != line_side(shape, *new16)


# ---- M8 F1.3: every mover's state cell and floors, ONE table for every reader --------------------------------------

def mover_table(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: (state cell, [its floor at state 0, 1, ...])}` for every mover -- each lift (`lstate + k*dw`, its
    stops) and each floor-group sector (`switch_cell(g)`, its stops). The readers (sight, sound, missiles, the
    collision cells, P_ChangeSector, the renderer) take a mover's cell and heights from here alone."""
    out = {}
    for k, (si, st) in enumerate(sorted(lift_states(secs, lds, sds, quant).items())):
        out[si] = ("lstate + %d*dw" % k, list(st))
    for g, grp in enumerate(floor_groups(secs, lds, sds, quant)):
        for si, hts in grp.heights:
            out[si] = (switch_cell(g), list(hts))
    return out


def cell_heights(table: dict, secs, cell: str, k: int) -> dict:
    """`{sector: (floor, ceil)}` -- every sector moving by `cell`, at state k (clamped to its last), off its stored
    floor: one machine's heights (a floor group's sectors move together)"""
    out = {}
    for si, (c, hts) in table.items():
        if c == cell:
            h = hts[min(k, len(hts) - 1)]
            if h != secs[si].floor_h:
                out[si] = (h, secs[si].ceil_h)
    return out


def mover_secs(table: dict, secs, changes=None) -> dict:
    """`{sector: [the sector list at each of its machine's states]}` -- a lift's list moves that lift alone (P2b's
    construction, unchanged), a floor group's moves the whole group (M8 L1's switch rule). M8 C4: `changes`
    (`change_table`) -- the texture-change floors' flats (`apply_change_flats`); None / {} on every map without one"""
    from doomfj.reference_model import apply_sector_heights
    out = {}
    for si, (cell, hts) in table.items():
        if cell.startswith("lstate"):
            out[si] = [apply_sector_heights(secs, {si: (h, secs[si].ceil_h)}) for h in hts]
        else:
            out[si] = [apply_sector_heights(secs, cell_heights(table, secs, cell, k)) for k in range(len(hts))]
    if changes:                 # M8 C4: the texture-change floors wear their new flat past their first stop
        out = {si: [apply_change_flats(sv, changes) for sv in svs] for si, svs in out.items()}
    return out


class MoverPhase:
    """The movers' frame for a gate ORACLE -- `doors.DoorPhase`'s twin, the model's rules in the
    model's order: the lifts tic on last frame's triggers (`tic`), then the player's use press
    (`use_press`: SR lifts, the S1 switch at once) and accepted move (`after_move`: WR lines) ask
    for the next. The player's triggers only: a gate mirrors the binary, whose monsters trigger
    lifts from P3.

    The state is plain data, `(lifts, req, switched)`: `lifts` a tuple of (state, dir, sub, wait)
    per lift in sector order, `req` a frozenset of lift sectors triggered for the next tic,
    `switched` 1 once the floor switch fired. M8 F1.3: in the wide layout (`floor_wide`) `switched` is the
    fswitch VECTOR -- a tuple of each group's state, then each group's step timer -- the binary's cells."""

    def __init__(self, secs, lds, sds, verts, quant: int = DEFAULT_QUANT):
        self.secs = secs
        self.stops = lift_states(secs, lds, sds, quant)
        self.order = sorted(self.stops)
        self.stride = {si: lift_stride(secs, lds, si) for si in self.order}
        self.perpetual = {si: lift_perpetual(secs, lds, si) for si in self.order}      # M8 C4
        self.walk = lift_walk_triggers(secs, lds, sds, verts)
        self.use = use_line_boxes(secs, lds, verts, LIFT_USE_SPECIALS)
        self.of_tag = {secs[si].tag: si for si in self.order}
        self.lifts_of_tag = {t: tuple(self.order[k] for k in ks)
                             for t, ks in lift_slots_of_tag(secs, self.order).items()}
        self.switch = switch_sectors(secs, lds, sds)
        self.switch_boxes = [b for _t, b in use_line_boxes(secs, lds, verts, FLOOR_SWITCH_SPECIALS)]
        self.groups = floor_groups(secs, lds, sds, quant)
        self.wide = floor_wide(self.groups)
        self.floor_walk = floor_walk_triggers(lds, verts, self.groups)
        self.floor_use = floor_use_boxes(lds, verts, self.groups)

    def _fs(self, sw) -> list:
        """[(state, sub)] per group from the state's `switched`"""
        ng = len(self.groups)
        if not self.wide:
            return [(sw, 0)] if ng else []
        return [(sw[g], sw[ng + g]) for g in range(ng)]

    def _sw(self, fs) -> object:
        if not self.wide:
            return fs[0][0] if fs else 0
        return tuple(s for s, _u in fs) + tuple(u for _s, u in fs)

    def initial(self):
        return (tuple((0, IDLE, 0, 0) for _ in self.order), frozenset(),
                self._sw([(0, 0)] * len(self.groups)))

    def tic(self, state):
        lifts, req, sw = state
        fs = [floor_tic(s, u, g.n, g.sub) for g, (s, u) in zip(self.groups, self._fs(sw))]
        return (tuple(lift_machine_tic(st, len(self.stops[si]), si in req, self.stride[si], self.perpetual[si])
                      for si, st in zip(self.order, lifts)), frozenset(), self._sw(fs))

    def use_press(self, state, x16: int, y16: int):
        from doomfj.doors import in_use_box_fixed
        lifts, req, sw = state
        req = set(req)
        for tag, box in self.use:
            if in_use_box_fixed(box, x16, y16):
                req.update(self.lifts_of_tag[tag])
        fs = self._fs(sw)
        for g, box in self.floor_use:
            if in_use_box_fixed(box, x16, y16):
                fs[g] = floor_trigger(*fs[g], self.groups[g].sub)
        return (lifts, frozenset(req), self._sw(fs))

    def after_move(self, state, old16: tuple, new16: tuple, radius: int = 16):
        from doomfj.doors import crossed
        lifts, req, sw = state
        req = set(req) | {t[0] for t in self.walk if crossed(t, old16, new16, radius)}
        fs = self._fs(sw)
        for g, shape in self.floor_walk:
            if crossed_shape(shape, old16, new16, radius):
                fs[g] = floor_trigger(*fs[g], self.groups[g].sub)
        return (lifts, frozenset(req), self._sw(fs))

    def heights(self, state) -> dict:
        lifts, _req, sw = state
        out = mover_heights(self.secs, self.stops, {si: st[0] for si, st in zip(self.order, lifts)}, {}, False)
        out.update(floor_heights(self.secs, self.groups, [s for s, _u in self._fs(sw)]))
        return out
