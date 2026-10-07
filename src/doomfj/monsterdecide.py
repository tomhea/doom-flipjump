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
"""
from typing import List

from doomfj import gamedata as gd

P32C_FIELDS = ("mon_justattacked",)

# md_attack's kinds (mm_kind), one per attack action the decide mode runs
ATTACK_KINDS = {"A_FaceTarget": 0, "A_PosAttack": 1, "A_SPosAttack": 2, "A_TroopAttack": 3, "A_SargAttack": 4}

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


def todist_leaf_lines() -> List[str]:
    return ["mm_todist:",
            "    hex.mov 4, mt_dx, viewx + 4*dw", "    hex.sub 4, mt_dx, mm_x",
            "    hex.mov 4, mt_dy, viewy + 4*dw", "    hex.sub 4, mt_dy, mm_y",
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


def as_leaf_lines() -> List[str]:
    """`mm_as`: the attack sight, once (mm_asok) -- needs mt_d current; mt_c128 is P3.2a's NEAR
    (monstercode.P32A_SCRATCH, from sight.NEAR)"""
    return ["mm_as:",
            "    hex.if1 1, mm_asok, mm_as_out",
            "    hex.set 1, mm_asok, 1", "    hex.set 1, mm_asr, 1",
            "    hex.if1 1, mm_seen, mm_as_out",
            "    hex.cmp 4, mt_d, mt_c128, mm_as_nr, mm_as_nr, mm_as_no",      # mt_c128: P3.2a's NEAR
            "  mm_as_nr:",
            "    stl.fcall sl_los, sl_ret",
            "    hex.if0 1, sl_hit, mm_as_out",
            "  mm_as_no:", "    hex.zero 1, mm_asr",
            "  mm_as_out:", "    stl.fret mm_asret"]


def decide_leaf_lines(justhit: bool = False) -> List[str]:
    """`mm_decide` (stl.fcall mm_decide, mm_dret) -- see the module docstring; the bias and cap are
    world.MISSILE_BIAS / MISSILE_NOMELEE_BIAS / MISSILE_CAP, compared as rand + bias >= min(d, bias + cap).
    `justhit` (M7 P4.2a): the context's `mm_jh` (damagecode declares it) is read and cleared"""
    from doomfj.world import MISSILE_BIAS, MISSILE_CAP, MISSILE_NOMELEE_BIAS
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
            "    hex.cmp 4, mt_d, mt_c60, mm_dc_mr2, mm_dc_ms, mm_dc_ms",
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


def attack_leaf_lines(full: bool = False, knock: bool = False) -> List[str]:
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
    -- the bullets', the claw's, the bite's (dp_go zeroes kb_on on every exit)"""
    from doomfj.combat import BULLETS
    from doomfj.knockcode import inflictor_lines
    assert not knock or full, "M7 P8a: the thrust rides the applied attacks"
    kb = inflictor_lines("mm_x", "mm_y", z="kb_az") if knock else []     # package K: the attacker's floorz (k_go)
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


def decide_leaves(justhit: bool = False, full: bool = False, knock: bool = False) -> List[str]:
    """`full` (M7 P5): md_attack applies its draws (attack_leaf_lines(full=True)); off, P3.2c's text to the byte.
    `knock` (M7 P8a): the attacker is each hit's inflictor (attack_leaf_lines(knock=True))"""
    return (todist_leaf_lines() + octant_leaf_lines() + as_leaf_lines() + decide_leaf_lines(justhit)
            + attack_leaf_lines(full, knock))


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
