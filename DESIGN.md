# DOOM-on-FlipJump — Design Document

> **Status: Stage 1 (Design) — IN PROGRESS.** Built iteratively through owner Q&A per the
> [implementation handoff](doom_implementation_handoff.md) §4–§5. Every decision is recorded in the
> **Decisions** section below with an ID, rationale, and the measurement (if any) that settled it —
> not in chat. Part II of the handoff is *input* to this document, not settled design; where an item
> here is still undecided it is marked **OPEN** and tagged with the D-item that will close it.
>
> **No game code is written until this document is complete and approved (Stage 2 done).**

## Process gates (handoff §4)

1. **Stage 1 — this document.** Cover every component per the §5 spec. ← *we are here*
2. **Stage 2 — contradiction hunt.** Adversarial pass (handoff §6 checklist); fix in-doc; re-approve → *final document*.
3. **Stage 3 — directory tree** (handoff §7).
4. **Stage 4 — iterative stage cutting** (handoff §8).
5. **Stage 5 — execution.** First item: CR-loop PR #1 into the Stage-3 tree (handoff §9), then execute.

---

## 1. Targets & budgets (living ledgers)

**Primary target (owner decision, locked):** 160×100, textured, 256 colors, 25 fps.
**Stretch:** 320×200 @ 25 fps textured — *only after* the jump-target speculation tier lands (~450–600M fj/s). Not a dependency.
**Fallbacks:** 160×100 flat-shaded · 160×100 textured @ 12.5 fps · flat→paged storage.

**Budget:** ~280M fj/s (measured flat, native engine) ÷ 25 fps = **~11.2M fj-ops / frame.**

### 1.1 Ops-per-frame ledger (must sum < 11.2M with stated margin)

Seeded from handoff §2 (estimates — **R-1**: measured at S5.3/R1 before R2 commits). Each component
below adds/refines its own line as the design firms up.

| Line | Per-frame cost (est.) | Technique | Settled by |
|---|---|---|---|
| Pixel stores (16K px × ~80 ops, static) | ~1.3M | static stores §3.1 | D2/R1 |
| Texture + colormap reads (16K × ~100–200, dispatch-LUT) | ~1.6–3.2M | dispatch-LUTs §3.2 | D5/D11 |
| Column math (160 cols) + visibility walk + game logic | ~1.5–3M | LUTs + adds, mul/div-free | D1/D6 |
| Present (`update_screen` 0x03 memory-hook) + input poll | ~negligible (~70 + tens) | — | — |
| **Total** | **~5–7M of 11.2M (~2× margin)** | | |

### 1.2 Address-span ledger (must sum < chosen `--flat-max-words`; **R-3**)

Power-of-two dispatch-table padding inflates the span — lay out **largest-alignment-first** (§3.3) and
sum padding here, don't discover it. **OPEN — D10** (concrete memory map). Default flat limit = 2²³ words
(64 MB); raise via `--flat-max-words` / `FLIPJUMP_FLAT_MAX_WORDS` if needed (cost = RAM + ~0.1 s/GB fill,
zero per-op cost). Assert `storage_mode == flat` in the harness.

| Segment / table | Entries | Entry size | Alignment pad | Span (words) | Notes |
|---|---|---|---|---|---|
| *TBD* | | | | | filled via D10 |

---

## 2. Glossary & conventions

- **fj-op** — one assembled FlipJump op (flip-word + jump-word = `dw` bits). The budget unit.
- **`@`** — the per-op cost constant (~27 at w=32); grows with total program size (**U7**). A figure in
  `@` is *not* comparable to a raw-ops figure without conversion (contradiction-hunt §6).
- **w / dw / dbit** — word width (=**32**, confirmed: 16.16 fits one word) / `2w` (one op) / `w` (data-bit offset).
- **nibble / hex / byte** — a `hex` = 4 data bits; a packed byte = 8 data bits in one op; register-form byte = two `hex` ops (low, then `+dw`). The two byte encodings do **not** interchange (see flipjump-dev skill).
- **Fixed-point** — Q-format: 16.16 = `n=8,f=4`; 8.8 = `n=4,f=2`. Signed; compare with `hex.scmp`, never `hex.cmp` (§3.5).
- **Static store** — a framebuffer write to a *compile-time-known* address (~7@), vs a runtime-address pointer write (~500–1300 ops).
- **Dispatch-LUT** — the `hex.xor`-jumper table idiom (`tables_init.fj`): ~10@/lookup, 10–30× cheaper than `read_table`.

---

## 3. Memory map

**OPEN — D10.** Largest-alignment-first layout of: state/scratch registers, dispatch tables (trig,
reciprocal, yslope, viewangle maps, colormaps, textures), map/seg streams, framebuffer. Tracked in the
§1.2 span ledger. Invariant: total span < flat limit; `storage_mode == flat` asserted in tests.

---

## 4. Decisions (D1–D15)

> Format: **D# — title.** *Status.* Resolution + rationale + what measurement settled it (if any).
> Owner leanings from the handoff are pre-recorded but **not** final until confirmed in the Q&A.

- **D1 — Visibility model.** *RESOLVED → **BSP front-to-back walk** (real DOOM geometry).* Now affordable post-rebaseline (~1.5–3M ops, shared with column math); no gridification, so **U11 is moot**. Accepts more renderer complexity (visplanes, clipping arrays, seg/node stream walk via sequential `*_and_inc` reads, §3.4). Settles H3 (map compiler bakes BSP NODES/SSECTORS/SEGS) and F5 (renderer is a BSP walk). Grid raycaster retained only as a documented last-resort fallback (would require a renderer rewrite — *not* a cheap fallback, noted for §6 fallback-reachability).
- **D2 — Static-store design.** *OPEN (decided by R1 measurements: ops AND assemble time AND `.fjm` size).* (a) fixed-address column buffer + one sequential pass **vs** (b) full column unroll (zero pixel-path pointers, costs WIDTH× code). Owner leaning: hex-memory for pixels (see D3 criterion).
- **D3 — Framebuffer encoding.** *OPEN — known tension (R-4).* Owner leaning **hex-memory** pixels; the screen device's primary read (`update_screen` 0x03 memory-hook) is a **packed-byte** framebuffer at bpp=8. Must co-resolve store layer ↔ device read format ↔ palette bpp. Resolve early (handoff §6).
- **D4 — Per-table dispatch shape.** *OPEN, per-table.* Per-result-nibble aligned tables (8 cheap dispatches for 32-bit entries) **vs** per-entry handlers (1 dispatch + popcount flips).
- **D5 — Texture storage.** *OPEN.* Dispatch tables **vs** sequential streams; texture count/resolution vs span ledger (**OQ8**).
- **D6 — Precision per quantity.** *OPEN.* 16.16 vs 8.8 (~4× cheaper mul) per variable, validated against the reference model (wobble risk, **OQ5**).
- **D7 — Feature scope at 160×100.** *RESOLVED → first playable (R2) = **textured 3D view (walls + floors/ceilings) + S0 walk/collide**, auto-warp into the level.* Flag-gated for R3+: S1 doors+hitscan, S2 sprites/enemies, HUD/status bar, menus, text, demo playback. Rationale: prove the renderer + the §1.1 budget (the hard part) first; matches the §8 ladder. The compositor/pass pipeline and `blit_rect`/glyph API (§E, F8) are **stubbed flag-gated from day one** so later passes drop in without touching the 3D core.
- **D8 — Maps & assets.** *OPEN.* Which level(s); full E1M1? entity counts. Handoff policy: shareware `doom1.wad` for dev, **Freedoom** for anything redistributed (CI fixtures) — confirm.
- **D9 — Frame pacing.** *RESOLVED → **tic:render 1:1, budget-bound**.* One input poll = one tic = one rendered frame. There is no timer device (§1.1), so the program cannot self-pace to wall-clock time; "25 fps" = "hold ops/frame < 11.2M so the native engine *delivers* ~25 fps on the reference machine." Accept and **report** the measured wall-clock fps (present-log). Sim/render decoupling (render 1-of-N tics, G21) is a deferred hedge, not built in R2.
- **D10 — Memory map.** *OPEN.* Concrete largest-alignment-first layout + span budget (→ §3, §1.2).
- **D11 — Colormap/lighting application point.** *OPEN.* Per-pixel (inside the 100–200 op texture-read est.) **vs** per-column (flat mode). Naïve per-pixel colormap = a pointer read per pixel (~6M+/frame) — **U9**.
- **D12 — Test granularity.** *OPEN.* What's unit-tested vs golden-framed; how many golden frames; demo scripts.
- **D13 — Fixed-point intermediates.** *OPEN.* 32×32→64 product handling at w=32 (**U5**). (PR #1's `fixed_mul` already does full 2n-nibble width — confirm this is the contract.)
- **D14 — Directory tree.** *Deferred to Stage 3.*
- **D15 — PR #1 CR surface.** *Deferred to Stage 5 / S5.0.* API/naming/test-style changes to `fixed_point.fj` + LUT generator.

---

## 5. Testing strategy (the pyramid)

Per handoff §H / §3.5. Top to bottom:

1. **Host unit tests (Python)** — WAD parser, LUT/dispatch generator, map/texture compilers, reference model. `pytest`.
2. **Per-macro fj tests** — TDD, `--werror`, byte-exact via `flipjump.assemble_and_run_test_output`, **a boundary input per behavior path** (single green fixture proved insufficient 3× in the catalog), `hex.scmp` for anything signable.
3. **Per-table generated tests** — each generated `.fj` table diffed vs a host reference over many indices incl. first/last/wrap.
4. **Golden-frame renderer tests** — headless `PcIO.headless(events_file, frames_dir)` / `InMemoryScreen`; hash + diff `SCREEN→PNG` vs host reference.
5. **Headless scripted-replay E2E** — scripted key-event file drives movement/collision/fire; player state must match the reference exactly; measured fps (present-log) meets the tier.

**Tracked metrics from the first renderer experiment:** ops/frame (`--profile`/featured loop on small builds) **and** assemble time **and** `.fjm` size.

---

## 6. Component inventory

> Each component gets the §5 per-component template: **Purpose · Supplies · Depends-on · Assumes ·
> Data & layout · Time · Space · Testing · Open questions.** Stubs below; filled through the Q&A.

### Host-side (Python, doom-flipjump repo)
- **H1 — WAD parser/extractor** — levels (VERTEXES/LINEDEFS/SIDEDEFS/SECTORS/SEGS/SSECTORS/NODES/THINGS) + assets (PLAYPAL, COLORMAP, textures/patches, flats, sprites) per D7/D8 scope. *Fields: TBD.*
- **H2 — LUT/dispatch generator** (from PR #1, upgraded) — emits **dispatch-code tables** (§3.2) *and* data tables; per-table emit modes (hypercube chain / per-entry handlers / per-result-nibble); alignment-aware. *Fields: TBD — D4.*
- **H3 — Map compiler** — WAD level → baked `.fj` BSP structures (NODES / SSECTORS / SEGS / SECTORS / SIDEDEFS / LINEDEFS / VERTEXES) walked as sequential streams by F5. *Fields: TBD — D1 resolved (BSP); layout via D10.*
- **H4 — Texture/colormap compiler** — D5's output format. *Fields: TBD — D5.*
- **H5 — Reference model** — host-side golden implementation of *our exact* renderer + sim for frame/state diffing. *Fields: TBD.*
- **H6 — Build system** — assemble pipeline (w=32, `--flat-max-words`, `--werror`), script/Makefile, CI. *Fields: TBD.*
- **H7 — Test harness** — headless replays, golden-frame compare, per-table runner, ops-budget profiler. *Fields: TBD.*

### FJ-side (the game program)
- **F1 — Memory map / layout module** — the address plan; has invariants and tests. *Fields: TBD — D10.*
- **F2 — Fixed-point math layer** — `fixed_point.fj` (PR #1): `fixed_mul`/`fixed_div` 16.16 + 8.8, plus D6/D13 intermediate-width handling. *Fields: partly specified by PR #1.*
- **F3 — LUT access layer** — the dispatch-jumper idioms, one per table family (finesine/finecosine, reciprocal/scale, yslope, viewangletox/xtoviewangle, colormaps). *Fields: TBD — D2/D4.*
- **F4 — Framebuffer + pixel-store layer** — D2/D3's resolved design. *Fields: TBD — D2/D3.*
- **F5 — Renderer** — BSP front-to-back walk (D1), wall column renderer, floor/ceiling spans/visplanes, sprite renderer (flag-gated, D7), lighting/colormap point (D11). R2 ships walls + floors/ceilings textured. *Fields: TBD.*
- **F6 — Game loop & tic** — tic:render 1:1 (D9): poll → update `keydown[]` → sim tic → render → present, every frame. R2 sim = S0 (turn / move / wall-slide collide). Doors/specials (S1), entities/AI (S2, §D), combat, level transitions all flag-gated (D7). *Fields: TBD.*
- **F7 — Present layer** — init/set_palette/update_screen; `update_rectangle` (0x04) only for status-bar/menus. *Fields: TBD.*
- **F8 — HUD/status bar/menu/text passes** — compositor/pass pipeline + `blit_rect`/glyph design (§E). *Fields: TBD — D7.*
- **F9 — Debug/diagnostics** — op-count probes, frame dumps, on-screen debug values. *Fields: TBD.*

---

## 7. Risks (handoff §10, live)

- **R-1** — Budget estimates are projections; S5.3 measures before R2 commits. Margin ~2×, not infinite. Fallbacks: flat-shaded / 12.5 fps.
- **R-2** — Assembler scalability is load-bearing (column-unroll + mega dispatch tables). Measure assemble time + `.fjm` size at game scale (S5.1/S5.3); relief valve = design (a) column buffer.
- **R-3** — Span vs flat path: power-of-two padding can silently overflow → paged (~2.5× slower). Guards: span ledger + `storage_mode` assertion.
- **R-4** — D3 encoding tension (hex-memory pixels vs packed-byte device read) — resolve in this doc, not in code.
- **R-5** — *(cleared)* flipjump 1.5.0 released; only WI-F speculation is future headroom.
- **R-6** — Fidelity unknowns: 8.8 wobble (D6), 32×32→64 intermediates (U5/D13), `@` growth (U7) — survive re-baselining, now with more headroom.

---

## 8. Open questions (inherited, mapped to D-items)

OQ4 (does per-column math reduce fully to LUTs+adds? → D2/R1) · OQ5 (16.16 vs 8.8 wobble → D6) ·
OQ8 (map/texture dispatch tables small enough for compile+span? → D5/R-2/R-3) · OQ9 (`fcall`
non-reentrancy — any hot call chain > 1 nesting level? → R1 as the call graph forms) · OQ10 (variable
fps vs worst-case cap → D9).
