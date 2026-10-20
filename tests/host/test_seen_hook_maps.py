"""M8 (gen_dryrun on E1M5): sight.SeenHook hides the RUNTIME non-monster things (a pickup on a monster-reachable or
mover leaf: things.baked_thing_mask's runtime class) its skill does not spawn -- the renderer requires the runtime
hidden set to be exactly ONE skill's absent set (things.skill_absent). The hook hid only the inactive monsters, so its
picture REFUSED wherever such a thing exists: E1M5 at hard (the boot skill: every generator stopped on its first tic),
and E1M1 / E1M2 at easy and medium (no gate runs the seen rule there -- a latent crash, not a moved result).

  - E1M1 / E1M2 at hard (the boot skill every gate and set runs): the added set is EMPTY -- nothing that ran moves;
  - E1M5 at hard, E1M1 and E1M2 at easy: a world with the seen rule tics, and the CONTROL (R9) -- the old hook, which
    hid only the inactive monsters -- refuses on that same first tic.
E1M5's model refuses its thing types until C6 / C7 land; the test drops them (gen_dryrun's `unknown-things`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for q in (ROOT / "src", ROOT / "scratchpad" / "gp"):
    if str(q) not in sys.path:
        sys.path.insert(0, str(q))


def _world(m, skill=None, monkeypatch=None):
    from doomfj import gamedata as gd
    from doomfj.wad import WadFile
    from doomfj.world import World
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_MODE, PLAYER_MODE
    if monkeypatch is not None:
        orig = WadFile.things
        monkeypatch.setattr(WadFile, "things", lambda self, name: [
            t for t in orig(self, name) if t.type in gd.THING_TYPES or t.type in gd.NOT_THINGS])
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / ("freedoom_%s.wad" % m.lower())))
    return World(mw, m, skill=BOOT_SKILL if skill is None else skill, monsters=MONSTER_MODE, player=PLAYER_MODE)


@pytest.mark.parametrize("m", ["E1M1", "E1M2"])
def test_added_set_empty_at_the_boot_skill(m):
    from doomfj.sight import SeenHook
    from doomfj.wall_renderer import BOOT_SKILL
    assert SeenHook(_world(m))._absent_rt(BOOT_SKILL) == set(), m


@pytest.mark.parametrize("m,skill_name", [("E1M5", "hard"), ("E1M1", "easy"), ("E1M2", "easy")])
def test_seen_picture_tics_and_control_refuses(m, skill_name, monkeypatch):
    from doomfj import gamedata as gd
    from doomfj.sight import SeenHook
    from doomfj.world import KEYS
    skill = gd.SKILL_NAMES[skill_name]
    mp = monkeypatch if m == "E1M5" else None
    w = _world(m, skill, mp)
    hook = SeenHook(w)
    assert hook._absent_rt(skill), "%s at %s has no runtime non-monster thing absent (the test proves nothing)" % (
        m, skill_name)
    w.set_sight_rule("seen", hook)
    w.tic({k: False for k in KEYS})                       # the fix: the first seen picture renders
    # CONTROL: the hook as it was (inactive monsters only) refuses on the same tic
    w2 = _world(m, skill, mp)
    old = SeenHook(w2)
    monkeypatch.setattr(old, "_absent_rt", lambda s: set())
    w2.set_sight_rule("seen", old)
    with pytest.raises(AssertionError, match="not one skill's absent set"):
        w2.tic({k: False for k in KEYS})
