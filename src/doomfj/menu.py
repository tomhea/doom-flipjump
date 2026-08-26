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
"""
from __future__ import annotations

# a 3x5 font: one string of 5 rows, 3 columns each, '#' = ink. 4 px per character with the gap, so
# a 160-wide screen fits 40 characters — enough for a menu and nothing more, which is the point.
_GLYPHS = {
    "A": "###|# #|###|# #|# #", "B": "## |# #|## |# #|## ", "C": "###|#  |#  |#  |###",
    "D": "## |# #|# #|# #|## ", "E": "###|#  |## |#  |###", "F": "###|#  |## |#  |#  ",
    "G": "###|#  |# #|# #|###", "H": "# #|# #|###|# #|# #", "I": "###| # | # | # |###",
    "J": "  #|  #|  #|# #|###", "K": "# #|# #|## |# #|# #", "L": "#  |#  |#  |#  |###",
    "M": "# #|###|###|# #|# #", "N": "## |# #|# #|# #|#  ", "O": "###|# #|# #|# #|###",
    "P": "###|# #|###|#  |#  ", "Q": "###|# #|# #|###|  #", "R": "###|# #|## |# #|# #",
    "S": "###|#  |###|  #|###", "T": "###| # | # | # | # ", "U": "# #|# #|# #|# #|###",
    "V": "# #|# #|# #|# #| # ", "W": "# #|# #|###|###|# #", "X": "# #|# #| # |# #|# #",
    "Y": "# #|# #| # | # | # ", "Z": "###|  #| # |#  |###",
    "0": "###|# #|# #|# #|###", "1": " # |## | # | # |###", "2": "###|  #|###|#  |###",
    "3": "###|  #|###|  #|###", "4": "# #|# #|###|  #|  #", "5": "###|#  |###|  #|###",
    "6": "###|#  |###|# #|###", "7": "###|  #|  #|  #|  #", "8": "###|# #|###|# #|###",
    "9": "###|# #|###|  #|###",
    " ": "   |   |   |   |   ", "-": "   |   |###|   |   ", ".": "   |   |   |   | # ",
    ":": "   | # |   | # |   ", "/": "  #|  #| # |#  |#  ", ">": "#  | # |  #| # |#  ",
}
GLYPH_W, GLYPH_H, GLYPH_GAP = 3, 5, 1
CELL_W = GLYPH_W + GLYPH_GAP

DITTO, END = 0xFE, 0xFF


def palette_colours(palette_rgb) -> tuple:
    """(background, text, highlight) palette indices, DERIVED from the wad's own PLAYPAL.

    `palette_rgb` is the flat RGB byte sequence (3 per entry) the emitter already bakes. Picking
    indices by hand would be two magic numbers that a different palette silently invalidates."""
    entries = [tuple(palette_rgb[3 * i:3 * i + 3]) for i in range(len(palette_rgb) // 3)]

    def luma(c):
        return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]

    background = min(range(len(entries)), key=lambda i: luma(entries[i]))
    text = max(range(len(entries)), key=lambda i: luma(entries[i]))
    highlight = max(range(len(entries)),
                    key=lambda i: entries[i][0] - (entries[i][1] + entries[i][2]) / 2)
    return background, text, highlight


def _bitmap(width, height, lines, selected, colours):
    """The menu as a width*height list of palette indices. THE picture, for both mirrors."""
    background, text, highlight = colours
    out = [background] * (width * height)
    if not lines:
        return out
    block_h = len(lines) * (GLYPH_H + 2) - 2
    top = max(0, (height - block_h) // 2)
    for row, line in enumerate(lines):
        ink = highlight if row == selected else text
        label = ("> " + line) if row == selected else ("  " + line)
        label = label.upper()[:width // CELL_W]
        x0 = max(0, (width - len(label) * CELL_W) // 2)
        y0 = top + row * (GLYPH_H + 2)
        for k, ch in enumerate(label):
            glyph = _GLYPHS.get(ch, _GLYPHS[" "]).split("|")
            for gy in range(GLYPH_H):
                for gx in range(GLYPH_W):
                    if glyph[gy][gx] != "#":
                        continue
                    x, y = x0 + k * CELL_W + gx, y0 + gy
                    if 0 <= x < width and 0 <= y < height:
                        out[y * width + x] = ink
    return out


def pixels(width, height, lines, selected, colours):
    """What the ORACLE expects on screen."""
    return _bitmap(width, height, lines, selected, colours)


def stream(width, height, lines, selected, colours) -> bytes:
    """The 0x0B frame that paints exactly `pixels()`.

    Column-major run-lists, with DITTO (0xFE) for a column identical to its left neighbour — which
    on a menu is most of them, and which exercises the one compression the protocol has. Column 0
    is never dittoed: it has no left neighbour, and the device refuses it."""
    grid = _bitmap(width, height, lines, selected, colours)
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


def fj(width, height, lines, selected, colours, label: str = "menu_frame") -> str:
    """The baked frame as fj: one `stl.output_char` per stream byte, all compile-time operands.

    ~2 ops per byte, and a menu stream is ~1 kB — so a menu frame costs order 2,000 ops against a
    world frame's ~28,000,000. The mode flag that chooses between them is the whole of M3's cost.
    """
    data = stream(width, height, lines, selected, colours)
    body = "\n".join("    stl.output_char %d" % b for b in data)
    return ("// M3: the baked menu frame -- %d bytes of 0x0B column run-lists, all constants\n"
            "%s:\n%s\n" % (len(data), label, body))
