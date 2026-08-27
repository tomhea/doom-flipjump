"""M5 — derive the STANDALONE restore set from the certified hosted one.

    python scratchpad/ca_labels.py --standalone --out scratchpad/_m5_labels_std.tsv.gz
    python scratchpad/m5_setfile.py --labels scratchpad/_m5_labels_std.tsv.gz
    python scratchpad/m5_setfile.py --selftest        # R9: the negative controls

THE RULE THIS OBEYS: **re-key the set, never re-derive it from a measurement.** A measured set has
holes by construction, and a hole in the restore set does not draw wrong pixels -- it HANGS the
next frame. So the certified 448-entry set is the input, and the only edits are the two the
standalone tier actually makes to the program:

  * `wmagic` is GONE. There is no wire, so there is no magic byte to check. Its entry is dropped,
    and the list of names allowed to disappear is CLOSED (`EXPECTED_GONE`) -- anything else
    vanishing is a refusal, because a silently dropped label is exactly how a hole gets in.
  * six new globals ARRIVE: the keyboard poll's scratch and the four held-key flags
    (`wall_renderer.STANDALONE_SCRATCH_DECLS`). They are added at FULL extent, cross-checked
    against the widths declared there, the same way m1_add_globals.py does it.

Everything else about the two programs' data layout is identical -- consecutive `hex.vec`
declarations, so each label's span is its own declared width -- and this script proves that rather
than assuming it: every surviving offset is re-checked against its label's extent in the STANDALONE
table before the fingerprint is recomputed.

⚠ AND THE PERSIST SET IS CHECKED HERE TOO. `build.STANDALONE_PERSIST` names the labels the reset
must leave alone, and `selfreset.emit_reset_part` asserts each one is IN the set (a persist label
the frame never dirties is a typo). Checking it at set-build time turns that from a failure 40
minutes into a build into a failure now.
"""
import argparse
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                   # noqa: E402
from doomfj.build import STANDALONE_PERSIST                    # noqa: E402
from doomfj.harness import W                                   # noqa: E402
from doomfj.selfreset import decl_words                        # noqa: E402
from doomfj.wall_renderer import STANDALONE_SCRATCH_DECLS      # noqa: E402

# The ONLY labels the standalone program is allowed to lack. `wmagic` is the binary wire's magic
# byte; the standalone tier reads no wire. Closed on purpose: see the module docstring.
EXPECTED_GONE = frozenset({"wmagic"})


def read_labels(path):
    """the label table as (addresses, names), sorted by address."""
    addresses, names = [], []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            name, tab, value = line.rstrip("\n").partition("\t")
            if tab:
                addresses.append(int(value) // W)
                names.append(name)
    order = sorted(range(len(addresses)), key=lambda i: addresses[i])
    return [addresses[i] for i in order], [names[i] for i in order]


def derive(doc, addresses, names):
    """Return (doc, dropped, added_words). Refuses rather than skipping anything it cannot verify."""
    bits = {}
    for address, name in zip(addresses, names):
        bits.setdefault(name, address * W)
    sorted_words = sorted(set(addresses))

    # ---- 1. what the standalone program no longer has -------------------------------------
    gone = sorted({e[0] for e in doc["entries"]} - set(bits))
    assert set(gone) == set(EXPECTED_GONE), (
        "the standalone build is missing %r from the certified set, but only %r is allowed to "
        "disappear. A label that vanishes unnoticed leaves a HOLE, and a hole hangs the next "
        "frame." % (gone, sorted(EXPECTED_GONE)))
    doc["entries"] = [e for e in doc["entries"] if e[0] in bits]

    # ---- 2. every surviving offset must still fit its label ---------------------------------
    # The same containment `load_restore_set` enforces at build time, done here so a layout the
    # standalone tier shifted fails NOW rather than an hour into a build.
    escaped = []
    for entry in doc["entries"]:
        base = bits[entry[0]] // W
        span = selfreset._extent(sorted_words, base) - base
        escaped += [(entry[0], off, span) for off in entry[1:] if off >= span]
    assert not escaped, (
        "%d offsets run past the end of their label in the STANDALONE layout, e.g. %s "
        "(name, offset, span) -- the two programs do not lay those labels out the same way, so "
        "this set does not describe the standalone one" % (len(escaped), escaped[:3]))

    # ---- 3. the globals the standalone tier ADDS -------------------------------------------
    have = {e[0] for e in doc["entries"]}
    added = 0
    for name, declared_words in (decl_words(d) for d in STANDALONE_SCRATCH_DECLS):
        assert name in bits, (
            "STANDALONE_SCRATCH_DECLS names %r but the standalone label table does not have it -- "
            "the emitter and this script disagree about what the tier declares" % name)
        if name in have:
            continue
        base = bits[name] // W
        extent = selfreset._extent(sorted_words, base) - base
        assert declared_words is None or extent == declared_words, (
            "%s spans %d words in the label table but STANDALONE_SCRATCH_DECLS declares %d. The "
            "two sources disagree; trusting either alone would leave part of the register "
            "unrestored." % (name, extent, declared_words))
        doc["entries"].append([name] + list(range(extent)))
        added += extent

    # ---- 4. the persist set has to be IN the set -------------------------------------------
    present = {e[0] for e in doc["entries"]}
    absent = [n for n in STANDALONE_PERSIST if n not in present]
    assert not absent, (
        "build.STANDALONE_PERSIST names %r, which the set does not carry. emit_reset_part would "
        "refuse an hour into the build; refuse here instead." % absent)

    # ---- 5. re-count and re-fingerprint ------------------------------------------------------
    doc["entries"] = sorted(doc["entries"])
    doc["labels"] = len(doc["entries"])
    # WORDS IS THE RESOLVED UNION, not the sum of offsets: the certified set carries overlapping
    # entries by design (ca_remap_set takes the superset for an ambiguous mapping).
    resolved = set()
    for entry in doc["entries"]:
        base = bits[entry[0]] // W
        resolved.update(base + off for off in entry[1:])
    doc["words"] = len(resolved)
    doc["layout_fingerprint"] = selfreset.layout_fingerprint(doc, bits)
    return doc, gone, added


def refuses(fn):
    try:
        fn()
    except AssertionError:
        return True
    return False


def selftest():
    """A synthetic label table, so a clean checkout can run this without a 40-minute build."""
    widths = dict(decl_words(d) for d in STANDALONE_SCRATCH_DECLS)
    layout = [("viewx", 16), ("viewy", 16), ("viewangle", 16), ("pkeys", 4)]
    layout += [decl_words(d) for d in STANDALONE_SCRATCH_DECLS]
    addresses, names, base = [], [], 1000
    for name, words in layout:
        addresses.append(base); names.append(name); base += words
    addresses.append(base); names.append("zzz_end")

    def doc():
        entries = [[n, *range(w)] for n, w in layout if not n.startswith("kb")]
        entries.append(["wmagic", 0, 1, 2, 3])          # the label the standalone tier drops
        return {"format": "label+offset", "words": 0, "labels": 0, "entries": entries}

    got, gone, added = derive(doc(), addresses, names)
    ok = (gone == ["wmagic"] and added == sum(widths.values())
          and all(n in {e[0] for e in got["entries"]} for n in STANDALONE_PERSIST))
    print("P  wmagic dropped, %d globals added at declared width, persist set present -> %s"
          % (len(widths), "ok" if ok else "!! MISMATCH"))

    # C1: a label vanishing that is NOT on the allowed list must refuse.
    k = names.index("pkeys")
    c1 = refuses(lambda: derive(doc(), addresses[:k] + addresses[k + 1:], names[:k] + names[k + 1:]))
    print("C1 an unexpected label vanishes      -> %s" % ("refused ok" if c1 else "!! DROPPED SILENTLY"))

    # C2: a persist label missing from the SET (not the table) must refuse.
    def without_viewangle():
        d = doc()
        d["entries"] = [e for e in d["entries"] if e[0] != "viewangle"]
        return derive(d, addresses, names)
    c2 = refuses(without_viewangle)
    print("C2 a persist label not in the set    -> %s" % ("refused ok" if c2 else "!! ACCEPTED"))

    # C3: a label extent that disagrees with the declared width must refuse.
    wide = list(addresses)
    kb = names.index("kbstat")
    for i in range(kb + 1, len(wide)):
        wide[i] += 2
    c3 = refuses(lambda: derive(doc(), wide, names))
    print("C3 extent != declared hex.vec width  -> %s" % ("refused ok" if c3 else "!! ACCEPTED"))

    # C4: an offset that runs past its label must refuse.
    def escaping():
        d = doc()
        d["entries"][0] = [d["entries"][0][0], *range(64)]
        return derive(d, addresses, names)
    c4 = refuses(escaping)
    print("C4 an offset escapes its label       -> %s" % ("refused ok" if c4 else "!! ACCEPTED"))

    good = ok and c1 and c2 and c3 and c4
    print("SELFTEST: %s" % ("PASS" if good else "!! FAIL"))
    return 0 if good else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
    ap.add_argument("--labels", default="scratchpad/_m5_labels_std.tsv.gz")
    ap.add_argument("--out", default="src/doomfj/data/m5_restore_set.json.gz")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    addresses, names = read_labels(args.labels)
    doc = json.load(gzip.open(args.set, "rt", encoding="utf-8"))
    before = (doc["words"], len(doc["entries"]))
    doc, gone, added = derive(doc, addresses, names)
    doc["generated_by"] = "scratchpad/m5_setfile.py --labels %s --set %s" % (args.labels, args.set)
    json.dump(doc, gzip.open(args.out, "wt", encoding="utf-8"))
    print("dropped %s; added %d words over %d standalone globals"
          % (", ".join(gone) or "nothing", added, len(STANDALONE_SCRATCH_DECLS)))
    print("%s: %d -> %d words over %d -> %d entries"
          % (args.out, before[0], doc["words"], before[1], doc["labels"]))
    print("persist: %s" % ", ".join(STANDALONE_PERSIST))
    return 0


if __name__ == "__main__":
    sys.exit(main())
