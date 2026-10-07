"""M7 P3 -- the monsters' fj (docs/gp-monsters.md). P3.0: the TABLES the monster phase will call, emitted from
the model's own sources (one source per table, handoff section 6 rule 8) and called by nothing yet -- the build that
carries them prices the pure placement tax.

  * `mstate`: gamedata's state table for every monster-reachable state, indexed by `gamedata.STATE_INDEX` (the
    model's `mon_state`): next state (nibbles 0-1), tics (nibble 2; 15 = forever), action id (nibble 3,
    `MON_ACTIONS`), view group (nibbles 4-5, `view_groups`). Any other state reads 0.
  * `mturn`: A_Chase's turn toward movedir, `world.turn_toward`, indexed by movedir << 4 | facing.
  * `mopp`: P_NewChaseDir's opposite direction, `gamedata.OPPOSITE`, indexed by movedir.
  * `mrnd`: the monster stream's P3 call sites (D10) folded into one outcome table indexed by the POST-increment
    state: the value (nibbles 0-1: A_Chase's missile roll compares it), `> 200` (nibble 2 bit 0) and `& 1`
    (nibble 2 bit 1) for P_NewChaseDir, `& 15` (nibble 3) for the walk's movecount.
"""
from typing import Dict, List, Sequence, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.noisecode import ambush_decl, noise_decls, noise_leaf_lines, noise_restart_lines
from doomfj.sight import NEAR
from doomfj.world import K_HEAVY, LOOK_BEHIND_REACH, monster_attacks_land

MONSTER_TYPES = ("MT_POSSESSED", "MT_SHOTGUY", "MT_TROOP", "MT_SERGEANT", "MT_SHADOWS")
# action ids; the sound actions (A_Pain, A_Scream, A_XScream) are no-ops (D5: no sound) and read 0
MON_ACTIONS = (None, "A_Look", "A_Chase", "A_FaceTarget", "A_Fall", "A_PosAttack", "A_SPosAttack",
               "A_TroopAttack", "A_SargAttack")
SOUND_ACTIONS = frozenset(a for a, x in gd.ACTIONS.items() if x.phase == "sound")
TICS_FOREVER = 15
STATE_FIELDS = (("next", 0, 2), ("tics", 2, 1), ("action", 3, 1), ("view", 4, 2))   # (name, nibble, width)


def monster_states() -> List[str]:
    """every state a monster type can reach from its info's state fields, in STATE_INDEX order"""
    seen = set()
    for mt in MONSTER_TYPES:
        info = gd.MOBJINFO[mt]
        for f, v in vars(info).items():
            s = v if f.endswith("state") and isinstance(v, str) else None
            while s and s != gd.S_NULL and s not in seen:
                seen.add(s)
                s = gd.STATES[s].next
    return sorted(seen, key=gd.STATE_INDEX.__getitem__)


def view_groups() -> List[Tuple[str, int]]:
    """the distinct (sprite, frame) a monster state draws, in the order monster_states first draws them"""
    out: List[Tuple[str, int]] = []
    for s in monster_states():
        st = gd.STATES[s]
        g = (st.sprite, st.frame & gd.FF_FRAMEMASK)
        if g not in out:
            out.append(g)
    return out


def action_id(action) -> int:
    if action is None or action in SOUND_ACTIONS:
        return 0
    return MON_ACTIONS.index(action)


def state_row(name: str) -> Dict[str, int]:
    st = gd.STATES[name]
    return {"next": gd.STATE_INDEX[st.next], "tics": TICS_FOREVER if st.tics < 0 else st.tics,
            "action": action_id(st.action),
            "view": view_groups().index((st.sprite, st.frame & gd.FF_FRAMEMASK))}


def pack(row: Dict[str, int]) -> int:
    v = 0
    for name, nib, width in STATE_FIELDS:
        assert 0 <= row[name] < 16 ** width, (name, row[name])
        v |= row[name] << (4 * nib)
    return v


def state_table_values() -> List[int]:
    vals = [0] * len(gd.STATE_NAMES)
    for s in monster_states():
        vals[gd.STATE_INDEX[s]] = pack(state_row(s))
    return vals


def turn_table_values() -> List[int]:
    from doomfj.world import turn_toward
    vals = [0] * 256
    for d in range(9):
        for f in range(8):
            vals[(d << 4) | f] = turn_toward(f, d) if d < 8 else f
    return vals[:(8 << 4) + 8]


def opposite_values() -> List[int]:
    return list(gd.OPPOSITE)


def rnd_row(v: int) -> int:
    return v | (int(v > 200) << 8) | ((v & 1) << 9) | ((v & 15) << 12)


def rnd_values() -> List[int]:
    return R.outcome_table(rnd_row)


def p30_tables_fj() -> List[str]:
    """P3.0: the four tables, emitted and called by nothing"""
    assert max(gd.STATE_INDEX.values()) < 256 and len(view_groups()) <= 256
    return [
        generate_dispatch_table_fj("mstate", state_table_values(), index_nibbles=2, result_nibbles=6),
        generate_dispatch_table_fj("mturn", turn_table_values(), index_nibbles=2, result_nibbles=1),
        generate_dispatch_table_fj("mopp", opposite_values(), index_nibbles=1, result_nibbles=1),
        generate_dispatch_table_fj("mrnd", rnd_values(), index_nibbles=2, result_nibbles=4),
    ]


# ---- P3.1: the cells and the tic (docs/gp-monsters.md section 7) ----------------------------------------------
# the per-slot cells P3.1 holds, (schema field, nibbles) -- widths from world.build_schema (rule 7)
P31_FIELDS = ("mon_state", "mon_tics", "mon_facing", "mon_active")


def cell_nibbles(schema, name: str) -> int:
    f = next(x for x in schema if x.name == name)
    return (f.bits + 3) // 4


def monster_decls(schema, nmon: int, values: dict = None) -> list:
    """the P3.1 cells as fj declarations, `nmon` slots each, from the schema's widths; `values` (field -> per-slot
    list) gives their initial contents (the boot skill's level start), zero otherwise"""
    out = []
    for name in P31_FIELDS:
        nib = cell_nibbles(schema, name)
        vals = (values or {}).get(name, [0] * nmon)
        assert len(vals) == nmon, (name, len(vals), nmon)
        assert all(0 <= v < 16 ** nib for v in vals), (name, vals)
        # ONE `name: hex.vec n, value` line (selfreset.decl_words' form, as mover_decls): slot m's
        # nibbles are value's nibbles nib*m .. nib*m + nib - 1
        packed = sum(v << (4 * nib * m) for m, v in enumerate(vals))
        out.append("%s: hex.vec %d, %d" % (name, nib * nmon, packed))
    return out


def idle_reachable_actions() -> set:
    """every action a monster can run WITHOUT waking: the states reachable from the spawn states by `next` alone"""
    acts = set()
    for mt in MONSTER_TYPES:
        s, seen = gd.MOBJINFO[mt].spawnstate, set()
        while s and s != gd.S_NULL and s not in seen:
            seen.add(s)
            acts.add(gd.STATES[s].action)
            s = gd.STATES[s].next
    return acts


def mon_tic_lines(schema, nmon: int, tag: str = "mt") -> list:
    """P3.1's monster tic, unrolled over the slots: inactive or forever -> nothing; else tics -= 1, and at 0 the
    state steps -- `mstate` gives the current state's next, then that state's tics. A monster state never has 0
    tics (asserted), so a step is ONE state, and in idle no action but A_Look (a no-op there) can run (asserted)."""
    assert all(gd.STATES[s].tics != 0 for s in monster_states()), "a zero-tic monster state: the step would chain"
    assert idle_reachable_actions() <= {None, "A_Look"}, idle_reachable_actions()
    ns, nt = cell_nibbles(schema, "mon_state"), cell_nibbles(schema, "mon_tics")
    na = cell_nibbles(schema, "mon_active")
    assert (ns, nt, na) == (2, 1, 1), (ns, nt, na)
    out = []
    for m in range(nmon):
        st, ti, ac = "mon_state + %d*dw" % (ns * m), "mon_tics + %d*dw" % (nt * m), "mon_active + %d*dw" % (na * m)
        done, go, ready = "%s%d_done" % (tag, m), "%s%d_go" % (tag, m), "%s%d_ready" % (tag, m)
        out += [
            "    hex.if0 1, %s, %s" % (ac, done),                          # not spawned at this skill
            # hex.if_flags x, flags, l0, l1: a set bit (the value 15, forever) goes to l1
            "    hex.if_flags %s, %d, %s, %s" % (ti, 1 << TICS_FOREVER, go, done),
            "  %s:" % go,
            "    hex.dec 1, %s" % ti,
            "    hex.if0 1, %s, %s" % (ti, ready),                          # reached 0: READY
            "    ;%s" % done,
            "  %s:" % ready,
            "    mstate.lookup mt_row, %s" % st,                          # the current state's next ...
            "    hex.mov 2, %s, mt_row" % st,
            "    mstate.lookup mt_row, %s" % st,                          # ... and that state's tics
            "    hex.mov 1, %s, mt_row + 2*dw" % ti,
            "  %s:" % done,
        ]
    return out

MT_DECLS = ["mt_row: hex.vec 6"]


# ---- P3.1: the rotation (doomfj.monsters.rotation, R_ProjectSprite's) -----------------------------------------------
def rot_table_values() -> List[int]:
    """`mrot[(n << 4) | facing]`, n the viewer-to-thing angle's TOP nibble: the rotation INDEX (rotation - 1).
    ((ang + 0x90000000) >> 29) is ((n + 9) & 15) >> 1 -- the lower nibbles of 0x90000000 are 0, so nothing carries
    into the top one -- and subtracting facing * ANG45 only moves bits 29..31, so it subtracts facing mod 8."""
    vals = [0] * 256
    for n in range(16):
        for f in range(8):
            vals[(n << 4) | f] = ((((n + 9) & 15) >> 1) - f) & 7
    return vals[:(15 << 4) + 8]


def rotation_leaf_lines(disp: int = 1) -> list:
    """the shared leaf: mr_rot = the rotation index of a thing at (mr_tx, mr_ty) facing mr_face, seen from
    (viewx, viewy) -- all 16.16 / nibble cells; `stl.fcall mon_rot_leaf, mr_ret`"""
    return [
        "mon_rot_leaf:",
        "    proj.point_to_angle mr_ang, viewx, viewy, mr_tx, mr_ty, %d" % disp,
        "    hex.mov 1, mr_idx + 1*dw, mr_ang + 7*dw",
        "    hex.mov 1, mr_idx, mr_face",
        "    mrot.lookup mr_rot, mr_idx",
        "    stl.fret mr_ret",
    ]


ROT_DECLS = ["mr_ang: hex.vec 8", "mr_tx: hex.vec 8", "mr_ty: hex.vec 8", "mr_face: hex.vec 1",
             "mr_idx: hex.vec 2", "mr_rot: hex.vec 1", "mr_ret: hex.vec w/4"]


def rot_table_fj() -> str:
    return generate_dispatch_table_fj("mrot", rot_table_values(), index_nibbles=2, result_nibbles=1)


# ---- P3.1: the emitter's parts (docs/gp-monsters.md section 7, items 1-4) --------------------------------------------
def _thing_key(t):
    return (t.type, t.x, t.y, t.angle, t.flags)


def p31_parts(rm, map_wad, mapname, sprite_wad, anim_index, rt_things, *, spr_near: bool, boot_skill: int,
              skills, cache: dict, mode: str = "idle", depth_order=None, player: str = "walk",
              static_bank=None) -> dict:
    """everything P3.1 adds to the game tier, from the model's own sources:
      * `view_rows`: one thing row per distinct monster VIEW (lump, mirrored) -- `things.thing_rows`' layout from the
        view's art, dw's bit 7 set for a mirrored view -- appended after the runtime things' own rows;
      * `mview`: the D4 table (view group << 4 | rotation index) -> that view's row;
      * `select`: the row-select leaf `thsel_leaf` (sp_ti = thing index in, its row out): a two-level `sim.jump16`
        on the index into one stub per runtime thing -- a static thing keeps its own row, a monster's stub runs the
        rotation leaf on its slot's facing and looks up its state's view group (rule 1: the index selects CODE);
      * `rotation`: the rotation leaf; `tic`: the per-slot tic; `decls`: the cells (the boot skill's level start)
        and the scratch; `restart`: per skill, the lines NEW GAME writes the cells with.

    `player` (M7 P4.2a): the game tier's PLAYER_MODE. A mode whose shots hurt (`damagecode.damage_on`; it needs
    the monster mode "decide") adds the monsters' DAMAGE:
    the P42 cells join `fields` (so NEW GAME restores them), damagecode's decls / leaves / table ride in
    `decls_wake` / `decide_lines` / `tables`, the slots run A_Fall and carry justhit (`p32a_slot(dmg=True)`), and
    `chase` names the per-slot flags the thing test (`solid`: mon_solid) and the door contact (`live`:
    mon_shootable) read -- mon_active for both without it.

    M7 P5: the monster mode "full" is "decide" with the attacks APPLIED (it needs a hurtable player mode,
    hurtcode.hurt_on, and vice versa -- asserted). It adds the MOBILES (docs/gp-p5-interface.md): `nmob` runtime
    things after the WAD's (monsters.mobile_rows' rule), one view row per mobile lump after the monsters' views
    (`mobile_view_rows`), their row-select stubs (`mobile_select_lines`) and `mobview`; the pools themselves
    (`proj`: projcode.proj_parts at this `nt`); damagecode's blood (`fx`); and `world`, the World the parts came from.

    M7 P6 (docs/gp-p67-interface.md 4.3 / 5; the player mode "full", `barrelcode.barrels_on`): the PUFFS join the
    mobiles' views (projcode `puffs`); the DROPS are `ndrop` more runtime things after the mobiles (nt + nmob + k,
    dropper k), each selecting its item's view row (`drop_view_rows`, from the STATIC bank `static_bank` =
    (spr_base, spr_ldbase, spr_dw): the item a map thing of that type is drawn with), never seen, never aimed; the
    BARRELS get one view row per state lump (`barrel_view_rows`, the anim bank) and `barview` (state -> row), which
    a RUNTIME barrel's stub looks up -- with its aim id 1 + nmon + b and radius class aimcode.RC_BARREL while it
    stands (S_BAR1 / S_BAR2: a live barrel's health is > 0 exactly there); `barrel` is barrelcode.barrel_parts,
    `bar_rt` {barrel: runtime thing}, `bar_view` {state: row} and `bar_rows` the rows (wall_renderer bakes the
    other barrels' views from them)."""
    from doomfj.monsters import view_of
    from doomfj.things import THING_ROW_BYTES
    from doomfj.wall_renderer import (DEG_MINH2_MON, MIN_SPRITE_H_MONSTER, anim_frames, anim_patches)
    from doomfj.world import World
    patches = anim_patches(sprite_wad, anim_frames(map_wad, mapname))
    groups = view_groups()
    nt = len(rt_things)
    views, keys, vidx = [], [], {}
    mview = [0] * (((len(groups) - 1) << 4) + 8)
    for g, (spr, fr) in enumerate(groups):
        letter = chr(ord("A") + fr)
        if not any(k[0] == spr and k[1] == letter for k in patches):
            continue                     # a type the map does not have: no monster reaches the group
        for r0 in range(8):
            v = view_of(patches, spr, fr, r0 + 1)
            if v not in vidx:
                vidx[v] = len(views)
                views.append(v)
                keys.append((spr, letter, 0) if (spr, letter, 0) in patches else (spr, letter, r0 + 1))
            mview[(g << 4) | r0] = nt + vidx[v]
    rows = []
    for (lump, mir), key in zip(views, keys):
        art = rm.art_of_lump(sprite_wad, lump, cache)
        base, dw, amir = anim_index[key]
        assert amir == mir and dw == art[2] and dw < 0x80, (key, amir, mir, dw)
        rows.append((art[5], art[3], art[4], art[6],
                     rm.sprite_tz_min_size(art[4], MIN_SPRITE_H_MONSTER) & 0xFFFFFFFF,
                     rm.sprite_tz_min_size(art[4], DEG_MINH2_MON) & 0xFFFFFFFF,
                     base, base + 2 * dw if spr_near else 0, 1, dw | (0x80 if mir else 0)))
    if not rows:
        return None                      # a map without monsters animates nothing
    assert len(THING_ROW_BYTES) == len(rows[0])
    # the monster slots, and which runtime thing each is
    assert mode in ("idle", "wake", "chase", "decide", "full", "push", "final"), mode   # M7 P8a: world.MONSTER_MODES
    # M7 P3.3 (D3 d): the leaf walk the game tier's picture asks for -- RAISES for a mode that cannot emit it.
    # `depth_order` None is GAME_RENDER_KW's; a unit fixture that builds no leaf walk passes False.
    depth = depth_walk(mode, depth_order)
    # M7 P3.2b: the chase mode is the wake mode plus the move; M7 P3.2c: the decide mode is the chase plus the
    # decisions; M7 P5: "full" is the decide mode with its attacks APPLIED; M7 P8a: "push" and "final" are "full"
    # and more (world.MONSTER_MODES) -- every rule of "full" holds in them
    wake = mode in ("wake", "chase", "decide", "full", "push", "final")
    chase = mode in ("chase", "decide", "full", "push", "final")
    decide = mode in ("decide", "full", "push", "final")
    full = monster_attacks_land(mode)
    from doomfj.damagecode import damage_on, fx_on
    damage = damage_on(player)
    assert not damage or decide, "damage (M7 P4.2a) runs on the decide mode's slots: mode %r" % mode
    # M7 P5 (doomfj.hurtcode): a player mode whose monsters HURT the player -- the player can die, and the slots
    # lose their target while he is dead (p32a_slot's `hurt`); the decide mode's slots carry it. The model hurts the
    # player in the monster mode "full" alone (combat: "decide" rolls and applies nothing), so the two must agree:
    # a "full" tier whose weapon cannot be hurt, or a hurtable player whose monsters never attack, is refused
    from doomfj.hurtcode import hurt_on
    hurt = hurt_on(player) and decide
    assert not decide or hurt == full, (
        "M7 P5: monster mode %r with player mode %r -- the monsters' attacks land (\"full\") exactly when the player "
        "can be hurt (hurtcode.HURT_PLAYER_MODES)" % (mode, player))
    # M7 P5 (docs/gp-p5-interface.md, THE MOBILE ROWS): the fireball and blood pools' runtime things nt .. nt + nmob - 1,
    # by the model's ONE rule (monsters.mobile_rows), and one VIEW row per mobile lump after the monsters' views
    from types import SimpleNamespace
    from doomfj.monsters import mobile_rows
    nmob = mobile_rows(SimpleNamespace(monsters=mode, player=player))
    bleed = fx_on(player)
    assert not nmob or full, ("M7 P5: the mobiles (%d rows) are emitted with the fireball pool, the monster mode "
                              "\"full\" -- mode %r, player %r" % (nmob, mode, player))
    assert not bleed or (damage and full), "M7 P5: the blood (fx_on) rides the damage and the pools"
    mob_first = nt + len(rows)
    # M7 P6: barrels, drops and puffs (the player mode "full")
    from doomfj.barrelcode import barrels_on
    loot = bool(nmob) and barrels_on(player)
    # M7 P8a (docs/gp-final-plan.md 3.0; doomfj.knockcode): KNOCKBACK's hooks -- every damage site names its inflictor
    # and the damage leaves call kb_go; each slot's turn opens on the knock move's splice point. Off in "full"
    from doomfj.world import knockback_on
    knock = loot and knockback_on(player, mode)
    # M7 P8a package C (docs/gp-final-plan.md 1.3; world.compositor_d3): THE COMPOSITOR RULES -- D3 a, the depth walk's
    # RANK (rank_threshold: the effects and the drops first), and D3 b, the barrels' soft exemption (`sp_ex`, set by a
    # runtime barrel's row select here and by a baked barrel's xor_by blocks in wall_renderer). Off in "full"
    from doomfj.world import compositor_d3
    d3 = loot and compositor_d3(player)
    assert not d3 or depth, "M7 P8a: D3 a ranks the depth walk -- a mode that walks no depth cannot take it"
    mob_rows, mob_view = (mobile_view_rows(rm, sprite_wad, anim_index, spr_near=spr_near, cache=cache,
                                           first=mob_first, puffs=loot) if nmob else ([], {}))
    rows = rows + mob_rows
    drop_row, bar_view, bar_rows = {}, {}, []
    if loot:
        assert static_bank is not None, "M7 P6: the drops draw from the static bank (spr_base, spr_ldbase, spr_dw)"
        d_rows, drop_row = drop_view_rows(rm, sprite_wad, static_bank, rt_things, spr_near=spr_near, cache=cache,
                                          first=nt + len(rows))
        rows = rows + d_rows
        bar_rows, bar_view = barrel_view_rows(rm, sprite_wad, anim_index, spr_near=spr_near, cache=cache,
                                              first=nt + len(rows))
        rows = rows + bar_rows
    nrows = nt + len(rows)
    rn = max(1, ((nrows - 1).bit_length() + 3) // 4)
    w = World(map_wad, mapname, boot_skill, rm=rm, sight_rule="seen" if wake else "los")
    nmon, schema = w.layout.nmon, w.schema
    if nmon == 0 or not rows:
        return None                      # a map without monsters animates nothing
    if loot:
        # M7 P6 (the GIB, damagecode `full`): every xdeath state a slot can enter has its views -- the state table
        # (monster_states follows every *state field) and a view row for each rotation (mview)
        for m in range(nmon):
            s_ = w.mon_info[m].xdeathstate
            while s_ != gd.S_NULL:
                st_ = gd.STATES[s_]
                g_ = groups.index((st_.sprite, st_.frame & gd.FF_FRAMEMASK))
                assert state_table_values()[gd.STATE_INDEX[s_]] and all(mview[(g_ << 4) | r_] for r_ in range(8)), (
                    "M7 P6: the gib state %s has no view row" % s_)
                if st_.tics < 0:
                    break
                s_ = st_.next
    slot_of = {_thing_key(t): m for m, t in enumerate(w.mon_things)}
    rt_slot = [slot_of.get(_thing_key(t)) for t in rt_things]
    assert sorted(m for m in rt_slot if m is not None) == list(range(nmon)), "every monster slot is a runtime thing"

    from doomfj.monsterdecide import P32C_FIELDS, type_decide
    from doomfj.damagecode import P42_FIELDS
    from doomfj.noisecode import NOISE_PLAYER_MODES
    # M7 P4.2b (doomfj.noisecode): a player whose shot makes NOISE -- A_Look's sound branch, the per-slot ambush flags
    hear = wake and player in NOISE_PLAYER_MODES
    fields = (P31_FIELDS + (P32A_FIELDS if wake else ()) + (P32B_FIELDS if chase else ())
              + (P32C_FIELDS if decide else ()) + (P42_FIELDS if damage else ()) + (P42B_FIELDS if hear else ()))
    slot_t = {m: t for t, m in enumerate(rt_slot) if m is not None}
    # the relink (docs/gp-monsters.md 8.4 piece 6): fj links the leaf lists by RUNTIME thing index, the model by
    # monster slot -- the lists' orders agree only while the slots run in runtime-thing order
    assert [slot_t[m] for m in range(nmon)] == sorted(slot_t.values()), (
        "the monster slots are not in runtime-thing order: the fj's leaf lists would part from the model's")

    def values(sk):
        w.reset(sk)
        return {f: list(getattr(w.ws, f)[:nmon]) for f in fields}

    boot = values(boot_skill)
    restart = []
    for sk in skills:
        v = values(sk)
        restart.append(["    hex.set %d, %s + %d*dw, %d" % (cell_nibbles(schema, f), f, cell_nibbles(schema, f) * m,
                                                            v[f][m] & (16 ** cell_nibbles(schema, f) - 1))
                        for f in fields for m in range(nmon)]
                       + (["    hex.set %d, sched_cursor, %d" % (cell_nibbles(schema, "sched_cursor"), w.ws.sched_cursor),
                           "    hex.zero %d, thseen" % nmon] if wake else [])
                       # M7 P3.2b: each monster's sector, and the barrels this skill stands
                       + (["    hex.set %d, msec, %d" % (2 * nmon, sum(w._mon_sector(m) << (8 * m) for m in range(nmon))),
                           "    hex.set %d, bar_solid, %d" % (max(1, len(w.barrel_things)),
                                                          sum(w.ws.bar_solid[b] << (4 * b)
                                                              for b in range(len(w.barrel_things)))),
                           # M7 P7: the movers' last state, as the level start's movers (all 0: every lift at its
                           # top, the switch not fired -- the boot image's zeros) -- else the first tic after a
                           # restart sees a mover "change" (tests/fj/test_restart_fj.py found it missing)
                           "    hex.zero %d, mh_prev" % (len(w.lift_order) + 1)]
                          if chase else [])
                       + (noise_restart_lines(w) if hear else []))           # M7 P4.2b: no node has heard a shot
    # the row select -- M7 P5: over the runtime things AND the mobiles (things nt .. nt + nmob - 1)
    # M7 P6: and the drops (nt + nmob .. + ndrop - 1)
    from doomfj.barrelcode import droppers
    drop_slots = droppers(w) if loot else []
    ndrop = len(drop_slots)
    ntm = nt + nmob + ndrop
    from doomfj.things import LIST_MAX_THINGS
    assert ntm <= LIST_MAX_THINGS and ntm <= 256, (nt, nmob, "the lists and the two-level select hold 254 things")
    sel = ["thsel_leaf:", "    sim.jump16 sp_ti + 1*dw, " + ", ".join(
        "thsel_h%d" % h if 16 * h < ntm else "thsel_none" for h in range(16))]
    for h in range((ntm + 15) // 16):
        sel += ["  thsel_h%d:" % h, "    sim.jump16 sp_ti, " + ", ".join(
            "thsel_s%d" % (16 * h + l) if 16 * h + l < ntm else "thsel_none" for l in range(16))]
    # M7 P4.2a (doomfj.aimcode): a tier whose player SHOOTS gives every runtime thing its aim id -- 1 + slot while
    # the monster is shootable (a corpse is not: damage clears it), 0 for any other thing -- and its radius class
    from doomfj.world import player_resolves
    shoot = player_resolves(player)
    # M7 P6: the runtime barrels (a barrel the bake leaves to the leaf lists): their barrel index
    bar_rt = {}
    if loot:
        bkey = {_thing_key(t): b for b, t in enumerate(w.barrel_things)}
        bar_rt = {bkey[_thing_key(t)]: i for i, t in enumerate(rt_things) if _thing_key(t) in bkey}
    rt_bar = {i: b for b, i in bar_rt.items()}
    for t, m in enumerate(rt_slot):
        sel.append("  thsel_s%d:" % t)
        if wake:
            sel.append("    hex.set w/4, sp_sa, thseen + %d*dw" % m if m is not None else "    hex.zero w/4, sp_sa")
        if shoot:
            sel.append("    hex.zero 2, sp_sid")
            if m is not None:
                assert w.mon_radius[m] in (20, 30), (m, w.mon_radius[m])
                sel += ["    hex.if0 1, mon_shootable + %d*dw, thsel_q%d" % (m, t),
                        "    hex.set 2, sp_sid, %d" % (m + 1),
                        "  thsel_q%d:" % t,
                        "    hex.set 1, sp_rc, %d" % int(w.mon_radius[m] == 30)]
        if m is not None:
            sel += ["    hex.mov 8, mr_tx, sp_x", "    hex.mov 8, mr_ty, sp_y",
                    "    hex.mov 1, mr_face, mon_facing + %d*dw" % m,
                    "    stl.fcall mon_rot_leaf, mr_ret",
                    "    mstate.lookup ts_row, mon_state + %d*dw" % (2 * m),
                    "    hex.mov 1, ts_idx, mr_rot",
                    "    hex.mov 2, ts_idx + 1*dw, ts_row + 4*dw",
                    "    hex.zero w/4, sp_ti",
                    "    mview.lookup sp_ti, ts_idx"]
        if t in rt_bar:                      # M7 P6: a runtime barrel -- its state's view; aimed while it stands
            sel += barrel_select_lines(t, rt_bar[t], nmon=nmon, shoot=shoot, ex=d3)
        sel.append("    stl.fret thsel_ret")
    sel += mobile_select_lines(nt, nmob, wake=wake, shoot=shoot)
    sel += drop_select_lines(nt + nmob, [drop_row[w.dropper[m]] for m in drop_slots], wake=wake, shoot=shoot)
    sel += ["  thsel_none:", "    stl.fret thsel_ret"]
    extra = {}
    if wake:
        w.reset(boot_skill)
        # M7 P3.2b: a monster that moves can stand in any sector -- every leaf's sector gets its REJECT row
        secs = (sorted({s_ for s_ in w.leaf_sector if s_ >= 0}) if chase
                else sorted({w._mon_sector(m) for m in range(nmon)}))
        slots = [dict(t=m, x=w.ws.mon_x[m], y=w.ws.mon_y[m], rj="rj%d" % w._mon_sector(m),
                      see_idx=gd.STATE_INDEX[w.mon_info[m].seestate],
                      see_tics=gd.STATES[w.mon_info[m].seestate].tics,
                      **({"mv": dict(rt=slot_t[m], radius=w.mon_radius[m], speed=w.mon_speed[m])} if chase else {}),
                      **({"dc": type_decide(w.mon_info[m])} if decide else {}),
                      **({"dmg": True} if damage else {}),
                      **({"hear": True, "sec": w._mon_sector(m)} if hear else {}),
                      **({"hurt": dict(sp=gd.STATE_INDEX[w.mon_info[m].spawnstate],
                                       spt=gd.STATES[w.mon_info[m].spawnstate].tics)} if hurt else {}),
                      **({"knock": True} if knock else {}))                      # M7 P8a: the knock move's splice
                 for m in range(nmon)]
        nleaf = len(w.cmap.subsectors)
        extra = {
            "tic_after_eye": ((p32b_change_sector_lines(w, nmon, exit_guard=True) if chase else [])
                              + p32a_tic_lines(schema, nmon, slots, exit_guard=True)
                              + ["    hex.zero %d, thseen" % nmon]),               # the render marks this frame's
            "tables": ([generate_dispatch_table_fj("rj%d" % s_, [int(w.reject.visible(s_, q)) for q in range(w.reject.nsec)],
                                                   index_nibbles=2, result_nibbles=1) for s_ in secs]
                       + [generate_dispatch_table_fj("lfsec", list(w.leaf_sector),
                                                     index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4),
                                                     result_nibbles=2)]),
            "leaves": p32a_leaves() + (p32b_rj_leaf(secs) if chase else []) + (noise_leaf_lines(w) if hear else []),
            "decls_wake": (p32a_decls(schema, nmon, {**{f: boot[f] for f in P32A_FIELDS}, "sched_cursor": w.ws.sched_cursor},
                                 nmon)
                      + P32A_SCRATCH + ["sp_sa: hex.vec w/4", "trb_seenf: hex.vec 1", "trb_one: hex.vec 1, 1"]
                      + ([ambush_decl(nmon, boot["mon_ambush"])] + noise_decls(w) if hear else [])
                      + (["mt_ms: hex.vec 2"] if hear and not chase else [])),     # nz_heard's operand (chase: p32b)
        }
        if chase:
            from doomfj.collision import MON_CELL_DECLS
            from doomfj.monstermove import monster_seed_decls, static_blockers
            from doomfj.things import LEAF_LINK_DECLS
            things, var = static_blockers(w)
            assert not var, "a decoration some skill lacks needs its mc_don flag set at NEW GAME"
            nb = max(1, len(w.barrel_things))
            extra["decls_wake"] += (
                p32b_decls(schema, nmon, {f: boot[f] for f in P32B_FIELDS}, [w._mon_sector(m) for m in range(nmon)])
                + MON_CELL_DECLS + monster_seed_decls() + LEAF_LINK_DECLS
                + ["bar_solid: hex.vec %d, %d" % (nb, sum(w.ws.bar_solid[b] << (4 * b)
                                                          for b in range(len(w.barrel_things)))),
                   "mh_prev: hex.vec %d" % (len(w.lift_order) + 1), "mcf_val: hex.vec 4", "mcf_hit: hex.vec 1",
                   "mcf_ret: hex.vec w/4"])
            if decide:                                 # M7 P3.2c: the justattacked flags, the context, the LOS
                from doomfj.monsterdecide import context_decls
                from doomfj.monstersight import SL_DECLS, near_los_lines
                extra["decls_wake"] += (p32c_decls(schema, nmon, {f: boot[f] for f in P32C_FIELDS})
                                        + context_decls() + SL_DECLS)
                extra["decide_lines"] = near_los_lines(w)
                barrel = None
                if loot:                               # M7 P6: the barrels, the blasts, the drops (barrelcode)
                    from doomfj.barrelcode import barrel_parts
                    # M7 P6+P7 (the integration): a baked barrel's thvis slot -- package A's layout (MonsterViews,
                    # the one definition: things.vanishable_slots) -- is zeroed when the barrel is removed
                    from doomfj.monsters import MonsterViews
                    _mv = MonsterViews(rm, map_wad, mapname, sprite_wad, w)
                    bar_vis = {b: _mv.vis_slots[di] for b, di in enumerate(_mv.bdi) if di in _mv.vis_slots}
                    assert not set(bar_vis) & set(bar_rt) and len(bar_vis) + len(bar_rt) == len(w.barrel_things)
                    barrel = barrel_parts(w, nt=nt, slot_rt=[slot_t[m] for m in range(nmon)], boot_skill=boot_skill,
                                          skills=skills, barrel_rt=bar_rt, barrel_vis=bar_vis,
                                          **({"knock": True} if knock else {}))
                    assert barrel["drop_first"] == nt + nmob and barrel["ndrop"] == ndrop
                    extra["barrel"] = barrel
                if damage:                             # M7 P4.2a: the monsters' damage (damagecode)
                    from doomfj.damagecode import damage_parts
                    # M7 P5: a hit in reach spawns the BLOOD (damagecode.fx_on: dm_leaf calls projcode's fx_spawn)
                    # M7 P6: the barrels' ids, the blast, the gib and the drops (`full`)
                    dmp = damage_parts(w, slot_rt=[slot_t[m] for m in range(nmon)], boot_skill=boot_skill,
                                       fx=bleed, full=loot, nbar=barrel["nbar"] if barrel else 0,
                                       drops=barrel["drops"] if barrel else None,
                                       **({"knock": True} if knock else {}))
                    extra["decls_wake"] += dmp["decls"]
                    extra["decide_lines"] += dmp["lines"]
                    extra["tables"] += dmp["tables"]
                    extra["justhit"] = True
                if full:                               # M7 P5: the fireball and blood pools (doomfj.projcode)
                    from doomfj.projcode import proj_parts
                    extra["proj"] = proj_parts(w, nt=nt, puffs=loot, **({"knock": True} if knock else {}))
                    extra["proj"]["nt"] = nt
            # M7 P3.3 (D3 d): the game tier draws a leaf's runtime things nearest first when the ONE game-tier
            # render setting says so (depth_walk, above) -- the walk's registers (sim.thing_pass_depth)
            if depth:
                extra["decls_wake"] += P33_DECLS
                extra["depth"] = True
                if d3:                         # M7 P8a (C): the rank's register and the barrel flag
                    extra["decls_wake"] += D3_DECLS
            extra["chase"] = dict(
                static_things=things, lift_walk=list(w.lift_walk), lift_order=list(w.lift_order),
                mon_door_boxes=[(si, w.mon_door_boxes[si]) for si in w.door_order if si in w.mon_door_boxes],
                slots_rt=[(slot_t[m], w.mon_radius[m]) for m in range(nmon)],
                mon_radius=[w.mon_radius[m] for m in range(nmon)], height=w.mon_height[0],
                # M7 P4.2a: what blocks a move (World._thing_blocker: MF_SOLID) and what holds a closing door
                # (World.door_touched: alive -- mon_shootable, damagecode.check_model_rules)
                solid="mon_solid" if damage else "mon_active", live="mon_shootable" if damage else "mon_active",
                # M7 P5: the emitter's things_leaf_lines(hurt=), decide_leaves(full=) and weapon_parts(hurt=)
                **({"hurt": True} if hurt else {}))
            assert len(set(w.mon_height[:nmon])) == 1, "one monster height: try_move_mon takes it at compile time"
    if knock:
        extra["knock"] = True          # M7 P8a: the emitter asserts its own `_KNOCK` agrees
    if d3:
        # M7 P8a (C): the emitter asserts its own `_D3` agrees, passes `rank0` to sim.thing_pass_depth (D3 a) and the
        # scenery soft flag to frame.thing_record_body (D3 b). The rank rides bit 15 of the aprox key: every key the
        # walk can form -- two points of the map -- is <= the map's width + height (P_AproxDistance <= |dx| + |dy|)
        _vx = [v.x for v in map_wad.vertexes(mapname)]
        _vy = [v.y for v in map_wad.vertexes(mapname)]
        assert (max(_vx) - min(_vx)) + (max(_vy) - min(_vy)) < 0x8000, (
            "M7 P8a (D3 a): an aprox key may reach bit 15, where sim.rank_key puts the rank")
        from doomfj.world import FIREBALL_POOL, FX_POOL
        assert nmob == FIREBALL_POOL + FX_POOL, (nmob, "the rank's row ranges are the P5 pools'")
        extra["d3"] = True
        extra["rank0"] = rank_threshold(nt)
    return {
        "mode": mode, **extra,
        "view_rows": rows, "nrows": nrows, "views": views, "rt_slot": rt_slot, "nmon": nmon, "schema": schema,
        "mview": generate_dispatch_table_fj("mview", mview, index_nibbles=3, result_nibbles=rn),
        "mrot": rot_table_fj(), "select": sel, "rotation": rotation_leaf_lines(1),
        "tic": [] if wake else mon_tic_lines(schema, nmon),
        "decls": (monster_decls(schema, nmon, boot) + MT_DECLS + ROT_DECLS
                  + ["ts_row: hex.vec 6", "ts_idx: hex.vec 3", "thsel_ret: hex.vec w/4",
                     "trb_mir: hex.vec 1", "trb_mu: hex.vec 2"]
                  + (["ts_mob: hex.vec 2"] if nmob else [])),                  # M7 P5: a mobile's state
        "restart": restart, "view_heights": sorted({max(1, r[2]) for r in rows}),
        # M7 P5: the mobiles -- how many runtime things follow the WAD's, the view row of each pool state (`mobview`,
        # indexed by the state cell pj_st / fx_st), the first mobile view row, the model World the parts came from
        "nmob": nmob, "mob_view": mob_view, "mob_first": mob_first, "world": w,
        **({"mobview": generate_dispatch_table_fj("mobview", [mob_view.get(i, 0) for i in range(max(mob_view) + 1)],
                                                  index_nibbles=2, result_nibbles=rn)} if nmob else {}),
        # M7 P6: the drops' runtime things (after the mobiles), the barrels' views and the runtime barrels
        "ndrop": ndrop, "drop_row": drop_row, "bar_view": bar_view, "bar_rows": bar_rows, "bar_rt": bar_rt,
        **({"barview": generate_dispatch_table_fj("barview", [bar_view.get(i, 0) for i in range(max(bar_view) + 1)],
                                                  index_nibbles=2, result_nibbles=rn)} if bar_view else {}),
    }


# ---- M7 P5: the MOBILES' rows (docs/gp-p5-interface.md, THE MOBILE ROWS) ---------------------------------------
def mobile_view_rows(rm, sprite_wad, anim_index, *, spr_near: bool, cache: dict, first: int, puffs: bool = False):
    """-> (rows, {state index: row}): one thing row per distinct mobile LUMP (`monsters.mobile_lump` of every pool
    state, projcode.pool_states' order), `things.thing_rows`' layout -- how the oracle draws a mobile
    (reference_model.render_wall_frame(mobiles=)), field by field:
      * its state's frame at rotation 0, never mirrored: the anim bank's `(sprite, letter, 0)` region, dw's bit 7 clear;
      * z: `project_thing` reads the floor only as `(floor + top) << 16`, so standing MISSILE_Z above the leaf's floor
        IS the art's top offset + MISSILE_Z (sim.thing_load adds the row's int16 zoff to the leaf's `ss_flr`);
      * the SCENERY class (sp_mon 0: THING_BUDGET), at the BASE minimum height MIN_SPRITE_H -- both depth bounds
        (sp_tzmax, and sp_tzmax2 which the graduated acceptance switches to) are the base one, so the raise binds
        nothing, as the oracle's `not mob` keeps it;
      * the near (LD) region 2*dw on, as a monster view's.
    M7 P6+P7 E (the owner, 2026-10-05: "you must always show the fireballs"): under the game picture's ACTORS RULE
    (reference_model.GAME_RENDER_KW `exempt_actors`) a mobile is an ACTOR -- the monster class (sp_mon 1: n_mon, no
    B-gate in frame.thing_record_body) at the MONSTER base bound MIN_SPRITE_H_MONSTER, as the oracle's `act` draws it.
    `first`: the row index of the first one (after the runtime things and the monsters' views). M7 P6 (`puffs`): the
    puff's states too (projcode.pool_states(puffs=True)), PUFFA0 .. PUFFD0 at MISSILE_Z as blood."""
    from doomfj.monsters import mobile_lump
    from doomfj.projcode import pool_states
    from doomfj.reference_model import GAME_RENDER_KW, MIN_SPRITE_H, MIN_SPRITE_H_MONSTER, MISSILE_Z
    actor = bool(GAME_RENDER_KW.get("exempt_actors"))
    rows, lump_row, by_state = [], {}, {}
    for s in pool_states(puffs):
        lump = mobile_lump(s)
        if lump not in lump_row:
            assert len(lump) == 6 and lump[5] == "0", (s, lump, "a mobile is drawn from a single-rotation lump")
            base, dw, mir = anim_index[(lump[:4], lump[4], 0)]
            art = rm.art_of_lump(sprite_wad, lump, cache)
            assert not mir and dw == art[2] and dw < 0x80, (lump, mir, dw, art[2])
            tzmin = rm.sprite_tz_min_size(art[4], MIN_SPRITE_H_MONSTER if actor else MIN_SPRITE_H) & 0xFFFFFFFF
            rows.append((art[5], art[3], art[4], art[6] + MISSILE_Z, tzmin, tzmin,
                         base, base + 2 * dw if spr_near else 0, 1 if actor else 0, dw))
            lump_row[lump] = first + len(rows) - 1
        by_state[gd.STATE_INDEX[s]] = lump_row[lump]
    return rows, by_state


def mobile_select_lines(nt: int, nmob: int, *, wake: bool, shoot: bool) -> list:
    """the row select's stubs for the mobiles (`thsel_leaf`, p31_parts): thing nt + s for fireball slot s < FIREBALL_POOL,
    nt + FIREBALL_POOL + s for blood slot s -- each stub copies its slot's state cell (pj_st / fx_st) into `ts_mob` and
    jumps to ONE shared tail (copy-stub + shared leaf: no per-slot logic), which clears what a scenery thing clears
    (no seen flag, aim id 0: never seen, never aimed) and looks the state's view row up in `mobview`"""
    if not nmob:
        return []
    from doomfj.world import FIREBALL_POOL, FX_POOL
    assert nmob == FIREBALL_POOL + FX_POOL, (nmob, FIREBALL_POOL, FX_POOL)
    out = []
    for k in range(nmob):
        cell = ("pj_st + %d*dw" % (2 * k) if k < FIREBALL_POOL else "fx_st + %d*dw" % (2 * (k - FIREBALL_POOL)))
        out += ["  thsel_s%d:" % (nt + k), "    hex.mov 2, ts_mob, %s" % cell, "    ;thsel_mob"]
    return out + (["  thsel_mob:"] + (["    hex.zero w/4, sp_sa"] if wake else [])
                  + (["    hex.zero 2, sp_sid"] if shoot else [])
                  + ["    hex.zero w/4, sp_ti", "    mobview.lookup sp_ti, ts_mob", "    stl.fret thsel_ret"])


# ---- M7 P6: the DROPS' and the BARRELS' rows (docs/gp-p67-interface.md 5) -------------------------------------
def drop_types(rt_things) -> List[int]:
    """the item types the map's monsters drop (combat.DROP_ITEM of gamedata.DROPS), ascending"""
    from doomfj.combat import DROP_ITEM
    names = {gd.MOBJINFO[n].doomednum: n for n in gd.MOBJINFO}
    out = set()
    for t in rt_things:
        name = names.get(t.type)
        if name and name in gd.DROPS and gd.DROPS[name] in DROP_ITEM:
            out.add(DROP_ITEM[gd.DROPS[name]])
    return sorted(out)


def drop_view_rows(rm, sprite_wad, static_bank, rt_things, *, spr_near: bool, cache: dict, first: int):
    """-> (rows, {item type: row}): one thing row per dropped item type -- the item a MAP thing of the type is drawn
    with (its static-bank kind: `things.thing_rows`' fields), except as the oracle draws a drop
    (reference_model.render_wall_frame(mobiles=) with z 0): standing ON the floor (the art's top + 0), the scenery
    class at the BASE minimum height in both depth bounds (P5's mobile rule: never the raised bar)"""
    from doomfj.reference_model import MIN_SPRITE_H
    spr_base, spr_ldbase, spr_dw = static_bank
    rows, row_of = [], {}
    for ty in drop_types(rt_things):
        art = rm.sprite_art(sprite_wad, ty, cache)
        assert art is not None and ty in spr_base, (ty, "a dropped item the static bank does not hold")
        assert spr_dw[ty] == art[2] and spr_dw[ty] < 0x80, (ty, spr_dw[ty], art[2])
        tzmin = rm.sprite_tz_min_size(art[4], MIN_SPRITE_H) & 0xFFFFFFFF
        rows.append((art[5], art[3], art[4], art[6], tzmin, tzmin, spr_base[ty],
                     spr_ldbase[ty] if spr_near else 0, 0, spr_dw[ty]))
        row_of[ty] = first + len(rows) - 1
    return rows, row_of


def barrel_view_rows(rm, sprite_wad, anim_index, *, spr_near: bool, cache: dict, first: int):
    """-> (rows, {state index: row}): one thing row per barrel state's lump (its frame at rotation 0: BAR1A0, BAR1B0,
    BEXPA0 .. BEXPE0, `monsters.mobile_lump`'s rule), from the anim bank as a mobile's -- but a barrel stays a
    SCENERY thing with the GRADUATED bounds a map barrel has today (`things.thing_rows`: MIN_SPRITE_H, and
    DEG_MINH2_SCENERY for the raised bar), standing on its floor (the art's top + 0)"""
    from doomfj.barrelcode import barrel_states
    from doomfj.monsters import mobile_lump
    from doomfj.reference_model import DEG_MINH2_SCENERY, MIN_SPRITE_H
    rows, lump_row, by_state = [], {}, {}
    for s in barrel_states():
        lump = mobile_lump(s)
        if lump not in lump_row:
            base, dw, mir = anim_index[(lump[:4], lump[4], 0)]
            art = rm.art_of_lump(sprite_wad, lump, cache)
            assert not mir and dw == art[2] and dw < 0x80, (lump, mir, dw, art[2])
            rows.append((art[5], art[3], art[4], art[6],
                         rm.sprite_tz_min_size(art[4], MIN_SPRITE_H) & 0xFFFFFFFF,
                         rm.sprite_tz_min_size(art[4], DEG_MINH2_SCENERY) & 0xFFFFFFFF,
                         base, base + 2 * dw if spr_near else 0, 0, dw))
            lump_row[lump] = first + len(rows) - 1
        by_state[gd.STATE_INDEX[s]] = lump_row[lump]
    return rows, by_state


def barrel_select_lines(t: int, b: int, *, nmon: int, shoot: bool, ex: bool = False) -> list:
    """runtime thing t, barrel b: the row of its state (`barview` on bar_st); while it STANDS (S_BAR1 / S_BAR2 --
    `combat.shootable_targets`' state != 0 and health > 0: the killing blow takes S_BEXP) its aim id 1 + nmon + b and
    the barrel's radius class. A removed barrel is in no list, so its stub never runs at state 0.
    M7 P8a (C, D3 b) `ex`: in every state the stub SETS `sp_ex` -- the barrel flag frame.thing_record_body's soft test
    and count read (no soft raise, not counted); sim.thing_pass_depth (its `ex`) zeroes it after the record"""
    from doomfj.aimcode import RC_BARREL
    from doomfj.barrelcode import barrel_states
    stand = [gd.STATE_INDEX[s] for s in barrel_states()[:2]]
    assert [gd.STATES[s].sprite for s in barrel_states()[:2]] == ["BAR1", "BAR1"] and stand[1] == stand[0] + 1
    out = []
    if shoot:
        L = "thsel_b%d" % t
        out += ["    hex.set 2, ts_mob, %d" % stand[0],
                "    hex.cmp 2, bar_st + %d*dw, ts_mob, %s_v, %s_a, %s_b" % (2 * b, L, L, L),
                "  %s_b:" % L,
                "    hex.inc 2, ts_mob",
                "    hex.cmp 2, bar_st + %d*dw, ts_mob, %s_v, %s_a, %s_v" % (2 * b, L, L, L),
                "  %s_a:" % L,
                "    hex.set 2, sp_sid, %d" % (1 + nmon + b),
                "    hex.set 1, sp_rc, %d" % RC_BARREL,
                "  %s_v:" % L]
    return out + (["    hex.set 1, sp_ex, 1"] if ex else []) + [
        "    hex.zero w/4, sp_ti", "    barview.lookup sp_ti, bar_st + %d*dw" % (2 * b)]


def drop_select_lines(first: int, rows: Sequence[int], *, wake: bool, shoot: bool) -> list:
    """the row select's stubs for the drops: thing first + k selects its item's view row (a constant), no seen flag,
    aim id 0 -- one shared tail"""
    if not rows:
        return []
    out = []
    for k, row in enumerate(rows):
        out += ["  thsel_s%d:" % (first + k), "    hex.zero w/4, sp_ti", "    hex.set w/4, sp_ti, %d" % row,
                "    ;thsel_drop"]
    return out + (["  thsel_drop:"] + (["    hex.zero w/4, sp_sa"] if wake else [])
                  + (["    hex.zero 2, sp_sid"] if shoot else []) + ["    stl.fret thsel_ret"])


# ---- P3.2a: the WAKE tic (docs/gp-monsters.md 8.3) -------------------------------------------------------------
P32A_FIELDS = ("mon_target", "mon_reaction", "mon_threshold", "mon_movedir")
P42B_FIELDS = ("mon_ambush",)       # M7 P4.2b (doomfj.noisecode): the per-slot cell the noise adds
HEAVY_IDS = (MON_ACTIONS.index("A_Chase"), MON_ACTIONS.index("A_FaceTarget"),
             MON_ACTIONS.index("A_PosAttack"), MON_ACTIONS.index("A_SPosAttack"),
             MON_ACTIONS.index("A_TroopAttack"), MON_ACTIONS.index("A_SargAttack"))
NEAR_UNITS = NEAR                    # doomfj.sight.NEAR (R6: one source): REJECT wakes within this
BEHIND_REACH = LOOK_BEHIND_REACH     # world.LOOK_BEHIND_REACH: P_LookForPlayers sees behind within this


def wake_reachable_actions() -> set:
    """the actions a monster runs in the WAKE mode: its spawn states' (A_Look) and its see states' (A_Chase) -- the
    wake mode decides no attack, so no attack or pain state is ever entered"""
    acts = set()
    for mt in MONSTER_TYPES:
        info = gd.MOBJINFO[mt]
        for s0 in (info.spawnstate, info.seestate):
            s, seen = s0, set()
            while s and s != gd.S_NULL and s not in seen:
                seen.add(s)
                acts.add(gd.STATES[s].action)
                s = gd.STATES[s].next
    return acts


def _sub16(dst, a, b):
    return ["    hex.mov 4, %s, %s" % (dst, a), "    hex.sub 4, %s, %s" % (dst, b)]


P32A_PERSISTED = ("mon_target", "mon_reaction", "mon_threshold", "mon_movedir", "sched_cursor", "thseen")


def persisted_monster_decls(w, mode: str, damage=None, player: str = None) -> list:
    """the monsters' PERSISTED cells as the emitter declares them, for the game tier's model `mode` (widths from the
    schema; values do not matter): the restore sets' standalone globals (scratchpad/m5_setfile.py) and the test that
    checks them (tests/host/test_restore_set_shipped.py) both read this one list. `damage` (M7 P4.2a): the P42
    cells too -- None reads the game tier's PLAYER_MODE (wall_renderer, damagecode.damage_on), as the emitter does.
    `player` (M7 P4.2b): the player's model mode for the noise's cells -- None reads wall_renderer.PLAYER_MODE too,
    so no caller can forget it and key a set without them"""
    if player is None:
        from doomfj.wall_renderer import PLAYER_MODE         # lazy: the emitter imports this module
        player = PLAYER_MODE
    n = w.layout.nmon
    if damage is None:
        from doomfj.damagecode import damage_on
        from doomfj.wall_renderer import PLAYER_MODE
        damage = damage_on(PLAYER_MODE) and mode in ("decide", "full", "push", "final")   # M7 P5: "full" decides too
    out = monster_decls(w.schema, n)
    if mode in ("wake", "chase", "decide", "full", "push", "final"):     # M7 P8a: "push" / "final" are "full"'s
        out += [d for d in p32a_decls(w.schema, n, {f: [0] * n for f in P32A_FIELDS}, n)
                if d.split(":")[0] in P32A_PERSISTED]
    if mode in ("chase", "decide", "full", "push", "final"):          # M7 P3.2b: the move's per-slot cells and msec, the barrels, mh_prev
        out += [d for d in p32b_decls(w.schema, n, {f: [0] * n for f in P32B_FIELDS}, [0] * n)
                if d.split(":")[0] in P32B_FIELDS + ("msec",)]
        out += ["bar_solid: hex.vec %d" % max(1, len(w.barrel_things)),
                "mh_prev: hex.vec %d" % (len(w.lift_order) + 1)]
    if mode in ("decide", "full", "push", "final"):       # M7 P3.2c: the missile decision's flag
        from doomfj.monsterdecide import P32C_FIELDS
        out += p32c_decls(w.schema, n, {f: [0] * n for f in P32C_FIELDS})
    if damage:                           # M7 P4.2a: health, shootable, solid, justhit
        from doomfj.damagecode import P42_FIELDS, field_decls
        out += field_decls(w.schema, n, {f: [0] * n for f in P42_FIELDS})
    from doomfj.noisecode import NOISE_PLAYER_MODES, PERSIST as NOISE_PERSIST
    if mode in ("wake", "chase", "decide", "full", "push", "final") and player in NOISE_PLAYER_MODES:   # M7 P4.2b: the alerts, the ambushers
        out += [d for d in [ambush_decl(n, [0] * n)] + noise_decls(w) if d.split(":")[0] in NOISE_PERSIST]
    return out


def p32a_decls(schema, nmon: int, values: dict, nthings: int) -> list:
    """the wake tic's cells (target, reaction, threshold, movedir per slot; the cursor), its scratch, and the
    per-SLOT seen flags `thseen` the render writes (`nthings` = the slots they cover)"""
    out = []
    for name in P32A_FIELDS:
        nib = cell_nibbles(schema, name)
        vals = values[name]
        packed = sum(v << (4 * nib * m) for m, v in enumerate(vals))
        out.append("%s: hex.vec %d, %d" % (name, nib * nmon, packed))
    cn = cell_nibbles(schema, "sched_cursor")
    out += ["sched_cursor: hex.vec %d, %d" % (cn, values.get("sched_cursor", 0)),
            "mt_used: hex.vec 1", "mt_fdef: hex.vec %d" % cn, "mt_nxt: hex.vec 2",
            "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
            "mt_t: hex.vec 4", "mt_rj: hex.vec 1", "mt_ti: hex.vec 2",
            "thseen: hex.vec %d" % max(1, nthings), "psec: hex.vec 2"]
    return out


FACING_BEHIND = {                    # world.behind: dot(FACING_VEC[f], (dx, dy)) < 0, as a sign test per facing
    0: ("dx", "neg"), 1: ("sum", "neg"), 2: ("dy", "neg"), 3: ("dydx", "neg"),
    4: ("dx", "pos"), 5: ("sum", "pos"), 6: ("dy", "pos"), 7: ("dxdy", "neg")}


def _sign_branch(cell, kind, yes, no):
    """jump to `yes` when the 4-nibble signed `cell` is negative (`neg`) / strictly positive (`pos`), else `no`"""
    if kind == "neg":
        return ["    hex.if_flags %s + 3*dw, 0xFF00, %s, %s" % (cell, no, yes)]
    return ["    hex.if_flags %s + 3*dw, 0xFF00, %s_z, %s" % (cell, yes, no),
            "  %s_z:" % yes, "    hex.if0 4, %s, %s" % (cell, no), "    ;%s" % yes]


def p32a_slot(m: int, *, t: int, x: int, y: int, rj: str, see_idx: int, see_tics: int, schema, mv=None,
              dc=None, dmg: bool = False, hear: bool = False, sec: int = None, hurt=None, knock: bool = False) -> list:
    """one slot of the wake tic -- the model's `_monsters_phase` step for slot m, A_Look and the wake mode's
    A_Chase (docs/gp-monsters.md 8.3). x, y: its spawn point (a monster never moves in this mode); rj: the D4
    REJECT row of its spawn sector (indexed by the player's sector); t: its seen flag's index (`thseen`).

    `mv` (M7 P3.2b, the CHASE mode: `dict(rt=runtime thing, radius=, speed=)`): the monster MOVES -- A_Look reads
    its position from `thpos_rt` and its REJECT row by its sector (`msec`, mt_rj_leaf) at run time, and A_Chase
    goes on after the turn to the move (monstermove.chase_leaf_lines: movecount, P_Move, P_NewChaseDir) through
    the context cells, its own `mon_active` cleared around the call so the thing test skips it.

    `dc` (M7 P3.2c, the DECIDE mode: `monsterdecide.type_decide`'s dict): A_Chase decides before it moves
    (`mm_decide`), a decision enters the melee or missile state, and the attack states' actions run
    (`md_attack`: the facing and the draws).

    `dmg` (M7 P4.2a, a player mode whose shots hurt: damagecode): monsters die -- A_Fall clears the slot's
    `mon_solid`, the move excludes the mover by its `mon_solid` (the thing test reads mon_solid, World._thing_blocker),
    and the decision carries `mon_justhit` (`mm_jh`, A_Chase's P_CheckMissileRange).

    `hear` (M7 P4.2b, the player mode "hit": doomfj.noisecode): A_Look's SOUND branch first, as the model's -- the
    node of the monster's sector (`msec` with `mv`, else its spawn sector `sec`) heard a shot (`nz_heard`): the
    target is set, and a monster without MTF_AMBUSH (`mon_ambush`) wakes; an ambusher needs the waking sight (seen,
    or the REJECT row within 128) and wakes without the facing test, or else does not wake at all (the model's
    look that follows asks the same sight). A_FaceTarget clears `mon_ambush` (p32c_slot_lines).

    `hurt` (M7 P5, doomfj.hurtcode: the player can die -- `dict(sp=the spawn state's index, spt=its tics)`): the
    target is LOST while the player is dead (`p_dead`, one flag: hurtcode keeps p_hp <= 0 <=> p_dead), as the model's
    `player_alive()` guards -- A_Look neither hears nor sees (both of its branches need a live player); A_Chase's
    threshold resets instead of counting down, and after the turn the monster returns to its spawn state (its
    A_Look runs at once in the model and changes nothing more: the threshold is already 0) instead of deciding or
    moving.

    `knock` (M7 P8a, world.knockback_on): the SPLICE POINT of the slot's knock move (doomfj.knockcode
    .monster_slot_lines: P_MobjThinker's P_XYMovement before the state's tics), right after the "not active" skip."""
    ns, nt, nf = cell_nibbles(schema, "mon_state"), cell_nibbles(schema, "mon_tics"), cell_nibbles(schema, "mon_facing")
    nthr = cell_nibbles(schema, "mon_threshold")
    assert not hear or mv or sec is not None, "a hearing slot needs its sector: msec (mv) or the spawn sector"
    ST, TI, AC = "mon_state + %d*dw" % (ns * m), "mon_tics + %d*dw" % (nt * m), "mon_active + %d*dw" % m
    FA, TG = "mon_facing + %d*dw" % (nf * m), "mon_target + %d*dw" % m
    RE, TH, MD = "mon_reaction + %d*dw" % m, "mon_threshold + %d*dw" % (nthr * m), "mon_movedir + %d*dw" % m
    L = "mw%d_" % m
    nxt = "mw%d_next" % m
    out = ["  mw%d:" % m,
           "    hex.if0 2, mt_n, mt_end",
           "    hex.dec 2, mt_n",
           "    hex.if0 1, %s, %s" % (AC, nxt),
           *(_knock_slot_lines(m) if knock else []),                  # M7 P8a: the knock move (package K)
           "    hex.if_flags %s, %d, %sgo, %s" % (TI, 1 << TICS_FOREVER, L, nxt),
           "  %sgo:" % L,
           "    hex.if0 1, %s, %sready" % (TI, L),              # tics 0 at entry: deferred last tic -- READY
           "    hex.dec 1, %s" % TI,
           "    hex.if0 1, %s, %sready" % (TI, L),
           "    ;%s" % nxt,
           "  %sready:" % L,
           "    mstate.lookup mt_row, %s" % ST,
           "    hex.mov 2, mt_nxt, mt_row",
           "    mstate.lookup mt_row, mt_nxt",
           "    hex.if_flags mt_row + 3*dw, %d, %slight, %sheavy" % (sum(1 << h for h in HEAVY_IDS), L, L),
           "  %sheavy:" % L,
           "    hex.if_flags mt_used, %d, %stake, %sdefer" % (1 << K_SLOTS, L, L),
           "  %sdefer:" % L,                                  # no slot: tics stay 0, served first next tic
           "    hex.if0 2, mt_fdef, %sfirst" % L,
           "    ;%s" % nxt,
           "  %sfirst:" % L,
           "    hex.set 2, mt_fdef, %d" % (m + 1),
           "    ;%s" % nxt,
           "  %stake:" % L,
           "    hex.inc 1, mt_used",
           "  %slight:" % L,
           "    hex.mov 2, %s, mt_nxt" % ST,
           "    hex.mov 1, %s, mt_row + 2*dw" % TI,
           "    sim.jump16 mt_row + 3*dw, %s" % ", ".join(_action_targets(L, nxt, dc, fall=dmg)),
           # ---- A_Look: threshold 0; no sound before P4; P_LookForPlayers (not all around) -----------------
           "  %slook:" % L,
           "    hex.zero %d, %s" % (nthr, TH),
           *(["    hex.if1 1, p_dead, %s" % nxt] if hurt else []),        # M7 P5: no live player to hear or see
           *(["    hex.zero 1, nz_amb",                                   # M7 P4.2b: the sound branch
              ("    hex.mov 2, mt_ms, msec + %d*dw" % (2 * m) if mv else "    hex.set 2, mt_ms, %d" % (sec or 0)),
              "    stl.fcall nz_heard, nz_hret",
              "    hex.if0 1, nz_h, %ssee" % L,
              "    hex.set 1, %s, 1" % TG,
              "    hex.if0 1, mon_ambush + %d*dw, %swake" % (m, L),     # not an ambusher: wakes at once
              "    hex.set 1, nz_amb, 1",                                 # an ambusher: the sight decides
              "  %ssee:" % L] if hear else []),
           "    hex.mov 4, mt_dx, viewx + 4*dw",
           ("    hex.sub 4, mt_dx, thpos_rt + %d*dw" % (16 * mv["rt"] + 4) if mv else
            "    hex.sub_constant 4, mt_dx, %d" % (x & 0xFFFF)),
           "    hex.mov 4, mt_dy, viewy + 4*dw",
           ("    hex.sub 4, mt_dy, thpos_rt + %d*dw" % (16 * mv["rt"] + 12) if mv else
            "    hex.sub_constant 4, mt_dy, %d" % (y & 0xFFFF)),
           "    stl.fcall mt_dist_leaf, mt_ret",                  # mt_d = P_AproxDistance(dx, dy)
           "    hex.if1 1, thseen + %d*dw, %sbehind" % (t, L),     # seen by last frame's picture
           "    hex.cmp 4, mt_d, mt_c128, %snear, %snear, %s" % (L, L, nxt),
           "  %snear:" % L,
           "    stl.fcall mt_psec_leaf, mt_ret",                  # psec, once a frame
           *(["    hex.mov 2, mt_ms, msec + %d*dw" % (2 * m), "    stl.fcall mt_rj_leaf, mt_rjret"] if mv else
             ["    %s.lookup mt_rj, psec" % rj]),
           "    hex.if0 1, mt_rj, %s" % nxt,
           "  %sbehind:" % L,                                  # behind and beyond 64: not seen
           *(["    hex.if1 1, nz_amb, %swake" % L] if hear else []),   # a heard ambusher in sight: no facing test
           "    sim.jump16 %s, %s" % (FA, ", ".join(["%sf%d" % (L, k) for k in range(8)] + [nxt] * 8))]
    for k in range(8):
        cell, kind = FACING_BEHIND[k]
        src = {"dx": "mt_dx", "dy": "mt_dy", "sum": "mt_s", "dydx": "mt_s", "dxdy": "mt_s"}[cell]
        out.append("  %sf%d:" % (L, k))
        if cell == "sum":
            out += ["    hex.mov 4, mt_s, mt_dx", "    hex.add 4, mt_s, mt_dy"]
        elif cell == "dydx":
            out += ["    hex.mov 4, mt_s, mt_dy", "    hex.sub 4, mt_s, mt_dx"]
        elif cell == "dxdy":
            out += ["    hex.mov 4, mt_s, mt_dx", "    hex.sub 4, mt_s, mt_dy"]
        out += _sign_branch(src, kind, "%sbh%d" % (L, k), "%swake" % L)
        out += ["  %sbh%d:" % (L, k), "    hex.cmp 4, mt_d, mt_c64, %swake, %swake, %s" % (L, L, nxt)]
    out += ["  %swake:" % L,
            "    hex.set 1, %s, 1" % TG,
            "    hex.set %d, %s, %d" % (ns, ST, see_idx),        # D-WAKE: the see state, no action run now
            "    hex.set %d, %s, %d" % (nt, TI, see_tics),
            "    ;%s" % nxt,
            # ---- M7 P4.2a: A_Fall -- the corpse stops blocking (World._run_action) ------------------------------
            *(["  %sfall:" % L, "    hex.zero 1, mon_solid + %d*dw" % m, "    ;%s" % nxt] if dmg else []),
            # ---- A_Chase in the wake mode: the counters and the turn; the target is never lost before P5 -------
            "  %schase:" % L,
            "    hex.if0 1, %s, %sr0" % (RE, L),
            "    hex.dec 1, %s" % RE,
            "  %sr0:" % L,
            "    hex.if0 %d, %s, %st0" % (nthr, TH, L),
            *(["    hex.if1 1, p_dead, %sthz" % L] if hurt else []),       # M7 P5: a dead target resets it
            "    hex.dec %d, %s" % (nthr, TH),
            *(["    ;%st0" % L, "  %sthz:" % L, "    hex.zero %d, %s" % (nthr, TH)] if hurt else []),
            "  %st0:" % L,
            "    hex.if_flags %s, %d, %sturn, %s" % (MD, 1 << 8, L, ("%sal" % L) if hurt else ("%smv" % L) if mv
                                                      else nxt),
            "  %sturn:" % L,
            "    hex.mov 1, mt_ti, %s" % FA,
            "    hex.mov 1, mt_ti + 1*dw, %s" % MD,
            "    mturn.lookup %s, mt_ti" % FA]
    if hurt:                                    # M7 P5: the target lost -> the spawn state (World._a_chase)
        out += ["  %sal:" % L,
                "    hex.if0 1, p_dead, %s" % (("%smv" % L) if mv else nxt),
                "    hex.set %d, %s, %d" % (ns, ST, hurt["sp"]),
                "    hex.set %d, %s, %d" % (nt, TI, hurt["spt"]),
                "    ;%s" % nxt]
    if mv:
        out += ["  %smv:" % L] + p32b_move_lines(m, schema=schema, **mv, dc=dict(dc, t=t, jh=dmg) if dc else None,
                                                 solid="mon_solid" if dmg else "mon_active")
    if dc:
        out += p32c_slot_lines(m, t=t, rt=mv["rt"], dc=dc, schema=schema, nxt=nxt, hear=hear, src=bool(hurt))
    out += ["  %s:" % nxt]
    return out


# ---- M7 P3.2b "chase" ------------------------------------------------------------------------------------------
P32B_FIELDS = ("mon_movecount", "mon_rng", "mon_floorz")


def p32b_move_lines(m: int, *, rt: int, radius: int, speed: int, schema, dc=None, solid: str = "mon_active") -> list:
    """slot m's move: its cells into the context, `mm_chase` (its own `solid` flag cleared, so the thing test skips
    it), the context back -- position into thpos_rt, the leaf into thss_rt, the sector into msec. `dc` (M7 P3.2c):
    `mm_decide` instead, with the decision's inputs (justattacked, seen, the kinds, reaction) and justattacked back;
    the slot then enters a decided state (p32c_slot_lines); `dc["jh"]` (M7 P4.2a): justhit in and back too.
    `solid`: the per-slot flag `monstermove.things_leaf_lines` tests -- the same name on both sides (mon_active
    until monsters die; M7 P4.2a: mon_solid, SET again after the move: a monster that moves is alive and solid,
    damagecode.check_model_rules)"""
    nz, nr, nc = (cell_nibbles(schema, f) for f in ("mon_floorz", "mon_rng", "mon_movecount"))
    assert (nz, nr, nc) == (4, 2, 2), (nz, nr, nc)
    assert radius in (20, 30) and speed in (8, 10), (radius, speed)
    X, Y = "thpos_rt + %d*dw" % (16 * rt + 4), "thpos_rt + %d*dw" % (16 * rt + 12)
    FZ, RN, MC = "mon_floorz + %d*dw" % (4 * m), "mon_rng + %d*dw" % (2 * m), "mon_movecount + %d*dw" % (2 * m)
    MD, AC, SS = "mon_movedir + %d*dw" % m, "%s + %d*dw" % (solid, m), "thss_rt + %d*dw" % (16 * rt)
    SC = "msec + %d*dw" % (2 * m)
    return ["    hex.mov 4, mm_x, %s" % X, "    hex.mov 4, mm_y, %s" % Y,
            "    hex.mov 4, mm_z, %s" % FZ, "    hex.sign_extend 8, 4, mm_z",
            "    hex.set 2, mm_r, %d" % radius, "    hex.set 1, mm_r30, %d" % int(radius == 30),
            "    hex.set 1, mm_spd, %d" % int(speed == 10),
            "    hex.mov 1, mm_dir, %s" % MD, "    hex.mov 2, mm_rng, %s" % RN, "    hex.mov 2, mm_mc, %s" % MC,
            "    hex.set w/4, mm_tw, %d" % rt,
            "    hex.zero w/4, mm_leafw", "    hex.mov 3, mm_leafw, %s" % SS,
            "    hex.mov 2, mm_sec, %s" % SC,
            "    hex.zero 1, %s" % AC,
            *(["    hex.mov 1, mm_ja, mon_justattacked + %d*dw" % m, "    hex.mov 1, mm_seen, thseen + %d*dw" % dc["t"],
               "    hex.set 1, mm_mk, %d" % dc["mk"], "    hex.mov 1, mm_re, mon_reaction + %d*dw" % m,
               *(["    hex.mov 1, mm_jh, mon_justhit + %d*dw" % m] if dc.get("jh") else []),
               "    stl.fcall mm_decide, mm_dret", "    hex.mov 1, mon_justattacked + %d*dw, mm_ja" % m,
               *(["    hex.mov 1, mon_justhit + %d*dw, mm_jh" % m] if dc.get("jh") else [])]
              if dc else ["    stl.fcall mm_chase, mm_cret"]),
            "    hex.set 1, %s, 1" % AC,
            "    hex.mov 4, %s, mm_x" % X, "    hex.mov 4, %s, mm_y" % Y,
            "    hex.mov 4, %s, mm_z" % FZ,
            "    hex.mov 1, %s, mm_dir" % MD, "    hex.mov 2, %s, mm_rng" % RN, "    hex.mov 2, %s, mm_mc" % MC,
            "    hex.mov 3, %s, mm_leafw" % SS,
            "    hex.mov 2, %s, mm_sec" % SC]


# ---- M7 P3.2c "decide" -----------------------------------------------------------------------------------------
def _action_targets(L: str, nxt: str, dc, fall: bool = False) -> list:
    """the slot's action dispatch: A_Look, A_Chase, and in the decide mode the attack states' actions its type runs;
    `fall` (M7 P4.2a): A_Fall"""
    tg = [nxt] * 16
    tg[MON_ACTIONS.index("A_Look")] = "%slook" % L
    tg[MON_ACTIONS.index("A_Chase")] = "%schase" % L
    if fall:
        tg[MON_ACTIONS.index("A_Fall")] = "%sfall" % L
    for a in sorted(dc["acts"]) if dc else ():
        tg[MON_ACTIONS.index(a)] = "%sk_%s" % (L, a)
    return tg


def p32c_slot_lines(m: int, *, t: int, rt: int, dc: dict, schema, nxt: str, hear: bool = False,
                    src: bool = False) -> list:
    """after mm_decide: a decision enters its state (A_FaceTarget's facing from the leaf); and the attack states'
    actions -- each sets its kind and runs md_attack on the slot's position, seen flag and stream. `hear` (M7 P4.2b):
    each A_FaceTarget -- the decided state's, and every attack action's, behind its target test -- clears
    `mon_ambush`"""
    from doomfj.monsterdecide import ATTACK_KINDS
    ns, nt, nf = cell_nibbles(schema, "mon_state"), cell_nibbles(schema, "mon_tics"), cell_nibbles(schema, "mon_facing")
    ST, TI, FA = "mon_state + %d*dw" % (ns * m), "mon_tics + %d*dw" % (nt * m), "mon_facing + %d*dw" % (nf * m)
    TG, RN = "mon_target + %d*dw" % m, "mon_rng + %d*dw" % (2 * m)
    L = "mw%d_" % m
    out = ["    hex.if0 1, mm_dec, %s" % nxt, "    hex.mov 1, %s, mm_fa" % FA]
    amb = ["    hex.zero 1, mon_ambush + %d*dw" % m] if hear else []       # M7 P4.2b: A_FaceTarget's MF_AMBUSH
    out += amb
    if dc["mel"] and dc["mis"]:
        out.append("    hex.if_flags mm_dec, 2, %sdmis, %sdmel" % (L, L))
    for lab, st in (("dmel", dc["mel"]), ("dmis", dc["mis"])):
        if st:
            out += ["  %s%s:" % (L, lab), "    hex.set %d, %s, %d" % (ns, ST, st[0]),
                    "    hex.set %d, %s, %d" % (nt, TI, st[1]), "    ;%s" % nxt]
    for a in sorted(dc["acts"]):
        out += ["  %sk_%s:" % (L, a), "    hex.set 1, mm_kind, %d" % ATTACK_KINDS[a], "    ;%sk_go" % L]
    if dc["acts"]:
        out += ["  %sk_go:" % L,
                "    hex.if0 1, %s, %s" % (TG, nxt),
                *amb,
                "    hex.mov 4, mm_x, thpos_rt + %d*dw" % (16 * rt + 4),
                "    hex.mov 4, mm_y, thpos_rt + %d*dw" % (16 * rt + 12),
                "    hex.mov 1, mm_seen, thseen + %d*dw" % t, "    hex.mov 2, mm_rng, %s" % RN,
                # M7 P7 (`src`: the attacks land, hurtcode): the attacker's id for dp_go and a fireball's pj_src
                *(["    hex.set 2, md_src, %d" % (m + 1)] if src else []),
                "    stl.fcall md_attack, md_ret",
                "    hex.mov 1, %s, mm_fa" % FA, "    hex.mov 2, %s, mm_rng" % RN,
                "    ;%s" % nxt]
    return out


def p32c_decls(schema, nmon: int, values: dict) -> list:
    from doomfj.monsterdecide import P32C_FIELDS
    out = []
    for name in P32C_FIELDS:
        nib = cell_nibbles(schema, name)
        out.append("%s: hex.vec %d, %d" % (name, nib * nmon, sum(v << (4 * nib * m) for m, v in
                                                                 enumerate(values[name]))))
    return out


def p32b_decls(schema, nmon: int, values: dict, msec: list) -> list:
    """the chase's per-slot cells (movecount, P_Random state, floorz; `msec`, each monster's sector), the move's
    context, and the REJECT leaf's operand"""
    from doomfj.monstermove import P32B_CONTEXT
    out = []
    for name in P32B_FIELDS:
        nib = cell_nibbles(schema, name)
        vals = [v & (16 ** nib - 1) for v in values[name]]
        out.append("%s: hex.vec %d, %d" % (name, nib * nmon, sum(v << (4 * nib * m) for m, v in enumerate(vals))))
    assert all(0 <= s_ < 256 for s_ in msec), msec
    out.append("msec: hex.vec %d, %d" % (2 * nmon, sum(v << (8 * m) for m, v in enumerate(msec))))
    return out + P32B_CONTEXT + ["mt_ms: hex.vec 2", "mt_rjret: hex.vec w/4"]


def p32b_change_sector_lines(w, nmon: int, *, exit_guard: bool) -> list:
    """P_ChangeSector for the lifts (world._door_phase_scene): when a mover's state differs from the last frame's
    (`mh_prev` holds each lift's state and the switch) every ACTIVE monster standing in a mover's sector takes that
    sector's floor at the mover's state. The model's trigger is the movers' heights off their stored floors; a
    lift's stops are distinct heights (asserted), so a state change is a height change and the two agree.

    `exit_guard`: a finished level (`lvdone`) skips it, `mh_prev` included -- the gates' mirrors skip the whole
    monster frame then (p2a_gate: `if not lvdone: mph.frame`, whose `sync` IS this), the exit-press frame too,
    where the lifts have already ticked; `mt_tic`'s own guard (p32a_tic_lines) covers only the tic after it.
    (tests/fj/test_change_sector_fj.py)"""
    from doomfj.movers import mover_heights
    lifts = list(w.lift_order)
    for si in lifts:
        assert len(set(w.lift_stops[si])) == len(w.lift_stops[si]), (si, w.lift_stops[si])
    nl = len(lifts)
    movers = {si: ("lstate + %d*dw" % k, [mover_heights(w.secs, w.lift_stops, {si: st}, {}, False).get(
        si, (w.secs[si].floor_h, 0))[0] for st in range(len(w.lift_stops[si]))]) for k, si in enumerate(lifts)}
    for si in w.switch:
        low_hi = mover_heights(w.secs, w.lift_stops, {}, w.switch, True)
        movers[si] = ("fswitch", [w.secs[si].floor_h, low_hi.get(si, (w.secs[si].floor_h, 0))[0]])
    out = ["  // M7 P3.2b: P_ChangeSector -- the movers moved since the last frame: their monsters take the new floor"]
    if exit_guard:
        out.append("    hex.if1 1, lvdone, mcs_skip")                   # a finished level: the world is frozen
    out += ["    hex.cmp %d, mh_prev, lstate, mcs_chg, mcs_sw, mcs_chg" % nl if nl else "    ;mcs_sw",
           "  mcs_sw:",
           "    hex.cmp 1, mh_prev + %d*dw, fswitch, mcs_chg, mcs_skip, mcs_chg" % nl,
           "  mcs_chg:"]
    out += (["    hex.mov %d, mh_prev, lstate" % nl] if nl else []) + ["    hex.mov 1, mh_prev + %d*dw, fswitch" % nl]
    for m in range(nmon):
        out += ["    hex.if0 1, mon_active + %d*dw, mcs_m%d" % (m, m),
                "    hex.mov 2, mt_ms, msec + %d*dw" % (2 * m),
                "    stl.fcall mcf_leaf, mcf_ret",
                "    hex.if0 1, mcf_hit, mcs_m%d" % m,
                "    hex.mov 4, mon_floorz + %d*dw, mcf_val" % (4 * m),
                "  mcs_m%d:" % m]
    out += ["    ;mcs_skip"]
    # mcf_leaf: the sector in mt_ms -> (mcf_hit, mcf_val = its floor at its mover's state)
    hs = sorted({si >> 4 for si in movers})
    out += ["  mcf_leaf:", "    hex.zero 1, mcf_hit",
            "    sim.jump16 mt_ms + 1*dw, " + ", ".join("mcf_h%d" % h if h in hs else "mcf_out" for h in range(16))]
    for h in hs:
        out += ["  mcf_h%d:" % h, "    sim.jump16 mt_ms, " + ", ".join(
            "mcf_s%d" % (16 * h + l) if 16 * h + l in movers else "mcf_out" for l in range(16))]
    for si, (cell, floors) in sorted(movers.items()):
        labs = ["mcf_s%d_%d" % (si, k) for k in range(len(floors))]
        out += ["  mcf_s%d:" % si, "    sim.jump16 %s, %s" % (cell, ", ".join(labs + [labs[-1]] * (16 - len(labs))))]
        for k, fl in enumerate(floors):
            out += ["  %s:" % labs[k], "    hex.set 4, mcf_val, %d" % (fl & 0xFFFF), "    ;mcf_one"]
    out += ["  mcf_one:", "    hex.set 1, mcf_hit, 1", "  mcf_out:", "    stl.fret mcf_ret", "  mcs_skip:"]
    return out


def p32b_rj_leaf(sectors) -> list:
    """`mt_rj_leaf`: mt_rj = REJECT-visible(mt_ms -> psec) -- a two-nibble jump on the monster's sector to that
    sector's row (`rj<sector>`, indexed by the player's sector); `sectors`: every one a monster can stand in"""
    secs = sorted(set(sectors))
    have = set(secs)
    out = ["mt_rj_leaf:", "    sim.jump16 mt_ms + 1*dw, " + ", ".join(
        "mt_rjh%d" % h if any(16 * h <= s_ < 16 * h + 16 for s_ in secs) else "mt_rj_none" for h in range(16))]
    for h in range(16):
        if any(16 * h <= s_ < 16 * h + 16 for s_ in secs):
            out += ["  mt_rjh%d:" % h, "    sim.jump16 mt_ms, " + ", ".join(
                "mt_rjs%d" % (16 * h + l) if 16 * h + l in have else "mt_rj_none" for l in range(16))]
    for s_ in secs:
        out += ["  mt_rjs%d:" % s_, "    rj%d.lookup mt_rj, psec" % s_, "    stl.fret mt_rjret"]
    out += ["  mt_rj_none:", "    hex.zero 1, mt_rj", "    stl.fret mt_rjret"]
    return out


K_SLOTS = K_HEAVY                    # world.K_HEAVY: heavy monster actions per tic (D5)

# M7 P3.3: the monster modes that emit sim.thing_pass_depth -- the walk's registers come with the chase block
DEPTH_MODES = ("chase", "decide", "full", "push", "final")   # M7 P8a: + the modes after "full"


def depth_walk(mode: str, order=None) -> bool:
    """M7 P3.3 (D3 d): does the game tier walk a leaf's runtime things NEAREST FIRST (`sim.thing_pass_depth`)?
    `order` is the oracle's `rt_depth_order` the binary must match; None reads GAME_RENDER_KW's, the ONE game-tier
    setting. Only DEPTH_MODES emit the walk, so a mode that cannot while the setting asks for it RAISES: emitting
    `sim.thing_pass` instead draws index order against an oracle that sorts, and only a byte gate would notice."""
    if order is None:
        from doomfj.reference_model import GAME_RENDER_KW     # lazy: reference_model is the oracle, not a dep
        order = GAME_RENDER_KW.get("rt_depth_order")
    if not order:
        return False
    assert order == "aprox", "the fj walk keys by P_AproxDistance only, not rt_depth_order=%r" % (order,)
    assert mode in DEPTH_MODES, (
        "monster mode %r cannot emit the depth walk (only %s do), yet the game tier's render setting asks for "
        "rt_depth_order=%r -- the binary would walk index order against a sorted oracle. Build a %s game tier, or "
        "drop rt_depth_order from GAME_RENDER_KW for this mode." % (mode, "/".join(DEPTH_MODES), order,
                                                                   "/".join(DEPTH_MODES)))
    return True


# M7 P3.3: sim.thing_pass_depth's registers (named globals: no @-local data in a game-tier macro)
P33_DECLS = (["td_%s: hex.vec w/4" % r for r in ("head", "e", "t", "p", "q", "best", "lt", "poff", "pbase", "pptr")]
             + ["td_pos: hex.vec 16", "td_bk: hex.vec 4", "td_lk: hex.vec 4", "td_have: hex.vec 1",
                "td_first: hex.vec 1"])
# M7 P8a package C (docs/gp-final-plan.md 1.3): the compositor rules' cells -- `td_rk` (D3 a: sim.thing_pass_depth's
# first rank-0 row, SET at every multi-thing leaf before its rounds read it) and `sp_ex` (D3 b: the barrel flag, 1 from a
# barrel's xor_by block or row select to its record, 0 everywhere else -- so 0 at every frame's end). Scratch, never
# persisted
D3_DECLS = ("td_rk: hex.vec 2", "sp_ex: hex.vec 1")


def rank_threshold(nt: int) -> int:
    """M7 P8a (C, D3 a): the first runtime row of RANK 0 -- the rows run [0, nt) the map's runtime things, then the
    fireball pool (nt + s, s < FIREBALL_POOL), the fx pool (blood and puffs), the drops (`mobile_select_lines`,
    `drop_select_lines`): rows >= nt + FIREBALL_POOL are the effects and the drops, drawn first in their leaf; the
    oracle's `reference_model.mobile_rank` names the same pools by their lumps"""
    from doomfj.world import FIREBALL_POOL
    return nt + FIREBALL_POOL


def p32a_leaves() -> list:
    """the wake tic's two shared leaves: mt_d = P_AproxDistance(mt_dx, mt_dy) (world.aprox_distance), and psec = the
    player's sector (world.player_sector: the point location of the INTEGER map position), once a frame"""
    return dist_leaf_lines() + [
            "mt_psec_leaf:",
            "    hex.if1 1, mt_psok, mt_psec_done",
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, viewx + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, viewy + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    lfsec.lookup psec, ptss",
            "    hex.set 1, mt_psok, 1",
            "  mt_psec_done:",
            "    stl.fret mt_ret"]


def dist_leaf_lines() -> list:
    """`mt_dist_leaf` (stl.fcall mt_dist_leaf, mt_ret): mt_d = P_AproxDistance(mt_dx, mt_dy) (world.aprox_distance),
    |dx| and |dy| left in mt_ax, mt_ay -- p32a_leaves' first leaf, alone for a caller without the point location
    (M7 P4.2a: damagecode's reach test)"""
    out = ["mt_dist_leaf:"]
    for c, a in (("mt_dx", "mt_ax"), ("mt_dy", "mt_ay")):
        out += ["    hex.mov 4, %s, %s" % (a, c),
                "    hex.if_flags %s + 3*dw, 0xFF00, %s_ok, %s_neg" % (a, a, a),
                "  %s_neg:" % a, "    hex.neg 4, %s" % a,
                "  %s_ok:" % a]
    for lab, small in (("mt_xlt", "mt_ax"), ("mt_xge", "mt_ay")):
        pass
    out += ["    hex.cmp 4, mt_ax, mt_ay, mt_xlt, mt_xge, mt_xge",
            "  mt_xlt:", "    hex.mov 4, mt_d, mt_ax", ";mt_half",
            "  mt_xge:", "    hex.mov 4, mt_d, mt_ay",
            "  mt_half:",
            "    hex.shr_bit 4, mt_d",                              # min(|dx|, |dy|) >> 1
            "    hex.mov 4, mt_t, mt_ax",
            "    hex.add 4, mt_t, mt_ay",
            "    hex.sub 4, mt_t, mt_d",
            "    hex.mov 4, mt_d, mt_t",
            "    stl.fret mt_ret"]
    return out


def _knock_slot_lines(m: int) -> list:
    from doomfj.knockcode import monster_slot_lines   # lazy: K's module reads this one's helpers
    return monster_slot_lines(m)


def p32a_tic_lines(schema, nmon: int, slots: list, exit_guard: bool) -> list:
    """the whole wake tic: from `sched_cursor`, every slot once in order (world._monsters_phase), then the cursor to
    the first deferred slot. `slots[m]` = p32a_slot's keyword arguments for slot m."""
    nh = (nmon + 15) // 16
    out = ["mt_tic:"]
    if exit_guard:
        out.append("    hex.if1 1, lvdone, mt_skip")                    # a finished level: the world is frozen
    out += ["    hex.zero 1, mt_used", "    hex.zero 2, mt_fdef", "    hex.set 2, mt_n, %d" % nmon,
            "    hex.zero 1, mt_psok",
            "    sim.jump16 sched_cursor + 1*dw, " + ", ".join(
                ["mt_h%d" % h if h < nh else "mt_end" for h in range(16)])]
    for h in range(nh):
        out += ["  mt_h%d:" % h, "    sim.jump16 sched_cursor, " + ", ".join(
            ["mw%d" % (16 * h + l) if 16 * h + l < nmon else "mt_end" for l in range(16)])]
    for m in range(nmon):
        out += p32a_slot(m, schema=schema, **slots[m])
    out += ["    ;mw0",                                                # the chain wraps; mt_n ends it
            "  mt_end:",
            "    hex.if0 2, mt_fdef, mt_skip",
            "    hex.mov 2, sched_cursor, mt_fdef",
            "    hex.dec 2, sched_cursor",
            "  mt_skip:"]
    return out


# mt_c128 / mt_c64 hold NEAR_UNITS / BEHIND_REACH: the LABELS keep their names (fj globals, the frozen ABI), the
# VALUES come from the one source each (R6); `hex.cmp 4` compares them as 4-nibble words
assert 0 < NEAR_UNITS < 16 ** 4 and 0 < BEHIND_REACH < 16 ** 4
P32A_SCRATCH = ["mt_c128: hex.vec 4, %d" % NEAR_UNITS, "mt_c64: hex.vec 4, %d" % BEHIND_REACH,
                "mt_s: hex.vec 4", "mt_n: hex.vec 2", "mt_psok: hex.vec 1", "mt_ret: hex.vec w/4"]
