# M4 PHASE A -- findings

**Run 2026-08-31, before any M4 code.** Phase A was defined in
`docs/handoff-m4-nine-levels.md` section 2b: read the two loose ends (the `stl.fcall` early-out and
the cr2 findings) through the lens *"M4 multiplies per-map things by 14.8x"*, and produce three
things -- a baked-vs-runtime verdict per optimisation finding, every per-map assumption reading can
find, and a short list of what to take with each cost **measured**.

Every number below was produced in that session by a command named beside it. Nothing here is
quoted from a doc or from git.

---

## 0. The headline

| | |
|---|---|
| per-map assumptions found | **4**, three of them hard blockers -- and they block SINGLE maps |
| of those, fixed in Phase A | **1** (`door_states`, which used to throw on five of nine maps) |
| optimisation findings that M4 multiplies | **0** of the eight triaged -- every one is RUNTIME |
| the lever Phase A actually found | **share the band-walk clamp tail per colour: 11,401,761 words, 12.74% of the span** |
| the `stl.fcall` early-out lead | **exhausted** -- every site already has it, is loop-bounded, or is per-frame |

The triage's own conclusion is the useful one: **the cr2 optimisation findings are all in shared
leaf code, so M4 does not multiply any of them.** The size that M4 multiplies lives somewhere the
findings never looked -- in `lut_generator`'s baked output, which had no test at all.

---

## 1. Baked vs runtime -- the verdict table

The question that decides whether M4 multiplies a finding by 14.8x is whether the code it names is
**emitted per map** or **emitted once and executed per map**. Settled by counting instantiations in
the shipped emission (`build/generated_menu/`, the 89.5M-word menu build):

    e1m1_02_main.fj        wedge=2       <- ONE shared leaf, not per seg
    e1m1_03_segconsts.fj   xor_by=43310  <- BAKED, per seg
    e1m1_04_walk.fj        xor_by=5823   <- BAKED, per node

| finding | names | verdict | does M4 multiply it? |
|---|---|---|---|
| `PJ-7` wedge_qt's invariant dispatch | `wedge_reject` in `seg_pass1_leaf` | **RUNTIME** -- 2 occurrences in `main`, none per seg | **no** |
| `PJ-5` anglea cancels to a per-column constant | `scale_from_global_angle` in the pass-2 leaf | **RUNTIME** | **no** |
| `SI-6` six loop-invariant `hex.set`s | `sim.fj`, one instantiation | **RUNTIME**, flat size | **no** |
| `PM-7` build_bands re-tests an invariant | `plane_bands.fj` | **DEAD** -- see 2.3 | **no** |
| `PM-8` 3 read_byte_and_inc per row | `plane_bands.fj` | **DEAD** -- see 2.3 | **no** |
| `RM-4` level-invariant thing data per frame | `reference_model.py` | **ORACLE (host)** | not the binary -- but see below |
| `PM-12` nine untested present emitters | `present.fj` | RUNTIME, shared | no |
| `PJ-3` no kernel test for the shipped projection path | `projection.fj` | RUNTIME, shared | no |

**`RM-4` is the one whose value M4 changes anyway**, in the other direction: it is oracle time, and
GAP 4 says nine levels need a per-level byte-exact gate. A gate that renders nine maps pays RM-4's
~251 redundant BSP descents per frame nine times over. Take it when the multi-level gate is built,
not before -- the cost is only visible once something calls it that often.

**PJ-7 and PJ-5 keep their value for a different reason.** The +10% ops budget exists to pay for
wider LUT indices. These two are the obvious places to *earn* that budget back if the index has to
widen. They are not M4 work; they are M4's insurance.

---

## 2. Per-map assumptions -- the `sky` class, found by reading and by measuring

### 2.1 `door_states` threw on five of nine maps -- FIXED

    E1M3 door sector 302: state 0 must be shut and the last state fully open, got [84, 88]

The cause was not the assert. `door_sectors` computes `open_h = min(neighbouring ceiling) - 4`, and
on five maps some sector behind a special linedef has **every** neighbour's ceiling at or below its
own floor -- a "door" that opens *downward through its own floor*. `stops` returns a SORTED set, so
`open_h < floor_h` silently swapped the two ends and `door_states` caught it.

**Fix** (`src/doomfj/doors.py`): such a sector is not a door, exactly as an already-open one is not.
**Byte-exact on the shipped build by construction, and MEASURED**: E1M1 has 13 door sectors, **0**
with `open_h < floor_h` and **0** with `open_h == floor_h`, so nothing this repo has ever built with
leaves the dict. The filter is `<`, strictly, for that reason.

    map    doors  open<lo  kept
    E1M1      13        0    13
    E1M2       8        0     8
    E1M3      18        2    16
    E1M4      16        7     9
    E1M5       7        1     6
    E1M6      11       10     1
    E1M7      21        5    16
    E1M8       0        0     0     <- exercises the empty _dst_tbl path
    E1M9      11        1    10

Pinned by four new tests in `tests/host/test_doors.py`, including a negative control that names the
six maps the filter must fire on. Verified with teeth: reverting the filter fails two of them.

### 2.2 TWO capacity caps BIND on E1 maps -- `scratchpad/m4_caps.py`

New tool. It evaluates every statically-checkable emitter cap against all nine maps, because a cap
that binds is not a wrong picture -- it is a dead build, hours in.

    [OVER] segs < DEG_PNEAR       cap  4095  worst 6947  BINDS: E1M6(4409), E1M7(6947)
    [OVER] runtime things < 0xFF  cap   255  worst  344  BINDS: E1M6(344), E1M7(330)
    [ok  ] door states <= 16      cap    16  worst   10

⚠ **THIS TABLE IS THE SECOND VERSION, AND THE FIRST ONE WAS WRONG IN BOTH DIRECTIONS.** It is worth
recording, because it is this repo's own recurring failure -- a checking tool that overstates.

* The thing row first counted **drawables**. The assert counts `len(_mt_keep)`, the M14.5 RUNTIME
  subset (`thing_rows` drops the rest). Drawables read 463 for E1M6 where the emitter reports
  **344**, and the column claimed **seven of nine** maps overflow when only **two** do. It now
  computes the real subset (one `bake_bsp` + one `point_in_subsector` per thing, about a second a
  map) and reproduces the emitter's 344 exactly -- which is the cross-check that says it is right
  this time.
* The pid row was labelled a **LOWER BOUND**. It is not a bound in either direction: it counts one
  pair per SECTOR, and the emitter both adds (a variant per door state, stacked back sectors) and
  subtracts (only sectors a WALK seg reaches are registered). It reads low on seven maps and HIGH
  on E1M6 (328 against a real count under the cap). It has been demoted to a sighting shot and
  taken out of the pass/fail count entirely.

**The pid cap is not statically checkable at all, so it is MEASURED** by running the emitter
(`scratchpad/m4_bands.py`):

    E1M1  222        E1M2  376 OVER   E1M3  337 OVER   E1M4  276 OVER
    E1M5  147        E1M8   90        E1M9  340 OVER
    E1M6, E1M7  UNMEASURED -- both die on the thing cap at :970, before the pid assert at :1195

* **`segs < DEG_PNEAR`** (`_assert_pnear_unbound`). The deg attribution budget must provably never
  bind, and its counter `n_tsv` is **3 nibbles** -- so the cap cannot simply be raised to 6,947. It
  needs a 4-nibble counter, which is a hot-path cost and therefore a charge against the +10% budget.
* **`runtime things < 0xFF`** (`wall_renderer:470`). 0xFF is the empty/end sentinel of BOTH thing
  linked-list arrays. **E1M6 (344) and E1M7 (330) only.** Needs 2-byte indices through `sim.fj`'s
  `bind_things`/`thing_pass`.
* **`lines_pid <= 255`** (`wall_renderer:1195`). The per-column plane-pair id is ONE BYTE, written
  per column by `hex.write_byte pptr, seg_pid` and dispatched on by `skypid`. **This is the one
  that matters most, and it is NOT a multi-level problem**: E1M2 needs 376 pids as a SINGLE map, so
  four of the seven maps that reach the assert cannot be built today at all. Widening the pid is a
  hot-path cost (a per-column store and a wider dispatch), and it is the largest single piece of
  unplanned M4 work Phase A found. A GLOBAL nine-map pid space lands near 3,500 -- still inside
  4 nibbles -- so the pid does not need per-map rebasing, only one widening.

Caps that need a live emission -- `lines_pid <= 255`, the stepcol/sprite-light class indices, the
sky half slots -- are measured by `scratchpad/m4_bands.py` instead, and `m4_caps.py` says so in its
own output rather than implying it covered them.

**The order the caps bind in is the fallback ladder, and it is a good one.** Widening the pid ALONE
builds E1M1, E1M2, E1M3, E1M4, E1M5, E1M8 and E1M9 -- **seven of nine**. Only E1M6 and E1M7 need
the thing index and the seg counter as well. So "drop levels, keep full detail" has a natural first
rung that costs exactly one widening.

### 2.3 `src/fj/plane_bands.fj` is entirely dead code

Both its macros -- `plane.build_bands` and `plane.recip32` -- have **zero** instantiation sites in
`src/fj`, in the Python emitters, and in the generated program (`grep -c` over all seven parts:
0, 0, 0, 0, 0, 0, 0). Every reference is a comment. The file is 304 lines and is in the shipped
include list.

It costs **zero span** -- a file holding only `def`s emits no ops -- so this is hygiene, not size.
**Do not delete it yet.** Removing a file from the include list renumbers every macro-expansion
label in every file after it, and `sim.fj` and `stream_render.fj` come after it. The M1 restore set
is keyed by 461 **plain global** names (checked: no `f<file>:l<line>` names at all), so the *names*
survive -- but `layout_fingerprint` is a hash over (name, span-to-next-label) and the build asserts
it. **The moment to delete this file is inside GAP 3's restore-set re-key, which M4 has to do
anyway.** Doing it separately buys a second re-key.

This also settles PM-7 and PM-8: they optimise code nothing runs.

---

## 3. A1 -- the `stl.fcall` early-out lead is EXHAUSTED

The handoff already corrected the claim that the pixel path lacked the early-out; it has it. Phase A
read the other seventeen sites. **Every one is already guarded, by one of three mechanisms:**

| site | why there is nothing to take |
|---|---|
| `frame_render.pixel_tramp` | IS the early-out -- a skip falls to `end` with no fcall |
| `frame_render.plane_tramp` | the identical trampoline, the identical skip |
| `stream_render.half_walk` / `half_walk_code` | `hex.cmp qlo, qbound -> end` returns on an empty window before either fcall, then gates asc/desc on CENTERY separately |
| `stream_render` expand_leaf x2 | inside a counted loop; the loop bound IS the test |
| `sim.thing_pass` | guarded by `hex.if0 h, done` and the `tstop` flag |
| `sim` ptloc_walk | only reached on the dirty branch |
| `projection` wsel x2 | twice per FRAME, in `wedge_setup` |
| `plane_bands` recip32_leaf | inside the dead file (2.3) |
| `frame_render` span_leaf x2 | the `spans` tier, not the shipped one, and both are already inside "a span exists" |

**Close the loose end.** The `m13opt3-early-out` branch is named for work that was already done.

---

## 4. What Phase A found instead -- and it is the biggest size lever in the program

Reading `banks` (142.3 MB of the 158.0 MB emission) by label family:

    vpb_*  (bands-as-code)   86.0% of banks   ~78% of the whole emitted program
    sprbank + sprlight        9.5% of banks
    everything else           4.5%

and inside `vpb_*`, the `rb_*` families alone are **58.3 MB -- 41% of banks**. They are
`_raw_byte_out`, inlined into the CLAMP arm of every band pair: 8 bits x 7 lines, **byte-for-byte
identical every single time**, once per pair. `grep -c "_rb_z0:"` says the shipped emission has
**40,567** of them.

Every `vpb_fin` is the same `stl.fret vpb_x`, so a per-COLOUR shared tail can fret directly and the
arm collapses to one jump.

**MEASURED, by assembling both shapes** (`scratchpad/m4_rawbyte_cost.py`, N=200 copies each):

    inlined   283.1 span-words per clamp arm
    shared      2.0 span-words per clamp arm   (+284 words fixed per distinct colour)
    SAVING    281.1 words x 40,567 arms = 11,401,761 words = 12.74% of the 89,494,606-word span

It is pixel-neutral by construction -- the same bytes in the same order -- and it is a **shared**
saving, so it applies to the one-map program and to all nine. Implemented in
`generate_bands_walk_fj`.

**And it had no test.** `generate_bands_walk_fj` emits ~78% of the program's text and the only thing
that ever checked it was a twenty-minute whole-frame gate. `tests/fj/test_bands_walk.py` is new: it
states the walker's contract in twelve lines of Python and drives ten windows through the real
assembled walker, covering the skip / emit / `==` / clamp arms and the shared-body path. Verified
with teeth -- two mutations of the real generator each fail three of the cases.

---

## 5. What to take, in order

1. **DONE -- the door filter** (2.1). Byte-exact on E1M1 by measurement, and it unblocks eight maps.
2. **DONE -- the shared clamp tail** (4). 12.74% of the span, measured, pixel-neutral, now tested.
3. **`lines_pid <= 255`** (2.2). The gating one, and the best value in the milestone: one widening
   takes the buildable set from three maps to seven. Everything else in M4 is downstream of
   deciding how wide a pid is.
4. **`runtime things < 0xFF`** (2.2). E1M6 and E1M7 only -- i.e. this is what levels eight and nine
   cost, and it can be deferred behind a 7-level build.
5. **`segs < DEG_PNEAR`** (2.2). Binds on two of nine. A 4-nibble `n_tsv` is a charge against the
   +10% ops budget -- measure it with `scratchpad/m2_ops.py` on a matched pair.
6. **Delete `plane_bands.fj`** (2.3) -- inside the GAP 3 restore-set re-key, not before.
7. **`RM-4`** -- when the multi-level gate exists, not before.
8. **`PJ-7` / `PJ-5`** -- held in reserve, to pay for the wider indices 3-5 are about to cost.

## 6. What Phase A did NOT do

* It did not touch `PJ-3` or `PM-12` (missing tests for shared runtime code). They are real and they
  are unchanged by M4; they compete with M4's own new gate (GAP 4), which covers more.
* It did not re-run `emit_baseline --check` before the clamp-tail change. That change moves the
  `banks` part **on purpose**, so the baseline has to be re-frozen with the gates as its evidence --
  and until it is, the M4 safety net is not armed.
