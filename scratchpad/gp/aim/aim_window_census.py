"""P0 -- the AIM WINDOW design (docs/gp-aim-window.md), measured on the oracle's own walk.

    python scratchpad/gp/aim/aim_window_census.py [--s4 SNAPSHOT] [--staged] [--k 3] [--runs A,B]

For every frame of S4's combat set (the snapshot's checkpoints and key strings, replayed through
the gameplay model with the replay control) and, with --staged, census.py's six staged fights, the
ORACLE renders the frame (census_lib's hooks, no tracked file touched) and this script builds the
17-column aim window FROM THE WALK, several ways, and compares each with the model's default
geometric aim (`World.aim_geometric`) column by column:

  box      THE DESIGN: every shootable living thing whose leaf the walk reaches, projected with the
           renderer's own tz/tx/xscale; its RADIUS BOX's column span (x1b, x2b -- the same formula
           aim_geometric uses); written into each window column still OPEN at that moment
           (drawn[col] == 0, the snapshot census_lib takes when the thing arrives); the nearest
           integer depth wins, ties keep the earlier arrival. Eligible: depth MINZ..MISSILERANGE,
           |tx| <= tz<<2 -- NOT the sprite's min-size (a far barrel too small to draw still counts).
  box_draw the same, but eligible only when the sprite's BASE projection is accepted (drawable size)
  first    box, but the FIRST arrival wins (no depth compare)
  first_d  first, with plan D3 (d) emulated: inside a leaf, baked things in list order, then the
           runtime things by view depth (the order census_lib's depth_order option builds)
  sprite   NEGATIVE CONTROL: the sprite's drawn span (the census's picture aim, first writer)
  r_minus4 NEGATIVE CONTROL: the box with every radius 4 units smaller (a mutated span)
  no_occl  NEGATIVE CONTROL: the box, ignoring drawn[] (occlusion off)

Cost drivers, per frame: all arrivals and shootable arrivals (each pays the id test); `boxed`
(shootable, in range and in the FOV: pays the box math); `prepass` (boxed things that pass the
cheap centre stop |tx| - r <= tz/4 -- `pre_violation` counts window-overlapping things the stop
would have skipped, and must be 0); `overlap` (boxes that meet columns 72..88); `cov` (window
columns covered, open or not: each pays a drawn test); `visits` (open covered columns: each pays
the empty/depth test); and the design's writes (into an empty cell / over a farther target).
Output: a table per run and in total, and the reasons for every remaining 'box' disagreement, at
column 80 and over all 17 columns.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
GP = HERE.parent
sys.path.insert(0, str(GP))
import census_lib as CL                                                     # noqa: E402
from census import LETTERS, SCENARIOS, keys_of                              # noqa: E402
from census_lib import W, gd                                                # noqa: E402
from doomfj import combat as C                                              # noqa: E402
from doomfj.fixedpoint import _signed, fixed_mul                            # noqa: E402
from doomfj.reference_model import SPRITE_MINZ                              # noqa: E402

M32 = 0xFFFFFFFF
LO, HI, CENTRE = CL.AIM_LO, CL.AIM_HI, 80
RULES = ("box", "box_draw", "first", "first_d", "sprite", "r_minus4", "no_occl")
DRIVERS = ("arrivals", "shoot", "boxed", "prepass", "overlap", "pre_violation", "pre16_violation",
           "cov", "visits", "w_empty", "w_nearer", "w_kept")


def box_span(rm, ws, x, y, r):
    """(tz, tx, x1b, x2b) of a radius-r box at map (x, y) seen from the player's view, with
    `ReferenceModel.project_thing`'s own arithmetic (and `CombatMixin.aim_geometric`'s), or None
    when it is nearer than MINZ or outside the view (|tx| > tz<<2)."""
    cfg = rm.cfg
    vcos, vsin = rm.read_cos(ws.pangle), rm.read_sin(ws.pangle)
    tr_x = _signed((x << 16) - ws.px, 32)
    tr_y = _signed((y << 16) - ws.py, 32)
    tz = _signed(fixed_mul(tr_x & M32, vcos, 8, 4), 32) + _signed(fixed_mul(tr_y & M32, vsin, 8, 4), 32)
    if tz < SPRITE_MINZ:
        return None
    tx = -(_signed(fixed_mul(tr_y & M32, vcos, 8, 4), 32) - _signed(fixed_mul(tr_x & M32, vsin, 8, 4), 32))
    if abs(tx) > (tz << 2):
        return None
    xscale = rm._scale_recip_div(cfg.PROJECTION << 16, tz)
    cxf = cfg.CENTERX << 16
    x1 = (cxf + _signed(fixed_mul((tx - (r << 16)) & M32, xscale, 8, 4), 32)) >> 16
    x2 = ((cxf + _signed(fixed_mul((tx + (r << 16)) & M32, xscale, 8, 4), 32)) >> 16) - 1
    return tz, tx, x1, x2


def reff(w, r):
    """DOOM's diagonal half-width across a ray at the view angle: r * (|sin v| + |cos v|), rounded
    to whole units (plan: a per-frame table from the repo's sine table; float here)."""
    import math
    a = w.ws.pangle * 2 * math.pi / 2 ** 32
    return int(round(r * (abs(math.sin(a)) + abs(math.cos(a)))))


RADIUS = [lambda w, r: r]          # --reff swaps in `reff` (window AND geometric aim)


def target_of(w, meta):
    if meta.role == "live":
        m = meta.idx
        return ("mon", m), w.ws.mon_x[m], w.ws.mon_y[m], RADIUS[0](w, w.mon_radius[m])
    t = w.barrel_things[meta.idx]
    return ("bar", meta.idx), t.x, t.y, RADIUS[0](w, C.BARREL_R)


def patch_geometric(w):
    """--reff: World.aim_geometric reads radii through shootable_targets; scale them the same way."""
    orig = w.shootable_targets
    w.shootable_targets = lambda: [(k, i, x, y, RADIUS[0](w, r)) for (k, i, x, y, r) in orig()]


def windows(c, arr):
    """{rule: {col: target}} and the cost drivers (a Counter), from one render's arrivals."""
    w, rm = c.world, c.world.rm
    best = {r: {} for r in RULES}
    d = Counter()
    cands = []
    group, last_leaf = -1, None
    for order, a in enumerate(arr):
        if a["leaf"] != last_leaf:
            group, last_leaf = group + 1, a["leaf"]
        d["arrivals"] += 1
        meta = a["meta"]
        if meta is None or not meta.shoot:
            continue
        d["shoot"] += 1
        tgt, x, y, r = target_of(w, meta)
        span = box_span(rm, w.ws, x, y, r)
        if span is None or span[0] > (C.MISSILERANGE_U << 16):
            continue
        tz, tx, x1, x2 = span
        d["boxed"] += 1
        lo, hi = max(x1, LO), min(x2, HI)
        pre = abs(tx) - (r << 16) <= (tz >> 2)
        d["prepass"] += pre
        if lo <= hi:
            d["overlap"] += 1
            d["cov"] += hi - lo + 1
            d["pre_violation"] += not pre
            d["pre16_violation"] += not (abs(tx) - (r << 16) <= (tz >> 4))   # a too-tight stop: control
        dkey = (group, 0 if meta.baked else 1, order if meta.baked else tz, order)
        cands.append((order, a, tgt, tz, lo, hi, dkey, x, y, r))
    # the design's own write sequence: arrival order, write when empty or strictly nearer
    cell = {}
    for (order, a, tgt, tz, lo, hi, dkey, x, y, r) in cands:
        for col in range(lo, hi + 1):
            if a["drawn"][col]:
                continue
            d["visits"] += 1
            z = tz >> 16
            if col not in cell:
                d["w_empty"] += 1
                cell[col] = z
            elif z < cell[col]:
                d["w_nearer"] += 1
                cell[col] = z
            else:
                d["w_kept"] += 1
    for (order, a, tgt, tz, lo, hi, dkey, x, y, r) in cands:
        drawn = a["drawn"]
        for rule in ("box", "box_draw", "first", "first_d", "no_occl"):
            if rule == "box_draw" and a["rbase"] is None:
                continue
            key = {"box": (tz >> 16, order), "box_draw": (tz >> 16, order), "no_occl": (tz >> 16, order),
                   "first": (0, order), "first_d": dkey}[rule]
            for col in range(lo, hi + 1):
                if drawn[col] and rule != "no_occl":
                    continue
                if col not in best[rule] or key < best[rule][col][0]:
                    best[rule][col] = (key, tgt)
        span4 = box_span(rm, w.ws, x, y, max(1, r - 4))
        if span4 is not None:
            for col in range(max(span4[2], LO), min(span4[3], HI) + 1):
                if not drawn[col]:
                    key = (tz >> 16, order)
                    if col not in best["r_minus4"] or key < best["r_minus4"][col][0]:
                        best["r_minus4"][col] = (key, tgt)
        for col in set(a["A"]) | set(a["B"]):              # the drawn sprite span, first writer
            if LO <= col <= HI and col not in best["sprite"]:
                best["sprite"][col] = ((0, order), tgt)
    out = {rule: {col: v[1] for col, v in best[rule].items()} for rule in RULES}
    return out, d


def why_box(c, arr, col, geo, got):
    """Why the design's window and the geometric aim differ at `col`."""
    w, ws = c.world, c.world.ws
    arrived = {}
    for a in arr:
        m = a["meta"]
        if m is not None and m.shoot:
            arrived[target_of(w, m)[0]] = a
    if got is None:
        a = arrived.get(geo)
        if a is None:
            return "geo-only: its leaf was not reached (not visited, or after the full stop)"
        if a["drawn"][col]:
            return "geo-only: a solid wall had closed the column when it arrived (2D sight is open)"
        return "geo-only: other"
    if geo is None:
        tgt, x, y, _r = target_of(w, next(a["meta"] for a in arr if a["meta"] is not None
                                           and a["meta"].shoot and target_of(w, a["meta"])[0] == got))
        if not w.los_points((ws.px, ws.py), (x << 16, y << 16)):
            return "win-only: 2D sight to its centre is blocked (the column was open)"
        return "win-only: other"
    tg = {t: target_of(w, a["meta"]) for t, a in arrived.items()}
    zg = box_span(w.rm, ws, tg[geo][1], tg[geo][2], tg[geo][3])[0] if geo in tg else None
    zw = box_span(w.rm, ws, tg[got][1], tg[got][2], tg[got][3])[0]
    if geo not in arrived:
        return "both: geo's target was not reached"
    if arrived[geo]["drawn"][col]:
        return "both: geo's target sat behind a closed column"
    if zg is not None and zg >> 16 == zw >> 16:
        return "both: same integer depth, the tie went the other way"
    if zw < (zg or 0):
        x, y = tg[got][1], tg[got][2]
        if not w.los_points((ws.px, ws.py), (x << 16, y << 16)):
            return "both: the window's (nearer) target has no 2D sight to its centre"
    return "both: other"


def frames_s4(snap, runs, k):
    data = json.loads(Path(snap).read_text())
    for r in data["runs"]:
        if runs and r["name"] not in runs:
            continue
        cp = r["checkpoint"]
        c = CL.Census(cp.get("skill", gd.SK_HARD))
        c.world.k_heavy = k
        c.world.teleport_player(cp["x16"], cp["y16"], cp["angle"])
        keys = [{LETTERS[ch]: True for ch in s if LETTERS.get(ch)} for s in r["keys"]]
        yield "s4_" + r["name"], c, keys, r.get("model_final_digest")


def frames_staged(names, k):
    for name in names:
        setup, script = SCENARIOS[name]
        c = CL.Census(gd.SK_HARD)
        c.world.k_heavy = k
        setup(c.world)
        yield "st_" + name, c, keys_of(script), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--s4", default=str(GP / "census_out/s4v1/combat_scenarios_v1.snapshot.json"))
    ap.add_argument("--staged", action="store_true", help="also census.py's staged fights")
    ap.add_argument("--no-s4", action="store_true")
    ap.add_argument("--k", type=int, default=3, help="K the snapshot was frozen with (3)")
    ap.add_argument("--runs", default="")
    ap.add_argument("--out", default=str(HERE / "aim_window_census.txt"))
    ap.add_argument("--reff", action="store_true",
                    help="radius r -> r*(|sin v|+|cos v|) per frame, in the window AND the geometric aim")
    a = ap.parse_args()
    if a.reff:
        RADIUS[0] = reff
    sources = []
    if not a.no_s4:
        sources.append(frames_s4(a.s4, set(filter(None, a.runs.split(","))), a.k))
    if a.staged:
        sources.append(frames_staged([n for n in SCENARIOS if n != "quiet_walk"] + ["quiet_walk"],
                                     a.k))
    lines = []

    def say(s):
        print(s, flush=True)
        lines.append(s)
    say("aim window census: rules %s; K = %d; radius %s; snapshot %s" % (
        ",".join(RULES), a.k, "r*(|sin v|+|cos v|) (--reff)" if a.reff else "r", a.s4))
    tot = {"frames": 0, "fight": 0, "c80": Counter(), "cols": Counter(), "why": Counter(),
           "why_all": Counter(), "d": Counter(), "dmax": Counter(), "geo80": 0,
           "fight_d": Counter(), "box_vs_draw": 0}
    t0 = time.perf_counter()
    for src in sources:
        for name, c, keys, digest in src:
            w = c.world
            if a.reff:
                patch_geometric(w)
            run = {"frames": 0, "fight": 0, "c80": Counter(), "cols": Counter(), "d": Counter(),
                   "geo80": 0}
            for key in keys:
                w.tic(key)
                th, bk, me, mt = c.game_things()
                _fb, arr = c.render(th, bk, me, mt)
                win, d = windows(c, arr)
                geo = {col: w.aim_geometric(w, col) for col in range(LO, HI + 1)}
                fight = any(v is not None for v in geo.values()) or any(win["box"].values())
                run["frames"] += 1
                run["fight"] += fight
                run["d"].update(d)
                if fight:
                    tot["fight_d"].update(d)
                for k2, v in d.items():
                    tot["dmax"][k2] = max(tot["dmax"][k2], v)
                run["geo80"] += geo[CENTRE] is not None
                for rule in RULES:
                    got = win[rule]
                    if got.get(CENTRE) != geo[CENTRE]:
                        run["c80"][rule] += 1
                    run["cols"][rule] += sum(1 for col in range(LO, HI + 1)
                                             if got.get(col) != geo[col])
                tot["box_vs_draw"] += sum(1 for col in range(LO, HI + 1)
                                          if win["box"].get(col) != win["box_draw"].get(col))
                for col in range(LO, HI + 1):
                    if win["box"].get(col) != geo[col]:
                        why = why_box(c, arr, col, geo[col], win["box"].get(col))
                        tot["why_all"][why] += 1
                        if col == CENTRE:
                            tot["why"][why] += 1
            ctl = ("" if digest is None else
                   "  replay %s" % ("EQUALS" if w.digest() == digest else "!! DIFFERS"))
            nf = max(1, run["frames"])
            say("%-26s frames %3d (fight %3d) geo@80 %3d | col-80 disagreements: %s | "
                "all 17 cols: %s | boxed/frame %.2f overlap %.2f cov %.2f visits %.2f%s" % (
                    name, run["frames"], run["fight"], run["geo80"],
                    " ".join("%s %d" % (r, run["c80"][r]) for r in RULES),
                    " ".join("%s %d" % (r, run["cols"][r]) for r in RULES),
                    run["d"]["boxed"] / nf, run["d"]["overlap"] / nf, run["d"]["cov"] / nf,
                    run["d"]["visits"] / nf, ctl))
            for k2 in ("frames", "fight", "geo80"):
                tot[k2] += run[k2]
            tot["c80"].update(run["c80"])
            tot["cols"].update(run["cols"])
            tot["d"].update(run["d"])
    f, fi = tot["frames"], max(1, tot["fight"])
    say("TOTAL frames %d, fight frames %d (a target at some window column by either aim), "
        "geo target at col 80: %d frames" % (f, tot["fight"], tot["geo80"]))
    for rule in RULES:
        say("  %-9s col 80: %4d frames differ = %5.2f%% of fight frames | all 17 columns: %5d "
            "column-frames = %5.2f%% of fight column-frames" % (
                rule, tot["c80"][rule], 100.0 * tot["c80"][rule] / fi, tot["cols"][rule],
                100.0 * tot["cols"][rule] / (17 * fi)))
    say("  box vs box_draw, the two eligibility rules, directly: %d column-frames differ (of %d)"
        % (tot["box_vs_draw"], 17 * f))
    say("  cost drivers per frame (all frames | fight frames | max in one frame | total):")
    for k2 in DRIVERS:
        say("    %-15s %7.2f | %7.2f | %4d | %7d" % (k2, tot["d"][k2] / max(1, f),
                                                     tot["fight_d"][k2] / fi, tot["dmax"][k2],
                                                     tot["d"][k2]))
    say("  the design's ('box') remaining col-80 disagreements, by reason:")
    for k2, v in tot["why"].most_common():
        say("    %4d  %s" % (v, k2))
    say("  the design's ('box') remaining disagreements over all 17 columns (column-frames):")
    for k2, v in tot["why_all"].most_common():
        say("    %4d  %s" % (v, k2))
    say("(%.0f s)" % (time.perf_counter() - t0))
    Path(a.out).write_text("\n".join(lines) + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
