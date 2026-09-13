# The ship gate: how a new game binary earns the name "shipped"

Written 2026-09-13, after a session that measured every engine lever shut and one program change
that deleted 25% of the frame's ops without making the frame faster. The owner's instruction:
**keep the shipped number in line so it does not get lost, and keep the ideas.** This file is
that. CLAUDE.md points here; `docs/measurement-process.md` is the instrument's protocol;
`docs/handoff-throughput-plan.md` sections 10-14 are the evidence behind every line below.

## 1. The standing number

| what | value | how it was measured |
|---|---|---|
| **the shipped binary** | `build/doom_e1m1_blocked25.fjm`, sha256 `fc46c28c5f2bbac8` (first 16 hex), built 2026-09-11 18:04, `.doors.json` stamp beside it | -- |
| **ms/frame, quiet box** | **82 ms/frame** (81.9-82.2 across three runs) | msframe, 200 frames x 5 reps, pinned to P-core 2, 4-byte-cell engine `b96339f7`, nothing else running (yardstick 3.62 G) |
| **fj ops/s** | **242 M** (241.5-242.4 M) | same runs; ops/frame 19,855,016 on msframe's forward-walk script |
| **binding metric** (owner spec) | (mean+p80)/2 = **19,246,013 ops/frame -- PASS** (mean 16,629,651; p80 21,862,375) | `gamespeed.py --fjm build/doom_e1m1_blocked25.fjm`, 2026-09-13 20:43 (`--validate` not re-run on it that night; it was run on the experiment binary: 10/10 distinct end cells) |
| **size** | **32.53% of 2^27 -- PASS** (43,657,732 words; span 96,009,696) | same run |

The same binary reads 99-104 ms/frame with a background video render at ~0.3-0.45 core -- under
msframe's busy refusal -- and 84-89 ms with a lighter one. **Absolute ms/frame is a number about
the machine state; only an A/B inside one run is a number about the binary.** The msframe
baseline `shipped` (`scratchpad/12m/msframe_baselines/shipped.json`) is frozen on this binary
(re-frozen 2026-09-13 22:51: it stores 89.3 ms because a background render was still on, yardstick
3.55 G -- the stored ms is informational; `--against shipped` RE-MEASURES both arms live, and the
binary hash is what it checks), so `--against shipped` is the comparison.

⚠ Its build command is NOT recorded anywhere (checked: git log, the handoffs, the ledger,
FINDINGS). The recorded reference build is `b26` (`build_blocked.py game --merge-aliases`, default
knobs), the same emitted program placed differently, at 28,962,604 ops/frame and 100 ms/frame.
That gap -- 46% more ops for the same program -- is the placement axis (handoff 13.4). **The next
shipped binary MUST record its command line (section 3).**

## 2. The gate, in order; a failure stops the process

1. **Correctness, byte-exact.** `scratchpad/m2_std_gate.py --fjm <new>` (the full-game play-test:
   menu, 154-frame walk, a door opened and carried across two resets; every game frame byte-exact
   against the oracle) and `scratchpad/m3_gate.py --fjm <new>` (menu and world). `m5_gate.py` is
   NOT a gate for a menu-booting binary -- it never presses Enter and fails vacuously on every
   game-tier binary, changed or not (handoff 14.4). tests/host green.
2. **Speed, by the instrument.** `python scratchpad/12m/msframe.py --a build/<new>.fjm --against
   shipped --note "<what changed>"`. The verdict must be **FASTER**, or NOT SEPARATED with a stated
   reason to ship anyway (size, a feature). **B SLOWER does not ship**, whatever the op count says
   -- 2026-09-13 built three binaries whose op deltas said -25% and whose verdicts said SLOWER.
   Check the yardstick line: if it is below ~3.5 G the box was not quiet and the run is not a
   measurement.
3. **The owner's metric.** `python scratchpad/12m/gamespeed.py --fjm build/<new>.fjm` (both
   targets: (mean+p80)/2 <= 20,000,000 ops/frame, size <= 35%), then a separate `--validate` run
   (it is a mode: 10/10 distinct end cells).
4. **Record it, or it did not happen.** The build's command line, its counts-cache path, its label
   table (`build_labeled.py --labels ...` produces it), its sha256, the ledger row of step 2, and
   the numbers of step 3 -- into section 1 of this file and the commit message. Then
   `msframe.py --a build/<new>.fjm --save-baseline shipped` on a quiet box.

## 3. The ideas to keep (each with the evidence that earned or limited it)

**Measurement -- these are what kept the session honest and they are cheap.**
- `msframe` is the metric; ops/frame is a proxy. Placement moved ops/frame by 46% on one program
  (13.4) and moved the per-op rate by 20% the other way. Judge on ms/frame, inside one run.
- `--selftest` before measuring; a background process under the busy threshold costs 5-20% and
  the yardstick is the tell (13.2).
- Engine A/B: `--env-a/--env-b MSFRAME_FJCORE_PYD=<pyd>` switches the engine per arm;
  `scratchpad/12m/with_engine.py` runs any gate on a candidate `.pyd`; `engine_diff.py` is the
  15-case edge differential with an R9 self-test; `pgo_build.py` builds MSVC PGO for a layout
  experiment. The installed `.pyd` stays the shipped one until the verdict.

**The engine is closed** (12-13): 12 -> 3 branches per op, a fully fall-through PGO layout, the
jump-word hoist (2a, re-tested in the engine: marginally slower), TLB/large pages, the flip store
-- all NOT SEPARATED. The per-op time is the memory chain, and 242 M fj/s is what the game's
83.5%-L1 instruction stream costs on this machine (the sieve's 378 M is 99.4% L1). Do not spend a
session there again without a new mechanism.

**Placement and pins are where ops hide** (13.4, 14.6-14.8). The blocking pass decides, from the
program's table COUNTS, which shared source words are pinned; a pinned word dispatches by a
short index flip, an unpinned one by a whole-address flip. Any change to the counts -- adding or
removing code -- re-rolls those decisions: deleting 25% of executed code cost 6 M ops/frame of
`hex.tables.res/ret` and `hex.mul.ret` chains. After ANY emitter change: profile
(`mkprof3.py T` + `prof3run.py` + `timeobj.py` with the new label table) and read the
`m1_reset`-labelled slice -- it is the wflip-chain area, and a jump there is the signature; then
the flipped-bit histogram of the chains (14.8's script) names the words. A good binary is one
whose hot words came out pinned; the ladder's knobs (`--spread 2 --max-slot-ops 512 --span-bits
0x9fffffe0 --pin-broken --width-buckets --merge-aliases`) were worth ~2 M on the experiment.

**Hot-code alignment** (14.8): `pad 2097152` before the frame's walk code puts the shared leaves at
word 2^22 (bit 2^27), popcount 1. Measured +0.5 M ops/frame better than the same program
unaligned, on the experiment binary only -- a candidate, not a proven win on the shipped program.
`scratchpad/12m/engine_folds/patch_nobind_align.py` is the form.

**Thing binding, for the monster work** (14.9): the per-frame `sim.bind_things` costs ~7.5 M
ops/frame (25% of the frame) to rebuild 75 monsters' per-leaf lists that today never change. It
stays -- monsters will move -- but the rebuild should become PER MOVE (DOOM's
P_SetThingPosition: re-bind only the thing that moved), which costs ops proportional to movement.
Baking the lists (`patch_nobind.py`, `baked_thing_lists` with its reference-model tests) is only
valid for a static world and was reverted for that reason.

**The reset** (12.7): its restore walk is already in address order; its cost is its own
straight-line code once per frame. Restore fewer cells (a dirty set) is the only lever left there.

## 4. Where the leverage is now, ranked by measured size

1. Ops per frame, by object (10.1): `bind_things` 25% -> per-move rebind; `seg_pass2_leaf` 14.5%;
   `m1_reset` 13.2%; `thing_pass_leaf` 8.6%; `seg_pass1_ts` 7.6%; `seg_pass1` 6.3%; bspcode 5.9%.
   At 82 ms and 19.86 M ops, one million ops removed is ~4.1 ms/frame -- IF the pins survive.
2. Pins/placement of the hottest shared words, measured per build (above).
3. The clock: 3.5-3.7 GHz under this load; a performance plan on wall power is +20-30% for free.
