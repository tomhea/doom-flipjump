"""M7 P8a package C (host): THE COMPOSITOR RULES D3 a and D3 b (docs/gp-final-plan.md 1.3) -- the oracle's side and the
emitter's bindings. The fj's side runs on the engine: tests/fj/test_thing_pass_depth_fj.py (the rank, the barrel flag's
clear) and tests/fj/test_actor_record_fj.py (the record's soft test and count).

  * D3 a (`rt_rank`): within a leaf's runtime list the key is (rank, P_AproxDistance key, index) -- rank 0 for the
    EFFECTS (blood, puffs) and the DROPS, drawn first (in front: a sprite pixel is written once), rank 1 for the monsters,
    live or dead, the fireballs and every other runtime thing. A drop TIES with its corpse on the aprox key and the row
    order used to give the corpse slot A, leaving the drop (scenery, B-gated under 32 rows) invisible in those columns.
  * D3 b (`exempt_barrels`): a BARREL (baked or runtime, every state) keeps its BASE size bound whatever the scenery
    count and does not count; it stays scenery (THING_BUDGET, the B-gate). Projectiles were already exempt -- and more
    -- under the actors rule (`exempt_actors`: a mobile is an actor, no soft raise, no B-gate): nothing to build.
  * Both are GAME_RENDER_KW keys (`rt_rank`, `exempt_barrels` -- package V's names), OFF while the game tier is at
    "full" (blocked51's picture, v6's record) and ON exactly when world.compositor_d3(wall_renderer.PLAYER_MODE) -- the
    P8a player mode "final": the integrator flips them with the mode (the emitter asserts they agree with its `_D3`).
    `game_render_kw(d3)` draws either picture explicitly. deg_gate's visual tier passes neither key.
  * R9 for the gates: rank_off is `rt_rank=False`, barrel_soft `exempt_barrels=False`, rank_swap `rank_depth_key`
    patched to rank 1 - r (proved to part below).

The scenes: v5's R0-courtyard checkpoint facing north (test_actors_rule's), things placed by hand -- a corpse with its
clip on it, a zombieman with blood on it (one leaf, an exact aprox tie), a far runtime barrel behind three near drops.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets/freedoom1.wad"
COURT = (1424, 732, 0x40000000)                  # v5's R0-courtyard checkpoint, facing north across the open yard
SLOT = 9                                         # a zombieman (S_POSS_*), moved where each scene needs him


def _diff(a, b):
    return [i for i, (p, q) in enumerate(zip(a, b)) if p != q]


# ---- the keyword sets and the rule ---------------------------------------------------------------------------------

def test_the_game_pictures_keys_follow_the_mode():
    """GAME_RENDER_KW's two D3 keys are ON exactly when the game tier's player mode takes the rule (so at "full" the
    picture is blocked51's); the hosted tiers' set keeps them off; game_render_kw(d3) sets both, whatever the flip"""
    from doomfj import wall_renderer as WR
    from doomfj.reference_model import D3_RENDER_KW, GAME_RENDER_KW, HOSTED_RENDER_KW, game_render_kw
    from doomfj.world import compositor_d3
    assert D3_RENDER_KW == {"rt_rank": True, "exempt_barrels": True}
    on = compositor_d3(WR.PLAYER_MODE)
    assert GAME_RENDER_KW["rt_rank"] is on and GAME_RENDER_KW["exempt_barrels"] is on, (WR.PLAYER_MODE, on)
    assert HOSTED_RENDER_KW["rt_rank"] is False and HOSTED_RENDER_KW["exempt_barrels"] is False
    for d3 in (False, True):
        kw = game_render_kw(d3)
        assert kw is not GAME_RENDER_KW and kw == dict(GAME_RENDER_KW, rt_rank=d3, exempt_barrels=d3)


def test_deg_gates_keyword_set_is_unchanged():
    """deg_gate (the visual tier: byte-exact AND op counts equal to blocked51's) names none of the P8a picture"""
    src = (ROOT / "scratchpad" / "deg_gate.py").read_text(encoding="utf-8")
    for word in ("rt_rank", "exempt_barrels", "D3_RENDER_KW", "game_render_kw", "GAME_RENDER_KW", "compositor_d3",
                 "HOSTED_RENDER_KW"):
        assert word not in src, word


def test_the_rule_is_the_final_player_modes_alone():
    from doomfj.world import PLAYER_MODES, compositor_d3
    assert [m for m in PLAYER_MODES if compositor_d3(m)] == ["final"]
    with pytest.raises(AssertionError):
        compositor_d3("push")                    # a MONSTER mode: the rule is the player mode's


def test_each_mobile_ranks_by_its_pool():
    """the oracle names a mobile's rank by its LUMP; the fj by its ROW (rows from monstercode.rank_threshold on rank
    0). They agree because every lump the fireball pool can show is BAL1 (rank 1) and every lump the fx pool can show
    (blood, puffs) is BLUD / PUFF (rank 0) -- projcode.pool_states' chains, read here; a drop (z 0) ranks 0"""
    from doomfj import gamedata as gd
    from doomfj.monsters import mobile_lump
    from doomfj.projcode import _info, chain
    from doomfj.reference_model import MOBILE_RANK, mobile_rank
    fire = chain(_info().spawnstate) + chain(_info().deathstate)
    fx = chain("S_BLOOD1") + chain("S_PUFF1")
    assert fire and fx and not set(fire) & set(fx)
    assert {mobile_rank(mobile_lump(s)) for s in fire} == {1}
    assert {mobile_rank(mobile_lump(s)) for s in fx} == {0}
    assert {mobile_lump(s)[:4] for s in fire + fx} == set(MOBILE_RANK)
    assert mobile_rank("CLIPA0", 0) == 0 and mobile_rank("SHOTA0", 0) == 0 and mobile_rank("BAL1A0", None) == 1
    with pytest.raises(AssertionError, match="no pool rank"):
        mobile_rank("CLIPA0")                    # an item that is not a drop has no mobile pool
    assert gd.STATES["S_BLOOD1"].sprite == "BLUD"


def test_the_rank_threshold_is_the_row_layout():
    """rows [nt, nt + FIREBALL_POOL) are the fireball slots (the row select copies pj_st), the rows from
    rank_threshold(nt) the fx slots (fx_st) and then the drops -- so `t >= rank_threshold(nt)` is "an effect or a
    drop", the oracle's rank 0"""
    from doomfj import monstercode as MC
    from doomfj.world import FIREBALL_POOL, FX_POOL
    nt = 37
    rk = MC.rank_threshold(nt)
    assert rk == nt + FIREBALL_POOL
    sel = MC.mobile_select_lines(nt, FIREBALL_POOL + FX_POOL, wake=True, shoot=True)
    stub = {int(ln.strip()[len("thsel_s"):-1]): sel[i + 1] for i, ln in enumerate(sel) if ln.strip().startswith("thsel_s")}
    assert sorted(stub) == list(range(nt, nt + FIREBALL_POOL + FX_POOL))
    assert all(("pj_st" in v) == (t < rk) and ("fx_st" in v) == (t >= rk) for t, v in stub.items()), stub
    drops = MC.drop_select_lines(nt + FIREBALL_POOL + FX_POOL, [5, 6], wake=True, shoot=True)
    assert min(int(ln.strip()[len("thsel_s"):-1]) for ln in drops if ln.strip().startswith("thsel_s")) >= rk


def test_the_runtime_barrel_select_flags_the_barrel():
    """D3 b's runtime half: the stub SETS sp_ex in every state (ex=True); without the rule its text is blocked51's"""
    from doomfj import monstercode as MC
    off = MC.barrel_select_lines(40, 1, nmon=53, shoot=True)
    on = MC.barrel_select_lines(40, 1, nmon=53, shoot=True, ex=True)
    assert "sp_ex" not in "\n".join(off)
    assert [ln for ln in on if ln not in off] == ["    hex.set 1, sp_ex, 1"] and len(on) == len(off) + 1
    # the flag is set before the view lookup, on the path every state takes (after the standing barrel's aim stub)
    assert on.index("    hex.set 1, sp_ex, 1") > max(i for i, ln in enumerate(on) if ln.startswith("  thsel_b40_v"))


# ---- the pictures ----------------------------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def court():
    if not ART.exists():
        pytest.skip("needs assets/freedoom1.wad (the sprite art)")
    from doomfj.config import GAME_CFG
    from doomfj.monsters import MonsterPhase, MonsterViews
    from doomfj.reference_model import ReferenceModel, SimState, build_scene, game_render_kw
    from doomfj.wad import WadFile
    art = WadFile.from_path(str(ART))
    ph = MonsterPhase(mode="full", player="full")
    w, ws = ph.world, ph.world.ws
    ws.px, ws.py, ws.pangle = COURT[0] << 16, COURT[1] << 16, COURT[2]
    rm = ReferenceModel(GAME_CFG)
    mv = MonsterViews(rm, w.mw, w.mapname, art, w)
    sc = build_scene(w.mw, w.mw, w.mapname)
    st = SimState(ws.px, ws.py, ws.pangle, w.mapname)
    home = (ws.mon_x[SLOT], ws.mon_y[SLOT])

    def render(at=None, state=None, positions=None, things_out=None, **kw):
        """the court picture at the P8a game keywords (`kw` overrides), the zombieman at `at` (else home) in `state`"""
        from doomfj import gamedata as gd
        ws.mon_x[SLOT], ws.mon_y[SLOT] = at or home
        ws.mon_state[SLOT] = gd.STATE_INDEX[state or "S_POSS_STND"]
        try:
            return bytes(rm.render_wall_frame(st, sc, sprite_wad=art, thing_views=mv(ph, ws.px, ws.py),
                                              thing_positions=positions or mv.positions(ph), things_out=things_out,
                                              **dict(game_render_kw(True), **kw)))
        finally:
            ws.mon_x[SLOT], ws.mon_y[SLOT] = home
            ws.mon_state[SLOT] = gd.STATE_INDEX["S_POSS_STND"]
    render.rm, render.sc, render.mv, render.ph = rm, sc, mv, ph
    return render


def _in_front(court, mob, state):
    """(pixels of the mobile alone, how many of them the scene keeps with the zombieman ON it -- ranked, and not)"""
    at = (mob[0][0], mob[0][1])
    alone = court(mobiles=mob)                       # the zombieman at home, out of this view
    fp = _diff(alone, court())
    ranked = court(at=at, state=state, mobiles=mob)
    plain = court(at=at, state=state, mobiles=mob, rt_rank=False)
    return fp, sum(ranked[i] == alone[i] for i in fp), sum(plain[i] == alone[i] for i in fp)


def test_a_drop_is_drawn_before_its_corpse(court):
    """D3 a: a dead zombieman 150 units up the yard with his clip ON him (an exact aprox tie; the corpse's row first):
    ranked, every pixel of the clip shows; unranked (blocked51's rule), the corpse takes slot A and the clip, scenery
    under 32 rows, is B-gated out of those columns -- the R9 control: the scene is one the rank decides"""
    at = (COURT[0], COURT[1] + 150)
    fp, ranked, plain = _in_front(court, [(at[0], at[1], "CLIPA0", 0)], "S_POSS_DIE5")
    assert len(fp) >= 20 and ranked == len(fp), (len(fp), ranked)
    assert plain < len(fp) - 10, (len(fp), plain)


def test_blood_is_drawn_before_its_monster(court):
    """D3 a: blood ON a live zombieman (32 units up his body): ranked, all of it shows in front of him; unranked his
    sprite covers it -- the R9 control"""
    at = (COURT[0], COURT[1] + 150)
    fp, ranked, plain = _in_front(court, [(at[0], at[1], "BLUDA0")], "S_POSS_STND")
    assert len(fp) >= 15 and ranked == len(fp), (len(fp), ranked)
    assert plain < len(fp) // 2, (len(fp), plain)


def test_control_the_swapped_rank_parts(court, monkeypatch):
    """R9 for the gates (V's rank_swap): `rank_depth_key` patched to rank 1 - r -- the monsters drawn before the effects
    -- hides the blood behind its zombieman again; a gate's oracle mutation is exactly this patch"""
    from doomfj import reference_model as RM
    at = (COURT[0], COURT[1] + 150)
    blood = [(at[0], at[1], "BLUDA0")]
    good = court(at=at, mobiles=blood)
    orig = RM.rank_depth_key
    monkeypatch.setattr(RM, "rank_depth_key", lambda vx, vy, x, y, r: orig(vx, vy, x, y, 1 - r))
    swapped = court(at=at, mobiles=blood)
    assert swapped != good and swapped == court(at=at, mobiles=blood, rt_rank=False)


def test_a_fireball_still_sorts_with_the_monsters(court):
    """a FIREBALL is rank 1: on the zombieman the rank changes nothing (both rank 1, the aprox tie, the row order)"""
    at = (COURT[0], COURT[1] + 150)
    mob = [(at[0], at[1], "BAL1A0")]
    assert court(at=at, mobiles=mob) == court(at=at, mobiles=mob, rt_rank=False)


def test_rt_rank_needs_the_aprox_walk(court):
    for order in (False, "tz"):
        with pytest.raises(AssertionError, match="rt_rank"):
            court(rt_depth_order=order)


def _far_barrel(court):
    from doomfj.reference_model import BARREL_TYPE
    mv = court.mv
    b = next(i for i, t in enumerate(mv.drawable) if t.type == BARREL_TYPE and i in mv.rt_drawable)   # a RUNTIME one
    pos = list(mv.positions(court.ph))
    home = pos[b]
    pos[b] = (COURT[0] + 20, COURT[1] + 450)
    return pos, home, b


def test_a_far_barrel_after_three_scenery_things_is_drawn(court):
    """D3 b: a runtime barrel 450 units up the yard (~5 rows), three clips on the floor in front of it (near scenery,
    accepted first): exempt, it is drawn; blocked51's rule raises it to DEG_MINH2_SCENERY (24 rows) and drops it. R9
    control: with the soft count out of reach (255) the old rule draws it too -- the count is what hid it"""
    from doomfj.reference_model import DEG_MINH2_MON, DEG_MINH2_SCENERY, DEG_SOFT_MON
    pos, home, b = _far_barrel(court)
    gone = list(pos)
    gone[b] = home
    clips = [(COURT[0] - 40 + 25 * k, COURT[1] + 90 + 10 * k, "CLIPA0", 0) for k in range(3)]
    on = _diff(court(positions=pos, mobiles=clips), court(positions=gone, mobiles=clips))
    off = _diff(court(positions=pos, mobiles=clips, exempt_barrels=False),
                court(positions=gone, mobiles=clips, exempt_barrels=False))
    assert len(on) >= 8 and not off, (len(on), len(off))
    soft = (255, DEG_MINH2_SCENERY, DEG_SOFT_MON, DEG_MINH2_MON)
    ctl = _diff(court(positions=pos, mobiles=clips, exempt_barrels=False, deg_things=soft),
                court(positions=gone, mobiles=clips, exempt_barrels=False, deg_things=soft))
    assert ctl == on, (len(ctl), len(on))


def test_a_barrel_does_not_count(court):
    """D3 b: a barrel does not count. With the soft count out of reach (255: every visible scenery thing accepted, so
    the count is the number accepted) the accepted scenery count (`things_out`' n_thing) does not move when a near
    runtime barrel comes into view under the rule, and takes one under blocked51's. And in the court as it is (its
    own scenery fills DEG_SOFT_SCENERY) the uncounted barrel leaves a far scenery thing its base bound: the two rules'
    pictures differ beyond the barrel itself"""
    from doomfj.reference_model import DEG_MINH2_MON, DEG_MINH2_SCENERY, DEG_SOFT_MON
    pos, home, b = _far_barrel(court)
    pos[b] = (COURT[0] + 20, COURT[1] + 200)
    gone = list(pos)
    gone[b] = home
    soft = (255, DEG_MINH2_SCENERY, DEG_SOFT_MON, DEG_MINH2_MON)
    counts = {}
    for ex in (True, False):
        for name, p in (("in", pos), ("out", gone)):
            out = []
            court(positions=p, things_out=out, exempt_barrels=ex, deg_things=soft)
            counts[(ex, name)] = out[1]
    assert counts[(True, "in")] == counts[(True, "out")] >= 3, counts
    assert counts[(False, "in")] == counts[(False, "out")] + 1, counts
    assert court(positions=pos) != court(positions=gone), "the near barrel is not in view: the case is vacuous"
    # the court's own load: blocked51's rule hides a far scenery thing behind the counted barrel, D3 b keeps it
    barrel_px = set(_diff(court(positions=pos), court(positions=gone)))
    rest = [i for i in _diff(court(positions=pos), court(positions=pos, exempt_barrels=False)) if i not in barrel_px]
    assert rest, "the counted barrel raised nothing in the court: the picture half is vacuous"


# ---- the emitter's binding (p31_parts at both modes) -----------------------------------------------------------------

@pytest.fixture(scope="module")
def parts():
    if not ART.exists():
        pytest.skip("needs assets/freedoom1.wad (the sprite art)")
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ART))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, WR.MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    rt = [mw.things("E1M1")[w] for w in keep]
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + 64 * i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    kinds = sorted({t.type for t in drawable})
    static = ({k: 0x900 + i for i, k in enumerate(kinds)}, {k: 0xA00 + i for i, k in enumerate(kinds)},
              {k: rm.sprite_art(art, k, cache)[2] for k in kinds})
    out = {}
    for mode, player in (("full", "full"), ("final", "final"), ("push", "final")):
        out[(mode, player)] = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL,
                                           skills=WR.SKILLS, cache=cache, mode=mode, player=player,
                                           static_bank=static)
    out["nt"] = len(rt)
    return out


def test_p31_parts_binds_the_rules_at_the_p8a_player_mode(parts):
    from doomfj import monstercode as MC
    full = parts[("full", "full")]
    assert "d3" not in full and "rank0" not in full
    assert not any("sp_ex" in ln or "td_rk" in ln for ln in full["select"] + full["decls_wake"])
    for key in (("final", "final"), ("push", "final")):
        p = parts[key]
        assert p["d3"] is True and p["rank0"] == MC.rank_threshold(parts["nt"]), key
        assert all(d in p["decls_wake"] for d in MC.D3_DECLS), key
        flagged = [ln for ln in p["select"] if "sp_ex" in ln]
        assert len(flagged) == len(p["bar_rt"]) >= 1, (key, flagged, p["bar_rt"])
