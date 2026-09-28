"""M7 P2b -- E1M1's MOVERS, one module both mirrors run (docs/gp-lift-spike.md; the doors' twin,
doomfj.doors): the two lifts (special 88 WR / 62 SR, DOOM's "Plat Down-Wait-Up-Stay") and the floor
switch (23 S1, "Floor Lower to Lowest"). The model (doomfj.world / combat), every gate oracle and the
emitter take their rules from here.

THE LIFT IS THE DOOR MACHINE ON THE FLOOR. A lift's states are its floor heights from the stored
(top) one DOWN to the lowest surrounding floor, on the doors' zero-aligned grid (`doors.stops`),
state 0 the stored floor. `lift_tic` is `doors.door_tic` with the lift's wait at the bottom
(LIFT_WAIT) and a trigger taken only AT REST at the top: DOOM's active plat ignores new triggers
(EV_DoPlat's specialdata check), and "Down-Wait-Up-Stay" is removed once back up, so a new
trigger then starts a new cycle. Frame tuning (decision D-L1, the spike's default the owner did not
overrule, handoff D11): one 16-unit stop a frame, 26 frames at the bottom.

THE FLOOR SWITCH is instant (D-L2): two states, the stored floor and the lowest surrounding one,
fired once (S1) by a use PRESS in its line's box -- the exit's idiom (`doors.exit_boxes`).

TRIGGERS: a walk-over line (88) is `doors.crossed` on an accepted move, one axis-aligned segment
per LINE (a lift's lines face different ways); a use line (62, 23) is the doors' proximity box
around the line, taken on a use press. Both repeat for the lifts (WR / SR) -- a trigger on a
moving lift is ignored by `lift_tic` -- and the switch fires once.
"""
from __future__ import annotations

from doomfj.doors import (DEFAULT_QUANT, IDLE, MAX_STATES, USE_RANGE, door_tic, neighbours,
                          stops)

LIFT_WALK_SPECIALS = frozenset({88})          # WR Plat Down-Wait-Up-Stay (players; monsters: P3)
LIFT_USE_SPECIALS = frozenset({62})           # SR Plat Down-Wait-Up-Stay (players)
FLOOR_SWITCH_SPECIALS = frozenset({23})       # S1 Floor Lower to Lowest
LIFT_WAIT = 26                                # frames at the bottom (D-L1: 37 x 105/150)


def _tagged(secs, lds, specials) -> list:
    """the sectors the lines with `specials` tag, sorted"""
    tags = {ld.tag for ld in lds if ld.special in specials and ld.tag}
    return sorted(si for si, s in enumerate(secs) if s.tag in tags)


def lowest_surrounding(secs, lds, sds, si: int) -> int:
    """P_FindLowestFloorSurrounding: the lowest floor among `si`'s neighbours"""
    nb = neighbours(lds, sds).get(si)
    assert nb, "sector %d has no neighbours" % si
    return min(secs[n].floor_h for n in nb)


def lift_sectors(secs, lds, sds) -> dict:
    """`{sector: (low, high)}` for every lift: `high` its stored floor, `low` the lowest surrounding
    floor but never above its own (EV_DoPlat's `low`)"""
    out = {}
    for si in _tagged(secs, lds, LIFT_WALK_SPECIALS | LIFT_USE_SPECIALS):
        high = secs[si].floor_h
        out[si] = (min(high, lowest_surrounding(secs, lds, sds, si)), high)
    return out


def lift_states(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: [top, ..., bottom]}`: every floor each lift stops at, state 0 the stored one"""
    out = {}
    for si, (low, high) in lift_sectors(secs, lds, sds).items():
        st = stops(low, high, quant)[::-1]
        assert len(st) <= MAX_STATES, "lift %d has %d stops at quant %d" % (si, len(st), quant)
        out[si] = st
    return out


def switch_sectors(secs, lds, sds) -> dict:
    """`{sector: (low, high)}` for the floor switch's sectors: stored floor -> lowest surrounding"""
    out = {}
    for si in _tagged(secs, lds, FLOOR_SWITCH_SPECIALS):
        high = secs[si].floor_h
        low = lowest_surrounding(secs, lds, sds, si)
        assert low < high, "floor switch sector %d would not lower (%d -> %d)" % (si, high, low)
        out[si] = (low, high)
    return out


def lift_tic(st: tuple, nstates: int, triggered: bool) -> tuple:
    """One frame of one lift, `st` = (state, dir, sub, wait) as a door's: a trigger at rest at the
    top starts the cycle; any other trigger is ignored"""
    state, dr, _sub, wait = st
    at_rest = state == 0 and dr == IDLE and wait == 0     # `sub` is residue once back at the top
    return door_tic(st, nstates, bool(triggered and at_rest), wait_frames=LIFT_WAIT)


def _xy(v):
    return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])


def lift_walk_triggers(secs, lds, sds, verts) -> list:
    """`[(lift sector, axis, coord, lo, hi)]`, one per WR line in linedef order (the shape of
    `doors.walkover_triggers`, so `doors.crossed` tests it)"""
    lifts = lift_sectors(secs, lds, sds)
    out = []
    for ld in lds:
        if ld.special not in LIFT_WALK_SPECIALS:
            continue
        (ax, ay), (bx, by) = _xy(verts[ld.v1]), _xy(verts[ld.v2])
        target = [si for si in lifts if secs[si].tag == ld.tag]
        assert len(target) == 1, target
        if ay == by:
            out.append((target[0], "y", ay, min(ax, bx), max(ax, bx)))
        else:
            assert ax == bx, "lift trigger line is not axis-aligned"
            out.append((target[0], "x", ax, min(ay, by), max(ay, by)))
    return out


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
