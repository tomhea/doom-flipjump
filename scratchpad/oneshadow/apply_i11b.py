"""Idea 11 part 2: rewrite the two loaders over the shared pointers."""
import pathlib
NL = chr(10)
BS = chr(92)

p = pathlib.Path("src/fj/frame_render.fj")
s = p.read_text(encoding="utf-8")

old = ("        hex.set w/4, sfflag_b, sfflag" + NL
       + "        hex.ptr_index sfflag_p, sfflag_b, x" + NL
       + "        hex.read_byte flags_v, sfflag_p" + NL)
new = "        hex.read_byte flags_v, p2_sffp           // idea 11: seeded per seg, stepped at skipcol" + NL
assert s.count(old) == 1
s = s.replace(old, new)

old = ("        hex.zero w/4, slot_idx" + NL
       + "        hex.mov 2, slot_idx, x" + NL
       + "        hex.shl_hex w/4, SLOT_SHIFT, slot_idx" + NL
       + "        hex.set w/4, sfslot_b, sfslot" + NL
       + "        hex.ptr_index sfslot_p, sfslot_b, slot_idx" + NL)
new = "        hex.mov w/4, sfslot_p, p2_sfsp           // idea 11: working copy -- the and_incs mutate it" + NL
assert s.count(old) == 1
s = s.replace(old, new)

old = ("    def lines_steps_load2 x " + BS + NL
       + "            @ up_one, up_none, lo_read, lo_one, sfflag_b, sfflag_p, sfslot_b, sfslot_p, slot_idx, flags_v, end " + BS + NL
       + "            < sfflag, sfslot, ucnt,")
new = ("    def lines_steps_load2 " + BS + NL
       + "            @ up_one, up_none, lo_read, lo_one, sfslot_p, flags_v, end " + BS + NL
       + "            < p2_sffp, p2_sfsp, ucnt,")
assert s.count(old) == 1
s = s.replace(old, new)

for dead in ("      sfflag_b: hex.vec w/4" + NL, "      sfflag_p: hex.vec w/4" + NL,
             "      sfslot_b: hex.vec w/4" + NL):
    assert s.count(dead) == 1, dead
    s = s.replace(dead, "", 1)
# the FIRST slot_idx local decl (steps loader's); spr_load has its own later
i = s.index("      slot_idx: hex.vec w/4" + NL)
s = s[:i] + s[i + len("      slot_idx: hex.vec w/4" + NL):]

old = "        rep(steps*stack, k) .lines_steps_load2 x" + NL
assert s.count(old) == 1
s = s.replace(old, "        rep(steps*stack, k) .lines_steps_load2" + NL)

old = ("        hex.set w/4, sprflag_b, sprflag" + NL
       + "        hex.ptr_index sprflag_p, sprflag_b, x" + NL
       + "        hex.read_byte sprfl, sprflag_p" + NL)
assert s.count(old) == 1
s = s.replace(old, "        hex.read_byte sprfl, p2_spfp             // idea 11" + NL)

old = ("        hex.zero w/4, slot_idx" + NL
       + "        hex.mov 2, slot_idx, x" + NL
       + "        hex.shl_hex w/4, 1, slot_idx            // spslot's OWN stride (SPR_SLOT_STRIDE), NOT sfslot's -- do NOT convert this to SLOT_SHIFT" + NL
       + "        hex.set w/4, spslot_b, spslot" + NL
       + "        hex.ptr_index spslot_p, spslot_b, slot_idx" + NL)
assert s.count(old) == 1
s = s.replace(old, "        hex.mov w/4, spslot_p, p2_sspp           // idea 11: working copy" + NL)

old = "    def lines_spr_load sprfl, ssy1, ssy2, sy0b, sblk, slr, ssy1b, ssy2b, sy0bb, sblkb, slrb, x " + BS
assert s.count(old) == 1
s = s.replace(old, "    def lines_spr_load sprfl, ssy1, ssy2, sy0b, sblk, slr, ssy1b, ssy2b, sy0bb, sblkb, slrb " + BS)
old = "            @ sprflag_b, sprflag_p, spslot_b, spslot_p, slot_idx, has_slot_b, end < sprflag, spslot {"
assert s.count(old) == 1
s = s.replace(old, "            @ spslot_p, has_slot_b, end < p2_spfp, p2_sspp {")
for dead in ("      sprflag_b: hex.vec w/4" + NL, "      sprflag_p: hex.vec w/4" + NL,
             "      spslot_b: hex.vec w/4" + NL, "      slot_idx: hex.vec w/4" + NL):
    assert s.count(dead) == 1, dead
    s = s.replace(dead, "", 1)

old = ", p2_slrb, x"
assert s.count(old) == 1
s = s.replace(old, ", p2_slrb")
p.write_text(s, encoding="utf-8")
print("part 2 fj ok")

q = pathlib.Path("src/doomfj/wall_renderer.py")
t = q.read_text(encoding="utf-8")
anchor = '        "p2_one: hex.vec 2",' + NL
if anchor not in t:
    import re
    m = re.search(r'        "p2_[a-z0-9_]+: hex\.vec [^"]+",\n', t)
    anchor = m.group(0)
new = (anchor + '        "p2_sffp: hex.vec w/4",' + NL + '        "p2_sfsp: hex.vec w/4",' + NL
       + '        "p2_spfp: hex.vec w/4",' + NL + '        "p2_sspp: hex.vec w/4",' + NL)
t = t.replace(anchor, new, 1)
q.write_text(t, encoding="utf-8")
print("registers declared")
