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

| P7-1 | P7 | delete 3 `hex.zero` the next `hex.mov` already performs | +4,077 / -35,442 / -14,229 / -25,121 | **18,754,902** (-16,249, -0.09%) | SHIP | (commit) |

**P7-1 detail.** `hex.mov` zeroes its destination before xoring the source in -- proved on the
interpreter by moving into a PRE-DIRTIED register, which is the first hard evidence for a fact
the source only asserted in a comment. So `lines_pclm_index2`'s `hex.zero w/4, tmp` (full cover)
and `scale_recip_div`'s two `hex.zero 14` (partial cover, uncovered nibbles written by nothing in
the tree) are dead. -122 / -196 / -202 executed ops per call.

> ⚠ **FREEZE RESIDUAL: -192 ops, CARRY IT FORWARD.** 20,682 labels moved -192 (plus 4 at -256,
> 1 at -128, 1 at -64), so the real deletion was 1,312 ops against micro.py's 1,104 -- a 208-op
> under-estimate, an order worse than P1-3's 16. Deleting a `hex.zero` removes wflips whose
> operands are REAL ADDRESSES, and their emitted size is popcount-driven (FINDINGS N), so the
> micro estimate is weakest exactly for deletions. One deg viewpoint got WORSE (+4,077) and the
> sweep MAX went +164 while the median improved -- that is the placement de-tuning a -192 shift
> causes. **The next filler carries +192.**

| P2-1 | P2 | `frame.ptr_index`: the stl macro with the chained add, 22 sites | -104,166 / -54,902 / -93,042 / -71,704 | **18,697,401** (-57,501, -0.31%) | SHIP | (commit) |

**P2-1 detail.** `hex.ptr_index` is 1,196.8 executed ops per call and runs ~760x per median
frame; 554.8 of that is one `hex.add w/4`. Swapping it for `frame.add8_chain` needs NO bound on
anything, applies at every site, and is SIZE-IDENTICAL -- so a 22-site change moved 0 of 781,326
labels. All four deg viewpoints improved. Predicted -64k, got -57,501.
The filler carrying P7-1's +192 residual was right: freeze exact.

| P2-2 | P2 | `ptr_index` shift stage at the proven width, 19 of 22 sites | -123,377 / -94,831 / -131,202 / -120,621 | **18,624,169** (-73,232, -0.39%) | SHIP | (commit) |

**P2-2 detail.** 12 sites at width 4 (column indices, proven <= 161), 4 at width 5 (column x 16,
<= 2,576), 3 at width 6 (the two 4-nibble packed indices); the three sprite-BLOCK indices stay at
8. Per-call: -219 / -151 / -87 including the jump.
THE FILLER LIVES INSIDE THE MACRO, behind its own jump, so each of the 19 expansions compensates
itself and no local fillers were needed anywhere: **freeze exact, 0 of 781,326 labels moved**.
All four deg viewpoints improved by ~0.4%. Predicted -100k..-130k, got -73,232.

### Running total after 7 ideas: 18,982,338 -> 18,624,169 = **-358,169 (-1.89%)**

| P2-3 | P2 | the pointer ARM narrowed to 5 hexes in `read0_byte_and_inc` | -235,780 / -126,209 / -160,718 / -117,494 | **18,474,050** (-150,118, -0.81%) | SHIP | (commit) |

**P2-3 detail -- the biggest idea so far.** The arm is 192.0 executed ops and runs ~10,526 times
per median frame. A 5-hex arm (121.8) is exact whenever consecutive armed addresses agree above
nibble 4; all 30 call sites walk `sfslot_p`/`spslot_p`, and a 10-agent census proved every
reachable predecessor arm in both loaders is also in the sub-2^20 hot-data block -- so even the
FIRST read of a run is safe and no restructuring was needed.
Three adversarial lenses attacked the proof and NONE refuted it, but two changed the design:
width 4 is unsafe (column 5 piece 0 runs 0x8FFC0 -> 0x90080, changing nibbles 3 AND 4), and the
scope grew from "later reads in a run" to every read.
The filler sits inside `arm5` itself, so every macro built on it is automatically size-identical
to its 8-hex twin: **freeze exact, 0 of 781,326 labels moved**.

> ⚠ **A MACHINE-CHECKED INVARIANT NOW GUARDS THIS.** The narrow arm is exact only while every
> narrow-armed table lies in one 16^5 window. fj has no assert directive and rep() cannot take a
> label-dependent count, so `ritual.py` checks it on every build and refuses to keep artifacts if
> violated: *hot-data block pclm(0x873C0)..wrej(0xE3740), 1,827 ops of headroom*. This is NOT
> hypothetical -- config.py sets SLOT_SHIFT = 2 as soon as PID_BYTES becomes 2, which makes
> sfslot alone 2,621,440 bits and would break every narrow arm silently.

### Running total after 8 ideas: 18,982,338 -> 18,474,050 = **-508,288 (-2.68%)**

| P2-4 | P2 | the narrow arm on the ts piece writes (8 `write_byte_and_inc` + 1 `write_byte`) | -185,592 / -153,913 / -128,870 / -141,972 | **18,388,677** (-85,373, -0.46%) | SHIP | (commit) |

**P2-4 detail.** `ts_piece_wr` writes a 4-byte piece twice over (first-piece and later-piece
branches), all eight writes walking `fbp` through sfslot; `ts_piece_store` then writes the flag
byte through sfflag. Both tables are in the hot-data block, so all nine take `arm5`.
Because arm5 carries its own filler, the whole family (`read_byte5`, `read_hex5`, `write_byte5`,
`write_byte_and_inc5`) is size-identical to its stl twins: **freeze exact again**.

### Running total after 9 ideas: 18,982,338 -> 18,388,677 = **-593,661 (-3.13%)**

| P2-5 | P2 | the narrow arm on the remaining 15 vetted sites | -221,650 / -128,149 / -180,151 / -126,275 | **18,233,878** (-154,799, -0.84%) | SHIP | (commit) |

**P2-5 detail.** The rest of the census's unconditional set: `ts_clamp2`/`ts_clamp2_lo`,
`ts_step_faces`'s sfflag read, `lines_steps_load2`, `lines_spr_load`, `lines_col_plane_ids`,
`seg_pass2_leaf_body_lines`'s drawn read, and in `thing_record_body` the sprflag read plus writes
2-7 of the spslot run and the slot-flag write.
PRECISION MATTERED: three sites share the exact text `hex.read_byte pval8, pptr` and only ONE
(`lines_col_plane_ids`) was cleared -- the copies in `seg_pass1_leaf_body_ts` and
`lines_col_plane` can be reached with a sprite-bank arm standing. Line-targeted edits with
content assertions, not text substitution, which would have silently taken all three. Same in
`thing_record_body`: the FIRST write of the spslot run keeps the full arm, the six after it do not.

### Running total after 10 ideas: 18,982,338 -> 18,233,878 = **-748,460 (-3.94%)**

| P2-6 | P2 | the prearmed write -- the arm was a no-op | -61,600 x4 (identical) | **18,171,018** (-62,860, -0.34%) | SHIP | (commit) |

**P2-6 detail -- a different mechanism: DELETE the arm, do not narrow it.** At three sites the
code reads through `pptr`, branches on the value, and on the taken branch writes through the SAME
`pptr` -- only the not-taken path does the `ptr_add`. `claim:`/`own:` each have exactly one
predecessor (that if0), and the read dance restores to_flip before returning, so the write's
`set_flip_and_jump_pointers` is a CLEAR then a SET of the identical address. -243.0 per site,
verified by writing through the prearmed form and reading the cell back (0x6D both ways).
Its precondition is far WEAKER than arm5's -- prearming does not care where the pointer points,
only that the arm already points there -- so it needs no window invariant and no cluster proof.
All four deg viewpoints moved by exactly -61,600: a fixed number of claims per frame.

### Running total after 11 ideas: 18,982,338 -> 18,171,018 = **-811,320 (-4.27%)**
The pointer pool (P2-1..P2-6) is **-594,650** of that, in six gates.
The arm family alone (P2-3/4/5) is **-390,290** of that, in three gates.
Every idea byte-exact 4/4 and 260/260. Freeze exact on 5 of 7 builds; the two residuals
(-16, -192) were carried forward and closed out.
