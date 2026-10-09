"""Run the suite as K topic-coherent, duration-balanced shards side by side on this machine (tests/conftest.py's
PYTEST_SHARD plan, the same one CI's matrix uses), and report every shard's summary.

    python scripts/test_parallel.py --jobs 3                  # the whole suite in 3 processes
    python scripts/test_parallel.py --jobs 2 -- tests/fj -x   # extra pytest arguments after --

Each shard's output goes to <logdir>/shard_<i>_of_<K>.log; the exit code is 0 only when every shard passed.
⚠ MEMORY: one fj harness can hold ~3 GB, so K x 3 GB must fit (CLAUDE.md rule 1 -- no build beside it); K = 2 or 3
on a 16 GB box."""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--logdir", default=None)
    ap.add_argument("pytest_args", nargs="*")
    a = ap.parse_args(argv)
    k = a.jobs
    assert k >= 1
    logdir = Path(a.logdir or tempfile.mkdtemp(prefix="doom_shards_"))
    logdir.mkdir(parents=True, exist_ok=True)
    env0 = dict(os.environ, PYTHONIOENCODING="utf-8")
    env0.setdefault("PYTHONPATH", os.pathsep.join(["src", "."]))
    procs = []
    t0 = time.time()
    for i in range(k):
        log = logdir / ("shard_%d_of_%d.log" % (i, k))
        fh = open(log, "w", encoding="utf-8")
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *a.pytest_args]
        procs.append((i, log, fh, subprocess.Popen(cmd, cwd=ROOT, env=dict(env0, PYTEST_SHARD="%d/%d" % (i, k)),
                                                   stdout=fh, stderr=subprocess.STDOUT)))
    print("%d shards running; logs in %s" % (k, logdir), flush=True)
    worst = 0
    for i, log, fh, p in procs:
        rc = p.wait()
        fh.close()
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
        head = next((ln for ln in lines if ln.startswith("shard ")), "shard %d/%d" % (i, k))
        tail = next((ln for ln in reversed(lines) if ln.strip()), "")
        print("[%s] rc=%d -- %s" % (head, rc, tail), flush=True)
        worst = worst or rc
    print("all %d shards done in %.0f s: %s" % (k, time.time() - t0, "PASS" if worst == 0 else "FAIL"))
    return worst


if __name__ == "__main__":
    sys.exit(main())
