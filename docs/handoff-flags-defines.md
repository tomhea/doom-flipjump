# Handoff — finish the flag retirement, CR it into main, then add `fj -D`

**Written 2026-08-28, at the end of the M2 + flag-retirement session. Start at PHASE 0.**

Everything here is either measured in that session or is a design worked out against the real
source. Numbers without a "MEASURED" label are UNVERIFIED and must be re-run before quoting.

---

## 0. Where things stand, exactly

Branch **`m2-runtime-door`**, working tree CLEAN, **7 commits unpushed**, nothing running.

    5d722f7  Flag retirement 3/N: the FlipJump half -- 65 dead macros, 1,514 lines
    f5bb2fe  Flag retirement 2/N: state_wire, over_align, and the branches the modes left behind
    e38b0f2  Flag retirement 1/N: two_sided, wall_mode, floor_mode, raster_mode
    3852273  M2: the SHIPPED standalone game gets runtime doors -- reset loop carries their state
    f8a19ca  M2-R4 fix: kb.poll's new `u` parameter had two callers in tests/
    c5e4b3d  M2-R4: the player opens the door
    3ab9f28  M2-R3: the runtime door -- one binary holds every door position

**Suites at HEAD (MEASURED):** `tests/host` 420 passed / 1 deselected · `tests/fj` 156 passed
(21:14) · `emit_baseline --check` all 14 parts SAME.

**The playable artifact:** `build/doom_e1m1_menu.fjm` — standalone + menu + self_reset + doors, all
on. Run it:

    fj build/doom_e1m1_menu.fjm --io pc --flat-max-words 134217728

enter starts the game, WASD/arrows move, **space opens doors**. It was built BEFORE the flag
retirement and is still valid: the emission is byte-identical across all three stages, so a rebuild
from current source produces the same program.

⚠ **The tier-1 default flip the owner asked for is NOT DONE.** `standalone`, `menu`, `self_reset`
and `doors` all still default `False` in `build_wall_renderer`; the artifact has them because
`m5_build.py --menu --doors` passes them explicitly. This is an outstanding owner request — see
PHASE 2c.

Signatures now (MEASURED): `build_wall_renderer` 24 params, `emit_wall_renderer` 23.
`wall_renderer.py` 2,953 lines; `src/fj/*.fj` 7,221 lines (was 8,735).

---

## PHASE 0 — push and CR what is already done (do this FIRST)

The owner's standing complaint is long-lived branches; this one already holds two milestones and
three refactor stages. Do not start PHASE 1 until this is merged or at least reviewed.

1. `git push origin HEAD` (7 commits).
2. Open a PR. **Title must be `M<N>: <feature>`** (R7). Suggested: `M2: the runtime door`.
   The branch name `m2-runtime-door` already follows the `mN-feature-slug` convention promised in
   PR #78's review — keep it.
3. Run the reviewer: `Agent(subagent_type="crist", prompt="Review PR #<n> ...")`. It reads
   `docs/cr-rules.md` and posts via `gh`. It cannot `--approve` a self-authored PR, so its comment
   body IS the verdict.
4. The PR body must carry, because R1/R2/R4/R9 all ask for it:
   * the gate outputs quoted below (§ Evidence),
   * the ops measurement (+0.46%) with its command,
   * the span rows for the new binary,
   * and the two declared deviations: the `m2_gate` carve-out and the deleted
     `test_visual_features.py` coverage (see § Debts).
5. Fix findings, re-request, merge to `main`.

### Evidence to paste (all MEASURED this session)

    M2-R3 GATE: PASS -- one binary, every door state, byte-exact on every JUDGED pixel
      C1 state 0 vs the doors-less binary, fj vs fj: IDENTICAL at all 7 viewpoints
      C0 the label capture's re-assembly reproduces the binary byte for byte
      C2 every single door alone moves pixels: 1,479 - 7,958 px across all 13
      C3 --selftest judged against the STATE 0 oracle -> rejected, 5,091 px and up

    M2-R4 GATE: PASS -- the program opens its own doors, byte-exact every frame
      40 frames; door 0 walks 0->8, holds 10, shuts to 0 by frame 27
      the player walked THROUGH the doorway (y 458 -> 958, door lines at 512..544)
      fj's own echoed position equals the oracle's every frame (this is what gates fj's COLLISION)
      --selftest (oracle never presses use): rejected from frame 2, 3,786 px

    PASSABILITY PROBE (scratchpad/m2_pass_probe.py): PASS
      states 0..3 REFUSED, 4..8 ADMITTED, pass_state = 4, all 9 observed

    M3 GATE (the shipped menu+doors binary): PASS -- 13 frames byte-exact

    OPS: +0.46% over 7 viewpoints for ALL of M2 (scratchpad/m2_ops.py --open
      build/doom_e1m1_doors_rt.fjm), shut-vs-shut control 0. An OPEN door alone is -0.52%.

    SPAN: build/doom_e1m1_menu.fjm 89,494,606 words, headroom 1.500, flat, 32,879,690 bytes,
      built in 4,966 s (two passes). DESIGN.md §1.2 needs a row for it (R4) -- NOT YET ADDED.

---

## PHASE 1 — finish the flag retirement

**The owner's ruling:** a feature that no longer needs a flag should not keep one, and the branch
nobody takes is bloat — delete it, in the Python AND the FlipJump. The policy that stops it
recurring: **a milestone's opt-in flag is retired into the default when its gate certifies.**

Already retired (all verified EMISSION IDENTICAL): `two_sided`, `wall_mode`, `floor_mode`,
`raster_mode`, `state_wire`, `over_align`, `wall_noise`, `plane_near`.

### The method, which is the important part

**The safety net is `scratchpad/cr/emit_baseline.py`.** `emit_hash_vs_head.py` compares against a
git ref by calling THE SAME SIGNATURE on both sides — useless the moment a parameter is deleted. So
`emit_baseline` freezes the emitted text's per-part SHA-256 to disk (`emit_baseline.json`, already
committed) and re-checks through whatever the API has become, dropping kwargs the signature no
longer accepts and printing which.

    python scratchpad/cr/emit_baseline.py --check              # ~20 min, the arbiter
    python scratchpad/cr/emit_baseline.py --check --selftest   # R9: must FAIL

⚠ **NEVER re-save the baseline mid-refactor.** Every stage is checked against the ORIGINAL frozen
hashes. Re-baselining ratchets a mistake in as the new "correct".

⚠ **The net only covers the two configs it was saved with, and BOTH have `plane_near=True`.** A
`plane_near=False` regression was invisible to it and surfaced only in `tests/fj`. **Before
starting, add a third baseline config with the sim and doors OFF** so the net covers more than one
point in the flag space. (Editing `CONFIGS` in `emit_baseline.py` then `--save` is the ONLY
legitimate re-save, and it must happen BEFORE any further deletion.)

**The verification ladder — cheap rungs after EVERY edit, expensive ones batched:**

| rung | cost | catches |
|---|---|---|
| `python -m pytest tests/host/test_no_undefined_names.py` | 0.4 s | a deleted branch that took a live name |
| `python -m pytest tests/host -q` | 41 s | host logic, restore-set shape |
| one targeted `tests/fj/<file>` | ~4 min | assembly + byte-exactness of that area |
| `emit_baseline --check` | ~20 min | **the byte-for-byte arbiter** |
| `python -m pytest tests/fj -q` | ~21 min | assembly of ~156 real programs |

Batch flags of the SAME KIND per emission check and commit per verified batch. Never batch across
kinds — a failed check then cannot tell you which cut did it.

**Before touching each flag, run ONE consumer sweep** across `src/`, `tests/` AND `scratchpad/` for
who still selects the non-default value, and classify every hit as either *passes the value that is
becoming the constant* (one-line strip) or *selects the value being deleted* (delete or retarget).
Discovering these one at a time via 4–21 minute runs was the single biggest time sink last session.

### The batches, easiest first

**1a. `sky`, `steps`, `stack_steps`, `bbox_cull`, `deg`** — always-True feature flags whose False
branch is mostly `*([...] if flag else [])`. Removes conditions, not big blocks; high flag-count
win, low structural risk. `deg` and `bbox_cull` also gate budget asserts
(`_assert_pnear_unbound`) — keep the asserts, drop the condition.

**1b. `things` + `moving_things` — DO NOT RETIRE. Measured 2026-08-29, and the premise is wrong.**
These are not single-valued. `things` is passed True by 11 call sites and **OMITTED by 21**, which
takes the `False` default — and the omitters include `tests/fj/test_lines_render.py`, whose
`_assemble_lines` builds the byte-exact lines fixtures. Retiring `things` into True would put the
sprite bank (~104M characters, ~7 min to emit) into every one of them and turn a 29-minute suite
into an overnight one. `moving_things` is likewise omitted by 31 call sites, and
`scratchpad/m145_static_hash.py` selects `moving_things=False` deliberately ("inert BY
CONSTRUCTION"). A flag with two live values is not bloat; it is a flag.

**1c. `player_sim` + `collide` — DO NOT RETIRE, same reason.** Each is omitted by 31 call sites,
which take `False`, and `collide=False` is explicitly selected by `scratchpad/m14_ablate_price.py`
and `scratchpad/opprof.py` — a sim build that does not pay for collision is a real measurement
config. Retiring them would force the sim into every fixture that omits them today.

**1d. `sector_heights`** — R2's static door override, superseded by `doors`. Deleting it retires
`scratchpad/m2_build.py` and `scratchpad/m2_gate.py` (R2's rung). Keep the built
`build/doom_e1m1_doors100.fjm` — `m2_ops.py` uses it as a measurement baseline.

**1e. `ablate` (26 modes)** — the owner ACCEPTED keeping it: it is the only way perf work gets
priced in this repo and every ops number in `docs/` came from it. Do not remove without a new
instruction.

**1f. The oracle's dead renderers — DONE, but smaller than it looks.** `render_frame_2s` (131
lines) was genuinely dead and is gone, with its three tracked probes. The framebuffer/stream paths
are NOT: `render_frame` is the background reference in `test_floor_planes`, `test_reference_model`
and `test_wall_frame`, and `render_wall_frame`'s `wall_mode` is still passed five values by tracked
files — W1 (7), W1R (57), W2 (3), WPX (19), textured (7). The oracle is the reference implementation
of the whole ladder and the tests compare against several rungs on purpose; deleting a mode there
deletes a test's expected answer, which is not the same as deleting an emitter branch nothing takes.
**The emission net does NOT cover the oracle**; `tests/host` is the arbiter.

### PHASE 1 — WHERE IT ACTUALLY LANDED (2026-08-29)

Done: **1a** (`sky`, `steps`, `stack_steps`, `bbox_cull`, `deg`), **1d** (`sector_heights` + R2's
rung), **1f** (`render_frame_2s`). `emit_wall_renderer` 23 -> 17 parameters, `build_wall_renderer`
24 -> 18. Every stage EMISSION IDENTICAL across all three baseline configs.

Refused with evidence: **1b** and **1c** (see above). **1e** (`ablate`) kept, per the owner.

Two lessons the batches cost, both worth more than the flags:
* **A flag can carry two facts.** `sky` meant both "render V2 sky ceilings" and "this wad has no
  sky lump", which is true of `square_room.wad` and `arena.wad`. Folding it to True made a sky-less
  map emit `skyoff.lookup` against a bank never built — an ASSEMBLY error no baseline config could
  show, since all three are E1M1. It is `_has_sky`, read off the map.
* **Only dedent a block when the WHOLE condition is the constant.** `if steps and (_um or _lm):`
  became unconditional instead of `if _um or _lm:` — +27,397 chars, caught by the emission baseline
  and by nothing else.

And the sweep found more than the batches: **32 tracked callers were already broken on `main`** by
the M2 retirement, including `scripts/walk_e1m1.py`, `scripts/measure_frame.py` and `deg_gate.py`.
`tests/host/test_emitter_call_sites.py` now guards that class permanently.

⚠ **What this means for PHASE 2's "6 parameters".** That target assumed 1b and 1c would succeed.
They cannot, so `things`, `sprite_wad`, `player_sim`, `collide` and `moving_things` all have to stay
expressible. The reachable shape is roughly **11-12**, not 6: `tier` still collapses
`standalone`+`menu`+`self_reset`, `generated_dir` still derives from `out_fjm`, and
`flat_max_words`/`door_quant`/`menu_entries`/`menu_selected` still fold into `cfg`.

### PHASE 2 — DONE (2026-08-29). The API is SIX parameters.

    build_wall_renderer(out_fjm, *, wad_path=DEFAULT_WAD, mapname="E1M1", cfg=None,
                        tier="game", ablate=frozenset())

`emit_wall_renderer` went 17 -> 8 the same way. The target was 6 and the earlier note here said
11-12 was the reachable shape; that note was wrong, and the reason is worth keeping:

**The flags were never the problem. The absence of NAMES was.** `things`, `player_sim`, `collide`
and `moving_things` each had two live values, which is why PHASE 1 refused to retire them -- but
they do not vary INDEPENDENTLY. Eight booleans describe 256 nominal programs; the repo ever built
seven. Naming those seven collapses all eight parameters into one, and keeps every configuration
that made retiring them impossible.

`wall_renderer.TIERS` is the registry. **A new combination is a new ROW, not a new parameter** --
that is the whole mechanism, and it is what stops the count creeping back up.

| tier | what it is |
|---|---|
| `game` | the shipped playable binary, and the DEFAULT (the owner's tier-1 flip, delivered) |
| `hosted` | the hosted renderer a Python host drives over the wire |
| `hosted-doors` | the same with runtime doors -- what the M2 gates build |
| `visual` | sprites, no simulation -- the picture gates, `deg_gate` among them |
| `render` | the cheap fixture tier: NO sprite bank, which is what keeps `tests/fj` at half an hour |
| `hosted-nocollide` / `hosted-static` / `loop` | measurement tiers -- pricing needs no parameter |

Everything else derives: `generated_dir` from `out_fjm`, `flat_max_words` from `cfg`, the restore
set from the tier (so the hosted and standalone sets cannot be crossed), `sprite_wad` internally.
`menu_entries`, `menu_selected` and `door_quant` were constants every caller already left alone.

⚠ **`m5_build.py` no longer builds partial standalone combinations** (`--menu`/`--doors`/
`--no-reset` assert instead). They were rungs on the way to `game`; the owner confirmed they are
not needed. If one is ever wanted again it is a TIERS row.

### PHASE 2d — CR the whole retirement into main

Same loop as PHASE 0. The PR body needs, per the R-rules:
* `emit_baseline --check` output (all parts SAME) as the R2/R6 evidence,
* the before/after line and parameter counts,
* **the coverage debt below, stated not buried** (R9's "say what was not judged"),
* and the re-run gate outputs if any default was flipped.

---

## Debts and declared deviations (carry these into every PR body)

1. **`test_visual_features.py` was DELETED and V1–V4 lost their only IN-SUITE byte-exact gate.**
   It was pinned to the WPX tier's whole configuration; two retarget attempts at the shipped flag
   set stayed ~15k of 16k pixels out. Those features remain gated by `deg_gate` / `m3_gate` /
   `m5_gate`, which are scratchpad tools, not pytest. **Rebuilding an in-suite shipped-tier gate is
   real work and is not done.** The owner accepted this.
2. **`m2_gate.py`'s PASS is byte-exact on every JUDGED pixel**, with 7 changed pixels inside the
   standing 378-px non-sim-tier delta NOT judged. Quote the verdict line whole.
3. **R7 branch-name deviation is spent** — `m13opt3-early-out` was waived once, explicitly not a
   precedent. New branches are `mN-feature-slug`.
4. **DESIGN.md §1.2 has no span row for `build/doom_e1m1_menu.fjm`** (89,494,606 / 1.500 / flat /
   32,879,690 bytes / 4,966 s). R4 wants one.

---

## The hazards that actually bit last session — read before deleting anything

1. **A function body is its INDENTED BLOCK.** A deleter that stops at the next `def` swallows the
   module-level code between functions. This bit TWICE: three constants out of `wall_renderer.py`
   (`LINES_HALF_SLOTS`, `STEP_SLOT_STRIDE`, `STEP_COL_STRIDE`) and an import + constant out of
   `test_plane_kernel.py`. Stop at the first non-blank column-0 line, and **diff the module's
   top-level names before/after every cut**.
2. **`cut(start, end)` needs the IMMEDIATELY FOLLOWING landmark.** One distant end anchor would
   have deleted ~1,000 lines silently; only the next anchor assertion caught it.
3. **A trailing `\` inside a Python string literal is a LINE CONTINUATION.** Any anchor spanning a
   backslash-continued source line silently loses its newline and matches nothing.
4. **The fj liveness scan must over-approximate LIVENESS.** The first version anchored on an
   indented leading name and missed `rep(n, k) .macro args` — mid-line, dot-prefixed — declaring
   `ts_step_faces`, `lines_step_load`, `lines_spr_load` dead. All three SHIP. Tools:
   `scratchpad/fj_deadmacros.py` (analyse) and `scratchpad/fj_cut_dead.py --dry` (remove).
   A live macro wrongly listed costs a failed assembly; a dead one left in place costs nothing.
5. **Deleting a test FILE can break collection of the whole suite** — a shared helper
   (`_ScreenWithInput`) lived inside `test_wall_render.py` and `test_plane_span_pass.py` imported
   it. Grep for imports from any file before deleting it. (It now lives in
   `tests/fj/stream_screen.py`.)
6. **Retiring a FORMAT invalidates everything that FEEDS it, and the symptom looks like a render
   bug.** Killing the decimal wire left dec-fed tests sending text at a bin-only program: magic-byte
   check fails → `bad:` → an all-zero frame vs the oracle's picture. Two cycles went into suspecting
   the renderer. Ask "what feeds this?", not just "what reads this?".
7. **A reported value computed by a SECOND expression drifts.** `metrics["persisted_labels"]` said 9
   while the reset persisted 13. When a retired flag appears in `metrics["features"]`, KEEP THE KEY
   (every gate log reads it) but source it from the constant.
8. **Nothing fast calls the emitter and nothing can** — emitting even a three-sector fixture is
   ~570 s, because the texture/colormap banks scale with the ASSET wad, not the map. That is why
   `tests/host/test_no_undefined_names.py` (pyflakes, 0.4 s, with a negative control) exists. Run it
   after every edit.

---

## PHASE 3 — `fj -D NAME=VALUE`, a define flag for the assembler

**Owner's ask:** add a `-D` flag to flipjump-1.5.1 that defines constants at the start of the
program, before anything. Assemble/both modes only, never `--run`. **Minimal, clean, no bloat.**

Repo: `C:\Users\tomhe\Documents\flipjump-151` (a local checkout; the doom project imports it).
⚠ Its perf commits are local-only on branch `perf-asm-10min` — check `git status` there first.

### Why this shape

* FlipJump constants are plain `NAME = EXPR` at file scope (`dw = 2 * w` in `stl/runlib.fj`).
* The assembler consumes `List[Tuple[str, Path]]` from
  `flipjump/utils/functions.py::get_file_tuples`, which puts the STL first and then the user files.
  It reads PATHS, so a define needs to be a real file — and a temporary directory already exists in
  the one place that matters.
* `flipjump_cli.py::execute_assemble_run` already owns a `TemporaryDirectory` and calls
  `assemble(...)` inside it. That is the natural, minimal home: no new temp dir, no new plumbing.
* Putting the file FIRST among `args.files` means it lands after the STL (so defines may use `w`,
  `dw`, …) and before every user file — which is "at the start of the program, before anything".

### The change (three small edits, ~8 lines total)

**1. the argument** — in `add_assemble_only_arguments`, next to `--no_stl`, so argparse documents
it under "assemble arguments (Ignored when using the --run option)":

```python
asm_arguments.add_argument(
    '-D',
    '--define',
    action='append',
    default=[],
    metavar='NAME=VALUE',
    help="define a constant before the assembled files (repeatable)",
)
```

**2. materialise it** — in `execute_assemble_run`, inside the `with TemporaryDirectory(...)` and
before `assemble(...)`:

```python
if not args.run and args.define:
    defines_path = Path(temp_dir_name) / '_defines.fj'
    defines_path.write_text(''.join(f'{d}\n' for d in args.define), encoding='utf-8')
    args.files.insert(0, str(defines_path))
```

Each `-D` value is written verbatim as one line, so `-D N=5` becomes `N = 5`... **only if it
already contains `=`.** Validate and normalise:

```python
for d in args.define:
    if '=' not in d:
        error_func(f"-D expects NAME=VALUE, got {d!r}")
```

**3. nothing else.** No changes to the assembler, the preprocessor, `get_file_tuples`, or
`flipjump_quickstart.assemble()` (the Python API doom-flipjump uses is untouched; if it ever needs
defines it can pass its own `.fj` file, which is what `-D` is sugar for).

### Notes for whoever implements it

* **No new imports are needed** (VERIFIED): `flipjump_cli.py` already imports `Path` (line 10) and
  `TemporaryDirectory` (line 11). `args.files` is a `nargs='+'` list, so it is mutable.
* The flipjump checkout is on branch `perf-asm-10min` and was CLEAN at handoff time.

* `get_temp_directory_suffix(args.files)` is evaluated when the `with` opens — mutate `args.files`
  AFTER it, which the placement above already does.
* The `not args.run` guard is what keeps it out of run-only mode; the argparse group only
  DOCUMENTS that, it does not enforce it.
* Redefining an STL constant will be an assembler error, not a silent override. That is correct
  behaviour, and worth one line in the `help` if it surprises anyone.
* **Test it** the way that repo tests the CLI: `flipjump-151/tests/` — assemble a two-line program
  that uses a `-D`-defined constant and check the output, plus one case asserting `-D FOO` (no `=`)
  is rejected. Keep it to two tests.
* The doom project pins its own flipjump; if `-D` is meant to be used from there, note that
  `doomfj.harness.assemble_fjm` and `fj.assemble()` take file lists, not CLI args.

---

## Reference — commands and paths used constantly

    # gates (all SOLO -- CLAUDE.md rule 1: ONE HEAVY BUILD AT A TIME, check the PROCESS is gone)
    python scratchpad/m2_r3_gate.py [--selftest]      # the runtime door's render, per state
    python scratchpad/m2_r4_gate.py [--selftest]      # the trigger + state machine, 40 frames
    python scratchpad/m2_pass_probe.py                # can you walk through, at every state
    python scratchpad/m3_gate.py                      # the shipped menu+doors binary
    python scratchpad/m2_ops.py --open <fjm> --label "..."   # ops/frame vs the doors-less binary

    # the refactor's safety net
    python scratchpad/cr/emit_baseline.py --check
    python scratchpad/fj_deadmacros.py                # fj macros: defined / reachable / dead
    python scratchpad/fj_cut_dead.py --dry

    # builds (~20 min hosted, ~80 min standalone two-pass)
    python scratchpad/m2_rt_build.py                  # hosted + doors (the gates' binary)
    python scratchpad/m5_build.py --menu --doors --out build/doom_e1m1_menu.fjm
        # THE PLAYABLE ARTIFACT. No --gen: PHASE 2 made the emitter DERIVE the generated
        # dir from out_fjm, so this writes build/generated_doom_e1m1_menu/. The flag was
        # parsed and then silently IGNORED from PHASE 2 until 2026-08-31 -- this very
        # invocation named a directory the build had stopped writing. It is gone now, and
        # m5_build prints the path it will actually use.

    # the standalone restore set, when a new global must survive the reset
    python scratchpad/ca_labels.py --standalone --menu --doors --out scratchpad/_labels.tsv.gz
    python scratchpad/m5_setfile.py --labels scratchpad/_labels.tsv.gz \
        --doors tests/fixtures/freedoom_e1m1.wad
    python scratchpad/m5_setfile.py --selftest        # P + C1..C4

**The owner's standing rule, from this session:** *never call a feature complete until the M1 reset
loop carries its new labels* — the restore-set entries AND, for world state, `build.STANDALONE_PERSIST`
/ `DOOR_PERSIST`. A gate that passes on a tier the player never runs is not completion.
