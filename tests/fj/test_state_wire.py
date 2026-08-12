"""M14-b/M14-c — the binary state wire and the player sim, tested as fj without building a renderer.

`emit_wall_renderer(state_wire="bin", player_sim=True)` replaces three `hex.input_dec_*` calls with:
a MAGIC byte check, three raw 32-bit reads, a key byte, ONE TIC of the player simulation, the
16.16 -> integer-map-unit derivation the BSP walk needs, and the state echo. Every one of those is a
few lines of fj, and every one is checkable in a program that assembles in seconds -- so none of
them has to be debugged inside a 20-minute renderer build.

The programs here splice in the EMITTER'S OWN TEXT (`_state_wire_lines`, which is what the
emitter itself calls -- and which splices in `_player_sim_lines` when `sim=True`; nothing is
retyped), so a change to the emitter that breaks the wire or the sim fails here first.

⚠ THE MULTI-FRAME PART MATTERS MOST. handoff-m14.md section 6: "One frame proving byte-exact says
nothing about state drift on frame 200." The sim is stateful across frames while every existing gate
is single-frame, so `test_sim_matches_the_oracle_over_N_tics` runs the binary 200 times -- feeding
each tic's echoed state back in, exactly as the host relay will -- and compares the WHOLE sequence
against `ReferenceModel.step_sim`. A one-ulp difference in the first tic's FixedMul shows up there
and nowhere else.
"""
import random
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_emit_dispatch_table_fj, generate_trig_idioms_fj
from doomfj.reference_model import ReferenceModel, SimState
from doomfj.wall_renderer import _state_wire_lines
from doomfj.wireformat import (MAGIC, STATE_BYTES, STATE_CMD, decode_state, encode_feed,
                               keys_dict)

SRC = [Path("src/fj") / f for f in ("fixed_point.fj", "present.fj", "stream_render.fj")]
CFG = Config()
RM = ReferenceModel(CFG)


def _program(sim: bool) -> str:
    return "\n".join([
        "stl.startup_and_init_all",
        *_state_wire_lines("bin", sim=sim),
        # ... then dump the DERIVED integer coords and the key byte, which the echo does not carry
        "hex.print_as_digit 10, vx, 0", "stl.output 10",
        "hex.print_as_digit 10, vy, 0", "stl.output 10",
        "hex.print_as_digit 2, pkeys, 0", "stl.output 10",
        "stl.loop",
        "bad:", "stl.output_char 0x21", "stl.loop",       # '!' -- a rejected feed is visible
        "wmagic: hex.vec 2", "pkeys: hex.vec 2",
        "viewx: hex.vec 8", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        "vx: hex.vec 10", "vy: hex.vec 10",
        *(["pmove: hex.vec 8", "pangt: hex.vec 8", "pangi: hex.vec 3", "pmvc: hex.vec 8",
           "pmvs: hex.vec 8", "pmvdx: hex.vec 8", "pmvdy: hex.vec 8"] if sim else []),
        generate_emit_dispatch_table_fj("byte", list(range(256)), index_nibbles=2),
        # the sim's trig comes from the SAME generator the renderer bakes (R6) -- a private sine
        # table here would prove the fj matches itself, not that it matches the oracle
        *([generate_trig_idioms_fj("finesine", CFG.TRIG_N, 16)] if sim else []),
    ]) + "\n"


def _assemble(tmp_path, sim: bool) -> Path:
    src = tmp_path / f"wire{'_sim' if sim else ''}.fj"
    src.write_text(_program(sim), encoding="utf-8")
    out = tmp_path / f"wire{'_sim' if sim else ''}.fjm"
    consts = CFG.emit_fj_consts(tmp_path / "fj_consts.fj")     # present.fj reads W/H/BPP/NCOLORS
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()],
                out, memory_width=W, print_time=False)
    return out


@pytest.fixture(scope="module")
def wire_fjm(tmp_path_factory):
    return _assemble(tmp_path_factory.mktemp("wire"), sim=False)


@pytest.fixture(scope="module")
def sim_fjm(tmp_path_factory):
    return _assemble(tmp_path_factory.mktemp("sim"), sim=True)


def _run(fjm: Path, feed: bytes) -> bytes:
    io = FixedIO(feed)
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True)


def _parse(out: bytes):
    """(state, vx, vy, keys) out of the program's output."""
    assert out[0] == STATE_CMD, f"first byte {out[0]:#x} is not STATE_CMD"
    state = decode_state(out[1:1 + STATE_BYTES])
    vx_s, vy_s, keys_s = out[1 + STATE_BYTES:].decode("ascii").split("\n")[:3]
    return state, int(vx_s, 16), int(vy_s, 16), int(keys_s, 16)


# ── M14-b: the wire ────────────────────────────────────────────────────────────────────────────

VIEWPOINTS = [
    (664, 291, 0x18000000, 0),
    (1272, -724, 1073741824, 0b0101),
    (1869, 479, 2147483648, 0b1111),
    (-416, 256, 0, 1),
    (0, 0, 0xFFFFFFFF, 0),
    (-1, -1, 1, 0b1000),
    (32767, -32768, 0x7FFFFFFF, 0),          # the int16 extremes the map coords can reach
]


@pytest.mark.parametrize("vx,vy,va,keys", VIEWPOINTS)
def test_wire_round_trips_and_derives_the_map_coords(wire_fjm, vx, vy, va, keys):
    state, got_vx, got_vy, got_keys = _parse(_run(wire_fjm, encode_feed(vx << 16, vy << 16, va, keys)))
    assert state == (vx << 16, vy << 16, va), "the echoed state must be what was fed, bit for bit"
    assert got_keys == keys
    # vx/vy are 10-nibble two's complement -- exactly what `hex.input_dec_int 10` produced before
    assert got_vx == (vx & 0xFFFFFFFFFF), f"vx derived {got_vx:#x} from {vx}"
    assert got_vy == (vy & 0xFFFFFFFFFF), f"vy derived {got_vy:#x} from {vy}"


def test_a_fractional_position_floors(wire_fjm):
    """The derivation is an arithmetic shift, so it floors -- and that is what the dec wire's
    integer coordinate meant too. Stated as a test because M14-c starts producing fractions."""
    for x16, want in ((100 << 16 | 0x8000, 100),      # +100.5 -> 100
                      ((-100 << 16) + 0x8000, -100),  #  -99.5 -> -100 (floor, not toward zero)
                      ((-100 << 16) - 0x8000, -101),  # -100.5 -> -101
                      (-100 << 16, -100)):            # exactly -100 stays -100
        _state, got_vx, _got_vy, _keys = _parse(_run(wire_fjm, encode_feed(x16, 0, 0, 0)))
        assert got_vx == (want & 0xFFFFFFFFFF), f"{x16:#010x} -> {got_vx:#x}, want {want}"


@pytest.mark.parametrize("first", [0x00, 0x0A, 0x71, 0xD1, 0x1D, 0xFF])
def test_a_bad_magic_byte_reaches_the_halt(wire_fjm, first):
    """⚠ THE CONTROL FOR THE MAGIC BYTE. The R0 build gate feeds ONE junk byte and needs the
    program to halt on it; without a magic check a binary wire would block reading 13 more bytes and
    the gate would die on EOF instead. `0xD1` and `0x1D` are the near misses -- one nibble right."""
    out = _run(wire_fjm, bytes([first]) + b"\n")
    assert out == b"!", f"feed {first:#x} produced {out!r}, expected the bad: halt"


def test_the_good_magic_byte_is_the_one_the_wire_module_defines(wire_fjm):
    """R9-ish: the test above only proves rejection. This proves the accepted byte is MAGIC and not
    some other value the emitter happens to bake -- i.e. that the two halves agree."""
    out = _run(wire_fjm, bytes([MAGIC]) + b"\x00" * 13)
    assert out[0] == STATE_CMD and out != b"!"


# ── M14-c: the player sim ──────────────────────────────────────────────────────────────────────

def _oracle(state, keys: int):
    s = RM.step_sim(SimState(state[0] & 0xFFFFFFFF, state[1] & 0xFFFFFFFF, state[2], "E1M1"),
                    keys_dict(keys))
    return (s.x - (1 << 32) if s.x >> 31 else s.x,
            s.y - (1 << 32) if s.y >> 31 else s.y, s.angle)


@pytest.mark.parametrize("keys", range(16))
def test_one_tic_matches_the_oracle_for_every_key_combination(sim_fjm, keys):
    """All 16 combinations, including the two that must cancel: forward+back does not move, and
    turn_left+turn_right leaves the angle where it was."""
    start = (664 << 16, 291 << 16, 0x18000000)
    got, _vx, _vy, got_keys = _parse(_run(sim_fjm, encode_feed(*start, keys)))
    assert got_keys == keys
    assert got == _oracle(start, keys), f"keys={keys:#06b}"


def test_the_sim_is_off_when_no_key_is_pressed(sim_fjm):
    """The byte-exactness argument for M14-c rests on this: with keys=0 the sim binary must render
    from exactly the state it was fed, so its frame is the M14-b frame."""
    for vx, vy, va, _k in VIEWPOINTS:
        got, _a, _b, _c = _parse(_run(sim_fjm, encode_feed(vx << 16, vy << 16, va, 0)))
        assert got == (vx << 16, vy << 16, va)


@pytest.mark.parametrize("tics,seed", [(200, 14)])
def test_sim_matches_the_oracle_over_N_tics(sim_fjm, tics, seed):
    """⚠ THE MULTI-FRAME GATE (handoff-m14.md section 6). Feed each tic's ECHOED state back in, the
    way the host relay will, and require the whole trajectory to track `step_sim` exactly. Drift of
    a single ulp compounds here and is invisible in any single-frame check."""
    rng = random.Random(seed)
    state = (-416 << 16, 256 << 16, 0)
    want = state
    for tic in range(tics):
        keys = rng.randrange(16)
        got, _vx, _vy, _k = _parse(_run(sim_fjm, encode_feed(*state, keys)))
        want = _oracle(want, keys)
        assert got == want, (f"tic {tic} (keys={keys:#06b}): fj {got} != oracle {want} "
                             f"-- the trajectory has diverged")
        state = got                                    # the relay: this tic's output is next input


@pytest.mark.parametrize("start,keys", [
    (0xFFFFFFFF - 3, 0b0100),      # turning LEFT across the 2**32 -> 0 boundary
    (2, 0b1000),                   # ... and turning RIGHT back down through it
    (0x7FFFFFFF, 0b0100),          # and across the sign bit, which nothing here should care about
])
def test_the_angle_wraps_modularly(sim_fjm, start, keys):
    """The angle is modular, and the fj emits `-= ANGLE_TURN` as `+= (2**32 - ANGLE_TURN)`. Start
    a few tics from the wrap instead of walking a whole revolution: the boundary is the only place
    the identity can fail, and 12 tics prove it where 6,710 only cost 11 minutes."""
    state = want = (-416 << 16, 256 << 16, start)
    for tic in range(12):
        got, _vx, _vy, _k = _parse(_run(sim_fjm, encode_feed(*state, keys)))
        want = _oracle(want, keys)
        assert got == want, f"tic {tic} from angle {start:#010x}"
        state = got
