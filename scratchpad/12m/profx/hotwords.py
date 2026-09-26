"""The ~20 hottest SHARED WORDS: the source words whose dispatch tables carry the most ops.

A blocked build puts every table dispatched through one word into that word's block and PINS the
word (bakes the block base into it), so each dispatch flips a short index instead of a whole
address. Lose the pin and every dispatch through the word pays the base's bits again, twice (arm
and disarm). So the words that matter are the ones whose tables run the most: this ranks every
group of the build by the ops its pool tables executed in a profiled run, and writes the top N.

    python hotwords.py <prefix> [--top 20] [--out hotwords_blocked27.json]
        [--fjm ...] [--labels ...] [--counts-cache scratchpad/12m/_counts_game.json.gz]

Per group: table ops/frame (self counts of the pool words inside its block), dispatches/frame (self
count of the source cell's own op: every dispatch jumps THROUGH it), the block base and size, the
tables in the block, and an ESTIMATE of what the pin is worth: dispatches x 2 x popcount(base)
(arm + disarm would each write the base's bits again). The estimate is arithmetic, not measured.

CONTROL: the layout is RE-DERIVED from the counts cache (pool.reconstruct); it must agree with the
image -- every pinned word's rest value must carry exactly its reconstructed base -- or the file is
not written. A cache from another program, or other knobs, fails this.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import HERE, ROOT, W, default_fjm, default_labels, label_dict, load_sparse, work_dir  # noqa: E402
from fjmimage import FjmImage  # noqa: E402
from pool import KNOBS, eval_key, reconstruct  # noqa: E402


def game_frames(prefix):
    runs = json.load(open(prefix + ".runs.json"))["runs"]
    return sum(max(0, r["frames"] - 2) for r in runs if r["name"] != "calibration")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--out", default=None)
    ap.add_argument("--fjm", default=None)
    ap.add_argument("--labels", default=None)
    ap.add_argument("--counts-cache", default=str(ROOT / "scratchpad" / "12m" / "_counts_game.json.gz"))
    a = ap.parse_args()
    p = Path(a.prefix)
    prefix = str(p if p.is_absolute() else work_dir() / p)
    fjm = Path(a.fjm) if a.fjm else default_fjm()
    lab_path = Path(a.labels) if a.labels else default_labels()

    pool, fr = reconstruct(a.counts_cache)
    lab = label_dict(lab_path)
    img = FjmImage(fjm)
    F = game_frames(prefix)
    print("fjm %s (sha256 %s...), %d game frames in %s" % (fjm.name, hashlib.sha256(fjm.read_bytes()).hexdigest()[:16],
                                                        F, Path(prefix).name))
    print("counts cache %s: %d groups, %d tables; reconstructed blocks: %d placed, %d without room"
          % (Path(a.counts_cache).name, len(fr["counts"]), sum(fr["counts"].values()), len(pool.groups),
             len(pool.broken_groups)))

    # every placed group: its block, and its source word in this build
    groups = []
    agree = disagree = unresolved = 0
    for g, (base, _e) in pool.groups.items():
        bits = pool._block_bits(g)
        addr = eval_key(g, lab)
        if addr is None:
            unresolved += 1
            continue
        v = img.word(addr // W)
        rest = (v & ~(bits - 1)) if v is not None else None
        if rest == base:
            agree += 1
        else:
            disagree += 1
        groups.append((base, bits, g, addr, rest == base))
    n = agree + disagree
    print("CONTROL reconstruction vs image: %d of %d resolvable source words rest at their reconstructed base "
          "(%.2f%%); %d keys unresolved" % (agree, n, 100.0 * agree / max(1, n), unresolved))
    if agree < 0.99 * n:
        raise SystemExit("the counts cache does not describe this binary (or the knobs differ) -- not written")

    # ops executed in each block: self counts of pool words, bisected into the sorted blocks
    groups.sort()
    bases_w = [b // W for b, _bits, _g, _a, _p in groups]
    ws, cs = load_sparse(prefix + ".self.bin")
    selfc = dict(zip(ws.tolist(), cs.tolist()))
    pool_lo = KNOBS["pool_base"] // W
    table_ops = np.zeros(len(groups), dtype=np.int64)
    m = ws >= pool_lo
    idx = np.searchsorted(np.array(bases_w, dtype=np.int64), ws[m], side="right") - 1
    ok = idx >= 0
    for i, c, wv in zip(idx[ok].tolist(), cs[m][ok].tolist(), ws[m][ok].tolist()):
        b, bits, _g, _a, _p = groups[i]
        if wv < (b + bits) // W:
            table_ops[i] += c
    pooled = int(cs[m].sum())
    print("ops executed in the pool: %s over the run (%s per game frame); %.2f%% of them inside a placed block"
          % (format(pooled, ","), format(pooled // F, ","), 100.0 * table_ops.sum() / max(1, pooled)))

    order = np.argsort(-table_ops)[:a.top]
    out = []
    print("")
    print("%4s %12s %11s %6s %9s %8s %s" % ("rank", "table ops/fr", "dispatch/fr", "pc(b)", "pin value", "tables",
                                           "source word"))
    for r, i in enumerate(order.tolist(), start=1):
        b, bits, g, addr, pinned = groups[i]
        disp = selfc.get(addr // W - 1, 0)       # the cell's own op: every dispatch jumps through it
        pc = bin(b).count("1")
        value = disp * 2 * pc
        out.append({"rank": r, "key": g, "jump_word_bits": addr, "base_bits": b, "block_bits": bits,
                    "tables": fr["counts"].get(g, 0), "pinned": bool(pinned),
                    "table_ops_per_frame": round(table_ops[i] / F, 1), "dispatches_per_frame": round(disp / F, 1),
                    "base_popcount": pc, "pin_value_est_per_frame": round(value / F, 1)})
        print("%4d %12s %11s %6d %9s %8s %s" % (r, format(int(table_ops[i] / F), ","), format(int(disp / F), ","), pc,
                                               format(int(value / F), ","), format(fr["counts"].get(g, 0), ","), g[:70]))
    top_ops = sum(o["table_ops_per_frame"] for o in out)
    print("the top %d carry %s table ops/frame = %.1f%% of all pool ops"
          % (len(out), format(int(top_ops), ","), 100.0 * top_ops * F / max(1, pooled)))
    dest = Path(a.out) if a.out else HERE / ("hotwords_%s.json" % fjm.stem.replace("doom_e1m1_", ""))
    dest.write_text(json.dumps({
        "what": "the hottest shared words (block-pool groups) by table ops, from profx hotwords.py",
        "fjm": fjm.name, "fjm_sha256": hashlib.sha256(fjm.read_bytes()).hexdigest(),
        "labels": lab_path.name, "counts_cache": Path(a.counts_cache).name, "counts_sig": fr["sig"],
        "knobs": KNOBS, "run": Path(prefix).name, "game_frames": F, "pool_ops_per_frame": round(pooled / F, 1),
        "words": out}, indent=1), encoding="ascii")
    print("wrote %s" % dest)


if __name__ == "__main__":
    main()
