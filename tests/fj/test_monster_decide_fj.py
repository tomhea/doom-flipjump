"""M7 P3.2c (docs/gp-monsters.md 8.5): the DECIDE tic on the real flipjump engine against the model's decide mode
(World(monsters="decide", sight_rule="seen")) -- every slot's state, tics, facing, target, reaction, threshold,
movedir, movecount, P_Random state, justattacked, position, floorz and leaf, and the cursor, after every frame.
M7 P4.2a: justhit and solid too -- the slots run with `dmg` (damagecode): the decision reads and clears `mon_justhit`
(poked on the parked-by monster on random frames, both sides), and one monster DIES at the start (its death state,
shootable 0, health 0) so its tic runs A_Fall, which clears `mon_solid`, the flag the thing test reads.

The whole tic runs: the slots (monstercode.p32a_slot with `dc`), the chase's leaves, the decision (`mm_decide`), the
attack actions (`md_attack`), the attack sight with the near LOS (`mm_as`, `sl_los`). The world is woken at the
start (a subset: see _world); the script parks the player by a demon, an imp, a zombieman and a shotgun guy in turn -- in melee reach,
within NEAR, and beyond -- with random seen flags, so the near LOS runs both ways, and the model moves with it.

R9: a missile decision without its roll, an attack sight that never traces, a justattacked that is never read,
attacks that draw nothing, a justhit that is never cleared, and an A_Fall that clears nothing must each part from the
model.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import monstermove as MM
from doomfj import monstersight as MS
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, generate_point_location_fj, monster_cells_fj,
                              point_location_decls)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
from doomfj.world import DROPOFF_MAX, NEWCHASEDIR_MAX_TRIES, CHASE_DEADZONE, STEP_UP, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = 120
M32 = 0xFFFFFFFF
TARGETS = {3002: "demon", 3001: "imp", 3004: "zombieman", 9: "shotgun guy"}


def _world():
    """the four targets and every fourth other monster awake (the rest asleep: six heavy slots a tic serve the
    awake ones), the targets' reaction time spent so they may decide a missile at once"""
    w = World(monsters="decide", sight_rule="seen")
    tg = _targets(w)
    for m in range(w.layout.nmon):
        if w.ws.mon_active[m] and (m in tg or m % 4 == 0):
            w.ws.mon_target[m] = 1
            w._set_state(m, w.mon_info[m].seestate, False, TicEvents(0))
    for m in tg:
        w.ws.mon_reaction[m] = 0
    d = _dying(w)                        # M7 P4.2a: a monster killed at the start -- its tic reaches A_Fall
    w.ws.mon_shootable[d], w.ws.mon_health[d] = 0, 0
    w._set_state(d, w.mon_info[d].deathstate, True, TicEvents(0))
    return w


def _dying(w):
    """the first asleep active monster that is none of the targets"""
    tg = _targets(w)
    return next(m for m in range(w.layout.nmon) if w.ws.mon_active[m] and m not in tg and m % 4)


def _targets(w):
    """one active monster of each kind, in TARGETS' order"""
    out = []
    for ty in TARGETS:
        out.append(next(m for m in range(w.layout.nmon) if w.mon_things[m].type == ty and w.ws.mon_active[m]))
    return out


def _signed32(v):
    return v - (1 << 32) if v >> 31 else v


def _set(w, x16, y16, ang, seen, jh):
    ws = w.ws
    ws.px, ws.py, ws.pangle = _signed32(x16), _signed32(y16), ang
    for m in range(w.layout.nmon):
        ws.mon_seen[m] = int(m in seen)
    for m in jh:                         # M7 P4.2a: a hit's MF_JUSTHIT, as damage leaves it
        ws.mon_justhit[m] = 1


def _script():
    """per frame: (player x16, y16, angle, seen slots), placed by the model's CURRENT positions as it runs"""
    w = _world()
    rnd = random.Random(5)                   # a seed whose script runs all four attacks in 120 frames
    rjh = random.Random(0x42A)               # M7 P4.2a: the justhit pokes (their own stream: rnd's script stands)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    tg = _targets(w)
    out = []
    for f in range(FRAMES):
        m = tg[(f // 10) % len(tg)]
        r = rnd.choice((40, 40, 50, 90, 120, 300))
        a = rnd.randrange(8)
        dx, dy = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)][a]
        k = r if dx * dy == 0 else r * 7 // 10
        x16 = ((w.ws.mon_x[m] + dx * k) << 16 | rnd.randrange(1 << 16)) & M32
        y16 = ((w.ws.mon_y[m] + dy * k) << 16 | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        seen = set(rnd.sample(act, 6)) | ({m} if rnd.random() < 0.5 else set())
        seen.discard(m) if m in seen and rnd.random() < 0.3 else None
        out.append((x16, y16, rnd.randrange(1 << 32), seen, set(a for a in act if rjh.random() < 0.2)))
        _set(w, *out[-1])
        w._monsters_phase(TicEvents(0))
    return out


def _row(w):
    ws, n = w.ws, w.layout.nmon
    s = "".join("%02x%x%x%x%x%02x%x%02x%02x%x%x%x%04x%04x%04x%03x" % (
        ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m], ws.mon_target[m], ws.mon_reaction[m],
        ws.mon_threshold[m], ws.mon_movedir[m], ws.mon_movecount[m] & 0xFF, ws.mon_rng[m], ws.mon_justattacked[m],
        ws.mon_justhit[m], ws.mon_solid[m],
        ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m]) for m in range(n))
    return s + "%02x" % ws.sched_cursor


def _expected(script) -> bytes:
    w = _world()
    ws = w.ws
    lines = []
    for fr in script:
        _set(w, *fr)
        w._monsters_phase(TicEvents(0))
        lines.append(_row(w))
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
    return ("\n".join(lines) + "\n").encode()


def _parts(w, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    things, var = MM.static_blockers(w)
    cells, root = monster_cells_fj("e1m1", w.lds, w.cmap.vertexes, w.secs, w.sds, things=things, **kw)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    lift_trigs = [(w.lift_order.index(tr[0]),) + tuple(tr[1:]) for tr in w.lift_walk]
    door_boxes = [(d, w.mon_door_boxes[si]) for d, si in enumerate(w.door_order) if si in w.mon_door_boxes]
    slots = []
    for m in range(n):
        info = w.mon_info[m]
        slots.append(dict(t=m, x=ws.mon_x[m], y=ws.mon_y[m], rj="", see_idx=gd.STATE_INDEX[info.seestate],
                          see_tics=gd.STATES[info.seestate].tics,
                          mv=dict(rt=m, radius=w.mon_radius[m], speed=w.mon_speed[m]), dc=MD.type_decide(info),
                          dmg=True))
    secs = sorted({w.leaf_sector[s] for s in range(len(w.cmap.subsectors))})
    tables = MC.p30_tables_fj()
    tables += [generate_dispatch_table_fj("rj%d" % s, [int(w.reject.visible(s, q)) for q in range(w.reject.nsec)],
                                          index_nibbles=2, result_nibbles=1) for s in secs]
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3, result_nibbles=2))
    tables.append(generate_point_location_fj(w.cmap))
    fields = MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS + MD.P32C_FIELDS
    vals = {f: list(getattr(ws, f)[:n]) for f in fields}
    msec = [w._mon_sector(m) for m in range(n)]
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)], nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)])
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, msec)
             + MC.p32c_decls(schema, n, {f: vals[f] for f in MD.P32C_FIELDS})
             + DC.field_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in DC.P42_FIELDS}) + ["mm_jh: hex.vec 1"]
             + MD.context_decls() + MS.SL_DECLS
             + MC.MT_DECLS + MC.P32A_SCRATCH + point_location_decls() + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + LEAF_LINK_DECLS + MM.monster_seed_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4",
                "thpos_rt: hex.vec %d, %d" % (16 * n, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32) << 32)
                                                          << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * n, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * n),
                "dstate: hex.vec %d" % (2 * len(w.door_order)), "ddir: hex.vec %d" % (2 * len(w.door_order)),
                "dreq: hex.vec %d" % (2 * len(w.door_order)),
                "lstate: hex.vec %d" % (2 * len(w.lift_order)), "lreq: hex.vec %d" % (2 * len(w.lift_order)),
                "fswitch: hex.vec 1", "dbox: hex.vec 8",
                "bar_solid: hex.vec %d, %d" % (2 * len(w.barrel_things),
                                                sum(ws.bar_solid[b] << (4 * b) for b in range(len(w.barrel_things)))),
                "mc_don: hex.vec 2"])
    move = (MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], solid="mon_solid")
            + MM.move_leaf_lines(root=root, lift_trigs=lift_trigs, door_boxes=door_boxes, dropmax=DROPOFF_MAX,
                                 stepup=STEP_UP, height=56)
            + MM.ncd_leaf_lines(deadzone=CHASE_DEADZONE, max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.walk_leaf_lines(max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.chase_leaf_lines() + MD.decide_leaves(justhit=True) + MS.near_los_lines(w))
    code = (["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False) + ["    stl.fret mt_tret"]
            + MC.p32a_leaves() + MC.p32b_rj_leaf(secs) + move + seed)
    text = "\n".join(code + [cells] + tables) + "\n"
    muts = {"noroll": ("    hex.cmp 4, mo_t4, mo_c4, mm_dc_mv, mm_dc_yes, mm_dc_yes\n",
                       "    ;mm_dc_yes\n"),
            "nolos": ("    stl.fcall sl_los, sl_ret\n", "    hex.zero 1, sl_hit\n"),
            "nojust": ("    hex.if0 1, mm_ja, mm_dc_m\n", "    ;mm_dc_m\n"),
            "nodraws": ("    sim.jump16 mm_kind, ", "    sim.jump16 mm_zero, "),
            # M7 P4.2a: justhit never cleared; the dying monster's A_Fall clears nothing
            "nojhclear": ("    hex.zero 1, mm_jh\n", ""),
            "nofall": ("  mw%d_fall:\n    hex.zero 1, mon_solid + %d*dw\n" % (_dying(w), _dying(w)),
                       "  mw%d_fall:\n" % _dying(w))}
    if mut:
        old, new = muts[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
        if mut == "nodraws":
            decls = decls + ["mm_zero: hex.vec 1"]
    return decls, text


def _build(tmp_path, name, mut=None):
    """-> (fj sources, the expected output)"""
    w = _world()
    n = w.layout.nmon
    script = _script()
    body = ["stl.startup_and_init_all"]
    for x16, y16, ang, seen, jh in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen))]
        body += ["hex.set 1, mon_justhit + %d*dw, 1" % m for m in sorted(jh)]
        body += ["stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_target + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_movedir + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_movecount + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_justattacked + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_justhit + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_solid + %d*dw, 0" % m,
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0",
                 "hex.zero %d, dreq" % (2 * len(w.door_order)), "hex.zero %d, lreq" % (2 * len(w.lift_order)),
                 "stl.output 10"]
    body += ["stl.loop"]
    decls, text = _parts(w, mut)
    prog = "\n".join(body + decls + [text]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(script)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_script_exercises_every_path():
    """the model's own events over the script: melee and missile decisions, every attack action the four kinds
    run, a justattacked read, and near-LOS traces both clear and blocked -- each control below needs its path"""
    script = _script()
    w = _world()
    ws, n = w.ws, w.layout.nmon
    traces = {True: 0, False: 0}
    base = w.los_to_player

    def counting(world, m):
        v = base(world, m)
        traces[v] += 1
        return v
    w.los_to_player = counting
    dec, acts, ja, jh = set(), set(), 0, 0
    d = _dying(w)
    assert ws.mon_solid[d], "the dying monster starts solid"
    for fr in script:
        _set(w, *fr)
        before = list(ws.mon_justattacked[:n])
        bjh = list(ws.mon_justhit[:n])
        ev = TicEvents(0)
        w._monsters_phase(ev)
        dec |= {k for _, k in ev.decisions}
        acts |= {a for _, a in ev.attacks}
        ja += sum(1 for m in range(n) if before[m] and not ws.mon_justattacked[m])
        jh += sum(1 for m in range(n) if bjh[m] and not ws.mon_justhit[m])
    assert dec == {"melee", "missile"}, dec
    assert acts >= {"A_PosAttack", "A_SPosAttack", "A_TroopAttack", "A_SargAttack"}, acts
    assert ja >= 1, "no justattacked was ever read"
    assert jh >= 4, "justhit was read %d times" % jh
    assert not ws.mon_solid[d], "the dying monster never ran A_Fall"
    assert traces[True] >= 2 and traces[False] >= 2, traces    # test_monster_sight_fj covers the LOS in depth


def test_the_decide_tic_follows_the_model(tmp_path):
    assert _run(tmp_path, "mdecide"), "the fj decide tic parted from the model's decide mode"


@pytest.mark.parametrize("mut", ["noroll", "nolos", "nojust", "nodraws", "nojhclear", "nofall"])
def test_control_a_broken_decision_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mdecide_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
