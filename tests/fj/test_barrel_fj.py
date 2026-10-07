"""M7 P6 (doomfj.barrelcode, docs/gp-p67-interface.md 4.3): the BARRELS on the real flipjump engine -- the phase, the
blast (the player, the monster slots through damagecode's real slot stubs in BLAST mode, the static chain), the blast's
line of sight (monstersight's `bl_los`), damage_barrel, the player's shot on a barrel (damagecode's dm_go -> dmb<b>:
the reach, the PUFF through projcode's real fx_spawn, then the damage), the gib and the drops -- against the model's
`_line_attack`, `_barrels_phase` (-> `_barrel_set_state`, `_radius_attack`, `damage_monster`, `damage_barrel`,
`_kill_monster`) and `_fx_phase`, World(monsters="full", player="full").

Each record pokes, identically on both sides: the player near a barrel (alive or not, a random fraction), the doors,
lifts and the floor switch (the LOS's dynamic segments), one barrel's cells (around the damage that kills it, or a state
just before A_Explode), a few monster slots moved next to it with random cells (health around the blast's damage and
the gib bound); then either SHOOTS the barrel (bullets, the fist, the saw; damage up to the berserk fist's 200) or not,
then runs 0 .. 40 tics of `bar_phase` + `fx_phase` -- enough for a chain to go off and tick through. Some records take a
dropped item (drop_take). The point location is stubbed as in test_fx_pool_fj (its query printed, the model's leaf
read from stdin); dp_go is stubbed to print its damage (the model's damage_player logs the same).
After every record: every barrel's cells and bar_solid, rng_wd, every monster slot's damage cells, both fx slots,
rng_fx, mdrop / dr_live and the drop rows; every 6th record the leaf lists (the model's, plus the live drops at their
corpse's leaf and the two runtime barrels while not removed).

R9 (each must part): the player's Chebyshev on x alone, the LOS lists built with no margin, the pain draw dropped from a
non-lethal hit, no -128 saturation, the chain in reverse order, the gib branch dropped, the fist's puff as a plain puff,
no drop, the player's radius 20, and the tics roll dropped from the killing blow.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import barrelcode as BC
from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import monstersight as MS
from doomfj import projcode as PC
from doomfj.collision import point_location_decls
from doomfj.combat import MISSILERANGE_U, PUNCH_REACH, SAW_REACH, PLAYER_R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.weaponcode import DM_CELLS
from doomfj.world import FIREBALL_POOL, FX_POOL, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 150
LIST_EVERY = 6
M32 = 0xFFFFFFFF
CELLS = (("mon_health", 3), ("mon_shootable", 1), ("mon_state", 2), ("mon_tics", 1), ("mon_rng", 2),
         ("mon_threshold", 2), ("mon_reaction", 1), ("mon_target", 1), ("mon_justhit", 1), ("mon_active", 1))
RT_BARRELS = (15, 0)               # the harness's two runtime barrels (linked; removed -> unlinked)
NMOB = FIREBALL_POOL + FX_POOL


def _world():
    return World(monsters="full", sight_rule="seen", player="full")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _sidx(s):
    return gd.STATE_INDEX[s]


class Plan:
    """the records, drawn against a live model so a removed runtime barrel is never poked back and a dropped corpse
    is never revived (its drop row would be linked twice)"""

    def __init__(self, w):
        self.w = w
        self.rnd = random.Random(0xBA22E1)
        self.drop_k = {m: k for k, m in enumerate(BC.droppers(w))}

    def record(self):
        w, rnd, ws = self.w, self.rnd, self.w.ws
        nbar, n = len(w.barrel_things), w.layout.nmon
        live_rt = [b for b in RT_BARRELS if ws.bar_state[b]]
        cand = [b for b in range(nbar) if b not in RT_BARRELS] + live_rt
        b = rnd.choice(cand + [17, 18, 19] * 3)                  # the cluster 14..21 chains
        t = w.barrel_things[b]
        rec = {"b": b}
        dx, dy = rnd.randint(-150, 150), rnd.randint(-150, 150)
        if rnd.random() < 0.2:
            dx, dy = rnd.choice(((143, 0), (144, 0), (0, -143), (-144, 5), (16, 16), (0, 0), (17, 3)))
        rec["p"] = ((((t.x + dx) << 16) | rnd.choice((0, 0xFFFF, rnd.randrange(1 << 16)))) & M32,
                    (((t.y + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32)
        rec["pdead"] = int(rnd.random() < 0.08)
        rec["php"] = rnd.choice((100, 100, 50, 1, 0, -3))
        rec["doors"] = ([rnd.choice((0, w.door_nstates[si] - 1, rnd.randrange(w.door_nstates[si])))
                         for si in w.door_order] if rnd.random() < 0.3 else None)
        # the barrel: alive around the damage, or just before A_Explode, or (not a runtime one) removed
        k = rnd.random()
        sts = BC.barrel_states() + ([] if b in RT_BARRELS else [gd.S_NULL])
        if k < 0.45:
            st = rnd.choice(("S_BAR1", "S_BAR2"))
        elif k < 0.8:
            st = rnd.choice(("S_BEXP3", "S_BEXP3", "S_BEXP4", "S_BEXP2"))
        else:
            st = rnd.choice(sts)
        if st == gd.S_NULL:
            rec["bar"] = (0, 0, 0)
        else:
            rec["bar"] = (_sidx(st), rnd.randint(1, gd.STATES[st].tics),
                          rnd.choice((20, 20, 1, 5, 19, 0, -1, -128, rnd.randint(1, 20))))
        # the shot
        rec["shot"] = None
        if rnd.random() < 0.45:
            kind = rnd.choice(("bullet", "bullet", "fist", "saw"))
            dmg = rnd.choice((rnd.randint(1, 20), rnd.randint(1, 20), 5, 19, 20, 21, 148, 200, rnd.randint(20, 200)))
            rec["shot"] = (kind, dmg)
        # the monsters: a few moved next to the barrel, not a dropped corpse
        mons = {}
        free = [m for m in range(n) if ws.mon_drop[m] == 0]
        for _ in range(rnd.choice((0, 1, 2, 3, 4))):
            m = rnd.choice(free)
            info = w.mon_info[m]
            r = rnd.random()
            if r < 0.6:
                ox, oy = rnd.randint(-120, 120), rnd.randint(-120, 120)
            elif r < 0.8:                                          # on the edge of the blast
                e = 128 + w.mon_radius[m] + rnd.choice((-1, 0, 1))
                ox, oy = rnd.choice(((e, rnd.randint(-e, e)), (rnd.randint(-e, e), -e)))
            else:
                ox, oy = rnd.randint(-300, 300), rnd.randint(-300, 300)
            dmg_guess = rnd.randint(1, 128)
            hp = rnd.choice((dmg_guess, dmg_guess + 1, info.spawnhealth, rnd.randint(1, info.spawnhealth), 1, 0,
                             -2, 20, 60))
            stn = rnd.choice((info.spawnstate, info.spawnstate, info.seestate, info.painstate))
            mons[m] = {"xy": (t.x + ox, t.y + oy),
                       "mon_health": hp, "mon_shootable": int(rnd.random() < 0.9), "mon_state": _sidx(stn),
                       "mon_tics": rnd.randint(1, 14), "mon_rng": rnd.randrange(256),
                       "mon_threshold": rnd.choice((0, 0, 1, gd.BASETHRESHOLD)), "mon_reaction": rnd.randrange(16),
                       "mon_target": rnd.randrange(2), "mon_justhit": rnd.randrange(2),
                       "mon_active": int(rnd.random() < 0.95)}
        rec["mons"] = mons
        rec["tics"] = rnd.choice((0, 1, 2, 3, 8, 16, 25, 40))
        taken = [m for m in range(n) if ws.mon_drop[m] == 1]
        rec["take"] = rnd.choice(taken) if taken and rnd.random() < 0.15 else None
        return rec


def apply(w, rec, ev, hurt_log):
    ws = w.ws
    b = rec["b"]
    ws.px, ws.py = _s32(rec["p"][0]), _s32(rec["p"][1])
    ws.p_dead, ws.p_health = rec["pdead"], rec["php"]
    if rec["doors"] is not None:
        for d, v in enumerate(rec["doors"]):
            ws.d_state[d] = v
        w._mh_last = None
        w._door_phase_scene()
    ws.bar_state[b], ws.bar_tics[b], ws.bar_health[b] = rec["bar"]
    for m, pk in rec["mons"].items():
        ws.mon_x[m], ws.mon_y[m] = pk["xy"]
        for f, v in pk.items():
            if f != "xy":
                getattr(ws, f)[m] = v
    if rec["take"] is not None:
        ws.mon_drop[rec["take"]] = 2
    if rec["shot"]:
        kind, dmg = rec["shot"]
        w.aim = lambda world, col, _b=b: ("bar", _b)
        weapon = {"bullet": "pistol", "fist": "fist", "saw": "chainsaw"}[kind]
        reach = {"bullet": MISSILERANGE_U, "fist": PUNCH_REACH, "saw": SAW_REACH}[kind]
        w._line_attack(weapon, w.aim_centre, dmg, reach, ev)
    for _ in range(rec["tics"]):
        w._barrels_phase(ev)
        w._fx_phase(ev)


def _row(w, drop_pos):
    ws = w.ws
    s = "".join("%02x%x%02x%x" % (ws.bar_state[b], ws.bar_tics[b], ws.bar_health[b] & 0xFF, ws.bar_solid[b])
                for b in range(len(w.barrel_things)))
    s += "%02x" % ws.rng_world
    for m in range(w.layout.nmon):
        s += "".join("%0*x" % (nib, getattr(ws, f)[m] & (16 ** nib - 1)) for f, nib in CELLS)
    for k in range(FX_POOL):
        s += "%x%08x%08x%02x%x" % (ws.fx_active[k], ws.fx_x[k] & M32, ws.fx_y[k] & M32, ws.fx_state[k],
                                   ws.fx_tics[k])
    s += "%02x" % ws.rng_fx
    drops = BC.droppers(w)
    s += "".join("%x" % ws.mon_drop[m] for m in drops)
    s += "%02x" % sum(1 for m in drops if ws.mon_drop[m] == 1)
    for k, m in enumerate(drops):
        if ws.mon_drop[m] == 1:
            x, y = drop_pos[k]
            s += "%08x%08x%03x" % ((y << 16) & M32, (x << 16) & M32, ws.mon_leaf[m])
        else:
            s += "0" * 19
    return s


def _lists(w, nt, rt_leaf):
    """the model's leaf lists (mobiles), plus the live drops at their corpse's leaf, plus the runtime barrels"""
    ws = w.ws
    lists = {leaf: list(ks) for leaf, ks in w.leaf_lists().items()}
    for k, m in enumerate(BC.droppers(w)):
        if ws.mon_drop[m] == 1:
            lists.setdefault(ws.mon_leaf[m], []).append(nt + NMOB + k)
    for b, (t, leaf) in rt_leaf.items():
        if ws.bar_state[b]:
            lists.setdefault(leaf, []).append(t)
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in sorted(ks)))
                   for leaf, ks in sorted(lists.items()) if ks)


def _model(records, nt, rt_leaf):
    w = _world()
    log, feed = [], []
    orig = w._leaf16

    def leaf16(x16, y16):
        leaf = orig(x16, y16)
        log.append("p%010x%010x" % ((x16 >> 16) & 0xFFFFFFFFFF, (y16 >> 16) & 0xFFFFFFFFFF))
        feed.append(struct.pack("<H", leaf))
        return leaf
    w._leaf16 = leaf16

    def hurt(dmg, source, inflictor, ev):
        log.append("h%02x" % dmg)
    w.damage_player = hurt
    drops = BC.droppers(w)
    drop_pos = {}
    lines = []
    for r, rec in enumerate(records):
        before = [w.ws.mon_drop[m] for m in drops]
        apply(w, rec, TicEvents(0), log)
        for k, m in enumerate(drops):
            if before[k] == 0 and w.ws.mon_drop[m] == 1:
                drop_pos[k] = (w.ws.mon_x[m], w.ws.mon_y[m])
        lines.append("".join(log) + _row(w, drop_pos))
        log.clear()
        if r % LIST_EVERY == LIST_EVERY - 1:
            lines.append(_lists(w, nt, rt_leaf))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed), w


def make_records(n=N):
    w = _world()
    w.damage_player = lambda dmg, source, inflictor, ev: None
    plan = Plan(w)
    out = []
    for _ in range(n):
        rec = plan.record()
        out.append(rec)
        apply(w, rec, TicEvents(0), [])
    return out


MUTANTS = ("cheb_x", "los_margin", "pain_draw", "no_sat", "chain_rev", "no_gib", "fist_puff", "no_drop", "radius20",
           "no_tics_roll")


def _mutate(text, mut):
    def sub(old, new):
        assert text.count(old) == 1, (mut, old, text.count(old))
        return text.replace(old, new)
    if mut == "cheb_x":
        return sub("    hex.cmp 8, bl_ax, bl_ay, bl_pyb, bl_pxb, bl_pxb\n", "    ;bl_pxb\n")
    if mut == "pain_draw":
        text = sub("    hex.inc 2, rng_wd\n    hex.sign 3, bw_t, bd_kill, bd_zp\n",
                   "    hex.sign 3, bw_t, bd_kill, bd_zp\n")
        return sub("  bd_kill:\n", "  bd_kill:\n    hex.inc 2, rng_wd\n")
    if mut == "no_sat":
        return sub("    hex.mov 3, bw_t, bw_m128\n", "")
    if mut == "no_gib":
        return sub("    hex.scmp 3, dm_hp, dm_nsh, dm_gib, dm_ngib, dm_ngib\n", "    ;dm_ngib\n")
    if mut == "fist_puff":
        return sub("    hex.set 1, fxs_kind, 2\n", "    hex.set 1, fxs_kind, 1\n")
    if mut == "no_drop":                          # the kill never raises the drop's flag
        return sub("    hex.set 1, dm_kd, 1\n", "")
    if mut == "radius20":
        return sub("    hex.set 2, bl_r, %d\n" % PLAYER_R, "    hex.set 2, bl_r, 20\n")
    if mut == "no_tics_roll":
        return sub("    hex.sub 1, bw_ti, bw_rr + 2*dw\n", "")
    return text


def _barrel_lines(w, nt, slot_rt, barrel_rt, mut):
    from doomfj.combat import PLAYER_R as PR
    chains = BC.chain_pairs(w)
    if mut == "chain_rev":
        chains = {b: list(reversed(v)) for b, v in chains.items()}
    spots = [(t.x, t.y) for t in w.barrel_things]
    maxr = max([PR] + list(w.mon_radius[:w.layout.nmon]))
    lists = None
    if mut == "los_margin":
        lists = MS.spot_lists(MS.sight_segments(w), spots, 0)
    return (BC.phase_lines(w, barrel_rt=barrel_rt, chains=chains) + BC.damage_lines(len(spots))
            + BC.blast_lines(w, slot_rt=slot_rt) + MS.blast_los_lines(w, spots, maxr, lists=lists)
            + BC.shot_lines(w) + BC.drop_lines(w, nt=nt, slot_rt=slot_rt))


def _build(tmp_path, name, records, mut=None):
    w = _world()
    n, nleaf, schema, ws = w.layout.nmon, len(w.cmap.subsectors), w.schema, w.ws
    nt = n
    nd = len(BC.droppers(w))
    nthings = nt + NMOB + nd + len(RT_BARRELS)
    barrel_rt = {b: nt + NMOB + nd + i for i, b in enumerate(RT_BARRELS)}
    rt_leaf = {b: (t, w.rm.point_in_subsector(w.cmap, w.barrel_things[b].x, w.barrel_things[b].y))
               for b, t in barrel_rt.items()}
    want, feed, _mw = _model(records, nt, rt_leaf)
    slot_rt = list(range(n))
    bp = BC.barrel_parts(w, nt=nt, slot_rt=slot_rt, boot_skill=ws.skill, barrel_rt=barrel_rt)
    dp = DC.damage_parts(w, slot_rt=slot_rt, boot_skill=ws.skill, fx=True, full=True, nbar=bp["nbar"],
                         drops=bp["drops"])
    segs = MS.sight_segments(w)
    sight = [ln for k, s in enumerate(segs) for ln in MS._seg_block(k, s)] + MS.seg_test_lines()
    code = "\n".join(MC.dist_leaf_lines() + dp["lines"] + MD.octant_leaf_lines()
                     + PC.fx_lines(nt=nt, puffs=True) + PC.pool_tic_lines()
                     + _barrel_lines(w, nt, slot_rt, barrel_rt, mut) + sight) + "\n"
    code = _mutate(code, mut)
    # the leaf lists: the model's mobiles, plus the runtime barrels
    head, nxt = [0] * nleaf, [0] * nthings
    lists = {leaf: list(ks) for leaf, ks in w.leaf_lists().items()}
    for b, (t, leaf) in rt_leaf.items():
        lists.setdefault(leaf, []).append(t)
    for leaf, ks in lists.items():
        ks = sorted(ks)
        head[leaf] = ks[0] + 1
        for a, c in zip(ks, ks[1:] + [-1]):
            nxt[a] = c + 1
    nib = {f: MC.cell_nibbles(schema, f) for f, _ in CELLS}
    assert all(nib[f] == k for f, k in CELLS), nib
    nbar = len(w.barrel_things)
    drop_k = {m: k for k, m in enumerate(BC.droppers(w))}
    body = ["stl.startup_and_init_all"]
    for r, rec in enumerate(records):
        b = rec["b"]
        body += ["hex.set 8, viewx, %d" % rec["p"][0], "hex.set 8, viewy, %d" % rec["p"][1],
                 "hex.set 1, p_dead, %d" % rec["pdead"], "hex.set 3, p_hp, %d" % (rec["php"] & 0xFFF)]
        if rec["doors"] is not None:
            body += ["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
        st, ti, hp = rec["bar"]
        body += ["hex.set 2, bar_st + %d*dw, %d" % (2 * b, st), "hex.set 1, bar_ti + %d*dw, %d" % (b, ti),
                 "hex.set 2, bar_hp + %d*dw, %d" % (2 * b, hp & 0xFF)]
        for m, pk in rec["mons"].items():
            x, y = pk["xy"]
            # a MUTANT's fj may have killed (and dropped) a slot the model did not: reviving it would link its drop
            # row twice -- a cycle, and the run never ends. The faithful run never takes this skip (the plan pokes
            # only slots whose model mon_drop is 0, and then mdrop is 0 too).
            guard = drop_k.get(m)
            if guard is not None:
                body += ["hex.if1 1, mdrop + %d*dw, rp%d_%d" % (guard, r, m)]
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, y & 0xFFFF)]
            body += ["hex.set %d, %s + %d*dw, %d" % (nib[f], f, nib[f] * m, v & (16 ** nib[f] - 1))
                     for f, v in pk.items() if f != "xy"]
            if guard is not None:
                body += ["rp%d_%d:" % (r, m)]
        if rec["take"] is not None:
            body += ["stl.fcall drop_take%d, drt_ret" % BC.droppers(w).index(rec["take"])]
        if rec["shot"]:
            kind, dmg = rec["shot"]
            body += ["hex.set 2, dm_id, %d" % (1 + n + b), "hex.set 2, dm_dmg, %d" % dmg,
                     "hex.set 1, dm_melee, %d" % int(kind != "bullet"),
                     "hex.set 2, dm_reach, %d" % {"bullet": 0x33, "fist": PUNCH_REACH, "saw": SAW_REACH}[kind],
                     "stl.fcall dm_go, dm_ret"]
        body += ["stl.fcall bar_phase, bar_pret", "stl.fcall fx_phase, fx_pret"] * rec["tics"]
        body += ["stl.fcall rec_dump, dump_ret"]
        if r % LIST_EVERY == LIST_EVERY - 1:
            body += ["stl.fcall ll_dump, dump_ret"]
    body += ["stl.loop"]
    dump = ["rec_dump:"]
    for b in range(nbar):
        dump += ["    hex.print_as_digit 2, bar_st + %d*dw, 0" % (2 * b), "    hex.print_as_digit 1, bar_ti + %d*dw, 0" % b,
                 "    hex.print_as_digit 2, bar_hp + %d*dw, 0" % (2 * b),
                 "    hex.print_as_digit 1, bar_solid + %d*dw, 0" % b]
    dump += ["    hex.print_as_digit 2, rng_wd, 0"]
    for m in range(n):
        dump += ["    hex.print_as_digit %d, %s + %d*dw, 0" % (k, f, k * m) for f, k in CELLS]
    for s in range(FX_POOL):
        dump += ["    hex.print_as_digit 1, fx_act + %d*dw, 0" % s,
                 "    hex.print_as_digit 8, fx_x + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, fx_y + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 2, fx_st + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 1, fx_ti + %d*dw, 0" % s]
    dump += ["    hex.print_as_digit 2, rng_fx, 0"]
    dump += ["    hex.print_as_digit 1, mdrop + %d*dw, 0" % k for k in range(nd)]
    dump += ["    hex.print_as_digit 2, dr_live, 0"]
    for k in range(nd):
        t = nt + NMOB + k
        dump += ["    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    stl.output 10", "    stl.fret dump_ret"]
    stubs = ["ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0",
             "    hex.print_as_digit 10, pty, 0", "    hex.zero w/4, ptss", "    hex.input 2, ptss",
             "    stl.fret ptloc_ret",
             "dp_go:", "    stl.output 104", "    hex.print_as_digit 2, dp_dmg, 0", "    stl.fret dp_ret"]
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    rows = sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32) << 32) << (64 * m) for m in range(n))
    for b, (t, leaf) in rt_leaf.items():
        tb = w.barrel_things[b]
        rows |= ((tb.x << 16) & M32 | ((tb.y << 16) & M32) << 32) << (64 * t)
    ss = sum(ws.mon_leaf[m] << (64 * m) for m in range(n)) | sum(leaf << (64 * t) for t, leaf in rt_leaf.values())
    nd_ = len(w.door_order)
    nl = len(w.lift_order)
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n)
             + MC.P32A_SCRATCH + dp["decls"] + MD.context_decls() + PC.pool_decls(puffs=True)
             + point_location_decls() + LEAF_LINK_DECLS + bp["decls"] + MS.SL_DECLS
             + ["%s: hex.vec %d" % cn for cn in DM_CELLS]
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "lvdone: hex.vec 1", "p_dead: hex.vec 1",
                "p_hp: hex.vec 3", "dp_dmg: hex.vec 2", "dp_ret: hex.vec w/4",
                "bar_solid: hex.vec %d, %d" % (nbar, sum(1 << (4 * b) for b in range(nbar))),
                "dstate: hex.vec %d, %d" % (nd_, sum(v << (4 * d) for d, v in enumerate(ws.d_state[:nd_]))),
                "lstate: hex.vec %d, %d" % (max(1, nl), sum(v << (4 * d) for d, v in enumerate(ws.l_state[:nl]))),
                "fswitch: hex.vec 1, %d" % ws.f_switch,
                "dump_ret: hex.vec w/4", "dl_i: hex.vec w/4", "dl_n: hex.vec w/4",
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, rows),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, ss),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    prog = "\n".join(body + decls + dump + leaf_dump_lines(nleaf) + stubs + [code] + dp["tables"]
                     + PC.tables_fj(puffs=True) + bp["tables"]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, feed, want


def leaf_dump_lines(nleaf: int) -> list:
    """test_fx_pool_fj's ll_dump (copied: a test module is not imported): every leaf with a list, "lll:" then its
    runtime things"""
    return ["ll_dump:",
            "    hex.zero w/4, dl_i",
            "  dl_next:",
            "    hex.set w/4, ll_base, sshead",
            "    hex.ptr_index ll_p, ll_base, dl_i", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end",
            "    hex.print_as_digit 3, dl_i, 0", "    stl.output 58",
            "  dl_loop:",
            "    hex.dec 2, ll_v", "    hex.print_as_digit 2, ll_v, 0",
            "    hex.set w/4, ll_base, thnext", "    hex.zero w/4, ll_idx", "    hex.mov 2, ll_idx, ll_v",
            "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
            "    hex.if0 2, ll_v, dl_end", "    stl.output 44", "    ;dl_loop",
            "  dl_end:",
            "    hex.inc w/4, dl_i",
            "    hex.set w/4, dl_n, %d" % nleaf,
            "    hex.cmp w/4, dl_i, dl_n, dl_next, dl_done, dl_done",
            "  dl_done:",
            "    stl.output 10", "    stl.fret dump_ret"]


@pytest.fixture(scope="module")
def records():
    return make_records()


def _run(tmp_path, name, records, mut=None) -> bool:
    srcs, feed, want = _build(tmp_path, name, records, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path(records):
    """the model's own events over the records: shots that kill and that do not, puffs (and the fist's), a full fx
    pool skipping a puff, blasts, a CHAIN (a barrel a blast killed exploding in turn), the player hurt by a blast,
    monsters hurt / killed / gibbed by a blast, drops made and taken, a runtime barrel removed, the -128 saturation"""
    from doomfj.combat import BARREL_HEALTH_MIN
    w = _world()
    seen = dict(shot_kill=0, shot_hurt=0, puff=0, fistpuff=0, skipped=0, blasts=0, chain_kill=0, chain_blast=0,
                p_hurt=0, m_hit=0, m_kill=0, gib=0, drops=0, taken=0, rt_removed=0, sat=0)
    hurt = []
    w.damage_player = lambda dmg, src, inflictor, ev: hurt.append(dmg)
    blast_killed = set()
    for rec in records:
        ev = TicEvents(0)
        nb = len(hurt)
        sat0 = sum(1 for v in w.ws.bar_health if v == BARREL_HEALTH_MIN)
        apply(w, rec, ev, [])
        seen["p_hurt"] += len(hurt) - nb
        for k in ev.kills:
            if k[0] == "bar" and k[1] != rec["b"]:
                seen["chain_kill"] += 1
                blast_killed.add(k[1])
            if k[0] == "mon":
                seen["m_kill"] += 1
                seen["gib"] += k[2] == "gib"
                seen["drops"] += w.dropper[k[1]] is not None
        for blast in ev.barrel_blasts:
            seen["blasts"] += 1
            seen["chain_blast"] += blast in blast_killed
        seen["m_hit"] += sum(1 for h in ev.hits if h[0] == "barrel" and h[1] == "mon")
        for _slot, kind in ev.fx_spawns:
            seen["puff"] += kind == "puff"
            seen["fistpuff"] += kind == "puff" and rec["shot"][0] == "fist"
        seen["skipped"] += ev.fx_skipped
        if rec["shot"]:
            seen["shot_kill" if ("bar", rec["b"], "death") in ev.kills else "shot_hurt"] += 1
        seen["taken"] += rec["take"] is not None
        seen["sat"] += sum(1 for v in w.ws.bar_health if v == BARREL_HEALTH_MIN) > sat0
    seen["rt_removed"] = sum(1 for b in RT_BARRELS if not w.ws.bar_state[b])
    want = dict(shot_kill=10, shot_hurt=10, puff=20, fistpuff=3, skipped=2, blasts=20, chain_kill=10, chain_blast=5,
                p_hurt=5, m_hit=10, m_kill=5, gib=2, drops=2, taken=1, rt_removed=1, sat=2)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_barrels_follow_the_model(tmp_path, records):
    assert _run(tmp_path, "barrels", records), "the fj barrels parted from the model's"


@pytest.mark.parametrize("mut", MUTANTS)
def test_control_a_broken_barrel_is_caught(tmp_path, records, mut):
    assert not _run(tmp_path, "barrels_" + mut, records, mut=mut), "%s passed: the comparison is vacuous" % mut


# ---- M7 P8a I (docs/gp-final-plan.md 1.2.2, G-I7; barrelcode `fight`): THE BLAST'S SOURCE -------------------------
# barrelcode's fight emission -- bar_phase / bar_next, bdm<c> / bd_leaf (bar_src: the source of the first damage that
# did NOT kill the barrel), bl_leaf (the blast's source on the player's dp_src and on each slot's dm_src), the static
# chain (bd_src = the exploding barrel's bar_src), dmb<b> / dmb_leaf (a player's shot, a monster's bullet -- the puff,
# no reach -- or its fireball -- no puff) -- with the damage stubs printing each call (dp_go: damage, source; each
# slot stub dmg<m>: the damage, mode and source) and the blast's LOS a poke (bl_los returns the record's sl_hit; the
# model's los_points its negation), against the model's `_barrels_phase` (-> `_radius_attack`, `damage_barrel`) and
# `damage_barrel` / `_line_attack`, World(monsters="final", player="final"). Each record pokes one barrel about to
# explode (or standing), its bar_src, a few monsters beside it, the player, and maybe a hit on it first (its mode and
# source); then one tic of bar_phase. After each record: every barrel's state, health and bar_src, and rng_wd.
# R9: bar_src recorded as the player whatever the source; recorded on the killing blow too; overwritten by every hit
# (not the first); the blast's monsters told the player; the player's attacker never named; the chain's source lost.
FN = 260


def _fworld():
    return World(monsters="final", sight_rule="seen", player="final")


def _frecords(w):
    rnd = random.Random(0xBA5C)
    n, nbar = w.layout.nmon, len(w.barrel_things)
    out = []
    for r in range(FN):
        b = rnd.choice(list(range(nbar)) + [17, 18, 19] * 3)
        t = w.barrel_things[b]
        st = rnd.choice(("S_BAR1", "S_BEXP3", "S_BEXP3", "S_BAR2"))
        bar = (_sidx(st), 1 if st == "S_BEXP3" else rnd.randint(1, gd.STATES[st].tics),
               rnd.choice((20, 20, 5, 1, 0)) if st.startswith("S_BAR") else 0)
        srcs = [0, 1] + [2 + rnd.randrange(n) for _ in range(3)]
        bsrc = rnd.choice(srcs)
        others = {c: rnd.choice(srcs) for c in range(nbar)}                # every barrel's bar_src
        hit = None
        if rnd.random() < 0.5:
            mode = rnd.choice((0, 3, 4, 4))
            hit = (mode, rnd.choice((1, 4, 15, 19, 20, 24)), rnd.choice(srcs[2:]) if mode else 0)
            if rnd.random() < 0.6:
                bsrc = 0                                                    # the hit is the first to name one
        mons = {}
        for _ in range(rnd.choice((0, 1, 2, 3))):
            m = rnd.randrange(n)
            mons[m] = (t.x + rnd.randint(-120, 120), t.y + rnd.randint(-120, 120), int(rnd.random() < 0.85))
        pl = ((((t.x + rnd.randint(-140, 140)) << 16) | rnd.randrange(1 << 16)) & M32,
              (((t.y + rnd.randint(-140, 140)) << 16) | rnd.randrange(1 << 16)) & M32, int(rnd.random() < 0.15))
        out.append(dict(b=b, bar=bar, bsrc=bsrc, others=others, hit=hit, mons=mons, pl=pl,
                        los=int(rnd.random() < 0.8), rng=rnd.randrange(256)))
    return out


def _fsrc(code):
    return None if not code else ("player", -1) if code == 1 else ("mon", code - 2)


def _fapply(w, rec, log):
    ws, n, nbar = w.ws, w.layout.nmon, len(w.barrel_things)
    for c in range(nbar):                                   # the rest standing, out of the way of nothing
        ws.bar_state[c], ws.bar_tics[c], ws.bar_health[c], ws.bar_solid[c] = _sidx("S_BAR1"), 5, 20, 1
        ws.bar_src[c] = rec["others"][c]
    b = rec["b"]
    ws.bar_state[b], ws.bar_tics[b], ws.bar_health[b] = rec["bar"]
    ws.bar_src[b] = rec["bsrc"]
    for m in range(n):
        ws.mon_active[m], ws.mon_shootable[m], ws.mon_health[m] = 0, 0, 0
    for m, (x, y, alive) in rec["mons"].items():
        ws.mon_active[m], ws.mon_shootable[m], ws.mon_health[m] = 1, alive, 60 if alive else 0
        ws.mon_x[m], ws.mon_y[m] = x, y
    ws.px, ws.py, ws.p_dead = _s32(rec["pl"][0]), _s32(rec["pl"][1]), rec["pl"][2]
    ws.p_health = 0 if ws.p_dead else 100
    ws.rng_world = rec["rng"]
    spots = {(t.x << 16, t.y << 16) for t in w.barrel_things}     # the chain's pairs: statically clear (the fj's)
    w.los_points = lambda p, q, _l=rec["los"]: True if p in spots else bool(_l)
    w.damage_player = lambda dmg, source, inflictor, ev: log.append(
        "P%02x%02x" % (dmg, source[1] + 1 if source[0] == "mon" else 0))
    mode = {"v": 2}
    w.damage_monster = lambda m, dmg, source, inflictor, ev: log.append(
        "M%02x%02x%x%02x" % (m, dmg, mode["v"], w._source_code(source)))
    w._spawn_fx_at_target = lambda kind, x, y, dmg, melee, ev: log.append("F%x" % (kind == "puff"))
    ev = TicEvents(0)
    if rec["hit"]:
        md, dmg, src = rec["hit"]
        t = w.barrel_things[b]
        if md == 0:                                         # the player's bullet, from within its reach
            ws.px, ws.py = (t.x + 30) << 16, t.y << 16
            w.aim = lambda world, col, _b=b: ("bar", _b)
            w._line_attack("pistol", w.aim_centre, dmg, MISSILERANGE_U, ev)
        else:
            if md == 4:
                w._spawn_fx_at_target("puff", t.x, t.y, dmg, False, ev)
            w.damage_barrel(b, dmg, _fsrc(src), ev)
        ws.px, ws.py = _s32(rec["pl"][0]), _s32(rec["pl"][1])
    w._barrels_phase(ev)


def _fexpected(w, records) -> bytes:
    lines = []
    for rec in records:
        log = []
        _fapply(w, rec, log)
        ws = w.ws
        lines += log + ["".join("%02x%02x%02x" % (ws.bar_state[c], ws.bar_health[c] & 0xFF, ws.bar_src[c])
                                for c in range(len(w.barrel_things))) + "%02x" % ws.rng_world]
    return ("\n".join(lines) + "\n").encode()


FIGHT_MUTANTS = {
    "bar_src_player": ("    hex.mov 2, bw_sr, bd_src\n", "    hex.set 2, bw_sr, 1\n"),
    "bar_src_any": ("    hex.if1 2, bw_sr, bd_out\n", ""),
    "blast_player": ("    hex.mov 2, dm_src, bl_src\n", "    hex.set 2, dm_src, 1\n"),
    "no_attacker": ("  bl_pss:\n    hex.mov 2, dp_src, bl_src\n    hex.dec 2, dp_src\n", "  bl_pss:\n"),
    "chain_lost": None,
    "lethal_src": None,
}


def _fbuild(tmp_path, name, mut=None):
    w = _fworld()
    n, nbar = w.layout.nmon, len(w.barrel_things)
    records = _frecords(w)
    want = _fexpected(w, records)
    slot_rt = list(range(n))
    text = "\n".join(BC.phase_lines(w, fight=True) + BC.damage_lines(nbar, fight=True)
                     + BC.blast_lines(w, slot_rt=slot_rt, fight=True) + BC.shot_lines(w, fight=True)
                     + MC.dist_leaf_lines()) + "\n"
    if mut == "chain_lost":
        assert "    hex.mov 2, bd_src, bar_src + " in text
        text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("    hex.mov 2, bd_src, bar_src + ")) + "\n"
    elif mut == "lethal_src":                    # the source recorded before the kill test
        old = "    hex.inc 2, rng_wd\n"
        assert text.count(old) == 1
        text = text.replace(old, old + "    hex.if1 2, bw_sr, bd_lx\n    hex.mov 2, bw_sr, bd_src\n  bd_lx:\n")
    elif mut:
        old, new = FIGHT_MUTANTS[mut]
        assert text.count(old) == 1, (mut, text.count(old))
        text = text.replace(old, new)
    stubs = ["bl_los:", "    hex.mov 1, sl_hit, los_poke", "    hex.xor_by sl_hit, 1", "    stl.fret bl_lret",
             "dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
             "    stl.output 10", "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "fx_spawn:", "    stl.output 70", "    hex.print_as_digit 1, fxs_kind, 0", "    stl.output 10",
             "    stl.fret fx_sret"]
    for m in range(n):
        stubs += ["dmg%d:" % m, "    stl.output 77", "    hex.set 2, pr_m, %d" % m, "    hex.print_as_digit 2, pr_m, 0",
                  "    hex.print_as_digit 2, dm_dmg, 0", "    hex.print_as_digit 1, dm_melee, 0",
                  "    hex.print_as_digit 2, dm_src, 0", "    stl.output 10", "    hex.zero 2, dm_src",
                  "    stl.fret dm_ret"]
    body = ["stl.startup_and_init_all"]
    for k, rec in enumerate(records):
        b = rec["b"]
        for c in range(nbar):
            st, ti, hp, src = ((_sidx("S_BAR1"), 5, 20, rec["others"][c]) if c != b
                               else rec["bar"] + (rec["bsrc"],))
            body += ["hex.set 2, bar_st + %d*dw, %d" % (2 * c, st), "hex.set 1, bar_ti + %d*dw, %d" % (c, ti),
                     "hex.set 2, bar_hp + %d*dw, %d" % (2 * c, hp & 0xFF), "hex.set 2, bar_src + %d*dw, %d" % (2 * c, src),
                     "hex.set 1, bar_solid + %d*dw, 1" % c]
        body += ["hex.zero %d, mon_active" % n, "hex.zero %d, mon_shootable" % n, "hex.zero %d, mon_health" % (3 * n)]
        for m, (x, y, alive) in sorted(rec["mons"].items()):
            body += ["hex.set 1, mon_active + %d*dw, 1" % m, "hex.set 1, mon_shootable + %d*dw, %d" % (m, alive),
                     "hex.set 3, mon_health + %d*dw, %d" % (3 * m, 60 if alive else 0),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, y & 0xFFFF)]
        body += ["hex.set 1, p_dead, %d" % rec["pl"][2], "hex.set 3, p_hp, %d" % (0 if rec["pl"][2] else 100),
                 "hex.set 2, rng_wd, %d" % rec["rng"], "hex.set 1, los_poke, %d" % rec["los"]]
        if rec["hit"]:
            md, dmg, src = rec["hit"]
            t = w.barrel_things[b]
            px = ((t.x + 30) << 16) & M32 if md == 0 else rec["pl"][0]
            py = (t.y << 16) & M32 if md == 0 else rec["pl"][1]
            body += ["hex.set 8, viewx, %d" % px, "hex.set 8, viewy, %d" % py,
                     "hex.set 1, dm_melee, %d" % md, "hex.set 2, dm_dmg, %d" % dmg, "hex.set 2, dm_src, %d" % src,
                     "stl.fcall dmb%d, dm_ret" % b]
        body += ["hex.set 8, viewx, %d" % rec["pl"][0], "hex.set 8, viewy, %d" % rec["pl"][1],
                 "stl.fcall bar_phase, bar_pret"]
        for c in range(nbar):
            body += ["hex.print_as_digit 2, bar_st + %d*dw, 0" % (2 * c), "hex.print_as_digit 2, bar_hp + %d*dw, 0" % (2 * c),
                     "hex.print_as_digit 2, bar_src + %d*dw, 0" % (2 * c)]
        body += ["hex.print_as_digit 2, rng_wd, 0", "stl.output 10"]
    body += ["stl.loop"]
    decls = (BC.decls(w, gd.SK_HARD) + BC.fight_decls(w)
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "p_dead: hex.vec 1", "lvdone: hex.vec 1",
                "dp_dmg: hex.vec 2", "dp_src: hex.vec 2", "dp_ret: hex.vec w/4", "sl_hit: hex.vec 1",
                "los_poke: hex.vec 1", "pr_m: hex.vec 2",
                "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_reach: hex.vec 2",
                "dm_x: hex.vec 4", "dm_y: hex.vec 4", "dm_r4: hex.vec 4", "dm_ret: hex.vec w/4",
                "fxs_x: hex.vec 4", "fxs_y: hex.vec 4", "fxs_dmg: hex.vec 2", "fxs_kind: hex.vec 1",
                "fx_sret: hex.vec w/4", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
                "mt_dx: hex.vec 4", "mt_dy: hex.vec 4", "mt_ax: hex.vec 4", "mt_ay: hex.vec 4", "mt_d: hex.vec 4",
                "mt_t: hex.vec 4", "mt_ret: hex.vec w/4",
                "bar_solid: hex.vec %d" % nbar, "mon_active: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n,
                "mon_health: hex.vec %d" % (3 * n), "thpos_rt: hex.vec %d" % (16 * n)])
    prog = "\n".join(body + decls + [text] + stubs + BC.tables_fj() + [PC.tables_fj()[0]]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], want


def _frun(tmp_path, name, mut=None) -> bool:
    srcs, want = _fbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_fight_records_exercise_every_source():
    """bar_src recorded by a monster's and by the player's hit, kept on a second hit, refused on a killing blow; blasts
    whose source is a monster (the player's attacker named, the slots told), the player, none; a chain carrying it"""
    w = _fworld()
    seen = dict(rec_mon=0, rec_player=0, kept=0, lethal=0, blast_mon=0, blast_player=0, blast_none=0, chain=0,
                attacker=0, slot_told=0)
    for rec in _frecords(w):
        log = []
        b = rec["b"]
        before = rec["bsrc"]
        _fapply(w, rec, log)
        if rec["hit"] and rec["bar"][0] == _sidx("S_BAR1") or (rec["hit"] and rec["bar"][0] == _sidx("S_BAR2")):
            md, dmg, src = rec["hit"]
            if rec["bar"][2] - dmg <= 0 and rec["bar"][2] > 0:
                seen["lethal"] += 1
            elif rec["bar"][2] > 0:
                if before:
                    seen["kept"] += 1
                else:
                    seen["rec_mon" if md else "rec_player"] += 1
        if rec["bar"][0] == _sidx("S_BEXP3"):
            seen["blast_mon" if before >= 2 else "blast_player" if before == 1 else "blast_none"] += 1
        seen["attacker"] += any(ln[0] == "P" and ln[3:5] != "00" for ln in log)
        seen["slot_told"] += any(ln[0] == "M" and ln[6:8] not in ("00", "01") for ln in log)
        seen["chain"] += sum(1 for c in range(len(w.barrel_things)) if c != b and w.ws.bar_health[c] < 20)
    want = dict(rec_mon=8, rec_player=3, kept=5, lethal=3, blast_mon=30, blast_player=5, blast_none=5, chain=10,
                attacker=5, slot_told=10)
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_fight_barrels_follow_the_model(tmp_path):
    assert _frun(tmp_path, "barfight"), "the fj barrels' sources parted from the model's"


@pytest.mark.parametrize("mut", sorted(FIGHT_MUTANTS))
def test_control_a_broken_source_is_caught(tmp_path, mut):
    assert not _frun(tmp_path, "barfight_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
