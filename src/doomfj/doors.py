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
