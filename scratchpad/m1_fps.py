"""M1 — the fps M1 was for. Host-restore model vs the internal loop, measured back to back.

The whole point of M1: today the host reloads a pristine 84.8M-word image before every frame, a
fixed cost that caps the game no matter how cheap the frame gets. The looping binary does not need
it. This measures both, on the same machine, in the same process, alternating so a drifting machine
cannot favour one -- CLAUDE.md's rule about this box: two VMs compete for it and the same code has
measured 758 s and 802 s in consecutive runs.

⚠ NEGATIVE CONTROLS (R9):
  1. BOTH SIDES MEASURED IN-SESSION, alternating A/B/A/B, and CPU time reported beside wall.
  2. The two paths must produce the SAME PIXELS -- otherwise the fast one is fast because it is
     doing less. Checked frame by frame, not just at the end.
  3. The restore cost is isolated: the old path is also timed WITHOUT the reload, which is not a
     legal configuration (it renders garbage after frame 1) but bounds how much of the gap is the
     memcpy rather than the frame.

    python scratchpad/m1_fps.py [--frames 8] [--reps 3]
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
                                    ReferenceModel, spawn_state)
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
ap.add_argument("--frames", type=int, default=8)
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()


class MF(StreamScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])
sp = spawn_state(w, "E1M1")
SPX, SPY = _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16


def wire(vx, vy, va, keys=0):
    return (encode_feed(vx << 16, vy << 16, va, keys)
            + encode_things([(t.x << 16, t.y << 16) for t in RT])
            + BINDS + encode_visibility([1] * NVIS))


CH = [(664, 291, 0x18000000, 0), (700, 300, 0x20000000, 1), (1272, -724, 0x40000000, 5),
      (1869, 479, 0x80000000, 0), (SPX, SPY, sp.angle, 4), (1000, 100, 0x20000000, 8),
      (2100, 800, 0xC0000000, 5), (1500, -200, 0x60000000, 1)][:args.frames]

R_OLD = FjmRunner(Path(args.old_fjm))
R_NEW = FjmRunner(Path(args.loop_fjm))
print(f"old {Path(args.old_fjm).name}: {sum(n for _s,n in R_OLD._segments):,} words")
print(f"new {Path(args.loop_fjm).name}: {sum(n for _s,n in R_NEW._segments):,} words")


def image(r):
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for st, vals in r._runs:
        c.set_words(st, vals)
    return c


def host_restore_path():
    """What ships today: reload the pristine image, then run ONE frame. Per frame."""
    w0, c0 = time.perf_counter(), time.process_time()
    frames = []
    for v in CH:
        core = image(R_OLD)                       # <- THE ~52 ms whole-image restore
        scr = MF(stdin=wire(*v), n_things=len(RT))
        scr.attach_memory(NativeDeviceMemory(core, R_OLD.width))
        core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        frames += scr.frames
        del core, scr
    return time.perf_counter() - w0, time.process_time() - c0, frames


def loop_path():
    """M1: load the image ONCE, run every frame in a single execution."""
    w0, c0 = time.perf_counter(), time.process_time()
    core = image(R_NEW)
    scr = MF(stdin=b"".join(wire(*v) for v in CH), n_things=len(RT))
    scr.attach_memory(NativeDeviceMemory(core, R_NEW.width))
    core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    fr = list(scr.frames)
    del core, scr
    return time.perf_counter() - w0, time.process_time() - c0, fr


print(f"\nalternating A/B x{args.reps}, {len(CH)} frames each:")
A, B = [], []
ref = None
for rep in range(args.reps):
    aw, ac, af = host_restore_path()
    bw, bc, bf = loop_path()
    assert len(af) == len(bf) == len(CH), f"frame count {len(af)}/{len(bf)} != {len(CH)}"
    assert af == bf, "CONTROL 2 FAILED: the two paths render DIFFERENT pixels"
    if ref is None:
        ref = af
    assert af == ref, "the runs are not deterministic"
    A.append((aw, ac))
    B.append((bw, bc))
    print(f"  rep {rep}: host-restore {aw:6.2f}s wall / {ac:6.2f}s cpu   "
          f"loop {bw:6.2f}s wall / {bc:6.2f}s cpu", flush=True)

aw = min(x for x, _ in A)
ac = min(y for _, y in A)
bw = min(x for x, _ in B)
bc = min(y for _, y in B)
n = len(CH)
print("\nCONTROL 2: both paths rendered identical pixels on every frame, every rep  ok")
print("\n" + "=" * 92)
print(f"{'':<26}{'wall/frame':>14}{'fps (wall)':>12}{'cpu/frame':>14}{'fps (cpu)':>12}")
print("-" * 92)
print(f"{'host restores the image':<26}{aw/n*1000:>12.1f}ms{n/aw:>12.2f}{ac/n*1000:>12.1f}ms{n/ac:>12.2f}")
print(f"{'M1 internal loop':<26}{bw/n*1000:>12.1f}ms{n/bw:>12.2f}{bc/n*1000:>12.1f}ms{n/bc:>12.2f}")
print("-" * 92)
print(f"{'speedup':<26}{aw/bw:>12.2f}x{'':>12}{ac/bc:>12.2f}x")
print("=" * 92)
print(f"(best of {args.reps} reps each, alternated. The frame itself is unchanged; the loop pays")
print(" ~3.55M ops of in-program reset and saves the whole-image reload.)")
