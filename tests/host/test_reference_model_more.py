"""Oracle properties the byte-exactness gates CANNOT reach, or reach only by accident.

`src/doomfj/reference_model.py` is one half of a mirror: the fj emitter bakes the SAME rules, so a
gate that renders both halves and finds them equal proves AGREEMENT, not correctness -- the exact
warning `test_door_occlusion` opens with. Everything pinned here is a rule where a regression would
be invisible to a gate, because the gate compares the two mirrors to each other:

  * the BBOX WEDGE CULL (`render_wall_frame(bbox_cull=True)`, `bsp_render_order(bbox_gate=)`).
    Its whole licence is "this subtree provably cannot be seen". A wrong sign in `bbox_wedge_miss`
    deletes visible geometry in BOTH mirrors identically. Pinned as: the cull moves no pixel, and
    it REMOVES without REORDERING (front-to-back order is what makes solid-seg clipping correct).
  * the V5 piece store's off-screen guard (`steps_out`, `stack_steps=True`). An invisible piece
    used to consume one of the two V5_STACK slots and evict a visible door lintel (measured
    38 -> 405 px on E1M1 door 100). Reverting BOTH mirrors restores the bug silently.
  * Route C's texture pick: a shut two-sided line wears its `upper`, not its `middle`. Occlusion
    (which test_door_occlusion pins) survives the regression untouched; the door just turns into a
    featureless slab -- "doors are invisible" in another disguise.
  * `try_move`'s two post-`check_position` refusals (opening shorter than the player, step taller
    than MAX_STEP). `src/fj/sim.fj` implements both on MAP-UNIT operands while the oracle compares
    16.16; a units slip makes the mirrors disagree about which moves are legal, and the sim gates
    are CUMULATIVE, so one divergent tic parts every later frame.
  * the shared block-FP kernels `_slope_div`, `_scale_recip_div`, `scale_from_global_angle` and the
    sky-column split `sky_base`/`sky_col_off`/`sky_texel_u`. The fj macros (`slope_div`,
    `proj.scale_recip_div`, the baked sky bank) mirror THESE; several of their branches are
    unreachable from real 16.16 geometry, so no gate frame can ever execute them. Mirror-insurance,
    stated honestly as such.
  * the small defensive rules a picture would show but no assertion would: the SPR-NEAR feet clamp,
    the sky-ceiling upper suppression, the 4096-byte flat pad, and the `thing_hidden` host guard.

Nothing here builds or assembles a program -- every check runs against the Python oracle on the
committed fixtures. The fj halves of these mirrors are out of scope (they need deg_gate/m5_gate).
"""
import dataclasses
import math

import pytest

from doomfj.config import Config
from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.mapcompiler import (_point_side, bake_bsp, bbox_gate_boxes,
                                thing_live_subsectors)
from doomfj.reference_model import (
    ANG180, ANGLE_MASK, CLIPANGLE, MAX_STEP, PLAYER_HEIGHT, SCALE_MAX, SCALE_MIN, SKY_TURN,
    SLOPERANGE, WALL_BG, ReferenceModel, Scene, SimState, spawn_state,
)
from doomfj.wad import WadFile

E1M1 = "tests/fixtures/freedoom_e1m1.wad"
ASSETS = "tests/fixtures/freedoom_assets.wad"
SQUARE = "tests/fixtures/square_room.wad"
U = 1 << 16

# The shipped picture tier (the same kwargs test_door_occlusion renders with), so what these tests
# measure is what the game actually draws rather than a configuration nothing builds.
RENDER = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True,
              near_steps=True, stack_steps=True, degrade=True)


@pytest.fixture(scope="module")
def rm():
    return ReferenceModel()


@pytest.fixture(scope="module")
def level():
    """(map wad, asset wad, cmap) for E1M1, baked once.

    WARNING: `tests/fixtures/freedoom_assets.wad` holds only TWO TEXTURE1 defs, so a door's `upper`
    does NOT resolve through it. The map wad carries the full TEXTURE1 (plus PLAYPAL/COLORMAP),
    which is why `test_door_occlusion` passes the map wad as the asset wad too; the Route C test
    below does the same and says so at its call site."""
    mw = WadFile.from_path(E1M1)
    return mw, WadFile.from_path(ASSETS), bake_bsp(mw, "E1M1")


@pytest.fixture(scope="module")
def scene(level):
    mw, aw, cmap = level
    return Scene(mw, aw, "E1M1", cmap, None, frozenset())


def _views(st):
    """A handful of viewpoints around the player start: a few steps in each direction and a few
    facings, so a cull tested here is tested against more than one wedge."""
    return [SimState(x=st.x + (dx << 16), y=st.y + (dy << 16),
                     angle=(st.angle + da) & 0xFFFFFFFF, level="E1M1")
            for dx, dy, da in ((0, 0, 0), (0, 0, 1 << 30), (0, 0, 1 << 31),
                               (64, 0, 0), (-64, 32, 3 << 30), (0, -64, 1 << 29))]


# -- the bbox wedge cull: it may remove, it may not change the picture -------------------------

def test_the_wedge_cull_moves_no_pixel(rm, level, scene):
    """`bbox_cull=True` must be a pure cost reduction: byte-identical frames at every viewpoint.

    A wrong sign in `bbox_wedge_miss`, a stale `bbox_gate_boxes`, or a `thing_live_subsectors` that
    stops covering a subtree all silently DELETE visible geometry -- and since the fj emitter bakes
    the same gate, both mirrors would agree on the wrong picture. The control in the next test is
    what stops this passing vacuously: the gate has to actually be skipping subtrees."""
    mw, aw, _cmap = level
    st = spawn_state(mw, "E1M1")
    for s in _views(st):
        plain = rm.render_wall_frame(s, scene, things=True, sprite_wad=aw, **RENDER)
        culled = rm.render_wall_frame(s, scene, things=True, sprite_wad=aw,
                                      bbox_cull=True, **RENDER)
        assert culled == plain, (
            "%d px moved when the wedge cull was turned on at (%d,%d) angle %#x"
            % (sum(1 for a, b in zip(plain, culled) if a != b),
               s.x >> 16, s.y >> 16, s.angle))


def test_the_wedge_gate_removes_but_never_reorders(rm, level):
    """THE CONTROL for the pixel test above, and a different failure in its own right.

    Front-to-back order is what makes the per-column `drawn[x]` solid-seg clipping correct. A gate
    that pushed near/far in the wrong branch would still produce a plausible frame -- with far
    walls painted over near ones -- and at a sampled viewpoint that can even be invisible, so the
    pixel test would pass. 'The cull touched only MEMBERSHIP' is exactly the statement that the
    gated order is a SUBSEQUENCE of the ungated one.

    R9 (2026-09-11): the subsequence claim alone is RELATIVE -- it compares `bsp_render_order` to
    itself. Swapping `bsp_render_order`'s own near/far selection (the one-character `if back else`
    slip, which is the defect the paragraph above names) reverses BOTH walks, so the gated one
    stays a subsequence of the ungated one and this test passed on the mutant. The anchor below is
    the ABSOLUTE half: the eye's own subsector is the nearest thing in the level, so a nearest-
    first walk visits it FIRST and no wedge cull may ever drop it. `point_in_subsector` descends
    the BSP with its own copy of the side rule, so it is an independent witness, not a restatement
    of the function under test."""
    mw, _aw, cmap = level
    secs, lds, sds = mw.sectors("E1M1"), mw.linedefs("E1M1"), mw.sidedefs("E1M1")
    gate = bbox_gate_boxes(cmap, thing_subsectors=thing_live_subsectors(cmap, lds, sds, secs))
    assert gate, "bbox_gate_boxes gated no node -- every assertion below would be vacuous"
    st = spawn_state(mw, "E1M1")
    culled_any = False
    for s in _views(st):
        vx, vy = s.x >> 16, s.y >> 16
        plain = rm.bsp_render_order(cmap, vx, vy)
        gated = rm.bsp_render_order(cmap, vx, vy, bbox_gate=gate, va=s.angle,
                                    eye16=(_signed(s.x, 32), _signed(s.y, 32)))
        here = rm.point_in_subsector(cmap, vx, vy)
        assert plain[0] == here, (
            "the ungated walk starts at subsector %d, not the eye's own %d at (%d,%d): it is not "
            "front-to-back" % (plain[0], here, vx, vy))
        assert gated[0] == here, (
            "the gated walk starts at subsector %d, not the eye's own %d at (%d,%d): the cull "
            "either dropped the eye's leaf or reordered the walk" % (gated[0], here, vx, vy))
        walk = iter(plain)
        assert all(ss in walk for ss in gated), (
            "the gated order is not a subsequence of the ungated order at (%d,%d): the cull "
            "REORDERED the front-to-back walk" % (vx, vy))
        culled_any = culled_any or len(gated) < len(plain)
    assert culled_any, "the gate removed nothing at any viewpoint -- the cull is not exercised"


# -- V5: a stored boundary piece is always at least partly on screen ---------------------------

def test_no_boundary_piece_is_stored_entirely_off_screen(rm, level, scene):
    """The V5 piece store's guard `if a <= b and 0 <= b and a <= Hs` (mirrored in
    `src/fj/frame_render.fj` ts_piece_store).

    Before it, a piece that painted nothing still consumed one of the two V5_STACK slots and
    evicted a VISIBLE door lintel -- measured 38 -> 405 px at 344 units on E1M1 door 100. The
    guard keeps every stored piece inside [0, VIEW_H-1], which incidentally makes both `st_`
    sentinel arms -- (1,0) for b < 0 and (255,254) for a > Hs -- dead code; if a sentinel ever
    appears in `steps_out` again, the guard has been reverted on this side of the mirror.

    The stacking control matters: with no column holding two pieces, the eviction this guards
    against cannot occur and the assertion would prove nothing.

    R9 (2026-09-11): THE SPAWN FACING ALONE DOES NOT REACH THE GUARD. Rendered only from
    `spawn_state`, this test passed with the guard reverted to the bare `a <= b` it replaced --
    no boundary at that one view projects off-screen, so nothing was ever rejected and the
    assertions ran on a set the guard had not touched. Measured with the guard reverted over the
    `_views` sweep: the spawn position facing 180 deg stores 54 sentinel pieces and (-64,+32)
    facing 270 deg stores 40, while the spawn facing stores none. The sweep is the test."""
    view_h = Config().VIEW_H
    st = spawn_state(level[0], "E1M1")
    seen = stacked = 0
    for s in _views(st):
        steps = []
        rm.render_wall_frame(s, scene, steps_out=steps, **RENDER)
        assert len(steps) == 1
        ups, los = steps[0]
        columns = list(ups) + list(los)
        pieces = [p for col in columns for p in col]
        seen += len(pieces)
        stacked += max((len(c) for c in columns), default=0) >= 2
        where = "at (%d,%d) angle %#x" % (s.x >> 16, s.y >> 16, s.angle)
        bad = [(y1, y2) for y1, y2, *_ in pieces if not (0 <= y1 <= y2 <= view_h - 1)]
        assert not bad, "pieces stored outside [0,%d] %s: %s" % (view_h - 1, where, bad[:8])
        spans = [(p[0], p[1]) for p in pieces]
        assert (1, 0) not in spans, "the b < 0 sentinel was stored %s" % where
        assert (255, 254) not in spans, "the a > Hs sentinel was stored %s" % where
    assert seen, "no boundary piece was stored at all -- nothing is being checked"
    assert stacked, (
        "no column stacked two pieces at any viewpoint, so a slot cannot be wasted here and this "
        "test is vacuous")


# -- Route C: a shut two-sided line wears its `upper` ------------------------------------------

class _StripUppers:
    """A map-wad proxy whose sidedefs carry no `upper` -- the Route C regression, staged.

    `sd.upper` is read in exactly ONE place in reference_model (the closed-two-sided texture pick),
    so a frame rendered through this proxy is the frame the reverted code would draw, and nothing
    else about the level changes."""

    def __init__(self, wad, mapname, lineids):
        self._wad, self._mapname, self._lines = wad, mapname, lineids

    def __getattr__(self, name):
        return getattr(self._wad, name)

    def sidedefs(self, mapname):
        out = list(self._wad.sidedefs(mapname))
        for ld in (self._wad.linedefs(self._mapname)[i] for i in self._lines):
            for si in (ld.front, ld.back):
                if si != -1:
                    out[si] = dataclasses.replace(out[si], upper="-")
        return out


def _shut_door_lines(mw):
    """Two-sided lines whose BACK sector is shut (ceil == floor) and whose front sidedef has no
    `middle` but a real `upper` -- i.e. every line whose art can only come through Route C."""
    lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
    defs = {d.name.upper() for d in mw.texture_defs("TEXTURE1")}
    out = []
    for li, ld in enumerate(lds):
        if ld.back == -1:
            continue
        back_sec, sd = secs[sds[ld.back].sector], sds[ld.front]
        if back_sec.ceil_h != back_sec.floor_h or sd.middle not in ("-", "", None):
            continue
        if sd.upper in ("-", "", None) or sd.upper.upper() not in defs:
            continue
        out.append(li)
    return out


def _face_the_line(cmap, lds, li, standoff=128):
    """Stand `standoff` units off the line's midpoint on its FRONT side, looking at it. The side
    comes from `mapcompiler._point_side` (DOOM's right = front) rather than from a winding rule
    restated here -- the same construction test_door_occlusion uses."""
    ld = lds[li]
    v1, v2 = cmap.vertexes[ld.v1], cmap.vertexes[ld.v2]
    dx, dy = v2[0] - v1[0], v2[1] - v1[1]
    mx, my = (v1[0] + v2[0]) / 2.0, (v1[1] + v2[1]) / 2.0
    nl = (dx * dx + dy * dy) ** 0.5 or 1.0
    nx, ny = -dy / nl, dx / nl
    for sgn in (1.0, -1.0):
        px, py = int(mx + sgn * nx * standoff), int(my + sgn * ny * standoff)
        if _point_side(v1[0], v1[1], dx, dy, px, py) >= 0:
            continue
        ang = int(math.atan2(my - py, mx - px) / (2 * math.pi) * (1 << 32)) & 0xFFFFFFFF
        return px, py, ang
    return None


def test_a_shut_door_wears_its_upper_not_a_featureless_slab(rm, level):
    """The TEXTURE half of Route C, which `test_door_occlusion` does not cover.

    Revert `_wtex = sd.upper` and the door still occludes perfectly and still passes every existing
    test -- it just renders as one uniform `WALL_BG` flat_fill, because a `middle`-based pick gives
    `tex is None` for a line whose middle is '-'. So the measurement is: strip the `upper` off that
    one line and re-render. Every pixel that changes is a pixel the door's texture was painting,
    and in the stripped frame they must all collapse to a SINGLE constant -- the featureless slab
    the owner would see. This also guards the `wall_renderer._seg_dual` mirror, which has to choose
    the same texture per door state.

    The map wad is passed as the asset wad because the cut-down assets fixture has only two
    TEXTURE1 defs; the door texture would not resolve through it."""
    mw, _aw, cmap = level
    lds = mw.linedefs("E1M1")
    lines = _shut_door_lines(mw)
    assert lines, "no shut two-sided line with middle '-' and a real upper -- nothing to test"
    view = next(((li, v) for li in lines
                 for v in [_face_the_line(cmap, lds, li)] if v is not None), None)
    assert view is not None, "no usable viewpoint onto a shut door line"
    li, (px, py, ang) = view
    upper = mw.sidedefs("E1M1")[lds[li].front].upper
    st = SimState(x=px << 16, y=py << 16, angle=ang, level="E1M1")
    real = Scene(mw, mw, "E1M1", cmap, None, frozenset())
    stripped = Scene(_StripUppers(mw, "E1M1", [li]), mw, "E1M1", cmap, None, frozenset())
    f_real = rm.render_wall_frame(st, real, **RENDER)
    f_slab = rm.render_wall_frame(st, stripped, **RENDER)
    moved = [i for i, (a, b) in enumerate(zip(f_real, f_slab)) if a != b]
    assert len(moved) > 500, (
        "line %d's `upper` (%s) reaches only %d px -- either the viewpoint does not see the shut "
        "door or the texture pick no longer uses `upper`" % (li, upper, len(moved)))
    assert len(set(f_slab[i] for i in moved)) == 1, (
        "the stripped frame should paint ONE flat fill over the door band; it painted %d indices"
        % len(set(f_slab[i] for i in moved)))
    assert len(set(f_real[i] for i in moved)) >= 3, (
        "the real frame paints the door with fewer than 3 distinct indices -- that is a slab, not "
        "a texture")


# -- try_move: the two refusals that live past check_position ----------------------------------

def test_a_destination_check_position_accepts_is_still_refused_when_too_short(rm, scene):
    """The `(ceilingz - floorz) << 16 < height` rule -- the only thing stopping the player walking
    into a shut door's zero-height opening or under a crushed ceiling.

    The control is that `check_position` ACCEPTS the destination: without it the refusal could be
    coming from the position test and this would prove nothing about the height rule. And the step
    check is shown NOT to be the refuser, so exactly one rule is under test. `src/fj/sim.fj` runs
    the same test on MAP-UNIT operands (wall_renderer passes height=PLAYER_HEIGHT>>16), so the two
    spellings of one constant must never drift."""
    src, dst = (2474 * U, -44 * U), (2514 * U, -44 * U)
    ok, floorz, ceilingz = rm.check_position(scene, *dst)
    assert ok, "the destination is refused outright -- the height rule is not what is being tested"
    assert (ceilingz - floorz) << 16 < PLAYER_HEIGHT, (
        "the opening (%d) is not shorter than the player (%d map units)"
        % (ceilingz - floorz, PLAYER_HEIGHT >> 16))
    _ok, here_floor, _ceil = rm.check_position(scene, *src)
    assert (floorz - here_floor) << 16 <= MAX_STEP, "the step rule would refuse this move too"
    assert rm.try_move(scene, src[0], src[1], dst[0], dst[1]) is False


def test_a_step_taller_than_max_step_is_refused(rm, scene):
    """The 'too big a step up' rule. Drop it and the player climbs 160-unit ledges like stairs; get
    its sign backwards and real stairs become unclimbable.

    Both controls matter: the destination is a legal position AND its opening is ample, so the only
    thing left to refuse the move is the rise. The reverse move is required to SUCCEED, which is
    what separates a step-up rule from a 'the floors must match' rule. The fj mirror takes
    maxstep=MAX_STEP>>16 in map units while the oracle compares `(floorz - here_floor) << 16`."""
    src, dst = (480 * U, 220 * U), (480 * U, 180 * U)
    ok, floorz, ceilingz = rm.check_position(scene, *dst)
    assert ok, "the destination is refused outright -- the step rule is not what is being tested"
    assert (ceilingz - floorz) << 16 >= PLAYER_HEIGHT, "the opening is not the ample one"
    _ok, here_floor, _ceil = rm.check_position(scene, *src)
    assert (floorz - here_floor) << 16 > MAX_STEP, (
        "the rise (%d) is not taller than MAX_STEP (%d)"
        % (floorz - here_floor, MAX_STEP >> 16))
    assert rm.try_move(scene, src[0], src[1], dst[0], dst[1]) is False
    assert rm.try_move(scene, dst[0], dst[1], src[0], src[1]) is True


# -- wall_x_range: the affine pre-cull is exactly DOOM's span test -----------------------------

def _x_range_without_the_pre_cull(rm, viewx, viewy, viewangle, seg, verts):
    """R_AddLine as DOOM writes it: two point_to_angle calls, the `span >= ANG180` back-face test,
    the tspan frustum clip, angle_to_x. No affine pre-cull. Deliberately a restatement of the
    published algorithm, NOT a copy of the optimisation under test."""
    v1, v2 = verts[seg.v1], verts[seg.v2]
    a1 = rm.point_to_angle(viewx, viewy, v1[0] << 16, v1[1] << 16)
    a2 = rm.point_to_angle(viewx, viewy, v2[0] << 16, v2[1] << 16)
    span = (a1 - a2) & ANGLE_MASK
    if span >= ANG180:
        return None
    rw_angle1 = a1
    a1 = (a1 - viewangle) & ANGLE_MASK
    a2 = (a2 - viewangle) & ANGLE_MASK
    two_clip = 2 * CLIPANGLE
    tspan = (a1 + CLIPANGLE) & ANGLE_MASK
    if tspan > two_clip:
        if ((tspan - two_clip) & ANGLE_MASK) >= span:
            return None
        a1 = CLIPANGLE
    tspan = (CLIPANGLE - a2) & ANGLE_MASK
    if tspan > two_clip:
        if ((tspan - two_clip) & ANGLE_MASK) >= span:
            return None
        a2 = (-CLIPANGLE) & ANGLE_MASK
    x1, x2 = rm.angle_to_x(a1), rm.angle_to_x(a2)
    return None if x1 >= x2 else (x1, x2, rw_angle1)


@pytest.mark.parametrize("wad_path,mapname", [(SQUARE, "MAP01"), (E1M1, "E1M1")])
def test_the_affine_back_face_pre_cull_is_exactly_dooms_span_test(rm, wad_path, mapname):
    """perf #10 replaced two `point_to_angle` calls with one signed affine distance and asserts in
    a COMMENT that the swap is byte-exact. This is that claim's missing test.

    A wrong sign or scale in `seg_affine_coeffs` either culls front-facing walls (they vanish) or
    admits back faces (they paint over the room) -- and only against an independent implementation
    of the rule it replaced can you tell. It also explains honestly why `span >= ANG180 -> None` is
    unreachable in the shipped function: the pre-cull always fires first."""
    mw = WadFile.from_path(wad_path)
    cmap = bake_bsp(mw, mapname)
    st = spawn_state(mw, mapname)
    verts, segs = cmap.vertexes, cmap.segs
    step = max(1, len(segs) // 200)
    triples = visible = 0
    for si in range(0, len(segs), step):
        seg = segs[si]
        for dx, dy in ((0, 0), (96, 0), (-96, 64)):
            vx, vy = st.x + (dx << 16), st.y + (dy << 16)
            for k in range(8):
                va = (st.angle + k * (1 << 29)) & 0xFFFFFFFF
                triples += 1
                got = rm.wall_x_range(vx, vy, va, seg, verts)
                want = _x_range_without_the_pre_cull(rm, vx, vy, va, seg, verts)
                assert got == want, (
                    "seg %d from (%d,%d) facing %#x: pre-cull says %r, DOOM's span test says %r"
                    % (si, vx >> 16, vy >> 16, va, got, want))
                visible += got is not None
    assert visible > 20, (
        "only %d of %d triples produced a visible seg -- an all-None sweep would agree trivially"
        % (visible, triples))


# -- the sky: one decomposition, two consumers -------------------------------------------------

def _sky_width(rm, mw):
    """SKY1's texture width AFTER the oracle's downscale -- the `tw` every sky helper is indexed
    by. Read from TEXTURE1 rather than hard-coded, so a different fixture still tests the rule."""
    d = {x.name.upper(): x for x in mw.texture_defs("TEXTURE1")}["SKY1"]
    return d.width // rm.downscale


def test_sky_texel_is_exactly_base_plus_column_offset(rm, level):
    """The identity the fj sky bank rests on:

        sky_texel(va, x, y) == sky_texel_u((sky_base(va) + sky_col_off(x)) & (tw-1), y)

    `wall_renderer` bakes the sky bank from `sky_texel_u` (one run-list per texture column) and the
    per-column skyoff table from `sky_col_off`, while the oracle's frame path calls `sky_texel`.
    These are the two halves of one mirror. Move the split -- carry the add before the shift
    instead of after, say -- and every sky column in the shipped binary shifts while the oracle
    keeps its own answer, a divergence that only surfaces at gate time on a full E1M1 build."""
    mw = level[0]
    cfg, cache = Config(), {}
    tw = _sky_width(rm, mw)
    assert tw > 1, "SKY1 did not resolve; the loop below would compare CEIL_BG to itself"
    checked = 0
    for i in range(23):
        va = (i * ((1 << 32) // 23)) & 0xFFFFFFFF
        for x in range(0, cfg.VIEW_W, 7):
            u = (rm.sky_base(va, tw) + rm.sky_col_off(x, tw)) & (tw - 1)
            for y in range(0, cfg.VIEW_H, 13):
                checked += 1
                assert rm.sky_texel(mw, cache, va, x, y) == rm.sky_texel_u(mw, cache, u, y), (
                    "the sky split disagrees at va=%#x x=%d y=%d (u=%d)" % (va, x, y, u))
    assert checked > 1000


def test_the_sky_scrolls_sky_turn_widths_per_full_turn(rm, level):
    """`_sky_shift` is an off-by-one thicket (`32 - tw.bit_length() + 1 - SKY_TURN.bit_length() + 1`)
    and no test reads it. One step wrong and the sky scrolls at half or double speed, or wraps
    mid-turn -- a look bug with no byte-level tripwire, because both mirrors read the same helper
    and would drift together against the intended design rather than against each other.

    The design is stated directly instead: over one full turn `sky_base` visits every one of `tw`
    columns, ascends by exactly one column per step, and completes SKY_TURN cycles. That fixes the
    shift uniquely, which is the point."""
    tw = _sky_width(rm, level[0])
    steps = tw * SKY_TURN
    bases = [rm.sky_base((i * ((1 << 32) // steps)) & 0xFFFFFFFF, tw) for i in range(steps)]
    assert set(bases) == set(range(tw)), "sky_base does not cover every texture column"
    assert len(bases) // len(set(bases)) == SKY_TURN, "the sky does not cycle SKY_TURN times"
    off_by_one = sum(1 for a, b in zip(bases, bases[1:] + bases[:1]) if b != (a + 1) % tw)
    assert off_by_one == 0, "the sky does not advance exactly one column per 1/%d turn" % steps
    # ... and it is a pure function of the TOP bits: a whole run of low bits shares one base.
    run = (1 << 32) // steps
    va = 7 * run
    assert rm.sky_base(va, tw) == rm.sky_base(va + run - 1, tw)
    assert rm.sky_base(va, tw) != rm.sky_base(va + run, tw)


# -- SPR-NEAR: a too-near sprite plants its feet ------------------------------------------------

def test_a_too_near_sprite_plants_its_feet(rm):
    """`ytop_r += h - VIEW_H` is the SPR-NEAR compensation. Delete it and `h` still clamps, so the
    sprite still draws -- but its bottom snaps up to `ytop + VIEW_H` and a monster walking toward
    the player visibly slides UPWARD off the floor at close range. The emit clips the off-screen
    part on the same assumption, so both mirrors would render the same wrong thing.

    Stated as the property rather than as the line: the bottom row stays where the thing's FEET
    project (recomputed here from the depth alone, off the projection path), across the clamp
    boundary, and it keeps descending as the thing approaches. No wad needed -- `art` is just the
    seven leading fields the projection reads."""
    cfg = Config()
    art = (None, 64, 64, 64, 64, 32, 64)   # cols, dh, dw, wpx, wph, left, top
    viewz = 41 * U                         # eye a player-height above the sprite's floor
    bottoms, clamped = [], 0
    for tz_units in range(60, 25, -2):
        got = rm.project_thing(0, 0, 0, viewz, tz_units, 0, 0, art)
        assert got is not None, "tz=%d was rejected; the sweep must stay in the draw range" % tz_units
        _x1, _x2, ytop, h, _istep, tz = got
        assert h <= cfg.VIEW_H, "h=%d exceeds VIEW_H at tz=%d" % (h, tz_units)
        clamped += h == cfg.VIEW_H
        # Where the FEET land, from the depth alone: CENTERY - (feet_z - viewz) * xscale.
        xscale = rm._scale_recip_div(cfg.PROJECTION << 16, tz)
        foot = ((cfg.CENTERY << 16)
                - _signed(fixed_mul((0 - viewz) & ANGLE_MASK, xscale, 8, 4), 32)) >> 16
        assert abs((ytop + h) - foot) <= 1, (
            "tz=%d: the sprite's bottom row %d is %d px off its feet (%d)"
            % (tz_units, ytop + h, (ytop + h) - foot, foot))
        bottoms.append(ytop + h)
    assert clamped >= 6, "the sweep never entered the clamp -- SPR-NEAR is not being exercised"
    assert all(a < b for a, b in zip(bottoms, bottoms[1:])), (
        "the bottom row does not descend monotonically as the thing approaches: %s" % bottoms)


# -- v5_side_modes: nothing may draw lines in the sky -------------------------------------------

class _Sec:
    """A duck-typed sector stand-in -- `v5_side_modes` reads five fields and no wad."""

    def __init__(self, ceil_h, floor_h, ceil_tex="AQF054", floor_tex="AQF054", light=160):
        self.ceil_h, self.floor_h = ceil_h, floor_h
        self.ceil_tex, self.floor_tex, self.light = ceil_tex, floor_tex, light


def test_both_upper_modes_are_suppressed_between_two_sky_ceilings(rm):
    """CR-2026-08's fix: BOTH upper modes, not just the LIP. A RISER between two F_SKY1 ceilings is
    a face floating in the open sky, and DOOM's own sky hack skips the upper entirely.

    The regression is one dropped condition and costs nothing at emit time, so only the picture
    shows it. The four non-suppressed rows are the control: they prove each pair really does
    produce an upper piece when the sky rule does not apply, so a (0, 0) above means suppression
    rather than 'there was never an upper here'."""
    riser = (_Sec(200, 0, "F_SKY1"), _Sec(120, 0, "F_SKY1"))     # front ceiling HIGHER = riser
    lip = (_Sec(120, 0, "F_SKY1"), _Sec(200, 0, "F_SKY1"))       # front ceiling LOWER  = lip
    assert rm.v5_side_modes(*riser, True) == (0, 0)
    assert rm.v5_side_modes(*lip, True) == (0, 0)
    assert rm.v5_side_modes(*riser, False) == (1, 0)             # sky off: the riser is back
    assert rm.v5_side_modes(*lip, False) == (2, 0)               # sky off: the lip is back
    assert rm.v5_side_modes(_Sec(200, 0, "F_SKY1"), _Sec(120, 0, "AQF054"), True) == (1, 0)
    assert rm.v5_side_modes(_Sec(200, 0, "AQF054"), _Sec(120, 0, "F_SKY1"), True) == (1, 0)


# -- flats: the &63 masks assume a 64x64 tile, so one must always exist ------------------------

class _WadWithoutFlats:
    def flat(self, name):
        raise KeyError(name)


class _WadWithShortFlat:
    def flat(self, name):
        return bytes(range(100))


def test_a_missing_or_short_flat_still_yields_a_full_tile(rm):
    """The `&63` masks in the span rasteriser assume a 64x64 tile; `_flat_texels`' pad is what makes
    that assumption TRUE. Remove it and a truncated or absent flat -- the sky placeholder, or any
    asset wad missing a lump -- turns a floor into an IndexError mid-frame: the oracle crashes
    where the fj program would paint garbage, and the gate cannot even run to report it.

    `_flat_base`'s WALL_BG fallback is the same guarantee for the cheap flat tier."""
    assert rm._flat_base(_WadWithoutFlats(), "NOPE", {}) == WALL_BG
    missing = rm._flat_texels(_WadWithoutFlats(), "NOPE", {})
    assert len(missing) == 4096 and set(missing) == {WALL_BG}
    short = rm._flat_texels(_WadWithShortFlat(), "SHORT", {})
    assert len(short) == 4096, "a 100-byte lump was not padded to a full tile"
    assert short[:100] == bytes(range(100)), "the real texels were not preserved"
    assert set(short[100:]) == {WALL_BG}, "the pad is not WALL_BG"
    # The cache must not change the answer -- both mirrors read it many times per frame.
    cache = {}
    assert rm._flat_texels(_WadWithShortFlat(), "SHORT", cache) == \
        rm._flat_texels(_WadWithShortFlat(), "SHORT", cache)


# -- the shared block-FP reciprocal kernels ----------------------------------------------------

def test_the_block_fp_reciprocal_tracks_the_exact_divide(rm):
    """`_scale_recip_div` is the SSOT the fj `proj.scale_recip_div` macro mirrors, and its docstring
    blesses a specific recipe (fsh base 6, a 14-NIBBLE truncated product). A narrower product width
    or an fsh off by one degrades every wall scale and every sprite xscale at once, which reads as a
    sub-pixel shift rather than as a failure -- so it needs a numeric bound, not a golden value.

    HONEST SCOPE: den_abs == 1 wraps to 0. That input is unreachable from the callers (the smallest
    |den| a real seg produces in the 12m sweep is 101), so the bound is asserted over the reachable
    range only -- starting at 2, well below anything geometry can hand it."""
    dens = [2, 3, 17, 101, 242] + list(range(256, 4096, 37)) + list(range(4096, 1 << 20, 7919))
    for den in dens:
        got = rm._scale_recip_div(1 << 16, den)
        exact = ((1 << 16) << 16) // den
        assert abs(got - exact) <= exact * 3 // 1000, (
            "den=%d: %d vs exact %d (%.4f%%)" % (den, got, exact, 100.0 * abs(got - exact) / exact))
    vals = [rm._scale_recip_div(1 << 16, d) for d in sorted(dens)]
    assert all(a >= b for a, b in zip(vals, vals[1:])), (
        "the reciprocal is not non-increasing in the denominator")


def test_a_zero_denominator_fails_loudly(rm):
    """CR-2026-08's negative control: den_abs == 0 used to spin the left-normalize loop forever.
    Every caller owns a nonzero denominator, so an assertion is the right answer -- a hang in a
    shared kernel is the worst possible failure mode for a build that already costs 45 minutes."""
    with pytest.raises(AssertionError, match="den_abs must be positive"):
        rm._scale_recip_div(1 << 16, 0)


def test_a_negative_quotient_clamps_to_the_ceiling_instead_of_wrapping(rm):
    """M13-scalerecip's sign split is justified by a PROVEN-equivalence argument -- 'any negative
    32-bit quotient's unsigned reading is >= 2^31 > SCALE_MAX, so it always clamped to SCALE_MAX' --
    that no test checks. If the split is wrong, `abs()` hands the reciprocal a magnitude it should
    have rejected and the wall gets a plausible FINITE scale instead of the clamp: drawn at the
    wrong depth rather than obviously broken.

    The concrete sign-mismatch case (num = -5242880, den = 8388608) comes first, then the sweep says
    the clamp holds everywhere -- test_wall_scale.py covers only den == 0 and the two in-range
    clamps."""
    assert rm.scale_from_global_angle(0, 0, ANG180, 128 << 16) == SCALE_MAX
    for i in range(13):
        viewangle = (i * ((1 << 32) // 13)) & 0xFFFFFFFF
        for j in range(7):
            normal = (j * ((1 << 32) // 7)) & 0xFFFFFFFF
            for dist in (1 << 16, 64 << 16, 1024 << 16, 4096 << 16):
                for k in range(5):
                    vis = (k * ((1 << 32) // 5)) & 0xFFFFFFFF
                    s = rm.scale_from_global_angle(vis, viewangle, normal, dist)
                    assert SCALE_MIN <= s <= SCALE_MAX, (
                        "scale %d out of [%d, %d] at vis=%#x view=%#x normal=%#x dist=%d"
                        % (s, SCALE_MIN, SCALE_MAX, vis, viewangle, normal, dist))


def test_slope_div_is_monotone_and_clamps_below_512(rm):
    """MIRROR-INSURANCE, rated honestly: `den < 512` and the `P < 2` left-normalize are unreachable
    from real 16.16 geometry (0 hits in a 15,976-call sweep from real segs), so the byte-exactness
    gate can never execute them -- which is exactly why they need a unit test. The fj `slope_div`
    macro mirrors THIS; a normalization slip that breaks monotonicity folds a wall's column mapping
    and tears it.

    The contract is num <= den, both >= 0; the index must never exceed SLOPERANGE (`tantoangle` has
    SLOPERANGE+1 entries, so a bigger index is an IndexError in point_to_angle) and must never go
    DOWN as the slope goes up."""
    for den in (400, 511, 512, 600, 1024, 5000, 70000, 1 << 20):
        nums = list(range(0, den + 1, max(1, den // 97)))
        vals = [rm._slope_div(num, den) for num in nums]
        assert all(0 <= v <= SLOPERANGE for v in vals), (
            "den=%d produced an index outside [0, %d]" % (den, SLOPERANGE))
        assert all(a <= b for a, b in zip(vals, vals[1:])), (
            "den=%d is not monotone non-decreasing in num" % den)
        if den < 512:
            assert set(vals) == {SLOPERANGE}, (
                "den=%d must clamp to SLOPERANGE for every numerator" % den)
    assert rm._slope_div(0, 1 << 20) == 0, "a zero slope is index 0, not the clamp"


# -- the host and the emitted program must be simulating the same world ------------------------

def test_hiding_a_thing_with_no_visibility_flag_raises(rm, level, scene):
    """Only a BAKED VANISHABLE thing has a flag the fj program can clear. Hiding anything else means
    the host and the emitted program are simulating DIFFERENT WORLDS -- and without the assert the
    oracle quietly renders the host's version, so the mirror comparison blames the renderer.

    `test_thing_table.py` pins the sibling guard for `thing_positions` ('moves BAKED things');
    nothing reached this one."""
    mw, aw, _cmap = level
    st = spawn_state(mw, "E1M1")
    with pytest.raises(AssertionError, match="have no visibility flag"):
        rm.render_wall_frame(st, scene, things=True, sprite_wad=aw, thing_hidden={0}, **RENDER)
