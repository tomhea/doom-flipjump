"""M13pS0 — the column-stream device, prototyped as an in-repo InMemoryScreen SUBCLASS (per the plan:
"tests already pass io_device= explicitly, so byte-exact gates need NO package edit" — upstream this
into flipjump before M13p8, keep the diff here in the meantime).

`StreamScreen` decodes the ADDITIVE protocol from `src/fj/present.fj`'s `init_screen_stream`/
`begin_frame_stream` macros: an EXTENDED 9-byte `0x01` (the stock 8 bytes + one `flush_mode` byte) and
a new `0x07` command that puts the device into column-major run-stream mode — every subsequent byte
pair `[count][color]` fills `count` pixels of `color` starting at the current cursor, advancing
column-major (fill column 0's `height` rows, then column 1, ...), until exactly `width*height` pixels
have been placed, at which point the device reverts to normal command-byte parsing. There is no
per-run framing byte — the device knows the total pixel count from `init_screen_stream`, so the last
run naturally completes the frame.

`flush_mode` (0 = per-frame, the shipped default; 1 = per-column, for debugging a partial stream)
governs ONLY when `_present()` (the palette-composite + hash + optional PNG write) runs — never the
fj op cost, which is identical either way.

⚠ StreamScreen ALWAYS expects the EXTENDED 9-byte `0x01` — it must be paired ONLY with
`present.init_screen_stream`, never the stock 8-byte `present.init_screen` (which stays untouched and
is what every other test / build_doom keeps using against the stock `InMemoryScreen`)."""
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen
from flipjump.utils.exceptions import IOReadOnEOF

CMD_BEGIN_FRAME_STREAM = 0x07


class StreamScreen(InMemoryScreen):
    def __init__(self, *, frames_dir=None, stdin: bytes = b""):
        super().__init__(frames_dir=frames_dir)
        self._inp = stdin                          # optional stdin feed (mirrors tests/fj/test_wall_render._ScreenWithInput)
        self._in_byte = 0
        self._in_bits = 0
        self.flush_mode = 0
        self._in_pixel_stream = False
        self._stream_pixels_filled = 0
        self._stream_pending_count = None
        self.flush_count = 0                       # how many times _present() actually ran (verification aid)

    # ---------------------------------------------------------------- input stream (optional)

    def read_bit(self) -> bool:
        if self._in_bits == 0:
            if not self._inp:
                raise IOReadOnEOF("EOF on StreamScreen")
            self._in_byte, self._inp = self._inp[0], self._inp[1:]
            self._in_bits = 8
        bit = (self._in_byte & 1) == 1
        self._in_byte >>= 1
        self._in_bits -= 1
        return bit

    # ---------------------------------------------------------------- command decoding (extended)

    def _command_length(self, command: int) -> int:
        if command == 0x01:                        # CMD_INIT_SCREEN, extended: +1 flush_mode byte
            return 1 + 2 + 2 + 1 + 2 + 1
        if command == CMD_BEGIN_FRAME_STREAM:
            return 1
        return super()._command_length(command)

    def _execute_command(self, command: int, payload) -> None:
        if command == 0x01:
            self._init_screen(self._u16(payload, 0), self._u16(payload, 2), payload[4], self._u16(payload, 5))
            self.flush_mode = payload[7]
            return
        if command == CMD_BEGIN_FRAME_STREAM:
            self._begin_frame_stream()
            return
        super()._execute_command(command, payload)

    def _handle_byte(self, byte: int) -> None:
        if self._in_pixel_stream:
            self._handle_stream_byte(byte)
            return
        super()._handle_byte(byte)

    # ---------------------------------------------------------------- the run-stream decode

    def _begin_frame_stream(self) -> None:
        self._require_initialized_screen()
        self._in_pixel_stream = True
        self._stream_pixels_filled = 0
        self._stream_pending_count = None

    def _handle_stream_byte(self, byte: int) -> None:
        if self._stream_pending_count is None:
            self._stream_pending_count = byte
            return
        count, self._stream_pending_count = self._stream_pending_count, None
        pixel_mask = (1 << self.bpp) - 1
        color = byte & pixel_mask
        total = self.width * self.height
        for _ in range(count):
            col, row = divmod(self._stream_pixels_filled, self.height)
            self.pixel_indices[row * self.width + col] = color
            self._stream_pixels_filled += 1
            if self.flush_mode == 1 and self._stream_pixels_filled % self.height == 0:
                self._present()
                self.flush_count += 1
        if self._stream_pixels_filled >= total:
            self._in_pixel_stream = False
            if self.flush_mode == 0:
                self._present()
                self.flush_count += 1
