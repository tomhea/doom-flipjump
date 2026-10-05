"""p2a_gate.py -- M7 P2a.1's gate: doors and keys, byte- and state-exact (docs/gp-doors-keys.md 4).

    python scratchpad/gp/p2a_gate.py --fjm build/<new>.fjm --labels <its label table>
    python scratchpad/gp/p2a_gate.py --oracle-only          # the scenarios and controls, no binary

Each scenario starts by POKING the game tier (the probe machinery b0_scenarios uses): at frame 0's
start the world mode, the player's pose and -- where the scenario says -- the blue card; at every
frame's start the held-key flags (kb_f, kb_b, kb_l, kb_r, kb_u). The binary then runs its own door
tic, player tic (the collision move, the card at every tried candidate, the walk-over triggers after
an accepted move) and render. At every present the probe reads the pose, all four cells of every
door, `dreq`, `pcard` and `wfired`, and the frame is held against THE ORACLE: doomfj.doors.DoorPhase
and ReferenceModel.step_sim (the card's touch per tried candidate) on the scene of the doors not yet
passable -- m2_std_gate's order -- rendered by probe.Oracle with the card hidden once it was taken
in the run. STATE-EXACT AND BYTE-EXACT ON EVERY FRAME.

THE SCENARIOS (the design's six, and the card taken on its platform):
  S1 blue door 71 without the card: use -> it stays shut
  S2 on the card's platform: walk onto it -> pcard 1, the card gone from the picture
  S3 blue door 71 with the card (pcard poked 1): use -> it opens
  S4 from sector 124, inside the card's box but 112 units below it: NOT taken (the reach test)
  S5 blazing door 84: use -> it opens in BLAZE_STRIDE-stop strides
  S6 over tag 5's trigger: door 77 opens and stays open past WAIT; back over it: nothing (W1)
  S7 over tag 6's trigger: door 145 the same
  S8 the exit (M7 P2a.2, docs/gp-exit.md): use held from the start is no press; released and
     pressed in the exit box -> the level ends (that frame still draws the world), LEVEL COMPLETE
     under held movement keys, enter -> the main menu, esc -> the FROZEN world, enter, enter, enter
     (the main menu, the skill screen) -> NEW GAME at the boot skill: the level start, moving again. Menu keys are real key events.

THE CONTROLS (R9): every scenario names the rule it tests, and the ORACLE WITHOUT THAT RULE must
part from the oracle on some frame -- else the scenario could not see the rule broken and the gate
FAILS as vacuous. Since the binary is held to the oracle frame by frame, a binary that broke the rule
parts from it where the control does. Controls: `card` (the key check dropped), `no_card` (the card
never taken / not held), `reach` (the reach test dropped), `stride` (stride 1), `stay` (a closing
door closes), `w1` (a trigger that fires every crossing), `edge` (a held use presses every tic),
`frozen` (a finished level's world still tics), `restart` (NEW GAME forgets `lvdone`).
"""
from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", ROOT / "scratchpad" / "12m", ROOT / "scratchpad", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

import probe as P                                                            # noqa: E402
import onewalk                                                               # noqa: E402
from doomfj import doors as D                                                # noqa: E402
from doomfj.doors import in_use_box_fixed                                    # noqa: E402
from doomfj.fixedpoint import _signed                                        # noqa: E402
from doomfj.reference_model import SimState                                  # noqa: E402
from doomfj.things import drawable_things                                    # noqa: E402
from doomfj.doors import exit_boxes                                          # noqa: E402
from doomfj.menu import LEVEL_DONE_SCR, menu_step, palette_colours           # noqa: E402
from doomfj.wall_renderer import (BOOT_SKILL, SKILLS, STANDALONE_POLLS,     # noqa: E402
                                  menu_screen_pixels)
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent             # noqa: E402

M32 = 0xFFFFFFFF
KEYFLAG = {"forward": "kb_f", "back": "kb_b", "turn_left": "kb_l", "turn_right": "kb_r",
           "use": "kb_u"}
READ = ("viewx", "viewy", "viewangle", "mode", "menu_scr", "dstate", "ddir", "dsub", "dwait", "dreq",
        "pcard", "wfired", "lvdone", "pusedn",
        "lstate", "ldir", "lsub", "lwait", "lreq", "fswitch",        # M7 P2b
        "mon_state", "mon_tics", "mon_facing", "mon_active",          # M7 P3.1
        "mon_target", "mon_reaction", "mon_threshold", "mon_movedir", "sched_cursor", "thseen",   # M7 P3.2a
        "mon_movecount", "mon_rng", "mon_floorz", "msec", "thpos_rt", "thss_rt",                   # M7 P3.2b
        "mon_justattacked")                                                                       # M7 P3.2c
MENU_CODES = {"enter": 0x0D, "esc": 0x1B, "up": 0x80, "dn": 0x81}     # M7 P6: up / down (F5's NEW GAME medium)
CARD_TYPE = 5
# M7 P6: the player mode a Mirror steps when its caller names none -- None is the game tier's
# (wall_renderer.PLAYER_MODE); `--player-mode` sets it for an --oracle-only run (the rung's target before the
# tier moves to it)
PLAYER_MODE_OVERRIDE = None


def bam(dx: float, dy: float) -> int:
    import math
    return int(round(math.atan2(dy, dx) / (2 * math.pi) * (1 << 32))) & M32


# ================================================================================================
# the oracle: DoorPhase + step_sim, with the controls
# ================================================================================================
class Mirror:
    """one scenario on the oracle. `ctl` drops ONE rule (the module docstring's controls)."""

    def __init__(self, dsim: "onewalk.DoorSim", card_di: int, ctl: str | None = None):
        self.sim, self.dp, self.ctl, self.card_di = dsim, dsim.dp, ctl, card_di
        if ctl == "no_reversal":                  # M7 P2b's control: doors that close on the player
            self.dp = D.DoorPhase(dsim.secs, dsim.lds, dsim.sds, dsim.mw.vertexes(dsim.mapname),
                                  dsim.boxes, card_at=dsim.dp.card_at, reversal=False)
        self.exits = exit_boxes(dsim.lds, dsim.mw.vertexes(dsim.mapname))     # M7 P2a.2
        self.mp = dsim.mp                                                        # M7 P2b
        self.viewfn = None            # M7 P3.1: (MonsterPhase, x16, y16) -> the render's thing_views
        self.seenfn = None            # M7 P3.2a: (MonsterPhase, pose, door phase, movers, taken) -> seen slots
        self.posfn = None             # M7 P3.2b: MonsterPhase -> the render's thing_positions
        self.rtfn = None              # M7 P3.2b: MonsterPhase -> the runtime things' thpos_rt / thss_rt
        self.removedfn = None         # M7 P6: MonsterPhase -> the drawables the game removed (render's `removed`)
        self.bviewfn = None           # M7 P6: MonsterPhase -> the standing barrels' frames (render's `barrel_views`)
        # M7 P5 (hurt_gate.py drives this Mirror): the model modes (None: wall_renderer's), a setup applied to the
        # boot level start's monster phase before frame 0 (what the gate pokes into the binary), and the phase
        self.mmode, self.pmode = None, PLAYER_MODE_OVERRIDE
        self.setup = None
        # M7 P6 / P7 (fight_gate.py, die_gate.py): LATE setups -- {frame: fn(phase, events) -> a pose or None}, run at
        # that frame's START (before its menu step); the cells and the pose they move are the frame's `poke` (what
        # the gate writes into the binary at that frame's start), their events ride the frame's `ev`
        self.late = {}
        self.mph = None

    def _cells(self, mph, st) -> dict:
        """M7 P6: the cells a late setup may move -- the world's (state, the runtime rows, the weapon) and the pose,
        in the probe's units"""
        return {**mph.state(), **(self.rtfn(mph) if self.rtfn else {}), **mph.weapon_state(),
                "viewx": _signed(st.x, 32), "viewy": _signed(st.y, 32), "viewangle": st.angle & M32}

    @contextlib.contextmanager
    def _rules(self):
        saved = (D.door_stride, D.door_stay)
        if self.ctl == "stride":
            D.door_stride = lambda kind: 1
        if self.ctl == "stay":
            D.door_stay = lambda kind: False
        # M7 P6: once the player loots, the card is the WORLD's (one item of the model's pickups), so its controls
        # break the model's give: `no_card` -- the card is never taken; `reach` -- the card's reach test always holds
        from doomfj import combat as C
        orig_touch = C.CombatMixin._touch
        if self.ctl in ("no_card", "reach"):
            ctl = self.ctl

            def touch(world, kind, dropped, item_z, z):
                if kind == CARD_TYPE:
                    if ctl == "no_card":
                        return False
                    z = item_z
                return orig_touch(world, kind, dropped, item_z, z)
            C.CombatMixin._touch = touch
        try:
            yield
        finally:
            D.door_stride, D.door_stay = saved
            C.CombatMixin._touch = orig_touch

    def run(self, pose, keys: list, pcard: int = 0) -> list:
        """-> per frame {"pose", "phase", "taken", "mode", "scr", "sel", "lvdone", "pusedn",
        "drawn"}: the state after the frame, and what it drew ("world", or the menu screen). The
        binary's order: the menu's state machine on the frame's events, then -- on a world frame,
        unless the level is done -- the door tic, the exit press, the player's move.
        M7 P6 / P7 (docs/gp-p67-interface.md 4.1, 4.7) -- once the player LOOTS (world.player_loots: "full"):
        the move is the model's own (`MonsterPhase.move`: pickups, blocking by things, the card as one item), on
        the world `sync` put this frame's doors and movers into, after `nukage` and `weapon`; the card is the
        world's (`pcard` pokes it); a frame records what the game removed (`removed`) and the barrels' frames
        (`bviews`). Once the player is MORTAL (world.player_mortal): a WORLD frame first runs a due restart (the
        model's `_restart`, with this gate's doors, movers, pose, `pusedn` and `lvdone` put back as NEW GAME puts
        them), then reads THE TIC-START DEAD LATCH -- a player dead when the frame began presses no door, holds no
        closing door, presses no use line (and leaves `pusedn` alone: the death think does not read use's edge),
        does not move or turn, and thinks the death think in `weapon` (a held use asks for the restart)."""
        from doomfj.reference_model import SimState as _SS
        from doomfj.world import player_loots, player_mortal
        sim, dp = self.sim, self.dp
        st = SimState(pose[0], pose[1], pose[2], sim.mapname)
        ph = dp.initial()
        ph = (ph[0], ph[1], ph[2], pcard)
        taken, out = False, []
        mode, scr, sel = 0, 0, SKILLS.index(BOOT_SKILL)      # poked into the world; sel baked
        pusedn, lvdone = 1, 0                                  # baked: G_PlayerReborn's usedown
        mp, ms = self.mp, self.mp.initial()                    # M7 P2b: every lift at its top
        # M7 P3.1: the idle monsters from the boot image's level start (doomfj.monsters)
        from doomfj.monsters import MonsterPhase
        from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
        mph = MonsterPhase(sim.mw, sim.mapname, BOOT_SKILL, rm=sim.rm, mode=self.mmode or MONSTER_MODE,
                           player=self.pmode or PLAYER_MODE)
        loots, mortal = player_loots(mph.world.player), player_mortal(mph.world.player)
        if loots:
            mph.set_card(pcard)                               # M7 P6: `pcard` is the world's card
        if self.setup is not None:                            # M7 P5: the scenario's poked start
            self.setup(mph)
        self.mph = mph
        card_i = next((i for i, t in enumerate(mph.world.pickup_things) if t.type == CARD_TYPE), None)
        with self._rules():
            for f, kd in enumerate(keys):
                wev, mph.last_tic = None, None                # M7 P5: this frame's weapon and tic events
                nev = mev = rsev = lev = None                 # M7 P6 / P7: nukage, the move, the restart, late
                poke = {}
                if f in self.late:                            # M7 P6 / P7: a late setup at this frame's start
                    from doomfj.world import TicEvents
                    lev = TicEvents(f)
                    before = self._cells(mph, st)
                    got = self.late[f](mph, lev)
                    if got is not None:
                        st = SimState(got[0], got[1], got[2], sim.mapname)
                    after = self._cells(mph, st)
                    poke = {k: v for k, v in after.items() if before.get(k) != v}
                mode, scr, sel, ng = menu_step(mode, scr, sel, set(kd.get("menu", ())))
                if ng is not None:                            # NEW GAME: the level start
                    st = SimState(sim.spawn.x, sim.spawn.y, sim.spawn.angle, sim.mapname)
                    ph, taken, pusedn = dp.initial(), False, 1
                    if self.ctl != "restart_movers":
                        ms = mp.initial()
                    if self.ctl != "restart":
                        lvdone = 0
                    mph.reset(SKILLS[ng])                     # M7 P3.1: the skill's monsters
                drawn = ("menu", scr, sel) if mode else "world"
                if mode == 0 and mortal and mph.restart_due():
                    # M7 P7 (P7-d): the restart block at the world frame's start, then this frame's tic
                    rsev = mph.restart()
                    st = SimState(sim.spawn.x, sim.spawn.y, sim.spawn.angle, sim.mapname)
                    ph, taken, pusedn, ms, lvdone = dp.initial(), False, 1, mp.initial(), 0
                if mode == 0 and not (lvdone and self.ctl != "frozen"):
                    # M7 P7 (P7-a): the tic-start latch; before P7 nothing kills the player, so 0
                    dead = mph.dead_latch() if mortal else 0
                    use = bool(kd.get("use"))
                    has_blue = {"card": True, "no_card": False}.get(self.ctl)
                    alive = not dead or self.ctl == "dead_holds_door"
                    ph = dp.tic(ph, use and (not dead or self.ctl == "dead_uses"), st.x, st.y, has_blue=has_blue,
                                others=mph.boxes(), player=alive)    # P3.2b; P7-c
                    ms = mp.tic(ms)                           # M7 P2b: the lifts after the doors
                    if dead:                                  # P7-c: no use line, and the edge is not read
                        if self.ctl == "dead_exits" and use and any(in_use_box_fixed(b, st.x, st.y)
                                                                    for b in self.exits):
                            lvdone, mode, scr = 1, 1, LEVEL_DONE_SCR     # die_gate's control: a dead player exits
                    elif use:                                 # the exit: a PRESS in its box
                        if not pusedn or self.ctl == "edge":
                            pusedn = 1
                            if any(in_use_box_fixed(b, st.x, st.y) for b in self.exits):
                                lvdone, mode, scr = 1, 1, LEVEL_DONE_SCR
                            elif self.ctl != "no_use_lines":  # else the SR lifts and the switch
                                ms = mp.use_press(ms, st.x, st.y)
                    else:
                        pusedn = 0
                    blocked = frozenset(li for si in sim.order if ph[0][si][0] < sim.passes[si]
                                        for li in sim.lines_of.get(si, ()))
                    cur = [ph]

                    def touch(cx, cy, z):
                        if self.ctl == "no_card":
                            return
                        if self.ctl == "reach" and dp.card_at is not None:
                            z = dp.card_at[2]
                        cur[0] = dp.touch(cur[0], cx, cy, z)
                    if loots:
                        # M7 P6: the world's scene is this frame's doors and movers (after the use press: the switch)
                        mph.sync(ph[0], ms[0], ms[2])
                        nev = mph.nukage(st.x, st.y, st.angle, dead=dead)
                        if self.ctl == "latch":               # die_gate's control: the branch re-read after nukage
                            dead = mph.dead_latch()
                    wev = mph.weapon(kd, st.x, st.y, st.angle,   # M7 P4.1: the weapon, after the use press (pre-move)
                                     dead=dead if mortal else None)
                    if loots:
                        nx, ny, na = mph.move(kd, st.x, st.y, st.angle, dead=dead)
                        mev = mph.last_move
                        new = _SS(nx, ny, na, sim.mapname)
                        ph = (ph[0], ph[1], ph[2], mph.card())
                        taken = card_i is not None and bool(mph.world.ws.pickup_taken[card_i])
                    else:
                        mph.touch = touch
                        nx, ny, na = mph.move(kd, st.x, st.y, st.angle, scene=sim._scene(blocked, mp.heights(ms)))
                        new = _SS(nx, ny, na, sim.mapname)
                        ph = cur[0]
                        taken |= ph[3] == 1 and pcard == 0
                    if self.ctl == "w1":       # every crossing presses; the bits still read fired
                        was = ph[1]
                        ph = dp.after_move((ph[0], (0,) * len(was), ph[2], ph[3]), (st.x, st.y),
                                           (new.x, new.y))
                        ph = (ph[0], tuple(a | b for a, b in zip(was, ph[1])), ph[2], ph[3])
                    else:
                        ph = dp.after_move(ph, (st.x, st.y), (new.x, new.y))
                    if self.ctl != "no_wr":
                        ms = mp.after_move(ms, (st.x, st.y), (new.x, new.y))
                    st = new
                    # M7 P3.1: the monsters after the player -- P3.2a: unless THIS frame's press ended the level
                    # (the binary's tic runs after the player and skips on lvdone); P3.2b: inside the doors and lifts
                    if not lvdone:
                        ph, ms = mph.frame(ph, ms, st.x, st.y, st.angle)
                # M7 P3.2a: every frame that draws the WORLD marks the seen flags (the exit's own frame and the
                # frozen world's too: the tic is skipped, its zero and the render are not); a menu frame skips the
                # whole world pass and leaves them as they were
                removed = self.removedfn(mph) if (loots and self.removedfn) else None
                bviews = self.bviewfn(mph) if (loots and self.bviewfn) else None
                if self.seenfn is not None and drawn == "world":
                    mph.set_seen(self.seenfn(mph, st, ph, ms, taken))
                out.append({"pose": (st.x, st.y, st.angle), "phase": ph, "taken": taken,
                            "mode": mode, "scr": scr, "sel": sel, "lvdone": lvdone,
                            "pusedn": pusedn, "drawn": drawn, "movers": ms,
                            "mheights": mp.heights(ms),
                            "mstate": {**mph.state(), **(self.rtfn(mph) if self.rtfn else {}),
                                       **mph.weapon_state()},
                            "skw": mph.screen_kw(),                                   # M7 P4.1
                            # M7 P5: the fireballs and the blood, and the palette the present shows (a menu: 0)
                            "mobiles": mph.mobiles(), "pal": mph.palette() if drawn == "world" else 0,
                            "ev": (lev, rsev, nev, wev, mev, mph.last_tic),     # M7 P6 / P7: + late, restart, nukage, move
                            "poke": poke,                                       # M7 P6 / P7: the late setup's cells
                            "removed": removed, "bviews": bviews,               # M7 P6
                            "views": self.viewfn(mph, st.x, st.y) if self.viewfn else None,
                            "positions": self.posfn(mph) if self.posfn else None})
        return out


def seen_of(orc, dsim, card_di):
    """M7 P3.2a: (MonsterPhase, pose, door phase, movers, taken) -> the monster slots the frame's picture SEES --
    the same render the gate compares against, with `seen_out`. M7 P6: once the player loots, what the game
    removed and the barrels' frames (a barrel's lump sets its aim box's size bound)"""
    from doomfj.world import player_loots

    def fn(mph, st, ph, ms, taken):
        seen, aim = set(), [0] * 17
        loot = player_loots(mph.world.player)
        orc.render(st.x, st.y, st.angle, tuple(ph[0][si][0] for si in dsim.order),
                   hidden_extra=(card_di,) if (taken and not loot) else (), movers=dsim.mp.heights(ms),
                   views=orc.monster_views(mph, st.x, st.y), seen_out=seen,
                   positions=orc.monster_positions(mph), aim_things=orc._mviews.aim_things(mph), aim_out=aim,
                   mobiles=mph.mobiles(),                                     # M7 P5
                   removed=orc.monster_removed(mph) if loot else None,       # M7 P6
                   barrel_views=orc.monster_barrel_views(mph) if loot else None)
        mph.set_aim(aim)                    # M7 P4.2a: this picture's window -> the next frame's shots
        return orc._mviews.slots_of(seen)
    return fn


def hooked(mirror: "Mirror", orc, dsim, card_di) -> "Mirror":
    """the oracle's hooks on a Mirror -- the monsters' views (P3.1), the picture's seen (P3.2a), positions and the
    runtime rows (P3.2b). A CONTROL's Mirror takes them too (M7 P5 found it did not: from P3.2b on its cells lacked
    thpos_rt / thss_rt, so EVERY control parted at frame 0 on the missing keys alone and none was tested)"""
    mirror.viewfn = orc.monster_views
    mirror.seenfn = seen_of(orc, dsim, card_di)
    mirror.posfn, mirror.rtfn = orc.monster_positions, orc.monster_rt
    mirror.removedfn, mirror.bviewfn = orc.monster_removed, orc.monster_barrel_views    # M7 P6
    return mirror


def picture(orc, dsim, fr: dict, card_di) -> bytes:
    """a world frame's picture as the oracle draws it: the doors, movers, monsters, mobiles -- the card hidden once
    taken (before P6), or (M7 P6, `fr["removed"]` not None) everything the game removed and the barrels by state;
    the bar's card is `pcard`'s (S3 pokes it)"""
    loot = fr.get("removed") is not None
    cd = [card_di] if isinstance(card_di, int) else list(card_di)
    return orc.render(fr["pose"][0], fr["pose"][1], fr["pose"][2], tuple(fr["phase"][0][si][0] for si in dsim.order),
                      hidden_extra=cd if (fr["taken"] and not loot) else (), movers=fr["mheights"],
                      views=fr["views"], positions=fr["positions"], screen_kw=fr.get("skw"),
                      mobiles=fr["mobiles"],                                        # M7 P5
                      removed=fr.get("removed"), barrel_views=fr.get("bviews"),     # M7 P6
                      card=fr["phase"][3])


def expected_cells(fr: dict, order: list, mover_order=()) -> dict:
    ds, fired, req, card = fr["phase"]
    lifts, lreq, sw = fr["movers"]
    x, y, a = fr["pose"]
    doors = [ds[si] for si in order]
    return {"viewx": _signed(x, 32), "viewy": _signed(y, 32), "viewangle": a & M32,
            "mode": fr["mode"], "menu_scr": fr["scr"],
            "dstate": tuple(d[0] for d in doors), "ddir": tuple(d[1] for d in doors),
            "dsub": tuple(d[2] for d in doors), "dwait": tuple(d[3] for d in doors),
            "dreq": tuple(int(si in req) for si in order), "pcard": card,
            "wfired": P.wfired_value(fired), "lvdone": fr["lvdone"], "pusedn": fr["pusedn"],
            # M7 P2b
            "lstate": tuple(t[0] for t in lifts), "ldir": tuple(t[1] for t in lifts),
            "lsub": tuple(t[2] for t in lifts), "lwait": tuple(t[3] for t in lifts),
            "lreq": tuple(int(si in lreq) for si in mover_order), "fswitch": sw,
            **fr.get("mstate", {})}                                  # M7 P3.1


def screen(orc, scr: int, sel: int) -> bytes:
    """a menu screen's picture: the main menu, the skill screen at `sel`, LEVEL COMPLETE -- or (M7
    P3.4) the main menu on HELP and the help: `wall_renderer.menu_screen_pixels`, the one mapping"""
    colours = palette_colours(bytes(b for rgb in orc.mw.playpal(0) for b in rgb))
    return bytes(menu_screen_pixels(orc.rm.cfg, colours, scr, sel))


def menu_events(keys: list) -> list:
    """each frame's "menu" keys as the device's events: down on the frame's first poll, up next"""
    out = []
    for f, kd in enumerate(keys):
        for k, name in enumerate(kd.get("menu", ())):
            out += [KeyEvent(f * STANDALONE_POLLS + 2 * k, True, MENU_CODES[name]),
                    KeyEvent(f * STANDALONE_POLLS + 2 * k + 1, False, MENU_CODES[name])]
    return out


# ================================================================================================
# the scenarios, placed from the map
# ================================================================================================
def _ok(dsim, x16, y16) -> bool:
    return dsim.rm.check_position(dsim._scene(frozenset(li for si in dsim.order
                                                         for li in dsim.lines_of.get(si, ()))),
                                  x16, y16)[0]


def _sector(dsim, x, y) -> int:
    """the sector INDEX (x, y) lies in: its subsector's first seg -> linedef -> sidedef"""
    rm = dsim.rm
    cmap = dsim._scene(frozenset()).cmap
    seg = cmap.segs[cmap.subsectors[rm.point_in_subsector(cmap, x, y)].firstseg]
    ld = dsim.lds[seg.linedef]
    return dsim.sds[ld.front if seg.side == 0 else ld.back].sector


def door_front(dsim, si: int):
    """a standing pose inside door `si`'s use box, facing its nearest line, off the door sector"""
    box = dsim.boxes[si]
    verts = dsim.mw.vertexes(dsim.mapname)
    best = None
    for li in sorted(dsim.lines_of[si]):
        ld = dsim.lds[li]
        v1, v2 = verts[ld.v1], verts[ld.v2]
        mx, my = (v1.x + v2.x) / 2, (v1.y + v2.y) / 2
        nx, ny = -(v2.y - v1.y), (v2.x - v1.x)
        n = (nx * nx + ny * ny) ** 0.5
        for side in (1, -1):
            for d in (40, 48, 56, 64):
                x, y = round(mx + side * nx / n * d), round(my + side * ny / n * d)
                if _sector(dsim, x, y) != si and in_use_box_fixed(box, x << 16, y << 16) \
                        and _ok(dsim, x << 16, y << 16):
                    cand = (d, x, y, bam(mx - x, my - y))
                    best = min(best, cand) if best else cand
    assert best, "no standing pose in door %d's box" % si
    return (best[1] << 16, best[2] << 16, best[3])


def card_pose(dsim, card):
    """on the card's platform (its sector), 48 units off, facing it"""
    kx, ky, _kz = card
    ksec = _sector(dsim, kx, ky)
    for dx, dy in ((-48, 0), (48, 0), (0, -48), (0, 48), (-34, -34), (34, 34), (-34, 34), (34, -34)):
        x, y = kx + dx, ky + dy
        if _sector(dsim, x, y) == ksec and _ok(dsim, x << 16, y << 16):
            return (x << 16, y << 16, bam(-dx, -dy))
    raise AssertionError("no pose on the card's platform")


def below_card_pose(dsim, card, sector: int = 124, frames: int = 3):
    """standing in `sector` (floor 24: 112 units below the card), facing the card, near enough that a
    TRIED step lands inside the card's box -- proven by the reach control taking it; nearest first"""
    kx, ky, _kz = card
    pts = sorted(((dx * dx + dy * dy, kx + dx, ky + dy) for dx in range(-80, 81, 4)
                  for dy in range(-80, 81, 4)))
    for _d2, x, y in pts:
        if _sector(dsim, x, y) != sector or not _ok(dsim, x << 16, y << 16):
            continue
        pose = (x << 16, y << 16, bam(kx - x, ky - y))
        tr = Mirror(dsim, -1, "reach").run(pose, [{"forward": True}] * frames)
        if tr[-1]["phase"][3] == 1:
            return pose
    raise AssertionError("no pose in sector %d whose step reaches the card's box" % sector)


def exit_pose(dsim):
    """a standing pose inside the exit box, off the exit line, facing it"""
    (x0, y0, x1, y1), = exit_boxes(dsim.lds, dsim.mw.vertexes(dsim.mapname))
    verts = dsim.mw.vertexes(dsim.mapname)
    ld = [ld for ld in dsim.lds if ld.special in D.EXIT_SPECIALS][0]
    v1, v2 = verts[ld.v1], verts[ld.v2]
    mx, my = (v1.x + v2.x) / 2, (v1.y + v2.y) / 2
    nx, ny = -(v2.y - v1.y), (v2.x - v1.x)
    n = (nx * nx + ny * ny) ** 0.5
    for d in (32, 40, 48, 24, 56):
        for side in (1, -1):
            x, y = round(mx + side * nx / n * d), round(my + side * ny / n * d)
            if x0 <= x <= x1 and y0 <= y <= y1 and _ok(dsim, x << 16, y << 16):
                return (x << 16, y << 16, bam(mx - x, my - y))
    raise AssertionError("no standing pose in the exit box")


def _standing(dsim, xy, angle):
    x, y = xy
    assert _ok(dsim, x << 16, y << 16), ("not a standing pose", xy)
    return (x << 16, y << 16, angle)


def _in_box(dsim, box):
    """a standing pose inside a use box, nearest its centre"""
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    for r in range(0, 64, 4):
        for dx, dy in ((r, 0), (-r, 0), (0, r), (0, -r), (r, r), (-r, -r), (r, -r), (-r, r)):
            x, y = cx + dx, cy + dy
            if x0 <= x <= x1 and y0 <= y <= y1 and _ok(dsim, x << 16, y << 16):
                return (x << 16, y << 16, 0)
    raise AssertionError("no standing pose in the box %s" % (box,))


def trigger_pose(dsim, trig, back: int = 40):
    """`back` units before the trigger line's middle, facing across it"""
    _si, axis, coord, lo, hi = trig
    mid = (lo + hi) // 2
    for side in (-1, 1):
        a = coord + side * back
        x, y = (mid, a) if axis == "y" else (a, mid)
        if _ok(dsim, x << 16, y << 16):
            ang = bam(0, -side) if axis == "y" else bam(-side, 0)
            return (x << 16, y << 16, ang)
    raise AssertionError("no pose before trigger %s" % (trig,))


def _strides(tr, si: int, nstates: int) -> bool:
    """door `si` opened AND closed again, every move a full stride (BLAZE_STRIDE stops, clamped
    at the ends)"""
    st = [0] + [fr["phase"][0][si][0] for fr in tr]
    moves = [b - a for a, b in zip(st, st[1:]) if b != a]
    full = all(abs(m) == min(D.BLAZE_STRIDE, nstates - 1) for m in moves)
    return max(st) == nstates - 1 and st[-1] == 0 and full and len(moves) >= 2


def scenarios(dsim, card) -> list:
    kinds = dsim.dp.kinds
    blue = 71
    assert kinds[blue] == "blue", kinds[blue]
    blaze = [si for si, k in kinds.items() if k == "blaze"]
    assert blaze == [84], blaze
    trig = {t[0]: t for t in dsim.dp.triggers}
    assert sorted(trig) == [77, 145], trig
    n = dsim.nstates
    F, B, U, I = {"forward": True}, {"back": True}, {"use": True}, {}
    out = [
        {"name": "S1 blue door 71, no card: stays shut", "pose": door_front(dsim, blue),
         "keys": [U] * 3 + [I] * 12, "pcard": 0, "controls": ["card"],
         "claim": lambda tr: all(fr["phase"][0][blue][0] == 0 for fr in tr)},
        {"name": "S2 onto the card: taken, gone from the picture", "pose": card_pose(dsim, card),
         "keys": [F] * 4 + [I] * 2, "pcard": 0, "controls": ["no_card"],
         "claim": lambda tr: tr[-1]["phase"][3] == 1 and tr[-1]["taken"]},
        {"name": "S3 blue door 71 with the card: opens", "pose": door_front(dsim, blue),
         "keys": [U] * 3 + [I] * (D.SPEED * n[blue] + 2), "pcard": 1, "controls": ["no_card"],
         "claim": lambda tr: tr[-1]["phase"][0][blue][0] == n[blue] - 1},
        {"name": "S4 from sector 124 in the card's box: out of reach", "pose": below_card_pose(dsim, card),
         "keys": [F] * 3, "pcard": 0, "controls": ["reach"],
         "claim": lambda tr: all(fr["phase"][3] == 0 for fr in tr)},
        {"name": "S5 blazing door 84: opens and closes in strides", "pose": door_front(dsim, 84),
         "keys": [U] * 2 + [I] * (D.WAIT + 10), "pcard": 0, "controls": ["stride"],
         "claim": lambda tr: _strides(tr, 84, n[84])},
    ]
    for si, tag in ((77, 5), (145, 6)):
        t = trig[si]
        stay = D.SPEED * (n[si] - 1) + D.WAIT + 8
        out.append({"name": "S%d over tag %d's trigger: door %d opens, stays; back over: nothing"
                            % (6 if si == 77 else 7, tag, si),
                    # M7 P6: back over AT ONCE, then the wait -- once the player is blocked by things, a zombie
                    # woken by the wait (S6's, 40 units south of the pose) stands on the way back
                    "pose": trigger_pose(dsim, t), "keys": [F] * 5 + [B] * 5 + [I] * stay + [I] * 3,
                    "pcard": 0, "controls": ["stay", "w1"],
                    "claim": lambda tr, si=si: tr[-1]["phase"][0][si][0] == n[si] - 1
                    and sum(1 for fr in tr if si in fr["phase"][2]) == 1})
    F_ = {"forward": True}
    # ---- M7 P2b: the movers --------------------------------------------------------------------------
    k98, k103 = dsim.mp.order.index(98), dsim.mp.order.index(103)

    def ride(tr, k):
        st = [fr["movers"][0][k][0] for fr in tr]
        return max(st) == 9 and st[-1] == 0 and st.index(9) < len(st) - 1

    out.append({
        "name": "S9 over lift 98's WR line: it rides down, waits, comes back up",
        "pose": _standing(dsim, (40, 256), 0), "keys": [F_] * 3 + [I] * 50, "pcard": 0,
        "controls": ["no_wr"], "claim": lambda tr: ride(tr, k98)})
    sr = [b for t, b in dsim.mp.use if t == 2]
    out.append({
        "name": "S10 an SR press at lift 103: it rides",
        "pose": _in_box(dsim, sr[0]), "keys": [I, U] + [I] * 50, "pcard": 0,
        "controls": ["no_use_lines"], "claim": lambda tr: ride(tr, k103)})
    out.append({
        "name": "S11 the floor switch: a press lowers the pillars at once",
        "pose": _in_box(dsim, dsim.mp.switch_boxes[0]), "keys": [I, U, I, I], "pcard": 0,
        "controls": ["no_use_lines"],
        "claim": lambda tr: [fr["movers"][2] for fr in tr] == [0, 1, 1, 1]
        and tr[1]["mheights"][129][0] == 136})
    out.append({
        "name": "S12 NEW GAME puts a riding lift back",
        "pose": _standing(dsim, (40, 256), 0),
        "keys": [F_] * 3 + [I] * 4 + [{"menu": ["esc"]}, {"menu": ["enter"]}, {"menu": ["enter"]}]
        + [I] * 3, "pcard": 0, "controls": ["restart_movers"],
        "claim": lambda tr: tr[6]["movers"][0][k98][0] > 0 and tr[-1]["movers"][0][k98][0] == 0})
    p10 = dsim.passes[10]
    out.append({
        "name": "S13 standing in door 10 as it closes: it goes back up at its pass state",
        "pose": door_front(dsim, 10), "keys": [U] * 2 + [I] * 8 + [F] * 3 + [I] * 70, "pcard": 0,
        "controls": ["no_reversal"],
        "claim": lambda tr: min(fr["phase"][0][10][0] for fr in tr[12:]) == p10
        and any(a["phase"][0][10][1] == D.CLOSING and b["phase"][0][10][1] == D.OPENING
                for a, b in zip(tr, tr[1:]))})
    out.append({
        "name": "S8 the exit: a press ends the level; LEVEL COMPLETE; the frozen world; NEW GAME",
        "pose": exit_pose(dsim),
        "keys": [U, I, U, F_, F_, dict(F_, menu=["enter"]), dict(F_, menu=["esc"]), F_,
                 dict(F_, menu=["enter"]), {"menu": ["enter"]}, dict(F_, menu=["enter"]), F_, I],
        "pcard": 0, "controls": ["edge", "frozen", "restart"],
        "claim": lambda tr: (tr[1]["lvdone"], tr[2]["lvdone"]) == (0, 1)
        and tr[2]["drawn"] == "world" and tr[3]["drawn"] == ("menu", LEVEL_DONE_SCR, tr[3]["sel"])
        and tr[5]["drawn"][:2] == ("menu", 0) and tr[6]["drawn"] == "world"
        and tr[7]["pose"] == tr[2]["pose"] and tr[10]["lvdone"] == 0
        and tr[11]["pose"] != tr[10]["pose"]})
    return out


# ================================================================================================
# the run
# ================================================================================================
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fjm")
    ap.add_argument("--labels")
    ap.add_argument("--oracle-only", action="store_true", help="the scenarios and controls, no binary")
    ap.add_argument("--player-mode", help="--oracle-only: the oracle's player mode (default wall_renderer's)")
    a = ap.parse_args(argv)
    if not a.oracle_only and not (a.fjm and a.labels):
        ap.error("--fjm and --labels (the build's label table), or --oracle-only")
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    if a.player_mode and a.player_mode != PLAYER_MODE and not a.oracle_only:
        ap.error("--player-mode %s: the binary is the game tier's (%s); another mode is for --oracle-only"
                 % (a.player_mode, PLAYER_MODE))
    global PLAYER_MODE_OVERRIDE
    PLAYER_MODE_OVERRIDE = a.player_mode or None
    t0 = time.time()
    orc = P.Oracle()
    if a.player_mode:
        orc.player_mode = a.player_mode
    dsim = onewalk.DoorSim()
    assert dsim.order == orc.door_order
    card = dsim.dp.card_at
    assert card == (2192, 576, 136), card
    card_di = [di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
               if t.type == CARD_TYPE]
    assert len(card_di) == 1, card_di
    scen = scenarios(dsim, card)
    ok = True
    print("P2A GATE -- %d scenarios (MONSTER_MODE %s, PLAYER_MODE %s)%s"
          % (len(scen), MONSTER_MODE, orc.player_mode, "" if a.oracle_only else ", %s" % a.fjm))
    if not a.oracle_only:
        gb = P.GameBinary(ROOT / a.fjm)
        cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
        table = P.LabelTable.load(ROOT / a.labels, {c.label for c in cells.values()})
        assert not table.absent & {"dreq", "pcard", "wfired"}, (
            "the label table has no %s: a binary before P2a.1" % sorted(table.absent))
    for sc in scen:
        mirror = hooked(Mirror(dsim, card_di[0]), orc, dsim, card_di[0])
        want = mirror.run(sc["pose"], sc["keys"], sc["pcard"])
        claim = bool(sc["claim"](want))
        ok &= claim
        print("\n%s -- %d frames from (%.0f, %.0f) angle %08x%s" % (
            sc["name"], len(sc["keys"]), sc["pose"][0] / 65536, sc["pose"][1] / 65536, sc["pose"][2],
            ", pcard poked 1" if sc["pcard"] else ""))
        print("  the oracle does what the scenario claims: %s" % ("yes" if claim else "NO -- FAIL"))
        for ctl in sc["controls"]:
            alt = hooked(Mirror(dsim, card_di[0], ctl), orc, dsim, card_di[0]).run(sc["pose"], sc["keys"],
                                                                               sc["pcard"])
            part = next((f for f, (x, y) in enumerate(zip(want, alt))
                         if expected_cells(x, dsim.order, dsim.mp.order)
                         != expected_cells(y, dsim.order, dsim.mp.order)), None)
            ok &= part is not None
            print("  CONTROL %-8s the oracle without the rule parts at frame %s%s" % (
                ctl, part, "" if part is not None else " -- NEVER: the scenario is VACUOUS, FAIL"))
        if a.oracle_only:
            continue
        reads = []
        p = P.Probe(cells, table, gb.width)

        def start(pr, f, sc=sc):
            vals = {k: int(bool(sc["keys"][f].get(n))) for n, k in KEYFLAG.items()}
            if f == 0:
                vals.update({"mode": 0, "viewx": _signed(sc["pose"][0], 32),
                             "viewy": _signed(sc["pose"][1], 32), "viewangle": sc["pose"][2],
                             "pcard": sc["pcard"]})
            pr.write_cells(vals)
        p.on_frame_start(start)
        # every cell the probe holds (P.game_cells: each later rung's group joins there), not READ alone -- READ was
        # a hand list the P4 cells never joined, so the binary's side of their comparison read None
        assert set(READ) <= set(cells), sorted(set(READ) - set(cells))
        p.on_present(lambda pr, f: reads.append(pr.read_cells(list(cells))))
        r = gb.run(len(sc["keys"]), menu_events(sc["keys"]), p)
        s_bad = x_bad = p_bad = None
        for f, fr in enumerate(want):
            exp = expected_cells(fr, dsim.order, dsim.mp.order)
            got = reads[f] if f < len(reads) else {}
            if s_bad is None and any(got.get(k) != v for k, v in exp.items()):
                s_bad = (f, {k: (got.get(k), v) for k, v in exp.items() if got.get(k) != v})
            if fr["drawn"] == "world":
                pic = picture(orc, dsim, fr, card_di)
            else:
                pic = screen(orc, fr["drawn"][1], fr["drawn"][2])
            if x_bad is None and (f >= len(r.frames) or r.frames[f] != pic):
                x_bad = (f, P.px_diff(r.frames[f], pic) if f < len(r.frames) else -1)
            # M7 P5: the palette the present showed -- combat.palette_index on a world frame, 0 on a menu frame
            if p_bad is None and (f >= len(r.palettes) or r.palettes[f] != orc.palette_sha(fr["pal"])):
                p_bad = (f, fr["pal"])
        ok &= s_bad is None and x_bad is None and p_bad is None
        print("  binary: %d frames, %s ops -- STATE %s, PIXELS %s, PALETTE %s" % (
            len(r.frames), format(r.ops, ","),
            "exact on every frame" if s_bad is None else "PART at frame %d: %s" % s_bad,
            "byte-exact on every frame" if x_bad is None else "PART at frame %d (%d px)" % x_bad,
            "exact on every frame" if p_bad is None else "PART at frame %d (the oracle's PLAYPAL %d)" % p_bad))
    print("\nP2A GATE %s (%.0f s)" % ("PASS" if ok else "FAIL", time.time() - t0))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
