"""Cross-viewpoint check of the two-insertion plan: the same shift simulated under each of the
four deg viewpoints' per-op histograms. Ship only if all four predict wins."""
import gzip
import json
from pathlib import Path

import numpy as np

with gzip.open("scratchpad/oneshadow/census_151_vals.json.gz", "rt", encoding="utf-8") as f:
    payload = json.load(f)
sites = np.array(payload["sites"], dtype=np.int64)
values = np.array(payload["values"], dtype=np.int64)
bases = sites[:, 0]

LUT = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.int8)


def pc(a):
    return (LUT[a & 0xFFFF] + LUT[(a >> 16) & 0xFFFF] + LUT[(a >> 32) & 0xFFFF]).astype(np.int64)


# the plan: F=1552 at seg_pass1_leaf, then F=16 at the (shifted) pos_leaf
shifted = np.where(values >= 0x19C0A40, values + 1552 * 64, values)
shifted = np.where(shifted >= 0xE062D80 + 1552 * 64, shifted + 16 * 64, shifted)
dcost = np.maximum(1, pc(shifted)) - np.maximum(1, pc(values))

HISTS = [
    ("(664,291,0x18000000)", "hist_151_vp1.json"),
    ("(1272,-724,0x40000000)", "hist_151_vp2.json"),
    ("(1869,479,0x80000000)", "hist_151_vp3.json"),
    ("(-416,256,0x0)", "hist_151_default_vp.json"),
]
for vp, hist_file in HISTS:
    p = Path("scratchpad/oneshadow") / hist_file
    if not p.exists():
        print(f"{vp:>24}: hist missing, skipped")
        continue
    hp = json.loads(p.read_text())
    keys = np.array([int(k) for k in hp["hist"].keys()], dtype=np.int64)
    counts = np.array(list(hp["hist"].values()), dtype=np.int64)
    o = np.argsort(keys)
    keys, counts = keys[o], counts[o]
    sk = bases >> 6
    ix = np.clip(np.searchsorted(keys, sk), 0, len(keys) - 1)
    visits = np.where(keys[ix] == sk, counts[ix], 0)
    d = int((visits * dcost).sum())
    print(f"{vp:>24}: frame {hp['op_counter']:>12,}  predicted {d:+,}  -> {hp['op_counter']+d:,}")
