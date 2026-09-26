"""ESTIMATE for the pin-protection design: what heat-ordered INDEX assignment inside the hot groups
would save on blocked27. Not a measurement of any build -- arithmetic on a measured profile.

For each hot group: the tables executed in its block (self counts of pool words, profx games run),
each table's arm/disarm cost 2 x popcount(offset in block) (what a pinned word's writers flip), and
its dispatch share (table ops scaled to the group's measured dispatch count). "now" charges each
table its current offset; "heat-ordered" gives the hottest tables the cheapest offsets of their
width bucket.
"""
import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, load_sparse, work_dir  # noqa: E402
from pool import reconstruct  # noqa: E402

#     python heatindex.py games [hotwords_blocked27.json]
prefix = str(work_dir() / sys.argv[1])
hot = json.loads(Path(sys.argv[2] if len(sys.argv) > 2 else
                      Path(__file__).resolve().parent / "hotwords_blocked27.json").read_text())
pool, fr = reconstruct(ROOT / "scratchpad" / "12m" / "_counts_game.json.gz")
ws, cs = load_sparse(prefix + ".self.bin")
F = hot["game_frames"]
tot_now = tot_opt = 0.0
print("%-60s %10s %12s %12s %8s" % ("group", "disp/fr", "arm now/fr", "heat-ord/fr", "saving"))
for h in hot["words"]:
    g = h["key"]
    base, bits = pool.groups[g][0], pool._block_bits(g)
    layout, _ = pool._bucket_layout(g)
    lo, hi = base // 32, (base + bits) // 32
    m = (ws >= lo) & (ws < hi)
    offs = ws[m] * 32 - base
    ops = cs[m]
    tables = {}
    for off, c in zip(offs.tolist(), ops.tolist()):
        for slot_ops, (boff, slots, count) in layout.items():
            sb = slot_ops * 64
            if boff <= off < boff + slots * sb:
                key = (slot_ops, (off - boff) // sb)
                tables[key] = tables.get(key, 0) + c
                break
    tops = sum(tables.values())
    disp = h["dispatches_per_frame"] * F
    scale = disp / tops if tops else 0.0
    now = opt = 0.0
    for slot_ops, (boff, slots, count) in layout.items():
        sb = slot_ops * 64
        mine = sorted(((v, idx) for (so, idx), v in tables.items() if so == slot_ops), reverse=True)
        for v, idx in mine:
            now += v * scale * 2 * bin(boff + idx * sb).count("1")
        cheap = sorted(range(slots), key=lambda i: (bin(boff + i * sb).count("1"), i))
        for (v, _idx), ci in zip(mine, cheap):
            opt += v * scale * 2 * bin(boff + ci * sb).count("1")
    tot_now += now
    tot_opt += opt
    print("%-60s %10s %12s %12s %8s" % (g[:60], format(int(disp / F), ","), format(int(now / F), ","),
                                        format(int(opt / F), ","), format(int((now - opt) / F), ",")))
print("TOTAL over the %d hot words: arm/disarm now %s ops/frame, heat-ordered %s, saving %s (ESTIMATE)"
      % (len(hot["words"]), format(int(tot_now / F), ","), format(int(tot_opt / F), ","),
         format(int((tot_now - tot_opt) / F), ",")))
