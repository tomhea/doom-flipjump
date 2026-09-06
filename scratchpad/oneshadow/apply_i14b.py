"""Idea 14 part 2: the clamp readers and the call-site offsets."""
import pathlib
NL = chr(10)
p = pathlib.Path("src/fj/frame_render.fj")
s = p.read_text(encoding="utf-8")

# ---- clamp2: prev y2 is the HIGH half of the [y2|y1] cell ---------------------------------
old = NL.join([
"    def ts_clamp2 fra, cnt, fbp, off @ doclamp, noprev, prev_y, prev_end, end {",
"        hex.if0 1, cnt, noprev",
"        hex.ptr_add fbp, off+1",
"        hex.read_byte prev_y, fbp",
"        hex.ptr_sub fbp, off+1",
"        hex.zero 8, prev_end",
"        hex.mov 2, prev_end, prev_y",])
new = NL.join([
"    def ts_clamp2 fra, cnt, fbp, off @ doclamp, noprev, pairv, prev_end, end {",
"        hex.if0 1, cnt, noprev",
"        hex.ptr_add fbp, off",
"        hex.read_cell pairv, fbp                 // [y2|y1] -- prev y2 is the HIGH half",
"        hex.ptr_sub fbp, off",
"        hex.zero 8, prev_end",
"        hex.mov 2, prev_end, pairv + 2*dw",])
assert s.count(old) == 1
s = s.replace(old, new)
old = "      prev_y: hex.vec 2" + NL + "      prev_end: hex.vec 8"
assert s.count(old) >= 1
s = s.replace(old, "      pairv: hex.vec 4" + NL + "      prev_end: hex.vec 8", 1)
print("clamp2 packed")
p.write_text(s, encoding="utf-8")
