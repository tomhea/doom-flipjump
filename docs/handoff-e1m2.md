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
- The scrolling wall (48, lines 1254 and 1338, COMPBLUE): ANIMATED, as a DELIBERATE APPROXIMATION (the integrator,
  2026-10-18, under the owner's "implement it if it costs <= +0.5%"). DOOM slides the texture one texel a tic; the game
  tier has no texture u (a W1R wall is a 1-column, 2-texel canvas keyed on the screen column: an offset moves 0 pixels,
  `scratchpad/p48_scroll_probe.py`), so the segs of a special-48 line slide their W1R PATTERN KEY instead: x + wnoff +
  (leveltime & 0xFF), one screen column a frame -- screen-space, not world-anchored, with a jump every 256 frames when
  the low byte wraps. Both mirrors: `doomfj.scrollcode` (config.MAP_CONFIG `WALL_SCROLL`, E1M2 only; E1M1's text
  unchanged), `render_wall_frame(wall_scroll=)` from `World.wall_scroll()`. Price: 539 ops per scrolling seg drawn
  (tests/fj/test_wall_scroll_fj.py), the wnoise tables 801 -> 1,056 keys.
- The teleporters (97, L4; `doomfj.teleport` holds the rules and these decisions): NO TELEPORT FOG and no sound (nothing
  reads them); NO TELEFRAG -- DOOM's player kills every shootable thing at the destination, here his teleport is
  refused there exactly as a monster's is (P_TeleportMove's stomp for a monster), in both mirrors; ONE TELEPORT PER MOVE
  (asserted exact on E1M2: no destination lies within any teleport line's reach). Kept DOOM's: the front side only,
  WR (every crossing), monsters and sliding corpses teleport, the destination's angle (a monster's facing octant),
  floorz from the destination sector, momentum 0, the player's 18-tic reactiontime (no turn, no walk).
- M8 F1.3 (the movers): every one-shot floor moves on the doors' 16-unit grid -- a stop every 4 frames (FLOORSPEED, a
  quarter of the lift's), turboLower (71) every frame, the S1 23 switch INSTANT as on E1M1 (D-L2); a floor's destination
  is computed from its neighbours' STORED floors (EV_DoFloor reads them at the trigger: sector 206 borders blazing lift
  47); the S1 switch textures do not change; a W1 crossing is tested once per tic (start to end), a slanted one by the
  exact cross product (P_PointOnLineSide without FixedMul's truncation); a blazing lift (120 / 123) strides two stops.

## 4. The width plan for L1 (analysis 2026-10-16, read-only, at be8f2cc)

**(A) Plane-pair ids: `PID_NIBBLES=3` (`PID_BYTES=2`).** Already width-generic (verified by reading): the pclm claim/step,
pval8/cpid/p2_*pid, lines_pid_ids*/lines_pid_addrs, the V5 ditto compares, skypid, ts_piece_wr, lines_steps_load2,
seg_pid/seg_bpid. NOT generic, to change:
1. **sfbase**: `sfbase[x]` is read at `flagp + off` (one byte). Make it BYTE-PLANAR: keep `sfbase` as the LOW bytes and add
   `sfbhi` (`[VIEW_W ceiling hi][VIEW_W floor hi]`) after `sprflag`, only when PID_BYTES==2 -- the high byte is always at the
   low byte + 3*VIEW_W, so `ts_base_store` / `lines_base_split` add one `ptr_add 3*VIEW_W` + one byte under `rep(PID_BYTES-1)`
   (zero ops on E1M1); the assert at the sfbase declaration becomes "PID_BYTES <= 2, sfbhi iff 2".
2. `lines_steps_step`: the literal slot stride 16 -> the Config stride.
3. `ledge_test` (P11): the piece offsets 1, 5, 8, 12 -> 1, PIECE_BYTES+1, 2*PIECE_BYTES, 3*PIECE_BYTES.
4. **The slot stride**: SLOT_SHIFT's 16 -> 256 is unshippable (the arm5 hot block's 16^5-bit window); use a 32-byte stride
   (`Config.SLOT_BIT`, one `shl_bit` after each shift site) -- re-measure the hot block's headroom first (~+3,040 ops).
5. `selfreset` `expect["pclm"] = view_w` -> `view_w * pid_bytes` (fans out to build_blocked, test_selfreset, test_pin_veto,
   test_one_pass_reset).
6. `tests/host/test_doors.py` `PID_CEILING = 256` -> `16 ** cfg.PID_NIBBLES`.
PROOF (M4's): an E1M1 build forced to `PID_NIBBLES=3` must be pixel-exact with only ops rising -- E1M1's own gates never
build the wide path. Plus a `test_slot_layouts_fj` variant at PID_BYTES=2 with mutants (a wrong hi offset, the literal 16).

**(B) Sector ids: `World.sec_nibbles = max(2, ceil(log16(nsec)))`** (2 for E1M1's 182 sectors, 3 for E1M2's 380), derived,
never set; no .fj file uses it. Two helpers so definitions and call sites cannot drift: `msec_cell(m, nib)` and
`sector_dispatch(prefix, cell, targets, miss, nib)` (an N-level sim.jump16 that emits EXACTLY today's text and labels at nib=2).
Sites: monstercode `rj<s>` (index), `lfsec` (result), `psec`, `mt_ms`, `msec` (+ its restart set and the `<< 8*m`), the
mt_ms/mm_sec movs, `mcf_leaf`, `mt_rj_leaf`; monstermove `mm_sec` (P32B_CONTEXT -> a function of nib); knockcode's msec movs;
noisecode `_node_dispatch` and `nz_sec`; statcode `sc_sec` (E1M2's secret sectors 156..358 fail its `< 256` assert today);
probe.py's `("msec", 2)`; tests/fj/test_knock_fj.py's msec. SILENT RISK: a 2-nibble register receiving a 3-nibble value on
E1M2 only -- add tests/fj harnesses on a synthetic sector >= 256.

**(C) Other counts on E1M2** fit (subsectors 1,104 in 3 nibbles; 227 thing rows <= 254; 129 monsters; 88 sound nodes; doors
<= 16 states) except: `build_blocked.py --subsectors 682` -> 1104; COUNTITEM things vs `COUNT_NIBBLES` (count them);
the band index (`BAND_NIBBLES` 5).

## 5. Found while emitting E1M2 (2026-10-16)

- **A seg between TWO movers** (`wall_renderer._seg_mover`: "seg on linedef 1460 touches [241, 240] and door None -- one
  state nibble per seg"). Each seg's baked constants switch on ONE state cell today (`_seg_cell`, `_door_blocks`'s
  `generate_state_switch_fj`, up to 16 states). Two adjacent movers need the PAIR: `_seg_secs` as the product of both
  movers' sector lists and a two-level switch (the first mover's state, then a per-state switch on the second's). The
  call sites of `_seg_cell` / `_seg_secs` (registration loops, the claim/shut tests, the per-seg dispatch) follow. L1.
  **DONE (working tree):** `_seg_movers` returns the seg's movers (0..2); `_seg_cell` returns the PAIR of cells for two;
  `_seg_secs` is the product (the first mover's major, each mover being one sector); `_door_blocks` bakes a block per
  pair behind `lut_generator.generate_pair_state_switch_fj` -- the door switch on the first cell, whose landings
  `sim.jump16` on the second (its own aligned table: legal inside the switch, which holds `hex.tables.ret`). The
  dual gate (one `hex.if0` on one cell) refuses a pair at emit time. tests/fj/test_pair_switch_fj.py: all 15 pairs twice,
  both cells unchanged, the padding, and a control (landings on the wrong cell) -- 4 passed. One-mover and door segs
  emit exactly as before.
- **Done in the working tree (L1 so far):** the sector-id width (`World.sec_nibbles`, `sectorcode.py`, every site of 4 (B);
  tests/fj/test_sector_width_fj.py 9 passed with 5 controls); the two-byte pid layout of 4 (A) (`Config.SLOT_BIT` /
  `SLOT_STRIDE`, `sfbhi`, ledge_test's offsets, the reset's `pid_bytes`); `config.MAP_CONFIG` (E1M2: PID_NIBBLES 3,
  BAND_NIBBLES 5, applied by build_wall_renderer); the reset registry's map prefix. ~~E1M1's emission IDENTICAL on all
  three configs (emit_baseline vs main 5ad0ba8)~~ -- UNVERIFIED (2026-10-17): the tracked
  `scratchpad/cr/emit_baseline.json` was last saved at P8a package 0 (fe9c26a), so a `--check` against it differs on
  every part of every config and proves nothing; the baseline is re-frozen at main d339cfe in a clean worktree and
  the tree checked against THAT (section 6's result). The hot block on blocked62: 10,430 ops, 5,954 ops of headroom.

## 6. E1M2 EMITS (2026-10-16, asserts ON)

`scripts/emit_check.py E1M2` (docs/level-pipeline.md) iterated the emission to a complete program in 13 runs of ~3-7
minutes: 384 s, parts entry 26,502 / tables 23,034,155 / main 3,378,735 / segconsts 3,653,877 / walk 20,040,288 /
state 1,152,756 / banks 47,280,486 chars. Fixed for real on the way (E1M1's emission must stay identical -- checked
before commit):
- **one machine, two sectors.** Every floor-switch sector moves by the ONE `fswitch` cell, and E1M2's border each other
  (240 / 241 / 354 ...). `_msecs` now lowers ALL switch sectors at state 1 (each switch sector's list is the same);
  a line between two sectors on one cell is read through it in `noisecode.sound_edges`, `monstersight.sight_segments`,
  `projcode.missile_rows` and `collision`'s mover openings (two CELLS stay refused); the renderer's `_seg_movers`
  collapses such a pair to one mover (no 2x2 pair switch with two unreachable blocks).
- **a blocking mover line** (lift line 1143: ML_BLOCKMONSTERS) is a static blocking line in the monsters' cells -- the
  flag blocks before any opening (P_CheckPosition).
- **a baked thing some skill lacks** (lamp 2028 at (1272, -80)) gets a `thvis` slot (`things.vanishable_slots`, the
  one rule every mirror takes; E1M1's 111 slots identical).
Twelve STAND-INS remain (the size measurement's; each names its feature rung): soundblock-ignored (F3), gives (F4),
slanted-doors (F2), decor-every-skill, stats-digits, far-los, slot-ids, barrels-one-skill, barrel-chains-static,
pickup-static-z, attacker-7bit (F1), exit-bar-stale (F7).

## 7. E1M2 FITS 2^27 -- as a plain build (2026-10-17, measured)

`scripts/emit_check.py E1M2 --standin <the twelve> --assemble build/doom_e1m2_size1.fjm` (asserts ON): BUILT in
5,884 s (assembly 5,320 s); span 89,724,992 words = **66.85% of 2^27** (headroom x1.496), one flat segment, .fjm
32,645,162 bytes. Peak private memory 19.8 GB, available RAM down to 0.00 GB at the end (rule 1: an E1M2 assembly
alone fills this 16.8 GB machine). A SIZE measurement: twelve stand-ins, pixels not certified.

NOT comparable with blocked62's 38.83%: that is the BLOCKED build's stored words (52.1M of a 117.6M span, 550,177
segments). The fast build is the blocked one, and its binding resource is the table pool: blocked62's PREFLIGHT
"demand 49,798,976 words, capacity 67,108,863 (74.2%)". E1M2 emits 1.53x E1M1's characters (tables 1.73x, walk 1.79x,
banks 1.42x: 98,566,799 vs 64,484,928), so its pool demand projects (UNVERIFIED) to ~75-85M words -- OVER the 67.1M
capacity. The next measurement is one blocked E1M2 build's PREFLIGHT (it now derives `--subsectors` and the pid width,
docs/level-pipeline.md 1); levers if it overflows: `--max-slot-ops`, `--spread`, the pool base, or declining cold
groups (inline tables cost ops, so the decline list is chosen by heat).

## 8. The FAST build's pool: fits at --spread 1 (2026-10-17, measured)

The blocked build (ship-gate 1b's flags, E1M2's wad, 9 stand-ins, asserts ON, through `scripts/emit_check.py --then
scratchpad/12m/build_labeled.py ...`) wrote its census (`scratchpad/12m/_census_game_e1m2.json.gz`, 55,780 groups,
785,305 tables) and refused: "PREFLIGHT: demand 90,317,184 words, capacity 67,108,863 words (134.6% used) -- 55,624
GROUPS GET NO BLOCK". (My projection had been 75-85M: UNVERIFIED and low.)

Priced from the census with poolmap's own `probe_pool` (no assembly; calibrated: E1M1's census at the ship knobs gives
blocked62's 49,798,976 to the word):

| knobs | E1M2 demand | fit |
|---|---|---|
| ship (spread 2, min count 256) | 90,317,184 (134.6%) | 156 of 55,780 groups placed |
| spread 2, min count 4,096 | 75,669,888 (112.8%) | 953 placed |
| spread 2, min count 8,192..65,536 (only the giant group spread) | 70,427,008 (104.9%) | 8,322 placed |
| **spread 1** | **53,649,792 (79.9%)** | **all 55,780, 0 broken** |

THE CAUSE: one group of 97,647 tables (E1M1's largest is smaller): rounded to 2^17 slots and, spread, 2^18 -- ~16.8M
words alone; spreading every other group adds ~20M more. Options: `--spread 1` (fits now; its speed against spread 2 is
measured on the binary -- E1M2 has no baseline, its caps are CAP-22 ops and size), or a BlockPool knob that spreads
groups below a MAX count too (spread 2 for every group but the giant one: ~58.9M, ~88% -- a flipjump change).

## 9. The first fast E1M2 binary, and an L1 bug it found (2026-10-17)

`build/doom_e1m2_b2.fjm` (spread 1, F1.2, six stand-ins): PREFLIGHT 53,649,920 words (79.9%; the census price was
53,649,792), 55,781 of 55,781 groups placed, 0 broken, built in 5,815 s; **size 56.80% of 2^27** (76,236,288 stored
words; span 121,631,232) -- it fits the address space, OVER the 43% cap held for E1M1 (my call for every level, 1:
the owner's to keep or raise for E1M2).

**It died after the menu: NullIP (a jump to op 0) on the first world frame.** The last-ops ring mapped through the
build's label table: `rowmap.dsp` -> `rowmap.init` -> `hex.tables.ret` -> 0 -- a wild pointer.
**THE CAUSE: the hot data block outgrew its window.** `frame.arm5`, the narrow pointer arm, rewrites only an address's
low five hexes, so every table it reaches must lie in ONE 16^5-bit window (pclm .. wrej). E1M2's block: pclm 0x200000
.. wrej 0x301800, **16,480 ops against 16,384 -- 96 over** (E1M1: 10,430, 5,954 of headroom). The growth: `sfslot`
+2,560 (L1's 32-byte stride), `thss_rt` +1,968 (more runtime things), `sshead` +844 (1,104 leaves at 2 cells each),
`sfbhi` +320, `thnext` +188, `pclm` +160. I had priced `sfslot` alone (handoff 4 (A)).
(A first diagnosis -- `thing_record_body`'s slot shift -- was WRONG: that shift indexes `spslot`, whose stride
SPR_SLOT_STRIDE must NOT scale with the pid; reverted before any build used it. wall_renderer warns of exactly this.)
**THE FIX:** `Config.SSHEAD_RATIO` -- `sshead`'s declared cells per leaf: 2 on E1M1 (its restore sets' spans:
unchanged), 1 on E1M2 (`MAP_CONFIG`) -- threaded through the emitter, `selfreset.byte_arrays` /
`emit_reset_part[_by_label]` (`declared_ratio`), the pin veto and emit_check: -1,104 ops, ~1,008 of headroom.
**THE GUARD:** `build.hot_window_violation(labels)` -- the build REFUSES an image whose hot block straddles a window
(beside `sprbank_misalignment`); it rejects b2 ("96 ops past it") and passes blocked62. ritual.py had the check;
no E1M2 build ran ritual.
**THE PROOF of L1's wide layout** (handoff 4 (A)'s "PROOF (M4's)", which L1 had not run): E1M1 built with
`PID_NIBBLES=3 BAND_NIBBLES=5` forced (`scripts/emit_check.py E1M1 --map-config ... --then build_labeled ...`,
`build/doom_e1m1_pid3.fjm`, 2,572 s, preflight 74.9%, 0 broken) -- **`m2_std_gate` PASS: byte- and state-exact on all
421 frames** (walls, sprites, the door across the M1 reset, NEW GAME). sfbhi, the 32-byte stride, the ledge offsets and
the sprite record all run end to end with no stand-in.

## 10. E1M2 RUNS (2026-10-17, measured)

`build/doom_e1m2_b3.fjm` -- the fast (blocked, `--spread 1`) build with F1.2, SSHEAD_RATIO 1 and six stand-ins
(soundblock-ignored, gives, slanted-doors, slot-ids, pickup-static-z, exit-bar-stale), asserts ON: built in 5,824 s,
PREFLIGHT 53,649,920 words (79.9%), 55,781 of 55,781 groups placed, 0 broken; the hot data block pclm 0x200000 .. wrej
0x2F0400, **1,008 ops of headroom** (the build's new refusal passed); **size 56.80% of 2^27** (76,234,048 stored words,
span 121,631,232). Run on msframe's script (the menu, NEW GAME, 40 frames forward): 44 frames presented, the run ending
at the script's EOF; the frames show E1M2's start room and its monsters
(scratchpad: e1m2_frames_b3/frame_005.png, frame_043.png). **`msframe.py --a b3 --b b3`: 66.6 ms/frame (66.5 .. 67.7),
13,512,040 ops/frame, 202.8 M fj/s** on its 200-frame forward script -- E1M1's shipped baseline is 67.3 ms on its own
(a different scene: a first reading, not a ship number; the stand-ins move ops a little). NOT certified: the six
stand-ins' features are not built, and no E1M2 gate has run (E1M2's gates are L6's: its roles, its combat set).

## 11. L2 doors: every door kind E1M2 has, both mirrors (2026-10-17, branch m8-e1m2-doors)

- **Classification by special** (`doors.MANUAL_DOOR_KINDS` / `WALK_DOOR_KINDS` / `SWITCH_DOOR_KINDS`, `KIND_MOTION`):
  only door specials make a door. E1M2: 15 doors (was 11) -- 27 yellow (100), 28 red (29, 139), 31 D1 open-stay (208,
  stored OPEN 64/80: its stops start at the stored ceiling, `doors.shut_h`), 63 SR (258, also a DR door), 103 S1
  (145, 208), 109 W1 blazing open-stay (30 and 266 from one line). E1M1: doors, order, kinds, boxes, walk triggers,
  contact, stamp and every emitted door text IDENTICAL to main (`tests/host/test_doors_e1m2.py` freezes them).
- **Keys:** the fj reads `pcard_y` / `pcard_r` (declared and written by the pickups: `lootcode.card_cells`).
- **Switches:** a use in a switch box presses a door only at rest (`doors.switch_ready`: EV_DoDoor's
  `sec->specialdata` skip). The S1 latch is not kept: its doors are open-stay (asserted), where it is unobservable.
  No switch texture changes (the renderer animates no switch).
- **Walk-over per LINE**, one entry per (line, door): a tag opens every door it names; collinear touching lines of
  one tag fuse (exact for stay doors, asserted: E1M1's two tags stay one segment each); slanted lines cross by
  P_PointOnLineSide + the new box in spechit (`doors.crossed`, `doorcode._crossed_d_lines`). E1M3's tag 11 ring: 12 entries.
- **Slanted / split door contact:** straddle any boundary line (`doors.straddles_d`, `doorcode._straddle_d_lines`
  via `sim.point_side`); the centre-inside test only where a box fits (`door_contact_geo`'s `fits`; doorcode refuses
  such a CLOSING door -- E1M3 66, E1M4 102, E1M5 211; none on E1M2, whose four non-rectangular doors all stay open).
- The `slanted-doors` stand-in is retired (`scripts/emit_check.py`).
- **Known deviation kept (issue #104 F1):** `doors.neighbours` reads a one-sided line's back as `sds[-1]` (sector 309
  on E1M2, ceiling 152), so 54, 258, 139, 30 and 266 open to 148 where DOOM opens them to 228 / 196 / 156 / 196 / 196.
  Fixing it is a map-wide geometry change (pids, door stops) the owner decides; E1M1 keeps it for its pid byte.

## 12. L3 movers (M8 F1.3, 2026-10-17, branch m8-e1m2-movers)

Every moving floor E1M2 has, model and fj (`movers.py`, `movercode.py`; the readers through ONE table,
`movers.mover_table`): the blazing lifts 120 / 123 (stride 2), a lift tag on two sectors (tag 5: 47 and 209; monsters
trigger 88 only, P_CrossSpecialLine's list), and the one-shot floors 19 / 23 / 38 / 58 / 71 / 102 as ELEVEN GROUPS,
one per tag, each its own state cell `movers.switch_cell(g)` in the `fswitch` vector (states, then step timers) --
item 10: the two 23 tags fire apart. E1M1 keeps its narrow layout (`fswitch: hex.vec 1`, the 1-bit `f_switch`): its
movercode text, sight segments, sound edges, missile rows, P_ChangeSector and monster cells were diffed identical to
a6b5e63's. The one two-cell line (1199: lift 47 / floor 206) is read through the cell its opening depends on
(`monstersight.line_states`, `collision.mover_line_states`; the monsters' low floor on 47's cell, a split dispatch).
Item 9: an item on a mover's floor (seven on E1M2: the blue card on 45, the yellow card on 301, ...) touches at the
live floor (`lootcode.pk_mbox`) and renders RUNTIME (`things.mover_leaves`, `baked_thing_mask(mover_leaves=)`; E1M1's
mask unchanged). `pickup-static-z` is retired. Tests: tests/host/test_floor_movers.py, test_mover_things.py;
tests/fj/test_floor_movers_fj.py, test_pickup_mover_fj.py (each with R9 mutants). NOT run here (heavy): emit_baseline
on E1M1, emit_check E1M2, any build.
