# E1M3–E1M9: where each level stands, and what it still needs

Written 2026-10-24 ~02:00 and kept current as levels move. E1M1 (blocked63 → blocked64) and E1M2 (r4) are shipped
and not covered here.

**What the numbers rest on:**

- the fresh survey of 2026-10-24 (`scripts/level_survey.py --matrix`, at `io-api` = `m8-episode` + the screen
  API);
- the last build of each map (`doom-episode/build/doom_e1m*_b*.fjm`) and its gate logs;
- the commits named below.

`docs/levels/matrix.md` and the per-map survey pages (`E1M3.md` … `E1M9.md`) were regenerated with this document;
the 2026-10-17 versions listed MISSING / WRONG rows that have all been implemented since. The fresh survey has **no
MISSING or WRONG row on any map**.

Every binary named below was built on the **old** screen API and before the stl adoption. None of them runs on the
merged flipjump 1.6.0 without a rebuild (section 1).

---

## 0. One table

| map | size (segs / monsters) | last binary | survey | gates on that binary | B0 binding (CAP-22) | gamespeed binding / size | playthrough | blocked by |
|---|---|---|---|---|---|---|---|---|
| **E1M3** | 2,981 / 152 | `doom_e1m3_b4` (spread 1) | clean | m3, m2, p2a, hurt, fight, die **PASS** | 17,360,313 OK | 16,244,611 PASS / **45.81%** | **PASS** (easy, LEVEL COMPLETE at frame 3147) | nothing; the door-top fix needs a rebuild |
| **E1M4** | 3,502 / 183 | `doom_e1m4_b4` (spread 1) | clean | m3, m2, p2a, hurt, fight, die **PASS** | **23,647,225, OVER 22M** | 13,884,016 PASS / **49.69%** | exact on 5,000 frames, but **no route completes** (dies at world frame 4995) | CAP-22; the playthrough |
| **E1M5** | 1,933 / 189 | `doom_e1m5_b4` | clean | m3, m2, p2a, hurt, fight, die **PASS** | 18,768,855 OK | 12,825,949 PASS / 34.68% | **parts at frame 888**: a product bug (door 1), fixed on `w2fix-wip`, not yet proven | rebuild b5 + playthrough |
| **E1M6** | 4,409 / 294 | none (never built) | REFUSED + OVER on `m8-episode`; **emits clean on `soultele-wip`** | — | — | — | — | first build; RAM / pool edge |
| **E1M7** | 6,947 / 289 | none | REFUSED + 3 size WARNs | — | — | — | — | **does not emit** (hot block); pool 157% at spread 1 |
| **E1M8** | 1,796 / 4 (Barons) | `doom_e1m8_b1` (spread 2) | clean | p2a, hurt PASS; m2 PASS after `bb720098`; m3 fixed (`324e67c6`), re-run pending; fight + die FAIL (harness, fix on `w2fix-wip`) | no combat set | 11,975,852 PASS / 21.39% | no route yet (no checkpoints) | the combat-set rule (owner); harness fix proof |
| **E1M9** | 3,164 / 135 | `doom_e1m9_b1` (spread 1) | clean | m3, m2 PASS (`53bdca7b`); p2a, hurt, die PASS; **fight FAIL**: a product bug (F1, GR aim), fixed on `w2fix-wip` | 15,075,234 OK | 8,694,245 PASS / 41.79% | not run yet (checkpoints exist) | rebuild b2 + fight + playthrough |

**Gates:** byte-, state- and palette-exact against the oracle unless a FAIL is named.
**Size:** % of 2^27 words. The owner accepts above 43% (2026-10-24); 2^27 itself is the hard limit.

---

## 1. Work every level needs, in order

The same steps for all seven. They come after the work in `docs/flipjump-1.6.0-plan.md`.

1. **Merge the paused branches into `m8-episode`**, after `io-api` and `stl-adopt` merge:
   - `w2fix-wip` (`6d940630`): E1M5's door top, E1M9's GR record, E1M8's gate harness;
   - `soultele-wip` (`9d9297ee`): the lost soul through a teleport, E1M6's MAP_CONFIG, E1M7's THSS_COLD.

   Their unrun proofs run then:

   - `tests/fj/test_door_top_pass_fj.py`;
   - `test_door_reversal_fj.py`;
   - `test_shot_doors_fj.py`;
   - `emit_baseline --check` on E1M1 and E1M2.
2. **Rebuild on the new API + the stl.** Every old binary speaks the old screen bytes, and the adoption changes
   every multi-hex add, so each map is rebuilt once. That is phase 4d of the plan, for E1M3, E1M4, E1M5, E1M8 and
   E1M9.
3. **Re-plan the generated scenario sets, and the owner approves them before they are frozen.** These are the
   gate roles, the combat set and the gamespeed tours. Drafts exist (`scenarios/e1m*/` `*.draft.json`) for E1M3,
   E1M4, E1M5 and E1M9. E1M8 has gate roles but no combat set and no checkpoints. E1M6 and E1M7 have nothing yet.
4. **Every gate, one at a time:** m3, m2, p2a, hurt, fight, die, B0 on the frozen combat set (binding ≤ 22M),
   window smoke, `gamespeed_trail --record`, gamespeed, the playthrough (LEVEL COMPLETE, every frame exact), and
   the map's own fj tests.
5. **The speed pass ("as optimized as E1M1"):**
   - a pin-heat list from a profile of the level's own play (today every level uses E1M1's `heat_blocked27_p10`);
   - spread 2 where the pool fits (by the survey: E1M5 and E1M8);
   - msframe A/B for any cut.
6. **The playtest:** play the binary from start to exit, and write down what looks wrong.
7. **Ship:**
   - an msframe baseline `shipped_<map>`;
   - a byte-identical rebuild;
   - a `docs/ship-gate.md` section 5 block;
   - its row in `scripts/build_episode.py`'s REGISTRY set `ready=True`;
   - a PR.

**Fidelity gaps the survey WARNs about.** No gate fails on them, because the model and the fj agree. They are
still not DOOM, and they need correcting or an owner decision to keep:

| gap | maps | today | to correct |
|---|---|---|---|
| decorations with no picture (things 10, 15, 18, 19, 20, 21, 24, 60: bodies, blood pools, hanging bodies) | all seven | **not drawn** (`reference_model.THING_SPRITE` has no entry) | add the sprites to both mirrors. Cost: sprite-bank words per map |
| ML_SOUNDBLOCK lines (sound passes one, not two) | all seven (4–180 lines) | the fj noise flood does not honour them (noisecode, "until M8 L5") | M8 L5: honour them in both mirrors, or the owner accepts it |
| animated sector lights | E1M4, E1M5 | `SECTOR_LIGHTS` off: lights are static (a light sector there is a door or a mover, which `emit_wall_renderer` refuses) | lights on doors and movers, or the owner accepts static lights |
| slanted W1 floor lines | E1M7 (linedef 3760), E1M8 (1) | crossed by the grown box, not DOOM's spechit | play-test them; fix if a trigger fires early or late |

**Owner decisions still open, across levels:**

- **D-a. E1M1's door step.** The door-top fix (`7fe8cc9b`) keeps E1M1 on the old step (`DOOR_TOP_STEP_LEGACY`) so
  blocked63/64 are unchanged. Either keep that exemption, or let E1M1 take the fix and re-ship it (class F).
- **D-b. Combat sets.** E1M3, E1M4, E1M5 and E1M9 have drafts. E1M8 needs a rule first (section E1M8).
- **D-c. E1M4 over CAP-22** (section E1M4).

---

## E1M3

**Status.**

- Built: b4, spread 1, 718 s, 45.81% of 2^27, span 79.55%.
- Every gate PASS on b4:
  - m3 88 frames, m2 75, p2a, hurt 339 s, fight 1,113 s, die;
  - B0 OK, 11/11 runs exact, binding 17,360,313. The first B0 run "failed" because one scenario's mirror died; it
    was re-planned in `24485f76`.
- gamespeed binding 16,244,611 PASS; trail PASS.
- **Playthrough gate PASS**: easy, seed `0:0,415:1`, LEVEL COMPLETE at frame 3147, byte-, palette- and state-exact
  on all 3,157 frames (`dbbf963e`). E1M3 is the most finished of the seven.

**Left to fix:**

- **Doors 167, 213 and 228** close with their pass state at their top. The door-top bug that parted E1M5 (door 1)
  applies to them. The fix is `7fe8cc9b` on `w2fix-wip`. b4's playthrough did not happen to reverse one at its
  top, which is why it passed.

**Left to correct:** the decorations and sound blocks in section 1. Size 45.81% (accepted).

**Needs, in order:**

1. merge `w2fix-wip`;
2. rebuild on the API + stl (spread 1);
3. every gate plus the playthrough;
4. owner approval of its combat set (the draft exists; one run re-planned);
5. its own heat list, then the speed pass;
6. ship.

---

## E1M4

**Status.**

- Built: b4, spread 1, 49.69% (the largest of the built maps), span 83.52%.
- Gates: m3, m2 73 frames, p2a, die PASS. hurt PASS and fight PASS (N/A 9, including K3) on b4 after the harness
  fixes (`24485f76`).
- **B0 binding 23,647,225, over CAP-22.** The p80 run R0-s76 is at 25.29M.
  - A spread-2 trial (`doom_e1m4_s2`) gave 23,706,450, no better.
  - gamespeed's binding on the tours is 13,884,016, well under 22M. The combat set is what is heavy.
- **Playthrough:** exact on all 5,000 frames of b4 (`3c5d8ac5`), but the bot dies at world frame 4995. No seed has
  reached LEVEL COMPLETE. The seed search was stopped by the owner's order.
  - The bot learned the nukage channel's radiation suits (`ace37433` … `478f6563`): E1M4 needs the far suit before
    the blue card.

**Left to fix:**

1. **CAP-22.** Choose between a level speed pass and an owner decision:
   - the speed pass: E1M4's own heat list, the hot spots of R0-s76, and the generic cuts that land with the stl
     adoption;
   - or the owner relaxes the cap for E1M4, or the combat set changes.

   Measure after the adoption first: the chained adds move this number.
2. **The playthrough:** a route that completes, then the gate on the rebuilt binary.

**Left to correct:** section 1's gaps, plus **static lights** (an animated light sector there is a door or a mover).

**Needs, in order:**

1. rebuild (API + stl, spread 1);
2. every gate;
3. B0, then decision D-c if it is still over;
4. the bot's route (resume the seed search, or add waypoints);
5. the playthrough gate;
6. combat-set approval;
7. the speed pass;
8. ship.

---

## E1M5

**Status.**

- Built: b4, 34.68%, span 83.32%. It fits spread 2 by the survey, but b4 used spread 1.
- Gates: m3, m2 **424 frames**, p2a, die PASS. hurt PASS and fight PASS (N/A 18: no barrels, so K3, I3, I6, C3)
  after `24485f76`.
- B0 18,768,855 OK. gamespeed 12,825,949 PASS, trail PASS.
- **Playthrough: parts at frame 888** (easy, seed `0:0,342:3,1630:11,3352:24`).
  - Door 1 (sector 12; plain; 5 states; its pass state 4 is its top) reverses at its top.
  - The model clamps the door at the top with a fresh wait. The fj stepped past it: dstate 5 vs 4.
  - Pixels were still identical (0 px); 3 cells differ.

**Left to fix:**

- **The door-top bug.** The fix is `7fe8cc9b` on `w2fix-wip`; host tests are green, but it is unproven on a
  binary. It needs b5, built with spread 2, and the playthrough gate.

**Left to correct:** section 1's gaps, plus **static lights** (E1M5 has an animated light on a door or mover).
No barrels: the barrel scenarios are N/A by rule.

**Needs, in order:**

1. merge `w2fix-wip`;
2. build b5 (API + stl, **spread 2**);
3. every gate plus the playthrough through frame 888 and on to LEVEL COMPLETE;
4. combat-set approval;
5. the speed pass;
6. ship.

---

## E1M6

**Status.** Never built.

- On `m8-episode` the survey still says:
  - **REFUSED**: 4 lost souls beside teleport lines;
  - **OVER**: band lists 176,175 against 65,536;
  - WARN: plane pairs 328 against 256.
- **All three are fixed on `soultele-wip`:**
  - `93b4357b`: a lost soul teleports in the fj (EV_Teleport's z, momz and ceiling in both mirrors);
    `test_soul_teleport_fj` and `test_teleport_mover_fj` pass, 16 tests;
  - `6c7f24b8`: E1M6's MAP_CONFIG (PID_NIBBLES 3, BAND_NIBBLES 5, AUTOMAP, SWITCH_TEX, SSHEAD_RATIO 1,
    THSS_COLD 1).
- **`emit_check E1M6` PASSES** on `soultele-wip`:
  - asserts on, no stand-in;
  - 112.6M chars;
  - hot block 12,390 of 16,384 ops;
  - pid bake 441 of 4,095;
  - reset 2,780 nibble + 480 byte cells.
- Survey size rows:
  - pool demand **100% at spread 1**: the edge;
  - address span packed at spread 1, 63.9%;
  - drawable things 464 (slot cap 255 a frame);
  - runtime ids 522 (12-bit lists).

**Left to fix:**

- **Door 47** has its pass state at its top, so it needs the door-top fix (`w2fix-wip`).
- **The build's RAM is unknown.** The survey's 20.8 GB is scaled from E1M2's 17.21 GB, measured BEFORE the
  assembler memory work (#373). Since #373 the wave-1 builds peaked at 3.6–5.5 GB. Measure it on the first build,
  alone on the machine.
- **The pool is at 100%.** If the first build overflows: size work (E1M2's levers), or `--pack-blocks` /
  `--pool-base`.

**Left to correct:** section 1's gaps (114 sound-block lines, the most after E1M7).

**Needs, in order:**

1. merge `soultele-wip` and `w2fix-wip`;
2. survey clean;
3. emit_check;
4. the first build (spread 1, solo, RAM watched);
5. generate its scenario sets (gate roles, combat set, checkpoints, tours) and get them approved;
6. every gate;
7. the playthrough (the bot has never seen E1M6);
8. the speed pass;
9. ship.

---

## E1M7

**Status.** The largest map in the episode: 6,947 segs, 2× E1M3. It has never built.

- On `soultele-wip` (before THSS_COLD) `emit_check E1M7` emitted 183,248,058 chars in 751 s, with an emission peak
  of 0.94 GB. It was then **REFUSED: "the hot data block is 3880 ops past frame.arm5's window"** (20,264 of 16,384
  ops).
- `9d9297ee` adds THSS_COLD 1 (E1M3/E1M4's fix) and is **untested**.
- The survey on `m8-episode`:
  - **REFUSED**: 7 lost souls beside teleport lines (fixed on `soultele-wip`);
  - **WARN**: pool demand **157% at spread 1** (256% at spread 2). Size work is needed before any build;
  - **WARN**: the main stream is ~76.7M words, past the shipped pool base 2^26. `--pool-base` must move up (with
    `--pack-blocks`);
  - address span packed at spread 1: 86.1%;
  - WARN: RAM estimated at 32.8 GB. This is scaled from the old assembler (see E1M6); the real number comes from a
    probe;
  - 2 teleport destinations stand on movers (sectors 89 and 88). Supported (`C5b`, z read where the mover stands);
    the E1M7 tests are xfailed by name until it builds;
  - 1 slanted W1 floor line (3760).

**Left to fix (blockers, in order):**

1. `emit_check E1M7` with THSS_COLD. If the hot block still overflows, split the hot data further.
2. **The pool (157%).** E1M2's levers first:
   - drop the sprite pictures it does not use;
   - narrow tables;
   - `--pack-blocks`.

   **If it cannot fit:** "lose unimportant features" (the owner, 2026-10-19) or decide otherwise. **2^27 is the
   hard limit.**
3. `--pool-base` moved above the main stream.
4. A RAM probe, alone on the machine.

**Left to correct:** section 1's gaps (180 sound-block lines, the most of any map), and the slanted line 3760.

**Needs:** 1–4 above, then the same order as E1M6 (scenario sets, gates, playthrough, speed pass, ship).
**It is the riskiest level.** Expect it last.

---

## E1M8

**Status.**

- Built: b1, spread 2, 21.39%, 488 s emission.
- A small map: 4 Barons of Hell, 1 door (95: D1 open-stay onto a 64×56 closet), 8 W1 exit lines.
- The boss trigger is in: A_BossDeath; the last Baron's death lowers tag 666 to its lowest.
- **Gates:**
  - p2a PASS, hurt PASS;
  - **m2 PASS** after `bb720098`: the through-walk tries shallower depths behind a shallow closet; 413 frames
    exact;
  - **m3**: it failed frame 0 on the shape of a count-1 cell, its pixels BYTE-EXACT. Fixed by `324e67c6`
    (`gatestate.diff`); not re-run since;
  - **fight FAIL and die FAIL** (10-23): every scenario that ran is state-, pixel- and palette-exact. The harness
    still requires event counters that a map with only Barons cannot raise:
    - fight: `pickup_drops`, `drop_frames`, `fx_spawns`;
    - die: `drop_frames`.

    The fix is `482fda01` on `w2fix-wip`: the rim pose off the firestick, the drop counters a Baron map cannot
    raise, and the one-door reading. It is unproven on the binary.
  - the trail: `TypeError: 'int' object is not subscriptable` (the one-door reading). Also fixed by `482fda01`.
- gamespeed 11,975,852 PASS.

**Left to fix:**

- prove `482fda01`: fight, die, trail and m3 on the rebuilt binary.

**Left to decide (owner):**

- **The combat set.** The generic rules assume zombiemen, imps and sergeants; E1M8 has 4 Barons and nothing else
  (no barrels, no drops). The choice:
  - a Baron-only combat set (fewer scenarios; the binding comes from Baron fights and the boss trigger);
  - or count E1M8 as covered by the other maps' sets plus its own fight / die / playthrough.
- No checkpoints exist yet, so the bot has no route. The route: kill the 4 Barons; the floor lowers; then the exit.

**Left to correct:** section 1's decorations; 1 slanted W1 floor line.

**Needs, in order:**

1. merge `w2fix-wip`;
2. rebuild (API + stl, spread 2);
3. every gate;
4. decision D-b for E1M8, then its combat set and B0;
5. checkpoints + the playthrough (it must include the Barons' death → the floor lowers);
6. the speed pass;
7. ship.

---

## E1M9

**Status.**

- Built: b1, spread 1, 41.79%, the slowest emission (1,811 s).
- **Gates:**
  - m3 + m2 PASS after two harness fixes (`53bdca7b`: the help's plasma key 6, `wfired`'s latch bits);
  - p2a PASS, hurt PASS (312 s), die PASS (247 s);
  - B0 OK 15,075,234; gamespeed 8,694,245 PASS; trail PASS.
- **fight FAIL (F1)**, a product bug:
  - `aim_sid` in the fj is 0 everywhere; the model has 252 in window columns 12..16 (GR door line 1271).
  - The shot record ran right after pass 1, which only *reads* `drawn`. Pass 2 is what claims the columns, so no
    GR (gun-shot door) line ever recorded.
  - The fix is `c2c6c842` on `w2fix-wip`: the record runs after pass 2 (`wall_renderer.solid_seg_call_lines`). A
    map without a GR line emits the old text.
  - Every other fight scenario was exact; N/A 12.

**Left to fix:**

- prove `c2c6c842`: build b2 (spread 1), then fight.

**Left to correct:** section 1's gaps (decorations, including 4 hanging things 60).

**Needs, in order:**

1. merge `w2fix-wip`;
2. rebuild b2 (API + stl, spread 1);
3. every gate, fight F1 included;
4. the playthrough (checkpoints exist; never run);
5. combat-set approval;
6. the speed pass;
7. ship.

---

## Suggested order

**E1M3 → E1M5 → E1M9 → E1M8 → E1M4 → E1M6 → E1M7.** Closest to shipped first; size and speed risk last. E1M8 waits
on the combat-set decision and E1M4 on CAP-22, and neither blocks the others.

## Update log

| when | change |
|---|---|
| 2026-10-24 ~02:00 | written: fresh survey at `io-api`, every level's last logs, the WIP branches' commits |
