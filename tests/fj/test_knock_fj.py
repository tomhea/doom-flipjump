"""M7 P8a package K (docs/gp-final-plan.md 3.1 row K, doomfj.knockcode): KNOCKBACK on the real flipjump engine -- the
very text the emitter splices, against the model's own `combat._thrust` / `_xy_move` (`_player_knock_try`,
`world._monster_knock_try`, `_knock_slides`), record by record in ONE image per program.

THE THRUST (`kb_go`, its slot stubs kbt<m>, `kb_gm`, `kb_th`): each record pokes a target -- the player, or a monster
slot (dm_leaf's window dm_hp / dm_rng / dm_x / dm_y as its stub loads it, its fraction, floorz and momentum) -- and a
site's inflictor (the player, a monster, a fireball, a barrel: kb_ix / kb_iy / kb_iz / kb_izp / kb_sp exactly as the
site sets them), the ready weapon, the damage (at and around 40 and the health), the stream, a momentum already moving
or not (and one record whose thrust cancels it exactly), then calls kb_go and prints the momentum, the stream, kb_live
and the site flags. The player's z (`kb_pz`, the cells' floorz) is the one stubbed line: it reads the model's
check_position floorz from stdin, in the model's order (target first) -- `kb_pz` itself runs in the MOVES program.

THE MOVES (`kb_xy`, `kb_ptry`, `kb_mtry`, `kb_cell`, `kb_pmove`, `kb_mmove`, the slot stubs kbs<m>): the player's and
the monsters' knock moves on E1M1's real cells -- the player's cells with the static blockers, the monsters' cells, the
point location and seed, mm_things, pk_go (with the drops' own rows) and pb_mon, the walk-over and lift lines, the leaf
lists (projcode's pw_link / pw_unlink stand-ins: the same macros) -- from positions beside walls, ledges, lifts,
monsters, items, with momenta at and around MAXMOVE, MAXMOVE / 2, STOPSPEED, FRACUNIT / 4 (halved and not, negative
and positive), live, dead and corpse; after every record the mover's cells and the world it touched.

R9 (each must part from the model): THRUST no_thrust, thrust_sign (the angle target -> inflictor), mass (the 400 shift
dropped), saw_thrust (the chainsaw thrusts), reverse_rng (the coin read from v > 200), no_reverse, live (kb_live not
kept); MOVES no_friction, stopspeed (<= for <), no_clamp, no_halve, half_shift (x + xmove >> 1 for xmove / 2),
wall_keeps (a refused try keeps the momentum), frac_drop (the fraction not kept), no_retest (an integer change
accepted untested), corpse_live (a corpse tries as a live monster), corpse_rule (the corpse slides on), drop_follows
(the pickup reads the corpse's row, not the drop's).
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import knockcode as KC
from doomfj import rng as R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj, generate_trig_idioms_fj
from doomfj.monstercode import rnd_values
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj
from doomfj.world import TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
U = gd.FRACUNIT
N_THRUST = 420


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _world():
    return World(skill=gd.SK_HARD, monsters="final", player="final")


def _legal_spots(w, n=200):
    """leaf interior points the player may stand on (check_position ok, 56 fits, no solid thing)"""
    out = []
    for s, ss in enumerate(w.cmap.subsectors):
        segs = [w.cmap.segs[ss.firstseg + i] for i in range(ss.numsegs)]
        xs = [w.cmap.vertexes[g.v1][0] for g in segs]
        ys = [w.cmap.vertexes[g.v1][1] for g in segs]
        cx, cy = sum(xs) // len(xs), sum(ys) // len(ys)
        if w.rm.point_in_subsector(w.cmap, cx, cy) != s:
            continue
        ok, fz, cz = w.rm.check_position(w.scene_c, cx << 16, cy << 16)
        if ok and cz - fz >= 56 and w._solid_thing_at(cx << 16, cy << 16) is None:
            out.append((cx, cy))
    return out


# ================================================================================================================
# THE THRUST
# ================================================================================================================
def _thrust_records(w):
    rnd = random.Random(0x4B)
    ws = w.ws
    n = w.layout.nmon
    spots = _legal_spots(w)
    act = [m for m in range(n) if ws.mon_active[m]]
    heavy = [m for m in act if w.mon_info[m].mass == 400]
    out = []
    for r in range(N_THRUST):
        rec = {}
        rec["target"] = ("player", -1) if rnd.random() < 0.4 else ("mon", rnd.choice(heavy if rnd.random() < 0.3
                                                                                       else act))
        px, py = rnd.choice(spots)
        rec["p"] = ((px << 16) + rnd.choice((0, 0x8000, rnd.randrange(1 << 16))),
                    (py << 16) + rnd.choice((0, 0xFFFF, rnd.randrange(1 << 16))))
        if rec["target"][0] == "player":
            rec["ikind"] = rnd.choice(("mon", "mon", "proj", "bar"))
        else:
            rec["ikind"] = rnd.choice(("player", "player", "player", "bar"))
        rec["on"] = rnd.random() > 0.06
        rec["saw"] = rnd.random() < 0.12
        # the target's and the inflictor's positions: the inflictor around the target at some angle
        k = rnd.randrange(12)
        ang = [0, 45, 90, 135, 180, 225, 270, 315][k] if k < 8 else rnd.uniform(0, 360)
        import math
        d = rnd.choice((24, 64, 200, 900, rnd.randint(1, 1500)))
        dx, dy = int(round(d * math.cos(math.radians(ang)))), int(round(d * math.sin(math.radians(ang))))
        if rec["target"][0] == "player":
            rec["ipos"] = ((rec["p"][0] >> 16) + dx, (rec["p"][1] >> 16) + dy)
        else:
            tx, ty = rnd.choice(spots)
            rec["tpos"] = (tx, ty, rnd.randrange(1 << 16), rnd.randrange(1 << 16))
            rec["ipos"] = (tx + dx, ty + dy)
            if rec["ikind"] == "player":
                rec["p"] = (((tx + dx) << 16) + rnd.randrange(1 << 16), ((ty + dy) << 16) + rnd.randrange(1 << 16))
        rec["ij"] = rnd.choice(act) if rec["ikind"] == "mon" else rnd.randrange(8) if rec["ikind"] == "proj" else \
            rnd.randrange(len(w.barrel_things))
        rec["dmg"] = rnd.choice((1, 3, 5, 10, 15, 24, 39, 39, 40, 41, 64, 100, 128, 200, 255, rnd.randint(1, 255)))
        dmg = rec["dmg"]
        rec["hp"] = rnd.choice((dmg - 1, dmg - 1, dmg, dmg + 1, 1, 100, 300, rnd.randint(1, 255)))
        rec["hp"] = max(1, rec["hp"])
        # the z difference around 64 -- the target above
        rec["dz"] = rnd.choice((63, 64, 65, 65, 100, 130, -10, 0, rnd.randint(-200, 200)))
        rec["rng"] = rnd.randrange(256)
        rec["mom"] = rnd.choice(((0, 0), (0, 0), (rnd.randint(-0x80000, 0x80000), rnd.randint(-0x80000, 0x80000)),
                                 (5, 0), (0, -7)))
        rec["cancel"] = rnd.random() < 0.05
        rec["live0"] = rnd.randrange(0, 5)
        out.append(rec)
    return out


def _thrust_apply(w, rec, feed=None):
    """the record into the model, the thrust, and the fj's site values: -> (target, dict of fj pokes)"""
    ws = w.ws
    n = w.layout.nmon
    for m in range(n):
        ws.mon_momx[m] = ws.mon_momy[m] = 0
    ws.p_momx = ws.p_momy = 0
    ws.px, ws.py = rec["p"]
    ws.p_owned[gd.WP_CHAINSAW] = 1
    ws.p_ready = gd.WP_CHAINSAW if rec["saw"] else gd.WP_PISTOL
    tgt = rec["target"]
    pz = w.rm.check_position(w.scene_c, ws.px, ws.py)[1]
    if tgt[0] == "player":
        ws.p_health, ws.rng_player = rec["hp"], rec["rng"]
        ws.p_momx, ws.p_momy = rec["mom"]
        tz = pz
    else:
        m = tgt[1]
        tx, ty, fx, fy = rec["tpos"]
        ws.mon_x[m], ws.mon_y[m], ws.mon_fx[m], ws.mon_fy[m] = tx, ty, fx, fy
        ws.mon_health[m], ws.mon_rng[m] = rec["hp"], rec["rng"]
        ws.mon_momx[m], ws.mon_momy[m] = rec["mom"]
        tz = ws.mon_floorz[m] = (pz + rec["dz"]) if rec["ikind"] == "player" else rec["dz"] + 7
    kind, j = rec["ikind"], rec["ij"]
    if kind == "mon":
        ws.mon_x[j], ws.mon_y[j] = rec["ipos"]
        ws.mon_floorz[j] = tz - rec["dz"]
        src = ("mon", j)
    elif kind == "proj":
        ws.proj_x[j], ws.proj_y[j] = (rec["ipos"][0] << 16) + 0x1234, (rec["ipos"][1] << 16) + 0xFEDC
        ws.proj_z[j] = tz - rec["dz"]
        src = ("mon", 0)
    elif kind == "bar":
        src = ("bar", j)
        if "bar_src" in ws._fields:
            ws.bar_src[j] = 1                   # the player set it off (package I's record; the fj site's kb_sp 1)
        if tgt[0] == "mon":                     # a barrel's z is its floor: put the monster's around it
            ws.mon_floorz[tgt[1]] = w._knock_z(("bar", j)) + rec["dz"]
    else:
        src = ("player", -1)
    infl = (kind, j) if kind != "player" else ("player", -1)
    if rec["cancel"] and rec["on"]:
        # a momentum the thrust cancels exactly: run it once on a copy to learn the delta
        snap = ws.copy()
        w._thrust(tgt, infl, src, rec["dmg"])
        if tgt[0] == "player":
            d = (ws.p_momx - rec["mom"][0], ws.p_momy - rec["mom"][1])
        else:
            d = (ws.mon_momx[tgt[1]] - rec["mom"][0], ws.mon_momy[tgt[1]] - rec["mom"][1])
        w.ws = snap
        ws = w.ws
        if tgt[0] == "player":
            ws.p_momx, ws.p_momy = -d[0], -d[1]
        else:
            ws.mon_momx[tgt[1]], ws.mon_momy[tgt[1]] = -d[0], -d[1]
    # the slots moving before: the record's own target's momentum, plus `live0` others (never read, only counted)
    live_before = sum(1 for m in range(n) if ws.mon_momx[m] or ws.mon_momy[m]) + rec["live0"]
    ix, iy = w._inflictor_xy(infl)
    site = {"on": int(rec["on"]), "ix": (ix >> 16) & 0xFFFF, "iy": (iy >> 16) & 0xFFFF,
            "iz": (w._knock_z(infl) if kind != "player" else 0) & 0xFFFF, "izp": int(kind == "player"),
            "sp": int(w._source_is_player(src))}
    snap_t = (ws.p_momx, ws.p_momy) if tgt[0] == "player" else (ws.mon_momx[tgt[1]], ws.mon_momy[tgt[1]])
    pre = {"mom": snap_t, "live": live_before}
    if feed is not None:
        real = w._knock_z

        def spy(thing):
            v = real(thing)
            if thing[0] == "player":
                feed.append(v)
            return v
        w._knock_z = spy
    try:
        if rec["on"]:
            w._thrust(tgt, infl, src, rec["dmg"])
    finally:
        w.__dict__.pop("_knock_z", None)
    return pre, site


def _thrust_row(w, rec, pre):
    ws = w.ws
    tgt = rec["target"]
    n = w.layout.nmon
    live = sum(1 for m in range(n) if ws.mon_momx[m] or ws.mon_momy[m]) + rec["live0"]
    s = "%08x%08x%02x" % (ws.p_momx & M32, ws.p_momy & M32, ws.rng_player)
    if tgt[0] == "mon":
        m = tgt[1]
        s += "%08x%08x%02x" % (ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_rng[m])
    return s + "%02x00" % live


THRUST_MUTANTS = {
    "no_thrust": ("    hex.if0 1, kb_on, kq_out\n", "    ;kq_out\n"),
    "thrust_sign": ("    proj.point_to_angle kb_ang, kb_i8x, kb_i8y, kb_tx, kb_ty, 1\n",
                    "    proj.point_to_angle kb_ang, kb_tx, kb_ty, kb_i8x, kb_i8y, 1\n"),
    "mass": ("    hex.if0 1, kb_hv, kq_s3\n", "    ;kq_s3\n"),
    "saw_thrust": ("    hex.if0 1, kb_sp, kq_ns\n", "    ;kq_ns\n"),
    "reverse_rng": ("    hex.if_flags kb_rr + 2*dw, %d, kq_nr, kq_rv\n" % 0b1100110011001100,
                    "    hex.if_flags kb_rr + 2*dw, %d, kq_nr, kq_rv\n" % 0b1010101010101010),
    "no_reverse": ("  kq_rv:\n    hex.set 1, kb_rev, 1\n", "  kq_rv:\n"),
    "live": ("    hex.inc 2, kb_live\n", ""),
}


def _thrust_program(w, mut=None):
    n = w.layout.nmon
    slots = KC.slots_of(w, list(range(n)))
    code = "\n".join(KC.go_lines(slots)) + "\n"
    a = code.index("kb_pz:\n")
    b = code.index("    stl.fret kb_pzret\n", a) + len("    stl.fret kb_pzret\n")
    code = code[:a] + "kb_pz:\n    hex.input 2, kb_pzv\n    stl.fret kb_pzret\n" + code[b:]     # THE ONE STUB
    if mut:
        old, new = THRUST_MUTANTS[mut]
        assert code.count(old) == 1, (mut, code.count(old))
        code = code.replace(old, new)
    decls = (KC.decls(n) + ["viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "rng_pl: hex.vec 2",
                            "wp_rdy: hex.vec 1", "dm_hp: hex.vec 3", "dm_rng: hex.vec 2", "dm_x: hex.vec 4",
                            "dm_y: hex.vec 4", "mon_floorz: hex.vec %d" % (4 * n)])
    tables = [generate_dispatch_table_fj("mrnd", rnd_values(), index_nibbles=2, result_nibbles=4),
              generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry"),
              generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
              generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
              generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    return decls, code, tables


def _thrust_build(tmp_path, name, mut=None):
    w = _world()
    recs = _thrust_records(w)
    n = w.layout.nmon
    feed, want = [], []
    body = ["stl.startup_and_init_all"]
    for rec in recs:
        w.reset(gd.SK_HARD)
        pre, site = _thrust_apply(w, rec, feed)
        want.append(_thrust_row(w, rec, pre))
        tgt = rec["target"]
        ws0 = pre
        body += ["hex.set 8, viewx, %d" % (rec["p"][0] & M32), "hex.set 8, viewy, %d" % (rec["p"][1] & M32),
                 "hex.set 1, wp_rdy, %d" % (gd.WP_CHAINSAW if rec["saw"] else gd.WP_PISTOL),
                 "hex.zero 8, p_kmx", "hex.zero 8, p_kmy", "hex.set 2, kb_live, %d" % ws0["live"]]
        if tgt[0] == "player":
            body += ["hex.set 3, p_hp, %d" % rec["hp"], "hex.set 2, rng_pl, %d" % rec["rng"],
                     "hex.set 8, p_kmx, %d" % (ws0["mom"][0] & M32), "hex.set 8, p_kmy, %d" % (ws0["mom"][1] & M32),
                     "hex.set 2, kb_tg, 0"]
        else:
            m = tgt[1]
            tx, ty, fx, fy = rec["tpos"]
            body += ["hex.set 3, dm_hp, %d" % rec["hp"], "hex.set 2, dm_rng, %d" % rec["rng"],
                     "hex.set 4, dm_x, %d" % (tx & 0xFFFF), "hex.set 4, dm_y, %d" % (ty & 0xFFFF),
                     "hex.set 4, mfx + %d*dw, %d" % (4 * m, fx), "hex.set 4, mfy + %d*dw, %d" % (4 * m, fy),
                     "hex.set 4, mon_floorz + %d*dw, %d" % (4 * m, w.ws.mon_floorz[m] & 0xFFFF),
                     "hex.set 8, mkx + %d*dw, %d" % (8 * m, ws0["mom"][0] & M32),
                     "hex.set 8, mky + %d*dw, %d" % (8 * m, ws0["mom"][1] & M32),
                     "hex.set 2, rng_pl, %d" % w.ws.rng_player, "hex.set 2, kb_tg, %d" % (m + 1)]
        body += ["hex.set 1, kb_on, %d" % site["on"], "hex.set 4, kb_ix, %d" % site["ix"],
                 "hex.set 4, kb_iy, %d" % site["iy"], "hex.set 4, kb_iz, %d" % site["iz"],
                 "hex.set 1, kb_izp, %d" % site["izp"], "hex.set 1, kb_sp, %d" % site["sp"],
                 "hex.set 2, kb_dm, %d" % rec["dmg"],
                 "stl.fcall kb_go, kb_ret",
                 "hex.print_as_digit 8, p_kmx, 0", "hex.print_as_digit 8, p_kmy, 0",
                 "hex.print_as_digit 2, rng_pl, 0"]
        if tgt[0] == "mon":
            m = tgt[1]
            body += ["hex.print_as_digit 8, mkx + %d*dw, 0" % (8 * m), "hex.print_as_digit 8, mky + %d*dw, 0" % (8 * m),
                     "hex.print_as_digit 2, dm_rng, 0"]
        body += ["hex.print_as_digit 2, kb_live, 0", "hex.print_as_digit 1, kb_sp, 0",
                 "hex.print_as_digit 1, kb_izp, 0", "stl.output 10"]
        if tgt[0] == "mon":                       # clear the slot for the next record (the fj's cells persist)
            m = tgt[1]
            body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)]
    body += ["stl.loop"]
    decls, code, tables = _thrust_program(w, mut)
    prog = "\n".join(body + decls + [code] + tables) + "\n" + hoisted_scratch_fj()
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    fin = b"".join((v & 0xFFFF).to_bytes(2, "little") for v in feed)
    return srcs, fin, ("\n".join(want) + "\n").encode()


def _thrust_run(tmp_path, name, mut=None) -> bool:
    srcs, fin, want = _thrust_build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, fin, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_thrust_records_exercise_every_path():
    """the model over the records: both targets and both masses, every inflictor kind, no inflictor, the saw (both
    sources), reversals with both coins, a reversal refused by each condition, kb_live going up, down and staying,
    and the player's z read for a target and for an inflictor"""
    w = _world()
    seen = dict(player=0, mon=0, heavy=0, none=0, saw_none=0, saw_hit=0, rev_odd=0, rev_even=0, near40=0, nearhp=0,
                nearz=0, up=0, down=0, pz_t=0, pz_i=0, **{"i_" + k: 0 for k in ("player", "mon", "proj", "bar")})
    for rec in _thrust_records(w):
        w.reset(gd.SK_HARD)
        feed = []
        tgt = rec["target"]
        pre, site = _thrust_apply(w, rec, feed)
        ws = w.ws
        seen[tgt[0]] += 1
        seen["heavy"] += tgt[0] == "mon" and w.mon_info[tgt[1]].mass == 400
        seen["i_" + rec["ikind"]] += 1
        seen["none"] += not rec["on"]
        after = (ws.p_momx, ws.p_momy) if tgt[0] == "player" else (ws.mon_momx[tgt[1]], ws.mon_momy[tgt[1]])
        if rec["saw"] and rec["on"]:
            seen["saw_none" if site["sp"] else "saw_hit"] += 1
        drew = (ws.rng_player if tgt[0] == "player" else ws.mon_rng[tgt[1]]) != rec["rng"]
        if drew:
            seen["rev_odd" if R.p_random(rec["rng"])[0] & 1 else "rev_even"] += 1
        elif rec["on"] and not (rec["saw"] and site["sp"]):
            seen["near40"] += rec["dmg"] == 40 and rec["hp"] < 40
            seen["nearhp"] += rec["dmg"] == rec["hp"] and rec["dmg"] < 40
            seen["nearz"] += rec["dz"] == 64 and rec["dmg"] < 40 and rec["dmg"] > rec["hp"]
        b, a = bool(pre["mom"][0] or pre["mom"][1]), bool(after[0] or after[1])
        seen["up"] += a and not b
        seen["down"] += b and not a
        seen["pz_t"] += bool(feed) and tgt[0] == "player"
        seen["pz_i"] += bool(feed) and tgt[0] == "mon"
    want = dict(player=100, mon=150, heavy=30, none=10, saw_none=10, saw_hit=3, rev_odd=8, rev_even=8, near40=2,
                nearhp=2, nearz=1, up=100, down=3, pz_t=10, pz_i=10, i_player=60, i_mon=60, i_proj=20, i_bar=30)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_thrust_follows_the_model(tmp_path):
    assert _thrust_run(tmp_path, "kthrust"), "the fj thrust parted from the model's _thrust"


@pytest.mark.parametrize("mut", sorted(THRUST_MUTANTS))
def test_control_a_broken_thrust_is_caught(tmp_path, mut):
    assert not _thrust_run(tmp_path, "kthrust_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================================
# THE MOVES
# ================================================================================================================
N_MON, N_PLAYER = 220, 200
NMOB = 10                                         # FIREBALL_POOL + FX_POOL: the drop rows follow them (barrelcode)


class Mv:
    """the moves' static world: the model, its cell sets and the runtime rows -- monster slot m is row m (the chase
    harness's layout), the drops rows n + NMOB + k"""

    def __init__(self):
        from doomfj import lootcode as L
        from doomfj import monstermove as MM
        from doomfj.wad import WadFile
        self.w = w = _world()
        self.n = w.layout.nmon
        self.art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
        self.slots = L.pickup_slots(w, w.rm, w.mw, "E1M1", self.art)
        self.things, self.var = MM.static_blockers(w)
        self.drop = L.droppers(w)
        self.drop_rt = [self.n + NMOB + k for k in range(len(self.drop))]
        self.nrows = self.n + NMOB + len(self.drop)
        self.spots = _legal_spots(w)


def _ledges(w):
    """(x, y, ux, uy): a point on the HIGH side of a ledge (a two-sided line whose floors are > 24 apart), 23 units
    in, and the unit step toward the low side"""
    import math
    out = []
    for li, ld in enumerate(w.lds):
        if ld.back == -1:
            continue
        fs, bs = w.secs[w.sds[ld.front].sector], w.secs[w.sds[ld.back].sector]
        if abs(fs.floor_h - bs.floor_h) <= 24:
            continue
        (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 48:
            continue
        nx, ny = (y2 - y1) / length, -(x2 - x1) / length     # the front side's normal (right of v1 -> v2)
        if bs.floor_h > fs.floor_h:
            nx, ny = -nx, -ny                                 # toward the HIGH side
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out.append((int(mx + 23 * nx), int(my + 23 * ny), -nx, -ny))
    return out


def _mon_records(c):
    import math
    w = c.w
    rnd = random.Random(0x4B4D)
    ws = w.ws
    act = [m for m in range(c.n) if ws.mon_active[m]]
    ledges = _ledges(w)
    lifts = [(tr[2], tr[3], tr[4], tr[1]) for tr in w.lift_walk]
    out = []
    for r in range(N_MON):
        rec = {"m": rnd.choice(act)}
        kind = rnd.choice(("open", "open", "open", "ledge", "ledge", "wall", "lift", "lift", "crowd"))
        mag = rnd.choice((3 * U, 8 * U, 15 * U, 15 * U + 1, 16 * U, 30 * U, 31 * U, 45 * U, 0x4001, 0x4000,
                          0x1000, 0xFFF, 0x2000, rnd.randint(1, 40 * U)))
        ang = rnd.uniform(0, 2 * math.pi)
        if kind == "ledge":
            x, y, ux, uy = rnd.choice(ledges)
            ang = math.atan2(uy, ux) + rnd.uniform(-0.3, 0.3)
        elif kind == "lift":
            coord, lo, hi, axis = rnd.choice(lifts)
            t = rnd.randint(lo, hi)
            side = rnd.choice((-1, 1))
            x, y = ((coord + side * rnd.randint(2, 8), t) if axis == "x" else (t, coord + side * rnd.randint(2, 8)))
            ang = (0 if side < 0 else math.pi) if axis == "x" else (math.pi / 2 if side < 0 else -math.pi / 2)
            mag = rnd.randint(10 * U, 25 * U)
        elif kind == "wall":
            x, y = rnd.choice(c.spots)
            x, y = x + rnd.randint(-40, 40), y + rnd.randint(-40, 40)
        else:
            x, y = rnd.choice(c.spots)
            x, y = x + rnd.randint(-6, 6), y + rnd.randint(-6, 6)
        rec["pos"] = (x, y, rnd.choice((0, 0, 0xFFFF, 0x8000, rnd.randrange(1 << 16))),
                      rnd.choice((0, 0x0001, 0xFFF0, rnd.randrange(1 << 16))))
        mx, my = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        if rnd.random() < 0.15:                            # an axis exactly: one coordinate 0
            mx, my = (mx, 0) if rnd.random() < 0.5 else (0, my)
        if mx == 0 and my == 0:
            mx = 1
        rec["mom"] = (mx, my)
        rec["corpse"] = rnd.random() < (0.6 if kind == "ledge" else 0.3)
        rec["solid"] = int(not rec["corpse"] or rnd.random() < 0.3)      # a dying corpse still blocks
        rec["dz"] = rnd.choice((0, 0, 0, 8, -16)) if rec["corpse"] else 0
        rec["player"] = None
        if rnd.random() < 0.3:
            rec["player"] = (((x + int(40 * math.cos(ang))) << 16) + rnd.randrange(1 << 16),
                             ((y + int(40 * math.sin(ang))) << 16) + rnd.randrange(1 << 16), int(rnd.random() < 0.3))
        rec["other"] = None
        if kind == "crowd" or rnd.random() < 0.15:
            j = rnd.choice([a for a in act if a != rec["m"]])
            d = rnd.choice((45, 52, 60))
            rec["other"] = (j, x + int(d * math.cos(ang)), y + int(d * math.sin(ang)), rnd.choice((1, 1, 0)))
        rec["doors"] = [rnd.choice((0, 0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order]
        rec["lifts"] = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        out.append(rec)
    return out


def _player_records(c):
    import math
    w = c.w
    rnd = random.Random(0x4B50)
    ws = w.ws
    act = [m for m in range(c.n) if ws.mon_active[m]]
    P = w.pickup_things
    walks = [(tr[2], tr[3], tr[4], tr[1]) for tr in list(w.walk_triggers) + list(w.lift_walk)]
    out = []
    for r in range(N_PLAYER):
        kind = rnd.choice(("open", "open", "item", "drop", "drop", "mon", "walk", "walk", "dead"))
        rec = {"kind": kind, "mons": {}, "present": {}, "drop": None, "dead": kind == "dead" or rnd.random() < 0.1}
        x, y = rnd.choice(c.spots)
        ang = rnd.uniform(0, 2 * math.pi)
        if kind == "item":
            i = rnd.randrange(len(P))
            rec["present"][i] = 1
            d = rnd.randint(20, 60)
            x, y = P[i].x - int(d * math.cos(ang)), P[i].y - int(d * math.sin(ang))
        elif kind == "drop":
            k = rnd.choice([k_ for k_, m_ in enumerate(c.drop) if ws.mon_active[m_]])   # a monster of this skill
            d = rnd.randint(24, 60)
            dx_, dy_ = rnd.choice(c.spots)
            rec["drop"] = (k, c.drop[k], dx_, dy_, dx_ + rnd.choice((-1, 1)) * rnd.randint(80, 200),
                           dy_ + rnd.choice((-1, 1)) * rnd.randint(80, 200))
            x, y = dx_ - int(d * math.cos(ang)), dy_ - int(d * math.sin(ang))
        elif kind == "mon":
            m = rnd.choice(act)
            d = rnd.randint(40, 70)
            rec["mons"][m] = (x + int(d * math.cos(ang)), y + int(d * math.sin(ang)), rnd.choice((1, 1, 0)))
        elif kind == "walk":
            coord, lo, hi, axis = rnd.choice(walks)
            t = rnd.randint(lo, hi)
            side = rnd.choice((-1, 1))
            x, y = ((coord + side * rnd.randint(3, 10), t) if axis == "x" else (t, coord + side * rnd.randint(3, 10)))
            ang = (0 if side < 0 else math.pi) if axis == "x" else (math.pi / 2 if side < 0 else -math.pi / 2)
        rec["pos"] = ((x << 16) + rnd.randrange(1 << 16), (y << 16) + rnd.randrange(1 << 16))
        mag = rnd.choice((3 * U, 8 * U, 15 * U, 15 * U + 3, 20 * U, 30 * U, 40 * U, 0x4001, 0x1000, 0xFFF,
                          rnd.randint(1, 35 * U)))
        if kind == "walk":
            mag = rnd.randint(12 * U, 25 * U)
        mx, my = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        if rnd.random() < 0.15:
            mx, my = (mx, 0) if rnd.random() < 0.5 else (0, my)
        if mx == 0 and my == 0:
            my = -1
        rec["mom"] = (mx, my)
        rec["hp"] = 0 if rec["dead"] else rnd.choice((50, 100, 150))
        rec["doors"] = [rnd.choice((0, 0, rnd.randrange(w.door_nstates[si]))) for si in w.door_order]
        rec["lifts"] = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        out.append(rec)
    return out


def _records(c):
    """the monster records and the player records, interleaved"""
    a, b = _mon_records(c), _player_records(c)
    out = []
    for k in range(max(len(a), len(b))):
        if k < len(a):
            out.append(("mon", a[k]))
        if k < len(b):
            out.append(("player", b[k]))
    # APPENDED (so every line above is unchanged): momenta exactly ON the stop's and the corpse rule's edges, from
    # open spots -- |mom| == STOPSPEED is not stopped (strict <), |mom| == FRACUNIT/4 is not "more than"
    edges = [(0x1000, 0), (-0x1000, 3), (0, 0x1000), (5, -0x1000), (0xFFF, -0xFFF), (-0xFFF, 0),
             (0x4000, 0), (-0x4001, 0), (0x1000, 0x1000)]
    rnd = random.Random(0xED6E)
    act = [m for m in range(c.n) if c.w.ws.mon_active[m]]
    w = c.w
    for k, mom in enumerate(edges * 2):
        x, y = rnd.choice(c.spots)
        doors = [0] * len(w.door_order)
        lifts = [0] * len(w.lift_order)
        if k % 2 == 0:
            out.append(("mon", {"m": rnd.choice(act), "pos": (x, y, 0x8000, 0x8000), "mom": mom,
                                "corpse": k % 4 == 0, "solid": 1, "dz": 8 if k % 4 == 0 else 0, "player": None,
                                "other": None, "doors": doors, "lifts": lifts}))
        else:
            out.append(("player", {"kind": "edge", "mons": {}, "present": {}, "drop": None, "dead": k % 3 == 0,
                                   "pos": ((x << 16) + 0x8000, (y << 16) + 0x8000), "mom": mom,
                                   "hp": 0 if k % 3 == 0 else 100, "doors": doors, "lifts": lifts}))
    return out


def _scene(w, rec):
    ws = w.ws
    for d, v in enumerate(rec["doors"]):
        ws.d_state[d] = v
    for k, v in enumerate(rec["lifts"]):
        ws.l_state[k] = v
    w._door_phase_scene()
    for k in range(len(w.lift_order)):
        ws.l_req[k] = 0
    for d in range(len(w.door_order)):
        ws.d_monreq[d] = 0


def _apply_mon(c, rec):
    """the record into the model (before the move): -> the slots it put somewhere"""
    w, ws = c.w, c.w.ws
    _scene(w, rec)
    m = rec["m"]
    x, y, fx, fy = rec["pos"]
    w.teleport_monster(m, x, y)
    ws.mon_fx[m], ws.mon_fy[m] = fx, fy
    ws.mon_floorz[m] += rec["dz"]
    ws.mon_momx[m], ws.mon_momy[m] = rec["mom"]
    ws.mon_shootable[m] = int(not rec["corpse"])
    ws.mon_health[m] = 0 if rec["corpse"] else w.mon_info[m].spawnhealth
    ws.mon_solid[m] = rec["solid"]
    if rec["player"]:
        ws.px, ws.py, dead = rec["player"]
        ws.p_dead, ws.p_health = dead, 0 if dead else 100
    else:
        ws.px, ws.py, ws.p_dead, ws.p_health = -(5000 << 16), -(5000 << 16), 0, 100
    moved = [m]
    if rec["other"]:
        j, ox, oy, sol = rec["other"]
        w.teleport_monster(j, ox, oy)
        ws.mon_solid[j] = sol
        moved.append(j)
    return moved


def _apply_player(c, rec):
    w, ws = c.w, c.w.ws
    _scene(w, rec)
    ws.px, ws.py = rec["pos"]
    ws.p_momx, ws.p_momy = rec["mom"]
    ws.p_dead, ws.p_health = int(rec["dead"]), rec["hp"]
    moved = []
    for m, (x, y, sol) in rec["mons"].items():
        w.teleport_monster(m, x, y)
        ws.mon_solid[m] = sol
        moved.append(m)
    for i, v in rec["present"].items():
        ws.pickup_taken[i] = 1 - v
    if rec["drop"]:
        k, m, dx, dy, cx, cy = rec["drop"]
        w.teleport_monster(m, cx, cy)
        ws.mon_solid[m], ws.mon_shootable[m], ws.mon_health[m] = 0, 0, 0
        ws.mon_drop[m] = 1
        ws.drop_x[m], ws.drop_y[m] = dx, dy
        moved.append(m)
    return moved


def _mon_row(c, m):
    w, ws = c.w, c.w.ws
    s = "%08x%08x%04x%04x%04x%04x%04x%03x%02x" % (
        ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_fx[m], ws.mon_fy[m], ws.mon_x[m] & 0xFFFF,
        ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF, ws.mon_leaf[m], w._mon_sector(m))
    s += "%02x" % sum(1 for j in range(c.n) if ws.mon_momx[j] or ws.mon_momy[j])
    return s + "".join("%x" % ws.l_req[k] for k in range(len(w.lift_order)))


def _player_row(c):
    w, ws = c.w, c.w.ws
    s = "%08x%08x%08x%08x%03x%03x%03x%02x" % (ws.px & M32, ws.py & M32, ws.p_momx & M32, ws.p_momy & M32,
                                              ws.p_health & 0xFFF, ws.p_ammo[gd.AM_CLIP], ws.p_ammo[gd.AM_SHELL],
                                              ws.p_bonuscount)
    s += "".join("%x" % (1 - ws.pickup_taken[i]) for i in range(len(w.pickup_things)))
    s += "".join("%x" % ws.mon_drop[m] for m in c.drop)
    s += "".join("%x" % ws.w_fired[k] for k in range(len(w.walk_triggers)))
    s += "".join("%x" % ws.d_monreq[d] for d in range(len(w.door_order)))
    return s + "".join("%x" % ws.l_req[k] for k in range(len(w.lift_order)))


def _lists(c):
    """every leaf's list, restricted to the monster rows (the fj's rows = the model's slots)"""
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks if k < c.n))
                   for leaf, ks in sorted(c.w.leaf_lists().items()) if any(k < c.n for k in ks))


MOVE_MUTANTS = {
    "no_friction": ("  kq_fr:\n", "  kq_fr:\n    ;kq_xout\n"),    # kb_xy's exit (kq_out is kb_go's since the merge)
    "stopspeed": ("    hex.cmp 8, kb_t, kb_c, kq_sy, kq_fr, kq_fr\n", "    hex.cmp 8, kb_t, kb_c, kq_sy, kq_sy, kq_fr\n"),
    "no_clamp": ("  kq_cx_hi:\n    hex.mov 8, kb_vx, kb_c\n", "  kq_cx_hi:\n"),
    "no_halve": ("    hex.scmp 8, kb_xm, kb_c, kq_hy, kq_hy, kq_half\n",
                 "    hex.scmp 8, kb_xm, kb_c, kq_hy, kq_hy, kq_hy\n"),
    "half_shift": ("  kq_tx_i:\n    hex.inc 8, kb_cx\n", "  kq_tx_i:\n"),
    "wall_keeps": ("    hex.zero 8, kb_vx\n    hex.zero 8, kb_vy\n  kq_t2:\n", "  kq_t2:\n"),
    "frac_drop": None,                                    # the stubs' fraction copy-out (below)
    "no_retest": ("    hex.cmp 4, kb_cx + 4*dw, mm_x, kq_mt, kq_msx, kq_mt\n",
                  "    hex.cmp 4, kb_cx + 4*dw, mm_x, kq_msx, kq_msx, kq_msx\n"),
    "corpse_live": ("    hex.if1 1, kb_dead, kq_mok\n", ""),
    "corpse_rule": ("    hex.if0 1, kb_dead, kq_stop\n", "    ;kq_stop\n"),
    "drop_follows": None,                                 # the pickup without drop_rt (below)
}


def _move_program(c, mut=None):
    import re
    from doomfj import hurtcode as H
    from doomfj import lootcode as L
    from doomfj import monstermove as MM
    from doomfj import weaponcode as WC
    from doomfj.collision import (COLLISION_STATE_DECLS, MON_CELL_DECLS, cell_lists, collision_cells_fj,
                                  generate_point_location_fj, line_rows, monster_cells_fj, mover_line_openings,
                                  point_location_decls)
    from doomfj.doorcode import walkover_lines
    from doomfj.movercode import lift_walk_lines
    from doomfj.reference_model import ML_BLOCKING, PLAYER_RADIUS
    from doomfj.things import LEAF_LINK_DECLS, byte_array_decl, spawn_leaf_lists
    from doomfj.wall_renderer import DOOR_QUANT
    w, n = c.w, c.n
    ws = w.ws
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    # the player's cells: the emitter's construction (test_player_move_fj's)
    rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING, secs_open=kw["secs_open"],
                     door_line_ids=kw["door_line_ids"])
    obs = mover_line_openings(w.lds, w.sds, w.secs, kw["msecs"])
    movers = {li: (kw["mcell"][m_], obs[li]) for li in obs
              for m_ in [next(x for x in (w.sds[w.lds[li].front].sector, w.sds[w.lds[li].back].sector)
                              if x in kw["msecs"])]}
    lists, things = L.player_cell_things(w, cell_lists(rows, PLAYER_RADIUS))
    pcells, proot = collision_cells_fj("e1m1", rows, lists, doors=kw["doors"], movers=movers, things=things,
                                       thing_test=L.THING_TEST16)
    # the monsters' cells (the chase harness's)
    mcells, mroot = monster_cells_fj("e1m1", w.lds, w.cmap.vertexes, w.secs, w.sds, things=c.things, **kw)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    lift_trigs = [(w.lift_order.index(tr[0]),) + tuple(tr[1:]) for tr in w.lift_walk]
    after = (walkover_lines(w.walk_triggers, list(w.door_order), 16, prefix="kbwo")
             + lift_walk_lines(w.lift_walk, list(w.lift_order), 16, prefix="kblw"))
    knock = "\n".join(KC.cell_lines(proot) + KC.xy_lines() + KC.ptry_lines(after) + KC.mtry_lines(mroot, lift_trigs)
                      + KC.move_lines(KC.slots_of(w, list(range(n))))) + "\n"
    if mut == "frac_drop":
        knock, k = re.subn(r"    hex\.mov 4, mf[xy] \+ \d+\*dw, kb_p[xy]\n", "", knock)
        assert k == 2 * n, k
    elif mut and MOVE_MUTANTS[mut]:
        old, new = MOVE_MUTANTS[mut]
        assert knock.count(old) == 1, (mut, knock.count(old))
        knock = knock.replace(old, new)
    pick = L.pickup_lines(w, c.slots, list(range(n)), drop_rt=None if mut == "drop_follows" else c.drop_rt)
    pb = L.pb_mon_lines(w, list(range(n)))
    things_leaf = MM.things_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], solid="mon_solid", hurt=True)
    stubs = (["rt_unlink:", "    stl.fret rtu_ret"]
             + sum((["drop_take%d:" % k, "    hex.set 1, mdrop + %d*dw, 2" % k, "    hex.dec 2, dr_live",
                     "    stl.fret drt_ret"] for k in range(len(c.drop))), [])
             + ["pw_link:", "    sim.leaf_link pw_t, pw_leaf", "    stl.fret pw_lkret",
                "pw_unlink:", "    sim.leaf_unlink pw_t, pw_leaf", "    stl.fret pw_ulret"])
    splice = ["kbp_leaf:"] + KC.player_move_lines() + ["    stl.fret kbp_ret"]   # the splice's very lines
    code = knock + "\n".join(splice + pick + pb + things_leaf + seed + stubs) + "\n" + pcells + mcells
    # the cells' start: the model's level start (the records then poke what they set)
    nleaf = len(w.cmap.subsectors)
    head, nxt = spawn_leaf_lists([ws.mon_leaf[m] for m in range(n)] + [0] * (c.nrows - n), nleaf,
                                 present=[bool(ws.mon_active[m]) for m in range(n)] + [False] * (c.nrows - n))
    thpos = [((ws.mon_x[m] << 16) & M32) | (((ws.mon_y[m] << 16) & M32) << 32) for m in range(n)]
    vis = [1] * (c.slots["nvis"] + c.slots["nextra"])
    for i, s in enumerate(c.slots["slot"]):
        vis[s] = 1 - ws.pickup_taken[i]
    wstart = WC.level_start(w.mw, "E1M1")
    states, frames = WC.weapon_states(), WC.overlay_frames()
    nd, nl = len(w.door_order), len(w.lift_order)

    def vec(name, nib, vals):
        return "%s: hex.vec %d, %d" % (name, nib * len(vals), sum((v & (16 ** nib - 1)) << (4 * nib * i)
                                                                  for i, v in enumerate(vals)))
    decls = (KC.decls(n) + L.loot_decls(L.level_start(w)) + H.hurt_decls(H.level_start(w))
             + WC.weapon_decls(wstart, states, frames) + COLLISION_STATE_DECLS + MON_CELL_DECLS
             + point_location_decls() + MM.monster_seed_decls() + MM.P32B_CONTEXT + LEAF_LINK_DECLS
             + ["pcard: hex.vec 1", "thvis:"] + ["    hex.vec 2, %d" % v for v in vis]
             + ["mdrop: hex.vec %d" % len(c.drop), "dr_live: hex.vec 2", "rtu_t: hex.vec w/4",
                "rtu_leaf: hex.vec w/4", "rtu_ret: hex.vec w/4", "drt_ret: hex.vec w/4",
                "viewx: hex.vec 8", "viewy: hex.vec 8",
                "thpos_rt: hex.vec %d, %d" % (16 * c.nrows, sum(v << (64 * t) for t, v in enumerate(thpos))),
                "thss_rt: hex.vec %d, %d" % (16 * c.nrows, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * c.nrows),
                vec("mon_solid", 1, [ws.mon_solid[m] for m in range(n)]),
                vec("mon_active", 1, [ws.mon_active[m] for m in range(n)]),
                vec("mon_shootable", 1, [ws.mon_shootable[m] for m in range(n)]),
                vec("mon_floorz", 4, [ws.mon_floorz[m] for m in range(n)]),
                vec("msec", 2, [w._mon_sector(m) for m in range(n)]),
                vec("bar_solid", 1, [ws.bar_solid[b] for b in range(len(w.barrel_things))]),
                "mc_don: hex.vec %d" % max(1, len(c.var)),
                "dstate: hex.vec %d" % nd, "ddir: hex.vec %d" % nd, "dreq: hex.vec %d" % nd,
                "wfired: hex.vec %d" % max(1, len(w.walk_triggers)),
                "lstate: hex.vec %d" % max(1, nl), "lreq: hex.vec %d" % max(1, nl), "fswitch: hex.vec 1",
                "pw_t: hex.vec w/4", "pw_leaf: hex.vec w/4", "pw_lkret: hex.vec w/4", "pw_ulret: hex.vec w/4",
                "dump_ret: hex.vec w/4", "dl_leaf: hex.vec 3", "kbp_ret: hex.vec w/4", "dbox: hex.vec 8"])
    tables = (L.tables_fj(w) + [generate_point_location_fj(w.cmap),
                                generate_dispatch_table_fj("lfsec", list(w.leaf_sector), index_nibbles=3,
                                                           result_nibbles=2)])
    return decls, code, tables


def _place(c, m) -> list:
    """the model's slot m as it stands now, into the fj: out of its old list (the row's leaf), the row, into its
    new list, its sector, floor, flags"""
    w, ws = c.w, c.w.ws
    leaf = ws.mon_leaf[m]
    assert ws.mon_active[m], "only a slot of this skill is in a list"
    return ["hex.set w/4, pw_t, %d" % m, "hex.zero w/4, pw_leaf", "hex.mov 3, pw_leaf, thss_rt + %d*dw" % (16 * m),
            "stl.fcall pw_unlink, pw_ulret",
            "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, ws.mon_x[m] & 0xFFFF),
            "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, ws.mon_y[m] & 0xFFFF),
            "hex.set 3, thss_rt + %d*dw, %d" % (16 * m, leaf), "hex.set w/4, pw_leaf, %d" % leaf,
            "stl.fcall pw_link, pw_lkret",
            "hex.set 2, msec + %d*dw, %d" % (2 * m, w._mon_sector(m)),
            "hex.set 4, mon_floorz + %d*dw, %d" % (4 * m, ws.mon_floorz[m] & 0xFFFF),
            "hex.set 1, mon_solid + %d*dw, %d" % (m, ws.mon_solid[m]),
            "hex.set 1, mon_shootable + %d*dw, %d" % (m, ws.mon_shootable[m]),
            "hex.set 4, mfx + %d*dw, %d" % (4 * m, ws.mon_fx[m]), "hex.set 4, mfy + %d*dw, %d" % (4 * m, ws.mon_fy[m]),
            "hex.set 8, mkx + %d*dw, %d" % (8 * m, ws.mon_momx[m] & M32),
            "hex.set 8, mky + %d*dw, %d" % (8 * m, ws.mon_momy[m] & M32)]


def _scene_lines(c, rec) -> list:
    w = c.w
    return (["hex.set 1, dstate + %d*dw, %d" % (d, v) for d, v in enumerate(rec["doors"])]
            + ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(rec["lifts"])]
            + ["hex.zero %d, lreq" % max(1, len(w.lift_order)), "hex.zero %d, dreq" % len(w.door_order)])


def _player_lines(c) -> list:
    ws = c.w.ws
    return ["hex.set 8, viewx, %d" % (ws.px & M32), "hex.set 8, viewy, %d" % (ws.py & M32),
            "hex.set 8, p_kmx, %d" % (ws.p_momx & M32), "hex.set 8, p_kmy, %d" % (ws.p_momy & M32),
            "hex.set 1, p_dead, %d" % ws.p_dead, "hex.set 3, p_hp, %d" % (ws.p_health & 0xFFF)]


def _move_build(tmp_path, name, mut=None):
    c = Mv()                                        # a fresh model: the program starts from its level start
    recs = _records(c)
    decls, code, tables = _move_program(c, mut)
    w, n = c.w, c.n
    want = []
    body = ["stl.startup_and_init_all"]
    for kind, rec in recs:
        body += _scene_lines(c, rec)
        ev = TicEvents(0)
        ws = w.ws
        if kind == "mon":
            moved = _apply_mon(c, rec)
            body += sum((_place(c, j) for j in moved), []) + _player_lines(c)
            body += ["hex.set 2, kb_live, %d" % sum(1 for j in range(n) if ws.mon_momx[j] or ws.mon_momy[j])]
            m = rec["m"]
            w._monster_knock_move(m, ev)
            body += ["stl.fcall kbs%d, kbs_ret" % m,
                     "hex.print_as_digit 8, mkx + %d*dw, 0" % (8 * m), "hex.print_as_digit 8, mky + %d*dw, 0" % (8 * m),
                     "hex.print_as_digit 4, mfx + %d*dw, 0" % (4 * m), "hex.print_as_digit 4, mfy + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 4),
                     "hex.print_as_digit 4, thpos_rt + %d*dw, 0" % (16 * m + 12),
                     "hex.print_as_digit 4, mon_floorz + %d*dw, 0" % (4 * m),
                     "hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * m),
                     "hex.print_as_digit 2, msec + %d*dw, 0" % (2 * m), "hex.print_as_digit 2, kb_live, 0"]
            body += ["hex.print_as_digit 1, lreq + %d*dw, 0" % k for k in range(len(w.lift_order))]
            want.append(_mon_row(c, m))
            ws.mon_momx[m] = ws.mon_momy[m] = 0              # both sides: the next record starts still
            body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)]
        else:
            moved = _apply_player(c, rec)
            body += sum((_place(c, j) for j in moved), []) + _player_lines(c)
            for i, v in rec["present"].items():
                body.append("hex.set 2, thvis + %d*2*dw, %d" % (c.slots["slot"][i], v))
            if rec["drop"]:
                k, m, dx, dy, cx, cy = rec["drop"]
                d = c.drop_rt[k]
                body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * d + 4, dx & 0xFFFF),
                         "hex.set 4, thpos_rt + %d*dw, %d" % (16 * d + 12, dy & 0xFFFF),
                         "hex.set 3, thss_rt + %d*dw, %d" % (16 * d, w.drop_leaf(m)),
                         "hex.set 1, mdrop + %d*dw, 1" % k]
            body += ["hex.set 2, dr_live, %d" % sum(1 for m in c.drop if ws.mon_drop[m] == 1)]
            w._player_knock_move(ev)
            body += ["stl.fcall kbp_leaf, kbp_ret"]
            body += ["hex.print_as_digit 8, viewx, 0", "hex.print_as_digit 8, viewy, 0",
                     "hex.print_as_digit 8, p_kmx, 0", "hex.print_as_digit 8, p_kmy, 0",
                     "hex.print_as_digit 3, p_hp, 0", "hex.print_as_digit 3, am_clip, 0",
                     "hex.print_as_digit 3, am_shell, 0", "hex.print_as_digit 2, p_bc, 0"]
            body += ["hex.print_as_digit 1, thvis + %d*2*dw, 0" % c.slots["slot"][i] for i in range(len(w.pickup_things))]
            body += ["hex.print_as_digit 1, mdrop + %d*dw, 0" % k for k in range(len(c.drop))]
            body += ["hex.print_as_digit 1, wfired + %d*dw, 0" % k for k in range(len(w.walk_triggers))]
            body += ["hex.print_as_digit 1, dreq + %d*dw, 0" % d for d in range(len(w.door_order))]
            body += ["hex.print_as_digit 1, lreq + %d*dw, 0" % k for k in range(len(w.lift_order))]
            want.append(_player_row(c))
        body += ["stl.output 10"]
    body += ["stl.fcall ll_dump, dump_ret", "stl.loop"]
    want.append(_lists(c))
    dump = ["ll_dump:"]
    for leaf in range(len(w.cmap.subsectors)):
        dump += ["    hex.set w/4, ll_base, sshead", "    hex.set w/4, ll_idx, %d" % leaf,
                 "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
                 "    hex.if0 2, ll_v, dl%d_end" % leaf,
                 "  dl%d_loop:" % leaf,
                 "    hex.dec 2, ll_v",
                 "    hex.if_flags ll_v + 1*dw, 0xFFF0, dl%d_mon, dl%d_skip" % (leaf, leaf),   # a monster row (< 0x40)
                 "  dl%d_mon:" % leaf,
                 "    hex.if1 1, dl_have, dl%d_pr" % leaf,
                 "    hex.set 3, dl_leaf, %d" % leaf, "    hex.print_as_digit 3, dl_leaf, 0", "    stl.output 58",
                 "    hex.set 1, dl_have, 1", "    ;dl%d_pv" % leaf,
                 "  dl%d_pr:" % leaf, "    stl.output 44",
                 "  dl%d_pv:" % leaf, "    hex.print_as_digit 2, ll_v, 0",
                 "  dl%d_skip:" % leaf,
                 "    hex.set w/4, ll_base, thnext", "    hex.zero w/4, ll_idx", "    hex.mov 2, ll_idx, ll_v",
                 "    hex.ptr_index ll_p, ll_base, ll_idx", "    hex.read_byte ll_v, ll_p",
                 "    hex.if0 2, ll_v, dl%d_end" % leaf, "    ;dl%d_loop" % leaf,
                 "  dl%d_end:" % leaf, "    hex.zero 1, dl_have"]
    dump += ["    stl.output 10", "    stl.fret dump_ret"]
    prog = "\n".join(body + decls + ["dl_have: hex.vec 1"] + dump + [code] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, ("\n".join(want) + "\n").encode()


def _move_run(tmp_path, name, mut=None) -> bool:
    srcs, want = _move_build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_move_records_exercise_every_path():
    """the model over the records: two tries (halved) and one, refused tries (a wall, a thing, a ledge for a live
    monster) and accepted, the clamp, the stop exactly at STOPSPEED and the friction, a monster's untested
    fraction-only move and an integer re-test, a corpse sliding off a ledge a live monster may not leave and a corpse
    keeping its momentum (the corpse rule), relinks, lifts crossed, items and drops taken (a drop away from its
    corpse), a walk-over line fired, a dead player sliding"""
    c = Mv()
    w = c.w
    seen = dict(two=0, one=0, refused=0, accepted=0, clamp=0, stop=0, friction=0, untested=0, retest=0,
                corpse_ledge=0, corpse_rule=0, relink=0, lift=0, item=0, drop=0, walk=0, dead=0, pblock=0, edge=0)
    for kind, rec in _records(c):
        ev = TicEvents(0)
        ws = w.ws
        if kind == "mon":
            _apply_mon(c, rec)
            m = rec["m"]
            x0, y0, leaf0 = ws.mon_x[m], ws.mon_y[m], ws.mon_leaf[m]
            calls = []
            real = w.try_move_monster
            w.try_move_monster = lambda mm, nx, ny, corpse=False: calls.append(corpse) or real(mm, nx, ny, corpse)
            mom = rec["mom"]
            try:
                w._monster_knock_move(m, ev)
            finally:
                del w.try_move_monster
            tries = [ok for t, ok in ev.knocks]
            seen["two" if len(tries) == 2 else "one"] += 1
            seen["refused"] += tries.count(False)
            seen["accepted"] += tries.count(True)
            seen["clamp"] += max(abs(mom[0]), abs(mom[1])) > gd.MAXMOVE
            seen["untested"] += len(calls) < len(tries)
            seen["retest"] += len(calls) > 0
            seen["corpse_ledge"] += rec["corpse"] and bool(calls) and all(tries) and (
                w.try_move_lines(m, ws.mon_x[m], ws.mon_y[m])[0] == "dropoff")
            seen["corpse_rule"] += rec["corpse"] and (ws.mon_momx[m], ws.mon_momy[m]) != (0, 0) and \
                w._knock_slides(("mon", m), ws.mon_momx[m], ws.mon_momy[m])
            seen["relink"] += ws.mon_leaf[m] != leaf0
            seen["lift"] += any(ws.l_req[k] for k in range(len(w.lift_order)))
            v = (ws.mon_momx[m], ws.mon_momy[m])
            seen["stop"] += all(tries) and v == (0, 0)
            seen["edge"] += all(tries) and abs(mom[0]) == gd.STOPSPEED and abs(mom[1]) < gd.STOPSPEED and v != (0, 0)
            seen["friction"] += v != (0, 0)
            ws.mon_momx[m] = ws.mon_momy[m] = 0
        else:
            _apply_player(c, rec)
            bt, bd = list(ws.pickup_taken), [ws.mon_drop[m] for m in c.drop]
            bw = list(ws.w_fired)
            w._player_knock_move(ev)
            tries = [ok for t, ok in ev.knocks]
            seen["refused"] += tries.count(False)
            seen["item"] += any(ws.pickup_taken[i] and not bt[i] for i in range(len(bt)))
            seen["drop"] += any(ws.mon_drop[m] == 2 and b == 1 for m, b in zip(c.drop, bd))
            seen["walk"] += ws.w_fired != bw or any(ws.l_req[k] for k in range(len(w.lift_order)))
            seen["dead"] += rec["dead"] and any(tries)
            seen["pblock"] += ev.player_blocked > 0
    want = dict(two=30, one=40, refused=60, accepted=90, clamp=10, stop=20, friction=50, untested=10, retest=80,
                corpse_ledge=3, corpse_rule=3, relink=8, lift=2, item=5, drop=5, walk=2, dead=5, pblock=3, edge=1)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)


def test_the_moves_follow_the_model(tmp_path):
    assert _move_run(tmp_path, "kmove"), "the fj knock moves parted from the model's _xy_move"


@pytest.mark.parametrize("mut", sorted(MOVE_MUTANTS))
def test_control_a_broken_move_is_caught(tmp_path, mut):
    assert not _move_run(tmp_path, "kmove_" + mut, mut), "%s passed: the comparison is vacuous" % mut


# ================================================================================================================
# THE RESTART
# ================================================================================================================
def test_the_restart_zeroes_every_knock_cell(tmp_path):
    """knockcode.restart_lines over dirty cells: every persisted cell (PERSIST, at its declared width) reads 0 after,
    the model's level start for p_momx .. proj_z (World._restart). R9: a line dropped leaves its dirt"""
    w = _world()
    n = w.layout.nmon
    decls = KC.persisted_decls(n)
    widths = {d.split(":")[0]: int(d.split("hex.vec ")[1]) for d in decls}
    assert set(widths) == set(KC.PERSIST)
    snap = w.level_start(gd.SK_HARD)
    for cell, field in KC.MODEL_FIELD.items():
        v = getattr(snap, field)
        assert not any(v) if isinstance(v, list) else v == 0, field

    def run(lines, name):
        body = ["stl.startup_and_init_all"]
        body += ["hex.set %d, %s, %d" % (wd, cl, (1 << (4 * wd)) - 1 - 5) for cl, wd in widths.items()]
        body += ["stl.fcall rs_leaf, rs_ret"] + ["hex.print_as_digit %d, %s, 0" % (wd, cl) for cl, wd in widths.items()]
        body += ["stl.output 10", "stl.loop"]
        prog = "\n".join(body + decls + ["rs_ret: hex.vec w/4", "rs_leaf:"] + lines + ["    stl.fret rs_ret"]) + "\n"
        p = tmp_path / ("%s.fj" % name)
        p.write_text(prog, encoding="utf-8")
        consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
        want = ("".join("0" * wd for wd in widths.values()) + "\n").encode()
        return fj.assemble_and_run_test_output([consts.resolve(), p.resolve()], b"", want, memory_width=W,
                                               warning_as_errors=True, should_raise_assertion_error=False)
    lines = KC.restart_lines(n)
    assert run(lines, "krestart")
    assert not run([ln for ln in lines if "kb_live" not in ln], "krestart_r9")
