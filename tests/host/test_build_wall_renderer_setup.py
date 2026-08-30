"""`build_wall_renderer`'s SETUP, without the 20-minute build.

WHY THIS EXISTS. The tier refactor rewrote this function's whole signature and every derivation in
it -- the flat limit, the generated directory, the restore set, the sprite wad -- and shipped with
`limit = cfg.RENDER_FLAT_MAX_WORDS`, which raises `AttributeError` because that is a MODULE
constant in `config.py`, not a field of the frozen `Config`. Every caller was dead on the first
line, and none of the evidence noticed: `emit_baseline` and `deg_gate` call `emit_wall_renderer`
directly, `tests/fj` never calls the builder at all, and the one host test that does is the `slow`
one that `addopts` deselects. `449 passed, 1 deselected` executed not one changed line of build.py.

So this stubs the two expensive things -- the emitter and the assembler -- and asserts what the
function DERIVES. It costs milliseconds and it would have caught that on the first run.
"""

import pytest

from doomfj import build as B
from doomfj.config import DEFAULT_MAP_WAD, RENDER_FLAT_MAX_WORDS
from doomfj.wall_renderer import TIERS, tier_flags


def _run(tmp_path, **kw):
    seen = {}

    def fake_emit(wad, mapname, cfg, **k):
        seen.update(k)
        seen["mapname"] = mapname
        seen["wad_lumps"] = wad is not None
        raise _Stop()

    class _Stop(Exception):
        pass

    import doomfj.build as mod
    real = mod.emit_wall_renderer
    mod.emit_wall_renderer = fake_emit
    try:
        mod.build_wall_renderer(tmp_path / "out.fjm", **kw)
    except _Stop:
        pass
    finally:
        mod.emit_wall_renderer = real
    return seen


def test_it_gets_past_its_own_first_lines(tmp_path):
    """THE regression. `cfg.RENDER_FLAT_MAX_WORDS` raised AttributeError before the emitter was
    ever reached, so every caller died on setup and every gate missed it."""
    seen = _run(tmp_path)
    assert seen, "build_wall_renderer never reached the emitter"


def test_the_tier_reaches_the_emitter_unchanged(tmp_path):
    for tier in sorted(TIERS):
        assert _run(tmp_path, tier=tier)["tier"] == tier


def test_each_tier_means_exactly_what_it_says():
    """The registry PINNED, flag by flag.

    Without this, `test_the_tier_reaches_the_emitter_unchanged` passes for a tier whose contents
    silently changed -- it only checks the NAME is forwarded. Proven: mutating `hosted` to drop
    collision and the runtime thing table left that test green. A tier quietly meaning something
    else is the exact failure the registry exists to prevent, so the meanings live here where a
    diff shows them."""
    expected = {
        "game":        "things player_sim collide moving_things standalone menu doors self_reset",
        "hosted":      "things player_sim collide moving_things",
        "hosted-doors": "things player_sim collide moving_things doors",
        "hosted-loop": "things player_sim collide moving_things self_reset",
        "hosted-nocollide": "things player_sim moving_things",
        "hosted-static": "things player_sim collide",
        "hosted-nosim-nocollide": "things player_sim",
        "visual":      "things",
        "render":      "",
        "loop":        "self_reset",
    }
    assert set(expected) == set(TIERS), (
        "TIERS changed shape -- add the new tier's meaning here deliberately. A tier is a promise "
        "about which program gets built; it does not get to change quietly.")
    for tier, want in expected.items():
        on = {f for f, v in tier_flags(tier).items() if v}
        assert on == set(want.split()), (tier, sorted(on), want)


def test_the_default_tier_is_the_game(tmp_path):
    """The owner's tier-1 flip: a bare call builds the playable binary."""
    assert _run(tmp_path)["tier"] == "game"
    assert tier_flags("game")["standalone"] and tier_flags("game")["self_reset"]


def test_the_generated_dir_is_derived_from_the_out_path(tmp_path):
    """It was a required parameter that every caller kept in step with `out_fjm` by hand."""
    import doomfj.build as mod

    class _Stop(Exception):
        pass

    real = mod.emit_wall_renderer
    mod.emit_wall_renderer = lambda *a, **k: (_ for _ in ()).throw(_Stop())
    try:
        with pytest.raises(_Stop):
            mod.build_wall_renderer(tmp_path / "doom_e1m1_menu.fjm")
    finally:
        mod.emit_wall_renderer = real
    assert (tmp_path / "generated_doom_e1m1_menu").is_dir()


def test_a_things_tier_resolves_sprite_art_and_a_render_tier_does_not(tmp_path):
    """`sprite_wad` stopped being a parameter, so the tier has to decide it."""
    assert _run(tmp_path, tier="visual")["sprite_wad"] is not None
    assert _run(tmp_path, tier="render")["sprite_wad"] is None


def test_an_unknown_tier_fails_loudly_and_names_the_choices():
    with pytest.raises(ValueError) as e:
        tier_flags("hosted_doors")          # underscore, not hyphen: the typo that would build
    assert "hosted-doors" in str(e.value)   # a different program in silence


def test_the_flat_limit_is_the_raised_one():
    """R4: the renderer needs 2**27, and `Config` does not carry it -- that is the bug above."""
    assert RENDER_FLAT_MAX_WORDS == 1 << 27
    assert not hasattr(B.Config(), "RENDER_FLAT_MAX_WORDS")


def test_the_default_map_exists():
    assert DEFAULT_MAP_WAD.is_file(), DEFAULT_MAP_WAD
