"""Idea 12: DDA the wall top/bottom, exactly as the face path already does.

column_params_m runs two 6-row schoolbook multiplies (wt*scale) PER COLUMN; wt is per-seg
constant and scale steps linearly in the loop. low32(w*(s+k*d)) == low32(low32(w*s)+k*low32(w*d))
distributes mod 2^32 exactly (the Option-A face DDA proves the identity in-repo), so seed
prod=w*scale and step=w*scalestep per seg, add per column, and the per-column multiplies vanish."""
import pathlib
NL = chr(10)

# ---- projection.fj: the DDA twin, sharing the cpm_ latch/constants -------------------------
p = pathlib.Path("src/fj/projection.fj")
s = p.read_text(encoding="utf-8")
anchor = NL + "    // proj.point_on_side back,"
assert s.count(anchor) == 1
twin = NL.join([
"",
"    // idea 12: column_params_m with the two per-column multiplies replaced by the p2_prod DDA",
"    // accumulators frame_render seeds per seg and steps per column. Identical latch, identical",
"    // shift/sign-extend/clamp tail -- only where wt*scale comes from changed, and the identity",
"    // low32(w*(s+k*d)) == low32(low32(w*s)+k*low32(w*d)) is exact mod 2^32 (the Option-A face",
"    // DDA note proves the same identity).",
"    def column_params_dda top, bottom, centeryfix_c, viewh1 \\",
"            @ set_consts, consts_ready, tneg, tok, bok, bhi, end \\",
"            < cpm_c_centeryfix, cpm_c_viewh1, cpm_consts_set, p2_prodc, p2_prodf {",
"        hex.if0 1, cpm_consts_set, set_consts",
"        ;consts_ready",
"      set_consts:",
"        hex.set 8, cpm_c_centeryfix, centeryfix_c",
"        hex.set 8, cpm_c_viewh1, viewh1",
"        hex.set 1, cpm_consts_set, 1",
"      consts_ready:",
"        hex.mov 8, top, cpm_c_centeryfix",
"        hex.sub 8, top, p2_prodc                // topfrac = centeryfix - wt*scale (the DDA copy)",
"        hex.shr_hex 8, 4, top",
"        hex.sign_extend 8, 4, top",
"        hex.mov 8, bottom, cpm_c_centeryfix",
"        hex.sub 8, bottom, p2_prodf",
"        hex.shr_hex 8, 4, bottom",
"        hex.sign_extend 8, 4, bottom",
"        hex.sign 8, top, tneg, tok          // top = max(0, top)",
"      tneg:",
"        hex.zero 8, top",
"      tok:",
"        hex.scmp 8, bottom, cpm_c_viewh1, bok, bok, bhi   // bottom = min(VIEW_H-1, ...)",
"      bhi:",
"        hex.mov 8, bottom, cpm_c_viewh1",
"      bok:",
"        ;end",
"      end:",
"    }",
anchor])
s = s.replace(anchor, twin, 1)
p.write_text(s, encoding="utf-8")
print("projection: column_params_dda added")
