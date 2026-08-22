"""Generate the M1 tool inventory for docs/handoff-m1-reset.md 9.7, from the filesystem.

WHY THIS EXISTS. That table has been wrong in SEVEN successive revisions: overclaiming,
undercounting, miscounting, mis-partitioning, a wrong total, stale cells in freshly-edited rows, and
a stale count in a row the same commit touched. Every failure was a hand-maintained inventory of the
author's own evidence decaying faster than the evidence -- because the commit that adds a control is
the one least likely to re-read the table.

⚠ The glob is `*m1*.py`, NOT `m1*.py`. The previous hand-written scope used the latter, which cannot
see `_m1_scratchtest.py`; that file was tracked by accident for eight rounds and the inventory could
never have found it.

    python scratchpad/m1_inventory.py            # print the table
    python scratchpad/m1_inventory.py --check    # exit 1 if 9.7 disagrees with the filesystem
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
        "selftest": "--selftest" in src or "args.selftest" in src,
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

if args.check:
    doc = io.open(DOC, encoding="utf-8").read()
    ok = summary in doc
    print("9.7 %s the filesystem: %s" % ("agrees with" if ok else "DISAGREES with", summary))
    sys.exit(0 if ok else 1)

print(table)
print("")
print(summary)
