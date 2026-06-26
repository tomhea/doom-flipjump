"""M13a (F5) — floors/ceilings as distance-lit **flat-colored** visplanes (the cheaper §1 floor tier).

`render_wall_frame` no longer leaves the M9 two-band background under the walls: when a one-sided wall
claims a column, the rows ABOVE it become that sector's ceiling flat and the rows BELOW its floor flat,
each shaded by a distance-based colormap row (zlight). M13a uses the flat's base index (no per-pixel
texture u,v yet — that's M13b). These host tests pin the new LUT generators (yslope/zlight) and the new
visible behavior; the fj span raster (M13c) diffs against this byte-for-byte.
"""
from doomfj.config import Config
from doomfj.reference_model import ReferenceModel, SimState, build_scene, spawn_state, frame_hash
from doomfj.tables import (
    yslope_table, zlight_table, distscale_table, LIGHTLEVELS, MAXLIGHTZ,
)
from doomfj.wad import WadFile

ROOM = "tests/fixtures/square_room.wad"
ASSET = "tests/fixtures/freedoom_assets.wad"
E1M1 = "tests/fixtures/freedoom_e1m1.wad"
COLORMAP_LIGHTS = 32
WALL_BOT = 75   # the square room's head-on wall covers rows [0,75]; [76,99] is the floor visplane


# ── new LUT generators (yslope / zlight) — value tests, per-entry + call-twice (R5) ──────────

def test_yslope_table_shape_positive_and_peaks_at_horizon():
    cfg = Config()
    ys = yslope_table(cfg.VIEW_W, cfg.VIEW_H)
    assert len(ys) == cfg.VIEW_H
    assert all(isinstance(v, int) and v > 0 for v in ys)        # FixedDiv of positives -> positive 16.16
    # |dy| is smallest at the horizon row (CENTERY) -> the slope (1/|dy|) is largest there
    assert ys[cfg.CENTERY] == max(ys)
    assert yslope_table(cfg.VIEW_W, cfg.VIEW_H) == ys           # deterministic / call-twice (R5)


def test_distscale_table_shape_positive_and_symmetric():
    cfg = Config()
    dz = distscale_table(cfg.VIEW_W, cfg.TRIG_N)
    assert len(dz) == cfg.VIEW_W
    assert all(isinstance(v, int) and v > 0 for v in dz)        # 1/|cos| over the FOV -> positive 16.16
    assert min(dz) >= 1 << 16                                   # 1/cos >= 1 (cos <= 1)
    # the centre column looks straight ahead (cos≈1 -> distscale≈1.0); the edges (±FOV) are larger
    assert dz[cfg.CENTERX] <= dz[0] and dz[cfg.CENTERX] <= dz[cfg.VIEW_W - 1]
    assert distscale_table(cfg.VIEW_W, cfg.TRIG_N) == dz        # deterministic / call-twice (R5)


def test_zlight_table_dims_range_and_darker_with_distance():
    cfg = Config()
    zl = zlight_table(cfg.VIEW_W, COLORMAP_LIGHTS)
    assert len(zl) == LIGHTLEVELS and all(len(r) == MAXLIGHTZ for r in zl)
    assert all(0 <= v < COLORMAP_LIGHTS for r in zl for v in r)
    for r in zl:                                                # farther z bucket -> darker (row index up)
        assert all(r[j + 1] >= r[j] for j in range(MAXLIGHTZ - 1))
    # a brighter light level (higher i) is never darker at the same distance bucket
    for j in range(MAXLIGHTZ):
        assert all(zl[i + 1][j] <= zl[i][j] for i in range(LIGHTLEVELS - 1))
    assert zlight_table(cfg.VIEW_W, COLORMAP_LIGHTS) == zl      # deterministic / call-twice (R5)


# ── new behavior: the floor under a wall is a distance-lit flat, not the M9 two-band bg ───────

def test_square_floor_is_distance_lit_flat_not_two_band_bg():
    """Spawn in the square room facing the head-on north wall (covers rows [0,75]). The floor band
    [76,99] used to be the M9 two-band background (a single constant FLOOR_BG shade). It is now the
    sector's floor flat, distance-lit: it (a) differs from the two-band bg, and (b) varies down the
    column (the zlight gradient — nearer rows brighter)."""
    cfg = Config()
    rm = ReferenceModel()
    scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
    state = spawn_state(WadFile.from_path(ROOM), "MAP01")
    frame = rm.render_wall_frame(state, scene)
    bg = rm.render_frame(state, scene)                          # the old M9 two-band background
    W, H = cfg.VIEW_W, cfg.VIEW_H
    col = W // 2
    band = [frame[y * W + col] for y in range(WALL_BOT + 1, H)]
    assert any(frame[y * W + col] != bg[y * W + col] for y in range(WALL_BOT + 1, H))  # not the two-band bg
    assert len(set(band)) >= 2                                  # distance gradient (not a constant fill)


def test_e1m1_floors_ceilings_replace_the_background():
    """E1M1 spawn: every column is claimed (no black holes) and the floors/ceilings now overwrite the
    M9 background almost everywhere — far more pixels differ from the two-band bg than the walls alone."""
    cfg = Config()
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    state = spawn_state(map_wad, "E1M1")
    frame = rm.render_wall_frame(state, scene)
    bg = rm.render_frame(state, scene)
    W, H = cfg.VIEW_W, cfg.VIEW_H
    assert all(any(frame[y * W + x] != 0 for y in range(H)) for x in range(W))  # no all-zero column
    assert sum(1 for a, b in zip(frame, bg) if a != b) > 12000  # walls+floors+ceilings, not walls alone


# ── M13b: full-res TEXTURED floors/ceilings (the chosen §1 default) ───────────────────────────

def test_textured_floor_differs_from_flat_colored_tier():
    """The default `render_wall_frame` (M13b textured floors) is NOT the M13a flat-colored tier: the
    E1M1 spawn frame differs from `floor_texturing=False` and carries more distinct palette indices (a
    real perspective texture, not one flat shade per region)."""
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    state = spawn_state(map_wad, "E1M1")
    textured = rm.render_wall_frame(state, scene)                       # default = textured (M13b)
    flat = rm.render_wall_frame(state, scene, floor_texturing=False)    # the M13a flat-colored tier
    assert textured != flat
    assert len(set(textured)) > len(set(flat))                         # texturing adds palette variety


def test_square_textured_floor_golden_hash():
    rm = ReferenceModel()
    scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
    assert frame_hash(frame) == "00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12"


def test_e1m1_textured_floor_golden_hash():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene)
    assert frame_hash(frame) == "db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2"


# ── M13a flat-colored tier preserved under floor_texturing=False (the cheaper §1 fallback) ────

def test_square_flatcolored_floor_golden_hash():
    rm = ReferenceModel()
    scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
    frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene, floor_texturing=False)
    assert frame_hash(frame) == "aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463"


def test_e1m1_flatcolored_floor_golden_hash():
    rm = ReferenceModel()
    map_wad = WadFile.from_path(E1M1)
    scene = build_scene(map_wad, map_wad, "E1M1")
    frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene, floor_texturing=False)
    assert frame_hash(frame) == "9569a547c0fef22416fcc3549f0c0bc96bdc1ea3aa8f1eca2b8feae82f576d01"
