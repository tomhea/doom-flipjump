# P10 -- the owner's second play-test round (plan, 2026-10-12)

**Status: PLAN.** Base: main `194ed62`, with blocked54 (P9) shipped. One feature build (blocked55) carries everything
below. The rung follows the full per-rung process: gates, B0 on a re-planned frozen set (v9), gamespeed, msframe
(class F), deg_gate attribution, tests/fj, PR, CR and merge.

## What the owner asked (2026-10-12), answering scratchpad/playtest_2026-10-12.md

| # | Ask | Package |
|---|---|---|
| 1 | Fix the floor/ceiling beyond a near boundary taking the near sector's look (nukage vanishes near its edge) | G2 |
| 2 | flipjump: a max-fps screen command; X is mine to choose | FPS |
| 3 | Make the exit switch, other switches, doors and the blue door distinct from walls AND from each other | T |
| 4 | LEVEL COMPLETE shows stats; ANY key returns to the main menu "as at the start of the game" | M |
| 5 | Fix sprites drawn over nearer ledges, and the 1-2 frame sprite blinks | G1, G3 |
| 6 | Turning "a bit faster" | P0 |
| 7 | Question: is monster FOV cheap, and is facing readable at 160x100? | (answered, below) |
| 8 | Add a shotgun and a chaingun on medium/hard (weaker is fine) | P0 (shotgun), CG |
| 9 | Skill screen defaults to MEDIUM; RESUME when a game is in progress; the weapon lowers on death; the help watermark | M, P0 |

**Two corrections to the play-test report** (from reading the code):
- **#7 already exists.** Both mirrors already ignore a player more than 90 degrees behind the monster beyond 64 units
  (`world.behind`, `LOOK_BEHIND_REACH`; fj `FACING_BEHIND` since P3.2a). The courtyard zombiemen face west (Thing
  angles 225/180), toward the start room, so they do see the player. Sound wakes whole regions, because E1M1 has no
  sound-blocking lines. The test costs well under 1K ops a check, and facing is readable up to about 256 units
  (`scratchpad/q7_facing.png`). **Nothing to build.**
- **#9's weapon already lowers in the logic.** `combat._kill_player` and `hurtcode.dp_kill` set the downstate. Only
  the DRAWING ignores the weapon height (the overlays are baked at WEAPONTOP).

## Decisions (mine, per "be autonomous"; the owner can overturn any)

- **FPS: X = 20.** On gamespeed's 10 games, frames run 33-378 ms (median 125, on a busy box). A 20 fps cap holds back
  only the cheap tail: 7% of frames here, more on a quiet or fast machine. At 2 monster tics a frame it caps the
  monsters at 40 tics/s, against DOOM's 35. flipjump `0x14 [X]` (branch `max-fps`, bc9c510): only the interactive
  window waits; headless runs never sleep. The doom program emits it once at boot (`present.set_max_fps`, entry
  part, next to the window title).
- **Turning:** `ANGLE_TURN_HELD` 960<<16 -> 1280<<16, i.e. 5.27 -> 7.03 degrees a frame (DOOM's per-tic fast turn).
  The tap stays 320<<16, so fine aiming is unchanged.
- **Dead player:** hide the weapon and its flash while `p_dead`, in both mirrors (about 2 ops a frame). Real lowering
  frames would cost 0.3-0.5M words for a 4-frame animation.
- **Shotgun:** Thing #41 (864,896, big room) joins `SINGLE_PLAYER_EXTRA`. **Chaingun:** Thing #40 (2288,1024, the
  cave), a new weapon in both mirrors. Their multiplayer ammo boxes stay multiplayer: that is the "a bit weaker".
- **Menus (M, built 2026-10-12):** a new persisted cell `g_live` (a game is in progress; `menu.menu_step` takes and
  returns `live`).
  - RESUME is the main menu's first item, highlighted when the world opens the menu, only while `g_live` is set
    (`menu_scr` 7). Esc on any main-menu item resumes only a game in progress; without one it is no rule and the
    next event in the order is read. Up from NEW GAME reaches RESUME only with a game.
  - The skill highlight boots at MEDIUM (`wall_renderer.BOOT_MENU_SKILL`). The boot WORLD stays HARD (`BOOT_SKILL`:
    the frozen sets and gamespeed measure it).
  - LEVEL COMPLETE shows KILLS x / total, ITEMS x / total, SECRETS x / total and TIME mm:ss, and "PRESS ANY KEY".
    Any key (`ev_any`: every key's down edge, the poll's discarded keys included) goes to the main menu with
    `g_live` cleared, the menu as at boot.
  - THE HOLD: the exit opens LEVEL COMPLETE at `menu_scr` 15, counted down a frame at a time to 8 and then to 2, which
    takes any key: eight frames (0.4 s at the cap) in which a key already on its way cannot skip the stats. Nibble
    values no other screen uses, so the hold needs no cell.
  - TIME is world frames / MAX_FPS seconds (not the DOOM clock): the wall-clock time on a machine that keeps the
    20 fps cap. `leveltime` widened from 16 to 20 bits (it wrapped after 55 minutes at the cap; now 14.5 hours).
  - Counters (`doomfj.statcode`; schema fields `p_killcount`, `p_itemcount`, `p_secretcount`, `p_secret[]`): kills
    at damagecode's `dm_kill` (every E1M1 monster is COUNTKILL), items at the COUNTITEM gives' taken exit, secrets by
    a per-secret box filter on the player's whole-unit position, then the point location and nukage's "on the
    floor" test, once each. Totals per skill: kills 17 / 29 / 46, items 53 / 49 / 48, secrets 4.
  - DRIVERS: the boot menu has no game, so key-driven drivers enter the world through NEW GAME at HARD
    (`m2_std_gate.boot_pick`: enter, down, enter; `MENU_FRAMES` 4). Probe drivers that poke every frame's state
    (b0_scenarios) POKE `mode` 0 and `g_live` 1 at frame 2 instead (`POKE_ENTER`), so NEW GAME's restart cannot
    overwrite their pokes and the frame layout stays v8's. p2a_gate's S8 drops its "frozen" control: no play reaches
    the frozen world after the exit frame now.
- **Switches and doors (T):** per-seg colour overrides, read by both mirrors from ONE helper.
  - EXIT (special 11): a red panel.
  - Other switches (SW1*/SW2* textures): orange/yellow.
  - Doors (door lines, shut face): tan/yellow with dark.
  - Blue doors (special 26/32 and their DOORTRAK jambs): blue.
  - All are lit by the sector light like any wall, and the pattern stays the shared masonry walker (no new fj code).
- **G2 (built 2026-10-12):** a per-column, per-side BASE.
  - An upper piece wholly ABOVE the screen, or a lower piece wholly BELOW it (`ts_piece_store`'s two off-screen
    exits), records its back pid as the side's base: bit 3 of the side's count nibble in `sfflag` (the side's count
    is 0 there: a stored piece clamps a farther one past its end, onto the screen) and the pid in `sfbase`
    (`[VIEW_W ceilings][VIEW_W floors]`, declared right after `sfflag`, reached by a constant offset). A farther
    off-screen boundary overwrites it: the farthest wins. `sfbase` is never reset; its pids are read only under the
    flag, and `sfflag` is in the M1 set.
  - Every count test in `ts_step_faces` asks for the count with or without the flag (`frame.if0_cnt`: `if0`'s own
    expansion with mask 0xfefe; the room test is one `hex.if_flags` dispatch, {0,1,8,9}).
  - Pass 2: `lines_steps_load2` runs FIRST, strips the flags and reads the base pids (`lines_base_split`);
    `lines_col_plane_ids` keys its cache on (claim pid, ceiling base, floor base) and overrides the ceiling / floor
    ids (`lines_base_ids`); the sky test asks about the EFFECTIVE ceiling pid (`lines_eff_ceil`); the bases join
    the ditto signature. The oracle: `cbase` / `fbase` and `_region_paint` of the base region (`bases_out`).
  - It takes no stack slot, so the door-100 lintel fix (efde61c) stands.
- **G8 (found while building G2):** the region BEHIND a stacked upper piece whose back ceiling is F_SKY1 walked the
  F_SKY1 FLAT's plane lists in fj, where the oracle paints sky. The shipped blocked54 disagrees with its own oracle
  by 60 px at (-416, 128) facing north (the start room's window lips onto sector 18; P9 worktree, probe injection).
  Fixed in fj: `lines_piece_sky` flags each upper piece whose back ceiling is sky and sets the column's sky u
  (`soff`, the ditto signature's sky rung); `steps_splice_c` walks the column's sky pair there
  (`lines_region_ids_c`).
- **G1 (built 2026-10-12):** the record snapshots the column's `sfflag` byte -- the counts of the pieces stored
  so far, all NEARER than the thing (the walk is front to back) -- into the fragment's 4th byte: 3 (A), 7 (C), 11 (B)
  (`frame.rec_clip_read`; `SPR_FRAG_FIELDS` gains "clip counts"). The emit derives the window from the loaded
  pieces (`stream.frag_clip`: the last nearer upper piece's end + 1 down to the last nearer lower piece's start,
  DOOM's running ceilingclip / floorclip), clamps the fragment's rows into it (`frag_clamp`) and walks a cut
  fragment through the window (`frag_runs_cut`); slot B's two windows are bounded by its own. The snapshots join the
  sprite signature. The oracle: `sclip` / `sclip2`, snapshotted at the record, the paint clamped. No per-column
  "no slot when clipped away" rule: a hidden column still holds its slot (both mirrors).
- **G3 (built 2026-10-12): a THIRD fragment slot.** Classified on v8's 1,100 frames with the p67e attribution: a live
  monster the player should see (an open column, a row in the view) claimed no slot 101 times -- 50 legitimately (its
  open columns are its transparent edge: "empty"), 51 because two NEARER fragments held both slots in every open
  column ("full"): a corpse in slot B 18 times, a crowd (two live monsters) 8, blood or a fireball 6, the rest mixed.
  Slot C takes the third record under B's gate: `spslot` bytes 4-7 (between A's and B's; the stride stays 16),
  `sprflag` 3, the oracle's `sfrag3` / `sclip3`, painted C, B, A. The emit composites C into the A+B path's four
  background windows (`stream.emit_region_c`: region | C's runs | region, each guarded); C joins the ditto
  signature. With three slots the same scan leaves 16 of the 51 (one courtyard crowd, four sprites deep) and no new
  miss (`g3_blinks3.py`, P10 session).

## The harness at P10 (2026-10-12)

- **gamespeed gen 3b.** At the P10 turn rate the route planner ORBITED: holding forward (16 units a frame) while
  turning 7.03 degrees a frame draws a circle of radius ~130 units, and a waypoint inside it on the turn's side is
  never reached -- the run circles it, moving every frame, so the planner's `stuck` rule never fires. Measured: nine
  of the ten runs ended within 200 units of spawn with a turn key on all 100 frames (gen 2's failure, the starting
  room measured ten times). `_steer` now turns on the spot to such a waypoint (d < 2 r |sin err|) and counts a turn
  on the spot as no refused step. The ten runs: 9/10 distinct end cells, spread 920 units, worst run 33% blocked,
  every run >= 660 units travelled. `BINARY_ENDS` are GameSim's predicted ends ((578, 303) ... (97, 254), no door),
  owed their confirmation by `gamespeed_trail.py` on the P10 build; runs 0/1's recorded keys re-recorded.
- **Replay tests re-pointed** (the faster turn moved every recorded replay): test_aim_window_oracle's slice to v9
  (R3-mid 25, R0-west-hall 25, R2-spectre-corridor 10 frames: 45 targets at column 80, the window agrees with the
  geometric aim on all 60 frames and on 1017 / 1020 columns; three residuals, all "edge-closed"; the controls move 25
  and 6 frames); test_b0_setup_and_proxy to v9 at its "final" modes (the poke moves `sshead`, not `thpos_rt`: measured
  under both modes); test_gamespeed_validate and test_p67_model's route prediction to the re-recorded keys.
- **fight_gate CG1** (the chaingun in the game binary, `--only CG`): key 4, a late setup at an awake crowd, the
  trigger held -- both bursts' flashes, accurate then spread rounds, hits; controls `cgun_one_flash`, `cgun_accurate`.
  On the model (`--oracle-only --only CG`, docs/ship-evidence/p10_fight_cg_oracle.log): placed at the first candidate,
  8 rounds (3 accurate, 5 spread), 7 hits, 2 kills, each burst's flash on 8 frames; the controls part at frames 28
  and 30.
- **The re-key without P9's label table** (`scratchpad/ca_rekey_newspan.py`): `_ca_labels_p9.tsv.gz` did not survive
  its worktree, and a re-capture cannot reproduce its recorded sha256 (gzip stamps the time). Every entry of the
  shipped set holds a contiguous prefix of a GLOBAL label; an entry that covers its label's new span is kept, any
  other needs a decision on the command line (`--whole` / `--keep`), each recorded in `generated_by`. Its selftest's
  six negative controls refuse a grown or shrunk label without a decision, a `--keep` past the label, a vanished
  label, a non-prefix entry and an old table whose fingerprint differs.
- tests/fj/test_slot_layouts_fj: the snapshot mutant writes `trb_blk + 0*trb_clip_v` -- the record's `<` list names
  the snapshot register, and an unused name there is an assembly error, so the mutant must keep it referenced.

## Order of work

P0 (small items) -> M -> T -> G2 -> G1 -> G3 -> CG -> the v9 plan (oracle-only; shown to the owner) -> build ->
gates/B0/gamespeed/msframe/deg_gate -> tests/fj -> PRs (flipjump max-fps first: the game binary emits 0x14, which an
older flipjump rejects as an unknown command) -> CR -> merge.
