"""M7 P6 (docs/gp-p67-interface.md 5): the row select (monstercode.p31_parts' `thsel_leaf`, at the monster mode "full"
and the player mode "full") on the real flipjump engine for what P6 adds to the runtime things:

  * the PUFFS: a blood slot in each puff state selects the row of its state's lump (`monsters.mobile_lump`);
  * the DROPS (things nt + nmob + k): each selects its item's row -- the static-bank kind of the item a map thing of
    that type is drawn with -- with no seen flag and aim id 0;
  * the RUNTIME BARRELS (the barrels the bake leaves to the leaf lists): in every barrel state, the row of the state's
    lump, and while the barrel STANDS (S_BAR1 / S_BAR2) its aim id 1 + nmon + b and radius class aimcode.RC_BARREL;
    in an exploding state aim id 0.

Expected rows are identified by the BANK REGION each carries (stand-in anim and static indices give every lump and
every kind a distinct base), so the check does not read the `barview` / `mobview` tables the code reads.
R9: `barview` one row off, a barrel aimed in every state, the drop rows of the two item types swapped, and puffs
missing from `mobview` must each fail."""
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.barrelcode import barrel_states
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
    from doomfj.wall_renderer import BOOT_SKILL, MONSTER_TYPES, SKILLS, anim_frames, anim_patches
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ROOT / "assets" / "freedoom1.wad"))
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, MONSTER_TYPES)
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
    return rt, anim, static, p31


def _program(setup, *, barview=None, mobview=None, select=None):
    rt, anim, (sbase, _sld, _sdw), p31 = setup
    nt, nmob, nmon = len(rt), p31["nmob"], p31["nmon"]
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    fmt = "%0" + str(rn) + "x"
    region = {r[6]: nt + k for k, r in enumerate(p31["view_rows"])}
    body, expected = ["stl.startup_and_init_all"], []

    def probe(t, row, sa, sid, rc):
        body.extend(["hex.set w/4, sp_ti, %d" % t, "hex.set w/4, sp_sa, 0x5a5", "hex.set 2, sp_sid, 0x77",
                     "hex.set 1, sp_rc, 7", "stl.fcall thsel_leaf, thsel_ret",
                     "hex.print_as_digit %d, sp_ti, 0" % rn, "hex.print_as_digit 3, sp_sa, 0",
                     "hex.print_as_digit 2, sp_sid, 0", "hex.print_as_digit 1, sp_rc, 0", "stl.output 10"])
        expected.append(fmt % row + "%03x%02x%x\n" % (sa, sid, rc))

    # the puffs, in a blood slot
    for s in ("S_PUFF1", "S_PUFF2", "S_PUFF3", "S_PUFF4"):
        body.append("hex.set 4, fx_st, %d" % gd.STATE_INDEX[s])
        lump = mobile_lump(s)
        probe(nt + 8, region[anim[(lump[:4], lump[4], 0)][0]], 0, 0, 7)
    # the drops
    from doomfj.barrelcode import droppers
    w = p31["world"]
    for k, m in enumerate(droppers(w)):
        probe(nt + nmob + k, region[sbase[w.dropper[m]]], 0, 0, 7)
    # the runtime barrels, in every state
    assert p31["bar_rt"], "no runtime barrel on E1M1: the stub is never exercised"
    for b, t in sorted(p31["bar_rt"].items()):
        for s in barrel_states():
            body.append("hex.set 2, bar_st + %d*dw, %d" % (2 * b, gd.STATE_INDEX[s]))
            lump = mobile_lump(s)
            stand = s in ("S_BAR1", "S_BAR2")
            probe(t, region[anim[(lump[:4], lump[4], 0)][0]], 0, 1 + nmon + b if stand else 0, 2 if stand else 7)
    body.append("stl.loop")
    nbar = len(w.barrel_things)
    data = ["viewx: hex.vec 8", "viewy: hex.vec 8", "sp_ti: hex.vec w/4", "sp_x: hex.vec 8", "sp_y: hex.vec 8",
            "sp_sa: hex.vec w/4", "sp_sid: hex.vec 2", "sp_rc: hex.vec 1",
            "thseen: hex.vec %d" % nmon, "mon_shootable: hex.vec %d" % nmon,
            "pj_st: hex.vec 16", "fx_st: hex.vec 4", "bar_st: hex.vec %d" % (2 * nbar)]
    data += list(p31["decls"]) + list(select or p31["select"]) + p31["rotation"]
    data += [p31["mview"], p31["mrot"], mobview or p31["mobview"], barview or p31["barview"],
             generate_dispatch_table_fj("mstate", MC.state_table_values(), index_nibbles=2, result_nibbles=6),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    return "\n".join(body + data) + "\n" + hoisted_scratch_fj(), "".join(expected)


def _run(tmp_path, name, setup, **kw) -> bool:
    prog, want = _program(setup, **kw)
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want.encode(), memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


def test_the_rows_of_the_drops_puffs_and_runtime_barrels(setup):
    rt, _anim, _static, p31 = setup
    assert p31["ndrop"] == 25 and p31["nmob"] == 10
    assert len(p31["bar_rows"]) == 7 and sorted(p31["bar_view"]) == [gd.STATE_INDEX[s] for s in barrel_states()]
    assert len(p31["bar_rt"]) == 2, "docs/gp-p67-interface.md: 2 of the 22 barrels are runtime things"
    for r in p31["bar_rows"]:
        assert r[8] == 0 and r[4] != r[5] and r[9] < 0x80                # scenery, graduated, not mirrored
    for ty, row in p31["drop_row"].items():
        r = p31["view_rows"][row - len(rt)]
        assert r[8] == 0 and r[4] == r[5]                                 # scenery, the base bound twice


def test_every_new_runtime_thing_selects_its_row(tmp_path, setup):
    assert _run(tmp_path, "barsel", setup), "a puff's, drop's or runtime barrel's row select parted"


def test_control_a_mutated_barview_is_caught(tmp_path, setup):
    p31 = setup[3]
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    bv = p31["bar_view"]
    vals = [bv.get(i, 0) for i in range(max(bv) + 1)]
    assert generate_dispatch_table_fj("barview", vals, index_nibbles=2, result_nibbles=rn) == p31["barview"]
    bad = generate_dispatch_table_fj("barview", [v + 1 if v else v for v in vals], index_nibbles=2, result_nibbles=rn)
    assert not _run(tmp_path, "barsel_bv", setup, barview=bad)


def test_control_a_barrel_aimed_in_every_state_is_caught(tmp_path, setup):
    sel = [ln for ln in setup[3]["select"] if "thsel_b" not in ln or not ln.strip().startswith("hex.cmp")]
    sel = [ln.replace("  thsel_b", "  thsel_b") for ln in sel]
    assert len(sel) < len(setup[3]["select"])
    assert not _run(tmp_path, "barsel_aim", setup, select=sel)


def test_control_swapped_drop_rows_are_caught(tmp_path, setup):
    p31 = setup[3]
    rows = sorted(p31["drop_row"].values())
    assert len(rows) == 2
    swap = {"sp_ti, %d" % rows[0]: "sp_ti, %d" % rows[1], "sp_ti, %d" % rows[1]: "sp_ti, %d" % rows[0]}
    sel = [next((ln.replace(a, b) for a, b in swap.items() if ln.endswith(a) and "hex.set w/4" in ln), ln)
           for ln in p31["select"]]
    assert sel != list(p31["select"])
    assert not _run(tmp_path, "barsel_drop", setup, select=sel)


def test_control_puffs_missing_from_mobview_are_caught(tmp_path, setup):
    p31 = setup[3]
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    mv = dict(p31["mob_view"])
    for s in ("S_PUFF1", "S_PUFF2", "S_PUFF3", "S_PUFF4"):
        mv[gd.STATE_INDEX[s]] = 0
    bad = generate_dispatch_table_fj("mobview", [mv.get(i, 0) for i in range(max(p31["mob_view"]) + 1)],
                                     index_nibbles=2, result_nibbles=rn)
    assert not _run(tmp_path, "barsel_puff", setup, mobview=bad)
