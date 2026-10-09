"""tests/durations.json's FIRST estimates (2026-10-09; scripts/ci_durations.py refreshes them since). Usage:
    python scripts/ci_durations_nnls.py <dir>   # <dir>: run_<id>.log (gh run view <id> --log) + collect_<sha>.txt
                                                # (pytest --collect-only -q at that commit) for RUNS below
Per-file per-test cost from GitHub CI logs: every `pytest -q` progress line is timestamped and covers the next
len(line) tests in that commit's collection order. Unknown x_f = one test's seconds in file f; each line gives
sum_{t in line} x_{file(t)} = its duration. Solved by NNLS over every run together."""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

S = Path(sys.argv[1])
RUNS = {"37867510055": "09eb0e0", "37867455169": "09eb0e0", "37871172421": "09eb0e0", "37871167901": "09eb0e0",
        "37585553201": "3fab6c1", "37548104405": "e4e05e5", "37548100281": "e4e05e5",
        "37266577667": "f8dc9e8", "37244087909": "fe754a0", "37244086014": "fe754a0", "37242904210": "470e39b",
        "37228066602": "c26b32a", "37228065177": "c26b32a", "37177048302": "397ec35", "37093091327": "f157602",
        "37093089979": "f157602"}
PROG = re.compile(r"^﻿?(\d{4}-\d\d-\d\dT[\d:.]+)Z ([.sxXFE]+)(?:\s+\[\s*(\d+)%\])?\s*$")
TS = re.compile(r"(\d{4}-\d\d-\d\dT[\d:.]+)Z")


def ts(s):
    s = s[:26]
    return datetime.fromisoformat(s)


def chunks(run, total):
    lines = (S / ("run_%s.log" % run)).read_text(encoding="utf-8", errors="replace").splitlines()
    start = None
    out, pos = [], 0
    for ln in lines:
        if start is None and "##[group]Run bash scripts/test.sh" in ln:
            start = ts(TS.search(ln).group(1))
            continue
        if start is None:
            continue
        parts = ln.split("\t")
        m = PROG.match(parts[-1]) if len(parts) >= 3 else None
        if not m:
            continue
        t, chars, pct = ts(m.group(1)), m.group(2), m.group(3)
        out.append((pos, pos + len(chars), t))
        pos += len(chars)
        if pct is not None:
            assert abs(int(pct) - round(100 * pos / total)) <= 1, (run, pos, total, pct)
    res, prev = [], start
    for k, (a, b, t) in enumerate(out):
        d = (t - prev).total_seconds() - (30.0 if k == 0 else 0.0)      # the first line carries the collection
        res.append((a, b, max(d, 0.0)))
        prev = t
    return res, pos


collect = {c: [l for l in (S / ("collect_%s.txt" % c)).read_text().split("\n") if l] for c in set(RUNS.values())}
files = sorted({t.split("::")[0] for ids in collect.values() for t in ids})
fi = {f: k for k, f in enumerate(files)}
rows, rhs, covered = [], [], set()
for run, c in RUNS.items():
    ids = collect[c]
    ch, reached = chunks(run, len(ids))
    print("run %s (%s): %d lines, %d of %d tests reached" % (run, c, len(ch), reached, len(ids)))
    for a, b, d in ch:
        r = np.zeros(len(files))
        for t in ids[a:b]:
            r[fi[t.split("::")[0]]] += 1
            covered.add(t.split("::")[0])
        rows.append(r)
        rhs.append(d)
A, y = np.array(rows), np.array(rhs)
x, resid = nnls(A, y, maxiter=50000)
print("equations %d, unknowns %d, covered files %d, residual %.0f s" % (len(y), len(files), len(covered), resid))
cur = collect["09eb0e0"]
per_file = {}
for t in cur:
    f = t.split("::")[0]
    per_file.setdefault(f, 0)
    per_file[f] += 1
est = {f: {"tests": n, "per_test": float(x[fi[f]]), "total": float(x[fi[f]] * n), "covered": f in covered}
       for f, n in per_file.items()}
tot = sum(e["total"] for e in est.values())
print("current suite estimate: %.0f s = %.2f h over %d files" % (tot, tot / 3600, len(est)))
print("uncovered files:", [f for f, e in est.items() if not e["covered"]])
for f, e in sorted(est.items(), key=lambda kv: -kv[1]["total"])[:30]:
    print("%8.0f s  %4d tests  %7.1f s/test  %s" % (e["total"], e["tests"], e["per_test"], f))
json.dump(est, open(S / "file_estimates.json", "w"), indent=1)
