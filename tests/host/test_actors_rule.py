"""M7 P6+P7 package E (host): THE ACTORS RULE -- the game picture's `exempt_actors` (reference_model.GAME_RENDER_KW).

The owner, 2026-10-05: "make sure monsters are almost always seen"; "sometimes [the fireball] doesn't show at all ...
you must always show the fireballs"; "monsters get off-rendered when I move a little bit to some side ... a really
small part of them is behind a corpse ... monsters should always be shown".

ROOT CAUSES found in the oracle (blocked48 draws the same pixels), each held here by a frame that shows it:
  * the corpse: a sprite with no row inside the view still recorded a fragment -- the corpse the player stands on is
    under the view yet spans every column, so it held slot A everywhere and every monster behind it was left to the
    B-gate, which refuses slot B to a sprite under DEG_SPRB_MINH (32) rows: a monster ~150+ units away vanished whole
    (v5 R0-aftermath frame 57: a sergeant at 438 and an imp at 1016 units behind a corpse 4 units away);
  * the fireball: a mobile was SCENERY at MIN_SPRITE_H (3 rows) -- a fireball farther than ~400 units projects under 3
    rows and was not drawn at all until it came near; and behind a nearer sprite it was B-gated;
  * the crowd: DEG_SOFT_MON -- after 4 monsters a monster needed 10 rows (~450 units).
The rule: no soft raise for monsters, a mobile is an actor (monster class and base bound), no B-gate for an actor, and
no slot for a sprite without a row in the view (every thing). The hosted tiers and deg_gate's picture keep the old
rule (HOSTED_RENDER_KW; deg_gate passes neither key).
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets/freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (the sprite art)")
COURT = (1424, 732, 0x40000000)                  # v5's R0-courtyard checkpoint, facing north across the open yard


def test_the_rule_is_the_game_pictures_alone():
    from doomfj.reference_model import GAME_RENDER_KW, HOSTED_RENDER_KW
    assert GAME_RENDER_KW["exempt_actors"] is True
    assert HOSTED_RENDER_KW["exempt_actors"] is False
    src = (ROOT / "scratchpad" / "deg_gate.py").read_text(encoding="utf-8")
    assert "exempt_actors" not in src and "GAME_RENDER_KW" not in src     # deg_gate's visual tier: unchanged


@pytest.fixture(scope="module")
def court():
    from doomfj.config import GAME_CFG
    from doomfj.monsters import MonsterPhase, MonsterViews
    from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    ph = MonsterPhase(mode="full", player="fx")
    w, ws = ph.world, ph.world.ws
    ws.px, ws.py, ws.pangle = COURT[0] << 16, COURT[1] << 16, COURT[2]
    rm = ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm, w.mw, w.mapname, art, w)
    sc = build_scene(w.mw, w.mw, w.mapname)
    st = SimState(ws.px, ws.py, ws.pangle, w.mapname)

    def render(**kw):
        return bytes(rm.render_wall_frame(st, sc, sprite_wad=art, thing_views=mv(ph, ws.px, ws.py),
                                          thing_positions=mv.positions(ph), **dict(GAME_RENDER_KW, **kw)))
    return render


def _diff(a, b):
    return sum(p != q for p, q in zip(a, b))


def test_a_far_fireball_is_drawn(court):
    """a fireball 500 units up the open courtyard: under 3 rows -- blocked48's picture drops it, the rule draws it"""
    mob = [(COURT[0] + 8, COURT[1] + 500, "BAL1A0")]
    assert _diff(court(mobiles=mob), court()) > 0, "the far fireball is not drawn under the actors rule"
    # R9 control: the old rule (scenery at MIN_SPRITE_H) does not draw it -- the case is one the rule changes
    assert _diff(court(mobiles=mob, exempt_actors=False), court(exempt_actors=False)) == 0


def test_a_near_fireball_still_draws_both_ways(court):
    mob = [(COURT[0] + 8, COURT[1] + 150, "BAL1A0")]
    assert _diff(court(mobiles=mob), court()) > 0 and _diff(court(mobiles=mob, exempt_actors=False),
                                                           court(exempt_actors=False)) > 0


def test_a_drop_is_scenery_not_an_actor(court, monkeypatch):
    """a DROP (a `mobiles` entry at z 0: the clip a zombieman left) is an ITEM on the floor -- the scenery class at
    MIN_SPRITE_H, B-gated (docs/gp-p67-interface.md section 5), as the fj bakes its row (monstercode.drop_view_rows:
    sp_mon 0, the base bound twice -- tests/fj/test_barrel_rowselect_fj.py). FOUND by b0 v6 on blocked50 (2026-10-06):
    the oracle drew a drop as an ACTOR, so behind its own corpse it took slot B where the binary B-gated it -- 44 of
    R0-northwest's 100 frames parted (1-53 px), and R0-south-hall, R0-imp-court, R2-barrel-hall, R2-spectre-corridor,
    R3-west, R3-mid likewise. Here: a clip 500 units up the open courtyard projects under 3 rows -- not drawn."""
    from doomfj.reference_model import MobileThing
    drop = [(COURT[0] + 8, COURT[1] + 500, "CLIPA0", 0)]
    assert MobileThing(0, 0, z=0).drop and not MobileThing(0, 0).drop and not MobileThing(0, 0, z=32).drop
    assert _diff(court(mobiles=drop), court()) == 0, "a far drop is drawn: the oracle treats it as an actor"
    # R9 control: the rule this replaced (every mobile an actor, at the monster base bound 1) draws it
    monkeypatch.setattr(MobileThing, "drop", property(lambda self: False))
    assert _diff(court(mobiles=drop), court()) > 0, "the case does not separate a scenery drop from an actor one"


def test_the_corpse_no_longer_hides_the_monsters_behind_it():
    """v5 R0-aftermath frame 57 (the player on a corpse; injected from tests/fixtures/p67_scenes.json): the old rule draws neither live monster in view, the rule
    draws both -- scratchpad/gp/p67e_visibility_probe.py's attribution, which is also its own R9 control"""
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import p67_scene_dump as SC
    import p67e_visibility_probe as V
    # the scene, INJECTED (M7 P6+P7): frame 57 as tests/fixtures/p67_scenes.json froze it -- the owner's tempo / turn /
    # fire changes moved v5's replay, not the scene
    w = SC.load_scene("aftermath57")
    mph = V.MonsterPhase.__new__(V.MonsterPhase)
    mph.world, mph.gd = w, V.S.gd
    row = V.frame_stats(V.P.Oracle(), mph, V.RMOD.DEG_SOFT_MON)
    assert row["miss_d"] >= 2 and row["miss_e"] == 0, row
