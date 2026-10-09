"""tests/conftest.py's topic-coherent, duration-balanced sharding (PYTEST_SHARD=i/n):
- PARTITION: over a real collection of tests/host, the n shards hold every collected test exactly once;
- COHERENCE: over the whole suite's node ids, every shard is one directory's CONTIGUOUS stretch of the topic-ordered
  tests (conftest.topic_key, then collection order) -- so a file is cut only at a shard's edge, and its parts are
  neighbouring shards;
- BALANCE: no shard's estimate exceeds its directory's mean share by more than the longest single test.

R9: dropping a shard leaves a hole the partition check sees; a longest-first (LPT) plan -- balanced, but a random mix
of files -- fails the coherence check."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import conftest as C  # noqa: E402

N = 3


def _collect(path="tests/host", shard=None) -> list:
    env = dict(os.environ)
    env.pop("PYTEST_SHARD", None)
    if shard is not None:
        env["PYTEST_SHARD"] = shard
    out = subprocess.run([sys.executable, "-m", "pytest", path, "--collect-only", "-q", "-p", "no:cacheprovider"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    return [ln.strip() for ln in out.stdout.splitlines() if "::" in ln]


def _holes(whole, shards):
    seen = [t for s in shards for t in s]
    return sorted(set(whole) - set(seen)), len(seen) - len(set(seen))


@pytest.fixture(scope="module")
def host_shards():
    return _collect(), [_collect(shard="%d/%d" % (i, N)) for i in range(N)]


@pytest.fixture(scope="module")
def suite():
    return _collect(path="tests")


def test_the_shards_partition_the_suite(host_shards):
    whole, shards = host_shards
    assert len(whole) > 100 and all(shards), [len(s) for s in shards]
    missing, dup = _holes(whole, shards)
    assert not missing and dup == 0 and sum(map(len, shards)) == len(whole), (missing[:5], dup)


def test_control_a_lost_shard_is_seen(host_shards):
    whole, shards = host_shards
    missing, _dup = _holes(whole, shards[1:])
    assert missing, "dropping a shard left no hole: the partition check is vacuous"


def _incoherent(ids, shard):
    """the shards that are NOT one directory's contiguous stretch of the topic-ordered tests"""
    pos = {}
    for k, nid in enumerate(ids):
        pos.setdefault(nid.split("::")[0], []).append(k)
    order = [k for f in sorted(pos, key=C.topic_key) for k in pos[f]]
    bad = set()
    for s in set(shard):
        where = [r for r, k in enumerate(order) if shard[k] == s]
        dirs = {C.topic_key(ids[order[r]].split("::")[0])[0] for r in where}
        if where[-1] - where[0] + 1 != len(where) or len(dirs) != 1:
            bad.add(s)
    return sorted(bad)


@pytest.mark.parametrize("n", [8, 20])
def test_every_shard_is_one_contiguous_topic_stretch(suite, n):
    shard = C.plan(suite, n)
    assert sorted(set(shard)) == list(range(n)), "an empty shard"
    assert not _incoherent(suite, shard)


@pytest.mark.parametrize("n", [8, 20])
def test_the_shards_balance_within_the_longest_test(suite, n):
    est = C.estimates(suite)
    shard = C.plan(suite, n)
    load, dirs = [0.0] * n, {}
    for nid, s, e in zip(suite, shard, est):
        load[s] += e
        dirs.setdefault(C.topic_key(nid.split("::")[0])[0], set()).add(s)
    for d, ss in dirs.items():
        total = sum(load[s] for s in ss)
        assert max(load[s] for s in ss) <= total / len(ss) + max(est) + 1e-6, (d, [load[s] for s in ss])


def test_control_a_longest_first_plan_is_incoherent(suite):
    """R9: LPT (each test, longest first, to the least-loaded shard) balances but mixes files -- the coherence check
    must see it"""
    est = C.estimates(suite)
    n, load, shard = 20, [0.0] * 20, [0] * len(suite)
    for k in sorted(range(len(suite)), key=lambda j: (-est[j], j)):
        s = min(range(n), key=lambda q: (load[q], q))
        shard[k], load[s] = s, load[s] + est[k]
    assert _incoherent(suite, shard)
