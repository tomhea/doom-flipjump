from pathlib import Path

from doomfj.config import Config, FLAT_MAX_WORDS
from doomfj.harness import probe

MEMORY_MAP = Path("src/fj/memory_map.fj")


def _assemble_memory_map(cfg: Config, tmp_path):
    """Generate fj_consts for cfg, then assemble+run [fj_consts, memory_map] via the probe."""
    consts = cfg.emit_fj_consts(tmp_path / "fj_consts.fj")
    return probe([consts, MEMORY_MAP])


def test_memory_map_assembles_flat(tmp_path):
    term = _assemble_memory_map(Config(), tmp_path)
    assert str(term.storage_mode) == "flat"   # R4: no silent paged fallback
    assert term.op_counter > 0                 # it actually ran to stl.loop


def test_memory_map_assembles_flat_at_second_resolution(tmp_path):
    """fj-level resolution-parametricity guard: regenerate at 320x200 — the program must
    recompile 'as if native' and still run flat (the §1 2-const invariant)."""
    term = _assemble_memory_map(Config(W=320, H=200), tmp_path)
    assert str(term.storage_mode) == "flat"
    assert term.op_counter > 0


def test_span_skeleton_under_flat_limit():
    """Span/alignment-invariant HOME (the M1 skeleton). M10 (R0) fills the real per-table
    numbers; M1 only checks the known segments and the R-3 ceiling."""
    c = Config()
    ledger = c.span_ledger()
    assert ledger["framebuffer"] == c.W * c.H     # framebuffer = W*H packed bytes (§1.2)
    assert ledger["palette"] == c.NCOLORS * 3
    assert c.total_span() < FLAT_MAX_WORDS         # R-3: total span < flat limit
