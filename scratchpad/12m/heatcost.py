"""1b. COST per object, not TOUCHES per object -- the ranking the plan should be built on.

`nameheat.py` ranked objects by touch count and put `cb_bx` at #1: 125M touches on a 3,920-word
block. But 125M touches on ~490 cache lines is a hot loop over L1-resident data -- nearly free.
`m1_reset` (35M touches spread over ~800k words) is what actually misses. Touches measure how
often an object is used; COST is how often using it misses, and that is governed by how many
distinct lines it spans and how much each line is reused.

For every top-level object this computes, from the word-level trace and the label table of the
SAME build:
    T   touches
    L8  distinct 64 B lines touched at 8 B/word      L4  the same at 4 B/word (the engine today)
    R   reuse = T / L4   -- touches per line; high R is cache-friendly, low R is a miss machine
and ranks by L4 (footprint share -- what fills the cache) and by T/R (an estimate of misses:
touches that cannot be served by reuse).

    python scratchpad/12m/heatcost.py <words.bin> <labels.tsv.gz> [top]
"""
import bisect
import gzip
import struct
import sys
from pathlib import Path


def human(n):
    return format(int(n), ",")


def is_top(name):
    return not (name.startswith("f") and ":l" in name[:24])


def main():
    words_bin, labels_gz = Path(sys.argv[1]), Path(sys.argv[2])
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 25
    W = 32

    names, addrs = [], []
    with gzip.open(labels_gz, "rt", encoding="utf-8") as fh:
        for line in fh:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if addr and is_top(name):
                try:
                    addrs.append(int(addr) // W)
                    names.append(name)
                except ValueError:
                    pass
    order = sorted(range(len(addrs)), key=lambda i: addrs[i])
    taddr = [addrs[i] for i in order]
    tname = [names[i] for i in order]

    raw = words_bin.read_bytes()
    wpu, n = struct.unpack_from("<QQ", raw, 0)
    assert wpu == 1
    counts = memoryview(raw)[16:].cast("I")

    T, L8, L4, WORDS = {}, {}, {}, {}
    total = 0
    for a in range(n):
        c = counts[a]
        if not c:
            continue
        total += c
        i = bisect.bisect_right(taddr, a) - 1
        obj = tname[i] if i >= 0 else "(before first label)"
        T[obj] = T.get(obj, 0) + c
        WORDS[obj] = WORDS.get(obj, 0) + 1
        L8.setdefault(obj, set()).add(a // 8)
        L4.setdefault(obj, set()).add(a // 16)

    objs = list(T)
    tot_l4 = sum(len(L4[o]) for o in objs)
    print("objects touched : %s   touches %s   distinct lines@4B %s = %.2f MB"
          % (human(len(objs)), human(total), human(tot_l4), tot_l4 * 64 / 2**20))
    print("")

    def row(o):
        l4 = len(L4[o]); l8 = len(L8[o]); t = T[o]
        r = t / float(l4)
        return t, l8, l4, r, WORDS[o]

    print("BY FOOTPRINT (distinct lines at 4 B/word -- what actually fills the cache)")
    print("%5s %10s %8s %10s %14s %9s  %s" % ("rank", "lines@4B", "MB", "touches%", "reuse T/L", "words", "object"))
    cum = 0
    for k, o in enumerate(sorted(objs, key=lambda o: len(L4[o]), reverse=True)[:top]):
        t, l8, l4, r, w = row(o)
        cum += l4
        print("%5d %10s %7.2f %9.2f%% %14s %9s  %s"
              % (k, human(l4), l4 * 64 / 2**20, 100.0 * t / total, human(r), human(w), o[:52]))
    print("      top %d objects hold %.1f%% of all touched lines" % (top, 100.0 * cum / tot_l4))
    print("")

    print("BY REUSE, LOWEST FIRST among objects with >= 1,000 lines (miss machines)")
    print("%5s %10s %10s %14s  %s" % ("rank", "lines@4B", "touches%", "reuse T/L", "object"))
    big = [o for o in objs if len(L4[o]) >= 1000]
    for k, o in enumerate(sorted(big, key=lambda o: T[o] / float(len(L4[o])))[:top]):
        t, l8, l4, r, w = row(o)
        print("%5d %10s %9.2f%% %14s  %s" % (k, human(l4), 100.0 * t / total, human(r), o[:60]))
    print("")

    print("BY TOUCHES (the OLD ranking, kept to show why it misled)")
    print("%5s %10s %10s %14s  %s" % ("rank", "touches%", "lines@4B", "reuse T/L", "object"))
    for k, o in enumerate(sorted(objs, key=lambda o: T[o], reverse=True)[:10]):
        t, l8, l4, r, w = row(o)
        print("%5d %9.2f%% %10s %14s  %s" % (k, 100.0 * t / total, human(l4), human(r), o[:60]))
    print("")
    print("READ THIS AS: an object high on the FOOTPRINT list with LOW reuse is where misses come")
    print("from. An object high on the TOUCHES list with high reuse is L1-resident and near free,")
    print("however hot it looks.")


if __name__ == "__main__":
    raise SystemExit(main())
