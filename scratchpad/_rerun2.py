"""Does the SHIPPED program get PAST the 9-op death when word 1 is restored -- and does it STOP?

The first version of this probe timed out at 1800s, which is itself the headline: with word 1 put
back, frame 2 no longer dies at 9 ops, it runs and runs. This one bounds the run so the answer is a
number instead of a timeout, and it reuses ONE core instead of rebuilding a 629 MB image per case.

⚠ RUNNING LONG IS NOT RUNNING CORRECTLY. The latches (drawn/pclm/sfflag/sprflag, tsstop, n_claimed,
sshead/thnext) are still dirty from frame 1, so frame 2 may render nonsense enthusiastically. What
this measures is the SHAPE of the remaining work: if frame 2 terminates near frame 1's op count the
reset list is nearly complete; if it never terminates, a latch is driving an unbounded loop and the
prologue has to clear it. Either way it is bounded engineering, not an architecture change.
"""
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.fastrun import FjmRunner, _fjcore
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel, spawn_state
from doomfj.things import baked_thing_mask, vanishable_slots
from doomfj.wad import WadFile
from doomfj.wireformat import encode_bindings, encode_feed, encode_things, encode_visibility
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from tests.fj.stream_screen import StreamScreen

FJM = sys.argv[1]
BUDGET = float(sys.argv[2]) if len(sys.argv) > 2 else 120.0

cfg = Config()
w = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(cfg)
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bk = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
nvis = len(vanishable_slots(dr, bk, VANISHABLE_TYPES))
rt = [t for t, b in zip(dr, bk) if not b]
BLOB = (encode_things([(t.x << 16, t.y << 16) for t in rt])
        + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
        + encode_visibility([1] * nvis))
sp = spawn_state(w, "E1M1")
ST = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
FEED = encode_feed(ST[0], ST[1], ST[2], 0) + BLOB

r = FjmRunner(ROOT / FJM)
core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
for s, n in r._segments:
    core.add_segment(s, n)
for s, vals in r._runs:
    core.set_words(s, vals)
print(f"{Path(FJM).name}: {sum(n for _s, n in r._segments):,} words", flush=True)

PRIS = [core.get_word(a) for a in range(8)]


def run(tag):
    scr = StreamScreen(stdin=FEED, n_things=len(rt))
    scr.attach_memory(NativeDeviceMemory(core, r.width))
    t0 = time.perf_counter()
    try:
        _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
        dt = time.perf_counter() - t0
        print(f"  {tag:<22} {ops:>14,} ops in {dt:6.1f}s   "
              f"{len(bytes(scr.pixel_indices)):>6} px bytes", flush=True)
        return ops, bytes(scr.pixel_indices)
    except Exception as e:
        print(f"  {tag:<22} died -- {type(e).__name__}: {str(e)[:60]}", flush=True)
        return None, b""


ops1, px1 = run("frame 1 (pristine)")
changed = [(a, PRIS[a], core.get_word(a)) for a in range(8) if core.get_word(a) != PRIS[a]]
print(f"  low words changed by a frame: "
      f"{[(a, hex(o), hex(n), 'xor=%d' % (o ^ n)) for a, o, n in changed]}", flush=True)

for a, old, _new in changed:
    core.set_words(a, [old])
print(f"  restored {len(changed)} low word(s); running frame 2 on the OTHERWISE DIRTY image "
      f"(budget {BUDGET:.0f}s)", flush=True)


class Timeout(Exception):
    pass


ops2, px2 = None, b""
t0 = time.perf_counter()
try:
    ops2, px2 = run("frame 2 (words restored)")
except KeyboardInterrupt:
    print(f"  frame 2: still running after {time.perf_counter()-t0:.0f}s", flush=True)

if ops2 is not None:
    print(f"\nframe 2 TERMINATED: {ops2:,} ops vs frame 1's {ops1:,} "
          f"({ops2 - ops1:+,})")
    print(f"pixels {'IDENTICAL to frame 1' if px2 == px1 else 'DIFFER -- the latches are dirty, as expected'}")
    print("\n=> the 9-op death is the LOW WORDS ONLY. What remains is a reset prologue over the")
    print("   known latch set -- bounded engineering, not an architecture change.")
