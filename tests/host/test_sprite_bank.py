"""M7 P1.6 -- the emitted sprite bank IS the native lists (docs/gp-sprite-bank.md).

`wall_renderer._lines_sprite_bank` bakes, for every drawn kind and every animation view (each frame
and rotation of the map's monsters, barrels, fireballs, puffs and blood), three regions of 64-op
blocks -- HD, MID, LD -- holding `doomfj.spritebank`'s lists. These decode the emitted TEXT back to
cells and require every block to be `sprite_block_body` of `sprite_tier_lists` of that patch: the
lists the oracle draws with, so the two mirrors share one source. The animation's views are checked
against the wad's own lump names (every frame has rotation 0 or all eight; a mirrored view is its
pair's lump), and the size against the per-bucket bank it replaces.
"""
import re

import pytest

from doomfj import wall_renderer as wr
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SPRITE_HEIGHT_BUCKETS
from doomfj.wad import WadFile

MW = WadFile.from_path("tests/fixtures/freedoom_e1m1.wad")
ART_PATH = "assets/freedoom1.wad"
CFG = Config()
_CELL = re.compile(r"^;(0x[0-9a-f]+|\d+) \* dw$")


@pytest.fixture(scope="module")
def bank():
    art = WadFile.from_path(ART_PATH)
    rm = ReferenceModel(CFG)
    text, base, dw, ld, anim = wr._lines_sprite_bank(rm, art, CFG, MW, "E1M1")
    lines = text.splitlines()
    head = wr.sprite_bank_header()
    assert lines[:len(head)] == head
    cells = [int(_CELL.match(ln).group(1), 0) for ln in lines[len(head):]]
    assert len(cells) % wr.SPR_BLOCK_STRIDE == 0
    blocks = [cells[i:i + wr.SPR_BLOCK_STRIDE] for i in range(0, len(cells), wr.SPR_BLOCK_STRIDE)]
    return rm, art, blocks, base, dw, ld, anim


def _region_ok(blocks, first, lists):
    """the blocks from `first` on are exactly `lists`' bodies, each zero-padded"""
    for k, bl in enumerate(lists):
        body = wr.sprite_block_body(bl, SPRITE_HEIGHT_BUCKETS)
        want = body + [0] * (wr.SPR_BLOCK_STRIDE - len(body))
        if blocks[first + k] != want:
            return False
    return True


def test_every_kind_holds_its_three_tiers_native_lists(bank):
    rm, art, blocks, base, dw, ld, _anim = bank
    cache = {}
    for kind, b0 in base.items():
        tiers = wr.sprite_tier_lists(rm.sprite_art(art, kind, cache), CFG)
        assert len(tiers) == 3 and all(len(t) == dw[kind] for t in tiers)
        for t, lists in enumerate(tiers):
            assert _region_ok(blocks, b0 + t * dw[kind], lists), (kind, t)
        assert ld[kind] == b0 + 2 * dw[kind]            # the record's sp_base2


def test_every_animation_view_holds_its_patchs_lists(bank):
    rm, art, blocks, _base, _dw, _ld, anim = bank
    cache = {}
    patches = wr.anim_patches(art, wr.anim_frames(MW, "E1M1"))
    assert set(anim) == set(patches)
    for key, (b0, dwid, mirrored) in anim.items():
        lump, m = patches[key]
        assert m == mirrored
        tiers = wr.sprite_tier_lists(rm.art_of_lump(art, lump, cache), CFG)
        assert all(len(t) == dwid for t in tiers)
        for t, lists in enumerate(tiers):
            assert _region_ok(blocks, b0 + t * dwid, lists), (key, lump, t)


def test_the_views_follow_the_wads_lump_names(bank):
    """rotation 0 or all eight, per frame; a mirrored view is its pair's lump (`TROOA2A8` is
    rotation 2 and, mirrored, 8); and the monsters' walk frames really have eight"""
    _rm, art, _b, _base, _dw, _ld, _anim = bank
    frames = wr.anim_frames(MW, "E1M1")
    patches = wr.anim_patches(art, frames)
    for sprite, idxs in frames.items():
        for fi in idxs:
            letter = chr(ord("A") + fi)
            rots = {r for (s, lt, r) in patches if s == sprite and lt == letter}
            assert rots == {0} or rots == set(range(1, 9)), (sprite, letter, rots)
    for (s, lt, r), (lump, mirrored) in patches.items():
        if mirrored:
            assert len(lump) == 8 and lump[6] == lt and int(lump[7]) == r, (s, lt, r, lump)
        else:
            assert lump[4] == lt and int(lump[5]) == r, (s, lt, r, lump)
    assert {r for (s, lt, r) in patches if s == "TROO" and lt == "A"} == set(range(1, 9))
    assert any(m for (_l, m) in patches.values()), "no mirrored view at all: the pairs were missed"


# DOOM's frames (info.c's states) for E1M1's actors: the zombieman, the shotgun guy, the imp and the
# demon / spectre on the map, and the barrel, the imp's fireball, the puff and the blood -- pinned, so
# a change to gamedata's tables or to anim_frames' walk is a deliberate edit here
E1M1_FRAMES = {"POSS": "ABCDEFGHIJKLMNOPQRSTU", "SPOS": "ABCDEFGHIJKLMNOPQRSTU",
               "TROO": "ABCDEFGHIJKLMNOPQRSTU", "SARG": "ABCDEFGHIJKLMN", "BAR1": "AB",
               "BEXP": "ABCDE", "BAL1": "ABCDE", "PUFF": "ABCD", "BLUD": "ABC"}


def test_the_animation_covers_every_frame_of_the_maps_actors():
    frames = wr.anim_frames(MW, "E1M1")
    assert {k: "".join(chr(65 + i) for i in v) for k, v in frames.items()} == E1M1_FRAMES


def test_the_bank_is_smaller_than_the_per_bucket_bank_it_replaces(bank):
    """the per-bucket bank this one replaces is P1.5's: 27 kinds x 440 columns x 41 blocks = 18,040
    blocks (p16_size.log; before P1.5 dropped the multiplayer-only kinds it was 32 x 557 x 41 =
    22,837). Three native lists a column, with every animation view on top, must still be fewer"""
    blocks = bank[2]
    assert len(blocks) < 18040, len(blocks)


def test_a_changed_cell_is_caught(bank):
    """R9: the region check must notice ONE cell off -- here a list's min_b"""
    rm, art, blocks, base, dw, _ld, _anim = bank
    kind = sorted(base)[0]
    lists = wr.sprite_tier_lists(rm.sprite_art(art, kind, {}), CFG)[0]
    bad = [list(b) for b in blocks]
    bad[base[kind]][1] ^= 1
    assert _region_ok(blocks, base[kind], lists) and not _region_ok(bad, base[kind], lists)
