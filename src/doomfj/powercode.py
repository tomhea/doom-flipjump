"""M8 C6 -- THE TIMED POWERS in fj (partial invisibility 2024, the radiation suit 2025): the rules are
`doomfj.powers`' (one definition, the model's too), and nothing here is emitted on a map that holds neither power
(E1M1, E1M2: their programs are unchanged). The pieces, each spliced where the model runs the rule:

  * `decls(powers)`: the persisted counters `p_inv` / `p_rad` (3 nibbles, 0 at the level start) and the scratch;
    `map_persist`: the counters the M1 reset leaves alone (build._map_persist); `level_start_lines`: NEW GAME and the
    restart zero them (G_PlayerReborn);
  * the GIVES (`give_lines`, lootcode.give_lines' case): P_GivePower -- the counter SET to 2100, always taken;
  * `countdown_lines`: P_PlayerThink's countdown, alive only (lootcode.post_lines' alive branch, after the strength --
    the model's `_player_phase` order);
  * `suit_lines`: P_PlayerInSpecialSector with the suit (lootcode.nukage_lines, at the hurt, after the floor test):
    a 20-damage floor leaks when `sutr[rng_pl]` (P_Random() < 5, one draw on the player's stream), the others hurt
    nothing;
  * `pal_lines`: ST_doPaletteStuff's RADIATIONPAL (hurtcode.pal_lines(suit=True), when no red or gold palette is up)
    -- `p_rad > 128 || p_rad & 8`;
  * `shj_leaf_lines`: `mm_shj` (stl.fcall mm_shj, mm_shjret) -- A_FaceTarget at a shadow target: the target is the
    player (`mt_pl`) and `p_inv` != 0 -> two draws on the shooter's stream (`mm_rng`) and `md_jit` = 2 * (a - b) (the
    bullets' spread unit), else `md_jit` = 0 and no draw. monsterdecide calls it after every facing of an attack
    (md_attack) and of a decision (mm_decide's attack state), and md_bul adds md_jit to each bullet's spread;
  * `missile_lines`: P_SpawnMissile at a shadow target (projcode's pj_spawn_leaf, after the aim): two draws on
    `mm_rng`, `(a - b) << 20` added to the fireball's angle;
  * `shadow_lines`: the weapon's shadow draw test (hudcode's tail: R_DrawPSprite's `p_inv > 128 || p_inv & 8`).
"""
from __future__ import annotations

from typing import List, Sequence

from doomfj import powers as P

M = P.NIBBLES


def cells(powers: Sequence[int]) -> tuple:
    return tuple(P.CELL[k] for k in powers)


def map_persist(map_wad, mapname: str) -> tuple:
    """the counters the M1 reset leaves alone on this map (build._map_persist; E1M1, E1M2: none)"""
    return cells(P.map_powers(map_wad.things(mapname)))


def decls(powers: Sequence[int]) -> List[str]:
    out = [f"{c}: hex.vec {M}, 0" for c in cells(powers)]
    if powers:
        out += [f"pw_c128: hex.vec {M}, {P.BLINK_TICS}"]
    if P.INVIS_TYPE in powers:
        out += ["md_jit: hex.vec 4", "mm_shjret: hex.vec w/4", "pw_shm: hex.vec 3", "pw_shd: hex.vec 1"]
    if P.SUIT_TYPE in powers:
        out += ["pw_lk: hex.vec 2"]                                        # the leak floor (2), the roll (1)
    return out


def level_start_lines(powers: Sequence[int]) -> List[str]:
    """NEW GAME / the restart: no power (G_PlayerReborn)"""
    return [f"    hex.zero {M}, {c}" for c in cells(powers)]


def give_lines(kind: int, ok: str) -> List[str]:
    """P_GivePower(pw_invisibility / pw_ironfeet): the counter set, taken"""
    return [f"    hex.set {M}, {P.CELL[kind]}, {P.TICS[kind]}", f"    ;{ok}"]


def countdown_lines(powers: Sequence[int]) -> List[str]:
    """P_PlayerThink: each running counter one less (alive only: the caller's branch)"""
    out = []
    for c in cells(powers):
        out += [f"hex.if0 {M}, {c}, {c}_cd", f"hex.dec {M}, {c}", f"{c}_cd:"]
    return out


def _blink(cell: str, yes: str, no: str, tag: str) -> List[str]:
    """`cell > 128 || cell & 8` -> yes, else no"""
    return [f"hex.if_flags {cell}, 0xFF00, {tag}_g, {yes}",          # nibble 0 in 8..15: bit 3 set
            f"{tag}_g:",
            f"hex.cmp {M}, {cell}, pw_c128, {no}, {no}, {yes}"]


def pal_lines() -> List[str]:
    """after the red and the gold (pal_new 0 only): RADIATIONPAL while the suit shows"""
    return (["hex.if1 1, pal_new, pl_rad_end"] + _blink("p_rad", "pl_rad_on", "pl_rad_end", "pl_rad")
            + ["pl_rad_on:", f"hex.set 1, pal_new, {P.RADIATIONPAL}", "pl_rad_end:"])


def shadow_lines(draw_shadow: str, draw_plain: str) -> List[str]:
    """the weapon's psprites: the shadow draw while invisibility shows, else the plain one"""
    return _blink("p_inv", draw_shadow, draw_plain, "hw_shd")


def suit_lines(hurt: str, out: str) -> List[str]:
    """at the nukage hurt (the floor test passed, nk_dmg the sector's damage): with the suit, only a 20-damage floor,
    and only when P_Random() < 5 (one draw on rng_pl)"""
    return ["hex.if0 3, p_rad, %s" % hurt,
            "hex.set 2, pw_lk, %d" % P.SUIT_LEAK_DAMAGE,
            "hex.cmp 2, nk_dmg, pw_lk, %s, nk_suit_r, %s" % (out, out),
            "nk_suit_r:",
            "hex.inc 2, rng_pl",
            "hex.zero 1, pw_lk", "sutr.lookup pw_lk, rng_pl",
            "hex.if0 1, pw_lk, %s" % out,
            ";%s" % hurt]


def shj_leaf_lines() -> List[str]:
    """`mm_shj`: A_FaceTarget's shadow draws (see the module docstring)"""
    return ["mm_shj:",
            "    hex.zero 4, md_jit",
            "    hex.if0 1, mt_pl, shj_out",
            f"    hex.if0 {M}, p_inv, shj_out",
            "    hex.inc 2, mm_rng",
            "    shj.lookup md_jit, mm_rng",
            "    hex.inc 2, mm_rng",
            "  shj_out:",
            "    stl.fret mm_shjret"]


def missile_lines() -> List[str]:
    """pj_spawn_leaf after the aim (pw_ang): P_SpawnMissile's shadow turn"""
    return ["    hex.if0 1, mt_pl, pj_shn",
            f"    hex.if0 {M}, p_inv, pj_shn",
            "    hex.inc 2, mm_rng",
            "    shm.lookup pw_shm, mm_rng",
            "    hex.inc 2, mm_rng",
            "    hex.add 3, pw_ang + 5*dw, pw_shm",                  # (a - b) << 20: the angle's top 12 bits
            "  pj_shn:"]


# ---- the tables -----------------------------------------------------------------------------------------------------
def shj_values() -> List[int]:
    """`shj`: combat.Sites.shadow_face (2 draws, D10's outcome_table_k), 16-bit two's complement"""
    from doomfj.combat import outcome_table_k, site_formulas
    k, f = site_formulas(lambda s: 0)["shadow_face"]
    assert k == 2
    return [v & 0xFFFF for v in outcome_table_k(f, 2)]


def shm_values() -> List[int]:
    """`shm`: combat.Sites.shadow_missile >> 20 (P_SubRandom), 12-bit two's complement -- the angle's top 3 nibbles"""
    from doomfj.combat import outcome_table_k, site_formulas
    k, f = site_formulas(lambda s: 0)["shadow_missile"]
    assert k == 2
    out = []
    for v in outcome_table_k(f, 2):
        assert v % (1 << P.MISSILE_SHIFT) == 0
        out.append((v >> P.MISSILE_SHIFT) & 0xFFF)
    return out


def sutr_values() -> List[int]:
    from doomfj import rng as R
    from doomfj.combat import site_formulas
    k, f = site_formulas(lambda s: 0)["suit_leak"]
    assert k == 1
    return R.outcome_table(f)


def tables_fj(powers: Sequence[int]) -> List[str]:
    from doomfj.lut_generator import generate_dispatch_table_fj
    out = []
    if P.INVIS_TYPE in powers:
        out += [generate_dispatch_table_fj("shj", shj_values(), index_nibbles=2, result_nibbles=4),
                generate_dispatch_table_fj("shm", shm_values(), index_nibbles=2, result_nibbles=3)]
    if P.SUIT_TYPE in powers:
        out += [generate_dispatch_table_fj("sutr", sutr_values(), index_nibbles=2, result_nibbles=1)]
    return out
