"""Step 3: where a sprite column's emission goes, TODAY and PROPOSED, on one oracle frame.

  SR       TODAY  stream.sprite_runs                                   (the runs + block setup)
  REG2     TODAY  the prologue + emit_region(0,sy1) + emit_region(sy2,H) (no runs)
  DER      PROP   gpspr.frag_derive                                    (slot fetch, block header)
  DERRUNS  PROP   frag_derive + gpspr.runs
  PREG2    PROP   the prologue + the window-first regions / covered path (no runs)
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

key = tuple(sys.argv[1].split(":")) if len(sys.argv) > 1 else ("heavy", "gate664")
fr = plib.Frame(plib.by_frame(plib.load_cases())[key])
n = len(fr.cases)
PRO = ["hex.mov 2, ecl_ctake, c_cexcl",
       "hex.cmp 2, ecl_ctake, c_fstart, bd_ok, bd_ok, bd_clamp",
       "bd_clamp:", "hex.mov 2, ecl_ctake, c_fstart", "bd_ok:",
       "byte.emit c_x", "stream.wpx_grain_col c_gnrow, ecl_cmidx",
       "hex.set 2, ecl_ccy, %d" % plib.cfg.CENTERY, "hex.zero 2, ecl_full_lo",
       "hex.set 2, ecl_full_hi, %d" % plib.H]
REG = ("stream.emit_region %s, %d, 0, 0, 1, 1, 1, %d, 0, 1, 1, ecl_ctake, c_fstart, c_wlit, c_wlit2, "
       "c_gnrow, c_wstrip, wstripbase, c_cbufa, c_cbufd, c_fbufa, c_fbufd, ecl_win_lo, ecl_win_end, "
       "ecl_wlo, ecl_whi, ecl_ptr, ecl_ccy, ecl_cmidx, bd_qwalk, bd_qret")
TODAY_REG2 = PRO + [REG % ("ecl_full_lo, c_ssy1", plib.H, plib.WPXSTRIDE),
                    REG % ("c_ssy2, ecl_full_hi", plib.H, plib.WPXSTRIDE),
                    "stl.output_char 0xFF", ";bd_end", "bd_qwalk: ;0", "bd_qret: ;0", "bd_end:"]
PREG = ("gpspr.emit_region %s, %d, ecl_ctake, c_fstart, c_wlit, c_wlit2, c_gnrow, c_cbufa, c_cbufd, "
        "c_fbufa, c_fbufd, ecl_wlo, ecl_whi, ecl_ccy, ecl_cmidx")
PROP_REG2 = PRO + ["hex.set 4, gps_cvh, %d" % plib.H,
                   "gpspr.frag_derive c_s, c_sblk, 6",
                   "hex.cmp 2, gps_sy1, ecl_ctake, pc1, pc1, psplit", "pc1:",
                   "hex.cmp 2, gps_sy2, c_fstart, psplit, pc2, pc2", "pc2:",
                   "gpspr.steps_splice_c ecl_ctake, ecl_full_lo, gps_sy1, 1, c_gnrow, ecl_cmidx, c_cbufa, c_cbufd, ecl_ccy",
                   "gpspr.steps_splice_f c_fstart, %d, gps_sy2, ecl_full_hi, 1, c_gnrow, ecl_cmidx, c_fbufa, c_fbufd, ecl_ccy" % plib.H,
                   ";pdone", "psplit:",
                   PREG % ("ecl_full_lo, gps_sy1", plib.H),
                   PREG % ("gps_sy2, ecl_full_hi", plib.H),
                   "pdone:", "stl.output_char 0xFF"]
variants = [("BASE", [], ()),
            ("SR", ["stream.sprite_runs c_sblk, c_sy0b, c_slr, %d, 6" % plib.H], ()),
            ("REG2", TODAY_REG2, ()),
            ("DER", ["hex.set 4, gps_cvh, %d" % plib.H, "gpspr.frag_derive c_s, c_sblk, 6"], (plib.PROP_FJ,)),
            ("DERRUNS", ["hex.set 4, gps_cvh, %d" % plib.H, "gpspr.frag_derive c_s, c_sblk, 6", "gpspr.runs"],
             (plib.PROP_FJ,)),
            ("PREG2", PROP_REG2, (plib.PROP_FJ,)),
            ("DER2", ["hex.set 4, gps_cvh, %d" % plib.H, "gpspr.frag_derive2 c_s, c_sblk"], (plib.PROP_FJ,)),
            ("DERRUNS2", ["hex.set 4, gps_cvh, %d" % plib.H, "gpspr.frag_derive2 c_s, c_sblk", "gpspr.runs2"],
             (plib.PROP_FJ,)),
            ("SR_NIB", ["hex.set 4, gps_cvh, %d" % plib.H, "gpspr.blk_addr gps_ptr, c_sblk, sprbank"], (plib.PROP_FJ,)),
            ("SR_SHL", ["hex.zero w/4, gps_sidx", "hex.mov 4, gps_sidx, c_sblk", "rep(6, k) hex.shl_bit w/4, gps_sidx",
                        "hex.set w/4, gps_sbase, sprbank", "frame.ptr_index gps_ptr, gps_sbase, gps_sidx"], (plib.PROP_FJ,))]
res = {}
for name, leaf, xfj in variants:
    t0 = time.time()
    ops = [plib.assemble_run(plib.program(fr, leaf, p), "%s_%d" % (name, p), extra_fj=xfj)[0] for p in (1, 2)]
    res[name] = ops[1] - ops[0]
    print("  %-8s per column %8.0f  (%.0fs)" % (name, (res[name] - res.get("BASE", res[name])) / n,
                                             time.time() - t0), flush=True)
runs = sum(len(c["runs"]) for c in fr.cases)
fast = sum(1 for c in fr.cases if c["y_base"] >= 0 and c["y_base"] + c["runs"][-1][0] <= plib.H)
print("frame %s: %d columns, %.1f runs/col, %d fully on screen (fast path)" % (key, n, runs / n, fast))
