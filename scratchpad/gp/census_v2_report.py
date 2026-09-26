"""S5 v2 -- the census, the fight line and the binding effect on the FROZEN combat scenario set v2,
for the handoff's budget table. Reads census_v2.py's JSON lines; prices with census_report.py's unit
costs, imported unchanged (its docstring has them and their provenance).

    python scratchpad/gp/census_v2_report.py [--dir scratchpad/gp/census_out/s4v2]
                                             [--b0 scratchpad/gp/scenarios/b0_v2.json]
        -> census_out/s4v2/report_s4v2.txt (the caller redirects)

PICTURES: `game` = the model's picture under TODAY's compositor rules; `rec` = the DECIDED D3
(a + c + d + e; b for projectiles and barrels); `todayR4` = blocked27's picture skill-filtered (the
fight line's baseline); `today` = blocked27's picture (what B0 measured).
FIGHT LINE (FL) = picture - todayR4 at the same viewpoint and the same unit costs, with today's
sprite column or with the v2 column (S6b) on BOTH sides. Frame categories are census_report's
(`category`, from the `game` picture): quiet / typical / heavy (>= 4 awake monsters drawn or >= 80
fight columns -- the census's own class, not world.K_HEAVY) / post-kill.
BINDING: gamespeed.binding_speed over the eleven runs -- B0's MEASURED per-run averages (and the
strafe proxy's) plus each run's mean modelled delta. The statistic depends on the run averages only,
so adding per-run means is exact arithmetic; the deltas are the unit-cost model. B0's own binding is
recomputed from its run averages first and must match b0_v2.json.
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
sys.path.insert(0, str(HERE))
import census_report as CR                                                   # noqa: E402

GS = CR.GS
CATS = ("quiet", "typical", "heavy", "post-kill")


def fl(F, v, cut):
    return CR.ops(F[v], cut) - CR.ops(F["todayR4"], cut)


def dist_line(vals):
    v = sorted(vals)
    return "p10 %+.2fM  p50 %+.2fM  p80 %+.2fM  p95 %+.2fM  max %+.2fM  (mean %+.2fM)" % (
        tuple(CR.pct(v, q) / 1e6 for q in (0.1, 0.5, 0.8, 0.95, 1.0)) + (ST.mean(v) / 1e6,))


def census_rows(recs):
    n = max(1, len(recs))
    m = lambda f: sum(f(r) for r in recs) / n                                   # noqa: E731
    fr = lambda f: 100.0 * sum(1 for r in recs if f(r)) / n                     # noqa: E731
    small_w = sum(r["small"]["wanted_cols"] for r in recs)
    return [
        ("live monsters degraded / frame", m(lambda r: r["deg"].get("live", 0)), "%.2f"),
        ("  frames with one (%)", fr(lambda r: r["deg"].get("live", 0)), "%.0f"),
        ("in view + 2D LOS, NOT drawn (picture 'seen')", m(lambda r: r["seen"]["los_not_drawn_inview"]), "%.2f"),
        ("  of which degraded", m(lambda r: r["seen"]["why"].get("degraded", 0)), "%.2f"),
        ("  of which lost to the two slots", m(lambda r: r["seen"]["why"].get("slots", 0)), "%.2f"),
        ("  same, 'seen' at column open (e)", m(lambda r: r["seen"]["e_los_not_inview"]), "%.2f"),
        ("drawn WITHOUT 2D LOS", m(lambda r: r["seen"]["drawn_no_los"]), "%.2f"),
        ("small things accepted / frame", m(lambda r: r["small"]["things"]), "%.2f"),
        ("  fully hidden (slot A taken)", m(lambda r: r["small"]["all_hidden"]), "%.2f"),
        ("  their wanted columns hidden (%)", 100.0 * sum(r["small"]["hidden_cols"] for r in recs)
         / max(1, small_w), "%.0f"),
        ("  degraded by the soft budget", m(lambda r: r["small"]["deg"]), "%.2f"),
        ("depth inversions: baked-first", m(lambda r: r["inv"]["baked_first"]), "%.2f"),
        ("  by index (same leaf)", m(lambda r: r["inv"]["index"]), "%.2f"),
        ("  across leaves", m(lambda r: r["inv"]["cross_leaf"]), "%.2f"),
        ("  a NEARER fragment hidden", m(lambda r: r["near_hidden"]), "%.2f"),
        ("  frames with an inversion (%)", fr(lambda r: sum(r["inv"].values())), "%.0f"),
        ("corpses spending monster soft slots", m(lambda r: r["corpses_acc_soft"]), "%.2f"),
        ("  frames: live degraded after them (%)", fr(lambda r: r["live_deg_after_corpse"] > 0), "%.0f"),
        ("aim col 80: picture (first writer) != geometric (% fr)", fr(lambda r: r["aim"]["pic80"]), "%.1f"),
        ("aim col 80: SPRITE-PIXEL window at column open != geo", fr(lambda r: r["aim"]["ed80"]), "%.1f"),
        ("aim cols 72-88: picture != geometric (cols / frame)", m(lambda r: r["aim"]["pic"]), "%.2f"),
        ("sprite columns: slot A / frame", m(lambda r: r["colsA"]), "%.1f"),
        ("sprite columns: slot B / frame", m(lambda r: r["colsB"]), "%.1f"),
    ]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(HERE / "census_out" / "s4v2"))
    ap.add_argument("--b0", default=str(HERE / "scenarios" / "b0_v2.json"))
    a = ap.parse_args()
    d = Path(a.dir)
    frames = defaultdict(dict)
    for path in sorted(glob.glob(str(d / "s4v2_*.jsonl"))):
        for line in open(path):
            r = json.loads(line)
            frames[(r["scen"][5:], r["tic"])][r["variant"]] = r
    keys = sorted(frames)
    runs = sorted({k[0] for k in keys})
    missing = [k for k in keys if set(frames[k]) != {"today", "todayR4", "game", "rec"}]
    cat = {k: CR.category(frames[k]["game"]) for k in keys}
    fight = [k for k in keys if cat[k] != "quiet"]
    print("S5 v2 -- the FROZEN combat scenario set v2 (843f28a): census, fight line, binding")
    print("source: %s/s4v2_*.jsonl (census_v2.py); %d runs x %s frames = %d frames, 4 pictures each%s"
          % (d.as_posix(), len(runs), sorted({sum(1 for k in keys if k[0] == s) for s in runs}),
             len(keys), "" if not missing else " -- !! %d frames lack a picture" % len(missing)))
    log = d / "run_s4v2.log"
    if log.exists():
        for line in open(log):
            if line.startswith(("S4 set", "recorded file hashes", "ALL CONTROLS")):
                print("  " + line.rstrip())
    print("unit costs: census_report.py (LOAD %d + PROJ %d per runtime arrival, PROJ per baked arrival;"
          " slot A column %.0f today / %.0f v2, slot B %.0f / %.0f)" % (
              CR.LOAD, CR.PROJ, CR.COL_A[False], CR.COL_A[True], CR.COL_B[False], CR.COL_B[True]))

    print("\n1. FRAMES (categories from the `game` picture; drawn counts from `rec`)")
    for s in runs:
        ks = [k for k in keys if k[0] == s]
        g = [frames[k]["rec"] for k in ks]
        cc = defaultdict(int)
        for k in ks:
            cc[cat[k]] += 1
        dr = lambda role: ST.mean(r.get("drawn", {}).get(role, 0) for r in g)          # noqa: E731
        print("  %-20s kills %d | drawn: awake %.2f asleep %.2f corpses %.2f drops %.2f fx %.2f"
              " fireballs %.2f (in flight %.2f) barrels %.2f | %s" % (
                  s, max(r["kills_so_far"] for r in g), dr("live_awake"), dr("live"), dr("corpse"),
                  dr("drop"), dr("fx"), dr("fireball"), ST.mean(r["fireballs"] for r in g),
                  dr("barrel"), " ".join("%s %d" % kv for kv in sorted(cc.items()))))
    print("  all: %d frames, %d fight frames (%.1f%%): %s" % (
        len(keys), len(fight), 100.0 * len(fight) / len(keys),
        ", ".join("%s %d" % (c_, sum(1 for k in keys if cat[k] == c_)) for c_ in CATS)))

    print("\n2. CENSUS -- per frame, mean. today's rules = `game`; decided D3 = `rec` (a + c + d + e, b for"
          " projectiles and barrels)")
    print("  %-55s %11s %11s   %11s %11s" % ("", "today fight", "D3 fight", "today all", "D3 all"))
    rows = [census_rows([frames[k][v] for k in ks]) for v, ks in
            (("game", fight), ("rec", fight), ("game", keys), ("rec", keys))]
    for i, (name, _v, f) in enumerate(rows[0]):
        print("  %-55s %11s %11s   %11s %11s" % ((name,) + tuple(f % r[i][1] for r in rows)))
    print("  NOTE the decided (e) aim window records RADIUS BOXES, not sprite pixels (docs/gp-aim-window.md"
          " section 0: column 80 differs from the geometric aim in 0.06% of frames, MEASURED there on the"
          " v1 set + staged fights, not re-measured on v2). The two aim rows above are the PICTURE rule and"
          " a sprite-pixel window -- what the box window replaces.")

    print("\n3. FIGHT LINE -- sprite ops per frame, FL = picture - todayR4 (same viewpoint, same units)")
    print("  %-10s %5s | %6s %6s %6s | %9s %9s | %9s %9s" % (
        "category", "n", "arr_rt", "colsA", "colsB", "today col", "v2 col", "today col", "v2 col"))
    print("  %-10s %5s | %-20s | %-19s | %-19s" % ("", "", "  (rec picture)", "  today's rules", "  decided D3"))
    for cname in CATS + ("ALL",):
        ks = [k for k in keys if cname == "ALL" or cat[k] == cname]
        if not ks:
            continue
        R = [frames[k]["rec"] for k in ks]
        print("  %-10s %5d | %6.1f %6.1f %6.1f | %+8.2fM %+8.2fM | %+8.2fM %+8.2fM" % (
            cname, len(ks), ST.mean(r["arr_rt"] for r in R), ST.mean(r["colsA"] for r in R),
            ST.mean(r["colsB"] for r in R),
            ST.mean(fl(frames[k], "game", False) for k in ks) / 1e6,
            ST.mean(fl(frames[k], "game", True) for k in ks) / 1e6,
            ST.mean(fl(frames[k], "rec", False) for k in ks) / 1e6,
            ST.mean(fl(frames[k], "rec", True) for k in ks) / 1e6))
    print("  distribution over the %d fight frames:" % len(fight))
    for label, v, cut in (("today's rules, today col", "game", False), ("today's rules, v2 col", "game", True),
                          ("decided D3,   today col", "rec", False), ("decided D3,   v2 col", "rec", True)):
        print("    %-26s %s" % (label, dist_line([fl(frames[k], v, cut) for k in fight])))
    for v in ("game", "rec"):
        dd = {f: ST.mean(frames[k][v][f] - frames[k]["todayR4"][f] for k in keys)
              for f in ("arr_rt", "arr_bk", "colsA", "colsB")}
        thing = CR.LOAD * dd["arr_rt"] + CR.PROJ * (dd["arr_rt"] + dd["arr_bk"])
        print("  split, all frames, %-4s: per THING %+.2fM (arrivals rt %+.1f, baked %+.1f) | per COLUMN"
              " %+.2fM today, %+.2fM v2 (slot A %+.1f, slot B %+.1f)" % (
                  v, thing / 1e6, dd["arr_rt"], dd["arr_bk"],
                  (CR.COL_A[False] * dd["colsA"] + CR.COL_B[False] * dd["colsB"]) / 1e6,
                  (CR.COL_A[True] * dd["colsA"] + CR.COL_B[True] * dd["colsB"]) / 1e6,
                  dd["colsA"], dd["colsB"]))

    print("\n4. BINDING on v2's run structure (gamespeed.binding_speed; 11 runs x 100 frames)")
    b0 = json.loads(Path(a.b0).read_text())
    order = [r["name"] for r in b0["runs"]]
    if sorted(order) != runs:
        print("  !! B0's runs %s are not the census's %s" % (order, runs))
        return
    base = {r["name"]: r["avg_exact"] for r in b0["runs"]}
    su = b0["strafe_undercount"]
    proxy = {n: su["per_run"][n]["avg_exact_proxy"] for n in order}
    bb = GS.binding_speed([base[n] for n in order])
    bp = GS.binding_speed([proxy[n] for n in order])
    print("  B0 CHECK: binding_speed(B0 run averages) = %s vs b0_v2.json %s -> %s; proxy %s vs %s -> %s" % (
        format(round(bb), ","), format(round(b0["binding"]), ","),
        "EQUAL" if abs(bb - b0["binding"]) < 1 else "!! DIFFERENT", format(round(bp), ","),
        format(round(su["binding_proxy"]), ","),
        "EQUAL" if abs(bp - su["binding_proxy"]) < 1 else "!! DIFFERENT"))

    def per_run(f):
        return {n: ST.mean(f(frames[k]) for k in keys if k[0] == n) for n in order}
    L = {"FL game today": per_run(lambda F: fl(F, "game", False)),
         "FL game v2": per_run(lambda F: fl(F, "game", True)),
         "FL rec today": per_run(lambda F: fl(F, "rec", False)),
         "FL rec v2": per_run(lambda F: fl(F, "rec", True)),
         "R4": per_run(lambda F: CR.ops(F["todayR4"]) - CR.ops(F["today"])),
         "cut": per_run(lambda F: CR.ops(F["todayR4"], True) - CR.ops(F["todayR4"])),
         "model today": per_run(lambda F: CR.ops(F["today"]))}
    L["sprite side"] = {n: L["FL rec v2"][n] + L["R4"][n] + L["cut"][n] for n in order}
    print("  %-20s %11s %11s %5s | %8s %8s %8s | %8s %8s | %9s %8s" % (
        "run", "B0 avg", "proxy avg", "fight", "(i)", "(ii)", "(iii)", "R4", "v2 cut", "(iv) all", "model/B0"))
    for n in order:
        nf = sum(1 for k in keys if k[0] == n)
        print("  %-20s %11s %11s %4.0f%% | %+7.2fM %+7.2fM %+7.2fM | %+7.2fM %+7.2fM | %+8.2fM %7.1f%%" % (
            n, format(round(base[n]), ","), format(round(proxy[n]), ","),
            100.0 * sum(1 for k in keys if k[0] == n and cat[k] != "quiet") / nf,
            L["FL game today"][n] / 1e6, L["FL game v2"][n] / 1e6, L["FL rec v2"][n] / 1e6,
            L["R4"][n] / 1e6, L["cut"][n] / 1e6, L["sprite side"][n] / 1e6,
            100.0 * L["model today"][n] / base[n]))

    def show(label, b_runs, b_ref, delta):
        new = [b_runs[n] + delta[n] for n in order]
        b = GS.binding_speed(new)
        p80 = GS.percentile_run(new)
        who = next(n for n in order if b_runs[n] + delta[n] == p80)
        print("  %-52s %s  (%+.2fM, %+.1f%%)  mean %s  p80 run %s %s" % (
            label, format(round(b), ","), (b - b_ref) / 1e6, 100.0 * (b - b_ref) / b_ref,
            format(round(sum(new) / len(new)), ","), who, format(round(p80), ",")))
    zero = {n: 0.0 for n in order}
    print("  -- on B0 (MEASURED %s):" % format(round(bb), ","))
    show("B0", base, bb, zero)
    show("(i)   + FL, today's rules, today's column", base, bb, L["FL game today"])
    show("(ii)  + FL, today's rules, v2 column", base, bb, L["FL game v2"])
    show("(iii) + FL, decided D3, v2 column", base, bb, L["FL rec v2"])
    show("(iv)  whole sprite side: D3 + v2 column + skill filter", base, bb, L["sprite side"])
    show("      (+ FL, decided D3, today's column)", base, bb, L["FL rec today"])
    show("      ((i) x 1.11, the model's measured low bias)", base, bb,
         {n: 1.11 * L["FL game today"][n] for n in order})
    print("  -- on the strafe PROXY B0 (%s):" % format(round(bp), ","))
    show("proxy B0", proxy, bp, zero)
    show("(iii) + FL, decided D3, v2 column", proxy, bp, L["FL rec v2"])
    show("(iv)  whole sprite side", proxy, bp, L["sprite side"])

    print("\n5. FIREBALLS")
    inflight = sum(1 for k in keys if frames[k]["rec"]["fireballs"])
    drawn_fb = {v: sum(frames[k][v].get("drawn", {}).get("fireball", 0) for k in keys) for v in ("game", "rec")}
    print("  frames with a fireball in flight: %d of %d; fireballs drawn: %d (today's rules), %d (decided D3)"
          % (inflight, len(keys), drawn_fb["game"], drawn_fb["rec"]))
    fb = d / "fireballs.txt"
    if fb.exists():
        print("  census_v2_fireball.py (%s):" % fb.as_posix())
        for line in open(fb):
            if line.strip() and not line.startswith("exit"):
                print("    " + line.rstrip())

    print("\n6. CAVEATS")
    for c_ in CAVEATS:
        print("  - " + c_)


CAVEATS = (
    "FIREBALLS ARE NOT PRICED. The set never draws one (section 5): of its 284 fireball-frames, 229"
    " are off screen (every one of them off screen by scenarios_v2's geometric box test, so the"
    " wedge cull hides nothing visible) and 55 are 910-1425 units away, 0-1 rows tall, under the"
    " 3-row minimum that (b) does not lift. So the fight line holds ZERO fireball columns, and the"
    " fireball stand-in (freedoom1's real BAL patches, drawn standing on the leaf floor, not at"
    " flight height) is untested by this set. Where fireballs ARE drawn (the staged fights) one"
    " costs a mean 66 columns (median 90: most burst at the player): ~2.9M ops per frame drawn"
    " with today's column, ~1.8M with v2 (+34K per thing). Every 1% of a run's frames that draws"
    " one adds ~0.018M (v2) to that run's average.",
    "Sprite sizes are stand-ins (the real patch of each state's frame and rotation); the animated"
    " bank does not exist.",
    "Column costs are S6b's standalone medians / the 1.70 standalone-to-game factor (UNVERIFIED"
    " in-game). The unit-cost model read ~11% low against gamespeed's MEASURED means (the x1.11"
    " line). Slot B is unprototyped: its x0.665 (today) / x0.765 (v2) of slot A is UNVERIFIED --"
    " and the decided D3 raises slot-B columns (section 2).",
    "The fight line is SPRITES ONLY: no AI, simulation, projectile or HUD cost. The mechanisms of"
    " (d) and (e) are not in it (v1's models: ~8K and ~12K per fight frame; the aim window ~0.05M"
    " per fight frame, docs/gp-aim-window.md, UNVERIFIED).",
    "Binding lines add each run's MEAN modelled delta to B0's MEASURED run average: exact for the"
    " statistic's shape, a model in the deltas. B0 follows the model's camera; the strafe proxy"
    " adds the same deltas to its own run averages.",
    "Categories are the census's (heavy = >= 4 awake monsters drawn or >= 80 fight columns in the"
    " `game` picture), not world.K_HEAVY. d_awake differs from the set's on 10 frames of"
    " R2-spectre-corridor only because the two count 'awake' differently (target vs not in A_Look).",
    "The model's aim is geometric; the view is 160x100.",
)


if __name__ == "__main__":
    main()
