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

import functools
import json
from pathlib import Path

# Door height QUANTISATION, in map units per stop -- and the knob that decides how SMOOTH a door
# looks, which SPEED does not. A door slides through `travel/quant` stops, so a coarse quant makes
# each phase visibly large no matter how many frames it is held for.
#
# TWO CEILINGS BOUND IT, and the second one is not obvious:
#   * MAX_STATES = 16, because the fj switch index is one nibble;
#   * THE PID BYTE. Every door stop is a distinct (ceiling key, floor key) pair, and a pid must fit
#     PID_NIBBLES = 2 nibbles, so the whole map gets 255 of them. E1M1 spends 142 on its static
#     geometry, leaving 113 for door stops -- a budget a quant change can blow without touching
#     anything that looks related. `tests/host/test_doors.py` guards it in 0.3 s; finding out from
#     an AssertionError ten minutes into a build is how this was learned.
#
# MEASURED on E1M1 (door 10 travels 124 units, the longest; pid totals cross-checked against a
# real build, which asserted exactly 263 at quant 10):
#     quant 16 -> 9 stops,  8 frames at SPEED 1, 222 pids   <-- SHIPPED: ~27% faster than quant 12
#     quant 12 -> 12 stops, 11 frames,           245 pids   (smoother, and what shipped before)
#     quant 11 -> 13 stops, 12 frames,           255 pids   (fits with ZERO margin)
#     quant 10 -> 14 stops, 13 frames,           263 pids   OVERFLOWS the pid byte
#     quant  8 -> 17 stops,                                 OVERFLOWS MAX_STATES = 16
#
# ⚠ THERE IS NO SETTING THAT IS BOTH FASTER AND AS SMOOTH, and it is worth being plain about why.
# At SPEED = 1 the door advances one stop per frame, so frames = stops - 1 and the number of
# DISTINCT POSITIONS the eye sees is frames + 1. Fewer frames IS fewer visible positions; the two
# are the same quantity counted from different ends. Nothing in `door_tic` or its fj mirror
# supports a stride, SPEED is frames-per-stop and cannot be 0 or fractional, and the wall-clock is
# frames x frame-time. "30% faster" therefore costs ~25% of the animation's positions.
#
# ⚠ AND THE HEADLINE IS DOOR 10's, not the map's. Over all 13 E1M1 doors, quant 12 -> 16 takes the
# total frames-to-open from 126 to 94 = 25.4%. Per door: the nine 124-unit doors 27.3%, sector 48
# (116 units) and sector 84 (60) 20.0%, sectors 54 and 64 (68) only 16.7%. Four of thirteen doors
# get well under 20%, so "the door opens in 8 frames instead of 11" is true of nine of them.
#
# ⚠ MORE STATES ALSO COSTS SIZE: a door seg bakes one constant block per state, so this multiplies
# the per-door fan-out. It is the reason quant cannot simply go to 1.
DEFAULT_QUANT = 16
OPEN_GAP = 4              # P_DoorRaise: min(neighbouring ceiling) - 4


NO_SIDE = (0xFFFF, -1)          # a linedef's missing side: 0xFFFF raw, -1 as the WAD parser gives it


def two_sided_neighbours(lds, sds):
    """sector -> the set of sectors sharing a TWO-SIDED linedef with it: DOOM's getNextSector, which
    skips a line without a back side. The movers' rule (PR #103 review: `neighbours` below reads a
    one-sided line's -1 back as the last sidedef's sector)."""
    out: dict = {}
    for ld in lds:
        if ld.front in NO_SIDE or ld.back in NO_SIDE:
            continue
        f, b = sds[ld.front].sector, sds[ld.back].sector
        if f != b:
            out.setdefault(f, set()).add(b)
            out.setdefault(b, set()).add(f)
    return out


def neighbours(lds, sds):
    """sector -> the set of sectors sharing a linedef with it. ⚠ KNOWN DEVIATION (issue #104 F1): a
    one-sided line's back is -1 from the parser and reads `sds[-1]` (sector 105) here, so walk-over
    door 145 opens to 228 where DOOM opens it to 260. The doors keep it because the true height
    needs 256 plane ids, past the byte (PR #103, 2026-09-29); `two_sided_neighbours` is DOOM's rule."""
    out: dict = {}
    for ld in lds:
        f = sds[ld.front].sector if ld.front != 0xFFFF and ld.front < len(sds) else None
        b = sds[ld.back].sector if ld.back != 0xFFFF and ld.back < len(sds) else None
        if f is not None and b is not None and f != b:
            out.setdefault(f, set()).add(b)
            out.setdefault(b, set()).add(f)
    return out


# M8 (the E1M2 playtest, 2026-10-18): the legacy rule above reads a one-sided line's missing back as the LAST sidedef's
# sector -- on E1M2 sector 309 (ceiling 152), which capped five doors at 148: blue door 54 (floor 136) opened 12
# units and could never be passed. Every map takes DOOM's rule (`two_sided_neighbours`: getNextSector skips a line
# without a back) EXCEPT the shipped E1M1 family, whose door stops its one-byte pid budget froze (PR #103) --
# recognised by its own sizes: Freedoom E1M1 (assets / tests/fixtures) and the tests' e1m1_lite, which carries the
# same doors. (sectors, linedefs, sidedefs).
LEGACY_NEIGHBOUR_MAPS = frozenset({(182, 1175, 1829), (118, 836, 1228)})


def door_neighbours(secs, lds, sds) -> dict:
    """the neighbours a door's open height is found among (P_FindLowestCeilingSurrounding): DOOM's
    `two_sided_neighbours`, or the legacy `neighbours` on the E1M1 family (LEGACY_NEIGHBOUR_MAPS)"""
    if (len(secs), len(lds), len(sds)) in LEGACY_NEIGHBOUR_MAPS:
        return neighbours(lds, sds)
    return two_sided_neighbours(lds, sds)


def _door_lines_of(secs, lds, sds) -> dict:
    """M8 L2: `{sector: {"manual": {kind}, "walk": {kind}, "switch": {kind}}}` -- the door kind every DOOR line asks
    of a sector: a MANUAL line's (DR / D1, EV_VerticalDoor: the sector behind it), a walk-over line's (W1,
    P_CrossSpecialLine -> EV_DoDoor) and a switch line's (S1 / SR, P_UseSpecialLine -> EV_DoDoor): the sectors their
    TAG names. Only door specials: a lift's or a floor's line behind a shut sector makes no door."""
    out: dict = {}
    for ld in lds:
        if ld.special in MANUAL_DOOR_KINDS and ld.back not in NO_SIDE and ld.back < len(sds):
            out.setdefault(sds[ld.back].sector, {}).setdefault("manual", set()).add(MANUAL_DOOR_KINDS[ld.special])
    for src, table in (("walk", WALK_DOOR_KINDS), ("switch", {s: k for s, (k, _o) in SWITCH_DOOR_KINDS.items()})):
        tags: dict = {}
        for ld in lds:
            if ld.special in table and ld.tag:
                tags.setdefault(ld.tag, set()).add(table[ld.special])
        for si, sec in enumerate(secs):
            if sec.tag in tags:
                out.setdefault(si, {}).setdefault(src, set()).update(tags[sec.tag])
    return out


def door_sectors(secs, lds, sds) -> dict:
    """{sector index: fully-open ceil_h} for every REAL door on the map: a sector behind a door line's
    back side, and (M7 P2a.1) a sector a walk-over door line TAGS -- E1M1's 77 and 145, which no line
    has behind it (`door_kinds`).

    M8 L2 (E1M2): only DOOR specials make a door (`_door_lines_of`; every special E1M1 has behind a shut
    sector is one, so its 15 doors and their order are unchanged), a switch door line (SR 63, S1 103)
    tags doors as a walk-over line does, and a sector stored OPEN is a door when every line that moves
    it opens it to STAY (E1M2's 208: D1 31 and S1 103, its ceiling 80 over its floor 64) -- EV_DoDoor's
    open rises from the ceiling the sector has and never closes, so its stops start at that ceiling
    (`door_states`). A stored-open sector a re-closing door line moves stays out: it would close to its
    floor, below its state 0."""
    nb = door_neighbours(secs, lds, sds)      # M8: DOOM's rule off the E1M1 family
    out = {}
    lines_of = _door_lines_of(secs, lds, sds)
    candidates = []
    for ld in lds:                     # E1M1's order: the doors behind lines first, in linedef order
        if ld.special in MANUAL_DOOR_KINDS and ld.back not in NO_SIDE and ld.back < len(sds):
            candidates.append(sds[ld.back].sector)
    candidates += [si for si in range(len(secs)) if set(lines_of.get(si, ())) - {"manual"}]
    for si in candidates:
        s = secs[si]
        if s.ceil_h != s.floor_h:
            # already open: a lift or a trigger sector, not a door -- unless every line moving it opens it to stay
            stay = all(KIND_MOTION[k][1] for ks in lines_of[si].values() for k in ks)
            if not stay or not nb.get(si) or min(secs[n].ceil_h for n in nb[si]) - OPEN_GAP <= s.ceil_h:
                continue
        if not nb.get(si):
            continue
        open_h = min(secs[n].ceil_h for n in nb[si]) - OPEN_GAP
        # M4 (2026-08-31): ...and neither is a sector whose "fully open" ceiling lands BELOW its own
        # floor. `open_h` is min(neighbouring ceiling) - 4, and on five of the nine E1 maps some
        # sector behind a special linedef has every neighbour ceiling at or under its floor -- so
        # opening it would put the ceiling beneath the floor. Those are the sectors that made
        # `door_states` throw on E1M3/4/5/6/7/9 ("state 0 must be shut and the last state fully
        # open, got [84, 88]"): `stops` returns a SORTED set, so an open_h below lo silently swaps
        # the two ends and the assert caught it. Same shape as `sky` in the flag retirement -- one
        # E1M1 fact ("every door sector has a neighbour that clears its floor") standing in for a
        # general one.
        # !! STRICTLY BELOW, and that is what makes this byte-exact on the shipped build: MEASURED
        # 2026-08-31, E1M1 has 13 door sectors, 0 with open_h < floor_h and 0 with open_h ==
        # floor_h, so no sector this repo has ever built with leaves the dict. E1M2 likewise.
        # Counts per map: M3 2/18, M4 7/16, M5 1/7, M6 10/11, M7 5/21, M9 1/11; M8 has no doors.
        if open_h < s.floor_h:
            continue
        out[si] = open_h
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


def shut_h(secs, si: int) -> int:
    """M8 L2: a door's state-0 ceiling -- the one the map stores: its floor for every stored-shut door (all of
    E1M1's), the open ceiling of a stored-open stay door (`door_sectors`)"""
    return secs[si].ceil_h


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
        lo = shut_h(secs, si)
        out[si] = (secs[si].floor_h, quantise(lo, open_h, lo + (open_h - lo) * frac, quant))
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
        st = stops(shut_h(secs, si), open_h, quant)
        assert len(st) <= MAX_STATES, (
            "door sector %d has %d stops at quant %d, past the %d the fj state nibble addresses"
            % (si, len(st), quant, MAX_STATES))
        assert st[0] == shut_h(secs, si) and st[-1] == open_h, (
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
# Frames per HEIGHT STEP -- how fast the door slides, not how long it stays open (that is WAIT).
# A TIC IS A FRAME here, so 1 made a 9-stop door snap open in 8 frames, which reads as a jump
# rather than a door. 2 halves the speed: 16 frames to open, 16 to close.
# ⚠ `dsub` is ONE nibble (doorcode.py asserts 0 < SPEED < 16), and anything that waits for a door
# to finish opening must scale with this -- see m2_std_gate's --open-wait, which now derives from
# it instead of assuming 8.
SPEED = 1                 # frames per height step -- see DEFAULT_QUANT for the real smoothness knob
# ⚠ SCALED WITH THE WALKING SPEED. A TIC IS A FRAME here, so WAIT is how far the player can travel
# while the door is passable: at the old FORWARD_MOVE=50 that was 10*50 = 500 units, ample. When the
# step was corrected to 16 units/tic (see reference_model.FORWARD_MOVE) the same 10 frames became
# 160 units and the door shut in the player's face -- MEASURED: door 10 is passable only on frames
# 3..21 after the press, while walking through it took until frame 48. 32 restores the old reach
# (32*16 = 512 units). `dwait` is WAIT_NIBBLES=2 wide, so anything under 256 fits.
WAIT = 37                 # frames fully open before it closes again
# ⚠ WAIT IS COUPLED TO DEFAULT_QUANT and has to move with it. A faster door reaches "fully open"
# sooner AND starts closing sooner, so the window during which a player can walk through shrinks
# at both ends. MEASURED driving `door_tic` from a frame-0 press: the last passable frame moves
# back 5 (f48 -> f43) going quant 12 -> 16, while m2_std_gate's own schedule starts the
# walk-through leg 3 frames earlier (its --open-wait default is SPEED*(nstates-1)+2, i.e. 13
# frames at quant 12 and 10 at quant 16) -- a net loss of 2 frames of margin. WAIT = 37 makes the
# quant-16 window a strict SUPERSET of the quant-12 one rather than merely a wide-enough one.
USE_RANGE = 64            # map units around a door's trigger lines that count as "at the door"

IDLE, OPENING, CLOSING = 0, 1, 2
# M8 C11: an OPENING door's `wait` is 0 -- except a door an open-stay SWITCH opened though its own kind re-closes (a
# MIXED door, `stay_switch_boxes`: E1M9's 135, DR 1 with S1 103 on its tag): STAY_MARK there, so reaching the top
# sets no wait and it stays open, as EV_DoDoor(open)'s thinker does (`door_tic`'s `stay_used`)
STAY_MARK = 1

# ---- M7 P2a.1: E1M1's door KINDS, stated once ---------------------------------------------------------
# The 13 doors this module was written for are plain DR doors (special 1) -- two of them need the
# blue card (26) and one is a blazing door (117) -- and two more sectors are doors a walk-over line
# opens once and leaves open (special 2, W1 "door open stay", matched by TAG). The model, every gate
# oracle and the fj emitter take the kind of a door from `door_kinds` and its behaviour from here.
# The blazing door's speed: DOOM's VDOORSPEED * 4. A TIC IS A FRAME here and a plain door already
# moves one stop a frame (SPEED = 1, the fastest `sub` allows), so the blazing door moves FOUR stops
# a frame, clamped at both ends -- the same 4:1 ratio, in the only unit this machine has.
BLAZE_STRIDE = 4
# ---- M8 L2: every door kind E1M2 has, from DOOM's tables (p_doors.c EV_VerticalDoor / EV_DoDoor, p_spec.c
# P_CrossSpecialLine, p_switch.c P_UseSpecialLine). A kind is a MOTION (stride, stay) and a card:
#   plain / blue / yellow / red  DR: raise, wait VDOORWAIT, close (vld_normal); the key doors need their card
#   blaze                        DR blazing (vld_blazeRaise): the same, VDOORSPEED*4
#   walkover / stay              open and stay (vld_open): W1 2 by tag, D1 31 on its own line
#   blazestay                    blazing open-stay (vld_blazeOpen): W1 109 by tag, D1 118
# E1M1's kind names are unchanged (they name its emitted door blocks).
KIND_MOTION = {"plain": (1, False), "blue": (1, False), "yellow": (1, False), "red": (1, False),
               "blaze": (BLAZE_STRIDE, False), "walkover": (1, True), "stay": (1, True),
               "blazestay": (BLAZE_STRIDE, True)}
KIND_CARD = {"blue": "blue", "yellow": "yellow", "red": "red"}       # EV_VerticalDoor's key check
# the use key on the door's own line (the sector behind it): DR 1 / 26 / 27 / 28 / 117, D1 31 / 118
MANUAL_DOOR_KINDS = {1: "plain", 26: "blue", 27: "yellow", 28: "red", 117: "blaze", 31: "stay", 118: "blazestay"}
# crossing the line (W1, once per line, by tag): 2 open-stay, 109 blazing open-stay
WALK_DOOR_KINDS = {2: "walkover", 109: "blazestay"}
# the use key on a switch (by tag): SR 63 EV_DoDoor(normal) -- repeatable; S1 103 EV_DoDoor(open) -- once
SWITCH_DOOR_KINDS = {63: ("plain", False), 103: ("stay", True)}
BLUE_DOOR_SPECIALS = frozenset(s for s, k in MANUAL_DOOR_KINDS.items() if k == "blue")      # {26}
YELLOW_DOOR_SPECIALS = frozenset(s for s, k in MANUAL_DOOR_KINDS.items() if k == "yellow")  # {27}
RED_DOOR_SPECIALS = frozenset(s for s, k in MANUAL_DOOR_KINDS.items() if k == "red")        # {28}
BLAZE_DOOR_SPECIALS = frozenset({117})     # DR, blazing
STAY_DOOR_SPECIALS = frozenset({31, 118})  # D1 open-stay (118 blazing)
WALKOVER_SPECIALS = frozenset(WALK_DOOR_KINDS)       # W1 door open-stay, by tag: {2, 109}
SWITCH_DOOR_SPECIALS = frozenset(SWITCH_DOOR_KINDS)  # {63, 103}
# The blue card's touch (the model's `_touch_specials`, doomfj.combat): the boxes overlap -- item
# radius 20 + player radius 16, strict -- and the card is within the player's reach of the floor it
# stands on: kz - z in [-REACH_DOWN, REACH_UP] = [-8, 56]. tests/host/test_doors_p2a.py ties these
# to combat's constants (this module cannot import combat, which imports it).
CARD_BOX, CARD_REACH_UP, CARD_REACH_DOWN = 36, 56, 8


def use_boxes(secs, lds, sds, rng: int = USE_RANGE) -> dict:
    """`{sector: (x0, y0, x1, y1)}` — the box the player must be inside to open that door.

    It is the bounding box of the door's own SPECIAL linedefs, inflated by `rng`. One box per door
    (not per line) so the fj test is four compares against baked constants no matter how many
    lines the door has, and the box is axis-aligned so none of them needs a multiply. M8 L2: the
    MANUAL door lines only (a switch's or a walk-over line's box is not the door's; E1M1's are all
    manual)."""
    out: dict = {}
    for ld in lds:
        if ld.special not in MANUAL_DOOR_KINDS or ld.back == 0xFFFF or ld.back >= len(sds):
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


def in_use_box_fixed(box, x16: int, y16: int) -> bool:
    """The trigger test in 16.16 — what the emitted fj actually compares.

    The fj side has the player's position in 16.16 and bakes the corners shifted, so it compares
    there. Comparing in map units instead means shifting the position down first, and `>>` floors:
    at negative coordinates that rounds the box one unit the wrong way and the two mirrors trigger
    on different frames. Same predicate, one shift apart, and the shift is the bug."""
    x0, y0, x1, y1 = box
    return (x0 << 16) <= x16 <= (x1 << 16) and (y0 << 16) <= y16 <= (y1 << 16)


def door_tic(st: tuple, nstates: int, used: bool, stride: int = 1, stay: bool = False,
             wait_frames: int = WAIT, blocked: bool = False, pass_at: int = 0, stay_used: bool = False) -> tuple:
    """One tic of one door. `st` is `(state, dir, sub, wait)`; returns the next one.

    M7 P2a.1: `stride` stops a step (BLAZE_STRIDE for the blazing door, clamped at both ends) and
    `stay` for a door that stays open (the walk-over doors: reaching the top sets no wait, so it
    never closes, and a press on it at the top changes nothing). M7 P2b: `wait_frames` the frames
    fully "open" before it returns (a lift's LIFT_WAIT at its bottom -- doomfj.movers).
    M7 P2b, REVERSAL ON THINGS (docs/gp-lift-spike.md section 4; T_VerticalDoor's crush branch for
    every E1M1 door type that closes): a CLOSING door whose step would take it from `pass_at` (its
    pass state, or above) to below it goes back UP instead when `blocked` -- a shootable thing
    touches it -- and the state does not move that frame.

    THE WHOLE STATE MACHINE, and it is written with nothing but increments, decrements and
    zero-tests on purpose: that is the instruction set the fj side has cheaply. A compare against a
    bound would cost a constant register and a `hex.cmp` per door per tic; counting `sub` and
    `wait` DOWN to zero, and counting `state` against `nstates - 1` only at the moment it steps,
    keeps an idle door at exactly one 1-nibble test.

    M8 C11, THE MIXED DOOR: `stay_used` -- an open-stay switch pressed this door (its caller asks `switch_ready`: at
    rest, no wait) and `used` did not: shut or part-open, it opens with `wait` = STAY_MARK, so the top sets no wait
    (EV_DoDoor(open): the thinker ends at the top); at the top it changes nothing. A later DR press at the top waits
    and closes (EV_VerticalDoor: a new raise on an idle open sector), as `used` always did. `wait` is 0 in every
    other OPENING, so the top's rule below is the old one for every other door.
    """
    state, dr, sub, wait = st
    top_wait = 0 if stay else wait_frames
    if stay_used and not used and dr != OPENING:
        if state != nstates - 1:
            dr, sub, wait = OPENING, SPEED, STAY_MARK
    if used and dr != OPENING:
        # a press always means "open", including on a door that is closing (DOOM reverses) and on
        # one that is already open and waiting (it restarts the wait).
        if stay and state == nstates - 1:
            return st                            # open for good: nothing to restart
        dr, sub, wait = OPENING, SPEED, 0
        if state == nstates - 1:
            dr, wait = IDLE, top_wait
    if dr == OPENING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            state += stride
            if state >= nstates - 1:
                state, dr, wait = nstates - 1, IDLE, (0 if wait else top_wait)     # M8 C11: wait != 0 -- STAY_MARK
    elif dr == CLOSING:
        sub -= 1
        if sub == 0:
            sub = SPEED
            if blocked and state >= pass_at > state - stride:
                return (state, OPENING, sub, wait)      # reversed on a thing: no step this frame
            state -= stride
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


# -- what geometry a BUILT binary froze -----------------------------------------------------

STAMP_SUFFIX = ".doors.json"


def geometry_stamp(secs, lds, sds, quant: int = DEFAULT_QUANT) -> dict:
    """Everything about door geometry that a built binary BAKES IN and an oracle must match.

    ⚠ WHY THIS EXISTS. A binary bakes one constant block per door STOP; the oracle recomputes the
    stops from `DEFAULT_QUANT` at run time. Nothing tied the two together, so a binary built at
    quant 12 could be gated against an oracle at quant 11 -- and it was, on 2026-09-11, by a
    background job that rewrote this module's constant while a build was in flight. The gate did
    not notice: it reported 285 differing pixels and blamed the renderer, and the door's ceiling at
    state 1 was simply -120 in the binary and -121 in the oracle. Hours went into a bug that did
    not exist.

    `stamp_path`/`write_stamp` put this beside the .fjm at build time; `scratchpad/m2_std_gate.py`
    refuses to run when it disagrees with the live module."""
    return {
        "quant": quant, "speed": SPEED, "wait": WAIT, "max_states": MAX_STATES,
        "open_gap": OPEN_GAP,
        "stops": {str(si): stops(shut_h(secs, si), open_h, quant)
                  for si, open_h in sorted(door_sectors(secs, lds, sds).items())},
    }


def stamp_path(fjm) -> Path:
    return Path(str(fjm) + STAMP_SUFFIX)


def write_stamp(fjm, secs, lds, sds, quant: int = DEFAULT_QUANT) -> Path:
    p = stamp_path(fjm)
    p.write_text(json.dumps(geometry_stamp(secs, lds, sds, quant), indent=1), encoding="utf-8")
    return p


def read_stamp(fjm):
    """The stamp beside `fjm`, or None. A caller that gets None must SAY SO, never assume a match."""
    p = stamp_path(fjm)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def compare_stamp(stamp: dict, secs, lds, sds) -> list:
    """[] when the built geometry matches this process's, else one line per disagreement."""
    live = geometry_stamp(secs, lds, sds)
    bad = []
    for k in ("quant", "speed", "wait", "max_states", "open_gap"):
        if stamp.get(k) != live[k]:
            bad.append("%s: binary %r, this process %r" % (k, stamp.get(k), live[k]))
    bs, ls = stamp.get("stops", {}), live["stops"]
    if set(bs) != set(ls):
        bad.append("door sectors differ: binary %s, this process %s"
                   % (sorted(bs), sorted(ls)))
    else:
        for si in sorted(ls, key=int):
            if bs[si] != ls[si]:
                bad.append("door %s stops: binary %s, this process %s" % (si, bs[si], ls[si]))
    return bad


# ---- M7 P2a.1: the kinds, the card check, the walk-over triggers ----------------------------------------

def door_kinds(secs, lds, sds) -> dict:
    """`{door sector: kind}` (`KIND_MOTION`) -- one kind per `door_sectors` entry: its manual line's
    (the one behind it: it carries the card), else its walk-over line's, else its switch line's.
    M8 L2: every line moving one door must ask the same MOTION of it (asserted: E1M2's 258 is a DR door
    its SR 63 switch also opens, EV_DoDoor(normal) -- the same raise; 208 a D1 open-stay door its S1 103
    switch also opens, EV_DoDoor(open)); E1M1's kinds are its old ones."""
    doors = door_sectors(secs, lds, sds)
    lines_of = _door_lines_of(secs, lds, sds)
    out = {}
    for si in sorted(doors):
        src = lines_of[si]
        for k in ("manual", "walk", "switch"):
            if src.get(k):
                assert len(src[k]) == 1, "door %d has two %s kinds: %s" % (si, k, sorted(src[k]))
                kind = next(iter(src[k]))
                break
        every = {kk for ks in src.values() for kk in ks}
        # M8 C11: ... but a SWITCH may ask the open-STAY form of the door's own motion (a mixed door: E1M9's 135, DR 1
        # with S1 103) -- `stay_switch_boxes` presses it with door_tic's `stay_used`
        mot = KIND_MOTION[kind]
        assert all(KIND_MOTION[kk] == mot or (k2 == "switch" and KIND_MOTION[kk] == (mot[0], True))
                   for k2, ks in src.items() for kk in ks), (
            "door %d is asked two motions: %s" % (si, sorted(every)))
        out[si] = kind
    return out


def door_stride(kind: str) -> int:
    return KIND_MOTION[kind][0]


def door_stay(kind: str) -> bool:
    return KIND_MOTION[kind][1]


def can_open(kind: str, has_blue: bool, has_yellow: bool = False, has_red: bool = False) -> bool:
    """May the player's USE on the door's own line open a door of this kind? A key door needs its
    card (EV_VerticalDoor); a walk-over door has no use line at all. (Whether the door HAS a use
    line is its use box: `use_boxes`.)"""
    if kind == "walkover":
        return False
    need = KIND_CARD.get(kind)
    return need is None or {"blue": has_blue, "yellow": has_yellow, "red": has_red}[need]


def door_card_cell(kind: str):
    """the fj cell holding the card a key door of this kind needs, or None: `pcard` (blue, M7 P2a.1),
    `pcard_y` / `pcard_r` (M8 L2: one nibble each, declared and written by the pickups)"""
    return {"blue": "pcard", "yellow": "pcard_y", "red": "pcard_r"}.get(KIND_CARD.get(kind))


# ---- M8 L2: the switch doors (P_UseSpecialLine -> EV_DoDoor, by tag) --------------------------------------

def switch_door_triggers(secs, lds, sds, verts, rng: int = USE_RANGE) -> list:
    """`[(box, (door sector, ...), once)]` -- `_switch_door_lines` without the line"""
    return [(box, targets, once) for _ld, box, targets, once in _switch_door_lines(secs, lds, sds, verts, rng)]


def _switch_door_lines(secs, lds, sds, verts, rng: int = USE_RANGE) -> list:
    """`[(box, (door sector, ...), once)]`, one per switch door line (SR 63 / S1 103) in linedef order: the
    line's extent inflated by `rng` (`use_boxes`' proximity compromise, as the exit and the floor switch),
    and the doors its tag names.

    EV_DoDoor skips a sector whose door is ACTIVE (`sec->specialdata`): a press reaches a door only while
    it is still -- `switch_ready`. An S1 line clears itself on the first press that started a door
    (P_ChangeSwitchTexture(line, 0) after EV_DoDoor returned 1). That latch is NOT kept, and it need not
    be: an S1 door switch's doors are open-STAY doors (asserted), and once such a door has been
    started it moves only up and comes to rest open, where a press changes nothing (`door_tic`) --
    so every press after the first finds nothing to do, latched or not. (The line's TEXTURE latch is
    doomfj.switches' -- a map's SWITCH_TEX; E1M1 animates no switch.)"""
    def xy(v):
        v = verts[v]
        return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])
    doors = door_sectors(secs, lds, sds)
    kinds = door_kinds(secs, lds, sds)
    out = []
    for ld in lds:
        if ld.special not in SWITCH_DOOR_KINDS or not ld.tag:
            continue
        targets = tuple(si for si, sec in enumerate(secs) if sec.tag == ld.tag and si in doors)
        if not targets:
            continue
        once = SWITCH_DOOR_KINDS[ld.special][1]
        # M8 C11: or a MIXED door (a re-closing door this open-stay switch opens to stay: `stay_switch_boxes`) -- there
        # the latch IS seen, and it is NOT kept: a KNOWN SIMPLIFICATION (DOOM: S1 103 clears itself, so after a DR use
        # closed the door the switch does nothing; here it opens it to stay again). level_survey lists such doors.
        assert not once or all(door_stay(kinds[si]) or door_stay(SWITCH_DOOR_KINDS[ld.special][0])
                               for si in targets), (
            "S1 door switch tag %d opens a door that closes: its latch would be seen" % ld.tag)
        (ax, ay), (bx, by) = xy(ld.v1), xy(ld.v2)
        out.append((ld, (min(ax, bx) - rng, min(ay, by) - rng, max(ax, bx) + rng, max(ay, by) + rng), targets, once))
    return out


def switch_boxes(secs, lds, sds, verts, rng: int = USE_RANGE) -> dict:
    """`{door sector: [box, ...]}` -- the switch boxes (`switch_door_triggers`) that press each door as its own kind
    (M8 C11: all but the mixed ones, `stay_switch_boxes`)"""
    return _switch_split(secs, lds, sds, verts, rng)[0]


def stay_switch_boxes(secs, lds, sds, verts, rng: int = USE_RANGE) -> dict:
    """M8 C11: `{door sector: [box, ...]}` -- the MIXED presses: an open-stay switch (S1 103) on a door whose own kind
    re-closes (E1M9's 135, DR 1). A press at rest opens it to STAY (door_tic's `stay_used`); every map before E1M9 has
    none, so its door text and model are unchanged"""
    return _switch_split(secs, lds, sds, verts, rng)[1]


def _switch_split(secs, lds, sds, verts, rng: int = USE_RANGE) -> tuple:
    """(switch_boxes, stay_switch_boxes): every switch door line's box (`_switch_door_lines`, linedef order) under
    each door it names, by the switch's motion against the door's"""
    kinds = door_kinds(secs, lds, sds)
    norm: dict = {}
    mixed: dict = {}
    for ld, box, targets, _once in _switch_door_lines(secs, lds, sds, verts, rng):
        stays = door_stay(SWITCH_DOOR_KINDS[ld.special][0])
        for si in targets:
            (mixed if stays and not door_stay(kinds[si]) else norm).setdefault(si, []).append(box)
    return norm, mixed


def switch_ready(st: tuple) -> bool:
    """EV_DoDoor's `if (sec->specialdata) continue`, on a door's `(state, dir, sub, wait)`: no thinker while
    the door is neither moving nor waiting open (a door at rest shut, or an open-stay door at rest open)"""
    return st[1] == IDLE and st[3] == 0


# M7 P2a.2 -- the exit switch (S1 exit; E1M1: linedef 407): P_UseLines' box, the doors' trigger
# box around the line (`use_boxes`' compromise), one per exit line
EXIT_SPECIALS = frozenset({11})


def exit_boxes(lds, verts, rng: int = USE_RANGE) -> list:
    """`[(x0, y0, x1, y1)]` in map units, one per exit line in linedef order: the line's extent
    inflated by `rng`. `verts`: (x, y) tuples (a compiled map's) or the wad's Vertex objects. The
    model's exit (doomfj.combat), every gate oracle and the emitter take the boxes from here."""
    def xy(v):
        return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])
    out = []
    for ld in lds:
        if ld.special in EXIT_SPECIALS:
            (ax, ay), (bx, by) = xy(verts[ld.v1]), xy(verts[ld.v2])
            out.append((min(ax, bx) - rng, min(ay, by) - rng, max(ax, bx) + rng, max(ay, by) + rng))
    return out


def door_contact_geo(secs, lds, sds, verts) -> dict:
    """M7 P2b: `{door sector: (area, lines)}` for `touches_door`. `area` is the door's rectangle `(x0, y0, x1, y1)`
    when the sector is an axis-aligned rectangle (every E1M1 door: its lines all on its bounding box), else
    `("poly", edges, fits)` with every boundary line as `(x1, y1, x2, y2)` (M8 L0: E1M2's doors 299 and 318 have
    slanted sides; M8 L2: `fits` -- a thing's box could lie wholly inside it, so its contact keeps the centre-inside
    test). `lines` are its two-sided lines: `(axis, coord, lo, hi)` for an axis-aligned one ("y": y = coord, x in
    [lo, hi]), `("d", x1, y1, x2, y2)` for a slanted one."""
    tbl = door_states(secs, lds, sds)
    out = {}

    def xy(v):
        return (verts[v].x, verts[v].y) if hasattr(verts[v], "x") else tuple(verts[v][:2])
    for si in sorted(tbl):
        mine = [ld for ld in lds if sds[ld.front].sector == si
                or (ld.back not in (-1, 0xFFFF) and ld.back < len(sds) and sds[ld.back].sector == si)]
        pts = [xy(v) for ld in mine for v in (ld.v1, ld.v2)]
        xs, ys = [x for x, _ in pts], [y for _, y in pts]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
        lines, rect = [], True
        for ld in mine:
            (ax, ay), (bx, by) = xy(ld.v1), xy(ld.v2)
            if not ((ax == bx and ax in (x0, x1)) or (ay == by and ay in (y0, y1))):
                rect = False                            # a line off the bounding box: not a rectangle
            if ld.back in (-1, 0xFFFF) or ld.back >= len(sds):
                continue                                 # a track wall: nothing stands across it
            if ay == by:
                lines.append(("y", ay, min(ax, bx), max(ax, bx)))
            elif ax == bx:
                lines.append(("x", ax, min(ay, by), max(ay, by)))
            else:
                lines.append(("d", ax, ay, bx, by))
        if rect:
            area = (x0, y0, x1, y1)
        else:
            edges = tuple(xy(ld.v1) + xy(ld.v2) for ld in mine)
            # M8 L2: a slanted (or split) door's contact is a box STRADDLING one of its boundary lines (`touches_door`),
            # and its centre inside the polygon only where a thing's box could lie wholly inside it (`fits`): where
            # none can (the player's, 32 wide, the smallest) and none can hold it (a side over 2 * 31, the widest E1
            # monster's), a box overlapping the door straddles a line of it, and the fj needs no inside test
            # (doorcode.door_contact_lines refuses a closing door that `fits`). E1M2's: 299 and 318 (slanted
            # sides), 30 (two 16-thick strips: one sector, two pieces), 208 (two 32 x 32 squares: fits) -- all
            # open-stay doors, which never close, so none asks for its contact (`door_tic`'s reversal)
            fits = (max(x1 - x0, y1 - y0) <= 2 * MAX_DOOR_THING_R
                    or _square_fits(edges, x0, y0, x1, y1, 32))
            area = ("poly", edges, fits)
        out[si] = (area, lines)
    return out


MAX_DOOR_THING_R = 31          # the widest thing a door reverses on in E1 (the cacodemon; E1M2's widest is 30)


@functools.lru_cache(maxsize=None)
def _square_fits(edges, x0: int, y0: int, x1: int, y1: int, side: int) -> bool:
    """M8 L2: could an axis-aligned `side` x `side` square lie inside the polygon of `edges`? Conservative (True when
    unsure): a fitting square covers a (side-1)^2 block of whole unit cells, each with its centre inside, so no such
    block of inside centres proves no square fits."""
    n = side - 1
    run = {}                                             # (cx, cy) -> the inside run ending there, along y
    best = 0
    for cx in range(x0, x1):
        col = 0
        for cy in range(y0, y1):
            col = col + 1 if _inside_poly(edges, (cx << 16) + 0x8000, (cy << 16) + 0x8000) else 0
            run[cx, cy] = col
    for cy in range(y0, y1):                             # a block of n columns each with an n-run ending at cy
        wide = 0
        for cx in range(x0, x1):
            wide = wide + 1 if run[cx, cy] >= n else 0
            best = max(best, wide)
    return best >= n


def _inside_poly(edges, x16: int, y16: int) -> bool:
    """the 16.16 point STRICTLY inside the polygon of `edges` (map units): an even-odd crossing count on exact integers;
    a point on an edge is not inside (as `touches_door`'s strict rectangle test)"""
    inside = False
    for ax, ay, bx, by in edges:
        ax, ay, bx, by = ax << 16, ay << 16, bx << 16, by << 16
        cr = (bx - ax) * (y16 - ay) - (by - ay) * (x16 - ax)
        if cr == 0 and min(ax, bx) <= x16 <= max(ax, bx) and min(ay, by) <= y16 <= max(ay, by):
            return False                                 # on the boundary
        if (ay > y16) != (by > y16):
            # the edge crosses the horizontal through the point: is the crossing to the point's right?
            if (cr > 0) == (by > ay):
                inside = not inside
    return inside


def straddles_d(ax: int, ay: int, bx: int, by: int, x16: int, y16: int, r16: int) -> bool:
    """M8 L2: does the box of half-width `r16` at (`x16`, `y16`) touch the SLANTED line (`ax`, `ay`)-(`bx`, `by`)
    (all 16.16)? check_position's own test: the boxes overlap, strict, and P_BoxOnLineSide is -1 -- DOOM's two
    extreme corners through P_PointOnLineSide (FixedMul truncation; a point ON the line is its back side). The
    contact (`touches_door`) and the slanted walk-over trigger (`crossed`); the fj is `doorcode._straddle_d_lines`."""
    top, bottom, left, right = y16 + r16, y16 - r16, x16 - r16, x16 + r16
    if right <= min(ax, bx) or left >= max(ax, bx) or top <= min(ay, by) or bottom >= max(ay, by):
        return False
    from doomfj.reference_model import ReferenceModel
    pol = ReferenceModel.point_on_line_side
    if (by - ay > 0) == (bx - ax > 0):                    # ST_POSITIVE: the \ diagonal
        p1, p2 = pol(left, top, ax, ay, bx, by), pol(right, bottom, ax, ay, bx, by)
    else:                                                 # ST_NEGATIVE: the / diagonal
        p1, p2 = pol(right, top, ax, ay, bx, by), pol(left, bottom, ax, ay, bx, by)
    return p1 != p2


def _straddles_axis(axis: str, coord: int, lo: int, hi: int, x16: int, y16: int, r16: int) -> bool:
    """the axis-aligned line's straddle, strict both axes (M7 P2b's rule; map-unit line, 16.16 box)"""
    c, o = (y16, x16) if axis == "y" else (x16, y16)
    return (coord << 16) - r16 < c < (coord << 16) + r16 and (lo << 16) - r16 < o < (hi << 16) + r16


def poly_edges(area) -> list:
    """M8 L2: a slanted door's boundary as `touches_door` tests it: `(axis, coord, lo, hi)` per axis-aligned line,
    `("d", x1, y1, x2, y2)` per slanted one, in `door_contact_geo`'s line order"""
    out = []
    for ax, ay, bx, by in area[1]:
        if ay == by:
            out.append(("y", ay, min(ax, bx), max(ax, bx)))
        elif ax == bx:
            out.append(("x", ax, min(ay, by), max(ay, by)))
        else:
            out.append(("d", ax, ay, bx, by))
    return out


def touches_door(geo, x16: int, y16: int, r16: int) -> bool:
    """M7 P2b, the reversal's contact (docs/gp-lift-spike.md section 4): a thing at 16.16 (x16, y16)
    with half-width r16 touches the door when its box STRADDLES one of the door's two-sided lines --
    check_position's test: the bboxes overlap and P_BoxOnLineSide is -1, which for an axis-aligned
    line is `coord - r < c < coord + r` across it and the extent's `lo - r < o < hi + r` along it,
    all strict -- or its centre is strictly inside the door's rectangle (a 32-thick door holds a
    centred 32-wide box whose edges lie ON both lines). The model's `door_touched` and the fj
    (`doorcode.door_contact_lines`) are this. M8 L0: a slanted line by check_position's own test (the boxes overlap,
    strict, and P_BoxOnLineSide is -1, `reference_model.box_on_line_side`'s semantics). M8 L2: a non-rectangular door
    (`poly`) is touched when the box straddles ANY of its boundary lines -- two-sided or track wall (a box on a track
    wall is a position P_CheckPosition refuses) -- or, only where a box can fit inside it (`door_contact_geo`'s
    `fits`), its centre is strictly inside: the rule the fj runs (for a door that does not `fit`), DOOM's for every
    position a thing can stand at (tests/host/test_e1m2_model.py's grid)."""
    area, lines = geo
    if area[0] == "poly":
        if area[2] and _inside_poly(area[1], x16, y16):
            return True
        lines = poly_edges(area)
    else:
        x0, y0, x1, y1 = area
        if (x0 << 16) < x16 < (x1 << 16) and (y0 << 16) < y16 < (y1 << 16):
            return True
    for ln in lines:
        if ln[0] == "d":
            _, ax, ay, bx, by = ln
            if straddles_d(ax << 16, ay << 16, bx << 16, by << 16, x16, y16, r16):
                return True
        elif _straddles_axis(*ln, x16, y16, r16):
            return True
    return False


def walkover_triggers(secs, lds, sds, verts) -> list:
    """`[(door sector, axis, coord, lo, hi)]` for an axis-aligned trigger -- `axis` "y" for a horizontal
    one (y = coord, x in [lo, hi]), "x" for a vertical one -- and `[(door sector, "d", x1, y1, x2, y2)]`
    for a slanted one (v1 -> v2 as the line runs), sorted: one entry per (trigger, door it opens).

    M8 L2: each W1 LINE is its own trigger (P_CrossSpecialLine) and opens every door its tag names
    (EV_DoDoor) -- E1M2's 109 opens 30 and 266; E1M3's tag 11 is a ring of six lines, two slanted.
    Collinear axis-aligned lines of one tag that touch end to end are FUSED into one segment, which is
    exact: every W1 door line opens its doors to STAY (asserted), so a second line's press finds a
    door already opening or open for good and changes nothing (`door_tic`), and the fused extent is
    the union of the lines'. E1M1's two tags (three collinear lines each) are one segment each, as
    before."""
    def xy(v):
        v = verts[v]
        return (v.x, v.y) if hasattr(v, "x") else (v[0], v[1])
    doors = door_sectors(secs, lds, sds)
    kinds = door_kinds(secs, lds, sds)
    by_tag: dict = {}
    for ld in lds:
        if ld.special in WALK_DOOR_KINDS and ld.tag:
            by_tag.setdefault(ld.tag, []).append(ld)
    out = []
    for tag, lines in by_tag.items():
        targets = [si for si, sec in enumerate(secs) if sec.tag == tag and si in doors]
        assert targets, "walk-over tag %d opens no door" % tag
        assert all(door_stay(kinds[si]) for si in targets), "walk-over tag %d opens a door that closes" % tag
        segs, diag = [], []
        for ld in lines:
            (ax, ay), (bx, by) = xy(ld.v1), xy(ld.v2)
            if ay == by:
                segs.append(("y", ay, min(ax, bx), max(ax, bx)))
            elif ax == bx:
                segs.append(("x", ax, min(ay, by), max(ay, by)))
            else:
                diag.append(("d", ax, ay, bx, by))
        fused: list = []
        for axis, coord, lo, hi in sorted(segs):
            if fused and fused[-1][:2] == (axis, coord) and lo <= fused[-1][3]:
                fused[-1] = (axis, coord, fused[-1][2], max(hi, fused[-1][3]))
            else:
                fused.append((axis, coord, lo, hi))
        for seg in fused + diag:
            out += [(si,) + seg for si in targets]
    return sorted(out)


def crossed(trig: tuple, old16: tuple, new16: tuple, radius: int) -> bool:
    """Did a tic's move from `old16` to `new16` (16.16 centres) cross walk-over trigger `trig`?

    DOOM (P_TryMove -> P_CrossSpecialLine): a line in the move's `spechit` set -- the new box
    touches it -- whose P_PointOnLineSide differs before and after. For an axis-aligned line that
    side is `c <= L` on the crossing axis (a point ON the line counts with the low side), and for a
    move of at most 16 units a side change implies the box straddles the line, so what remains is the
    new box overlapping the segment's extent on the other axis: lo - R < centre < hi + R, strict, as
    PIT_CheckLine's box test. DEVIATION: tested once per tic between the tic's start and end, not
    per P_TryMove of a slide.

    M8 L2, a SLANTED trigger ("d"): DOOM's own two tests -- P_PointOnLineSide of the old and the new
    centre differ, and the new box is in the move's spechit (`straddles_d`: PIT_CheckLine's bbox
    overlap and P_BoxOnLineSide -1)."""
    if trig[1] == "d":
        _si, _d, x1, y1, x2, y2 = trig
        a = (x1 << 16, y1 << 16, x2 << 16, y2 << 16)
        from doomfj.reference_model import ReferenceModel
        pol = ReferenceModel.point_on_line_side
        if pol(old16[0], old16[1], *a) == pol(new16[0], new16[1], *a):
            return False
        return straddles_d(*a, new16[0], new16[1], radius << 16)
    _si, axis, coord, lo, hi = trig
    L = coord << 16
    a, o = (1, 0) if axis == "y" else (0, 1)
    if (old16[a] <= L) == (new16[a] <= L):
        return False
    return ((lo - radius) << 16) < new16[o] < ((hi + radius) << 16)


class DoorPhase:
    """M7 P2a.1 -- a level's doors stepped the way the model and the binary step them, in ONE place,
    for every oracle (the gates, gamespeed's replay, the scenario mirrors): the frame's door phase --
    each door's kind decides its use box and card check, its stride and its stay -- and the
    walk-over triggers after an accepted move, which fire once and press their door on the NEXT door
    phase (the model's `d_monreq` convention).

    The state is plain data, `(ds, fired, req, card)`: `ds` {sector: (state, dir, sub, wait)},
    `fired` a tuple of 0/1 per trigger, `req` a frozenset of door sectors pressed at the next tic,
    `card` 1 once the blue card is taken. `card_at` = (x, y, z) of the card in map units (None: no
    card): `touch` is the model's `_touch_specials` for it -- the boxes overlap (CARD_BOX, strict) and
    the card is within reach of the floor the player stands on."""

    def __init__(self, secs, lds, sds, verts, boxes, quant: int = DEFAULT_QUANT, card_at=None,
                 reversal: bool = True):
        self.card_at = card_at
        tbl = door_states(secs, lds, sds, quant)
        self.order = sorted(tbl)
        self.nstates = {si: len(v) for si, v in tbl.items()}
        self.kinds = door_kinds(secs, lds, sds)
        self.boxes = boxes                                 # use_boxes_xy: no walk-over door in it
        # M7 P2b: reversal on the player (touches_door at the tic-start position); off for a
        # binary before P2b or a control
        self.contact = door_contact_geo(secs, lds, sds, verts) if reversal else None
        self.passes = {si: pass_state(secs, lds, sds, si, quant=quant) for si in self.nstates}
        self.triggers = walkover_triggers(secs, lds, sds, verts)
        self.switches = switch_boxes(secs, lds, sds, verts)       # M8 L2: SR / S1 door switches
        self.stay_switches = stay_switch_boxes(secs, lds, sds, verts)    # M8 C11: the mixed doors' (E1M9's 135)
        self._initial = initial_states(secs, lds, sds, quant)

    def initial(self):
        return (dict(self._initial), (0,) * len(self.triggers), frozenset(), 0)

    def tic(self, state, use: bool, x16: int, y16: int, has_blue=None, others=(), player: bool = True,
            has_yellow: bool = False, has_red: bool = False):
        """`has_blue`: None takes the state's card. `others` (M7 P3.2b): the live monsters' boxes [(x16, y16, r16)]
        -- a closing door reverses on them as on the player (World.door_touched). `player` (M7 P7, P7-c): False for
        a player dead when the tic began -- he holds no closing door (World.door_touched asks `player_alive`; the
        caller also drops his `use`: World._doors_phase's press needs him alive). M8 L2: `has_yellow` / `has_red`
        the other cards (the model's p_cards); a switch box presses its doors that are at rest (`switch_ready`)"""
        ds, fired, req, card = state
        if has_blue is None:
            has_blue = bool(card)
        out = {}
        for si in self.order:
            kind, box = self.kinds[si], self.boxes.get(si)
            pressed = (use and box is not None and can_open(kind, has_blue, has_yellow, has_red)
                       and in_use_box_fixed(box, x16, y16)) or si in req or (
                use and switch_ready(ds[si])
                and any(in_use_box_fixed(b, x16, y16) for b in self.switches.get(si, ())))
            blocked = (self.contact is not None and ds[si][1] == CLOSING
                       and ((player and touches_door(self.contact[si], x16, y16, 16 << 16))
                            or any(touches_door(self.contact[si], ox, oy, orr) for ox, oy, orr in others)))
            # M8 C11: an open-stay switch on a mixed door, at rest
            spress = (use and switch_ready(ds[si])
                      and any(in_use_box_fixed(b, x16, y16) for b in self.stay_switches.get(si, ())))
            out[si] = door_tic(ds[si], self.nstates[si], bool(pressed),
                               stride=door_stride(kind), stay=door_stay(kind), blocked=blocked,
                               pass_at=self.passes[si], stay_used=bool(spress))
        return (out, fired, frozenset(), card)

    def after_move(self, state, old16: tuple, new16: tuple, radius: int = 16):
        ds, fired, req, card = state
        fired, req = list(fired), set(req)
        for k, trig in enumerate(self.triggers):
            if not fired[k] and crossed(trig, old16, new16, radius):
                fired[k] = 1
                req.add(trig[0])
        return (ds, tuple(fired), frozenset(req), card)

    def touch(self, state, cx16: int, cy16: int, here_z: int):
        """the card at one tried candidate (16.16), the player standing on `here_z`"""
        ds, fired, req, card = state
        if card or self.card_at is None:
            return state
        kx, ky, kz = self.card_at
        bd = CARD_BOX << 16
        if abs((kx << 16) - cx16) < bd and abs((ky << 16) - cy16) < bd \
                and -CARD_REACH_DOWN <= kz - here_z <= CARD_REACH_UP:
            return (ds, fired, req, 1)
        return state
