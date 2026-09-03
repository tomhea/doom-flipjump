"""Joint (F1, F2) tuning of the two filler insertions against EVERY available per-op histogram:
maximize the summed win subject to NO frame losing more than TOL ops. The single-frame tuning
overfit (won 3 deg frames, lost the 4th by +9,550); this is the fix."""
import gzip
import json
from pathlib import Path

import numpy as np

AT1 = 0x19C0A40           # seg_pass1_leaf
AT2_BASE = 0xE062D80      # e1m1_bspcode_pos_leaf (before any shift)
TOL = 0                   # no frame may lose
DW = 64

with gzip.open("scratchpad/oneshadow/census_151_vals.json.gz", "rt", encoding="utf-8") as f:
    payload = json.load(f)
sites = np.array(payload["sites"], dtype=np.int64)
values = np.array(payload["values"], dtype=np.int64)
bases = sites[:, 0]

LUT = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.int8)


def pc(a):
    return (LUT[a & 0xFFFF] + LUT[(a >> 16) & 0xFFFF] + LUT[(a >> 32) & 0xFFFF]).astype(np.int64)


HIST_FILES = sorted(Path("scratchpad/oneshadow").glob("hist_151_*.json"))
vis_list, names = [], []
sk = bases >> 6
for p in HIST_FILES:
    hp = json.loads(p.read_text())
    assert hp["bucket_bits"] == 6
    keys = np.array([int(k) for k in hp["hist"].keys()], dtype=np.int64)
    counts = np.array(list(hp["hist"].values()), dtype=np.int64)
    o = np.argsort(keys)
    keys, counts = keys[o], counts[o]
    ix = np.clip(np.searchsorted(keys, sk), 0, len(keys) - 1)
    vis_list.append(np.where(keys[ix] == sk, counts[ix], 0))
    names.append(p.stem.replace("hist_151_", ""))
print("histograms:", ", ".join(names))

any_hot = np.zeros(len(values), dtype=bool)
for v in vis_list:
    any_hot |= v > 0
val = values[any_hot]
VIS = np.stack([v[any_hot] for v in vis_list])
p0 = np.maximum(1, pc(val))
print(f"{val.shape[0]:,} sites hot in at least one histogram")


def deltas(F1, F2):
    s = np.where(val >= AT1, val + F1 * DW, val)
    if F2:
        s = np.where(s >= AT2_BASE + F1 * DW, s + F2 * DW, s)
    d = np.maximum(1, pc(s)) - p0
    return VIS @ d


stage1 = []
for F1 in range(0, 4097, 16):
    d = deltas(F1, 0)
    stage1.append((int(d.sum()), int(d.max()), F1))
feasible = [(s, m, F1) for s, m, F1 in stage1 if m <= TOL]
feasible.sort()
shortlist = [F1 for _s, _m, F1 in feasible[:30]] or [F1 for _s, _m, F1 in sorted(stage1)[:30]]

best = None
for F1 in shortlist:
    for F2 in range(0, 1025, 16):
        d = deltas(F1, F2)
        s, m = int(d.sum()), int(d.max())
        if m <= TOL and (best is None or s < best[0]):
            best = (s, m, F1, F2, d.copy())

if best is None:
    print("NO feasible (F1, F2) where every frame wins; best unconstrained:")
    s, m, F1 = sorted(stage1)[0]
    print(f"  F1={F1} sum={s:+,} worst={m:+,}")
else:
    s, m, F1, F2, d = best
    print(f"\nBEST feasible: F1={F1}, F2={F2}   sum {s:+,}   worst frame {m:+,}")
    for name, di in zip(names, d):
        print(f"   {name:<12} {int(di):+,}")
