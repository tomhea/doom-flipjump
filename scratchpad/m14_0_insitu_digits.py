"""M14-0 spike, part 1 of 2: the IN-SITU cost of one decimal input DIGIT, measured inside a real
~12MB E1M1 binary (not a toy program, where `@` -- the wflip cost, which scales with the set bits of
a label's ADDRESS -- is far smaller).

Method: leading zeros. `hex.input_dec_uint`/`input_dec_int` consume ASCII digits until the
terminator, so "0000001869" and "1869" are the SAME VALUE but 6 digits apart. Re-run one cached
binary over both and diff op_counter.

NEGATIVE CONTROL (R9): the frame bytes MUST be identical across every run -- if padding changed the
value, the pixels would move and the delta would be measuring something else. The script fails if
any padded run's frame differs from the base run's.

Usage:  python scratchpad/m14_0_insitu_digits.py [path/to.fjm]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))

import flipjump as fj
from doomfj.harness import W                                    # noqa: F401  (memory width, doc)
from doomfj.wireformat import encode_feed_mapunits
from tests.fj.stream_screen import StreamScreen

FJM = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "scratchpad/fjmcache/b_272d37507ca58434.fjm"
VX, VY, VA = 1869, 479, 2147483648      # the deg_gate "everything" viewpoint


def pad(n: int, width: int) -> str:
    """The same integer, written with leading zeros to `width` digits (sign kept in front)."""
    s = str(abs(n)).rjust(width, "0")
    return ("-" + s) if n < 0 else s


def run(sx: str, sy: str, sa: str):
    scr = StreamScreen(stdin=encode_feed_mapunits(sx, sy, sa))
    t = time.perf_counter()
    term = fj.run(FJM, io_device=scr, print_time=False, print_termination=False,
                  flat_max_words=1 << 26)
    return term.op_counter, bytes(scr.pixel_indices), time.perf_counter() - t


def main():
    print(f"binary: {FJM.name}  ({FJM.stat().st_size:,} bytes)", flush=True)
    base_s = (str(VX), str(VY), str(VA))
    base_ops, base_px, secs = run(*base_s)
    print(f"base  vx={base_s[0]} vy={base_s[1]} va={base_s[2]}  -> {base_ops:,} ops  ({secs:.1f}s)",
          flush=True)

    # each probe pads exactly ONE field, so the delta is attributable to that field's macro
    probes = [
        ("vx  hex.input_dec_int 10", (pad(VX, 10), base_s[1], base_s[2]), 10 - len(str(abs(VX)))),
        ("vy  hex.input_dec_int 10", (base_s[0], pad(VY, 10), base_s[2]), 10 - len(str(abs(VY)))),
        ("va  hex.input_dec_uint 8", (base_s[0], base_s[1], pad(VA, 20)), 20 - len(str(VA))),
    ]
    ok = True
    for name, args, extra in probes:
        ops, px, secs = run(*args)
        same = px == base_px
        ok &= same
        print(f"{name}: +{extra} digits -> {ops:,} ops   delta {ops - base_ops:+,}   "
              f"per digit {(ops - base_ops) / extra:,.0f}   "
              f"frame {'IDENTICAL' if same else '!! DIFFERS (probe invalid)'}   ({secs:.1f}s)",
              flush=True)
    print("PASS" if ok else "FAIL -- a padded run changed the frame; the deltas are not comparable")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
