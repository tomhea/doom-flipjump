"""M3 — the baked menu frame: the fj stream and the oracle's pixels must be the same picture.

The whole point of `doomfj.menu` is that ONE generator feeds both mirrors. These tests prove it by
decoding the stream through the REAL device the standalone binary presents to
(`flipjump.interpreter.io_devices.ScreenIO.InMemoryScreen`, which learned 0x0B in M5a) and
comparing pixel for pixel — so a menu that fj paints differently from what the oracle expects
fails here, in milliseconds, instead of after an 80-minute build.
"""
import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IODeviceException

from doomfj.config import Config
from doomfj.menu import CELL_W, fj, palette_colours, pixels, stream

# R6: the CONFIGURED resolution, not a hardcoded 160x100 -- otherwise
# `test_glyph_geometry_fits_the_screen` asserts nothing about the screen the program actually
# builds, which is the point of that test. The two fj-level menu tests already do this.
CFG = Config()
W, H = CFG.VIEW_W, CFG.VIEW_H
LINES = ["DOOM ON FLIPJUMP", "NEW GAME", "LEVEL 1", "LEVEL 5", "LEVEL 8", "QUIT"]
COLOURS = (0, 4, 176, 101)          # palette_colours of the E1M1 PLAYPAL


def _feed(device, data: bytes):
    for byte in data:
        for i in range(8):
            device.write_bit(bool((byte >> i) & 1))


def _present(data: bytes, width=W, height=H):
    screen = InMemoryScreen()
    _feed(screen, bytes([0x01, width & 0xFF, width >> 8, height & 0xFF, height >> 8, 8, 0, 1]))
    _feed(screen, data)
    return screen


@pytest.mark.parametrize("selected", range(len(LINES)))
def test_the_stream_paints_exactly_the_oracle_picture(selected):
    """THE test. Everything else here is a detail of it."""
    screen = _present(stream(W, H, LINES, selected, COLOURS))
    assert screen.frame_count == 1
    assert screen.pixel_indices == pixels(W, H, LINES, selected, COLOURS)


def test_the_picture_is_not_blank():
    """R9 — two mirrors that agree on an empty screen agree about nothing."""
    grid = pixels(W, H, LINES, 0, COLOURS)
    assert len(set(grid)) == 4, sorted(set(grid))          # background, text, highlight, credit
    assert 0 < sum(1 for p in grid if p != COLOURS[0]) < W * H


def test_the_selection_actually_moves():
    """A menu whose highlight does not follow the cursor would still pass the test above."""
    frames = [tuple(pixels(W, H, LINES, k, COLOURS)) for k in range(len(LINES))]
    assert len(set(frames)) == len(LINES)


def test_a_selected_row_uses_the_highlight_colour():
    grid = pixels(W, H, LINES, 2, COLOURS)
    assert COLOURS[2] in grid
    assert pixels(W, H, LINES, 2, COLOURS).count(COLOURS[2]) > 0


def test_ditto_is_actually_used():
    """The menu is mostly background, so most columns repeat. If the encoder stopped emitting
    DITTO the picture would still be right and the stream would be several times larger — worth
    knowing, since the stream's size IS the frame's op cost."""
    data = stream(W, H, LINES, 0, COLOURS)
    assert 0xFE in data


def test_column_zero_is_never_dittoed():
    """The device refuses a DITTO for column 0 (no left neighbour), and would raise."""
    for selected in range(len(LINES)):
        data = stream(W, H, LINES, selected, COLOURS)
        assert data[1] == 0 and data[2] != 0xFE


def test_the_frame_is_cheap():
    """The claim M3 rests on: a menu frame is orders of magnitude cheaper than a world frame
    (~28M ops). At ~2 ops per output_char this is a few thousand."""
    data = stream(W, H, LINES, 0, COLOURS)
    assert len(data) < 4096, len(data)


def test_fj_emits_one_output_char_per_stream_byte():
    data = stream(W, H, LINES, 0, COLOURS)
    text = fj(W, H, LINES, 0, COLOURS)
    assert text.count("stl.output_char") == len(data)
    assert all(("stl.output_char %d" % b) in text for b in set(data))


def test_an_empty_menu_is_a_blank_frame():
    screen = _present(stream(W, H, [], 0, COLOURS))
    assert screen.pixel_indices == [COLOURS[0]] * (W * H)


def test_long_lines_are_clipped_not_overflowed():
    """A label wider than the screen must clip, not paint out of bounds or desynchronise the
    stream -- the device raises on a run past the last row."""
    long_lines = ["X" * 200, "Y" * 200]
    screen = _present(stream(W, H, long_lines, 0, COLOURS))
    assert screen.pixel_indices == pixels(W, H, long_lines, 0, COLOURS)


def test_palette_colours_are_derived_not_guessed():
    """Black is darkest, white brightest, the highlight is the reddest entry, and the credit is the
    gray nearest 40% of the text's brightness (0.4 * 210 = 84: the gray of 90, entry 3)."""
    rgb = bytearray()
    for i in range(8):
        rgb += bytes([i * 30, i * 30, i * 30])
    rgb += bytes([255, 0, 0])
    background, text, highlight, credit = palette_colours(rgb)
    assert background == 0 and text == 7 and highlight == 8 and credit == 3


def test_a_wrong_picture_is_caught(monkeypatch):
    """R9 negative control: corrupt one pixel of the ORACLE side and require the comparison to
    fail. A differential that cannot fail is not evidence."""
    good = pixels(W, H, LINES, 0, COLOURS)
    bad = list(good)
    bad[W * (H // 2) + W // 2] ^= 0xFF
    screen = _present(stream(W, H, LINES, 0, COLOURS))
    assert screen.pixel_indices == good
    assert screen.pixel_indices != bad


def test_glyph_geometry_fits_the_screen():
    assert W // CELL_W >= 20, "a 160px screen must fit a usable menu label"


# -- M7 P1.5: the menu's RULES (doomfj.menu.menu_step, the oracle side of docs/gp-skill-menu.md) ----

def test_the_menu_rules_move_between_the_screens():
    from doomfj.menu import menu_step
    assert menu_step(0, 0, 2, {"esc"}) == (1, 0, 2, None)        # the world: esc opens the menu
    assert menu_step(0, 0, 2, {"enter"}) == (1, 0, 2, None)      # ...and so does enter
    assert menu_step(0, 0, 2, {"up", "dn"}) == (0, 0, 2, None)   # the world ignores up / down
    assert menu_step(1, 0, 2, {"esc"}) == (0, 0, 2, None)        # the main menu: esc resumes
    assert menu_step(1, 0, 2, {"enter"}) == (1, 1, 2, None)      # ...enter opens the skill screen
    assert menu_step(1, 1, 1, {"esc"}) == (1, 0, 1, None)        # the skill screen: esc goes back
    assert menu_step(1, 1, 1, {"enter"}) == (0, 0, 1, 1)         # ...enter starts skill 1
    assert menu_step(1, 1, 1, set()) == (1, 1, 1, None)          # nothing happens without an event


def test_the_highlight_clamps_and_the_first_event_wins():
    from doomfj.menu import menu_step
    from doomfj.wall_renderer import SKILLS
    assert menu_step(1, 1, 0, {"up"})[2] == 0                    # clamped at the first skill
    assert menu_step(1, 1, len(SKILLS) - 1, {"dn"})[2] == len(SKILLS) - 1   # ...and the last
    assert menu_step(1, 1, 1, {"up"})[2] == 0 and menu_step(1, 1, 1, {"dn"})[2] == 2
    # first match, in the order esc > enter > up > down
    assert menu_step(1, 1, 1, {"esc", "enter", "up"}) == (1, 0, 1, None)
    assert menu_step(1, 1, 1, {"enter", "up"}) == (0, 0, 1, 1)
    assert menu_step(1, 1, 1, {"up", "dn"})[2] == 0
    assert menu_step(1, 0, 2, {"esc", "enter"}) == (0, 0, 2, None)


def test_the_skill_count_is_one_number():
    """R6 (the P1.5 review): the skill screen's entries, the rules' clamp, the emitted clamp and the
    restart dispatch all answer to wall_renderer.SKILLS. The rules kept their own `MENU_SKILLS = 3`
    until the review -- a second number, free to drift from the first, and nothing tied them."""
    from doomfj.menu import menu_step
    from doomfj.wall_renderer import (SKILL_MENU, SKILL_MENU_FIRST, SKILLS, menu_state_lines,
                                      restart_lines)
    last = len(SKILLS) - 1
    assert len(SKILL_MENU) - SKILL_MENU_FIRST == len(SKILLS), "one screen entry per skill"
    assert [menu_step(1, 1, s, {"dn"})[2] for s in range(len(SKILLS))] == [*range(1, last + 1), last]
    assert [menu_step(1, 1, s, {"up"})[2] for s in range(len(SKILLS))] == [0, *range(last)]
    spawn = type("Spawn", (), {"x": 0, "y": 0, "angle": 0})()
    lines = menu_state_lines(restart_lines(spawn, 0, [], [], 1, [([0], [], [])] * len(SKILLS)))
    assert f"hex.if_flags menu_sel, 1<<{last}, mn_dn_inc, mn_done" in lines, "the emitted clamp"
    assert [ln for ln in lines if ln.startswith("mn_r")] == ["mn_r%d:" % k for k in range(len(SKILLS))]


def test_the_skill_dispatch_refuses_a_fourth_skill(monkeypatch):
    """R9 for the tie above: the screens' and NEW GAME's dispatch is three-way by its shape (an if0,
    then one if_flags on bit 1), so a fourth skill must stop the emitter, not reach skill 2's block"""
    import doomfj.wall_renderer as wr
    assert wr._skill_dispatch("mn_r") == ["hex.if0 1, menu_sel, mn_r0",
                                          "hex.if_flags menu_sel, 1<<1, mn_r2, mn_r1"]
    monkeypatch.setattr(wr, "SKILLS", wr.SKILLS + (wr.SKILLS[-1] + 1,))
    with pytest.raises(AssertionError, match="three skills"):
        wr._skill_dispatch("mn_r")


def test_the_menu_keys_are_the_devices():
    """the keycodes kb.poll turns into the menu's events (src/fj/input.fj's table)"""
    from doomfj.menu import MENU_KEYS
    assert MENU_KEYS == {0x0D: "enter", 0x1B: "esc", 0x77: "up", 0x80: "up", 0x73: "dn", 0x81: "dn",
                         0x68: "help"}                     # M7 P3.4: 'h'


# -- M7 P1.5 (the owner, 2026-09-27): the credit, and an M that reads as an M ----------------------

def test_the_credit_sits_in_the_bottom_right_corner_small_and_in_its_dim_gray():
    """the owner's "tomhe.app" on every menu screen: CREDIT in the SMALL (3x5) font, CREDIT_MARGIN px
    from the right and bottom edges, in palette_colours' fourth colour -- and that colour nowhere else"""
    from doomfj.menu import (CREDIT, CREDIT_MARGIN, SMALL_GLYPH_H, _SMALL_GLYPHS, glyph_width,
                             text_width)
    for lines, sel in ((LINES, 0), (["CHOOSE SKILL", "", "EASY", "MEDIUM", "HARD"], 4)):
        grid = pixels(W, H, lines, sel, COLOURS)
        x0 = W - CREDIT_MARGIN - text_width(CREDIT, _SMALL_GLYPHS)
        y0 = H - CREDIT_MARGIN - SMALL_GLYPH_H
        want, x = set(), x0
        for ch in CREDIT:
            rows = _SMALL_GLYPHS[ch].split("|")
            assert len(rows) == SMALL_GLYPH_H
            want |= {(x + gx, y0 + gy) for gy, r in enumerate(rows) for gx, c in enumerate(r)
                     if c == "#"}
            x += glyph_width(ch, _SMALL_GLYPHS) + 1
        got = {(i % W, i // W) for i, p in enumerate(grid) if p == COLOURS[3]}
        assert got == want, sorted(got ^ want)[:8]
        assert x - 1 == W - CREDIT_MARGIN, "the credit does not end at the margin"


def test_the_lines_are_5x7_and_both_fonts_draw_an_m_with_two_stems_and_a_dip():
    """the owner chose the 5x7 font for the menu's lines (and kept the credit's 3x5): in both, M is
    five columns, its outer columns full, its middle column inked only where the dip reaches --
    rows 2-3 -- which no three-column M can draw"""
    from doomfj.menu import (GLYPH_H, SMALL_GLYPH_H, _GLYPHS, _SMALL_GLYPHS, glyph_width,
                             text_width)
    assert GLYPH_H == 7 and SMALL_GLYPH_H == 5
    assert all(len(g.split("|")) == GLYPH_H for g in _GLYPHS.values())
    assert all(len(g.split("|")) == SMALL_GLYPH_H for g in _SMALL_GLYPHS.values())
    for font, h in ((_GLYPHS, GLYPH_H), (_SMALL_GLYPHS, SMALL_GLYPH_H)):
        rows = font["M"].split("|")
        assert glyph_width("M", font) == 5 and len(rows) == h
        assert all(r[0] == "#" and r[4] == "#" for r in rows)
        assert [k for k, r in enumerate(rows) if r[2] == "#"] == [2, 3]
    assert text_width("M.") == 5 + 1 + 2                      # widths add, one gap between
    assert text_width("MH", _SMALL_GLYPHS) == 5 + 1 + 3


# -- M7 P3.4: the HELP screen (docs/gp-help.md) -----------------------------------------------------

def test_the_help_stream_paints_exactly_the_help_picture():
    """the one-generator rule for the help: the stream fj emits, decoded by the REAL device, is the
    oracle's picture"""
    from doomfj.menu import help_pixels, help_stream
    screen = _present(help_stream(W, H, COLOURS))
    assert screen.frame_count == 1
    assert screen.pixel_indices == help_pixels(W, H, COLOURS)


def test_the_help_screen_draws_its_title_and_every_row_where_the_layout_says():
    """legibility, checked glyph by glyph: the title centred at HELP_TITLE_Y in the highlight colour;
    every row's key and description in the 5x7 font, in the text colour, the keys left-aligned in one
    column and the descriptions in another; the credit as on every screen; NOTHING else inked. And
    the rows are the key map the owner asked for, in his order."""
    from doomfj.menu import (CREDIT, CREDIT_MARGIN, GLYPH_GAP, HELP_COL_GAP, HELP_PITCH, HELP_ROWS,
                             HELP_ROWS_Y, HELP_TITLE, HELP_TITLE_Y, SMALL_GLYPH_H, _GLYPHS,
                             _SMALL_GLYPHS, help_pixels, text_width)

    def ink(label, x0, y0, font=_GLYPHS):
        out, x = set(), x0
        for ch in label:
            rows = font[ch].split("|")
            out |= {(x + gx, y0 + gy) for gy, r in enumerate(rows) for gx, c in enumerate(r) if c == "#"}
            x += len(rows[0]) + GLYPH_GAP
        return out

    assert [k for k, _ in HELP_ROWS] == ["W / UP", "S / DOWN", "A / LEFT", "D / RIGHT", "SPACE / E",
                                        "", "ENTER", "ESC", "H"]
    assert " ".join(d for _, d in HELP_ROWS) == ("MOVE FORWARD MOVE BACK TURN LEFT TURN RIGHT USE: "
                                                 "DOORS, SWITCHES, LIFTS SELECT MENU THIS HELP")
    assert all(ch in _GLYPHS for label in [HELP_TITLE] + [s for row in HELP_ROWS for s in row]
               for ch in label), "a help character the font cannot draw would print as a blank"
    grid = help_pixels(W, H, COLOURS)
    got = {c: {(i % W, i // W) for i, p in enumerate(grid) if p == c} for c in COLOURS[1:]}
    title = ink(HELP_TITLE, (W - text_width(HELP_TITLE)) // 2, HELP_TITLE_Y)
    keys_w = max(text_width(k) for k, _ in HELP_ROWS)
    table_w = keys_w + HELP_COL_GAP + max(text_width(d) for _, d in HELP_ROWS)
    x_keys = (W - table_w) // 2
    rows = set()
    for r, (key, what) in enumerate(HELP_ROWS):
        y = HELP_ROWS_Y + r * HELP_PITCH
        rows |= ink(key, x_keys, y) | ink(what, x_keys + keys_w + HELP_COL_GAP, y)
    credit = ink(CREDIT, W - CREDIT_MARGIN - text_width(CREDIT, _SMALL_GLYPHS),
                 H - CREDIT_MARGIN - SMALL_GLYPH_H, _SMALL_GLYPHS)
    assert got[COLOURS[2]] == title
    assert got[COLOURS[1]] == rows
    assert got[COLOURS[3]] == credit
    assert max(y for _x, y in rows) < H - CREDIT_MARGIN - SMALL_GLYPH_H, "a row reaches the credit"
    assert all(0 <= x < W for x, _y in rows | title)


def test_the_help_screen_is_not_the_menu_and_is_not_blank():
    """R9: two mirrors that agree on a blank screen, or on the main menu, agree about nothing"""
    from doomfj.menu import help_pixels
    grid = help_pixels(W, H, COLOURS)
    assert len(set(grid)) == 4
    assert grid != pixels(W, H, ["DOOM ON FLIPJUMP", "", "NEW GAME", "HELP"], 2, COLOURS)
    assert sum(1 for p in grid if p == COLOURS[1]) > 1000      # nine rows of 5x7 text


def test_a_wrong_help_picture_is_caught():
    """R9 negative control for the help's differential: one pixel of the oracle moved, and the
    device's decode of the stream must disagree with it"""
    from doomfj.menu import help_pixels, help_stream
    good = help_pixels(W, H, COLOURS)
    bad = list(good)
    bad[W * 20 + 30] ^= 0xFF
    screen = _present(help_stream(W, H, COLOURS))
    assert screen.pixel_indices == good and screen.pixel_indices != bad


def test_the_help_layout_refuses_a_row_too_wide(monkeypatch):
    """R9 for the layout's asserts: a row wider than the screen stops the generator instead of
    clipping the key map"""
    import doomfj.menu as menu
    monkeypatch.setattr(menu, "HELP_ROWS", menu.HELP_ROWS + (("SPACE / E", "USE: DOORS, SWITCHES, LIFTS"),))
    with pytest.raises(AssertionError, match="wider than the screen"):
        menu.help_pixels(W, H, COLOURS)


def test_the_help_rules():
    """menu_step's help: h in the world and on the main menu, enter on HELP, esc or h closing back
    to where it was opened, the main menu's two items clamped, h ignored on the skill screen and
    LEVEL COMPLETE, and esc / enter winning over h"""
    from doomfj.menu import (HELP_GAME_SCR as HG, HELP_MENU_SCR as HM, LEVEL_DONE_SCR as LD,
                             MAIN_HELP_SCR as MH, menu_step)
    assert menu_step(0, 0, 2, {"help"}) == (1, HG, 2, None)       # the world: h opens the help
    assert menu_step(1, HG, 2, {"help"}) == (0, 0, 2, None)       # ...h closes it to the world
    assert menu_step(1, HG, 2, {"esc"}) == (0, 0, 2, None)        # ...and so does esc
    assert menu_step(1, HG, 2, {"enter", "up", "dn"}) == (1, HG, 2, None)
    assert menu_step(1, 0, 2, {"help"}) == (1, HM, 2, None)       # the main menu: h opens it
    assert menu_step(1, 0, 2, {"dn"}) == (1, MH, 2, None)         # ...down highlights HELP
    assert menu_step(1, 0, 2, {"up"}) == (1, 0, 2, None)          # ...up is clamped
    assert menu_step(1, MH, 2, {"enter"}) == (1, HM, 2, None)     # HELP: enter opens it
    assert menu_step(1, MH, 2, {"help"}) == (1, HM, 2, None)      # ...and so does h
    assert menu_step(1, MH, 2, {"up"}) == (1, 0, 2, None)         # ...up to NEW GAME
    assert menu_step(1, MH, 2, {"dn"}) == (1, MH, 2, None)        # ...down is clamped
    assert menu_step(1, MH, 2, {"esc"}) == (0, 0, 2, None)        # ...esc resumes the world
    assert menu_step(1, HM, 2, {"esc"}) == (1, MH, 2, None)       # the menu's help: back to HELP
    assert menu_step(1, HM, 2, {"help"}) == (1, MH, 2, None)
    assert menu_step(1, HM, 2, set()) == (1, HM, 2, None)
    assert menu_step(1, 1, 1, {"help"}) == (1, 1, 1, None)        # the skill screen ignores h
    assert menu_step(1, LD, 1, {"help"}) == (1, LD, 1, None)      # ...and so does LEVEL COMPLETE
    assert menu_step(0, 0, 2, {"esc", "help"}) == (1, 0, 2, None)  # esc and enter win over h
    assert menu_step(1, 0, 2, {"enter", "help"}) == (1, 1, 2, None)
    assert menu_step(1, 0, 2, {"help", "dn"}) == (1, HM, 2, None)  # ...and h over up / down


def test_the_menu_screens_are_one_mapping():
    """`wall_renderer.menu_screen_pixels` -- the oracle's picture for every menu state -- gives each
    state the picture `_menu_lines` bakes for it: the two main-menu highlights, the three skill
    highlights, LEVEL COMPLETE and the help, the two help ids ONE picture; seven distinct pictures"""
    from doomfj.menu import (HELP_GAME_SCR, HELP_MENU_SCR, LEVEL_DONE_SCR, MAIN_HELP_SCR,
                             help_pixels)
    from doomfj.wall_renderer import DEFAULT_MENU, MENU_HELP_ITEM, menu_screen_pixels
    cfg = CFG
    assert DEFAULT_MENU == ["DOOM ON FLIPJUMP", "", "NEW GAME", "HELP"]
    states = [(0, 2), (MAIN_HELP_SCR, 2), (1, 0), (1, 1), (1, 2), (LEVEL_DONE_SCR, 2),
              (HELP_MENU_SCR, 2), (HELP_GAME_SCR, 2)]
    pics = {s: tuple(menu_screen_pixels(cfg, COLOURS, *s)) for s in states}
    assert pics[(HELP_MENU_SCR, 2)] == pics[(HELP_GAME_SCR, 2)] == tuple(help_pixels(W, H, COLOURS))
    assert len(set(pics.values())) == 7
    assert pics[(MAIN_HELP_SCR, 2)] == tuple(pixels(W, H, DEFAULT_MENU,
                                                    DEFAULT_MENU.index(MENU_HELP_ITEM), COLOURS))


def test_the_main_menu_must_have_a_help_item():
    """`_menu_lines` finds the HELP item by name; a menu without one must stop the emitter"""
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import _menu_lines, restart_lines
    spawn = type("Spawn", (), {"x": 0, "y": 0, "angle": 0})()
    restart = restart_lines(spawn, 0, [], [], 1, [([0], [], [])] * 3)
    with pytest.raises(AssertionError, match="HELP"):
        _menu_lines(CFG, WadFile.from_path("tests/fixtures/freedoom_assets.wad"), ["A", "QUIT"], 0, restart=restart)
