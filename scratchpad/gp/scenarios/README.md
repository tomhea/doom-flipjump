# Combat scenario set v1 (S4) -- for the owner to review and freeze

`combat_scenarios_v1.json` is the scenario set the 22M cap (CAP-22, `docs/plan-gameplay.md` section 9;
decision D1 in section 11) is measured on: **10 runs x 100 frames, skill hard (46 monsters), one tic per frame (D4)**.
Status: **DRAFT until the owner signs it off (D2)**. After that the file is frozen: its keys, its
checkpoints and the model's code hashes do not change, and B0 is re-measured only on it.

## What a run is

Each run **starts from a checkpoint (D2)**: a player position and angle injected into E1M1's **start
state** -- monsters asleep at their spawns, doors shut, nothing taken, the start inventory (pistol,
50 bullets, 100 health). Then 100 frames of keys, planned on the gameplay model by an autopilot and
frozen. The checkpoints cover the level's progression regions (the spec mission's flood,
`scenarios.py --regions`): the doors region the player starts in (R0, 21 hard monsters), the 31
sectors behind the two lifts (R2, 16) and the 12 behind the blue-key doors (R3, 4). No run rides a
lift or opens a key door: the model has neither lifts nor a card, blocked27 has no lifts and opens
key doors without keys, so a route through one would not be comparable.

| run | region | sector | start (map units) | facing | style | why |
|---|---|---|---|---|---|---|
| R0-west-hall | R0 | 150 | (300, 338) | 0 deg | fight | the opening fight: the ambush trio of sector 17 (2 zombiemen, an imp) at 450-570 units, near the player start |
| R0-south-hall | R0 | 57 | (616, -640) | 15 deg | collect | the south hall (11 pickups): shotgun guys at 264 and 504, the imps of sector 106 at 440-900 |
| R0-imp-court | R0 | 12 | (640, 812) | 50 deg | fight | three imps at 290-460 and a shotgun guy, 3 barrels -- fireballs |
| R0-northwest | R0 | 135 | (252, 1474) | 321 deg | fight | the densest doors-region cluster: 2 demons at ~400, shotgun guy and zombiemen at 140-400 -- melee |
| R0-courtyard | R0 | 18 | (1424, 732) | 90 deg | collect | the tall courtyard (ceiling 536, 6 pickups, 2 barrels): imps at 600-950 across the drop |
| R2-barrel-hall | R2 | 134 | (2150, -520) | 74 deg | fight | behind the lifts: 16 barrels with 3 shotgun guys, 2 imps, 2 demons and the spectre in view |
| R2-spectre-corridor | R2 | 102 | (1588, -492) | 74 deg | fight | behind the lifts: a demon at 278, a shotgun guy at 226, the spectre's corridor beyond |
| R2-east-yard | R2 | 15 | (2052, 680) | 37 deg | fight | behind the lifts: two imps at 190 and 350, beside the blue-key room |
| R3-west | R3 | 86 | (-120, 1768) | 84 deg | collect | behind the blue-key doors: two of the four shotgun guys at 230-360 |
| R3-mid | R3 | 87 | (400, 1856) | 159 deg | fight | the same room from its middle: three shotgun guys at 300-560 |

## How the keys were made (`scratchpad/gp/scenarios.py --plan`)

An autopilot plays the MODEL (`doomfj.world` + `doomfj.combat`, the default geometric aim), frame by
frame, from the model's state only:
- **fight**: the target is the nearest living monster it can see within 1024 units (awake first,
  the weaker first); it turns until the aim is on a monster and fires only while the weapon is
  READY (so every pistol shot is DOOM's accurate first shot); it closes in to a keep band and backs
  off inside it, or when hurt with a monster near (no strafe key: it moves along the line it shoots);
- **tour**: with nothing to fight it walks the shortest path (a 16-unit cell graph built with the
  oracle's own `try_move`) to the nearest living monster, pressing use in plain doors' boxes;
- **pickups**: fight-first runs take an item only when there is nothing to fight, when it is within a
  step or two, or health when hurt; the three item-rich runs (style `collect`) sweep items whenever no
  awake monster is within 256 units;
- **rules**: never use in a key door's box or the exit's box; never step where a solid thing would
  refuse the step (the model blocks the player on things, blocked27 does not);
- **survival**: parameter sets from aggressive to defensive; the first whose whole run survives is
  kept (all ten kept `aggressive`).

The plan is deterministic (no randomness but the model's own seeded streams); `--selftest` S6
re-plans a checkpoint and requires the same keys. The JSON records the checkpoints, the per-frame
keys and the model's per-frame poses, the model's final digests, and the sha256 of every model file
and of the planner.

## Validation (`scenarios.py --validate`, MEASURED)

**VALIDATE PASS** (`validate_v1.log`, 3 s; re-run 2026-09-26 and identical). Per run, from the model:

| run | hp at end | kills | player hits | monster hitscan | melee | fireballs | pickups | awake in view | movement frames |
|---|---|---|---|---|---|---|---|---|---|
| R0-west-hall | 100 | 1 | 4 | 0 | 0 | 0 | 0 | 100% | 24 |
| R0-south-hall | 100 | 0 | 0 | 6 | 0 | 1 | 4 | 34% | 64 |
| R0-imp-court | 17 | 0 | 4 | 6 | 1 | 3 | 1 | 98% | 30 |
| R0-northwest | 26 | 2 | 4 | 5 | 2 | 0 | 0 | 70% | 18 |
| R0-courtyard | 52 | 0 | 5 | 3 | 2 | 3 | 0 | 91% | 36 |
| R2-barrel-hall | 79 | 1 | 5 | 3 | 1 | 0 | 0 | 95% | 19 |
| R2-spectre-corridor | 79 | 0 | 4 | 3 | 0 | 0 | 0 | 99% | 22 |
| R2-east-yard | 100 | 1 | 5 | 3 | 0 | 4 | 0 | 100% | 11 |
| R3-west | 88 | 1 | 2 | 3 | 0 | 0 | 0 | 35% | 47 |
| R3-mid | 100 | 1 | 5 | 6 | 0 | 0 | 0 | 84% | 15 |

The criteria:

| criterion | result |
|---|---|
| every run survives | PASS: 10 runs, 0 deaths (the lowest end health is 17) |
| >= 30% of frames have an awake monster in view | PASS: 806/1000 = 80.6% |
| >= 5 kills | PASS: 7 |
| all three attack kinds | PASS: hitscan 38, melee 6, fireball 11 |
| >= 3 pickups | PASS: 5 (4 of them in R0-south-hall) |
| every run moves on >= 60% of its movement frames | PASS: every run moves on 100% of them |
| no run uses the exit | PASS: 0 |
| the frozen poses and final digests replay exactly | PASS: 10/10 |

Doors: the set presses `use` 4 times, all in R3-west, and opens one plain door (sector 78). The
B0 comparability check finds 0 frames where blocked27's step parts from the model's pose, 0 where a
door state differs, and 0 where a thing blocks the player.

**Population per frame** (1,000 frames; `deferred` is the heavy actions K = 3 pushed to a later tic,
`heavy` the ones run):

| per frame | mean | p50 | p80 | p99 | max |
|---|---|---|---|---|---|
| awake monsters | 6.25 | 6 | 9 | 14 | 14 |
| monsters in view | 1.86 | 2 | 3 | 6 | 7 |
| awake and in view | 1.66 | 2 | 2 | 5 | 6 |
| corpses in view | 0.20 | 0 | 0 | 2 | 2 |
| fireballs alive | 0.16 | 0 | 0 | 3 | 4 |
| K deferrals | 0.59 | 0 | 0 | 6 | 7 |
| heavy actions run | 1.71 | 2 | 3 | 3 | 3 |

K defers something on 195 of the 1,000 frames: 85 of them in R2-barrel-hall and 81 in
R2-spectre-corridor, where the monsters behind the lifts wake together. 286 frames carry a
movement key (gamespeed's ten scripts: 865 of 1,000, MEASURED with `gamespeed.script`).

R9 (`scenarios.py --selftest`): a set with no fire key FAILS the kills criterion; with no movement
keys FAILS the movement criterion (a set with no movement frames is not a pass); silent and facing
away FAILS the awake-in-view criterion; one key changed FAILS the freeze check; synthetic deaths,
no fireballs and no pickups each FAIL their criterion; the binary mirror parts from the model when a
thing blocks and not otherwise.

"In view" is geometric: the thing's box projects onto the 160 columns from the player's view and a
2D line of sight reaches its centre. The compositor census (S5) counts what is DRAWN.

## B0 (`scratchpad/gp/b0_scenarios.py`, MEASURED on blocked27)

**B0 OK** (`b0_v1.log`, `b0_v1.json`: `python scratchpad/gp/b0_scenarios.py --pixel-every 1 --json
scratchpad/gp/scenarios/b0_v1.json`). blocked27 is sha256 38b09a7331f4f52b; startup + menu is
518,147 ops, exact and equal to the recorded calibration. Every picture was checked:

| run | avg ops/frame (exact) | p50 | p80 | max | state | pixels | parted |
|---|---|---|---|---|---|---|---|
| R0-west-hall | 23,713,071 | 23,855,104 | 24,117,248 | 25,165,824 | 100/100 | 100/100 | 0 |
| R0-south-hall | 11,832,308 | 11,534,336 | 14,155,776 | 19,398,656 | 100/100 | 100/100 | 0 |
| R0-imp-court | 18,567,350 | 19,136,512 | 19,922,944 | 21,757,952 | 100/100 | 100/100 | 0 |
| R0-northwest | 10,544,461 | 11,272,192 | 11,796,480 | 13,369,344 | 100/100 | 100/100 | 0 |
| R0-courtyard | 13,886,524 | 14,155,776 | 14,155,776 | 15,728,640 | 100/100 | 100/100 | 0 |
| R2-barrel-hall | 15,041,594 | 14,680,064 | 15,990,784 | 17,825,792 | 100/100 | 100/100 | 0 |
| R2-spectre-corridor | 12,325,891 | 13,893,632 | 15,466,496 | 16,515,072 | 100/100 | 100/100 | 0 |
| R2-east-yard | 15,814,151 | 15,990,784 | 16,515,072 | 18,087,936 | 100/100 | 100/100 | 0 |
| R3-west | 7,130,310 | 8,126,464 | 10,485,760 | 12,845,056 | 100/100 | 100/100 | 0 |
| R3-mid | 12,461,227 | 12,582,912 | 12,845,056 | 13,369,344 | 100/100 | 100/100 | 0 |

- **The binding (mean + p80)/2 is 14,972,920 ops/frame** (mean 14,131,689; the p80 run is
  R2-east-yard at 15,814,151), which leaves 7,027,080 ops/frame of headroom to 22M.
- The per-frame maximum is 25,165,824, in R0-west-hall.
- Run averages and the binding are exact (the totals are exact). The per-frame columns are +/-2^18,
  because the engine refreshes its op counter every 2^18 ops.

The driver's own R9 controls (`--selftest`, `b0_selftest_v1.log`):
- T1: gamespeed run 0, driven as a scenario, reproduces the recorded 2,100,441,242 ops to the op
  (state 100/100, pixels 10/10).
- T2: an expectation one turn off is accepted on 0/100 frames.
- T3: startup + menu measures 518,147.
- T4: the courtyard's first six frames show sky. The game oracle passes all 6, and the oracle
  without the game tier's `sky=True` is accepted on 0 of 6.

**What B0 measures.** blocked27 plays each run in TIC mode: the menu and enter as gamespeed composes
them, then 100 frames where the probe writes the model's pre-tic pose at every frame start (the
checkpoint for the first) and the movement and use keys arrive as real key events (fire and the
weapon keys are not delivered -- blocked27 has none). So each frame is blocked27's own door tic,
player tic and collision from where the model stood, and the render of where that leaves it, in
blocked27's world: monsters at their spawns in their spawn frames, every pickup present, no
fireballs, corpses or effects. Every frame's pose must equal the static oracle's step of the same
pre-pose and keys (state-exact) and sampled frames' pictures must equal the oracle's render
(byte-exact). **How the route stays comparable:** the autopilot never steps where a solid thing
would refuse the step and never uses a key door or the exit; the one remaining source of parting --
a monster opening a door in the model -- is counted per run; and because the pose is re-injected
every frame, a parting lasts one frame and never accumulates.

## Reproduce

```
python scratchpad/gp/scenarios.py --validate     # replays the frozen set on the model (3 s)
python scratchpad/gp/scenarios.py --selftest     # its R9 controls S0-S7 (12 s)
python scratchpad/gp/b0_scenarios.py --pixel-every 1 --json scratchpad/gp/scenarios/b0_v1.json
python scratchpad/gp/b0_scenarios.py --selftest  # the driver's R9 controls T1-T4
```

The two `b0_scenarios.py` commands run the game binary and take the binary lock. `--plan`
writes to `--file`, whose default is THIS set: re-plan into a new file (`--plan --file
scratchpad/gp/scenarios/replan.json`) and compare, never over the frozen one. Re-planning is
deterministic; `--selftest` S6 re-plans checkpoint 0 and requires the frozen keys.

## Open questions for the owner

1. **Movement share.** 286 of 1,000 frames carry a movement key, against 865 of 1,000 in gamespeed's
   ten scripts (both MEASURED). The autopilot stands and shoots inside its keep band, and the model
   has no strafe key. So v1 weighs collision less than a walking tour does. Keep it, or give v2 a
   floor (say 50% movement frames)?
2. **Thin margins.** Kills are 7 (the floor is 5), pickups 5 (the floor is 3, and 4 of them are in
   one run), and the whole set opens one door. One run ends at 17 hp. A model change that moves any
   trajectory fails the freeze check by design, and the keys are then re-planned as v2 with a new
   B0. Raise the floors, or accept this?
3. **Coverage.** No checkpoint is in R1 (2 sectors, 1 monster) or R4 (3 sectors, no monsters).
4. **The D2 shape.** Every run starts from the level's START state at a checkpoint: monsters asleep
   at their spawns, nothing taken. No run starts mid-fight or in an area already cleared. Is this
   D2 as intended?
5. **A heavy run.** R0-west-hall averages 23.7M ops/frame on blocked27 alone, with a maximum of
   25.2M. The binding does not see it, and D1 reports it.
6. **"In view".** The criterion is geometric; S5's census counts what is DRAWN.
7. **Freezing needs `git add -f`.** `combat_scenarios_v1.json`, `b0_v1.json` and the logs are
   gitignored (`scratchpad/**/*.json`, `scratchpad/**/*.log`).
