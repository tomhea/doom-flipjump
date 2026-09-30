"""M7 P3 -- the monsters' shared rules (docs/gp-monsters.md): the model's monster phase as the gate oracles' frame
(`MonsterPhase`, as `doors.DoorPhase` / `movers.MoverPhase` are for doors and lifts), and the ONE rule for the sprite
view a monster is drawn with -- its state's frame at DOOM's rotation for this viewer -- which the oracle draws with
and the fj mirrors.

The rotation is R_ProjectSprite's: `rot = ((R_PointToAngle(thing) - thing.angle + ANG45/2*9) >> 29) + 1`, the
viewer-to-thing angle from `ReferenceModel.point_to_angle` (the fj's `proj.point_to_angle`), the thing's angle its
facing octant times ANG45. A frame drawn from a `...0` lump has one view; otherwise rotation r reads the lump named
for r, MIRRORED when r is the lump's second half (`TROOA2A8` is rotation 2 and, mirrored, rotation 8)."""
from typing import Dict, Optional, Tuple

ANG45 = 0x20000000
MASK32 = 0xFFFFFFFF


def rotation(rm, view_x16: int, view_y16: int, thing_x16: int, thing_y16: int, facing: int) -> int:
    """DOOM's sprite rotation 1..8 of a thing facing octant `facing`, seen from (view_x16, view_y16)"""
    ang = rm.point_to_angle(view_x16, view_y16, thing_x16, thing_y16)
    return (((ang - facing * ANG45 + (ANG45 // 2) * 9) & MASK32) >> 29) + 1


def view_of(patches: dict, sprite: str, frame: int, rot: int) -> Tuple[str, bool]:
    """(lump, mirrored) for a frame index at rotation `rot`, from `wall_renderer.anim_patches`' map"""
    letter = chr(ord("A") + frame)
    v = patches.get((sprite, letter, 0))
    return v if v is not None else patches[(sprite, letter, rot)]


class MonsterPhase:
    """The gate oracles' monster frame: the MODEL's own monster phase (`World._monsters_phase`) in a model mode
    (`World(monsters=...)`), stepped once per game frame after the player, and read for drawing. Nothing here
    re-implements a monster rule."""

    def __init__(self, map_wad=None, mapname: str = "E1M1", skill: Optional[int] = None, *, mode: str = "idle",
                 rm=None):
        from doomfj import gamedata as gd
        from doomfj.world import World
        self.world = World(map_wad, mapname, gd.SK_HARD if skill is None else skill, rm=rm, monsters=mode)
        self.gd = gd

    def reset(self, skill: int) -> None:
        self.world.reset(skill)

    def tic(self) -> None:
        from doomfj.world import TicEvents
        self.world._monsters_phase(TicEvents(0))

    def state(self) -> Dict[str, tuple]:
        """the cells the fj holds per monster slot: (mon_state, mon_tics, mon_facing, mon_active)"""
        ws = self.world.ws
        n = self.world.layout.nmon
        return {"mon_state": tuple(ws.mon_state[:n]), "mon_tics": tuple(ws.mon_tics[:n]),
                "mon_facing": tuple(ws.mon_facing[:n]), "mon_active": tuple(ws.mon_active[:n])}

    def views(self, rm, patches: dict, view_x16: int, view_y16: int) -> Dict[int, Tuple[str, bool]]:
        """{monster slot: (lump, mirrored)} for every active monster, seen from the viewer"""
        gd, ws, out = self.gd, self.world.ws, {}
        for m in range(self.world.layout.nmon):
            if not ws.mon_active[m]:
                continue
            st = gd.STATES[gd.STATE_NAMES[ws.mon_state[m]]]
            rot = rotation(rm, view_x16, view_y16, ws.mon_x[m] << 16, ws.mon_y[m] << 16, ws.mon_facing[m])
            out[m] = view_of(patches, st.sprite, st.frame_index, rot)
        return out


class MonsterViews:
    """`render_wall_frame(thing_views=...)` for a MonsterPhase: the monsters' views in the render's DRAWABLE order
    (`things.drawable_things`, the index space the emitter bakes by), None for every other thing. One mapping for
    every gate, matched on the WAD thing (type, x, y, angle, flags)."""

    def __init__(self, rm, map_wad, mapname: str, sprite_wad, world):
        from doomfj.things import drawable_things
        from doomfj.wall_renderer import anim_frames, anim_patches
        drawable, _ = drawable_things(rm, map_wad.things(mapname), sprite_wad, {})
        key = {(t.type, t.x, t.y, t.angle, t.flags): i for i, t in enumerate(drawable)}
        self.n = len(drawable)
        self.mdi = [key[(t.type, t.x, t.y, t.angle, t.flags)] for t in world.mon_things]
        self.patches = anim_patches(sprite_wad, anim_frames(map_wad, mapname))
        self.rm = rm

    def __call__(self, phase: "MonsterPhase", x16: int, y16: int) -> list:
        out = [None] * self.n
        for m, v in phase.views(self.rm, self.patches, x16, y16).items():
            out[self.mdi[m]] = v
        return out
