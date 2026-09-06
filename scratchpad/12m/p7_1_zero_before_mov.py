"""P7-1: delete `hex.zero` calls that the very next `hex.mov` already performs.

hex.mov zeroes its destination before xoring the source in (projection.fj says so in a comment;
this script PROVES it by moving into a pre-dirtied register and checking nothing survives). So a
`hex.zero n, X` immediately followed by a mov that covers X[0..n) is dead work, and a mov that
covers only part of it is still enough when the uncovered nibbles are never written by anybody.

THREE SITES, each with the whole-register write history grepped:

  frame.lines_pclm_index2   `hex.zero w/4, tmp` then `hex.mov w/4, tmp, idx` -- same register,
                            same width, no offset. Unconditionally dead.
  proj.scale_recip_div      `hex.zero 14, srd_num_wide` then `hex.mov 8, srd_num_wide + 4*dw`.
                            Nibbles 0..3 and 12..13 are written by NOTHING in the tree (grep:
                            srd_num_wide appears only in its `hex.vec 14` declaration and these
                            two lines), so they hold their zero-init forever.
  proj.scale_recip_div      `hex.zero 14, srd_recip_wide` then `hex.mov 6, srd_recip_wide`.
                            Same argument for nibbles 6..13.

THE TEST THAT MATTERS is the second call, not the first: in the real program these registers
arrive holding the PREVIOUS call's value, which is exactly what the deleted zero used to clear.
So every case below runs the sequence twice -- a dense value, then a sparse one -- and compares
the second result.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare                                              # noqa: E402

PRELUDE = """
ns pclm {
    def old dst, idx {
        hex.zero 8, dst
        hex.mov 8, dst, idx
    }
    def new dst, idx {
        hex.mov 8, dst, idx
    }
}
ns numw {
    def old dst, num {
        hex.zero 14, dst
        hex.mov 8, dst + 4*dw, num
    }
    def new dst, num {
        hex.mov 8, dst + 4*dw, num
    }
}
ns recw {
    def old dst, r {
        hex.zero 14, dst
        hex.mov 6, dst, r
    }
    def new dst, r {
        hex.mov 6, dst, r
    }
}
"""

DATA = ["va: hex.vec 8, 0xFEDCBA98", "vb: hex.vec 8, 0x00000007",
        "ra: hex.vec 6, 0xFFFFFF", "rb: hex.vec 6, 0x000003",
        "t8: hex.vec 8", "n14: hex.vec 14", "r14: hex.vec 14"]

SEQ = {
    # dense first, sparse second -- the second result is the one the deleted zero used to protect
    "lines_pclm_index2 tmp": (["pclm.old t8, va", "pclm.old t8, vb"],
                              ["pclm.new t8, va", "pclm.new t8, vb"],
                              ["hex.print_as_digit 8, t8, 1"]),
    "scale_recip_div srd_num_wide": (["numw.old n14, va", "numw.old n14, vb"],
                                     ["numw.new n14, va", "numw.new n14, vb"],
                                     ["hex.print_as_digit 14, n14, 1"]),
    "scale_recip_div srd_recip_wide": (["recw.old r14, ra", "recw.old r14, rb"],
                                       ["recw.new r14, ra", "recw.new r14, rb"],
                                       ["hex.print_as_digit 14, r14, 1"]),
}

print("=== P7-1  delete the hex.zero that the next hex.mov already does ===")
print("")
print("VALUE CHECK -- second call after a DENSE first call, so a missing zero would show.")
bad = 0
for name, (old, new, pr) in SEQ.items():
    rows = compare([("old", old), ("new", new)], data=DATA, prelude=PRELUDE, quiet=True, printer=pr)
    o, n = rows[0][3], rows[1][3]
    ok = o == n
    bad += 0 if ok else 1
    print("  %-32s old=%-16s new=%-16s %s" % (name, o, n, "ok" if ok else "!! DIFFER"))
print("")
print("value check: %s" % ("all %d sequences identical" % len(SEQ) if not bad
                           else "!! %d DIFFER -- do not ship" % bad))
print("")
print("COST (one call of each, not the doubled sequence)")
for name, one_old, one_new in (("lines_pclm_index2 tmp", ["pclm.old t8, va"], ["pclm.new t8, va"]),
                               ("srd_num_wide", ["numw.old n14, va"], ["numw.new n14, va"]),
                               ("srd_recip_wide", ["recw.old r14, ra"], ["recw.new r14, ra"])):
    print("  %s" % name)
    compare([("old", one_old), ("new", one_new)], data=DATA, prelude=PRELUDE)
    print("")
