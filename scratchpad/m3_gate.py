"""M3 GATE -- the menu and the world, in ONE run, chosen by persisted cells.

    python scratchpad/m3_gate.py [--fjm build/doom_e1m1_menu.fjm]
    python scratchpad/m3_gate.py --selftest          # R9: every frame claimed to be a world frame
    python scratchpad/m3_gate.py --selftest-skill    # R9 (M7 P1.5): the oracle starts the WRONG skill

The binary boots into the MAIN MENU (`mode` bakes to 1, `menu_scr` to 0). M7 P1.5 gave the menu a
skill screen (docs/gp-skill-menu.md; `doomfj.menu.menu_step` is the rules' oracle side): in the
world esc or enter opens the main menu; there esc resumes the world and enter opens the skill
screen; there w / s move the highlight (clamped), esc goes back, and enter starts the highlighted
skill -- the level restarts at that skill's start and the same frame is a world frame. So one run
produces two entirely different kinds of frame from the same program, and every one is compared:

  * menu frames against `doomfj.menu.pixels()` for the screen the rules say is up -- the main menu,
    or the skill screen with its highlight -- the oracle side of the generator fj emits from;
  * world frames against `ReferenceModel.render_wall_frame` at the state the sim reached, hiding
    what the skill being played does not spawn (`things.skill_hidden`; the boot skill until a NEW
    GAME picks another).

THE THINGS THIS GATE EXISTS TO CATCH, none of which a single-frame check would see:

  1. THE MODE MUST PERSIST. It is excluded from the M1 restore set (build.STANDALONE_PERSIST); if
     that exclusion were missing, `mode` would snap back to 1 every frame and the game would show
     the menu forever, one frame after appearing to work. M7 P1.5: `menu_scr` and `menu_sel` too --
     a skill screen that reset every frame could never be left, a highlight never moved.
  2. THE MENU MUST NOT MOVE THE PLAYER. The branch sits before the sim, so menu frames skip the
     tic entirely -- which is what makes leaving the menu resume where you were. The script walks,
     opens the menu, holds a key WHILE IN THE MENU, and requires the player not to have moved.
  3. THE EVENTS MUST EDGE-TRIGGER. A press delivers a down AND an up event; acting on both would
     act twice (M3's toggle landed back where it started; a highlight would move two rows).
  4. NEW GAME MUST RESTART AT THE CHOSEN SKILL (M7 P1.5). Walked away from the spawn first, each
     NEW GAME frame must be the spawn view with THAT skill's things -- and the three skills' spawn
     views differ (CONTROL), so a restart that loaded another skill's lists or flags is caught.
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
from doomfj.menu import MENU_KEYS, menu_step, palette_colours, pixels     # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.things import skill_hidden                                    # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.reference_model import GAME_RENDER_KW                          # noqa: E402
from doomfj.wall_renderer import (BOOT_SKILL, DEFAULT_MENU,               # noqa: E402
                                  DEFAULT_MENU_SELECTED, SKILL_MENU, SKILL_MENU_FIRST, SKILLS,
                                  STANDALONE_POLLS)
from flipjump.interpreter.io_devices.KeyboardIO import (KeyboardIO, KeyEvent,   # noqa: E402
                                                        ScriptedKeyEventSource)
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen            # noqa: E402
from flipjump.interpreter.io_devices.device_memory import NativeDeviceMemory   # noqa: E402
from flipjump.interpreter.io_devices.pygame_window import PcIO                 # noqa: E402
from flipjump.utils.exceptions import IOReadOnEOF                              # noqa: E402

ENTER, ESC, K_FWD, K_BACK = 0x0D, 0x1B, 0x77, 0x73
SKILL_NAMES = {s: n for s, n in zip(SKILLS, ("easy", "medium", "hard"))}


def press(f, key):
    """a key pressed and released within frame f's first two polls"""
    return [(f, 0, True, key), (f, 1, False, key)]


# (frame, poll, is_down, keycode). The binary boots into the menu, so frames 0-1 are menu frames
# with no input at all -- which is already control 1: if `mode` did not persist there would be
# nothing to persist it FROM, but if the RESET clobbered it these frames would still look right
# and frame 2 would go wrong.
SCRIPT = (
    press(2, ESC)                              # -> the world, at the boot skill's level start
    + [(3, 0, True, K_FWD)]                    # walk
    + press(6, ENTER)                          # -> the main menu from frame 6, W STILL HELD
    + press(9, ESC)                            # -> the world from frame 9; must resume in place
    + [(11, 0, False, K_FWD)]
    + press(12, ENTER)                         # -> the main menu
    + press(13, ENTER)                         # -> the skill screen: the boot skill highlighted
    + press(14, K_BACK)                        # down: clamped at the last skill
    + press(15, K_FWD) + press(16, K_FWD)      # up, up: medium, then easy
    + press(17, K_FWD)                         # up: clamped at the first skill
    + press(18, ESC)                           # -> back to the main menu
    + press(19, ENTER)                         # -> the skill screen, easy STILL highlighted
    + press(20, ENTER)                         # NEW GAME at easy: its level start, this frame
    + press(22, ENTER) + press(23, ENTER)      # the main menu, the skill screen (easy)
    + press(24, K_BACK)                        # down: medium
    + press(25, ENTER)                         # NEW GAME at medium
    + press(27, ENTER) + press(28, ENTER)      # the main menu, the skill screen (medium)
    + press(29, K_BACK)                        # down: hard
    + press(30, ENTER)                         # NEW GAME at hard
)
FRAMES = 32
WITH_W_HELD = (6, 7, 8)                        # menu frames while W is held
NEW_GAMES = (20, 25, 30)                       # easy, medium, hard


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
    ap.add_argument("--selftest-skill", action="store_true",
                    help="R9 (M7 P1.5): the oracle starts the NEXT skill at every NEW GAME; the "
                         "gate must FAIL")
    args = ap.parse_args()

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    cfg = Config()
    rm = ReferenceModel(cfg)
    scene = build_scene(mw, mw, args.map)
    colours = palette_colours(bytes(b for rgb in mw.playpal(0) for b in rgb))
    screens = {(0, None): bytes(pixels(cfg.VIEW_W, cfg.VIEW_H, DEFAULT_MENU, DEFAULT_MENU_SELECTED,
                                       colours))}
    for k in range(len(SKILLS)):
        screens[(1, k)] = bytes(pixels(cfg.VIEW_W, cfg.VIEW_H, SKILL_MENU, SKILL_MENU_FIRST + k,
                                       colours))
    render_kw = dict(GAME_RENDER_KW, sprite_wad=art)
    hidden = {s: skill_hidden(rm, mw.things(args.map), art, s) for s in SKILLS}

    events = [KeyEvent(f * STANDALONE_POLLS + p, d, c) for f, p, d, c in SCRIPT]
    print("fjm    : %s" % args.fjm)
    print("menu   : %s   colours bg=%d text=%d hi=%d" % (DEFAULT_MENU, *colours))
    print("skills : %s -- hidden %s; the boot skill is %s"
          % (SKILL_MENU[SKILL_MENU_FIRST:], [len(hidden[s]) for s in SKILLS],
             SKILL_NAMES[BOOT_SKILL]))
    print("script : boot in menu -> esc@2 -> walk -> enter@6 (W held) -> esc@9 -> the skill "
          "screen @13, clamp both ends, back, NEW GAME at easy@20, medium@25, hard@30")

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

    # the oracle's mirror: the device's delivery rule (one event per poll, due once the tic clock
    # reaches it) feeding the menu's rules, and a menu frame skipping the tic
    held = {"forward": False, "back": False}
    mode, scr, sel, skill = 1, 0, SKILLS.index(BOOT_SKILL), BOOT_SKILL
    spawn = spawn_state(mw, args.map)
    state, rows = spawn, []
    pending, i = sorted(events, key=lambda e: e.tic), 0
    for f in range(FRAMES):
        ev = set()
        for tic in range(f * STANDALONE_POLLS, (f + 1) * STANDALONE_POLLS):
            if i < len(pending) and pending[i].tic <= tic:
                e = pending[i]
                i += 1
                if e.is_down and e.keycode in MENU_KEYS:
                    ev.add(MENU_KEYS[e.keycode])
                name = {K_FWD: "forward", K_BACK: "back"}.get(e.keycode)
                if name:
                    held[name] = e.is_down
        mode, scr, sel, ng = menu_step(mode, scr, sel, ev)
        before = state
        if ng is not None:
            # NEW GAME: the chosen skill's level start, then this frame's tic. THE R9 CONTROL
            # starts the next skill instead -- the gate must see it.
            skill = SKILLS[(ng + 1) % len(SKILLS)] if args.selftest_skill else SKILLS[ng]
            state = spawn
        if mode == 0:
            state = rm.step_sim(state, dict(held, turn_left=False, turn_right=False), scene=scene)
        rows.append({"mode": mode, "scr": scr, "sel": sel, "skill": skill, "state": state,
                     "ng": ng, "before": before})

    ok, menus, worlds, moved, oracle_ng, first_bad = True, 0, 0, 0, {}, None
    screens_seen = set()
    previous = None
    for f in range(min(len(got), FRAMES)):
        row = rows[f]
        state = row["state"]
        is_menu = row["mode"] == 1
        if args.selftest:
            is_menu = False                             # THE NEGATIVE CONTROL
        if is_menu:
            key = (0, None) if row["scr"] == 0 else (1, row["sel"])
            want = screens[key]
            kind = "MENU  main   " if row["scr"] == 0 else "MENU  skill %d" % row["sel"]
            screens_seen.add(key)
            menus += 1
        else:
            want = bytes(rm.render_wall_frame(SimState(state.x, state.y, state.angle, args.map),
                                              scene, thing_hidden=hidden[row["skill"]],
                                              **render_kw))
            kind = "world %-7s" % SKILL_NAMES[row["skill"]]
            worlds += 1
            if row["ng"] is not None:
                oracle_ng[f] = want
        same = got[f] == want
        ok &= same
        pos = (_signed(state.x, 32) / 65536, _signed(state.y, 32) / 65536)
        moved += (not is_menu) and previous is not None and pos != previous
        previous = pos
        diff = sum(1 for a, b in zip(got[f], want) if a != b)
        print("  frame %2d %s (%8.3f,%8.3f)%s  %s"
              % (f, kind, pos[0], pos[1], "  NEW GAME" if row["ng"] is not None else "",
                 "BYTE-EXACT" if same else "!! %d px DIFFER" % diff), flush=True)
        if not same:
            first_bad = f
            print("  -- stopping: once a frame is wrong the later ones compare nothing useful")
            break

    # frames 6-8 are menu frames with W HELD. If the branch ran after the sim, or the menu did not
    # skip the tic, the player would have walked through them.
    held_menu = [rows[f]["state"] for f in WITH_W_HELD]
    frozen = len({(s.x, s.y, s.angle) for s in held_menu}) == 1
    walked = (rows[NEW_GAMES[0]]["before"].x, rows[NEW_GAMES[0]]["before"].y) != (spawn.x, spawn.y)
    reset = all((rows[f]["state"].x, rows[f]["state"].y, rows[f]["state"].angle)
                == (spawn.x, spawn.y, spawn.angle) for f in NEW_GAMES)
    # the three NEW GAME frames as the oracle drew them -- distinct only if the skills can be TOLD
    # APART at the spawn, which is what makes "each frame is byte-exact" mean "each is its skill's"
    told = len(oracle_ng) == len(NEW_GAMES) and len(set(oracle_ng.values())) == len(NEW_GAMES)
    print("")
    print("  CONTROL: menu frames %d, world frames %d, frames that moved the player %d"
          % (menus, worlds, moved))
    print("  CONTROL: the player did NOT move during the %d menu frames with W held: %s"
          % (len(WITH_W_HELD), "ok" if frozen else "!! IT MOVED"))
    print("  CONTROL: the screens shown: main menu %s, the skill screen at highlights %s of %d"
          % ("yes" if (0, None) in screens_seen else "!! no",
             sorted(k for m, k in screens_seen if m == 1), len(SKILLS)))
    print("  CONTROL: the first NEW GAME found the player walked away (%s), and every NEW GAME "
          "frame is the spawn view (%s)" % ("yes" if walked else "!! no", "yes" if reset else "!! no"))
    print("  CONTROL: the three skills' NEW GAME frames are pairwise distinct in the oracle: %s"
          % ("yes" if told else "!! no -- the skills cannot be told apart here"))
    print("  CONTROL: distinct pictures: %d of %d" % (len(set(got[:FRAMES])), min(len(got), FRAMES)))
    vacuous = (menus < 2 or worlds < 2 or moved < 2 or not frozen or not walked or not reset
               or len(screens_seen) != 1 + len(SKILLS) or not told)
    if vacuous and not (args.selftest or args.selftest_skill):
        print("  !! VACUOUS -- this script does not exercise the menu machine")

    ok = ok and not vacuous and len(got) >= FRAMES
    print("")
    if args.selftest or args.selftest_skill:
        # rejected for the RIGHT reason: the first wrong frame is the first one the mutation moves
        # (frame 0 is a menu frame; the first NEW GAME is the first frame drawn at a wrong skill)
        expect = 0 if args.selftest else NEW_GAMES[0]
        caught = first_bad == expect
        print("SELFTEST (%s): " % ("every frame claimed to be a world frame" if args.selftest else
                                   "the oracle starts the next skill at every NEW GAME")
              + ("PASS -- the gate rejected it at frame %d, where it must" % expect if caught else
                 "FAIL -- " + ("the gate did not notice" if first_bad is None else
                               "it failed at frame %d, not %d" % (first_bad, expect))))
        return 0 if caught else 1
    print("M3 GATE: " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
