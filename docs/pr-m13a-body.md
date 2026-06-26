## Summary

M13a (oracle, the cheaper §1 floor tier): replace the M9 two-band background under the walls with
**distance-lit flat-colored floors/ceilings**. When a one-sided wall claims a column covering screen
rows `[top,bottom]`, the rows ABOVE (`0..top-1`) become that sector's ceiling flat and the rows BELOW
(`bottom+1..H-1`) its floor flat, each shaded by a distance-based COLORMAP row (DOOM's `zlight` /
`R_MapPlane`). M13a uses the flat's base index (no per-pixel `u,v` texture yet — that lands at M13b);
the perspective span raster + the fj mirror are M13b–M13d.

New shared LUT generators (R6, used by the oracle now and the fj emitter at M13c): `yslope_table`
(per-row distance slope, `FixedDiv(centerx, |y-centery|)`) and `zlight_table`
(`(light, distance) → colormap row`, darker with distance). Both mirror DOOM exactly, scaled to our
config (`centerx = VIEW_W//2`).

Per the handoff ("do the host oracle first, mirror in fj at M13c/d"), the oracle is intentionally one
rung ahead of the fj wall renderer for M13a–b. The two heavy E1M1 fj golden tests full-frame-diff the
fj output (still the M9 two-band bg) against the **live** oracle, so they are `skip`ped with a precise,
time-boxed reason and **re-enabled at M13d** when the fj span raster lands. No other fj test diffs the
live oracle (verified by grep), so the rest of the suite is unaffected.

## TDD evidence (R1)

### Before (FAIL — oracle still renders the M9 two-band bg under the walls):

```
..FFFF                                                                   [100%]
================================== FAILURES ===================================
___________ test_square_floor_is_distance_lit_flat_not_two_band_bg ____________

    def test_square_floor_is_distance_lit_flat_not_two_band_bg():
        """Spawn in the square room facing the head-on north wall (covers rows [0,75]). The floor band
        [76,99] used to be the M9 two-band background (a single constant FLOOR_BG shade). It is now the
        sector's floor flat, distance-lit: it (a) differs from the two-band bg, and (b) varies down the
        column (the zlight gradient � nearer rows brighter)."""
        cfg = Config()
        rm = ReferenceModel()
        scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
        state = spawn_state(WadFile.from_path(ROOM), "MAP01")
        frame = rm.render_wall_frame(state, scene)
        bg = rm.render_frame(state, scene)                          # the old M9 two-band background
        W, H = cfg.VIEW_W, cfg.VIEW_H
        col = W // 2
        band = [frame[y * W + col] for y in range(WALL_BOT + 1, H)]
>       assert any(frame[y * W + col] != bg[y * W + col] for y in range(WALL_BOT + 1, H))  # not the two-band bg
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       assert False
E        +  where False = any(<generator object test_square_floor_is_distance_lit_flat_not_two_band_bg.<locals>.<genexpr> at 0x000001DE96FA1F40>)

tests\host\test_floor_planes.py:64: AssertionError
______________ test_e1m1_floors_ceilings_replace_the_background _______________

    def test_e1m1_floors_ceilings_replace_the_background():
        """E1M1 spawn: every column is claimed (no black holes) and the floors/ceilings now overwrite the
        M9 background almost everywhere � far more pixels differ from the two-band bg than the walls alone."""
        cfg = Config()
        rm = ReferenceModel()
        map_wad = WadFile.from_path(E1M1)
        scene = build_scene(map_wad, map_wad, "E1M1")
        state = spawn_state(map_wad, "E1M1")
        frame = rm.render_wall_frame(state, scene)
        bg = rm.render_frame(state, scene)
        W, H = cfg.VIEW_W, cfg.VIEW_H
        assert all(any(frame[y * W + x] != 0 for y in range(H)) for x in range(W))  # no all-zero column
>       assert sum(1 for a, b in zip(frame, bg) if a != b) > 12000  # walls+floors+ceilings, not walls alone
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       assert 5287 > 12000
E        +  where 5287 = sum(<generator object test_e1m1_floors_ceilings_replace_the_background.<locals>.<genexpr> at 0x000001DE96FAF3E0>)

tests\host\test_floor_planes.py:80: AssertionError
________________________ test_square_floor_golden_hash ________________________

    def test_square_floor_golden_hash():
        rm = ReferenceModel()
        scene = build_scene(WadFile.from_path(ROOM), WadFile.from_path(ASSET), "MAP01")
        frame = rm.render_wall_frame(spawn_state(WadFile.from_path(ROOM), "MAP01"), scene)
>       assert frame_hash(frame) == "aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463"
E       AssertionError: assert 'b7da67d5f0d8...1efc1ed7208e8' == 'aeeb82a8bea7...b00a1702d1463'
E         
E         - aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463
E         + b7da67d5f0d8f1ea832038ad571442b986c8a6225fba1a270fb1efc1ed7208e8

tests\host\test_floor_planes.py:89: AssertionError
_________________________ test_e1m1_floor_golden_hash _________________________

    def test_e1m1_floor_golden_hash():
        rm = ReferenceModel()
        map_wad = WadFile.from_path(E1M1)
        scene = build_scene(map_wad, map_wad, "E1M1")
        frame = rm.render_wall_frame(spawn_state(map_wad, "E1M1"), scene)
>       assert frame_hash(frame) == "9569a547c0fef22416fcc3549f0c0bc96bdc1ea3aa8f1eca2b8feae82f576d01"
E       AssertionError: assert '0b817e4a1260...36e752e566c0e' == '9569a547c0fe...feae82f576d01'
E         
E         - 9569a547c0fef22416fcc3549f0c0bc96bdc1ea3aa8f1eca2b8feae82f576d01
E         + 0b817e4a126026207f40327cb32b68685efd47572f79661ff7136e752e566c0e

tests\host\test_floor_planes.py:97: AssertionError
=========================== short test summary info ===========================
FAILED tests/host/test_floor_planes.py::test_square_floor_is_distance_lit_flat_not_two_band_bg
FAILED tests/host/test_floor_planes.py::test_e1m1_floors_ceilings_replace_the_background
FAILED tests/host/test_floor_planes.py::test_square_floor_golden_hash - Asser...
FAILED tests/host/test_floor_planes.py::test_e1m1_floor_golden_hash - Asserti...
4 failed, 2 passed in 0.47s
```

### After (PASS):

```
.............                                                            [100%]
13 passed in 0.91s
```

## Integration evidence (R2)

Re-blessed byte-exact goldens (the keys the fj span raster will diff against at M13c/d):

- square room spawn: `aeeb82a8bea795acf51edf4ff9150dab8f4bd15030f8e6008c6b00a1702d1463`
- E1M1 spawn: `9569a547c0fef22416fcc3549f0c0bc96bdc1ea3aa8f1eca2b8feae82f576d01`

E1M1 spawn frame: every one of the 160 columns is claimed (no black holes); floors/ceilings now
overwrite the two-band bg almost everywhere (`>12000` of 16000 pixels differ from the M9 bg, vs walls
alone before). The square room floor band `[76,99]` is a distance gradient (e.g. `110…109` down the
column), no longer a constant `FLOOR_BG` shade.

## R-by-R self-check

| Rule | Status |
| --- | --- |
| R1 tests-first evidence | pass |
| R2 integration evidence | pass (goldens + coverage) |
| R3 coverage of touched logic | pass (tests/host/test_floor_planes.py: yslope/zlight + behavior) |
| R4 span/flat guard | n/a (host oracle only; no new fj segment — fj LUTs land M13c) |
| R5 signed-compare + LUT correctness | pass (zlight/yslope per-entry + call-twice tests) |
| R6 single source of truth | pass (yslope/zlight in tables.py, shared by oracle + future emitter; centerx from config) |
| R7 branch + PR naming | pass (`m13a-oracle-flat-floors`, `M13a: ...`) |
| R8 zero new warnings | pass (pytest clean) |

## Test plan

- [x] `tests/host/test_floor_planes.py` (new) — FAIL→PASS captured
- [x] `tests/host/test_wall_frame.py` goldens re-blessed; head-on band test updated
- [x] full host suite passes
- [x] two live-oracle fj golden tests skipped with time-boxed reason (re-enabled M13d)
- [ ] CR-ist approves
