"""M14-d — the fj half of line collision: DOOM's PIT_CheckLine, BAKED AS CODE.

Why baked and not table-driven. `ReferenceModel.check_position` tests every linedef; that is fine
in Python and about **7M fj ops per tic** if the emitted program read the same rows through
`hex.read_table_packed`. The blockmap (`mapcompiler.build_blockmap`) cuts the candidate set to the
~0-8 lines whose block the player's box touches, and baking each of those lines AS CODE removes the
rest of the cost: a linedef's geometry is compile-time, so most of PIT_CheckLine's branching
collapses before the program ever runs.

WHAT COLLAPSES AT COMPILE TIME, which is the whole reason this is affordable:

* `P_PointOnLineSide`'s three cases are chosen by the line's slope, and the slope is baked -- a
  vertical line emits one compare, not a cross product;
* so is `P_BoxOnLineSide`'s slopetype switch, and the `dx < 0` / `dy < 0` parity flips inside it;
* `line->dy >> FRACBITS` is a constant, so the two FixedMuls take a baked multiplier;
* one-sided-ness, ML_BLOCKING and the two sector openings are constants, so a blocking line emits
  a jump and nothing else.

Most of E1M1's linedefs are axis-aligned, and those reduce to two compares.

⚠ The emitted code must produce the ORACLE's answer, bit for bit -- `tests/fj/test_collision_fj.py`
drives this against `check_position` directly. The rules are mirrored from `reference_model`'s
`point_on_line_side` / `box_on_line_side` / `line_opening`, including DOOM's `<=` boundary
conventions, which are not the same as the cross product's.
"""
from __future__ import annotations

M32 = 0xFFFFFFFF
BOXTOP, BOXBOTTOM, BOXLEFT, BOXRIGHT = 0, 1, 2, 3


def _set(reg: str, value: int, nib: int = 8) -> str:
    return f"    hex.set {nib}, {reg}, {value & M32}"


class LineBake:
    """One linedef's compile-time facts, in the form the emitted test needs."""

    def __init__(self, ld, verts, secs, sds, ml_blocking: int):
        self.v1x, self.v1y = (c << 16 for c in verts[ld.v1])
        self.v2x, self.v2y = (c << 16 for c in verts[ld.v2])
        self.dx, self.dy = self.v2x - self.v1x, self.v2y - self.v1y
        self.minx, self.maxx = min(self.v1x, self.v2x), max(self.v1x, self.v2x)
        self.miny, self.maxy = min(self.v1y, self.v2y), max(self.v1y, self.v2y)
        self.one_sided = ld.back == -1
        self.blocking = bool(ld.flags & ml_blocking)
        if self.one_sided:
            self.opentop = self.openbottom = 0
        else:
            fs, bs = secs[sds[ld.front].sector], secs[sds[ld.back].sector]
            self.opentop = min(fs.ceil_h, bs.ceil_h)
            self.openbottom = max(fs.floor_h, bs.floor_h)

    # ── P_PointOnLineSide, with the case already chosen ──────────────────────────────────────
    def point_side_ops(self, xreg: str, yreg: str, tag: str, side0: str, side1: str) -> list:
        """Jump to `side0` (front) or `side1` (back) for the point in (xreg, yreg)."""
        if self.dx == 0:                                  # vertical: x <= v1x ? (dy>0) : (dy<0)
            lo, hi = (side1, side0) if self.dy > 0 else (side0, side1)
            return [_set(f"{tag}c", self.v1x),
                    f"    hex.scmp 8, {xreg}, {tag}c, {lo}, {lo}, {hi}"]
        if self.dy == 0:                                  # horizontal: y <= v1y ? (dx<0) : (dx>0)
            lo, hi = (side1, side0) if self.dx < 0 else (side0, side1)
            return [_set(f"{tag}c", self.v1y),
                    f"    hex.scmp 8, {yreg}, {tag}c, {lo}, {lo}, {hi}"]
        # left = FixedMul(dy >> 16, x - v1x); right = FixedMul(y - v1y, dx >> 16)
        # right < left -> front (0), else back (1). Both multipliers are baked.
        return [_set(f"{tag}a", self.v1x), _set(f"{tag}b", self.v1y),
                f"    hex.mov 8, {tag}dx, {xreg}", f"    hex.sub 8, {tag}dx, {tag}a",
                f"    hex.mov 8, {tag}dy, {yreg}", f"    hex.sub 8, {tag}dy, {tag}b",
                _set(f"{tag}k", self.dy >> 16),
                f"    hex.fixed_mul_lo 8, 4, {tag}l, {tag}k, {tag}dx",
                _set(f"{tag}k", self.dx >> 16),
                f"    hex.fixed_mul_lo 8, 4, {tag}r, {tag}dy, {tag}k",
                f"    hex.scmp 8, {tag}r, {tag}l, {side0}, {side1}, {side1}"]

    # ── P_BoxOnLineSide: skip unless the box STRADDLES the line ──────────────────────────────
    def box_straddles_ops(self, tag: str, skip: str, hit: str) -> list:
        """`skip` when the box is wholly on one side (DOOM's `p1 == p2`); `hit` when it straddles.

        The parity flips DOOM applies for `dx < 0` / `dy < 0` hit BOTH p1 and p2, so they cannot
        change whether the two agree — the axis cases reduce to a band test and the flips drop out.
        The `<=` boundaries do NOT drop out and are the whole reason this is written by hand rather
        than as "is the line inside the box"."""
        if self.dy == 0:                                  # ST_HORIZONTAL
            # p1 = top > v1y, p2 = bottom > v1y  ->  differ iff  bottom <= v1y < top
            return [_set(f"{tag}c", self.v1y),
                    f"    hex.scmp 8, cby_hi, {tag}c, {skip}, {skip}, {tag}_h1",   # need top > v1y
                    f"  {tag}_h1:",
                    f"    hex.scmp 8, cby_lo, {tag}c, {hit}, {hit}, {skip}"]       # need bottom <= v1y
        if self.dx == 0:                                  # ST_VERTICAL
            # p1 = right < v1x, p2 = left < v1x  ->  differ iff  left < v1x <= right
            return [_set(f"{tag}c", self.v1x),
                    f"    hex.scmp 8, cbx_hi, {tag}c, {skip}, {tag}_v1, {tag}_v1",  # need right >= v1x
                    f"  {tag}_v1:",
                    f"    hex.scmp 8, cbx_lo, {tag}c, {hit}, {skip}, {skip}"]       # need left < v1x
        # the two diagonal cases test opposite corner pairs, and straddling is p1 != p2
        if (self.dy > 0) == (self.dx > 0):                # ST_POSITIVE: (left, top) vs (right, bottom)
            first, second = ("cbx_lo", "cby_hi"), ("cbx_hi", "cby_lo")
        else:                                            # ST_NEGATIVE: (right, top) vs (left, bottom)
            first, second = ("cbx_hi", "cby_hi"), ("cbx_lo", "cby_lo")
        return (self.point_side_ops(first[0], first[1], f"{tag}p", f"{tag}_p0", f"{tag}_p1")
                + [f"  {tag}_p0:"]                        # p1 = 0 -> straddle iff p2 = 1
                + self.point_side_ops(second[0], second[1], f"{tag}q", skip, hit)
                + [f"  {tag}_p1:"]                        # p1 = 1 -> straddle iff p2 = 0
                + self.point_side_ops(second[0], second[1], f"{tag}s", hit, skip))


def line_test_ops(bake: "LineBake", tag: str, nxt: str) -> list:
    """One linedef's full PIT_CheckLine, as straight-line fj. Falls through to `nxt` in every
    outcome except a blocking hit, which jumps to `cp_blocked`.

    Order is DOOM's and it matters for cost, not just correctness: the bbox reject first (four
    compares, and it rejects nearly everything), then the straddle test, and only then the
    blocking rules and the opening."""
    out = [f"  {tag}:"]
    # bbox reject -- box.right <= line.minx, box.left >= line.maxx, and the same in y
    for reg, const, cmp_lo, name in (("cbx_hi", bake.minx, True, "a"),
                                     ("cbx_lo", bake.maxx, False, "b"),
                                     ("cby_hi", bake.miny, True, "c"),
                                     ("cby_lo", bake.maxy, False, "d")):
        out.append(_set(f"{tag}{name}", const))
        if cmp_lo:      # reject when reg <= const
            out.append(f"    hex.scmp 8, {reg}, {tag}{name}, {nxt}, {nxt}, {tag}_k{name}")
        else:           # reject when reg >= const
            out.append(f"    hex.scmp 8, {reg}, {tag}{name}, {tag}_k{name}, {nxt}, {nxt}")
        out.append(f"  {tag}_k{name}:")
    out += bake.box_straddles_ops(tag, nxt, f"{tag}_hit")
    out.append(f"  {tag}_hit:")
    if bake.one_sided or bake.blocking:
        out.append("    ;cp_blocked")          # a wall: the position is refused outright
        return out
    # two-sided and passable: narrow the opening. floorz = max(floorz, openbottom),
    # ceilingz = min(ceilingz, opentop) -- heights are map units, 8-nibble signed.
    out += [_set(f"{tag}o", bake.openbottom),
            f"    hex.scmp 8, {tag}o, cp_floor, {tag}_f, {tag}_f, {tag}_setf",
            f"  {tag}_setf:", f"    hex.mov 8, cp_floor, {tag}o",
            f"  {tag}_f:",
            _set(f"{tag}t", bake.opentop),
            f"    hex.scmp 8, {tag}t, cp_ceil, {tag}_setc, {tag}_c, {tag}_c",
            f"  {tag}_setc:", f"    hex.mov 8, cp_ceil, {tag}t",
            f"  {tag}_c:", f"    ;{nxt}"]
    return out


def check_position_ops(bakes, *, radius: int, seed_floor: int, seed_ceil: int) -> list:
    """The whole of `check_position` for one candidate position in `cpx`/`cpy` (16.16).

    Writes `cp_ok` (1 = the position is legal), `cp_floor` / `cp_ceil` (map units). The subsector
    SEED comes from the caller -- P_CheckPosition seeds the opening from the sector the position
    lands in, and without it a position with no line near it reads as open space (which is how the
    oracle's first draft teleported the player to (30000, 30000))."""
    out = ["    hex.set 1, cp_ok, 1",
           _set("cp_floor", seed_floor), _set("cp_ceil", seed_ceil),
           _set("cprad", radius),
           "    hex.mov 8, cbx_lo, cpx", "    hex.sub 8, cbx_lo, cprad",
           "    hex.mov 8, cbx_hi, cpx", "    hex.add 8, cbx_hi, cprad",
           "    hex.mov 8, cby_lo, cpy", "    hex.sub 8, cby_lo, cprad",
           "    hex.mov 8, cby_hi, cpy", "    hex.add 8, cby_hi, cprad"]
    for i, bake in enumerate(bakes):
        out += line_test_ops(bake, f"cl{i}", f"cl{i + 1}")
    out += [f"  cl{len(bakes)}:", "    ;cp_done",
            "  cp_blocked:", "    hex.set 1, cp_ok, 0",
            "  cp_done:"]
    return out


COLLISION_DECLS = [
    "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
    "cbx_lo: hex.vec 8", "cbx_hi: hex.vec 8", "cby_lo: hex.vec 8", "cby_hi: hex.vec 8",
    "cp_ok: hex.vec 1", "cp_floor: hex.vec 8", "cp_ceil: hex.vec 8",
]


def line_scratch_decls(n: int) -> list:
    """Per-line scratch. Each baked line owns its own cells rather than sharing one set, because a
    shared cell would have to be cleared on every early-out path and a missed clear is silent."""
    out = []
    for i in range(n):
        t = f"cl{i}"
        out += [f"{t}a: hex.vec 8", f"{t}b: hex.vec 8", f"{t}c: hex.vec 8", f"{t}d: hex.vec 8",
                f"{t}o: hex.vec 8", f"{t}t: hex.vec 8"]
        for sub in ("p", "q", "s"):
            out += [f"{t}{sub}a: hex.vec 8", f"{t}{sub}b: hex.vec 8", f"{t}{sub}c: hex.vec 8",
                    f"{t}{sub}k: hex.vec 8", f"{t}{sub}l: hex.vec 8", f"{t}{sub}r: hex.vec 8",
                    f"{t}{sub}dx: hex.vec 8", f"{t}{sub}dy: hex.vec 8"]
    return out
