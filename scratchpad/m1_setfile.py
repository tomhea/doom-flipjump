"""Convert the restore set from ABSOLUTE word addresses to LABEL + OFFSET.

Absolute addresses are only valid for the exact assembly they were derived from. As a build INPUT
that is a landmine: any change that shifts the layout silently makes the reset write the wrong
cells, and the build's own pass1-vs-pass2 check cannot see it, because it compares the two passes
to each other and not to the set.

Label-relative is layout-independent. The build resolves each (label, offset) against its OWN
pass-1 label table, and refuses if a label is missing.

    python scratchpad/m1_setfile.py --set scratchpad/_m1_setD.json.gz \
        --labels scratchpad/_m1b_labels.tsv.gz --out src/doomfj/data/m1_restore_set.json.gz
"""
import argparse
import bisect
import gzip
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.harness import W  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="scratchpad/_m1_setD.json.gz")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
args = ap.parse_args()

words = sorted(x for a, b in json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
               for x in range(a, b))
sa, sn = [], []
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            sa.append(int(v) // W)
            sn.append(a)
o = sorted(range(len(sa)), key=lambda i: sa[i])
sa = [sa[i] for i in o]
sn = [sn[i] for i in o]

rel = defaultdict(list)
orphan = 0
for x in words:
    i = bisect.bisect_right(sa, x) - 1
    if i < 0:
        orphan += 1
        continue
    rel[sn[i]].append(x - sa[i])
assert not orphan, "%d words fall before the first label" % orphan

out = Path(args.out)
out.parent.mkdir(parents=True, exist_ok=True)
payload = {"format": "label+offset", "words": len(words), "labels": len(rel),
           "entries": sorted(([k] + sorted(v)) for k, v in rel.items())}
json.dump(payload, gzip.open(out, "wt", encoding="utf-8"))
print("%s words over %s labels -> %s (%.2f MB)"
      % (format(len(words), ","), format(len(rel), ","), out, out.stat().st_size / 1e6))

# CONTROL: round-trip back to absolute using the same table and require an exact match.
back = set()
pos = {n: a for n, a in zip(sn, sa)}
for e in payload["entries"]:
    base = pos[e[0]]
    for off in e[1:]:
        back.add(base + off)
same = back == set(words)
print("CONTROL round-trip: %s (%d vs %d words)"
      % ("ok" if same else "!! MISMATCH", len(back), len(words)))
sys.exit(0 if same else 1)
