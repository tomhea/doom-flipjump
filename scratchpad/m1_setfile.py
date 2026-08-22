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
import tempfile
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
ap.add_argument("--view-w", type=int, default=160)
ap.add_argument("--nss", type=int, default=682)
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


def resolve_via_production(payload, sa, sn, tmp, refingerprint=False):
    """Resolve through selfreset.load_restore_set -- the code the BUILD runs, not a local twin.

    `refingerprint` recomputes the layout fingerprint for the MUTATED table. The controls need it:
    otherwise every mutation would be caught by the fingerprint alone and C1/C2/C3 would stop
    testing resolution, containment and the missing-label refusal at all -- passing for the wrong
    reason, which is the failure this file already had once.
    """
    labels = {n: a * W for a, n in zip(sa, sn)}
    doc = dict(payload)
    if refingerprint:
        doc["layout_fingerprint"] = selfreset.layout_fingerprint(doc, labels)
    json.dump(doc, gzip.open(tmp, "wt", encoding="utf-8"))
    return selfreset.load_restore_set(tmp, labels)


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
        got = resolve_via_production(payload, sa2, sn, tmp, refingerprint=True)
        c1 = got != set(words)
    except AssertionError:
        c1 = True                       # containment refused it -- also a catch
    print("  C1 shifted label %-28s -> %s" % (busiest[:28], "differs/refused ok" if c1 else "!! IDENTICAL - control is vacuous"))
    ok &= c1

    # C2 -- MISSING. Delete a label the set names. Must be refused, not silently dropped.
    keep = [i for i in range(len(sn)) if sn[i] != busiest]
    c2 = refuses(lambda: resolve_via_production(payload, [sa[i] for i in keep],
                                                [sn[i] for i in keep], tmp, True))
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
        c3 = refuses(lambda: resolve_via_production(payload, sa3, sn, tmp, True))
        print("  C3 offset %d escapes its span    -> %s" % (big, "refused ok" if c3 else "!! ACCEPTED"))
        ok &= c3

    # C4 -- LAYOUT. Shift a label WITHOUT refingerprinting: resolution, containment and the count
    # can all still pass, and only the fingerprint can catch it. This is the hazard the three
    # provenance hashes describe but cannot check.
    c4 = refuses(lambda: resolve_via_production(payload, sa2, sn, tmp))
    print("  C4 layout changed, fingerprint stale -> %s" % ("refused ok" if c4 else "!! ACCEPTED"))
    ok &= c4

    # POSITIVE: the unmutated table must resolve to exactly the original words.
    got = resolve_via_production(payload, sa, sn, tmp, refingerprint=True)
    pos = got == set(words)
    print("  P  unmutated table               -> %s (%d words)"
          % ("exact ok" if pos else "!! MISMATCH", len(got)))
    return ok and pos


def synthetic():
    """Inputs for --selftest, built here rather than read from disk.

    CR round 2: --selftest read scratchpad/_m1_setD.json.gz and a 48 MB _m1b_labels.tsv.gz, neither
    of which is tracked, so on a clean checkout the control died in open() and the shipped data file
    could not be regenerated by the command its own provenance field names. The controls are about
    the RESOLUTION LOGIC, and that logic does not care whose program the labels came from.
    """
    # spacing IS the declaration: sshead 2*nss cells, the per-column arrays view_w cells
    sa = [100, 112, 120, 128, 134]
    sn = ["sshead", "pclm", "sfflag", "scratch", "zzz_end"]
    # sshead reaches nss cells of a 2*nss declaration; the tail must be trimmed, exactly as on the
    # real set, so the selftest exercises the trim too.
    words = list(range(100, 112)) + list(range(112, 120)) + list(range(120, 128))         + list(range(128, 134))          # sshead 106..111 is the padding the trim must remove
    return words, sa, sn


if args.selftest:
    words, sa, sn = synthetic()
    args.view_w, args.nss = 4, 3
    print("SELFTEST inputs are synthetic (no scratchpad artifacts needed)")
else:
    words = sorted(x for a, b in json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
                   for x in range(a, b))
    sa, sn = read_labels(args.labels)

# TRIM THE UNREACHABLE TAIL OF EACH BYTE ARRAY. The set was derived by taking whole label extents
# ("derive labels, never learn cells" -- a sampled set is unsound, because a cell can be clean at
# one viewpoint and dirty at another). But sshead is declared hex.vec 2*nss while a 1-cell stride
# reaches only nss, so half its extent is padding no code can address. Those words cannot be byte
# cells, so they fall through to the NIBBLE clear -- 682 dead cells, ~13.3k ops/frame.
# MEASURED, not assumed: 0 dirty words there across all five scratchpad/_m1_dirty*.json.gz maps.
bits = {n: a * W for a, n in zip(sa, sn)}
ws = sorted(set(sa))
drop = set()
for name, reach in selfreset.byte_arrays(bits, ws, args.view_w, args.nss):
    base = bits[name] // W
    i = bisect.bisect_right(ws, base)
    end = ws[i] if i < len(ws) else base + 2 * reach
    tail = range(base + 2 * reach, end)
    drop.update(tail)
    if len(tail):
        print("  trim %-8s reachable %d cells; dropping %d unreachable-padding words"
              % (name, reach, len(tail)))
before = len(words)
words = [x for x in words if x not in drop]
print("  restore set %d -> %d words (%d trimmed)" % (before, len(words), before - len(words)))

payload = build_payload(words, sa, sn)
payload["source_sha256"] = "selftest" if args.selftest else sha_file(args.set)
payload["labels_sha256"] = "selftest" if args.selftest else sha_file(args.labels)
payload["generated_by"] = ("scratchpad/m1_setfile.py --set %s --labels %s"
                           % (args.set, args.labels))
# The one piece of provenance the BUILD can actually check: the layout of the labels this set
# names. Invariant to line-number churn elsewhere; catches a set from a different map or tier.
payload["layout_fingerprint"] = selfreset.layout_fingerprint(
    payload, {n: a * W for a, n in zip(sa, sn)})
print("  layout_fingerprint %s" % payload["layout_fingerprint"][:16])

tmp = Path(tempfile.mkdtemp(prefix="m1set_")) / "probe.json.gz"
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
