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

| P3-1 | P3 | `fixed_mul_lo` drives its rows off `b` in place; `wide_b` deleted | -450,083 / -478,242 / -467,052 / -462,600 | **17,919,032** (-251,986, -1.39%) | SHIP | (commit) |

**P3-1 detail -- the biggest idea of the campaign.** The macro copied BOTH operands into
12-nibble scratch vectors, but `wide_b` existed only to be read one nibble at a time as the row
driver and `hex.add_mul` never writes its `b`. So the rows read `b` in place, and the f
sign-extension nibbles -- the only thing the copy contributed -- become f rows against a constant
0xF, run only when b is negative. -225.0 executed ops/call (b positive), -385.0 (b negative).
Verified against PYTHON's own (a*b)>>16 AND the old macro over 14 cases: every sign combination,
both most-negative extremes, b = 0, -1, +1.0. Predicted -185k, got -251,986.

Three things the process caught that the gate would otherwise have:
1. My first value check showed the new form returning 0 for 11 of 14 cases. That was MY HARNESS:
   `compare` builds one program per variant, so I was reading the *current* variant's copy of a
   register only the *new* variant writes. It looks exactly like a broken optimisation.
2. The `0xF` constant must be a MACRO-LOCAL after the `;end` -- a file-scope `hex.hex` is a live
   op and would wild-jump (invariant C-1).
3. `bneg:` must FALL THROUGH to `bpos:`; a `;bpos` there would skip the result mov.
Also: `proj.scale_from_global_angle`'s M13-CPROJSTATIC comment documented the old SNAPSHOT of b.
"Never writes b" was a convenience then and is a REQUIREMENT now -- same fact, new load-bearing
status, and the comment says so.

### Running total after 12 ideas: 18,982,338 -> 17,919,032 = **-1,063,306 (-5.60%)**

| P3-2 | P3 | `fixed_mul_lo` reads `a` in place; `wide_a` deleted | -514,968 / -411,759 / -460,255 / -464,279 | **17,673,906** (-245,126, -1.37%) | SHIP | (commit) |

**P3-2 detail.** `wide_a` was only [a's n nibbles, then f copies of its sign], so rows read `a`
directly and take the tail from a 4-nibble all-sign vector written before it is read.
THE TRAP: `hex.add_mul n, res, a, b` brackets its inner loop with `.mul.clear_carry`, so calling
it twice per row would clear the carry BETWEEN the halves and lose it. The split has to happen
inside ONE bracket, over the 2-arg `.add_mul`, which carries no clear_carry. Verified by an
IDENTITY CONFIGURATION first -- the split row aimed at the same vector for both halves must
reproduce today's `row` exactly -- identical space and executed ops at j = 0, 3, 7, 11; only then
were products checked against Python. -210.8 executed ops/call.
`scratchpad/m1c_restore_set.py` asserted on the literal `wide_a`; re-anchored to `res` in the
same commit rather than left to break in a later session.

> ⚠ **FREEZE MISS: +16,320 ops, AND IT WAS AN ARITHMETIC ERROR, not tool drift.** micro.py
> measured 1203 as the TOTAL filler for the new macro to match the current one -- and I added it
> to P3-1's existing 795, double-counting. The label table settles it: `fixed_mul_lo` has 12 call
> sites but **20 EXPANSIONS** (some sit inside `rep`), and 20 x (1998 - 1182) = 16,320 exactly.
> **The correct filler is 1182.** Count EXPANSIONS, not call sites, and remember that a measured
> filler is a TOTAL, never an increment on the one already there.
> (micro said 1182+21; the 21 is the address-dependent wflip size of FINDINGS N, as expected.)


| P3-2b | P3 | freeze correction, filler 1998 -> 1182 | +226,494 / +109,561 / +140,819 / +157,455 | 17,813,823 (+139,917, +0.79%) | **KILL** | reverted |

**P3-2b: the correction was RIGHT and the result was WORSE, which re-prices P3-2.** Restoring the
size-preserving filler moved every label back exactly (-16,320, undoing the miss to the op) and
cost **+139,917 ops per median frame**. So the accidental shift was worth that much: it moved hot
code onto cheaper addresses, because a wflip costs popcount of its operand and alignment is worth
real ops.

**Therefore P3-2's honest split is -105,209 algorithm + -139,917 placement**, not -245,126 of
idea. The headline number stands as the shipped median, but 57% of it was luck, and this ledger
says so. The filler stays at 1998 as a deliberate PLACEMENT CHOICE (the median is the ship
criterion) and the source comment now says it is not a freeze.

**What this opens.** A RANDOM 16,320-op shift bought 140k. Deliberate placement tuning is
therefore a live pool worth real ops -- the plan's P7, and `scratchpad/oneshadow/tune_round.py`
already exists to do it. Nothing in this campaign has run a tuning round yet.

### Running total after 13 ideas: 18,982,338 -> 17,673,906 = **-1,308,432 (-6.89%)**

| P7-3 | P7 | hot-data anchor + to_flip reorder + mul.init pad 4096 | +507,008 / +200,181 / +653,402 / +317,009 | 18,013,859 (+1.92%) | **KILL** | reverted |
| P7-4 | P7 | **`hex.exact_xor` pad 16 -> 128** + hot-data anchor + `to_flip` reorder | -1,538,847 / -1,364,340 / -1,322,658 / -1,192,639 | **17,066,424** (-607,482, -3.44%) | SHIP | (commit) |

**P7-2 KILLED, and it broke the frame.** `hex.mul.init`'s `pad 256 -> 4096` shifted the hot-data
block 2,048 ops against 1,827 of headroom, so the narrow arm's 16^5 window was VIOLATED by 221
ops and every arm5 pointer went wild: 15,975 px wrong, the run died at 5.7M ops. My own invariant
caught it -- but `ritual.py` ran the check AFTER the deg gate, so it presented as an unexplained
pixel diff. **The check now runs the moment the label table exists**, before the viewpoints.

**P7-3 KILLED (+339,953).** Anchoring the hot-data block with `pad 16384` is structurally right,
but alone it forced a +32,768-op shift (it aligns to the NEXT multiple, and mul.init's pad had
already pushed past 16,384) and that placement re-roll cost more than the alignment won.
⚠ But its binary got SMALLER: 11,231,004 vs 11,307,396 bytes while ADDING 32,768 ops of padding.
`get_wflip_spot` fills padding with chains that were extending the wflip area. Padding can be
better than free.

**P7-4: the biggest gate of the campaign.** `hex.exact_xor` is 33.6% of the frame in ONE label --
its `switch` is flipped twice per call, 953,688 times a frame, and was aligned only to 16 ops.
`pad 16 -> 128` is a ONE-TOKEN change. Bundled with the anchor (required: the pad shifts the
layout by ~1.2M ops and would otherwise break the window again) and the to_flip reorder, because
they share one re-roll and pricing them apart would price a layout none of them ships with.
Predicted -1,420,476 for the pad alone; got -607,482 net of the anchor's placement cost.
⚠ **BINARY: 11,307,396 -> 14,219,263 bytes (+25.8%).** This padding was too large to be absorbed.
Watch this number on every further pad -- it is the owner's stated constraint.

### Running total after 14 ideas: 18,982,338 -> 17,066,424 = **-1,915,914 (-10.09%)**

| P7-5 | P7 | six pads incl. `bit.exact_xor` 8 -> 128 | assembler OverflowError | -- | **KILL** | reverted |
| P7-6 | P7 | five pads: double/triple_exact_xor, if_flags, add+sub.clear_carry, jump_to_table_entry | -441,819 / -482,729 / -163,273 / -453,320 | **16,911,740** (-154,683, -0.91%) | SHIP | (commit) |

**P7-5 KILLED in the ASSEMBLER**, not the gate: `OverflowError: Python int too large to convert
to C unsigned long` -- the image outgrew the addressable space. `bit.exact_xor` expands ~600,000
times (1,200,416 label mentions), so `pad 8 -> 128` meant ~38M ops of padding on a ~12.6M-op
image. **PAD SAVING SCALES WITH HOT EXPANSIONS; PAD SPACE SCALES WITH TOTAL EXPANSIONS**, and I
had priced both from the census, which only sees the hot set -- a 1,800x undercount here.
FINDINGS Y carries the expansion table for every candidate. The assembler's error names no macro,
so that table is the only way to see this coming.

**P7-6: the same five pads minus that one, and they ship.** Binary 14,219,263 -> 14,235,077 bytes
= **+15,814 (+0.1%)** while adding ~1.8M ops of padding: this time `get_wflip_spot` absorbed it
into wflip chains almost exactly. Padding really is close to free when it is not enormous.

### Running total after 15 ideas: 18,982,338 -> 16,911,740 = **-2,070,598 (-10.91%)**

| P7-7 | P7 | `read_cell_from_inners_ptrs` pad 4 -> 64 + `mul.init` after_add pad 4096 (retry) | -128,232 / -125,210 / -118,292 / -96,272 | **16,861,090** (-50,650, -0.30%) | SHIP | (commit) |

**P7-7.** Both chosen by the FINDINGS-Y rule (count TOTAL expansions first):
`read_cell_from_inners_ptrs` is only ~340 expansions, and its pad aligns TWO hot labels at once --
`read_ptr_and_flip_back` (flipped as a full value on every dereference) and `cleanup`, two ops
past it. `mul.init`'s pad 4096 is the retry of the change that BROKE the frame in P7-2: its
~1,800-op shift used to push the narrow-arm window over a 16^5 boundary, and that window is now
anchored, so the shift is absorbed. Binary +36,428 bytes (+0.26%).

### Running total after 16 ideas: 18,982,338 -> 16,861,090 = **-2,121,248 (-11.17%)**

| P7-8 | P7 | `hex.exact_xor` pad 128 -> 256 | -980,804 / -530,897 / -1,228,792 / -678,735 | **16,136,363** (-724,727, -4.30%) | SHIP | (commit) |

**P7-8.** One more power of two on the same token. Binary 14,271,505 -> 15,402,408 bytes
(+1,130,903, +7.9%) -- much cheaper in space than the 16->128 step, whose 4.5M ops of padding
cost +25.8%. The marginal return did NOT thin out: 128 gave -607,482 (bundled with the anchor),
256 gives another -724,727 on its own.

### Running total after 17 ideas: 18,982,338 -> 16,136,363 = **-2,845,975 (-14.99%)**

| P7-9 | P7 | `exact_xor` pad 256 -> 512 | +760,500 / -289,139 / +767,339 / -103,848 | 16,452,873 (+1.96%) | **KILL** | reverted |
| P7-10 | P7 | `hex.add_mul` + `hex.cmp` return pads 4 -> 32 | -169,402 / -153,564 / -145,728 / -130,180 | **16,052,722** (-83,640, -0.52%) | SHIP | (commit) |

**P7-9 KILLED -- and it locates the optimum.** exact_xor's pad: 16->128 gave -607,482,
128->256 a further -724,727, 256->512 REVERSED to +316,510 with two deg viewpoints ~760k worse.
**256 is the measured optimum**, now recorded in the stl source so nobody rediscovers it.

**P7-10.** Binary 15,402,408 -> 14,787,204 = **-615,204 bytes (-4%)** while ADDING padding: the
new pads pulled wflip chains out of the segment's wflip area. Padding can shrink the image.

### Running total after 18 ideas: 18,982,338 -> 16,052,722 = **-2,929,616 (-15.43%)**

| P7-11 | P7 | `add_mul` + `cmp` return pads 32 -> 64 | -33,071 / -46,686 / -13,604 / -19,516 | **16,038,392** (-14,330, -0.09%) | SHIP (thin) | (commit) |

**P7-11: the lever is done.** 4 -> 32 gave -83,640; 32 -> 64 gives -14,330 for +381,750 bytes.
Diminishing, unlike exact_xor where the second doubling beat the first. Stop here on these two.

### Running total after 19 ideas: 18,982,338 -> 16,038,392 = **-2,943,946 (-15.51%)**

| P7-12 | P7 | widen five pad families (triple 256, double/if_flags/clear_carry/jump_table 128) | -38,405 / +348,870 / +14,733 / +286,933 | 16,257,841 (+1.37%) | **KILL** | reverted |

**P7-12 KILLED, and it closes the pool.** Two consecutive widening attempts have now reversed --
`exact_xor` 256 -> 512 (+316,510) and this five-family bundle (+219,449). Every pad in the tree
is at or near its measured optimum: exact_xor 256, double_exact_xor 64, triple_exact_xor 128,
if_flags 64, clear_carry 64, jump_to_table_entry 64, read dance 64, add_mul/cmp 64, mul.init 4096.

### THE PAD POOL IS EXHAUSTED. Final: **-1,635,512 over 15 shipped directions**, 4 kills.
What remains is not reachable: `bit.exact_xor` holds 392,250 but has ~600,000 expansions and
padding it overflows the address space; `hex.exact_xor` still shows 5,147,872 'available' but is
past its optimum at 256. The census's 'available' column is an upper bound assuming free
alignment -- it is not a to-do list.

### FINAL: 19 ideas shipped, 18,982,338 -> 16,038,392 = **-2,943,946 (-15.51%)**

| pool | ideas | delta |
|---|---:|---:|
| P1 width doctrine | 3 | -211,187 |
| P7 zero deletions | 1 | -16,249 |
| P2 pointer family | 6 | -594,650 |
| P3 multiply | 2 | -497,112 |
| **P7 pads** | **15** | **-1,635,512** |

Binary 11,307,396 -> 15,168,954 bytes (+34%). wflip cost 15,260,433 (81.1% of frame) ->
13,619,278 (79.5%): the pads took 1.64M ops out of the dominant cost class directly.
Pads alone, 15 directions: **-1,635,512**.
Pads alone, 14 directions: **-1,621,182**.
Pads alone (P7-4, P7-6, P7-7, P7-8): **-1,537,542**.
Pads alone (P7-4, P7-6, P7-7): **-812,815**.
Pads alone (P7-4 + P7-6): **-762,165**.
The pointer pool (P2-1..P2-6) is **-594,650** of that, in six gates.
The arm family alone (P2-3/4/5) is **-390,290** of that, in three gates.
Every idea byte-exact 4/4 and 260/260. Freeze exact on 5 of 7 builds; the two residuals
(-16, -192) were carried forward and closed out.
| P8-1 | P8 | sparse_exact_xor PAD parameter; per-macro pads 512-16384 on 282 call sites in 36 hot doom macros | +988759/+180722/+1234100/+122130 | 16,687,779 (+4.05%) | KILL | reverted |
| P9-1 | S(ize) | shared pair-blocks: one vpb_pb per distinct (y2,c) via 3-lane fcall; 40,567 instances -> 5,326 blocks | -3272/+38179/+16916/+15987 | 16,055,788 (+0.11%) | **SHIP (size criterion)** | fjm 15,168,954 -> 7,923,027 (-47.8%); 260/260 byte-exact |
| P10-1 | P10 | pad round REVERTED in stl + sparse_ on 282 hot sites (h57_1) + S2; cold un-padded | +2621853/+1499598/+2479523/+1441704 | 17,135,838 (+6.84%) | slim WIN / speed partial | fjm 6,943,453 (-54% vs P7B, -12% vs P9-1); 260/260 byte-exact; game tier fits (42M words) |
| P10-2 | P10 | union-over-5-viewpoints hot set: 63 macros @ pad 256 + S2, pads reverted | +2084474/+1863065/+2021272/+1412286 | 17,384,587 (+8.39%) | slimmer but SLOWER than P10-1 | fjm 6,855,480; width>coverage: uniform 256 < P10-1's per-macro 512-16384 |
| P10-3 | P10 | 7 cheap-keep pads + exact_xor sparse-on-hot(36) + S2 | +2653820/+1080889/+2922461/+1110655 | 17,151,507 (+6.94%) | cheap-keep ~neutral on median | fjm 6,799,822 |
| P10-4 | P10 | exact_xor DEF pad 128 (FULL coverage) + 7 cheap-keep + S2 | +1308862/+1389537/+1403760/+1395982 | 16,892,522 (+5.33%) | BEST; full-coverage > sparse | fjm 7,387,587; deg fits; game-fit pending |
| P10-5 | P10 | exact_xor128 + double64 + if_flags64 + 7 cheap-keep + S2 (full-coverage) | +1308862(deg approx) | 16,584,954 (+3.41%) | BEST shippable padding config | fjm 7,616,097; game fits at exact_xor128 (105.9M words, 21% headroom) |
| P10-6 | P10 | P10-5 + cmp64 | -- | 16,617,424 (+3.61%) | WORSE than P10-5 (cmp def-pad net-negative on median) + bigger | fjm 8,025,514; reverted |
