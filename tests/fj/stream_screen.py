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

# M13-raster: the block-FP reciprocal table is a pure Config-derived math constant (no asset-wad
# dependency, no game data) shared SSOT-style with slope_div/recip32/scale_from_global_angle -- the
# device importing it directly is the same sharing principle as those fj macros already lean on, NOT
# an oracle backdoor (colormap, by contrast, IS asset/level data, so it's DMA-read via the wire, not
# imported -- see CMD_LOAD_RASTER_TABLES below).
from doomfj.tables import slopediv_recip_table, SLOPEDIV_RECIP_RK

CMD_BEGIN_FRAME_STREAM = 0x07
CMD_BEGIN_FRAME_PLANES = 0x09      # M13-planesproto (0x08 stays reserved for M16 write_pixel)
CMD_BEGIN_FRAME_SPANS = 0x0A       # M13-spanfill: dumb-screen fillCol span list
CMD_LOAD_RASTER_TABLES = 0x0C      # M13-raster: hand the device yslope/zlight/colormap addresses (once)
CMD_BEGIN_FRAME_RASTER = 0x0D      # M13-raster: the device rasterizer per-frame record stream
UNCLAIMED_FVP = 0xFF               # a column record with fvp == 0xFF paints nothing
SPANS_END_X = 0xFF                 # a fillCol record with x == 0xFF terminates the frame

# M13-raster interleaved record tags (a seg record's own tag byte is its x1, always < RASTER_TAG_FLOOR_VP
# since VIEW_W <= 160; the three reserved high tags can never collide with a real column index).
RASTER_TAG_FLOOR_VP = 0xFD
RASTER_TAG_CEIL_VP = 0xFE
RASTER_TAG_END = 0xFF
LIGHTZSHIFT = 20                   # R_MapPlane: distance -> zidx bucket shift (mirrors reference_model)
MAXLIGHTZ = 128
LIGHTLEVELS = 16                   # zlight light buckets (sector light >> LIGHTSEGSHIFT)
LIGHTSEGSHIFT = 4                  # sector light (0..255) -> zlight light bucket (0..15)
COLORMAP_LIGHTS = 32                # colormap usable light rows (0..31)


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
        self._planes_buf = None                    # M13-planesproto: accumulating payload bytes (None = off)
        self._spans_active = False                 # M13-spanfill: inside a 0x0A fillCol span list
        self._spans_rec = bytearray()              # the current 4-byte [x][y1][y2][colour] record being read
        # M13-raster: the device rasterizer's static tables (loaded once via 0x0C, DMA-read directly
        # from fj memory -- see _execute_command) + per-frame state (reset each 0x0D).
        self._yslope = None; self._zlight = None; self._colormap = None
        self._raster_active = False
        self._raster_rec = bytearray()
        self._raster_ceil_vp = {}                  # vp_idx -> (planeheight, light, base)
        self._raster_floor_vp = {}
        self._raster_lut_cache = {}                 # vp key -> the [0,H) row->color array (memoized)

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
        if command == CMD_BEGIN_FRAME_PLANES:
            return 1
        if command == CMD_BEGIN_FRAME_SPANS:
            return 1
        if command == CMD_LOAD_RASTER_TABLES:
            return 1 + 3 * self._address_bytes()
        if command == CMD_BEGIN_FRAME_RASTER:
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
        if command == CMD_BEGIN_FRAME_PLANES:
            self._require_initialized_screen()
            self._planes_buf = bytearray()
            return
        if command == CMD_BEGIN_FRAME_SPANS:
            self._require_initialized_screen()
            self._spans_active = True
            self._spans_rec = bytearray()
            return
        if command == CMD_LOAD_RASTER_TABLES:
            self._require_initialized_screen()
            ab = self._address_bytes()
            yslope_addr = self._read_address(payload, 0)
            zlight_addr = self._read_address(payload, ab)
            colormap_addr = self._read_address(payload, 2 * ab)
            # DMA-read the three static packed-byte tables directly from fj memory (zero fj ops,
            # same mechanism set_palette/update_screen already use) -- ONCE per program.
            yb = self._read_packed_bytes(yslope_addr, 3 * self.height)
            self._yslope = [int.from_bytes(yb[3 * y:3 * y + 3], "little") for y in range(self.height)]
            self._zlight = self._read_packed_bytes(zlight_addr, LIGHTLEVELS * MAXLIGHTZ)
            self._colormap = self._read_packed_bytes(colormap_addr, COLORMAP_LIGHTS * 256)
            return
        if command == CMD_BEGIN_FRAME_RASTER:
            self._require_initialized_screen()
            self._raster_active = True
            self._raster_rec = bytearray()
            self._raster_ceil_vp = {}
            self._raster_floor_vp = {}
            self._raster_lut_cache = {}
            self._raster_painted = bytearray(self.width)
            self._raster_ceil_hi = [-1] * self.width
            self._raster_floor_lo = [self.height] * self.width
            self._raster_cvp_of = [None] * self.width
            self._raster_fvp_of = [None] * self.width
            return
        super()._execute_command(command, payload)

    def _handle_byte(self, byte: int) -> None:
        if self._raster_active:
            self._handle_raster_byte(byte)
            return
        if self._spans_active:
            self._handle_spans_byte(byte)
            return
        if self._planes_buf is not None:
            self._planes_buf.append(byte)
            if self._planes_payload_complete():
                self._decode_planes_frame()
            return
        if self._in_pixel_stream:
            self._handle_stream_byte(byte)
            return
        super()._handle_byte(byte)

    # ------------------------------------------------- M13-spanfill: the dumb fillCol span frame
    # A flat list of [x][y1][y2][colour] records; the frame ends at the first record with x==0xFF.
    # Each record fills column x, rows [y1, y2), with palette index colour. The device holds no state
    # between records (no cursor, no band lists) — it just paints one vertical strip per record.

    def _handle_spans_byte(self, byte: int) -> None:
        rec = self._spans_rec
        rec.append(byte)
        if len(rec) == 1 and byte == SPANS_END_X:      # sentinel: x==0xFF ends the frame
            self._spans_active = False
            self._spans_rec = bytearray()
            self._present()
            self.flush_count += 1
            return
        if len(rec) == 4:
            x, y1, y2, colour = rec
            for y in range(y1, y2):
                self.pixel_indices[y * self.width + x] = colour
            self._spans_rec = bytearray()

    # ------------------------------------------------- M13-raster: the DEVICE RASTERIZER frame
    # fj stays the "brain" (BSP walk, visibility/occlusion decisions, per-seg projection setup) and
    # emits a flat, INTERLEAVED stream of small records in front-to-back walk order (no separate
    # buffer-then-emit phase -- ordering alone is what encodes occlusion, matching the walk's own
    # front-to-back guarantee): a ceiling/floor VISPLANE record on first reference
    # ([0xFE/0xFD][vp_idx][planeheight:4][light][base], 8 bytes) and a SEG record per surviving seg
    # ([x1][x2][scale1:4][scalestep:4][wt_ceil:4 signed][wt_floor:4 signed][lit][cvp_idx][fvp_idx],
    # 21 bytes), terminated by one 0xFF byte. The device does PURE RENDERING MECHANICS from these:
    # a per-column wall DDA + first-writer-wins fill, then (once the whole seg stream is in) a
    # per-visplane distance-light march producing a [0,H) row->colour array that every column
    # sharing that visplane just slices -- the SAME algorithm `plane.build_bands`/`_zidx_band_walk`
    # already used, just executed here instead of costing fj ops. Verified byte-exact against the
    # oracle over a broad random-viewpoint sweep before this was wired into fj (scratchpad/
    # proto_device_rasterizer.py).

    def _handle_raster_byte(self, byte: int) -> None:
        rec = self._raster_rec
        if not rec:
            rec.append(byte)
            if byte == RASTER_TAG_END:
                self._finish_raster_frame()
                self._raster_rec = bytearray()
            return
        rec.append(byte)
        need = 8 if rec[0] in (RASTER_TAG_CEIL_VP, RASTER_TAG_FLOOR_VP) else 21
        if len(rec) == need:
            self._decode_raster_record(bytes(rec))
            self._raster_rec = bytearray()

    @staticmethod
    def _i32(b: bytes, off: int, *, signed: bool) -> int:
        return int.from_bytes(b[off:off + 4], "little", signed=signed)

    def _decode_raster_record(self, rec: bytes) -> None:
        tag = rec[0]
        if tag in (RASTER_TAG_CEIL_VP, RASTER_TAG_FLOOR_VP):
            vp_idx = rec[1]
            planeheight = self._i32(rec, 2, signed=False)
            light, base = rec[6], rec[7]
            table = self._raster_ceil_vp if tag == RASTER_TAG_CEIL_VP else self._raster_floor_vp
            table[vp_idx] = (planeheight, light, base)
            return
        # seg record: the wall DDA (mirrors proj.wall_screen_span / reference_model.wall_screen_span
        # exactly -- fixed_mul then an arithmetic >>16), first-writer-wins fill, and bookkeeping for
        # the shading pass that runs once the frame's terminator arrives.
        x1, x2 = rec[0], rec[1]
        scale = self._i32(rec, 2, signed=False)
        scalestep = self._i32(rec, 6, signed=True)
        wt_ceil = self._i32(rec, 10, signed=True)
        wt_floor = self._i32(rec, 14, signed=True)
        lit, cvp_idx, fvp_idx = rec[18], rec[19], rec[20]
        centeryfix = (self.height // 2) << 16          # CENTERY == VIEW_H/2 (the Config convention)
        painted = self._raster_painted
        for x in range(x1, x2):
            if not painted[x]:
                top = self._signed32(centeryfix - self._fixed_mul(wt_ceil, scale)) >> 16
                bot = self._signed32(centeryfix - self._fixed_mul(wt_floor, scale)) >> 16
                if top < 0:
                    top = 0
                if bot > self.height - 1:
                    bot = self.height - 1
                if top <= bot:
                    for y in range(top, bot + 1):
                        self.pixel_indices[y * self.width + x] = lit
                self._raster_ceil_hi[x] = min(top, self.height) - 1
                self._raster_floor_lo[x] = max(bot + 1, 0)
                self._raster_cvp_of[x] = cvp_idx
                self._raster_fvp_of[x] = fvp_idx
                painted[x] = 1
            scale = (scale + scalestep) & 0xFFFFFFFF

    @staticmethod
    def _signed32(v: int) -> int:
        v &= 0xFFFFFFFF
        return v - (1 << 32) if v & 0x80000000 else v

    @staticmethod
    def _fixed_mul(a: int, b: int) -> int:
        """Mirrors doomfj.fixedpoint.fixed_mul(a, b, 8, 4) EXACTLY: the product is formed at full
        64-bit width (no intermediate overflow -- `a`,`b` are 32-bit signed, product fits in 62 bits),
        wrapped to an unsigned 64-bit pattern, THEN shifted right 16 bits and wrapped to 32 bits. This
        two-stage wrap (64 then 32) matters: a naive `(signed_a*signed_b) & 0xFFFFFFFF` done BEFORE
        the shift would discard the low 16 bits the shift is supposed to keep."""
        a = StreamScreen._signed32(a); b = StreamScreen._signed32(b)
        product = (a * b) & 0xFFFFFFFFFFFFFFFF
        return (product >> 16) & 0xFFFFFFFF

    def _row_colour_lut(self, key):
        """The per-visplane [0,H) row->colour array: a threshold march over self._yslope (the SAME
        seed-then-step algorithm as _zidx_band_walk/plane.build_bands), then a zlight+colormap lookup
        per row. Memoized per (planeheight,light,base) -- shared by every column referencing this
        visplane, exactly like build_bands's per-visplane sharing today."""
        if key in self._raster_lut_cache:
            return self._raster_lut_cache[key]
        planeheight, light, base = key
        H = self.height
        centery = H // 2
        zidx_per_row = self._zidx_band_walk(planeheight, list(range(H)), centery)
        lvl = min(LIGHTLEVELS - 1, light >> LIGHTSEGSHIFT)
        lut = [self._colormap[self._zlight[lvl * MAXLIGHTZ + z] * 256 + base] for z in zidx_per_row]
        self._raster_lut_cache[key] = lut
        return lut

    def _zidx_band_walk(self, planeheight: int, rows: list, centery: int) -> list:
        """Device-side reimplementation of reference_model._zidx_band_walk (the SAME seed + threshold
        march plane.build_bands already ran fj-side) -- split at `centery` since yslope is only
        monotone within each half (never across the whole screen)."""
        if not rows:
            return []
        if planeheight == 0:
            return [0] * len(rows)
        if rows[0] < centery <= rows[-1]:
            k = centery - rows[0]
            return (self._zidx_band_walk(planeheight, rows[:k], centery)
                    + self._zidx_band_walk(planeheight, rows[k:], centery))
        recip = self._recip_div32(planeheight)
        step = 16 * recip
        y0 = rows[0]
        zidx = min(MAXLIGHTZ - 1, self._fixed_mul_shift(planeheight, self._yslope[y0]))
        ascending = len(rows) < 2 or self._yslope[rows[1]] >= self._yslope[y0]
        threshold_hi = step * (zidx + 1)
        threshold_lo = step * zidx
        out = [zidx]
        for y in rows[1:]:
            ys = self._yslope[y]
            if ascending:
                while zidx < MAXLIGHTZ - 1 and ys >= threshold_hi:
                    zidx += 1
                    threshold_hi += step
            else:
                while zidx > 0 and ys < threshold_lo:
                    zidx -= 1
                    threshold_lo -= step
            out.append(zidx)
        return out

    @staticmethod
    def _fixed_mul_shift(planeheight: int, yslope_val: int) -> int:
        """distance = FixedMul(planeheight, yslope[y], 8, 4) >> LIGHTZSHIFT, both non-negative here.
        Uses the shared `_fixed_mul` (32-bit wrap included) rather than a raw Python multiply+shift --
        for implausibly tall sectors the true product can exceed 32 bits, and `fixed_mul`'s wrap
        (truncate, don't clamp) is part of the byte-exact contract, same as reference_model's own
        `distance >> LIGHTZSHIFT` after a wrapping FixedMul."""
        return StreamScreen._fixed_mul(planeheight, yslope_val) >> LIGHTZSHIFT

    @staticmethod
    def _recip_div32(divisor: int) -> int:
        """(1<<32)//divisor via the shared block-FP slopediv_recip table (mirrors
        reference_model._recip_div32 / proj.slope_div's own recipe exactly)."""
        table = slopediv_recip_table()
        P = (divisor.bit_length() - 1) // 4
        if P >= 2:
            m = (divisor >> (4 * (P - 2))) & 0xFFF
            sh = SLOPEDIV_RECIP_RK + 4 * (P - 2)
        else:
            m = (divisor << (4 * (2 - P))) & 0xFFF
            sh = SLOPEDIV_RECIP_RK - 4 * (2 - P)
        return ((1 << 32) * table[m]) >> sh

    def _finish_raster_frame(self) -> None:
        """The shading pass: once every seg is in, slice each column's ceiling/floor region out of
        its visplane's shared row->colour array (a prefix / suffix, exactly like the prefix/suffix
        clip planesproto's device already did -- just against a locally-computed array instead of
        an fj-emitted band list)."""
        for x in range(self.width):
            if self._raster_cvp_of[x] is None:
                continue
            cL = self._row_colour_lut(self._raster_ceil_vp[self._raster_cvp_of[x]])
            for y in range(0, self._raster_ceil_hi[x] + 1):
                self.pixel_indices[y * self.width + x] = cL[y]
            fL = self._row_colour_lut(self._raster_floor_vp[self._raster_fvp_of[x]])
            for y in range(self._raster_floor_lo[x], self.height):
                self.pixel_indices[y * self.width + x] = fL[y]
        self._raster_active = False
        self._present()
        self.flush_count += 1

    # ------------------------------------------------- M13-planesproto: the per-visplane frame
    # Payload (all bytes): [n_cvps][each list: n_entries, then n x (count, colour)]
    #                      [n_fvps][same]  then width x 5-byte column records
    #                      [cexcl][fstart][lit][cvp][fvp]   (fvp==0xFF -> unclaimed, paints nothing).
    # The device reconstructs each column EXACTLY like stream.emit_column's window semantics:
    # ceiling = the cvp list's PREFIX [0, min(cexcl, fstart)), then one wall run of `lit` up to
    # fstart, then floor = the fvp list's SUFFIX skipping its first fstart rows. Colours arrive
    # FINAL (the fj side cm.emit-maps each list entry once per VISPLANE, not per column).

    def _planes_payload_complete(self) -> bool:
        b = self._planes_buf
        pos = 0
        for _bank in range(2):
            if len(b) <= pos:
                return False
            nvp = b[pos]; pos += 1
            for _ in range(nvp):
                if len(b) <= pos:
                    return False
                pos += 1 + 2 * b[pos]              # n_entries byte + n x (count, colour)
                if len(b) < pos:
                    return False
        return len(b) >= pos + 5 * self.width

    def _decode_planes_frame(self) -> None:
        b = self._planes_buf; self._planes_buf = None
        pos = 0
        banks = []
        for _bank in range(2):
            nvp = b[pos]; pos += 1
            lists = []
            for _ in range(nvp):
                n = b[pos]; pos += 1
                lists.append([(b[pos + 2 * k], b[pos + 2 * k + 1]) for k in range(n)])
                pos += 2 * n
            banks.append(lists)
        cvps, fvps = banks
        for x in range(self.width):
            cexcl, fstart, lit, cvp, fvp = b[pos:pos + 5]; pos += 5
            if fvp == UNCLAIMED_FVP:
                continue
            ctake = min(cexcl, fstart)
            y = 0
            if ctake > 0:                          # (mirrors emit_prefix's take==0 no-deref guard)
                for count, colour in cvps[cvp]:    # ceiling PREFIX [0, ctake)
                    if y >= ctake:
                        break
                    for _ in range(min(count, ctake - y)):
                        self.pixel_indices[y * self.width + x] = colour
                        y += 1
            y = ctake
            while y < fstart:                      # the wall run
                self.pixel_indices[y * self.width + x] = lit
                y += 1
            skip = fstart                          # floor SUFFIX: skip the list's first fstart rows
            for count, colour in fvps[fvp]:
                take = count - skip if count > skip else 0
                skip = skip - count if skip >= count else 0
                for _ in range(take):
                    self.pixel_indices[y * self.width + x] = colour
                    y += 1
        self._present()
        self.flush_count += 1

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
