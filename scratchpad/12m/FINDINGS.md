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
