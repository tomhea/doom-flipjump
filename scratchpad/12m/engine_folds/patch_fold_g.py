"""fold (g): the tail's two branches (sentinel v|j, and finish j==ip|j<2w) become one; the cold
block keeps the old order (sentinels, then - the op now counted - looping, then null).
Applies on top of fold (f)."""
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
rep("""            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            /* ONE branch for the flip target's and the jump word's sentinel tests (fold b) */
            if (FLAT_IS_SENTINEL(flip_value) | FLAT_IS_SENTINEL(j)) {
                goto cold_flip_or_jump_sentinel;
            }
        jump_word_ready: /* the op counts from here on (fold e: done_counted) */

            /* check finish? ONE branch for "jumps to itself" and "null ip" (fold d); the cold
               block keeps the old order: the self-flip exemption, then looping, then null. */
            if ((j == ip) | (j < dw)) {
                goto cold_finish;
            }
        jump_go:
""", """            j = cell32 ? (uint64_t)flat32[word_address + 1] : flat64[word_address + 1];
            /* ONE branch for everything rare at the op's tail (folds b, d, g): the flip target's
               and the jump word's sentinel tests, the self-jump and the null ip. The cold block
               keeps the old order: sentinels first, then - the op counted from there on (fold e:
               done_counted) - looping, then null. */
            if (FLAT_IS_SENTINEL(flip_value) | FLAT_IS_SENTINEL(j) | (j == ip) | (j < dw)) {
                goto cold_tail;
            }
        jump_go:
""")
rep("""    cold_jump_word_slow_read:
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

    cold_finish: /* j == ip (a halt, unless the op flips its own words) and/or j < 2w (null ip) */
""", """    cold_jump_word_slow_read:
        if (mem_get_word_unaligned(self, ip + width, &cold_word) < 0) {
            goto memory_error;
        }
        j = cold_word;
        goto cold_finish;

    cold_tail: /* the flip target and/or the jump word read as the sentinel (w=64 / 4-byte cells:
                  possibly real data equal to the magic), and/or the op halts - in that order */
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
        /* falls through: from here the op counts (fold e) */
    cold_finish: /* j == ip (a halt, unless the op flips its own words) and/or j < 2w (null ip) */
""")
assert "goto jump_word_ready" not in s, "a jump_word_ready user survived"
s = s + tail
p.write_text(s, encoding="utf-8")
print("fold (g) written")
