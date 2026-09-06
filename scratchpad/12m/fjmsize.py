"""THE ONE PLACE that knows how big an .fjm is and how big it is ALLOWED to be.

Why this file exists: four files had four copies of the address ceiling (`1 << 27` twice, the
literal `134,217,728` twice) and three different ideas of a word's size (`BITS_PER_WORD = 32`,
`// 4`, and the fjm's own `memory_width`). They agree only while `w == 32` -- which is precisely
the assumption the campaign is questioning. CR-2026-09-06 finding R6.

THE CEILING IS NOT A TUNABLE. An address in FlipJump is `memory_width` bits and a word is
`memory_width` bits, so a program cannot exceed `(1 << w) // w` words. At w=32 that is
2^27 = 134,217,728, and it is enforced at `flipjump/assembler/assembler.py:24`
(`if address < 0 or address >= (1 << memory_width)`). This is a DIFFERENT thing from
`flat_max_words`, which is a runtime allocation limit: raising that does not widen an address.

    ceiling_words(32) =                 134,217,728
    ceiling_words(64) = 288,230,376,151,711,744

THE SIZE READER. `word_pct` used to be `lzma.decompress(data[64:])` then `len(raw) // 4`. Both
constants were assumptions that happen to hold for today's builds:

  * `64` is `20 + 12 + 32*segment_num` and is right only when `segment_num == 1`;
  * `// 4` is `memory_width // 8` and is right only when `memory_width == 32`.

Neither was asserted, so the failure mode was a WRONG NUMBER rather than a crash.

The two constants fail in OPPOSITE directions, and only one of them is dangerous:

  * `// 4` at w != 32 OVER-counts. A w=64 payload is 8 bytes per word, so dividing by 4 reports
    TWICE the words (control C2: correct=21,470, old reader=42,940). Over-counting inflates the
    percentage of the ceiling, so it turns a PASS into a FAIL -- wrong, but loud.
  * `data[64:]` at segment_num != 1 slices into the SEGMENT TABLE rather than the payload, and the
    decompression then yields nothing: control C3 measures a 60-word file as **0 words**. Zero
    words is 0% of the ceiling, so THIS is the false-PASS mode -- wrong, and silent.

The header is now parsed with the fjm's own struct formats
(`flipjump.fjm.fjm_consts`), so both derive.

Two word counts are reported because they answer different questions:

  * DATA words  -- the decompressed payload. This is the "word count" the size metric names, and
                   it is the number the campaign has been quoting.
  * SPAN words  -- `max(segment_start + segment_length)`. THIS is what must fit under the ceiling;
                   a sparse segment layout can push the span past 2^27 while the data looks small.

    python scratchpad/12m/fjmsize.py build/doom_e1m1_menu.fjm
    python scratchpad/12m/fjmsize.py --selftest
"""
import argparse
import lzma
import struct
import sys
from pathlib import Path

from flipjump.fjm.fjm_consts import (FJ_MAGIC, FJMVersion, _LZMA_DECOMPRESSION_FILTERS,
                                     _LZMA_FORMAT, _header_base_format, _header_base_size,
                                     _header_extension_size, _segment_format, _segment_size)


def ceiling_words(memory_width):
    """The HARD address ceiling in words: an address is `memory_width` bits and so is a word."""
    return (1 << memory_width) // memory_width


class FjmSize:
    """what an .fjm weighs, read from its own header rather than from assumptions"""

    def __init__(self, memory_width, segment_num, data_words, span_words, file_bytes):
        self.memory_width = memory_width
        self.segment_num = segment_num
        self.data_words = data_words
        self.span_words = span_words
        self.file_bytes = file_bytes
        self.ceiling = ceiling_words(memory_width)

    @property
    def data_pct(self):
        return 100.0 * self.data_words / self.ceiling

    @property
    def span_pct(self):
        return 100.0 * self.span_words / self.ceiling

    def __str__(self):
        return ("w=%d  segments=%d  data=%s words (%.2f%% of 2^%d)  span=%s words (%.2f%%)  "
                "file=%s bytes"
                % (self.memory_width, self.segment_num, format(self.data_words, ","),
                   self.data_pct, self.ceiling.bit_length() - 1, format(self.span_words, ","),
                   self.span_pct, format(self.file_bytes, ",")))


def read_fjm_size(path):
    """Parse an .fjm's header and payload size WITHOUT building the interpreter's memory dict.

    `fjm_reader.Reader` is the single source of this format, but it materialises a word->value
    dict; on a 125M-word image that is not a thing you can hold. So the header structs come from
    `fjm_consts` (the same definitions Reader unpacks with) and the payload is only measured.
    """
    raw = Path(path).read_bytes()
    magic, memory_width, version, segment_num = struct.unpack(
        _header_base_format, raw[:_header_base_size])
    if magic != FJ_MAGIC:
        raise ValueError("%s: bad magic 0x%x (expected 0x%x) -- not an .fjm?"
                         % (path, magic, FJ_MAGIC))
    version = FJMVersion(version)
    off = _header_base_size
    if version != FJMVersion.BaseVersion:
        off += _header_extension_size                      # the flags/reserved extension
    segments = []
    for _ in range(segment_num):
        segments.append(struct.unpack(_segment_format, raw[off:off + _segment_size]))
        off += _segment_size

    payload = raw[off:]
    if version == FJMVersion.CompressedVersion:
        payload = lzma.decompress(payload, format=_LZMA_FORMAT,
                                  filters=_LZMA_DECOMPRESSION_FILTERS)
    word_bytes = memory_width // 8
    if len(payload) % word_bytes:
        raise ValueError("%s: payload of %d bytes is not a whole number of %d-byte words"
                         % (path, len(payload), word_bytes))
    data_words = len(payload) // word_bytes
    span_words = max((s[0] + s[1] for s in segments), default=0)
    return FjmSize(memory_width, segment_num, data_words, span_words, len(raw))


# ----------------------------------------------------------------------------------------------
# R9. C2-C5 are true negative controls: each FAILS against the code this file replaces.
# C0-C1 are agreement checks and are labelled as such -- claiming them as controls was a
# CR-2026-09-06 finding, since C1's w=32 single-segment case is the one the old reader
# handles correctly.
# ----------------------------------------------------------------------------------------------

TINY = "stl.startup_and_init_all\n    stl.loop\n"


def _assemble_tiny(tmp, width):
    import flipjump as fj
    src = tmp / ("tiny%d.fj" % width)
    src.write_text(TINY, encoding="utf-8")
    out = tmp / ("tiny%d.fjm" % width)
    fj.assemble([src], out, memory_width=width, print_time=False)
    return out


def _synth_fjm(memory_width, segments, data_words):
    """Build an .fjm BYTE-EXACTLY by the spec, with an arbitrary segment count.

    This is the control the real assembler cannot cheaply give: today every build the campaign
    makes has segment_num == 1, so a reader that hardcodes the 64-byte offset passes on all of
    them. Here the header is synthesised, so segment_num is ours to choose.
    """
    word_bytes = memory_width // 8
    payload = b"\x00" * (data_words * word_bytes)
    head = struct.pack(_header_base_format, FJ_MAGIC, memory_width,
                       int(FJMVersion.CompressedVersion.value), len(segments))
    head += struct.pack("<QL", 0, 0)                       # the flags/reserved extension
    for seg in segments:
        head += struct.pack(_segment_format, *seg)
    comp = lzma.compress(payload, format=_LZMA_FORMAT, filters=_LZMA_DECOMPRESSION_FILTERS)
    return head + comp


def selftest():
    import tempfile
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""),
              flush=True)
        if not cond:
            fails.append(name)

    print("fjmsize selftest -- C2..C5 are the negative controls: each FAILS against the",
          flush=True)
    print("  `data[64:]` + `//4` reader this replaces. C0/C1 are AGREEMENT checks, not",
          flush=True)
    print("  controls -- C0 tests a function the old reader never had, and C1 uses the w=32",
          flush=True)
    print("  single-segment file the old reader gets RIGHT (it also reports 21,406).",
          flush=True)

    # C0  the ceiling is arithmetic, not a constant someone typed
    check("C0 ceiling_words(32) == 134,217,728 == 2^27", ceiling_words(32) == 134_217_728)
    check("C0 ceiling_words(64) == (1<<64)//64", ceiling_words(64) == (1 << 64) // 64)
    check("C0 the ceiling MOVES with the width", ceiling_words(64) != ceiling_words(32))

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)

        # C1  round-trip a REAL assembled program: the reported data words must equal the truth
        #     that the fjm's own Reader recovers.
        from flipjump.fjm.fjm_reader import Reader
        f32 = _assemble_tiny(tmp, 32)
        got = read_fjm_size(f32)
        truth = Reader(f32)
        check("C1 real w=32 build parses (magic, width, segments)",
              got.memory_width == 32 and got.segment_num == truth.segment_num,
              "w=%d segs=%d" % (got.memory_width, got.segment_num))
        check("C1 data words > 0 (not vacuous)", got.data_words > 0,
              "%s words" % format(got.data_words, ","))
        check("C1 span >= data (segments cover the payload)", got.span_words >= got.data_words,
              "span=%s data=%s" % (format(got.span_words, ","), format(got.data_words, ",")))

        # C2  THE WIDTH CONTROL -- the bug this file was written to kill.
        #     The same program at w=64 holds the same number of WORDS. The old `//4` reader
        #     divided a 2x-larger payload by 4 and reported 2x the words.
        f64 = _assemble_tiny(tmp, 64)
        g64 = read_fjm_size(f64)
        old_reader_words = len(lzma.decompress(Path(f64).read_bytes()[64:], format=_LZMA_FORMAT,
                                               filters=_LZMA_DECOMPRESSION_FILTERS)) // 4
        check("C2 w=64 file is read as w=64", g64.memory_width == 64)
        check("C2 w=64 word count is NOT the payload/4",
              g64.data_words != old_reader_words,
              "correct=%s  old-reader=%s (%.1fx)"
              % (format(g64.data_words, ","), format(old_reader_words, ","),
                 old_reader_words / max(1, g64.data_words)))
        check("C2 the old reader OVER-counted, so its %-of-ceiling was wrong twice over",
              old_reader_words > g64.data_words)

        # C3  THE SEGMENT-COUNT CONTROL. Two segments push the payload past byte 64.
        two = _synth_fjm(32, [(0, 100, 0, 40), (1 << 20, 60, 40, 20)], data_words=60)
        p2 = tmp / "two_segments.fjm"
        p2.write_bytes(two)
        g2 = read_fjm_size(p2)
        check("C3 segment_num == 2 is read from the header", g2.segment_num == 2)
        check("C3 data words exact with 2 segments", g2.data_words == 60,
              "got %s, want 60" % format(g2.data_words, ","))
        check("C3 span is max(start+len), not the data size",
              g2.span_words == (1 << 20) + 60,
              "got %s, want %s" % (format(g2.span_words, ","), format((1 << 20) + 60, ",")))
        try:
            old = len(lzma.decompress(two[64:], format=_LZMA_FORMAT,
                                      filters=_LZMA_DECOMPRESSION_FILTERS)) // 4
            check("C3 the old 64-byte slice gets this WRONG", old != 60, "old-reader=%s" % old)
        except lzma.LZMAError:
            check("C3 the old 64-byte slice cannot even decompress it", True,
                  "LZMAError -- it sliced into the segment table")

        # C4  VACUITY. A file that is not an fjm must be REJECTED, not silently measured as 0.
        bad = tmp / "not.fjm"
        bad.write_bytes(b"\x00" * 256)
        try:
            read_fjm_size(bad)
            check("C4 a non-fjm is rejected", False, "it returned a size!")
        except ValueError as e:
            check("C4 a non-fjm is rejected", "bad magic" in str(e))

        # C5  a truncated payload must not round down to a plausible-looking count
        trunc = tmp / "trunc.fjm"
        trunc.write_bytes(two[:len(two) - 1])
        try:
            read_fjm_size(trunc)
            check("C5 a corrupt payload is rejected", False, "it returned a size!")
        except (lzma.LZMAError, ValueError, struct.error):
            check("C5 a corrupt payload is rejected", True)

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL", "" if not fails else ": " + ", ".join(fails)),
          flush=True)
    return 1 if fails else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fjm", nargs="?", help="the .fjm to weigh")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.fjm:
        ap.error("give an .fjm path, or --selftest")
    print(read_fjm_size(a.fjm), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
