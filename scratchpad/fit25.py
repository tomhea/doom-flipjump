"""Constrained refit of per-population prices (nnls, merged collinear terms) + species split.

scale==2*setup exactly (each p2seg pays setup+2 scales) and infr tracks setup -> merge into one
`p2seg` regressor. pieces/fcols carry the ts cost together with mark -> keep all three but
non-negative so the solver cannot alias them into nonsense.
"""
import sys
import numpy as np
from scipy.optimize import nnls

rows = []
with open("scratchpad/pop25.csv", encoding="utf-8") as f:
    hdr = next(f).strip().split(",")
    for line in f:
        rows.append(dict(zip(hdr, (int(v) for v in line.strip().split(",")))))

KEYS = ["walk", "p2seg", "mark", "thproj", "thacc", "sstrip", "cols", "pieces", "fcols"]


def feats(r):
    return [r["xr1s"] + r["mark"],          # segs visited by the walk (x_range calls)
            r["setup"],                     # pass-2 one-sided segs (setup + 2 scales each)
            r["mark"],                      # marking segs (plane_near + ts attribution)
            r["thproj"], r["thacc"], r["sstrip"],
            r["cols"], r["pieces"], r["fcols"]]


A = np.array([[1.0] + feats(r) for r in rows])
b = np.array([float(r["ops"]) for r in rows])
coef, rnorm = nnls(A, b)
pred = A @ coef
err = pred - b
print(f"nnls fit: mean|err| {np.mean(np.abs(err))/1e6:.3f}M  max|err| {np.max(np.abs(err))/1e6:.3f}M"
      f"  R2 {1 - np.var(err)/np.var(b):.4f}")
print(f"{'base':>8s} {coef[0]:12,.0f}")
for k, c in zip(KEYS, coef[1:]):
    print(f"{k:>8s} {c:12,.0f}")

# how much of each >25M frame the fit attributes to each term
over = [r for r in rows if r["ops"] > 25_000_000]
over.sort(key=lambda r: -r["ops"])
print(f"\n{len(over)} frames over 25M -- fitted attribution (M ops):")
print(f"{'ops':>6s} {'pred':>6s} {'vp':>20s}  " + " ".join(f"{k:>6s}" for k in KEYS))
for r in over[:14]:
    f_ = feats(r)
    parts = [coef[1 + i] * f_[i] / 1e6 for i in range(len(KEYS))]
    vp = f"({r['x']},{r['y']},{r['angle']>>28:x})"
    print(f"{r['ops']/1e6:6.1f} {pred[rows.index(r)]/1e6:6.1f} {vp:>20s}  "
          + " ".join(f"{p:6.2f}" for p in parts))

# species split: how much would perfect removal of ALL thing work save on each?
print("\nif ALL thing work vanished (thproj+thacc+sstrip terms):")
for r in over[:8]:
    f_ = feats(r)
    tsave = coef[4] * r["thproj"] + coef[5] * r["thacc"] + coef[6] * r["sstrip"]
    print(f"  {r['ops']/1e6:6.1f}M -> ~{(r['ops']-tsave)/1e6:6.1f}M  @ ({r['x']},{r['y']})")
