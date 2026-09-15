"""fold (d): the two finish tests (j == ip, j < 2w) become one branch; the cold block keeps the
old order (self-flip exemption, looping, null ip). Applies on top of fold (c)."""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/flipjump-151/flipjump/interpreter/_fjcore.c")
s = p.read_text(encoding="utf-8")


def rep(old, new, count=1):
    global s
    assert s.count(old) == count, (s.count(old), old[:90])
    s = s.replace(old, new)


# only the flat loop: split at its dispatcher
cut = s.index("static int run_flat_loop(")
head, tail = s[:cut], s[cut:]
s = head
rep("""        jump_word_ready:
            ops++;

            /* check finish? */
            if (j == ip) {
                goto cold_maybe_looping;
            }
        not_looping:
            if (j < dw) {
                cause = TERM_NULL_IP;
                goto done;
            }

            /* JUMP! */
            ip = j;
        } while (--inner_left);
""", """        jump_word_ready:
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
""")
rep("""    cold_maybe_looping:
        if (f >= ip && f - ip < dw) {
            goto not_looping; /* the op flips its own words - not a halt */
        }
        cause = TERM_LOOPING;
        goto done;
    }
""", """    cold_finish: /* j == ip (a halt, unless the op flips its own words) and/or j < 2w (null ip) */
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
""")
s = s + tail
p.write_text(s, encoding="utf-8")
print("fold (d) written")
