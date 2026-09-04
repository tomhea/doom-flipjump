"""P3-1: drive fixed_mul_lo's rows off `b` IN PLACE, and delete wide_b entirely.

Today the macro copies BOTH operands into n+f-nibble scratch vectors and sign-extends them:

    .mov n, wide_a, a      .sign_extend n+f, n, wide_a
    .mov n, wide_b, b      .sign_extend n+f, n, wide_b      <- 125,255 + ~0 ops/frame
    .zero n+f, res
    rep(n+f, j) row n+f, j, res, wide_a, wide_b

But `wide_b` exists only to be READ one nibble at a time as the row driver, and add_mul never
writes its b operand. So the rows can read `b` directly, and the f sign-extension rows -- which
are the only thing the copy adds -- become f rows driven by a constant 0xF nibble, run only when
b is negative:

    rep(n, j) rowa n+f, j, res, wide_a, b + j*dw
    .sign n, b, bneg, bpos
  bneg:
    rep(f, k) .add_mul f-k, res+(n+k)*dw, wide_a, fnib     // fnib is a macro-local 0xF
  bpos:
    .mov n, dst, res + f*dw

`hex.sign` tests the same nibble with the same predicate `hex.sign_extend` does, so the polarity
is identical by construction.

THE TEST THAT MATTERS is the product itself, over every sign combination and the extremes -- this
is a multiply, and the campaign already has one truncation that passed casual inspection and
painted thousands of wrong pixels. Every case below is also checked against PYTHON's own
(a*b)>>16, so the two fj forms cannot be jointly wrong.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, price                                       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXED = ROOT / "src/fj/fixed_point.fj"
FILES = [FIXED]
NL = chr(10)


def prelude(fill):
    body = [
        "ns mb {",
        "    ns inner {",
        "        def rowa m, j, res, wa, wbj @ skip {",
        "            hex.if0 1, wbj, skip",
        "            hex.add_mul m-j, res + j*dw, wa, wbj",
        "          skip:",
        "        }",
        "    }",
        "    def go n, f, dst, a, b @ wide_a, res, fnib, bneg, bpos, end {",
        "        hex.mov n, wide_a, a",
        "        hex.sign_extend n+f, n, wide_a",
        "        hex.zero n+f, res",
        "        rep(n, j) .inner.rowa n+f, j, res, wide_a, b + j*dw",
        "        hex.sign n, b, bneg, bpos",
        "      bneg:",
        "        rep(f, k) hex.add_mul f-k, res+(n+k)*dw, wide_a, fnib",
        "      bpos:",
        "        hex.mov n, dst, res + f*dw",
        "        ;end",
    ]
    if fill:
        body += ["        rep(%d, i) stl.fj 0, 0" % fill]
    body += [
        "      wide_a: hex.vec n+f",
        "      res: hex.vec n+f",
        "      fnib: hex.hex 0xf",
        "      end:",
        "    }",
        "}",
    ]
    return NL.join(body)


def sx(v):
    return v - (1 << 32) if v & 0x80000000 else v


CASES = [
    ("both positive", 0x0004F85E, 0x00012345),
    ("a negative", 0xFFFB07A2, 0x00012345),
    ("b NEGATIVE", 0x0004F85E, 0xFFFEDCBB),
    ("both negative", 0xFFFB07A2, 0xFFFEDCBB),
    ("b = -1", 0x0004F85E, 0xFFFFFFFF),
    ("b = 0", 0x0004F85E, 0x00000000),
    ("a = 0", 0x00000000, 0xFFFEDCBB),
    ("b = most negative", 0x0004F85E, 0x80000000),
    ("a = most negative", 0x80000000, 0x00012345),
    ("both most negative", 0x80000000, 0x80000000),
    ("b sparse high nibble", 0x0004F85E, 0x90000000),
    ("b = 0x0000FFFF", 0x12345678, 0x0000FFFF),
    ("a dense, b dense", 0xDEADBEEF, 0xCAFEBABE),
    ("b = +1.0 (0x10000)", 0x0004F85E, 0x00010000),
]

print("=== P3-1  fixed_mul_lo: drive the rows off b, delete wide_b ===")
print("")
print("%-24s %10s %10s %10s   %s" % ("case", "python", "current", "new", ""))
bad = 0
for name, av, bv in CASES:
    data = ["av: hex.vec 8, 0x%08X" % av, "bv: hex.vec 8, 0x%08X" % bv,
            "d1: hex.vec 8", "d2: hex.vec 8"]
    rows = compare([("cur", ["hex.fixed_mul_lo 8, 4, d1, av, bv"]),
                    ("new", ["mb.go 8, 4, d2, av, bv"])],
                   data=data, prelude=prelude(0), files=FILES, quiet=True,
                   printer=["hex.print_as_digit 8, d1, 1", "hex.print_as_digit 8, d2, 1"])
    # compare() builds ONE PROGRAM PER VARIANT, so each variant only writes its own dst --
    # read each row's own output, not one row's copy of both.
    cur, new = rows[0][3][0:8], rows[1][3][8:16]
    want = "%08X" % (((sx(av) * sx(bv)) >> 16) & 0xFFFFFFFF)
    ok = cur.upper() == want and new.upper() == want
    bad += 0 if ok else 1
    print("%-24s %10s %10s %10s   %s" % (name, want, cur, new,
                                         "ok" if ok else "!! MISMATCH"))
print("")
print("value check: %s"
      % ("all %d cases match python AND each other" % len(CASES) if not bad
         else "!! %d CASES WRONG -- do not ship" % bad))
print("")
print("COST and the freeze filler (n=8, f=4, the shape every whole-macro call uses)")
data = ["av: hex.vec 8, 0x0004F85E", "bv: hex.vec 8, 0x00012345", "d1: hex.vec 8", "d2: hex.vec 8"]
ex_c, sp_c = price(["hex.fixed_mul_lo 8, 4, d1, av, bv"], data, prelude(0), files=FILES)
ex_n, sp_n = price(["mb.go 8, 4, d2, av, bv"], data, prelude(0), files=FILES)
fill = sp_c - sp_n
ex_f, sp_f = price(["mb.go 8, 4, d2, av, bv"], data, prelude(fill), files=FILES)
print("  current : %8.1f executed   %6d space" % (ex_c, sp_c))
print("  new     : %8.1f executed   %6d space   -> filler %d" % (ex_n, sp_n, fill))
print("  new+fill: %8.1f executed   %6d space   %s"
      % (ex_f, sp_f, "SIZE-IDENTICAL" if sp_f == sp_c else "!! OFF by %d" % (sp_f - sp_c)))
print("  delta   : %+8.1f executed per call" % (ex_f - ex_c))
print("")
print("Negative b costs more (it runs the f sign rows), so also price it:")
data2 = ["av: hex.vec 8, 0x0004F85E", "bv: hex.vec 8, 0xFFFEDCBB", "d1: hex.vec 8", "d2: hex.vec 8"]
compare([("current", ["hex.fixed_mul_lo 8, 4, d1, av, bv"]),
         ("new", ["mb.go 8, 4, d2, av, bv"])], data=data2, prelude=prelude(fill), files=FILES)
