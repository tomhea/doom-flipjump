"""M8 L4 -- THE TELEPORTERS (line special 97) RUN in fj against the MODEL, on E1M2's four real lines: the emitter's own
text (doomfj.teleportcode) fed records, read back, and compared with the model's own functions on an E1M2 World --
`combat._teleport_player` (the walk's and the knock move's copies), `world._teleport_monster` with the slot's
write-back (the walk's and the knock move's copies), and the player's reactiontime (`reaction_lines` spliced before
the REAL `_player_sim_lines`, against `combat._player_move` with the collision made free).

The records: every line, both sides, moves that cross it and moves that stop short or start ON it (P_PointOnLineSide's
`<=`), the extent's strict ends (lo - r, hi + r, and one ulp inside), WR crossings repeated, monsters standing at the
destination inside and exactly at the blockdist (shootable or not), the player alive and dead (a monster's stomp).

R9 (MUTANTS): each a real edit of the emitted text (or the rules the text is generated from) that must part from the
model: the back side teleports (front_le flipped), no stomp, a stomp whose box is inclusive, a dead player who still
blocks, the extent inclusive, no reactiontime, the angle kept, the knock momentum kept, the knock loop not restarted
at the destination, the monster's leaf / floor / facing not taken, the reaction gate that never counts down and one
that never skips the move.
"""
import dataclasses
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import teleportcode as T
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_trig_idioms_fj
from doomfj.reference_model import ReferenceModel
from doomfj.teleport import REACTION_TICS
from doomfj.wad import WadFile
from doomfj.wall_renderer import _player_sim_lines
from doomfj.wireformat import keys_byte
from doomfj.world import KEYS, TicEvents, World

FIX = "tests/fixtures/freedoom_e1m2.wad"
FJ = Path(__file__).resolve().parents[2] / "src" / "fj"
CFG = Config()
M32 = 0xFFFFFFFF
NH = 3                                   # the harness's monster rows (thpos_rt rows 0..2)


class _FreeRM(ReferenceModel):
    """the oracle with the collision made free while `free` (the reaction test's: the gate, not the walls)"""
    free = False

    def try_move(self, *a, **k):
        return True if self.free else super().try_move(*a, **k)

    def check_position(self, *a, **k):
        return (True, 0, 0, 0) if self.free else super().check_position(*a, **k)


class Ctx:
    def __init__(self):
        self.rm = _FreeRM(CFG)
        self.w = World(WadFile.from_path(FIX), "E1M2", player="final", monsters="final", rm=self.rm)
        w = self.w
        self.tels = w.teleports
        assert len(self.tels) == 4
        r20 = [m for m in range(w.layout.nmon) if w.mon_radius[m] == 20]
        r30 = [m for m in range(w.layout.nmon) if w.mon_radius[m] == 30]
        self.hslots = [r20[0], r30[0], r20[1]]          # the harness rows' model slots
        self.movers = {20: r20[2], 30: r30[1]}         # a teleporting monster of each radius (no harness row)
        self.rows = [(j, w.mon_radius[m]) for j, m in enumerate(self.hslots)]

    def place(self, mons, alive=True):
        """the model's monsters: only the harness slots, at `mons` [(x, y, shootable)]; the player alive or dead"""
        ws = self.w.ws
        for m in range(self.w.layout.nmon):
            ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = 0
        for (x, y, sh), m in zip(mons, self.hslots):
            ws.mon_x[m], ws.mon_y[m] = x, y
            ws.mon_active[m] = ws.mon_shootable[m] = ws.mon_solid[m] = sh
        for b in range(len(self.w.barrel_things)):
            ws.bar_state[b] = 0
        ws.p_dead = 0 if alive else 1
        ws.p_health = 100 if alive else 0


@pytest.fixture(scope="module")
def ctx():
    return Ctx()


def _run(tmp, name, program, feed, consts=False):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    paths = [src.resolve()]
    if consts:
        paths = [CFG.emit_fj_consts(tmp / "fj_consts.fj").resolve(), (FJ / "fixed_point.fj").resolve()] + paths
    fj.assemble(paths, out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def _mons_in():
    out = []
    for j in range(NH):
        out += [f"hex.input 2, thpos_rt + {16 * j + 4}*dw", f"hex.input 2, thpos_rt + {16 * j + 12}*dw",
                "hex.input 1, rb", f"hex.mov 1, mon_shootable + {j}*dw, rb"]
    return out


def _mons_feed(mons):
    return b"".join(struct.pack("<HH", x & 0xFFFF, y & 0xFFFF) + bytes([sh]) for x, y, sh in mons)


def _common_decls():
    return ["rmagic: hex.vec 2", "rb: hex.vec 2", f"thpos_rt: hex.vec {16 * NH}", f"mon_shootable: hex.vec {NH}",
            "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8", "p_dead: hex.vec 1", *T.decls()]


def _mutate(text, muts):
    for old, new in muts:
        assert text.count(old) >= 1, (old, text[:200])
        text = text.replace(old, new)
    return text


# ---- the records ------------------------------------------------------------------------------------------------------

def _pos(tel, c16, o16):
    return (c16, o16) if tel.axis == "x" else (o16, c16)


def _records(ctx, radius, seed, n_rand=60):
    """[(tel index, old16, new16, mons, alive)] around every line: targeted ends and sides, then random"""
    rng = random.Random(seed)
    out = []
    for k, tel in enumerate(ctx.tels):
        L = tel.coord << 16
        ends = [((tel.lo - radius) << 16) + d for d in (-1, 0, 1)] + [((tel.hi + radius) << 16) + d for d in (-1, 0, 1)]
        mids = [((tel.lo + tel.hi) // 2) << 16, (tel.lo << 16) + 5]
        cs = [L - (6 << 16), L - 1, L, L + 1, L + (6 << 16)]
        for o in ends + mids:
            for co in cs:
                for cn in cs:
                    if co != cn:
                        out.append((k, _pos(tel, co, o + rng.randint(-3, 3) * 4096), _pos(tel, cn, o), None, True))
        # a destination stomp: one harness monster near the destination, inside / at / outside the blockdist
        dx, dy = tel.dest
        for j, (_t, rj) in enumerate(ctx.rows):
            for off in (rj + radius - 1, rj + radius, rj + radius + 1, 0):
                for sh in (1, 0):
                    mons = [(dx + 999, dy, 1)] * NH
                    mons[j] = (dx + off, dy - off // 2, sh)
                    co, cn = (L - (4 << 16), L + (4 << 16)) if tel.front_le else (L + (4 << 16), L - (4 << 16))
                    mid = ((tel.lo + tel.hi) // 2) << 16
                    out.append((k, _pos(tel, co, mid), _pos(tel, cn, mid), mons, True))
        for _ in range(n_rand):
            o = rng.randint((tel.lo - radius - 8) << 16, (tel.hi + radius + 8) << 16)
            co, cn = L + rng.randint(-20 << 16, 20 << 16), L + rng.randint(-20 << 16, 20 << 16)
            out.append((k, _pos(tel, co, o + rng.randint(-1 << 16, 1 << 16)), _pos(tel, cn, o), None,
                        rng.random() < 0.8))
    # WR: the same crossing again fires again (no latch) -- the first crossing of each line, repeated
    out += [r for r in out if r[3] is None][:8]
    return out


def _mons_of(ctx, rec):
    k, _o, _n, mons, _alive = rec
    if mons is None:
        dx, dy = ctx.tels[k].dest
        mons = [(dx + 500 + 100 * j, dy, 1) for j in range(NH)]
    return mons


# ---- 1. the player --------------------------------------------------------------------------------------------------

def player_program(ctx, *, knock_ctx=False, muts=(), tels=None):
    tels = ctx.tels if tels is None else tels
    lines = "\n".join(T.player_lines(tels, prefix="tpk" if knock_ctx else "tpw", knock_cells=True,
                                     knock_ctx=knock_ctx))
    stomp = "\n".join(T.stomp_leaf_lines(ctx.rows))
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 4, viewangle", "hex.input 1, rb", "hex.mov 2, p_rct, rb",
            "hex.input 4, p_kmx", "hex.input 4, p_kmy", "hex.input 1, rb", "hex.mov 1, p_dead, rb",
            "hex.input 4, kb_px", "hex.input 4, kb_py", "hex.input 4, kb_vx", "hex.input 4, kb_vy",
            *_mons_in(), lines]
    for reg, n in (("viewx", 8), ("viewy", 8), ("viewangle", 8), ("p_rct", 2), ("p_kmx", 8), ("p_kmy", 8),
                   ("kb_px", 8), ("kb_py", 8), ("kb_vx", 8), ("kb_vy", 8)):
        body += _pr(reg, n)
    body += [";loop", "done:", "stl.loop", stomp, "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "p_kmx: hex.vec 8",
             "p_kmy: hex.vec 8", "kb_px: hex.vec 8", "kb_py: hex.vec 8", "kb_vx: hex.vec 8", "kb_vy: hex.vec 8",
             *_common_decls()]
    return _mutate("\n".join(body), muts) + "\n"


def _player_case(ctx, rec, rng, knock_ctx):
    """(feed bytes, the model's expectation) for one record"""
    w, ws = ctx.w, ctx.w.ws
    k, old, new, _m, alive = rec
    mons = _mons_of(ctx, rec)
    ang, rct = rng.getrandbits(32), rng.choice((0, 0, 3))
    momx, momy = rng.randint(-(30 << 16), 30 << 16), rng.randint(-(30 << 16), 30 << 16)
    kb = [rng.getrandbits(32) for _ in range(4)]
    feed = (bytes([1]) + struct.pack("<IIIII", old[0] & M32, old[1] & M32, new[0] & M32, new[1] & M32, ang)
            + bytes([rct]) + struct.pack("<II", momx & M32, momy & M32) + bytes([0 if alive else 1])
            + struct.pack("<IIII", *kb) + _mons_feed(mons))
    ctx.place(mons, alive)
    ws.px, ws.py, ws.pangle, ws.p_reaction, ws.p_momx, ws.p_momy = new[0], new[1], ang, rct, momx, momy
    w._teleported = False
    w._teleport_player(old[0], old[1], new[0], new[1])
    hit = w._teleported
    kbx = [ws.px & M32, ws.py & M32, 0, 0] if (hit and knock_ctx) else kb     # the knock loop's own registers
    want = [ws.px & M32, ws.py & M32, ws.pangle, ws.p_reaction, ws.p_momx & M32, ws.p_momy & M32] + kbx
    return feed, want, hit


def _player_expect(ctx, recs, knock_ctx=False, seed=11):
    rng = random.Random(seed)
    feed, want, hits = b"", [], 0
    for rec in recs:
        f, wv, hit = _player_case(ctx, rec, rng, knock_ctx)
        feed, want, hits = feed + f, want + wv, hits + hit
    return feed, want, hits


@pytest.fixture(scope="module")
def player_recs(ctx):
    return _records(ctx, PLAYER_R, seed=3)


def _check(got, want, per):
    assert len(got) == len(want), (len(got), len(want))
    bad = [i // per for i, (g, v) in enumerate(zip(got, want)) if g != v]
    return sorted(set(bad))


@pytest.mark.parametrize("knock_ctx", [False, True], ids=["walk", "knock"])
def test_the_player_teleports_as_the_model(tmp_path, ctx, player_recs, knock_ctx):
    feed, want, hits = _player_expect(ctx, player_recs, knock_ctx)
    # not vacuous: teleports and refusals (from the back, short of the line, stomped) both occur, on every line
    assert 40 <= hits <= len(player_recs) - 100, (hits, len(player_recs))
    got = _run(tmp_path, "tpp", player_program(ctx, knock_ctx=knock_ctx), feed)
    bad = _check(got, want, 10)
    assert not bad, (len(bad), [player_recs[i] for i in bad[:3]])


def test_every_line_teleports_from_its_front_only(ctx):
    """the model's own rule on E1M2's four lines, the side named by hand from the vertices: line 126 (x 2816, v1 at
    y 0 -> 320: front east), 1910 (x 2800, 320 -> 0: front west), 1215 (x 1624: front east, the pad), 1219 (x 1752:
    front west, the pad); a crossing from the back never teleports"""
    from doomfj.teleport import crossed_front
    front_east = {126: True, 1910: False, 1215: True, 1219: False}
    for tel in ctx.tels:
        L, mid = tel.coord << 16, ((tel.lo + tel.hi) // 2) << 16
        east, west = (L + (3 << 16), mid), (L - (3 << 16), mid)
        fe = front_east[tel.line]
        assert crossed_front(tel, east, west, PLAYER_R) == fe
        assert crossed_front(tel, west, east, PLAYER_R) == (not fe)


# ---- 2. a monster ---------------------------------------------------------------------------------------------------

def monster_program(ctx, *, knock_ctx=False, muts=(), tels=None):
    tels = ctx.tels if tels is None else tels
    lines = "\n".join(T.monster_lines(tels, prefix="tpq" if knock_ctx else "tpm", knock_ctx=knock_ctx))
    back = "\n".join(T.slot_back_lines(1, facing="mon_facing + 1*dw", knock=True, walk=not knock_ctx, tag="tpb"))
    stomp = "\n".join(T.stomp_leaf_lines(ctx.rows))
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, mm_ox16", "hex.input 4, mm_oy16", "hex.input 4, cpx", "hex.input 4, cpy",
            "hex.input 1, mm_r", "hex.input 1, rb", "hex.mov 1, mm_r30, rb",
            "hex.input 2, mm_nx", "hex.input 2, mm_ny", "hex.input 4, cp_floor", "hex.input 2, ptss",
            "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 1, rb", "hex.mov 1, p_dead, rb",
            "hex.input 1, rb", "hex.mov 1, mon_facing + 1*dw, rb",
            "hex.input 4, mkx + 8*dw", "hex.input 4, mky + 8*dw", "hex.input 2, mfx + 4*dw", "hex.input 2, mfy + 4*dw",
            "hex.input 4, kb_cx", "hex.input 4, kb_cy", "hex.input 4, kb_vx", "hex.input 4, kb_vy",
            *_mons_in(), lines, back]
    for reg, n in (("mm_nx", 4), ("mm_ny", 4), ("cp_floor", 8), ("ptss", 3), ("mon_facing + 1*dw", 1),
                   ("mkx + 8*dw", 8), ("mky + 8*dw", 8), ("mfx + 4*dw", 4), ("mfy + 4*dw", 4),
                   ("kb_cx", 8), ("kb_cy", 8), ("kb_vx", 8), ("kb_vy", 8), ("tp_hit", 1)):
        body += _pr(reg, n)
    body += [";loop", "done:", "stl.loop", stomp,
             "mm_ox16: hex.vec 8", "mm_oy16: hex.vec 8", "cpx: hex.vec 8", "cpy: hex.vec 8", "mm_r: hex.vec 2",
             "mm_r30: hex.vec 1", "mm_nx: hex.vec 4", "mm_ny: hex.vec 4", "cp_floor: hex.vec 8", "ptss: hex.vec w/4",
             "mon_facing: hex.vec 2", "mkx: hex.vec 16", "mky: hex.vec 16", "mfx: hex.vec 8", "mfy: hex.vec 8",
             "kb_cx: hex.vec 8", "kb_cy: hex.vec 8", "kb_vx: hex.vec 8", "kb_vy: hex.vec 8", *_common_decls()]
    return _mutate("\n".join(body), muts) + "\n"


def _monster_case(ctx, rec, radius, rng, knock_ctx):
    w, ws = ctx.w, ctx.w.ws
    k, old16, new16, _m, alive = rec
    m = ctx.movers[radius]
    mons = _mons_of(ctx, rec)
    old, new = (old16[0] >> 16, old16[1] >> 16), (new16[0] >> 16, new16[1] >> 16)
    floor, leaf, fa = rng.randint(-200, 300), rng.randrange(1104), rng.randrange(8)
    px, py = rng.choice([(ctx.tels[k].dest[0] << 16, ctx.tels[k].dest[1] << 16),
                         ((ctx.tels[k].dest[0] + 46) << 16, ctx.tels[k].dest[1] << 16),
                         ((ctx.tels[k].dest[0] + 45) << 16, (ctx.tels[k].dest[1] - 1) << 16),
                         (0, 0), (0, 0)])
    mom = [rng.randint(-(9 << 16), 9 << 16) for _ in range(2)]
    frac = [rng.getrandbits(16) for _ in range(2)]
    kb = [rng.getrandbits(32) for _ in range(4)]
    feed = (bytes([1]) + struct.pack("<IIII", (old[0] << 16) & M32, (old[1] << 16) & M32, (new[0] << 16) & M32,
                                     (new[1] << 16) & M32)
            + bytes([radius, int(radius == 30)]) + struct.pack("<HHIH", new[0] & 0xFFFF, new[1] & 0xFFFF,
                                                                 floor & M32, leaf)
            + struct.pack("<II", px & M32, py & M32) + bytes([0 if alive else 1, fa])
            + struct.pack("<IIHH", mom[0] & M32, mom[1] & M32, frac[0], frac[1])
            + struct.pack("<IIII", *kb) + _mons_feed(mons))
    ctx.place(mons, alive)
    ws.px, ws.py = px, py
    ws.mon_x[m], ws.mon_y[m], ws.mon_floorz[m], ws.mon_facing[m] = new[0], new[1], floor, fa
    ws.mon_momx[m], ws.mon_momy[m], ws.mon_fx[m], ws.mon_fy[m] = mom[0], mom[1], frac[0], frac[1]
    ws.mon_active[m] = ws.mon_shootable[m] = 1
    w._teleported = False
    nx, ny = w._teleport_monster(m, old[0], old[1], new[0], new[1])
    hit = w._teleported
    if hit:
        assert (nx, ny) == (ws.mon_x[m], ws.mon_y[m])
    lf = w.rm.point_in_subsector(w.cmap, nx, ny) if hit else leaf
    walk = not knock_ctx
    mback = ([ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_fx[m], ws.mon_fy[m]] if walk or not hit
             else [mom[0] & M32, mom[1] & M32, frac[0], frac[1]])     # the knock stub writes these back itself
    kbx = ([(nx << 16) & M32, (ny << 16) & M32, 0, 0] if (hit and knock_ctx) else kb)
    want = ([nx & 0xFFFF, ny & 0xFFFF, (ws.mon_floorz[m] if hit else floor) & M32, lf, ws.mon_facing[m]] + mback
            + kbx + [0])
    return feed, want, hit


def _monster_expect(ctx, recs, knock_ctx, seed=7):
    rng = random.Random(seed)
    feed, want, hits = b"", [], 0
    for radius, rec in recs:
        f, wv, hit = _monster_case(ctx, rec, radius, rng, knock_ctx)
        feed, want, hits = feed + f, want + wv, hits + hit
    return feed, want, hits


@pytest.fixture(scope="module")
def monster_recs(ctx):
    return [(r, rec) for r in (20, 30) for rec in _records(ctx, r, seed=r, n_rand=40)
            if (rec[1][0] >> 16, rec[1][1] >> 16) != (rec[2][0] >> 16, rec[2][1] >> 16)]


@pytest.mark.parametrize("knock_ctx", [False, True], ids=["walk", "knock"])
def test_a_monster_teleports_as_the_model(tmp_path, ctx, monster_recs, knock_ctx):
    feed, want, hits = _monster_expect(ctx, monster_recs, knock_ctx)
    assert 40 <= hits <= len(monster_recs) - 100, (hits, len(monster_recs))
    got = _run(tmp_path, "tpm", monster_program(ctx, knock_ctx=knock_ctx), feed)
    bad = _check(got, want, 14)
    assert not bad, (len(bad), [monster_recs[i] for i in bad[:3]])


# ---- 3. the player's reactiontime ------------------------------------------------------------------------------------

def reaction_program(muts=()):
    text = "\n".join(T.reaction_lines() + _player_sim_lines(collide=False, strafe=True, tap=True))
    return _mutate("\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
        "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 4, viewangle", "hex.input 1, pkeys",
        "hex.input 1, rb", "hex.mov 1, p_tnh, rb", "hex.input 1, rb", "hex.mov 2, p_rct, rb",
        text,
        *_pr("viewx", 8), *_pr("viewy", 8), *_pr("viewangle", 8), *_pr("p_tnh", 1), *_pr("p_rct", 2),
        ";loop", "done:", "stl.loop",
        "rmagic: hex.vec 2", "rb: hex.vec 2", "pkeys: hex.vec 2", "p_tnh: hex.vec 1", "viewx: hex.vec 8",
        "viewy: hex.vec 8", "viewangle: hex.vec 8", f"p_rct: hex.vec {T.REACTION_NIBBLES}",
        "pmove: hex.vec 8", "pangt: hex.vec 8", "pangi: hex.vec 3", "pmvc: hex.vec 8", "pmvs: hex.vec 8",
        "pmvdx: hex.vec 8", "pmvdy: hex.vec 8", "psid: hex.vec 8", "psdx: hex.vec 8", "psdy: hex.vec 8",
        generate_trig_idioms_fj("finesine", CFG.TRIG_N, 16)]), muts) + "\n"


NAMES = ("forward", "back", "turn_left", "turn_right", "strafe_left", "strafe_right")


def _reaction_trajectory(ctx, frames=60, seed=9):
    """a teleport's 18 frozen frames inside a walk: frames fed back on themselves (the model's World, its collision
    free), p_rct set to 18 at frames 5 and 33 (a teleport), keys random -> (feed per frame, want per frame)"""
    rng = random.Random(seed)
    w, ws = ctx.w, ctx.w.ws
    ctx.place([(0, 0, 0)] * NH)
    w.player_blocking = False
    ws.px, ws.py, ws.pangle, ws.p_turnheld, ws.p_reaction = 100 << 16, 3000 << 16, 0, 0, 0   # far from the lines
    recs = []
    ctx.rm.free = True
    try:
        for f in range(frames):
            if f in (5, 33):
                ws.p_reaction = REACTION_TICS
            k = {n: rng.random() < 0.4 for n in NAMES}
            kk = dict.fromkeys(KEYS, False)
            kk.update(k)
            pose = (ws.px & M32, ws.py & M32, ws.pangle, ws.p_turnheld, ws.p_reaction)
            w._player_move(kk, TicEvents(0))
            recs.append((pose, k, [ws.px & M32, ws.py & M32, ws.pangle, ws.p_turnheld, ws.p_reaction]))
    finally:
        ctx.rm.free = False
        w.player_blocking = True
    return recs


def _reaction_feed(pose, k):
    return (bytes([1]) + struct.pack("<III", pose[0], pose[1], pose[2]) + bytes([keys_byte(k), pose[3], pose[4]]))


def test_the_reactiontime_freezes_the_turn_and_the_walk(tmp_path, ctx):
    recs = _reaction_trajectory(ctx)
    frozen = [r for r in recs if r[0][4]]
    assert len(frozen) == 2 * REACTION_TICS and any(r[0][:3] != tuple(r[2][:3]) for r in recs)
    got = _run(tmp_path, "tpr", reaction_program(), b"".join(_reaction_feed(p, k) for p, k, _w in recs), consts=True)
    want = sum((wv for _p, _k, wv in recs), [])
    bad = _check(got, want, 5)
    assert not bad, (len(bad), [recs[i] for i in bad[:2]])


# ---- R9: the mutants -------------------------------------------------------------------------------------------------

def _flip(ctx):
    return [dataclasses.replace(t, front_le=not t.front_le) for t in ctx.tels]


P_MUTS = {
    "back_side": dict(tels=_flip),
    "no_stomp": dict(muts=[("    stl.fcall tp_stomp, tp_sret\n    hex.if1 1, tp_blk, tpw_end", "")]),
    "stomp_inclusive": dict(muts=[("tp_s0_y, tp_s0_n, tp_s0_n", "tp_s0_y, tp_s0_y, tp_s0_n"),
                                  ("tp_stk, tp_s0_n, tp_s0_n", "tp_stk, tp_stk, tp_s0_n")]),
    "extent_inclusive": dict(muts=[("tpw_f0, tpw0_no, tpw0_no", "tpw_f0, tpw_f0, tpw0_no")]),
    "no_reaction": dict(muts=[(f"p_rct, {REACTION_TICS}", "p_rct, 0")]),
    "angle_kept": dict(muts=[("    hex.set 8, viewangle, 0x80000000\n", ""), ("    hex.set 8, viewangle, 0x0\n", "")]),
    "momentum_kept": dict(muts=[("    hex.zero 8, p_kmx\n", "")]),
}
PK_MUTS = {"knock_not_restarted": dict(muts=[("    hex.zero 8, kb_vx\n", "")])}
M_MUTS = {
    "back_side": dict(tels=_flip),
    "player_dead_blocks": dict(muts=[("    hex.if1 1, p_dead, tp_out\n", "")]),
    "no_leaf": dict(muts=[("hex.set 3, ptss, 0x233", "hex.set 3, ptss, 0x232"),
                          ("hex.set 3, ptss, 0xee", "hex.set 3, ptss, 0xed")]),
    "floor_kept": dict(muts=[("    hex.set 8, cp_floor, 0xf0\n", ""), ("    hex.set 8, cp_floor, 0xffffffc8\n", "")]),
    "facing_kept": dict(muts=[("    hex.mov 1, mon_facing + 1*dw, tp_fa\n", "")]),
    "fraction_kept": dict(muts=[("    hex.zero 4, mfx + 4*dw\n", "")]),
}


def _mut_kw(ctx, spec):
    kw = {}
    if "tels" in spec:
        kw["tels"] = spec["tels"](ctx)
    if "muts" in spec:
        kw["muts"] = spec["muts"]
    return kw


@pytest.mark.parametrize("mut", sorted(P_MUTS))
def test_a_broken_player_teleport_is_caught(tmp_path, ctx, player_recs, mut):
    feed, want, _h = _player_expect(ctx, player_recs)
    got = _run(tmp_path, "tpp_" + mut, player_program(ctx, **_mut_kw(ctx, P_MUTS[mut])), feed)
    assert len(got) == len(want), "the mutant %s did not run to the end" % mut      # it ran: it disagrees
    assert got != want, "the mutant %s went unnoticed" % mut


@pytest.mark.parametrize("mut", sorted(PK_MUTS))
def test_a_broken_knock_teleport_is_caught(tmp_path, ctx, player_recs, mut):
    feed, want, _h = _player_expect(ctx, player_recs, True)
    got = _run(tmp_path, "tpk_" + mut, player_program(ctx, knock_ctx=True, **_mut_kw(ctx, PK_MUTS[mut])), feed)
    assert len(got) == len(want), "the mutant %s did not run to the end" % mut      # it ran: it disagrees
    assert got != want, "the mutant %s went unnoticed" % mut


@pytest.mark.parametrize("mut", sorted(M_MUTS))
def test_a_broken_monster_teleport_is_caught(tmp_path, ctx, monster_recs, mut):
    feed, want, _h = _monster_expect(ctx, monster_recs, False)
    got = _run(tmp_path, "tpm_" + mut, monster_program(ctx, **_mut_kw(ctx, M_MUTS[mut])), feed)
    assert len(got) == len(want), "the mutant %s did not run to the end" % mut      # it ran: it disagrees
    assert got != want, "the mutant %s went unnoticed" % mut


R_MUTS = {"never_counts_down": [("hex.dec 2, p_rct\n", "")],
          "never_skips": [(";simmv_done\ntp_rgo:", ";tp_rgo\ntp_rgo:")]}


@pytest.mark.parametrize("mut", sorted(R_MUTS))
def test_a_broken_reaction_gate_is_caught(tmp_path, ctx, mut):
    recs = _reaction_trajectory(ctx)
    got = _run(tmp_path, "tpr_" + mut, reaction_program(R_MUTS[mut]),
               b"".join(_reaction_feed(p, k) for p, k, _w in recs), consts=True)
    want = sum((wv for _p, _k, wv in recs), [])
    assert len(got) == len(want), "the mutant %s did not run to the end" % mut
    assert got != want, "the mutant %s went unnoticed" % mut
