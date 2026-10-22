"""M8 C5b -- A TELEPORT ONTO A MOVER in fj: E1M7's 97 lines 516 and 521 land on sectors 89 and 88, which floor movers
lower (89: W1 36 line 4272, tag 60, floor down to 8 above highest). P_TeleportMove's floorz is the destination SECTOR's
floor NOW -- the model's `world._teleport_monster` reads `secs_c` (the movers where they stand); the fj's fire branch
(teleportcode.monster_lines) splices `teleportcode.dest_floor_lines`: ptss = the destination's leaf, `ms_seed_leaf` (the
mover's state cell -> that state's floor in cp_seedf) -> cp_floor. RUN: that piece, after the REAL
`monstermove.monster_seed_fj` of E1M7, over random states of every lift and floor group (each destination's group at
its every state), each printing cp_floor and ptss, against the model's own teleport of a monster crossing the line at
the same states (its mon_floorz).

R9 (MUTANTS), each must part: the STORED floor (dest_moves off: the pre-C5b baked dest_floor -- parts once the floor
left), the seed not called (a stale cp_seedf), cp_floor never written (the candidate's floor kept).
"""
import dataclasses
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstermove as MM
from doomfj import teleportcode as T
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.config import Config
from doomfj.harness import W
from doomfj.movers import fswitch_nibbles, switch_cell
from doomfj.wad import WadFile
from doomfj.world import World
from tests.fixtures.map_variants import episode_wad

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
ART = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")
N = 200
DEST = {516: 89, 521: 88}                     # the teleport lines whose destination sector moves
NL = chr(10)


@pytest.fixture(scope="module")
def w():
    w = World(episode_wad(WadFile.from_path(str(ART)), "E1M7"), "E1M7", skill=gd.SK_HARD, player="final",
              monsters="final")
    ws = w.ws
    for k in range(w.layout.nmon):              # nothing stands on the destination: no stomp refuses the teleport
        if ws.mon_active[k]:
            w._list_remove(k, ws.mon_leaf[k])
        ws.mon_active[k] = ws.mon_shootable[k] = ws.mon_solid[k] = 0
    ws.px, ws.py = 30000 << 16, 30000 << 16
    return w


def _tel(w, line):
    return [t for t in w.teleports if t.line == line][0]


def _group(w, sector):
    return [g for g, grp in enumerate(w.floor_groups) if sector in grp.sectors][0]


def _cross(w, tel, m):
    """the model's teleport of slot m crossing `tel` at its middle from its front -> mon_floorz"""
    ws = w.ws
    mid = (tel.lo + tel.hi) // 2
    a, b = (tel.coord - 4, tel.coord + 4) if tel.front_le else (tel.coord + 4, tel.coord - 4)
    (ox, oy), (nx, ny) = ((a, mid), (b, mid)) if tel.axis == "x" else ((mid, a), (mid, b))
    ws.mon_x[m], ws.mon_y[m], ws.mon_floorz[m] = nx, ny, 0x5A5A
    ws.mon_active[m] = ws.mon_shootable[m] = 1
    w._teleported = False
    assert w._teleport_monster(m, ox, oy, nx, ny) == tel.dest and w._teleported
    ws.mon_active[m] = ws.mon_shootable[m] = 0
    return ws.mon_floorz[m]


def _records(w):
    """[(line, lift states, floor-group states, the model's floorz)] -- the destination's group at every state, the
    rest random"""
    rnd = random.Random(0xC5B)
    m = [k for k in range(w.layout.nmon) if w.mon_radius[k] == 20][0]
    out = []
    for r in range(N):
        line = sorted(DEST)[r % len(DEST)]
        tel, g = _tel(w, line), _group(w, DEST[line])
        lst = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        fst = [rnd.randrange(grp.n) if rnd.random() < 0.6 else 0 for grp in w.floor_groups]
        n = w.floor_groups[g].n
        fst[g] = (r // len(DEST)) % n if r < 2 * len(DEST) * n else rnd.randrange(n)
        for k, v in enumerate(lst):
            w.ws.l_state[k] = v
        for k, v in enumerate(fst):
            w.ws.f_switch[k], w.ws.f_sub[k] = v, 0
        w._door_phase_scene()
        z = _cross(w, tel, m)
        assert z == w.secs_c[DEST[line]].floor_h
        out.append((line, lst, fst, z))
    return out


def _piece(w, line, mut=None):
    tel = _tel(w, line)
    if mut == "stored":
        return T.dest_floor_lines(dataclasses.replace(tel, dest_moves=False))
    lines = T.dest_floor_lines(tel)
    if mut == "noseed":
        lines = [ln for ln in lines if "ms_seed_leaf" not in ln]
    elif mut == "nowrite":
        lines = [ln for ln in lines if "cp_floor" not in ln]
    return lines


def _program(w, recs, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    body = ["stl.startup_and_init_all"]
    for line, lst, fst, _z in recs:
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(lst)]
        body += ["hex.set 1, %s, %d" % (switch_cell(g), v) for g, v in enumerate(fst)]
        body += ["hex.set 8, cp_floor, 0x5A5A5A5A", "hex.set 8, cp_seedf, 0xA5A5A5A5", "hex.set w/4, ptss, 0x777",
                 *[ln.strip() for ln in _piece(w, line, mut)],
                 "hex.print_as_digit 8, cp_floor, 0", "hex.print_as_digit 3, ptss, 0", "stl.output 10"]
    body += ["stl.loop"]
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    decls = (COLLISION_STATE_DECLS + point_location_decls() + MM.monster_seed_decls()
             + ["lstate: hex.vec %d" % max(1, len(w.lift_order)),
                "fswitch: hex.vec %d" % fswitch_nibbles(w.floor_groups)])
    return NL.join(body + decls + seed) + NL


def _run(tmp_path, w, recs, name, mut=None):
    want = "".join("%08x%03x" % (z & 0xFFFFFFFF, _tel(w, line).dest_leaf) + NL for line, _l, _f, z in recs)
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(w, recs, mut), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], b"",
                                           want.encode(), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


@pytest.fixture(scope="module")
def recs(w):
    return _records(w)


def test_e1m7s_516_and_521_land_on_movers_and_only_their_fires_read_one(w):
    for line, sector in DEST.items():
        tel = _tel(w, line)
        assert tel.dest_sector == sector and tel.dest_moves and sector in w.mover_order
    assert sorted(t.line for t in w.teleports if t.dest_moves) == sorted(DEST)
    text = NL.join(T.monster_lines(w.teleports, prefix="tpm"))
    for line in DEST:
        assert NL.join(T.dest_floor_lines(_tel(w, line))) in text
    assert text.count("stl.fcall ms_seed_leaf, ms_seed_ret") == len(DEST)   # only their fire branches read a mover
    still = [t for t in w.teleports if not t.dest_moves][0]
    assert "ms_seed_leaf" not in NL.join(T.dest_floor_lines(still))


def test_the_records_reach_every_case(w, recs):
    for line in DEST:
        tel = _tel(w, line)
        zs = [z for ln, _l, _f, z in recs if ln == line]
        assert tel.dest_floor in zs, (line, "the floor never sat at its stored height")
        assert sum(z != tel.dest_floor for z in zs) >= 20, (line, "the floor never left its stored height", set(zs))


def test_the_teleports_floor_is_the_models_at_every_mover_state(tmp_path, w, recs):
    assert _run(tmp_path, w, recs, "tpmv"), "cp_floor parted from the model's mon_floorz at the live floor"


@pytest.mark.parametrize("mut", ["stored", "noseed", "nowrite"])
def test_a_broken_mover_destination_is_caught(tmp_path, w, recs, mut):
    assert not _run(tmp_path, w, recs, "tpmv_" + mut, mut), "the mutant %s went unnoticed" % mut
