"""The layout FIX for the baked-lists change (handoff-throughput-plan section 14.7): align the code
after the deleted bind site to 2^22 words.

Why: the shared-leaf call/return flips (`wflip hex.tables.ret+w, back`) cost popcount(back), the
call site's own address. In b26 the hot leaves sat just ABOVE word 2^22 (bit 2^27) -- seg_pass1_leaf
at word 4,492,346, bspcode at 4,482,054, thing_leaf at 4,926,016 -- addresses with a lone leading
1. Deleting 652,096 words of bind_things slid them BELOW that boundary into `0111...` addresses,
and the return flips quadrupled (14.6). `pad 2097152` (2^21 ops = 2^22 words) at the deleted
call's position puts everything after it right at the boundary: lower popcounts than b26 had,
for ~370K words of padding instead of the 652K a like-for-like filler needs. Never executed: the
frame jumps over it. Applies on top of patch_nobind.py.
"""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/src/doomfj/wall_renderer.py")
s = p.read_text(encoding="utf-8")
old = """        *([] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
"""
new = """        # HOT-CODE ALIGNMENT (handoff-throughput-plan 14.7). Everything from here to the reset --
        # the frame's setup, the BSP walk and every shared leaf -- is the code whose call sites the
        # shared-leaf return flips pay popcount(address) for. b26 had it just above word 2^22 by
        # accident of size; dropping bind_things slid it below (14.6). Align it there on purpose.
        # `pad` counts OPS: 2^21 ops = 2^22 words = bit 2^27. Never executed (the frame jumps over).
        *(["    ;hot_align_end", "    pad %d" % HOT_ALIGN_OPS, "  hot_align_end:"]
          if (moving_things and standalone and HOT_ALIGN_OPS) else []),
        *([] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
"""
assert s.count(old) == 1
s = s.replace(old, new)
old2 = "NLJ = chr(10)   # newline constant for generated .fj text\n"
new2 = old2 + "HOT_ALIGN_OPS = 1 << 21   # section 14.7: align the hot code to 2^22 words (0 = off)\n"
assert s.count(old2) == 1
s = s.replace(old2, new2)
p.write_text(s, encoding="utf-8")
print("align patch applied (HOT_ALIGN_OPS = 2^21 ops)")
