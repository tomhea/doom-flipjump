# The level pipeline: a new E1 map in ~24 hours (M8, owner 2026-10-16)

**The owner's words:** "try to make a system to make the next levels (3,4,5,8,9) a much faster process. Of like total
of 24h per level."

**What "a level" means here** (`docs/handoff-e1m2.md`): the map as its own game binary `build/doom_e1mN_<name>.fjm`,
byte-exact against the model on its own frozen scenario sets, under the same caps as E1M1 (size <= 43% of 2^27,
binding speed <= 22M ops/frame), shipped through `docs/ship-gate.md` with its own baseline.

## 1. Where E1M2's time went -- and what removes it

| cost on E1M2 | why | the fix (this pipeline) |
|---|---|---|
| a blocker found per emission (pid width, band index, sector ids, the reset prefix, two movers on a seg ...), each a 12 GB / 30-minute run | every cap was sized on E1M1 and asserts only at emit time | **`scripts/level_survey.py`**: every cap and refusal checked from the WAD and the model in seconds (2 below) |
| features the map needs (key colours, lifts, teleports, ...) found by reading the WAD | no inventory | the survey's **matrix** across all remaining maps; each feature is built ONCE, before the levels that need it (5) |
| gates hard-wired to E1M1: wad, map name, poses, sector and door numbers, counts from a default `World()` | they were written for one map | **one map profile + `--map` everywhere** (3); the scenario ROLES generated per map (4) |
| scenario sets, gate targets, viewpoints, tours chosen by hand | E1M1 had months | **generators** (4): the human step is approving the frozen set, not finding it |

Silent bugs the inventory found that would each have cost E1M2 a build (2026-10-16):
- `build_blocked.py` passed neither the map's subsector count (hard-wired 682) nor the pid width to the pin veto: an
  E1M2 build with `--pin-state-cells` would have died in `selfreset.byte_arrays`. **Fixed** (derived from `--wad/--map`).
- `aim_sid` is a 7-bit field with no fj-side guard: `1 + monsters + barrels` must be <= 127; E1M2 has 129 monsters.
- LEVEL COMPLETE's kill total is two decimal digits: E1M2's 129 monsters overflow it.
- `probe.game_cells` sizes `msec`, `snd_alert`, `st_secm`, the drop and barrel cells from a DEFAULT-map `World()`:
  every gate on E1M2 would read cells at E1M1's widths.
- gamespeed's tours open every use-box door, key doors included: E1M2's tours would walk through doors the binary
  keeps shut.
- `doors.door_sectors` makes ANY special line with a shut sector behind it a plain DR door: E1M2's yellow / red / D1
  / SR / S1 doors open without a key and re-close.

## 2. The survey (hour 0, seconds)

    python scripts/level_survey.py E1M3 --out docs/levels/E1M3.md
    python scripts/level_survey.py --matrix E1M2 E1M3 E1M4 E1M5 E1M8 E1M9

Every check calls the model's own function (`doors.door_states`, `movers.lift_states`, `World(strict=True)`,
`lootcode.give_lines`, `things.drawable_things`, `seg_marks_in` ...), so a check cannot drift from the cap it
predicts, and each runs in its own try so one refusal does not hide the next. Statuses: REFUSED (the model or emitter
asserts), OVER (a width cap), WRONG (builds, behaves unlike DOOM), MISSING (inert today), WARN (a known L-rung item).
What it cannot see -- the plane-pair count, the band lists, the light classes, the address-space fit -- it marks as
an ESTIMATE; `scratchpad/m4_bands.py` measures the first three by running the emitter up to the band walk.

## 2b. The emission check (minutes, asserts ON)

    python scripts/emit_check.py E1M3                                # the first refusal, in ~3-7 minutes
    python scripts/emit_check.py E1M3 --standin far-los ...           # past the named ones: a SIZE measurement
    python scripts/emit_check.py E1M3 --standin ... --assemble build/doom_e1m3_size.fjm   # + the assembly

It refuses `python -O`. After the emission it also counts the HOT DATA BLOCK from the text against `frame.arm5`'s
16,384-op window (E1M2's first fast build crossed it and jumped to op 0 -- 97 minutes in) and composes the one-pass
reset (a persisted name the registry lacks surfaced 7 minutes into a build): both refusals now cost minutes. A STAND-IN supplies a missing feature as code (a give routine of the same size, a decoration
present on every skill) and names the feature rung that removes it; a program built with any is a size measurement,
never a certified one. E1M2 went from nothing to a complete emission in 13 runs (handoff-e1m2.md 6); with the
survey's rows in hand first, the next map should take a few.

## 3. One map profile, `--map` everywhere

The tools already take `wad` / `mapname` at the bottom layer (`probe.Oracle`, `onewalk.DoorSim`, `gamespeed._tour_plan`,
`build_blocked --wad/--map`, `m2_std_gate` / `m3_gate --wad/--map`); the gates break by calling them with no map.
**`scratchpad/mapprofile.py`** resolves, from `--map E1Mn`: the fixture wad, the binary prefix, the census path
(`_census_game_<map>.json.gz`), the heat list, the scenario files, the msframe baseline name (`shipped_<map>`). It is
threaded through `probe.DEFAULT_*` and `gamespeed.DEFAULT_*`, which nearly every gate inherits. Default-map fallbacks
(`World()`, `MonsterPhase()`) are refused while a map profile is active, so a gate cannot silently measure E1M1.

The sites, file by file, are the inventory of 2026-10-16 (kept with this doc as `docs/levels/inventory.md`):
build path (build_blocked, the 1b line per map, `test_pin_heat` keyed by map), correctness gates (deg, m2_std, m3 --
`nlift` passed --, probe's counts, p2a / hurt / fight / die, the B0 runner reading `doc["map"]`, scenarios_v2's
checkpoints and model hashes), speed and size (gamespeed --map and the key-door filter, msframe's baseline name,
pinreport / poolmap's knobs).

## 4. The generators: roles, not poses

The gates' scenarios are already DERIVED from roles (`door_front`, `card_pose`, `trigger_pose`, `poses_in_sector`);
only the roles are E1M1 literals. One generator per artifact, each writing a tracked file under `scenarios/<map>/`:

| artifact | generator | human step |
|---|---|---|
| fixture wad | `tests/fixtures/make_e1m1_wad.py E1Mn` | none |
| gate roles (key door per colour, blaze door, walk-over triggers, an SR and a WR lift + standing pose, the floor switch, a reversal door, cards, barrel chains, nukage sectors, a crowd court, pickup-cluster walks) | `gp/gate_targets.py --map` from `DoorPhase` / `MoverPhase` / the world's things; a scenario a map cannot host is N/A with its reason | read the N/A list |
| combat-set checkpoints | `scenarios_v2.py --suggest-checkpoints --map`: the region flood + per region the sectors with most wakeable monsters | **the owner approves the frozen set** (as v5..v10) |
| deg_gate viewpoints + op baselines | spawn + the top op-cost poses of a pose sweep (`m14_vp_sweep.py`) | none |
| gamespeed tours | already generated (`_tour_plan`), deterministic -- free once the map is threaded | none |
| `BINARY_ENDS` / doors / recorded keys | `gamespeed_trail.py --map --record` -> `scenarios/<map>/gamespeed.json` | none |
| census, label table, stamp | the one-pass build writes them | none |
| heat list | E1M1's list first (its keys are macro paths, map-free); regenerate (profx drive + heatsites) only if `pinreport` shows hot groups unpinned | maybe |
| msframe baseline | `msframe.py --save-baseline shipped_<map>` | none |
| restore sets | reused (one-pass tiers use names; the map prefix is remapped); new state cells join `registered_reset_names` | none |

## 5. Features once, in the order that unblocks the most maps

The survey's matrix (section 6) lists, per map, every line special, sector special and pickup the binary does not
have. Each is a FEATURE RUNG on the model + fj + gates, done once, before the level rungs, in matrix order (most maps
first). A level rung then adds no feature: it is the map's widths (MAP_CONFIG), its generated artifacts and its gates.

## 6. The matrix (2026-10-16) and the feature rungs it orders

`docs/levels/matrix.md` (70 rows) and `docs/levels/E1M{2,3,4,5,8,9}.md` are the survey's output. Survey cost: ~2 s a map.
Grouped into FEATURE RUNGS, each done once on the model + fj + gates, ordered by how many maps it unblocks:

| rung | what | maps | evidence (survey rows) |
|---|---|---|---|
| **F1 big-map widths** | the fragment slot id past one byte (drawables 293..352 vs 256); the far-LOS extent (4,328..6,856 vs 4,064); `aim_sid` past 7 bits + a guard (139..190 vs 127); LEVEL COMPLETE kills in 3 digits (129..189 vs 99); lifts with more than 16 stops (17, 19); a map with no barrel; skill-dependent solid decoration (`mc_don` at NEW GAME); a walk-over tag opening two doors; floor switches per tag (one `fswitch` cell today); lines between two switch/lift sectors in collision / sight / noise | all six | REFUSED / OVER rows |
| **F2 door kinds** | trigger {DR, D1, S1, SR, W1, GR} x {close again, stay open} x key {none, blue, yellow, red} x {normal, blaze}: specials 27, 28, 31, 32, 33, 46, 63, 103, 109, 112; slanted door sides in doorcode | all six | WRONG / MISSING rows (31 on every map but E1M8) |
| **F3 sound blocking in fj** | noisecode's flood with ML_SOUNDBLOCK (the model has it since L0) | all six | 4..54 lines a map |
| **F4 things** | yellow / red cards (6, 13), soulsphere 2013, box of rockets 2046, partial invisibility 2024, radiation suit 2025, plasma rifle 2004; decorations 22, 30-32, 44-46, 53, 55-57, 59, 62, 63 | 2..4 each | MISSING thing rows |
| **F5 floor movers** | 19, 20, 36, 38, 58, 71, 102, stairs 7, fast lifts 120 / 123 | E1M2, E1M3, E1M4, E1M5, E1M8, E1M9 | MISSING line specials |
| **F6 teleports** | 97 (player + monsters), 126 (monsters only) | E1M2, E1M4, E1M5 | |
| **F7 exits and the rest** | W1 exit 52, S1 secret exit 51, scrolling wall 48, SR light 138 | E1M2, E1M3, E1M8 | |
| **F8 E1M8's boss** | the Baron of Hell (3003, a new monster type) and the boss-death floor (tag 666) | E1M8 | thing 3003 |

**The honest budget.** 24 hours a LEVEL holds once F1-F8 are in: the level rung then adds only widths, generated
artifacts and gates (7). The features themselves are front-loaded and shared -- my estimate, to be replaced by
measured rung times: F1 6-8 days + 2-3 for the runtime thing ids past 254 (its design, `docs/f1-big-map-widths.md`, replaced
my first guess of 2), F2 2, F3 1, F4 1-2, F5 2, F6 1-2, F7 1, F8 2: ~18-22 days, built while E1M2 ships
(E1M2 needs F1-F7 minus some specials, so most of it is E1M2's own L2-L5), then E1M3, E1M4, E1M5, E1M9, E1M8 at
~24 h each. Each feature rung is built against the two maps that use it most and re-checked by every map's survey.

## 7. The 24-hour level rung (after the feature rungs)

Wall clock, one map, heavy jobs serialized (rule 1):

| h | step | heavy? |
|---|---|---|
| 0 - 1 | fixture, survey, MAP_CONFIG (widths from the survey + m4_bands), the profile | m4_bands: light emission |
| 1 - 3 | clear the map's REFUSED / OVER rows that are not features (geometry cases: a slanted trigger, a mover on a door line) | no |
| 3 - 4 | `gate_targets`, checkpoints suggested, viewpoints swept | light |
| 3 - 3.5 | **a full EMISSION with asserts ON** (no assembly): every Python refusal in ~10 min, before any 1-2 h assembly | **yes** |
| 4 - 5 | the game-tier ONE-PASS build (~45 min for E1M1; ~1.5 h measured shape for E1M2's size) | **yes** |
| 5 - 8 | m2_std / m3 gates, p2a / hurt / fight / die on the generated roles | **yes** (one at a time) |
| 8 - 12 | B0 on the planned combat set; the owner approves the freeze | **yes** |
| 12 - 14 | gamespeed (both caps), msframe baseline, deg_gate | **yes** |
| 14 - 15 | the byte-identical rebuild | **yes** |
| 15 - 18 | ship-gate record, PR, review, CI (sharded, ~2 h) | no |
| 18 - 24 | slack: one failed gate, one fix, one re-run | -- |

The budget holds only when the level rung has NO feature work and NO tool work: both are front-loaded (5, 3, 4), and
E1M2's L1-L6 build them -- E1M2 is where the pipeline is made, E1M3 is the first map to run on it.

## 8. Rules learned building this (2026-10-16)

- **Never assemble with asserts off.** E1M2's size measurement ran under `python -O` to skip guards; the decoration
  guard (`mc_don`) it skipped became an undefined label 98 minutes later, at label resolution. The survey checks it
  in a second; the emission with asserts on catches the rest in minutes. Stand-ins for missing features are written
  as code (a monkeypatch that supplies the thing), never as asserts switched off.
- **Survey before every heavy job on a new map**, and re-survey after each feature rung: a rung that lands moves rows
  from MISSING to OK in every map's report at once.
- **A heavy job's subagent is a heavy job** (rule 1): agents doing pipeline work get read-only tasks while an
  assembly runs.
