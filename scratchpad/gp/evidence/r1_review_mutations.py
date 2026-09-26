"""PR #87 review round 1: each new or fixed test must FAIL on the mutation the reviewer found
getting through. Mutates the source in place, runs the test, restores; prints one line per case.

usage: python scratchpad/gp/evidence/r1_review_mutations.py  (prints the lines of r1_review_mutations.log;
every file it mutates is restored)"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the repo root
CASES = [
    ("aim: the farther target wins", "src/doomfj/combat.py",
     "if best is not None and (tz, order) >= best[0]:",
     "if best is not None and (tz, order) <= best[0]:", ["tests/host/test_gp_aim.py"]),
    ("aim: the sight check disabled", "src/doomfj/combat.py",
     "if not world.los_points((ws.px, ws.py), (x << 16, y << 16)):",
     "if False and world.los_points((ws.px, ws.py), (x << 16, y << 16)):", ["tests/host/test_gp_aim.py"]),
    ("nukage: a 16-tic period", "src/doomfj/combat.py",
     "HURT_PERIOD_MASK = 0x1F", "HURT_PERIOD_MASK = 0x0F", ["tests/host/test_gp_restart.py"]),
    ("walls: a mover that refuses every step", "src/doomfj/world.py",
     "        r, h = self.mon_radius[m], self.mon_height[m]\n",
     "        r, h = self.mon_radius[m], self.mon_height[m]\n        return V_WALL, None\n",
     ["tests/host/test_gp_world.py::test_a_monster_cannot_step_through_a_wall"]),
]
print("# PR #87 review round 1: the mutation each new/fixed test must catch (source mutated, test run, restored)")
for name, rel, a, b, tests in CASES:
    p = ROOT / rel
    orig = p.read_text(encoding="utf-8")
    assert orig.count(a) == 1, (name, orig.count(a))
    try:
        p.write_text(orig.replace(a, b), encoding="utf-8", newline="\n")
        r = subprocess.run(["python", "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                           cwd=ROOT, capture_output=True, text=True)
        print("%-42s -> %s" % (name, r.stdout.strip().splitlines()[-1]))
    finally:
        p.write_text(orig, encoding="utf-8", newline="\n")
r = subprocess.run(["python", "-m", "pytest", "tests/host/test_gp_aim.py", "tests/host/test_gp_restart.py",
                    "tests/host/test_gp_world.py", "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                   capture_output=True, text=True)
print("%-42s -> %s" % ("unmutated (restored)", r.stdout.strip().splitlines()[-1]))
