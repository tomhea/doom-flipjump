"""tests/conftest.py's CI sharding (PYTEST_SHARD=i/n): over a real collection, the n shards PARTITION the suite --
every collected test in exactly one shard, every file whole in one shard -- so a CI matrix of shards runs all of it,
once. Collect-only runs of tests/host (seconds each).

R9: the control drops one shard's files and requires the union check to see the hole."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
N = 3


def _collect(shard=None) -> list:
    env = dict(os.environ)
    env.pop("PYTEST_SHARD", None)
    if shard is not None:
        env["PYTEST_SHARD"] = shard
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/host", "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    return [ln.strip() for ln in out.stdout.splitlines() if "::" in ln]


def _partition_holes(whole, shards):
    seen = [t for s in shards for t in s]
    return sorted(set(whole) - set(seen)), len(seen) - len(set(seen))


def test_the_shards_partition_the_suite():
    whole = _collect()
    shards = [_collect("%d/%d" % (i, N)) for i in range(N)]
    assert len(whole) > 100 and all(shards), [len(s) for s in shards]
    missing, dup = _partition_holes(whole, shards)
    assert not missing and dup == 0 and sum(map(len, shards)) == len(whole), (missing[:5], dup)
    files = [{t.split("::")[0] for t in s} for s in shards]
    assert all(not (files[a] & files[b]) for a in range(N) for b in range(a + 1, N)), "a file split across shards"


def test_control_a_lost_shard_is_seen():
    whole = _collect()
    shards = [_collect("%d/%d" % (i, N)) for i in range(N)]
    missing, _dup = _partition_holes(whole, shards[1:])
    assert missing, "dropping a shard left no hole: the partition check is vacuous"
