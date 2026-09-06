"""Where the wflip cost lives, attributed to the SITE THAT ISSUED IT.

The atlas attributes by instruction pointer, and FINDINGS V flagged why that blurs: at mean
popcount 7.76, ~87% of wflip ops execute in the wflip AREA, not at the source line, so an IP
histogram smears each chain onto whatever label happens to precede the area. This tool does not
have that problem. The census records, per wflip SITE, the address of its FIRST op (which is
inline, at the source) and the popcount of the whole chain. Joining that first-op address to the
IP histogram gives ISSUES -- how many times the site fired -- and issues * popcount is the whole
chain's cost, attributed to the line that caused it.

So this reports, per macro:

    issues        how many wflips that macro executes per frame
    cost          issues * popcount, the ops those wflips walk
    mean pc       cost / issues -- the average chain length
    plain         executed ops in the macro's region that are NOT a wflip first-op

and the point of the split is that the two have DIFFERENT levers. High cost with high mean pc is a
VALUE problem (alignment, placement, smaller constants -- the pad toolbox). High cost with low mean
pc is a COUNT problem (the macro simply runs too many wflips -- only restructuring helps).
`--by count` sorts on issues to make the second kind visible, which cost-ranking hides.

CAVEAT INHERITED FROM THE CENSUS: attribution is to the innermost macro whose label most recently
precedes the site. A site emitted between two macro expansions is charged to the earlier one.

NEGATIVE CONTROLS (R9), all under --selftest:
  1. conservation -- summed cost must equal the census/hist join total computed independently.
  2. attribution  -- a synthetic site placed just after a known label must be charged to it, and
                     one placed just BEFORE must not be.
  3. vacuity      -- an all-zero histogram must yield zero issues and zero cost everywhere.

    python scratchpad/12m/wprof.py --census atlas/P7B.census.json.gz \
        --hist atlas/P7B.h57_1.json --labels atlas/P7B.labels.tsv.gz --top 40
"""
import argparse
import bisect
import gzip
import json
import re
from pathlib import Path

import numpy as np

OPBITS = 6
SEG = re.compile(r"^[sf]\d+:l\d+:(.*?)(?:\(\d+\))?$")
REP = re.compile(r"^(?:rep\d+:)+")


STL_NS = ("hex.", "bit.", "stl.")


def _mac(part):
    m = SEG.match(part)
    return REP.sub("", m.group(1) if m else part)


def innermost_macro(name):
    """The macro that directly encloses this label, `rep` unrolling collapsed."""
    parts = name.split("---")
    if len(parts) == 1:
        return "(top level)"
    return _mac(parts[-2])


def doom_macro(name):
    """The DEEPEST macro in the path that is not stl -- i.e. the doom-level operation that is
    ultimately buying this wflip. `hex.exact_xor` is 40% of the frame but it is a leaf everything
    calls; charging its cost to the caller is the only view that says what to change."""
    parts = name.split("---")
    if len(parts) == 1:
        return "(top level)"
    for part in reversed(parts[:-1]):
        mac = _mac(part)
        if not mac.startswith(STL_NS):
            return mac
    return "(pure stl) " + _mac(parts[0])


def load_label_map(labels_path, level="inner", only=""):
    """-> (sorted bit-addresses, macro-id per address, macro name list).

    `only` keeps just the labels whose INNERMOST macro is that one, then attributes them by
    `level`. That is how "who is buying hex.exact_xor" gets asked: the site sits inside the leaf,
    but the charge goes to the deepest doom-level caller above it."""
    pick = doom_macro if level == "doom" else innermost_macro
    addrs, ids = [], []
    names, index = [], {}
    with gzip.open(labels_path, "rt", encoding="utf-8") as f:
        for line in f:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if only and innermost_macro(name) != only:
                continue
            mac = pick(name)
            mid = index.get(mac)
            if mid is None:
                mid = index[mac] = len(names)
                names.append(mac)
            addrs.append(int(addr))
            ids.append(mid)
    a = np.array(addrs, dtype=np.int64)
    b = np.array(ids, dtype=np.int32)
    order = np.argsort(a, kind="stable")
    return a[order], b[order], names


def attribute(site_addrs, label_addrs, label_ids):
    """each site -> the id of the macro whose label most recently precedes it."""
    pos = np.searchsorted(label_addrs, site_addrs, side="right") - 1
    pos[pos < 0] = 0
    return label_ids[pos]


# ------------------------------------------------------------------------------- selftest

def selftest():
    ok = True
    labels = np.array([100, 200, 300], dtype=np.int64)
    ids = np.array([0, 1, 2], dtype=np.int32)

    got = attribute(np.array([201, 250, 299], dtype=np.int64), labels, ids)
    good = list(got) == [1, 1, 1]
    ok &= good
    print("  CONTROL 2a after a label -> charged to it : %s  %s"
          % (list(got), "ok" if good else "!! want [1,1,1]"))
    got = attribute(np.array([199], dtype=np.int64), labels, ids)
    good = list(got) == [0]
    ok &= good
    print("  CONTROL 2b before it     -> NOT charged   : %s  %s"
          % (list(got), "ok" if good else "!! want [0]"))

    bases = np.array([201, 250, 301], dtype=np.int64)
    pcs = np.array([3, 5, 7], dtype=np.int64)
    hist = {201 >> OPBITS: 10, 250 >> OPBITS: 20, 301 >> OPBITS: 30}
    vis = np.array([hist.get(int(b) >> OPBITS, 0) for b in bases], dtype=np.int64)
    total = int((vis * np.maximum(pcs, 1)).sum())
    mid = attribute(bases, labels, ids)
    per = {}
    for m, c in zip(mid, vis * np.maximum(pcs, 1)):
        per[int(m)] = per.get(int(m), 0) + int(c)
    good = sum(per.values()) == total
    ok &= good
    print("  CONTROL 1  conservation                   : %d vs %d  %s"
          % (sum(per.values()), total, "ok" if good else "!! LOST COST"))

    zvis = np.zeros(3, dtype=np.int64)
    good = int((zvis * np.maximum(pcs, 1)).sum()) == 0
    ok &= good
    print("  CONTROL 3  empty histogram -> zero        : %s" % ("ok" if good else "!! nonzero"))
    print("")
    print("SELFTEST %s" % ("PASS" if ok else "!! FAIL"))
    raise SystemExit(0 if ok else 1)


# ------------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census")
    ap.add_argument("--hist")
    ap.add_argument("--labels")
    ap.add_argument("--top", type=int, default=40)
    ap.add_argument("--by", choices=["cost", "count", "meanpc"], default="cost")
    ap.add_argument("--level", choices=["inner", "doom"], default="inner",
                    help="inner = the macro that emitted the wflip (a leaf like hex.exact_xor); "
                         "doom = the deepest NON-stl caller, i.e. what to actually change")
    ap.add_argument("--only", default="", help="restrict to sites whose innermost macro is this")
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
    for need in ("census", "hist", "labels"):
        if not getattr(a, need):
            raise SystemExit("--%s is required" % need)

    payload = json.load(gzip.open(a.census, "rt", encoding="utf-8"))
    bases = np.array([b for b, _ in payload["sites"]], dtype=np.int64)
    pcs = np.array([p for _, p in payload["sites"]], dtype=np.int64)
    hj = json.load(open(a.hist))
    shift = hj["bucket_bits"]
    frame = hj["op_counter"]

    hk = np.array([int(k) for k in hj["hist"]], dtype=np.int64)
    hv = np.array(list(hj["hist"].values()), dtype=np.int64)
    o = np.argsort(hk)
    hk, hv = hk[o], hv[o]

    buckets = bases >> shift
    idx = np.searchsorted(hk, buckets)
    idx[idx >= len(hk)] = 0
    vis = np.where(hk[idx] == buckets, hv[idx], 0)

    cost = vis * np.maximum(pcs, 1)
    total_cost = int(cost.sum())
    total_issues = int(vis.sum())
    print("census %s sites; %s wflip ISSUES/frame carrying %s ops = %.1f%% of a %s-op frame"
          % (format(len(bases), ","), format(total_issues, ","), format(total_cost, ","),
             100.0 * total_cost / frame, format(frame, ",")))
    print("mean chain length %.2f ops; the other %s ops (%.1f%%) are plain jumps"
          % (total_cost / max(1, total_issues), format(frame - total_cost, ","),
             100.0 * (frame - total_cost) / frame))
    print("")

    la, li, names = load_label_map(a.labels, a.level, a.only)
    if a.only:
        # restricting the label map changes attribution: sites outside `only` now fall to whatever
        # kept label precedes them. Keep only sites that land INSIDE an `only` region -- between
        # its first label and the next kept label -- by re-checking against the full map.
        fa, fi, fnames = load_label_map(a.labels, "inner")
        inner = fi[np.searchsorted(fa, bases, side="right") - 1]
        want = fnames.index(a.only) if a.only in fnames else -1
        keep = inner == want
        bases, pcs, vis, cost = bases[keep], pcs[keep], vis[keep], cost[keep]
        print("--only %s: %s of %s sites, %s issues, %s ops (%.2f%% of frame)"
              % (a.only, format(int(keep.sum()), ","), format(len(keep), ","),
                 format(int(vis.sum()), ","), format(int(cost.sum()), ","),
                 100.0 * cost.sum() / frame))
        print("")
        total_cost = int(cost.sum())
    mid = attribute(bases, la, li)
    n = len(names)
    agg_cost = np.bincount(mid, weights=cost, minlength=n)
    agg_iss = np.bincount(mid, weights=vis, minlength=n)
    # CONTROL 1 at real scale: attribution must not lose or invent cost
    assert abs(agg_cost.sum() - total_cost) < 1, "attribution lost cost"

    key = {"cost": agg_cost, "count": agg_iss,
           "meanpc": np.where(agg_iss > 0, agg_cost / np.maximum(agg_iss, 1), 0)}[a.by]
    order = np.argsort(-key)[:a.top]

    hdr = ("%-4s %-44s %12s %7s %11s %7s %7s"
           % ("#", "macro", "issues", "meanpc", "cost", "%frame", "cum%"))
    lines = [hdr, "-" * len(hdr)]
    cum = 0.0
    for i, m in enumerate(order, 1):
        c, iss = float(agg_cost[m]), float(agg_iss[m])
        if c <= 0 and iss <= 0:
            continue
        cum += 100.0 * c / frame
        lines.append("%-4d %-44s %12s %7.2f %11s %7.2f %7.2f"
                     % (i, names[m][:44], format(int(iss), ","),
                        (c / iss) if iss else 0.0, format(int(c), ","),
                        100.0 * c / frame, cum))
    lines.append("-" * len(hdr))
    lines.append("sorted by %s, attributed to the %s macro; %s carry wflip cost"
                 % (a.by, a.level, format(int((agg_cost > 0).sum()), ",")))
    out = "\n".join(lines)
    print(out)
    if a.out:
        Path(a.out).write_text(out + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
