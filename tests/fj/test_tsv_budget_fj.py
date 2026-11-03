"""M8 C11 (E1M7): THE DEG ATTRIBUTION BUDGET past 3 nibbles, on the real engine.

`frame.seg_pass1_leaf_body_ts` counts every MARKING two-sided seg a frame reaches in `n_tsv` and, at the budget,
sets `tsstop` / `tsbstop` (that seg is the last the budget allows). The budget must never bind (a binding one paints
the smudged columns): `wall_renderer._assert_pnear_unbound` holds the map's marking-seg count below it. E1M7 marks
4,183 segs, past the 3-nibble counter's 4,095, so a map's counter is `Config.TSV_NIBBLES` wide (MAP_CONFIG: E1M7 4)
and its budget `Config.TSV_BUDGET` = 16^n - 1; the macro DERIVES its width from the budget it is passed
(`(#budget+3)/4`), so the counter, its compare and its constant cannot drift apart.

THE ORACLE'S RULE (reference_model.render_wall_frame): a marking seg is skipped when `n_ts >= deg_mark`, else
`n_ts += 1` -- seg k (1-based) runs iff k <= budget, so the fj's latch must rise ON seg `budget` and never before.
(tests/host/test_tsv_width.py proves the oracle takes the map's budget.)

THE FJ: the macro's budget span TRANSPLANTED verbatim (from `hex.inc ... n_tsv` to `budget_ok:`) with its `bcap`
declaration, called once per seg for N = 4,200 segs (E1M7's 4,183 + slack); the harness prints the 1-based seg index
at which `tsstop` rose (4 hex digits), or nothing. `n_tsv` is declared Config.TSV_NIBBLES wide, as the emitter does.

R9 (each must PART from the oracle's rule):
  * the pre-C11 macro (the literal 3-nibble counter) at E1M7's budget: it binds at 4,095;
  * `n_tsv` declared 3 nibbles under a 4-nibble budget (the decl drifted from the budget): its top nibble lands on the
    next cell (`tsstop`) and the latch rises early.
"""
import re
from dataclasses import replace
from pathlib import Path

import flipjump as fj
import pytest
from flipjump.interpreter.io_devices.FixedIO import FixedIO

from doomfj.config import Config, map_cfg
from doomfj.harness import W
from doomfj.reference_model import DEG_PNEAR

ROOT = Path(__file__).resolve().parents[2]
NSEGS = 4200
_IDENT = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(?![\w.(])")


def _src():
    return (ROOT / "src/fj/frame_render.fj").read_text(encoding="utf-8").replace("\r\n", "\n")


def span(src):
    """the budget span of frame.seg_pass1_leaf_body_ts (verbatim, comments dropped) and its `bcap` declaration"""
    a = src.index("    def seg_pass1_leaf_body_ts ")
    body = src[a:src.index("\n    def ", a + 1)]
    lines = body.split("\n")
    s = next(n for n, ln in enumerate(lines) if ln.split("//")[0].strip().startswith("hex.inc ")
             and ln.split("//")[0].strip().endswith(", n_tsv"))
    e = next(n for n, ln in enumerate(lines) if ln.split("//")[0].strip() == "budget_ok:") + 1
    decl = [ln for ln in lines if ln.strip().startswith("bcap:")]
    assert len(decl) == 1, decl
    code = [ln.split("//")[0].rstrip() for ln in lines[s:e] if ln.split("//")[0].strip()]
    return code, decl[0].strip()


def program(src, budget: int, tsv_nibbles: int, nsegs: int = NSEGS) -> str:
    code, bdecl = span(src)
    text = "\n".join(code + ["        ;t_over", "      " + bdecl, "      t_over:"])     # the decl jumped over
    labels = set(re.findall(r"^\s*(\w+):", text, re.M))
    used = set(_IDENT.findall(text)) - {"budget"}
    glob = sorted(used - labels)
    assert set(glob) == {"n_tsv", "tsstop", "tsbstop"}, glob
    macro = "def t_budget budget @ %s < %s {\n%s\n}\n" % (", ".join(sorted(labels)), ", ".join(glob), text)
    main = ["stl.startup_and_init_all",
            "t_loop:",
            "    stl.fcall t_leaf, t_ret",
            "    hex.inc 4, t_i",
            "    hex.if0 1, tsstop, t_cont",
            "    hex.if1 1, t_said, t_cont",
            "    hex.set 1, t_said, 1",
            "    hex.print_as_digit 4, t_i, 1",
            "    stl.output_char 32",
            "  t_cont:",
            "    hex.cmp 4, t_i, t_n, t_loop, t_end, t_end",
            "  t_end:",
            "    stl.output_char 10",
            "    stl.loop",
            "t_leaf:",
            "    t_budget %d" % budget,
            "    stl.fret t_ret",
            macro,
            # the emitter's order (wall_renderer, the banks part): n_tsv, then the latch it must not reach
            "n_tsv: hex.vec %d" % tsv_nibbles, "tsstop: hex.vec 1", "tsbstop: hex.vec 1",
            "t_i: hex.vec 4", "t_n: hex.vec 4, %d" % nsegs, "t_said: hex.vec 1", "t_ret: hex.vec w/4"]
    return "\n".join(main) + "\n"


def run(tmp_path, name, src, budget, tsv_nibbles) -> bytes:
    """the fj's print. An fj that does not assemble RAISES: never a catch"""
    p = tmp_path / ("%s.fj" % name)
    p.write_text(program(src, budget, tsv_nibbles), encoding="utf-8")
    out = tmp_path / ("%s.fjm" % name)
    fj.assemble([p.resolve()], out, memory_width=W, warning_as_errors=True, print_time=False)
    io = FixedIO(b"")
    term = fj.run(out, io_device=io, print_time=False, print_termination=False)
    assert term.termination_cause == fj.TerminationCause.Looping, term.termination_cause
    return io.get_output(allow_incomplete_output=True)


def oracle_rule(budget: int, nsegs: int = NSEGS) -> bytes:
    """render_wall_frame's `n_ts >= deg_mark` skip: the last seg that runs is seg `budget`; the latch rises there"""
    ran = [k for k in range(1, nsegs + 1) if k - 1 < budget]
    stop = ran[-1] if len(ran) == budget else None
    return (("%04X " % stop) if stop else "").encode() + b"\n"


def test_the_widths():
    """the default is E1M1's 3 nibbles = DEG_PNEAR; E1M7 takes 4 through MAP_CONFIG; E1M2 keeps 3"""
    assert Config().TSV_NIBBLES == 3 and Config().TSV_BUDGET == DEG_PNEAR == 4095
    assert map_cfg(Config(), "E1M1").TSV_BUDGET == 4095 and map_cfg(Config(), "E1M2").TSV_BUDGET == 4095
    assert map_cfg(Config(), "E1M7").TSV_NIBBLES == 4 and map_cfg(Config(), "E1M7").TSV_BUDGET == 0xFFFF


@pytest.mark.parametrize("nib", [3, 4])
def test_the_budget_latch_is_the_oracles(tmp_path, nib):
    """3 nibbles: 4,200 segs bind at 4,095 (why E1M7 needs 4); 4 nibbles: they never bind"""
    cfg = replace(Config(), TSV_NIBBLES=nib)
    got, want = run(tmp_path, "b%d" % nib, _src(), cfg.TSV_BUDGET, cfg.TSV_NIBBLES), oracle_rule(cfg.TSV_BUDGET)
    assert got == want, "the budget latch parted from the oracle's rule (%d nibbles): fj %r oracle %r" % (nib, got, want)
    assert (want == b"0FFF \n") if nib == 3 else (want == b"\n")


def _pre_c11(src):
    """the macro before C11: a literal 3-nibble counter, compare and constant"""
    out = src.replace("hex.inc (#budget+3)/4, n_tsv", "hex.inc 3, n_tsv").replace(
        "hex.set (#budget+3)/4, bcap, budget", "hex.set 3, bcap, budget").replace(
        "hex.cmp (#budget+3)/4, n_tsv, bcap,", "hex.cmp 3, n_tsv, bcap,").replace(
        "bcap: hex.vec (#budget+3)/4", "bcap: hex.vec 3")
    code, decl = span(out)
    assert out != src and "(#budget+3)/4" not in "\n".join(code) + decl
    return out


def test_control_the_pre_c11_counter_binds_on_e1m7(tmp_path):
    """R9: the literal 3-nibble macro at E1M7's budget latches at seg 4,095 -- the oracle's never does"""
    b = map_cfg(Config(), "E1M7").TSV_BUDGET
    got = run(tmp_path, "pre", _pre_c11(_src()), b, 4)
    assert got == b"0FFF \n" and got != oracle_rule(b)


def test_control_a_decl_narrower_than_its_budget_parts(tmp_path):
    """R9: n_tsv declared 3 nibbles under the 4-nibble budget -- the counter's top nibble is tsstop's cell"""
    b = map_cfg(Config(), "E1M7").TSV_BUDGET
    assert run(tmp_path, "narrow", _src(), b, 3) != oracle_rule(b)


def test_e1m1_assembles_to_the_pre_c11_image(tmp_path):
    """E1M1 (and every 3-nibble map) is unchanged: at budget 4,095 the derived width IS the old literal 3 -- the
    transplanted span assembles to the same image, word for word, as the pre-C11 text"""
    images = []
    for name, src in (("now", _src()), ("pre", _pre_c11(_src()))):
        p = tmp_path / ("%s.fj" % name)
        p.write_text(program(src, DEG_PNEAR, 3), encoding="utf-8")
        out = tmp_path / ("%s.fjm" % name)
        fj.assemble([p.resolve()], out, memory_width=W, warning_as_errors=True, print_time=False)
        images.append(out.read_bytes())
    assert images[0] == images[1]
    p = tmp_path / "e7.fj"                     # and the control: E1M7's budget assembles to a different image
    p.write_text(program(_src(), 0xFFFF, 3), encoding="utf-8")
    fj.assemble([p.resolve()], tmp_path / "e7.fjm", memory_width=W, warning_as_errors=True, print_time=False)
    assert (tmp_path / "e7.fjm").read_bytes() != images[0]
