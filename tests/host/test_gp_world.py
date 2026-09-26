"""S3a: the gameplay model's schema, state, collision, leaf lists, sound and sight (`doomfj.world`).

Every property here has a negative control -- a mutation the check must reject -- because a check
that cannot fail proves nothing (docs/cr-rules.md R9)."""
import random

import pytest

from doomfj import gamedata as gd
from doomfj import world as W


@pytest.fixture(scope="module")
def world():
    return W.World(skill=gd.SK_HARD, strict=True)


# ---- schema ------------------------------------------------------------------------------------
def test_the_schema_is_well_formed(world):
    names = [f.name for f in world.schema]
    assert len(names) == len(set(names))
    for f in world.schema:
        assert f.bits > 0 and f.count > 0 and f.nibbles == (f.bits + 3) // 4
        assert f.kind in ("persist", "derived") and f.phase in ("existing", "S3a", "S3b", "P3")
    derived = {f.name for f in world.schema if f.kind == "derived"}
    assert derived == {"mon_leaf", "leaf_head", "mob_next", "proj_leaf", "fx_leaf"}
    by = {f.name: f for f in world.schema}
    assert by["mon_state"].bits >= (len(gd.STATES) - 1).bit_length()
    assert by["mon_leaf"].hi >= world.layout.nleaf - 1
    assert by["sched_cursor"].hi >= world.layout.nmon - 1
    assert by["mob_next"].hi >= world.layout.nmobile           # stores index + 1


def test_the_schema_has_room_for_combat(world):
    """What S3b builds on without a schema change."""
    by = {f.name: f for f in world.schema}
    lay = world.layout
    want = {"p_health": 1, "p_armor": 1, "p_armortype": 1, "p_ammo": gd.NUMAMMO,
            "p_owned": gd.NUMWEAPONS, "p_ready": 1, "p_pending": 1, "p_wpn_state": 1,
            "p_refire": 1, "p_cards": gd.NUMCARDS, "mon_health": lay.nmon,
            "proj_active": W.FIREBALL_POOL, "proj_x": W.FIREBALL_POOL, "fx_state": W.FX_POOL,
            "pickup_taken": lay.npickup, "bar_state": lay.nbarrel, "bar_health": lay.nbarrel,
            "mon_rng": lay.nmon, "rng_world": 1, "rng_player": 1, "rng_fx": 1, "skill": 1}
    for name, count in want.items():
        assert name in by and by[name].count == count, name
    assert (lay.nmon, lay.nbarrel, lay.npickup) == (53, 22, 95)
    assert by["p_health"].signed and by["mon_health"].signed and by["p_health"].bits >= 9


def test_the_schema_table_renders_one_ascii_row_per_field(world):
    text = W.schema_table(world.schema)
    assert text.isascii() and len(text.splitlines()) == len(world.schema) + 2


# ---- WorldState ----------------------------------------------------------------------------------
def test_writes_wrap_to_the_declared_width_like_an_fj_cell(world):
    ws = W.WorldState(world.schema)
    ws.mon_tics[0] = 17                 # 4 bits unsigned
    assert ws.mon_tics[0] == 1
    ws.mon_movecount[0] = 16            # 5 bits signed
    assert ws.mon_movecount[0] == -16
    ws.mon_movecount[0] = -17
    assert ws.mon_movecount[0] == 15
    ws.px = (1 << 31)
    assert ws.px == -(1 << 31)
    with pytest.raises(AttributeError):
        ws.no_such_field = 1
    with pytest.raises(TypeError):
        ws.mon_x = 3                    # an array field is written element by element
    strict = W.WorldState(world.schema, strict=True)
    with pytest.raises(OverflowError):
        strict.mon_tics[0] = 16
    with pytest.raises(OverflowError):
        strict.mon_movecount[0] = -17


def test_the_digest_sees_every_field_and_survives_a_copy(world):
    base = world.ws.digest()
    assert world.ws.copy().digest() == base
    for f in world.schema:              # R9: a one-unit change anywhere moves the digest
        c = world.ws.copy()
        if f.count == 1:
            setattr(c, f.name, getattr(c, f.name) ^ 1)
        else:
            arr = getattr(c, f.name)
            arr[f.count - 1] = arr[f.count - 1] ^ 1
        assert c.digest() != base, f.name


# ---- level start ---------------------------------------------------------------------------------
@pytest.mark.parametrize("skill,active", [(gd.SK_EASY, 17), (gd.SK_MEDIUM, 29), (gd.SK_HARD, 46)])
def test_the_skill_decides_what_spawns(skill, active):
    w = W.World(skill=skill)
    assert sum(w.ws.mon_active) == active
    assert sum(len(v) for v in w.leaf_lists().values()) == active
    assert sum(w.ws.bar_solid) == sum(1 for t in w.barrel_things if t.flags & gd.skill_bit(skill))


def test_level_start_is_doom_like(world):
    ws = world.ws
    for m in range(world.layout.nmon):
        info, t = world.mon_info[m], world.mon_things[m]
        assert (ws.mon_x[m], ws.mon_y[m]) == (t.x, t.y)
        assert ws.mon_facing[m] == (t.angle // 45) % 8 and ws.mon_movedir[m] == gd.DI_EAST
        assert ws.mon_health[m] == info.spawnhealth and ws.mon_reaction[m] == 8
        if ws.mon_active[m]:
            assert gd.STATE_NAMES[ws.mon_state[m]] == info.spawnstate
            assert 1 <= ws.mon_tics[m] <= gd.STATES[info.spawnstate].tics   # the phase roll
            assert ws.mon_ambush[m] == (1 if t.flags & gd.MTF_AMBUSH else 0)
    assert ws.p_health == 100 and ws.p_ammo[gd.AM_CLIP] == 50 and ws.p_ready == gd.WP_PISTOL
    assert len({ws.mon_tics[m] for m in range(world.layout.nmon) if ws.mon_active[m]}) > 3
    assert world.leaf_lists() == world.leaf_lists_from_scratch()


# ---- collision -----------------------------------------------------------------------------------
def test_the_line_test_agrees_with_the_oracle(world):
    """With monster rules off, `check_lines` is `ReferenceModel.check_position`: same verdict, same
    floor and ceiling, over a sample of the whole map -- both outcomes required (vacuity)."""
    xs = [v[0] for v in world.cmap.vertexes]
    ys = [v[1] for v in world.cmap.vertexes]
    rnd = random.Random(7)
    seen = {True: 0, False: 0}
    for _ in range(600):
        x16 = rnd.randint(min(xs), max(xs)) << 16 | rnd.randrange(0, 65536, 4096)
        y16 = rnd.randint(min(ys), max(ys)) << 16 | rnd.randrange(0, 65536, 4096)
        verdict, floor, ceil, _drop = world.check_lines(x16, y16, W.PLAYER_R << 16, monster=False)
        ok, of, oc = world.rm.check_position(world.scene_c, x16, y16)
        assert (verdict == W.OK, floor, ceil) == (ok, of, oc), (x16, y16)
        seen[ok] += 1
    assert seen[True] > 50 and seen[False] > 50


def test_monster_blocking_lines_stop_monsters_and_not_the_player(world):
    hits = 0
    for (li, _a, _b, _c, _d, ax, ay, bx, by, one, flags, _fs, _bs) in world._lines:
        if one or not flags & gd.ML_BLOCKMONSTERS:
            continue
        x16, y16 = (ax + bx) // 2, (ay + by) // 2
        mon = world.check_lines(x16, y16, 20 << 16, monster=True)[0]
        ply = world.check_lines(x16, y16, 20 << 16, monster=False)[0]
        assert mon != W.OK, li
        hits += mon == W.V_MONLINE and ply == W.OK
    assert hits > 0


def test_a_monster_cannot_step_through_a_wall(world):
    """For every long axis-aligned one-sided line: a monster just clear of it, stepping at it,
    is refused -- and the same step AWAY from it is not refused for being a wall."""
    w = W.World(skill=gd.SK_HARD)
    ws, m = w.ws, 0
    # only the wall may answer: no other monster, barrel, decor or player in the way
    for j in range(w.layout.nmon):
        ws.mon_solid[j] = 0
    for b in range(w.layout.nbarrel):
        ws.bar_solid[b] = 0
    w._decor_now = []
    ws.px = ws.py = -(1 << 31)
    ws.mon_active[m], ws.mon_solid[m] = 1, 1
    refused = 0
    for (li, x0, x1, y0, y1, ax, ay, bx, by, one, _f, fs, _bs) in w._lines:
        if not one or (ax != bx and ay != by) or max(x1 - x0, y1 - y0) < (96 << 16):
            continue
        # the side the sector is on: DOOM's front side is to the RIGHT of v1 -> v2
        dxl, dyl = (bx - ax) >> 16, (by - ay) >> 16
        nx, ny = ((dyl > 0) - (dyl < 0)), -((dxl > 0) - (dxl < 0))     # right-hand normal
        mx, my = (ax + bx) // 2 >> 16, (ay + by) // 2 >> 16
        px, py = mx + nx * 21, my + ny * 21                              # 1 unit clear (r = 20)
        ws.mon_x[m], ws.mon_y[m] = px, py
        leaf = w.rm.point_in_subsector(w.cmap, px, py)
        ws.mon_floorz[m] = w.secs_c[w.leaf_sector[leaf]].floor_h
        if w.check_lines(px << 16, py << 16, 20 << 16, monster=True)[0] != W.OK:
            continue                                                     # not a free spot
        verdict, _ = w.try_move_monster(m, px - nx * 8, py - ny * 8)
        assert verdict == W.V_WALL, (li, verdict)
        refused += 1
    assert refused > 20


# ---- leaf lists ----------------------------------------------------------------------------------
def _fight(w, tics):
    w.wake_all()
    changes = 0
    for _ in range(tics):
        changes += len(w.tic({}).leaf_changes)
        if w.leaf_lists() != w.leaf_lists_from_scratch():
            return changes, False
    return changes, True


def test_leaf_lists_stay_equal_to_a_rebuild():
    w = W.World(skill=gd.SK_HARD, k_heavy=53)
    changes, same = _fight(w, 150)
    assert same and changes > 20


def test_the_list_check_catches_doom_style_prepending(monkeypatch):
    """R9: DOOM's own P_SetThingPosition prepends. Planted here, the ascending-order invariant
    must break (a leaf holds two monsters at spawn, and more once they converge)."""
    def prepend(self, k, leaf):
        self.ws.mob_next[k] = self.ws.leaf_head[leaf]
        self.ws.leaf_head[leaf] = k + 1
    monkeypatch.setattr(W.World, "_list_insert", prepend)
    w = W.World(skill=gd.SK_HARD, k_heavy=53)
    _changes, same = _fight(w, 150)
    assert not same


# ---- sound ---------------------------------------------------------------------------------------
def _recursive_sound(w, start):
    """P_RecursiveSound over SECTORS with this tic's heights (no soundblock lines on E1M1)."""
    adj = {}
    for ld in w.lds:
        if not ld.flags & gd.ML_TWOSIDED or ld.back < 0:
            continue
        a, b = w.sds[ld.front].sector, w.sds[ld.back].sector
        (fa, ca), (fb, cb) = w._sector_hts(a), w._sector_hts(b)
        if a != b and min(ca, cb) - max(fa, fb) > 0:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    seen, stack = {start}, [start]
    while stack:
        for n in adj.get(stack.pop(), ()):
            if n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


@pytest.mark.parametrize("doors", ["shut", "open", "mixed"])
def test_sound_regions_equal_dooms_flood_fill(doors):
    w = W.World(skill=gd.SK_HARD)
    rnd = random.Random(3)
    for d, si in enumerate(w.door_order):
        top = w.door_nstates[si] - 1
        w.ws.d_state[d] = {"shut": 0, "open": top, "mixed": rnd.randint(0, top)}[doors]
    w._door_phase_scene()
    for start in range(len(w.secs)):
        for k in range(w.layout.nsound):
            w.ws.snd_alert[k] = 0
        # stand the player in `start` by asking for it directly
        w.player_sector = lambda s=start: s
        w.noise_alert()
        want = {w.sector_node[s] for s in _recursive_sound(w, start)}
        got = {k for k in range(w.layout.nsound) if w.ws.snd_alert[k]}
        assert got == want, (doors, start)


def test_an_open_door_carries_sound_further_than_a_shut_one():
    w = W.World(skill=gd.SK_HARD)
    w.noise_alert()
    shut = sum(w.ws.snd_alert)
    for d, si in enumerate(w.door_order):
        w.ws.d_state[d] = w.door_nstates[si] - 1
    w._door_phase_scene()
    w.noise_alert()
    assert sum(w.ws.snd_alert) > shut


# ---- sight ---------------------------------------------------------------------------------------
def test_a_shut_door_blocks_sight_and_an_open_one_does_not():
    w = W.World(skill=gd.SK_HARD)
    ws, m = w.ws, 0
    both = 0
    for d, si in enumerate(w.door_order):
        faces = [w._lines[li] for li in w.door_lines[si]]
        if len(faces) < 2:
            continue
        (_, _, _, _, _, ax, ay, bx, by, *_r), (_, _, _, _, _, cx, cy, ex, ey, *_s) = faces[:2]
        m1 = ((ax + bx) // 2 >> 16, (ay + by) // 2 >> 16)
        m2 = ((cx + ex) // 2 >> 16, (cy + ey) // 2 >> 16)
        ux, uy = m2[0] - m1[0], m2[1] - m1[1]
        if ux == 0 and uy == 0:
            continue
        ws.mon_x[m], ws.mon_y[m] = m1[0] - ux, m1[1] - uy
        ws.px, ws.py = (m2[0] + ux) << 16, (m2[1] + uy) << 16
        ws.d_state[d] = 0
        w._door_phase_scene()
        assert not W.World.los_to_player(w, m), si
        ws.d_state[d] = w.door_nstates[si] - 1
        w._door_phase_scene()
        both += W.World.los_to_player(w, m)
        ws.d_state[d] = 0
    assert both > 0


def test_sight_from_the_spawn_is_what_it_was():
    """A pin on the default sight at level start (hard): three sleeping monsters see the player's
    start, all of them ambushers. A change here is a change to the rules of the game."""
    w = W.World(skill=gd.SK_HARD)
    seen = [m for m in range(w.layout.nmon) if w.ws.mon_active[m] and w.sight(w, m)]
    assert seen == [21, 22, 23] and all(w.ws.mon_ambush[m] for m in seen)


# ---- monsters and doors --------------------------------------------------------------------------
def test_monsters_may_open_only_plain_doors(world):
    assert set(world.mon_door_boxes) == set(world.door_order) - {51, 71, 84}   # blue-key, blazing


def test_a_monster_bumping_a_shut_door_opens_it():
    w = W.World(skill=gd.SK_HARD)
    ws, m = w.ws, 0
    d, si = 0, w.door_order[0]
    faces = [w._lines[li] for li in w.door_lines[si]]
    (_, _, _, _, _, ax, ay, bx, by, *_r) = faces[0]
    fx, fy = (ax + bx) // 2 >> 16, (ay + by) // 2 >> 16
    for dirn in range(8):                     # the first free spot, 24 units out, facing the door
        sx, sy = W.step_delta(8, dirn)
        px, py = fx - 3 * sx, fy - 3 * sy
        leaf = w.rm.point_in_subsector(w.cmap, px, py)
        if w.check_lines(px << 16, py << 16, 20 << 16, monster=True)[0] != W.OK:
            continue
        ws.mon_x[m], ws.mon_y[m] = px, py
        ws.mon_floorz[m] = w.secs_c[w.leaf_sector[leaf]].floor_h
        ws.mon_movedir[m] = dirn
        ev = W.TicEvents(0)
        for _ in range(4):                    # walk into the door
            if not w._p_move(m, ev) or ev.door_uses:
                break
        if ev.door_uses:
            break
    assert ev.door_uses and ev.door_uses[0][1] == si and ws.d_monreq[d] == 1
    ws.mon_active[m] = 0                      # keep the slot out of the tic
    w.tic({})
    assert ws.d_state[d] == 1 and ws.d_monreq[d] == 0
