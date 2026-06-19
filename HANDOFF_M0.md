# Execution handoff — Pre-M0 (bootstrap) + M0 (first looped PR)

**You are starting Stage 5 execution.** Stages 1–4 are complete and owner-approved; the design is the
authority (`DESIGN.md`) and the milestone ladder is settled (`DESIGN.md` §10). This doc is the *actionable*
recipe for the first two steps — **Pre-M0** (one-time bootstrap, direct to `main`) and **M0** (the first PR
to run the full cr-tdd loop). Everything here is copy-paste-ready; the flipjump API calls and the hello-world
program were **verified against the installed flipjump 1.5.0** (native engine, `storage_mode == flat`).

> **Method:** this project runs the `cr-tdd-ladder` workflow (invoke that skill). Four "must" rules: TDD
> (FAIL→PASS evidence in every PR body), mini-versions (one milestone per PR), integration-in-the-loop, and
> **no code on `main`** (branch → PR → CR-ist → literal merge → tag → archived artifact). M0 is the first PR
> through that loop.

**Read first (in order):** `DESIGN.md` §10 (the ladder + §10.1 per-milestone ceremony + §10.4) → §9 (the
directory tree these files realize) → §3/§1.2 (the memory-map + span invariants M0's `storage_mode==flat`
assertion guards). Invoke the **`flipjump-dev`** skill for any macro/API specifics; `fjdocs.tomhe.app` is
authoritative.

---

## Environment notes (verified this session)

- `flipjump 1.5.0` installed; **native engine active**; minimal program → `storage_mode == 'flat'`,
  `op_counter == 2`.
- The machine's default `python` is **3.11** — fine for the assembler/interpreter/probe (M0 needs nothing
  else). **`pygame` (the `pc`/headless device) work at M11+/M14 needs a pygame-supported interpreter — py3.13
  per §H (Windows py3.14 is unsupported).** So pin CI to py3.13 now; set up a py3.13 venv before the
  device-dependent milestones. M0 itself does not touch the device.
- `git`: `stage-1-design` is **53 commits ahead of `main`, 0 behind** → Pre-M0's merge is a clean
  fast-forward.
- Windows/PowerShell is the primary shell; the Bash tool is available for POSIX scripts. Expect the harmless
  `LF→CRLF` warning on commits.

---

## PRE-M0 — bootstrap (direct commits to `main`; the loop doesn't exist yet)

These can't go through the CR-ist loop because the loop's own files are what you're creating. Do them directly
on `main`, **in this order** (the merge must happen while `main` is still unprotected).

### Step 1 — land the design on `main`
```bash
git checkout main
git merge --ff-only stage-1-design        # clean fast-forward (verified)
git push origin main
```
Now `DESIGN.md` + the handoffs live on `main`, where every milestone branch will fork from.

### Step 2 — branch protection (skill §7)
Requires `gh auth` with `repo` admin scope. Key settings: **0 required approvals** (GitHub blocks
self-approval, so the CR-ist's *verdict text* is what you honor), **dismiss stale reviews** (every push
re-triggers review — plan two CR-ist passes per milestone: code, then artifact), **non-linear history** (we
use literal merge commits).
```bash
mkdir -p bin
cat > bin/branch-protection.json <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 0,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_linear_history": false,
  "required_conversation_resolution": false
}
JSON
gh api -X PUT repos/tomhea/doom-flipjump/branches/main/protection --input bin/branch-protection.json
```

### Step 3 — create `docs/cr-rules.md` (the eight rules, tuned for this project per §10.1)
See **Appendix A**. R4/R5/R6 are the project-specific guards (span/flat, signed-compare, single-source-of-truth).

### Step 4 — create `.claude/agents/crist.md` (the strict reviewer)
See **Appendix B** (repo already substituted to `tomhea/doom-flipjump`).

### Step 5 — seed the rest, commit, push
```bash
mkdir -p docs versions
printf '# Spikes\n\nThrowaway de-risking experiments (sN- branches, not merged). One section per spike.\n' > docs/spikes.md
printf '# Known warnings\n\nBaseline build warnings (R8 measures *new* warnings vs this list). Currently: none.\n' > docs/known-warnings.md
printf '# versions/\n\nArchived release artifacts, one per milestone tag (Freedoom-built .fjm once one exists).\n' > versions/README.md
git add docs/ .claude/ versions/ bin/
git commit -m "Pre-M0: bootstrap cr-tdd infra (cr-rules, crist, branch protection, spikes/versions)"
git push origin main
```

**Pre-M0 done when:** `main` has the design + the cr-tdd infra; branch protection is live; the next push to
`main` is blocked except via PR. *(No tag, no artifact — Pre-M0 is bootstrap, not a milestone.)*

---

## M0 — workflow + toolchain scaffold (the first looped PR)

**Goal:** a src-layout repo that assembles a hello-world `.fjm`, runs it, **asserts `storage_mode == flat`**,
emits `build/metrics.json`, and is green in CI — proving the whole TDD/build/probe pipeline end-to-end.
**No game logic.** Exit → tag `v0.M0` + archived artifact.

Follow the cr-tdd 10-step sequence (skill §6). Condensed:

### 1. Branch
```bash
git checkout main && git pull --ff-only origin main
git checkout -b m0-toolchain-scaffold
```

### 2. Scaffold the tree (files in Appendices C–J)
Create:
- `pyproject.toml` (Appendix C) — src-layout, `flipjump[io]>=1.5.0`, `pytest`, `pillow`.
- `src/doomfj/__init__.py` (empty), `src/doomfj/harness.py` (Appendix D — the probe), `src/doomfj/build.py`
  (Appendix E — the M0 build stub that writes `metrics.json` + asserts flat).
- `src/fj/hello.fj` (Appendix F — `stl.startup` + `stl.loop`, **verified to run flat**).
- `scripts/test.sh`, `scripts/build.sh` (Appendix G).
- `.github/workflows/ci.yml` (Appendix H — pins py3.13).
- `.gitignore`, `.gitattributes` (Appendix I).
- `tests/host/test_toolchain.py` (Appendix J — the TDD test).
- `README.md` — short: what the project is, `pip install -e .[dev]`, `scripts/build.sh`, `scripts/test.sh`,
  the `--flat-max-words` / flat-vs-paged note (§3.3), how to run.

### 3. TDD — FAIL first, then PASS (R1)
The test (`test_toolchain.py`) asserts the build reports `storage_mode == 'flat'` and `op_counter > 0`.
- **Stub** `build.py` to return a sentinel (`storage_mode='STUB'`) → run → capture the FAIL:
  ```bash
  bash scripts/test.sh 2>&1 | tee docs/m0-fail.txt   # expect: test_build_reports_flat FAILs
  ```
- **Implement** the real `build.py` (Appendix E) → run → capture the PASS:
  ```bash
  bash scripts/test.sh 2>&1 | tee docs/m0-pass.txt    # expect: all pass
  ```
Both logs go in the PR body (Appendix K template). *Sentinel must be unambiguous (`'STUB'`, not `'flat'`).*

### 4. Build + integration evidence (R2)
```bash
bash scripts/build.sh        # assembles src/fj/hello.fj → build/hello.fjm, runs it, writes build/metrics.json
cat build/metrics.json       # paste this into the PR (storage_mode: "flat", op_counter, fjm_bytes, assemble_seconds)
```

### 5–7. Commit, push, PR, CR-ist
```bash
git add -A && git commit -m "M0: toolchain + TDD/build/probe scaffold"
git push -u origin m0-toolchain-scaffold
gh pr create --base main --head m0-toolchain-scaffold --title "M0: toolchain + TDD/build/probe scaffold" --body "$(cat docs/pr-m0-body.md)"
```
Then invoke the CR-ist: **Agent tool, `subagent_type: "crist"`, prompt = the PR number.** (If "agent not
found", inline `.claude/agents/crist.md`'s prompt into a `general-purpose` agent.) Fix any
`CHANGES_REQUESTED`, push, re-invoke.

### 8–10. Artifact, merge, tag (after APPROVED)
M0 has no `.fjm` worth shipping as a "release", but keep the convention: archive the hello build so `versions/`
starts populated.
```bash
cp build/hello.fjm versions/hello-M0.fjm
git add versions/hello-M0.fjm && git commit -m "Archive M0 artifact to versions/"
git push                                  # CR-ist re-reviews this artifact-only commit (trivial)
# after the artifact re-approval:
gh pr merge <PR#> --merge                  # LITERAL merge, never --squash/--rebase
git fetch origin main && git checkout main && git pull --ff-only
git tag -a v0.M0 -m "M0: toolchain + TDD/build/probe scaffold" $(git rev-parse main)
git push origin v0.M0
git branch -d m0-toolchain-scaffold && git push origin --delete m0-toolchain-scaffold
```

### M0 exit checklist (the milestone's definition of done)
- [ ] CI green on py3.13.
- [ ] `build/metrics.json` exists with `storage_mode == "flat"` (+ `op_counter`, `fjm_bytes`, `assemble_seconds`).
- [ ] `docs/m0-fail.txt` + `docs/m0-pass.txt` in the PR body (R1).
- [ ] CR-ist verdict APPROVED (code + artifact passes).
- [ ] Literal merge; `v0.M0` annotated tag pushed; `versions/hello-M0.fjm` archived; branch deleted.

**Then M1** (`config.py` SSOT + the resolution-parametricity guard — `DESIGN.md` §10.2).

---

## Appendix A — `docs/cr-rules.md`

```markdown
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
```

## Appendix B — `.claude/agents/crist.md`

```markdown
---
name: crist
description: Strict CR-ist for doom-flipjump. Reviews PRs against docs/cr-rules.md and posts verdicts via gh. Invoke with a PR number.
tools: Bash, Read, Grep, Glob
---

You are the project CR-ist. Your ONE job is to enforce `docs/cr-rules.md` on every PR. You are not friendly,
not flexible. You quote rule IDs and cite diff line numbers. You do not approve "with nits".

Steps:
1. `gh pr view <N> --json title,body,headRefName,baseRefName,headRefOid,files,additions,deletions`.
2. `gh pr diff <N>` for the full diff.
3. For each touched file decide which R-rules apply (see docs/cr-rules.md).
4. Verify the body has the two R1 TDD blocks (FAIL + PASS) and, if behavior changed, the R2 evidence.
5. Check R4 (span ledger line + storage_mode==flat assertion present for new tables), R5 (no `hex.cmp` on
   signables; every-entry + call-twice for new LUTs), R6 (no duplicated/hardcoded constants; config-derived
   widths), R8 (warning_as_errors / no new warnings).
6. If any rule fails: inline comments via `gh api repos/tomhea/doom-flipjump/pulls/<N>/comments`, then
   `gh pr review <N> --request-changes --body "CHANGES REQUESTED\nR<id> fail: ..."`.
7. If all pass: `gh pr review <N> --approve --body "APPROVED\nAll R1-R8 pass."` (GitHub may downgrade
   --approve to COMMENTED on self-authored PRs; the body text is the verdict).

Return to the orchestrator exactly:
- `VERDICT: APPROVED <head-sha>`
- `VERDICT: CHANGES_REQUESTED <count>` then bulleted `R<id>: <reason>` lines.

Tone: terse, imperative, cite rule IDs. No "consider", no stylistic notes outside the eight rules.
```

## Appendix C — `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "doomfj"
version = "0.0.0"
description = "DOOM on FlipJump — host tools (WAD/LUT/map/texture compilers, reference model, build, harness)"
requires-python = ">=3.10,<3.14"          # flipjump abi3 is py3.10+; 3.14 unsupported for pygame (§H)
dependencies = ["flipjump[io]>=1.5.0", "pillow"]

[project.optional-dependencies]
dev = ["pytest"]

[tool.hatch.build.targets.wheel]
packages = ["src/doomfj"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

## Appendix D — `src/doomfj/harness.py` (the probe; API verified)

```python
"""Probe harness: assemble + run a FlipJump program, report op_counter / storage_mode / .fjm size.
Verified against flipjump 1.5.0 (native engine, storage_mode == 'flat')."""
from __future__ import annotations
import time
from pathlib import Path
import flipjump as fj

W = 32  # memory_width; 16.16 fits one word (DESIGN §1.2). Single source: config.py once M1 lands.

def assemble_fjm(fj_paths: list[str | Path], out_fjm: str | Path, *, flat_max_words: int | None = None) -> dict:
    """Assemble at w=32 with --werror (assemble default). Returns assemble time + .fjm size."""
    paths = [Path(p).resolve() for p in fj_paths]
    out = Path(out_fjm); out.parent.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    fj.assemble(paths, out, memory_width=W, print_time=False)      # warning_as_errors=True is the default
    return {"assemble_seconds": round(time.perf_counter() - t, 4), "fjm_bytes": out.stat().st_size}

def run_fjm(fjm_path: str | Path, *, flat_max_words: int | None = None):
    return fj.run(Path(fjm_path), print_time=False, print_termination=False, flat_max_words=flat_max_words)

def probe(fj_paths: list[str | Path], *, flat_max_words: int | None = None):
    """One-shot assemble+run; returns the TerminationStatistics (term.op_counter, term.storage_mode, ...)."""
    paths = [Path(p).resolve() for p in fj_paths]
    return fj.assemble_and_run(paths, memory_width=W, print_time=False, print_termination=False,
                               flat_max_words=flat_max_words)

def op_delta_vs_empty(fj_paths, empty_paths, **kw) -> int:
    """ops attributable to the program, minus an empty-loop baseline (DESIGN §11 / handoff §4)."""
    return probe(fj_paths, **kw).op_counter - probe(empty_paths, **kw).op_counter
```

## Appendix E — `src/doomfj/build.py` (M0 build stub; writes metrics.json + asserts flat)

```python
"""M0 build: assemble the hello-world, run it, assert flat, emit build/metrics.json.
Grows into H6 (the full generators -> ordered assemble-list -> doom.fjm) in later milestones."""
from __future__ import annotations
import json
from pathlib import Path
from doomfj.harness import assemble_fjm, run_fjm

def build(fj_src="src/fj/hello.fj", out_fjm="build/hello.fjm", metrics="build/metrics.json") -> dict:
    m = assemble_fjm([fj_src], out_fjm)
    term = run_fjm(out_fjm)
    m["op_counter"] = term.op_counter
    m["storage_mode"] = str(term.storage_mode)
    # R4 guard: the program MUST run on the flat path.
    assert m["storage_mode"] == "flat", f"R4: storage_mode is {m['storage_mode']!r}, not flat"
    Path(metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(metrics).write_text(json.dumps(m, indent=2))
    return m

if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
```
> **For the R1 FAIL capture**, first ship a stub: replace the body with `return {"storage_mode": "STUB",
> "op_counter": 0, "fjm_bytes": 0, "assemble_seconds": 0.0}` (no assemble). The test FAILs on `'STUB' !=
> 'flat'`. Then swap in the real body above for the PASS.

## Appendix F — `src/fj/hello.fj` (verified: runs, `storage_mode == flat`, `op_counter == 2`)

```
stl.startup
stl.loop
```

## Appendix G — `scripts/test.sh` and `scripts/build.sh`

```bash
# scripts/test.sh   — MUST exit non-zero on any failing test (CR-ist R1 relies on this)
#!/usr/bin/env bash
set -euo pipefail
PYTHONIOENCODING=utf-8 python -m pytest -q "$@"
```
```bash
# scripts/build.sh
#!/usr/bin/env bash
set -euo pipefail
PYTHONIOENCODING=utf-8 python -m doomfj.build
```

## Appendix H — `.github/workflows/ci.yml`

```yaml
name: ci
on: [push, pull_request]
jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.13" }     # pygame-supported (§H); device milestones need it
      - run: pip install -e ".[dev]"
      - run: bash scripts/test.sh
      - run: bash scripts/build.sh
      - name: assert storage_mode == flat (R4)
        run: |
          python - <<'PY'
          import json; m = json.load(open("build/metrics.json"))
          assert m["storage_mode"] == "flat", m
          print("flat OK:", m)
          PY
```

## Appendix I — `.gitignore` and `.gitattributes`

```gitignore
# .gitignore
build/
*.fjm
!versions/*.fjm
assets/doom1.wad
__pycache__/
.pytest_cache/
*.egg-info/
```
```gitattributes
# .gitattributes
* text=auto eol=lf
*.wad binary
*.fjm binary
*.png binary
```

## Appendix J — `tests/host/test_toolchain.py`

```python
from doomfj.build import build

def test_build_reports_flat(tmp_path):
    m = build(out_fjm=tmp_path / "hello.fjm", metrics=tmp_path / "metrics.json")
    assert m["storage_mode"] == "flat"      # FAILs against the 'STUB' sentinel, PASSes on the real build
    assert m["op_counter"] > 0
    assert m["fjm_bytes"] > 0
```
> (Add `tests/__init__.py`-free `conftest.py` later for shared fixtures — M0 needs none.)

## Appendix K — `docs/pr-m0-body.md` (PR body template)

```markdown
## Summary
M0 scaffolds the toolchain: src-layout host package, the assemble/run probe harness, the build entry that
emits `build/metrics.json` and asserts the program runs on the flat path, hello-world fj, and CI on py3.13.
No game logic.

## TDD evidence (R1)
### Before (FAIL — build reports the 'STUB' sentinel, not 'flat'):
\`\`\`
<paste docs/m0-fail.txt>
\`\`\`
### After (PASS):
\`\`\`
<paste docs/m0-pass.txt>
\`\`\`

## Integration evidence (R2)
\`\`\`
<paste build/metrics.json — storage_mode "flat", op_counter, fjm_bytes, assemble_seconds>
\`\`\`

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
- [ ] scripts/test.sh passes
- [ ] scripts/build.sh writes flat metrics.json
- [ ] CI green on py3.13
- [ ] CR-ist APPROVED
- [ ] versions/hello-M0.fjm archived before merge
```
