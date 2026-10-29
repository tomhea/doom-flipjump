"""tests/fj/stream_screen.StreamScreen -- the hosted tiers' device: flipjump's own screen plus the host channel
(doomfj.wireformat's STATE_CMD / THING_CMD) and a stdin feed. The screen half is the API's decoder; these check that
the harness takes out exactly the host channel and nothing else, and that it does not weaken the device: an opcode
that is neither the API's nor the host channel's is still refused (R9)."""
import pytest
from flipjump.utils.exceptions import IODeviceException, IOReadOnEOF

from doomfj import screenwire as SW
from doomfj import wireformat as WF
from tests.fj.stream_screen import StreamScreen


def _feed(dev, data: bytes):
    for byte in data:
        for i in range(8):
            dev.write_bit(bool((byte >> i) & 1))


def test_the_host_channel_is_outside_the_screen_api():
    api = {SW.OP_INIT_SCREEN, SW.OP_DEFINE_PALETTE, SW.OP_SET_MAX_FPS, SW.OP_SET_WINDOW_TITLE, SW.OP_SET_WINDOW_ICON,
           SW.OP_SELECT_PALETTE, SW.OP_BUILTIN_PALETTE, SW.OP_DRAW_RAW, SW.OP_DRAW_COLLINES, SW.OP_PRESENT}
    assert WF.STATE_CMD not in api and WF.THING_CMD not in api and WF.STATE_CMD != WF.THING_CMD


def test_state_and_bindings_are_taken_out_and_the_frames_still_decode():
    dev = StreamScreen(n_things=2)
    grid = [3] * (160 * 100)
    state = bytes(range(WF.STATE_BYTES))
    things = bytes(range(10, 10 + WF.BINDING_OUT_BYTES * 2))
    _feed(dev, SW.init_screen(160, 100) + bytes([WF.STATE_CMD]) + state + SW.frame(grid, 160, 100)
          + bytes([WF.THING_CMD]) + things + SW.frame(grid, 160, 100))
    assert dev.state == WF.decode_state(state)
    assert dev.bindings == WF.decode_bindings(things)
    assert dev.flush_count == dev.frame_count == 2 and list(dev.pixel_indices) == grid


def test_no_things_means_an_empty_bindings_block():
    dev = StreamScreen(n_things=0)
    _feed(dev, SW.init_screen(160, 100) + bytes([WF.THING_CMD]) + SW.frame([1] * 16000, 160, 100))
    assert dev.bindings == WF.decode_bindings(b"") and dev.frame_count == 1


def test_the_stdin_feed_is_read_lsb_first_and_ends_in_eof():
    dev = StreamScreen(stdin=bytes([0b10110001]))
    assert [dev.read_bit() for _ in range(8)] == [True, False, False, False, True, True, False, True]
    with pytest.raises(IOReadOnEOF):
        dev.read_bit()


def test_control_any_other_opcode_is_still_refused():
    dev = StreamScreen()
    with pytest.raises(IODeviceException):
        _feed(dev, SW.init_screen(160, 100) + bytes([0x82]))
    dev = StreamScreen()
    with pytest.raises(IODeviceException):
        _feed(dev, SW.init_screen(160, 100) + bytes([0x0B]))          # the old frame command is gone
