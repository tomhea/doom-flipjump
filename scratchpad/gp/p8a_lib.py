"""p8a_lib.py -- M7 P8a (package V): what the game-tier gates share for the final rung (docs/gp-final-plan.md 5).

The behaviour P8a's new scenarios test -- the dying view's sink (package A), knockback (K), infighting (I), the
compositor rules D3 a / b (C) -- is built in parallel on other branches. The gates' scenarios and their R9 controls
are written against package 0's INTERFACES (gp-final-plan 3.0 / 4.1: the modes, the schema fields, the damage
signatures with inflictors, `_thrust` / `_xy_move`, K's `_player_knock_move` / `_monster_knock_move`, I's
`target_alive`, A's `render_wall_frame(view_drop=)`, C's GAME_RENDER_KW keys), so they run unchanged once the packages
merge. Until then a scenario whose package is not in the tree AWAITS it: the gate prints which, runs nothing for it,
and ends INCOMPLETE (exit 2) -- never PASS.

  rules(pm, mm)      the P8a rules on at these modes: "sink" (world.player_sinks), "knock" (knockback_on), "fight"
                     (infighting_on), "p8a" (the final rung's player mode at all: C's compositor rules); a scenario
                     of a rule that is off is N/A (that game has no such thing)
  packages()         which packages' behaviour is IN THE MODEL, each detected by doing what it does on a fresh World
                     (A: a death think sinks the view and the oracle takes `view_drop`; K: a hit on the player
                     thrusts him and the knock move exists; I: a monster hit by a monster targets it; C: the
                     GAME_RENDER_KW keys exist) -- cached
  status(sc, pm, mm) "run" | "n/a: ..." | "awaits package X: ..."
  control(name)      the P8a R9 controls: ONE mutated rule each, applied to the model from outside its packages'
                     code (wrapping the interface functions) so it is ready before the code it breaks exists
  PICTURE_CONTROLS   the controls that change only the PICTURE (a render rule): a gate compares the pictures of the
                     SAME trace rendered with and without them (`picture_parts`) -- the state cannot part
  set_modes(pm, mm)  every gate module's MMODE / PMODE (and p2a_gate's override) -- `--modes PLAYER/MONSTER`
  frame_ops_line()   `--frame-ops`: a binary run's per-frame op readings, summarised (max, p95, mean, frames over
                     the 22M cap, and the tripwire of O-E1: 44M)
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for _q in (ROOT / "src", HERE):
    if str(_q) not in sys.path:
        sys.path.insert(0, str(_q))

from doomfj import gamedata as gd                                            # noqa: E402

M32 = 0xFFFFFFFF
CAP = 22_000_000               # D1: the frame cap the stress frames are recorded against (not capped: O-E1)
TRIPWIRE = 44_000_000          # O-E1: a stress frame over this must be attributed before the ship
# package C's GAME_RENDER_KW keys (docs/gp-final-plan.md 1.3): D3 a's rank and D3 b's barrel exemption. The plan names
# `rt_rank`; the barrel key is NOT named by the plan -- this is the name the gate asks C for (a merge note)
RANK_KEY = "rt_rank"
BARREL_KEY = "exempt_barrels"
# package A's split knob (docs/gp-final-plan.md 5.1's R9: "the oracle with the bands from the SUNK eye"): the gate's
# `band_eye` control turns it off -- the name the gate asks A for (a merge note)
SPLIT_KNOB = "VIEW_DROP_SPLIT"


class Awaits(Exception):
    """a control (or a scenario) needs a package that is not in this tree"""


# ================================================================================================
# the rules, the packages, a scenario's status
# ================================================================================================
def rules(pm: str, mm: str) -> frozenset:
    from doomfj import world as W
    return frozenset(n for n, on in (("sink", W.player_sinks(pm)), ("knock", W.knockback_on(pm, mm)),
                                     ("fight", W.infighting_on(mm)),
                                     # the final rung's game at all (C's D3 a / b: the compositor of P8a's tier)
                                     ("p8a", pm in W.P8A_PLAYER_MODES)) if on)


_PKG = None


def packages() -> dict:
    """{"A" | "K" | "I" | "C": (present, how it was decided)} -- each package's behaviour, DONE on a fresh model"""
    global _PKG
    if _PKG is not None:
        return _PKG
    from doomfj.world import TicEvents, World
    out = {}
    # A: the death think sinks the view one unit, and the oracle draws a sunk eye
    try:
        import inspect
        from doomfj.reference_model import ReferenceModel
        w = World(player="final", monsters="full")
        ev = TicEvents(0)
        w.damage_player(w.ws.p_health + 50, ("gate", 0), None, ev)
        w._death_think({k: False for k in __import__("doomfj.world", fromlist=["KEYS"]).KEYS}, ev)
        sank = w.ws.p_vdrop == 1
        kw = "view_drop" in inspect.signature(ReferenceModel.render_wall_frame).parameters
        out["A"] = (sank and kw, "death think p_vdrop %d (want 1); render_wall_frame(view_drop=) %s"
                    % (w.ws.p_vdrop, "yes" if kw else "no"))
    except Exception as e:                       # noqa: BLE001 -- any failure is "not in"
        out["A"] = (False, "probe raised %r" % (e,))
    # K: a monster's hit on the player thrusts him, and the player's knock move exists
    try:
        w = World(player="final", monsters="push")
        m = next(i for i in range(w.layout.nmon) if w.ws.mon_active[i])
        w.ws.p_armor = 0
        w.damage_player(10, ("mon", m), ("mon", m), TicEvents(0))
        thr = bool(w.ws.p_momx or w.ws.p_momy)
        mv = hasattr(type(w), "_player_knock_move") and hasattr(type(w), "_monster_knock_move")
        out["K"] = (thr and mv, "a hit thrusts the player: %s; _player_knock_move / _monster_knock_move: %s"
                    % (thr, mv))
    except Exception as e:                       # noqa: BLE001
        out["K"] = (False, "probe raised %r" % (e,))
    # I: a monster hit by a monster targets it
    try:
        w = World(player="final", monsters="final")
        act = [i for i in range(w.layout.nmon) if w.ws.mon_active[i]]
        a, b = act[0], act[1]
        w.damage_monster(a, 1, ("mon", b), ("mon", b), TicEvents(0))
        sw = w.ws.mon_target[a] == 2 + b
        ta = hasattr(type(w), "target_alive")
        out["I"] = (sw and ta, "a monster hit by slot %d targets %d (want %d); target_alive: %s"
                    % (b, w.ws.mon_target[a], 2 + b, ta))
    except Exception as e:                       # noqa: BLE001
        out["I"] = (False, "probe raised %r" % (e,))
    from doomfj import reference_model as RM
    has = [k for k in (RANK_KEY, BARREL_KEY) if k in RM.GAME_RENDER_KW]
    kw = hasattr(RM, "game_render_kw") and hasattr(RM, "rank_depth_key")
    out["C"] = (len(has) == 2 and kw, "GAME_RENDER_KW has %s of %s; game_render_kw / rank_depth_key: %s"
                % (has, [RANK_KEY, BARREL_KEY], kw))
    _PKG = out
    return out


def status(sc: dict, pm: str, mm: str) -> str:
    """"run", or why not: a scenario's `rule` (a P8a rule its game must have) and `pkg` (the packages whose behaviour
    it tests) -- "n/a: ..." when the modes lack the rule (that game has no such thing: not a failure), "awaits ..."
    when a package is not in the tree (the gate is INCOMPLETE)"""
    need = sc.get("rule")
    for r in ((need,) if isinstance(need, str) else tuple(need or ())):
        if r not in rules(pm, mm):
            return "n/a: the modes %s/%s have no %r rule" % (pm, mm, r)
    pk = packages()
    miss = [p for p in sc.get("pkg", ()) if not pk[p][0]]
    if miss:
        return "awaits package %s (%s)" % ("+".join(miss), "; ".join(pk[p][1] for p in miss))
    return "run"


# ================================================================================================
# the modes of every gate module
# ================================================================================================
def default_modes() -> tuple:
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    return PLAYER_MODE, MONSTER_MODE


def set_modes(pm: str, mm: str) -> None:
    """every loaded gate module's (PMODE, MMODE) and p2a_gate's player override -- `--modes PLAYER/MONSTER`"""
    from doomfj import world as W
    assert pm in W.PLAYER_MODES and mm in W.MONSTER_MODES, (pm, mm)
    for name in ("hurt_gate", "fight_gate", "die_gate", "__main__"):     # a gate run as a script is __main__
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "MMODE"):
            mod.MMODE, mod.PMODE = mm, pm
    g = sys.modules.get("p2a_gate")
    if g is not None:
        g.PLAYER_MODE_OVERRIDE = pm
    # the gates' oracle draws THESE modes' picture: package C's compositor rules follow the player mode
    # (world.compositor_d3; GAME_RENDER_KW holds them as the game tier's mode has them, so an --oracle-only run at
    # another mode -- "final" before the integrator's flip -- must set them, or C1-C3's controls cannot part)
    P = sys.modules.get("probe")
    from doomfj import reference_model as RM
    if P is not None and hasattr(RM, "game_render_kw") and hasattr(W, "compositor_d3"):
        kw = RM.game_render_kw(W.compositor_d3(pm))
        P.Oracle.RENDER_KW.clear()
        P.Oracle.RENDER_KW.update(kw)


def parse_modes(text) -> tuple:
    if not text:
        return default_modes()
    pm, mm = text.split("/")
    return pm, mm


# ================================================================================================
# the controls (R9): ONE mutated rule each
# ================================================================================================
CONTROLS = {
    # A -- the dying view
    "no_sink": "the death think does not sink the view (p_vdrop kept)",
    "sink_fast": "the view sinks 2 units a death-think tic",
    "sink_floor": "the sink stops at viewheight 7 (p_vdrop <= 34)",
    "sink_restart": "the restart keeps the sink",
    "band_eye": "the oracle draws the planes from the SUNK eye (A's split removed)",
    "dead_no_slide": "a dead player's knock move does not run (the corpse does not slide)",
    # K -- knockback
    "no_thrust": "P_DamageMobj thrusts nothing",
    "thrust_sign": "the thrust pushes TOWARD the inflictor",
    "no_friction": "FRICTION = FRACUNIT (no friction)",
    "stopspeed": "STOPSPEED = 0 (a knock never stops by speed)",
    "wall_keeps": "a refused player knock keeps its momentum",
    "blast_inflictor": "a blast thrusts from the PLAYER, not the barrel",
    "mass": "the target's mass ignored (every mass 100)",
    "frac_drop": "the monsters' position fractions are dropped every tic",
    "no_retest": "a monster's knock candidates are accepted untested",
    "drop_follows": "a drop lies where its corpse is now (not where it died)",
    "saw_thrust": "the chainsaw thrusts",
    "no_reverse": "the falling-forward reversal never applies (the target's z lowered)",
    "reverse_rng": "the reversal's coin drawn on the wrong stream",
    # I -- infighting
    "pass_through": "a monster's bullet never damages a monster",
    "no_switch": "a monster or barrel source never becomes a monster's target",
    "fx_none": "a monster's bullet makes no blood or puff",
    "species": "the fireball's same-species rule off (the shooter's species changed)",
    "hits_shooter": "a fireball is not passed through its shooter",
    "bar_src_player": "a blast's source is always the player",
    "target_stale": "a dead target is kept (target_alive always true)",
    "los_ignored": "the chase sees through walls",
    "threshold_ignored": "a monster's threshold is ignored (every source switches it)",
    # C -- the compositor
    "rank_off": "D3 a off: a leaf's runtime things by depth alone",
    "rank_swap": "D3 a swapped: a leaf's monsters and fireballs drawn before its effects and drops",
    "barrel_soft": "D3 b off: barrels take the scenery soft budget",
}
PICTURE_CONTROLS = frozenset({"band_eye", "rank_off", "rank_swap", "barrel_soft"})


@contextlib.contextmanager
def control(name: str):
    """the model (or the oracle's picture) with rule `name` broken, for the duration. Raises Awaits when the rule's
    package is not in this tree (the control has nothing to break yet)"""
    from doomfj import combat as C
    from doomfj import world as W
    CM, WD = C.CombatMixin, W.World
    saved = []

    def patch(obj, attr, val):
        saved.append((obj, attr, getattr(obj, attr)))
        setattr(obj, attr, val)

    def need(obj, attr, pkg):
        if not hasattr(obj, attr):
            raise Awaits("package %s: %s.%s" % (pkg, getattr(obj, "__name__", obj), attr))
        return getattr(obj, attr)

    def around(obj, attr, before=None, after=None, pkg=None):
        """wrap obj.attr: before(self, *a) -> a state; after(self, state, *a) once the original returned"""
        orig = need(obj, attr, pkg) if pkg else getattr(obj, attr)

        def fn(self, *a, **k):
            st = before(self, *a) if before else None
            try:
                return orig(self, *a, **k)
            finally:
                if after:
                    after(self, st, *a)
        patch(obj, attr, fn)

    if name not in CONTROLS:
        raise KeyError(name)
    # ---- A
    if name == "no_sink":
        around(CM, "_death_think", lambda s, *a: s.ws.p_vdrop, lambda s, v, *a: setattr(s.ws, "p_vdrop", v))
    elif name == "sink_fast":
        around(CM, "_death_think", lambda s, *a: s.ws.p_vdrop,
               lambda s, v, *a: setattr(s.ws, "p_vdrop", min(35, s.ws.p_vdrop + 1)) if s.ws.p_vdrop > v else None)
    elif name == "sink_floor":
        around(CM, "_death_think", None, lambda s, v, *a: setattr(s.ws, "p_vdrop", min(34, s.ws.p_vdrop)))
    elif name == "sink_restart":
        around(CM, "_restart", lambda s, *a: s.ws.p_vdrop, lambda s, v, *a: setattr(s.ws, "p_vdrop", v))
    elif name == "band_eye":
        from doomfj import reference_model as RM
        need(RM, SPLIT_KNOB, "A")
        patch(RM, SPLIT_KNOB, False)
    elif name == "dead_no_slide":
        orig = need(CM, "_player_knock_move", "K")

        def pkm(self, *a, **k):
            if self.ws.p_dead:
                return None
            return orig(self, *a, **k)
        patch(CM, "_player_knock_move", pkm)
    # ---- K
    elif name in ("no_thrust", "thrust_sign", "blast_inflictor", "mass", "saw_thrust", "no_reverse", "reverse_rng"):
        need(CM, "_player_knock_move", "K")
        orig = CM._thrust

        def mom(self, target):
            ws = self.ws
            if target[0] == "player":
                return ws.p_momx, ws.p_momy
            return ws.mon_momx[target[1]], ws.mon_momy[target[1]]

        def set_mom(self, target, v):
            ws = self.ws
            if target[0] == "player":
                ws.p_momx, ws.p_momy = v
            else:
                ws.mon_momx[target[1]], ws.mon_momy[target[1]] = v

        def thrust(self, target, inflictor, source, dmg):
            ws = self.ws
            if name == "no_thrust":
                return None
            if name == "blast_inflictor" and inflictor and inflictor[0] == "bar":
                inflictor = ("player", -1)
            m0 = mom(self, target)
            keep = None
            if name == "saw_thrust" and ws.p_ready == gd.WP_CHAINSAW:
                keep, ws.p_ready = ws.p_ready, gd.WP_FIST
            if name == "no_reverse" and target[0] == "mon":
                keep = ws.mon_floorz[target[1]]
                ws.mon_floorz[target[1]] = -0x8000
            if name == "reverse_rng":
                if target[0] == "mon":
                    keep = ws.mon_rng[target[1]]
                    ws.mon_rng[target[1]] = ws.rng_player
                else:
                    keep = ws.rng_player
                    ws.rng_player = ws.rng_fx
            try:
                out = orig(self, target, inflictor, source, dmg)
            finally:
                if name == "saw_thrust" and keep is not None:
                    ws.p_ready = keep
                if name == "no_reverse" and target[0] == "mon":
                    ws.mon_floorz[target[1]] = keep
                if name == "reverse_rng":
                    if target[0] == "mon":
                        ws.rng_player, ws.mon_rng[target[1]] = ws.mon_rng[target[1]], keep
                    else:
                        ws.rng_fx, ws.rng_player = ws.rng_player, keep
            m1 = mom(self, target)
            d = (m1[0] - m0[0], m1[1] - m0[1])
            if name == "thrust_sign":
                set_mom(self, target, (m0[0] - d[0], m0[1] - d[1]))
            elif name == "mass" and target[0] == "mon":
                k = self.mon_info[target[1]].mass // 100
                set_mom(self, target, (m0[0] + d[0] * k, m0[1] + d[1] * k))
            return out
        patch(CM, "_thrust", thrust)
    elif name in ("no_friction", "stopspeed"):
        need(CM, "_player_knock_move", "K")
        attr, val = ("FRICTION", 0x10000) if name == "no_friction" else ("STOPSPEED", 0)
        for mod in (gd, C, W) + tuple(m for n_, m in sys.modules.items() if n_ == "doomfj.knockcode"):
            if hasattr(mod, attr):
                patch(mod, attr, val)
    elif name == "wall_keeps":
        orig = need(CM, "_player_knock_move", "K")

        def pkm(self, *a, **k):
            ws = self.ws
            m0 = (ws.p_momx, ws.p_momy)
            out = orig(self, *a, **k)
            if any(abs(v) >= gd.STOPSPEED for v in m0) and (ws.p_momx, ws.p_momy) == (0, 0):
                ws.p_momx, ws.p_momy = m0
            return out
        patch(CM, "_player_knock_move", pkm)
    elif name == "frac_drop":
        need(WD, "_monster_knock_move", "K")

        def zero(self, st, *a):
            for m in range(self.layout.nmon):
                self.ws.mon_fx[m] = self.ws.mon_fy[m] = 0
        around(WD, "_monsters_phase", None, zero)
    elif name == "no_retest":
        orig = need(WD, "_monster_knock_move", "K")

        def mkm(self, *a, **k):
            def accept(m, nx, ny, **kw):              # (K's corpse variant passes corpse=)
                return W.OK, self.ws.mon_floorz[m]
            self.try_move_monster = accept
            self.try_move_lines = accept
            try:
                return orig(self, *a, **k)
            finally:
                del self.try_move_monster
                del self.try_move_lines
        patch(WD, "_monster_knock_move", mkm)
    elif name == "drop_follows":
        need(CM, "_player_knock_move", "K")
        patch(WD, "drop_pos", lambda self, m: (self.ws.mon_x[m], self.ws.mon_y[m]))
    # ---- I
    elif name in ("pass_through", "fx_none"):
        need(WD, "target_alive", "I")
        orig = CM._mon_hitscan

        def hs(self, *a, **k):
            if name == "pass_through":
                self.damage_monster = lambda m, dmg, source, inflictor, ev: None
            else:
                self._spawn_fx = lambda *a_, **k_: None
                self._spawn_fx_at_target = lambda *a_, **k_: None
            try:
                return orig(self, *a, **k)
            finally:
                for at in ("damage_monster", "_spawn_fx", "_spawn_fx_at_target"):
                    self.__dict__.pop(at, None)
        patch(CM, "_mon_hitscan", hs)
    elif name == "no_switch":
        need(WD, "target_alive", "I")

        def b(self, m, dmg, source, inflictor, ev):
            return self.ws.mon_target[m], self.ws.mon_threshold[m]

        def a(self, st, m, dmg, source, inflictor, ev):
            if source and source[0] in ("mon", "bar") and self.ws.mon_target[m] != st[0]:
                self.ws.mon_target[m], self.ws.mon_threshold[m] = st
        around(CM, "damage_monster", b, a)
    elif name == "threshold_ignored":
        need(WD, "target_alive", "I")
        around(CM, "damage_monster", lambda s, m, *a: s.ws.mon_threshold.__setitem__(m, 0))
    elif name in ("species", "hits_shooter"):
        need(WD, "target_alive", "I")
        orig = CM._missile_try

        def mt(self, s, nx, ny, ev):
            ws = self.ws
            src = ws.proj_src[s]
            if name == "hits_shooter":
                n = self.layout.nmon
                ws.proj_src[s] = (src + 1) % n
                try:
                    return orig(self, s, nx, ny, ev)
                finally:
                    if ws.proj_src[s] == (src + 1) % n:
                        ws.proj_src[s] = src
            other = next(m for m in range(self.layout.nmon) if self.mon_things[m].type != self.mon_things[src].type)
            keep = (self.mon_info[src], self.mon_things[src])
            self.mon_info[src], self.mon_things[src] = self.mon_info[other], self.mon_things[other]
            try:
                return orig(self, s, nx, ny, ev)
            finally:
                self.mon_info[src], self.mon_things[src] = keep
        patch(CM, "_missile_try", mt)
    elif name == "bar_src_player":
        need(WD, "target_alive", "I")
        around(CM, "_radius_attack", lambda s, b, *a: s.ws.bar_src.__setitem__(b, 1))
    elif name == "target_stale":
        need(WD, "target_alive", "I")
        patch(WD, "target_alive", lambda self, m: True)
    elif name == "los_ignored":
        need(WD, "target_alive", "I")

        def b(self, *a):
            self.los_points = lambda p, q: True

        def a(self, st, *args):
            self.__dict__.pop("los_points", None)
        around(WD, "_a_chase", b, a)
    # ---- C (the picture: the gate's oracle keywords)
    elif name == "rank_swap":                    # package C's own R9 (reference_model's note at D3_RENDER_KW)
        from doomfj import reference_model as RM
        orig = need(RM, "rank_depth_key", "C")
        patch(RM, "rank_depth_key", lambda vx, vy, x, y, r: orig(vx, vy, x, y, 1 - r))
    elif name in ("rank_off", "barrel_soft"):
        import probe as P
        key = RANK_KEY if name == "rank_off" else BARREL_KEY
        from doomfj.reference_model import GAME_RENDER_KW
        if key not in GAME_RENDER_KW:
            raise Awaits("package C: GAME_RENDER_KW[%r]" % key)
        kw = P.Oracle.RENDER_KW
        saved.append((kw, None, dict(kw)))
        kw[key] = False
    try:
        yield
    finally:
        for obj, attr, val in reversed(saved):
            if attr is None:
                obj.clear()
                obj.update(val)
            else:
                setattr(obj, attr, val)


def picture_parts(run, want: list, ctl: str):
    """a PICTURE control: the first world frame of the SAME trace whose picture the broken rule changes -> (f,
    "picture") or None. (`hurt_gate.parts` draws a picture only where the mobiles or the removals differ -- a render
    rule moves neither)"""
    ref = [run.picture(fr) if fr["drawn"] == "world" else None for fr in want]
    with control(ctl):
        for f, fr in enumerate(want):
            if ref[f] is not None and run.picture(fr) != ref[f]:
                return f, "picture"
    return None


# ================================================================================================
# the counters P8a's claims read (from a p2a_gate.Mirror trace)
# ================================================================================================
def counters(tr: list) -> dict:
    """knock_frames: frames ending with the player's knock momentum not zero; mon_knock_frames: ... a monster's;
    frac_frames: ... a monster's position fraction not zero; knock_moves / knock_walls: the knock moves that ran and
    the ones a wall refused (monsters.KnockTap, recorded per frame by the Mirror); infight: monster -> monster target
    switches (a target newly >= 2); sink_max: the largest p_vd; sink_frames: frames with p_vd > 0; corpse_slides:
    frames on which a dead monster's position changed; dead_slides: frames on which a dead player's pose changed;
    knock_refused / mon_knock_refused: the player's / the monsters' knock tries K refused (TicEvents.knocks)"""
    c = {k: 0 for k in ("knock_frames", "mon_knock_frames", "frac_frames", "knock_moves", "knock_walls", "infight",
                        "sink_max", "sink_frames", "corpse_slides", "dead_slides", "knock_refused", "mon_knock_refused")}
    prev = None
    for fr in tr:
        # package K's own record of each knock try: TicEvents.knocks [(thing, accepted)] -- every refusal, whatever
        # the momentum (KnockTap's wall test needs a component of at least STOPSPEED going in)
        for ev in fr["ev"]:
            for thing, ok in getattr(ev, "knocks", ()) if ev is not None else ():
                if not ok:
                    c["knock_refused" if thing[0] == "player" else "mon_knock_refused"] += 1
        st = fr["mstate"]
        if st.get("p_kmx") or st.get("p_kmy"):
            c["knock_frames"] += 1
        if any(st.get("mkx", ())) or any(st.get("mky", ())):
            c["mon_knock_frames"] += 1
        if any(st.get("mfx", ())) or any(st.get("mfy", ())):
            c["frac_frames"] += 1
        kn = fr.get("knock") or (0, 0)
        c["knock_moves"] += kn[0]
        c["knock_walls"] += kn[1]
        c["sink_max"] = max(c["sink_max"], st.get("p_vd", 0))
        c["sink_frames"] += st.get("p_vd", 0) > 0
        if prev is not None:
            pt, t = prev["mstate"].get("mon_target"), st.get("mon_target")
            if t is not None and pt is not None and len(pt) == len(t):
                c["infight"] += sum(1 for a, b in zip(pt, t) if b >= 2 and b != a)
            hp, php = st.get("mon_health"), prev["mstate"].get("mon_health")
            if hp is not None and php is not None and fr.get("mxy") and prev.get("mxy"):
                # dead on BOTH frames: a monster that walked and died in one frame did not slide
                c["corpse_slides"] += any(_dead(h) and _dead(g) and a != b
                                          for h, g, a, b in zip(hp, php, prev["mxy"], fr["mxy"]))
            if prev["mstate"].get("p_dead") and st.get("p_dead") and fr["pose"][:2] != prev["pose"][:2]:
                c["dead_slides"] += 1
        prev = fr
    return c


def _dead(h) -> bool:
    """a 12-bit health read unsigned (MonsterPhase.state) is <= 0"""
    return h == 0 or bool(h & 0x800)


def mon_moved(tr: list, m: int) -> bool:
    """monster m's whole-unit position changed on some frame"""
    xs = {fr["mxy"][m] for fr in tr if fr.get("mxy")}
    return len(xs) > 1


# ================================================================================================
# --frame-ops
# ================================================================================================
def frame_ops_line(ops: list) -> str:
    """a binary run's per-frame op readings (probe.Probe.frame_ops: each within +-2^18), summarised"""
    if not ops:
        return "frame ops: none read"
    s = sorted(ops)
    p95 = s[min(len(s) - 1, -(-95 * len(s) // 100) - 1)]
    over = sum(1 for v in ops if v > CAP)
    trip = sum(1 for v in ops if v > TRIPWIRE)
    return ("frame ops: max %s (frame %d), p95 %s, mean %s, %d of %d frames over %s, %d over the %s tripwire%s"
            % (format(s[-1], ","), ops.index(s[-1]), format(p95, ","), format(sum(ops) // len(ops), ","), over,
               len(ops), format(CAP, ","), trip, format(TRIPWIRE, ","),
               " -- ATTRIBUTE IT (O-E1)" if trip or sum(ops) / len(ops) > 30_000_000 else ""))
