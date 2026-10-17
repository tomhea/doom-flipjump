"""M8 F1.3 item 9 (docs/f1-big-map-widths.md 9) -- the RENDER half of a thing on a mover's floor: `baked_thing_mask`
makes every drawable thing in a mover's leaf (`things.mover_leaves`, the one helper every mirror takes) RUNTIME, whose
leaf floor `ss_flr` follows the mover's state, so the sprite stands on the moved floor as the oracle draws it.

  * E1M1: no drawable thing stands in a mover leaf -- its mask, with or without the keyword, is the one it always was
    (`mover_mask_kw` passes nothing), so its binary cannot move;
  * E1M2: exactly the things on its movers' floors (the blue card on switch sector 45, the soulsphere on turbo floor
    358, the backpack on 241, the items on floor 206 and on lift 47) leave the baked set; the leaves stay homogeneous.
CONTROL (R9): the keyword dropped, E1M2's card stays baked -- its z then its stored floor."""
from pathlib import Path

import pytest

from doomfj import things as TH
from doomfj.mapcompiler import bake_bsp
from doomfj.reference_model import MONSTER_TYPES, ReferenceModel
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
FIX = ROOT / "tests" / "fixtures"

pytestmark = pytest.mark.skipif(not ART.exists(), reason="assets/freedoom1.wad (the sprite art) is not here")


def _mask(mapname, wadname):
    rm = ReferenceModel()
    mw = WadFile.from_path(FIX / wadname)
    cmap = bake_bsp(mw, mapname)
    drawable, _ = TH.drawable_things(rm, mw.things(mapname), WadFile.from_path(ART))
    leaves = TH.mover_leaves(mw, mapname, cmap)
    kw = TH.mover_mask_kw(rm, cmap, drawable, leaves)
    return (rm, cmap, drawable, leaves, kw, TH.baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES),
            TH.baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES, **kw))


def test_e1m1_mask_is_unchanged():
    rm, cmap, drawable, leaves, kw, old, new = _mask("E1M1", "freedoom_e1m1.wad")
    assert len(leaves) == 9 and kw == {}, "E1M1's lifts and pillars hold no drawable thing"
    assert new == old
    assert TH.baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES, mover_leaves=leaves) == old


def test_e1m2_things_on_movers_run():
    rm, cmap, drawable, leaves, kw, old, new = _mask("E1M2", "freedoom_e1m2.wad")
    assert kw == {"mover_leaves": leaves}
    moved = sorted(drawable[i].type for i in range(len(drawable)) if old[i] != new[i])
    assert moved == sorted([5, 2049, 2013, 8, 2015, 2007])
    for i, t in enumerate(drawable):
        if rm.point_in_subsector(cmap, t.x, t.y) in leaves:
            assert not new[i], (i, t.type)
    # homogeneous leaves at spawn (M14.5's invariant)
    by_leaf = {}
    for i, t in enumerate(drawable):
        by_leaf.setdefault(rm.point_in_subsector(cmap, t.x, t.y), set()).add(new[i])
    assert all(len(v) == 1 for v in by_leaf.values())


def test_control_without_the_keyword_the_card_stays_baked():
    rm, cmap, drawable, leaves, kw, old, new = _mask("E1M2", "freedoom_e1m2.wad")
    card = next(i for i, t in enumerate(drawable) if t.type == 5)
    assert old[card] and not new[card]
