# The aim window: the player's hitscan, recorded by the walk

**Status: PHASE 0 DESIGN NOTE for P4** (plan-gameplay section 16 lists it as "the aim-window design
note"). D3 is decided: a + c + d + e, with b only for projectiles and barrels (plan section 11,
c116309). Only this note was added: no tracked file changed, nothing was built, and the game was
not run. Every number is MEASURED, with its command in section 7, or UNVERIFIED. The scripts are
in `scratchpad/gp/aim/`.

---

## 0. The answer

- **The window records radius boxes, not sprite pixels.** Each column 72..88 is one cell. A cell
  holds the nearest shootable living thing whose box covers that column. 72..88 is DOOM's full
  pellet spread at 160 wide.
  - A thing writes when the walk visits its leaf. It writes only the columns that no solid wall
    has drawn yet.
  - It writes before the soft budgets decide whether it is drawn (D3 e), so a degraded-out
    monster can still be shot.
  - The next tic's weapon reads the window.
- **It agrees with the model's geometric aim almost everywhere.** The test set is the S4 combat
  set plus the six staged fights: 2,198 frames, 1,705 of them with a target.
  - Column 80 differs in **1 frame (0.06%)**.
  - All 17 columns: **33 of 28,985 column-frames (0.11%)** differ.
  - The picture rule S5 measured differs on the same frames in 22.05% (column 80) and 24.34%
    (all columns).
  - All 33 residuals are one kind: a thing at a wall edge. Its column was open, but 2D sight to
    its CENTRE is blocked. A DOOM-style 2D trace hits the window's target in all 33, at one or
    more of the spread angles that land in that column. So the residual comes from the geometric
    aim's centre-sight shortcut, not from the window.
- **Against DOOM itself, the box is the weak part, and a free change halves the gap.**
  - DOOM's hitscan crosses a thing's corner-to-corner diagonal. Across the ray, that diagonal is
    r..1.41r wide, depending on the view angle.
  - A 2D DOOM trace disagrees with the +-r box on 9.23% of pistol shots and 13.28% of pellets.
  - With r_eff = r * (|sin v| + |cos v|), recomputed per frame, the disagreement falls to 5.14%
    and 7.36%.
  - Today's picture rule disagrees on 27.82% and 33.90%.
  - No 17-column window can get below 1.62% on pellets: that is DOOM's own answer taken at one
    ray per column.
- **Cost: ~0.05M ops per fight frame, and at most ~0.2M in any frame of the set** (UNVERIFIED:
  MEASURED unit costs x MEASURED per-frame counts). That is ~0.2% of the 22M cap. The pistol's
  read is ~0.1K and a shotgun blast's is ~1.9K.
- **r_eff (section 1.7) was ADOPTED 2026-09-26** (free, and closer to DOOM). It changed the S3b
  model's geometric aim as well, through one shared helper (`combat.CombatMixin.aim_radius`).

## 1. What the window records

**1.1 The cells.**
- `aim_sid[17]`: 2 nibbles each. 0 = empty, 1..53 = 1 + monster slot, 54..75 = 54 + barrel
  index. E1M1 holds 53 monster slots (the union of the skills) and 22 barrels (`World.layout`),
  so 7 bits.
- `aim_tz[17]`: 3 nibbles each. The winner's integer depth, `tz >> 16`, is at most 2048.

**1.2 Who writes.** Only what `CombatMixin.shootable_targets()` lists: live monsters that are
shootable with health > 0, and barrels that are live and not yet exploding. Everything else
carries id 0 and is transparent to the window: corpses (scenery under D3 c), drops, fireballs,
puffs and decorations. DOOM's trace passes through all of them too, because none is MF_SHOOTABLE.

**1.3 When a thing may write.** All of the following must hold:
- the walk reaches its leaf before the full stop (every column wall-drawn);
- `tz >= MINZ`;
- `tz` is within the thing's BASE far bound. In fj that is `sp_tzmax`; in the oracle it is the
  base minimum-height test. The two reject the identical set: the emitter scans for the exact
  boundary (see the far-reject comments in `proj.project_thing` and
  `ReferenceModel.project_thing`). The degraded bound `sp_tzmax2` only stops the drawing.
- `|tx| <= tz << 2`;
- `tz <= 2048 << 16` (MISSILERANGE, measured along the view axis).

Monsters (base minimum height 1) never reach the base bound within 2048 units. A barrel (scenery,
minimum height 3) does, beyond the depth where it would project under 3 px. That barrel is neither
drawn nor aimable.
- The census measured two eligibility rules. "box" ignores the base bound, and "box_draw"
  requires the whole base projection to succeed. Their windows are identical in all 37,366
  column-frames (compared directly).
- The design's rule lies between the two. A nearest-first window is a minimum over its candidate
  set, and that minimum is monotone in the set. So the design's window equals both, frame for
  frame, on this set.

**1.4 The span, with no divide.**
- `P = fixed_mul(tx, xscale)` and `Q = r * xscale`, where `xscale` is the sprite's own reciprocal.
- The box's columns are `x1b = (cxf + P - Q) >> 16` and `x2b = ((cxf + P + Q) >> 16) - 1`.
- This is `aim_geometric`'s formula exactly. `fixed_mul` is `floor(a*b / 2^16) mod 2^32`, and
  `(r<<16) * xscale / 2^16 = r * xscale` is an integer, so
  `fixed_mul(tx -/+ (r<<16), xscale) == P -/+ r*xscale (mod 2^32)` for integer r.
- One `fixed_mul_lo` and one small `mul_lo` replace two `fixed_mul_lo`. The integer parts are
  nibbles 4..7 of the sums, so no shift is needed.

**1.5 Occlusion.** A column is open when `drawn[c] == 0` at the moment the thing's leaf is visited.
- `drawn[c]` is the renderer's own solid-wall closure: one-sided walls, plus closed doors sent down
  the one-sided path. It is the same flag that refuses sprite fragments.
- The walk is front to back, so `drawn[c] == 1` means a solid wall stands nearer along column c.
- Two-sided walls never close a column: steps, ledges and sills (section 4).

**1.6 Two things in one column.** The smaller integer depth wins. On a tie, the earlier arrival
keeps the cell: overwrite only when strictly nearer.
- Measured alternatives, as disagreement with the geometric aim:
  - first arrival wins: 2.87% (column 80) and 1.24% (all columns);
  - D3 (d)'s in-leaf depth order then first arrival ("first_d"): 0.12% and 0.15%;
  - the depth compare: 0.06% and 0.11%.
- The compare costs ~1-2K per fight frame (inside section 3's per-column rows). It also makes the
  window independent of the compositor's in-leaf order, which D3 may yet revise. It stays.
- "first_d" is the measured fallback if P4 wants the bare write-once cell of the S6 probe. That
  cell has no `aim_tz` and no compare.

**1.7 The radius: r, or DOOM's diagonal width -- ADOPTED 2026-09-26** (main session: free, and closer to
DOOM; `combat.CombatMixin.aim_radius`, quantized to the view angle's top 8 bits, integer from the
repo's sine table -- the measurements below used a float r_eff at full angle resolution, so the
quantized version's agreement is UNVERIFIED until re-measured).**
- DOOM's `PIT_AddThingIntercepts` tests the corner-to-corner diagonal chosen by the sign of
  `dx ^ dy`. Across a ray at angle v, that diagonal's half-width is `r * (|sin v| + |cos v|)`:
  r on an axis, 1.41r at 45 degrees.
- Proposal: `r_eff = round(r * (|sin v| + |cos v|))` per frame and per radius class (10, 20, 30).
  It is one lookup on the view angle's top bits into a table built from the repo's sine table.
  - Q becomes `r_eff * xscale`: still one small `mul_lo`, so the cost per thing is unchanged.
  - `aim_geometric` must use the same helper, or model-only runs stop representing the game.
- Measured with r_eff in BOTH aims: column 80 differs in 1 of 1,735 fight frames (0.06%), and all
  columns in 45 of 29,495 column-frames (0.15%). All are the same centre-sight kind.
  - Wider boxes change the model's own shots. One S4 run, R2-barrel-hall, therefore leaves its
    frozen trajectory: its replay control says DIFFERS.
  - Freeze scenario set v2 after this decision.

## 2. The hooks

**2.1 fj.** `frame.thing_record_body` is a shared fcall leaf, and it expands `proj.project_thing`
exactly once. All of the hook lives in that one expansion plus one new shared leaf.
1. **Every thing's loader supplies `sp_sid` and `sp_rad`.**
   - A monster stub writes its id when it is alive and shootable, else 0.
   - A barrel's call site writes its id while its live flag is set.
   - Everything else writes 0.
   - `sp_rad` is the frame's r_eff for the thing's radius class. The stub knows its class at
     emit time, so this is a constant-address move.
2. **The far test splits.** A degraded-out shootable must still reach `xscale`. This is D3 (e):
   ```
       hex.cmp 8, pth_tz, sp_tzmax, deg_test, deg_test, reject   // BASE bound: a stop for all
     deg_test:
       rep(deg,k) hex.if0 1, degfl, past_far
       rep(deg,k) hex.cmp 8, pth_tz, sp_tzmax2, past_far, past_far, deg_out
     deg_out:
       rep(deg,k) hex.if0 2, sp_sid, reject                      // not shootable: as today
       rep(deg,k) hex.set 1, aimonly, 1                          // shootable: aim yes, draw no
   ```
   `sp_tzmax >= sp_tzmax2` (project_thing's own comment), so no sprite decision changes. Only op
   counts move.
3. **After `.scale_recip_div pth_xscale`**, before the sprite's x1:
   `hex.if0 2, sp_sid, aim_skip`, then `stl.fcall` into `frame.aim_record`.
   - The leaf consumes `aimonly`: it clears the flag and returns to `reject` if the flag was set.
   - Non-shootable things pay only the `if0`.
4. **`frame.aim_record`, one shared leaf:**
   - the range test on the high nibbles of tz;
   - the centre stop: `|tx| - (sp_rad<<16) > tz >> 2` returns. `pth_tx_abs` already exists
     for the FOV test.
   - P, Q and the two edges;
   - reject when `x2b < 72` or `x1b > 88`; clamp to lo/hi;
   - set `stop[hi]` by a jump on hi-72, then jump into the unrolled chain at lo-72.
5. **Column block c** (17 of them, all addresses constant):
   ```
       hex.if1 1, drawn(c), next_c                  // closed column: skip
       hex.if0 2, aim_sid(c), write_c               // empty: take it
       hex.cmp 3, tzi, aim_tz(c), write_c, next_c, next_c   // strictly nearer: overwrite
     write_c:
       hex.mov 2, aim_sid(c), sp_sid
       hex.mov 3, aim_tz(c), tzi                    // tzi = nibbles 4..6 of pth_tz, by address
     next_c:
       hex.if1 1, stop(c), done_c                   // done_c clears stop(c) and returns
   ```
6. **Prologue.** Zero `aim_sid[17]` at the start of the BSP walk.
7. **Persistence.** The generated main runs input -> doors -> sim -> walk -> `m1_reset`. So the
   window frame N's walk writes is read by frame N+1's weapon, across the reset.
   - `aim_sid` joins the persisted labels: `AIM_PERSIST`, beside `DOOR_PERSIST`, by the same
     `build` mechanism.
   - `aim_tz` is only read behind a non-empty `aim_sid` that the same walk wrote. So it needs no
     restore; persisting it too saves 51 restored cells, ~2.1K per frame at ~41 each (UNVERIFIED).
     The P4 probe asserts that invariant.
   - The stop bits and `aimonly` are always cleared before the leaf returns.
   - "Seen" (D3 e) needs the same tz/tx/xscale at the same moment. It should sit on this hook.

**2.2 The oracle.** `ReferenceModel.render_wall_frame` gains `aim=None`. It takes an object that
gives each thing's id and radius class and receives the 17 (sid, tzi) cells.
- The cells start as all zero: the fj prologue.
- **Position.** Inside `for t in things_by_ss[...]`, after the full-stop `break`, the
  count-budget `continue` and `sprite_art`. That is fj's order, where the first two precede
  `project_thing`; the art's height feeds the base bound. The count budgets are 255 and never
  bind. The hook comes before any degradation choice of `minh_`.
- **One helper computes tz, tx and xscale for both paths.** It is split out of `project_thing`, so
  the sprite and the box cannot drift apart (CLAUDE.md rule 5).
- **Eligibility, span, `drawn[]` test and depth rule** are exactly as in section 1.
- **The oracle has no centre stop.** If the fj stop ever skipped a box that meets the window, the
  fj/oracle window probe (T5) would fail.
- The hook writes only the window. It changes no pixel in either mirror.

**2.3 What moves.**
- **Pixels: nothing.** deg_gate, m2_std_gate and m3_gate must stay byte-exact.
- **Op counts: they move** (rule 2). The new structure adds the per-thing id test, the split far
  test and the leaf. The P4 commit states the delta per viewpoint.
- **Placement.** A new leaf and new tables re-roll the blocking pass's pins, like any change to
  the table counts (plan 13 #1). P1's pin protection is what makes the ms/frame delta readable.

## 3. Costs

**Unit costs (MEASURED).**

| unit | ops | source |
|---|---|---|
| `fixed_mul_lo 8,4` / `hex.mul_lo 8` | 3,381 / 825 | plan section 3 (blocked27, in game) |
| `hex.cmp` 1 nibble / `hex.scmp 8` | 40 / 249 | plan section 3 |
| aim cell: taken -> skip / write a constant / write a runtime id | 27 / 56 / 62 | S6 `probes/s6/results.json`, pool mode |
| D4 lookup (1-2 nibble index -> 1-4 nibbles) | 47-100 | S6 |
| jump on an index into constant-address stubs (64 / 256 entries) | 68-70 | S6 |
| composed per-site RNG outcome table (`rng_col b`) | 96 | S6 |
| AproxDistance | 999 | S6 |
| M1 reset, per restored cell | ~41 | plan section 3 |

8-nibble add/sub/shift have no in-game measurement. This note assumes ~150-250 each (UNVERIFIED).
The pre-blocking harness gave 795 for `hex.sub 8`; blocking cut the measured primitives 3-7x.

**Per event, and per fight frame** (UNVERIFIED sums). The drivers are MEASURED by the census, as
means over the 1,705 fight frames.

| event | ops each | per fight frame | ops per fight frame |
|---|---|---|---|
| a thing reaches `xscale`: the id test | 27-50 | <= 89.3 (all arrivals) | <= 4.5K |
| a shootable reaches the leaf: fcall, range test, centre stop | ~0.8K | 14.74-19.46 | ~12-16K |
| ... and passes the stop: P, Q, 4 add/sub, clip, 2 jumps | ~6.1K | 4.82 | ~29.4K |
| a covered window column: drawn test + stop test | 55-100 | 20.63 | ~1.5K |
| an open covered column: empty test, then a write (sid + tz) or a depth compare | 27-230 | 20.33 (13.19 writes, 6.96 kept, 0.19 overwritten) | ~2.8K |
| per frame: zero 17 sids, the r_eff lookup | ~1.1K | 1 | ~1.1K |
| **total** | | | **~0.05M** |

- **The worst frame on the set** is bounded by taking each count at its own worst frame: 156
  arrivals, 37 boxed things, 25 passing the stop and 64 visits. That gives ~0.2M.
- **The centre stop never cut a window-overlapping box.** 0 of the 5,109 that meet the window,
  among 28,579 boxed things (MEASURED).
  - It lets 4.82 of 14.74 boxed things per fight frame through to the multiplies, and 2.98 of
    those actually meet the window.
  - A too-tight stop (`tz >> 4`) is the control: it would cut 700 of the 5,109.
- **D3 (e)'s projection of degraded-out monsters.** 1.27 live monsters per fight frame are
  degraded out (S5, MEASURED). They now continue past the far test to tx and xscale: two
  `fixed_mul_lo` in the sparse operand order plus the reciprocal.
  - That is ~5-10K each (UNVERIFIED: a part of the 15.4K MEASURED for project+record of a baked
    sprite), so ~6-13K per fight frame.
  - "Seen" needs the same values, so it is paid once for both. S5 priced (e) at ~11.6K per frame
    (UNVERIFIED).
- **The read side (P4's weapon).**
  - The pistol: an `if0 2` on cell 80, then a jump on the id into the target's stub: ~0.1-0.15K.
  - A pellet: 96 (the composed RNG/column table) + 68 (the jump on the column) + 27-50 (the `if0`)
    + ~70 (the jump on the id), so ~0.27K. A shotgun blast is ~1.9K.
  - Fist and saw add AproxDistance to the target's centre: 999.
- **Size.** One leaf, 17 blocks, two 17-entry jump tables, 85 nibbles of cells and 17 stop bits.
  That is a few thousand words (UNVERIFIED), noise against the 35% target.
- **A P4 trim (optional).** Take P from the sprite's own x1 numerator:
  `N1 = fixed_mul(tx - (L<<16), xscale)`, where L is the sprite frame's left offset (an integer
  by construction: `left << 16` in `project_thing`).
  - Then `P = N1 + L*xscale`, exact by the same identity. One small `mul_lo` replaces a
    `fixed_mul_lo`: ~-2.5K per recorded thing, ~-12K per fight frame (UNVERIFIED).
  - The cost: the hook moves after x1's multiply, and the box reads the sprite frame's data.

## 4. What still differs from DOOM

The census compares the window with a model that shares its box, so it cannot see DOOM.
`aim_vs_doom2d.py` casts DOOM's own 2D hitscan on the same frames:
- DOOM's diagonal choice;
- the nearest crossing within 2048 units along the ray;
- a wall test from the eye to the crossing.

It compares that answer with each rule, in the column the ray lands in.

| rule | column 80: pistol, accurate (of 1,517 frames) | pellets (P_SubRandom-weighted) |
|---|---|---|
| sprite span (the picture rule S5 measured) | 27.82% | 33.90% |
| box with r - 4 (a control) | 18.98% | 24.40% |
| box +-r (= the geometric aim; geometric itself: 9.16%) | 9.23% | 13.28% |
| **box +-r_eff** | **5.14%** | **7.36%** |
| ceiling: DOOM's own answer at one ray per column | 0 by construction | 1.62% |

**What remains, largest first:**
1. **The diagonal's slant.** r_eff fixes the diagonal's width, not its depth.
   - Near an axis, the diagonal's near end sits wider in angle than the box and its far end
     narrower.
   - DOOM also switches diagonals between rays on either side of an axis.
   - Of r_eff's 78 column-80 disagreements:
     - 52: DOOM's ray misses the window's target and hits another;
     - 8: DOOM's ray misses the target and hits nothing;
     - 6: DOOM hits a thing whose box misses column 80.
   - Most of the 78 (54) come from one staged crowd, placed_pistol, on and near an axis-aligned
     view: the player starts facing east, angle 0.
   - The exact fix projects the diagonal's two ends: two more reciprocals per recorded thing,
     ~+0.1M per fight frame (UNVERIFIED). The table bounds the gain at the 1.62% ceiling. Not
     proposed.
2. **Nearest by centre depth vs nearest crossing along the ray.** DOOM hits whichever diagonal the
   ray crosses first. Of r_eff's disagreements, 11 are this. The last 1 is a wall that DOOM's ray
   meets before the crossing.
3. **Column granularity.** A column spans ~30 of P_SubRandom's ray angles, and the window gives
   them one answer: the 1.62% ceiling.
4. **No heights (not measured).**
   - Vertical autoaim is treated as always succeeding.
   - No shot passes over or under a thing.
   - A thing wholly hidden behind a low two-sided wall (a step, ledge or sill) is still hit when
     its column is open.
   - A P4 probe with a height-aware trace prices this.
5. **One target per column.** A pellet into a column whose target died earlier in the same tic
   is absorbed. `damage_monster` ignores the dead, while DOOM's trace goes on to the thing behind.
   This affects overkill only.
6. **Latency.** The window is frame N's picture, which is exactly the tic-start world the model's
   aim sees, with one exception. Doors move before the weapon (the doors phase comes first in the
   model and in fj), so a door that moves on that tic is seen one tic late.
7. **Small differences.**
   - The range is measured along the view axis: +0.5% at the window's edge.
   - Integer-depth ties go to the earlier arrival.
   - A barrel too small to draw cannot be shot.
   - DOOM's blockmap quirk, which can miss a thing whose centre lies in a block the ray does not
     enter, is not reproduced.

## 5. Tests

- **T1 (host, now possible): oracle window vs geometric aim, through the census wiring.**
  - On the combat set and the staged fights, EVERY fight frame must agree at every column, except
    a frozen list of (run, frame, column) residuals. With r there are 33, all of the class
    "centre hidden, column open"; with r_eff there are 45.
  - Compare against the list, not a bound, so any movement is a visible diff.
  - Vacuity: >= 1,400 frames with a geometric target at column 80 (MEASURED 1,468), and nonzero
    writes, overwrites and kept cells (MEASURED 13.19 / 0.19 / 6.96 per fight frame).
- **T2 (R9 negative controls): the same comparison must FAIL on each of these** (MEASURED,
  column 80 / all columns):
  - radius - 4: 13.72% / 12.57%;
  - the sprite span: 22.05% / 24.34%;
  - first arrival without depth: 2.87% / 1.24%;
  - occlusion off (`drawn[]` ignored): 0.41% / 0.87% (7 frames / 251 column-frames).
  - The last control is weak as a rate, because the walk seldom delivers a shootable thing whose
    window columns a wall has already closed. Against T1's frozen list it still differs in at
    least 218 column-frames (251 - 33). That is why T1 compares lists, not rates.
- **T3 (host): the identity.**
  - `fixed_mul(tx -/+ (r<<16), xs) == P -/+ r*xs mod 2^32`, over random and boundary operands.
  - Control: a fractional R must break it.
- **T4 (host): the centre stop is a stop.**
  - Bound the reciprocal's relative error over its whole table. The stop leaves 20 columns of
    margin where 9 are needed, so it survives any error below ~55%.
  - Also require the census count to stay 0.
  - Control: a `tz >> 4` stop must be caught (700 of 5,109 overlapping boxes on the set).
- **T5 (P4, fj vs oracle): a state probe compares the 17 cells after every frame's walk.**
  - Trajectories: the gate trajectories (`m2_std_gate` and `m3_gate` keys) plus a combat script.
  - The byte-exact gates must stay byte-exact; the window touches no pixel.
  - Report the op delta.
  - Vacuity: count the frames with a non-empty cell and with an overwrite.
  - Control: an emitter-side radius mutation (r + 1) must make the probe fail at a frame stated in
    advance. The oracle, mutated the same way, names that frame.
- **T6 (model): `World(aim=window_aim)` replays the set with the renderer in the loop.**
  - Compare its events with the geometric replay's, tic by tic. The first tic where they differ
    must fire a shot through a column in T1's frozen list. After that, the two trajectories may
    part.

## 6. How `aim(world, col)` consumes it

- **Schema.** One new field:
  `f("aim_sid", 7, count=17, group="player", phase="P4", doc="aim window ...")`.
  - It is state, because the next tic reads it. It is persisted in fj (2.1.7).
  - It is not in `RESTART_KEEP`, so a restart clears it. The restart frame's own walk refills
    it before the next tic's weapon reads it.
  - Adding it changes the model digest: freeze scenario set v2 after it lands.
- **The bridge.**
  - Wherever the oracle renders the game frame (the P4 gates render every frame already), pass the
    frame's things with their ids and radius classes.
  - After the render, write the 17 cells into `ws.aim_sid`. Ids: 1 + monster slot, then
    1 + nmon + barrel index.
- **The hook.** `window_aim(world, col)` decodes `ws.aim_sid[col - world.aim_lo]`:
  - 0 -> None;
  - <= nmon -> ("mon", id - 1);
  - otherwise ("bar", id - 1 - nmon).
  - It is passed as `World(aim=window_aim)`.
  - `_line_attack` is unchanged: the reach test for fist and saw (AproxDistance to the target's
    centre) and the damage path stay as S3b wrote them.
- **Order.** The model must keep fj's order: doors, then the weapon (reading the window of the
  previous render), then the move, the monsters and the rest, then the render that writes the next
  window. S3b's tic already runs doors before the player.
- **Model-only runs keep `aim_geometric`** (no renderer, fast) as the default and as T1's
  reference. If r_eff is chosen, both use the same radius helper.

## 7. Evidence (all MEASURED, K = 3, the S4 v1 snapshot; all ten replays EQUALS unless stated)

- `python scratchpad/gp/aim/aim_window_census.py --staged` -> `aim_window_census.txt`.
  - It gives the window rules against `aim_geometric`, the cost drivers and the residual classes.
  - Its "sprite" control reproduces S5's per-run column-80 counts on the five runs S5's aimdiag
    classified: 42, 2, 31, 0, 2 = 77.
- `... aim_window_census.py --staged --reff` -> `aim_window_census_reff.txt`. This is r_eff in
  both aims. R2-barrel-hall's replay DIFFERS, as explained in 1.7.
- `python scratchpad/gp/aim/aim_residual_trace.py` -> `aim_residual_trace.txt`.
  - For the 33 residuals, the DOOM-style 2D trace hits the window's target at every ray of the
    column in 20 and at some rays in 13.
  - Its positive control: in the same three runs, on column-80 frames where both aims agree, the
    trace hits the target in 294 of 345. The misses are the box-vs-diagonal gap of section 4.
- `python scratchpad/gp/aim/aim_vs_doom2d.py --staged` -> `aim_vs_doom2d.txt`. This is section 4's
  table.
  - It replays the census's frames: same keys, same K, and nothing written to the world.
  - Pellets are sampled every 8th spread (64 rays), weighted 256 - |s|.
  - The geometry is float and 2D. It is a classification, not a mirror.
