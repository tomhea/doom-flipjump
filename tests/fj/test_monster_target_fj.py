"""M7 P8a I (docs/gp-final-plan.md 1.2.2 / 1.2.3): the monsters' tic WITH TARGETS on the real flipjump engine -- the
slots of `monstercode.p32a_slot(fight=True)` (the wide `mon_target`, monsterdecide's target load `mt_load` before
A_Chase's threshold, the lost target's all-around look then the spawn state's A_Look), the decide leaves in their fight
emission (the target's distance, reach and attack sight -- the player's seen mark and near trace `sl_los`, a monster's
FAR LOS `sl_far` --, P_NewChaseDir toward the target), and md_attack at the target (the bullets' scan of the things in
the way, the claw and the bite on a monster target) -- against the model's `_monsters_phase` in World(monsters="final",
player="final", sight_rule="seen").

THE SCRIPT: a crowd woken around the player's start with targets poked to OTHER MONSTERS (alive, and some killed on
the way: a dead target is lost) and to the player, who moves about and dies for a stretch; random seen marks. The
damage leaves are stubs that print each call (dp_go: damage, source; dm_go: id, damage, mode, source), as the model's
damage_player / damage_monster / damage_barrel are recorders (nothing is applied: both sides keep the script's cells);
pj_spawn prints the shooter and the target it aims at. After every frame: every slot's state, tics, facing, target,
reaction, threshold, movedir, movecount, stream, justattacked, justhit, position, floorz and leaf, and the cursor.

R9 (each must part): a dead monster target never lost (the threshold and the chase read p_dead); the all-around look
skipped (a lost target goes straight to the spawn state); P_NewChaseDir toward the player; a monster target's melee
reach the player's; a monster target's attack sight ignored (sl_far never consulted)."""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import monstermove as MM
from doomfj import monstersight as MS
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, generate_point_location_fj, monster_cells_fj,
                              point_location_decls)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
from doomfj.world import DROPOFF_MAX, NEWCHASEDIR_MAX_TRIES, CHASE_DEADZONE, STEP_UP, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = 150
M32 = 0xFFFFFFFF
NTG = 2                                    # mon_target's nibbles with infighting


def _world():
    """the slots within 900 units of the crowd's centre woken, each targeting another of them (a third the player);
    reaction spent; the rest asleep"""
    w = World(monsters="final", player="final", sight_rule="seen")
    ws, n = w.ws, w.layout.nmon
    cx, cy = 300, 1300
    near = [m for m in range(n) if ws.mon_active[m] and max(abs(ws.mon_x[m] - cx), abs(ws.mon_y[m] - cy)) < 900]
    rnd = random.Random(0x7A6)
    for k, m in enumerate(near):
        w._set_state(m, w.mon_info[m].seestate, False, TicEvents(0))
        ws.mon_reaction[m] = 0
        vis = [j for j in near if j != m and w.los_points((ws.mon_x[m] << 16, ws.mon_y[m] << 16),
                                                          (ws.mon_x[j] << 16, ws.mon_y[j] << 16))]
        ws.mon_target[m] = 1 if k % 4 == 0 else 2 + rnd.choice(vis or [j for j in near if j != m])
    return w


def _awake(w):
    return [m for m in range(w.layout.nmon) if w.ws.mon_target[m]]


def _script():
    """per frame: (player x16, y16, angle, p_dead, seen slots, slots killed this frame)"""
    w = _world()
    rnd = random.Random(0xF16)
    n = w.layout.nmon
    awake = _awake(w)
    out = []
    px, py = -200, 1300
    for f in range(FRAMES):
        px += rnd.randint(-40, 40)
        py += rnd.randint(-40, 40)
        dead = int(40 <= f < 55)
        seen = set(rnd.sample(awake, min(6, len(awake))))
        kill = set()
        if f in (10, 25, 60, 80):                     # a TARGET killed: whoever chases it loses it
            targets = sorted({w.ws.mon_target[m] - 2 for m in awake if w.ws.mon_target[m] >= 2}
                             - {m for m in range(n) if not w.ws.mon_shootable[m]})
            if targets:
                kill = {rnd.choice(targets)}
        rec = (((px << 16) | rnd.randrange(1 << 16)) & M32, ((py << 16) | rnd.randrange(1 << 16)) & M32,
               rnd.randrange(1 << 32), dead, seen, kill)
        out.append(rec)
        _set(w, *rec)
        _hook(w, [])
        w._monsters_phase(TicEvents(0))
    return out


def _s32(v):
    return v - (1 << 32) if v >> 31 else v


def _set(w, x16, y16, ang, dead, seen, kill):
    ws = w.ws
    ws.px, ws.py, ws.pangle = _s32(x16), _s32(y16), ang
    ws.p_dead, ws.p_health = dead, 0 if dead else 100
    for m in range(w.layout.nmon):
        ws.mon_seen[m] = int(m in seen)
    for m in kill:
        ws.mon_shootable[m], ws.mon_health[m] = 0, 0


def _hook(w, log):
    n = w.layout.nmon
    mode = {"v": 3}

    def dp(dmg, source, inflictor, ev):
        log.append("P%02x%02x" % (dmg, source[1] + 1))

    def dmon(j, dmg, source, inflictor, ev):
        log.append("M%02x%02x%x%02x" % (1 + j, dmg, mode["v"], 2 + source[1]))

    def dbar(b, dmg, source, ev):
        log.append("M%02x%02x4%02x" % (1 + n + b, dmg, 2 + source[1]))

    def spawn(m, ev):
        tx, ty = w._target_pos16(m)
        log.append("F%04x%04x%08x%08x" % (w.ws.mon_x[m] & 0xFFFF, w.ws.mon_y[m] & 0xFFFF, tx & M32, ty & M32))
    w.damage_player, w.damage_monster, w.damage_barrel, w._spawn_fireball = dp, dmon, dbar, spawn
    w._spawn_fx_at_target = lambda *a: None
    base = type(w)._mon_hitscan

    def hitscan(m, bullets, ev):
        mode["v"] = 4
        try:
            base(w, m, bullets, ev)
        finally:
            mode["v"] = 3
    w._mon_hitscan = hitscan


def _row(w):
    ws, n = w.ws, w.layout.nmon
    s = "".join("%02x%x%x%02x%x%02x%x%02x%02x%x%x%04x%04x%04x%03x" % (
        ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m], ws.mon_target[m], ws.mon_reaction[m],
        ws.mon_threshold[m], ws.mon_movedir[m], ws.mon_movecount[m] & 0xFF, ws.mon_rng[m], ws.mon_justattacked[m],
        ws.mon_justhit[m], ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m])
        for m in range(n))
    return s + "%02x" % ws.sched_cursor


def _expected(script) -> bytes:
    w = _world()
    ws = w.ws
    lines = []
    for fr in script:
        log = []
        _hook(w, log)
        _set(w, *fr)
        w._monsters_phase(TicEvents(0))
        lines += log + [_row(w)]
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "target_stale": None,                                       # the slots' mt_al tests read p_dead (below)
    "no_reacquire": None,                                       # a lost target: straight to the spawn state
    "ncd_player": ("    hex.mov 4, mm_dx, mt_tqx + 4*dw\n", "    hex.mov 4, mm_dx, viewx + 4*dw\n"),
    "reach_player": ("    hex.cmp 4, mt_d, mt_reach, mm_dc_mr2, mm_dc_ms, mm_dc_ms\n",
                     "    hex.cmp 4, mt_d, mt_c60, mm_dc_mr2, mm_dc_ms, mm_dc_ms\n"),
    "los_ignored": ("    stl.fcall sl_far, sf_ret\n    hex.if0 1, sl_hit, mm_as_out\n", "    ;mm_as_out\n"),
}


def _parts(w, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    assert MC.cell_nibbles(schema, "mon_target") == NTG
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    things, _var = MM.static_blockers(w)
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
                          dmg=True, hurt=dict(sp=gd.STATE_INDEX[info.spawnstate], spt=gd.STATES[info.spawnstate].tics),
                          fight=True))
    secs = sorted({w.leaf_sector[s] for s in range(len(w.cmap.subsectors))})
    tables = MC.p30_tables_fj() + H.tables_fj(w.hwt) + MD.fight_tables_fj(w.rm.sine)
    tables += [generate_dispatch_table_fj("rj%d" % s, [int(w.reject.visible(s, q)) for q in range(w.reject.nsec)],
                                          index_nibbles=2, result_nibbles=1) for s in secs]
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3, result_nibbles=2))
    tables.append(generate_point_location_fj(w.cmap))
    tables += [generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
               generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
               generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    fields = MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS + MD.P32C_FIELDS
    vals = {f: list(getattr(ws, f)[:n]) for f in fields}
    msec = [w._mon_sector(m) for m in range(n)]
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)], nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)])
    fp = MD.fight_parts(w, list(range(n)))
    nbar = len(w.barrel_things)
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, msec)
             + MC.p32c_decls(schema, n, {f: vals[f] for f in MD.P32C_FIELDS})
             + DC.field_decls(schema, n, {f: list(getattr(ws, f)[:n]) for f in DC.P42_FIELDS}) + ["mm_jh: hex.vec 1"]
             + MD.context_decls() + MS.SL_DECLS + MS.SF_DECLS + fp["decls"] + H.hurt_decls(H.level_start(w))
             + MC.MT_DECLS + MC.P32A_SCRATCH + point_location_decls() + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + LEAF_LINK_DECLS + MM.monster_seed_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tret: hex.vec w/4", "pj_sret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2",
                "dm_ret: hex.vec w/4",
                "thpos_rt: hex.vec %d, %d" % (16 * n, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32) << 32)
                                                          << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * n, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * n),
                "dstate: hex.vec %d" % (2 * len(w.door_order)), "ddir: hex.vec %d" % (2 * len(w.door_order)),
                "dreq: hex.vec %d" % (2 * len(w.door_order)),
                "lstate: hex.vec %d" % (2 * len(w.lift_order)), "lreq: hex.vec %d" % (2 * len(w.lift_order)),
                "fswitch: hex.vec 1", "dbox: hex.vec 8",
                "bar_solid: hex.vec %d, %d" % (2 * nbar, sum(ws.bar_solid[b] << (4 * b) for b in range(nbar))),
                "bar_st: hex.vec %d, %d" % (2 * nbar, sum(ws.bar_state[b] << (8 * b) for b in range(nbar))),
                "bar_hp: hex.vec %d, %d" % (2 * nbar, sum((ws.bar_health[b] & 0xFF) << (8 * b) for b in range(nbar))),
                "mc_don: hex.vec 2"])
    move = (MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], solid="mon_solid", hurt=True)
            + MM.move_leaf_lines(root=root, lift_trigs=lift_trigs, door_boxes=door_boxes, dropmax=DROPOFF_MAX,
                                 stepup=STEP_UP, height=56)
            + MM.ncd_leaf_lines(deadzone=CHASE_DEADZONE, max_tries=NEWCHASEDIR_MAX_TRIES, fight=True)
            + MM.walk_leaf_lines(max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.chase_leaf_lines() + MD.decide_leaves(justhit=True, full=True, fight=True)
            + MS.near_los_lines(w, fight=True) + MS.far_los_lines(w) + fp["lines"])
    stubs = ["dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
             "    stl.output 10", "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "dm_go:", "    stl.output 77", "    hex.print_as_digit 2, dm_id, 0", "    hex.print_as_digit 2, dm_dmg, 0",
             "    hex.print_as_digit 1, dm_melee, 0", "    hex.print_as_digit 2, dm_src, 0", "    stl.output 10",
             "    hex.zero 2, dm_src", "    stl.fret dm_ret",
             "pj_spawn:", "    stl.output 70", "    hex.print_as_digit 4, mm_x, 0", "    hex.print_as_digit 4, mm_y, 0",
             "    hex.print_as_digit 8, mt_tqx, 0", "    hex.print_as_digit 8, mt_tqy, 0", "    stl.output 10",
             "    stl.fret pj_sret"]
    code = (["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False) + ["    stl.fret mt_tret"]
            + MC.p32a_leaves() + MC.p32b_rj_leaf(secs) + move + seed + stubs)
    text = "\n".join(code + [cells] + tables) + "\n"
    if mut == "target_stale":
        import re
        text, k1 = re.subn(r"    hex\.if0 1, mt_al, (mw\d+_)", r"    hex.if1 1, p_dead, \1", text)
        text, k2 = re.subn(r"    hex\.if1 1, mt_al, (mw\d+_)", r"    hex.if0 1, p_dead, \1", text)
        assert k1 == k2 == n, (k1, k2)
    elif mut == "no_reacquire":
        import re
        text, k = re.subn(r"    hex\.if1 1, p_dead, (mw\d+_sp)\n", r"    ;\1\n", text)
        assert k == n, k
    elif mut:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    return decls, text


def _build(tmp_path, name, mut=None):
    w = _world()
    n = w.layout.nmon
    script = _script()
    body = ["stl.startup_and_init_all"]
    for x16, y16, ang, dead, seen, kill in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set 1, p_dead, %d" % dead, "hex.set 3, p_hp, %d" % (0 if dead else 100),
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen))]
        body += ["hex.zero 1, mon_shootable + %d*dw" % m for m in sorted(kill)]
        body += ["hex.zero 3, mon_health + %d*dw" % (3 * m) for m in sorted(kill)]
        body += ["stl.fcall mt_tic_leaf, mt_tret"]
        for m in range(n):
            body += ["hex.print_as_digit 2, mon_state + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_tics + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_target + %d*dw, 0" % (NTG * m),
                     "hex.print_as_digit 1, mon_reaction + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_threshold + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_movedir + %d*dw, 0" % m,
                     "hex.print_as_digit 2, mon_movecount + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 2, mon_rng + %d*dw, 0" % (2 * m),
                     "hex.print_as_digit 1, mon_justattacked + %d*dw, 0" % m,
                     "hex.print_as_digit 1, mon_justhit + %d*dw, 0" % m,
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0",
                 "hex.zero %d, dreq" % (2 * len(w.door_order)), "hex.zero %d, lreq" % (2 * len(w.lift_order)),
                 "stl.output 10"]
    body += ["stl.loop"]
    decls, text = _parts(w, mut)
    from doomfj.wall_renderer import hoisted_scratch_fj
    prog = "\n".join(body + decls + [text]) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(script)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_script_exercises_every_path():
    """the model's own events: decisions at monster targets (melee and missile), far LOS traces both ways, attacks
    landing on monsters, a lost monster target re-acquiring the player and one returning to its spawn state, a
    threshold reset by a dead target"""
    script = _script()
    w = _world()
    ws, n = w.ws, w.layout.nmon
    far = {True: 0, False: 0}
    base = World.los_to_target

    def counting(world, m):
        v = base(world, m)
        far[v] += 1
        return v
    w.los_to_target = counting
    seen = dict(dec_mon=0, hit_mon=0, reacq=0, to_spawn=0, fire_mon=0)
    for fr in script:
        log = []
        _hook(w, log)
        _set(w, *fr)
        before_t = list(ws.mon_target[:n])
        before_s = list(ws.mon_state[:n])
        ev = TicEvents(0)
        w._monsters_phase(ev)
        seen["dec_mon"] += sum(1 for m, _k in ev.decisions if before_t[m] >= 2)
        seen["hit_mon"] += sum(1 for ln in log if ln[0] == "M")
        seen["fire_mon"] += sum(1 for ln in log if ln[0] == "F" and int(ln[9:17], 16) & 0xFFFF == 0)
        for m in range(n):
            if before_t[m] >= 2 and ws.mon_target[m] == 1:
                seen["reacq"] += 1
            if before_t[m] >= 2 and ws.mon_state[m] == gd.STATE_INDEX[w.mon_info[m].spawnstate] != before_s[m]:
                seen["to_spawn"] += 1
    print(seen, far)
    want = dict(dec_mon=5, hit_mon=3, reacq=1, to_spawn=1, fire_mon=1)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())
    assert far[True] >= 3 and far[False] >= 3, far


def test_the_target_tic_follows_the_model(tmp_path):
    assert _run(tmp_path, "mtarget"), "the fj fight tic parted from the model's"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_target_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mtarget_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
