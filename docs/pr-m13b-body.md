## Summary

M13b (oracle): replace the M13a flat-colored floor tier with **full-res perspective-textured
floors/ceilings** — DOOM's R_DrawPlanes / R_MapPlane / R_DrawSpan. After the BSP walk records each
claimed column's ceiling/floor region (height + flat + light), `_render_planes_textured` rasterizes
them as **horizontal spans**: for each screen row, consecutive columns sharing a visplane (region +
flat + plane-height + light) form a span, and the span is drawn with the perspective **2-coord (u,v)
DDA** — `distance = FixedMul(planeheight, yslope[y])`, per-pixel `xstep/ystep` from the per-frame
`basexscale/baseyscale` (R_ClearPlanes), span-left `xfrac/yfrac` seeded from `distscale[x1]` + the
column view angle, then `flat[(yfrac>>10 & 63·64) + (xfrac>>16 & 63)]` distance-lit (zlight). This is
the chosen §1 default (full-res textured floors, ~20 fps target). The cheaper M13a flat-colored tier is
retained behind `floor_texturing=False` (the §2 perf fallback) and stays byte-exact (its goldens are
re-asserted).

New shared LUT (R6): `distscale_table` (per-column `1/|cos|` fisheye correction). The fj span raster
mirrors this at M13c (flat-color) / M13d (textured); the two live-oracle E1M1 fj golden tests remain
`skip`ped until M13d, same as M13a.

## TDD evidence (R1)

### Before (FAIL — the M13a flat-colored oracle produces the flat hash, not the textured one):

```
FF                                                                       [100%]
================================== FAILURES ===================================
___________________ test_square_textured_floor_golden_hash ____________________

    def test_square_textured_floor_golden_hash():
        rm = ReferenceModel()
        scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
        frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
>       assert frame_hash(frame) == "00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12"
E       AssertionError: assert 'aeeb82a8bea7...b00a1702d1463' == '00de1aaadf35...5d856eb973a12'
E         
E         - 00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12
E         + aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463

tests\host\test_floor_planes.py:114: AssertionError
____________________ test_e1m1_textured_floor_golden_hash _____________________

    def test_e1m1_textured_floor_golden_hash():
        rm = ReferenceModel()
        map_wad = WadFile.from_path(E1M1)
        scene = build_scene(map_wad, map_wad, "E1M1")
        frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene)
>       assert frame_hash(frame) == "db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2"
E       AssertionError: assert '9569a547c0fe...feae82f576d01' == 'db5d3da80a52...0c267302ef0b2'
E         
E         - db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2
E         + 9569a547c0fef22416fcc3549f0c0bc96bdc1ea3aa8f1eca2b8feae82f576d01

tests\host\test_floor_planes.py:122: AssertionError
=========================== short test summary info ===========================
FAILED tests/host/test_floor_planes.py::test_square_textured_floor_golden_hash
FAILED tests/host/test_floor_planes.py::test_e1m1_textured_floor_golden_hash
2 failed, 8 deselected in 0.42s
```

### After (PASS):

```
.........................                                                [100%]
25 passed in 1.52s
```

## Integration evidence (R2)

Re-blessed textured goldens (the keys the fj textured span raster diffs against at M13d):

- square room spawn: `00de1aaadf358eae11ddbf75fd54e44c04549942cb8a6322ea35d856eb973a12`
- E1M1 spawn: `db5d3da80a52c3ea78a8f599d121aaeb450bdfb84ca96b4656f0c267302ef0b2`

Flat-colored tier preserved byte-exact under `floor_texturing=False` (square `aeeb82a8…`, E1M1
`9569a547…`). Rendered E1M1 spawn frame (perspective-textured floors converging to the horizon, full
DOOM look):

![E1M1 textured floors](https://github.com/tomhea/doom-flipjump/raw/088d6dbd079f74611e4b5ad0eb5d610c58ec3ea5/docs/m13b-e1m1-textured-floors.png)

## R-by-R self-check

| Rule | Status |
| --- | --- |
| R1 tests-first evidence | pass |
| R2 integration evidence | pass (goldens + PNG) |
| R3 coverage of touched logic | pass (distscale value test + textured behavior/golden tests) |
| R4 span/flat guard | n/a (host oracle only; the fj flat table + LUTs land M13c/d) |
| R5 signed-compare + LUT correctness | pass (distscale per-entry + call-twice; modular 32-bit coords mirror the fj) |
| R6 single source of truth | pass (distscale in tables.py shared by oracle + future emitter; cxfrac from CENTERX) |
| R7 branch + PR naming | pass (`m13b-oracle-textured-floors`, `M13b: ...`) |
| R8 zero new warnings | pass (pytest clean) |

## Test plan

- [x] `tests/host/test_floor_planes.py` textured goldens + distscale + textured-vs-flat — FAIL→PASS captured
- [x] `tests/host/test_wall_frame.py` default goldens re-blessed to textured
- [x] M13a flat-colored tier preserved byte-exact under `floor_texturing=False`
- [x] full host suite passes
- [x] two live-oracle fj golden tests remain skipped (re-enabled M13d)
- [ ] CR-ist approves
