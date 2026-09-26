"""PR #88 review round 3: the mutations the review found getting through, each must now FAIL a test.

usage: python scratchpad/gp/evidence/r3_review_mutations.py  (prints the lines of r3_review_mutations.log;
every file it mutates is restored)"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the repo root
TRIP = ["tests/host/test_oracle_calls_in_step.py"]
AIM = ["tests/host/test_gp_aim.py"]
M5 = "    render_kw = dict(GAME_RENDER_KW, sprite_wad=art)"
CASES = [
    ("m5_gate: the shared binding, then REBOUND without sky", "scratchpad/m5_gate.py", M5,
     M5 + "\n    render_kw = dict(wall_mode=\"W1R\", floor_mode_ft1=True, plane_near=True, wall_noise=True,\n"
     "                     near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True,\n"
     "                     bbox_cull=True)", TRIP),
    ("m5_gate: the shared binding, then del render_kw['sky']", "scratchpad/m5_gate.py", M5,
     M5 + "\n    del render_kw[\"sky\"]", TRIP),
    ("m5_gate: the shared binding, then .update(sky=False)", "scratchpad/m5_gate.py", M5,
     M5 + "\n    render_kw.update(sky=False)", TRIP),
    ("aim: the LAST target in slot order wins", "src/doomfj/combat.py",
     "if best is not None and (tz, order) >= best[0]:",
     "if best is not None and order < best[0][1]:", AIM),
    ("aim: the FIRST target in slot order wins", "src/doomfj/combat.py",
     "if best is not None and (tz, order) >= best[0]:",
     "if best is not None and order >= best[0][1]:", AIM),
]
print("# PR #88 review round 3: the mutation each hardened test must catch (source mutated, test run, restored)")
for name, rel, a, b, tests in CASES:
    p = ROOT / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    assert text.count(a) == 1, (name, text.count(a))
    try:
        p.write_bytes(text.replace(a, b).encode("utf-8"))
        r = subprocess.run(["python", "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                           cwd=ROOT, capture_output=True, text=True)
        print("%-56s -> %s" % (name, r.stdout.strip().splitlines()[-1]))
    finally:
        p.write_bytes(orig)
    assert p.read_bytes() == orig, "restore failed: %s" % rel
r = subprocess.run(["python", "-m", "pytest", *TRIP, *AIM, "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                   capture_output=True, text=True)
print("%-56s -> %s" % ("unmutated (restored, byte-identical)", r.stdout.strip().splitlines()[-1]))
