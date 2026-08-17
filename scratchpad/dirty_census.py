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

    python scratchpad/dirty_census.py <cached.fjm> [--sample 200000] [--feed "x\\ny\\na\\n"]
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
args = ap.parse_args()


def fresh(r):
    """A core holding the program's PRISTINE image."""
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for seg_start, seg_len in r._segments:
        core.add_segment(seg_start, seg_len)
    for start, vals in r._runs:
        core.set_words(start, vals)
    return core


def run_one(r, core, feed):
    scr = StreamScreen(stdin=feed.encode())
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    return ops


r = FjmRunner(Path(args.fjm))
assert r.native, "needs the native engine"
total_words = sum(seg_len for _s, seg_len in r._segments)
print(f"{Path(args.fjm).name}: segments={len(r._segments)}  words={total_words:,}"
      f"  (~{total_words*8/1e6:.0f} MB)", flush=True)

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

dirty_core = fresh(r)
ops = run_one(r, dirty_core, args.feed)
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
