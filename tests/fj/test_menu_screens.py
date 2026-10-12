"""M7 P3.4 -- the WHOLE menu block, run: `wall_renderer._menu_lines` -- the state machine, the producer
branch and every baked screen, the help screen among them -- driven frame by frame by the real
keyboard device and presented through the real screen device, against the oracle's side:
`doomfj.menu.menu_step` for the state, `wall_renderer.menu_screen_pixels` for the picture of a menu
frame (and the world stub's flat frame for a world one).

The tests beside it check the pieces apart: tests/fj/test_skill_menu.py the state machine alone (a
digit dump, no screens), tests/host/test_menu.py each screen's stream decoded on its own. What only
this one sees is the PRODUCER BRANCH -- the `if_flags` masks on `menu_scr` that pick which baked
screen a frame paints -- which P3.4 grew from four screens to seven. A mask bit wrong sends a state
to another state's picture, and every picture is still a perfect picture of SOMETHING.

R9: a mutant of the branch (the help and the HELP-highlighted main menu swapped) and an oracle whose
world help closes to the main menu must each be rejected, at the frame they first move.

P9 (the owner's play-test, 2026-10-10): the main menu's third item, EXIT -- one more baked screen (the main menu on
EXIT) and the HALT: enter on EXIT stops the program on that frame, before it presents anything, so the run presents
exactly the frames before it (`HALT_SCRIPT`). R9: the branch with the EXIT and the HELP highlights swapped, and the
halt replaced by "back to the menu", are each rejected.

P10 (the owner's play-test, 2026-10-12): `g_live`. The main menu is baked twice -- without a game (the boot menu) and
with RESUME over NEW GAME -- and RESUME highlighted once more: the tour below visits every one of the twelve pictures,
the boot half without a game and the rest after NEW GAME. LEVEL COMPLETE leaves on ANY key (here without a World: its
digit slots empty, `_menu_lines(stats=None)`; the stats' own frame is tests/fj/test_level_done_fj.py's).
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.interpreter.io_devices.pygame_window import PcIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import (ANY_KEY_EVENT, HELP_GAME_SCR, HELP_MENU_SCR, LEVEL_DONE_ENTER, LEVEL_DONE_SCR,
                         LEVEL_DONE_SCREENS, MAIN_EXIT_SCR, MAIN_HELP_SCR, MAIN_RESUME_SCR, MENU_HALTED, MENU_KEYS,
                         menu_step, palette_colours)
from doomfj.wad import WadFile
from doomfj.wall_renderer import (BOOT_MENU_SKILL, MENU_STATE_DECLS, SKILLS, _menu_lines, DEFAULT_MENU,
                                  DEFAULT_MENU_SELECTED, menu_screen_pixels, restart_lines)

CFG = Config()
VW, VH = CFG.VIEW_W, CFG.VIEW_H
ASSETS = Path("tests/fixtures/freedoom_assets.wad")
SRC = [Path("src/fj") / "present.fj", Path("src/fj") / "input.fj", Path("src/fj") / "m1_reset.fj"]
POLLS = 4
STUB = 7                                            # the world stub paints every column this colour
ENTER, ESC, UP, DOWN, H_KEY = 0x0D, 0x1B, 0x80, 0x81, 0x68

# a minimal restart block: no doors, one runtime thing on one leaf (the block must assemble; what
# it writes is tests/fj/test_skill_menu.py's business)
SPAWN = type("Spawn", (), {"x": 1 << 16, "y": 2 << 16, "angle": 0})()
RESTART = restart_lines(SPAWN, 0, [0], [5], 1, [([1], [0], [])] * len(SKILLS))


def press(f, key):
    return [(f * POLLS, True, key), (f * POLLS + 1, False, key)]


# (frame: what the press does) -- every screen, both help ids, both ways out of each. P10: the boot half has no
# game (esc is no rule there); NEW GAME on frame 13 starts one, and the second half visits the game's menu
SCRIPT = (press(1, DOWN)          # the boot menu: down to HELP
          + press(2, DOWN)        # down: EXIT
          + press(3, UP)          # up: HELP
          + press(4, ENTER)       # enter on HELP: the help (from the menu)
          + press(6, ESC)         # esc: back to the main menu, HELP highlighted
          + press(7, UP)          # up: NEW GAME
          + press(8, H_KEY)       # h on NEW GAME: the help
          + press(9, H_KEY)       # h: back to the main menu on HELP
          + press(10, ESC)        # esc on HELP without a game: no rule (P10)
          + press(11, UP)         # up: NEW GAME
          + press(12, ENTER)      # enter: the skill screen, MEDIUM highlighted (P10)
          + press(13, ENTER)      # enter: NEW GAME at medium -- the world
          + press(14, H_KEY)      # h in the world: the help (from the game)
          + press(16, ESC)        # esc: back to the WORLD
          + press(17, H_KEY)      # the help again
          + press(18, H_KEY)      # h: back to the world
          + press(19, ENTER)      # enter in the world: the main menu, on RESUME (P10)
          + press(20, DOWN)       # down: NEW GAME (the game's menu)
          + press(21, ENTER)      # enter: the skill screen
          + press(22, UP)         # up: easy
          + press(23, H_KEY)      # h on the skill screen: ignored
          + press(24, DOWN)       # down: medium
          + press(25, DOWN)       # down: hard
          + press(26, ESC)        # esc: the main menu (the game's, NEW GAME highlighted)
          + press(27, DOWN)       # down: HELP
          + press(28, DOWN)       # down: EXIT
          + press(29, DOWN)       # down: clamped
          + press(30, H_KEY)      # h on EXIT: the help
          + press(31, ESC)        # esc: back to the main menu, HELP highlighted
          + press(32, DOWN)       # down: EXIT
          + press(33, UP)         # up: HELP
          + press(34, UP)         # up: NEW GAME
          + press(35, UP)         # up: RESUME (P10)
          + press(36, ESC))       # esc on RESUME: the world
FRAMES = 38
# P9: EXIT -- down, down, enter: the program HALTS on frame 4, before presenting it (frames 0..3 are all it shows)
HALT_SCRIPT = press(1, DOWN) + press(2, DOWN) + press(4, ENTER) + press(6, ESC)
HALT_FRAMES = 8
# from LEVEL COMPLETE (the exit's state): P10 -- h is a key: ANY key leads to the boot's main menu; enter there opens
# the skill screen
DONE_SCRIPT = press(1, H_KEY) + press(2, ENTER) + press(3, DOWN)
DONE_FRAMES = 5
# P10: from the EXIT's state (LEVEL COMPLETE at its hold's first code): keys on the hold's frames are ignored, the
# screen drawn throughout; the first key after it leaves for the boot menu
HOLD_SCRIPT = press(0, ENTER) + press(2, H_KEY) + press(5, ESC) + press(7, ENTER) + press(9, DOWN) + press(10, ENTER)
HOLD_FRAMES = 12


def _program(menu_lines, scr0, frames):
    world = []
    for x in range(VW):                             # the world STUB: one flat frame
        world += [f"    stl.output_char {x}", f"    stl.output_char {VH}",
                  f"    stl.output_char {STUB}", "    stl.output_char 0xFF"]
    return "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        "tm_frame:",
        *[f"    hex.zero 1, {e}" for e in ("ev_enter", "ev_esc", "ev_up", "ev_dn", "ev_help", "ev_any")],
        f"    rep({POLLS}, i) kb.poll kbstat, kbcode, kb_f, kb_b, kb_l, kb_r, kb_u, kb_sl, kb_sr, kb_fi, kb_w1, kb_w2, kb_w3, kb_w4, kb_w5, kb_now, "
        "ev_enter, ev_esc, ev_up, ev_dn, ev_help, ev_any, bad",     # P10: ev_any
        *menu_lines,                                # ends at `do_world:`
        "    stl.output_char 0x0B",
        *world,
        "frame_end:",
        "    stl.output_char 0xFF",
        "    hex.inc 2, tm_count",
        "    hex.cmp 2, tm_count, tm_frames, tm_frame, tm_done, tm_done",
        "tm_done:", "    stl.loop",
        "bad:", "    stl.output_char 0x21", "    stl.loop",
        "mode: hex.vec 1, 1",
        *[f"menu_scr: hex.vec 1, {scr0}" if d.startswith("menu_scr:") else
          f"g_live: hex.vec 1, {int(scr0 in LEVEL_DONE_SCREENS)}" if d.startswith("g_live:") else d    # P10
          for d in MENU_STATE_DECLS],
        "kbstat: hex.vec 1", "kbcode: hex.vec 2", "kb_f: hex.vec 1", "kb_b: hex.vec 1",
        "kb_l: hex.vec 1", "kb_r: hex.vec 1", "kb_u: hex.vec 1",
        "kb_sl: hex.vec 1", "kb_sr: hex.vec 1", "kb_fi: hex.vec 1", "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1", "kb_w5: hex.vec 1",   # M7 P4.1
        "kb_now: hex.vec 13",                                       # P9: the press latch kb.poll sets
        "p_tnh: hex.vec 1",                                         # M7 P6+P7: the turn held flag the restart zeroes
        "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "thss_rt: hex.vec 16", "thpos_rt: hex.vec 16",
        "sshead:", "    ;0 * dw", "thnext:", "    ;0 * dw",
        "tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {frames}",
    ]) + "\n"


class _Recording(InMemoryScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(list(self.pixel_indices))


def _run(tmp, name, menu_lines, events, scr0=0, frames=FRAMES):
    src = tmp / f"{name}.fj"
    src.write_text(_program(menu_lines, scr0, frames), encoding="utf-8")
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / f"{name}.fjm"
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out,
                memory_width=W, print_time=False)
    screen = _Recording()
    io = PcIO(screen, KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events])))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return screen.frames


def _colours():
    wad = WadFile.from_path(str(ASSETS))
    return palette_colours(bytes(b for rgb in wad.playpal(0) for b in rgb))


def _expected(events, scr0=0, frames=FRAMES, step=menu_step):
    """the oracle: the device's delivery (one event per poll tic), the rules, the picture"""
    colours = _colours()
    pending = sorted((KeyEvent(*e) for e in events), key=lambda e: e.tic)
    mode, scr, sel, live = 1, scr0, SKILLS.index(BOOT_MENU_SKILL), int(scr0 in LEVEL_DONE_SCREENS)   # P10
    out, states, i = [], [], 0
    for f in range(frames):
        ev = set()
        for tic in range(f * POLLS, (f + 1) * POLLS):
            if i < len(pending) and pending[i].tic <= tic:
                if pending[i].is_down and pending[i].keycode in MENU_KEYS:
                    ev.add(MENU_KEYS[pending[i].keycode])
                if pending[i].is_down:
                    ev.add(ANY_KEY_EVENT)           # P10
                i += 1
        mode, scr, sel, _ng, live = step(mode, scr, sel, ev, live)
        states.append((mode, scr, sel, live))
        if scr == MENU_HALTED:                      # P9: the program halts on this frame, presenting nothing more
            break
        out.append(menu_screen_pixels(CFG, colours, scr, sel, live) if mode else [STUB] * (VW * VH))
    return out, states


def _lines(mutate=None):
    lines = _menu_lines(CFG, WadFile.from_path(str(ASSETS)), list(DEFAULT_MENU),
                        DEFAULT_MENU_SELECTED, restart=RESTART)
    return mutate(lines) if mutate else lines


def _first_bad(got, want):
    for f, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return f
    return None if len(got) == len(want) else min(len(got), len(want))


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("menuscreens")
    return {"main": _run(tmp, "main", _lines(), SCRIPT),
            "done": _run(tmp, "done", _lines(), DONE_SCRIPT, LEVEL_DONE_SCR, DONE_FRAMES),
            "hold": _run(tmp, "hold", _lines(), HOLD_SCRIPT, LEVEL_DONE_ENTER, HOLD_FRAMES),            # P10
            "halt": _run(tmp, "halt", _lines(), HALT_SCRIPT, frames=HALT_FRAMES)}


def test_every_frame_is_the_oracles_picture(runs):
    want, states = _expected(SCRIPT)
    got = runs["main"]
    assert len(got) == FRAMES
    bad = _first_bad(got, want)
    assert bad is None, "frame %d: the program painted another picture (oracle state %r)" % (
        bad, states[bad])


def test_from_level_complete_any_key_leaves_for_the_boot_menu(runs):
    """P10: h is a key -- LEVEL COMPLETE leaves on it for the main menu WITHOUT a game (g_live 0), whose enter opens the
    skill screen and whose down then moves the skill (before P10, h was ignored and enter left)"""
    want, states = _expected(DONE_SCRIPT, LEVEL_DONE_SCR, DONE_FRAMES)
    assert [s[1] for s in states] == [LEVEL_DONE_SCR, 0, 1, 1, 1]
    assert [s[3] for s in states] == [1, 0, 0, 0, 0]
    assert _first_bad(runs["done"], want) is None


def test_level_complete_holds_then_any_key_leaves(runs):
    """P10: booted as the exit leaves it (LEVEL_DONE_ENTER), frames 0..7 are LEVEL COMPLETE whatever is pressed (enter,
    h, esc, enter on frames 0, 2, 5, 7), frame 8 is still it (nothing pressed), and down on frame 9 -- ANY key --
    leaves for the boot menu on NEW GAME (no game: g_live 0; the down is the leaving, not a move), whose enter opens
    the skill screen"""
    want, states = _expected(HOLD_SCRIPT, LEVEL_DONE_ENTER, HOLD_FRAMES)
    assert all(s[1] in LEVEL_DONE_SCREENS for s in states[:9]) and states[8][1] == LEVEL_DONE_SCR, states
    assert states[9][1:4:2] == (0, 0) and states[10][1] == 1, states
    assert _first_bad(runs["hold"], want) is None


def test_the_script_visits_every_screen():
    """R9 against a vacuous script: every menu state the branch can pick is drawn at least once --
    the main menu on both items, the help under both ids, the skill screen at every highlight -- and
    there are world frames, and the help closes both ways"""
    _want, states = _expected(SCRIPT)
    # P10: a main-menu screen is a picture per (screen, g_live); the help and the skill screen do not depend on it
    menus = {(s[1], s[2] if s[1] == 1 else None, s[3] if s[1] in (0, MAIN_HELP_SCR, MAIN_EXIT_SCR) else None)
             for s in states if s[0] == 1}
    assert menus == {(0, None, 0), (MAIN_HELP_SCR, None, 0), (MAIN_EXIT_SCR, None, 0),
                     (0, None, 1), (MAIN_HELP_SCR, None, 1), (MAIN_EXIT_SCR, None, 1), (MAIN_RESUME_SCR, None, None),
                     (HELP_MENU_SCR, None, None), (HELP_GAME_SCR, None, None), (1, 0, None), (1, 1, None),
                     (1, 2, None)}, menus
    assert any(s[0] == 0 for s in states)
    pairs = set(zip([s[:2] for s in states], [s[:2] for s in states[1:]]))
    assert ((1, HELP_GAME_SCR), (0, 0)) in pairs and ((1, HELP_MENU_SCR), (1, MAIN_HELP_SCR)) in pairs
    assert ((0, 0), (1, MAIN_RESUME_SCR)) in pairs and ((1, MAIN_RESUME_SCR), (0, 0)) in pairs


def test_enter_on_exit_halts_the_program(runs):
    """P9: down, down (EXIT), enter -- the program halts on that frame (`mn_exit`, a jump-to-self) before presenting
    it: the run presents frames 0..3, each the oracle's picture, and NOTHING after, though the script presses esc
    later and the harness would loop for HALT_FRAMES frames"""
    want, states = _expected(HALT_SCRIPT, frames=HALT_FRAMES)
    assert [s[1] for s in states] == [0, MAIN_HELP_SCR, MAIN_EXIT_SCR, MAIN_EXIT_SCR, MENU_HALTED], states
    assert len(want) == 4 and len(runs["halt"]) == 4, (len(want), len(runs["halt"]))
    assert _first_bad(runs["halt"], want) is None


def test_an_exit_that_does_not_halt_is_caught(tmp_path):
    """R9 for the halt: `mn_exit` sending the program back to the menu instead of halting presents frames past the
    halting one -- rejected; and the oracle without the halt (EXIT's enter ignored) disagrees with the real run"""
    def mutate(lines):
        assert lines.count("mn_exit: stl.loop") == 1
        return ["mn_exit: ;mn_done" if ln == "mn_exit: stl.loop" else ln for ln in lines]
    got = _run(tmp_path, "nohalt", _lines(mutate), HALT_SCRIPT, frames=HALT_FRAMES)
    assert len(got) == HALT_FRAMES and _first_bad(got, _expected(HALT_SCRIPT, frames=HALT_FRAMES)[0]) == 4

    def no_halt(mode, scr, sel, ev, live):
        st = menu_step(mode, scr, sel, ev, live)
        return (1, scr, sel, None, live) if st[1] == MENU_HALTED else st
    real = _run(tmp_path, "halt2", _lines(), HALT_SCRIPT, frames=HALT_FRAMES)
    assert _first_bad(real, _expected(HALT_SCRIPT, frames=HALT_FRAMES, step=no_halt)[0]) == 4


def test_a_branch_that_draws_exit_as_help_is_caught(tmp_path):
    """R9 for the new branch bit: the main menu on EXIT drawn as the main menu on HELP -- a perfect picture of the main
    menu -- must be rejected at the first frame on EXIT (P10: frame 2, the boot menu's EXIT)"""
    line = f"hex.if_flags menu_scr, 1<<{MAIN_EXIT_SCR}, mf_p34h, mf_mainx"
    wrong = f"hex.if_flags menu_scr, 1<<{MAIN_EXIT_SCR}, mf_p34h, mf_mainh"

    def mutate(lines):
        assert lines.count(line) == 1
        return [wrong if ln == line else ln for ln in lines]

    got = _run(tmp_path, "exitashelp", _lines(mutate), SCRIPT)
    assert _first_bad(got, _expected(SCRIPT)[0]) == 2


def test_a_branch_that_swaps_two_screens_is_caught(tmp_path):
    """R9: the help and the HELP-highlighted main menu swapped in the producer branch -- each
    picture still perfect -- must be rejected at the first frame on either (frame 1: HELP)"""
    line = f"hex.if_flags menu_scr, 1<<{MAIN_HELP_SCR}, mf_help, mf_mainh"
    swapped = f"hex.if_flags menu_scr, 1<<{MAIN_HELP_SCR}, mf_mainh, mf_help"

    def mutate(lines):
        assert lines.count(line) == 1
        return [swapped if ln == line else ln for ln in lines]

    got = _run(tmp_path, "swapped", _lines(mutate), SCRIPT)
    assert _first_bad(got, _expected(SCRIPT)[0]) == 1


def test_an_oracle_whose_world_help_closes_to_the_menu_is_caught(runs):
    """R9 for the oracle side: the rules with HELP_GAME_SCR closing to the main menu must disagree
    with the program at frame 16 (P10), where esc leaves the world's help"""
    def wrong(mode, scr, sel, ev, live):
        if mode == 1 and scr == HELP_GAME_SCR and ("esc" in ev or "help" in ev):
            return 1, 0, sel, None, live
        return menu_step(mode, scr, sel, ev, live)
    assert _first_bad(runs["main"], _expected(SCRIPT, step=wrong)[0]) == 16


def test_a_branch_that_draws_resume_as_new_game_is_caught(tmp_path):
    """R9 (P10): the main menu on RESUME drawn as the game's main menu on NEW GAME -- each a perfect picture -- must be
    rejected at the first frame on RESUME (frame 19, where enter in the world opens the menu)"""
    line = f"hex.if_flags menu_scr, 1<<{MAIN_RESUME_SCR}, mf_p34r, mf_mainr"
    wrong = f"hex.if_flags menu_scr, 1<<{MAIN_RESUME_SCR}, mf_p34r, mf_main_l"

    def mutate(lines):
        assert lines.count(line) == 1
        return [wrong if ln == line else ln for ln in lines]

    got = _run(tmp_path, "resumeasnew", _lines(mutate), SCRIPT)
    assert _first_bad(got, _expected(SCRIPT)[0]) == 19


def test_a_main_menu_that_ignores_the_game_is_caught(tmp_path):
    """R9 (P10): the main menu drawn as the boot's whatever `g_live` says -- the RESUME variant never shown -- must be
    rejected at the first main-menu frame of the game (frame 20: NEW GAME with RESUME over it)"""
    line = "hex.if1 1, g_live, mf_main_l"

    def mutate(lines):
        assert lines.count(line) == 1
        return ["// P10 mutant: no g_live test" if ln == line else ln for ln in lines]

    got = _run(tmp_path, "nolive", _lines(mutate), SCRIPT)
    assert _first_bad(got, _expected(SCRIPT)[0]) == 20
