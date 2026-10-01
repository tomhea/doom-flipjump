"""M7 P3.2c (host): the `decide` model mode (docs/gp-monsters.md 8.5) -- awake monsters decide melee and missile
attacks and run their attack states, FACING and ROLLING as the full model does, but apply nothing (damage and the
fireball are P5). Each claim has its control: the chase mode decides nothing, and the stream comparison catches a
decide mode that forgets its rolls."""
import pytest

from doomfj.world import TicEvents, World

TICS = 210                            # the reaction time runs out near tic 70; ~20 decisions by 210
CELLS = ("mon_state", "mon_tics", "mon_facing", "mon_rng", "mon_movecount", "mon_movedir", "mon_x", "mon_y",
         "mon_justattacked", "mon_reaction", "mon_threshold", "mon_target")


def _awake(mode: str) -> World:
    w = World(monsters=mode, sight_rule="seen")
    w.wake_all()
    return w


def _tic(w: World) -> TicEvents:
    for m in range(w.layout.nmon):
        w.ws.mon_seen[m] = 1              # every monster sees the player: the modes differ only in what they DO
    ev = TicEvents(0)
    w._monsters_phase(ev)
    return ev


def _cells(w: World):
    n = w.layout.nmon
    return {c: tuple(getattr(w.ws, c)[:n]) for c in CELLS}


def test_decide_attacks_and_applies_nothing():
    w = _awake("decide")
    hp = w.ws.p_health
    evs = [_tic(w) for _ in range(TICS)]
    kinds = {k for e in evs for _, k in e.decisions}
    assert "missile" in kinds, kinds
    assert sum(len(e.attacks) for e in evs) > 10, "the attack states ran no attack action"
    assert sum(len(e.moves) for e in evs) > 0, "the decide mode stopped moving"
    assert not any(e.player_hurt or e.mon_shots or e.mon_melee or e.proj_spawns or e.fizzles for e in evs)
    assert w.ws.p_health == hp


def _lockstep(decide: World, full: World):
    """tic both until the full model's player dies; return (tics compared, attack actions in them, first part)"""
    tics = attacks = 0
    for _ in range(TICS):
        if not full.player_alive():
            break
        ed, ef = _tic(decide), _tic(full)
        if _cells(decide) != _cells(full) or ed.decisions != ef.decisions or ed.attacks != ef.attacks:
            return tics, attacks, tics
        tics += 1
        attacks += len(ef.attacks)
    return tics, attacks, None


def test_decide_tracks_the_full_models_monsters():
    tics, attacks, parted = _lockstep(_awake("decide"), _awake("full"))
    assert parted is None, "the decide mode parted from the full model at tic %d" % parted
    assert attacks >= 5, "only %d attack actions in %d tics: the comparison is vacuous" % (attacks, tics)


def test_control_rolls_forgotten_part(monkeypatch):
    """R9: a decide mode that faces but draws nothing must part from the full model"""
    monkeypatch.setattr(World, "_attack_rolls", lambda self, m, action: None)
    _tics, _attacks, parted = _lockstep(_awake("decide"), _awake("full"))
    assert parted is not None, "the lockstep did not notice the missing rolls"


@pytest.mark.parametrize("mode", ["chase"])
def test_control_chase_decides_nothing(mode):
    w = _awake(mode)
    evs = [_tic(w) for _ in range(TICS)]
    assert not any(e.decisions or e.attacks for e in evs)
