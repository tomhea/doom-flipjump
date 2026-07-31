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
