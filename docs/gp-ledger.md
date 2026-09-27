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

**Row**: (filled after the build)

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

**Row**: (filled after the build)

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

**Row**: (filled after the build)

## P1.6 the native-list sprite bank (class F) -- declared 2026-09-27, before the build

**What**: `docs/gp-sprite-bank.md`. Each patch column is stored once per tier (HD / MID / LD) as a
NATIVE run list, rows normalized to 0..255 of its own height (`doomfj.spritebank`), and drawn at the
thing's height bucket through `rowmap`, a D4 dispatch (`rowmap[b][n] = ceil(n * hb / 255)`) -- two
lookups a fragment, one a run; the record adds `u` to the tier's region instead of multiplying, and
takes a column iff its bucket is at least the list's `min_b` (the shared rule). The bank also holds
every frame and rotation of E1M1's monsters, barrels, fireballs, puffs and blood (306 views, 237
lumps), which nothing draws before P3.

**Budget**: size **-793,856 words** MEASURED at emit (16,635 blocks against 22,837; 2,129,280 against
2,923,136 words) while holding the animation; ops ESTIMATE +0.05 .. +0.15M on combat set v2's binding
(the rowmap lookups against the record's saved multiply). The frozen set: a v3 (below).

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

**Row**: (filled after the build)
