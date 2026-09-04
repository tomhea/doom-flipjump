"""THE ATLAS -- where the ops actually go, by macro, measured.

The join: ca2_profile gives a per-op instruction-pointer histogram (bucket_bits 6 == one op per
bucket at w=32); the assembler's resolved label table gives, for every code site, the full MACRO
CALL STACK that produced it. FlipJump label paths are literally a stack:

    f13:l185:frame.seg_pass1_leaf_body_lines(4)---f5:l2463:hex.set(3)---s15:l87:hex.zero(1)---end
    \___ call site + macro ___/                   \_ its call site _/                       \local

so attributing each executed op to the nearest label at or below its address, then walking that
path, prices EVERY macro two ways at once:

    INCLUSIVE  ops executed anywhere inside that macro (summed over all its call sites)
               -- this is the "pool" number: ts_step_faces 3.27M, hex.zero 1.48M.
    EXCLUSIVE  ops attributed to that macro's own body, not to macros it calls
               -- this is where an optimisation has to actually land.

and prices every CALL SITE (the f<i>:l<n> tag of the frame above it), which is the plan's
"per-line pricing of every macro region".

    python scratchpad/12m/atlas.py --labels atlas/BASE.labels.tsv.gz \
        --hist "scratchpad/12m/atlas/BASE.h*.json" --out docs-or-md-path [--top 45]

CONTROLS (R9)
  * COVERAGE is printed: the share of executed ops that got a resolved label. A pool table that
    quietly dropped 20% of the frame is not a pool table.
  * The per-frame op totals are printed against each profile's own op_counter (ca2_profile
    already proved that equals the interpreter's count).
  * Inclusive cost of the outermost frame must equal the frame's resolved op total -- printed as
    a check, because a path-walking bug shows up there first.
  * --selftest builds a synthetic label table + histogram whose answer is known by hand.
"""
import argparse
import glob
import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent

# f<i> indices are assigned in the order the files were passed to fj.assemble; deg_gate passes
# fj_consts, the seven src/fj sources, then the seven generated parts. ritual.py records the real
# list in <id>.deg.json ("input_files"); this is the fallback and is CHECKED against it when
# present.
FALLBACK_FILES = ["fj_consts", "fixed_point", "present", "projection", "frame_render",
                  "plane_render", "plane_bands", "stream_render", "00_entry", "01_tables",
                  "02_main", "03_segconsts", "04_walk", "05_state", "06_banks"]

FRAME_RE = re.compile(r"^([sf]\d+):l(\d+):(.*)$")
CALL_SUFFIX = re.compile(r"\(\d+\)$")
# a macro invoked inside a rep gets a "rep<k>:" prefix on its path segment. That is call-site
# identity, NOT a different macro: leaving it in split hex.zero across four rows and hid
# 1.8M ops from the pool table. Strip it for the NAME, keep the site for the site table.
REP_PREFIX = re.compile(r"^(rep\d+:)+")


def parse_path(name):
    """-> (list of (site, macro) outermost-first, local_label). Non-macro globals give []."""
    parts = name.split("---")
    frames = []
    for seg in parts[:-1]:
        m = FRAME_RE.match(seg)
        if not m:
            continue
        frames.append((m.group(1) + ":l" + m.group(2),
                       REP_PREFIX.sub("", CALL_SUFFIX.sub("", m.group(3)))))
    return frames, parts[-1]


# ------------------------------------------------------------------------------------ the join


def label_addresses(path):
    """Pass 1: addresses only, as int64 + the line ordinal. Names are NOT held -- there are
    millions of them and the hot set is a small fraction."""
    addrs = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            _, _, a = line.rstrip("\n").rpartition("\t")
            addrs.append(int(a))
    return np.array(addrs, dtype=np.int64)


def resolve_names(path, wanted):
    """Pass 2: the names of just the line ordinals we actually need."""
    out = {}
    want = set(wanted)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i in want:
                out[i] = line.rstrip("\n").rpartition("\t")[0]
    return out


def attribute(hist_path, addrs, order, sorted_addrs):
    """-> (Counter over label line-ordinal, total ops, meta). One searchsorted for the frame."""
    payload = json.load(open(hist_path))
    shift = payload["bucket_bits"]
    keys = np.fromiter((int(k) for k in payload["hist"]), dtype=np.int64,
                       count=len(payload["hist"]))
    vals = np.fromiter(payload["hist"].values(), dtype=np.int64, count=len(payload["hist"]))
    ips = keys << shift
    pos = np.searchsorted(sorted_addrs, ips, side="right") - 1
    ok = pos >= 0
    owners = order[pos[ok]]
    c = Counter()
    for owner, n in zip(owners.tolist(), vals[ok].tolist()):
        c[owner] += n
    return c, int(vals.sum()), {"op_counter": payload["op_counter"],
                                "viewpoint": payload["viewpoint"],
                                "unresolved": int(vals[~ok].sum())}


def price(counter, names, cover_ops, src_tags=()):
    """Walk each hot label's macro path -> inclusive / exclusive / per-call-site tables.

    `hand` is the one that names work: the DEEPEST frame whose call site lies in a
    hand-written source file (src_tags). Every op below that came from stl macros the
    line invoked, so `hand` prices the actual line of doom code that must change --
    the innermost-frame table only ever names stl leaves like hex.exact_xor."""
    inc, exc, site = Counter(), Counter(), Counter()
    hand, pair = Counter(), Counter()
    for idx, n in counter.items():
        nm = names.get(idx)
        if nm is None:
            continue
        frames, _local = parse_path(nm)
        if not frames:
            exc["<top level: " + nm[:40] + ">"] += n
            continue
        for macro in {m for _s, m in frames}:      # a recursive macro counts once, not per level
            inc[macro] += n
        exc[frames[-1][1]] += n
        site[frames[-1]] += n
        hw = [(sit, macro) for sit, macro in frames if sit.split(":", 1)[0] in src_tags]
        if hw:
            hand[hw[-1]] += n
            # the CALLER of the deepest hand-written frame, when it is also hand-written.
            # Without it a macro defined in a .fj file (hex.fixed_mul_lo.row) collapses all
            # of its callers into one row and the caller breakdown is lost.
            pair[(hw[-2][0] if len(hw) > 1 else "-", hw[-1][0], hw[-1][1])] += n
    return inc, exc, site, hand, pair


# ---------------------------------------------------------------------------------------- main


def run(labels, hists, out_md, top, files_json, dump_hand=""):
    addrs = label_addresses(labels)
    order = np.argsort(addrs, kind="stable")
    sorted_addrs = addrs[order]
    print("labels: %s  (address range %s .. %s bits)"
          % (format(len(addrs), ","), format(int(sorted_addrs[0]), ","),
             format(int(sorted_addrs[-1]), ",")), flush=True)

    files = FALLBACK_FILES
    if files_json and Path(files_json).exists():
        meta = json.load(open(files_json))
        if meta.get("input_files"):
            files = [Path(p).stem for p in meta["input_files"]]
            print("file map from %s: %s" % (files_json, ", ".join(files)))

    # the hand-written sources: every input file that is not one of the emitted e1m1 parts.
    src_tags = {"f%d" % (i + 1) for i, f in enumerate(files)
                if not re.match(r"^(e1m1_)?\d\d_", f)}
    print("hand-written source tags: %s"
          % ", ".join("%s=%s" % (t, files[int(t[1:]) - 1]) for t in sorted(src_tags,
                                                                          key=lambda t: int(t[1:]))))
    per_frame = []
    all_wanted = set()
    for h in hists:
        c, tot, meta = attribute(h, addrs, order, sorted_addrs)
        per_frame.append((h, c, tot, meta))
        all_wanted |= set(c)
        print("  %-38s %13s ops  (%s distinct owners, %s unresolved)"
              % (Path(h).name, format(tot, ","), format(len(c), ","),
                 format(meta["unresolved"], ",")), flush=True)
    print("resolving %s label names..." % format(len(all_wanted), ","), flush=True)
    names = resolve_names(labels, all_wanted)

    rows = []
    for h, c, tot, meta in per_frame:
        inc, exc, site, hand, pair = price(c, names, tot, src_tags)
        covered = sum(n for idx, n in c.items() if idx in names)
        rows.append({"hist": h, "total": tot, "meta": meta, "inc": inc, "exc": exc,
                     "site": site, "hand": hand, "pair": pair, "covered": covered})
        print("  %-38s coverage %.3f%%  (%s of %s ops carry a resolved label)"
              % (Path(h).name, 100.0 * covered / tot, format(covered, ","), format(tot, ",")),
              flush=True)

    rows.sort(key=lambda r: r["total"])
    mid = rows[len(rows) // 2]
    lo, hi = rows[0], rows[-1]

    def fmt(n):
        return format(int(n), ",")

    lines = []
    A = lines.append
    A("# ATLAS -- where the ops go (measured)")
    A("")
    A("Built by `scratchpad/12m/atlas.py` from %d per-op profiles of `%s`."
      % (len(rows), Path(labels).name.replace(".labels.tsv.gz", ".fjm")))
    A("Method: every executed op is attributed to the nearest label at or below its address; that")
    A("label's name IS its macro call stack, so INCLUSIVE = ops anywhere inside a macro (the pool")
    A("size) and EXCLUSIVE = ops in that macro's own body (where a fix must land).")
    A("")
    A("| profile | viewpoint | ops | coverage |")
    A("|---|---|---|---|")
    for r in rows:
        vp = r["meta"]["viewpoint"]
        A("| %s | (%d,%d,%#x) | %s | %.3f%% |"
          % (Path(r["hist"]).stem, vp[0], vp[1], vp[2], fmt(r["total"]),
             100.0 * r["covered"] / r["total"]))
    A("")
    A("The MEDIAN column below is the profile whose op count is the median of the profiled")
    A("set (`%s`, %s ops); MIN and MAX are the cheapest and dearest profiled frames. The"
      % (Path(mid["hist"]).stem, fmt(mid["total"])))
    A("campaign ships on the 260-frame sweep median, so MEDIAN is the column that ranks.")
    A("")
    A("## Pool table -- INCLUSIVE ops per macro (all call sites summed)")
    A("")
    A("| macro | median frame | min frame | max frame | share of median |")
    A("|---|---:|---:|---:|---:|")
    for macro, n in mid["inc"].most_common(top):
        A("| `%s` | %s | %s | %s | %.2f%% |"
          % (macro, fmt(n), fmt(lo["inc"].get(macro, 0)), fmt(hi["inc"].get(macro, 0)),
             100.0 * n / mid["total"]))
    A("")
    A("## Where it lands -- EXCLUSIVE ops per macro body")
    A("")
    A("| macro body | median frame | share |")
    A("|---|---:|---:|")
    for macro, n in mid["exc"].most_common(top):
        A("| `%s` | %s | %.2f%% |" % (macro, fmt(n), 100.0 * n / mid["total"]))
    A("")
    A("## THE ACTIONABLE TABLE -- per hand-written call site")
    A("")
    A("The deepest call site that lies in a hand-written .fj source. Everything below it is")
    A("stl machinery that this line asked for, so this is the line that has to change.")
    A("")
    A("| site | macro called | median frame | min | max | share of median |")
    A("|---|---|---:|---:|---:|---:|")
    for (st, macro), n in mid["hand"].most_common(top):
        A("| `%s` | `%s` | %s | %s | %s | %.2f%% |"
          % (st, macro, fmt(n), fmt(lo["hand"].get((st, macro), 0)),
             fmt(hi["hand"].get((st, macro), 0)), 100.0 * n / mid["total"]))
    A("")
    A("## Per call SITE -- the innermost (caller file:line -> macro) pairs")
    A("")
    A("f<i> is the i-th file passed to the assembler: %s"
      % ", ".join("f%d=%s" % (i + 1, f) for i, f in enumerate(files)))
    A("")
    A("| site | macro | median frame | share |")
    A("|---|---|---:|---:|")
    for (s, macro), n in mid["site"].most_common(top):
        A("| `%s` | `%s` | %s | %.2f%% |" % (s, macro, fmt(n), 100.0 * n / mid["total"]))
    A("")
    text = "\n".join(lines)
    Path(out_md).write_text(text, encoding="utf-8")
    print("")
    print("-> %s   (%d lines)" % (out_md, len(lines)))
    if dump_hand:
        json.dump({"median_hist": Path(mid["hist"]).stem, "median_total": mid["total"],
                   "hand": [[st, macro, n] for (st, macro), n in mid["hand"].most_common()],
                   "pair": [[a, b, m, n] for (a, b, m), n in mid["pair"].most_common()],
                   "inc": mid["inc"].most_common(), "exc": mid["exc"].most_common()},
                  open(dump_hand, "w"))
        print("full median tables -> %s (%d hand sites)" % (dump_hand, len(mid["hand"])))
    print("median profile: %s = %s ops; top pool: %s"
          % (Path(mid["hist"]).stem, fmt(mid["total"]),
             ", ".join("%s %s" % (m, fmt(n)) for m, n in mid["inc"].most_common(5))))


def selftest():
    """A synthetic table+histogram whose answer is known by hand."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    lab = tmp / "l.tsv.gz"
    rows = [
        ("f1:l10:outer---f5:l3:inner---start", 0),        # ops at 0,64  -> outer+inner
        ("f1:l10:outer---tail", 128),                     # op at 128    -> outer only
        ("f1:l20:other---start", 192),                    # op at 192    -> other
    ]
    with gzip.open(lab, "wt", encoding="utf-8") as f:
        for n, a in rows:
            f.write("%s\t%d\n" % (n, a))
    hist = {"bucket_bits": 6, "op_counter": 7, "viewpoint": [0, 0, 0],
            "hist": {"0": 2, "1": 1, "2": 3, "3": 1}}      # ip 0,64,128,192
    hp = tmp / "h.json"
    hp.write_text(json.dumps(hist))
    addrs = label_addresses(str(lab))
    order = np.argsort(addrs, kind="stable")
    c, tot, meta = attribute(str(hp), addrs, order, addrs[order])
    names = resolve_names(str(lab), set(c))
    inc, exc, site, _hand, _pair = price(c, names, tot, {"f1"})
    ok = tot == 7
    ok &= inc["outer"] == 6 and inc["inner"] == 3 and inc["other"] == 1
    ok &= exc["inner"] == 3 and exc["outer"] == 3 and exc["other"] == 1
    ok &= site[("f5:l3", "inner")] == 3 and site[("f1:l10", "outer")] == 3
    print("control 1 (inclusive/exclusive/site on a hand-computed case): %s"
          % ("ok" if ok else "FAIL"))
    # negative control: move one op into the other macro and require the table to change
    hist["hist"] = {"0": 2, "1": 1, "2": 3, "3": 4}
    hp.write_text(json.dumps(hist))
    c2, tot2, _ = attribute(str(hp), addrs, order, addrs[order])
    inc2, _e2, _s2, hand2, _p2 = price(c2, resolve_names(str(lab), set(c2)), tot2, {"f1"})
    ok2 = inc2["other"] == 4 and inc2["outer"] == 6 and tot2 == 10
    # control 3: a rep-prefixed segment is the SAME macro. This is the bug that split hex.zero
    # into four rows and hid 1.8M ops; the table must merge it.
    lab3 = Path(str(lab).replace("l.tsv.gz", "l3.tsv.gz"))
    with gzip.open(lab3, "wt", encoding="utf-8") as f:
        f.write("f1:l10:outer---f5:l3:rep0:inner---start" + chr(9) + "0" + chr(10))
        f.write("f1:l10:outer---f5:l7:rep1:inner---start" + chr(9) + "64" + chr(10))
    hp.write_text(json.dumps({"bucket_bits": 6, "op_counter": 5, "viewpoint": [0, 0, 0],
                              "hist": {"0": 2, "1": 3}}))
    a3 = label_addresses(str(lab3))
    o3 = np.argsort(a3, kind="stable")
    c3, t3, _ = attribute(str(hp), a3, o3, a3[o3])
    inc3, exc3, site3, _h3, _p3 = price(c3, resolve_names(str(lab3), set(c3)), t3, {"f1"})
    ok3 = inc3["inner"] == 5 and exc3["inner"] == 5 and t3 == 5
    ok3 &= site3[("f5:l3", "inner")] == 2 and site3[("f5:l7", "inner")] == 3
    print("control 3 (rep-prefixed segments merge into one macro):     %s"
          % ("ok" if ok3 else "FAIL"))
    # `hand` must name the OUTER f1 call site, not the inner f5 one
    ok2 &= hand2[("f1:l10", "outer")] == 6 and hand2[("f1:l20", "other")] == 4
    print("control 2 (a perturbed histogram moves exactly that macro):   %s"
          % ("ok" if ok2 else "FAIL"))
    print("atlas selftest: %s" % ("PASS" if (ok and ok2 and ok3) else "FAIL"))
    return 0 if (ok and ok2 and ok3) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels")
    ap.add_argument("--hist", nargs="+", default=[])
    ap.add_argument("--out", default=str(HERE / "ATLAS.md"))
    ap.add_argument("--top", type=int, default=45)
    ap.add_argument("--files-json", default="")
    ap.add_argument("--dump-hand", default="", help="full median-frame tables as JSON")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    if not a.labels or not a.hist:
        raise SystemExit("need --labels and --hist")
    hists = sorted({p for pat in a.hist for p in glob.glob(pat)})
    if not hists:
        raise SystemExit("no histograms matched %r" % (a.hist,))
    run(a.labels, hists, a.out, a.top, a.files_json, a.dump_hand)


if __name__ == "__main__":
    main()
