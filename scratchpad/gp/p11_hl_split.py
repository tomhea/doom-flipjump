"""P11 (the CR of PR #133): the hosted-loop tier's TWO-PASS reset part and its pass-1 label table, in TWO processes so
the memory peaks do not add up (the one-process run died at the reset step, ~3 GB free).
    python hl_split.py pass1 LABELS.tsv.gz STEM    -- the real build to pass 1's capture_labels; saves the labels, stops
    python hl_split.py reset LABELS.tsv.gz STEM    -- loads build/STEM.fjm (pass 1's image) and the labels, runs the
                                                     REAL selfreset.emit_reset_part exactly as build.py does
Run at the checkout's root with PYTHONPATH=src."""
import gzip
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "src"))
from doomfj import selfreset  # noqa: E402

mode, out_labels, stem = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
FJM = ROOT / "build" / (stem + ".fjm")
GEN = ROOT / "build" / ("generated_" + stem)
WAD = ROOT / "tests/fixtures/freedoom_e1m1.wad"
t0 = time.perf_counter()

if mode == "pass1":
    from doomfj.build import build_wall_renderer

    class Done(Exception):
        pass

    _real = selfreset.capture_labels

    def spy(*a, **k):
        labels = _real(*a, **k)                     # pass 1 assembled; its image written to build/STEM.fjm
        with gzip.open(out_labels, "wt", encoding="utf-8") as f:
            for n, v in labels.items():
                f.write("%s\t%d\n" % (n, v))
        print("pass 1: %s labels -> %s (%.0f s)" % (format(len(labels), ","), out_labels, time.perf_counter() - t0),
              flush=True)
        raise Done()

    selfreset.capture_labels = spy
    try:
        build_wall_renderer(FJM, wad_path=WAD, mapname="E1M1", tier="hosted-loop")
    except Done:
        pass
    sys.exit(0)

assert mode == "reset", mode
from doomfj.build import DEFAULT_RESTORE_SET, bake_bsp, persist_labels  # noqa: E402
from doomfj.config import Config, RENDER_FLAT_MAX_WORDS  # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore  # noqa: E402
from doomfj.wad import WadFile  # noqa: E402
from doomfj.wall_renderer import tier_cfg, tier_flags  # noqa: E402

labels1 = {}
with gzip.open(out_labels, "rt", encoding="utf-8") as fh:
    for ln in fh:
        n, _, a = ln.rstrip("\n").rpartition("\t")
        labels1[n] = int(a)
t = tier_flags("hosted-loop")
assert not t["standalone"] and t["self_reset"]
cfg = tier_cfg(Config(), "hosted-loop")
r1 = FjmRunner(FJM, flat_max_words=RENDER_FLAT_MAX_WORDS)
core1 = _fjcore.Memory(r1.width, flat_max_words=r1.flat_max_words)
for _s, _n in r1._segments:
    core1.add_segment(_s, _n)
for _st, _v in r1._runs:
    core1.set_words(_st, _v)
nss = len(bake_bsp(WadFile.from_path(WAD), "E1M1").subsectors)
persist = persist_labels(standalone=False, doors=t["doors"], moving_things=t["moving_things"])
part, n_nib, n_byte = selfreset.emit_reset_part(GEN, labels1, core1.get_word, DEFAULT_RESTORE_SET, cfg.VIEW_W, nss,
                                                "E1M1", persist=persist)
print("the two-pass reset part %s: %d nibble cells, %d byte cells (%.0f s)" % (part, n_nib, n_byte,
                                                                             time.perf_counter() - t0))
