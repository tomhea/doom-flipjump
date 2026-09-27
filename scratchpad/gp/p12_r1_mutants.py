"""M7 P1.2 -- R1 for the NEW tests in EXISTING test files (PR #91's review, after PR #78's ruling).

On main those files fail as a whole -- an import error -- which names no test and hides the file's
unchanged ones. So each new test is shown RED here against a targeted break of the code it guards,
applied to a copy of this tree (`git archive HEAD`), and GREEN on the unbroken copy: the same
command, one line changed.

    python scratchpad/gp/p12_r1_mutants.py            # the baseline, then every mutant
    python scratchpad/gp/p12_r1_mutants.py --only M6  # one
"""
import argparse
import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CM = "tests/host/test_collision_more.py"
CF = "tests/fj/test_collision_fj.py"

# (id, what breaks, file, from, to, [the tests that must go red])
MUTANTS = [
    ("M1", "the three candidate moves enter a SECOND cell root", "src/doomfj/collision.py",
     'f"    sim.try_move {root}, {height}, {maxstep}, cm_hf",',
     'f"    sim.try_move {root}_x, {height}, {maxstep}, cm_hf",',
     [CM + "::test_all_four_checks_enter_the_same_cell_routine"]),
    ("M2", "a move-block jump takes the map prefix", "src/doomfj/collision.py",
     '"    ;cmv_done",', 'f"    ;{mapname_pfx}_cmv_done",',
     [CM + "::test_only_the_seed_descent_and_the_cell_root_are_map_prefixed"]),
    ("M3", "a line's slope code leaves its one nibble", "src/doomfj/collision.py",
     "slope, flags, opentop, openbottom))", "slope + 4, flags, opentop, openbottom))",
     [CM + "::test_every_line_constant_survives_the_argument_cell_it_is_xored_into"]),
    ("M4", "the model refuses a position in no cell", "src/doomfj/collision.py",
     "    for li in lists.get((cell_of(x16), cell_of(y16)), ()):",
     "    if (cell_of(x16), cell_of(y16)) not in lists:\n"
     "        return (False, seed_floor, seed_ceil)\n"
     "    for li in lists.get((cell_of(x16), cell_of(y16)), ()):",
     [CM + "::test_the_cell_model_agrees_with_the_oracle_off_the_map"]),
    ("M5", "the cell size moves without the tree", "src/doomfj/collision.py",
     "CELL_SHIFT = 21", "CELL_SHIFT = 20",
     [CM + "::test_the_cell_size_is_the_one_the_trees_nibble_split_describes"]),
    ("M6", "the shared line test never refuses", "src/fj/sim.fj",
     "        hex.zero 1, cp_ok                       // one-sided, ML_BLOCKING or a shut door: LATCH",
     "        hex.set 1, cp_ok, 1                     // (M6: the latch never refuses)",
     [CF + "::test_the_cell_routine_matches_the_oracle",
      CF + "::test_the_door_lines_follow_their_doors_states"]),
    # the walk meets no wall: what it guards is the ONE-IMAGE hygiene -- every argument cell back to
    # zero after each line, or the next line tests against the leftovers
    ("M9", "a line stub leaves an argument nibble dirty", "src/doomfj/collision.py",
     '        out += xors + ["    stl.fret cc_lret"]',
     '        out += xors[1:] + ["    stl.fret cc_lret"]',
     [CF + "::test_a_walked_trajectory_matches_too"]),
    ("M7", "a door line ignores its door's state", "src/doomfj/collision.py",
     "{shut_mask:#06x}, {nxt}, {lab}_shut", "0x0000, {nxt}, {lab}_shut",
     [CF + "::test_the_door_lines_follow_their_doors_states"]),
    ("M8", "the emitter ignores the cell lists it is handed", "src/doomfj/collision.py",
     "def collision_cells_fj(pfx: str, rows, lists, doors=None) -> tuple:",
     "def collision_cells_fj(pfx: str, rows, lists, doors=None) -> tuple:\n"
     "    lists = cell_lists(rows, 16 << 16)",
     [CF + "::test_a_routine_missing_one_line_is_caught"]),
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
    env = dict(__import__("os").environ, PYTHONPATH=str(Path(tmp) / "src"))
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
            print("   %-100s %s" % (n, " ".join(got.get(n, ["MISSING"]))))
        ok &= green
    for mid, what, path, old, new, must in MUTANTS:
        if args.only and mid != args.only:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tree(tmp)
            f = Path(tmp) / path
            text = f.read_text(encoding="utf-8")
            assert text.count(old) == 1, "%s: the mutation site moved in %s" % (mid, path)
            f.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
            got, tail = run(tmp, must)
            red = all(got.get(n) and all(o.startswith("FAILED") for o in got[n]) for n in must)
            print("%s %s (%s): %s -- %s" % (mid, what, path, "every named test RED" if red
                                            else "!! NOT CAUGHT", tail))
            for n in must:
                print("   %-100s %s" % (n, " ".join(got.get(n, ["MISSING"]))))
            ok &= red
    print("R1 MUTANTS: %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
