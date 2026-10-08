"""M7 P5 (docs/gp-p5-interface.md, THE MOBILE ROWS): the row select (monstercode.p31_parts' `thsel_leaf`, emitted at the
game tier's model modes wall_renderer.MONSTER_MODE / PLAYER_MODE) on the real flipjump engine, for every MOBILE --
runtime things nt .. nt + 9, the fireball slots then the blood slots -- in every pool state: the row it selects must
be the one whose art is the state's frame at rotation 0 (`monsters.mobile_lump`, the oracle's lump), and the stub must
leave the thing with no seen flag and aim id 0 (never seen, never aimed) whatever the registers held.

Expected rows are identified by the BANK REGION each carries (a stand-in anim index gives every lump a distinct base:
the region is the one thing that names the lump, two lumps can share an art box), so the check does not read the
`mobview` table the code reads. The rows' other fields are the oracle's draw rule (tests/host/test_p5_splice.py).
R9: a mutated `mobview` (every mobile row one off) and a stub reading the other pool's state cell must fail."""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.monsters import mobile_lump
from doomfj.reference_model import SLOPERANGE, ReferenceModel
from doomfj.tables import slopediv_recip8_table, tantoangle_table
from doomfj.wall_renderer import hoisted_scratch_fj

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"


@pytest.fixture(scope="module")
def setup():
    from doomfj.mapcompiler import bake_bsp
    from doomfj.things import baked_thing_mask, drawable_things
    from doomfj.wad import WadFile
    from doomfj.wall_renderer import (BOOT_SKILL, MONSTER_MODE, MONSTER_TYPES, PLAYER_MODE, SKILLS, anim_frames,
                                      anim_patches)
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, MONSTER_TYPES)
    keep = sorted(i for i, b in zip(draw_idx, baked) if not b)
    rt = [mw.things("E1M1")[w] for w in keep]
    patches = anim_patches(art, anim_frames(mw, "E1M1"))
    # a stand-in anim index: the real widths, a DISTINCT region per view (what names a lump below)
    anim = {k: (0x100 + i, rm.art_of_lump(art, lump, cache)[2], mir) for i, (k, (lump, mir)) in
            enumerate(sorted(patches.items()))}
    # M7 P6 (PLAYER_MODE "full"): the drops draw from the STATIC bank -- a synthetic one, as test_barrel_rowselect_fj's
    _kinds = sorted({t.type for t in drawable_things(rm, mw.things("E1M1"), art, cache)[0]})
    _static = ({k: 0x900 + i for i, k in enumerate(_kinds)}, {k: 0xA00 + i for i, k in enumerate(_kinds)},
               {k: rm.sprite_art(art, k, cache)[2] for k in _kinds})
    p31 = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=BOOT_SKILL, skills=SKILLS,
                       cache=cache, mode=MONSTER_MODE, player=PLAYER_MODE, static_bank=_static)
    return rt, anim, p31


def _cases():
    """(fireball states, blood states) -- three rounds that put every pool state in every slot of its pool"""
    from doomfj import projcode as PC
    pj = [s for s in PC.chain("S_TBALL1") + PC.chain("S_TBALLX1")]
    bl = PC.chain("S_BLOOD1")
    return [([pj[(s + k) % len(pj)] for s in range(8)], [bl[(s + k) % len(bl)] for s in range(2)]) for k in range(5)]


def _run(tmp_path, name, setup, mobview=None, swap_pools=False) -> bool:
    rt, anim, p31 = setup
    nt, nmob = len(rt), p31["nmob"]
    assert nmob == 10
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    fmt = "%0" + str(rn) + "x"
    region = {r[6]: p31["mob_first"] + k for k, r in enumerate(p31["view_rows"][p31["mob_first"] - nt:])}
    body, expected = ["stl.startup_and_init_all"], []
    for pj, bl in _cases():
        body += ["hex.set %d, pj_st, %d" % (2 * 8, sum(gd.STATE_INDEX[s] << (8 * k) for k, s in enumerate(pj))),
                 "hex.set %d, fx_st, %d" % (2 * 2, sum(gd.STATE_INDEX[s] << (8 * k) for k, s in enumerate(bl)))]
        for k, st in enumerate(pj + bl):
            body += ["hex.set w/4, sp_ti, %d" % (nt + k), "hex.set w/4, sp_sa, 0x5a5", "hex.set 2, sp_sid, 0x77",
                     "stl.fcall thsel_leaf, thsel_ret",
                     "hex.print_as_digit %d, sp_ti, 0" % rn, "hex.print_as_digit 3, sp_sa, 0",
                     "hex.print_as_digit 2, sp_sid, 0"]
            lump = mobile_lump(st)
            expected.append(fmt % region[anim[(lump[:4], lump[4], 0)][0]] + "000" + "00")
        body.append("stl.output 10")
        expected.append("\n")
    body.append("stl.loop")
    sel = list(p31["select"])
    if swap_pools:
        sel = [ln.replace("pj_st +", "@@").replace("fx_st +", "pj_st +").replace("@@", "fx_st +") for ln in sel]
    nmon = p31["nmon"]
    data = ["viewx: hex.vec 8", "viewy: hex.vec 8", "sp_ti: hex.vec w/4", "sp_x: hex.vec 8", "sp_y: hex.vec 8",
            "sp_sa: hex.vec w/4", "sp_sid: hex.vec 2", "sp_rc: hex.vec 1",
            "thseen: hex.vec %d" % nmon, "mon_shootable: hex.vec %d" % nmon,
            "pj_st: hex.vec 16", "fx_st: hex.vec 4"]
    # M7 P6 (PLAYER_MODE "full"): the select also holds the runtime barrels' stubs (barview, bar_st) --
    # tests/fj/test_barrel_rowselect_fj.py checks those; here they need only assemble
    barrels = "barview" in p31
    if barrels:
        data += ["bar_st: hex.vec %d" % (2 * len(p31["world"].barrel_things))]
    data += list(p31["decls"]) + sel + p31["rotation"]
    # M7 P8a (C, D3): the select writes sp_ex (the scenery-exempt flag) -- declared with the wake decls
    # (monstercode.D3_DECLS), which this harness does not take; here the cells need only exist
    text = "\n".join(sel)
    data += [d for d in MC.D3_DECLS if d.split(":")[0] in text and not any(x.startswith(d.split(":")[0] + ":")
                                                                           for x in data)]
    data += [p31["mview"], p31["mrot"], mobview or p31["mobview"], *([p31["barview"]] if barrels else []),
             generate_dispatch_table_fj("mstate", MC.state_table_values(), index_nibbles=2, result_nibbles=6),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    prog = "\n".join(body + data) + "\n" + hoisted_scratch_fj()
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", "".join(expected).encode(), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_every_mobile_selects_its_state_lump_row(tmp_path, setup):
    assert _run(tmp_path, "mobsel", setup), "a mobile's row select parted from monsters.mobile_lump"


def test_control_a_mutated_mobview_is_caught(tmp_path, setup):
    _rt, _anim, p31 = setup
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    mv = p31["mob_view"]
    vals = [mv.get(i, 0) for i in range(max(mv) + 1)]
    assert generate_dispatch_table_fj("mobview", vals, index_nibbles=2, result_nibbles=rn) == p31["mobview"]
    bad = generate_dispatch_table_fj("mobview", [v + 1 if v else v for v in vals], index_nibbles=2, result_nibbles=rn)
    assert not _run(tmp_path, "mobsel_mut", setup, mobview=bad), "a mutated mobview passed: the check is vacuous"


def test_control_the_other_pools_state_is_caught(tmp_path, setup):
    assert not _run(tmp_path, "mobsel_swap", setup, swap_pools=True), (
        "stubs reading the other pool's state cell passed: the slots are not told apart")
