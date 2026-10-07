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
    spawn fireballs ("full", and M7 P8a's modes after it: world.monster_attacks_land) or whose player's shots bleed
    (world.player_bleeds); 0 before P5"""
    from doomfj.world import FIREBALL_POOL, FX_POOL, monster_attacks_land, player_bleeds
    return FIREBALL_POOL + FX_POOL if (monster_attacks_land(world.monsters) or player_bleeds(world.player)) else 0


def drop_rows(world) -> int:
    """M7 P6 (docs/gp-p67-interface.md 4.5): the runtime-thing rows the DROPS add after the mobiles' -- one per DROPPER
    k (the monster slots `world.dropper` names, in slot order: E1M1's 12 zombiemen and 13 shotgun guys), row
    nt + mobile_rows + k -- in a world whose player loots (world.player_loots: "full"); 0 before P6"""
    from doomfj.world import player_loots
    return len(droppers(world)) if player_loots(world.player) else 0


def droppers(world) -> list:
    """M7 P6: the DROPPER slots -- the monster slots whose kill drops an item (combat's `dropper`), in slot order;
    dropper k is `droppers(world)[k]` (the fj's `mdrop[k]`, its row nt + 10 + k)"""
    return [m for m in range(world.layout.nmon) if world.dropper[m] is not None]


def loot_cells(world) -> Dict[str, object]:
    """M7 P6: the player's loot cells of a World, in their units (`MonsterPhase.loot_state` documents them) -- one
    definition for the gates' phase and for B0's frozen model (its per-run loot partings)"""
    from doomfj import gamedata as gd
    ws = world.ws
    md = tuple(ws.mon_drop[m] for m in droppers(world))
    return {"p_bc": ws.p_bonuscount, "p_str": ws.p_strength, "p_bp": ws.p_backpack,
            "am_misl": ws.p_ammo[gd.AM_MISL], "am_cell": ws.p_ammo[gd.AM_CELL],
            "mdrop": md, "dr_live": sum(1 for v in md if v == 1)}


def drop_lump(kind: int) -> str:
    """M7 P6: the one view a DROP of editor number `kind` is drawn with -- its thing's spawn frame at rotation 0
    (`mobile_lump`): MT_CLIP's CLIPA0, MT_SHOTGUN's SHOTA0"""
    from doomfj import gamedata as gd
    from doomfj.combat import DROP_ITEM
    name = next(n for n, k in DROP_ITEM.items() if k == kind)
    return mobile_lump(gd.MOBJINFO[name].spawnstate)


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


# M7 P8a (V, docs/gp-final-plan.md 4.3 step 6): a knock move CROSSES walk-over lines as the walk does -- DOOM's
# P_XYMovement -> P_TryMove -> P_CrossSpecialLine, for the player as for any thing. The gates' Mirror fires the door
# and mover walk-overs over the walk's segment AND, when this holds, over the knock's (`MonsterPhase.walk_end` ->
# the final pose); package K's fj must agree (a knock that fires no walk-over is this constant False, and a gate
# parts on any knock that crosses one)
KNOCK_WALKOVERS = True


def walkover_segments(phase, old, new) -> list:
    """M7 P8a (V): the segments a gate fires its door and mover walk-overs over this frame -- the walk's (old ->
    `phase.walk_end`) and, while KNOCK_WALKOVERS, the knock move's (walk_end -> new); the one segment old -> new when
    no knock move ran (every frame before P8a, and every frame of a mode without knockback)"""
    we = getattr(phase, "walk_end", None) if phase is not None else None
    if we is None:
        return [(tuple(old), tuple(new))]
    return [(tuple(old), tuple(we))] + ([(tuple(we), tuple(new))] if KNOCK_WALKOVERS else [])


def view_drop_kw(phase) -> dict:
    """M7 P8a (V): `render_wall_frame`'s keyword for a world frame of `phase` (a MonsterPhase, or None): the dying
    view's sink (`MonsterPhase.view_drop`) -- {} while it is 0, so every picture before package A lands (and every
    living frame after it) is drawn by today's call, keyword for keyword. EVERY game-tier gate's world render passes
    it, or `view_drop=` itself (tests/host/test_p8a_gates.py, static: rule 5)"""
    d = phase.view_drop() if phase is not None else 0
    return {"view_drop": d} if d else {}


class KnockTap:
    """M7 P8a (V): the KNOCK MOVES of one World, as they happen -- a recorder wrapped around package K's model entry
    points (docs/gp-final-plan.md 3.1: `combat._player_knock_move`, `world._monster_knock_move`, and the shared
    `_xy_move(thing, ev)` both may call), installed as INSTANCE attributes so the class (and every other World) is
    untouched. Each OUTERMOST call is one record: {"name", "frame", "mom0", "mom1", "pos0", "pos1"} -- the player's
    knock momentum (p_momx, p_momy) and every monster's (mon_momx, mon_momy) before and after, and the positions
    (the player's 16.16, each monster's whole units + fraction) -- so a reader asks what MOVED, not how K's
    functions are called. A model without them (any mode before P8a, or K not merged) installs nothing: `ok` False.

    It answers the gates' and the v7 planner's questions about a knock move, from the cells alone (section 4.1's
    units, DOOM's P_XYMovement): `walk_end` -- where the player stood when his knock move began this frame (B0
    injects the pose that lands the binary's WALK there); `refused` -- a thing whose momentum had a component of
    at least STOPSPEED going in and is zero coming out (friction keeps 29/32 of such a component and the STOPSPEED
    stop needs both below it, so only a REFUSED step zeroes it: DOOM's non-player rule, O-B4)."""

    NAMES = ("_player_knock_move", "_monster_knock_move", "_xy_move")

    def __init__(self, world):
        self.world = world
        self.records = []
        self.frame = 0
        self.depth = 0
        self.ok = False
        from doomfj.world import knockback_on
        if not knockback_on(world.player, world.monsters):
            return
        for name in self.NAMES:
            orig = getattr(world, name, None)
            if orig is None:
                continue
            setattr(world, name, self._wrap(name, orig))
        # K's model is in when its PLAYER entry exists (package 0 declares only the empty `_xy_move` hook)
        self.ok = hasattr(type(world), "_player_knock_move")

    def _snap(self):
        ws, n = self.world.ws, self.world.layout.nmon
        return ((ws.p_momx, ws.p_momy), tuple((ws.mon_momx[m], ws.mon_momy[m]) for m in range(n)),
                (ws.px, ws.py), tuple((ws.mon_x[m], ws.mon_y[m], ws.mon_fx[m], ws.mon_fy[m]) for m in range(n)))

    def _wrap(self, name, orig):
        def fn(*args, **kw):
            outer = self.depth == 0
            before = self._snap() if outer else None
            self.depth += 1
            try:
                return orig(*args, **kw)
            finally:
                self.depth -= 1
                if outer:
                    after = self._snap()
                    self.records.append({"name": name, "frame": self.frame, "args": args[:1],
                                         "mom0": before[0], "mom1": after[0], "mmom0": before[1], "mmom1": after[1],
                                         "pos0": before[2], "pos1": after[2], "mpos0": before[3], "mpos1": after[3]})
        fn.__wrapped__ = orig
        return fn

    def detach(self) -> None:
        for name in self.NAMES:
            if name in self.world.__dict__:
                delattr(self.world, name)

    def since(self, k: int) -> list:
        return self.records[k:]

    @staticmethod
    def _stopped(m0, m1) -> bool:
        from doomfj.gamedata import STOPSPEED
        return any(abs(v) >= STOPSPEED for v in m0) and tuple(m1) == (0, 0)

    def player_calls(self, recs=None) -> list:
        """the records whose PLAYER momentum or position changed, or that are the player's own entry"""
        return [r for r in (self.records if recs is None else recs)
                if r["name"] == "_player_knock_move" or r["mom0"] != r["mom1"] or r["pos0"] != r["pos1"]
                or (r["args"] and r["args"][0] == ("player", -1))]

    def wall_refusals(self, recs=None) -> list:
        """the `refusals` that no SOLID THING refused (O-V1's "a knock stopped by a wall"): nothing solid at the push's
        target -- the thing's position plus its momentum going in, clamped to +-MAXMOVE as P_XYMovement clamps it --
        so a wall, a step or a drop-off stopped it"""
        from doomfj.gamedata import MAXMOVE
        w, out = self.world, []

        def cl(v):
            return max(-MAXMOVE, min(MAXMOVE, v))
        for thing, r in self.refusals(recs):
            if thing[0] == "player":
                ok = w._solid_thing_at(r["pos0"][0] + cl(r["mom0"][0]), r["pos0"][1] + cl(r["mom0"][1])) is None
            else:
                m = thing[1]
                x, y = r["mpos0"][m][:2]
                mx, my = (cl(v) for v in r["mmom0"][m])
                ok = w._thing_blocker(m, x + (mx >> 16), y + (my >> 16), w.mon_radius[m]) is None
            if ok:
                out.append((thing, r))
        return out

    def refusals(self, recs=None) -> list:
        """[(thing, record)] of every knock REFUSED in `recs` (default all): ("player", -1) or ("mon", slot)"""
        out = []
        for r in (self.records if recs is None else recs):
            if self._stopped(r["mom0"], r["mom1"]):
                out.append((("player", -1), r))
            for m, (a, b) in enumerate(zip(r["mmom0"], r["mmom1"])):
                if self._stopped(a, b):
                    out.append((("mon", m), r))
        return out


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
        # M7 P8a (V): the knock moves as they happen (KnockTap; nothing installed before knockback_on), the walk's
        # landing this frame (`walk_end`: B0 and the walk-overs), and the player's last knock record
        self.tap = KnockTap(self.world)
        self.walk_end = None
        self.last_knock = None

    def reset(self, skill: int) -> None:
        self.world.reset(skill)

    # ---- M7 P8a (V, docs/gp-final-plan.md 4.1 / 5): the dying view and the knock ------------------------------------
    def view_drop(self) -> int:
        """`render_wall_frame(view_drop=)` for this world frame: P_DeathThink's sink in map units (`p_vdrop`, 0..35:
        viewheight = 41 - it) while the player SINKS (world.player_sinks), else 0 -- today's picture. EVERY game-tier
        gate's render passes it (`probe.view_drop_kw`; tests/host/test_p8a_gates.py holds the call sites)"""
        from doomfj.world import player_sinks
        return self.world.ws.p_vdrop if player_sinks(self.world.player) else 0

    def knocks(self) -> bool:
        """the world's knockback is on (world.knockback_on) -- the player's knock move runs in `move`"""
        from doomfj.world import knockback_on
        return knockback_on(self.world.player, self.world.monsters)

    def _knock_move(self, ev, n_before: int) -> None:
        """THE PLAYER'S KNOCK MOVE (docs/gp-final-plan.md 4.3 step 6: after the walk, dead or alive) -- the model's own
        (package K's `_player_knock_move(ev)`; before K, the declared hook `_xy_move(("player", -1), ev)`, empty) --
        unless the model already ran it inside this frame's weapon or move (`n_before`: the tap's records when the
        frame began; a K that knocks inside `_player_move` or `_death_think` is not knocked twice). The record of it
        is `last_knock`; `walk_end` is the pose it began from"""
        w = self.world

        def player_rec(r):
            return r["name"] == "_player_knock_move" or (r["name"] == "_xy_move" and r["args"]
                                                         and r["args"][0] == ("player", -1))
        mine = [r for r in self.tap.since(n_before) if player_rec(r)]
        if not mine:
            k = len(self.tap.records)
            fn = getattr(w, "_player_knock_move", None)
            if fn is not None:
                fn(ev)
            else:
                w._xy_move(("player", -1), ev)
            mine = [r for r in self.tap.since(k) if player_rec(r)]
        if mine:
            self.walk_end = (mine[0]["pos0"][0] & MASK32, mine[0]["pos0"][1] & MASK32)
            self.last_knock = mine[0]

    def tic(self, x16: Optional[int] = None, y16: Optional[int] = None, angle: Optional[int] = None):
        """one monster FRAME (M7 P6+P7 E: `world.monster_tics` tics, World._monster_world) -- the player where the
        gate's world put him this frame (the wake mode looks at him).
        M7 P5: and then the rest of world.tic's order after the monsters -- the fireballs, the barrels, the effects
        (`_projectiles_phase`, `_barrels_phase`, `_fx_phase`; before P5 nothing spawns into the pools and the barrels
        only animate). M7 P6: and `leveltime` +1, world.tic's last step (nukage reads it; the gate calls this only on
        a frame whose level is not done -- G2). -> the tic's events (also kept as `last_tic`)"""
        from doomfj.world import TicEvents
        w = self.world
        ws = w.ws
        if x16 is not None:
            ws.px = x16 - (1 << 32) if x16 >> 31 & 1 else x16
            ws.py = y16 - (1 << 32) if y16 >> 31 & 1 else y16
            ws.pangle = angle & 0xFFFFFFFF
        ev = TicEvents(0)
        w._monster_world(ev)              # M7 P6+P7 E: world.MONSTER_TICS_PER_FRAME tics, the model's own loop
        ws.leveltime = (ws.leveltime + 1) & 0xFFFF
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
    def _pose(self, x16: Optional[int], y16: Optional[int], angle: Optional[int]) -> None:
        """the gate's pose into the world's player cells (16.16 as the model keeps them: signed)"""
        if x16 is not None:
            ws = self.world.ws
            ws.px = x16 - (1 << 32) if x16 >> 31 & 1 else x16
            ws.py = y16 - (1 << 32) if y16 >> 31 & 1 else y16
            ws.pangle = angle & 0xFFFFFFFF

    def weapon(self, keys: dict, x16: Optional[int] = None, y16: Optional[int] = None,
               angle: Optional[int] = None, dead: Optional[int] = None):
        """ONE world frame of the player's weapon: the number keys, then P_MovePsprites -- the model's own
        (`combat._weapon_keys`, `_weapon_tics`: M7 P6+P7, world.WEAPON_TICS passes) in the world's player mode. A gate calls it on every world frame
        that tics (not a menu frame, not a finished level), with the frame's held keys. M7 P4.2a: and with the
        player's PRE-MOVE pose -- the binary's weapon runs before the player's move, so a melee reach and a shot's
        target are measured from where the player stood when the frame began. -> the tic's events.
        M7 P7 (docs/gp-p67-interface.md P7-a): `dead` -- THE TIC-START LATCH (`dead_latch()`, read before the frame's
        door tic): the branch is chosen ONCE, on `p_dead` as the tic found it, as `combat._player_phase` chooses it,
        so a player whom this tic's `nukage()` killed still runs the alive branch (the keys, the psprites, the
        fades). None reads `p_dead` now (the modes before P7, where nothing kills the player before the weapon).
        Dead in a mortal mode (world.player_mortal): the model's own `_death_think` -- the psprites, the damage
        fade, and a HELD use asks for the restart (`g_restart`). Alive: the keys, the psprites, then (combat's
        order) the berserk counter, the damage and the bonus fades."""
        from doomfj.world import KEYS, TicEvents, player_mortal
        w = self.world
        self._tap_at = len(self.tap.records)          # M7 P8a: the frame's knock records start here (`move`)
        if w.player == "walk":
            return TicEvents(0)
        self._pose(x16, y16, angle)
        k = {n: bool(keys.get(n)) for n in KEYS}
        ev = TicEvents(0)
        ws = w.ws
        if ws.p_dead if dead is None else dead:
            if player_mortal(w.player):   # M7 P7: P_DeathThink -- the restart request rides it
                w._death_think(k, ev)
                return ev
            w._weapon_tics(k, ev)         # M7 P5: P_DeathThink's weapon half; M7 P6+P7 F: world.WEAPON_TICS passes
            if ws.p_damagecount:
                ws.p_damagecount -= 1
            return ev
        w._weapon_keys(k)
        w._weapon_tics(k, ev)             # M7 P6+P7 F: world.WEAPON_TICS passes of P_MovePsprites
        # M7 P5: the flashes fade after the psprites, in the model's player-phase order (combat._player_phase);
        # M7 P6: the berserk counter grows before them (zero until a PSTR is taken: always zero before "full")
        if ws.p_strength:
            ws.p_strength = min(ws.p_strength + 1, 0xFFFF)
        if ws.p_damagecount:
            ws.p_damagecount -= 1
        if ws.p_bonuscount:
            ws.p_bonuscount -= 1
        return ev

    # ---- M7 P6 / P7: the player's half in the world (docs/gp-p67-interface.md 4.1) ------------------------------------
    def dead_latch(self) -> int:
        """M7 P7 (P7-a): `p_dead` as THIS world frame found it -- a gate reads it at the frame's start (after a due
        restart, before the door tic) and hands it to every guard of the frame: the door press and the closing
        door's contact, the use lines, `nukage`, `weapon`, `move` (the binary's `p_dd0`)"""
        return self.world.ws.p_dead

    def restart_due(self) -> bool:
        """M7 P7 (P7-d): a restart was asked (use while dead) -- the next WORLD frame starts with `restart()`"""
        return bool(self.world.ws.g_restart)

    def restart(self):
        """M7 P7 (P7-d): THE RESTART BLOCK -- the model's own `_restart`: every schema field but RESTART_KEEP (the
        skill, the menu mode, the held keys) back to the level start of the world's skill. The gate runs it at the
        START of a world frame whose `restart_due()`, then that frame's tic, and puts back its own phases (doors,
        movers, the pose, `pusedn`, `lvdone`) as NEW GAME does. -> the events (restarts 1)"""
        from doomfj.world import TicEvents
        ev = TicEvents(0)
        self.world._restart(ev)
        self.last_restart = ev
        return ev

    def nukage(self, x16: Optional[int] = None, y16: Optional[int] = None, angle: Optional[int] = None,
               dead: Optional[int] = None):
        """M7 P6 (P6-k): P_PlayerInSpecialSector -- the model's own `_special_sector` at the TIC-START pose, first
        in the alive branch (combat._player_phase), on the scene `sync` put the gate's doors and movers into. Only
        when the player loots (world.player_loots) and was alive when the tic began (`dead`, the latch). -> events"""
        from doomfj.world import TicEvents, player_loots
        w = self.world
        ev = TicEvents(0)
        if not player_loots(w.player) or (w.ws.p_dead if dead is None else dead):
            return ev
        self._pose(x16, y16, angle)
        w._special_sector(ev)
        return ev

    touch = None            # M7 P6: before "full", the gate's card touch for `move`'s step_sim (DoorPhase.touch)

    def move(self, keys: dict, x16: int, y16: int, angle: int, dead: Optional[int] = None, scene=None):
        """M7 P6: THE PLAYER'S MOVE -- the model's own `World._player_move` (the turn, the FixedMul step, the three
        candidates; at each the pickups -- map things, then drops -- then a solid thing's refusal, then the lines)
        on the world `sync` put the gate's doors and movers into (`scene_c`: the doors at their open height with
        the not-yet-passable doors' lines blocked, the movers at their heights). -> (x, y, angle) as
        `ReferenceModel.step_sim` returns them (the position's 32 bits when the keys move, else the pose given);
        its events (pickups, player_blocked) are `last_move`.
        THE WALK-OVERS stay the gate's: `doors.DoorPhase.after_move` / `movers.MoverPhase.after_move` fire them from
        (old, new) exactly as `World._walkover` does, so the world's own copy (`w_fired`, `d_monreq`, `l_req`) is
        put back here -- else a control that drops a gate's walk-over (p2a's `w1`, `no_wr`) could not part.
        A DEAD player (the tic-start latch, P7-a) does not move or turn BY KEYS: the position comes back unchanged and
        the angle is the world's -- in a mortal mode `weapon(dead=)`'s death think has just turned it to the killer
        (P_DeathThink; die_gate D1 on blocked51 found the pose given returned here, dropping the turn).
        Before "full" (world.player_loots false) the move is `step_sim`'s own (strafe on) with `self.touch(cx, cy,
        z)` -- the gate's card -- at every tried candidate, what those binaries run: on `scene` when given (the
        gate's own collision scene, as it stepped before P6), else on `scene_c`. In "full" `scene` must be None:
        the world's scene is the one the model's move reads."""
        from doomfj.reference_model import SimState
        from doomfj.world import KEYS, TicEvents, player_loots
        w, ws = self.world, self.world.ws
        ev = TicEvents(0)
        self.last_move = ev
        k = {n: bool(keys.get(n)) for n in KEYS}
        if not player_loots(w.player):
            st = w.rm.step_sim(SimState(x16, y16, angle, w.mapname), k, scene=w.scene_c if scene is None else scene,
                               touch=self.touch, strafe=True)
            return st.x, st.y, st.angle
        assert scene is None, "the full model moves on the world's own scene (sync it), not a gate's"
        # M7 P8a (V): this frame's walk landing and the player's knock record (`walk_end` None: no knock move ran)
        n0 = getattr(self, "_tap_at", len(self.tap.records))
        self._tap_at = len(self.tap.records)
        self.walk_end, self.last_knock = None, None
        knock = self.knocks()
        if ws.p_dead if dead is None else dead:
            from doomfj.world import player_mortal
            if knock:                     # M7 P8a: the corpse slides (4.3 step 6: dead or alive)
                ws.px = x16 - (1 << 32) if x16 >> 31 & 1 else x16
                ws.py = y16 - (1 << 32) if y16 >> 31 & 1 else y16
                keep = (list(ws.w_fired), list(ws.d_monreq), list(ws.l_req))
                self._knock_move(ev, n0)
                for arr, vals in zip((ws.w_fired, ws.d_monreq, ws.l_req), keep):
                    for i, v in enumerate(vals):
                        arr[i] = v
                if (ws.px & MASK32, ws.py & MASK32) != (x16 & MASK32, y16 & MASK32):
                    return ws.px & MASK32, ws.py & MASK32, ws.pangle
            return x16, y16, (ws.pangle if player_mortal(w.player) else angle)
        self._pose(x16, y16, angle)
        keep = (list(ws.w_fired), list(ws.d_monreq), list(ws.l_req))
        w._player_move(k, ev)
        if knock:                         # M7 P8a: the knock move after the walk (pickups at every tried position)
            self._knock_move(ev, n0)
        for arr, vals in zip((ws.w_fired, ws.d_monreq, ws.l_req), keep):
            for i, v in enumerate(vals):
                arr[i] = v
        if knock and (ws.px & MASK32, ws.py & MASK32) != (x16 & MASK32, y16 & MASK32):
            return ws.px & MASK32, ws.py & MASK32, ws.pangle   # the walk or the knock moved him
        if k["forward"] != k["back"] or k["strafe_left"] != k["strafe_right"]:
            return ws.px & MASK32, ws.py & MASK32, ws.pangle
        return x16, y16, ws.pangle

    def card(self) -> int:
        """M7 P6: the blue card as the world holds it (`p_cards[IT_BLUECARD]`) -- the gate's door phase's card
        (`pcard`) once the player loots: the World takes it, as the binary does, as one item of `move`'s pickups"""
        return self.world.ws.p_cards[self.gd.IT_BLUECARD]

    def set_card(self, value: int) -> None:
        """M7 P6: a scenario that POKES `pcard` pokes the world's card"""
        self.world.ws.p_cards[self.gd.IT_BLUECARD] = int(bool(value))

    def taken(self) -> Tuple[list, list]:
        """M7 P6: what the GAME removed, in the model's indices -- (pickup indices taken, barrel indices gone), each
        only among the things the world's skill spawned (a thing another skill spawns is `thing_hidden`'s -- the
        skill's absent set -- not a removal)"""
        w, ws, gd = self.world, self.world.ws, self.gd
        bit = gd.skill_bit(ws.skill)
        picks = [i for i, t in enumerate(w.pickup_things) if ws.pickup_taken[i] and t.flags & bit]
        bars = [b for b, t in enumerate(w.barrel_things) if not ws.bar_state[b] and t.flags & bit]
        return picks, bars

    def barrel_lumps(self) -> Dict[int, str]:
        """M7 P6: {barrel index: lump} of every barrel standing (bar_state != 0) -- its state's frame at rotation 0
        (`mobile_lump`: BAR1A0 / BAR1B0 / BEXPA0 .. BEXPE0)"""
        ws, gd = self.world.ws, self.gd
        return {b: mobile_lump(gd.STATE_NAMES[ws.bar_state[b]]) for b in range(self.world.layout.nbarrel)
                if ws.bar_state[b]}

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
        from doomfj.world import monster_attacks_land
        if monster_attacks_land(self.world.monsters):            # M7 P5: the attacks land -- hurtcode's player cells
            out.update(self.hurt_state())                        # and projcode's fireball pool
            out.update(self.proj_state())
        if monster_attacks_land(self.world.monsters) or player_bleeds(self.world.player):   # M7 P5: the blood pool
            out.update(self.fx_state())
        from doomfj.world import player_loots, player_mortal
        if player_loots(self.world.player):                       # M7 P6: the loot, the barrels, the game cells
            out.update(self.loot_state())
            out.update(self.barrel_state())
        if player_loots(self.world.player) or player_mortal(self.world.player):
            out.update(self.game_state())
        out.update(self.p8a_state())
        return out

    # ---- M7 P8a (V, docs/gp-final-plan.md 4.1): the final rung's cells, in the fj cells' units ----------------------
    def p8a_state(self) -> Dict[str, object]:
        """the cells P6's flag and P8a add, each only in the modes that emit it (the probe's OPTIONAL_GROUPS):
          p_tnh   1 nibble   P6+P7's "a turn key was held last frame" (the player's p_turnheld) -- the F1 gap of
                             #123: every game binary since P6 has it and no gate compared it (world.player_loots)
          p_vd    2 nibbles  P_DeathThink's sink, 0..35 (world.player_sinks)
          knock (world.knockback_on): p_kmx / p_kmy the player's KNOCK momentum, mkx / mky per slot, each 16.16 a
                  tic as its 32 bits unsigned (8 nibbles); mfx / mfy per slot the position's fraction (4 nibbles);
                  kb_live (2 nibbles) the slots whose momentum is not zero -- the monsters' fast skip, checked here;
                  pj_z per fireball slot, the shooter's floor + 32 at the spawn, its 16 bits (4 nibbles; a free
                  slot 0)
          fight (world.infighting_on): bar_src per barrel (2 nibbles: 0 none, 1 the player, 2 + slot the FIRST
                  thing that damaged it) -- `mon_target` (state(), 2 nibbles in this mode) names 0 / 1 / 2 + slot"""
        from doomfj.world import infighting_on, knockback_on, player_loots, player_sinks
        w, ws, n = self.world, self.world.ws, self.world.layout.nmon
        out = {}
        if player_loots(w.player):
            out["p_tnh"] = ws.p_turnheld
        if player_sinks(w.player):
            out["p_vd"] = ws.p_vdrop
        if knockback_on(w.player, w.monsters):
            out.update({"p_kmx": ws.p_momx & MASK32, "p_kmy": ws.p_momy & MASK32,
                        "mkx": tuple(v & MASK32 for v in ws.mon_momx[:n]),
                        "mky": tuple(v & MASK32 for v in ws.mon_momy[:n]),
                        "mfx": tuple(v & 0xFFFF for v in ws.mon_fx[:n]),
                        "mfy": tuple(v & 0xFFFF for v in ws.mon_fy[:n]),
                        "kb_live": sum(1 for m in range(n) if ws.mon_momx[m] or ws.mon_momy[m]),
                        "pj_z": tuple(v & 0xFFFF for v in ws.proj_z)})
        if infighting_on(w.monsters):
            out["bar_src"] = tuple(ws.bar_src)
        return out

    # ---- M7 P5: the monsters' attacks (docs/gp-p5-interface.md, "the cells' units") -----------------------------------
    def hurt_state(self) -> Dict[str, int]:
        """hurtcode's player cells in their own units: p_hp the health's 12 bits (3 nibbles, two's complement -- a
        killing blow takes it below 0), p_ar the armor points (2 nibbles, 0..200), p_at the armor type (0 none,
        1 green, 2 blue), p_dc the damage count (2 nibbles, 0..100), p_dead (PST_DEAD, 0/1); M7 P7: p_atk the
        attacker (2 nibbles: 0 none, 1 + the monster slot)"""
        ws = self.world.ws
        return {"p_hp": ws.p_health & 0xFFF, "p_ar": ws.p_armor, "p_at": ws.p_armortype, "p_dc": ws.p_damagecount,
                "p_dead": ws.p_dead, "p_atk": ws.p_attacker}

    def proj_state(self) -> Dict[str, tuple]:
        """projcode's fireball pool, per slot (FIREBALL_POOL of them): pj_act 0/1; pj_x / pj_y the 16.16 position and
        pj_mx / pj_my the 16.16 momentum, each its 32 bits unsigned (8 nibbles); pj_st the GAMEDATA state index (2
        nibbles: S_TBALL1 .. S_TBALLX3); pj_ti the tics left (1 nibble). A free slot is all zeros (the model's
        P_RemoveMobj zeroes it, and so does the level start)"""
        ws = self.world.ws
        return {"pj_act": tuple(ws.proj_active), "pj_x": tuple(v & MASK32 for v in ws.proj_x),
                "pj_y": tuple(v & MASK32 for v in ws.proj_y), "pj_mx": tuple(v & MASK32 for v in ws.proj_momx),
                "pj_my": tuple(v & MASK32 for v in ws.proj_momy), "pj_st": tuple(ws.proj_state),
                "pj_ti": tuple(ws.proj_tics),
                # M7 P7: the shooter, 1 + its slot while the slot is live (P_RemoveMobj zeroes proj_src too)
                "pj_src": tuple(ws.proj_src[s] + 1 if ws.proj_active[s] else 0 for s in range(len(ws.proj_src)))}

    def fx_state(self) -> Dict[str, object]:
        """projcode's blood pool, per slot (FX_POOL of them), in pj_*'s units (fx_x / fx_y always whole map units: the
        spawn point is one), and the effects' stream rng_fx (2 nibbles)"""
        ws = self.world.ws
        return {"fx_act": tuple(ws.fx_active), "fx_x": tuple(v & MASK32 for v in ws.fx_x),
                "fx_y": tuple(v & MASK32 for v in ws.fx_y), "fx_st": tuple(ws.fx_state),
                "fx_ti": tuple(ws.fx_tics), "rng_fx": ws.rng_fx}

    # ---- M7 P6 / P7: the new cells' ONE definition (docs/gp-p67-interface.md 4.5) ----------------------------------
    def loot_state(self) -> Dict[str, object]:
        """the player's loot in the fj cells' units (all unsigned, nibbles little-endian): p_bc the bonus count
        (2 nibbles, 0..255, +6 a take, saturating -- the card SETS 6, then +6), p_str the berserk counter (4
        nibbles, 0..0xFFFF, 1 at the take, +1 a live tic, saturating), p_bp the backpack (1 nibble, 0/1), am_misl /
        am_cell the rockets and the cells (3 nibbles each, 0 .. 2 x maxammo: no E1M1 weapon fires them, but a full
        count refuses the item), mdrop[k] per DROPPER k (`droppers`, slot order; 1 nibble: 0 none, 1 dropped,
        2 taken) and dr_live the count of mdrop == 1 (2 nibbles: the binary's fast skip, checked here)"""
        return loot_cells(self.world)

    def barrel_state(self) -> Dict[str, object]:
        """the barrels per index (22 on E1M1, WAD order), in the fj cells' units: bar_st the GAMEDATA state index
        (2 nibbles: S_BAR1 203, S_BAR2 204, S_BEXP .. S_BEXP5 205 .. 209; 0 removed or not at this skill), bar_ti
        its tics (1 nibble, 1..10; 0 removed), bar_hp the health's 8 bits (2 nibbles, two's complement: 20 at the
        start, saturating at -128 = 0x80), bar_solid (1 nibble, 0/1: P3.2b's presence cell), and rng_wd the world
        stream (2 nibbles) -- its value after the level start's 22 phase rolls, +1 a hit on a live barrel"""
        ws = self.world.ws
        return {"bar_st": tuple(ws.bar_state), "bar_ti": tuple(ws.bar_tics),
                "bar_hp": tuple(v & 0xFF for v in ws.bar_health), "bar_solid": tuple(ws.bar_solid),
                "rng_wd": ws.rng_world}

    def game_state(self) -> Dict[str, int]:
        """the game's cells: lvtime the level time (4 nibbles, 16 bits, wraps; +1 at the end of every tic that
        ran), g_rs the restart request (1 nibble, 0/1), g_skill the world's skill as the SKILLS index (1 nibble:
        0 easy, 1 medium, 2 hard -- wall_renderer.SKILLS, what the menu's `menu_sel` numbers)"""
        from doomfj.wall_renderer import SKILLS
        ws = self.world.ws
        return {"lvtime": ws.leveltime, "g_rs": ws.g_restart, "g_skill": SKILLS.index(ws.skill)}

    def palette(self) -> int:
        """the PLAYPAL index this world frame is shown with (combat.palette_index: ST_doPaletteStuff)"""
        from doomfj.combat import palette_index
        return palette_index(self.world.ws)

    def mobiles(self) -> list:
        """`render_wall_frame(mobiles=...)`: [(x, y, lump)] of every live mobile in ROW order -- the fireball slots,
        then the blood slots -- at its whole map units (the 16.16 position floored: its thpos_rt row carries no
        fraction), drawn with its state's frame (`mobile_lump`).
        M7 P6: then the DROPS lying (mdrop 1), in dropper order -- (x, y, lump, 0): at the corpse's position, ON its
        leaf's floor (z 0, not MISSILE_Z), CLIPA0 / SHOTA0 (`drop_lump`).
        M7 P8a (C, D3 a): each entry's KIND is what it carries -- a drop by its z 0, a fireball (BAL1*) or an effect
        (BLUD* / PUFF*) by its lump, which only that pool ever shows; `reference_model.mobile_rank` reads it (rank 0
        for the effects and the drops, drawn first in their leaf; 1 for the fireballs, as the monsters), the fj by the
        row ranges above (monstercode.rank_threshold). The tuples are unchanged, so every reader keeps its shape."""
        from doomfj.world import FIREBALL_POOL, FX_POOL
        ws, gd, out = self.world.ws, self.gd, []
        for s in range(FIREBALL_POOL):
            if ws.proj_active[s]:
                out.append((ws.proj_x[s] >> 16, ws.proj_y[s] >> 16, mobile_lump(gd.STATE_NAMES[ws.proj_state[s]])))
        for s in range(FX_POOL):
            if ws.fx_active[s]:
                out.append((ws.fx_x[s] >> 16, ws.fx_y[s] >> 16, mobile_lump(gd.STATE_NAMES[ws.fx_state[s]])))
        if drop_rows(self.world):
            for m in droppers(self.world):
                if ws.mon_drop[m] == 1:                 # M7 P8a: at the drop's own position (World.drop_pos)
                    out.append((*self.world.drop_pos(m), drop_lump(self.world.dropper[m]), 0))
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
        # M7 P6: the pickups' and the barrels' drawable indices (the same key), and the `thvis` slots: the baked
        # vanishable things' (things.vanishable_slots, the slot order wall_renderer bakes), then ONE slot per
        # RUNTIME pickup after them, in runtime-thing order (docs/gp-p67-interface.md 4.5: the probe reads
        # "taken" for all 95 pickups the same way)
        from doomfj.reference_model import VANISHABLE_TYPES
        from doomfj.things import vanishable_slots
        self.pdi = [key[(t.type, t.x, t.y, t.angle, t.flags)] for t in world.pickup_things]
        self.bdi = [key[(t.type, t.x, t.y, t.angle, t.flags)] for t in world.barrel_things]
        self.vis_slots = vanishable_slots(drawable, baked, VANISHABLE_TYPES)
        rt_set = set(self.rt_drawable)
        self.rt_pickups = sorted((di for di in self.pdi if di in rt_set), key=self.rt_drawable.index)
        self.nvis = len(self.vis_slots) + len(self.rt_pickups)
        assert all(di in self.vis_slots or di in rt_set for di in self.pdi + self.bdi), \
            "a pickup or a barrel is baked without a thvis slot: it could never vanish"

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
        out = {"thpos_rt": tuple(thpos), "thss_rt": tuple(thss)}
        if drop_rows(phase.world):
            # M7 P6: the DROP rows nt + 10 + k, one per dropper k: while its drop lies (mdrop 1) the corpse's
            # whole-unit row and its leaf (the monster's own), else (0, 0) -- and in no list
            for m in droppers(phase.world):
                live = ws.mon_drop[m] == 1
                dx, dy = phase.world.drop_pos(m)        # M7 P8a: the drop's own position (K: its leaf too)
                thpos.append((((dx << 16) & M) | (((dy << 16) & M) << 32)) if live else 0)
                thss.append(ws.mon_leaf[m] if live else 0)
            out = {"thpos_rt": tuple(thpos), "thss_rt": tuple(thss), **self.vis_state(phase)}
        return out

    def vis_state(self, phase: "MonsterPhase") -> dict:
        """M7 P6: the `thvis` cell (2 nibbles a slot: 1 drawn, 0 not -- taken, removed, or not at this skill): the
        baked vanishable slots in `things.vanishable_slots` order (a pickup: 1 - pickup_taken; a barrel: its state
        is not 0), then one slot per RUNTIME pickup in runtime-thing order (`rt_pickups`)"""
        ws = phase.world.ws
        pick = {di: i for i, di in enumerate(self.pdi)}
        bar = {di: b for b, di in enumerate(self.bdi)}

        def present(di):
            if di in pick:
                return 1 - ws.pickup_taken[pick[di]]
            return int(bool(ws.bar_state[bar[di]]))
        vals = [present(di) for di in sorted(self.vis_slots, key=self.vis_slots.get)]
        vals += [1 - ws.pickup_taken[pick[di]] for di in self.rt_pickups]
        return {"thvis": tuple(vals)}

    def nrows(self, phase: "MonsterPhase") -> int:
        """M7 P5: the rows of thpos_rt / thss_rt the probe reads -- the runtime things, then the mobiles.
        M7 P6: then the drop rows"""
        return self.nrt + mobile_rows(phase.world) + drop_rows(phase.world)

    def hidden(self, phase: "MonsterPhase") -> list:
        """M7 P6: `render_wall_frame(thing_removed=)` -- the drawable indices of what the game removed (the pickups
        taken, the barrels gone; `MonsterPhase.taken`)"""
        picks, bars = phase.taken()
        return sorted([self.pdi[i] for i in picks] + [self.bdi[b] for b in bars])

    def barrel_views(self, phase: "MonsterPhase") -> Dict[int, str]:
        """M7 P6: `render_wall_frame(barrel_views=)` -- {drawable index: lump} of every standing barrel, its state's
        frame (`MonsterPhase.barrel_lumps`)"""
        return {self.bdi[b]: lump for b, lump in phase.barrel_lumps().items()}

    def aim_things(self, phase: "MonsterPhase") -> Dict[int, Tuple[int, int]]:
        """M7 P4.2a: `render_wall_frame(aim_things=...)` -- {drawable index: (sid, radius)} for every shootable living
        monster (`combat.CombatMixin.shootable_targets`' monster half): sid = 1 + slot, the radius its class (20, 30;
        the render widens it to r_eff for the view angle). Everything else is transparent to the window.
        M7 P6: and every live barrel when the model aims at barrels ("full": shootable_targets' barrel half) --
        sid 1 + nmon + b, radius 10 (`combat.window_aim` reads it back as ("bar", b))."""
        nmon = phase.world.layout.nmon
        return {(self.mdi[i] if kind == "mon" else self.bdi[i]): ((i + 1) if kind == "mon" else (1 + nmon + i), r)
                for kind, i, _x, _y, r in phase.world.shootable_targets()}

    def slots_of(self, seen_drawables) -> set:
        """a render's `seen_out` (drawable indices) as monster slots"""
        return {m for m, di in enumerate(self.mdi) if di in seen_drawables}

    def __call__(self, phase: "MonsterPhase", x16: int, y16: int) -> list:
        out = [None] * self.n
        for m, v in phase.views(self.rm, self.patches, x16, y16).items():
            out[self.mdi[m]] = v
        return out
