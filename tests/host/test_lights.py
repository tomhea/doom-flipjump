"""M8 -- THE SECTOR LIGHT SPECIALS on the host: doomfj.lights (the rules both mirrors run), the model's thinkers
(world.World._lights_phase), the oracle's `sector_lights`, and what the emitter and the build read from them.

  * E1M2's thinkers: 18 light specials, the 9 animated ones (3 flashes, a fast strobe, a fire flicker, 4 glows) with
    their levels -- the 9 glows between equal lights are static -- and the min surrounding light DOOM's way;
  * the tic, against an INDEPENDENT transcription of p_lights.c that runs on light VALUES (no states, no tables):
    thousands of tics of every E1M2 thinker and a synthetic set must show the same lights, counts and stream (R9: a
    transcription with T_Glow's bound check moved is caught);
  * the world: the thinkers tic `monster_tics` times a frame, not on a frozen level, and NEW GAME puts them back;
    E1M1's world has no light cell, field or keyword (its flag is off);
  * the oracle: `sector_lights` at every thinker's state 0 draws today's picture (the marking rule it switches on is
    pixel-neutral there), a changed light changes pixels, and every two-sided seg on an animated light marks in some
    light state -- the fact the oracle's marking rule rests on (the emitter asserts it too);
  * the build: the cells persist on E1M2 only; the leaf bases reach every light state's lightnum; the flag is not an
    fj constant; p5_tic_lines puts the light phase after the effects, inside the world tic's loop.
"""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import lightcode as LC
from doomfj import lights as L
from doomfj import rng as R
from doomfj.config import Config, map_cfg
from doomfj.wad import Linedef, Sector, Sidedef, WadFile

FIX = Path(__file__).resolve().parents[1] / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def mw2():
    return WadFile.from_path(FIX / "freedoom_e1m2.wad")


@pytest.fixture(scope="module")
def ths(mw2):
    return L.map_thinkers(mw2, "E1M2")


# ---- the thinkers ---------------------------------------------------------------------------------------------------

def test_e1m2s_light_specials(mw2, ths):
    every = L.all_thinkers(mw2.sectors("E1M2"), mw2.linedefs("E1M2"), mw2.sidedefs("E1M2"))
    assert sorted(t.special for t in every) == [1] * 3 + [2] + [8] * 13 + [17]
    assert [(t.sector, t.kind, t.levels) for t in ths] == [
        (1, "flash", (208, 160)), (70, "flash", (192, 176)), (97, "glow", (208, 200)), (194, "fire", (96, 112)),
        (256, "strobe", (144, 112)), (261, "flash", (192, 160)), (283, "glow", (192, 184, 176, 168)),
        (323, "glow", (224, 216, 208, 200, 192, 184)), (350, "glow", (224, 216, 208, 200, 192, 184))]
    static = [t for t in every if t not in ths]
    assert len(static) == 9 and all(t.kind == "glow" and t.levels == (t.maxlight,) for t in static)
    # sector 194's fire: its minlight (the min surrounding + 16) is ABOVE its own light, so the first flicker takes it
    # to 112 for good -- DOOM's own arithmetic
    fire = ths[3]
    assert fire.minlight == 112 > fire.maxlight == 96


def test_min_surrounding_light_reads_twosided_lines_only():
    secs = [Sector(0, 128, "F", "C", 200, 1, 0), Sector(0, 128, "F", "C", 100, 0, 0), Sector(0, 128, "F", "C", 50, 0, 0)]
    sds = [Sidedef(0, 0, "-", "-", "-", 0), Sidedef(0, 0, "-", "-", "-", 1), Sidedef(0, 0, "-", "-", "-", 0),
           Sidedef(0, 0, "-", "-", "-", 2)]

    def line(front, back, flags):
        return Linedef(0, 1, flags, 0, 0, front, back)
    lds = [line(0, 1, L.ML_TWOSIDED), line(2, 3, 0)]           # the second line has two sides but no ML_TWOSIDED
    assert L.min_surrounding_light(secs, lds, sds, 0, 200) == 100
    lds[1] = line(2, 3, L.ML_TWOSIDED)
    assert L.min_surrounding_light(secs, lds, sds, 0, 200) == 50
    assert L.min_surrounding_light(secs, lds, sds, 1, 100) == 100      # never above max


def test_the_flag_is_e1m2s_and_not_an_fj_constant(mw2):
    assert L.lights_on("E1M2") and not L.lights_on("E1M1")
    assert map_cfg(Config(), "E1M2").SECTOR_LIGHTS == 1 and Config().SECTOR_LIGHTS == 0
    assert "SECTOR_LIGHTS" not in map_cfg(Config(), "E1M2").constants()
    assert L.map_thinkers(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1") == []
    assert R.STREAM_LIGHT == 255 and R.stream_seed(R.STREAM_LIGHT) not in {R.stream_seed(s) for s in range(255)}


# ---- the tic, against p_lights.c on light values ---------------------------------------------------------------------

class _Doom:
    """p_lights.c on a sector's LIGHT VALUE -- written from the C, sharing nothing with doomfj.lights but the RNG table"""

    def __init__(self, th, rng, glow_bound_late=False):
        self.th, self.light, self.late = th, th.maxlight, glow_bound_late
        self.rng = rng
        if th.kind == "flash":
            self.count = (self._rand() & 64) + 1
        elif th.kind == "strobe":
            self.count = 1 if th.sync else (self._rand() & 7) + 1
        elif th.kind == "glow":
            self.direction = -1
        else:
            self.count = 4

    def _rand(self):
        v, self.rng[0] = R.p_random(self.rng[0])
        return v

    def think(self):
        th = self.th
        if th.kind == "glow":
            if self.direction == -1:
                self.light -= 8
                if (self.light < th.minlight) if self.late else (self.light <= th.minlight):
                    self.light += 8
                    self.direction = 1
            else:
                self.light += 8
                if self.light >= th.maxlight:
                    self.light -= 8
                    self.direction = -1
            return
        self.count -= 1
        if self.count:
            return
        if th.kind == "strobe":
            if self.light == th.minlight:
                self.light, self.count = th.maxlight, 5
            else:
                self.light, self.count = th.minlight, th.darktime
        elif th.kind == "flash":
            if self.light == th.maxlight:
                self.light, self.count = th.minlight, (self._rand() & 7) + 1
            else:
                self.light, self.count = th.maxlight, (self._rand() & 64) + 1
        else:
            amount = (self._rand() & 3) * 16
            self.light = th.minlight if self.light - amount < th.minlight else th.maxlight - amount
            self.count = 4


def _synthetic():
    return [L.LightThinker(400, 3, "strobe", 200, 120, (200, 120), L.SLOWDARK, False),
            L.LightThinker(401, 12, "strobe", 176, 0, (176, 0), L.SLOWDARK, True),
            L.LightThinker(403, 17, "fire", 192, 144, L._fire_levels(192, 144)),
            L.LightThinker(404, 8, "glow", 128, 112, L._glow_levels(128, 112)),
            L.LightThinker(405, 8, "glow", 255, 0, L._glow_levels(255, 0))]


def _agree(ths, tics, **kw):
    rng = [R.stream_seed(R.STREAM_LIGHT)]
    doom = [_Doom(th, rng, **kw) for th in ths]
    states, counts, r = L.level_start(ths)
    if r != rng[0]:
        return False
    for _ in range(tics):
        for d in doom:
            d.think()
        r = L.tic_all(ths, states, counts, r)
        if L.lights_of(ths, states) != {d.th.sector: d.light for d in doom} or r != rng[0]:
            return False
    return True


def test_the_tic_is_p_lights(ths):
    assert _agree(ths, 4000)
    assert _agree(_synthetic(), 4000)


def test_control_a_glow_turning_late_is_caught(ths):
    """R9: T_Glow with `<` for `<=` at the bottom -- a light one step lower than any state (the model's state_of
    refuses it, or the lights part)"""
    with pytest.raises(AssertionError):
        assert _agree(ths, 200, glow_bound_late=True)


# ---- the world --------------------------------------------------------------------------------------------------------

@pytest.fixture()
def w2(mw2):
    from doomfj.world import World
    return World(mw2, "E1M2", skill=gd.SK_HARD, monsters="idle", strict=True)


def test_the_world_tics_its_lights_with_the_monsters(w2, ths):
    from doomfj.world import MONSTER_TICS_PER_FRAME
    assert w2.light_thinkers == ths and w2.layout.nlight == 9
    states, counts, r = L.level_start(ths)
    assert (list(w2.ws.lt_state), list(w2.ws.lt_count), w2.ws.rng_light) == (states, counts, r)
    assert w2.lights_now() == {th.sector: th.maxlight for th in ths}
    for _f in range(40):
        w2.tic({})
        for _t in range(MONSTER_TICS_PER_FRAME):
            r = L.tic_all(ths, states, counts, r)
        assert (list(w2.ws.lt_state), list(w2.ws.lt_count), w2.ws.rng_light) == (states, counts, r)
    assert w2.lights_now() != {th.sector: th.maxlight for th in ths}
    assert w2.light_render_kw() == {"sector_lights": w2.lights_now()}


def test_a_frozen_level_freezes_the_lights_and_new_game_restarts_them(w2, ths):
    for _f in range(30):
        w2.tic({})
    w2.ws.g_leveldone = 1
    before = (list(w2.ws.lt_state), list(w2.ws.lt_count), w2.ws.rng_light)
    w2.tic({})
    assert (list(w2.ws.lt_state), list(w2.ws.lt_count), w2.ws.rng_light) == before
    w2.ws.g_leveldone = 0
    w2.new_game(gd.SK_EASY)
    w2.tic({})                                     # the restart, then this tic's two light tics
    states, counts, r = L.level_start(ths)
    for _t in range(w2.monster_tics):
        r = L.tic_all(ths, states, counts, r)
    assert (list(w2.ws.lt_state), list(w2.ws.lt_count), w2.ws.rng_light) == (states, counts, r)


def test_e1m1s_world_has_no_lights():
    from doomfj.monsters import view_drop_kw
    from doomfj.world import World
    w = World(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1", monsters="idle")
    assert w.light_thinkers == [] and w.layout.nlight == 0 and w.lights_now() == {} and w.light_render_kw() == {}
    assert not [f for f in w.schema if f.group == "light"]
    assert view_drop_kw(None) == {}


# ---- the oracle -----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def oracle(mw2):
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import ReferenceModel, build_scene
    art = WadFile.from_path(ROOT / "assets" / "freedoom1.wad")
    return ReferenceModel(map_cfg(GAME_CFG, "E1M2")), build_scene(mw2, mw2, "E1M2"), art


def _view(sector):
    return {1: (608, 72, 0x40000000), 323: (2021, -2498, 0), 194: (1373, -997, 0x80000000),
            256: (1514, -2016, 0)}[sector]


@pytest.mark.parametrize("sector", [1, 323, 194, 256])
def test_the_oracle_draws_the_lights(oracle, ths, sector):
    from doomfj.reference_model import GAME_RENDER_KW, SimState
    rm, scene, art = oracle
    x, y, a = _view(sector)
    st = SimState(x << 16, y << 16, a, "E1M2")
    plain = rm.render_wall_frame(st, scene, sprite_wad=art, **GAME_RENDER_KW)
    # every thinker at state 0: the marking rule the keys switch on draws the same picture
    at0 = rm.render_wall_frame(st, scene, sprite_wad=art, sector_lights={th.sector: th.maxlight for th in ths},
                               **GAME_RENDER_KW)
    assert at0 == plain
    assert rm.render_wall_frame(st, scene, sprite_wad=art, sector_lights={}, **GAME_RENDER_KW) == plain
    lit = rm.render_wall_frame(st, scene, sprite_wad=art, sector_lights={th.sector: th.levels[-1] for th in ths},
                               **GAME_RENDER_KW)
    assert sum(p != q for p, q in zip(lit, plain)) > 100, "the animated light did not reach the picture"


def test_every_seg_on_an_animated_light_marks_in_some_state(mw2, ths):
    """the fact the oracle's marking rule rests on: a two-sided seg with an animated light on a side is never skipped,
    because the program marks it in every state once it marks in one -- and it does mark in one"""
    from doomfj.mapcompiler import bake_bsp
    from doomfj.wall_renderer import seg_marks_in
    secs, lds, sds = mw2.sectors("E1M2"), mw2.linedefs("E1M2"), mw2.sidedefs("E1M2")
    lsecs = {th.sector: L.state_secs(secs, th) for th in ths}
    n = 0
    for seg in bake_bsp(mw2, "E1M2").segs:
        ld = lds[seg.linedef]
        if ld.back == -1:
            continue
        sides = {sds[ld.front].sector, sds[ld.back].sector} & set(lsecs)
        if not sides:
            continue
        n += 1
        variants = [sv for s in sides for sv in lsecs[s]]
        assert any(seg_marks_in(lds, sds, seg, sv) for sv in variants), seg
    assert n == 95                                           # E1M2: 95 two-sided segs on animated lights
    # the case the rule exists for: sector 261's flash dims to 160, its neighbours' light, on linedefs 1557 / 1560 -- a
    # seg the old per-state test would skip at state 1, the program marks (it marks at state 0)
    segs = bake_bsp(mw2, "E1M2").segs
    s61 = [sg for sg in segs if sg.linedef in (1557, 1560)]
    dim = L.apply_sector_lights(secs, {261: 160})
    assert s61 and all(not seg_marks_in(lds, sds, sg, dim) and seg_marks_in(lds, sds, sg, secs) for sg in s61)
    # R9: the same check over a "light" pinned to its neighbours' level marks in none -- the check can fail
    assert not any(seg_marks_in(lds, sds, sg, sv) for sg in s61 for sv in [dim])


# ---- the fj side's host half ----------------------------------------------------------------------------------------

def test_the_cells_persist_on_e1m2_only(mw2):
    from doomfj.build import _map_persist
    assert set(LC.PERSIST) <= set(_map_persist(mw2, "E1M2", True))
    assert not set(LC.PERSIST) & set(_map_persist(WadFile.from_path(FIX / "freedoom_e1m1.wad"), "E1M1", True))
    assert LC.map_persist(mw2, "E1M2") == LC.PERSIST


def test_the_declared_cells_are_the_level_start(ths):
    states, counts, r = L.level_start(ths)
    d = LC.decls(ths)
    st, ct, rng = LC.level_start_values(ths)
    assert d[:3] == [f"ltst: hex.vec 9, {st}", f"ltct: hex.vec 18, {ct}", f"rng_lt: hex.vec 2, {rng}"]
    assert [(st >> 4 * k) & 15 for k in range(9)] == states
    assert [(ct >> 8 * k) & 255 for k in range(9)] == counts and rng == r
    assert LC.level_start_lines(ths) == [f"    hex.set 9, ltst, {st}", f"    hex.set 18, ltct, {ct}",
                                         f"    hex.set 2, rng_lt, {rng}"]


def test_the_leaf_bases_reach_every_light_state(ths, mw2):
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import reachable_lightnums
    rm = ReferenceModel()
    secs = mw2.sectors("E1M2")
    extra = sorted({v for th in ths for v in th.levels})
    got = reachable_lightnums(rm, secs, extra)
    assert set(got) >= {rm.wall_lightnum(v, 0) for v in extra}
    assert reachable_lightnums(rm, secs) == sorted({rm.wall_lightnum(s.light, 0) for s in secs})


def test_the_light_phase_runs_in_the_world_tics_loop():
    from doomfj.wall_renderer import p5_tic_lines, world_tic_lines
    hrt = {"bar": ["    // the bar"]}
    plain, lit = p5_tic_lines(hrt), p5_tic_lines(hrt, lights=True)
    assert [ln for ln in lit if ln != LC.TIC_CALL] == plain                # E1M1: no text
    assert lit[lit.index("stl.fcall fx_phase, fx_pret") + 1] == LC.TIC_CALL
    tic = ["mt_tic:", "  mt_skip:", "    hex.zero 53, thseen"]
    loop = world_tic_lines(tic, lit, 2)
    assert loop.index(LC.TIC_CALL) < loop.index("    hex.dec 1, wt_rep")    # inside the loop: twice a frame
