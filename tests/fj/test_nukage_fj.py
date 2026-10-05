"""M7 P6 (doomfj.lootcode): NUKAGE on the real flipjump engine -- `nk_go`, the very text the emitter splices (the
leveltime test, `ptloc_walk`, `nkleaf`, `ms_seed_leaf`, the player's collision cells WITH the static blockers, and
`dp_go`) -- against the model's own `combat._special_sector`, record by record in ONE image.

Each record stands the player somewhere -- deep in one of E1M1's three special-7 sectors (23, 38, 173), on their
edges where the box reaches a higher floor (a ledge: "falling, not all the way down yet", no damage), or outside --
with `leveltime` at, around and away from a multiple of 32, the doors and lifts in random states, and the health,
armor and damage count poked so that a hit lands, kills, or meets a dead player. After every record: the player's
hurt cells, the weapon (a kill drops it) and the stream.

R9 (MUTANTS), each must part: every 16 tics instead of 32, the floor test gone, a damaging sector missing from
`nkleaf`, the damage read as 10.
"""
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
from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, cell_lists, collision_cells_fj,
                              generate_point_location_fj, line_rows, mover_line_openings, point_location_decls)
from doomfj.combat import half_width_table
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import PLAYER_RADIUS
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 300
M32 = 0xFFFFFFFF
CELLS = (("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("p_dc", 2), ("p_dead", 1), ("rng_pl", 2), ("wp_st", 2),
         ("wp_sy", 2))


def _world():
    return World(skill=gd.SK_HARD, monsters="idle", player="fire")


def _statics_clear(w, x16, y16) -> bool:
    """no static blocker overlaps the player's box (the invariant the move keeps)"""
    for b, t in enumerate(w.barrel_things):
        if w.ws.bar_solid[b] and abs((t.x << 16) - x16) < 26 << 16 and abs((t.y << 16) - y16) < 26 << 16:
            return False
    for t in w._decor_now:
        bd = (w.decor_radius[t.type] + 16) << 16
        if abs((t.x << 16) - x16) < bd and abs((t.y << 16) - y16) < bd:
            return False
    return True


def _records(w):
    rnd = random.Random(0x6E)
    hurt = {23, 38, 173}
    xs = [v[0] for v in w.cmap.vertexes]
    ys = [v[1] for v in w.cmap.vertexes]
    out = []
    while len(out) < N:
        kind = rnd.choice(("in", "in", "in", "out"))
        x = rnd.randint(1200, 2500) if kind == "in" else rnd.randint(min(xs), max(xs))
        y = rnd.randint(600, 1560) if kind == "in" else rnd.randint(min(ys), max(ys))
        x16 = (x << 16) + rnd.choice((0, 0, 0x8000, 0xFFFF))
        y16 = (y << 16) + rnd.choice((0, 0, 0x4000))
        sec = w.leaf_sector[w.rm.point_in_subsector(w.cmap, x16 >> 16, y16 >> 16)]
        if kind == "in" and sec not in hurt:
            continue
        if not _statics_clear(w, x16, y16):
            continue
        lt = rnd.choice((0, 32, 64, 96, 4096, 0xFFE0, 1, 16, 31, 33, rnd.randrange(1 << 16)))
        dead = int(rnd.random() < 0.05)
        hp = 0 if dead else rnd.choice((100, 50, 6, 5, 4, 1, rnd.randint(1, 200)))
        armor = rnd.choice((0, 0, 1, 3, 50))
        rec = {"pos": (x16, y16), "lt": lt, "hp": hp, "dead": dead, "armor": armor,
               "at": rnd.choice((1, 2)) if armor else 0, "dc": rnd.choice((0, 0, 98, 100, rnd.randint(0, 100))),
               "rng": rnd.randrange(256), "ready": rnd.choice(WC.WEAPONS),
               "doors": [rnd.choice((0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order],
               "lifts": [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]}
        out.append(rec)
    return out


def _apply(w, rec):
    ws = w.ws
    ws.px, ws.py = rec["pos"]
    ws.leveltime = rec["lt"]
    ws.p_health, ws.p_dead, ws.p_armor, ws.p_armortype = rec["hp"], rec["dead"], rec["armor"], rec["at"]
    ws.p_damagecount, ws.rng_player = rec["dc"], rec["rng"]
    ws.p_ready = rec["ready"]
    up = gd.WEAPONINFO[rec["ready"]].readystate
    ws.p_wpn_state, ws.p_wpn_tics, ws.p_wpn_sy = gd.STATE_INDEX[up], 1, WC.TOP
    for d, v in enumerate(rec["doors"]):
        ws.d_state[d] = v
    for k, v in enumerate(rec["lifts"]):
        ws.l_state[k] = v
    w._door_phase_scene()


def _row(ws, states, frames) -> str:
    idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(states)}
    vals = [ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_damagecount, ws.p_dead, ws.rng_player,
            idx[ws.p_wpn_state], ws.p_wpn_sy]
    return "".join("%0*x" % (n, v) for (_c, n), v in zip(CELLS, vals))


def _expected(records) -> bytes:
    w = _world()
    states, frames = WC.weapon_states(), WC.overlay_frames()
    lines = []
    for rec in records:
        _apply(w, rec)
        w._special_sector(TicEvents(0))
        lines.append(_row(w.ws, states, frames))
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "period16": (r"    hex\.if_flags lvtime \+ dw, 0xAAAA, nk_b, nk_out\n", ""),
    "nofloor": (r"    hex\.cmp 8, cp_floor, cp_seedf, nk_out, nk_hit, nk_out\n", ""),
    "sector": None,
    "dmg10": None,
}


def _program(w, mut=None):
    from doomfj.reference_model import ML_BLOCKING
    from doomfj.wall_renderer import DOOR_QUANT
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING, secs_open=kw["secs_open"],
                     door_line_ids=kw["door_line_ids"])
    obs = mover_line_openings(w.lds, w.sds, w.secs, kw["msecs"])
    movers = {li: (kw["mcell"][m_], obs[li]) for li in obs
              for m_ in [next(x for x in (w.sds[w.lds[li].front].sector, w.sds[w.lds[li].back].sector)
                              if x in kw["msecs"])]}
    lists, things = L.player_cell_things(w, cell_lists(rows, PLAYER_RADIUS))
    cells, root = collision_cells_fj("e1m1", rows, lists, doors=kw["doors"], movers=movers, things=things,
                                     thing_test=L.THING_TEST16)
    text = "\n".join(L.nukage_lines(w, root)) + "\n"
    if mut and MUTANTS[mut]:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    tables = L.tables_fj(w)
    vals = L.nkleaf_values(w)
    if mut == "sector":
        vals = [0 if w.leaf_sector[s] == 38 else v for s, v in enumerate(vals)]
    if mut == "dmg10":
        vals = [10 if v else 0 for v in vals]
    if mut in ("sector", "dmg10"):
        tables = [t if "ns nkleaf {" not in t else
                  generate_dispatch_table_fj("nkleaf", vals, index_nibbles=3, result_nibbles=2) for t in tables]
    ws = w.ws
    nd, nl = len(w.door_order), len(w.lift_order)
    states, frames = WC.weapon_states(), WC.overlay_frames()
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(WC.level_start(w.mw, "E1M1"), states, frames) + WC.weapon_const_decls()
             + COLLISION_STATE_DECLS + MON_CELL_DECLS + point_location_decls() + MM.monster_seed_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "lvtime: hex.vec 4",
                "bar_solid: hex.vec %d, %d" % (len(w.barrel_things),
                                                sum(ws.bar_solid[b] << (4 * b) for b in range(len(w.barrel_things)))),
                "mc_don: hex.vec %d, %d" % (max(1, len(MM.static_blockers(w)[1])),
                                             sum(v << (4 * k) for k, v in
                                                 enumerate(MM.decor_presence(w, MM.static_blockers(w)[1],
                                                                             gd.SK_HARD)))),
                "dstate: hex.vec %d" % nd, "lstate: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1"])
    rm = w.rm
    tables += H.tables_fj(half_width_table(rm.sine)) + [generate_point_location_fj(w.cmap)]
    return decls, text + "\n".join(H.dp_lines() + seed) + "\n" + cells, tables


def _build(tmp_path, name, mut=None):
    w = _world()
    records = _records(w)
    states, frames = WC.weapon_states(), WC.overlay_frames()
    idx = {s: i for i, s in enumerate(states)}
    body = ["stl.startup_and_init_all"]
    for rec in records:
        up = gd.WEAPONINFO[rec["ready"]].readystate
        body += ["hex.set 8, viewx, %d" % (rec["pos"][0] & M32), "hex.set 8, viewy, %d" % (rec["pos"][1] & M32),
                 "hex.set 4, lvtime, %d" % rec["lt"], "hex.set 3, p_hp, %d" % rec["hp"],
                 "hex.set 1, p_dead, %d" % rec["dead"], "hex.set 2, p_ar, %d" % rec["armor"],
                 "hex.set 1, p_at, %d" % rec["at"], "hex.set 2, p_dc, %d" % rec["dc"],
                 "hex.set 2, rng_pl, %d" % rec["rng"], "hex.set 1, wp_rdy, %d" % rec["ready"],
                 "hex.set 2, wp_st, %d" % idx[up], "hex.set 1, wp_tics, 1", "hex.set 2, wp_sy, %d" % WC.TOP,
                 "hex.set 1, wp_frm, %d" % frames.index(WC.psprite_lump(up))]
        body += ["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(rec["lifts"])]
        body += ["stl.fcall nk_go, nk_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, c) for c, n in CELLS] + ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(w, mut)
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


def test_the_records_exercise_every_path():
    """hits in each of the three sectors, kills, a dead player, ledges (in the sector, on the period, no hit), the
    off-period tics (16 among them), outside"""
    w = _world()
    seen = dict(hit=0, kill=0, deadrec=0, ledge=0, off=0, off16=0, out=0)
    secs = set()
    for rec in _records(w):
        _apply(w, rec)
        ev = TicEvents(0)
        w._special_sector(ev)
        sec = w.player_sector()
        inside = sec in (23, 38, 173)
        if ev.nukage:
            seen["hit"] += 1
            secs.add(sec)
        seen["kill"] += ev.deaths
        seen["deadrec"] += rec["dead"] and inside and not rec["lt"] & 31
        seen["ledge"] += inside and not rec["lt"] & 31 and not ev.nukage and not rec["dead"]
        seen["off"] += inside and bool(rec["lt"] & 31)
        seen["off16"] += inside and rec["lt"] & 31 == 16
        seen["out"] += not inside
    want = dict(hit=40, kill=3, deadrec=2, ledge=5, off=40, off16=5, out=30)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert secs == {23, 38, 173}, secs


def test_nukage_follows_the_model(tmp_path):
    assert _run(tmp_path, "nukage"), "the fj nukage parted from the model's _special_sector"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_broken_nukage_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "nukage_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
