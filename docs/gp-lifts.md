# M7 P2b -- lifts, the floor switch, door reversal (the model; before any build)

The design is `docs/gp-lift-spike.md` with its defaults (handoff D11: D-L1 door-style frames, D-L2 an
instant switch, D-L3 quant 16). This file records what L0 -- the host rung -- settled.

## 1. One module: `doomfj.movers`

- **Lifts 98 and 103** (`lift_sectors`: 98 12 -> -124, 103 136 -> 8; ten stops each at quant 16,
  state 0 the stored top floor). **A lift is the door machine on the floor**: `lift_tic` is
  `doors.door_tic` with the lift's bottom wait (`LIFT_WAIT` = 26, `door_tic`'s new `wait_frames`)
  and a trigger taken only at rest at the top (state 0, idle, no wait -- `sub` is residue there).
  DOOM's active plat ignores triggers; "Down-Wait-Up-Stay" is removed at the top, so the next
  trigger starts a new cycle. MEASURED (tests/host/test_movers.py): 9 frames down (the trigger
  frame steps), the bottom held on the arrival frame and 26 more, 9 up.
- **The floor switch** (23 S1, tag 3): sectors 76, 126, 129 -- pillars stored with floor = ceiling
  -- drop to the lowest surrounding floor (136, 144, **8**: 129 borders sector 101) at once, once.
- **Triggers.** WR 88 (593, 595, 596 for 98; 618, 1078 for 103): `doors.crossed` on an accepted
  move, one segment per LINE, the player's and -- 88 is on P_CrossSpecialLine's non-player list --
  a monster's. SR 62 (594; 620, 1064, 1075) and S1 23 (753): the doors' proximity box around the
  line, on a use PRESS (the exit's usedown edge). A lift trigger is a request for the next mover
  tic (`l_req`, the walk-over doors' convention); the switch fires at once, so the tic's move sees
  the lowered pillars.
- **Heights.** `mover_heights` gives `{sector: (floor, ceil)}` for every mover off its stored
  floor, merged with the doors' in every scene.

## 2. The model

- Cells (group `mover`, phase P2b): `l_state`, `l_dir`, `l_sub`, `l_wait`, `l_req` per lift,
  `f_switch`. NEW GAME's restart resets them with every other field.
- The tic: the door phase, then **the mover phase** (`_movers_phase`), then the player.
- Every consumer of heights takes the movers: the player's collision scene, sight and sound
  (`heights_now`; each mover is a dynamic sector like a door: its own sound node, its lines
  tested at the heights of the moment), the monsters' collision map (`secs_c`), and the floor of
  every live monster standing in a mover's sector when a mover moves (P_ChangeSector).

## 3. Door reversal on things (spike section 4)

`door_tic(..., blocked, pass_at)`: a CLOSING door whose step would take it from `pass_at` (or above)
to below it goes back up instead, without moving that frame, when a shootable thing touches it.
The model's `door_touched`: the player alive, or a live monster, whose box straddles one of the
door's lines (the collision test) or whose centre is in the door sector -- the second half is what
holds doors 10 and 34, 32 units thick, where a centred box's edges lie ON both lines. A blazing
door reverses when its 4-stop stride would cross the pass state. Walk-over doors never close.

## 4. The frozen set: a NEW VERSION

MEASURED (the v3 keys replayed on this model): 10 of 11 runs replay the same poses; **R2-spectre-
corridor crosses lift 103's WR lines from frame 0, and its pose parts at frame 4** (the lift goes
down under the player). No run reverses a door. This is a BEHAVIOUR change: by the freeze rule a
new version, `combat_scenarios_v4.json` -- planned by `--plan --file`, B0 re-measured on it, then
frozen with THE OWNER's approval.

## 5. What is not here yet

The fj side (L1 render proof, L2 runtime movers, L3 triggers and reversal in the binary) and the
gate oracles' mover phase (they mirror the binary, which has no movers until L2).
