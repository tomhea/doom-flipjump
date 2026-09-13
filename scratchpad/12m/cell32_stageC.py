"""STAGE C: actually store w<=32 words in 4-byte cells, and replace the sentinel that cannot fit.

THE POINT. The binding cost is the TOUCHED CACHE FOOTPRINT, measured at 26.67 MB of distinct
64 B lines for the DOOM binary with only 3.12 of each line's 8 words ever read. Storing a 32-bit
word in 8 bytes wastes half of every line. Halving the cell halves the footprint: measured
1.65x fewer distinct lines over the same access trace, and the re-measured latency curve puts the
L2 cliff between 1.00 MB (6.2 ns) and 2.67 MB (~29 ns), so the hot set crossing back over it is
worth ~2.5x on the dependent-chase component.

THE OBSTACLE, and the whole reason this is three stages. At w<=32 the engine detects
out-of-segment reads with an IN-BAND sentinel: bit 63, which a 32-bit word can never set, so a
match is EXACT and never needs a membership check. A uint32 cell has no spare bit. Stage C
therefore switches w<=32 to the scheme the w=64 path already uses -- a magic value that CAN
collide with real data, disambiguated by segment membership -- which is why `flat_seg_contains`
had to become a binary search first (424,743 segments; a linear scan per collision would be
worse than the change is worth).

THREE PLACES THE SENTINEL BREAKS, all fixed here:
  1. the HOLE FILL. `garbage_fill` is GARBAGE_SENTINEL = 1<<63 at w<=32, which TRUNCATES TO ZERO
     when stored in a uint32 -- holes would read back as a legal 0 and out-of-segment reads would
     go undetected. Silent, and exactly the class of bug the check exists to catch.
  2. the THREE hot-loop tests, which compare against the width's sentinel.
  3. `flat_is_garbage` / `flat_garbage_check`, whose `m->w > 32` guard encodes "only w=64 can
     collide". With 4-byte cells w<=32 can collide too.

FLIPJUMP_CELL64=1 forces the old 8-byte path for A/B on one binary.
"""
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = SRC.read_text(encoding="utf-8")


def sub1(old, new, what):
    global s
    assert s.count(old) == 1, "anchor %r not unique (%d)" % (what, s.count(old))
    s = s.replace(old, new, 1)


# ── 1. the 32-bit magic ────────────────────────────────────────────────────────────────────────
sub1("""#define FLAT_GARBAGE_MAGIC 0xBB67AE8584CAA73Bull""",
     """#define FLAT_GARBAGE_MAGIC 0xBB67AE8584CAA73Bull
/* the 4-byte-cell fill. Like FLAT_GARBAGE_MAGIC it CAN collide with real data -- every 32-bit
   value is a legal word -- so a match is only a filter and membership decides. Chosen as the
   high half of the w=64 magic for no reason beyond being an unlikely address or counter. */
#define FLAT_GARBAGE_MAGIC32 0xBB67AE85u""",
     "magic32")

# ── 2. choose the cell size ────────────────────────────────────────────────────────────────────
sub1("""    m->cell_bytes = 8;   /* stage C chooses 4 at w<=32; pinned here so A and B cannot change
                            behaviour while the plumbing is verified */""",
     """    /* 4-byte cells for a program whose words fit in 32 bits: half the cache footprint, which
       is the measured binding cost. FLIPJUMP_CELL64=1 forces the old width for A/B. */
    m->cell_bytes = 8;
    if (m->w <= 32) {
        const char* force64 = getenv("FLIPJUMP_CELL64");
        m->cell_bytes = (force64 && force64[0] == '1') ? 8 : 4;
    }""",
     "cell choice")

# ── 3. the hole fill must be storable in the cell ──────────────────────────────────────────────
sub1("""        const uint64_t garbage_fill = (m->w <= 32) ? GARBAGE_SENTINEL : FLAT_GARBAGE_MAGIC;""",
     """        /* ⚠ GARBAGE_SENTINEL is bit 63 and TRUNCATES TO ZERO in a 4-byte cell -- holes would
           read back as a legal 0 and out-of-segment reads would go silently undetected. */
        const uint64_t garbage_fill = (m->cell_bytes == 4) ? (uint64_t)FLAT_GARBAGE_MAGIC32
                                    : ((m->w <= 32) ? GARBAGE_SENTINEL : FLAT_GARBAGE_MAGIC);""",
     "hole fill")

# ── 4. the predicate and the disambiguator ─────────────────────────────────────────────────────
sub1("""    return (m->w <= 32) ? ((value & GARBAGE_SENTINEL) != 0) : (value == FLAT_GARBAGE_MAGIC);""",
     """    if (m->cell_bytes == 4) {
        return value == (uint64_t)FLAT_GARBAGE_MAGIC32;
    }
    return (m->w <= 32) ? ((value & GARBAGE_SENTINEL) != 0) : (value == FLAT_GARBAGE_MAGIC);""",
     "flat_is_garbage")

sub1("""/* a flat word whose value matched the width's sentinel: decide whether it is REAL
   garbage (an out-of-segment touch - reported via flat_garbage, returns -1) or, at
   w=64, an in-segment word that legitimately holds the magic value (kept, returns 0).
   w<=32 has no collisions, so a sentinel match there is always real garbage. */
static inline int flat_garbage_check(MemoryObject* m, uint64_t word_address, uint64_t* value)
{
    if (m->w > 32 && flat_seg_contains(m, word_address)) {
        return 0; /* the word really holds the magic constant - real data */
    }""",
     """/* a flat word whose value matched the sentinel: decide whether it is REAL garbage (an
   out-of-segment touch - reported via flat_garbage, returns -1) or an in-segment word that
   legitimately holds the magic value (kept, returns 0).
   ⚠ WHICH SCHEMES CAN COLLIDE: the w<=32 in-band bit-63 sentinel cannot -- a 32-bit word can
   never set bit 63 -- so a match there is always real garbage and no membership check is needed.
   Both MAGIC schemes CAN collide: every value is a legal word, so membership decides. That is
   true of w=64 (FLAT_GARBAGE_MAGIC) and, since stage C, of 4-byte cells at any width
   (FLAT_GARBAGE_MAGIC32). Getting this guard wrong in the collide-able direction halts a correct
   program on a value that merely looked like the fill. */
static inline int flat_garbage_check(MemoryObject* m, uint64_t word_address, uint64_t* value)
{
    const int magic_can_collide = (m->cell_bytes == 4) || (m->w > 32);
    if (magic_can_collide && flat_seg_contains(m, word_address)) {
        return 0; /* the word really holds the magic constant - real data */
    }""",
     "flat_garbage_check")

# ── 5. the three hot-loop tests ────────────────────────────────────────────────────────────────
for var in ("f", "flip_value", "j"):
    sub1("            if (width <= 32 ? ((%s & GARBAGE_SENTINEL) != 0) : (%s == FLAT_GARBAGE_MAGIC)) {"
         % (var, var),
         "            if (cell32 ? (%s == (uint64_t)FLAT_GARBAGE_MAGIC32)\n"
         "                       : (width <= 32 ? ((%s & GARBAGE_SENTINEL) != 0)\n"
         "                                      : (%s == FLAT_GARBAGE_MAGIC))) {" % (var, var, var),
         "hot test %s" % var)

SRC.write_text(s, encoding="utf-8")
print("stage C applied")
