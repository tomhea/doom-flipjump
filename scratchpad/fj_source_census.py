"""WHAT IS THE 129 MB MADE OF? A streaming census of the emitted fj source.

Assemble time is now dominated by how much source there is: parsing is O(lines) and macro-resolve is
O(macro calls). This counts both, per file, and -- the point of the exercise -- measures the RUNS of
consecutive zero-word data ops (`;0 * dw`), because a run of N of those is N parsed lines, N Expr
pairs, N ops and 2N emitted words that all describe the same thing: N words of zero.

⚠ IT ONLY MEASURES. It does not claim the runs are replaceable; whether `reserve` (which emits a
segment whose declared length exceeds its data, so the loader zero-fills) can stand in for them is a
question about the RUNTIME, not about this count. See the note printed at the end.

Streams line by line -- never loads a 114 MB file into memory, because the assembler may be running.

    python scratchpad/fj_source_census.py [dir-with-the-emitted-parts]
"""
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARTS = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\tomhe\AppData\Local\Temp\tmp97fndv92")

SRC = [ROOT / "src/fj" / f for f in ("fixed_point.fj", "present.fj", "projection.fj",
                                     "frame_render.fj", "plane_render.fj", "plane_bands.fj",
                                     "stream_render.fj", "sim.fj")]
files = [PARTS / "fj_consts.fj"] + SRC + sorted(PARTS.glob("e1m1_0*.fj"))

ZERO_OP = re.compile(r"^\s*;\s*0\s*\*\s*dw\s*$")
RAW_OP = re.compile(r"^\s*[^;\s][^;]*;|^\s*;")          # `a;b` or `;b`
LABEL = re.compile(r"^\s*[A-Za-z_][A-Za-z_0-9.]*\s*:\s*$")
MACRO_CALL = re.compile(r"^\s*([A-Za-z_][A-Za-z_0-9.]*)\s")

totals = Counter()
runs = Counter()          # run length -> how many runs of that length
per_file = {}

for path in files:
    if not path.exists():
        print(f"  !! missing {path}")
        continue
    counts = Counter()
    run = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            counts["lines"] += 1
            if ZERO_OP.match(line):
                counts["zero_op"] += 1
                run += 1
                continue
            if run:
                runs[run] += 1
                counts["zero_runs"] += 1
                run = 0
            stripped = line.strip()
            if not stripped:
                counts["blank"] += 1
            elif stripped.startswith("//"):
                counts["comment"] += 1
            elif LABEL.match(line):
                counts["label"] += 1
            elif RAW_OP.match(line):
                counts["raw_op"] += 1
            elif MACRO_CALL.match(line):
                counts["macro_call"] += 1
            else:
                counts["other"] += 1
    if run:
        runs[run] += 1
        counts["zero_runs"] += 1
    counts["bytes"] = path.stat().st_size
    per_file[path.name] = counts
    totals.update(counts)

print(f"{'file':<26}{'MB':>7}{'lines':>12}{'zero-op':>12}{'raw op':>11}{'macro':>10}{'label':>10}")
for name, c in per_file.items():
    print(f"{name:<26}{c['bytes']/1e6:>7.1f}{c['lines']:>12,}{c['zero_op']:>12,}"
          f"{c['raw_op']:>11,}{c['macro_call']:>10,}{c['label']:>10,}")
print(f"{'TOTAL':<26}{totals['bytes']/1e6:>7.1f}{totals['lines']:>12,}{totals['zero_op']:>12,}"
      f"{totals['raw_op']:>11,}{totals['macro_call']:>10,}{totals['label']:>10,}")

zero, lines = totals["zero_op"], totals["lines"]
print(f"\nZERO-WORD DATA OPS: {zero:,} lines = {zero/lines:.1%} of every line in the program")
print(f"  in {totals['zero_runs']:,} consecutive runs")
if runs:
    ordered = sorted(runs.items(), reverse=True)
    print(f"  longest run {ordered[0][0]:,} ops; "
          f"{sum(n for length, n in runs.items() if length >= 64):,} runs are >= 64 ops long, "
          f"covering {sum(length * n for length, n in runs.items() if length >= 64):,} ops")
    print("  run-length histogram (top 10 by total ops):")
    for length, n in sorted(runs.items(), key=lambda kv: -kv[0] * kv[1])[:10]:
        print(f"     {length:>8,} ops x {n:>8,} runs = {length*n:>12,} ops")

print("\n⚠ WHAT THIS DOES NOT SAY: that these are replaceable. `reserve` would express them in O(1)")
print("  source and leave them out of the .fjm entirely (the loader zero-fills the declared span),")
print("  but that changes the SEGMENT LAYOUT, and this repo's runner (doomfj.fastrun + _fjcore)")
print("  builds its memory from the segment list. That has to be checked against the runner, and")
print("  the result has to pass deg_gate byte-exact -- it is an emission change, not a free one.")
