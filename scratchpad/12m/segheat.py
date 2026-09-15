"""Can a 1 MB super-hot tier and a 2 MB second tier actually be BUILT? Answer before coding it.

THE GOAL (owner, 2026-09-12): pack the super-hot data into 1 MB and the rest of the hot data into
2 MB, so both live in L2 on ordinary machines (256 KB on 2019 Skylake-era, 512 KB on Zen 2/3,
1-2 MB on 2021+ Intel / Zen 4+).

THE CATCH THIS MEASURES. `packgain.py` showed the hot words are tiny -- 145,908 words carry 90%
of all touches, 1.11 MB packed -- but that is a bound on packing INDIVIDUAL WORDS, and nothing
can place individual words. Placement happens per SEGMENT: a segment is contiguous and moves as
one unit, so pulling a hot word into the hot tier drags its whole segment along. If the hot words
sit in small segments the goal is reachable; if they sit inside a few enormous mostly-cold
segments, per-segment packing cannot reach 1 MB no matter how it is ordered, and the plan has to
change (split segments, or place at a finer granularity).

So: attribute every touch to its segment, then simulate the actual buildable layout -- sort
segments by heat, lay them end to end, and report what share of the touch stream each budget
captures. That is the honest ceiling for a segment-granularity placement pass.

    python scratchpad/12m/segheat.py <words.bin> <image.fjm>
"""
import bisect
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from flipjump.fjm import fjm_reader          # noqa: E402


def human(n):
    return format(int(n), ",")


def main():
    words_bin, fjm_path = Path(sys.argv[1]), Path(sys.argv[2])

    raw = words_bin.read_bytes()
    words_per_unit, unit_count = struct.unpack_from("<QQ", raw, 0)
    assert words_per_unit == 1, "need FJPROF_WORDS_PER_UNIT=1, got %d" % words_per_unit
    counts = memoryview(raw)[16:].cast("I")

    r = fjm_reader.Reader(fjm_path)
    segs = sorted((s.segment_start, s.segment_length) for s in r.memory_segments)
    r.memory = {}                              # the word dict is ~4 GB; we only need the layout
    starts = [a for a, _l in segs]
    print("segments        : %s" % human(len(segs)))
    print("image span      : %s words" % human(max(a + l for a, l in segs)))

    # ── attribute touches to segments
    seg_touch = {}
    seg_hotwords = {}
    total = 0
    orphan = 0
    for a in range(unit_count):
        c = counts[a]
        if not c:
            continue
        total += c
        i = bisect.bisect_right(starts, a) - 1
        if i < 0 or a >= segs[i][0] + segs[i][1]:
            orphan += c                        # touched outside any declared segment
            continue
        seg_touch[i] = seg_touch.get(i, 0) + c
        seg_hotwords[i] = seg_hotwords.get(i, 0) + 1

    print("touches         : %s  (%s outside any segment)" % (human(total), human(orphan)))
    print("segments touched: %s of %s (%.2f%%)"
          % (human(len(seg_touch)), human(len(segs)), 100.0 * len(seg_touch) / len(segs)))

    sizes = [segs[i][1] for i in seg_touch]
    sizes.sort()
    touched_words_total = sum(seg_hotwords.values())
    seg_bytes_total = sum(segs[i][1] for i in seg_touch) * 8
    print("touched words   : %s" % human(touched_words_total))
    print("their segments  : %s words = %.2f MB at 8 B/word   <- what packing them REALLY costs"
          % (human(seg_bytes_total // 8), seg_bytes_total / 2**20))
    print("segment sizes   : median %s, p90 %s, max %s words"
          % (human(sizes[len(sizes) // 2]), human(sizes[int(len(sizes) * 0.9)]), human(sizes[-1])))
    print("density in touched segments: %.1f%% of their words are ever read"
          % (100.0 * touched_words_total / max(1, seg_bytes_total // 8)))
    print("")

    # ── the buildable layout: order whole segments by heat, lay them contiguously
    order = sorted(seg_touch, key=lambda i: seg_touch[i], reverse=True)
    print("PACKING WHOLE SEGMENTS BY HEAT (the layout a placement pass can actually emit)")
    print("%10s %14s %12s %14s %14s" % ("budget", "segments", "words", "% of touches",
                                        "hot-word share"))
    for budget_mb, cell in ((1, 8), (2, 8), (3, 8), (1, 4), (2, 4), (3, 4), (8, 8), (16, 8)):
        cap_words = budget_mb * 2**20 // cell
        used, acc, nseg, hotw = 0, 0, 0, 0
        for i in order:
            L = segs[i][1]
            if used + L > cap_words:
                continue                       # skip: a later, smaller segment may still fit
            used += L
            acc += seg_touch[i]
            hotw += seg_hotwords[i]
            nseg += 1
        print("%6d MB@%dB %14s %12s %13.2f%% %13.2f%%"
              % (budget_mb, cell, human(nseg), human(used), 100.0 * acc / total,
                 100.0 * hotw / touched_words_total))
    print("")

    # ── how concentrated is the heat? the top segments by touches
    print("THE HOTTEST SEGMENTS")
    print("%6s %14s %12s %12s %10s" % ("rank", "touches", "%", "seg words", "hot words"))
    cum = 0
    for k, i in enumerate(order[:12]):
        cum += seg_touch[i]
        print("%6d %14s %11.2f%% %12s %10s"
              % (k, human(seg_touch[i]), 100.0 * cum / total, human(segs[i][1]),
                 human(seg_hotwords[i])))
    print("")
    print("READ THIS AS: if the 1 MB row captures most of the touch stream, a segment-granularity")
    print("placement pass reaches the goal. If it does not, the hot words are trapped inside big")
    print("cold segments and the pass must SPLIT segments (or place finer) to get there.")


if __name__ == "__main__":
    raise SystemExit(main())
