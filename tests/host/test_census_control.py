"""M7 P11 (the pre-review's finding): the census's own R9 control, scratchpad/gp/census_control.py, in the host suite.

The census (scratchpad/gp/census_lib.py) draws the model's monsters as SYNTHETIC types, made monsters by patching
reference_model.MONSTER_TYPES around each render. P11 (a) added DRAW_ACTOR_TYPES, derived from MONSTER_TYPES at
import, which the census did not patch: its live monsters drew in the SCENERY class (h42 and the courtyard parted from
the stock picture), the planner's drawn populations halved, and nothing ran the control. Here, any drift between the
oracle's module state and the census's patching fails the suite. Two tests, because the control alone cannot see that
drift: its eleven viewpoints draw TODAY's things, at their WAD types, and only the model's monsters (game_things) are
synthetic -- so the second test renders game_things and requires its live types in BOTH sets while the oracle draws.
(The control itself was miscalibrated since P8a: it built the census at the default modes, whose compositor keys are
off, against a stock picture with them on -- h42 and the courtyard parted; it now builds it at the game tier's.)"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "scratchpad" / "gp" / "census_control.py"


@pytest.mark.skipif(not (ROOT / "assets" / "freedoom1.wad").exists(), reason="needs assets/freedoom1.wad")
def test_the_census_draws_the_oracles_picture():
    r = subprocess.run([sys.executable, str(CONTROL)], cwd=ROOT, capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    assert "CONTROL: PASS" in out, out[-3000:]
    assert "the comparison has teeth" in out and r.returncode == 0, out[-3000:]


@pytest.mark.skipif(not (ROOT / "assets" / "freedoom1.wad").exists(), reason="needs assets/freedoom1.wad")
def test_the_census_draws_its_monsters_in_the_monster_class(monkeypatch):
    """the model's live monsters are SYNTHETIC types in the census; while the oracle draws them they must be in
    MONSTER_TYPES (the budget category, the seen and aim tests) AND in DRAW_ACTOR_TYPES (the drawing class: P11 (a)),
    and both sets are restored after the render"""
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import census_lib as CL
    from doomfj import reference_model as RMOD
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    c = CL.Census(player=PLAYER_MODE, monsters=MONSTER_MODE)
    th, bk, me, mt = c.game_things(corpse_as_monster=False, depth_order=True)
    live = {t.type for t, m in zip(th, me) if m is not None and m.role == "live"}
    assert live and not live & CL.ORIG_MONSTER_TYPES, "the level start's monsters are drawn as synthetic types"
    seen = []
    orig = RMOD.ReferenceModel.render_wall_frame

    def spy(self, *a, **k):
        seen.append((RMOD.MONSTER_TYPES, RMOD.DRAW_ACTOR_TYPES))
        return orig(self, *a, **k)
    monkeypatch.setattr(RMOD.ReferenceModel, "render_wall_frame", spy)
    before = (RMOD.MONSTER_TYPES, RMOD.DRAW_ACTOR_TYPES)
    c.render(th, bk, me, mt)
    assert len(seen) == 1
    monster_types, actor_types = seen[0]
    assert live <= monster_types, "a live monster is not a monster while the census draws"
    assert live <= actor_types, "a live monster is drawn as SCENERY: DRAW_ACTOR_TYPES lacks the census's live types"
    assert (RMOD.MONSTER_TYPES, RMOD.DRAW_ACTOR_TYPES) == before, "the census did not restore the oracle's sets"
