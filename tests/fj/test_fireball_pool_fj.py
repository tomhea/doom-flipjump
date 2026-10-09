"""M7 P5 (doomfj.projcode): the FIREBALL pool on the real flipjump engine -- `pj_spawn` / `pj_phase`, the very text the
emitter splices (with the missile cells, the point location, the leaf lists and the dispatch tables), against the
model's own `_spawn_fireball` and `_projectiles_phase` (World(monsters="full", player="full")).

THE SCRIPT (fed on stdin, one record a frame -- one image, every frame in turn): scenes of 12 to 40 frames, each a
shooter (a monster's spawn point) and a player around it -- in the open, across a door (the doors' states change
every frame), on an AXIS from the shooter (R_PointToAngle2's axis quirks: the flipped angle's fine index differs
there), and at the EXACT box distance (an east shot meets the player exactly 22 units away on a tic). The player's
health and death flag change by scene: a dead player lets the fireballs through. Each frame spawns 0..3 fireballs (a
full pool fizzles), then runs the phase. The model's `damage_player` is replaced by a recorder, as the fj's `dp_go`
(agent B's) is by a stub that prints the damage: the pool alone is under test, and the player's health is the
script's.

After every frame: every slot's cells (active, x, y, momentum, state, tics), its runtime thing's thpos_rt row and
thss_rt leaf, and rng_fx; every 8th frame and at the end every leaf's list (the runtime things linked, monsters
included -- the lists hold mobile k as runtime thing k: nt = the monster slots).

R9 (each must part from the model): the highest free slot, a pool of 9, the angle flipped from the player's
(the rotation leaf's), `<=` in the box, no relink, no half step, an explosion without its draw.
"""
import math
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import projcode as PC
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import (generate_dispatch_table_fj, generate_tantoangle_lut_fj,
                                  generate_trig_idioms_fj)
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.things import LEAF_LINK_DECLS, byte_array_decl
from doomfj.wall_renderer import hoisted_scratch_fj
from doomfj.world import FIREBALL_POOL, FX_POOL, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
FRAMES = 1500
LIST_EVERY = 8


def _world():
    return World(monsters="full", player="full")


def _s32(v):
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def _open_east(w):
    """a shooter spot (a monster's spawn point) with no wall for 130 units east: the exact-box scene's"""
    for m in range(w.layout.nmon):
        x, y = w.ws.mon_x[m], w.ws.mon_y[m]
        if not any(w.missile_lines_block((x + d) << 16, y << 16) for d in range(0, 131, 2)):
            return x, y
    raise AssertionError("no open east run")


def _script(w):
    """[(px16, py16, p_hp, p_dead, door states, lift states, fswitch, [(mm_x, mm_y)], dump lists)]"""
    rnd = random.Random(0x5F1B)
    n = w.layout.nmon
    spots = [(w.ws.mon_x[m], w.ws.mon_y[m]) for m in range(n)]
    V = w.cmap.vertexes
    door_mids = []
    for d, si in enumerate(w.door_order):
        for li in w.door_lines.get(si, ()):
            ld = w.lds[li]
            (ax, ay), (bx, by) = V[ld.v1], V[ld.v2]
            door_mids.append(((ax + bx) // 2, (ay + by) // 2, bx - ax, by - ay))
    east = _open_east(w)
    out, f = [], 0
    kinds = ["open", "door", "axis", "open", "exact", "door", "dead", "axis", "open", "blank"]
    sc = 0
    while f < FRAMES:
        kind = kinds[sc % len(kinds)]
        sc += 1
        length = rnd.randint(12, 40)
        hp, dead = rnd.choice((100, 100, 100, 37, 1)), 0
        if kind == "dead":
            hp, dead = rnd.choice(((100, 1), (0, 0), (-5, 0), (100, 1)))
        if kind == "door":
            mx, my, ldx, ldy = rnd.choice(door_mids)
            ln = math.hypot(ldx, ldy) or 1.0
            nx, ny = -ldy / ln, ldx / ln
            a, b = rnd.randint(40, 120), rnd.randint(30, 160)
            shooter = (int(mx + nx * a), int(my + ny * a))
            target = ((mx - nx * b) * 65536, (my - ny * b) * 65536)
        elif kind == "exact":
            shooter = east
            target = ((east[0] + 107) << 16, east[1] << 16)
        else:
            shooter = rnd.choice(spots)
            if kind == "blank":              # point blank: the spawn's own try meets the player (P_CheckMissileSpawn)
                ang = rnd.random() * 2 * math.pi
                dist = rnd.uniform(4, 27)
                target = ((shooter[0] + dist * math.cos(ang)) * 65536, (shooter[1] + dist * math.sin(ang)) * 65536)
            elif kind == "axis":
                d = rnd.randint(40, 250) * rnd.choice((1, -1))
                target = (((shooter[0] + d) << 16), shooter[1] << 16) if rnd.random() < 0.5 else \
                         (shooter[0] << 16, (shooter[1] + d) << 16)
            else:
                ang = rnd.random() * 2 * math.pi
                dist = rnd.randint(30, 200)
                target = ((shooter[0] + dist * math.cos(ang)) * 65536, (shooter[1] + dist * math.sin(ang)) * 65536)
        px, py = int(target[0]), int(target[1])
        dstates = [rnd.randrange(w.door_nstates[si]) for si in w.door_order]
        for i in range(length):
            if f >= FRAMES:
                break
            if kind == "door":
                dstates = [(v + 1) % w.door_nstates[si] if rnd.random() < 0.3 else v
                           for v, si in zip(dstates, w.door_order)]
            elif kind == "open" and i % 6 == 5:
                px += rnd.randint(-8 << 16, 8 << 16)
                py += rnd.randint(-8 << 16, 8 << 16)
            lstates = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
            r = rnd.random()
            nsp = 0 if r < 0.55 else 1 if r < 0.9 else 2 if r < 0.98 else 3
            if kind == "exact":
                nsp = 1 if i == 0 else 0
            near = [q for q in spots if abs(q[0] - (px >> 16)) + abs(q[1] - (py >> 16)) < 400] or [shooter]
            sp = [shooter if k == 0 else rnd.choice(near) for k in range(nsp)]
            out.append((px & M32, py & M32, hp, dead, dstates, lstates, rnd.randrange(2), sp,
                        f % LIST_EVERY == LIST_EVERY - 1 or f == FRAMES - 1))
            f += 1
    return out


def _apply_frame(w, rec, ev):
    """the model's frame (the census's: `_model` is the harness's own copy with the feed)"""
    px16, py16, hp, dead, dstates, lstates, fsw, sp, _lists = rec
    ws = w.ws
    ws.px, ws.py = _s32(px16), _s32(py16)
    ws.p_health, ws.p_dead = hp, dead
    for d, v in enumerate(dstates):
        ws.d_state[d] = v
    for k, v in enumerate(lstates):
        ws.l_state[k] = v
    ws.f_switch = fsw
    w._door_phase_scene()
    for x, y in sp:
        ws.mon_x[0], ws.mon_y[0] = x, y
        w._spawn_fireball(0, ev)
    w._projectiles_phase(ev)


def _row(w, nt):
    ws = w.ws
    s = ""
    for k in range(FIREBALL_POOL):
        s += "%x%08x%08x%08x%08x%02x%x" % (ws.proj_active[k], ws.proj_x[k] & M32, ws.proj_y[k] & M32,
                                          ws.proj_momx[k] & M32, ws.proj_momy[k] & M32, ws.proj_state[k],
                                          ws.proj_tics[k])
        s += "%02x" % (ws.proj_src[k] + 1 if ws.proj_active[k] else 0)        # M7 P7: the shooter (1 + slot)
        # the runtime thing's row: the WHOLE-UNIT position (the fraction cleared -- docs/gp-p5-interface.md, THE
        # MOBILE ROWS: monsters.MonsterViews.rt_state's), and the leaf
        s += "%08x%08x%03x" % (ws.proj_y[k] & M32 & ~0xFFFF, ws.proj_x[k] & M32 & ~0xFFFF, ws.proj_leaf[k])
    return s + "%02x" % ws.rng_fx


def _lists(w):
    return "".join("%03x:%s" % (leaf, ",".join("%02x" % k for k in ks)) for leaf, ks in sorted(w.leaf_lists().items()))


def _hooks(w, log, feed):
    """the model's side of the harness's two stubs: `damage_player` appends "hDD" to `log` (dp_go's stub prints it);
    every point location the FJ makes appends "p" + its ptx, pty (10 nibbles each) to `log` and the leaf (2 bytes) to
    `feed` (ptloc_walk's stub prints the query and reads the leaf). The fj locates a spawn once; the model's
    `_missile_try` at the spawn position locates it again (an unchanged leaf) -- that second one is not the fj's."""
    orig_leaf, orig_try, orig_spawn = w._leaf16, w._missile_try, w._spawn_fireball
    st = {"spawn": False, "skip": False}

    def leaf16(x16, y16):
        leaf = orig_leaf(x16, y16)
        if not st["skip"]:
            log.append("p%010x%010x" % ((x16 >> 16) & 0xFFFFFFFFFF, (y16 >> 16) & 0xFFFFFFFFFF))
            feed.append(struct.pack("<H", leaf))
        return leaf

    def mtry(slot, nx, ny, ev):
        st["skip"] = st["spawn"]
        try:
            return orig_try(slot, nx, ny, ev)
        finally:
            st["skip"] = False

    def spawn(m, ev):
        st["spawn"] = True
        try:
            orig_spawn(m, ev)
        finally:
            st["spawn"] = False
    w._leaf16, w._missile_try, w._spawn_fireball = leaf16, mtry, spawn
    # M7 P7: and the attacker the hit names (1 + the shooter's slot)
    w.damage_player = lambda dmg, source, inflictor, ev: log.append("h%02x%02x" % (dmg, source[1] + 1))


def _model(script, nt):
    """-> (the expected output, the stdin feed): per frame the pokes, each spawn's (mm_x, mm_y) followed -- for a
    spawn the model's pool takes -- by the angle the stubbed point_to_angle line reads and the spawn's leaf, then the
    phase's leaves, then the list-dump flag"""
    w = _world()
    log, feed = [], []
    _hooks(w, log, feed)
    ws = w.ws
    lines = []
    for rec in script:
        px16, py16, hp, dead, dstates, lstates, fsw, sp, lists = rec
        ds = list(dstates) + [0] * (len(dstates) & 1)
        ls = list(lstates) + [0] * (len(lstates) & 1)
        feed.append(bytes([0xD0]) + struct.pack("<II", px16, py16) + struct.pack("<H", (hp & 0xFFF) | (dead << 12))
                    + bytes(ds[2 * i] | ds[2 * i + 1] << 4 for i in range(len(ds) // 2))
                    + bytes(ls[2 * i] | ls[2 * i + 1] << 4 for i in range(len(ls) // 2)) + bytes([fsw, len(sp)]))
        ws.px, ws.py = _s32(px16), _s32(py16)
        ws.p_health, ws.p_dead = hp, dead
        for d, v in enumerate(dstates):
            ws.d_state[d] = v
        for k, v in enumerate(lstates):
            ws.l_state[k] = v
        ws.f_switch = fsw
        w._door_phase_scene()
        ev = TicEvents(0)
        for x, y in sp:
            feed.append(struct.pack("<HH", x & 0xFFFF, y & 0xFFFF))
            ws.mon_x[0], ws.mon_y[0] = x, y
            if not all(ws.proj_active):
                feed.append(struct.pack("<I", w.rm.point_to_angle(x << 16, y << 16, ws.px, ws.py)))
            w._spawn_fireball(0, ev)
        w._projectiles_phase(ev)
        feed.append(bytes([int(lists)]))
        lines.append("".join(log) + _row(w, nt))
        log.clear()
        if lists:
            lines.append(_lists(w))
    return ("\n".join(lines) + "\n").encode(), b"".join(feed) + bytes([0])


def leaf_dump_lines(nleaf: int) -> list:
    """`ll_dump` (stl.fcall ll_dump, dump_ret): every leaf with a list, "lll:" then its runtime things ("tt," each) in
    list order, then a newline -- ONE loop over the leaves (an unrolled dump per leaf costs the harness gigabytes)"""
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


MUTANTS = ("highest", "pool9", "boxle", "norelink", "nohalf", "nodraw",
           "nosrc", "srcfree")        # M7 P7: the impact names no attacker; a freed slot keeps its shooter
ANGLE = "    proj.point_to_angle pw_ang, pw_x, pw_y, viewx, viewy, 1\n"
FLIPPED = "    proj.point_to_angle pw_ang, viewx, viewy, pw_x, pw_y, 1\n    hex.xor_by pw_ang + 7*dw, 8\n"


def _mutate(text, mut):
    def sub(old, new):
        assert text.count(old) == 1, (mut, old, text.count(old))
        return text.replace(old, new)
    if mut == "highest":
        tests = "".join("    hex.if0 1, pj_act + %d*dw, pj_sp%d\n" % (s, s) for s in range(FIREBALL_POOL))
        rev = "".join("    hex.if0 1, pj_act + %d*dw, pj_sp%d\n" % (s, s) for s in reversed(range(FIREBALL_POOL)))
        return sub(tests, rev)
    if mut == "boxle":
        return sub("    hex.scmp 8, pw_c, pj_bd, pj_tb, pj_tl, pj_tl\n", "    hex.scmp 8, pw_c, pj_bd, pj_tb, pj_tb, pj_tl\n")
    if mut == "norelink":
        return sub("    hex.mov 3, pw_leaf, ptss\n    stl.fcall pw_link, pw_lkret\n  pj_lt:\n",
                   "    hex.mov 3, pw_leaf, ptss\n  pj_lt:\n")
    if mut == "nohalf":
        text = sub("  pj_hx_p:\n    hex.add 8, pw_x, pw_c\n", "  pj_hx_p:\n")
        return sub("  pj_hy_p:\n    hex.add 8, pw_y, pw_c\n", "  pj_hy_p:\n")
    if mut == "nosrc":
        return sub("    hex.mov 2, dp_src, pw_src\n", "")
    if mut == "srcfree":
        return sub("    hex.zero 2, pw_src\n", "")
    if mut == "nodraw":
        return sub("    hex.inc 2, rng_fx\n    fxrnd.lookup pw_rr, rng_fx\n    hex.sub 1, pw_ti, pw_rr + 2*dw\n"
                   "    stl.fret pj_eret\n", "    stl.fret pj_eret\n")
    return text


def _build(tmp_path, name, mut=None):
    w = _world()
    n, nleaf = w.layout.nmon, len(w.cmap.subsectors)
    nt = n
    nthings = nt + FIREBALL_POOL + FX_POOL
    script = _script(w)
    want, feed = _model(script, nt)
    pool = 9 if mut == "pool9" else FIREBALL_POOL
    cells, root = PC.missile_cells_fj(w)
    code = "\n".join(PC.pj_lines(nt=nt, root=root, pool=pool) + PC.pool_tic_lines()) + "\n"
    code = _mutate(code, mut)
    # THE ONE STUBBED LINE: the angle comes from stdin (the model's R_PointToAngle2) -- the angle tables would put this
    # harness past its memory bound; test_the_spawn_angle_is_r_pointtoangle2 runs the real line on its own
    assert code.count(ANGLE) == 1
    code = code.replace(ANGLE, "    hex.input 4, pw_ang\n")
    # the level-start lists (monsters only), stored t + 1 in bytes
    head, nxt = [0] * nleaf, [0] * nthings
    for leaf, ks in w.leaf_lists().items():
        head[leaf] = ks[0] + 1
        for a, b in zip(ks, ks[1:] + [-1]):
            nxt[a] = b + 1
    ws = w.ws
    nd, nl = len(w.door_order), len(w.lift_order)
    dump = ["pj_dump:"]
    for s in range(FIREBALL_POOL):
        t = nt + s
        dump += ["    hex.print_as_digit 1, pj_act + %d*dw, 0" % s,
                 "    hex.print_as_digit 8, pj_x + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_y + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_mx + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 8, pj_my + %d*dw, 0" % (8 * s),
                 "    hex.print_as_digit 2, pj_st + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 1, pj_ti + %d*dw, 0" % s,
                 "    hex.print_as_digit 2, pj_src + %d*dw, 0" % (2 * s),
                 "    hex.print_as_digit 16, thpos_rt + %d*dw, 0" % (16 * t),
                 "    hex.print_as_digit 3, thss_rt + %d*dw, 0" % (16 * t)]
    dump += ["    hex.print_as_digit 2, rng_fx, 0", "    stl.output 10", "    stl.fret dump_ret"]
    ll = leaf_dump_lines(nleaf)
    body = ["stl.startup_and_init_all",
            "loop:",
            "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.input 2, hpin", "hex.mov 3, p_hp, hpin", "hex.mov 1, p_dead, hpin + 3*dw",
            "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
            "hex.input 1, fswitch", "hex.input 1, nsp",
            "sp_loop:", "hex.if0 2, nsp, sp_done",
            "hex.input 2, mm_x", "hex.input 2, mm_y",
            "hex.set 2, md_src, 1",                        # M7 P7: the shooter is slot 0, as the model's
            "stl.fcall pj_spawn, pj_sret",
            "hex.dec 2, nsp", ";sp_loop",
            "sp_done:",
            "stl.fcall pj_phase, pj_pret",
            "stl.fcall pj_dump, dump_ret",
            "hex.input 1, wlist", "hex.if0 2, wlist, loop",
            "stl.fcall ll_dump, dump_ret",
            ";loop",
            "done:", "stl.loop",
            # dp_go (agent B's): the stub prints the damage it was given
            "dp_go:", "    stl.output 104", "    hex.print_as_digit 2, dp_dmg, 0",
            "    hex.print_as_digit 2, dp_src, 0", "    hex.zero 2, dp_src", "    stl.fret dp_ret",   # M7 P7
            # ptloc_walk (the binary's shared point location, held to point_in_subsector by test_collision_fj; its
            # 682-node text alone assembles past this harness's memory bound): the stub prints the query and reads
            # the model's leaf
            "ptloc_walk:", "    stl.output 112", "    hex.print_as_digit 10, ptx, 0", "    hex.print_as_digit 10, pty, 0",
            "    hex.zero w/4, ptss", "    hex.input 2, ptss", "    stl.fret ptloc_ret"]
    decls = (PC.pool_decls(pool=pool) + COLLISION_STATE_DECLS + point_location_decls() + LEAF_LINK_DECLS
             + ["wmagic: hex.vec 2", "wlist: hex.vec 2", "nsp: hex.vec 2", "hpin: hex.vec 4",
                "viewx: hex.vec 8", "viewy: hex.vec 8", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
                "p_hp: hex.vec 3", "p_dead: hex.vec 1", "lvdone: hex.vec 1", "dp_dmg: hex.vec 2",
                "dp_src: hex.vec 2", "md_src: hex.vec 2",                   # M7 P7
                "dp_ret: hex.vec w/4", "dump_ret: hex.vec w/4", "dl_i: hex.vec w/4", "dl_n: hex.vec w/4",
                "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)), "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)),
                "fswitch: hex.vec 2",
                "thpos_rt: hex.vec %d, %d" % (16 * nthings, sum(((ws.mon_x[m] << 16) & M32 | ((ws.mon_y[m] << 16) & M32)
                                                                 << 32) << (64 * m) for m in range(n))),
                "thss_rt: hex.vec %d, %d" % (16 * nthings, sum(ws.mon_leaf[m] << (64 * m) for m in range(n))),
                byte_array_decl("sshead", head, 2 * nleaf), byte_array_decl("thnext", nxt, 2 * nthings)])
    tables = PC.tables_fj() + [generate_trig_idioms_fj("finesine", Config().TRIG_N, 16, mode="per_entry")]
    prog = "\n".join(body + decls + dump + ll + [code, cells] + tables) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return srcs, feed, want


def _run(tmp_path, name, mut=None) -> bool:
    srcs, feed, want = _build(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, feed, want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def _angle_cases(w):
    """(mm_x, mm_y, px16, py16): shooters at monster spawn points; players on the four axes (integer and fractional
    along the axis), on the diagonals, at random 16.16 offsets, and on the shooter itself"""
    rnd = random.Random(0xA16)
    out = []
    for m in range(0, w.layout.nmon, 3):
        x, y = w.ws.mon_x[m], w.ws.mon_y[m]
        d = rnd.randint(1, 900)
        for dx, dy in ((d, 0), (-d, 0), (0, d), (0, -d), (d, d), (-d, d), (d, -d), (-d, -d)):
            out.append((x, y, (x + dx) << 16, (y + dy) << 16))
        out.append((x, y, ((x + d) << 16) | rnd.randrange(1 << 16), y << 16))
        out.append((x, y, x << 16, ((y - d) << 16) | rnd.randrange(1 << 16)))
        for _ in range(6):
            out.append((x, y, ((x + rnd.randint(-900, 900)) << 16) | rnd.randrange(1 << 16),
                        ((y + rnd.randint(-900, 900)) << 16) | rnd.randrange(1 << 16)))
    out.append((100, -200, 100 << 16, -200 << 16))
    return out


def _angle_run(tmp_path, name, line) -> bool:
    """the REAL lines of pj_spawn_leaf from its start to the fine index (the shooter's 16.16 position, the angle, the
    index), per case: pw_idx printed against the model's R_PointToAngle2 >> 20 (combat._spawn_fireball's)"""
    w = _world()
    code = "\n".join(PC.pj_lines(nt=0, root="R")) + "\n"
    a = code.index("pj_spawn_leaf:\n")
    b = code.index("    hex.mov 3, pw_idx, pw_ang + 5*dw\n") + len("    hex.mov 3, pw_idx, pw_ang + 5*dw\n")
    unit = code[a:b].replace("pj_spawn_leaf:", "angle_unit:")
    assert unit.count(ANGLE) == 1
    unit = unit.replace(ANGLE, line)
    cases = _angle_cases(w)
    body = ["stl.startup_and_init_all"]
    for k, (x, y, px16, py16) in enumerate(cases):
        body += ["hex.set 4, mm_x, %d" % (x & 0xFFFF), "hex.set 4, mm_y, %d" % (y & 0xFFFF),
                 "hex.set 8, viewx, %d" % (px16 & M32), "hex.set 8, viewy, %d" % (py16 & M32),
                 "stl.fcall angle_unit, au_ret", "hex.print_as_digit 3, pw_idx, 0"]
    body += ["stl.output 10", "stl.loop"]
    data = (["viewx: hex.vec 8", "viewy: hex.vec 8", "mm_x: hex.vec 4", "mm_y: hex.vec 4", "au_ret: hex.vec w/4"]
            + PC.WINDOW_DECLS + [unit + "    stl.fret au_ret",
                                 generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3,
                                                            result_nibbles=8),
                                 generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3,
                                                            result_nibbles=6),
                                 generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)])
    want = ("".join("%03x" % (w.rm.point_to_angle(x << 16, y << 16, _s32(px16), _s32(py16)) >> 20)
                    for x, y, px16, py16 in cases) + "\n").encode()
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + data) + "\n" + hoisted_scratch_fj(), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_spawn_angle_is_r_pointtoangle2(tmp_path):
    assert _angle_run(tmp_path, "pjang", ANGLE), "the spawn's fine angle parted from the model's"


def test_control_the_flipped_angle_is_caught(tmp_path):
    """the rotation leaf's angle (player -> thing, plus ANG180) differs by one BAM on the axes: its fine index too"""
    w = _world()
    assert any(w.rm.point_to_angle(x << 16, y << 16, px, py) >> 20
               != ((w.rm.point_to_angle(px, py, x << 16, y << 16) + 0x80000000) & M32) >> 20
               for x, y, px, py in _angle_cases(w))
    assert not _angle_run(tmp_path, "pjang_flip", FLIPPED), "the flipped angle passed: the comparison is vacuous"


def test_the_script_exercises_every_path():
    """the model's own events over the script: ~300 spawns, fizzles (a full pool), impacts on the player and walls,
    explosions at the spawn, relinks, removals; dead-player frames a fireball flies through; axis shots; the
    exact-box impact -- each control needs its path"""
    w = _world()
    script = _script(w)
    hits = []
    w.damage_player = lambda dmg, source, inflictor, ev: hits.append(dmg)
    tot = dict(spawns=0, fizzles=0, impacts=0, walls=0, early_boom=0, relinks=0, removals=0, through_dead=0,
               axis=0, full_frames=0)
    ws = w.ws
    for rec in script:
        ev = TicEvents(0)
        leaves = list(ws.proj_leaf)
        act = list(ws.proj_active)
        px16, py16, hp, dead = rec[:4]
        _apply_frame(w, rec, ev)
        tot["spawns"] += len(ev.proj_spawns)
        tot["early_boom"] += sum(1 for s, _m in ev.proj_spawns if not (ws.proj_momx[s] or ws.proj_momy[s]))
        tot["fizzles"] += len(ev.fizzles)
        tot["impacts"] += len(ev.proj_impacts)
        tot["walls"] += len(ev.proj_walls)
        tot["relinks"] += sum(1 for s in range(FIREBALL_POOL) if act[s] and ws.proj_active[s]
                              and ws.proj_leaf[s] != leaves[s])
        tot["removals"] += sum(1 for s in range(FIREBALL_POOL) if act[s] and not ws.proj_active[s])
        tot["full_frames"] += all(ws.proj_active)
        for x, y in rec[7]:
            if (x << 16) == _s32(px16) or (y << 16) == _s32(py16):
                tot["axis"] += 1
        if not (hp > 0 and not dead):
            tot["through_dead"] += sum(1 for s in range(FIREBALL_POOL) if ws.proj_active[s]
                                       and abs(ws.px - ws.proj_x[s]) < 22 << 16 and abs(ws.py - ws.proj_y[s]) < 22 << 16)
    want = dict(spawns=280, fizzles=50, impacts=100, walls=100, early_boom=5, relinks=300, removals=280, through_dead=1,
                axis=100, full_frames=100)
    assert all(tot[k] >= v for k, v in want.items()), (tot, want)
    # the spawn-time explosion (P_CheckMissileSpawn) and the exact-box impact, from the model's own runs
    w2 = _world()
    w2.damage_player = lambda dmg, source, inflictor, ev: None
    ex = _open_east(w2)
    w2.ws.mon_x[0], w2.ws.mon_y[0] = ex
    w2.ws.px, w2.ws.py = (ex[0] + 107) << 16, ex[1] << 16
    ev = TicEvents(0)
    w2._spawn_fireball(0, ev)
    for k in range(9):
        w2._projectiles_phase(ev)
        if ev.proj_impacts:
            break
    # the impact refuses the move: the fireball stays where it sat a tic at EXACTLY the box distance, unhit by "<"
    assert ev.proj_impacts and abs(w2.ws.px - w2.ws.proj_x[0]) == 22 << 16 and k == 8, (k, ev.proj_impacts)


def test_the_fireball_pool_follows_the_model(tmp_path):
    assert _run(tmp_path, "pjpool"), "the fj fireball pool parted from the model's"


@pytest.mark.parametrize("mut", MUTANTS)
def test_control_a_broken_pool_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "pjpool_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut


# ---- M7 P8a I (docs/gp-final-plan.md 1.2.2, G-I5; projcode `fight`): FIREBALLS ON THINGS ----------------------------
# 1. THE AIM: the real lines of pj_spawn_leaf's fight emission (the shooter's 16.16 position, the shared angle leaf
#    `ia_leaf` toward the TARGET's mt_tqx / mt_tqy, the fine index), against combat._spawn_fireball's
#    R_PointToAngle2(shooter -> _target_pos16) >> 20 -- monster targets (whole units) and the player (16.16); R9: the
#    aim at the player (viewx / viewy, poked elsewhere) instead of the target.
# 2. THE THINGS: pj_try's fight emission (`pt_lines`: the integer box bounds, the monster slots, the barrels,
#    `pt_thing`) driven with poked records against the model's `_missile_try` (World(monsters="final",
#    player="final")) -- a fireball of an imp at a 16.16 spot with monsters around it at the box's edge (|dx| = r + 6
#    - 1, r + 6, r + 6 + 1, with and without a fraction), alive, dying (solid, not shootable) or fallen (neither), of
#    the shooter's species or not, the shooter itself; barrels standing, exploding or removed; the player alive or
#    dead. The lines are a poke (`sim.check_cells` stubbed to the record's verdict; the model's missile_lines_block
#    returns its negation); the damage leaves are stubs that print each call (dm_go: id, damage, mode, source), as the
#    model's damage_monster / damage_barrel / damage_player are recorders. After each record: pw_ok and rng_fx.
#    R9: the species rule dropped; the shooter not passed; a solid corpse taken for a shootable thing; the box's
#    fraction rule dropped (B - 1 always); barrels passed through; monsters passed through.
from doomfj import gamedata as gd                                                    # noqa: E402
from doomfj import monsterdecide as _MD                                               # noqa: E402

FIGHT_N = 600


def _fworld():
    return World(monsters="final", player="final", sight_rule="seen")


def _imps(w):
    return [m for m, t in enumerate(w.mon_things) if t.type == 3001 and w.ws.mon_active[m]]


def _faim_cases(w):
    rnd = random.Random(0xA1F)
    out = []
    for k in range(120):
        x, y = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
        d = rnd.randint(1, 1500)
        dx, dy = rnd.choice(((d, 0), (-d, 0), (0, d), (0, -d), (d, d), (-d, -d),
                             (rnd.randint(-d, d), rnd.randint(-d, d))))
        frac = (rnd.randrange(1 << 16), rnd.randrange(1 << 16)) if k % 3 == 0 else (0, 0)   # the player's
        out.append((x, y, (((x + dx) << 16) | frac[0]) & M32, (((y + dy) << 16) | frac[1]) & M32))
    return out


def _faim_run(tmp_path, name, mut=None) -> bool:
    w = _fworld()
    ft = PC.fight_things(w, list(range(w.layout.nmon)))
    code = "\n".join(PC.pj_lines(nt=0, root="R", fight=ft)) + "\n"
    a = code.index("pj_spawn_leaf:\n")
    b = code.index("    hex.mov 3, pw_idx, pw_ang + 5*dw\n") + len("    hex.mov 3, pw_idx, pw_ang + 5*dw\n")
    unit = code[a:b].replace("pj_spawn_leaf:", "angle_unit:")
    aim = "    hex.mov 8, ia_x2, mt_tqx\n    hex.mov 8, ia_y2, mt_tqy\n"
    assert unit.count(aim) == 1
    if mut == "aim_player":
        unit = unit.replace(aim, "    hex.mov 8, ia_x2, viewx\n    hex.mov 8, ia_y2, viewy\n")
    cases = _faim_cases(w)
    body = ["stl.startup_and_init_all"]
    for x, y, tx16, ty16 in cases:
        body += ["hex.set 4, mm_x, %d" % (x & 0xFFFF), "hex.set 4, mm_y, %d" % (y & 0xFFFF),
                 "hex.set 8, mt_tqx, %d" % tx16, "hex.set 8, mt_tqy, %d" % ty16,
                 "hex.set 8, viewx, %d" % ((tx16 + (5 << 16)) & M32), "hex.set 8, viewy, %d" % ty16,
                 "stl.fcall angle_unit, au_ret", "hex.print_as_digit 3, pw_idx, 0"]
    body += ["stl.output 10", "stl.loop"]
    data = (["viewx: hex.vec 8", "viewy: hex.vec 8", "mm_x: hex.vec 4", "mm_y: hex.vec 4", "au_ret: hex.vec w/4"]
            + PC.WINDOW_DECLS + [d for d in _MD.FIGHT_DECLS if d.split(":")[0].startswith(("ia_", "mt_tq"))]
            + [unit + "    stl.fret au_ret"] + _MD.angle_leaf_lines()
            + [generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
               generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
               generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)])
    want = ("".join("%03x" % (w.rm.point_to_angle(x << 16, y << 16, _s32(tx16), _s32(ty16)) >> 20)
                    for x, y, tx16, ty16 in cases) + "\n").encode()
    p = tmp_path / ("%s.fj" % name)
    p.write_text("\n".join(body + data) + "\n" + hoisted_scratch_fj(), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_fight_spawn_aims_at_the_target(tmp_path):
    assert _faim_run(tmp_path, "pjaim_fight"), "the fight's spawn angle parted from the model's"


def test_control_an_aim_at_the_player_is_caught(tmp_path):
    assert not _faim_run(tmp_path, "pjaim_fight_player", mut="aim_player"), "the comparison is vacuous"


def _frecords(w):
    """[dict]: the fireball (its shooter, nx16, ny16), the slots' pokes, the barrels', the player's, the lines'"""
    from doomfj.combat import BARREL_R, FIREBALL_R
    rnd = random.Random(0x7F1)
    n = w.layout.nmon
    imps = _imps(w)
    out = []
    for r in range(FIGHT_N):
        src = rnd.choice(imps)
        if rnd.random() < 0.25:                                   # beside a barrel
            bt = w.barrel_things[rnd.randrange(len(w.barrel_things))]
            cx, cy = bt.x, bt.y
            B = BARREL_R + FIREBALL_R
        else:
            cx, cy = rnd.randint(-600, 3000), rnd.randint(-1000, 2200)
            B = rnd.choice((20, 30)) + FIREBALL_R
        k = rnd.choice((B - 1, B, B + 1, rnd.randint(0, B + 2)))
        fx, fy = rnd.choice((0, 0, rnd.randrange(1 << 16))), rnd.choice((0, rnd.randrange(1 << 16)))
        nx16 = (((cx + rnd.choice((k, -k, rnd.randint(-k, k)))) << 16) | fx) & M32
        ny16 = (((cy + rnd.choice((k, -k, rnd.randint(-k, k)))) << 16) | fy) & M32
        mons = {}
        pool = [j for j in range(n) if w.ws.mon_active[j]]
        for j in rnd.sample(pool, rnd.choice((0, 1, 2, 3, 5))) + ([src] if rnd.random() < 0.3 else []):
            r_ = w.mon_radius[j] + FIREBALL_R
            kk = rnd.choice((r_ - 1, r_, r_ + 1, rnd.randint(0, r_ + 2)))
            x = (nx16 >> 16) + rnd.choice((kk, -kk, rnd.randint(-kk, kk)))
            y = (ny16 >> 16) + rnd.choice((kk, -kk, rnd.randint(-kk, kk)))
            st = rnd.choice(("alive", "alive", "alive", "dying", "fallen"))
            mons[j] = (x, y, int(st != "fallen"), int(st == "alive"))
        bars = [rnd.choice(("stand", "stand", "boom", "gone")) for _ in w.barrel_things]
        pl = (int(rnd.random() < 0.2), ((nx16 + rnd.randint(-30 << 16, 30 << 16)) & M32,
                                        (ny16 + rnd.randint(-30 << 16, 30 << 16)) & M32))
        out.append(dict(src=src, nx16=nx16, ny16=ny16, mons=mons, bars=bars, pdead=pl[0], p16=pl[1],
                        lines=int(rnd.random() < 0.8), rng=rnd.randrange(256)))
    return out


BAR_ST = {"stand": (lambda: gd.STATE_INDEX["S_BAR1"], 20, 1), "boom": (lambda: gd.STATE_INDEX["S_BEXP"], 0, 1),
          "gone": (lambda: 0, 0, 0)}


def _fapply(w, rec, log):
    ws, n = w.ws, w.layout.nmon
    for j in range(n):
        ws.mon_solid[j] = ws.mon_shootable[j] = ws.mon_health[j] = 0
        ws.mon_x[j], ws.mon_y[j] = -20000, -20000
    for j, (x, y, solid, alive) in rec["mons"].items():
        ws.mon_x[j], ws.mon_y[j], ws.mon_solid[j], ws.mon_shootable[j] = x, y, solid, alive
        ws.mon_health[j] = 30 if alive else -3
    for b, kind in enumerate(rec["bars"]):
        st, hp, solid = BAR_ST[kind]
        ws.bar_state[b], ws.bar_health[b], ws.bar_solid[b] = st(), hp, solid
    ws.p_dead, ws.p_health = rec["pdead"], 0 if rec["pdead"] else 100
    ws.px, ws.py = _s32(rec["p16"][0]), _s32(rec["p16"][1])
    ws.rng_fx = rec["rng"]
    s = 0
    ws.proj_src[s], ws.proj_active[s] = rec["src"], 1
    w.missile_lines_block = lambda x16, y16, _ok=rec["lines"]: not _ok
    w.damage_player = lambda dmg, source, inflictor, ev: log.append("P%02x%02x" % (dmg, source[1] + 1))
    w.damage_monster = lambda j, dmg, source, inflictor, ev: log.append(
        "M%02x%02x3%02x" % (1 + j, dmg, 2 + source[1]))
    w.damage_barrel = lambda b, dmg, source, ev: log.append("M%02x%02x3%02x" % (1 + n + b, dmg, 2 + source[1]))
    w._leaf16 = lambda x16, y16: 0
    w._list_remove = w._list_insert = lambda k, leaf: None
    ws.proj_leaf[s] = 0
    return w._missile_try(s, _s32(rec["nx16"]), _s32(rec["ny16"]), TicEvents(0))


def _fexpected(w, records) -> bytes:
    lines = []
    for r, rec in enumerate(records):
        log = []
        ok = _fapply(w, rec, log)
        lines += log + ["%x%02x%02x%03x" % ((int(ok), w.ws.rng_fx) + _window(r))]
    return ("\n".join(lines) + "\n").encode()


def _window(r):
    """record r's pool window: its runtime thing and leaf, poked before pj_try -- they must come back unchanged
    (the window's thing is the one pool_tic links and writes back: pj_out / _copy_out's thss_rt)"""
    return 0x44 + r % 10, (37 * r + 5) % 0x2C0


FIGHT_MUTANTS = {
    "species": ("    hex.if1 1, pt_imp, pt_tout\n", ""),
    "hits_shooter": ("    hex.cmp 2, pt_j, pt_me, pt_tst, pt_tout, pt_tst\n", ""),
    "corpse": ("    hex.if0 1, pt_sh, pt_tout\n", ""),
    "box_fraction": None,
    "pass_barrels": None,
    "pass_through": ("  pj_tm:\n", "  pj_tm:\n    ;pj_tl\n"),
    # the window not put back after dm_go: the fireball written back with the drop's thing and leaf
    "window_lost": ("    hex.mov w/4, pw_leaf, pt_svl\n", ""),
}


def _fbuild(tmp_path, name, mut=None):
    w = _fworld()
    n, nb = w.layout.nmon, len(w.barrel_things)
    records = _frecords(w)
    want = _fexpected(w, records)
    ft = PC.fight_things(w, list(range(n)))
    code = "\n".join(PC.pj_lines(nt=0, root="R", fight=ft)) + "\n"
    a = code.index("pj_try:\n")
    b = code.index("pj_explode:\n")
    unit = code[a:b]
    assert unit.count("    sim.check_cells R\n") == 1
    unit = unit.replace("    sim.check_cells R\n", "    hex.mov 1, cp_ok, cp_poke\n")
    if mut == "box_fraction":
        assert unit.count("    hex.if1 4, pw_nx, pt_fx\n") == 1       # B - 1 above whatever the fraction
        unit = unit.replace("    hex.if1 4, pw_nx, pt_fx\n", "")
    elif mut == "pass_barrels":
        i = unit.index("    hex.if0 1, bar_solid + 0*dw, pt_b0_n\n")
        unit = unit[:i] + "    ;pj_tl\n" + unit[i:]
    elif mut:
        old, new = FIGHT_MUTANTS[mut]
        assert unit.count(old) == 1, (mut, unit.count(old))
        unit = unit.replace(old, new)
    body = ["stl.startup_and_init_all"]
    for r, rec in enumerate(records):
        body += ["hex.zero %d, mon_solid" % n, "hex.zero %d, mon_shootable" % n]
        for j, (x, y, solid, alive) in sorted(rec["mons"].items()):
            body += ["hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 4, x & 0xFFFF),
                     "hex.set 4, thpos_rt + %d*dw, %d" % (16 * j + 12, y & 0xFFFF),
                     "hex.set 1, mon_solid + %d*dw, %d" % (j, solid), "hex.set 1, mon_shootable + %d*dw, %d" % (j, alive)]
        for bb, kind in enumerate(rec["bars"]):
            st, hp, solid = BAR_ST[kind]
            body += ["hex.set 2, bar_st + %d*dw, %d" % (2 * bb, st()), "hex.set 2, bar_hp + %d*dw, %d" % (2 * bb, hp),
                     "hex.set 1, bar_solid + %d*dw, %d" % (bb, solid)]
        body += ["hex.set 1, p_dead, %d" % rec["pdead"], "hex.set 3, p_hp, %d" % (0 if rec["pdead"] else 100),
                 "hex.set 8, viewx, %d" % rec["p16"][0], "hex.set 8, viewy, %d" % rec["p16"][1],
                 "hex.set 2, rng_fx, %d" % rec["rng"], "hex.set 2, pw_src, %d" % (rec["src"] + 1),
                 "hex.set 8, pw_nx, %d" % rec["nx16"], "hex.set 8, pw_ny, %d" % rec["ny16"],
                 "hex.set 1, cp_poke, %d" % rec["lines"],
                 "hex.set w/4, pw_t, %d" % _window(r)[0], "hex.set w/4, pw_leaf, %d" % _window(r)[1],
                 "stl.fcall pj_try, pj_tret",
                 "hex.print_as_digit 1, pw_ok, 0", "hex.print_as_digit 2, rng_fx, 0",
                 "hex.print_as_digit 2, pw_t, 0", "hex.print_as_digit 3, pw_leaf, 0", "stl.output 10"]
    body += ["stl.loop",
             "dp_go:", "    stl.output 80", "    hex.print_as_digit 2, dp_dmg, 0", "    hex.print_as_digit 2, dp_src, 0",
             "    stl.output 10", "    hex.zero 2, dp_src", "    stl.fret dp_ret",
             "dm_go:", "    stl.output 77", "    hex.print_as_digit 2, dm_id, 0", "    hex.print_as_digit 2, dm_dmg, 0",
             "    hex.print_as_digit 1, dm_melee, 0", "    hex.print_as_digit 2, dm_src, 0", "    stl.output 10",
             "    hex.zero 2, dm_src",
             # the real dm_go's kill of a dropper links the drop through the POOL WINDOW (damagecode: drop_link<k> ->
             # barrelcode.dr_link writes pw_t / pw_leaf); the stub does the same to them (blocked52 fight_gate F6
             # frame 44: imp 36's fireball killed shotgun guy 35 and was written back with the corpse's leaf)
             "    hex.not w/4, pw_t", "    hex.not w/4, pw_leaf",
             "    stl.fret dm_ret"]
    decls = (PC.pool_decls() + PC.pt_decls(ft)
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "p_hp: hex.vec 3", "p_dead: hex.vec 1",
                "dp_dmg: hex.vec 2", "dp_src: hex.vec 2", "dp_ret: hex.vec w/4",
                "dm_id: hex.vec 2", "dm_dmg: hex.vec 2", "dm_melee: hex.vec 1", "dm_src: hex.vec 2", "dm_ret: hex.vec w/4",
                "cp_ok: hex.vec 1", "cp_poke: hex.vec 1", "cpx: hex.vec 8", "cpy: hex.vec 8", "cprad: hex.vec 8",
                "mon_solid: hex.vec %d" % n, "mon_shootable: hex.vec %d" % n, "thpos_rt: hex.vec %d" % (16 * n),
                "bar_st: hex.vec %d" % (2 * nb), "bar_hp: hex.vec %d" % (2 * nb), "bar_solid: hex.vec %d" % nb])
    prog = "\n".join(body + decls + [unit] + [PC.tables_fj()[0]]) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], want


def _frun(tmp_path, name, mut=None) -> bool:
    srcs, want = _fbuild(tmp_path, name, mut)
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_fight_records_exercise_every_thing():
    """the model's own outcomes: monsters hit, the species exploding, solid corpses stopping it, the shooter passed,
    barrels hit and exploding ones stopping it, the player hit, the lines refusing, and clear passes"""
    w = _fworld()
    seen = {"mon": 0, "species": 0, "corpse": 0, "bar": 0, "player": 0, "pass": 0, "lines": 0, "shooter_near": 0}
    for rec in _frecords(w):
        log = []
        ev_hits = []
        orig = w._missile_things
        w._missile_things = lambda s, nx, ny, ev, _o=orig: (_o(s, nx, ny, ev), ev_hits.extend(ev.mon_hits))[0]
        ok = _fapply(w, rec, log)
        w._missile_things = orig
        kinds = [h[2] for h in ev_hits]
        for k in kinds:
            seen["corpse" if k == "corpse" else k] += 1
        seen["player"] += any(ln[0] == "P" for ln in log)
        seen["pass"] += bool(ok)
        seen["lines"] += (not ok) and not log and not kinds
        seen["shooter_near"] += rec["src"] in rec["mons"]
    want = {"mon": 40, "species": 10, "corpse": 10, "bar": 8, "player": 10, "pass": 100, "lines": 20,
            "shooter_near": 40}
    assert all(seen[k] >= v for k, v in want.items()), sorted((k, seen[k], v) for k, v in want.items())


def test_the_fight_things_follow_the_model(tmp_path):
    assert _frun(tmp_path, "pjthings"), "the fj fireball's things parted from the model's _missile_try"


@pytest.mark.parametrize("mut", sorted(FIGHT_MUTANTS))
def test_control_a_broken_thing_test_is_caught(tmp_path, mut):
    assert not _frun(tmp_path, "pjthings_" + mut, mut=mut), "%s passed: the comparison is vacuous" % mut
