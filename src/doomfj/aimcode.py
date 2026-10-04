"""M7 P4.2a -- the AIM WINDOW in fj (docs/gp-aim-window.md; the oracle: `ReferenceModel.render_wall_frame(aim_out=)`).

Every picture records, per screen column of the pellet spread (`combat.aim_window`: 72..88 at 160 wide), the nearest
shootable living monster whose radius box covers the column and that no nearer solid wall hides -- the next tic's
weapon reads it (`window_aim`). The binary records it where it projects things: `proj.project_thing` calls the shared
leaf `aim_record` right after `pth_xscale` (its `aim` parameter is 1 for the runtime monsters' projections only, so a
baked thing never records). `sp_sid` is the thing's id (0 = not shootable: its row-select stub sets it) and `sp_rc`
its radius class (0 = 20, 1 = 30).

THE LEAF (gp-aim-window 1.4 -- no divide):
  * range: tz <= 2048 << 16 (MISSILERANGE along the view axis); MINZ, the base far bound and the FOV test are
    project_thing's own rejects, all before xscale;
  * P = FixedMul(tx, xscale), Q = r_eff * xscale (r_eff from `aimr`, the view angle's top 8 bits -- combat.aim_radius);
  * x1 = (centerxfrac + P - Q) >> 16, x2 = ((centerxfrac + P + Q) >> 16) - 1, clipped to the window;
  * a jump into the unrolled chain of 17 column blocks at x1, counting down to x2: a column a solid wall drew
    (`drawn[c]`) is skipped, an empty cell or a strictly nearer integer depth (tz >> 16) takes the thing.
The cells: `aim_sid` (2 nibbles per column: 0 or 1 + slot) and `aim_tz` (3 nibbles: the integer depth), zeroed by the
frame's prologue (`prologue_lines`), persisted across the reset (build.AIM_PERSIST) for the next frame's weapon.
"""
from __future__ import annotations

from typing import List

FIRST, NCOLS = 72, 17                  # combat.aim_window at 160 wide (asserted by the emitter against the model)
MAXTZ = 2048 << 16                     # MISSILERANGE
REFF_BITS = 8                          # combat.AIM_REFF_BITS


def reff_values(rm) -> List[int]:
    """`aimr`: the view angle's top 8 bits -> r_eff(20) | r_eff(30) << 8 (combat.aim_radius, the ONE definition)"""
    from doomfj.combat import CombatMixin, AIM_REFF_BITS
    assert AIM_REFF_BITS == REFF_BITS
    out = []
    for i in range(1 << REFF_BITS):
        a = i << (32 - REFF_BITS)
        r20, r30 = CombatMixin.aim_radius(rm, a, 20), CombatMixin.aim_radius(rm, a, 30)
        assert r20 < 256 and r30 < 256
        out.append(r20 | r30 << 8)
    return out


def decls() -> List[str]:
    return [f"aim_sid: hex.vec {2 * NCOLS}", f"aim_tz: hex.vec {3 * NCOLS}", "aim_rr: hex.vec 4",
            "aim_ret: hex.vec w/4", "sp_sid: hex.vec 2", "sp_rc: hex.vec 1",
            "ar_p: hex.vec 8", "ar_q: hex.vec 8", "ar_r16: hex.vec 8", "ar_x1: hex.vec 8", "ar_x2: hex.vec 8",
            "ar_lo: hex.vec 2", "ar_n: hex.vec 2", "ar_tzi: hex.vec 3",
            f"ar_maxtz: hex.vec 8, {MAXTZ}", f"ar_c72: hex.vec 8, {FIRST}", f"ar_c88: hex.vec 8, {FIRST + NCOLS - 1}"]


def prologue_lines() -> List[str]:
    """the frame's start: an empty window, and this frame's r_eff pair (one lookup on the view angle)"""
    return [f"hex.zero {2 * NCOLS}, aim_sid", "aimr.lookup aim_rr, viewangle + 6*dw"]


def leaf_lines(centerx: int) -> List[str]:
    """`aim_record:` ... `stl.fret aim_ret` -- fcall'd from project_thing after pth_xscale, with sp_sid != 0"""
    out = ["aim_record:",
           "hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_out",               # beyond MISSILERANGE
           "ar_in:",
           "hex.zero 8, ar_r16",
           "hex.if0 1, sp_rc, ar_r20",
           "hex.mov 2, ar_r16 + 4*dw, aim_rr + 2*dw", ";ar_rok",               # r_eff(30) << 16
           "ar_r20:", "hex.mov 2, ar_r16 + 4*dw, aim_rr",                     # r_eff(20) << 16
           "ar_rok:",
           "hex.fixed_mul_lo 8, 4, ar_p, pth_tx, pth_xscale",                   # P = FixedMul(tx, xscale)
           "hex.fixed_mul_lo 8, 4, ar_q, ar_r16, pth_xscale",                  # Q = r_eff * xscale, exactly
           f"hex.set 8, ar_x1, {centerx << 16}", "frame.add8_chain ar_x1, ar_p", "frame.sub8_chain ar_x1, ar_q",
           "hex.shr_hex 8, 4, ar_x1", "hex.sign_extend 8, 4, ar_x1",
           f"hex.set 8, ar_x2, {centerx << 16}", "frame.add8_chain ar_x2, ar_p", "frame.add8_chain ar_x2, ar_q",
           "hex.shr_hex 8, 4, ar_x2", "hex.sign_extend 8, 4, ar_x2", "hex.dec 8, ar_x2",
           # the box against the window: x2 < 72 or x1 > 88 -> nothing; then lo = max(x1, 72), hi = min(x2, 88)
           "hex.scmp 8, ar_x2, ar_c72, ar_out, ar_a, ar_a",
           "ar_a:", "hex.scmp 8, ar_x1, ar_c88, ar_b, ar_b, ar_out",
           "ar_b:", "hex.scmp 8, ar_x1, ar_c72, ar_lo72, ar_lox, ar_lox",
           "ar_lo72:", "hex.mov 8, ar_x1, ar_c72",
           "ar_lox:", "hex.scmp 8, ar_x2, ar_c88, ar_hix, ar_hix, ar_hi88",
           "ar_hi88:", "hex.mov 8, ar_x2, ar_c88",
           "ar_hix:",
           # n = hi - lo + 1 (1..17), the first block lo - 72 (0..16): both fit two nibbles now
           "hex.mov 2, ar_n, ar_x2", "hex.sub 2, ar_n, ar_x1", "hex.inc 2, ar_n",
           f"hex.mov 2, ar_lo, ar_x1", f"hex.sub_constant 2, ar_lo, {FIRST}",
           "hex.mov 3, ar_tzi, pth_tz + 4*dw"]                                 # the integer depth (<= 0x800)
    # the jump into the chain at block lo: the high nibble (0 or 1), then the low nibble
    out += ["hex.if_flags ar_lo + dw, 1<<1, ar_jl0, ar_jl1"]
    for h in (0, 1):
        out.append(f"ar_jl{h}:")
        for lo in range(16):
            c = h * 16 + lo
            if c >= NCOLS:
                break
            out += [f"hex.if_flags ar_lo, 1<<{lo}, ar_j{c}n, aimb{c}", f"ar_j{c}n:"]
        out.append(";ar_out")
    for c in range(NCOLS):
        x = FIRST + c
        out += [f"aimb{c}:",
                f"hex.if0 1, drawn + {x}*dw, aimo{c}", f";aimx{c}",               # a solid wall drew it: skip
                f"aimo{c}:",
                f"hex.if0 2, aim_sid + {2 * c}*dw, aimw{c}",                       # empty: take it
                f"hex.cmp 3, ar_tzi, aim_tz + {3 * c}*dw, aimw{c}, aimx{c}, aimx{c}",   # strictly nearer
                f"aimw{c}:",
                f"hex.mov 2, aim_sid + {2 * c}*dw, sp_sid",
                f"hex.mov 3, aim_tz + {3 * c}*dw, ar_tzi",
                f"aimx{c}:",
                "hex.dec 2, ar_n", "hex.if0 2, ar_n, ar_out"]
    out += [";ar_out", "ar_out:", "stl.fret aim_ret"]
    return out


def table_text(rm) -> str:
    from doomfj.lut_generator import generate_dispatch_table_fj
    return generate_dispatch_table_fj("aimr", reff_values(rm), index_nibbles=2, result_nibbles=4)
