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

## V. WHERE TUNING'S LIMITS ACTUALLY ARE -- measured on the current binary (2026-09-04)

Census of the shipped tree (P7A = the P3-2 binary), joined to a per-op profile of the same binary.

**wflips ARE the program: 15,260,433 of 18,812,927 executed ops = 81.1%.**
Mean popcount of an executed wflip: **7.76**. The cost distribution peaks at popcount 9 (21.0%),
with popcounts 7-11 holding 79% of it -- i.e. the hot values look exactly like ~30-bit addresses,
NOT like the small deltas the top-of-table suggests.

⚠ **Do not read the `rank-values` top table as the pool.** Cost is spread over 33,759 distinct hot
values; the top 28 together are only 503,848 ops = 2.7% of the frame. A label expanded N times has
N DIFFERENT addresses, so per-value ranking fragments exactly the thing you want to aggregate. It
is the right lens for GLOBAL labels and the wrong one for macro-locals.

**THE ALIGNMENT CEILING** -- if EVERY flipped value in the program had its low x bits zeroed:

| align to | ops saved | of wflip cost | of frame |
|---|---:|---:|---:|
| 2^4 (pad 16) | 65,718 | 0.4% | 0.3% |
| 2^6 | 84,904 | 0.6% | 0.5% |
| 2^8 (pad 256) | 293,603 | 1.9% | 1.6% |
| 2^10 (pad 1024) | 528,066 | 3.5% | 2.8% |
| 2^12 | 2,208,250 | 14.5% | 11.7% |
| 2^16 | 5,656,182 | 37.1% | 30.1% |

These are CEILINGS assuming free, universal alignment. They are not reachable: aligning a label
expanded 80,834 times to 32 costs ~1.3M ops of space for at most ~75k, and pad-4096 on everything
is absurd. A realistic round is a fraction of the 2^8 row.

**THE KNOBS ARE ALREADY TUNED.** `simulate-shift` on the three inter-leaf placement points says the
best available move is -5,286 (thing_leaf, 256 ops); every other size at every point is WORSE.
Five placement rounds in earlier campaigns tuned exactly these.

**AND THE ONE NEW KNOB IS TOO.** `fixed_mul_lo`'s in-macro filler shifts at 20 expansions at once
(the compound shift that accidentally bought 139,917 on P3-2). `scratchpad/12m/multishift.py`
generalises the predictor to that case and searched 1182..3000 at step 16: **1998 -- the accidental
value -- is the best in the range**, everything else is worse. Saved a 20-minute gate by predicting.
Predictor validated against the one real measurement: it says 1182 costs +251,069 on the profiled
frame where the sweep median measured +139,917 -- same sign, same order, different quantities
(one frame vs a 260-frame median). Directionally reliable, magnitude approximate.

**SO: the accessible placement gain from here is tens of thousands of ops, not hundreds.** The
shift lottery has ±140-250k variance but it is ONE global degree of freedom and it is already
sampled at a good point; it cannot be accumulated. Tuning is not the next big win. It was worth
measuring precisely because the P3-2b accident made it look like it was.

**A tooling caveat that came out of this, worth checking before trusting the atlas further.**
`insert_wflip_ops` emits the FIRST op of a wflip chain inline and sends the remaining
popcount-1 ops to `get_wflip_spot()` -- padding, else the segment's wflip area. At mean popcount
7.76 that is ~87% of all wflip cost executing at addresses that are NOT the issuing source line.
The atlas attributes by address, so that cost lands on whatever label precedes those ops. This
does not invalidate the pool table (the chain ops sit near their expansion), but any claim of the
form "line X costs N" is really "line X's region costs N". Do not push the per-line numbers harder
than that without checking where the chain ops actually landed.

## W. The alignment ceiling IS concentrated -- but the mass is in values `pad` cannot change

Correcting section V, which said the pool was flat. It is not, and that reasoning was wrong:

| align to | top 10 | top 25 | top 50 | of the ceiling (top 25) |
|---|---:|---:|---:|---:|
| 2^8 | 134,090 | 181,378 | 192,250 | 61.8% |
| 2^10 | 162,367 | 245,669 | 265,649 | 46.5% |

So 25 labels hold half the ceiling. If those were alignable labels, `pad 1024` on 25 of them would
be -245,669 ops for ~12,800 ops of space -- the biggest idea in the campaign. **They are not.**

**NAMING THEM IS WHAT SETTLES IT. Only 2 of the top 25 are label ADDRESSES at all:**

| value | ops | what it is |
|---|---:|---|
| **0x2E** | 44,104 | **`dbit + 8`**, and `dbit = w + #w` = 38 at w=32. The read dance's `wflip to_flip, dbit+bits`. A CONSTANT of the memory width -- placement cannot touch it. |
| 0x3C0, 0x300, 0x1C0, 0x2C0, 0x180, 0x340, 0x140, 0x280, 0x240 | ~60k total | macro-local DELTAS (0x3C0 = 960 bits = a 15-op stride) at 6,000-36,000 sites each. Alignable in principle -- make the stride a power of two -- but the pad is per EXPANSION, so the space runs to hundreds of thousands of ops for tens of thousands saved. |
| 0x28, 0x2A, 0x2C, 0x26, 0xE, 0x6 | ~30k total | more `dbit+k` dance constants. Unalignable. |
| **0x80C0** | **22,052** | **`hex.pointers.to_flip`** -- a REAL, once-emitted label at op 515. **This one is worth taking.** |
| 0x40 | 8,874 | `stl.IO` at op 1, popcount already 1. Nothing to gain (a wflip costs max(1, popcount)). |

**THE ONE CLEAN WIN: `hex.pointers.to_flip`.** It sits at 0x80C0 (op 515), popcount 3. The table
`read_ptr_byte_table` is pinned at op 256 and runs 256 ops, so op 512 = 0x8000 is free and has
popcount 1. Moving `to_flip:` to be the first declaration after the table is a REORDER, not a pad:
**-22,052 ops on the profiled frame for ZERO ops of space.** It is an stl change (ptr_init in
basic_pointers.fj) so it needs a CR into flipjump-151/1.5.1, and the
`to_flip == to_jump+w == to_ptr_var` invariant must be re-checked -- that invariant is about the
VALUES those fields hold, not their layout, so a reorder should be safe, but "should" is not
"gated".

**THE HONEST SUMMARY.** Section V's conclusion (tuning is not the next big win) survives, but its
reasoning did not. The pool is concentrated, not flat; it is just concentrated in width constants
and in per-expansion deltas whose padding costs more than it saves. Realistic accessible gain:
~22k from the to_flip reorder, plus whatever the chain-delta stride restructure nets after its
space -- which nobody has costed properly and which the workflow's ~52k space estimate looks
optimistic about, since `pad N` aligns to N OPS and the chain has ~10 slots per expansion across
thousands of expansions.

## X. THE PAD POOL IS REAL AND IT IS ~2.2M -- I had it wrong twice (2026-09-05)

Sections V and W concluded the pad pool was ~77k. **That was wrong, and the error was in what I
measured, not in the arithmetic.** I ranked by DISTINCT VALUE, which fragments a macro-local label
across every expansion, and then I costed "move one label" instead of "widen one pad in one macro,
which realigns EVERY expansion at once".

**Group the hot wflip values by the MACRO + LABEL they belong to, and the pool is enormous:**

| family :: label | expansions | visits/frame | cost now | saving if trampolined to pc 1 |
|---|---:|---:|---:|---:|
| `hex.exact_xor :: switch` | 18,708 | 953,688 | 8,226,900 | 6,319,524 |
| `hex.double_exact_xor :: first_flip` | 3,842 | 157,494 | 1,355,978 | 1,040,990 |
| `hex.if_flags :: switch` | 2,558 | 109,522 | 953,892 | 734,848 |
| `hex.cmp :: ret` | 1,110 | 57,474 | 557,362 | 442,414 |
| `hex.add.clear_carry :: ret` | 928 | 46,236 | -- | 364,030 |
| `bit.exact_xor :: base_jump_label` | 331 | 43,190 | 398,806 | 312,426 |
| `hex.triple_exact_xor :: first_flip` | 636 | 122,060 | 1,055,132 | 725,334 |
| `hex.tables.jump_to_table_entry :: return` | 350 | 24,580 | -- | 193,260 |

**`hex.exact_xor` is 33.6% of the whole frame in ONE label.** Its body is
`wflip src+w, switch, src` … `pad 16` … `switch:` … `end: wflip src+w, switch` -- two wflips by
its own switch label per call, and that label is aligned only to 16 ops.

**WIDENING THAT ONE PAD IS THE IDEA.** Measured from the census values, across the six families:

| pad | saving | of frame | space | of image |
|---|---:|---:|---:|---:|
| 32 | 782,140 | 4.16% | 434,960 | +3.4% |
| 64 | 1,486,072 | 7.90% | 869,920 | +6.9% |
| **128** | **2,200,804** | **11.70%** | 1,739,840 | +13.8% |
| 256 | 2,921,386 | 15.53% | 3,479,680 | +27.5% |

Best RATIO at pad 128 (saving per op of space): `bit.exact_xor` 3.97, `triple_exact_xor` 3.92,
`hex.cmp` 1.94, `exact_xor` 1.19, `if_flags` 1.00, `double_exact_xor` 0.96.

**And the space is not really spent:** `get_wflip_spot` pops `padding_ops_indices` before it
allocates in the segment's wflip area (FINDINGS U), so padded ops are exactly where multi-bit
wflip chains get placed. The image already carries millions of chain ops; padding should absorb
them rather than add to them. **Measure the .fjm size on every one of these builds** -- the owner's
constraint is that the binary must not grow much, and that is the number that decides it.

**THE LESSON ABOUT MY OWN METHOD.** Twice I concluded a pool was thin from an aggregate that had
the wrong grouping. `rank-values` groups by value; the actionable unit is the MACRO. Always
re-group a census by the thing an edit actually changes before pricing a pool.

## Y. PAD SPACE SCALES WITH *TOTAL* EXPANSIONS, SAVING WITH *HOT* ONES (2026-09-05)

P7-5 died in the ASSEMBLER: `OverflowError: Python int too large to convert to C unsigned long`
-- the image outgrew the addressable space. Cause: I padded `bit.exact_xor` from 8 to 128 having
priced it from the census, which sees only the 331 HOT targets. The macro actually expands about
**600,000** times (1,200,416 label mentions / 2 labels per expansion), so the pad cost ~64 ops x
600k = **~38M ops of padding on a ~12.6M-op image**.

**The rule, and it is not optional: before widening any pad, count TOTAL expansions from the
label table, not hot ones from the census.** The two differ by 1,800x for bit.exact_xor.

    zcat <build>.labels.tsv.gz | grep -c "macro.name("      # mentions
    expansions ~= mentions / (number of labels the macro defines)

Expansion counts measured on the P7-4 build:

| macro | label mentions | ~expansions | pad cost |
|---|---:|---:|---|
| `bit.exact_xor` | 1,200,416 | ~600,000 | **catastrophic -- leave at 8** |
| `hex.exact_xor` | 160,228 | ~80,000 | 16->128 cost ~4.5M ops (shipped, +25.8% binary) |
| `hex.if_flags` | 75,232 | ~25,000 | 16->64 ~ 600k ops |
| `hex.double_exact_xor` | 23,277 | ~7,800 | 16->64 ~ 190k ops |
| `hex.tables.jump_to_table_entry` | 17,920 | ~18,000 | none->64 ~ 570k ops |
| `hex.add.clear_carry` | 10,662 | ~11,000 | none->64 ~ 350k ops |
| `hex.triple_exact_xor` | 5,592 | ~1,400 | 16->128 ~ 78k ops |
| `hex.sub.clear_carry` | 588 | ~590 | none->64 ~ 19k ops |

The saving-to-space ratio a census gives is an OVERESTIMATE by exactly (total / hot). Recompute
with the table above before proposing any further pad. The address-space ceiling is real: at
w = 32 the image cannot grow without bound, and the assembler's failure mode is an OverflowError
with no indication of which macro caused it.

## Z. THE PAD POOL, CLOSED: -1,635,512 over 15 directions, and where each lever stops

Every pad in the stl is now at a MEASURED optimum. Two consecutive widening attempts reversed --
`hex.exact_xor` 256 -> 512 (+316,510) and a five-family widening bundle (+219,449) -- which is the
empirical signal that the pool is done.

| macro :: label | optimum | evidence |
|---|---|---|
| `hex.exact_xor :: switch` | **256** | 16->128 -607,482; 128->256 -724,727; 256->512 **+316,510** |
| `hex.double_exact_xor :: first_flip` | 64 | 128 was worse in the P7-12 bundle |
| `hex.triple_exact_xor :: first_flip` | 128 | 256 was worse in the P7-12 bundle |
| `hex.if_flags :: switch` | 64 | 128 worse |
| `hex.{add,sub}.clear_carry :: ret` | 64 | 128 worse; had NO pad before |
| `hex.tables.jump_to_table_entry :: return` | 64 | 128 worse; had NO pad before |
| `read_cell_from_inners_ptrs` | 64 | aligns two labels at once, ~340 expansions |
| `hex.add_mul :: ret`, `hex.cmp :: ret` | 64 | 4->32 -83,640; 32->64 only -14,330 |
| `hex.mul.init :: after_add` | 4096 | needs the consumer's window anchored first |
| `bit.exact_xor :: base_jump_label` | **8 -- DO NOT PAD** | ~600,000 expansions; overflows the address space |

**THE TRAP TO REMEMBER.** The census's "available" column (visits x (popcount-1)) is an UPPER
BOUND assuming free alignment. After all this work it still reports 5,147,872 available on
`hex.exact_xor` and 392,250 on `bit.exact_xor` -- both unreachable, one past its optimum and one
unpaddable. **It is not a to-do list.** The reachable figure is bounded by the re-roll each pad
causes and by expansion count, neither of which the census sees.

**WHAT PADS ACTUALLY DID.** wflip cost went 15,260,433 (81.1% of frame) -> 13,619,278 (79.5%)
across the campaign: the pads removed 1.64M ops from the dominant cost class rather than moving
work around. Binary 11,307,396 -> 15,168,954 bytes (+34%), non-monotonic throughout -- P7-6 added
1.8M ops of padding for +0.1%, and P7-10 SHRANK the image by 615,204 bytes while adding padding,
because `get_wflip_spot` pulls chains out of the segment's wflip area into it.

## AA. WHY A PAD IS SOMETIMES FREE AND SOMETIMES EXPENSIVE: ABSORPTION (2026-09-05)

The add_mul/cmp anomaly -- `pad 4 -> 32` SHRANK the binary by 615,204 bytes while `pad 32 -> 64`
GREW it by 381,750 -- is not a lottery. The label diffs settle it:

| gate | change | labels moved |
|---|---|---|
| P7-10 | pad 4 -> 32 | **0 of 781,326 -- FROZEN** |
| P7-11 | pad 32 -> 64 | 20,687, every one by **exactly +256 ops** |

**A pad's shift is ABSORBED by the next downstream `pad M` whenever the accumulated shift is less
than that pad's slack.** Below the threshold the change is purely LOCAL: the label gets aligned,
nothing after it moves, and the byte cost is ~zero (padding is zero words; a chain op in a padding
slot costs what it would have cost in the wflip area). Above the threshold everything after jumps
by a FULL BLOCK, re-rolling every other site's popcount.

The +256 granularity names the grid: `hex.exact_xor`'s `pad 256` is expanded ~80,000 times across
the image, so 256-op re-anchors are everywhere. That is the absorption grid the whole program now
sits on.

**THE RULE THIS GIVES US, and it is the most useful thing in this file:**
> Prefer pad increments SMALL enough to be absorbed, and CHECK THE LABEL DIFF. `MOVED: none` means
> the pad was free and you keep the alignment gain outright. Any nonzero MOVED means the pad
> crossed a re-anchor and you are now paying a whole-image re-roll for it -- judge it on the sweep
> median, not on the alignment argument.

**And it explains the two metrics diverging.** File size tracks SUM POPCOUNT OVER ALL 1,992,624
wflip sites (every chain op is content whether or not it executes); runtime tracks
SUM VISITS x POPCOUNT, dominated by 33,759 hot values -- 1.7% of sites. A propagating shift plays
both lotteries, but the size one is decided by the cold 98.3% that runtime never sees. Measured
across the campaign: static popcount 17,420,626 -> 18,480,671 (WORSE by 1.06M) while weighted cost
15,260,433 -> 13,619,278 (BETTER by 1.64M).

⚠ **No tool reports static popcount.** If size matters as much as speed, that is the number to
add to the ritual -- it is one line over the census and nobody has been watching it.

## AB. THE 50-PAD TABLE, RANKED BY OPS-PER-KILOBYTE (`padrank.py`, 2026-09-05)

New instrument: `scratchpad/12m/padrank.py --selftest` (3 negative controls: vacuity, bit-mask,
rarity-ordering). It is the first tool that ranks the two pad columns AGAINST each other --
census visits for speed, LABEL-TABLE rows for space -- instead of one at a time, which is the
confusion that cost P7-5 an assembler overflow.

Full table: `scratchpad/12m/atlas/PADS50.txt`. Read on the P7-11 certified layout
(frame 17,130,098; image 15,168,954 B; 89.6% of hot visits resolve to a named label).

**Seven of the top 50 are pads a sweep has ALREADY REFUTED** -- and they are the seven biggest
predicted savings in the table (303,236 of the 391,692 ops). The tool prints them as `<-- refuted`
rather than dropping them, because their presence is the point: the census keeps offering
`hex.cmp 64->128` and the gate keeps saying no. FINDINGS Z's trap, now printed at the point of use.

**The 43 rows no gate has ruled on are worth 88,456 ops for 517,128 bytes** -- 0.52% of the frame
for +3.4% of the image. Grouped by the edit that would deliver them:

| # | edit | rows | ops | bytes | ops/KB |
|---|---|---:|---:|---:|---:|
| E | `hex.{and,or,add}.init` -- **one expansion each** | 5 | 9,367 | 7,168 | 1,338 |
| C | `hex.pointers.xor_hex_to_flip_ptr :: after_flip_bit*` 2/4 -> 16 | 2 | 12,240 | 5,928 | 2,114 |
| A | `lut_generator.py def lookup :: return` -- ONE emitter line | 11 | 1,864 | 2,016 | 947 |
| D | `read_cell_from_inners_ptrs :: cleanup` 2 -> 16 | 1 | 5,513 | 6,328 | 892 |
| B | `frame.{add,sub}{2,4,6,8,10}_chain :: rcc0/rcc1` 1/2 -> 16 | 14 | 11,173 | 31,224 | 366 |
| F | `hex.shifts.sh{l,r}_bit_once :: switch` 16 -> 32 | 2 | 15,130 | 92,416 | 168 |
| G | `hex.mul.clear_carry :: return` 32 -> 64 | 1 | 12,568 | 100,864 | 128 |
| H | `v{ql,qh}_load`, `vpb_walk :: return` 2 -> 16 | 3 | 3,036 | 12,544 | 248 |

**A/B/C/D/E are 34 of the 43 rows, 40,157 ops, and 21,440+31,224 = 52,664 bytes (+0.35% image).**
That is the bundle worth building. F/G/H double the ops for 4x the bytes.

**WHY THESE ARE STRUCTURALLY DIFFERENT FROM THE REFUTED SEVEN, and it follows from FINDINGS AA:**
every row in A-E is a SMALL increment (1 or 2 -> 16, or a 512 -> 1024 on a once-expanded macro).
`hex.exact_xor`'s `pad 256` expands 80,114 times, so 256-op re-anchors sit roughly every 200 ops
of image -- a shift of <=15 ops has nowhere to go but the next one. **These pads should be
ABSORBED: aligned label, zero labels moved, no whole-image popcount re-roll.** The refuted seven
were all +64 or +128 increments on macros expanded thousands of times, which is precisely the
regime that propagates. The label diff on the gate build is the check that decides it.

**THE ONE-LINE EDIT WORTH MOST PER KEYSTROKE** is `lut_generator.py`'s `def lookup`:

    wflip hex.tables.ret+w, return, .dsp
  return:                                    <-- unaligned; every LUT in the program shares this
    wflip hex.tables.ret+w, return

Two wflips by the label's own address, no pad, in the macro every baked table is read through.
`pad 16` before `return:` covers eleven separate table families at once.

⚠ The savings are SMALL in absolute terms -- 88,456 ops is 0.52% of the frame. **This confirms the
FINDINGS Z verdict rather than overturning it: the pad pool is essentially exhausted, and what is
left is a long tail of cheap-but-thin rows.** The 12M target will not come from padding.

⚠ **AB caveat -- padrank overstates families with CONSECUTIVE labels.** It scores each label as if
alignable alone. `xor_hex_to_flip_ptr`'s after_flip_bit0..3 sit at base+0..+3 behind ONE `pad 4`,
so only bit0 can be 16-aligned and the rest inherit +1/+2/+3. Group C's 12,240 is therefore an
upper bound on what one `pad 4 -> 16` delivers, not a prediction. Any macro appearing on more than
one row of PADS50.txt needs this check before its rows are added together.

⚠ **AB correction -- the predictor's frame is NOT the ship criterion's frame.** Every visit count
in padrank (and in popcount_census, and in multishift) comes from ONE profiled viewpoint's IP
histogram, `h57_1`. That viewpoint is the 6th of 8 and deliberately heavy:

| build | h57_1 | ca2_sweep median | h57_1 is |
|---|---:|---:|---:|
| BASE | 20,204,970 | 18,982,338 | +6.4% |
| P7-11 | 17,130,098 | 16,038,392 | +6.8% |

So an ops figure from any census tool is **~6% above the median delta a gate will report**, because
savings scale with visits and that frame has ~6% more of them. The percentages survive the scaling;
the absolutes do not. `padrank.py` now prints both lines. **The eight profiled viewpoints span
3.67M to 39.5M ops -- a 10.8x range -- so "the frame" is never a single number in this repo,** and
any figure quoted without naming its viewpoint is ambiguous by up to 10x.

## AC. THE REAL MAP (2026-09-05, new instrument `wprof.py`, selftest PASS)

`scratchpad/12m/wprof.py` attributes wflip cost to **the site that ISSUED the chain**, not to where
the chain ops executed. The census records each site's FIRST op (inline, at the source line) and
the whole chain's popcount; joining that to the IP histogram gives issues x popcount charged to the
causing line. This fixes the blur FINDINGS V flagged, where ~87% of wflip ops execute in the wflip
area and an IP histogram smears them onto whatever label precedes it. Three negative controls:
conservation, attribution (after a label yes / before it no), vacuity.

**On P7-11 (h57_1 viewpoint, 17,130,098 ops): 1,966,215 wflip ISSUES carrying 13,619,278 ops =
79.5% of the frame. Mean chain 6.93. The other 20.5% is plain jumps.**

### The cost is in ONE leaf and NO caller

| level | top entry | share |
|---|---|---:|
| leaf (`--level inner`) | **`hex.exact_xor`** | **39.86%** (6,827,389 ops, 943,572 issues) |
| leaf, top three | + double_ (7.10%) + triple_ (5.25%) | **52.2%** |
| doom caller (`--level doom`) | `frame.dance_boundary` | 6.13% -- flat over 147 macros |
| exact_xor's callers (`--only`) | `frame.dance_boundary` | 3.71% -- flat over 120 macros |

**So there is no caller-side fix at the 4M scale.** exact_xor is two wflips per call, both flipping
`switch`'s own ~25-bit address: `wflip src+w, switch, src` ... `end: wflip src+w, switch`.
471,786 calls/frame x 2 x 7.24 popcount = the 6.8M.

### WHY pad 512 REVERSED -- the mechanism, and it is now PREDICTIVE

| quantity | value |
|---|---:|
| chain ops needing a `get_wflip_spot()` slot (sum of popcount-1 over ALL sites) | **16,488,047** |
| padding slots from exact_xor at `pad 256` (80,114 x 128 avg slack) | 10,254,592 |
| ... at `pad 512` (80,114 x 256) | **20,514,304** |

At 256 the padding is **fully absorbed** -- there are more chain ops than slots, so the pad costs
ZERO image space and buys 8 zeroed address bits for free. At 512 the slack (20.5M) EXCEEDS demand
(16.5M), the surplus becomes dead space, the image grows, every address widens, and popcount rises
everywhere. That is the measured +316,510. **The rule: a pad is free while total slack stays under
16.5M chain ops, and starts costing the moment it passes it.** Nobody had this before; it predicts
the one result the campaign could only observe.

### The image, and why address width is a first-class cost

Highest wflip site: **op 31,092,386 = 24.89 bits.** Chain ops are 16.5M of that 31M = **53% of the
image is wflip chain**. Every bit of span costs ~0.5 popcount on all 1.97M issues ~ 1M ops/frame.

| macro | sites | hot | hot% | chain ops | %chain |
|---|---:|---:|---:|---:|---:|
| (top level, emitted doom) | 870,690 | 19,138 | 2.2% | 6,992,912 | 42.4% |
| **`bit.exact_xor`** | **601,104** | **475** | **0.1%** | **6,409,943** | **38.9%** |
| `hex.exact_xor` | 173,978 | 37,555 | 21.6% | 1,128,581 | 6.8% |
| `stl.fcall` | 85,085 | 3,548 | 4.2% | 939,301 | 5.7% |

**`bit.exact_xor` is 20.6% of the whole image span and 99.9% of it never executes.**

### THE CEILING THAT MATTERS -- concentration

exact_xor cost over its 37,555 hot sites is concentrated:

| top N sites | % of issues | % of exact_xor cost |
|---:|---:|---:|
| 1,000 | 17.3% | 21.5% |
| 2,000 | 32.4% | 37.3% |
| **5,000** | 59.8% | **62.8%** |
| 10,000 | 76.6% | 78.9% |

Addresses below 2^24 with popcount <= q: q<=2: 301, q<=3: 2,325, q<=4: 12,951, q<=5: 55,455.

| if the N hottest sites sat at popcount q | ops saved | of frame |
|---|---:|---:|
| top 2,325 at q=3 | 1,801,146 | 10.51% |
| **top 12,951 at q=4** | **2,680,701** | **15.65%** |
| top 500 expansions (1,000 sites) at q=3 | ~975,648 | 5.70% |

⚠ These are CEILINGS. Realising them needs the dispatch table HOISTED out of the macro so its
address can be chosen -- `pad` can only align, never select a sparse address. The gaps between
sparse slots would have to be filled with baked data, which the doom image has in abundance
(4.8M lines). This is an architecture change, not a tuning knob, and it cannot reach expansions
that sit inside stl macros. **But it is the only measured idea at the 4M scale, and the smaller
version -- the top ~500 expansions for ~975k -- is a legitimate first rung.**

## AD. THE PAD BUDGET IS A KNAPSACK, AND THE CEILING IS NOT REACHABLE (2026-09-05)

Owner's idea: give `exact_xor` a PAD PARAMETER -- `sparse_exact_xor PAD, ...` -- so the regular
macro passes a small pad and only the hottest call sites get a big one. That is the tractable form
of AC's hoisting idea: it needs an stl macro change plus call-site edits, where hoisting needs the
emitter to enumerate expansions. Priced it. Three results, in order of how much they change the plan.

### 1. The execution profile (owner asked for it, and it kills the "16k times" intuition)

Per-op, whole frame, 593,428 distinct ops executed at least once:

| runs/frame | #ops | % of distinct | % of frame |
|---:|---:|---:|---:|
| exactly 1 | 108,996 | 18.37% | 0.64% |
| 2-9 | 265,673 | 44.77% | 8.48% |
| 10-99 | 170,384 | 28.71% | 28.44% |
| **100-999** | **47,780** | **8.05%** | **48.57%** |
| 1,000-9,999 | 560 | 0.09% | 7.37% |
| >=10,000 | 35 | 0.01% | 6.51% |

**There is no per-pixel inner loop to exploit.** The single hottest op runs ~140,000 times and is
0.82% of the frame. The mass is 48,375 ops running 100-999x carrying 62.4%. Padding has to target a
WIDE band, not a handful of ops -- which is exactly why the budget below binds.

### 2. Padding is free only under a hard budget

Chain ops needing a `get_wflip_spot()` slot: **16,488,047** (FINDINGS AC). Total padding slack from
all pads must stay under that or the surplus becomes dead space (the pad-512 mechanism). Today
exact_xor supplies 10,254,592. Dropping its **61,337 COLD expansions** (78% of 80,114) to `pad 16`
frees **7,360,440**, giving ~14-15.5M to spend.

Single-tier optima, cold at 16 and the N hottest at 2^k (popcount modelled as
`7.24 * (24.89-k) / 16.89`, calibrated so pad 256 reproduces the measured 7.24):

| pad | expansions affordable | ops saved | % frame |
|---:|---:|---:|---:|
| 1,024 | 18,778 (all hot) | +804,863 | 4.70% |
| 4,096 | 8,634 | +1,420,133 | 8.29% |
| **8,192** | **4,308** | **+1,493,148** | **8.72%** |
| 16,384 | 2,152 | +1,389,783 | 8.11% |
| 65,536 | 537 | +621,796 | 3.63% |

### 3. ⚠ THE ADDRESSABLE UNIT IS A SOURCE CALL SITE, NOT AN EXPANSION -- and that is the whole gap

AC's 3,231,454 ceiling assumed each of the 7,547 hottest EXPANSIONS could be aligned independently.
It cannot: a `pad` lives in source, so every expansion of that line pays the slack, hot or cold.
Re-ranked by FULL macro path (expansion indices stripped -- the true editable unit):

**1,332 distinct exact_xor call sites carry the 6,827,389 ops. Greedy fill under a 14M slack
budget: 808 sites -> +1,098,896 ops = 6.42% of the frame.**

The optimum pad is almost always **1,024**: saving grows linearly in k while slack doubles, so the
ratio always favours the smallest useful pad, and the budget favours breadth over depth.

⚠ Top sites are deep stl chains -- `hex.zero/hex.zero/hex.xor/hex.exact_xor`,
`hex.cmp/hex.cmp_eq_next/hex.cmp/hex.xor/hex.exact_xor` -- so reaching them means threading a PAD
parameter through `hex.zero`, `hex.mov`, `hex.xor`, `hex.cmp`, `byte.emit`. That is an stl ABI
change (CLAUDE.md rule 4) and a CR into flipjump-151.

**HONEST BOUND: this idea is worth ~0.8-1.1M (5-6.4%), not 3.2M.** It takes 16,038,392 to about
14.9M. It is the largest single measured idea in the campaign and it does not close the 4M alone.

⚠ And the prediction is directional only: 14M ops of redistributed padding re-rolls every address
in the image (FINDINGS AA). Total slack stays under the 16.49M demand so the span should not grow,
but only the sweep decides.

## AE. THE >=1000-RUNS/FRAME BAND IS NOT A SEPARATE POOL (2026-09-05, owner-directed)

Owner asked to address the ops run >=1000 times per frame before anything else. **595 ops,
2,376,029 runs = 13.87% of the frame.** Decomposed them. The band is real but it is the SAME cost
the leaf profile already names, seen per-op, and its placement-addressable parts are already tuned.

| machinery | #ops | runs | %frame | is it a fresh lever? |
|---|---:|---:|---:|---|
| `hex.exact_xor` | 220 | 565,902 | 3.30% | **No -- these ARE the chain ops of hot exact_xor wflips**, parked in its own pad-256 region. Already the 6.8M the pad plan targets; counting them again would double-count. |
| shared global dispatch words | 22 | 735,697 | 4.29% | **No.** `hex.tables.ret` (139,975), `.res` (98,385), `hex.mul.dst`, `hex.add.dst` ... each is ONE op executing once per visit. 1 op is the floor. |
| `hex.mul.init` | 39 | 287,381 | 1.68% | partly -- its wflip targets are already popcount 1 |
| `hex.tables.clean_table_entry__table` | 54 | 195,408 | 1.14% | table-entry cleanup after dispatch |
| `hex.add.init` | 9 | 59,604 | 0.35% | already popcount 1 |

Only **12 of the 595** are wflip first-ops at all, and the three biggest of those
(`hex.add.init::switch__without_carry`, `hex.mul.init::after_add`, `hex.mul.init::add_res`) are
**already at popcount 1** from the P7 stl pad round. The band is 98% chain ops and plain dispatch.

### The owner's "first addresses" lever, measured and CLOSED

Hypothesis: put the most-jumped-into globals at low addresses so wflips to them are cheap. Measured
every shared global's address AND how often it appears as a wflip VALUE:

| global | op | popcount | visits as a VALUE |
|---|---:|---:|---:|
| `hex.pointers.to_flip` | 512 | **1** | 25,374 |
| `stl.IO` | 1 | **1** | 8,491 |
| `hex.tables.ret` | 600 | 4 | **0** |
| `hex.tables.res` | 601 | 5 | **0** |
| `hex.mul.dst`, `hex.add.dst`, `hex.sub.dst`, `hex.cmp.dst`, `hex.mul.ret`, ... | -- | 2-5 | **0** |

**Moving every one of them to a popcount-1 address would save 6 ops.** The two that matter are
already there (`to_flip` from the P7 reorder, `stl.IO` by construction). The rest are jumped INTO,
never flipped AS a value -- and the cost of `wflip X+w, V` is popcount(V), never popcount(X). So
the address of a jump TARGET is free; only the address of a flipped VALUE is paid.

**That distinction is the whole lever and it is now exhausted.** Being executed 139,975 times does
not make an op's address worth anything; being *named as a wflip value* does.

**CONSEQUENCE FOR THE CAMPAIGN: the >=1000 band yields no new idea.** The pad plan (AD, ~0.8-1.1M)
remains the largest measured item, and the remaining gap to 12M still has no identified source.

## AF. P8-1 IMPLEMENTED: the pad became a parameter (2026-09-05)

Owner's design, built. **`pad` accepts a macro parameter** -- that was the load-bearing unknown and
it is now proven by assembly, not argument:

| `tp.sparse_xor PAD` | executed | space |
|---|---:|---:|
| pad 16 | 14.9 | 22 |
| pad 256 | 6.8 | 198 |
| pad 1024 | 6.8 | 710 |
| pad 4096 | 2.6 | 1,734 |

### What changed

`flipjump-151/flipjump/stl/hex/logics.fj`
* `sparse_exact_xor PAD, d3, d2, d1, d0, src` -- exact_xor's body verbatim with `pad PAD`.
* `exact_xor` KEEPS its signature and delegates with 256. Rule 4 (frozen ABI) is not touched:
  no existing macro name, arity or parameter order changed.
* `sparse_xor PAD, dst, src` and `sparse_xor PAD, n, dst, src`; `xor` delegates with 256.

`flipjump-151/flipjump/stl/hex/memory.fj`
* `sparse_zero PAD, hex` / `sparse_zero PAD, n, x`, `sparse_mov PAD, dst, src` / `PAD, n, dst, src`.

⚠ A namespace constant (`hex.DEFAULT_XOR_PAD = 256`) FAILED -- inside a macro it trips
"Used a not global/parameter/declared-extern label", the same werror trap as the extern rule.
The literal 256 is inlined at the two delegation points instead.

### Controls run before the gate

1. **VALUE, all 16 src values**, `hex.xor` vs `sparse_xor` at pads 16/256/1024/4096, each checked
   against PYTHON's own xor so the fj forms cannot be jointly wrong: **all 16 identical at every
   width.** `sparse_mov`/`sparse_zero` likewise identical to the plain macros.
2. **NEUTRALITY of the refactor** -- the delegation must not change what today's callers emit.
   Measured on the old tree and the new, four shapes, EXACTLY equal:

   | | old | new |
   |---|---|---|
   | `hex.xor 1` | 6.75 exec / 198 space | 6.75 / 198 |
   | `hex.xor 8` | 71.75 / 1,990 | 71.75 / 1,990 |
   | `hex.mov 8` | 152.88 / 4,038 | 152.88 / 4,038 |
   | `hex.zero 8` | 69.75 / 1,990 | 69.75 / 1,990 |

### The conversion

286 call sites in **37** of the 62 target macros, at pad 1024, by brace-matched scripted edit:
`frame_render.fj` 176, `stream_render.fj` 57, `projection.fj` 53. The remaining 25 are either
emitted by `lut_generator.py` (the 10 `*.lookup` families -- one emitter line, saved for a second
gate) or named differently inside their namespace.

**PREDICTION: -682,545 ops on the h57_1 viewpoint (3.98%), ~-639,000 on the sweep median**
(x0.9363, FINDINGS AB), for 5,231,616 ops of extra padding slack -- which stays under the
16,488,047 chain demand, so it should be absorbed and cost no image space. Purely additive:
unconverted expansions keep pad 256, so no site can regress by construction.

⚠ Only 37 of 62 macros converted, so the realised figure should be BELOW the prediction. The
prediction also ignores the whole-image re-roll (FINDINGS AA), which at 5.2M ops of new padding
will be large. Gate P8-1 decides.

## AG. THERE ARE ONLY 12 HOT WFLIPS, AND THEY ARE ALL ALREADY AT POPCOUNT ~1 (2026-09-05)

Owner asked to pad every wflip among the 595 ops that run >=1000x/frame, trying 2048 and larger.
**Measured: only 12 wflip SITES fire >=1000x, they cost 131,446 ops = 0.77% of the frame, and
every one is already at mean popcount 1.00-4.00.**

| target the wflip flips | sites | visits | cost | mean pc |
|---|---:|---:|---:|---:|
| value `0x0` | 4 | 58,211 | 58,211 | **1.00** |
| `hex.mul.init::after_add` | 2 | 54,270 | 54,270 | **1.00** |
| value `0x3C0` | 1 | 1,847 | 7,388 | 4.00 |
| value `0x300` | 2 | 2,766 | 5,532 | 2.00 |
| value `0x100` | 2 | 3,472 | 3,472 | **1.00** |
| `stl.IO` | 1 | 2,573 | 2,573 | **1.00** |

**A wflip costs `max(1, popcount(value))`. Nine of these twelve already cost exactly 1 op per
visit -- the hard floor. No pad of any size can improve them.** The three above 1 flip `0x3C0`,
`0x300`, `0x100`, which are NOT labels but small macro-local strides (0x3C0 = 960 bits = a 15-op
stride); FINDINGS W already classified those as unalignable by `pad`. Total reachable: under 8,000
ops even if the impossible were done.

### WHY THE >=1000 OP BAND IS 13.87% BUT THE >=1000 WFLIP-SITE BAND IS 0.77%

This is the distinction that matters and it was implicit until now. **The op band counts CHAIN OPS
individually.** A site that fires 200 times with popcount 8 emits 8 ops that each run 200 times --
those chain ops land in the >=100 band and are hot, but the SITE fires only 200 times and never
appears in a >=1000 site census. So:

> The hot-op band is made of chain ops belonging to MANY MODERATELY-WARM sites, not of a few
> blazing-hot wflips. There is no small set of hot wflips to pad. The 6.8M of exact_xor is
> 471,786 calls averaging 14.5 ops, not a handful of sites averaging thousands.

**CONSEQUENCE: "find the hottest wflips and pad them huge" has no target in this program.** The
only shape that works is the P8-1 shape -- pad MANY moderately-warm call sites a moderate amount --
and its size is bounded by the slack budget, not by how big a pad we are willing to write.

## AH. BIG PADS ARE AFFORDABLE ONLY FOR RARE MACROS -- the per-macro knapsack (2026-09-05)

Owner asked to try 2048 and larger. **Uniformly, they are not affordable, and the arithmetic is
short.** The 36 converted macros hold **11,927 exact_xor expansions**, and slack scales with
expansions, not with call sites:

| pad, applied uniformly | slack needed | of the 5,233,455 headroom |
|---:|---:|---:|
| 512 | 1,526,656 | 29% |
| 1,024 | 4,579,968 | 88% |
| **2,048** | **10,686,592** | **204% -- OVER** |
| 4,096 | 22,899,840 | 438% |
| 16,384 | 96,179,328 | 1,838% |

Past the headroom the slack exceeds the 16,488,047 chain demand, the surplus becomes dead space,
every address widens -- the exact mechanism that made a global `pad 512` cost +316,510 (FINDINGS AC).

**BUT PER MACRO THEY ARE, AND THE OWNER'S INSTINCT WAS RIGHT.** Slack is `expansions x (pad-256)/2`,
so a macro with 34 expansions can take `pad 8192` for 137k of slack while one with 2,607 expansions
cannot afford 512. Running the knapsack per macro over pads 512..262144:

| allocation | ops saved | of frame | slack |
|---|---:|---:|---:|
| uniform 1,024 | +585,911 | 3.42% | 4,579,968 |
| **per-macro optimal** | **+753,256** | **4.40%** | 5,231,744 |

**+167,345 ops purely from choosing the width per macro instead of one number for all.**

Chosen widths: 512 x10, 1024 x7, 2048 x5, 4096 x6, 8192 x5, 16384 x3. The big pads land exactly
where the owner predicted -- on the RARE hot macros: `add6_chain` (4 expansions) 16384,
`lines_sky_base` (3) 16384, `read_hex5` (4) 16384, `ts_dda_row_one` (34) 8192, `clip_rows` (62)
8192 -- while the common ones are held down: `project_thing` (2,607 expansions) 512,
`thing_record_body` (954) 512.

**THE RULE: pad width should be inversely proportional to expansion count.** "Hot and rare" again,
the same criterion padrank found, now applied to width rather than to whether-to-pad. Applied:
282 call sites in 36 macros. Gate P8-1.

## AI. ⚠ THE ABSORPTION MODEL IS WRONG -- MEASURED 12.3%, NOT 100% (2026-09-05)

**Retracting the central cost premise of AC, AD and AH.** They all assumed padding is free because
`get_wflip_spot()` fills padding with wflip chains before using the segment's wflip area, and total
slack (would-be 15.5M) stayed under the 16,488,047 chain demand. The P8-1 freeze measures it
directly, and the premise does not hold:

| | ops |
|---|---:|
| slack added by the per-macro pads | 5,231,744 |
| image growth measured by the label diff | **4,587,520** |
| absorbed | 644,224 = **12.3%** |
| became image | **87.7%** |

781,207 of 781,326 top-level labels moved, nearly all by exactly +4,587,520 ops. Image span
31,092,386 -> 35,679,906 ops, **24.89 -> 25.09 bits.**

**Why the model failed.** "Total slack < total chain demand" is a GLOBAL accounting identity, and
allocation is not global. `get_wflip_spot()` consumes padding as it goes; padding created in a
region whose nearby chain demand is already satisfied is never claimed. The 10.25M of pre-existing
`pad 256` was evidently already meeting most of the demand it could reach, so 5.2M of NEW padding
in hot macros found almost nothing left to absorb. **Slack is only free where unmet demand is
adjacent to it -- a locality property the census cannot see.**

**What this invalidates.** Every "for N ops of slack, absorbed, so no image cost" claim in AC/AD/AH
is wrong by ~8x on the cost side. The pad knapsack's budget was not 5.2M of free space; it was 5.2M
of which ~4.6M is real growth. It does NOT invalidate the SAVING side (popcount reduction at the
padded call sites), but it adds a cost term that was priced at zero:
+0.20 bits of span across 1,966,215 wflip issues is roughly +200k ops, plus an unpriced whole-image
re-roll of every one of the 781,207 moved labels.

⚠ **This also means the FINDINGS AC explanation of the pad-512 reversal, while directionally right,
had the wrong quantities** -- 512 did not fail because slack crossed a 16.5M threshold; it failed
because padding barely absorbs at all, so ANY widening applied broadly is close to pure growth.

**STATUS: P8-1 is UNMEASURED.** Two gate runs were killed externally (no OOM: 8.6 GB free, no
error, no termination events). The second reached the label dump but never wrote a .fjm, so no
sweep is possible. The sign of P8-1 is genuinely unknown: predicted -753k of saving against a newly
discovered cost term of ~+200k plus the re-roll. **Do not quote a P8-1 number until a sweep runs.**

## AJ. P8-1 KILLED: +649,387 (+4.05%). THE PAD POOL IS DEFINITIVELY CLOSED (2026-09-05)

Measured, not modelled:

```
MEDIAN 16,038,392 -> 16,687,779   (+649,387, +4.05%)   MIN +35,156  MAX +1,670,772
DEG    +988,759 / +180,722 / +1,234,100 / +122,130   -- all four viewpoints WORSE
PICTURE CONTROL 260/260 byte-exact   VACUITY 254 distinct   ca2_sweep PASS
```

**Predicted -753,256. Measured +649,387. Wrong by 1.4M and wrong in SIGN.**

Correctness was never the issue -- 260/260 byte-exact confirms `sparse_exact_xor`/`sparse_xor`/
`sparse_zero`/`sparse_mov` compute exactly what the originals do, as the micro controls said. The
idea is simply not worth its space.

**WHERE THE 1.4M WENT.** AI measured the image growth (+4,587,520 ops, 24.89 -> 25.09 bits) and I
priced it at ~+200k from a log2-of-span popcount model. The truth is ~7x that. The span model is
not predictive because growth does not scale addresses uniformly -- **781,207 labels moved and each
one's popcount RE-ROLLED arbitrarily.** FINDINGS AA flagged the re-roll as unpriced; this measures
it. The exchange rate implied by P8-1:

> **~0.3 executed ops/frame per op of image growth.**

**THE BAR A PAD MUST NOW CLEAR.** For a macro with E expansions and V visits, widening 256 -> P:
  saving  ~ V * dpc          cost ~ 0.3 * 0.877 * E * (P-256)/2  ~  0.13 * E * (P-256)
A pad pays only when `V * dpc > 0.13 * E * (P-256)`. At the campaign's typical dpc (~1-2 ops) that
demands V/E ratios no macro in this program has -- which is why the greedy, run against the CORRECT
cost function, selects nothing.

**CONSEQUENCE: the pad toolbox is closed, and FINDINGS X/Y/Z/AB/AD/AH overstated it throughout.**
Every one of those priced padding at or near zero space. The correct statement is:

> Padding is ~12% absorbed and ~88% image growth, and image growth costs ~0.3 ops/frame per op.
> A pad is worth it only where the popcount saving beats that. The P7 round's -1.6M was real
> because those pads were SMALL and applied to already-hot shared stl leaves with tiny expansion
> counts; nothing of that shape remains.

⚠ **METHOD FAILURE TO CARRY FORWARD.** Three successive analyses (AC, AD, AH) built on an
unmeasured premise -- "padding is absorbed, so it is free" -- that a single label diff would have
falsified at any point. The premise came from reading `get_wflip_spot()` and reasoning globally
about an allocator that works locally. **Rule 3 of CLAUDE.md exists for exactly this: the cheap
pre-gate is not the gate, and a mechanism argument is not a measurement.** The freeze step, which
costs seconds, should have been run against a scratch build BEFORE the knapsack was ever written.

### AJ.1 Re-pricing with the measured cost -- what is left is inside the noise

Calibrating from P8-1: 4,587,520 ops of image growth cost 1,402,643 ops/frame (the +649,387
measured regression PLUS the 753,256 of predicted saving it cancelled) =
**0.306 executed ops/frame per op of image growth.**

Re-pricing all 62 candidate macros with that rate instead of ~0:

| | |
|---|---:|
| macros with positive net | 24 of 62 |
| best-subset total | +173,882 on the viewpoint, **~+162,806 on the median** |
| slack it would add | 497,280 ops |
| net over ALL 62 (what P8-1 did) | **-720,317** |

**+162,806 is INSIDE the placement lottery's own variance** -- FINDINGS V measured that shift luck
moves the median by 140,000-250,000 ops, and P3-2b was a 139,917-op swing from placement alone.
A gate cannot distinguish this subset from luck, and each gate is ~45 minutes.

⚠ And the 0.306 rate is ONE SAMPLE of a noisy process, not a linear law: most of that cost is the
re-roll, which is a lottery, not a function of growth. Using it to select a 24-macro subset is
fitting a subset to a single noisy calibration -- exactly the overfitting that produced P8-1.

**THE PAD TOOLBOX IS CLOSED. Do not open it again without a new mechanism** (one that changes
popcount WITHOUT moving anything else -- which `pad` cannot do, because alignment is global).

## AK. S1 SHIPPED-MECHANISM + S2 IMPLEMENTED (2026-09-05) -- the 12MB-file campaign

Owner's target: file ~12,000,000 bytes, median unchanged (~16.04M). Two mechanisms, measured-first.

### S1: LZMA 9|EXTREME repack -- PROVEN, -1,088,717 bytes for zero ops change
The .fjm is FORMAT_RAW LZMA2 at library-default preset 6 (the recompression control reproduced the
shipped blob BYTE-EXACTLY, which also proves the build did NOT use the fast match finder despite
FJM_LZMA_FAST=True in harness.py -- the deg/ritual path evidently writes without it).
* preset 9 alone: +1.86% (WORSE). dict 256MB: +2.43% (WORSE) -- **the long-range-redundancy
  hypothesis is refuted**; region B's per-seg leaves do not cross-match at distance.
* **9|EXTREME: 15,168,954 -> 14,080,237 (-7.18%). Decode 1.00s vs 1.11s -- FASTER. Encode 581-676s,
  once, at ship time.**
* `scratchpad/12m/repack.py` (selftest PASS incl. corrupt-byte negative control) repacks any .fjm;
  flipjump-151 reader got `dict_size: 1<<26` in _LZMA_DECOMPRESSION_FILTERS (reads old files too).

### S2: shared pair-blocks in generate_bands_walk_fj -- IMPLEMENTED, gate P9-1 RUNNING
Census: 40,567 pair instances, **5,326 distinct (y2,c)**, reuse 7.6x, ~172 static ops each; the
pair trees own ~85% of region D's 5.47MB. The M4 clamp-tail move applied one level up.

**The 3-outcome fcall lane mechanism** (stl.fcall's landing op IS its disarm):
body: `wflip vpb_px+w, ret, vpb_pb_Y_C` / `pad 4` / ret: 3 lane wflips (clamp/stop/continue),
each lane disarming with its own armed value. Block reports outcome by flipping bit 6 or 7 of
vpb_px's jump field before `;vpb_px`. Cell provably zero on every path.

Verified before any build:
* `p9_1_shared_pairs.py`: byte-identical output over 6 windows + an 18-walk sequence; lane-swap
  sabotage DETECTED. ⚠ first run was VACUOUS -- micro.compare's `if printer:` skips capture for
  an EMPTY list and returns None digits; the R9 control caught my own harness. Non-empty printer
  + an assert on capture now guard it.
* `tests/fj/test_bands_walk.py`: 15/15 through the real assembler+interpreter vs the oracle,
  including new cross-body-sharing cases and the block-count negative control.

Projection (site arithmetic, NOT a promise): body side 4 wflip sites/pair vs 14.8 today ->
~-4M static ops in region D. Runtime +~2x popcount(ret) per WALKED pair (~1.1k/frame) ~ +30-40k
ops/frame. The sweep decides; the file size is read off the artifact.

## AL. P9-1 SHIPPED: THE FILE HALVED AND THE FRAME DID NOT MOVE (2026-09-05)

```
PICTURE 260/260 byte-exact      VACUITY 254 distinct     ca2_sweep PASS
MEDIAN  16,038,392 -> 16,055,788   (+17,396, +0.11% -- a tenth of placement-lottery noise)
DEG     -3,272 / +38,179 / +16,916 / +15,987
FILE    15,168,954 -> 7,923,027    (-47.8%)          banks part -34% lines, labels -72%
```

Ship criterion for this gate is the owner's stated goal (file ~12M, speed unchanged), so the
ritual's ops-sign KILL label does not apply: **SHIP.** The 12MB target is overshot by 4MB before
the 9E repack is even applied.

**Why it beat the projection (~-4M ops of content predicted, ~-7.2MB of file delivered):** the
windowed attribution priced the trees' own bytes but not their NEIGHBORHOOD effect -- 599k
high-entropy wflip chains interleaved with everything in region D also poisoned the
compressibility of what they sat next to. Removing content can be worth more than its own bytes.

**Regression net:** tests/fj/test_bands_walk.py 15/15 (incl. new cross-body sharing cases +
block-count negative control). tests/host: 6 failures, ALL PRE-EXISTING on this dirty branch
(verified by stash: identical 6 fail with the change absent); 479 pass both ways.

**The S-campaign scoreboard:** S2 alone lands 7,923,027. S1 (repack 9|EXTREME, proven -7.18% on
the old image, decode FASTER) applies on top; result recorded when the encode lands. The two
compose: S2 shrinks content, S1 shrinks encoding.

### AL.1 S1-on-S2, measured: the two levers do NOT stack linearly

Repacking the P9-1 artifact at 9|EXTREME: **7,923,027 -> 7,795,688 (-1.61%)**, bit-identical
through the reader. On the OLD image the same repack was -7.18%. The S2 content removal took
most of what 9E's deeper search was finding -- the entropy the EXTREME pass exploited WAS largely
the tree chains. So: final artifact 7,795,688 bytes; keep the repack in the ship pipeline (it is
~free at ship time and decode is faster), but do not book -7% for it on future images.

### AL.2 S1 RETIRED (owner decision, 2026-09-05): -127,339 bytes is not worth the moving parts

With S2 shipped, 9|EXTREME saves 1.61%, costs ~16 min of encode at ship, and requires a reader
dict bump in flipjump-151. Owner: skip it. The reader revert is done (fjm_consts.py back to
stock), the 9E artifact is deleted, and THE ship artifact is P9-1.fjm -- 7,923,027 bytes, written
by the untouched standard build pipeline. `repack.py` stays in scratchpad/12m as a proven tool
(selftest + negative control) should a future image want it -- rememeber its saving must be
re-measured per image (AL.1: it shrank 7.18% -> 1.61% when S2 removed the entropy it fed on).

## AM. ⚠ THE HOSTED-LOOP TIER NO LONGER ASSEMBLES ON THIS BRANCH (2026-09-05)

Regenerating the m1 restore set needs `ca_labels.py` to build the `hosted-loop` tier to pass 1.
It DIES:

```
insert_wflip_ops: ops_list[last_address_index] = wflip_spot.address
OverflowError: Python int too large to convert to C unsigned long
```

Same failure class as P7-5 (FINDINGS Y): an address exceeded the assembler's ceiling (on Windows,
array('L') is 32-bit -> 2^32 bits = 67.1M ops of span). The `game`/deg (visual) tier P9-1 builds
fine (~35.7M ops span), so this is specific to the hosted-loop tier's layout.

**This is almost certainly why the restore-set regen was interrupted WIP** (m5_setfile/ca_labels
dirty at session start). Timeline: restore set last regenerated Aug 25 (hosted-loop built fine);
idea 11 (Sep 3) added the p2_* globals; the P7 pad round (committed on this branch, and in the
flipjump-151 1.5.1 stl at d22e1d8 "add_mul and cmp return pads to 64") inflated the address span
across all tiers. S2 is in the tree and shrinks the bands bank hard, yet the hosted-loop tier still
overflows -- so S2's saving is not enough to bring THIS tier back under the ceiling on its own.

**CONSEQUENCE FOR THE MERGE:** the branch has a broken build path (hosted self-reset), not just 2
red tests. The 4 mapbake fixes are committed and real; the 2 restore_set tests cannot go green
until the hosted-loop tier assembles again. That is a genuine regression to investigate (reduce
that tier's span -- extend S2's reach, or selectively back off the pads that pushed it over), not
a test-harness fix. Flagged to the owner rather than grinding heavy builds against an overflow.

## AM.1 The overshoot is static + banks-dominated, and pinning the exact cause needs milestone work

Overflow probe: hosted-loop peak wflip address 194,308,162 words vs 134,217,728 ceiling =
**+60,090,434 words, 44.8% over.** Only 14,003 wflip spots handed out before the crash, so peak
~= first_address -- the INLINE (static, pre-chain) section is already ~194M words.

Emit-only part sizes (chars of fj source, hosted-loop tier, S2 active):
  entry 2,455 | tables 10,026,130 | main 5,509 | segconsts 1,379,539 | walk 3,524,713 |
  state 10,630 | banks 35,205,634  -> TOTAL 50,154,610 chars.
The banks part dominates (70%), tables next (20%). 50M chars of source expand (rep/macros) to the
~97M inline ops (194M words) that overflow.

⚠ THE MURKY PART: the `visual` tier (P9-1, S2) ASSEMBLES and fits at ~71M words with a comparable
(larger, even) source. hosted-loop = visual + {player_sim, collide, moving_things, self_reset}.
Those flags add modest CODE, yet the assembled static size is 2.7x visual's. Pinning why needs an
apples-to-apples visual-vs-hosted-loop assembled-size comparison (more heavy builds) -- the source
char counts alone do not explain a 2.7x assembled-size gap, which points at wflip-chain/popcount
expansion differing by tier, i.e. back at the pad-inflated address span.

**BOTTOM LINE: this is a milestone-scale size-reduction on a pre-existing (Aug-25-buildable,
now-broken) tier, not a session trim. It is ORTHOGONAL to the delivered size win** (P9-1 game/deg
binary, 7.9MB, +0.11%, committed). It blocks the restore-set regen -> the 2 restore_set tests ->
the branch merge cleanup, but not the shipped picture the ritual gates.

⚠ OPEN QUESTION worth one build before any merge decision: does the SHIPPED `game` tier (more flags
than hosted-loop) also overflow? If yes, the branch's playable product is un-assemblable and that
is the real priority; if no, only the m1-capture path is blocked.

## AN. ⚠⚠ THE SHIPPED GAME TIER ALSO OVERFLOWS -- and the signature says SINGLE CAUSE (2026-09-05)

game tier: peak 195,391,042 words, **+61,173,314 (45.6%) over** the 2^27 ceiling.
hosted-loop: 194,308,162 words, +60,090,434 (44.8%).

**Both crash at EXACTLY 14,003 wflip spots and within 1M words of each other**, despite the game
tier having 3 more flags (standalone/menu/doors) and much more content. That near-identical
signature means the overflow is NOT diffuse tier content -- it is a SINGLE cause common to both,
which is everything they share and the visual/deg tier (62M words, FITS) does not: **self_reset**.

Peak ~= first_address (only 14,003 spots), so the WFLIP AREA of the first segment starts at ~194M
words -- i.e. the inline section that precedes it is ~194M words for both self_reset tiers vs ~62M
for the non-self_reset visual tier. self_reset appends m1_reset.fj and lays out the reset image;
the ~132M-word gap is almost certainly a memory-layout / reset-region effect, not 132M words of
real code.

**This reframes the whole session's cleanup: the branch's PLAYABLE product does not assemble.**
The delivered 7.9MB size win stands (it is the deg/visual tier, which fits and is byte-exact) --
but the game a user would run is broken on this branch. Fixing this is the priority over any merge.

Encouraging: a single shared cause at a fixed ~194M first_address is far more likely a targeted
fix (a reset-layout base address, a mis-sized reserved region, or one baked reset structure) than
a 60M-word diffuse-bloat problem. Next: find what sets first_address so high for self_reset builds
-- start OFFLINE in the memory map / selfreset layout before spending another build.

## AN.1 self_reset EXONERATED -- it is the `hosted` tier's sim CONTENT (2026-09-05)

Bisect: probe(tier="hosted", self_reset=FALSE) overflows at peak **194,308,162 words -- byte-
identical to hosted-loop (self_reset=TRUE)**, same 14,003 spots. So self_reset adds nothing to the
overflow (its pass-1 file is empty, as deduced). game is 195,391,042 (the extra ~1M from
standalone/menu/doors).

The cause is the `hosted` content = `things + {player_sim, collide, moving_things}`. The `visual`
tier (things only) fits at 62M words; the three sim flags turn ~3% more SOURCE TEXT into ~132M more
inline words -- the signature of a rep(N) unroll (a few chars -> millions of ops), NOT content
volume and NOT a reserve (grep found no large reserve/hex.vec in source). Most likely the collide
(geometry-as-code) or moving_things (runtime thing table) bake.

NEXT (not yet run -- checkpoint): bisect the flag with the sub-tiers that toggle ONE each --
`hosted-nosim-nocollide` (things+player_sim), `hosted-nocollide` (+moving_things), `hosted-static`
(+collide). Whichever fits vs overflows names the flag; then find the rep(N) in that flag's emitter
and cap/share it (S2-style) so the tier fits under 2^27 words. Each probe is one heavy build.

## AO. ROOT CAUSE: THE PADS. Pre-pad hosted = 41.5M words (FITS); with pads = 194M (2026-09-05)

Owner's method (revert the optimization) settled it. Checked out flipjump-151 to 0dcda77 (the last
PRE-PAD commit, before the P7 round c6b9634..d22e1d8) and re-probed:

| tier | pre-pad stl (0dcda77) | with pads (d22e1d8, current) | ceiling |
|---|---:|---:|---:|
| hosted | **41,541,186 words -- FITS** | 194,305,602 -- overflow | 134,217,728 |

**The P7 pad round adds 152,764,416 words -- a 4.7x blowup -- and it is uniform across every
region:** seg_pass2_leaf 4.5M->29.2M (6.5x), each cm*_vyd 2.16M->9.96M (4.6x), sprbank unchanged
(2.92M, no exact_xor). The multiplier tracks exact_xor density: `pad 256` on a macro that expands
tens of thousands of times inserts ~128+ filler ops PER EXPANSION, and exact_xor underlies every
hex.xor in the program. This is FINDINGS Y ("pad space scales with TOTAL expansions") realized at
catastrophic scale -- the census only ever saw the ~34k HOT expansions, never the ~total that
padding actually inflates.

**Why only hosted/game broke:** the deg/visual tier is small enough (13M pre-pad -> 62M padded)
that even 4.7x stays under 134M. The hosted tier, 3x larger from M14 collision (baked point-
location + 4 movement descents, all from 2026-08-13, pre-dating the Aug-25 fitting build), is
41.5M pre-pad -> 194M padded -> over. So M14 is the large base and the SEPTEMBER PADS are the
straw, exactly as the owner suspected.

**THE TRADE THE PADS MADE, now fully priced:**
- BOUGHT: -1.6M ops on the deg-tier sweep median (the P7 ledger).
- COST: +49M words on the deg tier (the +3.86MB file bloat S2 later had to undo), AND +153M words
  on the hosted/game tiers -- which makes the SHIPPED PLAYABLE GAME UN-ASSEMBLABLE.

**RECOMMENDATION: revert the P7 pad round in flipjump-151.** It fixes the game/hosted overflow,
shrinks the deg binary further (S2 stacks on a pre-pad base), and costs the -1.6M-op speed gain
(deg median ~16.0M -> ~17.6M). The pad pool was already declared closed (FINDINGS Z) and P8-1's
sparse-pad retry was KILLED (AJ); this shows the ORIGINAL pads were net-negative too once the game
tier is in scope. Speed-vs-size-vs-shippability is the owner's call.

## AP. P10-1: PAD REVERT + SPARSE-ON-HOT -- slim won, speed half-recovered (2026-09-05)

```
SIZE   P7B 15,168,954 -> P9-1(S2) 7,923,027 -> P10-1 6,943,453  (-54% vs P7B, -12% vs P9-1)
MEDIAN 16,038,392 -> 17,135,838  (+1,097,446, +6.84%)   260/260 byte-exact
GAME   assembles (42M words first_address, was 195M) -- the overflow is FIXED
```
stl: pad round reverted (0dcda77) + sparse_exact_xor/xor/zero/mov re-added (defaults pad 16).
doom: 282 hot call sites (36 macros, from the h57_1 knapsack) use sparse_ at pad 512-16384.

**The trade, measured:** slim binary + shippable game, but only ~0.5M of the pads' ~1.6M speed
recovered. Pure pre-pad would be ~+1.6M (+10%); sparse-on-hot lands +1.1M (+6.84%).

**WHY speed under-recovered -- HOT IS VIEWPOINT-DEPENDENT.** The convert list came from ONE frame
(h57_1). DEG's four viewpoints regressed +6.25..+8.92% -- they hammer exact_xor sites h57_1 did
not flag, which stayed un-padded (pad 16) here but were pad 256 in P7B. Padding one viewpoint's hot
set under-covers the others and the sweep.

**NEXT RUNG (the fix): union-over-sweep hot set.** Pad every site hot in ANY sweep frame, not just
h57_1. Cold-in-every-frame expansions (the bulk / the 4.7x bloat) stay un-padded so the binary
stays slim; sites hot in any frame get the pad, recovering that frame's lost speed. Headroom is
~92M words (ceiling 134M, current first_address ~42M pre-pad), so broad coverage is affordable.
Needs per-frame profiles across the sweep viewpoints to build the union.

## AQ. SPARSE-ON-HOT UNDERDELIVERS: width > coverage, and non-exact_xor pads are unreachable (2026-09-05)

Two shippable (game-assembles) rungs on the reverted base:
| build | coverage | pad | median vs P7B | size |
|---|---|---|---|---|
| P10-1 | 36 macros (h57_1) | per-macro 512-16384 | +6.84% | 6.94MB |
| P10-2 | 63 macros (union of 5 vps) | uniform 256 | **+8.39%** | 6.86MB |

**P10-2 is SLOWER despite more coverage** -- uniform pad 256 recovers less per site than P10-1's
wider per-macro pads. WIDTH dominates COVERAGE for speed recovery.

**And broadening exact_xor barely moved DEG (+6.3..7.8% both rungs), because the residual is NOT
exact_xor.** The P7 pad round padded ~8 stl macros; I only built sparse_ variants for exact_xor
(via hex.xor/zero/mov). The pads on `if_flags`, `mul.init`(4096), `add_mul`, `cmp`,
`double_exact_xor`, `triple_exact_xor`, `jump_to_table_entry` are reverted and UNREACHABLE by any
exact_xor tuning. Their share of the -1.6M is simply gone.

**Union-at-full-widths is not an option:** the per-macro-optimal widths on 111 macros = 83M words
of slack = 93% of the ceiling -> would re-overflow. So there is no single (coverage x width) that
both recovers the full -1.6M and stays under 2^27.

**HONEST CONCLUSION.** The pads' 16.04M was NEVER a shippable-game number (it overflows the game
tier). The shippable baseline is pre-pad ~17.6M. P10-1 recovers to 17.14M (+6.84%) at 6.94MB with
the game assembling -- the best shippable result. Fully reaching 16.04M would need sparse_ variants
of ALL padded stl macros at tuned widths, under the ceiling: a large multi-gate optimization with
uncertain payoff. The size+shippability win is banked regardless (6.86-6.94MB vs 15.2MB, game builds).

## AR. THE RESEARCH: how to get 16M on a SHIPPABLE game via selective padding (2026-09-05)

Padding multiplies CODE regions ~4.6x (measured, region-probe diff; sprbank/data is 1.0x). So
padding EVERY expansion overflows, but padding is cheap where EXPANSIONS are few. Per padded macro,
speed-at-stake (union-max hot cost over 5 viewpoints) vs expansions (size driver):

| macro | hot cost | expansions | plan |
|---|---:|---:|---|
| hex.exact_xor | 12,292,049 | 80,114 | SPARSE-on-hot (size killer) |
| hex.double_exact_xor | 2,427,434 | 23,277 | SPARSE-on-hot |
| hex.triple_exact_xor | 1,585,209 | 5,592 | **KEEP padded -- cheap** |
| hex.if_flags | 759,654 | 75,232 | SPARSE-on-hot |
| hex.add_mul | 715,258 | 2,532 | **KEEP padded** |
| hex.add.clear_carry | 609,960 | 4,456 | **KEEP padded** |
| hex.cmp | 372,196 | 62,944 | SPARSE-on-hot |
| hex.tables.jump_to_table_entry | 346,700 | 2,240 | **KEEP padded** |
| read_cell_from_inners_ptrs | 202,078 | 226 | **KEEP padded** |
| hex.mul.init | 115,356 | 14 | **KEEP padded** |
| hex.sub.clear_carry | 44,640 | 185 | **KEEP padded** |

**WHY P10-1/P10-2 ONLY GOT HALF:** they sparse-restored ONLY exact_xor and NEVER re-padded the 7
cheap macros. Those 7 hold ~3.6M of speed-at-stake for ~15k expansions -- re-padding them in the
stl DEFINITION is nearly free on size (~1-2M words vs 92M headroom) and recovers their full speed.

**THE PLAN (selective padding):**
1. RE-PAD the 7 cheap low-expansion macros in the stl definition (free full speed).
2. SPARSE-on-hot the 4 size killers (exact_xor + double_exact_xor + if_flags + cmp) at wide pads
   on hot sites only.
Budget: cheap-keep ~1-2M words + sparse-on-hot hot-only ~10-15M words << 92M headroom. The game
tier stays well under 2^27 AND recovers toward the full -1.6M -> ~16M on a SHIPPABLE game.

Config A (this step): re-pad the 7 cheap + exact_xor sparse-on-hot (P10-1 wide widths). Measures
the cheap-keep contribution on top of exact_xor. double_exact_xor/if_flags/cmp sparse come next
if needed.

## AS. FULL-COVERAGE DEF PADDING BEATS SPARSE-ON-HOT (2026-09-05)

Progress on the shippable path (pads reverted, game-tier-aware):
| config | median vs P7B | size | note |
|---|---|---|---|
| P10-1 sparse 36 macros wide | +6.84% | 6.94MB | sparse under-covers exact_xor's call paths |
| P10-2 sparse 63 macros @256 | +8.39% | 6.86MB | width < coverage; 256 too narrow |
| P10-3 cheap-keep + sparse 36 | +6.94% | 6.80MB | cheap-keep ~0 on MEDIAN (hot in DEG, not median) |
| **P10-4 exact_xor DEF pad 128 full** | **+5.33%** | **7.39MB** | **best; full coverage reaches all call paths** |

**KEY: exact_xor is -1.33M of the pads' -1.6M (P7 ledger: 16->128 -607k, 128->256 -724k), called
from MANY paths (stl-internal mov/cmp, cold doom sites) that sparse-on-hot cannot reach by hand.
Definition-padding covers ALL of them at once.** DEG viewpoints tightened to +4.3..6.2% (vs sparse
+6.25..10.5%). Full coverage is the right lever.

Remaining gap to 16M = ~890k, which is exactly exact_xor 128->256 (-724k) + the double/if_flags/cmp
defs (un-restored). BUT exact_xor def 256 = ~4.6x code = game first_address ~170M > 2^27 (overflow).
def 128 game first_address is 105.9M/134M. So the max full-coverage width is bounded; def 256's
full -1.33M does not fit the game tier. Reaching <16M needs either the max fitting width (~160-192)
+ double/if_flags/cmp def-pads, or shrinking the game base (M14 collision bake) to open room.

## AT. THE PADDING CEILING ON A SHIPPABLE GAME: ~16.58M (+3.41%) (2026-09-06)

Full-coverage selective padding ladder (pads reverted, then re-added definition-wide by hot-cost,
game-tier-aware):
| config | median | size | note |
|---|---|---|---|
| P10-4 exact_xor def 128 | +5.33% (16.89M) | 7.39MB | full coverage >> sparse |
| P10-5 + double64 + if_flags64 | **+3.41% (16.58M)** | 7.62MB | **BEST shippable** |
| P10-6 + cmp64 | +3.61% (16.62M) | 8.03MB | cmp NET-NEGATIVE on median; reverted |

**BEST SHIPPABLE = P10-5: exact_xor def 128 + double_exact_xor 64 + if_flags 64 + 7 cheap-keep +
S2. Median +3.41% (16,584,954), 7.62MB, and the GAME TIER ASSEMBLES** (overflow probe: "reached
emit_reset_part WITHOUT overflow", 105.9M words, 21% headroom at exact_xor 128).

**WHY IT PLATEAUS ~540k ABOVE P7B's 16.04M:** the remaining gap is exact_xor 128->256 (-724k in
the P7 ledger). But exact_xor def 256 = ~4.6x code -> game first_address ~170M >> 2^27 (overflow),
and even def 160 THRASHED (9.7GB RSS, 0.23GB free, ~30% CPU -- the assembler is memory-bound). So
128 is the RAM/address ceiling for exact_xor on the game tier. The median is measured on the DEG
tier but the exact_xor pad is ONE stl definition shared by both tiers, so the game's 128 cap bounds
the DEG median too.

**TO GO BELOW 16M: shrink the GAME BASE first.** The game tier is ~42M words pre-pad, dominated by
the M14 collision bake (ptloc baked point-location + cm*_vyd x4, ~40M words). S2-style sharing on
THAT (as S2 halved the bands) frees address+RAM room for exact_xor pad 256, which drops the median
to ~16.04M or below. That is the next lever; padding alone is exhausted at 16.58M.

## AU. BELOW-16M IS NOT REACHABLE VIA PADDING -- the arithmetic (2026-09-06)

The median (ship criterion, DEG tier) reaches 16.04M only with exact_xor pad 256 (the -1.33M lever).
exact_xor 256 multiplies the game tier 4.6x (measured: 42M base -> 195M). To fit under 2^27 (134M)
at 4.6x, the base must be < 29.1M -- a 13M cut (31% of the 42M base).

Collision bake, pre-pad (region probe): candidate blocks 8.64M (cmh check_position 2.15M + cma/cmb/
cmc try_move 2.16M x3), + seg_pass1_ts_leaf 0.79M + simcollide 0.35M + seg_pass1_leaf 0.25M ~=
10M total. **S2-style try_move sharing saves ~4.3M (2x of the 3 try_move copies); ALL collision is
~10M.** Even cutting all 10M -> base 32M -> x4.6 = 147M -> STILL overflows.

**THE 13M CUT NEEDED FOR exact_xor 256 IS LARGER THAN THE ENTIRE COLLISION BAKE.** So exact_xor 256
cannot fit the game tier by any collision reduction, and below-16M is not reachable via padding.

What collision sharing CAN do: base 42M -> ~37.7M, allowing exact_xor ~192 (37.7 x ~3.4 = 128M <
134M) -> median ~16.3M. Better than P10-5's 16.58M, not below 16M.

**DEFINITIVE: the padded 16.04M (P7B) is a DEG-tier-only number that overflows the game. On a
SHIPPABLE game the padding floor is ~16.3-16.58M. Below 16M needs a fundamentally smaller program
(fewer hex ops / width doctrine / renderer doing less work), not more/wider padding.**
