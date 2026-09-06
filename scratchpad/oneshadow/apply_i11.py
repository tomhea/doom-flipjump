"""Idea 11: incremental per-column pointers for the p2 col_loop's four stride-constant arrays.

The two loaders recompute set+ptr_index (~2,050 ops) per column for sfflag/sprflag, plus
zero+mov+shl+set+ptr_index (~2,300) per piece/sprite column for the slots -- while the caller's
loop walks x by +1 and already maintains dptr (drawn) and pclm incrementally. Seed per SEG,
advance at skipcol: (the one block every continuation path passes through)."""
import pathlib
NL = chr(10)
BS = chr(92)

p = pathlib.Path("src/fj/frame_render.fj")
s = p.read_text(encoding="utf-8")

old = ("        hex.mov 8, x, x1                        // the claim loop: re-aim drawn[] at x1" + NL
       + "        hex.ptr_index dptr, dbase, x1" + NL)
new = (old
       + "        // idea 11: the load pointers walk in LOCKSTEP with x, like dptr/pclm above." + NL
       + "        rep(steps*stack, k) .lines_steps_seed x1" + NL
       + "        rep(things*spremit, k) .lines_spr_seed x1" + NL)
assert s.count(old) == 1
s = s.replace(old, new)

old = ("      skipcol:" + NL + "        hex.inc 2, x" + NL)
new = ("      skipcol:" + NL
       + "        rep(steps*stack, k) .lines_steps_step        // idea 11: lockstep advance" + NL
       + "        rep(things*spremit, k) .lines_spr_step" + NL
       + "        hex.inc 2, x" + NL)
assert s.count(old) == 1
s = s.replace(old, new)

anchor = "    def lines_steps_load2 x " + BS
assert s.count(anchor) == 1
helpers = NL.join([
"    // idea 11 helpers: seed per seg, step at skipcol, loaders read the shared globals.",
"    def lines_steps_seed x1 @ sidx, bteam, end_seed < sfflag, sfslot, p2_sffp, p2_sfsp {",
"        hex.set w/4, bteam, sfflag",
"        hex.ptr_index p2_sffp, bteam, x1",
"        hex.zero w/4, sidx",
"        hex.mov 2, sidx, x1",
"        hex.shl_hex w/4, SLOT_SHIFT, sidx",
"        hex.set w/4, bteam, sfslot",
"        hex.ptr_index p2_sfsp, bteam, sidx",
"        ;end_seed",
"      sidx: hex.vec w/4",
"      bteam: hex.vec w/4",
"      end_seed:",
"    }",
"    def lines_spr_seed x1 @ sidx, bteam, end_seed < sprflag, spslot, p2_spfp, p2_sspp {",
"        hex.set w/4, bteam, sprflag",
"        hex.ptr_index p2_spfp, bteam, x1",
"        hex.zero w/4, sidx",
"        hex.mov 2, sidx, x1",
"        hex.shl_hex w/4, 1, sidx                 // spslot's OWN stride (SPR_SLOT_STRIDE)",
"        hex.set w/4, bteam, spslot",
"        hex.ptr_index p2_sspp, bteam, sidx",
"        ;end_seed",
"      sidx: hex.vec w/4",
"      bteam: hex.vec w/4",
"      end_seed:",
"    }",
"    def lines_steps_step < p2_sffp, p2_sfsp {",
"        hex.ptr_add p2_sffp, 1",
"        hex.ptr_add p2_sfsp, 16",
"    }",
"    def lines_spr_step < p2_spfp, p2_sspp {",
"        hex.ptr_add p2_spfp, 1",
"        hex.ptr_add p2_sspp, SPR_SLOT_STRIDE",
"    }",
"",
anchor])
s = s.replace(anchor, helpers, 1)
p.write_text(s, encoding="utf-8")
print("part 1 ok")
