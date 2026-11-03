"""doomfj.screenwire -- the program's one copy of the screen API's numbers and its baked-stream encoders -- against the
API (flipjump `io_devices/README.md`) and against flipjump's own device, which decodes every stream here.

The device is the authority: a stream the encoders produce must paint exactly the picture they were given, and a
stream off the API (a column without its END, a row behind the cursor, a reserved token, COPY in column 0) must be
REFUSED by it -- those are the negative controls (R9) that show the round trip can fail.
"""
import random

import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IODeviceException

from doomfj import screenwire as SW


def _decode(stream: bytes) -> InMemoryScreen:
    screen = InMemoryScreen()
    for byte in stream:
        for i in range(8):
            screen.write_bit(bool((byte >> i) & 1))
    return screen


def _boot(width, height):
    return SW.init_screen(width, height)


# ---- the numbers ---------------------------------------------------------------------------------------------------
def test_the_opcodes_are_the_apis():
    assert (SW.OP_INIT_SCREEN, SW.OP_DEFINE_PALETTE, SW.OP_SET_MAX_FPS, SW.OP_SET_WINDOW_TITLE, SW.OP_SET_WINDOW_ICON,
            SW.OP_SELECT_PALETTE, SW.OP_BUILTIN_PALETTE, SW.OP_DRAW_RAW, SW.OP_DRAW_COLLINES, SW.OP_PRESENT) == (
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x10, 0x11, 0x1F)
    assert (SW.END, SW.KEEP, SW.COPY, SW.RESERVED_ROW) == (0xFF, 0xFE, 0xFD, 0xFC)
    assert (SW.END_CMD, SW.RESERVED_COLUMN) == (0xFF, 0xFE)


@pytest.mark.parametrize("h, r", [(1, 4), (11, 4), (12, 8), (100, 8), (251, 8), (252, 12), (4091, 12), (4092, 16),
                                  (65531, 16)])
def test_row_bits_boundaries(h, r):
    assert SW.row_bits(h) == r


@pytest.mark.parametrize("w, c", [(1, 4), (14, 4), (15, 8), (160, 8), (254, 8), (255, 12), (4094, 12), (4095, 16),
                                  (65534, 16)])
def test_column_bits_boundaries(w, c):
    assert SW.column_bits(w) == c


def test_too_big_a_screen_is_refused():
    with pytest.raises(ValueError, match="65,531"):
        SW.row_bits(65532)
    with pytest.raises(ValueError, match="65,534"):
        SW.column_bits(65535)


def test_the_game_screen_has_byte_fields_and_a_wider_one_is_refused():
    SW.assert_byte_fields(160, 100)
    SW.assert_byte_fields(254, 251)
    with pytest.raises(AssertionError, match="R = 12"):
        SW.assert_byte_fields(160, 252)
    with pytest.raises(AssertionError, match="C = 12"):
        SW.assert_byte_fields(255, 100)


# ---- column(): END always; zero-row items allowed (the owner, 2026-10-23) -------------------------------------
def test_every_column_ends_with_end():
    assert SW.column(3, [("fill", 100, 7)], 100) == bytes([3, 100, 7, SW.END])
    assert SW.column(3, [("fill", 99, 7)], 100) == bytes([3, 99, 7, SW.END])
    assert SW.column(3, [("keep", 84), ("fill", 100, 5)], 100) == bytes([3, SW.KEEP, 84, 100, 5, SW.END])
    assert SW.column(3, [("copy", 84)], 100) == bytes([3, SW.COPY, 84, SW.END])
    assert SW.column(3, [], 100) == bytes([3, SW.END])


def test_a_zero_row_item_is_allowed():
    assert SW.column(3, [("keep", 0), ("fill", 10, 1), ("fill", 10, 2), ("fill", 100, 3), ("fill", 100, 4)], 100) \
        == bytes([3, SW.KEEP, 0, 10, 1, 10, 2, 100, 3, 100, 4, SW.END])


@pytest.mark.parametrize("x, items, msg", [
    (0, [("copy", 10)], "column 0 has none"),
    (3, [("fill", 10, 1), ("fill", 9, 2)], "behind the cursor"),
    (3, [("fill", 101, 1)], "past the screen"),
    (SW.RESERVED_COLUMN, [], "a column must be"),
])
def test_column_refuses_what_the_device_refuses(x, items, msg):
    with pytest.raises(AssertionError, match=msg):
        SW.column(x, items, 100)


# ---- through the real device ---------------------------------------------------------------------------------------
def _random_grid(rng, width, height, colours):
    grid = []
    for _y in range(height):
        grid.append([rng.choice(colours) for _x in range(width)])
    # columns equal to their left neighbour (COPY), and long runs
    out = [0] * (width * height)
    for x in range(width):
        src = x - 1 if x and rng.random() < 0.3 else x
        for y in range(height):
            out[y * width + x] = grid[y if rng.random() < 0.2 else y // 7 * 7][src]
    return out


@pytest.mark.parametrize("seed", range(40))
def test_a_frame_paints_its_picture_on_the_device(seed):
    rng = random.Random(seed)
    width, height = rng.choice([(15, 12), (16, 12), (40, 30), (160, 100), (254, 251)])   # byte fields: R = C = 8
    grid = _random_grid(rng, width, height, rng.sample(range(256), rng.randint(1, 6)))
    screen = _decode(_boot(width, height) + SW.frame(grid, width, height))
    assert screen.frame_count == 1
    assert list(screen.pixel_indices) == grid


def test_baked_column_records_over_a_frame_keep_and_paint_on_the_device():
    width, height = 20, 100
    base = [1] * (width * height)
    records = SW.column(5, [("keep", 30), ("fill", 40, 9), ("keep", 90), ("fill", 100, 8)], height)
    records += SW.column(6, [("keep", 84), ("fill", 99, 7)], height)
    stream = (_boot(width, height) + SW.strip_frame_tail(SW.frame(base, width, height)) + records
              + SW.FRAME_TAIL)
    screen = _decode(stream)
    want = list(base)
    for y in range(30, 40):
        want[y * width + 5] = 9
    for y in range(90, 100):
        want[y * width + 5] = 8
    for y in range(84, 99):
        want[y * width + 6] = 7
    assert screen.frame_count == 1 and list(screen.pixel_indices) == want


def test_palettes_select_and_the_chrome_decode_on_the_device():
    pal = [(k, 255 - k, k // 2) for k in range(256)]
    red = [(255, 0, 0)] * 256
    grid = [3] * (16 * 12)
    stream = (_boot(16, 12) + SW.define_palette(0, pal) + SW.define_palette(1, red) + SW.set_window_title("DOOM")
              + SW.set_max_fps(35) + SW.set_window_icon(2, 2, [0, 1, 2, 3])
              + SW.frame(grid, 16, 12) + SW.select_palette(1) + SW.frame(grid, 16, 12))
    screen = _decode(stream)
    assert screen.frame_count == 2
    assert screen.window_title == "DOOM" and screen.max_fps == 35
    assert list(screen.palette) == red


# ---- the negative controls: the device refuses a stream off the API ------------------------------------------------
def test_control_a_column_without_its_end_is_refused():
    width, height = 16, 12
    good = SW.frame([2] * (width * height), width, height)
    assert good[:5] == bytes([SW.OP_DRAW_COLLINES, 0, 12, 2, SW.END])  # column 0: one run to the bottom, then END
    bad = good[:4] + good[5:]                                           # the END dropped: x 1 is read as a row
    with pytest.raises(IODeviceException):
        _decode(_boot(width, height) + bad)


def test_control_a_row_behind_the_cursor_is_refused():
    bad = bytes([SW.OP_DRAW_COLLINES, 0, 5, 1, 4, 2, SW.END, SW.END_CMD, SW.OP_PRESENT])
    with pytest.raises(IODeviceException):
        _decode(_boot(16, 12) + bad)


def test_zero_row_items_decode_on_the_device():
    width, height = 16, 12
    rec = SW.column(0, [("keep", 0), ("fill", 5, 3), ("fill", 5, 9), ("fill", 12, 4), ("fill", 12, 7)], height)
    stream = _boot(width, height) + bytes([SW.OP_DRAW_COLLINES]) + rec + SW.FRAME_TAIL
    screen = _decode(stream)
    want = [0] * (width * height)
    for y in range(height):
        want[y * width] = 3 if y < 5 else 4
    assert screen.frame_count == 1 and list(screen.pixel_indices) == want


def test_control_the_old_keep_token_is_refused():
    bad = bytes([SW.OP_DRAW_COLLINES, 0, SW.RESERVED_ROW, 1, SW.END, SW.END_CMD, SW.OP_PRESENT])
    with pytest.raises(IODeviceException):
        _decode(_boot(16, 12) + bad)


def test_control_copy_in_column_zero_is_refused():
    bad = bytes([SW.OP_DRAW_COLLINES, 0, SW.COPY, 12, SW.END_CMD, SW.OP_PRESENT])
    with pytest.raises(IODeviceException):
        _decode(_boot(16, 12) + bad)


def test_control_a_command_before_init_is_refused():
    with pytest.raises(IODeviceException):
        _decode(SW.select_palette(0))
