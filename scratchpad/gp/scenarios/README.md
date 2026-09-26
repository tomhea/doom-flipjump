# Combat scenario set v2 -- FROZEN

`combat_scenarios_v2.json` is the set the 22M cap (CAP-22, `docs/plan-gameplay.md` section 9; D1
in section 11) is measured on: **11 runs x 100 frames, skill hard (46 monsters), one tic per frame
(D4)**.

**Status: FROZEN, with the owner's approval of the set**, recorded once in the set as
`owner_approval` and never re-stamped: on 2026-09-26, to the recommendation "plan a v2 [...] then
freeze v2 and its baseline", the owner answered "I agree with you on 1,2,3" (`docs/plan-gameplay.md`
section 11, D2).
- The owner's freeze was at git head `3688fa4`: the model with K = 6, strafe, and DOOM's diagonal aim
  box. Since then the set has been re-frozen only for CHECKER changes (PR #88 review rounds 2 and
  3); each re-freeze names its reviewer and reproduced every recorded result. The records are
  `freeze` (the latest) and `freeze_history`.
- The keys hash is `94d0e3c7cb37d580`, unchanged by every re-freeze.
- 20 files are hashed: the model, the census wiring and sprite art, every doomfj module the replay
  imports, and the planner.
- The frozen B0 was measured on these exact keys.

`--validate` checks all of this (section "The freeze" below). After the freeze, a changed model,
census or planner file makes `--validate` FAIL. What happens next depends on what changed (the
same rule as `docs/handoff-gameplay.md` section 1):
- a pure refactor of a hashed model or census file: `--rehash "<reason>"` re-records the hashes,
  only while the replay still reproduces every frozen pose, digest and drawn population
  (F1/F3/F4/F5 hold) AND the checker (`scenarios_v2.py`) is unchanged; each rehash is logged in
  `rehash_log`;
- a CHECKER change (`scenarios_v2.py` itself): `--freeze --approver "<its reviewer>"
  --approval-record "<where>"`, only when the re-plan gives identical keys AND the current code
  reproduces every recorded pose, digest and drawn population (F1/F3/F4/F5) -- a reviewable event.
  The owner's approval of the set (`owner_approval`) is never re-stamped; the previous freeze record
  goes to `freeze_history`;
- a BEHAVIOUR change (anything that moves a replay: a rule, a fix, a picture rule): a NEW VERSION in
  a new file -- `--plan --file <new>` (the planner refuses a frozen file), B0 re-measured on it
  (`b0_scenarios.py --file <new>`), then `--freeze --file <new> --approver "the owner"` with the
  owner's words (a first freeze refuses any other approver).

The refusals are `--selftest` controls: R1 the untouched set is accepted with nothing to re-record;
the rehash refuses R2 a behaviour change (strafe 13 -> 12) and R3 a checker change; the re-freeze
refuses R4 a picture-rule change (DEG_SOFT_MON 4 -> 2); R5 a clean re-freeze keeps the owner's
approval and names its own approver; R6 a first freeze by anyone but the owner is refused; R7
`--plan` refuses the frozen file.

**Superseded:** `combat_scenarios_v1.json` and its logs are v1, a DRAFT planned with K = 3 and no
strafe. v1 no longer replays on this model.

## What a run is

Each run starts from a CHECKPOINT (D2), which is the level's START state plus an injected part:
- the start state: monsters asleep at their spawns, doors shut, nothing taken, the start inventory
  (pistol, 50 bullets, 100 health);
- injected: the player's pose, and for the aftermath run three corpses (`setup.corpses`).

Then come 100 frames of keys, planned on the gameplay model by an autopilot and frozen. The
checkpoints are v1's ten, spread over the level's progression regions (`scenarios.py --regions`):
- the doors region the player starts in (R0);
- behind the two lifts (R2);
- behind the blue-key doors (R3).

No run rides a lift or opens a key door.

| run | region | sector | start (map units) | style | why |
|---|---|---|---|---|---|
| R0-west-hall | R0 | 150 | (300, 338) | fight | the opening fight: the sector-17 ambush trio (2 zombiemen, an imp) at 450-570 units |
| **R0-aftermath** | R0 | 17 | (700, 380) | collect | **AFTERMATH**: the same trio injected as corpses at their spawns (the zombiemen's clips dropped); the player stands among them, 70-130 units away |
| R0-south-hall | R0 | 57 | (616, -640) | collect | 11 pickups; shotgun guys at 264 and 504; the imps of sector 106 |
| R0-imp-court | R0 | 12 | (640, 812) | fight | 3 imps and a shotgun guy, 3 barrels; the sector-48 door is one cell away |
| R0-northwest | R0 | 135 | (252, 1474) | fight | 2 demons, a shotgun guy, zombiemen (mostly ambush) |
| R0-courtyard | R0 | 18 | (1424, 732) | collect | the tall courtyard: sky, imps across the drop |
| R2-barrel-hall | R2 | 134 | (2150, -520) | fight | 16 barrels with 3 shotgun guys, 2 imps, 2 demons and the spectre |
| R2-spectre-corridor | R2 | 102 | (1588, -492) | fight | a demon at 278, a shotgun guy at 226, the spectre's corridor |
| R2-east-yard | R2 | 15 | (2052, 680) | fight (brawl) | two imps at 190 and 350; fought inside claw reach, which gives the set its melee |
| R3-west | R3 | 86 | (-120, 1768) | collect | two of the room's four shotgun guys; the item closets' doors (sectors 78-81) |
| R3-mid | R3 | 87 | (400, 1856) | explore | three shotgun guys; three closet doors 10-11 cells away |

## How the keys were made (`scenarios_v2.py --plan`)

The autopilot plays the MODEL (`doomfj.world` and `doomfj.combat` at 3688fa4), frame by frame.

**Fight.**
- The target is a barrel with an awake monster beside it; otherwise the weakest monster it can
  see, awake ones first.
- It turns onto the target and fires only while the weapon is READY. Each pistol shot is DOOM's
  accurate first shot.
- It holds its bearing until the shot leaves: 4 tics after the trigger for the pistol, 3 for the
  shotgun.
- It keeps its distance band with forward and back, and strafes on every other fight frame,
  switching sides every 6-10 tics.

**Dodge.** When a fireball will pass within 30 units in the next 24 tics, it strafes out of the
fireball's line, provided that step moves. This applies in any mode.

**Tour.** Movement is omni-directional: the eight directions that forward, back and strafe make.
The destination depends on the style:
- `fight` goes to the nearest living monster;
- `collect` goes to items (drops included), then to doors, then to monsters;
- `explore` goes to doors first.

A closed plain door is opened by walking into its use box and pressing use.

**Rules.**
- It never uses a key door's box or the exit's box.
- It never strafes on a use frame.
- It never presses a movement key the model would refuse.

**Survival.** The first parameter set whose whole run survives is kept: ten runs use `aggressive`,
and the east yard uses `brawl`. The planner is deterministic: `--freeze` re-planned all 11 runs and
got identical keys.

## Validation (`scenarios_v2.py --validate`, MEASURED 2026-09-26: VALIDATE PASS, 85 s)

| run | hp | kills | hits | mon. hitscan | melee | fireballs | pickups | doors | move key | strafe | dodges | awake DRAWN | awake geometric | corpse drawn |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R0-west-hall | 100 | 2 | 4 | 0 | 0 | 0 | 0 | 0 | 84% | 78% | 0 | 98% | 98% | 28% |
| R0-aftermath | 104 | 0 | 0 | 0 | 0 | 0 | 6 | 1 | 95% | 51% | 0 | 41% | 41% | 42% |
| R0-south-hall | 100 | 0 | 2 | 6 | 0 | 1 | 5 | 0 | 100% | 58% | 0 | 74% | 75% | 0% |
| R0-imp-court | 55 | 1 | 6 | 3 | 0 | 4 | 2 | 1 | 93% | 78% | 6 | 84% | 87% | 0% |
| R0-northwest | 42 | 1 | 4 | 5 | 1 | 0 | 0 | 0 | 79% | 79% | 0 | 95% | 95% | 43% |
| R0-courtyard | 94 | 0 | 2 | 3 | 0 | 3 | 0 | 0 | 76% | 50% | 2 | 82% | 87% | 0% |
| R2-barrel-hall | 35 | 2 | 11 | 6 | 0 | 0 | 1 | 0 | 88% | 74% | 0 | 86% | 86% | 28% |
| R2-spectre-corridor | 100 | 0 | 4 | 3 | 0 | 1 | 0 | 0 | 84% | 79% | 0 | 99% | 99% | 0% |
| R2-east-yard | 88 | 0 | 0 | 3 | 1 | 5 | 0 | 0 | 95% | 71% | 19 | 66% | 66% | 0% |
| R3-west | 100 | 1 | 2 | 3 | 0 | 0 | 1 | 2 | 83% | 65% | 0 | 59% | 61% | 9% |
| R3-mid | 91 | 1 | 3 | 3 | 0 | 0 | 1 | 0 | 86% | 80% | 0 | 77% | 84% | 14% |

| criterion | result |
|---|---|
| every run survives | PASS: 11 runs, lowest end health 35 |
| >= 30% of frames have an awake monster DRAWN | PASS: 861/1100 = 78.3% |
| >= 8 monsters killed | PASS: **8** (and 5 barrels exploded) |
| all three monster attack kinds | PASS: hitscan 35, melee 2, fireball 14 |
| >= 6 pickups | PASS: 16 |
| >= 3 doors opened by the player | PASS: 4 (aftermath door 0, imp court door 2, R3-west doors 7 and 8); monsters opened 1 |
| >= 50% of frames carry a movement key | PASS: 963/1100 = **87.5%** (strafe on 763 = 69.4%) |
| every run moves on >= 60% of its movement frames | PASS: every run 100% |
| >= 50% of the frames with an awake monster drawn carry strafe | PASS: 604/861 = 70.2% |
| >= 1 fireball dodge | PASS: 27 dodge frames of 30 frames with a fireball threat |
| aftermath: >= 3 corpses within 160 units at the start, one drawn on frame 0, corpses drawn on >= 20% of its frames | PASS: 3 corpses, 2 drawn on frame 0, drawn on 42/100 |
| no run uses the exit | PASS |
| B0's injected pose lands on the model's pose | PASS: 0 camera partings; door states apart on 1 frame |

**"Drawn"** comes from the census wiring (`census_lib`, S5). Each frame is rendered on the replay's
own World with the D3 rules as decided (census.py's `rec` picture), and a thing is drawn when it
claimed at least one column. The geometric test (the box projects on screen and a 2D line of sight
reaches it) is the second column.

**Population per frame** (1,100 frames):

| per frame | mean | p50 | p80 | p99 | max |
|---|---|---|---|---|---|
| awake monsters | 5.89 | 6 | 9 | 14 | 14 |
| monsters DRAWN | 1.89 | 2 | 3 | 5 | 5 |
| awake monsters DRAWN | 1.71 | 2 | 3 | 5 | 5 |
| monsters in view (geometric) | 2.33 | 2 | 3 | 7 | 8 |
| awake in view (geometric) | 2.09 | 2 | 3 | 6 | 7 |
| corpses DRAWN | 0.19 | 0 | 0 | 2 | 2 |
| corpses in view (geometric) | 0.22 | 0 | 0 | 2 | 3 |
| drops DRAWN | 0.05 | 0 | 0 | 1 | 1 |
| fireballs alive | 0.26 | 0 | 0 | 4 | 4 |
| fireballs DRAWN | 0.00 | 0 | 0 | 0 | 0 |
| puffs and blood DRAWN | 0.24 | 0 | 1 | 1 | 2 |
| barrels DRAWN | 0.75 | 0 | 1 | 10 | 12 |
| K deferrals (K = 6) | 0.00 | 0 | 0 | 0 | 1 |
| heavy actions run | 1.83 | 2 | 3 | 6 | 6 |

## B0 v2 (`b0_scenarios.py`, MEASURED on blocked27, sha256 38b09a7331f4f52b)

Measured with `python scratchpad/gp/b0_scenarios.py --file scratchpad/gp/scenarios/combat_scenarios_v2.json --pixel-every 1 --proxy --json scratchpad/gp/scenarios/b0_v2.json`
(`b0_v2.log`). Startup plus menu is 518,147 ops, exact. **B0 OK**: every run is state-exact on
100/100 frames and byte-exact on 100/100 pictures.

| run | avg ops/frame (exact) | p50 | p80 | max (+/-2^18) | strafe-only frames |
|---|---|---|---|---|---|
| R0-west-hall | 22,018,124 | 22,020,096 | 23,330,816 | 25,427,968 | 50 |
| R0-aftermath | 20,857,004 | 21,233,664 | 22,806,528 | 28,049,408 | 12 |
| R0-south-hall | 16,034,555 | 16,777,216 | 18,087,936 | 19,660,800 | 16 |
| R0-imp-court | 18,894,196 | 18,350,080 | 20,971,520 | 25,427,968 | 20 |
| R0-northwest | 11,720,721 | 12,058,624 | 12,582,912 | 13,369,344 | 72 |
| R0-courtyard | 19,424,847 | 19,660,800 | 20,709,376 | 25,165,824 | 17 |
| R2-barrel-hall | 15,680,855 | 15,728,640 | 16,252,928 | 17,039,360 | 36 |
| R2-spectre-corridor | 13,324,683 | 13,369,344 | 13,893,632 | 14,942,208 | 59 |
| R2-east-yard | 16,916,780 | 17,563,648 | 19,398,656 | 23,592,960 | 14 |
| R3-west | 9,742,733 | 9,699,328 | 11,796,480 | 18,612,224 | 31 |
| R3-mid | 12,449,212 | 12,582,912 | 12,845,056 | 14,942,208 | 63 |

- **B0 BINDING (mean + p80)/2 = 17,760,774 ops/frame.** The mean is 16,096,701 and the p80 run is
  R0-courtyard at 19,424,847. The headroom to 22M is 4,239,226.
- The worst single frame is 28,049,408 (+/- 2^18), in R0-aftermath.
- v1's B0 was 14,972,920. It is not comparable: that set moved on 29% of frames against v2's
  87.5%, used another autopilot and ran on another model.

**How the route stays comparable.** At every frame start, b0 writes two things:
- **The pose from which blocked27's own tic lands exactly where the model did**
  (`scenarios_v2.b0_injection`): the pre-tic angle, and the model's landing minus blocked27's
  forward or back step (or the landing itself when the frame has no forward or back key). With no
  strafe and nothing in the way, this is v1's injection, the model's own pre-tic pose. It also
  absorbs strafe (blocked27 has none) and any step a solid thing refused (blocked27 walks through
  things). So v2 needs no rule against thing-blocked steps.
- **The model's doors, all four cells per door.** A door a monster opens in the model then opens
  in blocked27 one frame later instead of never. That happens on 1 frame of the set.

Forward, back, turn and use arrive as real key events. Strafe, fire and the weapon keys are not
delivered, because blocked27 reads none of them.

**What B0 measures.** It is blocked27's cost of drawing the set's camera path, with its own door
tic, player tic and collision, in its own world:
- monsters at their spawns in their spawn frames, the aftermath's trio included;
- every pickup present;
- no fireballs, corpses or effects.

**The strafe undercount (MEASURED, `--proxy`).**
- On a strafe-only frame (strafe with no forward or back), blocked27 does not move, so its
  collision tic does not run. The gameplay binary's will.
- `--proxy` re-runs every run with each of the 390 strafe-only frames given a forward step into
  the same landing: same pose, identical pictures, state-exact.
- The difference is exact: **+329,289,962 ops = 844,333 per strafe-only frame** (per run
  483,811..2,316,018).
- **Binding 18,107,313, so B0 undercounts the binding by 346,539 ops/frame.**
- The forward step is a proxy for the side step: the same collision code, the same destination
  box, but a 16-unit step against a 13-unit one.

## The freeze (what `--validate` checks)

- **F1**: the status is FROZEN and `owner_approval` records the owner, a date and the owner's
  words (2026-09-26 for v2); its detail also names the latest freeze's kind and approver.
- **F2**: every recorded file hash matches (20 files).
- **F3**: the replay reproduces every frozen per-frame pose and every run's final digest.
- **F4**: the drawn and geometric population reproduces frame by frame.
- **F5**: the B0 record is present and was measured on these keys (`keys_sha`).

The file also records:
- `owner_approval`, with the git head of the owner's freeze (`3688fa4`);
- `freeze`, the latest freeze: its kind (owner freeze or checker re-freeze), approver, approval
  record, git head, `files_not_at_head` and the rule; `freeze_history`, every earlier freeze record;
  `rehash_log`, every rehash;
- the B0 record: the binary and label-table sha256, the driver hash, the command, per-run numbers
  and the undercount.

## R9 controls

`scenarios_v2.py --selftest` PASSES on the frozen set (`selftest_r3.log`; the first run was
`selftest_v2.log`). It requires:
- the freeze-rule controls R1-R7 (section "The freeze" above: what the rehash, the re-freeze and
  the planner refuse);
- the true set passes;
- no fire key FAILS the kills floor;
- no strafe key FAILS strafe-while-fighting and the dodge floor;
- no movement key FAILS the movement floor and the "moves on >= 60%" check (vacuity);
- a silent set facing away FAILS the awake-DRAWN floor (26.7%);
- one key changed FAILS F3; an altered hash FAILS F2; status PLANNED FAILS F1; a removed B0 record
  FAILS F5; one altered drawn count FAILS F4;
- a set WITHOUT the aftermath run FAILS the aftermath criterion, and so does the aftermath with its
  corpses removed;
- no use key FAILS the doors floor;
- synthetic metrics FAIL survival, attack kinds, pickups, kills and the B0 camera criterion;
- the planner is deterministic;
- an injection one unit off parts the camera on every moving frame (84/84).

The movement floor is not a strafe test: without strafe, forward and back alone still carry
573/1100 = 52.1% of frames. The movement floor's own control is "no movement key".

`b0_scenarios.py --selftest` PASSES (`b0_selftest_v2.log`). It requires:
- gamespeed run 0, with every door written each frame, reproduces the recorded 2,100,441,242 ops
  exactly;
- an expectation one turn off is rejected on 100/100 frames;
- startup plus menu is 518,147;
- an oracle without `sky` is rejected on sky frames;
- a door written open takes effect, state- and pixel-exact;
- the strafe proxy draws identical pictures and costs more ops (+26,672,241 over 26 strafe-only
  frames).

## Reproduce

```
python scratchpad/gp/scenarios_v2.py --validate    # replay + census: criteria and the freeze (~90 s)
python scratchpad/gp/scenarios_v2.py --selftest    # R9 (~5 min)
python scratchpad/gp/b0_scenarios.py --file scratchpad/gp/scenarios/combat_scenarios_v2.json --pixel-every 1 --proxy --json OUT.json
python scratchpad/gp/b0_scenarios.py --selftest    # the driver's R9
```

The two `b0_scenarios.py` commands run the game binary under the binary lock. `--plan` refuses a
frozen file: plan a v3 into a new file. `--freeze` on the frozen file is the checker re-freeze of
the rule above, and needs `--approver` and `--approval-record`.

## Notes for the owner

1. **Kills sit exactly on the floor: 8.** At skill hard, E1M1's two shotgun pickups are
   easy-skill only, so the set fights with the pistol: about one shot every 20 tics, 4-5 per run.
   The only shotgun source is a dead shotgun guy's drop, and the set fires no shotgun shot.
2. **Melee comes from two runs** (the brawl in the east yard, and the northwest), one attack each.
3. **Fireballs are never DRAWN** (0 of 1,100 frames), although 150 frames have one in flight and
   the geometric test sees one on 36 frames. The census draws projectiles at their leaf's floor
   height (a stand-in, per `census_lib`'s docstring), and in this set they fly over lower floors
   or far away. So the set prices a fireball's flight, not its sprite.
4. **Corpses** are drawn on 42% of the aftermath's frames. The decided D3 picture degrades a
   corpse beyond about 130 units in a room full of things, so the aftermath criterion asks for
   20%, not 50%.
5. The heaviest runs in B0 are R0-west-hall (22.0M) and R0-aftermath (20.9M, worst frame 28.0M).
   Both walk the opening area of the level.
