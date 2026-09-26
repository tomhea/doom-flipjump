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
    python scratchpad/12m/pinreport.py --selftest

Per hot word: PINNED (base == reference) / PINNED, BASE MOVED / LOST (the word rests at no block
base: every dispatch through it pays the full table address) / UNRESOLVED (a label of its source
expression is missing from this build). With the build's counts cache the report also checks the
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
from pool import KNOBS, eval_key, reconstruct  # noqa: E402

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


def report(image, lab, hot, recon=None):
    """-> list of row dicts, one per hot word"""
    pool = fr = None
    if recon is not None:
        pool, fr = recon
    rows = []
    for h in hot["words"]:
        key = h["key"]
        row = {"rank": h["rank"], "key": key, "ref_base": h["base_bits"], "ref_tables": h["tables"],
               "dispatches": h["dispatches_per_frame"], "ref_pc": h["base_popcount"]}
        addr = eval_key(key, lab)
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
        print("%4d %-19s %6s %8d %13s %11s  %s" % (r["rank"], r["status"], r.get("pc", "-"), r["ref_pc"], tables,
                                                    format(int(r["dispatches"]), ","), r["key"][:64]))
        if r["status"] in ("LOST", "UNRESOLVED"):
            lost_cost += r["dispatches"] * 2 * r["ref_pc"]
    bad = [r for r in rows if r["status"] in ("LOST", "UNRESOLVED")]
    moved = [r for r in rows if r["status"] == "PINNED, BASE MOVED"]
    mism = [r for r in rows if r["status"] == "MISMATCH"]
    print("")
    print("hot words pinned: %d of %d; lost %d; unresolved %d; base moved %d; mismatch vs the counts cache %d"
          % (len(rows) - len(bad) - len(mism), len(rows), sum(r["status"] == "LOST" for r in rows),
             sum(r["status"] == "UNRESOLVED" for r in rows), len(moved), len(mism)))
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
    image = FjmImage(a.fjm)
    lab = label_dict(a.labels)
    recon = reconstruct(a.counts_cache) if a.counts_cache else None
    log = parse_log(Path(a.build_log).read_text(errors="replace")) if a.build_log else None
    print("pin report: %s against the hot list of %s (%d words, profiled on %s)"
          % (Path(a.fjm).name, hot["fjm"], len(hot["words"]), hot["run"]))
    rows = report(image, lab, hot, recon)
    return print_report(rows, log, exact_tables=recon is not None)


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
    print("pinreport selftest -- C2 and C3 are the negative controls")
    hot = json.loads(DEFAULT_HOT.read_text())
    image = FjmImage(fjm)
    lab = label_dict(labp)
    recon = reconstruct(cache)

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
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.fjm or not a.labels:
        ap.error("--fjm and --labels are required (or --selftest)")
    return run(a)


if __name__ == "__main__":
    sys.exit(main())
