"""M3 GATE -- the menu and the world, in ONE run, chosen by persisted cells.

    python scratchpad/m3_gate.py --fjm build/doom_e1m1_menu.fjm --labels <its label table>
    python scratchpad/m3_gate.py --selftest          # R9: every frame claimed to be a world frame
    python scratchpad/m3_gate.py --selftest-skill    # R9 (M7 P1.5): the oracle starts the WRONG skill
    python scratchpad/m3_gate.py --selftest-state    # R9 (M7 P1.5): a state no picture shows is wrong
    python scratchpad/m3_gate.py --selftest-help     # R9 (M7 P3.4): the world's help closes to the MENU

The binary boots into the MAIN MENU (`mode` bakes to 1, `menu_scr` to 0). M7 P1.5 gave the menu a
skill screen (docs/gp-skill-menu.md; `doomfj.menu.menu_step` is the rules' oracle side): in the
world esc or enter opens the main menu; there esc resumes the world and enter opens the skill
screen; there w / s move the highlight (clamped), esc goes back, and enter starts the highlighted
skill -- the level restarts at that skill's start and the same frame is a world frame. So one run
produces two entirely different kinds of frame from the same program, and every one is compared:

  * menu frames against `doomfj.menu.pixels()` for the screen the rules say is up -- the main menu,
    or the skill screen with its highlight -- the oracle side of the generator fj emits from;
  * world frames against `ReferenceModel.render_wall_frame` at the state the sim reached, hiding
    what the skill being played does not spawn (`things.skill_hidden`; the boot skill until a NEW
    GAME picks another).

THE THINGS THIS GATE EXISTS TO CATCH, none of which a single-frame check would see:

  1. THE MODE MUST PERSIST. It is excluded from the M1 restore set (build.STANDALONE_PERSIST); if
     that exclusion were missing, `mode` would snap back to 1 every frame and the game would show
     the menu forever, one frame after appearing to work. M7 P1.5: `menu_scr` and `menu_sel` too --
     a skill screen that reset every frame could never be left, a highlight never moved.
  2. THE MENU MUST NOT MOVE THE PLAYER. The branch sits before the sim, so menu frames skip the
     tic entirely -- which is what makes leaving the menu resume where you were. The script walks,
     opens the menu, holds a key WHILE IN THE MENU, and requires the player not to have moved.
  3. THE EVENTS MUST EDGE-TRIGGER. A press delivers a down AND an up event; acting on both would
     act twice (M3's toggle landed back where it started; a highlight would move two rows).
  4. NEW GAME MUST RESTART AT THE CHOSEN SKILL (M7 P1.5). Walked away from the spawn first, each
     NEW GAME frame must be the spawn view with THAT skill's things -- and the three skills' spawn
     views differ (CONTROL), so a restart that loaded another skill's lists or flags is caught.
  5. EVERY FRAME IS STATE-EXACT (M7 P1.5, kill criterion 3). The persisted cells -- the view,
     `mode`, `menu_scr`, `menu_sel` and every door's cells (shut and idle throughout: this script
     never presses use) -- are read at each present through the build's label table
     (scratchpad/gp/gatestate.py) and must equal the oracle's after that frame. A world frame cannot
     show `menu_scr`, so pixels alone would pass a screen cell that NEW GAME left wrong;
     --selftest-state (R9) expects exactly that from the oracle, and must be rejected on the first
     NEW GAME frame by the state check alone.
  6. THE HELP (M7 P3.4, docs/gp-help.md). From the world (h), the help is up, W held across it moves
     nobody, and esc closes it back to the WORLD where it was; from the main menu -- down to its
     HELP item and enter, and h on either item -- the help is up and esc / h close it back to the
     main menu on HELP; h again from the world and h closes it. Every help and main-menu frame is
     compared to `wall_renderer.menu_screen_pixels`, the one mapping from the menu's state to its
     picture. --selftest-help (R9): the oracle closes the world's help to the main menu, and the
     gate must reject it at the frame esc leaves the help (HELP_CLOSED_TO_WORLD).
  7. P10 (the owner's play-test, 2026-10-12): `g_live`. The boot menu has NO game -- esc on it is no rule, up from
     NEW GAME is clamped, and its HELP and EXIT highlights are its own pictures -- so the world is entered through
     NEW GAME (the skill screen's highlight boots at MEDIUM); from then on the menu opens on RESUME (its first item,
     W held across it), esc or enter there resume in place, and up from NEW GAME reaches it (clamped there). Every
     main-menu picture is checked in both variants, RESUME highlighted once more, and `g_live` is read each frame.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for q in (ROOT / "tests", ROOT / "src", ROOT):
    sys.path.insert(0, str(q))
if __name__ == "__main__":          # M8 (CR of #146): `--map E1Mn` before probe / gamespeed read their defaults
    from doomfj.mapprofile import take_map_arg
    take_map_arg(keep=True)         # keep: this gate's own parser takes --map too

from doomfj.config import Config                                          # noqa: E402
from doomfj.doors import door_states, initial_states, walkover_triggers   # noqa: E402
from doomfj.fixedpoint import _signed                                     # noqa: E402
from doomfj.menu import (HELP_GAME_SCR, HELP_MENU_SCR, MAIN_EXIT_SCR,    # noqa: E402
                         MAIN_HELP_SCR, MAIN_RESUME_SCR, MENU_HALTED, MENU_KEYS, menu_step, palette_colours)
from doomfj.reference_model import (ReferenceModel, SimState,             # noqa: E402
                                    build_scene, spawn_state)
from doomfj.things import skill_hidden                                    # noqa: E402
from doomfj.wad import WadFile                                            # noqa: E402
from doomfj.reference_model import GAME_RENDER_KW                          # noqa: E402
from doomfj.wall_renderer import (BOOT_MENU_SKILL, BOOT_SKILL, DEFAULT_MENU,               # noqa: E402
                                  SKILL_MENU, SKILL_MENU_FIRST, SKILLS, STANDALONE_POLLS,
                                  menu_screen_pixels)
from flipjump.interpreter.io_devices.KeyboardIO import KeyEvent               # noqa: E402

ENTER, ESC, K_FWD, K_BACK = 0x0D, 0x1B, 0x77, 0x73
K_HELP = 0x68                                  # M7 P3.4: the help key
SKILL_NAMES = {s: n for s, n in zip(SKILLS, ("easy", "medium", "hard"))}


def press(f, key):
    """a key pressed and released within frame f's first two polls"""
    return [(f, 0, True, key), (f, 1, False, key)]


# (frame, poll, is_down, keycode). The binary boots into the menu, so frames 0-1 are menu frames
# with no input at all -- which is already control 1: if `mode` did not persist there would be
# nothing to persist it FROM, but if the RESET clobbered it these frames would still look right
# and frame 2 would go wrong. P10: the boot menu has no game -- esc on it is no rule, and NEW GAME is the way in.
SCRIPT = (
    press(2, ESC)                              # the boot menu: esc is no rule (P10) -- no game in progress
    + press(3, K_BACK) + press(4, K_BACK)      # down, down: the boot menu's HELP, then its EXIT
    + press(5, K_FWD) + press(6, K_FWD)        # up, up: HELP, NEW GAME
    + press(7, K_FWD)                          # up: clamped (no RESUME without a game)
    + press(8, ENTER)                          # -> the skill screen, MEDIUM highlighted (P10)
    + press(9, K_FWD)                          # up: easy
    + press(10, ENTER)                         # NEW GAME at easy: its level start, this frame
    + [(11, 0, True, K_FWD)]                   # walk
    + press(14, ENTER)                         # -> the main menu ON RESUME from frame 14, W STILL HELD
    + press(17, ESC)                           # esc on RESUME -> the world from frame 17; must resume in place
    + [(19, 0, False, K_FWD)]
    + press(20, ENTER)                         # -> the main menu, on RESUME
    + press(21, K_BACK)                        # down: NEW GAME (the game's menu)
    + press(22, ENTER)                         # -> the skill screen, easy STILL highlighted
    + press(23, K_FWD)                         # up: clamped at the first skill
    + press(24, K_BACK) + press(25, K_BACK)    # down, down: medium, then hard
    + press(26, K_BACK)                        # down: clamped at the last skill
    + press(27, ESC)                           # -> back to the main menu (the game's, NEW GAME highlighted)
    + press(28, K_FWD)                         # up: RESUME (P10)
    + press(29, K_FWD)                         # up: clamped at RESUME
    + press(30, K_BACK)                        # down: NEW GAME
    + press(31, ENTER)                         # -> the skill screen, hard highlighted
    + press(32, ENTER)                         # NEW GAME at hard, where the player walked away from the spawn
    + press(34, ENTER) + press(35, K_BACK) + press(36, ENTER)   # RESUME, NEW GAME, the skill screen (hard)
    + press(37, K_FWD)                         # up: medium
    + press(38, ENTER)                         # NEW GAME at medium
    # M7 P3.4 -- THE HELP (docs/gp-help.md), in the world at medium's level start
    + press(40, K_HELP)                        # h in the world: the help, from frame 40
    + [(40, 2, True, K_FWD)]                   # W pressed WHILE THE HELP IS UP, held
    + [(42, 0, False, K_FWD)]                  # ... released,
    + [(42, 1, True, ESC), (42, 2, False, ESC)]   # ... and esc: the WORLD again from frame 42
    + press(44, ENTER)                         # the main menu, on RESUME
    + press(45, K_BACK) + press(46, K_BACK)    # down, down: NEW GAME, then HELP highlighted
    + press(47, ENTER)                         # enter on HELP: the help, from the menu
    + press(49, K_HELP)                        # h: back to the main menu, HELP highlighted
    + press(50, K_HELP)                        # h on HELP: the help again
    + press(51, ESC)                           # esc: back to the main menu on HELP
    + press(52, K_FWD)                         # up: NEW GAME highlighted
    + press(53, K_HELP)                        # h on NEW GAME: the help
    + press(54, ESC)                           # esc: the main menu on HELP
    + press(55, ESC)                           # esc: the world, where it was (a game is in progress)
    + press(56, K_HELP)                        # h: the help, from the world
    + press(57, K_HELP)                        # h: the world again
    # P9 -- EXIT, the main menu's last item (the owner's play-test, 2026-10-10; P10: the game's menu)
    + press(59, ENTER)                         # the main menu, on RESUME
    + press(60, K_BACK) + press(61, K_BACK) + press(62, K_BACK)   # down x3: NEW GAME, HELP, EXIT
    + press(63, K_BACK)                        # down: clamped at EXIT
    + press(64, K_FWD) + press(65, K_BACK)     # up: HELP; down: EXIT again
    + press(66, K_HELP)                        # h on EXIT: the help, from the menu
    + press(67, K_HELP)                        # h: the main menu again
    + press(68, K_BACK)                        # down: EXIT
    + press(69, ESC)                           # esc on EXIT: the world, where it was
    + press(71, ENTER)                         # the main menu, on RESUME
    + press(72, K_BACK) + press(73, K_BACK) + press(74, K_BACK)   # down x3: EXIT
    + press(75, ENTER)                         # enter on EXIT: the program HALTS -- frame 75 is never presented
)
FRAMES = 75                                    # P9: frames 0..74 are presented; the halt comes in frame 75
HALT_FRAME = 75
WITH_W_HELD = (14, 15, 16)                     # menu frames (on RESUME) while W is held
NEW_GAMES = (10, 32, 38)                       # easy (from the boot menu), hard (after a walk), medium
WALKED_NEW_GAME = 32                           # the NEW GAME that finds the player walked away from the spawn
WITH_W_HELD_HELP = (40, 41)                    # M7 P3.4: help frames while W is held
HELP_CLOSED_TO_WORLD = 42                      # M7 P3.4: esc leaves the world's help
HELP_CLOSED_TO_MENU = 49                       # M7 P3.4: h leaves the menu's help
# M7 P3.4: every menu picture the script must show -- (menu_scr, the highlight on the skill screen, g_live on a
# main-menu screen); P10: the main menu's three highlights without a game and with one, and RESUME's
_MAIN = (0, MAIN_HELP_SCR, MAIN_EXIT_SCR)
ALL_SCREENS = ({(m, None, live) for m in _MAIN for live in (0, 1)} | {(MAIN_RESUME_SCR, None, 1)}
               | {(HELP_MENU_SCR, None, None), (HELP_GAME_SCR, None, None)}
               | {(1, k, None) for k in range(len(SKILLS))})


def _screen_key(scr, sel, live):
    """a menu frame's picture key: the skill screen by its highlight, a main-menu screen by `g_live` (P10)"""
    return (scr, sel if scr == 1 else None, live if scr in _MAIN + (MAIN_RESUME_SCR,) else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fjm", default="build/doom_e1m1_menu.fjm")
    ap.add_argument("--labels", default=None,
                    help="the build's label table (build_labeled.py --labels) -- the state check "
                         "reads the persisted cells through it; the gate refuses to run without it")
    # M8: the map from doomfj.mapprofile (DOOMFJ_MAP / --map; E1M1 when unset), its fixture wad unless --wad names one
    from doomfj.mapprofile import ACTIVE, profile
    ap.add_argument("--wad", default=None, help="default: the map's fixture (mapprofile)")
    ap.add_argument("--map", default=ACTIVE)
    ap.add_argument("--asset", default="assets/freedoom1.wad")
    ap.add_argument("--selftest", action="store_true",
                    help="R9: claim every frame is a world frame; the gate must FAIL")
    ap.add_argument("--selftest-skill", action="store_true",
                    help="R9 (M7 P1.5): the oracle starts the NEXT skill at every NEW GAME; the "
                         "gate must FAIL")
    ap.add_argument("--selftest-state", action="store_true",
                    help="R9 (M7 P1.5): the oracle expects the skill screen's menu_scr on the world "
                         "frames from the first NEW GAME -- invisible in a world frame; the STATE "
                         "check must reject it")
    ap.add_argument("--selftest-exit", action="store_true",
                    help="R9 (P9): the oracle ignores enter on EXIT (no halt); the gate must FAIL")
    ap.add_argument("--selftest-help", action="store_true",
                    help="R9 (M7 P3.4): the oracle closes the world's help to the MAIN MENU; the "
                         "gate must FAIL at frame %d" % HELP_CLOSED_TO_WORLD)
    args = ap.parse_args()
    args.map = args.map.upper()
    args.wad = args.wad or profile(args.map).wad

    mw = WadFile.from_path(str(ROOT / args.wad))
    art = WadFile.from_path(str(ROOT / args.asset))
    # M7 P4.0: the GAME tier's config (the 84-row view under the status bar) and its screen (hud.GameScreen);
    # a menu frame still covers the whole W x H screen (menu_screen_pixels draws at cfg.W x cfg.H)
    from doomfj.config import GAME_CFG
    from doomfj.hud import GameScreen
    cfg = GAME_CFG
    rm = ReferenceModel(cfg)
    gscreen = GameScreen(rm, mw, art, mw.sectors(args.map))
    scene = build_scene(mw, mw, args.map)
    colours = palette_colours(bytes(b for rgb in mw.playpal(0) for b in rgb))
    # M7 P3.4: the menu's pictures through the ONE mapping from its state (the help joined them)
    screens = {key: bytes(menu_screen_pixels(cfg, colours, key[0], key[1] or 0, key[2] or 0))
               for key in ALL_SCREENS}
    render_kw = dict(GAME_RENDER_KW, sprite_wad=art)
    hidden = {s: skill_hidden(rm, mw.things(args.map), art, s) for s in SKILLS}

    events = [KeyEvent(f * STANDALONE_POLLS + p, d, c) for f, p, d, c in SCRIPT]
    print("fjm    : %s" % args.fjm)
    print("menu   : %s   colours bg=%d text=%d hi=%d credit=%d" % (DEFAULT_MENU, *colours))
    print("skills : %s -- hidden %s; the boot skill is %s"
          % (SKILL_MENU[SKILL_MENU_FIRST:], [len(hidden[s]) for s in SKILLS],
             SKILL_NAMES[BOOT_SKILL]))
    print("script : boot menu (no game): esc@2 no rule, HELP/EXIT @3-4, clamp @7 -> the skill screen @8 "
          "(medium), NEW GAME at easy@10 -> walk -> enter@14 (RESUME, W held) -> esc@17 -> the skill screen @22, "
          "clamp both ends, back, RESUME @28 (clamp @29), NEW GAME at hard@32, medium@38 -> the help from the "
          "world @40 (W held) -> esc@42 -> the menu's help @47, h@49 .. esc@55 -> the world's help @56-57 -> P9: "
          "EXIT @62, clamp @63, its help @66-67, esc to the world @69, enter on EXIT @75: the HALT")

    if not args.labels:
        print("  NO --labels. This gate is byte- AND state-exact (M7 P1.5), and without the build's")
        print("  label table it cannot read the program's state. Refusing to run.")
        return 1
    secs, lds, sds = mw.sectors(args.map), mw.linedefs(args.map), mw.sidedefs(args.map)
    order = sorted(door_states(secs, lds, sds))
    init = initial_states(secs, lds, sds)
    doors0 = [init[si] for si in order]          # this script never presses use: shut and idle
    # M7 P2a.1: ...and never reaches a walk-over trigger or the blue card: no press pending, no
    # card, no trigger fired (doors.DoorPhase's initial state)
    nwalk = len(walkover_triggers(secs, lds, sds, mw.vertexes(args.map)))
    phase0 = (init, (0,) * nwalk, frozenset(), 0)
    sys.path.insert(0, str(ROOT / "scratchpad" / "gp"))
    import gatestate as GST
    # M7 P3.1: the idle monsters -- the model's own phase (doomfj.monsters), from the boot skill's
    # level start, a tic per world frame, reset by NEW GAME; drawn with their views, cells read
    from doomfj.monsters import MonsterPhase, MonsterViews, view_drop_kw
    from doomfj.wall_renderer import MONSTER_MODE, PLAYER_MODE
    mph = MonsterPhase(mw, args.map, BOOT_SKILL, rm=rm, mode=MONSTER_MODE, player=PLAYER_MODE)   # M7 P4.1
    mviews = MonsterViews(rm, mw, args.map, art, mph.world)
    pals = []                                       # M7 P5: the palette each present showed
    from doomfj.world import player_loots
    loot = player_loots(mph.world.player)           # M7 P6: the player lives in the world's things
    deaths = 0                                      # M7 P7: frames the mirror's player was dead (this walk: none)
    causes = []                                     # P9: how the run ended -- the halt is LOOPING
    got, ops, reads = GST.run_reading_state(ROOT / args.fjm, ROOT / args.labels, events, FRAMES + 2,
                                            len(order), nwalk, nlift=len(mph.world.lift_order),  # M8: the map's
                                            nmon=mph.world.layout.nmon, nrt=mviews.nrows(mph),
                                            palettes_out=pals, nthvis=mviews.nvis if loot else 0,
                                            cause_out=causes)
    # M7 P3.2b: the monsters step inside this gate's fixed world -- its doors shut and idle, every lift at its top;
    # a monster that pressed a door or crossed a lift line would change that world, which this gate does not model:
    # it refuses rather than draw the wrong one
    from doomfj.movers import MoverPhase
    mps0 = MoverPhase(secs, lds, sds, mw.vertexes(args.map)).initial()
    print("  {:,} ops -> {} frames".format(ops, len(got)))

    # the oracle's mirror: the device's delivery rule (one event per poll, due once the tic clock
    # reaches it) feeding the menu's rules, and a menu frame skipping the tic
    held = {"forward": False, "back": False}
    # P10: the boot menu has no game; the skill screen's highlight boots at MEDIUM; the boot world is BOOT_SKILL's
    mode, scr, sel, skill, live = 1, 0, SKILLS.index(BOOT_MENU_SKILL), BOOT_SKILL, 0
    spawn = spawn_state(mw, args.map)
    state, rows = spawn, []
    pusedn = 1                                      # M7 P2a.2: baked 1; a world tic without use clears it
    # P9: the device's delivery and the press latch through THE oracle (doomfj.keyboard.frame_keys): the keys a
    # world frame acts on are held after its polls OR pressed during them
    from doomfj.keyboard import frame_keys
    fks = frame_keys(events, FRAMES + 1, polls=STANDALONE_POLLS, binding={K_FWD: "forward", K_BACK: "back"},
                     menu_keys=MENU_KEYS)
    for f in range(FRAMES):
        ev = set(fks[f].menu)
        held = dict(fks[f].now)
        if (args.selftest_help and mode == 1 and scr == HELP_GAME_SCR
                and ("esc" in ev or "help" in ev)):
            mode, scr, ng = 1, 0, None                  # THE HELP'S NEGATIVE CONTROL (M7 P3.4)
        else:
            mode, scr, sel, ng, live = menu_step(mode, scr, sel, ev, live)
        before = state
        if ng is not None:
            # NEW GAME: the chosen skill's level start, then this frame's tic. THE R9 CONTROL
            # starts the next skill instead -- the gate must see it.
            skill = SKILLS[(ng + 1) % len(SKILLS)] if args.selftest_skill else SKILLS[ng]
            state = spawn
            mph.reset(skill)                        # M7 P3.1: the skill's monsters, at their start
        if ng is not None:
            pusedn = 1                              # the restart block
        if mode == 0:
            # M7 P4.1: the weapon tics with the world (no fire held here) -- P4.2a: before the move, at its pose
            # M7 P6: once the player loots, the world takes this gate's fixed doors and lifts, nukage runs first, and
            # the move is the model's (`MonsterPhase.move`: pickups, blocking by things); before, step_sim's
            _keys = dict(held, turn_left=False, turn_right=False)
            if loot:
                mph.sync(phase0[0], mps0[0], mps0[2])
                dead = mph.dead_latch()
                mph.nukage(state.x, state.y, state.angle, dead=dead)
                mph.weapon(held, state.x, state.y, state.angle, dead=dead)
                state = SimState(*mph.move(_keys, state.x, state.y, state.angle, dead=dead), args.map)
            else:
                mph.weapon(held, state.x, state.y, state.angle)
                state = SimState(*mph.move(_keys, state.x, state.y, state.angle, scene=scene), args.map)
            pusedn = 0                              # this script never holds use
            _dps, _mps = mph.frame(phase0, mps0, state.x, state.y, state.angle)   # M7 P3.1 / P3.2b
            assert _dps == phase0 and _mps == mps0, "frame %d: a monster pressed a door or a lift" % f
            deaths += bool(mph.world.ws.p_dead)
            # M7 P3.2a: the frame's picture decides the next tic's seen (rendered below, per world frame)
            _seen = set()
            rm.render_wall_frame(SimState(state.x, state.y, state.angle, args.map), scene,
                                 thing_hidden=hidden[skill], thing_views=mviews(mph, state.x, state.y),
                                 thing_positions=mviews.positions(mph), seen_out=_seen,
                                 aim_things=mviews.aim_things(mph), aim_out=(_aim := [0] * 17),
                                 mobiles=mph.mobiles(),                       # M7 P5: the fireballs, the blood
                                 thing_removed=mviews.hidden(mph) if loot else None,      # M7 P6
                                 barrel_views=mviews.barrel_views(mph) if loot else None,
                                 **view_drop_kw(mph), **render_kw)            # M7 P8a: the dying view's sink
            mph.set_seen(mviews.slots_of(_seen))
            mph.set_aim(_aim)                       # M7 P4.2a: the window this picture recorded
        rows.append({"mode": mode, "scr": scr, "sel": sel, "live": live, "skill": skill, "state": state,
                     "ng": ng, "before": before, "pusedn": pusedn,
                     "mstate": {**mph.state(), **mviews.rt_state(mph), **mph.weapon_state()},
                     "skw": mph.screen_kw(), "views": mviews(mph, state.x, state.y),
                     "positions": mviews.positions(mph),
                     # M7 P5: the mobiles drawn, and the palette shown (a menu frame: PLAYPAL 0)
                     "mobiles": mph.mobiles(), "pal": mph.palette() if mode == 0 else 0,
                     # M7 P6: what the game removed, the barrels' frames
                     "removed": mviews.hidden(mph) if loot else None,
                     "bviews": mviews.barrel_views(mph) if loot else None,
                     "view_drop_kw": view_drop_kw(mph)})            # M7 P8a: the dying view's sink

    ok, menus, worlds, moved, oracle_ng, first_bad = True, 0, 0, 0, {}, None
    state_bad, state_checked = None, 0
    screens_seen = set()
    previous = None
    for f in range(min(len(got), FRAMES)):
        row = rows[f]
        state = row["state"]
        is_menu = row["mode"] == 1
        if args.selftest:
            is_menu = False                             # THE NEGATIVE CONTROL
        if is_menu:
            key = _screen_key(row["scr"], row["sel"], row["live"])
            want = screens[key]
            kind = {0: "MENU  main   ", MAIN_HELP_SCR: "MENU  main/H ", MAIN_EXIT_SCR: "MENU  main/X ",
                    MAIN_RESUME_SCR: "MENU  main/R ", HELP_MENU_SCR: "MENU  help/m ",
                    HELP_GAME_SCR: "MENU  help/g "}.get(row["scr"], "MENU  skill %d" % row["sel"])
            screens_seen.add(key)
            menus += 1
        else:
            want = gscreen.frame(bytes(rm.render_wall_frame(SimState(state.x, state.y, state.angle, args.map),
                                              scene, thing_hidden=hidden[row["skill"]],
                                              thing_views=row["views"], thing_positions=row["positions"],
                                              mobiles=row["mobiles"], thing_removed=row["removed"],
                                              barrel_views=row["bviews"], **row["view_drop_kw"],   # M7 P8a
                                              **render_kw)), **row["skw"])
            kind = "world %-7s" % SKILL_NAMES[row["skill"]]
            worlds += 1
            if row["ng"] is not None:
                oracle_ng[f] = want
        same = got[f] == want
        ok &= same
        want_state = GST.oracle_state(state.x, state.y, state.angle, row["mode"], row["scr"],
                                      row["sel"], doors0, phase0, order, (0, row["pusedn"]),
                                      monsters=row["mstate"], live=row["live"])          # P10: g_live
        if args.selftest_state and row["mode"] == 0 and f >= NEW_GAMES[0]:
            want_state["menu_scr"] ^= 1                 # THE STATE CHECK'S NEGATIVE CONTROL
        sbad = GST.diff(reads[f] if f < len(reads) else None, want_state)
        sbad.update(GST.palette_diff(pals, f, art, row["pal"]))     # M7 P5: the palette the present showed
        state_checked += 1
        pos = (_signed(state.x, 32) / 65536, _signed(state.y, 32) / 65536)
        moved += (not is_menu) and previous is not None and pos != previous
        previous = pos
        diff = sum(1 for a, b in zip(got[f], want) if a != b)
        print("  frame %2d %s (%8.3f,%8.3f)%s  %s  %s"
              % (f, kind, pos[0], pos[1], "  NEW GAME" if row["ng"] is not None else "",
                 "BYTE-EXACT" if same else "!! %d px DIFFER" % diff,
                 "state ok" if not sbad else "!! STATE: " + GST.show(sbad)), flush=True)
        if sbad:
            state_bad = f
        if not same:
            first_bad = f
        if sbad or not same:
            print("  -- stopping: once a frame is wrong the later ones compare nothing useful")
            break

    # frames 6-8 are menu frames with W HELD. If the branch ran after the sim, or the menu did not
    # skip the tic, the player would have walked through them.
    held_menu = [rows[f]["state"] for f in WITH_W_HELD]
    frozen = len({(s.x, s.y, s.angle) for s in held_menu}) == 1
    # M7 P3.4: the help with W held moves nobody either -- the frame before it is a world frame, so
    # the help frames must hold ITS pose
    held_help = [rows[f]["state"] for f in (WITH_W_HELD_HELP[0] - 1, *WITH_W_HELD_HELP)]
    help_frozen = len({(s.x, s.y, s.angle) for s in held_help}) == 1
    help_both_ways = (rows[HELP_CLOSED_TO_WORLD]["mode"] == 0
                      and rows[HELP_CLOSED_TO_WORLD - 1]["scr"] == HELP_GAME_SCR
                      and (rows[HELP_CLOSED_TO_MENU]["mode"], rows[HELP_CLOSED_TO_MENU]["scr"])
                      == (1, MAIN_HELP_SCR)
                      and rows[HELP_CLOSED_TO_MENU - 1]["scr"] == HELP_MENU_SCR)
    walked = (rows[WALKED_NEW_GAME]["before"].x, rows[WALKED_NEW_GAME]["before"].y) != (spawn.x, spawn.y)
    reset = all((rows[f]["state"].x, rows[f]["state"].y, rows[f]["state"].angle)
                == (spawn.x, spawn.y, spawn.angle) for f in NEW_GAMES)
    # the three NEW GAME frames as the oracle drew them -- distinct only if the skills can be TOLD
    # APART at the spawn, which is what makes "each frame is byte-exact" mean "each is its skill's"
    told = len(oracle_ng) == len(NEW_GAMES) and len(set(oracle_ng.values())) == len(NEW_GAMES)
    # M8 (E1M2: nothing that differs by skill is in view at the spawn -- every skill's NEW GAME frame is the same
    # picture): the skills are told apart by the BINARY'S OWN skill cell instead -- `g_skill` read at each NEW GAME frame
    # must be that frame's skill, and the three pairwise distinct. E1M1 tells them apart by the picture, as before.
    told_by = "the picture" if told else None
    if not told:
        _gs = [(reads[f] or {}).get("g_skill") if f < len(reads) else None for f in NEW_GAMES]
        if (None not in _gs and _gs == [SKILLS.index(rows[f]["skill"]) for f in NEW_GAMES]   # the cell: SKILLS.index
                and len(set(_gs)) == len(NEW_GAMES)):
            told, told_by = True, "the binary's g_skill cell %s" % _gs
        else:
            told_by = "neither: the pictures are equal and g_skill read %s at the NEW GAME frames (want %s)" % (
                _gs, [SKILLS.index(rows[f]["skill"]) for f in NEW_GAMES])
    print("")
    print("  CONTROL: menu frames %d, world frames %d, frames that moved the player %d"
          % (menus, worlds, moved))
    print("  CONTROL: the player did NOT move during the %d menu frames with W held: %s"
          % (len(WITH_W_HELD), "ok" if frozen else "!! IT MOVED"))
    print("  CONTROL: the screens shown: main menu %s, the skill screen at highlights %s of %d"
          % ("yes" if (0, None, 0) in screens_seen else "!! no",
             sorted(k for m, k, _l in screens_seen if m == 1), len(SKILLS)))
    print("  CONTROL (P3.4): the main menu on HELP %s, the help from the menu %s, from the world %s"
          % tuple("yes" if any(k[0] == s for k in screens_seen) else "!! no"
                  for s in (MAIN_HELP_SCR, HELP_MENU_SCR, HELP_GAME_SCR)))
    print("  CONTROL (P10): the main menu's pictures without a game %s, with one %s, RESUME highlighted %s"
          % tuple("yes" if want <= screens_seen else "!! no -- missing %s" % sorted(want - screens_seen)
                  for want in ({(m, None, 0) for m in _MAIN}, {(m, None, 1) for m in _MAIN},
                               {(MAIN_RESUME_SCR, None, 1)})))
    print("  CONTROL (P3.4): the player did NOT move during the %d help frames with W held: %s"
          % (len(WITH_W_HELD_HELP), "ok" if help_frozen else "!! IT MOVED"))
    print("  CONTROL (P3.4): the help closed back to the world (frame %d) and to the main menu on "
          "HELP (frame %d): %s" % (HELP_CLOSED_TO_WORLD, HELP_CLOSED_TO_MENU,
                                  "yes" if help_both_ways else "!! no"))
    print("  CONTROL: the first NEW GAME found the player walked away (%s), and every NEW GAME "
          "frame is the spawn view (%s)" % ("yes" if walked else "!! no", "yes" if reset else "!! no"))
    print("  CONTROL: the three skills' NEW GAME frames are told apart: %s"
          % (("yes, by " + told_by) if told else "!! no -- the skills cannot be told apart here: %s" % told_by))
    print("  CONTROL: distinct pictures: %d of %d" % (len(set(got[:FRAMES])), min(len(got), FRAMES)))
    print("  CONTROL: every frame's STATE (view, mode, menu_scr, menu_sel, g_live, every door's cells) "
          "equals the oracle's: %s"
          % ("yes, %d frames" % state_checked if state_bad is None and state_checked == FRAMES
             else "!! no -- frame %s" % state_bad if state_bad is not None
             else "!! only %d of %d frames were checked" % (state_checked, FRAMES)))
    vacuous = (menus < 2 or worlds < 2 or moved < 2 or not frozen or not walked or not reset
               or screens_seen != ALL_SCREENS or not told or not help_frozen or not help_both_ways)
    if vacuous and not (args.selftest or args.selftest_skill or args.selftest_help):
        print("  !! VACUOUS -- this script does not exercise the menu machine")

    print("  M7 P7: the mirror's player died on %d frames -- %s"
          % (deaths, "none, as this walk expects" if not deaths else "!! a death: this walk expects none"))
    # P9: THE HALT. The program presents exactly FRAMES frames and then ENDS by looping (enter on EXIT in frame
    # HALT_FRAME); the oracle's menu, stepped one more frame, must say the same (MENU_HALTED). The R9 control
    # makes the oracle ignore that enter: then it expects a frame the program never presents.
    from flipjump.interpreter import _fjcore as _core
    _m, _s, _sel, _ng, _live = menu_step(mode, scr, sel, set(fks[HALT_FRAME].menu) if HALT_FRAME < len(fks)
                                         else set(), live)
    if args.selftest_exit and _s == MENU_HALTED:
        _s = MAIN_EXIT_SCR                              # THE EXIT'S NEGATIVE CONTROL
    halted = causes == [_core.TERM_LOOPING] and len(got) == FRAMES
    oracle_halts = _s == MENU_HALTED
    print("  P9 HALT: the program %s after %d frames (cause %s); the oracle %s at frame %d"
          % ("HALTED" if halted else "did NOT halt", len(got), causes, "halts" if oracle_halts else "does NOT halt",
             HALT_FRAME))
    ok = ok and not vacuous and len(got) >= FRAMES and not deaths and halted and oracle_halts
    state_ok = state_bad is None and state_checked == FRAMES
    print("")
    if args.selftest_state:
        # rejected for the RIGHT reason: by the STATE check, on the first NEW GAME frame, whose
        # picture is right -- the mutation is one no world frame can show
        caught = state_bad == NEW_GAMES[0] and first_bad is None
        print("SELFTEST (the oracle expects the skill screen's menu_scr in the world): "
              + ("PASS -- the state check rejected frame %d, where it must, with its picture exact"
                 % NEW_GAMES[0] if caught else
                 "FAIL -- " + ("the gate did not notice" if state_bad is None else
                               "state %s, pixels %s" % (state_bad, first_bad))))
        return 0 if caught else 1
    if args.selftest or args.selftest_skill or args.selftest_help:
        # rejected for the RIGHT reason: the first wrong frame is the first one the mutation moves
        # (frame 0 is a menu frame; the first NEW GAME is the first frame drawn at a wrong skill;
        # M7 P3.4: the frame esc leaves the world's help is the first the wrong close moves)
        expect = (0 if args.selftest else NEW_GAMES[0] if args.selftest_skill
                  else HELP_CLOSED_TO_WORLD)
        caught = first_bad == expect
        print("SELFTEST (%s): " % ("every frame claimed to be a world frame" if args.selftest else
                                   "the oracle starts the next skill at every NEW GAME"
                                   if args.selftest_skill else
                                   "the oracle closes the world's help to the main menu")
              + ("PASS -- the gate rejected it at frame %d, where it must" % expect if caught else
                 "FAIL -- " + ("the gate did not notice" if first_bad is None else
                               "it failed at frame %d, not %d" % (first_bad, expect))))
        return 0 if caught else 1
    print("M3 GATE: " + ("PASS -- byte- and state-exact on all %d frames" % FRAMES
                         if ok and state_ok else "FAIL"))
    return 0 if ok and state_ok else 1


if __name__ == "__main__":
    sys.exit(main())
