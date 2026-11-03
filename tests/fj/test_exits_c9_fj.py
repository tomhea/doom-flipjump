"""M8 C9 -- THE EXITS a map adds RUN in fj against the MODEL: the S1 SECRET exit (51, E1M3) beside its S1 exit (11),
E1M7's two S1 exits (11, 11) with the switch textures on (each line its own cell), and the W1 EXIT (52, E1M8's eight
lines round the boss pad). The emitter's own text -- `wall_renderer.exit_lines` with `exitcode.hit_lines`, and
`exitcode.walk_lines` on `doors.exit_walk_triggers` -- fed records, read back, and compared with the model on that
map's World (tests/fixtures/map_variants.episode_wad): `combat._use_lines`' exit branch, `combat._walkover`.

The switch records: the 16.16 position at every exit box's edges (on, one step in, one step out, both axes), its
centre and far away, use held / not, use held last tic; read back pusedn, lvdone, mode, menu_scr, lvsec and each exit
line's switch cell. The walk records: moves crossing each fused W1 segment both ways at its middle and its extent's
strict ends (lo - r, hi + r, one step either side), short of it and starting ON it; read back lvdone, mode, menu_scr.

R9 (MUTANTS): the secret exit's lvsec never set; set by the plain exit too; the pressed line's cell given to the other
exit; the W1 exit firing one way only; its extent inclusive; the level not ending (mode untouched).
"""
import struct
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj import config as C
from doomfj import doors as D
from doomfj import exitcode as X
from doomfj import switches as SW
from doomfj.combat import PLAYER_R
from doomfj.harness import W
from doomfj.menu import LEVEL_DONE_ENTER
from doomfj.wad import WadFile
from doomfj.wall_renderer import exit_lines
from doomfj.world import TicEvents, World
from tests.fixtures.map_variants import episode_wad

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
M32 = 0xFFFFFFFF
FIRE = ["hex.set 1, lvdone, 1", "hex.set 1, mode, 1", f"hex.set 1, menu_scr, {LEVEL_DONE_ENTER}"]


def _run(tmp, name, text, feed) -> list:
    src = tmp / (name + ".fj")
    src.write_text(text, encoding="utf-8")
    out = tmp / (name + ".fjm")
    fj.assemble([src.resolve()], out, memory_width=W, print_time=False)
    io = FixedIO(feed + bytes([0]))
    fj.run(out, io_device=io, print_time=False, print_termination=False)
    return [int(t, 16) for t in io.get_output(allow_incomplete_output=True).decode().split()]


def _mutate(text, muts):
    for old, new in muts:
        assert text.count(old) >= 1, old
        text = text.replace(old, new)
    return text


_W = {}


def world(m, switch_tex=False):
    """the map's World, its switch textures on exactly when `switch_tex` (config.MAP_CONFIG patched for the build only:
    since M8 wave 1 E1M3's own config turns them on)"""
    key = (m, switch_tex)
    if key not in _W:
        saved = dict(C.MAP_CONFIG)
        try:
            C.MAP_CONFIG[m] = {**C.MAP_CONFIG.get(m, {}), "SWITCH_TEX": int(switch_tex)}
            _W[key] = World(episode_wad(WadFile.from_path(str(ART)), m), m, player="final", monsters="final")
        finally:
            C.MAP_CONFIG.clear()
            C.MAP_CONFIG.update(saved)
    return _W[key]


# ---- the switches: 51 beside 11, two 11s ------------------------------------------------------------------------------
def _exit_cells(w):
    """the latched exit switches' indices among switches.latched (switchcode.cell's k)"""
    return [k for k, s in enumerate(SW.latched(w.switches)) if s.kind == "exit"]


def switch_program(w, muts=()):
    lat = SW.latched(w.switches)
    nlat = max(1, len(lat))
    text = "\n".join(exit_lines(w.exit_boxes, (), (), X.hit_lines(w.lds, lat)))
    outs = ["pusedn", "lvdone", "mode", "menu_scr", "lvsec"] + [f"swpr + {k}*dw" for k in _exit_cells(w)]
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 1, rbyte", "hex.mov 1, duse, rbyte", "hex.input 1, rbyte", "hex.mov 1, pusedn, rbyte",
            "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.zero 1, lvdone", "hex.zero 1, mode", "hex.zero 1, menu_scr", "hex.zero 1, lvsec",
            f"hex.zero {nlat}, swpr", text]
    for reg in outs:
        body += [f"    hex.print_as_digit 1, {reg}, 0", "    stl.output 32"]
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "rbyte: hex.vec 2", "viewx: hex.vec 8",
             "viewy: hex.vec 8", "duse: hex.vec 1", "dbox: hex.vec 8, 0", "pusedn: hex.vec 1", "lvdone: hex.vec 1",
             "mode: hex.vec 1", "menu_scr: hex.vec 1", f"swpr: hex.vec {nlat}",
             *(X.decls(w.lds) or ["lvsec: hex.vec 1"])]
    return _mutate("\n".join(body) + "\n", muts), len(outs)


def _probes(w):
    out = []
    for (x0, y0, x1, y1) in w.exit_boxes:
        xs = [(x0 << 16) - 1, x0 << 16, (x0 << 16) + 1, ((x0 + x1) // 2) << 16, (x1 << 16) - 1, x1 << 16,
              (x1 << 16) + 1]
        ys = [(y0 << 16) - 1, y0 << 16, (y0 << 16) + 1, ((y0 + y1) // 2) << 16, (y1 << 16) - 1, y1 << 16,
              (y1 << 16) + 1]
        out += [(x, y) for x in xs for y in ys]
    out.append((-30000 << 16, -30000 << 16))
    return out


def _model_exit(w, x, y):
    """`combat._use_lines`' exit branch, alone (the harness runs no floor / lift switch lines: press_first is empty):
    the first box holding (x, y) ends the level, flags the secret exit, swaps its own line"""
    ws = w.ws
    for k, box in enumerate(w.exit_boxes):
        if D.in_use_box_fixed(box, x, y):
            ws.g_leveldone = 1
            if w.exit_secret[k]:
                ws.g_secretexit = 1
            w.switch_exit(w.exit_box_lines[k])
            return


def _switch_expect(w):
    ws = w.ws
    cells = _exit_cells(w)
    feed, want, hits, secrets = b"", [], 0, 0
    for x, y in _probes(w):
        for use, last in ((1, 0), (1, 1), (0, 0), (0, 1)):
            feed += bytes([1, use, last]) + struct.pack("<II", x & M32, y & M32)
            ws.g_leveldone = 0
            if w.layout.secexit:
                ws.g_secretexit = 0
            for k in range(len(w.switch_cells)):
                ws.sw_on[k] = 0
            pusedn = last
            if use and not pusedn:
                pusedn = 1
                _model_exit(w, x, y)
            elif not use:
                pusedn = 0
            done = ws.g_leveldone
            sec = ws.g_secretexit if w.layout.secexit else 0
            hits, secrets = hits + done, secrets + sec
            want += [pusedn, done, done, LEVEL_DONE_ENTER if done else 0, sec] + [ws.sw_on[k] for k in cells]
    return feed, want, hits, secrets


@needs_art
@pytest.mark.parametrize("m,tex", [("E1M3", False), ("E1M3", True), ("E1M7", True)])
def test_the_exit_switches_run_as_the_model(tmp_path, m, tex):
    w = world(m, tex)
    assert len(w.exit_boxes) == 2 and (len(_exit_cells(w)) == 2) == tex
    feed, want, hits, secrets = _switch_expect(w)
    assert hits >= 40 and (secrets >= 20) == (m == "E1M3"), (hits, secrets)
    text, per = switch_program(w)
    got = _run(tmp_path, "xs", text, feed)
    assert got == want, [i // per for i, (g, v) in enumerate(zip(got, want)) if g != v][:5]


@needs_art
def test_the_model_s_use_lines_set_the_secret_flag():
    """the model's own P_UseLines (combat._use_lines) on E1M3 -- the harness's `_model_exit` is exactly this branch:
    the box of line 993 (51) sets g_secretexit, 1367's (11) does not; only the pressed exit swaps"""
    w = world("E1M3", True)
    ws = w.ws
    for k, line in enumerate(w.exit_box_lines):
        ws.g_leveldone = ws.g_secretexit = 0
        for j in range(len(w.switch_cells)):
            ws.sw_on[j] = 0
        x0, y0, x1, y1 = w.exit_boxes[k]
        ws.px, ws.py = ((x0 + x1) // 2) << 16, ((y0 + y1) // 2) << 16
        w._use_lines(TicEvents(0))
        assert ws.g_leveldone == 1 and ws.g_secretexit == (line == 993)
        assert w.switch_on() == frozenset({line})


def _swap_cells(w):
    a, b = _exit_cells(w)
    return [(f"hex.set 1, swpr + {a}*dw, 1", f"hex.set 1, swpr + {b}*dw, 1"),
            (f"hex.set 1, swpr + {b}*dw, 1", f"hex.set 1, swpr + {a}*dw, 1")]


SW_MUTS = {
    "secret_never_set": ("E1M3", False, lambda w: [("hex.set 1, lvsec, 1\n", "")]),
    "secret_set_by_both": ("E1M3", False, lambda w: [("ex_hit:\n", "ex_hit:\nhex.set 1, lvsec, 1\n")]),
    "cells_swapped": ("E1M7", True, _swap_cells),
}


@needs_art
@pytest.mark.parametrize("mut", sorted(SW_MUTS))
def test_a_broken_exit_switch_is_caught(tmp_path, mut):
    m, tex, muts = SW_MUTS[mut]
    w = world(m, tex)
    feed, want, _h, _s = _switch_expect(w)
    text, _per = switch_program(w, muts(w))
    got = _run(tmp_path, "xs_" + mut, text, feed)
    assert len(got) == len(want) and got != want, mut


# ---- the W1 exit: E1M8 -----------------------------------------------------------------------------------------------
def walk_program(trigs, muts=()):
    text = "\n".join(X.walk_lines(trigs, PLAYER_R, FIRE))
    body = ["stl.startup_and_init_all", "loop:", "hex.input 1, rmagic", "hex.if0 2, rmagic, done",
            "hex.input 4, cm_ox", "hex.input 4, cm_oy", "hex.input 4, viewx", "hex.input 4, viewy",
            "hex.zero 1, lvdone", "hex.zero 1, mode", "hex.zero 1, menu_scr", text]
    for reg in ("lvdone", "mode", "menu_scr"):
        body += [f"    hex.print_as_digit 1, {reg}, 0", "    stl.output 32"]
    body += [";loop", "done:", "stl.loop", "rmagic: hex.vec 2", "cm_ox: hex.vec 8", "cm_oy: hex.vec 8",
             "viewx: hex.vec 8", "viewy: hex.vec 8", "lvdone: hex.vec 1", "mode: hex.vec 1", "menu_scr: hex.vec 1",
             "dbox: hex.vec 8"]
    return _mutate("\n".join(body) + "\n", muts)


def _walk_records(trigs, r=PLAYER_R):
    out = []
    for _s, axis, coord, lo, hi in trigs:
        L = coord << 16
        os_ = ([((lo - r) << 16) + d for d in (-1, 0, 1)] + [((hi + r) << 16) + d for d in (-1, 0, 1)]
               + [((lo + hi) // 2) << 16])
        cs = [L - (5 << 16), L - 1, L, L + 1, L + (5 << 16)]
        for o in os_:
            for a in cs:
                for b in cs:
                    if a != b:
                        out.append(((a, o), (b, o)) if axis == "x" else ((o, a), (o, b)))
    return out


def _walk_expect(w, recs):
    ws = w.ws
    feed, want, hits = b"", [], 0
    for (ox, oy), (nx, ny) in recs:
        feed += bytes([1]) + struct.pack("<IIII", ox & M32, oy & M32, nx & M32, ny & M32)
        ws.g_leveldone = 0
        ws.px, ws.py = nx, ny
        w._walkover(ox, oy, nx, ny, TicEvents(0))
        d = ws.g_leveldone
        hits += d
        want += [d, d, LEVEL_DONE_ENTER if d else 0]
    return feed, want, hits


@pytest.fixture(scope="module")
def e1m8():
    if not ART.exists():
        pytest.skip("needs assets/freedoom1.wad")
    w = world("E1M8")
    assert len(w.exit_walk) == 4 and w.exit_boxes == []
    return w


def test_the_w1_exit_runs_as_the_model(tmp_path, e1m8):
    recs = _walk_records(e1m8.exit_walk)
    feed, want, hits = _walk_expect(e1m8, recs)
    assert 100 <= hits <= len(recs) - 100, (hits, len(recs))      # both ways, and short / outside of it
    got = _run(tmp_path, "xw", walk_program(e1m8.exit_walk), feed)
    assert got == want, [i // 3 for i, (g, v) in enumerate(zip(got, want)) if g != v][:5]


def test_e1m8s_eight_lines_fuse_to_the_pads_four_sides(e1m8):
    assert e1m8.exit_walk == [(0, "x", 896, 256, 384), (0, "x", 1024, 256, 384), (0, "y", 256, 896, 1024),
                              (0, "y", 384, 896, 1024)]
    e1m1 = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    assert D.exit_walk_triggers(e1m1.linedefs("E1M1"), e1m1.vertexes("E1M1")) == []


def _w_muts(text, mut):
    if mut == "one_way_only":                       # an old centre above x = 896 never fires
        return [("  xw0_og:\n", "  xw0_og:\n    ;xw0_no\n")]
    if mut == "extent_inclusive":                   # the far end's strict compare made inclusive
        line = [ln for ln in text.splitlines() if "xw0_fire, xw0_no, xw0_no" in ln][0]
        return [(line, line.replace("xw0_fire, xw0_no, xw0_no", "xw0_fire, xw0_fire, xw0_no"))]
    return [("    hex.set 1, mode, 1\n", "")]       # level_not_ended


@pytest.mark.parametrize("mut", ["one_way_only", "extent_inclusive", "level_not_ended"])
def test_a_broken_w1_exit_is_caught(tmp_path, e1m8, mut):
    recs = _walk_records(e1m8.exit_walk)
    feed, want, _h = _walk_expect(e1m8, recs)
    text = walk_program(e1m8.exit_walk)
    got = _run(tmp_path, "xw_" + mut, _mutate(text, _w_muts(text, mut)), feed)
    assert len(got) == len(want) and got != want, mut
