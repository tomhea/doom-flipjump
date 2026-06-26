## Summary

M13c2 (fj): land the **flat-colored floor/ceiling plane pixel** kernel `plane.draw_pixel`
(`src/fj/plane_render.fj`), byte-exact vs the oracle's `_plane_pixel` (D12). This is the distance-light
spine of the visplane raster: `distance = FixedMul(planeheight, yslope[y])`; `zidx = min(127,
distance>>20)`; `lvl = light>>4`; `zrow = zlight[lvl*128 + zidx]`; `lit = colormap[zrow][pbase]`. It
reads the M13c1 `yslope`/`zlight` read_table LUTs and reuses the `cm.apply` colormap idiom. Standalone
rung (the projection-kernel precedent): proven in isolation here, wired into `emit_wall_renderer`
(replacing `render_background_reg`) at M13c3, then extended to the perspective u,v sample at M13d.

## TDD evidence (R1)

### Before (FAIL — kernel stubbed to skip the distance light / output the raw base; assembles + runs, wrong output):

```
F                                                                        [100%]
================================== FAILURES ===================================
_________________ test_plane_draw_pixel_byte_exact_vs_oracle __________________

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-925/test_plane_draw_pixel_byte_exa0')

    def test_plane_draw_pixel_byte_exact_vs_oracle(tmp_path):
        cfg = Config()
        rm = ReferenceModel(cfg)
        colormap = WadFile.from_path(str(ASSET)).colormap()
        yslope = generate_yslope_lut_fj("yslope", cfg.VIEW_W, cfg.VIEW_H)
        zlight = generate_zlight_lut_fj("zlight", cfg.VIEW_W, COLORMAP_LIGHTS)
        cm = compile_colormap("cm", WadFile.from_path(str(ASSET)), lights=COLORMAP_LIGHTS)
    
        body, data, expected = [], [], b""
        for k, (ph, light, base, y) in enumerate(CASES):
            for _ in range(2):   # call twice per case (R5 #8): catches scratch/result-reg cleanup bugs
                body += [
                    f"hex.mov 8, planeheight, ph{k}", f"hex.mov 2, light, lt{k}",
                    f"hex.mov 2, pbase, pb{k}", f"hex.mov 2, y, yy{k}",
                    "stl.fcall plane_leaf, plane_ret",
                    "hex.print_as_digit 2, lit, 0", "stl.output 10",
                ]
                expected += f"{rm._plane_pixel(colormap, ph, light, base, y):02x}\n".encode()
            data += [f"ph{k}: hex.vec 8, {ph}", f"lt{k}: hex.vec 2, {light}",
                     f"pb{k}: hex.vec 2, {base}", f"yy{k}: hex.vec 2, {y}"]
        data += [
            "planeheight: hex.vec 8", "light: hex.vec 2", "pbase: hex.vec 2", "y: hex.vec 2",
            "lit: hex.vec 2", "plane_ret: ;0",
            yslope, zlight, cm,
        ]
        prog = ("stl.startup_and_init_all\n" + "\n".join(body) + "\nstl.loop\n"
                + "plane_leaf: plane.draw_pixel\n" + "\n".join(data) + "\n")
        p = tmp_path / "plane_kernel.fj"
        p.write_text(prog, encoding="utf-8")
        ok = fj.assemble_and_run_test_output(
            [PLANE_FJ.resolve(), FIXED_POINT_FJ.resolve(), p.resolve()], b"", expected,
            memory_width=W, warning_as_errors=True, should_raise_assertion_error=False)
>       assert ok, "plane.draw_pixel: fj output != oracle _plane_pixel"
E       AssertionError: plane.draw_pixel: fj output != oracle _plane_pixel
E       assert False

tests\fj\test_plane_kernel.py:72: AssertionError
---------------------------- Captured stdout call -----------------------------
  parsing:         2.727s
  macro resolve:   1.335s
  labels resolve:  0.363s
  create binary:   1.071s
  loading memory:  0.092s

Finished by looping after 0.031s (391,035 ops executed).
=========================== short test summary info ===========================
FAILED tests/fj/test_plane_kernel.py::test_plane_draw_pixel_byte_exact_vs_oracle
1 failed in 6.09s
```

### After (PASS — byte-exact vs the oracle over 8 cases x2):

```
.                                                                        [100%]
1 passed in 5.98s
```

## Integration evidence (R2)

`tests/fj/test_plane_kernel.py` drives `plane.draw_pixel` over 8 `(planeheight, light, pbase, y)` cases
(near/far/clamp distances, light levels 0..255, the horizon row and the top/bottom screen edges), twice
each (R5 #8), comparing the printed lit byte to `ReferenceModel._plane_pixel`. (See the FAIL/PASS logs.)

## R-by-R self-check

| Rule | Status |
| --- | --- |
| R1 tests-first evidence | pass |
| R2 integration evidence | pass (byte-exact vs oracle) |
| R3 coverage of touched logic | pass (tests/fj/test_plane_kernel.py for plane.draw_pixel) |
| R4 span/flat guard | n/a (standalone kernel; not yet in build_doom's binary — lands in the span ledger when wired at M13c3) |
| R5 signed-compare + LUT correctness | pass (distance/zidx/lvl all non-negative -> hex.cmp clamp is correct; call-twice per case) |
| R6 single source of truth | pass (reads the tables.py-derived yslope/zlight LUTs + cm.apply; mirrors _plane_pixel exactly) |
| R7 branch + PR naming | pass (`m13c2-fj-plane-kernel`, `M13c2: ...`) |
| R8 zero new warnings | pass (warning_as_errors=True; pytest clean) |

## Test plan

- [x] `tests/fj/test_plane_kernel.py` (new) — FAIL (stub) -> PASS captured
- [x] byte-exact vs oracle over near/far/clamp + light spread + horizon/edges, twice per case (R5)
- [ ] CR-ist approves
