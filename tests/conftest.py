"""Duration-balanced, TOPIC-COHERENT sharding. `PYTEST_SHARD=i/n` keeps shard i of n and deselects the rest; unset (a
plain local run), nothing changes. CI runs the n shards as a matrix (.github/workflows/ci.yml); `scripts/test_parallel.py
--jobs K` runs them side by side on one machine.

THE SPLIT -- each shard is one connected piece of the suite, not a random mix:
1. the files are ordered by (directory, topic, name) -- the topic is the stem's first word without `test_` / `_fj`
   (monster_attack, monster_damage, ... sit together; tests/host and tests/fj never share a shard);
2. every test gets its estimated seconds from `tests/durations.json` (an exact per-test figure, else its file's per-test
   figure, else the default for tests/fj or tests/host);
3. the tests in that order are cut into n CONSECUTIVE runs with the smallest budget B that fits (binary search on B,
   greedy fill; a directory change always cuts). So a shard is one contiguous stretch of topic-ordered files: whole
   files, plus at most a part of a file at each edge, whose rest is the neighbouring shard. If fewer than n runs come
   out, the heaviest runs are halved (at a file boundary when one is near the middle) until there are n, so no shard
   is empty.
Every shard computes the same plan from the same collection. `pytest_report_header` prints the shard's file range.

Why: GitHub's hosted runners stop a job at 6 h, and the one-job suite outgrew it at M7 P8a (#124: both runs on 290cd9d
cancelled in `scripts/test.sh` at 6 h 00 m). tests/host/test_shards.py holds the partition, the coherence and the
balance."""
import json
import os
from pathlib import Path

DURATIONS = Path(__file__).resolve().parent / "durations.json"


def shard_of(spec: str):
    """`i/n` -> (i, n), 0 <= i < n"""
    i, n = (int(x) for x in spec.split("/"))
    assert 0 <= i < n, spec
    return i, n


def estimates(nodeids, table=None) -> list:
    """each node id's estimated seconds (tests/durations.json)"""
    t = table if table is not None else json.loads(DURATIONS.read_text(encoding="utf-8"))
    out = []
    for nid in nodeids:
        f = nid.split("::")[0]
        if nid in t["tests"]:
            out.append(float(t["tests"][nid]))
        elif f in t["files"]:
            out.append(float(t["files"][f]))
        else:
            out.append(float(t["default_fj"] if f.startswith("tests/fj/") else t["default_host"]))
    return out


def topic_key(path: str):
    """(directory, topic, name): the topic is the stem's first word, without `test_` and `_fj`"""
    d, _, name = path.rpartition("/")
    stem = name[:-3] if name.endswith(".py") else name
    stem = stem[5:] if stem.startswith("test_") else stem
    stem = stem[:-3] if stem.endswith("_fj") else stem
    return d, stem.split("_")[0], name


def _units(files, cost, idx):
    """the tests in shard order -- the files by topic_key, each file's tests in collection order -- as (dir, k, seconds)"""
    return [(topic_key(f)[0], k, cost[k]) for f in files for k in idx[f]]


def _fill(units, budget):
    """greedy consecutive runs of tests: close before a test that would overflow the budget, and at a directory change"""
    runs, cur, load, d0 = [], [], 0.0, None
    for d, k, c in units:
        if cur and (d != d0 or load + c > budget * (1 + 1e-9)):
            runs.append(cur)
            cur, load = [], 0.0
        cur.append(k)
        load += c
        d0 = d
    if cur:
        runs.append(cur)
    return runs


def plan(nodeids, n, table=None) -> list:
    """the shard of every node id (see the module docstring)"""
    cost = estimates(nodeids, table)
    idx = {}
    for k, nid in enumerate(nodeids):
        idx.setdefault(nid.split("::")[0], []).append(k)
    files = sorted(idx, key=topic_key)
    units = _units(files, cost, idx)
    lo, hi = max(cost) if cost else 0.0, sum(cost) or 1.0
    for _ in range(60):                                   # the smallest budget whose greedy fill needs <= n runs
        mid = (lo + hi) / 2
        if len(_fill(units, mid)) <= n:
            hi = mid
        else:
            lo = mid
    runs = _fill(units, hi)
    while len(runs) < n:                                  # halve the heaviest run until every shard has work
        j = max(range(len(runs)), key=lambda q: (sum(cost[t] for t in runs[q]), -q))
        r = runs[j]
        if len(r) < 2:
            break
        half, acc, cut = sum(cost[t] for t in r) / 2, 0.0, 1
        best = None
        for p in range(1, len(r)):                        # prefer a file boundary near the middle
            acc += cost[r[p - 1]]
            bound = nodeids[r[p - 1]].split("::")[0] != nodeids[r[p]].split("::")[0]
            score = abs(acc - half) * (1.0 if bound else 1.5)
            if best is None or score < best:
                best, cut = score, p
        runs[j:j + 1] = [r[:cut], r[cut:]]
    shard = [0] * len(nodeids)
    for s, r in enumerate(runs):
        for t in r:
            shard[t] = s
    return shard


def _shard_spec():
    spec = os.environ.get("PYTEST_SHARD")
    return shard_of(spec) if spec else None


def pytest_collection_modifyitems(config, items):
    spec = _shard_spec()
    if spec is None:
        return
    i, n = spec
    shard = plan([it.nodeid for it in items], n)
    selected = [it for it, s in zip(items, shard) if s == i]
    deselected = [it for it, s in zip(items, shard) if s != i]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
    files = list(dict.fromkeys(it.nodeid.split("::")[0] for it in selected))
    est = sum(estimates([it.nodeid for it in selected]))
    config._shard_summary = "shard %d/%d: %d tests in %d files, ~%.0f min estimated -- %s .. %s" % (
        i, n, len(selected), len(files), est / 60, files[0] if files else "-", files[-1] if files else "-")


def pytest_collection_finish(session):
    """the shard's range on the terminal, at every verbosity (`-q` hides pytest_report_collectionfinish's lines)"""
    summary = getattr(session.config, "_shard_summary", None)
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if summary and tr is not None:
        tr.write_line(summary)
