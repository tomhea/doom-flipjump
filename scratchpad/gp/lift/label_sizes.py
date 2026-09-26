"""S7 lift spike -- MEASURED word sizes of the bands-as-code bank and of M2's per-state door blocks,
read from the SHIPPED build's label table (blocked27). No build, no run: label addresses only.

    python scratchpad/gp/lift/label_sizes.py [scratchpad/12m/atlas/blocked27.labels.tsv.gz]

Addresses in the table are BITS; a word is 32 bits and an fj op is 2 words (dw = 64 bits).
A labelled unit's size = the distance to the next top-level label in address order, so every
number here is a sum of such distances inside one named region -- no model.
"""
import gzip, re, sys, collections
path = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/12m/atlas/blocked27.labels.tsv.gz"
top = []
with gzip.open(path, "rt") as f:
    for line in f:
        name, _, addr = line.rstrip("\n").rpartition("\t")
        if "---" in name or not addr.isdigit():
            continue
        top.append((int(addr), name))
top.sort()
addrs = [a for a, _ in top]
size = {}
for i, (a, n) in enumerate(top):
    nxt = next((b for b, _ in top[i + 1:i + 50] if b > a), a)
    size.setdefault(n, (nxt - a) // 32)            # words to the next distinct address
POOL = 0x60000000                                   # --pool-base, bits
def region(pred):
    s = c = 0
    for a, n in top:
        if pred(n) and a < POOL:
            s += size[n]; c += 1
    return c, s
groups = collections.OrderedDict([
    ("vpb_t<k> thunks (one per half-list id)", lambda n: re.fullmatch(r"vpb_t\d+", n)),
    ("vpb_body<k> + vpb_<k>_<j> (one per UNIQUE list)", lambda n: re.fullmatch(r"vpb_body\d+|vpb_\d+_\d+(_r)?|vpb_fin\d+", n)),
    ("vpb_pb_* shared pair blocks", lambda n: n.startswith("vpb_pb_")),
    ("vpb_cl_* clamp tails", lambda n: n.startswith("vpb_cl")),
    ("door per-state blocks  <seg>_st<k>", lambda n: re.search(r"_st\d+$", n) is not None),
    ("door switches  dsw_*", lambda n: n.startswith("dsw_")),
])
print("labels (top-level) %d; pool base %d words" % (len(top), POOL // 32))
for g, p in groups.items():
    c, s = region(p)
    print("  %-50s labels %7d  words %10d  (%.1f words/label)" % (g, c, s, s / max(1, c)))
st = [n for _, n in top if re.search(r"_st\d+$", n)]
segs = collections.Counter(re.sub(r"_st\d+$", "", n) for n in st)
print("  per-state door blocks: %d blocks over %d (seg, block-kind) units, states/unit %s"
      % (len(st), len(segs), sorted(collections.Counter(segs.values()).items())))
