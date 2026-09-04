"""Predict the effect of a filler that sits INSIDE a macro, so it shifts at EVERY expansion.

popcount_census.simulate_shift models one insertion point: everything at or after it moves by
filler_ops*dw, and only the popcounts of the shifted VALUES change the executed cost (a site's
visits move with the site). That is the right model for the campaign's inter-leaf fillers.

It is the WRONG model for a filler inside a macro. frame.arm5's filler and fixed_mul_lo's sit in
the macro body, so changing that one number inserts ops at EVERY expansion -- 20 of them for
fixed_mul_lo -- and a value late in the program shifts by the sum of every insertion before it.
That compound shift is what accidentally bought 139,917 ops on P3-2, at a knob nobody had tuned.

This generalises the model: given the expansion addresses A_1..A_K and a per-expansion delta d,
a value v shifts by d * dw * |{A_i <= v}|.

SAME CAVEAT, inherited and important: a recorded value that is not a plain address in the shifted
region -- an XOR of two labels, a dbit+k constant, a number that merely happens to be large -- is
mis-modelled. This is the free search rung. Only the gate certifies.

    python scratchpad/12m/multishift.py --census C.json.gz --hist H.json \
        --macro "hex.fixed_mul_lo" --labels L.tsv.gz --current 1998 --try 1182-2600
"""
import argparse
import bisect
import gzip
import json
import re
from pathlib import Path


def load_expansion_points(labels_path, macro):
    """the address of each EXPANSION's filler region: one per `<macro>(...)---end` label."""
    pat = re.compile(r"[sf]\d+:l\d+:" + re.escape(macro) + r"\(\d+\)---end$")
    pts = []
    with gzip.open(labels_path, "rt", encoding="utf-8") as f:
        for line in f:
            name, _, addr = line.rstrip("\n").rpartition("\t")
            if pat.search(name):
                pts.append(int(addr))
    return sorted(pts)


def predict(census, values, hist, hist_shift, points, per_site_delta, dw_bits=64):
    if not per_site_delta:
        return 0
    delta = 0
    for (base, pc), v in zip(census, values):
        k = bisect.bisect_right(points, v)
        if not k:
            continue
        visits = hist.get(base >> hist_shift, 0)
        if not visits:
            continue
        new_pc = bin(v + per_site_delta * dw_bits * k).count("1")
        if new_pc != pc:
            delta += visits * (max(1, new_pc) - max(1, pc))
    return delta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", required=True)
    ap.add_argument("--hist", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--macro", required=True)
    ap.add_argument("--current", type=int, required=True, help="the filler value in the tree now")
    ap.add_argument("--try", dest="tries", required=True, help="LO-HI or a comma list")
    ap.add_argument("--step", type=int, default=16,
                    help="keep candidates a multiple of this; 16 keeps the shift out of the "
                         "ragged-absorption regime at the next pad 16")
    a = ap.parse_args()

    payload = json.load(gzip.open(a.census, "rt", encoding="utf-8"))
    census = [(b, p) for b, p in payload["sites"]]
    values = payload["values"]
    hist_j = json.load(open(a.hist))
    hist = {int(k): v for k, v in hist_j["hist"].items()}
    shift = hist_j["bucket_bits"]
    frame = sum(hist.values())

    points = load_expansion_points(a.labels, a.macro)
    print("%s: %d expansions" % (a.macro, len(points)))
    if not points:
        raise SystemExit("no expansion points found -- check the macro name")
    print("frame %s ops; current filler %d" % (format(frame, ","), a.current))
    print()

    if "-" in a.tries and "," not in a.tries:
        lo, hi = (int(x) for x in a.tries.split("-"))
        cands = [v for v in range(lo, hi + 1) if v % a.step == a.current % a.step]
    else:
        cands = [int(x) for x in a.tries.split(",")]

    rows = []
    for c in cands:
        d = predict(census, values, hist, shift, points, c - a.current)
        rows.append((d, c))
    rows.sort()
    print("%-10s %14s   %s" % ("filler", "predicted", "vs now"))
    for d, c in rows[:14]:
        print("%-10d %14s   %s" % (c, format(d, "+,"), "<-- current" if c == a.current else ""))
    print("   ...")
    for d, c in rows[-3:]:
        print("%-10d %14s" % (c, format(d, "+,")))
    print()
    best = rows[0]
    print("BEST: filler %d -> predicted %s ops on this frame (%.2f%%)"
          % (best[1], format(best[0], "+,"), 100.0 * best[0] / frame))
    print("(prediction only -- the sweep median is the ship criterion)")


if __name__ == "__main__":
    main()
