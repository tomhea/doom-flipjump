"""How mis-tiered is the CURRENT hot region? Measure it before proposing a new one.

`wall_renderer.py` already declares a hot region: the `hotdata` list jumped over by `;__hot_end`
with `pad 16384`. It ends at word 806,912 (6.16 MB at 8 B/word). It was built by POPCOUNT
reasoning -- put the things whose addresses want low popcount where the arms can reach them --
not by measured access frequency, because until this session there was no per-word access census.

So the question is simply: does the heat actually live there? This reads the heat-ordered run
profile (`hotruns.py`'s .runs.tsv) and splits every run by whether it falls inside the declared
hot region, and reports what each side carries. It needs no build and no labels.

If a large share of the touches lands OUTSIDE the declared region, the region is mis-tiered and
re-tiering it by measured heat is the single highest-value edit -- the emitter already has the
mechanism (a hot list and a `pad`), so it is a reordering, not new machinery.

    python scratchpad/12m/tiercheck.py <words.runs.tsv> [hot_end_word]
"""
import sys
from pathlib import Path

HOT_END = 806912          # `__hot_end` in build/doom_e1m1_blocked25.fjm, per the placement audit
ARM5_WINDOW = 32768       # frame.arm5 rewrites 5 nibbles -> one 16^5-bit window = 32,768 words


def human(n):
    return format(int(n), ",")


def main():
    path = Path(sys.argv[1])
    hot_end = int(sys.argv[2]) if len(sys.argv) > 2 else HOT_END

    runs = []
    with open(path, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            a, w, t, hw = (int(x) for x in line.split("\t"))
            runs.append((a, w, t, hw))
    total = sum(r[2] for r in runs)
    print("runs            : %s" % human(len(runs)))
    print("touches         : %s" % human(total))
    print("declared hot end: word %s (%.2f MB at 8 B/word)" % (human(hot_end), hot_end * 8 / 2**20))
    print("")

    inside = [r for r in runs if r[0] + r[1] <= hot_end]
    outside = [r for r in runs if r[0] >= hot_end]
    straddle = [r for r in runs if r[0] < hot_end < r[0] + r[1]]
    for label, group in (("INSIDE the hot region", inside),
                         ("OUTSIDE it", outside),
                         ("straddling the boundary", straddle)):
        t = sum(r[2] for r in group)
        w = sum(r[1] for r in group)
        print("%-26s %8s runs  %12s words  %14s touches  %6.2f%%"
              % (label, human(len(group)), human(w), human(t), 100.0 * t / total))
    print("")

    # ── the indictment: how much of the heat is stranded outside, and how far out
    out_sorted = sorted(outside, key=lambda r: r[2], reverse=True)
    print("HOTTEST RUNS STRANDED OUTSIDE THE DECLARED HOT REGION")
    print("%6s %14s %10s %14s %8s" % ("rank", "touches", "words", "start", "x hot_end"))
    for k, r in enumerate(out_sorted[:10]):
        print("%6d %14s %10s %14s %7.1fx"
              % (k, human(r[2]), human(r[1]), human(r[0]), r[0] / float(hot_end)))
    print("")

    # ── what the region SHOULD hold: the heat-ordered prefix that fits each budget
    print("WHAT A HEAT-ORDERED HOT REGION WOULD HOLD")
    print("%26s %10s %14s %16s" % ("budget", "runs", "words", "% of touches"))
    for cap, label in ((ARM5_WINDOW, "arm5 window 32,768w"),
                       (131072, "1 MB @8B"),
                       (393216, "3 MB @8B"),
                       (hot_end, "today's hot region size")):
        acc, nr, w = 0, 0, 0
        for r in runs:                      # runs.tsv is already heat-ordered
            if w + r[1] > cap:
                continue
            w += r[1]
            acc += r[2]
            nr += 1
        print("%26s %10s %14s %15.2f%%" % (label, human(nr), human(w), 100.0 * acc / total))
    print("")
    cur_in = sum(r[2] for r in inside) / total
    print("READ THIS AS: the declared region is %s words and carries %.1f%% of the touches."
          % (human(hot_end), 100.0 * cur_in))
    print("A heat-ordered region of the SAME size would carry the figure in the last row above;")
    print("the gap between them is what re-tiering buys before any other change.")


if __name__ == "__main__":
    raise SystemExit(main())
