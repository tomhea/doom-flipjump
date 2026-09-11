"""Capture the FULL label table, including everything emitted in PASS 2.

`scratchpad/ca_labels.py` hooks `labels_resolve` and aborts at `emit_reset_part`, so it returns
PASS-1 labels only. That is cheap and it is what the restore-set tooling needs -- but it leaves the
whole pass-2 region unlabelled, and `hotpath` then has nothing to attribute those ops to.

That hole is not small. On the rung-0 binary, **9,726,044 ops of an 80,111,139-op two-frame walk
(12.14%) execute ABOVE the highest pass-1 label** -- in words 42,036,802..51,377,722, where the M1
self-reset part is emitted. Before the over-attribution guard those ops were silently credited to
`distscale`, the last top-level label, which is how FINDINGS AY came to claim a 12.14% macro that
did not exist (see BA).

This lets the build run to completion and captures labels from the LAST `labels_resolve` call, so
the reset part is included.

    python scratchpad/12m/labels2.py --out scratchpad/12m/_full_labels.tsv.gz
"""
import argparse
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def selftest():
    """R9. This is a CAPTURE tool -- its only claim is "these labels came from THIS build" -- so the
    control is that the provenance it stamps round-trips and that a different binary is detectable.
    CR-2026-09-07 blocked on this file having no control while FINDINGS BB rests entirely on it."""
    import gzip as gz, hashlib, tempfile
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hotpath import LabelTable, provenance_of
    fails = []

    def check(n, c, d=""):
        print("  %-54s %s%s" % (n, "ok" if c else "FAIL", ("  " + d) if d else ""), flush=True)
        if not c:
            fails.append(n)

    print("labels2 selftest -- a capture tool's claim is its PROVENANCE", flush=True)
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        fjm = t / "fake.fjm"
        fjm.write_bytes(b"not-a-real-fjm-but-hashable")
        sha = hashlib.sha256(fjm.read_bytes()).hexdigest()
        out = t / "l.tsv.gz"
        with gz.open(out, "wt", encoding="utf-8") as fh:
            fh.write("# fjm=" + str(fjm) + chr(10) + "# sha256=" + sha + chr(10)
                     + "# tier=game" + chr(10) + "lbl" + chr(9) + "64" + chr(10))
        pv = provenance_of(out)
        check("C1 the header carries the fjm and its sha256",
              pv.get("sha256") == sha and "fjm" in pv, str(pv)[:38])
        check("C2 a DIFFERENT binary's sha does not match",
              pv.get("sha256") != hashlib.sha256(b"other-binary").hexdigest())
        check("C3 the header does not become a label", LabelTable.load(out).names == ["lbl"],
              str(LabelTable.load(out).names))
        bare = t / "bare.tsv.gz"
        with gz.open(bare, "wt", encoding="utf-8") as fh:
            fh.write("lbl" + chr(9) + "64" + chr(10))
        check("C4 a file with NO provenance reports none (not a false match)",
              provenance_of(bare) == {}, str(provenance_of(bare)))
    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)), flush=True)
    return 1 if fails else 0



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="scratchpad/12m/_full_labels.tsv.gz")
    ap.add_argument("--fjm", default="build/labels2_scratch.fjm")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    import flipjump.assembler.assembler as asm
    from doomfj.build import build_wall_renderer

    grabbed = {}
    real = asm.labels_resolve

    def hook(ops, labels, memory_width, fjm_writer, **k):
        # keep the LAST call's labels -- pass 2 includes the reset part
        grabbed["labels"] = labels
        grabbed["mw"] = memory_width
        grabbed["n"] = grabbed.get("n", 0) + 1
        return real(ops, labels, memory_width, fjm_writer, **k)

    asm.labels_resolve = hook
    t0 = time.time()
    print("building the game tier to completion (both passes) ...", flush=True)
    try:
        build_wall_renderer(ROOT / a.fjm, tier="game")
    finally:
        asm.labels_resolve = real

    labels = grabbed.get("labels")
    if not labels:
        print("NO LABELS CAPTURED -- labels_resolve never ran", flush=True)
        return 1
    print("labels_resolve ran %d time(s); kept the last" % grabbed["n"], flush=True)

    out = ROOT / a.out
    n = 0
    # PROVENANCE. Without this the join key can only be checked by a drop-rate PROXY, which is
    # exactly what CR-2026-09-07 flagged. A `#` line is skipped by LabelTable.load: additive.
    import hashlib
    _fjm = ROOT / a.fjm
    _sha = hashlib.sha256(_fjm.read_bytes()).hexdigest() if _fjm.exists() else "no-fjm"
    with gzip.open(out, "wt", encoding="utf-8", newline="\n") as fh:
        fh.write("# fjm=" + str(a.fjm) + chr(10) + "# sha256=" + _sha + chr(10) + "# tier=game" + chr(10))
        for name, v in labels.items():
            try:
                addr = int(v)
            except (TypeError, ValueError):
                try:
                    addr = int(v.value)
                except (AttributeError, TypeError, ValueError):
                    continue
            fh.write("%s\t%d\n" % (name, addr))
            n += 1
    print("pass 2 in %ds: %s labels -> %s (%.1f MB)"
          % (int(time.time() - t0), format(n, ","), a.out, out.stat().st_size / 1e6), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
