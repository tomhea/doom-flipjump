"""EXACT per-phase costs from the marker log: op-index differences between label hits.

Every marker hit logs the op index BEFORE the marker op runs, and a snapshot of the per-object
counters, so a phase [A, B) is exact -- it includes every chain, pool table and shared leaf the
code between A and B executed -- and the render phase can be split by object with the snapshots.
A GAME frame runs from one `__hot_end` hit (marker 1) to the next and contains `do_world` (4); its
reset phase ends at the next frame's marker 1, as in gamespeed's totals.

    python phases.py <prefix>          (plan section 3's object table)
"""
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_marks, objects, work_dir  # noqa: E402

# (name, start marker, end markers, repeated?) -- the frame's phases in program order
PHASES = [
    ("input (8 polls, key decode)", 1, {4}, False),
    ("doors", 4, {5}, False),
    ("move / turn", 5, {6, 14}, False),
    ("collision", 6, {13}, False),
    ("  of which dsccs seed walks", 11, {12}, True),
    ("post-move vx/vy", 14, {15}, False),
    ("sim.bind_things", 15, {16}, False),
    ("  of which ptloc_walk (dirty things)", 22, {23}, True),
    ("view setup", 16, {17}, False),
    ("eye point location (dsc walk)", 17, {18}, False),
    ("render walk, all", 19, {20}, False),
    ("m1_reset", 21, {"next frame"}, False),
]


def resolve(prefix):
    p = Path(prefix)
    return str(p if p.is_absolute() else work_dir() / p)


def frames(M):
    ids = M[:, 0]
    starts = np.nonzero(ids == 1)[0]
    for k in range(len(starts) - 1):
        a, b = int(starts[k]), int(starts[k + 1])
        if 4 in set(ids[a:b].tolist()):
            yield a, b


def spans(M, a, b):
    """{phase name: (ops, snapshot delta or None, occurrences)} for the frame whose marker rows are [a, b]"""
    ids, t, snap = M[:, 0], M[:, 1], M[:, 2:]
    out = {}
    for name, start, ends, repeated in PHASES:
        total, dsnap, hits = 0, None, 0
        i = a
        while i < b:
            if ids[i] == start:
                if "next frame" in ends:
                    j = b
                else:
                    j = i + 1
                    while j < b and ids[j] not in ends:
                        j += 1
                    if j >= b:
                        break
                total += int(t[j] - t[i])
                hits += 1
                d = snap[j] - snap[i]
                dsnap = d if dsnap is None else dsnap + d
                if not repeated:
                    break
                i = j
            i += 1
        out[name] = (total, dsnap, hits)
    return out


def main():
    prefix = resolve(sys.argv[1])
    M = load_marks(prefix + ".marks.bin")
    obj = objects()
    acc = defaultdict(int)
    hits = defaultdict(int)
    render_obj = None
    tot = []
    F = 0
    for a, b in frames(M):
        F += 1
        tot.append(int(M[b, 1] - M[a, 1]))
        for name, (ops, dsnap, h) in spans(M, a, b).items():
            acc[name] += ops
            hits[name] += h
            if name == "render walk, all" and dsnap is not None:
                render_obj = dsnap if render_obj is None else render_obj + dsnap
    tot = np.array(tot)
    print("game frames: %d   mean frame %s ops (marker 1 to marker 1)" % (F, format(int(tot.mean()), ",")))
    print("")
    print("%-40s %14s %7s %10s %12s" % ("phase", "ops/frame", "%", "runs/fr", "ops/run"))
    top = 0
    for name, _s, _e, _r in PHASES:
        v = acc[name] / F
        if not name.startswith("  "):
            top += acc[name]
        print("%-40s %14s %6.2f%% %10.2f %12s" % (name, format(int(v), ","), 100.0 * acc[name] / tot.sum(),
                                                 hits[name] / F,
                                                 format(int(acc[name] / hits[name]), ",") if hits[name] else "-"))
    rest = tot.sum() - top
    print("%-40s %14s %6.2f%%" % ("(glue between phases)", format(int(rest / F), ","), 100.0 * rest / tot.sum()))
    tries = hits["  of which dsccs seed walks"]
    if tries:
        print("")
        print("one player move try = collision / seed walks: %s ops (%s of it the seed walk); %.2f tries/frame"
              % (format(int(acc["collision"] / tries), ","),
                 format(int(acc["  of which dsccs seed walks"] / tries), ","), tries / F))
    if render_obj is not None:
        print("")
        print("render walk split by owner object (ops/frame):")
        rsum = render_obj.sum()
        for k in np.argsort(-render_obj):
            if render_obj[k] <= 0:
                continue
            nm = obj[k]["name"] if k in obj else "obj%d" % k
            print("   %12s %6.2f%%  %s" % (format(int(render_obj[k] / F), ","), 100.0 * render_obj[k] / rsum, nm))


if __name__ == "__main__":
    main()
