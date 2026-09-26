"""PR #88 review round 4: the review's escapes, planted in the REAL m5_gate.py, must fail the scan; and
the tripwire's three new mechanisms (every other store, parameters, the alias closure), each removed,
must fail the fixtures.

usage: python scratchpad/gp/evidence/r4_review_mutations.py  (prints the lines of r4_review_mutations.log;
every file it mutates is restored)"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]          # the repo root
TRIP = ["tests/host/test_oracle_calls_in_step.py"]
TRIP_FILE = "tests/host/test_oracle_calls_in_step.py"
M5 = "    render_kw = dict(GAME_RENDER_KW, sprite_wad=art)"
NO_SKY = ('dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True, near_steps=True, '
          'stack_steps=True, things=True, sprite_wad=art, degrade=True, bbox_cull=True)')
CASES = [
    ("m5_gate: tuple unpacking rebinds it without sky", "scratchpad/m5_gate.py", M5,
     M5 + "\n    render_kw, _ = %s, 0" % NO_SKY),
    ("m5_gate: a for loop rebinds it without sky", "scratchpad/m5_gate.py", M5,
     M5 + "\n    for render_kw in (%s,):\n        pass" % NO_SKY),
    ("m5_gate: a comprehension target shadows it", "scratchpad/m5_gate.py", M5,
     M5 + "\n    _v = [rm.render_wall_frame(state, scene, **render_kw) for render_kw in VARIANTS]"),
    ("m5_gate: a walrus rebinds it without sky", "scratchpad/m5_gate.py", M5,
     M5 + "\n    (render_kw := %s)" % NO_SKY),
    ("m5_gate: del through a bare alias", "scratchpad/m5_gate.py", M5,
     M5 + "\n    _kw2 = render_kw\n    del _kw2[\"sky\"]"),
    ("tripwire without the rebound set", TRIP_FILE,
     "    out = rebound | mutated\n", "    out = mutated\n"),
    ("tripwire without parameters as bindings", TRIP_FILE,
     "        elif isinstance(n, ast.arg):\n            rebound.add(n.arg)\n",
     "        elif isinstance(n, ast.arg):\n            pass\n"),
    ("tripwire without the alias closure", TRIP_FILE,
     "            if group & mutated and not group <= mutated:\n",
     "            if False:\n"),
]
print("# PR #88 review round 4: each mutation must FAIL a tripwire test (source mutated, test run, restored)")
for name, rel, a, b in CASES:
    p = ROOT / rel
    orig = p.read_bytes()
    text = orig.decode("utf-8")
    assert text.count(a) == 1, (name, text.count(a))
    try:
        p.write_bytes(text.replace(a, b).encode("utf-8"))
        r = subprocess.run(["python", "-m", "pytest", *TRIP, "-q", "-p", "no:cacheprovider"],
                           cwd=ROOT, capture_output=True, text=True)
        failed = [l.split("::")[-1].split(" ")[0] for l in r.stdout.splitlines() if l.startswith("FAILED")]
        print("%-50s -> %s [%s]" % (name, r.stdout.strip().splitlines()[-1], ", ".join(failed)))
    finally:
        p.write_bytes(orig)
    assert p.read_bytes() == orig, "restore failed: %s" % rel
r = subprocess.run(["python", "-m", "pytest", *TRIP, "-q", "-p", "no:cacheprovider"], cwd=ROOT,
                   capture_output=True, text=True)
print("%-50s -> %s" % ("unmutated (restored, byte-identical)", r.stdout.strip().splitlines()[-1]))
