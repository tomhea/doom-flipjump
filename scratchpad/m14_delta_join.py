"""The PER-FRAME M14 delta, and what it is made of — a join, not a model.

docs/handoff-perf.md §1.1 states M14's cost as ONE number: the difference of two sweep MEDIANS
(36.68M - 22.94M = +13.7M). A median difference is not a per-frame cost: the two medians can be
different frames. Both sweeps wrote a CSV on the SAME grid, so the honest form is available for
free -- join on (x, y, angle) and subtract per frame.

Then join the M5 counts (`m5_counts.csv`, same grid again) and ask whether the per-frame delta
tracks the number of `sim.thing_load` calls. The slope of that fit is an INDEPENDENT estimate of
the per-call cost, to be compared against the k-sweep's measured 45,934 (§1.2) -- if the two agree,
the model "M14's cost is mostly per-thing" is corroborated by two unrelated instruments; if they
disagree, it is not, and the profile is the tiebreak.

⚠ THE CIRCULARITY WARNING IN §2 APPLIES. This fit is a CROSS-CHECK, never the source of a cost
figure: §2 lists "a residual divided by the cost it was used to corroborate" as the exact mistake
that made the evidence rule necessary. The slope here is reported next to the independently
measured 45,934, and neither is derived from the other.

    python scratchpad/m14_delta_join.py
"""
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = ROOT / "scratchpad"


def load(path, cols):
    rows = {}
    for ln in (S / path).read_text().strip().splitlines()[1:]:
        f = [int(v) for v in ln.split(",")]
        rows[(f[0], f[1], f[2])] = tuple(f[i] for i in cols)
    return rows


# ⚠ THE BASELINE ARGUMENT IS THE WHOLE POINT. `sweep_crfix2.csv`'s binary is NOT byte-exact
# against today's oracle (m14_vp_ops.py --oracle: 844-5300 of 16000 px at the gate viewpoints), so
# a delta against it prices M14 PLUS a picture change. `sweep_base_today.csv` comes from
# m14_basegate.py, which refuses to produce a binary that is not byte-exact against today's oracle.
# Default to the valid one; the old one stays reachable so the difference can be shown.
BASE = sys.argv[1] if len(sys.argv) > 1 else "sweep_base_today.csv"
pre = load(BASE, [3])
post = load("sweep_m14e_b1.csv", [3])         # today's M14 --things binary
cnt = load("m5_counts.csv", [6, 8, 4, 10])    # calls, accepted, arrived, leaves entered not-full
print(f"baseline = {BASE}")

keys = sorted(set(pre) & set(post) & set(cnt))
print(f"pre-M14 {len(pre)} frames, M14 {len(post)} frames, M5 {len(cnt)} frames; "
      f"joined on (x,y,angle): {len(keys)}")
if len(keys) != len(post):
    print(f"!! {len(post) - len(keys)} M14 frames have no partner -- the grids are NOT the same")
    sys.exit(1)
print("the three grids are IDENTICAL -- every comparison below is like-for-like\n")


def q(v, name, scale=1.0):
    v = sorted(v)
    print(f"{name:34s} min {v[0]/scale:11,.0f}  MEDIAN {v[len(v)//2]/scale:11,.0f}  "
          f"mean {statistics.mean(v)/scale:11,.0f}  max {v[-1]/scale:11,.0f}")


d = [post[k][0] - pre[k][0] for k in keys]
q([pre[k][0] for k in keys], "BASELINE ops/frame")
q([post[k][0] for k in keys], "M14 ops/frame")
q(d, "PER-FRAME M14 DELTA")
_medpost = sorted(post[k][0] for k in keys)[len(keys) // 2]
_medpre = sorted(pre[k][0] for k in keys)[len(keys) // 2]
print(f"\n  the two MEDIANS differ by {_medpost - _medpre:,} (that is §1.1's number)")
print(f"  the MEDIAN of the per-frame deltas is {sorted(d)[len(d)//2]:,} "
      "-- a different statistic of the same data")
print(f"  frames where M14 costs MORE: {sum(1 for v in d if v > 0)}/{len(d)}")

print()
q([cnt[k][0] for k in keys], "thing_load calls/frame")
q([cnt[k][1] for k in keys], "accepted sprites/frame")

# least squares, delta = a + b*calls -- b is ops per thing_load call
n = len(keys)
xs = [cnt[k][0] for k in keys]
mx, my = statistics.mean(xs), statistics.mean(d)
sxy = sum((x - mx) * (y - my) for x, y in zip(xs, d))
sxx = sum((x - mx) ** 2 for x in xs)
b = sxy / sxx
a = my - b * mx
res = [y - (a + b * x) for x, y in zip(xs, d)]
sst = sum((y - my) ** 2 for y in d)
print(f"\n=== delta = a + b * (thing_load calls), least squares over {n} frames ===")
print(f"  b (ops per call)   {b:12,.0f}     <- compare with §1.2's k-sweep 45,934, measured "
      "independently")
print(f"  a (frame-constant) {a:12,.0f}     <- what M14 costs a frame that loads NO thing")
print(f"  R^2                {1 - sum(r*r for r in res)/sst:12.3f}")
print(f"  residual std       {statistics.pstdev(res):12,.0f}")
print(f"\n  a + b*median_calls = {a:,.0f} + {b:,.0f}*{sorted(xs)[n//2]} = "
      f"{a + b*sorted(xs)[n//2]:,.0f}   (median per-frame delta {sorted(d)[n//2]:,})")

# ── the TWO-PREDICTOR fit: the per-LEAF preamble, separated from the per-THING loop step ───────
# `sim.thing_pass` costs a preamble at EVERY leaf the walk enters while `full` is clear (3 hex.set
# + fcall + ptr_index + read_byte -- wall_renderer subsector_action) plus a loop step per thing.
# One profiled frame cannot separate them, and two hand-picked viewpoints are near-parallel
# (463 leaves/183 calls vs 439/176). 260 frames spanning 0..680 leaves and 0..249 calls can.
#     delta = a + b*calls + c*leaves
# c is lever 5a's price per leaf; the lever removes that preamble from leaves holding no thing.
ls = [cnt[k][3] for k in keys]


def solve3(A, rhs):
    """Gaussian elimination with partial pivoting -- 3x3, no numpy dependency."""
    M = [row[:] + [r] for row, r in zip(A, rhs)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(M[r][i]))
        M[i], M[p] = M[p], M[i]
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                for c in range(i, 4):
                    M[r][c] -= f * M[i][c]
    return [M[i][3] / M[i][i] for i in range(3)]


def S(u, v):
    return sum(p * q for p, q in zip(u, v))


one = [1.0] * n
A = [[S(one, one), S(one, xs), S(one, ls)],
     [S(xs, one), S(xs, xs), S(xs, ls)],
     [S(ls, one), S(ls, xs), S(ls, ls)]]
a2, b2, c2 = solve3(A, [S(one, d), S(xs, d), S(ls, d)])
pred = [a2 + b2 * x + c2 * l for x, l in zip(xs, ls)]
res2 = [y - p for y, p in zip(d, pred)]
print(f"\n=== delta = a + b*calls + c*LEAVES-entered-before-`full`, over {n} frames ===")
print(f"  a (frame-constant)  {a2:12,.0f}   <- the wire + bind_things: what a frame pays for "
      "having things at all")
print(f"  b (per thing_load)  {b2:12,.0f}   <- lever 5c's target (94.1% of these are rejected "
      "after loading)")
print(f"  c (per LEAF)        {c2:12,.0f}   <- lever 5a's target (the preamble on every entered "
      "leaf, empty or not)")
print(f"  R^2                 {1 - sum(r*r for r in res2)/sst:12.3f}     residual std "
      f"{statistics.pstdev(res2):,.0f}")
med_l, med_x = sorted(ls)[n // 2], sorted(xs)[n // 2]
print(f"\n  at the MEDIAN frame ({med_x} calls, {med_l} leaves): "
      f"{a2:,.0f} + {b2:,.0f}*{med_x} + {c2:,.0f}*{med_l} = {a2 + b2*med_x + c2*med_l:,.0f}"
      f"   (median per-frame delta {sorted(d)[n//2]:,})")
