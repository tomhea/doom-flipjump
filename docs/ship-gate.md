# The ship gate: how a new game binary earns the name "shipped"

Written 2026-09-13, after a session that measured every engine lever shut and one program change
that deleted 25% of the frame's ops without making the frame faster. The owner's instruction:
**keep the shipped number in line so it does not get lost, and keep the ideas.** This file is
that. CLAUDE.md points here; `docs/measurement-process.md` is the instrument's protocol;
`docs/handoff-throughput-plan.md` sections 10-15 are the evidence behind every line below.

## 1. The standing number

| what | value | how it was measured |
|---|---|---|
| **the shipped binary** | `build/doom_e1m1_blocked27.fjm`, sha256 `38b09a7331f4f52b` (first 16 hex), built 2026-09-25 from the command in 1b, `.doors.json` stamp beside it | the build of that line IS the verification: byte-identical to the candidate it was measured as (`doom_e1m1_padB.fjm`) |
| **ms/frame, quiet box** | **74.7 ms/frame** (74.4-75.0), against **81.0** (80.7-82.0) for blocked25 in the same run -- **B FASTER, x1.085, all 5 pairs** | `msframe.py --a build/doom_e1m1_blocked25.fjm --b build/doom_e1m1_blocked27.fjm`, 200 frames x 5 reps, pinned to P-core 2, engine `79af8639`, nothing else running (yardstick 3.65 G), pixels identical across arms and reps (`docs/ship-evidence/blocked27_msframe_vs_blocked25.log`) |
| **fj ops/s** | **244 M** (243.8 M; blocked25 245.2 M in the same run) | same run; ops/frame **18,221,696** on msframe's forward-walk script (blocked25 19,855,016): the gain is fewer ops at the same rate |
| **binding metric** (owner spec) | (mean+p80)/2 = **17,665,168 ops/frame -- PASS** (mean 15,200,279; p80 20,130,057) | `gamespeed.py --fjm build/doom_e1m1_padB.fjm` (the same bytes), 2026-09-25; `--validate`: 10/10 distinct end cells, widest spread 1321 units, worst run 29% blocked (`docs/ship-evidence/padB_gamespeed.log`) |
| **size** | **32.23% of 2^27 -- PASS** (43,253,668 words; span 94,704,800) | same run |

**What it is:** blocked25 plus the two doom-side leads of handoff 15's pad census, each measured on
its own and shipped through this gate (section 3): the 91 hot `sparse_` sites block
(HOT_PAD = HOTTER_PAD = 16; x1.072 against blocked25) and the two shift macros block
(SAFE_TABLE_MACROS, which needed tomhea/flipjump#362's literal tables; x1.031 on top, 10x400). The
binary it replaced, blocked25 (sha256 `fc46c28c5f2bbac8`: 82 ms/frame quiet, binding 19,246,013,
32.53%), is kept in `build/` as the comparison arm.

blocked25 read 99-104 ms/frame with a background video render at ~0.3-0.45 core -- under
msframe's busy refusal -- and 84-89 ms with a lighter one (2026-09-13; blocked27 has not been timed
under load). **Absolute ms/frame is a number about
the machine state; only an A/B inside one run is a number about the binary.** The msframe
baseline `shipped` (`scratchpad/12m/msframe_baselines/shipped.json`) is frozen on this binary
(re-frozen 2026-09-25 on a quiet box: 74.7 ms/frame, yardstick 3.63 G -- the stored ms is
informational; `--against shipped` RE-MEASURES both arms live, and the binary hash is what it
checks), so `--against shipped` is the comparison.

## 1b. The build command, and the play command

**The build command of the shipped series** (recovered 2026-09-13 from the session transcript
that built blocked23 and blocked24, 09-11 11:22 and 13:01 -- the two builds before blocked25 in
the same series, with the same counts cache; blocked25's own line, 09-11 18:04, was never logged
and followed the renderer fix of FINDINGS CE):

```
python scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/<name>.labels.tsv.gz -- game --out build/doom_e1m1_<name>.fjm --pool-base 0x60000000 --span-bits 0x9fffffe0 --pin-state-cells --merge-aliases --spread 2 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --counts-cache scratchpad/12m/_counts_game.json.gz
```

`build_labeled.py` wraps `build_blocked.py` with the label spy on (everything after `--` is
`build_blocked.py`'s own arguments; `--labels` is the wrapper's). The label table it writes is
what every profile joins against -- keep it beside the binary. The counts cache is keyed by the
emitter sources; a cache MISS runs the counting assembly first (+25 min) and is the expected case
after any emitter change. Build time ~30 min on a quiet box, ~60 min while anything else holds
memory (the assembler peaks near 9.5 GB; CLAUDE.md rule 1).

Status: **VERIFIED, byte-identical.** A build from exactly this line on 2026-09-13 23:40
(a fresh counting assembly -- the cache signature had changed with
the working copies' line endings -- then the two passes) produced sha256 `fc46c28c5f2bbac8`, the
same bytes as `build/doom_e1m1_blocked25.fjm`. So this is blocked25's build command, and the
blocking pass is deterministic given the source, the knobs and the counts. Its label table is
`scratchpad/12m/atlas/blocked25.labels.tsv.gz` (the byte-identical rebuild's) -- the shipped binary's
map back to its source, which it never had until now; the rebuild itself was deleted as a duplicate.

**blocked27 (2026-09-25/26): VERIFIED byte-identical three times, the last two from a fresh count.**
The line did not change: its two leads live in the program (`config.py`'s pads) and in
`build_blocked.py`'s SAFE_TABLE_MACROS, not in the command.
1. At ffda044 against flipjump 1.5.1 at `73e09c0` (tomhea/flipjump#362 merged), the line HIT the
   counts cache made for padB -- at flipjump `3e53017`, #362's pre-review head; the signature hashes
   doom's sources and the macro list, not flipjump's stl -- and produced sha256 `38b09a7331f4f52b`,
   the bytes of `doom_e1m1_padB.fjm`, the candidate every measurement in section 1 was made on
   (`docs/ship-evidence/blocked27_rebuild.log`).
2. At 18d351d, whose `config.py` comment changed the signature, the same line MISSED the cache,
   ran the counting assembly at `73e09c0` (32,066 groups, 432,164 tables, 2,038 s) and produced
   `38b09a7331f4f52b` again (`docs/ship-evidence/blocked27_rebuild_recount.log`). The recount's
   counts, widths, aliases and width histogram equal the old cache's field for field; only the
   signature moved.
3. That signature (`src=3e1d39d67a047f0e`) was still a property of ONE working copy: the hash is
   over the source files' bytes on disk, and seven of them (doorcode/doors/mapcompiler/
   reference_model.py, frame_render/present/stream_render.fj) were CRLF there, while
   `.gitattributes` (`* text=auto eol=lf`) makes every fresh checkout LF on any OS. With those
   seven rewritten to LF (blob hashes unchanged -- no commit), the working copy signs
   `src=4a533c94ca7093ec`, and at cfa5daa the same line MISSED, recounted (1,998 s) and produced
   `38b09a7331f4f52b` a third time (`docs/ship-evidence/blocked27_rebuild_lf.log`), counts again
   equal field for field. The tracked cache is that LF recount, so the line HITs on a fresh
   checkout. A working copy with CRLF sources signs differently and recounts: harmless (+~34 min),
   and the fix is to make its sources LF, not to re-sign the cache.

Its label table is `scratchpad/12m/atlas/blocked27.labels.tsv.gz`; `padA`/`padB` and the recounts'
duplicates `blocked27r`/`blocked27lf` were deleted.

**The play command** (options verified against `fj --help`: `--run`, `--io pc`, `--flat-max-words N`):

```
fj --run build/doom_e1m1_blocked27.fjm --io pc --flat-max-words 134217728
```

`--run` is not optional (`fj a.fjm` assembles); the flat window must be the full 2^27 words or
the engine runs hybrid/paged. `m2_std_gate` drives this same `PcIO` composition in-process, so a
gate PASS is a statement about the object a person runs.

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
   measurement. `--against shipped` re-measures the frozen binary live, so `--a build/<shipped>.fjm
   --b build/<new>.fjm` is the same measurement; what `--against` adds is the check that arm A IS
   the frozen binary (its hash). Use the explicit form only with the shipped sha256 in the record.
3. **The owner's metric.** `python scratchpad/12m/gamespeed.py --fjm build/<new>.fjm` (both
   targets: (mean+p80)/2 <= 20,000,000 ops/frame, size <= 35%), then a separate `--validate` run
   (it is a mode: 10/10 distinct end cells).
4. **Record it, or it did not happen.** The build's command line, its counts-cache path, its label
   table (`build_labeled.py --labels ...` produces it), its sha256, the ledger row of step 2, and
   the numbers of step 3 -- into section 1 of this file and the commit message. Then
   `msframe.py --a build/<new>.fjm --save-baseline shipped` on a quiet box.

**How blocked27 departed from this order (2026-09-25), stated so it is not copied as the rule.**
Lead A ran step 2 as written (`--against shipped`, yardstick 3.51 G -- at the quiet-box line; it is
lead A's only stand-alone verdict. The combined run measured the binary CONTAINING lead A faster than
blocked25 at yardstick 3.65 G, which does not re-measure lead A's own x1.072). Lead B was measured against lead A's binary with
`--a/--b`, because lead A was the base it was built on and was never frozen. The combined step 2
(`--a blocked25 --b blocked27`; the ledger row carries both sha256s, fc46c28c5f2bbac8 and 38b09a7331f4f52b) ran at 22:43, AFTER the step-4 re-freeze
at 22:40 -- so `shipped` briefly named a binary whose combined verdict was not yet in. The freeze
comes last; the order above is the one to follow.

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

**The stl pad round is closed, pad by pad** (handoff 15, 2026-09-14). The relocated family's pads
(`exact_xor`/`double_`/`triple_exact_xor`) are dead by construction under blocking: the pad is the
slot width the counting pass records, so a wider pad is `declined_too_wide` for every table and
the group's pin with it. The ten pads on macros the pass never relocates were priced per pad by
the wflip-site census (-838 K direct, +338 K shift, -500 K net predicted; -431,322 ops/frame
measured on msframe's walk, binding 18,762,374 and 32.11% -- both better) and then MEASURED IN
TIME on a quiet box: 81.6 -> 83.4 ms/frame, 243 -> 233 M fj/s, slower in every pair, median
0.979 -- NOT SEPARATED by the rule, and the gate's clause for that ships only with a stated
reason, of which there is none (size is already under target). Fewer ops, a lower per-op rate:
ops/frame is half of frame time (13) again; what the padding does to the memory chain is the
hypothesis. They stay reverted; the per-pad TIME question (which of the ten pay in time -- the zero-space `to_flip`
reorder and the two-site `mul.init after_add` first) needs a per-pad timing sweep, not the census.
Two doom-side leads from the same census: the S2 sparse pads at 91 hot sites are
`declined_too_wide` under blocking (945,807 ops/frame inline; plain `hex.mov` there would let
them block), and `hex.shifts.shl/shr_bit_once`, `hex.inc1`, `hex.mul.clear_carry` dispatch inline
through pinned words (1.86 M ops/frame together).

**Both doom-side leads, measured and shipped** (2026-09-25, blocked27; handoff 15.4). The hot sites
block once HOT_PAD = HOTTER_PAD = 16, the plain table's own alignment: -653,225 ops/frame and x1.072
against blocked25 -- fewer ops AND a higher rate. The shift macros block once flipjump writes their
tables out literally (tomhea/flipjump#362: the detector reads only literal `a;b` ops, so adding their
names to SAFE_TABLE_MACROS alone was a measured NO-OP -- the same span, the same .fjm size and the
same 425,236 blocked tables as lead A's build, `docs/ship-evidence/padB_noop_build.log`; its sha256
was not taken):
-970,628 binding ops and x1.031 on top, which took the 10x400 escalation to separate (5x200 had one
tied pair). Together, same session: 81.0 -> 74.7 ms/frame, x1.085. What did NOT carry: `hex.inc1`'s
entry 15 falls through into its carry tail (the detector refuses it, rightly), and
`hex.mul.clear_carry` is a return-address wflip, not a table -- that is the parked pad idea above.

**The reset** (12.7): its restore walk is already in address order; its cost is its own
straight-line code once per frame. Restore fewer cells (a dirty set) is the only lever left there.

## 4. Where the leverage is now, ranked by measured size

1. Ops per frame, by object (10.1): `bind_things` 25% -> per-move rebind; `seg_pass2_leaf` 14.5%;
   `m1_reset` 13.2%; `thing_pass_leaf` 8.6%; `seg_pass1_ts` 7.6%; `seg_pass1` 6.3%; bspcode 5.9%.
   At 74.7 ms and 18.22 M ops (blocked27), one million ops removed is ~4.1 ms/frame -- IF the pins
   survive.
2. Pins/placement of the hottest shared words, measured per build (above).
3. The clock: 3.5-3.7 GHz under this load; a performance plan on wall power is +20-30% for free.
