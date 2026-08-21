"""Convert the restore set from ABSOLUTE word addresses to LABEL + OFFSET.

Absolute addresses are only valid for the exact assembly they were derived from. As a build INPUT
that is a landmine: any change that shifts the layout silently makes the reset write the wrong
cells, and the build's own pass1-vs-pass2 check cannot see it, because it compares the two passes
to each other and not to the set.

Label-relative is layout-independent. The build resolves each (label, offset) against its OWN
pass-1 label table, and refuses if a label is missing or if an offset escapes its label's span.

    python scratchpad/m1_setfile.py --set scratchpad/_m1_setD.json.gz \
        --labels scratchpad/_m1b_labels.tsv.gz --out src/doomfj/data/m1_restore_set.json.gz

R9. The previous version of this file carried a "round-trip" control that rebuilt the absolute set
from the SAME arrays that produced the offsets -- it computed base + (x - base) == x, an algebraic
identity, and could not fail for any input. It is replaced by a round-trip through the PRODUCTION
loader plus three negative controls that mutate the label table and REQUIRE a refusal or a
mismatch. Run with --selftest to execute the controls alone.
"""
import argparse
import bisect
import gzip
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj.harness import W          # noqa: E402
from doomfj import selfreset          # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="scratchpad/_m1_setD.json.gz")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_labels(path):
    sa, sn = [], []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            a, t, v = line.rstrip("\n").partition("\t")
            if t:
                sa.append(int(v) // W)
                sn.append(a)
    o = sorted(range(len(sa)), key=lambda i: sa[i])
    return [sa[i] for i in o], [sn[i] for i in o]


def build_payload(words, sa, sn):
    rel = defaultdict(list)
    orphan = 0
    for x in words:
        i = bisect.bisect_right(sa, x) - 1
        if i < 0:
            orphan += 1
            continue
        rel[sn[i]].append(x - sa[i])
    assert not orphan, "%d words fall before the first label" % orphan
    return {"format": "label+offset", "words": len(words), "labels": len(rel),
            "entries": sorted(([k] + sorted(v)) for k, v in rel.items())}


def resolve_via_production(payload, sa, sn, tmp):
    """Resolve through selfreset.load_restore_set -- the code the BUILD runs, not a local twin."""
    json.dump(payload, gzip.open(tmp, "wt", encoding="utf-8"))
    return selfreset.load_restore_set(tmp, {n: a * W for a, n in zip(sa, sn)})


def refuses(fn):
    try:
        fn()
    except AssertionError:
        return True
    return False


def controls(payload, words, sa, sn, tmp):
    """Three mutations of the real inputs; each MUST be caught. Prints ok/FAIL per control."""
    ok = True

    # C1 -- SHIFT. Move the busiest label by +2 words. The offsets under it are unchanged, so an
    # identity round-trip cannot notice; a real one must resolve to a DIFFERENT word set.
    busiest = max(payload["entries"], key=len)[0]
    j = sn.index(busiest)
    sa2 = list(sa)
    sa2[j] += 2
    try:
        got = resolve_via_production(payload, sa2, sn, tmp)
        c1 = got != set(words)
    except AssertionError:
        c1 = True                       # containment refused it -- also a catch
    print("  C1 shifted label %-28s -> %s" % (busiest[:28], "differs/refused ok" if c1 else "!! IDENTICAL - control is vacuous"))
    ok &= c1

    # C2 -- MISSING. Delete a label the set names. Must be refused, not silently dropped.
    keep = [i for i in range(len(sn)) if sn[i] != busiest]
    c2 = refuses(lambda: resolve_via_production(payload, [sa[i] for i in keep],
                                                [sn[i] for i in keep], tmp))
    print("  C2 deleted  label %-28s -> %s" % (busiest[:28], "refused ok" if c2 else "!! ACCEPTED"))
    ok &= c2

    # C3 -- ESCAPE. Pull the NEXT label back so the busiest label's largest offset runs past it.
    # Nearest-preceding attribution has no containment check of its own, so this is the failure
    # mode a plain round-trip is blind to.
    big = max(off for e in payload["entries"] if e[0] == busiest for off in e[1:])
    k = next((i for i in range(j + 1, len(sa)) if sa[i] > sa[j]), None)
    if k is None:
        print("  C3 skipped (no successor label)")
    else:
        sa3 = list(sa)
        sa3[k] = sa[j] + max(1, big // 2)
        c3 = refuses(lambda: resolve_via_production(payload, sa3, sn, tmp))
        print("  C3 offset %d escapes its span    -> %s" % (big, "refused ok" if c3 else "!! ACCEPTED"))
        ok &= c3

    # POSITIVE: the unmutated table must resolve to exactly the original words.
    got = resolve_via_production(payload, sa, sn, tmp)
    pos = got == set(words)
    print("  P  unmutated table               -> %s (%d words)"
          % ("exact ok" if pos else "!! MISMATCH", len(got)))
    return ok and pos


words = sorted(x for a, b in json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
               for x in range(a, b))
sa, sn = read_labels(args.labels)
payload = build_payload(words, sa, sn)
payload["source_sha256"] = sha_file(args.set)
payload["labels_sha256"] = sha_file(args.labels)
payload["generated_by"] = ("scratchpad/m1_setfile.py --set %s --labels %s"
                           % (args.set, args.labels))

tmp = Path(args.out).parent / "_m1_setfile_probe.json.gz"
Path(tmp).parent.mkdir(parents=True, exist_ok=True)
print("CONTROLS (each mutates the real label table and requires a catch):")
ok = controls(payload, words, sa, sn, tmp)
try:
    tmp.unlink()
except OSError:
    pass

if not ok:
    print("CONTROLS FAILED -- not writing %s" % args.out)
    sys.exit(1)
if args.selftest:
    print("SELFTEST: PASS")
    sys.exit(0)

out = Path(args.out)
json.dump(payload, gzip.open(out, "wt", encoding="utf-8"))
print("%s words over %s labels -> %s (%.2f MB)  src=%s labels=%s"
      % (format(len(words), ","), format(payload["labels"], ","), out,
         out.stat().st_size / 1e6, payload["source_sha256"][:12], payload["labels_sha256"][:12]))
