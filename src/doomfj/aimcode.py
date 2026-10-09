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

M7 P6 (`barrels`, the player mode "full": docs/gp-p67-interface.md 5): a standing BARREL records too -- id 1 + nmon + b,
radius class RC_BARREL (combat.BARREL_R = 10): `aimr` carries r_eff(10) in nibbles 4-5 and the leaf picks it on
class 2. The id still fits two nibbles (1 + 53 + 22 = 76).
"""
from __future__ import annotations

from pathlib import Path
from typing import List

from doomfj.world import AIM_COLUMNS

# issue #119 item 6: the window's width is world.AIM_COLUMNS (the schema's `aim_sid` count, asserted against
# combat.aim_window at World._combat_init); its first column needs the renderer's viewangletox (combat.aim_window(rm)),
# so it stays a constant here -- asserted against the model by the emitter (wall_renderer, "the window moved")
FIRST, NCOLS = 72, AIM_COLUMNS         # combat.aim_window at 160 wide
MAXTZ = 2048 << 16                     # MISSILERANGE
REFF_BITS = 8                          # combat.AIM_REFF_BITS
RC_BARREL = 2                          # M7 P6: sp_rc's class for a barrel (radius 10)
_PROJECTION_FJ = Path(__file__).resolve().parents[1] / "fj" / "projection.fj"


def reff_values(rm, barrels: bool = False) -> List[int]:
    """`aimr`: the view angle's top 8 bits -> r_eff(20) | r_eff(30) << 8 (combat.aim_radius, the ONE definition);
    M7 P6 (`barrels`): | r_eff(BARREL_R) << 16"""
    from doomfj.combat import CombatMixin, AIM_REFF_BITS, BARREL_R
    assert AIM_REFF_BITS == REFF_BITS
    out = []
    for i in range(1 << REFF_BITS):
        a = i << (32 - REFF_BITS)
        r20, r30 = CombatMixin.aim_radius(rm, a, 20), CombatMixin.aim_radius(rm, a, 30)
        r10 = CombatMixin.aim_radius(rm, a, BARREL_R)
        assert r20 < 256 and r30 < 256 and r10 < 256
        out.append(r20 | r30 << 8 | ((r10 << 16) if barrels else 0))
    return out


def decls(barrels: bool = False) -> List[str]:
    return [f"aim_sid: hex.vec {2 * NCOLS}", f"aim_tz: hex.vec {3 * NCOLS}", f"aim_rr: hex.vec {6 if barrels else 4}",
            "aim_ret: hex.vec w/4", "sp_sid: hex.vec 2", "sp_rc: hex.vec 1",
            "ar_p: hex.vec 8", "ar_q: hex.vec 8", "ar_r16: hex.vec 8", "ar_x1: hex.vec 8", "ar_x2: hex.vec 8",
            "ar_lo: hex.vec 2", "ar_n: hex.vec 2", "ar_tzi: hex.vec 3",
            f"ar_maxtz: hex.vec 8, {MAXTZ}", f"ar_c72: hex.vec 8, {FIRST}", f"ar_c88: hex.vec 8, {FIRST + NCOLS - 1}"]


def prologue_lines() -> List[str]:
    """the frame's start: an empty window, and this frame's r_eff pair (one lookup on the view angle)"""
    return [f"hex.zero {2 * NCOLS}, aim_sid", "aimr.lookup aim_rr, viewangle + 6*dw"]


def leaf_lines(centerx: int, barrels: bool = False) -> List[str]:
    """`aim_record:` ... `stl.fret aim_ret` -- fcall'd from project_thing after pth_xscale, with sp_sid != 0.
    M7 P6 (`barrels`): class RC_BARREL reads r_eff(10)"""
    assert RC_BARREL == 2
    check_minz_first()
    # issue #119 item 4: `hex.cmp` is UNSIGNED on the signed pth_tz -- exact only because pth_tz is positive here:
    # project_thing's MINZ reject (`hex.scmp`, signed) runs before this leaf is called, and 0 < MINZ < MAXTZ < 2^31
    # (check_minz_first asserts both, at emit time)
    out = ["aim_record:",
           "hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_out",               # beyond MISSILERANGE
           "ar_in:",
           "hex.zero 8, ar_r16",
           "hex.if0 1, sp_rc, ar_r20"]
    if barrels:                                                                 # class 2: r_eff(10) << 16
        out += ["hex.if_flags sp_rc, %d, ar_r30, ar_r10" % (1 << RC_BARREL),
                "ar_r10:", "hex.mov 2, ar_r16 + 4*dw, aim_rr + 4*dw", ";ar_rok",
                "ar_r30:"]
    out += ["hex.mov 2, ar_r16 + 4*dw, aim_rr + 2*dw", ";ar_rok",               # r_eff(30) << 16
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
           # n = hi - lo + 1 (1..17), the first block lo - 72 (0..16): both fit two nibbles now. n >= 1 needs a box at
           # least one column wide (x2 >= x1): an EMPTY box would make n 0 and `hex.dec` wrap it to 0xFF, recording
           # every column to the window's end where the oracle records none (issue #119 item 7) -- check_box_widths
           # proves every aimed box >= 1 column at emit time
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


def check_minz_first(text: str = None) -> None:
    """issue #119 item 4 (emit time): `aim_record`'s UNSIGNED `hex.cmp 8, pth_tz, ar_maxtz` reads a signed depth, so
    it is exact only while pth_tz is positive whenever the leaf runs. That holds because proj.project_thing's MINZ
    reject (a SIGNED `hex.scmp` of pth_tz against MINZ > 0) comes BEFORE its `aim_hook` in the macro's body, and
    0 < MINZ < MAXTZ < 2^31 (every accepted depth is then one the unsigned compare orders correctly). `text`: the
    projection.fj source (default: the file; a test passes a mutated copy -- tests/host/test_p8a_followups.py)."""
    from doomfj.reference_model import SPRITE_MINZ
    assert 0 < SPRITE_MINZ < MAXTZ < 1 << 31, ("aim_record's unsigned depth compare needs 0 < MINZ < MAXTZ < 2^31",
                                               SPRITE_MINZ, MAXTZ)
    text = _PROJECTION_FJ.read_text(encoding="utf-8") if text is None else text
    head = text.index("    def project_thing ")
    nxt = text.find("\n    def ", head + 1)
    body = [ln.strip() for ln in text[head:nxt if nxt >= 0 else len(text)].splitlines()]
    minz = [i for i, ln in enumerate(body) if ln.startswith("hex.scmp 8, pth_tz, pth_czlim, reject,")]
    hook = [i for i, ln in enumerate(body) if ln.startswith("rep(aim, k) .aim_hook")]
    assert len(minz) == 1 and len(hook) == 1, ("project_thing's MINZ reject / aim hook not found exactly once",
                                               minz, hook)
    assert body[minz[0] - 1] == "hex.set 8, pth_czlim, minz", ("the signed reject no longer compares MINZ",
                                                               body[minz[0] - 1])
    assert minz[0] < hook[0], ("aim_record's unsigned depth compare needs project_thing's MINZ reject BEFORE the aim "
                               "hook: a negative pth_tz would compare as huge and the far test would misread it")


def check_box_widths(rm, barrel_wph: int = None) -> dict:
    """issue #119 item 7 (emit time): every box `aim_record` sees is at least ONE column wide, so x2 >= x1 and the
    leaf's count n = hi - lo + 1 is >= 1 after clipping (an empty box would wrap n to 0xFF -- see leaf_lines).
    x1 = (c + P - Q) >> 16 and x2 = ((c + P + Q) >> 16) - 1 with Q = r_eff * xscale exactly (the leaf's
    `fixed_mul_lo` of r_eff << 16), so 2Q >= 1 << 16 suffices, for every view angle's r_eff and every depth the leaf
    records at:
      * a monster (classes 0 / 1, r_eff of radius 20 / 30): any depth up to MAXTZ (MIN_SPRITE_H_MONSTER rows lets a
        monster project nearly to MISSILERANGE);
      * a standing barrel (class RC_BARREL, radius 10; `barrel_wph` = the tallest standing frame's height, the
        program's barrels on): only where the projection keeps it -- MIN_SPRITE_H rows, depth <=
        sprite_tz_min_size(wph, MIN_SPRITE_H), its baked sp_tzmax (the raised degrade bound is nearer still). At
        MAXTZ a barrel's box would be 0.78 of a column; at its own bound it is ~1.9 (E1M1, freedoom).
    xscale is the block-FP reciprocal: its minimum over a class's depths is taken over every whole map unit of the
    top eighth of the range (it falls with depth; the margins are > 50%). Returns {class: (min r_eff, depth bound,
    min xscale, min 2Q in columns)}."""
    from doomfj.combat import BARREL_R, CombatMixin
    from doomfj.reference_model import MIN_SPRITE_H
    proj = rm.cfg.PROJECTION
    classes = {0: (20, MAXTZ), 1: (30, MAXTZ)}
    if barrel_wph is not None:
        classes[RC_BARREL] = (BARREL_R, min(MAXTZ, rm.sprite_tz_min_size(barrel_wph, MIN_SPRITE_H)))
    out = {}
    for rc, (r, tzmax) in classes.items():
        reff = min(CombatMixin.aim_radius(rm, i << (32 - REFF_BITS), r) for i in range(1 << REFF_BITS))
        top = tzmax >> 16
        xs = min(rm._scale_recip_div(proj << 16, tz << 16) for tz in range(top - top // 8, top + 1))
        xs = min(xs, rm._scale_recip_div(proj << 16, tzmax))
        out[rc] = (reff, tzmax, xs, 2 * reff * xs / 65536)
        assert 2 * reff * xs >= 1 << 16, (
            "aim_record: a class-%d box (r_eff %d) at depth %d is narrower than one column (2Q = %d < 65536) -- an "
            "empty box wraps the leaf's column count (issue #119 item 7)" % (rc, reff, tzmax >> 16, 2 * reff * xs))
    return out


def barrel_standing_wph(rm, sprite_wad) -> int:
    """the tallest standing barrel frame's height in map units (S_BAR1 / S_BAR2's lumps: the frames the aim id rides)"""
    from doomfj.monsters import mobile_lump
    cache = {}
    return max(rm.art_of_lump(sprite_wad, mobile_lump(s), cache)[4] for s in ("S_BAR1", "S_BAR2"))


def table_text(rm, barrels: bool = False, sprite_wad=None) -> str:
    """`aimr` -- and, at emit time, the leaf's two proofs (check_minz_first, check_box_widths): `barrels` needs the
    `sprite_wad` the barrels are drawn from (their box bound depends on the standing frame's height)"""
    from doomfj.lut_generator import generate_dispatch_table_fj
    check_minz_first()
    assert not barrels or sprite_wad is not None, "aimcode.table_text(barrels=True) needs the sprite wad (#119 item 7)"
    check_box_widths(rm, barrel_standing_wph(rm, sprite_wad) if barrels else None)
    return generate_dispatch_table_fj("aimr", reff_values(rm, barrels), index_nibbles=2,
                                      result_nibbles=6 if barrels else 4)
