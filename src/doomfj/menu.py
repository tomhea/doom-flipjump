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
_SMALL_GLYPHS = {
    "A": "###|# #|###|# #|# #", "B": "## |# #|## |# #|## ", "C": "###|#  |#  |#  |###",
    "D": "## |# #|# #|# #|## ", "E": "###|#  |## |#  |###", "F": "###|#  |## |#  |#  ",
    "G": "###|#  |# #|# #|###", "H": "# #|# #|###|# #|# #", "I": "###| # | # | # |###",
    "J": "  #|  #|  #|# #|###", "K": "# #|# #|## |# #|# #", "L": "#  |#  |#  |#  |###",
    "M": "#   #|## ##|# # #|# # #|#   #", "N": "## |# #|# #|# #|#  ", "O": "###|# #|# #|# #|###",
    "P": "###|# #|###|#  |#  ", "Q": "###|# #|# #|###|  #", "R": "###|# #|## |# #|# #",
    "S": "###|#  |###|  #|###", "T": "###| # | # | # | # ", "U": "# #|# #|# #|# #|###",
    "V": "# #|# #|# #|# #| # ", "W": "# #|# #|###|###|# #", "X": "# #|# #| # |# #|# #",
    "Y": "# #|# #| # | # | # ", "Z": "###|  #| # |#  |###",
    " ": "   |   |   |   |   ", ".": "  |  |  |  |# ",
}
SMALL_GLYPH_H = 5

# M7 P1.5 (the owner, 2026-09-27): the creator's credit, drawn on every menu screen in the corner,
# in a dim gray (palette_colours' fourth colour). The fonts have capitals only; a domain name is
# case-insensitive, so this is the owner's "tomhe.app".
CREDIT = "TOMHE.APP"
CREDIT_MARGIN = 2                        # px from the right and bottom edges
CREDIT_LUMA = 0.4                        # the credit's gray: this fraction of the text's brightness


def glyph_width(ch: str, font=None) -> int:
    font = _GLYPHS if font is None else font
    return len(font.get(ch, font[" "]).split("|")[0])


def text_width(label: str, font=None) -> int:
    """the pixel width of `label` as drawn in `font` (the lines' by default): each glyph's own width,
    one gap between glyphs"""
    return sum(glyph_width(ch, font) for ch in label) + GLYPH_GAP * max(0, len(label) - 1)

# the protocol's own constants, from the device that decodes them -- NOT a third private copy.
# (tests/fj/stream_screen.py has the lab decoder's; this file had a second. R6 is one source.)
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_DITTO as DITTO
from flipjump.interpreter.io_devices.ScreenIO import COLLINES_END as END


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
    block_h = len(lines) * (GLYPH_H + 2) - 2
    top = max(0, (height - block_h) // 2)
    for row, line in enumerate(lines):
        ink = highlight if row == selected else text
        label = ("> " + line) if row == selected else ("  " + line)
        label = label.upper()[:width // CELL_W]
        x0 = max(0, (width - text_width(label)) // 2)
        _draw(out, width, height, label, x0, top + row * (GLYPH_H + 2), ink)
    _draw_credit(out, width, height, credit)
    return out


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
# the legend beside the clusters: one line beside the top caps, one beside the bottom caps
HELP_CLUSTER_LEGEND = ("↑ ↓ MOVE", "← → TURN")
# the use keys' description, two lines -- the owner's wording (2026-10-02), ONE place to change it
HELP_USE_LINES = ("USE: DOORS,", "SWITCHES, LIFTS")
# below the clusters, one row per action: (its keys, drawn as caps; its description's lines)
HELP_ROWS = (
    (("SPACE", "E"), HELP_USE_LINES),
    (("ENTER",), ("SELECT",)),
    (("ESC",), ("MENU / BACK",)),                # in the help, Esc closes it (owner 2026-10-02)
    (("H",), ("THIS HELP",)),
)
# every key name the screen shows (`help_key_names`), as the keyboard device's keycodes (the SDL
# codes pygame_window delivers; input.fj's table). tests/fj/test_keyboard_input.py runs kb.poll on
# each and requires it to DO something -- a held flag or a menu event -- so the screen cannot list a
# dead key.
HELP_KEYCODES = {"W": 0x77, "UP": 0x80, "S": 0x73, "DOWN": 0x81, "A": 0x61, "LEFT": 0x82,
                 "D": 0x64, "RIGHT": 0x83, "SPACE": 0x20, "E": 0x65, "ENTER": 0x0D, "ESC": 0x1B,
                 "H": 0x68}
# THE GEOMETRY, px. A cap is a 1-px box in the credit's dim gray with 1 px of padding round its
# legend, the legend centred; every cap of a cluster is as wide as its widest legend's cap (W/A/S/D
# 9, the arrows 11), and each cap of a key row fits its own legend.
HELP_TITLE_Y = 2                         # the title's top row
HELP_X = 6                               # the left margin: the clusters and the key column
HELP_CLUSTERS_Y = 12                     # the clusters' top row
HELP_CAP_BORDER = 1
HELP_CAP_PAD = 1
HELP_CAP_INSET = HELP_CAP_BORDER + HELP_CAP_PAD      # a cap's edge to its legend
HELP_CAP_H = GLYPH_H + 2 * HELP_CAP_INSET           # every cap's outer height
HELP_CAP_GAP = 1                         # between a cluster's caps
HELP_OR_GAP = 4                          # either side of HELP_OR
HELP_LEGEND_GAP = 7                      # the last cluster to its legend
HELP_ROWS_GAP = 3                        # the clusters' bottom to the first key row
HELP_KEY_GAP = 2                         # between a key row's caps
HELP_DESC_GAP = 6                        # the widest key row to the descriptions
HELP_ROW_PITCH = HELP_CAP_H + 1          # one key row to the next...
HELP_LINE_PITCH = GLYPH_H + 2            # ...plus this per extra description line (menu pitch)


def help_key_names() -> list:
    """every key name the help screen shows, in screen order: the clusters', then the rows'"""
    return ([k for cluster in HELP_CLUSTERS for k in cluster]
            + [k for keys, _lines in HELP_ROWS for k in keys])


def help_cap_legend(key: str) -> str:
    """what `key`'s cap shows: its own glyph (the arrows) or its name"""
    return HELP_CAP_LEGENDS.get(key, key)


def help_cap_width(legend: str) -> int:
    """the outer width of the narrowest cap that holds `legend`"""
    return text_width(legend) + 2 * HELP_CAP_INSET


def help_layout(width, height) -> tuple:
    """THE help screen's layout: `(caps, texts)` -- `caps` the keycaps as `(key, x, y, w)`, each an
    outer box HELP_CAP_H high; `texts` every string drawn, as `(label, x, y, role)`, role
    "title" (the highlight colour) or "text" (the text colour), the caps' legends among them.
    ASSERTED inside the screen, so a longer row or a smaller screen stops the emitter instead of
    clipping the map."""
    caps, texts = [], [(HELP_TITLE, (width - text_width(HELP_TITLE)) // 2, HELP_TITLE_Y, "title")]

    def cap(key, x, y, w):
        legend = help_cap_legend(key)
        caps.append((key, x, y, w))
        texts.append((legend, x + (w - text_width(legend)) // 2, y + HELP_CAP_INSET, "text"))

    # the clusters: an inverted T each -- the up cap over the middle of left, down, right
    bottom_y = HELP_CLUSTERS_Y + HELP_CAP_H + HELP_CAP_GAP
    x = HELP_X
    for i, (up, left, down, right) in enumerate(HELP_CLUSTERS):
        if i:
            texts.append((HELP_OR, x + HELP_OR_GAP, bottom_y + HELP_CAP_INSET, "text"))
            x += HELP_OR_GAP + text_width(HELP_OR) + HELP_OR_GAP
        w = max(help_cap_width(help_cap_legend(k)) for k in (up, left, down, right))
        cap(up, x + w + HELP_CAP_GAP, HELP_CLUSTERS_Y, w)
        for col, key in enumerate((left, down, right)):
            cap(key, x + col * (w + HELP_CAP_GAP), bottom_y, w)
        x += 3 * w + 2 * HELP_CAP_GAP
    for row, line in enumerate(HELP_CLUSTER_LEGEND):
        texts.append((line, x + HELP_LEGEND_GAP,
                      HELP_CLUSTERS_Y + row * (HELP_CAP_H + HELP_CAP_GAP) + HELP_CAP_INSET, "text"))
    # the key rows: caps from the left margin, the descriptions in one column after the widest row
    keys_w = max(sum(help_cap_width(help_cap_legend(k)) for k in keys)
                 + HELP_KEY_GAP * (len(keys) - 1) for keys, _lines in HELP_ROWS)
    x_desc = HELP_X + keys_w + HELP_DESC_GAP
    y = bottom_y + HELP_CAP_H + HELP_ROWS_GAP
    for keys, lines in HELP_ROWS:
        x = HELP_X
        for key in keys:
            w = help_cap_width(help_cap_legend(key))
            cap(key, x, y, w)
            x += w + HELP_KEY_GAP
        for i, line in enumerate(lines):
            texts.append((line, x_desc, y + HELP_CAP_INSET + i * HELP_LINE_PITCH, "text"))
        y += HELP_ROW_PITCH + HELP_LINE_PITCH * (len(lines) - 1)
    boxes = [(x, y, w, HELP_CAP_H) for _k, x, y, w in caps] + \
            [(x, y, text_width(label), GLYPH_H) for label, x, y, _r in texts]
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
        _draw(out, width, height, label, x, y, highlight if role == "title" else text)
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
# M7 P1.5 -- THE MENU'S RULES, the oracle side (docs/gp-skill-menu.md). The program's side is the fj
# that wall_renderer.menu_state_lines generates; this is plain Python from the same document, and
# every check that drives a program through its menu steps THIS: tests/fj/test_skill_menu.py (the
# lines, on a synthetic level), m2_std_gate and m3_gate (the shipped binary), gp/probe.py.

# the keyboard device's keycodes the menu hears (src/fj/input.fj's table): enter and esc, and the
# forward keys (w, up arrow) as "up" and the back keys (s, down arrow) as "dn". Down edges only.
# M7 P3.4: 'h' as "help" (the device has no F1; docs/gp-help.md).
MENU_KEYS = {0x0D: "enter", 0x1B: "esc", 0x77: "up", 0x80: "up", 0x73: "dn", 0x81: "dn",
             0x68: "help"}
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


def menu_step(mode: int, scr: int, sel: int, events) -> tuple:
    """One frame of the menu -> `(mode, scr, sel, new_game)`.

    `mode` is 1 on a menu frame and 0 in the world; `scr` 0 is the main menu (NEW GAME
    highlighted), 1 the skill screen and LEVEL_DONE_SCR (2) the level-complete screen the exit opens
    -- esc or enter leave it for the main menu (M7 P2a.2); M7 P3.4: MAIN_HELP_SCR (5) is the main
    menu with HELP highlighted, HELP_MENU_SCR (3) and HELP_GAME_SCR (4) the help screen opened from
    the main menu and from the world. `sel` is the highlighted skill, an index into
    wall_renderer.SKILLS. `events` is the set of this frame's events ("esc", "enter", "help", "up",
    "dn"), and the FIRST of them in that order is the one acted on. `new_game` is the chosen skill's
    index on the frame NEW GAME is picked -- that frame restarts the level at the skill and then
    runs the world's tic, as the program does -- and None on every other frame.

    M7 P3.4 (docs/gp-help.md): in the world, h opens the help (HELP_GAME_SCR); on the main menu, up
    / down move between NEW GAME and HELP (clamped), and enter on HELP -- or h on either item --
    opens it (HELP_MENU_SCR); on the help screen, esc or h close it, back to where it was opened
    from: the main menu with HELP highlighted, or the world. The skill screen and LEVEL COMPLETE
    ignore h."""
    # The skills the screen offers are wall_renderer.SKILLS: ONE tuple for the emitter's screens,
    # its dispatch and these rules (R6 -- this module kept its own `MENU_SKILLS = 3` until the P1.5
    # review). Imported here, not at the top, because wall_renderer imports this module.
    from doomfj.wall_renderer import SKILLS
    if mode == 0:                                   # the world: esc or enter opens the main menu
        if "esc" in events or "enter" in events:
            return 1, 0, sel, None
        if "help" in events:                        # M7 P3.4: h opens the help
            return 1, HELP_GAME_SCR, sel, None
        return 0, scr, sel, None
    if scr in HELP_SCREENS:                         # M7 P3.4: the help -- esc or h close it
        if "esc" in events or "help" in events:
            return (1, MAIN_HELP_SCR, sel, None) if scr == HELP_MENU_SCR else (0, 0, sel, None)
        return 1, scr, sel, None
    if scr == MAIN_HELP_SCR:                        # M7 P3.4: the main menu, HELP highlighted
        if "esc" in events:
            return 0, 0, sel, None
        if "enter" in events or "help" in events:
            return 1, HELP_MENU_SCR, sel, None
        if "up" in events:
            return 1, 0, sel, None
        return 1, MAIN_HELP_SCR, sel, None
    if scr == LEVEL_DONE_SCR:                       # level complete: on to the main menu
        if "esc" in events or "enter" in events:
            return 1, 0, sel, None
        return 1, LEVEL_DONE_SCR, sel, None
    if scr == 0:                                    # the main menu, NEW GAME highlighted
        if "esc" in events:
            return 0, 0, sel, None                  # resume the world where it was
        if "enter" in events:
            return 1, 1, sel, None                  # NEW GAME: the skill screen
        if "help" in events:                        # M7 P3.4: h opens the help from here too
            return 1, HELP_MENU_SCR, sel, None
        if "dn" in events:                          # M7 P3.4: down to HELP
            return 1, MAIN_HELP_SCR, sel, None
        return 1, 0, sel, None
    if "esc" in events:                             # the skill screen: back to the main menu
        return 1, 0, sel, None
    if "enter" in events:                           # start the highlighted skill
        return 0, 0, sel, sel
    if "up" in events:
        return 1, 1, max(0, sel - 1), None
    if "dn" in events:
        return 1, 1, min(len(SKILLS) - 1, sel + 1), None
    return 1, 1, sel, None
