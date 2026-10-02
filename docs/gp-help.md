# M7 P3.4 -- the key-map HELP screen (design, before the build)

The owner (2026-10-02): "I want this phase 3 to include a key-map help in a 'help screen'." Scope
(option a): the screen lists ONLY the keys that work today; P4 adds strafe, fire and the weapons and
updates it (section 4). The owner's update the same day: the help is reachable from the MAIN MENU as
an item (up / down / enter, like the other items) as well as from the game (h), and E is a second
use key now. Class F: new pictures, the main menu's picture changes. Kill criteria:
`docs/gp-ledger.md`, "P3.4".

## 1. What the player sees

The main menu has two items, NEW GAME and HELP (QUIT went: it was never selectable -- enter always
meant NEW GAME -- and the program has no quit). Up / down (w / s, the arrows) move the highlight
between them, clamped at both ends; enter on NEW GAME opens the skill screen as before, enter on
HELP opens the help; h on either item opens it too.

The help screen, 160x100 like every menu screen, drawn by `doomfj.menu` with the menu's fonts and
colours:

```
            HELP - CONTROLS                    <- the 5x7 font, the highlight colour, centred
  W / UP      MOVE FORWARD                     <- two left-aligned columns in the text colour,
  S / DOWN    MOVE BACK                           the table centred as a block
  A / LEFT    TURN LEFT
  D / RIGHT   TURN RIGHT
  SPACE / E   USE: DOORS,
              SWITCHES, LIFTS                  <- one row would be 45 px too wide
  ENTER       SELECT
  ESC         MENU / BACK   (in the help, Esc closes it)
  H           THIS HELP                         TOMHE.APP  <- the credit, as on every screen
```

Esc or h close it, back to where it was opened from: the main menu (HELP highlighted), or the
world, where it was -- the help frame, like every menu frame, skips the tic, so nothing moves
behind it. The skill screen and LEVEL COMPLETE ignore h. Every key on the screen was checked against
`src/fj/input.fj` -- and the check is a test that RUNS `kb.poll` (section 3).

The keys: the device (flipjump's pygame_window) delivers ASCII and the arrows / shift / ctrl / alt,
no F1 -- so help is 'h' (0x68), a DOWN-edge event like enter and esc. 'e' (0x65) is a second use key:
the same held flag as space.

## 2. The state -- no new persisted cell

`menu_scr` already persists (build.STANDALONE_PERSIST) and is a nibble with three values in use, so
the new states are three more values of it:

| `menu_scr` | screen | esc | enter | h | up / down |
|---|---|---|---|---|---|
| 0 | main menu, NEW GAME highlighted | the world | the skill screen | help (3) | down: 5 |
| 5 | main menu, HELP highlighted | the world | help (3) | help (3) | up: 0 |
| 3 | the help, opened from the menu | main menu on HELP (5) | -- | main menu on HELP (5) | -- |
| 4 | the help, opened from the world | the world | -- | the world | -- |
| 1, 2 | the skill screen, LEVEL COMPLETE | as before | as before | ignored | as before |
| (world, `mode` 0) | | main menu (0) | main menu (0) | help (4) | -- |

The help is ONE picture under two ids because closing it has two destinations; a separate "opened
from" cell would be a new persisted label for the same information. First match wins, in the order
esc, enter, help, up, down. The new event cell `ev_help` is zeroed before each frame's polls with the
other four -- ordinary restore-set residue, like them.

**The two mirrors.** `doomfj.menu.menu_step` (the rules) and `wall_renderer.menu_screen_pixels` (the
picture for a state -- the ONE mapping; m3_gate and p2a_gate each kept their own table until now) are
the oracle; `wall_renderer.menu_state_lines` and `_menu_lines`' producer branch are the program. Both
pictures come from one generator: `menu.help_pixels` / `help_stream` / `help_fj` share the menu's
encoder (`_encode`), fj writer and credit -- the existing screens' streams, fj text and pixels are
byte-identical to before (checked against m7-depth's `menu.py` on the main, skill, clipped and empty
screens).

## 3. What a world frame pays

The poll's decode and one state branch, as the brief required:
- `kb.poll`: on a key event in the 0x6_ row past 'd', two more nibble tests ('e', then 'h'); nothing
  on an idle poll (the status hex 0x0 exits first) or any other key;
- the frame prologue zeroes `ev_help` (one `hex.zero 1`);
- the world's state path, when neither esc nor enter is down, tests `ev_help` (one `hex.if0`) before
  falling out. The producer branch is unchanged for a world frame (its first line jumps to the
  world).

ESTIMATE, from a tiny fj harness (`worldcost.py` in the session scratchpad: the prologue, 8 polls and
the state machine on world frames, m7-depth against this branch, 20 frames): +1.9 ops/frame idle,
+6.5 ops/frame with w / space / a pressed and released -- layout-dependent (an fj flip's cost is the
popcount of its address), and some 10^-6 of a 14M-op frame. Gameplay ops are unchanged within noise;
the rung's binding delta will be placement (`docs/gp-ledger.md`, P2a.2's row for how that reads).

The menu frames themselves: the help stream is 4,770 bytes (text-dense: ~3.5x a menu screen), the
main menu on HELP 1,318, the main menu 1,346 (was 1,364 with QUIT). Size ESTIMATE: 6,068 new stream
bytes x 8 ops x 2 words = 97,088 words, plus the decode and the state lines.

## 4. The owner's target key map (approved 2026-10-02, for P4)

| action | keys | now (P3.4) |
|---|---|---|
| move forward / back | W / S, UP / DOWN | as now |
| turn left / right | LEFT / RIGHT arrows | today also A / D |
| strafe left / right | A / D, and , / . | **P4** -- A / D move from turn to strafe |
| use | SPACE or E | as now (E lands in P3.4) |
| fire | CTRL | **P4** |
| weapons | 1-4 | **P4** |
| menu | ESC / ENTER | as now |
| help | H | as now |

P4 changes `kb.poll` (strafe, fire and the digit keys; A / D re-bound), `menu.HELP_ROWS` and
`HELP_KEYCODES` with it -- `tests/fj/test_keyboard_input.py`'s
`test_the_help_screen_lists_exactly_the_keys_that_work` fails until the screen and the poll agree,
in both directions. Recorded in `docs/handoff-gameplay.md`, P4.

## 5. Tests and gates

- Host (`tests/host/test_menu.py`): the help stream decoded by the real device is the oracle's
  picture; the title and every row's glyphs exactly where the layout says, in their colours, and
  nothing else inked (legibility, glyph by glyph); the rows are the owner's map; not blank, not the
  menu; R9 -- one pixel of the oracle moved is caught, a too-wide row stops the generator; the rules
  (`test_the_help_rules`); the one mapping gives seven distinct pictures; a main menu without HELP
  stops the emitter.
- fj, `kb.poll` (`tests/fj/test_keyboard_input.py`): 'e' holds use like space, one shared flag; 'h'
  an event on its down edge only, also held across a frame boundary; the 0x6_ row's unbound keys
  discarded in phase; the help lists exactly the keys that work -- every key it names does something
  when RUN, every key the poll binds is named; R9 -- mirrors without 'e' or 'h' are rejected, an
  unbound key does nothing.
- fj, the state machine (`tests/fj/test_skill_menu.py`, `HELP_SCRIPTS`): nine scripts on the real
  `menu_state_lines` against `menu_step`, every new state and both ways out reached; four mutants
  (the world's help closing to the menu, the world ignoring h, enter on HELP acting as NEW GAME, the
  main menu's down dropped) each caught.
- fj, the whole menu block (`tests/fj/test_menu_screens.py`, new): the REAL `_menu_lines` -- state
  machine, producer branch and all seven baked screens -- run frame by frame through the keyboard
  and screen devices, each frame against `menu_step` + `menu_screen_pixels`; R9 -- the branch with
  two screens swapped is rejected at frame 1, an oracle whose world help closes to the menu at frame
  11.
- `m3_gate` (50 frames, was 32): after NEW GAME at hard -- the help from the world with W held across
  it (no move), esc back to the world; the main menu, down to HELP, enter, h, h, esc, up, h, esc, esc;
  h and h from the world. Controls: all seven pictures shown, the help frames hold the pose, the help
  closes both ways; `--selftest-help` (the oracle closes the world's help to the menu) must fail at
  frame 34.
- `probe.RECORDED_CALIBRATION` (startup + 2 menu frames, to the op) and the restore sets (`ev_help`
  is a new label) are re-recorded / re-keyed on the rung's build.
