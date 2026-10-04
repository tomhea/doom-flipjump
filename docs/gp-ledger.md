# The M7 ledger: one row per phase-1+ rung (docs/handoff-gameplay.md section 10)

Every rung declares its kill criteria HERE, before its first build, and fills its row after. The
row: ops attributed to the rung's own code (`profx`), the binding delta on the frozen combat set v2
(`scratchpad/gp/b0_scenarios.py`, (mean + p80)/2 against B0 17,760,774 / proxy 18,107,313), size,
ms/frame (`msframe.py`, ship-gate section 2), the pin report (`pinreport.py`). The standing
kill rules (handoff section 10): attributed ops > 1.25x the rung's budget -> redesign; the
cumulative projection > 22M minus the remaining budgets minus a 15% reserve -> stop for the owner.

## P1.1 pin protection (class S) -- declared 2026-09-27, before the build

**What**: flipjump `BlockPool(heat=)` (tomhea/flipjump#363) + `build_blocked.py --pin-heat` with
the heat list of blocked27's profile (`heatsites.py`, top 20 groups); the same program as blocked27.

**Budget**: ESTIMATE -1.27M ops/frame (heat-ordered indices, `profx/heatindex.py`); no new code.

**Kill criteria** (any one -> the binary does not ship):
1. `m2_std_gate` or `m3_gate` not byte-exact.
2. `pinreport.py`: a hot word of the list not pinned.
3. `msframe.py --against shipped`: B SLOWER (ship-gate section 2). NOT SEPARATED ships only with the
   stated reason "foundation for P3" (the handoff's clause), never SLOWER.
4. The build's heat report: a hot group unmatched, ambiguous or without a block (the pool raises).

**Row** (2026-09-27, `build/doom_e1m1_blocked28.fjm`, sha256 `9fe88c6187a82921`; logs in
`docs/ship-evidence/blocked28_*`):

| measure | blocked27 | P1.1 (blocked28) | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 17,665,168 | 16,357,904 | -1,307,264 (-7.4%) |
| combat set v2 binding (b0_scenarios) | 17,760,774 | 16,448,992 | -1,311,782 (-7.4%) |
| ... with strafe's collision (proxy) | 18,107,313 | 16,794,857 | -1,312,456 |
| ms/frame (msframe, one quiet run) | 75.2 | 73.4 | NOT SEPARATED (all 5 pairs faster, x1.025) |
| fj ops/s | 242.4 M | 229.8 M | -5.2% |
| size (% of 2^27) | 32.23% | 32.21% | -24,510 words |
| hot words pinned (pinreport) | 20/20 | 20/20 (19 bases moved, by design) | 0 lost |

**Verdict against the kill criteria:** 1 m2_std_gate PASS, m3_gate PASS (221 frames byte-exact, 0
differ); 2 pinreport 20/20 pinned, exit 0; 3 msframe NOT SEPARATED, never slower -- ships as the
foundation for P3; 4 heat report: 20 hot groups matched, 0 missing, 0 ambiguous, 35,894/35,894
listed sites took their index. The ESTIMATE was -1.27M; measured -1.31M on both metrics.
Attributed ops (profx): n/a -- the rung adds no code.

## P1.2 player collision cells (class S) -- declared 2026-09-27, before the build

**What**: the player's `check_position` stops walking the 256-unit blockmap through packed tables
(`hex.read_table_packed`, ~6.8K ops per line tested, ~576K per check) and runs a CELL instead: a
jump tree on the 16.16 position finds the 32-unit cell, the cell's stub calls one stub per
candidate line, and each line stub XORs its constants into fixed argument cells and calls ONE
shared line test (`sim.line_test`: PIT_CheckLine with no conversions). A cell lists every line whose
bbox a box centred anywhere in the cell can touch -- exact interval arithmetic at 16.16, so the
verdict equals the oracle's all-lines sweep by construction. A door line reads `dstate` against its
pass state at test time; the one-bit `lnrow` wflip goes. Design: `docs/gp-collision-cells.md`.

**Budget**: -1.0 .. -1.4M ops/frame on the binding metric (handoff section 10). ESTIMATE from
phase 0: one try ~613K today (MEASURED: seed walk 35.4K + check_position 576K); on cells ~40-45K,
dominated by the unchanged seed walk.

**Kill criteria** (any one -> the binary does not ship):
1. `tests/host/test_collision_cells.py`: a cell missing a line some box in it can touch (the
   corner check, with its mutated-entry control), or the cell model disagreeing with
   `ReferenceModel.check_position` on the sample (refusals and door states included).
2. `tests/fj/test_collision_fj.py`: the emitted cell routine disagreeing with the oracle.
3. `m2_std_gate` or `m3_gate` not byte-exact.
4. `msframe.py --against shipped`: B SLOWER. NOT SEPARATED ships only as "foundation for P3".
5. The reclaim: gamespeed binding down by less than 0.8M ops/frame (the budget's low end / 1.25)
   -> redesign before shipping.
6. Size over 35% of 2^27, or `pinreport.py`: a hot word of the heat list not pinned.

**Row** (2026-09-27, `build/doom_e1m1_blocked29.fjm`, sha256 `a90f172ee718be63`; logs in
`docs/ship-evidence/blocked29_*`):

| measure | shipped (P1.1, blocked28) | P1.2 (blocked29) | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 16,357,904 | 14,780,831 | -1,577,073 (-9.6%) |
| combat set v2 binding (b0_scenarios) | 16,448,992 | 15,485,242 | -963,750 (-5.9%) |
| ... with strafe's collision (proxy) | 16,794,857 | 15,519,673 | -1,275,184 (-7.6%) |
| collision ops/frame (profx, gamespeed games) | 1,475,186 (blocked27's profile; the same program) | 122,218 | -1,352,968 (-91.7%) |
| ms/frame (msframe, one quiet run) | 74.0 | 64.4 | B FASTER (all 5 pairs, median x1.155) |
| fj ops/s | 227.8 M | 235.4 M | +3.3% |
| size (% of 2^27) | 32.21% | 27.35% | -6,522,370 words |
| hot words pinned (pinreport) | 20/20 | 20/20 (4 re-keyed by their heat key; 19 bases moved) | 0 lost |

**Verdict against the kill criteria:** 1 `test_collision_cells.py` passes, with its mutated-entry
control and the oracle sample (`p12_r1_pass.log`); 2 `tests/fj/test_collision_fj.py` passes (the same
log); 3 m2_std_gate PASS, m3_gate PASS (`blocked29_gates.log`); 4 msframe B FASTER, x1.155 in all 5
pairs; 5 the reclaim is -1.58M on the binding, past the budget's high end (-1.4M); 6 size 27.35%, and
pinreport 20/20 pinned, 0 lost. The ESTIMATE was -1.0 .. -1.4M; measured -1.58M on gamespeed, -0.96M
on set v2 (-1.28M counting strafe's collision, which B0 leaves out). Attributed ops (profx phases,
the same ten games): collision 122,218 ops/frame -- one player try 50,818, of which the unchanged
seed walk is 31,838; 2.40 tries a frame.

## P1.3 persistent leaf lists (class S) -- declared 2026-09-27, before the build

**What**: in the game tier the per-leaf thing lists stop being rebuilt every frame. `sshead` and
`thnext` are baked to the spawn lists (exactly what `sim.bind_things` builds from the baked spawn
bindings: each leaf's runtime things, ascending), and the M1 reset stops restoring `sshead`,
`thss_rt` (the bindings) and `thpos_rt` (the positions) -- they persist, like the view and the
doors (`build.STANDALONE_PERSIST`). The per-frame `sim.bind_things` call goes; the hosted tiers keep
the wire protocol. The per-MOVE rebind lands as fj macros (`sim.leaf_link` / `sim.leaf_unlink`,
ascending insert and unlink, the mirror of `world.py`'s `_list_insert` / `_list_remove`), tested
standalone -- monsters are still inert, so nothing in the binary calls them until P3.

**Budget**: -0.44M ops/frame (`sim.bind_things`, MEASURED 438,808 on gamespeed, plan section 3),
plus the reset work the three persisted arrays stop costing (ESTIMATE ~0.1-0.17M, ~41-53 ops a
restored cell over ~2,400 nibble cells and 682 byte cells).

**Kill criteria** (any one -> the binary does not ship):
1. Host: the baked lists differ from a Python mirror of `bind_things` on the spawn bindings, or the
   emitted declarations do not spell them (with a mutated-list control).
2. fj: `sim.leaf_link` / `sim.leaf_unlink` disagree with the model on a scripted sequence run in ONE
   image (head, middle, tail, empty, only element), or a mutated macro is not caught.
3. `m2_std_gate` or `m3_gate` not byte-exact.
4. `msframe.py --against shipped`: B SLOWER. NOT SEPARATED ships only as "foundation for P3".
5. The reclaim: gamespeed binding down by less than 0.35M ops/frame (the budget / 1.25) ->
   redesign before shipping.
6. Size over 35% of 2^27; `pinreport.py`: a hot word of the heat list not pinned; the build refusing
   a persisted name (every one must be in the restore set).

**Row** (2026-09-27, `build/doom_e1m1_blocked30.fjm`, sha256 `0dd3806016af68cd`; logs in
`docs/ship-evidence/blocked30_*`):

| measure | shipped (P1.2, blocked29) | P1.3 (blocked30) | delta |
|---|---|---|---|
| gamespeed binding (ops/frame) | 14,780,831 | 14,318,431 | -462,400 (-3.1%) |
| combat set v2 binding (b0_scenarios) | 15,485,242 | 15,041,859 | -443,383 (-2.9%) |
| ... with strafe's collision (proxy) | 15,519,673 | 15,077,276 | -442,397 (-2.9%) |
| `sim.bind_things` ops/frame (profx, gamespeed's ten games) | 401,796 | 0 | -401,796 |
| M1 reset ops/frame (the same) | 226,935 | 94,229 | -132,706 |
| render walk ops/frame (the same) | 11,714,758 | 11,783,074 | +68,316 (placement) |
| ms/frame (msframe, one quiet run) | 64.2 | 62.8 | NOT SEPARATED (faster in all 5 pairs, median x1.021 < 3%) |
| fj ops/s | 235.8 M | 233.8 M | -0.8% |
| size (% of 2^27) | 27.35% | 26.98% | -497,816 words |
| hot words pinned (pinreport) | 20/20 | 20/20 (4 re-keyed by their heat key; 19 bases moved) | 0 lost |

**Verdict against the kill criteria:** 1 `tests/host/test_leaf_lists.py` passes with its controls
(`p13_r1_pass.log`); 2 `tests/fj/test_leaf_lists_fj.py` passes -- the relink agrees with world.py's
lists after every op of 8 moves, and both mutated macros are caught (the same log); 3 m2_std_gate
PASS, m3_gate PASS (`blocked30_gates.log`), and B0 on set v2 is state- and pixel-exact on every
frame of all 11 runs; 4 msframe NOT SEPARATED -- faster in all 5 pairs, but the median x1.021 is
under the 3% rule -- so it ships under the ship gate's own clause, "foundation for P3": the per-move
relink (`sim.leaf_link` / `sim.leaf_unlink`) is what P3's moving monsters call; 5 the reclaim is
-0.46M on the binding, past the 0.35M line and the -0.44M budget (-0.44M on set v2); 6 size 26.98%,
pinreport 20/20 and 0 lost, and the build accepts THING_PERSIST -- after 87c2c75: the first build
would have been refused after pass 1 (the reset asserted that the persisted byte array `sshead`
was still in the set it had just removed it from); the P1.5 pre-build review found it and that
build was stopped. Attributed (profx phases, the same ten games): bind_things 401,796 -> 0 and the
reset 226,935 -> 94,229, -534,502 gross; the render walk's +68,316 and collision's +2,818 are
placement -- the changed table counts re-rolled the blocking pass's pins -- not work.

## P1.4 the v2 sprite column (class S) -- declared 2026-09-27, before the build

**What**: `docs/gp-sprite-column.md` section 5, v2, in the shipped macros. A sprite fragment's
record shrinks from seven bytes to three -- `[slot][blk lo][blk hi]` -- and the per-THING constants
(the biased top row, the light row) are written once per accepted thing into `gpslot`; the emit
derives `y_base`, `sy1` and `sy2` from the slot and the block header where it uses them. The ditto
ladder compares (slot, block) -- four compares and four shadow saves where there were eight. Step
faces test their draw window before the shade lookup, the splices derive a region's list ids only
for a region they walk, and `emit_region`'s wall piece tests its window before its flag tests. The
runs take a fast path when the fragment is wholly on screen; v2's addressing reads inside a bank
block on a 3-nibble arm, places the block address by whole nibbles and does the fast path's row
math at two nibbles -- exact only if `sprbank` is 4096-bit aligned, which the build checks. The A+B
path (a second fragment behind the first) gets the same derive; the prototype did not cover it.

**Budget**: -1.0M ops/frame on combat set v2's binding. ESTIMATE: the census's "v2 cut" column
(`scratchpad/gp/census_out/s4v2/report_s4v2.txt` section 4, the v2 column's saving on the static
world's own sprite columns) applied to B0's eleven run averages gives 17,760,774 -> 16,756,812
(`gamespeed.binding_speed`); the prototype measured -39 .. -43% per sprite column end to end,
standalone (`docs/gp-sprite-column.md` 4.1). The emitted signature of `stream.emit_col_lines`
changes, and a heat key carries it (`...emit_col_lines(45)---rep0:w1rpat.walk(7)---ycur`), so the
rung profiles its first build and regenerates the heat list before the binary it ships.

**Kill criteria** (any one -> the binary does not ship):
1. The column check -- the prototype's harness pointed at the SHIPPED macros: a sprite column
   (slot A, and A+B) differs from the oracle's fragment over the plain column, or its mutated
   control (the record's bias off by one row) is not caught.
2. The build's `sprbank` alignment check missing, or not refusing a misaligned bank (its control).
3. `deg_gate` (4 viewpoints), `m2_std_gate` or `m3_gate` not byte-exact; `b0_scenarios` on set v2
   with `--pixel-every 1` not pixel-exact on every frame.
4. `msframe.py --against shipped`: B SLOWER. NOT SEPARATED ships only as "foundation for P3".
5. The reclaim: the v2 binding down by less than 0.8M ops/frame (the budget / 1.25) -> redesign
   before shipping.
6. Size over 35% of 2^27; `pinreport.py`: a hot word of the regenerated heat list not pinned;
   `gps_nslot` / `gps_cur_s` missing from a restore set (a stale `gps_cur_s` draws the last frame's
   top row and light with no crash); the emitter's slot-id bound (drawable things + runtime pools
   <= 255) not asserted.

**Row** (2026-09-27, `build/doom_e1m1_blocked31.fjm`, sha256 `773b840ca044e39b`; logs in
`docs/ship-evidence/blocked31_*`):

| measure | shipped (P1.3, blocked30) | P1.4 (blocked31) | delta |
|---|---|---|---|
| combat set v2 binding (b0_scenarios) | 15,041,859 | 14,441,924 | **-599,935 (-4.0%)** |
| ... with strafe's collision (proxy) | 15,077,276 | 14,476,599 | -600,677 (-4.0%) |
| gamespeed binding (ops/frame) | 14,318,431 | 13,974,938 | -343,493 (-2.4%) |
| the sprite record, `thing_leaf` + `thing_leaf_b` (profx, gamespeed's ten games) | 1,448,470 | 1,346,297 | -102,173 |
| the emission, `seg_pass2_leaf` (the same) | 3,628,248 | 3,540,932 | -87,316 |
| ms/frame (msframe, one quiet run) | 62.5 | 61.6 | NOT SEPARATED (pairs 1.016 0.992 1.019 0.990 1.020, median x1.016) |
| fj ops/s | 234.9 M | 234.2 M | -0.3% |
| size (% of 2^27) | 26.98% | 27.31% | +448,114 words (the slot table, the aligned bank, the code) |
| hot words pinned (pinreport) | 20/20 | 20/20 (4 re-keyed by heat key; the list's renames applied) | 0 lost |

**Verdict against the kill criteria:** 1 the column check (`scratchpad/gp/probes/sprite/ship_check.py`,
`docs/ship-evidence/p14_column_check.log`) -- the SHIPPED record, load and emit on every one of the
16 fight frames' 1,648 sprite columns, one fragment and two: 0 differ from the oracle; its four
mutants are caught (heavy:h57), M1 on all 16 frames too (3,190 of 3,296 columns); 2
`build.sprbank_misalignment` refuses an off-block bank and `tests/host/test_sprite_column.py` /
`tests/fj/test_narrow_reads_fj.py` show the pad is what aligns it (their controls: no pad, off a block,
reads wrong); 3 deg_gate PASS at four viewpoints (`p14_deg_gate.log`), m2_std_gate PASS, m3_gate PASS
(`blocked31_gates.log`), and B0 on set v2 state- and pixel-exact on every frame of all 11 runs; 4
msframe NOT SEPARATED (the pairs split in sign, median x1.016) -- it ships under the clause as a
foundation: P1.6's native-list bank draws through this column's (slot, block) fragment and its
derive, and so do P3's animated monsters; **5 FIRED: the reclaim is -0.60M on the v2 binding, under
the 0.8M line** (the budget -1.0M came from the phase-0 prototype's -39 .. -43% per sprite column,
standalone; in the renderer the record fell 102,173 and the emission 87,316 ops a frame on gamespeed's
games). **The owner's decision, 2026-09-27: "Ship it, follow up later"** -- P1.4 ships at -0.60M, and a
follow-up after phase 1 looks for the missing ~0.4M; 6 size 27.31%, pinreport 20/20 and 0 lost (after
b019db9 -- 10d7b48 before the rebase, tag `evidence/p1.4-rebuild`: it reads the hot words through the
renames the heat list carries), `gps_nslot` / `gps_cur_s`
in both restore sets (`p14_rekey.log`, test_restore_set_shipped 18 passed), and
`wall_renderer.check_slot_ids` asserts the slot-id bound.

## P1.5 the skill filter and the skill menu (class F) -- declared 2026-09-27, before the build

**What**: `docs/gp-skill-menu.md`. The thing universe becomes DOOM's single-player one
(`things.single_player`, shared by the renderer's `drawable_things` and the model's `World`): the 26
multiplayer-only things leave the image, which holds the union of the three skills (225 things, 53
monsters). Presence per skill is `things.skill_absent`, asked by both mirrors: the leaf lists are
baked per skill and `thvis` per skill; the boot state is hard's level start. NEW GAME opens a skill
screen (easy / medium / hard, `w`/`s`, `enter`, `esc`), and choosing a skill runs that skill's
restart block -- every cell the program persists today back to its level-start value -- and enters
the world.

**Budget**: -0.3M ops/frame on combat set v2's binding (handoff section 10; ESTIMATE, plan section 7's
R4: at hard, 7 zombiemen and 26 multiplayer-only things no longer drawn).

**Kill criteria** (any one -> the binary does not ship; class F, decision D8):
1. Host: `single_player` / `skill_absent` disagree with `World(skill)`'s level start (`mon_active`,
   `pickup_taken`) for any skill, or their mutated control is not caught; the emitter lets a baked
   thing without a `thvis` flag vary by skill.
2. fj: after each skill's restart block the persisted cells (view, doors, lists, bindings,
   positions, `thvis`) differ from that skill's level start; or a restart does not reset (walk, open
   a door, choose a skill: the view and the door must be back) -- with a mutated block caught.
3. `m3_gate` (menu frames, the skill screen, NEW GAME at each skill) or `m2_std_gate` not byte- and
   state-exact; `b0_scenarios` on set v2 with `--pixel-every 1` not pixel-exact on every frame.
4. CAP-22: the v2 binding over 22M, or size over 35% of 2^27; msframe over ~90 ms/frame without an
   explanation (the class-F tripwire). msframe's time is recorded as the price.
5. The reclaim: the v2 binding not DOWN (the filter removes drawn things; ESTIMATE -0.3M) ->
   redesign before shipping.
6. `pinreport.py`: a hot word not pinned; a new persisted cell (`menu_scr`, `menu_sel`) missing from
   the persist set (the build refusing it).

**Row** (2026-09-28, `build/doom_e1m1_blocked32.fjm`, sha256 `89c3cf6348258eeb`; logs in
`docs/ship-evidence/blocked32_*`):

| measure | shipped (P1.4, blocked31) | P1.5 (blocked32) | delta |
|---|---|---|---|
| combat set v2 binding (b0_scenarios, the boot skill hard) | 14,441,924 | 14,022,076 | **-419,848 (-2.9%)** |
| ... with strafe's collision (proxy) | 14,476,599 | 14,055,673 | -420,926 (-2.9%) |
| gamespeed binding (ops/frame) | 13,974,938 | 13,560,716 | -414,222 (-3.0%) |
| the sprite record, `thing_leaf` + `thing_leaf_b` (profx, gamespeed's ten games) | 1,346,297 | 1,215,762 | -130,535 |
| the emission, `seg_pass2_leaf` (the same) | 3,540,932 | 3,517,481 | -23,451 |
| ms/frame (msframe, one run, A = blocked31) | 62.2 | 60.4 | NOT SEPARATED (pairs 1.000 1.018 1.049 1.012 1.034, median x1.018) |
| fj ops/s | 232.1 M | 233.5 M | +0.6% |
| size (% of 2^27) | 27.31% | 27.13% | -246,914 words |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**Verdict against the kill criteria (class F):**
1 host: tests/host at 7cdfb97 1248 passed (single_player / skill_absent held to World(skill), their
controls, the emitter's flagless-baked-thing clause);
2 fj: the restart tests (NEW GAME rewrites the persisted cells to each skill's level start, a
mutated block caught) and m2_std_gate's control 6 (walk, open a door, NEW GAME: the view and the
door are back; --selftest-restart and --selftest-restart-doors rejected);
3 m3_gate PASS (32 frames byte- and state-exact: the skill screen, NEW GAME at easy, medium and hard;
--selftest-skill rejected at frame 20, --selftest at frame 0, --selftest-state at frame 20),
m2_std_gate PASS (366 frames byte- and state-exact), b0 on set v2 with --pixel-every 1: state and
pixels 100/100 on all 11 runs;
4 CAP-22: the v2 binding 14.02M <= 22M, size 27.13% <= 35%, msframe 60.4 ms/frame (the ~90 ms
tripwire far off) -- the price, recorded;
5 the reclaim: -0.42M on the v2 binding (the estimate was -0.3M);
6 pinreport 20/20, 0 lost; menu_scr / menu_sel persisted (the build did not refuse).

## P1.6 the native-list sprite bank (class F) -- declared 2026-09-27, before the build

**What**: `docs/gp-sprite-bank.md`. Each patch column is stored once per tier (HD / MID / LD) as a
NATIVE run list, rows normalized to 0..255 of its own height (`doomfj.spritebank`), and drawn at the
thing's height bucket through `rowmap`, a D4 dispatch (`rowmap[b][n] = ceil(n * hb / 255)`) -- two
lookups a fragment, one a run; the record adds `u` to the tier's region instead of multiplying, and
takes a column iff its bucket is at least the list's `min_b` (the shared rule). The bank also holds
every frame and rotation of E1M1's monsters, barrels, fireballs, puffs and blood (306 views, 237
lumps; MEASURED, `docs/ship-evidence/p16_size.log`), which nothing draws before P3.

**Budget**: size MEASURED (`scratchpad/gp/probes/bank/size.py --base 18ef625` at 0da63c9,
`docs/ship-evidence/p16_size.log`): the bank **-224,768 words** (16,284 blocks against the
per-bucket bank's 18,040; 2,084,352 against 2,309,120 words, both for the 27 kinds a single-player
game draws) while holding the animation, and the new rowmap table **+98,308 words** (plus 0..16,382
words of its own `pad 8192` where the build lands it) -- together **-126,460 words** (-0.094% of
2^27). (First declared as -793,856, then -695,548 with the rowmap: both measured against P1.5 before
its drawable-kinds fix, whose five never-drawn kinds made up most of it.)
Ops ESTIMATE +0.05 .. +0.15M on combat set v2's binding (the rowmap lookups against the record's
saved multiply). The frozen set: a v3 (below).

**Kill criteria** (any one -> the binary does not ship; class F, decision D8):
1. Host: `doomfj.spritebank`'s rules (identity scale draws `sprite_strip`'s column; the rowmap is
   ceil(n*hb/255); `min_b` is the shared rule; a drawn strip is never empty), or the emitted bank not
   `spritebank`'s lists for every kind, tier and animation view -- each with its mutated control caught.
2. fj: the SHIPPED `stream.frag_derive` / `frag_runs` not drawing `strip_at`'s rows (the fast path
   and both clips), or a walker that skips the rowmap not caught (`tests/fj/test_sprite_bank_fj.py`).
3. `m3_gate`, `m2_std_gate` not byte- and state-exact against the new oracle; `b0_scenarios` with
   `--pixel-every 1` not pixel-exact; `deg_gate` not byte-exact at its four viewpoints.
4. CAP-22: the v2 binding over 22M, or size over 35% of 2^27; msframe over ~90 ms/frame without an
   explanation (the class-F tripwire). msframe's time is recorded as the price.
5. The frozen set: MEASURED, the census's drawn population (F4) moves on 5 of 11 runs under this
   oracle (`docs/ship-evidence/p16_census_f4.log`) -> a v3 of combat set planned on the frozen keys,
   its B0 re-measured, frozen by the OWNER (`docs/handoff-gameplay.md` section 1) -- P1.6 does not
   ship on v2.
6. `pinreport.py`: a hot word not pinned (the heat list re-keyed, `heat_blocked27_p16`,
   `thing_record_body:25:24`); the restore sets not re-keyed to this rung's labels.

**Row** (2026-09-28, `build/doom_e1m1_blocked33.fjm`, sha256 `7be00f1e51c63678`; logs in
`docs/ship-evidence/blocked33_*` and `p16_*`):

| measure | shipped (P1.5, blocked32) | P1.6 (blocked33) | delta |
|---|---|---|---|
| combat set v2 binding (b0_scenarios) | 14,022,076 | 14,158,345 | +136,269 (+1.0%) |
| combat set **v3** binding (the owner's freeze, 2026-09-28) | -- | **14,158,345** | the new frozen set (B0 17,760,774) |
| ... with strafe's collision (proxy) | 14,055,673 | 14,192,344 | +136,671 |
| gamespeed binding (ops/frame) | 13,560,716 | 13,665,215 | +104,499 |
| the sprite record, `thing_leaf` + `thing_leaf_b` (profx, gamespeed's ten games) | 1,215,762 | 1,269,551 | +53,789 |
| the emission, `seg_pass2_leaf` (the same) | 3,517,481 | 3,542,563 | +25,082 |
| ms/frame (msframe, one run, A = blocked32) | 70.1 | 69.5 | NOT SEPARATED (pairs 1.014 0.999 1.009 1.013 1.004, median x1.009) |
| size (% of 2^27) | 27.13% | 26.96% | -230,976 words |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**Verdict against the kill criteria (class F):**
1 host: tests/host at the rebased head 1286 passed with tests/fj/test_sprite_bank_fj.py
(`p16_final_tests.log`) -- spritebank's rules and the emitted bank against its lists, each with its
control;
2 fj: test_sprite_bank_fj.py (the shipped derive / runs drawing `strip_at`'s rows, a walker that skips
the rowmap caught) in the same run; P1.4's layout harness adapted to the bank -- 81 passed, the
bucket byte, the region add and the min_b test each with their mutants;
3 m3_gate PASS (32 frames), m2_std_gate PASS (366 frames), byte- and state-exact, all six selftests
rejected where they must (`blocked33_gates.log`, `blocked33_gate_selftests.log`); b0 with
--pixel-every 1 pixel- and state-exact on every frame, v2 and v3; deg_gate BYTE-EXACT at its four
viewpoints (`p16_deg_gate.log`);
4 CAP-22: the v3 binding 14.16M <= 22M, size 26.96% <= 35%, msframe 69.5 ms/frame on the afternoon's
slow box (61.8 on the quiet re-freeze) -- the ~90 ms tripwire far off; the price recorded;
5 the frozen set: v3 FROZEN by the owner ("I approve v3", 2026-09-27) -- `scenarios_v2.py --freeze`
FREEZE PASS, F1-F5 (`p16_v3_freeze.log`); P1.6 is measured on v3 (`blocked33_b0_v3.log`);
6 pinreport 20 of 20, lost 0, unresolved 0 (`blocked33_pinreport.log`) -- the p14 heat list still
matches every hot group; the restore sets re-keyed (`p16_rekey.log`).
The budget (ESTIMATE +0.05 .. +0.15M on v2) held: +0.14M. Emission-neutral across the rebase
(`p16_emit_neutral.log`: e972725 vs the head, PASS, both controls caught).

## P2a.1 doors and keys (class F) -- declared 2026-09-28, before the build

**What**: `docs/gp-doors-keys.md`. The blue-card check on doors 51 and 71 (special 26); the blue
card drawn (BKEY, frame A) and taken by the model's own touch-and-reach rule; the blazing door 84
(special 117) at 4 stops a frame; the two walk-over doors 77 and 145 (special 2, tags 5 and 6) as
runtime doors that open when their line is crossed, once, and stay open. The model, every gate
oracle and the fj side take each rule from ONE place (`doomfj.doors`).

**Budget**: ops ESTIMATE +0.02 .. +0.05M on combat set v3's binding (the handoff: +0.05M for all of
P2a); size ESTIMATE +~0.1M words; plane ids MEASURED 233 (222 + 11; with P2b's lifts 254 of 255 --
`scratchpad/gp/p2a/walkover_pids.py`).

**Kill criteria** (any one -> the binary does not ship; class F, decision D8):
1. Host: the rules in `doomfj.doors` (the stride, the stay, the crossing test on both sides of each
   axis and at the extent's ends, W1 once), the card check, and the pickup's box and reach -- each
   held to the model with a mutated control caught; the emitted door machine and triggers
   (`doorcode`) match them per door.
2. fj: the SHIPPED door machine with the stride and the stay, the card check, the pickup and the
   crossing triggers, run in a tests/fj harness against `doomfj.doors` (run fj, don't model it),
   each with mutants.
3. `m3_gate`, `m2_std_gate` byte- and state-exact; the new `p2a_gate.py` runs (section 4 of the
   design) byte- and state-exact, each with its control rejected at the stated frame; B0 on v3
   with `--pixel-every 1` pixel-exact.
4. CAP-22: the v3 binding over 22M, or size over 35% of 2^27; msframe over ~90 ms/frame without an
   explanation. Ops attributed to the rung's code over 1.25x the budget (0.0625M) -> redesign.
5. Plane ids over 233 after the build (the walk-over doors' fallback is quant 24).
6. The frozen set: the card drawn in any v3 run's view, or a v3 run crossing a walk-over line,
   taking the card or pressing a blue door -> F4 or F3 moves, and the set needs the OWNER's
   re-freeze before this rung ships (MEASURED before the build).
7. `pinreport.py`: a hot word not pinned; the restore sets not re-keyed to this rung's labels.

**Row** (blocked34, sha256 `956a29893e7617a7`, built at e4270dc; `docs/ship-evidence/blocked34_*`):

| measure | blocked33 (P1.6) | blocked34 (P2a.1) | delta |
|---|---|---|---|
| combat set v3 binding | 14,158,345 | 14,158,771 | +426 |
| ... with strafe's collision (proxy) | 14,192,344 | 14,193,201 | +857 |
| gamespeed binding | 13,665,215 | 13,667,149 | +1,934 |
| size (% of 2^27) | 26.96% | 27.17% | +293,940 words |
| plane ids | 222 | 233 | +11 |
| ms/frame (msframe, one run, A = blocked33) | 66.1 | 67.8 | NOT SEPARATED (pairs 0.954 0.975 0.983 1.193 0.996) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**Verdict: every kill criterion met -- criterion 6 by the owner's decision.**
1. Host: 1,360 passed; the rules and their mutants (`test_doors_p2a.py`, `test_doorcode_more.py`).
2. fj: `tests/fj/test_doors_p2a_fj.py` 13 passed, its mutants caught.
3. m3_gate, m2_std_gate byte- and state-exact, six selftests; p2a_gate S1-S7 on the binary, every
   control parting; B0 v3 pixel-exact on every frame.
4. CAP-22: v3 14.16M <= 22M, size 27.17% <= 35%, msframe far under 90 ms. The ops held the budget
   (+426 against +0.02 .. +0.05M); the size did not hold its ESTIMATE (+0.29M words against ~+0.1M,
   no kill criterion).
5. Plane ids 233.
6. The frozen set: no v3 run takes the card or crosses a trigger (`p2a1_v3_reach.log`), and the
   model's growth (w_fired) re-froze v3 under the owner's schema-growth rule
   (`p2a1_v3_growth_freeze.log`) -- every pose and drawn population reproduced. BUT the card IS
   DRAWN: on 18 frames of R2-east-yard (51-68, 42-195 px each; `p2a1_v3_card_view.log`, the PR #99
   review's probe). The first check looked only at taking and triggers, and F4's census counts no
   items, so it could not see it. As declared, that needed the OWNER's decision: "I approve as is"
   (the owner, 2026-09-29, in the Claude Code session) -- keys, poses, digests and census unchanged,
   the 18 pictures gain the card, B0 measured with it. The owner added: re-freezes of v3 need no
   owner approval any more, only proof that nothing got worse.
7. pinreport 20 of 20; the restore sets re-keyed (`p2a1_rekey.log`).

## P2a.2 the exit switch and LEVEL COMPLETE (class F) -- declared 2026-09-28, before the build

**What**: `docs/gp-exit.md`. The exit switch (linedef 407, special 11) in the binary: a use PRESS
(the model's usedown edge, `pusedn`) inside its box (`doomfj.doors.exit_boxes`, now the model's own)
ends the level -- `lvdone`, the world frozen as the model's frozen tic -- and opens the LEVEL
COMPLETE screen (`menu_scr` 2); esc or enter lead to the main menu; NEW GAME resets both cells.

**Budget**: ops ESTIMATE ~+0 on v3 (a nibble test, the use edge; the box test only on a press);
size ESTIMATE +~1.3K words (one baked screen). No plane ids.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host: the exit box is linedef 407's inflated extent and the model's; the model exits exactly on
   a press inside it (edge probes on both axes, held use never); menu_step's LEVEL COMPLETE
   transitions; NEW GAME's reset of `lvdone`/`pusedn`; both persisted.
2. fj: `exit_lines` run on E1M1's box against the rule, five mutants caught
   (`tests/fj/test_exit_fj.py`); the menu state machine's LEVEL COMPLETE screen and the restart's
   new writes run in `tests/fj/test_skill_menu.py`, each with a control.
3. `m3_gate`, `m2_std_gate` byte- and state-exact with `lvdone`/`pusedn` read; `p2a_gate.py` S1-S8
   byte- and state-exact, every control parting (S8: edge, frozen, restart); B0 on v3 pixel-exact.
4. CAP-22 as P2a.1's; msframe B SLOWER against P2a.1's binary without an explanation.
5. `pinreport.py`: a hot word not pinned; the restore sets not re-keyed to this rung's labels.

**Row** (blocked35, sha256 `45674256d3f168e6`, built at a3504af; `docs/ship-evidence/blocked35_*`):

| measure | blocked34 (P2a.1) | blocked35 (P2a.2) | delta |
|---|---|---|---|
| combat set v3 binding | 14,158,771 | 14,218,744 | +59,973 |
| ... with strafe's collision (proxy) | 14,193,201 | 14,253,712 | +60,511 |
| gamespeed binding | 13,667,149 | 13,745,300 | +78,151 |
| size (% of 2^27) | 27.17% | 27.21% | +51,228 words |
| plane ids | 233 | 233 | 0 |
| ms/frame (msframe, one run, A = blocked34) | 61.4 | 61.6 | NOT SEPARATED (pairs 0.993 0.998 0.993 0.998 0.987) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**Where the ops went** (`profx/phases.py`, gamespeed's ten games, blocked34 -> blocked35): input
+16, doors -123, move +313, collision +1,197 -- the rung's own code is flat -- while the render walk,
which P2a.2 did not touch, moved +62,086 (seg_pass1/pass2, the BSP walk, things). That is
placement: the blocking pass re-rolls its pins on any change to the table counts. msframe, the
arbiter, does not separate the two binaries.

**Verdict: every kill criterion met.**
1. Host: 1,367 passed (`blocked35_host_suite.log`); the exit rule, the press edge, LEVEL COMPLETE's
   transitions and NEW GAME's reset (`tests/host/test_exit_p2a2.py`).
2. fj: `tests/fj/test_exit_fj.py` and `tests/fj/test_skill_menu.py` pass, their mutants and controls
   caught (`p2a2_fj_tests.log`).
3. m3_gate, m2_std_gate byte- and state-exact with `lvdone`/`pusedn` read, six selftests; p2a_gate
   S1-S8 on the binary, every control parting; B0 v3 pixel-exact on every frame.
4. CAP-22: v3 14.22M <= 22M, size 27.21% <= 35%; msframe NOT SEPARATED. The ops did NOT hold the
   ~+0 estimate (+59,973), explained above as placement -- by elimination: the rung's phases are
   flat, and nothing isolates the re-roll from the program's own growth ahead of the render walk
   (+43,772 words below the pool, which shifts its addresses). The size did not hold its +~1.3K
   estimate, and that is the rung's OWN code, not a re-roll (the size counts payload words, which a
   re-roll does not move; `blocked34_poolmap.log` -> `blocked35_poolmap.log`): the program below the
   pool +43,772 words, the pool's payload +7,456 (+233 tables, +66 groups) = +51,228. The LEVEL
   COMPLETE screen alone is 1,379 `stl.output_char` x 8 ops x 2 words = 22,064 words; the estimate
   counted the screen's bytes as words. No kill criterion.
5. pinreport 20 of 20; the restore sets re-keyed (`p2a2_rekey.log`).

## P2b lifts, the floor switch, door reversal (class F) -- L0 declared 2026-09-28, before any build

**What**: `docs/gp-lifts.md` (the spike, `docs/gp-lift-spike.md`, with its defaults). L0 (host):
`doomfj.movers` -- lifts 98/103 as the door machine on the floor, the instant floor switch, the
WR/SR/S1 triggers -- and door reversal in `doors.door_tic`; the model runs them. L1-L3: the fj side.

**Budget** (the spike's, kill at 1.25x attributed): ops <= +0.1M on the binding metric; size <=
+0.35M words; plane ids: 233 after P2a.1 + the spike's +21 = 254 of 255 (fallback: quant 24).

**Kill criteria**:
1. Host: the movers' geometry, the lift cycle in frames, a trigger ignored while active, the
   triggers, the height override; the model's rides, SR press, switch, monster WR, monster floors,
   restart, sight/sound nodes; door reversal at the pass step (both halves of the contact rule) --
   each with a mutation caught.
2. The frozen set: the model moves v3 (R2-spectre-corridor rides lift 103) -> v4 needs THE OWNER's
   approval before any P2b binary is measured against the cap.
3. L1-L3: byte- and state-exact gates with the movers in every oracle; plane ids <= 255.

**Row** (blocked37, sha256 `770209700dfbac8c`, built at 7041353, the PR #103 review's fix -- the movers'
two-sided neighbours, pillar 129 to 136; `docs/ship-evidence/blocked37_*`. blocked36, the pre-review build at
4118d8d, measured within a few thousand ops of it: `blocked36_*`):

| measure | blocked35 (P2a.2) | blocked37 (P2b) | delta |
|---|---|---|---|
| combat set binding | v3 14,218,744 | v4 **14,223,921** | the sets differ in one run; the 10 shared runs: mean -19,765 |
| ... R2-spectre-corridor (v3 walks, v4 rides lift 103) | 11,066,540 | 11,398,567 | +332,027 (a different route) |
| ... with strafe's collision (proxy) | v3 14,253,712 | v4 14,256,695 | |
| gamespeed binding | 13,745,300 | 13,642,413 | **-102,887** |
| size (% of 2^27) | 27.21% | 28.24% | **+1,373,516 words** (budget +0.35M) |
| plane ids | 233 | 254 | +21 (the spike's count, exact) |
| ms/frame (msframe, one run, A = blocked35, a quiet box) | 61.5 | 61.6 | NOT SEPARATED (the arms part at frame 33: lift 98) |
| ... pixel-identical, first 30 frames, 9 reps | 90.9 | 92.9 | NOT SEPARATED (pairs 0.965 .. 1.063, median x0.981; 8 of 9 below 1) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**The size, attributed** (`blocked35_poolmap.log` -> `blocked36_poolmap.log`, label families): the
pool's payload +413,822 words (+12,931 tables); below the pool +960,448 -- +273K in labelled code
(plane-band thunks `vpb_t`, the per-state seg consts `seg*_*_consts_st*`, the mover dispatch
`dr*_ct_*`, the dual-end seg code) and +687K in the program's UNLABELLED tail after `m1_reset` (code:
ops that fall through, 5.67M -> 6.01M ops -- read as the assembler's out-of-line flip sequences for
the new code, NOT confirmed). The spike's 241K counted band ids, band bodies, pair blocks and state
blocks only. All of it is the rung's own code. **Kill criterion (size, 1.25x) BREACHED -- the owner,
2026-09-29: ship blocked36** (blocked37 carries the review's fix, the same size to -754 words); the end-of-game size projection moves from ~32.6-33.3% to ~33.7-34.4%.

**Verdict: every kill criterion met but the size budget, which the owner waived.**
1. Host: 1,400 passed on the re-keyed tree (`blocked37_host_suite.log`); the movers' geometry, the
   lift cycle, the triggers, the rides, door reversal, each with a mutation caught
   (`tests/host/test_movers_model.py` and the P2b host tests).
2. The frozen set: v4 FROZEN by the owner (`p2b_v4_freeze.log`) -- re-planned on the tree with PR
   #99's planner fix, R0-imp-court back to v3's exact keys, so v4 = v3 but R2-spectre-corridor; B0 on
   v4 exact on every frame of 11 runs; `--selftest` on v4 (`p2b_v4_selftest.log`).
3. m3_gate, m2_std_gate byte- and state-exact with the movers read; p2a_gate S1-S13, every control
   parting; B0 v4 pixel-exact (first run without the movers' heights parted exactly on the lift run:
   `blocked36_b0_v4_no_mover_heights.log`, the harness fixed); plane ids 254 <= 255.
4. CAP-22: v4 14.22M <= 22M, size 28.24% <= 35%; msframe NOT SEPARATED. Ops: -102,887 on the
   binding metric (budget +0.1M).



## P3.0 the monster tables, uncalled (class S) -- declared 2026-09-29, before the build

**What**: `docs/gp-monsters.md` section 6. `doomfj.monstercode` emits four D4 tables in the game tier, called by
nothing: `mstate` (the monster state table: next, tics, action, view group, over `gamedata.STATE_INDEX`), `mturn`
(A_Chase's turn), `mopp` (P_NewChaseDir's opposite), `mrnd` (the monster stream's P3 call sites folded into one
outcome table, D10). The monster collision cells are NOT in P3.0 -- their shape is P3.2's (the drop-off and
BLOCKMONSTERS rules decide the stubs), and pricing showed each radius class is a player-sized cell set (~52K fj
lines, ~226K labelled words before its tables and tail).

**Budget**: size <= +0.1M words (four small tables); ops: the placement tax only (nothing is called).

**Kill criteria** (class S: no pixel moves):
1. Host: each table equals its Python source -- gamedata's states (127 monster states, 77 view groups),
   `world.turn_toward`, `gamedata.OPPOSITE`, `rng.outcome_table` -- with a packing mutation caught
   (`tests/host/test_monstercode.py`).
2. fj: every entry of every table looked up twice on the engine against its source, a mutated entry caught
   (`tests/fj/test_monster_tables_fj.py`).
3. Every gate byte- and state-exact; deg_gate byte-exact with the SAME picture; B0 v4 exact.
4. msframe against P2b's binary: B SLOWER does not ship (class S) unless explained as placement and accepted as
   P3's entry price by the owner.
5. pinreport: no hot word lost.

**Row** (blocked38, sha256 `457e175106f10776`, built at 8cb0865; `docs/ship-evidence/blocked38_*`):

| measure | blocked37 (P2b) | blocked38 (P3.0) | delta |
|---|---|---|---|
| combat set v4 binding | 14,223,921 | 14,250,398 | +26,477 |
| gamespeed binding | 13,642,413 | 13,696,511 | +54,098 |
| profx mean frame (gamespeed's games) | 11,600,461 | 11,650,201 | +49,740 (the render walk +48,435) |
| size (% of 2^27) | 28.24% | 28.24% | +10,936 words (budget 0.1M) |
| ms/frame (msframe, one run, A = blocked37, pixels identical) | 61.3 | 61.7 | NOT SEPARATED (x0.995) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**The placement tax**: nothing calls the four tables. Outside the render walk the phases moved by at most +1,249
(collision 123,868 -> 125,117, its seed walks +701; eye point +302; move/turn -202; the rest within +/- 70); the
render walk moved +48,435 -- the blocking pass re-rolling its pins on a changed table count. That is P3's entry
price, and it is small against the budget (+0.3M for all of P3).

**Verdict: every kill criterion met.**
1. Host: `tests/host/test_monstercode.py` (each table against its source, a packing mutation caught).
2. fj: `tests/fj/test_monster_tables_fj.py` -- every entry twice on the engine, a mutated entry caught.
3. m2_std_gate, m3_gate byte- and state-exact with their selftests; p2a_gate S1-S13; deg_gate BYTE-EXACT with
   EVERY op count equal to blocked37's; B0 v4 exact on every frame.
4. msframe NOT SEPARATED with the pictures identical: not B SLOWER, class S ships.
5. pinreport 20 of 20; the restore sets re-keyed (`p30_rekey.log`).


## P3.1 idle life (class F) -- declared 2026-09-30, before blocked40's build

**What**: `docs/gp-monsters.md` section 7. The monsters run their state machine in the model's `idle` mode (nothing
wakes): per slot the tic and one `mstate` step; drawn at their state's frame and DOOM's rotation for the viewer
(`doomfj.monsters`), mirrored views included -- the renderer reads a runtime thing's row through a row select
(a static thing its own row, a monster its view's), the light class two bytes wide (`ltw`).

**Budget**: ops <= +0.15M on the binding metric (the tic ~53 slot tests, the row select and rotation per drawn
monster); size <= +0.4M words (the view rows, the light classes, the slot code).

**Kill criteria** (class F):
1. Host: the idle mode, the view rule and the oracle's views each with a control (`test_monsters_idle.py`).
2. fj: the tic, the rotation (with `mrot`), the row select (with `mview`) and P3.0's four tables on the engine
   against the model's rules, mutants caught (`test_monster_tic_fj.py`, `test_monster_rotation_fj.py`,
   `test_monster_rowselect_fj.py`, `test_monster_tables_fj.py`). The record's new parameters run in
   `test_sprite_bank_fj.py` at their OFF values only (`ltw=1`, `mir/mirf/miru=0`: the old ops); the mirrored column
   and the second light-class byte are proven only by the gates' pixels where their frames draw them (no harness
   runs them on -- a follow-up).
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact with every gate's oracle running `MonsterPhase` and
   drawing its views; their selftests reject where they must; B0 v4 exact (the idle monsters from the boot image).
4. CAP-22 on v4; size <= 35%; msframe recorded (the pictures differ from blocked38's -- monsters animate).
5. pinreport 20 of 20 with the re-keyed heat list (`heat_blocked27_p31`); the restore sets re-keyed.

**Row** (blocked40, sha256 `dc1e85e52f48a299`, built at 7608ef3; `docs/ship-evidence/blocked40_*`):

| measure | blocked38 (P3.0) | blocked40 (P3.1) | delta |
|---|---|---|---|
| combat set v4 binding | 14,250,398 | 14,447,782 | +197,384 |
| gamespeed binding | 13,696,511 | 13,940,191 | +243,680 |
| profx mean frame (gamespeed's games) | 11,650,201 | 11,845,713 | +195,512 (thing_pass_leaf +135,518, the tic +7,652) |
| size (% of 2^27) | 28.24% | 28.65% | +548,490 words |
| ms/frame (msframe, one run, A = blocked38) | 62.7 | 64.2 | NOT SEPARATED (x0.978) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost (after the heat list's renames were made to accumulate) |

**OVER BUDGET, both ways**: +0.24M on gamespeed and +0.20M on v4 against the +0.15M declared, and +0.55M words
against +0.4M. The ops are the row select and the rotation per DRAWN monster (`thing_pass_leaf` +135,518: every
monster in view pays `thsel_leaf`, the mstate lookup and `mon_rot_leaf`, where the estimate priced the tic alone);
the words are the view rows and two-byte light classes. Neither is a kill criterion, and the totals stay far
inside both owner targets (22M cap: 14.45M on v4; 35%: 28.65%). Recorded so P3.2's budget prices the per-drawn
cost that P3.1's did not.

**Found on the way**: `heat_rekey.py` overwrote its list's rename record instead of accumulating it, so a list
re-keyed from a re-keyed list (p31 <- p16 <- p14) lost P1.4's `stream.emit_col_lines 45 -> 38`, and pinreport left
a word the build HAD pinned UNRESOLVED (`blocked40_pinreport_r0_unresolved.log`). Fixed with an R9 control;
heat_blocked27_p31 regenerated, its groups identical (the pool reads only those).

**Verdict: every kill criterion met.**
1. Host: `test_monsters_idle.py` (the idle mode, the view rule, the oracle's views, each with a control).
2. fj: the tic, the rotation (`mrot`), the row select (`mview`) and the four P3.0 tables on the engine, mutants
   caught; the record's new parameters at their off values in `test_sprite_bank_fj.py` (mirroring and the 2-byte
   class on only through the gates' pixels -- the follow-up issue).
3. m2_std_gate, m3_gate byte- and state-exact with their selftests (restart-doors parts on the doors alone);
   p2a_gate S1-S13; B0 v4 exact on every frame; deg_gate BYTE-EXACT with every op count equal to blocked38's.
4. CAP-22 on v4 (14,447,782); size 28.65%; msframe recorded (NOT SEPARATED).
5. pinreport 20 of 20 with `heat_blocked27_p31`; the restore sets re-keyed (`p31_rekey.log`).

**Row**: (filled after the build)


## P3.2a wake (class F) -- declared 2026-09-30, before blocked41's build

**What**: `docs/gp-monsters.md` sections 8.2-8.3, rung P3.2a. The monsters run the model's `wake` mode under the
seen rule (combat set v5): the render marks each monster it SEES (some column open at the base monster size cull,
before the count budgets and the soft raise -- `seen_probe`), and the next frame's tic reads the flags. The tic walks
the slots from `sched_cursor`, at most K = 6 heavy slots a frame (the first deferred is the next cursor); A_Look
wakes on seen, or REJECT-visible within 128 and not behind; A_Chase in `wake` runs its counters and the turn
(`mturn`), and nothing moves yet (P3.2b).

**Budget**: ops <= +0.3M on the binding metric (the slot walk, one REJECT row read per near sleeper, the seen mark
per drawn monster and the probe per culled one); size <= +0.2M words (the REJECT rows of the monsters' sectors,
`lfsec`, the unrolled slots).

**Kill criteria** (class F):
1. Host: the seen rule, REJECT and the wake mode each with a control (`tests/host/test_sight.py`, added in review: REJECT bit for bit, the wake and attack sights,
   SeenHook, set_seen; the world's wake tests).
2. fj: the wake tic on the engine against the model's wake mode, a mutated REJECT row and a mutated turn table
   caught (`test_monster_wake_fj.py`); `seen = 0` leaves the transplanted record exact (`test_sprite_bank_fj.py`);
   the `seen = 1` mark and probe are proven where they run whole -- `thseen` state-exact in the gates below.
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact with every gate's oracle ticking `MonsterPhase` in `wake`
   and feeding it the seen set of the picture it drew; their selftests reject where they must; B0 v5 exact.
4. v5 frozen (the owner's approval stands if every criterion still passes on the measured B0); CAP-22 on v5;
   size <= 35%; msframe recorded (the pictures differ from blocked40's -- monsters wake and turn).
5. pinreport 20 of 20 with the re-keyed heat list (`frame.thing_record_body` 28 -> 32); the restore sets
   re-keyed (the wake cells and `thseen` persist).

**Row** (blocked43, sha256 `3c3a87d474d975e5`, built at df7c4b8; `docs/ship-evidence/blocked43_*`):

| measure | blocked40 (P3.1) | blocked43 (P3.2a) | delta |
|---|---|---|---|
| combat set binding | v4 14,447,782 | **v5** 14,400,185 | the set changed (v5, the seen rule) |
| gamespeed binding | 13,940,191 | 14,086,236 | +146,045 (budget 0.3M) |
| profx mean frame (gamespeed's games) | 11,845,713 | 11,948,995 | +103,282 |
| size (% of 2^27) | 28.65% | 29.64% | +1,330,204 words (budget 0.2M: OVER) |
| ms/frame (msframe, one run, A = blocked40; the pictures differ, so its pixel check reads NO) | 64.2 | 63.6 | NOT SEPARATED (x0.999) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**OVER the size budget**: +1.33M words against the +0.2M declared. The pool's preflight says where: +17,701 tables
(371,471 -> 389,172) in +848 groups, +1.21M words of pool demand -- every hex op of the new code carries its own
lookup table here, and the tic is 53 unrolled slots (and the seen probe sits in both record expansions). The ops are
inside the budget. Not a kill criterion; size stays far inside 35% (29.64%).

**Two dead builds, two pointer rules** (both now written down in `src/fj/frame_render.fj` and `selfreset.py`):
blocked41 died at its first world frame (NullIP): `rec_seen_mark`'s `hex.write_hex` armed the pointer library at
`thseen`, outside the hot-data 16^5 window, and the column loop's next `frame.read_byte5` (arm5 moves only five hexes)
jumped into code -- the mark now re-arms at the pointer its caller reads next. blocked42 then looped forever:
`--pin-state-cells` pre-arms every `hex.vec` cell at its reader table's base, a pointer write took that base for the
value and left a redirect bit flipped in `thseen[22]`, and the tic's next `hex.zero` cycled -- `thseen` joined the pin
veto. Neither is visible to an unpinned tests/fj harness; the record harness now runs the mark ON with the flags a
window away (control: no re-arm), and `test_monstercode` pins the veto. The chain now proves a binary presents frames
(`_smoke_frames.py`, under a timeout) before any gate runs.

**Verdict: every kill criterion met.**
1. Host: the seen rule, REJECT and the wake mode with their controls; the probe's wake group all-or-none.
2. fj: `test_monster_wake_fj.py` (the wake tic against the model, a mutated REJECT row and turn table caught);
   `test_sprite_bank_fj.py` runs the record with the mark ON (every thing marked, the layout exact; the mark without
   its re-arm caught); `test_slot_layouts_fj.py` binds the switch off.
3. m2_std_gate, m3_gate byte- and state-exact with their selftests; p2a_gate S1-S13 and S8 (the exit: no tic on the
   frame its press ends the level); B0 v5 exact on every frame; deg_gate BYTE-EXACT with every op count equal to
   blocked40's.
4. v5 FROZEN (F1-F5 PASS, `p32a_v5_freeze.log`); CAP-22 on v5 (14,400,185); size 29.64%; msframe recorded.
5. pinreport 20 of 20 with `heat_blocked27_p32a`; the restore sets re-keyed (`p32a_rekey.log`).


## P3.2b chase (class F) -- declared 2026-09-30, before its build

**What**: `docs/gp-monsters.md` section 8.4. The monsters run the model's `chase` mode: A_Chase MOVES -- movecount,
P_Move (the step, the other monsters' and the player's boxes, the static blockers and the lines in the monsters'
cells at radius 30 with ML_BLOCKMONSTERS and the drop-off, the seed through ptloc_walk), P_NewChaseDir with its cap
of 6, the relink of a changed leaf, the WR lifts a step crosses, a refused step in a monster door's box pressing it;
the REJECT row by the monster's sector at run time; a closing door reversing on a monster; P_ChangeSector on the
lifts. No attack is decided (P3.2c).

**Budget**: ops <= +0.4M on the binding metric (the model's 2.32 tries a frame at ~80K a try, ~0.19M mean,
`p32b_chase_census_v5.log`; the rest the per-slot copy in / out); size <= +2.5M words (the monster cells, a REJECT row
per sector, the unrolled thing test and the door contacts per monster).

**Kill criteria** (class F):
1. Host: the chase mode with its controls (`test_monsters_chase.py`: the wake mode does not move, the full mode
   decides); the probe's new cell group all-or-none.
2. fj: the monsters' cells, the seed and the static blockers against `World.try_move_lines` / `try_move_monster`
   with doors, lifts and the switch in random states (`test_monster_cells_fj.py`, three controls); the whole chase
   tic against the model's chase mode over 40 frames -- every slot's state, position, floor, leaf, movedir,
   movecount and P_Random state, the door presses, the lift triggers and the final leaf lists, with a lift
   crossing, a capped NewChaseDir and a door press in the script (`test_monster_chase_fj.py`, three controls: no
   cap, no thing test, no relink).
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact (thpos_rt / thss_rt read for every runtime thing) with the
   monsters stepped inside each gate's doors and lifts (`MonsterPhase.frame`); their selftests; B0 v5 exact (the
   mirror re-stepped with the monsters' presses and boxes).
4. CAP-22 on v5; size <= 35%; msframe recorded.
5. pinreport 20 of 20 (the heat list p32a: `sim.line_test`, re-signed here, is on no hot path); the restore sets
   re-keyed (the chase's cells, `bar_solid`, `mh_prev` persist).

**Row** (blocked44, sha256 `06e8912c4d4d3b96`, built at 2f76124; `docs/ship-evidence/blocked44_*`):

| measure | blocked43 (P3.2a) | blocked44 (P3.2b) | delta |
|---|---|---|---|
| combat set binding (v5) | 14,400,185 | 15,299,168 | +898,983 |
| ... with strafe's collision | 14,435,039 | 15,335,250 | +900,211 |
| v5 per-frame maximum (+/- 2^18) | 24,641,536 | 25,427,968 (R0-aftermath) | +786,432 |
| gamespeed binding | 14,086,236 | 14,452,893 | +366,657 (budget 0.4M: inside) |
| profx mean frame (gamespeed's games) | 11,948,995 | 12,334,235 | +385,240 |
| size (% of 2^27) | 29.64% | 33.38% | +5,017,552 words (budget 2.5M: OVER) |
| pool tables (build) | 389,172 in 25,184 groups | 466,633 in 33,572 groups | +77,461 tables |
| ms/frame (msframe, one run, A = blocked43; the pictures differ, so its pixel check reads NO) | 62.2 | 66.4 | B SLOWER (x0.934) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**msframe B SLOWER is the class-F price (D8), explained**: on msframe's forward walk blocked44 runs 14,944,344
ops/frame against 14,336,652 (+607,692, +4.2%: the awake monsters along the walk now MOVE every frame -- mm_chase /
mm_move / the thing test / the relinks -- where blocked43's only turned) and its rate fell 230.6 -> 225.2 M fj/s
(-2.3%: the new code and the 77,461 new pool tables re-roll the placement); together 62.2 -> 66.4 ms/frame (x0.934, all
five pairs one sign). Far under the ~90 ms tripwire; recorded, not a kill criterion for a class F rung.

The design's estimate was ~0.19M mean, 0.32M at p80 (`docs/gp-monsters.md` 8.4); gamespeed moved +366,657. Where profx
puts it (phases.py, ops/frame, blocked43 -> blocked44; lines that moved >= 10,000): render walk, all 11,651,545 ->
11,883,836; (glue between phases) 22,518 -> 167,927; seg_pass2_leaf 3,508,143 -> 3,665,644; seg_pass1_ts_leaf
2,452,237 -> 2,481,799; seg_pass1_leaf 2,366,520 -> 2,324,892; bspcode walk (nodes, pos_leaf, ss code) 885,891 ->
913,828; thing_leaf_b 718,112 -> 779,699; thing_leaf 722,700 -> 702,631; thing_pass_leaf 634,555 -> 650,839.

**OVER the size budget**: +5,017,552 words against the +2.5M declared -- +2,467,118 below the pool (the program,
25,576,624 -> 28,043,742) and +2,550,434 in it (14,210,886 -> 16,761,320 payload words; +77,461 tables). The size
audit (`scratchpad/plan/p32b/size_audit`) found the "12M unexplained" a layout mix-up -- the counting pass's
UNRELOCATED layout against the final one: the final program is 7.29M ops, and the counting layout's headroom 3.49M.
**Size is now 33.38% of 2^27 against the 35% target: 2,171,142 words (1.62 points) of room left -- less than this rung
alone added.** One more rung of this size crosses the target; raising it (the owner's 2026-09-25 note already says 35%
conflicts with even two levels) or buying words back is the owner's call.

**One dead build, one stopped chain.** r0 (at 5399be4, `blocked44_build_r0_overflow.log`) died in the COUNTING pass:
"the program reached 0x857cc840, which is inside the table pool based at 0x60000000" -- the counting assembly lays the
program out unrelocated, and the game tier's door tic had inlined the contact test of every door for each of the 53
monster slots: 8,056 signed constant compares (hex.set 8 + hex.scmp 8, 1,808 ops each), ~14.6M ops. ee6761c gives each
(door, radius) one contact leaf on `dc_x` / `dc_y` (a monster costs two moves, a call and a flag test), with
`tests/fj/test_door_reversal_fj.py` (a closing door reverses on a LIVE monster exactly as `door_tic`, 738 records, 528
reversals; a door ignores an inactive one; controls: the inactive flag read from another slot, one radius for all).
The r1 chain then stopped at its host suite (`blocked44_host_suite_r0_doorcensus.log`): `test_doorcode`'s write census
did not admit the contact leaves' own registers (`dc_x`, `dc_y`, `dc_hit`) -- 2f76124, a test fix; the build is at
that commit.

**Known divergence, carried to P3.2c:** P_ChangeSector runs outside the `lvdone` exit guard. Fixed on P3.2c's branch,
796cdcc.

**Verdict: every kill criterion met.**
1. Host: 1415 passed, 2 skipped, 1 deselected, 2 xfailed, 3 warnings (`blocked44_host_suite.log`),
   `test_monsters_chase.py` with its controls (the wake mode does not move, the full mode decides) among them; the
   probe's chase group all-or-none.
2. fj, on the engine against the model (the runs the commits record): `test_monster_cells_fj.py` (3 passed, f322b47:
   700 moves verdict- and floor-exact, ML_BLOCKMONSTERS and the drop-off each caught; the seed and the static
   blockers, 0843a6f); `test_monster_chase_fj.py` (the chase tic over 40 frames ALL EQUAL, 895de7f; the no-cap control
   was VACUOUS -- a monster boxed in on all 8 sides ends at NODIR either way -- so slot 3 now stands at CAP_SPOT and
   `test_the_cap_decides_something` requires the capless model to part); `test_door_reversal_fj.py` (ee6761c). The
   whole files re-run: 22 passed (`p32b_fj_harnesses.log`).
3. m2_std_gate (452 frames) and m3_gate (32 frames) byte- and state-exact, their 6 selftests PASS; p2a_gate 13
   scenarios state- and pixel-exact with the monsters stepped inside its doors and lifts; B0 v5 exact on every frame
   (11 runs, 1,100 frames: state and pixels); deg_gate BYTE-EXACT with every op count equal to blocked43's.
4. CAP-22 on v5: 15,299,168 (headroom 6,700,832; the per-frame maximum 25,427,968 in R0-aftermath is not the cap's
   measure); gamespeed 14,452,893 PASS; size 33.38% (<= 35%); msframe recorded (B SLOWER: median x0.934).
5. pinreport 20 of 20 with `heat_blocked27_p32a`; the restore sets re-keyed (`p32b_rekey.log` 20 passed in 0.28s;
   `p32b2_rekey.log` 20 passed in 0.31s).


## P3.2c decide (class F) -- written at ship, 2026-10-02: NO budget was declared before blocked45's build

**What**: `docs/gp-monsters.md` section 8.5. The monsters run the model's `decide` mode: A_Chase whole --
`justattacked` (per slot, persisted) clears and re-picks the direction; the melee decision (a melee state,
P_AproxDistance < MELEE_REACH 60, the attack sight); the missile decision (a missile state, movecount 0, the attack
sight, reaction 0, then `P_Random < min(dist - bias, 200)` refuses); the decided state entered with A_FaceTarget. The
attack states' actions face and DRAW as the full model's (`combat._attack_rolls`) and apply nothing: damage and the
fireball are P5, so the monster random stream is already the full model's. The attack sight is seen, or within NEAR
and `sl_los`, the exact 2D LOS of `World.los_points` on per-256-unit-cell candidate lists with 48-bit orientation
signs. It carries P3.2b's review fixes (796cdcc): P_ChangeSector inside the `lvdone` exit guard, B0's selftest frames,
the slot-order assert, the hardening.

**Budget**: none was declared in this file before the build -- a gap in the rung's process (every rung before it
declared one first); it is NOT back-filled here. What priced the work before the build is the census
(`p32c_decide_census_v5.log`, `scratchpad/gp/p32c_decide_census.py`) on v5's 1100 frames: per frame, mean 0.02
decisions, 0.01 attack actions, 0.20 attack-sight calls and 0.01 near LOS traces (6 traces in all) -- and the near LOS
was cut from 5.52M to 0.19M ops before the build (e24ab75).

**Kill criteria** (class F, as run):
1. Host: the decide mode in lockstep with the full model's monsters until the player dies, two runs (all seen; the
   player parked by an active monster), the no-draws control parting in both (`tests/host/test_monsters_decide.py`);
   the restore sets carry every persisted monster cell (`test_restore_set_shipped`'s monster-cells test and its
   control).
2. fj: the near LOS against `World.los_points` (`tests/fj/test_monster_sight_fj.py`: 900 traces, every door and lift
   state; controls: the dynamic segments always shut, strict crossings only, no margin, o4 without its o3 term,
   registers left uncleared); the decide tic against the model (`tests/fj/test_monster_decide_fj.py`: 120 frames;
   controls: no roll, no LOS, justattacked never read, no draws); P_ChangeSector against `World._door_phase_scene`
   (`tests/fj/test_change_sector_fj.py`; controls nomh, noswitch, noactive, nolvdone).
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact with the gates' oracles in `decide`; their selftests; B0 v5
   exact on every frame; deg_gate byte-exact.
4. CAP-22 on v5; size <= 35%; msframe recorded (D8).
5. pinreport 20 of 20 (heat list p32a); the restore sets re-keyed (`mon_justattacked` persists).

**Row** (blocked45, sha256 `25957324521286dd`, built at 197682c; `docs/ship-evidence/blocked45_*`):

| measure | blocked44 (P3.2b) | blocked45 (P3.2c) | delta |
|---|---|---|---|
| combat set binding (v5) | 15,299,168 | 15,087,224 | -211,944 |
| ... with strafe's collision | 15,335,250 | 15,122,674 | -212,576 |
| v5 per-frame maximum (+/- 2^18) | 25,427,968 | 25,690,112 (R0-aftermath) | +262,144 |
| gamespeed binding | 14,452,893 | 14,462,688 | +9,795 (no budget declared) |
| profx mean frame (gamespeed's games) | 12,334,235 | 12,321,663 | -12,572 |
| size (% of 2^27) | 33.38% | 33.92% | +726,572 words (no budget declared) |
| pool tables (build) | 466,633 in 33,572 groups | 471,582 in 33,949 groups | +4,949 tables |
| ms/frame (msframe, one run, A = blocked44; the pictures differ, so its pixel check reads NO) | 67.6 | 66.7 | NOT SEPARATED (x1.000) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

The census priced the decisions small (0.02 a frame on v5), and gamespeed moved +9,795, B0 v5 -211,944. Where profx
puts it (phases.py, ops/frame, blocked44 -> blocked45; lines that moved >= 10,000): seg_pass2_leaf 3,665,644 ->
3,623,277; seg_pass1_leaf 2,324,892 -> 2,366,784; bspcode walk (nodes, pos_leaf, ss code) 913,828 -> 896,926;
thing_pass_leaf 650,839 -> 669,426. Why v5 fell by 211,944 is not attributed: phases.py has no monster-tic phase
(#113), and no run here measured the tic alone.

**Size**: +726,572 words -- +555,196 below the pool (the program, 28,043,742 -> 28,598,938) and +171,376 in it
(16,761,320 -> 16,932,696 payload words; +4,949 tables). **Size is now 33.92% of 2^27 against the 35% target:
1,444,570 words (1.08 points) of room left.** The target's raise is still the owner's call (#113).

**msframe NOT SEPARATED is the class-F record (D8)**: 67.6 -> 66.7 ms/frame (pairs 0.996 0.983 1.010 1.000 1.016),
14,944,344 -> 14,828,598 ops/frame on msframe's walk, 221.0 -> 222.2 M fj/s. The re-freeze of the `shipped` baseline
on blocked45 waits for a quiet window.

**Verdict: every kill criterion met -- criterion 2's P_ChangeSector run on its commit's record (see there).**
1. Host: 1427 passed, 2 skipped, 1 deselected, 2 xfailed, 3 warnings (`blocked45_host_suite.log`, at the build's
   commit 197682c), `test_monsters_decide.py` and `test_restore_set_shipped.py` among them.
2. fj: `test_monster_sight_fj.py` 8 passed in 32.37s (`p32c_sight_fj.log`), `test_monster_decide_fj.py` 6 passed in
   2284.07s (`p32c_decide_fj.log`) -- both at e24ab75; 7d9d851 then moved NEAR / reach / K to one source each with the
   emitted text IDENTICAL (its message: the decide harness's parts sha256 472145c1...); `test_change_sector_fj.py` (6
   passed in 16.70s, as 796cdcc's message records -- no log of it is in ship-evidence).
3. m2_std_gate (452 frames) and m3_gate (32 frames) byte- and state-exact, their 6 selftests PASS; p2a_gate 13
   scenarios state- and pixel-exact; B0 v5 exact on every frame (11 runs, 1,100 frames: state and pixels); deg_gate
   BYTE-EXACT with every op count equal to blocked44's.
4. CAP-22 on v5: 15,087,224 (headroom 6,912,776; the per-frame maximum 25,690,112 in R0-aftermath is not the cap's
   measure); gamespeed 14,462,688 PASS; size 33.92% (<= 35%); msframe recorded (NOT SEPARATED: median x1.000).
5. pinreport 20 of 20 with `heat_blocked27_p32a`; the restore sets re-keyed (`p32c_rekey.log` 22 passed in 0.72s).


## P3.3 depth order inside a leaf (class F) -- written at ship, 2026-10-03: NO budget or kill criteria were declared in this file before blocked46's build

**What**: `docs/gp-monsters.md` section 8.6 (D3 d). The walk is front-to-back and a sprite pixel is written once, so
inside one leaf the NEAR thing must be drawn first; until P3.3 a leaf's runtime things were drawn in index order
(`sim.thing_pass`). Now `sim.thing_pass_depth` (the game tier) draws a longer list in rounds, each taking the least
(P_AproxDistance from the player's integer position, index) above the last drawn -- no per-thing storage, pointer
reads only; the oracle's `render_wall_frame(rt_depth_order="aprox")` through `GAME_RENDER_KW`; the hosted tiers keep
index order (`HOSTED_RENDER_KW`). D3 a (drops and effects before monsters) waits for P4/P5, which create them.

**Budget**: none was declared here before the build -- a gap in the rung's process, as at P3.2c; it is NOT
back-filled. The design was priced by the census (`p33_depth_census_v5.log`) on v5's 1,100 frames: the depth order
changes 25 frames (2.27%), 4,357 px, up to 915 px on one (R0-aftermath frame 96); the aprox key draws another picture
than the true depth tz on 2 frames (28 px); leaves holding 2+ active monsters: 12.54 a frame. Phase 3's own budget
(+0.3M, `docs/handoff-gameplay.md` P3) is the only declared number that covers it -- see "Phase 3 summed" below.

**Kill criteria** (class F, as run -- written at ship, not before):
1. Host: `tests/host/test_depth_order.py` (frame 96: the order changes the picture, aprox = tz there);
   `test_oracle_calls_in_step.py` pins which gate asks for `GAME_RENDER_KW` and which for `HOSTED_RENDER_KW`;
   `monstercode.depth_walk` raises when the setting asks for an order the mode cannot emit.
2. fj: `tests/fj/test_thing_pass_depth_fj.py` (160 records x 4 leaves of 1-4 things, ties and reorders, the `tstop`
   budget stop counted across leaves, all 13 cleared registers zero after every leaf; strict controls: the first
   candidate taken, the key without dy, the tie toward the later index, either tstop test removed, sp_lt's clear
   narrowed).
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact with the game oracle's depth order; their selftests; B0 v5
   exact on every frame; deg_gate byte-exact.
4. CAP-22 on v5; size <= 35%; msframe recorded (D8).
5. pinreport 20 of 20 (heat list p33); the restore sets re-keyed.

**v5 under the depth rule** (`p33_v5_validate_depth.log`, before main froze v5 on this branch): F3 PASS -- the replay
reproduces every frozen pose and digest (11/11 runs: the depth order moves no trajectory); F4 FAIL -- the drawn census
differs on 6 runs (a binding monster budget now drops by depth, not by index); F1 / F2 / F5 FAIL / FAIL / FAIL -- the
set was PLANNED on this branch, FROZEN on main. The frozen record's drawn census and file hashes must be re-recorded
(a follow-up; B0 on v5 itself is exact on every frame of blocked46).

**Row and verdict**: one build carries P3.3 and P3.4 -- the owner united them on 2026-10-02 ("lets get over with it
much faster. No need for another entire testing pass for another menu"). The row and both verdicts are P3.4's, below.

## P3.4 the key-map help screen (class F) -- declared 2026-10-02, before the build

**What**: `docs/gp-help.md`. A HELP screen -- the keys that work today and what they do, a baked
frame from `doomfj.menu`'s one generator -- opened from the main menu (its new HELP item: up / down /
enter, or h) and from the world (h); esc or h close it back to where it was opened. 'e' is a second
use key; 'h' the help event. No new persisted cell: `menu_scr` 3 / 4 / 5 (the help from the menu,
from the world; the main menu on HELP). The main menu loses QUIT (never selectable).

**Budget**: ops ESTIMATE ~+0 on the binding metric (one `hex.if0` and one `hex.zero` a world frame;
a tiny-harness ESTIMATE of +1.9 to +6.5 ops a frame, `docs/gp-help.md` section 3); size <= +0.12M
words -- ESTIMATE 97,088 words for the 6,068 new stream bytes (the help 4,770, the main menu on HELP
1,318, the main menu -18) at P2a.2's 8 ops x 2 words a byte, plus the decode and the state lines.
(The brief proposed +0.1M; the frames alone are 97% of that, so +0.1M would be a coin toss on
arithmetic already done -- the coordinator decides whether to hold the rung to it.) No plane ids.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host: `menu_step`'s help rules (`test_the_help_rules`: both opens, both closes, the main menu's two
   items clamped, h ignored on the skill screen and LEVEL COMPLETE, the event order); the help picture
   decoded by the real device equals the oracle's, its title and every row glyph-exact in their
   colours and nothing else inked, with a moved-pixel control and a too-wide-row control;
   `menu_screen_pixels` gives the seven states seven pictures, the help one picture under both ids.
2. fj: `kb.poll`'s 'e' and 'h' against the mirror, with controls; the help lists EXACTLY the keys
   that work (run, both directions, an unbound-key control); the state machine's nine help scripts
   with four mutants caught (`test_skill_menu.py`); the whole menu block frame by frame through both
   devices, two controls (`test_menu_screens.py`).
3. Gates: `m3_gate` byte- and state-exact on all 50 frames -- the help from the world (W held across
   it, no move) and from the main menu, both closes, all seven menu pictures -- and its four selftests
   rejected where they must (`--selftest-help` at frame 34); `m2_std_gate`, `p2a_gate` byte- and
   state-exact (their scripts never press h; the main menu's down now moves a highlight -- neither
   presses it on the main menu); B0 on v5 exact.
4. Gameplay ops unchanged within noise: the binding metric on v5 and gamespeed's may move only by
   placement, which `profx/phases.py` must show -- the input phase within +100 ops a frame of P3.3's
   binary and the rung's own phases flat; CAP-22 on v5; size <= +0.12M words and <= 35%; msframe
   recorded (B SLOWER without an explanation kills it).
5. pinreport 20 of 20; the restore sets re-keyed (`ev_help` is a new restore-set label; no persist
   change); `probe.RECORDED_CALIBRATION` re-recorded (the startup + 2 menu frames changed: the main
   menu's picture and its state path).

**Row** (the UNITED rung P3.3 + P3.4: blocked46, sha256 `b7c9e110be1494d8`, built at 5748228 with `heat_blocked27_p33`; `docs/ship-evidence/blocked46_*`):

| measure | blocked45 (P3.2c) | blocked46 (P3.3 + P3.4) | delta |
|---|---|---|---|
| combat set binding (v5) | 15,087,224 | 15,560,076 | +472,852 |
| ... with strafe's collision | 15,122,674 | 15,594,013 | +471,339 |
| v5 per-frame maximum (+/- 2^18) | 25,690,112 | 26,214,400 (R0-aftermath) | +524,288 |
| gamespeed binding | 14,462,688 | 15,243,295 | +780,607 (P3.4: ~+0 ESTIMATE; P3.3: none declared) |
| profx mean frame (gamespeed's games) | 12,321,663 | 12,911,839 | +590,176 |
| input phase (phases.py) | 1,137 | 1,193 | +56 (P3.4's bound +100) |
| size (% of 2^27) | 33.92% | 34.19% | +355,886 words (P3.4's budget +120,000: OVER) |
| pool tables (build) | 471,582 in 33,949 groups | 473,950 in 34,185 groups | +2,368 tables |
| ms/frame (msframe, one run, A = blocked45; the pictures differ, so its pixel check reads NO) | 77.1 | 79.5 | NOT SEPARATED (x0.958) |
| hot words pinned (pinreport) | 20/20 | 20/20 | 0 lost |

**r0, stopped at the pin report.** The first build (r0, sha256 `fc45c241867e738c`, at 7dfc22a, `blocked46_r0pins_*`
logs) passed the smoke run, m2_std_gate (452 frames), m3_gate (50 frames, the help visits included) and the 6 gate
selftests, then STOPPED at its pin report: 17 of 20 hot words, 3 UNRESOLVED (an ESTIMATE of ~106,873 ops/frame of lost
pins) -- the walk's pointer register moved from `sim.thing_pass`'s local `hp` to `sim.thing_pass_depth`'s global
`td_p`, so `heat_blocked27_p32a` named words this program no longer has. 7e97a5a taught `heat_rekey` / `pinreport` a
whole-token text rename and wrote `heat_blocked27_p33`; on r0's binary B0 v5 was exact on every frame (15,621,284,
`blocked46_r0pins_b0_v5_precheck.log`) and p2a_gate passed (13 scenarios, `blocked46_r0pins_p2a_precheck.log`). r1 is
the same program built with `heat_blocked27_p33`; its evidence is `blocked46_*`.

**Where the ops went** (one binary for two rungs: P3.4's "placement only" clause cannot be judged apart from P3.3's
walk). gamespeed moved +780,607, B0 v5 +472,852, profx's mean frame +590,176; the input phase 1,137 -> 1,193 (+56,
P3.4's bound +100: inside). phases.py lines that moved >= 10,000 ops/frame (blocked45 -> blocked46): render walk, all
11,878,314 -> 12,479,305; seg_pass2_leaf 3,623,277 -> 3,578,343; seg_pass1_ts_leaf 2,472,239 -> 2,500,839;
seg_pass1_leaf 2,366,784 -> 2,354,320; thing_pass_leaf 669,426 -> 1,328,319; bspcode walk (nodes, pos_leaf, ss code)
896,926 -> 848,554; thing_leaf_b 782,615 -> 801,257. **The depth walk is the cost**: `thing_pass_leaf`, the leaf
thing walk that `sim.thing_pass_depth` replaces, moved +658,893 -- n rounds that each recompute every candidate's
P_AproxDistance key; the other lines net to placement. Caching each leaf's keys once is follow-up #117.

**Size**: +355,886 words **OVER** P3.4's declared +120,000 -- shipped on the coordinator's statement: P3.4's +0.12M
was declared for the help screen alone; this binary also carries P3.3's depth walk, which declared no budget (the two
rungs were united on 2026-10-02 and no single-rung binary was built). The build logs split the +355,886 words as
+178,272 of pool demand (46,794,944 -> 46,973,216 words; +2,368 tables) and +177,614 below the pool. The help frames
alone were estimated at 97,088 words before the build; the rest is not attributed per rung, because nothing measured
the rungs apart. Size is 34.19% of 2^27, still under the 35% target. -- +217,388 below the pool (the program,
28,598,938 -> 28,816,326) and +138,498 in it (16,932,696 -> 17,071,194 payload words; +2,368 tables). P3.4's +120,000
was declared for P3.4 ALONE (the help stream ESTIMATE 100,992 words); P3.3's walk, with no budget, is in the same
delta. **Size is now 34.19% of 2^27 against the 35% target: 1,088,684 words (0.81 points) of room left.**

**msframe NOT SEPARATED is the class-F record (D8)**: 77.1 -> 79.5 ms/frame (pairs 1.134 0.958 0.911 0.976 0.954),
14,828,598 -> 15,580,689 ops/frame on msframe's walk, 192.3 -> 195.9 M fj/s. The `shipped` baseline is still
blocked44's: neither blocked45 nor blocked46 has been frozen (#115).

**Verdict P3.3 (as run): every criterion met.**
1. Host: 1454 passed, 2 skipped, 1 deselected, 2 xfailed, 3 warnings (`blocked46_host_suite.log`, at the build's
   commit 5748228), `test_depth_order.py` and `test_oracle_calls_in_step.py` among them.
2. fj: `test_thing_pass_depth_fj.py` in `p33_p34_fj.log` (89 passed in 34.48s, with the help screen's fj tests).
3. m2_std_gate (452 frames), m3_gate (50 frames), p2a_gate (13 scenarios) byte- and state-exact; 7 gate selftests
   PASS; B0 v5 exact on every frame (11 runs, 1,100 frames: state and pixels); deg_gate BYTE-EXACT with every op count
   equal to blocked45's.
4. CAP-22 on v5: 15,560,076 (headroom 6,439,924; the per-frame maximum 26,214,400 in R0-aftermath is not the cap's
   measure); gamespeed 15,243,295 PASS; size 34.19% (<= 35%); msframe recorded (NOT SEPARATED: median x0.958).
5. pinreport 20 of 20 with `heat_blocked27_p33` (r0's 17 of 20 above); the restore sets re-keyed (`p33_rekey.log` 22
   passed in 0.78s).

**Verdict P3.4 (its declared kill criteria): met, with the coordinator's stated exceptions: size over +120,000.**
1. Host: 1454 passed, 2 skipped, 1 deselected, 2 xfailed, 3 warnings (`blocked46_host_suite.log`):
   `test_the_help_rules`, the help picture through the real device glyph-exact with its controls, the seven states'
   seven pictures (`tests/host/test_menu.py`).
2. fj: `p33_p34_fj.log` -- 89 passed in 34.48s: `test_menu_screens.py`, `test_menu_frame.py`,
   `test_keyboard_input.py`, `test_skill_menu.py`, `test_menu_mode.py`, `test_thing_pass_depth_fj.py`.
3. Gates: m3_gate byte- and state-exact on all 50 frames (the help from the world and from the main menu, both closes,
   all seven menu pictures); `--selftest-help`: "SELFTEST (the oracle closes the world's help to the main menu): PASS
   -- the gate rejected it at frame 34, where it must" (`blocked46_gate_selftests.log`); m2_std_gate (452 frames) and
   p2a_gate (13 scenarios) byte- and state-exact; B0 on v5 exact.
4. The input phase +56 ops a frame (bound +100: inside); the binding metrics moved +780,607 (gamespeed) and +472,852
   (v5) with P3.3's walk in the same binary; CAP-22 on v5 15,560,076; size +355,886 words (OVER +120,000) and 34.19%
   (<= 35%); msframe recorded (NOT SEPARATED: median x0.958).
5. pinreport 20 of 20; the restore sets re-keyed (`p33_rekey.log` 22 passed in 0.78s; `ev_help` is in the standalone
   set). `probe.RECORDED_CALIBRATION` (518_147) was NOT re-recorded, and need not be: it is blocked27's number, keyed
   by `RECORDED_SHA16` (`38b09a7331f4f52b`), and probe's C5 / B0's T3 SKIP on every other binary -- the criterion as
   declared named a check that never runs on blocked46.


## Phase 3 summed (written at P3.3 + P3.4's ship, 2026-10-03; issue #115)

SUMMED from the rows above, NOT re-measured: each rung's gamespeed binding delta as its own row recorded it (one A
binary to the next; the rows telescope -- each starts where the last ended, checked when this was written).

| rung | gamespeed binding | delta |
|---|---|---|
| P3.0 | 13,642,413 -> 13,696,511 | +54,098 |
| P3.1 | 13,696,511 -> 13,940,191 | +243,680 |
| P3.2a | 13,940,191 -> 14,086,236 | +146,045 |
| P3.2b | 14,086,236 -> 14,452,893 | +366,657 |
| P3.2c | 14,452,893 -> 14,462,688 | +9,795 |
| P3.3 + P3.4 | 14,462,688 -> 15,243,295 | +780,607 |
| **phase 3** | **13,642,413 -> 15,243,295** | **+1,600,882** |

**Against the phase's budget of +0.3M** (`docs/handoff-gameplay.md`, P3): +1,600,882, OVER -- 5.34x the budget. This
file's header puts a cumulative overrun to the owner (the projection > 22M minus the remaining budgets minus a 15%
reserve -> stop); this section records the sum and does not apply that rule. P3.2c and P3.3 declared no budget of
their own. The CAP-22 measure is v5's: 15,560,076 (headroom 6,439,924 to 22M).


## P4.0 the game screen (class F) -- declared 2026-10-04, before the build

**What**: `docs/gp-combat.md` section 2. The game tier's view becomes 160x84 (`config.GAME_CFG`, D6), so the view's
dittos become PARTIAL dittos `[0xFD][84][0xFF]` (the device change flipjump#364, merged into `1.5.1` at 1cd6e0c). A
16-row status bar is drawn below the view in the menu's fonts: AMMO, HEALTH, ARMS, ARMOR, KEYS, redrawn per slot
only when its value changes, and whole after every menu frame. The ready pistol (`PISGA0`) is drawn over the view as
KEEP records with constant colours, because all of E1M1's sectors light a psprite with colormap row 0. The values
are the level start's (100 / 0 / 50, the pistol), and the card is the doors' `pcard`. The aim window moved to P4.1
(gp-combat C1), where it is first read. No v6: the 84-row view leaves every seen set of v5 unchanged (1,100 of 1,100
frames, `scratchpad/plan/p4/view84` in the session, recorded in gp-combat C5).

**Size target**: from this rung on it is **40% of 2^27** (gp-combat C2; the owner, 2026-09-25 and 2026-10-04).

**Budget** (ESTIMATES; their basis):
- v5 binding: **-0.3 .. -1.2M**. The 84-row view cuts the oracle's stream proxy by 10.0% (mean) and 11.0% (p80) and
  floor/ceiling pixels by 20%. The weapon costs ~6K a frame (343 runs x 16 ops, baked), the bar's 13 slot tests
  ~1-2K, and the partial dittos +16 ops each (~0.9K).
- gamespeed: the same sign.
- size: **<= +0.3M words**. The weapon's records, the bar's static columns and the 13 slots' variants come to
  ~0.1M words of constant output, and placement adds to that.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host: `tests/host/test_hud.py` (the slot columns equal the full bar for 4 value sets; a changed value changes
   only its slot; the pistol's geometry, with a shifted-psprite control; one light row on E1M1; only the game tier
   has the bar) and `tests/host/test_collines_device.py`'s token differential with its two controls.
2. fj: `tests/fj/test_hud_fj.py`, 8 frames of the REAL emitted tail against the oracle's screen, every slot changed
   and a menu frame in between, with three mutants rejected at the stated frames (inverted change test -> 0,
   shadows not invalidated -> 6, KEEP one row short -> 0).
3. Gates: m2_std_gate, m3_gate and p2a_gate byte- and state-exact against the oracle's game screen
   (`hud.GameScreen`: the 84-row view, the weapon, the bar); their selftests rejected where they must; B0 on v5
   exact; deg_gate unchanged (the visual tier keeps 100 rows), every op count to the digit.
4. v5 binding must not RISE by more than 0.1M over blocked46's 15,560,076, because the 84-row saving is the
   premise. gamespeed is recorded. size <= +0.3M words and <= 40%; msframe recorded (D8).
5. pinreport 20 of 20, and the restore sets re-keyed (`hud_v`, `hud_s`, `hud_full` are new state).

**Row**: the UNITED build's (blocked47: P4.0 + P4.1 + P4.2a + P4.2b) -- "P4 united: the row and the verdicts" below; no binary of this rung alone was built.


## P4.1 the trigger (class F) -- declared 2026-10-04, before the build; UNITED with P4.2a into one build (the owner, 2026-10-04: merge small rungs -- gp-combat section 5)

**What**: `docs/gp-combat.md` section 1. The model's "fire" mode (`World(player="fire")`, `wall_renderer.PLAYER_MODE`):
- **The owner's key map** (approved 2026-10-02): A / D and ',' / '.' strafe, only the arrows turn, ctrl fires,
  1..4 are held weapon keys. Seven new persisted held flags.
- **The help screen** updated to that map: three legend lines beside the clusters, and two-item key rows.
- **Strafe** in the game tier's sim, and `step_sim(strafe=True)` in the oracle. The side step is the model's
  `combat._player_move`.
- **The weapon** (`doomfj.weaponcode`): DOOM's psprite machine for the fist, pistol, shotgun and chainsaw. Each state
  is a baked block, and a nested P_SetPsprite is a tail jump. The flash is an fcall'd chain. The ammo checks and
  DOOM's out-of-ammo preference are included, and each shot advances the player's stream by its draws (1 for the
  accurate pistol shot, 3 for every other shot).
- **The screen**: the overlay drawn per weapon frame (`wp_frm`) with the flash over it (`fl_frm`), and the bar's
  ammo and arms written by the weapon tic.

Nothing is applied: no target, no damage, no noise (P4.2). The aim window moved to P4.2 with the hit (gp-combat C1):
"fire" never reads a shot's outcome.

**Budget** (ESTIMATES; their basis):
- v5 binding: **+0.02 .. +0.08M**.
  - The weapon's tic is a few hundred ops a frame plus a state block on transitions.
  - The overlay costs what P4.0's did: one constant frame of ~5-7K ops, plus the dispatch.
  - Strafe costs two `fixed_mul_lo` on the frames that strafe.
  - B0 delivers no fire and no strafe, so the binary's weapon only idles there.
- gamespeed: the same, plus the arrows now turning: gamespeed's scripts turn, and the turn is the same tic.
- size: **<= +0.6M words**. 14 more weapon frames and 3 flash frames of constant records, at ~5K words each before
  the pool factor, plus the state blocks.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host: `tests/host/test_player_modes.py` ("fire" equals "full" on every weapon field and the player's stream for
   400 tics, a gun that draws nothing parts); `tests/host/test_menu.py` (the re-pinned help screen and its controls);
   `tests/host/test_hud.py`.
2. fj: `tests/fj/test_weapon_fj.py` (the real weapon text equals the fire mode on every tic of two 600-tic runs,
   with four mutants caught); `tests/fj/test_player_strafe_fj.py` (every key combination at five poses and a
   300-tic trajectory, two mutants caught); `tests/fj/test_keyboard_input.py` (the new map; the help lists exactly
   the keys the poll binds); `test_hud_fj.py`; the menu fj tests.
3. Gates: m2_std_gate, m3_gate, p2a_gate and B0 v5, byte- and state-exact, with the weapon cells in the state check
   and the psprite frames in the picture; their selftests rejected where they must; deg_gate unchanged.
4. v5 binding within +0.1M of P4.0's; size <= +0.6M words and <= 40%; msframe recorded (D8).
5. pinreport 20 of 20, and the restore sets re-keyed (the weapon cells persist; `psid`/`psdx`/`psdy`, `wp_bcd` and
   `fl_ret` are scratch).

**Row**: the UNITED build's (blocked47: P4.0 + P4.1 + P4.2a + P4.2b) -- "P4 united: the row and the verdicts" below; no binary of this rung alone was built.


## P4.2a the hit (class F) -- declared 2026-10-04, before the build; ONE build with P4.0 and P4.1 (gp-combat section 5)

**What**: the model's "shoot" mode (`World(player="shoot")`, `wall_renderer.PLAYER_MODE`):
- **The aim window** (`doomfj.aimcode`; the oracle: `render_wall_frame(aim_out=)`). The runtime monsters'
  projections record, per column 72..88, the nearest shootable monster whose r_eff box covers the column and no
  nearer solid wall hides; `aim_sid` persists for the next frame's weapon.
- **The shots** (`weaponcode`, shoot=True): each shot draws its outcome from the player's stream through the folded
  table `wpo`, reads `aim_sid` at its column and hands the target to `dm_go`.
- **The damage** (`doomfj.damagecode`): copy stubs into ONE `dm_leaf`, which does health, the bullet or melee reach,
  the pain roll on the monster's stream, the death state with its tics roll, justhit and the threshold / target wake.
  A_Fall clears `mon_solid`; the thing test and the door contact read `mon_solid` / `mon_shootable`.

No noise (P4.2b), effects (P5), barrels, drops or berserk (P6). The gates step the weapon at the pre-move pose and
write each picture's window back (`MonsterPhase.set_aim`); B0 delivers fire and the number keys (v5 fires on 36
frames).

**Budget** (ESTIMATES; their basis):
- v5 binding: **+0.02 .. +0.1M**. The window costs ~0.05M a fight frame (gp-aim-window 3), now on monsters only. A
  shot costs ~0.3K on a miss and ~3K on a hit; a kill also moves the monsters' own costs, so this is approximate.
- size: **<= +0.5M words**. Three D4 tables (`aimr`, `wpo`, `dmrnd`), 53 copy stubs, the leaves and 17 column
  blocks, and placement.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host:
   - `tests/host/test_player_modes.py`: shoot == full on every monster cell and the player's stream, for four types,
     with a painless control.
   - `test_aim_window_oracle.py` and `test_damage_tables.py`.
   - `test_gp_shot_table.py`.
2. fj, the real emitted text against the model, with every mutant caught:
   - `test_aim_record_fj.py`: 400 records; mutants r+1, a tie overwriting, drawn ignored, no range test.
   - `test_player_shot_fj.py`: 4 scripts x 1500 tics; mutants column+1, the accurate shot's column, 6 pellets, the
     saw's melee flag.
   - `test_monster_damage_fj.py`: 320 shots, 8 mutants.
   - the decide and chase harnesses with justhit, A_Fall and a corpse not blocking.
3. Gates, byte- and state-exact with `aim_sid` and the damage cells in the state check:
   - m2_std_gate, m3_gate and p2a_gate;
   - B0 on v5, firing, exact on every frame;
   - deg_gate unchanged (the visual tier has no aim).
4. v5 binding <= 22M (CAP-22). The rise is recorded against blocked46, the P4.0 + P4.1 + P4.2a sum. size <= 40%;
   msframe recorded (D8).
5. pinreport 20 of 20 with `heat_blocked27_p42`; the restore sets re-keyed (the weapon, window, bar and damage
   cells persist).

**Row**: the UNITED build's (blocked47: P4.0 + P4.1 + P4.2a + P4.2b) -- "P4 united: the row and the verdicts" below; no binary of this rung alone was built.


## P4.2b the noise (class F) -- written at ship, 2026-10-04: NO budget or kill criteria of its own were declared in this file before blocked47's build

**What**: the shots are HEARD (`doomfj.noisecode`; the model's `PLAYER_MODE = "hit"`, 5fe7b81). At each shot the
weapon fcalls `nz_leaf`: P_NoiseAlert's flood over E1M1's 35 sound edges from the player's sector at the pre-move
pose (the open test on the dynamic sectors' door / lift / switch cells), ORed into the persisted `snd_alert`; A_Look's
sound branch (`nz_heard`) wakes a non-ambusher and needs the waking sight for an ambusher; `mon_ambush` persists and
clears at A_FaceTarget. It joined the united build under gp-combat section 5 ("P4.2b ... joins the build if it is
ready when P4.2a is").

**Budget**: none of its own. P4.2a's declaration says "No noise (P4.2b)", so no declared number covers it; it is NOT
back-filled.

**Kill criteria** (as run -- written at ship, not before): `tests/fj/test_noise_fj.py` (the flood against
`World.noise_alert`, 182 sectors x 4 state mixes + 54 located points, controls onepass / noscratch / invert caught;
the sound branch, noambush / deaf caught; the decide tic with hear, noface caught -- c1e179d; after the merged decide
harness, its 3 decide tests and the flood with its controls 10 passed -- a151dc6); `tests/host/test_player_modes.py`
(hit == full on the monster cells and alerts over 600 tics, a shoot control parts -- c1e179d); `mon_ambush` /
`snd_alert` persisted and in the gates' state check (5fe7b81); then the united build's gates below.


## P4 united: the row and the verdicts (blocked47, written at ship 2026-10-04)

ONE build carries P4.0, P4.1, P4.2a and P4.2b (the owner, 2026-10-04: "try to merge small rungs"; gp-combat section
5). **Row** (blocked47, sha256 `9e4ab7d92ff9649d`, built at 3bfe5ed with `heat_blocked27_p42` and flipjump 1.5.1 at
`1cd6e0c`; `docs/ship-evidence/blocked47_*`):

| measure | blocked46 (P3.3 + P3.4) | blocked47 (P4) | delta |
|---|---|---|---|
| combat set binding (v5) | 15,560,076 | 15,851,173 | +291,097 |
| ... with strafe's collision | 15,594,013 | 15,889,348 | +295,335 |
| v5 per-frame maximum (+/- 2^18) | 26,214,400 (R0-aftermath) | 25,427,968 (R0-aftermath) | -786,432 |
| gamespeed binding | 15,243,295 | 15,403,663 | +160,368 |
| gamespeed mean / p80 run | 12,911,839 / 17,574,751 | 13,035,385 / 17,771,942 | +123,546 / +197,191 |
| input phase (phases.py) | 1,193 | 1,141 | -52 |
| size (% of 2^27) | 34.19% | 34.25% | +86,672 words (the target is now 40%: 7,712,899 words of room) |
| pool tables (build) | 473,950 in 34,185 groups | 483,308 in 35,102 groups | +9,358 tables |
| ms/frame (msframe, one run, A = blocked46; the pictures differ, so its pixel check reads NO) | 73.4 | 73.0 | NOT SEPARATED (x1.000) |
| hot words pinned (pinreport) | 20/20 | 20/20 (0 broken groups of 35,102) | 0 lost |

**Where the ops went** (phases.py on gamespeed's games; one binary for four rungs, so nothing below is attributed per
rung). profx's mean frame 12,911,839 -> 13,035,385 (+123,546). Lines that moved >= 10,000 ops/frame: move / turn
10,172 -> 21,660 (+11,488); glue between phases 163,821 -> 175,291 (+11,470); render walk, all 12,479,305 ->
12,573,119 (+93,814) -- inside it seg_pass1_leaf +130,754, seg_pass2_leaf -75,745, seg_pass1_ts_leaf -53,678, vpb
bands-as-code (plane bands) -32,499, bspcode walk +26,216, thing_leaf +25,967, and a "bad/padding" line of 82,391
that blocked46's profile did not have (not attributed here). The plane bands fell, as the 84-row view's premise said;
the net did not.

**Size**: +86,672 words -- below the pool 28,816,326 -> 28,590,852 (-225,474), in the pool 17,071,194 -> 17,383,340
payload words (+312,146; +9,358 tables; demand 46,973,216 -> 47,366,720). 34.25% of 2^27. **The size target is 40%
from P4.0 on** (gp-combat C2, the owner 2026-09-25 + 2026-10-04); the binary is also under the old 35% (1,002,012
words of it left).

**msframe NOT SEPARATED is the class-F record (D8)**: 73.4 -> 73.0 ms/frame (pairs 1.025 1.007 0.999 1.000 0.998),
15,580,689 -> 15,632,447 ops/frame on msframe's walk, 212.2 -> 214.2 M fj/s. **The run was taken with
`--ignore-busy`**: the owner's fullscan.py (pid 28924) ran beside it, logged as `python(28924) 1.0s/s`, not ours to
stop; the run's note says so; its yardstick median read 3.47G, under ship-gate step 2's ~3.5 G quiet line. The `shipped` baseline is still blocked44's (#115).

**Found and fixed during the rung** (each before blocked47 shipped):
- 7dd242a: `init_screen` (it zeroes the device's palette and pixels) ran every frame in main, because the M1 reset
  re-enters at `__hot_end`; it would have blanked every bar column the tail does not redraw. Moved to the entry part;
  caught by the P5 integrator before the P4 build started.
- 3bfe5ed: the re-key STOPPED at `m5_setfile` -- the standalone restore set never carried the game screen's persisted
  cells (hud / weapon / aim). `build.game_screen_persisted_decls` is now the one list, read by `m5_setfile` and the
  test; `m5_setfile --selftest`'s C5b positive control had been refusing since the monsters' cells joined and now
  carries every persist name (`p4_rekey.log`: 436 -> 518 entries, 15,198 words; 22 passed).
- f045865: blocked47's first p2a_gate run FAILED with pixels byte-exact and every P4 cell read as None -- the probe's
  hand-kept READ list never took them. It now reads every game cell, which exposed the bar's card rule (the binary
  reads `pcard`; the gate's oracle lit the card only when it was gone from the world: 38 px in S3). Re-run 13/13 exact.
- 02993d7: `test_restore_set_shipped` now requires the standalone set to carry every `build.persist_labels` name, so
  the next missing cell fails in a millisecond, not at the re-key's last step.

**Verdict P4.0 (its declared kill criteria): NOT all met -- criterion 4's v5 bound is EXCEEDED.**
1. Host: 1500 passed, 2 skipped, 1 deselected, 2 xfailed (`blocked47_host_suite.log`), `test_hud.py` and
   `test_collines_device.py` among them.
2. fj: `test_hud_fj.py` -- 4 passed with the three mutants rejected at frames 0 / 6 / 0 (599aada), then 6 passed with
   the psprite frames and the flash (4ad32a9). No fj-suite log is in `blocked47_*`; these are the rung commits' runs.
3. Gates: m2_std_gate (452 frames) and m3_gate (50 frames) byte- and state-exact, p2a_gate 13/13 (after f045865); the
   7 gate selftests rejected where they must (`blocked47_gate_selftests.log`); B0 v5 exact on every frame (11 runs);
   deg_gate BYTE-EXACT with every op count equal to blocked46's (`blocked47_deg_gate.log`).
4. **v5 must not rise by more than 0.1M over 15,560,076: it rose +291,097 (15,851,173) -- EXCEEDED.** No P4.0-only
   binary was built, so the rise cannot be split between P4.0's view and the trigger, hit and noise in the same
   binary; but the summed v5 ESTIMATES of the three declared rungs (P4.0 -0.3 .. -1.2M, P4.1 +0.02 .. +0.08M, P4.2a
   +0.02 .. +0.1M) are -1.16 .. -0.12M, and the measured +0.29M is outside that range: the 84-row saving premise did
   not show in the net. Shipped on the coordinator's decision (this commit), as class F under D8: CAP-22 and size
   pass. gamespeed +160,368 (the declaration said "the same sign" as v5's ESTIMATE; it is not). Size +86,672 words
   (<= +0.3M: held) and 34.25% (<= 40%: held); msframe recorded.
5. pinreport 20 of 20 (`heat_blocked27_p42`); the restore sets re-keyed with `hud_v`, `hud_s`, `hud_full` (3bfe5ed).

**Verdict P4.1 (its declared kill criteria): met, except criterion 4's v5 comparison, which cannot be judged.**
1. Host: the full suite above; `test_player_modes.py`, `test_menu.py` and `test_hud.py` among them.
2. fj (the rung commits' runs, 4ad32a9): `test_weapon_fj` 6 passed, `test_player_strafe_fj` 4 passed,
   `test_keyboard_input` + `test_menu` 72 passed, the menu fj tests 50 passed, `test_hud_fj` 6 passed.
3. Gates as in P4.0's 3; m2_std_gate's first walk holds and taps fire and switches weapons (4ad32a9). The gates' state
   check reads the weapon cells through the probe / gatestate (4ad32a9); the logs' CONTROL 7 line still names only
   view, mode, menu and doors.
4. "v5 within +0.1M of P4.0's": NOT JUDGEABLE -- no P4.0 binary exists to compare with; the united rise is in P4.0's
   verdict. Size: the united +86,672 words is under P4.1's own <= +0.6M; 34.25% <= 40%; msframe recorded.
5. pinreport 20 of 20; the weapon cells persist in both restore sets (3bfe5ed).

**Verdict P4.2a (its declared kill criteria): met.**
1. Host: `test_player_modes.py` (shoot == full for four types, a painless control parts -- 743e11f),
   `test_aim_window_oracle.py` (6 passed, 83901a0), `test_damage_tables.py` (5 passed, 22e95fd),
   `test_gp_shot_table.py` (4 passed, 2843dd0); the full suite above.
2. fj (the rung commits' runs): `test_aim_record_fj` 5 passed, mutants r+1 / tie overwrite / drawn ignored / no range
   test caught (743e11f); `test_player_shot_fj` 12 passed, 4 skipped, mutants col_plus1 / acc_table_col / six_pellets
   / saw_not_melee caught (2843dd0); `test_monster_damage_fj` 320 shots, 8 of 8 controls caught; the decide harness
   (nojhclear, nofall caught) and the chase harness with a corpse (active caught) (22e95fd).
3. Gates as in P4.0's 3, with `aim_sid` and the damage cells in the probe / gatestate (74573bc); B0 on v5 delivers
   fire and the number keys (v5 fires on 36 frames, ae16682) and is exact on every frame.
4. CAP-22: v5 15,851,173 <= 22,000,000 (headroom 6,148,827). The rise against blocked46, the whole of P4: +291,097
   (above). Size 34.25% <= 40%; the united +86,672 words is under P4.2a's own <= +0.5M; msframe recorded (NOT
   SEPARATED).
5. pinreport 20 of 20 with `heat_blocked27_p42`; the restore sets re-keyed (3bfe5ed; 02993d7 widened their test).

**Against the phase's budget** (`docs/handoff-gameplay.md`, P4: +0.6M): gamespeed +160,368 and v5 +291,097 -- both
inside it.


## P5 the monsters' attacks (class F) -- declared 2026-10-04, before the build

**What**: `docs/gp-p5-interface.md` -- ONE rung, the model modes `MONSTER_MODE = "full"`, `PLAYER_MODE = "fx"`
(`wall_renderer`; `monstercode.p31_parts` refuses a pair where the attacks land without a hurtable player or the
reverse):
- **The attacks land** (`doomfj.hurtcode`, agent B): the zombiemen's and sergeants' bullets (`mbul`, 3 draws folded
  with the hitscan's reach), the imp's claw and the demon's bite (`trclaw`, `sgbite`) through ONE `dp_go` --
  combat.damage_player: the armor's save, the damage count, health, the death moment (p_dead, the weapon's
  downstate), one rng_pl draw per hit. A dead player is lost as a target, blocks nothing, and his weapon stays down.
- **The imp's fireball and the blood** (`doomfj.projcode`, agent C): the 8-slot fireball pool (`pj_spawn`,
  `pj_phase`: the momentum, the missile cells `mc6`, the player's box, the impact, the explosion) and the 2-slot blood
  pool a hit spawns (`fx_spawn` from damagecode's reordered `dm_leaf`, `fx_phase`), one shared window, rng_fx.
- **The mobiles drawn**: runtime things nt .. nt + 9 (`p31_parts`' `nmob`), one VIEW row per mobile lump (BAL1A0 ..
  BAL1E0, BLUDA0 .. BLUDC0) -- the scenery class, the base minimum height in both depth bounds, the art's top +
  MISSILE_Z, rotation 0 never mirrored -- chosen by a copy stub per slot into ONE shared tail (`thsel_mob`,
  `mobview` by the slot's state). The rows hold the WHOLE-UNIT position (`projcode._copy_out` clears the fraction).
- **The bar and the screen**: health and armor written every tic (`hp_bar`), the damage count's fade after the
  weapon, and the red palette (`palidx`; `present.set_palette playpal<k>` only on a change, before the record
  stream; a menu frame shows playpal 0). The game tier's `present.init_screen` and boot palette moved to the
  boot-only ENTRY part: run per frame they zeroed the device's palette (and its pixels) behind `pal_cur` and the bar.
- The frame's order: the door tic, the weapon (+ the fade), the move, the monsters, the fireballs, the blood, the bar
  (inside the frozen-level guard), the palette, the render.

**Budget** (ESTIMATES, UNVERIFIED; their basis):
- v5 binding: **+0.05 .. +0.3M** on v5's frames, which have few fireballs in flight. A flying fireball costs a point
  location (`ptloc_walk`) and a missile-cell test per tic: **~0.1-0.15M per fireball per tic** (agent C's estimate,
  UNVERIFIED). A hit costs `dp_go` (~1-2K), the bar ~1K a tic, the palette test ~0.3K a frame, a mobile drawn one
  more runtime thing (~10-20K).
- gamespeed: the same sign; fights with imps cost the most.
- size: **~+1.05M words** (agent C's size probe over a stub base: cells 723,068 + code/tables 329,210 = 1,050,234,
  UNVERIFIED), plus hurtcode's tables and 9 palettes (~7K words) and the mobile rows, stubs and `mobview`.

**Kill criteria** (any one -> the binary does not ship; class F):
1. Host: `tests/host/test_p5_splice.py` (the mobile rows against the oracle's draw rule, the select's stubs, the
   emit-time asserts and the label check with their controls, the boot screen, the tic's order),
   `test_player_modes.py` ("fx" == "full" on the monsters, streams, pools and player), `test_p5_hurt_model.py`,
   `test_mobiles_oracle.py`, `test_hurt_tables.py`, `test_projcode.py`; the restore-set tests pass once re-keyed.
2. fj, the real emitted text against the model, every mutant caught: `test_player_damage_fj.py`,
   `test_monster_attack_fj.py`, `test_palette_fj.py`, `test_weapon_fj.py` (hurt), `test_fireball_pool_fj.py`,
   `test_fx_pool_fj.py`, `test_missile_cells_fj.py`, `test_monster_damage_fj.py`, `test_mobile_rowselect_fj.py`,
   and `test_monster_wake_fj.py`'s hurt tests (run solo: it reached 3.2 GB).
3. Gates, byte- and state-exact with P5's cells and every present's palette: m2_std_gate, m3_gate, p2a_gate, B0 on
   v5 (no death: a mirror that dies fails), and `scratchpad/gp/hurt_gate.py` (H1-H6, S1, deaths 0, its 10 controls
   parting); their selftests rejected where they must; deg_gate unchanged.
4. v5 binding <= 22M (CAP-22), the rise recorded against the P4 build; size <= 40%; msframe recorded (D8).
5. pinreport 20 of 20 with the heat list re-keyed for any changed macro arity; the restore sets re-keyed (hurtcode's
   cells and `pal_cur`, the pools and `rng_fx` persist -- `build.HURT_PERSIST`, `PROJ_PERSIST`).

**Row**: (filled after the build)
