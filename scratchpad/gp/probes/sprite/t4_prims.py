"""Step 4: the primitives a sprite run and a recorded column are made of, priced in the SAME
standalone setting as the column probes (same emit tables; the slot arrays in the low hot block
the narrow arm needs; the bank in the high part of the image), by the slope over repetitions.
Every run must end in the program's own loop (plib asserts it)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import plib                                                                  # noqa: E402

fr = plib.Frame(plib.by_frame(plib.load_cases())[("heavy", "gate664")][:4])
REPS = (10, 30)
HOT = "\n".join(["spslot:"] + [";0 * dw"] * 64 + ["gp_zero2: hex.vec 2"])
SETUP = ["hex.set w/4, gps_sbase, sprbank", "hex.set w/4, gps_sidx, 64",
         "frame.ptr_index gps_ptr, gps_sbase, gps_sidx",
         "hex.set w/4, gps_yb8, spslot", "hex.set w/4, gps_sidx, 8",
         "frame.ptr_index gps_ybase8, gps_yb8, gps_sidx",
         "hex.write_byte gps_ybase8, gp_zero2",          # a FULL arm into the hot block first
         "hex.set 4, gps_ybase, 20", "hex.set 2, gps_rel, 7", "hex.set 4, gps_cvh, 100",
         "hex.set 4, gps_smidx, 0x0512", "hex.set 8, trb_cbound, 100", "hex.set 8, trb_y_base, 40"]
BODIES = {
    "empty": [],
    "read_byte_and_inc (bank) + ptr_sub 1": ["hex.read_byte_and_inc gps_rel, gps_ptr", "hex.ptr_sub gps_ptr, 1"],
    "ptr_sub 1": ["hex.ptr_sub gps_ptr, 1"],
    "read_byte (bank)": ["hex.read_byte gps_rel, gps_ptr"],
    "byte.emit": ["byte.emit gps_rel"],
    "cm.emit": ["cm.emit gps_smidx"],
    "mov 4 + add4_chain": ["hex.mov 4, gps_yabs, gps_ybase", "frame.add4_chain gps_yabs, gps_rel"],
    "sign 4 + if0 4 + scmp 4": ["hex.sign 4, gps_yabs, pr_a, pr_a", "pr_a:", "hex.if0 4, gps_yabs, pr_b",
                                "pr_b:", "hex.scmp 4, gps_yabs, gps_cvh, pr_c, pr_c, pr_c", "pr_c:"],
    "zero 2 + mov 2": ["hex.zero 2, srn_rel_w + 2*dw", "hex.mov 2, srn_rel_w, srn_rel"],
    "6 x shl_bit w/4 + set w/4": ["rep(6, k) hex.shl_bit w/4, gps_sidx", "hex.set w/4, gps_sidx, 8"],
    "set w/4": ["hex.set w/4, gps_sidx, 8"],
    "ptr_index (full)": ["frame.ptr_index gps_ptr, gps_sbase, gps_sidx"],
    "write_byte5 (hot)": ["frame.write_byte5 gps_ybase8, gp_zero2"],
    "read_byte5 (hot)": ["frame.read_byte5 gps_rel, gps_ybase8"],
    "mov 8 + clamp_row": ["hex.mov 8, trb_sy1, trb_y_base", "frame.clamp_row trb_sy1, trb_cbound"],
}
DECL = "gps_yb8: hex.vec 8\ngps_ybase8: hex.vec w/4"
res = {}
for name, body in BODIES.items():
    ops = []
    for reps in REPS:
        unrolled = [l.replace("pr_", "pr%d_" % k) for k in range(reps) for l in body]
        text = plib.program(fr, [], 1, pre_loop=SETUP + unrolled, lite="emit", hot_text=HOT,
                            extra_text=DECL)
        ops.append(plib.assemble_run(text, "prim", extra_fj=(plib.PROP_FJ,), want_output=False)[0])
    res[name] = (ops[1] - ops[0]) / float(REPS[1] - REPS[0])
    print("  %-38s %7.0f ops" % (name, res[name] - (res["empty"] if name != "empty" else 0)), flush=True)
