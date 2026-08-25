"""M5a — the 0x0B column-run-list decoder, now in the STOCK `InMemoryScreen`.

The standalone `.fjm` (M5) is run by the plain `fj` CLI, whose screen device is
`flipjump.interpreter.io_devices.ScreenIO.InMemoryScreen`. The shipping renderer presents its
frames with `present.begin_frame_collines` (0x0B), which until now only this repo's lab device
(`tests/fj/stream_screen.StreamScreen`) could decode — so a standalone binary drew nothing.

This is a DIFFERENTIAL test: the same byte stream goes into the lab decoder and the upstream one,
and every pixel of every frame must agree. `StreamScreen` is byte-exact against the oracle at 260
sweep viewpoints, so agreeing with it is the strongest statement available without a build.

⚠ The two devices differ in exactly ONE place, deliberately: `StreamScreen` is paired with
`present.init_screen_stream` (the extended 9-byte 0x01 with its `flush_mode` byte), the upstream one
with the stock 8-byte `present.init_screen`. `flush_mode` governs only the 0x07 pixel-stream mode,
which 0x0B does not use, so the two see the same screen.

R9: `test_negative_control_*` mutate the upstream decoder and require this file to FAIL.
"""
import random

import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IODeviceException

from tests.fj.stream_screen import StreamScreen

W, H, NCOLORS = 64, 40, 256
DITTO, END = 0xFE, 0xFF


def _init(width=W, height=H, ncolors=NCOLORS):
    """[0x01][w:2][h:2][bpp:1][ncolors:2] — the stock init; the lab device wants one more byte."""
    stock = bytes([0x01, width & 0xFF, width >> 8, height & 0xFF, height >> 8, 8,
                   ncolors & 0xFF, ncolors >> 8])
    return stock, stock + bytes([0])          # (stock init, extended init with flush_mode=0)


def _feed(device, data: bytes):
    """the devices take BITS, lsb first — which is also what makes an off-by-one framing bug visible."""
    for byte in data:
        for i in range(8):
            device.write_bit(bool((byte >> i) & 1))


def _random_frame(rng, width=W, height=H, *, allow_ditto=True):
    """a valid 0x0B frame: columns in any order, each a top-down run-list or a DITTO."""
    out = bytearray([0x0B])
    for column in range(width):
        if rng.random() < 0.15:
            continue                                   # a column this frame never mentions
        out.append(column)
        if allow_ditto and column > 0 and rng.random() < 0.25:
            out.append(DITTO)
            continue
        cursor = 0
        while cursor < height and rng.random() < 0.8:
            y2 = rng.randint(cursor, height)           # y2 == cursor is legal: an empty run
            out += bytes([y2, rng.randrange(NCOLORS)])
            cursor = y2
        out.append(END)                                # the tail below the cursor is left alone
    out.append(END)
    return bytes(out)


def _both(frames: bytes):
    """run one byte stream through both decoders; returns (lab, upstream)."""
    stock_init, extended_init = _init()
    lab, upstream = StreamScreen(), InMemoryScreen()
    _feed(lab, extended_init + frames)
    _feed(upstream, stock_init + frames)
    return lab, upstream


# -- the differential --------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(8))
def test_random_frame_matches_the_lab_decoder(seed):
    rng = random.Random(seed)
    lab, upstream = _both(_random_frame(rng))
    assert upstream.frame_count == lab.frame_count == 1
    assert upstream.pixel_indices == lab.pixel_indices


def test_many_frames_and_the_carried_over_tail():
    """the pixel buffer is NOT cleared per frame — an unmentioned column keeps the last frame's
    pixels, which is the whole point of the protocol and the easiest thing to get wrong."""
    rng = random.Random(99)
    stream = b"".join(_random_frame(rng) for _ in range(6))
    lab, upstream = _both(stream)
    assert upstream.frame_count == lab.frame_count == 6
    assert upstream.pixel_indices == lab.pixel_indices


def test_ditto_copies_the_previous_column():
    """the one compression form: column 3 is written, column 4 dittos it."""
    frame = bytes([0x0B, 3, 10, 0x41, H, 0x42, END, 4, DITTO, END])
    lab, upstream = _both(frame)
    assert upstream.pixel_indices == lab.pixel_indices
    column3 = [upstream.pixel_indices[r * W + 3] for r in range(H)]
    column4 = [upstream.pixel_indices[r * W + 4] for r in range(H)]
    assert column3 == column4
    assert column3 == [0x41] * 10 + [0x42] * (H - 10)


def test_a_frame_of_nothing_still_presents():
    lab, upstream = _both(bytes([0x0B, END]))
    assert upstream.frame_count == lab.frame_count == 1
    assert upstream.pixel_indices == lab.pixel_indices == [0] * (W * H)


def test_a_command_after_the_frame_is_a_command_again():
    """0x0B is not sticky: the end marker returns the device to ordinary command parsing, or a
    looping program's second `init_screen` would be eaten as run-list bytes."""
    stock_init, _ = _init()
    upstream = InMemoryScreen()
    _feed(upstream, stock_init + bytes([0x0B, 0, 5, 0x77, END, END]) + stock_init)
    assert (upstream.width, upstream.height) == (W, H)
    assert upstream.frame_count == 1


# -- the malformed-stream rejections (the lab decoder asserts on one of these and ignores the
#    rest; upstream they are all IODeviceException, so a broken emitter names itself) ------------

@pytest.mark.parametrize("frame, message", [
    (bytes([0x0B, 0, DITTO]), "no left neighbour"),
    (bytes([0x0B, W]), "outside"),
    (bytes([0x0B, 0, H + 1]), "past the"),
    (bytes([0x0B, 0, 20, 0x11, 10]), "behind the fill cursor"),
])
def test_a_malformed_stream_is_rejected(frame, message):
    stock_init, _ = _init()
    upstream = InMemoryScreen()
    _feed(upstream, stock_init)
    with pytest.raises(IODeviceException, match=message):
        _feed(upstream, frame)


def test_collines_before_init_is_rejected():
    with pytest.raises(IODeviceException, match="not initialized"):
        _feed(InMemoryScreen(), bytes([0x0B]))


# -- R9: the negative controls. each breaks the upstream decoder the way a plausible mistake
#    would, and REQUIRES the differential above to catch it. a green run of the tests above only
#    means something because these are green too. ------------------------------------------------

def _differential_still_agrees(replacement, monkeypatch):
    monkeypatch.setattr(InMemoryScreen, "_handle_collines_byte", replacement)
    rng = random.Random(4)
    stream = b"".join(_random_frame(rng) for _ in range(4))
    lab, upstream = _both(stream)
    return upstream.pixel_indices == lab.pixel_indices


def test_negative_control_ditto_dropped(monkeypatch):
    """a DITTO that closes the column without copying it — the mutation this repo has actually
    shipped once, in the lab decoder, for column 0."""
    original = InMemoryScreen._handle_collines_byte

    def broken(self, byte):
        if self._collines_column is not None and self._collines_y2 is None and byte == DITTO:
            self._collines_column = None
            return
        return original(self, byte)

    assert not _differential_still_agrees(broken, monkeypatch)


def test_negative_control_cursor_not_advanced(monkeypatch):
    """each run painted from row 0 instead of from the cursor — an error that leaves the picture
    recognisable, which is exactly why "looks fine" does not exist here."""
    original = InMemoryScreen._handle_collines_byte

    def broken(self, byte):
        result = original(self, byte)
        if self._collines_column is not None:
            self._collines_row = 0
        return result

    assert not _differential_still_agrees(broken, monkeypatch)


def test_negative_control_frame_not_presented(monkeypatch):
    """the end marker leaves the mode but never presents — the frame count, not the pixels, is
    what catches this one."""
    original = InMemoryScreen._handle_collines_byte

    def broken(self, byte):
        if self._collines_column is None and self._in_collines and byte == END:
            self._in_collines = False
            return
        return original(self, byte)

    monkeypatch.setattr(InMemoryScreen, "_handle_collines_byte", broken)
    lab, upstream = _both(_random_frame(random.Random(1)))
    assert upstream.frame_count != lab.frame_count
