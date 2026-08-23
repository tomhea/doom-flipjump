"""M1c/M1d — assemble the SELF-RESETTING program, and prove no baked address moved.

The reset bakes NUMERIC addresses read from a previous assembly. That is sound only if adding the
reset moves nothing: the new part is APPENDED and the main patch is size-neutral (`stl.loop` ->
`;m1_reset`, one op either way). "Is sound only if" is not a proof, so this checks it:

⚠ THE LOAD-BEARING CONTROL (R9). Every label of the OLD assembly is compared against the new one,
and the build is REFUSED unless every address the reset actually baked is unchanged. A reset that
writes 60,661 cells at addresses that have shifted does not produce a wrong pixel -- it produces a
different program, and the failure would surface as a hang or garbage 25 minutes later.

    python scratchpad/m1_build.py
"""
import argparse
import gzip
import hashlib
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import psutil                                                             # noqa: E402
import flipjump as fj                                                     # noqa: E402
import flipjump.assembler.assembler as _asm                               # noqa: E402

from doomfj.config import RENDER_FLAT_MAX_WORDS                           # noqa: E402
from doomfj.harness import W                                              # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--gen", default="scratchpad/fjmcache/_m1gen")
ap.add_argument("--out", default="scratchpad/fjmcache/_m1loop.fjm")
ap.add_argument("--labels-out", default="scratchpad/_m1_labels_v2.tsv.gz")
ap.add_argument("--labels-old", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--set", default="scratchpad/_m1_final_set.json.gz")
args = ap.parse_args()

_SRC_FJ = ROOT / "src/fj"
INCLUDES = ["fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
            "plane_bands.fj", "stream_render.fj", "sim.fj"]
PARTS = ["e1m1_00_entry.fj", "e1m1_01_tables.fj", "e1m1_02_main.fj", "e1m1_03_segconsts.fj",
         "e1m1_04_walk.fj", "e1m1_05_state.fj", "e1m1_06_banks.fj", "e1m1_07_reset.fj"]

GEN = Path(args.gen)
paths = [GEN / "fj_consts.fj"] + [_SRC_FJ / f for f in INCLUDES] + [GEN / p for p in PARTS]
for p in paths:
    assert p.is_file(), f"missing {p}"
print(f"assembling {len(paths)} files:")
for p in paths:
    print(f"   {p.name:<26}{p.stat().st_size/1e6:>9.2f} MB")

captured = {}


def hook(_path, labels):
    captured["n"] = len(labels)
    with gzip.open(args.labels_out, "wt", encoding="utf-8", newline="\n") as f:
        for k, v in labels.items():
            f.write(f"{k}\t{v}\n")


_asm.save_debugging_labels = hook

peak = [0]
stop = threading.Event()


def sampler():
    p = psutil.Process()
    while not stop.is_set():
        peak[0] = max(peak[0], p.memory_info().rss)
        stop.wait(0.1)


th = threading.Thread(target=sampler, daemon=True)
th.start()
t0w, t0c = time.perf_counter(), time.process_time()
fj.assemble([p.resolve() for p in paths], Path(args.out), memory_width=W,
            print_time=False, lzma_fast=True)
dtw, dtc = time.perf_counter() - t0w, time.process_time() - t0c
stop.set()
th.join(timeout=2)
sha = hashlib.sha256(Path(args.out).read_bytes()).hexdigest()
print(f"\nassembled: wall {dtw:,.1f}s  CPU {dtc:,.1f}s  peakRSS {peak[0]/1e9:.2f} GB")
print(f"  {args.out}  {Path(args.out).stat().st_size:,} bytes")
print(f"  sha256 {sha}")
print(f"  {captured.get('n', 0):,} labels")

# ------------------------------------------------------------------ THE CONTROL: nothing moved
print("\nCONTROL: every baked address must still mean what it meant.", flush=True)
old = {}
with gzip.open(args.labels_old, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            old.setdefault(a, int(v))
new = {}
with gzip.open(args.labels_out, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            new.setdefault(a, int(v))
shared = set(old) & set(new)
moved = [k for k in shared if old[k] != new[k]]
print(f"  {len(shared):,} labels in both; {len(moved):,} moved")
if moved:
    for k in sorted(moved)[:10]:
        print(f"     {k[:70]:<70} {old[k]:,} -> {new[k]:,}")

# The addresses the reset actually baked. ⚠ MEMBERSHIP, not a min..max range: the set spans 62M
# words with enormous holes, so a range test flags labels that are nowhere near it. It did, on the
# first run -- 32 labels moved and all 32 were `hex.exact_xor`'s `end`/`switch`, which are attached
# to `wflip` statements and therefore live at WFLIP-CHAIN SPOTS. Adding thousands of wflips to the
# program changes which recycled `pad` slots those spots land in, so a handful of CODE labels move
# even though every op in the fj-words region keeps its address. None of them is a restored cell.
runs = json.load(gzip.open(args.set, "rt", encoding="utf-8"))["runs"]
S = set()
for a, b in runs:
    S.update(range(a, b))
in_range = [k for k in moved if (old[k] // W) in S or (old[k] // W + 1) in S]
print(f"  of those, actually INSIDE the {len(S):,}-word restored set: {len(in_range):,}")
ok = not in_range
print(f"  {'ok -- every baked address is unchanged' if ok else '!! REFUSED: a baked address moved'}")
if not ok:
    for k in sorted(in_range)[:10]:
        print(f"     {k[:70]:<70} {old[k]:,} -> {new[k]:,}")
    sys.exit(1)

from flipjump.interpreter.io_devices.FixedIO import FixedIO               # noqa: E402
term = fj.run(Path(args.out), io_device=FixedIO(b"q\n"), print_time=False,
              print_termination=False, flat_max_words=RENDER_FLAT_MAX_WORDS)
print(f"\nR4 gate: storage_mode={term.storage_mode}")
assert str(term.storage_mode) == "flat", f"R4: storage_mode {term.storage_mode!r} != flat"
print("  ok -- still flat")
print(f"\nBUILD OK. Gate it with scratchpad/m1_gate.py")
