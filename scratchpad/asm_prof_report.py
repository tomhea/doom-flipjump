"""Turn `py-spy record -f raw` collapsed stacks into a PER-PHASE self-time report.

⚠ THE TRAP THIS TOOL EXISTS TO AVOID. py-spy's sampling rate is NOT constant across the run, so
converting samples to seconds with one average rate is wrong. MEASURED (2026-08-20, the real
doom-flipjump assemble): the effective rate was 94.9 Hz during parsing, 99.7 Hz during create-binary
(where the GIL is released inside lzma), but only 35.7 Hz during labels-resolve and 26.6 Hz during
the post-assemble teardown -- py-spy under-samples exactly the memory-stalled phases, which is the
opposite of the bias you want. A flat conversion said create-binary was 171.8 s when the assembler's
own wall clock said 106.3 s.

So: phase TOTALS come from the assembler's PrintTimer (real wall clock, passed in with --phase), and
py-spy is used only to split each phase INTERNALLY, where the rate is roughly constant. The
cross-check that this works: lzma.compress lands at 106.3 s inside a 106.3 s create-binary phase.

    python scratchpad/asm_prof_report.py scratchpad/_asm_prof.txt \\
        --phase parsing=202.8 --phase "macro resolve=132.6" \\
        --phase "labels resolve=321.7" --phase "create binary=106.3" --phase outside=120.6
"""
import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("raw", type=Path)
ap.add_argument("--phase", action="append", default=[], metavar="NAME=SECONDS",
                help="the phase's MEASURED wall time, from the assembler's own PrintTimer")
ap.add_argument("--top", type=int, default=10)
args = ap.parse_args()

wall = {}
for spec in args.phase:
    name, _, seconds = spec.rpartition("=")
    wall[name] = float(seconds)

# entry function -> phase. These never nest inside one another.
PHASES = {
    "parse_macro_tree": "parsing",
    "resolve_macros": "macro resolve",
    "labels_resolve": "labels resolve",
    "write_to_file": "create binary",
}
OUTSIDE = "outside"

FRAME = re.compile(r"^(.*?)\s*\((.*)\)$")


def short(frame):
    m = FRAME.match(frame)
    if not m:
        return frame
    where = m.group(2).replace("\\", "/").split("/")[-1]
    return f"{m.group(1)}  ({where})"


per_phase_self = defaultdict(Counter)
per_phase_samples = Counter()

for line in args.raw.read_text(encoding="utf-8", errors="replace").splitlines():
    line = line.strip()
    if not line:
        continue
    stack, _, count = line.rpartition(" ")
    if not count.isdigit() or not stack:
        continue
    n = int(count)
    frames = stack.split(";")
    names = [FRAME.match(f).group(1) if FRAME.match(f) else f for f in frames]
    phase = next((PHASES[nm] for nm in names if nm in PHASES), OUTSIDE)
    per_phase_samples[phase] += n
    per_phase_self[phase][short(frames[-1])] += n

print(f"{args.raw.name}: {sum(per_phase_samples.values()):,} samples\n")
print(f"{'phase':<18}{'WALL s':>9}{'samples':>10}{'eff Hz':>9}   (rate varies -- see the docstring)")
for phase, n in sorted(per_phase_samples.items(), key=lambda kv: -kv[1]):
    w = wall.get(phase)
    rate = f"{n/w:>9.1f}" if w else f"{'?':>9}"
    print(f"{phase:<18}{w if w else 0:>9.1f}{n:>10,}{rate}")

for phase, _ in sorted(per_phase_samples.items(), key=lambda kv: -wall.get(kv[0], 0)):
    w = wall.get(phase)
    if not w:
        continue
    n_total = per_phase_samples[phase]
    print(f"\n=== {phase.upper()} -- {w:,.1f} s, split by self time ===")
    for name, n in per_phase_self[phase].most_common(args.top):
        print(f"  {n / n_total * w:>8.1f} s{n / n_total:>7.1%}  {name}")
