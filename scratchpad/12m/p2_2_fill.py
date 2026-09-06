"""P2-2, the freeze: find the filler that makes a narrow ptr_index the SAME SIZE as the wide one.

19 of the 22 call sites can narrow their shift stage, in three different widths, spread across a
dozen macros. Nineteen separate local fillers would be nineteen chances to be wrong -- so the
filler goes INSIDE the macro instead, behind a jump, and every expansion then compensates itself
automatically no matter where or how often it appears.

    def ptr_index_fill sw, fill, dst, ptr, index @ end {
        ... the narrow form ...
        ;end                              <- one executed op per call, ~760 per frame
        rep(fill, i) stl.fj 0, 0          <- unreachable
      end:
    }

This measures `fill` for each width by requiring the macro's emitted size to equal the width-8
form's exactly. Both forms are measured in the SAME micro program at the same addresses, so the
relative figure is sound even though micro.py's absolute space number is not (FINDINGS N).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import price                                                # noqa: E402

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


def variant(tag, sw, fill):
    body = ["ns %s {" % tag, "    def go dst, ptr, index @ end {",
            "        hex.mov w/4, dst, index",
            "        hex.shl_hex %d, dst" % sw,
            "        rep(8-#w, i) hex.shr_bit %d, dst" % sw,
            "        hex.shl_hex %d, dst" % sw,
            "        ch.add8_chain dst, ptr"]
    if fill:
        body += ["        ;end", "        rep(%d, i) stl.fj 0, 0" % fill]
    body += ["      end:", "    }", "}"]
    return NL.join(body)


DATA = ["base: hex.vec 8, 0x00A1B2C0", "idx: hex.vec 8, 159", "d: hex.vec 8"]
CH = chain_macros()

wide_ex, wide_sp = price(["w8.go d, base, idx"], DATA, CH + NL + variant("w8", 8, 0), files=FILES)
print("width 8 (shipped):  %8.1f executed/call   %6d ops of space" % (wide_ex, wide_sp))
print("")
print("%-6s %10s %10s %14s %10s" % ("sw", "fill", "space", "space delta", "exec/call"))
chosen = {}
for sw in (6, 5, 4):
    _e, bare = price(["v.go d, base, idx"], DATA, CH + NL + variant("v", sw, 0), files=FILES)
    # the jump costs one op of space; the filler makes up the rest
    fill = wide_sp - bare - 1
    ex, sp = price(["v.go d, base, idx"], DATA, CH + NL + variant("v", sw, fill), files=FILES)
    chosen[sw] = fill
    print("%-6d %10d %10d %14d %10.1f   %s"
          % (sw, fill, sp, sp - wide_sp, ex, "SIZE-IDENTICAL" if sp == wide_sp else "!! OFF"))
print("")
print("Fillers to use:  " + ", ".join("sw=%d -> rep(%d)" % (k, v) for k, v in sorted(chosen.items())))
print("Executed cost of the jump is included above, so these are the real per-call savings.")
