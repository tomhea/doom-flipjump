# Handoff — M4: nine levels in one image

**Written 2026-08-31, at the end of the session that merged M2, the flag retirement and the tier
API. Start at section 3. Nothing has been built or measured for M4 yet — section 2 is the whole
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
- The `stl.fcall` early-out check is still untaken.
- **10 open findings** in `scratchpad/cr2/findings/`.
- `self_reset=False` has not been built on the post-hoist tree, so the reset part's own span is
  unmeasured.
- `flipjump-151`'s `origin` remote redirects; the URL is not updated.
- The V-gate oddity: `v5_gate` and `w1r_faces_gate` build a THINGS-LESS program (tier `render`).
  That predates this session and was preserved exactly rather than silently "fixed" — but it means
  those two gates certify less than their names suggest.
