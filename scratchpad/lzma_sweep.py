"""HOW MUCH OF `create binary` IS LZMA, AND WHAT DOES A LOWER PRESET BUY?

`create binary` is 97.7 s of the 758 s assemble. Almost all of it is one lzma.compress() of the
program's words. This decompresses the CERTIFIED .fjm to recover exactly those bytes, then
re-compresses at each preset, reporting time and size.

⚠ WHY THIS IS NOT FREE. A different preset produces a different .fjm FILE for the same PROGRAM.
That is safe for the build cache (walk_e1m1 keys `w_<hash>` on the emitter inputs -- the .py files,
the args and the wad -- not on the .fjm bytes), and the decompressed words are identical by
construction, which is the property that actually matters. But it does mean "byte-identical .fjm"
stops being available as the acceptance test, and the shipped standalone artifact gets bigger.
So this measures the trade; it does not take it.

    python scratchpad/lzma_sweep.py [path/to/reference.fjm]
"""
import lzma
import sys
import time
from pathlib import Path
from struct import calcsize, unpack

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from flipjump.fjm.fjm_consts import (_header_base_format, _header_extension_format,  # noqa: E402
                                     _segment_format, _LZMA_FORMAT, _lzma_compression_filters)

FJM = Path(sys.argv[1] if len(sys.argv) > 1
           else r"C:\Users\tomhe\AppData\Local\Temp\tmp97fndv92\m14.fjm")
blob = FJM.read_bytes()

off = calcsize(_header_base_format)
magic, word_size, version, segment_num = unpack(_header_base_format, blob[:off])
if version != 0:
    off += calcsize(_header_extension_format)
off += calcsize(_segment_format) * segment_num
compressed = blob[off:]

filters = _lzma_compression_filters(2 * word_size, lzma.PRESET_DEFAULT)
t0 = time.perf_counter()
raw = lzma.decompress(compressed, format=_LZMA_FORMAT, filters=filters)
decompress_s = time.perf_counter() - t0

print(f"{FJM.name}: w={word_size} version={version} segments={segment_num}")
print(f"  {len(raw):,} raw bytes ({len(raw)//(word_size//8):,} words) "
      f"-> {len(compressed):,} compressed  ({len(compressed)/len(raw):.2%})")
print(f"  decompress at load: {decompress_s:.1f} s\n")
print(f"{'preset':>8}{'compress s':>13}{'size MB':>11}{'vs default':>13}{'load s':>9}")
for preset in (0, 1, 2, 3, 4, 6, 9):
    f = _lzma_compression_filters(2 * word_size, preset)
    t0 = time.perf_counter()
    out = lzma.compress(raw, format=_LZMA_FORMAT, filters=f)
    dt = time.perf_counter() - t0
    t0 = time.perf_counter()
    back = lzma.decompress(out, format=_LZMA_FORMAT, filters=f)
    load = time.perf_counter() - t0
    assert back == raw, f"preset {preset} did not round-trip"
    tag = "  <- current" if preset == lzma.PRESET_DEFAULT else ""
    print(f"{preset:>8}{dt:>13.1f}{len(out)/1e6:>11.1f}"
          f"{len(out)/len(compressed):>12.2f}x{load:>9.1f}{tag}")
print("\nevery preset round-tripped to the SAME bytes -- the program is identical, the file is not")
