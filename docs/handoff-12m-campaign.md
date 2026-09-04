# THE 12M CAMPAIGN -- plan of record (2026-09-04)

GOAL, HARD: the 260-frame ca2_sweep MEDIAN below 12,000,000 ops/frame.
Start: 18,982,338 (after the 20-idea campaign + the 5-idea ts round; -21.9% from 24,306,866).
Required: -6,982,338 (-36.8%) -- more than everything shipped so far combined. The yield ranges
below sum to the target only if the structural phases land near their tops, so this plan
includes second-order rounds and a wall protocol, not a soft stop.

---

## 0. The owner constraints (asked and answered 2026-09-04)

1. **Strict per-idea sweeps.** Every idea ships alone: deg 4/4 byte-exact + its own 260-frame
   sweep with the median improved. No batching. ~35 min of machine time per idea is accepted.
2. **The screen device MAY be modified -- while staying "stupid".** Operational test, all four
   must hold: (a) the device makes no rendering DECISIONS (no clipping, no spans, no texture
   or palette logic, no geometry); (b) it holds no state beyond a trivially describable
   cursor/counter; (c) the change removes or preserves special cases -- never adds a mode that
   needs a paragraph to explain; (d) a reader can state what the device does in one sentence
   after the change. Widening a field, simplifying an opcode, or DELETING a special case
   qualifies. A second frame format, a run-list dialect, or "the device figures out X" does
   not. Every device change ships in ONE commit with: the fj-repo test + CR into 1.5.1, the
   oracle mirror, and the doom side -- and a one-sentence device description in the message.
3. **Doom-local macros first**; promote to the stl (with tests + CR into 1.5.1) at
   consolidation points, when a macro proves general. The chain family and the coming
   second-arm apparatus are the expected candidates.
4. **12M is a hard target.** When pools run dry, re-attribute and open new ones; a wall is
   reported with atlas numbers and named blocked unlocks, never assumed.

## 1. Standing doctrine (applies to every idea, no exceptions)

- The sweep median is the ONLY ship criterion; deg viewpoints are worst-case pre-gates.
- Byte-exact 260/260 and 4/4. An op-count change with clean pixels still means structure
  moved -- explain it or kill it.
- SHAPE AND PLACEMENT ARE COUPLED: any hot-region resize ships WITH a tune_round.
- Deletions are layout-frozen with UNREACHABLE filler (behind a jump, never in the
  fall-through -- 0;0 in the fall-through jumps to address 0 and the frame dies).
- THE FREEZE IS VERIFIED BY LABEL DIFF EVERY BUILD. Never trust the op-by-op estimate;
  3 of 5 ts builds drifted. Carry residuals forward into the next filler.
- Width is a first-class cost. Every narrowing carries a proof: an emit-time bound assert or
  a construction argument (e.g. "sign_extend built it from 4 nibbles").
- A change scoped to marking segs must move the MIN sweep frame by +-0 (free confinement check).
- The tree is LOCKED while a build's assembler may still be reading it.
- ONE HEAVY BUILD AT A TIME -- verify the process is GONE, not that the log looks done.
- Estimates run 5-9x optimistic. Only the gate's number enters the ledger.
- Killed ideas are replaced until the pool's quota of WORKING ideas is met.

## 2. CONTEXT DISCIPLINE (owner requirement -- as binding as the gate rules)

**The main thread stays clean; nothing learned is lost.** With ~100 ideas, raw logs, greps and
patches would overflow context many times over. The campaign therefore keeps its memory ON
DISK and its reasoning in the thread.

### 2.1 The four durable artifacts (in scratchpad/12m/)

| file | what it holds | who writes |
|---|---|---|
| `LEDGER.md` | ONE row per idea attempt: id, pool, one-line mechanism, deg deltas, sweep median delta, verdict, commit. Kills included, with the cause. | main thread, immediately after each gate |
| `FINDINGS.md` | Durable knowledge: measured op costs, invariants, traps, "X is not chainable because Y". Anything that changes a FUTURE decision. | main thread + every subagent report |
| `ATLAS.md` | The current pool table (measured sizes per macro region), regenerated at phase boundaries. | Phase 0 and each consolidation |
| `atlas/*.json`, `*.gz` | Raw profiles, censuses, label tables. NEVER read whole into context -- queried by script or subagent. | the tools |

Rule: **if it is worth knowing next week, it goes in a file, not a message.** Rule: **before
opening a new pool, re-read FINDINGS.md** -- it is cheaper than re-deriving.

### 2.2 Delegation rule

Any task that would pull more than ~200 lines into the main thread is DELEGATED. Subagents
read; the main thread reads only their reports. Every subagent prompt carries: the cost model,
the doctrine paragraph, the FINDINGS.md path (read it first), and this required report shape:

    WHAT I DID        - two lines
    THE NUMBERS       - measured values only, with how they were measured
    FUTURE-RELEVANT   - lines to append verbatim to FINDINGS.md (or "none")
    FILES TOUCHED     - paths, or "none"

Main thread appends FUTURE-RELEVANT to FINDINGS.md before continuing. That is the mechanism by
which a subagent's lesson survives its own context being discarded.

### 2.3 Subagent model tiers (use the cheapest that fits)

- **haiku** -- mechanical: grep a census, price a macro by micro-assembly, tail a log and
  report five lines, apply a patch script and report the assertion results, list call sites.
- **sonnet** -- analytical: read a macro family and report its structure/invariants, verify a
  width or aliasing proof, price a pool from a profile, draft a patch script.
- **opus / fork** -- only for design decisions, adversarial review of a risky mechanism, and
  CR-level judgment on a device or stl change.
- Idea-generation panels: sonnet generators + sonnet skeptics, opus only for the synthesis.

### 2.4 Safety rules for parallel agents

- **Subagents NEVER launch builds, sweeps, or anything heavy.** Only the main thread
  orchestrates the gate; two concurrent builds are the repo's classic silent failure.
- Subagents never edit `src/` while a build may be reading it -- they hand back patch scripts,
  the main thread applies them.
- Heavy jobs run DETACHED (PowerShell Start-Process) + a Monitor watch. Background bash tasks
  in this harness have been killed mid-run twice; detached processes survived.

### 2.5 Compaction protocol

The thread is a working set, not an archive. After an idea certifies: write the ledger row,
keep the one-line result, drop the detail. After a compaction, recovery is exactly: read
this plan, then LEDGER.md (tail), then FINDINGS.md, then ATLAS.md -- and continue. Never
re-derive a number that is already in a file.

## 3. Phase 0 -- instruments (before any idea)

- **The atlas**: per-op IP profiles (--bucket-bits 6) on ~8 population-spanning frames of the
  current best binary, plus per-line pricing of EVERY macro region (the section-19 method
  applied to the whole program). Output: ATLAS.md, a ranked target table with measured sizes.
  Re-run at every phase boundary -- structural phases reshape the pools (ts3 proved it).
- **The ritual driver**: ONE script wrapping build -> label-diff freeze check -> deg compare
  vs baseline -> sweep -> (on shape change) tune_round -> ledger row. At strict cadence the
  ritual IS the wall-clock; it must be one command with the numbers printed at the end.
- Existing kit to reuse, not rebuild: popcount_census.py (capture/rank/rank-values/predict/
  simulate-shift), tune_round.py, frame_costs.py, gen_chains.py + the chain smokes,
  ca2_profile.py, ca2_sweep.py, deg_with_stl.py.

## 4. The pools and their quotas (>=10 WORKING ideas each; kills replaced)

**P1 -- the width doctrine sweep** (-1.5..-2.5M; highest-confidence family we own).
Every register in frame_render/projection/stream_render gets a bound (emit assert or
construction proof) and every op on it narrows. Known entries: the hex.cmp pool (~1.1M),
project_thing and trb widths, wedge quotients, stream emit registers, sga/scale movs, the
remaining 8-wide ops in the pass-2 column loop. ts3 (-386k from ONE datapath) is the model.

**P2 -- the deref and arm protocol** (-0.8..-1.5M).
The second-arm apparatus: doom-local to_flip2/to_jump2/shadow2 + a dance-only read/write clone
against the SHARED stl decoder table, with an R9 negative control written BEFORE first use.
Then: arm-carried +1 walks for drawn[] in both passes, the 4-byte piece-write run in
ts_piece_wr, sfslot and sprite-slot walks, and the sfflag-into-drawn fold (kills a read and a
pointer per column in two passes; selfreset BYTE_ARRAY_NAMES and both restore sets move with it).

**P3 -- multiplies and division** (-0.8..-1.5M).
fixed_mul rows (~1.7M): ROW-RULE pruning by proven operand nibble-bounds, site by site; more
per-column products converted to DDAs wherever a linear walk exists; wall_scale_setup's divide
(~470k): the 1-column sliver special case (scalestep = diff), a narrower quotient ladder, sga
clamp movs at width 6.

**P4 -- geometry and the walk** (-0.6..-1.2M).
Axis-aligned BSP nodes inlined at bake time (61% of E1M1 nodes -- sign tests instead of the
point_on_side fcall trio); wedge_reject narrowing; project_thing widths and chain follow-ups;
the call protocol itself (stl.fcall is ~2.5w@; a lighter doom-local call/ret for the hot
leaves, plus hot-ret placement from the census).

**P5 -- the emit path** (-0.4..-1.2M; range widened by constraint 2).
Doom side: the V4 signature ladder short-circuited by dirty flags (the ldirty/sdirty pattern
generalized), emit call-site batching, cheaper run construction before the device boundary.
Device side: changes that make InMemoryScreen SIMPLER or equally stupid while cutting doom-side
work -- e.g. a wider count field that removes a doom-side split, or deleting a special case
doom must currently feed. Each such change: fj test + CR into 1.5.1 + oracle mirror + doom, one
commit, one-sentence device description.

**P6 -- stores, slots, loaders round 2** (-0.4..-0.8M).
ts_piece_store's remaining ~1M (deferred flag write-back, the P2 write-run applied, sentinel
path narrowing); the load2/spr_load if_flags dispatch rewrite (packed-count tables); the pass-2
claim path.

**P7 -- zero/init deletions + recurring placement** (-0.3..-0.6M).
The hex.zero remainder (zero-before-overwrite wave 2, read0-style elisions program-wide);
tune_round after every shape change plus a standalone round per phase boundary.

**P8 -- second-order rounds to close the gap.**
Re-attribute after P1-P7 (the pools WILL have reshaped) and give the largest surviving pool a
dedicated round like section 19's, repeated until the median is below 12,000,000. Reserve
unlocks: leaf class-splitting by seg shape (bake-time specialization), the present/init path,
doom-local variants of stl-internal dances (div/mul internals), and the sprite bank walk.

## 5. Cadence and consolidation

- Ideas ship one at a time; each commit carries its gate numbers.
- CONSOLIDATION at every phase boundary: `pytest tests/host -q`, the steps=False lines test,
  full `tests/fj`, `m5_gate --smoke` (full m5_gate at campaign end), restore-set re-keys for
  everything parked (p2_ldirty/p2_sdirty and whatever P2 adds), a handoff section, ATLAS.md
  regenerated, and the fj-repo promotion review for any general macro or device change.

## 6. Honest arithmetic and the wall protocol

Targets sum to -4.8..-9.3M against a needed -7.0M. 12M lands only if P1+P2 hit near their tops
AND P8 harvests the reshaped pools; constraint 2's device latitude widens P5 and improves the
odds. If, after P8's first pass, the atlas shows the remaining certified-idea pool cannot
bridge the gap, REPORT the wall with the numbers and the named blocked unlocks -- with options,
not a silent stop. Machine time at strict cadence: roughly 60-80 gate hours across sessions.

---

## 7. THE KICKOFF PROMPT for the session that picks this up

Paste this as the first message of the new session:

    Read docs/handoff-12m-campaign.md -- it is the plan of record for a hard target: the
    260-frame ca2_sweep median below 12,000,000 ops/frame (currently 18,982,338 on branch
    m4-nine-levels, tip acaed54 + the plan commit). Follow its doctrine exactly, especially
    section 2 (context discipline: LEDGER.md / FINDINGS.md / ATLAS.md in scratchpad/12m/,
    delegate anything over ~200 lines, cheapest-model-that-fits for subagents, subagents never
    launch builds) and section 0 (strict per-idea sweeps; the screen device may change only
    while staying "stupid" by the four-part test; doom-local macros first).

    Start with Phase 0: build the atlas (per-op profiles on ~8 population-spanning frames of
    the current best binary + per-line pricing of every macro region -> ATLAS.md) and the
    one-command ritual driver (build -> label-diff freeze check -> deg compare -> sweep ->
    tune_round on shape change -> ledger row). Re-read scratchpad/12m/FINDINGS.md before
    generating any idea -- the measured op costs and traps in it are already paid for.

    Then work P1 (the width doctrine sweep) to its quota of 10 WORKING ideas, replacing every
    kill with a new idea, and keep going pool by pool. Report after each certified idea with
    one line; report in full at each phase consolidation.
