"""M8 F1.5 (docs/f1-runtime-ids.md, option A1) -- the host side of runtime thing ids past 254.

Config.LIST_ID_BITS (8 or 12) widens the per-leaf lists; every emitter it reaches must emit, at 8, the TEXT it emitted
before the flag existed (E1M1's and E1M2's programs are unchanged: scratchpad/cr/emit_baseline.py checks the whole
emission) -- so each 8-bit helper is compared here with the pre-F1.5 formula, copied verbatim -- and at 12 the wide
forms tests/fj/test_wide_ids_fj.py runs in fj.
"""
import random
from dataclasses import replace
from pathlib import Path

import pytest

from doomfj import barrelcode as BC
from doomfj import monstercode as MC
from doomfj import projcode as PC
from doomfj.config import Config, map_cfg
from doomfj.things import (LEAF_LINK_DECLS, LIST_MAX_THINGS, byte_array_decl, leaf_link_decls, list_bits, list_macros,
                           list_max, spawn_leaf_lists)
from doomfj.wall_renderer import list_restart_lines


def test_the_widths_and_their_bounds():
    assert (list_max(8), list_max(12)) == (LIST_MAX_THINGS, 4094) == (254, 4094)
    assert [list_bits(n) for n in (0, 228, 244, 254, 255, 341, 370, 4094)] == [8] * 4 + [12] * 4
    with pytest.raises(AssertionError):
        list_bits(4095)
    with pytest.raises(AssertionError):
        list_max(16)
    c = Config()
    assert (c.LIST_ID_BITS, c.LIST_WIDE, c.LIST_NIB) == (8, 0, 2)
    w = replace(c, LIST_ID_BITS=12)
    assert (w.LIST_WIDE, w.LIST_NIB) == (1, 3)
    with pytest.raises(AssertionError):
        replace(c, LIST_ID_BITS=10).LIST_WIDE
    # not an fj constant: fj_consts.fj is what it was
    assert "LIST_ID_BITS" not in c.constants() and "LIST_WIDE" not in c.constants()


def test_only_a_wide_map_gets_defines():
    assert Config().fj_defines() is None
    for m in ("E1M1", "E1M2"):                        # the shipped maps assemble with no -D at all
        assert map_cfg(Config(), m).LIST_ID_BITS == 8 and map_cfg(Config(), m).fj_defines() is None
    assert replace(Config(), LIST_ID_BITS=12).fj_defines() == {"hex.pointers.PTR_WIDE_BITS": 12}


def test_the_lists_and_their_cells_at_both_widths():
    binds = [t % 7 for t in range(300)]
    with pytest.raises(AssertionError):
        spawn_leaf_lists(binds, 7)                    # 300 things: past the 8-bit bound, as before
    head, nxt = spawn_leaf_lists(binds, 7, max_things=list_max(12))
    assert head == [1, 2, 3, 4, 5, 6, 7] and max(nxt) == 300
    vals = [0, 1, 0xFF, 7]
    assert byte_array_decl("x", vals, 6) == byte_array_decl("x", vals, 6, bits=12)   # the 8-bit text, unchanged
    assert byte_array_decl("x", [0x123], 2, bits=12) == "x:\n;291 * dw\nhex.vec 1"
    with pytest.raises(AssertionError):
        byte_array_decl("x", [0x100], 2)
    with pytest.raises(AssertionError):
        byte_array_decl("x", [0x1000], 2, bits=12)
    assert LEAF_LINK_DECLS == leaf_link_decls(2) == [
        "ll_enc: hex.vec 2", "ll_v: hex.vec 2", "ll_nxt: hex.vec 2", "ll_p: hex.vec w/4", "ll_q: hex.vec w/4",
        "ll_base: hex.vec w/4", "ll_idx: hex.vec w/4"]
    assert leaf_link_decls(3)[:3] == ["ll_enc: hex.vec 3", "ll_v: hex.vec 3", "ll_nxt: hex.vec 3"]
    assert list_macros(8) == {"link": "sim.leaf_link", "unlink": "sim.leaf_unlink", "depth": "sim.thing_pass_depth"}
    assert list_macros(12) == {"link": "sim.leaf_link_w", "unlink": "sim.leaf_unlink_w",
                               "depth": "sim.thing_pass_depth_w"}


def _old_select(ntm):
    """p31_parts' row select before F1.5, verbatim"""
    sel = ["thsel_leaf:", "    hex.switch sp_ti + 1*dw, " + ", ".join(
        "thsel_h%d" % h if 16 * h < ntm else "thsel_none" for h in range(16))]
    for h in range((ntm + 15) // 16):
        sel += ["  thsel_h%d:" % h, "    hex.switch sp_ti, " + ", ".join(
            "thsel_s%d" % (16 * h + l) if 16 * h + l < ntm else "thsel_none" for l in range(16))]
    return sel


def test_the_select_is_the_old_two_levels_through_256():
    for n in (1, 15, 16, 17, 100, 228, 254, 255, 256):
        assert MC.select_tree_lines(n) == _old_select(n), n
    s = MC.select_tree_lines(370)
    assert s[1] == "    hex.switch sp_ti + 2*dw, thsel_g0, thsel_g1" + ", thsel_none" * 14
    assert "  thsel_g1:" in s and "  thsel_h23:" in s and "  thsel_h24:" not in s
    assert [ln for ln in s if ln.startswith("  thsel_h")] == ["  thsel_h%d:" % h for h in range(24)]


def _old_list_restart(nss, nthings, per_skill):
    """wall_renderer.restart_lines' list lines before F1.5, verbatim"""
    common = [f"    rep({nss}, i) m1.zerobyte sshead + i*dw", f"    rep({nthings}, i) m1.zerobyte thnext + i*dw"]
    skills = []
    for head, nxt, vis in per_skill:
        out = []
        for label, arr in (("sshead", head), ("thnext", nxt)):
            for i, v in enumerate(arr):
                out += [f"    {label} + {i}*dw + dbit + {b};" for b in range(8) if v >> b & 1]
        skills.append(out)
    return common, skills


def test_the_restart_fragment_at_8_bits_is_the_old_text():
    rnd = random.Random(15)
    per = []
    for _ in range(3):
        binds = [rnd.randrange(9) for _ in range(120)]
        per.append(spawn_leaf_lists(binds, 9, present=[rnd.random() < 0.6 for _ in binds]) + ([1, 0],))
    assert list_restart_lines(9, 130, per) == _old_list_restart(9, 130, per)
    common, skills = list_restart_lines(9, 130, per, 12)
    assert common[0] == "    rep(9, i) m1.zerocell12 sshead + i*dw"
    assert skills == _old_list_restart(9, 130, per)[1]             # values < 256 flip only bits < 8
    with pytest.raises(AssertionError):
        list_restart_lines(1, 1, [([0x100], [0], [])])            # a 9-bit value in an 8-bit fragment


def test_the_depth_walks_registers_at_both_widths():
    assert MC.TD_KEY_ROWS == 256 and MC.td_key_rows(228) == 256 and MC.td_key_rows(370) == 370
    assert MC.P33_DECLS == MC.p33_decls(256) and MC.P33_DECLS[-1] == "td_keys: hex.vec 4096"
    assert MC.p33_decls(MC.td_key_rows(370))[-1] == "td_keys: hex.vec 5920"
    assert MC.d3_decls() == MC.D3_DECLS == ("td_rk: hex.vec 2", "sp_ex: hex.vec 1")
    assert MC.d3_decls(3) == ("td_rk: hex.vec 3", "sp_ex: hex.vec 1")


def test_the_relink_callers_name_the_macros_of_their_width():
    tic8, tic12 = PC.pool_tic_lines(), PC.pool_tic_lines(list_bits=12)
    assert "    sim.leaf_link pw_t, pw_leaf" in tic8 and "    sim.leaf_unlink pw_t, pw_leaf" in tic8
    assert "    sim.leaf_link_w pw_t, pw_leaf" in tic12 and "    sim.leaf_unlink_w pw_t, pw_leaf" in tic12
    assert [a for a, b in zip(tic8, tic12) if a != b] == ["    sim.leaf_link pw_t, pw_leaf",
                                                          "    sim.leaf_unlink pw_t, pw_leaf"]
    from doomfj.monstermove import move_leaf_lines
    kw = dict(root="r", lift_trigs=[], door_boxes=[], dropmax=24, stepup=24, height=56)
    m8, m12 = move_leaf_lines(**kw), move_leaf_lines(**kw, list_bits=12)
    assert [(a, b) for a, b in zip(m8, m12) if a != b] == [
        ("    sim.leaf_unlink mm_tw, mm_leafw", "    sim.leaf_unlink_w mm_tw, mm_leafw"),
        ("    sim.leaf_link mm_tw, mm_leafw", "    sim.leaf_link_w mm_tw, mm_leafw")]


def test_the_drop_row_register_at_both_widths():
    from doomfj.world import World
    w = World(monsters="full", sight_rule="seen", player="full")
    slot_rt = list(range(w.layout.nmon))
    d8 = BC.drop_lines(w, nt=60, slot_rt=slot_rt)
    d12 = BC.drop_lines(w, nt=300, slot_rt=slot_rt, list_bits=12)
    assert "    hex.set 2, dr_t, 70" in d8 and "    hex.mov 2, pw_t, dr_t" in d8
    assert "    hex.set 3, dr_t, 310" in d12 and "    hex.mov 3, pw_t, dr_t" in d12
    with pytest.raises(AssertionError):
        BC.drop_lines(w, nt=300, slot_rt=slot_rt)                 # row 310 does not fit two nibbles
    assert "dr_t: hex.vec 2" in BC.decls(w, 3) and "dr_t: hex.vec 3" in BC.decls(w, 3, list_bits=12)


def test_the_model_schema_keeps_its_8_bit_lists():
    """the model's lists hold the MOBILE index (monsters + pools): 8 bits on every surveyed map -- the frozen sets'
    schema -- and widen only past 254 mobiles"""
    from doomfj.world import World, build_schema
    w = World(monsters="full", sight_rule="seen", player="full")
    f = {x.name: x for x in w.schema}
    assert f["leaf_head"].bits == f["mob_next"].bits == 8
    big = build_schema(replace(w.layout, nmon=245, nbarrel=1))     # 245 + the 10 pool slots = 255 mobiles
    assert {x.name: x.bits for x in big if x.name in ("leaf_head", "mob_next")} == {"leaf_head": 12, "mob_next": 12}


def test_the_wide_twins_live_in_their_own_file_and_only_wide_builds_include_it():
    """the 8-bit list macros keep their text (their macro paths are heat-list keys, and tests mutate sim.fj by text);
    the wide ones are new names in sim_wide.fj, which build_wall_renderer includes only for a LIST_WIDE config"""
    fj = Path(__file__).resolve().parents[2] / "src" / "fj"
    wide, text = (fj / "sim_wide.fj").read_text(encoding="utf-8"), (fj / "sim.fj").read_text(encoding="utf-8")
    for name in ("leaf_link_w", "leaf_unlink_w", "thing_pass_depth_w", "rank_key_w", "zerocell12"):
        assert ("def %s " % name) in wide and ("def %s " % name) not in text, name
    from doomfj import build
    import inspect
    src = inspect.getsource(build.build_wall_renderer)
    assert build._SIM_WIDE_INCLUDES == ["sim_wide.fj"]
    assert "(_SIM_WIDE_INCLUDES if player_sim and cfg.LIST_WIDE else [])" in src
