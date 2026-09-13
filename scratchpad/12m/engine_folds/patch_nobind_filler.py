"""The LAYOUT CONTROL for the baked-lists change (handoff-throughput-plan section 14).

Dropping `sim.bind_things` from the standalone frame removed 652,096 words of code and slid every
later object down by that much. The op count then fell by only 0.8 M/frame instead of ~7.5 M:
the profile (14.6) shows the difference is entirely wflip chains into the shared-leaf return words
(`hex.tables.ret`, `hex.tables.res`, `hex.mul.ret`), whose cost is popcount(return address), and
the return addresses are the call sites that moved.

This patch puts a dead filler of EXACTLY the removed size where the call was, so every downstream
address is b26's again. It is an experiment, not the shipping answer: it proves (or refutes) that
the give-back is layout, and measures what the change is worth at b26's placement. Applies on top
of patch_nobind.py.
"""
from pathlib import Path
p = Path(r"C:/Users/tomhe/Documents/doom-flipjump/src/doomfj/wall_renderer.py")
s = p.read_text(encoding="utf-8")
old = """        *([] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
"""
new = """        # LAYOUT CONTROL (handoff-throughput-plan 14.6): a dead filler the exact size of the removed
        # bind_things expansion (652,096 words = 326,048 ops on E1M1 at b26's knobs), so every
        # object after it keeps b26's address and the shared-leaf return flips keep their popcount.
        # Never executed: the frame jumps over it. Experiment-only; see the handoff before shipping.
        *(["    ;bind_filler_end", "    rep(326048, i) ;", "  bind_filler_end:"]
          if (moving_things and standalone and BIND_FILLER) else []),
        *([] if (moving_things and standalone) else
          [f"rep({_MT_NT}, i) hex.input 8, thpos_rt + i*16*dw",
"""
assert s.count(old) == 1
s = s.replace(old, new)
old2 = "NLJ = chr(10)   # newline constant for generated .fj text\n"
new2 = old2 + "BIND_FILLER = True   # section 14.6 layout control; set False for the real build\n"
assert s.count(old2) == 1
s = s.replace(old2, new2)
p.write_text(s, encoding="utf-8")
print("filler patch applied (BIND_FILLER=True)")
