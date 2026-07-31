# Frame-cost experiments — what worked, what didn't, and why

One row per experiment. **A result only counts if the frame is byte-exact** (or the deviation is
named and accepted); a number from a build that changed the picture is not a number. Prices are
E1M1, lines tier WPX+FT1+plane_near, at the three gate viewpoints unless stated.

Method rules this repo has already paid for:
* **price a kernel by ADDING it**, never by stubbing it — a stub prices itself plus everything
  downstream (`fj-cost-model`, the `noproj` retraction);
* **divide measured totals by MEASURED counts**, never modelled ones;
* at ~40M characters of program, **a ±1M frame delta is layout noise**, not signal (V4-A's spawn
  came out 856k "cheaper" purely from the bank growing the program).

---

## Baseline (start of the campaign)

| build | spawn | courtyard | tree | worst (-309,-44) |
|---|---:|---:|---:|---:|
| V1+V2 | 23,536,484 | 20,134,978 | — | 26,405,793 |
| +V3 step faces | 26,545,502 | 27,604,046 | — | 32,137,393 |
| +V4-A record half | 25,689,298 | 28,722,844 | 25,058,919 | 36,992,405 |

Owner's band: 30–35M on the worst frame is acceptable, 25–30M hoped for on a typical one.
**The worst viewpoint is the problem.**

Where the frame goes (ablation, `fj-cost-model`, pre-V3/V4):

| component | spawn | worst |
|---|---:|---:|
| BSP walk skeleton + per-seg xorby + startup/present | 3.88M | 3.91M |
| the wedge cull | 2.02M | 2.11M |
| all `point_to_angle` (post-ATANDISP) | ~1.70M | ~2.00M |
| WPX wall texture detail (vs a flat wall) | 2.86M | 1.69M |
| ceiling/floor band emit | 1.58M | 1.67M |
| residue: per-column loop, occlusion prescan, emit framing | 5.47M | 13.84M |

**The biggest single named item is two `hex.fixed_div 8,4` per pass-2 seg inside
`proj.wall_scale_setup_m` — 2.16M spawn / 3.93M worst.** `hex.fixed_div 8,4` is 38,500 ops, the
dearest primitive in the table.

---

## Experiment log

_(entries appended below as they are run)_

### V4 STATUS at the start of the campaign (2026-07-31)

`things=True` **renders**, and is **BYTE-EXACT at spawn and at the courtyard**. Two viewpoints still
differ: the tree (1,930 px / 95 columns) and the worst sweep point (35 px / 9 columns). The stream
itself is clean everywhere — 160/160 columns decoded, **zero** structural anomalies — so this is a
content/selection mismatch, not a malformed frame.

Six real bugs were found getting here, and five of them are the SAME class — **a value used at the
wrong width or the wrong scale**. Worth having in front of you before writing more fj:

| bug | symptom | why |
|---|---|---|
| `projection*0x10000` | frame differed by EXACTLY its sprite pixels | `proj` already carries the `<<16`; the second shift truncated xscale to 0, so every thing failed projection |
| `hex.add 8, dst, <hex.vec 2>` (x3) | ditto | an 8-nibble add reads EIGHT nibbles of its source, dragging the neighbouring registers in as high nibbles |
| block index shifted twice | ditto | the record stored `blk*32` into a 4-nibble slot (overflow) and the emit shifted again |
| `blkstride/8-1` for a ×32 shift | garbage pairs | ×32 needs 5 bit-shifts, not 3 |
| `hex.add w/4, ptr, sbase` on a SLOT offset | a creeping cycle of pairs through the whole bank | a slot offset must be scaled by `dw` to become an address — use `ptr_index`, which does it |
| missing `byte.emit y2r` | frame ended early / IndexError | a pair is TWO bytes; emitting only the colour desynchronises the stream |

**The tool that found them was not another build.** `scratchpad/v4_check.py` now caches the
assembled `.fjm` keyed on a hash of the sources, and `--trace` decodes the 0x0B stream and reports
the first structural anomaly. Diagnosis went from ~10 minutes per hypothesis to seconds.

**RESOLVED — V4 is now BYTE-EXACT at all four viewpoints.** The seventh bug was the same shape as
the sixth: fj's BSP walk drops subtrees with no one-sided seg **twice over** — `_lines_prune` at
compile time and `_lines_plane_gate`'s `tsstop` node gate at RUNTIME. Making a thing-carrying leaf
count as live for the compile-time prune alone changed nothing, because the runtime gate was still
skipping the node; the sprites in E1M1's open, purely two-sided courtyard were never projected.
Both predicates now treat a thing-carrying leaf as live.

**Any pruning a feature does not know about is a feature that silently does not run.** That is the
general form, and it will bite the next per-subsector feature too.

---

## EXP-1 — `slopediv_recip`: `read_table_packed 3` → D4 dispatch ✅ **KEEP**

The dispatch lever's **fourth** application (after tantoangle, slopediv_recip8 and xtoviewangle).
`proj.scale_recip_div` opened with a `read_table_packed 3` (~247@ = 3 × `read_byte_and_inc` plus a
`mul_const`); it runs twice per pass-2 seg, twice per step-face seg and once per projected thing.
Threaded as a COMPILE-TIME `disp` flag so the non-lines tiers, which have no `srdisp` table, keep
the packed read.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 28,104,383 | 28,026,843 | **−77,540** |
| courtyard | 36,010,624 | 34,662,751 | **−1,347,873** |
| tree | 45,252,666 | 43,458,960 | **−1,793,706** |
| worst | 39,448,264 | 38,468,873 | **−979,391** |

**BYTE-EXACT at all four.** Cost: +1.06M characters of program (41.70M → 42.76M).

The spawn delta is small because spawn has few pass-2 segs and no visible things; the lever scales
with the number of *projections*, which is exactly what a sprite-heavy frame has most of. That makes
it worth more, not less, once enemies are in.

## EXP-1a — attribution: what V4 actually costs (`--nothings` build) 📏

Building the same tree with `things=False` gives V4's price at every viewpoint cleanly (both frames
byte-exact, so neither number is contaminated):

| viewpoint | V3 only | V3+V4 | **V4 costs** |
|---|---:|---:|---:|
| spawn | 25,896,401 | 28,026,843 | +2.13M |
| courtyard | 27,112,631 | 34,662,751 | +7.55M |
| **tree** | **17,917,814** | **43,458,960** | **+25.54M** |
| worst | 31,389,542 | 38,468,873 | +7.08M |

**The tree viewpoint is the whole problem** — a cheap 17.9M frame becomes 43.5M once 24 large,
near billboards are projected and recorded. That is also the frame most like a future firefight, so
it is the right one to optimise against.

`scratchpad/v4_check.py --nothings` builds and gates the no-things tier; both binaries stay in the
cache, so the pair can be re-measured for free after any change.

## EXP-2 — reject before the divide, and test the cheaper flag first ✅ **KEEP**

Two independent reorderings, both **free** (they change no result, only when work happens):

1. `proj.project_thing` ran DOOM's `|tx| > tz<<2` off-screen reject AFTER `FixedDiv(projection, tz)`.
   The test needs only `tz` and `tx`, and rejects exactly the same set either way — so moving it
   BEFORE the divide costs nothing and saves a `hex.fixed_div 8,4` (**38,500 ops**, the dearest
   primitive in the table) for every thing that is off-screen. At a viewpoint where the budget binds,
   most things reached are off-screen.
2. The record loop read `drawn[x]` then `sprflag[x]`. The conjunction is symmetric, so reading the
   SPRITE flag first means a column a nearer thing already claimed costs one byte read, not two.

| viewpoint | before | after | delta |
|---|---:|---:|---:|
| spawn | 28,026,843 | 28,051,295 | +24,452 (noise) |
| courtyard | 34,662,751 | 34,333,993 | **−328,758** |
| tree | 43,458,960 | 40,714,308 | **−2,744,652** |
| worst | 38,468,873 | 38,030,062 | **−438,811** |

**BYTE-EXACT at all four.** Zero added program text.

The lesson generalises past this kernel: **an early-out is worth what it skips, so it belongs as
early as its inputs allow — not where the reference implementation happens to put it.** DOOM does
the divide first because on a 486 the divide was not 38,500× a compare.
