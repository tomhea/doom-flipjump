# M7 P1.5 -- the skill filter and the skill menu (design, before the build)

The handoff's rung P1.5 (`docs/handoff-gameplay.md` section 10; decision D7): **the build spawns per
skill; NEW GAME asks easy / medium / hard and starts from that skill's level-start state** -- the
full restart block is P7. Class F: pixels move (the multiplayer-only things go, and the monsters and
pickups present depend on the chosen skill). Kill criteria: `docs/gp-ledger.md`.

## 1. What the model already says (phase 0, `src/doomfj/world.py`)

`World(skill)` / `reset(skill)` is the level start the fj side must reproduce, cell for cell:

- **The thing universe** is the union of the single-player skills, in WAD order: a thing flagged
  `MTF_NOTSINGLE` (multiplayer only) is not in it at all, nor is one with no skill bit.
- **Monsters** of the other skills keep their slots, `mon_active = 0`, and are NOT linked into their
  leaf's list; the chosen skill's are linked (`_list_insert`, ascending).
- **Pickups** of the other skills start TAKEN (`pickup_taken = 1`), which fj holds inverted as
  `thvis` (the M14.5 vanishable flags) -- hidden.
- **Decor** present at a skill is `_decor_for(skill)`; **barrels** of the other skills are not spawned.

MEASURED on E1M1 (freedoom_e1m1.wad things, freedoom1.wad art): `docs/ship-evidence/
p15_skill_census.log`, part A (`scratchpad/gp/p15_skill_census.py`). The classes: monsters =
`MONSTER_TYPES`, barrels = type 2035, pickups = the other `VANISHABLE_TYPES`, decor = the rest.

| | things | pickups | monsters | decor | barrels |
|---|---|---|---|---|---|
| drawable before this rung (art only) | 251 | 120 | 53 | 56 | 22 |
| multiplayer-only (leave the image) | 26 | 26 | 0 | 0 | 0 |
| the single-player union (the image) | 225 | 94 | 53 | 56 | 22 |
| easy | 183 | 88 | 17 | 56 | 22 |
| medium | 184 | 77 | 29 | 56 | 22 |
| hard | 203 | 79 | 46 | 56 | 22 |

(The first version of this table had no log and split the multiplayer-only 26 as 18 pickups and 8
decor; under the classes above all 26 are pickups -- 7 weapons, 18 ammo, a soulsphere.)

64 things change with the skill: 43 of the 53 monsters (10 are on every skill) and 21 pickups, all
of them VANISHABLE types. No decor and no barrel does -- so the two presence mechanisms that exist already
cover it: the leaf lists (runtime things) and `thvis` (baked vanishable things). And
`new_game(skill)` asks for the restart block at the next tic.

## 2. The fj side

**Build time.** `things.single_player(t)` is the universe's predicate, ONE definition: the renderer's
`drawable_things` (the emitter, the oracle, every gate) and the model's `World` both take it, so the
26 multiplayer-only things leave the image and everything of any single-player skill stays -- the
image holds the union (53 monsters). `things.thing_rows` takes it too (it had its own art-only test).

**Presence at run time -- `things.skill_absent(drawable, skill)`**, the drawable indices a skill does
not spawn, is the ONE answer both mirrors ask:
- **runtime things** (monsters, and the things that share a monster's leaf): the leaf lists (M7 P1.3)
  are baked PER SKILL -- `spawn_leaf_lists` over the things the skill spawns; an absent thing is in
  no list, so the thing pass never reaches it;
- **baked things**: only VANISHABLE types vary by skill on E1M1 (section 1), and each baked
  vanishable thing already has a `thvis` flag (1 visible, 0 hidden; `hex.if0` skips it). The emitter
  asserts that no baked thing without a flag varies by skill -- a map where one did would need a
  flag first, and must say so at emit time rather than draw the wrong things;
- **the oracle**: `render_wall_frame(thing_hidden=...)` accepts absent RUNTIME things as well as
  hidden baked vanishable ones (it asserted baked-only until now) -- but only a skill's: the
  runtime things named must be exactly the ones one skill does not spawn, the only runtime absence
  fj can draw (the P1.5 review; any runtime thing was accepted at first). The gates pass
  `skill_absent`.

**The boot state is hard's level start.** The image's pristine lists and `thvis` values are HARD's --
the skill the frozen combat set v2 runs at and the budget is sized on (D7) -- so the set, B0 and every
gate that enters the world without choosing a skill see a hard world.

**The restart block** (this rung's part of P7's): choosing a skill runs one baked block per skill that
sets every cell the fj program PERSISTS today to its level-start value for that skill -- the view
(`viewx`, `viewy`, `viewangle`: the player start), the doors (`dstate`, `ddir`, `dsub`, `dwait`:
shut and idle), the thing lists (`sshead` / `thnext`: the skill's), the bindings and positions
(`thss_rt` / `thpos_rt`: the spawn), the `thvis` flags (the skill's) -- with the M1 reset's own cell
writers (`hex.set` for nibble cells, `m1.zerobyte` then a flip for byte cells), and enters the world
(`mode` = 0). It runs on the one frame a skill is picked, so its ops are a menu event, not a
per-frame cost. P7 extends it with the combat state as that lands. Held-key flags and `mode` are not
level state and are not in it.

**The menu.** M3 is one baked frame, and `enter` / `esc` toggle `mode`. Now:
- `menu_scr` (persisted, 1 nibble): 0 = the main menu, 1 = the skill screen; `menu_sel` (persisted):
  the highlighted skill, baked to 2 (HARD, the skill the budget is sized on);
- on the main menu, `enter` opens the skill screen, and `esc` toggles to the world as today;
- on the skill screen, `w` / `s` move the highlight (clamped at the ends), `enter` runs the chosen
  skill's restart block, `esc` goes back to the main menu;
- every screen is a baked 0x0B frame (`doomfj.menu`, the same generator for both mirrors): the main
  menu, and the skill screen once per highlighted entry -- a constant byte stream each (~2.3K ops).

**As implemented** (before the build):
- The polls only RECORD: `kb.poll` sets `ev_enter` / `ev_esc` on enter's and esc's down edges and
  `ev_up` / `ev_dn` on forward's and back's (w / up arrow, s / down arrow), which the frame zeroes
  before its polls; M3's toggle of `mode` inside the poll is gone. After the polls,
  `wall_renderer.menu_state_lines` acts on the first of esc, enter, up, down -- the rules above --
  and then the producer branch picks the world or one of the four screens.
- The rules have ONE Python side, `doomfj.menu.menu_step` (with `MENU_KEYS`, the device's keycodes),
  which every check that drives a program through the menu steps: `tests/fj/test_skill_menu.py`
  runs the real `menu_state_lines` and `restart_lines` against it in a frame loop from DIRTY cells,
  printing every cell the restart writes (until the P1.5 review: only viewx, dstate, two list bytes
  a side and one flag), with swapped moves and the restart minus each group of its writes in turn
  as its R9 controls.
- `menu_scr` and `menu_sel` persist the way `mode` does: they are declared with the standalone
  tier's globals (`STANDALONE_SCRATCH_DECLS`, so `m5_setfile.py` re-attaches them to the restore set
  at their widths) and named in `build.STANDALONE_PERSIST`, the set's one intended hole -- the
  build refuses a persist name the set does not carry. The event cells and `rs_ret` are ordinary
  residue. `menu_sel`'s baked value derives from `BOOT_SKILL`.
- The restart block is `restart_common` (fcall'd: the player start, the doors shut and idle, each
  runtime thing's spawn leaf and position, every list byte zeroed with `m1.zerobyte`) plus each
  skill's inline half (its non-zero list bytes flipped in, its `thvis` flags set).
- Every driver leaves the boot menu with ESC (`m2_std_gate.menu_exit_events`, which gamespeed,
  b0_scenarios and the play tools compose): enter opens the skill screen now, and esc meant the
  world on every binary before this rung too, so one driver serves old and new binaries alike.

## 3. Gates and budget

- `m3_gate`: the menu frames byte-exact through the skill screen and all three skills' NEW GAME,
  each followed by world frames byte- and state-exact against the oracle at that skill's level
  start -- with the controls that the restart REALLY resets (walk, open a door, NEW GAME: the view
  and the door are back) and that the skills really differ (the frames at easy and hard differ
  exactly where `skill_absent` says). As implemented: 32 frames -- M3's script, then the skill
  screen clamped at both ends, backed out of, and NEW GAME at easy, medium and hard; controls: the
  first NEW GAME finds the player walked away, every NEW GAME frame is the spawn view, and the three
  NEW GAME frames are pairwise distinct in the oracle (MEASURED at the spawn view: easy / hard 20 px,
  easy / medium 12, medium / hard 8 -- `docs/ship-evidence/p15_skill_census.log`, part C, m3_gate's
  render of each). `--selftest-skill` (the oracle starts the next skill) must
  fail at frame 20.
- `m2_std_gate`: its route, entering the world at the boot state (hard) -- then, with the door open
  and walked through, NEW GAME at the boot skill and the same route again, which must retrace the
  first walk pose for pose and end facing a SHUT door (control 6; the door must have been open when
  NEW GAME landed -- UNVERIFIED: an unlogged `--dry` run found it at state 5, its pass state 4;
  control 6 itself requires at least the pass state on every run of the gate -- and the last frame
  must be able to tell). `--selftest-restart` (the oracle never restarts) must fail. This is the kill
  criterion 2's "walk, open a door, choose a skill" on the shipped binary.
- `b0_scenarios` on set v2: the runs start from their checkpoints at hard, and the frames change by
  what hard does not spawn -- the 26 multiplayer-only things and the 7 zombiemen of the other skills
  (the census log, part A; the model has always run at hard, and the render oracle is now told so,
  through `thing_hidden`).
- Budget: -0.3M ops/frame on the v2 binding (handoff section 10). ESTIMATE (plan section 7's R4):
  7 zombiemen and 26 multiplayer-only things no longer drawn at hard.
