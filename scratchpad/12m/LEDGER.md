# LEDGER -- one row per idea attempt (the 12M campaign)

Append immediately after each gate, kills included. The main thread keeps only the one-line
result in context; this file is the campaign memory.

Format: | id | pool | mechanism (one line) | deg deltas | sweep median | verdict | commit |

## Baseline entering the campaign

sweep median **18,982,338** -- branch m4-nine-levels, tip acaed54.
Best binary of that build: the deg.fjm produced by census_ts5_cand (see _deg_ts5.log).
Rebuild it with: python scratchpad/popcount_census.py capture-doom --out <c.json.gz> --stl stock

## Prior work (closed -- context only, details in handoff sections 16-19)

| round | ideas | median | notes |
|---|---|---|---|
| campaign 1-11 | 11 shipped | 24,306,866 -> 20,775,735 | one-shadow, DDA, lockstep, T4, ... |
| campaign 12-20 | 9 shipped, 6 killed | -> 19,716,925 | chains (-464k biggest), placement rounds |
| ts round 1-5 | 5 shipped, 0 killed | -> 18,982,338 | width 8->5 (-386k biggest) |

## Phase 0 -- the certified baseline (BASE), built 2026-09-04

`python scratchpad/12m/ritual.py build --id BASE --census --stl stock`  -- 741 s, deg PASS 4/4.
Artifacts: `scratchpad/12m/atlas/BASE.{fjm,labels.tsv.gz,census.json.gz,deg.json}`
(11.3 MB image, 3,653,012 labels, 1,996,735 wflip sites). stl = flipjump-151 (the merged 1.5.1).

| viewpoint | ops | picture |
|---|---:|---|
| (664,291,0x18000000) | 35,838,410 | BYTE-EXACT |
| (1272,-724,0x40000000) | 28,387,620 | BYTE-EXACT |
| (1869,479,0x80000000) | 32,708,537 | BYTE-EXACT |
| (-416,256,0x0) | 26,804,943 | BYTE-EXACT |

These four are the deg gate's WORST CASES, not the ship criterion; the sweep median is.

**Population control.** `frames.py` re-measured all 260 sweep frames on BASE.fjm and got
MEDIAN **18,982,338** -- the exact number the campaign's baseline claims. min 3,670,504,
p25 15,313,648, p75 23,773,801, max 39,514,873. So BASE.fjm IS the certified binary, proven
by re-measurement rather than by provenance.

## The 12M campaign

| id | pool | mechanism | deg | sweep median | verdict | commit |
|---|---|---|---|---|---|---|
| P1-1 | P1 | `frame.clip_rows` width 8 -> 5 | -109,218 / -107,200 / -110,364 / -107,200 | **18,875,138** (-107,200, -0.56%) | SHIP | (this commit) |

**P1-1 detail.** `top`/`bottom` arrive from `hex.sign_extend 8, 4`, so nibbles 4-7 are sign
copies; width 4 is NOT safe because `fstart = bottom+1` reads negative there at bottom = 32767,
while at width 5 the VALUE is identical. micro.py measured -363 executed ops/call and -1,360 ops
of space over 9 interpreter cases with identical outputs; 1,360 filler ops behind the `scmp`
(which never falls through) froze the layout: **0 of 781,326 top-level labels moved**.
Sweep MIN and MAX both moved by exactly -107,200 -- the saving is constant across all 260 frames,
so clip_rows runs a fixed number of times per frame regardless of viewpoint.
Estimate vs actual: predicted ~81k from the atlas region price, got 107,200 (25% low). micro.py
estimates are within tens of percent here -- nothing like the historical 5-9x optimism.
| P1-2 | P1 | `proj.column_params_dda` tail width 8 -> 5 | -7,238 / -4,428 / -10,002 / -4,160 | **18,870,978** (-4,160, -0.02%) | SHIP (thin) | (commit) |

**P1-2 detail.** clip_rows is the only reader of `top`/`bottom`, so the producer stopped
maintaining nibbles 5-7. Byte-exact 4/4 and 260/260, freeze exact again (0 of 781,326 moved).
But it delivered -4,160 against a ~30,000 estimate: `sign_extend`'s cost is a wflip by the sign,
which is ~1 op when the target nibbles are already 0 -- and `shr_hex` had just zeroed them. See
FINDINGS section M: narrow STRUCTURAL ops (mov/cmp/zero/inc, ~28 executed ops per nibble
regardless of value), not VALUE-DEPENDENT ones (sign_extend/set/xor, popcount of the delta).

| P1-3 | P1 | shift adjacency at 2 sites (`lines_sky_base`, `thing_record_body`'s trb_u) | -102,922 / -29,106 / -107,288 / -64,213 | **18,771,151** (-99,827, -0.53%) | SHIP | (commit) |

**P1-3 detail.** `hex.mov N, t, src` followed by `hex.shr_hex N, K, t` is byte-identically
`hex.mov r, t, src + K*dw` when t is read at width r and K is a whole-nibble shift, because
shr_hex's result nibble i IS source nibble i+K. Measured identical over 8 values;
-279 executed ops/call at the sky site, -243 at trb_u. Structural ops, so the estimate held:
predicted ~-79k, got -99,827.

> ⚠ **FREEZE RESIDUAL: -16 ops, CARRY IT FORWARD.** 20,683 labels all moved by exactly -16 ops
> (a clean single-mode shift), so the fillers were 16 ops short in total. micro.py's SPACE
> figure is measured in a micro program where every address differs from the real one, and a
> `wflip` emits one op per SET BIT of its value -- so emitted size is address-dependent and
> micro's space number is close but not exact. **The next idea's filler must be 16 ops LARGER**
> than its own measured delta. This is invariant C-2 doing its job.
