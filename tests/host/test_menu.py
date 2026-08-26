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

from doomfj.menu import CELL_W, fj, palette_colours, pixels, stream

W, H = 160, 100
LINES = ["DOOM ON FLIPJUMP", "NEW GAME", "LEVEL 1", "LEVEL 5", "LEVEL 8", "QUIT"]
COLOURS = (0, 4, 176)


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
    assert len(set(grid)) == 3, sorted(set(grid))
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
    """Black is darkest, white brightest, and the highlight is the reddest entry."""
    rgb = bytearray()
    for i in range(8):
        rgb += bytes([i * 30, i * 30, i * 30])
    rgb += bytes([255, 0, 0])
    background, text, highlight = palette_colours(rgb)
    assert background == 0 and text == 7 and highlight == 8


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
