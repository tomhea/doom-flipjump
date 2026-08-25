"""Capture the label table from the CURRENT generated program.

Assembles the existing files in build/generated_loop/ (no re-emission) and saves
the label table as a gzipped TSV for m1_setfile.py.

    python scratchpad/_capture_labels.py
"""
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset
from doomfj.build import _RENDERER_INCLUDES, _LINES_INCLUDES, _SIM_INCLUDES, _SRC_FJ
from doomfj.config import Config

t0 = time.perf_counter()
cfg = Config()
gen = ROOT / "build" / "generated_loop"
consts = gen / "fj_consts.fj"
if not consts.exists():
    consts = cfg.emit_fj_consts(consts)

includes = _RENDERER_INCLUDES + _LINES_INCLUDES + _SIM_INCLUDES
prog = sorted(gen.glob("e1m1_0[0-6]_*.fj"))
paths = [consts] + [_SRC_FJ / f for f in includes] + prog + [_SRC_FJ / "m1_reset.fj"]

out = ROOT / "build" / "_label_capture_temp.fjm"
print("assembling %d files (existing generated program)..." % len(paths), flush=True)
for p in paths:
    assert p.exists(), "missing: %s" % p
    print("  %s" % p.name)

labels = selfreset.capture_labels(paths, out, lzma_fast=True)

tsv_path = ROOT / "scratchpad" / "_m1_labels_current.tsv.gz"
print("\nsaving %d labels to %s..." % (len(labels), tsv_path.name), flush=True)
with gzip.open(tsv_path, "wt", encoding="utf-8") as f:
    for name, addr in sorted(labels.items(), key=lambda kv: kv[1]):
        f.write("%s\t%d\n" % (name, addr))

out.unlink(missing_ok=True)
elapsed = time.perf_counter() - t0
print("\ndone in %ds (%d labels)" % (elapsed, len(labels)))
print("\nnext: python scratchpad/m1_setfile.py --labels %s --out src/doomfj/data/m1_restore_set.json.gz" % tsv_path)
