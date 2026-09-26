"""A light .fjm reader: the segment table plus the decompressed payload as one numpy array.

flipjump's own Reader builds a {address: word} dict of every word (~2.4 GB for the game binary);
this keeps the payload as uint32/uint64 and resolves a word on demand. Formats and constants come
from flipjump.fjm.fjm_consts, so the header layout is not re-derived here.

The at-rest value of a JUMP word (odd offset in its segment) is stored RELATIVE in versions 2 and 3:
value = (stored + address * w) mod 2^w -- the same rule as fjm_reader.Reader._init_memory.
"""
import bisect
import lzma
import struct
from pathlib import Path

import numpy as np
from flipjump.fjm.fjm_consts import (FJ_MAGIC, FJMVersion, _LZMA_DECOMPRESSION_FILTERS, _LZMA_FORMAT,
                                     _header_base_format, _header_base_size, _header_extension_format,
                                     _header_extension_size, _segment_format, _segment_size)


class FjmImage:
    def __init__(self, path=None, *, w=None, segments=None, data=None, version=None):
        if path is not None:
            with open(Path(path), "rb") as fh:
                magic, w, version, segnum = struct.unpack(_header_base_format, fh.read(_header_base_size))
                if magic != FJ_MAGIC:
                    raise ValueError("%s is not an .fjm (magic %#x)" % (path, magic))
                version = FJMVersion(version)     # a plain Enum: the raw int never compares equal to it
                if version != FJMVersion.BaseVersion:
                    struct.unpack(_header_extension_format, fh.read(_header_extension_size))
                segments = [struct.unpack(_segment_format, fh.read(_segment_size)) for _ in range(segnum)]
                raw = fh.read()
            if version == FJMVersion.CompressedVersion:
                raw = lzma.decompress(raw, format=_LZMA_FORMAT, filters=_LZMA_DECOMPRESSION_FILTERS)
            data = np.frombuffer(raw, dtype={32: "<u4", 64: "<u8"}[w])
        self.w = w
        self.version = version
        self.relative = version in (FJMVersion.RelativeJumpVersion, FJMVersion.CompressedVersion)
        segs = sorted(segments)
        self.seg = np.array(segs, dtype=np.int64).reshape(-1, 4)     # start, length, data_start, data_length
        self._starts = self.seg[:, 0].tolist()
        self.data = data
        self.mask = (1 << w) - 1

    def word(self, addr):
        """the word at word address `addr` as loaded (None outside every segment)"""
        k = bisect.bisect_right(self._starts, addr) - 1
        if k < 0:
            return None
        start, length, dstart, dlen = (int(x) for x in self.seg[k])
        off = addr - start
        if off >= length:
            return None
        if off >= dlen:
            return 0                                   # the segment's zero-filled tail
        v = int(self.data[dstart + off])
        if self.relative and off % 2 == 1:
            v = (v + addr * self.w) & self.mask
        return v

    def segment_starts(self, lo, hi):
        """number of segments starting in [lo, hi) (word addresses) -- one per blocked table"""
        return bisect.bisect_left(self._starts, hi) - bisect.bisect_left(self._starts, lo)

    def with_word(self, addr, value):
        """a copy that reads `value` at `addr` (for negative controls); the payload is shared"""
        other = FjmImage(w=self.w, segments=[tuple(r) for r in self.seg.tolist()], data=self.data,
                         version=self.version)
        base_word = other.word

        def word(a):
            return value if a == addr else base_word(a)

        other.word = word
        return other
