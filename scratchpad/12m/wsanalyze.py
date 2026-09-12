"""What would it take to make the DOOM image TLB-friendly? Read the touch map and answer.

The engine's per-op cost is set by how many PAGES the working set spans (measured curve in
`tlbprobe.c`: 2,048 pages -> 448.8 M ops/s, 22,994 -> 113.6). Large pages would collapse that,
but they need a Windows privilege the owner cannot be granted. So the only remaining lever is to
TOUCH FEWER PAGES, and the question this answers is how much room there actually is.

Input is `mkprof.py`'s FJPROF_DUMP: a uint64 header (words_per_unit, unit_count) followed by one
uint32 touch counter per unit, dumped at CACHE-LINE granularity (8 words = 64 B).

    python scratchpad/12m/wsanalyze.py <lines.bin>
"""
import struct
import sys
from pathlib import Path

LINE = 64
PAGE = 4096
HUGE = 2 * 1024 * 1024
TLB_ENTRIES = 2048              # Alder Lake L2 (STLB) entries for 4 KB pages

# the MEASURED page-count -> throughput curve from scratchpad/12m/tlbprobe.c, same machine.
# Used only to translate a page count into an expected speed; never extrapolated beyond its ends.
CURVE = [(2048, 448.8), (3414, 213.8), (6827, 171.5), (11497, 116.7),
         (22994, 113.6), (109221, 59.3)]


def speed_for(pages):
    """Interpolate the measured curve in log(pages). Returns (M ops/s, 'measured'|'interpolated')."""
    import math
    if pages <= CURVE[0][0]:
        return CURVE[0][1], "at/below the measured floor"
    if pages >= CURVE[-1][0]:
        return CURVE[-1][1], "at/above the measured ceiling"
    for (p0, s0), (p1, s1) in zip(CURVE, CURVE[1:]):
        if p0 <= pages <= p1:
            t = (math.log(pages) - math.log(p0)) / (math.log(p1) - math.log(p0))
            return s0 + t * (s1 - s0), "interpolated between %s and %s pages" % (
                format(p0, ","), format(p1, ","))
    return CURVE[-1][1], "off-curve"


def main():
    path = Path(sys.argv[1])
    raw = path.read_bytes()
    words_per_unit, unit_count = struct.unpack_from("<QQ", raw, 0)
    counts = memoryview(raw)[16:].cast("I")
    assert words_per_unit == 8, "expected cache-line granularity (8 words); got %d" % words_per_unit
    assert len(counts) == unit_count, "header says %d units, file has %d" % (unit_count, len(counts))

    lines_per_page = PAGE // LINE
    total_touches = 0
    touched_lines = 0
    pages = {}
    hugepages = {}
    for i in range(unit_count):
        c = counts[i]
        if not c:
            continue
        total_touches += c
        touched_lines += 1
        p = (i * LINE) // PAGE
        pages[p] = pages.get(p, 0) + c
        h = (i * LINE) // HUGE
        hugepages[h] = hugepages.get(h, 0) + c

    print("touches            : %s" % format(total_touches, ","))
    print("distinct 64B lines : %s = %.2f MB" % (format(touched_lines, ","),
                                                 touched_lines * LINE / 2**20))
    print("distinct 4K pages  : %s = %.2f MB of pages" % (format(len(pages), ","),
                                                          len(pages) * PAGE / 2**20))
    print("distinct 2M regions: %s" % format(len(hugepages), ","))
    print("PAGE UTILISATION   : %.1f%% (%.1f of %d lines per touched page)"
          % (100.0 * touched_lines / (len(pages) * lines_per_page),
             touched_lines / float(len(pages)), lines_per_page))
    print("")

    # ── what a PERFECT compaction would give: the same lines, packed
    packed_pages = (touched_lines + lines_per_page - 1) // lines_per_page
    packed_pages_u32 = (touched_lines // 2 + lines_per_page - 1) // lines_per_page
    now, wnow = speed_for(len(pages))
    pk, wpk = speed_for(packed_pages)
    pk32, wpk32 = speed_for(packed_pages_u32)
    print("IF THE SAME DATA WERE PACKED DENSELY")
    print("  today              : %8s pages -> %6.1f M ops/s   (%s)"
          % (format(len(pages), ","), now, wnow))
    print("  packed             : %8s pages -> %6.1f M ops/s   (%s)  = %.2fx"
          % (format(packed_pages, ","), pk, wpk, pk / now))
    print("  packed + 4B cells  : %8s pages -> %6.1f M ops/s   (%s)  = %.2fx"
          % (format(packed_pages_u32, ","), pk32, wpk32, pk32 / now))
    print("")

    # ── THE REAL QUESTION: the TLB does not need the whole set, only the HOT part. How much of
    # the access stream would be TLB-resident if the hot pages were packed?
    ordered = sorted(pages.items(), key=lambda kv: kv[1], reverse=True)
    print("HOW MUCH OF THE ACCESS STREAM THE TLB COULD ALREADY HOLD")
    print("  the top %d pages (a full TLB) carry %.2f%% of all touches TODAY"
          % (TLB_ENTRIES, 100.0 * sum(c for _p, c in ordered[:TLB_ENTRIES]) / total_touches))
    # and if packed: how many lines live in those hot pages, and what would they pack into
    for pct in (0.80, 0.90, 0.95, 0.99, 1.00):
        need = pct * total_touches
        acc, npages = 0, 0
        for _p, c in ordered:
            acc += c
            npages += 1
            if acc >= need:
                break
        # the LINES inside those pages, which is what a packed layout would actually occupy
        hot = set(p for p, _c in ordered[:npages])
        hot_lines = 0
        for i in range(unit_count):
            if counts[i] and ((i * LINE) // PAGE) in hot:
                hot_lines += 1
        pkp = (hot_lines + lines_per_page - 1) // lines_per_page
        print("  %4.0f%% of touches: %8s pages today -> packs into %7s pages  (%s, %s TLB)"
              % (pct * 100, format(npages, ","), format(pkp, ","),
                 "%.2f MB" % (hot_lines * LINE / 2**20),
                 "FITS" if pkp <= TLB_ENTRIES else "over"))
    print("")

    # ── where the sparseness lives: is it uniform, or a few bad regions?
    occ = sorted(((len([1 for p in pages if (p * PAGE) // HUGE == h]), h)
                  for h in hugepages), reverse=True)
    pages_per_huge = HUGE // PAGE
    print("SHAPE OF THE SPREAD (2 MB regions, %d pages each)" % pages_per_huge)
    print("  regions touched   : %s" % format(len(hugepages), ","))
    print("  mean pages/region : %.1f of %d (%.1f%% occupied)"
          % (len(pages) / float(len(hugepages)), pages_per_huge,
             100.0 * len(pages) / (len(hugepages) * pages_per_huge)))
    print("  densest region    : %d pages" % occ[0][0])
    print("  sparsest 10%% hold : %d pages total"
          % sum(n for n, _h in occ[int(len(occ) * 0.9):]))
    print("")
    print("READ THIS AS: with large pages the whole set would need %s TLB entries."
          % format(len(hugepages), ","))
    print("Without them, the lever is packing -- and the numbers above bound what it can buy.")


if __name__ == "__main__":
    raise SystemExit(main())
