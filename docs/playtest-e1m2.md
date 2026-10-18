# E1M2 playtest (2026-10-18, on `build/doom_e1m2_r3.fjm`)

The owner asked: "actually play the game -- understand what works and what looks weird and needs changing -- and
afterwards fix those things by yourself". Every frame below came from the **binary** (not the oracle), driven by
`play.py` (session scratchpad: a key log replayed from boot through NEW GAME, the binary's own pose read each frame;
`@goto` / `@gofight` steer closed-loop on the binary's pose; a tester's warp and health/ammo top-up through the probe,
the way B0 injects state). Sessions: medium skill (s2, s4), easy (s3).

## What works, as DOOM does
- Moving, turning (the slow tap then x1.5), strafing; the pickup flash (yellow) and the damage flash (red, deepening
  with damage); picking up a shotgun switches to it, the ammo counter follows the weapon (blank on the fist).
- Monsters: they wake, close in, shoot and claw; **infighting** (zombies and sergeants killing each other in the
  first room while the player never fired); drops (shotguns, clips) and corpses; a barrel blast.
- **The blue card**: S1 switch 34 (special 23) lowers sector 45; the card shows on the lowered floor; walking onto it
  gives the yellow flash and the blue icon in KEYS. **Red** and **yellow** cards likewise (icons yellow / blue / red).
- **Key doors**: the red door (139) and the yellow door (100) open with their cards; a key door refuses without it.
- **Lifts**: SR switch 219 lowers lift 44 (an imp rode it down and attacked), and it rises back.
- **Teleport** (tag 18, line 1215): crossing from its front lands at (1504, -1440) facing east, and the player is
  frozen 18 frames (DOOM's reactiontime) before moving again.
- **The exit** (line 737): a press within 64 units ends the level; LEVEL COMPLETE shows kills 17/93, items 2/64,
  secrets 0/7, time 1:20 (three-digit columns fit); any key returns to the menu.
- A 40-point tour (one reachable spot per 448-unit square, a full turn at each): every area renders sensibly --
  sky, water, torches, trees, computers, corpses, items, spectres (drawn dark, as on E1M1).

## Found, and fixed
- **Blue door 54 could not be passed** (BLOCKER). It opened 12 units over its floor at 136 -- the legacy door rule
  read a one-sided line's missing back as the last sidedef's sector (E1M2: 309, ceiling 152), capping five doors at
  148. Fixed: DOOM's two-sided neighbour rule off the E1M1 family (`doors.door_neighbours`): 54 -> 228, 258 -> 196,
  139 -> 156, 30 / 266 -> 196. E1M1 keeps its shipped stops.

## Looks off, and why it stays (for now)
- **Tall step faces are flat gray slabs** (e.g. lower texture AQMETL13 at (2376, 936)). The renderer has drawn
  steps and lips as one flat tone since E1M1 (the V5 pieces); E1M2 just has much taller ones. Texturing them is a
  large renderer change -- an owner decision, not a fix.
- **Doors open in 2-3 frames** and **the red damage tint lasts ~30 frames**: both run per frame, not per 35 Hz tic,
  as on the shipped E1M1.
- **LEVEL COMPLETE's time** is game time: frames / 20 (the 20 fps cap), not the wall clock.
- The red key door wears a dim orange-red tone at its light level (the P10 tones).

## The owner's decisions on the recorded simplifications (each if <= +0.5% speed)
Being built in parallel: telefrag + teleport fog, switch textures that change when pressed, the scrolling wall
(invisible in the game tier's two-colour wall patterns -- built as a screen-space slide of the pattern on those two
walls), the sector lights (glow / strobe / flicker), and the MAP page (a fixed baked map with a live red dot).
