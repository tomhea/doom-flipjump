"""Would 4-byte cells actually shrink the hot working set? Answer it before building anything.

THE QUESTION. The corrected latency probe (`latprobe.c`, Sattolo single-cycle) puts this
machine's knee at the L2 boundary and the DOOM binary's hot set just past it:

      0.25 MB ->  3.72 ns    1.00 MB ->  4.82 ns    1.33 MB ->  8.06 ns
      2.67 MB -> 16.57 ns   <- where the game sits   26.67 MB -> 110.08 ns

So halving the hot set is worth ~2x. Storing a w=32 program's words in 4-byte cells instead of
8-byte cells halves every ADDRESS -- but that only halves the LINE COUNT if the touched words
share lines. If the hot words are isolated singles, each still needs its own 64 B line after
packing and the change buys nothing. The earlier "+2.7%" estimate for this change came from a
benchmark that has since been shown to be broken, so it is worth nothing either way.

THIS ANSWERS IT FROM THE ACTUAL ACCESS TRACE, at word granularity: group the touched words by
the line they land in at 8 bytes per word, then by the line they would land in at 4 bytes per
word, and compare -- overall and for the hot set that matters.

    python scratchpad/12m/packgain.py <words.bin>
"""
import struct
import sys
from pathlib import Path

LINE = 64


def curve_ns(mb):
    """MEASURED dependent-chase latency (latprobe.c, this machine). Interpolated in log(MB)."""
    import math
    pts = [(0.03, 1.23), (0.25, 3.72), (0.50, 4.21), (0.67, 4.58), (1.00, 4.82),
           (1.33, 8.06), (1.75, 14.55), (2.00, 15.62), (2.67, 16.57), (3.00, 25.85),
           (4.00, 21.36), (6.00, 82.15), (14.0, 105.64), (26.67, 110.08)]
    if mb <= pts[0][0]:
        return pts[0][1]
    if mb >= pts[-1][0]:
        return pts[-1][1]
    for (a, x), (b, y) in zip(pts, pts[1:]):
        if a <= mb <= b:
            t = (math.log(mb) - math.log(a)) / (math.log(b) - math.log(a))
            return x + t * (y - x)
    return pts[-1][1]


def main():
    raw = Path(sys.argv[1]).read_bytes()
    words_per_unit, unit_count = struct.unpack_from("<QQ", raw, 0)
    assert words_per_unit == 1, "need word granularity (FJPROF_WORDS_PER_UNIT=1), got %d" % words_per_unit
    counts = memoryview(raw)[16:].cast("I")

    total = 0
    words = 0
    lines8 = {}     # line index at 8 bytes/word: addr*8 // 64  == addr // 8
    lines4 = {}     # line index at 4 bytes/word: addr*4 // 64  == addr // 16
    for a in range(unit_count):
        c = counts[a]
        if not c:
            continue
        total += c
        words += 1
        l8 = a // 8
        l4 = a // 16
        lines8[l8] = lines8.get(l8, 0) + c
        lines4[l4] = lines4.get(l4, 0) + c

    mb8 = len(lines8) * LINE / 2**20
    mb4 = len(lines4) * LINE / 2**20
    print("touches                 : %s" % format(total, ","))
    print("distinct WORDS touched  : %s" % format(words, ","))
    print("lines at 8 B/word       : %s = %.2f MB   (%.2f words per line)"
          % (format(len(lines8), ","), mb8, words / float(len(lines8))))
    print("lines at 4 B/word       : %s = %.2f MB   (%.2f words per line)"
          % (format(len(lines4), ","), mb4, words / float(len(lines4))))
    print("=> 4-byte cells shrink the FULL touched set by %.2fx" % (mb8 / mb4 if mb4 else 0))
    print("")

    # the hot set is what the latency curve cares about -- a chase mostly stays in it
    print("%-6s %14s %14s %10s   %s" % ("pct", "MB @8B/word", "MB @4B/word", "shrink",
                                        "ns/access  8B -> 4B   (speedup)"))
    for pct in (0.50, 0.80, 0.90, 0.95, 0.99, 1.00):
        need = pct * total
        h8 = 0
        acc = 0
        for _l, c in sorted(lines8.items(), key=lambda kv: kv[1], reverse=True):
            acc += c
            h8 += 1
            if acc >= need:
                break
        h4 = 0
        acc = 0
        for _l, c in sorted(lines4.items(), key=lambda kv: kv[1], reverse=True):
            acc += c
            h4 += 1
            if acc >= need:
                break
        a8 = h8 * LINE / 2**20
        a4 = h4 * LINE / 2**20
        n8, n4 = curve_ns(a8), curve_ns(a4)
        print("%-6s %14.2f %14.2f %9.2fx   %6.2f -> %6.2f    (%.2fx)"
              % ("%.0f%%" % (pct * 100), a8, a4, (a8 / a4) if a4 else 0, n8, n4,
                 (n8 / n4) if n4 else 0))
    print("")
    print("READ THIS AS: the shrink column is what 4-byte cells buy in CACHE FOOTPRINT, and the")
    print("last column is what the MEASURED latency curve says that is worth. A shrink near 1.00x")
    print("would mean the touched words are isolated singles and the change buys nothing.")

    # ── THE BIGGER LEVER. Only 3.12 of a line's 8 words are ever touched, so the hot data is
    # ~32% dense INSIDE its own cache lines. Cell size is a 1.65x effect; PACKING THE HOT WORDS
    # TOGETHER is bounded by the raw word count, which is far smaller. This computes that bound:
    # how many distinct WORDS carry each share of the traffic, and what they would occupy if
    # laid out contiguously.
    print("")
    print("IF THE HOT WORDS WERE PACKED CONTIGUOUSLY (profile-guided layout)")
    print("%-6s %12s %12s %12s   %s" % ("pct", "words", "packed 8B", "packed 4B",
                                        "ns/access now -> packed8 -> packed4"))
    order = sorted(((c, a) for a, c in ((i, counts[i]) for i in range(unit_count)) if c),
                   reverse=True)
    acc = 0
    nwords = 0
    marks = {0.50: None, 0.80: None, 0.90: None, 0.95: None, 0.99: None, 1.00: None}
    todo = sorted(marks)
    ti = 0
    for c, _a in order:
        acc += c
        nwords += 1
        while ti < len(todo) and acc >= todo[ti] * total:
            marks[todo[ti]] = nwords
            ti += 1
    for pct in todo:
        w = marks[pct] or nwords
        p8 = w * 8 / 2**20
        p4 = w * 4 / 2**20
        # the CURRENT footprint at that share, from the line census above
        need = pct * total
        h8, a2 = 0, 0
        for _l, c in sorted(lines8.items(), key=lambda kv: kv[1], reverse=True):
            a2 += c
            h8 += 1
            if a2 >= need:
                break
        now = h8 * LINE / 2**20
        print("%-6s %12s %9.2f MB %9.2f MB   %6.2f -> %6.2f -> %6.2f   (%.2fx / %.2fx)"
              % ("%.0f%%" % (pct * 100), format(w, ","), p8, p4,
                 curve_ns(now), curve_ns(p8), curve_ns(p4),
                 curve_ns(now) / curve_ns(p8), curve_ns(now) / curve_ns(p4)))
    print("")
    print("Packing is bounded by the WORD count, not the line count, so it is the larger lever:")
    print("cell size is worth ~1.65x, packing collapses the 3.12-words-per-line waste as well.")


if __name__ == "__main__":
    raise SystemExit(main())
