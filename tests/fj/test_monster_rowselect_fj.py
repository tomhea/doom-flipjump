"""M7 P3.1: the row select (monstercode.p31_parts' `thsel_leaf`) on the real flipjump engine, for EVERY runtime
thing of E1M1: a static thing keeps its own row; a monster's row is the view of its state's frame at DOOM's rotation
for the viewer -- expected from doomfj.monsters' rules (rotation, view_of) and p31's view list, not from the tables
the leaf reads. Pokes: every monster slot in a different state (spawn, see, pain, missile, death) and facing, two
viewers. R9: a mutated mview entry must fail."""
import random
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import gamedata as gd
from doomfj import monstercode as MC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj, generate_tantoangle_lut_fj
from doomfj.monsters import rotation, view_of
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
    # the row select reads no bank region: a stand-in anim_index with the real widths
    anim = {k: (0, rm.art_of_lump(art, lump, cache)[2], mir) for k, (lump, mir) in patches.items()}
    p31 = MC.p31_parts(rm, mw, "E1M1", art, anim, rt, spr_near=True, boot_skill=BOOT_SKILL, skills=SKILLS,
                       cache=cache)
    return rm, rt, patches, p31


def _pokes(p31):
    rnd = random.Random(0x3131)
    n = p31["nmon"]
    from doomfj.world import World
    w = World()
    states, facing = [], []
    for m in range(n):
        info = w.mon_info[m]
        cands = [s for s in (info.spawnstate, info.seestate, info.painstate, info.missilestate, info.meleestate,
                             info.deathstate) if s and s != gd.S_NULL]
        states.append(gd.STATE_INDEX[cands[m % len(cands)]])
        facing.append(rnd.randrange(8))
    return states, facing


def _run(tmp_path, name, setup, mview_values=None) -> bool:
    rm, rt, patches, p31 = setup
    states, facing = _pokes(p31)
    groups = MC.view_groups()
    body, data, expected = ["stl.startup_and_init_all"], [], []
    for v, (vx, vy) in enumerate([(1056 << 16 | 0x8000, (-3616 << 16) + 0x21), (-200 << 16, 300 << 16)]):
        body += ["hex.set 8, viewx, %d" % (vx & 0xFFFFFFFF), "hex.set 8, viewy, %d" % (vy & 0xFFFFFFFF)]
        for t, th in enumerate(rt):
            tx, ty = th.x << 16, th.y << 16
            body += ["hex.set w/4, sp_ti, %d" % t, "hex.set 8, sp_x, %d" % (tx & 0xFFFFFFFF),
                     "hex.set 8, sp_y, %d" % (ty & 0xFFFFFFFF), "stl.fcall thsel_leaf, thsel_ret",
                     "hex.print_as_digit %d, sp_ti, 0" % max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)]
            m = p31["rt_slot"][t]
            if m is None:
                expected.append(t)
            else:
                st = gd.STATES[gd.STATE_NAMES[states[m]]]
                view = view_of(patches, st.sprite, st.frame_index, rotation(rm, vx, vy, tx, ty, facing[m]))
                expected.append(len(rt) + p31["views"].index(view))
        body.append("stl.output 10")
    body.append("stl.loop")
    nib = {f: MC.cell_nibbles(p31["schema"], f) for f in MC.P31_FIELDS}
    decls = [d for d in p31["decls"] if not d.startswith(("mon_state:", "mon_facing:"))]
    decls += ["mon_state: hex.vec %d, %d" % (nib["mon_state"] * len(states),
                                             sum(s << (8 * m) for m, s in enumerate(states))),
              "mon_facing: hex.vec %d, %d" % (len(facing), sum(f << (4 * m) for m, f in enumerate(facing)))]
    data += ["viewx: hex.vec 8", "viewy: hex.vec 8", "sp_ti: hex.vec w/4", "sp_x: hex.vec 8", "sp_y: hex.vec 8"]
    data += decls + p31["select"] + p31["rotation"]
    mv = p31["mview"] if mview_values is None else generate_dispatch_table_fj(
        "mview", mview_values, index_nibbles=3,
        result_nibbles=max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4))
    data += [mv, p31["mrot"],
             generate_dispatch_table_fj("mstate", MC.state_table_values(), index_nibbles=2, result_nibbles=6),
             generate_dispatch_table_fj("ttang", tantoangle_table(SLOPERANGE), index_nibbles=3, result_nibbles=8),
             generate_dispatch_table_fj("sdrecip", slopediv_recip8_table(), index_nibbles=3, result_nibbles=6),
             generate_tantoangle_lut_fj("tantoangle", SLOPERANGE)]
    rows = len(rt)
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)        # the row index's width
    fmt = "%0" + str(rn) + "x"
    exp = "".join(fmt % e for e in expected[:rows]) + "\n" + "".join(fmt % e for e in expected[rows:]) + "\n"
    prog = "\n".join(body + data) + "\n" + hoisted_scratch_fj()
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
            (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", exp.encode(), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_every_runtime_thing_selects_its_row(tmp_path, setup):
    assert _run(tmp_path, "thsel", setup), "the row select parted from doomfj.monsters' view rule"


def test_control_a_mutated_view_entry_is_caught(tmp_path, setup):
    rm, rt, patches, p31 = setup
    import re
    # rebuild mview's values the way p31_parts does, then move the entry of the FIRST monster's first poke
    groups = MC.view_groups()
    vals = [0] * (((len(groups) - 1) << 4) + 8)
    for g, (spr, fr) in enumerate(groups):
        letter = chr(ord("A") + fr)
        if not any(k[0] == spr and k[1] == letter for k in patches):
            continue
        for r0 in range(8):
            vals[(g << 4) | r0] = len(rt) + p31["views"].index(view_of(patches, spr, fr, r0 + 1))
    rn = max(1, ((p31["nrows"] - 1).bit_length() + 3) // 4)
    assert generate_dispatch_table_fj("mview", vals, index_nibbles=3, result_nibbles=rn) == p31["mview"]
    bad = [v + 1 if v else v for v in vals]                   # every monster row one off
    assert not _run(tmp_path, "thsel_mut", setup, bad), "a mutated mview passed: the comparison is vacuous"
