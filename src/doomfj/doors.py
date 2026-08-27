"""M2 — what a door IS, in one place.

Every consumer of door geometry goes through here: the oracle-side gate (`scratchpad/door_gate.py`),
the budget tools, the emitter's `sector_heights` override, and — when the runtime door lands — the
fj emitter's baked per-state blocks. The alternative is the same rule written out three times, and
a door the two mirrors disagree about is the failure this repo has already paid for three times
(M14-c, PJ-1, PJ-2).

THE MODEL (DOOM's `P_DoorRaise`):
  * a real door is STORED SHUT — its sector has `ceil_h == floor_h` — behind a special linedef;
  * it opens to `min(neighbouring sector ceiling) - 4`.
  ⚠ The first version of the door gate swept floor -> the WAD's own ceiling instead. For a stored
  shut door that is ZERO MOVEMENT, so the 1,451 px it proudly reported came from a LIFT. A sector
  behind a special line whose ceiling is already above its floor is a lift or a trigger, not a
  door, and `door_sectors` excludes it.

THE QUANTUM: the height a door stops at must be one the emitter can bake, so the sweep is
quantised — see `quantise`, which is the only rounding rule.
"""
from __future__ import annotations

DEFAULT_QUANT = 16
OPEN_GAP = 4              # P_DoorRaise: min(neighbouring ceiling) - 4


def neighbours(lds, sds):
    """sector -> the set of sectors sharing a linedef with it."""
    out: dict = {}
    for ld in lds:
        f = sds[ld.front].sector if ld.front != 0xFFFF and ld.front < len(sds) else None
        b = sds[ld.back].sector if ld.back != 0xFFFF and ld.back < len(sds) else None
        if f is not None and b is not None and f != b:
            out.setdefault(f, set()).add(b)
            out.setdefault(b, set()).add(f)
    return out


def door_sectors(secs, lds, sds) -> dict:
    """{sector index: fully-open ceil_h} for every REAL door on the map."""
    nb = neighbours(lds, sds)
    out = {}
    for ld in lds:
        if not ld.special or ld.back == 0xFFFF or ld.back >= len(sds):
            continue
        si = sds[ld.back].sector
        s = secs[si]
        if s.ceil_h != s.floor_h:          # already open: a lift or a trigger sector, not a door
            continue
        if nb.get(si):
            out[si] = min(secs[n].ceil_h for n in nb[si]) - OPEN_GAP
    return out


def quantise(lo: int, open_h: int, h: float, quant: int = DEFAULT_QUANT) -> int:
    """The height a door actually stops at, given where it would like to be. THE rounding rule.

    ⚠ BOTH ENDPOINTS ARE EXACT, and that is not decoration. Flooring alone can never reach an
    `open_h` that is not a multiple of the quantum — every E1M1 door opens to -4, -12, -60, 60,
    124 or 212, none of which is a multiple of 16 — so a floor-only rule leaves every door in the
    game 12 units short of open, permanently. It also made the budget tools count a fully-open stop
    that the gate could never produce.

    ⚠ AND THE CLAMP IS LOAD-BEARING at the other end. Flooring lands BELOW the floor whenever the
    floor is not a multiple of the quantum: floor -128 at quant 24 floors to -144, a ceiling under
    its own floor.
    """
    if h >= open_h:
        return open_h
    if h <= lo:
        return lo
    return max(lo, min(open_h, int(h // quant) * quant))


def stops(lo: int, open_h: int, quant: int = DEFAULT_QUANT) -> list:
    """Every height this door can stop at, shut..open inclusive — one baked state each.

    ⚠ THE GRID IS ALIGNED TO ZERO, NOT TO THE FLOOR. Stepping `quant` at a time from `lo` and
    quantising each step misses grid points whenever `lo` is not itself a multiple: floor -128,
    open -60, quant 24 walks -128/-104/-80 and reports {-128,-120,-96,-60}, but `quantise` will
    happily return -72 for a door partway between them. The two disagreed, and this list is what
    the budget tools count STATES with while `quantise` is what actually produces them — so the
    tools would have priced a door with a state it could reach and they had not counted.
    Enumerate the grid itself."""
    out = {lo, open_h}
    k = (lo // quant) * quant
    while k < open_h:
        if k > lo:
            out.add(k)
        k += quant
    return sorted(out)


def heights_at(secs, lds, sds, frac: float, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: (floor_h, ceil_h)}` with every door at `frac` of its sweep — the override
    `reference_model.apply_sector_heights` takes, and the one the emitter takes."""
    out = {}
    for si, open_h in door_sectors(secs, lds, sds).items():
        lo = secs[si].floor_h
        out[si] = (lo, quantise(lo, open_h, lo + (open_h - lo) * frac, quant))
    return out


# ---------------------------------------------------------------------------------------------
# M2-R3/R4 — the RUNTIME door: the same geometry, addressed by a per-door STATE INDEX.
#
# R2 baked one chosen height per door and proved the render path handles a door away from where
# the wad stored it. A runtime door is that, once per state, with a nibble choosing which. So the
# state index is the unit both mirrors speak, and everything below turns an index into geometry:
# `door_states` enumerates them, `heights_for_states` turns a state VECTOR into the same
# `{sector: (floor, ceil)}` override `apply_sector_heights` and the emitter already take.
#
# ⚠ THE INDEX IS A NIBBLE. fj addresses the per-state constant blocks with a 1-nibble switch, so a
# door with more than 16 stops cannot be dispatched -- asserted here rather than discovered as a
# wrong picture. At quant 16 E1M1's widest door has 9.
# ---------------------------------------------------------------------------------------------

MAX_STATES = 16           # the fj switch index is one nibble
SHUT = 0                  # state 0 is always the stored (shut) height, by construction of `stops`


def door_states(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: [shut_h, ..., open_h]}` — every height each door can stop at, in index order.

    Index 0 is shut and index -1 is fully open for every door, but the LENGTHS DIFFER (a door with
    124 units of travel has 9 stops at quant 16; one with 60 has 5). Two doors at "state 3" are not
    at the same height and are not meant to be — the index addresses a per-door block."""
    out = {}
    for si, open_h in door_sectors(secs, lds, sds).items():
        st = stops(secs[si].floor_h, open_h, quant)
        assert len(st) <= MAX_STATES, (
            "door sector %d has %d stops at quant %d, past the %d the fj state nibble addresses"
            % (si, len(st), quant, MAX_STATES))
        assert st[0] == secs[si].floor_h and st[-1] == open_h, (
            "door sector %d: state 0 must be shut and the last state fully open, got %r"
            % (si, st))
        out[si] = st
    return out


def heights_for_states(secs, lds, sds, states: dict, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: (floor_h, ceil_h)}` for a per-door STATE VECTOR `{sector: state index}`.

    A door missing from `states` is shut. An out-of-range index is an error and not a clamp: it
    means the caller and the state table disagree about how many stops this door has, and clamping
    would render a picture neither mirror asked for."""
    tbl = door_states(secs, lds, sds, quant)
    out = {}
    for si, st in tbl.items():
        k = states.get(si, SHUT)
        assert 0 <= k < len(st), (
            "door sector %d: state %d out of range, it has %d stops" % (si, k, len(st)))
        out[si] = (secs[si].floor_h, st[k])
    return out


def open_enough(secs, lds, sds, si: int, k: int, gap: int = 56,
                quant: int = DEFAULT_QUANT) -> bool:
    """Can the player fit through door `si` at state `k`? DOOM's P_TryMove needs `gap` (56) between
    the lowest ceiling and the highest floor. This is what the runtime collision test reads, and it
    is a STATE THRESHOLD rather than a height compare so fj can bake one number per door."""
    st = door_states(secs, lds, sds, quant)[si]
    assert 0 <= k < len(st), "door sector %d: state %d out of range" % (si, k)
    return st[k] - secs[si].floor_h >= gap


def pass_state(secs, lds, sds, si: int, gap: int = 56, quant: int = DEFAULT_QUANT) -> int:
    """The LOWEST state at which door `si` can be walked through — the one number fj bakes per door
    so its collision test is a single compare instead of a height subtraction.

    Returns `len(states)` when no state clears the gap, which reads as "never passable" in the
    `state >= pass_state` test rather than accidentally as "always"."""
    st = door_states(secs, lds, sds, quant)[si]
    for k in range(len(st)):
        if st[k] - secs[si].floor_h >= gap:
            return k
    return len(st)


# ---------------------------------------------------------------------------------------------
# M2-R4 — the TRIGGER and the STATE MACHINE.
#
# R3 made a door a nibble. This decides who writes it. The rule below is the SSOT both mirrors
# run: `reference_model` calls it directly, and the emitted fj is a transliteration of it, so the
# two cannot drift into different doors (which is the failure this repo has paid for three times).
#
# WHERE IT IS DELIBERATELY NOT DOOM, and why:
#   * THE TRIGGER IS PROXIMITY, NOT A LINE TRACE. DOOM's P_UseLines traces 64 units along the
#     player's facing and uses the first special line it crosses. That needs a trace per press;
#     this needs four signed compares against a baked box. The cost of the difference is that you
#     can open a door you are standing beside but not facing. The owner's constraint on this rung
#     is ops, and this is the compromise that buys the most of them.
#   * THE DOOR MOVES IN QUANTISED STEPS, not continuously — see `stops`. It is the same reason:
#     every height it stops at is a baked constant block.
#   * NO KEYS, no monsters opening doors, no crushing. E1M1's 13 doors are all plain DR doors.
# ---------------------------------------------------------------------------------------------

# ⚠ A TIC IS A FRAME. Both tiers run `_player_sim_lines` ONCE per frame (standalone polls the
# keyboard 8 times but simulates once), and a frame is ~28M fj ops. So these are counted in FRAMES,
# not in DOOM's 35 Hz tics: SPEED=4/WAIT=60 would be half a minute of real time to open one door.
SPEED = 1                 # frames per height step (a 9-stop door opens in 8 frames)
WAIT = 10                 # frames fully open before it closes again
USE_RANGE = 64            # map units around a door's trigger lines that count as "at the door"

IDLE, OPENING, CLOSING = 0, 1, 2


def use_boxes(secs, lds, sds, rng: int = USE_RANGE) -> dict:
    """`{sector: (x0, y0, x1, y1)}` — the box the player must be inside to open that door.

    It is the bounding box of the door's own SPECIAL linedefs, inflated by `rng`. One box per door
    (not per line) so the fj test is four compares against baked constants no matter how many
    lines the door has, and the box is axis-aligned so none of them needs a multiply."""
    out: dict = {}
    for ld in lds:
        if not ld.special or ld.back == 0xFFFF or ld.back >= len(sds):
            continue
        si = sds[ld.back].sector
        if si not in door_sectors(secs, lds, sds):
            continue
        for vi in (ld.v1, ld.v2):
            out.setdefault(si, []).append(vi)
    return out


def use_boxes_xy(secs, lds, sds, verts, rng: int = USE_RANGE) -> dict:
    """`use_boxes` resolved through a vertex table to actual coordinates."""
    out = {}
    for si, vis in use_boxes(secs, lds, sds, rng).items():
        xs = [verts[v][0] for v in vis]
        ys = [verts[v][1] for v in vis]
        out[si] = (min(xs) - rng, min(ys) - rng, max(xs) + rng, max(ys) + rng)
    return out


def in_use_box(box, x: int, y: int) -> bool:
    """The trigger test, in MAP UNITS. Both mirrors run this one function."""
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def door_tic(st: tuple, nstates: int, used: bool) -> tuple:
    """One tic of one door. `st` is `(state, dir, sub, wait)`; returns the next one.

    THE WHOLE STATE MACHINE, and it is written with nothing but increments, decrements and
    zero-tests on purpose: that is the instruction set the fj side has cheaply. A compare against a
    bound would cost a constant register and a `hex.cmp` per door per tic; counting `sub` and
    `wait` DOWN to zero, and counting `state` against `nstates - 1` only at the moment it steps,
    keeps an idle door at exactly one 1-nibble test.
    """
    state, dr, sub, wait = st
    if used and dr != OPENING:
        # a press always means "open", including on a door that is closing (DOOM reverses) and on
        # one that is already open and waiting (it restarts the wait).
        dr, sub, wait = OPENING, SPEED, 0
        if state == nstates - 1:
            dr, wait = IDLE, WAIT
    if dr == OPENING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            state += 1
            if state >= nstates - 1:
                state, dr, wait = nstates - 1, IDLE, WAIT
    elif dr == CLOSING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            state -= 1
            if state <= 0:
                state, dr = 0, IDLE
    elif wait:
        wait -= 1
        if wait == 0:
            dr, sub = CLOSING, SPEED
    return (state, dr, sub, wait)


def initial_states(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """`{sector: (0, IDLE, 0, 0)}` — every door shut and still, which is what the emitted
    declarations bake and therefore what the oracle must start from."""
    return {si: (SHUT, IDLE, 0, 0) for si in door_states(secs, lds, sds, quant)}
