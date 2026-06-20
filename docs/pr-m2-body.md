## Summary
M2 (S5.0a / F2 / D15) lands the signed fixed-point math. After an adversarial CR of PR #1, the **D15
verdict is KEEP**: `stl/hex/fixed_point.fj` ports verbatim (+ provenance header) to `src/fj/fixed_point.fj`
because it is byte-exact on flipjump 1.5.0, matches the F2/D13 intent (16.16 + 8.8 + `mul_const` +
`read_table`/`read_table_byte` §3.4 fallback), and is clean against R5 (no `hex.cmp` on signables — it uses
`sign_extend` + full-width `mul`/`idiv`). A NEW host mirror `src/doomfj/fixedpoint.py` reproduces the
truncation/wrap semantics bit-for-bit, so the host emitter/oracle can't drift from fj math (R6/D12). Full
D15 disposition (incl. the M4/M5 LUT-generator paths) recorded in `docs/d15-disposition.md`.

## TDD evidence (R1)
### Before (FAIL — tests written first against a sentinel host mirror; host-unit AND fj<->host parity both fail):
```
FAILED tests/fj/test_fixed_point.py::test_fixed_mul_parity        - fj output != host mirror
FAILED tests/fj/test_fixed_point.py::test_fixed_mul_aliasing      - fj output != host mirror
FAILED tests/fj/test_fixed_point.py::test_fixed_div_parity_and_div0 - fj output != host mirror
FAILED tests/fj/test_fixed_point.py::test_mul_const_parity        - fj output != host mirror
FAILED tests/host/test_fixedpoint.py::test_fixed_mul[98304-131072-8-4-196608]   - assert -1 == 196608
FAILED tests/host/test_fixedpoint.py::test_fixed_div[65536-196608-8-4-21845]    - assert -1 == 21845
FAILED tests/host/test_fixedpoint.py::test_fixed_div_by_zero_returns_none       - assert -1 is None
FAILED tests/host/test_fixedpoint.py::test_mul_const[4660-320-8-1491200]        - assert -1 == 1491200
... (all 23 new M2 tests fail against the stub)
```

### After (PASS — kept fixed_point.fj + real host mirror):
```
.................................                                        [100%]
33 passed in 11.78s
```

## Integration evidence (R2)
Actual fj stdout from the macros vs the host mirror (byte-exact across boundary / signed / overflow /
trunc-toward-zero / aliasing):
```
=== fixed_mul: actual fj stdout vs host mirror (16.16 / 8.8) ===
  1.5*2.0        fj=00030000  host=00030000  OK
  -1.5*2.0       fj=fffd0000  host=fffd0000  OK
  -1.5*-2.0      fj=00030000  host=00030000  OK
  overflow-wrap  fj=00000000  host=00000000  OK
  8.8 2.5*-2.0   fj=fb00      host=fb00      OK
=== fixed_div (incl. trunc-toward-zero, signed) ===
  -1.0/3.0       fj=ffffaaab  host=ffffaaab  OK
  1.0/3.0        fj=00005555  host=00005555  OK
  3.0/-2.0       fj=fffe8000  host=fffe8000  OK
=== mul_const (strength-reduced; 320 = DOOM screen stride) ===
  0x1234*320  fj=0016c100  host=0016c100  OK
  0xffffffff*5    fj=fffffffb  host=fffffffb  OK
```

## R-by-R self-check
| Rule | Status |
| --- | --- |
| R1 tests-first (FAIL->PASS above) | pass |
| R2 integration (fj stdout == host mirror, byte-exact) | pass |
| R3 coverage (test_fixedpoint for host mirror; test_fixed_point for fixed_point.fj) | pass |
| R4 storage_mode==flat | n/a (no new table/segment in the memory map; fixed_point is macros) |
| R5 signed-compare (no hex.cmp on signables; uses sign_extend+mul/idiv) + read_table every-entry+call-twice | pass |
| R6 single source of truth (host mirror == fj math, byte-exact; verified by parity) | pass |
| R7 naming (branch m2-fixed-point, title "M2: ...") | pass |
| R8 zero new warnings (--werror default; clean assemble + pytest) | pass |

## Test plan
- [x] scripts/test.sh passes (33 tests; 23 new for M2)
- [x] fixed_mul/div/mul_const byte-exact vs host mirror (boundary/signed/overflow/aliasing/div0)
- [x] read_table every-entry + call-twice (R5 #8)
- [x] D15 disposition recorded (docs/d15-disposition.md)
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/ artifact archived before merge
