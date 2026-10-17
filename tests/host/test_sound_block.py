"""M8 L0: `World.noise_alert` -- the sound REGIONS with ML_SOUNDBLOCK edges -- marks exactly the sectors DOOM's
P_RecursiveSound marks, on both maps, from every start sector.

The reference is a direct transcription of p_enemy.c's recursion over SECTORS (not regions): a sector is skipped when
already reached with no more blocks (`soundtraversed <= soundblocks + 1`), every two-sided line with a positive
opening at the current heights is followed, and a ML_SOUNDBLOCK line passes on with 1 only from 0. The model folds
the statically connected sectors into regions; a region is heard iff any of its sectors is, and then all of them are.
CONTROL (R9): a flood that ignores the marked lines hears MORE on E1M2 -- the comparison can fail."""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj.wad import WadFile
from doomfj.world import World

FIX = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module", params=["E1M1", "E1M2"])
def world(request):
    m = request.param
    return World(WadFile.from_path(FIX / ("freedoom_%s.wad" % m.lower())), m)


def recursive_sound(w, start: int, honour_block: bool = True) -> set:
    """P_RecursiveSound(start, 0) over sectors at the world's current heights: the sectors it marks"""
    lds, sds = w.lds, w.sds
    lines_of = {}
    for ld in lds:
        if not ld.flags & gd.ML_TWOSIDED or not 0 <= ld.back < len(sds):
            continue
        a, b = sds[ld.front].sector, sds[ld.back].sector
        lines_of.setdefault(a, []).append((ld, b))
        lines_of.setdefault(b, []).append((ld, a))
    traversed = {}

    def rec(sec, blocks):
        if sec in traversed and traversed[sec] <= blocks + 1:
            return
        traversed[sec] = blocks + 1
        for ld, other in lines_of.get(sec, []):
            (fa, ca), (fb, cb) = w._sector_hts(sec), w._sector_hts(other)
            if min(ca, cb) - max(fa, fb) <= 0:
                continue                                 # P_LineOpening: closed
            if honour_block and ld.flags & gd.ML_SOUNDBLOCK:
                if not blocks:
                    rec(other, 1)
            else:
                rec(other, blocks)
    rec(start, 0)
    return set(traversed)


def model_heard(w, start: int) -> set:
    """the sectors whose node `noise_alert` marks with the player standing in `start`"""
    for k in range(len(w.ws.snd_alert)):
        w.ws.snd_alert[k] = 0
    w.player_sector = lambda: start
    try:
        w.noise_alert()
    finally:
        del w.player_sector
    return {s for s in range(len(w.secs)) if w.ws.snd_alert[w.sector_node[s]]}


def test_noise_alert_is_p_recursivesound_from_every_sector(world):
    for start in range(len(world.secs)):
        assert model_heard(world, start) == recursive_sound(world, start), "start sector %d" % start


def test_e1m2_has_marked_lines_and_they_matter():
    """the map really exercises the block state: some start hears less than the flood that ignores the marks"""
    w = World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2")
    assert w._sound_block_static_edges or w._sound_block_door_edges
    assert any(recursive_sound(w, s) != recursive_sound(w, s, honour_block=False) for s in range(len(w.secs)))


def test_control_a_flood_ignoring_the_marks_is_caught():
    """CONTROL (R9): the model with its block edges turned into plain ones disagrees with P_RecursiveSound"""
    w = World(WadFile.from_path(FIX / "freedoom_e1m2.wad"), "E1M2")
    w._sound_door_edges = w._sound_door_edges + w._sound_block_door_edges
    w._sound_block_door_edges = []
    plain = w._sound_block_static_edges
    w._sound_block_static_edges = []
    # a static block edge joins two nodes for good: model it as an always-open door edge between their sectors
    rep = {}
    for s, n in enumerate(w.sector_node):
        rep.setdefault(n, s)
    w._sound_door_edges += [(rep[a], rep[b]) for a, b in plain]
    assert any(model_heard(w, s) != recursive_sound(w, s) for s in range(len(w.secs)))


# ---- M8 L5: the model's BLOCK DOOR edges (E1M2 has none), and the fj flood's E1M1 text --------------------------------
def _marked():
    """E1M1 with seeded ML_SOUNDBLOCK lines through doors, lifts and the switch (tests/fj/test_noise_block_fj.py's
    MARKED world)"""
    import dataclasses
    import random
    wad = WadFile.from_path(FIX / "freedoom_e1m1.wad")
    base = World(wad, "E1M1", monsters="idle")
    dyn = set(base.door_order) | set(base.mover_order)
    rnd = random.Random(0x5B)
    pick = set()
    for i, ld in enumerate(base.lds):
        if not ld.flags & gd.ML_TWOSIDED or not 0 <= ld.back < len(base.sds):
            continue
        a, b = base.sds[ld.front].sector, base.sds[ld.back].sector
        if a != b and rnd.random() < (0.5 if (a in dyn or b in dyn) else 0.25):
            pick.add(i)
    orig = wad.linedefs
    wad.linedefs = lambda m: [dataclasses.replace(ld, flags=ld.flags | gd.ML_SOUNDBLOCK) if i in pick else ld
                              for i, ld in enumerate(orig(m))]
    return World(wad, "E1M1", monsters="idle")


def _mix(w, seed):
    import random
    rnd = random.Random(seed)
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = rnd.randrange(w.door_nstates[si])
    for k, si in enumerate(w.lift_order):
        w.ws.l_state[k] = rnd.randrange(len(w.lift_stops[si]))
    w.ws.f_switch = rnd.randrange(2)
    w._door_phase_scene()


def test_block_door_edges_are_p_recursivesound_at_every_door_state():
    """the marked world's block edges through doors / movers, at random door, lift and switch states: the model
    marks exactly what P_RecursiveSound marks at those heights, from every start"""
    w = _marked()
    assert w._sound_block_door_edges and w._sound_block_static_edges
    differs = 0
    for seed in range(6):
        _mix(w, seed)
        for start in range(len(w.secs)):
            want = recursive_sound(w, start)
            assert model_heard(w, start) == want, "mix %d, start sector %d" % (seed, start)
            differs += want != recursive_sound(w, start, honour_block=False)
    assert differs, "the marks change nothing: the comparison cannot tell a flood that ignores them"


def test_e1m1_noise_text_is_frozen():
    """E1M1 has no ML_SOUNDBLOCK line: noisecode emits its one-level flood, byte for byte the text before M8 L5
    (sha256 of noise_leaf_lines + noise_decls + noise_restart_lines). CONTROL: the marked world's text differs."""
    import hashlib
    from doomfj import noisecode as NZ

    def digest(w):
        t = "\n".join(NZ.noise_leaf_lines(w) + ["#"] + NZ.noise_decls(w) + ["#"] + NZ.noise_restart_lines(w)) + "\n"
        return hashlib.sha256(t.encode()).hexdigest()
    w = World(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1", monsters="idle")
    assert digest(w) == "5127550cd3048c78de7efc12e9d21aa657b3bc4ed38d5571191aea74ee5880ed"
    assert digest(_marked()) != digest(w)
