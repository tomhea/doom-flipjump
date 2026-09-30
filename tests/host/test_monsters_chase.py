"""M7 P3.2b (host): the `chase` model mode (docs/gp-monsters.md 8.4) -- awake monsters MOVE (P_Move, NewChaseDir,
the relink) and decide no attack. Each claim has its control: the wake mode does not move, the full mode decides."""
from doomfj.world import TicEvents, World

TICS = 70


def _awake(mode: str) -> World:
    w = World(monsters=mode, sight_rule="seen")
    w.wake_all()
    return w


def _run(w: World):
    evs = []
    for _ in range(TICS):
        for m in range(w.layout.nmon):
            w.ws.mon_seen[m] = 1          # every monster sees the player: the modes differ only in what they DO
        ev = TicEvents(0)
        w._monsters_phase(ev)
        evs.append(ev)
    return evs


def test_chase_moves_relinks_and_decides_nothing():
    w = _awake("chase")
    x0 = list(w.ws.mon_x[:w.layout.nmon]), list(w.ws.mon_y[:w.layout.nmon])
    evs = _run(w)
    moves = sum(len(e.moves) for e in evs)
    assert moves > 100, moves
    assert sum(e.tries for e in evs) >= moves
    assert sum(e.newchasedir for e in evs) > 0
    assert not any(e.decisions or e.attacks for e in evs), "the chase mode decided an attack"
    assert (list(w.ws.mon_x[:w.layout.nmon]), list(w.ws.mon_y[:w.layout.nmon])) != x0
    assert any(e.leaf_changes for e in evs), "nobody changed leaf in %d tics" % TICS
    assert w.leaf_lists() == w.leaf_lists_from_scratch(), "the relinked lists parted from the positions"


def test_control_wake_does_not_move():
    evs = _run(_awake("wake"))
    assert sum(len(e.moves) for e in evs) == 0 and sum(e.tries for e in evs) == 0


def test_control_full_decides():
    evs = _run(_awake("full"))
    assert any(e.decisions for e in evs), "the full mode decided nothing: the chase test's 'no decision' is vacuous"
