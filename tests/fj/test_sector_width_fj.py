"""M8 L1 (docs/handoff-e1m2.md 4 (B), doomfj.sectorcode): a THREE-nibble sector id on the real flipjump engine.

E1M1 has 182 sectors, so its program never holds a sector id >= 256 and none of its harnesses can see a register or
a dispatch that drops the third nibble -- the SILENT RISK of E1M2 (380 sectors): a 2-nibble cell or jump would give
sector 300 the row of sector 44 on E1M2 only. This file runs the emitters' own sector code at `nib` = 3 on synthetic
sector ids up to 379 (a World of 380 sectors), with no map:

  * THE REJECT LEAF (`monstercode.p32b_rj_leaf`, `sector_dispatch` on `mt_ms`): every slot's sector READ out of
    `msec` (`hex.mov 3, mt_ms, msec_cell(m, 3)`, p32a_slot's line), the leaf's 3-level jump to that sector's row
    `rj<s>` (3-nibble index: the player's sector `psec`), a sector outside the leaf set -> `mt_rj_none` (0);
  * THE CELL (`msec`, declared by `monstercode.p32b_decls` with `msec_value`): each slot WRITTEN through
    `p32b_move_lines`' own write line and read back through `knockcode.move_lines`' read line, every slot printed
    (a write that spills into or misses a nibble of a neighbour shows);
  * THE LEAF'S SECTOR (`lfsec` at `result_nibbles=3` into `mm_sec`, monstermove's relink lookup);
  * THE NOISE NODE (`noisecode._node_dispatch` on `nz_sec`, declared by `noise_decls`): every sector of 380, and two
    past the table (-> the miss).

R9 (each must part from the expected output): the msec read as 2 nibbles; the leaf's dispatch built at 2 nibbles (on
the sectors' low bytes); the msec write as 2 nibbles; `lfsec` at 2 result nibbles (the low bytes); the noise dispatch
at 2 nibbles.
"""
import types
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import knockcode as KC
from doomfj import monstercode as MC
from doomfj import noisecode as NZ
from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.sectorcode import msec_cell, msec_value, sector_dispatch
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"

NSEC = 380                                        # E1M2's sector count: World.sec_nibbles == 3
NIB = 3
MSEC = [5, 255, 256, 300, 379, 17, 268]           # each slot's sector at the start
LEAF_SET = [0, 5, 12, 255, 256, 300, 379]         # the sectors with a REJECT row (17, 268: misses)
PSEC = [0, 1, 44, 200, 255, 256, 290, 379]        # the player's sectors the rows are read at
NEW = [300, 4, 379, 256, 0, 290, 257]             # each slot's sector written
LEAF_SEC = [3, 256, 379, 300, 255, 0, 12, 268]    # lfsec: a leaf's sector
NOISE_PROBE = list(range(NSEC)) + [NSEC, 4095]    # every sector, then two past the table
MUTANTS = ("rd2", "disp2", "wr2", "lf2", "noise2")


def _vis(s: int, q: int) -> int:
    """the synthetic REJECT: can sector s see sector q"""
    return ((s * 2654435761 + q * 40503) >> 7) & 1


def _node(s: int) -> int:
    """the synthetic sound node of sector s: unique per sector, so a wrong sector shows"""
    return (s * 7) % NSEC


def test_the_width_rule():
    """World.sec_nibbles: E1M1 (182 sectors) keeps its 2 nibbles; the rule gives E1M2's 380 three"""
    w = World(monsters="idle")
    assert len(w.secs) == 182 and w.sec_nibbles == 2
    fake = types.SimpleNamespace(secs=[None] * NSEC)
    assert World.sec_nibbles.fget(fake) == NIB
    for n, want in ((1, 2), (256, 2), (257, 3), (4096, 3), (4097, 4)):
        assert World.sec_nibbles.fget(types.SimpleNamespace(secs=[None] * n)) == want, n


def test_dispatch_at_two_nibbles_is_the_old_text():
    """sector_dispatch at 2 nibbles: the two-level jump the emitters wrote before it (noisecode's dense form and
    monstercode's sparse form), label for label"""
    node_of = [_node(s) % 50 for s in range(182)]
    old = ["    hex.switch c + 1*dw, " + ", ".join("p_h%d" % h if h < 12 else "m" for h in range(16))]
    for h in range(12):
        old += ["  p_h%d:" % h, "    hex.switch c, " + ", ".join(
            "t%d" % node_of[16 * h + l] if 16 * h + l < 182 else "m" for l in range(16))]
    assert sector_dispatch("p_", "c", lambda s: "t%d" % node_of[s], "m", 182, 2) == old
    have = {3, 40, 41, 170}
    hs = sorted({s >> 4 for s in have})
    old = ["    hex.switch c + 1*dw, " + ", ".join("qh%d" % h if h in hs else "m" for h in range(16))]
    for h in hs:
        old += ["  qh%d:" % h, "    hex.switch c, " + ", ".join(
            "qs%d" % (16 * h + l) if 16 * h + l in have else "m" for l in range(16))]
    assert sector_dispatch("q", "c", lambda s: "qs%d" % s if s in have else None, "m", 182, 2) == old


def _schema():
    return World().schema


def _rj_leaf(mut):
    if mut != "disp2":
        return MC.p32b_rj_leaf(LEAF_SET, NSEC, NIB)
    # a 2-nibble dispatch: the low byte picks the row (the first leaf sector with that low byte)
    low = {}
    for s in sorted(LEAF_SET):
        low.setdefault(s & 0xFF, s)
    out = ["mt_rj_leaf:"] + sector_dispatch("mt_rj", "mt_ms", lambda s: "mt_rjs%d" % low[s] if s in low else None,
                                            "mt_rj_none", 256, 2)
    for s in sorted(LEAF_SET):
        out += ["  mt_rjs%d:" % s, "    rj%d.lookup mt_rj, psec" % s, "    stl.fret mt_rjret"]
    return out + ["  mt_rj_none:", "    hex.zero 1, mt_rj", "    stl.fret mt_rjret"]


def _program(mut=None):
    schema = _schema()
    n = len(MSEC)
    # the emitters' own lines: p32b_move_lines' msec write, knockcode's msec read
    wr = [[ln.strip() for ln in MC.p32b_move_lines(m, rt=m, radius=20, speed=8, schema=schema, nib=NIB)
           if ln.strip().startswith("hex.mov %d, msec" % NIB)] for m in range(n)]
    kb = KC.move_lines([(m, 20, 100) for m in range(n)], nib=NIB)
    rd = [[ln.strip() for ln in kb if ln.strip() == "hex.mov %d, mm_sec, %s" % (NIB, msec_cell(m, NIB))]
          for m in range(n)]
    assert all(len(x) == 1 for x in wr) and all(len(x) == 1 for x in rd), (wr, rd)
    body = ["stl.startup_and_init_all"]
    # 1. the REJECT leaf on each slot's sector, at each player sector
    for m in range(n):
        load = "hex.mov %d, mt_ms, %s" % (2 if mut == "rd2" else NIB, msec_cell(m, NIB))
        for q in PSEC:
            body += ["hex.set %d, psec, %d" % (NIB, q), load, "stl.fcall mt_rj_leaf, mt_rjret",
                     "hex.print_as_digit 1, mt_rj, 0"]
        body.append("stl.output 10")
    # 2. the writes, then every slot, then each read back
    for m in range(n):
        line = wr[m][0].replace("hex.mov %d," % NIB, "hex.mov 2,", 1) if mut == "wr2" else wr[m][0]
        body += ["hex.set %d, mm_sec, %d" % (NIB, NEW[m]), line]
    body += ["hex.print_as_digit %d, %s, 0" % (NIB, msec_cell(m, NIB)) for m in range(n)] + ["stl.output 10"]
    for m in range(n):
        body += ["hex.set %d, mm_sec, %d" % (NIB, 0xFFF), rd[m][0], "hex.print_as_digit %d, mm_sec, 0" % NIB]
    body.append("stl.output 10")
    # 3. lfsec into mm_sec (stale bits set first: the lookup must own every nibble)
    for k in range(len(LEAF_SEC)):
        body += ["hex.set %d, mm_sec, %d" % (NIB, 0xFFF), "hex.set w/4, mm_leafw, %d" % k,
                 "lfsec.lookup mm_sec, mm_leafw", "hex.print_as_digit %d, mm_sec, 0" % NIB]
    body.append("stl.output 10")
    # 4. the noise node of every sector
    for s in NOISE_PROBE:
        body += ["hex.set %d, nz_sec, %d" % (NIB, s), "stl.fcall nzt_go, nzt_ret", "hex.print_as_digit 3, nzt_res, 0"]
    body += ["stl.output 10", "stl.loop"]
    fake = types.SimpleNamespace(nsound=1, sec_nibbles=NIB,      # M8 L5: no ML_SOUNDBLOCK line (noise_decls asks)
                                 _sound_block_door_edges=[], _sound_block_static_edges=[], door_order=[], mover_order=[])
    decls = (MC.p32a_decls(schema, n, {**{f: [0] * n for f in MC.P32A_FIELDS}, "sched_cursor": 0}, n, NIB)
             + MC.p32b_decls(schema, n, {f: [0] * n for f in MC.P32B_FIELDS}, MSEC, NIB)
             + NZ.noise_decls(fake) + ["nzt_res: hex.vec 3", "nzt_ret: hex.vec w/4"])
    if mut == "noise2":
        node_of = [_node(s) for s in range(256)]
        disp = sector_dispatch("nzt_d_", "nz_sec", lambda s: "nzt_n%d" % node_of[s], "nzt_miss", 256, 2)
    else:
        disp = NZ._node_dispatch("nzt_d", "nz_sec", [_node(s) for s in range(NSEC)], lambda k: "nzt_n%d" % k,
                                 "nzt_miss", NIB)
    noise = ["nzt_go:"] + disp
    for k in range(NSEC):
        noise += ["  nzt_n%d:" % k, "    hex.set 3, nzt_res, %d" % k, "    stl.fret nzt_ret"]
    noise += ["  nzt_miss:", "    hex.set 3, nzt_res, %d" % 0xFFF, "    stl.fret nzt_ret"]
    lf = (generate_dispatch_table_fj("lfsec", [s & 0xFF for s in LEAF_SEC], index_nibbles=3, result_nibbles=2)
          if mut == "lf2" else generate_dispatch_table_fj("lfsec", LEAF_SEC, index_nibbles=3, result_nibbles=NIB))
    tables = [generate_dispatch_table_fj("rj%d" % s, [_vis(s, q) for q in range(NSEC)], index_nibbles=NIB,
                                         result_nibbles=1) for s in LEAF_SET] + [lf]
    code = ["// the leaves", ";nzt_end"] + _rj_leaf(mut) + noise + ["nzt_end:"]
    return "\n".join(body + decls) + "\n" + "\n".join(code) + "\n" + "\n".join(tables) + "\n"


def _expected() -> bytes:
    lines = ["".join("%x" % (_vis(s, q) if s in LEAF_SET else 0) for q in PSEC) for s in MSEC]
    lines.append("".join("%03x" % s for s in NEW))
    lines.append("".join("%03x" % s for s in NEW))
    lines.append("".join("%03x" % s for s in LEAF_SEC))
    lines.append("".join("%03x" % (_node(s) if s < NSEC else 0xFFF) for s in NOISE_PROBE))
    return ("\n".join(lines) + "\n").encode()


def _run(tmp_path, name, mut=None) -> bool:
    p = tmp_path / f"{name}.fj"
    p.write_text(_program(mut), encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", _expected(), memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_controls_have_something_to_break():
    """each control's wrong answer differs from the right one in these cases"""
    assert [(msec_value(MSEC, NIB) >> (4 * NIB * m)) & 0xFFF for m in range(len(MSEC))] == MSEC
    with pytest.raises(AssertionError):
        msec_value([256], 2)
    low = {}
    for s in sorted(LEAF_SET):
        low.setdefault(s & 0xFF, s)
    right = [[_vis(s, q) if s in LEAF_SET else 0 for q in PSEC] for s in MSEC]
    disp2 = [[_vis(low[s & 0xFF], q) if (s & 0xFF) in low else 0 for q in PSEC] for s in MSEC]
    assert right != disp2
    assert any(s >> 8 for s in NEW) and any(s >> 8 for s in LEAF_SEC)
    assert any(_node(s) != _node(s & 0xFF) for s in range(256, NSEC))


def test_three_nibble_sectors_follow_the_model(tmp_path):
    assert _run(tmp_path, "secw"), "a 3-nibble sector id parted from its expected value"


@pytest.mark.parametrize("mut", MUTANTS)
def test_control_a_two_nibble_sector_is_caught(tmp_path, mut):
    assert not _run(tmp_path, "secw_" + mut, mut), "%s passed: the comparison is vacuous" % mut
