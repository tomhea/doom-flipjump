# DOOM-on-FlipJump — Design Document

> **Status: Stage 2 (Contradiction hunt) — COMPLETE, awaiting owner re-approval.** All decisions D1–D13
> resolved (D14/D15 deferred to Stages 3/5); all components H1–H7 / F1–F9 fleshed to the §5 template;
> ledgers seeded (concrete spans/ops filled by R0/R1 measurement). The handoff §6 checklist was run
> mechanically and adversarially; contradictions were fixed in-doc (load-bearing cost/device/macro
> claims **verified by assembling+running probes on stock flipjump 1.5.0**, not just reasoned). Next:
> owner re-approval → Stage 3 (directory tree).
> Built iteratively through owner Q&A per the
> [implementation handoff](doom_implementation_handoff.md) §4–§5. Every decision is recorded in the
> **Decisions** section below with an ID, rationale, and the measurement (if any) that settled it —
> not in chat. Part II of the handoff is *input* to this document, not settled design; where an item
> here is still undecided it is marked **OPEN** and tagged with the D-item that will close it.
>
> **No game code is written until this document is complete and approved (Stage 2 done).**

## Process gates (handoff §4)

1. **Stage 1 — this document.** Cover every component per the §5 spec. ✓ *done*
2. **Stage 2 — contradiction hunt.** Adversarial pass (handoff §6 checklist); fix in-doc; re-approve → *final document*. ← *we are here (awaiting re-approval)*
3. **Stage 3 — directory tree** (handoff §7).
4. **Stage 4 — iterative stage cutting** (handoff §8).
5. **Stage 5 — execution.** First item: CR-loop PR #1 into the Stage-3 tree (handoff §9), then execute.

---

## 1. Targets & budgets (living ledgers)

**Primary target (owner decision):** 160×100, **fully textured (walls + floors/ceilings)**, 256 colors. **fps is continuous, not a knob** — there is no timer (D9), so you *get* `engine ÷ ops/frame`, you don't *set* it. **Owner decision: full-res textured floors, accept ~20 fps** (a fps "knob" only exists as render-cost; see the fidelity/fps curve below).

**Floor-fidelity ↔ fps curve (all opts #1–9, @=25; walls always textured):**
| Floor mode | frame | ~fps | look |
|---|---|---|---|
| flat-colored floors | ~9M | ~30 fps | floors solid lit color |
| 2×2-block textured floors (perf toggle) | ~10M | ~27 fps | textured, half-res/blocky floors |
| **full-res textured floors (chosen)** | **~14M** | **~20 fps** | full DOOM look |

*Texture **size** ⊥ per-pixel **cost**: smaller flats (32²) save **span**, not fps — the per-pixel cost is the coordinate **DDA**, independent of texture resolution. The fps lever is fewer textured **pixels** (2×2 blocks / near-only), a `draw_span` flag, not smaller textures.*

**Stretch:** 320×200 textured — **no speculation tier** (we won't use it). Reachable if flat-run + the §2.1/§3 optimizations push the engine to **~400M+ fj/s**; revisit once R2's measured ops/frame are in. Not a dependency.
**Fidelity fallbacks (if @ ≫ 25 or opts underdeliver):** 2×2 textured floors → flat-colored floors → **flat-shaded** (walls *also* untextured) → 12.5 fps (render-1-of-2-tics, D9) → bpp=4 (16 colors) → flat→paged storage.

**Budget:** ~280M fj/s (measured flat, native engine) ÷ fps. fps is continuous (no timer, D9): 25 fps = **11.2M**, **20 fps = 14M** (the **chosen** target — full-res textured floors land ~14M, §1 curve), 12.5 fps = 22.4M. The ledger below is in **@** (scale-invariant) at the working **@ = 25** (≈ §A game scale; R-1 measures the real @). *Note: the per-pixel lines use the textured-**wall** cost applied uniformly; the actual frame depends on the wall/floor split and floor mode — flat floors are far cheaper, textured floors heavier (§1 curve). The ~14M target reflects full-res textured floors.*

### 1.1 Ops-per-frame ledger (sums to the chosen ~14M frame ⇒ ~20 fps; fps is continuous — §1/D9) — computed at **@ = 25**

Costs are stated in **@** (scale-invariant) and converted at **@ = 25** (the design working point; **R-1** measures
the real @ at S5.3 before R2 commits). Per-pixel lines are ×16,000 px, optimized model (§1.1.1).

| Line | Component | @/frame | Per-frame @ **@=25** | Technique |
|---|---|---|---|---|
| Pixel stores (deposit, ~4@/px) | F4 | 64K@ | **1.6M** | static stores §3.1, D3 deposit |
| Texture + colormap reads (2 dispatches, ~8@/px) | F3/F5 | 128K@ | **3.2M** | dispatch-LUTs §3.2 |
| **Per-pixel arithmetic** (select ~3@ + DDA ~11@ + index ~2@ = ~16@/px) | F5 | 256K@ | **6.4M** | **mandatory** 8.8 fraction-accumulator DDA + `hex.sign` select |
| Column + BSP walk + S0 sim (rebuilt §1.1.3) | F5/H3/F6 | ~180K@ raw | **~4.5M raw → ~3M optimized** | reads dominate; BSP-as-code (§1.1.3) |
| Present (`update_screen` 0x03) + input poll | F7 | ~negligible | **~0** | memory-hook |
| **Total** | | | **≈ 16M raw → ~14M all-opts** (full-res textured floors ⇒ ~20 fps; ~9M flat floors ⇒ ~30 fps — **§1 curve**) | **the opts are what make even ~20 fps reachable; higher fps/margin is a fidelity lever** |

**Putting it together (all opts #1–9, @=25), with the wall/floor split (§1 floor curve):** the per-pixel work depends on the floor mode — flat floors ~6M, full-res textured floors ~11M (floors are 2-coord spans, heavier than walls) — plus the rebuilt column/BSP ~2.5–3M (opts #6–9). So the frame is **~9M (flat floors, ~30 fps) … ~14M (full-res textured floors, ~20 fps — the chosen target)**. **Owner-agreed:** opts **#1–9**; **full-res textured floors at ~20 fps**; 2×2-block floors a perf toggle. *(History: my earlier "~8–9M, 1.3× margin @25fps" and "~11.4M at budget" were both wrong — the first used a too-low ~5@ DDA, the second mis-charged floors the cheap wall cost. The honest picture is the §1 floor↔fps curve.)* Per-quantity widths are the **precision ledger (§1.1.4)** — most quantities are *not* 16.16.

#### 1.1.1 Per-pixel arithmetic — reconstructed from the actual STL macro costs (S2)

The per-op costs in the design are **verified correct** against the 1.5.0 STL (S2): `hex.mul n=8`=`352@+1280`, `hex.div n=8`=`2304@+6400`, `hex.shl_hex n=8`=`8@+32`, `hex.write_byte`=`41@+197`, `hex.read_byte`=`33@+173`, `stl.fcall`=`@-1` — all match §A. **The gap was in the per-pixel *aggregation*, not the per-op numbers.** A textured wall pixel does more than the "2 dispatches" the texture line counted; reconstructing it from the real macros (`hex.add n`=`n(4@+12)`, `hex.cmp n`=`m(3@+8)` with early-exit, `hex.sign n`=`@-1`):

| Per textured-wall-pixel | macro | optimized | naïve |
|---|---|---|---|
| ceiling/wall/floor **select** | 1–2× `hex.cmp` of 2-nibble screen coords (early-exit ⇒ `m≈1`) / `hex.sign` | ~3–5@ | n-width cmp ~6–12@ |
| **DDA** `frac += step` | `hex.add n` | **~9–16@, avg ~11@** — each nibble-add is ~4@; the 8.8 *fraction-accumulator* adds only ~2 fraction nibbles/px for close/mid walls (~9@), the full 4-nibble add for far walls (~16@) | ~16@ (8.8, n=4) … ~32@ (16.16, n=8) |
| texel index assemble (col-base + texel) | `hex.xor_by` / small add | ~2@ | ~2@ |
| texture sample + colormap | 2 dispatches | ~8@ | ~8@ |
| deposit | 2 nibble-dispatches | ~4@ | ~4@ |
| **per-pixel total** | | **~28@** → **700 ops/px @ @=25** (×16K = **11.2M**) | **~58@** → **1,450 ops/px** (×16K = **23.2M**) |

So the budgeted "~12@/px" (2 dispatches + deposit) was **~2.5× low even optimized, ~5× low naïve** — the new **Per-pixel arithmetic** line carries the difference. Three consequences at @=25: **(1) the per-pixel path *is* the whole game** — the optimized per-pixel work alone is **~11.2M**, i.e. it fills the entire *25-fps* (11.2M) budget by itself before any column/BSP work — **which is exactly why the chosen target is 20 fps / ~14M, not 25 fps** (§1); the naïve version (~23.2M) is ~2× even that. **(2) the DDA is irreducibly the biggest line** — even optimized to 8.8 + accumulator it is ~11@/px (~4.4M), because a fixed-point add is *N* nibble-dispatches at ~4@ each. **(3) floors/ceilings are heavier** — perspective spans step **two** coordinates (`u`,`v`) per pixel (flat-colored floors avoid it; a fidelity lever). R-1 (S5.3) **must measure the real per-pixel cost including the DDA**.
> **Why the DDA add can't be made cheaper by being a *constant* (a settled question):** `step` is **runtime** (distance-dependent, differs per column), so it is genuinely variable+variable. And even if it were constant, **a constant nibble-add is *not* cheaper than a variable one in FlipJump** — the cost is the *carry dispatch* (a ~4@ table lookup needed whether the addend is constant or variable; a constant just makes it a 16-entry table instead of 256). So the only DDA wins are **narrower width (8.8, #2 precision ledger) + the fraction-accumulator (#1)**. A **countdown** (`counter -= 1`/pixel, texel++ on zero) *is* cheaper (~4@) but **aliases** (rounds texel spacing) unless done Bresenham-style, which costs ~8@ again — a quality-for-speed lever, not the default.

> **@ is the dominant budget variable (U7/R-6).** The whole ledger is **@-proportional** — a dispatch is ~4@, a deposit ~4@/byte (§2 glossary), the column/BSP reads are dispatches too — and **@ grows with total program size (U7)**. The design computes at the working point **@ = 25** (≈ the §A "DOOM-scale" figure); at that @ the frame is **over budget at full fidelity** (above), which is why the §1.1.2 optimizations are load-bearing. The budget scales ~linearly: a lighter build (smaller @) buys margin, a heavier one (more LUTs/textures/unrolled code) costs it. **R-1 (S5.3) measures the real @ at game scale before R2 commits** — it is the single most important budget measurement; if @ lands materially above 25 the §2 fallbacks (flat-colored floors, flat-shaded, 12.5 fps, bpp=4) are the relief.

#### 1.1.2 Optimization priorities — the flows by time-profit (@ = 25)

Ranked by the per-frame ops *saved* vs a naïve implementation. **#1–2 take the per-pixel path from the naïve
~23.2M down to the optimized ~11.2M baseline — they are mandatory just to be in the game**; **#3–9 then trim
the per-pixel and column/BSP work further so the full frame lands on the §1 floor↔fps curve: ~14M
(full-res textured floors ⇒ ~20 fps, the chosen target) … ~9M (flat floors ⇒ ~30 fps).** The opts are what
make even ~20 fps reachable; reaching 25 fps (~11.2M) or gaining margin is then a *fidelity lever*, not a
further per-pixel optimization.
Profits are at @=25; they shrink/grow ~linearly with the measured @.

| # | Flow (where the effort goes) | naïve | optimized | **profit @=25** | fidelity cost |
|---|---|---|---|---|---|
| **1** | **DDA `frac += step`** (per-pixel) | 16.16 add ~32@ | 8.8 + fraction-accumulator (add ~2 fraction nibbles/px, carry to a 2-nibble texel index) ~9–16@, **avg ~11@** | **~8.4M** | none (exact) |
| **2** | **ceiling/wall/floor select** (per-pixel) | n-width 2× `hex.cmp` ~12@ | `hex.sign` (`@-1`) + sticky region, 1 test/px ~3@ | **~3.6M** | none |
| **3** | **fuse texture→colormap** (per-pixel) | 2 separate dispatches ~8@ | chain the texel handler into the colormap entry (skip the `xor`-bridge), or per-light composed table ~4–5@ | **~1.2–1.6M** | none (chain) / +span (composed) |
| **4** | **per-column `fracstep`** (×160) | 16.16 `hex.mul` ~352@/col | 8.8 / `mul_const` shift-add ~80@/col | **~1.0M** | tiny (8.8 step) |
| **5** | **deposit** (per-pixel) | `hex.mov 2` zero+xor ~4@ | custom *set-into-clean* table, 1 dispatch/nibble ~2.5@ | **~0.6M** (×2 at bpp=4) | none (bpp=4 → 16 colors) |
| **6** | **BSP stream fields** (per node/seg) | every byte = `read_byte_and_inc` ~42@ | trim to the minimal per-node/seg record; pack so one walk reads it contiguously | **~0.3–0.6M** | none (data layout) |
| **7** | **BSP-as-code, not data** (§1.1.3) | walk *reads* node partition+bbox (~1.8M of reads) | compile each node into a code block with the partition as **compile-time constants** — no reads, side test becomes `mul_const` | **~1.5M** | +program size / assemble (R-2), per-level recompile |
| **8** | **16.0 integer BSP/visibility math** (§1.1.4) | 16.16 side-test mults (n=8) ~352@ | truncate to integer coords (sub-unit doesn't change the side) → n=4 mults ~88@ | **~0.3M** | none (visibility only) |
| **9** | **incremental scale interpolation** | per-column scale via a mult | scale at the two seg ends, then `+=` per column (DDA-style adds) | **~0.3–0.5M** | none (exact) |

Two structural levers sit *above* this table (they change which pixels pay at all, not how much each pays):
**flat-colored floors/ceilings** removes texture+colormap+2-coord-DDA+index on ~40–50% of pixels (the single
biggest single move, a fidelity tradeoff), and the **full-column unroll (D2b)** is what makes the per-pixel
*address* free in the first place (without it every store is a ~41@ pointer write — §A — which alone would be
~10× the deposit line). #1–9 are the *within-pixel*, *within-column*, and *within-BSP* wins on top of those.
**Owner-agreed (this review): all of #1–9** (incl. the §1.1.4 precision-ledger widths = #8, **#7 BSP-as-code**, and **#9** incremental scale). With #1–9 + **full-res textured floors** the frame is ~14M → **~20 fps** (the chosen target, §1 curve); the 2×2-block floor mode (~27 fps) and flat floors (~30 fps) are perf toggles, not the default.

#### 1.1.3 Column + BSP + sim — rebuilt from the macros (@ = 25)

Replaces the old soft "~2.5–5M" envelope. Assumptions: ~80 BSP nodes + ~60 wall-segs visible/frame (E1M1),
R-1 measures the real counts. **The reads dominate, not the multiplies** — each streamed byte is
`read_byte_and_inc` ≈ 42@, and a frame consumes ~1,700 bytes of node/seg/sector data:

| Part | cost @=25 | note |
|---|---|---|
| Stream reads (node + seg + sector) | **~1.8M** | ~1,700 bytes × 42@ — the biggest single piece; **opt #6 trims it, opt #7 (BSP-as-code) ~eliminates it** |
| Per-column setup (fracstep, interp, clip) ×160 | **~1.2M** | opt #4 (fracstep) + #9 (incremental scale) cut it |
| Multiplies (BSP side tests, scale, angles) | **~0.7M** | opt #8 (16.0) halves the side-test mults |
| Floor/ceiling visplane setup | **~0.6M** | per-span yslope + step |
| Sim S0 (move + collide) | **~0.2M** | cheap class (adds, signed compares) |
| **Total** | **~4.5M raw → ~3M with #6–9** | R-1 measures real node/seg counts |

#### 1.1.4 Precision ledger (per-quantity widths) — most of the game is *not* 16.16 (D6)

Drop below 16.16 wherever the reference model (H5) confirms acceptable wobble (D6). Width mismatches in one op
read past the end (flipjump-dev skill) — align at the boundaries (e.g. 16.16 player vs 16.0 vertex), D13.

| Quantity | width | why |
|---|---|---|
| Map geometry (vertices, linedefs, partitions) | **16.0** | DOOM stores these as integers |
| BSP side-test math | **16.0** | sub-unit doesn't change the side (opt #8) |
| Texture v-coord (wall DDA frac/step) | **8.8** | texel ≤256 + ~8 frac bits |
| Floor/ceiling span u,v (DDA) | **8.8 / 6.8** | flats are 64×64 |
| Wall scale / reciprocal output | **8.8–16.8** | pixel-accurate height |
| Wall top/bottom (screen clip) | **8.0** | screen rows 0–100 |
| Player angle | **~16.0 / 12-bit** | trig LUT uses only the top 12 bits |
| Velocity / move delta | **8.8** | bounded speed |
| Distance (recip / colormap index) | **12-bit index** | it's a bucket, no fraction |
| Light level | **5-bit** | 0–31 |
| Health / armor / ammo | **8.0–16.0** | small counters |
| **Player position x,y** | **16.16** | the *only* genuine 16.16 — big world + smooth movement |

### 1.2 Address-span ledger (must sum < chosen `--flat-max-words`; **R-3**)

Power-of-two dispatch-table padding inflates the span — lay out **hot-low + largest-alignment-first**
(§3/#2) and sum padding here, don't discover it. **OPEN — D10** (concrete memory map). Default flat limit = 2²³ words
(64 MB); raise via `--flat-max-words` / `FLIPJUMP_FLAT_MAX_WORDS` if needed (cost = RAM + ~0.1 s/GB fill,
zero per-op cost). Assert `storage_mode == flat` in the harness. Very-hot tables may be **over-aligned** by one bit (§2.1) — count the extra padding here.

| Segment / table | Size formula (ops) | Align pad | Span (R0-filled) | Notes |
|---|---|---|---|---|
| hex.init truth tables | ~fixed (or/and/mul/cmp/add/sub) | — | TBD | from `stl.startup_and_init_all` |
| Unrolled renderer code (D2b) | ~16K px × stub size + 160 col × col-setup | — | **TBD (R-2 watch)** | the big code consumer; assemble time tracked |
| Texture dispatch table(s) (D5) | ~300K texels (native E1M1; R0 exact) | pow2 pad | **~300K entries (OQ8 watch)** | likely largest → placed first; downscale is the lever |
| **Leading alignment pad** (hot-low ⇄ largest table) | = (texture-table 2ⁿ boundary) − (low data + small tables end) | **dead span** | **TBD (R0); ~0.1–0.5M expected** | the hot-low data region (framebuffer/palette/buffers) + the small tables sit in `[0, 2ⁿ)`; the gap up to the texture table's 2ⁿ boundary is dead span — **RAM only, zero per-op cost** — summed here per §3.3, not discovered. Shrinks if the texture table is downscaled to a smaller 2ⁿ. |
| Trig (finesine; cos = offset; tangent/viewangle) | **N=4096=16³** (top 3 nibbles, no shift §2.1; per-result-nibble, D4) | 16³-aligned | TBD (~0.25MB if 4096×8-nibble) | cosine shares the sine table (+N/4 = single-hex add); 256 = coarse fallback |
| Reciprocal / scale | pow2 ≥ entries | pow2 pad | TBD | replaces divides |
| yslope · viewangletox/xtoviewangle | pow2 ≥ entries | pow2 pad | TBD | |
| Colormaps (D4 handlers) | 32×256 = 8192, byte results | pow2 pad | 8192 entries | per-column-selected (D11); over-align #3 |
| +4-offset deposit table (D3) | 256 | pow2 pad | ~256 | |
| Framebuffer | W·H = 160·100 = 16,000 | — | 16,000 | packed bytes, no align |
| Palette | 256·3 = 768 | — | 768 | |
| Map/BSP (now **code**, opt #7) | ~470 nodes × ~40 ops | — | ~0.02–0.06M | replaces the data stream; +assemble time (R-2) |
| State/scratch registers | small fixed set | — | TBD | hex.vec |
| **Total (estimate, R0 confirms)** | | | **~2.5–3M ops ≈ 20–24 MB flat RAM** | **< 64 MB limit, ~3× headroom (R-3 holds)** |

**Program size (estimate, R0 measures):** ~2.5–3M ops ⇒ **~20–24 MB runtime flat-memory footprint** (well under the 64 MB / `2²³`-word default limit), and a **~6–10 MB compressed `.fjm`** on disk. **Textures dominate (~85%)** — dispatch-LUT textures trade ~6× space for cheap per-pixel reads (D5); halving texture resolution is the size/assemble lever if needed. **BSP-as-code (#7) adds little *size* (~0.2–0.5 MB) — its cost is assemble *time* (R-2) + per-level recompile.** **No runtime data loading:** FlipJump has no filesystem (only the keyboard input stream), so the **level is baked into `doom.fjm` at assemble time** (R2 = E1M1 only, D8).

**Level packaging — *owner-leaning: all levels in one binary*** (vs one `.fjm`/level). **Runtime fps is *unchanged* by level count** — the renderer walks only the *current* level's BSP; the others sit dormant (level-switch = re-point the BSP root + reset state, once per transition). Cost is space + assemble time only, and **textures are shared**, so it scales sub-linearly. **All 9 shareware E1 levels** (E1M1 Hangar · E1M2 Nuclear Plant · E1M3 Toxin Refinery · E1M4 Command Control · E1M5 Phobos Lab · E1M6 Central Processing · E1M7 Computer Station · E1M8 Phobos Anomaly · E1M9 Military Base) ≈ **~31–38 MB flat RAM** (texture *union* ~21–28 MB + 9× small BSP-code + shared LUTs/renderer; under the 64 MB limit, ~1.7× headroom) / **~12–18 MB `.fjm`**. **Watch item: assemble time** (~9× BSP blocks + the full texture union — R-2). The full game (Ultimate 36 / DOOM II 32) grows the texture union past 64 MB → raise `--flat-max-words` or downscale.

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
| colormap | (light, texel) | **8192** (32×256) | byte | R2 | 32 light levels; per-pixel, over-align #3 |
| +4-offset deposit | (old,new) hi-nibble | 256 | flips | R2 | D3 |
| textures (wall+flat) | texel position | **~300,000** | byte | R2 | native E1M1 (D5/OQ8); R0 measures exact, downscale is the lever if over budget |
| palette (device data) | index | 256 | 3 bytes | R2 | data, not a dispatch LUT |
| P_Random `rndtable` | rndindex | 256 | byte | R3 | excluded from the R2 total |
| — *STL infra*: `hex.init` | — | ~6×256 (+ mul) | — | infra | flipjump's own; counted apart |

**R2 subtotal** (fixed-size LUTs, *excl.* colormap + textures): 4096+2048+2048+161+160+100+4096+256 = **12,965 entries** (the 8 dispatch LUTs above; palette is data and rndtable is R3, both excluded).
**+ colormap (32×256) = 8,192** → non-texture total **21,157**.
**+ textures ≈ 300,000** (native E1M1 planning; R0 measures exact).
**⇒ Unified R2 total ≈ 321,157 entries** — **textures are ~93% of it**; everything else sums to ~21K.
*Span note (→ §1.2):* entry *count* ≠ span. Wide per-result-nibble tables multiply by result-nibbles (finesine/reciprocal ×8) and per-entry handlers cost ~popcount ops/entry; the **LUT span lands ≈1.5–2M ops** (textures dominate), comfortably under the 8.4M flat limit. **Span pressure vs assemble-time pressure are distinct, and live in different places:** for raw *span*, the LUTs/textures (≈1.5–2M) plus the leading alignment pad (§1.2) dominate; the unrolled renderer *code* is the **assemble-time** pressure (R-2 — ~16K macro expansions), with comparatively *small* span once the heavy logic is factored into the shared `fcall` leaf (~100–300K ops, §B/D2).

*Sizing (#1 — bump where it helps):* sizes are **matched to the 160×100/256/32 output**, so more entries are *not* added where they wouldn't show. The **angular/projection tables already out-resolve the 160-column output ~6×** (finesine 4096 = 0.088°/entry vs ~0.56°/column; tantoangle/viewangletox feed a 160-wide result and get re-quantized). The **per-row/col tables are exactly one entry per column/row** (xtoviewangle=W+1, distscale=W, yslope=H). **reciprocal/scale** is the only map-dependent size — **R0 tunes it to E1M1's measured max sightline** (default 4096; bumped freely, LUT span has ~6M ops headroom); near-wall scale smoothness comes from **seg-scale interpolation** (R1), not a bigger table. colormap=32 (owner) and textures=native are at chosen/max fidelity. W/H-dependent tables auto-scale for the 320×200 stretch. *(Override any specific table for more margin.)*

- **fj-op** — one assembled FlipJump op (flip-word + jump-word = `dw` bits). The budget unit.
- **`@`** — the per-op cost constant (~27 at w=32; **the design computes at the working point @ = 25**, ≈ game scale — R-1 measures the real value); grows with total program size (**U7**). A figure in
  `@` is *not* comparable to a raw-ops figure without conversion (contradiction-hunt §6).
- **w / dw / dbit** — word width (=**32**, confirmed: 16.16 fits one word) / `2w` (one op) / `w` (data-bit offset).
- **nibble / hex / byte** — a `hex` = 4 data bits; a packed byte = 8 data bits in one op; register-form byte = two `hex` ops (low, then `+dw`). The two byte encodings do **not** interchange (see flipjump-dev skill).
- **Fixed-point** — Q-format: 16.16 = `n=8,f=4`; 8.8 = `n=4,f=2`. **Signed-compare ladder (cheapest first, verified S2):** `hex.sign n` = **`@-1` (O(1), reads only the MSB)** for a *pure sign* test (is `x<0` / did it underflow) — use this wherever only the sign matters; `hex.scmp n` = **`n(7@+8)`** for a true two-operand signed *magnitude* compare (`a<b`); **never `hex.cmp` on signed values** (correctness — §3.5). Note `hex.cmp n` itself *early-exits* (`m(3@+8)`, `m` = count of differing high-nibble prefix), so unsigned compares of values that diverge high (e.g. screen coords) cost ~`3@`, not `3n@`.
- **Static store** — a framebuffer write to a *compile-time-known* address. The runtime-value byte deposit ≈ 2 nibble-dispatches ≈ **~4@/byte** (STL `hex.mov 2` = `2·(2@)`; the real packed deposit adds the +4-offset hi-nibble table, ~comparable) — i.e. **~100 ops at @ = 25** (~53 ops measured in a small probe at its @≈9, confirming the `4@` structure). Contrast a runtime-address pointer write (`write_byte` ≈ **41@** ≈ 1,000 ops). *(The handoff §A "~7@" single-byte-write estimate is superseded.)*
- **Dispatch-LUT** — the `hex.xor`-jumper table idiom (`tables_init.fj`): **~4@ per lookup** (STL `jump_to_table_entry` = `4@+4`, plus a cheap ~`log(n)/2`-**fj-op** in-table traversal; STL `hex.or` = `4@+10` end-to-end) — so **~9–10× cheaper than a `read_byte` pointer read** (`33@+173`). The cost is in **@** (scale-invariant): **~100 ops/lookup vs ~1,000 for `read_byte` at @ = 25**; a small probe gives ~46 ops/lookup at its @≈9 (`storage_mode=flat`) — same `4@` structure, smaller @. One dispatch sets a *fixed-address* hex = a *runtime* value, so it is the pointer-free deposit primitive. *(The handoff §3.2 "~10@/lookup" double-counted the cheap fj-op traversal as @-units; the dispatch core is ~4@. **@-vs-ops:** never compare a game-scale @-figure to a small-program ops-figure — see §1.1's @-note.)*
- **`P_Random` / determinism** — the game uses **no true RNG**. DOOM's "randomness" (combat/AI, R3+) is a deterministic 256-byte `rndtable` + advancing `rndindex` — a byte-LUT. The whole game is deterministic, which is *required* by D12 (bit-exact + replay). R2 uses no randomness at all.
- **Cell width ⊥ pointer-freeness** (key D3 insight) — "packed byte" (8-bit cell, forced by bpp=8/256-color + the device read) is the framebuffer *cell width*; "pointer-free" is whether the *address* is compile-time-known (delivered by D2(b) full-unroll). Orthogonal: a packed-byte framebuffer can be written entirely by fixed-address stores. The runtime-value→fixed-address deposit cost scales with bits — a byte ≈ 2× a nibble — so bpp=4/hex.vec is the ~2×-cheaper-deposit / 16-color cost-fallback.

## 2.1 Cross-cutting build techniques

- **Dependency policy — flipjump 1.5.0 is near-frozen, but *extensible*.** Default: build only on stock 1.5.0; **no speculation tier** (we won't use it). If a device/engine change would *materially* help and stock-1.5.0 designs are exhausted, we **can** ship a tested `fj==1.5.1` — a deliberate, justified, last-resort lever, not a default (strong preference: don't). Candidate extensions, *only if measured to win*: a ScreenIO mode reading **two 4-bpp ops as one 8-bpp pixel** (would make a `hex.vec 2` framebuffer device-direct — reopens D3's rejected option); a **column-major bit-input stream** matching the program's compute order; a **device-side fps cap** (D9).
- **16^x-sized shift-indexed LUTs (U6+).** When the index is *derived by shifting* a value (angle→sine: shift, then jump), size the table to a power of **16** (nibble-aligned entry count) so the index lands on nibble boundaries and **no runtime/sub-nibble shift is needed** (saves space + time). E.g. trig N = **4096 = 16³** (top 3 nibbles), not 8192 (2¹³, a 19-bit shift). Applies to every shift-indexed dispatch-LUT.
- **Over-align very-hot dispatch-LUTs.** Align a hot 2ⁿ-entry table to 2ⁿ⁺¹ so the top alignment bit is always 0 → the jumper's `wflip` round-trip skips it (~0.5 op each way, ~1 op/lookup saved). Worth it **only** for per-pixel/per-column-hot tables (colormap, texture, deposit) — the 2× padding isn't worth it for cold tables (track in the span ledger).
- **Call discipline — tiered `fcall`/`fret`, avoid the stack.** Prefer `fcall`/`fret` over `stl.call`/`return` (~2.5w@ + stack). A **non-leaf** function may `fcall` another using a **distinct `ret_reg` per call-graph level** (`ret_L0`, `ret_L1`, …) — so any *bounded, non-recursive* depth is stackless (**OQ9 resolved**). Reserve the stack for *genuine unbounded recursion*, and even there push it down the tree (F5's BSP walk takes its bottom levels stackless).

---

## 3. Memory map (D10)

**Layout principle (#2 + §3.3): hot LUTs / framebuffer / buffers at the LOWEST addresses; the entry op jumps over them.** Two goals: **(a) low = cheap** — the per-pixel hot targets (framebuffer, per-pixel dispatch tables, hot buffers) get the smallest addresses, so their `wflip`/store constants are tiny; this *also shrinks the unrolled renderer's compile-time address constants* (a real **R-2** size win). **(b) largest-alignment-first** among the pow2-aligned dispatch tables, so padding nests rather than sums. Dispatch tables are pad-aligned **CODE** (base low-bits zero, entry `k` at `base+k·dw`) — entered only via wflip-jumps, never fall-through; the framebuffer/buffers are data touched by stores/device. The program's **first op `;main` jumps over the whole low region** to the code. (The ~300K texture table sets a high alignment, so *code* lands at high addresses — fine, since code `wflip`s, `fcall`s and BSP jumps are per-column/per-node, *not* per-pixel, so they can afford the larger constants.) Units: 1 fj-op = `dw` = 64 bits at w=32 = one 8-byte span-word; default flat limit 2²³ span-words (64 MB) ≈ **8.4M ops** (raise via `--flat-max-words`). **Invariant: total span < flat limit; `storage_mode == flat` asserted (R-3).**

```
0x0   ;main                                ENTRY: jump over the low region to the code
      ── LOW ADDRESSES — hot, cheapest wflip/store targets ──
      framebuffer (screen)       W·H = 16K packed bytes   (per-pixel store targets)
      hot buffers                per-column scratch (top/bottom/colormap-sel) · player
                                 state · keydown[] · BSP clip array
      palette                    256×3 bytes (device-read)
      ── pow2-aligned dispatch tables: hottest + largest-alignment first (CODE) ──
      texture table(s)           per-pixel; ~300K → largest, sets the alignment
      colormap                   per-pixel; over-aligned (#3)
      +4-offset deposit table    per-pixel (256)
      finesine(cos=offset) · reciprocal/scale · viewangletox · xtoviewangle ·
        tantoangle · distscale · yslope                    (per-column)
      hex.init truth tables      heavily used → also kept low (exact entry/startup
                                 structuring is an R1 detail)
main: stl.startup_and_init_all   CODE begins right after the tables
      [CODE] game loop · BSP walk · unrolled renderer (D2b) · present · input · F3 idioms
      stl.loop   (halt)
      ── HIGHER / COLD ADDRESSES ──
      map/BSP streams            NODES/SSECTORS/SEGS/SECTORS/SIDEDEFS/LINEDEFS/VERTEXES (seq.)
      P_Random rndtable (R3) · stack (BSP upper levels only, F5)
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
- **D4 — Per-table dispatch shape.** *RESOLVED → **per-entry handlers (default)**; per-result-nibble as a per-table override.* Per-entry handler = 1 dispatch + popcount flips (≈4@+2W ops) — ~7× faster than per-result-nibble (W dispatches ≈ 4W@) for wide results, ~2× for a byte. Chosen because ops/frame is the scarce resource and the per-pixel colormap benefits most. **Cost it carries:** a more complex generator (custom per-entry flip code) and ~2–3× table space on wide tables (feeds **R-3** span). **Override:** large *cold* tables (e.g. trig) may use per-result-nibble to save span if the span ledger tightens — recorded per-table in the span ledger + the table's test. Both fit the shared `res`/`ret` machinery (handler XORs `value[k]` into `res`, caller `xor_zero`s out). **Construction (#5):** an over-alignable (`pad 2ⁿ`) `switch:` jump table (`;arg_k` per entry); each `arg_k:` **`xor_by`s (flips in) the entry's compile-time value into the shared *kept-zero* `res` — *not* `hex.set`** — and **cleans the jumped switch-op from within the table** (like stl's `clean_table_entry`, which also XORs rather than sets).
  - **Why not `hex.set` per entry — the trap (measured S2).** `hex.set` expands to `hex.zero` + `xor_by`, and `hex.zero` is itself a *table-dispatched* op (`@+12`/nibble) — so per-entry `hex.set` bakes a **value-independent zero into every entry**, ≈**32× the space** of a bare `xor_by` (~512 B vs 16 B/entry at w=32, measured). On the ~300K-entry texture table that is ~150 MB / ~19M ops (**over the flat limit — would break R-3**) vs ~5 MB. The fix costs **nothing in time**: `res` is held at zero by the caller's `xor_zero`-out (which also reads it into the destination), so the zero is paid once — in the read-out you do anyway — *not* per entry and *not* as a separate pre-zero. *(Per-entry `hex.set` is functionally correct; it is acceptable only where the entry count is small and space is abundant — for the big tables it is not. If a future construction ever does need an explicit pre-zero of a wide result, route it through one shared `fcall`'d zero-routine, never inline it per entry.)*
- **D5 — Texture storage.** *RESOLVED → **dispatch-LUT textures**.* Textures baked as aligned dispatch table(s); per-pixel texel sample = **~4@ dispatch** (not a ~33@ `read_byte` pointer read). Per column the source column is fixed (selected once, amortized); per pixel the index = per-column base + texel (`frac>>FRACBITS`, a compile-time shift) — an add, nibble-aligned, no runtime shift (U6). **Span (texel count rounded to pow2, OQ8) is the open risk — measured in R0/R1**; fallbacks: sequential packed-byte streams, fewer/smaller textures. R2 bound to E1M1's real textures (downscale if the span ledger demands). Entry shape per D4.
- **D6 — Precision per quantity.** *RESOLVED → **narrowest width the reference model validates; 16.16 only where genuinely needed**.* The **per-quantity precision ledger is §1.1.4** — and the S2 rebuild shows **most quantities are 8.8 / 16.0 / 8.0, not 16.16** (only player position is genuinely 16.16). These reductions are **load-bearing, not optional slack** — at @=25 the budget is ~at-limit (§1.1), so the narrow widths (8.8 DDA/scale, 16.0 map+BSP math, 8.0 screen coords) are part of *reaching* budget, not headroom. Each is still validated against the reference-model diff (OQ5/H5) for acceptable wobble; width mismatches at boundaries (16.16 player vs 16.0 vertex) handled per D13 / the flipjump-dev width-mismatch rule.
- **D7 — Feature scope at 160×100.** *RESOLVED → first playable (R2) = **textured 3D view (walls + floors/ceilings) + S0 walk/collide**, auto-warp into the level.* Flag-gated for R3+: S1 doors+hitscan, S2 sprites/enemies, HUD/status bar, menus, text, demo playback. Rationale: prove the renderer + the §1.1 budget (the hard part) first; matches the §8 ladder. The compositor/pass pipeline and `blit_rect`/glyph API (§E, F8) are **stubbed flag-gated from day one** so later passes drop in without touching the 3D core.
- **D8 — Maps & assets.** *RESOLVED.* **Asset source:** shareware `doom1.wad` for development; **Freedoom** WADs for anything redistributed (CI fixtures / golden frames). **Map ambition:** R1 renderer bring-up + measurement on a small (hand-built or smallest real) BSP map to keep the assemble/span/measure loop fast; **real E1M1 is the R2 target.** Entity counts: deferred to D7's S2 tier (sprites flag-gated; not in R2).
- **D9 — Frame pacing.** *RESOLVED → **tic:render 1:1, budget-bound; fps is continuous, not a target you set**.* One input poll = one tic = one rendered frame. There is no timer device (§1.1), so the program cannot self-pace; **fps = `engine ÷ ops-per-frame`, a continuous outcome** — you don't pick 25 vs 12.5, you spend ops and *get* a framerate. **Owner target: full-res textured floors ≈ 14M ops ⇒ ~20 fps** (§1 floor↔fps curve); flat/2×2 floors give ~30/~27 fps as toggles. Accept and **report** the measured wall-clock fps (present-log). Sim/render decoupling (render 1-of-N tics, G21) is a deferred hedge, not built in R2. **If frames run too fast** (likely on the native engine): wall-clock pacing can't be done in-program (no timer); the clean fix is a **device-side fps cap** — the screen device sleeps on present if too little wall-time elapsed ("aim for X fps"). Verified *not* in the stock pygame device ⇒ a candidate `fj==1.5.1` device extension (§2.1). R2: run uncapped + report fps; add the cap for a playable interactive build.
- **D10 — Memory map.** *RESOLVED (structure) → see §3 + the §1.2 span ledger.* **Hot-low + largest-alignment-first (#2):** entry `;main` jumps over a LOW region = framebuffer + hot buffers + the pow2-aligned dispatch tables (per-pixel: texture[largest] / colormap / deposit; then per-column: trig / reciprocal / viewangle / yslope) + hex.init tables → `main` code → `stl.loop` → cold map streams / stack. Low addresses ⇒ cheap `wflip`/store constants (and smaller unrolled-code constants, an R-2 win). Concrete spans filled by R0; flat-limit guarded by the span ledger + `storage_mode` assertion.
- **D11 — Colormap/lighting application point.** *RESOLVED → **per-column/span SELECT, per-pixel APPLY**.* The colormap (light level) is chosen once per column (walls) / per span (floors) — DOOM-faithful, ~160×/frame; it is then applied per pixel as a dispatch chained off the texel sample (texel → lit palette byte). Avoids the U9 trap (per-pixel light *recomputation* / pointer-read colormap, ~6M+/frame) while keeping correct per-pixel colormap application. Per-pixel light *recomputation* (smoother distance lighting) is a deferred fidelity option; flat-shaded (no colormap) is the fallback tier.
- **D12 — Test granularity.** *RESOLVED → **bit-exact (sha256)** against an exact-integer reference model.* The reference model (H5) replicates our exact integer pipeline (fixed-point truncation, LUT values, colormap select/apply), so rendered frames must match byte-for-byte (sha256 equality — `ScreenIO` logs this hash per present) and sim state (pos/angle) must match exactly. Any diff = a real bug. Golden set: a small curated set (spawn + movement waypoints + near-wall), grown as features land; scripted key-event demos for E2E. Obligation: the reference model mirrors every integer detail. **Determinism is load-bearing:** the game uses no true RNG (DOOM's `P_Random` is a deterministic 256-byte table, §2 glossary / F6), so golden frames and replays are reproducible. **LUT test mandate (#8):** every generated LUT is tested on **every entry** (not just samples/boundaries) **and** with a **call-twice-per-entry** check (catches result-reg / in-table jumper-cleanup bugs from the #5 construction). Triple-check every table.
- **D13 — Fixed-point intermediates.** *RESOLVED → **full 2n-nibble-width product** (PR #1's `hex.fixed_mul` approach is the standard).* Overflow-safe: compute the product at 2n nibbles, nibble-aligned fraction shift (no runtime-amount shift, U6), truncate to n. `@Assumes 0 < f <= n`. Narrow-intermediate optimization is opt-in per-call later only if a hot mul demands it.
- **D14 — Directory tree.** *Deferred to Stage 3.*
- **D15 — PR #1 CR surface.** *Deferred to Stage 5 / S5.0.* API/naming/test-style changes to `fixed_point.fj` + LUT generator.

---

## 5. Testing strategy (the pyramid)

Per handoff §H / §3.5. Top to bottom:

1. **Host unit tests (Python)** — WAD parser, LUT/dispatch generator, map/texture compilers, reference model. `pytest`.
2. **Per-macro fj tests** — TDD, `--werror`, byte-exact via `flipjump.assemble_and_run_test_output`, **a boundary input per behavior path** (single green fixture proved insufficient 3× in the catalog), the §2 signed-compare ladder (`hex.sign`/`hex.scmp`, never `hex.cmp`) for anything signable.
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
- **Data & layout:** generated tables = pow2-aligned dispatch CODE (→ §1.2 span ledger); alignment-aware emit, **over-aligns very-hot tables** (§2.1); per-entry handlers use the **#5 `switch` + `xor_by`-into-kept-zero-`res` + in-table-clean** construction (**not** per-entry `hex.set` — D4: that replicates a table-dispatched `hex.zero` per entry, ~32× space, span-breaking on big tables); **16^x sizing** for shift-indexed tables.
- **Time:** host build; per-entry codegen O(entries × popcount).
- **Space:** emitted `.fj` size feeds **R-2** (assemble time) + the span ledger; per-entry ~2–3× per-result-nibble on wide tables.
- **Testing:** per-table generated tests (D12, bit-exact): **every entry** + a **call-twice-per-entry** check (#8 — verifies result-reg/jumper cleanup), both emit modes, over-aligned and not.
- **Open Qs:** texture-table span (OQ8); the per-table mode heuristic (D4 override).

#### H3 — Map compiler
- **Purpose:** Compile a WAD level into baked `.fj` BSP structures the fj renderer walks.
- **Supplies:** `compile_map(wad, level) -> .fj` emitting NODES/SSECTORS/SEGS/SECTORS/SIDEDEFS/LINEDEFS/VERTEXES as sequential packed streams + the root-node entry point. **Emit mode (opt #7, §1.1.3):** either packed **data streams** (small, ~42@/byte to walk) or **BSP-as-code** — each node compiled to a code block with its partition line as compile-time constants (no per-node reads; side test becomes a `mul_const`). Code is ~1.5M/frame cheaper but costs program size + assemble time (R-2) and recompiles per level; the generator supports both, R1 picks per the measured read cost.
- **Depends/related:** H1; consumed by F5; mirrored by H5.
- **Assumes:** D1 = BSP; 16.16 coords (D6); coords fit w=32; F5 reads streams with `*_and_inc` (§3.4).
- **Data & layout:** sequential streams in the data region (no pow2 align); span = Σ lump sizes (§1.2).
- **Time / Space:** host build; stream span filled R0 (E1M1). **Per-element read cost (S2):** each streamed byte the walk consumes is a `hex.read_byte_and_inc` ≈ **42@** (`w(0.75@+5)+18@+27`, w=32) — the read is O(w) even sequentially; only the *re-indexing* is saved vs `read_nth_*` (~103@, O(w) *twice*). So per-node/per-seg field count is a first-order cost — **minimize streamed fields**, and pack multi-field records so one walk consumes them contiguously.
- **Testing:** unit-test compiled structures vs parsed WAD (counts + sample records); the walk validated by golden frames (D12).
- **Open Qs:** BSP traversal cost at E1M1 scale (R1); which seg/sidedef fields are actually needed (each ≈ 42@/byte/visit — keep the per-node record minimal).

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
- **Supplies:** wrappers over `assemble_and_run_test_output` / `run` + `FixedIO` / `InMemoryScreen` / `PcIO.headless`; sha256 golden compare vs H5; per-table runner (#8: every-entry + call-twice). **Profilers:** `--profile` (run) = per-region op-count / *time*; `--stats` (assemble) = macro *code-size*/usage — textual **only if plotly is absent** (verified absent in this environment — S2: `import plotly` fails — so textual output is available; keep plotly out of the build/CI env to preserve it).
- **Depends/related:** flipjump APIs, H5 (oracle).
- **Assumes:** deterministic runs; bit-exact (D12); scripted key-event files for E2E.
- **Data & layout:** fixtures (golden frames, event scripts, table fixtures) in-repo (Freedoom-derived where redistributable).
- **Time / Space:** CI cost.
- **Testing:** harness self-checked on a trivial program.
- **Open Qs:** *(resolved S2)* `PcIO.headless(events_file, frames_dir)` **exists** — `flipjump.interpreter.io_devices.pygame_window.PcIO.headless`, signature exactly as the handoff §1.1 states; `InMemoryScreen` is screen-only (no input), so input+screen headless replay uses `PcIO.headless`. Residual: it **requires pygame** (not supported on Windows py3.14; py3.13 OK — §H), so CI pins a supported interpreter.

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
- **Supplies:** `hex.fixed_mul n,f,…`, `hex.fixed_div n,f,…,div0`, **PR #1's own** `hex.mul_const n,…,c` and `read_table`/`read_table_byte` fallback wrappers. *(Note: `mul_const`, `read_table`, `read_table_byte` are **not** stock 1.5.0 STL macros — verified S2; the STL has only `hex.mul`/`hex.mul10`/`bit.mul` and the `read_byte`/`read_nth_byte` pointer primitives (~1,064 ops each). PR #1 supplies these wrappers; the handoff §1.1 mis-attributed them to the STL. The `×const → shifts+adds` technique is sound regardless: cost scales with `popcount(const)` shifted adds, so sparse constants are cheap — the `mul_const` wrapper just packages it.)*
- **Depends/related:** `hex.*` STL (incl. `read_byte`/`read_nth_byte`, the actual pointer-read primitives); consumed by F5/F6.
- **Assumes:** `0 < f <= n`; full 2n-width product (D13); default 16.16 (D6); `hex.init`; `hex.scmp` for signables (§3.5).
- **Data & layout:** scratch `hex.vec` in F1's register region.
- **Time / Space:** per PR #1's documented complexities (e.g. `fixed_mul` ≈ 4n²(5.5@+20)+…); div is expensive ⇒ **LUT it in hot paths**, never call per pixel/column.
- **Testing:** PR #1's byte-exact tests (boundary inputs per path) — re-homed + CR'd in S5.0 (D15).
- **Open Qs:** narrow-intermediate opt (D13) only if a hot mul needs it.

#### F3 — LUT access layer
- **Purpose:** The dispatch-jumper idioms that read the generated tables, one per family, + the packed-byte deposit primitive.
- **Supplies:** `sample_texture`, `read_trig`, `read_reciprocal`/`read_scale`, `read_yslope`, `read_viewangle*`, `apply_colormap`, `deposit_pixel_byte` (D3: low-nibble std + high-nibble +4-offset table). Per-entry-handler dispatch (D4).
- **Trig / angle quantization (NOT 2³² entries):** index by the **top nibbles** of the 32-bit BAM angle, sized **N = 4096 = 16³** (top 3 nibbles — *no sub-nibble shift*, §2.1 16^x rule); 16² = 256 is the coarse span fallback. Multi-nibble index: xor each index nibble into the jumper at offset `4i+6` (`dw=2⁶`), then jump — generalizes the single-nibble `tables_init.fj` idiom. **Cosine shares the sine table** at `(idx + N/4) & (N-1)`, and the `+N/4` (=+1024=0x400) is a **single-hex add** (+4 to nibble 2), ~free — so a *separate* cosine LUT (≈+span) is **not** worth it (#9; revisit only if profiling disagrees). **Index discipline for the angle/projection tables (so the 2¹¹ sizes in §1.3 don't violate U6):** `finetangent` is angle-indexed exactly like `finesine` (top-3-nibble, 4096). `viewangletox` uses the *same* nibble-aligned top-nibble extraction but on a **front-FOV-reduced** fine angle, which lands in `[0, N/2)` ⇒ a **2048-entry** table. `xtoviewangle` is **not** angle-quantized at all — it is indexed by **column x** (a computed `0..W` integer) ⇒ 161 entries (pad 256). `tantoangle` is indexed by the `R_PointToAngle` **slope quotient** (a *computed* value in `[0, SLOPERANGE=2048]`), **not** a shift-extracted index — so 2048 (= 2¹¹) is fine for nibble-dispatch: the §2.1 16^x rule constrains indices *formed by shifting a wide value*, not values already computed into a small register. Trig is **per-column** ⇒ the canonical **per-result-nibble override (D4)** site for its 32-bit entries. Optional **quadrant fold** (N/4 + sign/reflect) = 4× smaller, deferred lever. The very-hot per-pixel tables (colormap/texture/deposit), not trig, are the **over-align** candidates (§2.1).
- **Depends/related:** H2/H4 tables; consumed by F4/F5.
- **Assumes:** indices nibble-aligned without runtime shift (U6); tables init'd before first use; shared `res`/`ret`.
- **Data & layout:** reads code-region tables; owns the +4-offset 256-entry table.
- **Time:** **~4@ per byte dispatch** (STL `hex.or` = `4@+10`; ≈ **100 ops at @ = 25**) — per-pixel sample+colormap = 2 dispatches; a 32-bit per-column trig read via per-result-nibble (D4) = ~8 dispatches but only 160×/frame. Feeds the texture-read + column-math budget lines (in **@**, per §1.1's @-note).
- **Space:** small idiom code + the +4-offset table.
- **Testing:** per-idiom byte-exact vs host reference; boundary/wrap indices.
- **Open Qs:** OQ9 (`fcall` nesting if idioms chain > 1 level) — *mechanism resolved* (§2.1 tiered `ret_reg`s); R1 only measures the actual depth.

#### F4 — Framebuffer + pixel-store layer
- **Purpose:** The packed-byte framebuffer (D3) + the full-unroll static deposit (D2b).
- **Supplies:** `framebuffer` base; `render_column x` (unrolled, fixed addresses); the deposit (via F3).
- **Depends/related:** F3 (deposit table), F1 (layout); consumed by F5 (writes), F7 (present reads base).
- **Assumes:** **write-only during render** (invariant); bpp=8 packed byte; **no clear** (U10 — every px written once, ceiling→wall→floor, no gaps); fixed compile-time addresses (D2b).
- **Data & layout:** framebuffer = W·H = 16K packed-byte ops (data region).
- **Time:** deposit ≈ 2 nibble dispatches ≈ **~4@/byte** (STL `hex.mov 2` proxy = `2·(2@)`; the real low-nibble + custom +4-offset deposit is ~comparable). Small probe: ~53 ops/byte at @≈9. **At @ = 25 the deposit is ~100 ops/byte ⇒ ~1.6M for 16K px** (the §1.1 Pixel-stores line). The custom *set-into-clean* mov-table (1 dispatch/nibble vs `hex.mov`'s zero+xor) is **optimization #5** (§1.1.2) — cuts it to ~2.5@, ~0.6M profit (×2 at bpp=4).
- **Space:** 16K-op framebuffer + the unrolled column code (**R-2** watch).
- **Testing:** deposit byte-exact incl. the high nibble; golden frames.
- **Open Qs:** D2 final (a vs b) settled by R1; deposit cost (R-1).

#### F5 — Renderer
- **Purpose:** BSP front-to-back walk (D1) → textured wall columns + floor/ceiling spans, lit (D11), into the 3D-view rect.
- **Supplies:** `render_3d_view` (the §E pass), `draw_column`/`draw_span` (body chosen by the `TEXTURED` flag).
- **Depends/related:** H3 (map), F3 (LUTs), F4 (framebuffer), F2 (math); first pass of the §E pipeline.
- **Assumes:** front-to-back no-overdraw (upholds U10); per-column colormap select (D11); scale via reciprocal LUT (**no runtime divides**); 16.16 (D6); §2 signed-compare ladder on signed deltas (`hex.sign` for the per-pixel select's sign tests, `hex.scmp` only for true magnitude compares).
- **Data & layout:** per-column scratch (top/bottom/colormap-sel) in fixed registers; reads map streams sequentially.
- **Time:** column math + BSP walk ~1.5–3M — the dominant consumer alongside stores/reads.
- **Space:** unrolled column code (**R-2**); visplane + clip arrays.
- **Testing:** golden frames vs H5 (bit-exact); per-column math unit checks.
- **Call discipline (#4/#11):** the BSP walk recurses, but **don't pay `stl.call`/`return` for most of it.** Use **tiered `fcall`/`fret`** (distinct `ret_reg` per level, §2.1) for the **bottom ~3 tree levels** — the bulk of node visits (~7/8 of a balanced tree) — and reserve the stack for the upper, unbounded-depth levels only. This strips the ~2.5w@ stack cost off most visits (big speedup). Per-column/per-pixel leaf bodies stay `fcall`-stackless.
- **Open Qs:** OQ4 (does column math fully reduce to LUTs+adds? R1); visplane + clip-array design.

#### F6 — Game loop & tic
- **Purpose:** The 1:1 loop (D9): poll → update `keydown[]` → S0 sim → render → present, every frame.
- **Supplies:** the **program entry / mainline init** — `main: stl.startup_and_init_all` (§3) runs once before the loop, **supplying the `hex.init` + `stl.ptr_init` + `stl.stack_init 100` that F2/F3/F5/H2 *assume*** (hex truth tables for every dispatch/hex op, pointer machinery for the §3.4 sequential stream reads, and the call stack for F5's BSP upper levels). Then `main_loop`, `poll_input`, `sim_tic` (S0: turn / move / wall-slide collide), present call. **Level handling (multi-level binary):** a **level table** — one entry per baked level (E1M1–E1M9) holding its BSP-as-code root (+ later thing-list, par, sky) — indexed by `current_level`; `goto_level N` sets `current_bsp_root` + resets player state (a 9-entry dispatch, once per switch). **Per-frame cost: one indirect jump** to `current_bsp_root` (everything else — textures/LUTs/renderer/player — is shared, constant-address; §1.2 multi-level note). Switch triggers: **progression** (exit linedef/switch → `current_level++`, the DOOM-faithful default, S1-era logic) and a **select menu** (episode/level — F8/R3, or a minimal "warp 1–9" debug build early).
- **Depends/related:** F7 (poll/present), F5 (render), F4; S1/S2 flag-gated (D7, §D). **Init order:** `stl.startup_and_init_all` is the first mainline op; the generated dispatch tables are static CODE laid out *below* `main` (jumped over by `;main`, §3) — present at assemble time, no runtime init — so every component's "tables init'd before first use" assumption reduces to "the startup ran," which it always has by the time the loop body executes.
- **Assumes:** no timer device — frame counter is the clock; tic:render 1:1; `keydown[]` in registers; signed deltas via `hex.scmp`; **BSP recursion depth ≤ the `stl.stack_init 100` stack (E1M1 depth is well under 100; F5 also strips the bottom levels off the stack via tiered `fcall`)**. **Fully deterministic: no true RNG.** R2 (render + S0) uses no randomness at all. When combat/AI land (S1/S2, R3+) they use DOOM's deterministic `P_Random` — a hardcoded 256-byte `rndtable` + an advancing `rndindex` (`rndtable[++rndindex & 0xff]`) — emitted as a byte-LUT via H2, read via F3. This *preserves* D12 (a true RNG would break bit-exact golden frames + deterministic replay); H5 uses the same table + index so sequences match exactly.
- **Data & layout:** player state (pos/angle/eye) + `keydown[]` in fixed registers.
- **Time:** S0 ~few K ops/tic (cheap class: tile lookups, signed compares, adds).
- **Space:** small.
- **Testing:** scripted-replay E2E — sim state matches H5 exactly after a key sequence (D12); collision boundary cases.
- **Open Qs:** collision model (axis-separated slide, §D); S1/S2 scope (D7); level-table layout + progression vs select-menu timing (multi-level, this review).

#### F7 — Present layer
- **Purpose:** Drive the screen device over the output stream (init/palette/present/input).
- **Supplies:** `init_screen`, `set_palette`, `present` (`update_screen` 0x03), input-poll helpers; `update_rectangle` (0x04) reserved for status-bar/menu rects.
- **Depends/related:** F4 (framebuffer base), H4 (palette); the device (below).
- **Assumes / Device contract (read from `ScreenIO.py`, authoritative):**
  - `[0x01][w:2][h:2][bpp:1][palette_size:2]` init (bpp ∈ {4,8}); `[0x02][palette_addr:w/8]` set_palette; `[0x03][screen_addr:w/8]` update_screen (primary present, memory-hook, ~free); `[0x04][x,y,rw,rh:2 each][screen_addr:w/8]` update_rectangle (reads the *full-screen* base with screen stride — status-bar/menu only); `[0x05]` raw in-stream — **don't use**.
  - **Framebuffer:** pixel `(px,py)` = packed byte at `screen_addr + (px + py·W)·dw`, masked to bpp. One byte/op, stride `dw`, row-major.
  - **Palette:** entry `k` = 3 packed bytes R,G,B at `palette_addr + 3k·dw`.
  - Keyboard (input side of `pc`): non-blocking, tic-based — one status poll (`0x0` none / `0x8` up / `0x9` down) then one keycode byte on events; keycodes ASCII-like `<0x80`, arrows/shift/ctrl/alt `0x80–0x86` (§1.1).
- **Present-path rationale — memory-hook (0x03) over raw-stream (0x05):** *decisive reason = render order ≠ scan order.* The raw stream demands W·H bytes in **row-major** order; DOOM/BSP renders **column-major + front-to-back** with overdraw and multi-segment columns, so pixels are produced out of scan order. The framebuffer decouples render order from scan order; 0x03 then scans out the finished buffer for ~free (~70 ops/frame). *Per byte (@-invariant comparison):* raw output ≈ **~2@** vs deposit ≈ **~4@** — so raw output *is* ~2× cheaper per pixel, BUT that only helps if you emit directly row-major with **no** framebuffer (forfeits incremental `frac+=step` column sampling, and is impossible for multi-segment BSP columns). *With* a framebuffer (which BSP requires), 0x03 (deposit + ~70/frame) beats 0x05 (deposit + ~2@/px ⇒ **+~0.8M/frame at @ = 25**). So 0x03 is strictly better here.
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

- **R-1** — Budget estimates are projections; S5.3 measures before R2 commits. **At the @ = 25 working point the optimized per-pixel work alone is ~11.2M and the full frame ~14–16M — *over* the 11.2M budget at full fidelity** (§1.1): three optimisms were corrected in S2 — the budget is **@-proportional**, the per-pixel line was under-counted (DDA + select, §1.1.1), and the DDA's optimized cost was itself under-estimated (each nibble-add is ~4@, so the 8.8+accumulator DDA is ~11@/px, not ~5@). fps is continuous (D9), so this isn't a hard wall: applying the §1.1.2 optimization set (**#1–9**, incl. the §1.1.3 column rebuild's BSP-as-code) lands the full-res-textured frame at **~14M ⇒ ~20 fps — the chosen target** (§1 curve); reaching 25 fps (~11.2M) or buying margin is then a **fidelity lever** (flat-colored floors ~9M ⇒ ~30 fps / 12.5 fps / bpp=4), not a further per-pixel optimization. #1–2 are mandatory just to reach the per-pixel baseline. **Top R-1 tasks: measure @ *and* the real per-pixel DDA cost.** Fallbacks: flat-colored floors / flat-shaded / 12.5 fps / bpp=4.
- **R-2** — Assembler scalability is load-bearing (column-unroll + mega dispatch tables). Measure assemble time + `.fjm` size at game scale (S5.1/S5.3); relief valve = design (a) column buffer.
- **R-3** — Span vs flat path: power-of-two padding can silently overflow → paged (~2.5× slower). Guards: span ledger + `storage_mode` assertion.
- **R-4** — D3 encoding tension (hex-memory pixels vs packed-byte device read) — resolve in this doc, not in code.
- **R-5** — *(cleared)* flipjump 1.5.0 released. We use **no speculation tier**; the 320×200 stretch instead rides flat-run + our own optimizations toward ~400M+ (revisit at R2). flipjump is near-frozen but **extensible** (§2.1) — a device/engine change is a justified last-resort lever, not a dependency.
- **R-6** — Fidelity unknowns: 8.8 wobble (D6), 32×32→64 intermediates (U5/D13), `@` growth (U7) — survive re-baselining, now with more headroom.

---

## 8. Open questions (inherited, mapped to D-items)

OQ4 (does per-column math reduce fully to LUTs+adds? → D2/R1) · OQ5 (16.16 vs 8.8 wobble → D6) ·
OQ8 (map/texture dispatch tables small enough for compile+span? → D5/R-2/R-3) · OQ9 (`fcall`
non-reentrancy — **mechanism resolved** in §2.1: distinct `ret_reg` per call-graph level makes any
bounded non-recursive depth stackless; what R1 still *measures* is the actual nesting depth of the
hot call chains, which doesn't change the approach) · OQ10 (variable fps vs worst-case cap → D9).
