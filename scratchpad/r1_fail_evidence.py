"""R1 -- the FAIL run for every test file this PR adds, plus mutation teeth for the persist tests.

R1 asks for a test shown RED before its subject existed. Seven test files on this PR had none: the
body's two FAIL-then-PASS pairs were both bug fixes, which proves those tests can fail for a
REGRESSION but says nothing about whether they are attached to the feature they claim to gate.
A test that passes because it never reached its subject is the failure mode, and it is invisible in
a green run.

So for each new file this hides the module it tests -- the honest "before this existed" state --
runs that file alone, and records the result. Then it puts the module back and runs it again, so
each row is a FAIL/PASS pair from the same command.

    python scratchpad/r1_fail_evidence.py [--only substr]

The last block is different: `tests/host/test_selfreset.py` is NOT a new file, so hiding a module
proves nothing there. Its five new `persist=` tests get three MUTATIONS of the code path instead --
one per assert, one for the exclusion itself -- and each must take down a specific test.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (test file, [modules to hide], what the hiding removes)
CASES = [
    ("tests/host/test_mapprefix.py", ["src/doomfj/mapprefix.py"], "the label-prefixer itself"),
    ("tests/host/test_doors.py", ["src/doomfj/doors.py"], "the door geometry"),
    ("tests/host/test_menu.py", ["src/doomfj/menu.py"], "the menu generator"),
    ("tests/host/test_collines_device.py", ["tests/fj/stream_screen.py"],
     "the harness that speaks the 0x0B protocol"),
    ("tests/fj/test_keyboard_input.py", ["src/fj/input.fj"], "kb.poll"),
    ("tests/fj/test_menu_frame.py", ["src/doomfj/menu.py"], "the menu generator"),
    ("tests/fj/test_menu_mode.py", ["src/fj/input.fj", "src/doomfj/menu.py"],
     "kb.poll and the menu generator"),
]

# (label, file, from, to, the test that must go red)
MUTANTS = [
    ("persist becomes a no-op", "src/doomfj/selfreset.py",
     "    if persisted:\n        words = [x for x in words if x not in persisted]",
     "    if False:\n        words = [x for x in words if x not in persisted]",
     "test_persist_excludes_only_the_named_labels_cells"),
    ("the unknown-name assert is dropped", "src/doomfj/selfreset.py",
     '        assert name in bits, (\n            "self-reset: persist names %r, which this build has no label for" % name)',
     '        if name not in bits:\n            continue',
     "test_persist_refuses_a_name_this_build_has_no_label_for"),
    ("the empty-hit assert is dropped", "src/doomfj/selfreset.py",
     '        assert hit, (', '        if False: assert hit, (',
     "test_persist_refuses_a_label_the_restore_set_never_dirties"),
]

ap = argparse.ArgumentParser()
ap.add_argument("--only", default="")
args = ap.parse_args()


def run(target, extra=()):

    p = subprocess.run([sys.executable, "-m", "pytest", target, "-q", "--no-header", *extra],
                       cwd=ROOT, capture_output=True, text=True, timeout=1800)
    lines = [l for l in p.stdout.splitlines() if l.strip()]
    failed = {l.split("::")[-1].split()[0] for l in lines if l.startswith(("FAILED", "ERROR"))}
    return p.returncode, (lines[-1] if lines else "(no output)"), failed


rows, ok = [], True
for target, modules, what in CASES:
    if args.only and args.only not in target:
        continue
    hidden = []
    try:
        for m in modules:
            src = ROOT / m
            dst = src.with_suffix(src.suffix + ".r1hidden")
            shutil.move(str(src), str(dst)); hidden.append((src, dst))
        rc_bad, line_bad, _f = run(target)
    finally:
        for src, dst in hidden:
            shutil.move(str(dst), str(src))
    rc_good, line_good, _g = run(target)
    red = rc_bad != 0
    ok &= red and rc_good == 0
    print("%-38s without %-42s %s" % (Path(target).name, what,
                                      "RED" if red else "!! STILL GREEN"))
    print("      before: %s" % line_bad)
    print("      after : %s" % line_good, flush=True)

print("")
print("---- persist mutants (tests/host/test_selfreset.py is not a new file) ----")
SEL = ROOT / "src/doomfj/selfreset.py"
orig = SEL.read_text(encoding="utf-8")
for label, _f, a, b, want in MUTANTS:
    assert orig.count(a) == 1, "mutation anchor not unique: %s" % label
    try:
        SEL.write_text(orig.replace(a, b), encoding="utf-8")
        rc, line, failed = run("tests/host/test_selfreset.py")
    finally:
        SEL.write_text(orig, encoding="utf-8")
    # RED IS NOT ENOUGH: the mutant must take down the test that names that behaviour. A mutation
    # that breaks some OTHER test would still turn the file red and prove nothing about this one.
    red, hit = rc != 0, want in failed
    ok &= red and hit
    print("%-34s -> %-14s %-40s %s" % (label, "RED" if red else "!! STILL GREEN",
                                       ("killed " + want[13:]) if hit else "!! WRONG TEST DIED",
                                       line))
assert SEL.read_text(encoding="utf-8") == orig, "selfreset.py was not restored"

print("")
print("VERDICT: %s" % ("PASS -- every new test file is red without its subject, and every persist "
                       "mutant is caught" if ok else "FAIL -- see the STILL GREEN rows"))
sys.exit(0 if ok else 1)
