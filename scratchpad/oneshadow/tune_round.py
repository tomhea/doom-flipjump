"""The placement tuning round, generalized: fresh leaf addresses from --labels, the census from
--census, per-op histograms from --hist-glob; adjustable existing fillers (pass1/pos) given
their CURRENT rep counts, plus the three virgin leaf points. Prints the greedy no-frame-loses
plan. Usage:
    python tune_round.py --census C.json.gz --labels L.tsv.gz --hist-glob "hist_i18_*.json" \
        --pass1 5136 --pos 2400
"""
import argparse
import gzip
import json
from pathlib import Path

import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--census", required=True)
ap.add_argument("--labels", required=True)
ap.add_argument("--hist-glob", required=True)
ap.add_argument("--pass1", type=int, required=True, help="current pass1 filler rep count")
ap.add_argument("--pos", type=int, required=True, help="current pos_leaf filler rep count")
ap.add_argument("--ts", type=int, default=0, help="current ts filler rep count")
ap.add_argument("--threshold", type=int, default=20000)
args = ap.parse_args()
DW = 64

want = {}
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        name, _, addr = line.rstrip().rpartition(chr(9))
        if name in ("seg_pass1_leaf", "seg_pass1_ts_leaf", "thing_leaf", "seg_pass2_leaf",
                    "e1m1_bspcode_pos_leaf"):
            want[name] = int(addr)
POINTS = [("pass1 (adjust)", want["seg_pass1_leaf"], -args.pass1),
          ("ts (adjust)", want["seg_pass1_ts_leaf"], -args.ts),
          ("thing (new)", want["thing_leaf"], 0),
          ("pass2 (new)", want["seg_pass2_leaf"], 0),
          ("pos (adjust)", want["e1m1_bspcode_pos_leaf"], -args.pos)]

with gzip.open(args.census, "rt", encoding="utf-8") as f:
    payload = json.load(f)
sites = np.array(payload["sites"], dtype=np.int64)
values = np.array(payload["values"], dtype=np.int64)
bases = sites[:, 0]
LUT = np.array([bin(i).count("1") for i in range(1 << 16)], dtype=np.int8)


def pc(a):
    return (LUT[a & 0xFFFF] + LUT[(a >> 16) & 0xFFFF] + LUT[(a >> 32) & 0xFFFF]).astype(np.int64)


vis_list, names = [], []
sk = bases >> 6
for p in sorted(Path(".").glob(args.hist_glob)) or sorted(Path("scratchpad/oneshadow").glob(args.hist_glob)):
    hp = json.loads(p.read_text())
    keys = np.array([int(k) for k in hp["hist"].keys()], dtype=np.int64)
    counts = np.array(list(hp["hist"].values()), dtype=np.int64)
    o = np.argsort(keys)
    keys, counts = keys[o], counts[o]
    ix = np.clip(np.searchsorted(keys, sk), 0, len(keys) - 1)
    vis_list.append(np.where(keys[ix] == sk, counts[ix], 0))
    names.append(p.stem)
if not vis_list:
    raise SystemExit("no histograms matched")
any_hot = np.zeros(len(values), dtype=bool)
for v in vis_list:
    any_hot |= v > 0
val0 = values[any_hot]
VIS = np.stack([v[any_hot] for v in vis_list])
p_base = np.maximum(1, pc(val0))
print("hists:", ", ".join(names), f"| {val0.shape[0]:,} hot sites")

cur = val0.copy()
applied = []
for rnd in range(3):
    best = None
    for name, at, fmin in POINTS:
        at_cur = at + sum(F * DW for (_n, a, F) in applied if a <= at)
        m = cur >= at_cur
        v, p0 = cur[m], np.maximum(1, pc(cur[m]))
        vism = VIS[:, m]
        for F in range(fmin, 4097, 16):
            if F == 0:
                continue
            d = vism @ (np.maximum(1, pc(v + F * DW)) - p0)
            s, worst = int(d.sum()), int(d.max())
            if worst <= 0 and (best is None or s < best[0]):
                best = (s, worst, name, at, at_cur, F, d.copy())
    if best is None or best[0] >= -args.threshold:
        print(f"round {rnd+1}: nothing feasible above threshold; stopping")
        break
    s, worst, name, at, at_cur, F, d = best
    cur = np.where(cur >= at_cur, cur + F * DW, cur)
    applied.append((name, at, F))
    print(f"round {rnd+1}: {name} F={F:+} -> sum {s:+,} worst {worst:+,} | "
          + " ".join(f"{nm}:{int(di):+,}" for nm, di in zip(names, d)))
tot = VIS @ (np.maximum(1, pc(cur)) - p_base)
print("FINAL:", " ".join(f"{nm}:{int(di):+,}" for nm, di in zip(names, tot)))
print("PLAN:", [(n, F) for n, _a, F in applied])
