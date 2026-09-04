"""P1-3: the shift-adjacency rewrite -- `mov N, t, src; shr_hex N, K, t` is a `mov, t, src + K*dw`.

hex.shr_hex's stl body is

    .zero times, dst
    rep(n-times, i) .xor_zero dst + i*dw, dst + (i+times)*dw

so result nibble i IS source nibble i+times, and nibbles n-times..n-1 end at zero (xor_zero
clears its source). When the shifted register is afterwards read at width r, the whole
copy-then-shift is therefore byte-identically `hex.mov r, dst, src + times*dw` -- no scratch
vector, no shift, and the copy shrinks from N nibbles to r.

TWO LIVE SITES, both verified by grep to read the shifted register at width 2 only:

  frame.lines_sky_base    va8 = viewangle; va8 >>= 6 nibbles; skb = va8[:2]
                          -> skb = viewangle[6:8]. va8 (a hex.vec 8 scratch) disappears entirely.
                          Atlas, median frame: the mov is 46,080 ops and the shift 24,320.
  frame.thing_record_body trb_u = trb_frac_u; trb_u >>= 4 nibbles; then cmp 2 / mov 2 only
                          -> trb_u = trb_frac_u[4:6]. Atlas: 12,512 + 5,585.

trb_frac_u itself is untouched -- it stays the 8-nibble mod-2^32 DDA accumulator it was.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare                                              # noqa: E402

PRELUDE = """
ns sky {
    def old skb @ va8, end < vang {
        hex.mov 8, va8, vang
        hex.shr_hex 8, 6, va8
        hex.mov 2, skb, va8
        ;end
      va8: hex.vec 8
      end:
    }
    def new skb < vang {
        hex.mov 2, skb, vang + 6*dw
    }
}
ns trb {
    def old u, frac {
        hex.mov 8, u, frac
        hex.shr_hex 8, 4, u
    }
    def new u, frac {
        hex.mov 2, u, frac + 4*dw
    }
}
"""

VALUES = [0x00000000, 0x12345678, 0xFFFFFFFF, 0x87654321, 0xA0000000, 0x0000FFFF,
          0x00FF0000, 0xDEADBEEF]

print("=== P1-3  shift adjacency: mov N + shr_hex N,K  ->  mov r, dst, src + K*dw ===")
print("")
print("VALUE CHECK -- the shifted register is read at width 2, so width 2 is what must match.")
print("%-14s %10s %10s %10s %10s" % ("viewangle", "sky old", "sky new", "trb old", "trb new"))
bad = 0
for v in VALUES:
    data = ["vang: hex.vec 8, 0x%08X" % v, "frac: hex.vec 8, 0x%08X" % v,
            "skb: hex.vec 8", "u: hex.vec 8"]
    rs = compare([("old", ["sky.old skb", "trb.old u, frac"]),
                  ("new", ["sky.new skb", "trb.new u, frac"])],
                 data=data, prelude=PRELUDE, quiet=True,
                 printer=["hex.print_as_digit 2, skb, 1", "hex.print_as_digit 2, u, 1"])
    o, n = rs[0][3], rs[1][3]
    ok = o == n
    bad += 0 if ok else 1
    print("0x%08X     %10s %10s %10s %10s  %s"
          % (v, o[:2], n[:2], o[2:4], n[2:4], "ok" if ok else "!! DIFFER"))
print("")
print("value check: %s" % ("all %d values identical" % len(VALUES) if not bad
                           else "!! %d DIFFER -- do not ship" % bad))
print("")
for tag, body_old, body_new in (("lines_sky_base", ["sky.old skb"], ["sky.new skb"]),
                                ("thing_record_body trb_u", ["trb.old u, frac"], ["trb.new u, frac"])):
    print("  %s" % tag)
    compare([("old", body_old), ("new", body_new)],
            data=["vang: hex.vec 8, 0x12345678", "frac: hex.vec 8, 0x12345678",
                  "skb: hex.vec 8", "u: hex.vec 8"], prelude=PRELUDE)
    print("")
print("NOTE: sky.old also declares `va8: hex.vec 8`, which the space figure above includes only")
print("if it falls between the mstart/mend labels -- it does not (it is inside the macro's own")
print("tail). Deleting it removes a further 8 ops of DATA; the freeze filler must cover that too.")
