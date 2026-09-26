"""S7 lift spike -- MEASURED word sizes of the bands-as-code bank and of M2's per-state door blocks,
read from the SHIPPED build's label table (blocked27). No build, no run: label addresses only.

    python scratchpad/gp/lift/label_sizes.py [scratchpad/12m/atlas/blocked27.labels.tsv.gz]

Addresses in the table are BITS; a word is 32 bits and an fj op is 2 words (dw = 64 bits).
A labelled unit's size = the distance to the next top-level label in address order, so every
number here is a sum of such distances inside one named region -- no model.

These figures feed lift_budget.py's per-unit word costs (W_ID, W_BODY, W_PB, W_BLK, W_SW) and so its
size claim. lift_budget.py --selftest re-derives the five from here, checks them against the
constants and against the shipped program's own counts, and requires a mutated stride and a mutated
label to be caught (the functions below take the table and the stride as arguments for that).
"""
import collections
import gzip
import re
import sys

DEFAULT = "scratchpad/12m/atlas/blocked27.labels.tsv.gz"
WORD_BITS = 32                                      # bits per fj word
POOL = 0x60000000                                   # --pool-base, bits
GROUPS = collections.OrderedDict([
    ("vpb_t<k> thunks (one per half-list id)", lambda n: re.fullmatch(r"vpb_t\d+", n)),
    ("vpb_body<k> + vpb_<k>_<j> (one per UNIQUE list)", lambda n: re.fullmatch(r"vpb_body\d+|vpb_\d+_\d+(_r)?|vpb_fin\d+", n)),
    ("vpb_pb_* shared pair blocks", lambda n: n.startswith("vpb_pb_")),
    ("vpb_cl_* clamp tails", lambda n: n.startswith("vpb_cl")),
    ("door per-state blocks  <seg>_st<k>", lambda n: re.search(r"_st\d+$", n) is not None),
    ("door switches  dsw_*", lambda n: n.startswith("dsw_")),
])


def load(path=DEFAULT):
    """the top-level labels as a sorted [(bit address, name)]"""
    top = []
    with gzip.open(path, "rt") as f:
        for line in f:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if "---" in name or not addr.isdigit():
                continue
            top.append((int(addr), name))
    top.sort()
    return top


def sizes(top, word_bits=WORD_BITS):
    """{name: words to the next distinct address}"""
    size = {}
    for i, (a, n) in enumerate(top):
        nxt = next((b for b, _ in top[i + 1:i + 50] if b > a), a)
        size.setdefault(n, (nxt - a) // word_bits)
    return size


def region(top, size, pred):
    s = c = 0
    for a, n in top:
        if pred(n) and a < POOL:
            s += size[n]
            c += 1
    return c, s


def measure(top, word_bits=WORD_BITS):
    """{group: (labels, words)}, plus the per-state door blocks' (blocks, units, states/unit)"""
    size = sizes(top, word_bits)
    out = collections.OrderedDict((g, region(top, size, p)) for g, p in GROUPS.items())
    st = [n for _, n in top if re.search(r"_st\d+$", n)]
    segs = collections.Counter(re.sub(r"_st\d+$", "", n) for n in st)
    return out, (len(st), len(segs), sorted(collections.Counter(segs.values()).items()))


def main(argv):
    path = argv[0] if argv else DEFAULT
    top = load(path)
    groups, (nblk, nunit, spu) = measure(top)
    print("labels (top-level) %d; pool base %d words" % (len(top), POOL // WORD_BITS))
    for g, (c, s) in groups.items():
        print("  %-50s labels %7d  words %10d  (%.1f words/label)" % (g, c, s, s / max(1, c)))
    print("  per-state door blocks: %d blocks over %d (seg, block-kind) units, states/unit %s"
          % (nblk, nunit, spu))


if __name__ == "__main__":
    main(sys.argv[1:])
