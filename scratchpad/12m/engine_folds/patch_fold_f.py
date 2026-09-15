"""fold (f), full-span only: the alignment test joins the head branch. The flip-word read is safe
for ANY 32-bit ip there (word_address < 2^27 whether aligned or not), so it is issued first and the
one head branch covers unaligned | sentinel | output | input; an unaligned ip's f is re-read the
slow way in the cold block, exactly as before. Applies on top of fold (e)."""
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
rep("""            /* read flip word */
            if (ip & bit_mask) {
                goto cold_unaligned_flip_word;
            }
            word_address = ip >> ww;
            if (!full_span && word_address + 1 >= flat_count) {
                goto cold_flip_word_out_of_span;
            }
            f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
            /* ONE branch for "f is the sentinel", "f is an output op" (f is dw or dw+1) and "ip is
               the input op" (in_lo_exclusive < ip <= in_addr) - folds b and c: all three are rare,
               and the cold block tells them apart in the old order - sentinel, output, input. The
               bitwise | keeps it one branch. */
            if (FLAT_IS_SENTINEL(f) | (f - dw <= 1) | (ip - in_lo_exclusive - 1 < dw)) {
                goto cold_flip_word;
            }
        after_input:
""", """            /* read flip word */
            word_address = ip >> ww;
            if (full_span) {
                /* the read is safe for ANY 32-bit ip (word_address < 2^27, aligned or not), so the
                   alignment test joins the head branch (fold f): ONE branch for "ip is unaligned",
                   "f is the sentinel", "f is an output op" (f is dw or dw+1) and "ip is the input
                   op" (in_lo_exclusive < ip <= in_addr) - all rare; the cold block tells them apart
                   in the old order (an unaligned ip's f is re-read the slow way first). The bitwise
                   | keeps it one branch. */
                f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
                if ((ip & bit_mask) | FLAT_IS_SENTINEL(f) | (f - dw <= 1) | (ip - in_lo_exclusive - 1 < dw)) {
                    goto cold_head;
                }
            } else {
                if (ip & bit_mask) {
                    goto cold_unaligned_flip_word;
                }
                if (word_address + 1 >= flat_count) {
                    goto cold_flip_word_out_of_span;
                }
                f = cell32 ? (uint64_t)flat32[word_address] : flat64[word_address];
                /* ONE branch for "f is the sentinel", "f is an output op" and "ip is the input op"
                   (folds b, c); the cold block keeps the old order - sentinel, output, input */
                if (FLAT_IS_SENTINEL(f) | (f - dw <= 1) | (ip - in_lo_exclusive - 1 < dw)) {
                    goto cold_flip_word;
                }
            }
        after_input:
""")
rep("""    cold_flip_word: /* f is the sentinel (w=64 / 4-byte cells: possibly real data equal to the
                       magic fill), or an output op - in that order, as the hot path once tested */
""", """    cold_head: /* full span: an unaligned ip, or one of cold_flip_word's cases */
        if (ip & bit_mask) {
            goto cold_unaligned_flip_word;
        }
    cold_flip_word: /* f is the sentinel (w=64 / 4-byte cells: possibly real data equal to the
                       magic fill), or an output op - in that order, as the hot path once tested */
""")
s = s + tail
p.write_text(s, encoding="utf-8")
print("fold (f) written")
