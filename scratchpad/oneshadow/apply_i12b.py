"""Idea 12 part 2: frame_render seeds/steps the prod accumulators; the wrapper calls the twin."""
import pathlib
NL = chr(10)
BS = chr(92)

p = pathlib.Path("src/fj/frame_render.fj")
s = p.read_text(encoding="utf-8")

# seed macros beside the idea-11 ones
anchor = "    // idea 11 helpers: seed per seg, step at skipcol, loaders read the shared globals."
assert s.count(anchor) == 1
helpers = NL.join([
"    // idea 12: the wall top/bottom DDA. prod = wt*scale and step = wt*scalestep are seeded per",
"    // seg (four 6-row multiplies); per column the two adds at skipcol replace the two 6-row",
"    // multiplies column_params_m ran. Exact: low32 multiplication distributes over the mod-2^32",
"    // scale walk, the same identity the Option-A face DDA relies on.",
"    def lines_dda_seed scale, scalestep, wtc8, wtf8 < p2_prodc, p2_prodf, p2_stepc, p2_stepf {",
"        hex.zero 8, p2_prodc",
"        rep(6, j) hex.fixed_mul_lo.row 8, j, p2_prodc, wtc8, scale",
"        hex.zero 8, p2_stepc",
"        rep(6, j) hex.fixed_mul_lo.row 8, j, p2_stepc, wtc8, scalestep",
"        hex.zero 8, p2_prodf",
"        rep(6, j) hex.fixed_mul_lo.row 8, j, p2_prodf, wtf8, scale",
"        hex.zero 8, p2_stepf",
"        rep(6, j) hex.fixed_mul_lo.row 8, j, p2_stepf, wtf8, scalestep",
"    }",
"    def lines_dda_step < p2_prodc, p2_prodf, p2_stepc, p2_stepf {",
"        hex.add 8, p2_prodc, p2_stepc",
"        hex.add 8, p2_prodf, p2_stepf",
"    }",
"",
anchor])
s = s.replace(anchor, helpers, 1)

# seed at the seg head, next to the idea-11 seeds (scale/scalestep/p2_wt* are set by then)
old = "        rep(steps*stack, k) .lines_steps_seed x1" + NL
assert s.count(old) == 1
s = s.replace(old, "        rep(1-noproj, k) .lines_dda_seed scale, scalestep, p2_wtc8, p2_wtf8" + NL + old)

# step at skipcol, before the x increment
old = "        rep(steps*stack, k) .lines_steps_step        // idea 11: lockstep advance" + NL
assert s.count(old) == 1
s = s.replace(old, "        rep(1-noproj, k) .lines_dda_step             // idea 12: the wall DDA" + NL + old)

# the wrapper drops scale/wt and calls the twin (both call sites in this leaf)
old = ("    def lines_projcall centeryfix_c, viewh1, top, bottom, scale, wtc8, wtf8 {" + NL
       + "        proj.column_params_m top, bottom, scale, wtc8, wtf8, centeryfix_c, viewh1" + NL
       + "    }" + NL)
new = ("    def lines_projcall centeryfix_c, viewh1, top, bottom {" + NL
       + "        proj.column_params_dda top, bottom, centeryfix_c, viewh1" + NL
       + "    }" + NL)
assert s.count(old) == 1
s = s.replace(old, new)
for a, b in [
    ("        rep(1-noproj, k) .lines_projcall centery*0x10000, viewh1, top, bottom, scale, p2_wtc8, p2_wtf8",
     "        rep(1-noproj, k) .lines_projcall centery*0x10000, viewh1, top, bottom"),
    ("        rep(ptwice, k) .lines_projcall centery*0x10000, viewh1, p2_dtop, p2_dbot, scale, p2_wtc8, p2_wtf8",
     "        rep(ptwice, k) .lines_projcall centery*0x10000, viewh1, p2_dtop, p2_dbot"),
]:
    assert s.count(a) == 1, a[:60]
    s = s.replace(a, b)
p.write_text(s, encoding="utf-8")
print("frame_render: seeds, steps, wrapper switched")

q = pathlib.Path("src/doomfj/wall_renderer.py")
t = q.read_text(encoding="utf-8")
old = '        "p2_sffp: hex.vec w/4",' + NL
assert t.count(old) == 1
new = (old.replace('sffp: hex.vec w/4",', 'sffp: hex.vec w/4",')
       + '        "p2_prodc: hex.vec 8",' + NL + '        "p2_prodf: hex.vec 8",' + NL
       + '        "p2_stepc: hex.vec 8",' + NL + '        "p2_stepf: hex.vec 8",' + NL)
t = t.replace(old, new, 1)
q.write_text(t, encoding="utf-8")
print("registers declared")
