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
            return [_set("cs_c", self.v1x),
                    f"    hex.scmp 8, {xreg}, cs_c, {lo}, {lo}, {hi}"]
        if self.dy == 0:                                  # horizontal: y <= v1y ? (dx<0) : (dx>0)
            lo, hi = (side1, side0) if self.dx < 0 else (side0, side1)
            return [_set("cs_c", self.v1y),
                    f"    hex.scmp 8, {yreg}, cs_c, {lo}, {lo}, {hi}"]
        # left = FixedMul(dy >> 16, x - v1x); right = FixedMul(y - v1y, dx >> 16)
        # right < left -> front (0), else back (1). Both multipliers are baked.
        return [_set("cs_a", self.v1x), _set("cs_b", self.v1y),
                f"    hex.mov 8, cs_dx, {xreg}", "    hex.sub 8, cs_dx, cs_a",
                f"    hex.mov 8, cs_dy, {yreg}", "    hex.sub 8, cs_dy, cs_b",
                _set("cs_k", self.dy >> 16),
                "    hex.fixed_mul_lo 8, 4, cs_l, cs_k, cs_dx",
                _set("cs_k", self.dx >> 16),
                "    hex.fixed_mul_lo 8, 4, cs_r, cs_dy, cs_k",
                f"    hex.scmp 8, cs_r, cs_l, {side0}, {side1}, {side1}"]

    # ── P_BoxOnLineSide: skip unless the box STRADDLES the line ──────────────────────────────
    def box_straddles_ops(self, tag: str, skip: str, hit: str) -> list:
        """`skip` when the box is wholly on one side (DOOM's `p1 == p2`); `hit` when it straddles.

        The parity flips DOOM applies for `dx < 0` / `dy < 0` hit BOTH p1 and p2, so they cannot
        change whether the two agree — the axis cases reduce to a band test and the flips drop out.
        The `<=` boundaries do NOT drop out and are the whole reason this is written by hand rather
        than as "is the line inside the box"."""
        if self.dy == 0:                                  # ST_HORIZONTAL
            # p1 = top > v1y, p2 = bottom > v1y  ->  differ iff  bottom <= v1y < top
            return [_set("cs_c", self.v1y),
                    f"    hex.scmp 8, cby_hi, cs_c, {skip}, {skip}, {tag}_h1",   # need top > v1y
                    f"  {tag}_h1:",
                    f"    hex.scmp 8, cby_lo, cs_c, {hit}, {hit}, {skip}"]       # need bottom <= v1y
        if self.dx == 0:                                  # ST_VERTICAL
            # p1 = right < v1x, p2 = left < v1x  ->  differ iff  left < v1x <= right
            return [_set("cs_c", self.v1x),
                    f"    hex.scmp 8, cbx_hi, cs_c, {skip}, {tag}_v1, {tag}_v1",  # need right >= v1x
                    f"  {tag}_v1:",
                    f"    hex.scmp 8, cbx_lo, cs_c, {hit}, {skip}, {skip}"]       # need left < v1x
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
        out.append(_set("cs_c", const))
        if cmp_lo:      # reject when reg <= const
            out.append(f"    hex.scmp 8, {reg}, cs_c, {nxt}, {nxt}, {tag}_k{name}")
        else:           # reject when reg >= const
            out.append(f"    hex.scmp 8, {reg}, cs_c, {tag}_k{name}, {nxt}, {nxt}")
        out.append(f"  {tag}_k{name}:")
    out += bake.box_straddles_ops(tag, nxt, f"{tag}_hit")
    out.append(f"  {tag}_hit:")
    if bake.one_sided or bake.blocking:
        out.append("    ;cp_blocked")          # a wall: the position is refused outright
        return out
    # two-sided and passable: narrow the opening. floorz = max(floorz, openbottom),
    # ceilingz = min(ceilingz, opentop) -- heights are map units, 8-nibble signed.
    out += [_set("cs_o", bake.openbottom),
            f"    hex.scmp 8, cs_o, cp_floor, {tag}_f, {tag}_f, {tag}_setf",
            f"  {tag}_setf:", "    hex.mov 8, cp_floor, cs_o",
            f"  {tag}_f:",
            _set("cs_t", bake.opentop),
            f"    hex.scmp 8, cs_t, cp_ceil, {tag}_setc, {tag}_c, {tag}_c",
            f"  {tag}_setc:", "    hex.mov 8, cp_ceil, cs_t",
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


# ── the RUNTIME half: which lines to test is a per-tic question ────────────────────────────────
#
# The kernel above bakes the lines for a position known at compile time. The emitted renderer does
# not know where the player is, so the blockmap has to be walked at RUNTIME: compute the block the
# box corner falls in, jump to that block's handler, run its baked line tests.
#
# The jump is a BINARY SEARCH over the block index rather than a dispatch table, deliberately. The
# repo's dispatch-code idiom (`generate_bands_walk_fj`) forbids `hex.*` macros inside a handler --
# they corrupt the shared `hex.tables.ret` (R42) -- and every line test here is `hex.set` /
# `hex.scmp` / `hex.fixed_mul_lo`. A compare tree needs no shared return register, so the handlers
# stay ordinary code. Depth is ceil(log2 blocks) ~ 10 compares for E1M1.

def blockmap_grid(grid):
    """The blockmap's DENSE bounding grid: `(bx0, by0, nbx, nby)`.

    The handlers are reached by a compare tree over a single integer, so the block index has to be
    arithmetic -- `bmi = (by - by0) * nbx + (bx - bx0)` -- not a lookup in a sparse set. Unoccupied
    cells inside the rectangle simply route to the miss label."""
    bxs = [c[0] for c in grid]
    bys = [c[1] for c in grid]
    bx0, by0 = min(bxs), min(bys)
    return bx0, by0, max(bxs) - bx0 + 1, max(bys) - by0 + 1


def generate_blockmap_code_fj(grid, lds, verts, secs, sds, ml_blocking, *, label="bmk") -> str:
    """The blockmap as code: `{label}_walk` reads `bmi` (the DENSE block index) and runs that
    block's baked line tests, then `stl.fret {label}_ret`. A blocking line jumps straight to
    `cp_blocked` and never returns -- correct, because a refusal is final and the remaining blocks
    cannot un-refuse it."""
    bx0, by0, nbx, nby = blockmap_grid(grid)
    dense = {(by - by0) * nbx + (bx - bx0): lines for (bx, by), lines in grid.items()}
    n = nbx * nby
    out = [f"// M14-d blockmap-as-code: {nbx}x{nby} grid, {len(grid)} occupied, "
           f"{sum(len(v) for v in grid.values())} (block, line) pairs",
           f"{label}_walk:"]

    def tree(lo: int, hi: int) -> list:
        if hi - lo <= 1:
            return [f"    ;{label}_h{lo}" if lo in dense else f"    ;{label}_miss"]
        mid = (lo + hi) // 2
        tg = f"{label}_n{lo}_{hi}"
        return ([f"    hex.set 4, {tg}c, {mid}",
                 f"    hex.cmp 4, bmi, {tg}c, {tg}_lo, {tg}_hi, {tg}_hi",
                 f"  {tg}_lo:"] + tree(lo, mid)
                + [f"  {tg}_hi:"] + tree(mid, hi))

    out += tree(0, n)
    out += [f"  {label}_miss:", f"    stl.fret {label}_ret"]
    for bi, lines in sorted(dense.items()):
        out.append(f"  {label}_h{bi}:      // {len(lines)} lines")
        for k, li in enumerate(lines):
            bake = LineBake(lds[li], verts, secs, sds, ml_blocking)
            out += line_test_ops(bake, f"{label}b{bi}l{k}", f"{label}b{bi}l{k + 1}")
        out.append(f"  {label}b{bi}l{len(lines)}:")
        out.append(f"    stl.fret {label}_ret")
    return "\n".join(out) + "\n"


def blockmap_code_decls(grid, *, label="bmk") -> list:
    """Every scratch cell the generated blockmap code needs."""
    _bx0, _by0, nbx, nby = blockmap_grid(grid)
    n = nbx * nby
    out = ["bmi: hex.vec 4", f"{label}_ret: hex.vec w/4"]

    def tree_decls(lo, hi):
        if hi - lo <= 1:
            return []
        mid = (lo + hi) // 2
        return [f"{label}_n{lo}_{hi}c: hex.vec 4"] + tree_decls(lo, mid) + tree_decls(mid, hi)

    out += tree_decls(0, n)
    return out + list(SHARED_SCRATCH)


SHARED_SCRATCH = [
    "cs_a: hex.vec 8", "cs_b: hex.vec 8", "cs_c: hex.vec 8", "cs_k: hex.vec 8",
    "cs_l: hex.vec 8", "cs_r: hex.vec 8", "cs_dx: hex.vec 8", "cs_dy: hex.vec 8",
    "cs_o: hex.vec 8", "cs_t: hex.vec 8",
]


def line_scratch_decls(n: int = 0) -> list:
    """ONE shared scratch set for every baked line, not one set per line.

    Safe because every write here is `hex.set` (which zeroes the cell first) or a `hex.mov` that
    overwrites it -- there is no xor-involution invariant to preserve, so no early-out path has to
    clear anything. Per-line cells cost 63,837 declarations on E1M1 and bought nothing."""
    return list(SHARED_SCRATCH)


def blockmap_walk_ops(grid, xreg: str, yreg: str, tag: str, *, label="bmk", shift: int = 8) -> list:
    """Compute the block index for the point in (xreg, yreg) — 16.16 — and run that block.

    The index has to be an ARITHMETIC shift of a signed coordinate, and fj's `shr_hex` is logical,
    so the position is BIASED by 2**15 map units first. Map coordinates are int16, so `x + 32768`
    is non-negative for every point on any level, and `(x16 + (32768 << 16)) >> 6 nibbles` is
    `(x_int + 32768) >> 8` exactly — one whole-nibble shift, which is why the blocks are 256 units
    (see `mapcompiler.BLOCK_SHIFT`).

    Out-of-range indices are skipped rather than clamped: a biased index that wrapped would land on
    some other block's handler and test the wrong lines."""
    bx0, by0, nbx, nby = blockmap_grid(grid)
    bias_x, bias_y = bx0 + (1 << (15 - shift)), by0 + (1 << (15 - shift))
    return [
        f"    hex.mov 8, {tag}t, {xreg}", _set(f"{tag}bias", 1 << 31),
        f"    hex.add 8, {tag}t, {tag}bias", f"    hex.shr_hex 8, 6, {tag}t",
        f"    hex.mov 8, {tag}u, {yreg}", f"    hex.add 8, {tag}u, {tag}bias",
        f"    hex.shr_hex 8, 6, {tag}u",
        f"    hex.set 4, {tag}c, {bias_x & 0xFFFF}", f"    hex.sub 4, {tag}t, {tag}c",
        f"    hex.set 4, {tag}c, {bias_y & 0xFFFF}", f"    hex.sub 4, {tag}u, {tag}c",
        # bounds: an index outside the grid must NOT reach a handler
        f"    hex.set 4, {tag}c, {nbx}",
        f"    hex.cmp 4, {tag}t, {tag}c, {tag}_xok, {tag}_out, {tag}_out",
        f"  {tag}_xok:", f"    hex.set 4, {tag}c, {nby}",
        f"    hex.cmp 4, {tag}u, {tag}c, {tag}_yok, {tag}_out, {tag}_out",
        f"  {tag}_yok:",
        f"    hex.mul_const 4, bmi, {tag}u, {nbx}", f"    hex.add 4, bmi, {tag}t",
        f"    stl.fcall {label}_walk, {label}_ret",
        f"  {tag}_out:",
    ]


def blockmap_walk_decls(tag: str) -> list:
    return [f"{tag}t: hex.vec 8", f"{tag}u: hex.vec 8", f"{tag}c: hex.vec 4",
            f"{tag}bias: hex.vec 8"]


def check_position_runtime_ops(grid, *, radius: int, seed_floor: str, seed_ceil: str,
                               label="bmk") -> list:
    """`check_position` with the candidate lines chosen at RUNTIME: the box's four corners give at
    most 2x2 distinct blocks, and each is walked. A line listed in two of them is simply tested
    twice — harmless, because "blocked" is a latch and the opening updates are max/min.

    `seed_floor` / `seed_ceil` are REGISTER names here, not constants: P_CheckPosition seeds the
    opening from the subsector the position lands in, which only the caller knows."""
    out = ["    hex.set 1, cp_ok, 1",
           f"    hex.mov 8, cp_floor, {seed_floor}", f"    hex.mov 8, cp_ceil, {seed_ceil}",
           _set("cprad", radius),
           "    hex.mov 8, cbx_lo, cpx", "    hex.sub 8, cbx_lo, cprad",
           "    hex.mov 8, cbx_hi, cpx", "    hex.add 8, cbx_hi, cprad",
           "    hex.mov 8, cby_lo, cpy", "    hex.sub 8, cby_lo, cprad",
           "    hex.mov 8, cby_hi, cpy", "    hex.add 8, cby_hi, cprad"]
    for i, (xr, yr) in enumerate((("cbx_lo", "cby_lo"), ("cbx_hi", "cby_lo"),
                                  ("cbx_lo", "cby_hi"), ("cbx_hi", "cby_hi"))):
        out += blockmap_walk_ops(grid, xr, yr, f"bw{i}", label=label)
    out += ["    ;cp_done",
            "  cp_blocked:", "    hex.set 1, cp_ok, 0",
            "  cp_done:"]
    return out


def check_position_runtime_decls() -> list:
    out = list(COLLISION_DECLS) + list(SHARED_SCRATCH)
    for i in range(4):
        out += blockmap_walk_decls(f"bw{i}")
    return out
