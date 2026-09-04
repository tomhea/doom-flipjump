# FINDINGS -- durable knowledge for the 12M campaign

Everything here was MEASURED or proven in-session. Read this before generating ideas; do not
re-derive. Append (never rewrite) as the campaign learns. Subagent reports contribute their
FUTURE-RELEVANT lines here verbatim.

## A. Measured op SIZES (emitted ops of space, w=32, micro-assembly with a labels spy)

These are the campaign's price list. Width scales nearly everything -- this table is why the
width doctrine (P1) is the highest-confidence pool.

| op | ops | op | ops |
|---|---|---|---|
| hex.scmp 8 | 1566 | hex.scmp 5 | 986 |
| hex.mov 8 | 514 | hex.mov 5 | 320 |
| hex.mov 4 | 256 | hex.mov 2 | 128 |
| hex.mov 1 | 63 | hex.if0 1 | 31 |
| hex.zero 8 | 255 | hex.zero 6 | 192 |
| hex.zero 5 | 160 | hex.zero 3 | 96 |
| hex.set 8 | 254 | hex.set 5 | 160 |
| hex.dec 8 | 260 | hex.dec 5 | 160 |
| hex.dec 1 | 36 | hex.inc 8 | 256 |
| hex.inc 5 | 160 | hex.sign 8 | 27 |
| hex.sign 5 | 32 | hex.shr_hex 8,4 | 315 |
| hex.sign_extend 8,4 | 180 | hex.sign_extend 5,4 | 68 |
| hex.add 8 | 962 | frame.add8_chain | 962 |
| hex.add 6 | 736 | frame.add6_chain | 738 |
| hex.read_byte_and_inc | 1590 | xor_byte_from_ptr + ptr_inc | 1520 |

Notes: hex.sign is nearly free and slightly LARGER at width 5 than 8 (27 -> 32) -- do not
narrow sign for size. hex.set cost is value-dependent (a 6-nibble constant measured 243 vs 254).
The chain macros are size-identical to their stl form, so chain swaps are layout-neutral.

## B. The cost model (settled)

- A wflip costs max(1, popcount(value)) EXECUTED ops. Chain dedup is space-only.
- Whole-program delta of a VALUE-ONLY change = sum over sites of visits x delta-popcount --
  this is what popcount_census predicts, accurate to ~1% at doom scale.
- A pointer deref pays a full arm (set_flip_and_jump_pointers, ~230 ops) plus the read/write
  dance (~180). Three alternating pointers in a loop means the arm never carries over -- that
  is the P2 opportunity.
- stl.fcall is ~2.5w@ per call.

## C. Invariants and hazards (each one cost a build or a gate to learn)

1. `0;0` filler is inert ONLY while unreachable. In a fall-through path the frame jumps to
   address 0 (seen: 10.5M ops, 15,875 px wrong). Put the loop-back jump FIRST.
2. Freeze fillers drift. VERIFY BY LABEL DIFF against the previous build every time; carry
   the residual into the next filler. 3 of 5 ts builds drifted (+80, +16, -80).
3. Adding a state REGISTER shifts every label after the state part (the parts line prints
   "state=N"). Declare new registers at the END of the block to minimize the ripple.
4. Deleting a macro's last reader leaves an unused extern -> werror. Grep the extern lists.
5. hex.cmp USES hex.tables.ret -- it is not chainable and must never appear inside a chain's
   hermetic window. hex.xor / xor_zero / zero / if0 / if_flags / shifts / sign_extend do NOT
   touch tables.ret and are safe inside a window.
6. Chain macros: from first wflip to last, hex.tables.ret holds a LIVE label. Inserting any
   table-driven dance inside a chain body = stale arm = wild jump.
7. Pair-fusing two chains LOSES at a tuned layout (all four gates worse) -- the fused
   brackets' labels are already cheap. Do not retry without new evidence.
8. A marking-seg-only change moves the MIN sweep frame by +-0. Use it as a confinement check.
9. Bounds already proven: tsf_face_scale < SCALE_MAX = 0x400000 < 16^6 (nibbles 6-7 always 0);
   step-face rows are signed 16-bit, so 5 nibbles suffice everywhere including row_b - 1.
10. deg_gate ends in sys.exit -- a wrapper must catch SystemExit or its own tail never runs.

## D. Tooling and harness lessons

- Heavy jobs: run DETACHED via PowerShell Start-Process + a Monitor watch. Background bash
  tasks in this harness were killed mid-run twice; detached processes survived.
- The tool layer eats one backslash level in heredocs: build patch strings with chr(10)/chr(9)/
  chr(92) or PowerShell single-quoted here-strings. Always ast.parse a patch script before
  running it, and make every patch assert its anchor count == 1.
- Edit/Write can fail with ENOENT on paths outside the working directory -- use PowerShell
  here-strings or bash for files in the flipjump repos.
- ca2_profile --bucket-bits 6 is per-op resolution (ip>>6 == one op at w=32); it has three
  built-in controls (hook sees every op, same op count, same picture) -- check they print ok.
- Pricing a macro region: sum the per-op histogram over the address interval between its
  labels, bucketed by the source-line tag in the label path. This is the section-19 method
  and it is how ATLAS.md gets built.

## E. What is already shipped (do not re-propose)

Chained add/sub at every direct call site (widths 2/4/8/10); the wall DDA; incremental
lockstep pointers; L-infinity far reject; drawn[] as one nibble; the loader dirty-skips;
zero-eliding burst reads; zero-before-overwrite trims; baked gate thresholds; per-seg lip
modes; fmask-gated DDA; the 5-nibble row datapath; the lip single-row; the width-6 scale
advance; five placement/tuning rounds. See LEDGER.md and handoff sections 16-19.

## F. Subagent spend (owner instruction: use simpler models)

Default HAIKU for subagents; escalate to sonnet only on a stated trigger (plan section 2.3),
opus only for panel synthesis and CR judgment on device/stl changes. Calibration: the two
idea panels of the previous campaign cost 2.6M and 1.8M subagent tokens at the inherited
model, and most of their work was mechanical file reading that haiku handles.

Record here, as evidence accumulates, which task CLASSES actually needed escalation -- the
tiering should get sharper with data, not stay a guess:
- (no entries yet)

## D2. Harness: detached jobs must be launched from the PowerShell TOOL, not the Bash tool
(2026-09-04) A `Start-Process ... -PassThru` issued through the **Bash** tool returned a live pid
and then died with the bash call: no log file was ever created and no python remained. The SAME
command issued through the **PowerShell** tool survived (pid alive, log growing). So the rule from
D is sharper than "use Start-Process": use the PowerShell tool to launch, then a Monitor watch on
the log file. Cost of learning it: one wasted launch (caught in 2 min by checking the log existed).

## G. The layout-freeze fillers -- current inventory (verified 2026-09-04, tip 2e04d82)

Every `rep(N, i) stl.fj 0, 0` in the tree, with the label it sits behind. A narrowing that
deletes K ops from a hot region GROWS one of these by K, in the SAME region, so the labels after
it do not move. Total reserved today: **24,837 ops**.

| where | rep N | sits behind |
|---|---|---|
| src/fj/frame_render.fj, ts_step_faces tail | 12,047 | the `c_stk` baked data (unreachable) |
| src/fj/frame_render.fj, lines_steps_load2 | 1,120 | the `p2_ldirty` data |
| src/fj/frame_render.fj, lines_spr_load | 980 | the `p2_sdirty` data |
| src/fj/frame_render.fj, seg_pass2_leaf_body_lines | 962 | `;col_loop` (the loop-back jump comes FIRST) |
| src/doomfj/wall_renderer.py, before seg_pass1_leaf | 5,136 | inter-leaf space |
| src/doomfj/wall_renderer.py, before seg_pass1_ts_leaf | 1,200 | inter-leaf space |
| src/doomfj/wall_renderer.py, before seg_pass2_leaf | 288 | inter-leaf space |
| src/doomfj/mapcompiler.py, before {L}_pos_leaf | 3,104 | the emitted `;{done_label}` |

All eight are literals (no computed rep counts), so a freeze adjustment is a one-number edit.

## H. Width-doctrine audit of frame_render.fj (subagent, sonnet, 2026-09-04)

**Geometry correction -- I had this wrong in the audit prompts:** this repo's view is
**VIEW_W=160, VIEW_H=100**, NOT 320x200. Both fit in exactly 2 nibbles, so raw column/row indices
in frame_render.fj are ALREADY tight. The remaining width slack lives in DERIVED fixed-point /
DDA registers, not in geometry indices. Do not tell a subagent "320x200" again.

**The shift-adjacency smell (general, two live sites).** The pattern

    hex.mov N, scratch, src        //  N-wide copy
    hex.shr_hex N, K, scratch      //  shr_hex's stl body touches ALL N nibbles regardless of
                                   //  how few the caller reads

is byte-identically replaced, whenever K is a WHOLE-NIBBLE shift, by

    hex.mov <result-width>, dst, src + K*dw

because shr_hex's body is `.zero times,dst; rep(n-times,i) xor_zero dst+i*dw, dst+(i+times)*dw`,
i.e. result nibble i IS source nibble i+K. Live at `frame.lines_sky_base` (viewangle>>24, then
read at width 2) and at `frame.thing_record_body`'s `trb_u` (frac>>16, read only at width 2
downstream: a `cmp 2` and a `mov 2`). Worth grepping the whole tree for `mov N,x,y` immediately
followed by `shr_hex N,K,x`.

**Producer/consumer width mismatch at `frame.clip_rows`.** It computes at width 8 on cexcl/fstart
although (a) its inputs `top`/`bottom` are built by `hex.sign_extend 8,4` in
`proj.column_params_dda` -- the same construction that macro's own comment already uses to justify
a width-4 signed compare -- and (b) every downstream reader of `p2_cexcl`/`p2_fstart` reads them at
width 2. Called unconditionally per not-drawn column in the main wall pass.

**Checked and EXCLUDED (do not re-propose without new evidence):** `proj.step_rows`'s
`ccyfix`/`prod` are mod-2^32 DDA arithmetic and genuinely need 8 nibbles. `plane_col`'s
`cph`/`spanph` (`hex.cmp 8`, ~16,000 calls/frame) is tempting but `planeheight =
|(plane_z<<16) - viewz|` has NO proven upper bound -- excluded for lack of a proof, not for lack
of value; a proof here is worth real ops.

**⚠ UNVERIFIED numbers.** The audit's "ops saved" came from linearly extrapolating the section-A
table, which measures emitted SPACE, not executed ops. Ranking is plausible; magnitudes are not
evidence. Extrapolated (never measured): `scmp 4 ~ 793`, `inc 4 ~ 128`, `zero 4 ~ 128`,
`shr_hex 8,6 ~ 286`. Label them UNVERIFIED anywhere they are quoted; only a sweep enters the ledger.

## I. Width-doctrine audit of projection.fj + stream_render.fj (subagent, sonnet, 2026-09-04)

**Shipped-resolution constants (config.py W=160, H=100).** VIEW_W=0xA0, VIEW_H=0x64, CENTERX=80,
CENTERY=50 all fit **2 nibbles**; CENTERX<<16 = 0x500000, CENTERY<<16 = 0x320000 and
PROJECTION<<16 = 0x500000 all fit **6**; SPRITE_MINZ = 4<<16 = 0x40000 fits **5**.

**`scale1`/`scale2` share tsf_face_scale's bound.** `scale_from_global_angle` clamps its output to
[SCALE_MIN, SCALE_MAX = 0x400000] (`sga_csmax`, emitted from wall_renderer), so the per-seg
`proj.scalestep` difference `sst_diff` is 6-nibble bound. ts5 narrowed only the per-COLUMN advance
in frame_render.fj; the per-SEG step computation in projection.fj was never touched.

**Dead in the shipped tier (do not audit again):** `proj.column_setup`, `column_render_params`,
`wall_screen_span`, `texture_u`, `wall_x_range`, `wall_setup`, `wedge_bbox*`, `point_to_angle_m`,
`slope_div_m`; and `w2s_wall` in stream_render.fj is a non-certified lab tier.
stream_render.fj is otherwise already tight (row/column math at width 2 or 4 with the bound stated
in-comment).

**Three traps, each of which would have shipped a wrong picture:**
1. Narrowing a WRITE to a register that is later read WIDER is safe only when (a) the register
   holds ONE unchanging compile-time constant on every call -- its high nibbles are then
   permanently 0 from initial zero memory -- or (b) every write AND read of it is narrowed
   together and nothing outside the file reads it wider.
2. A register REUSED for two differently-bounded values cannot have just one write narrowed:
   `proj.project_thing`'s `pth_czlim` holds `minz` (5-nibble bound) on one path and `neartz`
   (unbounded) on another; narrowing the minz write leaves the prior call's wide nibbles standing.
   Same shape kills the `scale_from_global_angle` clamp-writes -- the pre-clamp value is
   unbounded BY DESIGN.
3. `hex.sign` is cheaper at width 8, but if a register's writes narrow to 6, its `sign` MUST also
   move to 6 for CORRECTNESS (nibble 7 would be stale). A rare case where narrowing sign is
   required; the ~5 extra ops are noise against the mov/sub saving.

**Candidates (⚠ op deltas INTERPOLATED from the section-A table, not measured):**
`proj.scalestep` sst_diff 8->6 (needs a new `frame.sub6_chain`), per-seg; `proj.project_thing`'s
four constant sets -- `pth_c_vieww` and `pth_c_viewh` 8->2, `pth_c_centerxfix` and
`pth_c_centeryfix` 8->6 -- per-thing.

## J. Phase 0 instruments (built 2026-09-04) -- what exists now, and its controls

| tool | what it gives | control |
|---|---|---|
| `scratchpad/12m/ritual.py` | build -> freeze -> deg compare -> sweep -> ledger row, one command | refuses to run beside a fat python; refuses to keep artifacts unless deg is 4/4 BYTE-EXACT; `selftest` on the freeze diff |
| `scratchpad/12m/frames.py` | all 260 sweep frames' op costs + 8 picks evenly spaced in RANK | re-derived the baseline median exactly |
| `scratchpad/12m/profile_picks.py` | a per-op profile per pick | discards any profile whose ca2_profile controls failed |
| `scratchpad/12m/atlas.py` | INCLUSIVE / EXCLUSIVE / per-call-site / per-hand-site op tables | 3 selftest controls incl. the rep-prefix merge; prints COVERAGE (100.000% on all 8) |
| `scratchpad/12m/micro.py` | EXACT executed-ops-per-call and EXACT emitted space for a macro variant, in seconds | reproduces FINDINGS' hex.mov 8 = 514 and the 64-ops-per-nibble slope; empty body prices 0/0 |

**`micro.py` is the tool that changes the campaign's economics**: an idea can be priced and
value-checked in ~60 s instead of a 19-minute gate, and the freeze filler is COMPUTED, not guessed.
Its executed-cost figure is a SLOPE with the loop harness measured empty over the same counter
range and subtracted, so the harness cancels exactly rather than approximately.

**Correction to section A:** `hex.mov n` costs **64n + 2** ops of space. The table's `mov 5 = 320`
dropped the +2 (the true value is 322); `mov 8 = 514` is right. Executed cost is ~27.9 ops per
nibble (mov 8 = 202.4, mov 5 = 118.8, measured).

**Reading the atlas' per-hand-site table.** It attributes each op to the DEEPEST hand-written call
site. So a file whose macros only call other hand-written macros shows ZERO -- plane_render.fj and
plane_bands.fj price at 0 not because they are dead but because their work is attributed down into
fixed_point.fj. Use the `pair` table (the two deepest hand frames) to see the caller.

## K. THE UNREACHABLE-SLOT RULE (the freeze technique this campaign runs on)

A layout freeze needs filler that is (a) LOCAL to the region that shrank -- filler further down
the file only re-aligns addresses after itself, so labels in between still move -- and (b)
provably unreachable. Both at once are easy, because:

**`hex.scmp`, `hex.cmp`, `hex.sign`, `hex.if` and `hex.if0` all JUMP to one of their label
arguments and never fall through.** The space immediately after such a call, before the next
label, is therefore unreachable and costs nothing at runtime. That is the natural filler slot,
and it sits exactly where a narrowing usually is.

## L. The measured pool table (median frame = 20,204,970 ops, BASE, 2026-09-04)

Full table in ATLAS.md. The headline shape, which is NOT what the stale table said:

- `hex.exact_xor` == `hex.xor` 8,888,487 (44.0%) -- the atom every hex op decomposes into.
- `frame.seg_pass2_leaf_body_lines` 7,865,735 (38.9%); `frame.seg_pass1_leaf_body_ts` 4,762,279.
- `hex.mov` 4,215,705 (20.9%) and `hex.zero` 4,147,979 (20.5%) -- but only 3.1M / 0.77M of those
  are called from doom lines; the rest are inside other stl macros. Both are SPREAD (277 / 112
  sites, biggest 130k) -- they are a sweep, not one idea.
- `stream.emit_col_lines` 3,812,820; `frame.ts_step_faces` 3,563,542; `frame.thing_record_body`
  2,383,571; the pointer arm (`set_flip_and_jump_pointers`) 2,022,344.
- CONCENTRATED, by contrast: `hex.add_mul` 1,832,124 at ONE line (fixed_point.fj's
  `fixed_mul_lo.row`), of which 1,186,378 comes from full `hex.fixed_mul_lo 8,4` calls;
  `hex.scmp` 852,998 over just 15 sites; `frame.dance_boundary` 1,290,578 in three lines;
  the four `write_byte_and_inc` of `ts_piece_wr` 795,631.

**Do NOT re-propose:** dropping the fixed_mul row count from 8 to 6 for `scalestep` operands. The
code comment records that the gate already killed it -- scalestep is negative and its sign
extension lives exactly in the dropped rows: 2,152-3,990 px wrong per viewpoint.

## M. WHY P1-2 MISSED ITS ESTIMATE BY 7x -- op cost is OPERAND-DEPENDENT (2026-09-04)

P1-2 (`sign_extend 8,4` -> `5,4` on top/bottom) measured -56..-144 executed ops per call on
micro.py's cases and delivered **-4,160** on the median frame, not the ~30k predicted.

THE CAUSE, and it generalises. `hex.sign_extend n, k, x` writes the sign into nibbles k..n-1.
Those nibbles were just ZEROED by `shr_hex`, so for a POSITIVE x the write is a wflip by 0 --
one op, not ~28. Narrowing 8->5 therefore removes three nearly-free ops on the common path and
only pays off on negatives. micro.py's case list was half negative and so overweighted the
expensive path by an order of magnitude.

THE RULE THIS BUYS:
- **Structural savings** are reliable: `hex.mov`, `hex.cmp`/`scmp`, `hex.zero`, `hex.inc`/`dec`
  walk a table per nibble and cost ~28 executed ops per nibble REGARDLESS of value. Narrow these.
- **Value-dependent savings** are not: `hex.sign_extend`, `hex.set`, `hex.xor` and every raw
  `wflip` cost popcount(the delta), which collapses to ~1 op when the target already holds the
  value. Narrowing these buys almost nothing on the common path.
- So when micro.py prices a candidate, WEIGHT THE CASES BY THE REAL OPERAND DISTRIBUTION, or
  price only the structural ops and treat the value-dependent ones as free.
- Cross-check every estimate against the atlas region price: est_frame_delta =
  atlas_ops_for_that_region x (fraction of its executed cost the change removes). P1-2's atlas
  region was ~85k for the two shr_hex sites, so a -30k prediction was already implausible.

**Call counts are NOT shared by adjacent call sites.** P1-1 (clip_rows) and P1-2
(column_params_dda) are invoked from consecutive lines of the same column loop, and P1-1's saving
was a CONSTANT -107,200 on every one of the 260 frames while P1-2's varied (-30,560 on the
cheapest frame, -4,160 on the median, -5,701 on the dearest). Never infer one macro's call count
from a neighbour's.

## N. micro.py's SPACE figure is close, not exact -- and why (2026-09-04)

P1-3's fillers were computed from micro.py's measured space deltas and came out **16 ops short**:
20,683 labels moved by exactly -16 ops, a clean single-mode shift.

THE CAUSE: a `wflip` emits ONE OP PER SET BIT of the value it flips, so the emitted SIZE of any
op whose operand is an address depends on that address's popcount -- and in a micro program every
address differs from the real one. micro.py's executed-op figure is exact (it is a slope on real
runs); its SPACE figure is within a few tens of ops, no better.

CONSEQUENCE FOR THE RITUAL: compute the filler from micro, then let the label diff tell you the
residual and CARRY IT INTO THE NEXT FILLER (invariant C-2, now with a mechanism behind it). Do
not spend a 12-minute build correcting a residual on its own -- a uniform shift of a few ops
de-tunes placement only marginally, and the next idea's build absorbs it for free.

## O. hex.zero / hex.mov redundant-work audit (subagent, 2026-09-04): 46 pairs, 5 dead, 0 unsure

Full census of adjacent `hex.zero N,X` / `hex.mov m,X[+k*dw]` in fixed_point / projection /
frame_render / stream_render / present.fj. Three shipped as P7-1 (independently agreed by the
audit). **Two more verified dead, not yet shipped:** `proj.slope_div`'s and `proj.slope_div_m`'s
`recip_wide` -- each a separate macro-local, `zero 8` + `mov 6,k=0`, and the uncovered nibbles
6..7 are read only as a zero-extended `fixed_mul_lo.row` operand and written by nothing.

**THE TWO PATTERNS THAT MAKE ~90% OF THESE ZEROS LOOK REDUNDANT BUT AREN'T** -- read this before
proposing any further zero deletion:
1. **Index to `hex.ptr_index`.** That macro reads its index argument at the full w/4 = 8 nibbles
   no matter how narrow the caller's data is (R37/R11). Live at `seg_pass1_leaf_body_ts`'s `x`,
   `step_shade`'s `sh_idx`, `lines_step_load`'s `slot_idx`, `lines_steps_seed`/`lines_spr_seed`'s
   `sidx`, `sprite_runs(_win)`'s `srw_sidx`/`srn_sidx`. All KEEP.
2. **shr_hex / shl_hex / shl_bit / add_chain / mul_lo / mul_const rewrite the full width they
   declare**, so a zero followed by a narrower mov is CONSUMED, not redundant, whenever one of
   those is the next instruction. That is ~30 of the 41 KEEPs.
3. Self-dirtying: `slope_div_m`'s `den_norm`/`num_norm` are re-zeroed every call because that same
   macro's `shr_hex 6,K` arms rewrite all 6 nibbles on a call that takes the shift path.
4. Five registers are KEEP only because *some* later op writes the uncovered nibbles before the
   first read (`project_thing`'s `pth_dtest`, `sprite_runs(_win)`'s `s{rw,rn}_smidx`,
   `wpx_grain_col`'s `cmidx`). A control-flow proof might downgrade them; not attempted.

**NOT the redundant-zero shape at all** (do not flag again): the "zero the HIGH nibbles, mov the
LOW ones" idiom where the zero has the offset and the mov does not -- disjoint ranges, both
required. Live at `trb_bucket_h`, `ts_clamp2`/`ts_clamp2_lo`'s `prev_end`/`prev_start`,
`ts_step_faces`'s `tsf_col_x`/`tsf_slot_idx`, all already commented as deliberate.

## P. hex.ptr_index priced stage by stage (2026-09-04) -- 1,196.8 executed ops per call

    def ptr_index dst, ptr, index {        measured, index = 0x1F64, w = 32
        .mov w/4, dst, index                 200.4
        .shl_hex w/4, dst                  }
        rep(8-#w, i) .shr_bit w/4, dst     }  441.6  (the three shift ops together)
        .shl_hex w/4, dst                  }
        .add w/4, dst, ptr                   554.8   <- nearly half the macro
    }                                       1196.8 total, 2,978 ops of space

TWO INDEPENDENT LEVERS, both measured value-identical for indices 0x42 / 0x1F64 / 0xFFFF:

1. **The final `hex.add w/4` -> `frame.add8_chain`: -84.0 executed ops per call, and ZERO ops of
   space** (the chain is size-identical to the stl add, so the swap moves no label). Needs NO
   bound on anything -- it applies to every ptr_index call in the program. The chain is the last
   statement of the macro, so nothing runs inside its hermetic window.
2. **Shift stage at width 6 instead of w/4: a further -92** -- but only where the index is
   provably < 16^4, because after the net five-bit left shift the value must still fit 6 nibbles.
   Both together: -176.2 per call, -384 ops of space.

The whole program runs ~760 ptr_index calls per median frame (909,630 ops / 1,196.8). Column
indices (`x`, `x1`, `trb_col_x`, `tsf_col_x`) are < VIEW_W = 160, i.e. TWO nibbles, so a
width-4 shift stage may be available at ~11 of the 22 sites -- unmeasured, worth a probe.

`hex.ptr_index` call sites: 22 live ones (20 in frame_render.fj, 2 in stream_render.fj); the 8 in
sim.fj and 3 in plane_render.fj are not in the visual tier. None is emitted from Python.

## Q. frame.ptr_index's shift stage: the exact bound, measured (2026-09-04)

ptr_index computes `ptr + index * 2w`, and **2w = 64**. So a shift stage of width `sw` is exact
iff **index < 16^sw / 64**:

| sw | index must be under | measured saving vs width 8 | space |
|---|---|---|---|
| 6 | 262,144 | -92.2 executed ops/call | -384 |
| 5 | 16,384 | -147.7 | -576 |
| 4 | **1,024** | **-217.9** (18% of the whole macro) | -768 |

⚠ I first derived `16^sw / 32` from reading the macro (shl_hex, 3x shr_bit, shl_hex = x32) and it
is WRONG BY A FACTOR OF 2. The negative control caught it: index 2047 is under 2,048 yet sw=4
produced a different pointer. **Do not re-derive this rule from the shift sequence -- the measured
table above is the authority.** Evidence: 159 -> all widths agree; 2047 and 8036 -> sw=4 differs;
32767 and 65535 -> sw=5 and sw=4 differ, sw=6 agrees.

A column index (< VIEW_W = 160) is comfortably sw=4. `sh_idx = (cls<<8)|h` < 65,536 needs sw=6.
This is the second lever on the ~760 ptr_index calls per median frame; P2-1 took the first.

### Q2. The per-site bound census for frame.ptr_index (subagent, 2026-09-04) -- all 22 PROVEN

Nobody should re-derive these. Reusable emitter constants found in the process: SLOT_SHIFT = 1
nibble (because PID_BYTES = 1), PIECE_BYTES = 4, SPRITE_HEIGHT_BUCKETS = 32,
SPR_BLOCK_STRIDE = 64 (blkshift 6), STEP_COL_STRIDE = 256, sp_base baked as `hex.set 4`.

| shape | bound | sw | which sites |
|---|---|---|---|
| plain COLUMN index | <= 161 | 4 | `trb_col_x` x2, `tsf_col_x` x2, `x` in seg_pass1_leaf_body_ts and lines_step_load, `x1` in lines_steps_seed / lines_spr_seed / lines_plane_ptr / seg_pass1_leaf_body_lines / seg_pass2_leaf_body_lines, `tmp` in lines_pclm_index2 (= idx*2) |
| COLUMN x 16 | <= 2,576 | 5 | `tsf_slot_idx`, `slot_idx`, `sidx` x2 |
| 4-nibble packed index | < 65,536 | 6 | `sh_idx` = cls*256+h; `trb_tab_idx` = sp_lt*256+bucket_h |
| sprite BLOCK index << 6 | < 4,194,240 | 7 | `trb_blk_ofs`, `srw_sidx`, `srn_sidx` -- left at 8, sw=7 is unpriced and barely narrower |

The column bound is `proj.wall_x_range_m`'s FOV clip (the source says so: "x/x2 are clipped
columns in [0,161]"); thing columns get it from `project_thing`'s x1_ok reject plus
`thing_record_body`'s zero-on-negative. The two 4-nibble bounds are the EMITTER'S OWN asserts:
`assert len(cls_of)*STEP_COL_STRIDE <= 0x10000` and `assert blk < 0x10000`.

⚠ `trb_tab_idx` is reached with TWO different bounds at its two sites (<= 65,381 at the table
seed, <= 2,552 at the block lookup). Shipped at sw=6 at BOTH -- paying ~64 ops/call rather than
depend on a reused-register argument, which is exactly trap 2 of section I.

## R. THE POINTER ARM -- measured, and what narrowing it would take (2026-09-04)

**The prize.** Every dereference pays `set_flip_and_jump_pointers`, which is two
`address_and_variable_triple_xor w/4` passes (a CLEAR of the old address out of three fields,
then a SET of the new one in). Measured on the interpreter:

| arm width | executed ops/call | space |
|---|---|---|
| 8 hexes (the stl) | **192.0** | 1,010 |
| 6 | ~145 (interp.) | ~754 |
| 5 | 121.8 | 626 |
| 4 | 104.1 | 498 |
| 3 | 74.0 | 370 |
| 2 | 48.0 | 242 |

The atlas puts the arm at 2,021,051 ops on the median frame, so **~10,526 arms per frame**, and
dereferences in total cost 2,912,865 (14.66%) across 38 sites -- the arm is 69% of that. Narrowing
every arm to 6 hexes would be worth roughly 495,000 ops/frame; to 4 hexes, over 900,000.

**Why it is not a one-line change.** The CLEAR pass xors out whatever address was armed LAST, so a
narrow arm is exact only when the previous and next addresses agree above the narrowed nibble.
The program's pointer targets fall in TWO clusters (bit addresses, from the P2-2 label table):

| cluster | span | nibbles 6-7 |
|---|---|---|
| the per-column tables: `pclm`, `sfflag`, `sprflag`, `sfslot`, `spslot`, `seg_wstrip`, `wstripbase`, `vzbank`, `drawn`, `slopediv_recip` | 0x000873C0 .. 0x00164180 | **always 0x00** |
| the sprite bank: `stepcol`, `sp_base`, `sp_base2`, `sprlight`, `sprbank` | 0x11A69B40 .. 0x11D6E000 | **always 0x11** |

So a **6-hex arm is exact for any consecutive pair of arms WITHIN either cluster** -- the low
cluster fits in 6 nibbles outright, and the high cluster shares its top two. What breaks it is a
crossing: a low arm following a high one leaves nibbles 6-7 holding 0x11.

**Hence the plan's second-arm apparatus is the right shape**, and this measurement says what it is
worth: give the sprite-bank pointers their own `to_flip2`/`to_jump2`/shadow2 so the main arm only
ever sees low-cluster addresses, and then EVERY main arm is 6 hexes with no per-site proof at all.
It needs: the doom-local second arm + a dance-only read/write clone against the SHARED stl decoder
table, an R9 negative control written BEFORE first use, and both restore sets re-keyed.
Estimated 350k-500k, the largest single mechanism the atlas has identified.

**A cheaper first slice exists** if that is too big to start with: inside a tight walk (e.g.
`frame.read0_byte_and_inc`, one site, 561,948 ops) consecutive arms are the same pointer +-1 cell,
so a 6-hex arm is exact for every iteration after the first -- provided the loop is entered with a
full arm. That is one macro and one loop, not an apparatus.

## S. The pointer RUN: measured, plus one negative result (2026-09-04)

The piece loaders read 3-4 consecutive bytes off one walking pointer with
`frame.read0_byte_and_inc`, and every read pays a full 8-hex arm. Measured on the interpreter,
one 4-read run:

| variant | executed ops | delta | space |
|---|---|---|---|
| all full arms (today) | 2,114.1 | -- | 6,328 |
| full arm + 3 x **5-hex** arms | **1,757.9** | **-356.2** | 5,176 |
| full arm + 3 x 6-hex arms | 1,850.1 | -264.0 | 5,560 |
| 5-hex arms + a 5-nibble ptr_inc | 1,809.8 | -304.4 | 4,888 |

One read alone: 602.9 with a full arm, 492.9 with a 5-hex one.

**NEGATIVE RESULT -- do not narrow `hex.ptr_inc`.** It is `hex.add_constant w/4, ptr, dw`, and
narrowing that to 5 nibbles makes the run *dearer* (-304.4 instead of -356.2). `hex.add_constant`
goes through `add_constant_with_leading_zeros`, which already skips the constant's leading zero
hexes, so an 8-wide add of dw = 64 touches only the low nibbles anyway and a narrower width just
adds carry work. Do not re-propose narrowing add_constant anywhere.

**Independently confirmed:** `hex.ptr_inc` never touches to_flip / to_jump / to_ptr_var (its whole
body is that one add_constant), so a walk does not disturb the arm between reads.

**THE HAZARD THIS IDEA CARRIES.** The 5-hex arm is exact only while the slot tables lie inside one
16^5 window. They do today -- `sfslot` at 0x8EBC0, `spslot` at 0xB6BC0, both tables together
ending near 0xDEC00, all under 2^20 -- but a future layout change (M4's nine levels is the obvious
one) could push them across that line and the frame would break SILENTLY. So this ships with an
ASSEMBLE-TIME assert in the fj, in the stl's own style
(`rep(condition, i) .name_that_states_the_rule` fails the assembly and names the rule), which
needs the emitter to mark the end of the slot block with a label. A comment is not enough here.

## T. The pool table after the pointer work (P2-6 binary, median frame 19,307,813)

The atlas was rebuilt on the same eight viewpoints as the baseline, so these diff directly.
Median profile 20,204,970 -> 19,307,813 (-897,157, -4.4%).

**What the pointer work actually moved:**

| pool | at BASE | now | delta |
|---|---:|---:|---:|
| `set_flip_and_jump_pointers` (the ARM) | 2,022,344 | **1,398,329** | **-624,015** |
| `frame.seg_pass2_leaf_body_lines` | 7,865,735 | 7,371,955 | -493,780 |
| `frame.seg_pass1_leaf_body_ts` | 4,762,279 | 4,466,123 | -296,156 |
| `frame.ts_step_faces` | 3,563,542 | 3,276,489 | -287,053 |
| `frame.ts_piece_store` | 1,632,509 | 1,432,304 | -200,205 |
| `frame.dance_boundary` | 1,290,578 | 1,491,021 | **+200,443** |

dance_boundary went UP because ptr_index now routes through add8_chain -- work MOVED into the
chain and the net was -57,501. Do not read that row as a regression.

**THE TOP TEN HAND-WRITTEN LINES NOW** (this is the ranking that matters):

| site | ops | share | what |
|---|---:|---:|---|
| `f2:l104` | **1,844,048** | **9.55%** | `add_mul` in `fixed_mul_lo.row` -- the multiply |
| `f5:l1546` | 702,752 | 3.64% | `hex.xor jumper, dst_next` in dance_boundary |
| `f5:l1545` | 685,879 | 3.55% | `hex.xor_zero dst_prev, hex.tables.res` |
| `f8:l1090` | 653,910 | 3.39% | `w1rpat.walk` |
| `f8:l607` | 543,429 | 2.81% | `w1rpat.walk_win` |
| `f5:l1889` | 459,696 | 2.38% | arm5's CLEAR pass |
| `f5:l1890` | 422,090 | 2.19% | arm5's SET pass |
| `f5:l1940` | 244,750 | 1.27% | `xor_byte_to_flip_ptr` (the write dance) |
| `f5:l949` | 178,684 | 0.93% | `hex.scmp 5` in ts_piece_store |
| `f2:l86/88/90/92` | 493,073 | 2.55% | fixed_mul_lo's setup movs + zero |

So the MULTIPLY FAMILY (add_mul + setup) is **2,337,121 = 12.1%**, the biggest addressable pool
left, and the arm remainder is 881,786 at the two arm5 lines plus the un-narrowed full arms.

**AN OPEN QUESTION worth someone's time.** `dance_boundary`'s two structurally identical
single-hex xors cost wildly different amounts:
    `hex.xor jumper,   dst_next`  702,752
    `hex.xor jumper+4, src_next`  102,390     <- 6.9x cheaper, same call count
Both are one `hex.xor` of one hex in the same macro body, so the difference must be in the VALUES
(cost is popcount-driven, FINDINGS M). Nobody has explained it. Whatever makes the second one
cheap may be arrangeable for the first -- 600k sits in that gap. Not investigated.

## U. `pad` vs `stl.fj 0, 0`: padding is NOT wasted space, filler IS (2026-09-04, owner + assembler)

Verified in `flipjump-151/flipjump/assembler/assembler.py`, not paraphrased:

```python
def get_wflip_spot(self):
    if self.padding_ops_indices:            # <- PADDING IS CONSUMED FIRST
        index = self.padding_ops_indices.pop()
        return WFlipSpot(self.fj_words, index, self.first_address + self.memory_width * index)
    wflip_spot = WFlipSpot(self.wflip_words, len(self.wflip_words), self.next_wflip_address)
    ...                                     # otherwise: the segment's wflip area, at the end

def insert_padding(self, ops_count):        # <- what the `pad` directive calls
    for i in range(len(self.fj_words), len(self.fj_words) + 2*ops_count, 2):
        self.padding_ops_indices.append(i)  # <- REGISTERED as an available wflip slot
        self.fj_words.extend((0, 0))
```

**So `pad` slots are storage the assembler REUSES for wflip chain ops, and it prefers them over
the wflip area at the end of the segment.** A multi-bit wflip expands into a chain of ops that has
to live somewhere; padding is where they go. The space is not lost.

**⚠ THE CAMPAIGN'S FREEZE FILLERS DO NOT DO THIS.** `rep(N, i) stl.fj 0, 0` emits ordinary ops
through `insert_fj_op`; they are never added to `padding_ops_indices`, so no wflip chain can ever
use them. Every filler this campaign has placed -- 24,837 ops in section G plus P3-1's 795 and
P3-2's 1,998 -- is genuinely dead space, while the same ops written as `pad` would have absorbed
wflip chains AND put those chain ops near the code that jumps to them instead of at the segment's
end. That is worth re-examining: it is a free-ish win available at every filler site already in
the tree.

**The tension to respect.** `pad N` aligns to a multiple of N, so its SIZE is whatever the current
address needs -- it cannot express "exactly K ops" the way the freeze fillers must. And the owner's
caution: **do not pad more than the wflip chains will actually consume**, or the surplus is back to
being dead space AND it shifts everything after it (re-rolling every later address). The sweet spot
is padding ~= the number of wflip-chain ops that region would otherwise push into the wflip area.

**Two mechanisms, both from the owner, both now grounded in the source:**
1. `pad 2^x` before a hot label zeroes the low x bits of its address, saving ~x ops per
   set-and-clear pair that flips by that label (~x/2 each).
2. Hot, frequently-jumped-into macros at LOW addresses (0 .. 65535*dw) are cheaper to wflip to and
   from, because a small address has few set bits.
