"""P3-2: delete wide_a as well -- read `a` in place and supply its sign nibbles separately.

After P3-1, fixed_mul_lo still copies `a`:

    .mov n, wide_a, a            <- 135,090 ops/frame
    .sign_extend n+f, n, wide_a

wide_a is just [a's n nibbles, then f copies of a's sign]. A row reads wa[0..m-j), so it can read
`a` for the first min(n, m-j) nibbles and a small all-sign vector `asgn` for the rest.

THE TRAP, and why this is not a two-line change. hex.add_mul n, res, a, b is

    .mul.clear_carry ; .xor .mul.dst, b ; rep(n,i) .add_mul res+i*dw, a+i*dw ; .xor ... ; .clear_carry

so calling it TWICE would clear the carry between the halves and lose it. The split has to happen
INSIDE that bracket, over the 2-arg .add_mul, which carries no clear_carry of its own.

So this file checks TWO things, in order:
  1. THE IDENTITY CONFIGURATION -- rowb pointed at wide_a for BOTH halves must reproduce today's
     `row` exactly, in space and in executed ops. That isolates the hand-rolled bracket from the
     operand change. If this fails, nothing else matters.
  2. The real configuration, against Python's (a*b)>>16.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, price                                       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]
NL = chr(10)

BRACKET = [
    "    ns inner {",
    "        // today's row, verbatim, for the identity check",
    "        def row_ref m, j, res, wa, wbj @ skip {",
    "            hex.if0 1, wbj, skip",
    "            hex.add_mul m-j, res + j*dw, wa, wbj",
    "          skip:",
    "        }",
    "        // the split row: `lo` nibbles from `a`, the rest from `asgn`. The bracket is",
    "        // hand-rolled so the carry flows from the first rep into the second.",
    "        def rowb m, n, j, res, a, asgn, wbj @ skip < hex.mul.dst {",
    "            hex.if0 1, wbj, skip",
    "            hex.mul.clear_carry",
    "            hex.xor hex.mul.dst, wbj",
    "            rep((m-j < n ? m-j : n), i) hex.add_mul res + (j+i)*dw, a + i*dw",
    "            rep((m-j > n ? m-j-n : 0), i) hex.add_mul res + (j+n+i)*dw, asgn + i*dw",
    "            hex.xor hex.mul.dst, wbj",
    "            hex.mul.clear_carry",
    "          skip:",
    "        }",
    "    }",
]

PRELUDE = NL.join(["ns mc {"] + BRACKET + [
    "    def go n, f, dst, a, b @ res, asgn, fnib, aneg, apos, bneg, bpos, end {",
    "        hex.zero n+f, res",
    "        hex.zero f, asgn",
    "        hex.sign n, a, aneg, apos",
    "      aneg:",
    "        hex.not f, asgn",
    "      apos:",
    "        rep(n, j) .inner.rowb n+f, n, j, res, a, asgn, b + j*dw",
    "        hex.sign n, b, bneg, bpos",
    "      bneg:",
    "        rep(f, k) .inner.rowb n+f, n, n+k, res, a, asgn, fnib",
    "      bpos:",
    "        hex.mov n, dst, res + f*dw",
    "        ;end",
    "      res: hex.vec n+f",
    "      asgn: hex.vec f",
    "      fnib: hex.hex 0xf",
    "      end:",
    "    }",
    "}",
])


def sx(v):
    return v - (1 << 32) if v & 0x80000000 else v


print("=== P3-2  delete wide_a: read `a` in place, sign nibbles from `asgn` ===")
print("")
print("STEP 1 -- THE IDENTITY CONFIGURATION.")
print("rowb aimed at wide_a for BOTH halves must reproduce today's row exactly.")
D0 = ["wa: hex.vec 12, 0x0004F85E", "wb: hex.vec 12, 0x00012345", "rs: hex.vec 12"]
ok_id = True
for j in (0, 3, 7, 11):
    er, sr = price(["mc.inner.row_ref 12, %d, rs, wa, wb + %d*dw" % (j, j)], D0, PRELUDE, files=FILES)
    eb, sb = price(["mc.inner.rowb 12, 12, %d, rs, wa, wa, wb + %d*dw" % (j, j)], D0, PRELUDE, files=FILES)
    same = (sr == sb) and round(er, 1) == round(eb, 1)
    ok_id &= same
    print("  j=%-3d  row %5d space / %8.1f exec    rowb %5d / %8.1f   %s"
          % (j, sr, er, sb, eb, "identical" if same else "!! DIFFERS"))
print("")
print("  identity: %s" % ("PASS -- the hand-rolled bracket is exact"
                          if ok_id else "!! FAIL -- the bracket is not equivalent, stop here"))
print("")
if ok_id:
    print("STEP 2 -- the real configuration, against Python's (a*b)>>16")
    CASES = [("both positive", 0x0004F85E, 0x00012345), ("a NEGATIVE", 0xFFFB07A2, 0x00012345),
             ("b negative", 0x0004F85E, 0xFFFEDCBB), ("both negative", 0xFFFB07A2, 0xFFFEDCBB),
             ("a = -1", 0xFFFFFFFF, 0x00012345), ("a = most negative", 0x80000000, 0x00012345),
             ("b = most negative", 0x0004F85E, 0x80000000), ("a = 0", 0, 0xFFFEDCBB),
             ("b = 0", 0x0004F85E, 0), ("dense x dense", 0xDEADBEEF, 0xCAFEBABE),
             ("a = 0x0000FFFF", 0x0000FFFF, 0x00012345)]
    bad = 0
    print("  %-22s %10s %10s %10s" % ("case", "python", "current", "new"))
    for name, av, bv in CASES:
        data = ["av: hex.vec 8, 0x%08X" % av, "bv: hex.vec 8, 0x%08X" % bv,
                "d1: hex.vec 8", "d2: hex.vec 8"]
        rows = compare([("cur", ["hex.fixed_mul_lo 8, 4, d1, av, bv"]),
                        ("new", ["mc.go 8, 4, d2, av, bv"])],
                       data=data, prelude=PRELUDE, files=FILES, quiet=True,
                       printer=["hex.print_as_digit 8, d1, 1", "hex.print_as_digit 8, d2, 1"])
        cur, new = rows[0][3][0:8], rows[1][3][8:16]
        want = "%08X" % (((sx(av) * sx(bv)) >> 16) & 0xFFFFFFFF)
        good = cur.upper() == want and new.upper() == want
        bad += 0 if good else 1
        print("  %-22s %10s %10s %10s  %s" % (name, want, cur, new, "ok" if good else "!! WRONG"))
    print("")
    print("  value check: %s" % ("all %d match python and the shipped macro" % len(CASES)
                                 if not bad else "!! %d WRONG -- do not ship" % bad))
    if not bad:
        print("")
        print("COST (n=8, f=4)")
        data = ["av: hex.vec 8, 0x0004F85E", "bv: hex.vec 8, 0x00012345",
                "d1: hex.vec 8", "d2: hex.vec 8"]
        ec, sc = price(["hex.fixed_mul_lo 8, 4, d1, av, bv"], data, PRELUDE, files=FILES)
        en, sn = price(["mc.go 8, 4, d2, av, bv"], data, PRELUDE, files=FILES)
        print("  current : %8.1f executed  %6d space" % (ec, sc))
        print("  new     : %8.1f executed  %6d space   -> filler %d" % (en, sn, sc - sn - 1))
        print("  delta   : %+8.1f executed per call" % (en - ec))
