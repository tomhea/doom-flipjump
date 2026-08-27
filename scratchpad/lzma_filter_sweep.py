"""Can `create binary` get its 96 s back WITHOUT a bigger .fjm and WITHOUT touching the reader?

`create binary` is 99.9% one lzma.compress (106.2 s of a 106.3 s phase, measured by py-spy on the
real build). The preset sweep found a cliff -- preset 3 costs 11.1 s, preset 4 costs 86.5 s -- which
is where LZMA switches from MODE_FAST/HC4 to MODE_NORMAL/BT4. flipjump compresses with
`{id: FILTER_LZMA2, preset: P, nice_len: 2*w}`, i.e. nice_len=64, the MAXIMUM, which forces the
match finder to keep searching for very long matches.

⚠ THE POINT: `mode`, `mf`, `nice_len` and `depth` are ENCODER-ONLY knobs. Only `dict_size` (and
lc/lp/pb) change what the DECODER needs. So if a faster match finder at the SAME dict_size gets a
similar ratio, the .fjm stays readable by every existing reader and every already-built binary --
no format change, no reader change, no artifact-size cost. This measures exactly that.

Each candidate is round-tripped through the READER'S OWN filter spec, not its own, which is the
property that has to hold.

    python scratchpad/lzma_filter_sweep.py [path/to/reference.fjm]
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
_magic, word_size, version, segment_num = unpack(_header_base_format, blob[:off])
if version != 0:
    off += calcsize(_header_extension_format)
off += calcsize(_segment_format) * segment_num

NICE = 2 * word_size
READER = _lzma_compression_filters(NICE, lzma.PRESET_DEFAULT)   # what the decoder is handed today
raw = lzma.decompress(blob[off:], format=_LZMA_FORMAT, filters=READER)
baseline = len(blob[off:])
print(f"{FJM.name}: {len(raw):,} raw bytes; shipped compressed size {baseline:,}")
print(f"reader filter spec: {READER}\n")


def spec(**over):
    f = {"id": lzma.FILTER_LZMA2, "preset": lzma.PRESET_DEFAULT, "nice_len": NICE}
    f.update(over)
    return [f]


CANDIDATES = [
    ("preset 6, as shipped", spec()),
    ("preset 6 + MODE_FAST/HC4", spec(mode=lzma.MODE_FAST, mf=lzma.MF_HC4)),
    ("preset 6 + MODE_FAST/HC4, nice 32", spec(mode=lzma.MODE_FAST, mf=lzma.MF_HC4, nice_len=32)),
    ("preset 6 + MODE_FAST/HC4, nice 16", spec(mode=lzma.MODE_FAST, mf=lzma.MF_HC4, nice_len=16)),
    ("preset 6 + MODE_NORMAL/HC4", spec(mode=lzma.MODE_NORMAL, mf=lzma.MF_HC4)),
    ("preset 6 + BT4, depth 8", spec(depth=8)),
    ("preset 9 dict + MODE_FAST/HC4", spec(preset=9, mode=lzma.MODE_FAST, mf=lzma.MF_HC4)),
    ("preset 3 (the earlier sweep's pick)", spec(preset=3)),
]

print(f"{'candidate':<38}{'compress s':>12}{'size MB':>10}{'vs shipped':>12}{'reader ok':>11}")
for name, filters in CANDIDATES:
    t0 = time.perf_counter()
    out = lzma.compress(raw, format=_LZMA_FORMAT, filters=filters)
    dt = time.perf_counter() - t0
    try:                                    # decode with the READER's spec, not this candidate's
        ok = lzma.decompress(out, format=_LZMA_FORMAT, filters=READER) == raw
    except lzma.LZMAError:
        ok = False
    print(f"{name:<38}{dt:>12.1f}{len(out)/1e6:>10.1f}{len(out)/baseline:>11.3f}x"
          f"{'yes' if ok else 'NO':>11}")

print("\n'reader ok' = the existing decoder, handed its existing filter spec, reproduces the exact")
print("bytes. A 'yes' row costs nothing in compatibility: same dict_size, encoder-only knobs.")
