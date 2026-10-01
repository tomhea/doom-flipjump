"""M7 P3.2c (docs/gp-monsters.md 8.5): the NEAR line of sight on the real engine (`monstersight.near_los_lines`:
the cell lists, the per-segment blocks, `sl_seg`'s 48-bit orientations) against the model's `World.los_points` --
a monster's integer position to a player's 16.16 one within NEAR, with every door, both lifts and the floor switch
in random states.

The sample: traces past random sight segments (both verdicts in volume), traces that pass EXACTLY through a segment's
end (an orientation of 0: the touching rule), traces collinear with a segment, and dynamic segments whose verdict
turns on their sector's state.

⚠ ONE IMAGE, MANY RECORDS: a leaf that leaves a register dirty corrupts the next record.
⚠ THE CONTROLS (R9): dynamic segments read as always shut, the touching codes dropped from the straddle (strict
crossings only), the lists built without the NEAR margin, and o4 without its o3 term must each part from the model.
"""
import random
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import monstersight as MS
from doomfj.config import Config
from doomfj.harness import W
from doomfj.world import World, aprox_distance

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
M32 = 0xFFFFFFFF
N = 900


@pytest.fixture(scope="module")
def world():
    return World(monsters="decide", sight_rule="seen")


def _nib_bytes(vals, n):
    v = list(vals) + [0] * (2 * ((n + 1) // 2) - len(vals))
    return bytes(v[2 * i] | (v[2 * i + 1] << 4) for i in range(len(v) // 2))


def _states(w, rng):
    doors = [rng.choice((0, 0, w.door_nstates[si] - 1, rng.randrange(w.door_nstates[si]))) for si in w.door_order]
    lifts = [rng.randrange(len(w.lift_stops[si])) for si in w.lift_order]
    return doors, lifts, rng.randrange(2)


def _near(dx, dy):
    return aprox_distance(dx, dy) <= MS.NEAR_UNITS


def _samples(w):
    """[(px, py, qx16, qy16, doors, lifts, switch)]"""
    rng = random.Random(0x32C)
    segs = MS.sight_segments(w)
    dyn = [k for k, s in enumerate(segs) if s["dyn"]]
    out = []
    while len(out) < N:
        doors, lifts, sw = _states(w, rng)
        r = rng.random()
        s = segs[rng.choice(dyn) if r < 0.3 else rng.randrange(len(segs))]
        (ax, ay), (bx, by) = s["a"], s["b"]
        t = rng.random()
        cx, cy = ax + t * (bx - ax), ay + t * (by - ay)
        px, py = int(cx) + rng.randint(-90, 90), int(cy) + rng.randint(-90, 90)
        if r < 0.8:                                       # a random trace across the segment's neighbourhood
            qx16 = ((int(cx) + rng.randint(-90, 90)) << 16) + rng.choice((0, rng.randrange(1 << 16)))
            qy16 = ((int(cy) + rng.randint(-90, 90)) << 16) + rng.choice((0, rng.randrange(1 << 16)))
        elif r < 0.9:                                     # through the segment's end exactly: o1 or o2 is 0
            e = (ax, ay) if rng.random() < 0.5 else (bx, by)
            k = rng.choice((1, 2))
            qx16, qy16 = (px + k * (e[0] - px)) << 16, (py + k * (e[1] - py)) << 16
        else:                                             # on the segment's line: all four orientations 0
            g = max(abs(bx - ax), abs(by - ay)) or 1
            u, v = (bx - ax) / g, (by - ay) / g
            step = rng.choice((-3, -1, 1, 2, 4)) * 16
            px, py = ax + round(u * rng.randint(-40, 40)), ay + round(v * rng.randint(-40, 40))
            if (bx - ax) % g or (by - ay) % g:
                continue
            qx16, qy16 = (px + int(u * step)) << 16, (py + int(v * step)) << 16
        if not _near((qx16 >> 16) - px, (qy16 >> 16) - py):
            continue
        out.append((px, py, qx16, qy16, doors, lifts, sw))
    return out


def _model(w, s) -> int:
    px, py, qx16, qy16, doors, lifts, sw = s
    for d, v in enumerate(doors):
        w.ws.d_state[d] = v
    for k, v in enumerate(lifts):
        w.ws.l_state[k] = v
    w.ws.f_switch = sw
    w._mh_last = None
    w._door_phase_scene()
    return int(not w.los_points((px << 16, py << 16), (qx16, qy16)))


def _lines(w, mut=None):
    saved = MS.STRADDLE, MS.NEAR_MARGIN
    try:
        if mut == "touch":
            MS.STRADDLE = (6, 9)                          # strictly opposite signs only
        if mut == "margin":
            MS.NEAR_MARGIN = 0
        text = "\n".join(MS.near_los_lines(w))
    finally:
        MS.STRADDLE, MS.NEAR_MARGIN = saved
    if mut == "nodyn":
        text = "\n".join(ln for ln in text.split("\n")
                         if not (ln.startswith("    hex.if_flags ") and ("dstate" in ln or "lstate" in ln
                                                                        or "fswitch" in ln)))
    if mut == "noshift":
        assert text.count("    hex.add 12, sl_o, sl_t12\n") == 1
        text = text.replace("    hex.add 12, sl_o, sl_t12\n", "")
    return text


def _run(tmp, w, samples, name, mut=None):
    nd, nl = len(w.door_order), len(w.lift_order)
    prog = "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, wmagic", "hex.if0 2, wmagic, done",
        "hex.input 2, mm_x", "hex.input 2, mm_y", "hex.input 4, viewx", "hex.input 4, viewy",
        "hex.input %d, dstate" % ((nd + 1) // 2), "hex.input %d, lstate" % ((nl + 1) // 2),
        "hex.input 1, rbyte", "hex.mov 1, fswitch, rbyte",
        "stl.fcall sl_los, sl_ret",
        "hex.print_as_digit 1, sl_hit, 0", "stl.output 10",
        ";loop", "done:", "stl.loop",
        _lines(w, mut),
        *MS.SL_DECLS,
        "wmagic: hex.vec 2", "rbyte: hex.vec 2", "mm_x: hex.vec 4", "mm_y: hex.vec 4",
        "viewx: hex.vec 8", "viewy: hex.vec 8",
        "dstate: hex.vec %d" % (2 * ((nd + 1) // 2)), "lstate: hex.vec %d" % (2 * ((nl + 1) // 2)),
        "fswitch: hex.vec 1"]) + "\n"
    src = tmp / ("%s.fj" % name)
    src.write_text(prog, encoding="utf-8")
    out = tmp / ("%s.fjm" % name)
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), src.resolve()],
                out, memory_width=W, print_time=False)
    feed = b""
    for px, py, qx16, qy16, doors, lifts, sw in samples:
        feed += bytes([0xD0]) + struct.pack("<HHII", px & 0xFFFF, py & 0xFFFF, qx16 & M32, qy16 & M32)
        feed += _nib_bytes(doors, nd) + _nib_bytes(lifts, nl) + bytes([sw])
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    got = io.get_output(allow_incomplete_output=True).decode().split("\n")
    return [int(g) for g in got[:len(samples)]]


@pytest.fixture(scope="module")
def sample(world):
    s = _samples(world)
    return s, [_model(world, x) for x in s]


def test_the_sample_exercises_every_rule(world, sample):
    s, want = sample
    blocked = sum(want)
    assert 150 <= blocked <= len(s) - 150, "only %d of %d traces blocked" % (blocked, len(s))
    # a dynamic segment decides: the same trace with every door, lift and the switch at state 0 differs
    shut = sum(_model(world, (px, py, qx, qy, [0] * len(d), [0] * len(l_), 0)) != v
               for (px, py, qx, qy, d, l_, sw), v in zip(s, want))
    assert shut >= 20, "only %d traces turn on a door, lift or the switch" % shut
    # the touching rule decides: strict crossings alone give another verdict on some traces
    import doomfj.world as Wm
    orig = Wm.segments_touch

    def strict(p, q, a, b):
        o = [Wm._orient(*p, *q, *a), Wm._orient(*p, *q, *b), Wm._orient(*a, *b, *p), Wm._orient(*a, *b, *q)]
        return o[0] * o[1] < 0 and o[2] * o[3] < 0
    Wm.segments_touch = strict
    try:
        touch = sum(_model(world, x) != v for x, v in zip(s, want))
    finally:
        Wm.segments_touch = orig
    assert touch >= 5, "only %d traces turn on a touch" % touch


def test_the_cell_lists_hold_every_candidate(world, sample):
    """the lists' claim, in the model's own terms: every segment whose box the trace's box meets is in the
    monster's cell's list -- and without the NEAR margin some are not (the control the fj `margin` run repeats)"""
    s, _want = sample
    segs = MS.sight_segments(world)

    def missing(margin):
        saved = MS.NEAR_MARGIN
        MS.NEAR_MARGIN = margin
        try:
            lists = MS.cell_lists(segs, MS.map_cells(world))
        finally:
            MS.NEAR_MARGIN = saved
        n = 0
        for px, py, qx16, qy16, *_ in s:
            x0, x1 = sorted((px << 16, qx16))
            y0, y1 = sorted((py << 16, qy16))
            have = set(lists.get((MS.cell_of(px), MS.cell_of(py)), ()))
            n += sum(1 for k, g in enumerate(segs) if k not in have and not (
                g["box"][1] << 16 < x0 or g["box"][0] << 16 > x1 or g["box"][3] << 16 < y0 or g["box"][2] << 16 > y1))
        return n
    assert missing(MS.NEAR_MARGIN) == 0
    assert missing(0) > 0, "the margin control finds nothing to miss"


def test_the_near_los_follows_the_model(tmp_path, world, sample):
    s, want = sample
    got = _run(tmp_path, world, s, "slos")
    bad = [(k, s[k][:4], g, w_) for k, (g, w_) in enumerate(zip(got, want)) if g != w_]
    assert not bad, "%d of %d parted, first %s" % (len(bad), len(s), bad[:3])


@pytest.mark.parametrize("mut", ["nodyn", "touch", "margin", "noshift"])
def test_control_a_broken_los_is_caught(tmp_path, world, sample, mut):
    s, want = sample
    got = _run(tmp_path, world, s, "slos_" + mut, mut=mut)
    assert got != want, "%s passed: the comparison is vacuous" % mut
