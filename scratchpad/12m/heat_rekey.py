"""heat_rekey.py -- carry a heat list across a change to the PARAMETER COUNT of a macro on its paths.

A heat list (heatsites.py; `build_blocked.py --pin-heat`) names its groups and sites by
macro-expansion paths with the call-site coordinates stripped (flipjump's `heat_key`) -- but every
macro on a path keeps its PARAMETER COUNT: `stream.emit_col_lines(45)`. A rung that changes a macro's
parameter list therefore renames every path through it, the pool matches none of those sites, and
they lose their heat-ordered indices; a group whose KEY carries the name goes missing outright.

This renames `name(old)` to `name(new)` in every group key and every site path, and says how many of
each it touched. It is a RE-KEY, not a re-profile -- the ranks stay the profiled binary's measurement.
What it cannot carry, and does not pretend to: sites in code the rung deleted (their paths name
macros that no longer exist, so the pool leaves those indices unused), and occurrence numbers that
moved because the rung put a same-key site ahead of a listed one. The build's heat report (no hot
group missing or ambiguous) and `pinreport.py` on the binary are the checks that it held; msframe
is the verdict on whether it was enough.

    python scratchpad/12m/heat_rekey.py --in scratchpad/12m/heat_blocked27.json.gz \\
        --out scratchpad/12m/heat_blocked27_p14.json.gz --rename stream.emit_col_lines:45:38 ...
    python scratchpad/12m/heat_rekey.py --selftest

CONTROL (R9, --selftest): a name must be matched WHOLE -- renaming `walk(7)` must leave
`w1rpat.walk(7)` alone, and renaming `emit_col_lines(45)` must leave `emit_col_lines(4)` and
`emit_col_lines(451)` alone; a rename that would merge two group keys, or that matches nothing, is
refused.
"""
import argparse
import gzip
import hashlib
import json
import re
import sys


def pattern(name, old):
    # a macro on a path is preceded by the start, `---`, or a `repN:` prefix -- never by a name char
    return re.compile(r"(?<![\w.])" + re.escape(name) + r"\(" + str(old) + r"\)")


def rekey(doc, renames):
    """(new doc, {rename: (group keys touched, site paths touched)}); refuses a merge or a no-op"""
    groups = doc["groups"]
    stats = {}
    for name, old, new in renames:
        pat, rep = pattern(name, old), "%s(%d)" % (name, new)
        nk = sum(1 for g in groups if pat.search(g))
        ns = sum(1 for sites in groups.values() for s in sites if pat.search(s[0]))
        if nk + ns == 0:
            raise SystemExit("rename %s(%d) -> (%d) matches nothing in the list" % (name, old, new))
        out = {}
        for g, sites in groups.items():
            g2 = pat.sub(rep, g)
            if g2 in out:
                raise SystemExit("rename %s(%d) -> (%d) merges two group keys: %r" % (name, old, new, g2))
            out[g2] = [[pat.sub(rep, s[0])] + list(s[1:]) for s in sites]
        groups = out
        stats["%s(%d)->(%d)" % (name, old, new)] = (nk, ns)
    new_doc = dict(doc, groups=groups)
    new_doc["rekeyed"] = {"from_sites_sha256": doc.get("sites_sha256"),
                          "renames": ["%s:%d:%d" % r for r in renames]}
    new_doc["sites_sha256"] = hashlib.sha256(json.dumps(groups, sort_keys=True).encode()).hexdigest()
    return new_doc, stats


def parse_rename(text):
    name, old, new = text.rsplit(":", 2)
    return name, int(old), int(new)


def selftest():
    doc = {"groups": {"((a---stream.emit_col_lines(45)---rep0:w1rpat.walk(7)---ycur + 0) + 32)":
                      [["a---stream.emit_col_lines(45)---walk(7)---x", 0, 16],
                       ["a---stream.emit_col_lines(4)---y", 0, 16],
                       ["a---stream.emit_col_lines(451)---z", 1, 16]],
                      "(hex.tables.res + 32)": [["b---walk(7)---t", 0, 16]]}}
    fails = []
    new, stats = rekey(doc, [("stream.emit_col_lines", 45, 38), ("walk", 7, 6)])
    keys = list(new["groups"])
    if "((a---stream.emit_col_lines(38)---rep0:w1rpat.walk(7)---ycur + 0) + 32)" not in keys:
        fails.append("the group key was not renamed, or `w1rpat.walk` was taken for `walk`")
    sites = [s[0] for v in new["groups"].values() for s in v]
    for want in ("a---stream.emit_col_lines(38)---walk(6)---x", "a---stream.emit_col_lines(4)---y",
                 "a---stream.emit_col_lines(451)---z", "b---walk(6)---t"):
        if want not in sites:
            fails.append("site path %r missing after the rename: %s" % (want, sites))
    if stats != {"stream.emit_col_lines(45)->(38)": (1, 1), "walk(7)->(6)": (0, 2)}:
        fails.append("the counts are wrong: %s" % stats)
    try:
        rekey(doc, [("stream.emit_col_lines", 99, 1)])
        fails.append("a rename that matches nothing was accepted")
    except SystemExit:
        pass
    merge = {"groups": {"k(1)": [["p", 0, 16]], "k(2)": [["q", 0, 16]]}}
    try:
        rekey(merge, [("k", 1, 2)])
        fails.append("a rename that merges two group keys was accepted")
    except SystemExit:
        pass
    for f in fails:
        print("SELFTEST FAIL: " + f)
    print("SELFTEST %s" % ("PASS" if not fails else "FAIL"))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="src")
    ap.add_argument("--out")
    ap.add_argument("--rename", action="append", default=[], type=parse_rename,
                    help="name:old_param_count:new_param_count (repeatable)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not (a.src and a.out and a.rename):
        ap.error("--in, --out and at least one --rename are required")
    opener = gzip.open if a.src.endswith(".gz") else open
    with opener(a.src, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    new, stats = rekey(doc, a.rename)
    for r, (nk, ns) in stats.items():
        print("  %-48s %d group key(s), %s site path(s)" % (r, nk, format(ns, ",")))
    raw = json.dumps(new).encode("utf-8")
    with gzip.open(a.out, "wb") as fh:
        fh.write(raw)
    print("%s: %d groups, %s sites; decompressed sha256 %s" % (
        a.out, len(new["groups"]), format(sum(len(v) for v in new["groups"].values()), ","),
        hashlib.sha256(raw).hexdigest()[:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
