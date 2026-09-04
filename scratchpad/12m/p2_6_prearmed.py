"""P2-6: a write whose arm is entirely redundant, because the read before it already aimed there.

Three macros share this shape:

    col_body / (the macro's entry):
        hex.read_byte pval8, pptr        <- ARMS pptr, and the read dance restores to_flip
        hex.if0 PID_NIBBLES, pval8, claim
        hex.ptr_add pptr, PID_BYTES      <- only the NOT-claim path moves the pointer
        ;col_next
      claim:
        hex.write_byte[_and_inc] pptr, seg_pid   <- pptr UNMOVED: the arm still points here

`claim:` / `own:` is reachable ONLY from that if0 (checked: one jump each, and the two `own`s are
locals of two different macros), so on entry the three address fields still hold exactly the
address the read armed. The write's `set_flip_and_jump_pointers` is therefore a CLEAR followed by
a SET of the identical value -- 192.0 executed ops that change nothing.

Note this precondition is far weaker than P2-3's: prearming does not care WHERE the pointer points,
only that the arm already points there. It is safe at all three sites regardless of address cluster.

Live at: frame.seg_pass1_leaf_body_ts (claim), frame.lines_col_plane_ids (own),
frame.lines_col_plane (own).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, price                                       # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]
NL = chr(10)


def prelude(fill):
    body = [
        "ns pa {",
        "    def write_byte_prearmed src @ end < hex.pointers.read_byte {",
        "        hex.pointers.read_byte_from_inners_ptrs",
        "        hex.xor 2, hex.pointers.read_byte, src",
        "        hex.pointers.xor_byte_to_flip_ptr hex.pointers.read_byte",
    ]
    if fill:
        body += ["        ;end", "        rep(%d, i) stl.fj 0, 0" % fill]
    body += [
        "      end:",
        "    }",
        "    def normal dst, ptr, src {",
        "        hex.read_byte dst, ptr",
        "        hex.write_byte ptr, src",
        "    }",
        "    def prearmed dst, ptr, src {",
        "        hex.read_byte dst, ptr",
        "        .write_byte_prearmed src",
        "    }",
        "}",
    ]
    return NL.join(body)


DATA = ["cell:", "  ;0 * dw", "  ;0 * dw",
        "pp: hex.vec 8, 0", "got: hex.vec 2", "back: hex.vec 2", "val: hex.vec 2, 0x6D"]
SETUP = ["hex.set w/4, pp, cell"]
PRINT = ["hex.print_as_digit 2, got, 1", "hex.print_as_digit 2, back, 1"]

# write, then read the cell BACK -- the only way to prove the byte landed at the right address
SEQ_NORMAL = SETUP + ["pa.normal got, pp, val", "hex.read_byte back, pp"]
SEQ_PREARM = SETUP + ["pa.prearmed got, pp, val", "hex.read_byte back, pp"]

print("=== P2-6  the prearmed write ===")
print("")
print("VALUE CHECK -- write 0x6D through each form, then read the cell back.")
print("The second digit pair is what actually landed in memory.")
rows = compare([("normal write", SEQ_NORMAL), ("prearmed write", SEQ_PREARM)],
               data=DATA, prelude=prelude(0), files=FILES, quiet=True, printer=PRINT)
for name, _e, _s, digits in rows:
    print("  %-18s read-before=%s  cell-after=%s" % (name, digits[:2], digits[2:4]))
same = rows[0][3] == rows[1][3]
landed = rows[1][3][2:4].upper() == "6D"
print("")
print("  identical to the normal write: %s" % ("yes" if same else "!! NO"))
print("  the byte actually landed:      %s" % ("yes, 0x6D" if landed else "!! NO -- wrote elsewhere"))
print("")
print("COST and the freeze filler")
_e, wide = price(SETUP + ["pa.normal got, pp, val"], DATA, prelude(0), files=FILES)
_e2, bare = price(SETUP + ["pa.prearmed got, pp, val"], DATA, prelude(0), files=FILES)
fill = wide - bare - 1
ex_n, sp_n = price(SETUP + ["pa.normal got, pp, val"], DATA, prelude(fill), files=FILES)
ex_p, sp_p = price(SETUP + ["pa.prearmed got, pp, val"], DATA, prelude(fill), files=FILES)
print("  read+write, normal   : %8.1f executed   %6d space" % (ex_n, sp_n))
print("  read+write, prearmed : %8.1f executed   %6d space   (filler %d)" % (ex_p, sp_p, fill))
print("  delta                : %+8.1f executed   %+6d space   %s"
      % (ex_p - ex_n, sp_p - sp_n, "SIZE-IDENTICAL" if sp_p == sp_n else "!! OFF"))
