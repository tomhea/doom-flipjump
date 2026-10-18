# The episode: a binary for every level, E1M1..E1M9 (M8, owner 2026-10-19)

**The owner's goal, verbatim:** "My definite goal is creating a binary for each of the e1m1-e1m9 levels." Each level
"should have enough tests, and should go a playthrough/gameplay phase, as e1m1-e1m2 went through"; "all the levels
should learn from each other mistakes"; "In the end there should be a final creator that build the final e1m1-e1m9";
"new levels shouldn't modify how e1m1 is created, but if its for the best, is should affect it"; "In the end ill run a
final build all 9, and all should go through tests and auto-gameplay and pass." And: "try to make the other levels as
optimized as e1m1, when possible." The wave plan below was approved ("Good plan. I agree.", 2026-10-19).

This supersedes the 2026-09-25 "1-3 levels" goal. `docs/level-pipeline.md` is the per-level procedure; this file is
the plan across the episode. Status lives in section 9.

## 1. The maps (Freedoom phase 1, `assets/freedoom1.wad`; survey 2026-10-19 at b64ef94d)

| map | linedefs | sectors | segs | subsectors | things | segs / E1M2 | status |
|---|---|---|---|---|---|---|---|
| E1M1 | 1,175 | 182 | 2,057 | 682 | 293 | 0.56 | SHIPPED (blocked63) |
| E1M2 | 2,290 | 380 | 3,650 | 1,104 | 356 | 1.00 | SHIPPED (r4; 62.19% of 2^27, span 92.06%) |
| E1M3 | 2,169 | 330 | 2,981 | 821 | 382 | 0.82 | wave 1 |
| E1M4 | 2,283 | 274 | 3,502 | 1,202 | 378 | 0.96 | wave 1 |
| E1M5 | 1,215 | 214 | 1,933 | 501 | 364 | 0.53 | wave 1 |
| E1M6 | 2,818 | 395 | 4,409 | 1,398 | 490 | 1.21 | wave 3 |
| E1M7 | 4,337 | 699 | 6,947 | 2,064 | 714 | **1.90** | wave 3 (size / RAM risk) |
| E1M8 | 930 | 97 | 1,796 | 627 | 123 | 0.49 | wave 2 |
| E1M9 | 1,935 | 297 | 3,164 | 913 | 368 | 0.87 | wave 2 |

`python scripts/level_survey.py --wad assets/freedoom1.wad --matrix E1M2 E1M3 E1M4 E1M5 E1M6 E1M7 E1M8 E1M9` is the
source of every row in section 2; re-run it after each feature lands (2 s a map).

## 2. The work, clustered across maps (each built ONCE, for every map that needs it)

| # | cluster | maps | notes |
|---|---|---|---|
| C1 | runtime ids past 254 (things + pools + drops; `docs/f1-runtime-ids.md` A1, 12-bit list cells) | E1M3 341, E1M4 345, E1M5 370; E1M6 / E1M7 / E1M9 refused | IN PROGRESS (branch `m8-runtime-ids`); the critical path of wave 1 |
| C2 | wide thing lists (runtime things past `LIST_MAX_THINGS`) | E1M6 345, E1M7 337 | the 12-bit wide-cell lists parked 2026-09-25 (`c313c97`, backup bundle); may fold into C1 |
| C3 | doors: 32 D1 blue stay, 33 D1 red stay, 61 SR open stay, 75 WR close, 46 GR (shot), blaze 105 / 107 / 112 / 114 / 133; door 102's closing box | E1M3, E1M4, E1M5, E1M6, E1M7, E1M9 | the door kinds of L2 extended; "door behind special 32" WRONG on E1M3 |
| C4 | floors, lifts, stairs, lights: 20 / 22 floor up + texture, 36 floor down to 8 above, 7 S1 stairs 8, 53 perpetual lift, 138 SR light 255; door-lift / lift-lift lines | E1M3, E1M4, E1M6, E1M7 | the movers of L3 extended |
| C5 | monster teleports 126 WR, 125 W1 | E1M4, E1M5, E1M6, E1M7 | the WR teleport of L4, for monsters |
| C6 | pickups: 2046 box of rockets, 2024 partial invisibility, 2025 radiation suit, 2004 PLASMA RIFLE | 6 / 4 / 4 / 2 maps | the plasma rifle is a new weapon and projectile; invisibility changes how monsters aim |
| C7 | decorations 22, 30, 31, 32, 36, 42, 44, 45, 46, 53, 55, 56, 57, 59, 62, 63 | E1M5, E1M6, E1M7, E1M8, E1M9 | sprites from the asset wad; solid or not per DOOM |
| C8 | NEW MONSTERS: 3003 (the Baron), 3006 (the lost soul) | E1M8 (4 Barons); E1M6, E1M7 | each a state machine, an attack and sprites, in both mirrors; E1M8's boss death opens the exit (tag 666 -- not in the survey yet: add it) |
| C9 | exits: 51 S1 secret exit, 52 W1 exit | E1M3, E1M8 | LEVEL COMPLETE exists; these line kinds do not |
| C10 | no barrels (barrelcode asserts one) | E1M5, E1M8 | a refusal to lift, not a feature |
| C11 | widths: n_tsv past 3 nibbles (E1M7: 4,183 two-sided segs); E1M9's "section doors / movers" refusal | E1M7, E1M9 | |
| C12 | the noise flood's sound-block lines at scale | E1M6 114, E1M7 180 | done at L5; watch its cost |

A feature lands in BOTH mirrors (the fj emitter and the oracle), behind `config.MAP_CONFIG` when E1M1 or E1M2 lack
it, with a tests/fj test RUN in fj and a negative control (R9).

## 3. Waves

- **Wave 1: E1M3, E1M4, E1M5.** C1, then C3 / C4 / C5 / C6 / C7 / C9 / C10 for those maps. E1M5 (E1M1's size) is
  likely first.
- **Wave 2: E1M8, E1M9.** C8 (the Baron and the boss trigger), C11 for E1M9, the rest of C3 / C6.
- **Wave 3: E1M6, E1M7.** C2, C8 (the lost soul), C11 for E1M7. **E1M7 first gets a FEASIBILITY PROBE** as soon
  as C1 lands: `emit_check.py E1M7` with stand-ins, measuring its emission (share of 2^27, span, peak RAM). E1M2 is
  already at 92% of the span and peaked at 17.2 GB on this 15.6 GB box; E1M7 is 1.9x E1M2. If it cannot fit or cannot
  build here, that is the owner's call (size work, a wider word, a bigger machine), raised the day it is known.

Feature agents work across waves where a cluster spans them; a level enters the build queue when its survey is clean.

## 4. A level, start to ship (the per-level contract)

1. **Survey clean** (`level_survey.py`): no REFUSED / OVER / MISSING / WRONG row left; each WARN explained.
2. **emit_check** with asserts ON (never `python -O`), no stand-in.
3. **The generated scenario sets** (`docs/level-pipeline.md` 4): the gate roles (`scenarios/<map>/gates.json`), the
   combat set (`combat_scenarios_<map>_v1.json`), the gamespeed tours -- approved, then frozen.
4. **The fast build** (`build_labeled.py ... --map`), spread 2 when its pool fits, else 1 (E1M2: 1).
5. **The gates**, each solo: `p2a`, `m2_std_gate`, `m3_gate`, `hurt`, `fight`, `die`, B0 on its combat set,
   `gamespeed_trail --record`, `gamespeed` (binding speed <= 22M; the size recorded), the playthrough gate (5), and
   the map's own feature tests (tests/fj). Every frame byte- and state-exact against the oracle.
6. **The playtest** (as `docs/playtest-e1m2.md`): the binary itself, played with the play tool, start to exit;
   written down: what works, what looks wrong, what blocks. Every finding is fixed (both mirrors) or recorded as a
   decision; then rebuild and re-gate.
7. **The speed pass** ("as optimized as E1M1"): a profile of the level's own play gives its own pin-heat list
   (E1M1's `heat_blocked27_p10` came from E1M1's profile); spread 2 where the pool fits; msframe class S A/B for any
   cut. Generic cuts (shared emitter code) ship for every map at once.
8. **Ship**: msframe baseline `shipped_<map>`, a byte-identical rebuild, `docs/ship-gate.md` section 5 (one block a
   map), evidence in `docs/ship-evidence/<map>_*.log`, a PR.

## 5. The playthrough tool and the auto-gameplay gate

- The play tool (written for the E1M2 playtest: drives `fj --run` with a key log, closed-loop steering on the
  binary's own pose, warp and god cheats through cell writes) moves into the repo as `scripts/play.py`.
- **A route planner** (`scripts/level_route.py`): from the map's start to its exit -- the keys in order, the doors and
  switches the route needs -- over the map's own geometry; a waypoint list per skill.
- **The auto-gameplay gate** (`scratchpad/gp/playthrough_gate.py`): plays the route on the binary (steering on its
  pose, fighting what blocks the path), checks every frame byte- and state-exact against the oracle stepping the
  same keys, and passes when LEVEL COMPLETE shows. Part of every level's gate set and of the final creator.

## 6. Learning across levels

`docs/level-lessons.md` holds every mistake a level found, one line each, with WHERE it now lives: a survey check
(caught in seconds), an emit_check refusal (minutes), or a gate (hours). A lesson that is only prose is unfinished.
Seeded from E1M2 (`docs/handoff-e1m2.md`, `docs/playtest-e1m2.md`, the CRs of #146 and #148).

## 7. E1M1 stays as it is -- unless it is for the best

Every change runs `scratchpad/cr/emit_baseline.py --check`: E1M1's emitted program identical. A change that would
improve E1M1 (a shared speed cut, a shared fix) is allowed; E1M1 then re-ships through `docs/ship-gate.md` (class S
or F) and the owner is told.

## 8. The final creator

`scripts/build_episode.py`: for E1M1..E1M9, ONE AT A TIME (rule 1): emit_check, the build (each map's recorded
command and spread), its gates, its playthrough gate, msframe against its baseline; then one report (pass / fail per
level per gate, sizes, ms/frame, hashes). Resumable: a level that passed is skipped on a re-run unless its source
changed. Expected wall time ~1.5-2 days for all nine on this machine.

## 9. Status

| date | event |
|---|---|
| 2026-10-19 | plan approved; C1 started (branch `m8-runtime-ids`); CR follow-ups #149 (branch `m8-cr149`); PR #148 (E1M2 r4 + blocked63) in CI |

## 10. Orchestration

- Worktrees: one per agent (`Documents/doom-<topic>`), branches `m8-*` from the integration branch `m8-episode`.
- **Heavy work goes through one lock**: every build, emission, gate, msframe and long tests/fj run is wrapped in
  `heavy.py NAME -- cmd` (waits for `Documents/HEAVY.lock`, takes it exclusively, releases it). Subagents count.
- The integrator merges features into `m8-episode`, runs the build queue, the gates and the playtests, and opens a PR
  per wave.
