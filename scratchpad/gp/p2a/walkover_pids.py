"""P2a: what the two walk-over doors (sectors 77, 145; W1 special 2, stored shut) cost in plane ids,
next to P2b's lifts -- the pid byte holds 255. Uses lift_budget's own registry (the emitter's rules).

    PYTHONPATH=src python scratchpad/gp/p2a/walkover_pids.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lift"))
import lift_budget as LB  # noqa: E402
from doomfj.doors import OPEN_GAP, stops  # noqa: E402

WALKOVER = (77, 145)


def door_mover(si, quant):
    """a stored-shut door sector as a mover table row: [(floor, ceil) per state], state 0 = shut"""
    fl = LB.secs[si].floor_h
    open_h = min(LB.secs[n].ceil_h for n in LB.nb[si]) - OPEN_GAP
    cs = [fl, open_h] if quant == "instant" else stops(fl, open_h, quant)
    return [(fl, c) for c in cs]


def pids(movers):
    return len(LB.registry(movers)[0])


base = pids({})
lifts = LB.mover_table(16, "instant")
print("today (the 13 doors):                  %d pids" % base)
print("+ P2b lifts q16, switch instant:       %d pids" % pids(lifts))
for q in (16, 24, 32, "instant"):
    wo = {si: door_mover(si, q) for si in WALKOVER}
    print("walk-over doors %-8s states %s:  alone %d, with P2b's lifts %d pids (cap %d)"
          % (q, [len(v) for v in wo.values()], pids(wo), pids({**lifts, **wo}), LB.PID_CAP))
