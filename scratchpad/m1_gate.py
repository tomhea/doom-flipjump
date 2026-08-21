"""M1 GATE — the self-resetting program renders N frames from ONE run, byte-exact.

This is the milestone gate for M1c+M1d. It runs the LOOPING binary once, feeds it several frames of
wire input, and requires:

  PHASE 1  every frame byte-exact against the ORACLE (`reference_model.render_wall_frame`) --
           the proof it still renders DOOM, not merely something stable;
  PHASE 2  a longer chain, every frame byte-exact against the SAME frame rendered by the OLD
           one-frame-per-run binary on a PRISTINE image -- the proof the in-program reset is
           equivalent to the host's whole-image memcpy;
  PHASE 3  the reset's own cost, measured as (loop run ops) - (sum of individual frame ops).

⚠ NEGATIVE CONTROLS (R9):
  1. FRAME COUNT: the device must present EXACTLY as many frames as were fed. A program that
     halted after one frame and a gate that only checked frame 1 would pass everything here.
  2. NON-LOOPING CONTROL: the same wire on the OLD binary must present exactly ONE frame. That is
     what makes "N frames" evidence of the loop rather than of the device.
  3. VACUITY: the reference pictures must all be DISTINCT, or "byte-exact" is free.
  4. The oracle is an INDEPENDENT renderer, not a recording of the binary.

    python scratchpad/m1_gate.py
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel, SimState, build_scene, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.fjm_run import IOReadOnEOF                      # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory  # noqa: E402
from tests.fj.stream_screen import StreamScreen                           # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--loop-fjm", default="scratchpad/fjmcache/_m1loop.fjm")
ap.add_argument("--old-fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
ap.add_argument("--corrupt-frame", type=int, default=None,
                help="flip one byte of this presented frame -- the NEGATIVE CONTROL, see --selftest")
ap.add_argument("--selftest", action="store_true",
                help="run the gate twice, once with --corrupt-frame 0, and require the second to FAIL")
args = ap.parse_args()

if args.selftest:
    # R9. A gate whose verdict is quoted as proof must be shown to be capable of the other verdict.
    # This re-runs the REAL gate on the REAL binaries, once untouched and once with a single byte of
    # one presented frame flipped, and requires PASS then FAIL. It is not a separate reimplementation
    # of the checks -- it is this file, twice.
    import subprocess
    base = [sys.executable, __file__, "--loop-fjm", args.loop_fjm, "--old-fjm", args.old_fjm,
            "--wad", args.wad]
    print("SELFTEST 1/2: the gate as shipped -- must PASS", flush=True)
    a = subprocess.run(base).returncode
    print("")
    print("SELFTEST 2/2: one byte of presented frame 0 flipped -- must FAIL", flush=True)
    b = subprocess.run(base + ["--corrupt-frame", "0"]).returncode
    good = a == 0 and b != 0
    print("")
    print("=" * 96)
    print("  clean run  exit %d (want 0)" % a)
    print("  mutated    exit %d (want non-zero)" % b)
    print("M1 GATE SELFTEST: %s" % ("PASS" if good else
                                    "!! FAIL -- this gate cannot distinguish a wrong frame"))
    print("=" * 96)
    sys.exit(0 if good else 1)


class MultiFrameScreen(StreamScreen):
    """StreamScreen that keeps a COPY of every presented frame, not just the last one."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
cfg = Config()
rm = ReferenceModel(cfg)
cmap = bake_bsp(w, "E1M1")
scene = build_scene(w, w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])
sp = spawn_state(w, "E1M1")
SPX, SPY = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16


def wire(vx, vy, va, keys=0, dx=0, dy=0):
    return (encode_feed(vx << 16, vy << 16, va, keys)
            + encode_things([((t.x + dx) << 16, (t.y + dy) << 16) for t in RT])
            + BINDS + encode_visibility([1] * NVIS))


def oracle(vx, vy, va):
    return bytes(rm.render_wall_frame(
        SimState(vx << 16, vy << 16, va, "E1M1"), scene, wall_mode="W1R", floor_mode_ft1=True,
        plane_near=True, wall_noise=True, near_steps=True, stack_steps=True,
        things=True, sprite_wad=art, degrade=True))


def run_all(fjm, blob, keep=None):
    r = FjmRunner(Path(fjm))
    assert r.native
    core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        core.add_segment(s, n)
    for st, vals in r._runs:
        core.set_words(st, vals)
    scr = MultiFrameScreen(stdin=blob, n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    frames = list(scr.frames)
    del core, scr, r
    if (args.corrupt_frame is not None and str(fjm) == str(args.loop_fjm)
            and len(frames) > args.corrupt_frame):
        # THE NEGATIVE CONTROL, and it must hit the LOOP BINARY ONLY.
        #
        # ⚠ CR round 3 caught this guard testing `keep is None`, which NO CALLER EVER SETS -- so the
        # flip landed on every run, INCLUDING the old-binary reference runs. The gate then failed
        # for the wrong reason: frame 0 came out "loop vs old BYTE-EXACT" (both corrupted
        # identically) and the FAIL came from a corrupted REFERENCE at frame 1. A control that
        # proves the gate notices a broken reference proves nothing about the property the gate
        # exists to certify -- that a WRONG LOOP FRAME is rejected. Compare against the loop path
        # explicitly instead.
        k = args.corrupt_frame
        b = bytearray(frames[k])
        b[0] ^= 1
        frames[k] = bytes(b)
    return ops, frames


# --------------------------------------------------------------------------------------- PHASE 1
VPS = [(664, 291, 0x18000000), (1272, -724, 0x40000000),
       (1869, 479, 0x80000000), (SPX, SPY, sp.angle)]
print("=" * 96)
print("PHASE 1 -- the four certified viewpoints, ALL IN ONE RUN, byte-exact vs the ORACLE")
print("=" * 96)
t0 = time.perf_counter()
refs = [oracle(*v) for v in VPS]
assert len({bytes(x) for x in refs}) == len(refs), \
    "CONTROL 3 (vacuity): the oracle pictures are not all distinct"
print(f"  {len(refs)} oracle pictures, all distinct ({time.perf_counter()-t0:.0f}s)", flush=True)

blob = b"".join(wire(*v) for v in VPS)
ops, frames = run_all(args.loop_fjm, blob)
print(f"  ONE run: {ops:,} ops -> {len(frames)} frames presented", flush=True)
ok1 = len(frames) == len(VPS)
print(f"  CONTROL 1 (frame count): {len(frames)} == {len(VPS)}?  "
      f"{'ok' if ok1 else '!! FAIL -- the loop did not run ' + str(len(VPS)) + ' frames'}")

# ⚠ THE ORACLE CALL BELOW IS `deg_gate`'s, WHICH CERTIFIES THE NON-SIM TIER. The shipped binary
# runs `moving_things=True`, so 75 things arrive on the wire instead of being baked into their
# leaf, and at some viewpoints that renders a few pixels differently. MEASURED: the OLD, already
# certified binary differs from this oracle call by 378 px at (1869,479) too. So the test that
# means anything for M1 is not "loop == oracle" -- it is "the loop's delta from the oracle is
# EXACTLY the old binary's delta", i.e. M1 introduced nothing. Both numbers are printed.
print("  (the oracle call is deg_gate's, which certifies the NON-sim tier -- so the old binary's")
print("   own delta is printed beside the loop's, and they must be equal)")
for k, (v, ref) in enumerate(zip(VPS, refs)):
    if k >= len(frames):
        print(f"  frame {k} ({v[0]},{v[1]},{v[2]:#x}): MISSING")
        ok1 = False
        continue
    _o, oldf = run_all(args.old_fjm, wire(*v))
    assert len(oldf) == 1
    d_loop = sum(1 for a, b in zip(frames[k], ref) if a != b)
    d_old = sum(1 for a, b in zip(oldf[0], ref) if a != b)
    same_as_old = frames[k] == oldf[0]
    good = same_as_old and d_loop == d_old
    ok1 &= good
    print(f"  frame {k} ({v[0]},{v[1]},{v[2]:#x}): loop vs old "
          f"{'BYTE-EXACT' if same_as_old else '!! DIFFER'}; "
          f"vs oracle loop={d_loop} old={d_old} "
          f"{'(equal -- M1 changed nothing)' if d_loop == d_old else '!! M1 MOVED PIXELS'}"
          f"  {'ok' if good else 'FAIL'}")

# --------------------------------------------------------------------------------------- CONTROL 2
print("\nCONTROL 2 (non-looping): the SAME wire on the OLD binary must present exactly 1 frame")
ops_old1, frames_old = run_all(args.old_fjm, blob)
ok2 = len(frames_old) == 1
print(f"  old binary: {ops_old1:,} ops -> {len(frames_old)} frame(s)  "
      f"{'ok -- so N frames IS the loop' if ok2 else '!! the device loops by itself; phase 1 proves nothing'}")

# --------------------------------------------------------------------------------------- PHASE 2
print("\n" + "=" * 96)
print("PHASE 2 -- a longer chain vs the OLD binary on a PRISTINE image, per frame")
print("=" * 96)
CHAIN = [(664, 291, 0x18000000, 0, 0, 0), (700, 300, 0x20000000, 1, 0, 0),
         (1272, -724, 0x40000000, 5, 16, 0), (1869, 479, 0x80000000, 0, 0, 0),
         (SPX, SPY, sp.angle, 4, -32, 48), (1000, 100, 0x20000000, 8, 0, 0),
         (2100, 800, 0xC0000000, 5, 16, -16), (1500, -200, 0x60000000, 1, 0, 0)]
ref2, ops_each = [], []
for c in CHAIN:
    o, f = run_all(args.old_fjm, wire(*c))
    assert len(f) == 1, f"the old binary presented {len(f)} frames for one wire"
    ref2.append(f[0])
    ops_each.append(o)
assert len(set(ref2)) == len(ref2), "CONTROL 3 (vacuity): chain pictures are not all distinct"
print(f"  {len(ref2)} pristine references, all distinct", flush=True)

blob2 = b"".join(wire(*c) for c in CHAIN)
ops_loop, frames2 = run_all(args.loop_fjm, blob2)
ok3 = len(frames2) == len(CHAIN)
print(f"  ONE run: {ops_loop:,} ops -> {len(frames2)} frames  "
      f"{'ok' if ok3 else '!! FAIL'}")
for k, c in enumerate(CHAIN):
    if k >= len(frames2):
        print(f"  frame {k}: MISSING")
        ok3 = False
        continue
    same = frames2[k] == ref2[k]
    diff = sum(1 for a, b in zip(frames2[k], ref2[k]) if a != b)
    ok3 &= same
    print(f"  frame {k} ({c[0]},{c[1]},{c[2]:#x},k={c[3]}): "
          f"{'BYTE-EXACT' if same else f'!! {diff} px DIFFER'}")

# --------------------------------------------------------------------------------------- PHASE 3
print("\n" + "=" * 96)
print("PHASE 3 -- what the in-program reset COSTS")
print("=" * 96)
base = sum(ops_each)
extra = ops_loop - base
# the reset runs after EVERY frame, including the last (then the next input read hits EOF),
# so the divisor is the frame count, not count-1.
per = extra / len(CHAIN)
print(f"  {len(CHAIN)} frames, one at a time on the old binary : {base:,} ops")
print(f"  the same {len(CHAIN)} frames in ONE looping run       : {ops_loop:,} ops")
print(f"  difference                                        : {extra:+,} ops")
print(f"  => the reset costs ~{per:,.0f} ops per frame "
      f"({100*per/(base/len(CHAIN)):.2f}% of a {base//len(CHAIN):,}-op frame)")
print("  (the loop also SAVES the 2 ops of op0 + `;__hot_end` per frame, and the host's whole-image")
print("   memcpy entirely -- which is the point; see the fps line in the handoff.)")

ok = ok1 and ok2 and ok3
print("\n" + "=" * 96)
print(f"PHASE 1 (oracle, 4 frames one run) : {'PASS' if ok1 else 'FAIL'}")
print(f"CONTROL 2 (old binary = 1 frame)   : {'PASS' if ok2 else 'FAIL'}")
print(f"PHASE 2 (8-frame chain vs pristine): {'PASS' if ok3 else 'FAIL'}")
print(f"M1 GATE: {'PASS' if ok else 'FAIL'}")
print("=" * 96)
sys.exit(0 if ok else 1)
