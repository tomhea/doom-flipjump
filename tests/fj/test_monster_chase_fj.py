"""M7 P3.2b (docs/gp-monsters.md 8.4): the CHASE tic on the real flipjump engine against the model's chase mode
(World(monsters="chase", sight_rule="seen")) -- every slot's state, tics, facing, target, reaction, threshold,
movedir, movecount, P_Random state, position, floorz and leaf, the cursor, the monster door presses (`dreq`) and
the lift triggers (`lreq`) after every frame, and every leaf's list at the end.

The whole move runs: the unrolled slots (monstercode.p32a_slot's chase mode), the shared leaves (monstermove:
mm_chase, mm_move, mm_things, mm_ncd, mm_walk), the monsters' cells with the static blockers, the seed through
ptloc_walk, the relink (sim.leaf_unlink / leaf_link) and the REJECT leaf by the monster's sector. The world is
woken at the start (World.wake_all) so every monster chases; the player walks a script past the monster groups.
Doors and lifts do not tic here (their presses and triggers are compared, then cleared on both sides).

R9: a NewChaseDir without its cap, a move that ignores the other monsters, and a relink that never happens must
each part from the model.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import monstermove as MM
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, generate_point_location_fj, monster_cells_fj,
                              point_location_decls)
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
from doomfj.world import DROPOFF_MAX, NEWCHASEDIR_MAX_TRIES, CHASE_DEADZONE, STEP_UP, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FRAMES = 40
M32 = 0xFFFFFFFF


LIFT_SPOT = (1313, -390)             # slot 0 (radius 30): stepping north crosses lift 103's WR line y = -384
PIT_SPOT = (855, 1163)               # slot 1: every direction refused -- NewChaseDir runs into its cap
LIFT_PLAYER = (1313, -100)           # the player north of the lift for the first frames
DOOR_SPOT = (2255, 276)              # slot 2 (radius 30) in door 54's monster use box, 7 of 8 steps refused
CAP_SPOT = (719, 1706)               # slot 3: ONE direction open (west) -- the cap stops NewChaseDir before it


def _world():
    w = World(monsters="chase", sight_rule="seen")
    w.wake_all()
    w.teleport_monster(0, *LIFT_SPOT)
    w.teleport_monster(1, *PIT_SPOT)
    w.teleport_monster(2, *DOOR_SPOT)
    w.teleport_monster(3, *CAP_SPOT)
    return w


def _script(w):
    """per frame: (player x16, y16, angle, seen slots) -- the player stands by one awake group after another"""
    rnd = random.Random(0x32B)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for f in range(FRAMES):
        m = act[(f // 8 * 11) % len(act)]
        ox, oy = [(90, 20), (-120, 60), (160, -80), (-60, -150)][(f // 8) % 4]
        x16, y16 = (w.ws.mon_x[m] + ox) << 16 | 0x2000, (w.ws.mon_y[m] + oy) << 16
        if f < 8:
            x16, y16 = LIFT_PLAYER[0] << 16, LIFT_PLAYER[1] << 16
        out.append((x16 & M32, y16 & M32, rnd.randrange(1 << 32), set(rnd.sample(act, 5))))
    return out


def _row(w):
    ws, n = w.ws, w.layout.nmon
    s = "".join("%02x%x%x%x%x%02x%x%02x%02x%04x%04x%04x%03x" % (
        ws.mon_state[m], ws.mon_tics[m], ws.mon_facing[m], ws.mon_target[m], ws.mon_reaction[m],
        ws.mon_threshold[m], ws.mon_movedir[m], ws.mon_movecount[m] & 0xFF, ws.mon_rng[m],
        ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m]) for m in range(n))
    s += "%02x" % ws.sched_cursor
    s += "".join("%x" % ws.d_monreq[d] for d in range(len(w.door_order)))
    s += "".join("%x" % ws.l_req[k] for k in range(len(w.lift_order)))
    return s


def _expected(script) -> bytes:
    w = _world()
    ws, n = w.ws, w.layout.nmon
    lines = []
    for x16, y16, ang, seen in script:
        ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
        ws.pangle = ang
        for m in range(n):
            ws.mon_seen[m] = int(m in seen)
        w._monsters_phase(TicEvents(0))
        lines.append(_row(w))
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
    lists = w.leaf_lists()
    lines.append("".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks if k < n))
                         for leaf, ks in sorted(lists.items()) if any(k < n for k in ks)))
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
                          mv=dict(rt=m, radius=w.mon_radius[m], speed=w.mon_speed[m])))
    secs = sorted({w.leaf_sector[s] for s in range(len(w.cmap.subsectors))})
    tables = MC.p30_tables_fj()
    tables += [generate_dispatch_table_fj("rj%d" % s, [int(w.reject.visible(s, q)) for q in range(w.reject.nsec)],
                                          index_nibbles=2, result_nibbles=1) for s in secs]
    nleaf = len(w.cmap.subsectors)
    tables.append(generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3, result_nibbles=2))
    tables.append(generate_point_location_fj(w.cmap))
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    msec = [w._mon_sector(m) for m in range(n)]
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)], nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)])
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": ws.sched_cursor}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, msec)
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
    move = (MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)])
            + MM.move_leaf_lines(root=root, lift_trigs=lift_trigs, door_boxes=door_boxes, dropmax=DROPOFF_MAX,
                                 stepup=STEP_UP, height=56)
            + MM.ncd_leaf_lines(deadzone=CHASE_DEADZONE, max_tries=NEWCHASEDIR_MAX_TRIES)
            + MM.walk_leaf_lines(max_tries=99 if mut == "nocap" else NEWCHASEDIR_MAX_TRIES)
            + MM.chase_leaf_lines())
    code = (["mt_tic_leaf:"] + MC.p32a_tic_lines(schema, n, slots, exit_guard=False) + ["    stl.fret mt_tret"]
            + MC.p32a_leaves() + MC.p32b_rj_leaf(secs) + move + seed)
    text = "\n".join(code + [cells] + tables)
    if mut == "nothings":
        text = text.replace("    stl.fcall mm_things, mm_tret\n", "")
    if mut == "norelink":
        text = text.replace("    sim.leaf_link mm_tw, mm_leafw\n", "")
    return decls, text


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def _build(tmp_path, name, mut=None):
    """-> (fj sources, the expected output)"""
    w = _world()
    n = w.layout.nmon
    script = _script(w)
    body = ["stl.startup_and_init_all"]
    for x16, y16, ang, seen in script:
        body += ["hex.set 8, viewx, %d" % x16, "hex.set 8, viewy, %d" % y16,
                 "hex.set %d, thseen, %d" % (n, sum(1 << (4 * m) for m in seen)),
                 "stl.fcall mt_tic_leaf, mt_tret"]
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
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m)]
        body += ["hex.print_as_digit 2, sched_cursor, 0"]
        body += ["hex.print_as_digit 1, dreq + %d*dw, 0" % d for d in range(len(w.door_order))]
        body += ["hex.print_as_digit 1, lreq + %d*dw, 0" % k for k in range(len(w.lift_order))]
        body += ["hex.zero %d, dreq" % (2 * len(w.door_order)), "hex.zero %d, lreq" % (2 * len(w.lift_order)),
                 "stl.output 10"]
    body += ["stl.fcall ll_dump, dump_ret", "stl.loop"]
    decls, text = _parts(w, mut)
    dump = ["ll_dump:"]
    # every leaf with a monster: "lll:" then its list's monsters ("mm," each), in list order
    for leaf in range(len(w.cmap.subsectors)):
        dump += ["    hex.set w/4, ll_base, sshead", "    hex.set w/4, ll_idx, %d" % leaf,
                 "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
                 "    hex.if0 2, ll_v, dl%d_end" % leaf,
                 "    hex.set 3, dl_leaf, %d" % leaf, "    hex.print_as_digit 3, dl_leaf, 0", "    stl.output 58",
                 "  dl%d_loop:" % leaf,
                 "    hex.dec 2, ll_v", "    hex.print_as_digit 2, ll_v, 0",
                 "    hex.set w/4, ll_base, thnext", "    hex.zero w/4, ll_idx", "    hex.mov 2, ll_idx, ll_v",
                 "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
                 "    hex.if0 2, ll_v, dl%d_end" % leaf, "    stl.output 44", "    ;dl%d_loop" % leaf,
                 "  dl%d_end:" % leaf]
    dump += ["    stl.output 10", "    stl.fret dump_ret"]
    prog = "\n".join(body + decls + ["dump_ret: hex.vec w/4", "dl_leaf: hex.vec 3"] + dump + [text]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(script)


def test_the_script_exercises_every_path():
    """the model's own events over the script: moves, relinks, NewChaseDir calls AND its cap, a monster door press,
    a lift trigger and a monster refused by another thing -- each of the controls below needs its path to run"""
    w = _world()
    ws, n = w.ws, w.layout.nmon
    tot = dict(moves=0, relinks=0, ncd=0, capped=0, doors=0, lifts=0, things=0)
    for x16, y16, ang, seen in _script(w):
        ws.px, ws.py = x16 - (1 << 32) if x16 >> 31 else x16, y16 - (1 << 32) if y16 >> 31 else y16
        for m in range(n):
            ws.mon_seen[m] = int(m in seen)
        ev = TicEvents(0)
        w._monsters_phase(ev)
        tot["moves"] += len(ev.moves)
        tot["relinks"] += len(ev.leaf_changes)
        tot["ncd"] += ev.newchasedir
        tot["capped"] += ev.capped
        tot["doors"] += len(ev.door_uses)
        tot["lifts"] += sum(ws.l_req[k] for k in range(len(w.lift_order)))
        tot["things"] += ev.blocked["thing"]
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
    want = dict(moves=100, relinks=5, ncd=30, capped=1, doors=1, lifts=1, things=1)
    assert all(tot[k] >= v for k, v in want.items()), (tot, want)


def test_the_cap_decides_something():
    """the `nocap` control can only bite where a direction the cap forbids would have been OPEN (a monster boxed in
    on every side ends at NODIR either way): the model itself, run without the cap, must part from the script"""
    import doomfj.world as Wm

    def rows(cap):
        old, Wm.NEWCHASEDIR_MAX_TRIES = Wm.NEWCHASEDIR_MAX_TRIES, cap
        try:
            return _expected(_script(_world()))
        finally:
            Wm.NEWCHASEDIR_MAX_TRIES = old
    assert rows(NEWCHASEDIR_MAX_TRIES) != rows(99), "no capped NewChaseDir in the script left a direction untried"


def test_the_chase_tic_follows_the_model(tmp_path):
    assert _run(tmp_path, "mchase"), "the fj chase tic parted from the model's chase mode"


@pytest.mark.parametrize("mut", ["nocap", "nothings", "norelink"])
def test_control_a_broken_move_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "mchase_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
