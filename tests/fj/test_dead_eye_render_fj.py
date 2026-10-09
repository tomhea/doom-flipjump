"""M7 P8a A -- THE DEAD-EYE RENDER PRE-GATE (docs/gp-final-plan.md 5.1; O-A1 taken: S0). No game build.

The renderer has only ever drawn an eye at floor + 41. The dying view sinks it to floor + 6 -- floors above the eye
seen from the ground, step faces seen from below their top, ceilings that come down to the eye -- and S0 keeps the
planes' band lists of the STANDING eye while the geometry takes the sunk one. This proves the fj renderer draws exactly
what the oracle's `render_wall_frame(view_drop=d)` draws there, BEFORE any game build depends on it.

THE PROGRAM: the RENDER tier of E1M1 at the game's view (config.GAME_CFG, 84 rows), with the game tier's drop line --
the REAL `wall_renderer.landing_drop_lines()` -- spliced in after its landing (`dsc_done:`), as the game tier's
emitter splices it behind world.player_sinks (the test transplants the emitted text, as test_actor_record_fj does: no
new tier row). `p_vd` is poked per frame through the feed: one byte read right before the drop lines (the harness's
only addition; the game tier reads the persisted cell instead).

THE VIEWPOINTS, found from the WAD's geometry (so they stay where the sink matters): the player start; beside a 24-unit
step (the eye crosses the step's top at d = 17); below a ledge (a floor 64 above: above even the standing eye); on a
ledge's edge looking down (the lower floor the edge hides more of as the eye sinks); inside lift 98's leaf (the render
tier holds it at its stored height); under the lowest ceiling a player fits beneath (64 units: the eye's distance to it
changes the most). Each at d in {0, 1, 17, 35}: d 0 is the transplant's own check (the picture without the sink).

R9 (oracle mutations, each must PART from the fj's sunk picture on some viewpoint):
  * `bands_sunk`  -- the split removed for the planes (the oracle's eye class itself sunk: DOOM's exact planes);
  * `geo_standing` -- the geometry from the standing eye (view_drop 0).
and the fj's sunk picture must differ from its own d = 0 picture (the drop drew something).

HEAVY (the render tier's emission is minutes and its assembly a few GB): run it solo (CLAUDE.md rule 1).
"""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.config import GAME_CFG
from doomfj.fixedpoint import _signed
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile
from doomfj.wall_renderer import emit_wall_renderer, landing_drop_lines
from doomfj.wireformat import encode_feed_mapunits

from tests.fj.stream_screen import StreamScreen

ROOT = Path(__file__).resolve().parents[2]
SRC = [ROOT / "src" / "fj" / f for f in
       ("fixed_point.fj", "present.fj", "projection.fj", "frame_render.fj", "plane_render.fj",
        "plane_bands.fj", "stream_render.fj")]
E1M1_WAD = ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"
CFG = GAME_CFG
DROPS = (0, 1, 17, 35)
# the render tier's picture (tests/fj/test_lines_render.py's E1M1 keywords: the renderer's only behaviour)
# (the forced keys -- sky, near_steps, stack_steps, bbox_cull, degrade -- are written at each call, where
# tests/host/test_oracle_calls_in_step.py reads them)
KW = dict(floor_texturing=False, wall_mode="W1R", floor_mode_ft1=True, wall_noise=True, plane_near=True)
LIFT = 98


def _transplant(text: str) -> str:
    """the render tier with the game's drop line after its landing, `p_vd` read from the feed right before it"""
    lines = text.split("\n")
    at = [i for i, ln in enumerate(lines) if ln.strip() == "dsc_done:"]
    assert len(at) == 1, "the render tier must have exactly one landing (dsc_done:), has %d" % len(at)
    drop = landing_drop_lines()
    assert drop and any("p_vd" in ln for ln in drop), drop
    lines[at[0] + 1:at[0] + 1] = ["hex.input 1, p_vd", *drop]
    assert "p_vd:" not in text
    return "\n".join(lines) + "\np_vd: hex.vec 2, 0\n"


def _viewpoints(mw, rm, scene):
    """[(name, x, y, angle)] in whole map units, each checked to stand in the sector it names"""
    from doomfj.doors import door_states
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    cmap = scene.cmap
    vs = cmap.vertexes
    doors = set(door_states(secs, lds, sds))

    def sector_at(x, y):
        sg = cmap.segs[cmap.subsectors[rm.point_in_subsector(cmap, x, y)].firstseg]
        ld = lds[sg.linedef]
        return sds[ld.front if sg.side == 0 else ld.back].sector

    def facing(x, y, tx, ty):
        return rm.point_to_angle(x << 16, y << 16, tx << 16, ty << 16)

    def beside(df_want, side, dist=(24, 32, 40, 48, 64)):
        """a two-sided line whose floors differ by df_want (no door): the eye `dist` units off its middle on the
        LOW side ("low") or the HIGH side ("high"), facing the line"""
        for ld in lds:
            if ld.back == -1:
                continue
            a, b = sds[ld.front].sector, sds[ld.back].sector
            if a in doors or b in doors or secs[b].floor_h - secs[a].floor_h not in (df_want, -df_want):
                continue
            lo, hi = (a, b) if secs[a].floor_h < secs[b].floor_h else (b, a)
            want = lo if side == "low" else hi
            (x1, y1), (x2, y2) = vs[ld.v1], vs[ld.v2]
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2
            ln = max(1.0, ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5)
            if ln < 48:
                continue
            nx, ny = (y2 - y1) / ln, -(x2 - x1) / ln          # the front side's normal (right of v1 -> v2)
            for d in dist:
                for sgn in (1, -1):
                    x, y = round(mx + sgn * nx * d), round(my + sgn * ny * d)
                    if sector_at(x, y) == want and secs[want].ceil_h - secs[want].floor_h >= 56:
                        return x, y, facing(x, y, mx, my)
        raise AssertionError("no %d-unit step with a %s side to stand on" % (df_want, side))

    def inside(si):
        for s, ss in enumerate(cmap.subsectors):
            pts = [vs[cmap.segs[ss.firstseg + k].v1] for k in range(ss.numsegs)]
            if len(pts) < 3:
                continue
            x, y = round(sum(p[0] for p in pts) / len(pts)), round(sum(p[1] for p in pts) / len(pts))
            if rm.point_in_subsector(cmap, x, y) == s and sector_at(x, y) == si:
                return x, y
        raise AssertionError("no leaf of sector %d to stand in" % si)

    sp = spawn_state(mw, "E1M1")
    out = [("spawn", _signed(sp.x, 32) >> 16, _signed(sp.y, 32) >> 16, sp.angle)]
    out.append(("step24", *beside(24, "low")))
    out.append(("below-ledge64", *beside(64, "low")))
    out.append(("ledge64-edge", *beside(64, "high")))
    lx, ly = inside(LIFT)
    out.append(("lift%d" % LIFT, lx, ly, 0x20000000))
    low = min((s.ceil_h - s.floor_h, i) for i, s in enumerate(secs)
              if i not in doors and s.ceil_h - s.floor_h >= 56)[1]
    cx, cy = inside(low)
    out.append(("lowceil%d" % low, cx, cy, 0x60000000))
    for name, x, y, a in out:
        assert sector_at(x, y) is not None, name
    return out


@pytest.fixture(scope="module")
def rig(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("deadeye")
    mw = WadFile.from_path(str(E1M1_WAD))
    rm = ReferenceModel(CFG)
    scene = build_scene(mw, mw, "E1M1")
    main = _transplant(emit_wall_renderer(mw, "E1M1", CFG, tier="render"))
    consts = CFG.emit_fj_consts(tmp / "fj_consts.fj")
    p = tmp / "deadeye.fj"
    p.write_text(main, encoding="utf-8")
    out = tmp / "deadeye.fjm"
    fj.assemble([consts.resolve(), *[s.resolve() for s in SRC], p.resolve()], out, memory_width=W, print_time=False)
    from doomfj.fastrun import FjmRunner
    runner = FjmRunner(out, flat_max_words=1 << 26)
    return dict(mw=mw, rm=rm, scene=scene, runner=runner, vps=_viewpoints(mw, rm, scene))


def _fj_frame(rig, x, y, a, d):
    screen = StreamScreen(stdin=encode_feed_mapunits(x, y, a) + bytes([d]))
    ops = rig["runner"].run(screen)
    return bytes(screen.pixel_indices), ops


def _oracle(rig, x, y, a, d, mutate=None):
    rm = rig["rm"]
    st = SimState(x << 16, y << 16, a, "E1M1")
    if mutate == "bands_sunk":                     # DOOM's exact planes: the eye class itself sunk, no split
        rm.view_z = lambda f, _d=d: ReferenceModel.view_z(f) - (_d << 16)
        try:
            return bytes(rm.render_wall_frame(st, rig["scene"], sky=True, near_steps=True, stack_steps=True, bbox_cull=True,
                                          degrade=True, **KW))
        finally:
            del rm.view_z
    if mutate == "geo_standing":
        return bytes(rm.render_wall_frame(st, rig["scene"], sky=True, near_steps=True, stack_steps=True, bbox_cull=True,
                                          degrade=True, **KW))
    return bytes(rm.render_wall_frame(st, rig["scene"], view_drop=d, sky=True, near_steps=True, stack_steps=True,
                                      bbox_cull=True, degrade=True, **KW))


def test_the_sunk_eye_renders_as_the_oracle(rig):
    bad, parted = [], {"bands_sunk": 0, "geo_standing": 0}
    drew = 0
    for name, x, y, a in rig["vps"]:
        base = None
        for d in DROPS:
            got, ops = _fj_frame(rig, x, y, a, d)
            want = _oracle(rig, x, y, a, d)
            npx = sum(g != w for g, w in zip(got, want))
            print("[dead-eye] %-14s (%5d,%5d) %#010x d %2d: %s, %d ops"
                  % (name, x, y, a, d, "EXACT" if got == want else "%d px differ" % npx, ops))
            if got != want:
                bad.append((name, d, npx))
            if d == 0:
                base = got
                continue
            drew += got != base
            for m in parted:
                parted[m] += got != _oracle(rig, x, y, a, d, mutate=m)
    assert not bad, "the fj's sunk eye differs from the oracle's: %s" % bad
    assert drew >= len(rig["vps"]) * (len(DROPS) - 1) - 2, "the drop drew nothing on %d frames" % (
        len(rig["vps"]) * (len(DROPS) - 1) - drew)
    assert all(parted.values()), "an oracle mutation the fj agreed with everywhere (vacuous): %s" % parted
