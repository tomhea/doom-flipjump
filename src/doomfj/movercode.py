"""M7 P2b -- the MOVERS in fj (the doors' doorcode twin; the rules are doomfj.movers).

A lift is the door machine on the floor, so its frame is `doorcode.machine_lines` -- the very lines
every door runs -- on its own cells (`lstate`/`ldir`/`lsub`/`lwait`), with the lift's bottom wait and
a trigger that takes `lreq` only AT REST at the top (`movers.lift_tic`). The request is set by a WR
crossing after an accepted move and by an SR press; the floor switch's `fswitch` by its S1 press.
"""
from __future__ import annotations

from doomfj.doorcode import WAIT_NIBBLES, _box_test, _crossed_lines, machine_lines
from doomfj.movers import LIFT_WAIT


def mover_decls(nlift: int) -> list:
    """The movers' persisted cells (build.MOVER_PERSIST), baked to the level start: every lift at
    its stored top floor, idle, no request; the switch not fired."""
    n = max(nlift, 1)
    return [
        f"lstate: hex.vec {n}, 0",                        # stop index, 0 the top floor (movers.lift_states)
        f"ldir: hex.vec {n}, 0",                          # 0 idle / 1 down / 2 up
        f"lsub: hex.vec {n}, 0",                          # frames until the next stop
        f"lwait: hex.vec {WAIT_NIBBLES * n}, 0",          # frames left at the bottom
        f"lreq: hex.vec {n}, 0",                          # a trigger for the next mover tic
        "fswitch: hex.vec 1, 0",                          # the floor switch fired (S1)
    ]


def lift_tic_lines(slots, nstates) -> list:
    """One frame of every lift -- `movers.lift_tic`: a request (`lreq`, cleared) presses only a lift
    at rest at the top (state 0, idle, no wait); the motion is the doors'. `slots` = sorted lift
    sectors, `nstates[si]` its stops. Labels `lf{k}_`."""
    out = ["// == M7 P2b: the lifts, one tic each (doomfj.movers.lift_tic) =========="]
    for k, si in enumerate(slots):
        p = f"lf{k}"
        st, dr, sub = f"lstate + {k}*dw", f"ldir + {k}*dw", f"lsub + {k}*dw"
        wt, rq = f"lwait + {WAIT_NIBBLES * k}*dw", f"lreq + {k}*dw"
        trigger = [f"    hex.if0 1, {rq}, {p}_moved",
                   f"    hex.zero 1, {rq}",
                   f"    hex.if0 1, {st}, {p}_press",          # at rest is state 0 (lift_tic)
                   f"    ;{p}_moved"]
        out += [f"  // ---- lift {k} (sector {si}): {nstates[si]} states ----",
                *machine_lines(p, st, dr, sub, wt, nstates[si] - 1, trigger, top_wait=LIFT_WAIT)]
    return out


def lift_walk_lines(triggers, slots, radius: int) -> list:
    """After an ACCEPTED move from (`cm_ox`, `cm_oy`) to (`viewx`, `viewy`): each WR line the move
    crossed asks for its lift (`lreq`) -- `doors.crossed`, the walk-over doors' test
    (`doorcode.walkover_lines`), without the W1 latch. `triggers` = `movers.lift_walk_triggers`."""
    out = ["// == M7 P2b: the WR lift lines (doors.crossed, every crossing) ======"]
    for k, (si, axis, coord, lo, hi) in enumerate(triggers):
        out += _crossed_lines(f"lw{k}", axis, coord, lo, hi, radius,
                              [f"    hex.set 1, lreq + {slots.index(si)}*dw, 1"])
    return out


def use_line_lines(sr_boxes, switch_boxes, of_tag) -> list:
    """On a use PRESS (the exit's edge, inside `exit_lines`' `ex_press`): each SR lift box holding
    the player asks for its lift; the S1 switch box fires `fswitch` (once: setting it again
    changes nothing, so no guard). `of_tag` = tag -> the lift's slot."""
    out = ["// == M7 P2b: the SR lift lines and the S1 floor switch, on a use press =="]
    for k, (tag, box) in enumerate(sr_boxes):
        out += _box_test(f"s{k}", box, f"us{k}_hit", f"us{k}_miss")
        out += [f"  us{k}_hit:", f"    hex.set 1, lreq + {of_tag[tag]}*dw, 1", f"  us{k}_miss:"]
    if switch_boxes:
        for k, box in enumerate(switch_boxes):
            out += _box_test(f"w{k}", box, "fs_hit", f"fs_miss{k}") + [f"  fs_miss{k}:"]
        out += [";fs_done", "fs_hit:", "    hex.set 1, fswitch, 1", "fs_done:"]
    return out
