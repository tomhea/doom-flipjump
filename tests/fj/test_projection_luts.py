"""M12l (F5) — the projection LUTs the fj wall renderer reads, emitted as `.fj` read_table data tables
(tantoangle / viewangletox / xtoviewangle / finetangent). Each is the SAME host kernel the H5 oracle uses
(tables.py, R6 SSOT); here we assemble the emitted table, read a spread of entries TWICE each (R5 #8,
catches pointer/result-reg cleanup bugs), and assert byte-exact equality with the host value — so the fj
renderer and the oracle index identical projection data (D12). This is the data layer of the fj renderer.
"""
from pathlib import Path

import flipjump as fj

from doomfj.config import Config
from doomfj.harness import W
from doomfj.lut_generator import (
    generate_tantoangle_lut_fj, generate_finetangent_lut_fj,
    generate_xtoviewangle_lut_fj, generate_viewangletox_lut_fj,
)
from doomfj.reference_model import SLOPERANGE
from doomfj.tables import (
    tantoangle_table, viewangletox_table, xtoviewangle_table, finetangent_table,
)

FIXED_POINT_FJ = Path("src/fj/fixed_point.fj")   # provides hex.read_table


def _read_lut(tmp_path, name, lut_fj, host_values, picks, *, entry_nibbles, idx_nibbles):
    """Assemble `lut_fj` + a driver that reads each picked index twice via hex.read_table, then compare
    the printed entry_nibbles-digit output to the host values (masked to the entry width)."""
    mask = (1 << (4 * entry_nibbles)) - 1
    body, data, expected = [], [], b""
    for k, idx in enumerate(picks):
        for _ in range(2):
            body += [f"hex.read_table {entry_nibbles}, d, {name}, {idx_nibbles}, q{k}",
                     f"hex.print_as_digit {entry_nibbles}, d, 0", "stl.output 10"]
            expected += f"{host_values[idx] & mask:0{entry_nibbles}x}\n".encode()
        data.append(f"q{k}: hex.vec {idx_nibbles}, {idx}")
    data += [f"d: hex.vec {entry_nibbles}", lut_fj]
    prog = "stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n" + "\n".join(data) + "\n"
    p = tmp_path / f"{name}.fj"
    p.write_text(prog, encoding="utf-8")
    ok = fj.assemble_and_run_test_output(
        [FIXED_POINT_FJ.resolve(), p.resolve()], b"", expected,
        memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
    assert ok, f"{name}: fj read_table output != host table"


def test_tantoangle_lut_byte_exact(tmp_path):
    host = tantoangle_table(SLOPERANGE)
    picks = [0, 1, 512, 1024, 2047, SLOPERANGE]          # incl. anchors [0]=0, [SLOPERANGE]=ANG45
    _read_lut(tmp_path, "tantoangle", generate_tantoangle_lut_fj("tantoangle", SLOPERANGE),
              host, picks, entry_nibbles=8, idx_nibbles=3)


def test_finetangent_lut_byte_exact(tmp_path):
    cfg = Config()
    host = finetangent_table(cfg.TRIG_N)
    picks = [0, cfg.TRIG_N // 8, cfg.TRIG_N // 4, cfg.TRIG_N * 3 // 8, cfg.TRIG_N // 2, cfg.TRIG_N - 1]
    _read_lut(tmp_path, "finetangent", generate_finetangent_lut_fj("finetangent", cfg.TRIG_N),
              host, picks, entry_nibbles=8, idx_nibbles=3)


def test_xtoviewangle_lut_byte_exact(tmp_path):
    cfg = Config()
    host = xtoviewangle_table(cfg.VIEW_W, cfg.TRIG_N)
    picks = [0, 1, cfg.VIEW_W // 2, cfg.VIEW_W - 1, cfg.VIEW_W]   # incl. both edges + centre
    _read_lut(tmp_path, "xtoviewangle", generate_xtoviewangle_lut_fj("xtoviewangle", cfg.VIEW_W, cfg.TRIG_N),
              host, picks, entry_nibbles=8, idx_nibbles=2)


def test_viewangletox_lut_byte_exact_incl_signed_sentinel(tmp_path):
    """viewangletox holds SIGNED columns (the -1 / view_w+1 off-screen sentinels); the two's-complement
    encoding must round-trip, so include an index whose value is the negative sentinel."""
    cfg = Config()
    host = viewangletox_table(cfg.VIEW_W, cfg.TRIG_N)
    # straight-ahead -> CENTERX; +45deg -> col 0; -45deg -> col view_w; the table ends carry sentinels
    picks = [0, 512, 1024, 1536, len(host) - 1]
    assert -1 in (host[picks[0]], host[picks[-1]]) or min(host) == -1   # a signed sentinel is exercised
    _read_lut(tmp_path, "viewangletox",
              generate_viewangletox_lut_fj("viewangletox", cfg.VIEW_W, cfg.TRIG_N),
              host, picks, entry_nibbles=8, idx_nibbles=3)
