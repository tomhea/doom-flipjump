# M6 optimisation candidates — 10 places, 10 ideas each

**Ground rules for this document.** Every "place" is ranked by a MEASURED share of the frame, from
the matched-label profile of the S2 binary (`scratchpad/12m/_s2_hist.json.gz` +
`_full_labels.tsv.gz`, 78,675,599 ops, 100.0% attributed). Every idea says what evidence it rests
on. **No idea carries an ops estimate**, because FINDINGS BC: the profile RANKS correctly and does
not SIZE anything — W1 was predicted at ~362k ops/frame and measured 45,720, a 7.9x miss, and two
earlier estimates missed by 2M and 33M words. Size by building, not by arithmetic.

Confidence tags: **[M]** mechanism measured or read directly in the source · **[R]** reasoned from
the code but unverified · **[S]** speculative, needs a spike before it is worth a build.

Baseline to beat: **binding 23,447,960 ops/frame, 51,094,744 words (38.07%)**, `m2_std_gate` PASS.

---

## The measured ranking (outermost doom macro)

| # | place | ops | share |
|---|---|---:|---:|
| 1 | `frame.seg_pass2_leaf_body_lines` | 19,189,640 | 24.39% |
| 2 | `frame.seg_pass1_leaf_body_lines` | 13,653,599 | 17.35% |
| 3 | `frame.seg_pass1_leaf_body_ts` | 10,022,272 | 12.74% |
| 4 | `frame.thing_record_body` | 5,028,047 | 6.39% |
| 5 | `sim.thing_pass` | 4,876,520 | 6.20% |
| 6 | `proj.point_on_side_leaf` | 4,659,646 | 5.92% |
| 7 | `sim.try_move` | 4,211,386 | 5.35% |
| 8 | `sim.check_position` | 3,448,345 | 4.38% |
| 9 | `sim.bind_things` | 2,226,365 | 2.83% |
| 10 | `m1.zerobyte` (the M1 reset) | 1,657,895 | 2.11% |

⚠ **The frame is flat** (FINDINGS BB). These ten are 87.7% of it, but no single one is a
target whose removal closes the 3,447,960 gap. Expect many small wins, or a structural change.

---

## THE BIGGEST SINGLE FINDING, and it spans places 7 and 8

`hex.read_table_packed 8, cl_box, lnbox, n_ln, li` is **55.4% of `sim.try_move` and 49.4% of
`sim.check_position`** — together **5.12% of the whole frame** in ONE call. The comment directly
above it already names the fix and does not apply it:

> *"the BBOX HALF ONLY — 8 bytes... Most candidates die on the four compares below, and every byte
> read for them was wasted... Same lever M14.5 applied to `thing_load`."*

It reads all 8 bbox bytes, then immediately runs four rejects that kill most candidates on the
first compare. `read_table_packed nb` is `nb` separate byte reads each rebuilding the pointer
(~781 ops each by the repo's own note), so the wasted work is proportional and large. **This is
idea 7.1 and it is the one to try first.**

---

## 1. `frame.seg_pass2_leaf_body_lines` — 24.39%

Hot calls: `sparse_mov@l2398` (width 8, 5.5%), `address_and_variable_triple_xor` (2.6% + 2.3%),
`sparse_mov@l2384` (width 4, 2.5%), `xor_zero`/`xor` via `dance_boundary` (4.4%),
`sparse_mov@l2489` (width 2, 2.3%).

1. **[M] The `sparse_mov 8, x, x1` here is already narrowed by W1** — confirm the same treatment is
   applied to every remaining width-8 mov in this macro, not just the one W1 caught. The profile
   lists the call sites; walk them.
2. **[R] `sparse_mov@l2384` is width 4 on a value that may be 2.** Check what it moves; the same
   [0,161] column argument may apply.
3. **[R] Hoist the loop-invariant part of the claim loop.** `dbase`/`dptr` are re-aimed per seg;
   if consecutive segs share a base, the `hex.set w/4, dbase, drawn` is redundant.
4. **[M] `dance_boundary` is called from here and is 4 ops of pure chaining machinery.** It exists
   to move `hex.tables.ret` between chained adds. Fewer, longer chains mean fewer boundaries —
   check whether the chain length is a tunable.
5. **[R] The `address_and_variable_triple_xor` pair (4.9% together)** writes three destinations
   from one source. If two of the three are dead on the common path, a `double_xor` is cheaper.
6. **[S] Merge pass 1 and pass 2 leaf walks.** They iterate the same leaf lines twice with
   different bodies; one walk with a fused body would halve the walk overhead, but it is a large
   restructure and the two passes exist for occlusion ordering.
7. **[R] The stride-1 `drawn[]` scan is byte-per-column.** A packed bitmask (8 columns/byte) would
   cut the scan 8x, at the cost of bit extraction — price the extraction first.
8. **[R] Early-out the claim loop on a fully-claimed span** rather than walking to `x2`.
9. **[S] Cache the previous seg's `x1..x2` and skip the scan entirely when the new span is a
   subset** of an already-fully-claimed range.
10. **[M] Re-check the pad tier here.** S2 gave this macro pad 1024 on a median of 207 ops/frame;
    S3 showed 4096 was too far globally, but per-site tuning was never swept (AZ says the knee is
    between S2 and S3 and does not say where).

## 2. `frame.seg_pass1_leaf_body_lines` — 17.35%

Hot calls: `sparse_mov@l2332` (width 8 — **W1 fixed this one**, 13.6%), `fixed_mul_lo@l2016` and
`@l2017` (width 8, 11.4% + 10.6%), `xor_zero`/`xor` (12.6%), `fixed_mul_lo.row@l124` (3.9%).

1. **[M] The two `fixed_mul_lo` width-8 calls are 22% of this macro.** They are 16.16 multiplies;
   8 nibbles is genuinely needed for the product, but check whether either OPERAND is narrow — a
   narrow multiplicand may allow a cheaper row schedule.
2. **[R] `fixed_mul_lo.row` at 3.9% is the inner row of the same multiply.** FINDINGS records
   P3-1/P3-2 already reworked `fixed_mul_lo`'s row driving; re-read those before touching it.
3. **[M] W1's narrowing applied here; verify no other width-8 mov remains** in the macro.
4. **[R] `hex.set 1, proceed, 0` then `hex.set 1, proceed, 1`** — a one-nibble flag written twice
   on the success path. A single write at the exit is cheaper.
5. **[R] `hex.if0 1, full, work` guards the whole body**; if `full` is common late in a frame,
   hoisting the check to the caller skips the call frame entirely.
6. **[M] The occlusion pre-scan is ablatable already** (`rep(noscan, k) .lines_jmp occproc`), so
   its value is measurable without new code — run the ablation and see what the pre-scan buys.
7. **[R] `wedge_reject` runs before the affine cull.** Check the reject rates: if the wedge rarely
   rejects, it is pure overhead; if it usually rejects, move MORE work behind it.
8. **[S] Share the `drawn[]` pointer with pass 2** rather than rebuilding it per pass.
9. **[R] `hex.cmp 2, x, x2` + `hex.inc 2, x` per column** — a countdown to zero would replace the
   compare with a zero-test, which is cheaper in this ISA.
10. **[S] Batch the column scan by 4** with an early exit, trading exactness of the stop position
    for fewer compares.

## 3. `frame.seg_pass1_leaf_body_ts` — 12.74%

Hot calls: `address_and_variable_triple_xor` (5.2% + 4.9%), `xor_byte_to_flip_ptr` (5.1%),
`read_hex@l1032` (4.7%), `xor_zero` (4.3%), `sparse_mov@l1209` (width 2 — already narrow).

1. **[M] This macro already uses the SAFE narrow pattern** (`sparse_zero 8, x` + `sparse_mov 2`)
   because `ptr_index4` indexes by `x` here. Do not "fix" it to match places 1–2.
2. **[R] `xor_byte_to_flip_ptr` at 5.1%** rebuilds a flip pointer per byte. If consecutive bytes
   are adjacent, an increment is cheaper than a rebuild — the same lever as idea 7.1.
3. **[R] `read_hex@l1032` at 4.7%**: check its width; if it reads 8 nibbles of a value that is
   2 wide, it is W1 again.
4. **[M] The triple_xor pair is 10.1% of this macro.** Check whether all three destinations are
   live; a dead third destination makes `double_xor` correct and cheaper.
5. **[R] `ptr_index4` is called under `rep(2-PID_BYTES, k)`** — a compile-time rep. Confirm
   PID_BYTES makes this 1 iteration in the shipped config, not 2.
6. **[S] The TS (two-sided) path duplicates much of the lines path.** Factor the shared prologue.
7. **[R] `hex.cmp 2` / `hex.inc 2` loop** — same countdown idea as 2.9.
8. **[S] Precompute the per-face constants once per seg** instead of per column.
9. **[R] Check the pad tier**: S2 gave this pad 1024 at a median of 136 ops/frame, the lowest of
   the tiered set. It may be below the threshold where padding pays at all.
10. **[S] Skip the TS body entirely for segs with no back sector** — verify the caller already
    does this before spending a build.

## 4. `frame.thing_record_body` — 6.39%

Hot calls: `fixed_mul_lo@l1395` (width 8, 15.4%), `@l1396` (width 8, 9.2%), `xor`/`xor_zero`
(9.3%), `scmp@l1401` (width 8, 4.1%), `add@l1346` (2.0%).

1. **[M] Two width-8 `fixed_mul_lo` calls are 24.6% of this macro** — the sprite scale multiplies.
   Same question as 2.1: is either operand narrow?
2. **[M] `scmp 8` at 4.1%** — a SIGNED 8-nibble compare. If the compared quantity is a screen
   coordinate (which the surrounding code suggests), an unsigned 2-nibble compare is ~4x cheaper;
   this is the exact lever the M13-lines3 comment describes applying elsewhere.
3. **[R] `step_shade` does `hex.zero w/4, sh_idx` then writes only 4 nibbles** — the same
   `zero 8` + narrow-write shape W1 optimised, if `ptr_index6` does not read all 8.
4. **[R] `frame.sub2_chain sh_idx, y1` + `hex.inc 2, sh_idx`** computes `y2-y1+1`; folding the +1
   into the subtraction constant removes an increment per thing.
5. **[R] The class byte is read in place** (`read_byte cls, sh_p`) — good. Check the caller does
   not re-read it.
6. **[S] Hoist the shade lookup out of the per-thing loop** when consecutive things share a class
   and clipped height.
7. **[R] `add@l1346` at 2.0%** — check its width.
8. **[S] Sort things by class once** so the shade pointer is monotone and can be incremented.
9. **[R] Verify the thing loop early-exits on the invisible case** before doing any multiply.
10. **[M] This macro was EXCLUDED from S2's pad tiers** (median 68 ops/frame, below the >99
    threshold) and S3 showed including it made things worse. Leave it unpadded.

## 5. `sim.thing_pass` — 6.20%

Hot calls: `ptr_index@l576` (width 8, 22.6%), `read_table_packed@l348` (width 8, 19.6%),
`read_hex@l359` (11.7%), `sparse_zero@l577` (8.0%), `read_byte@l578` (width 2, 7.4%).

1. **[M] `ptr_index` is 22.6% of this macro and works at `w/4` = 8 nibbles unconditionally**
   (`frame_render.fj:1590`: `mov w/4` + `shl_hex w/4` + `shr_bit w/4` + `shl_hex w/4` +
   `add8_chain`). A thing index is small — a narrow `ptr_index` variant is the single best idea
   here, and it also helps place 9.
2. **[M] `read_table_packed 8` at 19.6%** — same eager-read problem as idea 7.1; check whether the
   consumer rejects early.
3. **[R] `sparse_zero@l577` (8.0%) immediately precedes the `ptr_index`** — if `ptr_index` writes
   all 8 nibbles of its destination, the zero is dead.
4. **[M] 15 `hex.zero` calls were converted to `sparse_zero` in S2.** Check whether any of them
   zero a cell that is fully overwritten immediately after.
5. **[R] `read_byte@l578` is width 2 and follows the pointer build** — fine; the cost is the
   pointer, not the read.
6. **[S] Keep the thing pointer live across iterations** and increment, rather than rebuilding per
   thing (the `read_byte_and_inc` pattern already exists in `read_table_packed`).
7. **[R] The zero-invariant clears at the end** (`sp_*` registers, guarded by a host test) run
   unconditionally — skip them when no runtime thing was loaded.
8. **[S] Split the loop into "any runtime things?" fast path** and the general path.
9. **[R] Check the pad tier** — S2 gave this pad 1024 at a median of 614 ops/frame, the second
   highest. It may deserve 4096 on its own even though the global S3 sweep failed.
10. **[S] Bind things once per frame rather than per pass** if `bind_things` (place 9) and this
    share work.

## 6. `proj.point_on_side_leaf` — 5.92%

Hot calls: `mul_lo@l1743` (16.3%), `@l1744` (15.3%), `sparse_mov@l1741` (width 5, 9.4%),
`sparse_mov@l1718` and `@l1716` (width 10, 8.4–9.3%).

1. **[M] Two `mul_lo` calls are 31.6% of this macro** — the side-of-line cross product. A sign
   test does not need the full product: comparing magnitudes with the operands' signs can decide
   the side without multiplying in many cases.
2. **[M] Two width-10 `sparse_mov` calls (17.7%)** — 10 nibbles is wider than a 16.16 fixed value.
   Check what needs 40 bits; this smells like a W1 opportunity.
3. **[M] `sparse_mov@l1741` is width 5** — check whether 5 is genuinely needed or a rounded-up 4.
4. **[R] The leaf form was specialised already** (`point_on_side_leaf` vs the general form); check
   the general form is not also called on the hot path.
5. **[S] Precompute the line's normal once per line** rather than per query — this is the classic
   DOOM `R_PointOnSide` optimisation and the emitter bakes lines, so it may be a compile-time win.
6. **[R] `xor_zero` at 7.2%** — the standard chaining cost; see 1.4.
7. **[S] Branch on the axis-aligned cases first.** Real DOOM special-cases vertical and horizontal
   lines to avoid the multiply entirely; `generate_point_location_fj` already bakes 209 vertical +
   209 horizontal of 681 nodes, so 61% of nodes may already skip it — verify, then extend.
8. **[R] Check the pad tier** — S2 gave this pad 4096 at a median of 2,626 ops/frame, the highest
   of any site. It is the best candidate for a per-site pad sweep.
9. **[S] Memoise the last query's subsector** — consecutive queries often land in the same leaf.
10. **[R] Confirm the caller cannot hoist the query** out of a per-column loop.

## 7. `sim.try_move` — 5.35%

Hot calls: **`read_table_packed@l123` (width 8, 55.4%)**, `read_table_packed@l258` (width 8,
22.9%), `scmp@l127`/`@l130` (width 8, 7.9%), `read_table_packed@l248` (2.7%).

1. **[M] ⚠ THE ONE TO TRY FIRST — lazy bbox read.** `read_table_packed 8` fetches all 8 bbox bytes
   before four compares that reject most candidates. Read minx (2 bytes), compare, and fetch the
   rest only on survival. The source comment already identifies this and cites M14.5 doing exactly
   this for `thing_load`. Affects places 7 AND 8 — **5.12% of the whole frame**.
2. **[M] `scmp 8` x2 (7.9%)** — signed 8-nibble compares on bbox coordinates. Map coordinates are
   16.16; the integer half may suffice for a reject, making these 4-nibble.
3. **[M] `read_table_packed@l258` is the inner line-list read (22.9%)**, 2 bytes per line but a
   full pointer rebuild each time. Walk the list with an incrementing pointer instead.
4. **[R] The block-row prologue does 5 movs/zeros of width 4** (`cb_first`, `cb_count`, `cb_k`,
   `cb_kend`) where `cb_k` and `cb_kend` are both copies of `cb_first`. Compute `cb_kend` once as
   `first + count` and drop one mov.
5. **[R] `hex.mov 4, cb_count, cb_row + 4*dw` after `hex.zero 4, cb_count`** — the zero is dead if
   the mov writes all 4; it writes 2 (`hex.mov 2`), so only the top 2 need clearing.
6. **[R] `hex.cmp 4, cb_k, cb_kend`** per line — a countdown on `cb_count` replaces a compare with
   a zero-test.
7. **[S] Cache the blockmap row** across the four collision candidates; `cma/cmb/cmc/cmh` often
   query overlapping blocks.
8. **[S] Reject the whole block early** when the mover's bbox does not intersect the block bounds.
9. **[R] `mul_const 4, cb_idx, cb_by, nbx` + `add 4`** — the blockmap index. If `nbx` is a power of
   two the multiply is a shift.
10. **[M] This site was EXCLUDED from S2's pads** (0.43 ops/instance, 72,444 instances — the worst
    candidate by FINDINGS AX) and S3 confirmed including it hurt. Keep it unpadded.

## 8. `sim.check_position` — 4.38%

Hot calls: `read_table_packed@l123` (width 8, 49.4%), `@l258` (27.3%), `@l248` (5.2%),
`scmp@l127`/`@l130` (6.7%), `zero@l59` (2.0%).

1. **[M] Shares lines 123/248/258 with place 7** — every idea 7.1–7.9 applies here at the same
   time, from the same edit. That is what makes 7.1 worth 5.12% rather than 2.96%.
2. **[R] `check_position` and `try_move` differ only in what they do on success.** Confirm they
   share the emitter path so a fix cannot land in one and not the other.
3. **[M] `zero@l59` at 2.0%** — check its width against what is written after it.
4. **[R] The four candidate blocks** (`cma/cmb/cmc/cmh`) each re-run the seed descent; FINDINGS
   records the descent is already shared via `stl.fcall` but the four bodies are not.
5. **[S] Memoise the subsector across candidates** — if two candidates land in the same subsector
   the second descent is redundant (this is the plan's rung-2 idea 3, still unpriced).
6. **[R] Early-exit the candidate chain** the moment a full move succeeds; check whether the
   emitted `hex.if0 1, mv_ok, {nxt}` already does this and where the ops actually go if so.
7. **[S] Share `try_move`'s body across the three slide candidates** (the plan's rung-2 idea 1) —
   but note G4: that is a SIZE lever worth ~4.3M words and buys no ops.
8. **[R] Check whether the bbox reject can use the blockmap** to skip whole lines cheaply.
9. **[R] Confirm the collision runs once per frame, not per candidate per axis.**
10. **[M] Collision totals ~18% of the frame, not the ~11.6M ops/frame the plan assumed** — that
    figure is 2.6x too high (FINDINGS AW). Re-price rung 2 before designing against it.

## 9. `sim.bind_things` — 2.83%

Hot calls: `write_hex@l523` (15.2%), `read_hex@l495` (14.4%), three `ptr_index` calls at width 8
(l493, l527, l532 — 30.2% together), `sparse_zero@l513` (7.9%).

1. **[M] Three width-8 `ptr_index` calls are 30.2% of this macro** — the same unconditional
   `w/4` pointer build as idea 5.1. A narrow variant fixes both places at once.
2. **[R] Two of the three `ptr_index` calls may share a base** — build once, increment twice.
3. **[R] `read_hex@l495` then `write_hex@l523`** — a read-modify-write of the same cell. If the
   pointer is unchanged between them, keep it live.
4. **[M] `sparse_zero@l513` (7.9%)** — check whether the cell is fully overwritten after.
5. **[S] Bind incrementally**: only re-bind things whose subsector changed since last frame.
6. **[R] The bind loop walks all things**; a count guard skips it when the map has none nearby.
7. **[R] Check the pad tier** — S2 gave this pad 4096 at a median of 1,350 ops/frame; a per-site
   sweep may find better.
8. **[S] Fold `bind_things` into `thing_pass`** (place 5) if they walk the same list.
9. **[R] `hex.dec`/`hex.inc` widths** — confirm they match the loop counter's real range.
10. **[S] Pack the thing→subsector map** so the write is a byte rather than a hex vector.

## 10. `m1.zerobyte` — the M1 self-reset, 2.11%

Hot calls: `exact_xor@l50` (86.4% of the macro!), `@l49` (5.3%), `zero@l43` (5.1%).

1. **[M] ONE `exact_xor` call is 86.4% of the reset.** Read `src/fj/m1_reset.fj:50` first; the
   whole rung-4 cost is concentrated in a single line.
2. **[M] The reset is ~830,000 ops/frame** — measured at last (FINDINGS BB), and far smaller than
   the plan's rung 4 implied. It cannot close the gap alone; budget effort accordingly.
3. **[R] The restore set is 474 entries / 12,400 words** restored every frame. Anything provably
   unchanged since the last frame need not be restored.
4. **[S] Dirty-tracking**: restore only cells the frame actually wrote. This is the big structural
   idea and it is also the riskiest — a missed cell hangs the next frame (M1's known failure mode).
5. **[R] `zerobyte` clears a byte inside one cell.** If runs of adjacent bytes are cleared, a
   wider clear amortises the pointer work.
6. **[R] Check `rep(159, ...)` bounds** — the profile shows rep indices up to 682 here; confirm the
   loop count matches the actual restore-set size and is not rounded up.
7. **[S] Split the restore set into "always dirty" and "rarely dirty"**, and check the rarely-dirty
   half against a hash before restoring.
8. **[R] The `STANDALONE_PERSIST`/`DOOR_PERSIST` holes are deliberate** — verify no cell is being
   restored that is also persisted (wasted work).
9. **[S] Restore lazily on first read** rather than eagerly at frame start — a large change to the
   M1 contract; read `docs/handoff-m1-reset.md` before considering it.
10. **[M] Do not pad this macro.** It is 2.11% spread over a huge rep, and S3 showed instance-heavy
    sites are where padding turns negative.

---

## How to run these

1. **One idea per build.** S3 moved two variables and its result is uninterpretable as a result —
   the knee is known to be between S2 and S3 and nothing more.
2. **`overflow_probe game` on any stl or shared-emitter change**, before the build (§6b).
3. **`m2_std_gate` is the correctness gate** — 43 byte-exact game frames of 45 presented, and it caught nothing this
   session only because every change was genuinely equivalent. Treat a PASS as the evidence, not
   the reasoning that preceded it.
4. **Rank with the profile, size by building** (BC). Do not put an ops estimate in a commit message
   before the measurement exists.
5. **Re-profile after any accepted change** — with labels from the SAME build (`labels2.py`).
   Attributing a histogram to another build's labels is what produced FINDINGS AY and cost a full
   build-gate-measure cycle to disprove.
