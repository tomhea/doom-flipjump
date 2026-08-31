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
    E1M6, E1M7  UNMEASURED -- both die earlier, see 2.4

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
builds E1M1, E1M2, E1M3, E1M4, E1M5, E1M8 and E1M9 -- **seven of nine**. E1M6 needs the thing index
and the seg counter as well; E1M7 needs those plus the uninhabitable-sector question in 2.4. So
"drop levels, keep full detail" has a natural first rung that costs exactly one widening, and the
last two levels are each individually expensive.

### 2.4 E1M7 has a THIRD blocker, and the door fix in 2.1 is what exposed it

    E1M7 !! thing_live_subsectors says subsectors [445] are uninhabitable, yet E1M7 spawns
            drawable things in them: [(2047, 1528, 2112)]

That is the emitter's deliberate loud failure (handoff-m14: "a silent vanish is unacceptable, a
hard failure is fine"), and it is **directly caused by 2.1**. Traced: subsector 445 is sector 274,
floor 128 / ceiling 128, behind a special linedef, `min(neighbouring ceiling) - 4 = 124` -- i.e. it
is EXACTLY the sector E1M7's original `door_states` error named ("door sector 274: ... got
[124, 128]"). The filter drops it, so it is no longer a door, so it stays stored-shut, so
`thing_live_subsectors` calls its subsector uninhabitable -- and a thing spawns in it.

**So 2.1 did not make all nine maps emit; it moved E1M7's failure from one assert to another.** Both
are hard failures and E1M7 was unbuildable either way, but `m4_survey.py` now shows E1M7 with 16
doors and no throw, which makes it LOOK fixed. It is not. Stated here so nobody reads that table as
a green light.

The underlying question is a modelling one and it is not Phase A's to settle: DOOM routinely spawns
items behind closed doors, and `thing_live_subsectors` is right to call `ceil <= floor`
uninhabitable *unless the door can open*. For a door whose open height is below its own floor,
nothing can open it, and the item is genuinely unreachable but still in the map. Whatever is
decided has to be decided in BOTH mirrors. E1M7 is the last map to become buildable anyway (it also
needs the thing cap and the seg cap), so this sits behind those.

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

### The gate, and the op counts it moved

`deg_gate` on the changed tree, against the 2026-08-29 run of the same gate (all six other parts
identical to the digit, so the only difference between the two programs is this change):

    part sizes   banks 5,373,317 -> 3,247,543 lines   -39.6% on banks, -36.5% on the emission
    .fjm bytes   15,390,938 -> 11,811,428             -23.3%

    viewpoint            before        after       delta
    (664,291)        43,199,791   43,192,505      -7,286   BYTE-EXACT
    (1272,-724)      34,296,380   34,296,270        -110   BYTE-EXACT
    (1869,479)       39,341,354   39,327,546     -13,808   BYTE-EXACT
    (-416,256)       32,812,917   32,861,669     +48,752   BYTE-EXACT
    PASS

**The op counts moved, and CLAUDE.md says that has to be investigated rather than waved through.**
The prediction was exactly zero: the arm gains one jump (`;vpb_cl_c`) and loses one (`;vpb_fin{k}`,
because the shared tail frets directly).

**The SIGNS are the discriminator.** A control-flow change costs `k` ops per EXECUTED clamp arm, so
its delta would carry the same sign at every viewpoint and scale with how many arms that viewpoint
runs. Three fell and one rose. That rules out a per-arm cost. What remains is address placement:
dispatch and `wflip` cost in this program scales with the SET BITS of the target address, and
deleting 2.1M lines moves every later label. There is in-repo precedent with exactly this
signature -- the M13-hotdata note in `wall_renderer.py` records moving data changing 78.54M ->
76.39M ops/frame with the frame byte-identical.

Spread is -0.035% to +0.149%, against a +10% budget. Four viewpoints are worst cases, not the cost
model, so the claim rests on the governing 260-frame sweep instead -- run on the SAME matched pair
of binaries (`scratchpad/ca2_sweep.py --a <pre> --b <post>`, both sha256'd in its log):

                    median          mean           min           max
    A base      24,282,566    24,404,895     6,219,980    47,935,811
    B new       24,306,866    24,408,647     6,219,980    47,937,393
    delta           24,300         3,751             0         1,582
    pct              0.10%         0.02%

    PICTURE CONTROL : 260 of 260 frames byte-exact       ok
    VACUITY CONTROL : 254 distinct pictures across 260   ok
    ca2_sweep: PASS

**260 of 260 frames byte-exact** -- a strictly stronger picture proof than the gate -- and the
governing median moves **+0.10%**. Note the MIN delta is exactly 0: the cheapest frames are
unchanged, which is what address placement predicts and what a per-arm control-flow cost could not
produce. Its two controls were checked before the numbers were quoted (hazard 2: this tool once
"proved" byte-exactness by comparing two blank `bad:` frames) -- it counts a mismatch on every one
of the 260 and requires >65 distinct pictures.

### The emission-identity proof, done against the SHIPPED artifact

Better than `emit_baseline` for this one change, because it compares the new emission part-by-part
against `build/generated_menu` -- the emission the 89,494,606-word shipped binary was built from --
instead of against a saved hash:

    00_entry      70dcbdd0fbe050a1   SAME
    01_tables     d22b703bbfc12d67   SAME
    03_segconsts  def001b533cf662a   SAME
    04_walk       19799a7d2c3d18eb   SAME
    05_state      3d64230c653114fa   SAME
    06_banks      142,299,711 -> 79,966,363 bytes   -43.8%

`02_main` differs by ONE line and it is not this change: `;m1_reset` vs `stl.loop`, which is the
pass-2 self-reset patch the shipped emission already carries and a mid-flight build has not applied
yet. Everything else is SHA-256 identical, which is the proof that the change is confined to the
one part it should touch.

Whole emission, game tier: **157.9 MB -> 95.6 MB, -39.5%** -- deeper than the visual tier's -36.5%
because the game tier bakes more band lists.

### The SPAN, which is the currency the owner's x4 budget is written in

The full `game`-tier build (`scratchpad/m5_build.py --menu --doors`), against the shipped
89,494,606-word artifact:

    span_words   89,494,606 -> 74,091,162     -15,403,444   -17.21%
    headroom     1.500      -> 1.812          (against 2**27)
    .fjm bytes   32,879,690 -> 26,669,803     -18.9%
    build wall   3,389 s    -> 1,514 s        2.24x FASTER

**And the M1 self-reset survived 2.1M lines vanishing**, which was the real risk -- the restore set
is keyed by label and the build asserts a layout fingerprint over (label, span-to-next-label):

    "labels_moved_in_set": 0,  "values_changed_in_set": 0,
    "baked_cells_value_checked": 12234,  all 13 persisted labels present

⚠ **AND THE MICRO-BENCHMARK READ LOW -- do not reuse that method for a load-bearing number.**
`m4_rawbyte_cost.py` assembles N copies of each shape in a small program and predicted 281.1
words/arm => 11,401,761 words => 12.74%. The real build gives 15,403,444 => **17.21%**, i.e.
**379.7 words per arm, 35% more than predicted**. The same construct costs more inside a 90M-word
program than in a 17k-word one, so the isolated figure is a floor, not an estimate. The BUILD is
the authority and 17.21% is the number to quote.

The 2.24x build speedup is a second-order win that matters for M4 specifically: the assembler is
MEMORY-bound (CLAUDE.md rule 1), and peak RSS is the constraint most likely to make nine levels
impossible on a 16.8 GB box.

### The emission baseline, across all THREE shipped programs

`emit_baseline --check` before re-freezing, which is the record of what moved:

    certified     banks  DIFF  124,315,644 -> 69,552,783   -44.0%
    hosted_doors  banks  DIFF  135,625,002 -> 76,038,071   -43.9%
    standalone    banks  DIFF  135,627,081 -> 76,040,150   -43.9%
    entry / main / segconsts / state / tables / walk       SAME, all three configs
    EMISSION !! MOVED

**18 of 21 parts byte-identical across three DIFFERENT programs; only `banks` moved.** The MOVED
verdict is the tool doing its job -- it shouts when any part changes and one did, on purpose. What
makes it evidence rather than noise is WHICH: six parts x three programs unchanged to the hash.

Re-frozen with this section as the justification. (The 76,040,150 chars here against the
79,966,363 bytes the same part has on disk is CRLF: ~3.93M lines, one extra byte each.)

### The suites

    tests/host   464 passed, 1 deselected   (460 before; +4 door tests)
    tests/fj     168 passed in 27:01        (156 before; +12 from test_bands_walk.py)

**The whole trade, measured end to end: -17.21% span, -18.9% .fjm bytes, -39.5% emitted text,
2.24x faster to build, +0.10% median ops, 260/260 frames byte-exact.**

### Why the text falls 39.5% but the span only 17.2%

Worth stating, because the two numbers get conflated and only the span is what the owner's x4
budget is written in. The deleted lines are LABEL-AND-JUMP DENSE: three of every seven are things
like `t12345_67_rb_n3:`, which cost many characters and ZERO words. Across the whole program the
ratio is 1.76 bytes per span-word; across the deleted region it is 4.05 -- 2.3x more
character-dense than average. The `.fjm` tracks the span (-18.9%), not the text.

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
