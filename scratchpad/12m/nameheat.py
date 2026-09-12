"""Name the hot runs. Turns "address 10,568,074 is hot" into "THIS emitted object is hot".

The access census says WHICH ADDRESSES carry the traffic; re-tiering the emitter's hot list needs
to know WHICH OBJECT each address is. The label table (`build_labeled.py`, via
`popcount_census._spy_on_labels`) is `name<TAB>bit-address` for exactly the build that was
profiled -- the pair must come from ONE build, because addresses shift with any change of pool
geometry or emitted file list, and a mismatched table would name things confidently wrong.

Two label flavours matter and they are reported separately:
  * TOP-LEVEL labels -- real names an address constant can depend on, e.g. `pclm`, `sfslot`.
  * macro-expansion labels -- `f<file>:l<line>:...`, which name a call site rather than an object.
    They are still useful (they say which emitted LINE produced the hot words) but they are not
    things the hot list can be reordered by, so they are labelled as such.

    python scratchpad/12m/nameheat.py <runs.tsv> <labels.tsv.gz> [top]
"""
import bisect
import gzip
import sys
from pathlib import Path


def human(n):
    return format(int(n), ",")


def is_top_level(name):
    """A macro-expansion label looks like `f<n>:l<n>:...`; anything else is a real name."""
    return not (name.startswith("f") and ":l" in name[:24])


def main():
    runs_path, labels_path = Path(sys.argv[1]), Path(sys.argv[2])
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    # label addresses are BIT addresses; the census counts WORDS. w=32 for this image.
    W = 32
    names, addrs = [], []
    with gzip.open(labels_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if not addr:
                continue
            try:
                a = int(addr)
            except ValueError:
                continue
            addrs.append(a // W)
            names.append(name)
    order = sorted(range(len(addrs)), key=lambda i: addrs[i])
    saddr = [addrs[i] for i in order]
    sname = [names[i] for i in order]
    print("labels loaded : %s (%s top-level)"
          % (human(len(sname)), human(sum(1 for n in sname if is_top_level(n)))))

    # the same, restricted to top-level names -- what a hot list can actually be reordered by
    tidx = [i for i in range(len(sname)) if is_top_level(sname[i])]
    taddr = [saddr[i] for i in tidx]
    tname = [sname[i] for i in tidx]

    runs = []
    with open(runs_path, encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            a, w, t, hw = (int(x) for x in line.split("\t"))
            runs.append((a, w, t, hw))
    total = sum(r[2] for r in runs)
    print("runs          : %s, %s touches" % (human(len(runs)), human(total)))
    print("")

    def name_at(arr, nm, word):
        i = bisect.bisect_right(arr, word) - 1
        if i < 0:
            return "(before the first label)", 0
        return nm[i], word - arr[i]

    print("THE HOTTEST RUNS, NAMED")
    print("%5s %14s %8s %7s  %-42s %s" % ("rank", "touches", "words", "%", "nearest top-level label",
                                          "exact label at start"))
    cum = 0
    for k, r in enumerate(runs[:top]):
        cum += r[2]
        tn, toff = name_at(taddr, tname, r[0])
        en, eoff = name_at(saddr, sname, r[0])
        tlabel = "%s+%s" % (tn, human(toff)) if toff else tn
        elabel = "%s+%s" % (en, human(eoff)) if eoff else en
        print("%5d %14s %8s %6.2f%%  %-42s %s"
              % (k, human(r[2]), human(r[1]), 100.0 * r[2] / total, tlabel[:42], elabel[:60]))
    print("")
    print("cumulative over the %d listed: %.2f%% of all touches" % (top, 100.0 * cum / total))

    # ── roll the heat up BY TOP-LEVEL OBJECT: this is the reorder key
    print("")
    print("HEAT BY TOP-LEVEL OBJECT (the key a hot list would be sorted on)")
    heat = {}
    words = {}
    for r in runs:
        tn, _ = name_at(taddr, tname, r[0])
        heat[tn] = heat.get(tn, 0) + r[2]
        words[tn] = words.get(tn, 0) + r[1]
    ranked = sorted(heat, key=lambda n: heat[n], reverse=True)
    print("%5s %14s %7s %12s  %s" % ("rank", "touches", "%", "words", "object"))
    cum = 0
    for k, n in enumerate(ranked[:top]):
        cum += heat[n]
        print("%5d %14s %6.2f%% %12s  %s"
              % (k, human(heat[n]), 100.0 * heat[n] / total, human(words[n]), n[:64]))
    print("")
    print("top %d objects carry %.2f%% of all touches in %s words"
          % (top, 100.0 * cum / total, human(sum(words[n] for n in ranked[:top]))))
    out = runs_path.with_suffix(".named.tsv")
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("\t".join(("object", "touches", "words")) + "\n")
        for n in ranked:
            fh.write("\t".join((n, str(heat[n]), str(words[n]))) + "\n")
    print("wrote %s (%s objects, heat-ordered)" % (out, human(len(ranked))))


if __name__ == "__main__":
    raise SystemExit(main())
