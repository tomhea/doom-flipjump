"""M7 P4.2a "shoot" (docs/gp-combat.md): the fj of P_DamageMobj on a MONSTER -- the model's `combat.damage_monster`
and `_kill_monster` in the player mode "shoot" (no drop, no effect, no barrel), behind `_line_attack`'s reach test.

THE INTERFACE (the player's shot is the caller):

    dm_id     2 nibbles   1 + the monster slot hit (0: nothing -- dm_go returns at once)
    dm_dmg    2 nibbles   the damage, 1 .. DM_MAX
    dm_melee  1 nibble    1 for the fist and the saw: the target's centre must be within dm_reach
    dm_reach  2 nibbles   64 fist / 65 saw; unused when dm_melee = 0, where the reach is MISSILERANGE_U (2048) --
                          `_line_attack` tests every weapon's reach, the bullets' too
    stl.fcall dm_go, dm_ret

`dm_go` returns through `stl.fret dm_ret` on EVERY path. It reads the player's position from viewx / viewy: the
weapon runs before the player moves (combat: the tic-start view).

THE CODE (no per-slot logic -- P3.2b's first build overflowed the table pool when per-slot code was unrolled):
  * `dm_go`: a two-level `sim.jump16` on dm_id to the slot's stub `dmg<m>`, which copies the slot's cells into the
    window (the `dm_*` registers), its position from thpos_rt, its damage PROFILE index (`dm_type`), calls `dm_leaf`
    and copies the cells back;
  * `dm_leaf`, damage_monster's order: not shootable or health <= 0 -> nothing; P_AproxDistance(target - player) >
    reach -> nothing; health -= damage; ONE P_Random on the monster's stream (both outcomes in the folded table
    `dmrnd`: either path draws exactly once); a dispatch on the profile sets its constants and its pain outcome;
    then the death (shootable 0, the death state and its tics, tics -= P_Random() & 3) or the hurt (the pain state and
    justhit on the roll; reaction 0; threshold 0 -> target, BASETHRESHOLD, and the spawn state -> the see state).

What the emit-time asserts hold (each a model rule the code does NOT implement because E1M1 cannot reach it):
  * no gib: DM_MAX cannot take a live monster below -spawnhealth;
  * `max(1, tics - (P_Random() & 3))` never clamps: every death state lasts >= 4 tics;
  * the states entered need nothing more from `World._set_state`: no zero-tic state (no chain), the pain and death
    states run no action but a sound (a no-op, D5), the see state is entered without its action (D-WAKE);
  * every E1M1 monster is MF_SHOOTABLE and MF_SOLID, so at level start mon_shootable = mon_solid = mon_active, and
    mon_shootable stays exactly "active and health > 0" (World.door_touched's live monster) while only damage moves
    health;
  * a monster whose A_Fall cleared mon_solid never moves again (no A_Chase after a death state), so the slot code
    may clear and SET its own mon_solid around its move.
"""
from typing import Dict, List, Sequence, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.lut_generator import generate_dispatch_table_fj

# the per-slot cells P4.2a adds (world.build_schema's widths: health 12 bits signed -> 3 nibbles, the flags 1)
P42_FIELDS = ("mon_health", "mon_shootable", "mon_solid", "mon_justhit")
# the player modes whose shots hurt monsters (world.PLAYER_MODES): the emitter adds this module when the game tier's
# PLAYER_MODE is one of them
DAMAGE_PLAYER_MODES = ("shoot", "hit", "full")
DM_MAX = 20                          # the largest damage a shot deals in P4.2a (the fist and the saw: 20)
TICS_FOREVER = 15


def damage_on(player_mode: str) -> bool:
    return player_mode in DAMAGE_PLAYER_MODES


# ---- the profiles: what P_DamageMobj reads from a monster's mobjinfo -----------------------------------------------
def profile_key(info) -> tuple:
    return (info.painchance, info.painstate, info.deathstate, info.spawnstate, info.seestate)


def profiles(w) -> Tuple[List[tuple], List[int]]:
    """(the distinct damage profiles of the world's monster slots, in first-slot order; each slot's profile index)"""
    keys, of = [], []
    for m in range(w.layout.nmon):
        k = profile_key(w.mon_info[m])
        if k not in keys:
            keys.append(k)
        of.append(keys.index(k))
    return keys, of


def pain_classes(keys) -> List[int]:
    """the distinct painchances, ascending: bit c of dmrnd's nibble 1 is `P_Random() < pain_classes[c]`"""
    return sorted({k[0] for k in keys})


def dmrnd_row(v: int, classes: Sequence[int]) -> int:
    """the folded outcome of ONE P_Random value v: nibble 0 = v & 3 (P_KillMobj's tics roll), nibble 1 bit c =
    v < classes[c] (P_DamageMobj's pain roll for painchance classes[c])"""
    return (v & 3) | (sum(int(v < pc) << c for c, pc in enumerate(classes)) << 4)


def dmrnd_values(classes: Sequence[int]) -> List[int]:
    """`dmrnd`, indexed (as `mrnd`) by the stream's POST-increment state"""
    return R.outcome_table(lambda v: dmrnd_row(v, classes))


def pain_mask(cls: int) -> int:
    """`hex.if_flags` flags: the nibble values (pain bits) whose bit `cls` is set"""
    return sum(1 << n for n in range(16) if n >> cls & 1)


def _tics(name: str) -> int:
    t = gd.STATES[name].tics
    return TICS_FOREVER if t < 0 else t


def check_model_rules(w, *, max_dmg: int = DM_MAX) -> None:
    """the emit-time asserts of the module docstring, over the world's monster types"""
    from doomfj.monstercode import MON_ACTIONS, SOUND_ACTIONS
    keys, _of = profiles(w)
    assert len(pain_classes(keys)) <= 4, "the pain bits fill one nibble"
    for m in range(w.layout.nmon):
        info = w.mon_info[m]
        assert info.flags & gd.MF_SHOOTABLE and info.flags & gd.MF_SOLID, (m, "every monster shootable and solid")
        # gib: health < -spawnhealth after a hit on a live (health >= 1) monster needs damage > spawnhealth + 1
        assert max_dmg <= info.spawnhealth + 1, (m, info.spawnhealth, "a gib path would be needed")
    for pc, pain, death, spawn, see in keys:
        assert 0 < pc <= 256
        for s, run in ((pain, True), (death, True), (see, False)):
            st = gd.STATES[s]
            assert 0 < st.tics < TICS_FOREVER, (s, st.tics, "a zero-tic or forever state: _set_state would chain")
            assert not run or st.action is None or st.action in SOUND_ACTIONS, (s, st.action)
            assert gd.STATE_INDEX[s] < 256
        assert gd.STATES[death].tics >= 4, (death, "tics - (P_Random() & 3) could clamp at 1")
        assert gd.STATE_INDEX[spawn] < 256 and see != gd.S_NULL
        # the death sequence: A_Fall clears MF_SOLID, and nothing after it moves the monster
        s, acts, seen = death, [], set()
        while s != gd.S_NULL and s not in seen:
            seen.add(s)
            acts.append(gd.STATES[s].action)
            if gd.STATES[s].tics < 0:
                break
            s = gd.STATES[s].next
        assert "A_Fall" in acts, (death, acts)
        assert not set(acts) & {"A_Chase", "A_Look", "A_FaceTarget"}, (death, acts)
        assert all(a is None or a in SOUND_ACTIONS or a in MON_ACTIONS for a in acts), acts
    assert 0 < gd.BASETHRESHOLD < 128, "mon_threshold is 7 bits"


# ---- the decls -----------------------------------------------------------------------------------------------------
DM_INTERFACE = ["dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_reach: hex.vec 2",
                "dm_ret: hex.vec w/4"]
DM_WINDOW = ["dm_hp: hex.vec 3", "dm_sh: hex.vec 1", "dm_st: hex.vec 2", "dm_ti: hex.vec 1", "dm_rng: hex.vec 2",
             "dm_th: hex.vec 2", "dm_re: hex.vec 1", "dm_tg: hex.vec 1", "dm_jh: hex.vec 1",
             "dm_x: hex.vec 4", "dm_y: hex.vec 4", "dm_type: hex.vec 1"]
DM_SCRATCH = ["dm_rr: hex.vec 2", "dm_pn: hex.vec 1", "dm_r4: hex.vec 4",
              "dm_dst: hex.vec 2", "dm_dti: hex.vec 1", "dm_pst: hex.vec 2", "dm_pti: hex.vec 1",
              "dm_sp: hex.vec 2", "dm_se: hex.vec 2", "dm_seti: hex.vec 1", "dm_lret: hex.vec w/4",
              # the decide leaf's justhit operand (monsterdecide.decide_leaf_lines(justhit=True))
              "mm_jh: hex.vec 1"]


def field_decls(schema, nmon: int, values: Dict[str, Sequence[int]]) -> List[str]:
    """the P42 cells as fj declarations (selfreset.decl_words' one-line form), `values` per field per slot"""
    from doomfj.monstercode import cell_nibbles
    out = []
    for name in P42_FIELDS:
        nib = cell_nibbles(schema, name)
        vals = [v & (16 ** nib - 1) for v in values[name]]
        assert len(vals) == nmon, (name, len(vals), nmon)
        out.append("%s: hex.vec %d, %d" % (name, nib * nmon, sum(v << (4 * nib * m) for m, v in enumerate(vals))))
    return out


# ---- the code ------------------------------------------------------------------------------------------------------
# (window register, schema field, writable) -- the cells a stub copies in, and back when writable
WINDOW = (("dm_hp", "mon_health"), ("dm_sh", "mon_shootable"), ("dm_st", "mon_state"), ("dm_ti", "mon_tics"),
          ("dm_rng", "mon_rng"), ("dm_th", "mon_threshold"), ("dm_re", "mon_reaction"), ("dm_tg", "mon_target"),
          ("dm_jh", "mon_justhit"))


def go_lines(schema, slot_rt: Sequence[int], slot_profile: Sequence[int]) -> List[str]:
    """`dm_go` and the per-slot stubs `dmg<m>`: copy the slot's cells in, `dm_leaf`, copy them back"""
    from doomfj.monstercode import cell_nibbles
    n = len(slot_rt)
    assert len(slot_profile) == n and 0 < n < 255, n
    nh = n // 16 + 1                                   # ids 1 .. n (id 0: nothing)
    out = ["dm_go:",
           "    sim.jump16 dm_id + 1*dw, " + ", ".join("dm_h%d" % h if h < nh else "dm_none" for h in range(16))]
    for h in range(nh):
        out += ["  dm_h%d:" % h, "    sim.jump16 dm_id, " + ", ".join(
            "dmg%d" % (16 * h + l - 1) if 1 <= 16 * h + l <= n else "dm_none" for l in range(16))]
    for m in range(n):
        cells = [(reg, "%s + %d*dw" % (f, cell_nibbles(schema, f) * m), cell_nibbles(schema, f)) for reg, f in WINDOW]
        out += ["  dmg%d:" % m]
        out += ["    hex.mov %d, %s, %s" % (nib, reg, cell) for reg, cell, nib in cells]
        out += ["    hex.mov 4, dm_x, thpos_rt + %d*dw" % (16 * slot_rt[m] + 4),
                "    hex.mov 4, dm_y, thpos_rt + %d*dw" % (16 * slot_rt[m] + 12),
                "    hex.set 1, dm_type, %d" % slot_profile[m],
                "    stl.fcall dm_leaf, dm_lret"]
        out += ["    hex.mov %d, %s, %s" % (nib, cell, reg) for reg, cell, nib in cells]
        out += ["    stl.fret dm_ret"]
    out += ["  dm_none:", "    stl.fret dm_ret"]
    return out


def leaf_lines(keys: Sequence[tuple]) -> List[str]:
    """`dm_leaf` (stl.fcall dm_leaf, dm_lret) on the window -- the module docstring's order. `keys`: the profiles
    (`profiles(w)[0]`); mt_dist_leaf (monstercode.dist_leaf_lines) computes P_AproxDistance"""
    from doomfj.combat import MISSILERANGE_U
    classes = pain_classes(keys)
    assert 0 < len(keys) <= 16
    out = ["dm_leaf:",
           "    hex.if0 1, dm_sh, dm_out",                                    # not shootable
           "    hex.if_flags dm_hp + 2*dw, 0xFF00, dm_pos, dm_out",            # health < 0
           "  dm_pos:",
           "    hex.if0 3, dm_hp, dm_out",                                    # health == 0
           # _line_attack's reach: P_AproxDistance(target - player) > reach -> no hit
           "    hex.if0 1, dm_melee, dm_far",
           "    hex.zero 4, dm_r4", "    hex.mov 2, dm_r4, dm_reach", "    ;dm_rch",
           "  dm_far:",
           "    hex.set 4, dm_r4, %d" % MISSILERANGE_U,
           "  dm_rch:",
           "    hex.mov 4, mt_dx, viewx + 4*dw", "    hex.sub 4, mt_dx, dm_x",
           "    hex.mov 4, mt_dy, viewy + 4*dw", "    hex.sub 4, mt_dy, dm_y",
           "    stl.fcall mt_dist_leaf, mt_ret",
           "    hex.cmp 4, mt_d, dm_r4, dm_in, dm_in, dm_out",
           "  dm_in:",
           "    hex.sub_shifted 3, 2, dm_hp, dm_dmg, 0",                       # health -= damage
           "    hex.inc 2, dm_rng",                                            # P_Random on the monster's stream:
           "    dmrnd.lookup dm_rr, dm_rng",                                   # v & 3, and the pain bits
           "    hex.zero 1, dm_pn",
           "    sim.jump16 dm_type, " + ", ".join("dm_p%d" % k if k < len(keys) else "dm_out" for k in range(16))]
    for k, (pc, pain, death, spawn, see) in enumerate(keys):
        out += ["  dm_p%d:" % k,
                "    hex.set 2, dm_dst, %d" % gd.STATE_INDEX[death], "    hex.set 1, dm_dti, %d" % _tics(death),
                "    hex.set 2, dm_pst, %d" % gd.STATE_INDEX[pain], "    hex.set 1, dm_pti, %d" % _tics(pain),
                "    hex.set 2, dm_sp, %d" % gd.STATE_INDEX[spawn],
                "    hex.set 2, dm_se, %d" % gd.STATE_INDEX[see], "    hex.set 1, dm_seti, %d" % _tics(see),
                "    hex.if_flags dm_rr + 1*dw, %d, dm_typed, dm_p%dy" % (pain_mask(classes.index(pc)), k),
                "  dm_p%dy:" % k,
                "    hex.set 1, dm_pn, 1",
                "    ;dm_typed"]
    out += ["  dm_typed:",
            "    hex.if_flags dm_hp + 2*dw, 0xFF00, dm_live, dm_kill",          # health < 0: dead
            "  dm_live:",
            "    hex.if0 3, dm_hp, dm_kill",                                    # health == 0: dead
            # ---- hurt: the pain roll; reactiontime 0; threshold 0 -> the player becomes the target --------------
            "    hex.if0 1, dm_pn, dm_nopain",
            "    hex.set 1, dm_jh, 1",
            "    hex.mov 2, dm_st, dm_pst", "    hex.mov 1, dm_ti, dm_pti",
            "  dm_nopain:",
            "    hex.zero 1, dm_re",
            "    hex.if1 2, dm_th, dm_out",
            "    hex.set 1, dm_tg, 1",
            "    hex.set 2, dm_th, %d" % gd.BASETHRESHOLD,
            "    hex.cmp 2, dm_st, dm_sp, dm_out, dm_see, dm_out",              # exactly the spawn state: wake
            "  dm_see:",
            "    hex.mov 2, dm_st, dm_se", "    hex.mov 1, dm_ti, dm_seti",
            "    ;dm_out",
            # ---- P_KillMobj: not shootable, the death state, tics -= P_Random() & 3 (>= 4 tics: no clamp) -----
            "  dm_kill:",
            "    hex.zero 1, dm_sh",
            "    hex.mov 2, dm_st, dm_dst", "    hex.mov 1, dm_ti, dm_dti",
            "    hex.sub 1, dm_ti, dm_rr",
            "  dm_out:",
            "    stl.fret dm_lret"]
    return out


def damage_parts(w, *, slot_rt: Sequence[int], boot_skill: int, max_dmg: int = DM_MAX) -> dict:
    """everything P4.2a's damage adds, for the World `w` (any monster mode; the emitter's needs P3.2c "decide"):
      * `decls`: the P42 cells at `boot_skill`'s level start, the interface, the window and the scratch;
      * `lines`: dm_go, the per-slot stubs, dm_leaf -- leaves (each ends in a fret), placed where nothing falls in;
      * `tables`: `dmrnd`, the folded P_Random outcomes.
    `slot_rt[m]`: monster slot m's runtime thing (its thpos_rt row). NEW GAME restores the P42 cells through
    p31_parts' `fields` (P42_FIELDS joins them when its `damage` is on)."""
    check_model_rules(w, max_dmg=max_dmg)
    n = w.layout.nmon
    assert len(slot_rt) == n
    keys, of = profiles(w)
    snap = w.level_start(boot_skill)
    vals = {f: list(getattr(snap, f)[:n]) for f in P42_FIELDS}
    return {"fields": P42_FIELDS,
            "decls": field_decls(w.schema, n, vals) + DM_INTERFACE + DM_WINDOW + DM_SCRATCH,
            "lines": go_lines(w.schema, slot_rt, of) + leaf_lines(keys),
            "tables": [generate_dispatch_table_fj("dmrnd", dmrnd_values(pain_classes(keys)),
                                                  index_nibbles=2, result_nibbles=2)]}
