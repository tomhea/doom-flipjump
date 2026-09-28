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

A LABEL WHOSE SPAN CHANGED (M7 P1.5). Offsets are relative to their label, so a re-key keeps them --
but an array sized by the map moves its END. P1.5 took the multiplayer-only things out of the image,
and the runtime things' `thpos_rt` / `thss_rt` went from 75 things to 68 (2,400 -> 2,176 words):
the old offsets past the new end point into the next label, which selfreset.load_restore_set
refuses. The other direction is worse: an array that GREW passes every check with its new words
missing -- a hole, and a hole HANGS the next frame. So the re-key reads the label table the set was
keyed on (`--old-labels`, held to the set's own `labels_sha256`) and compares every entry's span:
  * a label the set held WHOLE -- offsets exactly 0 .. its old span - 1 -- is held whole at its new
    span: it is one array of one kind of cell, so all of it is still the set's;
  * a label held IN PART whose span changed is REFUSED -- which of its words need restoring is not
    a function of the old offsets. Re-derive the set instead.

    python scratchpad/ca_remap_set.py --labels L --old-labels <the table the set was keyed on>
    python scratchpad/ca_remap_set.py --selftest
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
from doomfj import selfreset          # noqa: E402
from doomfj.harness import W          # noqa: E402


def read_labels(path):
    labels = {}
    for line in gzip.open(path, "rt", encoding="utf-8"):
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            labels.setdefault(a, int(v))
    return labels


def spans(labels):
    """name -> its span in words, bounded exactly as selfreset.load_restore_set bounds an offset:
    up to the next label's word, and the highest label one cell"""
    base = {k: v // W for k, v in labels.items()}
    addrs = sorted(set(base.values()))

    def span(name):
        b = base[name]
        i = bisect.bisect_right(addrs, b)
        return (addrs[i] - b) if i < len(addrs) else 2
    return span


def check_old_labels(doc, path):
    """the table `--old-labels` names must be the one the set was keyed on -- the set records it"""
    got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert got == doc.get("labels_sha256"), (
        "re-key REFUSED: --old-labels %s is not the table this set was keyed on (sha256 %s, the "
        "set records %s)" % (path, got[:16], str(doc.get("labels_sha256"))[:16]))


def resize_whole(rows, ent, old_span, new_span):
    """rows: (old name, new name) per entry. Returns (entries, resized, refused): an entry keeps its
    offsets while its label's span is unchanged; a label held WHOLE at its old span is held whole at
    its new one; a label held IN PART whose span changed is refused."""
    entries, resized, refused = [], [], []
    for o, n in rows:
        offs, so, sn = ent[o], old_span(o), new_span(n)
        if so == sn:
            entries.append([n] + offs)
        elif sorted(set(offs)) == list(range(so)):
            entries.append([n] + list(range(sn)))
            resized.append((n, so, sn))
        else:
            refused.append((n, so, sn, len(offs)))
    return entries, resized, refused


def remap(doc, labels, old_labels):
    """the re-keyed entries and what happened to them"""
    ent = {e[0]: list(e[1:]) for e in doc["entries"]}
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

    rows = [(n, n) for n in present]
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
        # WHEN THE MAPPING IS AMBIGUOUS, TAKE THE SUPERSET -- do not guess.
        #
        # A group can have FEWER old labels than candidates: `collision.py` emits three candidate
        # positions (whole step, x-only, y-only), so a macro-local exists in three sibling expansions
        # while the derived set named only one of them. Nothing in the label distinguishes which, and
        # picking wrong would leave the cell that actually needed restoring DIRTY -- and a hole in the
        # restore set does not draw wrong pixels, it HANGS the next frame (handoff-m1-reset.md 4b).
        #
        # Restoring all three is safe in the direction that matters: writing a scratch cell back to its
        # pristine value when it did not need it is a no-op, because pristine is exactly what it should
        # hold at frame start. The cost is a few extra cells. The guards still apply to every one of
        # them -- containment, the byte/nibble split, and the pristine-value check in build.py.
        for o in sorted(olds):
            for c in cands:
                assert o.split("---")[-1] == c.split("---")[-1], (o[-40:], c[-40:])
                rows.append((o, c))
                remapped.append((o, c))

    unknown = sorted({o for o, _ in rows if o not in old_labels})
    assert not unknown, ("re-key REFUSED: the set names %d labels the --old-labels table does not "
                         "have, e.g. %s" % (len(unknown), unknown[:3]))
    entries, resized, refused = resize_whole(rows, ent, spans(old_labels), spans(labels))
    return ent, entries, present, remapped, dropped, resized, refused


def main(args):
    doc = json.load(gzip.open(args.set, "rt", encoding="utf-8"))
    check_old_labels(doc, args.old_labels)
    labels = read_labels(args.labels)
    ent, new_entries, present, remapped, dropped, resized, refused = remap(
        doc, labels, read_labels(args.old_labels))

    print("labels in the set      : %d" % len(ent))
    print("  unchanged            : %d" % len(present))
    print("  re-keyed             : %d" % len(remapped))
    print("  dropped (register gone): %d  %s"
          % (len(dropped), sorted({d.split("---")[-1] for d in dropped})))
    print("  span changed, held whole -> resized: %d  %s"
          % (len(resized), ", ".join("%s %d -> %d" % r for r in resized)))
    assert not refused, (
        "re-key REFUSED: %d labels held IN PART changed their span, e.g. %s (name, old span, new "
        "span, offsets) -- which of their words need restoring is not a function of the old "
        "offsets. Re-derive the set instead." % (len(refused), refused[:3]))

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
               "generated_by": "scratchpad/ca_remap_set.py --labels %s --old-labels %s"
                               % (args.labels, args.old_labels)}
    payload["layout_fingerprint"] = selfreset.layout_fingerprint(payload, labels)

    old_words = doc["words"]
    print("words: %s -> %s  (delta %+d)  negative = a dropped register or a shrunk array; positive ="
          % (format(old_words, ","), format(len(words), ","), len(words) - old_words))
    print("      a grown array, or the superset taken where the old->new mapping was ambiguous --")
    print("      see the comments above.")

    tmp = Path(args.out).with_suffix(".probe.gz")
    json.dump(payload, gzip.open(tmp, "wt", encoding="utf-8"))
    got = selfreset.load_restore_set(tmp, labels)          # full production path, check_layout=True
    assert got == words, "the production loader disagrees with this script"
    print("production loader accepts it: %s words, layout fingerprint %s"
          % (format(len(got), ","), payload["layout_fingerprint"][:16]))
    tmp.unlink()
    json.dump(payload, gzip.open(args.out, "wt", encoding="utf-8"))
    print("wrote %s" % args.out)


def selftest():
    """synthetic label tables: an array held whole that shrinks and one that grows are resized whole;
    the NEGATIVE CONTROLS -- a label held in part whose span changed, an array held whole but for
    one word, a wrong --old-labels table -- must each be refused"""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print("%s  %s%s" % ("PASS" if cond else "FAIL", name, ("  -- " + detail) if detail else ""))

    def table(**words):
        return {k: v * W for k, v in words.items()}

    old = table(a=0, arr=10, part=2410, tail=2430)             # spans: a 10, arr 2400, part 20
    ent = {"a": [0, 1], "arr": list(range(2400)), "part": [0, 3, 7], "tail": [0]}
    rows = [(n, n) for n in ent]

    def run(new, ent=ent):
        return resize_whole(rows, ent, spans(old), spans(new))

    e, resized, refused = run(table(a=0, arr=10, part=2186, tail=2206))
    got = {x[0]: x[1:] for x in e}
    check("C1 an array held whole that SHRANK is held whole at its new span",
          not refused and resized == [("arr", 2400, 2176)] and got["arr"] == list(range(2176))
          and got["a"] == [0, 1] and got["part"] == [0, 3, 7], "%s %s" % (resized, refused))
    e, resized, refused = run(table(a=0, arr=10, part=2610, tail=2630))
    got = {x[0]: x[1:] for x in e}
    check("C2 an array held whole that GREW is held whole at its new span -- no hole",
          not refused and resized == [("arr", 2400, 2600)] and got["arr"] == list(range(2600)),
          "%s %s" % (resized, refused))
    e, resized, refused = run(table(a=0, arr=10, part=2410, tail=2435))
    check("C3 (negative control) a label held IN PART whose span changed is refused",
          refused == [("part", 20, 25, 3)] and not resized, "%s %s" % (resized, refused))
    ent4 = dict(ent, arr=list(range(2399)))
    e, resized, refused = run(table(a=0, arr=10, part=2186, tail=2206), ent4)
    check("C4 (negative control) an array held whole but for its last word is refused, not resized",
          refused == [("arr", 2400, 2176, 2399)] and not resized, "%s %s" % (resized, refused))
    e, resized, refused = run(dict(old))
    check("C5 an unchanged layout resizes nothing and refuses nothing",
          not resized and not refused and [x[1:] for x in e] == [ent[n] for n in ent])
    with tempfile.TemporaryDirectory() as t:
        right, wrong = Path(t) / "right.tsv.gz", Path(t) / "wrong.tsv.gz"
        right.write_bytes(b"right table")
        wrong.write_bytes(b"another table")
        doc = {"labels_sha256": hashlib.sha256(b"right table").hexdigest()}
        check_old_labels(doc, right)
        try:
            check_old_labels(doc, wrong)
            refused_wrong = False
        except AssertionError:
            refused_wrong = True
        check("C6 (negative control) an --old-labels table the set was not keyed on is refused",
              refused_wrong)
    print("ca_remap_set selftest -- C3, C4 and C6 are the negative controls: %s"
          % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="scratchpad/_ca_labels.tsv.gz")
    ap.add_argument("--old-labels", help="the label table the set was keyed on (its sha256 is the "
                                         "set's labels_sha256)")
    ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
    ap.add_argument("--out", default="src/doomfj/data/m1_restore_set.json.gz")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(selftest())
    if not a.old_labels:
        ap.error("--old-labels is required: the span check needs the table the set was keyed on")
    main(a)
