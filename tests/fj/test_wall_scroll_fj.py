"""M8 -- THE SCROLLING WALL (special 48), on the real flipjump engine against the MODEL (doomfj.scrollcode).

The fj side is the REAL emitted text: a seg's pass-2 call as the emitter writes it (`scrollcode.pass2_lines` for the
emitter's own choice `scrollcode.seg_scrolls(seg, scroll_lines(lds))`, on E1M2's real segs), around a stand-in
`seg_pass2_leaf` that runs the column key lines READ OUT OF src/fj/frame_render.fj (the `rep(w1r, k)` p2_xkey lines:
p2_xkey = x + wnoff, then the wnoise / wnoise2 / wnoise3 lookups) for five columns, and the three tables generated as
the emitter generates them over `scrollcode.wnoise_domain` (E1M2's game tier: 1,056 keys). Each record pokes lvtime
(all 5 nibbles) and wnoff, runs the block, and prints every column's key and its three group keys, then wnoff after.

The model: the segs whose line is special 48 (read off the WAD here, not through scrollcode) take
key = x + wnoff + (leveltime & 0xFF) -- reference_model.render_wall_frame's seg_xoff with World.wall_scroll's value --
every other seg x + wnoff; the group keys are ReferenceModel.wall_noise / wall_noise2 / wall_noise3 of the key; wnoff
is back where it was after every seg. And the three tables over EVERY key of the domain.

R9: each mutant must be caught -- `scroll_dropped` (no add), `wrong_sign` (the slide subtracted), `wrong_seg` (the
emitter's choice moved to the line before the scrolling one), `not_restored` (wnoff left slid). A key outside the
tables' domain prints `!` instead of dispatching (a wrong-sign key would jump out of the table).

OPS (printed, -s): the wrap's price per scrolling seg drawn, and a lookup's price in the 1,056-key tables against
E1M1's 801.
"""
import re
from pathlib import Path

import flipjump as fj
import pytest

from doomfj import scrollcode as SC
from doomfj.config import GAME_CFG, Config, map_cfg
from doomfj.harness import W
from doomfj.lut_generator import generate_dispatch_table_fj
from doomfj.reference_model import ReferenceModel
from doomfj.restartcode import LVTIME_NIBBLES
from doomfj.wad import WadFile
from doomfj.wall_renderer import hoisted_scratch_fj

ROOT = Path(__file__).resolve().parents[2]
FJ = ROOT / "src" / "fj"
MAPWAD = ROOT / "tests" / "fixtures" / "freedoom_e1m2.wad"
needs_map = pytest.mark.skipif(not MAPWAD.exists(), reason="needs tests/fixtures/freedoom_e1m2.wad")

LVTIMES = (0, 1, 2, 0x7F, 0xFF, 0x100, 0x1A5, 0x12345, 0xFFFFF)
WNOFFS = (0, 1, 255, 383, 639)
XS = (0, 1, 79, 159, 160)
CFG = map_cfg(GAME_CFG, "E1M2")
BANG = "!" * 6


def key_lines() -> list:
    """the column key lines of frame_render.fj's pass-2 column (the W1R-ANCHOR block), `rep(..., k)` stripped"""
    out = []
    for ln in (FJ / "frame_render.fj").read_text(encoding="utf-8").split("\n"):
        t = ln.split("//")[0].strip()
        m = re.match(r"rep\((w1r|noise\*w1r), k\) (.*p2_xkey.*)$", t)
        if m:
            out.append(m.group(2).strip())
    assert len(out) == 6 and out[2] == "hex.add 4, p2_xkey, wnoff", out
    return out


@pytest.fixture(scope="module")
def level():
    w = WadFile.from_path(MAPWAD)
    from doomfj.reference_model import build_scene
    lds = w.linedefs("E1M2")
    segs = build_scene(w, w, "E1M2", {}).cmap.segs
    scroll = [si for si, sg in enumerate(segs) if lds[sg.linedef].special == 48]      # the WAD's own, not scrollcode's
    assert len(scroll) == 2, scroll
    before = [next(si for si, sg in enumerate(segs) if sg.linedef == segs[s].linedef - 1) for s in scroll]
    plain = before + [0]
    assert all(lds[segs[si].linedef].special != 48 for si in plain)
    return lds, segs, scroll + plain


def _tables(dom: int) -> list:
    rm = ReferenceModel
    return [generate_dispatch_table_fj(n, [f(x) for x in range(dom)], index_nibbles=3, result_nibbles=2)
            for n, f in (("wnoise", rm.wall_noise), ("wnoise2", rm.wall_noise2), ("wnoise3", rm.wall_noise3))]


def _program(lds, segs, test_segs, choose, pass2) -> str:
    dom = SC.wnoise_domain(CFG.VIEW_W, True, True)
    kl = key_lines()
    body = ["stl.startup_and_init_all"]
    for si in test_segs:
        blk = "blk_s" if choose(segs[si], SC.scroll_lines(lds)) else "blk_p"
        for L in LVTIMES:
            for Wn in WNOFFS:
                body += ["hex.set %d, lvtime, %d" % (LVTIME_NIBBLES, L), "hex.set 4, wnoff, %d" % Wn,
                         "stl.fcall %s, blk_ret" % blk, "hex.print_as_digit 4, wnoff, 0", "stl.output 10"]
    # the tables, every key of the domain
    for k in range(dom):
        body += ["hex.set 4, p2_xkey, %d" % k, *kl[3:], "hex.print_as_digit 2, p2_gnrow, 0",
                 "hex.print_as_digit 2, gnrow2, 0", "hex.print_as_digit 2, gnrow3, 0", "stl.output_char 32"]
    body += ["stl.output 10", "stl.loop",
             "blk_s:", *pass2(True), "stl.fret blk_ret",
             "blk_p:", *pass2(False), "stl.fret blk_ret",
             "seg_pass2_leaf:"]
    for x in XS:
        body += ["hex.set 8, x, %d" % x, *kl[:3], "hex.print_as_digit 4, p2_xkey, 0",
                 "hex.cmp 4, p2_xkey, c_dom, in%d, out%d, out%d" % (x, x, x),
                 "out%d:" % x, "stl.output \"%s\"" % BANG, ";next%d" % x,
                 "in%d:" % x, *kl[3:], "hex.print_as_digit 2, p2_gnrow, 0", "hex.print_as_digit 2, gnrow2, 0",
                 "hex.print_as_digit 2, gnrow3, 0",
                 "next%d:" % x, "stl.output_char 32"]
    body += ["stl.fret seg_ret2"]
    # (p2_xkey and p2_gnrow come with hoisted_scratch_fj, as the emitted program's do)
    data = ["lvtime: hex.vec %d, 0" % LVTIME_NIBBLES, "wnoff: hex.vec 4", "x: hex.vec 8",
            "gnrow2: hex.vec 2", "gnrow3: hex.vec 2", "c_dom: hex.vec 4, %d" % dom,
            "blk_ret: hex.vec w/4", "seg_ret2: hex.vec w/4", *SC.DECLS, *_tables(dom)]
    return "\n".join(body + data) + "\n" + hoisted_scratch_fj()


def _assemble_run(tmp_path, name, text):
    p = tmp_path / ("%s.fj" % name)
    p.write_text(text, encoding="utf-8")
    consts = Config().emit_fj_consts(tmp_path / "fj_consts.fj")
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([consts.resolve(), (FJ / "fixed_point.fj").resolve(), (FJ / "projection.fj").resolve(),
                 (FJ / "frame_render.fj").resolve(), (FJ / "sim.fj").resolve(), p.resolve()], out,
                memory_width=W, print_time=False)
    from flipjump.interpreter.io_devices.FixedIO import FixedIO
    io = FixedIO(b"")
    st = fj.run(out, io_device=io, print_time=False, print_termination=False)
    return io.get_output(allow_incomplete_output=True).decode("ascii").split("\n"), st.op_counter


def _model(lds, segs, test_segs) -> list:
    rm = ReferenceModel
    out = []
    for si in test_segs:
        scrolls = lds[segs[si].linedef].special == 48
        for L in LVTIMES:
            for Wn in WNOFFS:
                toks = []
                for x in XS:
                    k = x + Wn + (L & 0xFF if scrolls else 0)
                    toks.append("%04x%02x%02x%02x" % (k, rm.wall_noise(k), rm.wall_noise2(k), rm.wall_noise3(k)))
                out.append(" ".join(toks) + " %04x" % Wn)
    dom = SC.wnoise_domain(CFG.VIEW_W, True, True)
    out.append(" ".join("%02x%02x%02x" % (rm.wall_noise(k), rm.wall_noise2(k), rm.wall_noise3(k))
                        for k in range(dom)))
    return out


def _verdict(got, want):
    for i, (g, w) in enumerate(zip(got, want)):
        if g.strip() != w:
            return "record %d: fj %r, model %r" % (i, g.strip()[:80], w[:80])
    if len(got) < len(want):
        return "%d records printed of %d" % (len(got), len(want))
    return None


def _sub(lines, old, new):
    """`lines` with the one line `old` replaced by `new` (None: removed)"""
    assert sum(ln == old for ln in lines) == 1, (old, lines)
    return [new if ln == old else ln for ln in lines if ln != old or new is not None]


def _mut_wrap(old, new):
    return lambda s: _sub(SC.pass2_lines(s), old, new) if s else SC.pass2_lines(s)


ADD = "    hex.add 4, wnoff, wnscr"
MUTANTS = {
    "scroll_dropped": (SC.seg_scrolls, _mut_wrap(ADD, None)),
    "wrong_sign": (SC.seg_scrolls, _mut_wrap(ADD, "    hex.sub 4, wnoff, wnscr")),
    "wrong_seg": (lambda seg, lines: seg.linedef + 1 in lines, SC.pass2_lines),
    "not_restored": (SC.seg_scrolls, _mut_wrap("    hex.mov 4, wnoff, wnsave", None)),
}


@needs_map
def test_the_scrolling_segs_slide_as_the_model(tmp_path, level):
    lds, segs, test_segs = level
    got, _ops = _assemble_run(tmp_path, "scroll", _program(lds, segs, test_segs, SC.seg_scrolls, SC.pass2_lines))
    want = _model(lds, segs, test_segs)
    bad = _verdict(got, want)
    assert bad is None, bad
    # vacuity: a slide moved a key past E1M1's 801-key tables; lvtime 0x100 slides nothing; a plain seg never slides
    assert SC.wnoise_domain(CFG.VIEW_W, True, False) == 801
    assert any(int(t[:4], 16) >= 801 for ln in want[:-1] for t in ln.split()[:-1])
    assert SC.wnoise_domain(CFG.VIEW_W, True, True) == 1056 == CFG.VIEW_W + 639 + 255 + 2


@needs_map
@pytest.mark.parametrize("name", sorted(MUTANTS))
def test_a_broken_scroll_is_caught(tmp_path, level, name):
    lds, segs, test_segs = level
    choose, pass2 = MUTANTS[name]
    assert (choose, pass2) != (SC.seg_scrolls, SC.pass2_lines)
    got, _ops = _assemble_run(tmp_path, "mut", _program(lds, segs, test_segs, choose, pass2))
    assert _verdict(got, _model(lds, segs, test_segs)) is not None, "a scroll with %r passed every record" % name


N_OPS = 64


def _ops_program(scrolls: bool, dom: int, lookups: bool) -> str:
    """N_OPS calls of the seg's pass-2 block around an empty leaf, or (lookups) the three lookups over keys 0..800"""
    kl = key_lines()
    body = ["stl.startup_and_init_all", "hex.set %d, lvtime, %d" % (LVTIME_NIBBLES, 0xA5), "hex.set 4, wnoff, 383"]
    if lookups:
        for k in range(801):
            body += ["hex.set 4, p2_xkey, %d" % k, *kl[3:]]
    else:
        body += ["stl.fcall blk, blk_ret"] * N_OPS
    body += ["stl.loop", "blk:", *SC.pass2_lines(scrolls), "stl.fret blk_ret", "seg_pass2_leaf:", "stl.fret seg_ret2"]
    data = ["lvtime: hex.vec %d, 0" % LVTIME_NIBBLES, "wnoff: hex.vec 4", "gnrow2: hex.vec 2", "gnrow3: hex.vec 2",
            "blk_ret: hex.vec w/4", "seg_ret2: hex.vec w/4", *SC.DECLS, *_tables(dom)]
    return "\n".join(body + data) + "\n" + hoisted_scratch_fj()


def test_the_price(tmp_path):
    """MEASURED: the wrap's ops per scrolling seg drawn (a scrolling seg against a plain one, N_OPS each), and the
    lookups' ops in E1M2's 1,056-key tables against E1M1's 801 (the same 801 keys)"""
    _o, plain = _assemble_run(tmp_path, "plain", _ops_program(False, 801, False))
    _o, wrap = _assemble_run(tmp_path, "wrap", _ops_program(True, 801, False))
    per_seg = (wrap - plain) / N_OPS
    _o, t801 = _assemble_run(tmp_path, "t801", _ops_program(False, 801, True))
    _o, t1056 = _assemble_run(tmp_path, "t1056", _ops_program(False, 1056, True))
    per_col = (t1056 - t801) / 801
    print("\nwall scroll: the wrap costs %.1f ops per scrolling seg drawn (%d vs %d ops for %d calls); the three "
          "lookups cost %+.2f ops per column in the 1,056-key tables (%d vs %d ops for 801 columns)"
          % (per_seg, wrap, plain, N_OPS, per_col, t1056, t801))
    assert 0 < per_seg < 600, per_seg
    assert abs(per_col) < 20, per_col
