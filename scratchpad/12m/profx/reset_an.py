"""M1 reset: owner-attributed ops per restored cell, by statement kind.

    python reset_an.py <prefix>
Cells come from the generated reset part (hex.zero N / hex.set 1 / rep(N) m1.zerobyte lines); ops
from the owner-attributed histogram over the reset code's range, per reset executed (marker 21).
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, default_fjm, labels, load_marks, load_sparse, objects, work_dir  # noqa: E402


def resolve(prefix):
    p = Path(prefix)
    return str(p if p.is_absolute() else work_dir() / p)


def main():
    prefix = resolve(sys.argv[1])
    M = load_marks(prefix + ".marks.bin")
    nres = int((M[:, 0] == 21).sum())
    obj = {v["name"]: v for v in objects().values()}["m1_reset code"]
    la, ln = labels()
    w, c = load_sparse(prefix + ".incl.bin")
    m = (w >= obj["lo"]) & (w < obj["hi"])
    idx = np.searchsorted(la, w[m], side="right") - 1
    s = np.bincount(idx, weights=c[m], minlength=len(la))
    part = ROOT / "build" / ("generated_" + default_fjm().stem) / "e1m1_07_reset.fj"
    src = part.read_text(encoding="utf-8").split("\n")
    fidx = None
    kind_ops = defaultdict(float)
    kind_cells = defaultdict(int)
    for i in np.nonzero(s)[0]:
        mm = re.match(r"^(f\d+):l(\d+):", ln[i])
        line = src[int(mm.group(2)) - 1].strip() if mm else ""
        if mm and fidx is None and line.startswith(("hex.zero", "hex.set", "rep(")):
            fidx = mm.group(1)
        if not mm or mm.group(1) != fidx:
            kind_ops["(the m1_reset label, glue)"] += s[i]
            continue
        kind_ops["m1.zerobyte" if line.startswith("rep(") else line.split()[0]] += s[i]
    for line in src:
        t = line.strip()
        mz = re.match(r"hex\.zero (\d+),", t)
        ms = re.match(r"hex\.set (\d+),", t)
        mr = re.match(r"rep\((\d+), i\) m1\.zerobyte", t)
        if mz:
            kind_cells["hex.zero"] += int(mz.group(1))
        elif ms:
            kind_cells["hex.set"] += int(ms.group(1))
        elif mr:
            kind_cells["m1.zerobyte"] += int(mr.group(1))
    tot = sum(kind_ops.values())
    cells = sum(kind_cells.values())
    print("resets executed: %d; ops per reset %s; cells restored %d -> %.1f ops/cell overall"
          % (nres, format(int(tot / nres), ","), cells, tot / nres / cells))
    for k in sorted(kind_ops, key=lambda k: -kind_ops[k]):
        n = kind_cells.get(k, 0)
        print("  %-28s %10s ops/reset  cells %6d  -> %s ops/cell" % (k, format(int(kind_ops[k] / nres), ","), n,
              ("%.1f" % (kind_ops[k] / nres / n)) if n else "-"))


if __name__ == "__main__":
    main()
