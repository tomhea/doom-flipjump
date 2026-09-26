"""PR #87 review round 2: the mutations the review found getting through, each must now FAIL a test.

usage: python scratchpad/gp/evidence/r2_review_mutations.py  (prints the lines of r2_review_mutations.log;
every file it mutates is restored)"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the repo root
TRIP = ["tests/host/test_oracle_calls_in_step.py"]
CASES = [
    ("shared set without sky and bbox_cull", "src/doomfj/reference_model.py",
     "near_steps=True, stack_steps=True, things=True, degrade=True, sky=True,\n                      bbox_cull=True)",
     "near_steps=True, stack_steps=True, things=True, degrade=True)", TRIP),
    ("m5_gate: import kept, its own dict without sky", "scratchpad/m5_gate.py",
     "    render_kw = dict(GAME_RENDER_KW, sprite_wad=art)",
     "    render_kw = dict(wall_mode=\"W1R\", floor_mode_ft1=True, plane_near=True, wall_noise=True,\n"
     "                     near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True,\n"
     "                     bbox_cull=True)", TRIP),
    ("m1_gate: splats an unrelated OLD_KW", "scratchpad/m1_gate.py",
     "scene, sprite_wad=art, **GAME_RENDER_KW))",
     "scene, sprite_wad=art, **OLD_KW))", TRIP),
    ("aim: the first target in slot order wins", "src/doomfj/combat.py",
     "if best is not None and (tz, order) >= best[0]:",
     "if best is not None and order >= best[0][1]:", ["tests/host/test_gp_aim.py"]),
]
print("# PR #87 review round 2: the mutation each hardened test must catch (source mutated, test run, restored)")
for name, rel, a, b, tests in CASES:
    p = ROOT / rel
    orig = p.read_text(encoding="utf-8")
    assert orig.count(a) == 1, (name, orig.count(a))
    try:
        p.write_text(orig.replace(a, b), encoding="utf-8", newline="\n")
        r = subprocess.run(["python", "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider"],
                           cwd=ROOT, capture_output=True, text=True)
        print("%-46s -> %s" % (name, r.stdout.strip().splitlines()[-1]))
    finally:
        p.write_text(orig, encoding="utf-8", newline="\n")
r = subprocess.run(["python", "-m", "pytest", *TRIP, "tests/host/test_gp_aim.py", "-q", "-p",
                    "no:cacheprovider"], cwd=ROOT, capture_output=True, text=True)
print("%-46s -> %s" % ("unmutated (restored)", r.stdout.strip().splitlines()[-1]))
