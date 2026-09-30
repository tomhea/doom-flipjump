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


# ---- P3.2a: the WAKE tic (docs/gp-monsters.md 8.3) -------------------------------------------------------------
P32A_FIELDS = ("mon_target", "mon_reaction", "mon_threshold", "mon_movedir")
HEAVY_IDS = (MON_ACTIONS.index("A_Chase"), MON_ACTIONS.index("A_FaceTarget"),
             MON_ACTIONS.index("A_PosAttack"), MON_ACTIONS.index("A_SPosAttack"),
             MON_ACTIONS.index("A_TroopAttack"), MON_ACTIONS.index("A_SargAttack"))
NEAR_UNITS = 128                     # doomfj.sight.NEAR: REJECT wakes within this
BEHIND_REACH = 64                    # world.LOOK_BEHIND_REACH: P_LookForPlayers sees behind within this


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


def p32a_decls(schema, nmon: int, values: dict, nthings: int) -> list:
    """the wake tic's cells (target, reaction, threshold, movedir per slot; the cursor), its scratch, and the
    per-runtime-thing seen flags `thseen` the render writes"""
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


def p32a_slot(m: int, *, t: int, x: int, y: int, rj: str, see_idx: int, see_tics: int, schema) -> list:
    """one slot of the wake tic -- the model's `_monsters_phase` step for slot m, A_Look and the wake mode's
    A_Chase (docs/gp-monsters.md 8.3). x, y: its spawn point (a monster never moves in this mode); rj: the D4
    REJECT row of its spawn sector (indexed by the player's sector); t: its runtime thing (the render's seen flag)."""
    ns, nt, nf = cell_nibbles(schema, "mon_state"), cell_nibbles(schema, "mon_tics"), cell_nibbles(schema, "mon_facing")
    nthr = cell_nibbles(schema, "mon_threshold")
    ST, TI, AC = "mon_state + %d*dw" % (ns * m), "mon_tics + %d*dw" % (nt * m), "mon_active + %d*dw" % m
    FA, TG = "mon_facing + %d*dw" % (nf * m), "mon_target + %d*dw" % m
    RE, TH, MD = "mon_reaction + %d*dw" % m, "mon_threshold + %d*dw" % (nthr * m), "mon_movedir + %d*dw" % m
    L = "mw%d_" % m
    nxt = "mw%d_next" % m
    out = ["  mw%d:" % m,
           "    hex.if0 2, mt_n, mt_end",
           "    hex.dec 2, mt_n",
           "    hex.if0 1, %s, %s" % (AC, nxt),
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
           "    sim.jump16 mt_row + 3*dw, %s, %slook, %schase, %s" % (nxt, L, L, ", ".join([nxt] * 13)),
           # ---- A_Look: threshold 0; no sound before P4; P_LookForPlayers (not all around) -----------------
           "  %slook:" % L,
           "    hex.zero %d, %s" % (nthr, TH),
           "    hex.mov 4, mt_dx, viewx + 4*dw",
           "    hex.sub_constant 4, mt_dx, %d" % (x & 0xFFFF),
           "    hex.mov 4, mt_dy, viewy + 4*dw",
           "    hex.sub_constant 4, mt_dy, %d" % (y & 0xFFFF),
           "    stl.fcall mt_dist_leaf, mt_ret",                  # mt_d = P_AproxDistance(dx, dy)
           "    hex.if1 1, thseen + %d*dw, %sbehind" % (t, L),     # seen by last frame's picture
           "    hex.cmp 4, mt_d, mt_c128, %snear, %snear, %s" % (L, L, nxt),
           "  %snear:" % L,
           "    stl.fcall mt_psec_leaf, mt_ret",                  # psec, once a frame
           "    %s.lookup mt_rj, psec" % rj,
           "    hex.if0 1, mt_rj, %s" % nxt,
           "  %sbehind:" % L,                                  # behind and beyond 64: not seen
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
            # ---- A_Chase in the wake mode: the counters and the turn; the target is never lost before P5 -------
            "  %schase:" % L,
            "    hex.if0 1, %s, %sr0" % (RE, L),
            "    hex.dec 1, %s" % RE,
            "  %sr0:" % L,
            "    hex.if0 %d, %s, %st0" % (nthr, TH, L),
            "    hex.dec %d, %s" % (nthr, TH),
            "  %st0:" % L,
            "    hex.if_flags %s, %d, %sturn, %s" % (MD, 1 << 8, L, nxt),
            "  %sturn:" % L,
            "    hex.mov 1, mt_ti, %s" % FA,
            "    hex.mov 1, mt_ti + 1*dw, %s" % MD,
            "    mturn.lookup %s, mt_ti" % FA,
            "  %s:" % nxt]
    return out


K_SLOTS = 6                          # world.K_HEAVY: heavy monster actions per tic (D5)


def p32a_leaves() -> list:
    """the wake tic's two shared leaves: mt_d = P_AproxDistance(mt_dx, mt_dy) (world.aprox_distance), and psec = the
    player's sector (world.player_sector: the point location of the INTEGER map position), once a frame"""
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
            "    stl.fret mt_ret",
            "mt_psec_leaf:",
            "    hex.if1 1, mt_psok, mt_psec_done",
            "    hex.zero 10, ptx", "    hex.mov 4, ptx, viewx + 4*dw", "    hex.sign_extend 10, 4, ptx",
            "    hex.zero 10, pty", "    hex.mov 4, pty, viewy + 4*dw", "    hex.sign_extend 10, 4, pty",
            "    stl.fcall ptloc_walk, ptloc_ret",
            "    lfsec.lookup psec, ptss",
            "    hex.set 1, mt_psok, 1",
            "  mt_psec_done:",
            "    stl.fret mt_ret"]
    return out


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


P32A_SCRATCH = ["mt_c128: hex.vec 4, 128", "mt_c64: hex.vec 4, 64", "mt_s: hex.vec 4", "mt_n: hex.vec 2",
                "mt_psok: hex.vec 1", "mt_ret: hex.vec w/4"]
