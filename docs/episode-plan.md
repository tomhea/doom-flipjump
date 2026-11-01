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

`scripts/build_episode.py` (2026-10-19; host tests `tests/host/test_build_episode.py`). For E1M1..E1M9 (or
`--maps E1M1 E1M2`), ONE AT A TIME, per map in section 4's order:

| step | what runs (each heavy one as `heavy.py creator --prio 8 [--build] --log <out>/logs/<map>_<step>.log -- ...`, `DOOMFJ_MAP=<map>`) | passes on |
|---|---|---|
| `emit_check` | `scripts/emit_check.py <map> --json ...` (asserts ON) | rc 0, `EMITTED in`, `asserts ON` |
| `build` | `build_labeled.py` with the map's RECORDED flags (`--build`: other agents' `--light` work waits); refused under 15 GB free disk (G8); the map's `generated_doom_<map>` directory removed after it (G8) | rc 0, `done in Ns` |
| `sha256` | in process: the binary against the recorded sha256 (a byte-identical REBUILD check when one is recorded); the census written beside it compared with the recorded one (information) | equal, or no record (a NEW binary) |
| `p2a` `m2_std` `m3` `hurt` `fight` `die` | section 4.5's gates on the built binary and its label table | rc 0 AND the gate's own PASS line |
| `b0` | `b0_scenarios.py --file <the map's combat set> --pixel-every 1 --proxy` | `B0 OK`, binding <= 22,000,000 (CAP-22) |
| `gamespeed_trail` | `--record` where the map keeps `scenarios/<map>/gamespeed.json` (E1M2; E1M1's record is `gamespeed.BINARY_ENDS`) | `TRAIL ...: PASS` |
| `gamespeed` | `--map <map> --fjm ...` | speed binding PASS; size <= the row's cap (E1M1 43%; E1M2's 62.19% WAIVED by the owner, "Size is ok") |
| `playthrough` | `scratchpad/gp/playthrough_gate.py --map --fjm --labels [--skill]` -- OPTIONAL while the script does not exist: `MISSING` + a WARNING in the report, re-tried on the next run | rc 0 |
| `feature_tests` | the map's own tests/fj files (`pytest -q`) | rc 0, `N passed`, nothing failed |
| `msframe` | `--map <map> --a <new> --against <shipped / shipped_<map>>` (alone, with a WARNING, when no baseline is saved; the plan warns when the baseline's binary is not on disk, which msframe refuses) | a median; never `B SLOWER` |

A failed `emit_check` or `build` stops its map (the rest `NOT RUN`); any other failure is recorded and the map goes on.

**The registry** (`REGISTRY`, one row a map) holds what docs/ship-gate.md records: wad, spread, heat list, combat set,
baseline, size cap, the recorded output / labels / census / full sha256, the feature tests. E1M1 = blocked63 (1b),
E1M2 = r4 (5). E1M3..E1M9 are placeholders marked NOT READY (shown by `--dry-run`, never run); when a level ships, fill
its row from its ship-gate block and set `ready=True`. The host tests parse ship-gate's recorded build lines and
require each ready row to reproduce them token for token (negative control: a changed spread / heat / wad / census
is caught). The creator writes ONLY under `--out-dir` (default `build/episode/`: `doom_<map>.fjm`, its
`.labels.tsv.gz`, `census_<map>.json.gz`, `logs/`, `state.json`, `report.md`, `report.json`) -- never over a shipped
binary or a tracked census. The exception is the trail's `--record` (a tracked file; equal bytes for an equal binary).

**Resumable.** A step's key = its command and environment + the source tree (git: tracked files under `src`,
`scripts`, `scenarios`, `tests/fj`, `tests/fixtures`, `scratchpad/**.py`, `scratchpad/gp/scenarios`, worktree edits
included; the creator itself excluded) + the installed flipjump's HEAD + its input files' content + (after the build)
the binary's sha256. A step that PASSED under the same key is skipped; anything else runs; `--force` re-runs all;
`--steps a b` runs a subset. So a flag change re-runs the build, and the gates only if the bytes changed. Tested with
a fake runner: the re-run skips everything; a changed source re-runs every step (the negative control); a failed step
re-runs; a failed build blocks; the dry run writes nothing.

**Guards.** `python -O` and `PYTHONOPTIMIZE` are refused; so is running it UNDER heavy.py (it takes the lock per step
itself; its parent holding the lock would deadlock it). The lock is never held between steps.

**The estimate (G12)** comes from measured step times: the step's own last run on the map, else its mean on the
other maps, else a constant read off the blocked63 / e1m2_r4 evidence logs, printed as `guess`. The dry run at
c1905d63: ~8.8 h for E1M1 + E1M2 (all of it guessed; the playthrough not counted while missing), ~38.8 h for every
step of all nine -- the 1.5-2 day estimate stands until the first real run replaces the guesses.

    python scripts/build_episode.py --dry-run                 # the plan: every command, RUN / SKIP / NOT READY
    python scripts/build_episode.py --maps E1M1 E1M2          # the integrator's first real run

## 9. Status

| date | event |
|---|---|
| 2026-10-19 | plan approved; C1 started (branch `m8-runtime-ids`); CR follow-ups #149 (branch `m8-cr149`); PR #148 (E1M2 r4 + blocked63) in CI |
| 2026-10-19 | the owner: no more RAM ("i cant buy more ram"); **2^27 words is a super hard limit** -- "Optimize the levels or even lose unimportant features". Started: ASSEMBLER MEMORY WORK (flipjump, branch `asm-memory`, target <= ~11 GB peak for an E1M2-sized program, output byte-identical) and SIZE WORK (branch `m8-size`: attribution, per-map projection, cuts, feature-loss proposals). Lessons survey: E1M7 projected ~32.8 GB / pool 157% at spread 1, E1M6 ~20.8 GB (estimates) |
| 2026-10-19 | merged into `m8-episode`: the final creator (`scripts/build_episode.py`), the lessons (`docs/level-lessons.md`, 13 survey checks) |
| 2026-10-31 | E1M3, E1M5, E1M6, E1M7, E1M8, E1M9 shipped v1 (#158, #159); the owner's plan: section 12 (E1M4's three wins, E1M6's profile and cuts, a placement profile for every level) |
| 2026-11-01 | E1M4 v1 shipped (#162); E1M2 v2 (#165: r4 refused by flipjump 1.6.0's screen); step 2: E1M6 profiled (`mm_things` 9.5% of the frame) and its monster-move test cut -- E1M6 v2 (`docs/ship-gate.md` 12), speed set 20,234,657 -> 19,413,074 (-4.06%); msframe waits for the machine. Step 3 started: the creator records each build's table sites (`--record-sites`), what a level's own heat list joins |
| 2026-11-01 | step 3's first level: E1M6 v3 = v2 on its own heat list (`heat_e1m6`, 33,785 of 33,785 sites matched where p10 matched 2,610; `docs/ship-gate.md` 12): speed set 19,413,074 -> 17,749,651 (-8.57%), B0 -8.85%, tours -9.03%, every gate PASS, rebuild byte-identical. E1M7's own list does not fit (its code and wflip area reach the table pool at 0x80000000); E1M7 stays on p10. The other levels' lists in work |

## 10. Orchestration

- Worktrees: one per agent (`Documents/doom-<topic>`), branches `m8-*` from the integration branch `m8-episode`.
- **Heavy work goes through one lock**: every build, emission, gate, msframe and long tests/fj run is wrapped in
  `heavy.py NAME -- cmd` (waits for `Documents/HEAVY.lock`, takes it exclusively, releases it). Subagents count.
- The integrator merges features into `m8-episode`, runs the build queue, the gates and the playtests, and opens a PR
  per wave.

## 11. Gaps found in this plan (2026-10-19) and their fixes

| # | gap | fix |
|---|---|---|
| G1 | the lock only orders HEAVY jobs; a build peaks at ~17 GB on this 15.6 GB box, and 14 agents' light tests during it can kill it silently (exit 255) | `heavy.py --build` marks a build's lock; every agent runs host tests through `heavy.py NAME --light -- ...`, which waits while a BUILD holds the lock |
| G2 | no priority: ~14 agents x one emit_baseline (~33 min) = ~8 h of lock time, and the critical path (C1) can starve behind it | `heavy.py --prio N`: the integrator's builds and gates 8, C1 (runtime ids) 9, C11's E1M7 probe 7, the rest 5; each agent runs emit_baseline ONCE, at its end |
| G3 | 14 branches over the same core files (reference_model, wall_renderer, things, config, survey): each proves E1M1 identity alone, never together | the integrator merges into `m8-episode` in order (C1 first, then by smallest shared footprint); after each merge the touched host tests + the survey matrix; after each batch `emit_baseline --check` + E1M2's part hashes + `emit_check` on every wave map |
| G4 | C2 (wide thing lists, E1M6 / E1M7) has no owner | assigned when C1 lands (same files); the C1 agent reports whether A1 already covers it |
| G5 | the 22M binding-speed cap per level: E1M2 is at 20.6M, and E1M4 (0.96x), E1M6 (1.21x), E1M7 (1.90x) may exceed it | each level's first build measures it (gamespeed); the speed pass (section 4.7) runs before ship; a level that cannot reach 22M is reported to the owner with its number -- it does not silently ship over |
| G6 | 2^27 words is the w=32 HARD limit, and every new sprite (decor, Baron, lost soul, plasma, pickups) may grow every map's bank | the decor / monster / pickup agents report added words per map; the bank must carry only the sprites a map uses (verify; fix if not); the integrator re-measures E1M2's size after each batch |
| G7 | E1M7 may not fit 2^27 or build in this RAM | measured early (C11's emission probe, prio 7); a no-fit is raised to the owner the same day, with options |
| G8 | DISK: C: is 96% full (39 GB free); each build writes its generated program (~0.3-0.5 GB) and the page file grows during 17 GB builds; 46 `doom-*` worktrees exist | the integrator lists the worktrees whose branches are merged and clean, and asks the owner before removing any; builds clean their generated dirs after a ship; a build refuses to start under 15 GB free (to add to heavy.py --build) |
| G9 | CI is near GitHub's 6 h job cap (20 shards); every cluster adds tests/fj files | new fj tests stay short (seconds), heavy ones are `slow`-marked; shards re-balanced per wave |
| G10 | each level's combat set and gate roles need the owner's approval before they freeze; 7 levels = 7 interruptions | batched: one approval request per wave, with every map's set side by side |
| G11 | where a level starts from is undecided: DOOM carries health / ammo / weapons between levels | DECIDED (default, the owner may overrule): every binary is a PISTOL START, as DOOM's -warp; LEVEL COMPLETE ends the binary's level |
| G12 | the playthrough gate must finish without god mode; its cost (binary ~70 ms/frame + the oracle per frame, thousands of frames) is unknown | the playthrough agent measures it on E1M1 / E1M2 and picks the skill; the final creator's 1.5-2 day estimate is re-done from those numbers |
| G13 | "as optimized as E1M1" needs each map's own heat list, and the profiling tools are E1M1-shaped | added to the gate-tools agent's scope: profx / heat with `--map` |
| G14 | features meet each other only at the level gates (a lost soul through a blaze door, plasma on a Baron) | the generated combat sets and gate roles include each map's new monsters / weapons; `emit_check` on every wave map after each integration batch |
| G15 | CI and the gates need per-map fixture wads (`tests/fixtures/freedoom_e1m2.wad` exists; E1M3..E1M9 do not) | the gate-tools agent extracts them the way E1M2's was made, under the Freedoom licence |
| G16 | PR #148 (E1M2 r4 + blocked63) is not merged; `m8-episode` is built on it | merge #148 on green CI first; every wave PR targets main after it |
| G17 | an agent can stop mid-work (context, error) | branches are pushed in steps; the integrator re-launches from the pushed branch |

## 12. The owner's plan of 2026-10-31

Where it stands: E1M3, E1M5, E1M6, E1M7, E1M8 and E1M9 ship v1 (`docs/ship-gate.md` 6-9); E1M4 is built and gated but
no play reaches its exit. In order:

1. **E1M4: three winning plays, ship the middle one.** Three agents in three worktrees play the model at easy:
   `m8-e1m4bot` (the east: ammo, the nukage channel, health), `m8-e1m4-west` (the imp corridor at x ~ -2008, where 6
   of 8 seeds die), `m8-e1m4-route` (what the exit requires; other route orders). Each win is a line in
   `Documents/E1M4_WINS.md`. With three wins, each runs as the binary playthrough (the speed set); the one with the
   MIDDLE binding ops/frame of the three is pinned (`DEFAULT_SEED`), its branch merged, and E1M4 ships v1. Every
   steering change is E1M4's alone (`MAP_TACTICS`); the six pinned plays re-checked on the merged code.
2. **E1M6 alone: profile, then cut the hot spots.** Profile E1M6's playthrough on the binary (where its 22.7M
   ops/frame on msframe's walk, and its speed set's 20.2M, go); cut what provably changes no pixel (stops, not
   budgets); every cut byte-exact on the gates, then msframe class S A/B against `shipped_e1m6` -- B SLOWER does not
   ship. A cut in shared emitter code is checked on every shipped level before it ships anywhere. **E1M6's tours may
   stay above 22M** (the owner: allowed); its speed set stays under CAP-22.
3. **After E1M4 ships: EVERY level gets its own placement profile** (section 4, step 7, the speed pass): a profile
   of the level's own playthrough -> its own pin-heat list (`--pin-heat`) -> a rebuild -> msframe class S A/B against
   its `shipped_<map>` -> a byte-identical rebuild and a new `LEVEL_SHIPPED` row when it is faster. E1M1 included
   (its heat list `heat_e1m1_adopt` stays unless the A/B says otherwise).

Machine: until 22:00 on 2026-10-31 the owner uses the RAM -- only model plays (one process per agent, started only
with >= 3 GB available) and host tests run; builds, binary runs, profiles, msframe and tests/fj wait for 22:00 and then
go one at a time through `heavy.py`.
