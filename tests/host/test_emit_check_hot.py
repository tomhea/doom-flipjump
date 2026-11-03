"""M8 (docs/handoff-e1m2.md 9): `scripts/emit_check.py`'s hot-block count -- frame.arm5's window measured from the
emitted TEXT, before any assembly (build.hot_window_violation is the build's own refusal, from the labels).

The window is 16,384 ops: exactly that fits, one more is refused (the boundary is the control); `hex.vec w/4` is 8
ops; a line the count does not know is refused rather than skipped (a skipped line would under-count silently).
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NL = chr(10)


def _ec():
    spec = importlib.util.spec_from_file_location("emit_check", ROOT / "scripts" / "emit_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tables(cells, extra=()):
    return {"tables": NL.join(["guard:", "pclm:"] + [";0 * dw"] * cells + list(extra) + ["wrej: hex.vec 1"])}


def test_exactly_the_window_fits_and_one_more_is_refused():
    ec = _ec()
    ec.hot_block_check(_tables(ec.HOT_WINDOW_OPS))
    with pytest.raises(AssertionError, match="past frame.arm5's window"):
        ec.hot_block_check(_tables(ec.HOT_WINDOW_OPS + 1))


def test_a_register_of_w_over_4_is_eight_ops():
    ec = _ec()
    ec.hot_block_check(_tables(ec.HOT_WINDOW_OPS - 8, ["r: hex.vec w/4"]))
    with pytest.raises(AssertionError):
        ec.hot_block_check(_tables(ec.HOT_WINDOW_OPS - 7, ["r: hex.vec w/4"]))


def test_a_line_the_count_does_not_know_is_refused():
    ec = _ec()
    with pytest.raises(AssertionError, match="does not know"):
        ec.hot_block_check(_tables(10, ["    some.macro 3, x"]))


def test_e1m2_b3s_text_counts_its_labels():
    """the count against a real build's labels: E1M2 b3's tables part gives 15,376 ops, pclm 0x200000 .. wrej
    0x2F0400 in its label table (skipped where the generated part is absent)"""
    f = ROOT / "build" / "generated_doom_e1m2_b3" / "e1m2_01_tables.fj"
    if not f.exists():
        pytest.skip("build/generated_doom_e1m2_b3 is not on this machine")
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        _ec().hot_block_check({"tables": f.read_text(encoding="utf-8")})
    assert "15,376 ops" in out.getvalue()


# ---- M8 l12fix: constant_width_check -- a literal wider than its register (E1M3 / E1M4 / E1M5's pk_t) -----------------
def test_a_constant_that_fits_its_register_passes():
    _ec().constant_width_check({"walk": NL.join(["    hex.set 2, pk_t, 255", "    hex.set 3, pk_t, 0xFFF",
                                                  "    hex.xor_by w/4, cur_ssp, sshead + 5*dw",
                                                  "    hex.set 1, x + 2*dw, 15  // a comment"])})


def test_control_a_constant_past_its_register_is_refused():
    """R9: the E1M5 line itself, and a 1-nibble xor_by of 16"""
    ec = _ec()
    with pytest.raises(AssertionError, match="pk_t, 275"):
        ec.constant_width_check({"walk": "    hex.set 2, pk_t, 275"})
    with pytest.raises(AssertionError, match="wider than their registers"):
        ec.constant_width_check([("main", "    hex.xor_by 1, f, 16")])
