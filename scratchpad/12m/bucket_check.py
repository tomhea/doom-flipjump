"""Do width-bucketed sub-blocks hand out ADDRESSES that arm correctly and never overlap?

Measured on the game tier (blocked11): of 68,224,992 ops of pool allocated, 9,041,597 hold a real
table. 41,479,139 is WIDTH PADDING -- narrow tables inflated to the slot size of the one wide
sibling in their group. 1,058 groups are "mixed" (widest > 2x most common) and hold 21,388 tables.

Uniform slots are not required by the arming mechanism. It needs exactly one thing:

    base ^ offset == base + offset          (equivalently base & offset == 0)

which holds whenever the base is aligned to the block size and the offset lies inside the block.
Per-width sub-blocks keep that, so the padding is recoverable. This checks the implementation
actually does, on addresses rather than on the argument.

    python scratchpad/12m/bucket_check.py --selftest

CONTROLS (R9)
  C1 IT ACTUALLY SHRINKS -- a mixed group must get a smaller block, or the pass is a no-op that
     every other control would still pass.
  C2 HOMOGENEOUS GROUPS ARE UNTOUCHED -- one width in, byte-identical layout out. This is the
     blast radius: if it fails, the pass is not opt-in in the way the numbers assume.
  C3 CONTAINMENT -- every table must lie wholly inside its own group's block. A table that runs
     past the end lands in the NEXT group's block, which is the real corruption.
  C4 NEGATIVE CONTROL for C3 -- a bucket pushed past the block end must be REJECTED.
  C5 NO OVERLAP -- no two tables may share a word. The fjm writer rejects overlapping segments
     (measured once: seg[207408] and seg[207409] both at 0x96130000), and that is a build-time
     crash, not a wrong pixel -- so catch it here.
  C6 NEGATIVE CONTROL for C5 -- two buckets given the SAME offset must be REJECTED.
  C7 CONSERVATION -- every reserve call either allocates or declines with a counted reason.
  C8 THE SAVING IS REAL -- `(base + offset) ^ base == offset`, so arming flips the offset and
     nothing else. This is a COST property, not a correctness one: the base cancels in
     `base ^ (V ^ base) == V` for ANY V, so a bad layout would still render correctly and merely
     cost more ops. That is precisely why it needs its own check -- no gate would catch it.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path("C:/Users/tomhe/Documents/flipjump-151")))
from flipjump.assembler.preprocessor import BlockPool                      # noqa: E402

W = 32
OP_BITS = 2 * W
BASE = 1 << 31
# 'mixed' is the shape the game tier actually has: many narrow tables, one wide sibling.
HIST = {"mixed": {8: 300, 512: 2}, "plain": {8: 300}, "three": {4: 64, 32: 8, 256: 2}}
COUNTS = {g: sum(h.values()) for g, h in HIST.items()}
WIDTHS = {g: max(h) for g, h in HIST.items()}


def pool(buckets, **kw):
    return BlockPool(W, BASE, counts=COUNTS, widths=WIDTHS, width_hist=HIST,
                     width_buckets=buckets, max_slot_ops=512, **kw)


def allocate_all(p):
    """Drive reserve() exactly as the assembler does: every table, in its group, at its width."""
    out = []
    for g, h in HIST.items():
        for w, c in sorted(h.items()):
            for _ in range(c):
                got = p.reserve(w, w, g, None)
                if got is not None:
                    out.append((g, w, got[0]))
    return out


def selftest():
    fails = []

    def check(name, cond, detail=""):
        print("  %-58s %s%s" % (name, "ok" if cond else "FAIL", ("  " + detail) if detail else ""))
        if not cond:
            fails.append(name)

    print("bucket_check selftest -- C4 must FAIL a broken layout, or C3 proves nothing")

    on, off = pool(True), pool(False)
    check("C1 a mixed group's block shrinks", on._block_bits("mixed") < off._block_bits("mixed"),
          "%s -> %s bits" % (format(off._block_bits("mixed"), ","),
                             format(on._block_bits("mixed"), ",")))
    check("C1 ...and so does a three-width group",
          on._block_bits("three") < off._block_bits("three"),
          "%s -> %s bits" % (format(off._block_bits("three"), ","),
                             format(on._block_bits("three"), ",")))
    check("C2 a homogeneous group is UNCHANGED",
          on._block_bits("plain") == off._block_bits("plain"),
          "%s bits both" % format(on._block_bits("plain"), ","))

    got = allocate_all(on)
    check("C7 conservation: allocated + declined == tables offered",
          len(got) + on.declined == sum(COUNTS.values()),
          "%d + %d vs %d" % (len(got), on.declined, sum(COUNTS.values())))

    def escapes(p, rows):
        out = []
        for g, w, a in rows:
            base = p.groups[g][0]
            if not (base <= a and a + w * OP_BITS <= base + p._block_bits(g)):
                out.append((g, a))
        return out

    def overlaps(rows):
        spans = sorted((a, a + w * OP_BITS) for _g, w, a in rows)
        return [(spans[i], spans[i + 1]) for i in range(len(spans) - 1)
                if spans[i][1] > spans[i + 1][0]]

    check("C3 every table lies wholly inside its own block", not escapes(on, got),
          "%d escapes" % len(escapes(on, got)))
    check("C5 no two tables overlap", not overlaps(got), "%d overlaps" % len(overlaps(got)))
    check("C5 ...and every address is distinct", len({a for _g, _w, a in got}) == len(got))
    cost = [a for g, _w, a in got
            if ((on.groups[g][0] + (a - on.groups[g][0])) ^ on.groups[g][0]) != a - on.groups[g][0]]
    check("C8 arming flips the offset and nothing else", not cost, "%d costly" % len(cost))

    # C4 NEGATIVE CONTROL -- push a bucket past the end of its block; C3 must catch it.
    esc = pool(True)
    layout, total = esc._bucket_layout("mixed")
    sw = max(layout)
    off_, slots, cnt = layout[sw]
    layout[sw] = (total, slots, cnt)                    # starts exactly at the block end
    esc._layout_cache["mixed"] = (layout, total)
    check("C4 a bucket past the block end is REJECTED by C3",
          bool(escapes(esc, allocate_all(esc))))

    # C6 NEGATIVE CONTROL -- collide two buckets; C5 must catch it.
    col = pool(True)
    layout, total = col._bucket_layout("mixed")
    narrow, wide = min(layout), max(layout)
    off_n = layout[narrow][0]
    slots, cnt = layout[wide][1], layout[wide][2]
    layout[wide] = (off_n, slots, cnt)                  # both buckets at one offset
    col._layout_cache["mixed"] = (layout, total)
    check("C6 two buckets at one offset are REJECTED by C5",
          bool(overlaps(allocate_all(col))))

    print("")
    print("SELFTEST %s%s" % ("PASS" if not fails else "FAIL",
                             "" if not fails else ": " + ", ".join(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.parse_args()
    sys.exit(selftest())
