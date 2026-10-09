"""P8a's new code, priced on drive_b0's per-run dumps: owner-attributed ops by SOURCE LINE, new vs old, by family.

    python b0_families.py <prefix> --old-gen DIR [--old-ref 3fab6c1] [--gen DIR] [--labels TSV] [--top N]

WHAT IS "NEW". The generated program's parts (<gen>/e1m1_0*.fj) are diffed against the pre-P8a build's (--old-gen:
blocked51's), and src/fj/*.fj against git --old-ref (3fab6c1, the commit blocked51 shipped from), with `git diff -U0`.
A line on the new side of a hunk is NEW: INSERTED (the hunk removed nothing) or CHANGED (it replaced old lines --
code that existed before P8a and was edited in place; its whole cost is counted, not a delta).

WHICH LINE AN OP BELONGS TO. profx's rule (analyze.label_ops): an owner word's ops go to its nearest preceding label.
A label's line is the INNERMOST doom-authored element of its path (`fN:lL:` -- a generated part or a src/fj macro
body; the stl's `sN` files are not doom's), so an op inside `sim.thing_pass_depth` lands on the sim.fj line it runs,
not on the call. A plain (top-level) label's line is the first statement after its definition.

FAMILIES (docs/gp-final-plan.md 1.2.3, 3.0, 4.2): a NEW line is classed by the nearest preceding plain label (its
region: kb_*, kq_*, hs_*, sf_*, pt_*, mt_load ...) and else by the cells its text names (FAMILY_RULES, first match).

PER RUN: a run's game-frame ops = its histogram minus the calibration's (startup + menu are identical in every run
up to the first game frame's poke: the per-run totals equal B0's avg x 100 -- drive_b0.py check). Statistic over the
runs: B0's (mean + p80) / 2, p80 = gamespeed.percentile_run (the run at ceil(0.8 n)).
"""
import argparse
import json
import math
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, labels, load_sparse, work_dir  # noqa: E402

ELEM = re.compile(r"^(f\d+):l(\d+):")
DEF = re.compile(r"^\s*([A-Za-z_][\w.]*):\s*(//.*)?$")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# (family, region-label regex, line-text regex) -- first match wins; region = nearest preceding plain label
FAMILY_RULES = [
    ("knockback (kb_*, kbs*, kq_*, mkx/mky/mfx/mfy)",
     r"^(kb|kq_|kql|kbs|kbm|kbt|kblw|kbwo|kbp_|dm_kb)", r"\b(kb_\w+|kbs\d*\w*|kq_\w+|kbbz|p_kmx|p_kmy|mkx|mky|mfx|mfy|pj_z)\b"),
    ("infight: target load (mt_load, mtl_*)", r"^(mt_load|mtl_)", r"\bmt_load\b"),
    ("infight: angle leaf (ia_leaf)", r"^ia_", r"\bia_\w+\b"),
    ("infight: bullets' scan (hs_*)", r"^(hs_|hsc_|hsw_)", r"\b(hs_\w+|hwtr)\b"),
    ("infight: far LOS (sl_far, sf_*, sfw_*)", r"^(sl_far|sf_|sfw_)", r"\b(sl_far|sf_\w+|sfw_\w+)\b"),
    ("infight: fireball thing test (pt_*)", r"^(pt_|pj_tm)", r"\b(pt_\w+|pj_tm|pw_z)\b"),
    ("infight: dm_src / bar_src", r"^(dm_sw|dmb_|bl_sp)", r"\b(dm_src|bar_src|bd_src|bl_src|bl_sp|dmb_src)\b"),
    ("dying view (p_vd, view drop)", r"^(dtt_v|lnd_vd)", r"\bp_vd\b"),
    ("compositor D3 (rank, sp_ex, rt_rank)", r"^$", r"\b(sp_ex|td_rk|rank_key)\b"),
    ("infight: other (decisions/attacks at the target, acquire)", r"^(mw\d+_(aan|acq|sp)$|mm_as_far|md_mel_m|md_bul_)",
     r"\b(mon_target|mt_pl|mt_al|mbsd|mt_tg\w*|mt_tq\w+|mt_reach|md_fa|mm_fa)\b"),
    ("sight cell lists (sl_*; near LOS rewritten in place, shared with the far LOS)", r"^(sl_|sg\d)", r"\bsl_\w+\b"),
]
FAMILY_ORDER = [f for f, _r, _t in FAMILY_RULES] + ["new, unclassified"]
P8A_REQUESTED = FAMILY_ORDER[:9]          # the families the criterion names


def percentile_run(v, pct=0.8):
    s = sorted(v)
    return s[min(len(s) - 1, math.ceil(pct * len(s)) - 1)]


NUM = re.compile(r"\d+")


def new_lines(old, new, git_ref=None):
    """{new-side line: 'ins' | 'chg' | 'reloc'} -- 'reloc': a changed line equal, with every number masked, to a line
    the diff removed (a relocated address or a re-baked constant: the reset part's re-keyed zero runs, the sight
    lists' cell constants). Relocations are counted as OLD code."""
    if git_ref:
        rel = Path(new).resolve().relative_to(ROOT).as_posix()
        cmd = ["git", "-C", str(ROOT), "diff", "-U0", "--no-color", git_ref, "--", rel]
    else:
        cmd = ["git", "diff", "--no-index", "-U0", "--no-color", str(old), str(new)]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    res, removed, added = {}, defaultdict(int), []
    cur = 0
    for line in out.splitlines():
        m = HUNK.match(line)
        if m:
            b = 1 if m.group(2) is None else int(m.group(2))
            c, d = int(m.group(3)), 1 if m.group(4) is None else int(m.group(4))
            for k in range(c, c + d):
                res[k] = "ins" if b == 0 else "chg"
            cur = c
        elif line.startswith("-") and not line.startswith("---"):
            removed[NUM.sub("#", line[1:].strip())] += 1
        elif line.startswith("+") and not line.startswith("+++"):
            added.append((cur, NUM.sub("#", line[1:].strip())))
            cur += 1
    for k, t in added:
        if res.get(k) == "chg" and removed.get(t, 0) > 0:
            removed[t] -= 1
            res[k] = "reloc"
    return res


def file_map(ln, cands):
    """{fN: Path} -- each fN is the candidate whose lines carry its elements' macro names"""
    samples = defaultdict(list)
    for n in ln:
        for e in n.split("---")[:-1]:
            m = re.match(r"^(f\d+):l(\d+):(?:rep\d+:)*([\w.]+)", e)
            if m and len(samples[m.group(1)]) < 400:
                samples[m.group(1)].append((int(m.group(2)), m.group(3).split(".")[-1]))
    texts = {c: c.read_text(encoding="utf-8").split("\n") for c in cands}
    fmap = {}
    for f, sm in samples.items():
        best, score = None, 0.0
        for c, L in texts.items():
            ok = sum(1 for k, mac in sm if k <= len(L) and mac in L[k - 1])
            if ok / len(sm) > score:
                best, score = c, ok / len(sm)
        if score >= 0.9:
            fmap[f] = best
    return fmap, texts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefix")
    ap.add_argument("--old-gen", required=True)
    ap.add_argument("--old-ref", default="3fab6c1")
    ap.add_argument("--gen", default=str(ROOT / "build" / "generated_doom_e1m1_blocked53"))
    ap.add_argument("--labels", default=str(ROOT / "scratchpad" / "12m" / "atlas" / "blocked53.labels.tsv.gz"))
    ap.add_argument("--top", type=int, default=6)
    ap.add_argument("--top-unclassified", type=int, default=25)
    a = ap.parse_args()
    prefix = Path(a.prefix) if Path(a.prefix).is_absolute() else work_dir() / a.prefix
    runs = json.loads(Path(str(prefix) + ".runs.json").read_text())["runs"]
    la, ln = labels(a.labels)
    gen = sorted(Path(a.gen).glob("e1m1_0*.fj"))
    lib = sorted((ROOT / "src" / "fj").glob("*.fj"))
    fmap, texts = file_map(ln, gen + lib)
    print("file map: " + ", ".join("%s=%s" % (k, v.name) for k, v in sorted(fmap.items(), key=lambda kv: int(kv[0][1:]))))
    newl = {}
    for g in gen:
        newl[g] = new_lines(Path(a.old_gen) / g.name, g)
    for f in lib:
        newl[f] = new_lines(None, f, a.old_ref)
    print("new lines: " + ", ".join("%s +%d (ins %d, chg %d, reloc %d)" % (
        k.name, len(v), sum(x == "ins" for x in v.values()), sum(x == "chg" for x in v.values()),
        sum(x == "reloc" for x in v.values()))
                                    for k, v in newl.items() if v))
    # plain-label definitions in the generated parts -> (file, first statement line)
    pdef = {}
    for g in gen:
        L = texts[g]
        for i, t in enumerate(L):
            m = DEF.match(t)
            if m:
                k = i + 1
                while k < len(L) and k < i + 25 and (not L[k].strip() or L[k].strip().startswith("//")
                                                    or DEF.match(L[k])):
                    k += 1
                pdef[m.group(1)] = (g, k + 1 if k < len(L) else i + 1)
    plain = np.array(["---" not in n and not ELEM.match(n) for n in ln])
    plain_idx = np.nonzero(plain)[0]

    # every run's owner histogram, minus the calibration's, by label
    cal = runs[0]
    assert cal["name"] == "calibration"

    def by_label(r):
        w, c = load_sparse(str(prefix.parent / r["dump"]) + ".incl.bin")
        idx = np.searchsorted(la, w, side="right") - 1
        idx[idx < 0] = 0
        return np.bincount(idx, weights=c, minlength=len(la))
    base = by_label(cal)
    game = [r for r in runs[1:]]
    per = np.array([by_label(r) - base for r in game])           # [runs, labels]
    tot_run = per.sum(axis=1)
    nz = np.nonzero(np.abs(per).sum(axis=0))[0]

    def line_of(i):
        n = ln[i]
        if plain[i]:
            return pdef.get(n, (None, None))
        best = (None, None)
        for e in n.split("---")[:-1]:
            m = ELEM.match(e)
            if m and m.group(1) in fmap:
                best = (fmap[m.group(1)], int(m.group(2)))
        return best

    LIBCALL = re.compile(r"^\s*(frame|sim|stream|proj|finesine|fixed)\.\w+ ")
    old_call = [np.zeros(len(game))]
    reloc = [np.zeros(len(game))]
    fam_ops = defaultdict(lambda: np.zeros(len(game)))
    kind_ops = defaultdict(lambda: np.zeros(len(game)))
    lines_ops = defaultdict(lambda: np.zeros(len(game)))
    for i in nz:
        f, k = line_of(i)
        kind = newl.get(f, {}).get(k) if f is not None else None
        text = texts[f][k - 1] if f is not None and k - 1 < len(texts[f]) else ""
        if kind == "chg" and LIBCALL.match(text):
            # the innermost doom element is a CHANGED CALL of a src/fj macro (its arguments grew: thing_record_body's
            # sp_ex): the op runs in the macro body behind one of its local labels -- old code; its new lines (the
            # sp_ex tests) carry their own f5 / f10 elements and are counted there
            kind = "reloc"
            old_call[0] += per[:, i]
        if kind in (None, "reloc"):
            fam_ops["(old code: unchanged lines, and non-doom code)"] += per[:, i]
            if kind == "reloc":
                reloc[0] += per[:, i]
            continue
        j = plain_idx[np.searchsorted(plain_idx, i, side="right") - 1]
        region = ln[j]
        fam = "new, unclassified"
        for name, rre, tre in FAMILY_RULES:
            if (f in lib and name.startswith("compositor") and re.search(tre, text)) or \
               (f not in lib and (re.search(rre, region) or re.search(tre, text))):
                fam = name
                break
        if f in lib and fam == "new, unclassified" and "rank_key" in "".join(texts[f][max(0, k - 6):k]):
            fam = FAMILY_ORDER[8]
        fam_ops[fam] += per[:, i]
        kind_ops[(fam, kind)] += per[:, i]
        lines_ops[(fam, f.name, k, text.strip()[:90])] += per[:, i]

    F = 100.0
    names = [r["name"] for r in game]
    p80name = names[int(np.argsort(tot_run, kind="stable")[min(len(game) - 1, math.ceil(0.8 * len(game)) - 1)])]
    print("")
    print("runs: %d; per-run ops/frame = (run - calibration) / %d; B0's p80 run (by total) = %s"
          % (len(game), F, p80name))
    print("conservation: the families + old code sum to each run's game ops: %s"
          % all(abs(sum(v[r] for v in fam_ops.values()) - tot_run[r]) < 0.5 for r in range(len(game))))

    def stat(v):
        v = v / F
        m, p = v.mean(), percentile_run(v.tolist())
        return (m + p) / 2, m, p, v[names.index(p80name)]
    hdr = "%-78s %11s %11s %11s %11s %10s %10s" % ("family", "(m+p80)/2", "mean", "p80", "@" + p80name[:10],
                                                  "inserted", "changed")
    print("")
    print(hdr)
    newtot = np.zeros(len(game))
    reqtot = np.zeros(len(game))
    for fam in FAMILY_ORDER:
        v = fam_ops.get(fam, np.zeros(len(game)))
        s = stat(v)
        ins = kind_ops.get((fam, "ins"), np.zeros(len(game))).mean() / F
        chg = kind_ops.get((fam, "chg"), np.zeros(len(game))).mean() / F
        print("%-78s %11s %11s %11s %11s %10s %10s" % (fam[:78], *(format(int(round(x)), ",") for x in s),
                                                       format(int(round(ins)), ","), format(int(round(chg)), ",")))
        newtot += v
        if fam in P8A_REQUESTED:
            reqtot += v
    for label, v in (("TOTAL, the requested P8a families (rows 1-9)", reqtot), ("TOTAL, every new/changed line", newtot)):
        s = stat(v)
        print("%-78s %11s %11s %11s %11s" % (label, *(format(int(round(x)), ",") for x in s)))
    old = fam_ops["(old code: unchanged lines, and non-doom code)"]
    s = stat(old)
    print("%-78s %11s %11s %11s %11s" % ("(old code: unchanged lines, and non-doom code)", *(format(int(round(x)), ",")
                                                                                         for x in s)))
    for label, v in (("  of which RELOCATED changed lines (numbers only) + changed library calls", reloc[0]),
                     ("  of which changed library-macro CALL lines (old body ops)", old_call[0])):
        s = stat(v)
        print("%-78s %11s %11s %11s %11s" % (label, *(format(int(round(x)), ",") for x in s)))
    s = stat(tot_run.astype(float))
    print("%-78s %11s %11s %11s %11s" % ("ALL (= B0)", *(format(int(round(x)), ",") for x in s)))
    print("")
    print("per run, ops/frame: the requested families' total / every new line / the run's total")
    for r, nm in enumerate(names):
        print("  %-20s %10s %10s %12s" % (nm, format(int(round(reqtot[r] / F)), ","), format(int(round(newtot[r] / F)), ","),
                                          format(int(round(tot_run[r] / F)), ",")))
    print("")
    print("the heaviest new lines per family (mean ops/frame over the runs; file:line, kind, text)")
    for fam in FAMILY_ORDER:
        rows = sorted(((v.mean() / F, key) for key, v in lines_ops.items() if key[0] == fam), reverse=True)
        if not rows:
            continue
        print("  %s" % fam)
        for val, (_f, fn, k, t) in rows[:a.top_unclassified if fam == "new, unclassified" else a.top]:
            kind = newl[[g for g in newl if g.name == fn][0]][k]
            print("    %10s  %s:%d %s  %s" % (format(int(round(val)), ","), fn, k, kind, t))


if __name__ == "__main__":
    main()
