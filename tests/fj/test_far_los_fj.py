"""M7 P8a I (docs/gp-final-plan.md 1.2.3, O-B2 TAKEN): the FAR line of sight on the real engine -- `sl_far`
(`monstersight.far_los_lines`: the pieces, their runs, the near cell tree walked as a subroutine, `sl_seg` on the
WHOLE trace) against the model's `World.los_points`, monster to monster (both whole units) across E1M1 at every range
up to the map's width, with every door, both lifts and the floor switch in random states. The same image runs the
NEAR LOS and the BLAST's LOS in their "fight" forms -- `near_los_lines(fight=True)` (the tree on the cell registers
sl_jx / sl_jy; the segment blocks calling the fight's sl_seg on a biased box) and `blast_los_lines(fight=True)` -- on
near monster -> player traces and barrel -> target traces, which must stay the model's too.

THE COST: the run is repeated with `sl_far` stubbed (an immediate return) -- the difference over the far records is
the far LOS's ops a check, printed and bounded by O-B2's fallback trigger (~0.2M a check).

R9 (each must part from the model): the lists without their NEAR margin; a run box that assumes x grows (a run
moving west boxed empty); the walk stopped after the first run; the step's halving made logical (its sign lost); a
far trace that never walks a list; the fight's box reject unbiased (a signed box compared unsigned); the segment
constants not undone after the test.

M8 F1.1 (docs/f1-big-map-widths.md 4): the same on E1M2, 4,952 units wide -- its sample plus 120 traces of more than
32 pieces (up to 64, past the 32 `FAR_PIECES` was before; E1M1's need <= 32, MEASURED), with the walk's mutants run
on that sample too. (A walk capped at 32 pieces is NOT a usable control: its longer pieces' runs still cover the cells
they cross, and its verdicts did not change on E1M2's sample -- tried and dropped, 2026-10-17.)"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import monstersight as MS
from doomfj.combat import PLAYER_R
from doomfj.config import Config
from doomfj.harness import W
from doomfj.world import World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
NFAR, NNEAR, NBLAST = 500, 150, 150
FAR, NEAR, BLAST = 1, 2, 3


@pytest.fixture(scope="module")
def world():
    return World(monsters="final", player="final", sight_rule="seen")


@pytest.fixture(scope="module")
def world2():
    """M8 F1.1: E1M2, the first map wider than 32 x 127 units"""
    from doomfj.wad import WadFile
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"))
    return World(mw, "E1M2", monsters="final", player="final", sight_rule="seen")


def _pieces(s) -> int:
    """the pieces a FAR sample's trace walks: the least power of two N with every piece <= PIECE units an axis"""
    _kind, px, py, qx16, qy16 = s[:5]
    d = max(abs((qx16 >> 16) - px), abs((qy16 >> 16) - py))
    n = 1
    while d > MS.PIECE * n:
        n *= 2
    return n


def _nib_bytes(vals, n):
    v = list(vals) + [0] * (2 * ((n + 1) // 2) - len(vals))
    return bytes(v[2 * i] | (v[2 * i + 1] << 4) for i in range(len(v) // 2))


def _states(w, rng):
    doors = [rng.choice((0, 0, w.door_nstates[si] - 1, rng.randrange(w.door_nstates[si]))) for si in w.door_order]
    lifts = [rng.randrange(len(w.lift_stops[si])) for si in w.lift_order]
    # M8 F1.3: a state per floor group on a WIDE map (E1M2: `fswitch` a vector, states then timers); E1M1's one 1-bit
    # switch draws exactly as before
    if not w.floor_wide:
        return doors, lifts, rng.randrange(2)
    return doors, lifts, [rng.randrange(g.n) for g in w.floor_groups]


def _maxr(w):
    return max([PLAYER_R] + list(w.mon_radius[:w.layout.nmon]))


def _samples(w):
    """[(kind, px, py, qx16, qy16, barrel, doors, lifts, switch)] -- FAR: monster to monster (Q whole units), anywhere
    in the map's box and across random segments at every range; NEAR: within NEAR of a 16.16 player; BLAST: barrel b's
    spot (P) to a target within the blast's margin (whole units or 16.16)"""
    rng = random.Random(0xFA2)
    vs = w.cmap.vertexes
    x0, x1 = min(v[0] for v in vs), max(v[0] for v in vs)
    y0, y1 = min(v[1] for v in vs), max(v[1] for v in vs)
    segs = MS.sight_segments(w)
    margin = MS.blast_margin(_maxr(w)) - 1
    out = []
    while len(out) < NFAR + NNEAR + NBLAST:
        kind = FAR if len(out) < NFAR else NEAR if len(out) < NFAR + NNEAR else BLAST
        doors, lifts, sw = _states(w, rng)
        b = 0
        if kind == BLAST:
            b = rng.randrange(len(w.barrel_things))
            t = w.barrel_things[b]
            p = (t.x, t.y)
            q16 = ((t.x + rng.randint(-margin, margin)) << 16 | rng.choice((0, rng.randrange(1 << 16))),
                   (t.y + rng.randint(-margin, margin)) << 16 | rng.choice((0, rng.randrange(1 << 16))))
        elif kind == FAR and rng.random() < 0.4:
            p = (rng.randint(x0, x1), rng.randint(y0, y1))
            q = (rng.randint(x0, x1), rng.randint(y0, y1))
            q16 = (q[0] << 16, q[1] << 16)
        else:
            s = segs[rng.randrange(len(segs))]
            t = rng.random()
            cx = int(s["a"][0] + t * (s["b"][0] - s["a"][0]))
            cy = int(s["a"][1] + t * (s["b"][1] - s["a"][1]))
            k = rng.choice((90, 300, 900, 2000)) if kind == FAR else 90
            p = (cx + rng.randint(-k, k), cy + rng.randint(-k, k))
            q16 = (((cx + rng.randint(-k, k)) << 16) | (0 if kind == FAR else rng.randrange(1 << 16)),
                   ((cy + rng.randint(-k, k)) << 16) | (0 if kind == FAR else rng.choice((0, rng.randrange(1 << 16)))))
            if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and x0 <= q16[0] >> 16 <= x1 and y0 <= q16[1] >> 16 <= y1):
                continue
            if kind == NEAR and aprox_distance((q16[0] >> 16) - p[0], (q16[1] >> 16) - p[1]) > MS.NEAR_UNITS:
                continue
        out.append((kind, p[0], p[1], q16[0], q16[1], b, doors, lifts, sw))
    return out + ([blocked52_blast(w)] if w.mapname == "E1M1" else [])


def blocked52_blast(w):
    """blocked52's fight_gate S2 / S4: barrel 19's blast to imp 45 at (2464, -624), every door shut -- door 145's
    lines (y -584 / -576) are in the way, both ends at NEGATIVE y. The game's bl_los was emitted unbiased beside the
    fight's biased segment blocks (barrelcode.barrel_parts did not pass `fight`) and saw through them."""
    t = w.barrel_things[19]
    assert (t.x, t.y) == (2512, -496), (t.x, t.y)
    return (BLAST, t.x, t.y, 2464 << 16, -624 << 16, 19, [0] * len(w.door_order), [0] * len(w.lift_order), 0)


def _model(w, s) -> int:
    kind, px, py, qx16, qy16, _b, doors, lifts, sw = s
    for d, v in enumerate(doors):
        w.ws.d_state[d] = v
    for k, v in enumerate(lifts):
        w.ws.l_state[k] = v
    for g, v in enumerate(sw if w.floor_wide else [sw]):     # M8 F1.3: World's one accessor
        w._set_floor(g, v, 0)
    w._mh_last = None
    w._door_phase_scene()
    if kind == BLAST:                      # combat._radius_attack: los_points(target, spot)
        return int(not w.los_points((qx16, qy16), (px << 16, py << 16)))
    return int(not w.los_points((px << 16, py << 16), (qx16, qy16)))


def _lines(w, mut=None):
    lists = None
    if mut == "margin":
        saved = MS.NEAR_MARGIN
        MS.NEAR_MARGIN = 0
        try:
            lists = MS.cell_lists(MS.sight_segments(w), MS.map_cells(w))
        finally:
            MS.NEAR_MARGIN = saved
    spots = [(t.x, t.y) for t in w.barrel_things]
    text = "\n".join(MS.near_los_lines(w, fight=True, lists=lists) + MS.far_los_lines(w)
                     + MS.blast_los_lines(w, spots, _maxr(w), fight=True)) + "\n"
    rep = {"first": ("    hex.if0 2, sf_n, sf_out\n", "    ;sf_out\n", 1),
           "logical": ("  sf_hx_n:\n    hex.shr_bit 10, sf_sx\n    hex.xor_by sf_sx + 9*dw, 8\n",
                       "  sf_hx_n:\n    hex.shr_bit 10, sf_sx\n", 1),
           "notree": ("    stl.fcall sf_walk, sf_wret\n", "", 1),
           "rundir": ("    hex.if1 1, sf_xn, sfw_x_b\n", "", 1),
           # the near prologue's box left unbiased: the fight's sl_seg compares signed values as unsigned
           "unbiased": ("    hex.xor_by sl_x0 + 7*dw, 8\n    hex.xor_by sl_x1 + 7*dw, 8\n", "", 3),
           "stub": ("sl_far:\n", "sl_far:\n    stl.fret sf_ret\n", 1)}
    if mut in rep:
        old, new, cnt = rep[mut]
        assert text.count(old) == cnt, (mut, text.count(old))
        text = text.replace(old, new)
    if mut == "noundo":                    # each block's xors applied once: the constants pile up
        out, seen = [], set()
        for ln in text.split("\n"):
            if ln.startswith("sg"):
                seen = set()
            if ln.startswith("    hex.xor_by ") and ("sl_cx" in ln or "sl_cy" in ln):
                if ln in seen:
                    continue
                seen.add(ln)
            out.append(ln)
        text = "\n".join(out)
    return text


def _run(tmp, w, samples, name, mut=None):
    """-> (verdicts, op count)"""
    nd, nl = len(w.door_order), len(w.lift_order)
    nf = len(w.floor_groups)                             # M8 F1.3: the floor groups (E1M1: the switch)
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        "hex.input 2, mm_x", "hex.input 2, mm_y", "hex.input 4, mt_tqx", "hex.input 4, mt_tqy", "hex.input 1, bl_b",
        "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
        *(["hex.input %d, fswitch" % ((nf + 1) // 2)] if w.floor_wide else ["hex.input 1, rbyte", "hex.mov 1, fswitch, rbyte"]),
        "hex.switch wmagic, out, far, near, blast, out, out, out, out, out, out, out, out, out, out, out, out",
        "near:", "hex.mov 8, viewx, mt_tqx", "hex.mov 8, viewy, mt_tqy", "stl.fcall sl_los, sl_ret", ";out",
        "blast:", "hex.mov 4, bl_px, mm_x", "hex.mov 4, bl_py, mm_y", "hex.mov 8, bl_qx, mt_tqx",
        "hex.mov 8, bl_qy, mt_tqy", "stl.fcall bl_los, bl_lret", ";out",
        "far:", "stl.fcall sl_far, sf_ret",
        "out:", "hex.print_as_digit 1, sl_hit, 0", "stl.output 10",
        ";loop", "done:", "stl.loop",
        _lines(w, mut),
        *MS.SL_DECLS, *MS.SF_DECLS, *MS.BL_LOS_DECLS,
        "wmagic: hex.vec 2", "rbyte: hex.vec 2", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
        "viewx: hex.vec 8", "viewy: hex.vec 8", "mt_tqx: hex.vec 8", "mt_tqy: hex.vec 8",
        "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)), "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)),
        "fswitch: hex.vec %d" % (2 * nf if w.floor_wide else 1)]) + "\n"
    src = tmp / ("%s.fj" % name)
    src.write_text(prog, encoding="utf-8")
    out = tmp / ("%s.fjm" % name)
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    feed = b""
    for kind, px, py, qx16, qy16, b, doors, lifts, sw in samples:
        feed += bytes([kind]) + struct.pack("<HHIIB", px & 0xFFFF, py & 0xFFFF, qx16 & M32, qy16 & M32, b)
        feed += _nib_bytes(doors, nd) + _nib_bytes(lifts, nl) + (_nib_bytes(sw, nf) if w.floor_wide else bytes([sw]))
    io = FixedIO(feed + bytes([0]))
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True).decode().split("\n")
    return [int(g) for g in got[:len(samples)]], term.op_counter


@pytest.fixture(scope="module")
def sample(world):
    s = _samples(world)
    return s, [_model(world, x) for x in s]


def test_the_blocked52_blast_is_blocked_in_the_model(world):
    """the fixed record means something: the model's blast LOS is blocked there (the binary's was clear)"""
    assert _model(world, blocked52_blast(world)) == 1


def test_the_sample_exercises_every_range(world, sample):
    s, want = sample
    far = [(x, v) for x, v in zip(s, want) if x[0] == FAR]
    beyond = sum(1 for x, _v in far if max(abs((x[3] >> 16) - x[1]), abs((x[4] >> 16) - x[2])) > 1000)
    blocked = sum(v for _x, v in far)
    assert 50 <= blocked <= len(far) - 50, blocked
    assert beyond >= 50, beyond
    for kind in (NEAR, BLAST):
        v = [w_ for x, w_ in zip(s, want) if x[0] == kind]
        assert 15 <= sum(v) <= len(v) - 15, (kind, sum(v))


def test_the_far_los_follows_the_model(tmp_path, world, sample):
    s, want = sample
    got, ops = _run(tmp_path, world, s, "sfar")
    bad = [(k, s[k][:6], g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(s), bad[:3])
    _got0, ops0 = _run(tmp_path, world, s, "sfar_stub", mut="stub")
    per = (ops - ops0) / NFAR
    print("\nFAR LOS: %d checks, %.0f ops a check (MEASURED: the run minus the stubbed run)" % (NFAR, per))
    assert per < 200_000, "O-B2's fallback trigger: %.0f ops a check" % per


@pytest.mark.parametrize("mut", ["margin", "first", "logical", "notree", "rundir", "unbiased", "noundo"])
def test_control_a_broken_far_los_is_caught(tmp_path, world, sample, mut):
    s, want = sample
    got, _ops = _run(tmp_path, world, s, "sfar_" + mut, mut=mut)
    assert got != want, "%s passed: the comparison is vacuous" % mut


# ---- M8 F1.1: E1M2, wider than the old 32 pieces ----------------------------------------------------------------------
def _long_samples(w, n=120):
    """FAR traces of more than 32 pieces anywhere in the map's box that at most TWO sight segments touch (any state):
    their verdict hangs on one wall or none, so a walk that skips cells (the "cap32" control) changes it. MEASURED on
    E1M2: ~4% of random long traces qualify (45 of 3,000 touch none, 86 touch one or two)"""
    from doomfj.world import segments_touch
    rng = random.Random(0x64)
    vs = w.cmap.vertexes
    x0, x1 = min(v[0] for v in vs), max(v[0] for v in vs)
    y0, y1 = min(v[1] for v in vs), max(v[1] for v in vs)
    segs = MS.sight_segments(w)
    out = []
    while len(out) < n:
        p, q = (rng.randint(x0, x1), rng.randint(y0, y1)), (rng.randint(x0, x1), rng.randint(y0, y1))
        smp = (FAR, p[0], p[1], q[0] << 16, q[1] << 16, 0) + _states(w, rng)
        if _pieces(smp) <= 32:
            continue
        if sum(1 for s in segs if segments_touch(p, q, s["a"], s["b"])) <= 2:
            out.append(smp)
    return out


@pytest.fixture(scope="module")
def sample2(world2):
    s = _samples(world2) + _long_samples(world2)
    return s, [_model(world2, x) for x in s]


def test_e1m2_traces_walk_past_32_pieces(world2, sample2):
    s, want = sample2
    far = [x for x in s if x[0] == FAR]
    assert max(_pieces(x) for x in far) == 64, max(_pieces(x) for x in far)
    long_ = [v for x, v in zip(s, want) if x[0] == FAR and _pieces(x) > 32]
    assert len(long_) >= 120 and 10 <= sum(long_) <= len(long_) - 10, (len(long_), sum(long_))
    blocked = sum(v for x, v in zip(s, want) if x[0] == FAR)
    assert 50 <= blocked <= len(far) - 50, blocked


def test_the_far_los_follows_the_model_on_e1m2(tmp_path, world2, sample2):
    s, want = sample2
    got, ops = _run(tmp_path, world2, s, "sfar2")
    bad = [(k, s[k][:6], g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(s), bad[:3])


@pytest.mark.parametrize("mut", ["first", "logical", "rundir", "notree"])
def test_control_a_broken_far_los_is_caught_on_e1m2(tmp_path, world2, sample2, mut):
    """the E1M2 comparison is not vacuous: the far walk's own mutants part on its sample too"""
    s, want = sample2
    got, _ops = _run(tmp_path, world2, s, "sfar2_" + mut, mut=mut)
    assert got != want, "%s passed on E1M2: the comparison is vacuous" % mut
