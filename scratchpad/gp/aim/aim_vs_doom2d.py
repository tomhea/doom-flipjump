"""P0 -- the aim window against a DOOM-style 2D hitscan.

    python scratchpad/gp/aim/aim_vs_doom2d.py [--staged] [--runs A,B] [--step 8]

The geometric aim and the window share one box (+-r across the view, at the thing's centre depth),
so aim_window_census.py cannot see how far that box is from DOOM. DOOM's P_LineAttack traces a ray
and PIT_AddThingIntercepts crosses each shootable thing's corner-to-corner DIAGONAL (the one chosen
by the sign of dx^dy); the nearest crossing whose path is clear of walls is hit. This replays the
same frames and compares, per ray, DOOM's 2D answer with each window rule's answer in the column
the ray lands in (the renderer's own angle_to_x):
  doom      the 2D trace: nearest diagonal crossing within 2048 units along the ray whose
            eye->crossing segment `World.los_points` clears (no heights, float geometry; walls
            only -- DOOM's blockmap quirk, which can skip a thing whose centre lies in a block the
            ray does not enter, is NOT modelled)
  box       the design's window (aim_window_census.windows, rule 'box')
  box_reff  the same window with each radius r replaced, per frame, by round(r * (|sin v| + |cos v|))
            (v = view angle): the half-width DOOM's diagonal presents across a ray at that angle
  geo       World.aim_geometric (column 80 only)
  ceiling   pellets only: DOOM's own 2D answer at ONE ray per column (the column's median spread) --
            the best any 17-column window can do; its disagreement is the column granularity
  sprite    NEGATIVE CONTROL: the drawn sprite span (the census's picture aim)
  r_minus4  NEGATIVE CONTROL: the box, radius - 4
Two measures: the pistol's accurate first shot (spread 0 = the view angle, column 80), per frame;
and PELLETS: spreads s = -255..255 in steps of --step, weighted by P_SubRandom's triangular
distribution (256 - |s|), each compared in column angle_to_x(s << 18).
"""
from __future__ import annotations

import argparse
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import aim_window_census as A                                               # noqa: E402
from aim_window_census import M32, _signed, fixed_mul, SPRITE_MINZ           # noqa: E402

RANGE = 2048.0
RULES80 = ("box", "box_reff", "geo", "sprite", "r_minus4")
RULESP = ("box", "box_reff", "ceiling", "sprite", "r_minus4")


def near_targets(w):
    ws = w.ws
    ex, ey = ws.px / 65536.0, ws.py / 65536.0
    a = ws.pangle * 2 * math.pi / 2 ** 32
    vx, vy = math.cos(a), math.sin(a)
    out = []
    for kind, i, x, y, r in w.shootable_targets():
        ddx, ddy = x - ex, y - ey
        if ddx * vx + ddy * vy < -2 * r or math.hypot(ddx, ddy) > RANGE + 2 * r:
            continue
        out.append((kind, i, x, y, r))
    return out


def doom2d(w, cands, spread=0):
    """(target, {target: why it is not hit}) of the 2D DOOM trace at view angle + (spread << 18)."""
    ws = w.ws
    ex, ey = ws.px / 65536.0, ws.py / 65536.0
    a = ((ws.pangle + (spread << 18)) & 0xFFFFFFFF) * 2 * math.pi / 2 ** 32
    dx, dy = math.cos(a), math.sin(a)
    pos = (dx > 0) == (dy > 0)                     # DOOM: tracepositive = (dx ^ dy) > 0
    best, info = None, {}
    for kind, i, x, y, r in cands:
        p1, p2 = ((x - r, y + r), (x + r, y - r)) if pos else ((x - r, y - r), (x + r, y + r))
        s1 = dx * (p1[1] - ey) - dy * (p1[0] - ex)
        s2 = dx * (p2[1] - ey) - dy * (p2[0] - ex)
        if (s1 > 0) == (s2 > 0):
            info[(kind, i)] = "ray misses its diagonal"
            continue
        f = s1 / (s1 - s2)
        ix, iy = p1[0] + f * (p2[0] - p1[0]), p1[1] + f * (p2[1] - p1[1])
        dist = (ix - ex) * dx + (iy - ey) * dy
        if dist <= 0:
            info[(kind, i)] = "behind the eye"
            continue
        if dist > RANGE:
            info[(kind, i)] = "beyond 2048 along the ray"
            continue
        if best is not None and dist >= best[0]:
            continue
        if not w.los_points((ws.px, ws.py), (int(round(ix * 65536)), int(round(iy * 65536)))):
            info[(kind, i)] = "a wall before the crossing"
            continue
        best = (dist, (kind, i))
    return (None if best is None else best[1]), info


def reff(w, r):
    a = w.ws.pangle * 2 * math.pi / 2 ** 32
    return int(round(r * (abs(math.sin(a)) + abs(math.cos(a)))))


def window_reff(c, arr):
    """The design's window ('box'), every radius replaced by its per-frame DOOM-diagonal width."""
    w, rm = c.world, c.world.rm
    best = {}
    for order, a in enumerate(arr):
        meta = a["meta"]
        if meta is None or not meta.shoot:
            continue
        tgt, x, y, r = A.target_of(w, meta)
        span = A.box_span(rm, w.ws, x, y, reff(w, r))
        if span is None or span[0] > (A.C.MISSILERANGE_U << 16):
            continue
        tz, _tx, x1, x2 = span
        for col in range(max(x1, A.LO), min(x2, A.HI) + 1):
            if a["drawn"][col]:
                continue
            key = (tz >> 16, order)
            if col not in best or key < best[col][0]:
                best[col] = (key, tgt)
    return {col: v[1] for col, v in best.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--runs", default="")
    ap.add_argument("--step", type=int, default=8)
    ap.add_argument("--out", default=str(HERE / "aim_vs_doom2d.txt"))
    a = ap.parse_args()
    snap = str(A.GP / "census_out/s4v1/combat_scenarios_v1.snapshot.json")
    srcs = [A.frames_s4(snap, set(filter(None, a.runs.split(","))), 3)]
    if a.staged:
        srcs.append(A.frames_staged([n for n in A.SCENARIOS if n != "quiet_walk"] + ["quiet_walk"], 3))
    lines = []

    def say(s):
        print(s, flush=True)
        lines.append(s)
    say("aim vs DOOM 2D trace; pellet spreads every %d, triangular weights" % a.step)
    tot, why, pw, pden = Counter(), Counter(), Counter(), 0
    spreads = [s for s in range(-255, 256) if s % a.step == 0]
    rep = None                                     # column -> its median spread (one ray/column)
    for src in srcs:
        for name, c, keys, _dg in src:
            w = c.world
            run, rpw, rden = Counter(), Counter(), 0
            if rep is None:
                by_col = {}
                for s_ in range(-255, 256):
                    by_col.setdefault(w.sites.col(s_), []).append(s_)
                rep = {col: sorted(v)[len(v) // 2] for col, v in by_col.items()}
            for key in keys:
                w.tic(key)
                th, bk, me, mt = c.game_things()
                _fb, arr = c.render(th, bk, me, mt)
                win, _d = A.windows(c, arr)
                wr = window_reff(c, arr)
                cands = near_targets(w)
                # -- the pistol's accurate shot: spread 0, column 80
                ans = {"box": win["box"].get(A.CENTRE), "box_reff": wr.get(A.CENTRE),
                       "geo": w.aim_geometric(w, A.CENTRE), "sprite": win["sprite"].get(A.CENTRE),
                       "r_minus4": win["r_minus4"].get(A.CENTRE)}
                dv, info = doom2d(w, cands, 0)
                if any(v is not None for v in (dv, ans["box"], ans["box_reff"], ans["geo"])):
                    run["frames"] += 1
                    for rule in RULES80:
                        run[rule] += ans[rule] != dv
                    for rule, rad in (("box", lambda r: r), ("box_reff", lambda r: reff(w, r))):
                        wv = ans[rule]
                        if wv == dv:
                            continue
                        if dv is None:
                            k = "window hits, DOOM misses: " + info.get(wv, "?")
                        elif wv is None:
                            t = next(x for x in cands if (x[0], x[1]) == dv)
                            sp = A.box_span(w.rm, w.ws, t[2], t[3], rad(t[4]))
                            k = ("DOOM hits, window empty: nearer than MINZ or outside the FOV"
                                 if sp is None else
                                 "DOOM hits, window empty: the box misses col 80, the diagonal does not"
                                 if not sp[2] <= A.CENTRE <= sp[3] else
                                 "DOOM hits, window empty: the box covers col 80, the column was closed")
                        else:
                            k = "both hit, different targets (the window's, for DOOM: %s)" % info.get(
                                wv, "crossed and clear, but farther along the ray")
                        why[(rule, k)] += 1
                # -- pellets
                ceil = {col: doom2d(w, cands, s_)[0] for col, s_ in rep.items()}
                for s in spreads:
                    col = w.sites.col(s)
                    dv, _i = doom2d(w, cands, s)
                    pa = {"box": win["box"].get(col), "box_reff": wr.get(col), "ceiling": ceil[col],
                          "sprite": win["sprite"].get(col), "r_minus4": win["r_minus4"].get(col)}
                    if dv is None and pa["box"] is None and pa["box_reff"] is None:
                        continue
                    wt = 256 - abs(s)
                    rden += wt
                    for rule in RULESP:
                        if pa[rule] != dv:
                            rpw[rule] += wt
            say("%-24s col-80 frames %3d | %s | pellets: %s" % (
                name, run["frames"], " ".join("%s %d" % (r, run[r]) for r in RULES80),
                " ".join("%s %.1f%%" % (r, 100.0 * rpw[r] / max(1, rden)) for r in RULESP)))
            tot.update(run)
            pw.update(rpw)
            pden += rden
    n = max(1, tot["frames"])
    say("TOTAL col 80 (the pistol's accurate shot): %d frames in which doom, box, box_reff or geo "
        "names a target" % tot["frames"])
    for rule in RULES80:
        say("  %-9s != doom in %4d frames = %5.2f%%" % (rule, tot[rule], 100.0 * tot[rule] / n))
    say("TOTAL pellets (triangular-weighted rays that DOOM or a window hits something with):")
    for rule in RULESP:
        say("  %-9s != doom on %5.2f%% of the weight" % (rule, 100.0 * pw[rule] / max(1, pden)))
    for rule in ("box", "box_reff"):
        say("  %s != doom at col 80, by reason:" % rule)
        for (r2, k), v in why.most_common():
            if r2 == rule:
                say("    %4d  %s" % (v, k))
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
