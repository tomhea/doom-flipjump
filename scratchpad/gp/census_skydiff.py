"""S5 -- what adding `sky` (and `bbox_cull`) to the census keywords changed, frame by frame.

    python scratchpad/gp/census_skydiff.py OLD_DIR NEW_DIR OLD_SNAPSHOT NEW_SNAPSHOT [OLD_EXTRA_DIR...]
    python scratchpad/gp/census_skydiff.py OLD_DIR NEW_DIR - - [OLD_EXTRA_DIR...]     (staged fights)

OLD = the census rendered WITHOUT `sky`/`bbox_cull` (census_out/s4 + s4_rec, an older S4 draft);
NEW = with them (census_out/s4v1). Only runs whose checkpoint and keys are IDENTICAL in the two
snapshots are compared, so the model's trajectory is the same and every difference is the renderer's:
  * `bbox_cull` is a stop -- it may only remove ARRIVALS (things in subtrees wholly off the view
    wedge). It must not change any accepted projection (`acc`) or anything drawn;
  * `sky` changes the picture on frames that show sky (the V2 rule suppresses uppers between two sky
    ceilings, so walls that used to hide sprites may not) -- every drawn-derived count may move there.
The report lists, per run, how many (frame, picture) records moved in each field class.
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

old_dir, new_dir, old_snap, new_snap = (Path(p) for p in sys.argv[1:5])
old_extra = [Path(p) for p in sys.argv[5:]]          # e.g. census_out/s4_rec (rec rendered apart)
PFX = "s4_"
if str(old_snap) == "-":            # the STAGED fights: fixed scripts, so every common run compares
    PFX = ""
    same = sorted({p.stem for p in old_dir.glob("*.jsonl")} & {p.stem for p in new_dir.glob("*.jsonl")})
    print("staged runs present in both directories: %s" % ", ".join(same))
else:
    O = {r["name"]: r for r in json.loads(old_snap.read_text())["runs"]}
    N = {r["name"]: r for r in json.loads(new_snap.read_text())["runs"]}
    same = [n for n in N if n in O and O[n]["checkpoint"] == N[n]["checkpoint"]
            and O[n]["keys"] == N[n]["keys"]]
    print("runs with identical checkpoint and keys in both snapshots: %d of %d (%s differ)"
          % (len(same), len(N), ", ".join(n for n in N if n not in same) or "none"))

DRAWN = ("colsA", "colsB", "runs", "deg", "small", "inv", "inv_pairs", "near_hidden",
         "corpses_acc_soft", "live_deg_after_corpse", "drawn", "cols_role")
SIGHT = ("aim",)


def load(paths):
    out = {}
    for p in paths:
        if not p.exists():
            continue
        for line in open(p):
            r = json.loads(line)
            out[(r["tic"], r["variant"])] = r
    return out


def seen_core(r):
    s = dict(r["seen"])
    w = dict(s.pop("why"))
    # the cull turns "out of view" into "not reached": the same fact, a different reason
    w["off"] = w.pop("out of view", 0) + w.pop("not reached", 0)
    return s, w


tot = Counter()
for n in same:
    o = load([old_dir / ("%s%s.jsonl" % (PFX, n))] + [d / ("%s%s.jsonl" % (PFX, n)) for d in old_extra])
    nw = load([new_dir / ("%s%s.jsonl" % (PFX, n))])
    keys = sorted(set(o) & set(nw))
    c = Counter()
    moved_frames = defaultdict(set)
    d_arr = []
    for k in keys:
        a, b = o[k], nw[k]
        c["records"] += 1
        d_arr.append((a["arr_rt"] + a["arr_bk"], b["arr_rt"] + b["arr_bk"]))
        if a["acc"] != b["acc"]:
            c["acc MOVED (the cull must not)"] += 1
        if any(a.get(f) != b.get(f) for f in DRAWN):
            c["drawn-derived moved"] += 1
            moved_frames["drawn"].add(k[0])
        if any(a.get(f) != b.get(f) for f in SIGHT):
            c["aim moved"] += 1
            moved_frames["aim"].add(k[0])
        if seen_core(a) != seen_core(b):
            c["seen moved"] += 1
            moved_frames["seen"].add(k[0])
    tot.update(c)
    ao = sum(x for x, _ in d_arr) / max(1, len(d_arr))
    an = sum(y for _, y in d_arr) / max(1, len(d_arr))
    print("  %-20s %4d records | arrivals/record %.1f -> %.1f | %s | frames moved: drawn %d, aim %d, seen %d"
          % (n, c["records"], ao, an,
             ", ".join("%s %d" % kv for kv in sorted(c.items()) if kv[0] != "records") or "nothing moved",
             len(moved_frames["drawn"]), len(moved_frames["aim"]), len(moved_frames["seen"])))
print("TOTAL: %s" % ", ".join("%s %d" % kv for kv in sorted(tot.items())))

# NEGATIVE CONTROL (R9): the same comparator, fed the OLD 'game' picture against the NEW 'abcd'
# picture of the same frames (a real compositor change), must report moves -- and a single field
# mutated in one record must be caught. Otherwise "nothing moved" above proves nothing.
neg = Counter()
for n in same:
    o = load([old_dir / ("%s%s.jsonl" % (PFX, n))])
    nw = load([new_dir / ("%s%s.jsonl" % (PFX, n))])
    for (tic, v), a in o.items():
        b = nw.get((tic, "abcd"))
        if v != "game" or b is None:
            continue
        neg["pairs"] += 1
        neg["drawn-derived moved"] += any(a.get(f) != b.get(f) for f in DRAWN)
k0 = next(iter(sorted(load([new_dir / ("%s%s.jsonl" % (PFX, same[0]))]).items())))
mut = json.loads(json.dumps(k0[1]))
mut["colsA"] += 1
caught = any(k0[1].get(f) != mut.get(f) for f in DRAWN)
print("NEGATIVE CONTROL: old 'game' vs new 'abcd' on the same frames -> %d of %d records moved; one"
      " mutated colsA %s -> %s" % (neg["drawn-derived moved"], neg["pairs"],
                                   "caught" if caught else "!! MISSED",
                                   "the comparison has teeth" if neg["drawn-derived moved"] and caught
                                   else "!! VACUOUS"))
