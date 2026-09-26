"""fix/gamespeed-validate-doors: each mutation of the fix must FAIL a check.

    python scratchpad/12m/gamespeed_validate_mutations.py   (prints docs/ship-evidence/gamespeed_validate_mutations.log;
                                                             every file it mutates is restored)

M1-M3 break the door replay three ways and run the host test (tests/host/test_gamespeed_validate.py,
~1 s); M4 gives the selftest's recorded binary ends the door-blind answer and runs `gamespeed.py
--selftest` (~80 s), whose N6e must then fail."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # the repo root
GS_FILE = "scratchpad/12m/gamespeed.py"
HOST = [sys.executable, "-m", "pytest", "tests/host/test_gamespeed_validate.py", "-q", "-p",
        "no:cacheprovider"]
SELF = [sys.executable, "scratchpad/12m/gamespeed.py", "--selftest"]
CASES = [
    ("M1 --validate defaults to the doors-shut replay", GS_FILE,
     "quiet=False,\n                     doors=True):", "quiet=False,\n                     doors=False):",
     HOST),
    ("M2 the loop steps the doors-shut scene", GS_FILE,
     "st = dsim.step(st, kd) if dsim else rm.step_sim(st, kd, scene=scene)",
     "st = rm.step_sim(st, kd, scene=scene)", HOST),
    ("M3 DoorSim ignores `use` (no door ever opens)", "scratchpad/12m/onewalk.py",
     'bool(kd.get("use"))', "False", HOST),
    ("M4 the recorded binary end of run 0 is the door-blind one", GS_FILE,
     "BINARY_ENDS = ((831, 653),", "BINARY_ENDS = ((831, 485),", SELF),
]


def last(out: str, key: str) -> str:
    lines = [l for l in out.splitlines() if key in l]
    return lines[-1].strip() if lines else "(no %r line)" % key


print("# fix/gamespeed-validate-doors: each mutation must FAIL a check (source mutated, check run, restored)")
for name, rel, a, b, cmd in CASES:
    p = ROOT / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    assert text.count(a) == 1, (name, text.count(a))
    try:
        p.write_bytes(text.replace(a, b).encode("utf-8"))
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=1800)
        verdict = last(r.stdout, "SELFTEST") if cmd is SELF else r.stdout.strip().splitlines()[-1]
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
