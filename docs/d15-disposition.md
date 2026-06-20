# D15 disposition — PR #1 keep-vs-rewrite (the single holistic judgment)

D15's *policy* is in `DESIGN.md` §9 ("the design is authority, not PR #1") with a per-path disposition
table. This file records the *executed* CR judgment. Per §10.4 gap #9, the keep-vs-rewrite call is **one
holistic judgment** even though execution spans M2 / M4 / M5; it is recorded here at M2.

## Verdict: KEEP the fixed-point macros (executed at M2)

`stl/hex/fixed_point.fj` (PR #1) → **`src/fj/fixed_point.fj`** (F2), kept verbatim (+ a provenance header).

**Why keep, not rewrite:**
- **Byte-exact on the installed flipjump 1.5.0.** `fixed_mul`, `fixed_div`, `mul_const` were assembled at
  `w=32` and run against the host mirror (`src/doomfj/fixedpoint.py`) on boundary / signed / overflow /
  trunc-toward-zero / aliasing inputs — all match (see `docs/m2-integration.txt`, `tests/fj/test_fixed_point.py`).
- **Matches the F2/D13 design intent.** Signed Q-format 16.16 (`n=8,f=4`) and 8.8 (`n=4,f=2`); `mul_const`
  is the strength-reduced compile-time-constant multiply; `read_table`/`read_table_byte` are the §3.4
  data-table fallback (D13) with documented entry-layout contracts.
- **Clean against the project guards.** No `hex.cmp` on a signable anywhere (R5): the signed paths use
  `sign_extend` + full-width `mul`/`idiv`, the correct approach. Macros are documented with `// Complexity`,
  `@requires`, `@Assumes`, and aliasing notes; assemble is `--werror`-clean (R8).

## Host mirror (new at M2)

`src/doomfj/fixedpoint.py` is a NEW Python mirror of the truncation/wrap semantics so host math == fj math
bit-for-bit (D12/R6). Anchored to hand-computed Q-format values in `tests/host/test_fixedpoint.py`; the
fj<->host parity lives in `tests/fj/test_fixed_point.py`.

## Remaining PR #1 content (later milestones — same KEEP-leaning judgment, re-confirmed per file)

| PR #1 path | Designed home | Milestone | Status |
|---|---|---|---|
| `stl/hex/fixed_point.fj` | `src/fj/fixed_point.fj` (F2) | **M2** | **KEPT** (this doc) |
| `lut_generator.py` value kernel (`encode_fixed_point`, sine/recip math) | `src/doomfj/tables.py` + `fixedpoint.py` | M4 | pending CR |
| `lut_generator.py` data-table emitters | `src/doomfj/lut_generator.py` (§3.4 fallback) | M5 | pending CR; primary dispatch-code emitter written NEW |
| `tests/unit/test_lut_generator.py` | `tests/host/test_lut_generator.py` | M4/M5 | pending |

**PR #1 (`move-flipjump-lut-and-fixedpoint`, OPEN) stays open** until M5 absorbs `lut_generator.py`; then it
is closed as superseded (its content re-homed under the design's layout, never merged as-is — §9).
