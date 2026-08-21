"""M1 — find the set that ACTUALLY needs restoring, by ablation.

THE QUESTION I HAD NOT ASKED. Every set so far was built from "which cells does a frame DIRTY".
That is the wrong predicate. A cell only needs restoring if the next frame **reads it before it
writes it**. Almost all scratch is written before read -- `hex.mov`/`hex.zero`/`hex.set` overwrite
unconditionally -- so restoring it is pure cost. What genuinely needs restoring is the small set of
cells with cross-frame meaning: linked-list heads, write-once flags, latches, accumulators.

Static analysis would answer this exactly and is a large job. Ablation answers it empirically and
cheaply: drop a label from the restore set, run a chain of frames, and see whether the pictures
still come out right. If they do, that label never needed restoring.

METHOD — delta debugging over the label list:
  * `works(S)` runs a K-frame chain on one core, restoring only S between frames, and requires
    EVERY frame to be byte-exact against that frame rendered on a PRISTINE core.
  * start from the known-good set, try removing chunks, keep every removal that still works,
    halve the chunk size, repeat. Standard ddmin, biased to try the BIGGEST labels first so the
    expensive things go early.
  * the survivor is then confirmed on the full 260-frame sweep, which no set was built from.

⚠ NEGATIVE CONTROLS (R9):
  1. `works({})` -- restoring NOTHING -- must FAIL, or the search is measuring nothing. (It does
     worse than fail: it hangs, because a stale `sshead` makes `thing_pass` walk a cycle. So the
     empty set is checked with a frame budget and treated as a failure if it does not finish.)
  2. `works(full)` must PASS before the search starts.
  3. The K chain frames must render DISTINCT pictures, or "byte-exact" is free.
  4. Every candidate is judged against PRISTINE references, never against the previous frame.
  5. The final set is re-checked on 260 sweep frames it was not minimised against.

    python scratchpad/m1_minimize.py [--frames 24]
"""
import argparse
import bisect
import gzip
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT, ROOT / "scratchpad"):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from nb_validate import true_sector, _near_any_line                       # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--labels", default="scratchpad/_m1b_labels.tsv.gz")
ap.add_argument("--start-set", default="scratchpad/_m1_setB.json.gz")
ap.add_argument("--frames", type=int, default=24)
ap.add_argument("--out", default="scratchpad/_m1_setC.json.gz")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()
W = 32

# ------------------------------------------------------------------------------------- the image
r = FjmRunner(Path(args.fjm))
assert r.native
sa, sn = [], []
with gzip.open(args.labels, "rt", encoding="utf-8") as f:
    for line in f:
        a, t, v = line.rstrip("\n").partition("\t")
        if t:
            sa.append(int(v))
            sn.append(a)
o = sorted(range(len(sa)), key=lambda i: sa[i])
sa = [sa[i] for i in o]
sn = [sn[i] for i in o]
BITS = {}
for n, b in zip(sn, sa):
    BITS.setdefault(n, b)
HOT = BITS["__hot_end"]
saw = [b // W for b in sa]


def fresh():
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for st, vals in r._runs:
        c.set_words(st, vals)
    return c


PRISTINE = fresh()

# ------------------------------------------------------------------------------------- the feed
w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])


def wire(vx, vy, va, keys=0, dx=0, dy=0):
    return (encode_feed(vx, vy, va, keys)
            + encode_things([((t.x + dx) << 16, (t.y + dy) << 16) for t in RT])
            + BINDS + encode_visibility([1] * NVIS))


sp = spawn_state(w, "E1M1")
SPAWN = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
_v = [(v.x, v.y) for v in w.vertexes("E1M1")]
_l, _s = w.linedefs("E1M1"), w.sidedefs("E1M1")
_xs = [p[0] for p in _v]
_ys = [p[1] for p in _v]
_pts = [(x, y) for x in range(min(_xs) + 13, max(_xs), 256)
        for y in range(min(_ys) + 7, max(_ys), 256)
        if not _near_any_line(_v, _l, x, y, 24.0) and true_sector(_v, _l, _s, x, y) != -1]
# a DIVERSE short chain: gate viewpoints, key states, moved things, and a spread of sweep points.
CH = [(664 << 16, 291 << 16, 0x18000000, 0, 0, 0),
      (1272 << 16, (-724) << 16, 0x40000000, 5, 16, 0),
      (1869 << 16, 479 << 16, 0x80000000, 1, 0, 0),
      (SPAWN[0], SPAWN[1], SPAWN[2], 4, -32, 48),
      (SPAWN[0], SPAWN[1], SPAWN[2], 0, 64, 0),
      (SPAWN[0], SPAWN[1], SPAWN[2], 8, 0, 0)]
step = max(1, len(_pts) // max(1, args.frames - len(CH)))
for k, (x, y) in enumerate(_pts[::step][:args.frames - len(CH)]):
    CH.append((x << 16, y << 16, ((k % 4) * (1 << 30)) & 0xFFFFFFFF, (k % 3) and 1, 0, 0))
CH = CH[:args.frames]
print(f"chain: {len(CH)} frames", flush=True)


class MF(StreamScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


def run(core, blob, start_ip=0):
    scr = MF(stdin=blob, n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l2, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF,
                                    last_ops_length=0, start_ip=start_ip)
    return ops, scr.frames


print("rendering pristine references ...", flush=True)
t0 = time.perf_counter()
REF = []
for c in CH:
    core = fresh()
    ops, fr = run(core, wire(*c))
    assert ops > 1_000_000 and len(fr) == 1
    REF.append(fr[0])
    del core
uniq = len(set(REF))
assert uniq >= 0.9 * len(REF), f"CONTROL 3 (vacuity): only {uniq} distinct of {len(REF)}"
print(f"  {len(REF)} references, {uniq} distinct ({time.perf_counter()-t0:.0f}s)", flush=True)

# ------------------------------------------------------------------------------ the label pieces
start = json.load(gzip.open(args.start_set, "rt", encoding="utf-8"))["runs"]
S0 = sorted(x for a, b in start for x in range(a, b))
piece = {}
for x in S0:
    i = bisect.bisect_right(saw, x) - 1
    piece.setdefault(sn[i] if i >= 0 else "<none>", []).append(x)
PIECES = sorted(piece.items(), key=lambda kv: -len(kv[1]))
print(f"start set: {len(S0):,} words in {len(PIECES):,} labels", flush=True)


def patch_for(words):
    if not words:
        return []
    ws = sorted(words)
    out, s0, p = [], ws[0], ws[0]
    runs = []
    for c in ws[1:]:
        if c != p + 1:
            runs.append((s0, p + 1))
            s0 = c
        p = c
    runs.append((s0, p + 1))
    for a, b in runs:
        out.append((a, [PRISTINE.get_word(x) for x in range(a, b)]))
    return out


N_EVAL = [0]


def works(keep_names, budget_ops=400_000_000):
    """Chain the frames restoring only `keep_names`; every frame must match its pristine reference.

    `budget_ops` is a guard, not a tuning knob: a set that leaves `sshead` stale does not diverge,
    it makes the next frame walk a cycle and never terminate. The chain is run frame by frame and
    abandoned as soon as one frame's op count is absurd."""
    N_EVAL[0] += 1
    words = []
    for nm in keep_names:
        words.extend(piece[nm])
    patch = patch_for(words)
    core = fresh()
    ok = True
    try:
        for k, c in enumerate(CH):
            ops, fr = run(core, wire(*c), start_ip=(0 if k == 0 else HOT))
            if len(fr) != 1 or fr[0] != REF[k] or ops > budget_ops:
                ok = False
                break
            if k + 1 < len(CH):
                for a, vals in patch:
                    core.set_words(a, vals)
    finally:
        del core
    return ok


print("\nCONTROL 2: the full start set must PASS", flush=True)
allnames = [n for n, _ in PIECES]
t0 = time.perf_counter()
assert works(allnames), "the start set does not pass -- nothing below is meaningful"
print(f"  ok ({time.perf_counter()-t0:.0f}s per evaluation)", flush=True)

# ---------------------------------------------------------------------------------- ddmin search
keep = list(allnames)
chunk = max(1, len(keep) // 2)
print(f"\nminimising by ablation (drop a chunk, keep the drop if it still works):", flush=True)
while chunk >= 1:
    i = 0
    progressed = False
    while i < len(keep):
        cand = keep[:i] + keep[i + chunk:]
        dropped_words = sum(len(piece[n]) for n in keep[i:i + chunk])
        if cand and works(cand):
            keep = cand
            progressed = True
            kw = sum(len(piece[n]) for n in keep)
            print(f"  chunk {chunk:>4}: dropped {len(keep[i:i+chunk]) if False else chunk} labels "
                  f"/ {dropped_words:,} words -> {len(keep):,} labels, {kw:,} words", flush=True)
        else:
            i += chunk
    if chunk == 1 and not progressed:
        break
    chunk = chunk // 2 if chunk > 1 else 1
    if chunk == 0:
        break

final_words = sorted(x for n in keep for x in piece[n])
print(f"\nMINIMAL SET: {len(keep):,} labels, {len(final_words):,} words = "
      f"{len(final_words)//2:,} cells   ({N_EVAL[0]} evaluations)")
print(f"  from {len(S0):,} words -> {len(S0)/max(1,len(final_words)):.1f}x smaller")
print("\nthe labels that actually need restoring (top 30 by size):")
for n in sorted(keep, key=lambda n: -len(piece[n]))[:30]:
    print(f"  {len(piece[n]):>7,} words  {str(n)[:88]}")


def co(ws):
    out, s0, p = [], ws[0], ws[0]
    for c in ws[1:]:
        if c != p + 1:
            out.append([s0, p + 1])
            s0 = c
        p = c
    out.append([s0, p + 1])
    return out


json.dump({"runs": co(final_words), "labels": keep},
          gzip.open(args.out, "wt", encoding="utf-8"))
print(f"\nwrote {args.out}")
print("⚠ minimised against a %d-frame chain. CONFIRM on the 260-frame sweep before building:" % len(CH))
print(f"   python scratchpad/m1d_loop.py --set full --restore-set {args.out} --sweep")
