"""M7 P8a package K (docs/gp-final-plan.md 1.2.2, 3.1 row K): KNOCKBACK in the model, against DOOM's own numbers
(Chocolate Doom's p_inter.c P_DamageMobj and p_mobj.c P_XYMovement, transcribed below as the reference):

  * the thrust: `damage * (FRACUNIT >> 3) * 100 / mass` along R_PointToAngle2(inflictor -> target), FixedMul'd into
    the target's momentum -- per mass (100: the player, zombiemen, sergeants, imps; 400: demons, spectres), from the
    inflictor's whole-unit position to the target's 16.16 one, with the RAW damage; the chainsaw's exception (its
    source the player holding the saw -- a blast whose barrel he set off too); no inflictor, no thrust;
  * the reversal: damage < 40, damage > health, target z - inflictor z > 64 -> ONE coin on the TARGET's stream (only
    then), and on an odd coin the angle + ANG180 and the thrust x4;
  * P_XYMovement: the MAXMOVE clamp, the POSITIVE-only halving test, `x + xmove/2` (C's truncation) then `xmove >>= 1`
    (an arithmetic shift), a refused try zeroing the momentum while the loop goes on, FRICTION (floor(mom * 29/32)),
    the STOPSPEED stop, the MF_CORPSE rule;
  * the monsters' conventions: a candidate whose integer part is where the monster stands is accepted untested (only
    its fraction moves); a corpse's try (height >> 2, no drop-off refusal);
  * drops left behind: the drop lies where the corpse was at the kill, drawn and taken there while the corpse slides;
  * the frame order: the thrust lands in damage, the player moves on it after his walk (dead or alive), a monster at
    the top of its turn in each monster tic; "full" is untouched.
Every check names what would break it; the controls at the end mutate the model and must be caught (R9)."""
import pytest

from doomfj import gamedata as gd
from doomfj import rng as R
from doomfj.reference_model import ANG180, PLAYER_HEIGHT
from doomfj.world import TicEvents, World

M32 = 0xFFFFFFFF
U = gd.FRACUNIT
LOW = (-296, 256)           # floor 0, a legal spot (check_position ok, 56 fits)
HIGH = (1909, 405)          # floor 128
P_START = None


def _world(**kw):
    kw.setdefault("monsters", "final")
    kw.setdefault("player", "final")
    return World(strict=True, **kw)


@pytest.fixture(scope="module")
def W0():
    return _world()


def fresh(W0):
    W0.reset(gd.SK_HARD)
    return W0


# ---- the reference: DOOM's arithmetic, independent of the model -----------------------------------------------------
def fixedmul(a, b):
    return (a * b) >> 16                      # 64-bit product, arithmetic shift (FixedMul)


def thrust_ref(w, dmg, mass, ix16, iy16, tx16, ty16, reverse=False):
    ang = w.rm.point_to_angle(ix16, iy16, tx16, ty16)
    t = dmg * (U >> 3) * 100 // mass
    if reverse:
        ang = (ang + ANG180) & M32
        t *= 4
    idx = ang >> w.rm.angle_shift
    return fixedmul(t, w.rm._finecos_idx(idx) - (1 << 32 if w.rm._finecos_idx(idx) >> 31 else 0)), \
        fixedmul(t, w.rm._finesin_idx(idx) - (1 << 32 if w.rm._finesin_idx(idx) >> 31 else 0))


def _active(w, kinds):
    return [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and w.mon_things[m].type in kinds]


# ---- the thrust -------------------------------------------------------------------------------------------------------
def test_the_masses_are_doom_s():
    """the two mass classes the fj shifts by: 100 (>> 3) and 400 (>> 5) -- what knockcode bakes per slot"""
    w = _world()
    assert {w.mon_info[m].mass for m in range(w.layout.nmon)} == {100, 400}
    assert gd.MOBJINFO["MT_PLAYER"].mass == 100
    assert gd.MOBJINFO["MT_SERGEANT"].mass == gd.MOBJINFO["MT_SHADOWS"].mass == 400


@pytest.mark.parametrize("dmg", [1, 5, 15, 39, 40, 128, 200])
def test_the_thrust_per_mass_and_angle(W0, dmg):
    """a player's shot on a zombieman and on a sergeant, from 8 directions: DOOM's thrust from the inflictor's whole
    units to the target's 16.16 position (with a fraction), added to the momentum it already had"""
    w = fresh(W0)
    ws = w.ws
    for m in _active(w, (3004, 9))[:3] + _active(w, (3002,))[:2]:
        mass = w.mon_info[m].mass
        for k in range(8):
            w.reset(gd.SK_HARD)
            ws = w.ws
            tx, ty = ws.mon_x[m], ws.mon_y[m]
            ws.mon_fx[m], ws.mon_fy[m] = 0x3A5C, 0xC001
            ws.mon_health[m] = 1000                          # no reversal (damage <= health)
            ox, oy = [(100, 0), (70, 70), (0, 100), (-70, 70), (-100, 0), (-70, -70), (0, -100), (70, -71)][k]
            ws.px, ws.py = ((tx + ox) << 16) + 0x8001, ((ty + oy) << 16) + 0xFFFF
            ws.mon_momx[m], ws.mon_momy[m] = 12345, -777
            w.damage_monster(m, dmg, ("player", -1), ("player", -1), TicEvents(0))
            dx, dy = thrust_ref(w, dmg, mass, (ws.px >> 16) << 16, (ws.py >> 16) << 16,
                                (tx << 16) + 0x3A5C, (ty << 16) + 0xC001)
            assert (ws.mon_momx[m], ws.mon_momy[m]) == (12345 + dx, -777 + dy), (m, k, dmg)
            # away from the shooter
            assert (dx > 0) == (ox < 0) or ox == 0, (dx, ox)


def test_the_player_is_thrust_by_the_raw_damage(W0):
    """armor saves health, not momentum: the thrust uses the damage before the armor (P_DamageMobj's order)"""
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3004,))[0]
    ws.px, ws.py = (ws.mon_x[m] + 50) << 16, (ws.mon_y[m] - 30) << 16
    ws.p_armor, ws.p_armortype = 100, 2
    w.damage_player(30, ("mon", m), ("mon", m), TicEvents(0))
    dx, dy = thrust_ref(w, 30, 100, ws.mon_x[m] << 16, ws.mon_y[m] << 16, ws.px, ws.py)
    assert (ws.p_momx, ws.p_momy) == (dx, dy) and dx > 0 > dy
    assert ws.p_health == 100 - 15


def test_no_inflictor_no_thrust(W0):
    w = fresh(W0)
    ws = w.ws
    w.damage_player(10, ("sector", 0), None, TicEvents(0))
    m = _active(w, (3004,))[0]
    w.damage_monster(m, 5, ("player", -1), None, TicEvents(0))
    assert (ws.p_momx, ws.p_momy, ws.mon_momx[m], ws.mon_momy[m]) == (0, 0, 0, 0)


def test_the_chainsaw_kicks_nothing(W0):
    """`source->player->readyweapon != wp_chainsaw`: the saw's hit, AND a blast of a barrel the player set off while
    he holds the saw, thrust nothing; a monster's hit on him with the saw ready still does"""
    w = fresh(W0)
    ws = w.ws
    ws.p_owned[gd.WP_CHAINSAW], ws.p_ready = 1, gd.WP_CHAINSAW
    m = _active(w, (3001,))[0]
    ws.px, ws.py = (ws.mon_x[m] + 40) << 16, ws.mon_y[m] << 16
    w.damage_monster(m, 10, ("player", -1), ("player", -1), TicEvents(0))
    assert (ws.mon_momx[m], ws.mon_momy[m]) == (0, 0)
    w.damage_monster(m, 10, ("player", -1), ("bar", 0), TicEvents(0))            # the blast: source the player
    assert (ws.mon_momx[m], ws.mon_momy[m]) == (0, 0)
    if "bar_src" in ws._fields:                     # infighting: the barrel's own record says who set it off
        ws.bar_src[0] = 1
    w.damage_player(10, ("bar", 0), ("bar", 0), TicEvents(0))                   # his own barrel, on him
    assert (ws.p_momx, ws.p_momy) == (0, 0)
    if "bar_src" in ws._fields:                     # ... a barrel a MONSTER set off thrusts him, saw or not
        ws.bar_src[0] = 2
        w.damage_player(10, ("bar", 0), ("bar", 0), TicEvents(0))
        assert (ws.p_momx, ws.p_momy) != (0, 0)
        ws.p_momx = ws.p_momy = 0
    w.damage_player(10, ("mon", m), ("mon", m), TicEvents(0))
    assert (ws.p_momx, ws.p_momy) != (0, 0)
    ws.p_ready = gd.WP_PISTOL
    w.damage_monster(m, 10, ("player", -1), ("player", -1), TicEvents(0))
    assert (ws.mon_momx[m], ws.mon_momy[m]) != (0, 0)


def _ledge(w, *, coin_odd: bool, dmg=10, health=9, player_target=False):
    """the player LOW (floor 0), a zombieman HIGH (floor 128): z difference 128 > 64. The stream set so the coin
    (P_Random() & 1 at the post-increment state) is odd / even"""
    w.reset(gd.SK_HARD)
    ws = w.ws
    m = _active(w, (3004,))[0]
    w.teleport_monster(m, *HIGH)
    ws.px, ws.py = LOW[0] << 16, LOW[1] << 16
    st = next(s for s in range(256) if (R.p_random(s)[0] & 1) == int(coin_odd))
    if player_target:                       # the target must be ABOVE: swap
        w.teleport_monster(m, *LOW)
        ws.px, ws.py = HIGH[0] << 16, HIGH[1] << 16
        ws.p_health, ws.rng_player = health, st
    else:
        ws.mon_health[m], ws.mon_rng[m] = health, st
    return m, st


@pytest.mark.parametrize("odd", [False, True])
def test_the_reversal_falls_forwards(W0, odd):
    """damage < 40, > health, the target 64+ above the inflictor: ONE coin on the TARGET's stream; odd -> the angle
    turned ANG180 and the thrust x4 (the kill throws the corpse TOWARD the shooter, 4x as far)"""
    w = W0
    m, st = _ledge(w, coin_odd=odd)
    ws = w.ws
    w.damage_monster(m, 10, ("player", -1), ("player", -1), TicEvents(0))
    assert ws.mon_rng[m] != st, "the coin draws on the target's stream (then the death roll draws too)"
    dx, dy = thrust_ref(w, 10, 100, (ws.px >> 16) << 16, (ws.py >> 16) << 16, HIGH[0] << 16, HIGH[1] << 16,
                        reverse=odd)
    assert (ws.mon_momx[m], ws.mon_momy[m]) == (dx, dy)
    assert (dx > 0) == (not odd)            # LOW is west of HIGH: away (+x) unless reversed
    # the player's stream is untouched: the target's draws
    w2 = W0
    m, st = _ledge(w2, coin_odd=odd, player_target=True)
    before = w2.ws.rng_player
    w2.damage_player(10, ("mon", m), ("mon", m), TicEvents(0))
    assert w2.ws.rng_player != before
    dx, dy = thrust_ref(w2, 10, 100, LOW[0] << 16, LOW[1] << 16, HIGH[0] << 16, HIGH[1] << 16, reverse=odd)
    assert (w2.ws.p_momx, w2.ws.p_momy) == (dx, dy)


@pytest.mark.parametrize("why", ["dmg40", "health", "level"])
def test_the_coin_is_drawn_only_when_the_rest_holds(W0, why):
    """C's short circuit: no draw (the stream unmoved by the thrust) when damage >= 40, damage <= health, or the z
    difference is <= 64 -- and then no reversal"""
    w = W0
    m, st = _ledge(w, coin_odd=True, dmg=40 if why == "dmg40" else 10, health=10 if why == "health" else 9)
    ws = w.ws
    if why == "level":
        w.teleport_monster(m, LOW[0] + 200, LOW[1])
        ws.mon_floorz[m] = 64                               # exactly 64 above: not > 64
    seen = []
    real = w._roll

    def spy(stream, site, idx=None):
        seen.append(getattr(ws, stream) if idx is None else getattr(ws, stream)[idx])
        return real(stream, site, idx)
    w._roll = spy
    try:
        w.damage_monster(m, 40 if why == "dmg40" else 10, ("player", -1), ("player", -1), TicEvents(0))
    finally:
        del w._roll
    assert seen and seen[0] == st, "the first draw on the stream is the damage's own (pain / death), not a coin"


# ---- P_XYMovement -------------------------------------------------------------------------------------------------------
def _record_tries(w, kind="player", accept=lambda c: True):
    tries = []
    if kind == "player":
        def t(cx, cy, ev):
            tries.append((cx, cy))
            ok = accept((cx, cy))
            if ok:
                w.ws.px, w.ws.py = cx, cy
            return ok
        w._player_knock_try = t
    else:
        def t(m, cx, cy, ev):
            tries.append((cx, cy))
            ok = accept((cx, cy))
            if ok:
                w.ws.mon_x[m], w.ws.mon_y[m] = cx >> 16, cy >> 16
                w.ws.mon_fx[m], w.ws.mon_fy[m] = cx & 0xFFFF, cy & 0xFFFF
            return ok
        w._monster_knock_try = t
    return tries


def _unpatch(w):
    for a in ("_player_knock_try", "_monster_knock_try"):
        w.__dict__.pop(a, None)


def xy_ref(x, y, mx, my, accept):
    """P_XYMovement, transcribed (positions 16.16): -> (tries, final momx, momy)"""
    MAX, HALF = gd.MAXMOVE, gd.MAXMOVE // 2
    mx, my = max(-MAX, min(MAX, mx)), max(-MAX, min(MAX, my))
    xm, ym, tries = mx, my, []
    while True:
        if xm > HALF or ym > HALF:
            px = x + (int(xm / 2))
            py = y + (int(ym / 2))
            xm >>= 1
            ym >>= 1
        else:
            px, py, xm, ym = x + xm, y + ym, 0, 0
        tries.append((px, py))
        if accept((px, py)):
            x, y = px, py
        else:
            mx = my = 0
        if not (xm or ym):
            break
    if -gd.STOPSPEED < mx < gd.STOPSPEED and -gd.STOPSPEED < my < gd.STOPSPEED:
        mx = my = 0
    else:
        mx, my = fixedmul(mx, gd.FRICTION), fixedmul(my, gd.FRICTION)
    return tries, mx, my


CASES = [(40 * U, 0), (-40 * U, 3 * U), (30 * U, 30 * U), (-30 * U, -30 * U), (16 * U, -3), (-3, 16 * U),
         (15 * U, 15 * U), (15 * U + 1, -15 * U - 1), (-29 * U - 7, 15 * U + 1), (0x1000, 0), (0xFFF, -0xFFF),
         (-0x1000, 5), (1, 0), (-1, -1), (2 * U + 3, -U - 5), (123456, -654321)]


@pytest.mark.parametrize("mom", CASES)
@pytest.mark.parametrize("refuse", [None, 0, 1])
def test_the_xy_move_is_doom_s(W0, mom, refuse):
    """the clamp, the positive-only halving, xmove/2 then >>= 1, every try (a refused one zeroes the momentum and the
    loop goes on), the stop or the friction -- the player's move against the transcription"""
    w = fresh(W0)
    ws = w.ws
    x0, y0 = ws.px, ws.py
    ws.p_momx, ws.p_momy = mom
    accept = (lambda c, k=[0]: True) if refuse is None else None
    if refuse is not None:
        n = [0]

        def accept(c):
            n[0] += 1
            return n[0] - 1 != refuse
    want_tries, wmx, wmy = xy_ref(x0, y0, mom[0], mom[1], accept)
    if refuse is not None:
        n[0] = 0
    tries = _record_tries(w, "player", accept)
    try:
        w._xy_move(("player", -1), TicEvents(0))
    finally:
        _unpatch(w)
    assert tries == want_tries
    assert (ws.p_momx, ws.p_momy) == (wmx, wmy)


def test_the_halving_cases_happen():
    """the transcription's cases cover: two tries (halved), one try of a NEGATIVE move beyond MAXMOVE/2 (not halved),
    a truncation that differs from the shift, the stop and the friction"""
    two = [c for c in CASES if len(xy_ref(0, 0, *c, lambda p: True)[0]) == 2]
    one_neg = [c for c in CASES if min(c) < -gd.MAXMOVE // 2 and max(c) <= gd.MAXMOVE // 2]
    trunc = [c for c in two if any(v < 0 and v & 1 for v in (max(-gd.MAXMOVE, min(gd.MAXMOVE, x)) for x in c))]
    assert two and one_neg and trunc


def test_friction_is_29_over_32_floored():
    """FixedMul(mom, FRICTION) == floor(mom * 29 / 32) on every momentum P_XYMovement can leave (|mom| <= MAXMOVE):
    the shift-add the fj runs"""
    import random
    rnd = random.Random(7)
    for v in [rnd.randint(-gd.MAXMOVE, gd.MAXMOVE) for _ in range(20000)] + [-gd.MAXMOVE, gd.MAXMOVE, -1, 1, 0]:
        assert fixedmul(v, gd.FRICTION) == (29 * v) >> 5


def test_the_monster_slides_on_its_fraction(W0):
    """the monster's 16.16 position is (mon_x << 16) + mon_fx: the tries are DOOM's from it, and a candidate whose
    integer part is unchanged is accepted WITHOUT a try_move_monster (G-B2's convention)"""
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3004,))[0]
    ws.mon_fx[m], ws.mon_fy[m] = 0xFFF0, 0x0008
    ws.mon_momx[m], ws.mon_momy[m] = 0x8, -0x8                 # stays inside the unit: no test
    calls = []
    w.try_move_monster = lambda *a, **k: calls.append(a) or ("ok", 0)
    try:
        x0, y0 = ws.mon_x[m], ws.mon_y[m]
        w._monster_knock_move(m, TicEvents(0))
    finally:
        del w.try_move_monster
    assert calls == [] and (ws.mon_x[m], ws.mon_y[m]) == (x0, y0) and (ws.mon_fx[m], ws.mon_fy[m]) == (0xFFF8, 0)


def test_a_fraction_carry_is_tested(W0):
    """... while a candidate that carries into the next unit IS tested, at its integer part"""
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3004,))[0]
    ws.mon_fx[m] = 0xFFF0
    ws.mon_momx[m] = 0x20
    calls = []
    real = w.try_move_monster
    w.try_move_monster = lambda mm, nx, ny, corpse=False: calls.append((nx, ny, corpse)) or real(mm, nx, ny, corpse)
    try:
        x0, y0 = ws.mon_x[m], ws.mon_y[m]
        w._monster_knock_move(m, TicEvents(0))
    finally:
        del w.try_move_monster
    assert calls == [(x0 + 1, y0, False)]
    assert (ws.mon_x[m], ws.mon_fx[m]) == (x0 + 1, 0x0010)


def test_a_corpse_tries_as_a_corpse(W0):
    """a monster not shootable tries as MF_CORPSE: a quarter of the height (it fits where 56 does not), no drop-off
    refusal (it slides off a ledge a live monster may not walk off)"""
    w = fresh(W0)
    m = _active(w, (3004,))[0]
    rows = []
    found = {"dropoff": None, "height": None}
    for li, ld in enumerate(w.lds):
        if ld.back == -1:
            continue
        fs, bs = w.secs_c[w.sds[ld.front].sector], w.secs_c[w.sds[ld.back].sector]
        if abs(fs.floor_h - bs.floor_h) <= 24:
            continue
        v1, v2 = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        mx, my = (v1[0] + v2[0]) // 2, (v1[1] + v2[1]) // 2
        for dx in range(-24, 25, 4):
            for dy in range(-24, 25, 4):
                rows.append((mx + dx, my + dy))
    for x, y in rows[:6000]:
        leaf = w.rm.point_in_subsector(w.cmap, x, y)
        w.ws.mon_floorz[m] = w.secs_c[w.leaf_sector[leaf]].floor_h
        live, _ = w.try_move_lines(m, x, y)
        dead, _ = w.try_move_lines(m, x, y, corpse=True)
        if live == "dropoff" and dead == "ok" and not found["dropoff"]:
            found["dropoff"] = (x, y)
        if live == "height" and dead == "ok" and not found["height"]:
            found["height"] = (x, y)
        if all(found.values()):
            break
    assert found["dropoff"], "no position where only the drop-off refuses"
    # (a 14-unit corpse fitting where 56 does not needs an opening 14..55 high: E1M1 may have none -- recorded)


def test_the_stop_and_the_corpse_rule(W0):
    """the corpse keeps its momentum (no friction) while its floorz differs from its leaf's sector floor and it has
    more than 1/4 unit on an axis; a live monster and a corpse on its floor slow down"""
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3004,))[0]
    for shootable, floor_off, mom, slides in ((0, 8, 0x4001, True), (0, 8, 0x4000, False), (0, 0, 0x9000, False),
                                              (1, 8, 0x9000, False)):
        w.reset(gd.SK_HARD)
        ws = w.ws
        ws.mon_shootable[m] = shootable
        ws.mon_floorz[m] += floor_off
        assert w._knock_slides(("mon", m), -mom, 0) == slides, (shootable, floor_off, hex(mom))


# ---- the frame: the order, the drops, the corpses ----------------------------------------------------------------------
def test_full_is_untouched():
    """the "full" model has no knock: no cells, no thrust, no move (v6's model)"""
    w = World(monsters="full", player="full")
    assert not w._p_knock and "p_momx" not in w.ws._fields and "mon_fx" not in w.ws._fields
    assert w.drop_pos(0) == (w.ws.mon_x[0], w.ws.mon_y[0])


def test_a_kill_slides_the_corpse_and_leaves_the_drop(W0):
    """the killing blow thrusts (before the health): the corpse slides over the next tics -- each monster tic, from
    the top of its turn -- while its drop lies where the corpse was at the kill, and is taken there"""
    w = fresh(W0)
    ws = w.ws
    m = next(m for m in _active(w, (3004,)) if w.dropper[m] is not None)
    x0, y0 = ws.mon_x[m], ws.mon_y[m]
    ws.px, ws.py = (x0 - 60) << 16, y0 << 16
    w.damage_monster(m, 200, ("player", -1), ("player", -1), TicEvents(0))
    assert ws.mon_health[m] <= 0 and ws.mon_drop[m] == 1 and ws.mon_momx[m] > 0
    assert w.drop_pos(m) == (x0, y0) and w.drop_leaf(m) == ws.mon_leaf[m]
    moved = 0
    for _ in range(6):
        ev = w.tic({})
        moved += sum(1 for t, ok in ev.knocks if t == ("mon", m) and ok)
    assert ws.mon_x[m] > x0 and moved >= 4, (ws.mon_x[m], x0, moved)
    assert w.drop_pos(m) == (x0, y0)
    assert w.drop_leaf(m) == w.rm.point_in_subsector(w.cmap, x0, y0)
    ev = TicEvents(0)
    w._touch_specials(x0 << 16, y0 << 16, w._floor_at(x0, y0), ev)
    assert ("drop", m, w.dropper[m]) in ev.pickups and ws.mon_drop[m] == 2


def test_the_monster_moves_each_monster_tic_and_the_player_once_a_frame(W0):
    """O-B3: a monster's knock moves at its 2 tics a frame, the player's once (his tic): two tries vs one a frame"""
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3004,))[0]
    ws.mon_momx[m] = 3 * U
    ws.p_momx = 3 * U
    ev = w.tic({})
    assert sum(1 for t, _ in ev.knocks if t == ("mon", m)) == 2
    assert sum(1 for t, _ in ev.knocks if t == ("player", -1)) == 1


def test_the_dead_player_slides(W0):
    """the corpse slides: a dead player's knock momentum still moves him, as a corpse (height >> 2)"""
    w = fresh(W0)
    ws = w.ws
    ws.p_momx = 4 * U
    ws.p_health, ws.p_dead = 0, 1
    x0 = ws.px
    seen = []
    real = w.rm.try_move
    w.rm.try_move = lambda *a, **k: seen.append(k.get("height")) or real(*a, **k)
    try:
        w.tic({})
    finally:
        del w.rm.try_move
    assert ws.px == x0 + 4 * U and seen == [PLAYER_HEIGHT >> 2]


def test_a_wall_stops_the_knock(W0):
    """O-B4: a refused knock step zeroes the momentum (no slide along the wall)"""
    w = fresh(W0)
    ws = w.ws
    ws.p_momx = -30 * U                                         # the start room's west wall is near
    for _ in range(10):
        w.tic({})
        if not ws.p_momx:
            break
    assert ws.p_momx == 0 and ws.p_momy == 0


# ---- R9: the model mutated, the reference must part -----------------------------------------------------------------
def test_control_a_mass_blind_thrust_is_caught(W0):
    w = fresh(W0)
    ws = w.ws
    m = _active(w, (3002,))[0]                                 # a demon: mass 400
    ws.px, ws.py = (ws.mon_x[m] + 80) << 16, ws.mon_y[m] << 16
    ws.mon_health[m] = 999
    info = w.mon_info[m]
    real = info.mass
    w.damage_monster(m, 30, ("player", -1), ("player", -1), TicEvents(0))
    good = (ws.mon_momx[m], ws.mon_momy[m])
    assert real == 400 and good == thrust_ref(w, 30, 400, ws.px, ws.py, ws.mon_x[m] << 16, ws.mon_y[m] << 16)
    assert good != thrust_ref(w, 30, 100, ws.px, ws.py, ws.mon_x[m] << 16, ws.mon_y[m] << 16)


def test_control_the_shift_for_the_halving_is_caught():
    """xmove >> 1 in place of xmove/2 (or the reverse) parts on a negative odd move"""
    tries, _, _ = xy_ref(0, 0, -29 * U - 7, 15 * U + 1, lambda p: True)
    assert tries[0][0] == int((-29 * U - 7) / 2) != (-29 * U - 7) >> 1
