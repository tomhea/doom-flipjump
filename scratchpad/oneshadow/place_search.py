"""Vectorized placement search: for each candidate insertion point, find the filler count
F in [0..FMAX] minimizing the predicted whole-frame wflip delta (simulate-shift, exact under
the uniform-shift model: one segment, values >= at shift by F*dw)."""
import gzip
import json
import sys
import time
from pathlib import Path

import numpy as np

CENSUS = "scratchpad/oneshadow/census_151_vals.json.gz"
HIST = "scratchpad/oneshadow/hist_151_default_vp.json"
FMAX = 4096
DW = 64

t0 = time.perf_counter()
with gzip.open(CENSUS, "rt", encoding="utf-8") as f:
    payload = json.load(f)
sites = np.array(payload["sites"], dtype=np.int64)
values = np.array(payload["values"], dtype=np.int64)
bases, pcs = sites[:, 0], sites[:, 1]

hist_payload = json.loads(Path(HIST).read_text(encoding="utf-8"))
assert hist_payload["bucket_bits"] == 6
hist = hist_payload["hist"]
keys = np.array([int(k) for k in hist.keys()], dtype=np.int64)
counts = np.array(list(hist.values()), dtype=np.int64)
order = np.argsort(keys)
keys, counts = keys[order], counts[order]
site_keys = bases >> 6
idx = np.searchsorted(keys, site_keys)
idx_c = np.clip(idx, 0, len(keys) - 1)
visits = np.where(keys[idx_c] == site_keys, counts[idx_c], 0)

hot = visits > 0
hv, hval, hpc = visits[hot], values[hot], pcs[hot]
print(f"loaded {len(values):,} sites, {hot.sum():,} hot, in {time.perf_counter()-t0:.1f}s")

LUT = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.int8)


def popcount(a):
    return (LUT[a & 0xFFFF] + LUT[(a >> 16) & 0xFFFF] + LUT[(a >> 32) & 0xFFFF]).astype(np.int64)


def search(name, at_addr):
    m = hval >= at_addr
    v, pc, vis = hval[m], hpc[m], hv[m]
    cost0 = (vis * np.maximum(1, pc)).sum()
    base_cost_all = (hv * np.maximum(1, hpc)).sum()
    best = []
    for F in range(0, FMAX + 1):
        npc = popcount(v + F * DW)
        d = (vis * (np.maximum(1, npc) - np.maximum(1, pc))).sum()
        best.append((int(d), F))
    best.sort()
    print(f"\n== {name} (at {hex(at_addr)}): {m.sum():,} hot sites shift, "
          f"{cost0:,} of {base_cost_all:,} shifted wflip ops")
    for d, F in best[:8]:
        print(f"   F={F:>5} ops: predicted {d:+,}")
    return best[0]


CANDIDATES = [
    ("before seg_pass1_leaf", 0x19C0A40),
    ("before seg_pass2_leaf", 0x49E4CC0),
    ("after tables (all render code)", 0x14C0000),
]
# point_on_side_leaf: find it in the labels table
labels_path = "scratchpad/oneshadow/census_151_vals.json.labels.tsv.gz"
with gzip.open(labels_path, "rt", encoding="utf-8") as f:
    for line in f:
        name, _, addr = line.rstrip().rpartition(chr(9))
        if name == "point_on_side_leaf" or name.endswith(":point_on_side_leaf"):
            CANDIDATES.append(("before point_on_side_leaf", int(addr)))
            break

results = {}
for name, at in CANDIDATES:
    results[name] = search(name, at)

print("\n==== SUMMARY ====")
for name, (d, F) in sorted(results.items(), key=lambda kv: kv[1][0]):
    print(f"  {name:<36} F={F:>5} -> {d:+,} ops predicted")
