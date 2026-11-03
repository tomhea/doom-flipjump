"""M8 C5 -- THE MONSTER-ONLY TELEPORTS (126 WR, 125 W1) RUN in fj against the MODEL, on the real lines of E1M4 (a 126
among fourteen 97s), E1M5 (a 126 whose destination is hard-only) and E1M7 (four W1 125s end to end, three 97s): the
emitter's own text (doomfj.teleportcode.monster_lines / player_lines, slot_back_lines, stomp_leaf_lines) fed records,
read back, and compared with the model's own `world._teleport_monster` / `combat._teleport_player` on that map's
World (tests/fixtures/map_variants.episode_wad: the thing types gamedata lacks yet left out).

Each monster record carries the game's skill (`g_skill`, the SKILLS index) and, on E1M7, the four W1 latches
(`tp_w1`) going in; the program prints the move, the write-back, the stomp's calls, the fogs and the latches coming
out. The records: every monster-only line (and one 97) crossed both ways at its middle and its extent's strict ends,
short of it, from ON it, with a shootable monster on the destination or not, on each skill, with each latch armed or
dead; then random moves around each line.

The player (`player_lines`): the monster-only lines are not in his text at all -- his records cross them and a 97, and
the model agrees (he crosses a 126 / 125 and stays). E1M5 has no player line: `player_lines` is empty.

R9 (MUTANTS), each a real edit that must part from the model: the W1 latch never tested (a dead 125 fires again), the
latch set only by a front crossing (the back crossing leaves it armed), the latch never set, the skill test removed
(E1M5's 126 fires on medium), the skill test inverted, a 126 put in the player's text.
"""
import random
import struct
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import teleportcode as T
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile
from doomfj.wall_renderer import SKILLS
from doomfj.world import World
from tests.fixtures.map_variants import episode_wad
from tests.fj.test_teleport_fj import (FOG_CELLS, NH, _check, _common_decls, _dm_stub, _fog_want, _mons_feed,
                                       _mons_in, _mutate, _pr, _run, _tf_stub)

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
M32 = 0xFFFFFFFF
# per map: the lines the records cross (the monster-only ones and one 97)
LINES = {"E1M4": (1892, 1933), "E1M5": (633,), "E1M7": (3755, 3759, 3769, 3773, 94)}


class Ctx:
    def __init__(self, mapname):
        self.map = mapname
        self.rm = ReferenceModel(Config())
        self.w = World(episode_wad(WadFile.from_path(str(ART)), mapname), mapname, player="final", monsters="final",
                       rm=self.rm)
        w = self.w
        self.tels = w.teleports
        self.nonce = len(w.tele_once)
        self.ks = [k for k, t in enumerate(self.tels) if t.line in LINES[mapname]]
        r20 = [m for m in range(w.layout.nmon) if w.mon_radius[m] == 20]
        r30 = [m for m in range(w.layout.nmon) if w.mon_radius[m] == 30]
        self.hslots = [r20[0], r30[0], r20[1]]
        self.movers = {20: r20[2], 30: r30[1]}
        self.rows = [(j, w.mon_radius[m]) for j, m in enumerate(self.hslots)]
        self.fogs = []
        w._spawn_fx = lambda kind, x16, y16, dmg, melee, ev: self.fogs.append((kind, x16 >> 16, y16 >> 16))

    def place(self, mons, alive=True):
        ws = self.w.ws
        for m in range(self.w.layout.nmon):
            ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 0
        for (x, y, sh), m in zip(mons, self.hslots):
            ws.mon_x[m], ws.mon_y[m] = x, y
            ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = sh
            ws.mon_health[m] = self.w.mon_info[m].spawnhealth
        for b in range(len(self.w.barrel_things)):
            ws.bar_state[b] = 0
        ws.p_dead = 0 if alive else 1
        ws.p_health = 100 if alive else 0


_CTX = {}


def ctx_of(mapname):
    if mapname not in _CTX:
        _CTX[mapname] = Ctx(mapname)
    return _CTX[mapname]


def _pos(tel, c16, o16):
    return (c16, o16) if tel.axis == "x" else (o16, c16)


def _records(ctx, radius, seed, n_rand=30):
    """[(tel index, old16, new16, mons, alive)] around each chosen line"""
    rng = random.Random(seed)
    out = []
    for k in ctx.ks:
        tel = ctx.tels[k]
        L = tel.coord << 16
        ends = [((tel.lo - radius) << 16) + d for d in (-1, 0, 1)] + [((tel.hi + radius) << 16) + d for d in (-1, 0, 1)]
        mids = [((tel.lo + tel.hi) // 2) << 16]
        cs = [L - (6 << 16), L, L + (6 << 16)]
        for o in ends + mids:
            for co in cs:
                for cn in cs:
                    if co != cn:
                        out.append((k, _pos(tel, co, o), _pos(tel, cn, o), None, True))
        dx, dy = tel.dest
        mid = ((tel.lo + tel.hi) // 2) << 16
        for front in (True, False):
            co, cn = (L - (4 << 16), L + (4 << 16)) if (tel.front_le == front) else (L + (4 << 16), L - (4 << 16))
            for sh in (1, 0):
                mons = [(dx + 999, dy, 1)] * NH
                mons[0] = (dx + 5, dy - 3, sh)
                out.append((k, _pos(tel, co, mid), _pos(tel, cn, mid), mons, True))
                out.append((k, _pos(tel, co, mid), _pos(tel, cn, mid), None, bool(sh)))
        for _ in range(n_rand):
            o = rng.randint((tel.lo - radius - 8) << 16, (tel.hi + radius + 8) << 16)
            co, cn = L + rng.randint(-20 << 16, 20 << 16), L + rng.randint(-20 << 16, 20 << 16)
            out.append((k, _pos(tel, co, o + rng.randint(-1 << 16, 1 << 16)), _pos(tel, cn, o), None, True))
    return out


def _mons_of(ctx, rec):
    k, _o, _n, mons, _alive = rec
    if mons is None:
        dx, dy = ctx.tels[k].dest
        mons = [(dx + 500 + 100 * j, dy, 1) for j in range(NH)]
    return mons


# ---- a monster -----------------------------------------------------------------------------------------------------

def monster_program(ctx, *, knock_ctx=False, muts=(), tels=None):
    tels = ctx.tels if tels is None else tels
    n = max(1, ctx.nonce)
    lines = "\n".join(T.monster_lines(tels, prefix="tpq" if knock_ctx else "tpm", knock_ctx=knock_ctx))
    back = "\n".join(T.slot_back_lines(1, facing="mon_facing + 1*dw", knock=True, walk=not knock_ctx, tag="tpb"))
    stomp = "\n".join(T.stomp_leaf_lines(ctx.rows) + _dm_stub() + _tf_stub())
    latch_in = [ln for j in range(n) for ln in ("hex.input 1, rb", f"hex.mov 1, tp_w1 + {j}*dw, rb")]
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            f"hex.zero {NH}, kcount", "hex.zero 1, kerr", *[f"hex.zero {w_}, {c}" for c, w_ in FOG_CELLS],
            "hex.input 4, mm_ox16", "hex.input 4, mm_oy16", "hex.input 4, cpx", "hex.input 4, cpy",
            "hex.input 1, mm_r", "hex.input 1, rb", "hex.mov 1, mm_r30, rb",
            "hex.input 2, mm_nx", "hex.input 2, mm_ny", "hex.input 4, cp_floor", "hex.input 2, ptss",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rb", "hex.mov 1, p_dead, rb",
            "hex.input 1, rb", "hex.mov 1, mon_facing + 1*dw, rb",
            "hex.input 4, mkx + 8*dw", "hex.input 4, mky + 8*dw", "hex.input 2, mfx + 4*dw", "hex.input 2, mfy + 4*dw",
            "hex.input 4, kb_cx", "hex.input 4, kb_cy", "hex.input 4, kb_vx", "hex.input 4, kb_vy",
            "hex.input 1, rb", "hex.mov 1, g_skill, rb", *latch_in,
            *_mons_in(), lines, back]
    for reg, w_ in (("mm_nx", 4), ("mm_ny", 4), ("cp_floor", 8), ("ptss", 3), ("mon_facing + 1*dw", 1),
                    ("mkx + 8*dw", 8), ("mky + 8*dw", 8), ("mfx + 4*dw", 4), ("mfy + 4*dw", 4),
                    ("kb_cx", 8), ("kb_cy", 8), ("kb_vx", 8), ("kb_vy", 8), ("tp_hit", 1), ("kcount", NH),
                    ("kerr", 1), *FOG_CELLS, ("tp_w1", n)):
        body += _pr(reg, w_)
    decls = [d for d in _common_decls() if not d.startswith("tp_w1:")]
    moving = [t for t in tels if t.dest_moves]
    if moving:
        # M8 C5b: E1M7's 516 / 521 land on movers. The model's world is at the level start here, where each mover
        # destination's floor is its stored one: a stub `ms_seed_leaf` returning that by ptss (this harness has no
        # sim.fj for the real seed; tests/fj/test_teleport_mover_fj RUNS the real one at every mover state)
        w = ctx.w
        assert not any(w.ws.l_state) and not any(w.ws.f_switch), "the stub's floors are the level start's"
        stub = ["", "ms_seed_leaf:"]
        for j, t in enumerate(moving):
            assert w.secs_c[t.dest_sector].floor_h == t.dest_floor, t
            stub += [f"    hex.cmp 3, ptss, c5b_l{j}, c5b_n{j}, c5b_y{j}, c5b_n{j}",
                     f"  c5b_y{j}:", f"    hex.set 8, cp_seedf, {t.dest_floor & M32:#x}", "    stl.fret ms_seed_ret",
                     f"  c5b_n{j}:"]
            decls.append(f"c5b_l{j}: hex.vec 3, {t.dest_leaf:#x}")
        stomp += "\n".join(stub + ["    hex.set 8, cp_seedf, 0xDEADBEEF", "    stl.fret ms_seed_ret"])
        decls += ["cp_seedf: hex.vec 8", "ms_seed_ret: hex.vec w/4"]
    if not ctx.nonce:
        decls.append("tp_w1: hex.vec 1, 0")                          # read back as 0 (no W1 line on this map)
    body += [";loop", "done:", "stl.loop", stomp,
             "mm_ox16: hex.vec 8", "mm_oy16: hex.vec 8", "cpx: hex.vec 8", "cpy: hex.vec 8", "mm_r: hex.vec 2",
             "mm_r30: hex.vec 1", "mm_nx: hex.vec 4", "mm_ny: hex.vec 4", "cp_floor: hex.vec 8", "ptss: hex.vec w/4",
             "mon_facing: hex.vec 2", "mkx: hex.vec 16", "mky: hex.vec 16", "mfx: hex.vec 8", "mfy: hex.vec 8",
             "kb_cx: hex.vec 8", "kb_cy: hex.vec 8", "kb_vx: hex.vec 8", "kb_vy: hex.vec 8", "g_skill: hex.vec 1",
             *decls, *T.decls(tels)[:1 if ctx.nonce else 0]]
    return _mutate("\n".join(body), muts) + "\n"


def _monster_case(ctx, rec, radius, rng, knock_ctx):
    w, ws = ctx.w, ctx.w.ws
    k, old16, new16, _m, alive = rec
    m = ctx.movers[radius]
    mons = _mons_of(ctx, rec)
    old, new = (old16[0] >> 16, old16[1] >> 16), (new16[0] >> 16, new16[1] >> 16)
    floor, leaf, fa = rng.randint(-200, 300), rng.randrange(1104), rng.randrange(8)
    dest = ctx.tels[k].dest
    px, py = rng.choice([(dest[0] << 16, dest[1] << 16), (0, 0), (0, 0), (0, 0)])
    mom = [rng.randint(-(9 << 16), 9 << 16) for _ in range(2)]
    frac = [rng.getrandbits(16) for _ in range(2)]
    kb = [rng.getrandbits(32) for _ in range(4)]
    sk = rng.randrange(len(SKILLS))
    latches = [int(rng.random() < 0.3) for _ in range(ctx.nonce)]
    feed = (bytes([1]) + struct.pack("<IIII", (old[0] << 16) & M32, (old[1] << 16) & M32, (new[0] << 16) & M32,
                                     (new[1] << 16) & M32)
            + bytes([radius, int(radius == 30)]) + struct.pack("<HHIH", new[0] & 0xFFFF, new[1] & 0xFFFF,
                                                                 floor & M32, leaf)
            + struct.pack("<II", px & M32, py & M32) + bytes([0 if alive else 1, fa])
            + struct.pack("<IIHH", mom[0] & M32, mom[1] & M32, frac[0], frac[1])
            + struct.pack("<IIII", *kb) + bytes([sk] + (latches or [0])) + _mons_feed(mons))
    ctx.place(mons, alive)
    ws.px, ws.py = px, py
    ws.skill = SKILLS[sk]
    for j, v in enumerate(latches):
        ws.tp_fired[j] = v
    ws.mon_x[m], ws.mon_y[m], ws.mon_floorz[m], ws.mon_facing[m] = new[0], new[1], floor, fa
    ws.mon_momx[m], ws.mon_momy[m], ws.mon_fx[m], ws.mon_fy[m] = mom[0], mom[1], frac[0], frac[1]
    ws.mon_active[m] = ws.mon_shootable[m] = 1
    w._teleported = False
    nx, ny = w._teleport_monster(m, old[0], old[1], new[0], new[1])
    hit = w._teleported
    lf = w.rm.point_in_subsector(w.cmap, nx, ny) if hit else leaf
    walk = not knock_ctx
    mback = ([ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_fx[m], ws.mon_fy[m]] if walk or not hit
             else [mom[0] & M32, mom[1] & M32, frac[0], frac[1]])
    kbx = ([(nx << 16) & M32, (ny << 16) & M32, 0, 0] if (hit and knock_ctx) else kb)
    lat = sum(v << (4 * j) for j, v in enumerate(ws.tp_fired)) if ctx.nonce else 0
    want = ([nx & 0xFFFF, ny & 0xFFFF, (ws.mon_floorz[m] if hit else floor) & M32, lf, ws.mon_facing[m]] + mback
            + kbx + [0, 0, 0] + _fog_want(ctx) + [lat])
    return feed, want, hit, (latches, list(ws.tp_fired) if ctx.nonce else [])


def _monster_expect(ctx, recs, knock_ctx, seed=7):
    rng = random.Random(seed)
    feed, want, hits, flips = b"", [], 0, 0
    for radius, rec in recs:
        f, wv, hit, (a, b) = _monster_case(ctx, rec, radius, rng, knock_ctx)
        feed, want, hits, flips = feed + f, want + wv, hits + hit, flips + (a != b)
    return feed, want, hits, flips


def _mrecs(ctx):
    return [(r, rec) for r in (20, 30) for rec in _records(ctx, r, seed=r)
            if (rec[1][0] >> 16, rec[1][1] >> 16) != (rec[2][0] >> 16, rec[2][1] >> 16)]


PER = 22


@needs_art
@pytest.mark.parametrize("knock_ctx", [False, True], ids=["walk", "knock"])
@pytest.mark.parametrize("mapname", sorted(LINES))
def test_a_monster_teleports_as_the_model(tmp_path, mapname, knock_ctx):
    ctx = ctx_of(mapname)
    recs = _mrecs(ctx)
    feed, want, hits, flips = _monster_expect(ctx, recs, knock_ctx)
    assert 5 <= hits <= len(recs) - 50, (hits, len(recs))            # not vacuous: teleports and not
    assert not ctx.nonce or flips >= 20, flips                        # E1M7: latches the moves killed
    got = _run(tmp_path, "mtp", monster_program(ctx, knock_ctx=knock_ctx), feed)
    bad = _check(got, want, PER)
    assert not bad, (len(bad), [recs[i] for i in bad[:3]])


# ---- the player ------------------------------------------------------------------------------------------------------

def player_program(ctx, muts=()):
    lines = T.player_lines(ctx.tels, prefix="tpw", knock_cells=True)
    stomp = "\n".join(T.stomp_leaf_lines(ctx.rows) + _dm_stub() + _tf_stub())
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            f"hex.zero {NH}, kcount", "hex.zero 1, kerr", *[f"hex.zero {w_}, {c}" for c, w_ in FOG_CELLS],
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 4, viewangle", "hex.zero 2, p_rct", "hex.zero 8, p_kmx", "hex.zero 8, p_kmy",
            "hex.zero 1, p_dead", *_mons_in(), "\n".join(lines)]
    for reg, w_ in (("viewx", 8), ("viewy", 8), ("viewangle", 8), ("p_rct", 2), ("kcount", NH), *FOG_CELLS):
        body += _pr(reg, w_)
    body += [";loop", "done:", "stl.loop", stomp, "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "p_kmx: hex.vec 8",
             "p_kmy: hex.vec 8", "g_skill: hex.vec 1", *_common_decls()]
    return _mutate("\n".join(body), muts) + "\n"


@needs_art
@pytest.mark.parametrize("mapname", sorted(LINES))
def test_the_player_never_fires_a_monster_only_line(tmp_path, mapname):
    ctx = ctx_of(mapname)
    w, ws = ctx.w, ctx.w.ws
    rng = random.Random(5)
    feed, want, hits, mo = b"", [], 0, 0
    for rec in _records(ctx, PLAYER_R, seed=13, n_rand=10):
        k, old, new, _m, _alive = rec
        mons = _mons_of(ctx, rec)
        ang = rng.getrandbits(32)
        feed += (bytes([1]) + struct.pack("<IIIII", old[0] & M32, old[1] & M32, new[0] & M32, new[1] & M32, ang)
                 + _mons_feed(mons))
        ctx.place(mons, True)
        ws.px, ws.py, ws.pangle, ws.p_reaction, ws.p_momx, ws.p_momy = new[0], new[1], ang, 0, 0, 0
        w._teleported = False
        live = [ws.mon_shootable[m] for m in ctx.hslots]
        w._teleport_player(old[0], old[1], new[0], new[1])
        hits += w._teleported
        mo += ctx.tels[k].monster_only
        killed = sum(1 << (4 * j) for j, m in enumerate(ctx.hslots) if live[j] and not ws.mon_shootable[m])
        want += [ws.px & M32, ws.py & M32, ws.pangle, ws.p_reaction, killed] + _fog_want(ctx)
    assert mo >= 50
    if mapname != "E1M5":
        assert hits >= 10                                            # the 97 in the records still takes him
    else:
        assert hits == 0 and T.player_lines(ctx.tels, prefix="tpw", knock_cells=True) == []
    got = _run(tmp_path, "mtpp", player_program(ctx), feed)
    bad = _check(got, want, 10)
    assert not bad, (len(bad), bad[:3])


# ---- R9: the mutants ---------------------------------------------------------------------------------------------------
M_MUTS = {
    ("E1M7", "latch_never_tested"): [("    hex.if1 1, tp_w1 + 0*dw, tpm20_3_no\n", ""),
                                     ("    hex.if1 1, tp_w1 + 0*dw, tpm30_3_no\n", "")],
    ("E1M7", "latch_never_set"): [("    hex.set 1, tp_w1 + 1*dw, 1\n", "")],
    ("E1M7", "latch_front_only"): [("  tpm20_5_hit:\n    hex.set 1, tp_w1 + 2*dw, 1\n", "  tpm20_5_hit:\n"),
                                   ("  tpm20_5_ok:\n", "  tpm20_5_ok:\n    hex.set 1, tp_w1 + 2*dw, 1\n"),
                                   ("  tpm30_5_hit:\n    hex.set 1, tp_w1 + 2*dw, 1\n", "  tpm30_5_hit:\n"),
                                   ("  tpm30_5_ok:\n", "  tpm30_5_ok:\n    hex.set 1, tp_w1 + 2*dw, 1\n")],
    ("E1M5", "skill_ignored"): [("hex.if0 1, g_skill, tpm20_0_k0", ";tpm20_0_k2"),
                                ("hex.if0 1, g_skill, tpm30_0_k0", ";tpm30_0_k2")],
    ("E1M5", "skill_inverted"): [("  tpm20_0_k0:\n  tpm20_0_k1:\n    ;tpm20_0_no\n  tpm20_0_k2:\n",
                                  "  tpm20_0_k2:\n    ;tpm20_0_no\n  tpm20_0_k0:\n  tpm20_0_k1:\n")],
}


@needs_art
@pytest.mark.parametrize("key", sorted(M_MUTS), ids=["%s-%s" % k for k in sorted(M_MUTS)])
def test_a_broken_monster_only_teleport_is_caught(tmp_path, key):
    ctx = ctx_of(key[0])
    feed, want, _h, _f = _monster_expect(ctx, _mrecs(ctx), False)
    got = _run(tmp_path, "mtp_" + key[1], monster_program(ctx, muts=M_MUTS[key]), feed)
    assert len(got) == len(want), "the mutant %s did not run to the end" % (key,)
    assert got != want, "the mutant %s went unnoticed" % (key,)


@needs_art
def test_a_126_in_the_players_text_is_caught(tmp_path):
    """R9: E1M4's 126 handed to the player's text as a player line -- the player record crossing it parts"""
    import dataclasses
    ctx = ctx_of("E1M4")
    tels = [dataclasses.replace(t, monster_only=False) for t in ctx.tels]
    text = "\n".join(T.player_lines(tels, prefix="tpw", knock_cells=True))
    assert "tpw_f0:" in text and text != "\n".join(T.player_lines(ctx.tels, prefix="tpw", knock_cells=True))
    k = [i for i, t in enumerate(ctx.tels) if t.line == 1892][0]
    tel = ctx.tels[k]
    L, mid = tel.coord << 16, ((tel.lo + tel.hi) // 2) << 16
    co, cn = (L - (4 << 16), L + (4 << 16)) if tel.front_le else (L + (4 << 16), L - (4 << 16))
    old, new = _pos(tel, co, mid), _pos(tel, cn, mid)
    feed = (bytes([1]) + struct.pack("<IIIII", old[0] & M32, old[1] & M32, new[0] & M32, new[1] & M32, 0)
            + _mons_feed([(tel.dest[0] + 900, tel.dest[1], 0)] * NH))
    good = _run(tmp_path, "p126", player_program(ctx), feed)
    mutant = player_program(ctx).replace("\n".join(T.player_lines(ctx.tels, prefix="tpw", knock_cells=True)), text)
    bad = _run(tmp_path, "p126m", mutant, feed)
    assert good[:2] == [new[0] & M32, new[1] & M32] and bad[:2] != good[:2]
