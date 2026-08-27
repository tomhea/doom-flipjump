"""Open a REAL window and play the standalone binary in it, so a human (or a screenshot) can look.

This is the `fj --io pc` composition -- `PcIO(InteractiveScreen, KeyboardIO)` on one PygameWindow --
running the actual standalone .fjm. The window, SDL, the palette upload and the present path are
all real; the only substitution is the INPUT SOURCE: a scripted key list instead of a physical
keyboard, because Windows' foreground lock stops a background process from focusing a window and
SDL discards key events for an unfocused one.

It holds each frame on screen for --hold seconds so an external capture can see it.

    python scratchpad/play_window.py --frames 8 --hold 2.0
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.fastrun import FjmRunner, _fjcore                                  # noqa: E402
from doomfj.wall_renderer import STANDALONE_POLLS                             # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,  # noqa: E402
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.interpreter.io_devices.pygame_window import (InteractiveScreen,  # noqa: E402
                                                           PcIO, PygameWindow)
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402

ENTER, W, A, D, S = 0x0D, 0x77, 0x61, 0x64, 0x73
SCRIPT = [(2, 0, True, ENTER), (2, 1, False, ENTER),        # menu -> world
          (3, 0, True, W),                                   # walk
          (7, 0, False, W), (7, 1, True, D),                 # turn right
          (10, 0, False, D), (10, 1, True, W),               # walk again
          (14, 0, False, W), (14, 1, True, A),               # turn left
          (17, 0, False, A), (17, 1, True, W),
          (21, 0, False, W)]

ap = argparse.ArgumentParser()
ap.add_argument("--fjm", default="build/doom_e1m1_menu.fjm")
ap.add_argument("--frames", type=int, default=8)
ap.add_argument("--hold", type=float, default=2.0, help="seconds to leave each frame on screen")
ap.add_argument("--scale", type=int, default=4)
ap.add_argument("--dump", default=None, help="dir to save SDL's own surface per frame")
args = ap.parse_args()


class Held(InteractiveScreen):
    """present, then HOLD, so an external screenshot can catch each frame."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.n = 0

    def _present(self):
        super()._present()
        self.n += 1
        # report WHAT was presented, so "the window looks black" can be told apart from "fj
        # emitted a blank frame" -- two completely different bugs that look identical on screen.
        import collections
        hist = collections.Counter(self.pixel_indices).most_common(4)
        print("  frame %d presented  %d distinct colours, top: %s"
              % (self.n, len(set(self.pixel_indices)), hist), flush=True)
        # save what SDL ITSELF has on the display surface, right after the flip. That separates
        # "the program emitted a blank frame" (the histogram above) from "SDL did not paint it"
        # from "the external screenshot is wrong" -- three bugs that look identical on screen.
        if args.dump:
            import pygame
            pygame.image.save(self.window._screen_surface,
                              "%s/sdl_frame%02d.png" % (args.dump, self.n))
        time.sleep(args.hold)


class Stopper(KeyboardIO):
    def __init__(self, source, screen, limit):
        super().__init__(source)
        self._screen, self._limit = screen, limit

    def read_bit(self):
        if self._screen.n >= self._limit:
            raise IOReadOnEOF("done")
        return super().read_bit()


print("loading %s ..." % args.fjm, flush=True)
runner = FjmRunner(ROOT / args.fjm)
core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
for seg, n in runner._segments:
    core.add_segment(seg, n)
for start, vals in runner._runs:
    core.set_words(start, vals)

window = PygameWindow(title="FlipJump DOOM")
screen = Held(window=window)
events = [KeyEvent(f * STANDALONE_POLLS + p, d, c) for f, p, d, c in SCRIPT]
io = PcIO(screen, Stopper(ScriptedKeyEventSource(events), screen, args.frames))
io.attach_memory(NativeDeviceMemory(core, runner.width))
print("running -- window should be open", flush=True)
try:
    _c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
    print("%s ops, %d frames" % (format(ops, ","), screen.n), flush=True)
except KeyboardInterrupt:
    print("window closed", flush=True)
time.sleep(2)
window.close()
