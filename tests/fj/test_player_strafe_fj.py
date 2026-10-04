"""M7 P4.1 -- the game tier's strafe: `_player_sim_lines(strafe=True)`, the REAL emitted text, against
`ReferenceModel.step_sim(strafe=True)` (the model's `combat._player_move` side step): every combination of the four
moves and the two strafe keys at several poses, and a 300-tic trajectory fed back on itself, where one ulp would
compound. Collision-free: the collision is the shared candidate test both moves feed (`cm_dx` / `cm_dy`).

R9: the side step's sign flipped (dy += instead of -=) and the two strafe bits swapped -- each parts from the oracle.
"""
import random
import struct

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from pathlib import Path

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_trig_idioms_fj
from doomfj.reference_model import ReferenceModel, SimState
from doomfj.wall_renderer import _player_sim_lines
from doomfj.wireformat import keys_byte

CFG = Config()
FJ = Path(__file__).resolve().parents[2] / "src" / "fj"
RM = ReferenceModel(CFG)
M32 = 0xFFFFFFFF
NAMES = ("forward", "back", "turn_left", "turn_right", "strafe_left", "strafe_right")
MUTS = {"sign": ("hex.sub 8, pmvdy, psdy", "hex.add 8, pmvdy, psdy"),
        "swap": ("simsr_no, simsr_yes", "simsr_yes, simsr_no")}


def _program(mut=None):
    text = "\n".join(_player_sim_lines(collide=False, strafe=True))
    if mut:
        old, new = MUTS[mut]
        assert text.count(old) == 1, mut
        text = text.replace(old, new)
    return "\n".join([
        "stl.startup_and_init_all",
        "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
        "hex.input 4, viewx", "hex.input 4, viewy", "hex.input 4, viewangle", "hex.input 1, pkeys",
        text,
        "hex.print_as_digit 8, viewx, 0", "stl.output 44", "hex.print_as_digit 8, viewy, 0", "stl.output 44",
        "hex.print_as_digit 8, viewangle, 0", "stl.output 10", ";loop",
        "done:", "stl.loop",
        "rmagic: hex.vec 2", "pkeys: hex.vec 2", "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "pmove: hex.vec 8", "pangt: hex.vec 8", "pangi: hex.vec 3", "pmvc: hex.vec 8", "pmvs: hex.vec 8",
        "pmvdx: hex.vec 8", "pmvdy: hex.vec 8", "psid: hex.vec 8", "psdx: hex.vec 8", "psdy: hex.vec 8",
        generate_trig_idioms_fj("finesine", CFG.TRIG_N, 16),
    ]) + "\n"


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("strafe")
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")

    def make(mut=None):
        src = tmp / ("strafe_%s.fj" % (mut or "ok"))
        src.write_text(_program(mut), encoding="utf-8")
        out = tmp / ("strafe_%s.fjm" % (mut or "ok"))
        fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), src.resolve()], out, memory_width=W,
                    print_time=False)
        return out
    return make


def _feed(records):
    return b"".join(bytes([1]) + struct.pack("<III", x & M32, y & M32, a & M32) + bytes([keys_byte(k)])
                    for (x, y, a), k in records) + bytes([0])


def _run(fjm, records):
    io = FixedIO(_feed(records))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return [tuple(int(v, 16) for v in line.split(","))
            for line in io.get_output(allow_incomplete_output=True).decode().split("\n")[:len(records)]]


def _oracle(pose, k):
    s = RM.step_sim(SimState(pose[0], pose[1], pose[2], "E1M1"), k, strafe=True)
    return (s.x & M32, s.y & M32, s.angle & M32)


def _combos():
    for bits in range(64):
        yield {n: bool(bits >> i & 1) for i, n in enumerate(NAMES)}


POSES = [(664 << 16, 291 << 16, 0x18000000), (-416 << 16, 256 << 16, 0), (1272 << 16, -724 << 16, 0x40000000),
         (0, 0, 0xA5A5A5A5), (1869 << 16, 479 << 16, 0xC0000123)]


def test_every_key_combination_at_every_pose(build):
    recs = [(p, k) for p in POSES for k in _combos()]
    got = _run(build(), recs)
    want = [_oracle(p, k) for p, k in recs]
    bad = [(i, recs[i][1]) for i, (g, w) in enumerate(zip(got, want)) if g != w]
    assert not bad, "first mismatch at record %d, keys %s" % bad[0]


def test_a_strafing_trajectory_tracks_the_oracle(build):
    rng = random.Random(5)
    fjm = build()
    pose, want = (-416 << 16, 256 << 16, 0x12345678), (-416 << 16, 256 << 16, 0x12345678)
    for tic in range(300):
        k = {n: rng.random() < 0.3 for n in NAMES}
        (got,) = _run(fjm, [(pose, k)])
        want = _oracle(want, k)
        assert got == want, "tic %d diverged" % tic
        pose = got


@pytest.mark.parametrize("mut", sorted(MUTS))
def test_the_checks_catch_a_broken_strafe(build, mut):
    recs = [(p, k) for p in POSES for k in _combos()]
    got = _run(build(mut), recs)
    assert got != [_oracle(p, k) for p, k in recs], "the mutant %s went unnoticed" % mut
