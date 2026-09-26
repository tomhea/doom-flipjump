"""Per-frame event counts (leaf calls, from the marker log), unit costs derived from them, and the
heaviest frames with their objects and counts.

    python counts.py <prefix>
Unit costs are ratios of MEASURED totals, e.g. "BSP node visited" = the bspcode-walk object's
ops/frame / pos_leaf calls/frame. The least-squares fit is printed for orientation only (R^2 and
the residual say how well per-call constants describe a frame); it is not a measurement.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_marks, marks_meta, objects, work_dir  # noqa: E402

EV = [30, 31, 35, 34, 32, 33, 36, 37, 38]


def resolve(prefix):
    p = Path(prefix)
    return str(p if p.is_absolute() else work_dir() / p)


def main():
    prefix = resolve(sys.argv[1])
    M = load_marks(prefix + ".marks.bin")
    names = {k: v["name"] for k, v in marks_meta().items()}
    obj = objects()
    ids, t, snap = M[:, 0], M[:, 1], M[:, 2:]
    starts = np.nonzero(ids == 1)[0]
    rows, tots, rend, objd = [], [], [], []
    for k in range(len(starts) - 1):
        a, b = starts[k], starts[k + 1]
        seq = ids[a:b]
        if 4 not in set(seq.tolist()):
            continue
        rows.append([(seq == e).sum() for e in EV])
        tots.append(t[b] - t[a])
        i19 = a + int(np.nonzero(seq == 19)[0][0])
        i20 = a + int(np.nonzero(seq == 20)[0][0])
        rend.append(t[i20] - t[i19])
        objd.append(snap[b] - snap[a])
    X = np.array(rows, dtype=float)
    y = np.array(tots, dtype=float)
    R = np.array(rend, dtype=float)
    O = np.array(objd)
    F = len(y)
    print("game frames: %d   mean ops %s" % (F, format(int(y.mean()), ",")))
    print("per-frame event counts: mean / min / max")
    for j, e in enumerate(EV):
        print("   %-34s %8.1f %6d %6d" % (names.get(e, "marker %d" % e), X[:, j].mean(), X[:, j].min(), X[:, j].max()))
    inv = {v["name"]: k for k, v in obj.items()}
    bsp = O[:, inv["bspcode walk (nodes, pos_leaf, ss code)"]].mean()
    print("")
    print("unit costs (MEASURED ratios over the %d frames):" % F)
    print("   BSP node side test (bspcode-walk object / pos_leaf calls): %s ops"
          % format(int(bsp / X[:, EV.index(37)].mean()), ","))
    for j, e, on in ((0, 30, "seg_pass1_leaf"), (1, 31, "seg_pass1_ts_leaf"), (2, 35, "seg_pass2_leaf"),
                     (3, 34, "thing_pass_leaf"), (4, 32, "thing_leaf"), (5, 33, "thing_leaf_b")):
        c = X[:, j].mean()
        if c:
            print("   %-18s per call: %s ops (%.1f calls/frame)" % (on, format(int(O[:, inv[on]].mean() / c), ","), c))
    cols = [0, 1, 2, 3, 4, 5, 7]
    A = np.column_stack([X[:, cols], np.ones(F)])
    coef = np.linalg.lstsq(A, R, rcond=None)[0]
    pred = A @ coef
    r2 = 1 - ((R - pred) ** 2).sum() / ((R - R.mean()) ** 2).sum()
    print("")
    print("orientation only: render walk ~ sum(calls_k * c_k) + c0, least squares, R^2 = %.4f, residual sd %s"
          % (r2, format(int((R - pred).std()), ",")))
    keys = [k for k in np.argsort(-O.sum(axis=0)) if O[:, k].sum() > 0][:9]
    print("")
    print("heaviest game frames: total, objects (owner-attributed), then calls "
          "p1 ts p2 tp tl tlb pos")
    print("%11s " % "total" + " ".join("%9s" % obj.get(k, {"name": "o%d" % k})["name"][:9] for k in keys))
    print("%11s " % format(int(y.mean()), ",") + " ".join("%9s" % format(int(O[:, k].mean()), ",") for k in keys)
          + "  | %s  (mean)" % " ".join("%.0f" % X[:, j].mean() for j in cols))
    for i in list(np.argsort(-y)[:10]) + list(np.argsort(y)[:3]):
        print("%11s " % format(int(y[i]), ",") + " ".join("%9s" % format(int(O[i, k]), ",") for k in keys)
              + "  | %s" % " ".join("%d" % X[i, j] for j in cols))


if __name__ == "__main__":
    main()
