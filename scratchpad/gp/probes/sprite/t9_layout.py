"""Step 9: LAYOUT NOISE -- how far the SAME logic's price moves when only its addresses move.

An fj op's price follows the popcount of the addresses it flips, so every standalone comparison
in this probe compares two LAYOUTS as well as two pieces of logic. This re-prices TODAY and PROP2
with dead ops inserted (a) before the leaf -- the emission, t2's measurement -- and (b) before the
record pre-loop -- the end-to-end pipeline, t8's measurement. The spread over the shifts is the
noise floor a TODAY-vs-PROPOSED delta has to clear. (The repo's msframe A-vs-A self-test is the
same idea for wall-clock time.)

    python t9_layout.py emit [scen:vp]     # t2-style: BASE/TODAY/PROP2 x shifts, slope over passes
    python t9_layout.py e2e [scen:vp]      # t8-style: HARN/TODAY/PROP2 x shifts, one pass
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402
import t5_recload as t5                                                      # noqa: E402

part = sys.argv[1]
key = tuple(sys.argv[2].split(":")) if len(sys.argv) > 2 else ("heavy", "gate664")
fr = plib.Frame(plib.by_frame(plib.load_cases())[key])
n = len(fr.cases)
H = plib.H
TODAY_REC = t5.TODAY_REC.replace("rep(703, i) stl.fj 0, 0", "")      # as t8 (see its LAYOUT note)
assert TODAY_REC != t5.TODAY_REC
LOAD_T = ("frame.lines_spr_load p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
          "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb")
EMIT_T = plib.TODAY_EMIT.replace("c_sprfl, c_ssy1, c_ssy2, c_sy0b, c_sblk, c_slr, c_ssy1b, c_ssy2b, "
                                 "c_sy0bb, c_sblkb, c_slrb",
                                 "p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
                                 "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb")
EMIT_P2 = plib.PROP2_EMIT.replace("c_sprfl, c_s, c_sblk", "p2_sprfl, p2_s, p2_sblk")
assert EMIT_T != plib.TODAY_EMIT and EMIT_P2 != plib.PROP2_EMIT
HOT = "\n".join(t5.DECLS + ["gp_armd: hex.vec 2"])


def rec_setup(i):
    c = fr.cases[i]
    s = fr.slot_of[i]
    return ["hex.set 8, trb_col_x, %d" % c["x"], "hex.set 8, trb_tx2, %d" % c["x"],
            "hex.set 8, trb_frac_u, 0", "hex.set 8, trb_tistep, 0", "hex.set 2, trb_dw_max, 20",
            "hex.set w/4, trb_drawn_b, drawn", "frame.ptr_index4 trb_drawn_p, trb_drawn_b, trb_col_x",
            "hex.set w/4, trb_sprflag_b, sprflag",
            "frame.ptr_index4 trb_sprflag_p, trb_sprflag_b, trb_col_x",
            "hex.set w/4, trb_blk_const, %d" % i, "hex.set 1, hdfl, 1", "hex.set 1, ballow, 1",
            "hex.set 8, trb_y0, %d" % (fr.slot_y0[s - 1] & 0xFFFFFFFF),
            "hex.set 2, trb_shade_row, %d" % c["lr"]]


def build(v):
    pre = ["hex.set 2, gps_nslot, 0", "hex.set 2, gps_cur_s, 0"]
    for i in range(n):
        pre += rec_setup(i)
        if v == "PROP2":
            if i == 0 or fr.slot_of[i] != fr.slot_of[i - 1]:
                pre.append("gpspr.rec_thing")
            pre.append("gpspr.rec_cols2 32, 1, 1, 9")
        elif v == "TODAY":
            pre.append("frame.gp_today_rec 32, 6, 16, 1, 1, 9, %d" % H)
    return pre


def leaf(v):
    head = ["hex.zero 8, gp_k", "hex.mov 2, gp_k, c_x", "frame.lines_spr_seed gp_k",
            "hex.read_byte gp_armd, p2_spfp"]
    if v == "HARN":
        return head + [plib.TODAY_EMIT]
    if v == "TODAY":
        return head + [LOAD_T, EMIT_T]
    return head + ["gpspr.load p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb", EMIT_P2]


def run(text, name):
    return plib.assemble_run(text, name, extra_fj=(plib.PROP_FJ,), want_output=False)[0]


rows = []
if part == "emit":
    shifts = (0, 1500, 4000, 9000)
    for sh in shifts:
        t0 = time.time()
        res = {}
        for name, lf in (("BASE", []), ("TODAY", [plib.TODAY_EMIT]), ("PROP2", [plib.PROP2_EMIT])):
            o = [run(plib.program(fr, lf, p, shift_leaf=sh), "%s_%d_%d" % (name, sh, p)) for p in (1, 2)]
            res[name] = o[1] - o[0]
        t = (res["TODAY"] - res["BASE"]) / n
        p2 = (res["PROP2"] - res["BASE"]) / n
        rows.append((sh, t, p2))
        print("  emission, leaf shifted %5d ops:  TODAY %7.0f  PROP2 %7.0f  delta %7.0f  (%+.1f%%)  (%.0fs)" %
              (sh, t, p2, p2 - t, 100 * (p2 / t - 1), time.time() - t0), flush=True)
elif part == "e2e":
    shifts = (0, 1500, 4000)
    for sh in shifts:
        t0 = time.time()
        res = {}
        for v in ("HARN", "TODAY", "PROP2"):
            text = plib.program(fr, leaf(v), 1, pre_loop=build(v), extra_text=TODAY_REC, hot_text=HOT,
                                prefilled_slots=False, shift_pre=sh,
                                per_case_extra={i: {"c_sprfl": 0} for i in range(n)} if v == "HARN" else None)
            res[v] = run(text, "%s_%d" % (v, sh))
        t = (res["TODAY"] - res["HARN"]) / n
        p2 = (res["PROP2"] - res["HARN"]) / n
        rows.append((sh, t, p2))
        print("  end-to-end, pre-loop shifted %5d ops:  TODAY %7.0f  PROP2 %7.0f  delta %7.0f  (%+.1f%%)  (%.0fs)" %
              (sh, t, p2, p2 - t, 100 * (p2 / t - 1), time.time() - t0), flush=True)
else:
    raise SystemExit("usage: t9_layout.py emit|e2e [scen:vp]")


def spread(vals):
    return "%.0f .. %.0f (%.1f%% of the mean)" % (min(vals), max(vals),
                                                   100.0 * (max(vals) - min(vals)) / (sum(vals) / len(vals)))


print("%s %s over %d shifts: TODAY %s; PROP2 %s; PROP2-TODAY %s .. %s (%.1f%% .. %.1f%%)" % (
    part, key, len(rows), spread([r[1] for r in rows]), spread([r[2] for r in rows]),
    "%.0f" % min(r[2] - r[1] for r in rows), "%.0f" % max(r[2] - r[1] for r in rows),
    100 * min(r[2] / r[1] - 1 for r in rows), 100 * max(r[2] / r[1] - 1 for r in rows)))
