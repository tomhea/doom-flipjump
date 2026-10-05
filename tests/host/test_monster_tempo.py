"""M7 P6+P7 package E -- the owner's TEMPO (2026-10-05: "the enemies shooting and walking feels slow ... maybe run 2
ticks each time?"): the MONSTERS' world (the monster tic and its attacks, the fireballs, the barrels, the puffs and
blood) runs `world.MONSTER_TICS_PER_FRAME` = 2 DOOM tics a frame; the player, the doors, the lifts and `leveltime` one.

The model's rule is `World._monster_world`; these tests hold:
  * ONE frame at tempo 2 IS one frame at tempo 1 followed by one more monster-world tic -- the whole WorldState, on a
    fight (the player fires and is shot at), frame by frame. The control: the plain tempo-1 world parts from it;
  * the player half stays at one tic a frame (leveltime, the damage count's fade);
  * the gates' mirror (`MonsterPhase.tic`) steps the same tics as World.tic;
  * the frozen sets name their tempo: absent = 1 (v1 .. v5), the plan records the game's.
"""
import sys
from pathlib import Path

import pytest

from doomfj import world as W
from doomfj.world import KEYS, MONSTER_TICS_PER_FRAME, TicEvents, World

ROOT = Path(__file__).resolve().parents[2]
POSE = (41943040, 53215232, 591199480)          # v5's R0-imp-court checkpoint: 3 imps and a sergeant in view


def _keys(f: int) -> dict:
    """a fight's keys: fire on and off, a turn now and then (no movement: the twins stand where they are put)"""
    k = {n: False for n in KEYS}
    k["fire"] = f % 6 < 3
    k["turn_left"] = f % 17 == 0
    return k


def _world(tics: int) -> World:
    w = World(monsters="full", player="full", monster_tics=tics)
    w.ws.px, w.ws.py, w.ws.pangle = POSE
    return w


@pytest.fixture(scope="module")
def frames():
    """(tempo-2 digests, twin digests, tempo-1 digests, the tempo-2 world) over 40 frames"""
    a, b, c = _world(2), _world(1), _world(1)
    da, db, dc = [], [], []
    for f in range(40):
        a.tic(_keys(f))
        b.tic(_keys(f))
        b._monster_world(TicEvents(0))          # the twin's second monster tic, by hand
        c.tic(_keys(f))
        da.append(a.digest())
        db.append(b.digest())
        dc.append(c.digest())
    return da, db, dc, a


def test_the_tempo_is_two_and_one_definition():
    assert MONSTER_TICS_PER_FRAME == 2
    assert World(monsters="idle").monster_tics == MONSTER_TICS_PER_FRAME
    with pytest.raises(AssertionError):
        World(monsters="idle", monster_tics=0)


def test_one_tempo_two_frame_is_a_frame_and_one_more_monster_tic(frames):
    da, db, _dc, a = frames
    parted = [f for f in range(len(da)) if da[f] != db[f]]
    assert not parted, "tempo 2 parts from frame + one more monster tic at frames %s" % parted[:5]
    tot = a.event_totals()
    assert tot["fired"] > 0 and tot["hits"] > 0, tot           # the player fought ...
    assert tot["mon_shots"] + tot["mon_melee"] + tot["proj_spawns"] > 0, tot   # ... and was attacked


def test_control_tempo_one_parts(frames):
    da, _db, dc, _a = frames
    assert any(x != y for x, y in zip(da, dc)), "the tempo is not observed: tempo 1 and 2 never part"


def test_the_player_half_stays_at_one_tic_a_frame():
    w = _world(2)
    w.ws.p_damagecount = 10
    lt = w.ws.leveltime
    w.tic({n: False for n in KEYS})
    assert w.ws.leveltime == lt + 1
    # the damage count fades once a frame (the player phase); a hit this frame may add to it, never a second fade
    assert w.ws.p_damagecount >= 9


def test_the_monster_phase_mirror_steps_the_world_tempo():
    from doomfj.monsters import MonsterPhase
    a = MonsterPhase(mode="full", player="fx")
    b = MonsterPhase(mode="full", player="fx")
    assert a.world.monster_tics == MONSTER_TICS_PER_FRAME
    b.world.monster_tics = 1
    for ph in (a, b):
        ph.world.ws.px, ph.world.ws.py, ph.world.ws.pangle = POSE
    for _f in range(30):
        a.tic()
        b.tic()
        b.tic()                                   # tempo 1, twice a frame == tempo 2 once
        assert a.world.digest() == b.world.digest()


def test_the_sets_name_their_tempo():
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import scenarios_v2 as S
    try:
        S.use_sight_rule({"sight_rule": "seen"})
        assert S.MONSTER_TICS == 1                                       # v1 .. v5: absent = 1
        w = S.apply_sight_rule(World(monsters="idle"))
        assert w.monster_tics == 1
        S.use_sight_rule({"sight_rule": "los", "monster_tics": W.MONSTER_TICS_PER_FRAME})
        assert S.apply_sight_rule(World(monsters="idle")).monster_tics == 2
    finally:
        S.use_sight_rule({})
    src = (ROOT / "scratchpad" / "gp" / "scenarios_v2.py").read_text(encoding="utf-8")
    assert 'doc["monster_tics"] = MONSTER_TICS' in src                  # a new plan records its tempo
