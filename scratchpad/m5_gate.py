"""M5 GATE -- the STANDALONE binary, driven only by the keyboard device, against the oracle.

    python scratchpad/m5_gate.py --fjm build/doom_e1m1_std.fjm [--frames 24]
    python scratchpad/m5_gate.py --selftest            # R9: the negative control

What makes this different from every gate before it: NOTHING IS FED IN. The hosted gates hand the
program a viewpoint per frame and compare the picture. Here the program starts at the map's player
start (baked into `viewx`/`viewy`/`viewangle`), keeps that state across M1's reset, and the only
thing crossing the wire is KEY EVENTS -- so a single wrong bit in the sim, the reset's persist set
or the keyboard decode sends the trajectory somewhere the oracle never goes, and every later frame
differs. That is the point: this gate is CUMULATIVE, and a one-ulp drift on frame 0 is visible.

The io device is the STOCK `PcIO` the `fj` CLI's `--io pc` mode builds -- a scripted keyboard in,
a plain `InMemoryScreen` out -- so what this certifies is the same object a human runs, not a
repo-local lab device. `InMemoryScreen` understands the 0x0B column-run frame as of M5a.

THE TIC CLOCK IS THE CONTRACT. One `KeyboardIO` poll is one tic, the frame runs
`STANDALONE_POLLS` of them, and an event is delivered at the first poll whose tic has reached it.
The mirror below re-implements exactly that from the device's own docstring, so the two sides are
independent: if the emitter changed the poll count and this did not, the trajectories part.

R9 negative control (`--selftest`): the same run with ONE frame's oracle picture corrupted; the
gate must FAIL. A gate that cannot fail is not evidence.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from doomfj.build import STANDALONE_PERSIST                                    # noqa: E402
from doomfj.config import Config                                               # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                                  # noqa: E402
from doomfj.fixedpoint import _signed                                          # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState, build_scene,     # noqa: E402
                                    spawn_state)
from doomfj.wad import WadFile                                                 # noqa: E402
from doomfj.wall_renderer import STANDALONE_POLLS                              # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,  # noqa: E402
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen            # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.interpreter.io_devices.pygame_window import PcIO                 # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402

K_FWD, K_BACK, K_LEFT, K_RIGHT = 0x77, 0x73, 0x61, 0x64
KEY_NAMES = ("forward", "back", "turn_left", "turn_right")
BINDING = {K_FWD: "forward", 0x80: "forward", K_BACK: "back", 0x81: "back",
           K_LEFT: "turn_left", 0x82: "turn_left", K_RIGHT: "turn_right", 0x83: "turn_right"}

# (frame, poll-within-frame, is_down, keycode). Chosen so the trajectory turns, WALKS INTO A
# WALL, backs off and uses the arrow bindings -- a script that only crossed open floor would leave
# the collision half of the sim untested, and for the first 24-frame version of this script it did
# (`frames COLLISION changed: 0`). The four opening turns aim the player at geometry:
# scratchpad/_m2_findwall.py searched every heading from the spawn with the ORACLE alone and found
# turn-right x4 blocks soonest, at frame 8.
SCRIPT = [
    (0, 0, True, K_RIGHT),                  # 4 turns right: aim at a wall
    (4, 0, False, K_RIGHT),
    (4, 1, True, K_FWD),                    # ... and walk into it -- collision binds from frame 8
    (12, 0, False, K_FWD),
    (12, 1, True, K_BACK),                  # back off
    (15, 0, False, K_BACK),
    (15, 1, True, 0x82),                    # the ARROW binding for turn-left, same flag as 'a'
    (19, 0, False, 0x82),
    (19, 1, True, 0x80),                    # ... and the arrow for forward
    (23, 0, False, 0x80),
]


class Recording(InMemoryScreen):
    """the stock device plus a snapshot of every PRESENTED frame."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


class Stopper(KeyboardIO):
    """the keyboard, but it EOFs once the screen has presented enough frames.

    ⚠ THE STANDALONE PROGRAM HAS NO END. Every hosted gate before this one terminated because the
    WIRE ran out -- the program read past the last frame's state and hit EOF. There is no wire here
    and `KeyboardIO` never EOFs on an idle poll (deliberately: a game must not die because nobody
    pressed a key), so the binary renders frames until something stops it. In a window that is
    closing the window; headless it is this. Without it the gate does not fail, it never returns --
    which is exactly what the first run of it did.
    """

    def __init__(self, event_source, screen, limit):
        super().__init__(event_source)
        self._screen, self._limit = screen, limit

    def read_bit(self):
        if len(self._screen.frames) >= self._limit:
            raise IOReadOnEOF("the gate has the %d frames it asked for" % self._limit)
        return super().read_bit()


SMOKE = False          # --smoke: no key script at all, so frame 0 IS the spawn viewpoint


def events(frames):
    if SMOKE:
        return []
    return [KeyEvent(f * STANDALONE_POLLS + p, d, c) for f, p, d, c in SCRIPT if f < frames]


def held_per_frame(frames):
    """the DEVICE's delivery rule, re-implemented: one event per poll, due once the tic clock
    reaches it. Returns the key dict the sim sees on each frame."""
    pending = sorted(events(frames), key=lambda e: e.tic)
    held = {name: False for name in KEY_NAMES}
    out, i = [], 0
    for tic in range(frames * STANDALONE_POLLS):
        if i < len(pending) and pending[i].tic <= tic:
            event = pending[i]
            i += 1
            name = BINDING.get(event.keycode)
            if name is not None:
                held[name] = event.is_down
        if tic % STANDALONE_POLLS == STANDALONE_POLLS - 1:
            out.append(dict(held))
    return out


def run(fjm, frames):
    runner = FjmRunner(Path(fjm))
    assert runner.native, "the M5 gate needs the native engine"
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    screen = Recording()
    keyboard = Stopper(ScriptedKeyEventSource(events(frames)), screen, frames)
    io = PcIO(screen, keyboard)                 # the SAME composition `fj --io pc` builds
    io.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
    out = (list(screen.frames), ops)
    del core, screen, io, runner
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_std.fjm")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    # 24 is what is CERTIFIED: the opening 4 turns aim at a wall, frames 8-10 are blocked,
    # and the tail covers the arrow bindings. Fewer than 12 stops short of the collision.
    ap.add_argument("--frames", type=int, default=24)
    ap.add_argument("--selftest", action="store_true",
                    help="R9: corrupt one oracle frame; the gate must FAIL")
    ap.add_argument("--smoke", action="store_true",
                    help="the no-loop build: ONE frame at the spawn, no keys, vs the oracle")
    args = ap.parse_args()
    if args.smoke:
        args.frames = 1

    global SMOKE
    SMOKE = args.smoke

    print("fjm    : %s" % args.fjm)
    print("persist: %s" % ", ".join(STANDALONE_PERSIST))
    print("polls  : %d per frame  ->  %d tics over %d frames"
          % (STANDALONE_POLLS, STANDALONE_POLLS * args.frames, args.frames))

    wad = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    rm = ReferenceModel(Config())
    scene = build_scene(wad, wad, args.map)
    render_kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                     near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

    print("running (one process, %d frames)..." % args.frames, flush=True)
    got, ops = run(args.fjm, args.frames)
    print("  {:,} ops -> {} frame(s) presented".format(ops, len(got)))
    if len(got) < args.frames:
        print("  !! the program presented FEWER frames than asked for -- the loop stopped early")

    keys_by_frame = held_per_frame(args.frames)
    state = spawn_state(wad, args.map)
    print("  spawn: (%.3f, %.3f) ang=%#010x"
          % (_signed(state.x, 32) / 65536, _signed(state.y, 32) / 65536, state.angle))

    ok, moved, turned, blocked = True, 0, 0, 0
    for i in range(min(len(got), args.frames)):
        previous = state
        # the tic runs BEFORE the render, exactly as the program orders it (M14-c)
        state = rm.step_sim(previous, keys_by_frame[i], scene=scene)
        moved += (state.x, state.y) != (previous.x, previous.y)
        turned += state.angle != previous.angle
        # did COLLISION actually change this tic's outcome? Without this the script could walk in
        # open space for every frame and say nothing about the collision half of the sim.
        free = rm.step_sim(previous, keys_by_frame[i])
        blocked += (free.x, free.y) != (state.x, state.y)
        want = bytes(rm.render_wall_frame(SimState(state.x, state.y, state.angle, args.map),
                                          scene, **render_kw))
        if args.selftest and i == args.frames // 2:
            want = bytes([b ^ 1 for b in want])        # THE NEGATIVE CONTROL
        same = got[i] == want
        ok &= same
        diff = sum(1 for a, b in zip(got[i], want) if a != b)
        print("  frame %2d keys=%s -> (%9.3f,%9.3f) ang=%#010x  %s"
              % (i, "".join("1" if keys_by_frame[i][k] else "0" for k in KEY_NAMES),
                 _signed(state.x, 32) / 65536, _signed(state.y, 32) / 65536, state.angle,
                 "BYTE-EXACT" if same else "!! %d px DIFFER" % diff), flush=True)
        if not same:
            print("  -- stopping: once the trajectories part, later frames compare nothing useful")
            break

    # THE VACUITY CONTROLS. A run where the player never moved and never turned would compare a
    # dozen copies of one picture and pass while proving nothing about the keyboard or the sim.
    print("")
    print("  CONTROL: frames that MOVED the player: %d   frames that TURNED: %d   "
          "frames COLLISION changed: %d" % (moved, turned, blocked))
    distinct = len(set(got[:args.frames]))
    print("  CONTROL: distinct pictures presented: %d of %d"
          % (distinct, min(len(got), args.frames)))
    # --smoke makes a DIFFERENT and much weaker claim -- "the emit half is right and the program
    # presents the spawn frame" -- on a build with no loop and no keys, so the controls that
    # certify the sim do not apply and are not silently waived: they are not claimed.
    # COLLISION is in the list because it was NOT covered when this gate first passed: 24 frames
    # of open floor, every one byte-exact, and `frames COLLISION changed: 0`. A gate that cannot
    # tell you which half of the sim it exercised is not telling you much.
    vacuous = (not args.smoke) and (moved < 2 or turned < 2 or distinct < 3 or blocked < 1)
    if vacuous:
        print("  !! VACUOUS -- this script does not exercise the sim; fix SCRIPT, not the verdict")
    if args.smoke:
        print("  (--smoke: ONE spawn frame, no keys -- this proves the EMIT half only. The sim,")
        print("   the keyboard and the persisted state are certified by a full run, not by this.)")
        if len(got) != 1:
            print("  !! a no-loop build must present exactly 1 frame, got %d" % len(got))

    ok = ok and not vacuous and (len(got) == 1 if args.smoke else len(got) >= args.frames)
    print("")
    if args.selftest:
        print("SELFTEST (one oracle frame corrupted): "
              + ("FAIL -- the gate did not notice" if ok else "PASS -- the gate rejected it"))
        return 0 if not ok else 1
    print("M5 GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
