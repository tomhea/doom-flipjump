"""M7 P1.5 -- which things a skill has, asked of ONE helper (`things.skill_absent`) by both mirrors.

The gameplay model (`world.World(skill)`, phase 0) is the spec of a skill's level start: monsters of
the other skills stay in their slots inactive, pickups of the other skills start taken, barrels and
solid decor of the other skills are not spawned. The renderer side asks `skill_absent(drawable,
skill)`: the emitter bakes each skill's leaf lists and `thvis` flags from it and the gates hand it to
the oracle. This holds the two to each other on E1M1, for every skill, as multisets of (x, y, type)
over the kinds of thing the model tracks -- with its control (R9): a helper asked the wrong skill's
bit must disagree with the model. The comparison is over the things BOTH sides have: the model
also tracks a few things the renderer has no art for (E1M1: the blue keycard, a type-26 decoration),
which are in no drawable index space and so in no presence question.
"""
from collections import Counter
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import world as W
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel
from doomfj.things import drawable_things, single_player, skill_absent
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
SKILLS = (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)


def _key(t):
    return (t.x, t.y, t.type)


@pytest.fixture(scope="module")
def drawable():
    if not ART.exists():
        pytest.skip("assets/freedoom1.wad (the sprite art) is not here")
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    d, _ = drawable_things(ReferenceModel(Config()), mw.things("E1M1"), WadFile.from_path(str(ART)), {})
    return d


def _model_present(skill, drawable):
    """(x, y, type) of every DRAWABLE thing the model spawns at `skill`, of the kinds it tracks"""
    w = W.World(skill=skill)
    ws = w.ws
    out = Counter()
    out.update(_key(t) for m, t in enumerate(w.mon_things) if ws.mon_active[m])
    out.update(_key(t) for b, t in enumerate(w.barrel_things) if ws.bar_solid[b])
    out.update(_key(t) for i, t in enumerate(w.pickup_things) if not ws.pickup_taken[i])
    out.update(_key(t) for t in w._decor_now)
    drawn = {_key(t) for t in drawable}
    tracked = {_key(t) for t in w.mon_things + w.barrel_things + w.pickup_things + w.decor_solid} & drawn
    return Counter({k: n for k, n in out.items() if k in drawn}), tracked


def _ours(drawable, absent, tracked):
    return Counter(_key(t) for i, t in enumerate(drawable) if i not in absent and _key(t) in tracked)


@pytest.mark.parametrize("skill", SKILLS)
def test_skill_absent_is_the_models_level_start(drawable, skill):
    model, tracked = _model_present(skill, drawable)
    ours = _ours(drawable, skill_absent(drawable, skill), tracked)
    assert ours == model, "skill %d: the helper and the model disagree on %s" % (
        skill, sorted((ours - model) + (model - ours))[:6])
    assert sum(model.values()) > 100


def test_the_skills_differ_and_the_check_can_fail(drawable):
    """R9: the three skills' absent sets differ (so the per-skill check is not one check three
    times), and a helper asked another skill's bit disagrees with the model"""
    absent = {s: skill_absent(drawable, s) for s in SKILLS}
    assert len({absent[s] for s in SKILLS}) == 3
    model, tracked = _model_present(gd.SK_HARD, drawable)
    assert _ours(drawable, absent[gd.SK_EASY], tracked) != model


def test_every_drawable_thing_is_single_player_and_hard_draws_203(drawable):
    assert all(single_player(t) for t in drawable)
    assert len(drawable) - len(skill_absent(drawable, gd.SK_HARD)) == 203      # E1M1, MEASURED


def test_skill_level_start_links_and_flags_only_what_the_skill_spawns():
    """the game tier's per-skill presence: runtime things by being LINKED, baked vanishable things by
    their flag -- on a synthetic level whose answer is written down (and the wrong skill's differs)"""
    from collections import namedtuple
    from doomfj.things import skill_level_start
    T = namedtuple("T", "x y type flags")
    E, N, H = gd.MTF_EASY, gd.MTF_NORMAL, gd.MTF_HARD
    drawable = [T(0, 0, 3004, E), T(1, 0, 3004, H), T(2, 0, 2011, E | N), T(3, 0, 2011, H),
                T(4, 0, 3001, E | N | H)]
    rt_draw, rt_binds = [0, 1, 4], [0, 0, 1]          # runtime things 0..2: drawable 0, 1, 4
    vis_slots = {2: 0, 3: 1}                          # the baked vanishable things
    head, nxt, vis = skill_level_start(drawable, rt_draw, rt_binds, 2, vis_slots, gd.SK_HARD)
    assert (head, nxt, vis) == ([2, 3], [0, 0, 0], [0, 1])      # hard: runtime 1 and 2; slot 1
    head, nxt, vis = skill_level_start(drawable, rt_draw, rt_binds, 2, vis_slots, gd.SK_EASY)
    assert (head, nxt, vis) == ([1, 3], [0, 0, 0], [1, 0])      # easy: runtime 0 and 2; slot 0
    # two present things on one leaf chain ascending, and an absent one between them is skipped
    drawable2 = drawable + [T(5, 0, 3004, H)]
    head, nxt, _ = skill_level_start(drawable2, [1, 0, 5], [0, 0, 0], 1, {}, gd.SK_HARD)
    assert (head, nxt) == ([1], [3, 0, 0])            # runtime 0 -> runtime 2; runtime 1 absent
