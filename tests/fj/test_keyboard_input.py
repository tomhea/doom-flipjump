"""M5 — `kb.poll` (src/fj/input.fj) against the flipjump keyboard device, with no renderer.

The standalone `.fjm` has no host to hand it the player's state, so it learns about the player from
the keyboard device: one input hex per poll, a keycode byte on an event, and four PERSISTENT flag
cells that hold "this key is held". Everything that can go wrong there is checkable in a program
that assembles in seconds, so none of it has to be debugged inside a 60-minute renderer build.

The two failure modes worth naming:
  * a poll that reads the status hex but not the keycode byte leaves every LATER poll reading a
    byte out of phase -- the whole input stream desynchronises after one unrecognised key;
  * a flag driven by the frame rather than by the transition makes holding a key take one step and
    then stop.
Both show up as a wrong digit line here.

The expected flags come from a plain-Python mirror of the device's own contract (one event per
tic, due when tic >= event.tic), NOT from the program -- so this compares two independent things.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj.config import Config
from doomfj.harness import W

SRC = [Path("src/fj") / "input.fj"]
CFG = Config()

POLLS = 8          # polls per "frame", the same unroll the emitter uses
FRAMES = 6
KEYS = ("f", "b", "l", "r")

# keycode -> which flag, mirroring the macro's own comment table
BINDING = {0x77: "f", 0x80: "f", 0x73: "b", 0x81: "b",
           0x61: "l", 0x82: "l", 0x64: "r", 0x83: "r"}


def _program() -> str:
    lines = ["stl.startup_and_init_all"]
    for _ in range(FRAMES):
        lines.append(f"rep({POLLS}, i) kb.poll kstat, kcode, kfwd, kback, kleft, kright, bad")
        lines += [f"hex.print_as_digit k{name}, 0" for name in
                  ("fwd", "back", "left", "right")]
        lines.append("stl.output 10")
    lines += ["stl.loop",
              # the halt a non-keyboard input stream gets -- '!' so a rejected run is visible
              "bad:", "stl.output_char 0x21", "stl.loop",
              "kstat: hex.vec 1", "kcode: hex.vec 2",
              "kfwd: hex.vec 1", "kback: hex.vec 1", "kleft: hex.vec 1", "kright: hex.vec 1"]
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def kb_fjm(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("kb")
    src = tmp / "kb.fj"
    src.write_text(_program(), encoding="utf-8")
    out = tmp / "kb.fjm"
    fj.assemble([*[p.resolve() for p in SRC], src.resolve()], out, memory_width=W,
                print_time=False)
    return out


def _run(fjm: Path, events) -> list:
    """run the program on a scripted key script; returns one "fblr" string per frame."""
    io = KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    text = io.get_output(allow_incomplete_output=True).decode("ascii")
    return text.split("\n")[:FRAMES]


def _expected(events, binding=None) -> list:
    """the same thing in plain python, from the DEVICE's contract: at most one event per tic, due
    once the tic clock reaches it; the program prints its flags after every POLLS polls."""
    binding = BINDING if binding is None else binding
    pending = sorted((KeyEvent(*e) for e in events), key=lambda e: e.tic)
    held = {name: 0 for name in KEYS}
    out, index = [], 0
    for tic in range(FRAMES * POLLS):
        if index < len(pending) and pending[index].tic <= tic:
            event = pending[index]
            index += 1
            name = binding.get(event.keycode)
            if name is not None:
                held[name] = 1 if event.is_down else 0
        if tic % POLLS == POLLS - 1:
            out.append("".join(str(held[name]) for name in KEYS))
    return out


SCRIPTS = {
    "nothing at all": [],
    "hold w across frames": [(0, True, 0x77)],
    "press and release w": [(0, True, 0x77), (10, False, 0x77)],
    "every key down, then up": [(0, True, 0x77), (1, True, 0x73), (2, True, 0x61),
                                (3, True, 0x64), (16, False, 0x77), (17, False, 0x73),
                                (18, False, 0x61), (19, False, 0x64)],
    "the arrows bind the same": [(0, True, 0x80), (1, True, 0x82), (12, False, 0x80),
                                 (13, False, 0x82)],
    # THE PHASE TEST: unrecognised keycodes between real ones. If a poll ever skipped the keycode
    # byte, every event after the first junk key would be read out of phase and the flags would be
    # garbage from there on.
    "junk keys between real ones": [(0, True, 0x71), (1, True, 0x77), (2, True, 0x2E),
                                    (3, True, 0x64), (9, False, 0x5B), (10, False, 0x77),
                                    (20, True, 0xFF), (21, True, 0x73)],
    "a key held down twice never sticks off": [(0, True, 0x77), (1, True, 0x77),
                                               (9, False, 0x77)],
}


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_flags_track_the_key_script(kb_fjm, name):
    events = SCRIPTS[name]
    assert _run(kb_fjm, events) == _expected(events)


def test_a_non_keyboard_input_stream_halts_at_bad(kb_fjm):
    """The status alphabet is {0x0, 0x8, 0x9}. Anything else means the program is not reading a
    keyboard -- a piped file, or the wrong --io mode -- and it must halt loudly rather than render
    from garbage. This is also what keeps `bad:` referenced in a build that has no wire, and what
    lets `build_wall_renderer`'s R0 gate keep halting the program with a junk byte."""
    io = FixedIO(bytes([0x71, 0x0A]))                     # 'q' = 0x71: the first status hex is 0x1
    fj.run(kb_fjm, io_device=io, print_time=False, print_termination=False)
    assert io.get_output(allow_incomplete_output=True) == b"!"


def test_the_mirror_is_not_vacuous():
    """R9 — a check whose two sides are both "all zeros" proves nothing. At least one script must
    drive every flag both up and down."""
    seen_high = {name: False for name in KEYS}
    for events in SCRIPTS.values():
        for frame in _expected(events):
            for name, digit in zip(KEYS, frame):
                seen_high[name] |= digit == "1"
    assert all(seen_high.values()), seen_high
    assert any(frame != "0000" for frame in _expected(SCRIPTS["hold w across frames"]))


def test_negative_control_a_wrong_binding_is_caught(kb_fjm):
    """R9 — the differential must FAIL when the mirror and the program disagree. 'q' (0x71) is
    deliberately unbound in the macro; a mirror that bound it would have to be rejected."""
    events = [(0, True, 0x71)]
    assert _run(kb_fjm, events) != _expected(events, {**BINDING, 0x71: "f"})
