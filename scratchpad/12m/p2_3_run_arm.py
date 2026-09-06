"""P2-3: a full arm on entry to a pointer RUN, narrow arms for the rest of it.

The piece loaders (frame.lines_steps_load2, frame.lines_spr_load) read 3-4 consecutive bytes off
one walking pointer with frame.read0_byte_and_inc:

    def read0_byte_and_inc dst, ptr {
        hex.xor_byte_from_ptr dst, ptr      // = set_flip_and_jump_pointers + the read dance + xor
        hex.ptr_inc ptr
    }

Every one of those reads pays a FULL 8-hex arm (192.0 executed ops), even though after the first
read the armed address is already inside the same table and the next one is only a cell away.

This measures the alternative -- full arm first, 5-hex arms after -- and checks the bytes read
back are identical. The value check runs the WHOLE RUN, because the thing that could break is
precisely the state the previous read left behind.

The safety argument is being attacked in parallel by three adversarial reviewers; this file only
establishes what it is worth if it survives.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, show                                        # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]

PRELUDE = """
ns rd {
    // exactly frame.read0_byte_and_inc: the stl arm, the read dance, the xor, the increment
    def full dst, ptr < hex.pointers.read_byte {
        hex.pointers.set_flip_and_jump_pointers ptr
        hex.pointers.read_byte_from_inners_ptrs
        hex.xor 2, dst, hex.pointers.read_byte
        hex.ptr_inc ptr
    }
    // the same with the arm narrowed to n hexes -- exact only when the previously armed address
    // agrees with this one in every nibble at or above n
    def narrow n, dst, ptr < hex.pointers.to_flip, hex.pointers.to_jump, hex.pointers.to_ptr_var, hex.pointers.read_byte {
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, hex.pointers.to_ptr_var
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, ptr
        hex.pointers.read_byte_from_inners_ptrs
        hex.xor 2, dst, hex.pointers.read_byte
        hex.ptr_inc ptr
    }
    def n5 dst, ptr {
        .narrow 5, dst, ptr
    }
    def n6 dst, ptr {
        .narrow 6, dst, ptr
    }
    // ptr_inc is hex.add_constant w/4, ptr, dw -- it never touches the arm (checked in the stl),
    // and it rides the SAME window proof: while the walk stays inside one 16^5 window a carry
    // out of nibble 4 is impossible, so a 5-nibble add is exact.
    def narrow_inc n, dst, ptr < hex.pointers.to_flip, hex.pointers.to_jump, hex.pointers.to_ptr_var, hex.pointers.read_byte {
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, hex.pointers.to_ptr_var
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, ptr
        hex.pointers.read_byte_from_inners_ptrs
        hex.xor 2, dst, hex.pointers.read_byte
        hex.add_constant n, ptr, dw
    }
    def n5i dst, ptr {
        .narrow_inc 5, dst, ptr
    }
}
"""

# a four-cell piece, the shape the loaders read: [y1][y2][cls][bpid]
DATA = ["piece:", "  hex.vec 2, 0x3B", "  hex.vec 2, 0x5C", "  hex.vec 2, 0x07", "  hex.vec 2, 0xA1",
        "other:", "  hex.vec 2, 0xFF",
        "pp: hex.vec 8, 0", "d0: hex.vec 2", "d1: hex.vec 2", "d2: hex.vec 2", "d3: hex.vec 2"]

SETUP = ["hex.set w/4, pp, piece",
         "hex.zero 2, d0", "hex.zero 2, d1", "hex.zero 2, d2", "hex.zero 2, d3"]
PRINT = ["hex.print_as_digit 2, d0, 1", "hex.print_as_digit 2, d1, 1",
         "hex.print_as_digit 2, d2, 1", "hex.print_as_digit 2, d3, 1"]

RESET = ["hex.set w/4, pp, piece"]   # the pointer WALKS; without this it leaves the data and the
                                     # program halts early, which shows up as a zero slope
RUN_FULL = RESET + ["rd.full d0, pp", "rd.full d1, pp", "rd.full d2, pp", "rd.full d3, pp"]
RUN_N5 = RESET + ["rd.full d0, pp", "rd.n5 d1, pp", "rd.n5 d2, pp", "rd.n5 d3, pp"]
RUN_N6 = RESET + ["rd.full d0, pp", "rd.n6 d1, pp", "rd.n6 d2, pp", "rd.n6 d3, pp"]
RUN_N5I = RESET + ["rd.full d0, pp", "rd.n5i d1, pp", "rd.n5i d2, pp", "rd.n5i d3, pp"]

print("=== P2-3  full arm on entry, narrow arms through the run ===")
print("")
print("VALUE CHECK -- the whole 4-byte run. The three variants must agree with each other;")
print("the absolute digits depend on the cell layout and are not the point.")
rows = compare([("all full arms", SETUP + RUN_FULL),
                ("full + 3x 5-hex", SETUP + RUN_N5),
                ("full + 3x 6-hex", SETUP + RUN_N6),
                ("5-hex arm + 5-nib inc", SETUP + RUN_N5I)],
               data=DATA, prelude=PRELUDE, files=FILES, quiet=True, printer=PRINT)
base = rows[0][3]
for name, _ex, _sp, digits in rows:
    print("  %-20s reads %s   %s" % (name, digits, "ok" if digits == base else "!! DIFFER"))
print("")
ok = all(r[3] == base for r in rows)
print("value check: %s" % ("all variants read the same four bytes" if ok else "!! A VARIANT DIFFERS"))
print("")
print("COST of one 4-read run")
compare([("all full arms", RUN_FULL), ("full + 3x 5-hex", RUN_N5),
         ("full + 3x 6-hex", RUN_N6), ("5-hex arm + 5-nib inc", RUN_N5I)],
        data=DATA, prelude=PRELUDE, files=FILES)
print("")
print("COST of one read, for reference")
show(RESET + ["rd.full d0, pp"], DATA, PRELUDE, files=FILES, label="read0_byte_and_inc (full arm)")
show(RESET + ["rd.n5 d0, pp"], DATA, PRELUDE, files=FILES, label="  with a 5-hex arm")
