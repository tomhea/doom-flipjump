"""Every tier EMITS -- on the one-sector room, in seconds, so a path only some tiers take cannot break
unseen until tests/fj's half-hour run (M7 P1.5: the boot-visibility default read `_vis_slots`, which
only a tier with things defines, and the render tier crashed in `emit_wall_renderer` -- caught by
tests/fj/test_lines_render.py, sixteen minutes in; this is the same failure in a few seconds).

The room has no things, doors or sky, so this proves emission, not pictures: the byte-exact tests
are tests/fj's and the gates'. The last three tests give it two things, for the game tier's skill
refusal (M7 P1.5's kill criterion 1).
"""
import pytest

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.wad import Thing, WadFile

ROOM = "tests/fixtures/square_room.wad"          # one sector, map MAP01, no things
ASSETS = "tests/fixtures/freedoom_assets.wad"      # the textures / palette tests/fj renders it with
ART = "assets/freedoom1.wad"                       # the sprite tiers' art


@pytest.mark.parametrize("tier", sorted(wr.TIERS))
def test_every_tier_emits_on_the_one_room_map(tier):
    parts = wr.emit_wall_renderer(WadFile.from_path(ROOM), "MAP01", Config(), tier=tier,
                                  asset_wad=WadFile.from_path(ASSETS),
                                  sprite_wad=WadFile.from_path(ART), return_parts=True)
    assert parts and all(isinstance(n, str) and isinstance(t, str) and t for n, t in parts)


# -- M7 P1.5, kill criterion 1's emitter clause (docs/gp-ledger.md) --------------------------------
# A BAKED thing is code inside its leaf, so the only way a skill can leave one out is its `thvis`
# flag -- and only vanishable types have a flag. The game tier therefore refuses to emit a map where
# a baked thing WITHOUT a flag changes with the skill: it would be drawn at every skill. No E1M1
# thing is like that (docs/gp-skill-menu.md section 1), so the refusal is reached here, on the room
# with a floor lamp (baked, no flag) and a stimpack (baked, flagged) -- no monster, so both bake --
# and `things.skill_absent` told that easy lacks one of them. (Until the P1.5 review nothing reached
# the refusal at all.)
LAMP, STIM = 2028, 2011


def _room_with_things():
    mw = WadFile.from_path(ROOM)
    base = mw.things
    extra = [Thing(64, 64, 0, LAMP, 7), Thing(192, 192, 0, STIM, 7)]     # flags 7: every skill
    mw.things = lambda name: base(name) + extra
    return mw


def _emit_game(mw):
    return wr.emit_wall_renderer(mw, "MAP01", Config(), tier="game",
                                 asset_wad=WadFile.from_path(ASSETS),
                                 sprite_wad=WadFile.from_path(ART), return_parts=True)


def _easy_lacks(monkeypatch, thing_type):
    """`things.skill_absent` told that EASY does not spawn the room's `thing_type`"""
    from doomfj import gamedata as gd
    from doomfj import things
    real = things.skill_absent

    def fake(drawable, skill):
        mine = {i for i, t in enumerate(drawable) if t.type == thing_type}
        assert mine, "the room lost its type %d" % thing_type
        return real(drawable, skill) | mine if skill == gd.SK_EASY else real(drawable, skill)
    monkeypatch.setattr(things, "skill_absent", fake)


def test_the_game_tier_emits_the_room_with_a_lamp_and_a_stimpack():
    """the control for the refusal below: the same room, every thing on every skill, emits"""
    text = "\n".join(t for _n, t in _emit_game(_room_with_things()))
    assert "thvis:" in text and "hex.set 2, thvis + 0*2*dw, 0" not in text


def test_a_baked_thing_without_a_flag_may_not_change_with_the_skill(monkeypatch):
    """kill criterion 1: the emitter refuses a baked, flagless thing that a skill does not spawn"""
    _easy_lacks(monkeypatch, LAMP)
    with pytest.raises(AssertionError, match="change with the skill but have no thvis flag"):
        _emit_game(_room_with_things())


def test_a_flagged_thing_may_change_with_the_skill(monkeypatch):
    """R9: the refusal separates. The stimpack HAS a flag, so easy lacking it emits -- and easy's
    restart block clears that flag, which says the patched answer reached the emitter"""
    _easy_lacks(monkeypatch, STIM)
    text = "\n".join(t for _n, t in _emit_game(_room_with_things()))
    assert "hex.set 2, thvis + 0*2*dw, 0" in text
