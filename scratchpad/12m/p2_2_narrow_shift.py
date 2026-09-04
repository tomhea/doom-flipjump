"""P2-2: frame.ptr_index's shift stage at a width the index actually needs.

frame.ptr_index (P2-1) is

    hex.mov w/4, dst, index          // must stay 8: it clears dst for the 8-nibble add
    hex.shl_hex w/4, dst             //  <<4
    rep(8-#w, i) hex.shr_bit w/4, dst   //  >>3   -- net <<5, i.e. index * 32
    hex.shl_hex w/4, dst             //  <<4
    frame.add8_chain dst, ptr        // must stay 8: ptr is a full address

Only the SHIFT STAGE depends on how big the index is. The widest intermediate is index*16 (after
the first shl_hex) and the final value is index*32, so a shift stage of width sw is exact iff

    index * 16 < 16^sw   and   index * 32 < 16^sw    ->    index < 16^sw / 32

  sw = 4  ->  index < 2,048     covers every COLUMN index (x, x1, trb_col_x, tsf_col_x < 160)
  sw = 5  ->  index < 32,768
  sw = 6  ->  index < 524,288   covers sh_idx = (cls<<8)|h < 65,536

This measures each width and checks the pointer is identical, including at the exact boundary
value where the bound is tight -- and one value PAST the bound, which must DIFFER (the negative
control: a bound that cannot be violated is not a bound).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare                                              # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]
NL = chr(10)


def chain_macros():
    src = (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8").split(NL)

    def grab(name):
        start = next(i for i, l in enumerate(src) if l.strip().startswith("def " + name + " "))
        depth, out = 0, []
        for i in range(start, len(src)):
            out.append(src[i])
            depth += src[i].count("{") - src[i].count("}")
            if depth == 0 and i > start:
                break
        return NL.join(out)

    return "ns ch {" + NL + grab("dance_boundary") + NL + grab("add8_chain") + NL + "}"


VARIANT = """
ns pi%(sw)s {
    def go dst, ptr, index {
        hex.mov w/4, dst, index
        hex.shl_hex %(sw)s, dst
        rep(8-#w, i) hex.shr_bit %(sw)s, dst
        hex.shl_hex %(sw)s, dst
        ch.add8_chain dst, ptr
    }
}
"""

PRELUDE = chain_macros() + "".join(VARIANT % {"sw": sw} for sw in ("8", "6", "5", "4"))

CASES = [("column index 159", 159), ("column index 2047 (sw=4 bound)", 2047),
         ("2048 -- PAST the sw=4 bound", 2048), ("sh_idx shape 0x1F64", 0x1F64),
         ("32767 (sw=5 bound)", 32767), ("65535", 65535)]

print("=== P2-2  the shift stage at the width the index needs ===")
print("")
print("%-32s %10s %10s %10s %10s" % ("index", "sw=8", "sw=6", "sw=5", "sw=4"))
for name, v in CASES:
    data = ["base: hex.vec 8, 0x00A1B2C0", "idx: hex.vec 8, 0x%08X" % v, "d: hex.vec 8"]
    rows = compare([(sw, ["pi%s.go d, base, idx" % sw]) for sw in ("8", "6", "5", "4")],
                   data=data, prelude=PRELUDE, files=FILES, quiet=True,
                   printer=["hex.print_as_digit 8, d, 1"])
    g = [r[3] for r in rows]
    marks = ["ok" if x == g[0] else "DIFFER" for x in g]
    print("%-32s %10s %10s %10s %10s   %s"
          % ("%d (0x%X)" % (v, v), g[0], g[1], g[2], g[3], " ".join(marks[1:])))
print("")
print("The 2048 row is the NEGATIVE CONTROL: sw=4 must DIFFER there, or the bound is not a bound.")
print("")
print("COST (index 159, a column)")
data = ["base: hex.vec 8, 0x00A1B2C0", "idx: hex.vec 8, 159", "d: hex.vec 8"]
compare([("sw=8 (shipped)", ["pi8.go d, base, idx"]),
         ("sw=6", ["pi6.go d, base, idx"]),
         ("sw=5", ["pi5.go d, base, idx"]),
         ("sw=4", ["pi4.go d, base, idx"])], data=data, prelude=PRELUDE, files=FILES)
