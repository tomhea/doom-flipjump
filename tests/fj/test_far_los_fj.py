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
constants not undone after the test."""
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


def _nib_bytes(vals, n):
    v = list(vals) + [0] * (2 * ((n + 1) // 2) - len(vals))
    return bytes(v[2 * i] | (v[2 * i + 1] << 4) for i in range(len(v) // 2))


def _states(w, rng):
    doors = [rng.choice((0, 0, w.door_nstates[si] - 1, rng.randrange(w.door_nstates[si]))) for si in w.door_order]
    lifts = [rng.randrange(len(w.lift_stops[si])) for si in w.lift_order]
    return doors, lifts, rng.randrange(2)


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
    return out


def _model(w, s) -> int:
    kind, px, py, qx16, qy16, _b, doors, lifts, sw = s
    for d, v in enumerate(doors):
        w.ws.d_state[d] = v
    for k, v in enumerate(lifts):
        w.ws.l_state[k] = v
    w.ws.f_switch = sw
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
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        "hex.input 2, mm_x", "hex.input 2, mm_y", "hex.input 4, mt_tqx", "hex.input 4, mt_tqy", "hex.input 1, bl_b",
        "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
        "hex.input 1, rbyte", "hex.mov 1, fswitch, rbyte",
        "sim.jump16 wmagic, out, far, near, blast, out, out, out, out, out, out, out, out, out, out, out, out",
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
        "fswitch: hex.vec 1"]) + "\n"
    src = tmp / ("%s.fj" % name)
    src.write_text(prog, encoding="utf-8")
    out = tmp / ("%s.fjm" % name)
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    feed = b""
    for kind, px, py, qx16, qy16, b, doors, lifts, sw in samples:
        feed += bytes([kind]) + struct.pack("<HHIIB", px & 0xFFFF, py & 0xFFFF, qx16 & M32, qy16 & M32, b)
        feed += _nib_bytes(doors, nd) + _nib_bytes(lifts, nl) + bytes([sw])
    io = FixedIO(feed + bytes([0]))
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True).decode().split("\n")
    return [int(g) for g in got[:len(samples)]], term.op_counter


@pytest.fixture(scope="module")
def sample(world):
    s = _samples(world)
    return s, [_model(world, x) for x in s]


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
