"""The test tree itself: no two test modules may share a basename.

`tests/` has no `__init__.py` anywhere, so pytest's default `prepend` import mode puts each test
file's directory on `sys.path` and imports the file under its BASENAME. Two files called
`test_dispatch_tables.py` -- one in `tests/host`, one in `tests/fj` -- therefore cannot both be
collected in ONE run: whichever comes second is refused with "import file mismatch" and the whole
session stops at collection.

Nobody runs both directories in one command locally, because `tests/fj` is about 37 minutes on its
own. CI does -- `scripts/test.sh` is `pytest` over the whole tree -- so the collision was invisible
everywhere except CI, which died on it at collection from 2026-08-23 (19dd5b0 added the host twin
of a name `tests/fj` had used since June) until this file's commit.

This lives on the host tier, the one everybody does run, so the next collision fails here and not
three weeks later in a CI log nobody is reading.
"""
from collections import defaultdict
from pathlib import Path

TESTS = Path(__file__).resolve().parents[1]

# pytest's default `python_files`; pyproject.toml does not override it.
TEST_MODULE_GLOBS = ("test_*.py", "*_test.py")


def collected_modules(root=TESTS):
    """Every file under `root` that pytest would collect as a test module."""
    found = set()
    for pattern in TEST_MODULE_GLOBS:
        found.update(p for p in root.rglob(pattern) if "__pycache__" not in p.parts)
    return sorted(found)


def duplicate_basenames(paths):
    """{basename: [paths]} for each basename more than one of `paths` uses."""
    by_name = defaultdict(list)
    for p in paths:
        by_name[p.name].append(p)
    return {name: sorted(ps) for name, ps in by_name.items() if len(ps) > 1}


def test_every_test_module_basename_is_unique_across_the_tree():
    modules = collected_modules()
    # A glob that matched nothing would pass vacuously, so require both tiers to be in view.
    for tier in ("host", "fj"):
        assert any(p.parent.name == tier for p in modules), "no test module found under tests/%s" % tier
    dups = duplicate_basenames(modules)
    assert not dups, (
        "pytest imports a test module by its basename when its directory has no __init__.py, so "
        "these cannot be collected in one run (CI runs the whole tree): "
        + "; ".join("%s: %s" % (name, ", ".join(p.relative_to(TESTS).as_posix() for p in ps))
                    for name, ps in sorted(dups.items())))


def test_the_check_rejects_a_duplicate_and_only_a_duplicate():
    """R9: the check has to be able to fail. A shared basename in two tiers is flagged with both
    paths; distinct basenames, and the same directory name holding different files, are not."""
    host_x, fj_x, fj_y = Path("tests/host/test_x.py"), Path("tests/fj/test_x.py"), Path("tests/fj/test_y.py")
    assert duplicate_basenames([host_x, fj_x, fj_y]) == {"test_x.py": sorted([host_x, fj_x])}
    assert duplicate_basenames([host_x, fj_y]) == {}


def test_the_scan_sees_both_patterns_pytest_collects(tmp_path):
    """The `*_test.py` spelling is a test module too; a scan that only globbed `test_*.py` would
    miss a collision between two of those."""
    for rel in ("host/test_a.py", "fj/b_test.py", "fj/helper.py", "fj/__pycache__/test_c.py"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("", encoding="utf-8")
    assert [p.relative_to(tmp_path).as_posix() for p in collected_modules(tmp_path)] == [
        "fj/b_test.py", "host/test_a.py"]
