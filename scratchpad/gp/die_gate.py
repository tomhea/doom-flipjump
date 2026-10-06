"""die_gate.py -- M7 P7's gate: the dead player, the restart, NEW GAME after death (docs/gp-p67-interface.md 6.2).

    python scratchpad/gp/die_gate.py --fjm build/<new>.fjm --labels <its label table>
    python scratchpad/gp/die_gate.py --oracle-only [--only D4]    # the scenarios, their counters and controls

fight_gate's machinery (p2a_gate.Mirror in the game tier's "full" modes; frame-0 and LATE pokes; menu keys as key
events; STATE-, PIXEL- AND PALETTE-EXACT ON EVERY FRAME), with the opposite rule on deaths: EVERY SCENARIO MUST
REACH A DEATH (deaths >= 1 in its run), and a scenario that does not die FAILS. A death is either the game's own (a
zombieman's hitscan, nukage, a barrel's blast) or a LATE setup that runs the model's `damage_player` at a frame's
start -- the death moment (P5's: p_dead, the weapon's downstate, one rng_pl draw) poked into the binary as the cells
it moved -- where the scenario is about what follows the death, not the death.

THE SCENARIOS:
  D1  a zombieman kills the player (p_hp poked 6); then forward, a turn, fire and the number keys are held: the
      position stays and the angle is the turn to the killer's alone, the weapon stays down, wp_pend does not move,
      the red fades
  D2  killed standing in door 10 as it closes: the door does NOT go back up on the dead player
  D3d dead in front of a door, use pressed: no door press -- the RESTART next frame
  D3x dead in the exit's box, use pressed: no level end -- the restart
  D4  the restart: a pickup taken and a baked barrel gone (poked), dead, use held: the next frame is the level start
  D4m the restart puts a lying drop back (a zombieman shot first)
  D4s NEW GAME medium, dead, use: the restart is MEDIUM's level start
  D5  NEW GAME after death: esc, NEW GAME, easy -- easy's level start (its berserk and backpack present)
  D6  death by nukage (p_hp 5 in sector 23): the nukage tic still runs the weapon keys and the move (the latch)
  D7  death by a barrel's blast (p_hp 10 beside a barrel shot)
  D8  death during the gold flash: the bonus count frozen while dead, the gold palette after the red fades

THE CONTROLS (R9, each must part on its scenario): `dead_walks` / `dead_turns` (a dead player moves / turns),
`dead_keys` (a dead player's number keys are read), `dead_holds_door` (a closing door reverses on the dead player),
`dead_uses` (a dead player's use presses a door), `dead_exits` (... a use line: the exit), `restart_pickup` /
`restart_barrel` / `restart_mdrop` (the restart keeps `pickup_taken` / the barrels / `mon_drop`), `use_edge` (the death
think wants a use PRESS, not a held use), `restart_skill` (the restart is hard's), `ng_skill` (NEW GAME starts hard),
`latch` (the dead branch re-read after nukage), `dead_bonus_fade` (the bonus count fades while dead).
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fight_gate as FG                                                      # noqa: E402
import p2a_gate as G                                                         # noqa: E402
from doomfj import gamedata as gd                                            # noqa: E402

I, F, B, FIRE, U = FG.I, FG.F, FG.B, FG.FIRE, {"use": True}
# the controls that are the Mirror's own (its frame order), not a patched model rule
MIRROR_CTLS = ("dead_holds_door", "dead_uses", "dead_exits", "latch")


@contextlib.contextmanager
def control(name: str | None):
    """the oracle with rule `name` broken (None: the oracle); fight_gate's controls pass through"""
    from doomfj import combat as C
    from doomfj import monsters as MS
    CM = C.CombatMixin
    saved = []

    def patch(obj, attr, val):
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)
    if name == "dead_walks":                     # a dead player moves (and turns)
        orig = MS.MonsterPhase.move

        def move(self, keys, x16, y16, angle, dead=None, scene=None):
            if dead:
                self.world.ws.p_dead, was = 0, self.world.ws.p_dead
                try:
                    return orig(self, keys, x16, y16, angle, dead=0, scene=scene)
                finally:
                    self.world.ws.p_dead = was
            return orig(self, keys, x16, y16, angle, dead=dead, scene=scene)
        patch(MS.MonsterPhase, "move", move)
    elif name == "dead_turns":                   # a dead player turns (and does not move)
        orig = MS.MonsterPhase.move

        def move(self, keys, x16, y16, angle, dead=None, scene=None):
            out = orig(self, keys, x16, y16, angle, dead=dead, scene=scene)
            if dead:
                from doomfj.reference_model import ANGLE_TURN
                a = out[2] + (ANGLE_TURN if keys.get("turn_left") else 0) - (ANGLE_TURN if keys.get("turn_right") else 0)
                return out[0], out[1], a & 0xFFFFFFFF
            return out
        patch(MS.MonsterPhase, "move", move)
    elif name == "dead_keys":                    # a dead player's number keys are read
        orig_dt = CM._death_think

        def dt(self, keys, ev):
            self._weapon_keys(keys)
            orig_dt(self, keys, ev)
        patch(CM, "_death_think", dt)
    elif name in ("restart_pickup", "restart_barrel", "restart_mdrop"):   # the restart keeps one array
        keep = {"restart_pickup": ("pickup_taken",), "restart_barrel": ("bar_state", "bar_tics", "bar_solid"),
                "restart_mdrop": ("mon_drop",)}[name]
        orig_rs = CM._restart

        def rs(self, ev):
            old = {f: list(getattr(self.ws, f)) for f in keep}
            orig_rs(self, ev)
            for f, vals in old.items():
                arr = getattr(self.ws, f)
                for i, v in enumerate(vals):
                    arr[i] = v
        patch(CM, "_restart", rs)
    elif name == "use_edge":                     # the death think asks for a use PRESS (DOOM reads it held)
        orig_dt = CM._death_think

        def dt(self, keys, ev):
            held = self.ws.p_usedown
            self.ws.p_usedown = int(bool(keys["use"]))
            orig_dt(self, dict(keys, use=bool(keys["use"] and not held)), ev)
        patch(CM, "_death_think", dt)
    elif name == "restart_skill":                # the restart is hard's, whatever the skill
        orig_rs = CM._restart

        def rs(self, ev):
            sk = self.ws.skill
            self.ws.skill = gd.SK_HARD
            orig_rs(self, ev)
            self.ws.skill = sk
        patch(CM, "_restart", rs)
    elif name == "ng_skill":                     # NEW GAME starts hard, whatever was picked
        orig_reset = MS.MonsterPhase.reset

        def reset(self, skill):
            orig_reset(self, gd.SK_HARD)
        patch(MS.MonsterPhase, "reset", reset)
    elif name == "dead_bonus_fade":              # the bonus count fades while dead
        orig_dt = CM._death_think

        def dt(self, keys, ev):
            orig_dt(self, keys, ev)
            if self.ws.p_bonuscount:
                self.ws.p_bonuscount -= 1
        patch(CM, "_death_think", dt)
    else:
        with FG.control(name):
            yield
        return
    try:
        yield
    finally:
        for obj, attr, val in reversed(saved):
            setattr(obj, attr, val)


class Run(FG.Run):
    controls = staticmethod(control)

    def __call__(self, pose, keys, setup, ctl=None, late=None):
        mctl = ctl if ctl in MIRROR_CTLS else None
        with self.controls(None if mctl else ctl):
            mr = self.mirror(setup, late)
            mr.ctl = mctl
            tr = mr.run(pose, keys, 0)
        return tr, mr


# ---- setups
def kill(dmg_over: int = 20, armor_off: bool = True):
    """a LATE setup: the model's damage_player takes the player `dmg_over` below 0 (armor dropped first) -- the death
    moment, its cells poked"""
    def fn(mph, ev):
        ws = mph.world.ws
        if armor_off:
            ws.p_armor = ws.p_armortype = 0
        mph.world.damage_player(ws.p_health + dmg_over, ("gate", 0), ev)
    return fn


def first_death(tr):
    """the first frame whose state is dead, or None"""
    return next((f for f, fr in enumerate(tr) if fr["mstate"].get("p_dead")), None)


def after_death_frozen(tr) -> bool:
    d = first_death(tr)
    if d is None:
        return False
    rest = tr[d:]
    # M7 P7: the POSITION stays; the angle is the death think's -- it turns to the killer from the first dead tic
    # (d + 1) and, the killer standing, settles there: no key turns it (die_gate D1 on blocked51 found the gates'
    # MonsterPhase.move dropping that turn, and this claim holding the whole pose frozen, which only a killer at
    # exactly the facing angle satisfies)
    return (len({fr["pose"][:2] for fr in rest}) == 1 and len({fr["pose"][2] for fr in rest[1:]}) == 1
            and len({fr["mstate"]["wp_pend"] for fr in rest}) == 1
            and rest[-1]["mstate"]["wp_sy"] == gd.WEAPONBOTTOM >> 16
            and rest[-1]["mstate"]["p_dc"] < max(fr["mstate"]["p_dc"] for fr in rest))


def scenario_list(dsim, w, card) -> list:
    out = []
    # ---- D1: killed by a zombieman's hitscan, then every key held
    zomb = FG.first_live(w, "MT_POSSESSED")
    all_keys = {"forward": True, "turn_left": True, "fire": True, "w1": True, "w2": True, "w3": True, "w4": True}
    keys1 = [I] * 36 + [all_keys] * 16
    d1 = [(p, FG.both(FG.poke_hp(6), (lambda mph, m=m: _attack(mph, m))))
          for m in zomb for p in FG.poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (128, 96, 160))]
    out.append({"name": "D1 killed by a zombieman; every key held after: nothing moves", "keys": keys1,
                "controls": ["dead_walks", "dead_turns", "dead_keys"], "cands": d1,
                "claim": lambda c, tr: c["deaths"] >= 1 and first_death(tr) is not None and first_death(tr) < 36
                and after_death_frozen(tr)})
    # ---- D2: killed in door 10 as it closes (p2a S13's walk-in), the door closes on the corpse
    p10 = dsim.passes[10]
    keys2 = [U] * 2 + [I] * 8 + [F] * 3 + [I] * 70
    out.append({"name": "D2 killed in door 10 as it closes: it does not go back up", "keys": keys2,
                "controls": ["dead_holds_door"],
                "cands": [(G.door_front(dsim, 10), None, {13: kill()})],
                "claim": lambda c, tr: c["deaths"] >= 1 and tr[-1]["phase"][0][10][0] < p10
                and not any(a["phase"][0][10][1] == 2 and b["phase"][0][10][1] == 1 for a, b in zip(tr[13:], tr[14:]))})
    # ---- D3: dead, then use -- at a door, in the exit's box
    keys3 = [I] * 3 + [U] + [I] * 3
    out.append({"name": "D3d dead before door 10, use: no press, the restart", "keys": keys3,
                "controls": ["dead_uses"], "cands": [(G.door_front(dsim, 10), None, {0: kill()})],
                "claim": lambda c, tr: c["deaths"] >= 1 and c["restarts"] >= 1
                and all(fr["phase"][0][10][0] == 0 for fr in tr)})
    out.append({"name": "D3x dead in the exit's box, use: no level end, the restart", "keys": keys3,
                "controls": ["dead_exits"], "cands": [(G.exit_pose(dsim), None, {0: kill()})],
                "claim": lambda c, tr: c["deaths"] >= 1 and c["restarts"] >= 1 and not any(fr["lvdone"] for fr in tr)})
    # ---- D4: the restart -- a pickup taken and a baked barrel gone (poked), dead, use held
    pk = [i for i, t in enumerate(w.pickup_things) if t.type == 2014 and t.flags & gd.skill_bit(gd.SK_HARD)]

    def messy(mph, ev):
        ws = mph.world.ws
        ws.pickup_taken[_baked_pickup(mph, pk)] = 1
        b = _baked_barrel(mph)
        ws.bar_state[b] = ws.bar_tics[b] = ws.bar_solid[b] = 0
        kill()(mph, ev)
    keys4 = [U] * 4 + [I] * 3
    out.append({"name": "D4 the restart: the level start, a taken pickup and a gone barrel back", "keys": keys4,
                "controls": ["restart_pickup", "restart_barrel", "use_edge"],
                "cands": [((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle), None, {0: messy})],
                "claim": lambda c, tr: c["deaths"] >= 1 and c["restarts"] == 1 and _level_start_after(tr, w)})
    # ---- D4m: a drop lies; dead; use: the restart takes it back
    keys4m = [I] * 14 + [FIRE] * 2 + [I] * 8 + [U] * 3 + [I] * 3
    d4m = [(p, FG.mon_health(m, 1), {24: kill()}) for m in zomb
           for p in FG.poses_facing(dsim, w, w.ws.mon_x[m], w.ws.mon_y[m], (96, 112))]
    out.append({"name": "D4m the restart takes a lying drop back", "keys": keys4m, "controls": ["restart_mdrop"],
                "cands": d4m,
                "claim": lambda c, tr: c["deaths"] >= 1 and c["restarts"] == 1 and c["drop_frames"] >= 1
                and not tr[-1]["mstate"]["dr_live"]})
    # ---- D4s: NEW GAME medium, dead, use: medium's level start
    menu_med = [{"menu": ["esc"]}, {"menu": ["enter"]}, {"menu": ["up"]}, {"menu": ["enter"]}]
    out.append({"name": "D4s NEW GAME medium, dead, use: the restart is medium's", "keys": menu_med + [I, U, I, I],
                "controls": ["restart_skill"],
                "cands": [((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle), None, {4: kill()})],
                "claim": lambda c, tr: c["deaths"] >= 1 and c["restarts"] == 1
                and tr[-1]["mstate"]["g_skill"] == 1})
    # ---- D5: NEW GAME after death: easy
    menu_easy = [{"menu": ["esc"]}, {"menu": ["enter"]}, {"menu": ["up"]}, {"menu": ["up"]}, {"menu": ["enter"]}]
    out.append({"name": "D5 NEW GAME after death: easy's level start", "keys": [I] * 2 + menu_easy + [I] * 3,
                "controls": ["ng_skill"],
                "cands": [((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle), None, {0: kill()})],
                "claim": lambda c, tr: c["deaths"] >= 1 and tr[-1]["mstate"]["g_skill"] == 0
                and not tr[-1]["mstate"]["p_dead"]})
    # ---- D6: death by nukage, the latch
    keys6 = [{"forward": True, "w1": True}] + [I] * 6
    d6 = [(p, FG.poke_hp(5)) for p in FG.poses_in_sector(dsim, w, 23, step=32, ledge=False)[:12]]
    out.append({"name": "D6 death by nukage: that tic still runs the keys and the move", "keys": keys6,
                "controls": ["latch"], "cands": d6,
                "claim": lambda c, tr: c["deaths"] >= 1 and c["nukage"] >= 1 and first_death(tr) == 0
                and tr[0]["pose"][:2] != tr[0]["start"][:2] and tr[0]["mstate"]["wp_pend"] == gd.WP_FIST})
    # ---- D7: death by a barrel's blast
    keys7 = [I] * 14 + [FIRE] * 2 + [I] * 24          # S_BEXP .. S_BEXP4: ~15 tics from the shot to the blast
    d7 = [(p, FG.both(FG.poke_hp(10), FG.bar_health(b, 1))) for b, t in enumerate(w.barrel_things)
          for p in FG.poses_facing(dsim, w, t.x, t.y, (48, 56, 64))]
    out.append({"name": "D7 death by a barrel's blast", "keys": keys7, "controls": [], "cands": d7,
                "claim": lambda c, tr: c["deaths"] >= 1 and c["barrel_hurt"] >= 1})
    # ---- D8: death during the gold flash
    def gold_kill(mph, ev):
        ws = mph.world.ws
        ws.p_bonuscount = 200
        ws.p_health = 1
        kill(dmg_over=3)(mph, ev)
    out.append({"name": "D8 death during the gold flash: the bonus frozen, gold after the red", "keys": [I] * 12,
                "controls": ["dead_bonus_fade"],
                "cands": [((dsim.spawn.x, dsim.spawn.y, dsim.spawn.angle), None, {0: gold_kill})],
                "claim": lambda c, tr: c["deaths"] >= 1 and c["bonus_frames"] >= 1
                and len({fr["mstate"]["p_bc"] for fr in tr}) == 1})
    return out


def _attack(mph, m):
    """zombieman m awake, attacking, its target the player (hurt_gate's poke)"""
    import hurt_gate as H
    H.attack(mph, m, "S_POSS_ATK1")


def _baked_pickup(mph, candidates) -> int:
    """the first of `candidates` (pickup indices) whose thing is BAKED with a thvis slot (a poke can hide it)"""
    mv = FG.P.Oracle()._mv(mph.world) if not hasattr(_baked_pickup, "mv") else _baked_pickup.mv
    _baked_pickup.mv = mv
    return next(i for i in candidates if mv.pdi[i] in mv.vis_slots)


def _baked_barrel(mph) -> int:
    mv = _baked_pickup.mv if hasattr(_baked_pickup, "mv") else FG.P.Oracle()._mv(mph.world)
    _baked_pickup.mv = mv
    return next(b for b in range(mph.world.layout.nbarrel) if mv.bdi[b] in mv.vis_slots)


def _level_start_after(tr, w) -> bool:
    """the restart's frame: the player at the spawn, full health, alive, no flash, every barrel standing"""
    f = next((k for k, fr in enumerate(tr) if fr["ev"][1] is not None and fr["ev"][1].restarts), None)
    if f is None:
        return False
    st = tr[f]["mstate"]
    return (st["p_hp"] == 100 and not st["p_dead"] and st["p_bc"] == 0 and all(st["bar_st"])
            and tr[f]["pose"][:2] == (w.ws.px & 0xFFFFFFFF, w.ws.py & 0xFFFFFFFF)[:2] or
            (st["p_hp"] == 100 and not st["p_dead"] and all(st["bar_st"])
             and FG._signed(tr[f]["pose"][0], 32) == FG._signed(w.ws.px, 32)))


NEED = ("deaths", "restarts", "restart_requests", "nukage", "barrel_hurt", "bonus_frames", "drop_frames")


def main(argv=None) -> int:
    return FG.main(argv, gate="DIE", scen_fn=scenario_list, need=NEED, deaths_ok=True, run_cls=Run, doc=__doc__)


if __name__ == "__main__":
    sys.exit(main())
