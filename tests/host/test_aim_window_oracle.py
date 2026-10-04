"""M7 P4.2a (host): the ORACLE's aim window -- `render_wall_frame(aim_things=, aim_out=)` (docs/gp-aim-window.md 1,
2.2): per column 72..88 the nearest shootable living monster whose +-r_eff box covers the column while the column is
still open when the walk reaches the monster's leaf.

  (a) on a LIGHT slice of the frozen v5 set (60 frames: three runs' first 20, replayed with the set's own sight
      rule -- the picture renders every frame anyway) the window agrees with `combat.aim_geometric` (monsters only:
      the barrels are P6's) everywhere except a FROZEN list of (run, frame, column) residuals, and every residual is
      the wall-edge class the doc names: the centre-sight shortcut of the geometric aim, in either direction;
  (b) a hand-built case: one monster fills exactly the window columns its box covers; a nearer later arrival
      overwrites; an equal-depth later arrival does not;
  (c) R9 negative controls, each a MUTANT of the real render_wall_frame source: radius + 1, `drawn[]` ignored, and
      "first arrival wins" each change the window -- the first two on the slice, the last on the hand case (it
      changes nothing on the slice: no farther monster arrives first there, which the test states).
"""
import inspect
import json
import random
import re
import sys
import textwrap
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scratchpad" / "gp"), str(ROOT / "scratchpad" / "12m")]
SET_V5 = ROOT / "scratchpad/gp/scenarios/combat_scenarios_v5.json"
ART = ROOT / "assets/freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists() or not SET_V5.exists(),
                                reason="needs assets/freedoom1.wad and the v5 scenario set")

# the LIGHT slice: three runs' first 20 frames -- 60 rendered frames, ~48 with a geometric target at column 80
SLICE = (("R0-west-hall", 20), ("R2-spectre-corridor", 20), ("R0-imp-court", 20))
COL = 80
# THE FROZEN RESIDUALS (run, frame, column) of the slice, measured 2026-10-04 with r_eff in both aims. Every one is
# "edge-closed": the geometric aim's target, whose centre has 2D sight, has a box that reaches behind a solid wall
# edge -- the column was already wall-drawn when the walk reached the monster's leaf. Compared as a LIST (doc 5, T1):
# any movement is a visible diff.
FROZEN_RESIDUALS = {
    ("R2-spectre-corridor", 8): (82, 83, 84, 85, 86, 87, 88),
    ("R2-spectre-corridor", 9): (81, 82, 83, 84, 85, 86, 87, 88),
    ("R2-spectre-corridor", 10): (74, 75, 76, 77, 78),
    ("R2-spectre-corridor", 11): (75, 76, 77, 78),
    ("R2-spectre-corridor", 12): (75, 76, 77, 78),
    ("R2-spectre-corridor", 13): (77, 78),
    ("R2-spectre-corridor", 14): (77,),
    ("R2-spectre-corridor", 16): (80, 81),
    ("R0-imp-court", 0): (81, 82),
}


# ---------------------------------------------------------------------------------------------- mutants (R9)
def _method_source():
    from doomfj.reference_model import ReferenceModel
    return inspect.getsource(ReferenceModel.render_wall_frame)


def _compile(src: str, extra=None):
    from doomfj import reference_model as RMOD
    g = dict(vars(RMOD))
    g.update(extra or {})
    exec(compile(textwrap.dedent(src), "render_wall_frame_mutant", "exec"), g)
    return g["render_wall_frame"]


def mutant(edits):
    """render_wall_frame with each (old, new) applied -- each `old` must occur EXACTLY once, so a control cannot go
    vacuous by missing its target after an edit to the hook"""
    src = _method_source()
    for old, new in edits:
        assert src.count(old) == 1, f"mutant anchor {old!r} occurs {src.count(old)} times"
        src = src.replace(old, new)
    return _compile(src)


MUTANTS = {
    "radius+1": [("aim_reff[_ar] = _CM.aim_radius(self, viewangle & ANGLE_MASK, _ar)",
                  "aim_reff[_ar] = _CM.aim_radius(self, viewangle & ANGLE_MASK, _ar + 1)")],
    "no-occlusion": [("if drawn[_ac]:", "if False:")],
    "first-arrival": [("if aim_out[_ak] == 0 or _atzi < aim_tz[_ak]:", "if aim_out[_ak] == 0:")],
}


def logged():
    """render_wall_frame that also logs every boxed aim thing: (sid, x1, x2, tzi, drawn[lo..hi] at the visit)"""
    src = _method_source()
    m = re.search(r"^( *)_atzi = _atz >> 16\n", src, re.M)
    assert m and src.count(m.group(0)) == 1
    src = src.replace(m.group(0), m.group(0) + m.group(1) +
                      "_AIM_LOG.append((_asid, _ax1, _ax2, _atzi, bytes(drawn[aim_lo:aim_hi + 1])))\n")
    log = []
    return _compile(src, {"_AIM_LOG": log}), log


# ---------------------------------------------------------------------------------------------- the slice
class _MonstersOnly:
    """`aim_geometric`'s world with the barrels left out (they are P6's; the window here records monsters)"""

    def __init__(self, w):
        self.w, self.ws, self.rm = w, w.ws, w.rm

    def shootable_targets(self):
        return [t for t in self.w.shootable_targets() if t[0] == "mon"]

    def los_points(self, *a):
        return self.w.los_points(*a)


def _geo(w):
    from doomfj.combat import CombatMixin
    mo = _MonstersOnly(w)
    return [0 if g is None else g[1] + 1
            for g in (CombatMixin.aim_geometric(mo, c) for c in range(w.aim_lo, w.aim_hi + 1))]


@pytest.fixture(scope="module")
def slice_frames():
    import scenarios_v2 as S
    doc = json.loads(SET_V5.read_text(encoding="ascii"))
    saved = S.SIGHT_RULE
    S.use_sight_rule(doc)
    muts = {k: mutant(v) for k, v in MUTANTS.items()}
    log_fn, log = logged()
    frames = []
    try:
        for name, n in SLICE:
            run = next(r for r in doc["runs"] if r["name"] == name)
            w = S.start_world(run["setup"])
            hook = w.seen_hook
            assert hook is not None, "v5 is a seen-rule set: the picture renders every frame"
            phase = types.SimpleNamespace(world=w)
            orig = w.rm.render_wall_frame
            rec = {}

            def rwf(*a, **k):
                at = hook.views.aim_things(phase)
                out = [0] * 17
                pix = orig(*a, **dict(k, aim_things=at, aim_out=out))
                seen0 = set()                     # the window writes ONLY the window: same pixels, same seen set
                assert orig(*a, **dict(k, seen_out=seen0)) == pix and seen0 == k["seen_out"]
                rec.update(win=out, geo=_geo(w), at=at, mut={})
                for mk, fn in muts.items():
                    o = [0] * 17
                    fn(w.rm, *a, **dict(k, seen_out=set(), aim_things=at, aim_out=o))
                    rec["mut"][mk] = o
                rec["log"] = None
                if out != rec["geo"]:
                    log.clear()
                    o = [0] * 17
                    assert log_fn(w.rm, *a, **dict(k, seen_out=set(), aim_things=at, aim_out=o)) == pix
                    assert o == out, "the logging copy is not the oracle"
                    rec["log"] = list(log)
                ws = w.ws
                rec["los"] = {m + 1: w.los_points((ws.px, ws.py), (x << 16, y << 16))
                              for kind, m, x, y, _r in w.shootable_targets() if kind == "mon"}
                return pix
            w.rm.render_wall_frame = rwf
            try:
                for f, s in enumerate(run["keys"][:n]):
                    rec.clear()
                    w.tic(S.str_to_keys(s))
                    assert "win" in rec, "the tic rendered no picture"
                    frames.append(dict(rec, run=name, frame=f, lo=w.aim_lo))
            finally:
                del w.rm.render_wall_frame
    finally:
        S.SIGHT_RULE = saved
    return frames


def _residuals(frames):
    out = {}
    for fr in frames:
        cols = tuple(fr["lo"] + i for i in range(17) if fr["win"][i] != fr["geo"][i])
        if cols:
            out[(fr["run"], fr["frame"])] = cols
    return out


def _classify(fr, col):
    """why window and geometric differ at `col`: "edge-closed" (the geometric target's box reaches a column that was
    wall-drawn when the walk reached it; its centre has sight), "edge-centre-blocked" (the window's target is in an
    open column but 2D sight to its centre is blocked -- the doc's class), else "UNEXPLAINED"."""
    i = col - fr["lo"]
    v, g = fr["win"][i], fr["geo"][i]
    if g:
        for sid, x1, x2, _tzi, drawn in fr["log"]:
            if sid == g and x1 <= col <= x2 and drawn[i] and fr["los"][g]:
                return "edge-closed"
    if v and not fr["los"][v]:
        return "edge-centre-blocked"
    return "UNEXPLAINED"


def test_window_agrees_with_geometric_aim_on_the_slice(slice_frames):
    frames = slice_frames
    assert len(frames) == sum(n for _, n in SLICE) == 60
    i80 = COL - frames[0]["lo"]
    assert all(fr["lo"] == frames[0]["lo"] for fr in frames) and frames[0]["lo"] == 72
    with_target = sum(1 for fr in frames if fr["geo"][i80])
    window_hits = sum(1 for fr in frames if fr["win"][i80])
    agree80 = sum(1 for fr in frames if fr["win"][i80] == fr["geo"][i80])
    agree_all = sum(a == b for fr in frames for a, b in zip(fr["win"], fr["geo"]))
    print(f"\n[aim window] {len(frames)} frames; column 80: geometric target in {with_target}, window target in "
          f"{window_hits}, agree {agree80}/{len(frames)}; all 17 columns agree {agree_all}/{17 * len(frames)}")
    assert with_target >= 40 and window_hits >= 40, "the slice has too few targets: the comparison is vacuous"
    res = _residuals(frames)
    classes = {}
    for (run, f), cols in res.items():
        fr = next(x for x in frames if x["run"] == run and x["frame"] == f)
        for c in cols:
            classes.setdefault(_classify(fr, c), []).append((run, f, c, fr["win"][c - 72], fr["geo"][c - 72]))
    for k, v in sorted(classes.items()):
        print(f"[aim window] {k}: {len(v)} column-frames {v}")
    assert "UNEXPLAINED" not in classes, classes["UNEXPLAINED"]
    assert res == FROZEN_RESIDUALS, f"the residual list moved: {res}"


def test_the_controls_change_the_window_on_the_slice(slice_frames):
    """R9: radius + 1 and occlusion off each change the window on some frame of the slice. First arrival is
    counted and reported -- on this slice no farther monster reaches a column before a nearer one, so it changes
    nothing here; `test_hand_built_case` constructs the case where it does."""
    changed = {k: [(fr["run"], fr["frame"]) for fr in slice_frames if fr["mut"][k] != fr["win"]] for k in MUTANTS}
    print("\n[aim window] mutant frames changed:", {k: len(v) for k, v in changed.items()})
    assert changed["radius+1"], "radius + 1 changed no window: the box is not what the window reads"
    assert changed["no-occlusion"], "ignoring drawn[] changed no window: occlusion is not tested"
    assert not changed["first-arrival"], (
        "first-arrival now changes the slice -- good news for the control; move its assert here", changed)


# ---------------------------------------------------------------------------------------------- the hand case
@pytest.fixture(scope="module")
def hand():
    from doomfj import gamedata as gd
    from doomfj.sight import SeenHook
    from doomfj.world import World
    w = World(skill=gd.SK_HARD)
    return w, SeenHook(w)


def _render_hand(w, hook, placed, fn=None):
    """the monsters in `placed` {slot: (x, y)} moved there and the ONLY aim things (every other monster stays where
    it stands, transparent); WAD order inside a leaf (rt_depth_order=False), so the arrival order is the slot order"""
    from doomfj.combat import CombatMixin
    from doomfj.reference_model import SimState
    ws = w.ws
    for m, (x, y) in placed.items():
        ws.mon_x[m], ws.mon_y[m] = x, y
    pos = [(t.x, t.y) for t in hook.drawable]
    hidden = set()
    for m in range(w.layout.nmon):
        pos[hook.views.mdi[m]] = (ws.mon_x[m], ws.mon_y[m])
        if not ws.mon_active[m]:
            hidden.add(hook.views.mdi[m])
    views = [None] * hook.views.n
    for m, v in hook._mviews(w).items():
        views[hook.views.mdi[m]] = v
    at_all = hook.views.aim_things(types.SimpleNamespace(world=w))
    at = {hook.views.mdi[m]: at_all[hook.views.mdi[m]] for m in placed}
    out = [0] * 17
    kw = dict(hook.kw, rt_depth_order=False)
    args = (SimState(ws.px, ws.py, ws.pangle, w.mapname), hook._scene(w))
    kw.update(sprite_wad=hook.art, thing_positions=pos, thing_hidden=hidden, thing_views=views,
              aim_things=at, aim_out=out)
    (fn or type(w.rm).render_wall_frame)(w.rm, *args, **kw)
    geo = []
    for c in range(w.aim_lo, w.aim_hi + 1):
        g = CombatMixin.aim_geometric(_Only(w, placed), c)
        geo.append(0 if g is None else g[1] + 1)
    return out, geo


class _Only(_MonstersOnly):
    def __init__(self, w, slots):
        super().__init__(w)
        self.slots = set(slots)

    def shootable_targets(self):
        return [t for t in super().shootable_targets() if t[1] in self.slots]


def test_hand_built_case(hand):
    w, hook = hand
    ws = w.ws
    A, B = 1, 3                                       # two zombiemen (radius 20), slot 1 arrives before slot 3
    assert w.mon_radius[A] == w.mon_radius[B] == 20 and ws.mon_active[A] and ws.mon_active[B]
    assert hook.views.mdi[A] < hook.views.mdi[B]
    assert ws.pangle == 0, "the case is laid out facing east (tz = the x offset exactly)"
    px, py = ws.px >> 16, ws.py >> 16
    cm = hook._scene(w).cmap
    far, near, beside = (px + 128, py - 24), (px + 100, py - 20), (px + 128, py - 30)
    assert len({w.rm.point_in_subsector(cm, x, y) for x, y in (far, near, beside)}) == 1, \
        "the case needs ONE leaf, so the arrival order is the list order"
    # 1. one monster, right of centre: exactly the window columns its box covers, nothing else
    one, geo = _render_hand(w, hook, {A: far})
    assert one == geo, (one, geo)
    cover = [i for i, v in enumerate(one) if v]
    assert one[cover[0]:] == [A + 1] * (17 - cover[0]) and 0 < cover[0] < 16 and not any(one[:cover[0]]), one
    # 2. a NEARER monster arriving LATER overwrites where the boxes overlap
    two, geo = _render_hand(w, hook, {A: far, B: near})
    assert two == geo, (two, geo)
    both = [i for i in cover if two[i] == B + 1]
    assert both and set(both) <= set(cover), two
    # ... which "first arrival wins" does not (R9: the strictly-nearer rule is what makes this pass)
    fa, _ = _render_hand(w, hook, {A: far, B: near}, mutant(MUTANTS["first-arrival"]))
    assert fa != two and all(fa[i] == A + 1 for i in cover), (fa, two)
    # 3. an EQUAL-depth monster arriving later does not overwrite: the shared columns stay the first arrival's
    eq, geo = _render_hand(w, hook, {A: far, B: beside})
    assert eq == geo, (eq, geo)
    assert eq[:len(one)] == one, (eq, one)            # B's box lies inside A's columns: none of them changes hands
    shared = [i for i in cover if eq[i] == A + 1]
    assert shared == cover


# ---------------------------------------------------------------------------------------------- the pieces
def test_aim_things_and_set_aim(hand):
    from doomfj.monsters import MonsterPhase
    w, hook = hand
    ws = w.ws
    phase = types.SimpleNamespace(world=w)
    at = hook.views.aim_things(phase)
    live = [m for m in range(w.layout.nmon) if ws.mon_active[m] and ws.mon_shootable[m] and ws.mon_health[m] > 0]
    assert at == {hook.views.mdi[m]: (m + 1, w.mon_radius[m]) for m in live}
    assert {r for _sid, r in at.values()} == {20, 30}
    m0 = live[0]
    saved = ws.mon_health[m0]
    ws.mon_health[m0] = 0
    try:
        assert hook.views.mdi[m0] not in hook.views.aim_things(phase), "a dead monster is transparent"
    finally:
        ws.mon_health[m0] = saved
    cells = list(range(17))
    stub = types.SimpleNamespace(world=types.SimpleNamespace(ws=types.SimpleNamespace(aim_sid=[0] * 17)))
    MonsterPhase.set_aim(stub, cells)
    assert stub.world.ws.aim_sid == cells
    with pytest.raises(AssertionError):
        MonsterPhase.set_aim(stub, cells[:16])


def test_window_needs_both_arguments(hand):
    w, hook = hand
    from doomfj.reference_model import SimState
    with pytest.raises(AssertionError, match="go together"):
        w.rm.render_wall_frame(SimState(w.ws.px, w.ws.py, w.ws.pangle, w.mapname), hook._scene(w),
                               sprite_wad=hook.art, aim_out=[0] * 17, **hook.kw)


def test_span_identity():
    """doc 1.4 / T3: fixed_mul(tx -/+ (r<<16), xs) == P -/+ r*xs (mod 2^32) for an integer r -- the identity that
    lets one multiply replace two; a fractional radius breaks it (the control).
    ⚠ fixed_mul reads its first operand SIGNED, so the identity holds while tx -/+ (r<<16) does not cross the signed
    boundary. The window's operands never come near it: |tx| <= tz << 2 <= (2048 << 16) << 2 = 2^29 (the window's
    range and lateral bounds) and r_eff <= 43, so the operands below span exactly that domain, edges included."""
    from doomfj.fixedpoint import fixed_mul
    M = 0xFFFFFFFF
    TXMAX = (2048 << 16) << 2
    rnd = random.Random(42)
    ops = [(rnd.randint(-TXMAX, TXMAX) & M, rnd.getrandbits(22), rnd.choice((20, 28, 30, 42, 43)))
           for _ in range(2000)]
    ops += [(0, 1, 20), (M, 1 << 21, 42), (TXMAX, 0x3FFFFF, 43), (-TXMAX & M, 0x3FFFFF, 43), (1 << 16, 3, 1)]
    for tx, xs, r in ops:
        P = fixed_mul(tx, xs, 8, 4)
        assert fixed_mul((tx - (r << 16)) & M, xs, 8, 4) == (P - r * xs) & M
        assert fixed_mul((tx + (r << 16)) & M, xs, 8, 4) == (P + r * xs) & M
    broke = sum(fixed_mul((tx + (r << 16) + 0x8000) & M, xs, 8, 4) != (P_ + r * xs) & M
                for tx, xs, r in ops[:200] for P_ in [fixed_mul(tx, xs, 8, 4)])
    assert broke > 0, "a half-unit radius did not break the identity: the check is vacuous"
