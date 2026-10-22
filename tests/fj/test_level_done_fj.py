"""P10 (doomfj.statcode): LEVEL COMPLETE's STATS on the real flipjump engine, against the oracle (menu.stats_digits,
menu.level_done_pixels; statcode.level_totals).

  * THE DIGITS: `statcode.digit_lines` -- the kills and items split into two decimal digits (a leading zero blank), the
    skill's totals (a block per skill on `g_skill`), the secrets, and the clock (lvtime / MAX_FPS seconds -> mm:ss,
    capped at 99:59) -- run on edge and random values of the cells, the 13 slots printed after each;
  * THE FRAME: the cells -> the digits -> `statcode.frame_lines` (the baked frame and each slot's records for its
    digit) presented through the real screen device, against `level_done_pixels` of the oracle's digits.

R9 (MUTANTS), each must part: the minutes' leading zero drawn, the 99:59 cap gone, the clock divided by 35, the skills'
totals crossed, the secrets' slot read from the kills; and, for the frame, two digits' records swapped in one slot.

M8 F1.1 (docs/f1-big-map-widths.md 3): the same digits and frames on E1M2, whose 129 monster slots make every count
THREE digits (statcode.count_digits) -- 0, 9, 10, 99, 100, 109, 110 and up -- with its own mutants (the hundreds never
blanked, the tens never blanked) and a two-digit layout on a three-digit map refused.

M8 C2 (docs/c2-slot-ids.md): on E1M6 (294 monster slots: tests/fj/wide_maps.py) the counters themselves are THREE
nibbles (statcode.count_nibbles) and the kills reach 255, 256 and the most a skill counts (its 3 lost souls are not COUNTKILL) -- the first division is the 3-nibble one; R9
there: the 2-nibble division on the 3-nibble cell (a count past 255 read by its low byte) must part.
"""
import random
import re
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.ScreenIO import InMemoryScreen

from doomfj import gamedata as gd
from doomfj import statcode as SC
from doomfj.config import Config
from doomfj.harness import W
from doomfj.menu import DIGIT_BLANK, count_slots, level_done_pixels, palette_colours, stats_digits
from doomfj.wad import WadFile
from doomfj.wall_renderer import MAX_FPS, SKILLS
from doomfj.world import World

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
CFG = Config()
ASSETS = ROOT / "tests" / "fixtures" / "freedoom_assets.wad"


_WORLDS = {}


def _world(mapname="E1M1"):
    """the map's World (M8 F1.1: E1M2 for three-digit counts; M8 C2: E1M6 for three-nibble counters), built once"""
    if mapname not in _WORLDS:
        if mapname == "E1M6":
            from tests.fj.wide_maps import map_world
            _WORLDS[mapname] = map_world(mapname, skill=gd.SK_HARD, monsters="idle", player="full")
        else:
            mw = WadFile.from_path(str(ROOT / "tests" / "fixtures" / ("freedoom_%s.wad" % mapname.lower())))
            _WORLDS[mapname] = World(mw, mapname, skill=gd.SK_HARD, monsters="idle", player="full")
    return _WORLDS[mapname]


def _nd(mapname="E1M1"):
    return SC.count_digits(_world(mapname))


def _cases(mapname="E1M1"):
    """(kills, items, secrets, skill index, lvtime): every edge the slots have, then random ones -- M8 F1.1: on a
    three-digit map the counts' edges too (0, 9, 10, 99, 100, 109, 110)"""
    w = _world(mapname)
    totals = [SC.level_totals(w, sk) for sk in SKILLS]
    nsec = len(w.secret_sectors)
    edge_t = [0, 19, 20, 1199, 1200, 12000, 20 * 599, 20 * 600, 20 * 5999, 20 * 5999 + 19, 20 * 6000,
              (1 << 20) - 1]
    out = []
    for i, t in enumerate(edge_t):
        k = i % len(SKILLS)
        tk, ti = totals[k]
        out.append(((0, 1, 9, 10, tk)[i % 5], (0, 9, 10, 23, ti)[i % 5], i % (nsec + 1), k, t))
    if _nd(mapname) == 3:
        kmax = max(range(len(SKILLS)), key=lambda j: totals[j][0])       # the skill whose totals pass 99
        for i, v in enumerate((0, 9, 10, 99, 100, 109, 110, 128)
                              + ((255, 256, 257, 270, 290, 291) if SC.count_nibbles(w) == 3 else ())):   # M8 C2
            k = kmax if v >= 99 else i % len(SKILLS)
            tk, ti = totals[k]
            out.append((min(v, tk), min(v, ti), i % (nsec + 1), k, 1200 * i))
    rnd = random.Random(0x1D0)
    while len(out) < 60:
        k = rnd.randrange(len(SKILLS))
        tk, ti = totals[k]
        out.append((rnd.randint(0, tk), rnd.randint(0, ti), rnd.randint(0, nsec), k, rnd.randrange(1 << 20)))
    return out, totals


def _want(case, totals, nd=2) -> list:
    kills, items, secrets, k, t = case
    tk, ti = totals[k]
    return stats_digits(kills, tk, items, ti, secrets, t // MAX_FPS, nd)


def _set(case, cn=2) -> list:
    kills, items, secrets, k, t = case
    return ["hex.set %d, st_kill, %d" % (cn, kills), "hex.set %d, st_item, %d" % (cn, items),
            "hex.set 1, st_secn, %d" % secrets,
            "hex.set 1, g_skill, %d" % k, "hex.set 5, lvtime, %d" % t]


DIGIT_MUTANTS = {
    "minutes' leading zero": (r"hex\.set 1, st_dig \+ 9\*dw, 10\n", "hex.set 1, st_dig + 9*dw, 0\n"),
    "no cap": (r"  lvd_tcap:\n", "  lvd_tcap:\n    ;lvd_tok\n"),
    "by 35": None,
    "totals crossed": (r"hex\.if0 1, g_skill, lvt0\n", "hex.if0 1, g_skill, lvt2\n"),
    "secrets from the kills": (r"hex\.mov 1, st_dig \+ 8\*dw, st_secn\n", "hex.mov 1, st_dig + 8*dw, st_kill\n"),
}


# M8 F1.1: the three-digit split's own (E1M2: the kills' slots 0..2, the items' 6..8)
DIGIT3_MUTANTS = {
    "hundreds never blanked": (r"  lvd_b0:\n    hex\.set 1, st_dig \+ 0\*dw, 10\n", "  lvd_b0:\n"),
    "tens never blanked": (r"  lvd_bt6:\n    hex\.set 1, st_dig \+ 7\*dw, 10\n", "  lvd_bt6:\n"),
}
# M8 C2 (E1M6): the kills' 3-nibble division replaced by the 2-nibble one (the count read by its low byte)
DIGIT3W_MUTANTS = {
    "kills by the low byte": (r"    hex\.mov 3, lvd_v3, st_kill\n    hex\.div 3, 1, lvd_q3, lvd_o, lvd_v3, lvd_c10, "
                              r"lvd_div0\n    hex\.mov 2, lvd_q, lvd_q3\n",
                              "    hex.mov 2, lvd_v, st_kill\n    stl.fcall lvd_dec, lvd_ret\n"),
}


def _digit_text(w, mut=None) -> str:
    text = "\n".join(SC.digit_lines(w, SKILLS)) + "\n"
    table = {**DIGIT_MUTANTS, **DIGIT3_MUTANTS, **DIGIT3W_MUTANTS}
    if mut and table[mut]:
        pat, new = table[mut]
        text, n = re.subn(pat, new, text)
        assert n, mut
    return text


def _decls(w, mut=None) -> list:
    d = SC.decls(w)
    if mut == "by 35":
        d = [("lvd_cf: hex.vec 2, 35" if x.startswith("lvd_cf:") else x) for x in d]
    return d + ["g_skill: hex.vec 1", "lvtime: hex.vec 5", "dg_ret: hex.vec w/4", "fr_ret: hex.vec w/4"]


def _digits_program(mut=None, mapname="E1M1"):
    w = _world(mapname)
    cases, totals = _cases(mapname)
    nd = _nd(mapname)
    body = ["stl.startup_and_init_all"]
    for case in cases:
        body += _set(case, SC.count_nibbles(w)) + ["stl.fcall dg_go, dg_ret"]
        body += ["hex.print_as_digit 1, st_dig + %d*dw, 0" % i for i in range(count_slots(nd))] + ["stl.output 10"]
    body += ["stl.loop", "dg_go:", _digit_text(w, mut), "    stl.fret dg_ret", *SC.routine_lines(), *_decls(w, mut)]
    want = "".join("".join("%x" % d for d in _want(c, totals, nd)) + "\n" for c in cases).encode()
    return "\n".join(body) + "\n", want


def _assemble(tmp_path, name, text, extra=()):
    p = tmp_path / ("%s.fj" % name)
    p.write_text(text, encoding="utf-8")
    consts = CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), *[(FJ / f).resolve() for f in extra], (FJ / "sim.fj").resolve(), p.resolve()]
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble(srcs, out, memory_width=W, print_time=False)
    return out, srcs


def _run_digits(tmp_path, name, mut=None, mapname="E1M1") -> bool:
    text, want = _digits_program(mut, mapname)
    p = tmp_path / ("%s.fj" % name)
    p.write_text(text, encoding="utf-8")
    consts = CFG.emit_fj_consts(tmp_path / "fj_consts.fj")
    srcs = [consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()]
    return fj.assemble_and_run_test_output(srcs, b"", want, memory_width=W, warning_as_errors=True,
                                           should_raise_assertion_error=False)


def test_the_cases_reach_every_edge():
    """both blanks and both two-digit counts, every skill, every secret count, a leading-zero second, ten minutes and
    more, the cap (exactly 99:59 and past it), and the 20-bit clock's largest value"""
    cases, totals = _cases()
    digits = [_want(c, totals) for c in cases]
    assert {c[3] for c in cases} == set(range(len(SKILLS)))
    assert any(d[0] == DIGIT_BLANK for d in digits) and any(d[0] != DIGIT_BLANK for d in digits)
    assert any(d[4] == DIGIT_BLANK for d in digits) and any(d[4] != DIGIT_BLANK for d in digits)
    assert any(d[9] == DIGIT_BLANK for d in digits) and any(d[9] not in (DIGIT_BLANK, 0) for d in digits)
    assert any(d[11] == 0 for d in digits) and [9, 9, 5, 9] in [d[9:] for d in digits]
    assert sum(1 for c in cases if c[4] // MAX_FPS > 5999) >= 2
    assert {c[2] for c in cases} == set(range(5))


def test_the_digits_follow_the_oracle(tmp_path):
    assert _run_digits(tmp_path, "digits"), "statcode.digit_lines parted from menu.stats_digits"


@pytest.mark.parametrize("mut", sorted(DIGIT_MUTANTS))
def test_control_broken_digits_are_caught(tmp_path, mut):
    assert not _run_digits(tmp_path, "digits_" + mut.replace(" ", "_").replace("'", ""), mut), (
        "%s passed: the comparison is vacuous" % mut)


# ---- M8 F1.1: three-digit counts (E1M2) -----------------------------------------------------------------------------
def test_e1m2_counts_are_three_digits_and_e1m1_two():
    assert _nd("E1M1") == 2 and _nd("E1M2") == 3
    cases, totals = _cases("E1M2")
    digits = [_want(c, totals, 3) for c in cases]
    assert all(len(d) == count_slots(3) == 17 for d in digits)
    assert [DIGIT_BLANK, DIGIT_BLANK, 0] in [d[0:3] for d in digits]          # 0: the hundreds and tens blank
    assert [DIGIT_BLANK, 1, 0] in [d[0:3] for d in digits]                    # 10: the tens shown
    assert [1, 0, 0] in [d[0:3] for d in digits] and [1, 0, 9] in [d[0:3] for d in digits]   # 100, 109: inner zeros


def test_the_three_digit_counts_follow_the_oracle(tmp_path):
    assert _run_digits(tmp_path, "digits3", mapname="E1M2"), "three-digit digit_lines parted from stats_digits"


@pytest.mark.parametrize("mut", sorted(DIGIT3_MUTANTS))
def test_control_broken_three_digit_counts_are_caught(tmp_path, mut):
    assert not _run_digits(tmp_path, "digits3_" + mut.replace(" ", "_"), mut, "E1M2"), (
        "%s passed: the comparison is vacuous" % mut)


_WIDE = pytest.mark.skipif(not (ROOT / "assets" / "freedoom1.wad").exists(), reason="needs assets/freedoom1.wad")


@_WIDE
def test_e1m6_counters_are_three_nibbles_and_reach_past_255():
    w = _world("E1M6")
    assert SC.count_nibbles(w) == 3 and _nd("E1M6") == 3 and SC.count_nibbles(_world("E1M2")) == 2
    cases, totals = _cases("E1M6")
    top = max(t[0] for t in totals)                     # the most kills one skill counts (no soul: not COUNTKILL)
    assert top > 256 and {255, 256, top} <= {c[0] for c in cases}, (top, sorted({c[0] for c in cases}))


@_WIDE
def test_the_three_nibble_counts_follow_the_oracle(tmp_path):
    assert _run_digits(tmp_path, "digits3w", mapname="E1M6"), "three-nibble digit_lines parted from stats_digits"


@_WIDE
@pytest.mark.parametrize("mut", sorted(DIGIT3W_MUTANTS))
def test_control_broken_three_nibble_counts_are_caught(tmp_path, mut):
    assert not _run_digits(tmp_path, "digits3w_" + mut.replace(" ", "_"), mut, "E1M6"), (
        "%s passed: the comparison is vacuous" % mut)


def test_control_a_two_digit_layout_on_a_three_digit_map_is_refused():
    """the oracle's picture takes its layout from the slot count: 13 slots of a three-digit map's counts cannot be
    built -- count_codes refuses a count past two digits"""
    w = _world("E1M2")
    with pytest.raises(AssertionError):
        stats_digits(len(w.mon_things), len(w.mon_things), 0, 0, 0, 0, 2)


# ---- the frame ------------------------------------------------------------------------------------------------------
FRAME_CASES = 12


def _colours():
    wad = WadFile.from_path(str(ASSETS))
    return palette_colours(bytes(b for rgb in wad.playpal(0) for b in rgb))


def _frame_text(swap=False, mapname="E1M1") -> tuple:
    w = _world(mapname)
    cases, totals = _cases(mapname)
    cases = cases[:FRAME_CASES] if mapname == "E1M1" else cases[-FRAME_CASES:]
    nd = _nd(mapname)
    colours = _colours()
    frame = "\n".join(SC.frame_lines(CFG.W, CFG.H, colours, w)) + "\n"
    if swap:                                             # slot 4 (the items' tens) draws a 2 for a 1 and a 1 for a 2
        frame = frame.replace("  lvd4_1:\n", "  lvd4_T:\n").replace("  lvd4_2:\n", "  lvd4_1:\n") \
                     .replace("  lvd4_T:\n", "  lvd4_2:\n")
    body = ["stl.startup_and_init_all", "present.init_screen"]
    for case in cases:
        body += _set(case) + ["stl.fcall dg_go, dg_ret", "stl.fcall fr_go, fr_ret"]
    body += ["stl.loop", "dg_go:", _digit_text(w), "    stl.fret dg_ret",
             "fr_go:", frame, "    stl.output_char 0xFF", "    stl.fret fr_ret", *SC.routine_lines(), *_decls(w)]
    want = [level_done_pixels(CFG.W, CFG.H, colours, len(w.secret_sectors), _want(c, totals, nd)) for c in cases]
    return "\n".join(body) + "\n", want, cases, totals


class _Recording(InMemoryScreen):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.frames = []

    def _present(self):
        super()._present()
        self.frames.append(list(self.pixel_indices))


def _run_frames(tmp_path, name, swap=False, mapname="E1M1"):
    text, want, _cases_, _t = _frame_text(swap, mapname)
    out, _srcs = _assemble(tmp_path, name, text, extra=("present.fj", "fixed_point.fj"))
    screen = _Recording()
    fj.run(out, io_device=screen, print_time=False, print_termination=False)
    return screen.frames, want


def test_the_frame_cases_reach_a_one_and_a_two_in_the_items_tens():
    """R9's ground for the swap below: the frame cases show a 1 and a 2 in slot 4"""
    _text, _want_, cases, totals = _frame_text()
    assert {1, 2} <= {_want(c, totals)[4] for c in cases}


def test_every_level_complete_frame_is_the_oracles_picture(tmp_path):
    frames, want = _run_frames(tmp_path, "frames")
    assert len(frames) == FRAME_CASES
    bad = [i for i, (g, w_) in enumerate(zip(frames, want)) if g != w_]
    assert not bad, "LEVEL COMPLETE frames %s differ from the oracle's picture" % bad


def test_a_frame_with_two_digits_swapped_is_caught(tmp_path):
    frames, want = _run_frames(tmp_path, "frames_swap", swap=True)
    assert len(frames) == FRAME_CASES and any(g != w_ for g, w_ in zip(frames, want)), "the swap passed"


def test_the_three_digit_frames_follow_the_oracle(tmp_path):
    """M8 F1.1: E1M2's LEVEL COMPLETE -- the wider layout (three-digit counts) presented through the real screen"""
    frames, want = _run_frames(tmp_path, "frames3", mapname="E1M2")
    assert len(frames) == len(want) == FRAME_CASES
    for k, (got, exp) in enumerate(zip(frames, want)):
        assert got == exp, "E1M2 frame %d parted" % k
