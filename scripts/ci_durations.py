"""Refresh tests/durations.json -- the per-test estimates tests/conftest.py's shard plan balances on -- from CI runs.

    python scripts/ci_durations.py <run id> [<run id> ...]

CI runs `scripts/test.sh --durations=0 --durations-min=0.5`, so every job's log ends with pytest's "slowest durations"
report (`12.34s call     tests/fj/x.py::test_y`, and the setup / teardown lines). This sums setup + call + teardown
per test (the mean when several runs report it), writes them into "tests" (an exact figure wins over the file's),
and re-derives "files" -- one test's mean seconds in that file -- for the files measured, so a NEW test in a measured
file starts from its neighbours. Tests under the 0.5 s report floor keep their file's figure.

The first estimates (2026-10-09) came from the timestamped `pytest -q` progress lines of 16 one-job runs, solved per
file by NNLS (scripts/ci_durations_nnls.py)."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLE = ROOT / "tests" / "durations.json"
LINE = re.compile(r"(\d+(?:\.\d+)?)s (setup|call|teardown)\s+(tests/\S+::\S+)")
REPO = "tomhea/doom-flipjump"


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
    for k, vs in seen.items():
        table["tests"][k] = round(sum(vs) / len(vs), 2)
    per_file = {}
    for k, v in table["tests"].items():
        per_file.setdefault(k.split("::")[0], []).append(v)
    for f, vs in per_file.items():
        table["files"][f] = round(sum(vs) / len(vs), 1)
    TABLE.write_text(json.dumps(table, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("tests/durations.json: %d exact tests, %d files" % (len(table["tests"]), len(table["files"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
