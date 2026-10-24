"""M8 C4 -- the EPISODE'S MOVERS' fj RUN against the model (docs/episode-plan.md 2, C4), on the real lines and sectors
of the maps that have them (`assets/freedoom1.wad`), fed records and read back:

  1. the tic: every lift (`movercode.lift_tic_lines` -- E1M7's PERPETUAL lift 563 by `perpetual_lines`) and every
     floor group (`floor_tic_lines`: 36 turbo, 20 / 22 raise-and-change, 7 stairs among the old kinds), fired by
     `_fire_lines` on a schedule, against `movers.MoverPhase.tic` + `floor_trigger` -- E1M3, E1M4, E1M6, E1M7;
  2. the walk-overs after a move (36's four lines, 22, the perpetual lift's 53) against `MoverPhase.after_move`;
  3. the use presses (20, 7 S1; the SR lifts) against `MoverPhase.use_press`, and the LIGHT SWITCH (138,
     `lightcode.switch_use_lines`) against the model's box;
  4. the nukage a texture-change floor stops (`lootcode.nukage_clear_lines` + `nkgrp`) against
     `World.floor_special_cleared`, every leaf and every group state;
  5. the collision cells: a door line beside a lift (E1M3's 519: the door's gate, on its open arm the lift's low floor)
     and a line read through a PAIR of cells (`collision_cells_fj`'s two-level dispatch, forced on E1M2's line 1199 --
     whose model `World.try_move_lines` is the truth -- with its full (lift x floor) grid), against the model.

R9: MUTANTS -- one real edit of the emitted text each -- must each make their program disagree.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import gamedata as gd
from doomfj import movers as MV
from doomfj.collision import point_location_decls
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.harness import W
from doomfj.movercode import (_fire_lines, floor_tic_lines, floor_walk_lines, lift_tic_lines, lift_walk_lines,
                              mover_decls, use_line_lines)
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
FIX2 = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
PLAYER_R = 16
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")
MAPS = ("E1M3", "E1M4", "E1M6", "E1M7")


@pytest.fixture(scope="module")
def wad():
    return WadFile.from_path(ART)


_MP = {}


def _mp(wad, m):
    if m not in _MP:
        _MP[m] = MV.MoverPhase(wad.sectors(m), wad.linedefs(m), wad.sidedefs(m), wad.vertexes(m))
    return _MP[m]


def _world(wad, m):
    """the map's World, the thing types gamedata lacks left out (the survey's construction)"""
    from doomfj.world import World
    unknown = {t.type for t in wad.things(m)} - set(gd.THING_TYPES) - set(gd.NOT_THINGS)
    saved = gd.NOT_THINGS
    gd.NOT_THINGS = frozenset(saved | unknown)
    try:
        return World(wad, m, skill=gd.SK_HARD, monsters="chase", sight_rule="seen", strict=True)
    finally:
        gd.NOT_THINGS = saved


def _run(tmp, name, program, feed, sim=False):
    src = tmp / (name + ".fj")
    src.write_text(program, encoding="utf-8")
    out = tmp / (name + ".fjm")
    extra = []
    if sim:                                             # hex.switch and its constants
        from doomfj.config import Config
        extra = [Config().emit_fj_consts(tmp / "fj_consts.fj").resolve()]
    fj.assemble([*extra, *([(FJ / "sim.fj").resolve()] if sim else []),
                 src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _pr(reg, n):
    return [f"    hex.print_as_digit {n}, {reg}, 0", "    stl.output 32"]


def _decls(mp):
    return ["rmagic: hex.vec 2", "rbyte: hex.vec 2", "cm_ox: hex.vec 8", "cm_oy: hex.vec 8", "viewx: hex.vec 8",
            "viewy: hex.vec 8", "dbox: hex.vec 8, 0", *point_location_decls(),
            *mover_decls(len(mp.order), MV.fswitch_nibbles(mp.groups))]


def _nfs(mp):
    return MV.fswitch_nibbles(mp.groups)


def _in_fswitch(mp):
    out = []
    for i in range(_nfs(mp)):
        out += ["hex.input 1, rbyte", f"hex.mov 1, fswitch + {i}*dw, rbyte"]
    return out


def _out_fswitch(mp):
    return [ln for i in range(_nfs(mp)) for ln in _pr(f"fswitch + {i}*dw", 1)]


def test_the_maps_have_every_new_kind(wad):
    kinds = {m: {g.special for g in _mp(wad, m).groups} for m in MAPS}
    assert {20, 7} <= kinds["E1M3"] and 36 in kinds["E1M4"] and 20 in kinds["E1M6"] and 36 in kinds["E1M7"]
    assert sum(_mp(wad, "E1M7").perpetual.values()) == 1
    assert any(g.change for g in _mp(wad, "E1M6").groups)


# ---- 1. the tic --------------------------------------------------------------------------------------------------
def tic_text(mp):
    return (lift_tic_lines(mp.order, {si: len(v) for si, v in mp.stops.items()}, mp.stride,
                           {si: True for si in mp.order if mp.perpetual[si]})
            + floor_tic_lines(mp.groups))


def tic_program(mp, text=None):
    nl, ng = len(mp.order), len(mp.groups)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done"]
    for k in range(nl):
        body += ["hex.input 1, rbyte", f"hex.mov 1, lreq + {k}*dw, rbyte"]
    body += list(tic_text(mp) if text is None else text)
    for g in range(ng):                                  # the player's fires, after the tic (the frame's order)
        body += ["hex.input 1, rbyte", "hex.if0 1, rbyte, tf%d_skip" % g]
        body += [ln.replace(";tf%d_fired" % g, ";tf%d_skip" % g) for ln in _fire_lines("tf%d" % g, g, mp.groups)]
        body += ["tf%d_skip:" % g]
    for k in range(nl):
        body += _pr(f"lstate + {k}*dw", 1) + _pr(f"ldir + {k}*dw", 1) + _pr(f"lsub + {k}*dw", 1)
        body += _pr(f"lwait + {WAIT_NIBBLES * k}*dw", WAIT_NIBBLES) + _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def tic_schedule(mp, seed=5, frames=220):
    rng = random.Random(seed)
    out = []
    for f in range(frames):
        lifts = [int(f in (0, 3, 30, 31, 70, 150) or rng.random() < 0.05) for _ in mp.order]
        fires = [int(f == 2 * g or rng.random() < 0.03) for g in range(len(mp.groups))]
        out.append((lifts, fires))
    return out


def tic_expect(mp, sched):
    st, want = mp.initial(), []
    for lifts, fires in sched:
        req = frozenset(si for si, t in zip(mp.order, lifts) if t)
        st = mp.tic((st[0], req, st[2]))
        fs = mp._fs(st[2])
        for g, on in enumerate(fires):
            if on:
                fs[g] = MV.floor_trigger(*fs[g], mp.groups[g].sub)
        st = (st[0], st[1], mp._sw(fs))
        for s in st[0]:
            want += list(s) + [0]
        want += list(st[2])
    return want


def tic_feed(sched):
    return b"".join(bytes([1] + lifts + fires) for lifts, fires in sched)


@pytest.mark.parametrize("m", MAPS)
def test_the_tic_is_movers(tmp_path, wad, m):
    mp = _mp(wad, m)
    sched = tic_schedule(mp)
    want = tic_expect(mp, sched)
    assert _run(tmp_path, "tic", tic_program(mp), tic_feed(sched)) == want
    ng = len(mp.groups)
    assert want[-2 * ng:-ng] == [g.n - 1 for g in mp.groups], "every floor group reached its destination"


# ---- 2. the walk-overs after a move -----------------------------------------------------------------------------
def walk_text(mp):
    return lift_walk_lines(mp.walk, mp.order, PLAYER_R) + floor_walk_lines(mp.groups, mp.floor_walk, PLAYER_R)


def walk_program(mp, text=None):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            *_in_fswitch(mp), f"hex.zero {len(mp.order)}, lreq", *(walk_text(mp) if text is None else text)]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def _axis_moves(shape):
    axis, coord, lo, hi = shape
    L, out = coord << 16, []
    for o in (lo - PLAYER_R, lo - PLAYER_R + 1, (lo + hi) // 2, hi + PLAYER_R - 1, hi + PLAYER_R):
        for a_old, a_new in ((L, L - 1), (L + 1, L), (L - (8 << 16), L + (8 << 16)),
                             (L + (8 << 16), L - (8 << 16)), (L + (8 << 16), L + (2 << 16))):
            of = o << 16
            out.append(((of, a_old), (of, a_new)) if axis == "y" else ((a_old, of), (a_new, of)))
    return out


def _fired(mp, done=False):
    fs = [(1, 0) if not g.sub else ((g.n - 1, 0) if done else (1, g.sub)) for g in mp.groups]
    return mp._sw(fs)


def walk_recs(mp):
    """crossings, misses and the line itself, for the new kinds' lines (36, 22; the perpetual lift's 53) and -- for
    their company -- the map's other walk lines, from untouched, fired and arrived groups"""
    rng = random.Random(11)
    recs = []
    shapes = [(t[1], t[2], t[3], t[4]) for t in mp.walk] + [s for _g, s in mp.floor_walk if s[0] != "d"]
    for shape in shapes:
        for old, new in _axis_moves(shape):
            recs.append((old, new, mp.initial()[2]))
    for old, new, _sw in recs[::5]:
        recs.append((old, new, _fired(mp)))
    for old, new, _sw in recs[2::7]:
        recs.append((old, new, _fired(mp, done=True)))
    rng.shuffle(recs)
    return recs


def walk_expect(mp, recs):
    want = []
    for old, new, sw in recs:
        lifts, _req, _ = mp.initial()
        st = mp.after_move((lifts, frozenset(), sw), old, new, PLAYER_R)
        want += [int(si in st[1]) for si in mp.order] + list(st[2])
    return want


def walk_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<IIII", o[0] & M32, o[1] & M32, n[0] & M32, n[1] & M32)
                    + bytes(sw) for o, n, sw in recs)


@pytest.mark.parametrize("m", ("E1M4", "E1M6", "E1M7"))
def test_the_walk_overs_are_movers_after_move(tmp_path, wad, m):
    mp = _mp(wad, m)
    recs = walk_recs(mp)
    want = walk_expect(mp, recs)
    assert _run(tmp_path, "walk", walk_program(mp), walk_feed(recs)) == want
    new = [g for g, grp in enumerate(mp.groups) if grp.special in (36, 22)]
    n = len(mp.order) + _nfs(mp)
    for g in new:                                  # each new line fires its group somewhere in the records
        assert any(want[i * n + len(mp.order) + len(mp.groups) + g] or want[i * n + len(mp.order) + g]
                   for i in range(len(recs)) if recs[i][2] == mp.initial()[2]), g
    if m == "E1M7":
        k = mp.order.index(563)
        assert any(want[i * n + k] for i in range(len(recs))), "the perpetual lift's W1 line requests it"


# ---- 3. the use presses: the S1 floors, the SR lifts, the light switch ------------------------------------------
def use_text(mp):
    return use_line_lines(mp.use, [], MV.lift_slots_of_tag(mp.secs, mp.order), mp.groups, mp.floor_use)


def use_program(mp, text=None):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, viewx", "hex.input 4, viewy", *_in_fswitch(mp),
            f"hex.zero {len(mp.order)}, lreq", *(use_text(mp) if text is None else text)]
    for k in range(len(mp.order)):
        body += _pr(f"lreq + {k}*dw", 1)
    body += _out_fswitch(mp)
    body += [";loop", "done:", "stl.loop", *_decls(mp)]
    return "\n".join(body) + "\n"


def _box_points(boxes):
    pts = []
    for x0, y0, x1, y1 in boxes:
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        for x, y in ((cx, cy), (x0, cy), (x1, cy), (cx, y0), (cx, y1)):
            for dx, dy in ((0, 0), (-1, 0), (1, 0), (0, -1), (0, 1)):
                pts.append(((x << 16) + dx, (y << 16) + dy))
    return pts


def use_recs(mp):
    pts = _box_points([b for _t, b in mp.use] + [b for _g, b in mp.floor_use])
    return [(x, y, sw) for x, y in pts for sw in (mp.initial()[2], _fired(mp), _fired(mp, done=True))]


def use_expect(mp, recs):
    want = []
    for x, y, sw in recs:
        lifts, _req, _ = mp.initial()
        st = mp.use_press((lifts, frozenset(), sw), x, y)
        want += [int(si in st[1]) for si in mp.order] + list(st[2])
    return want


def use_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) + bytes(sw) for x, y, sw in recs)


@pytest.mark.parametrize("m", ("E1M3", "E1M6"))
def test_the_use_presses_are_movers_use_press(tmp_path, wad, m):
    mp = _mp(wad, m)
    recs = use_recs(mp)
    want = use_expect(mp, recs)
    assert _run(tmp_path, "use", use_program(mp), use_feed(recs)) == want
    n = len(mp.order) + _nfs(mp)
    fired = {g for i in range(len(recs)) for g in range(len(mp.groups))
             if want[i * n + len(mp.order) + g] != recs[i][2][g] or
             want[i * n + len(mp.order) + len(mp.groups) + g] != recs[i][2][len(mp.groups) + g]}
    assert fired == {g for g, _b in mp.floor_use}, "each S1 group fires by its own lines"
    assert {mp.groups[g].special for g in fired} >= ({20, 7} if m == "E1M3" else {20})


def _light_uses(wad):
    from doomfj import lights as L
    secs, lds, sds = wad.sectors("E1M3"), wad.linedefs("E1M3"), wad.sidedefs("E1M3")
    ths = L.game_thinkers(secs, lds, sds, False)
    return ths, L.light_switch_uses(secs, lds, wad.vertexes("E1M3"), ths)


def light_program(n, text):
    return "\n".join(["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
                      "hex.input 4, viewx", "hex.input 4, viewy", f"hex.zero {n}, ltst", *text,
                      *[ln for k in range(n) for ln in _pr(f"ltst + {k}*dw", 1)],
                      ";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8",
                      "dbox: hex.vec 8, 0", f"ltst: hex.vec {n}, 0"]) + "\n"


def test_the_light_switch_is_the_models_box(tmp_path, wad):
    from doomfj.doors import in_use_box_fixed
    from doomfj.lightcode import switch_use_lines
    ths, uses = _light_uses(wad)
    assert len(uses) == 1 and len(ths) == 1
    pts = _box_points([b for b, _k in uses])
    want = []
    for x, y in pts:
        st = [0] * len(ths)
        for box, ks in uses:
            if in_use_box_fixed(box, x, y):
                for k in ks:
                    st[k] = 1
        want += st
    feed = b"".join(bytes([1]) + struct.pack("<II", x & M32, y & M32) for x, y in pts)
    assert _run(tmp_path, "light", light_program(len(ths), switch_use_lines(uses)), feed) == want
    assert 0 < sum(want) < len(want)
    bad = [ln.replace("ltst + 0*dw, 1", "ltst + 0*dw, 0") for ln in switch_use_lines(uses)]      # R9
    assert _run(tmp_path, "light_bad", light_program(len(ths), bad), feed) != want


# ---- 4. the nukage a texture-change floor stops -------------------------------------------------------------------
@pytest.fixture(scope="module")
def w3(wad):
    return _world(wad, "E1M3")


def nk_program(w, clear):
    from doomfj import lootcode
    nfs = MV.fswitch_nibbles(w.floor_groups)
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 2, ptss"]
    for i in range(nfs):
        body += ["hex.input 1, rbyte", f"hex.mov 1, fswitch + {i}*dw, rbyte"]
    body += [*clear, "    hex.set 1, nkres, 1", "    ;nk_pr", "  nk_out:", "    hex.zero 1, nkres", "  nk_pr:",
             *_pr("nkres", 1), ";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
             "ptss: hex.vec 4", "nk_g: hex.vec 1", "nkres: hex.vec 1", f"fswitch: hex.vec {nfs}, 0"]
    import doomfj.lut_generator as LG
    body += [LG.generate_dispatch_table_fj("nkgrp", lootcode.nkgrp_values(w), index_nibbles=3, result_nibbles=1)]
    return "\n".join(body) + "\n"


def nk_recs(w):
    rng = random.Random(3)
    from doomfj import lootcode
    ng = lootcode.nkgrp_values(w)
    hot = [s for s, v in enumerate(ng) if v]
    leaves = hot * 12 + [rng.randrange(len(ng)) for _ in range(40)] + [w.leaf_sector.index(2)] * 4
    recs = []
    for leaf in leaves:
        sw = [0] * MV.fswitch_nibbles(w.floor_groups)
        chg = sorted({gg for _h, _f, gg in w.floor_change.values()})
        g = rng.choice(chg * 3 + list(range(len(w.floor_groups))))     # the change group's cells, most often
        r = rng.random()
        if r < 0.3:
            sw[g] = rng.randint(1, w.floor_groups[g].n - 1)
        elif r < 0.6:
            sw[len(w.floor_groups) + g] = rng.randint(1, 8)
        recs.append((leaf, sw))
    return recs


def nk_expect(w, recs):
    from doomfj import lootcode
    ng = lootcode.nkgrp_values(w)
    want = []
    for leaf, sw in recs:
        n = len(w.floor_groups)
        for g in range(n):
            w._set_floor(g, sw[g], sw[n + g])
        sec = w.leaf_sector[leaf]
        want.append(0 if (ng[leaf] and w.floor_special_cleared(sec)) else 1)
    for g in range(len(w.floor_groups)):
        w._set_floor(g, 0, 0)
    return want


def nk_feed(recs):
    return b"".join(bytes([1]) + struct.pack("<H", leaf) + bytes(sw) for leaf, sw in recs)


def test_the_nukage_clear_is_the_models(tmp_path, w3):
    from doomfj import lootcode
    recs = nk_recs(w3)
    want = nk_expect(w3, recs)
    got = _run(tmp_path, "nk", nk_program(w3, lootcode.nukage_clear_lines(w3)), nk_feed(recs), sim=True)
    assert got == want
    assert 0 < want.count(0) < len(want), "cleared and kept"
    g = next(gg for _h, _f, gg in w3.floor_change.values())
    n = len(w3.floor_groups)
    hot = [r for r in recs if lootcode.nkgrp_values(w3)[r[0]]]
    assert any(sw[g] and not sw[n + g] for _l, sw in hot) and any(sw[n + g] and not sw[g] for _l, sw in hot), (
        "fired by its state alone and by its timer alone")


@pytest.mark.parametrize("mut", ["no_timer_test", "no_state_test"])
def test_control_a_broken_nukage_clear_parts(tmp_path, w3, mut):
    from doomfj import lootcode
    recs = nk_recs(w3)
    want = nk_expect(w3, recs)
    lines = lootcode.nukage_clear_lines(w3)
    k = 1 if mut == "no_timer_test" else 0
    hits = [i for i, ln in enumerate(lines) if ln.strip().startswith("hex.if1 1, fswitch")]
    lines = [ln for i, ln in enumerate(lines) if i != hits[k]]
    assert _run(tmp_path, "nk_" + mut, nk_program(w3, lines), nk_feed(recs), sim=True) != want


# ---- R9: the movers' mutants ---------------------------------------------------------------------------------------
def _perp_slot(mp):
    return mp.order.index(next(si for si in mp.order if mp.perpetual[si]))


MUTANTS = {
    # a request to a perpetual lift that is WAITING restarts it (the never-started test dropped)
    "perpetual: a waiting lift is restarted": ("E1M7", "tic", lambda mp: [
        ln for ln in "\n".join(tic_text(mp)).replace(
            "    hex.if0 2, lwait + %d*dw, lf%d_start\n    ;lf%d_nr" % (2 * _perp_slot(mp), _perp_slot(mp),
                                                                       _perp_slot(mp)),
            "    ;lf%d_start" % _perp_slot(mp)).split("\n")]),
    # from the bottom the perpetual lift goes DOWN again (its CLOSING set as OPENING)
    "perpetual: never comes back up": ("E1M7", "tic", lambda mp: [
        ln.replace("hex.set 1, ldir + %d*dw, 2" % _perp_slot(mp), "hex.set 1, ldir + %d*dw, 1" % _perp_slot(mp))
        for ln in tic_text(mp)]),
    # a step that does not reload the perpetual lift's step timer
    "perpetual: its timer not reloaded": ("E1M7", "tic", lambda mp: [
        "" if ln.strip() == "hex.set 1, lsub + %d*dw, %d" % (_perp_slot(mp), MV.PERP_SUB) else ln
        for ln in tic_text(mp)]),
    # the stairs' step timer reloaded with the floors' 4 (the 16-unit grid's speed)
    "stairs: the wrong speed": ("E1M3", "tic", lambda mp: [
        ln.replace(", %d" % MV.STAIR_SUB, ", %d" % MV.FLOOR_SUB)
        if ln.strip().startswith("hex.set 1, fswitch + %d*dw" % (len(mp.groups) + next(
            g for g, grp in enumerate(mp.groups) if grp.special == 7))) else ln for ln in tic_text(mp)]),
    # 36's walk lines fire their group again after it arrived (the W1 latch's state test dropped)
    "36: fires twice": ("E1M4", "walk", lambda mp: [
        "    ;" + ln.strip().rsplit(", ", 1)[1]
        if ln.strip().startswith("hex.if0 1, %s," % MV.switch_cell(next(
            g for g, grp in enumerate(mp.groups) if grp.special == 36))) else ln for ln in walk_text(mp)]),
}


@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_mutated_mover_block_fails(tmp_path, wad, name):
    m, which, fn = MUTANTS[name]
    mp = _mp(wad, m)
    if which == "tic":
        good, sched = tic_text(mp), tic_schedule(mp)
        bad = fn(mp)
        prog, feed, want = tic_program(mp, bad), tic_feed(sched), tic_expect(mp, sched)
    else:
        good, recs = walk_text(mp), walk_recs(mp)
        bad = fn(mp)
        prog, feed, want = walk_program(mp, bad), walk_feed(recs), walk_expect(mp, recs)
    assert bad != good, "the mutant changed nothing"
    assert _run(tmp_path, "mut", prog, feed) != want, "%s passed: the comparison is vacuous" % name


# ---- 5. the collision cells: a door line beside a lift, a line on a PAIR of cells ---------------------------------
class Line:
    """one line in the MONSTERS' cells (`monster_cells_fj`'s construction, the lists kept round the line) against the
    model's `World.try_move_lines`, every state of the cells the line reads"""

    def __init__(self, w, li, cells, pfx):
        from doomfj.monstermove import world_cell_inputs
        self.w, self.li, self.cells, self.pfx = w, li, cells, pfx
        ld = w.lds[li]
        (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        self.mid, self.ends = ((x1 + x2) // 2, (y1 + y2) // 2), ((x1, y1), (x2, y2))
        self.kw = world_cell_inputs(w, 16)
        self.m = next(m for m in range(w.layout.nmon) if w.mon_radius[m] == 20 and w.mon_height[m] == 56)

    def movers(self):
        from doomfj.collision import mover_line_states
        w, kw = self.w, self.kw
        obs = mover_line_states(w.lds, w.sds, kw["msecs"], kw["mcell"], max)
        lfs = mover_line_states(w.lds, w.sds, kw["msecs"], kw["mcell"], min)
        return {li: (obs[li][0], obs[li][1], lfs[li][1]) + ((lfs[li][0],) if lfs[li][0] != obs[li][0] else ())
                for li in obs if obs[li][0] != "pair"}

    def cells_text(self, movers):
        from doomfj.collision import MONSTER_CELL_RADIUS, cell_lists, collision_cells_fj, line_lowfloors, line_rows
        from doomfj.reference_model import ML_BLOCKING
        w, kw = self.w, self.kw
        rows = line_rows(w.lds, w.cmap.vertexes, w.secs, w.sds, ML_BLOCKING | gd.ML_BLOCKMONSTERS,
                         secs_open=kw["secs_open"], door_line_ids=kw["door_line_ids"])
        mx, my = self.mid
        lists = {c: v for c, v in cell_lists(rows, MONSTER_CELL_RADIUS).items()
                 if abs(c[0] * 32 + 16 - mx) < 200 and abs(c[1] * 32 + 16 - my) < 200}
        assert any(self.li in v for v in lists.values())
        return collision_cells_fj(self.pfx, rows, lists, doors=kw["doors"], movers=movers, tag="mc",
                                  lowfloor=line_lowfloors(w.lds, w.sds, w.secs))

    def samples(self, n=300):
        rng = random.Random(self.li)
        dims = [k for _c, _set, k in self.cells]
        (x1, y1), (x2, y2) = self.ends
        out = []
        for k in range(n):
            st, r = [], k
            for d in dims:
                st.append(r % d)
                r //= d
            if rng.random() < 0.6:                    # the box ON the line
                t = rng.random()
                nx = int(x1 + t * (x2 - x1)) + rng.randint(-19, 19)
                ny = int(y1 + t * (y2 - y1)) + rng.randint(-19, 19)
            else:
                nx, ny = self.mid[0] + rng.randint(-90, 90), self.mid[1] + rng.randint(-90, 90)
            z = rng.choice(self.zs + [rng.randint(-150, 300)])
            out.append((nx, ny, z, tuple(st)))
        return out

    def model(self, s):
        w = self.w
        nx, ny, z, st = s
        for (_c, setter, _n), v in zip(self.cells, st):
            setter(w, v)
        w._mh_last = None
        w._door_phase_scene()
        w.ws.mon_floorz[self.m] = z
        from doomfj.world import OK
        leaf = w.rm.point_in_subsector(w.cmap, nx, ny)
        seed = w.secs_c[w.leaf_sector[leaf]]
        v, fz = w.try_move_lines(self.m, nx, ny)
        return (seed.floor_h, seed.ceil_h), (v == OK, fz if v == OK else None)

    def run(self, tmp, name, movers):
        from doomfj.collision import COLLISION_STATE_DECLS, MON_CELL_DECLS
        from doomfj.config import Config
        from doomfj.world import DROPOFF_MAX, STEP_UP
        w = self.w
        text, root = self.cells_text(movers)
        nd, nl, nfs = len(w.door_order), len(w.lift_order), MV.fswitch_nibbles(w.floor_groups)
        prog = "\n".join([
            "stl.startup_and_init_all",
            "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
            *["hex.input 4, %s" % r for r in ("cpx", "cpy", "cprad", "cp_seedf", "cp_seedc", "herf")],
            *[ln for c, _s, _n in self.cells for ln in ("hex.input 1, rbyte", "hex.mov 1, %s, rbyte" % c)],
            "sim.try_move_mon %s, 56, %d, herf, %d" % (root, STEP_UP, DROPOFF_MAX),
            "hex.print_as_digit 1, mv_ok, 0", "hex.print_as_digit 8, cp_floor, 0", "stl.output 10",
            ";loop", "done:", "stl.loop", text,
            "wmagic: hex.vec 2", "rbyte: hex.vec 2", "herf: hex.vec 8",
            "dstate: hex.vec %d, %d" % (nd, sum((w.door_nstates[si] - 1) << (4 * d)
                                                for d, si in enumerate(w.door_order))),
            "lstate: hex.vec %d" % nl, "fswitch: hex.vec %d" % nfs, *COLLISION_STATE_DECLS, *MON_CELL_DECLS]) + "\n"
        src = tmp / ("%s.fj" % name)
        src.write_text(prog, encoding="utf-8")
        out = tmp / ("%s.fjm" % name)
        consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
        fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                    out, memory_width=W, print_time=False)
        for d, si in enumerate(w.door_order):          # every door fully open in the model too (the fj's dstate)
            w.ws.d_state[d] = w.door_nstates[si] - 1
        feed, want = b"", []
        for s in self.samples():
            (sf, sc), res = self.model(s)
            nx, ny, z, st = s
            feed += bytes([0xD0]) + struct.pack("<IIIIII", (nx << 16) & M32, (ny << 16) & M32, (20 << 16) & M32,
                                                sf & M32, sc & M32, z & M32) + bytes(st)
            want.append(res)
        io = FixedIO(feed + bytes([0]))
        fj.run(out, io_device=io, print_time=False, print_termination=False)
        lines = io.get_output(allow_incomplete_output=True).decode().split("\n")
        got = []
        for k in range(len(want)):
            ok = lines[k][0] == "1"
            f = int(lines[k][1:9], 16)
            got.append((ok, (f - (1 << 32) if f >> 31 else f) if ok else None))
        for d, si in enumerate(w.door_order):
            w.ws.d_state[d] = 0
        return got, want


@pytest.fixture(scope="module")
def door_lift(w3):
    """E1M3's 519: DR door 106 (its gate) in front of lift 105 (the low floor per lift state on the open arm)"""
    w = w3
    d, k = w.door_order.index(106), w.lift_order.index(105)

    def set_d(w_, v):
        w_.ws.d_state[d] = v

    def set_l(w_, v):
        w_.ws.l_state[k] = v
    ln = Line(w, 519, [("dstate + %d*dw" % d, set_d, w.door_nstates[106]),
                       ("lstate + %d*dw" % k, set_l, len(w.lift_stops[105]))], "e1m3")
    ln.zs = list(w.lift_stops[105]) * 2 + [104, 104, 177]
    return ln


def test_the_door_beside_a_lift_is_the_model(tmp_path, door_lift):
    mv = door_lift.movers()
    assert 519 in mv and 519 in door_lift.kw["doors"], "a door line AND a mover line"
    got, want = door_lift.run(tmp_path, "doorlift", mv)
    bad = [(k, g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])
    assert 0.05 < sum(r[0] for r in want) / len(want) < 0.95, "refusals and accepts"   # E1M3 519: 30 of 300


def test_control_the_door_beside_a_lift_on_its_stored_floor(tmp_path, door_lift):
    """R9: the line read as a plain door line -- the low floor baked at the lift's top: the drop-off is lost"""
    mv = {li: v for li, v in door_lift.movers().items() if li != 519}
    got, want = door_lift.run(tmp_path, "doorlift_bad", mv)
    assert got != want


@pytest.fixture(scope="module")
def pair_line():
    """E1M2's 1199 (blazing lift 47 / S1 floor 206) through the PAIR dispatch: its full (lift, floor) grid -- the
    opening floor max, the low floor min of the two floors -- whose truth is the model's try_move_lines"""
    from doomfj.world import World
    w = World(WadFile.from_path(FIX2), "E1M2", skill=gd.SK_HARD, monsters="chase", sight_rule="seen")
    k = w.lift_order.index(47)
    g = next(g for g, grp in enumerate(w.floor_groups) if 206 in grp.sectors)

    def set_l(w_, v):
        w_.ws.l_state[k] = v

    def set_f(w_, v):
        w_.ws.f_switch[g] = v
    ln = Line(w, 1199, [("lstate + %d*dw" % k, set_l, len(w.lift_stops[47])),
                        (MV.switch_cell(g), set_f, w.floor_groups[g].n)], "e1m2")
    ln.zs = list(w.lift_stops[47]) + [w.floor_groups[g].floor(206, j) for j in range(w.floor_groups[g].n)]
    return ln


def _grid(ln, fn):
    w, kw = ln.w, ln.kw
    ld = w.lds[ln.li]
    f, b = w.sds[ld.front].sector, w.sds[ld.back].sector
    sa, sb = kw["msecs"][47], kw["msecs"][206]
    return [[fn(sa[i][f].floor_h if f == 47 else sb[j][f].floor_h, sa[i][b].floor_h if b == 47 else sb[j][b].floor_h)
             for j in range(len(sb))] for i in range(len(sa))]


def test_the_pair_dispatch_is_the_model(tmp_path, pair_line):
    mv = pair_line.movers()
    ca, cb = pair_line.cells[0][0], pair_line.cells[1][0]
    mv[1199] = ("pair", ca, cb, _grid(pair_line, max), _grid(pair_line, min))
    got, want = pair_line.run(tmp_path, "pair", mv)
    bad = [(k, g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(got), bad[:3])


@pytest.mark.parametrize("mut", ["cells_swapped", "lf_grid_flat"])
def test_control_a_broken_pair_dispatch_parts(tmp_path, pair_line, mut):
    mv = pair_line.movers()
    ca, cb = pair_line.cells[0][0], pair_line.cells[1][0]
    ob, lf = _grid(pair_line, max), _grid(pair_line, min)
    if mut == "cells_swapped":
        mv[1199] = ("pair", cb, ca, ob, lf)
    else:
        # the low floor varies with the LIFT (rows) and not with the floor switch (E1M2 1199: min of the two floors is
        # always the lift's side) -- flattening the columns was an equivalent mutant; flatten the rows
        assert any(lf[i] != lf[0] for i in range(len(lf))), "the control must change the grid"
        mv[1199] = ("pair", ca, cb, ob, [list(lf[0]) for _ in range(len(lf))])
    got, want = pair_line.run(tmp_path, "pair_" + mut, mv)
    assert got != want


# ---- 6. the renderer's dynamic-seg gate (wall_renderer.dual_gate_lines: hex.if0 on state 0, hex.if_flags on a mask) --
def _gate_program(gates):
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, rbyte", "hex.mov 1, gcell, rbyte"]
    for k, lines in enumerate(gates):
        body += [*lines, "    hex.set 1, gres, 0", f"    ;g{k}_end", f"  g{k}_solid:", "    hex.set 1, gres, 1",
                 f"  g{k}_end:", *_pr("gres", 1)]
    return "\n".join(body + [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2",
                             "gcell: hex.vec 1", "gres: hex.vec 1"]) + "\n"


def test_the_seg_gate_is_its_mask(tmp_path):
    from doomfj.wall_renderer import dual_gate_lines, seg_shut_gate
    pats = [[True] + [False] * 9, [True] * 5 + [False] * 5, [False, True, True, False], [True, False, True, True]]
    gates, masks = [], []
    for k, st in enumerate(pats):
        m, mask = seg_shut_gate(st, [len(st)])
        assert m == 0
        dc = "gcell" if mask == 1 else ("gcell", mask)
        gates.append(dual_gate_lines(dc, f"g{k}_open", f"g{k}_solid"))
        masks.append(mask)
    assert gates[0] == ["    hex.if0 1, gcell, g0_solid"]                 # E1M1's one-op gate, unchanged
    want = [int(bool(mk >> s & 1)) for s in range(16) for mk in masks]
    feed = b"".join(bytes([1, s]) for s in range(16))
    assert _run(tmp_path, "gate", _gate_program(gates), feed) == want
    bad = [dual_gate_lines(("gcell", mk ^ 0xFFFF) if mk != 1 else "gcell", f"g{k}_open", f"g{k}_solid")
           for k, mk in enumerate(masks)]                                    # R9: the complement mask
    assert _run(tmp_path, "gate_bad", _gate_program(bad), feed) != want
