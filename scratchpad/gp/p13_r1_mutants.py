"""M7 P1.3 -- R1 for the new tests a parent-rung run cannot show RED one by one.

`tests/host/test_restore_set_shipped.py` is an EXISTING file: on the parent rung it fails as a whole
(it imports THING_PERSIST, which is absent), which names no test and hides the file's unchanged ones.
`test_a_map_with_no_runtime_things_bakes_an_empty_array` arrived after the rung's R1 run (1ce6623).
So each is shown RED here against a targeted break of what it guards, applied to a copy of this tree
(`git archive HEAD`), and GREEN on the unbroken copy -- the same command, one change.

    python scratchpad/gp/p13_r1_mutants.py            # the baseline, then every mutant
    python scratchpad/gp/p13_r1_mutants.py --only M2  # one
"""
import argparse
import gzip
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RS = "tests/host/test_restore_set_shipped.py"
LL = "tests/host/test_leaf_lists.py"
STD_SET = "src/doomfj/data/m5_restore_set.json.gz"


def set_gains_thnext(tmp):
    """a re-key that adds `thnext` to the standalone set without persisting it"""
    f = Path(tmp) / STD_SET
    doc = json.loads(gzip.decompress(f.read_bytes()))
    assert not any(e[0] == "thnext" for e in doc["entries"]), "the set already carries thnext"
    doc["entries"].append(["thnext", 0])
    f.write_bytes(gzip.compress(json.dumps(doc).encode()))


# (id, what breaks, file, from, to -- or None and a function of the tree, [tests that must go red])
MUTANTS = [
    ("M1", "THING_PERSIST names a label the standalone set does not carry", "src/doomfj/build.py",
     'THING_PERSIST = ("sshead", "thss_rt", "thpos_rt")',
     'THING_PERSIST = ("sshead", "thss_rt", "thpos_rt", "thnext")',
     [RS + "::test_the_thing_cells_are_in_the_standalone_set_too"]),
    ("M2", "the standalone set restores thnext, which THING_PERSIST does not keep", STD_SET,
     None, set_gains_thnext,
     [RS + "::test_the_thing_cells_are_in_the_standalone_set_too"]),
    ("M3", "byte_array_decl's extent check before 1ce6623", "src/doomfj/things.py",
     "assert (len(values) < cells or not values) and",
     "assert len(values) < cells and",
     [LL + "::test_a_map_with_no_runtime_things_bakes_an_empty_array"]),
]


def tree(tmp):
    data = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        t.extractall(tmp)
    if (ROOT / "assets").is_dir():
        shutil.copytree(ROOT / "assets", Path(tmp) / "assets")


def run(tmp, nodes):
    """-> {test name (no params): [outcomes of its items]}"""
    env = dict(os.environ, PYTHONPATH=str(Path(tmp) / "src"))
    r = subprocess.run([sys.executable, "-m", "pytest", *nodes, "-q", "-p", "no:cacheprovider",
                        "-rA", "--tb=no"], cwd=tmp, env=env, capture_output=True, text=True)
    out = {}
    for line in r.stdout.splitlines():
        m = re.match(r"^(PASSED|FAILED|ERROR) (\S+?)(\[[^\]]*\])?(?: - .*)?$", line)
        if m:
            out.setdefault(m.group(2), []).append(m.group(1) + (m.group(3) or ""))
    return out, r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-300:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    ok = True
    nodes = sorted({n for m in MUTANTS for n in m[5]})
    with tempfile.TemporaryDirectory() as tmp:
        tree(tmp)
        got, tail = run(tmp, nodes)
        green = all(all(o.startswith("PASSED") for o in got.get(n, ["MISSING"])) for n in nodes)
        print("BASELINE (the tree itself): %s -- %s" % ("all green" if green else "NOT GREEN", tail))
        for n in nodes:
            print("   %-90s %s" % (n, " ".join(got.get(n, ["MISSING"]))))
        ok &= green
    for mid, what, path, old, new, must in MUTANTS:
        if args.only and mid != args.only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tree(tmp)
            if old is None:
                new(tmp)
            else:
                f = Path(tmp) / path
                text = f.read_text(encoding="utf-8")
                assert text.count(old) == 1, "%s: the mutation site moved in %s" % (mid, path)
                f.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            got, tail = run(tmp, must)
            red = all(got.get(n) and all(o.startswith("FAILED") for o in got[n]) for n in must)
            print("%s %s (%s): %s -- %s" % (mid, what, path, "every named test RED" if red
                                            else "!! NOT CAUGHT", tail))
            for n in must:
                print("   %-90s %s" % (n, " ".join(got.get(n, ["MISSING"]))))
            ok &= red
    print("R1 MUTANTS: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
