"""fold (b): the three per-op sentinel (garbage) tests become two branches shared with tests that
already exist -- f's joins the output test; the flip target's and the jump word's share one branch
placed after the jump-word read (the flip target's test is deferred past its store; the cold block
undoes the store when the target was real garbage, so memory and the reported error are identical).
Applies on top of fold (a)."""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


# 1. the helper + the sentinel macro, before the impl's comment block
rep("""#define CAUSE_PYTHON_ERROR (-2)
""", """#define CAUSE_PYTHON_ERROR (-2)

/* is a flat cell value the width's garbage sentinel? cell32/width are literals in the run loops,
   so this folds to one compare per instantiation. */
#define FLAT_IS_SENTINEL(x) \\
    (cell32 ? ((x) == (uint64_t)FLAT_GARBAGE_MAGIC32) \\
            : (width <= 32 ? (((x) & GARBAGE_SENTINEL) != 0) : ((x) == FLAT_GARBAGE_MAGIC)))

/* fold (b): the flip target's sentinel test is DEFERRED past its store, so that it shares one
   branch with the jump word's test. When the deferred test fires, the cell was already flipped:
   if it was real garbage (an out-of-segment touch) the store is undone here -- memory is then
   exactly what an undeferred check would have left -- and the error is reported at the flip's
   address, as before; if it was an in-segment word that merely holds the magic value, the flip
   stands, as before. `flip_value` is the value the cell held BEFORE the flip. */
static FJ_ALWAYS_INLINE int flat_deferred_flip_garbage(MemoryObject* m, uint64_t flip_word_address,
                                                       uint64_t flip_value, const int cell32)
{
    if (flat_garbage_check(m, flip_word_address, &flip_value) < 0) {
        if (cell32) {
            ((uint32_t*)m->flat)[flip_word_address] = (uint32_t)flip_value;
        } else {
            ((uint64_t*)m->flat)[flip_word_address] = flip_value;
        }
        return -1;
    }
    return 0;
}
""")

# 2. the hot path
rep("""            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
            if (cell32 ? (f == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((f & GARBAGE_SENTINEL) != 0)
                                      : (f == FLAT_GARBAGE_MAGIC))) {
                goto cold_flip_word_garbage;
            }
        flip_word_ready:

            /* IO - one unsigned compare each: output when f is dw or dw+1;
               input when in_lo_exclusive < ip <= in_addr */
            if (f - dw <= 1) {
                goto cold_output;
            }
        after_output:
            if (ip - in_lo_exclusive - 1 < dw) {
                goto cold_input;
            }
        after_input:

            /* FLIP! */
            flip_word_address = f >> ww;
            if (!full_span && flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }
            flip_value = cell32 ? (uint64_t)flat32[flip_word_address]
                                : flat64[flip_word_address];
            if (cell32 ? (flip_value == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((flip_value & GARBAGE_SENTINEL) != 0)
                                      : (flip_value == FLAT_GARBAGE_MAGIC))) {
                goto cold_flip_garbage;
            }
        flip_value_ready:
            {
                const uint64_t flipped = flip_value ^ (1ull << (f & bit_mask));
                if (cell32) {
                    flat32[flip_word_address] = (uint32_t)flipped;
                } else {
                    flat64[flip_word_address] = flipped;
                }
            }
        after_flip:

            /* read jump word (after the flip - the flip may modify it). word_address is
               (uint64_t)-2 for unaligned ops, so they take the slow read too. (full span: the
               unaligned op is parked on the guard cell instead - see cold_jump_word_garbage) */
            if (!full_span && word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            if (cell32 ? (j == (uint64_t)FLAT_GARBAGE_MAGIC32)
                       : (width <= 32 ? ((j & GARBAGE_SENTINEL) != 0)
                                      : (j == FLAT_GARBAGE_MAGIC))) {
                goto cold_jump_word_garbage;
            }
        jump_word_ready:
""", """            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
            /* ONE branch for "f is the sentinel" and "f is an output op" (fold b): both rare, and
               the cold block tells them apart in the old order - sentinel first, then output
               (which a sentinel-valued f can never be). The bitwise | keeps it one branch. */
            if (FLAT_IS_SENTINEL(f) | (f - dw <= 1)) {
                goto cold_flip_word;
            }
        after_output:
            /* input when in_lo_exclusive < ip <= in_addr - one unsigned compare */
            if (ip - in_lo_exclusive - 1 < dw) {
                goto cold_input;
            }
        after_input:

            /* FLIP! the target's sentinel test is DEFERRED past the store to share the jump
               word's branch below (fold b): see flat_deferred_flip_garbage for the undo. */
            flip_word_address = f >> ww;
            if (!full_span && flip_word_address >= flat_count) {
                goto cold_flip_out_of_span;
            }
            flip_value = cell32 ? (uint64_t)flat32[flip_word_address]
                                : flat64[flip_word_address];
            {
                const uint64_t flipped = flip_value ^ (1ull << (f & bit_mask));
                if (cell32) {
                    flat32[flip_word_address] = (uint32_t)flipped;
                } else {
                    flat64[flip_word_address] = flipped;
                }
            }
        after_flip:

            /* read jump word (after the flip - the flip may modify it). word_address is
               (uint64_t)-2 for unaligned ops, so they take the slow read too. (full span: the
               unaligned op is parked on the guard cell instead - see cold_flip_or_jump_sentinel) */
            if (!full_span && word_address + 1 >= flat_count) {
                goto cold_jump_word_slow;
            }
            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            /* ONE branch for the flip target's and the jump word's sentinel tests (fold b) */
            if (FLAT_IS_SENTINEL(flip_value) | FLAT_IS_SENTINEL(j)) {
                goto cold_flip_or_jump_sentinel;
            }
        jump_word_ready:
""")

# 3. the cold blocks
rep("""    cold_unaligned_flip_word:
        if (mem_get_word_unaligned(self, ip, &cold_word) < 0) {
            goto memory_error;
        }
        f = cold_word;
        /* the jump word is read the slow way below: general mode fails the span check with -2;
           full-span mode has no span check, so park it one below the guard cell, whose sentinel
           routes the read to cold_jump_word_slow */
        word_address = full_span ? span_end - 1 : (uint64_t)-2;
        goto flip_word_ready;

    cold_flip_word_out_of_span:
        /* the op's words reach past the flat window: read per word through the routing
           helper (hybrid: page-backed far code; pure flat: the paged access checks
           report the out-of-segment error) */
        if (mem_read_word(self, word_address, &cold_word) < 0) {
            goto memory_error;
        }
        f = cold_word;
        goto flip_word_ready;

    cold_flip_word_garbage: /* w=64: possibly real data equal to the magic fill */
        if (flat_garbage_check(self, word_address, &f) < 0) {
            goto memory_error;
        }
        goto flip_word_ready;

    cold_output:
    {
        /* time the output callback as paused, exactly like the input callback below - so the
           reported run-time is net fj-compute, excluding the cost of the IO device's writes */
        double io_start = monotonic_seconds();
        PyObject* result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);
        *paused_seconds_out += monotonic_seconds() - io_start;
        if (!result) {
            goto done;
        }
        Py_DECREF(result);
        goto after_output;
    }
""", """    cold_unaligned_flip_word:
        if (mem_get_word_unaligned(self, ip, &cold_word) < 0) {
            goto memory_error;
        }
        f = cold_word;
        /* the jump word is read the slow way below: general mode fails the span check with -2;
           full-span mode has no span check, so park it one below the guard cell, whose sentinel
           routes the read to cold_jump_word_slow */
        word_address = full_span ? span_end - 1 : (uint64_t)-2;
        goto cold_flip_word_resolved; /* the slow read resolved sentinels itself */

    cold_flip_word_out_of_span:
        /* the op's words reach past the flat window: read per word through the routing
           helper (hybrid: page-backed far code; pure flat: the paged access checks
           report the out-of-segment error) */
        if (mem_read_word(self, word_address, &cold_word) < 0) {
            goto memory_error;
        }
        f = cold_word;
        goto cold_flip_word_resolved;

    cold_flip_word: /* f is the sentinel (w=64 / 4-byte cells: possibly real data equal to the
                       magic fill), or an output op - in that order, as the hot path once tested */
        if (FLAT_IS_SENTINEL(f) && flat_garbage_check(self, word_address, &f) < 0) {
            goto memory_error;
        }
    cold_flip_word_resolved:
        if (f - dw <= 1) {
            /* output. time the callback as paused, exactly like the input callback below - so
               the reported run-time is net fj-compute, excluding the IO device's writes */
            double io_start = monotonic_seconds();
            PyObject* result = PyObject_CallFunctionObjArgs(write_bit, (f == dw + 1) ? Py_True : Py_False, NULL);
            *paused_seconds_out += monotonic_seconds() - io_start;
            if (!result) {
                goto done;
            }
            Py_DECREF(result);
        }
        goto after_output;
""")

rep("""    cold_flip_out_of_span:
        /* a flip above the flat window: the routing helper flips page-backed far data
           (hybrid - e.g. sieve's table) or reports the out-of-segment error */
        if (mem_flip_bit(self, f) < 0) {
            goto memory_error;
        }
        goto after_flip;

    cold_flip_garbage: /* w=64: possibly real data equal to the magic fill */
        if (flat_garbage_check(self, flip_word_address, &flip_value) < 0) {
            goto memory_error;
        }
        goto flip_value_ready;

    cold_jump_word_slow:
        if (mem_get_word_unaligned(self, ip + width, &cold_word) < 0) {
            goto memory_error;
        }
        j = cold_word;
        goto jump_word_ready;

    cold_jump_word_garbage: /* w=64: possibly real data equal to the magic fill */
        if (full_span && word_address + 1 >= span_end) {
            goto cold_jump_word_slow; /* the guard cell: an op in the last word, or a parked unaligned op */
        }
        if (flat_garbage_check(self, word_address + 1, &j) < 0) {
            goto memory_error;
        }
        goto jump_word_ready;
""", """    cold_flip_out_of_span:
        /* a flip above the flat window: the routing helper flips page-backed far data
           (hybrid - e.g. sieve's table) or reports the out-of-segment error */
        if (mem_flip_bit(self, f) < 0) {
            goto memory_error;
        }
        flip_value = 0; /* checked by the helper: keep the deferred sentinel test quiet */
        goto after_flip;

    cold_jump_word_slow:
        /* the deferred flip-target test comes first (in the hot path it shares the jump word's
           branch, which this path bypasses): a garbage target errors before the jump word is
           read, in the old order */
        if (FLAT_IS_SENTINEL(flip_value) &&
            flat_deferred_flip_garbage(self, flip_word_address, flip_value, cell32) < 0) {
            goto memory_error;
        }
    cold_jump_word_slow_read:
        if (mem_get_word_unaligned(self, ip + width, &cold_word) < 0) {
            goto memory_error;
        }
        j = cold_word;
        goto jump_word_ready;

    cold_flip_or_jump_sentinel: /* the flip target and/or the jump word read as the sentinel
                                   (w=64 / 4-byte cells: possibly real data equal to the magic) */
        if (FLAT_IS_SENTINEL(flip_value) &&
            flat_deferred_flip_garbage(self, flip_word_address, flip_value, cell32) < 0) {
            goto memory_error;
        }
        if (FLAT_IS_SENTINEL(j)) {
            if (full_span && word_address + 1 >= span_end) {
                goto cold_jump_word_slow_read; /* the guard cell: an op in the last word, or a parked unaligned op */
            }
            if (flat_garbage_check(self, word_address + 1, &j) < 0) {
                goto memory_error;
            }
        }
        goto jump_word_ready;
""")

# 4. undef the macro after the flat loop's dispatcher (the paged loop does not use it)
rep("""/* the generic run loop - the paged path (plus the rare flat-with-last-ops-ring debug
""", """#undef FLAT_IS_SENTINEL

/* the generic run loop - the paged path (plus the rare flat-with-last-ops-ring debug
""")

p.write_text(s, encoding="utf-8")
print("fold (b) written")
