"""How often is a 0x0B column a DITTO, and what does it save? Measured on real frames.

The renderer emits [x][0xFE] when a column's REGION LIST is byte-identical to the previous
column's (src/fj/stream_render.fj) -- so the question "how common are identical columns" is
answerable exactly: tap the shipped binary's own output stream and count.

    python scratchpad/ditto_census.py
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
                                    ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots              # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wireformat import (encode_bindings, encode_feed,              # noqa: E402
                               encode_things, encode_visibility)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402
from tests.fj.stream_screen import StreamScreen                                # noqa: E402

mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(mw, "E1M1")
dr = [t for t in mw.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bk = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
nvis = len(vanishable_slots(dr, bk, VANISHABLE_TYPES))
rt = [t for t, b in zip(dr, bk) if not b]
tail = (encode_things([(t.x << 16, t.y << 16) for t in rt])
        + encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
        + encode_visibility([1] * nvis))
sp = spawn_state(mw, "E1M1")
VPS = [(_signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle),
       (664, 291, 0x18000000), (1272, -724, 0x40000000), (1869, 479, 0x80000000),
       (461, 2015, 0x40000000), (845, 1631, 0xC0000000)]


class Tap(StreamScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.tap = bytearray()

    def _handle_byte(self, byte):
        self.tap.append(byte)
        return super()._handle_byte(byte)


def census(stream: bytes):
    """decode the 0x0B records: (columns, ditto columns, pairs, pairs the dittos stood in for)."""
    i = stream.index(0x0B) + 1
    cols = dittos = pairs = saved = 0
    last_pairs = 0
    while i < len(stream):
        tag = stream[i]; i += 1
        if tag == 0xFF:
            break
        cols += 1
        if stream[i] == 0xFE:                 # a DITTO stands in for the previous column's pairs
            dittos += 1
            saved += last_pairs
            i += 1
            continue
        n = 0
        while stream[i] != 0xFF:
            n += 1; i += 2
        i += 1
        pairs += n
        last_pairs = n
    return cols, dittos, pairs, saved


runner = FjmRunner(ROOT / "scratchpad/fjmcache/_ca2_ship_new.fjm")
print("           viewpoint          columns   DITTO    %      pairs  pairs saved   bytes saved")
tc = td = tp = ts = 0
for vx, vy, va in VPS:
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    scr = Tap(stdin=encode_feed(vx << 16, vy << 16, va, 0) + tail, n_things=len(rt))
    scr.attach_memory(NativeDeviceMemory(core, runner.width))
    core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
    data = bytes(scr.tap)
    del core, scr
    c, d, p, s = census(data)
    tc += c; td += d; tp += p; ts += s
    print("  (%5d,%5d,%#010x) %6d %7d %5.1f%% %10d %12d %13d"
          % (vx, vy, va, c, d, 100.0 * d / max(1, c), p, s, 2 * s - d))
print("")
print("  TOTAL over %d viewpoints    %6d %7d %5.1f%% %10d %12d %13d"
      % (len(VPS), tc, td, 100.0 * td / max(1, tc), tp, ts, 2 * ts - td))
print("")
print("  a DITTO column costs 2 bytes ([x][0xFE]); the column it replaces would have cost")
print("  2 + 2*pairs. So the saving is in PAIRS, and a pair is the unit the protocol charges")
print("  for -- docs/m13p put byte.emit at 283.6 ops and cm.emit at 329.5 (UNVERIFIED here).")
