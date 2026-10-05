"""M7 P5 -- the fj that HURTS THE PLAYER (docs/gp-p5-interface.md, agent B): P_DamageMobj on the player, the
monsters' attack APPLY path's tables, the health / armor bar, and the red palette. The model it mirrors is
`combat.CombatMixin.damage_player` / `_kill_player`, `_mon_hitscan` / `_mon_melee`, and DOOM's ST_doPaletteStuff.

THE INTERFACE (callers: monsterdecide's `md_attack` in its `full` emission; agent C's fireball impact):

    dp_dmg   2 nibbles   the damage, 1 .. DP_MAX
    stl.fcall dp_go, dp_ret

`dp_go` returns through `stl.fret dp_ret` on EVERY path. combat.damage_player's order, exactly:
  * dead (`p_dead`) or health <= 0 -> nothing (no draw);
  * armor: armortype 1 (green) saves dmg / 3, 2 (blue) dmg / 2 -- ONE D4 table `dpsav` indexed by
    (armortype << 8 | dmg) -- and armor <= saved -> saved = armor, armortype 0; armor -= saved, dmg -= saved;
  * damagecount = min(100, damagecount + dmg) (2 nibbles: 100 + DP_MAX < 256, asserted);
  * health -= dmg (3 nibbles, signed);
  * health <= 0 -> the KILL: p_dead = 1; P_DropWeapon -- the ready weapon's downstate (state, tics, overlay frame)
    with its action A_Lower run at once as DOOM's P_SetPsprite does (wp_sy += LOWERSPEED; at or past the bottom,
    the dead player's weapon stays AT the bottom); then the death state's tics roll: +1 rng_pl;
  * else the pain roll: +1 rng_pl (painchance 255; its outcome moves only the player THING's state, which the fj
    does not hold).
  Either way a hit that lands draws exactly ONE rng_pl.

NOT HERE: the gib choice and the player thing's states (no fj cell holds them), P_DeathThink and the restart (P7),
barrels / nukage / berserk / bonuscount (P6). `combat.damage_player` is the ONLY writer of p_health below its level
start in the "fx" player mode, so `p_hp <= 0` <=> `p_dead` holds on every reachable state; the weapon's A_Lower
"health <= 0 and not dead -> S_NULL psprite" branch is therefore never reached and is not emitted (the weapon
harness's health windows never let the weapon reach the bottom with health <= 0 and p_dead 0).

THE TABLES (all from the model's own sources, `combat.site_formulas` / `half_width_table`, rule 8):
  * `mbul` (3 draws, D10 `outcome_table_k`): a bullet's row = L | dmg -- nibble 0 the damage `(c%5+1)*3`, nibbles
    1-2 = L >> 4 where L = 16 * #{q : HWT[q] >= |a-b|}. HWT is non-increasing (asserted), so `dist < L` <=>
    `dist >> 4 < #{...}` <=> `dist < 2048 and |spread| <= HWT[dist >> 4]`: _mon_hitscan's test in ONE 3-nibble
    compare (mt_d's nibbles 1-3 against the row's nibbles 1-3, nibble 3 kept 0);
  * `trclaw` / `sgbite` (1 draw): A_TroopAttack's claw `(v%8+1)*3`, A_SargAttack's bite `(v%10+1)*4`;
  * `dpsav`: the armor's save; `palidx`: damagecount -> the red PLAYPAL index (0 = none, else
    STARTREDPALS + min(NUMREDPALS - 1, (dc + 7) >> 3)) -- so damage shows 0 and 2..8, never 1 ((dc + 7) >> 3 >= 1
    for dc >= 1, DOOM's own arithmetic); playpal1 is emitted for the interface (k = 0..8) and never sent.

THE BAR (`hp_bar`, every tic, after the monsters): max(0, p_hp) and p_ar into hud_v + 3..5 / 6..8 through
weaponcode's `ammobcd` (the same digits table the ammo uses).

THE TIC (`hp_tic`, the player phase, after the weapon): damagecount -= 1 when not 0 (combat._player_phase and
_death_think both run it).

THE PALETTE (`pal_lines`, after the tic and BEFORE `present.begin_frame_collines` -- never inside the record
stream): palidx[p_dc] against `pal_cur`; only on a change `present.set_palette playpal<k>` and pal_cur = k.
`pal_menu_lines`: a menu frame forces palette 0 (again only when pal_cur is not 0). ⚠ The change-only test holds
only if nothing else re-sends the palette per frame: the M1 reset re-enters at `__hot_end`, ahead of the main
part's `present.init_screen` / `present.set_palette palette` -- and `init_screen` ZEROES the device's palette
(ScreenIO._init_screen). Those two lines must move to the boot-only entry part (beside the window chrome) when
these lines are spliced, or the device shows playpal 0 again every frame after the first change. (M7 P5 integration:
done -- wall_renderer's `_boot_screen`, for the game-screen tier.)
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.lut_generator import generate_dispatch_table_fj

# the player modes whose monsters HURT the player (world.PLAYER_MODES; "fx" arrives with agent A's model work)
HURT_PLAYER_MODES = ("fx", "full")
DP_MAX = 155                        # the largest damage dp_go takes: damagecount + dmg stays one byte
DC_CAP = 100                        # P_DamageMobj: damagecount capped at 100
STARTREDPALS, NUMREDPALS = 1, 8     # st_stuff.c
NPALETTES = STARTREDPALS + NUMREDPALS          # playpal0 .. playpal8: the game palette and the red ones (P5)
STARTBONUSPALS, NUMBONUSPALS = 9, 4             # st_stuff.c: the pickup flash, palettes 9 .. 12 (M7 P6)
NPALETTES_LOOT = STARTBONUSPALS + NUMBONUSPALS  # playpal0 .. playpal12 (lootcode: the "full" player)
# (cell, schema field, nibbles): the player's hurt cells (world.build_schema's widths, asserted in hurt_decls)
CELLS = (("p_hp", "p_health", 3), ("p_ar", "p_armor", 2), ("p_at", "p_armortype", 1), ("p_dc", "p_damagecount", 2),
         ("p_dead", "p_dead", 1))
# the PERSISTENT cells (the M1 reset must leave them alone -- like weaponcode.PERSIST)
PERSIST = tuple(c for c, _f, _n in CELLS) + ("pal_cur",)
assert DC_CAP + DP_MAX < 256


def hurt_on(player_mode: str) -> bool:
    return player_mode in HURT_PLAYER_MODES


# ---- the tables -------------------------------------------------------------------------------------------------
def armor_saved(armortype: int, dmg: int) -> int:
    """combat.damage_player's `saved` before the armor cap: green 1/3, blue 1/2, none 0"""
    return dmg // 3 if armortype == 1 else dmg // 2 if armortype == 2 else 0


def dpsav_values() -> List[int]:
    """`dpsav`, indexed armortype << 8 | dmg"""
    return [armor_saved(i >> 8, i & 0xFF) for i in range(3 << 8)]


def red_palette(dc: int) -> int:
    """ST_doPaletteStuff's palette for a damagecount (no berserk, no bonus: P6)"""
    if not dc:
        return 0
    return STARTREDPALS + min(NUMREDPALS - 1, (dc + 7) >> 3)


def palidx_values() -> List[int]:
    return [red_palette(dc) for dc in range(256)]


def berserk_red(strength: int) -> int:
    """M7 P6: the red palette berserk alone asks for -- `red_palette(12 - (strength >> 6))` while strength runs and
    that count is positive, else 0. red_palette is monotone in the count, so ST_doPaletteStuff's
    red_palette(max(dc, 12 - (str >> 6))) is max(red_palette(dc), berserk_red(str)) -- what `pal_lines(loot=True)`
    computes, by strength's nibbles 2 and 3: str < 256 -> count 9..12 -> 3; 256 <= str < 768 -> count 1..8 -> 2."""
    if not strength:
        return 0
    cnt = 12 - (strength >> 6)
    return red_palette(cnt) if cnt > 0 else 0


def bonus_palette(bc: int) -> int:
    """M7 P6: ST_doPaletteStuff's gold palette for a bonus count (shown only when no red one is)"""
    return min(NUMBONUSPALS - 1, (bc + 7) >> 3) + STARTBONUSPALS if bc else 0


def bonpal_values() -> List[int]:
    return [bonus_palette(bc) for bc in range(256)]


def loot_palette(dc: int, strength: int, bc: int) -> int:
    """M7 P6: the palette `pal_lines(loot=True)` computes, in its own steps (the host test holds it to
    combat.palette_index over every strength)"""
    red = max(red_palette(dc), berserk_red(strength))
    return red if red else bonus_palette(bc)


def check_hwt(hwt: Sequence[int]) -> None:
    """the fold's preconditions: HWT covers the bullets' 2048 range in 16-unit buckets and never widens"""
    from doomfj.combat import HWT_SHIFT, MISSILERANGE_U
    assert len(hwt) << HWT_SHIFT == MISSILERANGE_U == 2048 and HWT_SHIFT == 4, (len(hwt), HWT_SHIFT)
    assert all(hwt[q] >= hwt[q + 1] for q in range(len(hwt) - 1)), "HWT is not monotone non-increasing"


def bullet_reach(hwt: Sequence[int], spread: int) -> int:
    """L: the bullet hits iff dist < L (16 * the buckets whose half-width admits |spread|)"""
    return 16 * sum(1 for v in hwt if v >= abs(spread))


def bullet_row(hwt: Sequence[int], spread: int, dmg: int) -> int:
    assert 0 < dmg < 16, dmg
    return bullet_reach(hwt, spread) | dmg


def bullet_fields(row: int):
    """(L, dmg)"""
    return row & ~0xF, row & 0xF


def mbul_values(hwt: Sequence[int], fold=None) -> List[int]:
    """`mbul`: combat.site_formulas' `mon_bullet` (spread, damage), folded with HWT; `fold` replaces the fold (the
    host test's negative control)"""
    from doomfj.combat import outcome_table_k, site_formulas
    check_hwt(hwt)
    k, f = site_formulas(lambda s: 0)["mon_bullet"]
    assert k == 3
    fold = fold or (lambda spread, dmg: bullet_row(hwt, spread, dmg))
    return outcome_table_k(lambda a, b, c: fold(*f(a, b, c)), 3)


def one_draw_values(site: str) -> List[int]:
    """`trclaw` (troop_claw) / `sgbite` (sarg_bite): combat.site_formulas' 1-draw damage"""
    from doomfj.combat import site_formulas
    k, f = site_formulas(lambda s: 0)[site]
    assert k == 1
    return R.outcome_table(f)


ATTACK_TABLES = {"trclaw": "troop_claw", "sgbite": "sarg_bite"}


def tables_fj(hwt: Sequence[int], loot: bool = False) -> List[str]:
    """every D4 table P5's hurt code reads: mbul, trclaw, sgbite, dpsav, palidx; `loot` (M7 P6): and bonpal"""
    out = [generate_dispatch_table_fj("mbul", mbul_values(hwt), index_nibbles=2, result_nibbles=3)]
    for label, site in ATTACK_TABLES.items():
        vals = one_draw_values(site)
        assert max(vals) <= DP_MAX
        out.append(generate_dispatch_table_fj(label, vals, index_nibbles=2, result_nibbles=2))
    out.append(generate_dispatch_table_fj("dpsav", dpsav_values(), index_nibbles=3, result_nibbles=2))
    out.append(generate_dispatch_table_fj("palidx", palidx_values(), index_nibbles=2, result_nibbles=1))
    if loot:
        out.append(generate_dispatch_table_fj("bonpal", bonpal_values(), index_nibbles=2, result_nibbles=1))
    return out


def palette_tables_fj(sprite_wad, boot_wad=None, n: int = NPALETTES) -> List[str]:
    """PLAYPAL 0..n-1 as device data `playpal<k>` (texturecompiler.compile_palette). The shipped `palette` comes from
    the map wad, which holds ONE palette; the sprite wad holds all 14 -- `boot_wad`'s palette 0 must equal it. M7 P6:
    `n` = NPALETTES_LOOT adds the gold ones, 9..12."""
    from doomfj.texturecompiler import compile_palette
    if boot_wad is not None:
        assert boot_wad.playpal(0) == sprite_wad.playpal(0), "playpal0 is not the boot palette"
    assert len(sprite_wad.get_data("PLAYPAL")) >= 768 * n, (
        "the wad holds fewer than 9 palettes" if n == NPALETTES else "the wad holds fewer than %d palettes" % n)
    return [compile_palette("playpal%d" % k, sprite_wad, index=k) for k in range(n)]


# ---- the cells --------------------------------------------------------------------------------------------------
def level_start(w) -> Dict[str, int]:
    """the hurt cells' level-start values from a World (any skill: the player's start does not depend on it)"""
    from doomfj.monstercode import cell_nibbles
    ws = w.ws
    out = {}
    for cell, field, nib in CELLS:
        assert cell_nibbles(w.schema, field) == nib, (field, cell_nibbles(w.schema, field), nib)
        out[cell] = getattr(ws, field) & (16 ** nib - 1)
    out["pal_cur"] = red_palette(ws.p_damagecount)
    return out


def hurt_decls(start: Dict[str, int]) -> List[str]:
    """the cells (at `start`, `level_start`'s dict), the interface and the scratch"""
    return ([f"{cell}: hex.vec {nib}, {start[cell]}" for cell, _f, nib in CELLS]
            + [f"pal_cur: hex.vec 1, {start['pal_cur']}", "pal_new: hex.vec 1",
               "dp_dmg: hex.vec 2", "dp_ret: hex.vec w/4", "dp_si: hex.vec 3", "dp_sv: hex.vec 2", "dp_d: hex.vec 2",
               "dp_c100: hex.vec 2, %d" % DC_CAP, "hp_v: hex.vec 3", "hp_bcd: hex.vec 3",
               # md_attack's full emission (monsterdecide.attack_leaf_lines(full=True)): the bullet row (nibble 3
               # is never written: the reach compare reads it as 0), the attack sight, the bullets' fcall register
               "md_row: hex.vec 4", "md_seen: hex.vec 1", "md_bret: hex.vec w/4"])


def restart_lines(start: Dict[str, int]) -> List[str]:
    """NEW GAME: every persistent hurt cell back to its level start (pal_cur too: the palette lines re-send)"""
    out = [f"hex.set {nib}, {cell}, {start[cell]}" for cell, _f, nib in CELLS]
    return out + [f"hex.set 1, pal_cur, {start['pal_cur']}"]


# ---- the code ---------------------------------------------------------------------------------------------------
def dp_lines() -> List[str]:
    """`dp_go` (stl.fcall dp_go, dp_ret): combat.damage_player -- the module docstring's order"""
    from doomfj import weaponcode as WC
    states, frames = WC.weapon_states(), WC.overlay_frames()
    idx = {s: i for i, s in enumerate(states)}
    out = ["// M7 P5 (doomfj.hurtcode): P_DamageMobj on the player",
           "dp_go:",
           "    hex.if1 1, p_dead, dp_out",
           "    hex.sign 3, p_hp, dp_out, dp_pos",                  # health < 0
           "  dp_pos:",
           "    hex.if0 3, p_hp, dp_out",                          # health == 0
           "    hex.mov 2, dp_d, dp_dmg",
           "    hex.if0 1, p_at, dp_dc",
           "    hex.mov 2, dp_si, dp_dmg", "    hex.mov 1, dp_si + 2*dw, p_at",
           "    dpsav.lookup dp_sv, dp_si",                         # saved = dmg/3 (green) | dmg/2 (blue)
           "    hex.cmp 2, p_ar, dp_sv, dp_ex, dp_ex, dp_ar",       # armor <= saved: it is used up
           "  dp_ex:",
           "    hex.mov 2, dp_sv, p_ar", "    hex.zero 1, p_at",
           "  dp_ar:",
           "    hex.sub 2, p_ar, dp_sv", "    hex.sub 2, dp_d, dp_sv",
           "  dp_dc:",
           "    hex.add 2, p_dc, dp_d",                             # damagecount + dmg < 256 (DC_CAP + DP_MAX)
           "    hex.cmp 2, p_dc, dp_c100, dp_hp, dp_hp, dp_cap",
           "  dp_cap:",
           "    hex.set 2, p_dc, %d" % DC_CAP,
           "  dp_hp:",
           "    hex.sub_shifted 3, 2, p_hp, dp_d, 0",               # health -= dmg
           "    hex.inc 2, rng_pl",                                 # the pain roll, or the death's tics roll
           "    hex.sign 3, p_hp, dp_kill, dp_hz",
           "  dp_hz:",
           "    hex.if0 3, p_hp, dp_kill",
           "    ;dp_out",
           # ---- P_KillMobj on the player: dead; P_DropWeapon -- the ready weapon's downstate, A_Lower at once ----
           "  dp_kill:",
           "    hex.set 1, p_dead, 1"]
    out += WC._by_ready("dpk", {w: "dpk_w%d" % w for w in WC.WEAPONS})
    for w in WC.WEAPONS:
        down = gd.WEAPONINFO[w].downstate
        st = gd.STATES[down]
        assert st.action == "A_Lower" and 0 < st.tics < 15, (down, st.action, st.tics)
        out += ["  dpk_w%d:" % w, "    hex.set 2, wp_st, %d" % idx[down], "    hex.set 1, wp_tics, %d" % st.tics,
                "    hex.set 1, wp_frm, %d" % frames.index(WC.psprite_lump(down)), "    ;dpk_lower"]
    out += ["  dpk_lower:",
            "    hex.add_constant 2, wp_sy, %d" % WC.LOWER,
            "    hex.cmp 2, wp_sy, wp_bottom_c, dp_out, dpk_bt, dpk_bt",
            "  dpk_bt:",
            "    hex.set 2, wp_sy, %d" % WC.BOTTOM,                   # the dead player's weapon stays down
            "  dp_out:",
            "    stl.fret dp_ret"]
    return out


def hp_tic_lines() -> List[str]:
    """the player phase's damagecount fade (after the weapon tic): -1 a tic down to 0"""
    return ["hex.if0 2, p_dc, hpt_end", "hex.dec 2, p_dc", "hpt_end:"]


def hp_bar_lines() -> List[str]:
    """the bar's health (max(0, p_hp)) and armor digits into hud_v + 3..5 and 6..8 (weaponcode's `ammobcd`)"""
    return ["hex.sign 3, p_hp, hb_neg, hb_pos",
            "hb_neg:", "hex.zero 3, hp_v", ";hb_set",
            "hb_pos:", "hex.mov 3, hp_v, p_hp",
            "hb_set:", "ammobcd.lookup hp_bcd, hp_v", "hex.mov 3, hud_v + 3*dw, hp_bcd",
            "hex.zero 1, hp_v + 2*dw", "hex.mov 2, hp_v, p_ar",
            "ammobcd.lookup hp_bcd, hp_v", "hex.mov 3, hud_v + 6*dw, hp_bcd"]


def pal_lines(loot: bool = False) -> List[str]:
    """the frame's palette: palidx[p_dc]; only a change sends `present.set_palette playpal<k>`. `loot` (M7 P6, the
    "full" player): ST_doPaletteStuff with berserk and the bonus -- the red one is the larger of palidx[p_dc] and
    berserk's (`berserk_red`, by p_str's nibbles 2 and 3), else the gold bonpal[p_bc]."""
    npal = NPALETTES_LOOT if loot else NPALETTES
    tg = ["pl_k%d" % k if k < npal else "pl_out" for k in range(16)]
    out = ["palidx.lookup pal_new, p_dc"]
    if loot:
        assert [berserk_red(v) for v in (1, 255, 256, 767, 768, 4095, 4096)] == [3, 3, 2, 2, 0, 0, 0]
        out += ["hex.if0 4, p_str, pl_bz",
                "hex.if0 1, p_str + 3*dw, pl_b0", ";pl_bz",                 # str >= 4096: none
                "pl_b0:",
                "hex.if_flags p_str + 2*dw, 0x0006, pl_b2, pl_bk2",         # nibble 2 in {1, 2}: count 1..8 -> 2
                "pl_b2:",
                "hex.if0 1, p_str + 2*dw, pl_bk3", ";pl_bz",                # nibble 2 = 0: count 9..12 -> 3
                "pl_bk3:", "hex.set 1, pal_bk, 3", ";pl_bmax",
                "pl_bk2:", "hex.set 1, pal_bk, 2",
                "pl_bmax:",
                "hex.cmp 1, pal_new, pal_bk, pl_bset, pl_bz, pl_bz",
                "pl_bset:", "hex.mov 1, pal_new, pal_bk",
                "pl_bz:",
                "hex.if0 1, pal_new, pl_gold", ";pl_have",
                "pl_gold:", "bonpal.lookup pal_new, p_bc",
                "pl_have:"]
    out += ["hex.cmp 1, pal_new, pal_cur, pl_chg, pl_out, pl_chg",
           "pl_chg:",
           "hex.mov 1, pal_cur, pal_new",
           "sim.jump16 pal_new, " + ", ".join(tg)]
    for k in range(npal):
        out += ["pl_k%d:" % k, "present.set_palette playpal%d" % k, ";pl_out"]
    return out + ["pl_out:"]


def pal_menu_lines() -> List[str]:
    """a menu frame: palette 0 (sent only when another one is up)"""
    return ["hex.if0 1, pal_cur, plm_out", "hex.zero 1, pal_cur", "present.set_palette playpal0", "plm_out:"]


def hurt_parts(w, *, sprite_wad, boot_wad=None, loot: bool = False) -> dict:
    """everything P5's hurt code adds, for the World `w` (the level start of the player cells):
      * `decls`: the cells, interface and scratch (`hurt_decls`);
      * `tables`: mbul, trclaw, sgbite, dpsav, palidx, and playpal0..8 (device data);
      * `leaves`: dp_go -- a leaf (every path frets), placed where nothing falls in;
      * `tic`: the damagecount fade, right after the weapon tic (weaponcode's `wp_end`);
      * `bar`: hp_bar, after the monsters' tic (the damage), anywhere before the bar is drawn;
      * `palette`: after the tic, before `present.begin_frame_collines`; `menu_palette`: in the menu block;
      * `restart`: NEW GAME's values; `persist`: the cells the M1 reset must leave alone.
    `loot` (M7 P6, lootcode.LOOT_PLAYER_MODES): the palette with berserk and the bonus (pal_bk, bonpal, playpal9..12);
    the program must then hold lootcode's p_str and p_bc."""
    start = level_start(w)
    return {"decls": hurt_decls(start) + (["pal_bk: hex.vec 1"] if loot else []),
            "tables": tables_fj(w.hwt, loot) + palette_tables_fj(sprite_wad, boot_wad,
                                                                 NPALETTES_LOOT if loot else NPALETTES),
            "leaves": dp_lines(), "tic": hp_tic_lines(), "bar": hp_bar_lines(), "palette": pal_lines(loot),
            "menu_palette": pal_menu_lines(), "restart": restart_lines(start), "persist": PERSIST, "start": start}
