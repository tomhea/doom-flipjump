"""fix/gamespeed-validate-doors: each mutation of the fix must FAIL a check.

    python scratchpad/12m/gamespeed_validate_mutations.py   (prints docs/ship-evidence/gamespeed_validate_mutations.log;
                                                             every file it mutates is restored)

M1-M3 and M5-M6 break the door replay five ways and run the host test
(tests/host/test_gamespeed_validate.py, ~1 s); M5 and M6 are PR #89 review round 1's, which the first
version of the checks let through. M4 gives the selftest's recorded binary ends the door-blind answer
and runs `gamespeed.py --selftest` (~4 min), whose N6e must then fail.

M7-M9 break `gamespeed_trail.same` -- the ONE comparison its TRAIL verdict and both controls call
(PR #89 review round 2) -- and run the trail's verdicts on runs 0 and 1 with the BINARY's trail
replayed from --validate's door-aware record, which the tool's own TRAIL shows equal to the binary
on every frame (docs/ship-evidence/blocked27_gamespeed_trail.log): the driver exercises the
verdicts' teeth without running the binary. Dropping the door term must fail CONTROL-DOORS, dropping
the pose term CONTROL-POSE, and comparing nothing both."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the repo root
GS_FILE = "scratchpad/12m/gamespeed.py"
HOST = [sys.executable, "-m", "pytest", "tests/host/test_gamespeed_validate.py", "-q", "-p",
        "no:cacheprovider"]
SELF = [sys.executable, "scratchpad/12m/gamespeed.py", "--selftest"]
TRAIL_FILE = "scratchpad/12m/gamespeed_trail.py"
TRAIL = [sys.executable, "-c", "\n".join([
    "import sys",
    "sys.path[:0] = ['scratchpad/12m', 'scratchpad/gp']",
    "import gamespeed_trail as T, onewalk",
    "doors, shut, wrong = T.records(2)",
    "dsim = onewalk.DoorSim()",
    "passes = [dsim.passes[si] for si in dsim.order]",
    "trails = {r: ([tuple(v) + (0,) for v in doors[r]], len(doors[r])) for r in (0, 1)}",
    "sys.exit(T.report(*T.verdicts(trails, doors, shut, wrong, passes)))"])]
CASES = [
    ("M1 --validate defaults to the doors-shut replay", GS_FILE,
     "doors=True, trails=None):", "doors=False, trails=None):",
     HOST),
    ("M2 the loop steps the doors-shut scene", GS_FILE,
     "st = dsim.step(st, kd) if dsim else rm.step_sim(st, kd, scene=scene)",
     "st = rm.step_sim(st, kd, scene=scene)", HOST),
    ("M3 DoorSim ignores `use` (no door ever opens)", "scratchpad/12m/onewalk.py",
     'bool(kd.get("use"))', "False", HOST),
    ("M4 the recorded binary end of run 0 is the door-blind one", GS_FILE,
     "BINARY_ENDS = ((831, 653),", "BINARY_ENDS = ((831, 485),", SELF),
    ("M5 the door stepper is not reset between runs", GS_FILE,
     "(dsim.reset() if dsim else sp)", "(dsim.spawn if dsim else sp)", HOST),
    ("M6 DoorSim drops the use-box test (`use` opens any door)", "scratchpad/12m/onewalk.py",
     "and in_use_box_fixed(self.boxes[si], st.x, st.y))", ")", HOST),
    ("M7 the trail's comparison drops its door term", TRAIL_FILE,
     "\n            and (not doors or b[3] == v[3]))", ")", TRAIL),
    ("M8 the trail's comparison drops its pose term", TRAIL_FILE,
     "b[4] == 0 and b[:3] == v[:3]", "b[4] == 0", TRAIL),
    ("M9 the trail's comparison compares nothing", TRAIL_FILE,
     "b[4] == 0 and b[:3] == v[:3]\n            and (not doors or b[3] == v[3]))", "b[4] == 0)", TRAIL),
]


def last(out: str, key: str) -> str:
    lines = [l for l in out.splitlines() if key in l]
    return lines[-1].strip() if lines else "(no %r line)" % key


def trail_verdict(r) -> str:
    """the trail driver's exit code and each verdict's PASS/FAIL"""
    names = ("TRAIL", "CONTROL-POSE", "CONTROL-DOORS")
    got = []
    for n in names:
        ln = last(r.stdout, n + " ")
        got.append("%s %s" % (n, "PASS" if ": PASS" in ln else "FAIL" if ": FAIL" in ln else "?"))
    return "rc=%d: %s" % (r.returncode, ", ".join(got))


print("# fix/gamespeed-validate-doors: each mutation must FAIL a check (source mutated, check run, restored)")
for name, rel, a, b, cmd in CASES:
    p = ROOT / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    assert text.count(a) == 1, (name, text.count(a))
    try:
        p.write_bytes(text.replace(a, b).encode("utf-8"))
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
        verdict = (last(r.stdout, "SELFTEST") if cmd is SELF else trail_verdict(r) if cmd is TRAIL
                   else r.stdout.strip().splitlines()[-1])
        n6e = [l.strip() for l in r.stdout.splitlines() if l.strip().startswith("N6e ")]
        extra = ("  [" + " ".join(n6e[0].split()) + "]") if cmd is SELF and n6e else ""
        print("%-58s -> %s%s" % (name, verdict, extra), flush=True)
    finally:
        p.write_bytes(orig)
    assert p.read_bytes() == orig, "restore failed: %s" % rel
r = subprocess.run(HOST, cwd=ROOT, capture_output=True, text=True, timeout=600)
print("%-58s -> %s" % ("unmutated (restored, byte-identical): the host test",
                       r.stdout.strip().splitlines()[-1]))
r = subprocess.run(SELF, cwd=ROOT, capture_output=True, text=True, timeout=1800)
print("%-58s -> %s" % ("unmutated: the selftest", last(r.stdout, "SELFTEST")))
r = subprocess.run(TRAIL, cwd=ROOT, capture_output=True, text=True, timeout=1800)
print("%-58s -> %s" % ("unmutated: the trail's verdicts (runs 0-1, replayed)", trail_verdict(r)))
