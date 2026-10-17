"""M8 L1 (CR of #142, R6): the oracle's `thvis` (`monsters.MonsterViews.vis_state`) on E1M2, whose lamp 2028 at
(1272, -80) is a baked thing only the hard skill spawns -- `things.vanishable_slots` gives it a slot (the emitter fills
it per skill from `things.skill_absent`), and the oracle must read that slot by the same rule instead of taking it for
a barrel (KeyError before the fix).

CONTROL: the skill rule replaced by "every skill spawns everything" -- the comparison must see the lamp drawn where
the skill lacks it.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from doomfj import gamedata as gd
from doomfj import things as TH
from doomfj.wad import WadFile
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ASSET.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")
SKILLS = (gd.SK_EASY, gd.SK_MEDIUM, gd.SK_HARD)


@pytest.fixture(scope="module")
def e1m2():
    from doomfj.monsters import MonsterViews
    w = World(WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad")), "E1M2", monsters="idle")
    mv = MonsterViews(w.rm, w.mw, "E1M2", WadFile.from_path(str(ASSET)), w)
    return w, mv


def _decor_slots(mv):
    """{slot: drawable index} of the thvis slots that are neither a pickup nor a barrel"""
    other = set(mv.pdi) | set(mv.bdi)
    return {k: di for di, k in mv.vis_slots.items() if di not in other}


def _mismatches(w, mv, absent):
    out = []
    for sk in SKILLS:
        w.reset(sk)
        vis = mv.vis_state(SimpleNamespace(world=w))["thvis"]
        for k, di in _decor_slots(mv).items():
            want = int(di not in absent(mv.drawable, sk))
            if vis[k] != want:
                out.append((sk, k, di, vis[k], want))
    return out


def test_e1m2_has_a_skill_dependent_decoration_slot(e1m2):
    w, mv = e1m2
    slots = _decor_slots(mv)
    assert slots, "E1M2's lamp 2028 has no thvis slot"
    assert any(mv.drawable[di].type == 2028 and (mv.drawable[di].x, mv.drawable[di].y) == (1272, -80)
               for di in slots.values())
    # the slot is worth having: its value differs between the skills
    assert any(len({int(di not in TH.skill_absent(mv.drawable, sk)) for sk in SKILLS}) == 2 for di in slots.values())


def test_the_decoration_slots_follow_the_skill(e1m2):
    w, mv = e1m2
    assert _mismatches(w, mv, TH.skill_absent) == []


def test_control_a_skill_blind_rule_is_caught(e1m2, monkeypatch):
    w, mv = e1m2
    real = TH.skill_absent
    monkeypatch.setattr(TH, "skill_absent", lambda drawable, skill: frozenset())
    assert _mismatches(w, mv, real), "the comparison is vacuous: a skill-blind thvis passed"
