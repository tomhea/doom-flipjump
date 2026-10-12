"""P10 (the owner's play-test, 2026-10-12) -- the oracle's column BASES (G2) and fragment CLIP WINDOWS (G1), in
`ReferenceModel.render_wall_frame`.

G2: "the nukage vanishes near its edge". A boundary whose near edge is OFF the screen -- above it for a ceiling, below
it for a floor -- stores no piece, yet everything of that surface the column shows lies beyond it: the column records
the boundary's back sector as its base, and the base region shows that sector's surface (`bases_out`).

G1: "monsters on a lower floor are drawn over the nearer ledge". A sprite fragment keeps only the rows the boundaries
NEARER than its thing leave open -- the last nearer upper piece's end + 1 down to the last nearer lower piece's start,
snapshotted when the fragment records.

The fj mirror of both is held byte-exact by scratchpad/gp/edge_gate.py (the visual tier) and the game gates. Here, R9:
each feature is checked against a copy of reference_model with its lines disabled -- at the views chosen for it the
picture must differ, so a reverted feature fails, and nothing may differ where the feature has nothing to do.
"""
import sys
import types
from pathlib import Path

import pytest

from doomfj import reference_model as RM
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene
from doomfj.wad import WadFile

ROOT = Path(__file__).resolve().parents[2]
CFG = Config()
KW = dict(wall_mode="W1R", floor_mode_ft1=True, plane_near=True, wall_noise=True, near_steps=True,
          stack_steps=True, things=True, degrade=True, sky=True, bbox_cull=True)
# the edge gate's G2 views (scratchpad/gp/edge_gate.py): line 101's nukage edge, ~40 units off it
POOL_BANK = (1688, 1357, 0xAF8091A2)        # on the courtyard (sector 18), facing the pool (sector 173)
POOL_IN = (1656, 1283, 0x2F8091A2)          # in the pool, facing the courtyard
# the edge gate's G1 views: a monster on the courtyard ledge (floor 24) seen from its foot (-88), and one in the pit
# (-160) seen from above (48) -- the clip moves 887 / 820 px
LEDGE_VIEWS = ((2018, 884, 0xEABF52E4), (1974, 1408, 0x80000000))
# the edge gate's G3 views: three map things share columns there (the third slot moves 144 / 121 px)
THREE_DEEP = ((2198, -159, 0xFFD64759), (639, 271, 0x20000000))


@pytest.fixture(scope="module")
def world():
    mw = WadFile.from_path(str(ROOT / "tests/fixtures/freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets/freedoom1.wad"))
    return build_scene(mw, mw, "E1M1"), art


def _without(*lines):
    """reference_model with each of `lines` (an `if` condition) made `if False:` -- a feature switched off"""
    src = Path(RM.__file__).read_text(encoding="utf-8")
    for line in lines:
        assert src.count(line) >= 1, line
        src = src.replace(line, "if False:" + line.split(":", 1)[1])
    name = "doomfj._rm_without_%d" % abs(hash(lines))
    mod = types.ModuleType(name)
    mod.__file__ = RM.__file__
    sys.modules[name] = mod
    exec(compile(src, RM.__file__, "exec"), mod.__dict__)
    return mod.ReferenceModel(CFG)


def _two_slots():
    """reference_model with the third fragment slot off: the two-slot early exit put back"""
    src = Path(RM.__file__).read_text(encoding="utf-8")
    line = "if drawn[x] or sfrag3[x] is not None:"
    assert src.count(line) == 1, line
    src = src.replace(line, "if drawn[x] or sfrag2[x] is not None:")
    mod = types.ModuleType("doomfj._rm_two_slots")
    mod.__file__ = RM.__file__
    sys.modules[mod.__name__] = mod
    exec(compile(src, RM.__file__, "exec"), mod.__dict__)
    return mod.ReferenceModel(CFG)


def _render(model, scene, art, view, **extra):
    vx, vy, va = view
    st = SimState((vx << 16) & 0xFFFFFFFF, (vy << 16) & 0xFFFFFFFF, va, "E1M1")
    return model.render_wall_frame(st, scene, sprite_wad=art, **dict(KW, **extra))


def test_a_pool_edge_below_the_screen_paints_the_pool(world):
    """On the bank, facing the pool: the edge (a LIP: the pool is 8 units lower) is below the screen, so no piece --
    and every column's floor base is the pool. The base region is then the pool's flat, where the model without the
    base paint draws the bank's floor all the way out to the far edge (the owner's report)."""
    scene, art = world
    bases = []
    with_ = _render(ReferenceModel(CFG), scene, art, POOL_BANK, bases_out=bases)
    cbase, fbase = bases[0]
    pool = [x for x, s in enumerate(fbase) if s is not None and s.floor_tex == "NUKAGE1"]
    assert len(pool) >= CFG.VIEW_W // 2, "the pool is the floor base in %d columns only" % len(pool)
    plain = _render(_without("if cbase[x] is not None:", "if fbase[x] is not None:"), scene, art, POOL_BANK)
    moved = {i % CFG.VIEW_W for i, (a, b) in enumerate(zip(with_, plain)) if a != b}
    assert moved, "the base paint moved no pixel at the pool's bank -- the view does not exercise it"
    assert moved <= {x for x, s in enumerate(fbase) if s is not None} | {x for x, s in enumerate(cbase) if s is not None}, (
        "pixels moved in columns with no base")


def test_a_riser_below_the_screen_shows_the_floor_beyond_it(world):
    """In the pool, facing the bank: the edge is a RISER (8 units up), wholly below the screen -- the floor shown is
    the bank's beyond it, not the pool's around the player."""
    scene, art = world
    bases = []
    _render(ReferenceModel(CFG), scene, art, POOL_IN, bases_out=bases)
    fbase = bases[0][1]
    flats = {s.floor_tex for s in fbase if s is not None}
    assert flats and "NUKAGE1" not in flats, flats


def test_no_base_is_recorded_without_the_stacked_pieces(world):
    """the bases are V5's (`stack_steps`): the single-piece tier keeps its picture"""
    scene, art = world
    bases = []
    kw = dict(KW, stack_steps=False)
    vx, vy, va = POOL_BANK
    ReferenceModel(CFG).render_wall_frame(SimState(vx << 16, vy << 16, va, "E1M1"), scene, sprite_wad=art,
                                          bases_out=bases, **kw)
    assert all(s is None for side in bases[0] for s in side)


def test_a_third_sprite_shows_where_the_two_nearer_leave_rows(world):
    """G3 (sprites "blink out"): where three things share columns, the two-slot model loses the third outright, and the
    model draws its rows that the two nearer fragments leave to the background -- at each view, a different picture"""
    scene, art = world
    two = _two_slots()
    for view in THREE_DEEP:
        three = _render(ReferenceModel(CFG), scene, art, view)
        plain = _render(two, scene, art, view)
        assert any(a != b for a, b in zip(three, plain)), "the third slot moved no pixel at %r" % (view,)


def test_the_third_slot_changes_nothing_where_no_column_holds_three(world):
    """... and nothing at all where no column holds three fragments: the pool views have none"""
    scene, art = world
    two = _two_slots()
    for view in (POOL_BANK, POOL_IN):
        assert _render(ReferenceModel(CFG), scene, art, view) == _render(two, scene, art, view)


def test_a_sprite_behind_a_nearer_ledge_keeps_only_the_rows_the_ledge_leaves(world):
    """G1 (the owner's ledge bug): the model without the G1 snapshot draws the monster over the nearer ledge; the model
    cuts it -- and every row it cuts shows exactly what is behind the sprite (the picture without the things), since a
    farther fragment snapshots at least the same nearer pieces and is cut there too"""
    scene, art = world
    plain_model = _without("if stack_steps:                # P10 G1")
    for view in LEDGE_VIEWS:
        cut = _render(ReferenceModel(CFG), scene, art, view)
        plain = _render(plain_model, scene, art, view)
        bare = _render(ReferenceModel(CFG), scene, art, view, things=False)
        moved = [i for i, (a, b) in enumerate(zip(cut, plain)) if a != b]
        assert moved, "the ledge clip moved no pixel at %r" % (view,)
        assert all(cut[i] == bare[i] for i in moved), "a cut row shows something other than what is behind it"
