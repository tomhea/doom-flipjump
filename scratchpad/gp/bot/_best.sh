#!/bin/bash
# the best attempt so far per search log
for f in "$@"; do
  python - "$f" <<'PY'
import re, sys
f = sys.argv[1]
best = None; n = 0
for line in open(f, errors="replace"):
    m = re.search(r"search(?: round (\d+))?: (\S+) -> \((True|False), (-?\d+), (-?\d+)\)", line)
    if m:
        n += 1
        sc = (m.group(3) == "True", int(m.group(4)), int(m.group(5)))
        if best is None or sc > best[0]:
            best = (sc, m.group(2), m.group(1))
    if "PLAYTHROUGH GATE PASS" in line or "PLAYTHROUGH GATE FAIL" in line:
        print(f, line.strip()[:150])
print(f.split("/")[-1], "attempts", n, "best", best)
PY
done
