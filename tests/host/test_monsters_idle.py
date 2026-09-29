"""M7 P3.1 (host): the idle model mode, the one view rule and the oracle's `thing_views` -- each with a control
that shows the check can fail (R9)."""
import importlib.util
import sys
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import monsters as MS
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def oracle():
    spec = importlib.util.spec_from_file_location("gp_probe_p31", ROOT / "scratchpad/gp/probe.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod          # @dataclass resolves the module's annotations through it
    spec.loader.exec_module(mod)
    return mod.Oracle()


@pytest.fixture(scope="module")
def phase(oracle):
    return MS.MonsterPhase(oracle.mw, "E1M1", rm=oracle.rm)


def test_idle_monsters_loop_their_spawn_states_and_never_wake():
    w = World(monsters="idle")
    m = next(k for k in range(w.layout.nmon) if w.ws.mon_active[k])
    w.wake_all  # noqa -- the helper exists; idle must not need it to stay asleep
    seen = set()
    for _ in range(60):
        w.tic({"forward": True})
        seen.add(gd.STATE_NAMES[w.ws.mon_state[m]])
    spawn = gd.MOBJINFO[w.mon_info[m].name].spawnstate if hasattr(w.mon_info[m], "name") else None
    assert len(seen) == 2, seen                                # the STND pair
    assert all(not w.ws.mon_target[k] for k in range(w.layout.nmon))
    assert spawn is None or spawn in seen


def test_control_the_full_mode_wakes_on_a_shot_heard():
    """R9: the same setup with the full model and a noise alert wakes somebody -- idle's silence is the mode's"""
    w = World(monsters="full")
    w.noise_alert()
    for _ in range(40):
        w.tic({})
    assert any(w.ws.mon_target[k] for k in range(w.layout.nmon))
    w2 = World(monsters="idle")
    w2.noise_alert()
    for _ in range(40):
        w2.tic({})
    assert not any(w2.ws.mon_target[k] for k in range(w2.layout.nmon))


def test_the_rotation_is_r_projectsprites(oracle):
    rm = oracle.rm
    # a thing east of the viewer facing west looks AT the viewer: rotation 1; facing east: 5 (its back)
    assert MS.rotation(rm, 0, 0, 100 << 16, 0, 4) == 1
    assert MS.rotation(rm, 0, 0, 100 << 16, 0, 0) == 5
    for f in range(8):
        assert MS.rotation(rm, 0, 0, 100 << 16, 3 << 16, f) == ((((rm.point_to_angle(0, 0, 100 << 16, 3 << 16)
                                                                   - f * MS.ANG45 + 0x90000000) & MS.MASK32)
                                                                 >> 29) + 1)


def test_views_mirror_the_second_half(oracle):
    from doomfj.wall_renderer import anim_frames, anim_patches
    p = anim_patches(oracle.art, anim_frames(oracle.mw, "E1M1"))
    lump, mir = MS.view_of(p, "TROO", 0, 8)
    assert lump.startswith("TROOA2A8") and mir
    assert MS.view_of(p, "TROO", 0, 2) == (lump, False)


def test_the_oracle_draws_views_and_mirrors_them(oracle, phase):
    x, y, a = oracle.spawn.x, oracle.spawn.y, oracle.spawn.angle
    base = oracle.render(x, y, a)
    assert oracle.render(x, y, a, views=[None] * len(oracle.monster_views(phase, x, y))) == base
    # stand where a monster is in view: the first active monster drawn at spawn from its own leaf's far side
    views = oracle.monster_views(phase, x, y)
    drawn = [i for i, v in enumerate(views) if v is not None]
    assert drawn, "no active monster"
    # R9: a whole-set mirror flip must move pixels somewhere a monster is drawn (asymmetric art)
    flipped = [None if v is None else (v[0], not v[1]) for v in views]
    poses = [(x, y, a)] + [(xx, yy, aa) for xx, yy, aa in _near_monster_poses(oracle, phase)]
    assert any(oracle.render(px, py, pa, views=oracle.monster_views(phase, px, py))
               != oracle.render(px, py, pa, views=[None if v is None else (v[0], not v[1])
                                                     for v in oracle.monster_views(phase, px, py)])
               for px, py, pa in poses), "mirroring moves no pixel: the view path is not drawn"
    assert flipped != views


def _near_monster_poses(oracle, phase):
    """a few poses looking at an active monster from 128 units, from four sides"""
    from doomfj.reference_model import ANG90
    w = phase.world
    m = next(k for k in range(w.layout.nmon) if w.ws.mon_active[k])
    mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
    out = []
    for k, (dx, dy) in enumerate(((-128, 0), (0, -128), (128, 0), (0, 128))):
        out.append(((mx + dx) << 16, (my + dy) << 16, (k * ANG90) & 0xFFFFFFFF))
    return out
