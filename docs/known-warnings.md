# Known warnings

Baseline warnings (R8 measures *new* warnings against this list).

## `python -m pytest tests/host -q` — 3 warnings

```
tests/host/test_emitter_call_sites.py::test_every_tracked_caller_passes_keywords_the_emitter_has
tests/host/test_no_decimal_wire.py::test_every_screen_is_fed_the_binary_wire
tests/host/test_oracle_calls_in_step.py::test_every_gate_asks_the_oracle_for_what_it_emits
  <unknown>:1: DeprecationWarning: invalid escape sequence '\_'
```

**Recorded 2026-09-06 (CR-2026-09-06, PR #83).** This file previously read "Currently: none",
which was false — the three have been present for some time and nobody had reconciled the doc.

**Where they come from.** All three tests walk the repo and `compile()`/`ast.parse()` OTHER files'
source; `<unknown>:1` is the giveaway that the warning is raised while compiling a string, not
while importing the test. So the invalid escape lives in a *scanned* file, not in any of the three
tests, and the count is 3 because three tests scan.

**Why they are recorded rather than fixed here.** PR #83 changed no `src/`, `tests/` or `scripts/`
file, and these three appeared identically before its first commit. Fixing them means finding the
scanned source with a non-raw `'\_'` and making it a raw string — a real but separate change, and
one that should come with the grep that proves the file is the only one.

⚠ If a run reports anything other than exactly these 3, R8 has something to say about your change.
