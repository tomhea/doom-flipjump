"""Every tier EMITS -- on the one-sector room, in seconds, so a path only some tiers take cannot break
unseen until tests/fj's half-hour run (M7 P1.5: the boot-visibility default read `_vis_slots`, which
only a tier with things defines, and the render tier crashed in `emit_wall_renderer` -- caught by
tests/fj/test_lines_render.py, sixteen minutes in; this is the same failure in a few seconds).

The room has no things, doors or sky, so this proves emission, not pictures: the byte-exact tests
are tests/fj's and the gates'.
"""
import pytest

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"          # one sector, map MAP01, no things
ASSETS = "tests/fixtures/freedoom_assets.wad"      # the textures / palette tests/fj renders it with
ART = "assets/freedoom1.wad"                       # the sprite tiers' art


@pytest.mark.parametrize("tier", sorted(wr.TIERS))
def test_every_tier_emits_on_the_one_room_map(tier):
    parts = wr.emit_wall_renderer(WadFile.from_path(ROOM), "MAP01", Config(), tier=tier,
                                  asset_wad=WadFile.from_path(ASSETS),
                                  sprite_wad=WadFile.from_path(ART), return_parts=True)
    assert parts and all(isinstance(n, str) and isinstance(t, str) and t for n, t in parts)
