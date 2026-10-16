# M8: E1M2 as its own binary (owner, 2026-10-16)

**The owner's words:** "i what you to start e1m2" -- what has to be there for it to feel done: "The feel of the
level, anything in it (you can remove some weird stuff). Start it now."

**What this is.** E1M2 (Freedoom Phase 1's map, its art from `assets/freedoom1.wad` as E1M1's) shipped as a SECOND,
separate game binary `build/doom_e1m2_<name>.fjm`, beside E1M1's. The same pipeline, the same oracle discipline:
the Python model (`world.py` + `reference_model.py`) is the authority and the binary must match it byte for byte on
frozen scenario sets before it ships. One level per binary: nothing carries between them (health, weapons) -- a
standalone .fjm takes no state in; the level starts with the pistol as a NEW GAME does.

**Caps (my call, recorded -- the owner may override):** each binary is held to the SAME caps as E1M1's: size <= 43%
of 2^27 words (`gamespeed.SIZE_TARGET_PCT`) and the binding speed (mean+p80)/2 <= 22M ops/frame on its own tours
(`gamespeed.SPEED_TARGET`). The ship gate (`docs/ship-gate.md`) applies per binary, with its own msframe baseline.

## 1. What E1M2 has (measured 2026-10-16 on assets/freedoom1.wad)

| | E1M1 | E1M2 |
|---|---|---|
| linedefs / sidedefs / sectors | -- | 2,290 / 3,296 / 380 |
| segs / subsectors / nodes | 2,057 / -- / -- | 3,650 (1.77x) / 1,104 / 1,103 |
| things (single player, hard) | -- | 356 total; zombiemen 26, shotgun guys 28, imps 39, demons 18, spectres 12 |
| textures / flats | 114 / 43 | 126 (86 not in E1M1) / 63 (44 not in E1M1) |
| sound-blocking lines | 0 | 54 |

Every monster type is already implemented (zombieman, shotgun guy, imp, demon, spectre). New thing types: the yellow
and red keycards (6, 13), the soulsphere (2013), the computer map (2026), candles and candelabra (34, 35), teleport
destinations (14).

Line specials (count): 1 DR door (1), 2 W1 door stay (3), 11 S1 exit (1), 19 W1 floor to highest neighbour (6),
23 S1 floor to lowest (2), 26 DR blue (4), 27 DR yellow (2), 28 DR red (5), 31 D1 door stay (4), 38 W1 floor to lowest
(2), 48 scrolling wall (2), 58 W1 floor up 24 (1), 62 SR lift (1), 63 SR door (1), 71 S1 floor to 8 above highest
neighbour (2), 88 WR lift (4), 97 WR teleport (4), 102 S1 floor to highest neighbour (1), 103 S1 door stay (2),
109 W1 blaze door stay (1), 117 DR blaze (4), 120 WR fast lift (5), 123 SR fast lift (3). Already supported on E1M1:
1, 11, 26, 62, 88, 117 (doors.py, the P2b movers).

Sector specials: lights 1/2/8/17 (E1M1 ignores its lights: static, as here), 9 secret (P10's count).

Known caps it exceeds: partition ids 376 > 255 (`PID_NIBBLES`; P10's `sfbase` assert refuses 4 nibbles). Thing rows
227 <= 254 fit the byte lists.

## 2. The rungs

Each rung is a branch + PR + review + CI, as M7's; the binary rungs carry the full per-rung process (build, gates,
B0 on its set, gamespeed, msframe, rebuild).

| rung | what | done when |
|---|---|---|
| L0 | **The model loads E1M2.** The fixture (`tests/fixtures/make_e1m1_wad.py E1M2` -> `freedoom_e1m2.wad`); `World` accepts ML_SOUNDBLOCK (DOOM's P_RecursiveSound: at most one marked line crossed) and the new thing types; the oracle renders E1M2 frames. E1M1's model, its emission and every E1M1 gate unchanged. | host tests: E1M2 world builds, the sound flood matches a direct P_RecursiveSound implementation on both maps, E1M1 emission hashes unchanged |
| L1 | **The first E1M2 binary.** The game tier builds for E1M2 with the unsupported specials inert; the widths it needs (partition ids, any other cap); size and ops measured against the caps. | a built, byte-exact E1M2 binary on a walk; its size and binding speed measured |
| L2 | **Keys and doors:** yellow and red cards and their doors (27, 28), the door variants (2, 31, 63, 103, 109). | gates on E1M2 scenarios |
| L3 | **Floors and lifts:** 19, 23, 38, 58, 71, 102; fast lifts 120, 123. | gates |
| L4 | **Teleporters** (97), player and monsters. | gates |
| L5 | **Sound blocking in the binary** (noisecode's flood with the block state), the soulsphere, the computer map. | gates |
| L6 | **Ship:** E1M2's frozen combat set, its gamespeed tours, its msframe baseline, its ship-gate record; the play command. | the ship gate, per binary |

## 2a. What L1 must clear first (the code survey, 2026-10-16)

- **The address space -- the deciding risk.** E1M1's binary already SPANS 117.6M of the 134.2M words (`blocked62_build.log`,
  87.66%; size 38.83%), and the code must end below the table pool's base (word 2^26, `--pool-base 0x80000000`; it overflowed
  once, `blocked52_build_r0_poolbase.log`). E1M2's geometry is 1.77x: measure the code region first; a pool moved or shrunk,
  or the geometry tables packed, may be the first real work.
- **Partition ids:** ~376 > 255 at `PID_NIBBLES=2`; 4 nibbles trips `assert cfg.PID_BYTES == 1` (`wall_renderer.py`, P10's
  `sfbase`), which runs at every tier.
- **The band index:** ~83k lists need `BAND_NIBBLES=5` (measured free on E1M1, 2026-09-01; re-measure).
- **The one-pass reset:** the restore sets register `e1m1_bspcode_side`; E1M2 declares `e1m2_bspcode_side`
  (`selfreset.emit_reset_part_by_label` refuses). Make the BSP label map-agnostic or register per map.
- **`build_blocked.py --subsectors 682`** (the pin veto under `--pin-state-cells`): E1M2 has 1,104.
- **The key doors:** 27 / 28 classify as "plain" in `doors.py` (they open without a key), while the model's `KEY_DOOR_CARDS`
  knows the cards -- the model and the binary would disagree (L2 makes both take the card; only the blue `pcard` exists in fj).
- The gates (p2a / hurt / fight / die / B0 / gamespeed / deg_gate) build E1M1 oracles with no map argument and carry E1M1 poses:
  E1M2 needs its own scenario sets (L6).

## 3. Simplifications ("you can remove some weird stuff") -- recorded as made

- Sector lights stay static (E1M1 already ignores its lights).
- The computer map is picked up and does nothing (there is no automap).
- Deathmatch / co-op starts and things are ignored (single player only, as E1M1).
- The scrolling wall (48, two lines): decided in L5 -- animated if cheap, else static.
