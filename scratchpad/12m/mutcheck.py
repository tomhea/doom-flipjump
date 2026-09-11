"""Do the NEW tests actually catch a broken renderer, or do they merely pass?

An agent reporting "I mutated the source and my test failed" is a claim, not evidence. This runs
the mutations here, in this checkout, against the tests as they stand on disk -- the same R9
discipline every verification tool in this repo owes (docs/cr-rules.md).

    python scratchpad/12m/mutcheck.py            # run every mutation
    python scratchpad/12m/mutcheck.py --selftest # the controls below

Each entry breaks ONE real constant or expression the way a person plausibly would, runs the test
file that claims to cover it, and REQUIRES a failure. The source is restored whatever happens --
including on Ctrl-C -- because a half-restored src/ is worse than an unverified test.

CONTROLS (R9)
  C1 THE MUTATION MUST APPLY -- an `old` string that no longer appears is reported as a BROKEN
     CHECK, never silently skipped. That is how a mutation suite quietly stops testing anything.
  C2 THE TEST MUST PASS CLEAN -- every target file is run unmutated first. A file that is already
     red would "catch" every mutation for the wrong reason.
  C3 THE SOURCE MUST COME BACK -- every file is byte-compared to its backup after restore.
"""
import argparse
import shutil
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
]


def _run(testfile, timeout=300):
    r = subprocess.run([sys.executable, "-m", "pytest", testfile, "-q", "--no-header", "-x"],
                       cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return r.returncode == 0, (r.stdout or "")[-400:]


def main(selftest=False):
    files = sorted({m[1] for m in MUTATIONS})
    tests = sorted({m[4] for m in MUTATIONS})
    backups = {}
    fails = []
    try:
        for f in files:
            p = ROOT / f
            backups[f] = p.read_bytes()

        print("C2 -- every target test file must be GREEN before any mutation")
        for t in tests:
            ok, tail = _run(t)
            print("   %-46s %s" % (t, "green" if ok else "!! ALREADY RED"))
            if not ok:
                fails.append("C2 %s already red" % t)
        if fails:
            print("\nRefusing to mutate against a red suite.")
            return 1

        print("\nMUTATIONS -- each must turn its test file RED")
        for label, f, old, new, t in MUTATIONS:
            p = ROOT / f
            src = p.read_text(encoding="utf-8")
            if src.count(old) != 1:
                print("   %-44s !! C1 BROKEN CHECK: anchor appears %d times in %s"
                      % (label, src.count(old), f))
                fails.append("C1 %s" % label)
                continue
            p.write_text(src.replace(old, new), encoding="utf-8")
            try:
                ok, tail = _run(t)
            finally:
                p.write_bytes(backups[f])
            print("   %-44s %s" % (label, "CAUGHT" if not ok else "!! NOT CAUGHT by " + t))
            if ok:
                fails.append("%s survived %s" % (t, label))
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
                    help="same run; the controls ARE the selftest (C1 anchor, C2 clean, C3 restore)")
    a = ap.parse_args()
    sys.exit(main(selftest=a.selftest))
