"""S5 v2 -- WHY the frozen set never draws a fireball, and what a drawn one would cost.

    python scratchpad/gp/census_v2_fireball.py [--file scratchpad/gp/scenarios/combat_scenarios_v2.json]
        -> census_out/s4v2/fireballs.txt

Replays every run that spawns a fireball exactly as census_v2.py does (scenarios_v2.apply_setup +
str_to_keys on a census_lib World) and, on every frame with a fireball in flight, renders the
DECIDED D3 picture (`rec`) twice:
  RULE   as decided: fireballs exempt from the soft budgets (b), so the base minimum applies --
         MIN_SPRITE_H = 3 rows for any non-monster sprite;
  FLOOR  the same with that base minimum at 0 for fireballs only, so every fireball that projects
         on screen at all is accepted -- a DIAGNOSTIC picture, never priced.
Each fireball in flight is classified by the first reason it is not drawn under RULE:
  not reached    no arrival: its leaf was never visited (wedge cull) or every column was already
                 walled when the walk got there -- split by scenarios_v2's geometric test (does
                 its radius box project onto the screen?): "box ON screen" would be a cull bug;
  off screen     it arrived, but projects nowhere even at size 0 (behind the player, outside the view);
  too small      it projects, but shorter than 3 rows (the FLOOR render gives its height and depth);
  hidden         accepted, but every column it wanted was taken (walls or both slots);
  drawn          it claimed a column.
It also reports DOOM's own question for each fireball -- 2D line of sight from the player -- and the
replay control (the model's final digest must equal the frozen one).

THE PRICE OF A DRAWN FIREBALL comes from the staged fights (census_out/staged_sky, `rec`), where
fireballs are drawn: columns per drawn fireball, priced with census_report's per-column units.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics as ST
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import census_lib as CL                                                      # noqa: E402
import census_report as CR                                                   # noqa: E402
import scenarios_v2 as SV2                                                   # noqa: E402
from census_lib import W                                                     # noqa: E402
from doomfj.combat import FIREBALL_R                                         # noqa: E402

EXEMPT = lambda m: m.role in ("fireball", "barrel")                          # noqa: E731  (rec's b)


def rec_things(c):
    return c.reorder_small_first(*c.game_things(corpse_as_monster=False, depth_order=True))


def box_on_screen(w, x16: int, y16: int) -> bool:
    """scenarios_v2's geometric test: does the fireball's radius box project onto the 160 columns?"""
    sp = SV2.span_on_screen(w, x16 >> 16, y16 >> 16, FIREBALL_R)
    return sp is not None and sp[2] >= 0 and sp[1] <= w.rm.cfg.VIEW_W - 1


def fireball_rows(arr):
    return {a["meta"].idx: a for a in arr if a["meta"] is not None and a["meta"].role == "fireball"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(HERE / "scenarios" / "combat_scenarios_v2.json"))
    ap.add_argument("--staged", default=str(HERE / "census_out" / "staged_sky" / "*.jsonl"))
    a = ap.parse_args()
    doc = json.loads(Path(a.file).read_text())
    why, los_of = Counter(), Counter()
    small_h, small_tz, small_dist, drawn_dist = [], [], [], []
    frames_fb = 0
    for run in doc["runs"]:
        if not run["totals"].get("proj_spawns"):
            continue
        c = CL.Census(SV2.SKILL)
        w, ws = c.world, c.world.ws
        SV2.apply_setup(w, run["setup"])
        n_run = Counter()
        for s in run["keys"]:
            w.tic(SV2.str_to_keys(s))
            live = [p for p in range(W.FIREBALL_POOL) if ws.proj_active[p]]
            if not live:
                continue
            frames_fb += 1
            _fb, arr = c.render(*rec_things(c), exempt=EXEMPT)
            rule = fireball_rows(arr)
            base = CL.MIN_SPRITE_H
            CL.MIN_SPRITE_H = 0                           # FLOOR: fireballs (exempt) use min 0
            try:
                _fb0, arr0 = c.render(*rec_things(c), exempt=lambda m: m.role == "fireball")
            finally:
                CL.MIN_SPRITE_H = base
            floor = fireball_rows(arr0)
            for p in live:
                x, y = ws.proj_x[p], ws.proj_y[p]
                dist = W.aprox_distance((x - ws.px) >> 16, (y - ws.py) >> 16)
                los = w.los_points((ws.px, ws.py), (x, y))
                r, r0 = rule.get(p), floor.get(p)
                if r is not None and (r["A"] or r["B"]):
                    k = "drawn"
                    drawn_dist.append(dist)
                elif r is None and r0 is None:
                    k = "not reached, box %s screen" % ("ON" if box_on_screen(w, x, y) else "off")
                elif r0 is None or r0["res"] is None:
                    k = "off screen (box %s screen)" % ("ON" if box_on_screen(w, x, y) else "off")
                elif r is None or r["res"] is None:
                    k = "too small (< %d rows)" % base
                    small_h.append(r0["res"][3])
                    small_tz.append(r0["res"][5] >> 16)
                    small_dist.append(dist)
                else:
                    k = "hidden (walls or both slots)"
                why[k] += 1
                n_run[k] += 1
                los_of[(k, "LOS" if los else "no LOS")] += 1
        print("run %-20s fireballs in flight on %3d frames: %s | digest %s" % (
            run["name"], sum(1 for _ in n_run.elements()),
            ", ".join("%s %d" % kv for kv in sorted(n_run.items())),
            "EQUALS" if w.digest() == run["model_final_digest"] else "!! DIFFERS"), flush=True)
    tot = sum(why.values())
    print("\nALL: %d fireball-frames on %d frames with a fireball in flight (the set's 14 spawns)"
          % (tot, frames_fb))
    for k, v in why.most_common():
        print("  %-30s %4d (%4.1f%%)  with 2D line of sight: %d" % (
            k, v, 100.0 * v / max(1, tot), los_of[(k, "LOS")]))
    if small_h:
        print("  too small: projected height %d..%d rows (median %.1f); depth %d..%d units (median %d);"
              " distance %d..%d" % (min(small_h), max(small_h), ST.median(small_h), min(small_tz),
                                    max(small_tz), ST.median(small_tz), min(small_dist), max(small_dist)))
    if drawn_dist:
        print("  drawn: distance %d..%d" % (min(drawn_dist), max(drawn_dist)))
    # the price of a drawn fireball, from the staged fights (where fireballs ARE drawn)
    cols, n_drawn, frames = [], 0, 0
    for path in sorted(glob.glob(a.staged)):
        for line in open(path):
            r = json.loads(line)
            if r["variant"] != "rec":
                continue
            frames += 1
            d = r.get("drawn", {}).get("fireball", 0)
            if d:
                n_drawn += d
                cols.append(r.get("cols_role", {}).get("fireball", 0) / d)
    if cols:
        m = ST.mean(cols)
        print("\nSTAGED FIGHTS (%s, rec): %d frames draw a fireball (%d drawn); columns per drawn fireball"
              " mean %.1f, median %.1f, max %.0f -> ~%.0fK ops today, ~%.0fK with the v2 column (slot A"
              " units, census_report; + one load and one projection, %.0fK)" % (
                  a.staged, len(cols), n_drawn, m, ST.median(cols), max(cols),
                  m * CR.COL_A[False] / 1e3, m * CR.COL_A[True] / 1e3, (CR.LOAD + CR.PROJ) / 1e3))


if __name__ == "__main__":
    main()
