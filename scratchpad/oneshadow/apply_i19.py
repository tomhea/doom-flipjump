"""Idea 19: pair-fused chains. Two back-to-back add8_chains (or sub8s with only exact_xor-family
ops between) share ONE mid bracket instead of [trail][lead] -- 19 dances instead of 20, every
boundary fused. Generates the pair macros, applies the two call-site changes, and extends the
smoke. RUN ONLY WHEN NO BUILD IS READING THE TREE."""
from pathlib import Path

NL = chr(10)
J = lambda *l: NL.join(l)


def gen_pair(op):
    jm = f"hex.{op}.dst"
    a = [f"a{i}" for i in range(8)]
    b = [f"b{i}" for i in range(8)]
    locs = ["rcc0"] + (["cc0_ok"] if op == "sub" else []) + a + ["mid"] + (["mid_ok"] if op == "sub" else []) + b + ["rcc1"] + (["done"] if op == "sub" else [])
    L = []
    p = L.append
    p(f"    //   dstA[:8] {'+' if op=='add' else '-'}= srcA[:8]; dstB[:8] {'+' if op=='add' else '-'}= srcB[:8]  -- two hex.{op} 8 calls")
    p("    //   sharing ONE mid bracket (19 dances, not 20), every boundary fused. Same hermetic-")
    p("    //   window rule as add8_chain.")
    p(f"    def {op}8_pair_chain dstA, srcA, dstB, srcB @ {', '.join(locs)} " + chr(92))
    p(f"            < hex.tables.ret, hex.tables.res, {jm} {{")
    p(f"        wflip hex.tables.ret+w, rcc0, {jm}")
    p("      rcc0:")
    if op == "add":
        p("        hex.zero hex.tables.res")
    else:
        p("        hex.if0 hex.tables.res, cc0_ok")
        p("        hex.sub.not_carry")
        p("        hex.xor_by hex.tables.res, 0xf")
        p("      cc0_ok:")
    p(f"        hex.xor {jm},   dstA")
    p(f"        hex.xor {jm}+4, srcA")
    p(f"        wflip hex.tables.ret+w, rcc0^a0, {jm}")
    for i in range(7):
        p(f"      a{i}:")
        p(f"        .dance_boundary dstA+{i}*dw, dstA+{i+1}*dw, srcA+{i+1}*dw, {jm}, a{i}, a{i+1}")
    p("      a7:")
    p("        hex.xor_zero dstA+7*dw, hex.tables.res")
    p(f"        wflip hex.tables.ret+w, a7^mid, {jm}")
    p("      mid:")
    if op == "add":
        p("        hex.zero hex.tables.res                 // discard A's final carry")
    else:
        p("        hex.if0 hex.tables.res, mid_ok          // discard A's final borrow")
        p("        hex.sub.not_carry")
        p("        hex.xor_by hex.tables.res, 0xf")
        p("      mid_ok:")
    p(f"        hex.xor {jm},   dstB")
    p(f"        hex.xor {jm}+4, srcB")
    p(f"        wflip hex.tables.ret+w, mid^b0, {jm}")
    for i in range(7):
        p(f"      b{i}:")
        p(f"        .dance_boundary dstB+{i}*dw, dstB+{i+1}*dw, srcB+{i+1}*dw, {jm}, b{i}, b{i+1}")
    p("      b7:")
    p("        hex.xor_zero dstB+7*dw, hex.tables.res")
    p(f"        wflip hex.tables.ret+w, b7^rcc1, {jm}")
    p("      rcc1:")
    p("        wflip hex.tables.ret+w, rcc1")
    if op == "add":
        p("        hex.zero hex.tables.res")
    else:
        p("        hex.if0 hex.tables.res, done")
        p("        hex.sub.not_carry")
        p("        hex.xor_by hex.tables.res, 0xf")
        p("      done:")
    p("    }")
    return J(*L)


def main():
    f = Path("src/fj/frame_render.fj")
    t = f.read_text(encoding="utf-8")
    fam = gen_pair("add") + NL * 2 + gen_pair("sub")
    anchor = "    def lines_dda_step < p2_prodc, p2_prodf, p2_stepc, p2_stepf {"
    assert t.count(anchor) == 1
    t = t.replace(anchor, fam + NL * 2 + anchor)

    old = J("    def lines_dda_step < p2_prodc, p2_prodf, p2_stepc, p2_stepf {",
            "        .add8_chain p2_prodc, p2_stepc               // idea 14: was hex.add 8 -- same 962 ops",
            "        .add8_chain p2_prodf, p2_stepf               //   of space, ~170 fewer executed per call",
            "    }")
    new = J("    def lines_dda_step < p2_prodc, p2_prodf, p2_stepc, p2_stepf {",
            "        .add8_pair_chain p2_prodc, p2_stepc, p2_prodf, p2_stepf   // idea 19: one mid bracket",
            "    }")
    assert t.count(old) == 1
    t = t.replace(old, new)
    f.write_text(t, encoding="utf-8")
    print("frame_render: pair macros + dda_step fused")

    f2 = Path("src/fj/projection.fj")
    t2 = f2.read_text(encoding="utf-8")
    old2 = J("        hex.mov 8, top, cpm_c_centeryfix",
             "        frame.sub8_chain top, p2_prodc          // topfrac = centeryfix - wt*scale (the DDA copy;",
             "        hex.shr_hex 8, 4, top                   //   idea 15: chained sub -- see add8_chain's",
             "        hex.sign_extend 8, 4, top               //   hermetic-window warning in frame_render.fj)",
             "        hex.mov 8, bottom, cpm_c_centeryfix",
             "        frame.sub8_chain bottom, p2_prodf       // idea 15: chained")
    new2 = J("        hex.mov 8, top, cpm_c_centeryfix",
             "        hex.mov 8, bottom, cpm_c_centeryfix",
             "        // idea 19: both subs in ONE pair-fused chain (movs hoisted above -- they touch",
             "        // neither sub's operands nor hex.tables.ret, so the reorder is inert).",
             "        frame.sub8_pair_chain top, p2_prodc, bottom, p2_prodf",
             "        hex.shr_hex 8, 4, top",
             "        hex.sign_extend 8, 4, top")
    assert t2.count(old2) == 1
    f2.write_text(t2.replace(old2, new2), encoding="utf-8")
    print("projection: column_params_dda pair-fused (movs hoisted)")


if __name__ == "__main__":
    main()
