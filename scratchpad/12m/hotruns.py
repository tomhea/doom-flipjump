"""What are the natural PLACEMENT UNITS inside the one giant hot segment?

`segheat.py` established that segment-granularity placement is a dead end: ONE segment of
27,527,046 words carries 95.50% of all touches and holds 1,136,056 of the 1,362,373 hot words.
Ordering whole segments captures 2.18% of the traffic in a 1 MB budget. The hot data has to be
reordered WITHIN that block, which is the emitter's table layout.

So the question becomes: does the hot data inside it form identifiable CONTIGUOUS RUNS -- which
would be tables, i.e. things an emitter can place -- or is it individual words scattered evenly?
If it is runs, a placement pass reorders runs and the 1 MB / 2 MB tiers are reachable. If it is
isolated words, no placement pass can help and the answer has to come from emitting less data.

This clusters the touched words into runs (a run ends after `gap` untouched words), then reports
the run-size distribution and -- the number that decides the design -- how few runs carry the
hot 50/80/90/95% of the touch stream, and what those runs would occupy if laid end to end.

    python scratchpad/12m/hotruns.py <words.bin> <image.fjm> [gap]
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
    gap = int(sys.argv[3]) if len(sys.argv) > 3 else 8

    raw = words_bin.read_bytes()
    wpu, unit_count = struct.unpack_from("<QQ", raw, 0)
    assert wpu == 1, "need word granularity"
    counts = memoryview(raw)[16:].cast("I")

    r = fjm_reader.Reader(fjm_path)
    segs = sorted((s.segment_start, s.segment_length) for s in r.memory_segments)
    r.memory = {}
    big = max(segs, key=lambda al: al[1])
    lo, hi = big[0], big[0] + big[1]
    print("the giant segment : start %s, %s words" % (human(lo), human(big[1])))
    print("run gap threshold : %d untouched words ends a run" % gap)

    # ── cluster touched words into runs, inside the giant segment only
    runs = []            # (start, length_words, touches, hotwords)
    cur = None
    last = None
    total_all = 0
    for a in range(unit_count):
        c = counts[a]
        if c:
            total_all += c
        if not (lo <= a < hi):
            continue
        if not c:
            continue
        if cur is None or a - last - 1 >= gap:
            if cur is not None:
                runs.append(cur)
            cur = [a, 1, c, 1]
        else:
            cur[1] = a - cur[0] + 1
            cur[2] += c
            cur[3] += 1
        last = a
    if cur is not None:
        runs.append(cur)

    inside = sum(r_[2] for r_ in runs)
    print("touches inside it : %s of %s (%.2f%%)"
          % (human(inside), human(total_all), 100.0 * inside / total_all))
    print("RUNS found        : %s" % human(len(runs)))
    sizes = sorted(r_[1] for r_ in runs)
    print("run sizes (words) : median %s, p90 %s, p99 %s, max %s"
          % (human(sizes[len(sizes) // 2]), human(sizes[int(len(sizes) * .9)]),
             human(sizes[int(len(sizes) * .99)]), human(sizes[-1])))
    span_words = sum(sizes)
    hotw = sum(r_[3] for r_ in runs)
    print("runs cover        : %s words, of which %s ever touched (%.1f%% dense)"
          % (human(span_words), human(hotw), 100.0 * hotw / max(1, span_words)))
    print("")

    # ── THE DESIGN NUMBER: how few runs carry the heat, and what they cost laid end to end
    order = sorted(runs, key=lambda r_: r_[2], reverse=True)
    print("PACKING RUNS BY HEAT (a placement pass reorders runs, paying each run's FULL length)")
    print("%8s %12s %14s %12s %12s" % ("share", "runs", "words", "MB @8B", "MB @4B"))
    acc, nr, w = 0, 0, 0
    marks = [0.50, 0.80, 0.90, 0.95, 0.99, 1.00]
    mi = 0
    for r_ in order:
        acc += r_[2]
        nr += 1
        w += r_[1]
        while mi < len(marks) and acc >= marks[mi] * inside:
            print("%7.0f%% %12s %14s %12.2f %12.2f"
                  % (marks[mi] * 100, human(nr), human(w), w * 8 / 2**20, w * 4 / 2**20))
            mi += 1
    while mi < len(marks):
        print("%7.0f%% %12s %14s %12.2f %12.2f"
              % (marks[mi] * 100, human(nr), human(w), w * 8 / 2**20, w * 4 / 2**20))
        mi += 1
    print("")
    # ── THE OWNER'S BUDGETS, answered exactly rather than interpolated: 1 MB super-hot tier
    #    plus a 2 MB second tier. A run is placed whole, so each costs its FULL length.
    print("THE 1 MB + 2 MB TIER GOAL, EXACTLY")
    print("%10s %10s %12s %14s %14s" % ("cell", "tier", "runs", "words", "% of ALL touches"))
    for cell in (8, 4):
        for tier_mb, label in ((1, "1MB hot"), (3, "1MB+2MB")):
            cap = tier_mb * 2**20 // cell
            acc2, nr2, w2 = 0, 0, 0
            for r_ in order:
                if w2 + r_[1] > cap:
                    continue                   # a later, smaller run may still fit
                w2 += r_[1]
                acc2 += r_[2]
                nr2 += 1
            print("%9dB %10s %12s %14s %13.1f%%"
                  % (cell, label, human(nr2), human(w2), 100.0 * acc2 / total_all))
    print("")
    # ── THE ARM5 CEILING, verified in flipjump-151 assembler.py:215 and doom ritual.py:210.
    #    `frame.arm5` rewrites only the low FIVE nibbles of three pointer fields, so every
    #    narrow-armed table must sit inside ONE aligned 16^5-bit window = 32,768 words. A 1 MB
    #    tier is 131,072 words and cannot be one window. That is not a loss: the measured
    #    latency curve reads 0.25 MB at 3.72 ns against 1.00 MB at 4.82 ns, so the smaller tier
    #    is FASTER as well as legal, and 256 KB is L2-resident even on 2019 Skylake (256 KB L2).
    print("TIER BUDGETS (words), against the arm5 32,768-word ceiling")
    print("%26s %12s %14s %14s" % ("budget", "runs", "words", "% of ALL touches"))
    for cap, label in ((32768, "arm5 window 32,768w"), (131072, "1 MB @8B"),
                       (262144, "1 MB @4B / 2MB@8B"), (393216, "3 MB @8B"),
                       (786432, "3 MB @4B"), (10**9, "everything packed")):
        acc2, nr2, w2 = 0, 0, 0
        for r_ in order:
            if w2 + r_[1] > cap:
                continue
            w2 += r_[1]
            acc2 += r_[2]
            nr2 += 1
        print("%26s %12s %14s %13.1f%%"
              % (label, human(nr2), human(w2), 100.0 * acc2 / total_all))
    print("")
    # ── the run list IS the heat profile a placement pass consumes. Dump it once so later
    #    analysis and the pass itself never re-scan the 384 MB trace.
    out = words_bin.with_suffix(".runs.tsv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(("start", "words", "touches", "hot_words")) + "\n")
        for r_ in order:
            fh.write("\t".join(str(v) for v in (r_[0], r_[1], r_[2], r_[3])) + "\n")
    print("wrote heat profile: %s (%s runs, heat-ordered)" % (out, human(len(order))))
    print("")
    print("THE HOTTEST RUNS")
    print("%6s %14s %10s %12s %10s" % ("rank", "touches", "words", "start", "dense%"))
    cum = 0
    for k, r_ in enumerate(order[:12]):
        cum += r_[2]
        print("%6d %14s %10s %12s %9.0f%%"
              % (k, human(r_[2]), human(r_[1]), human(r_[0]), 100.0 * r_[3] / r_[1]))
    print("")
    print("READ THIS AS: if a few thousand runs of a few hundred words carry the hot 90%, they")
    print("are tables and a placement pass can tier them. If the hot 90% needs hundreds of")
    print("thousands of runs, the data is scattered per-word and placement cannot fix it.")


if __name__ == "__main__":
    raise SystemExit(main())
