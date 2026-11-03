"""M8 L5 (doomfj.noisecode): the flood with ML_SOUNDBLOCK -- P_RecursiveSound's `soundblocks`, a sound crosses at
most ONE marked line -- on the real flipjump engine against the model (`World.noise_alert`, M8 L0).

TWO WORLDS. E1M2 (29 static block edges, no door block edge) and MARKED: E1M1 with ML_SOUNDBLOCK set on a seeded
quarter of its static two-sided lines and half of its door / mover lines, so the block edges THROUGH doors, lifts and
the floor switch (their open tests at the state cells, some node pairs joined by both a plain and a block edge) run
too. In each, `nz_flood` from EVERY start sector under five mixes of door, lift and switch states, each on top of a
random earlier alert (the OR and the scratch both show); then `nz_leaf` itself, the player's sector located from
`viewx` / `viewy`, at the start and at monsters' spawn points.

R9 controls, each a mutation of the emitted text that must part from the model: the block edges DROPPED (the
one-level flood's stand-in: nothing crosses a marked line), the block edges UNBOUNDED (a block edge carries from any
reached node: a second marked line allowed), ONE PASS (no fixpoint), and on MARKED a block door edge's open test
INVERTED.
"""
import dataclasses
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import noisecode as NZ
from doomfj.collision import generate_point_location_fj, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures"
MIXES = ("shut", "open", "mixed1", "mixed2", "mixed3")
CELLS = ("dstate", "lstate", "fswitch")


def marked_world(seed: int = 0x5B, pdoor: float = 0.5, pstat: float = 0.25) -> World:
    """E1M1 with ML_SOUNDBLOCK on a seeded share of its two-sided lines (`pdoor` of those with a door / mover side,
    `pstat` of the static ones) -- the World built from the marked lines, so its regions, nodes and edges are the
    model's own"""
    wad = WadFile.from_path(FIX / "freedoom_e1m1.wad")
    base = World(wad, "E1M1", monsters="idle")
    dyn = set(base.door_order) | set(base.mover_order)
    rnd = random.Random(seed)
    pick = set()
    for i, ld in enumerate(base.lds):
        if not ld.flags & gd.ML_TWOSIDED or not 0 <= ld.back < len(base.sds):
            continue
        a, b = base.sds[ld.front].sector, base.sds[ld.back].sector
        if a != b and rnd.random() < (pdoor if (a in dyn or b in dyn) else pstat):
            pick.add(i)
    orig = wad.linedefs

    def linedefs(m):
        return [dataclasses.replace(ld, flags=ld.flags | gd.ML_SOUNDBLOCK) if i in pick else ld
                for i, ld in enumerate(orig(m))]
    wad.linedefs = linedefs
    return World(wad, "E1M1", monsters="idle")


def _world(which: str) -> World:
    if which == "e1m2":
        return World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2", monsters="idle")
    assert which == "marked", which
    return marked_world()


def _lfsec(w) -> str:
    nleaf = len(w.cmap.subsectors)
    return generate_dispatch_table_fj("lfsec", list(w.leaf_sector),
                                      index_nibbles=max(1, ((nleaf - 1).bit_length() + 3) // 4),
                                      result_nibbles=w.sec_nibbles)


def _fsw(w, pick):
    """M8 F1.3: the floor switch's state -- one per floor group on a WIDE map (E1M2: `fswitch` a vector, states then
    timers), E1M1's one 1-bit switch an int (its group's n is 2: the same draw as before)"""
    vals = [pick(g) for g in w.floor_groups]
    return vals if w.floor_wide else vals[0]


def _states(w, mix):
    """(door states, lift states, switch) for a mix"""
    if mix == "shut":
        return [0] * len(w.door_order), [0] * len(w.lift_order), _fsw(w, lambda g: 0)
    if mix == "open":
        return ([w.door_nstates[si] - 1 for si in w.door_order], [len(w.lift_stops[si]) - 1 for si in w.lift_order],
                _fsw(w, lambda g: g.n - 1))
    rnd = random.Random(mix)
    return ([rnd.randrange(w.door_nstates[si]) for si in w.door_order],
            [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order], _fsw(w, lambda g: rnd.randrange(g.n)))


def _apply(w, st):
    ds, ls, sw = st
    for d, v in enumerate(ds):
        w.ws.d_state[d] = v
    for k, v in enumerate(ls):
        w.ws.l_state[k] = v
    for g, v in enumerate(sw if w.floor_wide else [sw]):     # M8 F1.3: World's one accessor
        w._set_floor(g, v, 0)
    w._door_phase_scene()


def _cases(w):
    """(the states, start sector or None, (x16, y16) or None, the earlier alert)"""
    rnd = random.Random(0x5B1)
    out = []
    for mix in MIXES:
        st = _states(w, mix)
        for s in range(len(w.secs)):
            out.append((st, s, None, [int(rnd.random() < 0.2) for _ in range(w.nsound)]))
    pts = [(w.ws.px, w.ws.py)] + [((w.ws.mon_x[m] << 16) | 0x8000, (w.ws.mon_y[m] << 16) | 0x2000)
                                 for m in range(0, w.layout.nmon, 5)]
    for i, (x16, y16) in enumerate(pts):
        out.append((_states(w, MIXES[i % len(MIXES)]), None, (x16 & 0xFFFFFFFF, y16 & 0xFFFFFFFF), [0] * w.nsound))
    return out


def _expected(w, cases) -> bytes:
    lines = []
    real = w.player_sector
    for st, s, xy, prior in cases:
        _apply(w, st)
        for k in range(w.nsound):
            w.ws.snd_alert[k] = prior[k]
        if s is None:
            x16, y16 = xy
            w.ws.px, w.ws.py = (x16 - (1 << 32) if x16 >> 31 else x16), (y16 - (1 << 32) if y16 >> 31 else y16)
            w.player_sector = real
        else:
            w.player_sector = lambda s=s: s
        w.noise_alert()
        lines.append("".join("%x" % w.ws.snd_alert[k] for k in range(w.nsound)))
    w.player_sector = real
    return ("\n".join(lines) + "\n").encode()


def _block_span(lines):
    """the indices [i, j) of the block edges' code in the leaf (nz_b0 .. the pass loop)"""
    i = lines.index("  nz_b0:")
    j = lines.index("    hex.if1 1, nz_ch, nz_pass")
    assert i < j
    return i, j


def _invert_target(w):
    """the block edge the "invert" control breaks: the first through a door / mover whose test is not always-open"""
    for j, (_a, _b, cell, n, mask) in enumerate(NZ.sound_block_edges(w)):
        if cell is not None and mask != (1 << n) - 1:
            return j, cell, n, mask
    raise AssertionError("no block edge has an open test")


def _flood_text(w, mut=None) -> str:
    lines = NZ.noise_leaf_lines(w)
    if mut == "dropped":                       # the stand-in: nothing crosses a marked line
        i, j = _block_span(lines)
        lines = lines[:i] + lines[j:]
    elif mut == "unbounded":                   # a block edge carries from any reached node: more than one marked line
        i, j = _block_span(lines)
        assert any("nz_z + " in ln for ln in lines[i:j])
        lines = lines[:i] + [ln.replace("nz_z + ", "nz_r + ") for ln in lines[i:j]] + lines[j:]
    elif mut == "onepass":
        assert lines.count("    hex.if1 1, nz_ch, nz_pass") == 1
        lines = [ln for ln in lines if ln != "    hex.if1 1, nz_ch, nz_pass"]
    elif mut == "invert":
        j, cell, ns, mask = _invert_target(w)
        old = "    hex.if_flags %s, %#06x, nz_b%dx, " % (cell, mask, j)
        new = "    hex.if_flags %s, %#06x, nz_b%dx, " % (cell, ~mask & ((1 << ns) - 1), j)
        assert sum(ln.startswith(old) for ln in lines) == 2
        lines = [new + ln[len(old):] if ln.startswith(old) else ln for ln in lines]
    else:
        assert mut is None, mut
    return "\n".join(lines) + "\n"


def _srcs(tmp_path, name, prog):
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]


def _flood_run(tmp_path, which, mut=None) -> bool:
    w = _world(which)
    assert {c.split(" ")[0] for _a, _b, c, *_ in NZ.sound_edges(w) + NZ.sound_block_edges(w) if c} <= set(CELLS)
    cases = _cases(w)
    want = _expected(w, cases)
    nd, nl, n = len(w.door_order), max(1, len(w.lift_order)), w.nsound
    nf = 2 * len(w.floor_groups) if w.floor_wide else 1    # M8 F1.3: fswitch's width (states, then timers)
    body = ["stl.startup_and_init_all"]
    for (ds, ls, sw), s, xy, prior in cases:
        body += ["hex.set %d, dstate, %d" % (nd, sum(v << (4 * d) for d, v in enumerate(ds))),
                 "hex.set %d, lstate, %d" % (nl, sum(v << (4 * k) for k, v in enumerate(ls))),
                 "hex.set %d, fswitch, %d" % (nf, sum(v << (4 * g) for g, v in enumerate(sw)) if w.floor_wide else sw),
                 "hex.set %d, snd_alert, %d" % (n, sum(v << (4 * k) for k, v in enumerate(prior)))]
        if s is None:
            body += ["hex.set 8, viewx, %d" % xy[0], "hex.set 8, viewy, %d" % xy[1], "stl.fcall nz_leaf, nz_ret"]
        else:
            body += ["hex.set %d, nz_sec, %d" % (w.sec_nibbles, s), "stl.fcall nz_flood, nz_ret"]
        body += ["stl.fcall nzb_print, nzb_pret"]
    body += ["stl.loop", "nzb_print:"]                     # the alert printed by one shared routine
    body += ["hex.print_as_digit 1, snd_alert + %d*dw, 0" % k for k in range(n)] + ["stl.output 10",
                                                                                     "stl.fret nzb_pret"]
    decls = (NZ.noise_decls(w) + point_location_decls()
             + ["viewx: hex.vec 8", "viewy: hex.vec 8", "mt_ms: hex.vec %d" % w.sec_nibbles,
                "dstate: hex.vec %d" % nd, "lstate: hex.vec %d" % nl, "fswitch: hex.vec %d" % nf,
                "nzb_pret: hex.vec w/4"])
    prog = "\n".join(body + decls) + "\n" + _flood_text(w, mut) + "\n".join(
        [_lfsec(w), generate_point_location_fj(w.cmap)]) + "\n"
    return fj.assemble_and_run_test_output(_srcs(tmp_path, "nzb_%s_%s" % (which, mut), prog), b"", want,
                                           memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def _model(w, s, rule=None):
    """the nodes `noise_alert` marks from sector `s` -- or, for the controls' arithmetic, with the block edges
    `dropped` or `unbounded` (crossed like plain ones)"""
    saved = (w._sound_door_edges, w._sound_block_door_edges, w._sound_block_static_edges)
    if rule == "dropped":
        w._sound_block_door_edges, w._sound_block_static_edges = [], []
    elif rule == "unbounded":
        rep = {}
        for sec, k in enumerate(w.sector_node):
            rep.setdefault(k, sec)
        w._sound_door_edges = (w._sound_door_edges + w._sound_block_door_edges
                               + [(rep[a], rep[b]) for a, b in w._sound_block_static_edges])
        w._sound_block_door_edges, w._sound_block_static_edges = [], []
    else:
        assert rule is None, rule
    real = w.player_sector
    try:
        for k in range(w.nsound):
            w.ws.snd_alert[k] = 0
        w.player_sector = lambda: s
        w.noise_alert()
        return tuple(w.ws.snd_alert[k] for k in range(w.nsound))
    finally:
        w.player_sector = real
        w._sound_door_edges, w._sound_block_door_edges, w._sound_block_static_edges = saved


def test_the_worlds_have_what_the_flood_needs():
    """E1M2's block edges are all static; MARKED has block edges through doors, lifts and the switch with real open
    tests, node pairs joined by a plain AND a block edge, and static ones -- and in both the marks change what some
    start hears (so the dropped / unbounded controls have something to break)"""
    e2, mk = _world("e1m2"), _world("marked")
    assert len(NZ.sound_block_edges(e2)) == len(e2._sound_block_static_edges) == 29
    blk = NZ.sound_block_edges(mk)
    assert {c.split(" ")[0] for _a, _b, c, *_ in blk if c} == set(CELLS)
    assert any(c and m != (1 << n) - 1 for _a, _b, c, n, m in blk)
    assert any(c is None for _a, _b, c, *_ in blk)
    assert {e[:2] for e in NZ.sound_edges(mk)} & {e[:2] for e in blk if e[2]}
    for w in (e2, mk):
        dropped = unbounded = 0
        for mix in MIXES:
            _apply(w, _states(w, mix))
            for s in range(len(w.secs)):
                heard = _model(w, s)
                dropped += heard != _model(w, s, "dropped")
                unbounded += heard != _model(w, s, "unbounded")
        assert dropped and unbounded, (w.mapname, dropped, unbounded)


def test_e1m1_emits_the_one_level_flood():
    """E1M1 has no marked line: no `nz_z`, no block edge -- the one-level flood (its text frozen in
    tests/host/test_sound_block.py)"""
    w = World(monsters="idle")
    assert NZ.sound_block_edges(w) == []
    text = "\n".join(NZ.noise_leaf_lines(w) + NZ.noise_decls(w))
    assert "nz_z" not in text and "nz_b0" not in text


@pytest.mark.parametrize("which", ["e1m2", "marked"])
def test_the_block_flood_follows_the_model(tmp_path, which):
    assert _flood_run(tmp_path, which), "the fj block flood parted from World.noise_alert on %s" % which


@pytest.mark.parametrize("which,mut", [("e1m2", "dropped"), ("e1m2", "unbounded"), ("e1m2", "onepass"),
                                       ("marked", "unbounded"), ("marked", "invert")])
def test_control_a_broken_block_flood_is_caught(tmp_path, which, mut):
    assert not _flood_run(tmp_path, which, mut), "%s on %s passed: the comparison is vacuous" % (mut, which)
