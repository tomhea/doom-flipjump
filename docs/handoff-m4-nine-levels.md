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

### R1 — a geometry-only emission mode

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

### GAP 6 — the level-select UI is unplanned

`DEFAULT_MENU` is a constant list of four strings. A configurable level list needs configurable
menu entries, and M3's `mode` cell is a 1-bit toggle, not an N-way select. R3 must extend it.

### GAP 7 — R0 as originally scoped costs ~2.25 hours

"Emit each of nine maps, ~15 min each." Replace with: the free survey above, then **two or three
targeted emissions** (E1M1 as the reference, E1M8 as the smallest, E1M7 as the largest) — enough to
fit the per-map growth curve and split `banks`. Nine full emissions buys almost nothing more.

---

## 8. OPTIMIZATIONS — where the size and the time actually are

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
