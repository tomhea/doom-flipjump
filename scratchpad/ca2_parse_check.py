"""Assemble every src/fj file together -- the fast proof that a comment/header pass broke nothing.

A header edit cannot change behaviour, but it CAN break parsing (an unterminated construct, a
stray brace inside a comment). The full fj suite proves that too, in ~3 hours; this proves the
parse-and-macro-resolve half in ~1 minute, which is the half a comment pass can actually break.

It is NOT a substitute for the suite -- it does not run anything or compare a pixel. It is the
cheap pre-gate; CLAUDE.md rule 3 applies: trust the gate, distrust the pre-gate.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import flipjump as fj                                        # noqa: E402
from doomfj.config import Config                             # noqa: E402
from doomfj.harness import W                                 # noqa: E402

NL = chr(10)
cfg = Config()
tmp = Path(tempfile.mkdtemp(prefix="parsecheck_"))
consts = cfg.emit_fj_consts(tmp / "fj_consts.fj")

# the shipped include order (build.py: _RENDERER_INCLUDES + _LINES_INCLUDES + _SIM_INCLUDES)
ORDER = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
         "plane_bands.fj", "stream_render.fj", "sim.fj"]
missing = [f for f in ORDER if not (ROOT / "src/fj" / f).exists()]
assert not missing, "include list names a file that does not exist: %s" % missing

main = tmp / "main.fj"
main.write_text("stl.startup_and_init_all" + NL + "stl.loop" + NL, encoding="utf-8")
files = [consts] + [ROOT / "src/fj" / f for f in ORDER] + [main]

print("assembling %d files together (shipped include order):" % len(files))
for f in files:
    print("   %s" % f.name)
out = tmp / "p.fjm"
fj.assemble([f.resolve() for f in files], out, memory_width=W, print_time=False)
print("")
print("PARSE + MACRO-RESOLVE OK  ->  %s (%s bytes)" % (out.name, format(out.stat().st_size, ",")))
print("")
print("(this proves the files parse and their macros resolve together -- it does NOT prove")
print(" behaviour. The gate for that is tests/fj + deg_gate.)")
