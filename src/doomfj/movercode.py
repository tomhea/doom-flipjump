"""M7 P2b -- the MOVERS in fj (the doors' doorcode twin; the rules are doomfj.movers).

A lift is the door machine on the floor, so its frame is `doorcode.machine_lines` -- the very lines
every door runs -- on its own cells (`lstate`/`ldir`/`lsub`/`lwait`), with the lift's bottom wait and
a trigger that takes `lreq` only AT REST at the top (`movers.lift_tic`). The request is set by a WR
crossing after an accepted move and by an SR press; the floor switch's `fswitch` by its S1 press.

M8 F1.3: a blazing lift is the same machine at stride 2; a WR line whose tag starts two lifts sets both requests
(one crossing test a segment). The ONE-SHOT FLOOR groups (`movers.floor_groups`) live in the `fswitch` vector --
E1M1's one instant group keeps `fswitch: hex.vec 1` and its exact text; the WIDE layout holds each group's state
(`movers.switch_cell(g)`) then each group's step timer (`movers.floor_sub_cell`). `floor_tic_lines` steps the moving
groups (`movers.floor_tic`), `floor_walk_lines` fires the W1 lines after an accepted move (a slanted one by
`movers.crossed_shape`'s exact cross product), `use_line_lines` the S1 ones on a press (`movers.floor_trigger`).
"""
from __future__ import annotations

from doomfj.doorcode import WAIT_NIBBLES, _box_test, _crossed_lines, _scmp_const, machine_lines
from doomfj.movers import LIFT_WAIT, PERP_SUB, floor_sub_cell, switch_cell

M40 = (1 << 40) - 1


def mover_decls(nlift: int, nfs: int = 1) -> list:
    """The movers' persisted cells (build.MOVER_PERSIST), baked to the level start: every lift at
    its stored top floor, idle, no request; the switch not fired. M8 F1.3: `nfs` the fswitch vector's nibbles
    (`movers.fswitch_nibbles`: 1 on E1M1, 2 per floor group in the wide layout)."""
    n = max(nlift, 1)
    return [
        f"lstate: hex.vec {n}, 0",                        # stop index, 0 the top floor (movers.lift_states)
        f"ldir: hex.vec {n}, 0",                          # 0 idle / 1 down / 2 up
        f"lsub: hex.vec {n}, 0",                          # frames until the next stop
        f"lwait: hex.vec {WAIT_NIBBLES * n}, 0",          # frames left at the bottom
        f"lreq: hex.vec {n}, 0",                          # a trigger for the next mover tic
        f"fswitch: hex.vec {nfs}, 0",                     # the floor switch fired (S1); M8: every floor group
    ]


def perpetual_lines(p: str, st: str, dr: str, sub: str, wt: str, rq: str, last: int) -> list:
    """M8 C4: one frame of a PERPETUAL lift (53) -- `movers.perpetual_tic` on the lift's cells, its request `rq`
    cleared: a request starts it only while it was never started (idle, no wait); moving, a stop every PERP_SUB frames,
    DOWN (OPENING: state + 1) or UP (CLOSING: state - 1); at either end idle with LIFT_WAIT; the wait run out, on again
    (up from the bottom, down from the top). An idle-and-never-started lift costs two nibble tests."""
    from doomfj.doors import CLOSING, OPENING
    return [
        f"    hex.if0 1, {rq}, {p}_nr",
        f"    hex.zero 1, {rq}",
        f"    hex.if0 1, {dr}, {p}_iw",
        f"    ;{p}_nr",
        f"  {p}_iw:",
        f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_start",        # never started: the request starts it
        f"    ;{p}_nr",
        f"  {p}_start:",
        f"    hex.set 1, {dr}, {OPENING}",
        f"    hex.set 1, {sub}, {PERP_SUB}",
        f"  {p}_nr:",
        f"    hex.if0 1, {dr}, {p}_idle",
        f"    hex.dec 1, {sub}",
        f"    hex.if0 1, {sub}, {p}_step",
        f"    ;{p}_done",
        f"  {p}_step:",
        f"    hex.set 1, {sub}, {PERP_SUB}",
        f"    hex.xor_by 1, {dr}, {OPENING}",
        f"    hex.if0 1, {dr}, {p}_down",
        f"    hex.xor_by 1, {dr}, {OPENING}",
        f"    hex.dec 1, {st}",                                # up: state - 1, at 0 the top
        f"    hex.if0 1, {st}, {p}_end",
        f"    ;{p}_done",
        f"  {p}_down:",
        f"    hex.xor_by 1, {dr}, {OPENING}",
        f"    hex.inc 1, {st}",                                # down: state + 1, at `last` the bottom
        f"    hex.xor_by 1, {st}, {last}",
        f"    hex.if0 1, {st}, {p}_endb",
        f"    hex.xor_by 1, {st}, {last}",
        f"    ;{p}_done",
        f"  {p}_endb:",
        f"    hex.xor_by 1, {st}, {last}",
        f"  {p}_end:",
        f"    hex.zero 1, {dr}",
        f"    hex.zero 1, {sub}",
        f"    hex.set {WAIT_NIBBLES}, {wt}, {LIFT_WAIT}",
        f"    ;{p}_done",
        f"  {p}_idle:",
        f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_done",
        f"    hex.dec {WAIT_NIBBLES}, {wt}",
        f"    hex.if0 {WAIT_NIBBLES}, {wt}, {p}_go",
        f"    ;{p}_done",
        f"  {p}_go:",
        f"    hex.set 1, {sub}, {PERP_SUB}",
        f"    hex.set 1, {dr}, {OPENING}",                     # from the top: down
        f"    hex.if0 1, {st}, {p}_done",
        f"    hex.set 1, {dr}, {CLOSING}",                     # from the bottom: up
        f"  {p}_done:"]


def lift_tic_lines(slots, nstates, strides=None, perpetual=None) -> list:
    """One frame of every lift -- `movers.lift_tic`: a request (`lreq`, cleared) presses only a lift
    at rest at the top (state 0, idle, no wait); the motion is the doors'. `slots` = sorted lift
    sectors, `nstates[si]` its stops, M8 F1.3 `strides[si]` its stops a frame (`movers.lift_stride`; 1 when
    None). M8 C4: `perpetual[si]` true -- a perpetual lift's machine (`perpetual_lines`). Labels `lf{k}_`."""
    out = ["// == M7 P2b: the lifts, one tic each (doomfj.movers.lift_tic) =========="]
    for k, si in enumerate(slots):
        p = f"lf{k}"
        st, dr, sub = f"lstate + {k}*dw", f"ldir + {k}*dw", f"lsub + {k}*dw"
        wt, rq = f"lwait + {WAIT_NIBBLES * k}*dw", f"lreq + {k}*dw"
        if perpetual and perpetual.get(si):
            out += [f"  // ---- lift {k} (sector {si}): perpetual, {nstates[si]} states ----",
                    *perpetual_lines(p, st, dr, sub, wt, rq, nstates[si] - 1)]
            continue
        trigger = [f"    hex.if0 1, {rq}, {p}_moved",
                   f"    hex.zero 1, {rq}",
                   f"    hex.if0 1, {st}, {p}_press",          # at rest is state 0 (lift_tic)
                   f"    ;{p}_moved"]
        out += [f"  // ---- lift {k} (sector {si}): {nstates[si]} states ----",
                *machine_lines(p, st, dr, sub, wt, nstates[si] - 1, trigger, top_wait=LIFT_WAIT,
                               stride=1 if strides is None else strides[si])]
    return out


def floor_tic_lines(groups) -> list:
    """M8 F1.3: one frame of every MOVING floor group (`movers.floor_tic`), after the lifts: a running timer counts
    down; at 0 the state steps, and the timer is set again unless the step reached the last state. A still group
    costs one nibble test. Labels `fg{g}_`."""
    ng = len(groups)
    if not any(grp.sub for grp in groups):
        return []                                      # E1M1: its one switch is instant -- no text
    out = ["// == M8 F1.3: the moving floor groups, one tic each (doomfj.movers.floor_tic) =="]
    for g, grp in enumerate(groups):
        if not grp.sub:
            continue
        p, st, u, last = f"fg{g}", switch_cell(g), floor_sub_cell(g, ng), grp.n - 1
        out += [f"  // ---- floor group {g} (tag {grp.tag}, special {grp.special}): {grp.n} states ----",
                f"    hex.if0 1, {u}, {p}_done",
                f"    hex.dec 1, {u}",
                f"    hex.if0 1, {u}, {p}_step",
                f"    ;{p}_done",
                f"  {p}_step:",
                f"    hex.inc 1, {st}",
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.if0 1, {st}, {p}_end",
                f"    hex.xor_by 1, {st}, {last}",
                f"    hex.set 1, {u}, {grp.sub}",
                f"    ;{p}_done",
                f"  {p}_end:",
                f"    hex.xor_by 1, {st}, {last}",
                f"  {p}_done:"]
    return out


def _fire_lines(p: str, g: int, groups) -> list:
    """group g's line fired (`movers.floor_trigger`): an instant group's state to 1 (again: no change); a moving
    one's timer set only while it is untouched (state 0, timer 0) -> on to `<p>_fired`"""
    grp, st = groups[g], switch_cell(g)
    if not grp.sub:
        return [f"    hex.set 1, {st}, 1", f"    ;{p}_fired"]
    u = floor_sub_cell(g, len(groups))
    return [f"    hex.if0 1, {st}, {p}_f1", f"    ;{p}_fired", f"  {p}_f1:",
            f"    hex.if0 1, {u}, {p}_f2", f"    ;{p}_fired", f"  {p}_f2:",
            f"    hex.set 1, {u}, {grp.sub}", f"    ;{p}_fired"]


def lift_walk_lines(triggers, slots, radius: int, prefix: str = "lw") -> list:
    """After an ACCEPTED move from (`cm_ox`, `cm_oy`) to (`viewx`, `viewy`): each WR line the move
    crossed asks for its lift (`lreq`) -- `doors.crossed`, the walk-over doors' test
    (`doorcode.walkover_lines`), without the W1 latch. `triggers` = `movers.lift_walk_triggers`.
    `prefix` (M7 P8a): the labels' (a second copy -- the knock move's -- takes its own). M8 F1.3: entries with one
    segment (a line whose tag starts two lifts) share ONE test that requests every lift."""
    out = ["// == M7 P2b: the WR lift lines (doors.crossed, every crossing) ======"]
    segs: dict = {}
    for (si, axis, coord, lo, hi) in triggers:
        segs.setdefault((axis, coord, lo, hi), []).append(si)
    for k, ((axis, coord, lo, hi), sis) in enumerate(segs.items()):
        out += _crossed_lines(f"{prefix}{k}", axis, coord, lo, hi, radius,
                              [f"    hex.set 1, lreq + {slots.index(si)}*dw, 1" for si in sis])
    return out


def slanted_side_lines(p: str, shape, xr: str, yr: str, side1: str, side0: str) -> list:
    """`movers.line_side` in fj for the 16.16 point (`xr`, `yr`) and the slanted line `shape` = ("d", x1, y1, x2,
    y2): A = x - x1, B = y - y1 (sign-extended to 10 nibbles), s = B*dx - A*dy by two `hex.mul_lo` against the
    |deltas| (the constant second: a row per nibble), the signs folded into an add or a subtract -> `side1` when
    s >= 0, else `side0`. The point-location scratch (ptlocdx/dy/k/p/q: written before read, kept by nobody across
    an accepted move). The caller bounds |A|, |B| (`floor_walk_lines`: the new centre in the line's box)."""
    _d, x1, y1, x2, y2 = shape
    dx, dy = x2 - x1, y2 - y1
    assert dx and dy, shape
    out = ["    hex.zero 10, ptlocdx", f"    hex.mov 8, ptlocdx, {xr}", "    hex.sign_extend 10, 8, ptlocdx",
           f"    hex.set 10, ptlock, {(x1 << 16) & M40:#x}", "    hex.sub 10, ptlocdx, ptlock",
           "    hex.zero 10, ptlocdy", f"    hex.mov 8, ptlocdy, {yr}", "    hex.sign_extend 10, 8, ptlocdy",
           f"    hex.set 10, ptlock, {(y1 << 16) & M40:#x}", "    hex.sub 10, ptlocdy, ptlock",
           f"    hex.set 10, ptlock, {abs(dx)}", "    hex.mul_lo 10, ptlocp, ptlocdy, ptlock",    # P = B*|dx|
           f"    hex.set 10, ptlock, {abs(dy)}", "    hex.mul_lo 10, ptlocq, ptlocdx, ptlock"]    # Q = A*|dy|
    # s = sgn(dx) P - sgn(dy) Q
    if dx > 0 and dy > 0:
        out += ["    hex.sub 10, ptlocp, ptlocq"]                 # s = P - Q
        neg = False
    elif dx > 0:
        out += ["    hex.add 10, ptlocp, ptlocq"]                 # s = P + Q
        neg = False
    elif dy > 0:
        out += ["    hex.add 10, ptlocp, ptlocq"]                 # s = -(P + Q)
        neg = True
    else:
        out += ["    hex.sub 10, ptlocq, ptlocp", "    hex.mov 10, ptlocp, ptlocq"]   # s = Q - P
        neg = False
    if not neg:                                                   # s >= 0 -> side 1
        return out + [f"    hex.sign 10, ptlocp, {side0}, {side1}"]
    # s = -t: s >= 0 <=> t <= 0
    return out + [f"    hex.sign 10, ptlocp, {side1}, {p}_tz", f"  {p}_tz:",
                  f"    hex.if0 10, ptlocp, {side1}", f"    ;{side0}"]


def _slanted_crossed_lines(p: str, shape, radius: int, fire, regs=("cm_ox", "cm_oy", "viewx", "viewy")) -> list:
    """`movers.crossed_shape` for a slanted line: the new centre strictly inside the line's box grown by `radius`
    (four compares), then the old and new centres' sides (`slanted_side_lines`) differ -> the `fire` lines; either
    way on to `<p>_no`"""
    _d, x1, y1, x2, y2 = shape
    ox, oy, nx, ny = regs
    # |A|, |B| <= the box + radius + one move (< 2^9 units here): |s| < 2^(9+16) * 2 * max|d| fits 40 bits signed
    ext = max(abs(x2 - x1), abs(y2 - y1)) + radius + 256
    assert 2 * (ext << 16) * max(abs(x2 - x1), abs(y2 - y1)) < 1 << 39, shape
    out = []
    for j, (reg, lo, hi) in enumerate(((nx, min(x1, x2), max(x1, x2)), (ny, min(y1, y2), max(y1, y2)))):
        out += _scmp_const(reg, (lo - radius) << 16, f"{p}_no", f"{p}_no", f"{p}_b{j}a") + [f"  {p}_b{j}a:"]
        out += _scmp_const(reg, (hi + radius) << 16, f"{p}_b{j}b", f"{p}_no", f"{p}_no") + [f"  {p}_b{j}b:"]
    out += slanted_side_lines(f"{p}o", shape, ox, oy, f"{p}_o1", f"{p}_o0")
    out += [f"  {p}_o1:"] + slanted_side_lines(f"{p}n1", shape, nx, ny, f"{p}_no", f"{p}_fire")
    out += [f"  {p}_o0:"] + slanted_side_lines(f"{p}n0", shape, nx, ny, f"{p}_fire", f"{p}_no")
    return out + [f"  {p}_fire:", *fire, f"  {p}_no:"]


def floor_walk_lines(groups, triggers, radius: int, prefix: str = "fw",
                     regs=("cm_ox", "cm_oy", "viewx", "viewy")) -> list:
    """M8 F1.3: after an ACCEPTED player move, each W1 floor line (`movers.floor_walk_triggers`: (group, shape)) of a
    group not yet fired that the move crossed (`movers.crossed_shape`) fires its group (`_fire_lines`). The untouched
    test comes first, so a fired group's lines cost one nibble test. `prefix`: the labels' (the knock move's copy
    takes its own). E1M1 has none: no text."""
    if not triggers:
        return []
    ng = len(groups)
    out = ["// == M8 F1.3: the W1 floor lines (movers.crossed_shape; each group fires once) =="]
    for k, (g, shape) in enumerate(triggers):
        p = f"{prefix}{k}"
        grp = groups[g]
        out += [f"    hex.if0 1, {switch_cell(g)}, {p}_u", f"    ;{p}_no", f"  {p}_u:"]
        if grp.sub:
            out += [f"    hex.if0 1, {floor_sub_cell(g, ng)}, {p}_try", f"    ;{p}_no", f"  {p}_try:"]
        fire = [ln.replace(f";{p}_fired", f";{p}_no") for ln in _fire_lines(p, g, groups)]
        if shape[0] == "d":
            out += _slanted_crossed_lines(p, shape, radius, fire, regs)
        else:
            axis, coord, lo, hi = shape
            out += _crossed_lines(p, axis, coord, lo, hi, radius, fire, regs)
    return out


def use_line_lines(sr_boxes, switch_boxes, of_tag, groups=None, floor_use=None) -> list:
    """On a use PRESS (the exit's edge, inside `exit_lines`' `ex_press`): each SR lift box holding
    the player asks for its lift; the S1 switch box fires `fswitch` (once: setting it again
    changes nothing, so no guard). `of_tag` = tag -> the lift's slot (M8 F1.3: or a tuple of slots, every lift
    of the tag). M8 F1.3: with `groups` / `floor_use` (`movers.floor_use_boxes`), every S1 floor group's boxes fire
    it (`_fire_lines`); group 0's labels are E1M1's (`fs_hit`, `fs_miss<k>`, `fs_done`), so its text is unchanged."""
    out = ["// == M7 P2b: the SR lift lines and the S1 floor switch, on a use press =="]
    for k, (tag, box) in enumerate(sr_boxes):
        slots = of_tag[tag] if isinstance(of_tag[tag], tuple) else (of_tag[tag],)
        out += _box_test(f"s{k}", box, f"us{k}_hit", f"us{k}_miss")
        out += [f"  us{k}_hit:", *[f"    hex.set 1, lreq + {s}*dw, 1" for s in slots], f"  us{k}_miss:"]
    if floor_use is None:
        per = [(0, list(switch_boxes))] if switch_boxes else []
        groups = None
    else:
        per = []
        for g in range(len(groups)):
            bx = [b for gg, b in floor_use if gg == g]
            if bx:
                per.append((g, bx))
    for g, boxes in per:
        nm = (lambda s: f"fs_{s}") if g == 0 else (lambda s, g=g: f"fs{g}_{s}")
        d = (lambda k: f"w{k}") if g == 0 else (lambda k, g=g: f"f{g}w{k}")
        for k, box in enumerate(boxes):
            out += _box_test(d(k), box, nm("hit"), nm(f"miss{k}")) + [f"  {nm(f'miss{k}')}:"]
        if groups is None or not groups[g].sub:
            out += [f";{nm('done')}", f"{nm('hit')}:", f"    hex.set 1, {switch_cell(g)}, 1", f"{nm('done')}:"]
        else:
            out += [f";{nm('done')}", f"{nm('hit')}:",
                    *[ln.replace(f";fu{g}_fired", f";{nm('done')}") for ln in _fire_lines(f"fu{g}", g, groups)],
                    f"{nm('done')}:"]
    return out
