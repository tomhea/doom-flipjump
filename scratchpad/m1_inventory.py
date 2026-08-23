"""Generate the M1 tool inventory for docs/handoff-m1-reset.md 9.7, from the filesystem.

WHY THIS EXISTS. That table has been wrong in SEVEN successive revisions: overclaiming,
undercounting, miscounting, mis-partitioning, a wrong total, stale cells in freshly-edited rows, and
a stale count in a row the same commit touched. Every failure was a hand-maintained inventory of the
author's own evidence decaying faster than the evidence -- because the commit that adds a control is
the one least likely to re-read the table.

⚠ The scope is `^_?m1(?![45])` -- a leading-underscore-tolerant match anchored at the START of the
name, excluding the m14/m145 tools. The previous hand-written scope was `m1*.py`, which cannot see
`_m1_scratchtest.py`; that file was tracked by accident for eight rounds and the inventory could
never have found it.

⚠⚠ CR round 12: the FIRST version of this generator was itself uncontrolled and overclaimed.
Its `--selftest` column was a substring test, so it matched its own summary template and credited
itself with a flag it does not have (8 reported, 7 real). Its `--check` compared only the one-line
summary, so falsifying an entire ROW still printed "agrees with the filesystem" and exited 0. A
generated inventory of negative controls, with no negative control of its own -- which is the same
failure the table was generated to end, one level up. Hence `--selftest` below.

    python scratchpad/m1_inventory.py            # print the table
    python scratchpad/m1_inventory.py --check    # exit 1 if 9.7 disagrees, ROW BY ROW
    python scratchpad/m1_inventory.py --selftest # mutate the doc, require --check to reject
"""
import argparse
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/handoff-m1-reset.md"

ap = argparse.ArgumentParser()
ap.add_argument("--check", action="store_true")
ap.add_argument("--selftest", action="store_true")
args = ap.parse_args()

# `_?m1` followed by anything that is not 4 -- catches m1_, m1a_..m1q_, and a leading underscore
# (which is how _m1_scratchtest.py hid from the old `m1*.py` scope for eight rounds), while
# excluding the m14/m145 milestone tools and make_e1m1_lite.py.
PAT = re.compile(r"^_?m1(?![45])")
tools = sorted(p for p in (ROOT / "scratchpad").glob("*.py") if PAT.match(p.name))
tracked = set(subprocess.run(["git", "ls-files", "scratchpad/"], cwd=ROOT, capture_output=True,
                             text=True).stdout.split())

rows = []
for p in tools:
    src = io.open(p, encoding="utf-8").read()
    rel = "scratchpad/" + p.name
    n_mut = len(re.findall(r'"\)?,\s+(?:SR|FJ),', src)) or None
    rows.append({
        "name": p.name,
        # Match the DECLARATION, not the string. A substring test matched this file's own summary
        # template and reported a flag it does not have (CR round 12).
        "selftest": bool(re.search(r'add_argument\(\s*"--selftest"', src)),
        # A count of the word CONTROL, and nothing more. It is NOT evidence any of them can fail;
        # the table says so. (This tool's own count includes its own regex literal.)
        "controls": len(re.findall(r"CONTROL", src)),
        "tracked": rel in tracked,
        "mutations": n_mut if p.name == "m1_mutations.py" else None,
    })

lines = ["| tool | `--selftest` | `CONTROL` mentions | tracked |", "|---|---|---|---|"]
for r in rows:
    extra = ""
    if r["mutations"]:
        extra = " (%d mutations)" % r["mutations"]
    lines.append("| `%s`%s | %s | %d | %s |"
                 % (r["name"], extra, "yes" if r["selftest"] else "**no**", r["controls"],
                    "yes" if r["tracked"] else "no"))
table = "\n".join(lines)

n_self = sum(1 for r in rows if r["selftest"])
summary = ("%d M1 scripts (`_?m1` not followed by 4); %d carry `--selftest`, %d do not."
           % (len(rows), n_self, len(rows) - n_self))

BLOCK = table + chr(10) + chr(10) + summary


def check(doc_text):
    """Compare the WHOLE generated block, row by row -- not just the summary line.

    CR round 12 demonstrated the summary-only version passing after a row for m1c_restore_set.py
    (the uncontrolled tool that produced the file shipping in src/) was falsified to "yes | 99 | no".
    """
    missing = [l for l in BLOCK.splitlines() if l.strip() and l not in doc_text]
    return missing


if args.selftest:
    # R9: this generator is cited as evidence, so it needs a control that mutates real input and
    # requires rejection.
    doc = io.open(DOC, encoding="utf-8").read()
    clean = check(doc)
    victim = next(l for l in BLOCK.splitlines() if "m1c_restore_set.py" in l)
    falsified = doc.replace(victim, "| `m1c_restore_set.py` | yes | 99 | no |")
    caught = check(falsified)
    ok = not clean and bool(caught)
    print("  the doc as committed            -> %s"
          % ("agrees ok" if not clean else "!! DISAGREES: %s" % clean[:2]))
    print("  one row falsified               -> %s"
          % ("rejected ok" if caught else "!! ACCEPTED -- --check cannot see a wrong row"))
    print("M1 INVENTORY SELFTEST: %s" % ("PASS" if ok else "FAIL"))
    sys.exit(0 if ok else 1)

if args.check:
    missing = check(io.open(DOC, encoding="utf-8").read())
    if missing:
        print("9.7 DISAGREES with the filesystem, %d line(s), e.g." % len(missing))
        for l in missing[:5]:
            print("   %s" % l)
    else:
        print("9.7 agrees with the filesystem, row by row: %s" % summary)
    sys.exit(1 if missing else 0)

print(table)
print("")
print(summary)
