"""M7 P3.2c "decide" (docs/gp-monsters.md 8.5): the attack sight's NEAR line of sight in fj -- `World.los_points`
from a monster (an integer position) to the player (16.16), exactly, for a monster within NEAR of the player that
the last picture did not show.

  * THE CANDIDATES: the map is cut into 256-unit cells on the monster's integer position (`SIGHT_CELL_SHIFT`); a cell
    lists every sight segment (the model's `_sight_walls`, then its `_sight_doors`) whose bounding box reaches the
    cell grown by `NEAR_MARGIN`. A trace from a monster in the cell to a player within NEAR stays inside that grown
    cell, so the list holds every segment whose box the trace's box can meet (`test_monster_sight`).
  * ONE BLOCK PER SEGMENT: a dynamic segment (a door's, a lift's or the floor switch's sector on one side) first
    reads that sector's state cell and goes on only at a state whose opening is shut (<= 0; `closed_states`, the
    model's height rules); then the model's bounding-box reject, in 16.16; then its constants into the registers
    and the shared test `sl_seg`.
  * `sl_seg`: `world.segments_touch` on the signs of four orientations, each an exact 48-bit product difference
    (`hex.mul_lo 12`, one shared leaf). With P the monster, Q the player, A, B the segment's ends, u = Q - P (16.16)
    and a = A - P, b = B - P, d = B - A (integers):
        o1 = u x a,   o2 = u x b,   o3 = d x (-a) = dy*ax - dx*ay,   o4 = d x u + (o3 << 16)
    -- the model's orientations over a positive 2^16 or 2^32, so the same signs. A touch: o1, o2 straddle (they
    differ and are not both nonzero of one sign) and so do o3, o4; or all four are 0 -- collinear, where the model's
    projection overlap always holds here because the box reject just passed on the same boxes.
The first touching segment ends the walk with `sl_hit` = 1. Every operand is bounded at emit time (`_bounds`).
"""
from typing import Dict, List, Tuple

SIGHT_CELL_SHIFT = 8                 # a sight cell: 256 map units of the integer position (nibbles 3 and 2)
NEAR_UNITS = 128                     # doomfj.sight.NEAR
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


def _bounds(segs) -> None:
    """every operand of `sl_seg` fits: ends within 2^13 of each other (so a, b, d fit 16-bit cells and every
    product and o4 stays below 2^47 in the 48-bit registers)"""
    xs = [v for s in segs for v in (s["a"][0], s["b"][0])]
    ys = [v for s in segs for v in (s["a"][1], s["b"][1])]
    assert max(xs) - min(xs) < 1 << 13 and max(ys) - min(ys) < 1 << 13, "the map is too wide for sl_seg's widths"
    u = (NEAR_MARGIN << 16)                                   # |Q - P| per axis
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


def _seg_block(k: int, s: dict) -> List[str]:
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
    out += ["    hex.mov 8, sl_t, sl_x0", "    hex.sub_constant 8, sl_t, %d" % (((maxx << 16) + 1) & M32),
            "    hex.sign 8, sl_t, %sa, %sout" % (L, L),          # x0 > maxx: the trace passes beside it
            "  %sa:" % L,
            "    hex.mov 8, sl_t, sl_x1", "    hex.sub_constant 8, sl_t, %d" % ((minx << 16) & M32),
            "    hex.sign 8, sl_t, %sout, %sb" % (L, L),          # x1 < minx
            "  %sb:" % L,
            "    hex.mov 8, sl_t, sl_y0", "    hex.sub_constant 8, sl_t, %d" % (((maxy << 16) + 1) & M32),
            "    hex.sign 8, sl_t, %sc, %sout" % (L, L),
            "  %sc:" % L,
            "    hex.mov 8, sl_t, sl_y1", "    hex.sub_constant 8, sl_t, %d" % ((miny << 16) & M32),
            "    hex.sign 8, sl_t, %sout, %sd" % (L, L),
            "  %sd:" % L,
            "    hex.set 12, sl_dx, %d" % ((bx - ax) & M48), "    hex.set 12, sl_dy, %d" % ((by - ay) & M48)]
    for reg, v, pos in (("sl_ax", ax, "mm_x"), ("sl_ay", ay, "mm_y"), ("sl_bx", bx, "mm_x"), ("sl_by", by, "mm_y")):
        out += ["    hex.set 4, %s, %d" % (reg, v & 0xFFFF), "    hex.sub 4, %s, %s" % (reg, pos),
                "    hex.sign_extend 12, 4, %s" % reg]
    return out + ["    ;sl_seg", "  %sout:" % L, "    stl.fret sl_sret"]


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


def seg_test_lines() -> List[str]:
    """`sl_seg` (entered by a segment block's tail jump; returns through sl_sret, or ends the walk on a touch) and
    the product leaf"""
    out = ["sl_seg:", "    hex.zero 1, sl_k12", "    hex.zero 1, sl_k34"]
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
            "  sl_miss:", "    stl.fret sl_sret",
            "  sl_touch:", "    hex.set 1, sl_hit, 1", "    ;sl_done",
            "sl_mul:", "    hex.mul_lo 12, sl_r, sl_m1, sl_m2", "    stl.fret sl_mret"]
    return out


def near_los_lines(w) -> List[str]:
    """the whole near LOS: `sl_los` (stl.fcall sl_los, sl_ret) -- mm_x, mm_y the monster's integer position,
    viewx, viewy the player's -- leaves sl_hit = 1 when a segment blocks the trace; the cell tree, the segment
    blocks, the test"""
    segs = sight_segments(w)
    _bounds(segs)
    cells = map_cells(w)
    lists = cell_lists(segs, cells)
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
            body.extend(["  %s:" % lab] + ["    stl.fcall sg%d, sl_sret" % k for k in idx] + ["    ;sl_done"])
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
        return node("mm_y + 2*dw", [list_label(lists[(cx, yh * 16 + yl)]) if (cx, yh * 16 + yl) in have
                                    else "sl_done" for yl in range(16)])

    def y_hi(cx):
        return node("mm_y + 3*dw", [y_lo(cx, yh) for yh in range(16)])

    def x_lo(xh):
        return node("mm_x + 2*dw", [y_hi(xh * 16 + xl) for xl in range(16)])

    root = node("mm_x + 3*dw", [x_lo(xh) for xh in range(16)])
    out += ["    ;%s" % root] + body + ["sl_done:", "    stl.fret sl_ret"]
    for k, s in enumerate(segs):
        out += _seg_block(k, s)
    return out + seg_test_lines()


SL_DECLS = (["sl_hit: hex.vec 1", "sl_k12: hex.vec 1", "sl_k34: hex.vec 1",
             "sl_px: hex.vec 8", "sl_py: hex.vec 8", "sl_x0: hex.vec 8", "sl_x1: hex.vec 8", "sl_y0: hex.vec 8",
             "sl_y1: hex.vec 8", "sl_t: hex.vec 8"]
            + ["%s: hex.vec 12" % r for r in ("sl_ux", "sl_uy", "sl_ax", "sl_ay", "sl_bx", "sl_by", "sl_dx", "sl_dy",
                                               "sl_m1", "sl_m2", "sl_r", "sl_o", "sl_o3", "sl_t12")]
            + ["sl_ret: hex.vec w/4", "sl_sret: hex.vec w/4", "sl_mret: hex.vec w/4"])
