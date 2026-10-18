"""M8 C8 part 2 (doomfj.lostsoul): THE LOST SOUL in the model -- its data, its rules against DOOM's code transcribed
here independently (Chocolate Doom at gamedata.SOURCE_COMMIT: p_enemy.c A_SkullAttack / P_CheckMissileRange, p_mobj.c
P_ZMovement, p_map.c PIT_CheckThing's slam, p_inter.c P_DamageMobj / P_KillMobj), and its integration in World on E1M1
with three souls placed in front of the player start (the soul's maps, E1M6 / E1M7, cannot build a World until their
other clusters land; E1M1 holds every rule's geometry: walls, steps, doors, items, barrels, monsters).

R9: every comparison test runs once on a MUTATED model (`monkeypatch` swaps one rule) and must then fail -- the
`_control_*` tests; and E1M1 without a soul is the model it was (a frozen digest of 30 tics, and no soul cell).
"""
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src")]

from doomfj import gamedata as gd                                    # noqa: E402
from doomfj import lostsoul as LS                                    # noqa: E402
from doomfj.fixedpoint import _signed, aprox_distance, fixed_mul    # noqa: E402
from doomfj.wad import Thing, WadFile                                # noqa: E402
from doomfj.world import TicEvents, World                            # noqa: E402

SOULS = [(-250, 240, 180), (-200, 300, 180), (-300, 200, 180)]       # in front of E1M1's start (-416, 256), facing it
E1M1_30_TICS = "6d201259720a9c734340c22c0db923dde5bdf97bd4b848868d67629a31505d53"   # the model before C8 (git b64ef94d)


def soul_wad(souls=SOULS):
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    base = mw.things
    mw.things = lambda name, base=base: base(name) + [Thing(x, y, a, 3006, 7) for x, y, a in souls]
    return mw


def soul_world(**kw):
    return World(soul_wad(), "E1M1", skill=gd.SK_HARD, monsters="final", player="final", **kw)


# ---- the data -------------------------------------------------------------------------------------------------------
def test_mt_skull_is_info_c():
    """info.c MT_SKULL and S_SKULL_* (Chocolate Doom, fetched raw 2026-10-19), field by field"""
    m = gd.MOBJINFO["MT_SKULL"]
    assert (m.doomednum, m.spawnhealth, m.reactiontime, m.painchance, m.speed, m.radius, m.height, m.mass,
            m.damage) == (3006, 100, 8, 256, 8, 16 << 16, 56 << 16, 50, 3)
    assert m.flags == gd.MF_SOLID | gd.MF_SHOOTABLE | gd.MF_FLOAT | gd.MF_NOGRAVITY
    assert (m.spawnstate, m.seestate, m.painstate, m.meleestate, m.missilestate, m.deathstate, m.xdeathstate) == (
        "S_SKULL_STND", "S_SKULL_RUN1", "S_SKULL_PAIN", gd.S_NULL, "S_SKULL_ATK1", "S_SKULL_DIE1", gd.S_NULL)
    rows = [(n, s.frame, s.tics, s.action, s.next) for n, s in ((n, gd.STATES[n]) for n in gd.EXT_STATE_NAMES)]
    assert rows == [
        ("S_SKULL_STND", 32768, 10, "A_Look", "S_SKULL_STND2"), ("S_SKULL_STND2", 32769, 10, "A_Look", "S_SKULL_STND"),
        ("S_SKULL_RUN1", 32768, 6, "A_Chase", "S_SKULL_RUN2"), ("S_SKULL_RUN2", 32769, 6, "A_Chase", "S_SKULL_RUN1"),
        ("S_SKULL_ATK1", 32770, 10, "A_FaceTarget", "S_SKULL_ATK2"),
        ("S_SKULL_ATK2", 32771, 4, "A_SkullAttack", "S_SKULL_ATK3"),
        ("S_SKULL_ATK3", 32770, 4, None, "S_SKULL_ATK4"), ("S_SKULL_ATK4", 32771, 4, None, "S_SKULL_ATK3"),
        ("S_SKULL_PAIN", 32772, 3, None, "S_SKULL_PAIN2"), ("S_SKULL_PAIN2", 32772, 3, "A_Pain", "S_SKULL_RUN1"),
        ("S_SKULL_DIE1", 32773, 6, None, "S_SKULL_DIE2"), ("S_SKULL_DIE2", 32774, 6, "A_Scream", "S_SKULL_DIE3"),
        ("S_SKULL_DIE3", 32775, 6, None, "S_SKULL_DIE4"), ("S_SKULL_DIE4", 32776, 6, "A_Fall", "S_SKULL_DIE5"),
        ("S_SKULL_DIE5", 9, 6, None, "S_SKULL_DIE6"), ("S_SKULL_DIE6", 10, 6, None, "S_NULL")]
    assert gd.ACTIONS["A_SkullAttack"].cls == "heavy" and not gd.check_integrity()


def test_extension_codes_are_monster_domain_free():
    """every extension row's alias code is a psprite state's (never a monster cell's) and names it back; every core
    monster state keeps its index; no two monster states share a code"""
    from doomfj.monstercode import monster_states
    types = tuple(gd.MONSTER_DOOMEDNUMS.values())
    core = set(monster_states())
    for n in gd.EXT_STATE_NAMES:
        code = gd.STATE_INDEX[n]
        assert code in gd.MON_ALIAS_POOL and gd.mon_state_name(code) == n
        assert gd.STATE_NAMES[code] not in core, (n, gd.STATE_NAMES[code])
    for s in monster_states(types):
        assert gd.mon_state_name(gd.STATE_INDEX[s]) == s
    codes = [gd.STATE_INDEX[s] for s in monster_states(types)]
    assert len(codes) == len(set(codes))
    assert all(gd.STATE_INDEX[s] == gd.STATE_NAMES.index(s) for s in core)


def test_e1m1_without_a_soul_is_unchanged():
    w = World(skill=gd.SK_HARD, monsters="final", player="final")
    assert w.layout.nsoul == 0 and not any(f.name.startswith("sk_") for f in w.schema)
    for i in range(30):
        w.tic({"forward": i % 3 == 0, "fire": i % 5 == 0})
    assert w.digest() == E1M1_30_TICS


# ---- DOOM's code, transcribed ---------------------------------------------------------------------------------------
def ref_skull_attack(rm, sx16, sy16, sz16, dx16, dy16, dz16):
    """A_SkullAttack after its target test: (momx, momy, momz) -- p_enemy.c, the model's angle kernel and trig"""
    an = rm.point_to_angle(sx16, sy16, dx16, dy16) >> rm.angle_shift
    momx = _signed(fixed_mul(20 << 16, rm._finecos_idx(an), 8, 4), 32)
    momy = _signed(fixed_mul(20 << 16, rm._finesin_idx(an), 8, 4), 32)
    dist = aprox_distance(dx16 - sx16, dy16 - sy16) // (20 << 16)
    if dist < 1:
        dist = 1
    num = dz16 + (56 << 16 >> 1) - sz16
    q = abs(num) // dist
    return momx, momy, (q if num >= 0 else -q)


def ref_z_movement(z, momz, floorz, ceilz, height, fly, floating, live, target):
    """P_ZMovement for a lost soul (p_mobj.c, correct_lost_soul_bounce): -> (z, momz). `target` None or (dist, tz)"""
    z += momz
    if live and target is not None and not fly and not floating:
        dist, tz = target
        delta = (tz + (height >> 1)) - z
        if delta < 0 and dist < -(delta * 3):
            z -= 4 << 16
        elif delta > 0 and dist < (delta * 3):
            z += 4 << 16
    if z <= floorz:
        if fly:
            momz = -momz
        if momz < 0:
            momz = 0
        z = floorz
    if z + height > ceilz:
        if momz > 0:
            momz = 0
        z = ceilz - height
        if fly:
            momz = -momz
    return z, momz


def check_missile_range_ref(d, v):
    """P_CheckMissileRange's roll for MT_SKULL (no melee): attack?"""
    dist = d - 64 - 128
    dist >>= 1
    if dist > 200:
        dist = 200
    return not v < dist


# ---- the rules ----------------------------------------------------------------------------------------------------
def _charge_cases(w, n=300):
    rnd = random.Random(0x5C)
    ws = w.ws
    m = w.soul_slots[0]
    out = []
    for _ in range(n):
        sx, sy = rnd.randint(-900, 200), rnd.randint(-200, 900)
        out.append(dict(s=(sx, sy), z=(rnd.randint(-40, 120) << 16) + rnd.choice((0, rnd.randrange(1 << 16))),
                        p=((sx + rnd.randint(-1500, 1500)) << 16 | rnd.randrange(1 << 16),
                           (sy + rnd.randint(-1500, 1500)) << 16 | rnd.randrange(1 << 16))))
    return m, out


def run_charges(w):
    """A_SkullAttack at the player for each case: [(momx, momy, momz, facing)]"""
    m, cases = _charge_cases(w)
    ws, k = w.ws, w.soul_of[m]
    got = []
    for c in cases:
        ws.mon_x[m], ws.mon_y[m] = c["s"]
        ws.sk_z[k] = c["z"]
        ws.px, ws.py = c["p"]
        ws.mon_target[m] = 1
        w._a_skull_attack(m, TicEvents(0))
        got.append((ws.mon_momx[m], ws.mon_momy[m], ws.sk_momz[k], ws.sk_fly[k]))
    return got, m, cases


def test_skull_attack_is_doom():
    w = soul_world()
    got, m, cases = run_charges(w)
    for g, c in zip(got, cases):
        pz = w.rm.check_position(w.scene_c, *c["p"])[1] << 16
        want = ref_skull_attack(w.rm, c["s"][0] << 16, c["s"][1] << 16, c["z"], c["p"][0], c["p"][1], pz)
        assert g == want + (1,), (c, g, want)


def test_control_skull_attack_octant_aim_is_caught(monkeypatch):
    """R9: aiming the charge along the FACING octant (A_FaceTarget's model angle) instead of the exact angle"""
    w = soul_world()
    orig = w.rm.point_to_angle
    monkeypatch.setattr(w.rm, "point_to_angle", lambda *a: orig(*a) & ~((1 << 29) - 1))
    got, m, cases = run_charges(w)
    monkeypatch.setattr(w.rm, "point_to_angle", orig)
    bad = 0
    for g, c in zip(got, cases):
        pz = w.rm.check_position(w.scene_c, *c["p"])[1] << 16
        bad += g != ref_skull_attack(w.rm, c["s"][0] << 16, c["s"][1] << 16, c["z"], c["p"][0], c["p"][1], pz) + (1,)
    assert bad > len(cases) // 2


def _z_cases(n=600):
    rnd = random.Random(0x2E)
    for _ in range(n):
        fl = rnd.randint(-80, 60)
        ce = fl + rnd.choice((56, 57, 72, 128, rnd.randint(56, 300)))
        yield dict(fl=fl, ce=ce, z=(fl << 16) + rnd.choice((0, 0, rnd.randint(-8 << 16, 120 << 16))),
                   mz=rnd.choice((0, 0, rnd.randint(-12 << 16, 12 << 16))), fly=rnd.random() < 0.4,
                   inf=rnd.random() < 0.2, live=rnd.random() < 0.85, tg=rnd.random() < 0.85,
                   d=rnd.choice((rnd.randint(0, 80), rnd.randint(0, 600))), tz=rnd.randint(-80, 60))


def run_z(w):
    ws = w.ws
    m = w.soul_slots[0]
    k = w.soul_of[m]
    got, want = [], []
    for c in _z_cases():
        ws.mon_x[m], ws.mon_y[m], ws.mon_fx[m], ws.mon_fy[m] = -300, 256, 0, 0
        ws.mon_floorz[m], ws.sk_ceil[k], ws.sk_z[k], ws.sk_momz[k] = c["fl"], c["ce"], c["z"], c["mz"]
        ws.sk_fly[k], ws.sk_inf[k], ws.mon_shootable[m] = int(c["fly"]), int(c["inf"]), int(c["live"])
        ws.mon_target[m] = int(c["tg"])
        ws.px, ws.py = (-300 + c["d"]) << 16, 256 << 16            # the target: the player, d units east
        tz = w.rm.check_position(w.scene_c, ws.px, ws.py)[1] << 16
        w._soul_z_move(m)
        got.append((ws.sk_z[k], ws.sk_momz[k]))
        h = (56 if c["live"] else 14) << 16
        want.append(ref_z_movement(c["z"], c["mz"], c["fl"] << 16, c["ce"] << 16, h, c["fly"], c["inf"], c["live"],
                                   (c["d"] << 16, tz) if c["tg"] else None))
    return got, want


def test_z_movement_is_doom():
    w = soul_world()
    got, want = run_z(w)
    assert got == want


def test_control_z_movement_without_the_bounce_is_caught(monkeypatch):
    """R9: the floor bounce dropped (Doom 2 v1.9's order, momz zeroed before the reversal)"""
    w = soul_world()
    orig = World._soul_z_move

    def no_bounce(self, m):
        k = self.soul_of[m]
        fly = self.ws.sk_fly[k]
        self.ws.sk_fly[k] = 0 if self.ws.sk_z[k] + self.ws.sk_momz[k] <= self.ws.mon_floorz[m] << 16 else fly
        orig(self, m)
        self.ws.sk_fly[k] = fly
    monkeypatch.setattr(World, "_soul_z_move", no_bounce)
    got, want = run_z(w)
    assert got != want


def test_missile_range_identity():
    """the fj's form (soulcode.decide_range_lines: refuse iff v < 200 and d >= 2v + 194) is P_CheckMissileRange's
    MT_SKULL roll, on every distance the world can hold and every P_Random value; and the model's"""
    for d in range(0, 6000):
        for v in range(256):
            fj = not (v < 200 and d >= 2 * v + 194)
            assert fj == check_missile_range_ref(d, v), (d, v)
    w = soul_world()
    m = w.soul_slots[0]
    ws = w.ws
    rnd = random.Random(7)
    for _ in range(400):
        d = rnd.randint(0, 3000)
        ws.mon_x[m], ws.mon_y[m] = -300, 256
        ws.px, ws.py = (-300 + d) << 16, 256 << 16
        ws.mon_justhit[m], ws.mon_reaction[m], ws.mon_target[m] = 0, 0, 1
        w.attack_sight = lambda _w, _m: True
        st = ws.mon_rng[m]
        got = w._check_missile_range(m)
        from doomfj import rng as R
        v, _ = R.p_random(st)
        assert got == check_missile_range_ref(aprox_distance(d, 0), v)


def test_control_missile_range_without_the_halving_is_caught():
    """R9: the plain monster's roll (no `dist >>= 1`) parts from MT_SKULL's"""
    bad = sum(1 for d in range(200, 2000, 7) for v in range(0, 256, 5)
              if (not v < min(d - 192, 200)) != check_missile_range_ref(d, v))
    assert bad > 100


# ---- the world ----------------------------------------------------------------------------------------------------
def _run(w, n, keys=lambda i: {}):
    evs = []
    for i in range(n):
        evs.append(w.tic(keys(i)))
    return evs


def test_souls_charge_slam_and_hurt():
    """three souls woken by the player's shots charge, slam (the player, each other), stop, float -- and the
    soul events agree with the cells: a slam's damage is the claw formula, a charge's momentum is 20 a tic"""
    w = soul_world()
    evs = _run(w, 400, lambda i: {"fire": i % 7 == 0, "turn_left": i < 10})
    kinds = {e[0] for ev in evs for e in ev.souls}
    assert {"charge", "slam", "stop"} <= kinds, kinds
    slams = [e for ev in evs for e in ev.souls if e[0] == "slam"]
    assert any(e[2] == "player" for e in slams) and all(e[4] in {LS.slam_roll(v) for v in range(256)} for e in slams)
    hurt = [h for ev in evs for h in ev.player_hurt if h[0][0] == "mon" and h[0][1] in w.soul_slots]
    assert hurt, "a slam hurt the player"
    for ev in evs:
        for e in ev.souls:
            if e[0] == "charge":
                _c, m, an, _mz = e
                mx, my = w.rocket_mom[an >> w.rm.angle_shift]
                assert abs(mx) <= 20 << 16 and abs(my) <= 20 << 16 and max(abs(mx), abs(my)) > 14 << 16


def test_a_killed_soul_is_removed():
    w = soul_world()
    m = w.soul_slots[1]
    ev = TicEvents(0)
    w.damage_monster(m, 200, ("player", -1), ("player", -1), ev)
    assert gd.mon_state_name(w.ws.mon_state[m]) == "S_SKULL_DIE1" and not w.ws.mon_shootable[m]
    assert w.ws.p_killcount == 0, "MT_SKULL is not MF_COUNTKILL"
    for _ in range(40):
        w.tic({})
    assert not w.ws.mon_active[m]
    assert all(m not in lst for lst in w.leaf_lists().values())
    assert w.leaf_lists() == w.leaf_lists_from_scratch()


def test_a_flying_soul_feels_no_pain_but_rolls():
    w = soul_world()
    m = w.soul_slots[0]
    k = w.soul_of[m]
    ws = w.ws
    ws.mon_target[m] = 1
    ws.mon_state[m], ws.mon_tics[m] = gd.STATE_INDEX["S_SKULL_ATK3"], 4     # charging
    w._a_skull_attack(m, TicEvents(0))
    st = ws.mon_rng[m]
    state = ws.mon_state[m]
    w.damage_monster(m, 5, ("player", -1), ("player", -1), TicEvents(0))
    assert ws.mon_rng[m] != st and ws.mon_state[m] == state and not ws.mon_justhit[m]
    assert ws.sk_fly[k] == 1 and ws.sk_momz[k] == 0, "SKULLFLY stays; the momentum is zeroed (then the thrust)"
    ws.sk_fly[k] = 0
    w.damage_monster(m, 5, ("player", -1), ("player", -1), TicEvents(0))
    assert gd.mon_state_name(ws.mon_state[m]) == "S_SKULL_PAIN" and ws.mon_justhit[m]


def test_a_slam_on_an_item_stops_the_soul_and_rolls():
    """PIT_CheckThing's MF_SPECIAL: a charging soul stops at a pickup, with the damage roll drawn"""
    w = soul_world()
    ws = w.ws
    m = w.soul_slots[0]
    k = w.soul_of[m]
    i, t = next((i, t) for i, t in enumerate(w.pickup_things) if not ws.pickup_taken[i])
    w.teleport_monster(m, t.x - 40, t.y)
    ws.mon_target[m] = 1
    ws.px, ws.py = (t.x + 400) << 16, t.y << 16
    ws.sk_fly[k] = 1
    ws.mon_momx[m], ws.mon_momy[m] = 20 << 16, 0
    st = ws.mon_rng[m]
    ev = TicEvents(0)
    due = w._soul_xy(m, ev)
    assert due and ws.sk_fly[k] == 0 and ws.mon_momx[m] == 0 and ws.mon_rng[m] != st
    assert ("slam", m, "pickup", i) == ev.souls[0][:4] and not ws.pickup_taken[i]


def test_the_oracle_draws_a_soul_at_its_z():
    """MonsterViews.positions carries a soul's z; the oracle's picture moves with it (the floor's would not)"""
    pytest.importorskip("doomfj.monsters")
    art_path = ROOT / "assets/freedoom1.wad"
    if not art_path.exists():
        pytest.skip("needs assets/freedoom1.wad")
    from doomfj.config import GAME_CFG
    from doomfj.monsters import MonsterPhase, MonsterViews
    from doomfj.reference_model import GAME_RENDER_KW, ReferenceModel, SimState, build_scene
    art = WadFile.from_path(str(art_path))
    ph = MonsterPhase(soul_wad(), "E1M1", mode="final", player="final")
    w, ws = ph.world, ph.world.ws
    rm = ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm, w.mw, w.mapname, art, w)
    sc = build_scene(w.mw, w.mw, w.mapname)
    st = SimState(ws.px, ws.py, ws.pangle, w.mapname)
    frames = []
    for dz in (0, 32):
        for k, m in enumerate(w.soul_slots):
            ws.sk_z[k] = (ws.mon_floorz[m] + dz) << 16
        pos = mv.positions(ph)
        assert all(pos[mv.mdi[m]][2] == ws.mon_floorz[m] + dz for m in w.soul_slots)
        frames.append(bytes(rm.render_wall_frame(st, sc, sprite_wad=art, thing_views=mv(ph, ws.px, ws.py),
                                                 thing_positions=pos, **GAME_RENDER_KW)))
    assert frames[0] != frames[1]


def _low_side_of_a_ledge(w):
    """(x, y, dir): a point 18 units in front of a ledge's LOW side (floors > 24 apart, an opening that holds a soul),
    and the DI_ direction (E/N/W/S) that steps into it"""
    import math
    for li, ld in enumerate(w.lds):
        if ld.back == -1:
            continue
        fs, bs = w.secs[w.sds[ld.front].sector], w.secs[w.sds[ld.back].sector]
        lo, hi = (fs, bs) if fs.floor_h < bs.floor_h else (bs, fs)
        if hi.floor_h - lo.floor_h <= 24 or min(fs.ceil_h, bs.ceil_h) - hi.floor_h < 56:
            continue
        (x1, y1), (x2, y2) = w.cmap.vertexes[ld.v1], w.cmap.vertexes[ld.v2]
        if x1 != x2 and y1 != y2 or math.hypot(x2 - x1, y2 - y1) < 80:
            continue
        nx, ny = (y2 - y1), -(x2 - x1)                      # the front side's normal
        L = math.hypot(nx, ny)
        nx, ny = nx / L, ny / L
        if lo is bs:
            nx, ny = -nx, -ny                                # toward the LOW side
        px, py = int((x1 + x2) / 2 + 18 * nx), int((y1 + y2) / 2 + 18 * ny)
        d = {(1, 0): gd.DI_WEST, (-1, 0): gd.DI_EAST, (0, 1): gd.DI_SOUTH, (0, -1): gd.DI_NORTH}[(round(nx), round(ny))]
        ok, fz, cz = w.rm.check_position(w.scene_c, px << 16, py << 16, radius=16 << 16)
        if ok and fz == lo.floor_h and cz - fz >= 56:
            yield px, py, d, lo.floor_h, hi.floor_h


def test_a_soul_floats_up_a_ledge():
    """P_Move's MF_FLOAT branch: a step too high for where it flies floats it 4 up (FLOATOK, before any door), and
    the step is taken once its z is within 24 of the higher floor"""
    w = soul_world()
    ws = w.ws
    m = w.soul_slots[0]
    k = w.soul_of[m]
    for x, y, d, lo, hi in _low_side_of_a_ledge(w):
        w.teleport_monster(m, x, y)
        if ws.mon_floorz[m] != lo:
            continue
        ws.mon_movedir[m] = d
        floats = 0
        for _ in range(40):
            z0 = ws.sk_z[k]
            ev = TicEvents(0)
            assert w._p_move(m, ev)
            if ("float", m) in ev.souls:
                floats += 1
                assert ws.sk_z[k] == z0 + (4 << 16) and ws.sk_inf[k] == 1
            else:
                break
        assert floats == (hi - 24 - lo + 3) // 4 and ws.sk_inf[k] == 0 and ws.mon_floorz[m] == hi
        return
    pytest.skip("no ledge on the map")
