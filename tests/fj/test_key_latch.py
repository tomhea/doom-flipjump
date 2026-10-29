"""P9 -- THE PRESS LATCH, run: the game tier's input prologue (`wall_renderer.standalone_key_lines`, the EXACT emitted
lines -- the menu events and `kb_now` zeroed, STANDALONE_POLLS polls of the real keyboard device, `kb_now` OR-ed with
the held flags, the key byte `pkeys` built from `kb_now`) against the oracle, `doomfj.keyboard.frame_keys`.

The owner's play-test (2026-10-10): "a key pressed since the last input check must count". A tap whose down AND up
both land inside one frame's polls used to leave every held flag where it was -- the frame fired nothing, switched
to nothing, used nothing. Now the frame acts on held-after-the-polls OR pressed-during-them, for every held key;
a release with no press in its frame still takes effect that frame.

Per frame the harness prints the key byte (what the sim, the doors, the exit, the restart and the FIRE read), the
twelve `kb_now` digits (the number keys' four are what the weapon's keys read: weaponcode reads
`keyboard.now_cell('w1'..'w3')`, test_wall_renderer_helpers holds that), and the twelve held flags (persisted).

R9: the pre-P9 oracle (no latch), and the prologue with each of its three P9 parts broken -- the builder reading the
held flags again, the OR dropped, the latch never re-zeroed -- must each disagree with the mirror on some script.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj import keyboard as KB
from doomfj.harness import W
from doomfj.automap import has_page
from doomfj.wall_renderer import STANDALONE_POLLS, standalone_key_lines
from doomfj.wireformat import KEY_FIRE, KEY_USE, keys_byte

SRC = [Path("src/fj") / "input.fj"]
POLLS, FRAMES = STANDALONE_POLLS, 6
FIRE, W2, USE, FWD, LEFT = KB.KC_LCTRL, 0x32, 0x20, 0x77, KB.KC_LEFT


def _program(key_lines) -> str:
    return "\n".join([
        "stl.startup_and_init_all",
        "tm_frame:",
        *key_lines,
        "    hex.print_as_digit 2, pkeys, 0", "    stl.output_char 32",
        *[f"    hex.print_as_digit 1, {KB.now_cell(k)}, 0" for k in KB.HELD_KEYS], "    stl.output_char 32",
        *[f"    hex.print_as_digit 1, {KB.flag(k)}, 0" for k in KB.HELD_KEYS],
        "    stl.output 10",
        "    hex.inc 2, tm_count",
        "    hex.cmp 2, tm_count, tm_frames, tm_frame, tm_done, tm_done",
        "tm_done:", "    stl.loop",
        "bad:", "    stl.output_char 0x21", "    stl.loop",
        "kbstat: hex.vec 1", "kbcode: hex.vec 2", "pkeys: hex.vec 2",
        *[f"{KB.flag(k)}: hex.vec 1" for k in KB.HELD_KEYS],
        KB.NOW_DECL,
        *[f"{e}: hex.vec 1" for e in ("ev_enter", "ev_esc", "ev_up", "ev_dn", "ev_help", "ev_any")],   # P10: ev_any
        "ev_map: hex.vec 1",                                                # M8: the map page's M (AUTOMAP)
        "tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {FRAMES}",
    ]) + "\n"


def _assemble(tmp, name, key_lines):
    src = tmp / f"{name}.fj"
    src.write_text(_program(key_lines), encoding="utf-8")
    out = tmp / f"{name}.fjm"
    fj.assemble([*[p.resolve() for p in SRC], src.resolve()], out, memory_width=W, print_time=False)
    return out


def _run(fjm, events) -> list:
    io = KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")[:FRAMES]


def _expected(events, latch=True) -> list:
    """the oracle's frames, printed as the harness prints them"""
    out = []
    for fk in KB.frame_keys(events, FRAMES, polls=POLLS, latch=latch):
        out.append("%02x %s %s" % (keys_byte(KB.named(fk.now)),
                                   "".join(str(int(fk.now[k])) for k in KB.HELD_KEYS),
                                   "".join(str(int(fk.held[k])) for k in KB.HELD_KEYS)))
    return out


def tap(frame, code, at=0):
    """a down and an up inside frame `frame`'s polls (at its poll `at` and the next)"""
    return [(frame * POLLS + at, True, code), (frame * POLLS + at + 1, False, code)]


SCRIPTS = {
    "nothing": [],
    # THE OWNER'S CASE: a tap inside one frame -- fire for that frame, and only that one
    "fire tapped inside one frame fires that frame": tap(1, FIRE),
    "weapon 2 tapped inside one frame switches that frame": tap(2, W2, at=3),
    "use tapped inside one frame uses that frame": tap(1, USE, at=6),
    "fire and weapon 2 tapped in the same frame": tap(1, FIRE) + tap(1, W2, at=2),
    "fire tapped twice inside one frame: one frame": tap(1, FIRE) + tap(1, FIRE, at=4),
    # a release takes effect on the frame it lands in, when that frame has no press
    "forward held two frames, released in the third": [(0, True, FWD), (2 * POLLS + 3, False, FWD)],
    "held from before, released and pressed again in one frame: held": [(0, True, LEFT), (POLLS, False, LEFT),
                                                                         (POLLS + 1, True, LEFT),
                                                                         (3 * POLLS, False, LEFT)],
    "fire held across frames": [(0, True, FIRE), (3 * POLLS + 2, False, FIRE)],
    "pressed in one frame, released in the next: both frames": [(POLLS + 6, True, W2), (2 * POLLS + 1, False, W2)],
    # the device delivers one event per poll: a burst spills, and the latch follows the poll that saw the down
    "a tap pushed into the next frame by a burst latches there": (
        [(0, True, c) for c in (0x61, 0x64, 0x2C, 0x2E, 0x65, 0x31, 0x33, 0x34)] + tap(0, FIRE)),
    # every keycode the oracle binds, tapped in turn (one event a poll: four taps a frame) -- the oracle's BINDING is
    # the poll's table, key by key, or this differs
    "every bound key tapped once": [(2 * k + (not d), d, c)
                                    for k, c in enumerate(sorted(KB.BINDING)) for d in (True, False)],
}
TAPS = ("fire tapped inside one frame fires that frame", "weapon 2 tapped inside one frame switches that frame",
        "use tapped inside one frame uses that frame", "fire and weapon 2 tapped in the same frame",
        "fire tapped twice inside one frame: one frame")
HOLDS = ("forward held two frames, released in the third", "fire held across frames")


# M8 (the owner, 2026-10-18: "Add it to e1m1 too"): E1M1's prologue reads M after each poll (the map page) -- the
# latch must be exactly what it was with those lines between the polls
AUTOMAP = has_page("E1M1")


def _shipped_lines():
    return standalone_key_lines(POLLS, automap=AUTOMAP)


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    return _assemble(tmp_path_factory.mktemp("latch"), "latch", _shipped_lines())


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_frame_acts_on_held_or_pressed(shipped, name):
    """THE test: the emitted prologue, run, is the oracle -- the key byte, the latch, the held flags, every frame"""
    got, want = _run(shipped, SCRIPTS[name]), _expected(SCRIPTS[name])
    assert got == want, (name, got, want)


def test_a_tap_counts_for_exactly_its_frame(shipped):
    """the owner's case, spelled out on the RUN program: a fire tap inside frame 1 sets the key byte's fire bit on
    frame 1 alone, with the fire flag 0 on every frame; a weapon-2 tap inside frame 2 sets `kb_now`'s w2 nibble (what
    the weapon's keys read) on frame 2 alone"""
    fire = _run(shipped, SCRIPTS["fire tapped inside one frame fires that frame"])
    assert [int(ln.split()[0], 16) & KEY_FIRE for ln in fire] == [0, KEY_FIRE, 0, 0, 0, 0], fire
    assert {ln.split()[2][KB.HELD_KEYS.index("fi")] for ln in fire} == {"0"}
    w2 = _run(shipped, SCRIPTS["weapon 2 tapped inside one frame switches that frame"])
    assert [ln.split()[1][KB.HELD_KEYS.index("w2")] for ln in w2] == ["0", "0", "1", "0", "0", "0"], w2
    use = _run(shipped, SCRIPTS["use tapped inside one frame uses that frame"])
    assert [int(ln.split()[0], 16) & KEY_USE for ln in use] == [0, KEY_USE, 0, 0, 0, 0], use


def test_the_scripts_are_not_vacuous():
    """R9: the tap scripts differ from the pre-P9 rule (that is what they are FOR), the hold scripts do not (the latch
    adds nothing to a held key), and the burst script's tap lands in frame 1"""
    for name in TAPS:
        assert _expected(SCRIPTS[name]) != _expected(SCRIPTS[name], latch=False), name
    for name in HOLDS:
        assert _expected(SCRIPTS[name]) == _expected(SCRIPTS[name], latch=False), name
    burst = _expected(SCRIPTS["a tap pushed into the next frame by a burst latches there"])
    assert [int(ln[:2], 16) & KEY_FIRE for ln in burst[:3]] == [0, KEY_FIRE, 0], burst


def test_negative_control_the_pre_p9_oracle_is_caught(shipped):
    """R9: the oracle without the latch (now = held) disagrees with the program on every tap script"""
    for name in TAPS:
        assert _run(shipped, SCRIPTS[name]) != _expected(SCRIPTS[name], latch=False), name


def _mutants():
    lines = _shipped_lines()

    def on_flags(ln):                    # the builder's `if0 1, kb_now + i*dw` back on the held flag
        for k in KB.HELD_KEYS:
            if ln.startswith("hex.if0 1, %s," % KB.now_cell(k)):
                return ln.replace(KB.now_cell(k), KB.flag(k))
        return ln
    builder_on_flags = [on_flags(ln) for ln in lines]
    nor = KB.now_lines()
    no_or = lines[:lines.index(nor[0])] + lines[lines.index(nor[-1]) + 1:]
    zero = f"hex.zero {len(KB.HELD_KEYS)}, {KB.KEY_NOW}"
    no_zero = [ln for ln in lines if ln != zero]
    return {"the key byte built from the held flags (pre-P9)": (builder_on_flags, TAPS),
            "the OR with the held flags dropped": (no_or, HOLDS),
            "the latch never re-zeroed": (no_zero, TAPS)}


@pytest.mark.parametrize("name", sorted(_mutants()))
def test_a_broken_prologue_is_caught(tmp_path, name):
    """R9: each P9 part of the prologue broken, assembled through the same harness, disagrees with the oracle on some
    script of the kind it breaks"""
    lines, scripts = _mutants()[name]
    assert lines != _shipped_lines(), "the mutant changed nothing"
    bad = _assemble(tmp_path, "bad", lines)
    caught = [n for n in scripts if _run(bad, SCRIPTS[n]) != _expected(SCRIPTS[n])]
    assert caught, "a prologue where %s passed every script" % name
