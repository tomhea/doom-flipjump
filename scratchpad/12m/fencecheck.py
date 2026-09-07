"""Every line inside a ``` fence must exist in a committed log. Nothing else is evidence.

WHY THIS EXISTS. Four CR rounds on PR #84 found four fabricated or altered transcripts:

  * the R1 fences on PR #83   -- formatted as `$ cmd` runs; no command produced that output
  * `486 passed ... (all seven instrument selftests PASS)` -- pytest printed no such thing,
    and it is 13 scripts with a --selftest, not seven
  * `M2 STANDALONE GATE: PASS -- 45/45 byte-exact, door across two resets` -- the tool prints
    something else entirely, and the real count is 43 BYTE-EXACT rows of 45 presented frames
  * a hand-written mutation summary table inside a fence, tidier than the real --selftest output

Every one was a RECONSTRUCTION of what the tool was believed to have said, and every one read as
more precise than the truth. Adopting a rule against it did not stop the next one; diffing against
files did. So this is the diff, as a command.

    python scratchpad/12m/fencecheck.py <doc-or-body.md> [--logs scratchpad/12m]
    python scratchpad/12m/fencecheck.py --selftest

A line is accepted if it appears verbatim in some log under --logs, or is a shell prompt (`$ ...`),
a comment (`# ...`), or a fence-language marker. Anything else is reported; exit 1 if any remain.
"""
import argparse
import os
import sys
from pathlib import Path

SKIP_PREFIXES = ("$", "#", "//")


def fenced_lines(text):
    """[(line_number, line)] for every content line inside a ``` fence"""
    out, inside = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            out.append((i, line))
    return out


def load_logs(dirs):
    blobs = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix in (".log", ".txt"):
                try:
                    blobs[str(f)] = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
    return blobs


def audit(text, blobs):
    """returns [(lineno, line)] for fenced lines found in no log"""
    missing = []
    for n, line in fenced_lines(text):
        t = line.strip()
        if not t or t.startswith(SKIP_PREFIXES):
            continue
        if any(t in b for b in blobs.values()):
            continue
        missing.append((n, t))
    return missing


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-56s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("fencecheck selftest -- a checker that accepts anything checks nothing")
    logs = {"a.log": "SELFTEST PASS\nM2 STANDALONE GATE: PASS -- the shipped binary opens a door\n"}

    doc_ok = "text\n```\nSELFTEST PASS\n```\n"
    check("C1 a line present in a log is ACCEPTED", audit(doc_ok, logs) == [])

    doc_bad = "text\n```\nSELFTEST PASS -- 45/45 byte-exact\n```\n"
    m = audit(doc_bad, logs)
    check("C2 an ALTERED line is REJECTED", len(m) == 1, m[0][1][:44] if m else "")

    doc_cmd = "```\n$ python x.py\nSELFTEST PASS\n```\n"
    check("C3 a shell prompt is not treated as output", audit(doc_cmd, logs) == [])

    doc_out = "outside a fence: 45/45 byte-exact, invented\n"
    check("C4 prose OUTSIDE a fence is not checked (that is a different problem)",
          audit(doc_out, logs) == [])

    check("C5 an empty log set rejects everything (the checker cannot pass vacuously)",
          len(audit(doc_ok, {})) == 1)

    # the real fabrication this tool was written for
    real = "```\nM2 STANDALONE GATE: PASS -- 45/45 byte-exact, door across two resets\n```\n"
    m = audit(real, logs)
    check("C6 the actual PR #84 fabrication is caught", len(m) == 1,
          m[0][1][:52] if m else "NOT CAUGHT")

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", nargs="?")
    ap.add_argument("--logs", action="append", default=None,
                    help="directory of .log/.txt files (repeatable)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.doc:
        ap.error("give a document, or --selftest")
    blobs = load_logs(a.logs or ["scratchpad/12m", "scratchpad"])
    if not blobs:
        print("no logs loaded -- every fenced line would be reported; check --logs")
        return 2
    text = Path(a.doc).read_text(encoding="utf-8", errors="replace")
    missing = audit(text, blobs)
    print("%s: %d fenced line(s) in no log, against %d log file(s)"
          % (a.doc, len(missing), len(blobs)))
    for n, t in missing:
        print("  line %-5d NOT IN ANY LOG: %s" % (n, t[:96]))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
