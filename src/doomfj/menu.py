"""M3 — the menu, as a BAKED FRAME.

A menu screen is a picture that never changes, and the shipping renderer already presents pictures
as 0x0B column run-lists. So the menu needs no renderer at all: it is a constant byte stream, and
"draw the menu" is a run of `stl.output_char`s with compile-time operands. That makes it roughly a
thousand times cheaper than a world frame and removes the only thing about M3 that looked hard.

⚠ ONE GENERATOR, TWO MIRRORS. `pixels()` is what the oracle expects to see and `stream()` is what
fj emits; both are built from the same `_bitmap()`, and `tests/host/test_menu.py` proves they agree
by decoding the stream through the REAL `InMemoryScreen`. Writing the picture out twice — once as
pixels for the oracle and once as fj — is exactly how the two mirrors drift, and it is the failure
this repo has paid for three times.

The colours are DERIVED from the wad's own PLAYPAL (darkest entry, brightest entry, most saturated
red), not chosen as magic indices, so a different palette moves them together in both mirrors.

M7 P3.4 -- the HELP screen (docs/gp-help.md) is one more baked frame from this module: a key map
drawn as keycaps, not a list of lines, so it has its own layout (`help_layout`) but the same fonts,
colours, credit and encoder, and the same one-generator-two-mirrors rule (`help_pixels` /
`help_stream` / `help_fj`).
"""
from __future__ import annotations

# THE MENU'S TWO FONTS, one string per glyph -- rows separated by '|', '#' = ink; a glyph is as wide
# as its rows (`glyph_width`) and a line is laid out glyph by glyph (`text_width`), one column apart.
#
# The LINES use a 5x7 font (the owner, 2026-09-27, from rendered previews: "make it more clear that
# this is an M letter" -- in a 3x5 font no M can draw two strokes and the dip between them). 6 px a
# character with the gap, so a 160-wide screen fits 26 -- a menu needs 18.
_GLYPHS = {
    "A": " ### |#   #|#   #|#####|#   #|#   #|#   #", "B": "#### |#   #|#   #|#### |#   #|#   #|#### ",
    "C": " ### |#   #|#    |#    |#    |#   #| ### ", "D": "#### |#   #|#   #|#   #|#   #|#   #|#### ",
    "E": "#####|#    |#    |#### |#    |#    |#####", "F": "#####|#    |#    |#### |#    |#    |#    ",
    "G": " ### |#   #|#    |# ###|#   #|#   #| ####", "H": "#   #|#   #|#   #|#####|#   #|#   #|#   #",
    "I": " ### |  #  |  #  |  #  |  #  |  #  | ### ", "J": "  ###|   # |   # |   # |   # |#  # | ##  ",
    "K": "#   #|#  # |# #  |##   |# #  |#  # |#   #", "L": "#    |#    |#    |#    |#    |#    |#####",
    "M": "#   #|## ##|# # #|# # #|#   #|#   #|#   #", "N": "#   #|#   #|##  #|# # #|#  ##|#   #|#   #",
    "O": " ### |#   #|#   #|#   #|#   #|#   #| ### ", "P": "#### |#   #|#   #|#### |#    |#    |#    ",
    "Q": " ### |#   #|#   #|#   #|# # #|#  # | ## #", "R": "#### |#   #|#   #|#### |# #  |#  # |#   #",
    "S": " ####|#    |#    | ### |    #|    #|#### ", "T": "#####|  #  |  #  |  #  |  #  |  #  |  #  ",
    "U": "#   #|#   #|#   #|#   #|#   #|#   #| ### ", "V": "#   #|#   #|#   #|#   #|#   #| # # |  #  ",
    "W": "#   #|#   #|#   #|# # #|# # #|# # #| # # ", "X": "#   #|#   #| # # |  #  | # # |#   #|#   #",
    "Y": "#   #|#   #| # # |  #  |  #  |  #  |  #  ", "Z": "#####|    #|   # |  #  | #   |#    |#####",
    "0": " ### |#   #|#  ##|# # #|##  #|#   #| ### ", "1": "  #  | ##  |  #  |  #  |  #  |  #  | ### ",
    "2": " ### |#   #|    #|   # |  #  | #   |#####", "3": "#####|   # |  #  |   # |    #|#   #| ### ",
    "4": "   # |  ## | # # |#  # |#####|   # |   # ", "5": "#####|#    |#### |    #|    #|#   #| ### ",
    "6": "  ## | #   |#    |#### |#   #|#   #| ### ", "7": "#####|    #|   # |  #  | #   | #   | #   ",
    "8": " ### |#   #|#   #| ### |#   #|#   #| ### ", "9": " ### |#   #|#   #| ####|    #|   # | ##  ",
    " ": "   |   |   |   |   |   |   ", "-": "    |    |    |####|    |    |    ",
    ".": "  |  |  |  |  |##|##", ":": "  |##|##|  |##|##|  ",
    "/": "    #|    #|   # |  #  | #   |#    |#    ", ">": "#    | #   |  #  |   # |  #  | #   |#    ",
    ",": "   |   |   |   | ##| ##|#  ",                          # M7 P3.4: the help screen's
    # M7 P3.4: the help's ARROW keys, under their OWN characters -- '>' is the menu's selection
    # marker and must not change, so no arrow overrides '<' or '>'. Up / down 5x7; left / right
    # 7x7, a long shaft, so they read as arrows beside the 5-wide up / down (the owner's prototype).
    "↑": "  #  | ### |# # #|  #  |  #  |  #  |  #  ",                   # up
    "↓": "  #  |  #  |  #  |  #  |# # #| ### |  #  ",                   # down
    "←": "       |  #    | #     |#######| #     |  #    |       ",     # left
    "→": "       |    #  |     # |#######|     # |    #  |       ",     # right
}
GLYPH_W, GLYPH_H, GLYPH_GAP = 5, 7, 1
CELL_W = GLYPH_W + GLYPH_GAP            # the usual advance; the truncation budget below counts it

# The CREDIT uses the small 3x5 font (the owner chose it small and quiet), its M five columns with
# the middle stroke two rows deep, and a two-column full stop.
# P9 (the owner's play-test, 2026-10-10: "smaller text" on the HELP page): the help's caps, legends and descriptions are
# drawn in this font too, so it grew every character the help needs -- the digits, ',', ':', '/', '-' and the four
# arrows (the 5x7 arrows' own shapes, cut to five rows) -- and the two letters a 3-column grid drew badly were redrawn
# in the classic shapes: N four columns with its diagonal ("## |# #|# #|# #|#  " read as a lower-case n), W five, the
# mirror of M ("# #|# #|###|###|# #" read as an H). The credit's own glyphs (T O M H E . A P) are untouched.
# P9: the help shows key 5 (the launcher) and the bar's ARMS digits are this font -- "5" was the same picture as "S", so
# it is the classic angular five ("###|#  |## |  #|## ")
_SMALL_GLYPHS = {
    "A": "###|# #|###|# #|# #", "B": "## |# #|## |# #|## ", "C": "###|#  |#  |#  |###",
    "D": "## |# #|# #|# #|## ", "E": "###|#  |## |#  |###", "F": "###|#  |## |#  |#  ",
    "G": "###|#  |# #|# #|###", "H": "# #|# #|###|# #|# #", "I": "###| # | # | # |###",
    "J": "  #|  #|  #|# #|###", "K": "# #|# #|## |# #|# #", "L": "#  |#  |#  |#  |###",
    "M": "#   #|## ##|# # #|# # #|#   #", "N": "#  #|## #|# ##|#  #|#  #", "O": "###|# #|# #|# #|###",
    "P": "###|# #|###|#  |#  ", "Q": "###|# #|# #|###|  #", "R": "###|# #|## |# #|# #",
    "S": "###|#  |###|  #|###", "T": "###| # | # | # | # ", "U": "# #|# #|# #|# #|###",
    "V": "# #|# #|# #|# #| # ", "W": "#   #|#   #|# # #|# # #| # # ", "X": "# #|# #| # |# #|# #",
    "Y": "# #|# #| # | # | # ", "Z": "###|  #| # |#  |###",
    "0": "###|# #|# #|# #|###", "1": " # |## | # | # |###", "2": "###|  #|###|#  |###",
    "3": "###|  #| ##|  #|###", "4": "# #|# #|###|  #|  #", "5": "###|#  |## |  #|## ",
    "6": "###|#  |###|# #|###", "7": "###|  #|  #|  #|  #", "8": "###|# #|###|# #|###",
    "9": "###|# #|###|  #|###",
    " ": "   |   |   |   |   ", ".": "  |  |  |  |# ", ",": "  |  |  |  | #|# ", ":": " |#| |#| ",
    "/": "  #|  #| # |#  |#  ", "-": "   |   |###|   |   ",
    "↑": "  #  | ### |# # #|  #  |  #  ",                                 # up
    "↓": "  #  |  #  |# # #| ### |  #  ",                                 # down
    "←": "  #  | #   |#####| #   |  #  ",                                 # left
    "→": "  #  |   # |#####|   # |  #  ",                                 # right
}
SMALL_GLYPH_H = 5
# P9 (the owner's play-test, 2026-10-10: the 3x5 ',' read as a '/'): the comma is a DOT on the baseline (row 4, the full
# stop's row) with a TAIL one pixel below-left -- a sixth, DESCENDER row under the five, the one glyph that has it.
# Every 3x5 glyph is SMALL_GLYPH_H rows but those in SMALL_DESCENDERS, which have one more (`glyph_height`): the help
# layout measures a line by what it draws, so the descender stays inside a cap's padding and inside the category gaps.
SMALL_DESCENDERS = frozenset({","})

# M7 P1.5 (the owner, 2026-09-27): the creator's credit, drawn on every menu screen in the corner,
# in a dim gray (palette_colours' fourth colour). The fonts have capitals only; a domain name is
# case-insensitive, so this is the owner's "tomhe.app".
CREDIT = "TOMHE.APP"
CREDIT_MARGIN = 2                        # px from the right and bottom edges
CREDIT_LUMA = 0.4                        # the credit's gray: this fraction of the text's brightness


def glyph_width(ch: str, font=None) -> int:
    font = _GLYPHS if font is None else font
    return len(font.get(ch, font[" "]).split("|")[0])


def glyph_height(ch: str, font=None) -> int:
    """the rows `ch` draws in `font` (the lines' by default): the font's height, one more for a descender (P9)"""
    font = _GLYPHS if font is None else font
    return len(font.get(ch, font[" "]).split("|"))


def text_height(label: str, font=None) -> int:
    """the rows a one-line `label` draws from its top: its tallest glyph's (a descender reaches one below the rest)"""
    return max([glyph_height(ch, font) for ch in label] or [0])


def text_width(label: str, font=None) -> int:
    """the pixel width of `label` as drawn in `font` (the lines' by default): each glyph's own width,
    one gap between glyphs"""
    return sum(glyph_width(ch, font) for ch in label) + GLYPH_GAP * max(0, len(label) - 1)

# the protocol's own constants, from the device that decodes them -- NOT a third private copy.
# (tests/fj/stream_screen.py has the lab decoder's; this file had a second. R6 is one source.)
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_DITTO as DITTO
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_END as END
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_KEEP as KEEP                    # noqa: E402 (P10)
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_TOKENS_MAX_HEIGHT               # noqa: E402 (P10)


def palette_colours(palette_rgb) -> tuple:
    """(background, text, highlight, credit) palette indices, DERIVED from the wad's own PLAYPAL.

    `palette_rgb` is the flat RGB byte sequence (3 per entry) the emitter already bakes. Picking
    indices by hand would be magic numbers that a different palette silently invalidates. The
    credit (M7 P1.5) is the GRAY -- channels within 8 of each other -- whose brightness is nearest
    CREDIT_LUMA of the text's: a dim gray, from the same palette."""
    entries = [tuple(palette_rgb[3 * i:3 * i + 3]) for i in range(len(palette_rgb) // 3)]

    def luma(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    background = min(range(len(entries)), key=lambda i: luma(entries[i]))
    text = max(range(len(entries)), key=lambda i: luma(entries[i]))
    highlight = max(range(len(entries)),
                    key=lambda i: entries[i][0] - (entries[i][1] + entries[i][2]) / 2)
    grays = [i for i in range(len(entries)) if max(entries[i]) - min(entries[i]) <= 8]
    target = CREDIT_LUMA * luma(entries[text])
    credit = min(grays, key=lambda i: abs(luma(entries[i]) - target))
    return background, text, highlight, credit


def _draw(out, width, height, label, x0, y0, ink, font=None):
    """`label` at (x0, y0) in `font` (the lines' by default), glyph after glyph at their own widths;
    clipped to the screen"""
    font = _GLYPHS if font is None else font
    x = x0
    for ch in label:
        glyph = font.get(ch, font[" "]).split("|")
        for gy, row in enumerate(glyph):
            for gx, cell in enumerate(row):
                if cell == "#" and 0 <= x + gx < width and 0 <= y0 + gy < height:
                    out[(y0 + gy) * width + x + gx] = ink
        x += len(glyph[0]) + GLYPH_GAP


def _bitmap(width, height, lines, selected, colours):
    """The menu as a width*height list of palette indices. THE picture, for both mirrors: the lines
    centred in the 5x7 font, and the owner's CREDIT in the bottom-right corner, small (3x5) and in
    its dim gray."""
    background, text, highlight, credit = colours
    out = [background] * (width * height)
    if not lines:
        return out
    for row, line in enumerate(lines):
        ink = highlight if row == selected else text
        label = ("> " + line) if row == selected else ("  " + line)
        label = label.upper()[:width // CELL_W]
        x0 = max(0, (width - text_width(label)) // 2)
        _draw(out, width, height, label, x0, _line_y(height, len(lines), row), ink)
    _draw_credit(out, width, height, credit)
    return out


def _line_y(height, nlines: int, row: int) -> int:
    """the top row of line `row` of `nlines`: `_bitmap`'s lines are GLYPH_H + 2 apart, the block centred"""
    block_h = nlines * (GLYPH_H + 2) - 2
    return max(0, (height - block_h) // 2) + row * (GLYPH_H + 2)


def credit_box(width, height) -> tuple:
    """the credit's bounding box `(x, y, w, h)`: CREDIT_MARGIN px from the right and bottom edges"""
    w = text_width(CREDIT, _SMALL_GLYPHS)
    return width - CREDIT_MARGIN - w, height - CREDIT_MARGIN - SMALL_GLYPH_H, w, SMALL_GLYPH_H


def _draw_credit(out, width, height, ink):
    """the owner's CREDIT in the bottom-right corner, small (3x5): every baked screen carries it"""
    x, y, _w, _h = credit_box(width, height)
    _draw(out, width, height, CREDIT, x, y, ink, _SMALL_GLYPHS)


def pixels(width, height, lines, selected, colours):
    """What the ORACLE expects on screen."""
    return _bitmap(width, height, lines, selected, colours)


# -------------------------------------------------------------------------------------------------
# M7 P3.4 -- THE HELP SCREEN (docs/gp-help.md): the key map, ONLY the keys that work today
# (src/fj/input.fj's kb.poll), drawn as KEYCAPS -- the owner's choice on 2026-10-02 from rendered
# prototypes: the movement keys as the keyboard's two inverted-T clusters, W/A/S/D "OR" the arrows,
# with a two-line legend beside them; below, one row of caps per remaining action, what it does
# beside. P4 adds strafe, fire and the weapons, and moves A / D from turn to strafe -- and updates
# these with them (the owner's target map, docs/gp-help.md section 4).
HELP_TITLE = "HELP - CONTROLS"
# the inverted-T clusters, left to right, HELP_OR between them: each is (up, left, down, right)
HELP_CLUSTERS = (("W", "A", "S", "D"), ("UP", "LEFT", "DOWN", "RIGHT"))
HELP_OR = "OR"
# what a cap shows where it is not the key's own name: the arrows' own glyphs
HELP_CAP_LEGENDS = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→"}
# the legend beside the clusters, top to bottom. M7 P4.1 (the owner's key map, approved 2026-10-02): W / S and the up /
# down arrows move, A / D STRAFE, the left / right arrows turn
HELP_CLUSTER_LEGEND = ("↑ ↓ MOVE", "A D STRAFE", "← → TURN")
# the use keys' description -- the owner's wording (2026-10-02), ONE place to change it. P10 (the owner's second
# play-test, 2026-10-12: the TOMHE.APP credit crowded the last row, "H HELP"): ONE line now (the 3x5 font fits it, 149 of
# 160 px), which with HELP_TITLE_Y 1 and HELP_TITLE_GAP 4 lifts every key row 7 px -- the last row ends at y 90, two
# rows clear of the credit (y 93..97), and the categories keep P9's 6 empty rows between them
HELP_USE_LINES = ("USE: DOORS, SWITCHES, LIFTS",)
# below the clusters, rows of ITEMS -- (its keys, drawn as caps; its description's lines) -- laid left to right. M7
# P4.1: fire, the weapons and the second strafe pair joined the table, so a row holds up to two items to fit 100 rows.
# P9 (the owner, 2026-10-10: the rocket launcher on key 5 -- "1 2 3 4 5 WEAPONS"): five weapon caps no longer fit the
# second column (86 + 77 > 160), so the weapons are the row's FIRST item and FIRE its second -- the second column moves
# right to clear them (col2, `help_layout`)
HELP_ROWS = (
    ((("SPACE", "E"), HELP_USE_LINES),),
    ((("1", "2", "3", "4", "5"), ("WEAPONS",)), (("CTRL",), ("FIRE",))),
    (((",", "."), ("STRAFE",)), (("ENTER",), ("SELECT",))),
    ((("ESC",), ("MENU / BACK",)), (("H",), ("HELP",))),     # in the help, Esc closes it (owner 2026-10-02)
)
# every key name the screen shows (`help_key_names`), as the keyboard device's keycodes (the SDL
# codes pygame_window delivers; input.fj's table). tests/fj/test_keyboard_input.py runs kb.poll on
# each and requires it to DO something -- a held flag or a menu event -- so the screen cannot list a
# dead key.
HELP_KEYCODES = {"W": 0x77, "UP": 0x80, "S": 0x73, "DOWN": 0x81, "A": 0x61, "LEFT": 0x82,
                 "D": 0x64, "RIGHT": 0x83, "SPACE": 0x20, "E": 0x65, "ENTER": 0x0D, "ESC": 0x1B,
                 "H": 0x68,
                 # M7 P4.1: fire (ctrl -- pygame_window's 0x85), the number keys, the second strafe pair
                 "CTRL": 0x85, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34, ",": 0x2C, ".": 0x2E,
                 "5": 0x35}                                  # P9: the rocket launcher
# THE GEOMETRY, px. A cap is a 1-px box in the credit's dim gray with 1 px of padding round its
# legend, the legend centred; every cap of a cluster is as wide as its widest legend's cap (all 9: W and the arrows
# are five columns), and each cap of a key row fits its own legend.
#
# P9 (the owner's play-test, 2026-10-10: "smaller text and more spaces between categories"): every string but the title
# -- the caps' legends, "OR", the clusters' legend, the descriptions -- is in the SMALL 3x5 font (`HELP_FONT`; the
# title keeps the 5x7), so a cap is 9 rows high instead of 11, and the rows that frees go to the gaps BETWEEN the
# categories: HELP_SECTION_GAP (6) empty rows between the clusters and the first key row and between every two key
# rows (it was 2), HELP_TITLE_GAP (5) under the title. And every row's second item stands in ONE column with the
# clusters' legend (`help_layout`): the page reads as two columns of categories with a gutter between them.
HELP_FONT = _SMALL_GLYPHS                # the font of every help string but the title
HELP_TEXT_H = SMALL_GLYPH_H              # ...and its height
HELP_TITLE_Y = 1                         # the title's top row (P10: 2 -> 1)
HELP_TITLE_GAP = 4                       # empty rows under the title, above the clusters (P10: 5 -> 4)
HELP_X = 6                               # the left margin: the clusters and the key column
HELP_CLUSTERS_Y = HELP_TITLE_Y + GLYPH_H + HELP_TITLE_GAP       # the clusters' top row
HELP_CAP_BORDER = 1
HELP_CAP_PAD = 1
HELP_CAP_INSET = HELP_CAP_BORDER + HELP_CAP_PAD      # a cap's edge to its legend
HELP_CAP_H = HELP_TEXT_H + 2 * HELP_CAP_INSET       # every cap's outer height
HELP_CAP_GAP = 1                         # between a cluster's caps
HELP_OR_GAP = 4                          # either side of HELP_OR
HELP_LEGEND_GAP = 7                      # the last cluster to its legend (the second column's least x)
HELP_LEGEND_PITCH = HELP_TEXT_H + 2      # one legend line to the next: three lines beside the two cap rows
HELP_SECTION_GAP = 6                     # P9: empty rows between two categories (the clusters, each key row)
HELP_KEY_GAP = 2                         # between an item's caps
HELP_DESC_GAP = 4                        # an item's caps to its description
HELP_ITEM_GAP = 8                        # the least gutter between a row's first item and the second column (P9: 12 -> 8,
#                                          so the second column clears the five weapon caps and "HELP" the credit)
HELP_LINE_PITCH = HELP_TEXT_H + 1        # one description line to the next


def help_key_names() -> list:
    """every key name the help screen shows, in screen order: the clusters', then the rows'"""
    return ([k for cluster in HELP_CLUSTERS for k in cluster]
            + [k for row in HELP_ROWS for keys, _lines in row for k in keys])


def help_cap_legend(key: str) -> str:
    """what `key`'s cap shows: its own glyph (the arrows) or its name"""
    return HELP_CAP_LEGENDS.get(key, key)


def help_font(role: str):
    """the font a help string of `role` is drawn in: the title the lines' 5x7, everything else HELP_FONT (P9)"""
    return _GLYPHS if role == "title" else HELP_FONT


def help_text_width(label: str, role: str = "text") -> int:
    """the pixel width of a help string of `role`"""
    return text_width(label, help_font(role))


def help_cap_width(legend: str) -> int:
    """the outer width of the narrowest cap that holds `legend`"""
    return help_text_width(legend) + 2 * HELP_CAP_INSET


def _help_item_width(keys, lines) -> int:
    """an item's width: its caps, HELP_KEY_GAP apart, then HELP_DESC_GAP, then its widest description line"""
    caps = sum(help_cap_width(help_cap_legend(k)) for k in keys) + HELP_KEY_GAP * (len(keys) - 1)
    return caps + HELP_DESC_GAP + max(help_text_width(line) for line in lines)


def help_layout(width, height) -> tuple:
    """THE help screen's layout: `(caps, texts)` -- `caps` the keycaps as `(key, x, y, w)`, each an
    outer box HELP_CAP_H high; `texts` every string drawn, as `(label, x, y, role)`, role
    "title" (the highlight colour, the 5x7 font) or "text" (the text colour, HELP_FONT), the caps' legends among them.
    ASSERTED inside the screen, so a longer row or a smaller screen stops the emitter instead of
    clipping the map.

    P9: two columns. The clusters and every row's FIRST item stand at HELP_X; the clusters' legend and every row's
    SECOND item stand at one x -- HELP_LEGEND_GAP past the clusters, or further right if some row's first item would
    come nearer it than HELP_ITEM_GAP; a third item would follow its row's second, HELP_ITEM_GAP on. Each key row
    stands HELP_SECTION_GAP empty rows below what the one above it DRAWS (a two-line description reaches below its
    caps)."""
    caps, texts = [], [(HELP_TITLE, (width - help_text_width(HELP_TITLE, "title")) // 2, HELP_TITLE_Y, "title")]

    def cap(key, x, y, w):
        legend = help_cap_legend(key)
        caps.append((key, x, y, w))
        texts.append((legend, x + (w - help_text_width(legend)) // 2, y + HELP_CAP_INSET, "text"))

    # the clusters: an inverted T each -- the up cap over the middle of left, down, right
    bottom_y = HELP_CLUSTERS_Y + HELP_CAP_H + HELP_CAP_GAP
    x = HELP_X
    for i, (up, left, down, right) in enumerate(HELP_CLUSTERS):
        if i:
            texts.append((HELP_OR, x + HELP_OR_GAP, bottom_y + HELP_CAP_INSET, "text"))
            x += HELP_OR_GAP + help_text_width(HELP_OR) + HELP_OR_GAP
        w = max(help_cap_width(help_cap_legend(k)) for k in (up, left, down, right))
        cap(up, x + w + HELP_CAP_GAP, HELP_CLUSTERS_Y, w)
        for col, key in enumerate((left, down, right)):
            cap(key, x + col * (w + HELP_CAP_GAP), bottom_y, w)
        x += 3 * w + 2 * HELP_CAP_GAP
    # the second column: the legend's x, or HELP_ITEM_GAP right of the widest first item of a two-item row
    col2 = max([x + HELP_LEGEND_GAP] + [HELP_X + _help_item_width(*row[0]) + HELP_ITEM_GAP
                                        for row in HELP_ROWS if len(row) > 1])
    for row, line in enumerate(HELP_CLUSTER_LEGEND):           # level with the caps' top
        texts.append((line, col2, HELP_CLUSTERS_Y + row * HELP_LEGEND_PITCH, "text"))
    # the key rows: each item's caps from its x, its description after them
    y = bottom_y + HELP_CAP_H + HELP_SECTION_GAP
    for row in HELP_ROWS:
        x, drawn = HELP_X, HELP_CAP_H
        for k, (keys, lines) in enumerate(row):
            if k == 1:
                x = col2
            for key in keys:
                w = help_cap_width(help_cap_legend(key))
                cap(key, x, y, w)
                x += w + HELP_KEY_GAP
            x += HELP_DESC_GAP - HELP_KEY_GAP
            for i, line in enumerate(lines):
                texts.append((line, x, y + HELP_CAP_INSET + i * HELP_LINE_PITCH, "text"))
            # what the item DRAWS below the row's top: every description line's rows -- a descender too (P9: the
            # comma's tail), so the next category keeps its HELP_SECTION_GAP empty rows
            drawn = max([drawn] + [HELP_CAP_INSET + i * HELP_LINE_PITCH + text_height(line, HELP_FONT)
                                   for i, line in enumerate(lines)])
            x += max(help_text_width(line) for line in lines) + HELP_ITEM_GAP
        y += drawn + HELP_SECTION_GAP
    boxes = [(x, y, w, HELP_CAP_H) for _k, x, y, w in caps] + \
            [(x, y, help_text_width(label, r), text_height(label, help_font(r))) for label, x, y, r in texts]
    outside = [(x, y, w, h) for x, y, w, h in boxes
               if x < 0 or y < 0 or x + w > width or y + h > height]
    assert not outside, "the help layout is outside the screen: %r" % outside
    return caps, texts


def _draw_box(out, width, x0, y0, w, h, ink):
    """the 1-px outline of a w*h rectangle at (x0, y0): a keycap"""
    for x in range(x0, x0 + w):
        out[y0 * width + x] = out[(y0 + h - 1) * width + x] = ink
    for y in range(y0, y0 + h):
        out[y * width + x0] = out[y * width + x0 + w - 1] = ink


def _help_bitmap(width, height, colours):
    """The help screen as a width*height list of palette indices -- THE picture, for both mirrors:
    `help_layout` drawn -- the caps' boxes in the credit's dim gray, the title in the highlight
    colour, every other string (the caps' legends among them) in the text colour -- and the credit.
    ASSERTED clear of the credit: no pixel of the table inside the credit's box (the credit is
    bottom-right and the H cap reaches as low on the left, so a whole-row rule would be wrong)."""
    background, text, highlight, credit = colours
    out = [background] * (width * height)
    caps, texts = help_layout(width, height)
    for _key, x, y, w in caps:
        _draw_box(out, width, x, y, w, HELP_CAP_H, credit)
    for label, x, y, role in texts:
        _draw(out, width, height, label, x, y, highlight if role == "title" else text, help_font(role))
    cx, cy, cw, ch = credit_box(width, height)
    over = [(x, y) for y in range(max(0, cy), min(height, cy + ch))
            for x in range(max(0, cx), min(width, cx + cw)) if out[y * width + x] != background]
    assert not over, "the help table reaches the credit's corner: %r" % over[:4]
    _draw_credit(out, width, height, credit)
    return out


def help_pixels(width, height, colours):
    """What the ORACLE expects on screen while the help is up."""
    return _help_bitmap(width, height, colours)


def help_stream(width, height, colours) -> bytes:
    """The 0x0B frame that paints exactly `help_pixels()` -- `stream()`'s encoder."""
    return _encode(_help_bitmap(width, height, colours), width, height)


def help_fj(width, height, colours, label: str = "menu_help", end_marker: bool = True) -> str:
    """The baked help frame as fj -- `fj()`'s shape: one `stl.output_char` per stream byte."""
    return _fj_text(help_stream(width, height, colours), label, end_marker,
                    "M7 P3.4: the baked help frame")


def stream(width, height, lines, selected, colours) -> bytes:
    """The 0x0B frame that paints exactly `pixels()`.

    Column-major run-lists, with DITTO (0xFE) for a column identical to its left neighbour — which
    on a menu is most of them, and which exercises the one compression the protocol has. Column 0
    is never dittoed: it has no left neighbour, and the device refuses it."""
    # ⚠ THE PROTOCOL BOUNDS THE RESOLUTION, and R6 forbids assuming it. A column tag must be
    # distinguishable from DITTO/END, and a run's `y2` is one byte, so this encoder is correct only
    # while width < 0xFE and height <= 0xFF. At 160x100 that is far off; assert rather than assume,
    # because a resolution change would otherwise corrupt the stream instead of failing.
    return _encode(_bitmap(width, height, lines, selected, colours), width, height)


def _encode(grid, width, height) -> bytes:
    """a width*height picture -> its 0x0B stream (see `stream`): every baked screen's ONE encoder"""
    assert width < DITTO, "0x0B column tags must stay below DITTO (0xFE); width=%d" % width
    assert height <= END, "0x0B run bounds are one byte; height=%d" % height
    out = bytearray([0x0B])
    previous = None
    for x in range(width):
        column = [grid[y * width + x] for y in range(height)]
        out.append(x)
        if previous is not None and column == previous:
            out.append(DITTO)
            previous = column
            continue
        y = 0
        while y < height:
            y2 = y + 1
            while y2 < height and column[y2] == column[y]:
                y2 += 1
            out += bytes([y2, column[y]])
            y = y2
        out.append(END)
        previous = column
    out.append(END)
    return bytes(out)


def fj(width, height, lines, selected, colours, label: str = "menu_frame",
       end_marker: bool = True) -> str:
    """The baked frame as fj: one `stl.output_char` per stream byte, all compile-time operands.

    ~2 ops per byte, and a menu stream is ~1 kB — so a menu frame costs order 2,000 ops against a
    world frame's ~28,000,000. The mode flag that chooses between them is the whole of M3's cost.
    """
    return _fj_text(stream(width, height, lines, selected, colours), label, end_marker,
                    "M3: the baked menu frame")


def _fj_text(data: bytes, label: str, end_marker: bool, what: str) -> str:
    """a stream as fj: one `stl.output_char` per byte under `label`"""
    if not end_marker:
        # the caller supplies the end-of-frame byte from a SHARED tail -- see
        # wall_renderer._menu_lines, where both frame producers fall into one tail
        assert data[-1] == END
        data = data[:-1]
    body = "\n".join("    stl.output_char %d" % b for b in data)
    return ("// %s -- %d bytes of 0x0B column run-lists, all constants\n"
            "%s:\n%s\n" % (what, len(data), label, body))

# -------------------------------------------------------------------------------------------------
# P10 -- LEVEL COMPLETE'S STATS (the owner's play-test, 2026-10-12: "should have some stats, and return to main menu (as
# start of the game) with any key pressed"; docs/gp-p10-plan.md). ONE baked frame -- the title, each row's label and
# its value's fixed glyphs, the prompt -- and DIGIT SLOTS over it: a slot's digit is the program's at run time
# (doomfj.statcode computes them), drawn by that slot's column records for that digit AFTER the frame, the way the bar
# draws its numbers. One layout (`level_done_layout`) places both mirrors' glyphs: `level_done_pixels` is the oracle's
# picture, `level_done_stream` + `level_done_digit_records` the program's bytes, and tests/host/test_menu.py decodes
# the second through the real InMemoryScreen against the first.
LEVEL_DONE_TITLE = "LEVEL COMPLETE"
LEVEL_DONE_PROMPT = "PRESS ANY KEY"
# a row's VALUE TEMPLATE: "D" a digit slot, "_" a digit-wide blank, anything else a fixed glyph. The secrets' total is
# the map's -- the same on every skill -- so it is fixed glyphs (`level_done_rows`); the kills' and items' totals are
# the skill's, so they are slots
STAT_LABEL_GAP = 2 * CELL_W              # the widest label to the values' column
DIGIT_BLANK = 10                         # a slot's "no digit" (a leading zero): hudcode.BLANK's twin
TIME_CAP = 100 * 60 - 1                  # 99:59 -- the most the four time slots show


def level_done_rows(nsecret: int, count_digits: int = 2) -> list:
    """the stats' rows, (label, value template): KILLS and ITEMS "found / total", SECRETS "found / total" (one slot:
    a map has at most 9), TIME "mm:ss". M8 F1.1: `count_digits` slots per count -- 2, or 3 on a map with more than
    99 monsters or items (statcode.count_digits, the one rule)"""
    assert 0 <= nsecret <= 9, "the secrets found are ONE digit slot: the map has %d secret sectors" % nsecret
    assert count_digits in (2, 3), count_digits
    d = "D" * count_digits
    return [("KILLS", "%s / %s" % (d, d)), ("ITEMS", "%s / %s" % (d, d)), ("SECRETS", "_D / _%d" % nsecret),
            ("TIME", "DD:DD")]


def count_slots(count_digits: int) -> int:
    """M8 F1.1: the digit slots of LEVEL COMPLETE -- kills, total kills, items, total items (`count_digits` each), the
    secrets (1) and the time (4): 13 at 2 digits, 17 at 3"""
    return 4 * count_digits + 5


def _template_cells(template: str, x0: int) -> list:
    """[(x, ch)]: each template character's left x -- glyph after glyph, GLYPH_GAP apart, "D" and "_" a digit wide"""
    assert all(glyph_width(d) == GLYPH_W for d in "0123456789"), "a digit slot is GLYPH_W wide"
    out, x = [], x0
    for ch in template:
        out.append((x, ch))
        x += (GLYPH_W if ch in "D_" else glyph_width(ch)) + GLYPH_GAP
    return out


def _template_width(template: str) -> int:
    cells = _template_cells(template, 0)
    x, ch = cells[-1]
    return x + (GLYPH_W if ch in "D_" else glyph_width(ch))


def level_done_layout(width, height, nsecret: int, count_digits: int = 2) -> tuple:
    """-> (lines, selected, rows, slots): `_bitmap`'s lines -- the title, the prompt, and blank lines where the stats
    go -- and its highlighted line (the prompt); each stat row as (label x, y, label, [(x, fixed glyph)]); and the
    digit slots' top-left (x, y) in `stats_digits`' order. The rows are `_bitmap`'s own line positions; the labels
    share a left edge, the values another (the block centred)"""
    rows = level_done_rows(nsecret, count_digits)
    lines = [LEVEL_DONE_TITLE, ""] + [""] * len(rows) + ["", LEVEL_DONE_PROMPT]
    label_w = max(text_width(label) for label, _t in rows)
    value_w = max(_template_width(t) for _l, t in rows)
    # M8 F1.1: the block must fit -- the max(0, ...) below would clamp a wider one silently, off-centre
    assert label_w + STAT_LABEL_GAP + value_w <= width, ("LEVEL COMPLETE's stats do not fit", width, count_digits)
    x_label = max(0, (width - (label_w + STAT_LABEL_GAP + value_w)) // 2)
    x_value = x_label + label_w + STAT_LABEL_GAP
    out_rows, slots = [], []
    for k, (label, template) in enumerate(rows):
        y = _line_y(height, len(lines), 2 + k)
        cells = _template_cells(template, x_value)
        out_rows.append((x_label, y, label, [(x, ch) for x, ch in cells if ch not in "D_"]))
        slots += [(x, y) for x, ch in cells if ch == "D"]
    return lines, len(lines) - 1, out_rows, slots


def _two_digits(v: int, lead_blank: bool = True) -> list:
    assert 0 <= v <= 99, v
    tens, ones = divmod(v, 10)
    return [DIGIT_BLANK if lead_blank and not tens else tens, ones]


def count_codes(v: int, count_digits: int = 2) -> list:
    """M8 F1.1: a count's slot codes, most significant first, every leading zero a DIGIT_BLANK (the ones always shown)
    -- `_two_digits` at 2; ONE rule for both mirrors (statcode bakes a skill's totals through it)"""
    assert 0 <= v < 10 ** count_digits, (v, count_digits)
    ds = [int(c) for c in str(v).rjust(count_digits, "0")]
    k = 0
    while k < count_digits - 1 and ds[k] == 0:
        ds[k] = DIGIT_BLANK
        k += 1
    return ds


def stats_digits(kills: int, total_kills: int, items: int, total_items: int, secrets: int, seconds: int,
                 count_digits: int = 2) -> list:
    """the digit slots' codes (0..9, or DIGIT_BLANK for a leading zero) for these stats, in `level_done_layout`'s slot
    order: kills / total, items / total, secrets, then the time as mm:ss -- the minutes without a leading zero, the
    seconds with one, both capped at 99:59 (TIME_CAP). What doomfj.statcode's fj computes at run time. M8 F1.1: the
    four counts in `count_digits` slots each (statcode.count_digits)"""
    assert 0 <= secrets <= 9, secrets
    mm, ss = divmod(min(seconds, TIME_CAP), 60)
    return (count_codes(kills, count_digits) + count_codes(total_kills, count_digits) + count_codes(items, count_digits)
            + count_codes(total_items, count_digits) + [secrets] + _two_digits(mm) + _two_digits(ss, lead_blank=False))


def _level_done_bitmap(width, height, colours, nsecret: int, digits=None, count_digits: int = 2):
    """LEVEL COMPLETE: `_bitmap`'s title, prompt and credit, the labels in the text colour, the values -- their fixed
    glyphs and, with `digits`, each slot's digit -- in the highlight colour. `digits` None: the slots left empty (the
    program's baked frame)"""
    _background, text, highlight, _credit = colours
    lines, selected, rows, slots = level_done_layout(width, height, nsecret, count_digits)
    out = _bitmap(width, height, lines, selected, colours)
    for x_label, y, label, glyphs in rows:
        _draw(out, width, height, label, x_label, y, text)
        for x, ch in glyphs:
            _draw(out, width, height, ch, x, y, highlight)
    if digits is not None:
        assert len(digits) == len(slots), (len(digits), len(slots))
        for (x, y), d in zip(slots, digits):
            if d != DIGIT_BLANK:
                _draw(out, width, height, str(d), x, y, highlight)
    return out


def level_done_pixels(width, height, colours, nsecret: int, digits) -> list:
    """What the ORACLE expects on LEVEL COMPLETE, the slots showing `digits` (`stats_digits`) -- M8 F1.1: their count
    names the layout (count_slots: 13 two-digit counts, 17 three)"""
    nd = 2 if digits is None else {count_slots(2): 2, count_slots(3): 3}[len(digits)]
    return _level_done_bitmap(width, height, colours, nsecret, digits, nd)


def level_done_stream(width, height, colours, nsecret: int, count_digits: int = 2) -> bytes:
    """the program's baked LEVEL COMPLETE frame: everything but the digits (its slots empty), ending in END"""
    return _encode(_level_done_bitmap(width, height, colours, nsecret, None, count_digits), width, height)


def level_done_fj(width, height, colours, nsecret: int, label: str = "menu_level_done",
                  end_marker: bool = True) -> str:
    """the baked LEVEL COMPLETE frame as fj, its slots EMPTY -- a menu with no World to count (a test harness's);
    the game tier draws the digits over it (doomfj.statcode.frame_lines)"""
    return _fj_text(level_done_stream(width, height, colours, nsecret), label, end_marker,
                    "P10: the baked LEVEL COMPLETE frame (no digits)")


def level_done_digit_records(width, height, colours, nsecret: int, slot: int, digit: int,
                             count_digits: int = 2) -> bytes:
    """slot `slot` showing `digit`, as column records drawn AFTER the frame (no frame END): per glyph column with ink,
    [x] then [KEEP][y][y2][ink] per vertical run of ink, then the column's END -- KEEP over the gaps, so the frame's
    background shows between the runs. A blank digit is no records at all"""
    _background, _text, highlight, _credit = colours
    assert height <= COLLINES_TOKENS_MAX_HEIGHT, "KEEP is a token only on a screen of <= 251 rows"
    if digit == DIGIT_BLANK:
        return b""
    assert 0 <= digit <= 9, digit
    _lines, _sel, _rows, slots = level_done_layout(width, height, nsecret, count_digits)
    x0, y0 = slots[slot]
    glyph = _GLYPHS[str(digit)].split("|")
    out = bytearray()
    for gx in range(len(glyph[0])):
        runs, gy = [], 0
        while gy < len(glyph):
            if glyph[gy][gx] != "#":
                gy += 1
                continue
            e = gy + 1
            while e < len(glyph) and glyph[e][gx] == "#":
                e += 1
            runs.append((y0 + gy, y0 + e))
            gy = e
        if not runs:
            continue
        out.append(x0 + gx)
        for ys, ye in runs:
            out += bytes([KEEP, ys, ye, highlight])
        out.append(END)
    return bytes(out)


# -------------------------------------------------------------------------------------------------
# M7 P1.5 -- THE MENU'S RULES, the oracle side (docs/gp-skill-menu.md). The program's side is the fj
# that wall_renderer.menu_state_lines generates; this is plain Python from the same document, and
# every check that drives a program through its menu steps THIS: tests/fj/test_skill_menu.py (the
# lines, on a synthetic level), m2_std_gate and m3_gate (the shipped binary), gp/probe.py.

# the keyboard device's keycodes the menu hears (src/fj/input.fj's table): enter and esc, and the
# forward keys (w, up arrow) as "up" and the back keys (s, down arrow) as "dn". Down edges only.
# M7 P3.4: 'h' as "help" (the device has no F1; docs/gp-help.md).
# P10: and "any" -- EVERY key's down edge, these and every other (the poll's `ev_any`; keyboard.frame_keys adds it) --
# which only LEVEL COMPLETE acts on
MENU_KEYS = {0x0D: "enter", 0x1B: "esc", 0x77: "up", 0x80: "up", 0x73: "dn", 0x81: "dn",
             0x68: "help"}
ANY_KEY_EVENT = "any"
# M7 P2a.2 -- `menu_scr`'s third screen: LEVEL COMPLETE, opened by the exit switch (docs/gp-exit.md)
LEVEL_DONE_SCR = 2
# M7 P3.4 (docs/gp-help.md) -- the HELP screen, one picture under two ids, because closing it goes
# back to where it was opened from: HELP_MENU_SCR from the main menu (closes to the main menu, HELP
# highlighted), HELP_GAME_SCR from the world (closes to the world). And the main menu now has two
# items, NEW GAME and HELP: menu_scr 0 is the main menu with NEW GAME highlighted, MAIN_HELP_SCR the
# same menu with HELP highlighted. No new persisted cell: `menu_scr` already persists.
HELP_MENU_SCR = 3
HELP_GAME_SCR = 4
MAIN_HELP_SCR = 5
HELP_SCREENS = (HELP_MENU_SCR, HELP_GAME_SCR)
# P9 (the owner's play-test, 2026-10-10): the main menu's third item, EXIT, under HELP -- menu_scr MAIN_EXIT_SCR is the
# main menu with EXIT highlighted, and enter on it HALTS the program (wall_renderer's `mn_exit`, a jump-to-self: the
# interpreter ends "Looping" and the window closes). MENU_HALTED is NOT a value the program's `menu_scr` ever holds:
# it is the oracle's word for "the program has stopped" -- no frame is presented on the halting frame or after it, and
# menu_step leaves it where it is.
MAIN_EXIT_SCR = 6
MENU_HALTED = -1
# P10 (the owner's play-test, 2026-10-12: "Add menu resume when possible") -- the main menu's RESUME item, at the top
# and highlighted, ONLY while a game is in progress: menu_scr MAIN_RESUME_SCR is the main menu with RESUME
# highlighted. "In progress" is the program's persisted `g_live`: 0 at boot, 1 from NEW GAME on, 0 again when LEVEL
# COMPLETE is left -- so the boot menu and the menu after a finished level (the owner: "return to main menu (as start
# of the game)") have no RESUME, and esc on them does nothing.
MAIN_RESUME_SCR = 7
# P10: LEVEL COMPLETE's HOLD -- its first frames ignore every key, so a press already on its way when the exit is used
# (a tap of forward, of fire) cannot skip the stats before they are seen. The exit opens the screen at
# LEVEL_DONE_ENTER, and each frame counts it down to LEVEL_DONE_HOLD_LAST and then to LEVEL_DONE_SCR, which takes any
# key: LEVEL_DONE_ENTER - LEVEL_DONE_HOLD_LAST + 1 frames (8: 0.4 s at the 20 fps cap) with the picture and no key.
# `menu_scr` nibble values no other screen uses, so the hold needs no cell of its own
LEVEL_DONE_ENTER = 15
LEVEL_DONE_HOLD_LAST = 8
LEVEL_DONE_SCREENS = (LEVEL_DONE_SCR,) + tuple(range(LEVEL_DONE_HOLD_LAST, LEVEL_DONE_ENTER + 1))


def menu_step(mode: int, scr: int, sel: int, events, live: int) -> tuple:
    """One frame of the menu -> `(mode, scr, sel, new_game, live)`.

    `mode` is 1 on a menu frame and 0 in the world; `scr` 0 is the main menu (NEW GAME
    highlighted), 1 the skill screen and LEVEL_DONE_SCR (2) the level-complete screen the exit opens; M7 P3.4:
    MAIN_HELP_SCR (5) is the main menu with HELP highlighted, HELP_MENU_SCR (3) and HELP_GAME_SCR (4) the help screen
    opened from the main menu and from the world. `sel` is the highlighted skill, an index into
    wall_renderer.SKILLS. `events` is the set of this frame's events ("esc", "enter", "help", "up",
    "dn", and P10's "any"), and the FIRST of them in that order is the one acted on. `new_game` is the chosen skill's
    index on the frame NEW GAME is picked -- that frame restarts the level at the skill and then
    runs the world's tic, as the program does -- and None on every other frame. `live` (P10) is whether a game is in
    progress (the program's `g_live`).

    M7 P3.4 (docs/gp-help.md): in the world, h opens the help (HELP_GAME_SCR); on the main menu, up
    / down move between the items (clamped), and enter on HELP -- or h on any item --
    opens it (HELP_MENU_SCR); on the help screen, esc or h close it, back to where it was opened
    from: the main menu with HELP highlighted, or the world. The skill screen and LEVEL COMPLETE
    ignore h.

    P9 (the owner's play-test, 2026-10-10): the main menu's EXIT item (MAIN_EXIT_SCR, 6), under HELP. On EXIT, h opens
    the help (closing, as from any other item, to HELP highlighted), and ENTER HALTS the program: `scr` becomes
    MENU_HALTED, which no later frame leaves (the program presents nothing more).

    P10 (the owner's play-test, 2026-10-12): `live`.
      * RESUME (MAIN_RESUME_SCR, 7) is the main menu's first item while `live`; esc or enter in the world open the
        menu ON it (without `live`, on NEW GAME), and esc or enter on it resume the world. Up from NEW GAME reaches
        it only while `live`.
      * On every main-menu item, esc resumes the world only while `live`; without a game it is no rule, and the
        next event in the order is acted on.
      * NEW GAME sets `live`; LEVEL COMPLETE leaves for the main menu on ANY key's down edge ("any"), clearing it --
        the menu as at boot, where `live` is 0 -- after its HOLD: the exit opens it at LEVEL_DONE_ENTER, and every
        frame counts down (LEVEL_DONE_ENTER .. LEVEL_DONE_HOLD_LAST, then LEVEL_DONE_SCR) whatever is pressed."""
    # The skills the screen offers are wall_renderer.SKILLS: ONE tuple for the emitter's screens,
    # its dispatch and these rules (R6 -- this module kept its own `MENU_SKILLS = 3` until the P1.5
    # review). Imported here, not at the top, because wall_renderer imports this module.
    from doomfj.wall_renderer import SKILLS
    if scr == MENU_HALTED:                          # P9: the program has halted -- nothing changes again
        return mode, scr, sel, None, live
    esc = "esc" in events and live                  # P10: esc resumes only a game in progress
    if mode == 0:                                   # the world: esc or enter opens the main menu
        if "esc" in events or "enter" in events:
            return 1, MAIN_RESUME_SCR if live else 0, sel, None, live      # P10: on RESUME
        if "help" in events:                        # M7 P3.4: h opens the help
            return 1, HELP_GAME_SCR, sel, None, live
        return 0, scr, sel, None, live
    if scr in HELP_SCREENS:                         # M7 P3.4: the help -- esc or h close it
        if "esc" in events or "help" in events:
            return (1, MAIN_HELP_SCR, sel, None, live) if scr == HELP_MENU_SCR else (0, 0, sel, None, live)
        return 1, scr, sel, None, live
    if scr == MAIN_RESUME_SCR:                      # P10: the main menu, RESUME highlighted
        if "esc" in events or "enter" in events:
            return 0, 0, sel, None, live            # resume the world where it was
        if "help" in events:
            return 1, HELP_MENU_SCR, sel, None, live
        if "dn" in events:                          # down to NEW GAME (up is clamped: RESUME is the first)
            return 1, 0, sel, None, live
        return 1, MAIN_RESUME_SCR, sel, None, live
    if scr == MAIN_HELP_SCR:                        # M7 P3.4: the main menu, HELP highlighted
        if esc:
            return 0, 0, sel, None, live
        if "enter" in events or "help" in events:
            return 1, HELP_MENU_SCR, sel, None, live
        if "up" in events:
            return 1, 0, sel, None, live
        if "dn" in events:                          # P9: down to EXIT
            return 1, MAIN_EXIT_SCR, sel, None, live
        return 1, MAIN_HELP_SCR, sel, None, live
    if scr == MAIN_EXIT_SCR:                        # P9: the main menu, EXIT highlighted
        if esc:
            return 0, 0, sel, None, live
        if "enter" in events:                       # the program halts
            return 1, MENU_HALTED, sel, None, live
        if "help" in events:
            return 1, HELP_MENU_SCR, sel, None, live
        if "up" in events:
            return 1, MAIN_HELP_SCR, sel, None, live
        return 1, MAIN_EXIT_SCR, sel, None, live    # (down is clamped: EXIT is the last item)
    if LEVEL_DONE_HOLD_LAST <= scr <= LEVEL_DONE_ENTER:   # P10: LEVEL COMPLETE's hold -- the picture, no key
        return 1, scr - 1 if scr > LEVEL_DONE_HOLD_LAST else LEVEL_DONE_SCR, sel, None, live
    if scr == LEVEL_DONE_SCR:                       # level complete: ANY key, on to the menu as at boot (P10)
        if ANY_KEY_EVENT in events:
            return 1, 0, sel, None, 0
        return 1, LEVEL_DONE_SCR, sel, None, live
    if scr == 0:                                    # the main menu, NEW GAME highlighted
        if esc:
            return 0, 0, sel, None, live            # resume the world where it was
        if "enter" in events:
            return 1, 1, sel, None, live            # NEW GAME: the skill screen
        if "help" in events:                        # M7 P3.4: h opens the help from here too
            return 1, HELP_MENU_SCR, sel, None, live
        if "up" in events and live:                 # P10: up to RESUME (clamped without a game)
            return 1, MAIN_RESUME_SCR, sel, None, live
        if "dn" in events:                          # M7 P3.4: down to HELP
            return 1, MAIN_HELP_SCR, sel, None, live
        return 1, 0, sel, None, live
    if "esc" in events:                             # the skill screen: back to the main menu
        return 1, 0, sel, None, live
    if "enter" in events:                           # start the highlighted skill: a game is in progress
        return 0, 0, sel, sel, 1
    if "up" in events:
        return 1, 1, max(0, sel - 1), None, live
    if "dn" in events:
        return 1, 1, min(len(SKILLS) - 1, sel + 1), None, live
    return 1, 1, sel, None, live
