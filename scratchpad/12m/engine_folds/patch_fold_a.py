"""fold (a): the full-span flat array (+ guard cell) and the span-check-free loop instantiation."""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:80])
    s = s.replace(old, new)


# E1: fields
rep("""    uint64_t flat_count;
    uint64_t flat_max_words; /* constructor override; 0 = use the env var / default */
""", """    uint64_t flat_count;
    uint64_t flat_alloc_count; /* cells actually allocated: flat_count + 1 -- one GUARD cell past the
                                  window, garbage-filled -- or, in full-span mode, the whole address
                                  space + 1. Sized by this, never by flat_count. See mem_decide_storage. */
    int flat_full_span;   /* 1: w=32, 4-byte cells, limit >= 2^27: the array holds EVERY 32-bit address,
                             so run_flat_loop's full_span instantiation runs without span checks. */
    uint64_t flat_max_words; /* constructor override; 0 = use the env var / default */
""")

# E2: init
rep("""    self->flat_count = 0;
    self->flat_max_words = flat_max_words;
""", """    self->flat_count = 0;
    self->flat_alloc_count = 0;
    self->flat_full_span = 0;
    self->flat_max_words = flat_max_words;
""")

# E3: free by the allocated size
rep("""    fj_free_flat(self->flat, self->flat_large,
                 (size_t)self->flat_count * (size_t)(self->cell_bytes ? self->cell_bytes : 8));
""", """    fj_free_flat(self->flat, self->flat_large,
                 (size_t)self->flat_alloc_count * (size_t)(self->cell_bytes ? self->cell_bytes : 8));
""")

# E4: allocation + fill
rep("""    m->flat = fj_alloc_flat((size_t)low_max_end * (size_t)m->cell_bytes, &m->flat_large);
    if (!m->flat) {
        fprintf(stderr, "flipjump: flat-storage allocation failed; running paged (slower). lower --flat-max-words / "
                "FLIPJUMP_FLAT_MAX_WORDS, or set FLIPJUMP_NO_FLAT=1 to silence this.\\n");
        fflush(stderr);
        return 0; /* paged fallback - the program still runs, just slower */
    }
    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);
    {
        /* \u26a0 GARBAGE_SENTINEL is bit 63 and TRUNCATES TO ZERO in a 4-byte cell -- holes would
           read back as a legal 0 and out-of-segment reads would go silently undetected. */
        const uint64_t garbage_fill = (m->cell_bytes == 4) ? (uint64_t)FLAT_GARBAGE_MAGIC32
                                    : ((m->w <= 32) ? GARBAGE_SENTINEL : FLAT_GARBAGE_MAGIC);
        for (i = 0; i < low_max_end; i++) {
            flat_store(m, i, garbage_fill);
        }
    }
""", """    /* FULL SPAN: a w=32 program with 4-byte cells whose flat limit admits the whole 32-bit address
       space (2^27 words) gets an array over ALL of it -- not just up to the last segment -- so that
       every address the run loop can form is inside the array, and the loop's three per-op span
       checks are compiled out (run_flat_loop_impl, full_span). The words past the last segment are
       garbage-filled like any gap, so an errant access there halts through the sentinel path with
       the same error address the paged path reported. Cost: the tail's fill (~150 MB for the game)
       and its resident memory, paid once per process. `flat_count` stays the semantic window (the
       last segment's end): freeze/reset, set_words and the API accessors are unchanged.

       THE GUARD CELL: one extra cell past the array, garbage-filled, so that the jump-word read of
       an op sitting in the LAST word -- word_address + 1 == the array size -- reads the sentinel
       instead of running off the end, at every width and in every mode. */
    m->flat_full_span = (m->w == 32 && m->cell_bytes == 4 && limit >= (1ull << 27));
    m->flat_alloc_count = (m->flat_full_span ? (1ull << 27) : low_max_end) + 1;
    m->flat = fj_alloc_flat((size_t)m->flat_alloc_count * (size_t)m->cell_bytes, &m->flat_large);
    if (!m->flat) {
        m->flat_alloc_count = 0;
        m->flat_full_span = 0;
        fprintf(stderr, "flipjump: flat-storage allocation failed; running paged (slower). lower --flat-max-words / "
                "FLIPJUMP_FLAT_MAX_WORDS, or set FLIPJUMP_NO_FLAT=1 to silence this.\\n");
        fflush(stderr);
        return 0; /* paged fallback - the program still runs, just slower */
    }
    m->flat_count = low_max_end;
    m->flat_covers_all = (max_end <= low_max_end);
    {
        /* \u26a0 GARBAGE_SENTINEL is bit 63 and TRUNCATES TO ZERO in a 4-byte cell -- holes would
           read back as a legal 0 and out-of-segment reads would go silently undetected. */
        const uint64_t garbage_fill = (m->cell_bytes == 4) ? (uint64_t)FLAT_GARBAGE_MAGIC32
                                    : ((m->w <= 32) ? GARBAGE_SENTINEL : FLAT_GARBAGE_MAGIC);
        for (i = 0; i < m->flat_alloc_count; i++) { /* the window, the full-span tail, the guard */
            flat_store(m, i, garbage_fill);
        }
    }
""")

# E5: allocated_bytes reports what is allocated
rep("""    return PyLong_FromUnsignedLongLong(self->flat_count * (uint64_t)self->cell_bytes +
""", """    return PyLong_FromUnsignedLongLong(self->flat_alloc_count * (uint64_t)self->cell_bytes +
""")

# E6: the getter + registration
rep("""static PyObject* Memory_get_storage_mode(MemoryObject* self, void* closure)
""", """static PyObject* Memory_get_flat_full_span(MemoryObject* self, void* closure)
{
    (void)closure;
    /* observability for the span-check-free loop: an A/B of it is only evidence if the caller can
       SEE which loop ran (same reason cell_bytes is exposed). */
    return PyBool_FromLong(self->flat_full_span ? 1 : 0);
}

static PyObject* Memory_get_storage_mode(MemoryObject* self, void* closure)
""")
rep("""    {"large_pages", (getter)Memory_get_large_pages, NULL,
""", """    {"flat_full_span", (getter)Memory_get_flat_full_span, NULL,
     "True when the flat image spans the whole 32-bit address space (w=32, 4-byte cells, "
     "flat_max_words >= 2**27) and the run loop therefore carries no per-op span checks.", NULL},
    {"large_pages", (getter)Memory_get_large_pages, NULL,
""")

# E7: the impl -- signature, the three span checks, the unaligned parking, the guard routing
rep("""   - width/ww arrive as literals from run_flat_loop's dispatch, so the shifts and the
     IO-range constants are immediates - freeing enough registers that the loop's live
     values stop spilling to the stack.
   returns the termination cause, or CAUSE_PYTHON_ERROR with the python error set. */
static FJ_ALWAYS_INLINE int run_flat_loop_impl(MemoryObject* self, PyObject* read_bit, PyObject* write_bit,
                                               PyObject* eof_exception_type, uint64_t start_ip, uint64_t* ops_out,
                                               double* paused_seconds_out, const uint64_t width, const uint64_t ww,
                                               const int cell32)
{
""", """   - width/ww arrive as literals from run_flat_loop's dispatch, so the shifts and the
     IO-range constants are immediates - freeing enough registers that the loop's live
     values stop spilling to the stack.
   - `full_span` (a literal too) compiles the three per-op span checks out. THE PROOF that they
     can never fire there (w=32, 4-byte cells, the array covers all 2^27 words + a guard cell,
     start_ip < 2^32 checked at dispatch):
       ip: start_ip < 2^32, and every later ip is a jump word j -- a uint32 cell value -- so
           word_address = ip >> 5 <= 2^27 - 1: the flip word is always inside the array;
       f:  a uint32 cell value, so flip_word_address = f >> 5 <= 2^27 - 1: the flip target too;
       j:  read at word_address + 1 <= 2^27, inside the array except for exactly the op in the
           LAST word, which reads index 2^27 -- the GUARD CELL, garbage-filled, so that read takes
           the sentinel cold path, which sends indices past the window to the same slow read the
           span check used to (cold_jump_word_slow: mem_get_word_unaligned(ip + width), a memory
           error at bit address 2^32, as before). The unaligned cold path parks word_address one
           below the guard for the same reason (in general mode it uses (uint64_t)-2, which fails
           the span check).
     Everything else -- the garbage sentinels, IO, the flip -- is unchanged, so the full-span loop
     is the general loop minus three never-taken branches.
   returns the termination cause, or CAUSE_PYTHON_ERROR with the python error set. */
static FJ_ALWAYS_INLINE int run_flat_loop_impl(MemoryObject* self, PyObject* read_bit, PyObject* write_bit,
                                               PyObject* eof_exception_type, uint64_t start_ip, uint64_t* ops_out,
                                               double* paused_seconds_out, const uint64_t width, const uint64_t ww,
                                               const int cell32, const int full_span)
{
""")
rep("""    const uint64_t flat_count = self->flat_count;

    uint64_t ip = start_ip, ops = 0;
""", """    const uint64_t flat_count = self->flat_count;
    /* one past the last index a jump-word read can name: the address space itself in full-span
       mode (the guard cell sits there), the window otherwise */
    const uint64_t span_end = full_span ? (1ull << (width - ww)) : flat_count;

    uint64_t ip = start_ip, ops = 0;
""")
rep("""            word_address = ip >> ww;
            if (word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }
            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
""", """            word_address = ip >> ww;
            if (!full_span && word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }
            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
""")
rep("""            flip_word_address = f >> ww;
            if (flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }
""", """            flip_word_address = f >> ww;
            if (!full_span && flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }
""")
rep("""            /* read jump word (after the flip - the flip may modify it). word_address is
               (uint64_t)-2 for unaligned ops, so they take the slow read too. */
            if (word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
""", """            /* read jump word (after the flip - the flip may modify it). word_address is
               (uint64_t)-2 for unaligned ops, so they take the slow read too. (full span: the
               unaligned op is parked on the guard cell instead - see cold_jump_word_garbage) */
            if (!full_span && word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
""")
rep("""        f = cold_word;
        word_address = (uint64_t)-2; /* the jump word is read the slow way below */
        goto flip_word_ready;
""", """        f = cold_word;
        /* the jump word is read the slow way below: general mode fails the span check with -2;
           full-span mode has no span check, so park it one below the guard cell, whose sentinel
           routes the read to cold_jump_word_slow */
        word_address = full_span ? span_end - 1 : (uint64_t)-2;
        goto flip_word_ready;
""")
rep("""    cold_jump_word_garbage: /* w=64: possibly real data equal to the magic fill */
        if (flat_garbage_check(self, word_address + 1, &j) < 0) {
            goto memory_error;
        }
        goto jump_word_ready;
""", """    cold_jump_word_garbage: /* w=64: possibly real data equal to the magic fill */
        if (full_span && word_address + 1 >= span_end) {
            goto cold_jump_word_slow; /* the guard cell: an op in the last word, or a parked unaligned op */
        }
        if (flat_garbage_check(self, word_address + 1, &j) < 0) {
            goto memory_error;
        }
        goto jump_word_ready;
""")

# E8: dispatch
rep("""        case 64:
            /* w=64 words cannot fit a 4-byte cell; mem_decide_storage never selects it, and the
               dispatch does not offer it, so the impossible instantiation is never generated. */
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 64, 6, 0);
        case 32:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 32, 5, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 32, 5, 0);
        case 16:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 0);
        case 8:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 1)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 0);
        default:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, (uint64_t)self->w, (uint64_t)self->ww, 0);
""", """        case 64:
            /* w=64 words cannot fit a 4-byte cell; mem_decide_storage never selects it, and the
               dispatch does not offer it, so the impossible instantiation is never generated. */
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 64, 6, 0, 0);
        case 32:
            if (c32) {
                /* the span-check-free loop needs the full-span array AND a 32-bit start ip (every
                   later ip is a uint32 cell value; only the caller's start_ip could be wider) */
                return (self->flat_full_span && start_ip < (1ull << 32))
                    ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                         paused_seconds_out, 32, 5, 1, 1)
                    : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                         paused_seconds_out, 32, 5, 1, 0);
            }
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, 32, 5, 0, 0);
        case 16:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 1, 0)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 16, 4, 0, 0);
        case 8:
            return c32
                ? run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 1, 0)
                : run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                     paused_seconds_out, 8, 3, 0, 0);
        default:
            return run_flat_loop_impl(self, read_bit, write_bit, eof_exception_type, start_ip, ops_out,
                                      paused_seconds_out, (uint64_t)self->w, (uint64_t)self->ww, 0, 0);
""")
p.write_text(s, encoding="utf-8")
print("fold (a) written")
