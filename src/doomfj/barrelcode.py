"""M7 P6 (docs/gp-p67-interface.md 4.3, package C): the WORLD's side of the player mode "full" in fj -- the barrels'
state machine and blasts, the drops, the puffs' callers. The model is `combat`'s `damage_barrel`, `_barrel_set_state`,
`_barrels_phase`, `_radius_attack`, `_line_attack` (a barrel named by the aim) and `_kill_monster`'s drop.

THE INTERFACE (the coordinator places the phase; damagecode and weaponcode call the rest):

    bar_phase / bar_pret     stl.fcall bar_phase, bar_pret -- once per tic, after pj_phase and before fx_phase
                             (world.tic: projectiles, barrels, effects); skipped while `lvdone`
    dmb<b> (dm_ret)          damagecode's dm_go jumps here for dm_id = 1 + nmon + b (the aim's barrel id, 54 + b on
                             E1M1): the reach, the PUFF (projcode's fx_spawn, `fxs_kind`), then damage_barrel; it
                             returns through `stl.fret dm_ret` as a slot stub does
    drop_link<k> / drl_ret   damagecode's slot stub calls it after a kill on dropper k's slot
    drop_take<k> / drt_ret   (package B's pickup) dropper k's item is taken: mdrop 2, unlinked, its rows zeroed
    rt_unlink_lines(t)       (Python) the lines that unlink runtime thing t from its leaf list (projcode's shared
                             `pw_unlink`): a removed runtime barrel, a taken runtime pickup (package B), a taken drop

THE CELLS (persisted; `MODEL_FIELD` names the model's):

    bar_st   2 nibbles x nbar   bar_state (gamedata.STATE_INDEX: S_BAR1 203 .. S_BEXP5 209; 0 removed)
    bar_ti   1 x nbar           bar_tics (1..10)
    bar_hp   2 x nbar           bar_health & 0xFF (8-bit two's complement, saturating at -128)
    rng_wd   2                  rng_world (the stream index; its level start is after the 22 baked phase rolls)
    mdrop    1 x ndrop          mon_drop of dropper k's slot (World.dropper, slot order): 0 none, 1 dropped, 2 taken
    dr_live  2                  the count of mdrop == 1 (a fast skip for the pickup scan)
    bar_solid (1 x nbar) is monstercode's (P3.2b's static blockers); the phase clears it at S_NULL.
Dropper k's runtime thing is row `nt + nmob + k` (nmob = FIREBALL_POOL + FX_POOL, after P5's mobiles): while
mdrop[k] == 1 its thpos_rt row is the corpse's (whole units) and its thss_rt leaf the corpse's, and it is linked in
that leaf's list in index order; otherwise both are 0 and it is in no list.

THE CODE (rule 1: per-barrel and per-slot STUBS, shared leaves):
  * `bar_phase`: per barrel, a stub -- state 0 skips; tics - 1; at 0 the shared `bar_next` (the D4 table `barnext`
    on the state: the next state, its tics, a flag) -- entering S_BEXP4 (A_Explode) runs the blast, S_NULL clears the
    barrel's solid flag (and unlinks a runtime barrel). The cells are read live, so a barrel a blast killed this tic
    with a HIGHER index ticks in the same pass (the model's loop).
  * the blast, P_RadiusAttack: barrel b's stub sets bl_b / bl_px / bl_py, calls the shared `bl_leaf` (1. the living
    player: the Chebyshev distance in 16.16 to the barrel, minus 16, floored -> d < 128 -> line of sight ->
    dp_go with 128 - d; 2. the monster slots in order, one stub each: active, shootable and health > 0 -> the
    integer Chebyshev minus the radius -> LOS -> damagecode's slot stub in BLAST mode), then barrel b's STATIC
    chain: (c, 128 - d) for every other barrel in range, in index order -- every pair's LOS is statically clear
    (asserted against every sight segment, doors in any state), so the list is all there is to it.
  * the LOS: monstersight's `bl_los` (a new entry into P3.2c's segment machinery, P = the barrel).
  * `bd_leaf` (damage_barrel on the window bw_*): alive -> health - damage, saturating at -128 -> ONE rng_world draw
    either way: the killing blow takes S_BEXP with tics 5 - (P_Random() & 3); a non-lethal hit's pain roll
    (painchance 0) never fires. `bdm<c>` copies barrel c in and out.
What the emit-time asserts hold (`check_model_rules`): the barrel's states (no zero-tic or forever state, A_Explode on
exactly one, no clamp on the tics roll), painchance 0, every barrel standing on every skill with the same level-start
cells, the static chain, the damages within dp_go's and dm_go's bounds.

M7 P8a I (`fight`, world.infighting_on; docs/gp-final-plan.md 1.2.2, G-I7): THE BLAST'S SOURCE. `bar_src` (2 nibbles
a barrel, persisted: mon_target's code -- 0 none, 1 the player, 2 + slot) is the source of the first damage that did
NOT kill the barrel and named one (combat.damage_barrel: DOOM's barrel target; the killing blow returns before the
switch): `bd_leaf` records `bd_src` on a non-lethal hit while bar_src is 0. The callers name it -- dmb<b> from the
shot's mode (the player's shot: 1; a monster's bullet or fireball: dm_src), the chain from the exploding barrel's
bar_src. The blast passes bar_src on as the source of all its damage: the player's attacker (dp_src = code - 1 for a
monster, else 0) and each slot's dm_src. A monster's hit on a barrel (damagecode's MONSTER / BULLET modes) skips the
reach; only the BULLET puffs.
"""
from typing import Dict, List, Sequence, Tuple

from doomfj import gamedata as gd
from doomfj.lut_generator import generate_dispatch_table_fj

BAR_FIELDS = (("bar_st", 2), ("bar_ti", 1), ("bar_hp", 2))
MODEL_FIELD = {"bar_st": "bar_state", "bar_ti": "bar_tics", "bar_hp": "bar_health", "rng_wd": "rng_world",
               "mdrop": "mon_drop"}
BARREL_PERSIST = ("bar_st", "bar_ti", "bar_hp", "rng_wd")       # bar_solid is monstercode's (MONSTER_PERSIST)
DROP_PERSIST = ("mdrop", "dr_live")
FIGHT_PERSIST = ("bar_src",)                                    # M7 P8a I (build.FIGHT_PERSIST)
PERSIST = BARREL_PERSIST + DROP_PERSIST                         # the module's whole persisted set (build wires it)
FL_EXPLODE, FL_REMOVE = 1, 2                                    # barnext's nibble 3
TICS_FOREVER = 15


def barrels_on(player_mode: str) -> bool:
    """the ONE rule: barrels, drops and puffs are the player mode "full"'s (world.player_loots if the "loot" fallback
    of docs/gp-p67-interface.md section 2 exists)"""
    from doomfj import world as W
    f = getattr(W, "player_loots", None)
    return f(player_mode) if f else player_mode == "full"


def _info():
    from doomfj.combat import BARREL_INFO
    return BARREL_INFO


def _sidx(name: str) -> int:
    return gd.STATE_INDEX[name]


def barrel_states() -> List[str]:
    """every state a barrel can be in: the spawn loop, then the death sequence"""
    info = _info()
    out = []
    for start in (info.spawnstate, info.deathstate):
        s = start
        while s != gd.S_NULL and s not in out:
            out.append(s)
            s = gd.STATES[s].next
    return out


def barnext_values() -> List[int]:
    """`barnext[state]` (the global STATE_INDEX): P_SetMobjState's step in one lookup -- the next state's index
    (nibbles 0-1), its tics (nibble 2), FL_EXPLODE when the next state's action is A_Explode, FL_REMOVE at S_NULL
    (nibble 3; the whole row is then FL_REMOVE << 12: state and tics 0)"""
    vals = [0] * (max(_sidx(s) for s in barrel_states()) + 1)
    for s in barrel_states():
        nxt = gd.STATES[s].next
        if nxt == gd.S_NULL:
            vals[_sidx(s)] = FL_REMOVE << 12
        else:
            fl = FL_EXPLODE if gd.STATES[nxt].action == "A_Explode" else 0
            vals[_sidx(s)] = _sidx(nxt) | (gd.STATES[nxt].tics << 8) | (fl << 12)
    return vals


# ---- the static facts --------------------------------------------------------------------------------------------
def chain_pairs(w) -> Dict[int, List[Tuple[int, int]]]:
    """{b: [(c, damage)]}: barrel b's blast reaches barrel c (c != b, in index order) with 128 - d -- the model's
    `_radius_attack` third loop with both ends static. Asserted: every such pair's LOS is clear against EVERY sight
    segment (walls, and door / lift / switch lines in any state), so the model's verdict never depends on the tic."""
    from doomfj.combat import BARREL_R, BOMB_DAMAGE
    from doomfj.monstersight import sight_segments
    from doomfj.world import segments_touch
    segs = sight_segments(w)
    out = {}
    for b, t in enumerate(w.barrel_things):
        lst = []
        for c, tc in enumerate(w.barrel_things):
            if c == b:
                continue
            d = max(0, max(abs(tc.x - t.x), abs(tc.y - t.y)) - BARREL_R)
            if d >= BOMB_DAMAGE:
                continue
            p, q = (tc.x, tc.y), (t.x, t.y)
            assert not any(segments_touch(p, q, s["a"], s["b"]) for s in segs), (
                "barrels %d -> %d: a sight segment touches the pair's trace -- the chain is not static" % (b, c))
            lst.append((c, BOMB_DAMAGE - d))
        out[b] = lst
    return out


def droppers(w) -> List[int]:
    """the monster slots that drop an item (World.dropper), in slot order: dropper k is slot droppers(w)[k]"""
    return [m for m in range(w.layout.nmon) if w.dropper[m] is not None]


def level_start_values(w, skill: int) -> dict:
    snap = w.level_start(skill)
    n = len(w.barrel_things)
    return {"bar_st": list(snap.bar_state[:n]), "bar_ti": list(snap.bar_tics[:n]),
            "bar_hp": list(snap.bar_health[:n]), "rng_wd": snap.rng_world}


def check_model_rules(w, skills: Sequence[int] = ()) -> None:
    from doomfj.combat import BARREL_HEALTH_MIN, BOMB_DAMAGE, PLAYER_R
    from doomfj.damagecode import DM_MAX_FULL
    from doomfj.hurtcode import DP_MAX
    info = _info()
    acts = [gd.STATES[s].action for s in barrel_states()]
    assert acts.count("A_Explode") == 1, acts
    assert all(a in (None, "A_Explode") or gd.ACTIONS[a].phase == "sound" for a in acts), acts
    for s in barrel_states():
        assert 0 < gd.STATES[s].tics < TICS_FOREVER and _sidx(s) < 256, (s, gd.STATES[s].tics)
    assert gd.STATES[info.spawnstate].action is None
    assert gd.STATES[info.deathstate].action is None, "the killing blow's P_SetMobjState runs no action"
    assert gd.STATES[info.deathstate].tics - 3 >= 1, "max(1, tics - (P_Random() & 3)) would clamp"
    assert info.painchance == 0, "the barrel's pain roll is drawn and never fires"
    assert 0 < info.spawnhealth < 128 and BARREL_HEALTH_MIN == -128, "bar_hp is 8-bit two's complement"
    assert BOMB_DAMAGE <= DP_MAX and BOMB_DAMAGE <= DM_MAX_FULL and BOMB_DAMAGE < 256
    assert PLAYER_R < 256 and all(r < 256 for r in w.mon_radius[:w.layout.nmon])
    assert 0 < len(w.barrel_things) <= 255
    assert w.layout.nmon + len(w.barrel_things) < 255, "dm_id is two nibbles"
    for sk in skills:
        assert level_start_values(w, sk) == level_start_values(w, skills[0]), (
            "the barrels' level start differs by skill: NEW GAME's lines must be per skill")
    chain_pairs(w)


# ---- the decls ---------------------------------------------------------------------------------------------------
SCRATCH = ["bw_st: hex.vec 2", "bw_ti: hex.vec 1", "bw_hp: hex.vec 2", "bw_dmg: hex.vec 2", "bw_t: hex.vec 3",
           "bw_n: hex.vec 4", "bw_fl: hex.vec 1", "bw_rr: hex.vec 3", "bw_m128: hex.vec 3, %d" % 0xF80,
           "bl_t: hex.vec 8", "bl_ax: hex.vec 8", "bl_ay: hex.vec 8", "bl_cx: hex.vec 4", "bl_r: hex.vec 2",
           "bl_d: hex.vec 4", "bl_r4: hex.vec 4", "bl_c128: hex.vec 4, 128", "bl_ok: hex.vec 1",
           "bl_dmg: hex.vec 2", "bl_tx: hex.vec 4", "bl_ty: hex.vec 4", "dmb_ok: hex.vec 1", "dmb_c: hex.vec 2",
           "dr_t: hex.vec 2", "dr_leaf: hex.vec 3"]
RET_DECLS = ["bar_pret: hex.vec w/4", "bn_ret: hex.vec w/4", "bd_ret: hex.vec w/4", "bdm_ret: hex.vec w/4",
             "bl_ret: hex.vec w/4", "bl_dret: hex.vec w/4", "blm_ret: hex.vec w/4", "dmb_lret: hex.vec w/4",
             "drl_ret: hex.vec w/4", "drt_ret: hex.vec w/4"]


def _vec(name: str, nib: int, vals: Sequence[int]) -> str:
    return "%s: hex.vec %d, %d" % (name, nib * max(1, len(vals)),
                                  sum((v & (16 ** nib - 1)) << (4 * nib * i) for i, v in enumerate(vals)))


def fight_decls(w, values: dict = None) -> List[str]:
    """M7 P8a I: `bar_src` (all 0 at level start; `values` overrides: the harness) and the source registers"""
    v = (values or {}).get("bar_src", [0] * len(w.barrel_things))
    return [_vec("bar_src", 2, v), "bd_src: hex.vec 2", "bl_src: hex.vec 2", "bw_sr: hex.vec 2",
            "dmb_sret: hex.vec w/4", "bl_sp: hex.vec 1"]          # bl_sp: M7 P8a K x I, the blast's kb_sp


def decls(w, boot_skill: int, values: dict = None) -> List[str]:
    """the barrels' and drops' cells at `boot_skill`'s level start (`values` overrides: the harness), the LOS entry's
    registers, the scratch and the return registers"""
    from doomfj.monstersight import BL_LOS_DECLS
    v = dict(level_start_values(w, boot_skill), mdrop=[0] * len(droppers(w)), dr_live=0)
    v.update(values or {})
    out = [_vec(name, nib, v[name]) for name, nib in BAR_FIELDS]
    out += ["rng_wd: hex.vec 2, %d" % v["rng_wd"], _vec("mdrop", 1, v["mdrop"]), "dr_live: hex.vec 2, %d" % v["dr_live"]]
    return out + BL_LOS_DECLS + SCRATCH + RET_DECLS


# ---- the code ----------------------------------------------------------------------------------------------------
def rt_unlink_lines(t: int) -> List[str]:
    """unlink runtime thing `t` (a compile-time index) from the leaf its thss_rt row names -- projcode's ONE
    expansion of sim.leaf_unlink (`pw_unlink`, ~50K words). The rows are left as they are."""
    return ["    hex.set w/4, pw_t, %d" % t, "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * t),
            "    stl.fcall pw_unlink, pw_ulret"]


def _cell(name: str, nib: int, i: int) -> str:
    return "%s + %d*dw" % (name, nib * i)


def damage_lines(nbar: int, fight: bool = False) -> List[str]:
    """`bdm<c>` (stl.fcall bdm<c>, bdm_ret; bw_dmg the damage): barrel c's cells through `bd_leaf`, damage_barrel.
    `fight` (M7 P8a I): bar_src rides the window (bw_sr), and a non-lethal hit records `bd_src` while it is 0"""
    out = []
    for c in range(nbar):
        cells = [(_cell(name, nib, c), "bw_" + name[4:], nib) for name, nib in BAR_FIELDS]
        if fight:
            cells.append((_cell("bar_src", 2, c), "bw_sr", 2))
        out += ["bdm%d:" % c] + ["    hex.mov %d, %s, %s" % (nib, reg, cell) for cell, reg, nib in cells]
        out += ["    stl.fcall bd_leaf, bd_ret"] + ["    hex.mov %d, %s, %s" % (nib, cell, reg) for cell, reg, nib in cells]
        out += ["    stl.fret bdm_ret"]
    info = _info()
    return out + [
        "bd_leaf:",
        "    hex.if0 2, bw_st, bd_out",                                   # removed
        "    hex.if_flags bw_hp + 1*dw, 0xFF00, bd_pos, bd_out",          # health < 0
        "  bd_pos:",
        "    hex.if0 2, bw_hp, bd_out",                                   # health == 0
        "    hex.zero 3, bw_t", "    hex.mov 2, bw_t, bw_hp",              # health 1..127, widened
        "    hex.sub_shifted 3, 2, bw_t, bw_dmg, 0",                       # - damage (<= 255): >= -254
        "    hex.scmp 3, bw_t, bw_m128, bd_sat, bd_ok, bd_ok",
        "  bd_sat:",
        "    hex.mov 3, bw_t, bw_m128",                                    # max(health - damage, -128)
        "  bd_ok:",
        "    hex.mov 2, bw_hp, bw_t",
        "    hex.inc 2, rng_wd",                                           # ONE draw either way
        "    hex.sign 3, bw_t, bd_kill, bd_zp",
        "  bd_zp:",
        "    hex.if0 3, bw_t, bd_kill",
        *(["    hex.if1 2, bw_sr, bd_out",                                # M7 P8a I: the first non-lethal source
           "    hex.mov 2, bw_sr, bd_src"] if fight else []),
        "    ;bd_out",                                                     # the pain roll: painchance 0, never
        "  bd_kill:",                                                      # S_BEXP, tics -= P_Random() & 3
        "    fxrnd.lookup bw_rr, rng_wd",
        "    hex.set 2, bw_st, %d" % _sidx(info.deathstate),
        "    hex.set 1, bw_ti, %d" % gd.STATES[info.deathstate].tics,
        "    hex.sub 1, bw_ti, bw_rr + 2*dw",
        "  bd_out:",
        "    stl.fret bd_ret"]


def blast_lines(w, *, slot_rt: Sequence[int], knock: bool = False, fight: bool = False) -> List[str]:
    """`bl_leaf` (stl.fcall bl_leaf, bl_ret; bl_b, bl_px, bl_py the barrel) -- the player, then the monster slots --
    and its shared pieces `bl_dist`, `bl_mon`. The other barrels are the caller's static chain. `knock` (M7 P8a,
    world.knockback_on; doomfj.knockcode): THE BARREL is the inflictor (kb_on, kb_ix / kb_iy = bl_px / bl_py) of
    every damage the blast deals -- set before dp_go and before each slot's dmg<m> (each damage leaf zeroes kb_on).
    `fight` (M7 P8a I): the blast's SOURCE is `bl_src` (the barrel's bar_src, its stub's): the player's attacker
    (dp_src: a monster's 1 + slot, else 0) and each slot's dm_src"""
    from doomfj.combat import BOMB_DAMAGE, PLAYER_R
    from doomfj.knockcode import inflictor_lines
    # package K: the barrel's z (its floor, knockcode's `kbbz` by bl_b); the source the player who set it off (every
    # barrel before package I's bar_src). With infighting (`fight`) the source is the barrel's bar_src: kb_sp is
    # `bl_sp` = (bl_src == 1), computed once at bl_leaf's top (combat._source_is_player: bar_src[b] == 1)
    kb = inflictor_lines("bl_px", "bl_py", z_lines=["    kbbz.lookup kb_iz, bl_b"], src_player=not fight) if knock else []
    if knock and fight:
        assert kb[-1] == "    hex.zero 1, kb_sp", kb
        kb[-1] = "    hex.mov 1, kb_sp, bl_sp"                         # M7 P8a K x I: the player set it off?
    from doomfj.damagecode import BLAST
    from doomfj.monstercode import cell_nibbles
    n = w.layout.nmon
    assert len(slot_rt) == n
    hn = cell_nibbles(w.schema, "mon_health")
    out = ["bl_leaf:",
           *(["    hex.zero 1, bl_sp",                                       # M7 P8a K x I: bl_sp = bl_src == 1
              "    hex.if_flags bl_src + 1*dw, 1, bl_sp0, bl_sph",          # (the high nibble 0 ...
              "  bl_sph:",
              "    hex.if_flags bl_src, 2, bl_sp0, bl_sp1",                 # ... and the low nibble 1)
              "  bl_sp1:",
              "    hex.set 1, bl_sp, 1",
              "  bl_sp0:"] if knock and fight else []),
           # 1. the player, if alive (World.player_alive: health > 0 and not dead)
           "    hex.if1 1, p_dead, bl_mons",
           "    hex.sign 3, p_hp, bl_mons, bl_pa",
           "  bl_pa:",
           "    hex.if0 3, p_hp, bl_mons",
           "    hex.zero 4, bl_t", "    hex.mov 4, bl_t + 4*dw, bl_px",          # the spot's x << 16
           "    hex.mov 8, bl_ax, viewx", "    hex.sub 8, bl_ax, bl_t", "    hex.abs 8, bl_ax",
           "    hex.mov 4, bl_t + 4*dw, bl_py",
           "    hex.mov 8, bl_ay, viewy", "    hex.sub 8, bl_ay, bl_t", "    hex.abs 8, bl_ay",
           "    hex.cmp 8, bl_ax, bl_ay, bl_pyb, bl_pxb, bl_pxb",
           "  bl_pyb:",
           "    hex.mov 8, bl_ax, bl_ay",
           "  bl_pxb:",
           # (Chebyshev - r << 16) >> 16 == (Chebyshev >> 16) - r: the integer part, then the radius
           "    hex.mov 4, bl_cx, bl_ax + 4*dw",
           "    hex.set 2, bl_r, %d" % PLAYER_R,
           "    stl.fcall bl_dist, bl_dret",
           "    hex.if0 1, bl_ok, bl_mons",
           "    hex.mov 8, bl_qx, viewx", "    hex.mov 8, bl_qy, viewy",
           "    stl.fcall bl_los, bl_lret",
           "    hex.if1 1, sl_hit, bl_mons",
           "    hex.mov 2, dp_dmg, bl_dmg",
           *kb,                                                             # M7 P8a: the barrel inflicts
           *(["    hex.zero 2, dp_src",                                    # M7 P8a I: a monster source names it
              "    hex.if_flags bl_src + 1*dw, 1, bl_pss, bl_psm",         # (bl_src >= 16: a monster)
              "  bl_psm:",
              "    hex.if_flags bl_src, 3, bl_pss, bl_psg",                # 0 none, 1 the player: no attacker
              "  bl_pss:",
              "    hex.mov 2, dp_src, bl_src", "    hex.dec 2, dp_src",
              "  bl_psg:"] if fight else []),
           "    stl.fcall dp_go, dp_ret",
           # 2. the monsters by slot: active, shootable, health > 0
           "  bl_mons:"]
    for m in range(n):
        rt, r = slot_rt[m], w.mon_radius[m]
        L = "blm%d_" % m
        out += ["    hex.if0 1, mon_active + %d*dw, %sn" % (m, L),
                "    hex.if0 1, mon_shootable + %d*dw, %sn" % (m, L),
                "    hex.sign %d, mon_health + %d*dw, %sn, %sp" % (hn, hn * m, L, L),
                "  %sp:" % L,
                "    hex.if0 %d, mon_health + %d*dw, %sn" % (hn, hn * m, L),
                "    hex.mov 4, bl_tx, thpos_rt + %d*dw" % (16 * rt + 4),
                "    hex.mov 4, bl_ty, thpos_rt + %d*dw" % (16 * rt + 12),
                "    stl.fcall bl_mon%d, blm_ret" % r,
                "    hex.if0 1, bl_ok, %sn" % L,
                "    hex.mov 2, dm_dmg, bl_dmg", "    hex.set 1, dm_melee, %d" % BLAST,
                *kb,                                                        # M7 P8a: the barrel inflicts
                *(["    hex.mov 2, dm_src, bl_src"] if fight else []),     # M7 P8a I: the blast's source
                "    stl.fcall dmg%d, dm_ret" % m,
                "  %sn:" % L]
    out += ["    stl.fret bl_ret"]
    # the monster's test, entered by its radius (bl_mon<r>): the integer Chebyshev, the radius, then the LOS from the
    # barrel to its position
    for r in sorted(set(w.mon_radius[:n])):
        assert 0 < r < 128
        out += ["bl_mon%d:" % r, "    hex.set 2, bl_r, %d" % r, "    ;bl_mon"]
    out += ["bl_mon:",
            "    hex.mov 4, bl_ax, bl_tx", "    hex.sub 4, bl_ax, bl_px", "    hex.abs 4, bl_ax",
            "    hex.mov 4, bl_ay, bl_ty", "    hex.sub 4, bl_ay, bl_py", "    hex.abs 4, bl_ay",
            "    hex.cmp 4, bl_ax, bl_ay, bl_myb, bl_mxb, bl_mxb",
            "  bl_myb:",
            "    hex.mov 4, bl_ax, bl_ay",
            "  bl_mxb:",
            "    hex.mov 4, bl_cx, bl_ax",
            "    stl.fcall bl_dist, bl_dret",
            "    hex.if0 1, bl_ok, bl_mout",
            "    hex.zero 4, bl_qx", "    hex.mov 4, bl_qx + 4*dw, bl_tx",
            "    hex.zero 4, bl_qy", "    hex.mov 4, bl_qy + 4*dw, bl_ty",
            "    stl.fcall bl_los, bl_lret",
            "    hex.if0 1, sl_hit, bl_mout",
            "    hex.zero 1, bl_ok",
            "  bl_mout:",
            "    stl.fret blm_ret",
            # d = max(0, cheb - r); bl_ok = d < 128; bl_dmg = 128 - d
            "bl_dist:",
            "    hex.zero 1, bl_ok",
            "    hex.mov 4, bl_d, bl_cx",
            "    hex.zero 4, bl_r4", "    hex.mov 2, bl_r4, bl_r",
            "    hex.sub 4, bl_d, bl_r4",
            "    hex.sign 4, bl_d, bl_d0, bl_dp",
            "  bl_d0:",
            "    hex.zero 4, bl_d",
            "  bl_dp:",
            "    hex.cmp 4, bl_d, bl_c128, bl_din, bl_dout, bl_dout",
            "  bl_din:",
            "    hex.set 1, bl_ok, 1",
            "    hex.set 2, bl_dmg, %d" % BOMB_DAMAGE, "    hex.sub 2, bl_dmg, bl_d",
            "  bl_dout:",
            "    stl.fret bl_dret"]
    return out


def phase_lines(w, *, barrel_rt: Dict[int, int] = None, exit_guard: bool = True, chains=None,
                barrel_vis: Dict[int, int] = None, fight: bool = False) -> List[str]:
    """`bar_phase` (+ the per-barrel stubs) and `bar_next`. `barrel_rt` {barrel: runtime thing}: the barrels drawn
    from the leaf lists (removed: unlinked). `chains` overrides `chain_pairs` (the harness's control).
    `barrel_vis` {barrel: thvis slot} (M7 P6+P7, the integration): a BAKED barrel keeps the vanishable slot every
    tier gives its type (things.vanishable_slots), and package A's thvis layout reads it as `bar_state != 0`
    (monsters.MonsterViews.vis_state) -- so S_NULL zeroes it too. The baked call site itself hides the barrel by
    its state (wall_renderer's `_baked_barrel_site`). `fight` (M7 P8a I): the blast's source is the barrel's bar_src
    (bl_src for bl_leaf, bd_src for the chain)."""
    chains = chain_pairs(w) if chains is None else chains
    barrel_rt = barrel_rt or {}
    barrel_vis = barrel_vis or {}
    out = ["bar_phase:"]
    if exit_guard:
        out.append("    hex.if1 1, lvdone, bar_ph_out")                     # a finished level: the world is frozen
    for b, t in enumerate(w.barrel_things):
        L = "bp%d_" % b
        out += ["    hex.if0 2, bar_st + %d*dw, %sn" % (2 * b, L),
                "    hex.dec 1, bar_ti + %d*dw" % b,
                "    hex.if1 1, bar_ti + %d*dw, %sn" % (b, L),
                "    hex.mov 2, bw_st, bar_st + %d*dw" % (2 * b),
                "    stl.fcall bar_next, bn_ret",
                "    hex.mov 2, bar_st + %d*dw, bw_st" % (2 * b),
                "    hex.mov 1, bar_ti + %d*dw, bw_ti" % b,
                "    hex.if0 1, bw_fl, %sn" % L,
                "    hex.if_flags bw_fl, %d, %srm, %sx" % (1 << FL_EXPLODE, L, L),
                "  %sx:" % L,                                                 # A_Explode: P_RadiusAttack
                "    hex.set 2, bl_b, %d" % b,
                "    hex.set 4, bl_px, %d" % (t.x & 0xFFFF), "    hex.set 4, bl_py, %d" % (t.y & 0xFFFF),
                *(["    hex.mov 2, bl_src, bar_src + %d*dw" % (2 * b)] if fight else []),   # M7 P8a I
                "    stl.fcall bl_leaf, bl_ret"]
        for c, dmg in chains[b]:                                              # 3. the other barrels, static
            out += ["    hex.set 2, bw_dmg, %d" % dmg,
                    *(["    hex.mov 2, bd_src, bar_src + %d*dw" % (2 * b)] if fight else []),
                    "    stl.fcall bdm%d, bdm_ret" % c]
        out += ["    ;%sn" % L,
                "  %srm:" % L,                                                # S_NULL: P_RemoveMobj
                "    hex.zero 1, bar_solid + %d*dw" % b]
        out += ["    hex.zero 2, thvis + %d*2*dw" % barrel_vis[b]] if b in barrel_vis else []
        out += rt_unlink_lines(barrel_rt[b]) if b in barrel_rt else []
        out += ["  %sn:" % L]
    out += ["  bar_ph_out:", "    stl.fret bar_pret",
            "bar_next:",
            "    barnext.lookup bw_n, bw_st",
            "    hex.mov 2, bw_st, bw_n", "    hex.mov 1, bw_ti, bw_n + 2*dw", "    hex.mov 1, bw_fl, bw_n + 3*dw",
            "    stl.fret bn_ret"]
    return out


def shot_lines(w, fight: bool = False) -> List[str]:
    """`dmb<b>` (damagecode's dm_go jumps here; it returns through dm_ret) and `dmb_leaf`: combat._line_attack on a
    barrel -- the reach to its centre, the PUFF (the fist's: S_PUFF3), then damage_barrel (`bdm<b>`). `fight` (M7 P8a
    I): a monster's hit (dm_melee MONSTER / BULLET) skips the reach and only its bullet puffs; the source (bd_src) is
    the player for a shot, dm_src for a monster's hit"""
    from doomfj.combat import MISSILERANGE_U, PUNCH_REACH, SAW_REACH
    from doomfj.projcode import FX_KINDS
    assert PUNCH_REACH != SAW_REACH
    out = []
    from doomfj.damagecode import BULLET, MONSTER
    for b, t in enumerate(w.barrel_things):
        out += ["dmb%d:" % b,
                "    hex.set 4, dm_x, %d" % (t.x & 0xFFFF), "    hex.set 4, dm_y, %d" % (t.y & 0xFFFF),
                "    stl.fcall dmb_leaf, dmb_lret",
                "    hex.if0 1, dmb_ok, dmb%d_r" % b,
                "    hex.mov 2, bw_dmg, dm_dmg",
                *(["    stl.fcall dmb_src, dmb_sret"] if fight else []),             # M7 P8a I: bd_src
                "    stl.fcall bdm%d, bdm_ret" % b,
                "  dmb%d_r:" % b,
                *(["    hex.zero 2, dm_src"] if fight else []),                  # M7 P8a I: as dm_leaf's dm_out
                "    stl.fret dm_ret"]
    return out + [
        *(["dmb_src:",                                                         # M7 P8a I: the hit's source
           "    hex.set 2, bd_src, 1",                                         # a shot: the player
           "    hex.if_flags dm_melee, %d, dmb_s_out, dmb_s_m" % ((1 << MONSTER) | (1 << BULLET)),
           "  dmb_s_m:",
           "    hex.mov 2, bd_src, dm_src",
           "  dmb_s_out:",
           "    stl.fret dmb_sret"] if fight else []),
        "dmb_leaf:",
        "    hex.zero 1, dmb_ok",
        *(["    hex.if_flags dm_melee, %d, dmb_nm, dmb_m" % ((1 << MONSTER) | (1 << BULLET)),   # M7 P8a I
           "  dmb_m:",
           "    hex.set 1, dmb_ok, 1",
           "    hex.if_flags dm_melee, %d, dmb_out, dmb_mb" % (1 << BULLET),           # MONSTER: no puff
           "  dmb_mb:",
           "    hex.mov 4, fxs_x, dm_x", "    hex.mov 4, fxs_y, dm_y", "    hex.mov 2, fxs_dmg, dm_dmg",
           "    hex.set 1, fxs_kind, %d" % FX_KINDS["puff"], "    ;dmb_fx",
           "  dmb_nm:"] if fight else []),
        # the reach (dm_leaf's): melee -> dm_reach, else MISSILERANGE
        "    hex.if0 1, dm_melee, dmb_far",
        "    hex.zero 4, dm_r4", "    hex.mov 2, dm_r4, dm_reach", "    ;dmb_rch",
        "  dmb_far:",
        "    hex.set 4, dm_r4, %d" % MISSILERANGE_U,
        "  dmb_rch:",
        "    hex.mov 4, mt_dx, viewx + 4*dw", "    hex.sub 4, mt_dx, dm_x",
        "    hex.mov 4, mt_dy, viewy + 4*dw", "    hex.sub 4, mt_dy, dm_y",
        "    stl.fcall mt_dist_leaf, mt_ret",
        "    hex.cmp 4, mt_d, dm_r4, dmb_in, dmb_in, dmb_out",
        "  dmb_in:",
        "    hex.set 1, dmb_ok, 1",
        "    hex.mov 4, fxs_x, dm_x", "    hex.mov 4, fxs_y, dm_y", "    hex.mov 2, fxs_dmg, dm_dmg",
        "    hex.set 1, fxs_kind, %d" % FX_KINDS["puff"],
        "    hex.if0 1, dm_melee, dmb_fx",                                     # the fist (reach 64), not the saw
        "    hex.set 2, dmb_c, %d" % PUNCH_REACH,
        "    hex.cmp 2, dm_reach, dmb_c, dmb_fx, dmb_fist, dmb_fx",
        "  dmb_fist:",
        "    hex.set 1, fxs_kind, %d" % FX_KINDS["fistpuff"],
        "  dmb_fx:",
        "    stl.fcall fx_spawn, fx_sret",
        "  dmb_out:",
        "    stl.fret dmb_lret"]


def drop_lines(w, *, nt: int, slot_rt: Sequence[int]) -> List[str]:
    """`drop_link<k>` (damagecode's slot stub, after a kill: dm_x / dm_y still hold the corpse's whole-unit position,
    the stub loaded them from its row) and `drop_take<k>` (the pickup): dropper k's row nt + nmob + k. A drop row is
    ZERO whenever it is not live (level start, and drop_take clears what drop_link wrote), so the link writes only
    the position's integer nibbles and the leaf, and the take clears only those. The leaf-list work is shared
    (`dr_link` / `dr_take`: projcode's pw_link / pw_unlink on dr_t, dr_leaf)."""
    from doomfj.world import FIREBALL_POOL, FX_POOL
    nmob = FIREBALL_POOL + FX_POOL
    out = []
    for k, m in enumerate(droppers(w)):
        d, rt = nt + nmob + k, slot_rt[m]
        assert d < 256, "dr_t is two nibbles"
        out += ["drop_link%d:" % k,
                "    hex.set 1, mdrop + %d*dw, 1" % k,
                "    hex.mov 4, thpos_rt + %d*dw, dm_x" % (16 * d + 4),
                "    hex.mov 4, thpos_rt + %d*dw, dm_y" % (16 * d + 12),
                "    hex.mov 3, dr_leaf, thss_rt + %d*dw" % (16 * rt),
                "    hex.mov 3, thss_rt + %d*dw, dr_leaf" % (16 * d),
                "    hex.set 2, dr_t, %d" % d,
                "    ;dr_link",
                "drop_take%d:" % k,
                "    hex.set 1, mdrop + %d*dw, 2" % k,
                "    hex.mov 3, dr_leaf, thss_rt + %d*dw" % (16 * d),
                "    hex.zero 4, thpos_rt + %d*dw" % (16 * d + 4), "    hex.zero 4, thpos_rt + %d*dw" % (16 * d + 12),
                "    hex.zero 3, thss_rt + %d*dw" % (16 * d),
                "    hex.set 2, dr_t, %d" % d,
                "    ;dr_take"]
    return out + ["dr_link:",
                  "    hex.zero w/4, pw_t", "    hex.mov 2, pw_t, dr_t",
                  "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, dr_leaf",
                  "    stl.fcall pw_link, pw_lkret",
                  "    hex.inc 2, dr_live",
                  "    stl.fret drl_ret",
                  "dr_take:",
                  "    hex.zero w/4, pw_t", "    hex.mov 2, pw_t, dr_t",
                  "    hex.zero w/4, pw_leaf", "    hex.mov 3, pw_leaf, dr_leaf",
                  "    stl.fcall pw_unlink, pw_ulret",
                  "    hex.dec 2, dr_live",
                  "    stl.fret drt_ret"]


def tables_fj() -> List[str]:
    return [generate_dispatch_table_fj("barnext", barnext_values(), index_nibbles=2, result_nibbles=4)]


def restart_lines(w, skill: int, *, nt: int) -> List[str]:
    """NEW GAME / the restart at `skill`: the barrels' level start, rng_wd at its seed after the phase rolls, no
    drops (their rows 0; the leaf lists are the restart's own). bar_solid is monstercode's restart."""
    from doomfj.world import FIREBALL_POOL, FX_POOL
    v = level_start_values(w, skill)
    nd = len(droppers(w))
    first = nt + FIREBALL_POOL + FX_POOL
    out = ["    hex.set %d, %s, %d" % (nib * len(v[name]), name, sum((x & (16 ** nib - 1)) << (4 * nib * i)
                                                                       for i, x in enumerate(v[name])))
           for name, nib in BAR_FIELDS]
    return out + ["    hex.set 2, rng_wd, %d" % v["rng_wd"], "    hex.zero %d, mdrop" % max(1, nd),
                  "    hex.zero 2, dr_live",
                  "    hex.zero %d, thpos_rt + %d*dw" % (16 * nd, 16 * first),
                  "    hex.zero %d, thss_rt + %d*dw" % (16 * nd, 16 * first)]


def barrel_parts(w, *, nt: int, slot_rt: Sequence[int], boot_skill: int, skills: Sequence[int] = (),
                 barrel_rt: Dict[int, int] = None, exit_guard: bool = True, barrel_vis: Dict[int, int] = None,
                 knock: bool = False, fight: bool = False) -> dict:
    """everything package C's sim adds, for the World `w` (the player mode "full"):
      * `decls`: the cells at `boot_skill`'s level start, the scratch, the LOS entry's registers;
      * `lines`: bar_phase / bar_next, bdm<c> / bd_leaf, bl_leaf / bl_mon / bl_dist, monstersight's bl_los, dmb<b> /
        dmb_leaf, drop_link<k> / drop_take<k> -- leaves (each ends in a fret), placed where nothing falls in;
      * `tables`: barnext;
      * `restart`: per skill in `skills`, NEW GAME's lines; `persist`: BARREL_PERSIST + DROP_PERSIST;
      * `nbar` (damagecode's id space), `drops` {slot: k} (damagecode's drop hook), `ndrop`, `drop_first` (the first
        drop row, nt + nmob).
    `slot_rt[m]`: monster slot m's runtime thing; `barrel_rt` {barrel: runtime thing} for the barrels drawn from the
    leaf lists. `fight` (M7 P8a I): bar_src (the module docstring) -- its cell, its NEW GAME line, its persistence. The callers' labels this text READS: viewx / viewy, p_dead / p_hp, dp_go / dp_dmg / dp_ret (hurtcode),
    lvdone, mon_active / mon_shootable / mon_health (P3.1 / P4.2a), bar_solid (P3.2b), thpos_rt / thss_rt, dm_* and
    the slot stubs dmg<m> (damagecode), mt_dx / mt_dy / mt_d / mt_dist_leaf, fx_spawn / fxs_* (projcode, puffs on),
    fxrnd, pw_t / pw_leaf / pw_link / pw_unlink (projcode), the sight machinery sg<k> / sl_seg / SL_DECLS
    (monstersight.near_los_lines) and mm_x / mm_y."""
    from doomfj.combat import PLAYER_R
    from doomfj.monstersight import blast_los_lines
    check_model_rules(w, tuple(skills) or (boot_skill,))
    spots = [(t.x, t.y) for t in w.barrel_things]
    maxr = max([PLAYER_R] + list(w.mon_radius[:w.layout.nmon]))
    from doomfj.world import FIREBALL_POOL, FX_POOL
    return {"decls": decls(w, boot_skill) + (fight_decls(w) if fight else []),
            "lines": (phase_lines(w, barrel_rt=barrel_rt, exit_guard=exit_guard, barrel_vis=barrel_vis, fight=fight)
                      + damage_lines(len(spots), fight=fight)
                      + blast_lines(w, slot_rt=slot_rt, knock=knock, fight=fight) + blast_los_lines(w, spots, maxr)
                      + shot_lines(w, fight=fight)
                      + drop_lines(w, nt=nt, slot_rt=slot_rt)),
            "tables": tables_fj(),
            "restart": [restart_lines(w, sk, nt=nt) + (["    hex.zero %d, bar_src" % (2 * len(spots))] if fight else [])
                        for sk in skills],
            "persist": BARREL_PERSIST + DROP_PERSIST + (FIGHT_PERSIST if fight else ()),
            "nbar": len(spots), "drops": {m: k for k, m in enumerate(droppers(w))}, "ndrop": len(droppers(w)),
            "drop_first": nt + FIREBALL_POOL + FX_POOL}
