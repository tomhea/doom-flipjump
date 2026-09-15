"""Does value-ordered eviction actually keep the HOT group when the pool cannot hold both?

BQ established that SPAN is the binding resource: `BlockPool._preallocate` fills memory to the w=32
ceiling and whatever the cursor reaches last is broken -- and a broken group loses its pin for ALL
its tables, not just the one that did not fit. Allocating in descending block size therefore spends
the last of the pool arbitrarily with respect to hotness: a cold group with a 512-op slot outranks a
hot group with an 8-op one purely for being bigger.

`evict_by_value=True` drops groups by ascending tables-per-bit until demand fits. This checks it
does that, and -- the part that makes it evidence rather than assertion -- that the fixture can tell
the difference.

    python scratchpad/12m/evict_check.py --selftest

CONTROLS (R9)
  C1 NEGATIVE CONTROL -- with the flag OFF the same fixture must drop the HOT group. A fixture both
     orders satisfy proves nothing; this one has to fail without the change.
  C2 THE EVICTED GROUP IS BROKEN -- eviction must reach `broken_groups`, or the group keeps its pin
     while its tables sit inline, which is the exact corruption `broken_groups` exists to prevent.
  C3 NO EVICTION WHEN IT FITS -- ample capacity must evict nothing, so the flag is inert until span
     actually binds.
  C4 CONSERVATION -- every counted group is either allocated or broken, never silently lost.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path("C:/Users/tomhe/Documents/flipjump-151")))
from flipjump.assembler.preprocessor import BlockPool                      # noqa: E402

# big_cold: 8 tables in 512-op slots  -> 262,144 bits, 3.05e-5 tables/bit
# small_hot: 256 tables in 8-op slots -> 131,072 bits, 1.95e-3 tables/bit  (64x the value density)
COUNTS = {"big_cold": 8, "small_hot": 256}
WIDTHS = {"big_cold": 512, "small_hot": 8}
BASE = 1 << 20                 # 4 x 262,144, so the big block needs no alignment padding
TIGHT = 262144                 # room for exactly ONE of the two


def pool(evict, span_bits):
    return BlockPool(32, BASE, counts=COUNTS, widths=WIDTHS, span_bits=span_bits,
                     max_slot_ops=512, evict_by_value=evict)


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("evict_check selftest -- the fixture must FAIL without the change, or it proves nothing")

    off = pool(False, TIGHT)
    check("C1 flag OFF drops the HOT group (the bug being fixed)",
          "small_hot" in off.broken_groups and "big_cold" in off.groups,
          "allocated=%s" % sorted(off.groups))

    on = pool(True, TIGHT)
    check("   flag ON keeps the HOT group instead",
          "small_hot" in on.groups and "big_cold" not in on.groups,
          "allocated=%s" % sorted(on.groups))
    check("C2 the evicted group is BROKEN (so it loses its pin)",
          "big_cold" in on.broken_groups and on.evicted_low_value == 1,
          "evicted=%d" % on.evicted_low_value)

    roomy = pool(True, 1 << 24)
    check("C3 ample capacity evicts nothing", roomy.evicted_low_value == 0
          and set(roomy.groups) == set(COUNTS))

    for label, p in (("off", off), ("on", on), ("roomy", roomy)):
        accounted = set(p.groups) | p.broken_groups
        check("C4 conservation (%s): every group allocated or broken" % label,
              accounted == set(COUNTS), "missing=%s" % sorted(set(COUNTS) - accounted))

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.parse_args()
    sys.exit(selftest())
