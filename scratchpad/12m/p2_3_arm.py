"""P2-3 probe: what is the pointer ARM worth, and what would a NARROW arm be worth?

Every dereference in the program pays

    hex.pointers.set_flip_and_jump_pointers ptr =
        address_and_variable_triple_xor w/4, to_flip, to_jump+w, to_ptr_var, to_ptr_var   // CLEAR
        address_and_variable_triple_xor w/4, to_flip, to_jump+w, to_ptr_var, ptr          // SET

-- two passes over all EIGHT hexes of an address, to move three address fields from the old
pointer to the new one. The atlas says that is 2,021,051 ops on the median frame, 10.2% of the
whole program and 69% of everything dereferences cost.

But consecutive arms usually move the pointer only a little: the four `write_byte_and_inc` of
ts_piece_wr walk four consecutive cells, so the address changes only in its low nibbles. A pass
over n hexes instead of eight is exact whenever the old and new addresses AGREE above nibble n --
which for a run inside an aligned block is a property the emitter controls.

This measures the prize: the full arm, narrowed arms at several widths, and a read through each,
checking the byte read back is the same.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from micro import compare, show                                        # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FILES = [ROOT / "src/fj/fixed_point.fj"]

PRELUDE = """
ns arm {
    // the stl arm, inlined
    def full ptr < hex.pointers.to_flip, hex.pointers.to_jump, hex.pointers.to_ptr_var {
        hex.address_and_variable_triple_xor w/4, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, hex.pointers.to_ptr_var
        hex.address_and_variable_triple_xor w/4, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, ptr
    }
    // the same, but only over the low n hexes: exact iff old and new agree above nibble n
    def narrow n, ptr < hex.pointers.to_flip, hex.pointers.to_jump, hex.pointers.to_ptr_var {
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, hex.pointers.to_ptr_var
        hex.address_and_variable_triple_xor n, hex.pointers.to_flip, hex.pointers.to_jump+w, hex.pointers.to_ptr_var, ptr
    }
    def n2 ptr {
        .narrow 2, ptr
    }
    def n3 ptr {
        .narrow 3, ptr
    }
    def n4 ptr {
        .narrow 4, ptr
    }
    def n5 ptr {
        .narrow 5, ptr
    }
    // a whole read, so the arm can be priced against what it enables
    def read_full dst, ptr < hex.pointers.read_byte {
        hex.zero 2, dst
        .full ptr
        hex.pointers.read_byte_from_inners_ptrs
        hex.xor 2, dst, hex.pointers.read_byte
        hex.zero 2, hex.pointers.read_byte
    }
    def read_n3 dst, ptr < hex.pointers.read_byte {
        hex.zero 2, dst
        .n3 ptr
        hex.pointers.read_byte_from_inners_ptrs
        hex.xor 2, dst, hex.pointers.read_byte
        hex.zero 2, hex.pointers.read_byte
    }
}
"""

DATA = ["tbl:", "  hex.vec 2, 0x11", "  hex.vec 2, 0x22", "  hex.vec 2, 0x33",
        "  hex.vec 2, 0x44",
        "p0: hex.vec 8, 0", "p1: hex.vec 8, 0", "dst: hex.vec 8"]
SETUP = ["hex.set w/4, p0, tbl", "hex.set w/4, p1, tbl+2*dw"]

print("=== P2-3 probe: the pointer arm ===")
print("")
print("COST of the arm alone, and of a whole read through it")
show(["arm.full p0"], DATA, PRELUDE, files=FILES, label="the stl arm (w/4 = 8 hexes)")
for n in (5, 4, 3, 2):
    show(["arm.n%d p0" % n], DATA, PRELUDE, files=FILES, label="  a %d-hex arm" % n)
show(["arm.read_full dst, p0"], DATA, PRELUDE, files=FILES, label="a whole hex.read_byte")
print("")
print("VALUE CHECK -- two pointers into the same aligned block, armed alternately.")
print("A 3-hex arm must read the same bytes as the full arm, because the two addresses")
print("agree above nibble 3.")
rows = compare([("full arm", SETUP + ["arm.read_full dst, p0", "hex.print_as_digit 2, dst, 1",
                                      "arm.read_full dst, p1", "hex.print_as_digit 2, dst, 1",
                                      "arm.read_full dst, p0", "hex.print_as_digit 2, dst, 1"]),
                ("3-hex arm", SETUP + ["arm.read_full dst, p0", "hex.print_as_digit 2, dst, 1",
                                       "arm.read_n3 dst, p1", "hex.print_as_digit 2, dst, 1",
                                       "arm.read_n3 dst, p0", "hex.print_as_digit 2, dst, 1"])],
               data=DATA, prelude=PRELUDE, files=FILES, quiet=True, printer=[])
print("  full arm reads : %s" % rows[0][3])
print("  3-hex arm reads: %s" % rows[1][3])
print("  %s" % ("ok -- identical" if rows[0][3] == rows[1][3] else "!! DIFFER"))
