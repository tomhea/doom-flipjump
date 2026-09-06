"""P1-1: frame.clip_rows at width 5 instead of 8.

THE BOUND. `top` and `bottom` reach clip_rows straight out of `hex.sign_extend 8, 4` (the
arithmetic >>16 in proj.column_params_dda / step_rows / lines_projcall), so both are signed
16-bit values sitting in 8 nibbles whose nibbles 4..7 are a copy of the sign. Reading only
nibbles 0..4 therefore sees the SAME SIGNED VALUE, and `fstart = bottom + 1` stays inside
[-32767, 32768], which still fits 5 nibbles signed -- so `hex.sign 5` and `hex.sign 8` agree on
it. That last step is why this is width 5 and not width 4: at width 4, bottom = 32767 makes
bottom+1 read as negative and the macro zeroes fstart instead of keeping 0x8000. (Both happen to
leave the same low two nibbles, and every reader of p2_cexcl/p2_fstart reads exactly two --
verified by grep: hex.cmp 2 / hex.mov 2 in the ditto test, in lines_step_load's ctake and in
emit_col_lines' ctake. But "the difference is invisible" is a budget argument; "the value is
identical" is a stop. Width 5 is the stop.)

This script measures the change instead of asserting it: exact executed ops per call and exact
emitted space for both variants, plus the outputs of both over a set of (top, bottom) pairs that
includes every edge the proof turns on.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, price                                        # noqa: E402

W8 = """
ns t8 {
    def clip_rows cexcl, fstart, top, bottom, cVH \\
            @ cexcl_clamp, cexcl_done, fstart_neg, fstart_done {
        hex.mov 8, cexcl, top
        hex.scmp 8, top, cVH, cexcl_done, cexcl_clamp, cexcl_clamp
      cexcl_clamp:
        hex.mov 8, cexcl, cVH
      cexcl_done:
        hex.mov 8, fstart, bottom
        hex.inc 8, fstart
        hex.sign 8, fstart, fstart_neg, fstart_done
      fstart_neg:
        hex.zero 8, fstart
      fstart_done:
    }
}
"""

W5 = """
ns t5 {
    def clip_rows cexcl, fstart, top, bottom, cVH \\
            @ cexcl_clamp, cexcl_done, fstart_neg, fstart_done {
        hex.mov 5, cexcl, top
        hex.scmp 5, top, cVH, cexcl_done, cexcl_clamp, cexcl_clamp
      cexcl_clamp:
        hex.mov 5, cexcl, cVH
      cexcl_done:
        hex.mov 5, fstart, bottom
        hex.inc 5, fstart
        hex.sign 5, fstart, fstart_neg, fstart_done
      fstart_neg:
        hex.zero 5, fstart
      fstart_done:
    }
}
"""

PRELUDE = W8 + W5


def data_for(top, bottom, viewh=100):
    return ["ctop: hex.vec 8, 0x%08X" % (top & 0xFFFFFFFF),
            "cbot: hex.vec 8, 0x%08X" % (bottom & 0xFFFFFFFF),
            "cvh: hex.vec 8, %d" % viewh,
            "oc: hex.vec 8", "of: hex.vec 8"]


# rows are signed 16-bit sign-extended into 8 nibbles -- the edges the proof turns on
CASES = [("mid, top under viewh", 40, 60),
         ("top over viewh (clamps)", 250, 300),
         ("top negative", -80, 20),
         ("bottom negative (fstart 0)", -300, -50),
         ("bottom = -1 (inc carries out)", 10, -1),
         ("bottom = 32767 (inc to 0x8000)", 10, 32767),
         ("bottom = -32768 (most negative)", 10, -32768),
         ("top = 32767", 32767, 5),
         ("top = -32768", -32768, 5)]

print("=== P1-1  frame.clip_rows: width 8 -> 5 ===")
print("")
print("VALUE CHECK -- both variants run on the real interpreter; the printed pair is")
print("(cexcl, fstart) as the readers see them (width 2) and then in full (width 5).")
print("")
print("%-32s %10s %10s %10s %10s %s" % ("case", "w8 cexcl", "w8 fstart", "w5 cexcl", "w5 fstart", ""))
bad = 0
for name, top, bottom in CASES:
    d = data_for(top, bottom)
    rows = compare([("w8", ["t8.clip_rows oc, of, ctop, cbot, cvh"]),
                    ("w5", ["t5.clip_rows oc, of, ctop, cbot, cvh"])],
                   data=d, prelude=PRELUDE, quiet=True,
                   printer=["hex.print_as_digit 2, oc, 1", "hex.print_as_digit 2, of, 1",
                            "hex.print_as_digit 5, oc, 1", "hex.print_as_digit 5, of, 1"])
    g8, g5 = rows[0][3], rows[1][3]
    same2 = g8[:4] == g5[:4]
    bad += 0 if same2 else 1
    print("%-32s %10s %10s %10s %10s %s"
          % (name, g8[0:2], g8[2:4], g5[0:2], g5[2:4],
             "ok" if same2 else "!! READERS SEE A DIFFERENT VALUE"))
    if g8[4:] != g5[4:]:
        print("%-32s   full w5 view differs: w8=%s w5=%s (only matters if a reader widens)"
              % ("", g8[4:], g5[4:]))
print("")
print("value check: %s" % ("all %d cases identical to the readers" % len(CASES) if not bad
                           else "!! %d CASES DIFFER -- do not ship" % bad))
print("")
print("COST -- executed ops per call (averaged over the cases' two control-flow paths) and space")
print("")
for name, top, bottom in (CASES[0], CASES[1], CASES[3]):
    print("  case: %s" % name)
    compare([("w8", ["t8.clip_rows oc, of, ctop, cbot, cvh"]),
             ("w5", ["t5.clip_rows oc, of, ctop, cbot, cvh"])],
            data=data_for(top, bottom), prelude=PRELUDE)
    print("")
