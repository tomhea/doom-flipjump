"""M7 P3.2a (host): `doomfj.sight` -- the owner's "seen" rule (docs/gp-monsters.md 8.2). REJECT is read from the
map's wad bit for bit; the waking sight is seen, or REJECT-visible within NEAR; the attack sight is seen, or within
NEAR with the exact LOS; `SeenHook` marks a monster the picture draws and not one behind the player; `set_seen` /
`slots_of` carry a render's drawables to slots. Each claim has a control that flips its verdict."""
import itertools

import pytest

from doomfj import sight as SI
from doomfj.monsters import MonsterPhase
from doomfj.world import World, aprox_distance


@pytest.fixture(scope="module")
def world():
    return World(monsters="wake", sight_rule="seen")


def _place_player(w, x, y, angle=0):
    w.ws.px, w.ws.py, w.ws.pangle = x << 16, y << 16, angle


def test_reject_is_the_wads_lump_bit_for_bit(world):
    r = world.reject
    nsec = len(world.secs)
    from doomfj.build import DEFAULT_SPRITE_WAD, _resolve_sprite_wad
    try:                                                # the map's own lump, else the asset wad's (load_reject)
        raw = bytes(world.mw._map_lump(world.mapname, "REJECT").data)
    except KeyError:
        raw = bytes(_resolve_sprite_wad(world.mw, DEFAULT_SPRITE_WAD)._map_lump(world.mapname, "REJECT").data)
    assert r.nsec == nsec and r.data == raw
    for s1, s2 in itertools.product(range(nsec), repeat=2):
        k = s1 * nsec + s2
        assert r.visible(s1, s2) == (not (raw[k >> 3] >> (k & 7)) & 1)
    assert not all(r.visible(a, b) for a in range(nsec) for b in range(nsec)), "E1M1's REJECT rejects nothing"
    # control: the all-visible fallback (a map without REJECT) sees every pair
    blank = SI.Reject(bytes(len(raw)), nsec)
    assert all(blank.visible(a, b) for a in range(nsec) for b in range(nsec))


def _near_rejected(w):
    """(monster, x, y): a player spot within NEAR of a monster whose sector REJECTs the player's"""
    for m in range(w.layout.nmon):
        mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
        for dx, dy in itertools.product(range(-120, 121, 8), repeat=2):
            if aprox_distance(dx, dy) > SI.NEAR:
                continue
            _place_player(w, mx + dx, my + dy)
            try:
                ps = w.player_sector()
            except Exception:                           # noqa: BLE001 -- outside the map
                continue
            if not w.reject.visible(w._mon_sector(m), ps):
                return m, mx + dx, my + dy
    return None


def test_wake_sight(world):
    w = world
    m = 0
    mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
    w.ws.mon_seen[m] = 1
    _place_player(w, mx + 2000, my)
    assert SI.wake_sight(w, m), "a seen monster wakes at any distance"
    w.ws.mon_seen[m] = 0
    assert not SI.wake_sight(w, m), "an unseen monster beyond NEAR does not"
    _place_player(w, mx + 40, my)
    assert SI.wake_sight(w, m) == w.reject.visible(w._mon_sector(m), w.player_sector())
    hit = _near_rejected(w)
    assert hit, "no near spot is REJECTed in E1M1: the REJECT branch is never exercised"
    m2, x, y = hit
    _place_player(w, x, y)
    w.ws.mon_seen[m2] = 0
    assert not SI.wake_sight(w, m2), "a near monster whose REJECT row hides the player woke"
    saved = w.reject
    try:                                                # control: without the REJECT lump it wakes
        w.reject = SI.Reject(bytes(len(saved.data)), saved.nsec)
        assert SI.wake_sight(w, m2)
    finally:
        w.reject = saved


def test_attack_sight(world):
    w = world
    m = 0
    mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
    w.ws.mon_seen[m] = 0
    near = [(mx + dx, my + dy) for dx, dy in itertools.product(range(-120, 121, 6), repeat=2)
            if aprox_distance(dx, dy) <= SI.NEAR]
    clear = blocked = 0
    for x, y in near:
        _place_player(w, x, y)
        a = SI.attack_sight(w, m)
        assert a == w.los_to_player(w, m)
        clear += a
        blocked += not a
    assert clear and blocked, (clear, blocked)          # both verdicts occur near the monster
    _place_player(w, mx + 2000, my)
    assert not SI.attack_sight(w, m), "beyond NEAR an unseen monster has no attack sight"
    w.ws.mon_seen[m] = 1
    assert SI.attack_sight(w, m), "a seen monster has it at any distance"
    w.ws.mon_seen[m] = 0


def test_seen_hook_marks_what_the_picture_draws():
    w = World(monsters="wake", sight_rule="seen")
    hook = SI.SeenHook(w)
    m = 0
    mx, my = w.ws.mon_x[m], w.ws.mon_y[m]
    w.wake_all()
    # the player 96 units east of the monster: facing west it is in the picture, facing east it is behind
    _place_player(w, mx + 96, my, angle=0x80000000)
    hook(w)
    assert w.ws.mon_seen[m] == 1, "a monster in front of the player was not marked seen"
    _place_player(w, mx + 96, my, angle=0)
    hook(w)
    assert w.ws.mon_seen[m] == 0, "a monster behind the player was marked seen (control)"


def test_set_seen_and_slots_of():
    from doomfj.monsters import MonsterViews
    ph = MonsterPhase(mode="wake")
    ph_views = MonsterViews(ph.world.rm, ph.world.mw, ph.world.mapname, SI.SeenHook(ph.world).art, ph.world)
    mdi = ph_views.mdi
    some = {mdi[1], mdi[4]}
    assert ph_views.slots_of(some) == {1, 4}
    assert ph_views.slots_of(set()) == set()
    ph.set_seen({1, 4})
    n = ph.world.layout.nmon
    assert [ph.world.ws.mon_seen[m] for m in range(n)] == [int(m in (1, 4)) for m in range(n)]
