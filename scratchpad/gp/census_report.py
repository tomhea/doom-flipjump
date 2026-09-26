"""S5 -- the census tables, the D3 option prices and the fight line, from census.py's JSON lines.

    python scratchpad/gp/census_report.py [--glob "census_out/*.jsonl"] [--share 0.3 --share80 0.6]

UNIT COSTS (ops). PER THING and PER COLUMN are kept apart, so nothing is counted twice:
  LOAD   19,464  per RUNTIME thing arrival: sim.thing_load, MEASURED in-game (plan section 3)
  PROJ   14,999  per arrival: proj.project_thing mean, MEASURED in-game (profiler an_calls). NOT the
                 per-thing thing_leaf 30.2K / thing_leaf_b 15.4K: those are whole thing_record_body
                 calls and include its column loop, i.e. the per-column RECORD priced below.
  COL_A  per slot-A sprite column, END TO END (record + lines_spr load + the sprite's emission
         share), S6b docs/gp-sprite-column.md 4.1 standalone median / the median standalone-to-
         blocked27 factor 1.70 (UNVERIFIED in-game):
           TODAY 43,873 (74,584 / 1.70; the three frames give 42-54K)
           v2    26,688 (45,370 / 1.70; 24-31K) -- lands in P1, before any monster moves
  COL_B  per slot-B fragment (the B path is unprototyped): the A price minus the regions it does not
         re-split, by S6b's 4.3 components -- TODAY x0.665 (record+load+runs 47,071 of 70,796),
         v2 x0.765 (31,607 of 41,320). UNVERIFIED.
CROSS-CHECK on gamespeed's MEASURED per-frame means (81.8 arrivals, 19.3 runtime loads, 15.1 sprite
columns): TODAY units give 2.27M against 2.55M MEASURED for the same objects (thing_leaf 0.58 +
thing_leaf_b 0.97 + thing_load 0.38 + sprite_runs 0.17 + emit_region 0.29 + lines_spr seed/step 0.08):
the model is ~11% low (per-accepted-thing overhead and thing_load_cold are not in it).

THE BINDING EFFECT ON S4's RUN STRUCTURE (`--b0`, S4's scratchpad/gp/scenarios/b0_v1.json): each S4
run's MEASURED blocked27 average (avg_exact) plus that run's mean modelled delta, then gamespeed's own
`binding_speed` over the ten runs -- (mean + the p80 RUN) / 2. The binding is a function of the run
averages only, so a per-run mean delta is exact arithmetic; the deltas themselves are the unit-cost
model. The report first recomputes B0's binding from its run averages and must hit b0_v1.json's.
"""
from __future__ import annotations

import argparse
import glob
import json
import statistics as ST
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "12m"))
import gamespeed as GS                                                      # noqa: E402  (binding_speed)
LOAD, PROJ, FACTOR = 19464, 14999, 1.70
COL_A = {False: 74584 / FACTOR, True: 45370 / FACTOR}          # TODAY, v2 (the `cut` flag)
COL_B = {False: COL_A[False] * 47071 / 70796, True: COL_A[True] * 31607 / 41320}
SCMP, BUF = 249, 600          # (d): one 8-nibble compare per pair (MEASURED 249), buffering (UNVERIFIED)
AIMW, PROJX = 62, 7500        # (e): an aim-window write (S6 MEASURED 62); finishing a projection past
                              #      the min-size reject (half a projection, UNVERIFIED)
VARIANTS = ("game", "a", "b", "c", "d", "abcd", "rec")


def ops(r, cut=False):
    return (LOAD * r["arr_rt"] + PROJ * (r["arr_rt"] + r["arr_bk"])
            + COL_A[cut] * r["colsA"] + COL_B[cut] * r["colsB"])


def category(g):
    """quiet: nothing of a fight is drawn. heavy: >= 4 awake monsters drawn, or >= 80 sprite
    columns (a fireball bursting in the player's face covers 100+). post-kill: a corpse drawn and at
    most one awake monster. typical: the rest (1-3 awake monsters, or effects only)."""
    d, cr = g.get("drawn", {}), g.get("cols_role", {})
    awake, corpse = d.get("live_awake", 0), d.get("corpse", 0)
    small = sum(d.get(k, 0) for k in ("drop", "fireball", "fx"))
    fight_cols = sum(cr.get(k, 0) for k in ("live", "corpse", "drop", "fireball", "fx"))
    if not (awake or corpse or small):
        return "quiet"
    if awake >= 4 or fight_cols >= 80:
        return "heavy"
    if corpse and awake <= 1:
        return "post-kill"
    return "typical"


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))] if v else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--glob", nargs="+", default=[str(HERE / "census_out" / "*.jsonl")])
    ap.add_argument("--share", type=float, default=0.30)
    ap.add_argument("--share80", type=float, default=0.60)
    ap.add_argument("--b0", default=str(HERE / "scenarios" / "b0_v1.json"),
                    help="S4's B0 (per-run blocked27 averages) for the binding section")
    a = ap.parse_args()
    frames = defaultdict(dict)                       # (scen, tic) -> variant -> record
    for path in sorted(p for g in a.glob for p in glob.glob(g)):
        for line in open(path):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            frames[(r["scen"], r["tic"])][r["variant"]] = r
    keys = sorted(frames)
    scens = sorted({k[0] for k in keys})
    cat = {k: category(frames[k]["game"]) for k in keys}
    print("FRAMES: %d over %d scenarios (every rendered tic x 8 pictures)" % (len(keys), len(scens)))
    for s in scens:
        ks = [k for k in keys if k[0] == s]
        g = [frames[k]["game"] for k in ks]
        cc = defaultdict(int)
        for k in ks:
            cc[cat[k]] += 1
        print("  %-14s %3d frames  kills %2d  mean alive-drawn %.1f awake-drawn %.1f corpses %.1f "
              "fireballs %.2f fx %.2f drops %.2f  | %s" % (
                  s, len(ks), max(r["kills_so_far"] for r in g),
                  ST.mean(r.get("drawn", {}).get("live", 0) + r.get("drawn", {}).get("live_awake", 0) for r in g),
                  ST.mean(r.get("drawn", {}).get("live_awake", 0) for r in g),
                  ST.mean(r["corpses"] for r in g), ST.mean(r["fireballs"] for r in g),
                  ST.mean(r["fx"] for r in g), ST.mean(r["drops"] for r in g),
                  " ".join("%s %d" % kv for kv in sorted(cc.items()))))

    def census_row(recs):
        n = len(recs)
        m = lambda f: sum(f(r) for r in recs) / max(1, n)                               # noqa: E731
        fr = lambda f: 100.0 * sum(1 for r in recs if f(r)) / max(1, n)                 # noqa: E731
        return {
            "live_deg": m(lambda r: r["deg"].get("live", 0)),
            "live_deg_fr%": fr(lambda r: r["deg"].get("live", 0)),
            "los_degraded": m(lambda r: r["seen"]["why"].get("degraded", 0)),
            "los_slots": m(lambda r: r["seen"]["why"].get("slots", 0)),
            "los_wall": m(lambda r: r["seen"]["why"].get("wall-occluded", 0)),
            "los_notdrawn_inview": m(lambda r: r["seen"]["los_not_drawn_inview"]),
            "e_los_not_inview": m(lambda r: r["seen"]["e_los_not_inview"]),
            "drawn_no_los": m(lambda r: r["seen"]["drawn_no_los"]),
            "small_acc": m(lambda r: r["small"]["things"]),
            "small_part": m(lambda r: r["small"]["part_hidden"]),
            "small_all": m(lambda r: r["small"]["all_hidden"]),
            "small_deg": m(lambda r: r["small"]["deg"]),
            "small_hid_cols%": 100.0 * sum(r["small"]["hidden_cols"] for r in recs)
            / max(1, sum(r["small"]["wanted_cols"] for r in recs)),
            "inv_baked": m(lambda r: r["inv"]["baked_first"]),
            "inv_index": m(lambda r: r["inv"]["index"]),
            "inv_cross": m(lambda r: r["inv"]["cross_leaf"]),
            "inv_fr%": fr(lambda r: sum(r["inv"].values())),
            "near_hidden": m(lambda r: r["near_hidden"]),
            "corpse_soft": m(lambda r: r["corpses_acc_soft"]),
            "live_deg_after_corpse_fr%": fr(lambda r: r["live_deg_after_corpse"] > 0),
            "aim_pic": m(lambda r: r["aim"]["pic"]),
            "aim_pic80_fr%": fr(lambda r: r["aim"]["pic80"]),
            "aim_pn": m(lambda r: r["aim"].get("pn", 0)),
            "aim_pn80_fr%": fr(lambda r: r["aim"].get("pn80", 0)),
            "aim_e": m(lambda r: r["aim"]["e"]),
            "aim_e80_fr%": fr(lambda r: r["aim"]["e80"]),
            "aim_ed": m(lambda r: r["aim"]["ed"]),
            "aim_ed80_fr%": fr(lambda r: r["aim"]["ed80"]),
            "colsA": m(lambda r: r["colsA"]), "colsB": m(lambda r: r["colsB"]),
            "runs": m(lambda r: r["runs"]), "arr_rt": m(lambda r: r["arr_rt"]),
            "arr_bk": m(lambda r: r["arr_bk"]), "acc": m(lambda r: r["acc"]),
            "ops": m(lambda r: ops(r)), "ops_cut": m(lambda r: ops(r, True)),
            "rt_pairs": m(lambda r: r["rt_pairs_in_leaf"]),
            "rt_multi": m(lambda r: r["rt_leaves_multi"]),
        }
    fight = [k for k in keys if cat[k] != "quiet"]
    print("\nCENSUS -- the model's picture under TODAY's compositor rules ('game'), per frame, mean:")
    rows = [("all frames", keys), ("fight frames", fight)] + [
        ("  " + s, [k for k in keys if k[0] == s]) for s in scens]
    hdr = ("live_deg", "los_degraded", "los_slots", "drawn_no_los", "small_acc", "small_all",
           "small_deg", "inv_baked", "inv_index", "inv_cross", "corpse_soft", "aim_pic",
           "aim_pic80_fr%")
    print("  %-16s " % "" + " ".join("%13s" % h for h in hdr))
    for name, ks in rows:
        cr = census_row([frames[k]["game"] for k in ks])
        print("  %-16s " % name + " ".join("%13.2f" % cr[h] for h in hdr))
    cg = census_row([frames[k]["game"] for k in fight])
    print("  fight frames: live monsters degraded in %.0f%% of frames; a depth inversion in %.0f%%;"
          " small things hidden in %.0f%% of their wanted columns; a live monster degraded AFTER"
          " corpses took soft slots in %.0f%%" % (cg["live_deg_fr%"], cg["inv_fr%"],
                                                  cg["small_hid_cols%"], cg["live_deg_after_corpse_fr%"]))
    print("\nD3 OPTIONS on the fight frames (mean per frame; ops = the unit costs in the docstring):")
    hdr2 = ("live_deg", "los_notdrawn_inview", "los_degraded", "los_slots", "los_wall",
            "e_los_not_inview", "small_part", "small_all",
            "small_hid_cols%", "inv_baked", "inv_index", "near_hidden", "aim_pic", "aim_pn", "aim_e",
            "aim_ed", "aim_pic80_fr%", "aim_ed80_fr%", "colsA", "colsB", "acc", "ops")
    print("  %-6s " % "" + " ".join("%11s" % h[:11] for h in hdr2))
    base = census_row([frames[k]["game"] for k in fight])
    for v in VARIANTS:
        if any(v not in frames[k] for k in fight):
            continue
        cr = census_row([frames[k][v] for k in fight])
        print("  %-6s " % v + " ".join("%11.2f" % cr[h] for h in hdr2)
              + "   d_ops %+9.0f  (v2 %+9.0f)" % (cr["ops"] - base["ops"], cr["ops_cut"] - base["ops_cut"]))
    dd = census_row([frames[k]["d"] for k in fight])
    print("  (d) mechanism: %.2f leaves with >1 runtime arrival, %.2f pairs per frame -> %.0f ops/frame"
          " (compares %d + buffering %d per thing, UNVERIFIED)" % (
              dd["rt_multi"], dd["rt_pairs"], dd["rt_pairs"] * SCMP + 2 * dd["rt_multi"] * BUF, SCMP, BUF))
    print("  (e) mechanism: %.2f degraded live monsters/frame x %d + window writes -> ~%.0f ops/frame"
          " (UNVERIFIED)" % (base["live_deg"], PROJX, base["live_deg"] * PROJX + 17 * AIMW * 2))
    print("\nFIGHT LINE -- sprite ops per frame. FL = picture - todayR4 at the SAME viewpoint and the")
    print("SAME unit costs (today's column, or v2 on both sides); 'rules' = today's compositor ('game') or the")
    print("recommended one ('abcd'):")
    has_rec = all("rec" in frames[k] for k in keys)
    print("  %-10s %5s %6s %6s %6s %6s %6s %9s %9s %9s %9s %9s%s" % (
        "category", "n", "arr_rt", "colsA", "colsB", "runs", "baseA", "game", "FL today",
        "FL v2", "FL abcd", "abcd v2", "   FL rec    rec v2" if has_rec else ""))
    cats = ("quiet", "typical", "heavy", "post-kill")
    for cname in cats + ("ALL",):
        ks = [k for k in keys if cname == "ALL" or cat[k] == cname]
        if not ks:
            continue
        g = [frames[k]["game"] for k in ks]
        t4 = [frames[k]["todayR4"] for k in ks]
        ab = [frames[k]["abcd"] for k in ks]
        print("  %-10s %5d %6.1f %6.1f %6.1f %6.0f %6.1f %8.2fM %+8.2fM %+8.2fM %+8.2fM %+8.2fM" % (
            cname, len(ks), ST.mean(r["arr_rt"] for r in g), ST.mean(r["colsA"] for r in g),
            ST.mean(r["colsB"] for r in g), ST.mean(r["runs"] for r in g),
            ST.mean(r["colsA"] for r in t4), ST.mean(ops(r) for r in g) / 1e6,
            ST.mean(ops(x) - ops(y) for x, y in zip(g, t4)) / 1e6,
            ST.mean(ops(x, True) - ops(y, True) for x, y in zip(g, t4)) / 1e6,
            ST.mean(ops(x) - ops(y) for x, y in zip(ab, t4)) / 1e6,
            ST.mean(ops(x, True) - ops(y, True) for x, y in zip(ab, t4)) / 1e6)
              + ((" %+8.2fM %+8.2fM" % (
                  ST.mean(ops(frames[k]["rec"]) - ops(frames[k]["todayR4"]) for k in ks) / 1e6,
                  ST.mean(ops(frames[k]["rec"], True) - ops(frames[k]["todayR4"], True) for k in ks) / 1e6))
                 if has_rec else ""))
    # the split the unit costs keep apart: PER THING (load + project) vs PER COLUMN (A + B)
    for cname in ("heavy", "ALL"):
        ks = [k for k in keys if cname == "ALL" or cat[k] == cname]
        if not ks:
            continue
        for v in ("game",) + (("rec",) if has_rec else ()):
            d = {f: ST.mean(frames[k][v][f] - frames[k]["todayR4"][f] for k in ks)
                 for f in ("arr_rt", "arr_bk", "colsA", "colsB")}
            thing = LOAD * d["arr_rt"] + PROJ * (d["arr_rt"] + d["arr_bk"])
            print("  FL split, %-5s %-4s: per thing %+.2fM (d arr_rt %+.1f, d arr_bk %+.1f) | per column"
                  " today %+.2fM, v2 %+.2fM (d colsA %+.1f, d colsB %+.1f)" % (
                      cname, v, thing / 1e6, d["arr_rt"], d["arr_bk"],
                      (COL_A[False] * d["colsA"] + COL_B[False] * d["colsB"]) / 1e6,
                      (COL_A[True] * d["colsA"] + COL_B[True] * d["colsB"]) / 1e6, d["colsA"], d["colsB"]))
    dist = sorted(ops(frames[k]["game"]) - ops(frames[k]["todayR4"]) for k in fight)
    print("  distribution of FL today over the fight frames: p10 %+.2fM p50 %+.2fM p80 %+.2fM"
          " p95 %+.2fM max %+.2fM" % tuple(pct(dist, q) / 1e6 for q in (0.1, 0.5, 0.8, 0.95, 1.0)))
    r4 = ST.mean(ops(frames[k]["todayR4"]) - ops(frames[k]["today"]) for k in keys)
    cutb = ST.mean(ops(frames[k]["todayR4"], True) - ops(frames[k]["todayR4"]) for k in keys)
    print("  separate lines, all frames: R4 (todayR4 - today) %+.2fM; the column cut on the baseline"
          " picture %+.2fM (both viewpoint-dependent: these are staged fights, not gamespeed)"
          % (r4 / 1e6, cutb / 1e6))
    for name, v, cut in (("game, today column", "game", False), ("game, v2 column", "game", True),
                         ("abcd, v2 column", "abcd", True)) + ((("rec, v2 column", "rec", True),)
                                                               if has_rec else ()):
        f_ = [ops(frames[k][v], cut) - ops(frames[k]["todayR4"], cut) for k in fight]
        q_ = [ops(frames[k][v], cut) - ops(frames[k]["todayR4"], cut) for k in keys
              if cat[k] == "quiet"]
        mf, qf = ST.mean(f_), (ST.mean(q_) if q_ else 0.0)
        b = (a.share * mf + (1 - a.share) * qf + a.share80 * mf + (1 - a.share80) * qf) / 2
        print("  BINDING (%s): fight-frame mean %+.2fM, quiet %+.2fM; fight share %.0f%% in the mean"
              " run and %.0f%% in the p80 run [ASSUMED] -> %+.2fM on (mean+p80)/2" % (
                  name, mf / 1e6, qf / 1e6, 100 * a.share, 100 * a.share80, b / 1e6))
    # per RUN (a scenario = a run): the binding statistic's own shape, gamespeed.percentile_run
    print("\nPER RUN (each scenario is one run; FL averaged over ALL its frames, quiet ones included):")
    share = 100.0 * len(fight) / max(1, len(keys))
    print("  fight share MEASURED here (frames with an awake monster, corpse or effect drawn):"
          " %.0f%% of %d frames" % (share, len(keys)))
    per_run = {}
    for s in scens:
        ks = [k for k in keys if k[0] == s]
        per_run[s] = tuple(ST.mean(ops(frames[k][v], cut) - ops(frames[k]["todayR4"], cut)
                                   for k in ks)
                           for v, cut in (("game", False), ("game", True), ("abcd", True))
                           + ((("rec", True),) if has_rec else ()))
        print("  %-22s %4d frames  FL today %+6.2fM  FL v2 %+6.2fM  FL abcd+v2 %+6.2fM%s  (fight %3.0f%%)"
              % (s, len(ks), per_run[s][0] / 1e6, per_run[s][1] / 1e6, per_run[s][2] / 1e6,
                 ("  FL rec+v2 %+6.2fM" % (per_run[s][3] / 1e6)) if has_rec else "",
                 100.0 * sum(1 for k in ks if cat[k] != "quiet") / len(ks)))
    if len(per_run) >= 2:
        for j, name in enumerate(("today column", "v2 column", "abcd + v2 column")
                                 + (("rec + v2 column",) if has_rec else ())):
            v = sorted(r[j] for r in per_run.values())
            p80 = v[min(len(v) - 1, -(-8 * len(v) // 10) - 1)]
            print("  (mean + p80)/2 of the per-run FL, %s: %+.2fM (mean %+.2fM, p80 run %+.2fM)."
                  " UNVERIFIED as a binding delta: B0's per-run totals decide which run is the p80"
                  " run" % (name, (ST.mean(v) + p80) / 2e6, ST.mean(v) / 1e6, p80 / 1e6))
    b0_section(a.b0, frames, keys, scens, cat, has_rec)


def b0_section(b0_path, frames, keys, scens, cat, has_rec):
    """The fight line on S4's OWN run structure: B0's MEASURED per-run averages + the per-run mean
    modelled delta, through gamespeed.binding_speed (see the module docstring)."""
    if not all(s.startswith("s4_") for s in scens) or not Path(b0_path).exists():
        return
    b0 = json.loads(Path(b0_path).read_text())
    base = {r["name"]: r["avg_exact"] for r in b0["runs"]}
    runs = [s[3:] for s in scens]
    print("\nBINDING ON S4's RUN STRUCTURE (B0 = %s, blocked27 sha %s; %d runs x %s frames)"
          % (Path(b0_path).name, b0["sha256"][:16], len(base),
             sorted({sum(1 for k in keys if k[0] == s) for s in scens})))
    if sorted(runs) != sorted(base):
        print("  !! the census runs %s are not B0's runs %s -- no binding arithmetic" % (runs, sorted(base)))
        return
    order = [r["name"] for r in b0["runs"]]
    b_bind = GS.binding_speed([base[n] for n in order])
    print("  B0 CHECK: binding_speed of B0's run averages = %s; b0_v1.json says %s -> %s" % (
        format(round(b_bind), ","), format(round(b0["binding"]), ","),
        "EQUAL" if abs(b_bind - b0["binding"]) < 1 else "!! DIFFERENT"))

    def per_run(f):
        return {n: ST.mean(f(frames[k]) for k in keys if k[0] == "s4_" + n) for n in order}
    lines = [("FL, today column", per_run(lambda F: ops(F["game"]) - ops(F["todayR4"]))),
             ("FL, v2 column", per_run(lambda F: ops(F["game"], True) - ops(F["todayR4"], True))),
             ("FL abcd, v2 column", per_run(lambda F: ops(F["abcd"], True) - ops(F["todayR4"], True)))]
    if has_rec:
        lines.append(("FL rec, v2 column", per_run(lambda F: ops(F["rec"], True) - ops(F["todayR4"], True))))
    r4 = per_run(lambda F: ops(F["todayR4"]) - ops(F["today"]))
    cut = per_run(lambda F: ops(F["todayR4"], True) - ops(F["todayR4"]))
    model_today = per_run(lambda F: ops(F["today"]))
    fight = {n: 100.0 * sum(1 for k in keys if k[0] == "s4_" + n and cat[k] != "quiet")
             / sum(1 for k in keys if k[0] == "s4_" + n) for n in order}
    print("  %-20s %11s %6s %9s %9s %9s %9s %9s %9s %9s" % (
        "run", "B0 avg", "fight", "FL today", "FL v2", "abcd v2", "rec v2" if has_rec else "-",
        "R4", "v2 cut", "model/B0"))
    for n in order:
        print("  %-20s %11s %5.0f%% %+8.2fM %+8.2fM %+8.2fM %9s %+8.2fM %+8.2fM %8.1f%%" % (
            n, format(round(base[n]), ","), fight[n], lines[0][1][n] / 1e6, lines[1][1][n] / 1e6,
            lines[2][1][n] / 1e6, ("%+8.2fM" % (lines[3][1][n] / 1e6)) if has_rec else "-",
            r4[n] / 1e6, cut[n] / 1e6, 100.0 * model_today[n] / base[n]))
    if has_rec:
        lines.append(("rec + v2 + R4 (sprite side, all)",
                      {n: lines[3][1][n] + r4[n] + cut[n] for n in order}))
    lines.append(("FL, today column, x1.11 (model-low)", {n: 1.11 * lines[0][1][n] for n in order}))

    def show(label, delta):
        new = [base[n] + delta[n] for n in order]
        b = GS.binding_speed(new)
        p80 = GS.percentile_run(new)
        who = next(n for n in order if base[n] + delta[n] == p80)
        print("  %-36s binding %s (%+.2fM = %+.1f%%)  mean %s  p80 run %s = %s" % (
            label, format(round(b), ","), (b - b_bind) / 1e6, 100 * (b - b_bind) / b_bind,
            format(round(sum(new) / len(new)), ","), who, format(round(p80), ",")))
    show("B0 (blocked27, MEASURED)", {n: 0.0 for n in order})
    for label, d in lines:
        show(label, d)


if __name__ == "__main__":
    main()
