"""M7 P1.5 -- the menu's STATE MACHINE and the RESTART BLOCK, in fj, against a plain-Python mirror.

`wall_renderer.menu_state_lines(restart)` is the part of the game tier's menu that decides: the
polls record enter / esc / up / down on their down edges (`kb.poll`), and these lines turn them into
`mode` (menu or world), `menu_scr` (main menu or skill screen), `menu_sel` (the highlighted skill),
and -- on NEW GAME -- the chosen skill's restart block (`restart_lines`): every persisted cell back to
that skill's level start. This runs those EXACT lines in a frame loop on a synthetic level (two
leaves, two runtime things, one door, one flagged thing), driven by the real keyboard device, and
prints the state after every frame. The cells start DIRTY (a moved view, an open door, garbage in
the lists), so a restart that misses a cell shows.

The expectation is an independent Python mirror of docs/gp-skill-menu.md's rules and the device's
contract (one event per poll tic, due when the tic reaches it) -- not a run of the program.

⚠ THE CONTROLS (R9): the up/down moves swapped, and a restart that leaves the lists unzeroed, are
assembled through the same harness and must disagree with the mirror.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj.config import Config
from doomfj.harness import W
from doomfj.wall_renderer import MENU_STATE_DECLS, menu_state_lines, restart_lines

SRC = [Path("src/fj") / "input.fj", Path("src/fj") / "m1_reset.fj"]
POLLS, FRAMES = 4, 8
ENTER, ESC, UP, DOWN, W_KEY, S_KEY = 0x0D, 0x1B, 0x80, 0x81, 0x77, 0x73

# the synthetic level: the spawn, one door, two runtime things on two leaves, one flagged thing
SPAWN = type("Spawn", (), {"x": 100 << 16, "y": 200 << 16, "angle": 0x40000000})()
BINDS, POS = [1, 0], [0x0005000600070008, 0x0001000200030004]
PER_SKILL = [([2, 0], [0, 0], [1]),        # easy: thing 1 on leaf 0; the flag shown
             ([0, 1], [0, 0], [0]),        # medium: thing 0 on leaf 1; the flag hidden
             ([2, 1], [0, 0], [1])]        # hard: both
DIRTY = {"viewx": 0x12345678, "dstate": 3, "sshead": [3, 3], "thnext": [2, 1], "thvis": 0}
START = {"viewx": SPAWN.x, "dstate": 0}


def _dump():
    """print: mode, menu_scr, menu_sel, viewx (8 digits), dstate, sshead[0..1], thnext[0..1], thvis"""
    out = ["    hex.print_as_digit 1, mode, 0", "    hex.print_as_digit 1, menu_scr, 0",
           "    hex.print_as_digit 1, menu_sel, 0", "    stl.output_char 32",
           "    hex.print_as_digit 8, viewx, 0", "    stl.output_char 32",
           "    hex.print_as_digit 1, dstate, 0", "    stl.output_char 32"]
    for label in ("sshead", "thnext"):
        for i in range(2):
            out += [f"    hex.set w/4, tm_base, {label}", f"    hex.set w/4, tm_idx, {i}",
                    "    hex.ptr_index tm_p, tm_base, tm_idx", "    hex.read_byte tm_v, tm_p",
                    "    hex.print_as_digit 2, tm_v, 0"]
        out.append("    stl.output_char 32")
    return out + ["    hex.print_as_digit 1, thvis, 0", "    stl.output 10"]


def _program(state_lines, common):
    return "\n".join([
        "stl.startup_and_init_all",
        "tm_frame:",
        "    hex.zero 1, ev_enter", "    hex.zero 1, ev_esc", "    hex.zero 1, ev_up",
        "    hex.zero 1, ev_dn",
        f"    rep({POLLS}, i) kb.poll kstat, kcode, kb_f, kb_b, kb_l, kb_r, kb_u, "
        "ev_enter, ev_esc, ev_up, ev_dn, bad",
        *state_lines,
        *_dump(),
        "    hex.inc 2, tm_count",
        "    hex.cmp 2, tm_count, tm_frames, tm_frame, tm_done, tm_done",
        "tm_done:", "    stl.loop",
        "bad:", "    stl.output_char 0x21", "    stl.loop",
        *common,                                        # fcall'd only
        "mode: hex.vec 1, 1", *MENU_STATE_DECLS,
        "kstat: hex.vec 1", "kcode: hex.vec 2", "kb_f: hex.vec 1", "kb_b: hex.vec 1",
        "kb_l: hex.vec 1", "kb_r: hex.vec 1", "kb_u: hex.vec 1",
        f"tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {FRAMES}",
        "tm_base: hex.vec w/4", "tm_idx: hex.vec w/4", "tm_p: hex.vec w/4", "tm_v: hex.vec 2",
        f"viewx: hex.vec 8, {DIRTY['viewx']}", "viewy: hex.vec 8", "viewangle: hex.vec 8",
        f"dstate: hex.vec 1, {DIRTY['dstate']}", "ddir: hex.vec 1, 2", "dsub: hex.vec 1, 5",
        "dwait: hex.vec 2, 9",
        "thss_rt:", "    hex.vec 16, 9", "    hex.vec 16, 9",
        "thpos_rt:", "    hex.vec 16", "    hex.vec 16",
        "sshead:", *[f";{v} * dw" for v in DIRTY["sshead"]],
        "thnext:", *[f";{v} * dw" for v in DIRTY["thnext"]],
        "thvis:", f"    hex.vec 2, {DIRTY['thvis']}",
    ]) + "\n"


def _assemble(tmp, name, state_lines, common):
    src = tmp / f"{name}.fj"
    src.write_text(_program(state_lines, common), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / f"{name}.fjm"
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out,
                memory_width=W, print_time=False)
    return out


def _run(fjm, events):
    io = KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")[:FRAMES]


def _fmt(st):
    return "%d%d%d %08x %x %02x%02x %02x%02x %x" % (
        st["mode"], st["scr"], st["sel"], st["viewx"], st["dstate"], *st["sshead"], *st["thnext"],
        st["thvis"])


def _expected(events):
    """docs/gp-skill-menu.md's rules in plain Python, frame by frame"""
    pending = sorted((KeyEvent(*e) for e in events), key=lambda e: e.tic)
    st = {"mode": 1, "scr": 0, "sel": 2, "viewx": DIRTY["viewx"], "dstate": DIRTY["dstate"],
          "sshead": list(DIRTY["sshead"]), "thnext": list(DIRTY["thnext"]), "thvis": DIRTY["thvis"]}
    out, index = [], 0
    for frame in range(FRAMES):
        ev = set()
        for tic in range(frame * POLLS, (frame + 1) * POLLS):
            if index < len(pending) and pending[index].tic <= tic:
                e = pending[index]
                index += 1
                if e.is_down:
                    ev.add({ENTER: "enter", ESC: "esc", UP: "up", W_KEY: "up", DOWN: "dn",
                            S_KEY: "dn"}.get(e.keycode, "other"))
        if st["mode"] == 0:
            if "esc" in ev or "enter" in ev:
                st["mode"], st["scr"] = 1, 0
        elif st["scr"] == 0:
            if "esc" in ev:
                st["mode"] = 0
            elif "enter" in ev:
                st["scr"] = 1
        else:
            if "esc" in ev:
                st["scr"] = 0
            elif "enter" in ev:
                head, nxt, vis = PER_SKILL[st["sel"]]
                st.update(viewx=START["viewx"], dstate=START["dstate"], sshead=list(head),
                          thnext=list(nxt), thvis=vis[0], mode=0, scr=0)
            elif "up" in ev:
                st["sel"] = max(0, st["sel"] - 1)
            elif "dn" in ev:
                st["sel"] = min(2, st["sel"] + 1)
        out.append(_fmt(st))
    return out


SCRIPTS = {
    "idle: the menu, hard highlighted, nothing reset": [],
    "esc resumes the world at boot": [(0, True, ESC), (1, False, ESC)],
    "new game at hard (enter, enter)": [(0, True, ENTER), (1, False, ENTER), (5, True, ENTER),
                                        (6, False, ENTER)],
    "down clamps at hard; up twice to easy; new game at easy": [
        (0, True, ENTER), (1, False, ENTER), (4, True, DOWN), (5, False, DOWN),
        (8, True, UP), (9, False, UP), (12, True, W_KEY), (13, False, W_KEY),
        (16, True, W_KEY), (17, False, W_KEY), (20, True, ENTER), (21, False, ENTER)],
    "medium, back out, in again, medium kept": [
        (0, True, ENTER), (1, False, ENTER), (4, True, UP), (5, False, UP),
        (8, True, ESC), (9, False, ESC), (12, True, ENTER), (13, False, ENTER),
        (16, True, ENTER), (17, False, ENTER)],
    "in the world, enter opens the main menu; esc resumes": [
        (0, True, ESC), (1, False, ESC), (4, True, ENTER), (5, False, ENTER),
        (8, True, ESC), (9, False, ESC)],
    "two events in one frame: esc wins over enter": [
        (0, True, ENTER), (1, False, ENTER), (4, True, ESC), (5, True, ENTER), (6, False, ESC),
        (7, False, ENTER)],
}


def _restart():
    return restart_lines(SPAWN, 1, BINDS, POS, 2, PER_SKILL)


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("skillmenu")
    common, _ = _restart()
    return _assemble(tmp, "menu", menu_state_lines(_restart()), common)


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_menu_follows_the_rules(shipped, name):
    got, want = _run(shipped, SCRIPTS[name]), _expected(SCRIPTS[name])
    assert got == want, "%s:\n  fj   %s\n  want %s" % (name, got, want)


def test_the_scripts_reach_every_skill_and_every_screen():
    finals = {_expected(SCRIPTS[n])[-1] for n in SCRIPTS}
    starts = {tuple(PER_SKILL[k][0]) for k in range(3)}
    seen = {tuple(int(f.split()[3][i:i + 2], 16) for i in (0, 2)) for f in finals}
    assert starts <= seen, "a skill's level start is never reached: %s" % (starts - seen)


def test_a_broken_menu_is_caught(tmp_path):
    """R9: the same harness must say no to swapped moves and to a restart that does not zero"""
    common, _ = _restart()
    lines = menu_state_lines(_restart())
    swapped = [l.replace("hex.dec 1, menu_sel", "@@").replace("hex.inc 1, menu_sel", "hex.dec 1, menu_sel")
               .replace("@@", "hex.inc 1, menu_sel") for l in lines]
    assert swapped != lines
    bad = _assemble(tmp_path, "swapped", swapped, common)
    name = "down clamps at hard; up twice to easy; new game at easy"
    assert _run(bad, SCRIPTS[name]) != _expected(SCRIPTS[name]), "swapped moves passed"
    nozero = [l for l in common if "m1.zerobyte sshead" not in l]
    assert nozero != common
    bad2 = _assemble(tmp_path, "nozero", lines, nozero)
    name = "new game at hard (enter, enter)"
    assert _run(bad2, SCRIPTS[name]) != _expected(SCRIPTS[name]), "an unzeroed restart passed"
