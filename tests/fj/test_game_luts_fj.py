"""M7 P8a package D (issues #119 item 5, #121 item 14, #123 R5b; docs/gp-final-plan.md 1.4): EVERY entry of the game
tier's gameplay LUTs looked up TWICE through its own fj lookup on the real flipjump engine, against the Python source
the table is generated from -- the shape of test_monster_tables_fj.py. Until now these were value-checked on the host
only (aimr not at all; ammobcd through a few tics of test_weapon_fj).

Each table is bound to the game tier's emission: the text the emitter's own function returns (aimcode.table_text,
weaponcode.shot_table_fj / bk10_table_fj, hurtcode.tables_fj, projcode.tables_fj, barrelcode.tables_fj,
lootcode.tables_fj, p31_parts' mobview / barview), or -- for the two emitted inline in a parts function -- the exact
generator call in that function's source (ammobcd, dmrnd).

R9: per table, the same comparison with ONE entry of the emitted table mutated (its lowest bit flipped) must fail.
(P8a's own tables -- the knock, the far LOS, mbul per radius -- join this list when their packages land.)
"""
import inspect
from pathlib import Path

import flipjump as fj
import pytest

from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj

ROOT = Path(__file__).resolve().parents[2]
ART = ROOT / "assets" / "freedoom1.wad"
pytestmark = pytest.mark.skipif(not ART.exists(), reason="needs assets/freedoom1.wad")


@pytest.fixture(scope="module")
def ctx():
    from doomfj.config import GAME_CFG
    from doomfj.reference_model import ReferenceModel
    from doomfj.wad import WadFile
    from doomfj.world import World
    mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / "freedoom_e1m1.wad"))
    art = WadFile.from_path(str(ART))
    return dict(rm=ReferenceModel(GAME_CFG), mw=mw, art=art, w=World(mw, "E1M1"))


@pytest.fixture(scope="module")
def p31(ctx):
    """p31_parts at the game tier's modes (test_mobile_rowselect_fj's setup): mobview and barview"""
    from doomfj import monstercode as MC
    from doomfj import wall_renderer as WR
    from doomfj.config import Config
    from doomfj.mapcompiler import bake_bsp
    from doomfj.reference_model import ReferenceModel
    from doomfj.things import baked_thing_mask, drawable_things
    mw, art = ctx["mw"], ctx["art"]
    rm = ReferenceModel(Config())
    cache = {}
    drawable, draw_idx = drawable_things(rm, mw.things("E1M1"), art, cache)
    baked = baked_thing_mask(rm, bake_bsp(mw, "E1M1"), drawable, WR.MONSTER_TYPES)
    rt = [mw.things("E1M1")[w] for w, b in zip(draw_idx, baked) if not b]
    patches = WR.anim_patches(art, WR.anim_frames(mw, "E1M1"))
    anim = {k: (0x100 + i, rm.art_of_lump(art, lump, cache)[2], mir)
            for i, (k, (lump, mir)) in enumerate(sorted(patches.items()))}
    kinds = sorted({t.type for t in drawable})
    static = ({k: 0x900 + i for i, k in enumerate(kinds)}, {k: 0xA00 + i for i, k in enumerate(kinds)},
              {k: rm.sprite_art(art, k, cache)[2] for k in kinds})
    return MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=WR.BOOT_SKILL, skills=WR.SKILLS,
                        cache=cache, mode=WR.MONSTER_MODE, player=WR.PLAYER_MODE, static_bank=static)


def _view_table(p31, key):
    d = p31["mob_view" if key == "mobview" else "bar_view"]
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    return [d.get(i, 0) for i in range(max(d) + 1)], 2, rn, p31[key]


def _source(ctx, p31, label):
    """(values, index nibbles, result nibbles, the emitted text that must hold this table)"""
    from doomfj import aimcode as AC
    from doomfj import barrelcode as BC
    from doomfj import damagecode as DC
    from doomfj import hurtcode as H
    from doomfj import lootcode as LC
    from doomfj import projcode as PC
    from doomfj import weaponcode as WC
    rm, w = ctx["rm"], ctx["w"]
    if label == "aimr":
        return AC.reff_values(rm, True), 2, 6, AC.table_text(rm, True, sprite_wad=ctx["art"])
    if label == "wpo":
        return WC.shot_values(), 2, WC.SHOT_ROW_NIBBLES, WC.shot_table_fj()
    if label == "bk10":
        return LC.bk10_values(), 2, 2, WC.bk10_table_fj()
    if label == "ammobcd":
        src = inspect.getsource(WC.weapon_parts)
        assert 'generate_dispatch_table_fj("ammobcd", ammo_digit_values(), index_nibbles=3, result_nibbles=3)' in src
        return WC.ammo_digit_values(), 3, 3, None
    if label == "dmrnd":
        src = inspect.getsource(DC.damage_parts)
        assert 'generate_dispatch_table_fj("dmrnd", dmrnd_values(pain_classes(keys)),' in src
        assert "keys, of = profiles(w, gib=full)" in src
        return DC.dmrnd_values(DC.pain_classes(DC.profiles(w, gib=True)[0])), 2, 2, None
    hurt = {"mbul": (H.mbul_values(w.hwt), 2, 3), "trclaw": (H.one_draw_values("troop_claw"), 2, 2),
            "sgbite": (H.one_draw_values("sarg_bite"), 2, 2), "dpsav": (H.dpsav_values(), 3, 2),
            "palidx": (H.palidx_values(), 2, 1), "bonpal": (H.bonpal_values(), 2, 1)}
    if label in hurt:
        return hurt[label] + ("\n".join(H.tables_fj(w.hwt, loot=True)),)
    if label in ("fxrnd", "pjst"):
        v = {"fxrnd": (PC.fxrnd_values(), 2, 3), "pjst": (PC.pjst_values(True), 2, 3)}[label]
        return v + ("\n".join(PC.tables_fj(puffs=True)),)
    if label == "barnext":
        return BC.barnext_values(), 2, 4, "\n".join(BC.tables_fj())
    if label in ("amcap", "nkleaf", "pkxyz"):
        v = {"amcap": (LC.amcap_values(), 2, 3), "nkleaf": (LC.nkleaf_values(w), 3, 2),
             "pkxyz": (LC.pkxyz_values(w), 2, 12)}[label]
        return v + ("\n".join(LC.tables_fj(w)),)
    if label in ("mobview", "barview"):
        return _view_table(p31, label)
    raise KeyError(label)


TABLES = ("aimr", "wpo", "dmrnd", "ammobcd", "mbul", "trclaw", "sgbite", "dpsav", "palidx", "fxrnd", "pjst",
          "mobview", "barnext", "bk10", "bonpal", "amcap", "nkleaf", "pkxyz", "barview")


def _run(tmp_path, name, label, values, idx_n, res_n, emitted_values=None, entries=None) -> bool:
    """every entry in `entries` (default all) looked up twice and printed; True iff the output is the Python source's"""
    entries = range(len(values)) if entries is None else entries
    body, data = [], []
    for k in entries:
        for _ in range(2):
            body += [f"{label}.lookup rdst, idx{k}", f"hex.print_as_digit {res_n}, rdst, 0", "stl.output 10"]
        data.append(f"idx{k}: hex.vec {idx_n}, {k}")
    data.append(f"rdst: hex.vec {res_n}")
    expected = "".join(f"{values[k]:0{res_n}x}\n" * 2 for k in entries).encode()
    table = generate_dispatch_table_fj(label, emitted_values if emitted_values is not None else values,
                                       index_nibbles=idx_n, result_nibbles=res_n)
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data + [table]) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    return fj.assemble_and_run_test_output([p.resolve()], b"", expected, memory_width=W,
                                           warning_as_errors=True, should_raise_assertion_error=False)


@pytest.mark.parametrize("label", TABLES)
def test_the_table_is_the_game_tiers(ctx, p31, label):
    """the generator's text for (values, widths) is what the emitter's own function returns"""
    vals, idx_n, res_n, emitted = _source(ctx, p31, label)
    assert vals and max(vals) < 16 ** res_n and len(vals) <= 16 ** idx_n, label
    if emitted is not None:
        assert generate_dispatch_table_fj(label, vals, index_nibbles=idx_n, result_nibbles=res_n) in emitted, label


@pytest.mark.parametrize("label", TABLES)
def test_every_entry_equals_its_python_source(tmp_path, ctx, p31, label):
    vals, idx_n, res_n, _ = _source(ctx, p31, label)
    assert _run(tmp_path, label, label, vals, idx_n, res_n), f"{label}: fj lookups != the Python source"


@pytest.mark.parametrize("label", TABLES)
def test_control_a_mutated_entry_is_caught(tmp_path, ctx, p31, label):
    """R9: the middle entry's lowest bit flipped in the EMITTED table -- the comparison (over the entries around it)
    must fail"""
    vals, idx_n, res_n, _ = _source(ctx, p31, label)
    k = len(vals) // 2
    bad = list(vals)
    bad[k] ^= 1
    near = range(max(0, k - 2), min(len(vals), k + 3))
    assert _run(tmp_path, label + "_ok", label, vals, idx_n, res_n, entries=near), "the subset run itself fails"
    assert not _run(tmp_path, label + "_mut", label, vals, idx_n, res_n, emitted_values=bad, entries=near), (
        "%s: a mutated entry passed -- the comparison is vacuous" % label)
