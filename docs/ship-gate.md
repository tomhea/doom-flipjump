# The ship gate: how a new game binary earns the name "shipped"

Written 2026-09-13, after a session that measured every engine lever shut and one program change
that deleted 25% of the frame's ops without making the frame faster. The owner's instruction:
**keep the shipped number in line so it does not get lost, and keep the ideas.** This file is
that. CLAUDE.md points here; `docs/measurement-process.md` is the instrument's protocol;
`docs/handoff-throughput-plan.md` sections 10-15 are the evidence behind every line below.

## 1. The standing number

**Since 2026-10-28 (ship #2) the shipped binary is `build/doom_e1m1_blocked65.fjm`** -- class S against blocked64
(EVERY PIXEL blocked64's): blocked64's game on flipjump 1.6.0's own stl (`stl-adopt`: the stl additions fjdoom moved into
flipjump, the pool API, `.fjm` v4 with lzma presets, and the stl audit's fixes at 1.6.0 e44ff3f), RE-PINNED with a heat
list of its own (`heat_e1m1_adopt`: the adoption renamed every label, so blocked27's list no longer matched). Built ONE
PASS from the 1b command at fa0e7452 with flipjump 1.6.0 e44ff3f (its heat list and census committed in 375b0c64), sha256 `3a2c9564adbfcb07` (full
`3a2c9564adbfcb07a1378b6c0045ca2291246c4100abcafad68bae4af3815d3b`; built as `adopt4`); REBUILT BYTE-IDENTICAL, the census
identical too (`blocked65_rebuild.log`). Its gates, each solo (`docs/ship-evidence/blocked65_*.log`):

| what | value |
|---|---|
| m2_std_gate / m3_gate | PASS -- 421 / 88 frames byte- and state-exact |
| p2a / hurt / fight / die | PASS -- 13 of 15 (2 N/A: E1M1 has no yellow / red door) / 7 / 43 / 17, state, pixels and palette exact |
| class S | the ten gamespeed games + calibration, stock engine: **1,044 of 1,044 frames' sha256 equal to blocked64's** (control: two games share only their 4 menu frames); ops **-11.64 .. -12.98% per game** (`blocked65_frames_compare.log`) |
| combat set v10 | (mean+p80)/2 = **14,249,841** (blocked64 16,297,393, **-12.56%**); every run state 100/100, pixels 100/100; B0 OK |
| binding metric | **14,792,784 ops/frame -- PASS** against 22,000,000 (blocked64 16,921,550, **-12.58%**); `gamespeed_trail` PASS (`--validate`'s record equals the binary on every frame of every run) |
| menu / key tests | key_latch, keyboard_input, menu_screens, skill_menu: 150 passed (`blocked65_menu_tests.log`) |
| size | **37.40% of 2^27 -- PASS** against 43% (50,198,748 words; file 17,606,504 bytes, .fjm v4); the pool 74.0% of its window, 44,739 of 44,739 groups placed, 20 of 20 hot words pinned, 0 lost |
| **ms/frame** | **63.4 ms/frame against blocked64's 68.3 -- B FASTER x1.076** (all five pairs, 1.066 .. 1.104; pixels identical; both on 1.6.0 e44ff3f, `blocked65_msframe.log`); 222.8 M fj/s, 14,126,543 ops/frame on msframe's script. The `shipped` baseline is re-frozen on blocked65: **63.6 ms/frame** (`blocked65_msframe_freeze.log`) |

The 12.6% fewer ops come with the adoption itself (`docs/flipjump-1.6.0-plan.md` A1-A8; not attributed per macro):
adopt3, the same game on the stl before the audit's fixes, ran the same ops to the op in every game and measured
x1.083 against blocked64 -- the audit's fixes move bytes, not executed ops.

**From 2026-10-28 (ship #1) the shipped binary was `build/doom_e1m1_blocked64.fjm`** -- class F (flipjump 1.6.0's screen /
keyboard API, the plan's ship #1, `docs/flipjump-1.6.0-plan.md` 1c-1g): blocked63's game with every emitter speaking the
new device API (7df54d00, the gate harnesses 24621131). Built ONE PASS from the 1b command with flipjump 1.6.0 at 9f6119c,
sha256 `f52751a2bb846c7a`; REBUILT BYTE-IDENTICAL (`blocked64_rebuild.log`). Its pixels are blocked63's on every gated
frame; class F because the device under them changed (D8). Its gates, each solo (`docs/ship-evidence/blocked64_*.log`):

| what | value |
|---|---|
| m2_std_gate / m3_gate | PASS -- 421 / 88 frames byte- and state-exact |
| p2a / hurt / fight / die | PASS -- 13 of 15 (2 N/A: E1M1 has no yellow / red door) / 7 / 43 / 17, state, pixels and palette exact |
| window smoke | PASS -- 40 frames through the interactive window and the headless screen, identical; title, icon, max fps |
| combat set v10 | (mean+p80)/2 = **16,297,393** (blocked63 16,255,310, +0.26%); B0 OK |
| binding metric | **16,921,550 ops/frame -- PASS** against 22,000,000 (blocked63 16,892,755, +0.17%) |
| size | **39.13% of 2^27 -- PASS** against 43% (52,522,052 words; file 39,836,502 bytes, .fjm v3) |
| ms/frame | the price (D8, class F): **68.3 ms/frame** against blocked63's **67.6** in one A/B run, each on its own flipjump (blocked63 on flipjump-151 5af5923, blocked64 on 1.6.0 e44ff3f; `blocked64_msframe.log`): **NOT SEPARATED**, ratio 0.989, pixels identical; 16,136,442 ops/frame (+0.44%). On 1.6.0 at 9f6119c, before area 6d's device speed fix, the same A/B was B SLOWER x0.961, 67.7 -> 70.2 (`blocked64_msframe_9f6119c.log`). The `shipped` baseline is re-frozen on blocked64 under 1.6.0 e44ff3f: **68.0 ms/frame**, 237.2 M fj/s (`blocked64_msframe_freeze.log`) |

**From 2026-10-18 to 2026-10-28 the shipped binary was `build/doom_e1m1_blocked63.fjm`** -- class F (M8): blocked62 + THE MAP PAGE
(the owner: "Add it to e1m1 too"; `config.MAP_CONFIG["E1M1"] = {"AUTOMAP": 1}`, 17536cad: a MAP menu item and the M key
show E1M1's lines at 40 units/px with a red dot at the player). Built ONE PASS from the 1b command at 93813efc, sha256
`b65e5a97c42adb71` (full `b65e5a97c42adb71dcf22b17f74c74e8713dfdaa862940d29c37a0fec994120c`); REBUILT BYTE-IDENTICAL
(`blocked63_rebuild.log`, the census identical too). What is new: the menu's MAP item, the M key and the MAP page. Its gates, each solo (`docs/ship-evidence/blocked63_*.log`):

| what | value |
|---|---|
| m2_std_gate / m3_gate | PASS -- 421 / 88 frames byte- and state-exact; m3 opens the MAP page from the menu and from the world, closes it back to each, and the player does not move while it shows |
| p2a / hurt / fight / die | PASS -- 13 of 15 (2 N/A: E1M1 has no yellow / red door) / 7 / 43 / 17, state, pixels and palette exact |
| combat set v10 | (mean+p80)/2 = **16,255,310** (blocked62 16,203,359, +0.32%); every frame of all 11 runs state- and pixel-exact; per-frame maximum 27,787,264 (R0-courtyard); **5,744,690 under CAP-22** |
| binding metric | **16,892,755 ops/frame -- PASS** against 22,000,000 (blocked62 16,837,730, +0.33%); `gamespeed_trail` PASS |
| size | **38.98% of 2^27 -- PASS** against 43% (52,323,960 words; blocked62 52,121,962); the pool 74.2% of its window, 44,262 of 44,262 groups placed, 20 of 20 hot words pinned |
| ms/frame | the price (D8, class F): **68.4 ms/frame** against blocked62's **68.7** in the same A/B run (`blocked63_msframe.log`; NOT SEPARATED, ratio 1.001; msframe's script passes the menu, so its pixels differ by design); 16,066,011 ops/frame on msframe's script (+13,883, +0.09%). The `shipped` baseline is re-frozen on blocked63: **69.1 ms/frame** (68.3 .. 71.0; one rep with a sagging yardstick), 232.6 M fj/s (`blocked63_msframe_freeze.log`) |
| host / fj tests | tests/host 2,219 passed at 93813efc; test_pin_heat 3 passed on the new census; key_latch 18, keyboard_input 43, menu_screens 12, skill_menu 75 passed (`blocked63_menu_tests.log`) |
| emit_baseline | every certified and hosted part SAME; the standalone banks / main / state DIFFER, the MAP page (`blocked63_emit_baseline.log`) |

The table below is **blocked62's**, the class S binary blocked63 extends -- its comparisons against blocked58 and P9 stand.

| what | value | how it was measured |
|---|---|---|
| **the shipped binary** | `build/doom_e1m1_blocked62.fjm`, sha256 `2827291fc223a6da` (first 16 hex; full `2827291fc223a6daf3469cda2606ec45f9b145511bc0bd76c100fe7149bc030a`), built 2026-10-15 ONE PASS from the command in 1b at df9e96d (M7 P13, the second speed rung: four exact cuts, the fourth the one msframe could see) | class S -- EVERY PIXEL blocked58's, on every gate, every B0 frame and 3,778 more frames of scripted and live play; the installed flipjump-151 at 6711d7a for the assembly and every run (msframe's ledger row; engine `df401f5d00a3ac5f`, blocked58's) (`docs/ship-evidence/blocked62_build.log`): 2,626 s for the whole build (the one-pass census 2,227 s), 0 broken groups, 20 of 20 hot groups pinned. The play command is `fj --run build/doom_e1m1_blocked62.fjm` |
| **ms/frame** | **74.1 ms/frame** (73.8-74.6), against **77.8** (77.7-78.8) for blocked58 in the same run -- **B FASTER x1.049** (all five pairs, 1.047 .. 1.064; pixels identical across arms and reps); yardstick median 3.57G. The `shipped` baseline is re-frozen on this binary WITH flipjump-151 at ccd1ec0 (#371, the device called once a byte): **67.3 ms/frame** (67.3 .. 68.8; re-frozen on a quiet box after the first freeze caught a busy rep), 238.4 M fj/s, yardstick 3.55G (`blocked62_msframe_freeze.log`) -- blocked58's 78.1 retired: the game as `fj --run` plays it is x1.16 faster than at P12. | `msframe.py --a build/doom_e1m1_blocked62.fjm --against shipped`, pinned core (`blocked62_msframe.log`) |
| **fj ops/s** | **216.5 M** in the A/B run (blocked58 215.1 M) -- the rate ROSE while the ops fell: v4 removed slow (cold) ops, where v1..v3 removed fast ones and lost rate (208.5 / 209.0 / 212.2 M against 214.1 / 214.8 / 214.6, `docs/gp-ledger.md` P13) | ops/frame **16,052,128** on msframe's forward-walk script (blocked58 16,745,998, -4.14%) |
| **binding metric** (owner spec) | (mean+p80)/2 = **16,837,730 ops/frame -- PASS** against **22,000,000** -- blocked58's 17,713,566 on the same tours, **-4.94%** (mean 16,922,952 -> 16,076,977, -5.00%; p80 18,504,180 -> 17,598,484, -4.89%). On IDENTICAL frames (each route's poses replayed into each binary, `blocked62_replay_{A,B,C}.log` beside `blocked58_replay_{A,B,C}.log`): route A 11,032,470 -> 10,598,375 (-3.93%), B 16,790,197 -> 15,980,500 (-4.82%), C 17,043,619 -> 16,339,217 (-4.13%) -- and against P9's blocked54 (11,413,568 / 17,707,790 / 17,602,108, `p11_ops_matrix.log`) -7.14% / -9.75% / -7.17% | `gamespeed.py --fjm build/doom_e1m1_blocked62.fjm` (`blocked62_gamespeed.log`); `gamespeed_trail.py` PASS (`blocked62_gamespeed_trail.log`: BINARY_ENDS blocked58's, unchanged) |
| **size** | **38.83% of 2^27 -- PASS against the 43% target** (52,121,962 words; span 117,649,216, 87.66%) -- 1,410,334 words under blocked58 (550,176 tables blocked where it had 578,900) | `gamespeed.py` SIZE PASS (`blocked62_gamespeed.log`); `poolmap.py` (`blocked62_poolmap.log`; its pad pricing skipped on the stale two-pass counts cache, as on blocked58; the build's preflight 74.2% of the pool window, 44,212 of 44,212 groups placed) |
| **combat set v10** (the CAP-22 set from P11 on, keys `5bb15f59e01c36b8`, FROZEN on blocked57's B0 with the owner's approval, 2026-10-14) | (mean+p80)/2 = **16,203,359** (blocked58 16,807,585, **-3.59%**; mean 14,193,897, p80 run R0-west-hall 18,212,820); every frame of all 11 runs state- and pixel-exact; every run cheaper (-2.13% R0-northwest .. -4.07% R0-west-hall); per-frame maximum 27,787,264 (+/- 2^18, R0-courtyard); **5,796,641 under CAP-22** | `b0_scenarios.py --file combat_scenarios_v10.json --pixel-every 1 --proxy` (`blocked62_b0_v10.log`, `.json`) |

**What it is:** blocked58 with FOUR MORE EXACT CUTS (M7 P13, the second speed rung, `docs/gp-ledger.md` P13) -- and the rung's lesson: the first three cut OPS and msframe could not see them; the fourth cut TIME. **(1) THE AXIS BSP NODE** (`mapcompiler.is_axis_node` / `axis_side_lines`): 418 of E1M1's 681 partitions are axis-parallel, so side = dx*(vy-py) - dy*(vx-px) has one term and the side is the sign of one 5-nibble subtract -- in the render walk and in every descend pre-walk (the eye's leaf, the collision's candidate leaves); the node XORs -c into `<L>_axc` and fcalls ONE shared classifier (`axis_leaves`: axs 0/1/2), the other 263 nodes keep the shared leaf; exact by algebra against the oracle's `_point_side` (on the line = front) (`tests/host/test_mapbake.py`: 3 viewpoints ON axis partitions and 62 points located against point_in_subsector, RUN in fj; control: the root's axis branches swapped parts). **(2) THE LEAF LIST'S HEAD BAKED + THE KEY CACHE** (`sim.thing_pass_depth`): the leaf list's head address is the leaf's constant (`cur_ssp` = sshead + s), not a ptr_index per visit (313 of 324 leaf visits a frame on route B find an empty list); the first selection round stores each thing's (rank, key) in `td_keys` (`selfreset.POINTER_READ_CELLS`) and the later rounds read it (`tests/fj/test_thing_pass_depth_fj.py` 23 passed, + a no-cache control). **(3) byte.emit THROUGH TWO NIBBLE DISPATCHES** (`lut_generator.generate_emit_byte_by_nibbles_fj`): the 256-entry EMIT table missed the cache on nearly every emit (16-26 ns/op); the same 8 output bits, lsb first, through one 16-entry table dispatched twice -- the same macro name and parameters (`tests/fj/test_byte_emit_nibbles_fj.py`: all 256 bytes RUN in fj; control: the nibbles swapped); `cur_ssp`'s per-leaf `hex.set` became an xor in and out. **(4) THE LEAF REGISTERS' ZERO INVARIANT + THE W1R ROW ONCE A CYCLE**: every visited leaf (~324 a frame) set cur_ss (8 nibbles), ss_flr and ss_ltb (4 each) with `hex.set` -- a zeroing dispatch per nibble, in code each leaf runs once; ss_flr / ss_ltb are now XORed in and back out (a mover leaf's floor cleared with hex.zero), and cur_ss, read only by the index-order sim.thing_pass, is not set when the depth pass walks; the W1R wall walkers set the colormap row once per cycle at `entry:` and xor the compile-time differences (`test_dropping_a_row_difference_breaks_the_rows`, R9; the W1R host tests 106 passed). **Why v4 and not v1..v3:** blocked59 (v1) cut msframe's script -2.62% and measured 78.2 vs 78.2 ms (x1.000; +1.52M words of inline node code, fj/s 214.1 -> 208.5 M); blocked60 (v2) -4.21%, 76.8 vs 78.0 (x1.018); blocked61 (v3) -3.75%, 76.0 vs 78.0 (x1.026, all five pairs B faster, under the 3% floor) -- all NOT SEPARATED. A timing profile by macro path (the rdtsc engine, timeobj / mkprof3 T) showed why: the ops they removed were the cheap kind (the BSP side test at 3.1 ns/op against the frame's 4.1), and the time sat in COLD code, once-per-leaf and once-per-run `hex.set` zeroing dispatches at 10-30 ns/op. v4 removed those: B FASTER x1.049 with FEWER ops cut than v2 (16,052,128 against blocked60's 16,041,515). **The playtest** (`scratchpad/gp/p12_playtest.py`, blocked58 against blocked62): 16 scripted sessions, 2,024 frames on each binary, EVERY frame's pixels and palette identical, -5.06% ops; its control (blocked58 against onepass56) DIFFERS (tour4, at frame 88); and the 100 s gameplay video's 1,754-frame run identical (-2.96%) (`blocked62_playtest.log`, `blocked62_playtest_control.log`, `blocked62_video_identity.log`). Gates (`blocked62_chain.log`): the smoke (8 of 8 frames presented), m2_std_gate (421 frames) and m3_gate (75) byte- and state-exact, the m3 selftest rejected at frame 0 where it must, p2a_gate 13/13, hurt_gate 7/7, fight_gate 43/43 and die_gate 17/17 STATE, PIXELS and PALETTE exact on every frame, B0 on v10 every frame of all 11 runs, pinreport (20 of 20 hot pinned, 0 lost, 0 broken), the host suite 1,987 passed at v2 and v3 (9fe400a, b0f35dc) and 1,988 at the shipped source (df9e96d), deg_gate 4 viewpoints BYTE-EXACT with op counts 29,898,712 / 17,307,125 / 29,162,215 / 26,630,673 (blocked58 31,251,785 / 17,984,353 / 30,263,769 / 27,915,355: -4.3 / -3.8 / -3.6 / -4.6%). Rebuilt BYTE-IDENTICAL from the 1b command (`blocked62_rebuild.log`: sha256 `2827291fc223a6da` both times, 2,621 s; the census `_census_blocked62_rebuild.json.gz` identical in content). **Not this binary's number, but the shipped game's:** the flipjump ENGINE change tomhea/flipjump#371 (`run(write_byte=...)`: the native loop gathers the output bits and calls the device once a byte; MERGED ccd1ec0 and installed in flipjump-151, `fj --run` passes it and msframe does whenever the engine has it) -- on blocked62 itself 74.4 -> 67.5 ms/frame, B FASTER x1.101 (all five pairs 1.093 .. 1.109, ops and pixels identical; `blocked62_msframe_engine.log`; on blocked58 it was 78.0 -> 71.0, x1.098). The binary does not change: it still outputs one bit an op. The binary it replaced, blocked58 (sha256 `c5c3d3b845f743f0`), is kept in `build/` as the comparison arm.

**What blocked58 was (P12; sha256 `c5c3d3b845f743f0`, built 2026-10-14 ONE PASS at fcfcb5d -- its standing numbers: 78.1 ms/frame against blocked57's 82.9, B FASTER x1.062, class S, 214.6 M fj/s, 16,745,998 ops/frame on msframe's script; binding 17,713,566 ops/frame; size 39.88% (53,532,296 words); combat set v10 16,807,585, per-frame maximum 28,311,552):** blocked57 with four exact stops, found by profiling P9 and P11 on identical frames -- (1) the axis fast path (`proj.wxr_axis_add`: a coefficient of 0 / +1.0 / -1.0 skips the multiply; 1,427 of 2,057 segs), (2) T5, the tight far bound in `proj.project_thing` for the baked things, (3) the depth scan's selection rounds reading the key's integer inputs, 8 nibbles where 16 (`sim.thing_int_read`), (4) the base flag's redundant write (`frame.ts_base_store`). Every pixel blocked57's: the playtest's 2,024 frames, the gameplay video's 1,754 and a model-planned 1,204. Gates: m2 / m3, p2a 13/13, hurt 7/7, fight 43/43, die 17/17, B0 v10, deg_gate BYTE-EXACT (31,251,785 / 17,984,353 / 30,263,769 / 27,915,355); VERIFIED by a byte-identical rebuild. Found on the way (in blocked57 too): the model and the binary part when the player fires while strafing, tomhea/doom-flipjump#134. Its full record: `docs/gp-ledger.md` P12 and this file's history.

**What blocked57 was (P11; sha256 `05c64ee3b966d5bf`, built 2026-10-13 ONE PASS at fecb44b -- its standing numbers: 82.5 ms/frame against onepass56's 84.2, NOT SEPARATED x1.024, class F, 214.0 M fj/s, 17,650,328 ops/frame on msframe's script; binding 18,928,872 ops/frame; size 39.89% (53,540,882 words); combat set v10 17,635,961, per-frame maximum 29,622,272):** onepass56 with the owner's answers to P10's play-test -- (a) a floating red EXIT sign over the exit alcove, (b) the third fragment slot's two background windows share ONE region painter, (c) a sprite fully hidden behind the nearer ledges takes no record slot, (d) the monsters' seen test and the player's aim window follow the same ledge rule. Gates: m2 / m3, p2a 13/13, hurt 7/7, fight 43/43, die 17/17, B0 v10 (FROZEN on it), deg_gate BYTE-EXACT. Its full record: `docs/gp-ledger.md` P11 and this file's history.

**What onepass56 was (P10; sha256 `63869ab4be6f2ddc`, built 2026-10-13 ONE PASS at dec86fc -- its standing numbers: 83.5 ms/frame against blocked54's 78.9, B SLOWER x0.945, class F, 211.6 M fj/s, 17,671,775 ops/frame on msframe's script; binding 18,975,792 ops/frame; size 42.06% (56,449,864 words); combat set v9 17,343,316, per-frame maximum 29,097,984):** blocked54 with the owner's second play-test round and the FIRST binary built ONE PASS -- G1's ledge clip, G2's column bases, G3's third fragment slot, G8's sky behind a stacked piece; the chaingun and the shotgun on medium / hard; the held turn 960 -> 1280; RESUME, LEVEL COMPLETE's stats, the skill highlight at MEDIUM; the switches' and doors' tones; the max-fps cap; the self-reset by label and the blocking pass sized from the expansion's own census (no counting assembly). Gates: m2 / m3, the selftests, p2a 13/13, hurt 7/7, fight 43/43, die 17/17, deg_gate BYTE-EXACT (31,425,877 / 17,639,966 / 30,893,233 / 28,635,934); superseded in its rung: blocked55 (two-pass; the empty-window walker bug) and blocked56 (stale counts). Its full record: `docs/gp-ledger.md` P10 and this file's history.

**What blocked54 was (P9; sha256 `0e4582a0c8d52134`, built 2026-10-11 at 4d46c74 -- its standing numbers: 80.3 ms/frame against blocked53's 80.2, NOT SEPARATED x0.999, 215.1 M fj/s; binding 12,498,447 ops/frame; size 38.40% (51,539,998 words); combat set v8 15,831,163, per-frame maximum 27,262,976):** blocked53 with the owner's play-test fixes and a new weapon (M7 P9, one rung, `docs/gp-ledger.md` P9). **The HELP page** in a 3x5 font with 6 empty rows between its categories (a real comma; "1 2 3 4 5 WEAPONS"). **EXIT** under HELP on the main menu: enter on it HALTS the program (the interpreter ends "looping", the window closes). **The key latch** (`kb_now`): a key pressed during a frame's polls counts for that frame even when released before the frame reads it. **DOOM's ARMS**: the six digits 2..7 in the small font (the chainsaw no longer lights "4"). **The rocket launcher** (key 5): E1M1's multiplayer launcher #226 and its rockets #227-230 spawn in single player; A_FireMissile puts MT_ROCKET in the fireball pool, its impact does 20 x 1..8, then A_Explode is the barrel blast at its whole-unit spot -- self-damage, knockback, barrels chained at run time, the player blamed (infighting); the simplifications are in 42bdadd. **The run header**: the binary compiles io mode pc and run flag flat memory (flipjump 1.5.1, tomhea/flipjump#365 / #366 / #367), so `fj --run build/doom_e1m1_blocked54.fjm` is the whole play command. Gates: m2_std_gate and m3_gate byte- and state-exact (m3 extended to 64 frames: EXIT, its help, esc to the world and the HALT at frame 64, the oracle agreeing; its new `--selftest-exit` control fails as it must), every gate selftest rejected where it must, p2a_gate 13/13, hurt_gate 7/7, fight_gate 39/39 plus the rocket's R1-R3 (4cf8f64; after the oracle's pj_src fix 5489ddc) and die_gate 17/17 STATE, PIXELS and PALETTE exact on every frame, pinreport (0 broken, 42,164 of 42,164 groups placed, pool 76.5%), host suite green, **tests/fj 944 of 944 passed** (3 parallel shards, `scripts/test_parallel.py --jobs 3`, 4 h 08 m), deg_gate 4 viewpoints BYTE-EXACT with op counts 30,313,001 / 16,674,217 / 30,589,536 / 28,600,295 (blocked53: 30,277,162 / 16,391,748 / 30,556,888 / 28,556,306) -- NOT equal, and ATTRIBUTED (`blocked54_deg_attribution.log`, `scratchpad/12m/p9_deg_attribution.py`): none of the four viewpoints DRAWS the five things P9 put on the map (the launcher #226 and its rockets #227-230; the oracle draws 4 / 3 / 5 / 4 things at each, as at blocked53's source), but the renderer processes them; deg_gate re-run with only `things.SINGLE_PLAYER_EXTRA` emptied gives 30,274,584 / 16,400,248 / 30,564,126 / 28,562,618 -- within -2,578 .. +8,500 ops (0.03%) of blocked53's, every viewpoint byte-exact. The five things are the change; the residue is P9's other visual-tier code (the rocket's sprite blocks and drawing code moving addresses) -- stated, not proven to the op. The declared criterion ("op counts EQUAL to blocked53's, the renderer did not change") was mis-specified for a rung that adds things to the map. **The stress cases** (max / mean per frame, 0 frames over the 44M tripwire): S1 25,165,824 / 23,243,434; fight S2-S4 17,301,504 / 15,680,580 (worst scenario); D9 19,660,800 / 19,116,851; the ROCKET R1-R3 (a rocket on a crowd by barrels: 3 barrels chained, 3 kills; point-blank self-damage; a held trigger) 20,185,088 / 17,345,194. Superseded in the rung: blocked54's first build (r0) died silently in its last pass beside another 7-process workload with ~3 GB free (`blocked54_build_r0_died.log`); the rerun hit the counts cache. The binary it replaced, blocked53 (sha256 `324e3d2281d5c7e1`), is kept in `build/` as the comparison arm.

**What blocked53 was (P8a + P8; sha256 `324e3d2281d5c7e1`, built 2026-10-08 at 1df5f96 -- its standing numbers: 78.6 ms/frame against blocked51's 72.0, B SLOWER x0.917, 218.5 M fj/s; binding 12,490,840 ops/frame; size 38.22% (51,304,694 words); combat set v7 15,825,592, per-frame maximum 27,000,832):** blocked51 with the final gameplay (M7 P8a + P8, `docs/gp-final-plan.md`; the model modes `PLAYER_MODE =
MONSTER_MODE = "final"`), ONE rung stacked on P6+P7, integrated from seven packages (0, A, K, I, C, D, V). **The dying
view sinks** (O-A1 S0): DOOM's P_DeathThink drop, 1 unit a tic to 6 above the floor (`p_vd`); the walls, sprites and
step faces sink exactly, the floors and ceilings keep the standing eye's band lists -- the oracle's `view_drop` split
renders the same. **Knockback** (`knockcode`): P_DamageMobj's thrust from its inflictor (the shooter, the missile, the
barrel; mass 100 / 400; none from the chainsaw; the falling-forward reversal), P_XYMovement for the player's knock once
a frame and for every monster and corpse at their 2 tics (MAXMOVE, DOOM's halving, FRICTION, STOPSPEED, the corpse
rule), a refused knock stops (O-B4), barrels are not pushed (O-B1), a drop stays where its owner died. **Infighting**:
`mon_target` names a thing, DOOM's switch and threshold, the far line of sight at any range (O-B2: the near-LOS cell
lists walked in 127-unit pieces), monster bullets take the nearest thing in their line (O-B5), fireballs hit monsters
and barrels (an imp's on an imp explodes harmlessly, the shooter is passed), a blast blames the barrel's first damager
(`bar_src`). **D3 a / b**: drops and effects before monsters in a leaf (the depth key's rank), a barrel exempt from the
soft raise (`sp_ex`). Gates: m2_std_gate 406 and m3_gate 50 frames byte- and state-exact, every gate selftest rejected
where it must (7, `blocked53_gate_selftests.log`), p2a_gate 13/13, hurt_gate 7/7, fight_gate 39/39 (F1-F10, K1-K7,
I1-I6, C1-C3, the stress S2-S4) and die_gate 17/17 (D1-D11, the sink D9-D11) STATE, PIXELS and PALETTE exact on every
frame with every control parting, deg_gate 4 viewpoints BYTE-EXACT with every op count equal to blocked51's, pinreport
20 of 20 (pool 76.4%), host suite 1878 passed, 2 skipped, 1 deselected, 2 xfailed. **The stress cases**, per frame (max
/ p95 / mean / frames over 22M; O-E1: recorded, exact, a tripwire at any frame over 44M or a scenario averaging over
30M): S1 25,165,824 / 24,379,392 / 23,173,529 / 30 of 30; S2 12,845,056 / 11,796,480 / 9,899,645 / 0 of 106; S3 (the
brawl) 17,039,360 / 17,039,360 / 15,645,627 / 0 of 60; S4 (the push storm) 15,466,496 / 14,942,208 / 12,679,491 / 0 of
76; D9 (the sink) 19,398,656 / 19,398,656 / 19,051,315 / 0 of 40. Superseded in the rung: blocked52 r0 (refused to
assemble -- the program reached 0x611aa840, inside the table pool at 0x60000000; the pool base moved, 9070b02) and
blocked52 (sha256 `f91abff8a04d37e0`: B0 v7 exact, but p2a 12/13, hurt 6/7 and fight 30/39 parted on three fj bugs --
3c6dc06 `md_fa`, 0c8a93c `bl_los`, 99609f3 the pool window; `docs/gp-ledger.md` P8a). The binary it replaced, blocked51
(sha256 `f736f73d456061ed`), is kept in `build/` as the comparison arm.

**What blocked51 was (P6+P7):** blocked48 with pickups, barrels, death and the restart (M7 P6+P7, `docs/gp-p67-interface.md`; the
model modes `PLAYER_MODE = "full"`, `MONSTER_MODE = "full"`), ONE rung stacked on P5, integrated from six packages.
**Pickups** (`lootcode`): every give with DOOM's caps (the bonuses over 100, a medikit refused at 100 health, a clip
at max ammo, the cards with the bonus's gold palette), berserk (the strength, the x10 punch, the red tint), the
chainsaw, and the drops of the dead (`barrelcode`'s `mdrop`: a zombieman's clip, a sergeant's shotgun -- on hard the
only one -- drawn on the floor as scenery). **Barrels** (`barrelcode`): shot or punched (the puff), the blast
(Chebyshev radius, line of sight, the player hurt, gibs), the chain; baked barrels record in the aim window.
**Blocking**: barrels, solid decor and live monsters stop the player; a corpse does not. **Nukage** hurts on DOOM's
period. **Death** (P7): the tic-start latch `p_dd0` chooses the branch once; a dead player presses no door, use line
or weapon key and neither walks nor turns; the dead view turns to the killer by ANG5 a tic (`p_atk`, `pj_src`,
`dt_turn`), the red fading only once facing him; no view drop (O1); use restarts the level at the skill being played,
one sequence with NEW GAME (`restartcode`). **The owner's 2026-10-05 requests**: the monsters and their pools run 2
tics a frame (`world.MONSTER_TICS_PER_FRAME`), the ACTORS rule (monsters and fireballs are always drawn -- exempt from
the soft raise and the B-gate; the corpse-slot root cause, `docs/gp-p67-interface.md` 11.2), the weapon runs 2 tics a
frame (`world.WEAPON_TICS`), a hold's first frame turns DOOM's tap (320 << 16) and later frames the owner's x1.5
(960 << 16; far aim measured equal to DOOM's, 12.1), and the help screen's spacing. Gates: m2_std_gate 406 frames
(played at easy through door 10 since 15aee03: at hard a monster stands in door 10's use box once things block) and
m3_gate 50 frames byte- and state-exact, every gate selftest rejected where it must (7,
`blocked51_gate_selftests.log`), p2a_gate 13/13, hurt_gate 7/7, P6's `fight_gate` 19/19 (F1-F10 and the stress S2)
and P7's `die_gate` 11/11 (D1-D8: 11 deaths, 5 restarts) STATE, PIXELS and PALETTE exact on every frame with every
control parting, deg_gate 4 viewpoints BYTE-EXACT with every op count equal to blocked48's, pinreport 20 of 20 with 0
broken groups of 38,098 (pool 58.2%), host suite 1656 passed. **S1** (every imp fires: 8 in flight) now costs
696,858,304 ops over 30 frames, ~23.2M/frame (blocked48: ~21.7M); **S2** (the barrel chain in view) 1,026,624,325
ops over 106 frames, ~9.7M/frame averaged -- both recorded, not judged (D1 caps v6's (mean + p80) / 2, not a
scenario). Superseded in the rung: blocked49 (a pickup's bar a frame late, c66b32c) and blocked50 (a baked barrel's
explosion light class truncated, 1af94b1); after blocked51 only the gates' oracle changed (c93b869, 3c7e381). The
binary it replaced, blocked48 (sha256 `69890d31f08b450b`), is kept in `build/` as the comparison arm.

**What blocked48 was (P5):** blocked47 with the monsters' attacks (M7 P5, `docs/gp-p5-interface.md`; the model modes
`MONSTER_MODE = "full"`, `PLAYER_MODE = "fx"`), ONE rung stacked on P4. **The player is hurt** (`hurtcode`): the
zombiemen's and sergeants' hitscan, the imp's claw and the demon's bite land through ONE `dp_go` (DOOM's
P_DamageMobj on the player: green / blue armor's save, the damage count, health, one `rng_pl` draw per hit), the bar
shows health and armor every tic, and the screen shows DOOM's red damage palettes (`set_palette` only on a change;
a menu frame shows palette 0). The death MOMENT is built (`p_dead`, the weapon lowered and kept down, the monsters
losing a dead target); the death think and restart are P7, and no gate reaches a death. **The imp's fireball**
(`projcode`): an 8-slot pool -- spawn, flight on its momentum, the missile cells `mc6` (a door's or the floor
switch's line shut to a missile by its state), the impact on the player, the explosion drawn, a fizzle when the pool
is full. **Blood**: a 2-slot pool the player's hits spawn (the "fx" player mode). The ten mobiles are drawn as
runtime things from their own view rows. Gates: m2_std_gate 452 frames and m3_gate 50 frames byte- and state-exact,
every gate selftest rejected where it must (7, `blocked48_gate_selftests.log`), p2a_gate 13/13, P5's own
`hurt_gate` (H1-H6 and the saturation case S1) STATE, PIXELS and PALETTE exact on every frame of all 7 scenarios with
every R9 control parting and deaths 0 (`blocked48_hurt_gate.log`), deg_gate 4 viewpoints BYTE-EXACT with every op
count equal to blocked47's, pinreport 20 of 20 with 0 broken groups of 36,506, host suite 1564 passed. **S1** (every
imp fires: 8 in flight, 10 fizzles) cost 651,896,774 ops over 30 frames, ~21.7M/frame -- the stress case, recorded;
the 22M cap binds v5's (mean + p80) / 2, not a scenario. The binary it replaced, blocked47 (sha256
`9e4ab7d92ff9649d`), is kept in `build/` as the comparison arm.

**What blocked47 was (P4):** blocked46 with the player's combat (M7 P4, `docs/gp-combat.md`), four rungs in ONE build on m7-shoot
(the owner, 2026-10-04: "try to merge small rungs"; gp-combat section 5). **P4.0**: the game tier's view is 160x84
under a 16-row status bar (AMMO, HEALTH, ARMS, ARMOR, KEYS in the menu's fonts, redrawn per slot on change), the
view's dittos are PARTIAL dittos (flipjump#364), and the weapon is drawn as KEEP records over the view. **P4.1**: the
owner's key map (a / d and , / . strafe, only the arrows turn, ctrl fires, 1-4 held weapon keys; the help screen
re-laid for it), strafe, DOOM's psprite machine for the fist, pistol, shotgun and chainsaw (`weaponcode`), ammo, the
overlay and the bar's ammo and arms. **P4.2a**: the aim window (`aimcode`, columns 72..88), the shots resolved through
it (`wpo`), and the monsters' damage (`damagecode`: pain, death, A_Fall, justhit, `mon_solid` / `mon_shootable`).
**P4.2b**: the shots are HEARD -- `noisecode`'s flood over E1M1's sound nodes into `snd_alert`, A_Look's sound branch
and `mon_ambush`. The model mode is `PLAYER_MODE = "hit"`. Gates: m2_std_gate 452 frames and m3_gate 50 frames byte-
and state-exact, every gate selftest rejected where it must (7, `blocked47_gate_selftests.log`), p2a_gate 13/13 state
exact and pixels byte-exact (after f045865), deg_gate 4 viewpoints BYTE-EXACT with every op count equal to blocked46's
(P4 touches the game tier only), pinreport 20 of 20 with 0 broken groups of 35,102, host suite 1500 passed. The binary
it replaced, blocked46 (sha256 `b7c9e110be1494d8`), is kept in `build/` as the comparison arm.

**What blocked46 was (P3.3 + P3.4):** blocked45 with two rungs in one build (the owner united them, 2026-10-02). **P3.3**
(`docs/gp-monsters.md` 8.6, D3 d): a leaf's runtime things are drawn NEAREST FIRST -- `sim.thing_pass_depth` draws a
longer list in rounds, each taking the least (P_AproxDistance from the player's integer position, index) above the
last drawn, pointer reads only; the oracle's `rt_depth_order="aprox"` in `GAME_RENDER_KW` (the hosted tiers keep index
order, `HOSTED_RENDER_KW`). On v5 the order changes 25 of 1,100 frames (4,357 px); the aprox key differs from the true
depth tz on 2 frames (28 px). **P3.4** (`docs/gp-help.md`): the HELP screen -- keycaps for W/A/S/D and the arrows,
SPACE / E "USE: DOORS, SWITCHES, LIFTS", ENTER, ESC "MENU / BACK", H -- opened from the main menu's new HELP item or
with H in the game; E is a second use key; the main menu lost QUIT (never selectable). The first build (r0, sha256
`fc45c241867e738c`, at 7dfc22a, `blocked46_r0pins_*` logs) passed the smoke run, m2_std_gate (452 frames), m3_gate (50
frames, the help visits included) and the 6 gate selftests, then STOPPED at its pin report: 17 of 20 hot words, 3
UNRESOLVED (an ESTIMATE of ~106,873 ops/frame of lost pins) -- the walk's pointer register moved from
`sim.thing_pass`'s local `hp` to `sim.thing_pass_depth`'s global `td_p`, so `heat_blocked27_p32a` named words this
program no longer has. 7e97a5a taught `heat_rekey` / `pinreport` a whole-token text rename and wrote
`heat_blocked27_p33`; on r0's binary B0 v5 was exact on every frame (15,621,284,
`blocked46_r0pins_b0_v5_precheck.log`) and p2a_gate passed (13 scenarios, `blocked46_r0pins_p2a_precheck.log`). r1 is
the same program built with `heat_blocked27_p33`; its evidence is `blocked46_*`. The binary it replaced, blocked45
(sha256 `25957324521286dd`), is kept in `build/` as the comparison arm.

**What blocked45 was (P3.2c):** blocked44 with the monsters DECIDING to attack in the model's `decide` mode (M7 P3.2c,
`docs/gp-monsters.md` section 8.5), class F: A_Chase whole -- `justattacked` (per slot, persisted) clears and re-picks
the direction; the melee decision (a melee state, P_AproxDistance < MELEE_REACH 60, the attack sight) and the missile
decision (a missile state, movecount 0, the attack sight, reaction 0, then the P_Random refusal); the decided state
entered with A_FaceTarget. The attack states' actions face and DRAW exactly as the full model's and apply nothing --
damage is P5. The attack sight is seen, or within NEAR and `sl_los`, the exact near LOS (per-256-unit-cell candidate
segment lists, a door's, a lift's or the switch's segment by its state, four 48-bit orientation signs), 5.52M -> 0.19M
ops after e24ab75 (a segment XORs its constants into zeroed registers). It carries P3.2b's review fixes (796cdcc):
P_ChangeSector now runs inside the `lvdone` exit guard (`tests/fj/test_change_sector_fj.py`), B0's selftest frames,
the slot-order assert and the hardening. The binary it replaced, blocked44 (sha256 `06e8912c4d4d3b96`), is kept in
`build/` as the comparison arm.

**What blocked44 was (P3.2b):** blocked43 with the monsters MOVING in the model's `chase` mode (M7 P3.2b, `docs/gp-monsters.md`
section 8.4), class F: A_Chase steps -- P_Move / P_TryMove on the monsters' own collision cells (radius 30 lists with
ML_BLOCKMONSTERS folded in, the step, height and drop-off rules, the static barrels and decorations as per-cell boxes,
the other monsters and the player as boxes), P_NewChaseDir with the D5 cap of 6, the relink of a changed leaf
(`sim.leaf_unlink` / `sim.leaf_link`), the seed through `ptloc_walk`, P_ChangeSector on the lifts, a refused step in a
monster door's box pressing it, and a closing door reversing on a live monster. No attack is decided yet (P3.2c). The
first build (r0, at 5399be4) died in the counting pass: the program reached `0x857cc840`, inside the table pool based
at `0x60000000` -- the door tic inlined the contact test of every door for each of the 53 monster slots, 8,056 signed
constant compares (~14.6M ops), and the counting pass assembles the program UNRELOCATED; one contact leaf per (door,
radius) on `dc_x` / `dc_y` fixed it (ee6761c, with `tests/fj/test_door_reversal_fj.py`). Known divergence, carried to
P3.2c: P_ChangeSector runs outside the `lvdone` exit guard (fixed on P3.2c's branch, 796cdcc). The binary it replaced,
blocked43 (sha256 `3c3a87d474d975e5`), is kept in `build/` as the comparison arm.

**What blocked43 was (P3.2a):** blocked40 with the monsters WAKING under the seen rule the owner decided (M7 P3.2a, `docs/gp-monsters.md`
sections 8.2-8.3), class F: the render marks each monster it SEES (`frame.rec_seen_mark`: an open column at the base
size, before the count budgets and the soft raise), and the next frame's tic walks the slots from `sched_cursor` (K = 6
heavy slots, deferral), A_Look waking on seen or REJECT-visible within 128 and not behind, A_Chase running its counters
and the turn. Nothing moves yet (P3.2b). Two builds died first, each on a pointer rule of the game tier: blocked41
(NullIP -- the mark's `write_hex` left the pointer arm outside the 16^5 window the narrow `read_byte5` assumes; the mark
now re-arms) and blocked42 (an endless `hex.zero` -- `--pin-state-cells` pinned `thseen`, and a pointer write takes a
pinned cell's base for its value; `thseen` joined the pin veto, `selfreset.POINTER_READ_CELLS`). The binary it
replaced, blocked40 (sha256 `dc1e85e52f48a299`), is kept in `build/` as the comparison arm.

**What blocked40 was (P3.1):** blocked38 with the monsters ALIVE in the model's `idle` mode (M7 P3.1, `docs/gp-monsters.md`
section 7), class F: every slot runs its tic and one `mstate` step (nothing wakes -- sight waits for P3.2), and the
renderer draws each monster at its state's frame and DOOM's rotation for the viewer, mirrored views included --
a runtime thing's row comes through a row select (`thsel_leaf`: a static thing its own row, a monster its view's),
and the sprite light class is two bytes wide in the animated tier (`ltw`). The gates are byte- and state-exact
with every oracle running `monsters.MonsterPhase`; deg_gate byte-exact with EVERY op count equal to blocked38's
(the visual tier expands the new record parameters to the old ops). The binary it replaced, blocked38 (sha256
`457e175106f10776`), is kept in `build/` as the comparison arm; blocked39 (the build before the heat list was
re-keyed, 17 of 20 hot words pinned) is superseded.

**What blocked38 was (P3.0):** blocked37 with the monster phase's tables emitted and called by nothing (M7 P3.0,
`docs/gp-monsters.md` section 6), class S: `mstate` (the monster state table), `mturn`, `mopp`, `mrnd`. Its
delta is the pure placement tax the handoff asked P3 to price first: +54,098 on gamespeed, +26,477 on v4,
+10,936 words, and msframe NOT SEPARATED with every pixel identical. The binary it replaced, blocked37 (sha256
`770209700dfbac8c`), is kept in `build/` as the comparison arm.

**What blocked37 was (P2b):** blocked35 with the movers (M7 P2b, `docs/gp-lifts.md`), class F: lifts 98 and 103
(the door machine on the floor, 10 stops each, WR 88 / SR 62), the instant floor switch (S1 23:
sectors 76/126/129), and doors reversing on the player at their pass state -- every rule from
`doomfj.movers` / `doomfj.doors`, plane ids 254 of 255. The gates are byte- and state-exact (m3_gate,
m2_std_gate -- whose route rides lift 98 -- and their selftests; p2a_gate's thirteen scenarios on the
binary, S9-S13 the movers, each control parting), deg_gate byte-exact at four viewpoints, B0
pixel-exact on every frame of v4. The model moves v2/v3 (R2-spectre-corridor rides lift 103), so the
CAP-22 set is now v4. The binary it replaced, blocked35 (sha256 `45674256d3f168e6`), is kept in
`build/` as the comparison arm; blocked36 (the pre-review build, pillar 129 lowered to 8) is superseded.

blocked25 read 99-104 ms/frame with a background video render at ~0.3-0.45 core -- under
msframe's busy refusal -- and 84-89 ms with a lighter one (2026-09-13; blocked27 has not been timed
under load). **Absolute ms/frame is a number about
the machine state; only an A/B inside one run is a number about the binary.** The msframe baseline `shipped`
(`scratchpad/12m/msframe_baselines/shipped.json`) is FROZEN on this binary (M7 P8, 2026-10-09: 78.1 ms/frame
[77.6 .. 78.5], yardstick 3.63G, 220.0M fj/s -- `blocked53_msframe_freeze.log`);
blocked45 to blocked51 were never frozen, so blocked44's stood until then
(re-frozen 2026-10-02 on blocked44: 73.1 ms/frame [72.3 .. 76.2], yardstick 3.50G,
204.4M fj/s -- `blocked44_msframe_freeze.log`; blocked40's 2026-09-30 read 63.7 [63.6 .. 63.8]; blocked38's the same day read 61.5 [61.3 .. 61.7];
blocked37's the same day read 61.9 [61.4 .. 62.0];
blocked36's 2026-09-29 read 77.4 on a slow box;
blocked35's the same day read 62.1 [61.4 .. 63.9];
blocked34's 61.3 [60.6 .. 61.5];
blocked33's the day before read 61.8 [61.7 .. 62.5]; blocked32's freeze that day read 70.1 at 11:54 on a
box running ~201M fj/s, after a 10:48 attempt (79.2 ms [72.0 .. 114.1], taken while the OS still
released the previous build's memory) was discarded -- which is exactly why only an A/B inside one
run counts; the stored ms is informational; `--against shipped` RE-MEASURES
both arms live, and the binary hash is what it checks), so `--against shipped` is the comparison.

## 1b. The build command, and the play command

**The build command of the shipped series** -- ONE PASS since onepass56 (M7 P10, 2026-10-13; below):

```
python scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/<name>.labels.tsv.gz -- game --out build/doom_e1m1_<name>.fjm --pool-base 0x80000000 --span-bits 0x7fffffe0 --pin-state-cells --merge-aliases --spread 2 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --one-pass-blocks --counts-cache scratchpad/12m/_census_game.json.gz --pin-heat scratchpad/12m/heat_e1m1_adopt.json.gz
```

`--one-pass-blocks` reads no counts: it WRITES the build's census to `--counts-cache`, the tracked
`scratchpad/12m/_census_game.json.gz` being the shipped build's (blocked65's since ship #2, the same census its
rebuild wrote; blocked63's at M8; blocked62's at P13; blocked58's before) -- the file `tests/host/test_pin_heat.py` fits the heat list against, as it fitted
the two-pass counts cache. **Until P10 the line was the TWO-PASS one** (recovered 2026-09-13 from the session
transcript that built blocked23 and blocked24, 09-11 11:22 and 13:01 -- the two builds before blocked25 in the same
series, with the same counts cache; blocked25's own line, 09-11 18:04, was never logged and followed the renderer
fix of FINDINGS CE): `python scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/<name>.labels.tsv.gz -- game --out build/doom_e1m1_<name>.fjm --pool-base 0x80000000 --span-bits 0x7fffffe0 --pin-state-cells --merge-aliases --spread 2 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --counts-cache scratchpad/12m/_counts_game.json.gz --pin-heat scratchpad/12m/heat_blocked27_p8a.json.gz` -- a counting assembly
first (or a counts-cache hit), then the placing one; blocked54's heat list was `heat_blocked27_p8a`.

Until blocked51 the line read `--pool-base 0x60000000 --span-bits 0x9fffffe0` (every build from blocked25 on);
blocked52's first build moved it (blocked53 below). Every tool that reconstructs the pool reads the same two knobs:
`poolmap.SHIP_GATE`, `profx/pool.KNOBS`, `profx/common.POOL_BASE_WORD` (9070b02) -- change all four places together.

`build_labeled.py` wraps `build_blocked.py` with the label spy on (everything after `--` is
`build_blocked.py`'s own arguments; `--labels` is the wrapper's). The label table it writes is
what every profile joins against -- keep it beside the binary. The counts cache is keyed by the
emitter sources; a cache MISS runs the counting assembly first (+25 min) and is the expected case
after any emitter change. Build time ~30 min on a quiet box, ~60 min while anything else holds
memory (the assembler peaks near 9.5 GB; CLAUDE.md rule 1).

Status: **VERIFIED, byte-identical.** A build from exactly this line on 2026-09-13 23:40
(a fresh counting assembly -- the cache signature had changed with
the working copies' line endings -- then the two passes) produced sha256 `fc46c28c5f2bbac8`, the
same bytes as `build/doom_e1m1_blocked25.fjm`. So this is blocked25's build command, and the
blocking pass is deterministic given the source, the knobs and the counts. Its label table is
`scratchpad/12m/atlas/blocked25.labels.tsv.gz` (the byte-identical rebuild's) -- the shipped binary's
map back to its source, which it never had until now; the rebuild itself was deleted as a duplicate.

**blocked27 (2026-09-25/26): VERIFIED byte-identical three times, the last two from a fresh count.**
The line did not change: its two leads live in the program (`config.py`'s pads) and in
`build_blocked.py`'s SAFE_TABLE_MACROS, not in the command.
1. At ffda044 against flipjump 1.5.1 at `73e09c0` (tomhea/flipjump#362 merged), the line HIT the
   counts cache made for padB -- at flipjump `3e53017`, #362's pre-review head; the signature hashes
   doom's sources and the macro list, not flipjump's stl -- and produced sha256 `38b09a7331f4f52b`,
   the bytes of `doom_e1m1_padB.fjm`, the candidate every measurement in section 1 was made on
   (`docs/ship-evidence/blocked27_rebuild.log`).
2. At 18d351d, whose `config.py` comment changed the signature, the same line MISSED the cache,
   ran the counting assembly at `73e09c0` (32,066 groups, 432,164 tables, 2,038 s) and produced
   `38b09a7331f4f52b` again (`docs/ship-evidence/blocked27_rebuild_recount.log`). The recount's
   counts, widths, aliases and width histogram equal the old cache's field for field; only the
   signature moved.
3. That signature (`src=3e1d39d67a047f0e`) was still a property of ONE working copy: the hash is
   over the source files' bytes on disk, and seven of them (doorcode/doors/mapcompiler/
   reference_model.py, frame_render/present/stream_render.fj) were CRLF there, while
   `.gitattributes` (`* text=auto eol=lf`) makes every fresh checkout LF on any OS. With those
   seven rewritten to LF (blob hashes unchanged -- no commit), the working copy signs
   `src=4a533c94ca7093ec`, and at cfa5daa the same line MISSED, recounted (1,998 s) and produced
   `38b09a7331f4f52b` a third time (`docs/ship-evidence/blocked27_rebuild_lf.log`), counts again
   equal field for field. The tracked cache is that LF recount, so the line HITs on a fresh
   checkout. A working copy with CRLF sources signs differently and recounts: harmless (+~34 min),
   and the fix is to make its sources LF, not to re-sign the cache.
4. **(PR #87, 2026-09-26)** the gameplay model's new `src/doomfj` modules (gamedata, rng, world,
   combat) and the `GAME_RENDER_KW` refactor change the signature: on main after that merge the
   line MISSES the tracked cache and recounts once (~34 min, the counts expected equal); the next
   ship build re-signs the cache from that recount, as in item 3.

Its label table is `scratchpad/12m/atlas/blocked27.labels.tsv.gz`; `padA`/`padB` and the recounts'
duplicates `blocked27r`/`blocked27lf` were deleted.

**blocked28 (2026-09-27, M7 P1.1): the line gains `--pin-heat scratchpad/12m/heat_blocked27.json.gz`,
and needs flipjump 1.5.1 >= `bc8ee63` (tomhea/flipjump#363, `BlockPool(heat=)`).** The heat list is
tracked gzipped (10.3 MB of JSON, 192 KB; force-added past `.gitignore`); it came from blocked27's
profile
(`profx drive.py games`, `heatsites.py`, which replays the recorded table sites through flipjump's
own `reserve()`). The counts cache was re-signed by the recording pass (`--record-sites`, a fresh
count: counts, widths, aliases and width histogram equal blocked27's field for field; only the
signature moved, `4a533c94` -> `26c336b8`), so the line HITs it. Built first with the pin-heat
branch's flipjump at `198bbb3` (the same code as `bc8ee63`, which later changed two comments):
sha256 `9fe88c6187a82921` in 5,024 s (`docs/ship-evidence/blocked28_build.log`); rebuilt with the
installed 1.5.1 at `bc8ee63`: sha256 `9fe88c6187a82921` (`blocked28_rebuild.log`) -- **VERIFIED byte-identical.**
Both builds read the list UNCOMPRESSED (`heat_blocked27.json`, JSON sha256 `e02565e1fe75d184`, which
both logs print); the tracked `.json.gz` decompresses to those exact bytes, and the loader prints
the decompressed JSON's sha, so a build from this line prints the same `e02565e1fe75d184`. Its label
table is `scratchpad/12m/atlas/blocked28.labels.tsv.gz`.

**blocked29 (2026-09-27, M7 P1.2): the line did not change** -- still blocked27's heat list; the
source did, so the counts cache MISSED and recounted (20,835 groups -> 17,611 after alias merging,
337,465 tables, 2,060 s) and the build took 7,894 s: sha256 `a90f172ee718be63`
(`docs/ship-evidence/blocked29_build.log`). All 20 hot groups matched; 14,198 of the list's 35,894
hot sites did -- the rest were the retired blockmap walk's. The tracked counts cache is that
recount, and the same line at the rebased head HIT it and produced `a90f172ee718be63` again, label table
included (`blocked29r_build.log`, 4814 s) -- **VERIFIED byte-identical.** Its label table is
`scratchpad/12m/atlas/blocked29.labels.tsv.gz`.

**blocked30 (2026-09-27, M7 P1.3): the line did not change** -- still blocked27's heat list; the
source did, so the counts cache MISSED and recounted (17,496 groups after alias merging, 336,374
tables) and the build took 7,234 s: sha256 `0dd3806016af68cd` (`docs/ship-evidence/blocked30_build.log`). All 20
hot groups matched; 14,083 of the list's 35,894 hot sites did. The tracked counts cache is that
recount, and the same line at 87c2c75 -- the build's own source -- HIT it and produced `0dd3806016af68cd` again,
label table included (`7bc5fa5d...`; `blocked30r_build.log`, 4,769 s) -- **VERIFIED byte-identical.** Its label
table is `scratchpad/12m/atlas/blocked30.labels.tsv.gz`. PR #92's review then changed `src/` (one list
bound, one persist composition, the lists' extents written once): the build's own path hands the
assembler the same files and the same persist tuple at 87c2c75 and at the head
(`docs/ship-evidence/p13_emit_neutral.log`), so the program -- and with it the counts and the binary
-- is blocked30's; but the head's sources sign the counts cache `3efece59` where the tracked recount
is signed by 87c2c75's (`aab5be8f`), so on main this line MISSES the cache and recounts once (~34 min,
the same counts) -- as after PR #87 (item 4). The next ship build re-signs it. (A first build of this rung was stopped in pass 1:
it would have been refused at the reset -- see `docs/gp-leaf-lists.md`, As built.)

**onepass56 (2026-10-13, M7 P10): ONE PASS -- the line at the top of 1b** (onepass56 itself wrote its census to
`scratchpad/12m/_census_onepass56.json.gz`; the tracked `_census_game.json.gz` is that file).

`--one-pass-blocks` (dec86fc) builds with flipjump's `BlockPool(one_pass=True)` (tomhea/flipjump#369, merged into 1.5.1
as 6711d7a; onepass56 was assembled at the PR's e4340ee, whose output for a pool that is not short #369's round 4
verified equal to 798cec4's: 857 of 857 fuzz pools and 256 of 256 corpus builds): the tables wait out of the op
stream and are placed when the expansion ends, the blocks sized from that expansion's own census -- NO counting
assembly, and `--counts-cache` is WRITTEN (the census, which pinreport reads), never read. The game tier's self-reset
is generated by label (6208788), so the whole build is ONE assembly: 2,887 s for onepass56 (emission and the
assembler's 2,443 s), against blocked54's 9,993 s on a counts-cache hit (+5,602 s for its recount). **Rebuilt
byte-identical**: onepass56's first build wrote the same bytes (sha256 `63869ab4...a520746e00`) and failed only the
build's own storage check (`storage_mode None`: the build RUNS the binary, and the assembling worktree had no native
engine -- `onepass56_build_try1.log`); the engine is the installed one since. The heat list is `heat_blocked27_p10`
(20 hot groups; 20 of 20 pinned). Status: VERIFIED by the rebuild above; it needs flipjump 1.5.1 >= 6711d7a (or the
PR's e4340ee). **The play command is `fj --run build/doom_e1m1_onepass56.fjm`.**

**blocked62 (2026-10-15, M7 P13): ONE PASS -- the line at the top of 1b** with `heat_blocked27_p10` (its census
`scratchpad/12m/_census_blocked62.json.gz`, the tracked `_census_game.json.gz` since P13; `tests/host/test_pin_heat.py`
passed against it). Assembled AND run by the installed flipjump-151 at 6711d7a. 2,626 s for the
whole build (the one-pass census 2,227 s). Pinning: 20 of 20 hot words, 0 lost (4 re-keyed by their label), 44,212 groups
placed, 0 broken, 550,176 tables blocked, the pool 74.2% of its window (`blocked62_pinreport.log`). Class S: VERIFIED by a byte-identical rebuild (`blocked62_rebuild.log`).
**The play command is `fj --run build/doom_e1m1_blocked62.fjm`.**

**blocked65 (2026-10-28, ship #2: flipjump 1.6.0's stl): ONE PASS -- the line at the top of 1b** with
`heat_e1m1_adopt`, at fa0e7452 with flipjump 1.6.0 e44ff3f; 1,713 s (the rebuild at 375b0c64). **The heat list is the map's own** (M8 G13,
`mapprofile.profile("E1M1").heat`), made in three steps the adoption needs once per stl change: (1) the counting pass
`build_blocked.py game <1b knobs> --record-sites scratchpad/12m/_sites_e1m1_adopt.json.gz` (no `--one-pass-blocks`;
`blocked65_heat_1a_sites.log`); (2) the one-pass build WITHOUT `--pin-heat` (`blocked65_heat_1b_unpinned.log`), profiled over
the ten gamespeed games (`profx/drive.py games`, `blocked65_heat_2_games.log`); (3) `heatsites.py` on that profile ->
20 hot groups, 24,970 hot sites, 0 ops unmapped; its layout control 41,006 words at their base, 3,733 unpinned (byte and
pointer-read cells), 0 at a wrong base (`blocked65_heat_2_heatsites.log`). Pinning: 20 of 20 hot words, 0 lost, 44,739
groups placed, 0 broken, 542,974 tables blocked, the pool 74.0% of its window (`blocked65_pinreport.log`). VERIFIED by a
byte-identical rebuild (`blocked65_rebuild.log`, 1,705 s). Runs on flipjump >= 1.6.0 e44ff3f.
**The play command is `fj --run build/doom_e1m1_blocked65.fjm`.**

**blocked64 (2026-10-28, flipjump 1.6.0's device API, ship #1): ONE PASS -- the line at the top of 1b** with
`heat_blocked27_p10`, assembled by flipjump 1.6.0 at 9f6119c (`emit_check.py E1M1 --then` the line). Pinning: 40,529 words
pinned, 44,262 groups placed, 0 broken, 550,497 tables blocked, the pool 74.2% of its window. VERIFIED by a byte-identical
rebuild (`blocked64_rebuild.log`). Runs on flipjump >= 1.6.0 (the new screen / keyboard device; flipjump-151 cannot run it).
**The play command is `fj --run build/doom_e1m1_blocked64.fjm`.**

**blocked63 (2026-10-18, M8: the MAP page): ONE PASS -- the line at the top of 1b** with `heat_blocked27_p10` at
93813efc (its census the tracked `_census_game.json.gz`; `tests/host/test_pin_heat.py` 3 passed against it). 2,599 s
(the one-pass census 2,184 s; peak private 11.26 GB). Pinning: 20 of 20 hot words, 44,262 groups placed, 0 left
unblocked, 550,497 tables blocked, the pool 74.2% of its window (`blocked63_build.log`). VERIFIED by a byte-identical
rebuild (`blocked63_rebuild.log`, 2,561 s). **The play command is `fj --run build/doom_e1m1_blocked63.fjm`.**

**blocked58 (2026-10-14, M7 P12): ONE PASS -- the line at the top of 1b** with `heat_blocked27_p10` (its census
`scratchpad/12m/_census_blocked58.json.gz`, the tracked `_census_game.json.gz` since P12; `tests/host/test_pin_heat.py`
passed against it in the host suite). Assembled AND run by the installed flipjump-151 at 6711d7a (#369 merged: no
detached worktree since). 3,032 s for the whole build. Pinning: 20 of 20 hot words, 0 lost (4 re-keyed by their
label), 44,177 groups placed, 0 broken, 578,900 tables blocked, the pool 78.1% of its window
(`blocked58_pinreport.log`). Class S: VERIFIED by a byte-identical rebuild (`blocked58_rebuild.log`).
**The play command is `fj --run build/doom_e1m1_blocked58.fjm`.**

**blocked57 (2026-10-13, M7 P11): ONE PASS -- the line at the top of 1b** with `heat_blocked27_p10` (its census
`scratchpad/12m/_census_blocked57.json.gz`, the tracked `_census_game.json.gz` since P11; `tests/host/test_pin_heat.py`
3 passed against it). Assembled by tomhea/flipjump#369's tree at 798cec4 (the PR's last head; merged into 1.5.1 as
6711d7a) on PYTHONPATH, in a detached worktree holding the installed engine's `_fjcore.pyd` (the build RUNS the
binary: onepass56's first try had none); every run on the installed 1.5.1 at 0a24613. 2,769 s for the whole build
(the assembler's 2,356 s). Pinning: 20 of 20 hot words, 0 lost (4 re-keyed by their label), 44,200 groups placed,
0 broken, 578,918 tables blocked, the pool 78.1% of its window (`blocked57_pinreport.log`). Class F: not rebuilt.
**The play command is `fj --run build/doom_e1m1_blocked57.fjm`.**

**blocked55 and blocked56 (2026-10-12/13, M7 P10, superseded):** blocked55 was the two-pass line above with
`heat_blocked27_p10` and the counts cache `_counts_game_p10.json.gz` (sha256 `837f1abaccc7e7c7`; its gamespeed crashed
on the empty-window walker bug); blocked56 the one-pass RESET with blocked55's counts trusted (`--counts-trust`):
the walker fix shifted `stream_render.fj`'s lines, the group keys carry file:line, and 60,256 tables went inline --
STOPPED by its own pinreport (the hot `ycur` word lost). A trusted counts cache is stale after ANY fj line shift; the
one-pass line has no cache to go stale.

**blocked54 (2026-10-11, M7 P9): the line is blocked53's, unchanged** -- `heat_blocked27_p8a` (no hot macro changed its parameter count: checked before the build), pool base 0x80000000; it needs flipjump 1.5.1 >= `342a3b9` (the .fjm run header: `selfreset.capture_labels` passes `run_flags` / `io_mode`). The counts cache MISSED and recounted (51,971 groups -> 42,164 after alias merging, 555,295 tables, 5,602 s beside another workload; the tracked cache is that recount); r0 died in its last pass (rc 127, no traceback, ~3 GB free); the rerun HIT the cache and built in 9,993 s (sha256 `0e4582a0c8d52134`; preflight 51,305,152 words, 76.5%; 556,575 tables blocked, 2,550 declined, 0 broken). **The play command is `fj --run build/doom_e1m1_blocked54.fjm`** (the binary carries io mode pc and run flag flat memory; `--io` / `--run-flags 0` override).

**blocked53 (2026-10-08, M7 P8a + P8): the line's heat list is `heat_blocked27_p8a` and its pool base is 0x80000000.**
- The heat list: `heat_blocked27_p42` re-keyed for package C's one arity change, `sim.thing_pass_depth` 7 -> 9
  parameters (the game tier calls the 9-parameter form at "final": D3 a's `rk0`, D3 b's `ex`): `heat_rekey.py --rename
  "text:sim.thing_pass_depth(7)=>sim.thing_pass_depth(9)"` -- 0 group keys, 579 site paths; 20 groups, 35,894 sites,
  decompressed sha256 `9520cefe18ad4943` (933db58; the build log reads `9520cefe18ad4943`, the same). No other package
  changed a macro's parameter count.
- The pool base: blocked52's first build (r0) refused to assemble -- "the program reached 0x611aa840, which is inside
  the table pool based at 0x60000000" (P8a's code, the unrolled infighting included; the counting pass assembles the
  program unrelocated, as P3.2b's r0 found). `--pool-base 0x80000000 --span-bits 0x7fffffe0`: popcount 1 against
  0x60000000's 2, so every pinned table address is one bit lighter; capacity 67,108,863 words. blocked52 (at 21224a0,
  sha256 `f91abff8a04d37e0`, 7,306 s) built by this line: 51,867 groups -> 42,083 after alias merging, 554,023 tables
  (2,042 s recount), preflight 51,258,464 words (76.4%), 0 broken groups, pinreport 20 of 20 -- superseded by its gates
  (`docs/gp-ledger.md` P8a).
- blocked53, at 1df5f96 with flipjump 1.5.1 at `1cd6e0c`: the source changed after blocked52 (3c6dc06, 0c8a93c,
  99609f3), so the counts cache MISSED and recounted (51,884 groups -> 42,100 after alias merging, 554,091 tables,
  2,006 s); the build took 7,126 s: sha256 `324e3d2281d5c7e1` (`docs/ship-evidence/blocked53_build.log`; preflight 51,264,672
  words, 76.4% of the pool's capacity; the restore set's check 0 labels moved, 0 values changed, 19,074 baked cells
  value-checked). The pin report: 20 of 20 (20 bases moved; `blocked53_pinreport.log`); poolmap 42,100 of 42,100 groups
  placed, 0 broken, the counts cache HIT; 31,376,774 words of pad inside the blocks, 1,003,520 of holes in front of
  them, a gap of 35,692,068 words from the program's end to the pool base (`blocked53_poolmap.log`). The tracked counts
  cache is that recount, and no `src/` file changed after the build, so the line HITs it at the head. Its label table is
  `scratchpad/12m/atlas/blocked53.labels.tsv.gz`. Not rebuilt (class F).

**blocked51 (2026-10-06, M7 P6+P7): the line did not change** -- still `heat_blocked27_p42` (the build log reads its
sha256 `b307cab74b45b336`; no hot site changed width, `hot_sites_width_changed 0`, so no re-key) and still flipjump
1.5.1 at `1cd6e0c` (the build log's first line). The source changed, so the counts cache MISSED ("counts cache is for
a DIFFERENT program -- recounting") and recounted (45,936 groups -> 38,098 after alias merging, 509,644 tables,
1,953 s); the build, at 7739a72, took 6,812 s: sha256 `f736f73d456061ed` (`docs/ship-evidence/blocked51_build.log`;
preflight 58.2% of the pool's capacity, 0 broken groups; the restore set's check: 0 labels moved, 0 values changed,
16,232 baked cells value-checked). The pin report read all 20 hot words through the list's 14 renames (20 of 20, 19
bases moved, 0 unresolved, 4 re-keyed to their one same-keyed label; `blocked51_pinreport.log`). The tracked counts
cache is that recount (committed in 557b60a). **At the head it MISSES**: the gates' oracle fixes after the build
(c93b869, 3c7e381) edited `src/doomfj/reference_model.py` and `monsters.py`, which the signature covers -- so poolmap,
run at the head, refused to price the pads (`blocked51_poolmap.log`: cache `b1aea717`, tree `3c4d2edb`) and the line
recounts once there (~33 min), as after PR #92. Its label table is `scratchpad/12m/atlas/blocked51.labels.tsv.gz`. Not
rebuilt (class F). blocked49 and blocked50 were built by the same line and superseded (`docs/gp-ledger.md`, P6 + P7).

**blocked48 (2026-10-04, M7 P5): the line did not change** -- still `heat_blocked27_p42` (the build log reads its
sha256 `b307cab74b45b336`; no fj macro's positional parameter count changed in P5, bf7efc6, so no re-key) and still
flipjump 1.5.1 at `1cd6e0c` (the build log's first line). The source changed, so the counts cache MISSED ("counts
cache is for a DIFFERENT program -- recounting") and recounted (43,727 groups -> 36,506 after alias merging, 492,804
tables, 2,294 s); the build, at c21df5a, took 7,495 s: sha256 `69890d31f08b450b`
(`docs/ship-evidence/blocked48_build.log`; preflight 57.1% of the pool's capacity, 0 broken groups). The pin report
read all 20 hot words through the list's 14 renames (20 of 20, 19 bases moved, 0 unresolved,
`blocked48_pinreport.log`). The tracked counts cache is that recount (committed in c5977e1); poolmap HIT it
(`blocked48_poolmap.log`). Its label table is `scratchpad/12m/atlas/blocked48.labels.tsv.gz`. Not rebuilt (class F).

**blocked47 (2026-10-04, M7 P4): the line's heat list is `heat_blocked27_p42`, and the line needs flipjump 1.5.1 >=
`1cd6e0c`** (flipjump#364: the screen device's PARTIAL DITTO / KEEP tokens; the build refuses to emit them against a
device that lacks them, gp-combat C7). `heat_blocked27_p42` is `heat_blocked27_p33` re-keyed through
`proj.project_thing` 16 -> 17 and `frame.thing_record_body` 32 -> 33 (the aim parameter; 8846120), so its record
holds 14 renames; the pin report read all 20 hot words through them (20 of 20, 19 bases moved, 0 unresolved,
`blocked47_pinreport.log`). The source changed, so the counts cache MISSED ("counts cache is for a DIFFERENT program
-- recounting") and recounted (41,632 groups -> 35,102 after alias merging, 482,028 tables, 1,914 s); the build, at
3bfe5ed, took 6,886 s: sha256 `9e4ab7d92ff9649d` (`docs/ship-evidence/blocked47_build.log`). The tracked counts cache
is that recount (committed in ded3f4b); poolmap HIT it (`blocked47_poolmap.log`). Its label table is
`scratchpad/12m/atlas/blocked47.labels.tsv.gz`. Not rebuilt (class F).

**blocked46 (2026-10-03, M7 P3.3 + P3.4): the line's heat list is `heat_blocked27_p33`** -- `heat_blocked27_p32a` with
`sim.thing_pass(7)` -> `sim.thing_pass_depth(7)` (3 keys, 579 sites) and the walk's pointer register,
`sim.thing_pass`'s local `hp` -> the depth walk's global `td_p` (3 keys), by `heat_rekey.py`'s new whole-token text
rename (7e97a5a). r0 (`blocked46_r0pins_build.log`) was built with `heat_blocked27_p32a` and its pin report left 3
words UNRESOLVED.

**blocked40 (2026-09-30, M7 P3.1): the line's heat list is `heat_blocked27_p31`** -- the P1.6 list
(`heat_blocked27_p16`, never used by a build: every build from P1.6 to P3.0 pinned with the stale p14, issue #107)
re-keyed through the four parameter-count changes P3.1 made on its paths (`sim.thing_pass` 3 -> 7, `sim.thing_load`
4 -> 7, `frame.thing_load_cold` 4 -> 5, `frame.thing_record_body` 24 -> 28; `p31_heat_rekey.log`). blocked40's build
(`blocked40_build.log`) used the list whose rename record held only those four, so its first pin report left one
word UNRESOLVED -- P1.4's `stream.emit_col_lines 45 -> 38` was lost (`blocked40_pinreport_r0_unresolved.log`).
`heat_rekey.py` now accumulates the record, and the tracked list is the same groups regenerated along the chain
p14 -> p16 -> p31 with the fixed tool (`scratchpad/12m/heat_rekey.py --in heat_blocked27_p14.json.gz` with P1.6's
`frame.thing_record_body:25:24`, then the four above): groups byte-equal, so the build's layout input is unchanged;
decompressed sha256 `716223ee86683d91` (the build log's list read `1468d7fbf91b235d`, the one-step record;
the regeneration re-run and byte-compared: `p31_heat_regen.log`).

**blocked31 (2026-09-27, M7 P1.4): the line changes its heat list** to
`--pin-heat scratchpad/12m/heat_blocked27_p14.json.gz` -- blocked27's list re-keyed through the four
parameter-count changes P1.4 made on its paths (`heat_rekey.py`; the list records the renames, and
pinreport reads the hot words through them). The source changed, so the counts cache MISSED and
recounted (21,118 groups before alias merging, 342,750 tables, 2,044 s) and the build, at 311f23f,
took 7,185 s: sha256 `773b840ca044e39b` (`docs/ship-evidence/blocked31_build.log`). All 20 hot groups
matched and pinned. The tracked counts cache is that recount, and the same line at 10d7b48 -- the same
`src/` tree as 311f23f; only pinreport.py and logs differ -- HIT it and produced `773b840ca044e39b`
again, label table included (`89226fa8...`; `blocked31r_build.log`, 4,765 s) -- **VERIFIED
byte-identical.** Both commits predate the branch's rebase, so pushed tags keep them:
`evidence/p1.4-build` and `evidence/p1.4-rebuild` (every such commit P1.4's evidence names has one --
`docs/gp-sprite-column.md`, Provenance). The branch was then rebased onto main, under P1.3's review
refactors, and its review stated the slot layouts in `wall_renderer` (R6): the build's own path hands
the assembler the same files and the same persist tuple at 311f23f and at 91eaeec, the PR's last
`src/` change (`p14_emit_neutral.log`), so the binary is blocked31's -- but the head's sources sign the
counts cache differently, so on main this line recounts once (~34 min, the same counts) until the
next ship build re-signs it. Its label table is `scratchpad/12m/atlas/blocked31.labels.tsv.gz`.

**blocked32 (2026-09-28, M7 P1.5): the line is unchanged** -- the same heat list; P1.5 changed no
parameter count on the hot paths, and all 20 hot groups matched and pinned. The source changed, so
the counts cache MISSED and recounted (23,560 groups before alias merging, 348,682 tables, 2,369 s)
and the build, at 7cdfb97 (tag `evidence/p1.5-build`), took 8,794 s: sha256 `89c3cf6348258eeb`
(`docs/ship-evidence/blocked32_build.log`). The tracked counts cache is that recount. Class F -- the
pixels move -- so no byte-identical rebuild. Its label table is
`scratchpad/12m/atlas/blocked32.labels.tsv.gz`.

**blocked33 (2026-09-28, M7 P1.6): the line is unchanged** -- the same heat list (p14): every hot
group matched and all 20 hot words pinned (`blocked33_pinreport.log`: lost 0). The source changed,
so the counts cache recounted (23,549 groups before alias merging, 348,100 tables, 2,344 s) and
the build, at e972725 (tag `evidence/p1.6-build`), took 8,515 s: sha256 `7be00f1e51c63678`
(`docs/ship-evidence/blocked33_build.log`). The tracked counts cache is that recount. Class F, so
no byte-identical rebuild; emission-neutral across the rebase (`p16_emit_neutral.log`). Its label
table is `scratchpad/12m/atlas/blocked33.labels.tsv.gz`.

**The play command** (options verified against `fj --help`: `--run`, `--io pc`, `--flat-max-words N`):

```
fj --run build/doom_e1m1_blocked53.fjm --io pc --flat-max-words 134217728
```

`--run` is not optional (`fj a.fjm` assembles); the flat window must be the full 2^27 words or
the engine runs hybrid/paged. `m2_std_gate` drives this same `PcIO` composition in-process, so a
gate PASS is a statement about the object a person runs.

## 2. The gate, in order; a failure stops the process

**2a. Features (class F, owner decision D8, 2026-09-26; `docs/handoff-gameplay.md`).** The steps
below are the gate for a change whose pixels are IDENTICAL (class S): B SLOWER never ships. A
gameplay FEATURE changes pixels by design, and msframe cannot judge that (it says the speed is
meaningless when the arms' pixels differ). A class-F change ships on: the byte- and state-exact
gates; CAP-22 (the owner's binding metric on the frozen combat set, <= 22,000,000); and size. Its
msframe time is recorded as the feature's price; ~90 ms/frame is a tripwire that must be
explained before shipping.

1. **Correctness, byte-exact.** `scratchpad/m2_std_gate.py --fjm <new>` (the full-game play-test:
   menu, 154-frame walk, a door opened and carried across two resets; every game frame byte-exact
   against the oracle) and `scratchpad/m3_gate.py --fjm <new>` (menu and world). `m5_gate.py` is
   NOT a gate for a menu-booting binary -- it never presses Enter and fails vacuously on every
   game-tier binary, changed or not (handoff 14.4). tests/host green. And the PIN REPORT:
   `python scratchpad/12m/pinreport.py --fjm build/<new>.fjm --labels <its label table>
   --counts-cache scratchpad/12m/_counts_game.json.gz --heat <the line's heat list, scratchpad/12m/heat_blocked27_p8a.json.gz since blocked53>
   --build-log <its build log>` must exit 0 -- every hot word pinned (a moved base is reported, not
   a failure; `--heat` lets it re-derive a heat build's layout).
2. **Speed, by the instrument.** `python scratchpad/12m/msframe.py --a build/<new>.fjm --against
   shipped --note "<what changed>"`. The verdict must be **FASTER**, or NOT SEPARATED with a stated
   reason to ship anyway (size, a feature). **B SLOWER does not ship**, whatever the op count says
   -- 2026-09-13 built three binaries whose op deltas said -25% and whose verdicts said SLOWER.
   Check the yardstick line: if it is below ~3.5 G the box was not quiet and the run is not a
   measurement. `--against shipped` re-measures the frozen binary live, so `--a build/<shipped>.fjm
   --b build/<new>.fjm` is the same measurement; what `--against` adds is the check that arm A IS
   the frozen binary (its hash). Use the explicit form only with the shipped sha256 in the record.
3. **The owner's metric.** `python scratchpad/12m/gamespeed.py --fjm build/<new>.fjm` (both
   targets: (mean+p80)/2 <= 22,000,000 ops/frame -- 20,000,000 until the combat game shipped; D1 moved it to 22M at M7 P8 (`gamespeed.SPEED_TARGET`, 6dea24d; `fencecheck.py` parses no 20M literal) -- size <= 43% -- RAISED from 35% in M7 P4.0 (gp-combat C2, 40%), to 42% by the owner after P5 (2026-10-04) and to 43%
   by the owner at P10 (2026-10-13: "Raise the cap to 43%", P10's one-pass binary at 42.06%)), then a separate `--validate` run
   (it is a mode: 9/10 distinct end cells on blocked53, the selftest's floor 6) and `--selftest` (SELFTEST PASS; its N6g is the only
   check that the host test's recorded keys are still what the planner plays -- CI does not run
   it). `--validate` replays the ORACLE; when the new binary moves, collides or opens doors
   differently from the shipped one, also run `scratchpad/12m/gamespeed_trail.py --fjm
   build/<new>.fjm --labels <its label table>` (TRAIL, CONTROL-POSE and CONTROL-DOORS must PASS) and
   re-record `gamespeed.BINARY_ENDS` and `BINARY_DOORS` from its output.
4. **Record it, or it did not happen.** The build's command line, its counts-cache path, its label
   table (`build_labeled.py --labels ...` produces it), its sha256, the ledger row of step 2, and
   the numbers of step 3 -- into section 1 of this file and the commit message. Then
   `msframe.py --a build/<new>.fjm --save-baseline shipped` on a quiet box.

**How blocked27 departed from this order (2026-09-25), stated so it is not copied as the rule.**
Lead A ran step 2 as written (`--against shipped`, yardstick 3.51 G -- at the quiet-box line; it is
lead A's only stand-alone verdict. The combined run measured the binary CONTAINING lead A faster than
blocked25 at yardstick 3.65 G, which does not re-measure lead A's own x1.072). Lead B was measured against lead A's binary with
`--a/--b`, because lead A was the base it was built on and was never frozen. The combined step 2
(`--a blocked25 --b blocked27`; the ledger row carries both sha256s, fc46c28c5f2bbac8 and 38b09a7331f4f52b) ran at 22:43, AFTER the step-4 re-freeze
at 22:40 -- so `shipped` briefly named a binary whose combined verdict was not yet in. The freeze
comes last; the order above is the one to follow.

## 3. The ideas to keep (each with the evidence that earned or limited it)

**Measurement -- these are what kept the session honest and they are cheap.**
- `msframe` is the metric; ops/frame is a proxy. Placement moved ops/frame by 46% on one program
  (13.4) and moved the per-op rate by 20% the other way. Judge on ms/frame, inside one run.
- `--selftest` before measuring; a background process under the busy threshold costs 5-20% and
  the yardstick is the tell (13.2).
- Engine A/B: `--env-a/--env-b MSFRAME_FJCORE_PYD=<pyd>` switches the engine per arm;
  `scratchpad/12m/with_engine.py` runs any gate on a candidate `.pyd`; `engine_diff.py` is the
  15-case edge differential with an R9 self-test; `pgo_build.py` builds MSVC PGO for a layout
  experiment. The installed `.pyd` stays the shipped one until the verdict.

**The engine is closed** (12-13): 12 -> 3 branches per op, a fully fall-through PGO layout, the
jump-word hoist (2a, re-tested in the engine: marginally slower), TLB/large pages, the flip store
-- all NOT SEPARATED. The per-op time is the memory chain, and 242 M fj/s is what the game's
83.5%-L1 instruction stream costs on this machine (the sieve's 378 M is 99.4% L1). Do not spend a
session there again without a new mechanism.

**Placement and pins are where ops hide** (13.4, 14.6-14.8). The blocking pass decides, from the
program's table COUNTS, which shared source words are pinned; a pinned word dispatches by a
short index flip, an unpinned one by a whole-address flip. Any change to the counts -- adding or
removing code -- re-rolls those decisions: deleting 25% of executed code cost 6 M ops/frame of
`hex.tables.res/ret` and `hex.mul.ret` chains. After ANY emitter change: profile
(`mkprof3.py T` + `prof3run.py` + `timeobj.py` with the new label table) and read the
`m1_reset`-labelled slice -- it is the wflip-chain area, and a jump there is the signature; then
the flipped-bit histogram of the chains (14.8's script) names the words. A good binary is one
whose hot words came out pinned; the ladder's knobs (`--spread 2 --max-slot-ops 512 --span-bits
0x9fffffe0 --pin-broken --width-buckets --merge-aliases`) were worth ~2 M on the experiment. Since blocked53 the pool
is based at 0x80000000 with span 0x7fffffe0 (popcount 1: every pinned table address one bit lighter than at
0x60000000); its effect on ops was not measured apart from P8a's code -- blocked52's r0 moved it for capacity, not speed.

**Hot-code alignment** (14.8): `pad 2097152` before the frame's walk code puts the shared leaves at
word 2^22 (bit 2^27), popcount 1. Measured +0.5 M ops/frame better than the same program
unaligned, on the experiment binary only -- a candidate, not a proven win on the shipped program.
`scratchpad/12m/engine_folds/patch_nobind_align.py` is the form.

**Thing binding, for the monster work** (14.9): the per-frame `sim.bind_things` costs ~7.5 M
ops/frame (25% of the frame) to rebuild 75 monsters' per-leaf lists that today never change. It
stays -- monsters will move -- but the rebuild should become PER MOVE (DOOM's
P_SetThingPosition: re-bind only the thing that moved), which costs ops proportional to movement.
Baking the lists (`patch_nobind.py`, `baked_thing_lists` with its reference-model tests) is only
valid for a static world and was reverted for that reason.

**The stl pad round is closed, pad by pad** (handoff 15, 2026-09-14). The relocated family's pads
(`exact_xor`/`double_`/`triple_exact_xor`) are dead by construction under blocking: the pad is the
slot width the counting pass records, so a wider pad is `declined_too_wide` for every table and
the group's pin with it. The ten pads on macros the pass never relocates were priced per pad by
the wflip-site census (-838 K direct, +338 K shift, -500 K net predicted; -431,322 ops/frame
measured on msframe's walk, binding 18,762,374 and 32.11% -- both better) and then MEASURED IN
TIME on a quiet box: 81.6 -> 83.4 ms/frame, 243 -> 233 M fj/s, slower in every pair, median
0.979 -- NOT SEPARATED by the rule, and the gate's clause for that ships only with a stated
reason, of which there is none (size is already under target). Fewer ops, a lower per-op rate:
ops/frame is half of frame time (13) again; what the padding does to the memory chain is the
hypothesis. They stay reverted; the per-pad TIME question (which of the ten pay in time -- the zero-space `to_flip`
reorder and the two-site `mul.init after_add` first) needs a per-pad timing sweep, not the census.
Two doom-side leads from the same census: the S2 sparse pads at 91 hot sites are
`declined_too_wide` under blocking (945,807 ops/frame inline; plain `hex.mov` there would let
them block), and `hex.shifts.shl/shr_bit_once`, `hex.inc1`, `hex.mul.clear_carry` dispatch inline
through pinned words (1.86 M ops/frame together).

**Both doom-side leads, measured and shipped** (2026-09-25, blocked27; handoff 15.4). The hot sites
block once HOT_PAD = HOTTER_PAD = 16, the plain table's own alignment: -653,225 ops/frame and x1.072
against blocked25 -- fewer ops AND a higher rate. The shift macros block once flipjump writes their
tables out literally (tomhea/flipjump#362: the detector reads only literal `a;b` ops, so adding their
names to SAFE_TABLE_MACROS alone was a measured NO-OP -- the same span, the same .fjm size and the
same 425,236 blocked tables as lead A's build, `docs/ship-evidence/padB_noop_build.log`; its sha256
was not taken):
-970,628 binding ops and x1.031 on top, which took the 10x400 escalation to separate (5x200 had one
tied pair). Together, same session: 81.0 -> 74.7 ms/frame, x1.085. What did NOT carry: `hex.inc1`'s
entry 15 falls through into its carry tail (the detector refuses it, rightly), and
`hex.mul.clear_carry` is a return-address wflip, not a table -- that is the parked pad idea above.

**The reset** (12.7): its restore walk is already in address order; its cost is its own
straight-line code once per frame. Restore fewer cells (a dirty set) is the only lever left there.

## 4. Where the leverage is now, ranked by measured size

1. Ops per frame, by object (10.1): `bind_things` 25% -> per-move rebind; `seg_pass2_leaf` 14.5%;
   `m1_reset` 13.2%; `thing_pass_leaf` 8.6%; `seg_pass1_ts` 7.6%; `seg_pass1` 6.3%; bspcode 5.9%.
   At 74.7 ms and 18.22 M ops (blocked27), one million ops removed is ~4.1 ms/frame -- IF the pins
   survive.
2. Pins/placement of the hottest shared words, measured per build (above).
3. The clock: 3.5-3.7 GHz under this load; a performance plan on wall power is +20-30% for free.

## 5. E1M2 (M8): the second level's binary, its own numbers

E1M2 is its OWN binary (`build/doom_e1m2_<id>.fjm`); E1M1's standing number (section 1) is untouched by it.
**`build/doom_e1m2_r4.fjm`** (2026-10-18, branch `m8p-final` at 925af820; sha256 `9a112139f3d35db3`) is the
standing E1M2 binary: r3 + THE PLAYTEST'S POLISH (`docs/playtest-e1m2.md`; the owner 2026-10-18: "if you can implement
it at +0.5% speed penalty, go for it") -- the door heights (`doors.door_neighbours`: two-sided neighbours on every map
but E1M1 / the legacy one; E1M2's doors 54 -> 228, 258 -> 196, 139 -> 156, 30 / 266 -> 196), the animated sector lights
(SECTOR_LIGHTS), the scrolling wall (WALL_SCROLL), the switch textures (SWITCH_TEX), the MAP page (AUTOMAP: a menu item
and the M key, the level's lines and a red dot where the player is), the telefrag and the teleport fog. Class F (its
pixels differ from r3's by design). Its gates, each run solo on it:

| gate | result |
|---|---|
| `p2a_gate` (DOOMFJ_MAP=E1M2) | PASS -- 21 scenarios (the harness now passes the world's animated lights to the oracle's picture, 25663875, and skips an OPTIONAL cell the binary lacks, a48390a6) |
| `m2_std_gate --map E1M2` | PASS -- 258 frames byte- and state-exact |
| `m3_gate --map E1M2` | PASS -- 88 frames byte- and state-exact (the tour now opens the MAP page; the program halts at frame 88 as the oracle does) |
| `hurt_gate` / `fight_gate` / `die_gate` (--map E1M2) | PASS -- 7 / 43 / 17 scenarios |
| B0, `combat_scenarios_e1m2_v1.json` (keys cfec92103602fc05; the owner: "Im ok with this set") | OK -- 11/11 runs state- and pixel-exact; binding 20,058,861 ops/frame (r3 19,909,950: +0.75%; CAP-22 headroom 1,941,139) |
| `gamespeed_trail --map E1M2 --record` | PASS; the record re-written (`scenarios/e1m2/gamespeed.json`, 93813efc) |
| `gamespeed --map E1M2` | SPEED binding 20,591,876 ops/frame PASS (r3 20,408,337: +0.90%); SIZE 83,467,260 words = **62.19% of 2^27** (span 92.06%; the owner: "Size is ok") |
| `msframe --map E1M2 --a build/doom_e1m2_r4.fjm --save-baseline shipped_e1m2` | **70.2 ms/frame** [70.1 .. 70.9], 195.1M fj/s, 13,697,361 ops/frame (r3 69.8: +0.57% -- the polish's whole price; not split per feature) |
| E1M1 identity | `emit_baseline --check` at 93813efc: every certified and hosted part SAME; only the standalone banks / main / state DIFFER -- the E1M1 MAP page (17536cad), on purpose (section 1); tests/host 2,219 passed |

The build command (section 1b's, with E1M2's pool at `--spread 1`: at spread 2 one 97,647-table group overflows the
pool, 134.6%):

    python scripts/emit_check.py E1M2 --then scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/e1m2_r4.labels.tsv.gz -- game --wad tests/fixtures/freedoom_e1m2.wad --map E1M2 --out build/doom_e1m2_r4.fjm --pool-base 0x80000000 --span-bits 0x7fffffe0 --pin-state-cells --merge-aliases --spread 1 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --one-pass-blocks --counts-cache scratchpad/12m/_census_game_e1m2_r4.json.gz --pin-heat scratchpad/12m/heat_blocked27_p10.json.gz

(7,181 s; peak private 17.21 GB, min available RAM 0.02 GB -- rule 1 is absolute for it.) Play: `fj --run build/doom_e1m2_r4.fjm`.
REBUILD VERIFIED: rebuilt from this command at 93813efc (after the E1M1 MAP page merged) as `build/doom_e1m2_r4b.fjm`
(7,090 s) -- BYTE-IDENTICAL, sha256 `9a112139f3d35db3f71a9b2c0fb57a9e383b342fd2d42e776e072b97fbb57f45` both: the build
reproduces, and the E1M1 change left E1M2 alone.

**Recorded simplifications still standing** (`docs/handoff-e1m2.md` 3): none of the playtest's list (the five doors
that opened to 148, issue #104 F1, now open to their DOOM heights). Follow-ups: #147.

<details><summary>r3, the binary r4 replaced</summary>

**`build/doom_e1m2_r3.fjm`** (2026-10-18, branch `m8-e1m2-final` at 9b8ef2c0; sha256 `f18d00c66d211cab`): every M8
rung merged -- the slot cap (F1.4), the yellow / red cards and the new gives (F4/F7), every door kind (L2), the WR
teleports (L4), the ML_SOUNDBLOCK flood (L5), the lifts / one-shot floors / pickups on movers (L3, F1.3) -- and
**NO stand-in** (`scripts/emit_check.py E1M2` with none: the build's preflight). r3 = r2 + the CR of #146's fix (a
moving seg closed at EVERY state takes the solid path: E1M2 lines 2033 / 2062 / 2050 / 2075); its proof is p2a S15,
which FAILS on r2 (pixels part at frame 0, 285 px, state exact) and PASSES on r3. Its gates, each run solo on it:

| gate | result |
|---|---|
| `p2a_gate` (DOOMFJ_MAP=E1M2) | PASS -- 21 scenarios incl. S14a/b (linedef 1199) and S15 (lines 2033, 2075); N/A: the blue card on a mover floor, the yellow / red doors, S13 |
| `m2_std_gate --map E1M2` | PASS -- door 172 at hard (monsters on its ground: the second, monsters-allowed pass), 258 frames byte- and state-exact |
| `m3_gate --map E1M2` | PASS -- 75 frames byte- and state-exact; the skills told apart by the binary's `g_skill` (the spawn view is one picture at every skill) |
| `hurt_gate` / `fight_gate` / `die_gate` (--map E1M2) | PASS -- 7 / 43 / 17 scenarios (9 roles N/A on E1M2: `scenarios/e1m2/gates.json`) |
| B0, `combat_scenarios_e1m2_v1.json` (keys cfec92103602fc05, PLANNED, not frozen) | OK -- 11/11 runs state- and pixel-exact; binding 19,909,950 ops/frame (CAP-22 headroom 2,090,050) |
| `gamespeed_trail --map E1M2 --record` | PASS -- the record equals the binary on every frame of every run; CONTROL-POSE parts |
| `gamespeed --map E1M2` | SPEED binding 20,408,337 ops/frame PASS (<= 22M); SIZE 81,137,244 words = **60.45% of 2^27** (span 91.94%) |
| `msframe --map E1M2 --a build/doom_e1m2_r3.fjm --save-baseline shipped_e1m2` | **69.8 ms/frame** [69.1 .. 71.3], 194.3M fj/s, 13,567,769 ops/frame |
| E1M1 identity | `emit_baseline --check` EMISSION IDENTICAL on the merged tree; tests/host 2,121 passed |

The build command (section 1b's, with E1M2's pool at `--spread 1`: at spread 2 one 97,647-table group overflows the
pool, 134.6%; at spread 1 the pool is 82.6%):

    python scripts/emit_check.py E1M2 --then scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/e1m2_r3.labels.tsv.gz -- game --wad tests/fixtures/freedoom_e1m2.wad --map E1M2 --out build/doom_e1m2_r3.fjm --pool-base 0x80000000 --span-bits 0x7fffffe0 --pin-state-cells --merge-aliases --spread 1 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --one-pass-blocks --counts-cache scratchpad/12m/_census_game_e1m2_r3.json.gz --pin-heat scratchpad/12m/heat_blocked27_p10.json.gz

(6,680 s; peak private 16.85 GB -- the box's whole RAM: rule 1 is absolute for it.) Play: `fj --run build/doom_e1m2_r3.fjm`.
REBUILD VERIFIED: rebuilt from this command at 71fa53e9 as `build/doom_e1m2_r3b.fjm` (6,395 s) -- BYTE-IDENTICAL, sha256
`f18d00c66d211cab26e69585b79ee2a45e52c546a0fbb3cf66d3c037240f574f` both.

</details>

## 6. E1M3 and E1M5 (M8 wave 1): their own binaries, their own numbers

Each level is its OWN binary; E1M1's standing number (section 1) is untouched by them -- E1M1 rebuilt on the same branch
is BYTE-IDENTICAL to blocked65 (`3a2c9564...`, `build_episode --maps E1M1`, 2026-10-29). Built on branch `m8-adopt`
(m8-episode + the stl adoption + w2fix-wip; flipjump 1.6.0 at 9877f25) by the final creator (`scripts/build_episode.py`,
its registry rows `LEVEL_SPREAD`), every gate run solo through `scripts/heavy.py`. Evidence: `docs/ship-evidence/e1m3_v1_*.log`,
`e1m5_v1_*.log`, `e1m3_e1m5_v1_msframe.log`. The v1 combat sets were frozen from the drafts the day they were built
(the owner's standing delegation; `scratchpad/gp/scenarios/combat_scenarios_e1m{3,5}_v1.json`).

| gate | **E1M3** (`build/doom_e1m3_v1.fjm`, sha256 `71d56069bb2db8c3`) | **E1M5** (`build/doom_e1m5_v1.fjm`, sha256 `4e8c0ed5e54a85ae`) |
|---|---|---|
| `emit_check` (asserts on, no stand-in) | PASS | PASS |
| the build (spread) | 998 s (spread 1) | 775 s (spread 2: the pool fits) |
| `p2a_gate` | PASS -- 6 scenarios, 9 N/A | PASS -- 5 scenarios, 9 N/A |
| `m2_std_gate` | PASS -- 75 frames byte- and state-exact | PASS -- 424 frames |
| `m3_gate` | PASS -- 88 frames | PASS -- 88 frames |
| `hurt_gate` / `fight_gate` / `die_gate` | PASS -- 7 / 34 (8 N/A) / 13 (3 N/A) scenarios | PASS -- 7 / 24 (18 N/A: no barrel, ...) / 13 (3 N/A) |
| B0 on its v1 combat set | OK -- 11/11 runs exact; binding 15,750,448 | OK -- 11/11; binding 17,074,364 |
| `gamespeed_trail --record` | PASS, CONTROL-POSE and CONTROL-DOORS PASS (`scenarios/e1m3/gamespeed.json`) | PASS, CONTROL-DOORS N/A (no tour reaches a door) (`scenarios/e1m5/gamespeed.json`) |
| `gamespeed` | SPEED binding 14,652,491 ops/frame PASS; SIZE 60,373,968 words = **44.98%** of 2^27 (span 79.42%) | SPEED 11,851,855 PASS; SIZE 45,721,482 words = **34.07%** (span 83.58%) |
| THE PLAYTHROUGH (`playthrough_gate --skill easy`, the pinned seed) | **PASS -- LEVEL COMPLETE at frame 3147**, byte-, palette- and state-exact on all 3,157 frames (777 s) | **PASS -- LEVEL COMPLETE at frame 4257**, exact on all 4,267 frames (822 s) |
| `msframe --save-baseline shipped` (the map's timed walk `scenarios/<map>/msframe.json`) | **73.5 ms/frame** [72.8 .. 74.7], 233.5M fj/s, 17,158,103 ops/frame -> `shipped_e1m3` | **58.2 ms/frame** [58.0 .. 58.7], 224.0M fj/s, 13,028,121 ops/frame -> `shipped_e1m5` |
| REBUILD | **BYTE-IDENTICAL** (`71d56069bb2db8c313c38b6775d90e1dad2a283c9d5919092164410b13adc784`) | **BYTE-IDENTICAL** (`4e8c0ed5e54a85ae4f7b9329b0bff7f698f3a63faaac3b19b753ffeb001593b2`) |
| **THE SPEED SET** (the owner, 2026-10-29: the level's own playthrough, 11 windows of 100 world frames from NEW GAME to LEVEL COMPLETE; `playthrough_gate --speed-json`, on the current steering) | **binding 12,781,307** ops/frame (mean 12,106,763, p80 13,455,852) -- LEVEL COMPLETE at world 2279, exact on all 2,293 frames | **binding 12,698,851** (mean 11,826,507, p80 13,571,195) -- LEVEL COMPLETE at world 4253, exact on all 4,267 frames |

Size: E1M3 at 44.98% is over the 43% cap -- the owner, 2026-10-24: "above 43% size is OK".
The build command (section 1b's, the map's wad and spread; `scripts/build_episode.py --maps E1M3` runs exactly it):

    python scratchpad/12m/build_labeled.py --labels scratchpad/12m/atlas/e1m3_v1.labels.tsv.gz -- game --wad tests/fixtures/freedoom_e1m3.wad --map E1M3 --out build/doom_e1m3_v1.fjm --pool-base 0x80000000 --span-bits 0x7fffffe0 --pin-state-cells --merge-aliases --spread 1 --spread-min-count 256 --max-slot-ops 512 --pin-broken --width-buckets --one-pass-blocks --counts-cache scratchpad/12m/_census_game_e1m3_v1.json.gz --pin-heat scratchpad/12m/heat_blocked27_p10.json.gz

(E1M5: `e1m5` / `E1M5` and `--spread 2`.) Play: `fj --run build/doom_e1m3_v1.fjm`, `fj --run build/doom_e1m5_v1.fjm`.

**Not done yet (recorded, not hidden):** the per-level SPEED PASS (`docs/episode-plan.md` 4.7: a heat list from each
level's own profile; both build on E1M1's `heat_blocked27_p10`) and the written playtest note (4.6) -- the playthrough
gate played each level start to exit on the binary. The playthroughs ran on the steering before 2026-10-29's lift rules
(8183305d); under the current steering E1M3's pin finishes at world 2279 and E1M5's at 4253 (model only).

## 7. E1M9 (M8 wave 2): its own binary, its own numbers

Built and gated as section 6's levels (branch `m8-adopt`, the final creator, every step through `scripts/heavy.py`).
Evidence: `docs/ship-evidence/e1m9_v1_*.log`. **`build/doom_e1m9_v1.fjm`**, sha256 `33da9dbcc55399a0`, spread 1.

| gate | result |
|---|---|
| `emit_check` / the build | PASS / 907 s |
| `p2a_gate` / `m2_std_gate` / `m3_gate` | PASS -- 6 scenarios (8 N/A) / 194 frames / 88 frames, byte- and state-exact |
| `hurt_gate` / `fight_gate` / `die_gate` | PASS -- 7 / 31 (12 N/A) / 15 (1 N/A) scenarios |
| B0 on its v1 combat set (keys `97a8a6475101cb0b`) | OK -- 11/11 runs exact; binding 13,649,248 ops/frame. The set was RE-PLANNED before its first pass: the draft's R0-s21 (params aggressive) died in b0's PROXY mirror at frames 98, 99 (`e1m9_v1_b0_before_replan.log`, 2026-10-29); `scenarios_map.mirror_deaths` now refuses a proxy-mirror death too, and R0-s21 is planned steady |
| `gamespeed_trail --record` | PASS; CONTROL-POSE and CONTROL-DOORS PASS (`scenarios/e1m9/gamespeed.json`) |
| `gamespeed` | SPEED binding 7,732,082 ops/frame PASS; SIZE 55,452,414 words = **41.32%** of 2^27 PASS (span 77.26%) |
| THE PLAYTHROUGH (`--skill easy`, seed 2) | **PASS -- LEVEL COMPLETE at frame 4663**, byte-, palette- and state-exact on all 4,673 frames (987 s). Its first run parted at frame 3241 on `p_rad` (binary 2099, mirror 2100): the GATES' MIRROR never counted the timed powers down (`MonsterPhase.weapon`, fixed 00d6ca5e); the binary was right (DOOM's P_PlayerThink order) |
| `msframe --save-baseline shipped` | **37.7 ms/frame** [37.4 .. 38.8], 208.2M fj/s, 7,849,063 ops/frame -> `shipped_e1m9` (a first measurement, 40.1 [38.8 .. 41.3], ran beside the combat planner and was replaced) |
| REBUILD | **BYTE-IDENTICAL** (`33da9dbcc55399a09d4a6e2db476c02a9f0715273f3f31a7f860093c4c930a48`) |
| **THE SPEED SET** (the playthrough's 11 windows of 100 world frames, as section 6) | **binding 14,577,947** ops/frame (mean 12,711,601, p80 16,444,293: a window at world 2280 heavier than any B0 run) -- LEVEL COMPLETE at world 4659, exact on all 4,673 frames |

The build command: section 6's with `e1m9` / `E1M9`, `--spread 1`. Play: `fj --run build/doom_e1m9_v1.fjm`.
The playthrough ran on the current steering (8183305d: the lift rules E1M9 needed -- its lift 109 called down from
its own SR lines). Not done yet, as for section 6: the per-level speed pass and the written playtest note.
