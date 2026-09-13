"""STAGE A of the 4-byte-cell change: make the flat array's CELL TYPE a variable, change nothing.

WHY STAGED. The flat array is read and written from 31 sites, several inside the interpreter's
hottest loop, and it is the mechanism the engine uses to detect out-of-segment reads. Doing the
type change and the behaviour change at once would leave no way to tell a layout mistake from a
garbage-detection mistake. So:

  A  `flat` becomes `void*` with a `cell_bytes` field and inline accessors; every COLD site goes
     through them; cell_bytes is pinned to 8. Behaviour must be bit-identical -- that is the whole
     point of the stage, and it is checked by op-counts and DOOM pixels before B starts.
  B  template the hot loop on the cell size, still pinned to 8.
  C  switch w<=32 to 4-byte cells and replace the in-band bit-63 sentinel (which has no room in a
     uint32) with the magic-plus-membership scheme the w=64 path already uses.

The accessors take one predictable branch, which is fine on the cold paths; the hot loop never
uses them (stage B folds the choice at compile time from a literal template argument, the same
way `width`/`ww` are already folded).
"""
from pathlib import Path

SRC = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = SRC.read_text(encoding="utf-8")
before = s


def sub1(old, new, what):
    global s
    assert s.count(old) == 1, "anchor not unique (%d) for: %s" % (s.count(old), what)
    s = s.replace(old, new, 1)


# ── 1. the field: a typeless pointer plus the cell size ────────────────────────────────────────
sub1("""    /* flat-storage mode (built at the first run when eligible; NULL = paged mode) */
    uint64_t* flat;""",
     """    /* flat-storage mode (built at the first run when eligible; NULL = paged mode) */
    void* flat;           /* cells are `cell_bytes` wide: uint64_t today, uint32_t at w<=32 once
                             stage C lands. Typeless so the two cannot be confused by accident;
                             every access goes through flat_load/flat_store or, in the hot loop,
                             a compile-time-folded branch. */
    int cell_bytes;       /* 8 or 4. A w<=32 program's words fit in 4 bytes, which halves the
                             touched cache footprint -- the measured binding cost. */""",
     "flat field")

# ── 2. the accessors, right after flat_seg_contains so they can use the garbage helpers ────────
ANCHOR = "/* a flat word whose value matched the width's sentinel: decide whether it is REAL"
sub1(ANCHOR, """/* the flat array's cells are `cell_bytes` wide; these are the ONLY way the cold paths touch
   them. The branch is predictable and these are not on the per-op path -- the hot loop folds the
   same choice at compile time instead. */
static FJ_ALWAYS_INLINE uint64_t flat_load(const MemoryObject* m, uint64_t i)
{
    return (m->cell_bytes == 4) ? (uint64_t)((const uint32_t*)m->flat)[i]
                                : ((const uint64_t*)m->flat)[i];
}

static FJ_ALWAYS_INLINE void flat_store(MemoryObject* m, uint64_t i, uint64_t v)
{
    if (m->cell_bytes == 4) {
        ((uint32_t*)m->flat)[i] = (uint32_t)v;
    } else {
        ((uint64_t*)m->flat)[i] = v;
    }
}

""" + ANCHOR, "accessors")

# ── 3. every cold site ─────────────────────────────────────────────────────────────────────────
sub1("""    if (m->flat && word_address < m->flat_count) {
        uint64_t value = m->flat[word_address];
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        *out = value;
        return 0;
    }""",
     """    if (m->flat && word_address < m->flat_count) {
        uint64_t value = flat_load(m, word_address);
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        *out = value;
        return 0;
    }""", "mem_read_word")

sub1("""        uint64_t value = m->flat[word_address];
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        m->flat[word_address] = value ^ (1ull << (bit_address & (uint64_t)(m->w - 1)));""",
     """        uint64_t value = flat_load(m, word_address);
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        flat_store(m, word_address, value ^ (1ull << (bit_address & (uint64_t)(m->w - 1))));""",
     "mem_flip_bit")

sub1("""        uint64_t value = m->flat[word_address];
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        m->flat[word_address] = bit_value ? (value | bit) : (value & ~bit);""",
     """        uint64_t value = flat_load(m, word_address);
        if (flat_is_garbage(m, value) && flat_garbage_check(m, word_address, &value) < 0) {
            return -1;
        }
        flat_store(m, word_address, bit_value ? (value | bit) : (value & ~bit));""",
     "mem_write_bit")

sub1("            m->flat[i] = garbage_fill;", "            flat_store(m, i, garbage_fill);",
     "sentinel fill")
sub1("        self->flat[word_address] = value & self->word_mask;",
     "        flat_store(self, word_address, value & self->word_mask);", "set_word")
sub1("        return PyLong_FromUnsignedLongLong(self->flat[word_address]);",
     "        return PyLong_FromUnsignedLongLong(flat_load(self, word_address));", "get_word")
sub1("            self->flat[start_word + i] = value & self->word_mask;",
     "            flat_store(self, start_word + i, value & self->word_mask);", "set_words")

# ── 4. allocation, free, and the memset/memcpy paths must use cell_bytes, not sizeof(uint64_t) ─
sub1("""    m->flat = (uint64_t*)fj_alloc_flat((size_t)low_max_end * sizeof(uint64_t), &m->flat_large);""",
     """    m->cell_bytes = 8;   /* stage C chooses 4 at w<=32; pinned here so A and B cannot change
                            behaviour while the plumbing is verified */
    m->flat = fj_alloc_flat((size_t)low_max_end * (size_t)m->cell_bytes, &m->flat_large);""",
     "flat alloc")
sub1("""    if (low_max_end > SIZE_MAX / sizeof(uint64_t)) {""",
     """    if (low_max_end > SIZE_MAX / 8u) {""", "overflow guard")
sub1("""            memset(m->flat + start, 0, (size_t)(end_clamped - start) * sizeof(uint64_t));""",
     """            memset((char*)m->flat + (size_t)start * (size_t)m->cell_bytes, 0,
                   (size_t)(end_clamped - start) * (size_t)m->cell_bytes);""", "segment zero-fill")
sub1("""    fj_free_flat(self->flat, self->flat_large, (size_t)self->flat_count * sizeof(uint64_t));""",
     """    fj_free_flat(self->flat, self->flat_large,
                 (size_t)self->flat_count * (size_t)(self->cell_bytes ? self->cell_bytes : 8));""",
     "flat free")

# ── 5. init the new field wherever flat is initialised ─────────────────────────────────────────
sub1("""    self->flat = NULL;
    self->flat_large = 0;
    self->flat_count = 0;""",
     """    self->flat = NULL;
    self->flat_large = 0;
    self->cell_bytes = 8;
    self->flat_count = 0;""", "init")

SRC.write_text(s, encoding="utf-8")
print("stage A applied: %d -> %d bytes, %d edits" % (len(before), len(s), 13))
