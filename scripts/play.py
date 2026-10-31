#!/usr/bin/env python
"""play.py -- PLAY a game binary: a key log from boot (NEW GAME at the skill), every frame from the BINARY, and -- with
--check -- THE ORACLE stepping the same keys, held to the binary byte- and state-exact on every frame.

    python scripts/play.py SESSION [KEYS ...] --map E1M2 --fjm build/doom_e1m2_r4.fjm \
        --labels scratchpad/12m/atlas/e1m2_r4.labels.tsv.gz [--skill easy|medium|hard] [--check] [--every 2] [--show N]

SESSION is a directory: keys.json (the log), sheet_<n>.png (the newest frames, annotated), map_<n>.png (an automap
around the player with his trail), state.txt (one line a frame). KEYS append frames: a token is a set of letters held
for one frame, `*n` repeats it:
    f forward  b back  < strafe left  > strafe right  l turn left  r turn right  u use  F fire  1-5 weapons  . nothing
e.g. `f*20 fl*4 u . .`; `undo N` drops the last N frames. `@goto:X,Y` (last) appends a closed-loop walk to (X, Y)
steered on the BINARY's pose (`Steer`, the playthrough gate's steering, with a one-leg route planned by
scripts/level_route.py from wherever the log left the player), `@route` the whole level route.

THE COMPOSITION (m2_std_gate's): the binary boots into the main menu; `boot_pick(skill)` presses enter, picks the skill
and enters NEW GAME (frame `mf`, the first world frame); every later frame's keys arrive as REAL key events on the
frame's first polls (down when a key starts being held, up when it stops), never as poked cells. The frame acts on
`doomfj.keyboard.frame_keys` of those events -- the device's own rule -- and the oracle (scratchpad/gp/p2a_gate.Mirror,
`steps(boot=True)`: menus, NEW GAME, the doors, movers, monsters, weapon, pickups, deaths and LEVEL COMPLETE in the
binary's order) steps the very same per-frame keys. With --check each frame is compared as the game-tier gates compare
it (fight_gate.binary_scenario): every cell `p2a_gate.expected_cells` names, read through the build's label table;
the picture (`p2a_gate.picture` / `p2a_gate.screen`); the palette. The first frame that parts STOPS the run and writes
mismatch_f<n>.png (binary | oracle | diff) and .json into the session.

Closed-loop decisions are made at a frame's START from the cells the binary presented at the end of the frame before:
the pose the BINARY reached, never the oracle's. `Player` is the library the playthrough gate drives.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _q in (ROOT / "scripts", ROOT / "scratchpad" / "gp", ROOT / "scratchpad" / "12m", ROOT / "scratchpad",
           ROOT / "src"):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

LET = {"f": "forward", "b": "back", "<": "strafe_left", ">": "strafe_right", "l": "turn_left", "r": "turn_right",
       "u": "use", "F": "fire", "1": "w1", "2": "w2", "3": "w3", "4": "w4", "5": "w5"}
NAME_LET = {v: k for k, v in LET.items()}
# the cells the steering and the session log read (every frame, with or without the oracle)
STEER_CELLS = ("viewx", "viewy", "viewangle", "mode", "menu_scr", "lvdone", "p_hp", "p_ar", "p_dead", "dstate",
               "lstate", "mon_active", "mon_health", "mon_target", "thseen", "thpos_rt", "am_clip", "am_shell",
               "wp_own", "p_rct", "lvtime", "st_kill", "st_item", "am_misl")
M32 = 0xFFFFFFFF


def signed(v: int) -> int:
    v &= M32
    return v - (1 << 32) if v >> 31 else v


def hp12(v: int) -> int:
    """a monster's health cell as the number it holds: `mon_health` is 12 bits, signed (World's schema) -- a Baron
    killed to -1 reads 4095"""
    v &= 0xFFF
    return v - 0x1000 if v >> 11 else v


def pose_of(c: dict):
    """(x, y, angle in degrees) of the cells `c`, in map units"""
    return signed(c["viewx"]) / 65536.0, signed(c["viewy"]) / 65536.0, (c["viewangle"] & M32) * 360.0 / 2 ** 32


def keys_str(kd) -> str:
    return "".join(NAME_LET[n] for n in sorted(kd) if n in NAME_LET) or "."


def expand(tokens) -> list:
    out = []
    for t in tokens:
        n = 1
        if "*" in t:
            t, n = t.split("*")
            n = int(n)
        assert all(ch in LET or ch == "." for ch in t), t
        out += [frozenset(LET[ch] for ch in t if ch != ".")] * n
    return out


class Mismatch(Exception):
    pass


# ---- the picture workers: p2a_gate.picture in processes of their own (each its own Oracle on the active map) ------
PIC_KEYS = ("pose", "phase", "taken", "mheights", "views", "positions", "skw", "mobiles", "removed", "bviews",
            "skill", "vdrop", "wscroll", "lights", "switches")
_W = {}


def _pic_init():
    import onewalk
    import p2a_gate as G
    import probe as P
    from doomfj.things import drawable_things
    orc = P.Oracle()
    _W.update(G=G, orc=orc, dsim=onewalk.DoorSim(),
              card=([di for di, t in enumerate(drawable_things(orc.rm, orc.mw.things(orc.mapname), orc.art)[0])
                     if t.type == G.CARD_TYPE] or [-1])[0])


def _pic_render(fr):
    return _W["G"].picture(_W["orc"], _W["dsim"], fr, _W["card"])


_TEX_MEMO = {}


def memo_textures() -> None:
    """THE MODEL-ONLY DEV LOOP'S SPEED: `ReferenceModel._wall_texture` caches a composited wall texture per FRAME only,
    so every picture re-composites every wall texture it shows (97% of a model-only frame: 13,651 composites and
    116,560 patch decodes in 500 E1M5 frames). Its result is a pure function of (the asset wad, the name, the wall
    mode, the downscale) -- memoized here across frames, the same object handed back. Installed by `run_model` alone
    (the search and --model-only); the gate's oracle beside a binary runs the model's code untouched."""
    from doomfj.reference_model import ReferenceModel as RM
    if getattr(RM._wall_texture, "_memo", False):
        return
    orig = RM._wall_texture

    def wall_texture(self, asset_wad, name, cache, *, wall_mode="textured"):
        k = (id(asset_wad), name.upper(), wall_mode, self.downscale)
        if k not in _TEX_MEMO:
            _TEX_MEMO[k] = (asset_wad, orig(self, asset_wad, name, cache, wall_mode=wall_mode))
        return _TEX_MEMO[k][1]
    wall_texture._memo = True
    RM._wall_texture = wall_texture
    # the sprites likewise (`sprite_art` by thing type, `art_of_lump` by lump name: per-frame caches too)
    for name in ("sprite_art", "art_of_lump"):
        def wrap(orig, name=name):
            def art(self, sprite_wad, what, cache):
                k = (name, id(sprite_wad), what, self.downscale)
                if k not in _TEX_MEMO:
                    _TEX_MEMO[k] = (sprite_wad, orig(self, sprite_wad, what, cache))
                return _TEX_MEMO[k][1]
            return art
        setattr(RM, name, wrap(getattr(RM, name)))


class Player:
    """one binary run from boot, the oracle beside it (optional). `decide(frame, cells) -> set of key names` is asked
    at every world frame's start past the key log; `on_frame(rec)` sees every presented frame and may return "stop".

    run() -> a dict: frames presented, the key log played (from the NEW GAME frame on), the verdict ("budget",
    "stop", "mismatch"), the first mismatch, the seconds spent in the binary and in the oracle."""

    def __init__(self, fjm, labels, skill: str = "easy", check: bool = True):
        import onewalk
        import p2a_gate as G
        import probe as P
        from doomfj import gamedata as gd
        from doomfj.things import drawable_things
        self.P, self.G = P, G
        self.skill = skill
        self.sk = gd.SKILL_NAMES[skill]
        self.check = check
        self.orc = P.Oracle()
        self.mapname = self.orc.mapname
        self.dsim = onewalk.DoorSim()
        assert self.dsim.order == self.orc.door_order
        drawn = drawable_things(self.orc.rm, self.orc.mw.things(self.mapname), self.orc.art)[0]
        self.card_di = ([di for di, t in enumerate(drawn) if t.type == G.CARD_TYPE] or [-1])[0]
        self.gb = P.GameBinary(Path(fjm))
        orc = self.orc
        self.cells = P.game_cells(orc.ndoors, orc.nwalk, orc.nlift, orc.nmon, orc.nrt, orc.nthvis)
        self.table = P.LabelTable.load(Path(labels), {c.label for c in self.cells.values()})
        from m2_std_gate import boot_pick, menu_exit_events
        self.mf = boot_pick(self.sk)[-1][0]               # the NEW GAME frame: the first world frame
        self.menu_events = list(menu_exit_events(self.sk))
        self.workers = 0                  # world pictures rendered in this many worker processes (0: inline)
        self.oracle_keys = None           # R9 controls (playthrough_gate.py): (frame, kd) -> the oracle's kd
        self.binary_pic = None            # (frame, pixels) -> the pixels compared as the binary's

    def run_model(self, keylog, frames: int, decide=None, on_frame=None) -> dict:
        """THE MODEL ALONE (no binary, no picture): the oracle steps the keys from boot and the steering reads the
        cells the binary WOULD present (`p2a_gate.expected_cells`). For developing a route's steering without the
        binary (or the heavy lock); never evidence -- the gate's verdict is Player.run's."""
        memo_textures()
        from doomfj.automap import has_page
        from doomfj.keyboard import frame_keys
        from doomfj.menu import menu_keys
        from doomfj.wall_renderer import STANDALONE_POLLS
        from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent
        from m2_std_gate import BINDING, CODE
        G = self.G
        mkeys = menu_keys(has_page(self.mapname))
        mirror = G.hooked(G.Mirror(self.dsim, self.card_di), self.orc, self.dsim, self.card_di)
        sp = self.dsim.spawn
        feed = {"kd": {}}

        class Feed:
            def __iter__(self):
                return self

            def __next__(self):
                return feed["kd"]
        gen = mirror.steps((sp.x, sp.y, sp.angle), Feed(), 0, boot=True)
        order, morder = self.dsim.order, self.dsim.mp.order
        events, held, log, prev = list(self.menu_events), frozenset(), list(keylog), None
        out = {"frames": 0, "verdict": "budget", "mismatch": None, "keys": log}
        t0 = time.time()
        for f in range(frames):
            if f > self.mf:
                i = f - self.mf - 1
                kd = frozenset(log[i]) if i < len(log) else frozenset(decide(f, prev)) if decide else frozenset()
                if i >= len(log):
                    log.append(kd)
                for name in sorted(held ^ kd):
                    events.append(KeyEvent(f * STANDALONE_POLLS, name in kd, CODE[name]))
                held = kd
            fk = frame_keys(events, f + 1, polls=STANDALONE_POLLS, binding=BINDING, menu_keys=mkeys)[f]
            feed["kd"] = {**dict(fk.now), "menu": tuple(sorted(fk.menu))}
            fr = next(gen)
            prev = G.expected_cells(fr, order, morder)
            rec = {"f": f, "world": f - self.mf, "cells": prev, "fr": fr,
                   "keys": log[f - self.mf - 1] if 0 <= f - self.mf - 1 < len(log) else frozenset()}
            out["frames"], out["last"] = f + 1, rec
            if on_frame is not None and on_frame(rec) == "stop":
                out["verdict"] = "stop"
                break
        out["seconds"] = out["t_oracle"] = time.time() - t0
        out["t_binary"], out["ops"] = 0.0, 0
        return out

    def monster_rows(self) -> list:
        """monster slot -> its runtime-thing row (thpos_rt), the oracle's own MonsterViews mapping"""
        mv = getattr(self.orc, "_mviews", None)
        if mv is None:
            from doomfj.monsters import MonsterPhase
            mv = self.orc._mv(MonsterPhase(self.dsim.mw, self.mapname, self.sk, rm=self.dsim.rm).world)
        return list(mv.rt)

    def run(self, keylog, frames: int, decide=None, on_frame=None, tail: int = 0) -> dict:
        """`keylog`: per world frame (from the NEW GAME frame) a set of key names; then `decide` until `frames`
        frames have been presented (or `on_frame` says stop); `tail` idle frames after the log when no `decide`"""
        P, G = self.P, self.G
        from doomfj.automap import has_page
        from doomfj.keyboard import frame_keys
        from doomfj.menu import menu_keys
        from doomfj.wall_renderer import STANDALONE_POLLS
        from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent
        from flipjump.utils.exceptions import IOReadOnEOF
        from m2_std_gate import BINDING, CODE
        mkeys = menu_keys(has_page(self.mapname))
        if decide is None:
            frames = min(frames, self.mf + 1 + len(keylog) + tail)
        events = list(self.menu_events)
        live = {"held": frozenset(), "src": None, "screen": None}
        log = list(keylog)
        p = P.Probe(self.cells, self.table, self.gb.width)
        names_steer = [k for k in STEER_CELLS if k in p.cells]
        out = {"frames": 0, "verdict": "budget", "mismatch": None, "keys": log, "t_oracle": 0.0, "records": []}
        gen = None
        pool, pend = None, collections.deque()
        if self.check and self.workers:
            import multiprocessing as MP
            pool = MP.get_context("spawn").Pool(self.workers, initializer=_pic_init)

        def collect(block):
            while pend and (block or pend[0][2].ready()):
                f0, pic0, ar = pend.popleft()
                want0 = ar.get()
                out["pictures"] = out.get("pictures", 0) + 1
                if want0 != pic0 and (out["mismatch"] is None or out["mismatch"]["frame"] > f0):
                    out["mismatch"] = {"frame": f0, "cells": {}, "ncells": 0, "palette": None,
                                       "px": P.px_diff(pic0, want0) if len(pic0) == len(want0) else -1}
                    out["verdict"] = "mismatch"
                    out["mismatch_pics"] = (f0, pic0, want0)
        if self.check:
            mirror = G.hooked(G.Mirror(self.dsim, self.card_di), self.orc, self.dsim, self.card_di)
            sp = self.dsim.spawn
            feed = {"kd": {}}

            class Feed:
                def __iter__(self):
                    return self

                def __next__(self):
                    return feed["kd"]
            gen = mirror.steps((sp.x, sp.y, sp.angle), Feed(), 0, boot=True)
        order, morder = self.dsim.order, self.dsim.mp.order
        state = {"names": None, "prev": None}

        def start(pr, f):
            # the world frames after NEW GAME's: the log, then `decide` -- each frame's changes as key events on its
            # first polls (the NEW GAME frame itself carries the menu's enter alone)
            if out["verdict"] in ("mismatch", "stop"):      # (raised here, on the keyboard's read: core.run's EOF)
                raise IOReadOnEOF("play.py: %s at frame %d" % (out["verdict"], f - 1))
            if f <= self.mf:
                return
            i = f - self.mf - 1
            if i < len(log):
                kd = frozenset(log[i])
            elif decide is not None:
                kd = frozenset(decide(f, state["prev"]))
                log.append(kd)
            else:
                kd = frozenset()
            for k, name in enumerate(sorted(live["held"] ^ kd)):
                ev = KeyEvent(f * STANDALONE_POLLS, name in kd, CODE[name])
                live["src"].events.append(ev)
                events.append(ev)
            live["held"] = kd

        def present(pr, f):
            screen = live["screen"]
            pic, pal = screen.frames[-1], screen.shown_palettes[-1]
            if self.binary_pic is not None:               # the R9 control: a wrong pixel in the BINARY's frame
                pic = self.binary_pic(f, pic)
            rec = {"f": f, "world": f - self.mf, "keys": log[f - self.mf - 1] if 0 <= f - self.mf - 1 < len(log)
                   else frozenset()}
            if gen is not None:
                t = time.time()
                fk = frame_keys(events, f + 1, polls=STANDALONE_POLLS, binding=BINDING, menu_keys=mkeys)[f]
                feed["kd"] = {**dict(fk.now), "menu": tuple(sorted(fk.menu))}
                if self.oracle_keys is not None:          # the R9 control: the ORACLE's keys mutated
                    feed["kd"] = self.oracle_keys(f, feed["kd"])
                fr = next(gen)
                exp = G.expected_cells(fr, order, morder)
                if state["names"] is None:
                    missing = sorted(k for k in exp if k not in pr.cells)
                    if missing:
                        raise Mismatch("the oracle names cells the probe cannot read: %s" % missing)
                    state["names"] = sorted(exp)          # the steering sees exactly what the model run sees
                got = pr.read_arrays(state["names"])
                bad = {k: (got.get(k), v) for k, v in exp.items() if not P.same_reading(got.get(k), v)}
                if fr["drawn"] == "world" and pool is not None:
                    # the world picture in a worker (the same p2a_gate.picture, its own Oracle): compared when it
                    # comes back, a few frames on -- the first parting frame is still the one reported
                    pend.append((f, pic, pool.apply_async(_pic_render, ({k: fr.get(k) for k in PIC_KEYS},))))
                    want = pic
                else:
                    want = (G.picture(self.orc, self.dsim, fr, self.card_di) if fr["drawn"] == "world" else
                            G.screen(self.orc, fr["drawn"][1], fr["drawn"][2], fr["live"], fr["stats"]))
                wpal = self.orc.palette_sha(fr["pal"])
                collect(False)
                out["t_oracle"] += time.time() - t
                rec.update(fr=fr, oracle_pic=want)
                if bad or want != pic or wpal != pal:
                    some = list(bad.items())[:8]
                    out["mismatch"] = {"frame": f, "cells": {k: [str(a), str(b)] for k, (a, b) in some},
                                       "ncells": len(bad), "px": P.px_diff(pic, want) if len(pic) == len(want) else -1,
                                       "palette": None if wpal == pal else [pal, wpal, fr["pal"]]}
                    out["verdict"] = "mismatch"
            else:
                got = pr.read_arrays(names_steer)
            rec.update(cells=got, pic=pic, pal=pal)
            state["prev"] = got
            out["frames"] = f + 1
            if on_frame is not None and on_frame(rec) == "stop" and out["verdict"] != "mismatch":
                out["verdict"] = "stop"
            out["last"] = rec
        p.on_frame_start(start)
        p.on_present(present)
        import flipjump.interpreter.io_devices.KeyboardIO as KIO
        import probe as _probe
        base_src = KIO.ScriptedKeyEventSource
        base_dev = _probe._devices

        class LiveSource(base_src):
            def __init__(self, evs):
                super().__init__(evs)
                live["src"] = self

        def devices():
            Screen, Keyboard, EOF = base_dev()

            class LiveScreen(Screen):
                def __init__(self, *a, **kw):
                    super().__init__(*a, **kw)
                    live["screen"] = self

                def _present(self):                    # keep only the newest frame: a level is thousands
                    super()._present()
                    if len(self.frames) > 2:
                        self.frames[0] = None
                        self.shown_palettes[0] = None
            return LiveScreen, Keyboard, EOF
        KIO.ScriptedKeyEventSource = LiveSource
        _probe._devices = devices
        t0 = time.time()
        try:
            r = self.gb.run(frames, sorted(events, key=lambda e: e.tic), p)
        finally:
            KIO.ScriptedKeyEventSource = base_src
            _probe._devices = base_dev
        if pool is not None:
            t = time.time()
            collect(True)
            pool.terminate()
            out["t_oracle"] += time.time() - t
        out["seconds"] = time.time() - t0
        out["t_binary"] = out["seconds"] - out["t_oracle"]
        out["ops"] = r.ops
        out["frame_ops"] = p.frame_ops()        # M8 (the owner, 2026-10-29): the playthrough's speed set reads them
        return out


# ================================================================================================================
# the steering: a route's legs, followed closed-loop on the binary's pose, fighting what attacks
# ================================================================================================================
class Steer:
    """`decide(frame, cells)` for Player.run: walks `legs` (scripts/level_route.py's) and does each leg's action.

    NAVIGATION: pure pursuit along the leg's cell path (a teleport marker splits it; the pose jumping onto the next
    piece's first point advances it), a few cells ahead; turn on the spot when the heading is far off. A DOOR on the
    path ahead that is not open yet (the binary's dstate below the door's pass state) is pressed with use from inside
    its box and waited for. A LIFT ahead whose floor is too high to step on is waited for (or its use box pressed);
    standing on a lift that is moving, the player rides. STUCK (no progress) -> a strafe wiggle, then a re-plan of
    the leg from where the player is (level_route's planner, the world as the route has it then).
    THE ACTION at a leg's end: touch (walk onto the key's touch point), use (a use TAP: the press edge exits and
    switches need), cross (walk to the cell past the line).
    COMBAT: a monster the binary's last picture SAW (`thseen`), alive, awake and hunting the player, within FIGHT_R:
    turn to it and fire when lined up; a monster shot at for GIVE_UP frames with no damage is ignored for a while.
    THE WEAPON (`_arm`): the chaingun while it has 20 bullets, else the shotgun while it has shells, else the pistol,
    else the saw / fist -- never the launcher (DOOM switches to a weapon picked up; its blast hurts close in). While
    fighting: circle-strafe; back away from a demon, and from anything when hurt; close in with the shotgun on a far
    foe that is not a hitscanner. RETREAT: badly hurt and still being hit, back along his own trail for a while, then
    re-plan. No fight on a damaging floor (the planner's paths avoid them: level_route.HURT_COST). Low health: a detour
    to the nearest medikit / stimpack, further when very low.
    No cheat of any kind: every key is one a player could press."""

    FIGHT_R = 900
    HITSCAN = frozenset({3004, 9, 65})        # zombieman, sergeant, chaingunner: their spread is an ANGLE -- far is safer
    MELEE = frozenset({3002, 58})             # demon, spectre: back away while shooting
    # the tactics' knobs (BOT_CFG, a JSON of them, overrides for an evaluation run -- scratchpad/gp/bot/evalseeds.py).
    # The defaults are the measured ones: on E1M2 easy, seeds 0..7 whole plays, the retreat / back-when-low /
    # close-strafe OFF and RUN_HURT 30 averaged 17.8 legs of ~25 (all ON: 13.2; scratchpad/gp/bot/ev_e1m2_*.log)
    RETREAT = False            # badly hurt and still hit: back along the trail
    LOW_BACK = False           # hurt: back away from the foe while shooting
    CLOSE_STRAFE = False       # circle-strafe close in too (not only past 120 units)
    BURN = 0.35                # health a damaging-floor cell ahead costs (10 a 32 frames at ~16 units a frame, 16-unit cells)
    RACE_FAR = 120             # a lift called from a switch this far (units) from it is raced back to, backwards
    BARREL_SAFE = 220          # no shot while a barrel this near (Chebyshev) is in the aim window
    RUN_HURT = 30              # > 0: losing this much health in 60 frames (below 70) -> run the route for 60 frames
    DASH = 160                 # cells of route left under which the player stops fighting and runs for the exit
    LOOK = 3
    GIVE_UP = 35
    SEEK_FAR = True            # very low health (a HEALTH seek allowing SEEK_FAR_MOST cells): past the 3 nearest, by path
    SEEK_FAR_MOST = 250
    # an IGNORED monster (GIVE_UP: shot at with no damage, or passed by) that comes this near AND is the one hurting the
    # player (p_atk, hurt in the last 30 frames) is fought again: E1M4's corridor at (-2005, -600) -- two imps ignored at
    # world 1558, then clawing him at 40-50 units for 70 frames while the steering walked into them (115 -> 5 health);
    # seed 0 the same at (-2011, -352) (57 -> 3). Near alone is not enough: an imp behind a sill 117 units off, never
    # hurt by a shot and never hurting, held E1M4 seed 3 for 8,000 frames when near alone lifted the ignore. And only
    # in CONTACT (64 units) with the walk BLOCKED (no progress on the path for IGN_STUCK frames). A MAP TACTIC (MAP_TACTICS,
    # E1M4 only): on every map it moved the pinned plays -- at 128 units E1M5's, E1M6's and E1M9's died, in contact and
    # blocked E1M9's still died and E1M6's ended at another frame. On E1M4, seeds 0..7: 9.6 legs a play on average
    # against 8.1 without it (scratchpad evaluation, 2026-10-30)
    IGN_NEAR = 0
    IGN_STUCK = 8
    # per-map overrides of the knobs above (BOT_CFG still overrides both): a tactic that helps one map and moves the other
    # maps' pinned plays is that map's alone
    MAP_TACTICS = {"E1M4": {"IGN_NEAR": 64, "CHANNEL_SUIT": True, "AMMO_LOW": 20, "AMMO_TYPES": (8,),
                            "SAVE_R": 300, "SEEK_AVOID": ((450, 1250, 1100, 1900),), "CHANNEL_COMMIT": True,
                            "CROSS_HP": 50, "SEEK_MAX_BURN": 8, "DROP_LOW": 60, "SAVE_LOW": 40, "CROSS_AMMO": 20,
                            "END_NO_AMMO": True},
                   "E1M7": {"SKIP_ITEMS": (2002,)}}
    # SEEK_AVOID: boxes (x0, y0, x1, y1) whose items no detour seeks -- E1M4's stimpacks (496, 1840), (816, 1840) and
    # the near suit (912, 1520) lie among imps: the channel rule's detours there killed every play that reached the
    # armor leg (deaths at (530..1000, 1300..1840)); the route takes the health by the corridor instead (level_route
    # MAP_PICKUPS)
    SEEK_AVOID = ()
    CHANNEL_COMMIT = False     # on a damaging floor no new detour starts (E1M4: see the seeks in _decide)
    CROSS_HP = 0               # > 0: at this health or more, a damaging stretch ahead -> no ammo detour (go now)
    CROSS_AMMO = 0             # > 0: ... but only with this many bullets (or a shell); under it, the far ammo first
    SEEK_MAX_BURN = None       # a detour (any seek) crosses at most this many damaging cells (None: no cap) -- E1M4:
    #                            the damaging-stretch rule sent a 13-health play to the medikit beyond the channel, and
    #                            ammo detours after the medikit crossed the channel back west (dead at (1780, 957))
    # AMMO (E1M4's tactic; 0 / () off): under AMMO_LOW bullets with no shell, a dead zombieman's clip within DROP_R
    # (DROP_MOST cells) first, then -- under 5 -- the map's ammo up to AMMO_FAR_MOST cells off, AMMO_TYPES joining the
    # list (the backpack (1536, 240) beside the shell box (1424, 240)); SAVE_R: short of ammo, no shot past it and none
    # in passing at a monster given up on. E1M4's best plays ran dry for the last 700 frames and died punching
    AMMO_LOW = 0
    DROP_LOW = 0               # > 0: dropped clips are sought under this many bullets, shells or not
    AMMO_TYPES = ()
    SAVE_R = 0
    SAVE_LOW = 0               # SAVE_R binds under this many bullets with no shell (0: AMMO_LOW)
    DROP_MOST = 60
    DROP_R = 700
    AMMO_FAR_MOST = 400
    CHANNEL_SUIT = False       # a long damaging stretch ahead, too little health, none in reach: a radiation suit
    FLOORS_SEEN = True         # a floor group the game moved joins the steering's world (_floors_seen)
    ITEM_SEEK_HP = 30          # > 0: under this health a LONG route pickup's leg seeks health too (0: never, as before)
    ITEM_SEEK_LEN = 200        # ... a leg planned this many cells or more (E1M4's chaingun 239, armor 316; the pinned
    #                            plays' shorter pickup legs keep the old rule: E1M5 185, E1M9 86 -- both died with it)
    FLOOR_SEEK_F = 120         # ... or any pickup leg this many frames after a moved floor joined the world: E1M4's
    #                            yellow card lowers the way to two medikits 22-27 cells off, and the clip-box leg after
    #                            it (62 cells) walked away from them at 1 health
    # the route's pickup legs this map's play skips (item types; () none): E1M7's chaingun (352, 1504) is a 127-cell
    # detour into a room of imps, demons and sergeants -- every play of the 2026-10-30 model search (seeds 0..4 and their
    # schedules, 14 attempts) died there or on the health detour beside it, at 23..48 health
    SKIP_ITEMS = ()
    END_NO_AMMO = False        # on the last DASH cells of the route no ammo detour (E1M4: see `near_end` in _decide)

    def __init__(self, route: dict, lv=None, log=print, seed: int = 0):
        sys.path.insert(0, str(ROOT / "scripts"))
        import os
        for k, v in self.MAP_TACTICS.get(str(route.get("map", "")).upper(), {}).items():
            setattr(self, k, v)
        for k, v in json.loads(os.environ.get("BOT_CFG") or "{}").items():
            assert hasattr(Steer, k), k
            setattr(self, k, v)
        import level_route as LR
        self.LR = LR
        self.lv = lv or LR.Level(route["map"], route.get("wad"), route["skill"])
        self.pl = LR.Planner(self.lv)
        self.route = route
        self.legs = [dict(g, cells0=len(g["path"] or ())) for g in route["legs"]    # cells0: the planned length
                     if not (g["kind"] == "item" and int(str(g["to"]).split(":")[-1] or 0) in self.SKIP_ITEMS)]
        self.log = log
        self.seed = seed
        self.li = 0
        self._leg(0)
        self.f0 = None
        self.last_pose = None
        self.stuck = 0
        self.wiggle = 0
        self.ign, self.trk, self.covered = {}, {}, {}
        self.floor_f = -1 << 30                      # the frame a moved floor last joined the world (_floors_seen)
        self.active = set()                          # mechanisms the legs done so far triggered (re-plans use them)
        self.keys = set()
        self.use_tap = 0
        self.fired = False
        self.last_turn = False
        self.ride = 0
        self.hurt_f = -1000
        from doomfj import gamedata as gd
        bit = gd.skill_bit(gd.SKILL_NAMES[route["skill"]])
        # health on the map at this skill (the stimpack, the medikit, the soulsphere): sought when health runs low
        lifts = set(self.lv.mp.order) if self.lv.mp is not None else set()       # (an item on a lift: see pickup_things)
        self.health = [(t.x, t.y) for t in self.lv.things if t.type in (2011, 2012, 2013) and t.flags & bit
                       and self.lv.sector_at(t.x, t.y) not in lifts]
        self.ammo = [(t.x, t.y) for t in self.lv.things if t.type in (2007, 2008, 2048, 2049) and t.flags & bit
                     and self.lv.sector_at(t.x, t.y) not in lifts]
        self.suits = [(t.x, t.y) for t in self.lv.things if t.type == 2025 and t.flags & bit
                      and self.lv.sector_at(t.x, t.y) not in lifts]
        self.ammo += [(t.x, t.y) for t in self.lv.things if t.type in self.AMMO_TYPES and t.flags & bit
                      and self.lv.sector_at(t.x, t.y) not in lifts]
        from doomfj.world import level_things
        self.mtype = [t.type for t in level_things(self.lv.mw, self.lv.map)[1]]     # monster slot -> its type
        from doomfj.combat import DROP_ITEM
        drop = [DROP_ITEM.get(gd.DROPS.get(gd.MONSTER_DOOMEDNUMS.get(t))) for t in self.mtype]
        self.droppers = [m for m, k in enumerate(drop) if k is not None]     # dropper k: the k-th drop row
        self.drop_kind = [drop[m] for m in self.droppers]
        # the barrels (their spawn spots; aim_sid's id 1 + nmon + b, combat.window_aim): never shot close by
        self.barrels = [(t.x, t.y) for t in level_things(self.lv.mw, self.lv.map)[2]]
        self.trail = collections.deque(maxlen=400)   # the player's own recent positions: the way back (a retreat)
        self.retreat_f, self.retreat_i, self.retreat_next = -1, 0, -1
        self.hp_hist = collections.deque(maxlen=60)
        self.run_until = -1
        self.health_taken = set()
        self.called = {}                             # lift sector -> the frames its switch was walked to
        self.race = None                             # (lift sector, until frame): racing back to a far-called lift
        self.retry = {}
        self.why = ""
        self.done_frame = None
        self.events = []
        self.rt = None
        self.dorder = self.lv.door_order
        self.lorder = self.lv.mp.order if self.lv.mp is not None else []
        from doomfj.doors import pass_state
        self.dpass = {si: pass_state(self.lv.secs, self.lv.lds, self.lv.sds, si) for si in self.dorder}

    # ---- legs and paths ------------------------------------------------------------------------------------------
    def _leg(self, i):
        self.li = i
        self.leg = self.legs[i] if i < len(self.legs) else None
        self.pieces, self.pi, self.wi = [], 0, 0
        if self.leg and self.leg["path"]:
            cur = []
            for p in self.leg["path"]:
                if p[0] == "teleport":
                    self.pieces.append(cur)
                    cur = []
                else:
                    cur.append(tuple(p))
            self.pieces.append(cur)
        self.leg_frames = 0
        self.lift_wait = 0
        self.end_best, self.end_f = 1e9, 1 << 30
        self.final = 0
        self.queue = []
        self.best_prog, self.best_f = (-1, -1), 1 << 30
        self.act = 0
        self.sig0 = None
        self.hunt_f = 1 << 30                        # M8 C8: the kill leg's next re-plan toward a boss

    def replan(self, x, y, why, f=None):
        """the rest of the leg from the player's pose, in the world the route has by now"""
        LR = self.LR
        goal = tuple(self.leg["path"][-1])
        gcell = LR.cell_of(*goal)
        opn = {"door:%d" % si for si in self.dorder if self.lv.dp.boxes.get(si) is not None
               and (not self.pl.mechs["door:%d" % si].key or self.pl.mechs["door:%d" % si].key in self.keys)}
        path = self.pl.leg_path(LR.cell_of(x, y), lambda c: c == gcell, self.active | opn)
        wide = ""
        if not path:                                 # the flood's world: every mechanism it found
            path = self.pl.leg_path(LR.cell_of(x, y), lambda c: c == gcell,
                                    self.active | opn | set(self.route.get("flood", {}).get("activated", ())))
            wide = " (in the flood's world)" if path else ""
        self.log("    re-plan (%s) from (%d, %d): %s%s" % (why, x, y, "%d cells" % len(path) if path else "NO PATH",
                                                       wide))
        if not path and self.leg["kind"] == "item" and f is not None:
            self._next(f, "unreachable from here: the detour is dropped")
            return False
        if path:
            self.leg["path"] = [list(LR.centre(c)) if c[0] != "teleport" else ["teleport", c[1]] for c in path]
            keep = (self.li, self.leg, self.leg_frames)
            self._leg(keep[0])
            self.leg = keep[1]
            self.leg_frames = keep[2]                # a re-plan is the same leg: its watchdogs keep counting
            self._leg_pieces()
        return bool(path)

    def _leg_pieces(self):
        self.pieces, cur = [], []
        for p in self.leg["path"]:
            if p[0] == "teleport":
                self.pieces.append(cur)
                cur = []
            else:
                cur.append(tuple(p))
        self.pieces.append(cur)
        self.pi, self.wi = 0, 0

    # ---- helpers -------------------------------------------------------------------------------------------------
    def _floors_seen(self, f, c):
        """FLOORS_SEEN: a floor group the game moved to its end (the wide `fswitch` vector: each group's state first)
        joins the world the re-plans and the health / ammo detours are planned in, whatever moved it -- E1M4's group 0
        (sector 43) is lowered by the W1 square round the yellow card, which is a key leg, not a floor leg: the two
        medikits behind it (-1344, 720), (-576, 720) were never in reach of a seek (22 and 27 cells from the card)"""
        mp = self.lv.mp
        sw = c.get("fswitch")
        if mp is None or not getattr(mp, "wide", False) or not isinstance(sw, (tuple, list)):
            return
        for g, grp in enumerate(mp.groups):
            mid = "floor:%d" % g
            if g < len(sw) and sw[g] >= grp.n - 1 and mid not in self.active:
                self.active.add(mid)
                self.floor_f = f                     # a new world: any pickup leg may seek health a while (FLOOR_SEEK_F)
                self.retry.pop("health", None)
                self.log("    f%d: %s moved -- in the world the detours are planned in" % (f, mid))

    def _turn_to(self, want, a, kd, tight=4.0):
        """turn toward `want`: a held turn is 7.0 degrees a frame, a TAP (no turn key the frame before) 1.76
        (reference_model.ANGLE_TURN_HELD / _TAP) -- so within 10 degrees, turn every other frame: taps only"""
        d = (want - a + 540) % 360 - 180
        if abs(d) > tight and not (abs(d) < 10 and self.last_turn):
            kd.add("turn_left" if d > 0 else "turn_right")
        return d

    def _retreat(self, f, c, x, y, a):
        """walk back along the trail (the positions he came by), fastest: forward, turned to a trail point a few
        back; the aim window's hunters are still shot in passing -> keys, or None when the trail is used up"""
        while self.retreat_i > 0 and math.hypot(self.trail[self.retreat_i][0] - x,
                                                self.trail[self.retreat_i][1] - y) < 24:
            self.retreat_i -= 1
        if self.retreat_i <= 0:
            self.retreat_f = -1
            return None
        tx, ty = self.trail[self.retreat_i]
        kd = set()
        want = math.degrees(math.atan2(ty - y, tx - x)) % 360
        d = self._turn_to(want, a, kd, tight=8)
        if abs(d) < 40:
            kd.add("forward")
        self.why = "retreat"
        self.last_pose = None
        if self.retreat_f <= f + 1:                  # the retreat ends: back on the route from wherever he is
            self.leg["replan"] = True
        return kd

    def _arm(self, f, c, kd) -> str:
        """the weapon to hold, and its key pressed (every 4th frame while it is not up and none is pending): the
        chaingun while it has 20 bullets, else the shotgun while it has shells, else the pistol while it has bullets,
        else the saw / fist -- never the launcher (its blast hurts the player close in; DOOM switches to a weapon
        picked up). -> "chaingun" / "shotgun" / "pistol" / "melee", the class of the weapon UP now"""
        from doomfj import gamedata as gd
        own = c.get("wp_own") or 0
        has = lambda nib: (own >> (4 * nib)) & 1                                  # noqa: E731 -- wp_own's nibbles
        clip, shell = c.get("am_clip") or 0, c.get("am_shell") or 0
        rdy = c.get("wp_rdy")
        if self._launch(c, has(4), rdy == gd.WP_MISSILE):
            want, key = gd.WP_MISSILE, "w5"          # M8 C8: a KILL leg's boss far off -- the launcher
        elif has(5) and clip >= 20:
            want, key = gd.WP_CHAINGUN, "w4"
        elif has(2) and shell:
            want, key = gd.WP_SHOTGUN, "w3"
        elif has(5) and clip:
            want, key = gd.WP_CHAINGUN, "w4"
        elif clip:
            want, key = gd.WP_PISTOL, "w2"
        else:
            want, key = (gd.WP_CHAINSAW if has(3) else gd.WP_FIST), "w1"
        rdy = c.get("wp_rdy")
        if rdy is not None and rdy != want and c.get("wp_pend") in (None, gd.WP_NOCHANGE, want) and f % 4 == 0                 and not (want == gd.WP_FIST and rdy == gd.WP_CHAINSAW):
            kd.add(key)
        return {gd.WP_CHAINGUN: "chaingun", gd.WP_SHOTGUN: "shotgun", gd.WP_PISTOL: "pistol",
                gd.WP_MISSILE: "launcher"}.get(rdy, "melee")

    # M8 C8: on a KILL leg the launcher is the weapon while the nearest live boss is far: up from LAUNCH_R units, kept
    # down to LAUNCH_KEEP (its blast reaches 128 round the boss; the switch costs frames, so no flapping between)
    LAUNCH_R = 224
    LAUNCH_KEEP = 176

    def _launch(self, c, owned, up) -> bool:
        if not owned or not (c.get("am_misl") or 0) or not self.leg or self.leg.get("action") != "kill":
            return False
        x, y, _a = pose_of(c)
        alive = self._bosses_alive(c)
        if not alive:
            return False
        d = min(math.hypot(bx - x, by - y) for _m, bx, by in alive)
        return d >= (self.LAUNCH_KEEP if up else self.LAUNCH_R)

    def _foe(self, c, x, y, f):
        """the nearest monster to fight: seen by the last picture, alive, hunting the player, within FIGHT_R"""
        if self.rt is None or "thseen" not in c:
            return None
        best = None
        hitter = (c.get("p_atk") or 0) - 1 if f - self.hurt_f < 30 else -1     # the monster hurting him now
        # M8 C8: on a KILL leg the bosses are fought whatever they target (asleep, or not yet turned on the player)
        bosses = {b[0] for b in self.leg.get("bosses", ())} if self.leg and self.leg.get("action") == "kill" else ()
        for m, row in enumerate(self.rt):
            if not c["mon_active"][m] or signed(c["mon_health"][m]) <= 0 or not c["thseen"][m]:
                continue
            if c["mon_target"][m] != 1 and m not in bosses:   # 0: asleep, 1: the player, 2+: another monster
                continue
            if m in bosses and hp12(c["mon_health"][m]) <= 0:   # (a boss's corpse: its 12-bit health below 0)
                continue
            v = c["thpos_rt"][row]
            mx, my = signed(v & M32) / 65536.0, signed((v >> 32) & M32) / 65536.0
            dd = math.hypot(mx - x, my - y)
            if self.ign.get(m, -1) > f and not (m == hitter and dd < self.IGN_NEAR
                                                and f - self.best_f >= self.IGN_STUCK):
                continue                             # (ignored -- unless it blocks the way and hurts him: IGN_NEAR)
            if dd <= self.FIGHT_R - 150 * (self.seed_at(f) % 2) and (best is None or dd < best[0]):
                best = (dd, mx, my, m)
        atk = (c.get("p_atk") or 0) - 1
        recent = f - self.hurt_f < 30 and self.ign.get(atk, -1) <= f
        if best is None and 0 <= atk < len(self.rt) and recent and signed(c["mon_health"][atk]) > 0:
            # hurt by a monster the last picture did not show (p_atk, 1 + slot): face it -- the next picture shows it
            v = c["thpos_rt"][self.rt[atk]]
            mx, my = signed(v & M32) / 65536.0, signed((v >> 32) & M32) / 65536.0
            best = (math.hypot(mx - x, my - y), mx, my, atk)
        if best is not None:
            m, h = best[3], signed(c["mon_health"][best[3]])
            t = self.trk.get(m)
            if t is None or h < t[1]:
                self.trk[m] = (f, h)
            elif f - t[0] > self.GIVE_UP and m not in bosses:   # shot at with no damage: leave it a while (never
                # a KILL leg's boss: he is the leg's goal, and he hunts the player whether shot or not)
                self.ign[m] = f + 150
                self.trk.pop(m, None)
                self.log("    f%d: monster %d ignored (no damage in %d frames)" % (f, m, self.GIVE_UP))
                return None
        return best

    def _door_boxes(self, si):
        """the boxes a press opens door `si` from: its own use box, and a mixed-card door's KEYED boxes
        (doors.keyed_boxes_xy: E1M3 150's blue east side) whose card the player holds"""
        out = [self.lv.dp.boxes[si]] if self.lv.dp.boxes.get(si) is not None else []
        return out + [b for b, card in getattr(self.lv.dp, "keyed", {}).get(si, ()) if card in self.keys]

    def _door_ahead(self, c, x, y, pts):
        """the first door on the next points that is not open yet: (sector, the boxes a press opens it from)"""
        LR = self.LR
        prev = (x, y)
        for q in pts:
            for k, si in enumerate(self.dorder):
                if c["dstate"][k] >= self.dpass[si]:
                    continue
                sec = self.pl.sector_of(LR.cell_of(*q))
                if sec == si or any(LR.seg_cross(prev, q, a, b) for a, b in self.pl.door_segs("door:%d" % si)):
                    return si, self._door_boxes(si)
            prev = q
        return None

    def _lift_ahead(self, c, x, y, pts):
        """a lift on the next points whose floor now is too high to step onto from here -> (lift index, sector)"""
        if not self.lorder:
            return None
        here = self.pl.floor_at(self.pl.scenes_for(()), self.LR.cell_of(x, y))
        for q in pts:
            sec = self.pl.sector_of(self.LR.cell_of(*q))
            if sec in self.lorder:
                k = self.lorder.index(sec)
                fl = self.lv.mp.stops[sec][min(c["lstate"][k], len(self.lv.mp.stops[sec]) - 1)]
                if fl - here > 24:
                    return k, sec
                return None
        return None

    # ---- the decision ----------------------------------------------------------------------------------------------
    def decide(self, f, c):
        self.opportune = None
        kd = self._decide(f, c)
        if c is not None and c.get("mode", 0) == 0 and not c.get("p_dead") and self.leg is not None:
            self._arm(f, c, kd)                      # the weapon to hold (a pickup switches to it: DOOM's rule)
        if self.opportune and "use" not in kd:
            kd.add("fire")
            self.fired = True
        if "fire" in kd and c is not None and self._barrel_near(c):
            kd.discard("fire")                       # a barrel by the player in the aim window: its blast is his
        self.last_turn = bool(kd & {"turn_left", "turn_right"})
        return kd

    def _decide(self, f, c):
        kd = set()
        if c is None or c.get("mode", 0) != 0 or self.leg is None:
            return kd
        if self.f0 is None:
            self.f0 = f
        if self.FLOORS_SEEN:
            self._floors_seen(f, c)
        x, y, a = pose_of(c)
        if c.get("p_dead"):
            return kd
        if c.get("p_rct"):                           # a teleport's reaction time: nothing moves
            return kd
        self.leg_frames += 1
        if self.leg["action"] == "kill" and not self._bosses_alive(c):
            return self._next(f, "every boss dead")      # M8 C8: A_BossDeath fires (its floor moves on its own)
        if self.retreat_f <= f and (not self.trail or math.hypot(x - self.trail[-1][0], y - self.trail[-1][1]) >= 12):
            self.trail.append((x, y))           # (not while retreating: the retreat indexes the trail)
        if self.retreat_f > f:
            kd = self._retreat(f, c, x, y, a)
            if kd is not None:
                return kd
        if self.leg_frames == 1 and self.pieces and self.pieces[0] and \
                math.hypot(self.pieces[0][0][0] - x, self.pieces[0][0][1] - y) > 48:
            self.replan(x, y, "the leg starts elsewhere", f)
            if self.leg is None:
                return set()
        if self.leg["kind"] == "item" and not self.leg.get("must") and                 self.leg_frames > max(300, 2 * len(self.leg["path"] or ()) + 100):
            return self._next(f, "the detour took 300 frames: dropped")
        if self.queue:                               # a precise approach in progress (a planned key sequence)
            self.why = "precise"
            return set(self.queue.pop(0))
        # ---- low health / no ammo: the nearest item first -- unless a monster is at arm's length
        foe = self._foe(c, x, y, f)
        # CHANNEL_COMMIT (a map tactic): standing on a damaging floor, no new detour -- the way on is shorter than the
        # way back (E1M4: plays that took the medikit died on health / suit detours started mid-channel, (2363..2537,
        # 1534..1596))
        free = (foe is None or foe[0] > 100) and not (self.CHANNEL_COMMIT and self.pl.hurts(self.LR.cell_of(x, y)))
        # END_NO_AMMO (a map tactic): on the route's last stretch (under DASH cells to the end) no ammo detour -- E1M4:
        # the first play to take the blue card stood 61 cells from the exit at 32 health and 0 ammo, walked 242 cells
        # back south for a clip and died at door 175 (world 4249)
        near_end = bool(self.END_NO_AMMO) and self.pieces and (
            sum(len(g["path"] or ()) for g in self.legs[self.li + 1:] if g["kind"] != "item")
            + max(0, len(self.pieces[self.pi]) - self.wi)) < self.DASH and self.leg["kind"] != "item"
        # CROSS_HP (a map tactic): healthy, with a long damaging stretch on the way ahead -- no AMMO detour: go now.
        # E1M4: a play reached the channel's leg at 93 health, then spent 5,000 frames on ammo detours back west and
        # crossed at 13 (dead of the floor at (2433, 1596))
        burn_ahead = (sum(1 for q in self.pieces[self.pi][self.wi:self.wi + 240] if self.pl.hurts(self.LR.cell_of(*q)))
                      if (self.CROSS_HP or self.CROSS_AMMO) and self.pieces else 0)
        # CROSS_AMMO (a map tactic): not into the stretch short of ammo -- an imp stands in E1M4's channel and blocks it;
        # seed 7 reached its mouth at 71 health with 6 bullets, stuck against the imp and died (2693, 1497)
        armed = (c.get("am_clip") or 0) >= self.CROSS_AMMO or bool(c.get("am_shell"))
        go_now = bool(self.CROSS_HP and (c.get("p_hp") or 0) >= self.CROSS_HP and burn_ahead > 20 and armed)
        fetch_first = bool(self.CROSS_AMMO and burn_ahead > 20 and not armed)
        if free and not self.use_tap and not c.get("p_rad") and self.health                 and self.pieces and self.leg.get("to") not in ("health", "suit"):
            # (any leg: E1M4's channel is crossed on the way to an item -- the armor beyond it)
            hp = c.get("p_hp") or 0
            ahead = self.pieces[self.pi][self.wi:self.wi + 240]
            burn = sum(1 for q in ahead if self.pl.hurts(self.LR.cell_of(*q)))
            if burn > 20 and hp < min(80, burn * self.BURN + 20) and self._seek_health(
                    f, x, y, self.health, "health", most=150, radius=2500, max_burn=self.SEEK_MAX_BURN):
                # (SEEK_MAX_BURN: not health beyond the stretch itself -- E1M4's seek picked the medikit at the channel's
                # far end at 13 health and the floor killed him on the way, (2433, 1596))
                self.log("    f%d: %d damaging cells ahead at %d health: health first" % (f, burn, hp))
                return kd
            if (burn > 20 and hp < min(80, burn * self.BURN + 20) and self.CHANNEL_SUIT and self.suits
                    and self._seek_health(f, x, y, self.suits, "suit", most=150, radius=2500,
                                          max_burn=self.SEEK_MAX_BURN)):
                # no health in reach: a radiation suit then (E1M4's near suit (912, 1520): an 18-leg play went into
                # the channel at 26 health with no health left in reach and died of the floor at (1995, 1437))
                self.log("    f%d: %d damaging cells ahead at %d health, no health in reach: the suit" % (f, burn, hp))
                return kd
        if free and not self.use_tap and self.leg["kind"] != "item":
            hp = c.get("p_hp") or 0
            want = 40 + 10 * (self.seed_at(f) % 3)              # the seed moves the health threshold too
            if hp < want + 25 and self.health and self._seek_health(
                    f, x, y, self.health, "health", most=250 if hp < 30 else 70 if hp < want else 25,
                    radius=3000 if hp < 30 else 900):
                return kd
            low_ammo = (c.get("am_clip") or 0) < 5 and not (c.get("am_shell") or 0)
            dry = not (c.get("am_clip") or 0) and not (c.get("am_shell") or 0)
            if low_ammo and not go_now and not near_end and self.ammo and self._seek_health(
                    f, x, y, self.ammo, "ammo", most=250 if dry else 70, radius=3000 if dry else 900):
                return kd
        elif (free and not self.use_tap and self.ITEM_SEEK_HP
              and str(self.leg.get("to")).startswith("item:")
              and (self.leg.get("cells0", 0) >= self.ITEM_SEEK_LEN or f - self.floor_f < self.FLOOR_SEEK_F)):
            # a ROUTE pickup's leg (not a detour of the steering's own) at very low health: the health first, as on
            # any other leg (E1M4: the armor's 316-cell leg crossed the map at 1-6 health and died on it) -- and with
            # no bullet and no shell left, ammo (E1M4: the same leg emptied the chaingun and died punching)
            if (c.get("p_hp") or 0) < self.ITEM_SEEK_HP and self.health and self._seek_health(
                    f, x, y, self.health, "health", most=250, radius=3000):
                self.log("    f%d: (the health above: on a route pickup's leg, ITEM_SEEK_HP)" % f)
                return kd
            if not go_now and not (c.get("am_clip") or 0) and not (c.get("am_shell") or 0) and self.ammo and self._seek_health(
                    f, x, y, self.ammo, "ammo", most=250, radius=3000):
                self.log("    f%d: (the ammo above: dry on a route pickup's leg, ITEM_SEEK_HP)" % f)
                return kd
        if (self.AMMO_LOW and free and not self.use_tap and not near_end
                and self.leg.get("to") not in ("ammo", "drop", "health", "suit")):
            # AMMO (a map tactic): short of bullets with no shell -- a clip a dead zombieman dropped near by first,
            # then the map's ammo FAR off when nearly dry (the backpack and shell box east, AMMO_TYPES)
            clip, shell = c.get("am_clip") or 0, c.get("am_shell") or 0
            if clip < max(self.AMMO_LOW, self.DROP_LOW) and (self.DROP_LOW or not shell) and not (
                    go_now and not self.DROP_LOW):
                # (DROP_LOW: the dropped clips are picked up below it, shells or not -- E1M4's best new-route play
                # reached the channel's mouth with 0 bullets and 0 shells and died there, world 5762; and before the
                # channel too (go_now holds back the FAR ammo only): seed 0 entered it with 0 / 0 and died in it)
                drops = self._live_drops(c)
                if drops and self._seek_health(f, x, y, drops, "drop", most=self.DROP_MOST, radius=self.DROP_R):
                    self.log("    f%d: (the drop above: %d bullets, AMMO_LOW)" % (f, clip))
                    return kd
                if (clip < 5 or fetch_first) and not shell and not go_now and self.ammo and self._seek_health(
                        f, x, y, self.ammo, "ammo", most=self.AMMO_FAR_MOST, radius=4000):
                    self.log("    f%d: (the ammo above: far off, %d bullets, AMMO_LOW)" % (f, clip))
                    return kd
        # ---- the DASH: when what is left of the route is short, run it -- stopping to fight a crowd on the last
        # stretch is how a worn-down player dies (E1M2's finale); the aim window's hunters are still shot in passing
        left = sum(len(g["path"] or ()) for g in self.legs[self.li + 1:] if g["kind"] != "item")
        left += max(0, len(self.pieces[self.pi]) - self.wi) if self.pieces else 0
        if left < self.DASH and (foe is None or foe[0] > 64) and self.leg["action"] != "kill":
            # (never on a KILL leg: the route goes on only once the bosses are dead)
            foe = None
            self.why = "dash"
        hp_now = c.get("p_hp") or 0
        self.hp_hist.append(hp_now)
        kill_leg = self.leg["action"] == "kill"
        if (self.RUN_HURT and hp_now < 70 and max(self.hp_hist) - hp_now >= self.RUN_HURT and f >= self.run_until + 120
                and not kill_leg):           # (a KILL leg's route runs AT the boss: no run there)
            self.run_until = f + 60                  # hurt fast: run the route a while (most hunters are slower)
            self.log("    f%d: run (lost %d in 60 frames)" % (f, max(self.hp_hist) - hp_now))
        if f < self.run_until and foe is not None and foe[0] > 80:
            foe = None
            self.why = "run"
        if foe is not None and foe[0] > 64 and not (c.get("am_clip") or 0) and not (c.get("am_shell") or 0):
            foe = None                               # dry (no bullet, no shell): run, punch only what is at arm's length
            self.why = "dry"
        if foe is not None and foe[0] > 100 and self.pl.hurts(self.LR.cell_of(x, y)):
            foe = None                               # on a damaging floor: walk on (shooting in passing), fight off it
        # ---- combat
        self.why = "nav %d/%d" % (self.wi, len(self.pieces[self.pi]) if self.pieces else 0)
        if foe is not None:
            m = foe[3]
            self.why = "fight m%d at %.0f" % (m, foe[0])
            want = math.degrees(math.atan2(foe[2] - y, foe[1] - x)) % 360
            # the AIM WINDOW the last picture recorded (`aim_sid`, 17 columns, 1 + slot): the weapon's next shot goes
            # to what it holds. Close in, the trigger is held (the refire's spread does not matter); far off, a fresh
            # press each shot (P_GunShot: the first shot of a pull is accurate)
            win = c.get("aim_sid") or ()
            aimed = (1 + m) in win
            d = (want - a + 540) % 360 - 180
            tol = max(1.0, math.degrees(math.atan2(14, max(foe[0], 1))))
            if abs(d) > tol:
                self._turn_to(want, a, kd, tight=tol)
            wp = self._arm(f, c, kd)
            # the trigger: HELD close in, and with the shotgun / chaingun / saw (the pellets and the burst spread
            # anyway); far off with the pistol, a fresh press each shot (P_GunShot: the first shot of a pull is accurate)
            hold = foe[0] < 320 or wp in ("shotgun", "chaingun", "melee")
            if wp == "launcher":                     # M8 C8: a rocket flies straight -- the window's middle, far off
                mid = win[max(0, len(win) // 2 - 2):len(win) // 2 + 3]
                if (1 + m) in mid and foe[0] >= self.LAUNCH_KEEP:
                    kd.add("fire")
            elif aimed and foe[0] < 800 and (hold or (not self.fired and not c.get("wp_rf"))) and not (
                    self.SAVE_R and foe[0] > self.SAVE_R and (c.get("am_clip") or 0) < (self.SAVE_LOW or self.AMMO_LOW)
                    and not (c.get("am_shell") or 0)):
                kd.add("fire")                       # (SAVE_R: short of ammo, no far shot -- the spread wastes it)
            if not aimed and abs(d) <= tol:          # lined up, but the window does not hold it: cover between
                self.covered[m] = self.covered.get(m, 0) + 1
                if self.covered[m] > 8:              # move on (a moving player is harder to hit); shoot when it shows
                    self.ign[m] = f + 60
                    self.covered[m] = 0
                    self.log("    f%d: monster %d passed by (lined up, not in the aim window)" % (f, m))
            if aimed:
                self.covered[m] = 0
            self.fired = "fire" in kd
            typ = self.mtype[m] if m < len(self.mtype) else 0
            boss = kill_leg and m in self._boss_slots()
            hp = c.get("p_hp") or 0
            low = hp < 35 + 10 * (self.seed_at(f) % 2)
            if self.RETREAT and hp < 25 + 10 * (self.seed_at(f) % 2) and f - self.hurt_f < 8 and f >= self.retreat_next                     and len(self.trail) > 8 and typ not in self.MELEE:
                # RETREAT: badly hurt and still being hit -- back the way he came, out of the shooter's sight (a
                # hitscanner hits what it sees; a hunter that follows is met round the corner)
                self.retreat_f, self.retreat_i, self.retreat_next = f + 45, len(self.trail) - 1, f + 150
                self.log("    f%d: retreat (hp %d, hit by m%d)" % (f, hp, m))
            if wp == "melee" and abs(d) < 20 and foe[0] > 40:
                kd.add("forward")                    # the fist / saw: close in
            elif ((typ in self.MELEE or boss) and foe[0] < (self.LAUNCH_R if boss else self.BACK_R)
                  and abs(d) < 45 and self._safe(x, y, a + 180)):
                # (a KILL leg's boss too, kept LAUNCH_R off: out of his claw, in the launcher's range)
                kd.add("back")                       # a demon: back away shooting (it is faster, but the gap buys shots)
            elif self.LOW_BACK and low and foe[0] < 260 and abs(d) < 45 and self._safe(x, y, a + 180):
                kd.add("back")                       # hurt: open the distance -- a hitscanner's spread is an angle
            elif wp == "shotgun" and foe[0] > 260 and hp > 35 and abs(d) < 20 and typ not in self.HITSCAN:
                kd.add("forward")                    # the pellets spread: close in on a far foe (not a hitscanner)
            g = f + 7 * self.seed_at(f)              # the seed shifts the dodge's rhythm (another real play)
            if "forward" not in kd and (foe[0] > 120 or (self.CLOSE_STRAFE and wp != "melee")):
                # CIRCLE-STRAFE while fighting (close in too, unless the fist / saw needs the contact): a fireball
                # aimed at where the player was misses a player moving across it; the side flips every 16 frames (the
                # seed shifts when)
                side = "strafe_left" if (g // 16) % 2 else "strafe_right"
                if not self._safe(x, y, a + (90 if side == "strafe_left" else -90)):
                    side = "strafe_right" if side == "strafe_left" else "strafe_left"
                if self._safe(x, y, a + (90 if side == "strafe_left" else -90)):
                    kd.add(side)
            self.last_pose = None
            return kd
        # no foe to face: still shoot what the aim window holds of the hunters (passing by, or a monster passed by)
        win = c.get("aim_sid") or ()
        hunters = {1 + m for m in range(len(self.rt or ())) if c["mon_target"][m] == 1
                   and signed(c["mon_health"][m]) > 0 and not (self.SAVE_R and self.ign.get(m, -1) > f)}
        # (SAVE_R: not at a monster given up on -- shot at with no damage -- in passing either)
        middle = range(max(0, len(win) // 2 - 3), min(len(win), len(win) // 2 + 4))
        if any(win[k] in hunters for k in middle) and not self.fired and not c.get("wp_rf"):
            self.opportune = "fire"
        else:
            self.opportune = None
        self.fired = False
        if self.leg.get("replan"):
            self.leg.pop("replan")
            self.replan(x, y, "back on the route", f)
        # ---- the use tap in progress (press, release, press ...)
        if self.use_tap:
            self.use_tap -= 1
            if self.use_tap % 2 == 1:
                kd.add("use")
            return kd
        piece = self.pieces[self.pi] if self.pieces else []
        # a teleport moved us onto the next piece
        if self.pi + 1 < len(self.pieces) and self.pieces[self.pi + 1] and \
                math.hypot(self.pieces[self.pi + 1][0][0] - x, self.pieces[self.pi + 1][0][1] - y) < 40:
            self.pi += 1
            self.wi = 0
            piece = self.pieces[self.pi]
            self.log("    f%d: teleported to (%d, %d)" % (f, x, y))
        last_piece = self.pi == len(self.pieces) - 1
        # progress along the piece
        hi = min(len(piece), self.wi + 10)
        if piece:
            j = min(range(self.wi, hi), key=lambda i: math.hypot(piece[i][0] - x, piece[i][1] - y))
            self.wi = max(self.wi, j)
        goal = tuple(self.leg["goal"])
        end = piece[-1] if piece else goal
        # ---- the leg's end
        action = self.leg["action"]
        if action == "kill" and (f >= self.hunt_f or (last_piece and self.wi >= len(piece) - 3)):
            if self._hunt(f, c, x, y):               # M8 C8: after the bosses, wherever they are now
                piece = self.pieces[self.pi] if self.pieces else []
                last_piece = self.pi == len(self.pieces) - 1
                end = piece[-1] if piece else goal
        if last_piece and self.wi >= len(piece) - 3:
            self.why = "end %s" % self.leg["action"]
            tx, ty = end
            if action == "touch":
                # combat's touch: the boxes overlap (20 + 16, strict) -- walk AT the key: a key on a ledge is taken
                # from below, the player sliding along the ledge's face (E1M2's red card)
                kx, ky = self.leg.get("key_at") or goal
                if abs(kx - x) < 35 and abs(ky - y) < 35:
                    return self._next(f, "in its touch box (bonus count %s)" % c.get("p_bc"))
                tx, ty = kx, ky
                self.final += 1
                if self.final > 20 and math.hypot(kx - x, ky - y) < 90 and not self.queue:
                    # the 16-unit step overshoots the box against the ledge: a short key sequence found by the
                    # model's own step (a beam over step_sim on the static scene) lands in it
                    self.final = 0
                    acc = lambda sx, sy: abs(kx - sx) < 35 and abs(ky - sy) < 35            # noqa: E731
                    acc.goal = (kx, ky)
                    self.queue = self._precise(c, acc)
                    self.log("    f%d: a precise approach to (%d, %d): %s" % (
                        f, kx, ky, " ".join(keys_str(q) for q in self.queue) if self.queue else "NONE FOUND"))
            dist = math.hypot(tx - x, ty - y)
            if action == "use":
                box = self.leg.get("box")
                inside = (box[0] + 2 <= x <= box[2] - 2 and box[1] + 2 <= y <= box[3] - 2) if box else dist < 12
                if inside:
                    sig = self._effect(c)
                    if self.sig0 is None:
                        self.sig0 = sig
                    elif sig != self.sig0:
                        return self._next(f, "used: its effect seen")
                    if self.act >= 10:
                        return self._next(f, "used: NO effect seen after 5 presses")
                    self.act += 2
                    self.use_tap = 1                 # press now, release next frame: the press edge
                    kd.add("use")
                    return kd
            if action == "cross" and dist < 10:
                return self._next(f, "reached")
            if dist < self.end_best - 4:
                self.end_best, self.end_f = dist, f
            elif f - self.end_f > 60:
                self.end_best, self.end_f = 1e9, f
                self.replan(x, y, "no progress to the leg's end in 60 frames", f)
                return kd
            want = math.degrees(math.atan2(ty - y, tx - x)) % 360
            d = self._turn_to(want, a, kd, tight=3 if dist < 40 else 6)
            if abs(d) < (25 if dist > 32 else 12):
                kd.add("forward")
            self._stuck(f, x, y, kd)
            return kd
        tgt = piece[min(self.wi + self.LOOK, len(piece) - 1)] if piece else end
        ahead = piece[self.wi + 1:self.wi + 7]
        door = self._door_ahead(c, x, y, ahead)
        if door is not None:
            si, boxes = door
            self.why = "door %d" % si
            if any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for box in boxes):
                k = self.dorder.index(si)
                if c["dstate"][k] == 0 or self.leg_frames % 8 == 0:
                    self.use_tap = 1                 # a press (held use opens a door; a tap does too)
                    kd.add("use")
                self.last_pose = None
                return kd
        lift = self._lift_ahead(c, x, y, ahead)
        if lift is not None:
            self.lift_wait += 1
        if lift is not None and self.lift_wait > 150:      # a lift that never comes: another way, in the flood's world
            self.lift_wait = 0
            self.replan(x, y, "the lift ahead never came down", f)
            return kd
        if lift is not None:
            k, sec = lift
            self.last_pose = None
            boxes = [box for tag, box in self.lv.mp.use if sec in self.lv.mp.lifts_of_tag[tag]]
            inside = any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for box in boxes)
            if c["lstate"][k] == 0 and inside and self.leg_frames % 30 == 0:
                self.use_tap = 1
                kd.add("use")
            if c["lstate"][k] == 0 and not inside and self.lift_wait > 10 and self._call_lift(f, x, y, sec, boxes):
                return kd                            # a lift at rest that this spot cannot call: walk to its switch
            self.why = "lift %d wait" % sec
            return kd                                # wait for the lift to come down
        here = self.pl.sector_of(self.LR.cell_of(x, y))
        if here in self.lorder and self.ride < 90:
            # ON A LIFT: ride while the path's next floor off the lift is too high to step up to from the lift's floor
            # now (a lower one is a drop: walk off)
            k = self.lorder.index(here)
            stops = self.lv.mp.stops[here]
            lift_floor = stops[min(c["lstate"][k], len(stops) - 1)]
            off = next((q for q in ahead if self.pl.sector_of(self.LR.cell_of(*q)) != here), None)
            # the way off under a ceiling the lift's floor now meets (E1M9's lift 109 at its top: sector 227's ceiling
            # 40 = the lift's floor -- a wall until the lift is down): at rest, call it down from its own SR lines
            # the way off, read from ITS OWN sector when that does not move (the planner's cell test spans the player's
            # radius, so beside the lift it reads the lift's own floor at the scene's state: E1M9's lift 109 at its
            # bottom read 40 off its south edge, a 160 step up, and the player rode it up and down for 2,000 frames)
            osec = self.pl.sector_of(self.LR.cell_of(*off)) if off is not None else None
            if osec is not None and osec not in self.lorder:
                off_floor, off_ceil = self.lv.secs[osec].floor_h, self.lv.secs[osec].ceil_h
            elif off is not None:
                _ok, off_floor, off_ceil = self.pl.cp(self.pl.scenes_for(self.active - {"lift:%d" % here})[0],
                                                      self.LR.cell_of(*off))
            # the way off under a ceiling the lift's floor now meets (E1M9's lift 109 at its top: sector 227's ceiling
            # 40 = the lift's floor -- a wall until the lift is down): at rest, call it down from its own SR lines
            low = off is not None and off_ceil - lift_floor < 56
            if low and c["lstate"][k] == 0:
                boxes = [box for tag, box in self.lv.mp.use if here in self.lv.mp.lifts_of_tag[tag]]
                if self._call_lift(f, x, y, here, boxes):
                    return kd
            if off is not None and (low or off_floor - lift_floor > 24):
                self.ride += 1
                self.last_pose = None
                self.why = "ride (lift at %d)" % lift_floor
                return kd
        if here not in self.lorder:
            self.ride = 0
        want = math.degrees(math.atan2(tgt[1] - y, tgt[0] - x)) % 360
        if self.race is not None and f < self.race[1] and here != self.race[0] and \
                abs((want - a + 540) % 360 - 180) > 90:
            # racing a called lift: the target is behind -- back-pedal to it (no time to turn round)
            d = self._turn_to((want + 180) % 360, a, kd, tight=6)
            if abs(d) < 35:
                kd.add("back")
            self.why = "race"
            self._stuck(f, x, y, kd)
            return kd
        d = self._turn_to(want, a, kd, tight=6)
        if abs(d) < 35:
            kd.add("forward")
        self._stuck(f, x, y, kd)
        prog = (self.pi, self.wi)
        if prog > self.best_prog:
            self.best_prog, self.best_f = prog, f
        elif f - self.best_f > 50:                   # no progress along the path (knocked about, or blocked)
            self.best_f = f
            self.stuck = 0
            self.replan(x, y, "no progress in 50 frames", f)
        elif f - self.best_f > 25:
            kd.discard("forward")
            kd.add("back" if (f // 8) % 2 else "strafe_left" if (f // 16) % 2 else "strafe_right")
        if self.stuck > 40:
            self.stuck = 0
            self.replan(x, y, "stuck", f)
        return kd

    # ---- M8 C8: the KILL leg (level_route's boss mechanism: every boss the skill spawns must die) ------------------
    HUNT_EVERY = 40            # frames between re-plans toward the nearest live boss
    BACK_R = 200               # a demon (and on a KILL leg a boss) this near is backed away from while shooting

    def _boss_slots(self):
        return {b[0] for b in self.leg.get("bosses", ())} if self.leg else set()

    def _bosses_alive(self, c) -> list:
        """[(slot, x, y)] of the kill leg's bosses alive now (their runtime positions)"""
        out = []
        for b in self.leg.get("bosses", ()):
            m = b[0]
            if c["mon_active"][m] and hp12(c["mon_health"][m]) > 0:
                if self.rt is not None and "thpos_rt" in c:
                    v = c["thpos_rt"][self.rt[m]]
                    out.append((m, signed(v & M32) / 65536.0, signed((v >> 32) & M32) / 65536.0))
                else:
                    out.append((m, b[1], b[2]))
        return out

    def _hunt(self, f, c, x, y) -> bool:
        """the kill leg's path re-planned to the nearest live boss's place now, every HUNT_EVERY frames (or when the
        path is used up) -> True when the path was replaced"""
        self.hunt_f = f + self.HUNT_EVERY
        alive = self._bosses_alive(c)
        if not alive:
            return False
        _m, bx, by = min(alive, key=lambda b: math.hypot(b[1] - x, b[2] - y))
        LR = self.LR
        path = self.pl.leg_path(LR.cell_of(x, y), lambda q: max(abs(LR.centre(q)[0] - bx),
                                                                 abs(LR.centre(q)[1] - by)) <= 48,
                                self.active | self._openable())
        if not path or len(path) < 2:
            self.why = "hunt: wait"
            return False
        self.leg["path"] = [list(LR.centre(q)) if q[0] != "teleport" else ["teleport", q[1]] for q in path]
        self._leg_pieces()
        self.why = "hunt"
        return True

    def _live_drops(self, c) -> list:
        """the dropped clips lying now (`mdrop` 1; their drop rows, the last of `thpos_rt`, hold where): [(x, y)]"""
        md = c.get("mdrop")
        rows = c.get("thpos_rt")
        if not md or not rows or len(md) != len(self.droppers):
            return []
        base = len(rows) - len(self.droppers)
        out = []
        for k, live in enumerate(md):
            if live == 1 and self.drop_kind[k] == 2007:
                v = rows[base + k]
                out.append((signed(v & M32) / 65536.0, signed((v >> 32) & M32) / 65536.0))
        return [(int(px), int(py)) for px, py in out if (int(px), int(py)) not in self.health_taken]

    def _barrel_near(self, c) -> bool:
        """a live barrel in the last picture's aim window within BARREL_SAFE (Chebyshev) of the player: a shot that
        bursts it (A_Explode, 128 at the blast's centre) hurts him -- E1M3 seed 0 died by the barrel at (780, 2448)"""
        win = c.get("aim_sid") or ()
        if not win or not self.barrels:
            return False
        x, y, _a = pose_of(c)
        nmon = len(self.mtype)
        for sid in set(win):
            b = sid - 1 - nmon
            if 0 <= b < len(self.barrels) and max(abs(self.barrels[b][0] - x),
                                                   abs(self.barrels[b][1] - y)) < self.BARREL_SAFE:
                return True
        return False

    def _safe(self, x, y, ang, dist: int = 40) -> bool:
        """is a step `dist` units toward `ang` (degrees) SAFE to strafe / back into: no damaging floor, no drop of more
        than a step (a nukage pit, a ledge the route would have to climb back from), not a refused cell"""
        LR = self.LR
        here = LR.cell_of(x, y)
        to = LR.cell_of(x + dist * math.cos(math.radians(ang)), y + dist * math.sin(math.radians(ang)))
        if to == here:
            return True
        if self.pl.hurts(to) and not self.pl.hurts(here):
            return False
        sc = self.pl.scenes_for(self.active)
        ok, fz, _cz = self.pl.cp(sc[0], to)
        return bool(ok) and fz >= self.pl.cp(sc[0], here)[1] - 24

    def _call_lift(self, f, x, y, sec, boxes) -> bool:
        """a leg inserted before this one: to the nearest reachable cell inside one of the lift's use boxes (SR 62 /
        S1 lines, `movers.use_line_boxes`), and a use press there -- three times in any 600 frames at most"""
        recent = [g for g in self.called.get(sec, ()) if f - g < 600]
        if not boxes or len(recent) >= 3:
            return False
        self.called[sec] = recent + [f]
        LR = self.LR

        def inbox(cell):
            cx, cy = LR.centre(cell)
            return any(b[0] + 12 <= cx <= b[2] - 12 and b[1] + 12 <= cy <= b[3] - 12 for b in boxes)
        path = self.pl.leg_path(LR.cell_of(x, y), inbox, self.active | self._openable())
        if not path or len(path) > 120 or any(q[0] == "teleport" for q in path):
            self.log("    f%d: lift %d at rest and no use box reachable from here" % (f, sec))
            return False
        box = next(b for b in boxes if b[0] <= LR.centre(path[-1])[0] <= b[2] and b[1] <= LR.centre(path[-1])[1] <= b[3])
        self.leg["replan"] = True
        self.legs.insert(self.li, {"to": "lift:%d" % sec, "kind": "call", "action": "use", "box": list(box),
                                   "goal": list(LR.centre(path[-1])), "path": [list(LR.centre(q)) for q in path]})
        self._leg(self.li)
        self.log("    f%d: lift %d at rest -- a detour to its switch, %d cells" % (f, sec, len(path)))
        return True

    def _openable(self):
        return {"door:%d" % si for si in self.dorder if self.lv.dp.boxes.get(si) is not None
                and (not self.pl.mechs["door:%d" % si].key or self.pl.mechs["door:%d" % si].key in self.keys)}

    def _seek_health(self, f, x, y, items, what, most: int = 70, radius: int = 900, max_burn=None) -> bool:
        """a detour leg to the nearest reachable item of `items` not taken yet (planned in the world the legs made)"""
        if f < self.retry.get(what, 0):
            return False
        LR = self.LR
        cands = sorted((math.hypot(hx - x, hy - y), hx, hy) for hx, hy in items
                       if (hx, hy) not in self.health_taken and math.hypot(hx - x, hy - y) < radius
                       and not any(b[0] <= hx <= b[2] and b[1] <= hy <= b[3] for b in self.SEEK_AVOID))
        opn = {"door:%d" % si for si in self.dorder if self.lv.dp.boxes.get(si) is not None
               and (not self.pl.mechs["door:%d" % si].key or self.pl.mechs["door:%d" % si].key in self.keys)}
        if max_burn is None:
            max_burn = self.SEEK_MAX_BURN            # (every detour: E1M4's ammo detours crossed the channel BACK)
        def usable(path):
            return (path and not any(q[0] == "teleport" for q in path) and len(path) < most
                    and not any(self.pl.sector_of(q) in self.lorder for q in path)
                    and (max_burn is None or sum(1 for q in path if q[0] != "teleport" and self.pl.hurts(q)) <= max_burn))
        for _d, hx, hy in cands[:3]:
            path = self.pl.leg_path(LR.cell_of(x, y), lambda c, hx=hx, hy=hy: abs(LR.centre(c)[0] - hx) < 24
                                    and abs(LR.centre(c)[1] - hy) < 24, self.active | opn)
            if usable(path):
                return self._detour(f, what, hx, hy, path)
        if self.SEEK_FAR and what == "health" and most >= self.SEEK_FAR_MOST and len(cands) > 3:
            # VERY LOW, and the three nearest in a straight line have no way to them: the nearest BY PATH of the rest,
            # one flood to any of them (E1M4 near (274, -254): the three nearest -- the stimpack at (544, -1056), the
            # medikit at (-640, -192), the stimpack at (-864, 288) -- have no path from there; the stimpacks at
            # (1192, 632) are 181 cells off. The play sat at 1-17 health and died there)
            rest = [(hx, hy) for _d, hx, hy in cands[3:]]

            def near(c):
                cx, cy = LR.centre(c)
                return any(abs(cx - hx) < 24 and abs(cy - hy) < 24 for hx, hy in rest)
            path = self.pl.leg_path(LR.cell_of(x, y), near, self.active | opn)
            if usable(path):
                cx, cy = LR.centre(path[-1])
                hx, hy = next((hx, hy) for hx, hy in rest if abs(cx - hx) < 24 and abs(cy - hy) < 24)
                return self._detour(f, what, hx, hy, path, " (the nearest by path: SEEK_FAR)")
        self.retry[what] = f + 60
        return False

    def _detour(self, f, what, hx, hy, path, how: str = "") -> bool:
        """the detour leg to the item at (hx, hy) along `path`, inserted before the leg in progress"""
        LR = self.LR
        self.leg["replan"] = True
        self.legs.insert(self.li, {"to": what, "kind": "item", "action": "touch", "goal": [hx, hy],
                                   "key_at": [hx, hy], "path": [list(LR.centre(q)) for q in path]})
        self._leg(self.li)
        self.log("    f%d: %s low -- a detour to the item at (%d, %d), %d cells%s" % (f, what, hx, hy, len(path), how))
        return True

    def _precise(self, c, accept, depth: int = 14, width: int = 30) -> list:
        """a beam search over the model's own player step (ReferenceModel.step_sim, the game tier's strafe and turn
        tap) on the static scene of the world the legs made, from the binary's pose: the keys to a pose `accept`s"""
        from dataclasses import replace
        from doomfj.reference_model import SimState
        rm = self.lv.rm
        scene = self.pl.scenes_for(self.active)[0][1]
        st = replace(SimState(signed(c["viewx"]), signed(c["viewy"]), c["viewangle"] & M32, self.lv.map),
                     turnheld=int(self.last_turn))
        moves = [frozenset(m) for m in (("forward",), ("forward", "turn_left"), ("forward", "turn_right"),
                                        ("turn_left",), ("turn_right",), ("strafe_left",), ("strafe_right",),
                                        ("back",), ("forward", "strafe_left"), ("forward", "strafe_right"))]
        goal = getattr(accept, "goal", None)

        def h(s):
            x, y = signed(s.x) / 65536.0, signed(s.y) / 65536.0
            return math.hypot(goal[0] - x, goal[1] - y) if goal else 0
        beam = [(0, st, [])]
        for _ in range(depth):
            nxt = []
            for _h, s0, path in beam:
                for mv in moves:
                    ns = rm.step_sim(s0, {k: True for k in mv}, scene=scene, strafe=True, tap=True)
                    if accept(signed(ns.x) / 65536.0, signed(ns.y) / 65536.0):
                        return path + [mv]
                    nxt.append((h(ns), ns, path + [mv]))
            nxt.sort(key=lambda t: t[0])
            seen, beam = set(), []
            for hh, s1, path in nxt:
                k = (s1.x >> 18, s1.y >> 18, s1.angle >> 26, s1.turnheld)
                if k not in seen:
                    seen.add(k)
                    beam.append((hh, s1, path))
                    if len(beam) >= width:
                        break
        return []

    def seed_at(self, f) -> int:
        """the steering seed in force at frame f: `seed` an int, or a schedule [(from frame, seed), ...]"""
        if isinstance(self.seed, int):
            return self.seed
        cur = 0
        for f0, sd in self.seed:
            if f >= f0:
                cur = sd
        return cur

    def _effect(self, c):
        """the cells a use leg's press must move: its door / lift state, the floor switches, the level's end"""
        mid = self.leg["to"]
        if mid.startswith("door:"):
            return c["dstate"][self.dorder.index(int(mid[5:]))]
        if mid.startswith("lift:"):
            return c["lstate"][self.lorder.index(int(mid[5:]))]
        if mid.startswith("floor:"):
            return str(c.get("fswitch"))
        return (c.get("lvdone"), c.get("mode"))

    def _stuck(self, f, x, y, kd):
        if self.last_pose is not None and math.hypot(x - self.last_pose[0], y - self.last_pose[1]) < 1.0 \
                and "forward" in kd:
            self.stuck += 1
        else:
            self.stuck = max(0, self.stuck - 1)
        self.last_pose = (x, y)
        if self.stuck > 8:
            kd.add("strafe_left" if (self.stuck // 6) % 2 else "strafe_right")

    def _next(self, f, why):
        leg = self.leg
        self.log("  f%d: leg %d -> %s %s (%s) after %d frames" % (f, self.li, leg["to"], leg["action"], why,
                                                                 self.leg_frames))
        mid = leg["to"]
        if leg["kind"] == "item":
            self.health_taken.add(tuple(leg["goal"]))
        if mid.startswith("key:"):
            self.keys.add(mid[4:])
        elif mid != "exit":
            self.active.add(mid)
        self.events.append((f, self.li, leg["to"], why))
        if mid == "exit":
            self.done_frame = f
            self.leg = None
            return set()
        if leg["kind"] == "call":
            sec = int(mid[5:])
            bb = self.lv.sector_bbox(sec)
            gx, gy = leg["goal"]
            far = max(bb[0] - gx, gx - bb[2], bb[1] - gy, gy - bb[3], 0) if bb else 0
            if far > self.RACE_FAR:
                self.race = (sec, f + 60)
                self.log("    f%d: race back to lift %d (%d units from its switch)" % (f, sec, far))
        self._leg(self.li + 1)
        self.stuck = 0
        return set()


# ================================================================================================================
# the session CLI
# ================================================================================================================
def main(argv=None) -> int:
    from doomfj.mapprofile import take_map_arg
    take_map_arg(argv if argv is not None else None)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session")
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--fjm", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--skill", default=None, choices=("easy", "medium", "hard"))
    ap.add_argument("--check", action="store_true", help="the oracle beside the binary, every frame exact")
    ap.add_argument("--workers", type=int, default=0, help="--check: processes rendering the oracle's pictures")
    ap.add_argument("--every", type=int, default=2)
    ap.add_argument("--show", type=int, default=0)
    ap.add_argument("--max", type=int, default=600, help="an @goto / @route's frame budget")
    a = ap.parse_args(argv)
    ses = Path(a.session)
    ses.mkdir(parents=True, exist_ok=True)
    kf = ses / "keys.json"
    log = json.loads(kf.read_text()) if kf.exists() else {"skill": a.skill or "easy", "keys": []}
    if a.skill and a.skill != log["skill"]:
        raise SystemExit("the session plays %s; a new session for %s" % (log["skill"], a.skill))
    keys = [frozenset(LET[ch] for ch in s) for s in log["keys"]]
    old = len(keys)
    cmd = [t for t in a.keys if t.startswith("@")]
    if a.keys[:1] == ["undo"]:
        keys = keys[:-(int(a.keys[1]) if len(a.keys) > 1 else 1)]
        cmd = []
    else:
        assert len(cmd) <= 1 and (not cmd or a.keys[-1] == cmd[0]), "one @command, last"
        keys += expand([t for t in a.keys if not t.startswith("@")])
    pl = Player(a.fjm, a.labels, log["skill"], check=a.check)
    pl.workers = a.workers
    steer = None
    if cmd:
        import level_route as LR
        if cmd[0] == "@route":
            route = LR.plan(pl.mapname, log["skill"])
        else:
            gx, gy = (int(v) for v in cmd[0].split(":")[1].split(","))
            route = {"map": pl.mapname, "skill": log["skill"], "legs": [
                {"to": "goto", "kind": "goto", "action": "cross", "goal": [gx, gy], "path": [[gx, gy]]}]}
        steer = Steer(route, log=print)
        steer.rt = pl.monster_rows()
    recs = []

    def on_frame(rec):
        recs.append({"f": rec["f"], "cells": rec["cells"], "keys": rec["keys"]})
        if a.show or rec["f"] >= pl.mf + old:
            recs[-1]["pic"], recs[-1]["pal"] = rec["pic"], rec["pal"]
        if steer is not None and steer.done_frame is not None:
            return "stop"
        return None
    r = pl.run(keys, pl.mf + 1 + len(keys) + (a.max if steer else 0), decide=steer.decide if steer else None,
               on_frame=on_frame)
    log["keys"] = ["".join(NAME_LET[n] for n in sorted(k)) for k in r["keys"]]
    kf.write_text(json.dumps(log))
    print("ran %d frames in %.0f s (binary %.0f s, oracle %.0f s), %s ops -- %s%s" % (
        r["frames"], r["seconds"], r["t_binary"], r["t_oracle"], format(r["ops"], ","), r["verdict"],
        "" if not r["mismatch"] else " " + json.dumps(r["mismatch"])))
    write_session(ses, pl, recs, r, old, a)
    return 0 if r["verdict"] != "mismatch" else 1


def write_session(ses, pl, recs, r, old, a):
    """state.txt, the sheet of the newest frames, the automap around the player"""
    from PIL import Image, ImageDraw
    from doomfj.config import Config
    lines = []
    for rec in recs:
        c = rec["cells"]
        x, y, ang = pose_of(c)
        lines.append("f%-5d w%-5d %-5s (%6d,%6d) a%3d hp %s ar %s dead %s mode %s" % (
            rec["f"], rec["f"] - pl.mf, keys_str(rec["keys"]), x, y, round(ang), c.get("p_hp"), c.get("p_ar"),
            c.get("p_dead"), c.get("mode")))
    (ses / "state.txt").write_text("\n".join(lines) + "\n")
    W, H = Config().W, Config().H
    shown = [rec for rec in recs if "pic" in rec]
    if a.show:
        shown = shown[-a.show:]
    shown = shown[::max(1, a.every)][-36:]
    if shown:
        S, cols = 3, min(6, len(shown))
        rows = (len(shown) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * W * S, rows * (H * S + 14)), (40, 0, 40))
        dr = ImageDraw.Draw(sheet)
        pals = {}
        for n, rec in enumerate(shown):
            im = Image.frombytes("P", (W, H), bytes(rec["pic"]))
            if rec["pal"] not in pals:
                pals[rec["pal"]] = next((list(b for rgb in pl.orc.art.playpal(k) for b in rgb) for k in range(14)
                                         if pl.orc.palette_sha(k) == rec["pal"]),
                                        list(b for rgb in pl.orc.art.playpal(0) for b in rgb))
            im.putpalette(pals[rec["pal"]])
            x0, y0 = (n % cols) * W * S, (n // cols) * (H * S + 14)
            sheet.paste(im.convert("RGB").resize((W * S, H * S), Image.NEAREST), (x0, y0 + 14))
            x, y, _a = pose_of(rec["cells"])
            dr.text((x0 + 3, y0 + 1), "f%d %s (%d,%d) hp%s" % (rec["f"], keys_str(rec["keys"]), x, y,
                                                              rec["cells"].get("p_hp")), fill=(255, 255, 0))
        sheet.save(ses / ("sheet_%d.png" % len(r["keys"])))
    mw, m = pl.orc.mw, pl.mapname
    V, L = mw.vertexes(m), mw.linedefs(m)
    trail = [pose_of(rec["cells"])[:2] for rec in recs if rec["f"] >= pl.mf]
    if not trail:
        return
    px, py = trail[-1]
    R, Z = 1024, 900
    mp = Image.new("RGB", (Z, Z), (0, 0, 0))
    md = ImageDraw.Draw(mp)

    def to(x, y):
        return ((x - px + R) * Z / (2 * R), (py - y + R) * Z / (2 * R))
    for ld in L:
        a1, a2 = V[ld.v1], V[ld.v2]
        two = ld.back not in (-1, 0xFFFF)
        col = (255, 200, 0) if ld.special else (90, 90, 90) if two else (220, 220, 220)
        md.line([to(a1.x, a1.y), to(a2.x, a2.y)], fill=col, width=1 if two else 2)
    if len(trail) > 1:
        md.line([to(*q) for q in trail[-800:]], fill=(255, 0, 255), width=1)
    cx, cy = to(px, py)
    md.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=(255, 255, 0))
    mp.save(ses / ("map_%d.png" % len(r["keys"])))
    print("\n".join(lines[-4:]))


if __name__ == "__main__":
    sys.exit(main())
