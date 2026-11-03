"""M8 wave 1: a BARREL on a mover's floor in fj -- E1M3's barrel on a lift rides it (P_ChangeSector), so the knock's
inflictor z of its blast (`bl_z`) is its leaf's floor NOW, the model's `combat._knock_z(("bar", b))` (`_floor_at`, the
live `secs_c`), not knockcode's baked `kbbz` (its level-start floor). RUN: the barrel's stub piece
(`barrelcode.mover_z_lines`: ptss = its leaf, `ms_seed_leaf` -> cp_seedf, bl_z, bl_mv) then bl_leaf's top
(`barrelcode.blast_z_lines(True)`), over random mover states (every lift and floor group), mixed with records of the
other barrels (no stub: kbbz by bl_b) and of a rocket (bl_dyn 1: its own bl_z kept) -- each printing bl_z and bl_mv.
`phase_lines` / `blast_lines` are checked to carry exactly those pieces (the stubs' text).

R9 (MUTANTS), each must part: the STATIC z (the stub's piece dropped: kbbz's stored floor -- the pre-M8 rule, parting
once the lift moves), bl_mv never set (kbbz overwrites the live floor), the seed not called (a stale cp_seedf), bl_mv
never cleared (the next barrel keeps the mover's z).
"""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import barrelcode as BC
from doomfj import gamedata as gd
from doomfj import monstermove as MM
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.knockcode import barrel_floor_values
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.movers import fswitch_nibbles, switch_cell
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m3.wad"
N = 240


@pytest.fixture(scope="module")
def w():
    return World(WadFile.from_path(FIX), "E1M3", skill=gd.SK_HARD, strict=True)


def _records(w):
    """(kind, barrel, lift states, floor-group states, preset bl_z, the model's bl_z): kind 'm' a mover barrel through
    its stub, 's' another barrel (kbbz), 'r' a rocket (bl_dyn 1, its z preset)"""
    rnd = random.Random(0xB4)
    mov = sorted(BC.mover_barrel_leaves(w))
    other = [b for b in range(len(w.barrel_things)) if b not in mov]
    out = []
    for r in range(N):
        kind = rnd.choice("mmmmsr") if other else rnd.choice("mmmr")
        b = rnd.choice(mov if kind != "s" else other)
        lst = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        fst = [rnd.randrange(g.n) if rnd.random() < 0.7 else 0 for g in w.floor_groups]
        for k, v in enumerate(lst):
            w.ws.l_state[k] = v
        for g, v in enumerate(fst):
            w.ws.f_switch[g], w.ws.f_sub[g] = v, 0
        w._door_phase_scene()
        pre = rnd.randrange(1 << 16)
        want = pre if kind == "r" else w._knock_z(("bar", b)) & 0xFFFF
        out.append((kind, b, lst, fst, pre, want))
    return out


def _mutate(stub, top, mut):
    if mut == "static":
        stub = []
    elif mut == "noflag":
        stub = [ln for ln in stub if "bl_mv" not in ln]
    elif mut == "noseed":
        stub = [ln for ln in stub if "ms_seed_leaf" not in ln]
    elif mut == "noclear" and top:
        assert "    hex.zero 1, bl_mv" in top
        top = [ln for ln in top if ln != "    hex.zero 1, bl_mv"]
    return stub, top


def _program(w, recs, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    leaves = BC.mover_barrel_leaves(w)
    body = ["stl.startup_and_init_all"]
    for kind, b, lst, fst, pre, _want in recs:
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(lst)]
        body += ["hex.set 1, %s, %d" % (switch_cell(g), v) for g, v in enumerate(fst)]
        body += ["hex.set 2, bl_b, %d" % b, "hex.set 1, bl_dyn, %d" % (kind == "r"), "hex.set 4, bl_z, %d" % pre,
                 "hex.set 8, cp_seedf, 0x5A5A5A5A"]
        if kind == "m":
            stub, _top = _mutate(BC.mover_z_lines(leaves[b]), [], mut)
            body += [ln.strip() for ln in stub]
        body += ["stl.fcall bz_top, bz_ret", "hex.print_as_digit 4, bl_z, 0", "hex.print_as_digit 1, bl_mv, 0",
                 "stl.output 10"]
    body += ["stl.loop"]
    _s, top = _mutate([], BC.blast_z_lines(True), mut)
    leaf = ["bz_top:"] + top + ["    stl.fret bz_ret"]
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    decls = (COLLISION_STATE_DECLS + point_location_decls() + MM.monster_seed_decls()
             + ["lstate: hex.vec %d" % len(w.lift_order), "fswitch: hex.vec %d" % fswitch_nibbles(w.floor_groups),
                "bl_b: hex.vec 2", "bl_dyn: hex.vec 1", "bl_z: hex.vec 4", "bl_mv: hex.vec 1", "bz_ret: hex.vec w/4"])
    kbbz = generate_dispatch_table_fj("kbbz", barrel_floor_values(w) or [0], index_nibbles=2, result_nibbles=4)
    return ("\n".join(body + decls) + "\n;bz_skip\n" + "\n".join(leaf) + "\n" + "\n".join(seed) + "\nbz_skip:\n"
            + kbbz)


def _run(tmp_path, w, name, mut=None):
    recs = _records(w)
    want = "".join("%04x0\n" % r[5] for r in recs)
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(w, recs, mut), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], b"",
                                           want.encode(), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_e1m3_has_a_barrel_on_a_mover_and_the_stubs_carry_its_z(w):
    leaves = BC.mover_barrel_leaves(w)
    assert leaves, "E1M3's barrel on a lift is gone: this test proves nothing"
    text = "\n".join(BC.phase_lines(w))
    for b in range(len(w.barrel_things)):
        stub = text[text.index("  bp%d_x:\n" % b):].split("stl.fcall bl_leaf, bl_ret")[0]
        if b in leaves:
            assert "\n".join(BC.mover_z_lines(leaves[b])) in stub, b
        assert ("ms_seed_leaf" in stub) == (b in leaves), b
    blast = BC.blast_lines(w, slot_rt=list(range(w.layout.nmon)), knock=True, fight=True, rockets=True)
    i = blast.index("bl_leaf:")
    assert blast[i + 1:i + 1 + len(BC.blast_z_lines(True))] == BC.blast_z_lines(True)


def test_the_records_reach_every_case(w):
    recs = _records(w)
    assert {r[0] for r in recs} >= {"m", "r"}
    stored = barrel_floor_values(w)
    moved = [r for r in recs if r[0] == "m" and r[5] != stored[r[1]]]
    still = [r for r in recs if r[0] == "m" and r[5] == stored[r[1]]]
    assert moved and still, "the lift never left (or never sat at) the barrel's level-start floor"


def test_the_mover_barrels_z_is_the_models(tmp_path, w):
    assert _run(tmp_path, w, "bz"), "bl_z parted from the model's _knock_z at the live floor"


@pytest.mark.parametrize("mut", ["static", "noflag", "noseed", "noclear"])
def test_control_a_broken_mover_z_is_caught(tmp_path, w, mut):
    assert not _run(tmp_path, w, "bz_" + mut, mut), "%s passed: the comparison is vacuous" % mut
