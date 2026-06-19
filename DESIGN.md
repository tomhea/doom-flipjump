# DOOM-on-FlipJump — Design Document

> **Status: Stage 1 (Design) — DRAFT COMPLETE, awaiting owner review.** All decisions D1–D13 resolved
> (D14/D15 deferred to Stages 3/5); all components H1–H7 / F1–F9 fleshed to the §5 template; ledgers
> seeded (concrete spans/ops filled by R0/R1 measurement). Next: owner review → Stage 2 contradiction hunt.
> Built iteratively through owner Q&A per the
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
**Stretch:** 320×200 @ 25 fps textured — **no speculation tier** (we won't use it). Reachable instead if flat-run + the §2.1/§3 optimizations push the engine to **~400M+ fj/s**; revisit once R2's measured ops/frame are in. Not a dependency.
**Fallbacks:** 160×100 flat-shaded · 160×100 textured @ 12.5 fps · flat→paged storage.

**Budget:** ~280M fj/s (measured flat, native engine) ÷ 25 fps = **~11.2M fj-ops / frame.**

### 1.1 Ops-per-frame ledger (must sum < 11.2M with stated margin)

Seeded from handoff §2 (estimates — **R-1**: measured at S5.3/R1 before R2 commits). Each component
below adds/refines its own line as the design firms up.

| Line | Component | Per-frame cost (est.) | Technique | Settled by |
|---|---|---|---|---|
| Pixel stores (16K px, packed-byte deposit ≈ 2 dispatches/px, static) | F4 | ~1.0M (measured proxy ~63 ops/byte; R1 confirms) | static stores §3.1, D3 deposit | D2/D3/R1 |
| Texture + colormap reads (16K × ~100–200, dispatch-LUT) | F3/F5 | ~1.6–3.2M | dispatch-LUTs §3.2 | D5/D11 |
| Column math (160 cols) + BSP walk + S0 logic | F5/H3/F6 | ~1.5–3M | LUTs + adds, mul/div-free | D1/D6 |
| Present (`update_screen` 0x03 memory-hook) + input poll | F7 | ~negligible (~70 + tens) | — | — |
| **Total** | | **~5–7M of 11.2M (~2× margin)** | | |

### 1.2 Address-span ledger (must sum < chosen `--flat-max-words`; **R-3**)

Power-of-two dispatch-table padding inflates the span — lay out **largest-alignment-first** (§3.3) and
sum padding here, don't discover it. **OPEN — D10** (concrete memory map). Default flat limit = 2²³ words
(64 MB); raise via `--flat-max-words` / `FLIPJUMP_FLAT_MAX_WORDS` if needed (cost = RAM + ~0.1 s/GB fill,
zero per-op cost). Assert `storage_mode == flat` in the harness. Very-hot tables may be **over-aligned** by one bit (§2.1) — count the extra padding here.

| Segment / table | Size formula (ops) | Align pad | Span (R0-filled) | Notes |
|---|---|---|---|---|
| hex.init truth tables | ~fixed (or/and/mul/cmp/add/sub) | — | TBD | from `stl.startup_and_init_all` |
| Unrolled renderer code (D2b) | ~16K px × stub size + 160 col × col-setup | — | **TBD (R-2 watch)** | the big code consumer; assemble time tracked |
| Texture dispatch table(s) (D5) | pow2 ≥ Σ texel counts | pow2 pad | **TBD (OQ8 watch)** | likely largest table → placed first |
| Trig (finesine; cos = offset; tangent/viewangle) | **N=4096=16³** (top 3 nibbles, no shift §2.1; per-result-nibble, D4) | 16³-aligned | TBD (~0.25MB if 4096×8-nibble) | cosine shares the sine table (+N/4 = single-hex add); 256 = coarse fallback |
| Reciprocal / scale | pow2 ≥ entries | pow2 pad | TBD | replaces divides |
| yslope · viewangletox/xtoviewangle | pow2 ≥ entries | pow2 pad | TBD | |
| Colormaps (D4 handlers) | pow2 ≥ 256·#maps, byte results | pow2 pad | TBD | per-column-selected (D11) |
| +4-offset deposit table (D3) | 256 | pow2 pad | ~256 | |
| Framebuffer | W·H = 160·100 = 16,000 | — | 16,000 | packed bytes, no align |
| Palette | 256·3 = 768 | — | 768 | |
| Map/BSP streams | Σ lump sizes (E1M1) | — | TBD | sequential |
| State/scratch registers | small fixed set | — | TBD | hex.vec |
| **Total** | | | **TBD < 8.4M (R0)** | else raise `--flat-max-words` |

### 1.3 LUT inventory & total entry count

Every runtime LUT with its **logical entry count** (the index range). Result-width and pow2/over-align
padding feed the §1.2 *span* ledger separately. STL infra (`hex.init` truth tables) is flipjump's own,
listed apart. `W=160, H=100`; trig `N=4096=16³` (§2.1). *PENDING* = a sizing decision being consulted.

| LUT (component) | index domain | #entries | result | tier | notes |
|---|---|---|---|---|---|
| finesine (cos = `+N/4` offset) | angle top-3-nibbles | 4096 | 32-bit | R2 | 16³ (#10); per-result-nibble (D4) |
| tantoangle | slope → angle (R_PointToAngle) | 2048 | angle | R2 | DOOM SLOPERANGE; R1 may refine |
| viewangletox | view-angle → column | 2048 | 8-bit | R2 | FINEANGLES/2 at N=4096 |
| xtoviewangle | column x → angle | 161 | angle | R2 | W+1 (pad 256) |
| distscale | column x | 160 | 16.16 | R2 | fisheye 1/cos (pad 256; may fold) |
| yslope | row y | 100 | 16.16 | R2 | floor/ceiling distance (pad 128) |
| reciprocal / scale | distance | 4096 | 16.16 | R2 | 16³ buckets; kills the wall divide |
| colormap | (light, texel) | **L×256** | byte | R2 | **L PENDING**; per-pixel, over-align #3 |
| +4-offset deposit | (old,new) hi-nibble | 256 | flips | R2 | D3 |
| textures (wall+flat) | texel position | **T** | byte | R2 | **T PENDING** (D5/OQ8 — dominates) |
| palette (device data) | index | 256 | 3 bytes | R2 | data, not a dispatch LUT |
| P_Random `rndtable` | rndindex | 256 | byte | R3 | excluded from the R2 total |
| — *STL infra*: `hex.init` | — | ~6×256 (+ mul) | — | infra | flipjump's own; counted apart |

**R2 subtotal** (all fixed-size LUTs, *excl.* colormap `L` and textures `T`): 4096+2048+2048+161+160+100+4096+256+256 = **13,221 entries.**
**Unified R2 total = 13,221 + L×256 + T** — finalized once `L` (colormap levels) and `T` (texture texels) are set below.

- **fj-op** — one assembled FlipJump op (flip-word + jump-word = `dw` bits). The budget unit.
- **`@`** — the per-op cost constant (~27 at w=32); grows with total program size (**U7**). A figure in
  `@` is *not* comparable to a raw-ops figure without conversion (contradiction-hunt §6).
- **w / dw / dbit** — word width (=**32**, confirmed: 16.16 fits one word) / `2w` (one op) / `w` (data-bit offset).
- **nibble / hex / byte** — a `hex` = 4 data bits; a packed byte = 8 data bits in one op; register-form byte = two `hex` ops (low, then `+dw`). The two byte encodings do **not** interchange (see flipjump-dev skill).
- **Fixed-point** — Q-format: 16.16 = `n=8,f=4`; 8.8 = `n=4,f=2`. Signed; compare with `hex.scmp`, never `hex.cmp` (§3.5).
- **Static store** — a framebuffer write to a *compile-time-known* address (~7@), vs a runtime-address pointer write (~500–1300 ops).
- **Dispatch-LUT** — the `hex.xor`-jumper table idiom (`tables_init.fj`): ~10@/lookup, 10–30× cheaper than `read_table`. One dispatch sets a *fixed-address* hex = a *runtime* value (indexes on the current nibble), so it is the pointer-free deposit primitive.
- **`P_Random` / determinism** — the game uses **no true RNG**. DOOM's "randomness" (combat/AI, R3+) is a deterministic 256-byte `rndtable` + advancing `rndindex` — a byte-LUT. The whole game is deterministic, which is *required* by D12 (bit-exact + replay). R2 uses no randomness at all.
- **Cell width ⊥ pointer-freeness** (key D3 insight) — "packed byte" (8-bit cell, forced by bpp=8/256-color + the device read) is the framebuffer *cell width*; "pointer-free" is whether the *address* is compile-time-known (delivered by D2(b) full-unroll). Orthogonal: a packed-byte framebuffer can be written entirely by fixed-address stores. The runtime-value→fixed-address deposit cost scales with bits — a byte ≈ 2× a nibble — so bpp=4/hex.vec is the ~2×-cheaper-deposit / 16-color cost-fallback.

## 2.1 Cross-cutting build techniques

- **Dependency policy — flipjump 1.5.0 is near-frozen, but *extensible*.** Default: build only on stock 1.5.0; **no speculation tier** (we won't use it). If a device/engine change would *materially* help and stock-1.5.0 designs are exhausted, we **can** ship a tested `fj==1.5.1` — a deliberate, justified, last-resort lever, not a default (strong preference: don't). Candidate extensions, *only if measured to win*: a ScreenIO mode reading **two 4-bpp ops as one 8-bpp pixel** (would make a `hex.vec 2` framebuffer device-direct — reopens D3's rejected option); a **column-major bit-input stream** matching the program's compute order; a **device-side fps cap** (D9).
- **16^x-sized shift-indexed LUTs (U6+).** When the index is *derived by shifting* a value (angle→sine: shift, then jump), size the table to a power of **16** (nibble-aligned entry count) so the index lands on nibble boundaries and **no runtime/sub-nibble shift is needed** (saves space + time). E.g. trig N = **4096 = 16³** (top 3 nibbles), not 8192 (2¹³, a 19-bit shift). Applies to every shift-indexed dispatch-LUT.
- **Over-align very-hot dispatch-LUTs.** Align a hot 2ⁿ-entry table to 2ⁿ⁺¹ so the top alignment bit is always 0 → the jumper's `wflip` round-trip skips it (~0.5 op each way, ~1 op/lookup saved). Worth it **only** for per-pixel/per-column-hot tables (colormap, texture, deposit) — the 2× padding isn't worth it for cold tables (track in the span ledger).
- **Call discipline — tiered `fcall`/`fret`, avoid the stack.** Prefer `fcall`/`fret` over `stl.call`/`return` (~2.5w@ + stack). A **non-leaf** function may `fcall` another using a **distinct `ret_reg` per call-graph level** (`ret_L0`, `ret_L1`, …) — so any *bounded, non-recursive* depth is stackless (**OQ9 resolved**). Reserve the stack for *genuine unbounded recursion*, and even there push it down the tree (F5's BSP walk takes its bottom levels stackless).

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
      stack              (minimal — tiered fcall/fret is stackless §2.1; stl.stack only for the BSP walk's upper levels, F5)
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
- **D4 — Per-table dispatch shape.** *RESOLVED → **per-entry handlers (default)**; per-result-nibble as a per-table override.* Per-entry handler = 1 dispatch + popcount flips (≈4@+2W ops) — ~7× faster than per-result-nibble (W dispatches ≈ 4W@) for wide results, ~2× for a byte. Chosen because ops/frame is the scarce resource and the per-pixel colormap benefits most. **Cost it carries:** a more complex generator (custom per-entry flip code) and ~2–3× table space on wide tables (feeds **R-3** span). **Override:** large *cold* tables (e.g. trig) may use per-result-nibble to save span if the span ledger tightens — recorded per-table in the span ledger + the table's test. Both fit the shared `res`/`ret` machinery (handler XORs `value[k]` into `res`, caller `xor_zero`s out). **Construction (#5):** an over-alignable (`pad 2ⁿ`) `switch:` jump table (`;arg_k` per entry); each `arg_k:` does `hex.set` of the entry's compile-time value into the pre-zeroed result reg and **cleans the jumped switch-op from within the table** (like stl's `clean_table_entry`) — saving the external xors (space + time).
- **D5 — Texture storage.** *RESOLVED → **dispatch-LUT textures**.* Textures baked as aligned dispatch table(s); per-pixel texel sample = ~10@ dispatch (not ~1000-op `read_table`). Per column the source column is fixed (selected once, amortized); per pixel the index = per-column base + texel (`frac>>FRACBITS`, a compile-time shift) — an add, nibble-aligned, no runtime shift (U6). **Span (texel count rounded to pow2, OQ8) is the open risk — measured in R0/R1**; fallbacks: sequential packed-byte streams, fewer/smaller textures. R2 bound to E1M1's real textures (downscale if the span ledger demands). Entry shape per D4.
- **D6 — Precision per quantity.** *RESOLVED → **16.16 default, drop to 8.8 only with evidence**.* Every quantity is 16.16 (DOOM-faithful, correctness-first) unless a **per-quantity precision ledger** records a justified 8.8: justification = profiling shows the cost is material **and** the reference-model diff (OQ5) confirms acceptable wobble. The mostly-LUT'd hot path + ~2× margin make this low-risk.
- **D7 — Feature scope at 160×100.** *RESOLVED → first playable (R2) = **textured 3D view (walls + floors/ceilings) + S0 walk/collide**, auto-warp into the level.* Flag-gated for R3+: S1 doors+hitscan, S2 sprites/enemies, HUD/status bar, menus, text, demo playback. Rationale: prove the renderer + the §1.1 budget (the hard part) first; matches the §8 ladder. The compositor/pass pipeline and `blit_rect`/glyph API (§E, F8) are **stubbed flag-gated from day one** so later passes drop in without touching the 3D core.
- **D8 — Maps & assets.** *RESOLVED.* **Asset source:** shareware `doom1.wad` for development; **Freedoom** WADs for anything redistributed (CI fixtures / golden frames). **Map ambition:** R1 renderer bring-up + measurement on a small (hand-built or smallest real) BSP map to keep the assemble/span/measure loop fast; **real E1M1 is the R2 target.** Entity counts: deferred to D7's S2 tier (sprites flag-gated; not in R2).
- **D9 — Frame pacing.** *RESOLVED → **tic:render 1:1, budget-bound**.* One input poll = one tic = one rendered frame. There is no timer device (§1.1), so the program cannot self-pace to wall-clock time; "25 fps" = "hold ops/frame < 11.2M so the native engine *delivers* ~25 fps on the reference machine." Accept and **report** the measured wall-clock fps (present-log). Sim/render decoupling (render 1-of-N tics, G21) is a deferred hedge, not built in R2. **If frames run too fast** (likely on the native engine): wall-clock pacing can't be done in-program (no timer); the clean fix is a **device-side fps cap** — the screen device sleeps on present if too little wall-time elapsed ("aim for X fps"). Verified *not* in the stock pygame device ⇒ a candidate `fj==1.5.1` device extension (§2.1). R2: run uncapped + report fps; add the cap for a playable interactive build.
- **D10 — Memory map.** *RESOLVED (structure) → see §3 + the §1.2 span ledger.* Largest-alignment-first: hex.init tables → unrolled renderer code → pow2-aligned dispatch tables (texture first, then trig/recip/yslope/viewangle/colormaps/+4-offset) → `stl.loop` → framebuffer / palette / map streams / scratch / stack. Concrete spans filled by R0; flat-limit invariant guarded by the span ledger + `storage_mode` assertion.
- **D11 — Colormap/lighting application point.** *RESOLVED → **per-column/span SELECT, per-pixel APPLY**.* The colormap (light level) is chosen once per column (walls) / per span (floors) — DOOM-faithful, ~160×/frame; it is then applied per pixel as a dispatch chained off the texel sample (texel → lit palette byte). Avoids the U9 trap (per-pixel light *recomputation* / pointer-read colormap, ~6M+/frame) while keeping correct per-pixel colormap application. Per-pixel light *recomputation* (smoother distance lighting) is a deferred fidelity option; flat-shaded (no colormap) is the fallback tier.
- **D12 — Test granularity.** *RESOLVED → **bit-exact (sha256)** against an exact-integer reference model.* The reference model (H5) replicates our exact integer pipeline (fixed-point truncation, LUT values, colormap select/apply), so rendered frames must match byte-for-byte (sha256 equality — `ScreenIO` logs this hash per present) and sim state (pos/angle) must match exactly. Any diff = a real bug. Golden set: a small curated set (spawn + movement waypoints + near-wall), grown as features land; scripted key-event demos for E2E. Obligation: the reference model mirrors every integer detail. **Determinism is load-bearing:** the game uses no true RNG (DOOM's `P_Random` is a deterministic 256-byte table, §2 glossary / F6), so golden frames and replays are reproducible. **LUT test mandate (#8):** every generated LUT is tested on **every entry** (not just samples/boundaries) **and** with a **call-twice-per-entry** check (catches result-reg / in-table jumper-cleanup bugs from the #5 construction). Triple-check every table.
- **D13 — Fixed-point intermediates.** *RESOLVED → **full 2n-nibble-width product** (PR #1's `hex.fixed_mul` approach is the standard).* Overflow-safe: compute the product at 2n nibbles, nibble-aligned fraction shift (no runtime-amount shift, U6), truncate to n. `@Assumes 0 < f <= n`. Narrow-intermediate optimization is opt-in per-call later only if a hot mul demands it.
- **D14 — Directory tree.** *Deferred to Stage 3.*
- **D15 — PR #1 CR surface.** *Deferred to Stage 5 / S5.0.* API/naming/test-style changes to `fixed_point.fj` + LUT generator.

---

## 5. Testing strategy (the pyramid)

Per handoff §H / §3.5. Top to bottom:

1. **Host unit tests (Python)** — WAD parser, LUT/dispatch generator, map/texture compilers, reference model. `pytest`.
2. **Per-macro fj tests** — TDD, `--werror`, byte-exact via `flipjump.assemble_and_run_test_output`, **a boundary input per behavior path** (single green fixture proved insufficient 3× in the catalog), `hex.scmp` for anything signable.
3. **Per-table generated tests** — each generated `.fj` table diffed vs a host reference on **every entry** (not just samples) **and** a **call-twice-per-entry** check (#8: result-reg/jumper cleanup); over-aligned variants too.
4. **Golden-frame renderer tests** — headless `PcIO.headless(events_file, frames_dir)` / `InMemoryScreen`; hash + diff `SCREEN→PNG` vs host reference.
5. **Headless scripted-replay E2E** — scripted key-event file drives movement/collision/fire; player state must match the reference exactly; measured fps (present-log) meets the tier.

**Tracked metrics from the first renderer experiment:** ops/frame (`--profile`/featured loop on small builds) **and** assemble time **and** `.fjm` size.

---

## 6. Component inventory

> Per-component template (§5): **Purpose · Supplies · Depends/related · Assumes · Data & layout ·
> Time · Space · Testing · Open Qs.** Host components are one-time build tools (no fj-op budget);
> fj components carry the runtime budget. Init order is called out under **Assumes** (contradiction-hunt §6).

### Host-side (Python, doom-flipjump repo)

#### H1 — WAD parser/extractor
- **Purpose:** Read a DOOM WAD and expose the level lumps + assets the compilers and reference model need.
- **Supplies:** `parse_wad(path) -> WAD`; typed accessors for VERTEXES/LINEDEFS/SIDEDEFS/SECTORS/SEGS/SSECTORS/NODES/THINGS and PLAYPAL/COLORMAP/TEXTURE1+PNAMES+patches/flats (sprites later, S2).
- **Depends/related:** none upstream; consumed by H3, H4, H5.
- **Assumes:** valid IWAD/PWAD; shareware `doom1.wad` (dev) / Freedoom (redistributable) — D8.
- **Data & layout:** host structures only; no span.
- **Time / Space:** host, one-time; negligible.
- **Testing:** unit-test lump offsets/counts + a few round-tripped records against `doom1.wad`/Freedoom fixtures; boundary (empty/odd-size lumps).
- **Open Qs:** THINGS/sprite extraction scope (→ S2/D7).

#### H2 — LUT/dispatch generator (PR #1, upgraded — the S5.1 work)
- **Purpose:** Emit `.fj` lookup tables: dispatch-code tables (per-entry handlers default, D4) + per-result-nibble override + legacy data tables + the D3 +4-offset deposit table.
- **Supplies:** `generate_dispatch_table_fj(label, values, mode, entry_nibbles, …)`, `generate_offset_deposit_table_fj(...)`, and PR #1's `generate_lut_fj`/`generate_byte_lut_fj`/`generate_reciprocal_lut_fj`/`generate_sine_lut_fj`/`encode_fixed_point`. Every emitter also returns a host-reference fixture for the per-table test.
- **Depends/related:** extends PR #1 `lut_generator.py`; consumed by H4 and the trig/recip/yslope/viewangle builds; output assembled into the program.
- **Assumes:** indices nibble-aligned (U6); pow2 alignment declared per table; values fit entry width; `hex.init` present at runtime for the dispatch machinery.
- **Data & layout:** generated tables = pow2-aligned dispatch CODE (→ §1.2 span ledger); alignment-aware emit, **over-aligns very-hot tables** (§2.1); per-entry handlers use the **#5 `switch`+`hex.set`+in-table-clean** construction; **16^x sizing** for shift-indexed tables.
- **Time:** host build; per-entry codegen O(entries × popcount).
- **Space:** emitted `.fj` size feeds **R-2** (assemble time) + the span ledger; per-entry ~2–3× per-result-nibble on wide tables.
- **Testing:** per-table generated tests (D12, bit-exact): **every entry** + a **call-twice-per-entry** check (#8 — verifies result-reg/jumper cleanup), both emit modes, over-aligned and not.
- **Open Qs:** texture-table span (OQ8); the per-table mode heuristic (D4 override).

#### H3 — Map compiler
- **Purpose:** Compile a WAD level into baked `.fj` BSP structures the fj renderer walks.
- **Supplies:** `compile_map(wad, level) -> .fj` emitting NODES/SSECTORS/SEGS/SECTORS/SIDEDEFS/LINEDEFS/VERTEXES as sequential packed streams + the root-node entry point.
- **Depends/related:** H1; consumed by F5; mirrored by H5.
- **Assumes:** D1 = BSP; 16.16 coords (D6); coords fit w=32; F5 reads streams with `*_and_inc` (§3.4).
- **Data & layout:** sequential streams in the data region (no pow2 align); span = Σ lump sizes (§1.2).
- **Time / Space:** host build; stream span filled R0 (E1M1).
- **Testing:** unit-test compiled structures vs parsed WAD (counts + sample records); the walk validated by golden frames (D12).
- **Open Qs:** BSP traversal cost at E1M1 scale (R1); which seg/sidedef fields are actually needed.

#### H4 — Texture/colormap compiler
- **Purpose:** Compile WAD textures/flats + COLORMAP/PLAYPAL into the dispatch tables F3 reads + the palette F7 sends.
- **Supplies:** `compile_textures`, `compile_colormaps`, `compile_palette` → `.fj` (via H2).
- **Depends/related:** H1, H2; consumed by F3/F5 (sampling + lighting), F7 (palette).
- **Assumes:** bpp=8 packed indices (D3); per-column-selected colormaps (D11); texel indices nibble-aligned (U6).
- **Data & layout:** pow2-aligned dispatch tables; texture table likely largest → placed first (D10).
- **Time / Space:** host build; **texture span = OQ8 risk** (R0/R1); downscale/reduce count if the ledger demands.
- **Testing:** per-table generated tests (sample == WAD texel; colormap[light][texel] correct); palette round-trip; bit-exact.
- **Open Qs:** texture count/resolution vs span (OQ8); flats rendered as spans.

#### H5 — Reference model
- **Purpose:** Host-side **exact-integer** golden renderer + sim — the test oracle (D12).
- **Supplies:** `render_frame(state) -> palette-index bytes`, `step_sim(state, keys) -> state`.
- **Depends/related:** H1/H3/H4 (same data); compared against the program in H7.
- **Assumes:** reproduces every integer detail — fixed-point truncation, LUT values, colormap select/apply, BSP walk order — so frame sha256 and sim state match the program exactly.
- **Data & layout / Time / Space:** host only.
- **Testing:** it *is* the oracle; sanity-seeded against hand-computed values + a known reference frame, then trusted.
- **Open Qs:** keeping it in lockstep as the fj pipeline evolves (a standing maintenance discipline).

#### H6 — Build system
- **Purpose:** One pipeline: run generators/compilers → assemble → `.fjm`; plus CI.
- **Supplies:** a build script (Python/Make) (`w=32`, `--werror`, `--flat-max-words` as needed) + CI config.
- **Depends/related:** all H*; flipjump 1.5.0 (near-frozen but extensible — §2.1 dependency policy).
- **Assumes:** w=32; flat path; `--werror` clean.
- **Data & layout:** produces the `.fjm`; reports the span ledger.
- **Time / Space:** **assemble time + `.fjm` size are tracked metrics** (R-2).
- **Testing:** CI runs host unit + fj-macro + per-table + golden + replay tests; asserts `storage_mode == flat`; records assemble time / `.fjm` size / ops-frame.
- **Open Qs:** assemble time at game scale (R-2) — measured S5.1/S5.3.

#### H7 — Test harness
- **Purpose:** Headless replays, golden-frame compares, per-table runs, ops profiling.
- **Supplies:** wrappers over `assemble_and_run_test_output` / `run` + `FixedIO` / `InMemoryScreen` / `PcIO.headless`; sha256 golden compare vs H5; per-table runner (#8: every-entry + call-twice). **Profilers:** `--profile` (run) = per-region op-count / *time*; `--stats` (assemble) = macro *code-size*/usage — textual **only if plotly is absent** (it currently IS, 5.17.0 → the build/CI env must uninstall plotly for textual output).
- **Depends/related:** flipjump APIs, H5 (oracle).
- **Assumes:** deterministic runs; bit-exact (D12); scripted key-event files for E2E.
- **Data & layout:** fixtures (golden frames, event scripts, table fixtures) in-repo (Freedoom-derived where redistributable).
- **Time / Space:** CI cost.
- **Testing:** harness self-checked on a trivial program.
- **Open Qs:** **verify `PcIO.headless(events_file, frames_dir)` exists + its signature** — `InMemoryScreen` is screen-only (no input); input+screen headless replay needs `PcIO.headless` (handoff §1.1). Confirm in S5.2.

### FJ-side (the game program)

#### F1 — Memory map / layout module
- **Purpose:** The address plan (D10) as fj labels/constants + its invariants.
- **Supplies:** segment/label definitions, table-base constants, the largest-alignment-first ordering.
- **Depends/related:** consumed by all fj components; defines the span.
- **Assumes:** flat path; pow2 table alignment; w=32.
- **Data & layout:** *is* the layout (§3); span = §1.2.
- **Time:** n/a.
- **Space:** the whole span ledger.
- **Testing:** build asserts `storage_mode == flat` and span-sum < flat limit; alignment invariants checked.
- **Open Qs:** final spans (R0).

#### F2 — Fixed-point math layer (`fixed_point.fj`, PR #1)
- **Purpose:** Signed Q-format math: `fixed_mul`/`fixed_div` + `mul_const` + pointer-fallback table reads.
- **Supplies:** `hex.fixed_mul n,f,…`, `hex.fixed_div n,f,…,div0`, `hex.mul_const n,…,c`, `hex.read_table`/`read_table_byte` (fallbacks only).
- **Depends/related:** `hex.*` STL; consumed by F5/F6.
- **Assumes:** `0 < f <= n`; full 2n-width product (D13); default 16.16 (D6); `hex.init`; `hex.scmp` for signables (§3.5).
- **Data & layout:** scratch `hex.vec` in F1's register region.
- **Time / Space:** per PR #1's documented complexities (e.g. `fixed_mul` ≈ 4n²(5.5@+20)+…); div is expensive ⇒ **LUT it in hot paths**, never call per pixel/column.
- **Testing:** PR #1's byte-exact tests (boundary inputs per path) — re-homed + CR'd in S5.0 (D15).
- **Open Qs:** narrow-intermediate opt (D13) only if a hot mul needs it.

#### F3 — LUT access layer
- **Purpose:** The dispatch-jumper idioms that read the generated tables, one per family, + the packed-byte deposit primitive.
- **Supplies:** `sample_texture`, `read_trig`, `read_reciprocal`/`read_scale`, `read_yslope`, `read_viewangle*`, `apply_colormap`, `deposit_pixel_byte` (D3: low-nibble std + high-nibble +4-offset table). Per-entry-handler dispatch (D4).
- **Trig / angle quantization (NOT 2³² entries):** index by the **top nibbles** of the 32-bit BAM angle, sized **N = 4096 = 16³** (top 3 nibbles — *no sub-nibble shift*, §2.1 16^x rule); 16² = 256 is the coarse span fallback. Multi-nibble index: xor each index nibble into the jumper at offset `4i+6` (`dw=2⁶`), then jump — generalizes the single-nibble `tables_init.fj` idiom. **Cosine shares the sine table** at `(idx + N/4) & (N-1)`, and the `+N/4` (=+1024=0x400) is a **single-hex add** (+4 to nibble 2), ~free — so a *separate* cosine LUT (≈+span) is **not** worth it (#9; revisit only if profiling disagrees). `finetangent`/`viewangletox`/`xtoviewangle` quantize the same way. Trig is **per-column** ⇒ the canonical **per-result-nibble override (D4)** site for its 32-bit entries. Optional **quadrant fold** (N/4 + sign/reflect) = 4× smaller, deferred lever. The very-hot per-pixel tables (colormap/texture/deposit), not trig, are the **over-align** candidates (§2.1).
- **Depends/related:** H2/H4 tables; consumed by F4/F5.
- **Assumes:** indices nibble-aligned without runtime shift (U6); tables init'd before first use; shared `res`/`ret`.
- **Data & layout:** reads code-region tables; owns the +4-offset 256-entry table.
- **Time:** ~10@/dispatch (per-pixel sample+colormap; per-column trig/recip) — feeds the texture-read + column-math budget lines.
- **Space:** small idiom code + the +4-offset table.
- **Testing:** per-idiom byte-exact vs host reference; boundary/wrap indices.
- **Open Qs:** OQ9 (`fcall` nesting if idioms chain > 1 level).

#### F4 — Framebuffer + pixel-store layer
- **Purpose:** The packed-byte framebuffer (D3) + the full-unroll static deposit (D2b).
- **Supplies:** `framebuffer` base; `render_column x` (unrolled, fixed addresses); the deposit (via F3).
- **Depends/related:** F3 (deposit table), F1 (layout); consumed by F5 (writes), F7 (present reads base).
- **Assumes:** **write-only during render** (invariant); bpp=8 packed byte; **no clear** (U10 — every px written once, ceiling→wall→floor, no gaps); fixed compile-time addresses (D2b).
- **Data & layout:** framebuffer = W·H = 16K packed-byte ops (data region).
- **Time:** deposit ≈ 2 nibble dispatches. **Measured proxy (`hex.mov 2`, w=32) ≈ 63 ops/byte** → ~1.0M for 16K px — validates the ~1.3M est (and far below an earlier ~216-op guess). A custom mov-table (set fixed hex = runtime value in 1 dispatch/nibble, vs `hex.mov`'s zero+xor) could cut it further — R1.
- **Space:** 16K-op framebuffer + the unrolled column code (**R-2** watch).
- **Testing:** deposit byte-exact incl. the high nibble; golden frames.
- **Open Qs:** D2 final (a vs b) settled by R1; deposit cost (R-1).

#### F5 — Renderer
- **Purpose:** BSP front-to-back walk (D1) → textured wall columns + floor/ceiling spans, lit (D11), into the 3D-view rect.
- **Supplies:** `render_3d_view` (the §E pass), `draw_column`/`draw_span` (body chosen by the `TEXTURED` flag).
- **Depends/related:** H3 (map), F3 (LUTs), F4 (framebuffer), F2 (math); first pass of the §E pipeline.
- **Assumes:** front-to-back no-overdraw (upholds U10); per-column colormap select (D11); scale via reciprocal LUT (**no runtime divides**); 16.16 (D6); `hex.scmp` on signed deltas.
- **Data & layout:** per-column scratch (top/bottom/colormap-sel) in fixed registers; reads map streams sequentially.
- **Time:** column math + BSP walk ~1.5–3M — the dominant consumer alongside stores/reads.
- **Space:** unrolled column code (**R-2**); visplane + clip arrays.
- **Testing:** golden frames vs H5 (bit-exact); per-column math unit checks.
- **Call discipline (#4/#11):** the BSP walk recurses, but **don't pay `stl.call`/`return` for most of it.** Use **tiered `fcall`/`fret`** (distinct `ret_reg` per level, §2.1) for the **bottom ~3 tree levels** — the bulk of node visits (~7/8 of a balanced tree) — and reserve the stack for the upper, unbounded-depth levels only. This strips the ~2.5w@ stack cost off most visits (big speedup). Per-column/per-pixel leaf bodies stay `fcall`-stackless.
- **Open Qs:** OQ4 (does column math fully reduce to LUTs+adds? R1); visplane + clip-array design.

#### F6 — Game loop & tic
- **Purpose:** The 1:1 loop (D9): poll → update `keydown[]` → S0 sim → render → present, every frame.
- **Supplies:** `main_loop`, `poll_input`, `sim_tic` (S0: turn / move / wall-slide collide), present call.
- **Depends/related:** F7 (poll/present), F5 (render), F4; S1/S2 flag-gated (D7, §D).
- **Assumes:** no timer device — frame counter is the clock; tic:render 1:1; `keydown[]` in registers; signed deltas via `hex.scmp`. **Fully deterministic: no true RNG.** R2 (render + S0) uses no randomness at all. When combat/AI land (S1/S2, R3+) they use DOOM's deterministic `P_Random` — a hardcoded 256-byte `rndtable` + an advancing `rndindex` (`rndtable[++rndindex & 0xff]`) — emitted as a byte-LUT via H2, read via F3. This *preserves* D12 (a true RNG would break bit-exact golden frames + deterministic replay); H5 uses the same table + index so sequences match exactly.
- **Data & layout:** player state (pos/angle/eye) + `keydown[]` in fixed registers.
- **Time:** S0 ~few K ops/tic (cheap class: tile lookups, signed compares, adds).
- **Space:** small.
- **Testing:** scripted-replay E2E — sim state matches H5 exactly after a key sequence (D12); collision boundary cases.
- **Open Qs:** collision model (axis-separated slide, §D); S1/S2 scope (D7).

#### F7 — Present layer
- **Purpose:** Drive the screen device over the output stream (init/palette/present/input).
- **Supplies:** `init_screen`, `set_palette`, `present` (`update_screen` 0x03), input-poll helpers; `update_rectangle` (0x04) reserved for status-bar/menu rects.
- **Depends/related:** F4 (framebuffer base), H4 (palette); the device (below).
- **Assumes / Device contract (read from `ScreenIO.py`, authoritative):**
  - `[0x01][w:2][h:2][bpp:1][palette_size:2]` init (bpp ∈ {4,8}); `[0x02][palette_addr:w/8]` set_palette; `[0x03][screen_addr:w/8]` update_screen (primary present, memory-hook, ~free); `[0x04][x,y,rw,rh:2 each][screen_addr:w/8]` update_rectangle (reads the *full-screen* base with screen stride — status-bar/menu only); `[0x05]` raw in-stream — **don't use**.
  - **Framebuffer:** pixel `(px,py)` = packed byte at `screen_addr + (px + py·W)·dw`, masked to bpp. One byte/op, stride `dw`, row-major.
  - **Palette:** entry `k` = 3 packed bytes R,G,B at `palette_addr + 3k·dw`.
  - Keyboard (input side of `pc`): non-blocking, tic-based — one status poll (`0x0` none / `0x8` up / `0x9` down) then one keycode byte on events; keycodes ASCII-like `<0x80`, arrows/shift/ctrl/alt `0x80–0x86` (§1.1).
- **Present-path rationale — memory-hook (0x03) over raw-stream (0x05):** *decisive reason = render order ≠ scan order.* The raw stream demands W·H bytes in **row-major** order; DOOM/BSP renders **column-major + front-to-back** with overdraw and multi-segment columns, so pixels are produced out of scan order. The framebuffer decouples render order from scan order; 0x03 then scans out the finished buffer for ~free (~70 ops/frame). *Measured per-byte (w=32):* output ≈ **34 ops**, deposit ≈ **63 ops** — so raw output *is* ~2× cheaper per pixel, BUT that only helps if you emit directly row-major with **no** framebuffer (forfeits incremental `frac+=step` column sampling, and is impossible for multi-segment BSP columns). *With* a framebuffer (which BSP requires), 0x03 (deposit + ~70/frame) beats 0x05 (deposit + 34/px ⇒ +~0.5M/frame). So 0x03 is strictly better here.
- **Data & layout:** command bytes only; reads F4's framebuffer + H4's palette in memory.
- **Time:** present ~70 fj-ops/frame; poll ~tens — negligible.
- **Space:** negligible.
- **Testing:** headless backend → one PNG/present + sha256 frame-hash log (golden + measured-fps); command-stream byte checks.
- **Open Qs:** none open (contract is read from source).

#### F8 — HUD / status-bar / menu / text passes (flag-gated, stubbed in R2)
- **Purpose:** Overlay passes (§E) layered on the 3D view — API seams exist from day one (D7), bodies land R3+.
- **Supplies:** `blit_rect(src,dx,dy,w,h,[transp])`, `draw_string(x,y,ptr)`, pass hooks `render_statusbar`/`render_text`/`render_menu` — **stubs** in R2.
- **Depends/related:** F4 (framebuffer), F3 (glyph LUT / `hu_font`); §E compositor; `update_rectangle` for non-redrawn rects.
- **Assumes:** 3D view writes `(VIEW_X,VIEW_Y,VIEW_W,VIEW_H)`; overlays own the remaining rows (no coordinate retrofit); framebuffer-write-heavy ⇒ enabled only at tiers whose budget pays.
- **Data & layout:** glyph table + HUD graphics (flag-gated span).
- **Time / Space:** per-pixel writes like walls — gated off in R2.
- **Testing:** `blit_rect`/`draw_string` golden tests when enabled (R3).
- **Open Qs:** which overlays ship when (D7/R3).

#### F9 — Debug / diagnostics
- **Purpose:** Op-count probes, frame dumps, on-screen debug values (cheap at this budget).
- **Supplies:** probe macros; optional on-screen number print.
- **Depends/related:** F4/F7; used by H7's profiler.
- **Assumes:** compile-time-gated (off in release builds).
- **Data & layout / Time / Space:** minimal; gated off normally.
- **Testing:** exercised by the harness ops-budget profiling.
- **Open Qs:** which probes pay off most at R1.

---

## 7. Risks (handoff §10, live)

- **R-1** — Budget estimates are projections; S5.3 measures before R2 commits. Margin ~2×, not infinite. Fallbacks: flat-shaded / 12.5 fps.
- **R-2** — Assembler scalability is load-bearing (column-unroll + mega dispatch tables). Measure assemble time + `.fjm` size at game scale (S5.1/S5.3); relief valve = design (a) column buffer.
- **R-3** — Span vs flat path: power-of-two padding can silently overflow → paged (~2.5× slower). Guards: span ledger + `storage_mode` assertion.
- **R-4** — D3 encoding tension (hex-memory pixels vs packed-byte device read) — resolve in this doc, not in code.
- **R-5** — *(cleared)* flipjump 1.5.0 released. We use **no speculation tier**; the 320×200 stretch instead rides flat-run + our own optimizations toward ~400M+ (revisit at R2). flipjump is near-frozen but **extensible** (§2.1) — a device/engine change is a justified last-resort lever, not a dependency.
- **R-6** — Fidelity unknowns: 8.8 wobble (D6), 32×32→64 intermediates (U5/D13), `@` growth (U7) — survive re-baselining, now with more headroom.

---

## 8. Open questions (inherited, mapped to D-items)

OQ4 (does per-column math reduce fully to LUTs+adds? → D2/R1) · OQ5 (16.16 vs 8.8 wobble → D6) ·
OQ8 (map/texture dispatch tables small enough for compile+span? → D5/R-2/R-3) · OQ9 (`fcall`
non-reentrancy — any hot call chain > 1 nesting level? → R1 as the call graph forms) · OQ10 (variable
fps vs worst-case cap → D9).
