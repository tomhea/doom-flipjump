"""fold (e): strip-mine the per-op ops++ -- the strip counter (inner_left) already counts, so the
op count is derived from it at the strip's end and at the exits. Applies on top of fold (d)."""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


cut = s.index("static int run_flat_loop(")
head, tail = s[:cut], s[cut:]
s = head
rep("""    self->mem_error = 0;
    for (;;) {
        /* the signal check is strip-mined out of the per-op path: the inner do-while
           runs SIGNAL_CHECK_MASK+1 ops on a fused dec-jnz back-edge, the outer loop
           checks signals - same cadence as a per-op (ops & MASK) == MASK test. */
        self->last_run_op_count = ops;
        if (PyErr_CheckSignals() < 0) {
            goto done;
        }
        inner_left = SIGNAL_CHECK_MASK + 1;
        do {
""", """    self->mem_error = 0;
    inner_left = SIGNAL_CHECK_MASK + 1;
    for (;;) {
        /* the signal check is strip-mined out of the per-op path: the inner do-while
           runs SIGNAL_CHECK_MASK+1 ops on a fused dec-jnz back-edge, the outer loop
           checks signals - same cadence as a per-op (ops & MASK) == MASK test.
           THE OP COUNT IS STRIP-MINED THE SAME WAY (fold e): `ops` holds the count at the strip's
           start; the strip's own count is (SIGNAL_CHECK_MASK + 1) - inner_left, added when the
           strip completes and at `done` - plus one at `done_counted`, for an op that halts after
           its jump word was read, the point where the per-op ops++ used to sit. */
        self->last_run_op_count = ops;
        if (PyErr_CheckSignals() < 0) {
            goto done; /* inner_left is whole here: `done` adds nothing */
        }
        do {
""")
rep("""        jump_word_ready:
            ops++;

            /* check finish? ONE branch for "jumps to itself" and "null ip" (fold d); the cold
               block keeps the old order: the self-flip exemption, then looping, then null. */
            if ((j == ip) | (j < dw)) {
                goto cold_finish;
            }
        jump_go:
            /* JUMP! */
            ip = j;
        } while (--inner_left);
        continue;
""", """        jump_word_ready: /* the op counts from here on (fold e: done_counted) */

            /* check finish? ONE branch for "jumps to itself" and "null ip" (fold d); the cold
               block keeps the old order: the self-flip exemption, then looping, then null. */
            if ((j == ip) | (j < dw)) {
                goto cold_finish;
            }
        jump_go:
            /* JUMP! */
            ip = j;
        } while (--inner_left);
        ops += SIGNAL_CHECK_MASK + 1;
        inner_left = SIGNAL_CHECK_MASK + 1;
        continue;
""")
rep("""    cold_finish: /* j == ip (a halt, unless the op flips its own words) and/or j < 2w (null ip) */
        if (j == ip && !(f >= ip && f - ip < dw)) {
            cause = TERM_LOOPING;
            goto done;
        }
        if (j < dw) {
            cause = TERM_NULL_IP;
            goto done;
        }
        goto jump_go;
    }

memory_error:
    if (self->mem_error) {
        self->mem_error = 0;
        cause = TERM_MEMORY_ERROR;
    }
done:
    self->last_run_op_count = ops;
""", """    cold_finish: /* j == ip (a halt, unless the op flips its own words) and/or j < 2w (null ip) */
        if (j == ip && !(f >= ip && f - ip < dw)) {
            cause = TERM_LOOPING;
            goto done_counted;
        }
        if (j < dw) {
            cause = TERM_NULL_IP;
            goto done_counted;
        }
        goto jump_go;
    }

memory_error:
    if (self->mem_error) {
        self->mem_error = 0;
        cause = TERM_MEMORY_ERROR;
    }
    goto done;
done_counted: /* the halting op had read its jump word: it counts, as the per-op ops++ counted it */
    ops += 1;
done:
    ops += (SIGNAL_CHECK_MASK + 1) - inner_left; /* the ops this strip completed before the exit */
    self->last_run_op_count = ops;
""")
s = s + tail
p.write_text(s, encoding="utf-8")
print("fold (e) written")
