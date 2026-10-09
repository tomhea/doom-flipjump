"""M7 P8a K x I (the integration of packages K and I, docs/gp-final-plan.md 3.1): KNOCKBACK and INFIGHTING together in
the model at "final" / "final" -- the rules each package proved alone, where they meet:

  * a fireball's impact on a monster KNOCKS it (the missile the inflictor: away from the missile) AND switches its
    target to the shooter (the source);
  * a barrel's blast credits bar_src's monster (the switch) AND knocks with the barrel as the inflictor; the
    chainsaw's exception reads bar_src: a barrel a MONSTER set off knocks the monster even with the player's saw ready,
    a barrel the PLAYER set off does not;
  * a blast with no source (bar_src 0) passes source None: `_thrust` knocks (the inflictor is set), switches nothing.
The fj side of the barrel's half is tests/fj/test_barrel_fj.py's K x I section (kb_sp = bar_src == 1)."""
import pytest

from doomfj import gamedata as gd
from doomfj.combat import FIREBALL_INFO
from doomfj.world import TicEvents, World

C = (800, 400)            # test_infighting_model's open spot


@pytest.fixture(scope="module")
def base():
    return World(skill=gd.SK_HARD, monsters="final", player="final", sight_rule="los", monster_tics=1)


@pytest.fixture
def w(base):
    base.reset(gd.SK_HARD)
    base.teleport_player(C[0] << 16, (C[1] + 300) << 16)
    ws = base.ws
    for m in range(base.layout.nmon):
        if ws.mon_active[m] and max(abs(ws.mon_x[m] - C[0]), abs(ws.mon_y[m] - C[1])) < 400:
            base._list_remove(m, ws.mon_leaf[m])
            ws.mon_active[m] = ws.mon_solid[m] = ws.mon_shootable[m] = 0
    assert base._p_knock and base._fight
    return base


def _of(w, ty, n=0):
    return [m for m, t in enumerate(w.mon_things) if t.type == ty and w.ws.mon_active[m]][n]


def _place(w, m, x, y, target=0):
    w.teleport_monster(m, x, y)
    w.ws.mon_target[m] = target
    w.ws.mon_momx[m] = w.ws.mon_momy[m] = 0


def _fly(w, s, tics=40):
    ev = TicEvents(0)
    for _ in range(tics):
        if not w.ws.proj_active[s] or w.ws.proj_state[s] != gd.STATE_INDEX[FIREBALL_INFO.spawnstate] and \
                w.ws.proj_momx[s] == 0 and w.ws.proj_momy[s] == 0:
            break
        w._projectiles_phase(ev)
    return ev


def test_a_fireball_impact_knocks_and_switches_the_target(w):
    ws = w.ws
    imp, z = _of(w, 3001), _of(w, 3004)
    _place(w, imp, *C, target=2 + z)
    _place(w, z, C[0] + 100, C[1])                          # due east of the shooter
    ws.mon_threshold[z] = 0
    ws.mon_health[z] = 200                                  # survives the hit: the switch is a live monster's
    ev = TicEvents(0)
    w._spawn_fireball(imp, ev)
    ev = _fly(w, ev.proj_spawns[0][0])
    assert [h[:4] for h in ev.mon_hits] == [(imp, "fireball", "mon", z)]
    assert ws.mon_target[z] == 2 + imp, "the switch: the shooter is the source"
    assert ws.mon_momx[z] > 0 and abs(ws.mon_momy[z]) < ws.mon_momx[z], "the thrust: away from the missile (east)"


def _blast_setup(w, b=0):
    ws = w.ws
    bt = w.barrel_things[b]
    imp, z = _of(w, 3001), _of(w, 3004)
    near = [(bt.x + dx, bt.y + dy) for dx in (60, -60, 80, -80) for dy in (0, 20, -20)]
    spot = next(p for p in near if w.los_points((p[0] << 16, p[1] << 16), (bt.x << 16, bt.y << 16)))
    _place(w, imp, *spot, target=0)
    ws.mon_threshold[imp] = 0
    ws.mon_health[imp] = 500                                # survives every blast
    w.teleport_player((bt.x + 1500) << 16, bt.y << 16)       # out of the blast
    return b, imp, z, spot, bt


@pytest.mark.parametrize("saw", [False, True])
def test_a_blast_credits_bar_src_s_monster_and_knocks(w, saw):
    ws = w.ws
    b, imp, z, spot, bt = _blast_setup(w)
    if saw:
        ws.p_owned[gd.WP_CHAINSAW], ws.p_ready = 1, gd.WP_CHAINSAW
    ws.bar_src[b] = 2 + z
    w._radius_attack(b, TicEvents(0))
    assert ws.mon_target[imp] == 2 + z, "the switch: bar_src's monster is the source"
    sx, sy = spot[0] - bt.x, spot[1] - bt.y
    assert (ws.mon_momx[imp], ws.mon_momy[imp]) != (0, 0), "a monster set it off: the saw's exception does not apply"
    assert ws.mon_momx[imp] * sx + ws.mon_momy[imp] * sy > 0, "the thrust points away from the barrel"


@pytest.mark.parametrize("saw", [False, True])
def test_a_barrel_the_player_set_off_respects_the_saw(w, saw):
    ws = w.ws
    b, imp, _z, _spot, _bt = _blast_setup(w)
    if saw:
        ws.p_owned[gd.WP_CHAINSAW], ws.p_ready = 1, gd.WP_CHAINSAW
    ws.bar_src[b] = 1
    w._radius_attack(b, TicEvents(0))
    assert ws.mon_target[imp] == 1, "the switch: the player"
    assert ((ws.mon_momx[imp], ws.mon_momy[imp]) == (0, 0)) == saw


@pytest.mark.parametrize("saw", [False, True])
def test_a_sourceless_blast_knocks_and_switches_nothing(w, saw):
    ws = w.ws
    b, imp, _z, _spot, _bt = _blast_setup(w)
    if saw:
        ws.p_owned[gd.WP_CHAINSAW], ws.p_ready = 1, gd.WP_CHAINSAW
    ws.bar_src[b] = 0
    calls = []
    real = w._thrust
    w._thrust = lambda target, inflictor, source, dmg: (calls.append((target, inflictor, source)),
                                                        real(target, inflictor, source, dmg))
    try:
        w._radius_attack(b, TicEvents(0))
    finally:
        del w._thrust
    assert calls == [(("mon", imp), ("bar", b), None)], calls
    assert ws.mon_target[imp] == 0, "no source: no switch"
    assert (ws.mon_momx[imp], ws.mon_momy[imp]) != (0, 0), "the inflictor is set: the thrust, saw or not"


def test_thrust_takes_a_source_of_none(w):
    ws = w.ws
    m = _of(w, 3004)
    _place(w, m, *C)
    w._thrust(("mon", m), ("bar", 0), None, 20)
    assert (ws.mon_momx[m], ws.mon_momy[m]) != (0, 0)
    ws.mon_momx[m] = ws.mon_momy[m] = 0
    w._thrust(("mon", m), None, None, 20)                    # no inflictor: nothing (DOOM's NULL)
    assert (ws.mon_momx[m], ws.mon_momy[m]) == (0, 0)
