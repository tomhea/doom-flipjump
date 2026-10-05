"""M7 P6 (doomfj.lootcode): THE PICKUPS on the real flipjump engine -- `pk_go`, the very text the emitter splices (the
cell tree, the item stubs, the drops, the give routines), against the model's own `combat._touch_specials`, record by
record in ONE image (a stub that left a register dirty would corrupt the next record).

Each record aims a TRIED CANDIDATE (16.16, fractional, on and around the touch box's exact edges) at a target -- a
map pickup, a cluster where two items share a cell (the touch ORDER decides which one a near-full count takes), or a
dropper's corpse placed beside a pickup or anywhere -- with the floor the player stands on (`cm_hf`) on and around
the reach window's edges, the movers in random states (a corpse on a lift: the drop's z follows it), and the
player's cells poked so that items are taken and refused (health, armor, ammo at and around the caps, the backpack,
weapons, the bonus count near 255, sometimes DEAD). Presence persists from record to record on both sides (a taken
item stays taken), and each record may put its target back. After every record: the player's cells, every pickup's
`thvis` slot, every dropper's `mdrop`, `dr_live`, and the hooks' marks (the runtime pickup unlinked, the drop taken).

R9 (MUTANTS), each must part: the dead guard gone, the presence test gone, the shared box test inclusive, the
reach without its lower / its upper bound, the cells' touch order reversed, the drop's z not its leaf's floor (no seed),
the drop's y read from its x, a taken drop left at 1, the bonus not added, a taken item left drawn, a runtime pickup
not unlinked.
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
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.monsters import MonsterViews
from doomfj.wad import WadFile
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
ART = ROOT / "assets" / "freedoom1.wad"
N = 520
M32 = 0xFFFFFFFF
PCELLS = (("p_hp", 3), ("p_ar", 2), ("p_at", 1), ("am_clip", 3), ("am_shell", 3), ("am_cell", 3), ("am_misl", 3),
          ("p_bp", 1), ("wp_own", 4), ("wp_pend", 1), ("p_str", 4), ("p_bc", 2), ("pcard", 1), ("dr_live", 2),
          ("rtu_mark", 2), ("rtu_lmark", 3), ("dt_mark", 2))


class Ctx:
    def __init__(self):
        self.w = World(skill=gd.SK_HARD, monsters="idle", player="fire")
        self.art = WadFile.from_path(str(ART))
        w = self.w
        self.mv = MonsterViews(w.rm, w.mw, "E1M1", self.art, w)
        self.slots = L.pickup_slots(w, w.rm, w.mw, "E1M1", self.art)
        self.drop = L.droppers(w)
        self.nslot = self.slots["nvis"] + self.slots["nextra"]


_CTX = None


def ctx():
    global _CTX
    if _CTX is None:
        _CTX = Ctx()
    return _CTX


def _leaf(w, x, y):
    return w.rm.point_in_subsector(w.cmap, x, y)


def _records(c):
    """[dict(pokes..., cand, z, present, drops {k: (x, y, state)}, movers)]"""
    w = c.w
    rnd = random.Random(0x6C)
    P = w.pickup_things
    pairs = [(i, j) for i in range(len(P)) for j in range(i + 1, len(P))
             if abs(P[i].x - P[j].x) < 72 and abs(P[i].y - P[j].y) < 72]
    out = []
    for r in range(N):
        kind = rnd.choice(("item", "item", "item", "pair", "drop", "drop", "dropitem"))
        rec = {"present": {}, "drops": {}}
        if kind in ("item", "dropitem"):
            i = rnd.randrange(len(P)) if rnd.random() < 0.7 else rnd.choice(
                [i for i, x in enumerate(c.slots["rt"]) if x is not None])
            t, z = P[i], w.pickup_z[i]
            rec["present"][i] = int(rnd.random() < 0.9)
        elif kind == "pair":
            i, j = rnd.choice(pairs)
            t, z = P[i], w.pickup_z[i]
            rec["present"][i] = rec["present"][j] = 1
            mx, my = (P[i].x + P[j].x) // 2, (P[i].y + P[j].y) // 2
        if kind == "drop":
            k = rnd.randrange(len(c.drop))
            m = c.drop[k]
            # a corpse at its own spawn, or somewhere a monster could be (another monster's spot), nudged
            base = w.mon_things[rnd.randrange(len(w.mon_things))] if rnd.random() < 0.5 else w.mon_things[m]
            x, y = base.x + rnd.randint(-20, 20), base.y + rnd.randint(-20, 20)
            rec["drops"][k] = (x, y, 1)
            tx, ty = x, y
        elif kind == "dropitem":
            k = rnd.randrange(len(c.drop))
            x, y = t.x + rnd.randint(-16, 16), t.y + rnd.randint(-16, 16)
            rec["drops"][k] = (x, y, rnd.choice((1, 1, 1, 2)))
            tx, ty = t.x, t.y
        elif kind == "pair":
            tx, ty = mx, my
        else:
            tx, ty = t.x, t.y
        for k in rnd.sample(range(len(c.drop)), 3):   # three other droppers: none, taken, or dropped where they spawned
            if k not in rec["drops"]:
                m = c.drop[k]
                st = rnd.choice((0, 0, 2, 1))
                rec["drops"][k] = (w.mon_things[m].x, w.mon_things[m].y, st)
        B = L.PK_RADIUS
        def coord(v):
            return rnd.choice(((v - B) << 16, ((v - B) << 16) + 1, ((v + B) << 16) - 1, (v + B) << 16,
                               ((v + rnd.randint(-B - 4, B + 4)) << 16) + rnd.choice((0, 0, 0x8000, 0x1234, 0xFFFF))))
        rec["cand"] = (coord(tx), coord(ty))
        if kind == "drop" or (kind == "dropitem" and rnd.random() < 0.5):
            x, y, _s = rec["drops"][next(iter(rec["drops"]))]
            sec = w.leaf_sector[_leaf(w, x, y)]
            zb = w.secs_c[sec].floor_h
        else:
            zb = z
        rec["z"] = rnd.choice((zb, zb, zb - 56, zb - 57, zb + 8, zb + 9, zb - 30, zb + rnd.randint(-80, 80)))
        rec["movers"] = ([rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order], rnd.choice((0, 1)))
        bp = rnd.choice((0, 0, 1))
        ammo = []
        for a in range(gd.NUMAMMO):
            cap = gd.MAXAMMO[a] * (2 if bp else 1)
            ammo.append(rnd.choice((0, 5, cap - 1, cap - 4, cap - 5, cap, rnd.randint(0, cap))))
        owned = {gd.WP_FIST: 1, gd.WP_PISTOL: 1, gd.WP_SHOTGUN: rnd.choice((0, 1)), gd.WP_CHAINSAW: rnd.choice((0, 1))}
        armor = rnd.choice((0, 99, 100, 199, rnd.randint(0, 200)))
        rec["pokes"] = {"p_health": rnd.choice((1, 60, 99, 100, 199, 200)), "p_armor": armor,
                        "p_armortype": rnd.choice((0, 1, 2)) if armor else 0, "ammo": ammo, "p_backpack": bp,
                        "owned": owned, "p_ready": rnd.choice([x for x in WC.WEAPONS if owned[x]]),
                        "p_pending": gd.WP_NOCHANGE, "p_strength": rnd.choice((0, 3)),
                        "p_bonuscount": rnd.choice((0, 0, 7, 250, 255)), "card": 0,
                        "p_dead": int(rnd.random() < 0.05)}
        out.append(rec)
    return out


def _model_apply(c, rec):
    w, ws = c.w, c.w.ws
    p = rec["pokes"]
    for f in ("p_health", "p_armor", "p_armortype", "p_backpack", "p_ready", "p_pending", "p_strength",
              "p_bonuscount", "p_dead"):
        setattr(ws, f, p[f])
    if p["p_dead"]:
        ws.p_health = 0
    for a in range(gd.NUMAMMO):
        ws.p_ammo[a] = p["ammo"][a]
    for x in range(gd.NUMWEAPONS):
        ws.p_owned[x] = p["owned"].get(x, 0)
    ws.p_cards[gd.IT_BLUECARD] = p["card"]
    for i, v in rec["present"].items():
        ws.pickup_taken[i] = 1 - v
    for k, (x, y, st) in rec["drops"].items():
        m = c.drop[k]
        ws.mon_x[m], ws.mon_y[m], ws.mon_drop[m] = x, y, st
        ws.mon_leaf[m] = _leaf(w, x, y)
    lst, sw = rec["movers"]
    for k in range(len(w.lift_order)):
        ws.l_state[k] = lst[k]
    ws.f_switch = sw
    w._door_phase_scene()


def _row(c, before_taken, before_drop) -> str:
    """the printed line: player cells, then every pickup's thvis slot (pickup order), then every dropper's mdrop"""
    w, ws = c.w, c.w.ws
    own = sum(ws.p_owned[x] << (4 * WC.OWN[x]) for x in WC.WEAPONS)
    rt_mark = lmark = 0
    for i in range(len(w.pickup_things)):
        if ws.pickup_taken[i] and not before_taken[i] and c.slots["rt"][i] is not None:
            rt_mark, lmark = c.slots["rt"][i] + 1, c.slots["leaf"][i]
    dt_mark = 0
    for k, m in enumerate(c.drop):
        if ws.mon_drop[m] == 2 and before_drop[k] == 1:
            dt_mark = k + 1
    vals = [ws.p_health & 0xFFF, ws.p_armor, ws.p_armortype, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
            ws.p_ammo[gd.AM_CELL], ws.p_ammo[gd.AM_MISL], ws.p_backpack, own, ws.p_pending, ws.p_strength,
            ws.p_bonuscount, ws.p_cards[gd.IT_BLUECARD], sum(ws.mon_drop[m] == 1 for m in c.drop),
            rt_mark, lmark, dt_mark]
    s = "".join("%0*x" % (n, v) for (_c, n), v in zip(PCELLS, vals))
    s += "".join("%x" % (1 - ws.pickup_taken[i]) for i in range(len(w.pickup_things)))
    s += "".join("%x" % ws.mon_drop[m] for m in c.drop)
    return s


def _expected(c, records) -> bytes:
    w = c.w
    # the persistent presence: the hard level start
    lines = []
    for rec in records:
        _model_apply(c, rec)
        bt = list(w.ws.pickup_taken)
        bd = [w.ws.mon_drop[m] for m in c.drop]
        w._touch_specials(rec["cand"][0], rec["cand"][1], rec["z"], TicEvents(0))
        lines.append(_row(c, bt, bd))
    return ("\n".join(lines) + "\n").encode()


def _hooks():
    def unl(t, leaf):
        return [f"    hex.set 2, rtu_mark, {t + 1}", f"    hex.set 3, rtu_lmark, {leaf}"]

    def take(k):
        return [f"    hex.set 2, dt_mark, {k + 1}"]
    return unl, take


MUTANTS = {
    "dead": (r"    hex\.if1 1, p_dead, pk_out\n", ""),
    "present": (r"    hex\.if0 1, thvis \+ \d+\*2\*dw, pk\d+_n\n", ""),
    # the shared box test (pk_boxz: items and drops) inclusive on both axes
    "strict": (r"(hex\.scmp 8, pk_d, pk_bd, (pkb_[yr])), pkb_out, ", r"\1, \2, "),
    # the reach window without its lower bound (item_z - z >= -8) / its upper one (<= 56)
    "reach": (r"    hex\.scmp 8, pk_d, pk_cdn, pkb_out, pkb_in, pkb_in\n", ""),
    "reach_up": (r"    hex\.scmp 8, pk_d, pk_cup, pkb_u, pkb_u, pkb_out\n", ""),
    "order": None,
    # the drop's z not its leaf's floor now (the seed never read: a stale cp_seedf)
    "drop_seed": (r"(    hex\.read_hex 3, ptss, pk_ptr\n)    stl\.fcall ms_seed_leaf, ms_seed_ret\n", r"\1"),
    # the drop's y read from its x
    "drop_y": (r"hex\.mov 8, pk_ty, pk_pos \+ 8\*dw", "hex.mov 8, pk_ty, pk_pos"),
    "drop_left": (r"    hex\.set 1, mdrop \+ \d+\*dw, 2\n", ""),
    "nobonus": (r"(  pkbba:\n)    hex\.add_constant 2, p_bc, 6\n", r"\1"),
    "novanish": (r"    hex\.zero 2, thvis \+ \d+\*2\*dw\n", ""),
    "nounlink": None,
}


def _program(c, mut=None):
    w = c.w
    unl, take = _hooks()
    lists = None
    if mut == "order":
        lists = {k: tuple(reversed(v)) for k, v in L.pickup_cell_lists(w).items()}
    if mut == "nounlink":
        unl = lambda t, leaf: []                                       # noqa: E731
    text = "\n".join(L.pickup_lines(w, c.slots, c.mv.rt, rt_unlink=unl, drop_take=take, lists=lists)) + "\n"
    if mut and MUTANTS[mut]:
        pat, new = MUTANTS[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    from doomfj.wall_renderer import DOOR_QUANT
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    ws = w.ws
    nrt = c.mv.nrt
    thpos = [0] * nrt
    thss = [0] * nrt
    for m, t in enumerate(c.mv.rt):
        thpos[t] = ((ws.mon_x[m] << 16) & M32) | (((ws.mon_y[m] << 16) & M32) << 32)
        thss[t] = ws.mon_leaf[m]
    vis = [1] * c.nslot
    for i, s in enumerate(c.slots["slot"]):
        vis[s] = 1 - ws.pickup_taken[i]
    wstart = WC.level_start(w.mw, "E1M1")
    states, frames = WC.weapon_states(), WC.overlay_frames()
    decls = (L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, states, frames) + COLLISION_STATE_DECLS + point_location_decls()
             + MM.monster_seed_decls()
             + ["pcard: hex.vec 1", "thvis:"] + ["    hex.vec 2, %d" % v for v in vis]
             + ["mdrop: hex.vec %d" % len(c.drop), "dr_live: hex.vec 2",
                "thpos_rt: hex.vec %d, %d" % (16 * nrt, sum(v << (64 * t) for t, v in enumerate(thpos))),
                "thss_rt: hex.vec %d, %d" % (16 * nrt, sum(v << (64 * t) for t, v in enumerate(thss))),
                "lstate: hex.vec %d" % max(1, len(w.lift_order)), "fswitch: hex.vec 1",
                "rtu_mark: hex.vec 2", "rtu_lmark: hex.vec 3", "dt_mark: hex.vec 2"])
    return decls, text + "\n".join(seed) + "\n", L.tables_fj(w)


def _build(tmp_path, name, mut=None):
    c = ctx()
    w = c.w
    records = _records(c)
    nib = {"p_health": ("p_hp", 3), "p_armor": ("p_ar", 2), "p_armortype": ("p_at", 1), "p_backpack": ("p_bp", 1),
           "p_ready": ("wp_rdy", 1), "p_pending": ("wp_pend", 1), "p_strength": ("p_str", 4),
           "p_bonuscount": ("p_bc", 2), "card": ("pcard", 1), "p_dead": ("p_dead", 1)}
    body = ["stl.startup_and_init_all"]
    for rec in records:
        p = rec["pokes"]
        for f, (cl, n) in nib.items():
            body.append("hex.set %d, %s, %d" % (n, cl, p[f]))
        if p["p_dead"]:
            body.append("hex.zero 3, p_hp")
        for a in range(gd.NUMAMMO):
            body.append("hex.set 3, %s, %d" % (L.AMMO_CELL[a], p["ammo"][a]))
        body.append("hex.set 4, wp_own, %d" % sum(p["owned"][x] << (4 * WC.OWN[x]) for x in WC.WEAPONS))
        for i, v in rec["present"].items():
            body.append("hex.set 2, thvis + %d*2*dw, %d" % (c.slots["slot"][i], v))
        for k, (x, y, st) in rec["drops"].items():
            t = c.mv.rt[c.drop[k]]
            body += ["hex.set 16, thpos_rt + %d*dw, %d" % (16 * t, ((x << 16) & M32) | (((y << 16) & M32) << 32)),
                     "hex.set 3, thss_rt + %d*dw, %d" % (16 * t, _leaf(w, x, y)),
                     "hex.set 1, mdrop + %d*dw, %d" % (k, st)]
        body.append("stl.fcall dr_count, drc_ret")         # dr_live: the count of mdrop == 1 (package C keeps it)
        lst, sw = rec["movers"]
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(lst)] + ["hex.set 1, fswitch, %d" % sw]
        body += ["hex.set 8, cpx, %d" % (rec["cand"][0] & M32), "hex.set 8, cpy, %d" % (rec["cand"][1] & M32),
                 "hex.set 8, cm_hf, %d" % (rec["z"] & M32),
                 "hex.zero 2, rtu_mark", "hex.zero 3, rtu_lmark", "hex.zero 2, dt_mark",
                 "stl.fcall pk_go, pk_ret"]
        body += ["hex.print_as_digit %d, %s, 0" % (n, cl) for cl, n in PCELLS]
        body += ["hex.print_as_digit 1, thvis + %d*2*dw, 0" % c.slots["slot"][i] for i in range(len(w.pickup_things))]
        body += ["hex.print_as_digit 1, mdrop + %d*dw, 0" % k for k in range(len(c.drop))]
        body += ["stl.output 10"]
    body += ["stl.loop"]
    decls, text, tables = _program(c, mut)
    count = ["dr_count:", "    hex.zero 2, dr_live"]
    for k in range(len(c.drop)):
        count += ["    hex.if_flags mdrop + %d*dw, 0x0002, drc%d, drc%dy" % (k, k, k), "  drc%dy:" % k,
                  "    hex.inc 2, dr_live", "  drc%d:" % k]
    count += ["    stl.fret drc_ret", "drc_ret: hex.vec w/4"]
    prog = "\n".join(body + decls + count + [text] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, _expected(Ctx(), records)


def _run(tmp_path, name, mut=None) -> bool:
    srcs, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """items taken (baked and runtime), refused by the give, by the box, by the reach (both edges), two taken at one
    candidate, drops taken (clip and shotgun) and refused, a corpse on a moved lift, a dead player touching nothing"""
    c = Ctx()
    w = c.w
    seen = dict(taken=0, rt_taken=0, multi=0, drop_taken=0, drop_refused=0, dead=0, box_edge_out=0, reach_lo=0,
                reach_hi=0)
    kinds = set()
    for rec in _records(c):
        _model_apply(c, rec)
        bt = list(w.ws.pickup_taken)
        bd = {k: w.ws.mon_drop[m] for k, m in enumerate(c.drop)}
        w._touch_specials(rec["cand"][0], rec["cand"][1], rec["z"], TicEvents(0))
        new = [i for i in range(len(bt)) if w.ws.pickup_taken[i] and not bt[i]]
        seen["taken"] += bool(new)
        seen["rt_taken"] += any(c.slots["rt"][i] is not None for i in new)
        seen["multi"] += len(new) >= 2
        dt = [k for k, m in enumerate(c.drop) if bd[k] == 1 and w.ws.mon_drop[m] == 2]
        seen["drop_taken"] += bool(dt)
        kinds |= {w.dropper[c.drop[k]] for k in dt}
        seen["drop_refused"] += any(bd[k] == 1 and w.ws.mon_drop[c.drop[k]] == 1 for k in rec["drops"])
        seen["dead"] += rec["pokes"]["p_dead"]
        cx, cy = rec["cand"]
        for i in rec["present"]:
            t, z = w.pickup_things[i], w.pickup_z[i]
            inbox = abs((t.x << 16) - cx) < L.PK_RADIUS << 16 and abs((t.y << 16) - cy) < L.PK_RADIUS << 16
            seen["box_edge_out"] += abs((t.x << 16) - cx) == L.PK_RADIUS << 16
            seen["reach_lo"] += inbox and rec["z"] == z - 57
            seen["reach_hi"] += inbox and rec["z"] == z + 9
    want = dict(taken=60, rt_taken=5, multi=5, drop_taken=20, drop_refused=20, dead=10, box_edge_out=10, reach_lo=5,
                reach_hi=5)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert kinds == {2007, 2001}, kinds


def test_the_pickups_follow_the_model(tmp_path):
    assert _run(tmp_path, "pickup"), "the fj pickups parted from the model's _touch_specials"


@pytest.mark.parametrize("mut", sorted(MUTANTS))
def test_control_broken_pickups_are_caught(tmp_path, mut):
    assert not _run(tmp_path, "pickup_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
