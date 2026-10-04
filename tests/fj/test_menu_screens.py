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
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.interpreter.io_devices.pygame_window import PcIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import (HELP_GAME_SCR, HELP_MENU_SCR, LEVEL_DONE_SCR, MAIN_HELP_SCR, MENU_KEYS,
                         menu_step, palette_colours)
from doomfj.wad import WadFile
from doomfj.wall_renderer import (BOOT_SKILL, MENU_STATE_DECLS, SKILLS, _menu_lines, DEFAULT_MENU,
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


# (frame: what the press does) -- every screen, both help ids, both ways out of each
SCRIPT = (press(1, DOWN)          # the main menu: down to HELP
          + press(2, ENTER)       # enter on HELP: the help (from the menu)
          + press(4, ESC)         # esc: back to the main menu, HELP highlighted
          + press(5, UP)          # up: NEW GAME
          + press(6, H_KEY)       # h on NEW GAME: the help
          + press(7, H_KEY)       # h: back to the main menu on HELP
          + press(8, ESC)         # esc: the world
          + press(9, H_KEY)       # h in the world: the help (from the game)
          + press(11, ESC)        # esc: back to the WORLD
          + press(12, H_KEY)      # the help again
          + press(13, H_KEY)      # h: back to the world
          + press(14, ENTER)      # enter in the world: the main menu
          + press(15, ENTER)      # the skill screen, the boot skill highlighted
          + press(16, UP)         # up
          + press(17, H_KEY)      # h on the skill screen: ignored
          + press(18, UP)         # up
          + press(19, ESC)        # esc: the main menu
          + press(20, DOWN)       # down: HELP
          + press(21, DOWN)       # down: clamped
          + press(22, ESC))       # esc: the world
FRAMES = 24
# from LEVEL COMPLETE (the exit's state): h is ignored, enter leads to the main menu
DONE_SCRIPT = press(1, H_KEY) + press(2, ENTER) + press(3, DOWN)
DONE_FRAMES = 5


def _program(menu_lines, scr0, frames):
    world = []
    for x in range(VW):                             # the world STUB: one flat frame
        world += [f"    stl.output_char {x}", f"    stl.output_char {VH}",
                  f"    stl.output_char {STUB}", "    stl.output_char 0xFF"]
    return "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        "tm_frame:",
        *[f"    hex.zero 1, {e}" for e in ("ev_enter", "ev_esc", "ev_up", "ev_dn", "ev_help")],
        f"    rep({POLLS}, i) kb.poll kbstat, kbcode, kb_f, kb_b, kb_l, kb_r, kb_u, kb_sl, kb_sr, kb_fi, kb_w1, kb_w2, kb_w3, kb_w4, "
        "ev_enter, ev_esc, ev_up, ev_dn, ev_help, bad",
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
        *[f"menu_scr: hex.vec 1, {scr0}" if d.startswith("menu_scr:") else d for d in MENU_STATE_DECLS],
        "kbstat: hex.vec 1", "kbcode: hex.vec 2", "kb_f: hex.vec 1", "kb_b: hex.vec 1",
        "kb_l: hex.vec 1", "kb_r: hex.vec 1", "kb_u: hex.vec 1",
        "kb_sl: hex.vec 1", "kb_sr: hex.vec 1", "kb_fi: hex.vec 1", "kb_w1: hex.vec 1", "kb_w2: hex.vec 1", "kb_w3: hex.vec 1", "kb_w4: hex.vec 1",   # M7 P4.1
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
    mode, scr, sel = 1, scr0, SKILLS.index(BOOT_SKILL)
    out, states, i = [], [], 0
    for f in range(frames):
        ev = set()
        for tic in range(f * POLLS, (f + 1) * POLLS):
            if i < len(pending) and pending[i].tic <= tic:
                if pending[i].is_down and pending[i].keycode in MENU_KEYS:
                    ev.add(MENU_KEYS[pending[i].keycode])
                i += 1
        mode, scr, sel, _ng = step(mode, scr, sel, ev)
        states.append((mode, scr, sel))
        out.append(menu_screen_pixels(CFG, colours, scr, sel) if mode else [STUB] * (VW * VH))
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
            "done": _run(tmp, "done", _lines(), DONE_SCRIPT, LEVEL_DONE_SCR, DONE_FRAMES)}


def test_every_frame_is_the_oracles_picture(runs):
    want, states = _expected(SCRIPT)
    got = runs["main"]
    assert len(got) == FRAMES
    bad = _first_bad(got, want)
    assert bad is None, "frame %d: the program painted another picture (oracle state %r)" % (
        bad, states[bad])


def test_from_level_complete_h_is_ignored(runs):
    want, states = _expected(DONE_SCRIPT, LEVEL_DONE_SCR, DONE_FRAMES)
    assert [s[1] for s in states] == [LEVEL_DONE_SCR, LEVEL_DONE_SCR, 0, MAIN_HELP_SCR, MAIN_HELP_SCR]
    assert _first_bad(runs["done"], want) is None


def test_the_script_visits_every_screen():
    """R9 against a vacuous script: every menu state the branch can pick is drawn at least once --
    the main menu on both items, the help under both ids, the skill screen at every highlight -- and
    there are world frames, and the help closes both ways"""
    _want, states = _expected(SCRIPT)
    menus = {(s[1], s[2] if s[1] == 1 else None) for s in states if s[0] == 1}
    assert menus == {(0, None), (MAIN_HELP_SCR, None), (HELP_MENU_SCR, None), (HELP_GAME_SCR, None),
                     (1, 0), (1, 1), (1, 2)}, menus
    assert any(s[0] == 0 for s in states)
    pairs = set(zip([s[:2] for s in states], [s[:2] for s in states[1:]]))
    assert ((1, HELP_GAME_SCR), (0, 0)) in pairs and ((1, HELP_MENU_SCR), (1, MAIN_HELP_SCR)) in pairs


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
    with the program at frame 11, where esc leaves the world's help"""
    def wrong(mode, scr, sel, ev):
        if mode == 1 and scr == HELP_GAME_SCR and ("esc" in ev or "help" in ev):
            return 1, 0, sel, None
        return menu_step(mode, scr, sel, ev)
    assert _first_bad(runs["main"], _expected(SCRIPT, step=wrong)[0]) == 11
