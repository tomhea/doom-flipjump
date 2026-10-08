"""M7 P8a I: a fireball's thing test (projcode `pt_thing`) runs INSIDE the pool window (pw_*: the slot copied in, written
back by pool_tic's pj_out) and calls dm_go -- whose kill of a dropper links the drop through that same window
(damagecode's drop_link<k> -> barrelcode's dr_link / dr_take). blocked52 fight_gate F6 frame 44: imp 36's fireball
killed shotgun guy 35 and was written back with the corpse's leaf (thss_rt 638, the model 621).

`pt_thing` keeps the window across dm_go. This pins, on the EMITTED text, that every window register the drop leaves
write is one pt_thing saves and restores -- so a new write there cannot slip past. The engine proof is
tests/fj/test_fireball_pool_fj.py (the dm_go stub borrows the window; mutant `window_lost`)."""
import re

import pytest

from doomfj import barrelcode as BC
from doomfj import projcode as PC
from doomfj.world import World

WRITE = re.compile(r"^\s+hex\.(?:mov|zero|set|not|inc|dec|add|sub|xor_by)\s+[^,]+,\s*(pw_\w+)")


@pytest.fixture(scope="module")
def world():
    return World(monsters="final", player="final", sight_rule="seen")


def _block(lines, label):
    i = lines.index(label + ":")
    j = next(k for k in range(i + 1, len(lines)) if lines[k].strip().startswith("stl.fret"))
    return lines[i:j + 1]


def _drop_writes(world):
    n = world.layout.nmon
    bp = BC.barrel_parts(world, nt=68, slot_rt=list(range(n)), boot_skill=3, skills=(1, 2, 3), fight=True)
    out = set()
    for label in ("dr_link", "dr_take"):
        out |= {m.group(1) for ln in _block(bp["lines"], label) for m in [WRITE.match(ln)] if m}
    return out


def _kept(lines):
    """the window registers pt_thing saves before its dm_go AND restores after it"""
    t = _block(lines, "pt_thing")
    k = t.index("    stl.fcall dm_go, dm_ret")
    saved = {m.group(2): m.group(1) for ln in t[:k] for m in [re.match(r"\s+hex\.mov w/4, (pt_sv\w+), (pw_\w+)$", ln)]
             if m}
    restored = {m.group(1): m.group(2) for ln in t[k:] for m in [re.match(r"\s+hex\.mov w/4, (pw_\w+), (pt_sv\w+)$", ln)]
                if m}
    return {r for r, sv in saved.items() if restored.get(r) == sv}


def test_the_drop_leaves_write_the_window(world):
    assert {"pw_t", "pw_leaf"} <= _drop_writes(world)


def test_pt_thing_keeps_every_window_register_the_drop_leaves_write(world):
    lines = PC.pt_lines(PC.fight_things(world, list(range(world.layout.nmon))))
    assert _drop_writes(world) <= _kept(lines), sorted(_drop_writes(world) - _kept(lines))


def test_control_a_lost_restore_is_seen(world):
    """R9: pt_thing without its pw_leaf restore must fail the check"""
    lines = [ln for ln in PC.pt_lines(PC.fight_things(world, list(range(world.layout.nmon))))
             if ln != "    hex.mov w/4, pw_leaf, pt_svl"]
    assert not _drop_writes(world) <= _kept(lines)
