"""M7 P3.2 -- the monsters' SIGHT, as the owner decided it on 2026-09-30 ("Seen rule + set v5";
docs/gp-monsters.md section 8.2, the handoff's 7.2 and D3 e):

  * seen (`mon_seen`): the PREVIOUS frame's picture drew the monster -- its sprite projects in front and one of its
    columns is still open when the walk reaches its leaf, before the budgets (`render_wall_frame(seen_out=)`);
  * waking sight: seen, or REJECT-visible within 128 units (E1M1's REJECT lump, `assets/freedoom1.wad`);
  * attack sight: seen, or within 128 units and the exact 2D LOS (the near-trace).

`SeenHook` is the model's picture after a tic: `World(sight_rule="seen", seen_hook=SeenHook(...))` calls it at the end
of every tic, and it writes `mon_seen` for the next."""
from typing import Optional

NEAR = 128                                    # map units: REJECT wakes, the near-trace attacks, within this


class Reject:
    """REJECT-visibility between two sectors (DOOM's P_CheckSight's first test): bit s1 * nsec + s2 set = s2 NOT
    visible from s1"""

    def __init__(self, data: bytes, nsec: int):
        assert len(data) * 8 >= nsec * nsec, (len(data), nsec)
        self.data, self.nsec = data, nsec

    def visible(self, s1: int, s2: int) -> bool:
        k = s1 * self.nsec + s2
        return not (self.data[k >> 3] >> (k & 7)) & 1


def load_reject(mapname: str = "E1M1", map_wad=None) -> Reject:
    """the map's REJECT: its OWN wad's lump (`map_wad`, the world's; the default map wad when None); else the asset
    wad's for the same map -- the test fixture carries none, and its E1M1 is the asset wad's (same sector count,
    asserted); else ALL VISIBLE, which is how DOOM reads a map with no REJECT (nothing rejected)"""
    from doomfj.wad import WadFile
    if map_wad is None:
        from doomfj.config import DEFAULT_MAP_WAD
        map_wad = WadFile.from_path(DEFAULT_MAP_WAD)
    nsec = len(map_wad.sectors(mapname))
    try:
        return Reject(bytes(map_wad._map_lump(mapname, "REJECT").data), nsec)
    except KeyError:
        pass
    try:
        from doomfj.build import DEFAULT_SPRITE_WAD, _resolve_sprite_wad
        art = _resolve_sprite_wad(map_wad, DEFAULT_SPRITE_WAD)
        if art is not map_wad and mapname in art.names():
            assert len(art.sectors(mapname)) == nsec, "the asset wad's map differs"
            return Reject(bytes(art._map_lump(mapname, "REJECT").data), nsec)
    except (KeyError, ValueError, OSError):
        pass
    return Reject(bytes((nsec * nsec + 7) // 8), nsec)


def _dist(world, m) -> int:
    from doomfj.world import aprox_distance
    return aprox_distance(*world._to_player(m))


def wake_sight(world, m: int) -> bool:
    ws = world.ws
    if ws.mon_seen[m]:
        return True
    if _dist(world, m) > NEAR:
        return False
    return world.reject.visible(world._mon_sector(m), world.player_sector())


def attack_sight(world, m: int) -> bool:
    ws = world.ws
    if getattr(world, "_fight", False) and ws.mon_target[m] >= 2:
        # M7 P8a I (O-B2, TAKEN): a MONSTER target -- the exact 2D LOS to it at any range; the seen mark is the
        # player's picture and NEAR the player's trace, so neither applies
        return world.los_to_target(world, m)
    if ws.mon_seen[m]:
        return True
    return _dist(world, m) <= NEAR and world.los_to_player(world, m)


class SeenHook:
    """after a tic: render the world as the binary draws it and write `mon_seen` -- the monsters whose sprite had an
    open column (docs/gp-monsters.md 8.2)"""

    _cache: dict = {}                         # per map: the art wad, the views mapping, the drawables, the scenes

    def __init__(self, world, sprite_wad=None):
        from doomfj.build import DEFAULT_SPRITE_WAD, _resolve_sprite_wad
        from doomfj.monsters import MonsterViews
        from doomfj.reference_model import GAME_RENDER_KW
        from doomfj.things import drawable_things
        key = (world.mapname, id(sprite_wad))
        if key not in SeenHook._cache:
            art = sprite_wad or _resolve_sprite_wad(world.mw, DEFAULT_SPRITE_WAD)
            SeenHook._cache[key] = (art, MonsterViews(world.rm, world.mw, world.mapname, art, world),
                                    drawable_things(world.rm, world.mw.things(world.mapname), art, {})[0], {})
        self.art, self.views, self.drawable, self._scenes = SeenHook._cache[key]
        self.kw = dict(GAME_RENDER_KW)

    def _scene(self, world):
        from doomfj.reference_model import build_scene
        key = tuple(sorted(world.heights_now.items()))
        if key not in self._scenes:
            self._scenes[key] = build_scene(world.mw, world.mw, world.mapname, dict(world.heights_now))
        return self._scenes[key]

    def __call__(self, world) -> None:
        from doomfj.reference_model import SimState
        ws, n = world.ws, world.layout.nmon
        pos = [(t.x, t.y) for t in self.drawable]
        hidden = set()
        for m in range(n):
            di = self.views.mdi[m]
            pos[di] = (ws.mon_x[m], ws.mon_y[m])
            if not ws.mon_active[m]:
                hidden.add(di)
        views = [None] * self.views.n
        for m, v in self._mviews(world).items():
            views[self.views.mdi[m]] = v
        seen = set()
        # the picture is the BINARY's, whatever instruments the oracle module (scratchpad/gp/census_lib patches
        # reference_model's drawable_things / baked_thing_mask to draw ITS frame): render through the real ones
        from doomfj import reference_model as RMOD, things as TH
        saved = (RMOD.drawable_things, RMOD.baked_thing_mask)
        RMOD.drawable_things, RMOD.baked_thing_mask = TH.drawable_things, TH.baked_thing_mask
        try:
            world.rm.render_wall_frame(SimState(ws.px, ws.py, ws.pangle, world.mapname), self._scene(world),
                                       sprite_wad=self.art, thing_positions=pos, thing_hidden=hidden,
                                       thing_views=views, seen_out=seen, **self.kw)
        finally:
            RMOD.drawable_things, RMOD.baked_thing_mask = saved
        for m in range(n):
            ws.mon_seen[m] = int(self.views.mdi[m] in seen)

    def _mviews(self, world):
        from doomfj.monsters import rotation, view_of
        from doomfj import gamedata as gd
        ws, out = world.ws, {}
        for m in range(world.layout.nmon):
            if not ws.mon_active[m]:
                continue
            st = gd.STATES[gd.STATE_NAMES[ws.mon_state[m]]]
            rot = rotation(world.rm, ws.px, ws.py, ws.mon_x[m] << 16, ws.mon_y[m] << 16, ws.mon_facing[m])
            out[m] = view_of(self.views.patches, st.sprite, st.frame_index, rot)
        return out
