"""B4.1 STEP 1 — how much of the image does ONE frame actually dirty?

WHY THIS IS THE HIGHEST-LEVERAGE MEASUREMENT IN THE PERF CAMPAIGN (docs/handoff-playable.md §4.2):
the fj program self-modifies, so the host restores the whole image before every run -- MEASURED
52.5-61.5 ms for a 68M-word image, a ~545MB memcpy that is memory-bandwidth-bound and INDEPENDENT
of ops/frame. At 300M fj/s that caps the game at ~19 fps no matter how cheap the frame gets, and
below ~15M ops the reset is more than half the frame. If the dirty set is small, restoring only it
turns that fixed cost into a small one and every op saved starts converting into fps again.

⚠ IT SAMPLES. `_fjcore.Memory` exposes `get_word` but no bulk read, so diffing all 68M words from
Python is impractical. This draws a uniform random sample of word addresses and compares a core
that has run one frame against a fresh one, giving the dirty FRACTION with a binomial confidence
interval. That is exactly the feasibility question ("is it small?"); it deliberately does NOT
answer "what is the dirty EXTENT", which decides whether a range-restore or a per-cell journal is
the right mechanism -- do that second, once this says the idea is alive.

⚠ NEGATIVE CONTROL (R9): the same comparison is run core-vs-ITSELF, which must report 0 dirty. A
sampler that reports 0% because it is comparing the wrong thing is the failure mode here.

⚠ THE FEED HAS TO MATCH THE BINARY'S WIRE. A decimal `--feed` handed to an M14-tier build
(`state_wire="bin"`) is parsed as raw state bytes, halts after ~200 ops, and the dirty fraction
that comes back is a fraction of NOTHING. `--m14` builds the real binary wire instead --
`encode_feed` + the runtime thing block + bindings + visibility, exactly as `m14_sweep.py` does --
and the `ops < 1000` tripwire at the bottom is the backstop for getting this wrong anyway.

    python scratchpad/dirty_census.py <cached.fjm> [--sample 200000] [--feed "x\\ny\\na\\n"]
    python scratchpad/dirty_census.py <m14.fjm> --m14 [--things]
"""
import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("fjm")
ap.add_argument("--sample", type=int, default=200_000)
ap.add_argument("--feed", default="-435\n223\n0\n")
ap.add_argument("--seed", type=int, default=20260817)
ap.add_argument("--m14", action="store_true",
                help="the binary state wire (state_wire='bin') instead of three decimals")
ap.add_argument("--things", action="store_true",
                help="with --m14: the build also reads a runtime thing block (moving_things)")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--exact", action="store_true",
                help="walk EVERY word instead of sampling: exact count AND the extent")
ap.add_argument("--gatevps", action="store_true",
                help="with --exact: census the FOUR gate viewpoints and report the UNION. One "
                     "frame's dirty set proves nothing about a restore mechanism -- a range "
                     "restore has to cover every frame, so the union is the number that matters.")
args = ap.parse_args()


def m14_feed(state=None):
    """The M14 binary wire at the SPAWN state, keys=0, warm bindings -- the same composite
    `m14_sweep.py` sends, so the frame this censuses is the frame that sweep measured. Returns
    (bytes, n_things) because StreamScreen must be told how many bindings to decode back."""
    from doomfj.config import Config
    from doomfj.fixedpoint import _signed
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel,
                                        spawn_state)
    from doomfj.things import baked_thing_mask, vanishable_slots
    from doomfj.wad import WadFile
    from doomfj.wireformat import (encode_bindings, encode_feed, encode_things,
                                   encode_visibility)

    w = WadFile.from_path(str(ROOT / args.wad))
    if state is None:
        sp = spawn_state(w, "E1M1")
        state = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
    blob = encode_feed(state[0], state[1], state[2], 0)
    if not args.things:
        return blob, 0
    rm = ReferenceModel(Config())
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    cmap = bake_bsp(w, "E1M1")
    drawable = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
    rt = [t for t, b in zip(drawable, baked) if not b]
    blob += encode_things([(t.x << 16, t.y << 16) for t in rt])
    blob += encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
    blob += encode_visibility([1] * nvis)
    return blob, len(rt)


def fresh(r):
    """A core holding the program's PRISTINE image."""
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for seg_start, seg_len in r._segments:
        core.add_segment(seg_start, seg_len)
    for start, vals in r._runs:
        core.set_words(start, vals)
    return core


def run_one(r, core, feed, n_things=0):
    scr = StreamScreen(stdin=feed, n_things=n_things)
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops


def walk_diff(a_core, b_core, segments, label):
    """EXACT: every word of every segment, a vs b. Returns the sorted list of differing addresses.

    ⚠ This is the same comparison the sampler does, just without the sampling -- which is what
    makes it usable as its OWN negative control: run it pristine-vs-pristine first and it must
    return []. A walker with an off-by-one in the segment arithmetic would report a huge dirty set
    and look like a THRILLING result, so the control runs before the measurement, not after.
    """
    t0 = time.perf_counter()
    hits, done = [], 0
    for seg_start, seg_len in segments:
        for a in range(seg_start, seg_start + seg_len):
            if a_core.get_word(a) != b_core.get_word(a):
                hits.append(a)
        done += seg_len
        print(f"  [{label}] {done:,} words walked, {len(hits):,} differ "
              f"({time.perf_counter()-t0:.0f}s)", flush=True)
    return hits


def extent_report(hits, total_words):
    """Step 2 of B4.1: is the dirty set CONTIGUOUS enough that ranges beat a blanket memcpy?"""
    if not hits:
        return
    print(f"\nEXTENT: {len(hits):,} dirty words, first {hits[0]:,} last {hits[-1]:,} "
          f"(span {hits[-1]-hits[0]+1:,} words of {total_words:,})")
    for gap in (0, 16, 256, 4096, 65536):
        runs, n = 1, 1
        for prev, cur in zip(hits, hits[1:]):
            if cur - prev > gap + 1:
                runs += 1
            n += 1
        covered = 0
        start = hits[0]
        prev = hits[0]
        for cur in hits[1:]:
            if cur - prev > gap + 1:
                covered += prev - start + 1
                start = cur
            prev = cur
        covered += prev - start + 1
        print(f"  coalesce gap {gap:>6,}: {runs:>6,} ranges covering {covered:,} words "
              f"({100*covered/total_words:.4f}% of the image, "
              f"~{covered*8/1e6:.2f} MB vs {total_words*8/1e6:.0f} MB)")


r = FjmRunner(Path(args.fjm))
assert r.native, "needs the native engine"
total_words = sum(seg_len for _s, seg_len in r._segments)
print(f"{Path(args.fjm).name}: segments={len(r._segments)}  words={total_words:,}"
      f"  (~{total_words*8/1e6:.0f} MB)", flush=True)

if args.exact:
    FEED, NTH = m14_feed() if args.m14 else (args.feed.encode(), 0)
    print(f"feed: {'BINARY wire' if args.m14 else 'three decimals'}, {len(FEED):,} bytes, "
          f"{NTH} runtime things", flush=True)
    a_core, b_core = fresh(r), fresh(r)
    ctl = walk_diff(a_core, b_core, r._segments, "control")
    print(f"negative control (two pristine images, EXACT): {len(ctl)} differ -- "
          f"{'ok' if not ctl else '!! THE WALKER IS BROKEN'}", flush=True)
    if ctl:
        sys.exit(1)
    # the states to census. Default: the spawn frame only. --gatevps: deg_gate's four.
    STATES = [None]
    if args.gatevps:
        STATES = [(664 << 16, 291 << 16, 0x18000000), (1272 << 16, (-724) << 16, 0x40000000),
                  (1869 << 16, 479 << 16, 0x80000000), None]

    union = set()
    for st in STATES:
        feed, nth = (m14_feed(st) if args.m14 else (args.feed.encode(), 0))
        core = b_core if st is STATES[0] else fresh(r)
        ops = run_one(r, core, feed, nth)
        hits = walk_diff(a_core, core, r._segments, "measure")
        union |= set(hits)
        name = "spawn" if st is None else f"({st[0] >> 16},{st[1] >> 16},{st[2]:#x})"
        print(f"  {name}: {ops:,} ops -> {len(hits):,} dirty words", flush=True)
        del core
    hits = sorted(union)
    print(f"\nDIRTY (EXACT{', UNION of %d frames' % len(STATES) if len(STATES) > 1 else ''}): "
          f"{len(hits):,} of {total_words:,} words = "
          f"{100*len(hits)/total_words:.6f}%  (~{len(hits)*8/1e6:.3f} MB of "
          f"{total_words*8/1e6:.0f} MB)")
    extent_report(hits, total_words)
    if ops < 1000:
        print("\n!! ops is tiny -- the feed did not drive a real frame (wrong wire?).")
    sys.exit(0)

addrs = []
rnd = random.Random(args.seed)
for _ in range(args.sample):
    # uniform over WORDS, weighted by segment length so every word is equally likely
    k = rnd.randrange(total_words)
    for seg_start, seg_len in r._segments:
        if k < seg_len:
            addrs.append(seg_start + k)
            break
        k -= seg_len

t0 = time.perf_counter()
pristine = fresh(r)
base = [pristine.get_word(a) for a in addrs]
print(f"sampled {len(addrs):,} words from the pristine image in {time.perf_counter()-t0:.1f}s",
      flush=True)

# NEGATIVE CONTROL first: the pristine core against itself must be 0% dirty.
ctl = sum(1 for a, b in zip(addrs, base) if pristine.get_word(a) != b)
print(f"negative control (pristine vs itself): {ctl} differ -- "
      f"{'ok' if ctl == 0 else '!! THE SAMPLER IS BROKEN'}", flush=True)
if ctl:
    sys.exit(1)

FEED, NTH = m14_feed() if args.m14 else (args.feed.encode(), 0)
print(f"feed: {'BINARY wire' if args.m14 else 'three decimals'}, {len(FEED):,} bytes, "
      f"{NTH} runtime things", flush=True)

dirty_core = fresh(r)
ops = run_one(r, dirty_core, FEED, NTH)
after = [dirty_core.get_word(a) for a in addrs]
n_dirty = sum(1 for x, y in zip(base, after) if x != y)

p = n_dirty / len(addrs)
se = (p * (1 - p) / len(addrs)) ** 0.5
lo, hi = max(0.0, p - 1.96 * se), p + 1.96 * se
print(f"\nran one frame: {ops:,} ops")
print(f"DIRTY: {n_dirty:,} of {len(addrs):,} sampled = {100*p:.4f}%  "
      f"(95% CI {100*lo:.4f}-{100*hi:.4f}%)")
print(f"  => ~{p*total_words:,.0f} words of {total_words:,} "
      f"(~{p*total_words*8/1e6:.1f} MB of {total_words*8/1e6:.0f} MB)")
print(f"  => a dirty-only restore would move ~{100*p:.2f}% of the bytes; the blanket memcpy "
       "measured 52.5-61.5 ms, so the floor could fall by roughly that ratio IF the dirty set is\n"
       "     contiguous enough to copy in ranges. Measure the EXTENT next -- this bounds the prize,\n"
       "     it does not deliver it.")
if ops < 1000:
    print("\n!! ops is tiny -- the feed did not drive a real frame (wrong wire?). "
          "The dirty fraction above is NOT a frame's worth. Re-run with the right --feed.")
