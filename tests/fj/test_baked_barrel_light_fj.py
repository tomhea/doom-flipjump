"""M7 P6+P7 (docs/gp-p67-interface.md 5): a BAKED barrel's per-state xor_by block on the real flipjump engine -- the
LIGHT CLASS the record body reads from it.

FOUND by b0 v6 on blocked50 (2026-10-06): R2-barrel-hall parted on frames 21..50, exactly the frames a baked barrel
showed BEXPB0 .. BEXPE0 (a chain of three explosions), 61-1,617 px a frame, off by one or more shade rows. The
explosion lumps are 31 / 40 / 50 / 53 rows tall, so their (light, height) classes come from the moving-things cross
product and run past 255 (279 .. 426 on E1M1), and the block wrote them with `hex.xor_by 2, sp_lt` -- which xors only
the LOW BYTE. frame.thing_record_body reads the class as `2*ltw` = 4 nibbles from `sp_lt` (its second byte
`sp_lt_hi` declared right behind it), so those states drew with class & 0xFF's shade rows.

The program here runs, for every distinct class a baked barrel's state blocks carry (every barrel's sector light x
the seven barrel states' lumps -- `wall_renderer.barrel_state_fields`, the emitter's own helper, on
`_lines_sprite_light`'s real classes), the block exactly as the emitter writes it (`_seg_xorby_block`): SET, the
body's 4-nibble read of `sp_lt`, CLEAR, and the two class bytes again (the involution must leave both zero for the
next thing). R9: the pre-fix text (the class whole in the 2-nibble `sp_lt`, no `sp_lt_hi`) prints the wrong class,
and the emitter's fit guard refuses to emit it."""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.barrelcode import barrel_states
from doomfj.config import Config
from doomfj.harness import W
from doomfj.reference_model import ReferenceModel
from doomfj.wall_renderer import THING_XORBY_FIELDS, _seg_xorby_block, barrel_state_fields

ROOT = Path(__file__).resolve().parents[2]
WR = ROOT / "src" / "doomfj" / "wall_renderer.py"


@pytest.fixture(scope="module")
def classes():
    """[(class, fields)] -- one entry per distinct class the baked barrels' non-S_BAR1 state blocks carry"""
    return barrel_light_setup()[1]


def barrel_light_setup():
    """(spr_cls, [(class, fields)]): the emitter's (light, height) -> class map for the game tier's moving things,
    and the distinct classes of the baked barrels' non-S_BAR1 state blocks with their xor_by fields"""
    from doomfj.mapcompiler import bake_bsp
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import (BOOT_SKILL, MONSTER_TYPES, SKILLS, _lines_sprite_light, _thing_sector,
                                      anim_frames, anim_patches)
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    cfg = Config()
    rm = ReferenceModel(cfg)
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    cmap = bake_bsp(mw, "E1M1")
    baked = baked_thing_mask(rm, cmap, drawable, MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    rt = [mw.things("E1M1")[w] for w in keep]
    patches = anim_patches(art, anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + i, rm.art_of_lump(art, lump, cache)[2], mir) for i, (k, (lump, mir)) in
            enumerate(sorted(patches.items()))}
    kinds = sorted({t.type for t in drawable})
    static = ({k: 0x900 + i for i, k in enumerate(kinds)}, {k: 0xA00 + i for i, k in enumerate(kinds)},
              {k: rm.sprite_art(art, k, cache)[2] for k in kinds})
    p31 = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=BOOT_SKILL, skills=SKILLS,
                       cache=cache, mode="full", player="full", static_bank=static)
    lds, sds, secs = mw.linedefs("E1M1"), mw.sidedefs("E1M1"), mw.sectors("E1M1")
    _bank, spr_cls = _lines_sprite_light(rm, cfg, art, mw, "E1M1", cmap, lds, sds, secs, moving_things=True,
                                         extra_heights=p31["view_heights"])
    tfields = [(n, w_, 0) for n, w_ in THING_XORBY_FIELDS]
    nt = len(rt)
    out = {}
    for t in p31["world"].barrel_things:
        sec = _thing_sector(rm, cmap, lds, sds, secs, t)
        for st in barrel_states()[1:]:
            r = p31["view_rows"][p31["bar_view"][gd.STATE_INDEX[st]] - nt]
            cls = spr_cls[(rm.wall_lightnum(sec.light, 0), max(1, r[2]))]
            out.setdefault(cls, barrel_state_fields(tfields, r, sec.floor_h, cls))
    return spr_cls, sorted(out.items())


DECLS = ["xb_ret: ;0", "sp_x: hex.vec 8", "sp_y: hex.vec 8", "sp_z: hex.vec 8", "sp_left: hex.vec 8",
         "sp_w: hex.vec 8", "sp_hh: hex.vec 8", "sp_base: hex.vec 4", "sp_dw: hex.vec 2", "sp_lt: hex.vec 2",
         "sp_lt_hi: hex.vec 2", "sp_tzmax: hex.vec 8", "sp_mon: hex.vec 2", "sp_tzmax2: hex.vec 8",
         "sp_base2: hex.vec 4", "cls_rd: hex.vec 4"]


def _run(tmp_path, name, blocks) -> bool:
    """blocks: [(class, block lines)] -- SET, read the class as the record body does, CLEAR, read it again"""
    body, data, want = ["stl.startup_and_init_all"], list(DECLS), ""
    for i, (cls, lines) in enumerate(blocks):
        label = lines[0].strip().rstrip(":")
        body += [f"    stl.fcall {label}, xb_ret",
                 "    hex.mov 4, cls_rd, sp_lt",                 # frame.thing_record_body: hex.mov 2*ltw, ..., sp_lt
                 "    hex.print_as_digit 4, cls_rd, 0",
                 f"    stl.fcall {label}, xb_ret",
                 "    hex.mov 4, cls_rd, sp_lt",
                 "    hex.print_as_digit 4, cls_rd, 0", "    stl.output 10"]
        data += lines
        want += "%04x0000\n" % cls
    body.append("    stl.loop")
    p = tmp_path / f"{name}.fj"
    p.write_text("\n".join(body + data) + "\n", encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    return fj.assemble_and_run_test_output([consts.resolve(), p.resolve()], b"", want.encode(), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_case_reaches_past_one_byte(classes):
    assert any(c > 0xFF for c, _f in classes), "no baked barrel state has a class past 255: the case is vacuous"
    # the record body's read is 4 nibbles from sp_lt, so sp_lt_hi must be declared right behind sp_lt
    src = WR.read_text(encoding="utf-8")
    assert src.index('"sp_lt: hex.vec 2",') < src.index('*(["sp_lt_hi: hex.vec 2"] if _ANIM else [])') < src.index(
        '"sp_tzmax: hex.vec 8"')


def test_every_baked_barrel_state_carries_its_whole_light_class(tmp_path, classes):
    blocks = [(c, _seg_xorby_block("bbl%d" % k, f)) for k, (c, f) in enumerate(classes)]
    assert _run(tmp_path, "bblight", blocks), "a baked barrel state's light class parted (or did not clear)"


def test_control_the_class_in_one_byte_is_caught(tmp_path, classes):
    """the pre-fix text: the whole class xored into the 2-nibble sp_lt, sp_lt_hi untouched"""
    old = [(c, [(n, w_, c) if n == "sp_lt" else (n, w_, v) for n, w_, v in f if n != "sp_lt_hi"])
           for c, f in classes]
    big = next(f for c, f in old if c > 0xFF)
    with pytest.raises(AssertionError, match="does not fit"):
        _seg_xorby_block("bbl_old", big)                     # the emitter refuses to write it now
    blocks = [(c, ["  bbo%d:" % k] + ["    hex.xor_by %d, %s, %d" % (w_, n, v) for n, w_, v in f]
               + ["    stl.fret xb_ret"]) for k, (c, f) in enumerate(old)]
    assert not _run(tmp_path, "bblight_old", blocks), "the truncated class was not caught"
