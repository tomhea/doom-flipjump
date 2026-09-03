"""Idea 14: pack the V5 sfslot piece [y1][y2][cls][bpid] into two 16-bit cells.

Slot STRIDE stays 16 cells (only the first 8 used), so every stride computation -- the
SLOT_SHIFT shifts, the idea-11 seeds and the ptr_add 16 steps -- is untouched. Within-slot
offsets go from bytes to cells (PIECE_CELLS = 2), and the accessors move to the dual decoder
table's read_cell/write_cell (a whole pair per dereference)."""
import pathlib
NL = chr(10)

p = pathlib.Path("src/fj/frame_render.fj")
s = p.read_text(encoding="utf-8")

# ---- 0. the cell-offset constant, at file top ----------------------------------------------
old = s.split(NL, 1)[0]
s = (old + NL
     + NL
     + "// idea 14: a V5 sfslot piece is TWO 16-bit cells, [y2|y1][bpid|cls], via the dual decoder" + NL
     + "// table (PTR_WIDE_BITS=16). The slot stride stays 16 CELLS with only 8 used, so no index" + NL
     + "// math changed -- only within-slot offsets (cells, not bytes) and the accessors." + NL
     + "PIECE_CELLS = 2" + NL
     + s.split(NL, 1)[1])

# ---- 1. the writer -------------------------------------------------------------------------
old_wr = s[s.index("    def ts_piece_wr cnt, fbp, off, fy1, fy2, cls, bpid @ first_piece, end {"):]
old_wr = old_wr[:old_wr.index(NL + "    }") + len(NL + "    }")]
new_wr = NL.join([
"    def ts_piece_wr cnt, fbp, off, fy1, fy2, cls, bpid @ first_piece, pairv, end {",
"        hex.if0 1, cnt, first_piece",
"        hex.ptr_add fbp, off+PIECE_CELLS",
"        hex.mov 2, pairv, fy1",
"        hex.mov 2, pairv + 2*dw, fy2",
"        hex.write_cell_and_inc fbp, pairv        // [y2|y1] -- ONE dereference for both",
"        hex.mov 2, pairv, cls",
"        hex.mov PID_NIBBLES, pairv + 2*dw, bpid",
"        hex.write_cell_and_inc fbp, pairv        // [bpid|cls]",
"        hex.ptr_sub fbp, off+2*PIECE_CELLS",
"        ;end",
"      first_piece:",
"        hex.ptr_add fbp, off",
"        hex.mov 2, pairv, fy1",
"        hex.mov 2, pairv + 2*dw, fy2",
"        hex.write_cell_and_inc fbp, pairv",
"        hex.mov 2, pairv, cls",
"        hex.mov PID_NIBBLES, pairv + 2*dw, bpid",
"        hex.write_cell_and_inc fbp, pairv",
"        hex.ptr_sub fbp, off+PIECE_CELLS",
"        ;end",
"      pairv: hex.vec 4",
"      end:",
"    }"])
s = s.replace(old_wr, new_wr, 1)
print("writer packed")
p.write_text(s, encoding="utf-8")
