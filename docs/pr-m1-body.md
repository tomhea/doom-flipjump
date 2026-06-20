## Summary
M1 (F1) establishes the host single-source-of-truth. `src/doomfj/config.py` holds the two resolution
constants (`W/H`) plus every resolution-derived size **and bit-width** — `COL_BITS=ceil(log2 W)`,
`ROW_BITS`, `FB_SIZE`, `PALETTE_SIZE`, `VIEW_W/H`, `NCOLORS` — and emits `build/generated/fj_consts.fj`.
`src/fj/memory_map.fj` consumes those generated constants (no hardcoded resolution literal) and lays out
the §3 hot-low skeleton (`;main` jumps over the framebuffer/palette LOW region). A **resolution-parametricity
guard** regenerates at a second resolution (320x200) and asserts every derived value tracks — the §1
2-const invariant — both host-side (`test_config`) and fj-side (`memory_map` recompiles flat at 320x200).
`test_build` is the span/alignment-invariant home M10 (R0) will fill with real per-table numbers.

Also fixes a latent M0 bug surfaced the first time `harness.probe` was exercised: it passed `flat_max_words`
to `fj.assemble_and_run`, which doesn't accept it (it's a *run* param). `probe` now assembles to a temp
`.fjm` then runs, honoring `flat_max_words`.

## TDD evidence (R1)
### Before (FAIL — tests written first; config is a sentinel stub, and the probe call exposes the harness bug):
```
FFFFFF...                                                                [100%]
E       assert 1 == 256          # test_derived_constants_160x100: NCOLORS stub
E       assert -1 == 9           # test_resolution_parametricity_320x200: COL_BITS stub
E       assert -1 == 8           # test_col_bits_is_ceil_log2_w: COL_BITS stub
E       assert 1 == (160 * 100)  # test_span_skeleton_under_flat_limit: FB_SIZE stub
E       TypeError: assemble_and_run() got an unexpected keyword argument 'flat_max_words'   # harness bug
=========================== short test summary info ===========================
FAILED tests/host/test_build.py::test_memory_map_assembles_flat
FAILED tests/host/test_build.py::test_memory_map_assembles_flat_at_second_resolution
FAILED tests/host/test_build.py::test_span_skeleton_under_flat_limit
FAILED tests/host/test_config.py::test_derived_constants_160x100
FAILED tests/host/test_config.py::test_resolution_parametricity_320x200
FAILED tests/host/test_config.py::test_col_bits_is_ceil_log2_w
6 failed, 3 passed in 0.92s
```

### After (PASS — real config derivations + harness fix):
```
.........                                                                [100%]
9 passed in 1.44s
```

## Integration evidence (R2)
`memory_map.fj` assembles + runs **flat** at both resolutions; the derived widths/sizes track W/H
(COL_BITS 8->9, FB_SIZE 16000->64000) — the §1 2-const switch, end to end:
```
=== 160x100 ===
  COL_BITS=8 ROW_BITS=7 FB_SIZE=16000 PALETTE_SIZE=768 total_span=16768
  memory_map run -> storage_mode=flat  op_counter=3
=== 320x200 ===
  COL_BITS=9 ROW_BITS=8 FB_SIZE=64000 PALETTE_SIZE=768 total_span=64768
  memory_map run -> storage_mode=flat  op_counter=3

=== generated build/generated/fj_consts.fj (160x100) ===
W = 160
H = 100
BPP = 8
TRIG_N = 4096
NCOLORS = 256
COL_BITS = 8
ROW_BITS = 7
VIEW_W = 160
VIEW_H = 100
FB_SIZE = 16000
PALETTE_SIZE = 768
```

## R-by-R self-check
| Rule | Status |
| --- | --- |
| R1 tests-first (FAIL->PASS above) | pass |
| R2 integration (memory_map flat @ 2 resolutions) | pass |
| R3 coverage (test_config for config.py; test_build for memory_map.fj + probe) | pass |
| R4 storage_mode==flat asserted; framebuffer/palette already in §1.2 ledger; total_span < flat limit | pass |
| R5 signed-compare / tables | n/a (no fj compares/LUTs yet) |
| R6 single source of truth (config.py -> fj_consts.fj; no hardcoded 160/100; COL_BITS=ceil(log2 W)) | pass |
| R7 naming (branch m1-config-ssot, title "M1: ...") | pass |
| R8 zero new warnings (--werror default; clean assemble + pytest) | pass |

## Test plan
- [x] scripts/test.sh passes (9 tests)
- [x] scripts/build.sh still writes flat metrics.json (M0 smoke, no regression)
- [x] memory_map.fj recompiles flat at a second resolution (parametricity guard)
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/ artifact archived before merge
