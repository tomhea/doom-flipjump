## Summary
M3 (S5.2 / H1) lands the WAD parser. `src/doomfj/wad.py` reads the IWAD/PWAD container (header + lump
directory + raw lumps) and the typed DOOM map records (VERTEXES / LINEDEFS / SIDEDEFS / SECTORS / THINGS),
with positional map-scoped lookup (marker -> component lumps). A minimal hand-built **test WAD** is committed
as the fast-loop R1 bring-up map (`tests/fixtures/test.wad`, a one-sector square room, MAP01), reproducible
from its builder (`tests/fixtures/make_test_wad.py`). `scripts/fetch_doom1.sh` fetches the shareware IWAD for
dev (gitignored; CI/golden/versions use Freedoom — D8). Texture/colormap/palette accessors are deferred to M8.

## TDD evidence (R1)
### Before (FAIL — tests written first against a stub parser returning empty/STUB):
```
FAILED tests/host/test_wad.py::test_header           - assert 'STUB' == 'PWAD'
FAILED tests/host/test_wad.py::test_lump_names_in_order
FAILED tests/host/test_wad.py::test_vertexes         - assert [] == [Vertex(x=0,...)]
FAILED tests/host/test_wad.py::test_linedefs         - assert 0 == 4
FAILED tests/host/test_wad.py::test_sidedefs         - assert 0 == 4
FAILED tests/host/test_wad.py::test_sectors          - assert 0 == 1
FAILED tests/host/test_wad.py::test_things           - assert [] == [Thing(x=128,...)]
FAILED tests/host/test_wad.py::test_get_raw_lump     - KeyError: 'VERTEXES'
FAILED tests/host/test_wad.py::test_bad_magic_rejected - DID NOT RAISE ValueError
(test_missing_lump_raises and test_fixture_is_reproducible pass — independent of the parser body)
```

### After (PASS — real parser + committed fixture):
```
............................................                             [100%]
44 passed in 17.23s
```

## Integration evidence (R2)
The parser reads the **real shareware doom1.wad** (fetched via `scripts/fetch_doom1.sh`) — E1M1's
canonical record counts and the known player-1 spawn — and the committed test fixture:
```
doom1.wad: type=IWAD  numlumps=1264
E1M1 counts: vertexes=467 linedefs=475 sidedefs=648 sectors=85 things=138
  vertex[0]=Vertex(x=1088, y=-3680)
  linedef[0]=Linedef(v1=0, v2=1, flags=1, special=0, tag=0, front=0, back=-1)
  sector[0]=Sector(floor_h=0, ceil_h=72, floor_tex='FLOOR4_8', ceil_tex='CEIL3_5', light=160, ...)
  player-1 start: Thing(x=1056, y=-3616, angle=90, type=1, flags=7)

test.wad: type=PWAD numlumps=6 names=['MAP01','THINGS','LINEDEFS','SIDEDEFS','VERTEXES','SECTORS']
  MAP01 vertexes=[Vertex(0,0), Vertex(256,0), Vertex(256,256), Vertex(0,256)]
```
(doom1.wad is gitignored/dev-only; the committed test.wad is what CI parses.)

## R-by-R self-check
| Rule | Status |
| --- | --- |
| R1 tests-first (FAIL->PASS above) | pass |
| R2 integration (real doom1.wad E1M1 + test fixture parse) | pass |
| R3 coverage (test_wad covers wad.py; the fixture builder is test infra) | pass |
| R4 storage_mode==flat | n/a (host-only; no fj/memory-map change) |
| R5 signed-compare / tables | n/a (no fj logic/LUTs) |
| R6 single source of truth (record formats live only in wad.py; fixture geometry only in make_test_wad.py) | pass |
| R7 naming (branch m3-wad-parser, title "M3: ...") | pass |
| R8 zero new warnings (pytest clean; no assembly) | pass |

## Test plan
- [x] scripts/test.sh passes (44 tests; 11 new for M3)
- [x] lump counts/sample records vs fixtures (test.wad) + real doom1.wad E1M1
- [x] the small test map parses; fixture reproducible from its builder
- [x] scripts/fetch_doom1.sh works (shareware sha1 5b2e249b...)
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/ artifact archived before merge
