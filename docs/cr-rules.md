# CR rules

Eight hard requirements for every PR into `main`. Each has an ID so review comments quote it (`R4 fail: ...`).

## R1 — Tests first, evidence in PR body
The PR body MUST contain two fenced blocks: (1) `scripts/test.sh` output showing the new test(s) FAILing
(run before the change), (2) the same showing them PASSing (after). No FAIL log ⇒ no proof the test catches
a regression. (fj-macro tests use `flipjump.assemble_and_run_test_output`; host tests use `pytest`.)

## R2 — Integration evidence for behavior changes
Any change to observable behavior MUST paste the relevant artifact: a `build/metrics.json` excerpt
(ops/frame, assemble time, `.fjm` size, `storage_mode`), a golden-frame hash/PNG, or a measured fps line.

## R3 — Test coverage on touched logic
Every new/modified file under `src/doomfj/` (host logic) or `src/fj/` (macros) MUST get at least one new
test (`tests/host/` or `tests/fj/`). Pure glue/present code is exempt (R2 covers it).

## R4 — Span / flat guard (resource guard)
Any new table/segment adds its line (size + alignment pad) to the `DESIGN.md` §1.2 span ledger, and the
build asserts `storage_mode == flat` AND total span < the flat limit (R-3). No silent paged-mode fallback.

## R5 — Signed-compare + table-correctness guard
Every compare on a signable quantity uses `hex.scmp` (magnitude) or `hex.sign` (sign-only) — NEVER `hex.cmp`
(§3.5; the catalog's #1 latent-bug class). Every generated LUT is tested on EVERY entry AND with a
call-twice-per-entry check (#8 — catches result-reg / in-table-jumper-cleanup bugs).

## R6 — Single source of truth
Constants come only from `config.py` / `fj_consts.fj`; LUT values only from `tables.py` / `fixedpoint.py`
(shared by the emitter AND the reference model). No duplicated constants; nothing hardcodes 160/100 or a
width that assumes W/H ≤ 256 (the §1 resolution 2-const invariant). Host math must mirror fj math bit-for-bit.

## R7 — Branch & PR naming
Branch `mN-feature-slug` (milestone) / `sN-topic` (spike) / `fix/slug` (hotfix). PR title `M<N>: <feature>`
/ `Spike: <topic>` / `Fix: <short>`. Body has `## TDD evidence (R1)` and (if behavior changed)
`## Integration evidence (R2)`.

## R8 — Zero new warnings
Assembly runs with `warning_as_errors=True` (the `flipjump.assemble` default = `--werror`) and introduces no
new warning vs `docs/known-warnings.md`. `pytest` runs clean.

## Verdict format
Approve: review body `APPROVED\nAll R1-R8 pass.` Request changes: `CHANGES REQUESTED\nR<id> fail: <reason>`.
Inline comments quote offending lines with `R<id>:`.
