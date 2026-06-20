## Summary
M0 scaffolds the toolchain: src-layout host package, the assemble/run probe harness, the build entry that
emits `build/metrics.json` and asserts the program runs on the flat path, hello-world fj, and CI on py3.13.
No game logic.

## TDD evidence (R1)
### Before (FAIL — build reports the 'STUB' sentinel, not 'flat'):
```
F                                                                        [100%]
================================== FAILURES ===================================
___________________________ test_build_reports_flat ___________________________

tmp_path = WindowsPath('C:/Users/tomhe/AppData/Local/Temp/pytest-of-tomhe/pytest-568/test_build_reports_flat0')

    def test_build_reports_flat(tmp_path):
        m = build(out_fjm=tmp_path / "hello.fjm", metrics=tmp_path / "metrics.json")
>       assert m["storage_mode"] == "flat"      # FAILs against the 'STUB' sentinel, PASSes on the real build
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AssertionError: assert 'STUB' == 'flat'
E
E         - flat
E         + STUB

tests\host\test_toolchain.py:5: AssertionError
=========================== short test summary info ===========================
FAILED tests/host/test_toolchain.py::test_build_reports_flat - AssertionError...
1 failed in 0.29s
```

### After (PASS):
```
.                                                                        [100%]
1 passed in 0.28s
```

## Integration evidence (R2)
```
{
  "assemble_seconds": 0.1556,
  "fjm_bytes": 88,
  "op_counter": 2,
  "storage_mode": "flat"
}
```

## R-by-R self-check
| Rule | Status |
| --- | --- |
| R1 tests-first | pass |
| R2 integration (metrics.json) | pass |
| R3 coverage (test_toolchain) | pass |
| R4 storage_mode==flat asserted | pass |
| R5 signed-compare / tables | n/a (no fj logic/LUTs yet) |
| R6 single source of truth | pass (no duplicated consts) |
| R7 naming | pass |
| R8 zero new warnings (--werror default) | pass |

## Test plan
- [x] scripts/test.sh passes
- [x] scripts/build.sh writes flat metrics.json
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/hello-M0.fjm archived before merge
