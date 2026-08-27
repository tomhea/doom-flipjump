"""Diff two `ca2_profile.py` histograms -- and decide between CONCENTRATED and SPREAD.

THE QUESTION. When a change makes a frame cheaper, is the saving in a few places (the code the
change actually edited) or spread thinly everywhere (a PLACEMENT effect -- R20 says pointer-deref
and dispatch cost scales with the set bits of the address, so moving the image moves every cost)?

WHY SHAPE AND NOT ADDRESSES. The two binaries differ in span, so every region after the point where
they diverge sits at a different address in each. A bucket-by-bucket subtraction across that
boundary compares unrelated code and is meaningless. The DISTRIBUTION is not affected by a rigid
shift, so it is what this compares:

  * CONCENTRATED (the change did it): a few buckets account for most of the delta, and the rest of
    the image is ~unchanged. The delta's Gini/top-k share is high.
  * SPREAD (placement did it): every bucket moves by a similar PERCENTAGE of its own op count.
    The per-bucket percentage changes cluster tightly around the global percentage.

The discriminator is therefore the spread of per-bucket PERCENTAGE change, weighted by bucket size,
compared against the global percentage change. Both are printed; neither is asserted -- this tool
reports a shape, it does not decide.

    python scratchpad/ca2_profile_diff.py --a hist_base.json --b hist_new.json
"""
import argparse
import json
import statistics
import sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--a", required=True, help="baseline histogram json")
ap.add_argument("--b", required=True, help="new histogram json")
ap.add_argument("--top", type=int, default=20)
args = ap.parse_args()

A = json.loads(Path(args.a).read_text(encoding="utf-8"))
B = json.loads(Path(args.b).read_text(encoding="utf-8"))
assert A["bucket_bits"] == B["bucket_bits"], "histograms must share a bucket width"
assert A["viewpoint"] == B["viewpoint"], "histograms must be of the SAME frame"
SH = A["bucket_bits"]
W = 32
wpb = (1 << SH) // W

ha = {int(k): v for k, v in A["hist"].items()}
hb = {int(k): v for k, v in B["hist"].items()}
ta, tb = sum(ha.values()), sum(hb.values())

print("A base : %s  %s ops  (%s)" % (Path(A["fjm"]).name, format(ta, ","), A["sha256"][:16]))
print("B new  : %s  %s ops  (%s)" % (Path(B["fjm"]).name, format(tb, ","), B["sha256"][:16]))
print("frame  : (%d, %d, %#x)   bucket = %s words" % (*A["viewpoint"], format(wpb, ",")))
print("")
gpct = 100.0 * (tb - ta) / ta
print("TOTAL  : %s -> %s   %s  (%.2f%%)"
      % (format(ta, ","), format(tb, ","), format(tb - ta, ","), gpct))
print("")

# ---- how many buckets does it take to account for the delta? ---------------------------------
# Buckets are matched by address, which is only valid where the two images have not shifted; the
# ranked view below is therefore about MAGNITUDE, not about naming a region.
keys = set(ha) | set(hb)
deltas = sorted(((hb.get(k, 0) - ha.get(k, 0), k) for k in keys), key=lambda t: t[0])
losers = [d for d in deltas if d[0] < 0]
gainers = [d for d in deltas if d[0] > 0]
tot_lost = -sum(d for d, _k in losers)
tot_gain = sum(d for d, _k in gainers)
print("buckets that LOST ops : %4d   total -%s" % (len(losers), format(tot_lost, ",")))
print("buckets that GAINED   : %4d   total +%s" % (len(gainers), format(tot_gain, ",")))
print("net                    :        %s" % format(tb - ta, ","))
print("")

run = 0
need = abs(tb - ta)
kbuckets = 0
for d, _k in deltas:
    if d >= 0:
        break
    run += -d
    kbuckets += 1
    if run >= need:
        break
print("CONCENTRATION: %d buckets account for the whole net change (%s of %s ops-lost)"
      % (kbuckets, format(run, ","), format(tot_lost, ",")))
print("               the image touched %d buckets in total" % len(keys))
print("")

# ---- the discriminator: are per-bucket percentage changes tight around the global one? --------
BIG = 50_000          # ignore noise buckets; a bucket must matter to vote
pcts = []
for k in keys:
    a, b = ha.get(k, 0), hb.get(k, 0)
    if a >= BIG:
        pcts.append((100.0 * (b - a) / a, a, k))
pcts.sort()
if pcts:
    vals = [p for p, _a, _k in pcts]
    wsum = sum(a for _p, a, _k in pcts)
    wmean = sum(p * a for p, a, _k in pcts) / wsum
    print("per-bucket %% change, over the %d buckets with >= %s ops in A:"
          % (len(pcts), format(BIG, ",")))
    print("   min %.2f%%   p25 %.2f%%   median %.2f%%   p75 %.2f%%   max %.2f%%"
          % (vals[0], vals[len(vals) // 4], statistics.median(vals),
             vals[3 * len(vals) // 4], vals[-1]))
    print("   op-weighted mean %.2f%%   vs GLOBAL %.2f%%" % (wmean, gpct))
    print("   stdev %.2f pct-points" % (statistics.pstdev(vals) if len(vals) > 1 else 0.0))
    print("")
    print("   READ: a SPREAD (placement) signature is a tight cluster around the global %.2f%%."
          % gpct)
    print("         a CONCENTRATED signature is most buckets near 0%% and a few far negative.")
    print("")
    near0 = sum(1 for v in vals if abs(v) < 1.0)
    print("   buckets within +-1%% of unchanged : %d of %d" % (near0, len(vals)))
    print("   buckets below -10%%               : %d of %d"
          % (sum(1 for v in vals if v < -10.0), len(vals)))

print("")
print("largest DECREASES (bucket, words, A ops -> B ops):")
print("%-14s %-16s %14s %14s %12s %8s" % ("bucket", "word range", "A", "B", "delta", "pct"))
for d, k in deltas[:args.top]:
    a, b = ha.get(k, 0), hb.get(k, 0)
    print("%-14s %-16s %14s %14s %12s %7s"
          % (hex(k << SH), format((k << SH) // W, ",") + "..", format(a, ","), format(b, ","),
             format(d, ","), ("%.1f%%" % (100.0 * d / a)) if a else "new"))
print("")
print("largest INCREASES:")
for d, k in reversed(deltas[-args.top:]):
    if d <= 0:
        continue
    a, b = ha.get(k, 0), hb.get(k, 0)
    print("%-14s %-16s %14s %14s %12s %7s"
          % (hex(k << SH), format((k << SH) // W, ",") + "..", format(a, ","), format(b, ","),
             format(d, ","), ("+%.1f%%" % (100.0 * d / a)) if a else "new"))
print("")
print("⚠ Bucket ADDRESSES are only comparable where the two images have not shifted relative to")
print("  each other. Use the SHAPE lines above to decide concentrated-vs-spread; use the address")
print("  rows only as a pointer to which regions to name with a label table.")
