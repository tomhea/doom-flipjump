"""CI sharding. `PYTEST_SHARD=i/n` keeps the test FILES at positions i, i + n, i + 2n, ... in collection order and
deselects the rest -- whole files, so a module's fixtures (an assembled fj image) build once, in one shard.

Why: GitHub's hosted runners stop a job at 6 h. The one-job suite outgrew it at M7 P8a (#124: both runs on 290cd9d
cancelled in `scripts/test.sh` at 6 h 00 m), so `.github/workflows/ci.yml` runs the suite as a matrix of shards.
Unset (every local run), nothing changes. tests/host/test_shards.py holds the partition: every collected test in
exactly one shard."""
import os


def shard_of(spec: str):
    """`i/n` -> (i, n), 0 <= i < n"""
    i, n = (int(x) for x in spec.split("/"))
    assert 0 <= i < n, spec
    return i, n


def pytest_collection_modifyitems(config, items):
    spec = os.environ.get("PYTEST_SHARD")
    if not spec:
        return
    i, n = shard_of(spec)
    files = list(dict.fromkeys(it.nodeid.split("::")[0] for it in items))
    keep = {f for k, f in enumerate(files) if k % n == i}
    selected = [it for it in items if it.nodeid.split("::")[0] in keep]
    deselected = [it for it in items if it.nodeid.split("::")[0] not in keep]
    if deselected:
        config.hook.pytest_deselected(items=deselected)
    items[:] = selected
