## Summary
M4 (S5.0b) lifts PR #1's LUT **value kernel** (D15 keep, per docs/d15-disposition.md) into the shared host
source of truth. `src/doomfj/tables.py` (NEW) holds the pure LUT *value* functions `sine_table` and
`reciprocal_table` (the raw encoded entry values), and `encode_fixed_point` moves into
`src/doomfj/fixedpoint.py` (the real->raw two's-complement encoder). These are the single source the emitter
(H2/H4, M5/M8) and the oracle (H5, M9) both consume, so host and fj math cannot drift (D12/R6). The fj-text
emitters stay in PR #1 for M5 (§3.4 fallback) — M4 is values only.

## TDD evidence (R1)
### Before (FAIL — tests written first against stub value fns):
```
FAILED tests/host/test_tables.py::test_sine_anchors_16_16            - assert 0 == 4096
FAILED tests/host/test_tables.py::test_sine_matches_math_sin         - IndexError (empty)
FAILED tests/host/test_tables.py::test_reciprocal_values_16_16       - assert 0 == 256
FAILED tests/host/test_tables.py::test_reciprocal_clamps_when_over_max
FAILED tests/host/test_fixedpoint.py::test_encode_positive           - assert -1 == 65536
FAILED tests/host/test_fixedpoint.py::test_encode_negative_is_twos_complement
FAILED tests/host/test_fixedpoint.py::test_encode_8_8                - assert -1 == 640
FAILED tests/host/test_fixedpoint.py::test_encode_rounds_to_nearest
FAILED tests/host/test_fixedpoint.py::test_encode_out_of_range_raises - DID NOT RAISE
```

### After (PASS):
```
.....................................................                    [100%]
53 passed in 10.62s
```

## Integration evidence (R2)
The value kernel matches DOOM finesine samples (identical to PR #1's hand-inlined table), the reciprocal is
correct, and the host `sine_table` round-trips through the fj `hex.read_table` path bit-for-bit (so the
emitter and oracle genuinely share one source):
```
=== sine_table(8, 16, 32) vs PR#1's hand-inlined finesine sample ===
  sin[0]=0x00000000  sin[1]=0x0000b505  sin[2]=0x00010000  sin[3]=0x0000b505
  sin[4]=0x00000000  sin[5]=0xffff4afb  sin[6]=0xffff0000  sin[7]=0xffff4afb   (all OK)
=== reciprocal_table(8, 16, 32) ===
  1/1=0x00010000  1/2=0x00008000  1/3=0x00005555  1/4=0x00004000  recip[0]=0xffffffff (clamp)
=== host sine_table == fj hex.read_table ===
  fj read-back == host sine_table: True
```

## R-by-R self-check
| Rule | Status |
| --- | --- |
| R1 tests-first (FAIL->PASS above) | pass |
| R2 integration (DOOM samples + host==fj read_table round-trip) | pass |
| R3 coverage (test_tables for tables.py; test_fixedpoint for encode_fixed_point) | pass |
| R4 storage_mode==flat | n/a (host-only) |
| R5 signed-compare / tables | n/a (value fns are pure host math; no fj compares; the fj read path is M2's, retested in R2) |
| R6 single source of truth (tables.py is THE value source for emitter+oracle; verified by the read_table round-trip) | pass |
| R7 naming (branch m4-tables, title "M4: ...") | pass |
| R8 zero new warnings (pytest clean) | pass |

## Test plan
- [x] scripts/test.sh passes (53 tests; 9 new for M4)
- [x] value fns match hand-computed + DOOM finesine samples
- [x] host sine_table == fj read_table read-back (shared source proven)
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/ artifact archived before merge
