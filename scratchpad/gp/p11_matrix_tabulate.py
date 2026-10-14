"""The owner's matrix (P11, 2026-10-13): replay_<route>_<bin>.log (p11_pose_replay.py's output, one per route and
binary) -> per-run tables (exact average ops per game frame) and the means.
python scratchpad/gp/p11_matrix_tabulate.py DIR_OF_REPLAY_LOGS"""
import re
import sys
from pathlib import Path

M = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
BINS = [("54", "P9 blocked54"), ("56", "P10 onepass56"), ("57", "P11 blocked57"),
        ("55", "2-pass(P10src)"), ("55o", "1-pass(P10src)")]


def load(route, b):
    p = M / ("replay_%s_%s.log" % (route, b))
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(errors="replace").splitlines():
        m = re.match(r"\s+run (\S+): (\d+) frames, avg ([\d,]+) ops/frame", line)
        if m:
            out[m.group(1)] = int(m.group(3).replace(",", ""))
        m = re.match(r"\s+run (\S+): CRASHED after (\d+) of (\d+) frames", line)
        if m:
            out[m.group(1)] = "crash@%s" % m.group(2)
    return out


def fmt(v):
    return ("%11s" % format(v, ",")) if isinstance(v, int) else "%11s" % v


for route, title in (("A", "route A: P9's 10 tours (as blocked54 walked them)"),
                     ("B", "route B: P10's 10 tours (today's binding metric; as blocked57 walked them)"),
                     ("C", "route C: the four deg_gate viewpoints, each held 20 frames")):
    data = {b: load(route, b) for b, _ in BINS}
    runs = sorted({r for d in data.values() for r in d}, key=lambda r: (len(r), r))
    if not runs:
        continue
    print("\n" + title)
    print("%-14s" % "run" + "".join("%15s" % name.split()[0] + " " for b, name in BINS))
    for r in runs:
        print("%-14s" % r + "".join(" %s    " % fmt(data[b].get(r, "-")) for b, _ in BINS))
    ok_all = [r for r in runs if all(isinstance(data[b].get(r), int) for b in ("54", "56", "57"))]
    means = {b: sum(data[b][r] for r in ok_all) / len(ok_all) for b in ("54", "56", "57")}
    print("%-14s" % ("mean (%d runs)" % len(ok_all)) + "".join(" %s    " % fmt(round(means[b])) for b in ("54", "56", "57")))
    print("   P9 -> P10 %+.2f%%   P10 -> P11 %+.2f%%   P9 -> P11 %+.2f%%"
          % (100 * (means["56"] / means["54"] - 1), 100 * (means["57"] / means["56"] - 1),
             100 * (means["57"] / means["54"] - 1)))
    both = [r for r in runs if isinstance(data["55"].get(r), int) and isinstance(data["55o"].get(r), int)]
    if both:
        a = sum(data["55"][r] for r in both) / len(both)
        o = sum(data["55o"][r] for r in both) / len(both)
        print("   two-pass vs one-pass (same source; %d runs both completed): %s vs %s = %+.2f%%"
              % (len(both), format(round(a), ","), format(round(o), ","), 100 * (o / a - 1)))
