"""M7 P6 (doomfj.lootcode): THE PLAYER'S MOVE WITH THINGS on the real flipjump engine -- the very text the emitter
splices: `collision.move_with_collision_lines(pickup=, block=, skip_still=True)` over the player's collision cells
WITH the static blockers (`player_cell_things`, `THING_TEST16`), `pb_mon`, and `pk_go` -- against the model's own
`combat._player_move` (`_solid_thing_at`, `_touch_specials`, `try_move`), tic by tic in ONE image.

Each record stands the player at a legal spot (the model's check_position and no solid thing in the way) a little
short of a target -- a live solid monster (its slot moved there), a corpse (active, no longer solid: it does not
block), a barrel (standing, or removed: bar_solid 0), a solid decoration (on or off this skill: mc_don), a pickup --
and steps him toward it (forward or strafing, the angle often an exact multiple of 90 degrees, so one axis of the step
is 0 and a candidate IS the tic-start position: the model skips it, `skip_still`), with the doors and lifts in random
states. Some records stand him ON an item he could not take before, beside a wall of monster: the only candidate that
touches it is the skipped one. After every record: the position, the player's cells and every pickup's thvis slot.

The seed descent the move calls (`e1m1_dsccs_walk`, the emitter's BSP descent) is stood in for by the same answer the
monsters' seed gives: `ptloc_walk` then `ms_seed_leaf` (the leaf's sector, doors open, movers at their states).

R9 (MUTANTS), each must part: no `block` (the player walks through monsters), a corpse that blocks (pb_mon on
mon_active), a removed barrel that blocks (the presence test gone), the static blockers tested on whole units
(`sim.thing_test`), a monster box that is inclusive, the still candidate tried (no `skip_still`), and the still
candidate tried at a negative coordinate (`still_signed`: the model's old masked compare, fixed by the coordinator's
decision in M7 P6+P7 -- a still candidate is skipped at every coordinate).
"""
import math
import random
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import hurtcode as H
from doomfj import lootcode as L
from doomfj import monstermove as MM
from doomfj import weaponcode as WC
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, cell_lists, collision_cells_fj, generate_point_location_fj,
                              line_rows, mover_line_openings, move_with_collision_lines, point_location_decls)
from doomfj.config import Config
from doomfj.fixedpoint import fixed_mul
from doomfj.harness import W
from doomfj.monsters import MonsterViews
from doomfj.reference_model import FORWARD_MOVE, MAX_STEP, PLAYER_HEIGHT, PLAYER_RADIUS, STRAFE_MOVE
from doomfj.wad import WadFile
from doomfj.world import KEYS, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
ART = ROOT / "assets" / "freedoom1.wad"
N = 360
M32 = 0xFFFFFFFF
ANG90 = 0x40000000
PCELLS = (("viewx", 8), ("viewy", 8), ("p_hp", 3), ("p_ar", 2), ("am_clip", 3), ("am_shell", 3), ("p_bc", 2))


class Ctx:
    def __init__(self):
        self.w = World(skill=gd.SK_HARD, monsters="idle", player="fire")
        w = self.w
        self.art = WadFile.from_path(str(ART))
        self.mv = MonsterViews(w.rm, w.mw, "E1M1", self.art, w)
        self.slots = L.pickup_slots(w, w.rm, w.mw, "E1M1", self.art)
        self.things, self.var = MM.static_blockers(w)


def _keys(fwd=False, sl=False, sr=False):
    k = dict.fromkeys(KEYS, False)
    k["forward"], k["strafe_left"], k["strafe_right"] = fwd, sl, sr
    return k


def _delta(w, angle, keys):
    """the tic's desired move, exactly `combat._player_move`'s (what `_player_sim_lines` hands the move in cm_dx/dy)"""
    rmod = w.rm
    move = (FORWARD_MOVE if keys["forward"] else 0) - (FORWARD_MOVE if keys["back"] else 0)
    side = (STRAFE_MOVE if keys["strafe_right"] else 0) - (STRAFE_MOVE if keys["strafe_left"] else 0)
    dx = dy = 0
    if move:
        dx += fixed_mul(move & M32, rmod.read_cos(angle), 8, 4)
        dy += fixed_mul(move & M32, rmod.read_sin(angle), 8, 4)
    if side:
        dx += fixed_mul(side & M32, rmod.read_sin(angle), 8, 4)
        dy -= fixed_mul(side & M32, rmod.read_cos(angle), 8, 4)
    return dx, dy


def _apply(c, rec):
    w, ws = c.w, c.w.ws
    ws.px, ws.py, ws.pangle = rec["pos"][0], rec["pos"][1], rec["angle"]
    ws.p_health, ws.p_dead = rec["hp"], 0
    for m, (x, y, act, sol) in rec["mons"].items():
        ws.mon_x[m], ws.mon_y[m], ws.mon_active[m], ws.mon_solid[m] = x, y, act, sol
    for b, v in rec["bars"].items():
        ws.bar_solid[b] = v
    for i, v in rec["present"].items():
        ws.pickup_taken[i] = 1 - v
    for d, v in enumerate(rec["doors"]):
        ws.d_state[d] = v
    for k, v in enumerate(rec["lifts"]):
        ws.l_state[k] = v
    w._decor_now = w._decor_for(rec["skill"])
    w._door_phase_scene()


def _legal(c, x16, y16) -> bool:
    w = c.w
    return w.rm.check_position(w.scene_c, x16, y16)[0] and w._solid_thing_at(x16, y16) is None


def _records(c):
    w = c.w
    rnd = random.Random(0x6D)
    out = []
    P = w.pickup_things
    while len(out) < N:
        kind = rnd.choice(("mon", "mon", "corpse", "bar", "bar", "decor", "decor", "item", "still"))
        rec = {"kind": kind, "mons": {}, "bars": {}, "present": {}, "hp": rnd.choice((50, 100, 150)),
               "skill": rnd.choice((gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)),
               "doors": [rnd.choice((0, 0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order],
               "lifts": [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]}
        m = rnd.randrange(w.layout.nmon)
        if kind in ("mon", "corpse"):
            base = w.mon_things[m] if rnd.random() < 0.6 else rnd.choice(w.things)
            tx, ty = base.x + rnd.randint(-8, 8), base.y + rnd.randint(-8, 8)
            rec["mons"][m] = (tx, ty, 1, int(kind == "mon"))
            tr = w.mon_radius[m]
        elif kind == "bar":
            b = rnd.randrange(len(w.barrel_things))
            rec["bars"][b] = rnd.choice((1, 1, 1, 0))
            tx, ty, tr = w.barrel_things[b].x, w.barrel_things[b].y, 10
        elif kind == "decor":
            k = rnd.choice(c.var) if c.var and rnd.random() < 0.5 else rnd.randrange(len(w.decor_solid))
            t = w.decor_solid[k]
            tx, ty, tr = t.x, t.y, gd.THING_TYPES[t.type].radius
        else:
            i = rnd.randrange(len(P))
            tx, ty, tr = P[i].x, P[i].y, 20
            rec["present"][i] = 1
        if kind == "still":
            # ON an item (30 units east / north of it), a wall of monster ahead: only the still candidate touches it --
            # and the model skips that one at every coordinate, negative ones included (collision's skip_still)
            i = rnd.randrange(len(P))
            ax = rnd.choice((0, 1))
            rec["angle"] = 0 if ax == 0 else ANG90
            px, py = (P[i].x + 30, P[i].y) if ax == 0 else (P[i].x, P[i].y + 30)
            rec["pos"] = ((px << 16) + rnd.choice((0, 0x4000)), (py << 16) + rnd.choice((0, 0x4000)))
            rec["present"][i] = 1
            rec["hp"] = 50
            rec["mons"][m] = ((px + 40, py, 1, 1) if ax == 0 else (px, py + 40, 1, 1))
            rec["keys"] = _keys(fwd=True)
        else:
            ang = rnd.choice((0, ANG90, 2 * ANG90, 3 * ANG90, 0x20000000, 0xA0000000, rnd.randrange(1 << 32)))
            back = ang + 2 * ANG90 & M32
            d = tr + 16 + rnd.choice((1, 2, 5, 9, 14, 16, 16, 20))   # 16: the full step ends ON the box edge
            fa = (back >> 20) & 4095
            ox = int(round(d * math.cos(fa * 2 * math.pi / 4096) * 65536))
            oy = int(round(d * math.sin(fa * 2 * math.pi / 4096) * 65536))
            rec["pos"] = (((tx << 16) + ox) + rnd.choice((0, 0, 0x8000, 0x1)), ((ty << 16) + oy) + rnd.choice((0, 0, 0xFFFF)))
            if rnd.random() < 0.2:
                rec["angle"] = ang - ANG90 & M32
                rec["keys"] = _keys(sr=True) if rnd.random() < 0.5 else _keys(fwd=True, sr=True)
            else:
                rec["angle"] = ang
                rec["keys"] = _keys(fwd=True)
        snap, decor = w.ws.copy(), w._decor_now
        _apply(c, rec)
        if not _legal(c, *rec["pos"]):
            w.ws, w._decor_now = snap, decor               # a rejected record leaves no trace
            continue
        out.append(rec)
    return out


def _row(c) -> str:
    w, ws = c.w, c.w.ws
    vals = [ws.px & M32, ws.py & M32, ws.p_health & 0xFFF, ws.p_armor, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
            ws.p_bonuscount]
    s = "".join("%0*x" % (n, v) for (_c, n), v in zip(PCELLS, vals))
    return s + "".join("%x" % (1 - ws.pickup_taken[i]) for i in range(len(w.pickup_things)))


def _expected(records) -> bytes:
    c = Ctx()
    lines = []
    for rec in records:
        _apply(c, rec)
        c.w._player_move(rec["keys"], TicEvents(0))
        lines.append(_row(c))
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "walk_through": None,
    "corpse_blocks": None,
    # a removed barrel still blocks (its presence test gone). (E1M1's solid decorations stand on every skill:
    # monstermove.static_blockers' `var` is empty, so no mc_don test exists to remove -- test_no_decoration_...)
    "barrel_removed": (r"    hex\.if0 1, bar_solid \+ \d+\*dw, e1m1_cc_t\d+_out\n", ""),
    "whole_units": None,
    "mon_inclusive": (r"(hex\.scmp 8, pb_c, pb_bd\d+, (pbt\d+_[yh])), (pbt\d+_n), ", r"\1, \2, "),
    "still": None,
    # the model's OLD quirk put back: the still candidate is skipped only where its moved coordinate is non-negative
    # (the x-only candidate's x, the y-only one's y), so at a negative one it is touched and tried
    "still_signed": (r"  (cm([bc])_)s0:\n",
                     lambda m: "  %ss0:\n    hex.sign 8, %s, %sgo, %ssq\n  %ssq:\n"
                     % (m.group(1), "viewx" if m.group(2) == "b" else "viewy", m.group(1), m.group(1), m.group(1))),
}


def _program(c, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    from doomfj.reference_model import ML_BLOCKING
    w = c.w
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING, secs_open=kw["secs_open"],
                     door_line_ids=kw["door_line_ids"])
    obs = mover_line_openings(w.lds, w.sds, w.secs, kw["msecs"])
    movers = {li: (kw["mcell"][m_], obs[li]) for li in obs
              for m_ in [next(x for x in (w.sds[w.lds[li].front].sector, w.sds[w.lds[li].back].sector)
                              if x in kw["msecs"])]}
    lists, things = L.player_cell_things(w, cell_lists(rows, PLAYER_RADIUS))
    cells, root = collision_cells_fj("e1m1", rows, lists, doors=kw["doors"], movers=movers, things=things,
                                     thing_test=None if mut == "whole_units" else L.THING_TEST16)
    move = move_with_collision_lines(root, "e1m1", radius=PLAYER_RADIUS, height=PLAYER_HEIGHT >> 16,
                                     maxstep=MAX_STEP >> 16, pickup=L.pickup_call,
                                     block=None if mut == "walk_through" else L.block_lines,
                                     skip_still=mut != "still")
    pb = L.pb_mon_lines(w, c.mv.rt)
    text = "\n".join(["mv_leaf:"] + move + ["    stl.fret mv_ret"]
                     + ["e1m1_dsccs_walk:", "    hex.mov 10, ptx, vx", "    hex.mov 10, pty, vy",
                        "    stl.fcall ptloc_walk, ptloc_ret", "    stl.fcall ms_seed_leaf, ms_seed_ret",
                        "    stl.fret cs_ret"]
                     + pb + L.pickup_lines(w, c.slots, c.mv.rt)) + "\n" + cells
    if mut == "corpse_blocks":
        text, n = re.subn(r"hex\.if0 1, mon_solid \+ ", "hex.if0 1, mon_active + ", text)
        assert n
    elif mut and MUTANTS[mut]:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    ws = w.ws
    n, nrt = w.layout.nmon, c.mv.nrt
    thpos = [0] * nrt
    for m, t in enumerate(c.mv.rt):
        thpos[t] = ((ws.mon_x[m] << 16) & M32) | (((ws.mon_y[m] << 16) & M32) << 32)
    vis = [1] * (c.slots["nvis"] + c.slots["nextra"])
    for i, s in enumerate(c.slots["slot"]):
        vis[s] = 1 - ws.pickup_taken[i]
    wstart = WC.level_start(w.mw, "E1M1")
    states, frames = WC.weapon_states(), WC.overlay_frames()
    nd, nl = len(w.door_order), len(w.lift_order)
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, states, frames) + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + point_location_decls() + MM.monster_seed_decls()
             + ["pcard: hex.vec 1", "thvis:"] + ["    hex.vec 2, %d" % v for v in vis]
             + ["mdrop: hex.vec 25", "dr_live: hex.vec 2", "rtu_t: hex.vec w/4", "rtu_leaf: hex.vec w/4",
                "rtu_ret: hex.vec w/4", "drt_ret: hex.vec w/4", "mv_ret: hex.vec w/4",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "vx: hex.vec 10", "vy: hex.vec 10",
                "thpos_rt: hex.vec %d, %d" % (16 * nrt, sum(v << (64 * t) for t, v in enumerate(thpos))),
                "thss_rt: hex.vec %d" % (16 * nrt),
                "mon_solid: hex.vec %d, %d" % (n, sum(ws.mon_solid[m] << (4 * m) for m in range(n))),
                "mon_active: hex.vec %d, %d" % (n, sum(ws.mon_active[m] << (4 * m) for m in range(n))),
                "bar_solid: hex.vec %d, %d" % (len(w.barrel_things),
                                                sum(ws.bar_solid[b] << (4 * b) for b in range(len(w.barrel_things)))),
                "mc_don: hex.vec %d" % max(1, len(c.var)),
                "dstate: hex.vec %d" % nd, "lstate: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1"])
    # the runtime pickups' unlink and the drops' take are never reached here (no drop, and a stub for the unlink)
    stubs = ["rt_unlink:", "    stl.fret rtu_ret"] + ["drop_take%d:" % k for k in range(25)] + ["    stl.fret drt_ret"]
    return decls, text + "\n" + "\n".join(seed + stubs) + "\n", L.tables_fj(w) + [generate_point_location_fj(w.cmap)]


def _build(tmp_path, name, mut=None):
    from doomfj.wall_renderer import _int_part_lines           # noqa: F401  (the move text calls it via collision)
    records = _records(Ctx())          # (the generation pokes its own World: the program starts from a fresh one)
    c = Ctx()
    w = c.w
    body = ["stl.startup_and_init_all"]
    for rec in records:
        dx, dy = _delta(w, rec["angle"], rec["keys"])
        body += ["hex.set 8, viewx, %d" % (rec["pos"][0] & M32), "hex.set 8, viewy, %d" % (rec["pos"][1] & M32),
                 "hex.set 8, cm_dx, %d" % (dx & M32), "hex.set 8, cm_dy, %d" % (dy & M32),
                 "hex.set 3, p_hp, %d" % rec["hp"], "hex.zero 1, p_dead"]
        for m, (x, y, act, sol) in rec["mons"].items():
            t = c.mv.rt[m]
            body += ["hex.set 16, thpos_rt + %d*dw, %d" % (16 * t, ((x << 16) & M32) | (((y << 16) & M32) << 32)),
                     "hex.set 1, mon_active + %d*dw, %d" % (m, act), "hex.set 1, mon_solid + %d*dw, %d" % (m, sol)]
        for b, v in rec["bars"].items():
            body.append("hex.set 1, bar_solid + %d*dw, %d" % (b, v))
        for i, v in rec["present"].items():
            body.append("hex.set 2, thvis + %d*2*dw, %d" % (c.slots["slot"][i], v))
        don = MM.decor_presence(w, c.var, rec["skill"])
        body += ["hex.set 1, mc_don + %d*dw, %d" % (k, v) for k, v in enumerate(don)]
        body += ["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(rec["lifts"])]
        body += ["stl.fcall mv_leaf, mv_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, cl) for cl, n in PCELLS]
        body += ["hex.print_as_digit 1, thvis + %d*2*dw, 0" % c.slots["slot"][i] for i in range(len(w.pickup_things))]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(c, mut)
    prog = "\n".join(body + decls + [text] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_no_decoration_depends_on_the_skill():
    """no presence flag (mc_don) exists on E1M1: every solid decoration stands on every skill"""
    assert Ctx().var == []


def test_the_records_exercise_every_path():
    """blocked by a monster, a barrel and a decoration; a corpse, a removed barrel and another skill's decoration
    passed; a slide (a later candidate taken); pickups through the move; the still candidate's item left alone"""
    records = _records(Ctx())
    c = Ctx()
    w = c.w
    seen = dict(blocked=0, bymon=0, bybar=0, bydecor=0, passed_corpse=0, slide=0, picked=0, still=0, still_neg=0,
                moved=0)
    for rec in records:
        _apply(c, rec)
        x, y = w.ws.px, w.ws.py
        ev = TicEvents(0)
        bt = list(w.ws.pickup_taken)
        dx, dy = _delta(w, rec["angle"], rec["keys"])
        first = w._solid_thing_at(x + dx, y + dy)
        w._player_move(rec["keys"], ev)
        seen["blocked"] += ev.player_blocked > 0
        seen["bymon"] += first is not None and first[0] == "mon"
        seen["bybar"] += first is not None and first[0] == "bar"
        seen["bydecor"] += first is not None and first[0] == "decor"
        seen["passed_corpse"] += any(not s and a for (_x, _y, a, s) in rec["mons"].values()) and (w.ws.px, w.ws.py) == (x + dx, y + dy)
        seen["slide"] += (w.ws.px, w.ws.py) not in ((x, y), (x + dx, y + dy))
        seen["picked"] += any(w.ws.pickup_taken[i] and not bt[i] for i in range(len(bt)))
        # the item the player stands on, left there: only the skipped still candidate would have touched it
        seen["still"] += rec["kind"] == "still" and any(
            not w.ws.pickup_taken[i] and abs((w.pickup_things[i].x << 16) - x) < L.PK_RADIUS << 16
            and abs((w.pickup_things[i].y << 16) - y) < L.PK_RADIUS << 16 for i in rec["present"])
        # ... and the same with the still coordinate negative: left alone there too (the model's fixed compare; the
        # masked one touched it there and took the item -- `still_signed`)
        seen["still_neg"] += rec["kind"] == "still" and (x < 0 if rec["angle"] else y < 0) and any(
            not w.ws.pickup_taken[i] and abs((w.pickup_things[i].x << 16) - x) < L.PK_RADIUS << 16
            and abs((w.pickup_things[i].y << 16) - y) < L.PK_RADIUS << 16 for i in rec["present"])
        seen["moved"] += (w.ws.px, w.ws.py) != (x, y)
    want = dict(blocked=60, bymon=20, bybar=10, bydecor=10, passed_corpse=5, slide=10, picked=10, still=8,
                still_neg=5, moved=100)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_move_follows_the_model(tmp_path):
    assert _run(tmp_path, "pmove"), "the fj move parted from the model's _player_move"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_move_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "pmove_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
