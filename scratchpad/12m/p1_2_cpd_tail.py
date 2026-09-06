"""P1-2: the tail of proj.column_params_dda at width 5, matching its only consumer.

P1-1 narrowed frame.clip_rows to width 5. clip_rows is the ONLY reader of the `top` and `bottom`
globals (grep: they are written by column_params_dda through lines_projcall, and read at
frame_render's clip_rows call; lines_projstub is the `noproj` ablation and is not emitted in the
shipped tier). So the PRODUCER can stop maintaining nibbles 5..7 at all.

WHY IT IS EXACT. `hex.shr_hex 8, 4, top` moves nibbles 4..7 down and ZEROES 4..7 (its body is
`.zero times, dst` then `rep(n-times,i) xor_zero dst+i, dst+(i+times)`, and xor_zero clears its
source). So after the shift, nibbles 4..7 are 0. `hex.sign_extend 5, 4` then writes nibble 4 --
the sign -- and leaves 5..7 at 0. A width-5 read sees exactly the value a width-8 sign extension
would have produced; a width-8 read would NOT, which is why `hex.sign 8, top` must become
`hex.sign 5, top` in the same change: with only 5 nibbles maintained, nibble 7 is permanently 0
and an 8-wide sign test would call every negative top positive. That is a correctness coupling,
not an optimisation -- the audit's trap 3.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare                                              # noqa: E402

TAIL = """
ns t%(tag)s {
    // the tail of column_params_dda, from the arithmetic >>16 onward
    def cpd_tail top, bottom, viewh1c @ tneg, tok, bok, bhi, end {
        hex.shr_hex 8, 4, top
        hex.sign_extend %(w)s, 4, top
        hex.shr_hex 8, 4, bottom
        hex.sign_extend %(w)s, 4, bottom
        hex.sign %(w)s, top, tneg, tok
      tneg:
        hex.zero %(w)s, top
      tok:
        hex.scmp 4, bottom, viewh1c, bok, bok, bhi
      bhi:
        hex.mov %(w)s, bottom, viewh1c
      bok:
        ;end
      end:
    }
}
"""

PRELUDE = (TAIL % {"tag": "8", "w": "8"}) + (TAIL % {"tag": "5", "w": "5"})


def data_for(topv, botv, viewh1=99):
    return ["ctop: hex.vec 8, 0x%08X" % (topv & 0xFFFFFFFF),
            "cbot: hex.vec 8, 0x%08X" % (botv & 0xFFFFFFFF),
            "cv1: hex.vec 8, %d" % viewh1,
            "wt: hex.vec 8", "wb: hex.vec 8"]


BODY8 = ["hex.mov 8, wt, ctop", "hex.mov 8, wb, cbot", "t8.cpd_tail wt, wb, cv1"]
BODY5 = ["hex.mov 8, wt, ctop", "hex.mov 8, wb, cbot", "t5.cpd_tail wt, wb, cv1"]

# pre-shift 32-bit fixed-point values: the >>16 makes them the signed rows clip_rows will read
CASES = [("mid rows (top 40, bottom 60)", 40 << 16, 60 << 16),
         ("top negative", (-80 << 16) & 0xFFFFFFFF, 20 << 16),
         ("bottom over viewh1 (clamps)", 10 << 16, 300 << 16),
         ("both negative", (-300 << 16) & 0xFFFFFFFF, (-50 << 16) & 0xFFFFFFFF),
         ("bottom = -1 row", 10 << 16, 0xFFFF8000),
         ("top row = 32767", 0x7FFF0000, 5 << 16),
         ("top row = -32768", 0x80000000, 5 << 16),
         ("fractional bits set", 0x0028C000, 0x003CF000)]

print("=== P1-2  proj.column_params_dda tail: width 8 -> 5 ===")
print("")
print("VALUE CHECK -- clip_rows reads 5 nibbles, so that is what must match.")
print("%-32s %12s %12s %12s %12s" % ("case", "w8 top", "w8 bottom", "w5 top", "w5 bottom"))
bad = 0
for name, tv, bv in CASES:
    rows = compare([("w8", BODY8), ("w5", BODY5)], data=data_for(tv, bv), prelude=PRELUDE,
                   quiet=True,
                   printer=["hex.print_as_digit 5, wt, 1", "hex.print_as_digit 5, wb, 1"])
    g8, g5 = rows[0][3], rows[1][3]
    same = g8 == g5
    bad += 0 if same else 1
    print("%-32s %12s %12s %12s %12s  %s"
          % (name, g8[:5], g8[5:10], g5[:5], g5[5:10], "ok" if same else "!! DIFFER"))
print("")
print("value check: %s" % ("all %d cases identical at width 5" % len(CASES) if not bad
                           else "!! %d CASES DIFFER -- do not ship" % bad))
print("")
print("COST")
for name, tv, bv in (CASES[0], CASES[1], CASES[2]):
    print("  case: %s" % name)
    compare([("w8", BODY8), ("w5", BODY5)], data=data_for(tv, bv), prelude=PRELUDE)
    print("")
