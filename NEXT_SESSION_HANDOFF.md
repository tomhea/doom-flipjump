# Handoff — Stage 5 (execution), starting at M0

**Audience:** a fresh session picking up DOOM-on-FlipJump after **Stages 1–4 are complete and owner-approved.**
Your job starts at **Stage 5 — execution**, first item **M0**. The *design is settled* (`DESIGN.md` §1–§9) and the
*ladder is settled* (`DESIGN.md` §10) — do not reopen either without a real contradiction.

---

## 0. Mission (TL;DR)

1. **Stage 4 — iterative stage cutting: DONE & approved (2026-06-20).** The full ladder is **`DESIGN.md` §10**:
   ~16 milestones **M0–M15** (+ an R3 fan-out), **full cr-tdd-ladder ceremony per milestone**, the **early unroll
   spike Sᵤ before R0**, two measurement gates (**M10/R0**, **M11c/R1**).
2. **Stage 5 — execution.** Start at **M0** (workflow + toolchain scaffold — the repo does **not** yet have the
   cr-tdd infra: `docs/cr-rules.md`, `.claude/agents/crist.md`, branch protection, `versions/`). Then walk the
   M-ladder in order. The **first feature milestone is M2** = the adversarial **PR #1 CR-loop** (D15 policy below).
3. Each milestone ends in an **owner approval gate**; the two measurement gates (M10, M11c) must land their numbers
   in-doc before anything downstream starts.

---

## 1. Where things stand

- **Repo:** `tomhea/doom-flipjump` (this repo). **Branch: `stage-1-design`** — `DESIGN.md` lives here, not yet on
  `main`. First thing: `git branch --show-current`. **Pre-M0 merges it to `main`** (§10.2) before execution
  branches start — the design stages were branch-only by design; Stage 5 needs the docs on `main`.
- **Stage 1 (design doc): complete.** D1–D14 resolved; D15 set as a policy (deciding-detail at S5.0).
- **Stage 2 (contradiction hunt): complete & re-approved (2026-06-20).** A fresh adversarial re-pass over the expanded
  doc fixed 4 contradictions (commits #20–23); the load-bearing per-op costs were **re-derived from the installed
  flipjump 1.5.0 STL source** (not just the doc) and all matched.
- **Stage 3 (directory tree): complete & approved (2026-06-20).** The full tree is **`DESIGN.md` §9**; D14 resolved.
- **The operating contract is `doom_implementation_handoff.md` Part I §4–§9.** Read it first. Part II is inherited
  raw material. Stage-4 rules are §8; Stage-5 kickoff is §9.

---

## 2. Two things that must not get lost

### 2a. D15 — the design is the authority; PR #1 is reference-only
The owner was explicit: **do not inherit anything from PR #1 just because it's written there.** S5.0's CR judges each
PR #1 file *against `DESIGN.md`* and keeps it **only where it independently earns its place**; anything misaligned or
low-quality is **discarded and rewritten to the design**. Saving a bad implementation is a non-goal. The provisional
split (from reading the diff this session, *pending* the CR):
- `stl/hex/fixed_point.fj` → *appears* design-aligned (`fixed_mul`/`fixed_div` = D13 full-2n-width; `mul_const` = opt #4;
  `read_table`/`read_table_byte` = §3.4 fallback) → **keep + adversarial CR** — but verify, don't assume.
- `lut_generator.py` emits **data tables only** → lift its **value kernel** (`encode_fixed_point` + sine/recip math)
  into the shared `src/doomfj/tables.py`/`fixedpoint.py`; keep its data-table emitters as the §3.4 fallback; **write
  the primary dispatch-code emitter new** (S5.1). All provisional — rewrite if the CR says so.

### 2b. The Stage-3 gap-closers (DESIGN.md §9) are load-bearing, not decoration
- **`config.py` (G-b)** is the *single* source of `W/H/bpp/N`, table sizes/bases, device command bytes,
  `--flat-max-words` — it emits `build/generated/fj_consts.fj` that `memory_map.fj` consumes. Host and fj must never
  carry duplicate constants.
- **`tables.py` + `fixedpoint.py` (G-a)** hold the pure value/semantics functions imported by **both** the table
  emitter (H2/H4) **and** the reference model (H5). This is what makes D12 bit-exactness structural instead of a
  hope — H5 cannot drift from what the program actually reads. **Build these early** (they gate the per-table and
  golden tests).
- **`build/metrics.json` (G-c)** is where assemble-time / `.fjm` size / ops-frame / span-ledger land; CI
  threshold-checks it — the R-2 (assembler scale) and R-3 (span vs flat) guards.
- Memory-map invariants get a real test home (`tests/host/test_build.py`): `storage_mode == flat`, span < flat
  limit, alignment/over-align.

---

## 3. The ladder (Stage 4 result — `DESIGN.md` §10)

Stage 4 is **done**; the authoritative ladder is **`DESIGN.md` §10** (M0–M15 + R3 fan-out, exit criteria,
per-milestone cr-tdd ceremony, the R4–R6 CR-rule tuning, the two gates). Do not re-derive it here. The shape:

```
pre  land stage-1-design → main; bootstrap branch protection + cr-rules.md + crist.md (direct)  ← START HERE
M0   workflow + toolchain scaffold (src-layout, probe harness, CI py3.13) — first looped PR
M1   config.py SSOT → fj_consts.fj + F1 memory_map.fj + span-invariant test home
M2   [S5.0a] adversarial PR #1 CR-loop → fixed_point.fj (F2) + fixedpoint.py mirror (D15)
Sᵤ   SPIKE (early, not merged): full-unroll assemble-time/size scaling — de-risk D2/R-2
M3   [R0] H1 WAD parser + fixtures            M7  H3 map compiler (BSP / BSP-as-code)
M4   [S5.0b] tables.py value fns              M8  H4 texture/colormap/palette → MEASURE texture span
M5   [S5.1] H2 dispatch-code emitter (#5/#8)  M9  H5 reference model (oracle)
M6   F3 fj-side LUT access                    M10 R0 GATE: real §1.2/§1.3 ledgers, flat verified
M11a F4 framebuffer + deposit  →  M11b F5 one textured column  →  M11c R1 GATE: decide D2 by measurement
M12  F5 full BSP walls   M13 F5 textured floors/ceilings   M14 F6/F7 loop+S0+present   M15 R2: 9-level binary
M16+ R3 (flag-gated): doors/hitscan · sprites/entities · HUD/text · fps cap · 320×200 — re-sliced when reached
```

**M2 is the PR #1 CR-loop** (adversarial, D15 below). M10 and M11c are owner-approval **measurement gates** —
their numbers land in-doc before anything downstream starts.

---

## 4. Setup & tools

- **flipjump 1.5.0 is installed** (verified this session: `flipjump 1.5.0`, native engine, `storage_mode=flat`).
  `pip install "flipjump[io]>=1.5.0"`.
- **flipjump-dev skill** — invoke it for fj specifics (macro signatures, complexities, idioms, the verification
  harness). `fjdocs.tomhe.app` is authoritative; prefer it over memory.
- **STL source** for macro complexities is inside the installed package
  (`.../site-packages/flipjump/stl/...`). This session re-verified the load-bearing costs there:
  `div n` = n²(36@+100), `write_byte`=41@+197, `read_byte`=33@+173, `read_byte_and_inc`=42@+187, `add n`=n(4@+12),
  `cmp n`=m(3@+8), `sign`=@-1, `scmp n`=n(7@+8), `shl_hex`=8@+32, `jump_to_table_entry`=4@+4, `or`=4@+10 — all match
  the doc. **Re-verify any cost you lean on; measure with a probe for anything load-bearing.**
- **Probe harness:** `flipjump.assemble([Path], fjm, memory_width=32)` + `flipjump.run(...)` → `term.op_counter`,
  `term.storage_mode`. Subtract an empty-loop baseline. (Windows: pipe stdin from a file, not `echo |`; set
  `PYTHONIOENCODING=utf-8`.) `flipjump.assemble_and_run_test_output(...)` for byte-exact macro tests.
- **PR #1 diff** (for S5.0): `gh pr diff 1 --repo tomhea/doom-flipjump`. (12 files, 576 lines: `fixed_point.fj`,
  `lut_generator.py`, the hexlib_tests, `test_lut_generator.py`.)

---

## 5. Guardrails

- **The design is settled — execute it, don't relitigate it.** Reopen a decision only on a real contradiction, and
  then fix it in-doc with a new `Stage N: … (#n)` commit.
- **D15: design is authority, PR #1 is reference.** No reuse-by-default. (See §2a.)
- **`@`-vs-ops discipline.** Never compare a game-scale `@=25` figure to a raw small-program ops figure without
  converting (the doc's `@`-note).
- **One logical change per commit**, message style `Stage N: … (#n)` (last was #24). Expect the harmless CRLF warning.
- **Owner approves at each gate.** The Stage-4 slicing is approved (§10), so Stage 5 is open. **The next action
  is Pre-M0** (`DESIGN.md` §10.2): **merge `stage-1-design` → `main`** (so the docs live where the loop branches
  from) and bootstrap branch protection + `docs/cr-rules.md` + `.claude/agents/crist.md` as direct commits.
  **Then M0** — the first PR to run the full loop. Execution then branches off `main` (`mN-…` per milestone).
