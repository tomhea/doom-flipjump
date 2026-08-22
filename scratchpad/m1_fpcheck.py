"""Does the layout fingerprint actually MATCH the table the BUILD resolves against?

CR round 7: `load_restore_set(..., check_layout=True)` is a hard assert on the shipped build path,
but the shipped fingerprint was generated from `scratchpad/_m1b_labels.tsv.gz` -- captured from the
`self_reset=False` assembly -- and `m1_reemit.py` re-checks it against that same file. Circular. A
new hard assert was shipping unexercised, and if it does not match, the next real build DIES.

This runs the emission and PASS 1 of the real two-pass build (`selfreset.capture_labels` over
exactly the paths `build_wall_renderer(self_reset=True)` uses, `m1_reset.fj` appended last), then
calls the production loader against THAT table with check_layout=True. Cheaper than a full rebuild
because pass 2 is skipped.

    python scratchpad/m1_fpcheck.py
"""
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                          # noqa: E402
from doomfj.build import DEFAULT_RESTORE_SET, build_wall_renderer     # noqa: E402
from doomfj.config import RENDER_FLAT_MAX_WORDS                       # noqa: E402


class Done(Exception):
    pass


RESULT = {}
_real = selfreset.emit_reset_part


def spy(gen, labels, pristine_get_word, restore_set_path, view_w, nss, mapname="e1m1"):
    """Intercept the build AT THE POINT the assert fires, with the build's OWN pass-1 table.

    ⚠ The first version of this script re-listed emit_wall_renderer's arguments by hand -- a twin of
    build.py that drifted immediately (it passed floor_mode="ft1"; the emitter wants "FT1") and died
    before assembling anything. So drive the REAL build_wall_renderer and intercept, rather than
    reconstruct what it does. Then abort: pass 2 costs another ~27 minutes and adds nothing here.
    """
    doc = json.load(gzip.open(restore_set_path, "rt", encoding="utf-8"))
    RESULT["want"] = doc["layout_fingerprint"]
    RESULT["got"] = selfreset.layout_fingerprint(doc, labels)
    RESULT["labels"] = len(labels)
    try:
        RESULT["words"] = len(selfreset.load_restore_set(restore_set_path, labels))
        RESULT["ok"] = True
    except AssertionError as e:
        RESULT["ok"] = False
        RESULT["err"] = str(e)[:300]
    raise Done()


selfreset.emit_reset_part = spy

t0 = time.perf_counter()
print("running build_wall_renderer(self_reset=True) as far as pass 1 ...", flush=True)
try:
    build_wall_renderer(ROOT / "tests/fixtures/freedoom_e1m1.wad", "E1M1",
                        out_fjm=ROOT / "build/fpcheck.fjm",
                        generated_dir=ROOT / "build/generated_fpcheck",
                        flat_max_words=RENDER_FLAT_MAX_WORDS,
                        self_reset=True)
except Done:
    pass
print("pass 1 reached in %.0fs, %s labels" % (time.perf_counter() - t0,
                                              format(RESULT.get("labels", 0), ",")), flush=True)
print("")
print("set's layout_fingerprint : %s  (generated from scratchpad/_m1b_labels.tsv.gz)"
      % RESULT.get("want"))
print("this build's pass-1 table: %s" % RESULT.get("got"))
print("")
if RESULT.get("ok"):
    print("load_restore_set against the REAL pass-1 table: ACCEPTED, %s words"
          % format(RESULT["words"], ","))
else:
    print("load_restore_set REFUSED: %s" % RESULT.get("err"))
print("")
print("m1_fpcheck: %s" % ("PASS -- the build-path assert is exercised and passes"
                          if RESULT.get("ok") else
                          "FAIL -- the shipped set would be REFUSED by a real build"))
sys.exit(0 if RESULT.get("ok") else 1)
