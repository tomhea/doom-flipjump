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

M7 P1.5: the poll no longer toggles the menu's `mode`; it records the menu's EVENTS -- enter, esc,
and the down edges of forward and back as up / down -- which the caller zeroes before a frame's
polls. The printed line is the four held flags, then the four events of that frame.

M7 P3.4: 'e' is a second USE key (space's held flag) and 'h' the HELP event (docs/gp-help.md); the
line now prints the use flag after the four and the help event after the four events. And the help
screen lists ONLY keys that work: every key it names must do something here, and every key this
macro binds must be on it (`test_the_help_screen_lists_exactly_the_keys_that_work`).
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import HELP_KEYCODES, MENU_KEYS, help_key_names

SRC = [Path("src/fj") / "input.fj"]
CFG = Config()

POLLS = 8          # polls per "frame", the same unroll the emitter uses
FRAMES = 6
KEYS = ("f", "b", "l", "r", "u")    # M7 P3.4: the use flag printed too
EVENTS = ("E", "X", "U", "D", "H")  # the menu's events: enter, esc, up (forward), down (back), help

# keycode -> which flag, mirroring the macro's own comment table. M7 P3.4: space and 'e' are USE.
BINDING = {0x77: "f", 0x80: "f", 0x73: "b", 0x81: "b",
           0x61: "l", 0x82: "l", 0x64: "r", 0x83: "r", 0x20: "u", 0x65: "u"}
# keycode -> the event its DOWN edge records (enter, esc, and M7 P3.4's help)
EVENT_KEYS = {0x0D: "E", 0x1B: "X", 0x68: "H"}


def _program() -> str:
    lines = ["stl.startup_and_init_all"]
    for _ in range(FRAMES):
        lines += [f"hex.zero 1, {e}" for e in ("kent", "kesc", "kup", "kdn", "khelp")]
        lines.append(f"rep({POLLS}, i) kb.poll kstat, kcode, kfwd, kback, kleft, kright, kuse, "
                     "kent, kesc, kup, kdn, khelp, bad")
        lines += [f"hex.print_as_digit k{name}, 0" for name in
                  ("fwd", "back", "left", "right", "use", "ent", "esc", "up", "dn", "help")]
        lines.append("stl.output 10")
    lines += ["stl.loop",
              # the halt a non-keyboard input stream gets -- '!' so a rejected run is visible
              "bad:", "stl.output_char 0x21", "stl.loop",
              "kstat: hex.vec 1", "kcode: hex.vec 2",
              "kent: hex.vec 1", "kesc: hex.vec 1", "kup: hex.vec 1", "kdn: hex.vec 1",
              "khelp: hex.vec 1",                     # M7 P3.4
              "kfwd: hex.vec 1", "kback: hex.vec 1", "kleft: hex.vec 1", "kright: hex.vec 1",
              # M2-R4: the USE key (space, 0x20) is a held flag like the four above
              "kuse: hex.vec 1"]
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


def _expected(events, binding=None, event_keys=None) -> list:
    """the same thing in plain python, from the DEVICE's contract: at most one event per tic, due
    once the tic clock reaches it; the program prints its flags after every POLLS polls."""
    binding = BINDING if binding is None else binding
    event_keys = EVENT_KEYS if event_keys is None else event_keys
    pending = sorted((KeyEvent(*e) for e in events), key=lambda e: e.tic)
    held = {name: 0 for name in KEYS}
    ev = {name: 0 for name in EVENTS}
    out, index = [], 0
    for tic in range(FRAMES * POLLS):
        if tic % POLLS == 0:
            ev = {name: 0 for name in EVENTS}      # zeroed before each frame's polls
        if index < len(pending) and pending[index].tic <= tic:
            event = pending[index]
            index += 1
            if event.keycode in event_keys:        # enter / esc / help: events, DOWN edge only
                if event.is_down:
                    ev[event_keys[event.keycode]] = 1
            else:
                name = binding.get(event.keycode)
                if name is not None:
                    held[name] = 1 if event.is_down else 0
                    if event.is_down and name in ("f", "b"):   # forward / back are up / down too
                        ev["U" if name == "f" else "D"] = 1
        if tic % POLLS == POLLS - 1:
            out.append("".join(str(held[name]) for name in KEYS)
                       + "".join(str(ev[name]) for name in EVENTS))
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
    # M3 / M7 P1.5: the menu's events. Enter and esc are recorded on the DOWN edge only -- acting
    # on both edges would act twice -- and only in the frame whose polls saw them.
    "enter is an event on its down edge only": [(0, True, 0x0D), (1, False, 0x0D)],
    "enter twice, two frames' events": [(0, True, 0x0D), (1, False, 0x0D),
                                        (8, True, 0x0D), (9, False, 0x0D)],
    "esc is its own event": [(0, True, 0x1B), (1, False, 0x1B)],
    # ... and an event is a FLAG, so a press and release inside ONE frame cannot tell the down edge
    # from the up edge: acting on both, or only on the up, sets the same flag. These hold the key
    # ACROSS a frame boundary -- down in one frame, up in the next -- and the second frame must have
    # no event (the P1.5 review: no script did this).
    "enter held across frames: no event on its up edge": [(0, True, 0x0D), (9, False, 0x0D)],
    "esc held across frames: no event on its up edge": [(0, True, 0x1B), (9, False, 0x1B)],
    "the menu's events do not disturb the keys": [(0, True, 0x77), (1, True, 0x0D),
                                                  (2, False, 0x0D), (16, False, 0x77)],
    "forward and back are the menu's up and down": [(0, True, 0x80), (1, False, 0x80),
                                                    (9, True, 0x73), (10, False, 0x73)],
    # M7 P3.4: 'e' is a second use key -- the SAME held flag as space -- and 'h' the help event
    "space holds use": [(0, True, 0x20), (12, False, 0x20)],
    "e holds use like space": [(0, True, 0x65), (12, False, 0x65)],
    "space and e share one flag": [(0, True, 0x20), (9, False, 0x20), (10, True, 0x65),
                                   (20, False, 0x65)],
    "h is an event on its down edge only": [(0, True, 0x68), (1, False, 0x68)],
    "h held across frames: no event on its up edge": [(0, True, 0x68), (9, False, 0x68)],
    "h does not disturb the held keys": [(0, True, 0x77), (1, True, 0x68), (2, False, 0x68),
                                         (3, True, 0x65), (16, False, 0x77), (17, False, 0x65)],
    # the 0x6_ row's other keys are NOT bound: 'b' 'c' 'f' 'g' 'i' between a, d, e and h, read
    # and discarded -- and the stream stays in phase after them
    "the 0x6_ row's unbound keys are discarded": [(0, True, 0x62), (1, True, 0x66), (2, True, 0x67),
                                                  (3, True, 0x69), (4, True, 0x63), (5, True, 0x68),
                                                  (6, True, 0x61), (9, False, 0x61)],
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
    seen_high = {name: False for name in KEYS + EVENTS}
    for events in SCRIPTS.values():
        for frame in _expected(events):
            for name, digit in zip(KEYS + EVENTS, frame):
                seen_high[name] |= digit == "1"
    assert all(seen_high.values()), seen_high
    assert any(frame != "0" * len(KEYS + EVENTS)
               for frame in _expected(SCRIPTS["hold w across frames"]))


def test_the_up_edge_scripts_straddle_a_frame():
    """R9 for the two held-across-frames scripts: the key must go down in one frame and up in the
    NEXT, with the event in the first frame only -- a pair inside one frame could not tell a poll
    that acts on the up edge from one that acts on the down edge."""
    for name, event in (("enter held across frames: no event on its up edge", "E"),
                        ("esc held across frames: no event on its up edge", "X"),
                        ("h held across frames: no event on its up edge", "H")):
        slot = len(KEYS) + EVENTS.index(event)          # the digit that event prints in
        (t0, down0, _), (t1, down1, _) = SCRIPTS[name]
        assert down0 and not down1 and t1 // POLLS == t0 // POLLS + 1, name
        frames = _expected(SCRIPTS[name])
        assert (frames[0][slot], frames[1][slot]) == ("1", "0"), (name, frames[:2])


def test_negative_control_a_wrong_binding_is_caught(kb_fjm):
    """R9 — the differential must FAIL when the mirror and the program disagree. 'q' (0x71) is
    deliberately unbound in the macro; a mirror that bound it would have to be rejected."""
    events = [(0, True, 0x71)]
    assert _run(kb_fjm, events) != _expected(events, {**BINDING, 0x71: "f"})


def test_negative_control_the_new_keys_are_caught(kb_fjm):
    """R9 (M7 P3.4): a mirror without 'e' as use, or without 'h' as help, must be rejected"""
    for script in ("e holds use like space", "h is an event on its down edge only"):
        events = SCRIPTS[script]
        assert _run(kb_fjm, events) == _expected(events)
        no_e = {k: v for k, v in BINDING.items() if k != 0x65}
        no_h = {k: v for k, v in EVENT_KEYS.items() if k != 0x68}
        assert _run(kb_fjm, events) != _expected(events, no_e, no_h), script


def _does_something(kb_fjm, code) -> bool:
    """the key, pressed, sets a held flag or records an event in kb.poll (the RUN program)"""
    return _run(kb_fjm, [(0, True, code)])[0] != "0" * len(KEYS + EVENTS)


def test_the_help_screen_lists_exactly_the_keys_that_work(kb_fjm):
    """M7 P3.4 (the owner: list ONLY the keys that work today). Every key the help screen draws a
    cap for (`menu.help_key_names`) has a keycode (`menu.HELP_KEYCODES`), and kb.poll -- RUN, not
    read -- does something on each; and every keycode the macro binds (the held flags and the
    events) is named on the screen. R9: an unbound key ('q', and 'g' in the 0x6_ row) does nothing,
    so `_does_something` can say no."""
    named = help_key_names()
    assert sorted(named) == sorted(HELP_KEYCODES), (sorted(named), sorted(HELP_KEYCODES))
    dead = [n for n in named if not _does_something(kb_fjm, HELP_KEYCODES[n])]
    assert not dead, "the help screen names keys kb.poll ignores: %r" % dead
    bound = set(BINDING) | set(EVENT_KEYS)
    assert bound == set(HELP_KEYCODES.values()), sorted(bound ^ set(HELP_KEYCODES.values()))
    assert set(MENU_KEYS) <= bound, "a menu key the poll does not bind"
    assert not _does_something(kb_fjm, 0x71) and not _does_something(kb_fjm, 0x67)
