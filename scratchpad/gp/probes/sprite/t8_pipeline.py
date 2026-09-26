"""Step 8: END-TO-END check of the proposal -- record (pass 1) -> slot read-back (pass 2) -> emit,
TODAY vs PROPOSED, on every column of an oracle frame, in ONE fj program each:

  HARN      the harness alone: the per-case record setup, the slot seed, the plain column
  PLAIN     the plain column only (no record setup, no seed) -- the column as if no sprite
  TODAY     transplanted frame.thing_record_body column loop -> frame.lines_spr_load ->
            stream.emit_col_lines (the loaded p2_* registers)
  PROP      gpspr.rec_thing (once per thing) + gpspr.rec_cols -> gpspr.load ->
            gpspr.emit_col (the loaded slot id and block)
  PROP2     PROP with the v2 addressing: gpspr.rec_cols2 -> gpspr.load -> gpspr.emit_col2

A sprite column's END-TO-END price is (variant - HARN) / columns: record + load + the sprite's
share of the emission. (The ditto ladder is priced separately by t6_ladder.py.)
CHECKS: TODAY == PLAIN with the oracle's fragment pasted (the harness wires the real macros
right), and PROP, PROP2 == TODAY pixel for pixel on every column.

    python t8_pipeline.py [scen:vp]
    python t8_pipeline.py --negative [scen:vp]   # R9: a one-row shift in the RECORD half
                                                 # (rec_thing's bias) must make PROP/PROP2 FAIL
"""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402
import t5_recload as t5                                                      # noqa: E402

args = [a for a in sys.argv[1:] if not a.startswith("--")]
negative = "--negative" in sys.argv
key = tuple(args[0].split(":")) if args else ("heavy", "gate664")
fr = plib.Frame(plib.by_frame(plib.load_cases())[key])
n = len(fr.cases)
H = plib.H
LOAD_T = ("frame.lines_spr_load p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
          "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb")
EMIT_T = plib.TODAY_EMIT.replace("c_sprfl, c_ssy1, c_ssy2, c_sy0b, c_sblk, c_slr, c_ssy1b, c_ssy2b, "
                                 "c_sy0bb, c_sblkb, c_slrb",
                                 "p2_sprfl, p2_ssy1, p2_ssy2, p2_sy0b, p2_sblk, p2_slr, p2_ssy1b, "
                                 "p2_ssy2b, p2_sy0bb, p2_sblkb, p2_slrb")
assert EMIT_T != plib.TODAY_EMIT
EMIT_P = plib.PROP_EMIT.replace("c_sprfl, c_s, c_sblk", "p2_sprfl, p2_s, p2_sblk")
assert EMIT_P != plib.PROP_EMIT
EMIT_P2 = plib.PROP2_EMIT.replace("c_sprfl, c_s, c_sblk", "p2_sprfl, p2_s, p2_sblk")
assert EMIT_P2 != plib.PROP2_EMIT

# LAYOUT: the transplanted record loop carries the renderer's unreachable layout freeze
# `rep(703, i) stl.fj 0, 0`. The renderer has ONE copy of it (a shared leaf); this harness expands
# the record once per CASE, so TODAY's program would carry ~100 copies (~70K dead ops) and every
# later label -- the whole emit leaf -- would sit at different addresses than in PROP's program.
# An op's price follows the popcount of the addresses it flips, so that is a layout confound, not
# a cost of the logic: strip it (`--keepfill` keeps it, to show how much layout alone moves).
FILL = "rep(703, i) stl.fj 0, 0"
TODAY_REC = t5.TODAY_REC
if "--keepfill" not in sys.argv:
    assert TODAY_REC.count(FILL) == 1
    TODAY_REC = TODAY_REC.replace(FILL, "")

prop_fj = plib.PROP_FJ
if negative:
    src = prop_fj.read_text(encoding="utf-8")
    mut = src.replace("hex.add_constant 8, gps_yb8, 32768", "hex.add_constant 8, gps_yb8, 32767")
    assert mut != src
    prop_fj = Path(tempfile.mkdtemp()) / "gp_sprite_col_mut.fj"
    prop_fj.write_text(mut, encoding="utf-8")


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


def build(prop):
    pre = ["hex.set 2, gps_nslot, 0", "hex.set 2, gps_cur_s, 0"]
    # PASS 1: record every column (things in order; a new thing takes a new slot)
    for i in range(n):
        pre += rec_setup(i)
        if prop == "HARN":
            continue
        if prop:
            if i == 0 or fr.slot_of[i] != fr.slot_of[i - 1]:
                pre.append("gpspr.rec_thing")
            pre.append("gpspr.rec_cols 32, 6, 1, 1, 9" if prop == 1 else "gpspr.rec_cols2 32, 1, 1, 9")
        else:
            pre.append("frame.gp_today_rec 32, 6, 16, 1, 1, 9, %d" % H)
    return pre


def leaf(prop):
    # PASS 2 (per case, through the harness stub): seed the slot pointers at x, load, emit.
    # `hex.read_byte gp_armd, p2_spfp` is HARNESS, the same in every variant: both loaders arm
    # their first read narrow (frame.arm5), which is exact only when the PREVIOUS arm is in the
    # hot-data block too. In the renderer the pass-2 leaf's earlier loaders provide that; here the
    # previous case's emit last armed the sprite bank or stepcol (high cluster), and the first
    # version of this probe ended in ip<2w / runtime-memory-error on exactly that.
    head = ["hex.zero 8, gp_k", "hex.mov 2, gp_k, c_x", "frame.lines_spr_seed gp_k",
            "hex.read_byte gp_armd, p2_spfp"]
    if prop == "HARN":
        return head + [plib.TODAY_EMIT]
    return head + (["gpspr.load p2_sprfl, p2_s, p2_sblk, p2_sb, p2_sblkb", EMIT_P if prop == 1 else EMIT_P2]
                   if prop else [LOAD_T, EMIT_T])


plain_extra = {i: {"c_sprfl": 0} for i in range(n)}
variants = [("PLAIN", None), ("HARN", "HARN"), ("TODAY", False), ("PROP", 1), ("PROP2", 2)]
if negative:
    variants = [("TODAY", False), ("PROP", 1), ("PROP2", 2)]
outs, ops = {}, {}
for name, prop in variants:
    t0 = time.time()
    if name == "PLAIN":
        text = plib.program(fr, [plib.TODAY_EMIT], 1, per_case_extra=plain_extra)
    else:
        text = plib.program(fr, leaf(prop), 1, pre_loop=build(prop), extra_text=TODAY_REC,
                            hot_text="\n".join(t5.DECLS + ["gp_armd: hex.vec 2"]), prefilled_slots=False,
                            per_case_extra=plain_extra if prop == "HARN" else None)
    o, out = plib.assemble_run(text, name, extra_fj=(prop_fj,))
    outs[name], ops[name] = plib.decode(out), o
    print("  %-6s %9d ops  (%.0fs)" % (name, o, time.time() - t0), flush=True)

bad_tp = sum(1 for i in range(n) if outs["TODAY"][i] != outs["PROP"][i])
bad_tp2 = sum(1 for i in range(n) if outs["TODAY"][i] != outs["PROP2"][i])
if negative:
    print("NEGATIVE CONTROL %s: with rec_thing's bias off by one, the PROP pipeline differs from TODAY on "
          "%d/%d columns, PROP2 on %d/%d -> %s" % (key, bad_tp, n, bad_tp2, n,
          "control PASSES (the check can fail)" if bad_tp and bad_tp2 else "control FAILS (the check is blind)"))
    sys.exit(0)
bad_t = 0
for i in range(n):
    want = dict(outs["PLAIN"][i][1])
    want.update(fr.expected_sprite_rows(i))
    bad_t += outs["TODAY"][i] != (outs["PLAIN"][i][0], want)
per = {k: (ops[k] - ops["HARN"]) / n for k in ("TODAY", "PROP", "PROP2")}
print("frame %s: %d columns; TODAY pipeline == plain + oracle fragment on %d; PROP pipeline == TODAY on %d; "
      "PROP2 pipeline == TODAY on %d" % (key, n, n - bad_t, n - bad_tp, n - bad_tp2))
print("per sprite column over HARN (record + load + the sprite's share of the emit):  TODAY %.0f  PROP %.0f "
      "(%+.1f%%)  PROP2 %.0f (%+.1f%%)   [HARN - PLAIN = %.0f/col of setup + seed]" %
      (per["TODAY"], per["PROP"], 100.0 * (per["PROP"] / per["TODAY"] - 1), per["PROP2"],
       100.0 * (per["PROP2"] / per["TODAY"] - 1), (ops["HARN"] - ops["PLAIN"]) / n))
(Path(__file__).resolve().parent / ("t8_results_%s-%s%s.json" % (key + ("_keepfill" if "--keepfill" in sys.argv else "",)))).write_text(
    json.dumps(dict(frame="%s:%s" % key, n=n, keepfill="--keepfill" in sys.argv, ops=ops, per_column_over_harn=per, bad_today=bad_t,
                    bad_prop=bad_tp, bad_prop2=bad_tp2), indent=1), encoding="utf-8")
