# P0 stream S7: the lift design spike (moving floors)

**Status: DESIGN SPIKE, 2026-09-26, branch `gameplay-p0`. No build, no game binary, no fj written.**
It prices plan section 6.5 (lifts 98 and 103, the floor switch on linedef 753 lowering sectors
76, 126 and 129) the way M2 priced doors (`docs/handoff-m5-m2-m3-m4.md` section 3).

**Labels.** MEASURED means a script in `scratchpad/gp/lift/` printed it this session; the command is
given. MEASURED (profiler) means the P0 measurement mission's attributing profiler on blocked27
(`plan-gameplay.md` section 12). UNVERIFIED is a model, a DOOM-source fact with no local copy of
the source, or a number carried from an older doc.

| script | what it does | runtime |
|---|---|---|
| `python scratchpad/gp/lift/lift_budget.py [--fast]` | Rebuilds the emitter's pid registry and viewz classes with the emitter's own rules. **Control:** before projecting anything it reproduces the shipped program's 222 pids, 48 classes, 43,392 half-lists, 9,015 unique bodies and 5,326 pair blocks, all read from `build/generated_doom_e1m1_blocked27/`. It then counts band bodies with the emitter's `_band_pair_lists`. | 214 s fast, 437 s full |
| `python scratchpad/gp/lift/lift_geometry.py` | Crush bounds, lnrow patch flips, trigger lines, things near doors, from the WAD | seconds |
| `python scratchpad/gp/lift/label_sizes.py` | Word sizes of the band bank and of M2's per-state door blocks, from blocked27's label table | ~1 min |

---

## 0. Verdict

- **It is an M2-shaped rung, and it fits the byte.** Lifts at quant 16 plus the floor switch as an
  instant two-state drop come to **243 of 255 plane ids** (MEASURED projection: 222 + 21, with 12
  spare).
  - The cost is +5 viewz classes, +8,892 band ids and +689 band bodies (+7.6%). The band table's
    pad stays at 65,536.
  - Size is **~0.18% of 2^27, about 241K words**, plus ~16K for the mover tics (MEASURED unit costs x
    MEASURED counts).
  - Ops are **+0.02 .. +0.1M on the binding metric** (UNVERIFIED; section 1.4 bounds it).
- **An animated floor switch does not fit.**
  - At quant 32 it needs 259 pids; at quant 16 it needs 274, and sector 129 then has 18 states,
    two more than the state nibble holds.
  - The only way to fit it today is `PID_NIBBLES` = 4, which cost +6.74% of the median frame when
    it was measured (UNVERIFIED on blocked27). Do not spend that on a one-shot switch.
- **Lifts can never crush a thing on E1M1** (MEASURED), so lifts need no reversal logic.
  - Doors do need it: all 13 are types that go back up when blocked.
  - The design is a per-door occupancy count kept from the collision check the mover already runs,
    so the per-frame cost is near zero.
- **Four of the five floor sites were never runtime.** Doors move ceilings, and the door machinery
  never had to touch the eye height, thing z, the collision seed floor or the line openings for
  height. What carries over from M2 unchanged is the SHAPE: a persisted state nibble per mover,
  per-state constant blocks behind a per-seg one-nibble switch, and bits patched into `lnrow`.
- **Two gaps this spike found, which apply to doors too:**
  - The `lnrow` bits that M2 patches live outside the restore set, so the restart block (P7) must
    drive them back.
  - P1's collision cells must patch the same bits.

---

## 1. The five baked floor sites

Per mover (MEASURED, `lift_budget.py`):

| sector | leaves | own segs | segs looking at it | lines |
|---|---|---|---|---|
| 98 (lift) | 1 | 4 | 4 | 4: 593-596 |
| 103 (lift) | 1 | 4 | 4 | 4: 618, 620, 1075, 1078 |
| 76 (switch) | 4 | 16 | 16 | 16: 730-745 |
| 126 (switch) | 2 | 8 | 8 | 8 |
| 129 (switch) | 1 | 4 | 2 | 4 |

- **9 mover leaves in total.**
- **No seg has a door or another mover on its other side**, so every seg still needs only ONE state
  nibble. That is the assumption `_seg_door` asserts for doors, and it holds here.

The ops unit costs below are MEASURED (profiler, blocked27): `hex.set` 28, `hex.mov` 56, `hex.scmp`
249, a D4 table read (`finesine.read_sin`) 239, `stl.fcall` 25. There are 2.4 collision position
checks per frame, and the 13 idle door tics cost 1,516 ops together.

**Summary** (ops are UNVERIFIED models built on those MEASURED units):

| site | runtime form for the movers | ops per frame | ops per affected leaf/visit | oracle |
|---|---|---|---|---|
| 1 eye viewz + vzcbase | state-nibble table read in the 9 mover leaves' landing; +5 viewz classes | +0.2-0.4K while the eye is on a mover, else 0 | same | none |
| 2 `ss_flr` | state-nibble table read in the 9 leaves' actions | 0 to ~2K | ~+0.2K per mover-leaf visit | none |
| 3 collision seed | state-nibble read in the `cs` landing | <= ~0.5K near a mover | ~+0.2K per try landing there | none |
| 4 faces / floorfix / pid | the door machinery generalised: 190 per-state block units behind per-seg switches | ~0.02-0.1M on the binding metric (the dominant term) | 1.6-4.8K per lift-leaf visit, 10-29K for sector 76 | none |
| 5 `lnrow` openbottom | per-transition bit flips into the table | 0 | <= 80 raw ops per mover step | none; exhaustive host test |
| tics | `mover_tic` x 5 | ~0.6K idle (5 x the MEASURED 117 per door tic) | +1-2K per step | `mover_tic` SSOT |

### 1.1 Eye height and band class (`_lines_descend_leaf`)

- **Where.**
  - Emitter: the landing action of the eye's descend-only pre-walk (`_bsp_descend_code(..., done_label="dsc_done")`,
    emitted into part 04).
  - It bakes `viewz` and `vzcbase` (the viewz class times `n_bank_keys` x 2 - 4) per leaf.
  - fj: `viewz` feeds every projection, e.g. `frame.ts_step_faces`; `vzcbase` is added in
    `frame.lines_pid_ids*` to reach the band-list ids.
- **Runtime.**
  - In the 9 mover leaves, the two constant sets become one lookup on the mover's state nibble: a
    16-entry table giving (viewz, vzcbase).
  - The landing runs in the descend walk, not inside a band handler, so a table dispatch there is
    legal (R42). If the per-seg switch is used instead, its targets must be `xor_by` onto zeroed
    cells, never `hex.set`.
  - Every mover state a player can stand in (gap >= 56) needs its own viewz class:
    - +5 classes (lifts q16, switch instant) and +3 (lifts q32), MEASURED;
    - each new class costs 4 x pids band ids.
- **Ops.** About +0.2..0.4K per frame, only while the eye is in a mover leaf (two table reads at
  ~0.24K each, MEASURED unit). Zero otherwise.
- **Oracle.** None. `render_wall_frame` takes viewz from `scene_sectors(scene)`, and
  `apply_sector_heights` already moves floors.
- **A visible edge, inherited (UNVERIFIED on screen).** The eye takes its height from its LEAF's
  floor, while collision takes the max of touched floors.
  - Sector 129 is a 64x16 slot. Lowered to 8, it sits between floors at 136, so the player crosses
    it supported at 136 while the eye drops to 8+41 for a frame.
  - Both mirrors agree, so this is a picture issue, not a divergence.

### 1.2 `ss_flr`, the thing z (`subsector_action`)

- **Where.**
  - Emitter: `hex.set 4, ss_flr, <leaf floor>` before `stl.fcall thing_pass_leaf`.
  - fj: `sim.thing_load` (`hex.mov 4, zt, ss_flr`, then `sp_z`).
- **Runtime.** In the 9 mover leaves, the same state-nibble lookup replaces the set.
  - No baked thing stands in a mover (or door) sector at spawn (MEASURED, `lift_geometry.py`), so
    no baked `sp_z` block has to become runtime.
- **Ops.** About +0.2K per visit of a mover leaf; at most 9 visits a frame, and 0 when none is in
  view.
- **Oracle.** None: thing z comes from the overridden sectors.
- **Also, for P3.** A monster's own floor cell must follow a lift it stands on (DOOM's
  P_ChangeSector / P_ThingHeightClip). Refresh it on each mover step for the things in contact with
  the mover (section 4).

### 1.3 The collision seed floor (`_collide_descend`)

- **Where.**
  - Emitter: the tag-`cs` descend's landing, which bakes `cp_seedf`/`cp_seedc` from `_dsecs_open`.
  - fj: `sim.check_position` (`hex.mov 8, cp_floor, cp_seedf`); `sim.try_move`'s step test reads
    the result.
- **Runtime.** In mover leaves, the seed floor comes from the state (sign-extended to 8 nibbles).
  - The door shortcut does NOT carry over. A door seeds from its OPEN map because its line bit
    decides passability; a lift's floor decides the step test at every height.
  - In P1 the seed comes from the cell grid's point location, with the same substitution.
- **Ops.** About +0.2K per try whose candidate lands in a mover leaf, so <= 0.5K a frame near a
  mover.
- **Oracle.** None: `check_position` reads `scene_sectors`.

### 1.4 The step faces `seg_lh1`/`seg_lh2`, plus `floorfix` and `seg_pid`

- **Where.**
  - Emitter: `_face_fields` (the lh fields), `rfields` (`floorfix`) and the attrib block
    (`seg_pid`). All three are already built per sector list `sv` and routed through `_door_blocks`.
  - fj: `frame.ts_step_faces` (`hex.mov 4, tsf_wtl1, seg_lh1`), `frame.seg_pass2_leaf_body_lines`
    (`floorfix`), `frame.lines_pid_ids` (pid).
- **Runtime.** Generalize `_dst_tbl` / `_seg_door` / `_seg_secs` from "door" to "mover". A mover is
  a sector whose floor, or whose ceiling for a door, has states. Nothing downstream changes, because
  every field builder already takes `sv`.
  - MEASURED: **190 block units** (render 54, attrib 68, face 68).
  - Blocks: 636 (lifts q16, switch instant) to 1,964 (all animated).
  - Every floor-switch seg that is closed in some state is closed in exactly state 0. So the
    existing `_seg_dual` one-op gate (`hex.if0 1, <state>`) applies unchanged.
- **Ops.** A mover seg's block is SET and CLEARed through the switch, two dispatches per block kind
  per visit, instead of two direct `fcall`s.
  - UNVERIFIED: ~0.1-0.3K extra per block kind per visit. The one number that would pin it (the
    switch dispatch) is experiment E4.
  - Worst leaf, a full visit of sector 76: 16 segs x 3 kinds x 2 = 96 dispatches, about 10-29K.
  - Bound: M2's 189 door units cost +0.46% of the whole frame in their day (UNVERIFIED, from the M2
    notes). The movers have 190 units, but they are in view far less often than 13 doors spread
    over the level.
  - **A two-state mover (the instant switch) needs no 16-entry switch.** A one-op state gate with
    direct `fcall`s, as `_seg_dual` already does, removes most of that overhead for 54 of the 190
    units.
- **Oracle.** None.

### 1.5 `lnrow`'s openbottom (`collision.line_rows`)

- **Where.**
  - Emitter: `collision_tables_fj(..., secs_open=_dsecs_open)` gives `line_rows`, which bakes
    `openbottom = max(front floor, back floor)` for every non-door line from the STORED map.
  - fj: `sim.check_line` (`.sext16 cl_open, cl_rest + 24*dw`, then `cp_floor = max`).
- **Runtime.** M2-R4's trick, generalized.
  - `lnrow` is a read-only packed table outside the restore set, so a raw bit flip into it
    survives frames.
  - Each mover state step runs a baked per-transition sequence that XORs (row k ^ row k+1) into the
    openbottom bytes of that mover's lines. `opentop` never changes for a floor mover.
  - MEASURED flips per step (quant 16): 98 <= 12, 103 <= 8, 76 <= 80, 126 <= 40, 129 <= 10.
- **Ops.** Zero on the hot path; <= ~80 raw ops per mover step.
- **Oracle.** None: openings come from `scene_sectors`. A host test must still prove that the
  patched rows equal `line_rows(state k)` for every k (exhaustive, seconds).
- **Found here, and it applies to doors too:** these bits are STATE that no restore set or persist
  schema names.
  - M2's `FLAG_BLOCKING` bits are the same.
  - The restart block (P7) must drive both back to state 0. The simplest way is a per-mover
    dispatch on its current state into a baked "row k ^ row 0" flip block.
  - P1's collision cells carry baked line constants, so they must take the same patches. A mover
    line can never get a static "no line blocks" verdict.

### 1.6 The unions

The floor-switch sectors are CLOSED at spawn (floor == ceil). So `thing_live_subsectors`, the walk
prune and the bbox gate all treat them as uninhabitable. Their lowered state must join
`_dsecs_open`, exactly as the open doors did (M2 trap 1: structural decisions are unions over
states). `_seg_marks` and `_seg_piece_modes` already OR over `_seg_secs`, so they need no change.

---

## 2. The plane-id budget

| configuration | states | pids (of 255) | viewz classes | band ids (pad) | seg blocks | words |
|---|---|---|---|---|---|---|
| today (control) | - | **222** | 48 | 43,392 (65,536) | - | - |
| **lifts q16, switch instant** | 10/10/2/2/2 | **243 (+21)** | 53 | 52,284 (65,536) | 636 | **241K (0.18%)** |
| lifts q32, switch instant | 6/6/2/2/2 | 235 (+13) | 51 | 48,708 (65,536) | 508 | 179K (0.13%) |
| lifts q16, switch q32 | 10/10/6/6/10 | **259, over** | 53 | 55,676 (65,536) | 1,324 | 328K (0.25%) |
| lifts q16, switch q16 | 10/10/10/9/**18** | **274, over** | 54 | 59,952 (65,536) | 1,964 | 423K (0.32%) |

New band bodies and pair blocks, in the same row order: +689 / +117, +485 / +77, +770 / +118,
+868 / +131.

- **Source:** all MEASURED by `lift_budget.py`, whose control reproduces the shipped 222 / 48 /
  43,392 / 9,015.
- **Words** are MEASURED unit costs from `label_sizes.py` times MEASURED counts:
  - 8.0 words per band id;
  - 44.0 per unique band body;
  - 336 per new pair block;
  - 81.8 per state block;
  - 253 per switch.
- **Not included:**
  - the mover tics: ~3K words each, from the 13 door tics' 39,654 words, MEASURED;
  - the patch sequences (<1K words).

**Why a mover costs a pid per stop.** A pid is the sector's (ceiling key, floor key) pair. Every
stop of a moving floor is a new pair, and no mover stop coincides with an existing one: the counts
above are exact deltas, not estimates.

**If it does not fit:**
1. **Wider pid.** `PID_NIBBLES=4` is built and gated (2026-09-01), but it cost +6.74% of the median
   and +6.05% of the mean on the 260-frame sweep (UNVERIFIED, `docs/handoff-m4-nine-levels.md`).
   At today's scale that is roughly 1.1-1.3M ops/frame, which is not affordable under the 22M cap.
   Width 3 has never been built.
2. **Sharing.** None is available among mover stops. A possible reclaim: V5 registers a back pair
   for EVERY two-sided walk seg, "a superset of the face-carrying ones". Pids that exist only as
   back pairs of face-less segs are free to reclaim; count them in experiment E6.
3. **Fewer stops.** Lifts at quant 32 need 235 pids, and the switch can be instant.
4. **Coarser doors.** Door quant 24 frees 26 pids (M2 table: 94 -> 68), at the price of the doors'
   smoothness.

**Recommended: lifts q16, switch instant.**

---

## 3. DOOM's lift behaviour, mapped to frames

**DOOM** (`p_plats.c`, `p_floor.c`, `p_spec.c`). These are UNVERIFIED: there is no DOOM source in
the repo.
- **88 (WR) and 62 (SR)** are both "Plat Down-Wait-Up-Stay" (`EV_DoPlat`, `downWaitUpStay`):
  - speed is PLATSPEED x 4 = 4 units per tic;
  - `low` = the lowest surrounding floor (never above its own); `high` = its own floor;
  - the wait is 35 x PLATWAIT = 105 tics;
  - the cycle is down, wait, up, then the plat is removed and stays up;
  - an active plat ignores new triggers (the `specialdata` check);
  - rising into a thing that does not fit sends it back down to wait again.
- **Who triggers.** Monsters trigger 88 (it is on `P_CrossSpecialLine`'s non-player list: 39, 97,
  125, 126, 4, 10, 88). Only the player uses 62.
  - A crossing is "the centre changed side of a special line the box touched at the new position"
    (`spechit`). Both directions trigger, with no side test.
- **23 (S1), Floor Lower to Lowest.** FLOORSPEED is 1 unit per tic; it goes down to the lowest
  surrounding floor once and stays.

**E1M1** (MEASURED, `lift_geometry.py`):
- Lift 98's own boundary lines 593, 595 and 596 are WR 88, and 594 is SR 62, so stepping on from
  three sides lowers it.
- Lift 103 has 618 and 1078 as WR 88, and 620, 1075 and 1064 as SR 62.
- Every trigger line is axis-aligned, so a side test is one compare.
- Travel is 136 units (98, 12 to -124) and 128 units (103, 136 to 8).

**Frames (decision D-L1):**

| option | down | wait | up | total |
|---|---|---|---|---|
| **(a) door-style frame tuning** (plan 2: "doors and lifts keep their frame tuning") | 9 frames (one 16-unit stop per frame, SPEED 1) | 26 frames (a proposal: 37 x 105/150, DOOM's lift/door wait ratio) | 9 frames | 44 frames |
| (b) DOOM tics, like the monsters | 34 frames (4 units/frame, one stop every 4 frames: SPEED 4, choppy) | 105 frames | 34 frames | 173 frames, 13-16 s at 75-90 ms |

- The floor switch is instant (two states; decision D-L2).
- **State.** `mover_tic` goes in the SSOT module next to `door_tic`, with cells
  `mstate`/`mdir`/`msub`/`mwait`. `mwait` needs 2 nibbles for either option.
  - All of it persists (a `MOVER_PERSIST` beside `DOOR_PERSIST`).
  - Everything else is DERIVED from `mstate` by dispatch, so no extra cell joins the schema.
- **Triggers.**
  - Use: the proximity box around the switch lines, the doors' idiom and approximation.
  - Walk-over: per accepted move, for each trigger line in the move's candidate list, compare the
    side before and after (~0.5K per line near a lift, ~0 elsewhere).
  - The monster half lands with P3's moves; the rule and its host test land here.

---

## 4. Reversal on things (P_ChangeSector)

**Rule** (DOOM, UNVERIFIED as source):
- **Doors.** A closing door reverses (goes back up) when its next step would leave less than a
  shootable thing's height between the ceiling and that thing's floorz. The ceiling does not move on
  the tic it reverses.
  - This holds for normal, blue-key and blazing-raise doors, which covers all 13 on E1M1 (specials
    1, 26 and 117). Only "close" and "blazeClose" types stall instead, and E1M1 has none.
  - What counts is shootable things: the player, monsters and barrels. No barrel can touch a door
    line (MEASURED).
  - A corpse under a closing door turns into gibs (height 0, not solid) and does not stop it. A
    dropped item there is removed. Pickups and decor are ignored.
- **Lifts.** A rising lift reverses on a thing that no longer fits. **This never happens on E1M1.**
  At the top, the smallest ceiling minus the largest floor over every sector a thing on the lift
  can touch is 116 (98) and 128 (103), against the tallest thing's 56 (MEASURED).
  - A lowering floor never refuses a thing, so the switch needs nothing either.
  - Carried things follow the floor: the player through sites 1-3, a monster by refreshing its floor
  cell.

**Design: contact records.**
- A thing is in contact with door d when, at its last ACCEPTED position, its box touched one of d's
  lines or its centre's leaf is in d's sector. Both are by-products of the collision check the move
  already ran (the candidate lines and the seed leaf).
- **One threshold per door is exact on E1M1** (MEASURED, a one-off query of the WAD):
  - every door's only non-blocking neighbours are its rooms, at the door's own floor;
  - its lines to sector 105 (floor 8) are all ML_BLOCKING, and no accepted position can straddle a
    blocking line;
  - so the floorz of a thing in contact is always the door floor, and the reversing step is exactly
    the closing step from `pass_state` to `pass_state - 1`. The door tic already has a branch at that
    step: `doorcode._cross`, which re-arms the blocking bit.
- **Rule:** closing, `dstate == pass_state` and occupancy > 0 means reverse (`ddir = OPENING`), and
  neither the state nor the bit moves. Otherwise step as today.
- Each door keeps one occupancy count, updated when a thing's contact changes. A corpse leaves the
  count when it dies.
- The oracle derives the same thing from positions. Add a `blocked` input to `doors.door_tic` (the
  SSOT both mirrors run).

**Ops (UNVERIFIED, from MEASURED unit costs):**
- ~0.3-0.5K per accepted move (compare the contact, update a count);
- ~0.1K per closing door, and only on its `pass_state` step;
- 0 otherwise.

**Gate:**
- Stand in a doorway as it closes: it reverses on the same frame in both mirrors.
- Negative control: with the test removed, the door seals the player and the gate fails.

---

## 5. The rung plan (P2b)

| sub-rung | content | gate | builds |
|---|---|---|---|
| **L0 host** | `src/doomfj/movers.py` SSOT: the mover table, `mover_tic`, heights for a state vector, the triggers (crossing, use box), the `lnrow` patch deltas, door reversal; oracle wiring through `build_scene(sector_heights=...)` | FAIL-first host tests: the cycle timing; retrigger ignored while active; monsters trigger 88; patched rows == `line_rows(k)` for every k (exhaustive); pid/viewz budget guard (like `test_doors`); the never-crush bound, asserted per map | 0 |
| **L1 render proof** | bake each mover at a non-stored state via the override (M2-R2's move) | byte-exact against the oracle at viewpoints overlooking each mover. A differential gate, because of the standing delta. Proves pids, bands, viewz classes, floorfix, faces, dual segs, liveness | 1-3 on the cheap `render` tier (its build time is UNVERIFIED) |
| **L2 runtime movers** | per-state blocks; the five sites; the unions; `MOVER_PERSIST`; the restart unpatch (doors' bits too); no `@`-local data cells in any new macro (plan section 9) | scripted rides with fj's OWN echoed state compared with the oracle every frame (M2 trap 3); a poke on `mstate` at frame k fails at k+1 | 1 game build |
| **L3 triggers and reversal** | WR/SR/S1 for the player; door reversal for the player; the monster halves are gated in P3 | the `lift` script: ride 98, take 103 to the key area, the switch, a doorway reversal | 1 game build |

**Budgets, declared** (kill at 1.25x attributed):
- ops <= +0.1M on the binding metric;
- size <= +0.35M words (0.26% of 2^27);
- pids <= 243;
- viewz classes <= 53;
- band ids <= 52,284 (the pad stays 65,536).

**The cheapest experiments that retire the risks:**
- **E1, DONE:** the pid, viewz and band fit (`lift_budget.py`, control reproduced).
- **E2, DONE:** no crush on lifts, the patch sizes, trigger geometry, no barrels near doors
  (`lift_geometry.py`).
- **E3 (host, seconds):** exhaustive patched-row equality; `mover_tic` against a DOOM-rule
  reference.
- **E4 (S6 probe, seconds):** the cost of one per-seg state dispatch and of one 16-entry table read.
  These are the only ops units in this doc that nobody has measured.
- **E5 (L1, one cheap build):** the byte-exact bake at three mover states.
- **E6 (seconds):** count the pids that exist only as back pairs of face-less segs. It decides
  whether an animated switch can ever fit without widening the pid.

## 6. Open decisions

- **D-L1:** lift timing: door-style (9 + 26 + 9 frames, recommended by the plan's rule) or DOOM
  tics (34 + 105 + 34).
- **D-L2:** the floor switch instant (243 pids) or animated (quant 32: 259, needs E6 or a wider pid).
- **D-L3:** lift quant 16 (10 states, 243) or 32 (6 states, 235).

**Plan changes this spike asks for (not owner decisions):**
- The persist schema and the restart block (P7) must own the `lnrow` patch bits, doors' and movers'
  alike.
- P1's collision cells must take the same patches.
- Door reversal (the `blocked` input to `door_tic`) lands in P2b's L3 for the player, not only in P3.
