"""Dump the pass-1 label table of the CURRENT program, from the REAL build path.

Why not m1b_labels.py: the label names are `f<file>:l<line>:macro(n)---local`, so they depend on the
exact FILE LIST and its ORDER. build_wall_renderer(self_reset=True) appends src/fj/m1_reset.fj LAST,
after the emitted parts; assembling any other list renumbers every `f<N>` and the names stop
matching. So drive the real builder and intercept at emit_reset_part, exactly as m1_fpcheck.py does,
then abort before pass 2.

    python scratchpad/ca_labels.py --out scratchpad/_ca_labels.tsv.gz
"""
import argparse
import gzip
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                   # noqa: E402
from doomfj.build import build_wall_renderer                   # noqa: E402
from doomfj.config import RENDER_FLAT_MAX_WORDS                # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", default="scratchpad/_ca_labels.tsv.gz")
# M5: the standalone tier is a DIFFERENT program (a keyboard prologue instead of the wire, baked
# thing bindings, no magic byte), so it has its own label table and its own restore set.
ap.add_argument("--standalone", action="store_true")
# M2-R4: a doors build declares per-door state, and those labels have to be in the table the
# restore set is re-keyed against -- otherwise the set is built for a program that is not the
# one being shipped.
ap.add_argument("--doors", action="store_true")
ap.add_argument("--menu", action="store_true", help="M3: emit the menu frame producer too")
args = ap.parse_args()


class Done(Exception):
    pass


RESULT = {}
_real_emit = selfreset.emit_reset_part


def spy(gen, labels, pristine_get_word, restore_set_path, view_w, nss, mapname="e1m1",
        persist=()):
    RESULT["labels"] = dict(labels)
    RESULT["code_start"] = pristine_get_word(1)
    raise Done()


selfreset.emit_reset_part = spy
t0 = time.perf_counter()
print("driving build_wall_renderer(self_reset=True) to pass 1 ...", flush=True)
try:
    # this captures the labels of a REAL build, so it must drive the same tier the artifact
    # ships as -- `--standalone` is the game, anything else is the hosted loop
    build_wall_renderer(
        ROOT / ("build/ca_labels%s.fjm" % ("_std" if args.standalone else "")),
        wad_path=ROOT / "tests/fixtures/freedoom_e1m1.wad", mapname="E1M1",
        tier="game" if args.standalone else "loop")
except Done:
    pass
labels = RESULT.get("labels")
assert labels, "the build never reached emit_reset_part -- no labels captured"
out = Path(args.out)
with gzip.open(out, "wt", encoding="utf-8") as f:
    for k, v in labels.items():
        f.write("%s\t%d\n" % (k, v))
print("pass 1 in %.0fs: %s labels -> %s (%.1f MB)"
      % (time.perf_counter() - t0, format(len(labels), ","), out, out.stat().st_size / 1e6))
print("code_start word: %d" % (RESULT["code_start"] // 32))
