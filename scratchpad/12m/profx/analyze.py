"""Tables from an FJPROFX run (the dumps drive.py wrote under <WORK>).

    python analyze.py objects <prefix>            ops/frame per coarse object over the GAME frames, the
                                                  per-run averages (gamespeed's arithmetic) and the
                                                  per-frame distribution
    python analyze.py sub     <prefix> <objid>    one object split by the statements inside it
    python analyze.py calls   <prefix>            per-call cost by macro family (ops / entry count)
    python analyze.py fam     <prefix> fam1[,fam2] ...   per-instance rows for those families
    python analyze.py heavy   <prefix> [N]        the N heaviest game frames, by object

A game frame's interval runs from the previous present to its own present: the previous frame's
M1 reset plus this frame's work -- the same total gamespeed divides by 100.
Per-call costs: an instance is a unique label-path prefix ending at the macro; its ops are the
OWNER-attributed ops of the words whose nearest label carries that prefix; its calls are the
execution count of its `body` label if it has one (its locals sit before it and are data), else of
its lowest code label. Validated against an op trace by `profx.py --selftest`.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, default_fjm, labels, load_log, load_sparse, objects, work_dir  # noqa: E402

MENU = 2
PAT = re.compile(r"^(?:[sf]\d+:l(\d+):)?((?:rep\d+:)*)([\w.]+)(?:\((\d+)\))?$")


def resolve(prefix):
    p = Path(prefix)
    return str(p if p.is_absolute() else work_dir() / p)


def code_range():
    obj = objects()
    return min(v["lo"] for v in obj.values()), max(v["hi"] for v in obj.values())


def game_frames(prefix):
    """-> (per-frame object deltas [F, 256], per-frame total, per-frame output ops, run index, frame index,
    runs, rejected-owner count)"""
    runs = json.load(open(prefix + ".runs.json"))["runs"]
    log, _outside, _out, rej = load_log(prefix + ".log.bin")
    rows, runidx, fidx = [], [], []
    k = 0
    for ri, r in enumerate(runs):
        n = len(r["marks"])
        start = k
        k += n
        if r["name"] == "calibration":
            continue
        for g in range(MENU, n):
            rows.append(log[start + g] - log[start + g - 1])
            runidx.append(ri)
            fidx.append(g - MENU)
    d = np.array(rows)
    return d[:, 2:], d[:, 2:].sum(axis=1), d[:, 1], np.array(runidx), np.array(fidx), runs, rej


def cmd_objects(prefix):
    obj = objects()
    D, tot, outops, ri, fi, runs, rej = game_frames(prefix)
    F = len(tot)
    print("game frames: %d (runs: %d)   ops re-attributed from far unlabelled opaque ops: %s over the run"
          % (F, len(set(ri.tolist())), format(rej, ",")))
    print("mean ops/frame %s   median %s   min %s   max %s   p80(frame) %s"
          % tuple(format(int(x), ",") for x in (tot.mean(), np.median(tot), tot.min(), tot.max(),
                                                np.percentile(tot, 80))))
    print("output-bit ops/frame: mean %.0f" % outops.mean())
    print("")
    print("%-3s %-46s %12s %7s %11s %11s" % ("id", "object", "ops/frame", "%", "min/frame", "max/frame"))
    for k in np.argsort(-D.sum(axis=0)):
        s = D[:, k]
        if s.sum() == 0:
            continue
        nm = obj[k]["name"] if k in obj else ("(startup, before any owner)" if k == 0 else "obj%d" % k)
        print("%-3d %-46s %12s %6.2f%% %11s %11s" % (k, nm[:46], format(int(round(s.mean())), ","),
                                                   100.0 * s.sum() / tot.sum(), format(int(s.min()), ","),
                                                   format(int(s.max()), ",")))
    print("")
    cal = [r for r in runs if r["name"] == "calibration"]
    if cal:
        calops = cal[0]["ops"]
        print("per run: gamespeed's (run ops - calibration)/100  vs  the mean of this run's frame intervals")
        avgs = []
        for i in sorted(set(ri.tolist())):
            r = runs[i]
            gs = (r["ops"] - calops) / 100.0
            avgs.append(gs)
            print("  %-7s ops %s  -> %s ops/frame   frame-interval mean %s   min %s  max %s"
                  % (r["name"], format(r["ops"], ","), format(int(gs), ","), format(int(tot[ri == i].mean()), ","),
                     format(int(tot[ri == i].min()), ","), format(int(tot[ri == i].max()), ",")))
        s = sorted(avgs)
        p80 = s[min(len(s) - 1, int(np.ceil(0.8 * len(s))) - 1)]
        mean = sum(avgs) / len(avgs)
        print("binding (mean+p80)/2 = %s   mean %s   p80 %s" % (format(int((mean + p80) / 2), ","),
                                                                format(int(mean), ","), format(int(p80), ",")))
    pct = [0, 10, 25, 50, 75, 80, 90, 95, 99, 100]
    print("per-frame distribution: " + "  ".join("p%d=%s" % (p, format(int(np.percentile(tot, p)), ","))
                                                 for p in pct))


def label_ops(prefix, lo=None, hi=None):
    """owner-attributed ops summed by the owner word's nearest preceding label"""
    clo, chi = code_range()
    lo = 0 if lo is None else lo
    hi = chi if hi is None else hi
    la, ln = labels()
    w, c = load_sparse(prefix + ".incl.bin")
    m = (w >= lo) & (w < hi)
    idx = np.searchsorted(la, w[m], side="right") - 1
    idx[idx < 0] = 0
    return np.bincount(idx, weights=c[m], minlength=len(la))


def nframes(prefix):
    return len(game_frames(prefix)[1])


def cmd_sub(prefix, oid):
    obj = objects()
    o = obj[oid]
    la, ln = labels()
    s = label_ops(prefix, o["lo"], o["hi"])
    F = nframes(prefix)
    groups = defaultdict(float)
    for i in np.nonzero(s)[0]:
        parts = ln[i].split("---")
        key = "---".join(parts[:2]) if len(parts) > 1 else parts[0]
        groups[key] += s[i]
    tot = sum(groups.values())
    print("object %d %s: %s ops over the run = %s per game frame (the run's menu frames included, / %d game frames)"
          % (oid, o["name"], format(int(tot), ","), format(int(tot / F), ","), F))
    for k, v in sorted(groups.items(), key=lambda kv: -kv[1])[:40]:
        print("  %12s %6.2f%%  %s" % (format(int(v / F), ","), 100.0 * v / tot, k[:150]))


FAMILIES = ["hex.ptr_index", "hex.read_byte", "hex.write_byte", "hex.read_hex", "hex.write_hex",
            "hex.read_byte_and_inc", "hex.read_table_packed", "hex.mul", "hex.mul_const", "hex.mul_lo",
            "hex.fixed_mul_lo", "hex.cmp", "hex.scmp", "hex.mov", "hex.sparse_mov", "hex.add", "hex.sub",
            "hex.add_constant", "hex.xor", "hex.zero", "hex.set", "hex.if0", "hex.if_flags", "hex.inc", "hex.dec",
            "hex.shl_hex", "hex.shr_hex", "hex.shl_bit", "hex.shr_bit", "hex.div", "sim.thing_load",
            "sim.try_move", "sim.check_position", "sim.check_block", "sim.check_line", "sim.thing_pass",
            "sim.bind_things", "stream.emit_col_lines", "byte.emit", "m1.zerobyte", "proj.project_thing",
            "frame.thing_record_body", "hex.sign", "sim.point_side", "finesine.read_cos", "finesine.read_sin",
            "proj.wedge_setup", "stl.fcall", "kb.poll", "hex.input_hex", "hex.input",
            "frame.seg_pass1_leaf_body_lines", "frame.seg_pass1_leaf_body_ts", "frame.seg_pass2_leaf_body_lines",
            "proj.wedge_bbox", "frame.thing_load_cold", "stream.sprite_runs", "stream.sprite_runs_win",
            "frame.lines_spr_load", "frame.lines_spr_seed", "vpb_walk", "frame.read_byte5",
            "frame.write_byte5", "frame.ptr_index4", "stream.emit_region", "stream.emit_column"]

# the label table's file indices (fN) on the game tier, for printing call sites (cosmetic)
_GEN = "build/generated_" + default_fjm().stem
FILES = {"f2": "src/fj/fixed_point.fj", "f4": "src/fj/projection.fj", "f5": "src/fj/frame_render.fj",
         "f8": "src/fj/stream_render.fj", "f9": "src/fj/input.fj", "f10": "src/fj/sim.fj",
         "f12": _GEN + "/e1m1_01_tables.fj", "f13": _GEN + "/e1m1_02_main.fj",
         "f14": _GEN + "/e1m1_03_segconsts.fj", "f15": _GEN + "/e1m1_04_walk.fj",
         "f17": _GEN + "/e1m1_06_banks.fj", "f18": "src/fj/m1_reset.fj", "f19": _GEN + "/e1m1_07_reset.fj"}
_SRC = {}


def src_line(elem):
    m = re.match(r"^(f\d+):l(\d+):", elem)
    if not m or m.group(1) not in FILES:
        return ""
    f = ROOT / FILES[m.group(1)]
    if f not in _SRC:
        _SRC[f] = f.read_text(encoding="utf-8").split("\n") if f.exists() else []
    L = _SRC[f]
    k = int(m.group(2))
    return L[k - 1].strip() if k <= len(L) else ""


def instances(prefix, fams=FAMILIES):
    """{instance prefix: (owner-attributed ops over the run, entry count, entry word)}"""
    la, ln = labels()
    s = label_ops(prefix)
    ws, cs = load_sparse(prefix + ".self.bin")
    selfc = dict(zip(ws.tolist(), cs.tolist()))
    clo, chi = code_range()
    fam = set(fams)
    ops = defaultdict(float)
    first, body = {}, {}
    for i in range(len(la)):
        a = int(la[i])
        if a >= chi or a < clo:
            continue
        parts = ln[i].split("---")
        for p in range(len(parts) - 1):
            m = PAT.match(parts[p])
            if not m or m.group(3) not in fam:
                continue
            key = "---".join(parts[:p + 1])
            if key not in first or a < first[key]:
                first[key] = a
            if p == len(parts) - 2 and parts[-1] == "body":
                body[key] = a
            if s[i]:
                ops[key] += s[i]
    return {key: (ops.get(key, 0.0), selfc.get(body.get(key, a), 0), body.get(key, a)) for key, a in first.items()}


def macro_of(key):
    m = PAT.match(key.split("---")[-1])
    return m.group(3) if m else key


def macro_args(key):
    m = PAT.match(key.split("---")[-1])
    return "%s(%s)" % (m.group(3), m.group(4)) if m else key


def cmd_calls(prefix):
    F = nframes(prefix)
    inst = instances(prefix)
    by = defaultdict(list)
    for key, (ops, calls, a) in inst.items():
        if calls > 0 and ops > 0:
            by[macro_args(key)].append((ops / calls, calls, ops, key))
    print("per-call cost by family (owner-attributed ops / entry count); %d game frames" % F)
    print("%-28s %6s %11s %12s %9s %9s %9s %9s" % ("family(nargs)", "sites", "calls/fr", "ops/frame", "mean", "min",
                                                  "median", "max"))
    order = sorted(by, key=lambda k: (FAMILIES.index(k.split("(")[0]) if k.split("(")[0] in FAMILIES else 999, k))
    for famn in order:
        v = by[famn]
        per = np.array([x[0] for x in v])
        wts = np.array([x[1] for x in v], dtype=float)
        tot_ops = sum(x[2] for x in v)
        tot_calls = wts.sum()
        big = per[wts >= max(1, F / 10)]      # min/median/max over sites called >= once per 10 frames
        print("%-28s %6d %11.1f %12s %9.0f %9s %9s %9s" % (
            famn, len(v), tot_calls / F, format(int(tot_ops / F), ","), tot_ops / tot_calls,
            ("%.0f" % big.min()) if len(big) else "-", ("%.0f" % np.median(big)) if len(big) else "-",
            ("%.0f" % big.max()) if len(big) else "-"))


def cmd_fam(prefix, famnames, top=40, cache={}):
    F = nframes(prefix)
    if prefix not in cache:
        cache[prefix] = instances(prefix)
    rows = []
    for key, (ops, calls, a) in cache[prefix].items():
        if macro_of(key) in famnames and calls > 0:
            rows.append((ops / F, calls / F, ops / calls, src_line(key.split("---")[-1])[:70], key))
    rows.sort(key=lambda r: -r[0])
    print("family %s: %d executed instances; top %d by ops/frame" % (",".join(famnames), len(rows), top))
    print("%12s %10s %10s  %s" % ("ops/frame", "calls/fr", "ops/call", "call site  |  path head"))
    for r in rows[:top]:
        head = "---".join(p.split(":")[-1][:28] for p in r[4].split("---")[:3])
        print("%12s %10.2f %10.0f  %s  |  %s" % (format(int(r[0]), ","), r[1], r[2], r[3], head[:90]))


def cmd_heavy(prefix, n=10):
    obj = objects()
    D, tot, outops, ri, fi, runs, rej = game_frames(prefix)
    keys = [k for k in np.argsort(-D.sum(axis=0)) if D[:, k].sum() > 0][:9]
    print("heaviest game frames (ops) and their biggest objects; the mean frame for reference")
    print("%-10s %11s " % ("run:frame", "total") + " ".join("%10s" % obj.get(k, {"name": "o%d" % k})["name"][:10]
                                                         for k in keys))
    print("%-10s %11s " % ("mean", format(int(tot.mean()), ",")) + " ".join("%10s" % format(int(D[:, k].mean()), ",")
                                                                         for k in keys))
    for i in np.argsort(-tot)[:n]:
        print("%-10s %11s " % ("%s:%d" % (runs[ri[i]]["name"].replace("game", "g"), fi[i]), format(int(tot[i]), ","))
              + " ".join("%10s" % format(int(D[i, k]), ",") for k in keys))


if __name__ == "__main__":
    cmd, prefix = sys.argv[1], resolve(sys.argv[2])
    if cmd == "objects":
        cmd_objects(prefix)
    elif cmd == "sub":
        cmd_sub(prefix, int(sys.argv[3]))
    elif cmd == "calls":
        cmd_calls(prefix)
    elif cmd == "heavy":
        cmd_heavy(prefix, int(sys.argv[3]) if len(sys.argv) > 3 else 10)
    elif cmd == "fam":
        for group in sys.argv[3:]:
            cmd_fam(prefix, group.split(","))
            print("")
    else:
        raise SystemExit(__doc__)
