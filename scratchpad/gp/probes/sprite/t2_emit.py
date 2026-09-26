"""Step 2: TODAY vs PROPOSED emission of a sprite column, per oracle frame.

  BASE   the harness alone (per-case register setup + the leaf call)
  PLAIN  TODAY's stream.emit_col_lines with the fragment switched off (the column as if no sprite)
  TODAY  TODAY's stream.emit_col_lines, sprite path (emit_region + sprite_runs + emit_region)
  PROP   gpspr.emit_col: (slot, block) record read back, window-first regions, no wall split
         when the fragment hides the wall, fast unclipped runs

Per variant: ops(2 passes) - ops(1 pass) over all the frame's cases = one pass; minus BASE.
CHECKS: TODAY == PLAIN with the fragment pasted (the harness wires the real macros right), and
PROP == TODAY pixel for pixel on every case (the proposal changes no pixel).

    python t2_emit.py                      # every heavy/melee frame
    python t2_emit.py heavy:gate664        # one frame
    python t2_emit.py --negative           # R9 control: a PROP with a one-row shift must FAIL
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
negative = "--negative" in sys.argv
frames = plib.by_frame(plib.load_cases())
keys = [tuple(a.split(":")) for a in args] or [k for k in frames if k[0] != "static"]

prop_fj = plib.PROP_FJ
if negative:
    src = prop_fj.read_text(encoding="utf-8")
    mut = src.replace("hex.sub_constant 4, gps_y0, 32768", "hex.sub_constant 4, gps_y0, 32767")
    assert mut != src
    prop_fj = Path(plib.tempfile.mkdtemp()) / "gp_sprite_col_mut.fj"
    prop_fj.write_text(mut, encoding="utf-8")


def pixels_equal(a, b):
    return a[0] == b[0] and a[1] == b[1]


results = []
for key in keys:
    fr = plib.Frame(frames[key])
    n = len(fr.cases)
    plain = {i: {"c_sprfl": 0} for i in range(n)}
    variants = [("BASE", [], None, ()), ("PLAIN", [plib.TODAY_EMIT], plain, ()),
                ("TODAY", [plib.TODAY_EMIT], None, ()), ("PROP", [plib.PROP_EMIT], None, (prop_fj,)),
                ("PROP2", [plib.PROP2_EMIT], None, (prop_fj,))]
    if negative:
        variants = [variants[0], variants[2], variants[3], variants[4]]
    res, outs = {}, {}
    t0 = time.time()
    for name, leaf, extra, xfj in variants:
        ops = []
        for p in (1, 2):
            o, out = plib.assemble_run(plib.program(fr, leaf, p, per_case_extra=extra),
                                       "%s_p%d" % (name, p), extra_fj=xfj)
            ops.append(o)
            if p == 1:
                outs[name] = plib.decode(out)
        res[name] = ops[1] - ops[0]
    per = {k: (res[k] - res["BASE"]) / n for k in res if k != "BASE"}
    # checks
    bad_prop = sum(1 for i in range(n) if not pixels_equal(outs["PROP"][i], outs["TODAY"][i]))
    bad_prop2 = sum(1 for i in range(n) if not pixels_equal(outs["PROP2"][i], outs["TODAY"][i]))
    bad_today = 0
    if "PLAIN" in outs:
        for i in range(n):
            want = dict(outs["PLAIN"][i][1])
            want.update(fr.expected_sprite_rows(i))
            bad_today += outs["TODAY"][i] != (outs["PLAIN"][i][0], want)
    runs = sum(len(c["runs"]) for c in fr.cases)
    row = dict(frame="%s:%s" % key, n=n, runs=runs, per=per, bad_prop=bad_prop, bad_prop2=bad_prop2,
               bad_today=bad_today, sec=round(time.time() - t0, 1))
    results.append(row)
    print("%-16s n=%3d runs/col=%4.1f  %s  PROP!=TODAY %d  PROP2!=TODAY %d  TODAY!=PLAIN+frag %d  (%.0fs)" %
          (row["frame"], n, runs / n,
           "  ".join("%s %6.0f" % (k, v) for k, v in per.items()), bad_prop, bad_prop2, bad_today,
           row["sec"]), flush=True)

if not negative:
    tot_n = sum(r["n"] for r in results)
    agg = {k: sum(r["per"][k] * r["n"] for r in results) / tot_n for k in results[0]["per"]}
    print("ALL %d columns (column-weighted):  %s" % (tot_n, "  ".join("%s %.0f" % kv for kv in agg.items())))
    print("PROP pixel-identical to TODAY on %d/%d columns, PROP2 on %d/%d, TODAY == PLAIN + oracle "
          "fragment on %d/%d" % (tot_n - sum(r["bad_prop"] for r in results), tot_n,
                                 tot_n - sum(r["bad_prop2"] for r in results), tot_n,
                                 tot_n - sum(r["bad_today"] for r in results), tot_n))
    name = "t2_emit_results.json" if not args else "t2_emit_results_%s.json" % "_".join(
        a.replace(":", "-") for a in args)
    (Path(__file__).resolve().parent / name).write_text(
        json.dumps(dict(frames=results, aggregate=agg), indent=1), encoding="utf-8")
else:
    b1 = sum(r["bad_prop"] for r in results)
    b2 = sum(r["bad_prop2"] for r in results)
    print("NEGATIVE CONTROL: the one-row-shifted PROP differs on %d columns, PROP2 on %d -> %s" %
          (b1, b2, "control PASSES (the check can fail)" if b1 and b2 else "control FAILS (the check is blind)"))
