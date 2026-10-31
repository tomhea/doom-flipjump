"""M8 soultele -- A LOST SOUL TELEPORTS, on the real flipjump engine: EV_Teleport of a soul (lostsoul._soul_teleported,
world._teleport_monster) -- z = the destination floor << 16, momz 0, ceilingz = the destination sector's ceiling (a
mover's where it stands), momentum and fraction 0, the facing -- through both fj copies the emitter splices:
  XY    the soul's own XY try (`sks<k>` -> sk_mmove -> kb_xy -> sk_try, whose teleports are
        teleportcode.monster_lines(knock_ctx=True, soul="knock")): a charge or a knock across a teleport line, flying
        or not, alive or a corpse, in the air or on its floor, the crossing on either half-step;
  MOVE  P_Move (`mm_move` with the soul context, teleportcode.monster_lines(soul="walk") -- radius 16 by mm_r16) and the
        slot's write-back (monstercode._tele_back: the facing, the knock cells, the soul's momz) then the context's.
The harness is tests/fj/test_lostsoul_fj's (E1M1 with three souls; ONE program, its move machinery) with three
SYNTHETIC teleport lines (Teleporter rows on open ground: E1M1 has none): one onto a still sector, two onto E1M1's two
lifts (sectors 98 and 103, `dest_moves`: the floor and the ceiling read where the lift stands -- each record puts every
lift at a random state on both sides). Some records put a monster on the destination (P_TeleportMove's stomp refuses
the teleport) and some cross at y in a line's radius margin (16 crosses, 20 more). The fogs are E1M7's / teleportcode's
(test_teleport_fj): the model's are off here and the fj's tf_spawn a stub.

R9 (each must part from the model): z_unset (no fire writes the soul's z), momz_kept (no fire / write-back zeroes
momz), ceil_try (cp_ceil not set: the soul keeps the try's ceiling), walk_r20 (P_Move's copy tests a soul at radius 20),
no_knock_tele (sk_try without its teleports: the pre-soultele text).
"""
import math
import random

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import soulcode as SC
from doomfj import teleportcode as T
from doomfj.harness import W
from doomfj.teleport import ANG45, Teleporter, check_one_per_move
from doomfj.world import TicEvents
from tests.fj import test_lostsoul_fj as LS

M32 = 0xFFFFFFFF
U = gd.FRACUNIT
N_XY, N_MOVE = 90, 90
NL = chr(10)
pytestmark = LS.pytestmark

MUTANTS = {
    "z_unset": [("    hex.zero 4, mm_skz\n    hex.mov 4, mm_skz + 4*dw, cp_floor\n", ""),
                ("    hex.zero 4, sw_z\n    hex.mov 4, sw_z + 4*dw, cp_floor\n", "")],
    "momz_kept": [("    hex.zero 8, sw_mz\n    hex.set 1, tp_fa", "    hex.set 1, tp_fa"),
                  (r"re:    hex.zero 8, sk_momz \+ \d+\*dw\n(  tpb\d+_n_r\d+:)", r"\1")],
    "ceil_try": [("    hex.mov 8, cp_ceil, cp_seedc\n", ""), ("re:    hex.set 8, cp_ceil, 0x[0-9a-f]+\n", "")],
    "walk_r20": [("    hex.if1 1, mm_r16, tpm_r16\n", "")],
}


# ================================================================================================================
# THE TELEPORT LINES
# ================================================================================================================
def _ok_at(w, x, y):
    ok, fz, cz = w.rm.check_position(w.scene_c, x << 16, y << 16)
    return ok and cz - fz >= 56, fz


def _others(w):
    """where the level's things stand (the active monsters, the barrels, the solid decorations, the pickups)"""
    ws = w.ws
    pts = [(ws.mon_x[m], ws.mon_y[m]) for m in range(w.layout.nmon) if ws.mon_active[m]]
    pts += [(t.x, t.y) for t in list(w.barrel_things) + list(w.decor_solid) + list(w.pickup_things)]
    return pts


def _clear(w, x, y, margin):
    return all(max(abs(x - ox), abs(y - oy)) > margin for ox, oy in _others(w))


def _sector_points(w, si, step=8):
    """legal points (a radius-16 box fits, 56 tall) in sector si, on a grid"""
    vs = [w.cmap.vertexes[v] for ld in w.lds for v in (ld.v1, ld.v2)
          if si in (w.sds[ld.front].sector, w.sds[ld.back].sector if ld.back != -1 else -1)]
    x0, x1 = min(v[0] for v in vs), max(v[0] for v in vs)
    y0, y1 = min(v[1] for v in vs), max(v[1] for v in vs)
    out = []
    for x in range(x0 + 16, x1 - 15, step):
        for y in range(y0 + 16, y1 - 15, step):
            if w.leaf_sector[w.rm.point_in_subsector(w.cmap, x, y)] == si and _ok_at(w, x, y)[0]:
                out.append((x, y))
    return out


def _tels(c):
    """three vertical lines (front: x <= coord) on open ground, each 48 long, a soul's walk across clear and no thing
    near; their destinations a still point and a point on each of E1M1's two lifts, no thing within 60 -> [Teleporter]"""
    w = c.w
    rnd = random.Random(0x7E1E)
    still = [s for s in c.spots if w.leaf_sector[w.rm.point_in_subsector(w.cmap, *s)] not in
             set(w.mover_order) | set(w.door_order) and _clear(w, s[0], s[1], 60)]
    dests = [still[len(still) // 2]]
    for si in w.lift_order:
        sp = [q for q in _sector_points(w, si) if _clear(w, q[0], q[1], 60)]
        assert sp, "E1M1's lift sector %d has a point clear of things" % si
        dests.append(sp[len(sp) // 2])
    lines = []
    for sx, sy in rnd.sample(still, len(still)):
        if (sx, sy) == dests[0] or not _clear(w, sx, sy, 90):
            continue
        good, fzs = True, set()
        for dx in (-26, -14, 0, 14, 26):
            for dy in (-44, -24, 0, 24, 44):
                ok, fz = _ok_at(w, sx + dx, sy + dy)
                good &= bool(ok)
                fzs.add(fz)
        if not good or len(fzs) != 1:
            continue
        lines.append((sx, sy))
        if len(lines) == 3:
            try:
                check_one_per_move(_rows(w, lines, dests, random.Random(0)))
            except AssertionError:
                lines.pop()
                continue
            break
    assert len(lines) == 3, lines
    tels = _rows(w, lines, dests, rnd)
    check_one_per_move(tels)
    return tels


def _rows(w, lines, dests, rnd):
    out = []
    for i, ((sx, sy), (dx, dy)) in enumerate(zip(lines, dests)):
        leaf = w.rm.point_in_subsector(w.cmap, dx, dy)
        s = w.leaf_sector[leaf]
        out.append(Teleporter(line=9000 + i, tag=9000 + i, axis="x", coord=sx, lo=sy - 24, hi=sy + 24, front_le=True,
                              dest=(dx, dy), angle=(rnd.randrange(8) * ANG45) & M32, dest_leaf=leaf, dest_sector=s,
                              dest_floor=w.secs[s].floor_h, dest_ceil=w.secs[s].ceil_h,
                              dest_moves=s in set(w.mover_order)))
    return out


class Tv(LS.Sv):
    def __init__(self):
        super().__init__()
        self.tels = _tels(self)
        self.w.teleports = self.tels
        self.w.tele_once = []
        self.w._teleport_fogs = lambda *a, **k: None          # the fogs: test_teleport_fj's
        T.check_barrels(self.w)                               # the fj's stomp tests no barrel (the emitter's assert)
        ws = self.w.ws
        self.home = {j: (ws.mon_x[j], ws.mon_y[j]) for j in range(self.n)}


# ================================================================================================================
# THE PROGRAM: the soul harness's, its two copies of the teleports spliced, the stomp, the fog stub
# ================================================================================================================
def _program(c, knock_tele=True):
    from doomfj import monstermove as MM
    w, n = c.w, c.n
    walk = T.monster_lines(c.tels, prefix="tpm", soul="walk")
    knock = T.monster_lines(c.tels, prefix="tps", knock_ctx=True, soul="knock") if knock_tele else []
    orig_move, orig_leaves = MM.move_leaf_lines, SC.leaves
    MM.move_leaf_lines = lambda **kw: orig_move(teleport=walk, **kw)
    SC.leaves = lambda w_, **kw: orig_leaves(w_, teleport=knock, **kw)
    try:
        decls, code, tables = LS._program(c)
    finally:
        MM.move_leaf_lines, SC.leaves = orig_move, orig_leaves
    if knock_tele:
        assert "tps16_0" in code and "tpsb%d_n" % w.soul_slots[0] in code
    code += NL.join(T.stomp_leaf_lines([(m, w.mon_radius[m]) for m in range(n)], hurt=True, knock=True, sn=2)
                    + ["tf_spawn:", "    stl.fret fx_sret"]) + NL
    decls = decls + T.decls(c.tels, souls=True) + [
        "fxs_x: hex.vec 4", "fxs_y: hex.vec 4", "fxs_kind: hex.vec 1", "fx_sret: hex.vec w/4",
        "mon_facing: hex.vec %d" % n]
    return decls, code, tables


# ================================================================================================================
# THE RECORDS
# ================================================================================================================
def _scene_at_line(c, rnd):
    """a random scene, a random soul on a line's back side -> (rec, moved, m, k, tel)"""
    w, ws = c.w, c.w.ws
    rec, moved, m, k, _ang = LS._setup(c, rnd, "open")
    for j in range(c.n):                          # a slot an earlier record left on a destination: back home
        if j != m and ws.mon_active[j] and any(max(abs(ws.mon_x[j] - t.dest[0]), abs(ws.mon_y[j] - t.dest[1])) < 80
                                               for t in c.tels):
            w.teleport_monster(j, *c.home[j])
            if j not in moved:
                moved.append(j)
    tel = rnd.choice(c.tels)
    y = rnd.choice((rnd.randint(tel.lo, tel.hi), rnd.randint(tel.lo - 19, tel.lo - 12),
                    rnd.randint(tel.hi + 12, tel.hi + 19)))
    w.teleport_monster(m, tel.coord - rnd.randint(1, 7), y)
    ws.mon_fx[m], ws.mon_fy[m] = rnd.choice((0, 0xFFFF, rnd.randrange(1 << 16))), rnd.randrange(1 << 16)
    ws.mon_facing[m] = rnd.randrange(8)
    if rnd.random() < 0.15:                       # a monster on the destination: the stomp refuses it
        j = rnd.choice([j for j in range(c.n) if j != m and ws.mon_active[j]])
        w.teleport_monster(j, tel.dest[0] + rnd.randint(-8, 8), tel.dest[1] + rnd.randint(-8, 8))
        ws.mon_solid[j] = ws.mon_shootable[j] = 1
        moved.append(j)
    return rec, moved, m, k, tel


def _facing_lines(c, m):
    return ["hex.set 1, mon_facing + %d*dw, %d" % (m, c.w.ws.mon_facing[m])]


def _xy_records(c, rnd, body, want, stats):
    w, ws = c.w, c.w.ws
    for r in range(N_XY):
        rec, moved, m, k, tel = _scene_at_line(c, rnd)
        mag = rnd.choice((20 * U, 20 * U, 15 * U + 1, 8 * U, 3 * U, U, rnd.randint(U, 31 * U)))
        ang = rnd.uniform(-0.5, 0.5)
        ws.mon_momx[m], ws.mon_momy[m] = int(mag * math.cos(ang)), int(mag * math.sin(ang))
        live = rnd.random() < 0.85
        ws.mon_shootable[m] = int(live)
        ws.mon_solid[m] = int(live or rnd.random() < 0.3)
        ws.sk_fly[k] = int(live and rnd.random() < 0.7)
        ws.sk_z[k] = (ws.mon_floorz[m] << 16) + rnd.choice((0, rnd.randint(1, 40 << 16), 30 << 16))
        ws.sk_momz[k] = rnd.choice((0, rnd.randint(-6 << 16, 6 << 16), rnd.randint(1, 6 << 16)))
        body += LS._scene_lines(c, rec) + LS._fj_scene_extra(c, rec)
        body += sum((LS._place(c, j) for j in moved), []) + LS._player_lines(c) + _facing_lines(c, m)
        body += ["hex.set 2, kb_live, %d" % sum(1 for j in range(c.n) if ws.mon_momx[j] or ws.mon_momy[j])]
        c.calls = []
        x0 = ws.mon_x[m]
        due = w._soul_xy(m, TicEvents(0))
        stats["xy_tele"] += (ws.mon_x[m], ws.mon_y[m]) == tel.dest
        stats["xy_cross"] += ws.mon_x[m] > tel.coord >= x0
        body += (["stl.fcall sks%d, sks_ret" % k] + LS._xy_print(c, m)
                 + ["hex.print_as_digit 8, sk_z + %d*dw, 0" % (8 * k), "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                    "stl.output 10"])
        want.append("".join(c.calls) + LS._xy_row(c, m, due) + "%08x%x" % (ws.sk_z[k] & M32, ws.mon_facing[m]))
        ws.mon_momx[m] = ws.mon_momy[m] = 0
        body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)] + LS._undo_extra(c, rec)


def _move_records(c, rnd, body, want, stats):
    from doomfj.sectorcode import msec_cell
    w, ws = c.w, c.w.ws
    for r in range(N_MOVE):
        rec, moved, m, k, tel = _scene_at_line(c, rnd)
        d = rnd.choice((0, 0, 0, 1, 7))                    # east, or a diagonal east
        ws.mon_movedir[m] = d
        ws.sk_z[k] = (ws.mon_floorz[m] << 16) + rnd.choice((0, rnd.randint(1, 30) << 16, rnd.randint(-8, 30) << 16))
        ws.sk_inf[k] = int(rnd.random() < 0.3)
        ws.sk_momz[k] = rnd.choice((0, rnd.randint(-6 << 16, 6 << 16)))
        ws.mon_momx[m], ws.mon_momy[m] = rnd.choice(((0, 0), (rnd.randint(-U, U), rnd.randint(-U, U))))
        ws.mon_shootable[m] = ws.mon_solid[m] = 1
        body += LS._scene_lines(c, rec) + LS._fj_scene_extra(c, rec)
        body += sum((LS._place(c, j) for j in moved), []) + LS._player_lines(c) + _facing_lines(c, m)
        ok = w._p_move(m, TicEvents(0))
        stats["mv_tele"] += (ws.mon_x[m], ws.mon_y[m]) == tel.dest
        tp = dict(knock=True, momz="sk_momz + %d*dw" % (8 * k))      # monstercode's mv dict for a soul slot
        body += ["hex.mov 4, mm_x, thpos_rt + %d*dw" % (16 * m + 4), "hex.mov 4, mm_y, thpos_rt + %d*dw" % (16 * m + 12),
                 "hex.mov 4, mm_z, mon_floorz + %d*dw" % (4 * m), "hex.sign_extend 8, 4, mm_z",
                 "hex.set 2, mm_r, 16", "hex.zero 1, mm_r30", "hex.zero 1, mm_spd", "hex.set 1, mm_dir, %d" % d,
                 "hex.set w/4, mm_tw, %d" % m, "hex.zero w/4, mm_leafw",
                 "hex.mov 3, mm_leafw, thss_rt + %d*dw" % (16 * m),
                 "hex.mov %d, mm_sec, %s" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles)),
                 *SC.move_context_lines(w, m, False),
                 "hex.zero 1, mon_solid + %d*dw" % m,
                 "stl.fcall mm_move, mm_ret",
                 *[ln.replace("tpb%d_n" % m, "tpb%d_n_r%d" % (m, r)) for ln in MC._tele_back(m, w.schema, tp)],
                 *SC.move_context_lines(w, m, True),
                 "hex.set 1, mon_solid + %d*dw, 1" % m,
                 "hex.mov 4, thpos_rt + %d*dw, mm_x" % (16 * m + 4), "hex.mov 4, thpos_rt + %d*dw, mm_y" % (16 * m + 12),
                 "hex.mov 4, mon_floorz + %d*dw, mm_z" % (4 * m), "hex.mov 3, thss_rt + %d*dw, mm_leafw" % (16 * m),
                 "hex.mov %d, %s, mm_sec" % (w.sec_nibbles, msec_cell(m, w.sec_nibbles)),
                 "hex.print_as_digit 1, mm_ok, 0", "hex.print_as_digit 1, mm_dir, 0",
                 "hex.print_as_digit 4, mm_x, 0", "hex.print_as_digit 4, mm_y, 0", "hex.print_as_digit 4, mm_z, 0",
                 "hex.print_as_digit 3, mm_leafw, 0",
                 "hex.print_as_digit 8, sk_z + %d*dw, 0" % (8 * k), "hex.print_as_digit 1, sk_inf + %d*dw, 0" % k,
                 "hex.print_as_digit 4, sk_ceil + %d*dw, 0" % (4 * k),
                 "hex.print_as_digit 8, sk_momz + %d*dw, 0" % (8 * k), "hex.print_as_digit 1, mon_facing + %d*dw, 0" % m,
                 "hex.print_as_digit 8, mkx + %d*dw, 0" % (8 * m), "hex.print_as_digit 8, mky + %d*dw, 0" % (8 * m),
                 "hex.print_as_digit 4, mfx + %d*dw, 0" % (4 * m), "hex.print_as_digit 4, mfy + %d*dw, 0" % (4 * m)]
        body += ["hex.print_as_digit 1, lreq + %d*dw, 0" % j for j in range(len(w.lift_order))] + ["stl.output 10"]
        want.append("%x%x%04x%04x%04x%03x%08x%x%04x%08x%x%08x%08x%04x%04x" % (
            int(ok), ws.mon_movedir[m], ws.mon_x[m] & 0xFFFF, ws.mon_y[m] & 0xFFFF, ws.mon_floorz[m] & 0xFFFF,
            ws.mon_leaf[m], ws.sk_z[k] & M32, ws.sk_inf[k], ws.sk_ceil[k] & 0xFFFF, ws.sk_momz[k] & M32,
            ws.mon_facing[m], ws.mon_momx[m] & M32, ws.mon_momy[m] & M32, ws.mon_fx[m], ws.mon_fy[m])
            + "".join("%x" % ws.l_req[j] for j in range(len(w.lift_order))))
        ws.mon_momx[m] = ws.mon_momy[m] = 0
        body += ["hex.zero 8, mkx + %d*dw" % (8 * m), "hex.zero 8, mky + %d*dw" % (8 * m)] + LS._undo_extra(c, rec)


def build(tmp_path, name, mut=None):
    import re
    from doomfj.config import Config
    from doomfj.wall_renderer import hoisted_scratch_fj
    c = Tv()
    c.record_damage()
    stats = {"xy_tele": 0, "xy_cross": 0, "mv_tele": 0}
    body, want = ["stl.startup_and_init_all"], []
    _xy_records(c, random.Random(0x50E1), body, want, stats)
    _move_records(c, random.Random(0x50E2), body, want, stats)
    body += ["stl.loop"]
    decls, code, tables = _program(c, knock_tele=mut != "no_knock_tele")
    prog = NL.join(body + decls + [code] + tables) + NL + hoisted_scratch_fj()
    for old, new in MUTANTS.get(mut, ()):
        if old.startswith("re:"):
            prog, k = re.subn(old[3:], new, prog)
        else:
            k = prog.count(old)
            prog = prog.replace(old, new)
        assert k >= 1, (mut, old)
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (LS.FJ / "projection.fj").resolve(),
            (LS.FJ / "frame_render.fj").resolve(), (LS.FJ / "sim.fj").resolve(), p.resolve()]
    return c, stats, srcs, (NL.join(want) + NL).encode()


def run(tmp_path, name, mut=None):
    c, stats, srcs, want = build(tmp_path, name, mut)
    return c, stats, fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                                     should_raise_assertion_error=False)


def test_the_synthetic_lines_reach_the_lifts_and_the_records_teleport(tmp_path):
    c, stats, _srcs, _want = build(tmp_path, "soultele_cov")
    assert sum(t.dest_moves for t in c.tels) == 2 and sum(not t.dest_moves for t in c.tels) == 1
    assert stats["xy_tele"] >= 15 and stats["mv_tele"] >= 15, stats
    assert stats["xy_cross"] > stats["xy_tele"], ("no crossing was refused (a stomp, the radius margin)", stats)


def test_a_soul_teleports_as_the_model(tmp_path):
    _c, stats, ok = run(tmp_path, "soultele")
    assert ok, stats


@pytest.mark.parametrize("mut", sorted(MUTANTS) + ["no_knock_tele"])
def test_control_a_broken_soul_teleport_is_caught(tmp_path, mut):
    _c, _stats, ok = run(tmp_path, "soultele_" + mut, mut)
    assert not ok, "the mutant %s went unnoticed" % mut
