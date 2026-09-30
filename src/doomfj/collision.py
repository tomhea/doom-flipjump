"""The player's collision, the fj half's source: DOOM's P_CheckPosition over real linedefs.

`ReferenceModel.check_position` is the oracle -- every linedef, in Python. This module holds what
the emitted program needs to give the same answer: the line constants (`line_rows`, one source for
both mirrors), the COLLISION CELLS the program runs (M7 P1.2, docs/gp-collision-cells.md), their
Python mirror, and the point location M14-e binds things with.

THE CELLS. The map is cut into 32-unit cells (`CELL_SHIFT`). A cell lists every linedef whose bbox
a box of the player's radius, centred ANYWHERE in the cell, does not reject (`cell_lists`: exact
interval arithmetic at 16.16), so the verdict is the all-lines sweep's by construction. The emitted
routine (`collision_cells_fj`) is a jump tree on the centre's hex nibbles to its cell's stub, one
stub per distinct list calling one stub per line, and a line stub that xors its constants into the
argument cells and calls ONE shared `sim.line_test`. `check_position_cells` runs the same
algorithm in Python, which is what lets the host test it against the oracle in a second instead
of a build.

WHAT IT REPLACED. M14-d walked the 256-unit blockmap through packed tables: four corners, ~20 lines
a block, every candidate's row read with `hex.read_table_packed` (~6.8K ops a line, 576K per check,
MEASURED on blocked27 -- docs/plan-gameplay.md section 3). Before that, baking a copy of every
line's test into every block that listed it did not assemble in 50 minutes (docs/opt-experiments.md).
A cell's line stub exists once per LINEDEF and is shared by every cell that lists it, which is what
keeps this one small.

⚠ The emitted code must produce the ORACLE's answer, bit for bit. `tests/host/test_collision_cells.py`
checks the lists and the model; `tests/fj/test_collision_fj.py` runs the emitted routine. The rules
mirror `reference_model`'s `point_on_line_side` / `box_on_line_side` / `line_opening`, including
DOOM's `<=` boundary conventions, which are not the same as the cross product's.
"""
from __future__ import annotations

from doomfj.wall_renderer import _int_part_lines

M32 = 0xFFFFFFFF


def _set(reg: str, value: int, nib: int = 8) -> str:
    return f"    hex.set {nib}, {reg}, {value & M32}"


# ── the line constants: ONE source for both mirrors ──────────────────────────────────────────────

FLAG_ONE_SIDED = 1 << 0
FLAG_BLOCKING = 1 << 1
# The bbox and the SLOPE TYPE are precomputed rather than derived at runtime: they remove four
# runtime min/max pairs and the whole sign-comparison switch from the one piece of fj that has to
# be exactly DOOM.
ST_HORIZONTAL, ST_VERTICAL, ST_POSITIVE, ST_NEGATIVE = 0, 1, 2, 3


def line_rows(lds, verts, secs, sds, ml_blocking: int, *, secs_open=None,
              door_line_ids=frozenset()) -> list:
    """One row per linedef -- `(v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, opentop,
    openbottom)` -- as SIGNED map units where signed.

    `dx`/`dy` rather than v2: the runtime test needs the direction for the slope switch and the two
    FixedMul multipliers, and v2 is one add away when the bbox is wanted. `flags` is the STATIC
    blocking: one-sided, or ML_BLOCKING.

    M2-R4: a line in `door_line_ids` takes its OPENING from `secs_open` (the map with every door
    fully open). A door's blocking is not static, so it is not in the row: while the door is below
    `doors.pass_state` it refuses like a wall, which the emitted line stub decides by reading the
    door's state (`collision_cells_fj`) and the oracle by `scene.blocked_lines`. Baking the opening
    OPEN is what makes that one predicate enough -- the alternative is a per-state opening for a
    `cp_ceil` nothing reads once the gap test has passed."""
    rows = []
    secs_open = secs if secs_open is None else secs_open
    for li, ld in enumerate(lds):
        v1x, v1y = verts[ld.v1]
        v2x, v2y = verts[ld.v2]
        dx, dy = v2x - v1x, v2y - v1y
        is_door = li in door_line_ids
        flags = (FLAG_ONE_SIDED if ld.back == -1 else 0) | \
                (FLAG_BLOCKING if ld.flags & ml_blocking else 0)
        if ld.back == -1:
            opentop = openbottom = 0
        else:
            _sv = secs_open if is_door else secs
            fs, bs = _sv[sds[ld.front].sector], _sv[sds[ld.back].sector]
            opentop, openbottom = min(fs.ceil_h, bs.ceil_h), max(fs.floor_h, bs.floor_h)
        slope = (ST_HORIZONTAL if dy == 0 else ST_VERTICAL if dx == 0 else
                 ST_POSITIVE if (dy > 0) == (dx > 0) else ST_NEGATIVE)
        rows.append((v1x, v1y, dx, dy, min(v1x, v2x), max(v1x, v2x), min(v1y, v2y), max(v1y, v2y),
                     slope, flags, opentop, openbottom))
    return rows


class _RowBake:
    """`box_on_line_side` over a row's geometry, with no compile-time specialisation -- the shape
    `sim.line_test` runs."""

    def __init__(self, v1x, v1y, dx, dy, slope):
        self.v1x, self.v1y, self.dx, self.dy, self.slope = v1x, v1y, dx, dy, slope

    def point_side(self, x, y):
        from doomfj.reference_model import ReferenceModel
        return ReferenceModel.point_on_line_side(x, y, self.v1x, self.v1y,
                                                 self.v1x + self.dx, self.v1y + self.dy)

    def box_side(self, box):
        top, bottom, left, right = box
        if self.slope == ST_HORIZONTAL:
            p1, p2 = int(top > self.v1y), int(bottom > self.v1y)
        elif self.slope == ST_VERTICAL:
            p1, p2 = int(right < self.v1x), int(left < self.v1x)
        elif self.slope == ST_POSITIVE:
            p1, p2 = self.point_side(left, top), self.point_side(right, bottom)
        else:
            p1, p2 = self.point_side(right, top), self.point_side(left, bottom)
        return p1 if p1 == p2 else -1


# ── M7 P1.2: the collision CELLS ───────────────────────────────────────────────────────────────

CELL_SHIFT = 21                   # a cell is floor(c16 / 2**21): 32 map units of a 16.16 coordinate
# the tree resolves 16-unit steps (nibbles 7, 6, 5 of the 16.16 word), so a cell is 2**(CELL_SHIFT -
# 20) of them and the addressable cells are the signed 12-bit 16-unit indices, halved
_HALVES = 1 << (CELL_SHIFT - 20)
_CELL_MIN, _CELL_MAX = -2048 // _HALVES, 2047 // _HALVES


def cell_of(c16: int) -> int:
    """The cell of a 16.16 coordinate, as the emitted tree reads it: the top 11 bits of the
    two's-complement 32-bit word, signed. (The tree jumps on nibbles 7, 6, 5 -- 16-unit steps --
    and both 16-unit halves of a cell lead to the same place.)"""
    c = c16 & M32
    return (c - (1 << 32) if c >> 31 else c) >> CELL_SHIFT


def cell_lists(rows, radius: int) -> dict:
    """`{(cx, cy): (linedef, ...)}` -- every line whose bbox a box of half-width `radius` (16.16)
    centred ANYWHERE in the cell does not reject, ascending. A cell no line can touch is absent.

    check_position's bbox reject is `right <= minx or left >= maxx or top <= miny or bottom >= maxy`,
    all 16.16. The centres that escape the x half form the OPEN interval (minx - r, maxx + r), so a
    cell whose x runs xa..xb has one iff `xb > minx - r and xa < maxx + r`, and the same in y. The
    two halves are independent, so the line needs the cell iff both hold: EXACT, not conservative --
    every listed line is touched by some box in the cell.

    ⚠ COVERAGE IS CHECKABLE AT THE CORNERS, and the tests do it that way. That open interval is at
    least 2r wide, so while 2r is at least the cell (asserted) it cannot sit strictly inside the
    cell: if any centre in the cell escapes the reject, a CORNER does. An unlisted line is rejected
    at all four corners of the cell."""
    S = 1 << CELL_SHIFT
    assert 2 * radius >= S, "the corner argument needs a box at least one cell wide"
    out: dict = {}
    for li, row in enumerate(rows):
        minx, maxx, miny, maxy = (v << 16 for v in row[4:8])
        xs = [c for c in range((minx - radius) // S - 1, (maxx + radius) // S + 2)
              if c * S + S - 1 > minx - radius and c * S < maxx + radius]
        ys = [c for c in range((miny - radius) // S - 1, (maxy + radius) // S + 2)
              if c * S + S - 1 > miny - radius and c * S < maxy + radius]
        for cx in xs:
            for cy in ys:
                out.setdefault((cx, cy), []).append(li)
    bad = [c for c in out if not (_CELL_MIN <= c[0] <= _CELL_MAX and _CELL_MIN <= c[1] <= _CELL_MAX)]
    assert not bad, "cells beyond the tree's 16-bit reach, e.g. %s" % bad[:3]
    return {k: tuple(v) for k, v in out.items()}


def check_position_cells(rows, lists, x16: int, y16: int, radius: int, seed_floor: int,
                         seed_ceil: int, shut=frozenset(), openbottom=None):
    """The cell routine, executed in PYTHON -- what `collision_cells_fj` emits, in its order: the
    centre's cell, each listed line through the one shared test, a wall LATCHING the refusal (a line
    stub cannot jump out of its two calls), and the SEED restored when the latch is set.

    `shut`: the door lines still below their pass state -- the stub xors FLAG_BLOCKING in for them.
    `openbottom`: M7 P2b, `{linedef: floor}` for the mover lines at their movers' present states
    (`mover_openbottoms`) -- the opening floor the stub's per-state block xors in.
    Returns `(ok, floorz, ceilingz)`, map units, as `ReferenceModel.check_position` does."""
    openbottom = openbottom or {}
    ok, floorz, ceilz = True, seed_floor, seed_ceil
    bx_lo, bx_hi = x16 - radius, x16 + radius
    by_lo, by_hi = y16 - radius, y16 + radius
    for li in lists.get((cell_of(x16), cell_of(y16)), ()):
        (v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, opentop, ob) = rows[li]
        ob = openbottom.get(li, ob)
        if (bx_hi <= minx << 16 or bx_lo >= maxx << 16
                or by_hi <= miny << 16 or by_lo >= maxy << 16):
            continue
        if _RowBake(v1x << 16, v1y << 16, dx << 16, dy << 16, slope).box_side(
                (by_hi, by_lo, bx_lo, bx_hi)) != -1:
            continue
        if flags or li in shut:
            ok = False                            # the latch; the remaining lines still run
            continue
        floorz, ceilz = max(floorz, ob), min(ceilz, opentop)
    return (True, floorz, ceilz) if ok else (False, seed_floor, seed_ceil)


def mover_line_openings(lds, sds, secs, mover_secs: dict) -> dict:
    """M7 P2b: `{linedef: [openbottom at state 0, 1, ...]}` for every two-sided line touching a
    mover. `mover_secs` = `{mover sector: [the sector list at each of its states]}` -- a line's
    opening floor is max(front floor, back floor) with the mover at that state (a mover's CEILING
    never moves, so its opentop is the row's). A line between two movers is refused: its opening
    would be two-dimensional (none on E1M1, asserted)."""
    out = {}
    for li, ld in enumerate(lds):
        if ld.back == -1:
            continue
        f, b = sds[ld.front].sector, sds[ld.back].sector
        mv = [m for m in (f, b) if m in mover_secs]
        if not mv:
            continue
        assert len(set(mv)) == 1, "line %d touches two movers %s" % (li, mv)
        out[li] = [max(sv[f].floor_h, sv[b].floor_h) for sv in mover_secs[mv[0]]]
    return out


# the line under test's argument cells and their widths in nibbles, in declaration order -- ONE
# table: CELL_DECLS declares them from it, `_xor_lines` xors that many nibbles, and `line_constants`
# bounds a value by it (a value wider than its cell would be cut, and the line land elsewhere)
ARG_CELLS = (("ca_minx", 8), ("ca_maxx", 8), ("ca_miny", 8), ("ca_maxy", 8),
             ("ca_v1x", 8), ("ca_v1y", 8), ("ca_dx", 8), ("ca_dy", 8),
             ("ca_ob", 8), ("ca_ot", 8), ("ca_slope", 1), ("ca_flags", 1))
_ARG_WIDTH = dict(ARG_CELLS)

# the argument cells and return registers the cell routine adds to the state part
CELL_DECLS = [
    # the line under test. Its stub xors each value in, calls sim.line_test and xors it out again,
    # on every path, so every one of these is ZERO between lines and at every frame's end -- the M1
    # restore set has nothing to restore in them.
    *[f"{cell}: hex.vec {width}" for cell, width in ARG_CELLS],
    # the three calls' return registers (tree -> cell stub -> line stub -> sim.line_test). Every
    # call returns, so they are clean on every exit -- as cs_ret, the seed descent's, always was.
    "cc_ret: hex.vec w/4", "cc_lret: hex.vec w/4", "cc_tret: hex.vec w/4",
]


def line_constants(row) -> list:
    """`[(argument cell, value), ...]` -- what one line's stub xors in, in this order, and ONLY
    what its path through `sim.line_test` reads: the bbox always; v1y for a horizontal line, v1x
    for a vertical one, both plus the sign-extended deltas for a diagonal; the slope and the static
    flags; the opening only for a line that can be passable (flags 0 -- a door's shut bit is added
    at runtime, and an open door reads its opening). Zero values are omitted: there is nothing to
    xor, and an unread cell stays zero."""
    (v1x, v1y, dx, dy, minx, maxx, miny, maxy, slope, flags, opentop, openbottom) = row
    out = [("ca_minx", minx << 16), ("ca_maxx", maxx << 16),
           ("ca_miny", miny << 16), ("ca_maxy", maxy << 16)]
    if slope == ST_HORIZONTAL:
        out.append(("ca_v1y", v1y << 16))
    elif slope == ST_VERTICAL:
        out.append(("ca_v1x", v1x << 16))
    else:
        out += [("ca_v1x", v1x << 16), ("ca_v1y", v1y << 16), ("ca_dx", dx), ("ca_dy", dy)]
    out += [("ca_slope", slope), ("ca_flags", flags)]
    if not flags:
        out += [("ca_ob", openbottom), ("ca_ot", opentop)]
    for cell, v in out:
        assert _ARG_WIDTH[cell] == 8 or 0 <= v < 16 ** _ARG_WIDTH[cell], (cell, v)
    return [(cell, v & M32) for cell, v in out if v & M32]


def _xor_lines(consts) -> list:
    """`hex.xor_by` per NONZERO nibble -- one op per set bit, and an involution, so the same lines
    run twice leave every cell as it was."""
    out = []
    for cell, v in consts:
        for i in range(_ARG_WIDTH[cell]):
            n = (v >> 4 * i) & 0xF
            if n:
                out.append(f"    hex.xor_by {cell} + {i}*dw, {n}" if i else f"    hex.xor_by {cell}, {n}")
    return out


def collision_cells_fj(pfx: str, rows, lists, doors=None, movers=None) -> tuple:
    """`(fj text, root label)`: the player's cell routine for `lists` (`cell_lists`) over `rows`
    (`line_rows`) -- the tree, a stub per distinct list, a stub per listed line, and the ONE
    shared `sim.line_test`.

    `doors`: `{linedef: ((door slot, pass state), ...)}` for the lines a door blocks. Such a line's
    stub reads `dstate + slot*dw` and xors FLAG_BLOCKING in while the state is below the pass
    state -- the predicate the oracle's `blocked_lines` is built from (`doors.pass_state`), so there
    is no second copy of the door's state to keep in step with it. A line on two doors (between two
    door sectors) refuses while EITHER is shut, which is the oracle's union.

    `movers`: M7 P2b, `{linedef: (state cell, [openbottom per state])}` for the lines touching a
    mover (`mover_line_openings`). Such a stub xors its constants WITHOUT the opening floor, then
    `sim.jump16` on the mover's state nibble picks a block that xors that state's floor into
    `ca_ob` around the shared test (states past the last reuse the last block).

    Entered by `stl.fcall <root>, cc_ret` (`sim.check_cells`) once the box, `cp_ok = 1` and the
    seeded opening are set; returns through `cc_ret`. The text jumps over itself, so it can sit
    anywhere in a part. Labels are `{pfx}_cc*`: map-prefixed, since fj top-level labels are global."""
    doors = doors or {}
    movers = movers or {}
    L = f"{pfx}_cc"
    none = f"{L}_none"
    stubs = {key: f"{L}_s{k}" for k, key in enumerate(sorted(set(lists.values())))}
    used = sorted({li for key in stubs for li in key})
    nodes: dict = {}                    # (cell register, nibble, 16 targets) -> label, hash-consed

    def node(reg, nib, targets):
        if all(t == none for t in targets):
            return none
        key = (reg, nib, targets)
        if key not in nodes:
            nodes[key] = f"{L}_n{len(nodes)}"
        return nodes[key]

    def tree(reg, leaf_of):
        """jump16 on nibbles 7, 6, 5 of `reg`; `leaf_of`: {12-bit prefix (unsigned): label}"""
        def sub(keys, depth, prefix):
            if depth == 3:
                return leaf_of.get(prefix, none)
            shift = 4 * (2 - depth)
            targets = []
            for d in range(16):
                p = (prefix << 4) | d
                below = [k for k in keys if k >> shift == p]
                targets.append(sub(below, depth + 1, p) if below else none)
            return node(reg, 7 - depth, tuple(targets))
        return sub(sorted(leaf_of), 0, 0)

    def halves(c):                      # a cell's 16-unit steps, as the unsigned 12-bit prefix
        return [((c * _HALVES) + h) & 0xFFF for h in range(_HALVES)]

    by_col: dict = {}
    for (cx, cy), key in lists.items():
        by_col.setdefault(cx, {})[cy] = stubs[key]
    x_leaf = {}
    for cx in sorted(by_col):
        col = tree("cpy", {p: lab for cy, lab in by_col[cx].items() for p in halves(cy)})
        x_leaf.update({p: col for p in halves(cx)})
    root = tree("cpx", x_leaf)

    out = [f"// M7 P1.2 collision cells: {len(lists)} cells, {len(stubs)} distinct lists, "
           f"{len(used)} lines, {len(nodes)} tree nodes (collision.collision_cells_fj)",
           f";{L}_end"]
    for (reg, nib, targets), lab in nodes.items():
        out += [f"{lab}:", f"    sim.jump16 {reg} + {nib}*dw, " + ", ".join(targets)]
    for key, lab in stubs.items():
        out += [f"{lab}:"] + [f"    stl.fcall {L}_l{li}, cc_lret" for li in key] + \
               ["    stl.fret cc_ret"]
    out += [f"{none}:", "    stl.fret cc_ret"]
    for li in used:
        row = rows[li]
        if li in movers:                  # M7 P2b: the opening floor comes from the mover's state
            assert li not in doors and row[9] == 0, "mover line %d is a door line or blocks" % li
            row = row[:11] + (0,)
        xors = _xor_lines(line_constants(row))
        lab = f"{L}_l{li}"
        out += [f"{lab}:"] + xors
        if li in movers:
            cell, obs = movers[li]
            blocks = [f"{lab}_m{k}" for k in range(len(obs))]
            out += [f"    sim.jump16 {cell}, " + ", ".join(blocks + [blocks[-1]] * (16 - len(blocks)))]
            for k, ob in enumerate(obs):
                obx = _xor_lines([("ca_ob", ob & M32)])
                out += [f"  {blocks[k]}:", *obx, f"    stl.fcall {L}_test, cc_tret", *obx,
                        f"    ;{lab}_mout"]
            out += [f"  {lab}_mout:"]
        elif li in doors:
            assert rows[li][9] == 0, (
                "door line %d carries static flags %d -- xoring FLAG_BLOCKING would clear them"
                % (li, rows[li][9]))
            for k, (slot, pw) in enumerate(doors[li]):
                shut_mask = (1 << min(max(pw, 0), 16)) - 1    # the states below the pass state
                nxt = f"{lab}_d{k + 1}" if k + 1 < len(doors[li]) else f"{lab}_go"
                out += ([f"  {lab}_d{k}:"] if k else []) +                     [f"    hex.if_flags dstate + {slot}*dw, {shut_mask:#06x}, {nxt}, {lab}_shut"]
            out += [f"  {lab}_shut:",
                    f"    hex.xor_by ca_flags, {FLAG_BLOCKING}",
                    f"    stl.fcall {L}_test, cc_tret",
                    f"    hex.xor_by ca_flags, {FLAG_BLOCKING}",
                    f"    ;{lab}_out",
                    f"  {lab}_go:",
                    f"    stl.fcall {L}_test, cc_tret",
                    f"  {lab}_out:"]
        else:
            out.append(f"    stl.fcall {L}_test, cc_tret")
        out += xors + ["    stl.fret cc_lret"]
    out += [f"{L}_test:", "    sim.line_test", "    stl.fret cc_tret", f"{L}_end:"]
    return "\n".join(out) + "\n", root


# ── the emitter's side: the state and the move ─────────────────────────────────────────────────

# The collision scratch the M1/M5 restore sets carry: `sim.line_test`'s corner sides for
# P_BoxOnLineSide. (The table walk's cb_* / cl_* scratch that shared this list -- hoisted out of
# `sim.check_block` / `check_line` so the sets could name it -- died with the walk in M7 P1.2 and
# stayed declared only because both sets named it; M7 P1.4's re-key dropped it.)
CHECK_SCRATCH_DECLS = [
    "cl_side1: hex.vec 1", "cl_side2: hex.vec 1",   # box-corner sides for P_BoxOnLineSide
]


# ⚠ ORDER IS LOAD-BEARING: the restore sets fingerprint each named label's SPAN (the distance to
# the next label), so CELL_DECLS goes AFTER CHECK_SCRATCH_DECLS and nothing is inserted between
# names the sets carry.
COLLISION_STATE_DECLS = [
    "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
    "cbx_lo: hex.vec 8", "cbx_hi: hex.vec 8", "cby_lo: hex.vec 8", "cby_hi: hex.vec 8",
    "cp_ok: hex.vec 1", "cp_floor: hex.vec 8", "cp_ceil: hex.vec 8",
    "cp_seedf: hex.vec 8", "cp_seedc: hex.vec 8", "mv_ok: hex.vec 1",
    "cm_hf: hex.vec 8",                       # the floor the player is standing on now
    "cm_dx: hex.vec 8", "cm_dy: hex.vec 8",   # the tic's desired move
    "cm_ox: hex.vec 8", "cm_oy: hex.vec 8",   # M7 P2a.1: where the tic's move started
    "cs_ret: hex.vec w/4",                    # the seed descent's fcall return
] + CHECK_SCRATCH_DECLS + CELL_DECLS


def move_with_collision_lines(root: str, mapname_pfx: str, *, radius: int, height: int,
                              maxstep: int, pickup=None, after_accept=()) -> list:
    """M14-d — the blocked-move policy, in the emitted program. `root`: the cell routine's entry
    (`collision_cells_fj`).

    `cm_dx`/`cm_dy` hold the tic's desired move and `viewx`/`viewy` the current position; on return
    `viewx`/`viewy` hold the position actually taken. Tries the whole step, then the two
    axis-separated halves — NOT DOOM's `P_SlideMove`, which projects the residual momentum along
    the wall. The oracle implements this same policy (`move_with_collision`), so it is a stated
    difference from vanilla rather than a drift between the mirrors.

    ⚠ Each candidate needs the sector UNDER IT for the check's seed, which is a BSP descent per
    candidate. The descent reads `vx`/`vy`, so those are set from the candidate before it runs.
    That is safe here and only here: this whole block runs BEFORE `_int_part_lines` re-derives
    `vx`/`vy` from the final position for the walk.

    M7 P2a.1: `pickup(tag)` gives the lines that touch the pickups at a TRIED candidate (`cpx`,
    `cpy`), before its P_TryMove -- the model touches at every candidate, taken or refused; and every
    ACCEPTED candidate runs `after_accept` (the walk-over triggers) once, from one shared block, with
    the tic's start in `cm_ox` / `cm_oy`."""

    def candidate(tag, xexpr, yexpr, nxt):
        return [
            *xexpr, *yexpr,
            *(pickup(tag) if pickup else []),
            # the seed: locate the candidate's subsector, then run the full P_TryMove
            *_int_part_lines("vx", "cpx", f"{tag}vxs", f"{tag}vxd"),
            *_int_part_lines("vy", "cpy", f"{tag}vys", f"{tag}vyd"),
            # the seed descent is a CALL, not a jump: it has one exit and four call sites, so it
            # frets to `cs_ret` instead of falling into any one caller's continuation
            f"    stl.fcall {mapname_pfx}_dsccs_walk, cs_ret",
            f"    sim.try_move {root}, {height}, {maxstep}, cm_hf",
            f"    hex.if0 1, mv_ok, {nxt}",
            "    hex.mov 8, viewx, cpx", "    hex.mov 8, viewy, cpy",
            "    ;cmv_accept",
            f"  {nxt}:",
        ]

    out = [
        # ⚠ THE RADIUS, ONCE. `sim.check_cells` READS `cprad` -- it does not set it -- and a
        # declared-but-unwritten hex.vec is ZERO. With cprad = 0 the collision box collapses to a
        # POINT, which walks straight through walls whose line the real 32-unit box would straddle.
        # The standalone tests set it themselves, so they never saw this; the gate's blocked-tic
        # control did, on the first tic where a wall mattered.
        _set("cprad", radius),
        # where the player stands now: its floor is what "too big a step up" is measured against
        "    hex.mov 8, cm_ox, viewx", "    hex.mov 8, cm_oy, viewy",
        "    hex.mov 8, cpx, viewx", "    hex.mov 8, cpy, viewy",
        *_int_part_lines("vx", "cpx", "cmh_vxs", "cmh_vxd"),
        *_int_part_lines("vy", "cpy", "cmh_vys", "cmh_vyd"),
        f"    stl.fcall {mapname_pfx}_dsccs_walk, cs_ret",
        f"    sim.check_cells {root}",
        "    hex.mov 8, cm_hf, cp_floor",
    ]
    out += candidate("cma_", ["    hex.mov 8, cpx, viewx", "    hex.add 8, cpx, cm_dx"],
                     ["    hex.mov 8, cpy, viewy", "    hex.add 8, cpy, cm_dy"], "cmv_b")
    out += candidate("cmb_", ["    hex.mov 8, cpx, viewx", "    hex.add 8, cpx, cm_dx"],
                     ["    hex.mov 8, cpy, viewy"], "cmv_c")
    out += candidate("cmc_", ["    hex.mov 8, cpx, viewx"],
                     ["    hex.mov 8, cpy, viewy", "    hex.add 8, cpy, cm_dy"], "cmv_stay")
    out += ["    ;cmv_done",
            "  cmv_accept:",
            *after_accept,
            "  cmv_done:"]
    return out


# ── M14-e's critical path: POINT LOCATION, baked as code ──────────────────────────────────────
#
# Re-binding things to leaves needs "which subsector is this point in?" once per thing per frame.
# The obvious answer -- reuse `_bsp_descend_code` -- was PRICED and rejected: M14-d's four descents
# cost 11,602,784 ops together, ~2.9M each, so 251 of them would be ~730M ops against a ~40M frame.
# The cost is `proj.point_on_side_leaf`: a generic 10-nibble cross product, plus two fcalls per node
# to set and clear the partition constants through the xor involution.
#
# None of that is needed when the partition is BAKED. `_point_side` is
# `dx*(y - py) - dy*(x - px)`, and dx/dy/px/py are compile-time per node, so:
#
#   * a VERTICAL partition (dx == 0) reduces to one compare of x against px -- no multiply;
#   * a HORIZONTAL one (dy == 0) reduces to one compare of y against py;
#   * only a diagonal needs the cross product, and even then both multipliers are constants, so the
#     row rule (see [[fj-cost-model]]) makes them sparse.
#
# On E1M1 that is 209 vertical + 209 horizontal + 263 diagonal of 681 nodes -- 61% multiply-free --
# and a descent visits ~13 nodes. Exact, not a grid approximation, so it costs no fidelity and
# needs no decision about which leaf owns a thing near a boundary.

def generate_point_location_fj(cmap, *, label="ptloc") -> str:
    """`{label}_walk` reads `ptx`/`pty` (10-nibble SIGNED map units) and leaves the containing
    subsector index in `ptss`, then `stl.fret {label}_ret`. Mirrors `mapcompiler._point_side`'s
    convention exactly: side = dx*(y - py) - dy*(x - px), and side > 0 is the BACK (left) child."""
    from doomfj.mapcompiler import NF_SUBSECTOR
    M40 = (1 << 40) - 1
    out = [f"// M14-e point location as code: {len(cmap.nodes)} nodes, {len(cmap.subsectors)} leaves",
           f"{label}_walk:"]

    def target(child):
        return (f"{label}_l{child & (NF_SUBSECTOR - 1)}" if child & NF_SUBSECTOR
                else f"{label}_n{child}")

    out.append(f"    ;{target(cmap.root)}")
    for i, n in enumerate(cmap.nodes):
        back, front = target(n.left), target(n.right)      # left = back, right = front
        out.append(f"  {label}_n{i}:")
        if n.dx == 0:                                      # side = -dy*(x - px)
            # back iff -dy*(x-px) > 0  iff  (dy > 0 and x < px) or (dy < 0 and x > px)
            lo, hi = (back, front) if n.dy > 0 else (front, back)
            out += [f"    hex.set 10, {label}k, {n.x & M40}",
                    f"    hex.scmp 10, ptx, {label}k, {lo}, {front}, {hi}"]
        elif n.dy == 0:                                    # side = dx*(y - py)
            lo, hi = (front, back) if n.dx > 0 else (back, front)
            out += [f"    hex.set 10, {label}k, {n.y & M40}",
                    f"    hex.scmp 10, pty, {label}k, {lo}, {front}, {hi}"]
        else:                                              # the general cross product
            out += [f"    hex.set 10, {label}k, {n.x & M40}",
                    f"    hex.mov 10, {label}dx, ptx", f"    hex.sub 10, {label}dx, {label}k",
                    f"    hex.set 10, {label}k, {n.y & M40}",
                    f"    hex.mov 10, {label}dy, pty", f"    hex.sub 10, {label}dy, {label}k",
                    # the CONSTANT goes second: fixed_mul_lo/mul_lo cost one schoolbook row per
                    # nonzero nibble of the second operand, and a partition delta is small
                    f"    hex.set 10, {label}k, {n.dx & M40}",
                    f"    hex.mul_lo 10, {label}p, {label}dy, {label}k",
                    f"    hex.set 10, {label}k, {n.dy & M40}",
                    f"    hex.mul_lo 10, {label}q, {label}dx, {label}k",
                    f"    hex.sub 10, {label}p, {label}q",
                    f"    hex.sign 10, {label}p, {front}, {label}_g{i}",   # < 0 -> front
                    f"  {label}_g{i}:",
                    f"    hex.if0 10, {label}p, {front}",                  # == 0 -> front (on the line)
                    f"    ;{back}"]
    for s in range(len(cmap.subsectors)):
        out += [f"  {label}_l{s}:", f"    hex.set w/4, ptss, {s}", f"    stl.fret {label}_ret"]
    return "\n".join(out) + "\n"


def point_location_decls(label="ptloc") -> list:
    # ⚠ ptss is w/4 wide, not 4: `hex.ptr_index` does `mov w/4` OUT of its index register, so a
    # narrower cell drags its neighbour in and yields a wild pointer (fj-lessons: an n-nibble
    # op reads n nibbles of its SOURCE).
    # ⚠ ptp/ptq/bhv/btv/bdv are `sim.bind_one`'s scratch and are SHARED on purpose: that macro is
    # instantiated once per thing (251 on E1M1), so an @-local data cell would be 251 cells and 251
    # declaration lines in the emitted text. It keeps nothing across the call.
    return ["ptx: hex.vec 10", "pty: hex.vec 10", "ptss: hex.vec w/4",
            f"{label}_ret: hex.vec w/4", f"{label}k: hex.vec 10",
            f"{label}dx: hex.vec 10", f"{label}dy: hex.vec 10",
            f"{label}p: hex.vec 10", f"{label}q: hex.vec 10",
            "ptp: hex.vec w/4", "ptq: hex.vec w/4",
            "bhv: hex.vec 2", "btv: hex.vec 2", "bdv: hex.vec 4"]
