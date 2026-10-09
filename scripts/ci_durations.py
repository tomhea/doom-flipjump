"""Refresh tests/durations.json -- the per-test estimates tests/conftest.py's shard plan balances on -- from CI runs.

    python scripts/ci_durations.py <run id> [<run id> ...]

CI runs `scripts/test.sh --durations=0 --durations-min=0.5`, so every job's log ends with pytest's "slowest durations"
report (`12.34s call     tests/fj/x.py::test_y`, and the setup / teardown lines). This sums setup + call + teardown
per test (the mean when several runs report it) and REPLACES "tests" with them (an exact figure wins over the file's),
and sets "files" -- the seconds of a test the report did NOT list -- to 0.05 for every collected file: with the
0.5 s report floor, an unlisted test of a full run took under 0.5 s. Pass the run ids of a FULL CI run of this
collection (a test the runs never ran would get 0.05 too).

The first estimates (2026-10-09) came from the timestamped `pytest -q` progress lines of 16 one-job runs, solved per
file by NNLS (scripts/ci_durations_nnls.py)."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tests" / "durations.json"
# the node id runs to the end of the line: a parametrized id may hold spaces (`test_x[the case]`) -- `\S+` cut it there
# and merged different tests into one key
LINE = re.compile(r"(\d+(?:\.\d+)?)s (setup|call|teardown)\s+(tests/.+?::.+?)\s*$")
REPO = "tomhea/doom-flipjump"
BELOW_FLOOR = 0.05                      # measured: run 37900825561's host shard (453.85 s) less its reported
                                        # tests (366 s), over its 1,759 unreported tests -- 0.050 s each


def collected_files() -> list:
    """the files `pytest --collect-only` finds now -- the runs passed must be of this collection (a full CI run)"""
    out = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    return sorted({ln.split("::")[0] for ln in out.splitlines() if "::" in ln})


def run_durations(run_id: str) -> dict:
    log = subprocess.run(["gh", "run", "view", run_id, "--repo", REPO, "--log"], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", check=True).stdout
    out = {}
    for ln in log.splitlines():
        m = LINE.search(ln)
        if m:
            out[m.group(3)] = out.get(m.group(3), 0.0) + float(m.group(1))
    return out


def main(argv) -> int:
    if not argv:
        print(__doc__)
        return 2
    seen = {}
    for rid in argv:
        d = run_durations(rid)
        print("run %s: %d tests reported" % (rid, len(d)))
        for k, v in d.items():
            seen.setdefault(k, []).append(v)
    if not seen:
        print("no durations found -- did the runs use --durations?")
        return 1
    table = json.loads(TABLE.read_text(encoding="utf-8"))
    table["tests"] = {k: round(sum(vs) / len(vs), 2) for k, vs in sorted(seen.items())}   # REPLACED: a full run's report
    # a test the runs did not report ran under the report's floor (--durations-min=0.5): every collected file the
    # runs covered gets BELOW_FLOOR for those tests -- not its reported tests' mean, which only the slow ones make
    for f in collected_files():
        table["files"][f] = BELOW_FLOOR
    TABLE.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("tests/durations.json: %d exact tests, %d files" % (len(table["tests"]), len(table["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
