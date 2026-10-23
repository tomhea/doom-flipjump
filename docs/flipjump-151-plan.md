# The flipjump plan: the new screen/keyboard API, the stl additions, and 1.5.1 → main

The owner's plan, agreed over the night of 2026-10-23/24. The executor (Claude) **follows it and updates it as
work lands**. Each step has a status, what it touches, how it is proven, and when it is done. Every change is
recorded in the update log at the end.

Status marks: ✅ done · ▶ running · ⏳ next / queued · ⏸ paused · ✖ dropped.

It lives in the doom repo, not in flipjump, so the 1.5.1 → `main` diff the owner reviews stays clean.

---

## 0. The goal and the owner's order

**The end point:** the owner's manual review of flipjump `1.5.1` into `main`. By then 1.5.1 holds:

- the new screen/keyboard API;
- the stl additions taken from fjdoom;
- a branch already cleaned by a review loop under the owner's five rules.

fjdoom must run on all of it, and it must already use every macro that moved into the stl.

**The owner's order (2026-10-24, revised at 00:30):**

1. E1M1 works on the new API, and the other levels follow in parallel. **Phase 1.**
2. io-api is merged into 1.5.1 after a review loop. **Phase 2, ✅.**
3. A `stl-additions` branch from 1.5.1 takes every macro we discussed: `fixed_mul` and its family, `read_entry`,
   `hex.switch`, `screen.fj`, the keyboard poll, `write_back` / `read_back`, `ptr_index n`, and the chained table
   dance. It is written to the standard of the classic stl. **Phase 3.**
4. fjdoom adopts each macro as soon as it lands. **Anything that moves into the stl is removed from fjdoom
   completely:** no copy, no reference to the old name or the old implementation. **Phase 4.**
5. I merge `stl-additions` into 1.5.1 myself. **Phase 5.**
6. The review loop 1.5.1 → `main`, **without merging**; the owner reviews it by hand. **Phase 6.** It started on
   Saturday and runs the stl area last.
7. Part C (faster sequential pointer access) may merge into 1.5.1 **during** the owner's review, after its own
   separate testing phase. **Phase 3d–e.**

**The owner's later decisions (2026-10-24, about 01:00):**

- Phase 1 is folded after E1M2. E1M3 and later are built once, after the adoption, in 4d.
- E1M1 re-ships twice: once on the new API (#1) and once after the adoption (#2).
- Use correct branching and git practice.
- A level above 43% size is OK.
- Every gap fix in section 9 is agreed.

---

## 1. Branches, worktrees, paths

**flipjump** (`C:/Users/tomhe/Documents/`):

| worktree | branch | role | state |
|---|---|---|---|
| `flipjump-151` | `1.5.1` | the INSTALLED flipjump (pip -e) | at `5af5923`. Not moved yet: blocked63 needs the old device until ship #1's A/B is done. |
| `flipjump-io` | `io-api` | the API work | fast-forwarded to `9f6119c` (= 1.5.1 after #375); junction `fjio-path` |
| `flipjump-cr` | `cr-minimal` | io-api's review loop | `eacc7ee`, pushed, merged by #375; junction `fjcr-path` |
| `flipjump-chain` | `stl-additions` | phase 3 implementer | part A committed (`691d19f`, `932352e`, `0823543`, `ea823e4`), part B in the working tree; junction `fjstl-path` |
| `flipjump-stlpin` | detached at the last COMMITTED `stl-additions` commit | what the doom adoption checks run against | `ea823e4`; advanced to each new stl commit; junction `fjstlpin-path`. **Never point a check at the implementer's live working tree:** its uncommitted moves collide with fjdoom's copies, which made 44 fj tests fail on 10-24 |
| (new) | `stl-seq-ptr` | part C (3d) | not created yet; it branches from `stl-additions` |
| `flipjump-crmain` | `cr-main` | phase 6 | from `9f6119c`; baseline `crmain_base.json` saved |
| `flipjump-bytes` | `stl-byte-output` | the byte-output check | ✖ closed: no improvement, never merged |

**doom-flipjump:**

| worktree | branch | role | state |
|---|---|---|---|
| `doom-io` | `io-api` (from `m8-episode`) | fjdoom on the new API | `7df54d00` + `24621131`, pushed; E1M1 ship #1 running |
| `doom-stl` | `stl-adopt` (from `io-api`) | phase 4 | step 1 (chained add/sub) done in text, under test |
| `doom-episode` | `m8-episode` | the integration branch | `e955dc2d` |
| — | `w2fix-wip`, `soultele-wip` | paused level fixes | merge after `stl-adopt` (section 7) |

**Path rule.** A doom run against an uninstalled flipjump puts a **junction holding only the `flipjump` package**
first on `PYTHONPATH` (for example `fjstl-path;src`). Putting the flipjump worktree root there shadows doom's `tests`
package.

**Git rule.**

- Flipjump: `1.5.1` is the integration branch, and every change reaches it through a PR: `stl-additions`,
  `stl-seq-ptr` and `cr-main` each go into 1.5.1. Then the owner reviews 1.5.1 → `main`.
- Doom: `io-api` → `m8-episode` (PR + CI). Then `stl-adopt`, merged up to date with `m8-episode`, goes into
  `m8-episode`. Then the WIP branches.
- Always: merge commits, no force-push, merged branches deleted, and a stacked PR retargeted before its base is
  deleted. Never `git add -A scratchpad/`.

---

## 2. Phase 1: fjdoom on the new screen/keyboard API

The API is `flipjump/interpreter/io_devices/README.md`.

| # | step | status | proof |
|---|---|---|---|
| 1a | Every emitter speaks the API (see below) | ✅ `7df54d00` | host 2,688 passed; the converted fj tests |
| 1b | Gate harnesses on the new device: their own `NativeDeviceMemory` view, `shown_palettes` | ✅ `24621131` | — |
| 1c | E1M1 (`build/doom_e1m1_io.fjm` = **blocked64**) | ✅ | m3 88 frames, m2 421, p2a, hurt, fight, die PASS; B0 OK 16,297,393 (+0.26% vs blocked63); window smoke PASS; re-checked on the cleaned device (m3, m2) |
| 1d | E1M2 (`build/doom_e1m2_io.fjm`) | ✅ | m3, m2 (258), p2a, hurt, fight, die PASS; B0 OK 20,193,314; window smoke PASS |
| 1e | E1M3+ | ✖ folded into 4d (owner) | — |
| 1f | **E1M1 ship #1**: rebuild byte-identical, `gamespeed`, msframe A/B vs blocked63 | ▶ rebuild **BYTE-IDENTICAL** (`f52751a2bb846c7a`); gamespeed binding **16,921,550 PASS** (mean 16,151,475, p80 17,691,624), size **39.13% PASS** (file 39,836,502 bytes). msframe waits for a quiet box (refused while agents ran) | blocked63's 16,892,755 / 38.98% come from ship-gate.md, UNVERIFIED here: +0.17% ops, +0.15 points of size |
| 1g | Ship record: `docs/ship-gate.md` 1 + 1b, CLAUDE.md's shipped-binary line, the README's play command, `shipped` baseline re-frozen on blocked64 under the new flipjump | ⏳ after 1f | — |
| 1h | PR `io-api` → `m8-episode`, CI green, merge | ⏳ after 1g | — |

**What the conversion did (for reference):**

- `src/doomfj/screenwire.py` is the only home of the API's numbers.
- A cold `io_boot` routine at the end of the program sends `init_screen` and defines palettes `0..n-1`.
- Each frame sends `select_palette`; `present.end_frame` sends `END_CMD` then `0x1F`.
- Column lists always end with END; zero-row items are legal (the owner relaxed the API).
- Keyboard:
  - hi nibble 8 is Ctrl: 0x80 / 0x84 fire;
  - the arrows are 0xD7..0xDA;
  - the `KC_*` constants live in `keyboard.py`.
- The hosted channel moved to extension opcodes: STATE 0x80 and THING 0x81, demuxed by `StreamScreen` through
  `_extension_command`.
- Removed with no replacement: `build_unroll_frame`, `m11c_evidence.py` and its tests, and the
  collines/unroll/render-macro/plane-span tests.

**Ship #1's rules.** blocked64 is class F: its pixels are blocked63's, but its device bytes differ. msframe runs
blocked63 on the old installed flipjump and blocked64 on 9f6119c (`--env-a`). The result is recorded as the API's
price. A tripwire at ~90 ms/frame must be explained before shipping. The installed `flipjump-151` moves to the
merged 1.5.1 only after this A/B.

---

## 3. Phase 3: the `stl-additions` branch (flipjump, from 1.5.1)

**The standard (classic stl):**

- Same file layout, the stl's own `ns`/naming idiom, and a doc comment above every macro in the stl's style:
  - what it computes;
  - its complexity in ops and space;
  - its preconditions;
  - what it clobbers.
- Every macro has hexlib tests in `tests/` (`tests/inout/hexlib*` + `conftest` tables, as the existing ones are
  written).
- `stl/README.md`, `stl/hex/README.md` and `conf.json` are updated.
- Every change runs `fjm_identity.py --check` against the 1.5.1 baseline:
  - programs that do not use a changed macro must assemble byte-identical;
  - programs that do must change only where expected.

### 3a. The chained table dance (the owner's idea) ✅ part A committed

An n-hex table op runs as one chain:

- a **head** step (sets `ret`, does not clear it);
- n−2 **chained** steps;
- a **tail** step (flips and clears).

A chained step flips `ret` from the previous step's landing label to its own in **one wflip**. `prev` is computed
from its own labels as `start − (after − return)`: every step expands identically, so the stride is fixed.

- **`pad 16` before `return:`** is the owner's decision. Every landing label is aligned, so the chain flip costs
  1–2 bits instead of ~4.
- **Report, never silently change:** for each macro, its stride and whether that stride is a power of two. If one
  is not, the owner is told; the pad stays.
- The chained variant is namespace-internal (`.add.chain` etc.): a hermetic window in which `ret` is live inside
  the chain.

Applied to: `hex.tables` (+ `or n` / `and n`), `hex.add` / `hex.sub` n + `_shifted`, and `hex.add_mul` n.
Committed as `691d19f`, `932352e`, `0823543`; tests `ea823e4` at n = 1, 2, 3, 4, 7, 8, 16.
`cmp` comes later: its early exits must clear `ret`.

**Proof:** bit-identical results (the stl/hexlib tests plus random carry vectors, n = 1..8+), then the op savings.
fjdoom's gates and msframe decide (4f).

### 3b. Macros moved from fjdoom ▶ (working tree)

| fjdoom today | stl name (decided) | stl file | notes |
|---|---|---|---|
| `hex.fixed_mul n, f, dst, a, b` (`src/fj/fixed_point.fj`) | `hex.fixed_mul` | `stl/hex/mul.fj` | name kept |
| `hex.fixed_div n, f, dst, a, b, div0` | `hex.fixed_div` | `stl/hex/div.fj` | name kept |
| `hex.mul_lo n, res, a, b` | **`hex.mul_low`** | `stl/hex/mul.fj` | owner: "low", not "lo" |
| `hex.fixed_mul_lo n, f, dst, a, b` | **`hex.fixed_mul_low`** | `stl/hex/mul.fj` | — |
| `hex.mul_const n, dst, src, c` | `hex.mul_const` | `stl/hex/mul.fj` | — |
| `hex.read_table n, dst, table, idx_n, idx` + `_byte`, `_packed` | **`hex.read_entry`** (+ `_byte`, `_packed`) | `stl/hex/pointers/read_pointers.fj` | dst = arr[i] for an array at a constant address; built on `ptr_index n` (one address step); the cheaper scaling (shift stage vs `mul_const`) is measured, and the faster one is used |
| `frame.ptr_index4/5/6 dst, ptr, index` + `ptr_index_fill` | **`hex.ptr_index n, dst, ptr, index`**, a width OVERLOAD of the existing 3-parameter form | `stl/hex/pointers/pointer_arithmetics.fj` | an unsigned `hex[:n]` index; equal to today's form at n = w/4, like `add` / `add n`. **No second macro** (owner); the interim names `ptr_index_n` / `ptr_advance` are dropped |
| `sim.jump16 x, t0..t15` | **`hex.switch`** | `stl/hex/cond_jumps.fj` | a 16-way jump on a hex |
| `present.*` (`init_screen`, `select_palette`, `draw_collines`, `end_frame`, `set_window_title`, `set_window_icon_header`, `set_max_fps`) | `stl/screen.fj` (new) | `stl/screen.fj` | the API's commands as macros; the opcodes come from the README |
| the generic keyboard read inside `input.poll` | a keyboard poll in `stl/hex/input.fj` | `stl/hex/input.fj` | the status nibble 0/8/9, then the keycode; fjdoom's `input.fj` keeps only its key bindings |

### 3c. The prearmed pair ⏳

- **`hex.write_back src`** is fjdoom's `frame.write_byte_prearmed` without its filler: it writes through a pointer
  that is already armed.
- **`hex.read_back dst`** is its read twin, which the owner asked for. The names are my proposal; the owner asked
  for something simpler than `write_byte_prearmed`.
- Documented and tested properly, including **the six gap tests**:
  1. the arm is still valid after a write;
  2. two writes in a row;
  3. a read after a write;
  4. a byte at both nibble ends;
  5. a re-arm to a different address;
  6. a precondition violation that is detected where it can be.
- **Stay in fjdoom (owner):** the narrow arms (`arm5` / `arm3`) and the `*5` / `*3` reads and writes. Their
  precondition is non-local and they fail silently.

### 3d. Part C: faster sequential pointer access ⏳ (branch `stl-seq-ptr`)

- A pointer walking an array advances its armed fields by `dw` instead of re-arming. Reads and writes chain the
  way part A chains table steps.
- The owner approved it with **a separate, independent testing phase (3e)**: a fresh agent proves correctness
  (exhaustive small widths plus random sequences against a Python model) and measures timings (ops and wall time
  against today's pointer ops).
- It gets its own short review loop, then a PR into 1.5.1. It may land **during** the owner's review.

### 3f. Byte output ✅ closed: no change to the stl

The stl's `hex.output` is already the best variant: 34–38 ops/byte. fjdoom's `byte.emit` costs 74–83 and is ~1.25×
slower. The shared-table and `pad 64` variants lose. The consequence is an **adoption item** (A8):
`byte.emit` → `hex.output` on the low then the high nibble, judged by msframe (it adds about 8 ops of space per
call site).

### 3g. The review loop on `stl-additions` ⏳

The owner's five rules (section 6) are applied to the new stl code until a round is clean. Then the PR
`stl-additions` → 1.5.1, which I merge (phase 5).

---

## 4. Phase 4: fjdoom adopts the stl (doom `stl-adopt`)

**For every macro, as soon as its stl commit lands:**

1. Delete fjdoom's implementation: the fj macro, and any Python emitter that writes it.
2. Move every call site to the stl name: fj files, the emitters' f-strings, `build_blocked` `SAFE_TABLE_MACROS`,
   tests, scratchpad tools, prose.
3. Check that this grep is EMPTY over `src/ tests/ scripts/ scratchpad/`: the old macro name, the old file name,
   and any comment that describes the old implementation.
4. Cheap proof: the doom host suite, the fj tests that exercise it, and an E1M1 emit with asserts ON (never
   `python -O`). Add E1M1's quick gates when hot code changed.
5. Commit on `stl-adopt` with the proof numbers.

| # | adoption item | status |
|---|---|---|
| A1 | `frame.add*/sub*_chain` + `dance_boundary` → `hex.add n` / `hex.sub n` (~160 sites: projection.fj 101, frame_render 36, stream_render 15, aimcode 6, scrollcode 1, tests) | ▶ grep empty. E1M1 emit_check PASSES (asserts on; hot block 10,430 of 16,384). Host 2681 passed; its 7 failures are 6 from the live-tree collision plus 1 expected: `lb_c`'s width is now visible to the narrowed-clear scan, so its pin moved from 1 to 0. Re-run against `flipjump-stlpin` queued |
| A10 | `FJM_LZMA_FAST` (harness.py) → `lzma_preset`: a low preset for day-to-day builds, normal compression for ship builds; chosen by measurement (owner, 10-24) | ⏳ after round 1b |
| A2 | `fixed_point.fj` deleted → `hex.fixed_mul/div`, `mul_low`, `fixed_mul_low`, `mul_const` | ⏳ after 3b |
| A3 | `read_table*` → `hex.read_entry*` | ⏳ after 3b |
| A4 | `frame.ptr_index4/5/6` + `ptr_index_fill` → `hex.ptr_index n` | ⏳ after 3b |
| A5 | `sim.jump16` → `hex.switch` | ⏳ after 3b |
| A6 | `present.fj` deleted → `stl/screen.fj`; `input.fj` → the stl poll + its bindings | ⏳ after 3b |
| A7 | `frame.write_byte_prearmed` → `hex.write_back` (and `read_back` where a prearmed read exists) | ⏳ after 3c |
| A8 | `byte.emit` (lut_generator) → `hex.output` low + high nibble | ⏳ |
| A9 | Part C's sequential access, where fjdoom walks arrays | ⏳ after 3e |

**After the last item (the gap fixes of section 9 are built in here):**

- **4b. Pins.**
  - Regenerate the heat / census pin files. They are keyed by label names, which the adoption changes, so the old
    pins silently stop matching and the table placement re-rolls.
  - `heat_blocked27_p10.json.gz` gets a successor from a fresh profile of E1M1's play, and each level gets its own.
- **4c. Baselines.** Re-freeze the frozen op-count baselines (`deg_gate`, `emit_baseline.json`, the B0 records).
  Each changes by design; the reason is written in the commit.
- **4d. Rebuild and gate all levels, one at a time (~10–12 h of heavy work).** E1M1, E1M2, E1M3, E1M4, E1M5, E1M8,
  E1M9: build, then m3, m2, p2a, hurt, fight, die, B0, window smoke, gamespeed, and the playthrough where it exists.
  - For E1M8 and E1M9 the rule is: a gate that passed before must pass now; a known failure must fail the same way;
    no new failure.
- **4e. Size per level, right after the adoption.** `pad 16` adds ~12 ops per nibble to every multi-hex add/sub.
  The owner accepts above 43%; **2^27 words stays the hard limit**. A level within ~5% of 2^27 goes to the owner
  before anything else is done.
- **4f. Speed.** B0 per level, and E1M1 ms/frame A/B against blocked64.
  - If the stl's generic chain is slower in a hot spot than fjdoom's hand-fused chain was, **report it with the
    numbers**. Never keep a private copy.
- **4g. E1M1 ship #2** goes through `docs/ship-gate.md`, class S if every pixel is blocked64's. **B SLOWER does not
  ship.**
- **4h.** PR `stl-adopt` → `m8-episode`, CI green, merge.

---

## 5. Phase 5: `stl-additions` into 1.5.1

- I merge it after 3g is clean and 4d is green.
- Then the installed `flipjump-151` fast-forwards to the merged 1.5.1, after ship #1's A/B has been recorded.
- The `cr-main` identity baseline is re-saved at this merge point (gap 5).

---

## 6. Phase 6: the review loop, 1.5.1 → `main` (no merge)

Branch `cr-main` from 1.5.1 (`9f6119c`), worktree `flipjump-crmain`.

**The owner's five rules:**

1. Minimal changes, as close to `main` as possible.
2. The same naming, doc style and length, tests, and function line length as `main`.
3. A similar API for everything.
4. Clean code in every addition or modification.
5. Correctness and tests come first.

**Loop mechanics:**

- One reviewer agent per area reads `git diff main...cr-main` for that area. Its findings are BLOCKING or MINOR,
  all reported in one pass, and go to `scratchpad/ioapi/cr/main_<area>_round<N>.md`.
- One fixer applies them. Then **byte identity:** `fjm_identity.py <wt> --check crmain_base.json` (117 `.fjm`, all
  compile tables), plus the full unit suite.
- Round N+1 re-reviews until a round has no BLOCKING finding and no MINOR worth taking.
- At most 2 agents at once, shared with phase 3.
- R9 control: `--mutate` must catch a one-op stl change. ✅ It caught one.

| # | area | status | notes |
|---|---|---|---|
| 6a | Identity baseline: `pytest --compile --all`, 117 `.fjm` hashed | ✅ | 1263 passed, 1 skipped; R9 control OK |
| 6b | Assembler + blocking pass | ▶ round 1 reviewed: **4 BLOCKING, 31 MINOR** | fixer next; the owner decides whether the table pool moves to its own file |
| 6c | Native engine, interpreter, CLI | ⏳ | — |
| 6d | IO devices (1.5.1's earlier changes; #375 is already clean) | ⏳ | — |
| 6e | Tests + programs | ⏳ | — |
| 6f | **stl, last**, after phase 5 | ⏳ | — |
| 6g | Final proof: every test program byte-identical to the last baseline; the E1M1 shipped binary rebuilt byte-identical | ⏳ | — |
| ➡ | **The owner's manual review** | — | non-stl areas from ~6e, the whole branch after 6g |

**Area 1, round 1 (2026-10-24).** The full list is in `scratchpad/ioapi/cr/main_area1_round1.md`.

BLOCKING:

1. About 160 lines of history comments ("PERF (doom-flipjump, …)", "MEASURED …"; one comment pasted 6× in
   `ops.py`).
2. `labels_resolve`'s old deque path was rewritten for speed, but `assemble()` no longer takes it. Restore main's
   version.
3. `_labels_resolve_stream` repeats one 9-line operand decoder 5×. Use `_deferred_value`, and time the stage before
   and after.
4. Error output off a terminal changed (`stopped after Ns`). Restore it and add a test.

Strongest MINOR: move `TablePool` / `BlockPool` / `BlockCensus` / `DeferredTables` (~1,440 lines) into
`flipjump/assembler/table_pool.py` (**the owner's call**). The others:

- `_cheap_indices` is quadratic;
- duplicate helpers in `op_stream.py`;
- `fj_parser`'s misplaced `# noinspection` and a filesystem call per constant;
- `WFlipSpot` → `dataclass(slots=True)` to keep main's field names.

Every proposed change keeps the assembled `.fjm` byte-identical.

**The owner's API decisions (2026-10-24, round 1b, after round 1's fixes).** The audit compared every public
entry point with `main`.

1. **Every combined quickstart helper takes every parameter of its halves.** `assemble_and_run`,
   `assemble_and_debug` and `assemble_and_run_test_output` gain:
   - from `assemble`: `table_pool`, `defines_file`, the lzma option;
   - from `run` / `debug`: `flat_memory`, `flat_required`, `profile`, `flat_max_words`.

   `run_test_output` gains `flat_required` and `profile`. A unit test pins it: each helper's parameters cover its
   halves', except the output paths.
2. **`-f` / `--flags` stays removed.** `--run-flags` and `--io-mode` replace it, and so do the Writer's
   `run_flags=` / `io_mode=`.
3. **lzma: one name in both the command line and Python.** `--lzma_preset` / `lzma_preset=`; Python's `lzma_fast`
   is in question (see the update log).
4. **The table pool moves to `flipjump/assembler/table_pool.py`.** `TablePool`, `BlockPool`, `BlockCensus`,
   `DeferredTables` and their helpers move unchanged and are re-imported from `preprocessor.py`, so existing
   imports keep working. It is reachable:
   - in Python, as it is today (`table_pool=`);
   - from the command line, through **one simplified option** with defaults that work on any program (designed in
     round 1b; it refuses with an exact reason where a pool cannot be used, for example a program that reads cells
     through `hex.pointers`).

**The baseline moves (gap 5).** When stl work merges into 1.5.1 and then into `cr-main`, re-save
`crmain_base.json` at that merge commit, before the next fixer round.

---

## 7. After the plan: fjdoom's other branches, shipping, launch

- `w2fix-wip` (`6d940630`) and `soultele-wip` (`9d9297ee`) merge into `m8-episode` after `stl-adopt`. Their
  binaries are rebuilt there. What each level needs is `docs/levels/STATUS.md`.
- **The launch chain (Nov 5):**
  1. the owner's review;
  2. 1.5.1 → `main`;
  3. a flipjump release on PyPI;
  4. E1M1 re-shipped on the released flipjump;
  5. the README's play command updated.

  The slack is thin. After step 2 the README and `docs/story.md` must not name a binary the released flipjump
  cannot run.

---

## 8. Proof tools (each one ships its negative control)

| tool | proves | control |
|---|---|---|
| `scratchpad/ioapi/cr/fjm_identity.py <wt> --save/--check base.json` | every flipjump test program assembles byte-identical | `--mutate`: a one-op change to `hex.not` must be caught |
| `scratchpad/cr/emit_baseline.py --check` | E1M1's emitted parts are unchanged (a change in them must be on purpose) | its two emitter-constant mutants |
| doom gates (`m3`, `m2_std`, `p2a`, `hurt`, `fight`, `die`, B0) | byte-, state- and palette-exact against the oracle | each gate's own CONTROL lines |
| `scratchpad/ioapi/window_smoke.py` | the real pygame window shows the same frames as the headless run | — |
| `scratchpad/12m/msframe.py` | ms/frame A/B (the only speed verdict) | `--selftest` (A vs A) |
| `scratchpad/12m/gamespeed.py --validate` | the owner's two targets: binding ≤ 22M, size | — |

Every heavy run goes through `scripts/heavy.py` (one at a time; `--build` for assemblies). Subagents count.

---

## 9. Known gaps and their fixes (agreed 2026-10-24)

| # | gap | fix | status |
|---|---|---|---|
| 1 | The level chain tested the pre-cleanup device | `flipjump-io` fast-forwarded to merged 1.5.1 after E1M2 | ✅ |
| 2 | Pin / heat files are keyed by label names that the adoption renames | regenerate them (4b); judge speed by ms/frame, not ops | ⏳ |
| 3 | 2^27 hard limit vs `pad 16` | size per level right after adoption (4e) | ⏳ |
| 4 | E1M8/E1M9 have known failures | "no new failure" rule (4d) | ⏳ |
| 5 | The `cr-main` identity baseline moves when 1.5.1 changes | re-save at each merge point | ⏳ |
| 6 | Frozen op-count baselines break by design | re-freeze with the reason (4c) | ⏳ |
| 7 | Not enough agent slots (max 2) | implementer + one review-loop agent in parallel; the rest queue | in force |
| 8 | Every level built twice | phase 1 folded after E1M2 (owner) | ✅ |
| 9 | One heavy queue | priorities: ship #1 > adoption checks > 4d; msframe only on a quiet box | in force |
| 10 | Part C / byte output would skip the review loop | each gets its own short loop (byte output: closed, nothing to merge) | ⏳ C |
| 11 | Re-shipping E1M1 + the launch | ship #1 now, ship #2 after the adoption (owner); the README after `main` | ▶ |
| 12 | fjdoom branch merge order | section 1's git rule | in force |

---

## 10. Timeline (estimates; rewritten whenever a step lands)

Estimated 2026-10-24 01:00, Sat. Each estimate assumes nothing big breaks; one gate failure costs ~1.5 h per level.

| step | runs beside | done around |
|---|---|---|
| 1f–1h E1M1 ship #1 + PR io-api | everything (heavy queue) | Sat ~06:00 (CI ~2 h more) |
| 3a–3c stl additions (agent slot 1) | 6 | Sat ~12:00 |
| 6b–6e review loop, non-stl areas (agent slot 2) | 3, 4 | Sun ~evening |
| 3g + 4 (A2–A8, 4b–4h) | 6 | Sun ~22:00 – Mon morning |
| 5 merge `stl-additions` into 1.5.1 | — | Mon ~00:00–06:00 |
| 6f stl area, 6g final proof | — | Mon ~10:00 |
| 3d–3e part C + its testing phase → 1.5.1 | the owner's review | Mon ~14:00+ |
| **The owner's manual review can start** | | **non-stl: Sun evening – Mon; whole branch: Mon** |

---

## 11. Update log

| when | change |
|---|---|
| 2026-10-24 ~01:30 | written from the night's decisions. Status: #374 + #375 merged (1.5.1 = 9f6119c); E1M1 + E1M2 green on the API; part A committed; A1 text done; byte output closed; area 1 round 1 reviewed (4 BLOCKING / 31 MINOR); ship #1 rebuild running |
| 2026-10-24 ~03:00 | ship #1: rebuild BYTE-IDENTICAL (f52751a2bb846c7a); gamespeed re-run (`--validate` only checks the tours); msframe refused a busy box, so it waits for a quiet window. STATUS.md for E1M3-E1M9 written (30fb0a29). Owner's API decisions 1-4 recorded in 6 (round 1b). lzma question open: `lzma_fast` is the match finder, not a preset; fjdoom builds with it, and the shipped bytes depend on it |
