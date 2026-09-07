# M6 structural ideas — 10 themes, 80 ideas, none of them "pad it more"

The companion document `handoff-m6-optimization-candidates.md` is TACTICAL: ten hot macros, ten
local edits each. This one is STRUCTURAL — it attacks the cost model, the representation, the
emission strategy and the algorithm. Padding is closed (FINDINGS AZ: S2 is the optimum, S3 was
worse on both metrics) and W1-class width narrowing measured at 45,721 ops/frame, which is ~75
edits to close the gap. Something else has to carry it.

Same rules as the tactical doc: **[M]** measured, **[R]** reasoned from source, **[S]** speculative.
**No idea carries an ops estimate** (FINDINGS BC). Baseline: **binding 23,447,960, 51,094,744 words
(38.07% of 2^27)**, gap **3,447,960**.

The one fact that shapes everything below: **`wflip addr, value` costs `popcount(value)` executed
ops**, the xor family is **68.59%** of the frame, and its ops-weighted mean target popcount is
**9.52** against a floor of 1.

---

## THEME 1 — Place hot targets at low-popcount addresses. The single biggest unexplored lever.

Padding aligns a target to `2^k`, which zeroes the low k bits and leaves the high ones alone. That
is why S2 won only 2% and S3 lost: alignment is a weak proxy for what actually matters, which is
**how many 1-bits the target address has**. Measured availability:

| popcount | addresses | cumulative |
|---:|---:|---:|
| 1 | 32 | 32 |
| 2 | 496 | 528 |
| 3 | 4,960 | 5,488 |
| 4 | 35,960 | **41,448** |

**10,000 emitted instances carry 80% of all xor-family ops** (FINDINGS AX). Every one of them could
sit at popcount ≤ 4 — there are four times as many such addresses as we need.

1. **[M] A placement pass.** Rank wflip targets by executed ops (the profile already does this),
   then assign the hottest to the lowest-popcount free addresses. Mean 9.52 → ~3.5 on the hot set;
   `exact_xor` pays the wflip **twice** (arm at entry, disarm at `end`), so the saving doubles.
2. **[R] Place the `end` label too.** Both `wflip src+w, switch, src` and `wflip src+w, switch` at
   the exit target `switch`; but `double_`/`triple_exact_xor` also wflip `first_flip`. Rank and
   place every wflipped label, not just the switch.
3. **[S] Deliberate high-popcount for cold code.** Low addresses are scarce only if cold code
   competes for them. Push the cold bulk to addresses with many 1-bits on purpose.
4. **[R] The emitter already controls layout** — `write_program_files` emits ordered parts and
   "ORDER IS THE CONTRACT". A placement pass is a reordering plus explicit padding, not a new
   mechanism.
5. **[S] Segment the address space by heat.** Put all hot targets inside one `2^k` window whose
   base has popcount 1, so every target in it inherits a low prefix.
6. **[M] Verify against the existing data first.** `_s2_hist.json.gz` plus the label table gives
   the exact popcount of every executed target; compute the achievable mean before building.
7. **[R] Interacts with S2's pads.** If placement lands a target at popcount 2, its `pad` becomes
   pointless — drop the pad and reclaim the size.
8. **[S] A greedy assignment is probably enough** — hot instances are only 2.35% of the emitted
   set, so there is no packing pressure.

## THEME 2 — Batch the xors. `quadrupled_exact_xor` exists and doom never calls it.

`exact_xor` costs one wflip per destination. `double_`/`triple_exact_xor` fold 2 and 3
destinations into ONE wflip, and the profile shows both in heavy use (8.63% + 8.55%).
**`hex.quadrupled_exact_xor` is defined in the stl and referenced zero times in `src/`.**

9. **[M] Find the 4-destination sites.** Anywhere four `exact_xor`s share a source is a
   `quadrupled_` call: 4 wflips → 1. The profile's per-site call lists locate them.
10. **[R] `hex.zero n, x` is `rep(n) xor x,x`** — n independent xors on the SAME source cell.
    A batched form could serve 4 nibbles per wflip.
11. **[R] `hex.mov n` is `zero n` + `xor n`** = 2n xors, all sharing sources pairwise.
12. **[S] Add a `quintupled_`/`octupled_` variant** if the site census shows 5+ sharers.
13. **[R] Reorder computations to create sharers.** Two macros each doing 2 xors from one source
    could be interleaved into one 4-way batch.
14. **[M] The batching is not free**: the double/triple bodies are bigger switch tables. Price the
    size against the win, and remember absorption makes size cheaper than it looks.
15. **[S] Batch across the `dance_boundary` chain** — it exists to move `hex.tables.ret` between
    chained adds; longer chains mean fewer boundaries.
16. **[R] Check `address_and_variable_triple_xor`** (5.2% + 4.9% in place 3) — is the third
    destination live on the common path? A dead one makes `double_` correct and cheaper.

## THEME 3 — Change the representation of hot values

Everything is 4-bit nibbles in 16.16 fixed point. That is a choice, not a law.

17. **[S] One-hot for small enumerations.** A class id or a flag stored one-hot makes "set" a
    single bit flip and "test" a single jump — no switch table, no xor chain.
18. **[R] Screen columns are 0..161** — 2 nibbles, already narrow, but a one-hot 162-bit column
    mask would make "is this column claimed" a single flip.
19. **[S] Bit-serial compare.** `hex.cmp` walks nibbles; comparing most-significant-first with an
    early exit is cheaper when values usually differ high.
20. **[S] Split hot 8-nibble values into two 4-nibble halves** where only one half varies per
    frame; the static half then costs nothing.
21. **[R] `drawn[]` is one byte per column** (place 1, idea 7). A packed bitmask is 8x smaller and
    a whole-word test replaces eight byte reads.
22. **[S] Store deltas, not absolutes.** Column-to-column steps are small; a 2-nibble delta plus a
    running accumulator beats an 8-nibble recompute.
23. **[S] Reduce fixed-point precision where the pixel cannot tell.** 16.16 everywhere is
    conservative; the screen is 160x100 at 8bpp.
24. **[M] Precision is a FIDELITY decision, not an optimisation** — it can move pixels, so it needs
    the owner's ruling and a re-baselined oracle, not just a gate.

## THEME 4 — Bake more into code (the emitter's existing superpower)

`generate_point_location_fj` already bakes point-location as code and FINDINGS records it "27x
cheaper". BSP-as-code is the repo's biggest historical win. What else is still data?

25. **[R] Bake the blockmap walk** the way the BSP descent was baked.
26. **[S] Bake per-subsector line lists as straight-line code** instead of a walked list.
27. **[S] Specialise the column loop per view octant** — eight variants, each with the sign tests
    resolved at emit time.
28. **[S] Bake the common thing-class shading** so `step_shade` becomes a jump, not a lookup.
29. **[R] The tier registry makes a "baked vs walked" A/B cheap** — it is a new row, not a flag.
30. **[M] Baking trades size for ops, and size is 62% free.** That is the trade the ceiling now
    permits and did not at 93.5%.
31. **[S] Partial evaluation of `try_move`** against the four candidate offsets, which are
    compile-time constants.
32. **[R] Watch the absorption interaction** — more baked code shifts addresses and changes every
    downstream popcount (FINDINGS AZ).

## THEME 5 — Self-modifying code, which in FlipJump is not a hack but the ISA

The only instruction modifies memory. The renderer already uses this (`vpb_px`'s 3-lane fcall
return, the `dance_boundary` chain). Push it further.

33. **[S] Rewrite the inner loop's constants per frame** instead of reading them from cells —
    the view angle changes once per frame and is read thousands of times.
34. **[R] The 3-lane fcall pattern generalises**: `stl.fcall`'s landing op is its own disarm, so a
    `pad 4` plus two bit flips selects among 3 continuations. A `pad 8` gives 7.
35. **[S] Arm the whole column loop once per seg** rather than testing per column.
36. **[S] Self-disarming guards**: a check that can only fire once should remove itself.
37. **[R] `m1.zerobyte` is 86.4% one `exact_xor`** — if the reset rewrote its own clear list to
    skip already-zero cells, it would shrink each frame.
38. **[S] Frame-to-frame specialisation**: emit the next frame's hot path from this frame's
    outcome. The M1 reset makes state deliberately non-persistent, so this fights the architecture
    — read `docs/handoff-m1-reset.md` before trying.

## THEME 6 — Classic DOOM algorithmics not yet applied

39. **[R] Visplane merging.** Adjacent columns with the same flat, light and height form one span;
    real DOOM merges them. `frame.seg_pass2_leaf_body_lines` is 24.39% of the frame.
40. **[R] Span coalescing for walls** — the same texture/light run.
41. **[M] `hex.if0 1, full, work` already early-outs on a full screen.** Check WHERE it is tested:
    hoisting it to the caller skips the call frame entirely (place 2, idea 5).
42. **[S] Reject whole subsectors** by screen-space bbox before walking their lines.
43. **[S] Sprite culling by column range** before projection, not after.
44. **[R] `proj.point_on_side_leaf` is 31.6% multiplies** — real DOOM special-cases axis-aligned
    lines to skip the cross product entirely, and `generate_point_location_fj` already bakes 209
    vertical + 209 horizontal of 681 nodes. Verify those 61% skip the multiply; extend if not.
45. **[S] Two-sided line early reject** when both sectors have equal floor/ceiling.
46. **[S] Depth-sorted early termination** — stop a column once it is opaque.

## THEME 7 — Spend the 62% free ceiling

At 93.5% nothing could grow. At 38.07% there are ~83M free words.

47. **[R] Bigger LUTs replacing arithmetic.** `fixed_mul_lo` is 22% of place 2 and 24.6% of
    place 4; a table indexed by the narrow operand may beat the multiply.
48. **[S] Fully unroll the hottest loops** — no counter, no compare, no increment.
49. **[S] Duplicate hot leaf code** so each caller jumps straight in with no pointer rebuild.
50. **[R] `read_table_packed nb` rebuilds the pointer per byte** (~781 ops each, the repo's own
    note). Emitting nb specialised readers removes the rebuild.
51. **[S] Precompute the whole projection for the 8 cardinal view angles** and interpolate.
52. **[M] Every growth idea must be probed** — `overflow_probe game` before the build, and note
    growth raises downstream popcount (AZ), so size is never free even when it fits.

## THEME 8 — Do less work per frame

53. **[S] Render alternate columns and interpolate** — halves the column loop.
54. **[S] Coarser spans**: 2-pixel granularity vertically.
55. **[S] Skip the sprite pass entirely when no thing is visible** — check the bind count first.
56. **[R] The menu frames cost ~2,344 ops** and prove a near-free frame is possible; the question
    is what the game frame does that the menu does not.
57. **[M] All of THEME 8 moves pixels** — fidelity decisions, owner's call, and each needs the
    oracle changed in the same commit (CLAUDE.md rule 2).

## THEME 9 — Attack the reset and the per-frame overhead

58. **[M] The M1 reset is ~830,000 ops/frame** (2.11%, FINDINGS BB) — measured at last, and
    smaller than the plan assumed.
59. **[S] Dirty-tracking**: restore only what the frame wrote. The big structural idea, and the
    riskiest — a missed cell hangs the next frame.
60. **[R] Split the restore set** into always-dirty and rarely-dirty; hash-check the second half.
61. **[R] `zerobyte` clears one byte inside a cell** — runs of adjacent bytes could be one wider
    clear.
62. **[R] Verify no cell is both restored and persisted** (`STANDALONE_PERSIST`/`DOOR_PERSIST`).
63. **[S] Restore lazily on first read** — a large change to the M1 contract.

## THEME 10 — Measure before building. Several answers already exist.

64. **[M] `ablate` has 20 modes already** (`noprescan`, `pnearprune`, `tsfull`, `sprnoemit`...).
    Each prices a feature with no new code. Run them.
65. **[M] The `hosted-nocollide` tier exists** — a hosted A/B for collision needs no emitter work,
    unlike the `game-nocollide` row that would not build (FINDINGS AV).
66. **[M] The saved histograms answer new questions with no run** — `_s2_hist.json.gz` plus a
    label table re-attributes in seconds.
67. **[R] Re-run the profile after ANY accepted change**, with labels from the same build
    (`labels2.py`), or the attribution is the AY failure again.
68. **[M] Price collision properly** before rung 2: the plan's ~11.6M is 2.6x too high, and
    ~4.5M is now larger than the whole remaining gap — so it is worth pricing exactly.
69. **[R] The `steps=False` lines config** is a program the gates never build; a bug could hide
    there.
70. **[S] Profile a SECOND walk** — everything here rests on seed 0. A different route may rank
    differently.

---

## The four I would build first, in order

71. **[M] Hot-address placement (THEME 1).** It attacks 68.59% of the frame at the mechanism level,
    the addresses are provably available (41,448 at popcount ≤ 4 for 10,000 needed), and it is the
    thing padding was a weak approximation of.
72. **[M] Lazy bbox read** (tactical doc idea 7.1) — 5.12% of the frame in one call, and the source
    comment already names the fix.
73. **[M] `quadrupled_exact_xor` at 4-destination sites (THEME 2)** — an stl macro that already
    exists, called zero times, turning 4 wflips into 1.
74. **[R] `read_table_packed` specialisation (idea 50)** — kills the per-byte pointer rebuild that
    makes idea 72 expensive in the first place.

## And the six things NOT to do

75. **Do not pad more.** S2 is the optimum; S3 was worse on both metrics (AZ).
76. **Do not narrow more widths expecting much** — W1 measured 45,721, i.e. ~75 more edits.
77. **Do not plan against collision's ~11.6M** — it is ~4.5M (BB).
78. **Do not trust `distscale`-style attribution** without a matched-label profile (BA).
79. **Do not pad `sim.try_move`, `check_position` or `thing_record_body`** — instance-heavy, and
    S3 proved including them hurts.
80. **Do not estimate an op saving in a commit message.** Rank with the profile, size by building
    (BC). Three estimates missed by 2M words, 33M words and 7.9x.
