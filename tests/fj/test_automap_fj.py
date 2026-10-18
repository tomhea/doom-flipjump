"""M8 -- THE MAP PAGE, run (doomfj.automap; the owner, 2026-10-18): the emitted fj against the oracle, on E1M2 -- the
one map whose MAP_CONFIG turns the page on.

1. THE DOT (`automap.fj_lines`, the exact lines the menu block bakes): a program that sets `viewx` / `viewy` to each of
   POSES -- the player start, the bounding box's corners, both sides of the band boundary to the map unit and to
   the 16.16 fraction, and seeded random positions with random fractions -- and draws the page each time, every
   frame through the real screen device, against `automap.pixels` (the band the row picks, its baked frame, the 3x3
   dot over it). R9: the x constant a pixel off, the band threshold a row off, a band's row constant a row off and
   the shift dropped are each rejected.

2. THE MENU (`wall_renderer._menu_lines` with the page + `standalone_key_lines(automap=True)`, the game tier's exact
   input prologue -- the real kb.poll with M read after each poll): a script through every way in and out of the
   page -- m in the world and on every main-menu item, MAP's enter, esc and m closing it back to where it was
   opened -- and the main menu's MAP between HELP and EXIT, against `menu.menu_step(automap=True)` and
   `wall_renderer.menu_screen_pixels`. The WORLD STUB moves the player each world frame, so the page shows the dot
   wherever the walk left him -- in both bands -- and a held W while the page is up moves nobody: THE PAUSED WORLD.
   R9: the M key read on its UP edge, the page opened from the world closing to the main menu (the oracle), the
   main-menu MAP drawn as HELP (the branch), and an oracle whose world tics under the page, are each rejected.

3. THE PRICE in normal play: the same harness's world frames with no key, the page on against off -- the added ops a
   world frame pays (M's per-poll check, `ev_map` zeroed, one more `if0` in the world's menu branch).
"""
from pathlib import Path
import random

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.interpreter.io_devices.pygame_window import PcIO
from flipjump.utils.exceptions import IODeviceException

from doomfj import automap as A
from doomfj import keyboard as KB
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_byte_by_nibbles_fj
from doomfj.menu import (HELP_GAME_SCR, HELP_MENU_SCR, MAIN_EXIT_SCR, MAIN_HELP_SCR, MAIN_MAP_SCR,
                         MAIN_RESUME_SCR, MAP_GAME_SCR, MAP_MENU_SCR, menu_keys, menu_step)
from doomfj.wad import WadFile
from doomfj.wall_renderer import (AUTOMAP_STATE_DECLS, BOOT_MENU_SKILL, DEFAULT_MENU, DEFAULT_MENU_SELECTED,
                                  MENU_STATE_DECLS, SKILLS, STANDALONE_POLLS, _menu_lines, menu_screen_pixels,
                                  restart_lines, standalone_key_lines)

CFG = Config()
MAP = "E1M2"
ASSETS = Path("tests/fixtures/freedoom_assets.wad")
MAP_WAD = Path("tests/fixtures/freedoom_e1m2.wad")
SRC = [Path("src/fj") / "present.fj", Path("src/fj") / "input.fj", Path("src/fj") / "m1_reset.fj"]
POLLS = 4
STUB = 7                                            # the world stub paints every column this colour
ENTER, ESC, UP, DOWN, H_KEY, M_KEY, W_KEY = 0x0D, 0x1B, 0x80, 0x81, 0x68, 0x6D, 0x77
M32 = 0xFFFFFFFF

SPAWN = type("Spawn", (), {"x": 1 << 16, "y": 2 << 16, "angle": 0})()
RESTART = restart_lines(SPAWN, 0, [0], [5], 1, [([1], [0], [])] * len(SKILLS))


def _palette():
    return bytes(b for rgb in WadFile.from_path(str(ASSETS)).playpal(0) for b in rgb)


@pytest.fixture(scope="module")
def pages():
    p = A.pages_for(WadFile.from_path(str(MAP_WAD)), MAP, _palette())
    assert p is not None and p.nbands == 2, "E1M2's page is on (config.MAP_CONFIG) and two bands tall"
    return p


def test_e1m1_has_no_page():
    """the switch: E1M1's MAP_CONFIG leaves the page off, so its menu, help, poll and state machine are E1M1's"""
    assert A.pages_for(WadFile.from_path("tests/fixtures/freedoom_e1m1.wad"), "E1M1", _palette()) is None


class _Recording(InMemoryScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(list(self.pixel_indices))


def _assemble_run(tmp, name, text, events=(), extra=()):
    src = tmp / f"{name}.fj"
    src.write_text(text, encoding="utf-8")
    byte_t = tmp / "byte_emit.fj"
    byte_t.write_text(generate_emit_byte_by_nibbles_fj("byte"), encoding="utf-8")
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / f"{name}.fjm"
    # the byte table AFTER the program: its file runs its `init` at top level, and the program's first op must be
    # stl.startup's
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve(), byte_t.resolve()], out,
                memory_width=W, print_time=False)
    screen = _Recording()
    io = PcIO(screen, KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events])))
    stats = fj.run(out, io_device=io, print_time=False, print_termination=False)
    return screen.frames, stats.op_counter


def _first_bad(got, want):
    for f, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return f
    return None if len(got) == len(want) else min(len(got), len(want))


# ---------------------------------------------------------------------------------------------------------------------
# 1. THE DOT
def _poses(p):
    """(viewx, viewy) 16.16, unsigned 32-bit -- the corners, the band boundary from both sides, the start, random"""
    s = A.shift_bits(p)
    t = p.thresholds[0]
    y_at = lambda row: ((p.maxy << 16) - (row << s)) & M32       # noqa: E731 -- the row's top edge, 16.16
    out = [(p.minx << 16, p.maxy << 16), ((p.maxx << 16) + 0xFFFF, p.miny << 16),
           (p.minx << 16, p.miny << 16), ((p.maxx << 16) + 0xFFFF, p.maxy << 16),
           (608 << 16, 48 << 16)]                                       # E1M2's player start
    for row in (t - 1, t):                                              # both sides of the boundary...
        out += [((p.minx + 700) << 16, y_at(row)), ((p.minx + 701) << 16, (y_at(row) - 1) & M32),
                ((p.minx + 702) << 16, (y_at(row + 1) + 1) & M32)]      # ...to the 16.16 unit
    rnd = random.Random(20261018)
    for _ in range(12):
        out.append((rnd.randrange(p.minx << 16, (p.maxx + 1) << 16) & M32,
                    rnd.randrange(p.miny << 16, (p.maxy << 16) + 1) & M32))
    return out


def _dot_program(p, poses, page_lines):
    body = ["stl.startup_and_init_all", "present.init_screen"]
    for vx, vy in poses:
        body += [f"hex.set 8, viewx, {vx}", f"hex.set 8, viewy, {vy}", "stl.fcall am_page, am_ret",
                 "stl.output_char 0xFF"]
    return "\n".join(body + ["stl.loop", "am_page:", *page_lines, "stl.fret am_ret",
                             "bad: stl.loop", "am_ret: hex.vec w/4", "viewx: hex.vec 8", "viewy: hex.vec 8",
                             *A.decls(p)]) + "\n"


def _dot_run(tmp, name, p, poses, page_lines):
    frames, _ops = _assemble_run(tmp, name, _dot_program(p, poses, page_lines))
    return frames


@pytest.fixture(scope="module")
def dot_frames(pages, tmp_path_factory):
    return _dot_run(tmp_path_factory.mktemp("amdot"), "dot", pages, _poses(pages), A.fj_lines(pages))


def test_the_poses_cover_both_bands_and_the_boundary(pages):
    bands = [A.dot(pages, vx, vy)[0] for vx, vy in _poses(pages)]
    assert set(bands) == {0, 1} and bands[5:8] == [0, 0, 0] and bands[8:11] == [1, 1, 1], bands


def test_every_pose_is_the_oracles_page(pages, dot_frames):
    want = [A.pixels(pages, vx, vy) for vx, vy in _poses(pages)]
    assert len(dot_frames) == len(want)
    bad = _first_bad(dot_frames, want)
    assert bad is None, "pose %d %r: the program's page differs (oracle dot %r)" % (
        bad, _poses(pages)[bad], A.dot(pages, *_poses(pages)[bad]))


def _mutated(lines, old, new):
    assert lines.count(old) == 1, old
    return [new if ln == old else ln for ln in lines]


@pytest.mark.parametrize("what", ["x a pixel off", "threshold a row off", "band 1 a row off", "no shift"])
def test_a_wrong_dot_is_caught(pages, tmp_path, what):
    """R9: each part of the dot's arithmetic, broken, moves some pose's dot"""
    lines = A.fj_lines(pages)
    q, _b = A.window(pages)
    if what == "x a pixel off":
        old = f"    hex.add_constant 8, am_x, {A.x_const(pages)}"
        lines = _mutated(lines, old, "    hex.add_constant 8, am_x, %d"
                         % ((A.x_const(pages) + (1 << A.shift_bits(pages))) & M32))
    elif what == "band 1 a row off":
        old = f"    hex.add_constant 2, am_y + {q}*dw, {A.top_const(pages, 1)}"
        lines = _mutated(lines, old, f"    hex.add_constant 2, am_y + {q}*dw, {A.top_const(pages, 1) + 1}")
    elif what == "no shift":
        old = f"    hex.shr_bit 3, am_x + {q}*dw"
        lines = _mutated(lines, old, "    // mutant: no shift")
    poses = _poses(pages)
    body = _dot_program(pages, poses, lines)
    if what == "threshold a row off":
        good = f"am_t1: hex.vec 2, {pages.thresholds[0]}"
        assert body.count(good) == 1
        body = body.replace(good, f"am_t1: hex.vec 2, {pages.thresholds[0] + 1}")
    want = [A.pixels(pages, vx, vy) for vx, vy in poses]
    try:
        frames, _ = _assemble_run(tmp_path, "mut", body)
    except IODeviceException:          # a dot pushed off the screen: the device itself refuses the run
        return
    assert _first_bad(frames, want) is not None, "the mutant (%s) was not caught" % what


# ---------------------------------------------------------------------------------------------------------------------
# 2. THE MENU, THE KEY AND THE PAUSED WORLD
DX, DY = 23 << 16, 260 << 16                        # the world stub's walk a frame: east a little, south a lot
START = (608 << 16, 48 << 16)


def press(f, key, at=0):
    return [(f * POLLS + at, True, key), (f * POLLS + at + 1, False, key)]


# (frame: what the press does) -- booted in the WORLD with a game in progress (g_live 1)
SCRIPT = (press(1, M_KEY)          # m in the world: the page (band 0), the world paused from here
          + [(2 * POLLS, True, W_KEY)]   # W down and up while the page is up: no picture changes (the stub
          + [(3 * POLLS + 2, False, W_KEY)]   # walks every WORLD frame; the page's frames have no tic)
          + press(3, H_KEY)        # h on the page: ignored
          + press(4, M_KEY)        # m: the world again (it walks from frame 4)
          + press(10, M_KEY)       # the page again -- the walk crossed into band 1
          + press(11, ESC)         # esc: the world
          + press(13, ENTER)       # the main menu, on RESUME
          + press(14, M_KEY)       # m on RESUME: the page, from the menu
          + press(15, M_KEY)       # m: the main menu, on MAP
          + press(16, UP)          # up: HELP
          + press(17, DOWN)        # down: MAP
          + press(18, DOWN)        # down: EXIT
          + press(19, UP)          # up: MAP
          + press(20, ENTER)       # enter on MAP: the page
          + press(21, ENTER)       # enter on the page: ignored
          + press(22, ESC)         # esc: the main menu on MAP
          + press(23, H_KEY)       # h on MAP: the help (it lists M)
          + press(24, ESC)         # esc: the main menu on HELP
          + press(25, M_KEY)       # m on HELP: the page
          + press(26, ESC)         # esc: the main menu on MAP
          + press(27, DOWN)        # down: EXIT
          + press(28, M_KEY)       # m on EXIT: the page
          + press(29, M_KEY)       # m: the main menu on MAP
          + press(30, UP) + press(31, UP)   # up, up: HELP, NEW GAME
          + press(32, M_KEY)       # m on NEW GAME: the page
          + press(33, ESC)         # esc: the main menu on MAP
          + press(34, ESC)         # esc on MAP: the world (a game is in progress)
          + press(36, H_KEY)       # h in the world: the help, listing M
          + press(37, ESC)         # esc: the world
          + [(39 * POLLS, True, M_KEY), (40 * POLLS + 2, False, M_KEY)])   # M held across two frames: the page
FRAMES = 42


def _menu_program(menu_lines, key_lines, frames, world_tic=True):
    world = []
    for x in range(CFG.VIEW_W):                     # the world STUB: one flat frame
        world += [f"    stl.output_char {x}", f"    stl.output_char {CFG.VIEW_H}",
                  f"    stl.output_char {STUB}", "    stl.output_char 0xFF"]
    return "\n".join([
        "stl.startup_and_init_all",
        "present.init_screen",
        "tm_frame:",
        *key_lines,
        *menu_lines,                                # ends at `do_world:`
        # the world STUB's tic: the player walks DX east, DY south -- only a world frame reaches here
        *([f"    hex.add_constant 8, viewx, {DX}", f"    hex.sub_constant 8, viewy, {DY}"] if world_tic else []),
        "    stl.output_char 0x0B",
        *world,
        "frame_end:",
        "    stl.output_char 0xFF",
        "    hex.inc 2, tm_count",
        "    hex.cmp 2, tm_count, tm_frames, tm_frame, tm_done, tm_done",
        "tm_done:", "    stl.loop",
        "bad:", "    stl.output_char 0x21", "    stl.loop",
        "mode: hex.vec 1, 0",                       # booted in the world...
        *["g_live: hex.vec 1, 1" if d.startswith("g_live:") else d for d in MENU_STATE_DECLS],   # ...in a game
        *AUTOMAP_STATE_DECLS,
        "kbstat: hex.vec 1", "kbcode: hex.vec 2", "pkeys: hex.vec 2",
        *[f"{KB.flag(k)}: hex.vec 1" for k in KB.HELD_KEYS], KB.NOW_DECL,
        "p_tnh: hex.vec 1",
        f"viewx: hex.vec 8, {START[0]}", f"viewy: hex.vec 8, {START[1]}", "viewangle: hex.vec 8",
        "thss_rt: hex.vec 16", "thpos_rt: hex.vec 16",
        "sshead:", "    ;0 * dw", "thnext:", "    ;0 * dw",
        "tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {frames}",
    ]) + "\n"


def _run_menu(tmp, name, pages, events, frames=FRAMES, mutate=None, keys=None, automap=True, polls=POLLS):
    menu_lines = (_menu_lines(CFG, WadFile.from_path(str(ASSETS)), list(DEFAULT_MENU), DEFAULT_MENU_SELECTED,
                              restart=RESTART, automap=pages if automap else None))
    if mutate:
        menu_lines = mutate(menu_lines)
    key_lines = keys if keys is not None else standalone_key_lines(polls, automap=automap)
    text = _menu_program(menu_lines, key_lines, frames) + "\n".join(A.decls(pages)) + "\n"
    return _assemble_run(tmp, name, text, events)


def _expected(pages, events, frames=FRAMES, step=menu_step, paused=True):
    """the oracle: the device's delivery (keyboard.frame_keys, M heard as "map"), the rules, the walk, the picture"""
    from doomfj.menu import palette_colours
    colours = palette_colours(_palette())
    fks = KB.frame_keys(events, frames, polls=POLLS, menu_keys=menu_keys(True))
    mode, scr, sel, live = 0, 0, SKILLS.index(BOOT_MENU_SKILL), 1
    vx, vy = START
    out, states = [], []
    for f in range(frames):
        mode, scr, sel, _ng, live = step(mode, scr, sel, set(fks[f].menu), live, automap=True)
        if mode == 0 or not paused:
            vx, vy = (vx + DX) & M32, (vy - DY) & M32
        states.append((mode, scr, sel, live, vx, vy))
        out.append(menu_screen_pixels(CFG, colours, scr, sel, live, automap=pages, view=(vx, vy)) if mode
                   else [STUB] * (CFG.VIEW_W * CFG.VIEW_H))
    return out, states


@pytest.fixture(scope="module")
def menu_run(pages, tmp_path_factory):
    return _run_menu(tmp_path_factory.mktemp("ammenu"), "menu", pages, SCRIPT)


def test_the_script_visits_every_map_state(pages):
    """R9 against a vacuous script: the page under both ids, in BOTH bands, the main menu on MAP with a game, the
    help (with M) from the menu and the world, the page closing both ways, W held under the page"""
    _want, states = _expected(pages, SCRIPT)
    scrs = [s[1] for s in states if s[0] == 1]
    assert {MAP_GAME_SCR, MAP_MENU_SCR, MAIN_MAP_SCR, HELP_MENU_SCR, HELP_GAME_SCR, MAIN_HELP_SCR, MAIN_EXIT_SCR,
            MAIN_RESUME_SCR, 0} <= set(scrs), sorted(set(scrs))
    bands = {A.dot(pages, s[4], s[5])[0] for s in states if s[1] in (MAP_GAME_SCR, MAP_MENU_SCR) and s[0] == 1}
    assert bands == {0, 1}, bands
    pairs = set(zip([s[:2] for s in states], [s[:2] for s in states[1:]]))
    assert ((1, MAP_GAME_SCR), (0, 0)) in pairs and ((1, MAP_MENU_SCR), (1, MAIN_MAP_SCR)) in pairs
    assert ((0, 0), (1, MAP_GAME_SCR)) in pairs and ((1, MAIN_MAP_SCR), (0, 0)) in pairs


def test_every_frame_is_the_oracles_picture(pages, menu_run):
    frames, _ops = menu_run
    want, states = _expected(pages, SCRIPT)
    assert len(frames) == FRAMES
    bad = _first_bad(frames, want)
    assert bad is None, "frame %d: the program painted another picture (oracle state %r)" % (bad, states[bad])


def test_the_world_is_paused_under_the_page(pages, menu_run):
    """the page's frames do not move the player: an oracle whose world walks under the page too disagrees with the
    program at the frame that opens it (frame 1: the dot would be 8 rows further south)"""
    frames, _ops = menu_run
    # (its first four frames only: walking on under every page, it leaves the map's bounding box later)
    assert _first_bad(frames[:4], _expected(pages, SCRIPT, frames=4, paused=False)[0]) == 1


def test_an_oracle_whose_world_page_closes_to_the_menu_is_caught(pages, menu_run):
    def wrong(mode, scr, sel, ev, live, automap=False):
        if mode == 1 and scr == MAP_GAME_SCR and ("esc" in ev or "map" in ev):
            return 1, MAIN_MAP_SCR, sel, None, live
        return menu_step(mode, scr, sel, ev, live, automap=automap)
    assert _first_bad(menu_run[0], _expected(pages, SCRIPT, step=wrong)[0]) == 4


def test_a_branch_that_draws_map_as_help_is_caught(pages, tmp_path):
    """R9 for the producer branch: the main menu on MAP drawn as the main menu on HELP -- a perfect picture of the
    main menu -- is rejected at the first frame on MAP (frame 15)"""
    line = "hex.if_flags amap, 1<<3, mf_amap, mf_mainm"

    def mutate(lines):
        assert lines.count(line) == 1
        return ["hex.if_flags amap, 1<<3, mf_amap, mf_mainh" if ln == line else ln for ln in lines]
    frames, _ = _run_menu(tmp_path, "mapashelp", pages, SCRIPT, mutate=mutate)
    assert _first_bad(frames, _expected(pages, SCRIPT)[0]) == 15


def test_m_read_on_its_up_edge_is_caught(pages, tmp_path):
    """R9 for the key: M read on its UP edge (status 0x8) -- a tap inside one frame still opens the page, but the M
    held across frames 39-40 opens it a frame late"""
    keys = standalone_key_lines(POLLS, automap=True)
    old = [ln for ln in keys if ln.startswith("hex.if_flags kbstat, 1<<0x9")]
    assert len(old) == POLLS
    keys = [ln.replace("1<<0x9", "1<<0x8") if ln in old else ln for ln in keys]
    frames, _ = _run_menu(tmp_path, "upedge", pages, SCRIPT, keys=keys)
    assert _first_bad(frames, _expected(pages, SCRIPT)[0]) == 39



# ---------------------------------------------------------------------------------------------------------------------
# 3. THE PRICE OF A WORLD FRAME
IDLE_FRAMES = 6


@pytest.mark.parametrize("polls", [POLLS, STANDALONE_POLLS])
def test_the_price_of_a_world_frame(pages, tmp_path, capsys, polls):
    """world frames with no key, the page on against off: the difference is the ops every world frame pays for the
    page -- M's per-poll check, ev_map's zeroing, the world's one more `if0` -- at this harness's polls and at the
    game's (STANDALONE_POLLS). Printed; bounded at 60 ops a poll (an idle poll's check is one if_flags)"""
    on = _run_menu(tmp_path, "idle_on", pages, [], frames=IDLE_FRAMES, polls=polls)
    off = _run_menu(tmp_path, "idle_off", pages, [], frames=IDLE_FRAMES, automap=False, polls=polls)
    assert on[0][:IDLE_FRAMES] == [[STUB] * (CFG.VIEW_W * CFG.VIEW_H)] * IDLE_FRAMES == off[0][:IDLE_FRAMES]
    per = (on[1] - off[1]) / IDLE_FRAMES
    with capsys.disabled():
        print("\n[automap] world frame, no key, %d polls: %d ops with the page, %d without -> +%.1f ops a frame"
              % (polls, on[1] // IDLE_FRAMES, off[1] // IDLE_FRAMES, per))
    assert 0 < per <= 60 * polls
