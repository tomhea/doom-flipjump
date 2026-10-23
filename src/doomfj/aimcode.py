"""M7 P4.2a -- the AIM WINDOW in fj (docs/gp-aim-window.md; the oracle: `ReferenceModel.render_wall_frame(aim_out=)`).

Every picture records, per screen column of the pellet spread (`combat.aim_window`: 72..88 at 160 wide), the nearest
shootable living monster whose radius box covers the column and that no nearer solid wall hides -- the next tic's
weapon reads it (`window_aim`). The binary records it where it projects things: `proj.project_thing` calls the shared
leaf `aim_record` right after `pth_xscale` (its `aim` parameter is 1 for the runtime monsters' projections only, so a
baked thing never records). `sp_sid` is the thing's id (0 = not shootable: its row-select stub sets it) and `sp_rc`
its radius class (0 = 20, 1 = 30).
M8 C2 (docs/c2-slot-ids.md): on a map past 254 monster + barrel slots (world.slot_nibbles 3) every id is THREE nibbles
(aim_sid's cells) and the stub writes it into `sp_sidw`; `sp_sid` is then the aimable flag (`sid_reg`).

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
RC_SOUL = 3                            # M8 C8: sp_rc's class for a lost soul (radius 16; doomfj.soulcode)
_PROJECTION_FJ = Path(__file__).resolve().parents[1] / "fj" / "projection.fj"


def reff_values(rm, barrels: bool = False, r0: int = 20, souls: bool = False) -> List[int]:
    """`aimr`: the view angle's top 8 bits -> r_eff(20) | r_eff(30) << 8 (combat.aim_radius, the ONE definition);
    M7 P6 (`barrels`): | r_eff(BARREL_R) << 16. M8 C8: `r0` radius class 0 (world.radius_classes: E1M8's 24); `souls`
    (a map with a lost soul: its own class RC_SOUL, beside class 0 and 1): | r_eff(16) << 24"""
    from doomfj.combat import CombatMixin, AIM_REFF_BITS, BARREL_R
    assert AIM_REFF_BITS == REFF_BITS
    out = []
    for i in range(1 << REFF_BITS):
        a = i << (32 - REFF_BITS)
        r20, r30 = CombatMixin.aim_radius(rm, a, r0), CombatMixin.aim_radius(rm, a, 30)
        r10 = CombatMixin.aim_radius(rm, a, BARREL_R)
        assert r20 < 256 and r30 < 256 and r10 < 256
        r16 = CombatMixin.aim_radius(rm, a, 16) if souls else 0
        assert r16 < 256
        out.append(r20 | r30 << 8 | ((r10 << 16) if barrels else 0) | (r16 << 24))
    return out


def sid_reg(sn: int = 2) -> str:
    """M8 C2 (docs/c2-slot-ids.md): the register holding a projected thing's aim ID -- `sp_sid` itself at two nibbles;
    at three (world.slot_nibbles 3) `sp_sidw`, while `sp_sid` stays the 2-nibble AIMABLE flag projection.fj's
    `proj.aim_hook` tests (`hex.if0 2, sp_sid`: the library is untouched, and an id like 0x100 would read as 0 there)"""
    assert sn in (2, 3), sn
    return "sp_sid" if sn == 2 else "sp_sidw"


def sid_set_lines(value: int, sn: int = 2, indent: str = "    ") -> List[str]:
    """a row-select stub's aim id `value` (non-zero): `hex.set 2, sp_sid, value` -- M8 C2 at three nibbles the flag
    1 and the id in sp_sidw (`sid_reg`)"""
    assert 0 < value < 16 ** sn, (value, sn)
    if sn == 2:
        return [indent + "hex.set 2, sp_sid, %d" % value]
    return [indent + "hex.set 2, sp_sid, 1", indent + "hex.set 3, sp_sidw, %d" % value]


def decls(barrels: bool = False, souls: bool = False, sn: int = 2) -> List[str]:
    """M8 C2 (`sn`, world.slot_nibbles): a slot id's nibbles -- aim_sid's per column; at 3 the id register sp_sidw
    beside the flag sp_sid (`sid_reg`)"""
    return [f"aim_sid: hex.vec {sn * NCOLS}", f"aim_tz: hex.vec {3 * NCOLS}",
            f"aim_rr: hex.vec {8 if souls else 6 if barrels else 4}",
            "aim_ret: hex.vec w/4", "sp_sid: hex.vec 2", *(["sp_sidw: hex.vec 3"] if sn == 3 else []),
            "sp_rc: hex.vec 1",
            "ar_p: hex.vec 8", "ar_q: hex.vec 8", "ar_r16: hex.vec 8", "ar_x1: hex.vec 8", "ar_x2: hex.vec 8",
            "ar_lo: hex.vec 2", "ar_n: hex.vec 2", "ar_tzi: hex.vec 3",
            # P11 (d): the thing's bucket box (proj.thing_rows, sprbkt, frame.ledge_box) and a column's piece counts
            "ar_ytop: hex.vec 8", "ar_hpx: hex.vec 8", "ar_bkt: hex.vec 4", "ar_hb: hex.vec 8", "ar_y0: hex.vec 8",
            "ar_ylo1: hex.vec 2", "ar_yhi1: hex.vec 2", "ar_fp: hex.vec w/4", "ar_cv: hex.vec 2", "ar_colx: hex.vec 2",
            f"ar_maxtz: hex.vec 8, {MAXTZ}", f"ar_c72: hex.vec 8, {FIRST}", f"ar_c88: hex.vec 8, {FIRST + NCOLS - 1}"]


def prologue_lines(sn: int = 2) -> List[str]:
    """the frame's start: an empty window, and this frame's r_eff pair (one lookup on the view angle). M8 C2: `sn`"""
    return [f"hex.zero {sn * NCOLS}, aim_sid", "aimr.lookup aim_rr, viewangle + 6*dw"]


def leaf_lines(centerx: int, barrels: bool = False, *, centery: int, viewh: int, souls: bool = False,
               sn: int = 2) -> List[str]:
    """`aim_record:` ... `stl.fret aim_ret` -- fcall'd from project_thing after pth_xscale, with sp_sid != 0.
    M7 P6 (`barrels`): class RC_BARREL reads r_eff(10). P11 (d): a column where the thing's bucket box is FULLY
    behind the column's nearer pieces (frame.ledge_test, the oracle's ledge_hidden) is skipped as a wall-drawn one is
    -- the box from project_thing's own rows (proj.thing_rows), taken once the box meets the window. M8 C2 (`sn`,
    world.slot_nibbles): a slot id's nibbles -- aim_sid's cells and sp_sid (3 on a map past 254 slots)"""
    assert RC_BARREL == 2 and sn in (2, 3)
    check_minz_first()
    # issue #119 item 4: `hex.cmp` is UNSIGNED on the signed pth_tz -- exact only because pth_tz is positive here:
    # project_thing's MINZ reject (`hex.scmp`, signed) runs before this leaf is called, and 0 < MINZ < MAXTZ < 2^31
    # (check_minz_first asserts both, at emit time)
    out = ["aim_record:",
           "hex.cmp 8, pth_tz, ar_maxtz, ar_in, ar_in, ar_out",               # beyond MISSILERANGE
           "ar_in:",
           "hex.zero 8, ar_r16",
           "hex.if0 1, sp_rc, ar_r20"]
    if souls:                                                                   # M8 C8: class 3: r_eff(16) << 16
        assert barrels, "a map with a lost soul is the game tier's: its barrels record too"
        out += ["hex.if_flags sp_rc, %d, ar_rn16, ar_rs16" % (1 << RC_SOUL),
                "ar_rs16:", "hex.mov 2, ar_r16 + 4*dw, aim_rr + 6*dw", ";ar_rok",
                "ar_rn16:"]
    if barrels:                                                                 # class 2: r_eff(10) << 16
        out += ["hex.if_flags sp_rc, %d, ar_r30, ar_r10" % (1 << RC_BARREL),
                "ar_r10:", "hex.mov 2, ar_r16 + 4*dw, aim_rr + 4*dw", ";ar_rok",
                "ar_r30:"]
    out += ["hex.mov 2, ar_r16 + 4*dw, aim_rr + 2*dw", ";ar_rok",               # r_eff(30) << 16
           "ar_r20:", "hex.mov 2, ar_r16 + 4*dw, aim_rr",                     # r_eff(20) << 16
           "ar_rok:",
           "hex.fixed_mul_low 8, 4, ar_p, pth_tx, pth_xscale",                   # P = FixedMul(tx, xscale)
           "hex.fixed_mul_low 8, 4, ar_q, ar_r16, pth_xscale",                  # Q = r_eff * xscale, exactly
           f"hex.set 8, ar_x1, {centerx << 16}", "hex.add 8, ar_x1, ar_p", "hex.sub 8, ar_x1, ar_q",
           "hex.shr_hex 8, 4, ar_x1", "hex.sign_extend 8, 4, ar_x1",
           f"hex.set 8, ar_x2, {centerx << 16}", "hex.add 8, ar_x2, ar_p", "hex.add 8, ar_x2, ar_q",
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
           "hex.mov 3, ar_tzi, pth_tz + 4*dw",                                 # the integer depth (<= 0x800)
           # P11 (d): the bucket box -- project_thing's rows (its registers are set again after this hook returns;
           # the height is >= 1 past its far reject, so the reject label is never taken), the bucket, clamped once
           f"proj.thing_rows ar_ytop, ar_hpx, {centery}, {viewh}, ar_out",
           "sprbkt.lookup ar_bkt, ar_hpx",
           "hex.zero 6, ar_hb + 2*dw", "hex.mov 2, ar_hb, ar_bkt + 2*dw",
           "hex.mov 8, ar_y0, ar_ytop", "hex.add 8, ar_y0, ar_hpx", "hex.sub 8, ar_y0, ar_hb",
           f"frame.ledge_box ar_y0, ar_hb, ar_ylo1, ar_yhi1, {viewh}"]
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
                f"hex.set w/4, ar_fp, sfflag + {x}*dw",                            # P11 (d): its piece counts,
                "hex.read_byte ar_cv, ar_fp",                                       # on the full arm
                f"hex.set 2, ar_colx, {x}",
                f"frame.ledge_test ar_cv, ar_colx, ar_ylo1, ar_yhi1, 0, aimx{c}",  # fully behind them: skip
                f"hex.if0 {sn}, aim_sid + {sn * c}*dw, aimw{c}",                     # empty: take it
                f"hex.cmp 3, ar_tzi, aim_tz + {3 * c}*dw, aimw{c}, aimx{c}, aimx{c}",   # strictly nearer
                f"aimw{c}:",
                f"hex.mov {sn}, aim_sid + {sn * c}*dw, {sid_reg(sn)}",
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


def check_box_widths(rm, barrel_wph: int = None, r0: int = 20, souls: bool = False) -> dict:
    """issue #119 item 7 (emit time): every box `aim_record` sees is at least ONE column wide, so x2 >= x1 and the
    leaf's count n = hi - lo + 1 is >= 1 after clipping (an empty box would wrap n to 0xFF -- see leaf_lines).
    x1 = (c + P - Q) >> 16 and x2 = ((c + P + Q) >> 16) - 1 with Q = r_eff * xscale exactly (the leaf's
    `fixed_mul_low` of r_eff << 16), so 2Q >= 1 << 16 suffices, for every view angle's r_eff and every depth the leaf
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
    classes = {0: (r0, MAXTZ), 1: (30, MAXTZ)}                # M8 C8: class 0 r0
    if souls:                                                       # M8 C8: the lost soul's class
        classes[RC_SOUL] = (16, MAXTZ)
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


def table_text(rm, barrels: bool = False, sprite_wad=None, r0: int = 20, souls: bool = False) -> str:
    """`aimr` -- and, at emit time, the leaf's two proofs (check_minz_first, check_box_widths): `barrels` needs the
    `sprite_wad` the barrels are drawn from (their box bound depends on the standing frame's height)"""
    from doomfj.lut_generator import generate_dispatch_table_fj
    check_minz_first()
    assert not barrels or sprite_wad is not None, "aimcode.table_text(barrels=True) needs the sprite wad (#119 item 7)"
    check_box_widths(rm, barrel_standing_wph(rm, sprite_wad) if barrels else None, r0, souls=souls)
    return generate_dispatch_table_fj("aimr", reff_values(rm, barrels, r0, souls), index_nibbles=2,
                                      result_nibbles=8 if souls else 6 if barrels else 4)
