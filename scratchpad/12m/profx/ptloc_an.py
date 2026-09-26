"""Point-location cost on the shipped binary: one runtime thing marked dirty per game frame.

    python drive.py still 75 poke --poke   and   python drive.py still 75 still
    python ptloc_an.py poke still

`--poke` writes thss_rt[t] = 0xFFFF (the host's "I moved this one") at the first input poll of game
frame g, t = g mod 75; bind_things then runs its DIRTY path for that thing: read its position,
fcall ptloc_walk, write the subsector back. The M1 reset restores thss_rt at frame end. CONTROL:
the pixels must equal the un-poked run's (the located subsector is the baked one), or the lookup
computed something else and the numbers mean nothing.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_marks, work_dir  # noqa: E402


def resolve(prefix):
    p = Path(prefix)
    return str(p if p.is_absolute() else work_dir() / p)


def frames(prefix):
    M = load_marks(prefix + ".marks.bin")
    ids, t = M[:, 0], M[:, 1]
    starts = np.nonzero(ids == 1)[0]
    out = []
    for k in range(len(starts) - 1):
        a, b = starts[k], starts[k + 1]
        seq = ids[a:b + 1].tolist()
        if 4 not in seq:
            continue
        seg = {}
        for i in range(a, b):
            seg[int(ids[i])] = seg.get(int(ids[i]), 0) + int(t[i + 1] - t[i])
        seg["bind"] = int(t[a + seq.index(16)] - t[a + seq.index(15)])
        seg["frame"] = int(t[b] - t[a])
        out.append(seg)
    return out


def main():
    poke, still = resolve(sys.argv[1]), resolve(sys.argv[2])
    P, S = frames(poke), frames(still)
    rp = json.load(open(poke + ".runs.json"))["runs"][0]
    rs = json.load(open(still + ".runs.json"))["runs"][0]
    same = rp["sha"] == rs["sha"]
    print("CONTROL pixels identical to the un-poked run: %s (%d vs %d frames)" % (same, len(rp["sha"]), len(rs["sha"])))
    print("ops: poke %s  control %s  delta %s" % (format(rp["ops"], ","), format(rs["ops"], ","),
                                                   format(rp["ops"] - rs["ops"], ",")))
    look = np.array([f.get(22, 0) for f in P])
    pre = np.array([f.get(24, 0) for f in P])
    post = np.array([f.get(23, 0) for f in P])
    n = min(len(P), len(S))
    bindd = np.array([f["bind"] for f in P[:n]]) - np.array([f["bind"] for f in S[:n]])
    print("game frames: %d, things poked: %d distinct" % (len(P), len(set(rp["poked"]))))
    for nm, v in (("ptloc_walk lookup (fcall .. fret)", look), ("dirty prelude (read pos, sign-extend)", pre),
                  ("write_hex back + glue", post), ("bind_things delta vs control", bindd)):
        print("  %-40s min %9s  mean %9s  median %9s  max %9s" % (nm, format(int(v.min()), ","),
              format(int(v.mean()), ","), format(int(np.median(v)), ","), format(int(v.max()), ",")))
    if not same:
        print("!! the pixels differ -- the dirty path computed a different binding; do not use these numbers")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
