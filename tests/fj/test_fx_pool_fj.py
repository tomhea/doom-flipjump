"""M7 P5 (doomfj.projcode): the BLOOD pool on the real flipjump engine, driven through its real caller -- damagecode's
dm_go / dm_leaf with the blood on (`damage_parts(fx=True)`: the REORDERED leaf -- the reach, then fx_spawn, then the
target's checks) -- and fx_phase, against the model's `_line_attack` -> `_spawn_fx_at_target` / `damage_monster` and
`_fx_phase` (World(monsters="decide", player=PLAYER): the player mode whose hits spawn blood).

Each record pokes ONE monster slot's cells (as test_monster_damage_fj: health around 0 and the hit's damage, shootable
or not, the states, the stream), its position, the player at an offset in every octant -- on the octant boundaries
(|dy| * 256 == |dx| * 106, a tie that goes to the axis), on the target itself, within and beyond the reach -- and a
damage from 1 to 20 with the BLOOD2 / BLOOD3 bounds (8, 9, 12, 13) weighted; shoots it; then runs 0 .. 3 fx phases
(few enough that the two-slot pool fills and a hit is skipped). The point location is stubbed as in
test_fireball_pool_fj (its query printed, the model's leaf read from stdin). After every record: the slot's cells,
both blood slots (active, x, y, state, tics, thpos_rt row, thss_rt leaf) and rng_fx; every 8th record the leaf lists.

R9 (each must part): FX_STEP's octant rotated by one, the BLOOD2 bounds moved (9 -> 10, 12 -> 13), a draw taken when
the pool is full, and the OLD order (the target's checks before the blood: a dead target would get none).
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import damagecode as DC
from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj import monsterdecide as MD
from doomfj import projcode as PC
from doomfj.collision import point_location_decls
from doomfj.combat import MISSILERANGE_U, PUNCH_REACH, SAW_REACH
from doomfj.config import Config
from doomfj.harness import W
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.weaponcode import DM_CELLS
from doomfj.world import FIREBALL_POOL, FX_POOL, PLAYER_MODES, TicEvents, World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
N = 400
LIST_EVERY = 8
M32 = 0xFFFFFFFF
# the player mode whose hits spawn blood: "fx" (P5, agent A's) once the model has it; "full" spawns it the same way
PLAYER = "fx" if "fx" in PLAYER_MODES else "full"
CELLS = (("mon_health", 3), ("mon_shootable", 1), ("mon_state", 2), ("mon_tics", 1), ("mon_rng", 2),
         ("mon_threshold", 2), ("mon_reaction", 1), ("mon_target", 1), ("mon_justhit", 1), ("mon_solid", 1))
TIES = ((128, 53), (53, 128), (256, 106), (106, 256), (128, 54), (54, 128), (0, 0), (5, 0), (0, 7), (7, 7))


def _world():
    return World(monsters="decide", sight_rule="seen", player=PLAYER)


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _records(w):
    """[(slot, pokes, (x, y), (px16, py16), dmg, melee, reach, fx phases after)]"""
    rnd = random.Random(0xB10D)
    n = w.layout.nmon
    act = [m for m in range(n) if w.ws.mon_active[m]]
    out = []
    for r in range(N):
        m = rnd.choice(act)
        info = w.mon_info[m]
        dmg = rnd.choice((8, 9, 12, 13, rnd.randint(1, DC.DM_MAX), rnd.randint(1, DC.DM_MAX)))
        hp = rnd.choice((dmg, dmg - 1, dmg + 1, 1, 0, -2, rnd.randint(1, info.spawnhealth), info.spawnhealth))
        st = rnd.choice((info.spawnstate, info.spawnstate, info.seestate, info.painstate))
        pokes = {"mon_health": hp, "mon_shootable": int(rnd.random() < 0.8), "mon_state": gd.STATE_INDEX[st],
                 "mon_tics": rnd.randint(1, 14), "mon_rng": rnd.randrange(256),
                 "mon_threshold": rnd.choice((0, 0, 1, gd.BASETHRESHOLD)),
                 "mon_reaction": rnd.randrange(16), "mon_target": rnd.randrange(2), "mon_justhit": rnd.randrange(2)}
        melee = int(rnd.random() < 0.25)
        reach = rnd.choice((PUNCH_REACH, SAW_REACH)) if melee else rnd.randrange(256)
        x, y = rnd.randint(-1500, 3000), rnd.randint(-3000, 1500)
        k = rnd.randrange(4)
        if k == 0:                                  # an octant boundary or the target itself
            dx, dy = rnd.choice(TIES)
        elif k == 1:                                # beyond the reach: no blood
            lim = reach if melee else MISSILERANGE_U
            dx, dy = lim + rnd.randint(1, 40), rnd.randint(0, 30)
        else:
            dx, dy = rnd.randint(0, 60 if melee else 900), rnd.randint(0, 60 if melee else 900)
        dx, dy = dx * rnd.choice((1, -1)), dy * rnd.choice((1, -1))
        if rnd.random() < 0.5:
            dx, dy = dy, dx
        px16 = (((x + dx) << 16) | rnd.randrange(1 << 16)) & M32
        py16 = (((y + dy) << 16) | rnd.choice((0, rnd.randrange(1 << 16)))) & M32
        phases = rnd.choice((0, 1, 3, 6, 8, 10))
        out.append((m, pokes, (x, y), (px16, py16), dmg, melee, reach, phases))
    return out


def _apply(w, rec, ev):
    m, pokes, (x, y), (px16, py16), dmg, melee, reach, phases = rec
    ws = w.ws
    ws.px, ws.py = _s32(px16), _s32(py16)
    for f, v in pokes.items():
        getattr(ws, f)[m] = v
    ws.mon_x[m], ws.mon_y[m] = x, y
    w.aim = lambda world, col, _m=m: ("mon", _m)
    w._line_attack("fist" if melee else "pistol", w.aim_centre, dmg, reach if melee else MISSILERANGE_U, ev)
    for _ in range(phases):
        w._fx_phase(ev)


def _row(w, m):
    ws = w.ws
    s = "".join("%0*x" % (nib, getattr(ws, f)[m] & (16 ** nib - 1)) for f, nib in CELLS)
    for k in range(FX_POOL):
        s += "%x%08x%08x%02x%x%08x%08x%03x" % (ws.fx_active[k], ws.fx_x[k] & M32, ws.fx_y[k] & M32, ws.fx_state[k],
                                               ws.fx_tics[k], ws.fx_y[k] & M32, ws.fx_x[k] & M32, ws.fx_leaf[k])
    return s + "%02x" % ws.rng_fx


def _lists(w):
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks)) for leaf, ks in sorted(w.leaf_lists().items()))


def _model(records):
    """-> (the expected output, the stdin feed: per record the leaves of its point locations)"""
    w = _world()
    log, feed = [], []
    orig = w._leaf16

    def leaf16(x16, y16):
        leaf = orig(x16, y16)
        log.append("p%010x%010x" % ((x16 >> 16) & 0xFFFFFFFFFF, (y16 >> 16) & 0xFFFFFFFFFF))
        feed.append(struct.pack("<H", leaf))
        return leaf
    w._leaf16 = leaf16
    lines = []
    for r, rec in enumerate(records):
        _apply(w, rec, TicEvents(0))
        lines.append("".join(log) + _row(w, rec[0]))
        log.clear()
        if r % LIST_EVERY == LIST_EVERY - 1:
            lines.append(_lists(w))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed)


def leaf_dump_lines(nleaf: int) -> list:
    """test_fireball_pool_fj's ll_dump: every leaf with a list, "lll:" then its runtime things -- one loop"""
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


MUTANTS = ("octant", "lo9", "hi12", "skipdraw", "oldorder")


def _mutate(text, mut):
    def sub(old, new):
        assert text.count(old) == 1, (mut, old, text.count(old))
        return text.replace(old, new)
    if mut == "octant":
        old = ", ".join("fx_o%d" % d for d in range(8))
        return sub("sim.jump16 mm_fa, " + old, "sim.jump16 mm_fa, " + ", ".join("fx_o%d" % ((d + 1) % 8)
                                                                               for d in range(8)))
    if mut == "lo9":
        return sub("    hex.set 2, pw_c, 9\n", "    hex.set 2, pw_c, 10\n")
    if mut == "hi12":
        return sub("    hex.set 2, pw_c, 12\n", "    hex.set 2, pw_c, 13\n")
    if mut == "skipdraw":
        return sub("  fx_skip:\n", "  fx_skip:\n    hex.inc 2, rng_fx\n")
    if mut == "oldorder":
        call = "".join(ln + "\n" for ln in DC.FX_CALL)
        checks = ("    hex.if0 1, dm_sh, dm_out\n    hex.if_flags dm_hp + 2*dw, 0xFF00, dm_pos, dm_out\n  dm_pos:\n"
                  "    hex.if0 3, dm_hp, dm_out\n")
        return sub(call + checks, checks + call)
    return text


def _build(tmp_path, name, mut=None):
    w = _world()
    n, nleaf, schema, ws = w.layout.nmon, len(w.cmap.subsectors), w.schema, w.ws
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    records = _records(w)
    want, feed = _model(records)
    dp = DC.damage_parts(w, slot_rt=list(range(n)), boot_skill=ws.skill, fx=True)
    code = "\n".join(MC.dist_leaf_lines() + dp["lines"] + MD.octant_leaf_lines() + PC.fx_lines(nt=nt)
                     + PC.pool_tic_lines()) + "\n"
    code = _mutate(code, mut)
    head, nxt = [0] * nleaf, [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    nib = {f: MC.cell_nibbles(schema, f) for f, _ in CELLS}
    assert all(nib[f] == k for f, k in CELLS), nib
    body = ["stl.startup_and_init_all"]
    for r, (m, pokes, (x, y), (px16, py16), dmg, melee, reach, phases) in enumerate(records):
        body += ["hex.set 8, viewx, %d" % px16, "hex.set 8, viewy, %d" % py16]
        body += ["hex.set %d, %s + %d*dw, %d" % (nib[f], f, nib[f] * m, v & (16 ** nib[f] - 1))
                 for f, v in pokes.items()]
        body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 4, x & 0xFFFF),
                 "hex.set 4, thpos_rt + %d*dw, %d" % (16 * m + 12, y & 0xFFFF),
                 "hex.set 2, dm_id, %d" % (m + 1), "hex.set 2, dm_dmg, %d" % dmg,
                 "hex.set 1, dm_melee, %d" % melee, "hex.set 2, dm_reach, %d" % reach,
                 "stl.fcall dm_go, dm_ret"]
        body += ["stl.fcall fx_phase, fx_pret"] * phases
        body += ["hex.set 2, dmp_m, %d" % m, "stl.fcall rec_dump, dump_ret"]
        if r % LIST_EVERY == LIST_EVERY - 1:
            body += ["stl.fcall ll_dump, dump_ret"]
    body += ["stl.loop"]
    # the record's dump: the slot's cells (a jump on the slot to its own print stub), the pool, rng_fx
    dump = ["rec_dump:", "    sim.jump16 dmp_m + 1*dw, " + ", ".join("dmp_h%d" % h if 16 * h < n else "dmp_end"
                                                                        for h in range(16))]
    for h in range((n + 15) // 16):
        dump += ["  dmp_h%d:" % h, "    sim.jump16 dmp_m, " + ", ".join("dmp_s%d" % (16 * h + l) if 16 * h + l < n
                                                                         else "dmp_end" for l in range(16))]
    for m in range(n):
        dump += ["  dmp_s%d:" % m] + ["    hex.print_as_digit %d, %s + %d*dw, 0" % (k, f, k * m) for f, k in CELLS]
        dump += ["    ;dmp_end"]
    dump += ["  dmp_end:"]
    for s in range(FX_POOL):
        t = nt + FIREBALL_POOL + s
        dump += ["    hex.print_as_digit 1, fx_act + %d*dw, 0" % s,
                 "    hex.print_as_digit 8, fx_x + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, fx_y + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 2, fx_st + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 1, fx_ti + %d*dw, 0" % s,
                 "    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    hex.print_as_digit 2, rng_fx, 0", "    stl.output 10", "    stl.fret dump_ret"]
    stubs = ["ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0",
             "    hex.print_as_digit 10, pty, 0", "    hex.zero w/4, ptss", "    hex.input 2, ptss",
             "    stl.fret ptloc_ret"]
    vals = {f: list(getattr(ws, f)[:n]) for f in MC.P31_FIELDS + MC.P32A_FIELDS + MC.P32B_FIELDS}
    decls = (MC.monster_decls(schema, n, {f: vals[f] for f in MC.P31_FIELDS})
             + MC.p32a_decls(schema, n, {**{f: vals[f] for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n)
             + MC.p32b_decls(schema, n, {f: vals[f] for f in MC.P32B_FIELDS}, [0] * n)
             + MC.P32A_SCRATCH + dp["decls"] + MD.context_decls() + PC.pool_decls()
             + point_location_decls() + LEAF_LINK_DECLS
             + ["%s: hex.vec %d" % cn for cn in DM_CELLS]
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "lvdone: hex.vec 1", "dmp_m: hex.vec 2",
                "dump_ret: hex.vec w/4", "dl_i: hex.vec w/4", "dl_n: hex.vec w/4",
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32)
                                                                 << 32) << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    prog = "\n".join(body + decls + dump + leaf_dump_lines(nleaf) + stubs + [code] + dp["tables"]
                     + PC.tables_fj()) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, feed, want


def _run(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_records_exercise_every_path():
    """the model's own events: blood of all three kinds (and at the 8/9 and 12/13 bounds), every octant, the octant
    ties, a full pool skipping a hit, blood on a dead or unshootable target (the reorder's bite), out-of-reach hits
    with none, removals"""
    from doomfj.world import octant_of
    w = _world()
    ws = w.ws
    seen = dict(b1=0, b2=0, b3=0, d8=0, d9=0, d12=0, d13=0, skipped=0, dead_target=0, far=0, removals=0, ties=0)
    octs = set()
    for rec in _records(w):
        m, pokes, (x, y), (px16, py16), dmg, melee, reach, phases = rec
        before = list(ws.fx_active)
        dead = not pokes["mon_shootable"] or pokes["mon_health"] <= 0
        ev = TicEvents(0)
        _apply(w, rec, ev)
        d = aprox_distance(x - (_s32(px16) >> 16), y - (_s32(py16) >> 16))
        if d > (reach if melee else MISSILERANGE_U):
            seen["far"] += 1
            assert not ev.fx_spawns and not ev.fx_skipped
            continue
        seen["skipped"] += ev.fx_skipped
        for _slot, _kind in ev.fx_spawns:
            seen["b2" if 9 <= dmg <= 12 else "b3" if dmg < 9 else "b1"] += 1
            seen["d%d" % dmg] = seen.get("d%d" % dmg, 0) + 1
            seen["dead_target"] += dead
            dx, dy = (_s32(px16) >> 16) - x, (_s32(py16) >> 16) - y
            octs.add(octant_of(dx, dy))
            seen["ties"] += (abs(dx), abs(dy)) in {(a, b) for a, b in TIES[:4]}
        seen["removals"] += sum(1 for s in range(FX_POOL) if before[s] and not ws.fx_active[s])
    want = dict(b1=30, b2=30, b3=30, d8=5, d9=5, d12=5, d13=5, skipped=20, dead_target=20, far=20, removals=50, ties=5)
    assert all(seen[k] >= v for k, v in want.items()), (seen, want)
    assert octs == set(range(8)), octs


def test_the_blood_pool_follows_the_model(tmp_path):
    assert _run(tmp_path, "fxpool"), "the fj blood pool parted from the model's"


@pytest.mark.parametrize("mut", MUTANTS)
def test_control_a_broken_blood_pool_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "fxpool_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
