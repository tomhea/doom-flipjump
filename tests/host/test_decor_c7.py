"""M8 C7 (docs/episode-plan.md section 2): the decorations E1M5..E1M9 add -- 22, 30, 31, 32, 36, 42, 44, 45, 46, 53,
55, 56, 57, 59, 62, 63 -- in the model's tables, the oracle's picture and the emitter's runtime rows.

  * gamedata.THING_TYPES carries info.c's radius, height and flags for each (the RAW file, parsed by script: Chocolate
    Doom at gamedata.SOURCE_COMMIT and id's linuxdoom-1.10, identical); the World blocks at the solid ones -- the
    hanging leg 53 too, at any height, as vanilla's PIT_CheckThing;
  * each is drawn with its SPAWN state's picture (reference_model.THING_SPRITE / THING_SPRITE_FRAME): the dead
    cacodemon is HEAD frame L, never the live HEADA1 a frame-A lookup finds first;
  * a hanging body (MF_SPAWNCEILING) hangs from its sector's ceiling: gamedata.spawn_dz is its z above the floor
    (ceiling - height - floor), the oracle draws it there, and the game tier's RUNTIME rows (`zoff`, which the fj adds
    to the bound leaf's floor) carry it.

R9 controls (each must fail when the rule is removed): the frame-A lookup draws a LIVE cacodemon; a body with no hang
paints below the horizon; the runtime rows built without the hang put every hanging body on its floor.
tests/fj/test_decor_fj.py runs the emitted program (the baked half) against the oracle.
"""
from pathlib import Path

import pytest

from doomfj import gamedata as gd
from doomfj import reference_model as RM
from doomfj.config import Config
from doomfj.wad import Thing, WadFile

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
ROOM = ROOT / "tests" / "fixtures" / "square_room.wad"
ASSET = ROOT / "tests" / "fixtures" / "freedoom_assets.wad"
needs_art = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad (scripts/fetch_freedoom.sh)")

# doomednum: (radius, height, solid, hangs, the spawn picture) -- info.c's mobjinfo[] and spawn states
C7 = {
    22: (20, 16, False, False, "HEADL0"),
    30: (16, 16, True, False, "COL1A0"), 31: (16, 16, True, False, "COL2A0"), 32: (16, 16, True, False, "COL3A0"),
    36: (16, 16, True, False, "COL5A0"), 42: (16, 16, True, False, "FSKUA0"),
    44: (16, 16, True, False, "TBLUA0"), 45: (16, 16, True, False, "TGRNA0"), 46: (16, 16, True, False, "TREDA0"),
    55: (16, 16, True, False, "SMBTA0"), 56: (16, 16, True, False, "SMGTA0"), 57: (16, 16, True, False, "SMRTA0"),
    53: (16, 52, True, True, "GOR5A0"), 59: (20, 84, False, True, "GOR2A0"), 62: (20, 52, False, True, "GOR5A0"),
    63: (20, 68, False, True, "GOR1A0"),
}
HANG = [(64, 200, 59), (128, 200, 53), (192, 200, 63)]            # in the room (floor 0, ceiling 128), ahead of the eye


def _room(extra):
    mw = WadFile.from_path(str(ROOM))
    base = mw.things
    mw.things = lambda name, base=base: base(name) + [Thing(x, y, 0, t, 7) for x, y, t in extra]
    return mw


def test_the_c7_types_carry_info_c_s_values():
    for ty, (radius, height, solid, hangs, _lump) in C7.items():
        tt = gd.THING_TYPES[ty]
        assert (tt.radius, tt.solid, tt.hangs, tt.source) == (radius, solid, hangs, "info.c"), ty
        assert not tt.flags & gd.MF_SPECIAL and ty not in gd.MONSTER_DOOMEDNUMS and ty not in gd.NOT_THINGS, ty
        if hangs:
            assert tt.height == height and tt.flags & gd.MF_NOGRAVITY, ty


def test_spawn_dz_hangs_only_the_ceiling_things():
    assert gd.spawn_dz(59, -72, 64) == 64 - (-72) - 84            # E1M9's gore room: z = ceiling - height
    assert gd.spawn_dz(53, 0, 128) == 128 - 52
    assert gd.spawn_dz(60, 0, 128) == 128 - 68                     # E1M1's (undrawn) body: info.c's height now
    for ty in (22, 30, 44, 2028, 3004, 2035, 12345):              # standing things and an unknown type: the floor
        assert gd.spawn_dz(ty, -72, 64) == 0


@needs_art
def test_each_type_draws_its_spawn_picture():
    art, rm, cache = WadFile.from_path(str(ART)), RM.ReferenceModel(Config()), {}
    for ty, (*_r, lump) in C7.items():
        assert rm.sprite_art(art, ty, cache) == rm.art_of_picture(RM.decode_picture(art.get_data(lump))), ty


@needs_art
def test_control_a_frame_a_lookup_draws_a_live_cacodemon(monkeypatch):
    art, rm = WadFile.from_path(str(ART)), RM.ReferenceModel(Config())
    monkeypatch.setattr(RM, "THING_SPRITE_FRAME", {})
    got = rm.sprite_art(art, 22, {})
    assert got != rm.art_of_picture(RM.decode_picture(art.get_data("HEADL0")))
    assert got == rm.art_of_picture(RM.decode_picture(art.get_data("HEADA1")))


def _sprite_rows(things):
    """the rows the hanging bodies paint: the room with them minus the room without (the start eye, facing north)"""
    art, cfg = WadFile.from_path(str(ART)), Config()
    rm = RM.ReferenceModel(cfg)
    frames = []
    for extra in ([], things):
        mw = _room(extra)
        scene = RM.build_scene(mw, WadFile.from_path(str(ASSET)), "MAP01")
        frames.append(rm.render_wall_frame(RM.spawn_state(mw, "MAP01"), scene, sprite_wad=art,
                                           **{**RM.GAME_RENDER_KW, "sky": False}))
    w = cfg.VIEW_W
    rows = sorted({i // w for i, (a, b) in enumerate(zip(*frames)) if a != b})
    return rows, cfg


@needs_art
def test_the_oracle_hangs_the_bodies_from_the_ceiling():
    """the eye is 41 above the floor and the bodies span ceiling - height .. ceiling >= 44: every row they paint is
    above the horizon"""
    rows, cfg = _sprite_rows(HANG)
    assert rows and max(rows) < cfg.CENTERY, rows


@needs_art
def test_control_unhung_bodies_stand_on_the_floor(monkeypatch):
    monkeypatch.setattr(gd, "spawn_dz", lambda *_a: 0)
    rows, cfg = _sprite_rows(HANG)
    assert rows and max(rows) >= cfg.CENTERY, rows


@needs_art
def test_the_game_tier_s_runtime_rows_carry_the_hang(monkeypatch):
    """the game tier's runtime table: a zombieman shares the room's one leaf, so EVERY thing is a runtime row, whose
    `sp_z` the fj forms as the bound leaf's floor + `zoff`. It must be the oracle's z: floor + spawn_dz + the art's top"""
    from doomfj import things as TH
    from doomfj import wall_renderer as wr
    # the game tier's emitter asks for a full cast: an imp (the fireballs), a zombieman's clip, a sergeant's shotgun
    cast = HANG + [(30, 120, 3001), (200, 100, 3004), (230, 30, 2007), (230, 120, 9), (230, 60, 2001),
                   (60, 60, 2035)] + [(16 + 15 * i, 240, ty) for i, ty in enumerate(sorted(C7))]
    mw = _room(cast)
    seen = []
    real = TH.thing_rows
    monkeypatch.setattr(TH, "thing_rows", lambda *a, **k: seen.append((a, k)) or real(*a, **k))
    art = WadFile.from_path(str(ART))
    wr.emit_wall_renderer(mw, "MAP01", Config(), tier="game", asset_wad=WadFile.from_path(str(ASSET)),
                          sprite_wad=art, return_parts=True)
    assert len(seen) == 1
    a, k = seen[0]
    rows, idx = real(*a, **k)
    allt, rm, cache = mw.things("MAP01"), RM.ReferenceModel(Config()), {}
    hung = [i for i in idx if gd.THING_TYPES[allt[i].type].hangs]
    assert len(hung) == 3 + 4 and len(idx) == len(cast)          # HANG + the four hanging types again

    def bad(rows_):
        out = []
        for r, i in zip(rows_, idx):
            t = allt[i]
            want = gd.spawn_dz(t.type, 0, 128) + rm.sprite_art(art, t.type, cache)[6]
            if 0 + r[3] != want:                                  # the room's floor is 0, its ceiling 128
                out.append(i)
        return out

    assert bad(rows) == []
    # CONTROL: the same rows without the hang -- exactly the hanging bodies sit on the floor
    rows0, _ = real(*a, **{**k, "dz_of": None})
    assert bad(rows0) == hung


def test_the_world_blocks_at_the_solid_decorations():
    from doomfj.world import World
    cast = [(40 + 12 * i, 200, ty) for i, ty in enumerate(sorted(C7))] + [(60, 60, 2035)]
    w = World(_room(cast), "MAP01", monsters="idle")
    assert sorted(t.type for t in w.decor_solid) == sorted(ty for ty, v in C7.items() if v[2])
    assert 53 in {t.type for t in w.decor_solid}                  # the hanging leg blocks at any height (vanilla)
