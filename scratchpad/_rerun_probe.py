"""Can the SHIPPED program render a SECOND frame if we restore only word 1?

THE CLAIM (design investigation, 2026-08-19): "one run = one frame" -- the fact that has shaped
this project's architecture -- is ONE BIT. Word 1 is the jump field of the program's first op
(stl.startup's `;code_start`); a run XORs it with 512, so run 2 enters 8 ops BEFORE code_start,
lands in the stack error handler and hits `;0` -> NullIP at exactly 9 ops. Restoring word 1 alone
was measured to turn 9 ops into 424,376 -- on SMALL binaries only.

⚠ THIS PROBE TESTS THE 68M-WORD SHIPPED BINARY, which is the gap in that evidence.

⚠ AND IT IS NOT A CORRECTNESS TEST. Getting further is not the same as being right: the latches
(pclm/drawn/sfflag/sprflag, tsstop, n_claimed, sshead/thnext) are still dirty, so frame 2 may run
long and draw garbage. What this measures is ONLY: is the 9-op death a single word, or the whole
image? Those imply completely different amounts of work.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config
from doomfj.fastrun import FjmRunner, _fjcore
from doomfj.fixedpoint import _signed
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import (MONSTER_TYPES, VANISHABLE_TYPES, ReferenceModel, spawn_state)
from doomfj.things import baked_thing_mask, vanishable_slots
from doomfj.wad import WadFile
from doomfj.wireformat import encode_bindings, encode_feed, encode_things, encode_visibility
from flipjump.interpreter.fjm_run import IOReadOnEOF
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory
from tests.fj.stream_screen import StreamScreen

FJM = sys.argv[1] if len(sys.argv) > 1 else "scratchpad/fjmcache/m14_bin_things_cull.fjm"
WAD = sys.argv[2] if len(sys.argv) > 2 else "tests/fixtures/freedoom_e1m1.wad"

cfg = Config()
w = WadFile.from_path(str(ROOT / WAD))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(cfg)
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bk = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
nvis = len(vanishable_slots(dr, bk, VANISHABLE_TYPES))
rt = [t for t, b in zip(dr, bk) if not b]
POS = encode_things([(t.x << 16, t.y << 16) for t in rt])
VIS = encode_visibility([1] * nvis)
BIND = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in rt])
sp = spawn_state(w, "E1M1")


def feed(st, keys=0):
    return encode_feed(st[0], st[1], st[2], keys) + POS + BIND + VIS


r = FjmRunner(ROOT / FJM)
core = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
for s, n in r._segments:
    core.add_segment(s, n)
for s, vals in r._runs:
    core.set_words(s, vals)
total = sum(n for _s, n in r._segments)
print(f"{Path(FJM).name}: {total:,} words", flush=True)

W0 = [core.get_word(a) for a in range(4)]
print(f"pristine words[0..3] = {[hex(v) for v in W0]}", flush=True)

st = (_signed(sp.x, 32), _signed(sp.y, 32), sp.angle)
scr = StreamScreen(stdin=feed(st), n_things=len(rt))
scr.attach_memory(NativeDeviceMemory(core, r.width))
_c, ops1, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
px1 = bytes(scr.pixel_indices)
st1 = scr.state
print(f"frame 1: {ops1:,} ops -> ({st1[0]/65536:.3f},{st1[1]/65536:.3f})", flush=True)

after = [core.get_word(a) for a in range(4)]
print(f"after   words[0..3] = {[hex(v) for v in after]}", flush=True)
for a in range(4):
    if after[a] != W0[a]:
        print(f"  word {a} CHANGED: {W0[a]:#x} -> {after[a]:#x}   xor = {W0[a] ^ after[a]}"
              f" (= bit {(W0[a] ^ after[a]).bit_length()-1})", flush=True)

for label, restore in (("NOTHING restored", []), ("word 1 only", [1]), ("words 0..3", [0, 1, 2, 3])):
    c2 = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c2.add_segment(s, n)
    for s, vals in r._runs:
        c2.set_words(s, vals)
    s2 = StreamScreen(stdin=feed(st), n_things=len(rt))
    s2.attach_memory(NativeDeviceMemory(c2, r.width))
    c2.run(s2.read_bit, s2.write_bit, IOReadOnEOF, last_ops_length=0)   # frame 1, dirties it
    for a in restore:
        c2.set_words(a, [W0[a]])
    s3 = StreamScreen(stdin=feed(st), n_things=len(rt))
    s3.attach_memory(NativeDeviceMemory(c2, r.width))
    try:
        _c, ops2, _e, _l, _p = c2.run(s3.read_bit, s3.write_bit, IOReadOnEOF, last_ops_length=0)
        px2 = bytes(s3.pixel_indices)
        same = px2 == px1 if len(px2) == len(px1) else False
        print(f"  frame 2 [{label:>16}]: {ops2:>12,} ops   pixels "
              f"{'IDENTICAL' if same else f'{len(px2)} bytes, differ'}", flush=True)
    except Exception as e:
        print(f"  frame 2 [{label:>16}]: died -- {type(e).__name__}: {str(e)[:70]}", flush=True)
