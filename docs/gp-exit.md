# M7 P2a.2 -- the exit switch and the "level complete" screen (design, before the build)

The handoff (section 6, P2a): "the exit switch (linedef 407, then a 'level complete' frame, then the
menu)". The model already has the rule (`doomfj.combat`, S3b): P_UseLines for special 11 -- a use
PRESS (DOOM's usedown edge) inside the door-style box around the exit line sets `g_leveldone`, and
from the next tic the world is frozen (`World.tic`: nothing moves). NEW GAME's restart block
returns it to the level start. This rung puts that rule in the binary, and gives the frozen level
its screen.

## 1. The rule, one place

- `doomfj.doors.exit_boxes(lds, verts)`: one box per special-11 line, the line's extent inflated by
  `USE_RANGE` -- the model's `exit_boxes` now calls it (it built them inline).
- The press: use held this tic and not last tic (`p_usedown`, 1 at the level start -- G_PlayerReborn
  -- and after NEW GAME), tested BEFORE the player moves (the model's P_PlayerThink order: use, then
  the move). The box test is the doors' `in_use_box_fixed` on the tic-start position.
- The binary's frame: the menu branch comes BEFORE the tics, so the frame of the press still draws
  the world (the player has moved that tic, as in the model); the next frame is the LEVEL COMPLETE
  screen.

## 2. The screens (`menu_step`, `doomfj.menu`)

`menu_scr` gains a third value, 2 = LEVEL COMPLETE (`LEVEL_DONE_MENU = ["LEVEL COMPLETE", "",
"PRESS ENTER"]`, the last line highlighted). The press sets `mode` 1 and `menu_scr` 2.

| screen | esc | enter | up / down |
|---|---|---|---|
| level complete (scr 2) | the main menu | the main menu | nothing |
| main menu (scr 0) | the world -- FROZEN if the level is done (render only, as the model's frozen tic) | the skill screen | nothing |
| skill screen (scr 1) | as P1.5 | NEW GAME at the skill: the restart block zeroes `lvdone`, sets `pusedn` | as P1.5 |

So a finished level is left only through NEW GAME, and nothing else in the menu changes: the esc
from the main menu into a frozen world is the model's own behaviour (a frozen tic draws the world
where it stopped).

## 3. The fj side

- Two persisted cells (build.STANDALONE_PERSIST): `lvdone` (the model's `g_leveldone`) and
  `pusedn` (`p_usedown`, baked 1). The restart zeroes `lvdone` and sets `pusedn` 1.
- The tic: `lvdone` set -> skip the door tic and the player tic (the frame renders the frozen
  world); else, after the doors, before the player's move: the exit test (`exit_lines`): use held ->
  if `pusedn` clear, set it and test the box -> hit: `lvdone` 1, `mode` 1, `menu_scr` 2; use not held
  -> `pusedn` 0.
- The menu: the scr-2 frame (one more baked frame, ~1.2K bytes) and its two transitions.

## 4. Gates

- `m3_gate`, `m2_std_gate` byte- and state-exact, the new cells (`lvdone`, `pusedn`) read by the
  probe (a third optional label group) and predicted by the oracles (`pusedn` = use held after every
  world tic; `lvdone` 0: neither gate reaches the exit).
- `p2a_gate.py` S8: from inside the exit box, use held from frame 0 (the baked `pusedn` 1: NOT a
  press -- control: an oracle without the edge exits), released, pressed -> the world frame, then
  LEVEL COMPLETE; frozen frames under movement keys; enter -> the main menu; esc -> the frozen world
  (the pose does not move under forward -- control: an oracle whose world is not frozen); enter,
  enter, enter (the world -> the main menu -> the skill screen -> NEW GAME) -> NEW GAME at the boot skill: the level start (control: a restart that forgets `lvdone`).
  Byte- and state-exact every frame.
- B0 on set v3 pixel- and state-exact (no v3 run uses the exit: its criteria say so, "no run uses
  the exit").

## 5. Budget

~+0 ops on v3 (one nibble test for `lvdone`, the use edge and one box test on a use press per
frame: ~30 ops); size +~1.3K words (the screen). No plane ids.
**Measured** (blocked35, `docs/gp-ledger.md`): size +51,228 words, the rung's own code -- the
estimate counted the screen's bytes as words (1,379 `stl.output_char` x 8 ops x 2 words = 22,064).
