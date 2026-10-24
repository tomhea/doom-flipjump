"""The screen device's wire API -- flipjump's `flipjump/interpreter/io_devices/README.md` -- as the program speaks it.

This module is the ONE place doom holds the API's numbers (opcodes, the format, the draw_collines tokens) and the
encoders every baked byte stream goes through (the menu and its screens, the bar, the weapon, the map page, LEVEL
COMPLETE) and the fj side's calls of the stl's screen macros (flipjump stl/screen.fj; `FJ_*` / `fj_*` below); the
proof that both match the device is that every test and gate decodes the program's output with flipjump's own
`InMemoryScreen`, which refuses anything off the API.

THE SHAPE OF A FRAME (what every tier prints, per frame):
    0x11 draw_collines   column records ...   0xFF END_CMD   0x1F present
and once at boot: 0x01 init_screen [w h format], the palettes (0x02 define_palette into slots 0..n-1; slot 0 is
selected by init_screen), and the window's title (0x04), icon (0x05) and frame-rate cap (0x03). A palette change is
`0x06 select_palette [slot]`, sent between frames.

THE PROGRAM'S FIELDS ARE BYTES. The API sizes draw_collines' row field R and column field C from the screen (the
smallest of 4 / 8 / 12 / 16 bits that leaves room for the tokens); the program's emitters write whole bytes, so every
screen it builds must come out at R = C = 8 -- `assert_byte_fields` says so wherever a screen size is fixed.

END ALWAYS CLOSES A COLUMN (the owner, 2026-10-23), also one whose cursor has reached the screen's height, and an
item may leave the cursor where it is (a zero-row item paints nothing): only a row BEHIND the cursor is refused. The
renderer relies on both -- its sprite runs can map two ends to one row -- and every encoder here goes through
`column()`.
"""
from __future__ import annotations

from typing import Iterable, List, Sequence, Tuple

# ---- opcodes (README: "Opcodes") ---------------------------------------------------------------------------------
OP_INIT_SCREEN = 0x01         # [w:16][h:16][format:8]
OP_DEFINE_PALETTE = 0x02      # [slot:8][first:B][last:B] then (last-first+1) x (R:8 G:8 B:8)
OP_SET_MAX_FPS = 0x03         # [fps:8]
OP_SET_WINDOW_TITLE = 0x04    # UTF-8 bytes, then 0x00
OP_SET_WINDOW_ICON = 0x05     # [w:8][h:8] then w*h colours of B bits
OP_SELECT_PALETTE = 0x06      # [slot:8]
OP_BUILTIN_PALETTE = 0x07     # [slot:8][id:8]
OP_DRAW_RAW = 0x10            # w*h colours of B bits, row-major
OP_DRAW_COLLINES = 0x11       # columns, ended by END_CMD
OP_PRESENT = 0x1F             # show the picture

FORMAT = 8                    # bits per colour: indexed, DOOM's 256-colour palettes

# ---- draw_collines tokens, at R = C = 8 (README: "draw_collines") ------------------------------------------------
END = 0xFF                    # row field: the column is done
KEEP = 0xFE                   # row field: [KEEP][y] -- rows [cursor, y) keep what the screen shows
COPY = 0xFD                   # row field: [COPY][y] -- rows [cursor, y) copy column x-1
RESERVED_ROW = 0xFC           # row field: reserved (an error)
END_CMD = 0xFF                # column field: the command is over
RESERVED_COLUMN = 0xFE        # column field: reserved (an error)


def row_bits(height: int) -> int:
    """R: the smallest of 4, 8, 12, 16 with height < 2^R - 4"""
    for r in (4, 8, 12, 16):
        if height < (1 << r) - 4:
            return r
    raise ValueError("h = %d: must be 1..65,531" % height)


def column_bits(width: int) -> int:
    """C: the smallest of 4, 8, 12, 16 with width < 2^C - 1"""
    for c in (4, 8, 12, 16):
        if width < (1 << c) - 1:
            return c
    raise ValueError("w = %d: must be 1..65,534" % width)


def assert_byte_fields(width: int, height: int) -> None:
    """the program writes byte-wide fields: refuse a screen whose R or C is not 8"""
    assert row_bits(height) == 8 and column_bits(width) == 8, (
        "a %dx%d screen has R = %d, C = %d; the program's draw_collines fields are bytes (R = C = 8)"
        % (width, height, row_bits(height), column_bits(width)))


# ---- encoders -----------------------------------------------------------------------------------------------------
def init_screen(width: int, height: int) -> bytes:
    return bytes([OP_INIT_SCREEN, width & 0xFF, width >> 8, height & 0xFF, height >> 8, FORMAT])


def define_palette(slot: int, rgb: Sequence[Tuple[int, int, int]], first: int = 0) -> bytes:
    """entries first .. first+len(rgb)-1 of palette `slot` (8-bit format: first / last are one byte each)"""
    last = first + len(rgb) - 1
    assert 0 <= slot <= 255 and 0 <= first <= last <= 255, (slot, first, last)
    return bytes([OP_DEFINE_PALETTE, slot, first, last]) + b"".join(bytes(c) for c in rgb)


def select_palette(slot: int) -> bytes:
    assert 0 <= slot <= 255, slot
    return bytes([OP_SELECT_PALETTE, slot])


def set_max_fps(fps: int) -> bytes:
    assert 0 <= fps <= 255, fps
    return bytes([OP_SET_MAX_FPS, fps])


def set_window_title(text: str) -> bytes:
    data = text.encode("utf-8")
    assert b"\x00" not in data, "a title cannot hold a NUL (it ends the title)"
    return bytes([OP_SET_WINDOW_TITLE]) + data + b"\x00"


def set_window_icon(width: int, height: int, colours: Sequence[int]) -> bytes:
    assert 1 <= width <= 255 and 1 <= height <= 255 and len(colours) == width * height, (width, height, len(colours))
    return bytes([OP_SET_WINDOW_ICON, width, height]) + bytes(colours)


def column(x: int, items: Iterable[tuple], height: int) -> bytes:
    """one column record: `x`, then `items` -- ("fill", y2, colour), ("keep", y) or ("copy", y) -- then END. Refuses a
    row behind the cursor or past the screen, and COPY in column 0 -- what the device would refuse."""
    assert 0 <= x < RESERVED_COLUMN, "x = %d: a column must be 0..%d" % (x, RESERVED_COLUMN - 1)
    out = bytearray([x])
    cursor = 0
    for item in items:
        kind, y = item[0], item[1]
        assert cursor <= y <= height, "column %d: y = %d is behind the cursor or past the screen (need %d <= y <= %d)" \
            % (x, y, cursor, height)
        if kind == "fill":
            out += bytes([y, item[2]])
        elif kind == "keep":
            out += bytes([KEEP, y])
        elif kind == "copy":
            assert x > 0, "COPY copies column x - 1, and column 0 has none"
            out += bytes([COPY, y])
        else:
            raise ValueError(kind)
        cursor = y
    out.append(END)
    return bytes(out)


def runs(values: Sequence[int], top: int = 0) -> List[tuple]:
    """("fill", y2, colour) items for the run-length runs of `values`, whose first row is `top`"""
    out = []
    y = 0
    while y < len(values):
        e = y + 1
        while e < len(values) and values[e] == values[y]:
            e += 1
        out.append(("fill", top + e, values[y]))
        y = e
    return out


def picture(grid: Sequence[int], width: int, height: int) -> bytes:
    """a whole width*height picture (row-major colour values) as ONE draw_collines command: 0x11, a record per column
    -- COPY for a column identical to the one on its left, else its runs -- and END_CMD. No present."""
    assert_byte_fields(width, height)
    assert len(grid) == width * height, (len(grid), width, height)
    out = bytearray([OP_DRAW_COLLINES])
    previous = None
    for x in range(width):
        col = [grid[y * width + x] for y in range(height)]
        items = [("copy", height)] if previous is not None and col == previous else runs(col)
        out += column(x, items, height)
        previous = col
    out.append(END_CMD)
    return bytes(out)


def frame(grid: Sequence[int], width: int, height: int) -> bytes:
    """a whole FRAME: `picture` (the draw_collines command, ending in END_CMD), then present"""
    return picture(grid, width, height) + bytes([OP_PRESENT])


# ---- the fj side: flipjump's stl/screen.fj, called with this module's numbers ------------------------------------
# W and H are fj_consts' screen size (Config.W / Config.H, the screen every tier builds -- R = C = 8, assert_byte_fields).
# FRAME_END_USED_BITS is `screen.end_frame`'s used_bits: the bits of the current output byte the column records already
# wrote. THE PROGRAM'S FIELDS ARE BYTES (above): every write into a draw_collines command -- stl.output_char, the byte
# emits, cm.emit's 8 output_bits -- is a whole byte, so the records end on a byte boundary and it is 0. end_frame then
# prints C = column_bits(W) = 8 one-bits (END_CMD 0xFF), (8 - (0 + 8) % 8) % 8 = 0 padding bits and present (0x1F):
# exactly FRAME_TAIL, the bytes the program's frame tail always printed (tests/fj/test_present.py runs it).
FRAME_END_USED_BITS = 0
FJ_INIT_SCREEN = "screen.init_screen W, H, %d" % FORMAT
FJ_DRAW_COLLINES = "screen.draw_collines"
FJ_END_FRAME = "screen.end_frame W, %d" % FRAME_END_USED_BITS


def fj_select_palette(slot: int) -> str:
    assert 0 <= slot <= 255, slot
    return "screen.select_palette %d" % slot


def fj_set_max_fps(fps: int) -> str:
    assert 0 <= fps <= 255, fps
    return "screen.set_max_fps %d" % fps


def fj_set_window_title(text: str) -> str:
    """the title as stl.screen's constant: its utf-8 bytes, least-significant first, and their count"""
    data = text.encode("utf-8")
    assert b"\x00" not in data, "a title cannot hold a NUL (it ends the title)"
    return "screen.set_window_title %s, %d" % (hex(int.from_bytes(data, "little")), len(data))


def fj_set_window_icon_header(width: int, height: int) -> str:
    assert 1 <= width <= 255 and 1 <= height <= 255, (width, height)
    return "screen.set_window_icon_header %d, %d" % (width, height)


FRAME_TAIL = bytes([END_CMD, OP_PRESENT])     # what FJ_END_FRAME prints: the end of every frame's command


def strip_frame_tail(data: bytes) -> bytes:
    """a frame's bytes without its END_CMD and present -- for a producer that falls into the program's shared frame
    tail (FJ_END_FRAME) instead of ending the frame itself"""
    assert data[-2:] == FRAME_TAIL, "not a whole frame: it does not end in END_CMD, present"
    return data[:-2]


def fj_lines(data: bytes, indent: str = "") -> List[str]:
    """a constant byte stream as fj: one `stl.output_char` per byte (fj has no statement separator)"""
    return ["%sstl.output_char %d" % (indent, b) for b in data]
