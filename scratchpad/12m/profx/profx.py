"""profx -- the ATTRIBUTING profiler for the game binary. Front door; see README.md.

    python profx.py engine                   build the instrumented engine into <WORK>/engX
    python profx.py maps                     derive the object map, label words and phase markers
    python profx.py --selftest [--lock PATH] the three checks below, on blocked27 (runs the binary:
                                             take the binary lock when other streams exist)

SELFTEST (R9). One idle run of the shipped binary -- menu + 3 game frames, 60M ops -- twice:
  (c) on the INSTALLED engine and on the profiler: the op totals and every frame's pixels must be
      identical, the histogram must sum to the op total, and the trace must be exactly the run's
      ops (its per-word counts equal the histogram's) -- the instrument changes nothing it measures;
  (a) the OWNER attribution against the op-by-op trace of that same run, per bind_things statement:
      within 5% on every statement >= 200 ops/call and 1% on the whole paired sequence, >= 5
      statements checked;
  (b) the NEGATIVE CONTROL: ADDRESS-ONLY attribution (every op charged to the word it runs at) put
      through the same check must FAIL -- it cannot see the chains and pool tables a statement
      causes elsewhere (hex.ptr_index: 171 vs 894 ops/call). If it passed, (a) would prove nothing.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import BinaryLock, engine_pyd, load_sparse, load_trace, work_dir  # noqa: E402


def _drive(args):
    cmd = [sys.executable, "-u", str(HERE / "drive.py")] + args
    print("  $ python drive.py %s" % " ".join(args), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    for line in r.stdout.splitlines():
        if line.startswith(("still", "prof_dump", "engine")):
            print("    " + line, flush=True)
    if r.returncode:
        print(r.stdout[-2000:])
        print(r.stderr[-2000:])
        raise SystemExit("drive.py failed")


def selftest(lock=None):
    import engine
    import maps
    import validate_trace as vt

    fails = []

    def check(name, cond, detail=""):
        print("  %-72s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""), flush=True)
        if not cond:
            fails.append(name)

    print("profx selftest -- (b) is the negative control; WORK = %s" % work_dir(), flush=True)
    if not engine_pyd().exists():
        engine.build()
    maps.build()
    wd = work_dir()
    with BinaryLock(lock, "S1/S8 measurement: profx --selftest"):
        _drive(["still", "3", "selftest_stock", "--stock"])
        stock = json.loads((wd / "selftest_stock.runs.json").read_text())["runs"][0]
        _drive(["still", "3", "selftest", "--trace", "0", str(stock["ops"])])
    instr = json.loads((wd / "selftest.runs.json").read_text())["runs"][0]
    prefix = str(wd / "selftest")

    print("(c) the instrument changes nothing it measures", flush=True)
    check("(c) op totals equal: stock %s vs profiler %s" % (format(stock["ops"], ","), format(instr["ops"], ",")),
          stock["ops"] == instr["ops"])
    check("(c) every presented frame's pixels equal (%d frames)" % len(stock["sha"]),
          stock["sha"] == instr["sha"] and len(stock["sha"]) == 5)
    ws, cs = load_sparse(prefix + ".self.bin")
    wi, ci = load_sparse(prefix + ".incl.bin")
    check("(c) the histograms conserve ops (self = owner-attributed = the op total)",
          int(cs.sum()) == int(ci.sum()) == instr["ops"], "%s / %s" % (format(int(cs.sum()), ","), format(int(ci.sum()), ",")))
    lo, tr = load_trace(prefix + ".trace.bin")
    tw, tc = np.unique(tr, return_counts=True)
    same = lo == 0 and len(tr) == instr["ops"] and np.array_equal(tw, ws) and np.array_equal(tc, cs)
    check("(c) the trace is exactly the run's ops (its per-word counts = the histogram)", same)

    print("(a) owner attribution vs the op trace", flush=True)
    ok_a, rows_a, _s = vt.check(prefix, "incl")
    check("(a) owner attribution PASSES (%.0f%%/statement, %.0f%% on the sequence, >= %d checked)"
          % (100 * vt.TOL, 100 * vt.SUM_TOL, vt.MIN_CHECKED), ok_a)
    print("(b) NEGATIVE CONTROL: address-only attribution through the same check", flush=True)
    ok_b, rows_b, _s = vt.check(prefix, "self")
    check("(b) address-only attribution FAILS the same check", not ok_b)
    ptr = [r for r in rows_b if "hex.ptr_index" in r[0] and r[5]]
    check("(b) ... and on hex.ptr_index it is far off (the chains it cannot see)",
          bool(ptr) and all(r[4] < -0.5 for r in ptr),
          ", ".join("%.0f vs %.0f" % (r[3], r[2]) for r in ptr))
    print("")
    print("SELFTEST %s" % ("PASS" if not fails else "FAIL: " + "; ".join(fails)), flush=True)
    return 1 if fails else 0


def main():
    args = sys.argv[1:]
    if "--selftest" in args:
        lock = args[args.index("--lock") + 1] if "--lock" in args else None
        return selftest(lock)
    if args[:1] == ["engine"]:
        import engine
        engine.build()
        return 0
    if args[:1] == ["maps"]:
        import maps
        maps.build()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
