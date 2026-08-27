"""Re-emit the M1 reset part against an ALREADY-BUILT image and compare it to a reference.

WHY THIS EXISTS. When a change touches selfreset.py but provably cannot change what it emits, the
honest way to say so is to re-run the emitter and diff the bytes -- not to argue it. CR round 2 was
right that the first time I did this the script lived in /tmp, so nothing in the tree recorded the
comparison and the claim was argued after all.

It is also the cheap pre-check before committing to a ~76-minute rebuild: emit the part, see whether
it differs and by how much, and only then decide.

    python scratchpad/m1_reemit.py --fjm build/doom_e1m1_loop.fjm \
        --ref build/generated_loop/e1m1_07_reset.fj

CONTROL (R9): --selftest re-emits TWICE, mutating the restore set in between, and requires the two
emissions to differ. A comparison that cannot report a difference proves nothing when it reports
sameness.
"""
import argparse
import gzip
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset                                    # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                   # noqa: E402
from doomfj.harness import W                                    # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", default="build/doom_e1m1_loop.fjm")
ap.add_argument("--ref", default="build/generated_loop/e1m1_07_reset.fj")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--set", default="src/doomfj/data/m1_restore_set.json.gz")
ap.add_argument("--view-w", type=int, default=160)
ap.add_argument("--nss", type=int, default=682)
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()


def load_image(path):
    r = FjmRunner(path, flat_max_words=1 << 28)
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, ln in r._segments:
        core.add_segment(s, ln)
    for st, v in r._runs:
        core.set_words(st, v)
    return core


def load_bits(path):
    bits = {}
    for line in gzip.open(path, "rt", encoding="utf-8"):
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            bits.setdefault(a, int(v))
    return bits


def emit(core, bits, setpath):
    """Emit into a throwaway dir. The main-part patch needs only the 3 lines it asserts on, and the
    emitted part does not depend on main at all."""
    tmp = Path(tempfile.mkdtemp(prefix="m1re_"))
    (tmp / "e1m1_02_main.fj").write_text(
        "stl.output_char 0xFF\nstl.loop\nbad: stl.loop\n", encoding="utf-8")
    part, n_nib, n_byte = selfreset.emit_reset_part(
        tmp, bits, core.get_word, setpath, args.view_w, args.nss, "e1m1")
    return part.read_bytes(), n_nib, n_byte


class FakeCore:
    """A pristine image for --selftest: word 1 carries code_start, everything else is a small
    value. emit_reset_part only ever calls get_word, so nothing about a real 85M-word image is
    needed to exercise it."""

    def __init__(self, code_start=100):
        self.code_start = code_start

    def get_word(self, word):
        return self.code_start * W if word == 1 else 0


def synthetic():
    """Inputs for --selftest, built here rather than read from disk.

    CR round 3: this selftest defaulted to build/doom_e1m1_loop.fjm and a 48 MB untracked labels
    file, so the fix for round 2 died in open() on a clean checkout -- the very defect it was
    answering. The control is about whether this script can SEE a difference, and that does not
    depend on whose program the labels describe.
    """
    bits = {"sshead": 200 * W, "pclm": 212 * W, "sfflag": 216 * W,
            "scratch": 220 * W, "zzz_end": 226 * W}
    doc = {"format": "label+offset", "words": 20, "labels": 4,
           "entries": [["pclm", 0, 1, 2, 3], ["scratch", 0, 1, 2, 3, 4, 5],
                       ["sfflag", 0, 1, 2, 3], ["sshead", 0, 1, 2, 3, 4, 5]],
           "source_sha256": "selftest", "labels_sha256": "selftest", "generated_by": "selftest"}
    tmp = Path(tempfile.mkdtemp(prefix="m1re_")) / "set.json.gz"
    json.dump(doc, gzip.open(tmp, "wt", encoding="utf-8"))
    return FakeCore(), bits, tmp, doc, 2, 3


if args.selftest:
    core, bits, setpath, doc, args.view_w, args.nss = synthetic()
    print("SELFTEST inputs are synthetic (no built binary, no scratchpad artifacts needed)")
    a, n1, b1 = emit(core, bits, setpath)
    # CONTROL: drop one label's offsets; the emission MUST change.
    victim = "scratch"
    doc = dict(doc, entries=[e for e in doc["entries"] if e[0] != victim])
    doc["words"] = sum(len(e) - 1 for e in doc["entries"])
    tmp2 = Path(tempfile.mkdtemp(prefix="m1re_")) / "mut.json.gz"
    json.dump(doc, gzip.open(tmp2, "wt", encoding="utf-8"))
    b, n2, b2 = emit(core, bits, tmp2)
    ok = a != b and n2 < n1
    print("  as given            : %s (%d nibble cells)" % (hashlib.sha256(a).hexdigest()[:16], n1))
    print("  %-20s: %s (%d nibble cells)" % ("without " + victim, hashlib.sha256(b).hexdigest()[:16], n2))
    print("  CONTROL: dropping a label changes the emission: %s"
          % ("ok" if ok else "!! IDENTICAL - this script cannot see a difference"))
    print("SELFTEST: %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

core = load_image(args.fjm)
bits = load_bits(args.labels)

new, n_nib, n_byte = emit(core, bits, args.set)
ref = Path(args.ref).read_bytes()
print("re-emitted : %s  (%d nibble cells, %d byte cells, %d lines)"
      % (hashlib.sha256(new).hexdigest()[:24], n_nib, n_byte, new.count(b"\n")))
print("reference  : %s  (%s, %d lines)"
      % (hashlib.sha256(ref).hexdigest()[:24], args.ref, ref.count(b"\n")))
print("=> %s" % ("IDENTICAL -- the built binary already matches this code"
                 if new == ref else "DIFFERS -- a rebuild is required"))
sys.exit(0 if new == ref else 2)
