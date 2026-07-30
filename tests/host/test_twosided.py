"""M13-2S host gates for `ReferenceModel.render_frame_2s` — the two-sided wall + plane-region model.

These encode the two defects the owner's playtest exposed, so neither can come back silently:
  1. two-sided linedefs were skipped entirely (72% of E1M1's segs), so every step face, ledge front
     and door frame was missing;
  2. a column's plane record came from whichever WALL claimed the column, so one continuous floor
     was painted in several shades depending on which distant wall happened to claim each column.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state
from doomfj.wad import WadFile

ROOM = str(ROOT / "tests/fixtures/square_room.wad")
ASSET = str(ROOT / "tests/fixtures/freedoom_assets.wad")
E1M1 = str(ROOT / "tests/fixtures/freedoom_e1m1.wad")


def _spawn(mw, mapname):
    sp = spawn_state(mw, mapname)
    return SimState(sp.x, sp.y, sp.angle, mapname)


def test_2s_square_room_leaves_no_hole():
    """The square room is fully enclosed, so the window model must close EVERY column: any pixel
    left at the zero fill would mean a clip range was mishandled (the failure mode that shows up as
    black gaps through geometry)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(ROOM)
    scene = build_scene(mw, WadFile.from_path(ASSET), "MAP01")
    for va in (0, 0x20000000, 0x40000000):
        sp = spawn_state(mw, "MAP01")
        fb = rm.render_frame_2s(SimState(sp.x, sp.y, va, "MAP01"), scene)
        assert len(fb) == cfg.FB_SIZE
        holes = sum(1 for b in fb if b == 0)
        assert holes == 0, f"{holes} unpainted pixels at angle {va:#x} -- a clip range is wrong"


def test_2s_draws_the_two_sided_surfaces():
    """E1M1 spawn: the two-sided model must actually paint substantially more wall surface than the
    one-sided renderer. At the time of writing the missing two-sided area (~40% of the screen)
    exceeded the drawn one-sided area (~35%), so the frames differ in thousands of pixels."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    st = _spawn(mw, "E1M1")
    one = rm.render_wall_frame(st, scene, floor_texturing=False, wall_mode="WPX",
                              floor_mode_ft1=True)
    two = rm.render_frame_2s(st, scene)
    differing = sum(1 for a, b in zip(one, two) if a != b)
    assert differing > 3000, f"only {differing} px differ -- two-sided surfaces are not being drawn"


def _planes(rm, st, scene, **kw):
    """render_wall_frame + its per-column plane records (ceil_hi, floor_lo, ch, fh, lt, cf, ff)."""
    out: list = []
    fb = rm.render_wall_frame(st, scene, floor_texturing=False, wall_mode="WPX",
                              floor_mode_ft1=True, planes_out=out, **kw)
    return fb, out[0]


def test_plane_near_claims_every_column_for_the_player_sector():
    """M13-2S rung 3a. The owner's report: "the close floor in the middle is gray, yet the sides are
    yellow... it should all be the same yellowish colour". Cause (docs/handoff-m13-2s.md §2): the
    per-column plane record is taken from whichever wall CLAIMS the column, and since the two-sided
    boundaries of the player's own sector were skipped, distant walls claimed most columns.

    With `plane_near` the nearest MARKING seg claims the column instead -- marking = the seg's two
    sides differ in the band-bank key (height, light, flat), DOOM's R_StoreWallRange
    markfloor/markceiling test. At E1M1 spawn that must attribute all 160 columns to the sector the
    player is standing in, for BOTH the floor and the ceiling."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    st = _spawn(mw, "E1M1")
    _fb, (_ch_hi, _f_lo, col_ch, col_fh, col_lt, col_cf, col_ff) = _planes(
        rm, st, scene, plane_near=True)
    floors = {(col_fh[x], col_lt[x], col_ff[x]) for x in range(cfg.VIEW_W)}
    ceils = {(col_ch[x], col_lt[x], col_cf[x]) for x in range(cfg.VIEW_W)}
    assert floors == {(0, 192, "AQF054")}, f"near floor still attributed to {len(floors)} surfaces: {floors}"
    assert ceils == {(128, 192, "SLIME14")}, f"near ceiling attributed to {len(ceils)} surfaces: {ceils}"


def test_plane_near_leaves_one_colour_per_near_floor_row():
    """The same fix seen in PIXELS: within one row every floor pixel is at the same distance on the
    same surface, so once attribution is right the row's floor is ONE colour. Measured before the
    fix: 6 distinct floor colours on those rows (three flats at two light levels)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    st = _spawn(mw, "E1M1")
    W = cfg.VIEW_W
    fb, (_c, floor_lo, *_rest) = _planes(rm, st, scene, plane_near=True)
    for y in range(cfg.VIEW_H - 12, cfg.VIEW_H):
        shades = {fb[y * W + x] for x in range(W) if y >= floor_lo[x]}
        assert len(shades) == 1, f"row {y}: {len(shades)} floor colours, expected 1 ({sorted(shades)})"


def test_plane_near_is_opt_in_and_changes_the_frame():
    """`plane_near` must be OFF by default -- `render_wall_frame` still feeds the tiers with stored
    goldens -- and must actually change the frame when ON (else the gates above pass vacuously)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    st = _spawn(mw, "E1M1")
    default = rm.render_wall_frame(st, scene, floor_texturing=False, wall_mode="WPX",
                                   floor_mode_ft1=True)
    off, _ = _planes(rm, st, scene)
    near, _ = _planes(rm, st, scene, plane_near=True)
    assert off == default, "planes_out must not change what is rendered"
    differing = sum(1 for a, b in zip(off, near) if a != b)
    assert differing > 2000, f"only {differing} px differ -- the near attribution did nothing"


def test_2s_near_floor_is_not_split_into_extra_shades():
    """THE owner-reported defect, as a guard: on the rows closest to the player the floor underfoot
    is one surface at one distance, so it must not be broken into MORE shades than the old
    per-column-claim model produced. Measured when written: 6 distinct colours per row before, 4
    after (the residue is genuine -- that floor really does span sectors lit 150/160/192, which DOOM
    shades differently too)."""
    cfg = Config()
    rm = ReferenceModel(cfg)
    mw = WadFile.from_path(E1M1)
    scene = build_scene(mw, mw, "E1M1")
    st = _spawn(mw, "E1M1")
    W = cfg.VIEW_W
    one = rm.render_wall_frame(st, scene, floor_texturing=False, wall_mode="WPX",
                               floor_mode_ft1=True)
    two = rm.render_frame_2s(st, scene)
    for y in (90, 92, 94, 96, 98):
        n_one = len({one[y * W + x] for x in range(W)})
        n_two = len({two[y * W + x] for x in range(W)})
        assert n_two <= n_one, (f"row {y}: two-sided model splits the near floor into {n_two} "
                               f"shades, worse than the {n_one} it replaces")
