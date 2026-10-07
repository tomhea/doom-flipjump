"""M7 P3.2c "decide" (docs/gp-monsters.md 8.5): the fj the attack decisions need -- shared leaves over the move's
context (`monstermove.P32B_CONTEXT`) plus a few cells (`P32C_CONTEXT`):

  * `mm_todist`: mt_dx, mt_dy = the player's integer position - (mm_x, mm_y); mt_d = P_AproxDistance (mt_dist_leaf,
    which also leaves |dx|, |dy| in mt_ax, mt_ay);
  * `mm_octant`: mm_fa = `world.octant_of(mt_dx, mt_dy)` -- A_FaceTarget's facing;
  * `mm_as`: mm_asr = the ATTACK sight (`sight.attack_sight`): seen, or within NEAR and the exact LOS (`sl_los`,
    doomfj.monstersight) -- computed once per A_Chase or attack (`mm_asok` caches it: the sight is pure);
  * `mm_decide`: A_Chase after the turn (world._a_chase): justattacked -> clear it, P_NewChaseDir, done; else the
    melee decision (a melee state, distance < MELEE_REACH, the attack sight), else the missile decision (a missile
    state, movecount 0, the attack sight, reaction 0, then the roll: P_Random < min(dist - bias, cap) refuses), else
    the move (`mm_chase`). A decision faces the player (the attack state's A_FaceTarget) and sets mm_dec (1 melee,
    2 missile) for the slot to enter the state; the missile decision sets justattacked. `justhit` is 0 until damage
    (P4) and is read only by `decide_leaf_lines(justhit=True)` (M7 P4.2a: `mm_jh`, world._check_missile_range --
    after the attack sight, a set justhit is cleared and decides the missile with no roll);
  * `md_attack`: an attack state's action in the decide mode (combat._attack_rolls): A_FaceTarget's facing, then
    every draw the full model's attack takes from the monster's stream -- 3 per bullet, the claw's and the bite's
    one each when in melee range with the attack sight -- and no effect (P5). M7 P5's `full` emission applies them
    (attack_leaf_lines: the bullets' hits, the claw and the bite through doomfj.hurtcode's dp_go, the imp's fireball).

M7 P8a I (docs/gp-final-plan.md 1.2.2 / 1.2.3; `fight`, world.infighting_on -- off, every text is P7's to the byte):
THE TARGET. A slot loads its `mon_target` (0 none, 1 the player, 2 + slot) into `mm_tg` and calls `mt_load`
(`target_load_lines`): the player in one nibble test, a monster by a two-level jump to its slot's copy-stub -- out come
the target's 16.16 position (mt_tqx / mt_tqy: the player's viewx / viewy, a monster's whole units), `mt_pl` (the player),
`mt_al` (world.target_alive: not p_dead, or the monster's mon_shootable -- damage keeps it == active and health > 0),
its melee reach `mt_reach` (MELEE_BASE + its radius) and its radius class `mt_rc` (RC). Every leaf above then reads
the TARGET: mm_todist, the melee reach, mm_as (the player: seen, or the near trace; a monster: `sl_far`, the exact LOS
at any range, monstersight.far_los_lines -- O-B2), md_attack (the claw and the bite land on the target: dp_go, or
damagecode's dm_go in its MONSTER mode; the fireball is aimed at mt_tq), and monstermove's P_NewChaseDir.
THE BULLETS (O-B5, combat._mon_hitscan / _bullet_victim): md_hs takes the target's angle once (`ia_leaf`, the ONE
point_to_angle the attacks share), and each bullet first scans the things in the way (`hs_scan`: the player, the
monster slots, the standing barrels -- each a copy-stub into the shared `hs_cand`: nearer than the best so far, under
MISSILERANGE, not the shooter, then its offset from the bullet's line within its width, `hs_wid` on the `hwtr` table)
before the target's own rule; the victim's code less one is dm_go's id (a monster's 1 + slot, a barrel's 1 + nmon + b).
"""
from typing import List

from doomfj import gamedata as gd

P32C_FIELDS = ("mon_justattacked",)

# md_attack's kinds (mm_kind), one per attack action the decide mode runs
ATTACK_KINDS = {"A_FaceTarget": 0, "A_PosAttack": 1, "A_SPosAttack": 2, "A_TroopAttack": 3, "A_SargAttack": 4}

# M7 P8a I: the radius classes the bullets' width table `hwtr` is indexed by (rc << 8 | distance >> 4)
RC = {16: 0, 20: 1, 30: 2, 10: 3}
DM_MONSTER, DM_BULLET = 3, 4          # damagecode's dm_melee for a monster's hit: no reach, no blood / with blood
# the fight's registers (not persisted; the scan's are scratch between two calls)
FIGHT_DECLS = ["mm_tg: hex.vec 2", "mt_tqx: hex.vec 8", "mt_tqy: hex.vec 8", "mt_pl: hex.vec 1", "mt_al: hex.vec 1",
               "mt_rc: hex.vec 1", "mt_reach: hex.vec 4", "mt_lret: hex.vec w/4",
               "ia_x1: hex.vec 8", "ia_y1: hex.vec 8", "ia_x2: hex.vec 8", "ia_y2: hex.vec 8", "ia_ang: hex.vec 8",
               "ia_ret: hex.vec w/4",
               "md_at: hex.vec 8", "md_td: hex.vec 4", "md_me: hex.vec 2", "md_sp: hex.vec 4", "md_c1: hex.vec 2, 1",
               "hs_vic: hex.vec 2", "hs_id: hex.vec 2", "hs_rc: hex.vec 1", "hs_pl: hex.vec 1", "hs_cx: hex.vec 4",
               "hs_cy: hex.vec 4", "hs_bd: hex.vec 4", "hs_d: hex.vec 4", "hs_del: hex.vec 4", "hs_t4: hex.vec 4",
               "hs_t8: hex.vec 8", "hs_ix: hex.vec 3", "hs_hw: hex.vec 4", "hs_in: hex.vec 1",
               "hs_c2048: hex.vec 4, 2048",
               "hs_xlo: hex.vec 4", "hs_xhi: hex.vec 4", "hs_ylo: hex.vec 4", "hs_yhi: hex.vec 4",
               "hs_ret: hex.vec w/4", "hs_cret: hex.vec w/4", "hs_wret: hex.vec w/4"]

P32C_CONTEXT = [
    "mm_ja: hex.vec 1", "mm_seen: hex.vec 1", "mm_mk: hex.vec 1", "mm_re: hex.vec 1",   # in: justattacked, seen,
    "mm_dec: hex.vec 1", "mm_fa: hex.vec 1", "mm_kind: hex.vec 1",          # kinds (1 melee | 2 missile), reaction
    "mm_asok: hex.vec 1", "mm_asr: hex.vec 1",
    "mo_a: hex.vec 6", "mo_b: hex.vec 6", "mo_t: hex.vec 6", "mo_t4: hex.vec 4", "mo_c4: hex.vec 4",
    "mt_c60: hex.vec 4, %d",
    "mm_tdret: hex.vec w/4", "mm_ocret: hex.vec w/4", "mm_asret: hex.vec w/4", "mm_dret: hex.vec w/4",
    "md_ret: hex.vec w/4",
]


def context_decls() -> List[str]:
    from doomfj.world import MELEE_REACH
    return [d % MELEE_REACH if "%d" in d else d for d in P32C_CONTEXT]


def draws() -> dict:
    """the monster stream's draws per attack site, from combat's own formulas (rule 8: one source)"""
    from doomfj.combat import site_formulas
    f = site_formulas(lambda s: 0)
    return {"bullet": f["mon_bullet"][0], "claw": f["troop_claw"][0], "bite": f["sarg_bite"][0]}


def todist_leaf_lines(fight: bool = False) -> List[str]:
    """`mm_todist`: the offset to the player -- M7 P8a I (`fight`): to the TARGET, mt_tq's whole units"""
    x, y = ("mt_tqx + 4*dw", "mt_tqy + 4*dw") if fight else ("viewx + 4*dw", "viewy + 4*dw")
    return ["mm_todist:",
            "    hex.mov 4, mt_dx, %s" % x, "    hex.sub 4, mt_dx, mm_x",
            "    hex.mov 4, mt_dy, %s" % y, "    hex.sub 4, mt_dy, mm_y",
            "    stl.fcall mt_dist_leaf, mt_ret",
            "    stl.fret mm_tdret"]


def _gt0(cell: str, yes: str, no: str, tag: str) -> List[str]:
    """jump to `yes` when the 4-nibble signed `cell` > 0, else `no`"""
    return ["    hex.sign 4, %s, %s, %s_zp" % (cell, no, tag), "  %s_zp:" % tag,
            "    hex.if0 4, %s, %s" % (cell, no), "    ;%s" % yes]


def octant_leaf_lines() -> List[str]:
    """`mm_octant`: world.octant_of on mt_dx, mt_dy (|.| in mt_ax, mt_ay): the axis when |b| * DEN <= |a| * NUM"""
    from doomfj.world import OCTANT_TAN_DEN, OCTANT_TAN_NUM
    assert OCTANT_TAN_DEN == 256 and 0 < OCTANT_TAN_NUM < 256      # a two-nibble shift, a constant multiply
    out = ["mm_octant:"]
    for tag, small, big, axis in (("mo_x", "mt_ay", "mt_ax", "mo_ew"), ("mo_y", "mt_ax", "mt_ay", "mo_ns")):
        out += ["    hex.zero 6, mo_a", "    hex.mov 4, mo_a + 2*dw, %s" % small,
                "    hex.zero 6, mo_t", "    hex.mov 4, mo_t, %s" % big,
                "    hex.mul_const 6, mo_b, mo_t, %d" % OCTANT_TAN_NUM,
                "    hex.cmp 6, mo_a, mo_b, %s, %s, %s_no" % (axis, axis, tag),
                "  %s_no:" % tag]
    out += ["    ;mo_dg",
            "  mo_ew:", "    hex.sign 4, mt_dx, mo_w, mo_e",
            "  mo_w:", "    hex.set 1, mm_fa, %d" % gd.DI_WEST, "    ;mo_out",
            "  mo_e:", "    hex.set 1, mm_fa, %d" % gd.DI_EAST, "    ;mo_out",
            "  mo_ns:"] + _gt0("mt_dy", "mo_n", "mo_s", "mo_nsg") + [
            "  mo_n:", "    hex.set 1, mm_fa, %d" % gd.DI_NORTH, "    ;mo_out",
            "  mo_s:", "    hex.set 1, mm_fa, %d" % gd.DI_SOUTH, "    ;mo_out",
            "  mo_dg:"] + _gt0("mt_dx", "mo_de", "mo_dw", "mo_dxg") + [
            "  mo_de:"] + _gt0("mt_dy", "mo_ne", "mo_se", "mo_deg") + [
            "  mo_dw:"] + _gt0("mt_dy", "mo_nw", "mo_sw", "mo_dwg")
    for lab, d in (("mo_ne", gd.DI_NORTHEAST), ("mo_se", gd.DI_SOUTHEAST), ("mo_nw", gd.DI_NORTHWEST),
                   ("mo_sw", gd.DI_SOUTHWEST)):
        out += ["  %s:" % lab, "    hex.set 1, mm_fa, %d" % d, "    ;mo_out"]
    return out + ["  mo_out:", "    stl.fret mm_ocret"]


def as_leaf_lines(fight: bool = False) -> List[str]:
    """`mm_as`: the attack sight, once (mm_asok) -- needs mt_d current; mt_c128 is P3.2a's NEAR
    (monstercode.P32A_SCRATCH, from sight.NEAR). M7 P8a I (`fight`): a MONSTER target's is `sl_far` (the exact LOS
    at any range, O-B2; the seen mark and NEAR are the player's)"""
    return ["mm_as:",
            "    hex.if1 1, mm_asok, mm_as_out",
            "    hex.set 1, mm_asok, 1", "    hex.set 1, mm_asr, 1",
            *(["    hex.if0 1, mt_pl, mm_as_far"] if fight else []),
            "    hex.if1 1, mm_seen, mm_as_out",
            "    hex.cmp 4, mt_d, mt_c128, mm_as_nr, mm_as_nr, mm_as_no",      # mt_c128: P3.2a's NEAR
            "  mm_as_nr:",
            "    stl.fcall sl_los, sl_ret",
            "    hex.if0 1, sl_hit, mm_as_out",
            "  mm_as_no:", "    hex.zero 1, mm_asr",
            "  mm_as_out:", "    stl.fret mm_asret",
            *(["  mm_as_far:",
               "    stl.fcall sl_far, sf_ret",
               "    hex.if0 1, sl_hit, mm_as_out",
               "    ;mm_as_no"] if fight else [])]


def decide_leaf_lines(justhit: bool = False, fight: bool = False) -> List[str]:
    """`mm_decide` (stl.fcall mm_decide, mm_dret) -- see the module docstring; the bias and cap are
    world.MISSILE_BIAS / MISSILE_NOMELEE_BIAS / MISSILE_CAP, compared as rand + bias >= min(d, bias + cap).
    `justhit` (M7 P4.2a): the context's `mm_jh` (damagecode declares it) is read and cleared. `fight` (M7 P8a I): the
    melee reach is the TARGET's (mt_reach: MELEE_BASE + its radius) -- the rest reads the target through mm_todist
    and mm_as"""
    from doomfj.world import MISSILE_BIAS, MISSILE_CAP, MISSILE_NOMELEE_BIAS
    reach = "mt_reach" if fight else "mt_c60"
    b1, b2 = MISSILE_BIAS, MISSILE_BIAS + MISSILE_NOMELEE_BIAS
    return ["mm_decide:",
            "    hex.zero 1, mm_dec",
            "    hex.if0 1, mm_ja, mm_dc_m",
            "    hex.zero 1, mm_ja",
            "    stl.fcall mm_ncd, mm_nret",
            "    stl.fret mm_dret",
            "  mm_dc_m:",
            "    hex.zero 1, mm_asok",
            "    stl.fcall mm_todist, mm_tdret",
            "    hex.if_flags mm_mk, 0xA, mm_dc_ms, mm_dc_mr",                    # kinds 1, 3: a melee state
            "  mm_dc_mr:",
            "    hex.cmp 4, mt_d, %s, mm_dc_mr2, mm_dc_ms, mm_dc_ms" % reach,
            "  mm_dc_mr2:",
            "    stl.fcall mm_as, mm_asret",
            "    hex.if0 1, mm_asr, mm_dc_ms",
            "    hex.set 1, mm_dec, 1",
            "    ;mm_dc_face",
            "  mm_dc_ms:",
            "    hex.if_flags mm_mk, 0xC, mm_dc_mv, mm_dc_ms1",                   # kinds 2, 3: a missile state
            "  mm_dc_ms1:",
            "    hex.if0 2, mm_mc, mm_dc_ms2",
            "    ;mm_dc_mv",
            "  mm_dc_ms2:",
            "    stl.fcall mm_as, mm_asret",
            "    hex.if0 1, mm_asr, mm_dc_mv",
            *(["    hex.if0 1, mm_jh, mm_dc_rc",                                 # MF_JUSTHIT: clear it, and attack
               "    hex.zero 1, mm_jh",
               "    ;mm_dc_yes",
               "  mm_dc_rc:"] if justhit else []),
            "    hex.if0 1, mm_re, mm_dc_roll",
            "    ;mm_dc_mv",
            "  mm_dc_roll:",
            "    hex.inc 2, mm_rng", "    mrnd.lookup mm_rr, mm_rng",              # P_Random: its value, nibbles 0-1
            "    hex.zero 4, mo_t4", "    hex.mov 2, mo_t4, mm_rr",
            "    hex.if_flags mm_mk, 0xA, mm_dc_b2, mm_dc_b1",
            "  mm_dc_b1:",
            "    hex.add_constant 4, mo_t4, %d" % b1, "    hex.set 4, mo_c4, %d" % (b1 + MISSILE_CAP),
            "    ;mm_dc_cap",
            "  mm_dc_b2:",
            "    hex.add_constant 4, mo_t4, %d" % b2, "    hex.set 4, mo_c4, %d" % (b2 + MISSILE_CAP),
            "  mm_dc_cap:",
            "    hex.cmp 4, mt_d, mo_c4, mm_dc_cd, mm_dc_c2, mm_dc_c2",
            "  mm_dc_cd:", "    hex.mov 4, mo_c4, mt_d",
            "  mm_dc_c2:",
            "    hex.cmp 4, mo_t4, mo_c4, mm_dc_mv, mm_dc_yes, mm_dc_yes",       # rand + bias >= min(d, bias + cap)
            "  mm_dc_yes:",
            "    hex.set 1, mm_dec, 2", "    hex.set 1, mm_ja, 1",
            "  mm_dc_face:",
            "    stl.fcall mm_octant, mm_ocret",
            "    stl.fret mm_dret",
            "  mm_dc_mv:",
            "    stl.fcall mm_chase, mm_cret",
            "    stl.fret mm_dret"]


def attack_leaf_lines(full: bool = False, knock: bool = False, fight: bool = False) -> List[str]:
    """`md_attack` (stl.fcall md_attack, md_ret): mm_kind's action, its facing and its draws (combat.BULLETS
    bullets of 3 draws each for the hitscanners).

    `full` (M7 P5, doomfj.hurtcode; off, the text is P3.2c's to the byte): the draws are APPLIED, as the model's
    `_monster_attack` -- a hitscanner's attack sight once (`md_hs`: p_dead 0 and `mm_as`, combat._mon_hitscan's
    `player_alive() and attack_sight`), then per bullet (`md_bul`) the 3-draw `mbul` row and a hit when seen and
    mt_d < L (the row's nibbles 1-3: hurtcode.mbul_values) -> `dp_go` with the row's damage; the claw and the bite
    (the reach and the attack sight as before) look their 1-draw damage up (`trclaw` / `sgbite`) -> `dp_go`; the
    imp outside melee (out of reach or out of sight: _check_melee_range false) spawns its fireball through
    `stl.fcall pj_spawn, pj_sret` (agent C, doomfj.projcode) with mm_x / mm_y as the monster's position. The
    program must then hold hurtcode's decls (md_row, md_seen, md_bret, dp_dmg), dp_go, the tables and pj_spawn.
    `knock` (M7 P8a, world.knockback_on; doomfj.knockcode): THE ATTACKER (mm_x / mm_y) is the inflictor of each dp_go
    -- the bullets', the claw's, the bite's (dp_go zeroes kb_on on every exit).
    `fight` (M7 P8a I, world.infighting_on; the module docstring): the attacks are at the TARGET (mt_load ran) -- the
    claw and the bite land on a monster target through dm_go (DM_MONSTER: no reach, no blood; dm_src the attacker),
    the bullets meet the things in the way first (`hs_scan`, then the target's own width), a bullet on a monster or a
    barrel goes through dm_go (DM_BULLET: blood, or the barrel's puff)"""
    from doomfj.combat import BULLETS
    from doomfj.knockcode import inflictor_lines
    assert not knock or full, "M7 P8a: the thrust rides the applied attacks"
    assert not fight or full, "M7 P8a I: infighting rides the applied attacks"
    if fight:
        return _fight_attack_lines(knock)
    kb = inflictor_lines("mm_x", "mm_y") if knock else []
    k = draws()
    pos = [ATTACK_KINDS[a] for a in ("A_PosAttack", "A_SPosAttack", "A_TroopAttack", "A_SargAttack")]
    tg = ["md_out"] * 16
    tg[pos[0]], tg[pos[1]], tg[pos[2]], tg[pos[3]] = "md_pos", "md_spos", "md_claw", "md_bite"
    out = ["md_attack:",
           "    hex.zero 1, mm_asok",
           "    stl.fcall mm_todist, mm_tdret",
           "    stl.fcall mm_octant, mm_ocret",
           "    sim.jump16 mm_kind, " + ", ".join(tg)]
    if not full:
        out += ["  md_pos:", "    hex.add_constant 2, mm_rng, %d" % (BULLETS["A_PosAttack"] * k["bullet"]),
                "    ;md_out",
                "  md_spos:", "    hex.add_constant 2, mm_rng, %d" % (BULLETS["A_SPosAttack"] * k["bullet"]),
                "    ;md_out"]
        for lab, n in (("md_claw", k["claw"]), ("md_bite", k["bite"])):
            out += ["  %s:" % lab,
                    "    hex.cmp 4, mt_d, mt_c60, %s_r, md_out, md_out" % lab,
                    "  %s_r:" % lab,
                    "    stl.fcall mm_as, mm_asret",
                    "    hex.if0 1, mm_asr, md_out",
                    "    hex.add_constant 2, mm_rng, %d" % n,
                    "    ;md_out"]
        return out + ["  md_out:", "    stl.fret md_ret"]
    assert (k["bullet"], k["claw"], k["bite"]) == (3, 1, 1), k       # mbul folds 3 draws; trclaw / sgbite one
    for lab, act in (("md_pos", "A_PosAttack"), ("md_spos", "A_SPosAttack")):
        out += ["  %s:" % lab, "    stl.fcall md_hs, md_bret"]
        out += ["    stl.fcall md_bul, md_bret"] * BULLETS[act]
        out += ["    ;md_out"]
    for lab, table, far in (("md_claw", "trclaw", "md_claw_f"), ("md_bite", "sgbite", "md_out")):
        out += ["  %s:" % lab,
                "    hex.cmp 4, mt_d, mt_c60, %s_r, %s, %s" % (lab, far, far),
                "  %s_r:" % lab,
                "    stl.fcall mm_as, mm_asret",
                "    hex.if0 1, mm_asr, %s" % far,
                "    hex.inc 2, mm_rng",
                "    %s.lookup dp_dmg, mm_rng" % table,
                "    hex.mov 2, dp_src, md_src",                  # M7 P7: the attacker (dp_go zeroes dp_src)
                *kb,                                              # M7 P8a: the attacker inflicts
                "    stl.fcall dp_go, dp_ret",
                "    ;md_out"]
    out += ["  md_claw_f:",                                       # A_TroopAttack beyond melee: the fireball
            "    stl.fcall pj_spawn, pj_sret",
            "  md_out:", "    stl.fret md_ret",
            # the hitscan's attack sight, once an attack: a dead player is not shootable
            "  md_hs:",
            "    hex.zero 1, md_seen",
            "    hex.if1 1, p_dead, md_hs_out",
            "    stl.fcall mm_as, mm_asret",
            "    hex.mov 1, md_seen, mm_asr",
            "  md_hs_out:", "    stl.fret md_bret",
            # one bullet: P_Random x 3 folded into its row, then the hit
            "  md_bul:",
            "    hex.inc 2, mm_rng",
            "    mbul.lookup md_row, mm_rng",
            "    hex.add_constant 2, mm_rng, 2",
            "    hex.if0 1, md_seen, md_bul_out",
            "    hex.cmp 3, mt_d + 1*dw, md_row + 1*dw, md_bul_hit, md_bul_out, md_bul_out",   # mt_d < L
            "  md_bul_hit:",
            "    hex.zero 2, dp_dmg", "    hex.mov 1, dp_dmg, md_row",
            "    hex.mov 2, dp_src, md_src",                          # M7 P7: the attacker, every bullet
            *kb,                                                      # M7 P8a: the attacker inflicts
            "    stl.fcall dp_go, dp_ret",
            "  md_bul_out:", "    stl.fret md_bret"]
    return out


def decide_leaves(justhit: bool = False, full: bool = False, knock: bool = False, fight: bool = False) -> List[str]:
    """`full` (M7 P5): md_attack applies its draws (attack_leaf_lines(full=True)); off, P3.2c's text to the byte.
    `knock` (M7 P8a): the attacker is each hit's inflictor (attack_leaf_lines(knock=True)). `fight` (M7 P8a I): the
    TARGET's (the module docstring) -- the program must hold `fight_parts`' lines and monstersight's sl_far"""
    return (todist_leaf_lines(fight) + octant_leaf_lines() + as_leaf_lines(fight) + decide_leaf_lines(justhit, fight)
            + attack_leaf_lines(full, knock, fight))


def type_decide(info) -> dict:
    """a monster type's decide-mode facts: `mk` (1 melee | 2 missile), the states a decision enters (index, tics)
    and the attack actions its attack states run"""
    out = {"mk": 0, "mel": None, "mis": None, "acts": set()}
    for key, bit, st0 in (("mel", 1, info.meleestate), ("mis", 2, info.missilestate)):
        if st0 == gd.S_NULL:
            continue
        st = gd.STATES[st0]
        assert st.action == "A_FaceTarget" and st.tics > 0, (st0, st.action, st.tics)
        out["mk"] |= bit
        out[key] = (gd.STATE_INDEX[st0], st.tics)
        s, seen = st0, set()
        while s != gd.S_NULL and s not in seen and gd.STATES[s].action != "A_Chase":
            seen.add(s)
            a = gd.STATES[s].action
            if a is not None:
                assert a in ATTACK_KINDS, (s, a)
                out["acts"].add(a)
            s = gd.STATES[s].next
    return out


# ---- M7 P8a I: the target, the angle, the bullets' scan (docs/gp-final-plan.md 1.2.2 / 1.2.3) ----------------------
def _fight_attack_lines(knock: bool) -> List[str]:
    """`md_attack` with infighting (attack_leaf_lines(full=True, fight=True)) -- see attack_leaf_lines"""
    from doomfj.combat import BULLETS
    from doomfj.knockcode import inflictor_lines
    kb = inflictor_lines("mm_x", "mm_y") if knock else []
    k = draws()
    assert (k["bullet"], k["claw"], k["bite"]) == (3, 1, 1), k
    pos = [ATTACK_KINDS[a] for a in ("A_PosAttack", "A_SPosAttack", "A_TroopAttack", "A_SargAttack")]
    tg = ["md_out"] * 16
    tg[pos[0]], tg[pos[1]], tg[pos[2]], tg[pos[3]] = "md_pos", "md_spos", "md_claw", "md_bite"
    out = ["md_attack:",
           "    hex.zero 1, mm_asok",
           "    stl.fcall mm_todist, mm_tdret",
           "    stl.fcall mm_octant, mm_ocret",
           "    sim.jump16 mm_kind, " + ", ".join(tg)]
    for lab, act in (("md_pos", "A_PosAttack"), ("md_spos", "A_SPosAttack")):
        out += ["  %s:" % lab, "    stl.fcall md_hs, md_bret"]
        out += ["    stl.fcall md_bul, md_bret"] * BULLETS[act]
        out += ["    ;md_out"]
    for lab, table, far in (("md_claw", "trclaw", "md_claw_f"), ("md_bite", "sgbite", "md_out")):
        out += ["  %s:" % lab,
                "    hex.cmp 4, mt_d, mt_reach, %s_r, %s, %s" % (lab, far, far),
                "  %s_r:" % lab,
                "    stl.fcall mm_as, mm_asret",
                "    hex.if0 1, mm_asr, %s" % far,
                "    hex.inc 2, mm_rng",
                "    %s.lookup dp_dmg, mm_rng" % table,
                "    hex.if0 1, mt_pl, md_mel_m",
                "    hex.mov 2, dp_src, md_src",                  # M7 P7: the attacker (dp_go zeroes dp_src)
                *kb,                                              # M7 P8a: the attacker inflicts
                "    stl.fcall dp_go, dp_ret",
                "    ;md_out"]
    out += ["  md_mel_m:",                                        # a MONSTER target: P_DamageMobj(target, me, me)
            "    hex.mov 2, dm_dmg, dp_dmg",
            "    hex.set 1, dm_melee, %d" % DM_MONSTER,
            "    hex.mov 2, dm_src, md_src", "    hex.inc 2, dm_src",            # the attacker's code: 2 + slot
            "    hex.mov 2, dm_id, mm_tg", "    hex.dec 2, dm_id",              # dm_go's id: 1 + its slot
            *kb,
            "    stl.fcall dm_go, dm_ret",
            "    ;md_out",
            "  md_claw_f:",                                       # A_TroopAttack beyond melee: the fireball
            "    stl.fcall pj_spawn, pj_sret",
            "  md_out:", "    stl.fret md_ret",
            # the hitscan's aim, once an attack: the target alive and in sight, its angle and its distance
            "  md_hs:",
            "    hex.zero 1, md_seen",
            "    hex.if0 1, mt_al, md_hs_out",
            "    stl.fcall mm_as, mm_asret",
            "    hex.mov 1, md_seen, mm_asr",
            "    hex.if0 1, md_seen, md_hs_out",
            "    hex.zero 4, ia_x1", "    hex.mov 4, ia_x1 + 4*dw, mm_x",
            "    hex.zero 4, ia_y1", "    hex.mov 4, ia_y1 + 4*dw, mm_y",
            "    hex.mov 8, ia_x2, mt_tqx", "    hex.mov 8, ia_y2, mt_tqy",
            "    stl.fcall ia_leaf, ia_ret",
            "    hex.mov 8, md_at, ia_ang",
            "    hex.mov 4, md_td, mt_d",
            "    hex.mov 2, md_me, md_src", "    hex.inc 2, md_me",            # the shooter's code: 2 + slot
            # the scan's box: a thing nearer than the target lies within d_t - 1 of the shooter on both axes
            # (P_AproxDistance >= either |delta|) -- [mm - d_t + 1, mm + d_t - 1], BIASED for unsigned compares
            "    hex.mov 4, hs_t4, md_td", "    hex.dec 4, hs_t4",
            *[ln for c in ("x", "y") for ln in (
                "    hex.mov 4, hs_%slo, mm_%s" % (c, c), "    hex.sub 4, hs_%slo, hs_t4" % c,
                "    hex.mov 4, hs_%shi, mm_%s" % (c, c), "    hex.add 4, hs_%shi, hs_t4" % c,
                "    hex.xor_by hs_%slo + 3*dw, 8" % c, "    hex.xor_by hs_%shi + 3*dw, 8" % c)],
            "  md_hs_out:", "    stl.fret md_bret",
            # one bullet: P_Random x 3 folded into its row (spread, damage), the things in the way, then the target
            "  md_bul:",
            "    hex.inc 2, mm_rng",
            "    mbsd.lookup md_row, mm_rng",
            "    hex.add_constant 2, mm_rng, 2",
            "    hex.if0 1, md_seen, md_bul_out",
            "    hex.mov 3, md_sp, md_row + 1*dw", "    hex.sign_extend 4, 3, md_sp",
            "    stl.fcall hs_scan, hs_ret",
            "    hex.if1 2, hs_vic, md_bul_v",
            "    hex.mov 4, hs_d, md_td", "    hex.mov 1, hs_rc, mt_rc", "    hex.zero 4, hs_del",
            "    stl.fcall hs_wid, hs_wret",
            "    hex.if0 1, hs_in, md_bul_out",
            "    hex.mov 2, hs_vic, mm_tg",
            "  md_bul_v:",
            "    hex.zero 2, dp_dmg", "    hex.mov 1, dp_dmg, md_row",
            "    hex.cmp 2, hs_vic, md_c1, md_bul_out, md_bul_p, md_bul_t",
            "  md_bul_p:",                                        # the player
            "    hex.mov 2, dp_src, md_src",
            *kb,
            "    stl.fcall dp_go, dp_ret",
            "    ;md_bul_out",
            "  md_bul_t:",                                        # a monster or a barrel: dm_go's id is the code - 1
            "    hex.mov 2, dm_dmg, dp_dmg",
            "    hex.set 1, dm_melee, %d" % DM_BULLET,
            "    hex.mov 2, dm_src, md_me",
            "    hex.mov 2, dm_id, hs_vic", "    hex.dec 2, dm_id",
            *kb,
            "    stl.fcall dm_go, dm_ret",
            "  md_bul_out:", "    stl.fret md_bret"]
    return out


def target_load_lines(slot_rt, radii) -> List[str]:
    """`mt_load` (stl.fcall mt_load, mt_lret; in: mm_tg) -- the module docstring's target load. `slot_rt[m]`: slot m's
    runtime thing (its thpos_rt row: whole units in nibbles 4-7 / 12-15), `radii[m]` its radius"""
    from doomfj.combat import PLAYER_R
    from doomfj.world import MELEE_BASE
    n = len(slot_rt)
    assert len(radii) == n and 0 < n and n + 2 <= 0x100
    hi = (n + 2 + 15) // 16
    out = ["mt_load:",
           "    hex.zero 1, mt_al", "    hex.zero 1, mt_pl",
           "    hex.if0 2, mm_tg, mtl_out",                       # no target: not alive
           "    sim.jump16 mm_tg + 1*dw, " + ", ".join("mtl_h%d" % h if h < hi else "mtl_out" for h in range(16))]
    for h in range(hi):
        tg = []
        for k in range(16):
            c = 16 * h + k
            tg.append("mtl_pl" if c == 1 else "mtl_m%d" % (c - 2) if 2 <= c < n + 2 else "mtl_out")
        out += ["  mtl_h%d:" % h, "    sim.jump16 mm_tg, " + ", ".join(tg)]
    out += ["  mtl_pl:",                                          # the player: alive while not dead
            "    hex.set 1, mt_pl, 1",
            "    hex.mov 8, mt_tqx, viewx", "    hex.mov 8, mt_tqy, viewy",
            "    hex.set 4, mt_reach, %d" % (MELEE_BASE + PLAYER_R), "    hex.set 1, mt_rc, %d" % RC[PLAYER_R],
            "    hex.if1 1, p_dead, mtl_out",
            "    hex.set 1, mt_al, 1",
            "    ;mtl_out"]
    for m, (t, r) in enumerate(zip(slot_rt, radii)):
        out += ["  mtl_m%d:" % m,
                "    hex.zero 4, mt_tqx", "    hex.mov 4, mt_tqx + 4*dw, thpos_rt + %d*dw" % (16 * t + 4),
                "    hex.zero 4, mt_tqy", "    hex.mov 4, mt_tqy + 4*dw, thpos_rt + %d*dw" % (16 * t + 12),
                "    hex.set 4, mt_reach, %d" % (MELEE_BASE + r), "    hex.set 1, mt_rc, %d" % RC[r],
                "    hex.mov 1, mt_al, mon_shootable + %d*dw" % m,
                "    ;mtl_out"]
    return out + ["  mtl_out:", "    stl.fret mt_lret"]


def angle_leaf_lines() -> List[str]:
    """`ia_leaf` (stl.fcall ia_leaf, ia_ret): ia_ang = R_PointToAngle2 (ia_x1, ia_y1) -> (ia_x2, ia_y2), all 16.16 --
    the ONE expansion of proj.point_to_angle the attacks share (the bullets' aim and scan, the fireball's aim)"""
    return ["ia_leaf:", "    proj.point_to_angle ia_ang, ia_x1, ia_y1, ia_x2, ia_y2, 1", "    stl.fret ia_ret"]


def scan_lines(slot_rt, radii, barrels) -> List[str]:
    """`hs_scan` (stl.fcall hs_scan, hs_ret): hs_vic = the code of the thing a bullet meets before its target
    (combat._bullet_victim; 0 none, 1 the player, 2 + slot, 2 + nmon + b a barrel) -- md_hs set md_at (the target's
    angle), md_td (its distance), md_me (the shooter's code), ia_x1 / ia_y1 (the shooter); md_bul set md_sp (the
    spread). The candidates in the model's order -- the player (alive, not the target), the slots (shootable), the
    barrels (standing: state != 0, health > 0) -- each a copy-stub into `hs_cand`; `barrels` = [(x, y)] by index.
    Then `hs_cand` and `hs_wid` (the width: hs_in = hs_d < 2048 and |md_sp - hs_del| <= hwtr[hs_rc][hs_d >> 4])"""
    from doomfj.combat import BARREL_R
    n = len(slot_rt)
    out = ["hs_scan:",
           "    hex.zero 2, hs_vic",
           "    hex.mov 4, hs_bd, md_td",                         # nearer than the target, then than the best
           "    hex.if1 1, mt_pl, hs_mons",
           "    hex.if1 1, p_dead, hs_mons",
           "    hex.mov 4, hs_cx, viewx + 4*dw", "    hex.mov 4, hs_cy, viewy + 4*dw",
           "    hex.set 2, hs_id, 1", "    hex.set 1, hs_rc, %d" % RC[16], "    hex.set 1, hs_pl, 1",
           "    stl.fcall hs_cand, hs_cret",
           "    hex.zero 1, hs_pl",
           "  hs_mons:"]
    for m, (t, r) in enumerate(zip(slot_rt, radii)):
        X, Y, L = "thpos_rt + %d*dw" % (16 * t + 4), "thpos_rt + %d*dw" % (16 * t + 12), "hs_m%d" % m
        out += ["    hex.if0 1, mon_shootable + %d*dw, %s" % (m, L)]
        out += _scan_box(X, Y, L, True)
        out += ["    hex.mov 4, hs_cx, %s" % X, "    hex.mov 4, hs_cy, %s" % Y,
                "    hex.set 2, hs_id, %d" % (2 + m), "    hex.set 1, hs_rc, %d" % RC[r],
                "    stl.fcall hs_cand, hs_cret",
                "  %s:" % L]
    for b, (x, y) in enumerate(barrels):
        L = "hs_b%d" % b
        out += ["    hex.if0 2, bar_st + %d*dw, %s" % (2 * b, L),
                "    hex.if_flags bar_hp + %d*dw, 0xFF00, %sp, %s" % (2 * b + 1, L, L),   # health < 0
                "  %sp:" % L,
                "    hex.if0 2, bar_hp + %d*dw, %s" % (2 * b, L)]                        # health == 0
        out += _scan_box("hs_bar + %d*dw" % (8 * b), "hs_bar + %d*dw" % (8 * b + 4), L, False)
        out += ["    hex.set 4, hs_cx, %d" % (x & 0xFFFF), "    hex.set 4, hs_cy, %d" % (y & 0xFFFF),
                "    hex.set 2, hs_id, %d" % (2 + n + b), "    hex.set 1, hs_rc, %d" % RC[BARREL_R],
                "    stl.fcall hs_cand, hs_cret",
                "  %s:" % L]
    out += ["    stl.fret hs_ret",
            # one candidate at (hs_cx, hs_cy) (whole units): nearer than hs_bd -- its box first (P_AproxDistance is
            # at least either |delta|), then the distance -- under MISSILERANGE, not the shooter; then its angle
            "hs_cand:",
            "    hex.mov 4, mt_dx, hs_cx", "    hex.sub 4, mt_dx, mm_x",
            "    hex.mov 4, hs_t4, mt_dx", "    hex.abs 4, hs_t4",
            "    hex.cmp 4, hs_t4, hs_bd, hsc_y, hsc_out, hsc_out",
            "  hsc_y:",
            "    hex.mov 4, mt_dy, hs_cy", "    hex.sub 4, mt_dy, mm_y",
            "    hex.mov 4, hs_t4, mt_dy", "    hex.abs 4, hs_t4",
            "    hex.cmp 4, hs_t4, hs_bd, hsc_me, hsc_out, hsc_out",
            "  hsc_me:",
            "    hex.cmp 2, hs_id, md_me, hsc_d, hsc_out, hsc_d",
            "  hsc_d:",
            "    stl.fcall mt_dist_leaf, mt_ret",
            "    hex.cmp 4, mt_d, hs_bd, hsc_r, hsc_out, hsc_out",
            "  hsc_r:",
            "    hex.cmp 4, mt_d, hs_c2048, hsc_a, hsc_out, hsc_out",
            "  hsc_a:",                                           # delta = (angle - md_at) >> 20, signed
            "    hex.if1 1, hs_pl, hsc_ap",
            "    hex.zero 4, ia_x2", "    hex.mov 4, ia_x2 + 4*dw, hs_cx",
            "    hex.zero 4, ia_y2", "    hex.mov 4, ia_y2 + 4*dw, hs_cy",
            "    ;hsc_ag",
            "  hsc_ap:",
            "    hex.mov 8, ia_x2, viewx", "    hex.mov 8, ia_y2, viewy",
            "  hsc_ag:",
            "    stl.fcall ia_leaf, ia_ret",
            "    hex.mov 8, hs_t8, ia_ang", "    hex.sub 8, hs_t8, md_at",
            "    hex.mov 3, hs_del, hs_t8 + 5*dw", "    hex.sign_extend 4, 3, hs_del",
            "    hex.mov 4, hs_d, mt_d",
            "    stl.fcall hs_wid, hs_wret",
            "    hex.if0 1, hs_in, hsc_out",
            "    hex.mov 4, hs_bd, mt_d", "    hex.mov 2, hs_vic, hs_id",
            "  hsc_out:",
            "    stl.fret hs_cret",
            "hs_wid:",
            "    hex.zero 1, hs_in",
            "    hex.cmp 4, hs_d, hs_c2048, hsw_1, hsw_out, hsw_out",
            "  hsw_1:",
            "    hex.mov 4, hs_t4, md_sp", "    hex.sub 4, hs_t4, hs_del", "    hex.abs 4, hs_t4",
            "    hex.mov 2, hs_ix, hs_d + 1*dw", "    hex.mov 1, hs_ix + 2*dw, hs_rc",     # rc << 8 | d >> 4
            "    hex.zero 4, hs_hw", "    hwtr.lookup hs_hw, hs_ix",
            "    hex.cmp 4, hs_t4, hs_hw, hsw_in, hsw_in, hsw_out",
            "  hsw_in:",
            "    hex.set 1, hs_in, 1",
            "  hsw_out:",
            "    stl.fret hs_wret"]
    return out


def _scan_box(xcell: str, ycell: str, miss: str, row: bool) -> List[str]:
    """a candidate within md_hs' biased box (hs_xlo .. hs_yhi) falls through, else `miss` -- `hex.cmp 4` on biased
    values (~60 ops; `hex.sub 4` is ~350, `hex.scmp 4` ~290: MEASURED). `row`: X and Y are a thing's row (unbiased):
    each is biased in place for its compares and restored on every way out; else they are biased constants"""
    t = miss + "_"
    bx = ["    hex.xor_by %s + 3*dw, 8" % xcell] if row else []
    by = ["    hex.xor_by %s + 3*dw, 8" % ycell] if row else []
    return (bx + ["    hex.cmp 4, %s, hs_xlo, %srx, %s1, %s1" % (xcell, t, t, t),
                  "  %s1:" % t,
                  "    hex.cmp 4, %s, hs_xhi, %s2, %s2, %srx" % (xcell, t, t, t),
                  "  %s2:" % t] + bx + by
            + ["    hex.cmp 4, %s, hs_ylo, %sry, %s3, %s3" % (ycell, t, t, t),
               "  %s3:" % t,
               "    hex.cmp 4, %s, hs_yhi, %s4, %s4, %sry" % (ycell, t, t, t),
               "  %s4:" % t] + by + ["    ;%sin" % t,
                                     "  %srx:" % t] + bx + ["    ;%s" % miss,
                                                            "  %sry:" % t] + by + ["    ;%s" % miss,
                                                                                   "  %sin:" % t])


def mbsd_row(spread: int, dmg: int) -> int:
    """a monster bullet's row with infighting: nibble 0 the damage, nibbles 1-3 the spread (12-bit two's complement)"""
    assert 0 < dmg < 16 and -2048 <= spread < 2048
    return dmg | ((spread & 0xFFF) << 4)


def mbsd_values() -> List[int]:
    """`mbsd`: combat.site_formulas' `mon_bullet` (spread, damage), 3 draws (D10's outcome_table_k), unfolded"""
    from doomfj.combat import outcome_table_k, site_formulas
    k, f = site_formulas(lambda s: 0)["mon_bullet"]
    assert k == 3
    return outcome_table_k(lambda a, b, c: mbsd_row(*f(a, b, c)), 3)


def hwtr_values(sine) -> List[int]:
    """`hwtr[rc << 8 | q]`: combat.half_width_table at hit_half_width(r) for the radius r of class rc, q < 128"""
    from doomfj.combat import HWT_SIZE, half_width_table, hit_half_width
    out = [0] * (len(RC) << 8)
    for r, rc in RC.items():
        t = half_width_table(sine, hit_half_width(r))
        assert len(t) == HWT_SIZE <= 256 and max(t) < 256
        for q, v in enumerate(t):
            out[(rc << 8) | q] = v
    return out


def fight_tables_fj(sine) -> List[str]:
    from doomfj.lut_generator import generate_dispatch_table_fj
    return [generate_dispatch_table_fj("mbsd", mbsd_values(), index_nibbles=2, result_nibbles=4),
            generate_dispatch_table_fj("hwtr", hwtr_values(sine), index_nibbles=3, result_nibbles=2)]


def fight_parts(w, slot_rt) -> dict:
    """everything infighting adds to the decide leaves, for the World `w` (its schema has the wide mon_target): the
    registers, the target load, the angle leaf, the scan, the tables"""
    n = w.layout.nmon
    radii = [w.mon_radius[m] for m in range(n)]
    assert set(radii) <= set(RC), radii
    bars = [(t.x, t.y) for t in w.barrel_things]
    hs_bar = "hs_bar: hex.vec %d, %d" % (max(1, 8 * len(bars)), sum(
        (((x & 0xFFFF) ^ 0x8000) | (((y & 0xFFFF) ^ 0x8000) << 16)) << (32 * b) for b, (x, y) in enumerate(bars)))
    return {"decls": list(FIGHT_DECLS) + [hs_bar],
            "lines": (target_load_lines(slot_rt, radii) + angle_leaf_lines()
                      + scan_lines(slot_rt, radii, [(t.x, t.y) for t in w.barrel_things])),
            "tables": fight_tables_fj(w.rm.sine)}
