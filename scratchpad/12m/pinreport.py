"""PIN REPORT: in a built binary, are the hottest shared words still PINNED?

WHY. flipjump's blocking pass (BlockPool, flipjump-151 flipjump/assembler/preprocessor.py) gives
every table dispatched through one word a block and PINS the word -- bakes the block base into it
-- so a dispatch flips a short index, not a whole address. Which words get a block is decided from
the whole program's table COUNTS, so a change anywhere can re-roll it: deleting bind_things once
cost ~6.8M ops/frame in lost pins on words the change never touched (handoff-throughput-plan 14.6-
14.8). The profiler names the words that matter (profx/hotwords.py -> hotwords_<build>.json); this
says, for any later build, whether each is still pinned, whether its tables are in its block, and
what the pool declined.

    python scratchpad/12m/pinreport.py --fjm build/<x>.fjm --labels scratchpad/12m/atlas/<x>.labels.tsv.gz
        [--hot scratchpad/12m/profx/hotwords_blocked27.json]
        [--counts-cache <that build's counts cache>] [--build-log <that build's log>]
        [--heat <the --pin-heat list it was built with>]
    python scratchpad/12m/pinreport.py --selftest

Per hot word: PINNED (base == reference) / PINNED, BASE MOVED / LOST (the word rests at no block
base: every dispatch through it pays the full table address) / UNRESOLVED (a label of its source
expression is missing from this build, and no single label of it has the same heat key).

A hot word is named as the PROFILED build named it -- a label with its call-site coordinates,
`f13:l2210:sim.thing_pass(3)---hp`. A later rung that moves lines renames it, while flipjump's pool
matches heat groups by `heat_key` (the path without its coordinates) and so still protects it. The
report does the same, and says so: a label this build lacks is replaced by the ONE label of this
build with the same heat key (row marked `*`); none, or two, and the word is UNRESOLVED. With the build's counts cache the report also checks the
base against the re-derived layout (MISMATCH = the cache does not describe this binary) and counts
the tables found in the block against the tables the counting pass saw. Exit status 1 if any hot
word is LOST or UNRESOLVED, so a build script can gate on it.

The cost line for a lost pin is an ESTIMATE, arithmetic from the mechanism (reference dispatches/frame
x 2 x popcount(reference base)); it is not a measurement of the new build.
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFX = Path(__file__).resolve().parent / "profx"
sys.path.insert(0, str(PROFX))
sys.path.insert(0, str(ROOT / "src"))
from common import W, label_dict  # noqa: E402
from fjmimage import FjmImage  # noqa: E402
from pool import KNOBS, _tokens, eval_key, load_heat, reconstruct  # noqa: E402

from flipjump.assembler.preprocessor import heat_key  # noqa: E402

DEFAULT_HOT = PROFX / "hotwords_blocked27.json"
LOG_RE = {
    "declines": re.compile(r"declines by reason: no-block ([\d,]+), too-wide ([\d,]+), overflow ([\d,]+)"),
    "broken": re.compile(r"broken groups: ([\d,]+) of ([\d,]+)"),
    "blocked": re.compile(r"blocked: ([\d,]+) tables in ([\d,]+) groups; declined ([\d,]+); ungrouped ([\d,]+)"),
    "conflicts": re.compile(r"pin conflicts \(aliased source-word expressions, un-pinned\): ([\d,]+)"),
    "preflight": re.compile(r"PREFLIGHT: demand ([\d,]+) words, capacity ([\d,]+) words \(([\d.]+)% used\); "
                            r"([\d,]+) of ([\d,]+) groups placed"),
}


def _n(s):
    return int(s.replace(",", ""))


def parse_log(text):
    """{field: numbers} from build_blocked.py's closing lines; {} when the log has none of them"""
    out = {}
    if text is None:
        return out
    for k, rx in LOG_RE.items():
        m = None
        for m in rx.finditer(text):
            pass                                    # the LAST occurrence: the final assembly's
        if m:
            out[k] = [float(g) if "." in g else _n(g) for g in m.groups()]
    return out


def rekey_by_heat(key, lab, by_heat):
    """`key` with every label this build lacks replaced by the ONE label of this build that has the
    same heat key -- the way flipjump's pool matched the group -- or None when a label has no such
    twin, or more than one"""
    out = key
    for t in sorted(set(_tokens(key))):
        if t in ("(", ")", "+", "?", ":") or re.fullmatch(r"-?\d+", t) or t in lab:
            continue
        twins = by_heat.get(heat_key(t), [])
        if len(twins) != 1:
            return None
        out = out.replace(t, twins[0])
    return out


def heat_renames(heat_path):
    """the `name:old:new` renames a heat list was re-keyed through (heat_rekey.py records them as
    `rekeyed.renames`), as (name, old, new) -- [] for a list never re-keyed, or no list"""
    if not heat_path:
        return []
    import gzip
    opener = gzip.open if str(heat_path).endswith(".gz") else open
    with opener(heat_path, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = []
    for r in (doc.get("rekeyed") or {}).get("renames", []):
        name, old, new = r.rsplit(":", 2)
        out.append((name, int(old), int(new)))
    return out


def rename_hot(hot, renames):
    """the hot list with every word's key carried through `renames` -- the SAME whole-name rewrite
    heat_rekey.py applied to the build's heat list. A rung that changes a macro's PARAMETER COUNT
    renames every path through it: the pool matched the re-keyed list, so the report must look the
    words up under the names the build has (M7 P1.4: emit_col_lines 45 -> 38 left rank 14
    UNRESOLVED while the build had pinned it)."""
    from heat_rekey import pattern
    words = []
    for h in hot["words"]:
        key = h["key"]
        for name, old, new in renames:
            key = pattern(name, old).sub("%s(%d)" % (name, new), key)
        words.append(dict(h, key=key))
    return dict(hot, words=words)


def heat_index(lab):
    by = {}
    for name in lab:
        by.setdefault(heat_key(name), []).append(name)
    return by


def report(image, lab, hot, recon=None):
    """-> list of row dicts, one per hot word"""
    pool = fr = None
    if recon is not None:
        pool, fr = recon
    rows = []
    by_heat = None
    for h in hot["words"]:
        key = h["key"]
        row = {"rank": h["rank"], "key": key, "ref_base": h["base_bits"], "ref_tables": h["tables"],
               "dispatches": h["dispatches_per_frame"], "ref_pc": h["base_popcount"], "rekeyed": False}
        addr = eval_key(key, lab)
        if addr is None:
            by_heat = heat_index(lab) if by_heat is None else by_heat
            key2 = rekey_by_heat(key, lab, by_heat)
            addr = eval_key(key2, lab) if key2 is not None else None
            if addr is not None:
                key = key2
                row.update(rekeyed=True, key=key2)
        if addr is None:
            row.update(status="UNRESOLVED", base=None)
            rows.append(row)
            continue
        v = image.word(addr // W)
        exp_base = exp_bits = None
        if pool is not None and key in pool.groups:
            exp_base, exp_bits = pool.groups[key][0], pool._block_bits(key)
        bits = exp_bits or h["block_bits"]
        base = (v & ~(bits - 1)) if v is not None else 0
        if base < KNOBS["pool_base"]:
            base = 0
        row["base"] = base
        row["pc"] = bin(base).count("1")
        if base == 0:
            row["status"] = "LOST"
        elif exp_base is not None and base != exp_base:
            row["status"] = "MISMATCH"
        elif base != h["base_bits"]:
            row["status"] = "PINNED, BASE MOVED"
        else:
            row["status"] = "PINNED"
        if base:
            row["tables_found"] = image.segment_starts(base // W, (base + bits) // W)
        row["tables_expected"] = fr["counts"].get(key) if fr is not None else h["tables"]
        rows.append(row)
    return rows


def print_report(rows, log, exact_tables=True):
    print("%4s %-19s %6s %8s %13s %11s  %s" % ("rank", "status", "pc(b)", "ref pc", "tables", "dispatch/fr",
                                               "source word"))
    lost_cost = 0.0
    for r in rows:
        tables = ("%s%s/%s" % ("" if exact_tables else "~", format(r.get("tables_found", 0), ","),
                               format(r.get("tables_expected") or 0, ","))
                  if r["status"] != "UNRESOLVED" else "-")
        print("%4d %-19s %6s %8d %13s %11s %s%s" % (r["rank"], r["status"], r.get("pc", "-"), r["ref_pc"], tables,
                                                     format(int(r["dispatches"]), ","),
                                                     "*" if r.get("rekeyed") else " ", r["key"][:64]))
        if r["status"] in ("LOST", "UNRESOLVED"):
            lost_cost += r["dispatches"] * 2 * r["ref_pc"]
    bad = [r for r in rows if r["status"] in ("LOST", "UNRESOLVED")]
    moved = [r for r in rows if r["status"] == "PINNED, BASE MOVED"]
    mism = [r for r in rows if r["status"] == "MISMATCH"]
    print("")
    print("hot words pinned: %d of %d; lost %d; unresolved %d; base moved %d; mismatch vs the counts cache %d"
          % (len(rows) - len(bad) - len(mism), len(rows), sum(r["status"] == "LOST" for r in rows),
             sum(r["status"] == "UNRESOLVED" for r in rows), len(moved), len(mism)))
    nre = sum(1 for r in rows if r.get("rekeyed"))
    if nre:
        print("(* %d hot word(s) re-keyed: their label moved, and this build has exactly one label with the "
              "same heat key -- the name flipjump's pool matched them by)" % nre)
    if not exact_tables:
        print("(~ tables: no counts cache for this build, so the block is taken at the REFERENCE size and the "
              "count is approximate; the reference count is the counted tables of the profiled build)")
    if bad:
        print("ESTIMATE (not measured): the lost pins cost ~%s ops/frame at the reference dispatch rates"
              % format(int(lost_cost), ","))
    if log:
        d, b, bl, pf = log.get("declines"), log.get("broken"), log.get("blocked"), log.get("preflight")
        if d:
            print("pool (build log): declines no-block %s, too-wide %s, overflow %s"
                  % tuple(format(x, ",") for x in d))
        if b:
            print("pool (build log): broken groups %s of %s (a broken group un-pins every table in it "
                  "unless --pin-broken)" % (format(b[0], ","), format(b[1], ",")))
        if bl:
            print("pool (build log): blocked %s tables in %s groups; declined %s; ungrouped %s"
                  % tuple(format(x, ",") for x in bl))
        if pf:
            print("pool (build log): preflight demand %s of %s words (%.1f%% used); %s of %s groups placed"
                  % (format(pf[0], ","), format(pf[1], ","), pf[2], format(pf[3], ","), format(pf[4], ",")))
        if not (d or b or bl or pf):
            print("pool (build log): the log has no pool lines")
    else:
        print("pool declines: n/a (no build log given)")
    return exit_code(rows)


def exit_code(rows):
    return 1 if any(r["status"] in ("LOST", "UNRESOLVED") for r in rows) else 0


def run(a):
    hot = json.loads(Path(a.hot).read_text())
    renames = heat_renames(a.heat)
    if renames:
        hot = rename_hot(hot, renames)
        print("hot words carried through the heat list's %d rename(s): %s"
              % (len(renames), ", ".join("%s %d->%d" % r for r in renames)))
    image = FjmImage(a.fjm)
    lab = label_dict(a.labels)
    recon = reconstruct(a.counts_cache, heat=load_heat(a.heat)) if a.counts_cache else None
    log = parse_log(Path(a.build_log).read_text(errors="replace")) if a.build_log else None
    print("pin report: %s against the hot list of %s (%d words, profiled on %s)"
          % (Path(a.fjm).name, hot["fjm"], len(hot["words"]), hot["run"]))
    rows = report(image, lab, hot, recon)
    return print_report(rows, log, exact_tables=recon is not None)


def _cache_is_blocked27(cache):
    """does the counts cache describe blocked27's program? (blocked27's counting pass saw 27,030 groups)"""
    import gzip
    try:
        with gzip.open(cache, "rt", encoding="utf-8") as fh:
            return len(json.load(fh)["counts"]) == 27030
    except (OSError, ValueError, KeyError):
        return False


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-66s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""), flush=True)
        if not cond:
            fails.append(name)

    fjm = ROOT / "build" / "doom_e1m1_blocked27.fjm"
    labp = ROOT / "scratchpad" / "12m" / "atlas" / "blocked27.labels.tsv.gz"
    cache = ROOT / "scratchpad" / "12m" / "_counts_game.json.gz"
    logp = ROOT / "docs" / "ship-evidence" / "blocked27_rebuild.log"
    print("pinreport selftest -- C2, C3, C6's second half and C7's first are the negative controls")
    hot = json.loads(DEFAULT_HOT.read_text())
    image = FjmImage(fjm)
    lab = label_dict(labp)
    # the layout is re-derived from blocked27's OWN counts only while the tracked cache is blocked27's
    # program; once a rung changes the program (M7 P1.2 on) the tracked cache describes that program,
    # so the checks take the hot list's reference counts -- which ARE blocked27's -- instead
    recon = reconstruct(cache) if _cache_is_blocked27(cache) else None
    if recon is None:
        print("  (the tracked counts cache describes a later program: tables checked against the hot "
              "list's reference counts)")

    # C1 the shipped binary against its own hot list: every word pinned where the profiler saw it
    rows = report(image, lab, hot, recon)
    check("C1 the hot list is not vacuous (>= 10 words)", len(rows) >= 10, "%d words" % len(rows))
    check("C1 every hot word of the shipped binary is PINNED at its reference base",
          all(r["status"] == "PINNED" for r in rows), ", ".join(sorted({r["status"] for r in rows})))
    check("C1 every block holds the tables the counting pass saw",
          all(r.get("tables_found") == r.get("tables_expected") for r in rows),
          "%d/%d" % (sum(r.get("tables_found", 0) for r in rows), sum(r.get("tables_expected") or 0 for r in rows)))

    # C2 NEGATIVE CONTROL: the hottest word rests at its UNPINNED value -> must be reported LOST
    top = min(hot["words"], key=lambda h: h["rank"])
    addr = eval_key(top["key"], lab)
    pinned_value = image.word(addr // W)
    stripped = image.with_word(addr // W, pinned_value & 1023)
    rows2 = report(stripped, lab, hot, recon)
    st = {r["key"]: r["status"] for r in rows2}
    check("C2 the stripped hottest word is reported LOST", st[top["key"]] == "LOST", st[top["key"]])
    check("C2 ... and only that one (the others stay PINNED)",
          sum(s == "PINNED" for s in st.values()) == len(rows2) - 1)
    check("C2 a lost pin makes the report's exit status nonzero", exit_code(rows2) == 1)
    check("C2 ... while the intact binary's is zero (the status separates)", exit_code(rows) == 0)

    # C3 a build without the hottest word's label: UNRESOLVED, never silently PINNED
    head = top["key"]
    lab3 = {k: v for k, v in lab.items() if k not in head}
    rows3 = report(image, lab3, hot, recon)
    st3 = {r["key"]: r["status"] for r in rows3}
    check("C3 a hot word whose label is gone is UNRESOLVED", st3[top["key"]] == "UNRESOLVED", st3[top["key"]])

    # C6 A MOVED LINE: the hottest word's label renamed to another line -> re-keyed and PINNED, not
    #    UNRESOLVED; and when TWO labels share that heat key the report must refuse to pick one
    mid = next(h for h in sorted(hot["words"], key=lambda h: h["rank"]) if re.search(r"\bf\d+:l\d+:", h["key"]))
    old = next(t for t in _tokens(mid["key"]) if re.match(r"f\d+:l\d+:", t))   # the label, whole
    moved = re.sub(r"^(f\d+:l)(\d+)", lambda m: m.group(1) + str(int(m.group(2)) + 7), old)
    lab6 = {(moved if k == old else k): v for k, v in lab.items()}
    st6 = {r["key"] if not r.get("rekeyed") else mid["key"]: (r["status"], r.get("rekeyed"))
           for r in report(image, lab6, hot, None)}
    check("C6 a hot word whose line moved is re-keyed by heat key and PINNED",
          st6[mid["key"]][1] is True and st6[mid["key"]][0].startswith("PINNED"), str(st6[mid["key"]]))
    lab7 = dict(lab6)
    lab7[re.sub(r"^(f\d+:l)(\d+)", lambda m: m.group(1) + str(int(m.group(2)) + 9), old)] = lab6[moved] + 64
    st7 = {r["key"]: r["status"] for r in report(image, lab7, hot, None)}
    check("C6 ... and with two labels of that heat key it is UNRESOLVED (no guessing)",
          st7[mid["key"]] == "UNRESOLVED", st7[mid["key"]])

    # C7 A CHANGED PARAMETER COUNT (M7 P1.4): every label on the mid word's path that carries a macro
    #    whose count a rung changed is renamed in the table; the report must fail to resolve the word
    #    WITHOUT the heat list's renames (the negative control) and pin it WITH them
    mid7 = next(h for h in sorted(hot["words"], key=lambda h: h["rank"])
                if re.search(r"\w\((\d+)\)---", h["key"]))
    mname, mcount = re.search(r"([\w.]+)\((\d+)\)---", mid7["key"]).groups()
    ren = [(mname, int(mcount), int(mcount) + 3)]
    from heat_rekey import pattern
    lab8 = {pattern(mname, int(mcount)).sub("%s(%d)" % (mname, int(mcount) + 3), k): v
            for k, v in lab.items()}
    st8 = {r["key"]: r["status"] for r in report(image, lab8, hot, None)}
    check("C7 a word whose macro changed its parameter count is UNRESOLVED without the renames",
          st8[mid7["key"]] == "UNRESOLVED", "%s: %s" % (mname, st8[mid7["key"]]))
    hot9 = rename_hot(hot, ren)
    k9 = next(h["key"] for h in hot9["words"] if h["rank"] == mid7["rank"])
    st9 = {r["key"]: r["status"] for r in report(image, lab8, hot9, None)}
    check("C7 ... and PINNED through the heat list's renames", st9[k9].startswith("PINNED"), st9[k9])

    # C5 a REAL build that lost pins: b26 (built without --pin-broken/--width-buckets: 10,052 too-wide
    #    declines broke 1,333 groups). Skipped, loudly, if that experiment binary is gone.
    b26, b26l = ROOT / "build" / "doom_e1m1_b26.fjm", ROOT / "scratchpad" / "12m" / "atlas" / "b26.labels.tsv.gz"
    if b26.exists() and b26l.exists():
        rows5 = report(FjmImage(b26), label_dict(b26l), hot, None)
        nlost = sum(r["status"] == "LOST" for r in rows5)
        check("C5 the real b26 build (1,333 broken groups) shows LOST hot words", nlost >= 1,
              "%d of %d lost" % (nlost, len(rows5)))
    else:
        print("  C5 SKIPPED: build/doom_e1m1_b26.fjm or its label table is gone")

    # C4 the pool's decline counts come from the build log's own lines, and only from them
    log = parse_log(logp.read_text(errors="replace"))
    check("C4 the shipped build log's declines parse", log.get("declines") == [5103, 0, 4008], str(log.get("declines")))
    check("C4 ... and its broken-group line", log.get("broken") == [2, 27030], str(log.get("broken")))
    syn = parse_log("declines by reason: no-block 1,234, too-wide 5, overflow 6\nbroken groups: 7 of 89 (x)\n")
    check("C4 a synthetic log parses to ITS numbers", syn.get("declines") == [1234, 5, 6] and syn.get("broken") == [7, 89])
    check("C4 a log without the lines yields nothing (not zeros)", parse_log("nothing here") == {})
    print("")
    print("SELFTEST %s" % ("PASS" if not fails else "FAIL: " + "; ".join(fails)))
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--hot", default=str(DEFAULT_HOT))
    ap.add_argument("--counts-cache", default=None)
    ap.add_argument("--build-log", default=None)
    ap.add_argument("--heat", default=None,
                    help="the --pin-heat list the build was placed with (so its layout re-derives)")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.fjm or not a.labels:
        ap.error("--fjm and --labels are required (or --selftest)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
