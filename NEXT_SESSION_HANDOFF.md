# Handoff — Stage 4 (iterative stage cutting), then Stage 5 (execution)

**Audience:** a fresh session picking up DOOM-on-FlipJump after **Stages 1–3 are complete and owner-approved.**
Your job starts at **Stage 4**. Bring fresh, adversarial eyes — but the *design itself is settled*; do not reopen it
without a contradiction.

---

## 0. Mission (TL;DR)

1. **Run Stage 4 — iterative stage cutting** (`doom_implementation_handoff.md` §8). Slice the approved design into
   small, independently testable execution stages, each with an explicit exit criterion. **Measurement stages come
   before the designs they decide** (e.g. R1 settles D2 before R2 commits). Get the owner to **approve the slicing**.
2. **STOP after Stage 4.** Do not start writing game code (Stage 5) until the slicing is approved.
3. Then **Stage 5 — execution**, first item **S5.0: the PR #1 CR-loop** — run it *adversarially* per the D15 policy
   below.

---

## 1. Where things stand

- **Repo:** `tomhea/doom-flipjump` (this repo). **Branch: `stage-1-design`** — `DESIGN.md` lives here, not on `main`.
  First thing: `git branch --show-current`.
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

## 3. Stage 4 — how to run it (handoff §8)

Slice the design into stages that are each **small, independently runnable, tested, and end in something
demonstrable** (a passing suite, a rendered frame, a measured number). Each states its **exit criterion** up front.
**Measurement before commitment** (R1 measures D2's static-store design — ops/frame *and* assemble time *and* `.fjm`
size — before R2 builds on it).

The handoff §8 sketch (non-binding — Stage 4 formalizes it), refined by the D15 policy and the §9 tree:

```
S5.0  CR-loop PR #1 ADVERSARIALLY into the §9 tree (D15): keep fixed_point.fj iff it
      matches D13/§3.4; lift the generator value-kernel into tables.py/fixedpoint.py;
      else rewrite. Land fixed_point.fj (F2) + the host shared-truth modules.
S5.1  LUT generator gains the dispatch-code emitter (per-entry default / per-result-nibble
      override / +4-offset deposit / over-align / 16^x) + per-table tests (#8: every entry
      + call-twice). Data-table emission stays as the §3.4 fallback.
S5.2  R0: WAD pipeline (H1) + generated tables (trig/recip/yslope/viewangle/colormap) +
      config.py/fj_consts wiring; fill the §1.2 span ledger + §1.3 entry counts with REAL
      E1M1 numbers.
S5.3  R1: renderer vertical slice — settle D2 (static-store: full-unroll vs column buffer)
      with MEASURED ops/frame + assemble time + size; settle the per-pixel deposit/DDA cost
      (R-1) and the real @ at game scale. This is the gate before R2.
S5.4  R2: full renderer at 160×100 textured + S0 walk/collide; all-9-E1-levels-in-one binary;
      report measured fps against the §1 floor↔fps curve (~14M ⇒ ~20 fps target).
S5.5  R3: doors/combat/entities/HUD/glyphs/sprites per D7; device-side fps cap (D9) for an
      interactive build.
```

Each stage's exit criterion should name the artifact and the metric. Get the owner to **approve the slicing**, then
**STOP** — Stage 5 execution is the next session.

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
- **Owner approves at each gate.** Stage-4 slicing approval opens Stage 5. **No game code before the slicing is
  approved.** Stay on `stage-1-design`; do not merge to `main`.
