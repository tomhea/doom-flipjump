# Handoff — clean Stage-2 re-pass, then Stage 3 (same run)

**Audience:** a fresh session picking up DOOM-on-FlipJump. **You have done none of this work — that is the point.**
Bring fresh, adversarial eyes.

---

## 0. Mission (TL;DR)

1. **Re-run Stage 2 (contradiction hunt)** over the *current* `DESIGN.md`, mechanically and adversarially, per the
   `doom_implementation_handoff.md` §6 checklist. Fix every contradiction **in the document**. Get the owner to **re-approve**.
2. **Then, in the same session, run Stage 3 (directory tree)** per `doom_implementation_handoff.md` §7. Get the owner to **approve the tree**.
3. **STOP before Stage 4.** Each stage ends with explicit owner approval; nothing from a later stage starts early.

**Why a re-pass:** Stage 2 was already run once — but the document then **grew a lot** (it ~doubled) through a deep
owner Q&A on the frame budget and optimizations. The owner wants a **clean look** at the now-larger document before moving on.
Treat this as a *fresh* adversarial pass, not a re-read of the old findings.

---

## 1. Where things stand

- **Repo:** `tomhea/doom-flipjump` (this repo). **Branch: `stage-1-design`** — `DESIGN.md` lives here, **not on `main`**.
  First thing: `git branch --show-current` and confirm you're on `stage-1-design`.
- **Stage 1 (design doc): complete.** All decisions D1–D13 resolved (D14/D15 deferred to Stages 3/5).
- **Stage 2: run once, then the doc expanded** — `DESIGN.md` is now ~490 lines (was ~390). The growth is almost
  entirely in **§1 / §1.1.x** (the budget) plus new cross-refs into the components.
- **The process + the §6 checklist live in `doom_implementation_handoff.md` Part I §4–§6.** That file is the operating
  contract; read it first. Part II is inherited raw material.
- **Prior Stage-2 commits** are in git history (`git log --oneline --grep="Stage 2"`). You may skim them, but your job is a
  fresh pass — re-derive, don't inherit conclusions.

---

## 2. What this session added — the new surface area to scrutinize hardest

The original §6 checklist still applies in full. But the budget deep-dive introduced a **lot of interlocking numbers**, and
that's where new contradictions are most likely. New/changed material:

- **`@ = 25` working point** — the design now computes the budget at a fixed per-op constant `@ = 25` (≈ game scale; R-1
  measures the real one). The whole §1.1 ledger is in `@` and converted at 25. *(History: it was earlier carried as a
  `@≈15`-vs-`@≈27` dual model; that was collapsed to the single `@=25`.)*
- **§1.1.1 — per-pixel reconstruction.** The budget's per-pixel line had been ~2.5–5× under-counted; it's now rebuilt from
  the real STL macro costs (added the DDA `frac+=step` add and the ceiling/wall/floor select).
- **§1.1.2 — optimization ladder `#1–9`**, each with a profit number at `@=25`. **All owner-agreed.** #1 DDA
  fraction-accumulator, #2 `hex.sign` select, #3 fuse texture→colormap, #4 8.8 fracstep, #5 custom deposit table, #6 trim
  BSP fields, #7 **BSP-as-code**, #8 16.0 BSP math (precision ledger), #9 incremental scale.
- **§1.1.3 — Column+BSP+sim rebuilt** bottom-up (the old "soft ~2.5–5M" bucket). Finding: **reads dominate** (~42@/byte),
  not the multiplies; BSP-as-code is the big lever.
- **§1.1.4 — precision ledger.** Most quantities are **8.8 / 16.0 / 8.0, not 16.16** (only player position is genuinely
  16.16). D6 was reframed around this.
- **Multi-level packaging** — all 9 shareware E1 levels baked into **one binary**; confirmed **no per-frame fps penalty**
  (shared resources are constant-address; each level is BSP-as-code with its own constants; only "which root to enter" is a
  1-indirect-jump/frame). **Level table + progression + select menu** added to F6.
- **Floor↔fps curve (§1)** — **fps is continuous** (no timer; `fps = engine ÷ ops/frame`). Owner chose **full-res textured
  floors ≈ 14M ops ⇒ ~20 fps**; flat floors (~30 fps) and 2×2-block floors (~27 fps) are perf toggles. **Texture *size* ⊥
  per-pixel *cost*** (smaller flats save span, not fps).
- **Program-size estimate (§1.2)** — ~20–24 MB flat RAM single-level, **~31–38 MB all-9-E1-levels** (under the 64 MB limit);
  ~6–10 MB / ~12–18 MB `.fjm`. Textures dominate (~85%).
- **BSP-as-code, fraction-accumulator DDA, DDA constant-vs-variable** — all settled in §1.1.1–§1.1.3 / H3.
- **The original §6 fixes** from the first pass are also in (dispatch costs in `@`-units, OQ9 status, viewangletox index
  discipline, init ownership in F6, H7 plotly/`PcIO.headless`, span leading-pad, F2 `read_table`/`mul_const` not-STL,
  the LUT `xor_by`-not-`hex.set` construction). Re-verify them too — don't assume they survived the later edits.

---

## 3. Stage-2 re-pass — how to run it

**Read, in order:** `doom_implementation_handoff.md` Part I §4–§6 → `DESIGN.md` → Part II + cross-refs as needed →
the installed flipjump STL for any macro you lean on.

**Run the §6 checklist mechanically and adversarially** (the nine items: ledger sums; assumes↔supplies incl. init order;
encoding coherence; index discipline; units (`@` vs raw ops); call discipline; pacing math; decision propagation; fallback
reachability). **Plus** these re-pass-specific checks for the new material:

- **Budget arithmetic, end to end.** `@ = 25` everywhere (no leftover `@≈15`/`@≈27` except as labeled history). The per-pixel
  `@`-values in §1.1.1 must match the ones used in §1.1.2 profits and the §1.1 ledger. The optimization profits (#1–9) must be
  consistent with the per-pixel/column costs they claim to cut. The floor↔fps curve (~9M/~10M/~14M ↔ ~30/~27/~20 fps) must be
  consistent with `280M ÷ ops` and with the wall/floor split.
- **One number, many places.** The frame total and fps appear in §1, §1.1 (ledger + conclusion), §1.1.2 conclusion, D9, and
  R-1. They must **all** say the same thing (full-res textured floors ≈ 14M → ~20 fps). Grep and reconcile.
- **Decision propagation for the *new* decisions.** Grep each and confirm every referencing component agrees: `@=25`;
  full-res textured floors @ ~20 fps; all opts #1–9 agreed; all-levels-in-one-binary; BSP-as-code (#7); the precision-ledger
  widths (#8).
- **Precision-ledger coherence (§1.1.4 ↔ usage).** Each width must match where the quantity is used (8.8 DDA/scale, 16.0
  map+BSP math, 8.0 screen coords, 16.16 player pos only). Width-mismatch boundaries (16.16 player vs 16.0 vertex) must be
  flagged (D13 / the flipjump-dev width-mismatch rule).
- **Multi-level coherence.** F6 level-table ↔ §1.2 size estimate ↔ H3 emit-mode ↔ the no-per-frame-penalty claim must all
  agree. Sanity-check the "no fps penalty" argument adversarially (does anything on the hot path actually become a runtime
  pointer because the level is now a variable? The doc claims no — verify).
- **Macro/cost claims — measure, don't reason.** flipjump 1.5.0 is installed (native engine; `storage_mode=flat`). For any
  load-bearing fj-op cost, **assemble + run a small probe** and check it (this session's earlier numbers were wrong *twice* —
  the DDA cost and the floor cost — and probes/STL-reads caught them). Especially: dispatch (~4@), deposit (~4@), the DDA
  (~9–16@, the step<1/≥1 split), `read_byte_and_inc` (~42@/byte), and the BSP-as-code side-test cost. **Convert carefully:**
  a small probe runs at a *small* `@` (~9–11), not the game-scale `@=25` — never compare a `@=25` figure to a raw small-`@`
  ops figure (the doc has an `@`-note on exactly this trap).

**For each contradiction:** state it plainly, fix it in `DESIGN.md`, commit (one logical fix per commit, message style
`Stage 2: <fix> (#n)` — match the existing commits). When the checklist passes clean, **summarize what you found and fixed,
and ask the owner to re-approve the document.** Do not proceed to Stage 3 until they do.

---

## 4. Stage 3 — directory tree (same run, after re-approval)

Per `doom_implementation_handoff.md` §7, propose the full `doom-flipjump` structure and get owner approval:

- **fj sources** — the F1–F9 engine layers (memory map, fixed-point, LUT-access, framebuffer, renderer, game-loop, present,
  HUD/compositor, debug).
- **Generated output** — tables/maps; decide the in-repo-vs-build-dir policy. **Account for the new generators:** BSP-as-code
  emitter (H3), the dispatch-LUT/texture tables (H2/H4), the **level table** for the multi-level binary, and the
  precision-ledger-driven fixed-point variants (8.8/16.0/8.0).
- **Host tools** — H1–H7 (WAD parser, LUT/dispatch generator, map compiler incl. BSP-as-code, texture/colormap compiler,
  reference model, build system, test harness).
- **Tests** — unit / per-table generated / golden-frame / headless scripted-replay fixtures.
- **Docs / CI** — `DESIGN.md`, README, the build pipeline (`w=32`, `--werror`, `--flat-max-words`).
- **PR #1 mapping** — explicitly map `fixed_point.fj` / `lut_generator.py` / their tests from the PR's paths → their
  *designed* homes in the tree.

Get the owner to approve the tree. **Then STOP** — do **not** start Stage 4 (iterative stage cutting).

---

## 5. Setup & tools

- **flipjump 1.5.0 is installed** (`pip install "flipjump[io]>=1.5.0"`). Verify: a quick `fj` run + a `storage_mode` report
  (must be `flat`). The native engine is ~280–334M fj/s flat.
- **flipjump-dev skill** — invoke it for fj specifics (macro signatures, complexities, idioms, the verification harness).
  `fjdocs.tomhe.app` is the authoritative macro/CLI reference; prefer it over memory.
- **STL source** for reading macro complexities is inside the installed `flipjump` package
  (`.../site-packages/flipjump/stl/...`). Files this session leaned on: `hex/math.fj`, `hex/memory.fj`, `hex/logics.fj`,
  `hex/cond_jumps.fj`, `hex/shifts.fj`, `hex/pointers/*.fj`, `hex/tables_init.fj`, `runlib.fj`, `ptrlib.fj`, and the device
  `interpreter/io_devices/ScreenIO.py` / `pygame_window.py`.
- **Probe harness:** `flipjump.assemble([Path], fjm, memory_width=32, print_time=False)` + `flipjump.run(fjm,
  print_time=False, print_termination=False)` → `term.op_counter`, `term.storage_mode`. Measure per-op cost via a runtime
  loop and subtract the empty-loop baseline. (Windows note: pipe stdin from a file, not `echo |`; set `PYTHONIOENCODING=utf-8`
  to avoid cp1255 errors on non-ASCII prints.) Clean up any scratch probe dir before committing.
- **Git:** stay on `stage-1-design`; commit per logical fix; do **not** merge to `main`. (Expect a harmless CRLF warning on
  commit.)

---

## 6. Guardrails

- **Fresh eyes — re-derive, don't trust the doc's numbers.** This session twice found its *own* earlier numbers wrong (the
  optimized DDA `~5@`→`~11@`, and floors mis-charged the cheap wall cost). The doc now reflects the corrections, but verify
  the load-bearing ones yourself by probe.
- **`@`-vs-ops discipline.** Never compare a `@=25` (game-scale) figure to a raw small-program ops figure without converting.
  This is the single most common units trap here and is called out in the doc's `@`-note.
- **One logical fix per commit**, message style `Stage 2: … (#n)`.
- **Owner approves at each gate.** Re-approval of the document closes Stage 2; tree approval closes Stage 3. **STOP after
  Stage 3** — do not begin Stage 4.
