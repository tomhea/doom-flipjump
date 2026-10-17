"""M8 F1.3 item 9 (docs/f1-big-map-widths.md 9): an item on a MOVER's floor in fj -- `lootcode`'s `pk_mbox` (the item's
x, y from `pkxyz`, its z the floor of its leaf NOW: `ptss` = the leaf, `ms_seed_leaf` -> `cp_seedf`, then the shared
`pk_boxz`) RUN on E1M2's seven mover items -- the blue card on S1 switch sector 45, the yellow card and the soulsphere
on the turbo floors 301 / 358, the backpack on switch sector 241, the items on S1 floor 206 and on blazing lift 47 --
against the model's touch at the live floor (`combat._touch_specials`: `secs_c[pickup_sector]`), over random mover
states (every lift and floor group), candidates on and around the box's edges and floors on and around the reach.
`pickup_lines` itself is checked to route exactly those items through `pk_mbox` (the stubs' text).

R9 (MUTANTS), each must part: the STATIC z (pkxyz's stored floor -- the pre-F1.3 rule: it parts once the floors move,
the card after its switch), the seed not called (a stale cp_seedf), the y read from x.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import lootcode as L
from doomfj import monstermove as MM
from doomfj.collision import COLLISION_STATE_DECLS, point_location_decls
from doomfj.combat import REACH_DOWN, REACH_UP
from doomfj.config import Config
from doomfj.harness import W
from doomfj.movers import fswitch_nibbles, switch_cell
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
FIX = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
M32 = 0xFFFFFFFF
N = 400


@pytest.fixture(scope="module")
def w():
    return World(WadFile.from_path(FIX), "E1M2", skill=gd.SK_HARD, strict=True)


def _records(w):
    rnd = random.Random(0x9B)
    mi = sorted(L.mover_pickup_leaves(w))
    B = L.PK_RADIUS
    out = []
    for r in range(N):
        i = mi[r % len(mi)]
        t = w.pickup_things[i]
        lst = [rnd.randrange(len(w.lift_stops[si])) for si in w.lift_order]
        fst = [rnd.randrange(g.n) if rnd.random() < 0.7 else 0 for g in w.floor_groups]
        for k, v in enumerate(lst):
            w.ws.l_state[k] = v
        for g, v in enumerate(fst):
            w.ws.f_switch[g], w.ws.f_sub[g] = v, 0
        w._door_phase_scene()
        live = w.secs_c[w.pickup_sector[i]].floor_h

        def coord(v):
            return rnd.choice(((v - B) << 16, ((v - B) << 16) + 1, ((v + B) << 16) - 1, (v + B) << 16,
                               ((v + rnd.randint(-B - 4, B + 4)) << 16) + rnd.choice((0, 0x8000, 0x1234, 0xFFFF))))
        cand = (coord(t.x), coord(t.y))
        stored = w.pickup_z[i]
        z = rnd.choice((live, live - REACH_UP, live - REACH_UP - 1, live + REACH_DOWN, live + REACH_DOWN + 1,
                        stored, stored - 30, live + rnd.randint(-90, 90)))
        out.append((i, cand, z, lst, fst, live))
    return out


def _expect(w, recs):
    out = []
    for i, (cx, cy), z, _l, _f, live in recs:
        t = w.pickup_things[i]
        bd = L.PK_RADIUS << 16
        inbox = abs((t.x << 16) - cx) < bd and abs((t.y << 16) - cy) < bd
        out.append(int(inbox and -REACH_DOWN <= live - z <= REACH_UP))
    return out


def _program(w, recs, mut=None):
    from doomfj.wall_renderer import DOOR_QUANT
    leaves = L.mover_pickup_leaves(w)
    nfs = fswitch_nibbles(w.floor_groups)
    body = ["stl.startup_and_init_all"]
    for i, (cx, cy), z, lst, fst, _live in recs:
        body += ["hex.set 1, lstate + %d*dw, %d" % (k, v) for k, v in enumerate(lst)]
        body += ["hex.set 1, %s, %d" % (switch_cell(g), v) for g, v in enumerate(fst)]
        body += ["hex.set 8, cpx, %d" % (cx & M32), "hex.set 8, cpy, %d" % (cy & M32),
                 "hex.set 8, cm_hf, %d" % (z & M32), "hex.set 2, pk_i, %d" % i,
                 "hex.set w/4, ptss, %d" % leaves[i], "stl.fcall pk_mbox, pk_mret",
                 "hex.print_as_digit 1, pk_in, 0"]
    body += ["stl.output 10", "stl.loop"]
    leaf = "\n".join(L._box_leaf() + L._mbox_leaf())
    if mut == "static":       # the item's z from pkxyz (its stored floor), the seed's floor ignored
        leaf, n = re.subn(r"    stl\.fcall ms_seed_leaf, ms_seed_ret\n    hex\.mov 8, pk_tz, cp_seedf\n",
                          "    hex.zero 8, pk_tz\n    hex.mov 4, pk_tz, pk_r + 8*dw\n    hex.sign_extend 8, 4, pk_tz\n",
                          leaf)
        assert n == 1
    elif mut == "noseed":
        leaf, n = re.subn(r"    stl\.fcall ms_seed_leaf, ms_seed_ret\n", "", leaf)
        assert n == 1
    elif mut == "y_from_x":
        leaf, n = re.subn(r"(pk_mbox:\n(?:.*\n){3})    hex\.mov 4, pk_ty \+ 4\*dw, pk_r \+ 4\*dw",
                          r"\1    hex.mov 4, pk_ty + 4*dw, pk_r", leaf)
        assert n == 1
    kw = MM.world_cell_inputs(w, DOOR_QUANT)
    seed = MM.monster_seed_fj(w.cmap, w.lds, w.sds, kw["secs_open"], kw["msecs"], kw["mcell"])
    decls = (L.loot_decls(L.level_start(w)) + L.mbox_decls(w) + COLLISION_STATE_DECLS + point_location_decls()
             + MM.monster_seed_decls()
             + ["lstate: hex.vec %d" % len(w.lift_order), "fswitch: hex.vec %d" % nfs])
    return "\n".join(body + decls) + "\n;pk_skip\n" + leaf + "\n" + "\n".join(seed) + "\npk_skip:\n" \
        + L.pickup_table_fj(w)


def _run(tmp_path, w, name, mut=None):
    recs = _records(w)
    want = "".join(str(v) for v in _expect(w, recs)) + "\n"
    p = tmp_path / ("%s.fj" % name)
    p.write_text(_program(w, recs, mut), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()], b"",
                                           want.encode(), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False), recs, want


def test_the_mover_items_are_the_seven_and_route_through_pk_mbox(w):
    leaves = L.mover_pickup_leaves(w)
    assert sorted(w.pickup_things[i].type for i in leaves) == sorted([5, 2049, 6, 2013, 8, 2015, 2007])
    # the stubs' text: exactly the mover items call pk_mbox, the rest pk_box (a stand-in slot map: one each)
    slots = {"slot": list(range(len(w.pickup_things))), "rt": [None] * len(w.pickup_things),
             "leaf": [None] * len(w.pickup_things)}
    try:
        text = "\n".join(L.pickup_lines(w, slots, [0] * w.layout.nmon))
    except (AssertionError, KeyError, NotImplementedError) as e:      # a give routine F4 owns (the stand-in)
        pytest.skip("pickup_lines on E1M2 needs the gives of F4: %r" % (e,))
    for i in range(len(w.pickup_things)):
        stub = text[text.index("\npk%d:\n" % i):].split("stl.fret pk_iret")[0]
        assert ("pk_mbox" in stub) == (i in leaves), i


def test_the_records_reach_every_case(w):
    recs = _records(w)
    want = _expect(w, recs)
    card = [r for r in recs if w.pickup_things[r[0]].type == 5]
    assert 0.15 < sum(want) / len(want) < 0.85
    # the card: taken on its LOWERED floor where the stored one refuses, and the reverse
    lowered = [r for r in card if r[5] != w.pickup_z[r[0]]]
    assert lowered and any(e and not (-REACH_DOWN <= w.pickup_z[r[0]] - r[2] <= REACH_UP)
                           for r, e in zip(recs, want) if r in lowered)


def test_pk_mbox_is_the_models_touch(tmp_path, w):
    ok, _r, _w = _run(tmp_path, w, "mbox")
    assert ok, "pk_mbox parted from the model's touch at the live floor"


@pytest.mark.parametrize("mut", ["static", "noseed", "y_from_x"])
def test_control_broken_mbox_is_caught(tmp_path, w, mut):
    ok, _r, _w = _run(tmp_path, w, "mbox_" + mut, mut)
    assert not ok, "%s passed: the comparison is vacuous" % mut
