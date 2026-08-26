"""M3 GATE -- the menu and the world, in ONE run, chosen by a persisted cell.

    python scratchpad/m3_gate.py [--fjm build/doom_e1m1_menu.fjm]
    python scratchpad/m3_gate.py --selftest        # R9: the negative control

The binary boots into the MENU (`mode` bakes to 1). Enter toggles it. So one run has to produce
two entirely different kinds of frame from the same program, and every one of them is compared:

  * menu frames against `doomfj.menu.pixels()` -- the oracle side of the generator fj emits from;
  * world frames against `ReferenceModel.render_wall_frame` at the state the sim reached.

THREE THINGS THIS GATE EXISTS TO CATCH, none of which a single-frame check would see:

  1. THE MODE MUST PERSIST. It is excluded from the M1 restore set (build.STANDALONE_PERSIST); if
     that exclusion were missing, `mode` would snap back to 1 every frame and the game would show
     the menu forever, one frame after appearing to work.
  2. THE MENU MUST NOT MOVE THE PLAYER. The branch sits before the sim, so menu frames skip the
     tic entirely -- which is what makes leaving the menu resume where you were. The script walks,
     opens the menu, holds a key WHILE IN THE MENU, and requires the player not to have moved.
  3. THE TOGGLE MUST EDGE-TRIGGER. A press delivers a down AND an up event; toggling on both
     would land back where it started and the menu would never open at all.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

from doomfj.config import Config                                          # noqa: E402
from doomfj.fastrun import FjmRunner, _fjcore                             # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.menu import palette_colours, pixels                           # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.wall_renderer import DEFAULT_MENU, STANDALONE_POLLS           # noqa: E402
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,   # noqa: E402
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen            # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.interpreter.io_devices.pygame_window import PcIO                 # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402

ENTER, K_FWD = 0x0D, 0x77

# (frame, poll, is_down, keycode). The binary boots into the menu, so frames 0-1 are menu frames
# with no input at all -- which is already control 1: if `mode` did not persist there would be
# nothing to persist it FROM, but if the RESET clobbered it these frames would still look right
# and frame 2 would go wrong.
SCRIPT = [
    (2, 0, True, ENTER), (2, 1, False, ENTER),      # -> world from frame 2
    (3, 0, True, K_FWD),                            # walk
    (6, 0, True, ENTER), (6, 1, False, ENTER),      # -> menu from frame 6, W STILL HELD
    (9, 0, True, ENTER), (9, 1, False, ENTER),      # -> world from frame 9; must resume in place
    (11, 0, False, K_FWD),
]
FRAMES = 13
MENU_FRAMES = {0, 1, 6, 7, 8}                        # everything else renders the world


class Recording(InMemoryScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(bytes(self.pixel_indices))


class Stopper(KeyboardIO):
    """the standalone program has no end (KeyboardIO never EOFs on an idle poll), so the gate
    closes its own input once it has the frames it asked for -- see scratchpad/m5_gate.py."""

    def __init__(self, source, screen, limit):
        super().__init__(source)
        self._screen, self._limit = screen, limit

    def read_bit(self):
        if len(self._screen.frames) >= self._limit:
            raise IOReadOnEOF("the gate has its %d frames" % self._limit)
        return super().read_bit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu.fjm")
    ap.add_argument("--wad", default="tests/fixtures/freedoom_e1m1.wad")
    ap.add_argument("--map", default="E1M1")
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--selftest", action="store_true",
                    help="R9: claim every frame is a world frame; the gate must FAIL")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    cfg = Config()
    rm = ReferenceModel(cfg)
    scene = build_scene(mw, mw, args.map)
    colours = palette_colours(bytes(b for rgb in mw.playpal(0) for b in rgb))
    menu_want = bytes(pixels(cfg.VIEW_W, cfg.VIEW_H, DEFAULT_MENU, 2, colours))
    render_kw = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                     near_steps=True, stack_steps=True, things=True, sprite_wad=art, degrade=True)

    events = [KeyEvent(f * STANDALONE_POLLS + p, d, c) for f, p, d, c in SCRIPT]
    print("fjm    : %s" % args.fjm)
    print("menu   : %s   colours bg=%d text=%d hi=%d" % (DEFAULT_MENU, *colours))
    print("script : boot in menu -> enter@2 -> walk -> enter@6 (W held) -> enter@9 -> stop")

    runner = FjmRunner(ROOT / args.fjm)
    assert runner.native, "the M3 gate needs the native engine"
    core = _fjcore.Memory(runner.width, flat_max_words=runner.flat_max_words)
    for seg, n in runner._segments:
        core.add_segment(seg, n)
    for start, vals in runner._runs:
        core.set_words(start, vals)
    screen = Recording()
    io = PcIO(screen, Stopper(ScriptedKeyEventSource(events), screen, FRAMES))
    io.attach_memory(NativeDeviceMemory(core, runner.width))
    _c, ops, _e, _l, _p = core.run(io.read_bit, io.write_bit, IOReadOnEOF, last_ops_length=0)
    got = list(screen.frames)
    del core, screen, io, runner
    print("  {:,} ops -> {} frames".format(ops, len(got)))

    # the oracle's own mirror of the mode machine: the same edge rule kb.poll implements
    held, mode, states = False, 1, []
    state = spawn_state(mw, args.map)
    pending, i = sorted(events, key=lambda e: e.tic), 0
    for f in range(FRAMES):
        for tic in range(f * STANDALONE_POLLS, (f + 1) * STANDALONE_POLLS):
            while i < len(pending) and pending[i].tic <= tic:
                ev = pending[i]; i += 1
                if ev.keycode == ENTER:
                    if ev.is_down:
                        mode ^= 1                       # DOWN edge only
                elif ev.keycode == K_FWD:
                    held = ev.is_down
        if mode == 0:                                   # a menu frame skips the tic entirely
            state = rm.step_sim(state, {"forward": held, "back": False,
                                        "turn_left": False, "turn_right": False}, scene=scene)
        states.append((mode, state))

    ok, menus, worlds, moved = True, 0, 0, 0
    previous = None
    for f in range(min(len(got), FRAMES)):
        mode, state = states[f]
        is_menu = mode == 1
        assert is_menu == (f in MENU_FRAMES), "the gate's own mirror disagrees with MENU_FRAMES"
        if args.selftest:
            is_menu = False                             # THE NEGATIVE CONTROL
        if is_menu:
            want, kind = menu_want, "MENU "
            menus += 1
        else:
            want = bytes(rm.render_wall_frame(SimState(state.x, state.y, state.angle, args.map),
                                              scene, **render_kw))
            kind = "world"
            worlds += 1
        same = got[f] == want
        ok &= same
        pos = (_signed(state.x, 32) / 65536, _signed(state.y, 32) / 65536)
        moved += previous is not None and pos != previous
        previous = pos
        diff = sum(1 for a, b in zip(got[f], want) if a != b)
        print("  frame %2d %s (%8.3f,%8.3f)  %s"
              % (f, kind, pos[0], pos[1],
                 "BYTE-EXACT" if same else "!! %d px DIFFER" % diff), flush=True)
        if not same:
            print("  -- stopping: once a frame is wrong the later ones compare nothing useful")
            break

    # frames 6-8 are menu frames with W HELD. If the branch ran after the sim, or the menu did not
    # skip the tic, the player would have walked through them.
    held_menu = [states[f][1] for f in (6, 7, 8)]
    frozen = len({(s.x, s.y, s.angle) for s in held_menu}) == 1
    print("")
    print("  CONTROL: menu frames %d, world frames %d, frames that moved the player %d"
          % (menus, worlds, moved))
    print("  CONTROL: the player did NOT move during the 3 menu frames with W held: %s"
          % ("ok" if frozen else "!! IT MOVED"))
    print("  CONTROL: distinct pictures: %d of %d" % (len(set(got[:FRAMES])), min(len(got), FRAMES)))
    vacuous = menus < 2 or worlds < 2 or moved < 2 or not frozen
    if vacuous:
        print("  !! VACUOUS -- this script does not exercise the mode machine")

    ok = ok and not vacuous and len(got) >= FRAMES
    print("")
    if args.selftest:
        print("SELFTEST (every frame claimed to be a world frame): "
              + ("FAIL -- the gate did not notice" if ok else "PASS -- the gate rejected it"))
        return 0 if not ok else 1
    print("M3 GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
