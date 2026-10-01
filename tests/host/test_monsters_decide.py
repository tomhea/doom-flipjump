"""M7 P3.2c (host): the `decide` model mode (docs/gp-monsters.md 8.5) -- awake monsters decide melee and missile
attacks and run their attack states, FACING and ROLLING as the full model does, but apply nothing (damage and the
fireball are P5). Each claim has its control: the chase mode decides nothing, and the stream comparison catches a
decide mode that forgets its rolls.

The lockstep runs twice: every monster seen from the player's start (the attack sight never traces), and the player
PARKED by a monster each tic with most seen flags off (`_parker`), so the attack sight takes its near-LOS branch --
clear and blocked -- and the test counts the traces."""
import random

import pytest

from doomfj.world import TicEvents, World

TICS = 210                            # the reaction time runs out near tic 70; ~20 decisions by 210
CELLS = ("mon_state", "mon_tics", "mon_facing", "mon_rng", "mon_movecount", "mon_movedir", "mon_x", "mon_y",
         "mon_justattacked", "mon_reaction", "mon_threshold", "mon_target")
PARK_SEED = 3                         # a seed whose parked run traces both ways (10 clear, 3 blocked) in 210 tics
M32 = 0xFFFFFFFF
DIRS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))


def _awake(mode: str) -> World:
    w = World(monsters=mode, sight_rule="seen")
    w.wake_all()
    return w


def _tic(w: World, park=None) -> TicEvents:
    """one monster phase; `park` = (px, py, seen flags) for this tic, else every monster seen from where the
    player stands"""
    n = w.layout.nmon
    if park is None:
        for m in range(n):
            w.ws.mon_seen[m] = 1          # every monster sees the player: the modes differ only in what they DO
    else:
        w.ws.px, w.ws.py, seen = park
        for m in range(n):
            w.ws.mon_seen[m] = seen[m]
    ev = TicEvents(0)
    w._monsters_phase(ev)
    return ev


def _s32(v: int) -> int:
    return v - (1 << 32) if v >> 31 else v


def _parker(seed: int):
    """-> park(w): this tic's (px, py, seen), the player put 40..300 units from an active monster (a new one every
    10 tics; the monster's CURRENT position in `w`) at a random 16.16 fraction, the monster itself unseen and each
    other one seen with probability 0.3 -- so the attack sight is often the near trace"""
    rnd = random.Random(seed)
    state = {"t": 0, "tg": None}

    def park(w: World):
        n = w.layout.nmon
        if state["t"] % 10 == 0:
            state["tg"] = rnd.choice([m for m in range(n) if w.ws.mon_active[m]])
        state["t"] += 1
        tg = state["tg"]
        r = rnd.choice((40, 50, 90, 120, 300))
        dx, dy = DIRS[rnd.randrange(8)]
        k = r if dx * dy == 0 else r * 7 // 10
        x16 = _s32(((w.ws.mon_x[tg] + dx * k) << 16 | rnd.randrange(1 << 16)) & M32)
        y16 = _s32(((w.ws.mon_y[tg] + dy * k) << 16 | rnd.randrange(1 << 16)) & M32)
        return x16, y16, [int(m != tg and rnd.random() < 0.3) for m in range(n)]
    return park


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


def _lockstep(decide: World, full: World, park=None):
    """tic both until the full model's player dies; return (tics compared, attack actions in them, first part).
    `park` (a `_parker`): both worlds get the same player position and seen flags, placed by the decide world's
    monsters -- the full one's while the two agree"""
    tics = attacks = 0
    for _ in range(TICS):
        if not full.player_alive():
            break
        p = park(decide) if park else None
        ed, ef = _tic(decide, p), _tic(full, p)
        if _cells(decide) != _cells(full) or ed.decisions != ef.decisions or ed.attacks != ef.attacks:
            return tics, attacks, tics
        tics += 1
        attacks += len(ef.attacks)
    return tics, attacks, None


def _counting_traces(monkeypatch) -> dict:
    """count the decide world's `los_to_player` calls by result -- the attack sight's near-trace branch"""
    traces = {True: 0, False: 0}
    base = World.los_to_player

    def counting(world, m):
        v = base(world, m)
        if world.monsters == "decide":
            traces[bool(v)] += 1
        return v
    monkeypatch.setattr(World, "los_to_player", staticmethod(counting))
    return traces


def test_decide_tracks_the_full_models_monsters(monkeypatch):
    traces = _counting_traces(monkeypatch)
    tics, attacks, parted = _lockstep(_awake("decide"), _awake("full"))
    assert parted is None, "the decide mode parted from the full model at tic %d" % parted
    assert attacks >= 5, "only %d attack actions in %d tics: the comparison is vacuous" % (attacks, tics)
    # the trace counter's control: every monster is seen, so the attack sight never traces -- the parked run
    # below is the one that does
    assert traces == {True: 0, False: 0}, traces


def test_decide_tracks_the_full_models_monsters_through_near_traces(monkeypatch):
    """the same lockstep with the player parked by the monsters and most of them unseen: the attack sight runs the
    near LOS, both clear and blocked, and the two modes still agree"""
    traces = _counting_traces(monkeypatch)
    tics, attacks, parted = _lockstep(_awake("decide"), _awake("full"), _parker(PARK_SEED))
    assert parted is None, "the decide mode parted from the full model at tic %d" % parted
    assert attacks >= 5, "only %d attack actions in %d tics: the comparison is vacuous" % (attacks, tics)
    assert traces[True] >= 3 and traces[False] >= 2, "the near-trace branch barely ran: %s" % traces


@pytest.mark.parametrize("parked", [False, True])
def test_control_rolls_forgotten_part(monkeypatch, parked):
    """R9: a decide mode that faces but draws nothing must part from the full model -- in both runs"""
    monkeypatch.setattr(World, "_attack_rolls", lambda self, m, action: None)
    park = _parker(PARK_SEED) if parked else None
    _tics, _attacks, parted = _lockstep(_awake("decide"), _awake("full"), park)
    assert parted is not None, "the lockstep did not notice the missing rolls"


@pytest.mark.parametrize("mode", ["chase"])
def test_control_chase_decides_nothing(mode):
    w = _awake(mode)
    evs = [_tic(w) for _ in range(TICS)]
    assert not any(e.decisions or e.attacks for e in evs)
