"""M1 -- PLAYABILITY: 100 frames of actual movement from ONE run of the program.

This is the test that the thing is a GAME and not a frame renderer. Every earlier gate fed a list
of viewpoints the HOST had chosen. Here the host chooses only KEYS: the fj program runs the player
sim, collides against real linedefs, moves the player, and ECHOES the new state, and the device
feeds that echo straight back as the next frame's input. The player really walks and turns; nothing
in Python computes where they end up.

That is only possible because the device generates the wire LAZILY -- read_bit refills from the
last echoed state when the buffer runs dry, which is exactly what an interactive host does. A
pre-filled buffer cannot do it: frame N+1's input does not exist until frame N has run.

WHAT IT CHECKS
  1. the run presents exactly N frames from ONE execution;
  2. the player actually MOVED -- a script that never leaves the spawn proves nothing, so distance
     travelled, distinct positions and distinct angles are all asserted;
  3. every frame is BYTE-EXACT against that same state rendered by the OLD one-frame-per-run
     binary on a PRISTINE image. That is the real check: the loop must be indistinguishable from
     the certified host-restore path, frame for frame, along a path the loop itself chose.

NEGATIVE CONTROLS (R9)
  * VACUITY: the frames must not all be identical, and the walk must cover ground.
  * The reference is an INDEPENDENT run of the old binary, never the previous frame.
  * The key script turns, walks, reverses and idles, so a bug that only shows when the view angle
    changes has somewhere to appear.

    python scratchpad/m1_play.py [--frames 100]
"""
import argparse
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

ap = argparse.ArgumentParser()
ap.add_argument("--loop-fjm", default="scratchpad/fjmcache/_m1loop4.fjm")
ap.add_argument("--old-fjm", default="scratchpad/fjmcache/_rssprobe.fjm")
ap.add_argument("--frames", type=int, default=100)
ap.add_argument("--png-every", type=int, default=25)
ap.add_argument("--png-dir", default="scratchpad/_m1_play_frames")
ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
args = ap.parse_args()


def _sha(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# R2 (CR round 6): a verdict that names no artifact cannot be attributed to one. Print the images
# this run is about, with hashes, so the log says what it measured.
for _lbl, _pth in (("loop", args.loop_fjm), ("old ", args.old_fjm)):
    print("%s : %s  sha256 %s" % (_lbl, _pth, _sha(_pth)))
print("")


FWD, BACK, LEFT, RIGHT = 1, 2, 4, 8


def key_script(n):
    out = []
    for i in range(n):
        p = i % 50
        if p < 14:
            out.append(FWD)
        elif p < 20:
            out.append(LEFT)
        elif p < 32:
            out.append(FWD)
        elif p < 36:
            out.append(RIGHT)
        elif p < 42:
            out.append(FWD | RIGHT)
        elif p < 46:
            out.append(BACK)
        else:
            out.append(0)
    return out


w = WadFile.from_path(str(ROOT / args.wad))
art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
rm = ReferenceModel(Config())
cmap = bake_bsp(w, "E1M1")
dr = [t for t in w.things("E1M1") if rm.sprite_art(art, t.type, {}) is not None]
bkd = baked_thing_mask(rm, cmap, dr, MONSTER_TYPES)
NVIS = len(vanishable_slots(dr, bkd, VANISHABLE_TYPES))
RT = [t for t, b in zip(dr, bkd) if not b]
BINDS = encode_bindings([rm.point_in_subsector(cmap, t.x, t.y) for t in RT])
THINGS = encode_things([(t.x << 16, t.y << 16) for t in RT])
VIS = encode_visibility([1] * NVIS)
sp = spawn_state(w, "E1M1")
SPAWN = (_signed(sp.x, 32) & 0xFFFFFFFF, _signed(sp.y, 32) & 0xFFFFFFFF, sp.angle)


def wire(state, keys):
    return encode_feed(state[0], state[1], state[2], keys) + THINGS + BINDS + VIS


class PlayScreen(StreamScreen):
    """A device that builds the next frame's wire from the state the PROGRAM just echoed."""

    def __init__(self, keys, **kw):
        super().__init__(stdin=b"", **kw)
        self.keys = list(keys)
        self.frames = []
        self.states = [SPAWN]
        self._inp = wire(SPAWN, self.keys[0]) if self.keys else b""
        self.sent = 1

    def read_bit(self):
        if self._in_bits == 0 and not self._inp:
            if self.sent >= len(self.keys):
                raise IOReadOnEOF("play: script exhausted")
            st = self.state if self.state else self.states[-1]
            self.states.append(st)
            self._inp = wire(st, self.keys[self.sent])
            self.sent += 1
        return super().read_bit()

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


def load(fjm):
    r = FjmRunner(Path(fjm))
    assert r.native, "needs the native engine"
    return r


def image(r):
    c = _fjcore.Memory(r.width, flat_max_words=r.flat_max_words)
    for s, n in r._segments:
        c.add_segment(s, n)
    for st, v in r._runs:
        c.set_words(st, v)
    return c


def sgn32(v):
    return v - (1 << 32) if v >= (1 << 31) else v


KEYS = key_script(args.frames)
print("PLAYING %d frames on %s" % (args.frames, Path(args.loop_fjm).name), flush=True)
t0 = time.perf_counter()
rl = load(args.loop_fjm)
core = image(rl)
scr = PlayScreen(KEYS, n_things=len(RT))
scr.attach_memory(NativeDeviceMemory(core, rl.width))
_c, ops, _e, _l, _p = core.run(scr.read_bit, scr.write_bit, IOReadOnEOF, last_ops_length=0)
frames = list(scr.frames)
states = list(scr.states)
del core, scr, rl
dt = time.perf_counter() - t0
print("  ONE run: %s ops, %d frames, %.1fs" % (format(ops, ","), len(frames), dt), flush=True)

ok = len(frames) == args.frames
print("  frame count %d == %d ?  %s" % (len(frames), args.frames, "ok" if ok else "!! FAIL"))

pos = [(sgn32(s[0]) / 65536.0, sgn32(s[1]) / 65536.0) for s in states]
dist = sum(((pos[i + 1][0] - pos[i][0]) ** 2 + (pos[i + 1][1] - pos[i][1]) ** 2) ** 0.5
           for i in range(len(pos) - 1))
uniq_pos = len({(round(x, 3), round(y, 3)) for x, y in pos})
uniq_ang = len({s[2] for s in states})
print("  CONTROL (the player really moved): %.0f map units travelled, %d distinct positions, "
      "%d distinct angles" % (dist, uniq_pos, uniq_ang))
moved = dist > 500 and uniq_pos > args.frames // 4 and uniq_ang > 3
ok = ok and moved
print("     %s" % ("ok" if moved else "!! FAIL -- the script never left the spawn"))
uniq_frames = len(set(frames))
print("  CONTROL (vacuity): %d distinct pictures of %d" % (uniq_frames, len(frames)))
ok = ok and uniq_frames > len(frames) // 2
print("  start (%.1f, %.1f)   end (%.1f, %.1f)" % (pos[0][0], pos[0][1], pos[-1][0], pos[-1][1]))

print("  replaying the SAME %d states on the old binary, one frame per run ..." % len(states),
      flush=True)
ro = load(args.old_fjm)
bad = []
t1 = time.perf_counter()
for k, st in enumerate(states):
    c2 = image(ro)
    s2 = StreamScreen(stdin=wire(st, KEYS[k]), n_things=len(RT))
    s2.attach_memory(NativeDeviceMemory(c2, ro.width))
    c2.run(s2.read_bit, s2.write_bit, IOReadOnEOF, last_ops_length=0)
    if bytes(s2.pixel_indices) != frames[k]:
        d = sum(1 for a, b in zip(bytes(s2.pixel_indices), frames[k]) if a != b)
        bad.append((k, d))
    del c2, s2
    if (k + 1) % 25 == 0:
        print("     %d/%d (%.0fs)" % (k + 1, len(states), time.perf_counter() - t1), flush=True)
print("  BYTE-EXACT vs the old binary: %d/%d frames  %s"
      % (len(frames) - len(bad), len(frames), "ok" if not bad else "!! " + str(bad[:5])))
ok = ok and not bad

if args.png_every:
    d = Path(args.png_dir)
    d.mkdir(parents=True, exist_ok=True)
    try:
        from doomfj.texturecompiler import palette_rgb
        pal = palette_rgb(WadFile.from_path(str(ROOT / "assets/freedoom1.wad")))
    except Exception:
        pal = None
    n = 0
    for k in range(0, len(frames), args.png_every):
        raw = frames[k]
        wpx, hpx = 160, 100
        if pal:
            rows = b"".join(bytes(v for i in range(wpx) for v in pal[raw[y * wpx + i]][:3])
                            for y in range(hpx))
            (d / ("frame_%03d.ppm" % k)).write_bytes(("P6\n%d %d\n255\n" % (wpx, hpx)).encode()
                                                     + rows)
        else:
            (d / ("frame_%03d.raw" % k)).write_bytes(raw)
        n += 1
    print("  wrote %d frame images to %s" % (n, d))

print("")
print("M1 PLAYABILITY: %s" % ("PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
