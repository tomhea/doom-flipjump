"""M7 P3.2c "decide" (docs/gp-monsters.md 8.5): the attack sight's NEAR line of sight in fj -- `World.los_points`
from a monster (an integer position) to the player (16.16), exactly, for a monster within NEAR of the player that
the last picture did not show.

  * THE CANDIDATES: the map is cut into 256-unit cells on the monster's integer position (`SIGHT_CELL_SHIFT`); a cell
    lists every sight segment (the model's `_sight_walls`, then its `_sight_doors`) whose bounding box reaches the
    cell grown by `NEAR_MARGIN`. A trace from a monster in the cell to a player within NEAR stays inside that grown
    cell, so the list holds every segment whose box the trace's box can meet (`test_monster_sight`).
  * ONE BLOCK PER SEGMENT: a dynamic segment (a door's, a lift's or the floor switch's sector on one side) first
    reads that sector's state cell and goes on only at a state whose opening is shut (<= 0; `closed_states`, the
    model's height rules); then its constants are XORed into zeroed registers (one op a nibble: the first version
    computed with them in place, ~9k ops a block, 5.4M for E1M1's 593) and the shared test `sl_seg` runs the
    model's bounding-box reject in 16.16, the rest, and zeroes them again.
  * `sl_seg`: `world.segments_touch` on the signs of four orientations, each an exact 48-bit product difference
    (`hex.mul_lo 12`, one shared leaf). With P the monster, Q the player, A, B the segment's ends, u = Q - P (16.16)
    and a = A - P, b = B - P, d = B - A (integers):
        o1 = u x a,   o2 = u x b,   o3 = d x (-a) = dy*ax - dx*ay,   o4 = d x u + (o3 << 16)
    -- the model's orientations over a positive 2^16 or 2^32, so the same signs. A touch: o1, o2 straddle (they
    differ and are not both nonzero of one sign) and so do o3, o4; or all four are 0 -- collinear, where the model's
    projection overlap always holds here because the box reject just passed on the same boxes.
The first touching segment ends the walk with `sl_hit` = 1 -- after it RETURNS: `stl.fcall` xors the return
address into its register and only the return xors it back, so a callee that jumps away leaves it armed and the
next call lands nowhere (the first harness run died so, at its fourth record). Every operand is bounded at emit time (`_bounds`).

M7 P6 (docs/gp-p67-interface.md 4.3): A BARREL'S BLAST enters the same machinery at `bl_los` (`blast_los_lines`) -- a NEW
entry, `sl_los` is unchanged. P is the barrel (an integer spot: it goes into mm_x / mm_y, which sl_seg reads), Q the
target in 16.16 (`bl_qx` / `bl_qy`: the player's viewx / viewy, or a monster's whole-unit position). Instead of the
cell tree it jumps (on `bl_b`) to the barrel's STATIC list: every sight segment whose box meets the barrel's spot grown
by `blast_margin`, the farthest a blast's target can stand (Chebyshev < 128 + the largest radius). The model calls
`los_points(target, spot)` -- `segments_touch` is symmetric in its first two points (o1, o2 change sign together, o3
and o4 swap), and the box reject takes min / max, so P and Q may trade places (tests/host/test_barrelcode.py holds
it). `_bounds` is re-proven at that margin.
"""
from typing import Dict, List, Tuple

from doomfj.sight import NEAR

SIGHT_CELL_SHIFT = 8                 # a sight cell: 256 map units of the integer position (nibbles 3 and 2)
NEAR_UNITS = NEAR                    # doomfj.sight.NEAR (R6: one source)
NEAR_MARGIN = NEAR_UNITS + 1         # the trace reaches NEAR whole units plus the player's fraction
M32, M48 = (1 << 32) - 1, (1 << 48) - 1
STRADDLE = (1, 2, 4, 6, 8, 9)        # sign codes c1*4 + c2 (zero 0, positive 1, negative 2) that straddle


def _int(v16: int) -> int:
    assert v16 & 0xFFFF == 0, "a segment end off the integer grid"
    return v16 >> 16


def closed_states(w, s: int) -> Tuple[str, int, frozenset]:
    """a DYNAMIC sector `s`: (its state cell, its number of states, the states at which a line between `s` and a
    static sector is shut for sight) -- `World._door_phase_scene`'s heights for that state alone"""
    from doomfj.doors import door_states, heights_for_states
    from doomfj.movers import mover_heights
    if s in w.door_order:
        d = w.door_order.index(s)
        n = len(door_states(w.secs, w.lds, w.sds)[s])
        hts = [heights_for_states(w.secs, w.lds, w.sds, {s: k}) for k in range(n)]
        return "dstate + %d*dw" % d, n, hts
    if s in w.lift_order:
        assert s not in w.switch, "a lift the floor switch also lowers"
        k_ = list(w.lift_order).index(s)
        n = len(w.lift_stops[s])
        hts = [mover_heights(w.secs, w.lift_stops, {s: k}, w.switch, False) for k in range(n)]
        return "lstate + %d*dw" % k_, n, hts
    assert s in w.switch, s
    return "fswitch", 2, [mover_heights(w.secs, w.lift_stops, {}, w.switch, bool(k)) for k in range(2)]


def sight_segments(w) -> List[dict]:
    """the model's sight segments in its order: `a`, `b` (integer ends), `box` (minx, maxx, miny, maxy), and for a
    dynamic one `dyn` = (state cell, states, the shut states)"""
    out = []
    for (a, b, box) in w._sight_walls:
        out.append(dict(a=(_int(a[0]), _int(a[1])), b=(_int(b[0]), _int(b[1])), box=tuple(_int(v) for v in box),
                        dyn=None))
    dyn = set(w.door_order) | set(w.mover_order)
    for (a, b, box), fs, bs in w._sight_doors:
        sides = [s for s in (fs, bs) if s in dyn]
        assert len(sides) == 1, "a line between two dynamic sectors (%d, %d)" % (fs, bs)
        s = sides[0]
        other = bs if s == fs else fs
        cell, n, hts = closed_states(w, s)
        shut = set()
        for k in range(n):
            (f1, c1) = hts[k].get(s, (w.secs[s].floor_h, w.secs[s].ceil_h))
            (f2, c2) = hts[k].get(other, (w.secs[other].floor_h, w.secs[other].ceil_h))
            if min(c1, c2) - max(f1, f2) <= 0:
                shut.add(k)
        out.append(dict(a=(_int(a[0]), _int(a[1])), b=(_int(b[0]), _int(b[1])), box=tuple(_int(v) for v in box),
                        dyn=(cell, n, frozenset(shut))))
    return out


def _bounds(segs, margin: int = None) -> None:
    """every operand of `sl_seg` fits: ends within 2^13 of each other (so a, b, d fit 16-bit cells and every
    product and o4 stays below 2^47 in the 48-bit registers). `margin` (M7 P6: a blast's `blast_margin`): the
    farthest |Q - P| per axis, in whole units -- NEAR_MARGIN by default"""
    xs = [v for s in segs for v in (s["a"][0], s["b"][0])]
    ys = [v for s in segs for v in (s["a"][1], s["b"][1])]
    assert max(xs) - min(xs) < 1 << 13 and max(ys) - min(ys) < 1 << 13, "the map is too wide for sl_seg's widths"
    u = ((NEAR_MARGIN if margin is None else margin) << 16)  # |Q - P| per axis
    e = 1 << 13
    assert 2 * u * e < 1 << 47 and 2 * e * e * (1 << 16) + 2 * e * u < 1 << 47


def cell_of(v: int) -> int:
    return (v >> SIGHT_CELL_SHIFT) & 0xFF


def cell_lists(segs, cells) -> Dict[Tuple[int, int], Tuple[int, ...]]:
    """{(cx, cy): segment indices} for every cell in `cells` (each the integer cell of a position, two's complement
    bytes): a segment is listed when its box meets the cell grown by NEAR_MARGIN"""
    S = 1 << SIGHT_CELL_SHIFT
    out = {}
    for cx, cy in cells:
        x0 = (cx - 256 if cx >= 128 else cx) * S - NEAR_MARGIN
        y0 = (cy - 256 if cy >= 128 else cy) * S - NEAR_MARGIN
        x1, y1 = x0 + S - 1 + 2 * NEAR_MARGIN, y0 + S - 1 + 2 * NEAR_MARGIN
        out[(cx, cy)] = tuple(k for k, s in enumerate(segs)
                              if not (s["box"][1] < x0 or s["box"][0] > x1 or s["box"][3] < y0 or s["box"][2] > y1))
    return out


def map_cells(w) -> List[Tuple[int, int]]:
    """every sight cell a monster can stand in: those the map's vertex box covers"""
    vs = w.cmap.vertexes
    xs, ys = [v[0] for v in vs], [v[1] for v in vs]
    return [(cx & 0xFF, cy & 0xFF) for cx in range(min(xs) >> SIGHT_CELL_SHIFT, (max(xs) >> SIGHT_CELL_SHIFT) + 1)
            for cy in range(min(ys) >> SIGHT_CELL_SHIFT, (max(ys) >> SIGHT_CELL_SHIFT) + 1)]


SIGN32 = 0x80000000                 # M7 P8a I: the bias that makes an unsigned compare a signed one (fight's sl_seg)


def _seg_block(k: int, s: dict, fight: bool = False) -> List[str]:
    """segment k: (a dynamic one: its sector shut, else return) its constants XORed into the zeroed registers --
    `hex.xor_by` costs one op a nibble, where a `hex.set 8` is 256 and a `hex.sub_constant 8` 755 -- then the shared
    test, which zeroes them again on every exit.

    `fight` (M7 P8a I; MEASURED: a rejected segment cost ~5K ops, 4 x (mov 8 + sub 8 + sign 8) and the clears): the
    box constants are BIASED (xor 0x80000000, so `hex.cmp 8` -- unsigned, ~50 ops -- orders them as signed numbers,
    against the prologue's biased box), `sl_seg` is CALLED (stl.fcall sl_seg, sl_tret), and the same xors undo the
    constants after it -- ~1.6 ops a nibble instead of the clears"""
    if fight:
        return _seg_block_fight(k, s)
    L = "sg%d_" % k
    (ax, ay), (bx, by) = s["a"], s["b"]
    minx, maxx, miny, maxy = s["box"]
    out = ["sg%d:" % k]
    if s["dyn"]:
        cell, n, shut = s["dyn"]
        if not shut:
            return out + ["    stl.fret sl_sret"]           # never shut: it never blocks
        mask = sum(1 << st for st in shut)
        out += ["    hex.if_flags %s, %d, %sout, %sgo" % (cell, mask, L, L), "  %sgo:" % L]
    for reg, n, v in (("sl_cx1", 8, (maxx << 16) + 1), ("sl_cx0", 8, minx << 16),
                      ("sl_cy1", 8, (maxy << 16) + 1), ("sl_cy0", 8, miny << 16),
                      ("sl_ax", 4, ax), ("sl_ay", 4, ay), ("sl_bx", 4, bx), ("sl_by", 4, by)):
        v &= 16 ** n - 1
        if v:
            out.append("    hex.xor_by %d, %s, %d" % (n, reg, v))
    out += ["    ;sl_seg"]
    if s["dyn"]:
        out += ["  %sout:" % L, "    stl.fret sl_sret"]
    return out


def _seg_block_fight(k: int, s: dict) -> List[str]:
    L = "sg%d_" % k
    (ax, ay), (bx, by) = s["a"], s["b"]
    minx, maxx, miny, maxy = s["box"]
    out = ["sg%d:" % k]
    if s["dyn"]:
        cell, n, shut = s["dyn"]
        if not shut:
            return out + ["    stl.fret sl_sret"]           # never shut: it never blocks
        mask = sum(1 << st for st in shut)
        out += ["    hex.if_flags %s, %d, %sout, %sgo" % (cell, mask, L, L), "  %sgo:" % L]
    xors = []
    for reg, n, v in (("sl_cx1", 8, ((maxx << 16) + 1) ^ SIGN32), ("sl_cx0", 8, (minx << 16) ^ SIGN32),
                      ("sl_cy1", 8, ((maxy << 16) + 1) ^ SIGN32), ("sl_cy0", 8, (miny << 16) ^ SIGN32),
                      ("sl_ax", 4, ax), ("sl_ay", 4, ay), ("sl_bx", 4, bx), ("sl_by", 4, by)):
        v &= 16 ** n - 1
        if v:
            xors.append("    hex.xor_by %d, %s, %d" % (n, reg, v))
    out += xors + ["    stl.fcall sl_seg, sl_tret"] + xors
    if s["dyn"]:
        out += ["  %sout:" % L]
    return out + ["    stl.fret sl_sret"]


def _cross(dst: str, x1: str, y1: str, x2: str, y2: str) -> List[str]:
    """dst = x1*y2 - y1*x2 (12-hex signed), through the shared product leaf"""
    return ["    hex.mov 12, sl_m1, %s" % x1, "    hex.mov 12, sl_m2, %s" % y2, "    stl.fcall sl_mul, sl_mret",
            "    hex.mov 12, %s, sl_r" % dst,
            "    hex.mov 12, sl_m1, %s" % y1, "    hex.mov 12, sl_m2, %s" % x2, "    stl.fcall sl_mul, sl_mret",
            "    hex.sub 12, %s, sl_r" % dst]


def _code(o: str, k: str, weight: int, tag: str) -> List[str]:
    """k += weight * (0 zero, 1 positive, 2 negative) of the 12-hex signed `o`"""
    return ["    hex.sign 12, %s, %sn, %szp" % (o, tag, tag),
            "  %sn:" % tag, "    hex.add_constant 1, %s, %d" % (k, 2 * weight), "    ;%sz" % tag,
            "  %szp:" % tag, "    hex.if0 12, %s, %sz" % (o, tag),
            "    hex.add_constant 1, %s, %d" % (k, weight),
            "  %sz:" % tag]


def seg_test_lines(fight: bool = False) -> List[str]:
    """`sl_seg` (entered by a segment block's tail jump; returns through sl_sret, or ends the walk on a touch) and
    the product leaf. `fight` (M7 P8a I, `_seg_block`'s): CALLED (sl_tret); the box reject is four unsigned compares
    on the biased box (the prologues bias sl_x0 .. sl_y1); the ends are copied into working registers (sl_wax ..:
    the block's xors undo the constants), and nothing is cleared"""
    if fight:
        return _seg_test_fight()
    out = ["sl_seg:"]
    # the model's box reject, in 16.16 (the constants: maxx + 1, minx, maxy + 1, miny, all << 16)
    for t, reg, c, keep_neg in (("a", "sl_x0", "sl_cx1", True), ("b", "sl_x1", "sl_cx0", False),
                                ("c", "sl_y0", "sl_cy1", True), ("d", "sl_y1", "sl_cy0", False)):
        nxt = "sl_b" + t
        out += ["    hex.mov 8, sl_t, %s" % reg, "    hex.sub 8, sl_t, %s" % c,
                "    hex.sign 8, sl_t, %s" % ((nxt + ", sl_clr") if keep_neg else ("sl_clr, " + nxt)),
                "  %s:" % nxt]
    # the ends relative to the monster (16-bit integers, sign-extended), and d = b - a
    for reg, pos in (("sl_ax", "mm_x"), ("sl_ay", "mm_y"), ("sl_bx", "mm_x"), ("sl_by", "mm_y")):
        out += ["    hex.sub 4, %s, %s" % (reg, pos), "    hex.sign_extend 12, 4, %s" % reg]
    out += ["    hex.mov 12, sl_dx, sl_bx", "    hex.sub 12, sl_dx, sl_ax",
            "    hex.mov 12, sl_dy, sl_by", "    hex.sub 12, sl_dy, sl_ay",
            "    hex.zero 1, sl_k12", "    hex.zero 1, sl_k34"]
    out += _cross("sl_o", "sl_ux", "sl_uy", "sl_ax", "sl_ay") + _code("sl_o", "sl_k12", 4, "sl_c1")
    out += _cross("sl_o", "sl_ux", "sl_uy", "sl_bx", "sl_by") + _code("sl_o", "sl_k12", 1, "sl_c2")
    out.append("    sim.jump16 sl_k12, " + ", ".join(
        "sl_q34" if c in STRADDLE or c == 0 else "sl_miss" for c in range(16)))
    out += ["  sl_q34:"]
    out += _cross("sl_o3", "sl_dy", "sl_dx", "sl_ay", "sl_ax")        # dy*ax - dx*ay
    out += _code("sl_o3", "sl_k34", 4, "sl_c3")
    out += _cross("sl_o", "sl_dx", "sl_dy", "sl_ux", "sl_uy")         # dx*uy - dy*ux
    out += ["    hex.mov 12, sl_t12, sl_o3", "    hex.shl_hex 12, 4, sl_t12", "    hex.add 12, sl_o, sl_t12"]
    out += _code("sl_o", "sl_k34", 1, "sl_c4")
    out += ["    hex.if0 1, sl_k12, sl_zz",
            "    sim.jump16 sl_k34, " + ", ".join("sl_touch" if c in STRADDLE else "sl_miss" for c in range(16)),
            "  sl_zz:",
            "    hex.if0 1, sl_k34, sl_touch",
            "    ;sl_miss",
            "  sl_touch:", "    hex.set 1, sl_hit, 1",
            "  sl_miss:",
            "  sl_clr:",                                   # every exit: the constant registers back to zero
            "    hex.zero 8, sl_cx1", "    hex.zero 8, sl_cx0", "    hex.zero 8, sl_cy1", "    hex.zero 8, sl_cy0",
            "    hex.zero 12, sl_ax", "    hex.zero 12, sl_ay", "    hex.zero 12, sl_bx", "    hex.zero 12, sl_by",
            "    stl.fret sl_sret",
            "sl_mul:", "    hex.mul_lo 12, sl_r, sl_m1, sl_m2", "    stl.fret sl_mret"]
    return out


def near_los_lines(w, fight: bool = False, lists=None) -> List[str]:
    """the whole near LOS: `sl_los` (stl.fcall sl_los, sl_ret) -- mm_x, mm_y the monster's integer position,
    viewx, viewy the player's -- leaves sl_hit = 1 when a segment blocks the trace; the cell tree, the segment
    blocks, the test.

    `fight` (M7 P8a I, world.infighting_on; off: the text is P6's to the byte): the cell tree becomes a subroutine the
    FAR LOS walks too (`far_los_lines`) -- it jumps on the cell registers `sl_jx` / `sl_jy` (nibbles 2-3: the cell
    byte), which sl_los fills from mm_x / mm_y, and it is entered at `sl_tree` (stl.fcall sl_tree, sl_ret: every list
    ends at sl_done, `stl.fret sl_ret`). `lists` overrides the cell lists (the harnesses' controls)."""
    segs = sight_segments(w)
    _bounds(segs)
    cells = map_cells(w)
    lists = cell_lists(segs, cells) if lists is None else lists
    jx, jy = ("sl_jx", "sl_jy") if fight else ("mm_x", "mm_y")
    out = ["sl_los:", "    hex.zero 1, sl_hit"]
    for c, v in (("x", "viewx"), ("y", "viewy")):
        p = "sl_p" + c
        out += ["    hex.zero 4, %s" % p, "    hex.mov 4, %s + 4*dw, mm_%s" % (p, c),
                "    hex.mov 8, sl_u%s, %s" % (c, v), "    hex.sub 8, sl_u%s, %s" % (c, p),
                "    hex.sign 8, sl_u%s, sl_%sneg, sl_%spos" % (c, c, c),
                "  sl_%sneg:" % c, "    hex.mov 8, sl_%s0, %s" % (c, v), "    hex.mov 8, sl_%s1, %s" % (c, p),
                "    ;sl_%sbox" % c,
                "  sl_%spos:" % c, "    hex.mov 8, sl_%s0, %s" % (c, p), "    hex.mov 8, sl_%s1, %s" % (c, v),
                "  sl_%sbox:" % c, "    hex.sign_extend 12, 8, sl_u%s" % c]
    if fight:                                   # M7 P8a I: the biased box; the tree's cell registers; sl_far's entry
        out += _bias_box() + ["    hex.mov 2, sl_jx + 2*dw, mm_x + 2*dw", "    hex.mov 2, sl_jy + 2*dw, mm_y + 2*dw",
                              "sl_tree:"]
    # the cell tree: x nibble 3, x nibble 2, y nibble 3, y nibble 2 -- hash-consed
    nodes: Dict[tuple, str] = {}
    body: List[str] = []
    lid: Dict[tuple, str] = {}

    def list_label(idx: tuple) -> str:
        if not idx:
            return "sl_done"
        if idx not in lid:
            lab = "sl_l%d" % len(lid)
            lid[idx] = lab
            # each segment RETURNS (an fcall's register is armed until its return un-flips it), then a touch
            # ends the walk
            body.extend(["  %s:" % lab] + [ln for k in idx for ln in ("    stl.fcall sg%d, sl_sret" % k,
                                                                      "    hex.if1 1, sl_hit, sl_done")]
                        + ["    ;sl_done"])
        return lid[idx]

    def node(reg: str, targets: List[str]) -> str:
        key = (reg, tuple(targets))
        if all(t == "sl_done" for t in targets):
            return "sl_done"
        if key not in nodes:
            lab = "sl_n%d" % len(nodes)
            nodes[key] = lab
            body.extend(["  %s:" % lab, "    sim.jump16 %s, %s" % (reg, ", ".join(targets))])
        return nodes[key]

    have = set(cells)

    def y_lo(cx, yh):
        return node(jy + " + 2*dw", [list_label(lists[(cx, yh * 16 + yl)]) if (cx, yh * 16 + yl) in have
                                     else "sl_done" for yl in range(16)])

    def y_hi(cx):
        return node(jy + " + 3*dw", [y_lo(cx, yh) for yh in range(16)])

    def x_lo(xh):
        return node(jx + " + 2*dw", [y_hi(xh * 16 + xl) for xl in range(16)])

    root = node(jx + " + 3*dw", [x_lo(xh) for xh in range(16)])
    out += ["    ;%s" % root] + body + ["sl_done:", "    stl.fret sl_ret"]
    for k, s in enumerate(segs):
        out += _seg_block(k, s, fight)
    return out + seg_test_lines(fight)


def _seg_test_fight() -> List[str]:
    out = ["sl_seg:",
           # the model's box reject (keep iff x0 <= maxx << 16 and x1 >= minx << 16, and in y): biased, unsigned
           "    hex.cmp 8, sl_x0, sl_cx1, sl_ba, sl_q, sl_q",
           "  sl_ba:",
           "    hex.cmp 8, sl_x1, sl_cx0, sl_q, sl_bb, sl_bb",
           "  sl_bb:",
           "    hex.cmp 8, sl_y0, sl_cy1, sl_bc, sl_q, sl_q",
           "  sl_bc:",
           "    hex.cmp 8, sl_y1, sl_cy0, sl_q, sl_bd, sl_bd",
           "  sl_bd:"]
    for reg, pos in (("ax", "mm_x"), ("ay", "mm_y"), ("bx", "mm_x"), ("by", "mm_y")):
        out += ["    hex.mov 4, sl_w%s, sl_%s" % (reg, reg), "    hex.sub 4, sl_w%s, %s" % (reg, pos),
                "    hex.sign_extend 12, 4, sl_w%s" % reg]
    out += ["    hex.mov 12, sl_dx, sl_wbx", "    hex.sub 12, sl_dx, sl_wax",
            "    hex.mov 12, sl_dy, sl_wby", "    hex.sub 12, sl_dy, sl_way",
            "    hex.zero 1, sl_k12", "    hex.zero 1, sl_k34"]
    out += _cross("sl_o", "sl_ux", "sl_uy", "sl_wax", "sl_way") + _code("sl_o", "sl_k12", 4, "sl_c1")
    out += _cross("sl_o", "sl_ux", "sl_uy", "sl_wbx", "sl_wby") + _code("sl_o", "sl_k12", 1, "sl_c2")
    out.append("    sim.jump16 sl_k12, " + ", ".join(
        "sl_q34" if c in STRADDLE or c == 0 else "sl_q" for c in range(16)))
    out += ["  sl_q34:"]
    out += _cross("sl_o3", "sl_dy", "sl_dx", "sl_way", "sl_wax")      # dy*ax - dx*ay
    out += _code("sl_o3", "sl_k34", 4, "sl_c3")
    out += _cross("sl_o", "sl_dx", "sl_dy", "sl_ux", "sl_uy")         # dx*uy - dy*ux
    out += ["    hex.mov 12, sl_t12, sl_o3", "    hex.shl_hex 12, 4, sl_t12", "    hex.add 12, sl_o, sl_t12"]
    out += _code("sl_o", "sl_k34", 1, "sl_c4")
    out += ["    hex.if0 1, sl_k12, sl_zz",
            "    sim.jump16 sl_k34, " + ", ".join("sl_touch" if c in STRADDLE else "sl_q" for c in range(16)),
            "  sl_zz:",
            "    hex.if0 1, sl_k34, sl_touch",
            "    ;sl_q",
            "  sl_touch:", "    hex.set 1, sl_hit, 1",
            "  sl_q:",
            "    stl.fret sl_tret",
            "sl_mul:", "    hex.mul_lo 12, sl_r, sl_m1, sl_m2", "    stl.fret sl_mret"]
    return out


def _bias_box() -> List[str]:
    """M7 P8a I: the trace's box biased for fight's sl_seg (xor the sign bit: signed order as unsigned order)"""
    return ["    hex.xor_by %s + 7*dw, 8" % r for r in ("sl_x0", "sl_x1", "sl_y0", "sl_y1")]


SL_DECLS = (["sl_hit: hex.vec 1", "sl_k12: hex.vec 1", "sl_k34: hex.vec 1",
             "sl_px: hex.vec 8", "sl_py: hex.vec 8", "sl_x0: hex.vec 8", "sl_x1: hex.vec 8", "sl_y0: hex.vec 8",
             "sl_y1: hex.vec 8", "sl_t: hex.vec 8",
             "sl_cx1: hex.vec 8", "sl_cx0: hex.vec 8", "sl_cy1: hex.vec 8", "sl_cy0: hex.vec 8"]
            + ["%s: hex.vec 12" % r for r in ("sl_ux", "sl_uy", "sl_ax", "sl_ay", "sl_bx", "sl_by", "sl_dx", "sl_dy",
                                               "sl_m1", "sl_m2", "sl_r", "sl_o", "sl_o3", "sl_t12")]
            + ["sl_ret: hex.vec w/4", "sl_sret: hex.vec w/4", "sl_mret: hex.vec w/4"])


# ---- M7 P8a I: the FAR LOS (docs/gp-final-plan.md 1.2.3, O-B2 TAKEN: the exact 2D LOS at any range) --------------
FAR_PIECES = 32                      # at most this many pieces: the map must be under FAR_PIECES * PIECE units wide
PIECE = NEAR_UNITS - 1               # 127: a piece's Chebyshev length -- its points stay within 128 of its start
SF_DECLS = ["sl_jx: hex.vec 4", "sl_jy: hex.vec 4",
            "sf_ax: hex.vec 10", "sf_ay: hex.vec 10", "sf_sx: hex.vec 10", "sf_sy: hex.vec 10", "sf_t: hex.vec 10",
            "sf_c: hex.vec 10, %d" % (PIECE << 24), "sf_n: hex.vec 2", "sf_pcx: hex.vec 2", "sf_pcy: hex.vec 2",
            "sf_bx: hex.vec 4", "sf_by: hex.vec 4", "sf_xn: hex.vec 1", "sf_yn: hex.vec 1",
            "sf_tx0: hex.vec 8", "sf_tx1: hex.vec 8", "sf_ty0: hex.vec 8", "sf_ty1: hex.vec 8",
            "sf_ret: hex.vec w/4", "sf_wret: hex.vec w/4",
            # the fight's sl_seg (`_seg_test_fight`): the ends' working registers, its return
            "sl_wax: hex.vec 12", "sl_way: hex.vec 12", "sl_wbx: hex.vec 12", "sl_wby: hex.vec 12",
            "sl_tret: hex.vec w/4"]


def far_margin(w) -> int:
    """the farthest |Q - P| per axis of two points in the map (whole units, + 1 for a 16.16 fraction): the map's
    vertex box -- asserted under FAR_PIECES pieces of PIECE units"""
    vs = w.cmap.vertexes
    ext = max(max(v[0] for v in vs) - min(v[0] for v in vs), max(v[1] for v in vs) - min(v[1] for v in vs)) + 1
    assert ext <= FAR_PIECES * PIECE, (ext, "the map is too wide for the far LOS's 32 pieces")
    return ext


def _sar10(reg: str, tag: str) -> List[str]:
    """reg[:10] >>= 1, arithmetic (the sign bit kept)"""
    return ["    hex.if_flags %s + 9*dw, 0xFF00, %s_p, %s_n" % (reg, tag, tag),
            "  %s_n:" % tag, "    hex.shr_bit 10, %s" % reg, "    hex.xor_by %s + 9*dw, 8" % reg, "    ;%s_d" % tag,
            "  %s_p:" % tag, "    hex.shr_bit 10, %s" % reg,
            "  %s_d:" % tag]


def far_los_lines(w, qx: str = "mt_tqx", qy: str = "mt_tqy") -> List[str]:
    """`sl_far` (stl.fcall sl_far, sf_ret): sl_hit = 1 when a sight segment blocks the trace from P = (mm_x, mm_y)
    (the monster's whole units) to Q = (qx, qy) -- a MONSTER target's whole units, in 16.16 with a zero fraction
    (monsterdecide's target load) -- `World.los_points` exactly, at ANY range (O-B2). It needs
    `near_los_lines(w, fight=True)`: no new table.

    THE PIECES: the trace is cut into N = 2^h <= FAR_PIECES pieces of at most PIECE (127) units per axis -- N the
    least power of two that does it. Piece k is the trace between parameters k/N and (k+1)/N; it starts at
    S_k = P + k(Q - P)/N, whose FLOOR lies in a 256-unit sight cell. Consecutive pieces whose floors share a cell form
    a RUN (the floors move monotonically along each axis, so a cell left is never re-entered).

    THE COVERING: every point of piece k is within 127 + 1 < NEAR_MARGIN of S_k's floor, so inside its cell grown by
    NEAR_MARGIN -- and the cell's list (`cell_lists`) holds every segment whose box meets that grown cell. A segment
    the trace touches is touched at a point X of some run, and X lies in the segment's box: so it is on that run's
    cell's list, and its box meets the RUN'S BOX -- the box of the run's part of the trace (from the run's first floor
    to the floor of its end point, + 1: S_k and the end are exact in 2^-24 units, so the floors bound every real
    point), clamped to the whole trace's box. Each run's list is walked with sl_seg's box reject on the run's box
    (sl_x0 .. sl_y1), and sl_seg's orientations on the WHOLE trace P -> Q (sl_ux / sl_uy): a reported segment touches
    the trace, and every touching one is reported -- the model's answer. The clamp keeps the run box inside the trace
    box, which sl_seg's collinear rule needs (all four orientations 0 is a touch only when the boxes meet).

    THE ARITHMETIC: positions in 2^-24 units, in 10-nibble registers -- acc_0 = P << 24, the step s = ((Q - P) << 8)
    / N (the 16.16 difference scaled to 2^-24; N | 2^8, so exact), halved from N = 1 while either |s| > 127 << 24;
    Q - P whole, N <= 32: s's low 19 bits are 0, so the walk adds nibbles 4-9 alone (acc_0's low nibbles are 0 too);
    the floor of acc is its nibbles 6-9, its cell byte nibbles 8-9; acc_N = Q << 8 exactly. Along an axis the floors
    move one way -- the sign of Q - P (sf_xn / sf_yn) -- so a run's box is [start floor, end floor + 1] or its
    mirror, in 16.16, BIASED for the fight's sl_seg (as the trace box sf_t*0 / sf_t*1 it is clamped to). `_bounds` is
    re-proven for |Q - P| up to the map's width (`far_margin`)."""
    segs = sight_segments(w)
    _bounds(segs, far_margin(w))
    assert FAR_PIECES <= 1 << 5, "the step's low 19 bits must be 0 for the 6-nibble walk"
    out = ["sl_far:", "    hex.zero 1, sl_hit"]
    for c, q in (("x", qx), ("y", qy)):              # sl_los' prologue, with Q = the target
        p = "sl_p" + c
        out += ["    hex.zero 4, %s" % p, "    hex.mov 4, %s + 4*dw, mm_%s" % (p, c),
                "    hex.mov 8, sl_u%s, %s" % (c, q), "    hex.sub 8, sl_u%s, %s" % (c, p),
                "    hex.zero 1, sf_%sn" % c,
                "    hex.sign 8, sl_u%s, sf_%sneg, sf_%spos" % (c, c, c),
                "  sf_%sneg:" % c, "    hex.set 1, sf_%sn, 1" % c,
                "    hex.mov 8, sf_t%s0, %s" % (c, q), "    hex.mov 8, sf_t%s1, %s" % (c, p),
                "    ;sf_%sbox" % c,
                "  sf_%spos:" % c, "    hex.mov 8, sf_t%s0, %s" % (c, p), "    hex.mov 8, sf_t%s1, %s" % (c, q),
                "  sf_%sbox:" % c, "    hex.sign_extend 12, 8, sl_u%s" % c,
                "    hex.xor_by sf_t%s0 + 7*dw, 8" % c, "    hex.xor_by sf_t%s1 + 7*dw, 8" % c,     # biased
                # the step, N = 1: (Q - P) << 8, i.e. the 16.16 difference in 2^-24 units
                "    hex.mov 10, sf_s%s, sl_u%s" % (c, c), "    hex.shl_hex 10, 2, sf_s%s" % c]
    out += ["    hex.set 2, sf_n, 1",
            "  sf_h:",                                     # a piece wider than PIECE units on an axis: N *= 2
            "    hex.mov 10, sf_t, sf_sx", "    hex.abs 10, sf_t",
            "    hex.cmp 10, sf_t, sf_c, sf_hy, sf_hy, sf_halve",
            "  sf_hy:",
            "    hex.mov 10, sf_t, sf_sy", "    hex.abs 10, sf_t",
            "    hex.cmp 10, sf_t, sf_c, sf_go, sf_go, sf_halve",
            "  sf_halve:"] + _sar10("sf_sx", "sf_hx") + _sar10("sf_sy", "sf_hyy") + [
            "    hex.shl_bit 2, sf_n", "    ;sf_h",
            "  sf_go:",                                    # acc_0 = P << 24; the first run starts at P
            "    hex.zero 6, sf_ax", "    hex.mov 4, sf_ax + 6*dw, mm_x",
            "    hex.zero 6, sf_ay", "    hex.mov 4, sf_ay + 6*dw, mm_y",
            "    hex.mov 2, sf_pcx, mm_x + 2*dw", "    hex.mov 2, sf_pcy, mm_y + 2*dw",
            "    hex.mov 4, sf_bx, mm_x", "    hex.mov 4, sf_by, mm_y",
            "  sf_loop:",                                  # S_k, k = 1 .. N (nibbles 0-3 of s and acc stay 0)
            "    hex.add 6, sf_ax + 4*dw, sf_sx + 4*dw", "    hex.add 6, sf_ay + 4*dw, sf_sy + 4*dw",
            "    hex.dec 2, sf_n",
            "    hex.if0 2, sf_n, sf_run",                     # S_N = Q: the last run ends
            "    hex.cmp 2, sf_ax + 8*dw, sf_pcx, sf_run, sf_cy, sf_run",
            "  sf_cy:",
            "    hex.cmp 2, sf_ay + 8*dw, sf_pcy, sf_run, sf_loop, sf_run",
            "  sf_run:",                                   # the run in cell (pcx, pcy) ends at S_k: walk its list
            "    stl.fcall sf_walk, sf_wret",
            "    hex.if1 1, sl_hit, sf_out",
            "    hex.if0 2, sf_n, sf_out",
            "    hex.mov 2, sf_pcx, sf_ax + 8*dw", "    hex.mov 2, sf_pcy, sf_ay + 8*dw",
            "    hex.mov 4, sf_bx, sf_ax + 6*dw", "    hex.mov 4, sf_by, sf_ay + 6*dw",
            "    ;sf_loop",
            "  sf_out:",
            "    stl.fret sf_ret",
            # the run's box: the floors from its start (sf_bx) to S_k's (acc's nibbles 6-9) in the trace's direction,
            # + 1, in 16.16, biased, inside the trace's biased box
            "sf_walk:"]
    for c in ("x", "y"):
        b, a, lo, hi, t0, t1 = "sf_b" + c, "sf_a%s + 6*dw" % c, "sl_%s0" % c, "sl_%s1" % c, "sf_t%s0" % c, "sf_t%s1" % c
        L = "sfw_" + c
        out += ["    hex.zero 4, %s" % lo, "    hex.zero 4, %s" % hi,
                "    hex.if1 1, sf_%sn, %s_b" % (c, L),
                "    hex.mov 4, %s + 4*dw, %s" % (lo, b), "    hex.mov 4, %s + 4*dw, %s" % (hi, a), "    ;%s_c" % L,
                "  %s_b:" % L,                                                   # moving to -: the end is the low
                "    hex.mov 4, %s + 4*dw, %s" % (lo, a), "    hex.mov 4, %s + 4*dw, %s" % (hi, b),
                "  %s_c:" % L,
                "    hex.inc 4, %s + 4*dw" % hi,
                "    hex.xor_by %s + 7*dw, 8" % lo, "    hex.xor_by %s + 7*dw, 8" % hi,
                "    hex.cmp 8, %s, %s, %s_lo, %s_d, %s_d" % (lo, t0, L, L, L),
                "  %s_lo:" % L, "    hex.mov 8, %s, %s" % (lo, t0),
                "  %s_d:" % L,
                "    hex.cmp 8, %s, %s, %s_e, %s_e, %s_hi" % (hi, t1, L, L, L),
                "  %s_hi:" % L, "    hex.mov 8, %s, %s" % (hi, t1),
                "  %s_e:" % L]
    out += ["    hex.mov 2, sl_jx + 2*dw, sf_pcx", "    hex.mov 2, sl_jy + 2*dw, sf_pcy",
            "    stl.fcall sl_tree, sl_ret",
            "    stl.fret sf_wret"]
    return out


def far_runs(p, q) -> List[Tuple[Tuple[int, int], Tuple[int, int, int, int]]]:
    """the runs `sl_far` walks for P (integers) -> Q (16.16), in order: (cell, its run box (x0, x1, y0, y1) in 16.16)
    -- its arithmetic in Python (the host test proves the covering with it; the fj harness runs the real text)"""
    ux, uy = q[0] - (p[0] << 16), q[1] - (p[1] << 16)
    sx, sy, n = ux << 8, uy << 8, 1
    while max(abs(sx), abs(sy)) > PIECE << 24:
        sx, sy, n = sx >> 1, sy >> 1, n * 2
    assert n <= FAR_PIECES
    tx = sorted((p[0] << 16, q[0]))
    ty = sorted((p[1] << 16, q[1]))
    ax, ay = p[0] << 24, p[1] << 24
    cell, bx, by, out = ((p[0] >> 8) & 0xFF, (p[1] >> 8) & 0xFF), p[0], p[1], []
    for k in range(1, n + 1):
        ax, ay = ax + sx, ay + sy
        c = ((ax >> 32) & 0xFF, (ay >> 32) & 0xFF)
        if k < n and c == cell:
            continue
        fx, fy = ax >> 24, ay >> 24
        x0, x1 = max(min(bx, fx) << 16, tx[0]), min((max(bx, fx) + 1) << 16, tx[1])
        y0, y1 = max(min(by, fy) << 16, ty[0]), min((max(by, fy) + 1) << 16, ty[1])
        out.append((cell, (x0, x1, y0, y1)))
        cell, bx, by = c, fx, fy
    return out


# ---- M7 P6: the BLAST's entry (docs/gp-p67-interface.md 4.3) ---------------------------------------------------
def blast_margin(max_radius: int) -> int:
    """the farthest whole-unit offset (per axis) of a blast's target from the barrel: combat._radius_attack hits when
    max(0, (Chebyshev - r) >> 16) < 128, i.e. Chebyshev < (128 + r) << 16 -- plus one for the box's closed edge"""
    from doomfj.combat import BOMB_DAMAGE
    return BOMB_DAMAGE + max_radius + 1


def spot_lists(segs, spots, margin: int) -> List[Tuple[int, ...]]:
    """per spot (an integer (x, y)): the indices of the segments whose box meets the spot grown by `margin` -- every
    segment a trace from the spot to a point within `margin` can meet (sl_seg's box reject decides the rest)"""
    return [tuple(k for k, s in enumerate(segs)
                  if not (s["box"][1] < x - margin or s["box"][0] > x + margin
                          or s["box"][3] < y - margin or s["box"][2] > y + margin))
            for x, y in spots]


BL_LOS_DECLS = ["bl_b: hex.vec 2", "bl_px: hex.vec 4", "bl_py: hex.vec 4", "bl_qx: hex.vec 8", "bl_qy: hex.vec 8",
                "bl_lret: hex.vec w/4"]


def blast_los_lines(w, spots, max_radius: int, lists=None, fight: bool = False) -> List[str]:
    """`bl_los` (stl.fcall bl_los, bl_lret): sl_hit = 1 when a sight segment blocks the trace from spot `bl_b`
    (bl_px, bl_py: its integer position, the caller's) to (bl_qx, bl_qy) in 16.16. It CALLS the segment blocks
    `sg<k>` and `sl_seg` that `near_los_lines` emits, and writes mm_x / mm_y (the monster tic's scratch: the blast
    runs in the barrel phase, after it). `lists` overrides the per-spot lists (the harness's control). `fight` (M7 P8a
    I): the box biased for the fight's sl_seg (`near_los_lines(fight=True)`)"""
    segs = sight_segments(w)
    margin = blast_margin(max_radius)
    _bounds(segs, margin)
    if lists is None:
        lists = spot_lists(segs, spots, margin)
    n = len(spots)
    assert 0 < n <= 255 and len(lists) == n
    out = ["bl_los:", "    hex.zero 1, sl_hit", "    hex.mov 4, mm_x, bl_px", "    hex.mov 4, mm_y, bl_py"]
    for c in ("x", "y"):                         # sl_los' prologue, with Q = (bl_qx, bl_qy)
        p, q = "sl_p" + c, "bl_q" + c
        out += ["    hex.zero 4, %s" % p, "    hex.mov 4, %s + 4*dw, mm_%s" % (p, c),
                "    hex.mov 8, sl_u%s, %s" % (c, q), "    hex.sub 8, sl_u%s, %s" % (c, p),
                "    hex.sign 8, sl_u%s, bl_%sneg, bl_%spos" % (c, c, c),
                "  bl_%sneg:" % c, "    hex.mov 8, sl_%s0, %s" % (c, q), "    hex.mov 8, sl_%s1, %s" % (c, p),
                "    ;bl_%sbox" % c,
                "  bl_%spos:" % c, "    hex.mov 8, sl_%s0, %s" % (c, p), "    hex.mov 8, sl_%s1, %s" % (c, q),
                "  bl_%sbox:" % c, "    hex.sign_extend 12, 8, sl_u%s" % c]
    if fight:
        out += _bias_box()
    nh = (n - 1) // 16 + 1
    out += ["    sim.jump16 bl_b + 1*dw, " + ", ".join("bl_lh%d" % h if h < nh else "bl_ldone" for h in range(16))]
    for h in range(nh):
        out += ["  bl_lh%d:" % h, "    sim.jump16 bl_b, " + ", ".join(
            "bl_ls%d" % (16 * h + l) if 16 * h + l < n else "bl_ldone" for l in range(16))]
    for b, idx in enumerate(lists):
        out += ["  bl_ls%d:" % b] + [ln for k in idx for ln in ("    stl.fcall sg%d, sl_sret" % k,
                                                                 "    hex.if1 1, sl_hit, bl_ldone")]
        out += ["    ;bl_ldone"]
    return out + ["bl_ldone:", "    stl.fret bl_lret"]
