"""M8 F1.2 (docs/f1-big-map-widths.md 7b): a SOLID decoration some skill lacks stands by its `mc_don` flag -- declared at
the boot skill's presence, set per skill by NEW GAME, persisted (the reset must not undo NEW GAME's choice) -- only on a
map that has one (E1M2's decor_solid[20], E1M9's [21]); E1M1 has none, so its program is unchanged.

CONTROL: the presence read from a skill-blind rule (every decoration on every skill) parts from the model's.
"""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import monstermove as MM
from doomfj.build import persist_labels
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
SKILLS = (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)


def _wad(m):
    return WadFile.from_path(str(ROOT / "tests" / "fixtures" / ("freedoom_%s.wad" % m.lower())))


@pytest.fixture(scope="module")
def e1m2():
    return World(_wad("E1M2"), "E1M2", monsters="idle")


def test_only_a_map_with_a_skill_dependent_decoration_persists_mc_don():
    assert MM.map_persist(_wad("E1M1"), "E1M1") == ()
    assert MM.map_persist(_wad("E1M2"), "E1M2") == ("mc_don",)


def test_persist_labels_carries_the_maps_own_names_last():
    base = persist_labels(standalone=True, doors=True, moving_things=True)
    assert "mc_don" not in base
    assert persist_labels(standalone=True, doors=True, moving_things=True, extra=("mc_don",)) == base + ("mc_don",)
    assert persist_labels(standalone=False, doors=True, moving_things=True, extra=("mc_don",)) == ()


def test_the_flags_follow_the_skill(e1m2):
    _things, var = MM.static_blockers(e1m2)
    assert var, "E1M2 has no skill-dependent solid decoration: the case is not exercised"
    vals = {sk: MM.decor_presence(e1m2, var, sk) for sk in SKILLS}
    assert len({tuple(v) for v in vals.values()}) > 1, "the flags do not differ by skill"
    for sk in SKILLS:
        standing = e1m2._decor_for(sk)                    # the model's own: the decorations that skill stands
        assert vals[sk] == [int(any(e1m2.decor_solid[k] is t for t in standing)) for k in var]
        want = sum(v << (4 * i) for i, v in enumerate(vals[sk]))
        assert MM.mc_don_restart(e1m2, var, sk) == ["    hex.set %d, mc_don, %d" % (len(var), want)]
    assert MM.mc_don_decl(e1m2, var, gd.SK_HARD).startswith("mc_don: hex.vec %d, " % len(var))


def test_control_a_skill_blind_presence_is_caught(e1m2, monkeypatch):
    _things, var = MM.static_blockers(e1m2)
    real = {sk: MM.decor_presence(e1m2, var, sk) for sk in SKILLS}
    monkeypatch.setattr(MM, "decor_presence", lambda w, var_, skill: [1] * len(var_))
    blind = {sk: MM.mc_don_restart(e1m2, var, sk) for sk in SKILLS}
    assert any(blind[sk] != ["    hex.set %d, mc_don, %d" % (len(var), sum(v << (4 * i) for i, v in enumerate(real[sk])))]
               for sk in SKILLS)
