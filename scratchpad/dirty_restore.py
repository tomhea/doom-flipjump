"""B4.1 STEP 2 — restore only the DIRTY RANGES, and MEASURE whether that actually beats the memcpy.

STEP 1 (dirty_census.py --exact) bounded the prize: one frame dirties ~4-5k of 68,223,650 words,
the union of four very different frames is 6,685, and coalescing at gap 256 gives 216 ranges over
0.22 MB against a 546 MB blanket `core.reset()`. THAT IS AN UPPER BOUND ON THE PRIZE, NOT THE PRIZE.
It says how many BYTES could move; it says nothing about per-range call overhead, and 216 Python
-> C `set_words` calls are not free. This script measures the wall-clock, which is the number the
fps arithmetic in handoff §4.2 actually needs.

⚠ THE CORRECTNESS RISK IS THE WHOLE POINT, AND IT IS ASYMMETRIC. A blanket reset is right by
construction. A range restore is right only if the ranges cover EVERY word EVERY future frame
dirties -- and the ranges here are derived from a SAMPLE of frames. A word dirtied outside them
survives into the next frame, and the program self-modifies, so a leak does not politely produce a
wrong pixel: it produces a different PROGRAM. So this ships three checks, and the last two are the
ones that matter:

  1. after a range restore, an EXACT walk of all 68M words against the pristine image must report
     0 differ -- per frame, not once;
  2. a SEQUENCE of frames restored only by ranges must reproduce, op count for op count, the same
     sequence restored by the blanket reset. Op counts are deterministic per frame, so a single
     leaked word almost certainly moves one;
  3. the pixels must match too, because a leak could in principle be op-neutral.

⚠ AND THE HONEST LIMIT, STATED UP FRONT: passing all three proves the range set covers the frames
TESTED. It does NOT prove a static bound over every viewpoint, every thing configuration and every
key combination. Shipping this as the real reset path needs either a proof of the bound from the
emitter (which knows every address it writes) or a cheap runtime guard. Until then it is a
MEASUREMENT of the prize, which is what B4.1 step 2 was scoped as.

    python scratchpad/dirty_restore.py <m14.fjm> [--frames 8] [--gap 256] [--validate-walk 2]
"""
import argparse
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
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--gap", type=int, default=256, help="coalesce ranges separated by <= gap words")
ap.add_argument("--validate-walk", type=int, default=2,
                help="how many frames get the FULL 68M-word walk (6s each)")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
# ⚠ 1<<27, NOT the certified 1<<26. MEASURED 2026-08-18: the M14 tier is 68,213,458 words, 1.6%
# OVER 2**26, so at the certified limit it runs in HYBRID storage and `freeze()` -- which requires
# pure flat -- REFUSES. Op counts are identical in both modes (43,115,656 either way), so this
# changes nothing about the op measurements; it does mean the fast reset path this script measures
# is NOT available to the shipped tier as it stands. See the R4 note in the handoff.
ap.add_argument("--flat-max", type=int, default=1 << 27)
ap.add_argument("--learn-extra", type=int, default=0,
                help="add N walkable sweep points to the LEARN set. The question this answers: is "
                     "the dirty set DATA-DEPENDENT (unbounded by sampling, so only an emitter-"
                     "derived bound or engine-side write tracking can be sound), or is it one fixed "
                     "region that 5 frames simply sampled too thinly?")
args = ap.parse_args()

w = WadFile.from_path(str(ROOT / args.wad))
sp = spawn_state(w, "E1M1")
SPX, SPY = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16

# The frames the ranges are LEARNED from, and the frames they are TESTED on, are deliberately
# different sets -- learning and testing on the same frames would prove nothing about coverage.
LEARN = [(SPX, SPY, sp.angle, 0), (664, 291, 0x18000000, 0), (1272, -724, 0x40000000, 0),
         (1869, 479, 0x80000000, 0), (SPX, SPY, sp.angle, 1)]
if args.learn_extra:
    from nb_validate import true_sector, _near_any_line
    verts = [(v.x, v.y) for v in w.vertexes("E1M1")]
    lds, sds = w.linedefs("E1M1"), w.sidedefs("E1M1")
    xs, ys = [v[0] for v in verts], [v[1] for v in verts]
    extra = []
    for x in range(min(xs) + 13, max(xs), 256):
        for y in range(min(ys) + 7, max(ys), 256):
            if _near_any_line(verts, lds, x, y, 24.0):
                continue
            if true_sector(verts, lds, sds, x, y) == -1:
                continue
            extra.append((x, y, (len(extra) % 4) << 30, len(extra) % 3))
    LEARN = LEARN + extra[:args.learn_extra]

TEST = [(2637, 1247, 0x80000000, 0),          # the sweep's WORST frame -- not in LEARN
        (SPX, SPY, sp.angle, 0b0100),         # turning
        (SPX, SPY, sp.angle, 0b0010),         # backing up
        (-435, 223, 0x0, 0), (333, -33, 0x40000000, 0),
        (664, 291, 0x18000000 + 0x5555, 0),   # a fractional angle
        (1869, 479, 0x80000000, 1)]


def build_thing_block():
    rm = ReferenceModel(Config())
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    cmap = bake_bsp(w, "E1M1")
    drawable = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    rt = [t for t, b in zip(drawable, baked) if not b]
    blob = encode_things([(t.x << 16, t.y << 16) for t in rt])
    blob += encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
    blob += encode_visibility([1] * nvis)
    return blob, len(rt)


THINGS, NTH = build_thing_block()


def feed(vx, vy, va, keys):
    return encode_feed(vx << 16, vy << 16, va, keys) + THINGS


def fresh(r):
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for seg_start, seg_len in r._segments:
        core.add_segment(seg_start, seg_len)
    for start, vals in r._runs:
        core.set_words(start, vals)
    return core


def run_one(r, core, blob):
    scr = StreamScreen(stdin=blob, n_things=NTH)
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops, bytes(scr.pixel_indices)


def walk_diff(a, b, segments):
    hits = []
    for seg_start, seg_len in segments:
        for addr in range(seg_start, seg_start + seg_len):
            if a.get_word(addr) != b.get_word(addr):
                hits.append(addr)
    return hits


def coalesce(hits, gap):
    ranges, start, prev = [], hits[0], hits[0]
    for cur in hits[1:]:
        if cur - prev > gap + 1:
            ranges.append((start, prev - start + 1))
            start = cur
        prev = cur
    ranges.append((start, prev - start + 1))
    return ranges


r = FjmRunner(Path(args.fjm), flat_max_words=args.flat_max)
assert r.native, "needs the native engine"
total = sum(n for _s, n in r._segments)
print(f"{Path(args.fjm).name}: {total:,} words (~{total*8/1e6:.0f} MB)", flush=True)

pristine = fresh(r)
work = fresh(r)
assert hasattr(work, "freeze"), "this engine has no freeze(); nothing to compare against"
work.freeze()

# ── LEARN the dirty set ───────────────────────────────────────────────────────
t0 = time.perf_counter()
union = set()
for vx, vy, va, keys in LEARN:
    work.reset()
    ops, _px = run_one(r, work, feed(vx, vy, va, keys))
    union |= set(walk_diff(pristine, work, r._segments))
    print(f"  learn ({vx},{vy},{va:#x},k={keys}): {ops:,} ops, union now {len(union):,}", flush=True)
hits = sorted(union)
ranges = coalesce(hits, args.gap)
covered = sum(n for _s, n in ranges)
print(f"\nLEARNED {len(hits):,} dirty words -> {len(ranges):,} ranges covering {covered:,} words "
      f"({100*covered/total:.4f}% of the image, ~{covered*8/1e6:.2f} MB) in "
      f"{time.perf_counter()-t0:.0f}s", flush=True)

# the pristine contents of those ranges, captured ONCE
vals = [[pristine.get_word(s + i) for i in range(n)] for s, n in ranges]

def restore_ranges(core):
    for (s, _n), v in zip(ranges, vals):
        core.set_words(s, v)

# ── TIME both restores ────────────────────────────────────────────────────────
work.reset()
run_one(r, work, feed(*LEARN[0]))
N = 5
t0 = time.perf_counter()
for _ in range(N):
    work.reset()
blanket = (time.perf_counter() - t0) / N
work.reset()
run_one(r, work, feed(*LEARN[0]))
t0 = time.perf_counter()
for _ in range(N):
    restore_ranges(work)
ranged = (time.perf_counter() - t0) / N
print(f"\nRESTORE COST (mean of {N}):")
print(f"  blanket core.reset()   {blanket*1000:8.2f} ms   ({total*8/1e6:.0f} MB)")
print(f"  {len(ranges):,} ranges          {ranged*1000:8.2f} ms   ({covered*8/1e6:.2f} MB)")
print(f"  => {blanket/ranged:.1f}x faster" if ranged else "  => ranges took no measurable time")

# ── CHECK 2 + 3: a frame sequence restored ONLY by ranges must match the blanket path ──
print(f"\nCORRECTNESS -- {len(TEST)} frames NOT in the learn set, ops and pixels vs the blanket path:",
      flush=True)
ok = True
for i, (vx, vy, va, keys) in enumerate(TEST):
    blob = feed(vx, vy, va, keys)
    work.reset()                       # ground truth
    want_ops, want_px = run_one(r, work, blob)
    restore_ranges(work)               # the candidate restore, from a DIRTY core
    got_ops, got_px = run_one(r, work, blob)
    same = (got_ops == want_ops) and (got_px == want_px)
    ok &= same
    print(f"  ({vx},{vy},{va:#x},k={keys}): blanket {want_ops:,} vs ranged {got_ops:,} "
          f"({got_ops - want_ops:+,})  pixels {'MATCH' if got_px == want_px else '!! DIFFER'}"
          f"  {'ok' if same else '!! LEAK'}", flush=True)

# ── CHECK 1: the strongest one, on a couple of frames -- FULL walk after a range restore ──
print(f"\nEXACT WALK after a range restore ({args.validate_walk} frames x 68M words):", flush=True)
for vx, vy, va, keys in TEST[:args.validate_walk]:
    work.reset()
    run_one(r, work, feed(vx, vy, va, keys))
    restore_ranges(work)
    leak = walk_diff(pristine, work, r._segments)
    ok &= not leak
    print(f"  ({vx},{vy},{va:#x},k={keys}): {len(leak):,} words NOT restored"
          f"  {'ok' if not leak else '!! ' + str(leak[:8])}", flush=True)

print("\nPASS -- the learned ranges covered every tested frame" if ok else
      "\nFAIL -- a frame dirtied outside the learned ranges; the set is NOT statically bounded "
      "by these LEARN frames")
sys.exit(0 if ok else 1)
