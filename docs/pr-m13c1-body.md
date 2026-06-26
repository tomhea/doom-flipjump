## Summary

M13c1 (fj, the data layer of the floor raster): emit the three floor/ceiling (visplane) LUTs the fj
plane raster will read — `yslope` (row → distance slope), `distscale` (column → 1/|cos| fisheye), and
`zlight` (distance light, the `LIGHTLEVELS×MAXLIGHTZ` grid flattened row-major). Each is a
`hex.read_table` data table emitted from the **same `tables.py` host kernel the M13a/b oracle uses**
(R6 SSOT), so the fj plane raster (M13c2/3 + M13d) and the oracle (`_plane_pixel`/`_draw_span`) index
identical visplane data (D12). Standalone rung (the M12l projection-LUT precedent): the tables are
assembled + read here; they get wired into `emit_wall_renderer` (replacing `render_background_reg`) in
the next rungs.

## TDD evidence (R1)

### Before (FAIL — generators stubbed to emit zero-valued tables; assembles + runs, wrong output):

```
FFF                                                                      [100%]
================================== FAILURES ===================================
_________________________ test_yslope_lut_byte_exact __________________________

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_yslope_lut_byte_exact0')

    def test_yslope_lut_byte_exact(tmp_path):
        cfg = Config()
        host = yslope_table(cfg.VIEW_W, cfg.VIEW_H)
        picks = [0, 1, cfg.CENTERY - 1, cfg.CENTERY, cfg.CENTERY + 1, cfg.VIEW_H - 1]   # incl. the horizon peak
>       _read_lut(tmp_path, "yslope", generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H),
                  host, picks, entry_nibbles=8, idx_nibbles=2)

tests\fj\test_floor_luts.py:47: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_yslope_lut_byte_exact0')
name = 'yslope'
lut_fj = '// LUT "yslope": 100 entries of 8 nibbles (doomfj.lut_generator)\nyslope:\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n  ...  hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n'
host_values = [105916, 108100, 110376, 112750, 115228, 117817, ...]
picks = [0, 1, 49, 50, 51, 99]

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
>       assert ok, f"{name}: fj read_table output != host table"
E       AssertionError: yslope: fj read_table output != host table
E       assert False

tests\fj\test_floor_luts.py:40: AssertionError
---------------------------- Captured stdout call -----------------------------
  parsing:         0.143s
  macro resolve:   1.866s
  labels resolve:  0.926s
  create binary:   3.010s
  loading memory:  0.184s

Finished by looping after 0.076s (114,448 ops executed).
________________________ test_distscale_lut_byte_exact ________________________

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_distscale_lut_byte_exact0')

    def test_distscale_lut_byte_exact(tmp_path):
        cfg = Config()
        host = distscale_table(cfg.VIEW_W, cfg.TRIG_N)
        picks = [0, 1, cfg.CENTERX, cfg.VIEW_W - 1]                  # incl. the straight-ahead centre (cos~1)
>       _read_lut(tmp_path, "distscale", generate_distscale_lut_fj("distscale", cfg.VIEW_W, cfg.TRIG_N),
                  host, picks, entry_nibbles=8, idx_nibbles=2)

tests\fj\test_floor_luts.py:55: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_distscale_lut_byte_exact0')
name = 'distscale'
lut_fj = '// LUT "distscale": 160 entries of 8 nibbles (doomfj.lut_generator)\ndistscale:\n    hex.vec 8, 0x0\n    hex.vec 8, 0...  hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n    hex.vec 8, 0x0\n'
host_values = [92398, 91841, 91292, 90754, 90224, 89577, ...]
picks = [0, 1, 80, 159]

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
>       assert ok, f"{name}: fj read_table output != host table"
E       AssertionError: distscale: fj read_table output != host table
E       assert False

tests\fj\test_floor_luts.py:40: AssertionError
---------------------------- Captured stdout call -----------------------------
  parsing:         0.029s
  macro resolve:   1.189s
  labels resolve:  0.575s
  create binary:   2.102s
  loading memory:  0.142s

Finished by looping after 0.049s (75,488 ops executed).
____________________ test_zlight_lut_byte_exact_flattened _____________________

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_zlight_lut_byte_exact_fla0')

    def test_zlight_lut_byte_exact_flattened(tmp_path):
        """zlight is the LIGHTLEVELS x MAXLIGHTZ grid flattened row-major; read entry `lvl*MAXLIGHTZ + zidx`.
        Exercise the corners (brightest near / darkest far) + an interior point, twice each (R5)."""
        cfg = Config()
        grid = zlight_table(cfg.VIEW_W, COLORMAP_LIGHTS)
        flat = [v for row in grid for v in row]
        cells = [(0, 0), (0, MAXLIGHTZ - 1), (LIGHTLEVELS - 1, 0), (LIGHTLEVELS - 1, MAXLIGHTZ - 1),
                 (8, 64), (15, 1)]
        picks = [lvl * MAXLIGHTZ + zidx for (lvl, zidx) in cells]
>       _read_lut(tmp_path, "zlight", generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS),
                  flat, picks, entry_nibbles=2, idx_nibbles=3)

tests\fj\test_floor_luts.py:68: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-922/test_zlight_lut_byte_exact_fla0')
name = 'zlight'
lut_fj = '// LUT "zlight": 2048 entries of 2 nibbles (doomfj.lut_generator)\nzlight:\n    hex.vec 2, 0x0\n    hex.vec 2, 0x0\n ...  hex.vec 2, 0x0\n    hex.vec 2, 0x0\n    hex.vec 2, 0x0\n    hex.vec 2, 0x0\n    hex.vec 2, 0x0\n    hex.vec 2, 0x0\n'
host_values = [20, 31, 31, 31, 31, 31, ...]
picks = [0, 127, 1920, 2047, 1088, 1921]

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
>       assert ok, f"{name}: fj read_table output != host table"
E       AssertionError: zlight: fj read_table output != host table
E       assert False

tests\fj\test_floor_luts.py:40: AssertionError
---------------------------- Captured stdout call -----------------------------
  parsing:         0.089s
  macro resolve:   1.184s
  labels resolve:  0.529s
  create binary:   1.995s
  loading memory:  0.120s

Finished by looping after 0.042s (54,744 ops executed).
=========================== short test summary info ===========================
FAILED tests/fj/test_floor_luts.py::test_yslope_lut_byte_exact - AssertionErr...
FAILED tests/fj/test_floor_luts.py::test_distscale_lut_byte_exact - Assertion...
FAILED tests/fj/test_floor_luts.py::test_zlight_lut_byte_exact_flattened - As...
3 failed in 15.07s
```

### After (3/3 PASS — fj read_table output byte-exact vs the host tables):

```
...                                                                      [100%]
3 passed in 15.80s
```

## Integration evidence (R2)

`tests/fj/test_floor_luts.py` assembles each emitted table and reads a spread of entries **twice each**
(R5 #8 — pointer/result-reg cleanup) byte-exact vs the host: `yslope` incl. the horizon-row peak,
`distscale` incl. the straight-ahead centre, `zlight` incl. the bright-near / dark-far corners. (See the
FAIL/PASS logs above.)

## R-by-R self-check

| Rule | Status |
| --- | --- |
| R1 tests-first evidence | pass |
| R2 integration evidence | pass (byte-exact read_table outputs) |
| R3 coverage of touched logic | pass (tests/fj/test_floor_luts.py for the 3 new generators) |
| R4 span/flat guard | n/a (standalone tables; not yet in build_doom's binary — they land in the span ledger when wired at M13c2/3) |
| R5 signed-compare + LUT correctness | pass (per-entry + call-twice for all 3 LUTs; values are non-negative 16.16 / colormap rows) |
| R6 single source of truth | pass (generators draw from tables.py yslope/distscale/zlight — the same kernels the oracle uses) |
| R7 branch + PR naming | pass (`m13c1-fj-floor-luts`, `M13c1: ...`) |
| R8 zero new warnings | pass (warning_as_errors=True in the harness; pytest clean) |

## Test plan

- [x] `tests/fj/test_floor_luts.py` (new) — FAIL (stubbed) → PASS (3/3) captured
- [x] yslope / distscale / zlight byte-exact vs tables.py, twice per entry (R5)
- [ ] CR-ist approves
