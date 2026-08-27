"""M2-R3 pre-measurement -- what does an OPEN door cost in ops, on binaries that already exist?
The owner's constraint on R3/R4 is "keep ops/frame at similar cost". Before designing the runtime
door it is worth knowing what the RENDER side of a door costs when it is open, because two of R3's
required changes only bite when a door is open:
  * the walk can no longer PRUNE a shut door's subsector (13 subsectors + their segs come back);
  * `thing_live_subsectors` can no longer call a shut door uninhabitable.
Both are already true in `build/doom_e1m1_doors100.fjm` (R2 baked every door open), so the delta
against the shut binary prices them WITHOUT a build. What it does NOT price is the per-state
dispatch R3 adds -- that is new code, and it gets its own measurement when it exists.
    python scratchpad/m2_ops.py
R9 CONTROL: the same binary against ITSELF must report a zero delta at every viewpoint. If the
runner were nondeterministic, or the op counter were reading something other than this frame, the
deltas below would be noise and the control would show it.
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
DOOR_VPS = [(461, 2015, 0x40000000), (845, 1631, 0xC0000000), (461, 863, 0x40000000)]
CERT_VPS = [(664, 291, 0x18000000), (1272, -724, 0x40000000),
            (1869, 479, 0x80000000), (-416, 256, 0x0)]
import argparse
_ap = argparse.ArgumentParser()
_ap.add_argument("--open", default="build/doom_e1m1_doors100.fjm")
_ap.add_argument("--shut", default="scratchpad/fjmcache/_ca2_ship_new.fjm")
_ap.add_argument("--label", default="the R2 binary with all 13 doors baked OPEN")
_args = _ap.parse_args()
OPEN_FJM = ROOT / _args.open
SHUT_FJM = ROOT / _args.shut
mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(mw, "E1M1")
drawable = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
nvis = len(vanishable_slots(drawable, baked, VANISHABLE_TYPES))
runtime = [t for t, b in zip(drawable, baked) if not b]
blob_tail = (encode_things([(t.x << 16, t.y << 16) for t in runtime])
             + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in runtime])
             + encode_visibility([1] * nvis))
def render(runner, vp):
    vx, vy, va = vp
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    scr = StreamScreen(stdin=encode_feed(vx << 16, vy << 16, va, 0) + blob_tail,
                       n_things=len(runtime))
    scr.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    del core, scr
    return ops
shut = FjmRunner(SHUT_FJM)
opn = FjmRunner(OPEN_FJM)
assert shut.native and opn.native, "this needs the native engine"
print("ops/frame: %s vs %s" % (SHUT_FJM.name, OPEN_FJM.name))
print("           %s" % _args.label)
print("%-26s %14s %14s %12s" % ("viewpoint", "base", "under test", "delta"))
tot_s = tot_o = 0
rows = []
for tag, vps in (("DOOR", DOOR_VPS), ("CERT", CERT_VPS)):
    for vp in vps:
        a, b = render(shut, vp), render(opn, vp)
        tot_s += a
        tot_o += b
        rows.append((tag, vp, a, b))
        print("%-4s %-21s %14s %14s %11.2f%%"
              % (tag, "(%d,%d,0x%08x)" % vp, format(a, ","), format(b, ","),
                 100.0 * (b - a) / a))
print("")
print("%-26s %14s %14s %11.2f%%"
      % ("TOTAL over 7 viewpoints", format(tot_s, ","), format(tot_o, ","),
         100.0 * (tot_o - tot_s) / tot_s))
# R9: the same binary against itself must be a flat zero, or the deltas above are noise.
same = [render(shut, vp) - render(shut, vp) for vp in DOOR_VPS]
print("")
print("CONTROL (shut vs shut, same viewpoints): %s -- %s"
      % (same, "deterministic" if not any(same) else "!! NONDETERMINISTIC, deltas are noise"))
