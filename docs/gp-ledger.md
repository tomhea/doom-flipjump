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
2. fj: the tic, the rotation, the row select and the tables on the engine against the model's rules, mutants
   caught (`test_monster_tic_fj.py`, `test_monster_rotation_fj.py`, `test_monster_rowselect_fj.py`,
   `test_monster_tables_fj.py`); the record's mirror and light-width parameters in `test_sprite_bank_fj.py`.
3. m2_std_gate, m3_gate, p2a_gate byte- and state-exact with every gate's oracle running `MonsterPhase` and
   drawing its views; their selftests reject where they must; B0 v4 exact (the idle monsters from the boot image).
4. CAP-22 on v4; size <= 35%; msframe recorded (the pictures differ from blocked38's -- monsters animate).
5. pinreport 20 of 20 with the re-keyed heat list (`heat_blocked27_p31`); the restore sets re-keyed.

**Row**: (filled after the build)
