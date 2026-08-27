"""Replay the labelled prof.fjm at ONE viewpoint and log the ts-attribution order.

Uses the SAME prof.fjm/prof.dbg pair opprof.py left in scratchpad/fjmcache (build them first,
with the SAME wad). Records, in execution order, every entry into a `seg<si>T_xorby` block (each
marking seg's SET runs once before its ts body, so consecutive pairs = one visit) — the exact fj
walk order over marking segs, to compare against the oracle's.

    python scratchpad/walk_trace.py --vp 1272,-724,1073741824 --watch 746,751,826,784,823
"""
import argparse
import bisect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
import flipjump as fj                                                     # noqa: E402
from flipjump.utils.classes import RunStatistics                          # noqa: E402
from flipjump.utils.functions import load_debugging_labels                # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--vp", required=True)
ap.add_argument("--watch", default="", help="comma list of seg ids to flag in the log")
ap.add_argument("--max", type=int, default=1200, help="stop logging after N events")
args = ap.parse_args()

out = ROOT / "scratchpad" / "fjmcache"
fjm, dbg = out / "prof.fjm", out / "prof.dbg"
labels = load_debugging_labels(dbg)
watch = set(int(x) for x in args.watch.split(",") if x)

pat = re.compile(r"seg(\d+)T_xorby", )
marks = {}
for name, a in labels.items():
    m = pat.search(name)
    if m:
        marks.setdefault(a, int(m.group(1)))
tsleaf = [a for n, a in labels.items() if n.endswith("seg_pass1_ts_leaf")]
for a in tsleaf:
    marks.setdefault(a, "TSLEAF")

addrs = sorted(marks)
events = []


def hook(self, ip):
    i = bisect.bisect_right(addrs, ip) - 1
    if i >= 0 and addrs[i] == ip and len(events) < args.max:
        events.append(marks[ip])


RunStatistics.register_op_address = hook
vx, vy, va = (int(v) for v in args.vp.split(","))
screen = StreamScreen(stdin=f"{vx}\n{vy}\n{va}\n".encode())
term = fj.run(fjm, io_device=screen, profile=True, print_time=False, print_termination=False,
              flat_max_words=1 << 26)
print(f"ops={term.op_counter:,}  raw events={len(events)}")
seq = [e for e in events if e != "TSLEAF"]
# LIMITATION: collapsing ALL consecutive equal events also hides a genuine immediate revisit
# of the same seg (visit, leave, immediately re-enter) -- acceptable for this diagnostic.
dedup = []
for e in seq:
    if not dedup or dedup[-1] != e:
        dedup.append(e)
print("ts xorby blocks in fj execution order (SET/CLEAR collapsed):")
print("  " + " ".join((f"[{s}]" if s in watch else str(s)) for s in dedup))
n_leaf = sum(1 for e in events if e == "TSLEAF")
print(f"ts leaf entries: {n_leaf}")
