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
        out.append("%s:" % name)
        out += ["  hex.vec %d, %d" % (nib, v) for v in vals]
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
