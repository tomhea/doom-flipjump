"""M2 -- what an OPEN door COSTS, in ops/frame. Measured, both binaries, same viewpoints.

The owner's M2 constraint is "keep ops/frame at similar cost". This is the R2 answer: the SAME
seven viewpoints the door gate uses, rendered by the doors-SHUT binary and the doors-OPEN one,
op counts side by side.

!! SCOPE. These are seven viewpoints, NOT the 260-frame sweep median that is the repo's real
metric (scratchpad/m1_sweep.py). The sweep needs a LOOPING binary and the R2 build has no
self-reset, so it cannot run here. Three of these seven were chosen precisely because they stare
at a door, so they OVERSTATE a typical frame's door cost by construction. Read the direction and
the order of magnitude, not the percentage.

    python scratchpad/m2_ops.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.mapcompiler import bake_bsp                                   # noqa: E402
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES,      # noqa: E402
                                    ReferenceModel)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

VPS = [("DOOR", (461, 2015, 0x40000000)), ("DOOR", (845, 1631, 0xC0000000)),
       ("DOOR", (461, 863, 0x40000000)), ("CERT", (664, 291, 0x18000000)),
       ("CERT", (1272, -724, 0x40000000)), ("CERT", (1869, 479, 0x80000000)),
       ("CERT", (-416, 256, 0x0))]

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(mw, "E1M1")
drawable = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
runtime = [t for t, b in zip(drawable, baked) if not b]
tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
        + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
        + encode_visibility([1] * nvis))


def ops_at(runner, vp):
    vx, vy, va = vp
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    scr = StreamScreen(stdin=encode_feed(vx << 16, vy << 16, va, 0) + tail, n_things=len(runtime))
    scr.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    del core, scr
    return ops


shut = FjmRunner(ROOT / "scratchpad/fjmcache/_ca2_ship_new.fjm")
open_ = FjmRunner(ROOT / "build/doom_e1m1_doors100.fjm")
print("        viewpoint                   doors SHUT      doors OPEN         delta")
tot_s = tot_o = 0
for label, vp in VPS:
    a, b = ops_at(shut, vp), ops_at(open_, vp)
    tot_s += a; tot_o += b
    print("  %s (%5d,%5d,%#010x)  %12s  %12s  %+12s  %+6.2f%%"
          % (label, vp[0], vp[1], vp[2], format(a, ","), format(b, ","),
             format(b - a, ","), 100.0 * (b - a) / a))
print("")
print("  TOTAL over %d viewpoints        %12s  %12s  %+12s  %+6.2f%%"
      % (len(VPS), format(tot_s, ","), format(tot_o, ","), format(tot_o - tot_s, ","),
         100.0 * (tot_o - tot_s) / tot_s))
print("")
print("  !! three of these seven stare AT a door and were picked for that, so this OVERSTATES a")
print("     typical frame. The real metric is the 260-frame sweep median, which needs a looping")
print("     binary the R2 build does not have.")
