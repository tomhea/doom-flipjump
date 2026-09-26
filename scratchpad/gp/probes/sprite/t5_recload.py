"""Step 5: the RECORD half (pass 1, per recorded column) and the pass-2 LOAD, TODAY vs PROPOSED.

TODAY's record loop is TRANSPLANTED from src/fj/frame_render.fj at run time (the text between
`col_loop:` and `set_tstop:` inside frame.thing_record_body), so it cannot drift from the source;
the loader is the real frame.lines_spr_load. One thing covers columns [0, K); the per-column
price is the slope over K in {2, 10}; the per-thing price is what is left at K = 0.
The sprflag reset between passes (write-once slots) is priced alone and subtracted.
Correctness: after TODAY record+load and PROPOSED record+load+derive, the fragment the emit sees
(sy1, sy2, y_base, block, light) must be equal -- printed by the check pass.
"""
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

SRCTXT = (plib.ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8")
body = SRCTXT[SRCTXT.index("def thing_record_body"):]
seg = body[body.index("      col_loop:"):body.index("      set_tstop:")]
LABELS = "col_loop, col_body, u_clamp, col_check, slot_check, slot_a, slot_b, slot_done, bucket_mul, " \
         "bucket_mul_done, do_store, col_next, ret"
CODE = "\n".join(l.split("//")[0] for l in seg.splitlines())
GLOB = sorted(set(re.findall(r"\btrb_[a-z0-9_]+\b", CODE)) | {"ballow", "hdfl", "sprbank", "spslot"})
TODAY_REC = ("ns frame {\n    def gp_today_rec buckets, blkshift, slotstride, deg, spn, nld, viewh @ %s < %s {\n%s      ret:\n    }\n}\n"
             % (LABELS, ", ".join(GLOB), seg))
DECLS = ["drawn:"] + [";0 * dw"] * 160 + ["sprflag:"] + [";0 * dw"] * 160 + \
        ["spslot:"] + [";0 * dw"] * (160 * 16) + \
        ["hdfl: hex.vec 1", "ballow: hex.vec 1", "gps_nslot: hex.vec 2", "gps_s_rec: hex.vec 2",
         "gps_yb8: hex.vec 8", "p2_s: hex.vec 2", "p2_sb: hex.vec 2", "gp_rb: hex.vec w/4", "gp_rp: hex.vec w/4",
         "gp_zero2: hex.vec 2", "gp_k: hex.vec 8", "gp_kl: hex.vec 2"]


def thing_setup(fr, i, K):
    c = fr.cases[i]
    s = fr.slot_of[i]
    return ["hex.set 8, trb_col_x, 0", "hex.set 8, trb_tx2, %d" % (K - 1), "hex.set 8, trb_frac_u, 0",
            "hex.set 8, trb_tistep, 0", "hex.set 2, trb_dw_max, 20",
            "hex.set w/4, trb_drawn_b, drawn", "frame.ptr_index4 trb_drawn_p, trb_drawn_b, trb_col_x",
            "hex.set w/4, trb_sprflag_b, sprflag", "frame.ptr_index4 trb_sprflag_p, trb_sprflag_b, trb_col_x",
            "hex.set w/4, trb_blk_const, %d" % i, "hex.set 1, hdfl, 1", "hex.set 1, ballow, 1",
            "hex.set 8, trb_y0, %d" % (fr.slot_y0[s - 1] & 0xFFFFFFFF), "hex.set 2, trb_shade_row, %d" % c["lr"],
            "hex.set 2, gps_nslot, %d" % (s - 1)]


def reset(K):
    return (["hex.set w/4, gp_rb, sprflag", "hex.set w/4, gp_rp, 0", "frame.ptr_index4 gp_rp, gp_rb, gp_rp"]
            + ["frame.write_byte5 gp_rp, gp_zero2", "hex.ptr_add gp_rp, 1"] * K)


REC_T = ["frame.gp_today_rec 32, 6, 16, 1, 1, 9, %d" % plib.H]
REC_P = ["gpspr.rec_thing", "gpspr.rec_cols 32, 6, 1, 1, 9"]
REC_P2 = ["gpspr.rec_thing", "gpspr.rec_cols2 32, 1, 1, 9"]


def load_t(K):
    return (["hex.set 8, gp_k, 0", "frame.lines_spr_seed gp_k"] +
            ["frame.lines_spr_load p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
             "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb", "frame.lines_spr_step"] * K)


def load_p(K):
    return (["hex.set 8, gp_k, 0", "frame.lines_spr_seed gp_k"] +
            ["gpspr.load p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb", "frame.lines_spr_step"] * K)


def run(fr, idx, leaf_fn, name):
    per = []
    for K in (2, 10):
        extra = {}
        leaf = []
        # the thing setup is per CASE (the harness's stub), so fold it into the leaf by case index
        # via per-case registers: simplest is one program per case set with the leaf taking the
        # setup from the stub -- here we inline it by generating one leaf per case.
        tot = 0
        for i in idx:
            text = plib.program(fr, thing_setup(fr, i, K) + leaf_fn(K), 1, only=[i], lite=True,
                                extra_text=TODAY_REC, hot_text="\n".join(DECLS))
            o, out = plib.assemble_run(text, "%s_%d_%d" % (name, i, K), extra_fj=(plib.PROP_FJ,),
                                       want_output=False)
            tot += o
        per.append(tot)
    slope = (per[1] - per[0]) / 8.0 / len(idx)
    icpt = per[0] / len(idx) - 2 * slope
    return slope, icpt


if __name__ == "__main__":
    fr = plib.Frame(plib.by_frame(plib.load_cases())[("heavy", "gate664")])
    idx = [0, 20, 40, 60]
    out = {}
    for name, fn in (("BASE", lambda K: []),
                     ("RESET", lambda K: reset(K)),
                     ("REC_T", lambda K: REC_T + reset(K)),
                     ("REC_P", lambda K: REC_P + reset(K)),
                     ("REC_P2", lambda K: REC_P2 + reset(K)),
                     ("LOAD_T", lambda K: REC_T + load_t(K) + reset(K)),
                     ("LOAD_P", lambda K: REC_P + load_p(K) + reset(K))):
        t0 = time.time()
        out[name] = run(fr, idx, fn, name)
        print("  %-7s slope %8.0f /column   intercept %9.0f   (%.0fs)" % (name, out[name][0], out[name][1],
                                                                        time.time() - t0), flush=True)
    rs = out["RESET"][0] - out["BASE"][0]
    print("record per column: TODAY %.0f  PROPOSED %.0f  PROPOSED+nibble-address %.0f" % (
        out["REC_T"][0] - out["RESET"][0], out["REC_P"][0] - out["RESET"][0], out["REC_P2"][0] - out["RESET"][0]))
    print("per thing (K=0 intercept, over BASE+RESET): TODAY %.0f  PROPOSED %.0f" %
          (out["REC_T"][1] - out["RESET"][1], out["REC_P"][1] - out["RESET"][1]))
    print("load per column: TODAY %.0f  PROPOSED %.0f" % (out["LOAD_T"][0] - out["REC_T"][0],
                                                        out["LOAD_P"][0] - out["REC_P"][0]))
