"""M7 P1.5 -- the menu's STATE MACHINE and the RESTART BLOCK, in fj, against a plain-Python mirror.

`wall_renderer.menu_state_lines(restart)` is the part of the game tier's menu that decides: the
polls record enter / esc / up / down on their down edges (`kb.poll`), and these lines turn them into
`mode` (menu or world), `menu_scr` (main menu or skill screen), `menu_sel` (the highlighted skill),
and -- on NEW GAME -- the chosen skill's restart block (`restart_lines`): every persisted cell back to
that skill's level start. This runs those EXACT lines in a frame loop on a synthetic level (two
leaves, three runtime things, two doors, two flagged things), driven by the real keyboard device,
and prints after every frame EVERY cell the restart block writes: the view (x, y, angle), every door
cell, every runtime thing's binding and position, every list byte and every flag. The cells start
DIRTY -- each at a value no level start holds -- so a restart that misses one shows.

The expectation is the Python side of docs/gp-skill-menu.md's rules, `doomfj.menu.menu_step` (the
mirror every gate that drives the game binary through its menu steps), and the device's contract
(one event per poll tic, due when the tic reaches it) -- not a run of the program.

⚠ THE CONTROLS (R9): the up/down moves swapped, and the restart block with each group of its writes
dropped in turn (the list zeroing, the doors, the positions, the bindings, the view's y and angle,
the per-skill links, the flags), are assembled through the same harness and must each disagree with
the mirror on some script. Until the P1.5 review this printed only viewx, dstate, two list bytes a
side and one flag, and no skill linked two things -- so a restart that missed viewy, viewangle, the
other door cells, the bindings, the positions or a link passed, and only the list zeroing had a
control.
"""
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.KeyboardIO import KeyboardIO, KeyEvent, ScriptedKeyEventSource

from doomfj.config import Config
from doomfj.doorcode import WAIT_NIBBLES
from doomfj.harness import W
from doomfj.menu import LEVEL_DONE_SCR, MENU_KEYS, menu_step
from doomfj.things import spawn_leaf_lists
from doomfj.wall_renderer import (BOOT_SKILL, MENU_STATE_DECLS, SKILLS, menu_state_lines,
                                  restart_lines)

SRC = [Path("src/fj") / "input.fj", Path("src/fj") / "m1_reset.fj"]
POLLS, FRAMES = 4, 8
ENTER, ESC, UP, DOWN, W_KEY, S_KEY = 0x0D, 0x1B, 0x80, 0x81, 0x77, 0x73
M32 = 0xFFFFFFFF

# the synthetic level: the spawn (a NEGATIVE y, so the 32-bit wrap is checked), two doors, three
# runtime things on two leaves, two flagged (baked vanishable) things
SPAWN = type("Spawn", (), {"x": 100 << 16, "y": -(200 << 16), "angle": 0x40000000})()
NDOORS, NSS = 2, 2
BINDS = [0, 1, 0]                                   # each runtime thing's spawn leaf
POS = [0x0005000600070008, 0x0001000200030004, 0xFFF0FFF1FFF2FFF3]
# which runtime things each skill spawns, and each flag, for easy, medium, hard. Things 0 and 2
# share leaf 0, so hard -- which has both -- LINKS them (thnext[0] = 3): a non-zero link, so the
# per-skill blocks' thnext bit flips are generated and run.
PRESENT = ([0, 1, 1], [1, 1, 0], [1, 1, 1])
VIS = ([1, 0], [0, 1], [1, 1])
PER_SKILL = [(*spawn_leaf_lists(BINDS, NSS, present=p), list(v)) for p, v in zip(PRESENT, VIS)]
NT, NVIS = len(BINDS), len(VIS[0])

# EVERY cell the restart block writes, in the order the dump prints it: (label, nibbles, count);
# element i sits at `label + i*nibbles*dw`. The byte arrays are read through a pointer.
HEX_TARGETS = [("viewx", 8, 1), ("viewy", 8, 1), ("viewangle", 8, 1),
               ("dstate", NDOORS, 1), ("ddir", NDOORS, 1), ("dsub", NDOORS, 1),
               ("dwait", WAIT_NIBBLES * NDOORS, 1),
               ("thss_rt", 16, NT), ("thpos_rt", 16, NT), ("thvis", 2, NVIS),
               # M7 P2a.1's door cells and P2a.2's exit cells (restart_lines' nwalk=1: one W1 bit)
               ("dreq", NDOORS, 1), ("pcard", 1, 1), ("wfired", 1, 1), ("lvdone", 1, 1),
               ("pusedn", 1, 1)]
BYTE_TARGETS = [("sshead", NSS), ("thnext", NT)]
FIELDS = "msv " + " ".join([f"{lb}[{i}]" for lb, _n, c in HEX_TARGETS for i in range(c)]
                           + [f"{lb}[{i}]" for lb, c in BYTE_TARGETS for i in range(c)])

# the cells start DIRTY: each at a value no skill's level start holds
DIRTY = {"viewx": [0x12345678], "viewy": [0x0BADF00D], "viewangle": [0x76543210],
         "dstate": [0x33], "ddir": [0x21], "dsub": [0x55], "dwait": [0x9A9A],
         "thss_rt": [0x9999, 0x8888, 0x7777], "thpos_rt": [0x1111, 0x2222, 0x3333],
         "thvis": [0x5A, 0xA5], "sshead": [0xA5, 0x5A], "thnext": [0x77, 0x66, 0x55],
         "dreq": [0x11], "pcard": [1], "wfired": [1], "lvdone": [1], "pusedn": [0]}
# the menu's own declarations less the exit's two cells, which the harness declares DIRTY
MENU_DECLS_CLEAN = [d for d in MENU_STATE_DECLS if not d.startswith(("lvdone:", "pusedn:"))]


def level_start(k) -> dict:
    """skill k's level start: the value of every restart target"""
    head, nxt, vis = PER_SKILL[k]
    return {"viewx": [SPAWN.x & M32], "viewy": [SPAWN.y & M32], "viewangle": [SPAWN.angle & M32],
            "dstate": [0], "ddir": [0], "dsub": [0], "dwait": [0],
            "thss_rt": list(BINDS), "thpos_rt": list(POS), "thvis": list(vis),
            "sshead": list(head), "thnext": list(nxt),
            "dreq": [0], "pcard": [0], "wfired": [0], "lvdone": [0], "pusedn": [1]}


def _dump():
    """print: mode menu_scr menu_sel, then every HEX_TARGETS element and every BYTE_TARGETS byte,
    space-separated -- `_fmt` is the same line"""
    out = ["    hex.print_as_digit 1, mode, 0", "    hex.print_as_digit 1, menu_scr, 0",
           "    hex.print_as_digit 1, menu_sel, 0"]
    for label, n, count in HEX_TARGETS:
        for i in range(count):
            out += ["    stl.output_char 32", f"    hex.print_as_digit {n}, {label} + {i * n}*dw, 0"]
    for label, count in BYTE_TARGETS:
        for i in range(count):
            out += ["    stl.output_char 32",
                    f"    hex.set w/4, tm_base, {label}", f"    hex.set w/4, tm_idx, {i}",
                    "    hex.ptr_index tm_p, tm_base, tm_idx", "    hex.read_byte tm_v, tm_p",
                    "    hex.print_as_digit 2, tm_v, 0"]
    return out + ["    stl.output 10"]


def _fmt(st) -> str:
    return " ".join(["%d%d%d" % (st["mode"], st["scr"], st["sel"])]
                    + ["%0*x" % (n, v) for label, n, _c in HEX_TARGETS for v in st[label]]
                    + ["%02x" % v for label, _c in BYTE_TARGETS for v in st[label]])


def _program(state_lines, common, scr0=0):
    cells = []
    for label, n, _count in HEX_TARGETS:
        cells += [f"{label}:"] + [f"    hex.vec {n}, {v}" for v in DIRTY[label]]
    for label, _count in BYTE_TARGETS:
        cells += [f"{label}:"] + [f";{v} * dw" for v in DIRTY[label]]
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
        "mode: hex.vec 1, 1",
        *[f"menu_scr: hex.vec 1, {scr0}" if d.startswith("menu_scr:") else d for d in MENU_DECLS_CLEAN],
        "kstat: hex.vec 1", "kcode: hex.vec 2", "kb_f: hex.vec 1", "kb_b: hex.vec 1",
        "kb_l: hex.vec 1", "kb_r: hex.vec 1", "kb_u: hex.vec 1",
        "tm_count: hex.vec 2", f"tm_frames: hex.vec 2, {FRAMES}",
        "tm_base: hex.vec w/4", "tm_idx: hex.vec w/4", "tm_p: hex.vec w/4", "tm_v: hex.vec 2",
        *cells,
    ]) + "\n"


def _assemble(tmp, name, state_lines, common, scr0=0):
    src = tmp / f"{name}.fj"
    src.write_text(_program(state_lines, common, scr0), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp / "fj_consts.fj")
    out = tmp / f"{name}.fjm"
    fj.assemble([consts.resolve(), *[p.resolve() for p in SRC], src.resolve()], out,
                memory_width=W, print_time=False)
    return out


def _run(fjm, events):
    io = KeyboardIO(ScriptedKeyEventSource([KeyEvent(*e) for e in events]))
    fj.run(fjm, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split("\n")[:FRAMES]


def _expected(events, scr0=0):
    """docs/gp-skill-menu.md's rules in plain Python, frame by frame -> (lines, states); `scr0`:
    the screen the program boots on (LEVEL_DONE_SCR: as the exit switch leaves it)"""
    pending = sorted((KeyEvent(*e) for e in events), key=lambda e: e.tic)
    st = {"mode": 1, "scr": scr0, "sel": SKILLS.index(BOOT_SKILL),
          **{label: list(v) for label, v in DIRTY.items()}}
    lines, states, index = [], [], 0
    for frame in range(FRAMES):
        ev = set()
        for tic in range(frame * POLLS, (frame + 1) * POLLS):
            if index < len(pending) and pending[index].tic <= tic:
                e = pending[index]
                index += 1
                if e.is_down and e.keycode in MENU_KEYS:
                    ev.add(MENU_KEYS[e.keycode])
        st["mode"], st["scr"], st["sel"], new_game = menu_step(st["mode"], st["scr"], st["sel"], ev)
        if new_game is not None:                    # the chosen skill's level start
            st.update(level_start(new_game))
        lines.append(_fmt(st))
        states.append({k: list(v) if isinstance(v, list) else v for k, v in st.items()})
    return lines, states


def _first_difference(name, got, want) -> str:
    for f, (g, w) in enumerate(zip(got, want)):
        if g != w:
            return "%s, frame %d:\n  cell %s\n  fj   %s\n  want %s" % (name, f, FIELDS, g, w)
    return "%s: %d frames printed, %d expected" % (name, len(got), len(want))


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
    # the P1.5 review: esc FROM THE WORLD (`mn_world` -> `mn_open`) was reached by no fj test and no
    # gate -- every script above left the world with enter or never entered it
    "in the world, esc opens the main menu": [
        (0, True, ESC), (1, False, ESC), (4, True, ESC), (5, False, ESC)],
    "after a new game, esc opens the main menu, not the skill screen": [
        (0, True, ENTER), (1, False, ENTER), (4, True, ENTER), (5, False, ENTER),
        (8, True, ESC), (9, False, ESC)],
    "two events in one frame: esc wins over enter": [
        (0, True, ENTER), (1, False, ENTER), (4, True, ESC), (5, True, ENTER), (6, False, ESC),
        (7, False, ENTER)],
}


# M7 P2a.2 -- from the LEVEL COMPLETE screen (a program booted on it: the exit switch's state)
LEVEL_DONE_SCRIPTS = {
    "level complete: nothing held stays": [],
    "level complete: up / down do nothing": [(0, True, UP), (1, False, UP), (4, True, DOWN),
                                             (5, False, DOWN)],
    "level complete: enter -> the main menu -> new game at hard": [
        (0, True, ENTER), (1, False, ENTER), (4, True, ENTER), (5, False, ENTER),
        (8, True, ENTER), (9, False, ENTER)],
    "level complete: esc -> the main menu; esc -> the world": [
        (0, True, ESC), (1, False, ESC), (4, True, ESC), (5, False, ESC)],
}


def _restart():
    return restart_lines(SPAWN, NDOORS, BINDS, POS, NSS, PER_SKILL)


@pytest.fixture(scope="module")
def shipped(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("skillmenu")
    common, _ = _restart()
    return _assemble(tmp, "menu", menu_state_lines(_restart()), common)


@pytest.mark.parametrize("name", sorted(SCRIPTS))
def test_the_menu_follows_the_rules(shipped, name):
    got, want = _run(shipped, SCRIPTS[name]), _expected(SCRIPTS[name])[0]
    assert got == want, _first_difference(name, got, want)


@pytest.fixture(scope="module")
def shipped_done(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("leveldone")
    common, _ = _restart()
    return _assemble(tmp, "menu_done", menu_state_lines(_restart()), common, scr0=LEVEL_DONE_SCR)


@pytest.mark.parametrize("name", sorted(LEVEL_DONE_SCRIPTS))
def test_the_level_complete_screen_follows_the_rules(shipped_done, name):
    ev = LEVEL_DONE_SCRIPTS[name]
    got, want = _run(shipped_done, ev), _expected(ev, LEVEL_DONE_SCR)[0]
    assert got == want, _first_difference(name, got, want)


def test_a_level_complete_screen_that_ignores_enter_is_caught(tmp_path):
    """R9: the screen's enter way out dropped must show"""
    common, _ = _restart()
    lines = menu_state_lines(_restart())
    k = lines.index("mn_lv1:")
    assert lines[k + 1] == "hex.if0 1, ev_enter, mn_done"
    bad_lines = lines[:k + 1] + [";mn_done"] + lines[k + 2:]
    bad = _assemble(tmp_path, "lvbad", bad_lines, common, scr0=LEVEL_DONE_SCR)
    name = "level complete: enter -> the main menu -> new game at hard"
    assert _run(bad, LEVEL_DONE_SCRIPTS[name]) != _expected(LEVEL_DONE_SCRIPTS[name], LEVEL_DONE_SCR)[0]


def test_the_scripts_reach_every_skill_and_every_screen():
    """R9 against a vacuous script set: every skill's WHOLE level start is some script's final state
    (reached from the dirty cells), the scripts pass through the world, the main menu and the skill
    screen, and some skill links two things -- or the per-skill link flips would never run"""
    runs = {n: _expected(SCRIPTS[n])[1] for n in SCRIPTS}
    for k in range(len(SKILLS)):
        want = level_start(k)
        assert any(all(r[-1][c] == v for c, v in want.items()) for r in runs.values()), (
            "skill %d's level start is never reached" % k)
    assert {(s["mode"], s["scr"]) for r in runs.values() for s in r} == {(0, 0), (1, 0), (1, 1)}
    done = {n: _expected(LEVEL_DONE_SCRIPTS[n], LEVEL_DONE_SCR)[1] for n in LEVEL_DONE_SCRIPTS}
    assert {(s["mode"], s["scr"]) for r in done.values() for s in r} == {
        (1, LEVEL_DONE_SCR), (1, 0), (1, 1), (0, 0)}
    assert any(any(nxt) for _head, nxt, _vis in PER_SKILL)
    assert any("thnext +" in ln for block in _restart()[1] for ln in block)
    # ... and esc from the world is taken: a frame in the world, then the main menu on esc
    for n in ("in the world, esc opens the main menu",
              "after a new game, esc opens the main menu, not the skill screen"):
        modes = [(s["mode"], s["scr"]) for s in runs[n]]
        assert (0, 0) in modes and modes[-1] == (1, 0), (n, modes)


def test_a_broken_menu_is_caught(tmp_path):
    """R9: the same harness must say no to swapped up / down moves"""
    common, _ = _restart()
    lines = menu_state_lines(_restart())
    swapped = [l.replace("hex.dec 1, menu_sel", "@@").replace("hex.inc 1, menu_sel", "hex.dec 1, menu_sel")
               .replace("@@", "hex.inc 1, menu_sel") for l in lines]
    assert swapped != lines
    bad = _assemble(tmp_path, "swapped", swapped, common)
    name = "down clamps at hard; up twice to easy; new game at easy"
    assert _run(bad, SCRIPTS[name]) != _expected(SCRIPTS[name])[0], "swapped moves passed"


def _drop(block, *needles):
    """`block` without its lines that name any of `needles` -- one group of the restart's writes"""
    return [ln for ln in block if not any(n in ln for n in needles)]


def _broken(name):
    """the restart block with one group of its writes dropped: (common, [each skill's block])"""
    common, skills = _restart()
    if name == "the lists are not zeroed":
        return _drop(common, "m1.zerobyte sshead"), skills
    if name == "the doors are not shut":
        return _drop(common, "dstate", "ddir", "dsub", "dwait"), skills
    if name == "the positions are not reset":
        return _drop(common, "thpos_rt"), skills
    if name == "the bindings are not reset":
        return _drop(common, "thss_rt"), skills
    if name == "the view's y and angle are not reset":
        return _drop(common, "viewy", "viewangle"), skills
    if name == "the door cells of P2a.1 are not reset":
        return _drop(common, "dreq", "pcard", "wfired"), skills
    if name == "the exit's cells are not reset":
        return _drop(common, "lvdone", "pusedn"), skills
    if name == "no skill links its things":
        return common, [_drop(s, "thnext +") for s in skills]
    assert name == "no skill sets its flags", name
    return common, [_drop(s, "thvis +") for s in skills]


BROKEN = ["the lists are not zeroed", "the doors are not shut", "the positions are not reset",
          "the bindings are not reset", "the view's y and angle are not reset",
          "the door cells of P2a.1 are not reset", "the exit's cells are not reset",
          "no skill links its things", "no skill sets its flags"]


@pytest.mark.parametrize("name", BROKEN)
def test_a_broken_restart_is_caught(tmp_path, name):
    """R9: each group of the restart block's writes, dropped, must show on some script"""
    common, skills = _broken(name)
    good_common, good_skills = _restart()
    assert (common, skills) != (good_common, good_skills), "the control removed nothing"
    bad = _assemble(tmp_path, "broken", menu_state_lines((common, skills)), common)
    caught = [n for n in SCRIPTS if _run(bad, SCRIPTS[n]) != _expected(SCRIPTS[n])[0]]
    assert caught, "a restart block where %s passed every script" % name
