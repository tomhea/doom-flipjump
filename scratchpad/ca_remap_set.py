"""Re-key the M1 restore set onto the CURRENT program's labels, after a source change moved them.

WHY THIS IS NEEDED AT ALL. The set is keyed on mangled macro-expansion labels --
`f<file>:l<line>:macro(arity)---local` -- so it is invalidated by a change of macro ARITY, by moving
LINES in any file an expansion passes through, or by deleting a register that was in the set. The
constant-address work did all three (`point_to_angle` gained a `disp` parameter; `sprite_runs` lost
`n_ent`), and `build_wall_renderer(self_reset=True)` correctly REFUSED the binary.

WHY A RE-KEY IS SOUND HERE, and the assert that makes it more than a hope. 284 of the 308 labels
still exist verbatim. Of the 24 that do not: 4 name a register that no longer exists (dropped), and
20 differ only in line number / arity. Those 20 fall into groups that share a normalised shape, and
within every such group THE OFFSET LISTS ARE IDENTICAL -- so any bijection from the group's old
labels onto its new ones restores exactly the same set of words. The pairing cannot matter. That
property is ASSERTED below; if it ever fails, this script refuses and the set must be re-derived
from scratch instead.

    python scratchpad/ca_remap_set.py --labels scratchpad/_ca_labels.tsv.gz
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset          # noqa: E402
from doomfj.harness import W          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--labels", default="scratchpad/_ca_labels.tsv.gz")
ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
args = ap.parse_args()

doc = json.load(gzip.open(args.set, "rt", encoding="utf-8"))
ent = {e[0]: list(e[1:]) for e in doc["entries"]}
labels = {}
for line in gzip.open(args.labels, "rt", encoding="utf-8"):
    a, t, v = line.rstrip("\n").partition("\t")
    if t:
        labels.setdefault(a, int(v))

norm = lambda s: re.sub(r"\(\d+\)", "(?)", re.sub(r":l\d+:", ":l?:", s))
present = [n for n in ent if n in labels]
missing = [n for n in ent if n not in labels]
free = set(labels) - set(present)
byshape = {}
for a in free:
    byshape.setdefault(norm(a), []).append(a)

groups = {}
for n in missing:
    groups.setdefault(norm(n), []).append(n)

new_entries = [[n] + ent[n] for n in present]
dropped, remapped = [], []
for shape, olds in groups.items():
    cands = sorted(byshape.get(shape, []))
    if not cands:
        dropped.extend(olds)
        continue
    # THE CONTROL: a bijection is only safe if every member of the group carries the SAME offsets.
    offs = {tuple(ent[o]) for o in olds}
    assert len(offs) == 1, (
        "re-key REFUSED: group %r has %d distinct offset lists, so the pairing WOULD matter. "
        "Re-derive the set instead of re-keying it." % (shape[-60:], len(offs)))
    assert len(cands) == len(olds), (
        "re-key REFUSED: group %r has %d old labels but %d candidates"
        % (shape[-60:], len(olds), len(cands)))
    for o, c in zip(sorted(olds), cands):
        assert o.split("---")[-1] == c.split("---")[-1], (o[-40:], c[-40:])
        new_entries.append([c] + ent[o])
        remapped.append((o, c))

print("labels in the set      : %d" % len(ent))
print("  unchanged            : %d" % len(present))
print("  re-keyed             : %d" % len(remapped))
print("  dropped (register gone): %d  %s"
      % (len(dropped), sorted({d.split("---")[-1] for d in dropped})))

new_entries.sort()
words = set()
for e in new_entries:
    b = labels[e[0]] // W
    for off in e[1:]:
        words.add(b + off)
payload = {"format": "label+offset", "words": len(words), "labels": len(new_entries),
           "entries": [[e[0]] + sorted(e[1:]) for e in new_entries],
           "source_sha256": doc.get("source_sha256", "re-keyed"),
           "labels_sha256": hashlib.sha256(open(args.labels, "rb").read()).hexdigest(),
           "generated_by": "scratchpad/ca_remap_set.py --labels %s" % args.labels}
payload["layout_fingerprint"] = selfreset.layout_fingerprint(payload, labels)

old_words = doc["words"]
print("words: %s -> %s  (delta %+d, expected negative only from the dropped register)"
      % (format(old_words, ","), format(len(words), ","), len(words) - old_words))

tmp = Path(args.out).with_suffix(".probe.gz")
json.dump(payload, gzip.open(tmp, "wt", encoding="utf-8"))
got = selfreset.load_restore_set(tmp, labels)          # full production path, check_layout=True
assert got == words, "the production loader disagrees with this script"
print("production loader accepts it: %s words, layout fingerprint %s"
      % (format(len(got), ","), payload["layout_fingerprint"][:16]))
tmp.unlink()
json.dump(payload, gzip.open(args.out, "wt", encoding="utf-8"))
print("wrote %s" % args.out)
