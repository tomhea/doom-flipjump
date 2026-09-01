# Handoff — M4: nine levels in one image

**Written 2026-08-31, at the end of the session that merged M2, the flag retirement and the tier
API. Start at section 2b (PHASE A), then section 3. Nothing has been built or measured for M4 yet — section 2 is the whole
job, and R0 is deliberately the cheapest rung.**

Every number below is either MEASURED in that session (and says so) or is marked UNVERIFIED.
CLAUDE.md's rule stands: do not quote an ops/span/time figure without re-running the harness.

---

## 1. Where the tree stands

`main` is at `aac9a3c`. Three PRs merged this session, each through a full CR loop:

| PR | what |
|---|---|
| #79 | **M2 — the runtime door.** R3 (per-state constant blocks behind a nibble switch) + R4 (collision as ONE baked bit). +0.50% ops/frame, matched pair. |
| #80 | **PHASE 1 — the flag retirement.** 13 emitter flags gone; `src/fj` 8,802 -> 7,300 lines, 0 dead macros. |
| #81 | **PHASE 2 — the tier API.** `build_wall_renderer` 18 -> **6 parameters**. |

Also pushed: six commits to `origin/1.5.1` in the SEPARATE checkout at
`C:\Users\tomhe\Documents\flipjump-151`, including `fj -D NAME=VALUE` and the 11.3x assembler
speedup. Not CR'd — the owner asked for the push only. That remote redirects
(`flip-jump.git` -> `flipjump.git`); `origin` still points at the old URL.

**M2 is DONE. M3 and M5 are DONE. M4 is the only milestone left that changes the emitter's shape,
then M6 (ship).**

### The API you will be extending

    build_wall_renderer(out_fjm, *, wad_path=DEFAULT_MAP_WAD, mapname="E1M1", cfg=None,
                        tier="game", ablate=frozenset())

`tier` is a name from `wall_renderer.TIERS` (9 rows), and **the rule that keeps it a registry is:
A NEW COMBINATION IS A NEW ROW, NOT A NEW PARAMETER.** `game` is the default and is the shipped
playable binary. `emit_wall_renderer` takes the same `tier`, REQUIRED (no default — a forgotten
argument used to silently emit the biggest program there is).

⚠ **The two functions had DIFFERENT defaults before the tiers** (`emit` all-False, `build`
things/player_sim/collide/moving_things True). Confusing them produced seven wrong call sites
across two review rounds. `scratchpad/to_tier.py --selftest` pins the distinction.

### Measured this session, all on `main`

    shipped binary   89,494,606 span-words | 32,879,690 bytes | headroom 1.500 | flat
                     3,389 s assemble (two passes)
    RENDER_FLAT_MAX_WORDS = 2**27 = 134,217,728          (config.py, a MODULE constant)
    deg_gate         PASS byte-exact x4 at
                     43,199,791 / 34,296,380 / 39,341,354 / 32,812,917 ops
    emit_baseline    certified 138,710,408 | standalone 150,752,424 | hosted_doors 150,729,008 chars
    tests/host       460 passed, 1 deselected      tests/fj  156 passed (~29:30)
    peak assembler RSS ~9.5 GB of 16.8 GB for ONE level

⚠ **THE SPAN AND BUILD FIGURES ABOVE ARE SUPERSEDED as of the Phase A clamp-tail change** (they
remain the record of what `main` measured at aac9a3c). The same `game`-tier build now reports:

    shipped binary   74,091,162 span-words | 26,669,803 bytes | headroom 1.812 | flat
                     1,514 s total, 979.7 s assemble
    emit_baseline    certified 83,947,547 | standalone 91,165,493 chars   (both -39.5%)
    deg_gate         PASS byte-exact x4 at
                     43,192,505 / 34,296,270 / 39,327,546 / 32,861,669 ops
    ca2_sweep        260/260 frames byte-exact, median 24,306,866 ops (+0.10%)
    tests/host       464 passed, 1 deselected      tests/fj  168 passed (27:01)

Everything downstream that reasons from 89.5M -- the x4 budget arithmetic in section 2, the
break-even P in section 7 -- is CONSERVATIVE by that much. The x4 budget was set against the OLD
span, so re-deriving it is an owner decision, not an assumption to make here: 4 x 89,494,606 =
357,978,424 either way, but it is now 4.83x the new one-level span rather than 4.0x.

---

## 2. THE OWNER'S DECISION, 2026-08-31 — this supersedes the three-level plan

The earlier handoffs (`handoff-m5-m2-m3-m4.md` section 5, `handoff-complete-game.md`) say **three
levels, E1M1 + E1M5 + E1M8**. That is now OUT OF DATE in two ways:

1. **The target is ALL NINE E1 levels, and the level list must be CONFIGURABLE.**
2. The three-map choice had **no recorded rationale**. The owner's original words were only about
   the count ("try 3 levels at first, and not the whole line"); the specific triple appeared in a
   docs commit with no justification. Do not inherit it. **Which levels ship is a MEASUREMENT
   (R0), not an assumption** — the criteria that bind are band-index count, BSP-walk size and
   texture-union overlap, and none of those were ever measured per map.

### The budgets, verbatim from the owner

| | budget | note |
|---|---|---|
| **ops/frame** | **up to +10%** | the frame may get ~10% dearer. At the deg_gate worst viewpoint that is ~+4.3M ops. **This is what buys the wider LUT indices** — the owner said explicitly it is OK to use more nibbles in LUTs to make it work. |
| **span** | **89.5M -> ~358M words (x4)** | that EXCEEDS 2**28 (268,435,456), so the cap goes to **2**29 = 536,870,912**. The owner is fine raising it. A limit is not an allocation, but the RUNTIME image is real: ~2.2 GB at x4. |
| **build** | **assemble 2, 3 and 4 levels, then EXTRAPOLATE to 9** | the owner's explicit instruction. Do not attempt 9 cold. Measure the ladder, extrapolate time AND peak RSS, report before committing to the full build. |
| **fallback** | **drop levels, keep full detail** | if 9 does not fit, ship 8/7/6... at today's fidelity. Do NOT reduce far-detail with the DEG knobs. The count is configurable, so the binary stays honest about what it holds. |

### What "configurable" means

The level list is a build-time input — `build_wall_renderer(out, levels=["E1M1", ...])` or, better
and consistent with PHASE 2, carried on `cfg` so the parameter count does not creep back up. **Six
parameters was the owner's ask and it was hard-won; adding a seventh needs a reason.** A tier is
about WHICH PROGRAM; the level list is data, like the wad — `cfg` is the natural home.

### The wads

    assets/freedoom1.wad             36 maps: E1M1..E1M9, E2M1..E2M9, E3M1..E3M9, E4M1..E4M9
    tests/fixtures/freedoom_e1m1.wad  1 map:  E1M1  (the cut-down fixture the gates use)

⚠ **The gates and the emission baseline all run on the FIXTURE, which has one map.** Any
multi-level work needs the full wad, and that changes the texture/flat union — so a multi-level
emission is NOT comparable to the baseline hashes. Keep single-level emission byte-identical
(that is what `emit_baseline` is for) and gate the multi-level program separately.

---

## 2-R2. THE SEVEN-LEVEL NUMBERS, MEASURED 2026-09-01 -- AND THEY FIT

All seven shippable maps emitted through the real emitter at `PID_NIBBLES=4`
(`scratchpad/m4_bands.py --pid-nibbles 4`), so this is R2's input, not a projection:

    map      nvz   pids   keys     lists      uniq
    E1M1      48    222    444     43392      8957
    E1M2      55    376    752     83488     17092
    E1M3      62    337    674     84344      9363
    E1M4      53    276    552     59280      7191
    E1M5      31    147    294     18996      3630
    E1M8      32     90    180     12288      4889
    E1M9      60    340    680     82368     13070

    sum of per-map list counts    384,156   (8.85x E1M1)
    sum of per-map unique bodies   64,192
    UNION unique bodies            40,902   cross-map dedup saves 36.3%
    BODY growth vs E1M1              4.57x
    band index                     4 -> 5 nibbles (pad 524,288, switch table 8x)
    naive global grid            2,438,832 lists = 6.3x WORSE than per-map bases
    pid global space                 1,788   fits 4 nibbles comfortably

### They fit the budget, and here is the argument

The x4 budget is 357,978,424 words (4x the OLD span, the owner's ruling). The one-level span is
now **74,091,162** after the Phase A clamp-tail win, so the budget is **4.83x** the current
program. The dominant per-map term -- the band bodies -- grows **4.57x**, and the shared parts
(trig/reciprocal tables, the sprite bank, the colormap) do not grow at all. Total growth is
therefore strictly BELOW 4.57x, which is below 4.83x. **Seven levels fit, with margin.**

⚠ That is a bound, not a span measurement. `walk` and `segconsts` grow with SEGS (9.28x over these
seven) but they are only ~5.9% of the emitted text; the sprite bank grows 1.55x with thing TYPES.
A text-weighted estimate lands near 3.9x. **The real number needs R4's build ladder** -- do not
quote 3.9 or 4.57 as a span.

### Two corrections to what this handoff said before

1. **The cross-map dedup DOES scale, and section 8's instinct was right.** An earlier measurement
   over the three small maps that could emit put it at 12.5% and I concluded "the layout is the
   lever, the dedup is not". Over the real seven it is **36.3%** -- it absorbs half the list
   growth (8.85x of lists becomes 4.57x of bodies). The conclusion was drawn from the only three
   maps the pid cap allowed, and they were the SMALL ones.
2. **The layout is worth even more than measured before**: 6.3x here against 2.7x at three maps.
   Per-map id bases versus a naive `vz_classes x keys` global grid remains the most valuable
   structural decision in the milestone.

### The band index at 5 nibbles is DONE and it is FREE -- measured 2026-09-01

`Config.BAND_NIBBLES` (default 4). The seven-level set needs 5. **The switch table does NOT grow
with the width** -- `generate_bands_walk_fj` derives its `pad` from the LIST COUNT -- so raising
it alone costs one extra `hex.xor` per band lookup and nothing else. That is what made it
measurable on E1M1, which needs only 4:

    deg_gate @ 4   43,192,505 / 34,296,270 / 39,327,546 / 32,861,669   (identical to shipped)
    deg_gate @ 5   43,086,924 / 34,381,630 / 38,923,162 / 32,872,532   BYTE-EXACT x4

    ca2_sweep, matched pair, 260 frames:
      median  24,306,866 -> 24,251,849   -0.23%
      mean    24,408,647 -> 24,351,715   -0.23%
      PICTURE 260 of 260 byte-exact ok    VACUITY 254 distinct ok    PASS

**It costs nothing.** The median moves -0.23%, i.e. slightly NEGATIVE -- one extra op per lookup is
swamped by address placement, the same effect the M13-hotdata note records (78.54M -> 76.39M with
the frame byte-identical). Do not read the minus sign as a saving; read it as zero.

⚠ It also breaks a vacuity assumption I wrote down: "identical ops would mean the width never took
effect". A DECREASE is equally consistent with it taking effect. For a change this small the ops
are placement noise and **byte-exactness is the only signal**; the four viewpoints even disagreed
in sign (-0.24%, +0.25%, -1.03%, +0.03%).

### THE BUDGET, COMPLETE

    pid width   2 -> 4 nibbles     +6.74%   (median, 260 frames)
    band index  4 -> 5 nibbles     -0.23%   (median, 260 frames)
    ------------------------------------------------------------
    total                          ~+6.5%   against the owner's +10% ceiling

**Seven levels fit BOTH budgets**: size by the 4.57x body growth against 4.83x of headroom, and
ops by ~6.5% against +10%. PJ-5/PJ-7 stay in reserve and are no longer needed to make the
arithmetic work.

---

## 2-OWNER. THREE DECISIONS, 2026-08-31, AFTER Phase A's measurements

These are the owner's, taken with the Phase A numbers in front of them. They supersede the
open questions section 2a raised.

| | decision |
|---|---|
| **the x4 budget** | **4x the OLD span: 357,978,424 words.** The one-level span is now 74,091,162, so that ceiling is 4.83x it -- the Phase A clamp-tail win is HEADROOM, not a smaller budget. |
| **E1M6 / E1M7** | Include them only if a SIMPLE fix makes **only those two** more time-expensive. Otherwise **start without them** and decide at the end. |
| **the level menu** | a **3x3 GRID, laid out like phone digits** -- 1-9, top-left to bottom-right. That answers GAP 6: `mode` is a 1-bit toggle and the level select needs an N-way choice, so the grid IS the UI. |

### What the E1M6/E1M7 test came back with

**One of the three caps was free to fix and it unblocked E1M6's seg cap entirely.**
`_assert_pnear_unbound` proved the attribution budget never binds using `len(cmap.segs)` -- but
`seg_pass1_ts_leaf` is called ONLY from `ss<c>_seg<s>_mark` blocks, which are emitted only for
MARKING two-sided segs. One-sided segs never reach it. Measured over every door state of every map
(`wall_renderer.marking_seg_count`, now a module-level SSOT so the predicate has ONE definition):

    map    segs  MARKING          map    segs  MARKING
    E1M1   2057     1445          E1M6   4409     2550   <- was rejected, fits with 1,545 spare
    E1M2   3650     2242          E1M7   6947     4183   <- still over 4,095, by 88
    E1M3   2981     1300          E1M8   1796     1284
    E1M4   3502     2036          E1M9   3164     2051
    E1M5   1933     1251

The old bound was over-conservative by 2-3x and **cost a level for nothing**. Tightening it moves
NOT ONE BYTE of the emitted program (`_assert_pnear_unbound` returns `""`), so it is free in every
sense. Pinned by `tests/host/test_marking_seg_bound.py`, whose control requires the OLD bound to
reject E1M6 -- if that ever stops being true the test has stopped proving anything.

**The remaining blocker is SHARED, so the answer to the owner's question is no.** After the fix:

    E1M6   blocked ONLY by runtime things 344 > 254
    E1M7   blocked by things 330, marking segs 4,183 > 4,095, and the stranded thing (2.4)

The thing index is the `0xFF` sentinel of `sshead`/`thnext`, walked by `sim.fj`'s `bind_things` and
`thing_pass` -- **shared code in a shared image**, so widening it to two bytes costs EVERY level a
little (order 1-2% of the median frame, UNMEASURED), not just E1M6 and E1M7. There is no per-map
version of it: the width is a compile-time property of macros every level runs.

**So: SHIP SEVEN.** E1M1-E1M5, E1M8, E1M9 -- which is exactly the set the pid widening alone
unlocks. E1M6 costs one shared widening on top; E1M7 costs that plus a 4-nibble `n_tsv` plus the
2.4 decision. Bring the measured cost of the thing widening to the owner before spending it.

---

## 2a. PHASE A IS DONE (2026-08-31) -- and it changed the plan below

**Read `docs/handoff-m4-phase-a.md` before section 3.** Section 2b (the Phase A brief) is kept
underneath for provenance; this is what it produced.

### The plan's first rung is no longer R0, because R0 cannot run

`scratchpad/m4_caps.py` evaluates every statically-checkable emitter cap against all nine maps.
**Three of four bind**, and the important part is that they bind on SINGLE maps:

    [OVER] segs < DEG_PNEAR       cap  4095  worst 6947  BINDS: E1M6(4409), E1M7(6947)
    [OVER] runtime things < 0xFF  cap   255  worst  344  BINDS: E1M6(344), E1M7(330)
    [ok  ] door states <= 16      cap    16  worst   10

...plus `lines_pid <= 255`, which is NOT statically checkable and so is MEASURED by running the
emitter (`scratchpad/m4_bands.py`): E1M1 222, E1M5 147, E1M8 90 pass; **E1M2 376, E1M3 337,
E1M4 276 and E1M9 340 fail**; E1M6 and E1M7 never reach it because the thing cap stops them first.

**Three maps emit today: E1M1, E1M5, E1M8.** (So the abandoned E1M1+E1M5+E1M8 triple would in fact
have built -- an earlier draft of this section said it would not, from a bad estimate. It is still
a triple with no recorded rationale, but it was not unbuildable.)

**And the order the caps bind in IS the fallback ladder.** Widening the pid ALONE takes the
buildable set from three maps to **seven** (E1M1-E1M5, E1M8, E1M9). Only E1M6 and E1M7 also need
the thing index and the seg counter. The owner's chosen fallback -- drop levels, keep full detail
-- therefore has a first rung that costs exactly one widening.

⚠ **The first version of the caps table was wrong in both directions**, and it is recorded in
`docs/handoff-m4-phase-a.md` because it is this repo's own recurring failure: the thing row counted
DRAWABLES (463 for E1M6) instead of the M14.5 runtime subset the assert counts (344), and claimed
seven of nine maps overflow when two do; and the pid row was labelled a LOWER BOUND when it is not
a bound in either direction. The tool now reproduces the emitter's own 344 exactly, which is the
cross-check that says it is right this time.

### The design that follows, and it is ONE idea repeated

**Every cap becomes a COMPILE-TIME WIDTH derived from the level set.** Not a parameter -- derived,
the same way `flat_max_words` and the restore set already derive. A one-level E1M1 build keeps
today's widths and stays byte-exact; a nine-level build pays for the widths it needs, and the
+10% ops budget is exactly the budget for that.

| cap | today | nine levels | where it costs |
|---|---|---|---|
| `seg_pid` / `pclm[x]` / `pval8` / `skypid` | 2 nibbles, 1 byte per column | 4 nibbles, 2 bytes per column | `hex.read_byte 2` / `write_byte 2` per column per marking seg -- the hot one |
| `n_tsv` vs `DEG_PNEAR` | 3 nibbles, cap 4095 | 4 nibbles | one counter per attributed seg |
| the thing linked lists | 1 byte, 0xFF sentinel | 2 bytes | `sim.fj` `bind_things` / `thing_pass` |

#### The pid width, site by site -- READ OFF THE SOURCE, not guessed

This is the one to do first and it is fully enumerated, so it can be done without re-deriving it.
`pidn` = pid nibbles (2 today, 4 when the level set needs it), `pidb = pidn/2` bytes.

**Emitter (`wall_renderer.py`)**

| where | today | becomes |
|---|---|---|
| the `lines_pid` assert (~:1195) | `assert len(lines_pid) <= 255` | derive `pidn`; assert against 65,535 |
| `skypid` (~:1200) | `index_nibbles=2` | `index_nibbles=pidn` |
| `seg_pid` decl (~:2670) | `hex.vec 2` | `hex.vec {pidn}` |
| `pval8` / `cpid` decls (~:1984, :1995) | `hex.vec 2` | `hex.vec {pidn}` |
| `p2_dpid` decl (~:2092) | `hex.vec 2` | `hex.vec {pidn}` |
| `pclm` in `_hot_arrays` (~:1737) | `VIEW_W` dw-slots | `VIEW_W * pidb` |
| the per-seg baked value (~:1433, :1561) | `("seg_pid", 2, ...)` | width `pidn` |

**fj (`frame_render.fj`)** -- every site, and the pointer arithmetic is the part to be careful with:

    :1153  hex.read_byte pval8, pptr              -> hex.read_byte pidb, pval8, pptr
    :1154  hex.if0 2, pval8, claim                -> hex.if0 pidn, ...
    :1158  hex.write_byte_and_inc pptr, seg_pid   -> hex.write_byte pidb + hex.ptr_add pptr, pidb
    :1192  hex.mov 2, cbufa, pidreg   (lines_pid_ids)      -> pidn
    :1206  hex.mov 2, cbufa, pidreg   (lines_pid_addrs)    -> pidn
    :1548/1570  hex.read_byte pval8, pptr         -> pidb
    :1549/1571  hex.if0 2, pval8, own             -> pidn
    :1552/1574  hex.write_byte pptr, seg_pid      -> hex.write_byte pidb, pptr, seg_pid
    :1553/1575  hex.mov 2, pval8, seg_pid         -> pidn
    :1560/1586  hex.cmp 2, pval8, cpid            -> pidn
    :1562/1588  hex.mov 2, cpid, pval8            -> pidn
    :1594  lines_plane_ptr -- pbase/pptr setup, scale the x1 offset by pidb
    :1639  hex.cmp 2, pval8, dpid   (lines_ditto_plane)    -> pidn
    :1643  hex.mov 2, dpid, pval8   (lines_save_plane)     -> pidn

#### ✅ THE PID WIDTH IS DONE, 2026-09-01. `Config.PID_NIBBLES` WORKS AT 2 AND AT 4.

Everything below this heading is the history of getting here; this is the result. The guard is
gone, and `PID_NIBBLES=4` is a correct program.

    NARROW (2) -- INERT
      deg_gate  43,192,505 / 34,296,270 / 39,327,546 / 32,861,669  BYTE-EXACT x4
                IDENTICAL TO THE DIGIT against the shipped numbers

    WIDE (4) -- EFFECTIVE AND CORRECT
      deg_gate  44,853,168 / 36,124,727 / 40,656,335 / 34,398,141  BYTE-EXACT x4
      ca2_sweep on the matched pair, 260 frames:
                median 24,306,866 -> 25,945,337   +6.74%
                mean   24,408,647 -> 25,885,915   +6.05%
                PICTURE 260 of 260 byte-exact ok    VACUITY 254 distinct ok    PASS

**⚠ THE COST IS TWO-THIRDS OF THE OWNER'S BUDGET.** +6.74% on the governing median against a
stated ceiling of +10%. It buys E1M2/M3/M4/M9 -- **seven levels** -- but it leaves only ~3% for
everything else M4 wants, and R2 may still need a wider BAND index. `PJ-5` and `PJ-7` (section 2a)
are the reserve for winning some of it back; they are loop-invariant work in the shared leaves and
were held for exactly this.

**Bring that trade to the owner before spending more of the budget.** Seven levels at +6.74% is a
different proposition from seven levels at +10%, and the choice is theirs.

---

#### ROOT CAUSE FOUND 2026-09-01: `slot_idx` NAMES TWO DIFFERENT ARRAYS

The bisect below localised the fault to the stride. The cause is one line, and it was mine:

    frame_render.fj  968   hex.shl_hex w/4, 1, tsf_slot_idx   -> sfslot   CONVERT
                    1345   hex.shl_hex w/4, 1, slot_idx       -> sfslot   CONVERT
                    1442   hex.shl_hex w/4, 1, slot_idx       -> sfslot   CONVERT
                    1515   hex.shl_hex w/4, 1, slot_idx       -> spslot   ⚠ DO NOT ⚠

**`sfslot` and `spslot` are different arrays with different strides** -- `STEP_SLOT_STRIDE` and
`SPR_SLOT_STRIDE`, both 16 today, which is why nothing complained. Their index registers are both
macro-locals called `slot_idx`, so a `str.replace` of the shift line hit all three and scaled the
SPRITE index by 256 into an array still sized for 16.

**The evidence was in the failure all along and I misread it.** Viewpoint (664,291) is deg_gate's
SPRITE-OVERLAP frame and it took by far the worst damage -- 2074 px with the full change, 2042 px
with the stride alone -- while the stairs frame, which is what actually exercises the V5 piece
slots, lost only 97 and 85. I spent three cycles rewriting the piece layout because I assumed the
pid work had broken the pid path; the frame that hurt most was telling me it was the sprites.

**The rule that comes out of it:** when a stride becomes derived, convert the shift sites BY LINE
after checking which ARRAY each one indexes -- never by matching the index register's name. The
names are macro-locals and they collide across unrelated readers. Line 1515 now carries a comment
saying so.

---

#### ⚠⚠⚠⚠ BISECTED 2026-09-01: IT IS THE STRIDE, NOT THE PIECE LAYOUT.

**Start here. The piece-layout rewrite described below was chasing the wrong thing.**

One run settled it. `SLOT_SHIFT` forced to 2 (stride 16 -> 256) with **the pid still NARROW and the
piece layout completely untouched** -- the only change in the tree -- and the picture breaks:

    (664,291)     41,983,391 ops   !! 2042 px DIFFER      (2074 with the full V5 change)
    (1272,-724)   34,294,708 ops   !!   85 px DIFFER      (97   with the full V5 change)

Nearly the same damage as the full change, from the stride ALONE. So `ts_piece_wr`, the readers,
`PIECE_BYTES`, the slotoffs and the widened `*bp` registers are all INNOCENT, and the search space
is one line of arithmetic instead of twenty sites.

`banks` grew by exactly 38,400 lines = `VIEW_W * (256-16)`, so the stride change did what it was
meant to and nothing else -- the emission is confined to `sfslot`.

**What was CHECKED and is not the cause:**

* `shl_hex n, times, dst` shifts by `times` NIBBLES (stdlib `shifts.fj:34`, `dst[:n] <<= 4*times`),
  so SLOT_SHIFT=2 really is x256, and `@Assumes times <= n` holds at n=w/4=8.
* `tsf_slot_idx` and `slot_idx` are both `hex.vec w/4` -- x*256 = 40,704 = 0x9F00 cannot overflow.
* `ptr_index` and `ptr_add` both advance in dw-slots, and `sfslot` is sized `VIEW_W * stride`.
* the within-column group layout is UNCHANGED in this experiment (0 and 8, 4-byte pieces).
* the only two live uses of `STEP_SLOT_STRIDE` in the emitter were both updated.

**So something still assumes 16 that reading did not find.** Candidates for the next session, and
note the third reader that the V5 work never touched:

1. `frame_render.fj:1318-1398` is a THIRD sfslot reader (the non-stacked V3 path). It hardcodes
   `hex.ptr_add sfslot_p, 5` after three reads and `hex.ptr_add sfslot_p, 8` -- group offsets, so
   they survive a stride change in principle. Verify that in practice.
2. Anything that reaches `sfslot` by ADDRESS ARITHMETIC rather than through `sfslot_p` -- a baked
   constant or a neighbouring hot array whose position the emitter computes.
3. Whether the hot-data region has a size or ordering assumption that 38,400 extra slots breaks
   (`;__hot_end`, the jump guard).

**And question the premise.** The stride only has to grow because a 5-byte piece x4 needs 20 bytes.
A pid high-nibble stored in a SEPARATE per-column array would keep the stride at 16 and sidestep
this entirely -- uglier, but it does not depend on finding this bug.

---

#### ⚠⚠⚠ THE V5 HALF WAS ATTEMPTED 2026-09-01 AND FAILED. READ THIS FIRST.

The slot-layout change below was implemented in full and REVERTED. It is not a matter of missing
sites -- every one named in this section was done -- so do not simply redo it and expect a
different answer.

**What was built:** `Config.PIECE_BYTES` (3 + PID_NIBBLES/2) and `Config.SLOT_SHIFT`
(log16 of the stride), both riding into `fj_consts.fj`; `ts_piece_wr` writing PIECE_BYTES per
piece with a 2-byte bpid; the face-load block reading the same layout back; the `up_one`/`up_none`
skips in pieces; the lower-group `slotoff` as `2*PIECE_BYTES`; `seg_bpid`, `u1bp`/`u2bp`/`l1bp`/
`l2bp` and the four `p2_d*bp` copies all at PID_NIBBLES; the four `hex.shl_hex w/4, 1` sites at
SLOT_SHIFT; the stride 16 -> 256 and `sfslot` sized to match.

**Narrow stayed perfect throughout** -- `deg_gate` at width 2 gave 43,192,505 / 34,296,270 /
39,327,546 / 32,861,669, identical to the digit, on a clean build. So the parameterisation is
inert, which is not the problem.

**Wide got WORSE, not better:**

    before the V5 work   all 4 deg_gate viewpoints BYTE-EXACT; 3 of 260 sweep frames wrong
    after  the V5 work   all 4 WRONG: 2074 / 97 / 2301 / 41 px

⚠ **AND THE SAME FOUR NUMBERS CAME BACK AFTER FIXING A REAL BUG**, which is the most useful clue
in this section. `lines_pclm_index2` was doing `hex.mov w/4, tmp, idx` -- reading eight nibbles of
a two-nibble column index, the same over-read class as the u1bp one. Fixing it moved the op counts
slightly and left the pixel diffs IDENTICAL (2074/97/2301/41). So that over-read was real but is
NOT the cause, and the cause is something the V5 change introduced that is still unidentified.

**Where to look next, in order of suspicion:**

1. **The stride 16 -> 256.** It is the only structural change that touches columns with no stacked
   pieces at all, and viewpoint 1 (sprite overlap, 2074 px) is exactly such a frame. Everything
   that indexes `sfslot` must agree: the setup shift, `ptr_add tsf_sfslot_p, slotstride` per
   column, and the array's own size. `tsf_slot_idx` was CHECKED and is `hex.vec w/4`, so it is not
   an index overflow.
2. Whether anything else keys off 16 for `sfslot` that greps did not surface (a bare literal, or a
   `rep(.../16)` like `thing_record_body`'s at :716 -- that one takes SPR_SLOT_STRIDE and was
   cleared, but the shape exists in this file).
3. The write/read offset symmetry, re-derived by hand rather than by reading the diff.

**A cheaper way to find it than a 35-minute cycle:** bisect the change. Apply the stride/SLOT_SHIFT
half ALONE at width 2 (it should be inert) and then at width 4 with the pid still narrow -- if
width 4 breaks with only the stride moved, the fault is there and the piece layout is innocent.

`scratchpad/m4_width_lint.py --regs <the pid registers>` is the over-read check that would have
caught both known bugs; `scratchpad/m4_pid_pair.py` builds both halves from one tree and sweeps
them, so the pair can never be mismatched by hand.

---

#### ⚠⚠ STATUS: HALF DONE, AND GUARDED. READ THIS BEFORE TOUCHING THE WIDTH.

`Config.PID_NIBBLES` exists, defaults to 2, and the **pclm half is finished and PROVEN INERT**.
`emit_wall_renderer` ASSERTS `PID_NIBBLES == 2` because **the V5 back-pid half is not done**.

**THE BUG THE SWEEP FOUND, and the lesson is the important part.** At width 4 all FOUR deg_gate
viewpoints were byte-exact -- and `scratchpad/ca2_sweep.py` over 260 frames found three that were
not:

    !! (-435,223,0x0):            2 px DIFFER
    !! (-435,223,0xc0000000):   292 px DIFFER
    !! (-179,1247,0x40000000):  940 px DIFFER

**A PID CHANGE IS PROVED BY THE SWEEP, NOT BY THE GATE.** The failure is intermittent by nature:
a too-narrow source register is read for `PID_NIBBLES` nibbles, and the neighbouring declaration
is usually zero -- so it is right on ~99% of frames. Four viewpoints cannot see that.

**WHAT IS MISSING -- the pid lives in FOUR places, not one.** The audit (every fj op touching a
pid register) is:

    DONE   pclm[] / pval8 / cpid / p2_dpid           frame_render.fj, all PID_NIBBLES
    TODO   seg_bpid                                  the emitter's field (:1474) and decl (:2014)
    TODO   the PIECE SLOT layout                     `ts_piece_wr` writes fy1, fy2, cls, bpid as
                                                     FOUR BYTES, piece 1 at `off+4`, group at
                                                     `off+8`, `ptr_sub off+8`
    TODO   the read side                             `hex.read_byte_and_inc u1bp/u2bp/l1bp/l2bp`
                                                     (:1449,1455,1469,1475) + `hex.zero 2`
                                                     (:1420,1424,1429,1433)
    TODO   the ditto copies                          `hex.mov 2, p2_du*bp` (:1983,1987,1992,1996)
                                                     and `hex.cmp 2, u*bp, p2_du*bp` (rep-guarded,
                                                     :1919,1927,1936,1944)
    TODO   the slotoff call-site constants           `0` and `8` (:1019, :1045)

The layout becomes **PB = 3 + PID_NIBBLES/2 bytes per piece** (4 today, 5 at width 4), group
`2*PB`, slotoff `0` and `2*PB`.

⚠ **CORRECTION -- `STEP_SLOT_STRIDE` DOES NOT HAVE ROOM.** An earlier draft of this section said
"16 with 6 used", quoting the constant's own comment. That comment is from V3, when a slot held
`[uy1][uy2][ucls][ly1][ly2][lcls]`. V5 added a second piece per group AND the bpid byte, so it is
now 2 groups x 2 pieces x 4 bytes = **16 of 16, completely full**.

The stride must stay a POWER OF 16, because the per-column offset is `hex.shl_hex w/4, 1,
slot_idx` (one nibble = x16) and the alternative is a `mul_const` the comment prices at ~72@. So
width 4 wants **stride 256 with `shl_hex 2`** -- the SAME op count, just a different constant --
and `sfslot` grows from `VIEW_W*16` to `VIEW_W*256` = +38,400 words, which is 0.05% of the span.
(Stride 32 would need `shl_hex 1` + `shl_bit`, an extra op per column, to save words that do not
matter. Prefer 256.)

**Writer and reader offsets must match exactly; a mismatch corrupts pieces silently, which is
exactly the 3-in-260 symptom above.**

⚠ Re-run `ca2_sweep` on a matched narrow/wide pair after ANY attempt. `deg_gate` is necessary and
NOT sufficient here, which is now measured rather than asserted.

---

#### ⚠ SOLVED 2026-08-31 -- IT IS `fj_consts.fj`, AND IT COSTS ZERO SIGNATURES

**The section below recommended threading the width as a MACRO ARGUMENT. That is superseded --
do not do it.** It would have touched 13 macro signatures across two files (the transitive chain
is `lines_*` x8 + `seg_pass2_leaf_body_lines` in frame_render.fj, plus `emit_col_lines`,
`emit_region`, `steps_splice_c`, `steps_splice_f` in stream_render.fj) and every one of their call
sites. **None of that is necessary.**

The rejected routes below both put the constant in a LATER file. `fj_consts.fj` is assembled
**FIRST** everywhere -- `paths = [consts] + includes + prog` in `build.py`, and consts-first in
`deg_gate` and every `tests/fj` helper -- so a constant there is a BACKWARD reference. TESTED:
a `rep(PIDN, i)` in a later file assembles fine against `PIDN = 3` in an earlier one.

So `PID_NIBBLES` is a `Config` field (default **2**), it rides into `fj_consts.fj` through
`Config.constants()` for free, and the fj macros read it directly. **`stream_render.fj` is not
touched at all.** What changes is nine macro BODIES in `frame_render.fj` and the emitter's pid
declarations -- and because macro bodies do not live in the emitted parts, the EMITTED TEXT IS
UNCHANGED at width 2.

**THE PAIR OF GATES IS THE PROOF, and neither half can pass by accident.** The narrow run must
be INERT (op counts identical to the digit -- nothing hides there); the wide run must be EFFECTIVE
(same picture, but MORE ops). A wide run that came back op-identical would mean `PID_NIBBLES` never
reached the fj and both gates were grading the same program.

    viewpoint        narrow(2)      wide(4)       delta
    (664,291)       43,192,505   43,220,275     +27,770   +0.064%
    (1272,-724)     34,296,270   35,038,597    +742,327   +2.164%   <- the stairs frame
    (1869,479)      39,327,546   39,436,901    +109,355   +0.278%
    (-416,256)      32,861,669   33,262,386    +400,717   +1.219%
    total          149,678,000  150,958,159  +1,280,159   +0.855%
    both runs BYTE-EXACT x4, PASS. `scratchpad/m4_pid4_gate.py` is the wide half.

**The wide pid is not a flat tax: 0.06% to 2.16%.** It concentrates where V5 stacked pieces
re-derive plane ids per column, which is why the stairs viewpoint is an order of magnitude dearer
than the sprite-overlap one. Four viewpoints are WORST CASES, not the cost model -- the governing
number is `ca2_sweep`'s 260-frame median on the narrow/wide pair.

Emitted parts at width 4 differ from width 2 in exactly one place: `tables` +160 lines, which is
`VIEW_W` extra `pclm` slots (two bytes per column). Everything else identical -- so the width
demonstrably reaches the emitter and changes nothing it should not.

MEASURED at `PID_NIBBLES=2`, which is the whole safety argument:

    deg_gate   43,192,505 / 34,296,270 / 39,327,546 / 32,861,669 ops   BYTE-EXACT x4, PASS
               -- IDENTICAL TO THE DIGIT against the shipped numbers
    parts      entry 32, tables 333,476, main 64, segconsts 44,419, walk 73,941, state 424,
               banks 3,247,543 -- identical to the previous run
    tests/host 485 passed

⚠ The widening is `rep`-GUARDED and must stay so. `hex.read_byte 1, dst, ptr` is NOT
`hex.read_byte dst, ptr` -- the n-form is `rep(n,i) read_byte_and_inc` plus a `ptr_sub`, so
switching outright would cost the shipped build a `ptr_inc`/`ptr_sub` pair per column AND destroy
the op-identical proof above:

    rep(2-PID_NIBBLES/2, k) hex.read_byte pval8, pptr             // width 2: the original
    rep(PID_NIBBLES/2-1, k) hex.read_byte PID_NIBBLES/2, pval8, pptr   // width 4: the n-form

⚠ AND THE FAN-OUT BIT ANYWAY, in a way rule 5 predicts. Making `HOISTED_SCRATCH_DECLS` a function
(`p2_dpid` needs the width, and a module-level list has no `cfg` in scope -- an f-string there is a
NameError at IMPORT) broke two importers of the UPPERCASE constant. Grepping the lowercase helper
names was not enough; `tests/host/test_restore_set_shipped.py` and `scratchpad/m1_add_globals.py`
import `HOISTED_SCRATCH_DECLS` directly. The host suite caught it.

---

#### HOW the width reaches the fj -- two routes TESTED and REJECTED, 2026-08-31

Do not spend the time again. The obvious idea is a single global constant so no signature changes:

1. **A constant defined in a LATER file** (e.g. the emitter writing `PID_NIBBLES = 2` into the
   `entry` part). REJECTED by the assembler at MACRO-DEFINITION time, not at expansion:
   `In macro useit: Used a not global/parameter/declared-extern label: PIDN.`
2. **The same, with the macro declaring `< PIDN`** -- the error message above names
   "declared-extern" as acceptable, so this looks like the fix. It is not:
   `Can't evaluate how many times to repeat in 'rep ...'`. An extern satisfies the LABEL checker,
   but a `rep` count must be known at PREPROCESSING and an extern label is not a value.

That leaves two workable routes, and the second is better:

* `fj_consts.fj` (assembled FIRST, so a backward reference) -- but it is written by
  `Config.emit_fj_consts`, which does not know the map, so the width would have to be plumbed out
  of the emitter and every gate that writes its own consts becomes a fan-out site.
* **A MACRO ARGUMENT from the emitted call site -- which is how every other compile-time knob in
  this emitter already flows** (`{atan_dbl}, {slope_dbl}, {table_dbl}, {stack_flag}` ... on
  `seg_pass2_leaf_body_lines`). No new mechanism, and the fan-out is just the two leaf-body macros,
  their emitted call sites and the ablate stubs. **Take this one.**

⚠ And the widening itself must be `rep`-GUARDED, not switched wholesale: `hex.read_byte 1, dst,
ptr` is NOT `hex.read_byte dst, ptr` -- the n-form is `rep(n,i) read_byte_and_inc` plus a
`ptr_sub`, so it costs the shipped build a `ptr_inc`/`ptr_sub` pair per column for nothing AND
destroys the sharpest test available (op counts identical to the digit at `pidn=2`). Use the
repo's own idiom:

    rep(2-pidb, k) hex.read_byte pval8, pptr          // pidb==1: the original, byte-identical
    rep(pidb-1, k) hex.read_byte pidb, pval8, pptr    // pidb==2: the n-form

**The property that makes this safe to land, stated honestly:** at `pidn=2` the ASSEMBLED PROGRAM
must be identical -- same ops, same span, same pixels -- because every changed number expands to
the value it already had. The emitted TEXT is not identical: a compile-time argument added to a
macro shows up in that macro's call site inside the emitted parts, so `emit_baseline --check` will
report the `main` part CHANGED and it is right to. **Do not read that as the proof; the proof is
`deg_gate` byte-exact with OP COUNTS IDENTICAL TO THE DIGIT**, which is the one thing an
expands-to-the-same-value change cannot fake. Re-freeze the baseline afterwards with that run as
its evidence. A width that is DERIVED rather than passed also means no seventh parameter -- the
owner's six stand.

⚠⚠ **THE FAN-OUT IS BIGGER THAN THE LIST ABOVE, AND THE LIST ABOVE IS THIS DOCUMENT'S OWN** --
found 2026-08-31 by starting the edit and grepping for callers left without the new argument.
The site list is `frame_render.fj` only. It is not enough:

    src/fj/stream_render.fj:650,673   frame.lines_pid_ids u1bp/u2bp, ...   (steps_splice_c)
    src/fj/stream_render.fj:721,740   frame.lines_pid_ids l1bp/l2bp, ...   (steps_splice_f)

Those are the V5 stacked-piece splices, and `pidn` has to be threaded through their whole chain:
`steps_splice_c`/`steps_splice_f` (2 call sites each) <- `emit_region` (**6+ call sites, 32
arguments each**) <- its own callers. Call it ~10 signatures and ~15 long call sites in a SECOND
file -- and `u1bp`/`u2bp`/`l1bp`/`l2bp` are emitter-declared `hex.vec 2` registers that must widen
with it.

**That path has no kernel test** (`PJ-3`), so the only thing that would catch an error is
`deg_gate`'s third viewpoint at ~25 minutes a cycle. **Budget for that before starting, and do the
grep for `.lines_pid_ids`/`.lines_col_plane`/`.lines_plane_ptr`/`.lines_plane_step`/
`.lines_ditto_plane`/`.lines_save_plane` across ALL of `src/fj` FIRST.** An attempt on 2026-08-31
got through `frame_render.fj` cleanly and was reverted on discovering this, rather than leave a
half-threaded frozen-ABI edit across two files.

What that attempt DID establish, and it still holds: no test and no live scratchpad caller
instantiates any of the six `frame_render` macros (only two stale patch scripts that already do
not apply), so the blast radius is entirely inside `src/fj` and the emitted parts.

`hex.read_byte n, dst, ptr` and `hex.write_byte n, ptr, src` already exist in the stdlib, so the
widening is a width argument, not new machinery. **The fj ABI is frozen against RENAMES, not
against a deliberate new parameter** -- but it is a fan-out edit (CLAUDE.md rule 5): `src/`,
`scratchpad/` and `tests/`.

### And Phase A found the milestone's biggest size lever

`vpb_*` is ~78% of the whole emitted program, and inside it the inlined `_raw_byte_out` clamp arms
are 58.3 MB. They are byte-identical to each other. Sharing them per COLOUR is **MEASURED by a full
`game`-tier build** at:

    span_words   89,494,606 -> 74,091,162   -17.21%
    .fjm bytes   32,879,690 -> 26,669,803   -18.9%
    build wall   3,389 s    -> 1,514 s      2.24x FASTER
    median ops   24,282,566 -> 24,306,866   +0.10%, and 260/260 sweep frames byte-exact

It is pixel-neutral by construction and it shrinks the ONE-map program, so **every rung below
starts with 17% more span headroom and a build that is twice as fast** -- and the assembler being
MEMORY-bound is the thing most likely to make nine levels impossible on this box.

⚠ It moves the `banks` part on purpose, so `emit_baseline` must be RE-FROZEN with these gates as
the evidence. Until that is done the M4 emission net is not armed.

⚠ `scratchpad/m4_rawbyte_cost.py` predicted 12.74% from N copies in a small assembled program; the
real build gives 17.21% (379.7 words/arm against a predicted 281.1). **That method reads LOW** --
treat its output as a floor and never as a quotable figure.

---

## 2b. PHASE A — the two loose ends, FIRST. No build, and it feeds M4 directly.

The owner asked for these before M4 starts. Both are no-build reading tasks, and both were
triaged on 2026-08-31 so this section names the specific items rather than pointing at 170.

**Read them through one lens: `M4 MULTIPLIES PER-MAP THINGS BY 14.8`.** A finding about work done
per SEG or per SECTOR is worth ~15x more in a nine-level image than it was when it was written —
if the thing it names is BAKED (emitted code), it is a size lever against the 21.7% break-even; if
it is RUNTIME, it is only ever the active level and the multiplier does not apply. **Sorting each
finding into baked-vs-runtime is the whole triage, and it is the first thing to do.**

### A1 — the `stl.fcall` early-out

Status corrected: **the pixel path already has it.** `frame_render.fj`'s `pixel_tramp` says so —
*"a skip falls straight to `end` with NO fcall (so the DDA only advances over the wall's rows)"*.
The branch `m13opt3-early-out` is named for a check that was, in the hot path, already taken.

So the open question is **the other fcall sites**: 8 in `frame_render.fj`, 4 in `stream_render.fj`,
2 in `projection.fj`, 2 in `sim.fj`, 1 in `plane_bands.fj`. For each, ask what `pixel_tramp`
answered yes to: *is there a cheap test that lets the caller skip the call entirely, rather than
calling and returning early?* An fcall is a trampoline plus a return-register write; skipping it
beats returning from it.

⚠ **Treat this as a LEAD, not a known win.** The note predates the retirements and the 15M
campaign, so the code may no longer look as described — and "cheap and unverified" is precisely the
shape of the "26 pids" claim that turned out to be 94. Read first, measure with
`scratchpad/bench.py --ablate`, and only then decide.

### A2 — the cr2 findings, triaged

`scratchpad/cr2/findings/` is **10 files, ~170 numbered findings**, from a READ-ONLY review: no
build, no test, no gate was run, and every number is either read from source or labelled
UNVERIFIED. Round 1 was fixed; the rest were never worked. Do NOT sweep them — pull the ones that
serve M4.

**Correctness, and all three are multi-level risks:**

| finding | why it matters for nine levels |
|---|---|
| `py-infra` **IN-5** — `build_blockmap` is a SAMPLED rasteriser, not an exact one; its soundness rests on a test, not on the argument in its docstring | the sampling was only ever validated against E1M1. Eight other maps with different geometry is exactly how a sampled rasteriser gets caught. **Same shape as `door_states` throwing on five of nine.** |
| `fj-projection` **PJ-3** — the entire SHIPPED lines/stream projection path has no kernel-level unit test | the path every level renders through, unprotected, while M4 changes the tables under it |
| `fj-planes-misc` **PM-12** — nine of `present.fj`'s fourteen command emitters have no byte-level test | the presentation layer is shared by all levels |

**Optimisations — check BAKED vs RUNTIME for each, because that decides whether M4 multiplies it:**

| finding | claim |
|---|---|
| `py-reference_model` **RM-4** — level-invariant thing data is recomputed on every rendered frame | the name says "level-invariant"; in a nine-level image that phrase means something new |
| `fj-projection` **PJ-7** — `wedge_qt`'s `q` dispatch tree is loop-invariant: 4 identical per-frame decisions re-taken PER SEG | per-seg. 2,057 segs on E1M1, **30,439 across nine**. If the tree is baked, this is a 14.8x size lever |
| `fj-projection` **PJ-5** — `scale_from_global_angle`'s `anglea` is identically `ANG90 + xtoviewangle[x]`: the viewangle cancels, so the whole term is a per-COLUMN constant | pure hot-path ops |
| `fj-sim` **SI-6** — six loop-invariant `hex.set w/4, <ptr>, <label>`s that a data initializer deletes outright | size, shared |
| `fj-planes-misc` **PM-7 / PM-8** — a per-row loop re-tests a call-invariant branch; the per-row cost is 3 `read_byte_and_inc` (~4k ops/row) and the alternative was deleted, not measured away | per-row, hot path |

**Also worth one pass:** `IN-1` says DESIGN.md's span ledger was stale by 3-5x. It has since gained
the M2 row, and **M4 must add a nine-level row anyway (R4 of the CR rules)** — so fix the ledger in
that same pass rather than as separate work.

### What Phase A must produce

1. **A baked-vs-runtime verdict for every optimisation finding above**, because that is what says
   whether M4 multiplies it by 14.8 or not at all.
2. **Any per-map assumption found by reading** — the `door_states` and `sky` class. Cheaper here
   than in a failed assembly, and section 7 GAP 2 says there will be more.
3. **A short list of what to actually take**, with each one's cost measured, not asserted.

⚠ Nothing in Phase A may move the shipped picture. `emit_baseline --check` stays 21/21 SAME, and
an ops change must be measured on a MATCHED pair from the same commit (`scratchpad/m2_ops.py`) —
never against a stale cache binary. That mistake is on the record in PR #79.

---

## 3. THE PLAN — start here

**Why two emissions cannot simply be concatenated:** each one contains the SHARED tables —
`palette`, the trig/reciprocal LUTs, the colormap, the texture and flat tables, the sprite bank,
the `vpb_walk` machinery. Two copies is a duplicate-label error that no prefix can fix, and two
would not fit anyway: they are the bulk of the 89.5M words.

### Already banked (measured in earlier sessions, committed)

| | |
|---|---|
| the 65,536 band-index cap | **CLEARED** — a real 70,000-half-list walk at 5 nibbles assembles and dispatches (`scratchpad/m2_widen.py`) |
| the label collision surface | **16,412 labels in 17 families** (`scratchpad/m4_labels.py`) |
| the namespacer | `doomfj.mapprefix` — opt-in by construction (empty prefix = identity), 51,787 tokens on the real emission, 20 tests |
| the level-select mechanism | M3's persisted `mode` cell is the same machinery |

### R0 — the shared/per-map boundary. NO BUILD. DO THIS FIRST.

⚠ **Section 7 rewrote this rung. Run `python scratchpad/m4_survey.py` first (ten seconds), then
read section 7 before doing anything else — it already answers half of what R0 was going to ask,
and it moved the milestone's gate to a single number: the map-specific fraction `P`, break-even
21.7%.**

Emit several DIFFERENT maps and diff the seven parts. That turns "which blocks are map-derived"
from a reading of the emitter into a list from the emitter's own output.

**Scope it wider than the old plan did**, because the level choice is now a measurement: emit
E1M1..E1M9 (geometry-affecting parts only if that is cheaper) and record PER MAP —

  * `segconsts` and `walk` size (the parts known to be map-specific)
  * the **band-index count** — the binding constraint; the union across maps must fit the widened
    index, and this is the number the +10% ops budget is being spent on
  * the **texture/flat set**, so the UNION and the overlap between candidate maps is known
  * anything in `banks` that is map-derived (it is 89.8% of the text and it is MIXED: bands-as-code
    is per-map, the sprite bank is shared)

Everything below depends on that table. It is ~15 min of emission per map, no assembly. The same
discipline caught "26 pids" (really 94) and "102 labels" (really 16,412).

**Deliverable: a per-map table, and a recommendation of which N levels fit and in what order to
drop them.** Bring it to the owner before R4.

### R1 -- RUN 2026-08-31. The label gate exists, and it FAILS on exactly two names.

`scratchpad/m4_r1_labels.py`. No build, no new emitter mode: a geometry-only emission is a
PROJECTION of the normal one (take the `segconsts` and `walk` parts, drop the rest), so it is the
same text a dedicated tier would emit and it cannot drift from what ships.

    E1M1  geometry defines 25,621 labels   (whole emission 861,969)
    E1M5  geometry defines 20,351          (407,924)
    E1M8  geometry defines 20,042          (499,494)

    CHECK 1  a geometry part defines only names the full emission does .... ok x3
    CHECK 2  two PREFIXED geometry emissions must not collide ............. !! 2 COLLIDE
             E1M1 vs E1M5   ['cs_seeded', 'ptloc_walk']
             E1M1 vs E1M8   ['cs_seeded', 'ptloc_walk']    <- the SAME pair
    CHECK 3  NEGATIVE CONTROL: unprefixed, the same pairs must COLLIDE .... 5,116 / 5,753 ok
    CHECK 4  every free name resolvable from the shared emission or src/fj  0 free names x3

**Two labels block concatenation, and they are the same two for every pair.** Both are FIXED
NAMES attached to PER-MAP code -- which is why `doomfj.mapprefix` deliberately keeps them, and why
nothing before this gate could have noticed:

| label | what it is | the fix, and it is cheap |
|---|---|---|
| `cs_seeded` | the collide-descend's `done_label` (`wall_renderer.py`, the `_bsp_descend_code` call). Its body is literally `stl.fret cs_ret` -- **identical on every map**; the descend's other labels already carry `_pfx(mapname)`, which is why only this one collides | **HOIST IT SHARED.** One copy, every map's descend jumps to it, zero cost. The same argument as the Phase A clamp-tail share: identical bodies do not need N copies |
| `ptloc_walk` | the entry of the baked per-thing point-location walk. `sim.fj:427` declares it EXTERN (`< ... ptloc_walk, ptloc_ret`) and `sim.fj:519` calls `stl.fcall ptloc_walk, ptloc_ret` | **PREFIX IT PER MAP** (`e1m5_ptloc_walk`) and leave a one-op shared `ptloc_walk:` trampoline whose target R3's level switch rewrites. `sim.fj`'s extern keeps resolving; it is called once per DIRTY thing, so a jump is noise. The M12oo wflip-trampoline idiom, already proven in `pixel_tramp` |

⚠ **R1 AND R3 ARE COUPLED, which this plan did not say.** `ptloc_walk` cannot be resolved by
prefixing alone -- something has to point the shared name at the ACTIVE map, and that something is
R3's persisted `level` cell (M3's `mode` machinery). Do R1's prefixing and R3's trampoline in one
go, or R1 cannot be gated green.

The gate is cheap to re-run: label sets are cached per map under `scratchpad/_m4_r1/`, and
`--from-dir MAP=build/generated_...` takes a map's parts from an existing build instead of
re-emitting (~13 min/map otherwise).

⚠ **The checker took four versions to stop passing for the wrong reason**, and every fix was a
scope error rather than a loosened threshold: 237 free names -> 156 -> 136 -> 0. It did not know
about `src/fj`'s registers and macros; it carried `m4_labels.py`'s `(?!hex.vec)` lookahead (a
DECLARATION is a definition); it did not record `def <name>` macro names (the walk emits thousands
of `dsw_seg####_*_go`); and it counted the segments of dotted paths like
`hex.tables.clean_table_entry__table` as free names.

### R1 (original wording) -- a geometry-only emission mode

`emit_wall_renderer(..., shared_tables=False)` — or, preferably, a TIERS row, since that is the
mechanism now: maps 2..N emit their `segconsts` + `walk` and nothing else.

**Gate it WITHOUT a build:** the label sets of a full emission and a geometry-only one must
intersect in exactly the shared names, and two PREFIXED geometry-only emissions must not intersect
at all. `doomfj.mapprefix` already exists for this and is identity on the empty prefix.

### R2 — one bands walk from N maps

`lines_bank_keys` is per-map today; the union is a concatenation with each map's
`seg_cvpidx`/`seg_fvpidx` shifted by its base, at `index_nibbles=5` (or wider — that is what the
ops budget is for). Nine maps is well past the old ~90k half-list estimate for three; **R0 gives
the real number.**

### R3 — the `level` cell and the dispatch

A persisted cell exactly like `mode`, and `main` jumps to the selected map's walk entry. The menu's
entries feed it, which is the whole reason M3 came first. It must survive the M1 reset, so it goes
in `build.STANDALONE_PERSIST` — **and the owner's standing rule applies: a feature is not complete
until the reset loop carries its labels.** `tests/host/test_restore_set_shipped.py` is where that
gets pinned (it already pins `STANDALONE_PERSIST` and `DOOR_PERSIST`).

### R4 — the build ladder. DO NOT SKIP A RUNG.

  1. **ONE map WITH a prefix** — must be byte-exact against the unprefixed build. This is the proof
     `mapprefix` is sound and it is cheap relative to what follows.
  2. **TWO maps** — finds every collision R1's label check missed, at half the build time of three.
  3. **THREE**, then **FOUR**.
  4. **EXTRAPOLATE to nine** — span, .fjm bytes, wall-clock AND peak RSS — and report to the owner
     before attempting the full build. This is the owner's explicit instruction.

Record peak RSS at each rung (`wmic process where "name='python.exe'" get WorkingSetSize`, or the
PowerShell equivalent used throughout this session). The 9.5 GB single-level figure is 57% of the
box; the ladder is what says whether nine is possible here at all.

---

## 4. The tools you have, and what they are good for

| tool | cost | what it proves |
|---|---|---|
| `scratchpad/cr/emit_baseline.py --check` | ~31 min | **the arbiter.** 21 parts across 3 configs, frozen hashes. Single-level emission must stay IDENTICAL through all of M4 — that is the whole safety net for surgery on a 2,957-line emitter where part order IS the contract. |
| `... --check --selftest` | ~21 min | R9: two REAL emitter mutations (`WALL_BG` -> segconsts+tables, `SPR_BLOCK_STRIDE` -> banks), plus a dropped-kwarg control. `entry`/`state`/`walk` are covered by neither, and it says so. |
| `tests/host/test_emitter_call_sites.py` | 0.7 s | every tracked caller passes keywords the emitter has. Resolves splats, aliases, tuple unpacks, parameters. |
| `tests/host/test_oracle_calls_in_step.py` | 0.5 s | every file that EMITS asks the oracle for the same five always-on features. |
| `tests/host/test_no_decimal_wire.py` | 0.6 s | closed-world: a screen's `stdin` must be traceable to `encode_feed*`. 8 exemptions, named, with a rot check. |
| `tests/host/test_build_wall_renderer_setup.py` | 0.5 s | the builder's derivations (limit, generated dir, restore set, sprite wad, tier) WITHOUT the 20-min build. |
| `scratchpad/cr/r1_evidence.py` | ~10 s | 11 mutations of real source, each required to FAIL. **RUN IT ALONE — it refuses otherwise.** |
| `scratchpad/deg_gate.py` | ~20 min | byte-exact x4. The only gate covering the `visual` tier. |
| `scratchpad/m2_std_gate.py` | ~5 min | the shipped standalone binary: 45 frames on keypresses alone, doors opened and walked through. |
| `scratchpad/ca2_sweep.py` | ~5 min | the GOVERNING 260-frame median. The repo's cost model is this, not deg_gate's four worst cases. |

---

## 5. Hazards — every one of these cost real time in the session that wrote this

1. **RUN ONE HEAVY JOB AT A TIME, and `r1_evidence.py` ALONE.** It plants a deliberate bug in
   `wall_renderer.py`/`build.py` for milliseconds at a time. Launching it beside
   `emit_baseline --check` made the arbiter report EMISSION MOVED on two configs and cost an hour
   proving the emitter was fine. It now refuses to start while another python is alive.
2. **A verification tool that cannot fail is the default failure mode here.** Across ten review
   rounds this session, nearly every finding was a broken CHECK, not broken renderer code:
   `deg_gate` unable to run at all; `ca2_sweep`'s byte-exactness control comparing two blank
   `bad:` frames; an R1 harness scoring "no tests ran" as a pass; guards defeated eleven ways.
   **Before quoting a tool, break something and confirm it screams.**
3. **Only fold a condition when the WHOLE of it is constant.** `if steps and (_um or _lm):`
   became unconditional and emitted +27,397 chars. tests/host, pyflakes and the fj lines tests all
   passed; only the emission baseline caught it.
4. **A flag can carry two facts.** `sky` meant "render V2 sky" AND "this wad has no sky lump".
   Folding it to True made a sky-less map emit `skyoff.lookup` against a bank never built — an
   ASSEMBLY error no baseline config could show, since all three are E1M1. **Nine maps will have
   more of these: per-map facts currently hidden behind a shared assumption.** Expect them.
5. **Retiring a FORMAT invalidates everything that FEEDS it, and the symptom looks like a render
   bug.** A decimal feed at a binary-only program halts at `bad:` after ~209 ops and draws a blank
   frame. 24 gates were doing it.
6. **The harness eats backslashes in bash heredocs** and the Write tool was failing all session.
   Author files in chunks under ~100 lines, avoid backslashes (use `chr(92)`/`chr(10)`), and
   re-parse after every edit.
7. **`.gitattributes` pins `eol=lf`** while the working copy is CRLF; `git status` is blind to it.
   A tool that rewrites a file must open with `newline=""` both ways or it dirties the tree.
8. **Same-length edits within the same second leave STALE BYTECODE.** Python invalidates a `.pyc`
   by `(mtime seconds, size)`; a restored mutation kept running the mutated module with a clean
   `git status`. Delete the `__pycache__` entry after restoring.
9. **Never `git add -A scratchpad/`.** It swept 35 artifacts and 36,519 insertions into a commit
   in this session, in the very PR that quoted the rule.

---

## 6. Loose ends carried forward

- **`DESIGN.md` 1.2 has no span row for the 9-level binary** — R4 must add one (R4 of the CR rules).
- The `stl.fcall` early-out check — **now PHASE A1 (section 2b), and its status is corrected
  there: the pixel path already has it.**
- **~170 open findings in 10 files** under `scratchpad/cr2/findings/` — **triaged into PHASE A2
  (section 2b)**; only the ones that serve M4 are named there.
- `self_reset=False` has not been built on the post-hoist tree, so the reset part's own span is
  unmeasured.
- `flipjump-151`'s `origin` remote redirects; the URL is not updated.
- The V-gate oddity: `v5_gate` and `w1r_faces_gate` build a THINGS-LESS program (tier `render`).
  That predates this session and was preserved exactly rather than silently "fixed" — but it means
  those two gates certify less than their names suggest.

---

## 7. GAPS IN THE PLAN ABOVE — found 2026-08-31 by measuring the nine maps, no build

A ten-second survey of `assets/freedoom1.wad` overturned an assumption the whole plan rested on.
**Do this survey again first thing; it is `scratchpad/m4_survey.py` and it costs nothing.**

| map | lines | sides | sectors | segs | ssecs | tex | flats | doors | things |
|---|---|---|---|---|---|---|---|---|---|
| E1M1 | 1175 | 1829 | 182 | 2057 | 682 | 114 | 44 | 13 | 292 |
| E1M2 | 2290 | 3296 | 380 | 3650 | 1104 | 126 | 64 | 8 | 356 |
| E1M3 | 2169 | 2822 | 330 | 2981 | 821 | 100 | 36 | **throws** | 382 |
| E1M4 | 2283 | 3211 | 274 | 3502 | 1202 | 93 | 40 | **throws** | 378 |
| E1M5 | 1215 | 1831 | 214 | 1933 | 501 | 66 | 31 | **throws** | 364 |
| E1M6 | 2818 | 3972 | 395 | 4409 | 1398 | 85 | 51 | **throws** | 490 |
| E1M7 | 4337 | 6253 | 699 | 6947 | 2064 | 106 | 60 | **throws** | 714 |
| E1M8 | 930 | 1446 | 97 | 1796 | 627 | 50 | 34 | **0** | 123 |
| E1M9 | 1935 | 2908 | 297 | 3164 | 913 | 124 | 51 | **throws** | 368 |
| **SUM9** | 19152 | 27568 | 2868 | **30439** | **9312** | union **343** | union **146** | | types **76** |

### ⚠ GAP 1'S MULTIPLIER IS THE WRONG ONE FOR THE DOMINANT TERM -- measured 2026-08-31

GAP 1 below projects the whole span with the SEG ratio (14.8x). That is right for `segconsts` and
`walk`, which really are per-seg and per-node -- but they are only ~5.6 MB of a 95.6 MB emission.
**The dominant term is `vpb_*` (78% of banks), and band half-lists do NOT scale with segs**: the
count is `2 * vz_classes * bank_keys`, and both factors grow far slower than seg count.

Over the three maps that emit, MEASURED:

    band half-lists   43,392 -> 74,676   1.72x E1M1
    segs               2,057 ->  5,786   2.81x E1M1
    the dominant term grows 1.63x SLOWER than segs

Applied to nine levels, GAP 1's 14.8x becomes roughly **9.1x on the band term** -- which is close
to the naive "9x" the handoff spent a section debunking, for a completely different and this time
MEASURED reason. **Every projection below that multiplies the whole span by 14.8 is pessimistic.**

⚠ Three maps is a thin base for a curve and four of the remaining six are the ones the pid cap
blocks, so this is a CORRECTION OF DIRECTION, not a new number to quote. The real figure is R2's:
emit the seven-level set once the pid is widened and count the union. Do not re-derive `P` from
seg ratios again.

### GAP 1 — "nine levels" is not 9x. It is **14.8x**.

E1M1 is nearly the SMALLEST map in the episode. Nine maps are **14.8x its segs** and 13.65x its
subsectors; E1M7 alone is 3.4x E1M1. Everything in the older handoffs that reasons from "9x" — the
per-level increment, the band-index projection, the build-time estimate — is wrong by ~60%.

**The arithmetic that follows, and it is the gate for the whole milestone.** If `P` is the fraction
of the 89,494,606-word span that is MAP-SPECIFIC, nine levels cost `span * ((1-P) + 14.8P)`:

| P | projected span | vs the x4 budget (357,978,424) |
|---|---|---|
| 5% | 151,245,884 | fits |
| 10% | 212,997,162 | fits |
| 15% | 274,748,440 | fits |
| 20% | 336,499,719 | fits |
| **21.7%** | **357,495,153** | **break-even** |
| 25% | 398,250,997 | over by 1.11x |
| 30% | 460,002,275 | over by 1.29x |

**If more than ~22% of the span is map-specific, nine levels do not fit in x4 and the fallback
starts.** Known map-specific TEXT today is only 3.3% (`walk` 2.4% + `segconsts` 0.9%). The decisive
unknown is **how much of `banks` — 89.8% of the emitted text — is bands-as-code (per-map) versus
the sprite/texture/colormap banks (shared).** That single number decides the milestone, and R0
exists to get it. Get it before anything else.

### GAP 2 — `door_states` THROWS on five of the nine maps

    E1M3  door sector 302: state 0 must be shut and the last state fully open, got [84, 88]
    E1M5  door sector 178: ... got [76, 144]
    E1M9  door sector 255: ... got [52, 56]

E1M4, E1M6 and E1M7 too. **The door SSOT assumes every door sector is STORED SHUT — an
E1M1-specific fact.** Other maps ship doors already part-open. E1M8 has ZERO doors, which exercises
the empty-`_dst_tbl` path.

This is hazard 4 (a flag/assumption carrying a per-map fact) arriving before a line of code was
written, and it is exactly the `sky` shape. **Expect more of them**: sky-less maps, thing types
E1M1 lacks, maps with no two-sided doors. Each is an assembly error or an assert, not a wrong
picture — cheap to find, so find them by SURVEY before emitting.

### GAP 3 — the M1 restore set was never considered

The shipped standalone set is **461 entries for ONE level**. With nine levels every level's dirty
cells live in the same image and the reset must cover all of them, or the loop hangs — CLAUDE.md's
"a hole HANGS the next frame". `scratchpad/ca_labels.py` + `m5_setfile.py` must re-key at 9-level
scale, the reset part's own span grows, and the owner's standing rule applies: **not complete until
the reset loop carries the new labels.** `tests/host/test_restore_set_shipped.py` is where it gets
pinned. Budget real time for this; it is not a footnote.

### GAP 4 — no multi-level gate exists or is planned

Every gate is single-map. Nine levels need the `m2_std_gate` treatment: **switch to level N, render
byte-exact against the oracle for THAT map**, for every N, plus a vacuity control proving the
switch actually changed the picture. Without it, "nine levels" is proven by a build that assembles.

### GAP 5 — the emission baseline cannot cover multi-level

All three `emit_baseline` configs are E1M1 on `tests/fixtures/freedoom_e1m1.wad`. Multi-level needs
the FULL wad, whose texture union is 3.0x — so a multi-level emission is not comparable to the
frozen hashes. **Keep single-level emission byte-identical (that is what the baseline is for) and
add a SEPARATE net for the multi-level program.** Do not re-save the baseline to make it pass.

### GAP 6 — the level-select UI — ANSWERED by the owner 2026-08-31: a 3x3 GRID

`DEFAULT_MENU` is a constant list of four strings. A configurable level list needs configurable
menu entries, and M3's `mode` cell is a 1-bit toggle, not an N-way select. R3 must extend it.

**The owner's answer: lay the levels out like PHONE DIGITS -- a 3x3 grid, 1..9, top-left to
bottom-right.** That is a good fit for what this renderer can already do cheaply:

* the menu is a BAKED frame (M3: ~2,344 ops against 28M), so a 3x3 grid of nine cells costs
  essentially nothing to draw -- it is one more baked picture, not a layout engine;
* **the digit IS the index.** A 3x3 grid keyed 1-9 means the level cell can be written straight
  from the keypress with no cursor state at all -- no up/down/left/right walk, no selection
  highlight to persist across the M1 reset. That is strictly less machinery than the four-entry
  list menu M3 already ships;
* it degrades honestly when fewer than nine levels ship (the owner's fallback): cells with no
  level are drawn dead and their digit does nothing. **The binary stays honest about what it
  holds**, which was the owner's stated reason for making the count configurable.

⚠ The level cell must survive the M1 reset (`build.STANDALONE_PERSIST`), exactly as `mode` does,
and the owner's standing rule applies: not complete until the reset loop carries its label.
⚠ **AND THE DIGIT KEYS ARE NOT POLLED -- CHECKED, not assumed.** `src/fj/input.fj`'s `kb.poll`
recognises exactly w/a/s/d, the four arrows, enter, esc and space; its own header says "anything
else is read and DISCARDED". `'1'..'9'` are `0x31..0x39`, so the grid needs a new `0x3_` arm in the
high-nibble dispatch plus a low-nibble 1..9 fan -- contained, but real work in the one macro that
decides what the player can do.

⚠⚠ **AND `kb.poll`'S SIGNATURE IS A KNOWN FAN-OUT TRAP.** Commit `f8a19ca` is titled *"M2-R4 fix:
kb.poll's new `u` parameter had two callers in tests/ that I did not grep for"* -- the exact same
macro, the exact same kind of change, one milestone ago. Adding a `level` output repeats it unless
`src/`, `scratchpad/` AND `tests/` are grepped for `kb.poll` first (CLAUDE.md rule 5).

**The grep, done 2026-08-31 so it cannot be skipped -- THREE call sites, TWO of them in tests:**

    src/doomfj/wall_renderer.py:383   rep({polls}, i) kb.poll kbstat, kbcode, kb_f, kb_b, kb_l,
                                      kb_r, kb_u, mode, bad        <- the emitted program
    tests/fj/test_keyboard_input.py:43   rep(POLLS, i) kb.poll kstat, kcode, ..., kuse, kmode, bad
    tests/fj/test_menu_mode.py:41        rep(4, i) kb.poll kbstat, kbcode, ..., kb_u, mode, bad

(`scratchpad/m2_std_gate.py` mentions `kb.poll` only in a comment about edge-triggering.)

### GAP 7 — R0 as originally scoped costs ~2.25 hours

"Emit each of nine maps, ~15 min each." Replace with: the free survey above, then **two or three
targeted emissions** (E1M1 as the reference, E1M8 as the smallest, E1M7 as the largest) — enough to
fit the per-map growth curve and split `banks`. Nine full emissions buys almost nothing more.

---

## 8. OPTIMIZATIONS — where the size and the time actually are

### MEASURED 2026-08-31 -- the LAYOUT is the lever, the dedup is not

`scratchpad/m4_bands.py` runs the real emitter per map and records every band half-list. Three
maps emit today (E1M1, E1M5, E1M8 -- the rest hit the caps in section 2a), and they settle both
halves of the argument below:

    map    nvz  pids  keys    lists   uniq
    E1M1    48   222   444    43392   8957
    E1M5    31   147   294    18996   3630
    E1M8    32    90   180    12288   4889

    PER-MAP BLOCK LAYOUT (map m based at its own offset)  74,676 lists   15,286 unique bodies
    NAIVE GLOBAL GRID (all vz-classes x all keys)        203,796 lists   = 2.7x MORE
    cross-map dedup of identical bodies                   saves 12.5%

**So the two levers are not the size the older text guessed.**

* **The layout is worth 2.7x and it is the whole game.** `_band_pair_lists` is a CROSS PRODUCT --
  `n = 2 * len(vz_classes) * len(bank_keys)`, class-major -- and both factors are per-map. Crossing
  every map's view-z classes with every map's keys is quadratic in map count; basing each map's ids
  at its own offset is linear. **Nothing else in M4 is worth as much as getting this right.**
* **The dedup is worth 12.5%, not "a large fraction".** The generator ALREADY dedups identical
  lists (`first_of`/`owner`), within a map and across the union alike, so the union costs nothing
  extra to obtain -- but three maps of the same episode share only an eighth of their bodies. The
  text below hoped for much more. It was a guess; this is the measurement.

* **Three maps already need 5 index nibbles** (pad 131,072 > 65,536). Nine will need 5 or 6. The
  +10% ops budget is being spent whatever happens, so PJ-5/PJ-7 (section 2a) are the reserve.

* **The sky lists are 768 on EVERY map and they are the same 768.** They come from
  `_sky_pair_lists`, which reads the SKY1 texture and nothing about the map, so nine levels need
  ONE copy at a single global base -- not nine. Small (768 of ~700k) but it is free, and getting it
  wrong means `sky_base_id` has to become per-map for no reason.

### The original argument, kept because its REASONING still holds

### THE BIG ONE: deduplicate, do not concatenate

The old plan says the multi-map bands walk is *"a concatenation, with each map's
`seg_cvpidx`/`seg_fvpidx` shifted by its base"*. **Concatenation is the naive choice and it is
probably the most expensive mistake available in this milestone.**

`lines_bank_keys` are KEYS — a band half-list is a run of `[y2_cumulative][colour]` pairs derived
from heights, light and flat/texture. Across nine maps of the same episode, sharing a texture set
that overlaps 60%, **a large fraction of band lists will be bit-identical**. Deduplicating the
union instead of concatenating it pays three times over:

1. **Size** — the bands-as-code bank is the suspected bulk of the per-map growth, i.e. the thing
   that decides GAP 1's `P`. Dedup attacks the dominant term directly.
2. **Speed, by not spending the ops budget** — the +10% exists to pay for a wider band index. If
   dedup keeps the union under **65,536**, the index stays at 4 nibbles and the frame cost of
   nine levels is **zero**. Widening is a fallback, not a plan.
3. **Assemble time and RAM** — the assembler is MEMORY-bound (129.4 MB of source became ~13.6 GB
   live before the 2026-08-20 work). Less emitted text is less peak RSS, which is the constraint
   most likely to make nine levels impossible on a 16.8 GB box.

**Measure the dedup rate in R0** — emit the band lists for two maps and count identical ones. It is
a dict lookup, not a build. If the rate is high this milestone gets much easier; if it is near zero,
GAP 1's arithmetic says start the fallback ladder early.

The same argument applies to **`segconsts`**: one `xor_by` block per seg, 30,439 segs across nine
maps. Segs with identical baked constants (same texture, same heights, same light) can share a
block. Measure the duplicate rate the same way.

### WHERE THE NEXT SIZE LEVER IS -- measured on the post-clamp-tail emission

Re-reading `banks` by label family after the Phase A change (`build/generated_doom_e1m1_menu_m4`):

    BEFORE  vpb 86.1% of banks   sprite  9.5%   other 4.4%
    AFTER   vpb 78.1% of banks   sprite 16.9%   other 5.0%
    top families now: lo_b# 27.2%, hi_b# 27.2%, sprbank 16.2%, em 4.1%, ls 4.0%, vpb_t# 4.0%

The `rb_*` families (41% of banks) are GONE. What dominates now is **`lo_b#` + `hi_b#` = 54.4% of
banks, ~43.5 MB**: the two `_cmp3_tree` compare chains every band pair carries -- one against
`vq_lo`, one against `vq_hi`.

**They are NOT shareable the way the clamp tail was**, and the reason is worth writing down so
nobody re-derives it: `_cmp3_tree` is specialised on the CONSTANT `y2`'s bits AND jumps to three
per-pair targets. The clamp tail was shareable precisely because it had no per-pair content at all
(it emits a runtime register) and a single per-colour exit.

⚠ **A LEAD, not a plan.** `y2` is a screen row + 1 and VIEW_H is 100, so there are at most 100
distinct values -- one tree per `y2` could serve every pair IF the three exits were reached
through a return register instead of
baked labels -- i.e. an `stl.fcall` per compare. That is TWO fcalls per pair ON THE HOT PATH, where
the clamp tail was one jump on an arm taken at most once per walk. So it trades ~43 MB against real
ops, in the opposite direction to the change that just landed. The +10% budget has room (the sweep
measured +0.10%), but this needs `ca2_sweep` on a matched pair BEFORE anyone believes it -- and it
is the same shape as the '26 pids' claim: cheap-looking, unmeasured, and about the hot path.

### Size levers, in order of expected value

| lever | expected | why |
|---|---|---|
| **dedup band lists across maps** | large, unmeasured | see above; also keeps the index at 4 nibbles |
| **dedup seg constant blocks** | medium, unmeasured | 30,439 segs, many geometrically identical |
| **texture/flat union** | **already sub-linear** | union 343 vs E1M1's 114 = **3.0x**, not 9x. Overlap saves **60%** against the naive sum. Nothing to do; just do not regress it by baking per-map texture tables. |
| **sprite bank** | **already near-flat** | thing TYPES 49 -> 76 = **1.55x**. The bank scales with types, not maps, and it is the single biggest block. |
| **raise the cap** | free | 2**29 is authorised. A limit is not an allocation; only the real span costs RAM. |

⚠ **The lever NOT to pull: bands-as-code -> bands-as-data for dormant levels.** It looks appealing
(only one level is walked at a time, so eight levels' walk code never executes) and it is wrong:
any level can become the active one, so all nine must be fast. Making levels 2-9 slower is exactly
the fallback the owner rejected — they chose **drop levels, keep full detail**.

### Time levers

**Frame ops.** Level count does not change what the frame walks — only the CURRENT level's BSP is
walked, dormant levels sit inert. The only per-frame cost of more levels is **wider dispatch
tables**: a 5-nibble band index costs one extra dispatch per lookup on the hot path. So the whole
+10% budget is really a budget for table width, and **dedup is how you avoid spending it**.
Measure ops with `scratchpad/m2_ops.py` against a matched pair (same commit, levels on/off) —
never against a stale cache binary; that mistake is on the record in PR #79.

**Assemble time and RAM — the real risk to the milestone.** One level is ~55 min two-pass and
peaks at ~9.5 GB of 16.8 GB. At 14.8x on the map-specific text this is where nine levels most
plausibly become impossible on this machine. The owner's instruction is the mitigation: **build 2,
3 and 4 levels and extrapolate time AND peak RSS before attempting nine.** Record RSS at every
rung. If the curve is superlinear, say so early — the fallback is dropping levels, and finding out
at rung 4 costs hours instead of a night.

Two smaller assemble-time notes: the 2026-08-20 assembler work (`flipjump-151` `06385ad` +
`108e391`) cut the live set 3.1x and is what makes this feasible at all; and CLAUDE.md rule 1's
clause about a finished build holding its memory for MINUTES after printing its last line applies
at every rung — check the PROCESS is gone, not the log.

### What NOT to optimise

- **Do not touch the shipped single-level picture.** `emit_baseline --check` must stay 21/21 SAME
  through every rung. Every optimisation above is about the MULTI-map union; none of them may move
  a byte of the one-map program.
- **Do not spend the ops budget speculatively.** +10% is a ceiling to be paid only when a
  measurement says the index must widen.
