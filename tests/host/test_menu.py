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
    # M7 P7: NEW GAME runs restartcode.call_lines -- one fcall'd routine per skill, dispatched on g_skill (which
    # NEW GAME sets from menu_sel), then the sequence's end label
    assert [ln for ln in lines if ln.startswith("mn_r")] == ["mn_r%d:" % k for k in range(len(SKILLS))] + ["mn_r_done:"]
    assert [ln for ln in lines if ln.startswith("stl.fcall rs_skill")] == [
        "stl.fcall rs_skill%d, rs_ret" % k for k in range(len(SKILLS))]
    assert "hex.mov 1, g_skill, menu_sel" in lines


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


# the owner's keycap design (2026-10-02, chosen from rendered prototypes), PINNED: every cap's outer
# box (key, x, y, w) -- HELP_CAP_H high -- and every string (label, x, y), the caps' legends centred
# in them. Written out, not re-derived from `help_layout`: a layout change must change this table.
# M7 P4.1: the help re-pinned for the owner's key map (approved 2026-10-02) -- three legend lines beside the clusters,
# fire / the weapons / the second strafe pair as two-item rows (docs/gp-combat.md; the render, reviewed, in the PR)
# M7 P6+P7 (the owner, 2026-10-05: "use a bit more space between different categories"): the items of a row further
# apart and each description nearer its own caps (HELP_ITEM_GAP 8 -> 12, HELP_DESC_GAP 6 -> 4), the key rows 2 px apart
# instead of 1 (HELP_ROW_PITCH), the two-line use description at the legend's 8-px pitch, the legend level with the
# caps' top -- docs/gp-p67-interface.md section 12
HELP_CAPS = [("W", 16, 11, 9), ("A", 6, 23, 9), ("S", 16, 23, 9), ("D", 26, 23, 9),
             ("UP", 66, 11, 11), ("LEFT", 54, 23, 11), ("DOWN", 66, 23, 11), ("RIGHT", 78, 23, 11),
             ("SPACE", 6, 36, 33), ("E", 41, 36, 9), ("CTRL", 6, 57, 27), ("1", 72, 57, 9), ("2", 83, 57, 9),
             ("3", 94, 57, 9), ("4", 105, 57, 9), (",", 6, 70, 7), (".", 15, 70, 6), ("ENTER", 72, 70, 33),
             ("ESC", 6, 83, 21), ("H", 104, 83, 9)]
HELP_LEGENDS = [("W", 18, 13), ("A", 8, 25), ("S", 18, 25), ("D", 28, 25), ("↑", 69, 13),
                ("←", 56, 25), ("↓", 69, 25), ("→", 80, 25), ("SPACE", 8, 38), ("E", 43, 38),
                ("CTRL", 8, 59), ("1", 74, 59), ("2", 85, 59), ("3", 96, 59), ("4", 107, 59), (",", 8, 72),
                (".", 17, 72), ("ENTER", 74, 72), ("ESC", 8, 85), ("H", 106, 85)]
HELP_TEXTS = [("OR", 39, 25), ("↑ ↓ MOVE", 96, 11), ("A D STRAFE", 96, 19), ("← → TURN", 96, 27),
              ("USE: DOORS,", 54, 38), ("SWITCHES, LIFTS", 54, 46), ("FIRE", 37, 59), ("WEAPONS", 118, 59),
              ("STRAFE", 25, 72), ("SELECT", 109, 72), ("MENU / BACK", 31, 85), ("HELP", 117, 85)]


def _ink(label, x0, y0, font=None):
    """the pixels `label` inks at (x0, y0), read straight from the font table"""
    from doomfj.menu import GLYPH_GAP, _GLYPHS
    font = _GLYPHS if font is None else font
    out, x = set(), x0
    for ch in label:
        rows = font[ch].split("|")
        out |= {(x + gx, y0 + gy) for gy, r in enumerate(rows) for gx, c in enumerate(r)
                if c == "#"}
        x += len(rows[0]) + GLYPH_GAP
    return out


def _outline(x0, y0, w, h):
    return {(x, y) for x in range(x0, x0 + w) for y in (y0, y0 + h - 1)} | \
           {(x, y) for y in range(y0, y0 + h) for x in (x0, x0 + w - 1)}


def _help_want():
    """the PINNED design as pixel sets per colour: {colour: pixels}"""
    from doomfj.menu import (CREDIT, HELP_CAP_H, HELP_TITLE, HELP_TITLE_Y, _SMALL_GLYPHS,
                             credit_box, text_width)
    cx, cy, _w, _h = credit_box(W, H)
    return {COLOURS[2]: _ink(HELP_TITLE, (W - text_width(HELP_TITLE)) // 2, HELP_TITLE_Y),
            COLOURS[1]: set().union(*(_ink(s, x, y) for s, x, y in HELP_LEGENDS + HELP_TEXTS)),
            COLOURS[3]: set().union(*(_outline(x, y, w, HELP_CAP_H) for _k, x, y, w in HELP_CAPS))
            | _ink(CREDIT, cx, cy, _SMALL_GLYPHS)}


def _help_got(grid):
    return {c: {(i % W, i // W) for i, p in enumerate(grid) if p == c} for c in COLOURS[1:]}


def test_the_help_layout_is_the_owners_keycap_design():
    """`help_layout` is the pinned design: the caps' boxes where the owner saw them -- two inverted-T
    clusters at HELP_CLUSTERS_Y, W/A/S/D caps 9 wide (the 5-wide letters + border + padding), the
    arrows' 11 (the 7-wide left / right arrows), 1 px apart; the key rows' caps fitting their
    legends, 2 px apart -- every legend centred in its cap, "OR" and the two-line legend beside the
    clusters, each item's description after its caps, the title centred"""
    from doomfj.menu import (GLYPH_H, HELP_CAP_H, HELP_CAP_PAD, HELP_CLUSTERS_Y, HELP_TITLE,
                             HELP_TITLE_Y, help_cap_legend, help_layout, text_width)
    caps, texts = help_layout(W, H)
    assert caps == HELP_CAPS
    assert HELP_CAP_H == GLYPH_H + 4 and HELP_CLUSTERS_Y == 11 and HELP_TITLE_Y == 2
    assert texts[0] == (HELP_TITLE, (W - text_width(HELP_TITLE)) // 2, HELP_TITLE_Y, "title")
    assert all(r == "text" for *_s, r in texts[1:])
    assert sorted((s, x, y) for s, x, y, _r in texts[1:]) == sorted(HELP_LEGENDS + HELP_TEXTS)
    for (key, cx, cy, cw), (legend, lx, ly) in zip(HELP_CAPS, HELP_LEGENDS):
        assert legend == help_cap_legend(key)
        left, right = lx - (cx + 1), (cx + cw - 1) - (lx + text_width(legend))
        assert left >= HELP_CAP_PAD and right >= HELP_CAP_PAD and abs(left - right) <= 1, key
        assert ly - (cy + 1) == HELP_CAP_PAD == (cy + HELP_CAP_H - 1) - (ly + GLYPH_H), key


def test_the_help_screen_draws_every_cap_and_glyph_where_the_design_says():
    """legibility, checked box by box and glyph by glyph: every cap's 1-px outline at its pinned
    rect in the CREDIT's dim gray, every legend and description in the 5x7 font in the text colour,
    the title in the highlight colour, the credit as on every screen -- and NOTHING else inked"""
    from doomfj.menu import help_pixels
    grid = help_pixels(W, H, COLOURS)
    assert set(grid) == set(COLOURS)
    got, want = _help_got(grid), _help_want()
    for c in COLOURS[1:]:
        assert got[c] == want[c], (c, sorted(got[c] ^ want[c])[:8])
    assert sum(1 for p in grid if p != COLOURS[0]) == sum(len(s) for s in want.values())


def test_the_help_design_check_rejects_a_moved_cap_and_a_wrong_legend(monkeypatch):
    """R9 for the check above: a cluster's caps 1 px further apart (M7 P4.1: the key rows now reach the right
    edge, so a wider KEY gap trips the screen assert first), or the left arrow's cap drawn with '<', or (M7 P6+P7) any
    one of the four spacings put back to its pre-2026-10-05 value, and the pinned design no longer matches the
    picture"""
    import doomfj.menu as menu
    want = _help_want()
    monkeypatch.setattr(menu, "HELP_CAP_GAP", menu.HELP_CAP_GAP + 1)
    assert _help_got(menu.help_pixels(W, H, COLOURS))[COLOURS[3]] != want[COLOURS[3]]
    monkeypatch.undo()
    monkeypatch.setattr(menu, "HELP_CAP_LEGENDS", dict(menu.HELP_CAP_LEGENDS, LEFT="<"))
    assert _help_got(menu.help_pixels(W, H, COLOURS))[COLOURS[1]] != want[COLOURS[1]]
    # M7 P6+P7: the pre-2026-10-05 spacing (the owner asked for more room between the categories) is rejected
    monkeypatch.undo()
    for name, old in (("HELP_ITEM_GAP", 8), ("HELP_DESC_GAP", 6), ("HELP_ROW_PITCH", menu.HELP_CAP_H + 1),
                      ("HELP_LINE_PITCH", menu.GLYPH_H + 2)):
        monkeypatch.setattr(menu, name, old)
        try:                                  # rejected: a different picture, or the screen assert (off the edge)
            assert _help_got(menu.help_pixels(W, H, COLOURS)) != {c: want[c] for c in COLOURS[1:]}, name
        except AssertionError as e:
            assert "outside the screen" in str(e), (name, e)
        monkeypatch.undo()


def test_the_help_says_what_the_owner_chose():
    """the words: the title, the clusters' legend, the use keys' two lines (HELP_USE_LINES, the
    owner's wording, 2026-10-02) and the other rows, in the owner's order -- and every character
    one the font draws (a missing one would print as a blank)"""
    from doomfj.menu import (HELP_CLUSTER_LEGEND, HELP_OR, HELP_ROWS, HELP_TITLE, HELP_USE_LINES,
                             _GLYPHS, help_cap_legend, help_key_names)
    assert HELP_TITLE == "HELP - CONTROLS" and HELP_OR == "OR"
    assert HELP_CLUSTER_LEGEND == ("\u2191 \u2193 MOVE", "A D STRAFE", "\u2190 \u2192 TURN")    # M7 P4.1
    assert HELP_USE_LINES == ("USE: DOORS,", "SWITCHES, LIFTS")
    assert HELP_ROWS == (((("SPACE", "E"), HELP_USE_LINES),),
                         ((("CTRL",), ("FIRE",)), (("1", "2", "3", "4"), ("WEAPONS",))),
                         (((",", "."), ("STRAFE",)), (("ENTER",), ("SELECT",))),
                         ((("ESC",), ("MENU / BACK",)), (("H",), ("HELP",))))
    labels = [HELP_TITLE, HELP_OR, *HELP_CLUSTER_LEGEND,
              *(help_cap_legend(k) for k in help_key_names()),
              *(line for row in HELP_ROWS for _keys, lines in row for line in lines)]
    assert all(ch in _GLYPHS for label in labels for ch in label)


def test_the_help_shows_a_cap_for_every_key_it_names():
    """`help_key_names` -- what tests/fj/test_keyboard_input.py runs through kb.poll -- is exactly
    the caps the screen draws, in screen order, and every one has a keycode"""
    from doomfj.menu import HELP_KEYCODES, help_key_names, help_layout
    names = help_key_names()
    assert names == ["W", "A", "S", "D", "UP", "LEFT", "DOWN", "RIGHT",
                     "SPACE", "E", "CTRL", "1", "2", "3", "4", ",", ".", "ENTER", "ESC", "H"]
    assert [k for k, *_r in help_layout(W, H)[0]] == names
    assert sorted(names) == sorted(HELP_KEYCODES)


def test_the_arrows_are_their_own_glyphs_and_the_selection_marker_is_untouched():
    """the arrow caps' glyphs: up / down 5x7 and left / right 7x7, the owner's prototype exactly,
    under their OWN characters -- '>' is the menu's selection marker and stays the glyph it was;
    nothing is drawn under '<', '^' or 'v'"""
    from doomfj.menu import GLYPH_H, _GLYPHS, glyph_width
    assert _GLYPHS["\u2191"] == "  #  | ### |# # #|  #  |  #  |  #  |  #  "
    assert _GLYPHS["\u2193"] == "  #  |  #  |  #  |  #  |# # #| ### |  #  "
    assert _GLYPHS["\u2190"] == "       |  #    | #     |#######| #     |  #    |       "
    assert _GLYPHS["\u2192"] == "       |    #  |     # |#######|     # |    #  |       "
    assert [glyph_width(c) for c in "\u2191\u2193\u2190\u2192"] == [5, 5, 7, 7]
    assert all(len(_GLYPHS[c].split("|")) == GLYPH_H for c in "\u2191\u2193\u2190\u2192")
    assert _GLYPHS[">"] == "#    | #   |  #  |   # |  #  | #   |#    "
    assert not {"<", "^", "v"} & set(_GLYPHS)


def test_the_help_screen_is_not_the_menu_and_is_not_blank():
    """R9: two mirrors that agree on a blank screen, or on the main menu, agree about nothing"""
    from doomfj.menu import help_pixels
    grid = help_pixels(W, H, COLOURS)
    assert len(set(grid)) == 4
    assert grid != pixels(W, H, ["DOOM ON FLIPJUMP", "", "NEW GAME", "HELP"], 2, COLOURS)
    assert sum(1 for p in grid if p == COLOURS[1]) > 1000      # 21 strings of 5x7 text
    assert sum(1 for p in grid if p == COLOURS[3]) > 500       # 20 caps' outlines


def test_a_wrong_help_picture_is_caught():
    """R9 negative control for the help's differential: one pixel of the oracle moved, and the
    device's decode of the stream must disagree with it"""
    from doomfj.menu import help_pixels, help_stream
    good = help_pixels(W, H, COLOURS)
    bad = list(good)
    bad[W * 20 + 30] ^= 0xFF
    screen = _present(help_stream(W, H, COLOURS))
    assert screen.pixel_indices == good and screen.pixel_indices != bad


@pytest.mark.parametrize("extra", [
    ((("SPACE", "E"), ("USE: DOORS, SWITCHES, LIFTS",)),),   # too wide: past the right edge
    ((("H",), ("THIS HELP",)),),                              # a fifth row: past the bottom edge
])
def test_the_help_layout_refuses_a_row_outside_the_screen(monkeypatch, extra):
    """R9 for the layout's screen assert: a row past the right or the bottom edge stops the
    generator instead of clipping the key map"""
    import doomfj.menu as menu
    monkeypatch.setattr(menu, "HELP_ROWS", menu.HELP_ROWS + (extra,))
    with pytest.raises(AssertionError, match="outside the screen"):
        menu.help_pixels(W, H, COLOURS)


def test_the_help_layout_refuses_a_table_in_the_credits_corner(monkeypatch):
    """R9 for the credit assert: the credit is bottom-RIGHT, beside the last key row, so the rule is the credit's box,
    not its rows. Clear today (the design test draws it); a credit raised into the last row (M7 P4.1: its HELP item
    now stands at the right) stops the generator"""
    import doomfj.menu as menu
    menu.help_pixels(W, H, COLOURS)
    monkeypatch.setattr(menu, "CREDIT_MARGIN", menu.CREDIT_MARGIN + 5)
    with pytest.raises(AssertionError, match="credit's corner"):
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
