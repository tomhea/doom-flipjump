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


def mobile_rows(world) -> int:
    """M7 P5 (docs/gp-p5-interface.md): the runtime-thing rows the MOBILES add after the WAD's runtime things -- fireball
    slot s is row nt + s (s < FIREBALL_POOL), blood slot s row nt + FIREBALL_POOL + s -- in a world whose monsters
    spawn fireballs ("full") or whose player's shots bleed (world.player_bleeds); 0 before P5"""
    from doomfj.world import FIREBALL_POOL, FX_POOL, player_bleeds
    return FIREBALL_POOL + FX_POOL if (world.monsters == "full" or player_bleeds(world.player)) else 0


def mobile_lump(state_name: str) -> str:
    """M7 P5: the sprite lump a mobile (fireball, blood, puff) is drawn with in state `state_name` -- its frame's
    single-rotation `...0` lump (BAL1A0 .. BAL1E0, BLUDA0 .. BLUDC0, PUFFA0 .. PUFFD0)"""
    from doomfj import gamedata as gd
    st = gd.STATES[state_name]
    return "%s%s0" % (st.sprite, chr(ord("A") + st.frame_index))


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
                 rm=None, player: str = "walk"):
        from doomfj import gamedata as gd
        from doomfj.world import World
        # M7 P3.2a: a mode that wakes sees by the picture (docs/gp-monsters.md 8.2) -- the gate hands it the
        # seen set of the picture it drew (`set_seen`), as the binary's render writes its flags
        # M7 P4.1: the PLAYER's model mode too (world.PLAYER_MODES; the gates pass wall_renderer.PLAYER_MODE) -- the
        # weapon half below steps the player's weapon in the same world the monsters live in
        # M7 P4.2a: a player whose shots resolve aims with THE PICTURE's window (combat.window_aim), which the gate
        # writes from each render's `aim_out` (`set_aim`), as the binary's render writes `aim_sid`
        from doomfj.world import player_resolves
        aim = World.window_aim if player_resolves(player) else None
        self.world = World(map_wad, mapname, gd.SK_HARD if skill is None else skill, rm=rm, monsters=mode,
                           sight_rule="los" if mode == "idle" else "seen", player=player, aim=aim)
        self.gd = gd

    def reset(self, skill: int) -> None:
        self.world.reset(skill)

    def tic(self, x16: Optional[int] = None, y16: Optional[int] = None, angle: Optional[int] = None):
        """one monster tic -- the player where the gate's world put him this frame (the wake mode looks at him).
        M7 P5: and then the rest of world.tic's order after the monsters -- the fireballs, the barrels, the effects
        (`_projectiles_phase`, `_barrels_phase`, `_fx_phase`; before P5 nothing spawns into the pools and the barrels
        only animate). -> the tic's events (also kept as `last_tic`)"""
        from doomfj.world import TicEvents
        w = self.world
        ws = w.ws
        if x16 is not None:
            ws.px = x16 - (1 << 32) if x16 >> 31 & 1 else x16
            ws.py = y16 - (1 << 32) if y16 >> 31 & 1 else y16
            ws.pangle = angle & 0xFFFFFFFF
        ev = TicEvents(0)
        w._monsters_phase(ev)
        w._projectiles_phase(ev)
        w._barrels_phase(ev)
        w._fx_phase(ev)
        self.last_tic = ev
        return ev

    # ---- M7 P3.2b "chase": the monsters and the gate's doors and lifts act on each other ------------------------
    def sync(self, doors: dict, lifts: tuple, switched: int) -> None:
        """the gate's doors {sector: (state, dir, sub, wait)}, lifts ((state, dir, sub, wait) per lift, sector order)
        and floor switch this frame -> the monsters' collision scene (World._door_phase_scene, which also sets the
        floor of every monster standing on a mover that moved -- P_ChangeSector)"""
        w, ws = self.world, self.world.ws
        for d, si in enumerate(w.door_order):
            ws.d_state[d], ws.d_dir[d], ws.d_sub[d], ws.d_wait[d] = doors[si]
        for k, st in enumerate(lifts):
            ws.l_state[k], ws.l_dir[k], ws.l_sub[k], ws.l_wait[k] = st
        ws.f_switch = int(bool(switched))
        w._door_phase_scene()

    def requests(self) -> Tuple[frozenset, frozenset]:
        """(door sectors the monsters pressed, lift sectors they triggered) this tic -- the gate's next door and
        mover phases take them (`DoorPhase` / `MoverPhase` state `req`); cleared here, as the model's phases do"""
        w, ws = self.world, self.world.ws
        doors = frozenset(si for d, si in enumerate(w.door_order) if ws.d_monreq[d])
        lifts = frozenset(si for k, si in enumerate(w.lift_order) if ws.l_req[k])
        for d in range(len(w.door_order)):
            ws.d_monreq[d] = 0
        for k in range(len(w.lift_order)):
            ws.l_req[k] = 0
        return doors, lifts

    def frame(self, dps, mps, x16: int, y16: int, angle: int):
        """M7 P3.2b: ONE world frame of the monsters inside a gate, after its door, lift and player phases -- the
        gate's doors (a `doors.DoorPhase` state) and movers (a `movers.MoverPhase` state, or None) into the monsters'
        world, the tic with the player's pose, and the monsters' door presses and lift triggers handed back into the
        two states' `req` for the next frame -> (dps, mps). Idle and wake monsters press nothing, so it is the plain
        tic for them."""
        ds, fired, req, card = dps
        lifts, lreq, sw = mps if mps is not None else ((), frozenset(), 0)
        self.sync(ds, lifts, sw)
        self.tic(x16, y16, angle)
        dr, lr = self.requests()
        return (ds, fired, frozenset(req) | dr, card), ((lifts, frozenset(lreq) | lr, sw) if mps is not None else None)

    # ---- M7 P4.1: the weapon half (docs/gp-combat.md section 1) -------------------------------------------------------
    def weapon(self, keys: dict, x16: Optional[int] = None, y16: Optional[int] = None,
               angle: Optional[int] = None):
        """ONE world frame of the player's weapon: the number keys, then P_MovePsprites -- the model's own
        (`combat._weapon_keys`, `_weapon_tics`: M7 P6+P7, world.WEAPON_TICS passes) in the world's player mode. A gate calls it on every world frame
        that tics (not a menu frame, not a finished level), with the frame's held keys. M7 P4.2a: and with the
        player's PRE-MOVE pose -- the binary's weapon runs before the player's move, so a melee reach and a shot's
        target are measured from where the player stood when the frame began. -> the tic's events"""
        from doomfj.world import KEYS, TicEvents
        w = self.world
        if w.player == "walk":
            return TicEvents(0)
        if x16 is not None:
            ws = w.ws
            ws.px = x16 - (1 << 32) if x16 >> 31 & 1 else x16
            ws.py = y16 - (1 << 32) if y16 >> 31 & 1 else y16
            ws.pangle = angle & 0xFFFFFFFF
        k = {n: bool(keys.get(n)) for n in KEYS}
        ev = TicEvents(0)
        ws = w.ws
        if ws.p_dead:                     # M7 P5: P_DeathThink's weapon half (the restart on use is P7's)
            w._weapon_tics(k, ev)         # M7 P6+P7: world.WEAPON_TICS passes, as the model's player phase
            if ws.p_damagecount:
                ws.p_damagecount -= 1
            return ev
        w._weapon_keys(k)
        w._weapon_tics(k, ev)
        # M7 P5: the flashes fade after the psprites, in the model's player-phase order (combat._player_phase)
        if ws.p_damagecount:
            ws.p_damagecount -= 1
        if ws.p_bonuscount:
            ws.p_bonuscount -= 1
        return ev

    def weapon_state(self) -> Dict[str, int]:
        """the weapon's fj cells (doomfj.weaponcode), in the cells' own units: the psprite states as LOCAL indices"""
        if self.world.player == "walk":
            return {}
        from doomfj import weaponcode as WC
        from doomfj.world import player_resolves
        ws, gd = self.world.ws, self.gd
        idx = {gd.STATE_INDEX[s]: i for i, s in enumerate(WC.weapon_states())}
        wst, fst = gd.STATE_NAMES[ws.p_wpn_state], gd.STATE_NAMES[ws.p_flash_state]
        return {"wp_rdy": ws.p_ready, "wp_pend": ws.p_pending, "wp_st": idx[ws.p_wpn_state], "wp_tics": ws.p_wpn_tics,
                "wp_sy": ws.p_wpn_sy, "fl_st": idx[ws.p_flash_state], "fl_tics": ws.p_flash_tics,
                "wp_rf": ws.p_refire, "wp_ad": ws.p_attackdown, "am_clip": ws.p_ammo[gd.AM_CLIP],
                "am_shell": ws.p_ammo[gd.AM_SHELL],
                "wp_own": sum(int(bool(ws.p_owned[w])) << (4 * i) for i, w in enumerate(WC.WEAPONS)),
                **({"aim_sid": tuple(ws.aim_sid)} if player_resolves(self.world.player) else {}),
                "rng_pl": ws.rng_player, "wp_frm": WC.overlay_frames().index(WC.psprite_lump(wst)),
                "fl_frm": 0 if fst == gd.S_NULL or gd.STATES[fst].tics == 0
                else 1 + WC.flash_frames().index(WC.psprite_lump(fst))}

    def screen_kw(self) -> dict:
        """`hud.GameScreen.frame`'s keywords for the player's weapon and bar: the psprites' lumps and the values"""
        if self.world.player == "walk":
            return {}
        from doomfj import weaponcode as WC
        ws, gd = self.world.ws, self.gd
        fst = gd.STATE_NAMES[ws.p_flash_state]
        ammo = {gd.WP_PISTOL: ws.p_ammo[gd.AM_CLIP], gd.WP_SHOTGUN: ws.p_ammo[gd.AM_SHELL]}.get(ws.p_ready)
        return {"weapon": WC.psprite_lump(gd.STATE_NAMES[ws.p_wpn_state]),
                "flash": None if fst == gd.S_NULL or gd.STATES[fst].tics == 0 else WC.psprite_lump(fst),
                "values": {"ammo": ammo, "health": max(0, ws.p_health), "armor": ws.p_armor,
                           "owned": (bool(ws.p_owned[gd.WP_PISTOL]), bool(ws.p_owned[gd.WP_SHOTGUN]),
                                     bool(ws.p_owned[gd.WP_CHAINSAW]))}}

    def boxes(self) -> list:
        """[(x16, y16, r16)] of every live monster -- a closing door reverses on them (World.door_touched)"""
        w, ws = self.world, self.world.ws
        return [(ws.mon_x[m] << 16, ws.mon_y[m] << 16, w.mon_radius[m] << 16) for m in range(w.layout.nmon)
                if ws.mon_active[m] and ws.mon_health[m] > 0]

    def set_seen(self, slots) -> None:
        """the picture just drawn: its seen monsters (slots) are the next tic's `mon_seen`"""
        ws = self.world.ws
        for m in range(self.world.layout.nmon):
            ws.mon_seen[m] = int(m in slots)

    def set_aim(self, cells) -> None:
        """M7 P4.2a: the picture just drawn: its aim window (`render_wall_frame(aim_out=)`, 17 sids) is the next tic's
        `aim_sid` -- what `combat.window_aim` reads (docs/gp-aim-window.md 6)"""
        arr = self.world.ws.aim_sid
        assert len(cells) == len(arr), (len(cells), len(arr))
        for i, v in enumerate(cells):
            arr[i] = v

    def state(self) -> Dict[str, tuple]:
        """the cells the fj holds per monster slot: (mon_state, mon_tics, mon_facing, mon_active)"""
        ws = self.world.ws
        n = self.world.layout.nmon
        out = {"mon_state": tuple(ws.mon_state[:n]), "mon_tics": tuple(ws.mon_tics[:n]),
               "mon_facing": tuple(ws.mon_facing[:n]), "mon_active": tuple(ws.mon_active[:n])}
        if self.world.monsters != "idle":        # M7 P3.2a: the wake mode's cells, and the seen flags
            out.update({"mon_target": tuple(ws.mon_target[:n]), "mon_reaction": tuple(ws.mon_reaction[:n]),
                        "mon_threshold": tuple(ws.mon_threshold[:n]), "mon_movedir": tuple(ws.mon_movedir[:n]),
                        "sched_cursor": ws.sched_cursor, "thseen": tuple(ws.mon_seen[:n])})
        if self.world.monsters not in ("idle", "wake"):   # M7 P3.2b: the move's cells (the position is thpos_rt,
            out.update({"mon_movecount": tuple(v & 0xFF for v in ws.mon_movecount[:n]),   # the leaf thss_rt)
                        "mon_rng": tuple(ws.mon_rng[:n]),
                        "mon_floorz": tuple(v & 0xFFFF for v in ws.mon_floorz[:n]),
                        "msec": tuple(self.world._mon_sector(m) for m in range(n))})
        if self.world.monsters not in ("idle", "wake", "chase"):   # M7 P3.2c: the missile decision's flag
            out["mon_justattacked"] = tuple(ws.mon_justattacked[:n])
        from doomfj.world import player_bleeds, player_hears, player_resolves
        if player_resolves(self.world.player):                  # M7 P4.2a: the damage's cells (health in its 12 bits)
            out.update({"mon_health": tuple(v & 0xFFF for v in ws.mon_health[:n]),
                        "mon_shootable": tuple(ws.mon_shootable[:n]), "mon_solid": tuple(ws.mon_solid[:n]),
                        "mon_justhit": tuple(ws.mon_justhit[:n])})
        if player_hears(self.world.player):                     # M7 P4.2b: who heard, who still waits in ambush
            out.update({"mon_ambush": tuple(ws.mon_ambush[:n]), "snd_alert": tuple(ws.snd_alert)})
        if self.world.monsters == "full":                        # M7 P5: the attacks land -- hurtcode's player cells
            out.update(self.hurt_state())                        # and projcode's fireball pool
            out.update(self.proj_state())
        if self.world.monsters == "full" or player_bleeds(self.world.player):   # M7 P5: the blood pool, its stream
            out.update(self.fx_state())
        return out

    # ---- M7 P5: the monsters' attacks (docs/gp-p5-interface.md, "the cells' units") -----------------------------------
    def hurt_state(self) -> Dict[str, int]:
        """hurtcode's player cells in their own units: p_hp the health's 12 bits (3 nibbles, two's complement -- a
        killing blow takes it below 0), p_ar the armor points (2 nibbles, 0..200), p_at the armor type (0 none,
        1 green, 2 blue), p_dc the damage count (2 nibbles, 0..100), p_dead (PST_DEAD, 0/1)"""
        ws = self.world.ws
        return {"p_hp": ws.p_health & 0xFFF, "p_ar": ws.p_armor, "p_at": ws.p_armortype, "p_dc": ws.p_damagecount,
                "p_dead": ws.p_dead}

    def proj_state(self) -> Dict[str, tuple]:
        """projcode's fireball pool, per slot (FIREBALL_POOL of them): pj_act 0/1; pj_x / pj_y the 16.16 position and
        pj_mx / pj_my the 16.16 momentum, each its 32 bits unsigned (8 nibbles); pj_st the GAMEDATA state index (2
        nibbles: S_TBALL1 .. S_TBALLX3); pj_ti the tics left (1 nibble). A free slot is all zeros (the model's
        P_RemoveMobj zeroes it, and so does the level start)"""
        ws = self.world.ws
        return {"pj_act": tuple(ws.proj_active), "pj_x": tuple(v & MASK32 for v in ws.proj_x),
                "pj_y": tuple(v & MASK32 for v in ws.proj_y), "pj_mx": tuple(v & MASK32 for v in ws.proj_momx),
                "pj_my": tuple(v & MASK32 for v in ws.proj_momy), "pj_st": tuple(ws.proj_state),
                "pj_ti": tuple(ws.proj_tics)}

    def fx_state(self) -> Dict[str, object]:
        """projcode's blood pool, per slot (FX_POOL of them), in pj_*'s units (fx_x / fx_y always whole map units: the
        spawn point is one), and the effects' stream rng_fx (2 nibbles)"""
        ws = self.world.ws
        return {"fx_act": tuple(ws.fx_active), "fx_x": tuple(v & MASK32 for v in ws.fx_x),
                "fx_y": tuple(v & MASK32 for v in ws.fx_y), "fx_st": tuple(ws.fx_state),
                "fx_ti": tuple(ws.fx_tics), "rng_fx": ws.rng_fx}

    def palette(self) -> int:
        """the PLAYPAL index this world frame is shown with (combat.palette_index: ST_doPaletteStuff)"""
        from doomfj.combat import palette_index
        return palette_index(self.world.ws)

    def mobiles(self) -> list:
        """`render_wall_frame(mobiles=...)`: [(x, y, lump)] of every live mobile in ROW order -- the fireball slots,
        then the blood slots -- at its whole map units (the 16.16 position floored: its thpos_rt row carries no
        fraction), drawn with its state's frame (`mobile_lump`)"""
        from doomfj.world import FIREBALL_POOL, FX_POOL
        ws, gd, out = self.world.ws, self.gd, []
        for s in range(FIREBALL_POOL):
            if ws.proj_active[s]:
                out.append((ws.proj_x[s] >> 16, ws.proj_y[s] >> 16, mobile_lump(gd.STATE_NAMES[ws.proj_state[s]])))
        for s in range(FX_POOL):
            if ws.fx_active[s]:
                out.append((ws.fx_x[s] >> 16, ws.fx_y[s] >> 16, mobile_lump(gd.STATE_NAMES[ws.fx_state[s]])))
        return out

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
        drawable, draw_idx = drawable_things(rm, map_wad.things(mapname), sprite_wad, {})
        key = {(t.type, t.x, t.y, t.angle, t.flags): i for i, t in enumerate(drawable)}
        self.n = len(drawable)
        self.mdi = [key[(t.type, t.x, t.y, t.angle, t.flags)] for t in world.mon_things]
        self.patches = anim_patches(sprite_wad, anim_frames(map_wad, mapname))
        self.rm = rm
        # M7 P3.2b: the RUNTIME things, as the emitter picks them (wall_renderer's `_mt_keep`: the drawables
        # `baked_thing_mask` leaves unbaked, in WAD order) -- the index space of thpos_rt / thss_rt
        from doomfj.mapcompiler import bake_bsp
        from doomfj.reference_model import MONSTER_TYPES
        from doomfj.things import baked_thing_mask
        self.drawable = drawable
        self.cmap = bake_bsp(map_wad, mapname)
        baked = baked_thing_mask(rm, self.cmap, drawable, MONSTER_TYPES)
        keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
        self.rt_drawable = [draw_idx.index(i) for i in keep]          # runtime thing t -> drawable index
        self.nrt = len(keep)
        self.rt = [keep.index(draw_idx[di]) for di in self.mdi]      # slot -> runtime thing

    def positions(self, phase: "MonsterPhase") -> list:
        """M7 P3.2b: `render_wall_frame(thing_positions=...)` -- every drawable where it stands, the monsters where
        the phase has moved them (map units)"""
        ws = phase.world.ws
        out = [(t.x, t.y) for t in self.drawable]
        for m, di in enumerate(self.mdi):
            out[di] = (ws.mon_x[m], ws.mon_y[m])
        return out

    def rt_state(self, phase: "MonsterPhase") -> dict:
        """M7 P3.2b: the runtime things' `thpos_rt` (16.16 x | y << 32) and `thss_rt` (the leaf) as the probe reads
        them -- the monsters where the phase has them, every other runtime thing at its spawn.
        M7 P5: then the MOBILE rows (`mobile_rows`): fireball slot s at row nrt + s, blood slot s at nrt +
        FIREBALL_POOL + s -- a live slot's whole-unit position (16.16 with the fraction ZERO: `MonsterPhase.mobiles`'
        x, y) and its leaf (the model's proj_leaf / fx_leaf), a free slot (0, 0)"""
        from doomfj.world import FIREBALL_POOL, FX_POOL
        ws, pos = phase.world.ws, self.positions(phase)
        M = 0xFFFFFFFF
        thpos, thss = [], []
        for di in self.rt_drawable:
            x, y = pos[di]
            thpos.append(((x << 16) & M) | (((y << 16) & M) << 32))
            thss.append(self.rm.point_in_subsector(self.cmap, x, y))
        for m, t in enumerate(self.rt):                   # a monster's leaf is the model's own
            thss[t] = ws.mon_leaf[m]
        if mobile_rows(phase.world):
            for act, xs, ys, leaf, n in ((ws.proj_active, ws.proj_x, ws.proj_y, ws.proj_leaf, FIREBALL_POOL),
                                         (ws.fx_active, ws.fx_x, ws.fx_y, ws.fx_leaf, FX_POOL)):
                for s in range(n):
                    live = bool(act[s])
                    thpos.append(((((xs[s] >> 16) << 16) & M) | ((((ys[s] >> 16) << 16) & M) << 32)) if live else 0)
                    thss.append(leaf[s] if live else 0)
        return {"thpos_rt": tuple(thpos), "thss_rt": tuple(thss)}

    def nrows(self, phase: "MonsterPhase") -> int:
        """M7 P5: the rows of thpos_rt / thss_rt the probe reads -- the runtime things, then the mobiles"""
        return self.nrt + mobile_rows(phase.world)

    def aim_things(self, phase: "MonsterPhase") -> Dict[int, Tuple[int, int]]:
        """M7 P4.2a: `render_wall_frame(aim_things=...)` -- {drawable index: (sid, radius)} for every shootable living
        monster (`combat.CombatMixin.shootable_targets`' monster half): sid = 1 + slot, the radius its class (20, 30;
        the render widens it to r_eff for the view angle). Everything else is transparent to the window."""
        return {self.mdi[m]: (m + 1, r) for kind, m, _x, _y, r in phase.world.shootable_targets() if kind == "mon"}

    def slots_of(self, seen_drawables) -> set:
        """a render's `seen_out` (drawable indices) as monster slots"""
        return {m for m, di in enumerate(self.mdi) if di in seen_drawables}

    def __call__(self, phase: "MonsterPhase", x16: int, y16: int) -> list:
        out = [None] * self.n
        for m, v in phase.views(self.rm, self.patches, x16, y16).items():
            out[self.mdi[m]] = v
        return out
