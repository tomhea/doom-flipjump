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

A line is accepted if it appears as a whole line in some TRACKED log under --logs, or is a shell
prompt (`$ ...`) or a comment. Anything else is reported; exit 1 if any remain.

⚠ WHAT THIS DOES NOT SOLVE, and it is the larger half. CR-2026-09-07's structural finding on
PR #84: all 22 findings across six rounds were PROSE claims about completeness or provenance --
"all corrected", "45/45 byte-exact", "checked exactly", a list of commit SHAs that was wrong in
three of four entries. This tool reads only ``` fences (control C4 says so), so it would not have
caught ONE of them.

The `--figures` audit is a partial answer and is ADVISORY, not a gate: it lists comma-formatted
figures that appear in no tracked log, which catches a fabricated number but also flags every
legitimately DERIVED one (a delta, a percentage, a sum). It surfaces candidates for a human to
re-derive; it does not decide. A real answer would re-compute each derived figure from the logs it
cites, and that tool does not exist yet.
"""
import argparse
import os
import re
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


def tracked_files():
    """the set of git-TRACKED paths. CR-2026-09-07: the docstring promised "committed" and
    load_logs never consulted git, so an untracked scratch log counted as evidence."""
    import subprocess
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, timeout=60)
        return {Path(l).as_posix() for l in out.stdout.splitlines() if l.strip()}
    except Exception:                                                  # noqa: BLE001
        return set()


def load_logs(dirs, require_tracked=True):
    """.log/.txt under `dirs`. With require_tracked (the default) ONLY git-tracked files count,
    because an uncommitted log is not evidence a reader can check."""
    keep = tracked_files() if require_tracked else None
    blobs = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.suffix not in (".log", ".txt"):
                continue
            if keep is not None and f.as_posix() not in keep:
                continue
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
        # ⚠ WHOLE-LINE match. `t in b` is a substring test, so a fence with the verdict
        # `(target <= 20,000,000)  OVER` stripped off still "matched" -- CR-2026-09-07 proved it
        # reports 0 findings on exactly that mutilation.
        if any(t in {ln.strip() for ln in b.splitlines()} for b in blobs.values()):
            continue
        missing.append((n, t))
    return missing


FIGURE = re.compile(r"(?<![\d,[])\d{1,3}(?:,\d{3})+\b")


def audit_figures(text, blobs):
    """Every comma-formatted figure ANYWHERE in the document -- prose included -- must appear in a
    log.

    ⚠ THIS, not the fence check, is the one that matters. CR-2026-09-07's structural finding:
    all 22 findings across six rounds were prose claims about completeness or provenance, and
    `fencecheck` reads only ``` fences, so it could not have caught a single one of them. The
    numbers that were wrong -- 45,720 for 45,721; +2,027 for +2,026; 23,493,680 for 23,493,681 --
    were all in prose and tables, not in fences.
    """
    body = FIGURE.findall(text)
    missing = []
    for fig in sorted(set(body)):
        if any(fig in b for b in blobs.values()):
            continue
        missing.append(fig)
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

    # C7 THE FIGURE AUDIT -- the class that caused all 22 findings, none of which were in a fence
    figlogs = {"a.log": "binding 23,493,681 ops/frame and a delta of 45,721" + chr(10)}
    check("C7 a figure present in a log is ACCEPTED",
          audit_figures("prose saying 23,493,681 here", figlogs) == [])
    check("C7 a WRONG figure in PROSE is REJECTED",
          audit_figures("prose saying 23,493,680 here", figlogs) == ["23,493,680"],
          str(audit_figures("prose saying 23,493,680 here", figlogs)))
    check("C7 it catches the real round-5 miss (45,720 for 45,721)",
          audit_figures("measured 45,720, a 7.9x miss", figlogs) == ["45,720"])
    check("C7 an empty log set rejects every figure (cannot pass vacuously)",
          audit_figures("23,493,681", {}) == ["23,493,681"])

    # C8 TRACKED-ONLY. "committed" must mean committed.
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "untracked.log").write_text("SELFTEST PASS" + chr(10), encoding="utf-8")
        check("C8 an UNTRACKED log is not evidence (tracked-only by default)",
              load_logs([t]) == {}, "loaded %d" % len(load_logs([t])))
        check("C8 ...and IS loaded when tracking is explicitly waived",
              len(load_logs([t], require_tracked=False)) == 1)
    check("C8 tracked_files() really returns paths from git",
          len(tracked_files()) > 100, "%d tracked" % len(tracked_files()))

    # C9 WHOLE-LINE, not substring: a truncated verdict must not pass
    trunc = {"a.log": "SIZE   words : 51,094,744 = 38.07% of 2^27   (target <= 35%)  OVER" + chr(10)}
    doc_trunc = "```" + chr(10) + "SIZE   words : 51,094,744 = 38.07% of 2^27" + chr(10) + "```" + chr(10)
    check("C9 a fence with the verdict STRIPPED is REJECTED (line match, not substring)",
          len(audit(doc_trunc, trunc)) == 1, str(audit(doc_trunc, trunc))[:48])


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
    ap.add_argument("--strict-figures", action="store_true",
                    help="fail on advisory figure findings too (noisy: derived values)")
    ap.add_argument("--no-figures", action="store_true",
                    help="skip the prose-figure audit (fences only)")
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
    print("%s: %d fenced line(s) in no log, against %d TRACKED log file(s)"
          % (a.doc, len(missing), len(blobs)))
    for n, t in missing:
        print("  line %-5d NOT IN ANY LOG: %s" % (n, t[:96]))
    figs = [] if a.no_figures else audit_figures(text, blobs)
    if not a.no_figures:
        print("%s: %d figure(s) not found verbatim in a tracked log  [ADVISORY]" % (a.doc, len(figs)))
        for f in figs:
            print("  FIGURE NOT IN A LOG: %s" % f)
        if figs:
            print("  ^ ADVISORY, not a verdict: a DERIVED figure (a delta, a percentage, a sum)")
            print("    legitimately appears in no log. Check each is arithmetic on figures that DO.")
    return 1 if (missing or (figs and a.strict_figures)) else 0


if __name__ == "__main__":
    sys.exit(main())
