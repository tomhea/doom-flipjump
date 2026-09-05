"""Repack a .fjm's data blob at LZMA preset 9|EXTREME. The decoded image is byte-identical, so
frame speed CANNOT change -- this trades ~10 minutes of one-time encode for ~7% of file size.

WHY THIS IS A REPACK TOOL AND NOT A WRITER CHANGE. Compression is a pure post-process: the
version-3 header (64 bytes: base + extension + one segment record) describes the DECOMPRESSED
data and does not mention the blob's encoding, so swapping the blob is valid by construction.
Keeping the builds on today's fast compression preserves the 20-gate-day iteration loop; only a
ship artifact pays the 581 s. (The writer's own `lzma_preset` also REJECTS the |EXTREME bit --
`lzma_preset not in range(10)` -- another reason to post-process.)

Measured on P7B.fjm (2026-09-05): 15,168,954 -> 14,080,237 bytes (-7.18%); decode 1.11 s -> 1.00 s
(faster: less data to pull). Requires the flipjump-151 reader dict bump (dict_size 1<<26 in
_LZMA_DECOMPRESSION_FILTERS), which still reads every old preset-6 file.

VERIFICATION IS PART OF THE TOOL: after writing, it re-reads BOTH files through the flipjump
package's OWN reader filters and requires bit-identical decompressed images. R9 negative control
(--selftest): corrupt one byte of the repacked blob and require that verification to FAIL.

    python scratchpad/12m/repack.py <in.fjm> [out.fjm]     (default: in-place, .bak kept)
    python scratchpad/12m/repack.py --selftest <in.fjm>
"""
import lzma
import sys
import time
from pathlib import Path

sys.path.insert(0, "C:/Users/tomhe/Documents/flipjump-151")
from flipjump.fjm.fjm_consts import _LZMA_DECOMPRESSION_FILTERS, _LZMA_FORMAT  # noqa: E402

HEADER = 64          # magic+version header, extension, one segment record -- verified on P7B
FILTERS_9E = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]


def read_image(path):
    data = Path(path).read_bytes()
    return data[:HEADER], lzma.decompress(data[HEADER:], format=_LZMA_FORMAT,
                                          filters=_LZMA_DECOMPRESSION_FILTERS)


def repack(src, dst):
    t0 = time.time()
    header, raw = read_image(src)
    print("decoded %s bytes from %s" % (format(len(raw), ","), src))
    t = time.time()
    blob = lzma.compress(raw, format=_LZMA_FORMAT, filters=FILTERS_9E)
    print("encoded 9|EXTREME in %.0f s" % (time.time() - t))
    Path(dst).write_bytes(header + blob)

    # verification through the package's own reader filters -- the interpreter's exact call
    _, back = read_image(dst)
    if back != raw:
        Path(dst).unlink()
        raise SystemExit("!! VERIFY FAILED: repacked image differs -- output deleted")
    a, b = Path(src).stat().st_size, Path(dst).stat().st_size
    print("VERIFY: decompressed images bit-identical through the flipjump reader")
    print("%s -> %s bytes (%+.2f%%), %.0f s total"
          % (format(a, ","), format(b, ","), 100.0 * (b - a) / a, time.time() - t0))
    return a, b


def selftest(src):
    """R9: the verification must be able to FAIL. Corrupt one byte mid-blob and require it to."""
    tmp = Path(src).with_suffix(".selftest.fjm")
    repack(src, tmp)
    data = bytearray(tmp.read_bytes())
    data[len(data) // 2] ^= 0xFF
    tmp.write_bytes(bytes(data))
    try:
        _, back = read_image(tmp)
        _, raw = read_image(src)
        caught = back != raw
    except lzma.LZMAError:
        caught = True
    tmp.unlink()
    print("NEGATIVE CONTROL: corrupted repack %s" % ("REJECTED -- selftest PASS" if caught
                                                     else "!! ACCEPTED -- the verify is vacuous"))
    raise SystemExit(0 if caught else 1)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--selftest"]
    if not args:
        raise SystemExit(__doc__)
    if "--selftest" in sys.argv:
        selftest(args[0])
    src = args[0]
    dst = args[1] if len(args) > 1 else args[0]
    if dst == src:
        bak = Path(src).with_suffix(".fjm.bak")
        Path(src).replace(bak)
        repack(bak, src)
        print("original kept at %s" % bak)
    else:
        repack(src, dst)
