"""S5 -- the compositor census library: the gameplay model (doomfj.world + doomfj.combat) wired to the
ORACLE renderer (`ReferenceModel.render_wall_frame`), instrumented WITHOUT editing it.

HOW IT HOOKS IN (all from scratchpad code, nothing tracked is touched):
  * `reference_model.drawable_things` / `baked_thing_mask` are swapped for functions that return THIS
    frame's thing list and baked mask, so the oracle's own per-leaf "baked first, then runtime, list
    order" build, its budgets, its degradation and its two write-once fragment slots run unchanged;
  * `reference_model.MONSTER_TYPES` gains the synthetic types of the model's monsters (and, unless an
    option says otherwise, of their corpses), so the budget CATEGORY is the oracle's own test;
  * `rm.sprite_art` answers synthetic types from a real patch of assets/freedoom1.wad (the frame the
    thing would show -- the SIZE STAND-IN, see below);
  * `rm.project_thing` is wrapped: at every call it reads the caller's frame (the thing `t`, its leaf,
    n_mon/n_thing, `drawn`, and the two slot arrays `sfrag`/`sfrag2`), attributes to the PREVIOUS
    thing every slot the previous call's column loop claimed (a diff of the slot arrays), calls the
    original, and returns its result untouched. The only non-pass-through is option (b), which asks
    the ORIGINAL for the base min-size instead of the degraded one.

THE SIZE STAND-IN (the animated bank does not exist yet): a monster, corpse, drop, fireball, puff,
blood splat or exploding barrel is drawn with the REAL patch of the frame its state shows, at DOOM's
rotation for this viewer (`point_to_angle` against the facing octant), downscaled exactly as
`sprite_art` downscales. Mirrored rotations use the unmirrored patch (same span and run counts, only
the column order is reversed). Things sit on their leaf's floor as every sprite in the oracle does
(2D projectiles are drawn at floor level); fragment slots are PER COLUMN, so height never changes a
slot count.

Import order matters only in that the World keeps its OWN ReferenceModel (geometry, sight, aim); the
instrumented one draws.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj import gamedata as gd                                            # noqa: E402
from doomfj import reference_model as RMOD                                   # noqa: E402
from doomfj import world as W                                                # noqa: E402
from doomfj.config import Config                                             # noqa: E402
from doomfj.reference_model import (ReferenceModel, SimState, build_scene,  # noqa: E402
                                    MIN_SPRITE_H, MIN_SPRITE_H_MONSTER)
from doomfj.things import baked_thing_mask as _BTM                           # noqa: E402
from doomfj.things import drawable_things as _DT                             # noqa: E402
from doomfj.wad import WadFile, decode_picture                               # noqa: E402

# THE GAME TIER'S PICTURE: deg_gate.py's keyword set, = b0_scenarios.GameOracle.RENDER_KW. `sky` (V2)
# and the `bbox_cull` wedge cull are retired into the default build. Without `sky` the oracle differs
# from blocked27 on every frame that shows sky (coordinator, 2026-09-26: 36 of 200 frames, 35,249 px).
# `bbox_cull` moves no pixel but decides which leaves the walk visits, i.e. which things ARRIVE --
# the per-thing load/project terms of the fight line (census_control.py measures both effects).
RENDER_KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
                 near_steps=True, stack_steps=True, things=True, degrade=True,
                 sky=True, bbox_cull=True)
ORIG_MONSTER_TYPES = RMOD.MONSTER_TYPES
AIM_LO, AIM_HI = 72, 88                     # the pellet window (plan 6.4; combat.aim_lo/hi)
SYN0 = 100000                               # synthetic thing types start here
ROLES = ("live", "corpse", "drop", "fireball", "fx", "barrel")
SMALL = ("drop", "fireball", "fx")          # the things plan section 5 worries about
ANG45 = 0x20000000


class PThing:
    """A thing as the renderer reads it (type, x, y) -- identity, not value, is its key."""
    __slots__ = ("type", "x", "y", "angle", "flags")

    def __init__(self, type_, x, y):
        self.type, self.x, self.y, self.angle, self.flags = type_, x, y, 0, 7


class Meta:
    __slots__ = ("role", "idx", "baked", "shoot", "wad", "lump", "awake")

    def __init__(self, role, idx, baked, shoot=False, wad=-1, lump="", awake=False):
        self.role, self.idx, self.baked, self.shoot = role, idx, baked, shoot
        self.wad, self.lump, self.awake = wad, lump, awake


class Census:
    def __init__(self, skill=gd.SK_HARD):
        self.cfg = Config()
        self.W = self.cfg.VIEW_W
        self.rm = ReferenceModel(self.cfg)                  # the DRAWING model (instrumented)
        self.mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
        self.art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
        self.world = W.World(self.mw, skill=skill)          # its own ReferenceModel
        self.cmap = self.world.cmap
        self.skill = skill
        # -- today's drawable space and classification (the ORIGINAL functions, at spawn) --------
        self.wad_things = self.mw.things("E1M1")
        self.today, self.today_idx = _DT(self.rm, self.wad_things, self.art, {})
        self.today_baked = _BTM(self.rm, self.cmap, self.today, ORIG_MONSTER_TYPES)
        # -- the sprite lump index: (sprite, frame letter, rotation 1..8 or 0) -> lump -------------
        names = self.art.names()
        spr = names[names.index("S_START") + 1:names.index("S_END")]
        self.lumps = {}
        for n in spr:
            if len(n) >= 6:
                self.lumps.setdefault((n[:4], n[4], n[5]), n)
                if len(n) >= 8:
                    self.lumps.setdefault((n[:4], n[6], n[7]), n)          # the mirrored half
        self._art_cache, self._syn = {}, {}
        # -- map WAD things to the world's lists ---------------------------------------------------
        def key(t):
            return (t.type, t.x, t.y, t.angle, t.flags)
        wad_of = {}
        for i, t in enumerate(self.wad_things):
            wad_of.setdefault(key(t), i)
        wd = self.world
        self.mon_wad = [wad_of[key(t)] for t in wd.mon_things]
        self.pickup_of_wad = {wad_of[key(t)]: i for i, t in enumerate(wd.pickup_things)}
        self.barrel_of_wad = {wad_of[key(t)]: b for b, t in enumerate(wd.barrel_things)}
        self.mon_of_wad = {w: m for m, w in enumerate(self.mon_wad)}
        self.install()

    # ------------------------------------------------------------------------------ art
    def lump_for(self, sprite: str, frame: int, rot: int) -> str:
        letter = chr(ord("A") + frame)
        for r in (str(rot), "0"):
            n = self.lumps.get((sprite, letter, r))
            if n:
                return n
        for r in "12345678":                                   # any view of the frame at all
            n = self.lumps.get((sprite, letter, r))
            if n:
                return n
        raise KeyError((sprite, letter, rot))

    def art_of_lump(self, lump: str):
        """`sprite_art`'s tuple for one named patch -- the same downscale, line for line."""
        if lump in self._art_cache:
            return self._art_cache[lump]
        pic = decode_picture(self.art.get_data(lump))
        ds = self.rm.downscale
        dw, dh = max(1, pic.width // ds), max(1, pic.height // ds)
        cols, fcols = [], []
        for u in range(dw):
            dense = [-1] * pic.height
            for (v, t) in pic.columns[min(pic.width - 1, u * ds)]:
                if 0 <= v < pic.height:
                    dense[v] = t
            cols.append([dense[min(pic.height - 1, v * ds)] for v in range(dh)])
            fcols.append(dense)
        a = (cols, dh, dw, pic.width, pic.height, pic.leftoffset, pic.topoffset, fcols, pic.height)
        self._art_cache[lump] = a
        return a

    def syn_type(self, lump: str, role: str) -> int:
        k = (lump, role)
        if k not in self._syn:
            self._syn[k] = SYN0 + len(self._syn)
        return self._syn[k]

    # ------------------------------------------------------------------------------ install
    def install(self):
        rm = self
        orig_art = ReferenceModel.sprite_art.__get__(self.rm)
        by_type = {}

        def sprite_art(sprite_wad, kind, cache):
            if kind >= SYN0:
                if kind not in by_type:
                    by_type.update({v: k[0] for k, v in rm._syn.items()})
                return rm.art_of_lump(by_type[kind])
            return orig_art(sprite_wad, kind, cache)
        self.rm.sprite_art = sprite_art
        self.frame = None                                      # (things, baked) of the next render

        def drawable_things(model, things, sprite_wad, cache=None):
            if rm.frame is None:
                return _DT(model, things, sprite_wad, cache)
            return list(rm.frame[0]), None

        def baked_thing_mask(model, cmap, drawable, monster_types):
            if rm.frame is None:
                return _BTM(model, cmap, drawable, monster_types)
            return tuple(rm.frame[1])
        RMOD.drawable_things = drawable_things
        RMOD.baked_thing_mask = baked_thing_mask
        self.probe = Probe(self)

    # ------------------------------------------------------------------------------ frames
    def rotation(self, x: int, y: int, facing: int) -> int:
        ws = self.world.ws
        ang = self.rm.point_to_angle(ws.px, ws.py, x << 16, y << 16)
        return (((ang - facing * ANG45 + (ANG45 // 2) * 9) & 0xFFFFFFFF) >> 29) + 1

    def game_things(self, *, corpse_as_monster=True, effects_first=False, depth_order=False):
        """This tic's picture as (things, baked, meta): the skill's static things (today's baked/
        runtime split), then the model's monsters (live or corpse), drops, fireballs and effects --
        in the per-leaf order the variant asks for."""
        wd, ws = self.world, self.world.ws
        bit = gd.skill_bit(self.skill)
        rows = []                                              # (sort key, thing, meta)
        live_types, corpse_types = set(), set()
        for di, t in enumerate(self.today):
            wadi = self.today_idx[di]
            if t.type in ORIG_MONSTER_TYPES:
                continue                                       # the model draws monsters
            if t.flags & gd.MTF_NOTSINGLE or not t.flags & bit:
                continue                                       # R4: this skill, single player
            baked = self.today_baked[di]
            if wadi in self.pickup_of_wad and ws.pickup_taken[self.pickup_of_wad[wadi]]:
                continue
            if wadi in self.barrel_of_wad:
                b = self.barrel_of_wad[wadi]
                if not ws.bar_state[b]:
                    continue                                   # exploded and removed
                st = gd.STATES[gd.STATE_NAMES[ws.bar_state[b]]]
                lump = self.lump_for(st.sprite, st.frame_index, 0)
                p = PThing(self.syn_type(lump, "barrel"), t.x, t.y)
                rows.append(((wadi, 0), p, Meta("barrel", b, baked, ws.bar_health[b] > 0, wadi, lump)))
                continue
            rows.append(((wadi, 0), PThing(t.type, t.x, t.y), Meta("static", di, baked, False, wadi)))
        for m, wadi in enumerate(self.mon_wad):
            if not ws.mon_active[m]:
                continue
            st = gd.STATES[gd.STATE_NAMES[ws.mon_state[m]]]
            dead = ws.mon_health[m] <= 0
            x, y = ws.mon_x[m], ws.mon_y[m]
            lump = self.lump_for(st.sprite, st.frame_index, self.rotation(x, y, ws.mon_facing[m]))
            role = "corpse" if dead else "live"
            ty = self.syn_type(lump, role)
            (corpse_types if dead else live_types).add(ty)
            awake = bool(ws.mon_target[m])
            rows.append(((wadi, 0), PThing(ty, x, y),
                         Meta(role, m, False, not dead and bool(ws.mon_shootable[m]), wadi, lump, awake)))
            if ws.mon_drop[m] == 1:
                item = wd.dropper[m]
                dl = {2007: "CLIPA0", 2001: "SHOTA0"}[item]
                rows.append(((wadi, 1), PThing(self.syn_type(dl, "drop"), x, y),
                             Meta("drop", m, False, False, wadi, dl)))
        for s in range(W.FIREBALL_POOL):
            if ws.proj_active[s]:
                st = gd.STATES[gd.STATE_NAMES[ws.proj_state[s]]]
                lump = self.lump_for(st.sprite, st.frame_index, 0)
                rows.append(((10 ** 6 + s, 0), PThing(self.syn_type(lump, "fireball"),
                                                      ws.proj_x[s] >> 16, ws.proj_y[s] >> 16),
                             Meta("fireball", s, False, False, -1, lump)))
        for s in range(W.FX_POOL):
            if ws.fx_active[s]:
                st = gd.STATES[gd.STATE_NAMES[ws.fx_state[s]]]
                lump = self.lump_for(st.sprite, st.frame_index, 0)
                rows.append(((2 * 10 ** 6 + s, 0), PThing(self.syn_type(lump, "fx"),
                                                          ws.fx_x[s] >> 16, ws.fx_y[s] >> 16),
                             Meta("fx", s, False, False, -1, lump)))
        if effects_first:                                      # option (a)
            rows.sort(key=lambda r: (0 if r[2].role in SMALL else 1, r[0]))
        elif depth_order:                                      # option (d): runtime by view depth
            vc, vs = self.rm.read_cos(ws.pangle), self.rm.read_sin(ws.pangle)
            from doomfj.fixedpoint import _signed, fixed_mul

            def depth(p):
                tx, ty = _signed((p.x << 16) - ws.px, 32), _signed((p.y << 16) - ws.py, 32)
                return (_signed(fixed_mul(tx & 0xFFFFFFFF, vc, 8, 4), 32)
                        + _signed(fixed_mul(ty & 0xFFFFFFFF, vs, 8, 4), 32))
            rows.sort(key=lambda r: (r[0] if r[2].baked else (-1, depth(r[1]))))
        else:
            rows.sort(key=lambda r: r[0])
        mt = set(ORIG_MONSTER_TYPES) | live_types | (corpse_types if corpse_as_monster else set())
        return [r[1] for r in rows], [r[2].baked for r in rows], [r[2] for r in rows], frozenset(mt)

    def today_things(self):
        """blocked27's picture: every drawable WAD thing at spawn, today's classification."""
        metas = []
        for di, t in enumerate(self.today):
            wadi = self.today_idx[di]
            role = "live" if t.type in ORIG_MONSTER_TYPES else "static"
            metas.append(Meta(role, self.mon_of_wad.get(wadi, di), self.today_baked[di],
                              role == "live", wadi, ""))
        return list(self.today), list(self.today_baked), metas, ORIG_MONSTER_TYPES

    def today_things_r4(self):
        """today's picture with the R4 skill filter only: this skill's single-player things, today's
        art and classification, monsters at spawn -- the fight line's baseline."""
        bit = gd.skill_bit(self.skill)
        th, bk, me, mt = self.today_things()
        keep = [i for i, t in enumerate(th)
                if not t.flags & gd.MTF_NOTSINGLE and t.flags & bit]
        return [th[i] for i in keep], [bk[i] for i in keep], [me[i] for i in keep], mt

    @staticmethod
    def reorder_small_first(th, bk, me, mt):
        """option (a) on top of any order: drops and effects first, the rest keep their order."""
        idx = sorted(range(len(th)), key=lambda i: (0 if me[i].role in SMALL else 1, i))
        return [th[i] for i in idx], [bk[i] for i in idx], [me[i] for i in idx], mt

    def render(self, things, baked, metas, mtypes, *, exempt=None, scene=None, state=None):
        """One oracle frame with this thing list; returns (pixels, arrivals)."""
        ws = self.world.ws
        if state is None:
            state = SimState(ws.px, ws.py, ws.pangle, "E1M1")
        if scene is None:
            scene = build_scene(self.mw, self.mw, "E1M1", self.world.heights_now)
        self.frame = (things, baked)
        RMOD.MONSTER_TYPES = mtypes
        self.probe.begin({id(t): mm for t, mm in zip(things, metas)}, exempt)
        try:
            fb = bytes(self.rm.render_wall_frame(state, scene, sprite_wad=self.art, **RENDER_KW))
        finally:
            self.probe.end()
            self.frame = None
            RMOD.MONSTER_TYPES = ORIG_MONSTER_TYPES
        return fb, self.probe.arrivals


class Probe:
    """The project_thing wrapper and the slot-claim attribution (see the module docstring)."""

    def __init__(self, census: Census):
        self.c = census
        self.orig = ReferenceModel.project_thing.__get__(census.rm)
        census.rm.project_thing = self.project
        self.meta_of, self.exempt, self.arrivals, self._refs = {}, None, [], None

    def begin(self, meta_of, exempt):
        self.meta_of, self.exempt, self.arrivals, self._refs = meta_of, exempt, [], None

    def _attribute(self):
        sa, sb = self._refs
        if self.arrivals:
            a = self.arrivals[-1]
            pa, pb = self._pa, self._pb
            a["A"] = [x for x in range(len(sa)) if pa[x] is None and sa[x] is not None]
            a["B"] = [x for x in range(len(sb)) if pb[x] is None and sb[x] is not None]
            a["runs"] = (sum(len(sa[x][1]) for x in a["A"]) + sum(len(sb[x][1]) for x in a["B"]))
        self._pa, self._pb = list(sa), list(sb)

    def project(self, viewx, viewy, viewangle, viewz, tx, ty, fz, art, min_h=None):
        L = sys._getframe(1).f_locals
        if self._refs is None:
            self._refs = (L["sfrag"], L["sfrag2"])
            self._pa, self._pb = [None] * len(L["sfrag"]), [None] * len(L["sfrag2"])
        self._attribute()
        t = L["t"]
        meta = self.meta_of.get(id(t))
        mon = t.type in RMOD.MONSTER_TYPES
        base = MIN_SPRITE_H_MONSTER if mon else MIN_SPRITE_H
        use = min_h
        if self.exempt is not None and meta is not None and self.exempt(meta) and min_h != base:
            use = base                                         # option (b) -- a picture change
        res = self.orig(viewx, viewy, viewangle, viewz, tx, ty, fz, art, use)
        rb = res if use == base else self.orig(viewx, viewy, viewangle, viewz, tx, ty, fz, art, base)
        self.arrivals.append({
            "meta": meta, "leaf": L["ss_first"][L["seg_i"]], "mon": mon, "n_mon": L["n_mon"],
            "n_thing": L["n_thing"], "minh": min_h, "base": base, "used": use, "res": res,
            "rbase": rb, "drawn": bytes(L["drawn"]), "occA": bytes(0 if v is None else 1 for v in self._pa),
            "occB": bytes(0 if v is None else 1 for v in self._pb), "art": art,
            "bminh": L.get("b_minh", 0), "A": [], "B": [], "runs": 0})
        return res

    def end(self):
        if self._refs is not None:
            self._attribute()
