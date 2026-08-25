"""Add the hoisted sim scratch globals to a re-keyed M1 restore set.

WHY THIS FILE EXISTS. `ca_remap_set.py` re-keys the certified set onto a new label table, but it can
only remap labels that still exist. bdf1f1a hoisted `sim.check_block` / `check_line` scratch out of
`@`-locals into NAMED GLOBALS (`collision.py::CHECK_SCRATCH_DECLS`), so 64 old keys name registers
that are simply gone and the re-key DROPS them. Dropping is not neutral: a hole in the restore set
does not draw wrong pixels, it HANGS the next frame (docs/handoff-m1-reset.md 4b). This adds the
globals that took their place, at full extent, so the set is whole again.

    python scratchpad/ca_remap_set.py --labels L --set S --out O      # step 1: re-key
    python scratchpad/m1_add_globals.py --labels L --set O --out O    # step 2: fill the holes

⚠ R9 (CR 2026-08-25). The shipped set previously recorded a `generated_by` naming only step 1, which
does not perform step 2 -- so the artifact could not be regenerated from the tracked tree. That is
the same defect CR round 2 fixed in m1_setfile.py, returning in a new form. This file IS step 2.

EXTENTS ARE DERIVED, NEVER BAKED. Each global's word count comes from the LABEL TABLE (the next
label's address), and is cross-checked against the `hex.vec N` width declared in CHECK_SCRATCH_DECLS.
Two independent sources must agree, so widening a vec without re-running this fails the build rather
than silently leaving half a register unrestored.

    python scratchpad/m1_add_globals.py --selftest
"""
import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset                              # noqa: E402
from doomfj.collision import CHECK_SCRATCH_DECLS          # noqa: E402
from doomfj.wall_renderer import HOISTED_SCRATCH_DECLS   # noqa: E402
from doomfj.harness import W                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--labels", default="scratchpad/_m1_labels_current.tsv.gz")
ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

CELL_WORDS = 2          # a hex cell is dw = 2w bits = 2 words


def declared():
    """(name, words|None) for every decl. None = size is symbolic beyond w/dw, so the DERIVED
    extent stands alone and the cross-check is skipped for that one (reported, never silent).

    The hoisted renderer registers carry SYMBOLIC sizes (`hex.vec w/4`, the pointer registers), so
    a numeric-only parser rejects them -- the same gap that silently under-hoisted 12 of them in
    m1_hoist.py. Evaluate w/dw instead of refusing.
    """
    out = []
    for d in list(CHECK_SCRATCH_DECLS) + list(HOISTED_SCRATCH_DECLS):
        m = re.match(r"\s*(\w+)\s*:\s*hex\.vec\s+(.+)", d)
        assert m, "decl is not `name: hex.vec ...`: %r" % d
        size = m.group(2).split(",")[0].strip()
        try:
            cells = int(size, 0)
        except ValueError:
            try:
                cells = int(eval(size, {"__builtins__": {}}, {"w": W, "dw": 2 * W}))
            except Exception:
                cells = None
        out.append((m.group(1), None if cells is None else cells * CELL_WORDS))
    return out


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


def add_globals(doc, sa, sn):
    """Return (doc, added_words). Refuses rather than skipping anything it cannot verify."""
    bits = {n: a * W for a, n in zip(sa, sn)}
    ws = sorted(set(sa))
    have = {e[0] for e in doc["entries"]}
    added = 0
    for name, want_words in declared():
        # CONTROL A: a global the label table does not have is a REFUSAL, never a silent skip --
        # skipping is exactly how a hole gets into the set.
        assert name in bits, ("CHECK_SCRATCH_DECLS names %r but this build's label table does not "
                              "have it -- the set would keep the hole" % name)
        if name in have:
            continue
        base = bits[name] // W
        extent = selfreset._extent(ws, base) - base
        # CONTROL B: DERIVED vs DECLARED must agree (R6). A vec widened in collision.py without
        # re-running this would otherwise leave the tail of the register unrestored.
        if want_words is None:
            print("   (symbolic size, extent-derived only): %s = %d words" % (name, extent))
        assert want_words is None or extent == want_words, (
            "%s spans %d words in the label table but CHECK_SCRATCH_DECLS declares hex.vec -> %d "
            "words. The two sources disagree; a baked count here would silently leave part of the "
            "register unrestored." % (name, extent, want_words))
        doc["entries"].append([name] + list(range(extent)))
        added += extent
    doc["entries"] = sorted(doc["entries"])
    doc["labels"] = len(doc["entries"])
    # ⚠ WORDS IS THE RESOLVED UNION, NOT THE SUM OF OFFSETS. ca_remap_set emits OVERLAPPING entries
    # by design (it takes the superset where the old->new mapping is ambiguous), so summing
    # over-counts and load_restore_set's `len(out) == doc["words"]` assert would fire.
    resolved = set()
    for e in doc["entries"]:
        b = bits[e[0]] // W
        resolved.update(b + off for off in e[1:])
    doc["words"] = len(resolved)
    doc["layout_fingerprint"] = selfreset.layout_fingerprint(doc, bits)
    return doc, added


def refuses(fn):
    try:
        fn()
    except AssertionError:
        return True
    return False


if args.selftest:
    # Synthetic, so a clean checkout can run it (CR round 2's lesson, applied here from the start).
    names = [n for n, _w in declared()]
    widths = dict(declared())
    sa, sn, base = [], [], 1000
    for n in names:
        sa.append(base); sn.append(n); base += widths[n]
    sa.append(base); sn.append("zzz_end")
    doc = {"format": "label+offset", "words": 0, "labels": 0, "entries": [["zzz_end", 0]]}
    got, added = add_globals(json.loads(json.dumps(doc)), sa, sn)
    ok = added == sum(widths.values())
    print("P  all %d globals added at declared width -> %s (%d words)"
          % (len(names), "ok" if ok else "!! MISMATCH", added))

    # C1: a global missing from the label table must REFUSE, not skip.
    k = sn.index(names[3])
    c1 = refuses(lambda: add_globals(json.loads(json.dumps(doc)),
                                     sa[:k] + sa[k+1:], sn[:k] + sn[k+1:]))
    print("C1 global absent from label table   -> %s" % ("refused ok" if c1 else "!! SKIPPED"))

    # C2: a label extent that disagrees with the declared width must REFUSE.
    sa2 = list(sa); sa2[1] += 2          # widen names[0], so its extent != declared
    c2 = refuses(lambda: add_globals(json.loads(json.dumps(doc)), sa2, sn))
    print("C2 extent != declared hex.vec width -> %s" % ("refused ok" if c2 else "!! ACCEPTED"))

    good = ok and c1 and c2
    print("SELFTEST: %s" % ("PASS" if good else "!! FAIL"))
    sys.exit(0 if good else 1)

sa, sn = read_labels(args.labels)
doc = json.load(gzip.open(args.set, "rt", encoding="utf-8"))
before = doc["words"]
doc, added = add_globals(doc, sa, sn)
doc["generated_by"] = ("scratchpad/ca_remap_set.py --labels %s   then   "
                       "scratchpad/m1_add_globals.py --labels %s" % (args.labels, args.labels))
json.dump(doc, gzip.open(args.out, "wt", encoding="utf-8"))
print("added %d words over %d globals (%d check + %d hoisted)"
      % (added, len(declared()), len(CHECK_SCRATCH_DECLS), len(HOISTED_SCRATCH_DECLS)))
print("%s: %d -> %d words over %d entries" % (args.out, before, doc["words"], doc["labels"]))
