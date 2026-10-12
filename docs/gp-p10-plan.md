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
- **G2:** a per-column, per-side BASE OVERRIDE.
  - A lower piece wholly below the screen (or an upper piece wholly above), met while that side has no stored piece,
    records its back plane-pair (`bpid`/`bsec`) as the side's base.
  - The base region -- the whole floor or ceiling, or region0 in front of the nearest stored piece -- is then painted
    from that pair instead of the claimed one.
  - It takes no stack slot, so the door-100 lintel fix (efde61c) stands. Sky follows the claimed path's sky lookup.
- **G1:** the record snapshots this column's nearer-boundary rows. `ctop` is the last stored upper piece's y2+1;
  `cbot` is the last stored lower piece's y1. They go into the fragment (spslot's free bytes 3-4 / 11-12), and the
  emit clamps the fragment's rows to `[ctop, cbot)`. A column whose fragment misses the window gets no slot (actors
  rule (4), generalised).
- **G3:** classify the sergeant blink (scratchpad/playtest_sergeant_blink.png, oracle-reproducible) with
  p67e_visibility_probe before choosing a fix.

## Order of work

P0 (small items) -> M -> T -> G2 -> G1 -> G3 -> CG -> the v9 plan (oracle-only; shown to the owner) -> build ->
gates/B0/gamespeed/msframe/deg_gate -> tests/fj -> PRs (flipjump max-fps first: the game binary emits 0x14, which an
older flipjump rejects as an unknown command) -> CR -> merge.
