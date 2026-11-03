"""Check an attribution against an op-by-op TRACE of the same run (the ground truth).

sim.bind_things' body is straight-line code run 75 times a frame. In the trace, the cost of
statement k on one iteration is (position where statement k+1's first label executes) minus
(position where statement k's first label executes): every op in between -- inline code, wflip
chains, pool tables, stl routines -- belongs to statement k. The attribution under test says the
same thing as (ops attributed to the words [first_label_k, first_label_{k+1})) / (calls of k).

A statement is CHECKED when both labels fire equally often and it costs >= MIN_OPS per call (the
first op of a statement sits a few ops before its first label, so tiny statements carry boundary
noise). PASS = every checked statement within TOL, the WHOLE paired sequence (every statement,
weighted by its calls -- boundary shifts between neighbours cancel there) within SUM_TOL, and at
least MIN_CHECKED statements checked (so the check cannot pass vacuously).

    python validate_trace.py <prefix> [--hist incl|self]
`incl` is the owner attribution (must PASS); `self` is address-only attribution (every op charged
to the word it executes at) -- the negative control, which must FAIL: it cannot see the chains and
pool tables a statement causes elsewhere (ptr_index: 171 vs 894 ops/call on blocked27).
"""
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import labels, load_sparse, load_trace, objects, work_dir  # noqa: E402

TOL, SUM_TOL, MIN_OPS, MIN_CHECKED = 0.05, 0.01, 200, 5
# the checked expansion: bind_things (75 runs a frame) until M7 P1.3 removed it; since, the thing pass's depth
# sort (sim.thing_pass_depth_w, every frame on every map)
MACROS = ("sim.bind_things(", "sim.thing_pass_depth_w(")
ELEM = re.compile(r"^f\d+:l\d+:")
# a statement followed by a call is not checked: the call's first label is where it RETURNS, so the trace's span
# from the statement to it holds the callee's labelled code, which owner attribution charges to the callee
# (thing_pass_depth_w's fcall into the thing pass's leaf: 1,335 traced vs 313 attributed ops a call)
CALLS = re.compile(r":stl\.f?call\(")


def statements():
    """the checked expansion's child statements that have code labels: [(key, first label word)], address order"""
    la, ln = labels()
    obj = objects()
    lo = min(v["lo"] for v in obj.values())
    hi = max(v["hi"] for v in obj.values())
    heads = []
    for macro in MACROS:
        heads = [n.split("---")[0] for n in ln if macro in n.split("---")[0]]
        if heads:
            break
    if not heads:
        raise SystemExit("none of %s expands in the label table" % ", ".join(MACROS))
    B = heads[0] + "---"
    first = {}
    for a, n in zip(la.tolist(), ln):
        if lo <= a < hi and n.startswith(B):
            child = n[len(B):].split("---")[0]
            if ELEM.match(child):
                if child not in first or a < first[child]:
                    first[child] = a
    return sorted(first.items(), key=lambda kv: kv[1])


def check(prefix, hist="incl", quiet=False):
    """-> (passed, rows, (trace_sum, attr_sum)); rows = (stmt, calls, trace/call, attr/call, err, checked)"""
    lo, tr = load_trace(prefix + ".trace.bin")
    w, c = load_sparse(prefix + (".incl.bin" if hist == "incl" else ".self.bin"))
    ws, cs = load_sparse(prefix + ".self.bin")
    selfc = dict(zip(ws.tolist(), cs.tolist()))
    st = statements()
    words = np.array([a for _k, a in st], dtype=np.int64)
    hit = np.nonzero(np.isin(tr, words))[0]
    pos = {}
    for i in hit:
        pos.setdefault(int(tr[i]), []).append(int(i))
    order = np.argsort(w)
    w, c = w[order], c[order]
    cum = np.concatenate([[0], np.cumsum(c)])
    rows = []
    tsum = asum = 0.0
    for (k, a), (k2, b) in zip(st, st[1:]):
        if CALLS.search(k2):
            continue                # a call's first label is its return point: the span holds the callee's own code
        pa, pb = pos.get(a, []), pos.get(b, [])
        calls = selfc.get(a, 0)
        if not pa or len(pa) != len(pb) or calls != len(pa):
            continue
        d = np.array(pb) - np.array(pa)
        if d.min() <= 0:
            continue
        tpc = float(d.mean())
        attr = cum[np.searchsorted(w, b)] - cum[np.searchsorted(w, a)]
        apc = attr / calls
        err = (apc - tpc) / tpc
        checked = tpc >= MIN_OPS
        rows.append((k, calls, tpc, apc, err, checked))
        tsum += tpc * calls
        asum += attr
    chk = [r for r in rows if r[5]]
    passed = (len(chk) >= MIN_CHECKED and all(abs(r[4]) <= TOL for r in chk)
              and tsum > 0 and abs(asum - tsum) / tsum <= SUM_TOL)
    if not quiet:
        print("  %-34s %7s %11s %11s %8s" % ("statement", "calls", "trace/call", "attr/call", "error"))
        for k, calls, tpc, apc, err, checked in rows:
            print("  %-34s %7d %11.1f %11.1f %+7.1f%%%s" % (k.split(":", 2)[2][:34], calls, tpc, apc, 100 * err,
                                                          "" if checked else "  (not checked: < %d ops)" % MIN_OPS))
        print("  checked %d statements; the whole paired sequence: trace %s ops, attributed %s (%+.2f%%)"
              % (len(chk), format(int(tsum), ","), format(int(asum), ","),
                 100.0 * (asum - tsum) / tsum if tsum else float("nan")))
    return passed, rows, (tsum, asum)


def main():
    p = Path(sys.argv[1])
    prefix = str(p if p.is_absolute() else work_dir() / p)
    hist = "self" if "--hist" in sys.argv and sys.argv[sys.argv.index("--hist") + 1] == "self" else "incl"
    ok, _rows, _s = check(prefix, hist)
    print("%s attribution vs the trace: %s (tolerance %.0f%% per statement, %.0f%% on the sum)"
          % (hist, "PASS" if ok else "FAIL", 100 * TOL, 100 * SUM_TOL))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
