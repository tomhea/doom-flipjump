"""How far over the w=32 ceiling (2^27 words = 2^32 bits) is the hosted-loop tier?

ca_labels.py dies in insert_wflip_ops with OverflowError because a wflip address exceeded 2^32
bits. This drives the SAME build but monkeypatches get_wflip_spot to track the max address handed
out, so when the overflow hits we can report the peak in WORDS and how far past 2^27 it is -- the
number that says whether S2's reach or a pad rollback is enough.

Read-only w.r.t. the repo: writes nothing but its own log line.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import selfreset                                          # noqa: E402
from doomfj.build import build_wall_renderer                          # noqa: E402
import flipjump.assembler.assembler as asm                            # noqa: E402

CEIL_WORDS = 1 << 27            # 2^27 words = 2^32 bits = the w=32 address ceiling
BITS_PER_WORD = 32

peak = {"addr_bits": 0, "spots": 0}
_real_spot = asm.BinaryData.get_wflip_spot


def _spy_spot(self):
    s = _real_spot(self)
    peak["spots"] += 1
    if s.address > peak["addr_bits"]:
        peak["addr_bits"] = s.address
    return s


asm.BinaryData.get_wflip_spot = _spy_spot

# abort right after pass 1 the way ca_labels does, so we do not pay pass 2
_real_emit = selfreset.emit_reset_part


class Done(Exception):
    pass


def _stop(*a, **k):
    raise Done()


print("driving %s build to pass 1 (instrumented) ..." % (sys.argv[1] if len(sys.argv)>1 else "hosted-loop"), flush=True)
err = None
try:
    selfreset.emit_reset_part = _stop
    import sys as _s
    _tier = _s.argv[1] if len(_s.argv) > 1 else "hosted-loop"
    build_wall_renderer(ROOT / "build/overflow_probe.fjm", tier=_tier)
except Done:
    print("reached emit_reset_part WITHOUT overflow -- the tier fits", flush=True)
except OverflowError as e:
    err = e
except Exception as e:                                                # noqa: BLE001
    err = e

peak_words = peak["addr_bits"] // BITS_PER_WORD
print("", flush=True)
print("wflip spots handed out : %s" % format(peak["spots"], ","), flush=True)
print("peak wflip address     : %s bits = %s words" % (format(peak["addr_bits"], ","),
                                                        format(peak_words, ",")), flush=True)
print("ceiling                : %s words (2^27)" % format(CEIL_WORDS, ","), flush=True)
over = peak_words - CEIL_WORDS
print("OVER by                : %s words (%.1f%% of the ceiling)"
      % (format(over, "+,"), 100.0 * over / CEIL_WORDS), flush=True)
if err is not None:
    print("crash: %s: %s" % (type(err).__name__, str(err)[:80]), flush=True)
print("DONE", flush=True)
