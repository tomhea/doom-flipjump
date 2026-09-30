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
from typing import Dict, List, Tuple

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.lut_generator import generate_dispatch_table_fj

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
              skills, cache: dict) -> dict:
    """everything P3.1 adds to the game tier, from the model's own sources:
      * `view_rows`: one thing row per distinct monster VIEW (lump, mirrored) -- `things.thing_rows`' layout from the
        view's art, dw's bit 7 set for a mirrored view -- appended after the runtime things' own rows;
      * `mview`: the D4 table (view group << 4 | rotation index) -> that view's row;
      * `select`: the row-select leaf `thsel_leaf` (sp_ti = thing index in, its row out): a two-level `sim.jump16`
        on the index into one stub per runtime thing -- a static thing keeps its own row, a monster's stub runs the
        rotation leaf on its slot's facing and looks up its state's view group (rule 1: the index selects CODE);
      * `rotation`: the rotation leaf; `tic`: the per-slot tic; `decls`: the cells (the boot skill's level start)
        and the scratch; `restart`: per skill, the lines NEW GAME writes the cells with."""
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
    nrows = nt + len(rows)
    rn = max(1, ((nrows - 1).bit_length() + 3) // 4)
    # the monster slots, and which runtime thing each is
    w = World(map_wad, mapname, boot_skill, rm=rm)
    nmon, schema = w.layout.nmon, w.schema
    if nmon == 0 or not rows:
        return None                      # a map without monsters animates nothing
    slot_of = {_thing_key(t): m for m, t in enumerate(w.mon_things)}
    rt_slot = [slot_of.get(_thing_key(t)) for t in rt_things]
    assert sorted(m for m in rt_slot if m is not None) == list(range(nmon)), "every monster slot is a runtime thing"

    def values(sk):
        w.reset(sk)
        return {f: list(getattr(w.ws, f)[:nmon]) for f in P31_FIELDS}

    boot = values(boot_skill)
    restart = []
    for sk in skills:
        v = values(sk)
        restart.append(["    hex.set %d, %s + %d*dw, %d" % (cell_nibbles(schema, f), f, cell_nibbles(schema, f) * m,
                                                            v[f][m]) for f in P31_FIELDS for m in range(nmon)])
    # the row select
    sel = ["thsel_leaf:", "    sim.jump16 sp_ti + 1*dw, " + ", ".join(
        "thsel_h%d" % h if 16 * h < nt else "thsel_none" for h in range(16))]
    for h in range((nt + 15) // 16):
        sel += ["  thsel_h%d:" % h, "    sim.jump16 sp_ti, " + ", ".join(
            "thsel_s%d" % (16 * h + l) if 16 * h + l < nt else "thsel_none" for l in range(16))]
    for t, m in enumerate(rt_slot):
        sel.append("  thsel_s%d:" % t)
        if m is not None:
            sel += ["    hex.mov 8, mr_tx, sp_x", "    hex.mov 8, mr_ty, sp_y",
                    "    hex.mov 1, mr_face, mon_facing + %d*dw" % m,
                    "    stl.fcall mon_rot_leaf, mr_ret",
                    "    mstate.lookup ts_row, mon_state + %d*dw" % (2 * m),
                    "    hex.mov 1, ts_idx, mr_rot",
                    "    hex.mov 2, ts_idx + 1*dw, ts_row + 4*dw",
                    "    hex.zero w/4, sp_ti",
                    "    mview.lookup sp_ti, ts_idx"]
        sel.append("    stl.fret thsel_ret")
    sel += ["  thsel_none:", "    stl.fret thsel_ret"]
    return {
        "view_rows": rows, "nrows": nrows, "views": views, "rt_slot": rt_slot, "nmon": nmon, "schema": schema,
        "mview": generate_dispatch_table_fj("mview", mview, index_nibbles=3, result_nibbles=rn),
        "mrot": rot_table_fj(), "select": sel, "rotation": rotation_leaf_lines(1),
        "tic": mon_tic_lines(schema, nmon),
        "decls": (monster_decls(schema, nmon, boot) + MT_DECLS + ROT_DECLS
                  + ["ts_row: hex.vec 6", "ts_idx: hex.vec 3", "thsel_ret: hex.vec w/4",
                     "trb_mir: hex.vec 1", "trb_mu: hex.vec 2"]),
        "restart": restart, "view_heights": sorted({max(1, r[2]) for r in rows}),
    }
