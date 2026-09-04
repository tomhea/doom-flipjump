# THE 12M CAMPAIGN -- plan of record (2026-09-04)

GOAL, HARD: the 260-frame ca2_sweep MEDIAN below 12,000,000 ops/frame.
Start: 18,982,338 (after the 20-idea campaign + the 5-idea ts round; -21.9% from 24,306,866).
Required: -6,982,338 (-36.8%) -- more than everything shipped so far combined. This plan treats
that seriously: the yield ranges below sum to the target only if the structural phases land
near their tops, so the plan includes second-order rounds and a wall protocol, not a soft stop.

## 0. The owner's constraints (asked and answered, 2026-09-04)

1. **Strict per-idea sweeps.** Every idea ships alone: deg 4/4 byte-exact + its own 260-frame
   sweep with the median improved. No batching. ~35 min of machine time per idea is accepted.
2. **The screen device stays simple.** No added complexity to InMemoryScreen; rendering logic
   lives on the doom side. A device change is allowed ONLY if it keeps the device equally
   "stupid" or simpler. The deep emit-protocol pool is therefore OFF the table; the emit work
   is doom-side only.
3. **Doom-local macros first**; promote to the stl (tests + CR into 1.5.1) at consolidation
   points when a macro proves general. (The chain family and the coming second-arm apparatus
   are the expected candidates.)
4. **12M is a hard target.** When pools run dry, re-attribute and generate new pools; walls
   are reported with data, never assumed.

## 1. Standing doctrine (all of it applies to every idea)

- The sweep median is the ONLY ship criterion; deg viewpoints are worst-case pre-gates.
- Byte-exactness 260/260 + 4/4; an op-count change with clean pixels still means structure
  changed -- explain it or kill it.
- SHAPE AND PLACEMENT ARE COUPLED: any hot-region resize ships with a tune_round.
- Deletions are layout-frozen with UNREACHABLE filler (behind a jump, never fall-through);
  the freeze is verified by LABEL DIFF against the previous build every single time.
- Width is a first-class cost: scmp/mov/set/zero/dec scale ~linearly with nibbles. Every
  narrowing carries a proof (bound assert at emit, or a sign-extension construction argument).
- A marking-seg-only change moves the min sweep frame by +-0 (free confinement check).
- The tree is LOCKED while a build's assembler may read it.
- Estimates are 5-9x optimistic historically; only the gate's number enters the ledger.
- Killed ideas are replaced until the phase's quota of WORKING ideas is met.

## 2. Phase 0 -- instruments (before any idea)

- **The atlas**: per-op IP profiles (--bucket-bits 6) on ~8 population-spanning frames of the
  current best binary; per-line pricing of every macro region (the section-19 method applied
  to the WHOLE program, not just ts). Output: a ranked target table with measured sizes.
  Re-run at every phase boundary -- structural phases reshape the pools (ts3 proved it).
- **The ritual driver**: one script wrapping build -> label-diff freeze check -> deg compare
  vs baseline -> sweep -> (on shape change) tune_round -> ledger row. With ~100 ideas the
  ritual is the wall-clock; it must be one command.
- The existing kit: popcount_census (capture/rank/rank-values/predict/simulate), tune_round,
  frame_costs, the chain generator + smokes.

## 3. The pools and their quotas (>=10 WORKING ideas each; kills replaced)

**P1 -- the width doctrine sweep** (target -1.5..-2.5M; the highest-confidence family).
Every register in frame_render/projection/stream_render gets a bound (emit assert or
construction proof) and every op on it narrows. Known entries: the hex.cmp pool (1.1M),
project_thing/trb widths, wedge quotient widths, stream emit registers, sga/scale movs,
the remaining 8-wide ops in the pass-2 loop. ts3 (-386k from ONE datapath) is the model.

**P2 -- the deref and arm protocol** (target -0.8..-1.5M).
The second-arm apparatus: doom-local to_flip2/to_jump2/shadow2 + a dance-only read/write clone
against the SHARED stl decoder table, with an R9 negative control BEFORE first use. Then:
arm-carried +1 walks for drawn[] in BOTH passes, the 4-byte piece-write run in ts_piece_wr,
sfslot/sprite-slot walks, and the sfflag-into-drawn fold (kills a read + a pointer per column
in two passes; selfreset BYTE_ARRAY_NAMES + both restore sets move with it).

**P3 -- multiplies and division** (target -0.8..-1.5M).
fixed_mul rows 1.7M: ROW-RULE pruning by proven operand nibble-bounds site by site; more
per-column products converted to DDAs where a linear walk exists; wall_scale_setup's divide
(~470k): 1-column sliver special case (scalestep = diff), narrower quotient ladder, and the
sga clamp movs at width 6.

**P4 -- geometry and the walk** (target -0.6..-1.2M).
Axis-aligned BSP nodes inlined at bake time (61% of E1M1 nodes; sign tests instead of the
point_on_side fcall trio); wedge_reject narrowing; project_thing width + chain follow-ups;
the fcall/ret protocol itself (stl.fcall is ~2.5w@ per call, hundreds of calls/frame -- a
lighter doom-local call/ret for the hot leaves, hot-ret placement via the census).

**P5 -- the emit path, doom side only** (target -0.4..-0.8M).
The V4 signature ladder short-circuited by the dirty flags that already exist (ldirty/sdirty
+ new per-group signature dirties); emit call-site batching; cheaper run construction before
the device boundary. The device format itself: frozen unless a change makes it SIMPLER.

**P6 -- stores, slots, loaders round 2** (target -0.4..-0.8M).
ts_piece_store's remaining ~1M: deferred flag write-back, the P2 write-run applied, sentinel
path narrowing; the load2/spr_load if_flags dispatch rewrite (packed-count tables); the
pass-2 claim path.

**P7 -- zero/init deletions + recurring placement** (target -0.3..-0.6M).
The hex.zero remainder (zero-before-overwrite wave 2, read0-style elisions elsewhere);
tune_round after every shape change plus a standalone round per phase boundary.

**P8 -- second-order rounds to close the gap.**
Re-attribute after P1-P7 (the pools WILL have reshaped); the largest surviving pool gets a
dedicated round like section 19's, repeated until the median is below 12,000,000. Candidate
deep unlocks held in reserve: leaf class-splitting by seg shape (bake-time specialization),
present/init-path work, chain coverage of stl-internal dances (div/mul internals as
doom-local variants).

## 4. Cadence and consolidation

- Ideas ship one at a time, each with its own commit carrying the gate numbers.
- CONSOLIDATION at every phase boundary: tests/host -q, the steps=False lines test,
  tests/fj (full), m5_gate --smoke (full m5_gate at campaign end), restore-set re-keys for
  everything parked (p2_ldirty/p2_sdirty and whatever P2 adds), a handoff section, and the
  atlas re-run.
- The fj-repo promotion review (constraint 3) happens at consolidation, not mid-phase.

## 5. Honest arithmetic and the wall protocol

Sum of targets: -4.8M..-8.9M against a needed -7.0M. The plan reaches 12M only if P1+P2 land
near their tops AND P8 harvests the reshaped pools. If, after P8's first pass, the atlas shows
the remaining certified-idea pool cannot bridge the gap, the wall is REPORTED with the atlas
numbers and the specific blocked unlocks (most likely: the frozen device protocol) -- with
options, not a silent stop. Machine-time estimate at strict cadence: roughly 60-80 gate hours
spread over the sessions it takes; engineering time on top.
