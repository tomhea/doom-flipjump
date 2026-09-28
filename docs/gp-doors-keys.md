# M7 P2a.1 -- doors and keys (design, before the build)

The handoff's P2a (`docs/handoff-gameplay.md` section 10; scope section 3; decision D11), first
rung: **the blue-key doors, the blue card and its pickup, the blazing door, and the two walk-over
doors.** The exit switch and its "level complete" frame are P2a.2. Class F: pictures move (the two
walk-over doors open; the blue card vanishes when taken). Kill criteria: `docs/gp-ledger.md`.

## 1. E1M1's line specials (MEASURED, `tests/fixtures/freedoom_e1m1.wad`)

| special | DOOM | lines | P2a.1 |
|---|---|---|---|
| 1 | DR door | 20 | as today |
| 26 | DR door, blue card | 421, 423 (sector 71); 520, 522 (sector 51) | **the card check** |
| 117 | DR door, blazing | 1162 (sector 84) | **the blazing speed** |
| 2 | W1 door open-stay | 528, 1002, 1006 (tag 5 -> sector 77); 997, 998, 999 (tag 6 -> sector 145) | **the walk-over doors** |
| 11 | S1 exit | 407 | P2a.2 |
| 23, 62, 88 | floor switch, lifts | | P2b |

**The blue card is not drawn today.** `reference_model.THING_SPRITE` has no entry for type 5
(BKEY), so it has no art, is not in `things.drawable_things` and has no `thvis` slot. P2a.1 maps
5 -> BKEY, frame A only (DOOM blinks it between A and B: a stated deviation, the blink is P3's
animation machinery). The card then joins the drawable list -- every drawable index after it
shifts, so the restore sets re-key -- and, being a VANISHABLE type, it gets a `thvis` slot.
BEFORE THE BUILD: the census on the frozen set v3 must show the card in no run's view; if it moves
F4, the set needs the owner's re-freeze.

The blue card (thing type 5) is at (2192, 576) on sector 35 (floor 136). Within its 36-unit touch
box lies sector 124 (floor 24) behind blocking lines, so the pickup's REACH test (below) decides
real positions: a player standing in 124 cannot take it.

## 2. The model (`src/doomfj/world.py`, `combat.py`) and the gates' oracle

The model already has the card check (`door_cards`, `player_can_open`) and the card's pickup
(`_touch_specials` / `_touch` kind 5, with the reach test). P2a.1 adds, in ONE place each
(`src/doomfj/doors.py`, which both mirrors and every gate oracle call):

- **Blazing**: `door_tic(..., stride=1)`; the blazing door moves `BLAZE_STRIDE = 4` stops a frame
  (DOOM's VDOORSPEED * 4), clamped at both ends; its wait is the same WAIT. The 13 doors keep
  stride 1.
- **Open-stay**: `door_tic(..., stay=False)`; a stay door that reaches the top goes IDLE with no
  wait, and never closes. A use press does nothing to it (it has no use line).
- **Walk-over**: `walkover_triggers(...) -> [(door sector, axis, coord, lo, hi)]`: the W1 lines of
  a tag are collinear and axis-aligned on E1M1 (asserted), so each tag is ONE segment. The trigger
  is `crossed(trigger, old16, new16)`: the player's centre changes side of the axis
  (`P_PointOnLineSide`: a point ON the line counts on the side DOOM gives it) between the tic's
  start and its accepted position, and the new centre is within the segment's extent inflated by
  the player's radius. W1: it fires once (a persisted `fired` bit per trigger), and it opens the
  tagged door, which stays open. DEVIATION from DOOM, stated as for the use box: DOOM triggers on
  the lines in the move's `spechit` set whose side changed; this uses the one segment per tag and
  the centre's side (the two agree on every move that crosses the segment's interior).
- **The two walk-over doors become runtime doors**: sectors 77 and 145, quant 16 like the other
  13 (5 and 8 states). `door_sectors` gains them (a stored-shut sector TAGGED by a W1 line).
  MEASURED plane ids (`scratchpad/gp/p2a/walkover_pids.py`, lift_budget's own registry): 222 today,
  233 with the two doors; with P2b's lifts 254 of 255 (quant 24: 252, quant 32: 249, instant:
  245). Quant 16 fits with 1 to spare; the fallback, if P2b's real count is higher, is quant 24.
- **The card for the gates' oracle**: the render oracle has no pickups today; it takes the blue
  card and hides it (`thing_hidden`) by the model's own rule, and no other item.

## 3. The fj side

- **The door machine** (`doorcode.door_tic_lines`): per door a stride (4 increments for the
  blazing door) and a stay flag (the top transition sets no wait); two more door slots (15 doors).
- **The card check**: the use trigger of doors 51 and 71 also needs `pcard` (one persisted
  nibble): `pressed = use & in_box & pcard` for those two only.
- **The pickup**: after the move, the tried position in the card's 36-unit box AND
  `136 - here_floor` within [-8, 56] (the model's REACH) -> `pcard = 1` and the card's `thvis`
  slot 0 (the slot it gets once it is drawable). Only while the card is untaken.
- **The walk-over triggers**: after an accepted move, per unfired trigger, the side test on the
  axis (a 16.16 compare of old and new) and the extent test (two compares) -> the door's press,
  and `wfired` set.
- **Restart / NEW GAME**: `pcard`, `wfired` and the two new doors return to their level-start
  values; the key's `thvis` returns to visible. The restore sets carry every new cell.

## 4. Gates

- `m2_std_gate` / `m3_gate` as today (byte- and state-exact), the new cells in the probe.
- A new `p2a_gate.py` in their style, runs started by POKING the pose (the probe machinery
  `b0_scenarios` uses), each byte- and state-exact against the oracle frame by frame:
  1. at blue door 71 without the card: use -> the door stays shut (control: the oracle opening it);
  2. onto the card's platform, take it (pcard 1, the card gone), then door 71 with use -> opens;
  3. from sector 124 inside the box: the card is NOT taken (the reach test; control: no reach);
  4. the blazing door 84: opens in 4-stop strides (control: stride 1);
  5. over tag 5's line: door 77 opens and stays open past WAIT (control: a door that closes);
     back over it: nothing (W1 once; control: fire twice);
  6. over tag 6's line: door 145 the same.
- B0 on set v3 pixel- and state-exact (the frozen runs do not reach these lines -- MEASURED before
  the build, or the set's census moves, which would need the owner).

## 5. Budget

+0.02 .. +0.05M ops/frame on v3 (the handoff's +0.05M for all of P2a): the card box (4 compares
while untaken), two trigger tests (3 compares each) per accepted move, two more idle doors (one
nibble test each). Size +~0.1M words (two doors' per-state blocks). Plane ids 233 (MEASURED).
