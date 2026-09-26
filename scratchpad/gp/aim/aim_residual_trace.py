"""P0 -- the aim window's residual disagreements, judged against a DOOM-style 2D trace.

    python scratchpad/gp/aim/aim_residual_trace.py

aim_window_census.py leaves 33 column-frames where the design ('box') names a target and the
geometric aim names none, all of one kind: the column was open when the thing arrived, but 2D
sight from the eye to the thing's CENTRE is blocked. DOOM does not test the centre: P_LineAttack
traces a ray and PIT_AddThingIntercepts tests the thing's corner-to-corner diagonal. This replays
the three runs that hold those frames and, for every residual column, casts the ray at EVERY
spread angle that lands in that column (angle = view + (s << 18), s = -255..255, the column from
the renderer's own angle_to_x) and asks: does the ray cross the target's diagonal (DOOM's choice
of diagonal by the sign of dx^dy), and is the 2D segment eye -> crossing point free of blocking
lines (`World.los_points`)? 2D only (no heights), float geometry, nearer things ignored -- a
classification of the residual, not a mirror.
"""
from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aim_window_census as A                                               # noqa: E402

RUNS = {"s4": ["R0-south-hall"], "staged": ["placed_pistol", "shotgun_imps"]}


def trace_hits(w, col, tgt):
    ws = w.ws
    kind, i = tgt
    if kind == "mon":
        x, y, r = ws.mon_x[i], ws.mon_y[i], w.mon_radius[i]
    else:
        t = w.barrel_things[i]
        x, y, r = t.x, t.y, A.C.BARREL_R
    ex, ey = ws.px / 65536.0, ws.py / 65536.0
    n = hit = 0
    for s in range(-255, 256):
        if w.sites.col(s) != col:
            continue
        n += 1
        a = ((ws.pangle + (s << 18)) & 0xFFFFFFFF) * 2 * math.pi / 2 ** 32
        dx, dy = math.cos(a), math.sin(a)
        pos = (dx > 0) == (dy > 0)                 # DOOM: tracepositive = (dx ^ dy) > 0
        p1, p2 = ((x - r, y + r), (x + r, y - r)) if pos else ((x - r, y - r), (x + r, y + r))
        s1 = dx * (p1[1] - ey) - dy * (p1[0] - ex)
        s2 = dx * (p2[1] - ey) - dy * (p2[0] - ex)
        if (s1 > 0) == (s2 > 0):
            continue                                # the ray misses the diagonal
        f = s1 / (s1 - s2)
        ix, iy = p1[0] + f * (p2[0] - p1[0]), p1[1] + f * (p2[1] - p1[1])
        if (ix - ex) * dx + (iy - ey) * dy <= 0:
            continue                                # behind the eye
        if w.los_points((ws.px, ws.py), (int(round(ix * 65536)), int(round(iy * 65536)))):
            hit += 1
    return n, hit


def main():
    snap = str(A.GP / "census_out/s4v1/combat_scenarios_v1.snapshot.json")
    srcs = [A.frames_s4(snap, set(RUNS["s4"]), 3), A.frames_staged(RUNS["staged"], 3)]
    tally, ctl = Counter(), Counter()
    for src in srcs:
        for name, c, keys, _digest in src:
            w = c.world
            for f, key in enumerate(keys):
                w.tic(key)
                th, bk, me, mt = c.game_things()
                _fb, arr = c.render(th, bk, me, mt)
                win, _d = A.windows(c, arr)
                for col in range(A.LO, A.HI + 1):
                    geo, got = w.aim_geometric(w, col), win["box"].get(col)
                    if got == geo:
                        if col == A.CENTRE and got is not None:   # the POSITIVE control
                            n, hit = trace_hits(w, col, got)
                            ctl["agree@80"] += 1
                            ctl["agree@80, DOOM trace hits"] += bool(hit)
                        continue
                    n, hit = trace_hits(w, col, got) if got is not None else (0, 0)
                    verdict = ("DOOM hits at every spread angle of the column" if n and hit == n else
                               "DOOM hits at some spread angles of the column" if hit else
                               "DOOM misses (a wall first, or the ray misses the diagonal)")
                    tally[(geo is None, verdict)] += 1
                    print("%-22s frame %3d col %2d window %-10s geo %-10s rays %2d hit %2d"
                          % (name, f, col, got, geo, n, hit))
    print("control: frames where window and geometric aim agree on a target at col 80: %d; "
          "the trace hits it in %d" % (ctl["agree@80"], ctl["agree@80, DOOM trace hits"]))
    print("residual column-frames by DOOM-style 2D trace:")
    for (geo_none, verdict), v in tally.most_common():
        print("  %3d  %s%s" % (v, "" if geo_none else "[geo names another] ", verdict))


if __name__ == "__main__":
    main()
