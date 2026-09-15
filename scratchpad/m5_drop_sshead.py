"""Drop `sshead` from the STANDALONE restore set (2026-09-13): the standalone tier bakes its
per-leaf thing lists finished and no longer calls sim.bind_things, so the frame never dirties
sshead -- and a reset that zeroed it would destroy the baked lists every frame.

RE-KEY, NEVER RE-DERIVE: the certified set is the input; the one edit is removing one label, and
`words` and the layout fingerprint are recomputed. The result is pushed through the PRODUCTION
loader (selfreset.load_restore_set, fingerprint check ON) against a label table of the same data
layout, so the build cannot be the first place it is tried.

    python scratchpad/m5_drop_sshead.py --labels scratchpad/12m/atlas/b26.labels.tsv.gz
"""
import argparse, gzip, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="src/doomfj/data/m5_restore_set.json.gz")
ap.add_argument("--labels", required=True)
ap.add_argument("--drop", default="sshead")
a = ap.parse_args()

doc = json.load(gzip.open(a.set, "rt", encoding="utf-8"))
before = len(doc["entries"])
gone = [e for e in doc["entries"] if e[0] == a.drop]
assert len(gone) == 1, "expected exactly one %r entry, found %d" % (a.drop, len(gone))
doc["entries"] = [e for e in doc["entries"] if e[0] != a.drop]
dropped_words = len(gone[0]) - 1
doc["words"] -= dropped_words
labels = {}
with gzip.open(a.labels, "rt", encoding="utf-8") as f:
    for line in f:
        name, tab, value = line.rstrip("\n").partition("\t")
        if tab:
            labels.setdefault(name, int(value))
doc["layout_fingerprint"] = selfreset.layout_fingerprint(doc, labels)
doc["generated_by"] = (doc.get("generated_by", "") + " | m5_drop_sshead.py: -sshead (%d words), "
                       "lists baked, 2026-09-13" % dropped_words)
# THE CHECK: the production loader, fingerprint on, must accept it and resolve to exactly `words`
resolved = selfreset.load_restore_set_from_doc if hasattr(selfreset, "load_restore_set_from_doc") else None
tmp = Path(a.set + ".tmp.gz")
with gzip.open(tmp, "wt", encoding="utf-8") as f:
    json.dump(doc, f)
words = selfreset.load_restore_set(tmp, labels, check_layout=True)
assert len(words) == doc["words"], (len(words), doc["words"])
# negative control: the OLD set must now FAIL the fingerprint against a doc without sshead... it
# cannot (its fingerprint covers its own labels); instead prove the drop is real: no resolved word
# lies inside sshead's extent.
base = labels[a.drop] // 32
assert not any(base <= w < base + 2728 for w in words), "a resolved word still lies inside sshead"
tmp.replace(Path(a.set))
print("%s: %d -> %d entries, words %d (-%d), fingerprint %s; loader accepts it"
      % (a.set, before, len(doc["entries"]), doc["words"], dropped_words, doc["layout_fingerprint"][:12]))
