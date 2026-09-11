"""H3 map compiler (`doomfj.mapcompiler`) — the properties the rest of the suite leaves open.

`test_mapbake.py` pins the bake's counts and proves the emitted walk's ORDER by assembling it;
`test_thing_liveness.py` pins the prune guard's runtime arm; `test_collision.py` pins the blockmap
against an exhaustive sweep. What none of them touch is (a) everything that decides WHICH geometry
the shipped program is allowed to SKIP, and (b) everything in the two emitters that is only
reachable through an option combination no host test ever builds. Those are what this file pins.

**The bbox wedge cull** (`bbox_wedge_miss`, `wedge_planes_bam`). Not its answers — its SOUNDNESS:
flooring after combining is conservative (the cull may fail to cull, never over-cull), the corner
it tests is the one that maximises that plane's value, a box containing the eye is never culled,
inflating a box can only relax the cull, and both plane indices stay in 0..7 across the whole 2^32
BAM range. An over-cull drops a whole BSP subtree — a visibly missing chunk of the level — and
CR-2026-08 (PJ-1) was exactly that: per-axis flooring, invisible to every certified gate because
all four gate viewpoints sit on whole map units. The PJ-1 witness is this file's negative control.

**The seg rules** (`seg_sector`, `seg_affine_coeffs`, `_point_side`). `seg_sector` is the SSOT that
lets `cmap.segs[ss.firstseg]` stand in for "the subsector's sector" in the oracle, the emitter,
`thing_live_subsectors` and the collision seeding — so the property that matters is that every seg
in a subsector agrees. `seg_affine_coeffs` IS perf #10's back-face cull and `_point_side` IS the
BSP side test; if the two disagree about which side is front, one-sided walls are culled from the
side you can see them and BOTH mirrors agree while both are wrong. And `_point_side`'s collinear
convention (0 ⇒ front/right) decides the front-to-back occlusion order of an entire subtree at a
position that is reachable in play — E1M1's partitions are axis-aligned integers.

**The bake's child boxes.** `bbr`/`bbl` reach nothing in `tests/host` except through the union in
`bbox_gate_boxes`; a swap there produces gate boxes that cull geometry which is on screen.

**The emitted walks** (`_bsp_as_code`, `_bsp_descend_code`). Structure only — the arithmetic needs
assembly and lives in `tests/fj`. Every label referenced is defined (or declared external), no
label is defined twice, a pruned node keeps the partition block the descend pre-walk fcalls, the
two emitters agree on which child is NEAR, and `inline_side` changes only the node body. Each of
these failures surfaces today as an assembler error tens of minutes into a heavy build, or (a
reused fcall return register) as a silent infinite loop at runtime.

**The guards and the streams.** The compile-time arm of `assert_thing_live_survives_prune` (only
its runtime arm has a negative control today), the seg-less-subsector guard and the no-baked-boxes
early return that every hand-built `CompiledMap` in this suite depends on, the byte-identity of
`compile_geometry_streams` with `compile_map` (collision reads one, the renderer bakes from the
other — nothing compares them), and `_bytes_stream`'s two's-complement handling of the negative
fields `compile_map` hands it unmasked.

⚠ R9. Six tests here carry a negative control: `_wedge_signed` is a parameterised restatement of
`bbox_wedge_miss` proved faithful against the real function first, then MUTATED (per-axis floor,
wrong corner set) and required to break the property; the seg_sector, bbr/bbl and label-closure
checks each mutate real data or real text and require the check to reject it. Nothing here is
built or assembled: the whole file is pure Python over the committed fixtures.
"""
import random
import re
from collections import Counter
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import pytest

from doomfj.fixedpoint import _signed, fixed_mul
from doomfj.mapcompiler import (
    ANG45_BAM, NF_SUBSECTOR, CompiledMap, Node, Seg, SubSector,
    assert_thing_live_survives_prune, bake_bsp, bbox_gate_boxes, bbox_wedge_miss,
    compile_geometry_streams, compile_map, seg_affine_coeffs, seg_sector,
    thing_live_subsectors, wedge_planes_bam, _bsp_as_code, _bsp_descend_code, _bytes_stream,
    _point_side,
)
from doomfj.reference_model import ReferenceModel
from doomfj.wad import WadFile

E1M1 = Path("tests/fixtures/freedoom_e1m1.wad")
ROOM = Path("tests/fixtures/square_room.wad")
MAPNAME = "E1M1"
U = 1 << 16                       # one map unit in 16.16


@pytest.fixture(scope="module")
def level():
    """The real level, baked once: the only test bed with a deep tree, side==1 segs and real bboxes."""
    wad = WadFile.from_path(E1M1)
    return (wad, bake_bsp(wad, MAPNAME), wad.linedefs(MAPNAME), wad.sidedefs(MAPNAME),
            wad.sectors(MAPNAME))


# ══ the bbox wedge cull ═══════════════════════════════════════════════════════════════════════
#
# `bbox_wedge_miss(m, box, vx, vy, eyex16, eyey16)` is True when the whole box lies outside
# half-plane m, i.e. when the plane's signed value at the box's MAXIMISING corner is negative.
# Everything below is about that sentence being true, because a False that should be True only
# costs ops while a True that should be False deletes a subtree from the frame.


def _wedge_signed(m, box, vx, vy, ex16, ey16, *, per_axis=False,
                  y_top=(0, 1, 6, 7), x_left=lambda m: m < 4):
    """A PARAMETERISED restatement of the plane value `bbox_wedge_miss` tests (miss ⇔ value < 0).

    It exists only so the two defects this module cares about can be INJECTED: `per_axis=True` is
    the CR-2026-08 (PJ-1) form that floored each axis separately, and `y_top`/`x_left` are the
    corner-choice rule. `test_wedge_value_model_matches_the_shipped_function` proves the default
    configuration agrees with the real function before any mutation is used as evidence (R9)."""
    top, bottom, left, right = box
    cx = left if x_left(m) else right
    cy = top if m in y_top else bottom
    if per_axis:
        q = (cy - vy, (cy - cx) - (vy - vx), cx - vx, (cx + cy) - (vx + vy))[m & 3]
    else:
        q = (cy - vy, (cy - cx) - ((ey16 - ex16) >> 16),
             cx - vx, (cx + cy) - ((ex16 + ey16) >> 16))[m & 3]
    return -q if 2 <= m <= 5 else q


def _exact_signed(m, box, ex16, ey16):
    """The plane value with NO flooring anywhere — exact rationals from the 16.16 eye. This is the
    "true wedge" a cull must never contradict."""
    top, bottom, left, right = box
    cx = Fraction(left if m < 4 else right)
    cy = Fraction(top if m in (0, 1, 6, 7) else bottom)
    ex, ey = Fraction(ex16, U), Fraction(ey16, U)
    q = (cy - ey, (cy - cx) - (ey - ex), cx - ex, (cx + cy) - (ex + ey))[m & 3]
    return -q if 2 <= m <= 5 else q


def _wedge_cases(seed, n, span, *, eye_in_box=False):
    """(box, eye16, floored eye) samples. Small `span` keeps corners close to the wedge boundary,
    which is the only place the flooring forms can differ — a sweep over a whole map is vacuous."""
    rnd = random.Random(seed)
    for _ in range(n):
        x0, x1 = sorted(rnd.randint(-span, span) for _ in range(2))
        y0, y1 = sorted(rnd.randint(-span, span) for _ in range(2))
        if eye_in_box:
            ex16, ey16 = rnd.randint(x0 * U, x1 * U), rnd.randint(y0 * U, y1 * U)
        else:
            ex16, ey16 = rnd.randint(-span * U, span * U), rnd.randint(-span * U, span * U)
        yield (y1, y0, x0, x1), ex16, ey16, ex16 >> 16, ey16 >> 16


def test_wedge_value_model_matches_the_shipped_function():
    """⚠ R9 FOUNDATION. The mutations below are only evidence if the un-mutated model is the real
    function. Nothing else in this file may cite `_wedge_signed` unless this passes."""
    seen = {True: 0, False: 0}
    for box, ex16, ey16, vx, vy in _wedge_cases(1, 800, 24):
        for m in range(8):
            miss = bbox_wedge_miss(m, box, vx, vy, ex16, ey16)
            assert miss == (_wedge_signed(m, box, vx, vy, ex16, ey16) < 0), (
                f"the local wedge model disagrees with bbox_wedge_miss at m={m}, box={box}, "
                f"eye16={(ex16, ey16)} -- the negative controls below prove nothing")
            seen[miss] += 1
    assert min(seen.values()) > 100, f"sample is one-sided ({seen}) -- the agreement is vacuous"


def test_wedge_cull_is_conservative_never_culls_a_box_the_true_wedge_contains():
    """Flooring AFTER combining makes the integer value differ from the exact one by frac(E) in
    [0,1), so an integer value with the culling sign always implies the exact value is negative
    too: the cull can fail to cull, never over-cull. That one-sidedness is the whole safety
    argument for gating a subtree, and it is stated only in a comment today."""
    culled = tight = 0
    for box, ex16, ey16, vx, vy in _wedge_cases(2, 1500, 24):
        for m in range(8):
            exact = _exact_signed(m, box, ex16, ey16)
            if bbox_wedge_miss(m, box, vx, vy, ex16, ey16):
                culled += 1
                assert exact < 0, (
                    f"OVER-CULL at m={m}, box={box}, eye16={(ex16, ey16)}: culled a box whose "
                    f"exact wedge value is {float(exact)} >= 0 -- a visible subtree would vanish")
            if abs(exact) < 1:
                tight += 1
    assert culled > 500 and tight > 100, (
        f"only {culled} culls / {tight} near-boundary cases -- the sweep never reaches the "
        "boundary where the flooring forms differ, so it cannot fail")


def test_per_axis_flooring_over_culls_which_is_the_pj1_regression():
    """⚠ THE NEGATIVE CONTROL for the test above, and the regression itself (CR-2026-08, PJ-1).

    `floor(vy) - floor(vx)` gives q=1 an error in (-1,1) and q=3 an error in [0,2), so the
    per-axis form culls boxes the true wedge genuinely contains. The named witness is the one in
    the docstring's MEASURED note; the sweep shows it is not a lone special case."""
    box, m = (60, 20, 11, 40), 3
    ex16, ey16 = int(10.6 * U), int(20.6 * U)
    vx, vy = ex16 >> 16, ey16 >> 16
    assert (vx, vy) == (10, 20)
    exact = _exact_signed(m, box, ex16, ey16)
    assert exact > 0, "the witness box must really be INSIDE the wedge for the control to mean anything"
    assert not bbox_wedge_miss(m, box, vx, vy, ex16, ey16), (
        "the shipped combined-floor form culled the PJ-1 witness -- the regression is back")
    assert _wedge_signed(m, box, vx, vy, ex16, ey16, per_axis=True) < 0, (
        "the per-axis form no longer over-culls the witness -- this control has gone blind")

    wrong = 0
    for b, ex, ey, vx, vy in _wedge_cases(3, 2500, 24):
        for mm in range(8):
            if (_wedge_signed(mm, b, vx, vy, ex, ey, per_axis=True) < 0
                    and _exact_signed(mm, b, ex, ey) > 0):
                wrong += 1
    assert wrong > 5, (           # 12 of these 20,000 cases today; it needs corners within one
        f"per-axis flooring produced only {wrong} genuinely-wrong culls -- if this ever reaches 0 "
        "the sweep has drifted away from the boundary and the control is worthless")


def test_wedge_tests_the_corner_that_maximises_the_plane_value():
    """The corner rule (x = left iff m < 4; y = top iff m in {0,1,6,7}) must pick the MAXIMISING
    corner, expressed without restating it: a box misses iff ALL FOUR of its corners, each passed
    back as a degenerate one-point box, miss. ⇐ is trivial (the tested corner is one of the four);
    ⇒ is exactly maximality. Testing a non-extremal corner culls a box that is partly inside."""
    for box, ex16, ey16, vx, vy in _wedge_cases(4, 500, 200):
        top, bottom, left, right = box
        corners = [(y, y, x, x) for y in (bottom, top) for x in (left, right)]
        for m in range(8):
            assert (bbox_wedge_miss(m, box, vx, vy, ex16, ey16)
                    == all(bbox_wedge_miss(m, c, vx, vy, ex16, ey16) for c in corners)), (
                f"m={m}, box={box}, eye16={(ex16, ey16)}: the tested corner is not the maximising "
                "one -- part of the box is inside the wedge and the box was culled anyway")


@pytest.mark.parametrize("name,kw", [
    ("y_top drops m=7", dict(y_top=(0, 1, 6))),
    ("x_left off by one at m=3", dict(x_left=lambda m: m < 3)),
    ("x_left off by one at m=5", dict(x_left=lambda m: m < 6)),
])
def test_a_wrong_corner_choice_breaks_the_maximal_corner_property(name, kw):
    """⚠ THE NEGATIVE CONTROL for the corner rule. Note which mutations are NOT here: `m < 5`
    instead of `m < 4` and adding m=2 to `y_top` are both INVISIBLE, because those planes never
    read that coordinate (m=4 uses only y, m=2 only x). A control has to mutate a coordinate the
    plane actually consumes."""
    violations = differs = 0
    for box, ex16, ey16, vx, vy in _wedge_cases(5, 300, 200):
        top, bottom, left, right = box
        corners = [(y, y, x, x) for y in (bottom, top) for x in (left, right)]
        for m in range(8):
            whole = _wedge_signed(m, box, vx, vy, ex16, ey16, **kw) < 0
            each = all(_wedge_signed(m, c, vx, vy, ex16, ey16, **kw) < 0 for c in corners)
            violations += whole != each
            # ⚠ R9 ON THE CONTROL ITSELF. Everything above runs on the local model, so no defect in
            # `bbox_wedge_miss` can make this row fail -- fine while these rules really are
            # mutations, worthless the moment one of them becomes the shipped rule. So tie the row
            # back to the real function: a mutant that agrees with `bbox_wedge_miss` everywhere is
            # describing the product, not testing it.
            differs += whole != bbox_wedge_miss(m, box, vx, vy, ex16, ey16)
    assert violations > 0, f"{name} is not detected by the maximal-corner property"
    assert differs > 0, (
        f"{name} agrees with bbox_wedge_miss on every sample -- the shipped corner rule IS this "
        "mutant, so this row says nothing about the shipped one")


def test_omitting_the_eye_is_identical_to_passing_the_whole_unit_eye():
    """The "identical by construction" claim in the docstring, asserted. Two q-formulas sit in the
    function (the defaulted eye and the explicit one); an edit to one and not the other keeps every
    whole-map-unit caller — which is every existing golden — green while the fractional callers
    drift. That split is precisely what let PJ-1 live."""
    for box, _ex, _ey, _vx, _vy in _wedge_cases(6, 400, 200):
        for vx, vy in ((-416, 256), (0, 0), (-7, -13)):
            for m in range(8):
                assert (bbox_wedge_miss(m, box, vx, vy)
                        == bbox_wedge_miss(m, box, vx, vy, vx << 16, vy << 16)), (
                    f"defaulted vs explicit whole-unit eye disagree at m={m}, box={box}, "
                    f"eye=({vx},{vy})")


def test_wedge_miss_rejects_an_eye_the_caller_floored_with_int():
    """The internal assert's reason to exist: `int(-4.5) == -4` but the 16.16 pattern shifted right
    floors to -5, and the two halves of the q-formula would then read different eyes. The assert
    looks like a cheap per-node cost in a hot compile path, so something has to pin that it fires.
    (Needs asserts enabled — the suite never runs python -O.)"""
    ex16 = -9 * U // 2                      # -4.5 map units as signed 16.16
    assert int(-4.5) == -4 and ex16 >> 16 == -5, "the trap this assert exists for has changed"
    with pytest.raises(AssertionError, match="disagrees with the floored eye"):
        bbox_wedge_miss(0, (10, -10, -10, 10), int(-4.5), 0, ex16, 0)
    # ... and the correctly floored eye is accepted, so the guard is not simply always-on.
    bbox_wedge_miss(0, (10, -10, -10, 10), ex16 >> 16, 0, ex16, 0)


def test_a_box_containing_the_eye_is_never_culled():
    """Soundness invariant #1, and the one `bbox_gate_boxes` leans on hardest: the node you are
    standing inside is never gated away. A global sign flip on the `2 <= m <= 5` negation breaks
    this immediately."""
    for box, ex16, ey16, vx, vy in _wedge_cases(7, 400, 300, eye_in_box=True):
        for m in range(8):
            assert not bbox_wedge_miss(m, box, vx, vy, ex16, ey16), (
                f"m={m}: box {box} contains the eye {(ex16 / U, ey16 / U)} and was culled anyway")


def test_inflating_a_box_can_only_relax_the_cull():
    """Soundness invariant #2. `bbox_gate_boxes` inflates a thing-carrying subtree's box by 96
    units so a sprite whose centre sits just outside the wedge keeps its on-screen columns. That is
    only a relaxation if growth is monotone; an inverted corner choice makes inflation TIGHTEN the
    cull, silently defeating the sprite margin."""
    relaxed = 0
    for box, ex16, ey16, vx, vy in _wedge_cases(8, 400, 300):
        top, bottom, left, right = box
        big = (top + 96, bottom - 96, left - 96, right + 96)
        for m in range(8):
            small_miss = bbox_wedge_miss(m, box, vx, vy, ex16, ey16)
            big_miss = bbox_wedge_miss(m, big, vx, vy, ex16, ey16)
            assert not (big_miss and not small_miss), (
                f"m={m}: inflating {box} to {big} turned a kept box into a culled one")
            relaxed += small_miss and not big_miss
    assert relaxed > 0, "inflation never relaxed anything -- the sweep cannot see a tightening"


def test_wedge_planes_advance_one_step_per_45_degrees_and_stay_in_range():
    """Rotational equivariance over the full 2^32 BAM range. The `& 0xFFFFFFFF` is what keeps the
    subtraction inside the range: without it `wedge_planes_bam(0)` returns -1, a negative index
    that picks the wrong half-plane out of the fj side's table for every angle in the first 45
    degrees. `wedge_planes_bam` is 0% covered today."""
    rnd = random.Random(9)
    angles = [0, 1, ANG45_BAM - 1, ANG45_BAM, ANG45_BAM + 1, 0x80000000, 0xFFFFFFFF]
    angles += [rnd.randrange(1 << 32) for _ in range(800)]
    for va in angles:
        lo, hi = wedge_planes_bam(va)
        assert 0 <= lo <= 7 and 0 <= hi <= 7, f"plane index out of range at va={va:#x}: {(lo, hi)}"
        lo2, hi2 = wedge_planes_bam((va + ANG45_BAM) & 0xFFFFFFFF)
        assert (lo2, hi2) == ((lo + 1) & 7, (hi + 1) & 7), (
            f"rotating by 45 degrees from va={va:#x} moved the planes {(lo, hi)} -> {(lo2, hi2)}")
    # the mask is load-bearing: without it the very first angle is already a negative index.
    assert ((0 - ANG45_BAM) >> 29) == -1 and wedge_planes_bam(0)[0] == 7


def test_wedge_plane_hi_is_the_ceil_of_the_45_degree_index():
    """The `+ (ANG45_BAM - 1)` term is a ceil: on an exact multiple of 45 degrees it must NOT round
    up. Two of the four certified gate angles ARE exact multiples, i.e. the angles where the
    wedge's rounding slack is zero and widening or narrowing by a whole 45-degree sector shows up
    as a dropped subtree."""
    rnd = random.Random(10)
    exact_seen = 0
    for va in [0, ANG45_BAM, 2 * ANG45_BAM, ANG45_BAM + 1, 7 * ANG45_BAM,
               (0 - ANG45_BAM) & 0xFFFFFFFF] + [rnd.randrange(1 << 32) for _ in range(500)]:
        s = (va + ANG45_BAM) & 0xFFFFFFFF
        on_boundary = s % ANG45_BAM == 0
        exact_seen += on_boundary
        expected = ((s >> 29) if on_boundary else (s >> 29) + 1) & 7
        assert ((wedge_planes_bam(va)[1] - 4) & 7) == expected, (
            f"va={va:#x}: hi index is not ceil((va+45deg)/45deg) (boundary={on_boundary})")
    assert exact_seen >= 5, "no exact-multiple angle in the sample -- the ceil arm is untested"


# ══ the seg rules ═════════════════════════════════════════════════════════════════════════════

def test_every_seg_in_a_subsector_resolves_to_the_same_sector(level):
    """What makes `seg_sector(..., cmap.segs[ss.firstseg])` a legitimate stand-in for "the
    subsector's sector" — the shortcut the oracle, `thing_live_subsectors`, the band-bank baking
    and the collision seeding all take. `ReferenceModel._seg_sector` merely delegates here, so a
    mirror-agreement test would be vacuous; this is the rule itself."""
    _wad, cmap, lds, sds, secs = level
    side1 = sum(1 for s in cmap.segs if s.side == 1)
    assert side1 > 100, f"only {side1} back-side segs -- the side==1 arm of the rule is untested"
    for si, ss in enumerate(cmap.subsectors):
        if not ss.numsegs:
            continue
        found = {id(seg_sector(lds, sds, secs, cmap.segs[i]))
                 for i in range(ss.firstseg, ss.firstseg + ss.numsegs)}
        assert len(found) == 1, (
            f"ss{si}: its {ss.numsegs} segs resolve to {len(found)} different sectors -- "
            "firstseg is no longer a stand-in for the subsector's sector")


def test_swapping_the_sidedef_for_back_segs_breaks_the_subsector_rule(level):
    """⚠ THE NEGATIVE CONTROL for the rule above. The swapped rule does NOT crash: `ld.back` is -1
    on one-sided lines and Python's negative index quietly reads the LAST sidedef, so the defect
    would ship as wrong floor/ceiling heights and light levels, not as an exception."""
    _wad, cmap, lds, sds, secs = level

    def flipped(seg):
        ld = lds[seg.linedef]
        return secs[sds[ld.back if seg.side == 0 else ld.front].sector]

    negative_reads = broken = 0
    for ss in cmap.subsectors:
        if not ss.numsegs:
            continue
        found = set()
        for i in range(ss.firstseg, ss.firstseg + ss.numsegs):
            s = cmap.segs[i]
            ld = lds[s.linedef]
            negative_reads += (ld.back if s.side == 0 else ld.front) < 0
            found.add(id(flipped(s)))
        broken += len(found) > 1
    assert negative_reads > 0, "no out-of-range sidedef read -- the silent-failure claim is stale"
    assert broken > 100, (
        f"the swapped front/back rule breaks only {broken} subsectors -- too weak to be a control")

    # ⚠ R9 ON THE CONTROL ITSELF. `flipped` is a local restatement, so a defect in `seg_sector`
    # cannot make anything above fail. What it CAN do is make `flipped` the shipped rule -- and
    # then this file would be "proving" that a defect is detectable while shipping it. 6 of these
    # 294 segs agree by coincidence today (a linedef whose two sidedefs face the same sector);
    # a flipped `seg_sector` makes it all 294.
    sample = cmap.segs[::7]
    agree = sum(1 for s in sample if seg_sector(lds, sds, secs, s) is flipped(s))
    assert agree < len(sample) // 2, (
        f"seg_sector agrees with the swapped rule on {agree}/{len(sample)} segs -- the shipped "
        "rule IS the flipped one, so this control no longer describes a defect")


def test_seg_affine_sign_agrees_with_the_bsp_side_test(level):
    """perf #10's back-face cull (the sign of `a*viewx + b*viewy + c`) and the BSP side test
    (`_point_side`) must call the same side FRONT. If they disagree, one-sided walls get culled
    from the side you can actually see them — and both mirrors would agree with each other while
    both are wrong, so no byte-exactness gate can see it."""
    _wad, cmap, _lds, _sds, _secs = level
    views = [(-416, 256), (0, 256), (256, -256), (2048, -3680), (1024, -1000)]
    front = back = skipped = 0
    for seg in cmap.segs[::5]:
        a, b, c = seg_affine_coeffs(seg, cmap.vertexes)
        v1x, v1y = cmap.vertexes[seg.v1]
        v2x, v2y = cmap.vertexes[seg.v2]
        for vx, vy in views:
            d = _signed((fixed_mul(a, (vx << 16) & 0xFFFFFFFF, 8, 4)
                         + fixed_mul(b, (vy << 16) & 0xFFFFFFFF, 8, 4) + c) & 0xFFFFFFFF, 32)
            # a sample within a unit of the wall LINE is inside the coefficients' own rounding
            # error (they are 16.16 encodings of segdy/seglen), so its sign carries no claim.
            if abs(d) < U:
                skipped += 1
                continue
            side = _point_side(v1x, v1y, v2x - v1x, v2y - v1y, vx, vy)
            assert (d > 0) == (side < 0), (
                f"seg {seg} at view ({vx},{vy}): affine distance {d / U:.3f} says "
                f"{'front' if d > 0 else 'back'} but _point_side says "
                f"{'front' if side < 0 else 'back'}")
            front += d > 0
            back += d < 0
    assert front > 100 and back > 100, f"one-sided sample (front={front}, back={back})"
    assert skipped < 50, f"{skipped} samples fell in the rounding band -- the test is thinning out"


def test_zero_length_seg_has_no_affine_coefficients():
    """The guard against a node builder that emitted a degenerate seg. Freedoom E1M1 has none,
    which is exactly why the branch is uncovered — and why M4's other eight maps are where a
    ZeroDivisionError would surface, 45 minutes into an emit."""
    verts = [(5, 5), (5, 5), (9, 12)]
    assert seg_affine_coeffs(Seg(0, 1, 0, 0, 0, 0), verts) == (0, 0, 0)
    assert seg_affine_coeffs(Seg(0, 2, 0, 0, 0, 0), verts) != (0, 0, 0), (
        "a real seg also returns (0,0,0) -- the degenerate case is indistinguishable")


def test_point_side_is_zero_on_the_partition_line_and_the_walk_goes_front(level):
    """The collinear convention: on the line is FRONT/right, in `point_in_subsector` and in
    `bsp_render_order` alike. Map coordinates are integers and E1M1's partitions are overwhelmingly
    axis-aligned, so standing exactly on one is reachable in play — and a `>` vs `>=` slip there
    flips a whole subtree's front-to-back order. tests/host pins the >0 convention only at
    viewpoints far from any line; the on-the-line pin lives only in the assembly-gated tests/fj."""
    _wad, cmap, _lds, _sds, _secs = level
    rm = ReferenceModel()
    root = cmap.nodes[cmap.root]
    # every node's own anchor is on its line, at the anchor, along it and beyond both ends
    assert all(_point_side(n.x, n.y, n.dx, n.dy, n.x, n.y) == 0 for n in cmap.nodes)
    for t in (-97, -1, 0, 1, 97):
        assert _point_side(root.x, root.y, root.dx, root.dy,
                           root.x + root.dx * t, root.y + root.dy * t) == 0

    def descend(child, x, y):
        while not child & NF_SUBSECTOR:
            n = cmap.nodes[child]
            child = n.left if _point_side(n.x, n.y, n.dx, n.dy, x, y) > 0 else n.right
        return child & (NF_SUBSECTOR - 1)

    on_line = (root.x, root.y)
    front_leaf, back_leaf = descend(root.right, *on_line), descend(root.left, *on_line)
    assert front_leaf != back_leaf, "both root children lead to the same leaf -- nothing to pin"
    assert rm.point_in_subsector(cmap, *on_line) == front_leaf, (
        "standing on the root partition landed in the BACK subtree -- the collinear convention "
        "flipped (>= where > was meant)")
    order = rm.bsp_render_order(cmap, *on_line)
    assert order[0] == front_leaf, (
        "on the partition line the render order starts in the back subtree -- the occlusion order "
        "of the whole frame is inverted at that position")


# ══ the bake ══════════════════════════════════════════════════════════════════════════════════

def test_bake_is_a_pure_function_of_the_wad_and_keeps_every_node(level):
    """`zip(wad.nodes(mapname), bboxes)` truncates to the shorter sequence WITH NO ERROR. One
    record short and `root = len(nodes) - 1` names a different node as the root: the walk still
    completes, still visits every subsector once, and renders a plausible-but-wrong frame — which
    is why `test_bake_e1m1_render_order_is_permutation` cannot see it."""
    wad, cmap, _lds, _sds, _secs = level
    assert len(cmap.nodes) == len(wad.nodes(MAPNAME)) == len(wad.nodes_bbox(MAPNAME)), (
        "bake_bsp's zip silently dropped nodes -- the root would be a different node")
    assert cmap.root == len(cmap.nodes) - 1
    assert bake_bsp(WadFile.from_path(E1M1), MAPNAME) == cmap, (
        "two bakes of the same WAD differ -- the emitter's input is not reproducible")


def test_child_bboxes_bound_the_right_and_left_subtrees(level):
    """`bbr` belongs to `right` and `bbl` to `left`. `bbox_gate_boxes` unions the two into the
    runtime wedge box, so a swap in the Node construction produces gate boxes that cull geometry
    which is on screen — and bbr/bbl reach nothing else in tests/host."""
    _wad, cmap, _lds, _sds, _secs = level
    extent = _subtree_extents(cmap)

    def contains(bbox, ext):
        top, bottom, left, right = bbox
        minx, maxx, miny, maxy = ext
        return minx >= left and maxx <= right and miny >= bottom and maxy <= top

    checked = swapped_violations = 0
    for i, n in enumerate(cmap.nodes):
        for bbox, child, which in ((n.bbr, n.right, "bbr/right"), (n.bbl, n.left, "bbl/left")):
            ext = extent[child]
            if ext is None:
                continue
            checked += 1
            assert contains(bbox, ext), (
                f"node {i} {which}: box {bbox} does not contain its subtree's segs {ext}")
        for bbox, child in ((n.bbl, n.right), (n.bbr, n.left)):        # ⚠ the swapped control
            ext = extent[child]
            if ext is not None and not contains(bbox, ext):
                swapped_violations += 1
    assert checked > 1000, f"only {checked} child boxes checked"
    assert swapped_violations > checked // 2, (
        f"swapping bbr/bbl breaks only {swapped_violations} of {checked} boxes -- the two boxes "
        "are too alike on this map for the test to catch a swap")


def _subtree_extents(cmap):
    """{child ref: (minx, maxx, miny, maxy) over every seg vertex below it}, or None when empty."""
    memo = {}

    def walk(child):
        if child in memo:
            return memo[child]
        if child & NF_SUBSECTOR:
            ss = cmap.subsectors[child & (NF_SUBSECTOR - 1)]
            pts = [cmap.vertexes[v]
                   for i in range(ss.firstseg, ss.firstseg + ss.numsegs)
                   for v in (cmap.segs[i].v1, cmap.segs[i].v2)]
            got = ((min(p[0] for p in pts), max(p[0] for p in pts),
                    min(p[1] for p in pts), max(p[1] for p in pts)) if pts else None)
        else:
            n = cmap.nodes[child]
            kids = [k for k in (walk(n.right), walk(n.left)) if k is not None]
            got = ((min(k[0] for k in kids), max(k[1] for k in kids),
                    min(k[2] for k in kids), max(k[3] for k in kids)) if kids else None)
        memo[child] = got
        return got

    import sys
    old = sys.getrecursionlimit()
    sys.setrecursionlimit(20000)
    try:
        walk(cmap.root)
    finally:
        sys.setrecursionlimit(old)
    return memo


# ══ the emitted walks ═════════════════════════════════════════════════════════════════════════
#
# Structure only. That the side test computes the right side needs assembly (tests/fj); that every
# name it uses RESOLVES does not, and that is the failure mode which otherwise surfaces as an
# assembler error tens of minutes into a heavy build — or, for a reused fcall return register, as a
# silent infinite loop at runtime.

_DEF = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"^-?(0x[0-9a-fA-F]+|\d+)$")


def _label_defs(text):
    """Every label the text DEFINES, in order (labels are `name:` at the head of a line)."""
    out = []
    for line in text.splitlines():
        m = _DEF.match(line.split("//")[0])
        if m:
            out.append(m.group(1))
    return out


def _label_refs(text):
    """Every name the text USES as an operand — jump targets, fcall/fret registers and the hex
    vectors macros read. Numeric literals are skipped; the macro name itself (it always carries a
    namespace dot) is dropped, and an operand head without one is an error rather than a silent
    miss, so a new instruction form cannot slip past this parser unnoticed."""
    out = set()
    for line in text.splitlines():
        body = _DEF.sub("", line.split("//")[0], count=1)
        body = re.sub(r"rep\(\s*[^)]*\)", "", body).strip()     # the hot-region pad: `rep(N, i) ...`
        if not body:
            continue
        if body.startswith(";"):
            body = body[1:]
        else:
            head, _, body = body.partition(" ")
            assert "." in head, f"unrecognised instruction head {head!r} in {line!r}"
        for tok in re.split(r"[\s,;+*\-]+", body):
            if not tok or _NUMBER.match(tok):
                continue
            out.update(_IDENT.findall(tok))
    return out


def _unresolved(text, externals, extra_defs=()):
    """Names the text uses but nothing defines — the assembler error, found in milliseconds."""
    known = set(_label_defs(text)) | set(extra_defs) | set(externals)   # hoisted: the walk texts
    return sorted(r for r in _label_refs(text) if r not in known)       # are ~800 KB apiece


# names the emitted walk deliberately does not define: the caller's globals and gate cells.
WALK_EXTERNALS = {"vx", "vy", "dw", "bsp_done", "tsstop", "tsbstop", "fbspent", "full",
                  "dsc_seed", "bbgate_leaf", "bbtret", "bbcl", "bbcb", "bbcr", "bbct", "bbvis"}


def _bbox_gate(i, ret_reg):
    """A stand-in for wall_renderer's `_bbox_gate_lines`, same shape: stage the box, call the
    shared leaf, fret out of the whole subtree on a miss."""
    stage = [f"    hex.xor_by 8, bbcl, {i}", f"    hex.xor_by 8, bbct, {i}"]
    return (stage + ["    stl.fcall bbgate_leaf, bbtret"] + stage
            + [f"    hex.if0 1, bbvis, bbmiss{i}", f"    ;bbgo{i}",
               f"  bbmiss{i}:", f"    stl.fret {ret_reg}", f"  bbgo{i}:"])


def _descend_leaf(s):
    """The descend pre-walk's landing action (the shipped one bakes viewz + a band-bank pointer)."""
    return [f"    hex.set 8, dsc_seed, {s}    // dleaf {s}"]


def _balanced_map(depth=5):
    """A full binary tree with sign- and magnitude-varied partitions, children before parents and
    the root last — DOOM's layout, small enough to emit the whole option matrix over."""
    nodes = []

    def build(level, x, y, dx, dy, lo, hi):
        if level == 0:
            return lo | NF_SUBSECTOR
        mid = (lo + hi) // 2
        left = build(level - 1, x + level, y - level, dy, -dx, lo, mid)
        right = build(level - 1, x - level, y + level, -dy, dx, mid, hi)
        nodes.append(Node(x, y, dx, dy, right=right, left=left))
        return len(nodes) - 1

    root = build(depth, 0, 0, 1, 0, 0, 1 << depth)
    return CompiledMap(vertexes=[(0, 0)], segs=[],
                       subsectors=[SubSector(1, 0) for _ in range(1 << depth)],
                       nodes=nodes, root=root)


def test_descend_code_references_only_labels_the_main_walk_emits(level):
    """`_bsp_descend_code`'s docstring names the failure: the shared blocks are keyed on `pfx`, and
    keying them on the tag instead would make "the second descent reference blocks nobody emits".
    The whole function is 0% covered. Everything the descent does not define itself must come from
    `_bsp_as_code` at the SAME pfx — node{i}_partition for every i, _pos_leaf, _pos_ret, _xbret,
    _side — or be a declared external."""
    _wad, cmap, _lds, _sds, _secs = level
    main = _bsp_as_code("e1m1", cmap, done_label="bsp_done")
    dsc = _bsp_descend_code("e1m1", cmap, _descend_leaf, done_label="bsp_done")
    main_defs = set(_label_defs(main))
    assert _unresolved(dsc, WALK_EXTERNALS, main_defs) == [], "the descent references labels nobody emits"
    borrowed = {r for r in _label_refs(dsc) if r in main_defs}
    for needed in ("e1m1_bspcode_pos_leaf", "e1m1_bspcode_pos_ret", "e1m1_bspcode_xbret",
                   "e1m1_bspcode_side", "e1m1_bspcode_node0_partition",
                   f"e1m1_bspcode_node{len(cmap.nodes) - 1}_partition"):
        assert needed in borrowed, f"{needed} is no longer shared with the main walk"
    assert sum(1 for i in range(len(cmap.nodes))
               if f"e1m1_bspcode_node{i}_partition" in borrowed) == len(cmap.nodes), (
        "the descent fcalls a partition block for only SOME nodes -- it fcalls one per node")
    # ⚠ the checker must be able to fail: break one definition and require it to notice.
    broken = main.replace("e1m1_bspcode_pos_leaf:", "e1m1_bspcode_posleaf:", 1)
    assert _unresolved(dsc, WALK_EXTERNALS, set(_label_defs(broken))) == ["e1m1_bspcode_pos_leaf"]


def test_two_descents_define_disjoint_labels(level):
    """M14-d runs a SECOND descent (the sector under a candidate collision position) alongside the
    player's. fj labels are global, so a shared own-label makes the assembler reject the whole
    program. ⚠ Writing this exposed that `tag` is SHADOWED by the `for child, tag in (...)` loop
    variable — harmless only because `D` is computed before the loop, which is precisely what a
    non-empty tag here keeps true."""
    _wad, cmap, _lds, _sds, _secs = level
    main = set(_label_defs(_bsp_as_code("e1m1", cmap, done_label="bsp_done")))
    a = _bsp_descend_code("e1m1", cmap, _descend_leaf, done_label="bsp_done")
    b = _bsp_descend_code("e1m1", cmap, _descend_leaf, done_label="e1m1_cs_seeded", tag="cs")
    da, db = _label_defs(a), _label_defs(b)
    assert set(da) & set(db) == set(), "the tagged descent collides with the untagged one"
    assert (set(da) | set(db)) & main == set(), "a descent redefines one of the main walk's labels"
    for name, d in (("untagged", da), ("tagged", db)):
        dup = [k for k, v in Counter(d).items() if v > 1]
        assert not dup, f"the {name} descent defines {dup[:3]} more than once"
    assert len(db) == len(da), "the tagged descent emits a different number of blocks"


def test_descend_and_walk_agree_on_which_child_is_near(level):
    """Near/far mirror. In BOTH emitters the fall-through after `hex.if0 2, _side, ..._far` is the
    LEFT child and the `_far` block leads with the RIGHT one. A swap in the descend-only walk
    renders nothing wrong — it just point-locates the eye in the wrong subsector, so the whole
    frame gets a wrong viewz and a wrong baked band-bank pointer."""
    _wad, cmap, _lds, _sds, _secs = level
    main = _bsp_as_code("e1m1", cmap, done_label="bsp_done")
    dsc = _bsp_descend_code("e1m1", cmap, _descend_leaf, done_label="bsp_done")
    walk_near, walk_far = _walk_first_children(main, "e1m1_bspcode")
    dsc_near, dsc_far = _descend_children(dsc, "e1m1_dsc", "e1m1_bspcode")
    assert len(walk_near) == len(dsc_near) == len(cmap.nodes)
    for i, n in enumerate(cmap.nodes):
        expect_near, expect_far = _child_token(n.left), _child_token(n.right)
        assert walk_near[i] == expect_near and walk_far[i] == expect_far, (
            f"_bsp_as_code node {i}: near/far is {(walk_near[i], walk_far[i])}, "
            f"expected {(expect_near, expect_far)}")
        assert dsc_near[i] == expect_near and dsc_far[i] == expect_far, (
            f"_bsp_descend_code node {i}: near/far is {(dsc_near[i], dsc_far[i])}, "
            f"expected {(expect_near, expect_far)} -- the two walks disagree on the near child")


def _child_token(child):
    return ("ss", child & (NF_SUBSECTOR - 1)) if child & NF_SUBSECTOR else ("node", child)


def _walk_first_children(text, L):
    """{node: first child visited before the _far label}, {node: first child visited after it}."""
    near, far, cur, phase = {}, {}, None, None
    block = re.compile(rf"^{L}_node(\d+):")
    far_lbl = re.compile(rf"^{L}_node(\d+)_far:")
    call = re.compile(rf"^\s*stl\.fcall {L}_node(\d+), {L}_node\1_ret\s*$")
    leaf = re.compile(r"^\s*stl\.output 10\s+// subsector (\d+)\s*$")
    for line in text.splitlines():
        if block.match(line):
            cur, phase = int(block.match(line).group(1)), near
            continue
        if far_lbl.match(line):
            phase = far
            continue
        if cur is None:
            continue
        m = call.match(line.split("//")[0])
        tok = ("node", int(m.group(1))) if m else None
        if tok is None:
            m = leaf.match(line)
            tok = ("ss", int(m.group(1))) if m else None
        if tok is not None and cur not in phase:
            phase[cur] = tok
    return near, far


def _descend_children(text, D, L):
    near, far, cur, phase = {}, {}, None, None
    block = re.compile(rf"^{D}_node(\d+):")
    far_lbl = re.compile(rf"^{D}_node(\d+)_far:")
    jump = re.compile(rf"^\s*;{D}_node(\d+)\s*$")
    leaf = re.compile(r"//\s*dleaf (\d+)\s*$")
    for line in text.splitlines():
        if block.match(line):
            cur, phase = int(block.match(line).group(1)), near
            continue
        if far_lbl.match(line):
            phase = far
            continue
        if cur is None:
            continue
        m = jump.match(line.split("//")[0])
        tok = ("node", int(m.group(1))) if m else None
        if tok is None:
            m = leaf.search(line)
            tok = ("ss", int(m.group(1))) if m else None
        if tok is not None and cur not in phase:
            phase[cur] = tok
    return near, far


def test_pruned_node_keeps_its_partition_block_and_leaves_no_dangling_reference(level):
    """A pruned subtree loses its WALK block but must keep its `node{i}_partition:` block, because
    `_bsp_descend_code` fcalls one for EVERY node, pruned or not. "Cleaning up" the pruned branch
    to skip the partition block breaks the descent — as an assembler failure at the end of a long
    build, since nothing here is exercised by a host test today."""
    _wad, cmap, _lds, _sds, _secs = level
    pruned = {3, 7, 11}
    text = _bsp_as_code("e1m1", cmap, done_label="bsp_done", prune=lambda c: c in pruned)
    defined = set(_label_defs(text))
    for i in pruned:
        assert f"e1m1_bspcode_node{i}" not in defined, f"node {i} was pruned but kept its walk block"
        assert f"e1m1_bspcode_node{i}_partition" in defined, (
            f"node {i}'s partition block is gone -- the descend pre-walk fcalls it for every node")
        assert f"e1m1_bspcode_node{i}_ret" in defined, "the per-node return register vanished"
    kept = len(cmap.nodes) - len(pruned)
    assert sum(1 for i in range(len(cmap.nodes))
               if f"e1m1_bspcode_node{i}" in defined) == kept, "wrong number of walk blocks"
    assert _unresolved(text, WALK_EXTERNALS) == [], "pruning left a dangling reference"
    dsc = _bsp_descend_code("e1m1", cmap, _descend_leaf, done_label="bsp_done")
    assert _unresolved(dsc, WALK_EXTERNALS, defined) == [], (
        "the descent cannot resolve against a pruned walk")


@pytest.mark.parametrize("prune", [None, lambda c: c in {3, 7, 11}], ids=["keep", "prune"])
@pytest.mark.parametrize("inline_side", [False, True], ids=["shared", "inline"])
@pytest.mark.parametrize("plane_gate", [None, lambda i: 1 if i % 3 == 0 else 0,
                                        lambda i: 2 if i % 3 == 0 else 0],
                         ids=["nogate", "mode1", "mode2"])
@pytest.mark.parametrize("full_abort_label", [None, "full"], ids=["noabort", "abort"])
@pytest.mark.parametrize("extra_gate", [None, _bbox_gate], ids=["nobbox", "bbox"])
def test_every_option_combination_emits_a_closed_label_set(prune, inline_side, plane_gate,
                                                           full_abort_label, extra_gate):
    """The option matrix. `full_abort`, `extra_gate`, both plane_gate modes and the whole
    `inline_side` body are 0% covered and are never built together anywhere, yet each adds labels
    and branch targets. Two failures live here: an undefined label (an assembler error at the end
    of a long build) and a DUPLICATED fcall return register — which is worse than an error, being
    a silent infinite loop or a skipped subtree at runtime."""
    cmap = _balanced_map()
    text = _bsp_as_code("bal", cmap, done_label="bsp_done", prune=prune, inline_side=inline_side,
                        plane_gate=plane_gate, full_abort_label=full_abort_label,
                        extra_gate=extra_gate)
    dup = [k for k, v in Counter(_label_defs(text)).items() if v > 1]
    assert not dup, f"labels defined twice: {dup[:5]}"
    assert _unresolved(text, WALK_EXTERNALS) == [], "undefined labels in this option combination"


def test_the_label_closure_check_can_fail():
    """⚠ R9 for the matrix above: a check that cannot reject anything proves nothing about the
    combinations it passed."""
    cmap = _balanced_map(3)
    text = _bsp_as_code("bal", cmap, done_label="bsp_done")
    assert _unresolved(text, WALK_EXTERNALS) == []
    renamed = text.replace("bal_bspcode_pos_leaf:", "bal_bspcode_typo:", 1)
    assert _unresolved(renamed, WALK_EXTERNALS) == ["bal_bspcode_pos_leaf"]
    doubled = text + "\nbal_bspcode_xbret: ;0\n"
    assert [k for k, v in Counter(_label_defs(doubled)).items() if v > 1] == ["bal_bspcode_xbret"]


def test_inline_side_changes_only_the_node_body(level):
    """M13-inlinenodes specialises the side test per node. What it must NOT do is take `_pos_leaf`
    or the partition blocks with it: the descend pre-walk still routes through both. Dead-code-
    eliminating them once the node bodies stop calling them would break `_bsp_descend_code`, whose
    own tests did not exist until this file."""
    _wad, cmap, _lds, _sds, _secs = level
    shared = _bsp_as_code("e1m1", cmap, done_label="bsp_done", inline_side=False)
    inline = _bsp_as_code("e1m1", cmap, done_label="bsp_done", inline_side=True)
    for text, mode in ((shared, "shared"), (inline, "inline")):
        d = set(_label_defs(text))
        assert "e1m1_bspcode_pos_leaf" in d, f"{mode}: _pos_leaf is gone"
        assert sum(1 for i in range(len(cmap.nodes))
                   if f"e1m1_bspcode_node{i}_partition" in d) == len(cmap.nodes), (
            f"{mode}: a node lost its partition block")
        assert _unresolved(text, WALK_EXTERNALS) == []
    assert shared.count("stl.fcall e1m1_bspcode_pos_leaf") == len(cmap.nodes)
    assert inline.count("stl.fcall e1m1_bspcode_pos_leaf") == 0, (
        "inline_side still fcalls the shared side-test leaf -- it is not inlining anything")
    for nm in ("idxv", "idyv", "ip1", "ip2", "is1", "is2"):
        decl = f"e1m1_bspcode_{nm}: hex.vec"
        assert decl in inline, f"inline_side did not declare its scratch vec {nm}"
        assert decl not in shared, f"the shared path declares the inline-only scratch vec {nm}"


def test_inline_side_and_shared_leaf_emit_the_same_traversal_skeleton(level):
    """The two side-test implementations must visit the same children in the same order — the
    closest CHEAP proxy for byte-exactness between them (the 4-way sign compare itself needs
    assembly, tests/fj). A lost child visit or a restructured branch would change the front-to-back
    order and therefore the frame, while every existing host test — none of which sets inline_side
    — stayed green."""
    _wad, cmap, _lds, _sds, _secs = level
    a = _skeleton(_bsp_as_code("e1m1", cmap, done_label="bsp_done", inline_side=False), "e1m1_bspcode")
    b = _skeleton(_bsp_as_code("e1m1", cmap, done_label="bsp_done", inline_side=True), "e1m1_bspcode")
    assert len(a) > 4 * len(cmap.nodes), "the skeleton extractor found almost nothing"
    assert a == b, "inline_side changed the traversal: first divergence at %r vs %r" % (
        next((x, y) for x, y in zip(a, b) if x != y),
        len(a) == len(b) or (len(a), len(b)))
    # every leaf is visited on both branches of its parent, as the walk emits each action twice
    leaves = {e[1] for e in a if e[0] == "leaf"}
    assert leaves == set(range(len(cmap.subsectors))), "a subsector dropped out of the walk"


def _skeleton(text, L):
    """The traversal events in order: node calls, leaf visits, far labels and frets."""
    pats = (("call", re.compile(rf"^\s*stl\.fcall {L}_node(\d+), {L}_node\1_ret\s*$")),
            ("fret", re.compile(rf"^\s*stl\.fret {L}_node(\d+)_ret\s*$")),
            ("far", re.compile(rf"^{L}_node(\d+)_far:")),
            ("block", re.compile(rf"^{L}_node(\d+):")),
            ("leaf", re.compile(r"^\s*stl\.output 10\s+// subsector (\d+)\s*$")))
    out = []
    for line in text.splitlines():
        for kind, pat in pats:
            m = pat.match(line if kind in ("far", "block", "leaf") else line.split("//")[0])
            if m:
                out.append((kind, int(m.group(1))))
                break
    return out


def test_plane_gate_mode_2_emits_the_compound_guard():
    """A tripwire on lines the coverage never reaches. CR-2026-08: mode 2 marks a subtree holding
    PIECE-carrying segs, and pieces still record into attributed-but-undrawn columns — so the plain
    `tsstop` test of mode 1 dropped riser/lip pieces the oracle records, a byte-exactness break.
    This is close to restating the emitted text and the honest proof is a frame render; it is here
    because silently reverting mode 2 to the plain form costs nothing to do and nothing catches it."""
    cmap = _balanced_map(3)
    one = _bsp_as_code("pg", cmap, plane_gate=lambda i: 1 if i == 0 else 0)
    two = _bsp_as_code("pg", cmap, plane_gate=lambda i: 2 if i == 0 else 0)
    ungated = _bsp_as_code("pg", cmap)
    for cell in ("tsstop", "tsbstop", "fbspent"):
        assert cell not in ungated, f"{cell} is referenced with no plane gate at all"
    assert "tsstop" in one and "tsbstop" not in one and "fbspent" not in one, (
        "mode 1 is no longer the single tsstop test")
    assert all(cell in two for cell in ("tsbstop", "tsstop", "fbspent")), (
        "mode 2 lost the compound tsbstop|(tsstop&fbspent) guard -- the CR-2026-08 regression")
    assert one.count("pg_bspcode_node0_planes_live") == 2, "mode 1's gate lost its live label"


# ══ the guards ════════════════════════════════════════════════════════════════════════════════

def _tiny_tree():
    """root (node 2) -> node 0 over ss0/ss1 and node 1 over ss2/ss3."""
    n0 = Node(x=0, y=10, dx=1, dy=0, right=0 | NF_SUBSECTOR, left=1 | NF_SUBSECTOR)
    n1 = Node(x=0, y=-10, dx=1, dy=0, right=2 | NF_SUBSECTOR, left=3 | NF_SUBSECTOR)
    root = Node(x=0, y=0, dx=0, dy=1, right=0, left=1)
    return CompiledMap(vertexes=[(0, 0)], segs=[],
                       subsectors=[SubSector(1, i) for i in range(4)], nodes=[n0, n1, root], root=2)


def test_guard_rejects_a_prune_that_drops_a_thing_live_leaf_at_emit_time():
    """⚠ THE MISSING HALF OF test_thing_liveness's negative control. That file's control fires the
    RUNTIME arm (`tsstop-gated`); the COMPILE-time arm ("walk-pruned at emit") — the one where the
    walk block is gone from the binary altogether — has never been shown to fire. Its own docstring
    says that if the guard goes blind "every other assertion here is worthless", so both arms need
    a control."""
    cmap = _tiny_tree()
    with pytest.raises(AssertionError, match="walk-pruned at emit"):
        assert_thing_live_survives_prune(cmap, thing_live={2}, prune=lambda c: c == 1, where="T: ")
    # pruning the ROOT drops everything, including the leaf
    with pytest.raises(AssertionError, match="walk-pruned at emit"):
        assert_thing_live_survives_prune(cmap, thing_live={2}, prune=lambda c: c == cmap.root)
    # ... and the permission is not unconditional: the same prune over a leaf nothing can enter,
    # and the same liveness with no prune at all, are both accepted.
    assert_thing_live_survives_prune(cmap, thing_live={2}, prune=None)
    assert_thing_live_survives_prune(cmap, thing_live={0, 1}, prune=lambda c: c == 1)

    # ⚠ THE ROOT'S OWN PRUNE IS A SEPARATE CALL SITE and every case above is blind to it: for an
    # interior root the walk re-applies `prune(child)` on entry, so dropping the seed argument
    # changes nothing. A map with no nodes is one convex subsector (`bake_bsp` sets
    # root = 0 | NF_SUBSECTOR) and the seed is then the ONLY place the prune is ever consulted --
    # M4's eight other maps are where a single-subsector level would first appear.
    leaf_root = CompiledMap(vertexes=[(0, 0)], segs=[], subsectors=[SubSector(1, 0)],
                            nodes=[], root=0 | NF_SUBSECTOR)
    with pytest.raises(AssertionError, match="walk-pruned at emit"):
        assert_thing_live_survives_prune(leaf_root, thing_live={0}, prune=lambda c: True)
    assert_thing_live_survives_prune(leaf_root, thing_live={0}, prune=None)


def test_seg_less_subsector_is_skipped_not_read_through():
    """`thing_live_subsectors` must skip a `numsegs == 0` leaf rather than read `segs[firstseg]`.
    Freedoom E1M1 has none — which is why the guard is uncovered, and why the risk belongs to M4's
    other eight maps. Without it the read is either an IndexError at emit or, worse, a NEIGHBOURING
    subsector's seg, marking a leaf live or dead on another sector's headroom."""
    cmap = CompiledMap(vertexes=[(0, 0), (1, 0)], segs=[Seg(0, 1, 0, 0, 0, 0)],
                       subsectors=[SubSector(1, 0), SubSector(0, 99), SubSector(1, 0)],
                       nodes=[], root=0 | NF_SUBSECTOR)
    lds, sds = [_LD(0, -1)], [_SD(0)]
    live = thing_live_subsectors(cmap, lds, sds, [_SEC(0, 128)])
    assert live == frozenset({0, 2}), f"expected the seg-less leaf to be skipped, got {live}"
    # firstseg is deliberately out of range: the guard, not luck, is what keeps this from raising.
    assert cmap.subsectors[1].firstseg >= len(cmap.segs)
    # a sector with no headroom is excluded for the OTHER reason, so both arms are live here
    assert thing_live_subsectors(cmap, lds, sds, [_SEC(128, 128)]) == frozenset()


@dataclass(frozen=True)
class _LD:
    front: int
    back: int


@dataclass(frozen=True)
class _SD:
    sector: int


@dataclass(frozen=True)
class _SEC:
    floor_h: int
    ceil_h: int


def test_bbox_gate_boxes_returns_nothing_without_baked_child_boxes():
    """Every hand-built `CompiledMap` in tests/host and tests/fj leaves `bbr`/`bbl` at their default
    None. Without the early return, `(rt,rb,rl,rr),(lt,lb,ll,lr) = n.bbr, n.bbl` raises TypeError on
    all of them."""
    no_nodes = CompiledMap(vertexes=[(0, 0)], segs=[], subsectors=[SubSector(0, 0)],
                           nodes=[], root=0 | NF_SUBSECTOR)
    assert bbox_gate_boxes(no_nodes) == {}
    assert bbox_gate_boxes(_tiny_tree(), min_segs=0) == {}, (
        "a tree whose nodes carry the default bbr=None must gate nothing, not raise")


# ══ the streams ═══════════════════════════════════════════════════════════════════════════════

def _stream_blocks(src):
    """{label: [non-blank lines]} for every `// stream "label":` block in an emitted .fj text."""
    out, cur, buf = {}, None, []
    for line in src.splitlines():
        m = re.match(r'^// stream "([^"]+)":', line)
        if m:
            if cur:
                out[cur] = buf
            cur, buf = m.group(1), [line]
        elif cur:
            buf.append(line)
    if cur:
        out[cur] = buf
    return {k: [l for l in v if l.strip()] for k, v in out.items()}


@pytest.mark.parametrize("wadpath,mapname", [(ROOM, "MAP01"), (E1M1, MAPNAME)])
def test_geometry_streams_match_compile_map_block_for_block(wadpath, mapname):
    """`compile_geometry_streams` and `compile_map` build the same four streams from DIFFERENT
    sources — compile_map masks `bake_bsp`'s vertex tuples, compile_geometry_streams masks the
    WAD's vertex objects. build.py ships the former as F6's collision data (D1) while the renderer
    bakes its geometry from bake_bsp, so a divergence means collision and rendering disagree about
    where the walls are. Nothing compares them today."""
    wad = WadFile.from_path(wadpath)
    full = _stream_blocks(compile_map(wad, mapname, mode="streams"))
    geom = _stream_blocks(compile_geometry_streams(wad, mapname))
    pfx = mapname.lower()
    assert set(geom) == {f"{pfx}_{n}" for n in ("vertexes", "linedefs", "sidedefs", "sectors")}, (
        f"compile_geometry_streams emitted {sorted(geom)} -- the collision lump set changed")
    assert set(geom) < set(full), "compile_map no longer emits every geometry stream"
    for label, lines in geom.items():
        assert lines == full[label], f"{label} differs between the two emitters"
        assert len(lines) > 2, f"{label} is empty -- the comparison is vacuous"


def test_negative_field_values_emit_twos_complement_bytes():
    """`compile_map` hands `_bytes_stream` several fields UNMASKED — seg.offset and a linedef's
    v1/v2/flags/special/tag — while only the node coords and vertexes get an explicit & 0xFFFF. So
    the per-byte mask is what makes a negative field emit at all: `value.to_bytes(w, "little")`,
    the obvious simplification, raises OverflowError on every one of them."""
    widths = (1, 2, 4)
    for rec in ((-1, -1, -1), (-2, -32768, -1 << 31), (0, 1, 0x12345678), (255, 65535, -3)):
        text = _bytes_stream("t", [rec], widths)
        got = _decode_stream(text, widths)
        assert got == [v & ((1 << (8 * w)) - 1) for v, w in zip(rec, widths)], (
            f"{rec} did not round-trip as little-endian two's complement: {got}")
    with pytest.raises(OverflowError):
        (-1).to_bytes(2, "little")          # ⚠ the control: why the mask cannot be simplified away
    assert _bytes_stream("t", [(-1,)], (2,)).count("* dw") == 2, "width is not honoured"


def _decode_stream(text, widths):
    raw = [int(x, 16) for x in re.findall(r";(0x[0-9a-fA-F]+) \* dw", text)]
    out, i = [], 0
    for w in widths:
        out.append(sum(raw[i + b] << (8 * b) for b in range(w)))
        i += w
    return out
