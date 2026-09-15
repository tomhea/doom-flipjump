"""Do the NEW tests actually catch a broken renderer, or do they merely pass?

An agent reporting "I mutated the source and my test failed" is a claim, not evidence. This runs
the mutations here, in this checkout, against the tests as they stand on disk -- the same R9
discipline every verification tool in this repo owes (docs/cr-rules.md).

    python scratchpad/12m/mutcheck.py            # run every mutation
    python scratchpad/12m/mutcheck.py --selftest # the same, plus R9 and the NEG arms below

Each entry breaks ONE real constant or expression the way a person plausibly would, runs the test
file that claims to cover it, and REQUIRES a failure. The source is restored whatever happens --
including on Ctrl-C -- because a half-restored src/ is worse than an unverified test.

CONTROLS (R9)
  C1 THE MUTATION MUST APPLY -- an `old` string that no longer appears is reported as a BROKEN
     CHECK, never silently skipped. That is how a mutation suite quietly stops testing anything.
  C2 THE TEST MUST PASS CLEAN -- every target file is run unmutated first. A file that is already
     red would "catch" every mutation for the wrong reason.
  C3 THE SOURCE MUST COME BACK -- every file is byte-compared to its backup after restore.
  C4 EVERY NEW TEST FILE MUST BE NAMED -- the twelve tests/host files this branch adds are listed
     below and each must appear as some mutation's target. Without it "all twelve carry FAIL
     evidence" is a claim about the version of this table it was written against, not a checked
     property, and a row deleted later takes its file's evidence with it silently. Pure
     bookkeeping over the table, so it runs BEFORE C2 and still reports when a file is red.
  R9 THE HARNESS MUST BE ABLE TO SAY NO -- `--selftest` adds one COMMENT-ONLY edit and requires
     mutcheck to report it NOT CAUGHT. What that rules out is narrow, so state it exactly: it is
     the run behind the claim that the CAUGHT verdicts are SEMANTIC. This harness rewrites files
     under src/ while launching pytest against them; the arm proves a behaviour-neutral WRITE
     does not by itself redden a suite, i.e. CAUGHT means "the edit broke the code", not
     "mutcheck touched the file". It does NOT stand between the harness and a `_run` that stopped
     reading the return code: a constant-RED `_run` never reaches the arm (C2 ends the run at
     "Refusing to mutate against a red suite"), and a constant-GREEN one is already 17 `survived`
     entries from MUTATIONS.
 NEG THE NEW CONTROLS MUST THEMSELVES BE ABLE TO FAIL -- `--selftest` finally runs C4 against a
     table with a file's rows removed, and the R9 arm against a stub runner that calls the
     comment edit red, and REQUIRES both to report a failure. In-process and in this file: a
     control whose own control is a copy of the tool kept somewhere else is a copy that drifts,
     and an uncommitted one is not evidence at all. Costs no pytest -- C4 is bookkeeping and the
     R9 negative needs only the verdict, so its runner never launches anything.
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (label, source file, exact text to replace, replacement, test file that must go red)
MUTATIONS = [
    ("wireformat: wrong magic byte",
     "src/doomfj/wireformat.py", "MAGIC = 0xD0", "MAGIC = 0xD1",
     "tests/host/test_wireformat.py"),
    ("wireformat: state one byte short",
     "src/doomfj/wireformat.py", "STATE_BYTES = 12", "STATE_BYTES = 11",
     "tests/host/test_wireformat.py"),
    ("doorcode: wait counter one nibble",
     "src/doomfj/doorcode.py", "WAIT_NIBBLES = 2", "WAIT_NIBBLES = 1",
     "tests/host/test_doorcode_more.py"),
    ("mapcompiler: point-side operands swapped",
     "src/doomfj/mapcompiler.py",
     "return dx * (y - py) - dy * (x - px)",
     "return dy * (y - py) - dx * (x - px)",
     "tests/host/test_mapcompiler_more.py"),
    ("doors: quantise loses the open endpoint",
     "src/doomfj/doors.py", "    if h >= open_h:\n        return open_h",
     "    if h > open_h:\n        return open_h",
     "tests/host/test_doors.py"),
    ("doors: stamp ignores the quantum",
     "src/doomfj/doors.py", '"quant": quant, "speed": SPEED',
     '"quant": DEFAULT_QUANT, "speed": SPEED',
     "tests/host/test_build_more.py"),
    # ⚠ RETIRED: "icon catch loses struct.error". It broke the except clause around
    # `decode_picture`, and there is no decode any more -- the icon is generated from
    # WINDOW_ICON_ART. C1 caught the dead anchor rather than skipping it, which is the whole
    # reason C1 exists. The two below target what replaced it.
    ("wall_renderer: the chrome goes back into the per-frame prelude",
     "src/doomfj/wall_renderer.py",
     '    prelude = ["present.set_palette palette"]',
     '    prelude = ["present.set_palette palette"] + _chrome_calls',
     "tests/host/test_wall_renderer_helpers.py"),
    ("wall_renderer: icon ink becomes the transparent index",
     "src/doomfj/wall_renderer.py", "WINDOW_ICON_INDEX = 181", "WINDOW_ICON_INDEX = 0",
     "tests/host/test_wall_renderer_helpers.py"),
    ("wall_renderer: a declared ablate mode with no consumer",
     "src/doomfj/wall_renderer.py",
     '                           "slopetwice", "tabletwice",',
     '                           "slopetwice", "tabletwice", "planes",',
     "tests/host/test_wall_renderer_helpers.py"),
    ("build: metrics features gains a key the slow guard does not name",
     "src/doomfj/build.py", '"menu": menu},', '"menu": menu, "sector_heights": False},',
     "tests/host/test_build_more.py"),
    ("things: hot/cold field split shifted",
     "src/doomfj/things.py", "_HOT_FIELDS = (0, 1, 2, 3, 4, 5, 8)",
     "_HOT_FIELDS = (0, 1, 2, 3, 4, 5, 7)",
     "tests/host/test_things_more.py"),
    # The eleven rows above name six of THE_TWELVE; the six below name the other six. The
    # alternative on offer -- "the file goes red when you hide the module it imports" -- is a
    # property a file whose only link to its subject is an unused import also has, so it is not
    # evidence that these tests catch anything.
    ("collision: the blockmap guard forgets the grid origin",
     "src/doomfj/collision.py",
     "if not (0 <= bx - bx0 < nbx and 0 <= by - by0 < nby):",
     "if not (0 <= bx < nbx and 0 <= by < nby):",
     "tests/host/test_collision_more.py"),
    ("reference_model: a shut door's zero opening reads as open",
     "src/doomfj/reference_model.py",
     "_closed2s = min(_f2.ceil_h, _b2.ceil_h) <= max(_f2.floor_h, _b2.floor_h)",
     "_closed2s = min(_f2.ceil_h, _b2.ceil_h) < max(_f2.floor_h, _b2.floor_h)",
     "tests/host/test_door_occlusion.py"),
    ("fastrun: the run coalescer never extends a run",
     "src/doomfj/fastrun.py", "nxt = addr + 1", "nxt = addr",
     "tests/host/test_fastrun.py"),
    ("lut_generator: the emit handler stride loses the jump op",
     "src/doomfj/lut_generator.py", "HSTRIDE = 9", "HSTRIDE = 8",
     "tests/host/test_lut_generator_more.py"),
    ("nodebuilder: a split fragment's offset restarts at zero",
     "src/doomfj/nodebuilder.py",
     "b = replace(s, x1=mx, y1=my, offset=s.offset + run)",
     "b = replace(s, x1=mx, y1=my, offset=run)",
     "tests/host/test_nodebuilder_more.py"),
    ("reference_model: the step-up rule compares map units to 16.16",
     "src/doomfj/reference_model.py",
     "if (floorz - here_floor) << 16 > MAX_STEP:",
     "if (floorz - here_floor) > MAX_STEP:",
     "tests/host/test_reference_model_more.py"),
]

# R9 -- THE HARNESS'S OWN NEGATIVE CONTROL, run by --selftest. Changing a COMMENT cannot change
# behaviour, so mutcheck must report this one NOT CAUGHT. That is what makes every CAUGHT above
# semantic rather than an artifact of rewriting a file in src/ while pytest imports it: the same
# write-and-restore machinery, the same test file, an edit with no meaning. (It is NOT a guard
# against a broken `_run` -- see the R9 paragraph in the module docstring for what already is.)
# Same five-field shape as a mutation, opposite expectation.
INERT = ("control: a comment-only edit must NOT be caught",
         "src/doomfj/wireformat.py",
         "# the present-protocol command carrying the thing BINDINGS back out",
         "# INERT mutcheck control -- this line is a comment and changes nothing",
         "tests/host/test_wireformat.py")

# Every tests/host file this branch adds, in order: `git diff --diff-filter=A --name-only main
# HEAD -- tests/` lists exactly these twelve and nothing else (they all arrive in efde61c).
THE_TWELVE = [
    "tests/host/test_build_more.py",
    "tests/host/test_collision_more.py",
    "tests/host/test_door_occlusion.py",
    "tests/host/test_doorcode_more.py",
    "tests/host/test_fastrun.py",
    "tests/host/test_lut_generator_more.py",
    "tests/host/test_mapcompiler_more.py",
    "tests/host/test_nodebuilder_more.py",
    "tests/host/test_reference_model_more.py",
    "tests/host/test_things_more.py",
    "tests/host/test_wall_renderer_helpers.py",
    "tests/host/test_wireformat.py",
]


def _run(testfile, timeout=300):
    r = subprocess.run([sys.executable, "-m", "pytest", testfile, "-q", "--no-header", "-x"],
                       cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout or "")[-400:]


def _always_red(_testfile):
    """The NEG arm's stub runner: every file reads red, and no pytest is launched."""
    return False, ""


def _mutate(row, backups, run=None, say=print):
    """Count the anchor, write the edit, run the test file, restore the source byte for byte.

    The MUTATIONS loop and the R9 arm share this body instead of keeping a copy each, so the two
    cannot drift apart (CLAUDE.md rule 5). Only the VERDICT differs between them, so only the
    verdict is printed by the caller. Returns (applied, caught); `applied` is False when C1
    rejected the anchor, and the restore happens whatever the run does.
    """
    run = run or _run   # resolved here, not at def time, so a sandbox can substitute _run
    label, f, old, new, t = row
    p = ROOT / f
    # The backup is looked up BEFORE the write, so a missing one refuses to mutate instead of
    # being discovered in the `finally` with the file already edited.
    backup = backups[f]
    src = p.read_text(encoding="utf-8")
    if src.count(old) != 1:
        say("   %-44s !! C1 BROKEN CHECK: anchor appears %d times in %s"
            % (label, src.count(old), f))
        return False, False
    p.write_text(src.replace(old, new), encoding="utf-8")
    try:
        ok, _tail = run(t)
    finally:
        p.write_bytes(backup)
    return True, not ok


def _c4(mutations, say=print):
    """C4: every file in THE_TWELVE must be NAMED by some row of `mutations` and be on disk.

    Bookkeeping over the table -- it launches nothing, which is why it runs before C2 and why its
    own negative control below needs no pytest either. Prints a line per file, returns the fails,
    and the negative control calls THIS, so what it proves is the arm the run uses.
    """
    named = {m[4] for m in mutations}
    out = []
    for t in THE_TWELVE:
        ok = t in named and (ROOT / t).exists()
        say("   %-46s %s" % (t, "covered" if ok else "!! NOT COVERED"))
        if not ok:
            out.append("C4 %s uncovered" % t)
    return out


def _r9(backups, run=None, say=print):
    """The R9 arm: apply INERT's comment-only edit and REQUIRE it NOT to be caught. -> fails."""
    label, t = INERT[0], INERT[4]
    applied, caught = _mutate(INERT, backups, run=run, say=say)
    if not applied:
        return ["C1 %s" % label]
    say("   %-44s %s" % (label, "!! CAUGHT -- an inert edit reddened " + t if caught
                         else "REJECTED (still green)"))
    return ["R9 %s went red on a comment-only edit" % t] if caught else []


def _neg(backups, say=print):
    """R9 turned on the two controls this branch adds: each must be able to report a failure.

    C4's negative is the real C4 over a table with one file's rows removed -- it must then call
    that file uncovered. The R9 arm's negative is the real arm driven by a runner that calls the
    comment edit red -- it must then report the arm caught. Both drive the arm the run itself
    uses, in this process, from this file: no second copy of the tool to keep in step. Each is
    paired with the failure string it must NAME, because "something failed" is the weak half of a
    negative control. The arms' own lines are captured, not printed -- a deliberate "!!" in a
    passing transcript is a trap for whoever greps it -- and the failure strings are printed.
    """
    fails = []
    swallowed = []
    victim = THE_TWELVE[0]
    arms = [
        ("C4, with %s's rows dropped" % victim.split("/")[-1],
         _c4([m for m in MUTATIONS if m[4] != victim], say=swallowed.append),
         "C4 %s uncovered" % victim),
        ("the R9 arm, against a runner that reddens the comment edit",
         _r9(backups, run=_always_red, say=swallowed.append),
         "R9 %s went red" % INERT[4]),
    ]
    for what, got, want in arms:
        say("   %s" % what)
        for g in got:
            say("       -> %s" % g)
        if not [g for g in got if g.startswith(want)]:
            say("       !! ACCEPTED -- this control cannot fail, so it proves nothing")
            fails.append("NEG %s did not report %r" % (what, want))
    return fails


def main(selftest=False):
    # INERT's source and test file are unioned in unconditionally. The R9 arm restores from
    # `backups` and C2 greens what it runs, so neither may depend on the control happening to sit
    # inside MUTATIONS' file set -- which it does today, and which a retired row could end.
    files = sorted({m[1] for m in MUTATIONS} | {INERT[1]})
    tests = sorted({m[4] for m in MUTATIONS} | {INERT[4]})
    backups = {}
    fails = []
    try:
        for f in files:
            p = ROOT / f
            backups[f] = p.read_bytes()

        print("C4 -- every tests/host file this branch adds must be named by a mutation")
        fails += _c4(MUTATIONS)

        print("\nC2 -- every target test file must be GREEN before any mutation")
        red = []
        for t in tests:
            ok, _tail = _run(t)
            print("   %-46s %s" % (t, "green" if ok else "!! ALREADY RED"))
            if not ok:
                red.append(t)
                fails.append("C2 %s already red" % t)
        if red:
            print("\nRefusing to mutate against a red suite.")
            return 1

        print("\nMUTATIONS -- each must turn its test file RED")
        for row in MUTATIONS:
            label, t = row[0], row[4]
            applied, caught = _mutate(row, backups)
            if not applied:
                fails.append("C1 %s" % label)
                continue
            print("   %-44s %s" % (label, "CAUGHT" if caught else "!! NOT CAUGHT by " + t))
            if not caught:
                fails.append("%s survived %s" % (t, label))

        if not selftest:
            print("\nR9 -- control mutation NOT RUN (pass --selftest)")
        else:
            print("\nR9 -- the control mutation, which must NOT be caught")
            fails += _r9(backups)
            print("\nNEG -- C4 and the R9 arm, each against the case it must reject")
            fails += _neg(backups)
    finally:
        for f, b in backups.items():
            (ROOT / f).write_bytes(b)

    print("\nC3 -- source restored")
    for f, b in backups.items():
        same = (ROOT / f).read_bytes() == b
        print("   %-46s %s" % (f, "identical" if same else "!! DIFFERS"))
        if not same:
            fails.append("C3 %s not restored" % f)

    print("")
    print("MUTCHECK %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + "; ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true",
                    help="the same run plus the R9 control mutation; C1-C4 run either way")
    a = ap.parse_args()
    sys.exit(main(selftest=a.selftest))
