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
| Pixel stores (16K px, packed-byte deposit ≈ 2 dispatches/px, static) | ~1.3M (est; R1 measures) | static stores §3.1, D3 deposit | D2/D3/R1 |
| Texture + colormap reads (16K × ~100–200, dispatch-LUT) | ~1.6–3.2M | dispatch-LUTs §3.2 | D5/D11 |
| Column math (160 cols) + visibility walk + game logic | ~1.5–3M | LUTs + adds, mul/div-free | D1/D6 |
| Present (`update_screen` 0x03 memory-hook) + input poll | ~negligible (~70 + tens) | — | — |
| **Total** | **~5–7M of 11.2M (~2× margin)** | | |

### 1.2 Address-span ledger (must sum < chosen `--flat-max-words`; **R-3**)

Power-of-two dispatch-table padding inflates the span — lay out **largest-alignment-first** (§3.3) and
sum padding here, don't discover it. **OPEN — D10** (concrete memory map). Default flat limit = 2²³ words
(64 MB); raise via `--flat-max-words` / `FLIPJUMP_FLAT_MAX_WORDS` if needed (cost = RAM + ~0.1 s/GB fill,
zero per-op cost). Assert `storage_mode == flat` in the harness.

| Segment / table | Size formula (ops) | Align pad | Span (R0-filled) | Notes |
|---|---|---|---|---|
| hex.init truth tables | ~fixed (or/and/mul/cmp/add/sub) | — | TBD | from `stl.startup_and_init_all` |
| Unrolled renderer code (D2b) | ~16K px × stub size + 160 col × col-setup | — | **TBD (R-2 watch)** | the big code consumer; assemble time tracked |
| Texture dispatch table(s) (D5) | pow2 ≥ Σ texel counts | pow2 pad | **TBD (OQ8 watch)** | likely largest table → placed first |
| Trig (finesine/cosine/tangent) | pow2 ≥ entries, per-entry handlers (D4) | pow2 pad | TBD | per-result-nibble override if span tight |
| Reciprocal / scale | pow2 ≥ entries | pow2 pad | TBD | replaces divides |
| yslope · viewangletox/xtoviewangle | pow2 ≥ entries | pow2 pad | TBD | |
| Colormaps (D4 handlers) | pow2 ≥ 256·#maps, byte results | pow2 pad | TBD | per-column-selected (D11) |
| +4-offset deposit table (D3) | 256 | pow2 pad | ~256 | |
| Framebuffer | W·H = 160·100 = 16,000 | — | 16,000 | packed bytes, no align |
| Palette | 256·3 = 768 | — | 768 | |
| Map/BSP streams | Σ lump sizes (E1M1) | — | TBD | sequential |
| State/scratch registers | small fixed set | — | TBD | hex.vec |
| **Total** | | | **TBD < 8.4M (R0)** | else raise `--flat-max-words` |

---

## 2. Glossary & conventions

- **fj-op** — one assembled FlipJump op (flip-word + jump-word = `dw` bits). The budget unit.
- **`@`** — the per-op cost constant (~27 at w=32); grows with total program size (**U7**). A figure in
  `@` is *not* comparable to a raw-ops figure without conversion (contradiction-hunt §6).
- **w / dw / dbit** — word width (=**32**, confirmed: 16.16 fits one word) / `2w` (one op) / `w` (data-bit offset).
- **nibble / hex / byte** — a `hex` = 4 data bits; a packed byte = 8 data bits in one op; register-form byte = two `hex` ops (low, then `+dw`). The two byte encodings do **not** interchange (see flipjump-dev skill).
- **Fixed-point** — Q-format: 16.16 = `n=8,f=4`; 8.8 = `n=4,f=2`. Signed; compare with `hex.scmp`, never `hex.cmp` (§3.5).
- **Static store** — a framebuffer write to a *compile-time-known* address (~7@), vs a runtime-address pointer write (~500–1300 ops).
- **Dispatch-LUT** — the `hex.xor`-jumper table idiom (`tables_init.fj`): ~10@/lookup, 10–30× cheaper than `read_table`. One dispatch sets a *fixed-address* hex = a *runtime* value (indexes on the current nibble), so it is the pointer-free deposit primitive.
- **Cell width ⊥ pointer-freeness** (key D3 insight) — "packed byte" (8-bit cell, forced by bpp=8/256-color + the device read) is the framebuffer *cell width*; "pointer-free" is whether the *address* is compile-time-known (delivered by D2(b) full-unroll). Orthogonal: a packed-byte framebuffer can be written entirely by fixed-address stores. The runtime-value→fixed-address deposit cost scales with bits — a byte ≈ 2× a nibble — so bpp=4/hex.vec is the ~2×-cheaper-deposit / 16-color cost-fallback.

---

## 3. Memory map (D10)

**Layout principle (§3.3): largest-alignment-first** so pow2 table padding nests instead of summing.
Dispatch tables are **pad-aligned CODE** (base low-bits zero, entry `k` at `base+k·dw`), so they live in
the code region; the framebuffer/streams/registers are data (below `stl.loop`). Units: 1 fj-op = `dw` =
64 bits at w=32 = one 8-byte span-word; default flat limit = 2²³ span-words (64 MB) ≈ **8.4M ops** (raise
via `--flat-max-words` if needed — cost is RAM + ~0.1 s/GB fill, zero per-op). **Invariant: total span <
flat limit; `storage_mode == flat` asserted in the harness (R-3).**

```
0x0   stl.startup + hex.init truth tables          (from stl.startup_and_init_all)
      [CODE] game loop · BSP walk · unrolled renderer (D2b) · present · input poll
      [CODE] LUT-access idioms (F3)
      --- pow2-aligned dispatch tables, LARGEST ALIGNMENT FIRST (CODE) ---
      texture dispatch table(s)     (D5; align pow2 ≥ texel count — likely the largest)
      trig: finesine/finecosine/finetangent
      reciprocal / scale
      yslope · viewangletox / xtoviewangle
      colormaps                     (D4 per-entry handlers; byte results)
      +4-offset packed-byte deposit table (256 entries, D3)
stl.loop   (halt)
      --- DATA (below stl.loop) ---
      framebuffer        (W·H = 16K packed-byte ops; no pow2 alignment needed)
      palette            (256 × 3 packed bytes)
      map/BSP streams    (NODES/SSECTORS/SEGS/SECTORS/SIDEDEFS/LINEDEFS/VERTEXES — sequential)
      state/scratch      (player pos/angle/eye; per-column top/bottom/colormap-sel scratch;
                          keydown[]; door/entity state [flag-gated]; precision ledger registers)
      stack              (minimal — fcall is stackless; stl.stack only if recursion appears, OQ9)
```

Concrete spans are tracked in the **§1.2 span ledger** (sizes filled by R0; padding waste summed there).

---

## 4. Decisions (D1–D15)

> Format: **D# — title.** *Status.* Resolution + rationale + what measurement settled it (if any).
> Owner leanings from the handoff are pre-recorded but **not** final until confirmed in the Q&A.

- **D1 — Visibility model.** *RESOLVED → **BSP front-to-back walk** (real DOOM geometry).* Now affordable post-rebaseline (~1.5–3M ops, shared with column math); no gridification, so **U11 is moot**. Accepts more renderer complexity (visplanes, clipping arrays, seg/node stream walk via sequential `*_and_inc` reads, §3.4). Settles H3 (map compiler bakes BSP NODES/SSECTORS/SEGS) and F5 (renderer is a BSP walk). Grid raycaster retained only as a documented last-resort fallback (would require a renderer rewrite — *not* a cheap fallback, noted for §6 fallback-reachability).
- **D2 — Static-store design.** *RESOLVED (direction) → **lean hard to (b) full column unroll**; R1 measures both before final commit.* (b) `rep(SCREEN_WIDTH, x) render_column x` makes every framebuffer address a compile-time constant ⇒ **zero pixel-path pointers** (the §B "constant algorithm"); heavy color/select/pack logic factored into a shared `stl.fcall` leaf so it isn't duplicated WIDTH×. R1 measures (b)'s ops/frame **and** assemble time **and** `.fjm` size against (a) the fixed-address column buffer + one sequential pass. (a) is the **first-class relief valve** if R-2 (assembler scale) bites. Owner intent: make (b) work.
- **D3 — Framebuffer encoding.** *RESOLVED → **packed-byte, bpp=8** (256 colors), device-direct.* **R-4 closed.** Framebuffer = one packed byte/op, stride `dw`, row-major (matches `ScreenIO` `update_screen` exactly — zero present-time conversion). Written by D2(b) full-unroll fixed-address stores (pointer-free). The framebuffer is **write-only during rendering** (F4 invariant), so encoding is chosen on *(device match) + (deposit cost)* only.
  - **Deposit mechanism (new component obligation, F3/F4):** a fixed-address packed-byte deposit of a runtime value = **low nibble** via the existing `hex` dispatch table (dbit-aligned) + **high nibble** via a custom **+4-offset 256-entry table** — a ~1-line variant of `hex.tables.clean_table_entry__table` (flip target `dst+dbit+4+(#d)-1`) plus its jumper. ~2 dispatches/pixel. TDD'd like any table.
  - **Rejected alternatives:** `hex.vec 2` framebuffer (256 colors via 2 ops/px) is **dominated** — the device reads one packed byte/op so it can't read `hex.vec 2`, forcing a pack pass that needs the *same* +4-offset code anyway, plus ~2× deposit work and 2× span. `hex.vec-1 bpp=4` (16 colors, zero custom code, ~1 dispatch/px) is the documented **cost-fallback** if R1 shows the byte deposit is the budget-buster and 16 colors is acceptable.
  - **R1 measures** the real per-pixel deposit cost before R2 commits (R-1).
- **D4 — Per-table dispatch shape.** *RESOLVED → **per-entry handlers (default)**; per-result-nibble as a per-table override.* Per-entry handler = 1 dispatch + popcount flips (≈4@+2W ops) — ~7× faster than per-result-nibble (W dispatches ≈ 4W@) for wide results, ~2× for a byte. Chosen because ops/frame is the scarce resource and the per-pixel colormap benefits most. **Cost it carries:** a more complex generator (custom per-entry flip code) and ~2–3× table space on wide tables (feeds **R-3** span). **Override:** large *cold* tables (e.g. trig) may use per-result-nibble to save span if the span ledger tightens — recorded per-table in the span ledger + the table's test. Both fit the shared `res`/`ret` machinery (handler XORs `value[k]` into `res`, caller `xor_zero`s out).
- **D5 — Texture storage.** *RESOLVED → **dispatch-LUT textures**.* Textures baked as aligned dispatch table(s); per-pixel texel sample = ~10@ dispatch (not ~1000-op `read_table`). Per column the source column is fixed (selected once, amortized); per pixel the index = per-column base + texel (`frac>>FRACBITS`, a compile-time shift) — an add, nibble-aligned, no runtime shift (U6). **Span (texel count rounded to pow2, OQ8) is the open risk — measured in R0/R1**; fallbacks: sequential packed-byte streams, fewer/smaller textures. R2 bound to E1M1's real textures (downscale if the span ledger demands). Entry shape per D4.
- **D6 — Precision per quantity.** *RESOLVED → **16.16 default, drop to 8.8 only with evidence**.* Every quantity is 16.16 (DOOM-faithful, correctness-first) unless a **per-quantity precision ledger** records a justified 8.8: justification = profiling shows the cost is material **and** the reference-model diff (OQ5) confirms acceptable wobble. The mostly-LUT'd hot path + ~2× margin make this low-risk.
- **D7 — Feature scope at 160×100.** *RESOLVED → first playable (R2) = **textured 3D view (walls + floors/ceilings) + S0 walk/collide**, auto-warp into the level.* Flag-gated for R3+: S1 doors+hitscan, S2 sprites/enemies, HUD/status bar, menus, text, demo playback. Rationale: prove the renderer + the §1.1 budget (the hard part) first; matches the §8 ladder. The compositor/pass pipeline and `blit_rect`/glyph API (§E, F8) are **stubbed flag-gated from day one** so later passes drop in without touching the 3D core.
- **D8 — Maps & assets.** *RESOLVED.* **Asset source:** shareware `doom1.wad` for development; **Freedoom** WADs for anything redistributed (CI fixtures / golden frames). **Map ambition:** R1 renderer bring-up + measurement on a small (hand-built or smallest real) BSP map to keep the assemble/span/measure loop fast; **real E1M1 is the R2 target.** Entity counts: deferred to D7's S2 tier (sprites flag-gated; not in R2).
- **D9 — Frame pacing.** *RESOLVED → **tic:render 1:1, budget-bound**.* One input poll = one tic = one rendered frame. There is no timer device (§1.1), so the program cannot self-pace to wall-clock time; "25 fps" = "hold ops/frame < 11.2M so the native engine *delivers* ~25 fps on the reference machine." Accept and **report** the measured wall-clock fps (present-log). Sim/render decoupling (render 1-of-N tics, G21) is a deferred hedge, not built in R2.
- **D10 — Memory map.** *RESOLVED (structure) → see §3 + the §1.2 span ledger.* Largest-alignment-first: hex.init tables → unrolled renderer code → pow2-aligned dispatch tables (texture first, then trig/recip/yslope/viewangle/colormaps/+4-offset) → `stl.loop` → framebuffer / palette / map streams / scratch / stack. Concrete spans filled by R0; flat-limit invariant guarded by the span ledger + `storage_mode` assertion.
- **D11 — Colormap/lighting application point.** *RESOLVED → **per-column/span SELECT, per-pixel APPLY**.* The colormap (light level) is chosen once per column (walls) / per span (floors) — DOOM-faithful, ~160×/frame; it is then applied per pixel as a dispatch chained off the texel sample (texel → lit palette byte). Avoids the U9 trap (per-pixel light *recomputation* / pointer-read colormap, ~6M+/frame) while keeping correct per-pixel colormap application. Per-pixel light *recomputation* (smoother distance lighting) is a deferred fidelity option; flat-shaded (no colormap) is the fallback tier.
- **D12 — Test granularity.** *RESOLVED → **bit-exact (sha256)** against an exact-integer reference model.* The reference model (H5) replicates our exact integer pipeline (fixed-point truncation, LUT values, colormap select/apply), so rendered frames must match byte-for-byte (sha256 equality — `ScreenIO` logs this hash per present) and sim state (pos/angle) must match exactly. Any diff = a real bug. Golden set: a small curated set (spawn + movement waypoints + near-wall), grown as features land; scripted key-event demos for E2E. Obligation: the reference model mirrors every integer detail.
- **D13 — Fixed-point intermediates.** *RESOLVED → **full 2n-nibble-width product** (PR #1's `hex.fixed_mul` approach is the standard).* Overflow-safe: compute the product at 2n nibbles, nibble-aligned fraction shift (no runtime-amount shift, U6), truncate to n. `@Assumes 0 < f <= n`. Narrow-intermediate optimization is opt-in per-call later only if a hot mul demands it.
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
- **H2 — LUT/dispatch generator** (from PR #1, upgraded) — emits **dispatch-code tables** (§3.2): **per-entry handlers as default** (D4), per-result-nibble as a per-table override, plus the legacy data tables (`generate_lut_fj`/`generate_byte_lut_fj`) and the custom +4-offset deposit table (D3). Alignment-aware (pow2 padding → span ledger). Each generated table emits a host-reference fixture for its per-table test. *Fields: TBD — this is the S5.1 generator upgrade.*
- **H3 — Map compiler** — WAD level → baked `.fj` BSP structures (NODES / SSECTORS / SEGS / SECTORS / SIDEDEFS / LINEDEFS / VERTEXES) walked as sequential streams by F5. *Fields: TBD — D1 resolved (BSP); layout via D10.*
- **H4 — Texture/colormap compiler** — D5's output format. *Fields: TBD — D5.*
- **H5 — Reference model** — host-side (Python) golden implementation of *our exact integer* renderer + sim. **Bit-exact obligation (D12):** must reproduce every fixed-point truncation, LUT value, and colormap select/apply so its frame sha256 == the fj program's frame sha256, and its sim state == the fj sim state, exactly. Drives golden-frame + E2E diffing. *Fields: TBD.*
- **H6 — Build system** — assemble pipeline (w=32, `--flat-max-words`, `--werror`), script/Makefile, CI. *Fields: TBD.*
- **H7 — Test harness** — headless replays, golden-frame compare, per-table runner, ops-budget profiler. *Fields: TBD.*

### FJ-side (the game program)
- **F1 — Memory map / layout module** — the address plan; has invariants and tests. *Fields: TBD — D10.*
- **F2 — Fixed-point math layer** — `fixed_point.fj` (PR #1): `fixed_mul`/`fixed_div` (full 2n-width product, D13) + `mul_const` (strength-reduced) + `read_table`/`read_table_byte` (pointer fallbacks). Default 16.16 (D6); 8.8 only per the precision ledger. `hex.scmp` for anything signable (§3.5). *Fields: partly specified by PR #1.*
- **F3 — LUT access layer** — the dispatch-jumper idioms, one per table family (finesine/finecosine, reciprocal/scale, yslope, viewangletox/xtoviewangle, colormaps). **Includes the custom +4-offset 256-entry nibble table** used by F4's packed-byte deposit (D3). *Fields: TBD — D2/D4.*
- **F4 — Framebuffer + pixel-store layer** — D2/D3's resolved design. **Invariant: the framebuffer is WRITE-ONLY during rendering** (color comes from textures + colormap + per-column scratch, never from a framebuffer read-back; the only classic-DOOM framebuffer readers — fuzz/spectre, translucency — are out of scope). Consequence: the cell encoding is chosen purely on *(device match) + (write/deposit cost)*; hex.vec offers no computational benefit, only a ~2×-cheaper deposit at 16 colors. Pairs with U10 ("no clear": every pixel written exactly once per frame, ceiling→wall→floor, no gaps). *Fields: TBD — D2/D3.*
- **F5 — Renderer** — BSP front-to-back walk (D1), wall column renderer, floor/ceiling spans/visplanes, sprite renderer (flag-gated, D7), lighting/colormap point (D11). R2 ships walls + floors/ceilings textured. *Fields: TBD.*
- **F6 — Game loop & tic** — tic:render 1:1 (D9): poll → update `keydown[]` → sim tic → render → present, every frame. R2 sim = S0 (turn / move / wall-slide collide). Doors/specials (S1), entities/AI (S2, §D), combat, level transitions all flag-gated (D7). *Fields: TBD.*
- **F7 — Present layer** — drives the screen device over the output stream. **Device contract (read from `ScreenIO.py`, authoritative):**
  - `[0x01][w:2][h:2][bpp:1][palette_size:2]` init (bpp ∈ {4,8}); `[0x02][palette_addr:w/8]` set_palette; `[0x03][screen_addr:w/8]` update_screen (primary present, memory-hook read, ~free); `[0x04][x,y,rw,rh:2 each][screen_addr:w/8]` update_rectangle (reads the *full-screen* base with screen stride — for status-bar/menu rects only); `[0x05]` raw in-stream pixels — **don't use**.
  - **Framebuffer:** pixel `(px,py)` = packed byte at `screen_addr + (px + py·W)·dw`, masked to bpp bits. One byte per fj-op, stride `dw`, row-major.
  - **Palette:** entry `k` = 3 packed bytes R,G,B at `palette_addr + 3k·dw`.
  - Headless backend writes one PNG per present to `frames_dir` + a sha256 frame-hash log (golden tests; measured fps from present timestamps). *Fields: TBD.*
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
