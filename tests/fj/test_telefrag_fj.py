"""M8 (the owner, 2026-10-18): THE TELEFRAG on the real flipjump engine -- the player's WR teleport on E1M2 kills every
shootable monster at the destination (DOOM's P_TeleportMove: PIT_StompThing's P_DamageMobj(thing, player, player,
10000)). The very text the emitter splices -- teleportcode's player_lines (the walk's copy) and stomp leaf with its
`tp_frag`, damagecode's dm_go / dm_leaf in the TELEFRAG mode (the game tier's: full, blood, knock, fight, the kill
count, the drops), knockcode's kb_go / kb_gm / kb_th with the telefrag's kb_tf -- against the model's own
`combat._teleport_player` -> `damage_monster(slot, 10000, player, player)` -> `_thrust` / `_kill_monster`, on an
E1M2 World in the game tier's modes ("final" / "final").

Each record: a crossing of one of the four lines from its front (it always teleports), and up to four real monster
slots placed around that line's destination -- inside the blockdist, exactly at it (outside), far -- of every E1M2
type (the masses 100 and 400, the droppers, the types with and without an xdeath state), shootable or not, with a
random health, state, tics, stream, threshold, target, reaction, justhit, floorz, momentum (zero or not) and position
fraction; the player's ready weapon the pistol or the CHAINSAW (P_DamageMobj's exception: no thrust); the kill count
and the moving-slot count poked first. Printed after each: the drops linked (drop_link<k>, a stub that prints k: the
drop's own machinery is test_barrel_fj's), the teleport's two fogs (tf_spawn, a stub that prints each position: the
pool is test_fog_pool_fj's), the player's position, angle and reactiontime, st_kill, kb_live and every placed slot's
damage cells and momentum.

R9: the health subtracted (10000's three low nibbles) instead of held at the floor; the thrust with kb_dm's stale
damage (kb_tf ignored); the reversal tested (kb_tf's skip removed: a stale kb_dm < 40 draws); the telefrag through
the player's reach and blood (the TELEFRAG flag dropped from dm_leaf's first test).
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import barrelcode as BC
from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import knockcode as KC
from doomfj import monstercode as MC
from doomfj import teleportcode as T
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj, generate_trig_idioms_fj
from doomfj.monstercode import rnd_values
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wad import WadFile
from doomfj.wall_renderer import hoisted_scratch_fj
from doomfj.weaponcode import DM_CELLS
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
M32 = 0xFFFFFFFF
N_REC = 140
CELLS = (("mon_health", 3), ("mon_shootable", 1), ("mon_state", 2), ("mon_tics", 1), ("mon_rng", 2),
         ("mon_threshold", 2), ("mon_reaction", 1), ("mon_target", 2), ("mon_justhit", 1), ("mon_solid", 1))


def _world():
    return World(WadFile.from_path(FIX), "E1M2", skill=gd.SK_HARD, player="final", monsters="final")


def _records(w):
    rnd = random.Random(0x7E1E)
    n = w.layout.nmon
    by_type = {}
    for m in range(n):
        by_type.setdefault(w.mon_info[m].name, []).append(m)
    out = []
    for r in range(N_REC):
        k = rnd.randrange(len(w.teleports))
        tel = w.teleports[k]
        L = tel.coord << 16
        o = rnd.randint((tel.lo + 2) << 16, (tel.hi - 2) << 16)
        a, b = L - rnd.randint(1, 6 << 16), L + rnd.randint(1, 6 << 16)
        co, cn = (a, b) if tel.front_le else (b, a)
        old, new = ((co, o + rnd.randint(-3, 3) * 4096), (cn, o)) if tel.axis == "x" else ((o, co), (o, cn))
        slots, mons = set(), []
        for _ in range(rnd.choice((1, 1, 2, 3, 4))):
            m = rnd.choice(by_type[rnd.choice(sorted(by_type))])
            if m in slots:
                continue
            slots.add(m)
            info = w.mon_info[m]
            bd = w.mon_radius[m] + PLAYER_R
            off = rnd.choice((0, 1, bd - 1, bd - 1, bd, bd, bd + 1, rnd.randint(-bd + 1, bd - 1), 300))
            dx, dy = (off, rnd.randint(-bd + 1, bd - 1)) if rnd.random() < 0.5 else (rnd.randint(-bd + 1, bd - 1), off)
            dx, dy = dx * rnd.choice((1, -1)), dy * rnd.choice((1, -1))
            st = rnd.choice((info.spawnstate, info.seestate, info.painstate, gd.STATES[info.seestate].next))
            mons.append(dict(
                m=m, x=tel.dest[0] + dx, y=tel.dest[1] + dy, sh=int(rnd.random() < 0.88),
                hp=rnd.choice((1, info.spawnhealth, rnd.randint(1, info.spawnhealth))), st=gd.STATE_INDEX[st],
                ti=rnd.randint(1, 14), rng=rnd.randrange(256), th=rnd.choice((0, 0, rnd.randint(1, gd.BASETHRESHOLD))),
                re=rnd.randrange(16), tg=rnd.choice((0, 1, 2 + rnd.randrange(n))), jh=rnd.randrange(2),
                fz=rnd.randint(-100, 300), fx=rnd.choice((0, rnd.randrange(1 << 16))), fy=rnd.randrange(1 << 16),
                mom=rnd.choice(((0, 0), (0, 0), (rnd.randint(-(9 << 16), 9 << 16), rnd.randint(-(9 << 16), 9 << 16))))))
        out.append(dict(k=k, old=old, new=new, mons=sorted(mons, key=lambda d: d["m"]), ang=rnd.getrandbits(32),
                        saw=rnd.random() < 0.15, kills0=rnd.randrange(150), live0=rnd.randrange(4),
                        hp=rnd.randint(1, 200), rngp=rnd.randrange(256)))
    return out


def _signed32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _apply(w, rec):
    """the record into the model and its teleport -> (the lines the stubs print -- the drops linked, then the two
    fogs -- the row printed after)"""
    ws, n = w.ws, w.layout.nmon
    for m in range(n):
        ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 0
        ws.mon_momx[m] = ws.mon_momy[m] = 0
        ws.mon_drop[m] = 0
    for d in rec["mons"]:
        m = d["m"]
        ws.mon_active[m] = 1
        ws.mon_shootable[m] = ws.mon_solid[m] = d["sh"]
        ws.mon_x[m], ws.mon_y[m], ws.mon_health[m], ws.mon_state[m] = d["x"], d["y"], d["hp"], d["st"]
        ws.mon_tics[m], ws.mon_rng[m], ws.mon_threshold[m], ws.mon_reaction[m] = d["ti"], d["rng"], d["th"], d["re"]
        ws.mon_target[m], ws.mon_justhit[m], ws.mon_floorz[m] = d["tg"], d["jh"], d["fz"]
        ws.mon_fx[m], ws.mon_fy[m] = d["fx"], d["fy"]
        ws.mon_momx[m], ws.mon_momy[m] = d["mom"]
    ws.p_owned[gd.WP_CHAINSAW] = 1
    ws.p_ready = gd.WP_CHAINSAW if rec["saw"] else gd.WP_PISTOL
    ws.p_killcount, ws.p_health, ws.rng_player, ws.p_dead = rec["kills0"], rec["hp"], rec["rngp"], 0
    ws.p_reaction, ws.p_momx, ws.p_momy = 0, 0, 0
    ws.px, ws.py = _signed32(rec["new"][0]), _signed32(rec["new"][1])
    ws.pangle = rec["ang"]
    w._teleported = False
    fogs = []
    w._spawn_fx = lambda kind, x16, y16, dmg, melee, ev: fogs.append("F%04x%04x" % ((x16 >> 16) & 0xFFFF,
                                                                                   (y16 >> 16) & 0xFFFF))
    try:
        w._teleport_player(_signed32(rec["old"][0]), _signed32(rec["old"][1]), ws.px, ws.py)
    finally:
        del w._spawn_fx
    assert w._teleported and len(fogs) == 2
    drops = ["D%02x" % BC.droppers(w).index(d["m"]) for d in rec["mons"] if ws.mon_drop[d["m"]] == 1] + fogs
    live = sum(1 for m in range(n) if ws.mon_momx[m] or ws.mon_momy[m]) + rec["live0"]
    row = "%08x%08x%08x%02x%02x%02x" % (ws.px & M32, ws.py & M32, ws.pangle, ws.p_reaction, ws.p_killcount, live)
    for d in rec["mons"]:
        m = d["m"]
        row += "".join("%0*x" % (nib, getattr(ws, f)[m] & (16 ** nib - 1)) for f, nib in CELLS)
        row += "%08x%08x" % (ws.mon_momx[m] & M32, ws.mon_momy[m] & M32)
    return drops, row


def _expected(w, recs) -> bytes:
    lines = []
    for rec in recs:
        w.reset(gd.SK_HARD)
        stubs, row = _apply(w, rec)
        lines += stubs + [row]
    return ("\n".join(lines) + "\n").encode()


MUTANTS = {
    "health_subtracted": ("    hex.set 3, dm_hp, 2048\n", "    hex.add_constant 3, dm_hp, %d\n" % (-10000 & 0xFFF)),
    "thrust_stale_damage": ("    hex.if0 1, kb_tf, kq_ntf\n", "    ;kq_ntf\n"),
    "reversal_tested": ("    hex.if1 1, kb_tf, kq_nr\n", ""),
    "reach_and_blood": ("    hex.if_flags dm_melee, %d, dm_nbl, dm_chk\n"
                        % ((1 << DC.BLAST) | (1 << DC.MONSTER) | (1 << DC.TELEFRAG)),
                        "    hex.if_flags dm_melee, %d, dm_nbl, dm_chk\n" % ((1 << DC.BLAST) | (1 << DC.MONSTER))),
}


def _program(w, recs, mut=None):
    n, schema, ws = w.layout.nmon, w.schema, w.ws
    drops = {m: k for k, m in enumerate(BC.droppers(w))}
    dp = DC.damage_parts(w, slot_rt=list(range(n)), boot_skill=ws.skill, fx=True, full=True, nbar=0, drops=drops,
                         knock=True, fight=True, stats=True, telefrag=True)
    w.reset(gd.SK_HARD)
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n, w.sec_nibbles)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n, w.sec_nibbles)
             + MC.P32A_SCRATCH + dp["decls"] + KC.decls(n) + T.decls()
             + ["%s: hex.vec %d" % cn for cn in DM_CELLS]
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "thpos_rt: hex.vec %d" % (16 * n),
                "fxs_x: hex.vec 4", "fxs_y: hex.vec 4", "fxs_dmg: hex.vec 2", "fxs_kind: hex.vec 1",
                "fx_sret: hex.vec w/4", "st_kill: hex.vec 2", "p_hp: hex.vec 3", "rng_pl: hex.vec 2",
                "wp_rdy: hex.vec 1", "p_dead: hex.vec 1", "cm_ox: hex.vec 8", "cm_oy: hex.vec 8",
                "drl_ret: hex.vec w/4", "tpc_ret: hex.vec w/4"])
    kcode = "\n".join(KC.go_lines(KC.slots_of(w, list(range(n))), telefrag=True)) + "\n"
    a = kcode.index("kb_pz:\n")
    b = kcode.index("    stl.fret kb_pzret\n", a) + len("    stl.fret kb_pzret\n")
    kcode = kcode[:a] + "kb_pz:\n    stl.output 90\n    stl.fret kb_pzret\n" + kcode[b:]   # never reached: prints Z
    text = "\n".join(
        MC.dist_leaf_lines() + dp["lines"] + dp["tables"]
        + T.stomp_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], hurt=True, knock=True)
        + ["tpcall:"] + T.player_lines(w.teleports, prefix="tpw", knock_cells=True) + ["    stl.fret tpc_ret"]
        # the blood: never spawned by a telefrag (no blood) -- a stub that would print B
        + ["fx_spawn:", "    stl.output 66", "    stl.fret fx_sret"]
        # the fogs: each spawn's position (the pool is test_fog_pool_fj's)
        + ["tf_spawn:", "    stl.output 70", "    hex.print_as_digit 4, fxs_x, 0", "    hex.print_as_digit 4, fxs_y, 0",
           "    stl.output 10", "    stl.fret fx_sret"]
        + [line for k in sorted(drops.values())
           for line in ("drop_link%d:" % k, "    stl.output 68",
                        "    hex.print_as_digit 2, dr_k%d, 0" % k, "    stl.output 10", "    stl.fret drl_ret")]) + "\n"
    decls += ["dr_k%d: hex.vec 2, %d" % (k, k) for k in sorted(drops.values())]
    text += kcode
    if mut:
        old, new = MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    nib = {f: MC.cell_nibbles(schema, f) for f, _ in CELLS}
    assert all(nib[f] == k for f, k in CELLS), nib
    body = ["stl.startup_and_init_all"]
    for rec in recs:
        body += ["hex.zero %d, mon_shootable" % n]
        for d in rec["mons"]:
            m = d["m"]
            pokes = {"mon_health": d["hp"], "mon_shootable": d["sh"], "mon_state": d["st"], "mon_tics": d["ti"],
                     "mon_rng": d["rng"], "mon_threshold": d["th"], "mon_reaction": d["re"], "mon_target": d["tg"],
                     "mon_justhit": d["jh"], "mon_solid": d["sh"]}
            body += ["hex.set %d, %s + %d*dw, %d" % (nib[f], f, nib[f] * m, v & (16 ** nib[f] - 1))
                     for f, v in pokes.items()]
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, d["x"] & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, d["y"] & 0xFFFF),
                     "hex.set 4, mon_floorz + %d*dw, %d" % (4 * m, d["fz"] & 0xFFFF),
                     "hex.set 4, mfx + %d*dw, %d" % (4 * m, d["fx"]), "hex.set 4, mfy + %d*dw, %d" % (4 * m, d["fy"]),
                     "hex.set 8, mkx + %d*dw, %d" % (8 * m, d["mom"][0] & M32),
                     "hex.set 8, mky + %d*dw, %d" % (8 * m, d["mom"][1] & M32)]
        moving = sum(1 for d in rec["mons"] if d["mom"] != (0, 0))
        body += ["hex.set 1, wp_rdy, %d" % (gd.WP_CHAINSAW if rec["saw"] else gd.WP_PISTOL),
                 "hex.set 2, st_kill, %d" % rec["kills0"], "hex.set 2, kb_live, %d" % (moving + rec["live0"]),
                 "hex.set 3, p_hp, %d" % rec["hp"], "hex.set 2, rng_pl, %d" % rec["rngp"], "hex.zero 1, p_dead",
                 # a STALE dm_dmg (dm_leaf copies it to kb_dm) the reversal would take (< 40, above a low health):
                 # the telefrag must not read it
                 "hex.set 2, dm_dmg, 39",
                 "hex.zero 2, p_rct", "hex.zero 8, p_kmx", "hex.zero 8, p_kmy",
                 "hex.set 8, cm_ox, %d" % (rec["old"][0] & M32), "hex.set 8, cm_oy, %d" % (rec["old"][1] & M32),
                 "hex.set 8, viewx, %d" % (rec["new"][0] & M32), "hex.set 8, viewy, %d" % (rec["new"][1] & M32),
                 "hex.set 8, viewangle, %d" % rec["ang"],
                 "stl.fcall tpcall, tpc_ret",
                 "hex.print_as_digit 8, viewx, 0", "hex.print_as_digit 8, viewy, 0",
                 "hex.print_as_digit 8, viewangle, 0", "hex.print_as_digit 2, p_rct, 0",
                 "hex.print_as_digit 2, st_kill, 0", "hex.print_as_digit 2, kb_live, 0"]
        for d in rec["mons"]:
            m = d["m"]
            body += ["hex.print_as_digit %d, %s + %d*dw, 0" % (kk, f, kk * m) for f, kk in CELLS]
            body += ["hex.print_as_digit 8, mkx + %d*dw, 0" % (8 * m), "hex.print_as_digit 8, mky + %d*dw, 0" % (8 * m)]
            body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    tables = [generate_dispatch_table_fj("mrnd", rnd_values(), index_nibbles=2, result_nibbles=4),
              generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry"),
              generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
              generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
              generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    return "\n".join(body + decls + [text] + tables) + "\n" + hoisted_scratch_fj()


def _build(tmp_path, name, mut=None):
    w = _world()
    recs = _records(w)
    want = _expected(w, recs)
    prog = _program(w, recs, mut)
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, want


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """kills of every E1M2 type (the gib and the plain death), two or more at once, a monster exactly at the blockdist
    untouched, an unshootable one untouched, the saw (no thrust) and the pistol, drops, a victim already moving"""
    w = _world()
    seen = dict(gib=0, death=0, multi=0, edge=0, unshootable=0, saw_kill=0, kill=0, drop=0, moving_kill=0,
                heavy_kill=0)
    for rec in _records(w):
        w.reset(gd.SK_HARD)
        before = {d["m"]: dict(d) for d in rec["mons"]}
        drops, _row = _apply(w, rec)
        ws = w.ws
        killed = [m for m in before if before[m]["sh"] and not ws.mon_shootable[m]]
        seen["kill"] += len(killed)
        seen["multi"] += len(killed) >= 2
        seen["drop"] += sum(1 for line in drops if line[0] == "D")
        seen["saw_kill"] += bool(killed) and rec["saw"]
        for m in killed:
            name = gd.STATE_NAMES[ws.mon_state[m]]
            seen["gib" if "XDIE" in name else "death"] += 1
            seen["moving_kill"] += before[m]["mom"] != (0, 0)
            seen["heavy_kill"] += w.mon_info[m].mass == 400
        for m, d in before.items():
            bd = w.mon_radius[m] + PLAYER_R
            tel = w.teleports[rec["k"]]
            if d["sh"] and max(abs(d["x"] - tel.dest[0]), abs(d["y"] - tel.dest[1])) == bd:
                seen["edge"] += ws.mon_shootable[m] == 1
            seen["unshootable"] += not d["sh"] and abs(d["x"] - tel.dest[0]) < bd and abs(d["y"] - tel.dest[1]) < bd
    want = dict(gib=40, death=15, multi=15, edge=10, unshootable=5, saw_kill=5, kill=80, drop=10, moving_kill=10,
                heavy_kill=10)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_telefrag_follows_the_model(tmp_path):
    assert _run(tmp_path, "telefrag"), "the fj telefrag parted from the model's _teleport_player / damage_monster"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_a_broken_telefrag_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "telefrag_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
