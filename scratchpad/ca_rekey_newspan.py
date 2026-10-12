"""Re-key the M1 restore set onto a new label table WITHOUT the table it was keyed on (M7 P10, 2026-10-12).

WHY THIS EXISTS. ca_remap_set.py needs --old-labels -- the table the set was keyed on, whose sha256 the set
records -- to see which labels changed their span between the two programs. P9's table
(scratchpad/_ca_labels_p9.tsv.gz) did not survive its worktree, and ca_labels.py writes its gzip with a
timestamp in the header, so a re-capture cannot reproduce the recorded hash.

WHAT IT CAN DECIDE WITHOUT IT. Every entry of the shipped set holds a CONTIGUOUS PREFIX [0, k) of its
label, and no entry names a macro-expansion path (`f<N>:l<N>:...`), only globals (both asserted). So a
name either exists in the new table or the re-key is refused, and against the new table each entry is
one of:

    covered   k == the label's new span: kept as is. Every word of the label is restored after the
              re-key, exactly the words [0, k) it restored before -- no new hole, no new write.
    part      k <  the new span: REFUSED unless the entry is named --whole NAME (restore the new span:
              the label grew, and its new words are scratch like its old ones) or --keep NAME (keep
              [0, k): the label was held in part on purpose and its span did not change).
    past      k >  the new span: REFUSED unless named --whole NAME (the label shrank; restore its new
              span). --keep is refused here: its offsets would run past the label.

A decision is a human's; each one is printed and recorded in `generated_by`. A re-key where every entry
is `covered` needs none. --old-fingerprint-table T (optional) is a re-captured old table: when the SET's
own layout_fingerprint recomputed on T matches the recorded one, T has the old spans of every label the set
names, and an entry that was held whole there and is `part`/`past` here is resized whole automatically --
ca_remap_set.py's rule, with the fingerprint in place of the file hash.

    python scratchpad/ca_rekey_newspan.py --labels NEW --set S --out O [--whole N]... [--keep N]...
    python scratchpad/ca_rekey_newspan.py --selftest

R9: --selftest builds a synthetic set and table. covered entries are kept; a `part` and a `past` entry are
REFUSED without a decision (the negative controls); --whole resizes them; --keep on a `past` entry is
refused; a name the new table lacks is refused; an entry that is not a contiguous prefix is refused; an
old table whose fingerprint does not match the set's is refused.
"""
import argparse
import bisect
import gzip
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset                    # noqa: E402
from doomfj.harness import W                    # noqa: E402


def read_labels(path):
    labels = {}
    for line in gzip.open(path, "rt", encoding="utf-8"):
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            labels.setdefault(a, int(v))
    return labels


def spans(labels):
    """name -> its span in words, bounded as selfreset.load_restore_set bounds an offset"""
    base = {k: v // W for k, v in labels.items()}
    addrs = sorted(set(base.values()))

    def span(name):
        b = base[name]
        i = bisect.bisect_right(addrs, b)
        return (addrs[i] - b) if i < len(addrs) else 2
    return span


def classify(doc, labels, whole=(), keep=(), old_labels=None):
    """(entries, report) or AssertionError. report: name -> (kind, k, new span, action)"""
    whole, keep = set(whole), set(keep)
    ent = {}
    for e in doc["entries"]:
        name, offs = e[0], list(e[1:])
        assert not re.match(r"f\d+:l\d+", name) and "---" not in name, (
            "re-key REFUSED: %r is a macro-expansion label -- re-key it with ca_remap_set.py" % name)
        assert offs == list(range(len(offs))), (
            "re-key REFUSED: %r holds %d offsets that are not the prefix [0, k)" % (name, len(offs)))
        assert name not in ent, "re-key REFUSED: %r appears twice" % name
        ent[name] = len(offs)
    missing = sorted(n for n in ent if n not in labels)
    assert not missing, ("re-key REFUSED: %d labels of the set are gone from the new table, e.g. %s"
                         % (len(missing), missing[:4]))
    stray = sorted((whole | keep) - set(ent))
    assert not stray, "re-key REFUSED: decisions name labels the set does not have: %s" % stray
    both = sorted(whole & keep)
    assert not both, "re-key REFUSED: --whole and --keep both name %s" % both
    old_span = None
    if old_labels is not None:
        got = selfreset.layout_fingerprint(doc, old_labels)
        assert got == doc.get("layout_fingerprint"), (
            "re-key REFUSED: the old table's fingerprint of the set's labels is %s, the set records %s -- "
            "it is not the layout the set was keyed on" % (got[:16], str(doc.get("layout_fingerprint"))[:16]))
        old_span = spans(old_labels)
    span = spans(labels)
    entries, report, refused = [], {}, []
    for name, k in sorted(ent.items()):
        sn = span(name)
        kind = "covered" if k == sn else "part" if k < sn else "past"
        if kind == "covered":
            act = "kept"
            n = k
        elif name in whole:
            act, n = "whole (--whole)", sn
        elif name in keep:
            if kind == "past":
                refused.append((name, kind, k, sn, "--keep cannot hold offsets past the label"))
                continue
            act, n = "kept in part (--keep)", k
        elif old_span is not None and old_span(name) == k:
            act, n = "whole (held whole on the fingerprinted old table)", sn
        elif old_span is not None and old_span(name) == sn:
            act, n = "kept in part (span unchanged on the fingerprinted old table)", k
        else:
            refused.append((name, kind, k, sn, "needs --whole or --keep"))
            continue
        entries.append([name] + list(range(n)))
        report[name] = (kind, k, sn, act)
    assert not refused, ("re-key REFUSED: %d entries need a decision: %s" % (
        len(refused), "; ".join("%s %s k=%d span=%d (%s)" % r for r in refused)))
    return entries, report


def payload_for(doc, entries, labels, labels_path, argv):
    words = set()
    for e in entries:
        b = labels[e[0]] // W
        words.update(b + off for off in e[1:])
    p = {"format": "label+offset", "words": len(words), "labels": len(entries), "entries": entries,
         "source_sha256": doc.get("source_sha256", "re-keyed"),
         "labels_sha256": hashlib.sha256(Path(labels_path).read_bytes()).hexdigest(),
         "generated_by": "scratchpad/ca_rekey_newspan.py %s" % " ".join(argv)}
    p["layout_fingerprint"] = selfreset.layout_fingerprint(p, labels)
    return p, words


def main(args, argv):
    doc = json.load(gzip.open(args.set, "rt", encoding="utf-8"))
    labels = read_labels(args.labels)
    old = read_labels(args.old_fingerprint_table) if args.old_fingerprint_table else None
    entries, report = classify(doc, labels, args.whole, args.keep, old)
    kinds = {}
    for name, (kind, k, sn, act) in report.items():
        kinds.setdefault(kind, []).append(name)
    print("labels in the set: %d  covered %d, part %d, past %d"
          % (len(report), len(kinds.get("covered", [])), len(kinds.get("part", [])), len(kinds.get("past", []))))
    for name, (kind, k, sn, act) in sorted(report.items()):
        if kind != "covered":
            print("   %-5s %-28s k=%-5d new span %-5d -> %s" % (kind, name, k, sn, act))
    p, words = payload_for(doc, entries, labels, args.labels, argv)
    print("words: %s -> %s (delta %+d)" % (format(doc["words"], ","), format(len(words), ","),
                                          len(words) - doc["words"]))
    tmp = Path(args.out).with_suffix(".probe.gz")
    json.dump(p, gzip.open(tmp, "wt", encoding="utf-8"))
    got = selfreset.load_restore_set(tmp, labels)           # the production path, check_layout=True
    tmp.unlink()
    assert got == words, "the production loader disagrees with this script"
    print("production loader accepts it: %s words, layout fingerprint %s"
          % (format(len(got), ","), p["layout_fingerprint"][:16]))
    json.dump(p, gzip.open(args.out, "wt", encoding="utf-8"))
    print("wrote %s" % args.out)
    return 0


def selftest():
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print("%s  %s%s" % ("PASS" if cond else "FAIL", name, ("  -- " + detail) if detail else ""))

    def refuses(fn):
        try:
            fn()
        except AssertionError as e:
            return str(e)
        return None

    def table(**words):
        return {k: v * W for k, v in words.items()}

    doc = {"entries": [["a", 0, 1], ["grow", *range(16)], ["shrink", *range(16)], ["inpart", 0, 1, 2, 3],
                       ["same", *range(8)]], "words": 0}
    new = table(a=0, grow=2, shrink=26, inpart=38, same=50, end=58)    # spans: a 2, grow 24, shrink 12,
    # inpart 12, same 8
    e, rep = classify(doc, new, whole=("grow", "shrink"), keep=("inpart",))
    got = {x[0]: x[1:] for x in e}
    check("S1 covered entries are kept; --whole resizes a grown and a shrunk label; --keep keeps a part",
          got["a"] == [0, 1] and got["same"] == list(range(8)) and got["grow"] == list(range(24))
          and got["shrink"] == list(range(12)) and got["inpart"] == [0, 1, 2, 3],
          str({k: v[3] for k, v in rep.items()}))
    r = refuses(lambda: classify(doc, new, whole=("shrink",), keep=("inpart",)))
    check("C1 (negative control) a label that GREW is refused without a decision", r and "grow part" in r, r)
    r = refuses(lambda: classify(doc, new, whole=("grow",), keep=("inpart",)))
    check("C2 (negative control) a label that SHRANK is refused without a decision", r and "shrink past" in r, r)
    r = refuses(lambda: classify(doc, new, whole=("grow",), keep=("inpart", "shrink")))
    check("C3 (negative control) --keep on a shrunk label is refused", r and "--keep cannot" in r, r)
    r = refuses(lambda: classify(doc, table(a=0, grow=2, shrink=26, inpart=38, end=58),
                                 whole=("grow", "shrink"), keep=("inpart",)))
    check("C4 (negative control) a label gone from the new table is refused", r and "gone" in r, r)
    bad = {"entries": doc["entries"] + [["holey", 0, 2]], "words": 0}
    r = refuses(lambda: classify(bad, dict(new, holey=60 * W), whole=("grow", "shrink"), keep=("inpart",)))
    check("C5 (negative control) an entry that is not a contiguous prefix is refused", r and "prefix" in r, r)
    old = table(a=0, grow=2, shrink=18, inpart=34, same=46, end=54)    # grow 16, shrink 16, inpart 12
    fp_doc = dict(doc, layout_fingerprint=selfreset.layout_fingerprint(doc, old))
    e, rep = classify(fp_doc, new, old_labels=old)
    got = {x[0]: x[1:] for x in e}
    check("S2 a fingerprinted old table decides: grow/shrink were whole -> whole, inpart kept in part",
          got["grow"] == list(range(24)) and got["shrink"] == list(range(12)) and got["inpart"] == [0, 1, 2, 3],
          str({k: v[3] for k, v in rep.items()}))
    r = refuses(lambda: classify(fp_doc, new, old_labels=dict(old, end=55 * W)))
    check("C6 (negative control) an old table whose fingerprint differs from the set's is refused",
          r and "fingerprint" in r, r)
    with tempfile.TemporaryDirectory() as t:
        lp = Path(t) / "l.tsv.gz"
        with gzip.open(lp, "wt", encoding="utf-8") as f:
            for k, v in new.items():
                f.write("%s\t%d\n" % (k, v))
        e, _rep = classify(doc, new, whole=("grow", "shrink"), keep=("inpart",))
        p, words = payload_for(doc, e, new, lp, ["--selftest"])
        sp = Path(t) / "s.json.gz"
        json.dump(p, gzip.open(sp, "wt", encoding="utf-8"))
        check("S3 the production loader accepts the written set", selfreset.load_restore_set(sp, new) == words)
    print("ca_rekey_newspan selftest -- C1..C6 are the negative controls: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", help="the NEW label table (ca_labels.py)")
    ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
    ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
    ap.add_argument("--whole", action="append", default=[], metavar="NAME")
    ap.add_argument("--keep", action="append", default=[], metavar="NAME")
    ap.add_argument("--old-fingerprint-table", metavar="T",
                    help="a re-captured old table, accepted when the set's layout_fingerprint matches on it")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    sys.exit(selftest() if a.selftest else main(a, sys.argv[1:]))
