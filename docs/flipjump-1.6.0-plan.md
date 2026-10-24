# The flipjump plan: the new screen/keyboard API, the stl additions, and 1.6.0 → main

The owner's plan, agreed over the night of 2026-10-23/24. The executor (Claude) **follows it and updates it as
work lands**. Each step has a status, what it touches, how it is proven, and when it is done. Every change is
recorded in the update log at the end.

Status marks: ✅ done · ▶ running · ⏳ next / queued · ⏸ paused · ✖ dropped.

It lives in the doom repo, not in flipjump, so the 1.6.0 → `main` diff the owner reviews stays clean.

---

## THE RULE FOR EVERY CHANGE (owner, 2026-10-24)

- Correctness first, then speed (measured), then the SMALLEST diff vs main that keeps both.
- Design the smallest diff BEFORE implementing: reuse main's code paths; no renames, refactors, moved code or new
  files unless unavoidable; main's names, style and function length.
- Every report shows `git diff --stat main...` per file, before and after.
- Reviewers block on "could this be smaller?".
- A conflict between them goes to the owner, in numbers.

## RESUME HERE (paused 2026-10-24 ~12:30 for a Claude update)

Every agent was paused. Each wrote its state to a file. Resume each piece with a NEW agent that reads its file:

| work | branch / head | state file | next |
|---|---|---|---|
| stl review fixes: the corrected Complexity front-line table (owner rules: no "~", only n-terms, space with @ = emitted ops incl. wflip chains, a numeric derivation per row), the new macros' lines, part C's n<1 guard | `stl-additions` / `stl-seq-ptr` (flipjump-chain) | `C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/ioapi/cr/stl_STATUS.md` | FIRST the owner's additions at the end of stl_STATUS.md: a wflip's space follows its value's alignment (@/2 − 2 for a `pad 16` address), and reconstruct how every FORMER line was derived before writing new ones (same conventions); MEASURE the chained step's wflip (`start^return`, the XOR of two nearby pad-16 addresses: mean / median / p90 / max popcount), use that trusted number, and add one line about it to `stl/README.md` under "Documentation & Complexities". Then publish the table to `docs/flipjump-complexity-frontline.md` |
| table-pool gap hunt, round 3 | `pool-relocatable` 640532c (worktree flipjump-hunt) | `C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/ioapi/cr/hunt/round3/STATUS.md` | finish round 3; if no BLOCKING, the hunt closes → `.fjm` v4 (`C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/ioapi/cr/fjm_v4_spec.md`) |
| fjdoom adoption A1–A8 | doom `stl-adopt` d6a20a52 (doom-stl) | this plan, section 4 | 4b pins, A10 presets, 4d all levels |
| E1M1 ship #1 | doom `io-api` (doom-io) | this plan, 1f | msframe A/B vs blocked63 on a quiet box, then 1g/1h |

Specs: `C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/ioapi/cr/` (relocatable_spec.md, fjm_v4_spec.md, stl_audit_spec.md, main_area1_round1b.md). The CR loop
baseline is `C:/Users/tomhe/AppData/Local/Temp/claude/C--Users-tomhe-Documents-doom-flipjump/29ddbecf-cbb7-4734-805a-36c0e391327d/scratchpad/ioapi/cr/crmain_base.json`. Pinned stl for adoption checks: flipjump-stlpin (detached; advance it to the
committed stl head; it needs `_fjcore.pyd` copied).

## 0. The goal and the owner's order

**The end point:** the owner's manual review of flipjump `1.6.0` into `main`. By then 1.6.0 holds:

- the new screen/keyboard API;
- the stl additions taken from fjdoom;
- a branch already cleaned by a review loop under the owner's five rules.

fjdoom must run on all of it, and it must already use every macro that moved into the stl.

**The owner's order (2026-10-24, revised at 00:30):**

1. E1M1 works on the new API, and the other levels follow in parallel. **Phase 1.**
2. io-api is merged into 1.6.0 after a review loop. **Phase 2, ✅.**
3. A `stl-additions` branch from 1.6.0 takes every macro we discussed: `fixed_mul` and its family, `read_entry`,
   `hex.switch`, `screen.fj`, the keyboard poll, `write_back` / `read_back`, `ptr_index n`, and the chained table
   dance. It is written to the standard of the classic stl. **Phase 3.**
4. fjdoom adopts each macro as soon as it lands. **Anything that moves into the stl is removed from fjdoom
   completely:** no copy, no reference to the old name or the old implementation. **Phase 4.**
5. I merge `stl-additions` into 1.6.0 myself. **Phase 5.**
6. The review loop 1.6.0 → `main`, **without merging**; the owner reviews it by hand. **Phase 6.** It started on
   Saturday and runs the stl area last.
7. Part C (faster sequential pointer access) may merge into 1.6.0 **during** the owner's review, after its own
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
| `flipjump-151` | `1.6.0` | the INSTALLED flipjump (pip -e) | at `5af5923`. Not moved yet: blocked63 needs the old device until ship #1's A/B is done. |
| `flipjump-io` | `io-api` | the API work | fast-forwarded to `9f6119c` (= 1.6.0 after #375); junction `fjio-path` |
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

- Flipjump: `1.6.0` is the integration branch, and every change reaches it through a PR: `stl-additions`,
  `stl-seq-ptr` and `cr-main` each go into 1.6.0. Then the owner reviews 1.6.0 → `main`.
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
| 1f | **E1M1 ship #1**: rebuild byte-identical, `gamespeed`, msframe A/B vs blocked63 | ✅ msframe (selftest PASS, a quiet box): **B SLOWER, 67.7 → 70.2 ms (+3.7%)**, ratio 0.961, all 5 pairs; pixels identical; ops +0.44% (16,066,011 → 16,136,442); **fj/s −3.2%** (237.4M → 229.9M), so the price sits in the device/engine path, not the program. Class F (D8): recorded as the API's price, under the 90 ms tripwire. **Speed item → 6d:** profile the new device's output path against the old one. The first run was VOID: its selftest failed while git ran beside it. Rebuild **BYTE-IDENTICAL** (`f52751a2bb846c7a`); gamespeed binding **16,921,550 PASS** (mean 16,151,475, p80 17,691,624), size **39.13% PASS** (file 39,836,502 bytes). msframe waits for a quiet box (refused while agents ran) | blocked63's 16,892,755 / 38.98% come from ship-gate.md, UNVERIFIED here: +0.17% ops, +0.15 points of size |
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
merged 1.6.0 only after this A/B.

---

## 3. Phase 3: the `stl-additions` branch (flipjump, from 1.6.0)

**The standard (classic stl):**

- Same file layout, the stl's own `ns`/naming idiom, and a doc comment above every macro in the stl's style:
  - what it computes;
  - its complexity in ops and space;
  - its preconditions;
  - what it clobbers.
- Every macro has hexlib tests in `tests/` (`tests/inout/hexlib*` + `conftest` tables, as the existing ones are
  written).
- `stl/README.md`, `stl/hex/README.md` and `conf.json` are updated.
- Every change runs `fjm_identity.py --check` against the 1.6.0 baseline:
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
- It gets its own short review loop, then a PR into 1.6.0. It may land **during** the owner's review.
- **3e, the independent testing phase (2026-10-24): CORRECT.**
  - 22,552 cases (880 random multi-step programs + 21,672 exhaustive carry-boundary windows at w=32/64, n = 1–32),
    all equal to pre-C and to a Python model; every mutation control is caught.
  - **Faster:** 0.13–0.75× the ops.
  - **Smaller in all 72 configurations:** −818 ops/call at n=1; about 38% smaller at n=32, w=32.
  - **One regression:** n = 0 used to fail to assemble and now silently corrupts. The fix (reject n < 1) is queued to
    the implementer; aliasing the pointer variable gets documented as undefined.
  - **Recommendation:** merge C after that fix.

### 3f. Byte output ✅ closed: no change to the stl

The stl's `hex.output` is already the best variant: 34–38 ops/byte. fjdoom's `byte.emit` costs 74–83 and is ~1.25×
slower. The shared-table and `pad 64` variants lose. The consequence is an **adoption item** (A8):
`byte.emit` → `hex.output` on the low then the high nibble, judged by msframe (it adds about 8 ops of space per
call site).

### 3h0-final. CONVERGE (owner, 2026-10-24): one more fix round, one final review, done

1. **Hunt round 3 finishes its runs** (the corpus, the 600-case fuzzer and its controls) with no new attack work,
   so every finding is known.
2. **ONE fix round:** round 3's open cases (r3a/b/c number and bitwise arms, r3e an offset across a realigned pad,
   r3g `(L|0)+15*dw`), everything the corpus and fuzzer add, AND 3h0b (the pool under `--flat-max-words`). Every
   fix comes with its test.
3. **ONE final review:** it confirms every fix and runs the corpus and fuzzer once.
   - Any silent divergence it finds is fixed and tested in that same pass, with no further hunt round.
   - MINOR items become follow-up issues.
   - The pool is then closed → v4.

### 3h0b. The pool and flat memory (owner, 2026-10-24) ⏳ after hunt round 3's fixes

The spec is `scratchpad/ioapi/cr/pool_flat_spec.md`.

- **The pool's maximum is `--flat-max-words`** (no new option). Its default is the automatic-flat threshold.
- **The default base is the first 2^k above the program**, falling back to compact if the pool does not fit.
- **Tables that do not fit stay inline**, counted.
- **Python:** `flat_max_words` drives the pool too (`BlockPool.for_flat`); the combined helpers pass theirs.
- **The proof:** w=64 + `--pool-tables` + flat runs flat, identical to the build without the pool.

### 3h1. Which tables to declare: by MERIT, not all (owner, 2026-10-24) ⏳ after hunt round 3

The owner: relocate the tables the program spends its time in. Not too many; the ones with the most merit.

**Candidates** (beyond today's 8 + `hex.switch`):

- hex: `output`, `print_as_digit`, `if_flags`, `inc1`, `dec1`, `add_count_bits`, `input_hex`, `input_as_hex`, `div`,
  `add_mul`, `cmp`;
- bit: `if`, `exact_xor`, `double_exact_xor`, `output`, `exact_xor_from_ptr`.

**Method:**

1. **A profile of real work:** fjdoom's E1M1 played frames (`profx`, per-label executed ops on the current binary)
   and the hexlib suite as a generic check. For each candidate, measure:
   - its dispatches per frame;
   - the ops each dispatch spends on arming and disarming today (2 × popcount of the table address);
   - the saving if relocated, i.e. the popcount after placement, estimated by the census predictor.
2. **Merit = dispatches × saving per dispatch.** The cost side is pool span and segments; each declared table
   competes for slots.
3. **Rank, then declare top-down, one at a time.** Each one is proved: byte-identical without the pool, the
   relocation proof, the fuzzer, then fjdoom's msframe. Stop when the next one no longer separates in msframe
   (`docs/measurement-process.md` verdict rule).

Expected first: `hex.output`, whose switch has been inline at 41 byte-output sites since A8.

### 3h. `.fjm` version 4: the segment table compressed too (owner, 2026-10-24) ⏳

Branch `fjm-compressed-segments`, taken from `cr-main` after round 1b, with a PR into 1.6.0. It may land during the
owner's review. The spec is `scratchpad/ioapi/cr/fjm_v4_spec.md`.

**Why.** Measured on blocked64:

- 550,498 segments × 32 bytes = **17.6 MB stored raw, 44% of the file**. The table pool makes one segment per
  placed table.
- Compressed at preset 6 they take **0.62 MB**.
- The shipped file would go from 39.8 MB to about **18.5 MB** at preset 6.

**What:**

- version 4 = version 3 plus a compressed segment stream, separate from the data stream, so a header-only read stays
  cheap;
- the default version becomes 4; versions 0–3 stay readable.

**Proof:**

- decode-equivalence of every test program, v4 against v3, with an R9 control;
- a new identity baseline;
- unit tests at every width;
- fjdoom's header readers (`build._span_words`) still work.

**Bug fixed with it (round 1b section 5, also on `main`):** `--lzma_preset 7..9` wrote a `.fjm` the reader could not
read. The reader passed no `dict_size`, so it decoded with 8 MiB. The decoder now uses a 64 MiB dictionary.

### 3h0. The table pool's gap hunt (owner, 2026-10-24): BEFORE v4 ⏳

The owner: the pool works today because it moves only the tables of 9 whitelisted stl macros, which must not change.
It has many gaps; find them and fix them, and keep the speedup.

**The owner's design (2026-10-24): declared tables.** The spec is `scratchpad/ioapi/cr/relocatable_spec.md`, on branch
`pool-relocatable` from `cr-main` after round 1b.

- **What a table is:** the expansion of a macro whose INNERMOST namespace is `__relocatable__`. Its first argument
  is the table's start label.
- **Errors, with the pool on (`--pool-tables` / `table_pool=`):**
  - a `$` inside a relocatable (fall-through included);
  - a start label not at the start;
  - no `pad` right before the call.
- **No call-site check.**
- **Alignment** comes from the outer macro's `pad` just before the call.
- **Removed:** the shape detector `_table_run` and `wants=`, deleted with no fallback.
- **The stl:** the 8 table macros on `cr-main` declare their tables, plus `hex.switch` on `stl-additions` (9 in
  all), with byte-identical output without the pool.
- **The command line:** `--pool-tables`, with plain `--help` and docstrings.
- **The relocation proof:** plain build vs pooled build, every op at its mapped address with mapped targets, plus a
  negative control.

**Done (2026-10-24):** `pool-relocatable` was pushed in 3 commits (`0f049f6`, `b1363d7`, `97a99bd`).

- **Byte-identical without the pool, 117/117;** every suite passes.
- **Same placement as the old detector** on all 8 macros, at w=32 and w=64.
- **Stricter than the spec:** with the pool on, a `wflip` or a `rep` / macro call inside a relocatable is a compile
  error.
- **`--pool-tables`:**
  - it is a one-pass BlockPool based at half the memory;
  - it refuses a program that reaches the upper half;
  - it refuses a program that reads cells through `hex.pointers`, because there is no safe default `pin_exclude`.
- **The relocation proof:**
  - 74 programs prove equal; its controls catch a corrupted op and a table one op short;
  - it catches `before + 2*dw`, which really miscompiles;
  - it found the fjdoom render tier equal (36,033 tables, 0 mismatches).
  - **Its limits:** it skips operands computed from addresses, and it does NOT verify pinning.
- **fjdoom follow-ups:**
  - `wants=` / `--macros` removed from the drivers and tests;
  - `sim.jump16` → `hex.switch` must be DECLARED on `stl-additions`, or its tables stop moving (speed!);
  - `lzma_fast` → `lzma_preset` (A10).

**Gap hunt, round 1 (2026-10-24): 9 BLOCKING, 9 MINOR** (`scratchpad/ioapi/cr/hunt/hunt_findings.md`).

- **The fuzzer found no difference in 300 random stl-only programs** (w=16/32/64, 6 pool variants, 8,719 tables
  moved). Both of its controls fire.
- **Every corruption came from a crafted program:**
  - B1–B4 are BlockPool pinning:
    - a pointer reader not on `RAW_READERS`;
    - the `pinned_floor` heuristic;
    - a pinned word inside a `reserve` region;
    - an XOR retarget of a pinned word.
  - B5: a table leaving its end through label arithmetic, checked only by the proof, not by the product;
  - B6: a non-power-of-two `pad`.
- **The proof's limits:**
  - B7: an operand it cannot evaluate is skipped silently;
  - B8: pinning is unchecked;
  - B9: false positives.
- **The MINOR ones:**
  - M1–M3: late, reasonless overlap errors;
  - M4: pool reuse;
  - M5: flat memory at w=64;
  - M6: the `__relocatable__` name undocumented;
  - M7: the docs overclaim;
  - M8: TablePool spill space;
  - M9: a w=16 `OverflowError`.

**All of them go to the fixer:**

- each crafted program becomes a unit test, running identically or refused with a reason;
- the fuzzer goes into `tests/`;
- fjdoom's exposure is checked per finding.

**Fixed (97a99bd..02fcb63).** All 18 findings are closed.

- The fixed-word (pin) checks work by mechanism, not by name list.
- The B5 and B6 compile errors are in.
- The proof checks pins and counts what it cannot check, with no false positives.
- Overlaps are refused early.
- An `OffsetGuard` in the PRODUCT refuses an outside label + offset into a moved table (c06, c07a–d), with a run
  negative control. Its cost: labels resolve ×1.28, about +2 s on fjdoom's 94 s render-tier assembly.
- The fuzzer and the 21 crafted programs are in `tests/`.
- Identity 117/117; every suite passes.
- The fjdoom render tier with the pool: 0 refusals over 36,033 tables, the `.fjm` identical.

**fjdoom exposure of the shipped build:**

| finding | shipped build |
|---|---|
| B2, B3, B4, B5 | not exposed |
| B1 | protected only by fjdoom's hand-kept `POINTER_READ_CELLS` veto list plus its exact gates |

**Hunt round 2 (2026-10-24):** every round-1 finding is confirmed closed. **6 new BLOCKING, 2 MINOR**
(`scratchpad/ioapi/cr/hunt/round2/hunt_findings_r2.md`), each needing code the stl's macros never emit:

- N1: `$`-relative jumps across a moved table;
- N2: computed label operands spanning a table. The repo's own `print_address_difference.fj` differs under
  TablePool;
- N3: a table label passed as an argument;
- N4: a numeric address armed into a pinned word;
- N5: bit-flip arms of a pinned word;
- N6: the proof's remaining blind spots;
- N7: correct programs refused, with a remedy the CLI cannot apply;
- N8: a misleading message.

**Corpus and fuzzer:**

- The repo corpus: 1,127 programs.
- The fuzzer: 600 cases, 8 pools, both controls fire. It found 0 differences.

**The principle given to the fixer:** never change behaviour; prefer a safe FALLBACK (un-pin, decline) over refusing;
refuse only when there is none; count and report every fallback.

**Fixed (02fcb63..640532c):** N1–N8.

- **Fallbacks:** a table is kept inline when an operand reaches across it; a word is un-pinned where it is armed in
  ways the pool cannot rewrite. Both are counted.
- **The proof** checks numbers and sums, holds per-program ceilings on its unchecked operands, and judges pins from
  the image.
- **The corpus:** 1,125 of 1,127 run the same, 2 are refused exactly, 0 differ.
- **The fjdoom render tier** (with its veto list): 0 refusals, 0 kept inline, 0 un-pinned; 2,138 pins kept.
  `fj --pool-tables`, which has no veto list, un-pins every word for the pointer runtime.

**Hunt round 3 is running.** Then v4.

Then the rest of the gap hunt below.

**Goal.** The pool's safety holds by CHECKS, not by the whitelist. The whitelist stays as policy, not as the
safety net.

1. **Write the safety contract** at the top of `table_pool.py`: exactly what must hold for a run of ops to be moved,
   and for a jump word to be pinned.
2. **Adversarial gap hunt.** A fresh reviewer, not the fixer, sets every assumption in the code against the
   contract. Seeds:
   - an outside label + offset that addresses into a moved run (already in round 1b);
   - `pool_base` overlapping the program ("nothing here checks that", TablePool's docstring);
   - pin safety resting on a caller-supplied `pin_exclude` that "may veto nothing", plus the name list
     `RAW_READERS`;
   - writes into table code through pointers (only reads are guarded);
   - alignment / XOR == ADD on block bases;
   - tables longer than their run (spill);
   - debug info and breakpoints for moved labels;
   - memory widths 8, 16 and 64;
   - user macros named like stl ones;
   - stale census caches.
3. **A differential fuzzer.** Random programs built from every stl table macro (not only the 9), assembled without a
   pool and with each pool mode, then run. Outputs and termination must be equal. It ships with mutation controls,
   e.g. disabling a check must make a crafted program differ.
4. **Each gap closes one of two ways:**
   - a check that refuses or declines, with the exact reason;
   - or a test proving the gap cannot occur.

**Kill criterion:** fjdoom keeps its speed. E1M1 must rebuild byte-identical, or, if placement legitimately
changes, msframe must not say B SLOWER.

### 3i. Mission, later: the smallest shipped `.fjm` (owner, 2026-10-24)

Compress the FINAL ship binaries as far as they go, and research more than the preset. Candidates, each measured on
the shipped image (size, write time, load time, round trip):

- `PRESET_EXTREME`;
- the dictionary at least the image size;
- `lc` / `lp` / `pb` tuned to the op structure (an op is 2w bits: `pb` / `lp` = log2 of its bytes);
- `FILTER_DELTA` (`dist` = the word bytes) before LZMA2;
- separating the flip words from the jump words (a column transform, as a new format version);
- the segment order;
- `nice_len` / `depth`.

What ships is decided by the measurement. Load time must not grow noticeably.

### 3g. The review loop on `stl-additions` ▶

**Round 1 (2026-10-24): 5 BLOCKING, 14 MINOR, 6 test gaps** (`scratchpad/ioapi/cr/stl_round1.md`).

- **BLOCKING:**
  - `ptr_index n` with `dst == index` on the wide path: fixed in the code;
  - n = 0 regressions in add/sub n, the shifted forms and add_mul n (they write before `dst`);
  - the `fixed_mul_low` test cannot catch a missing write;
  - `hex.mul.clear_carry` is public but untested;
  - `fixed_div`'s Complexity line is ~4× high.
- **Kept by my call:** the top-level `screen` namespace, because fjdoom already uses `screen.*` and it is what the
  owner asked for.
- **Taken:** `set_window_title` → `stl.output text`, plus a `draw_raw` header macro.

The implementer is fixing all of it on `stl-additions`, merged into `stl-seq-ptr`.

**Owner addition (2026-10-24), part of this round:** NEW macros are documented fully, from MEASUREMENT.

**Existing macros' Complexity lines are NOT edited directly (owner).** Instead, a FRONT-LINE table goes to the owner
(`scratchpad/ioapi/cr/complexity_frontline.md`):

- it holds only the macros whose OWN cost changed or whose doc is wrong, not their callers;
- each row has the measured values and a verified reason.

After acceptance, the accepted lines and every dependent's line are updated, transitively. The same rule holds for
the whole-stl audit (3g2). That includes the chained ops, part C's pointer ops, the moved macros, and
the 8 table macros that now declare `__relocatable__` (on `pool-relocatable`).

### 3g1. The complexity table → applied (owner, 2026-10-24) ▶

The owner's conventions, all in force:

- main is the baseline;
- a wflip costs the popcount of its VALUE (@/2; pad-2^k: @/2 − k/2; init labels: a constant; the chained step: 2);
- no shared tails; pads not counted;
- no "~"; n-terms only;
- old → new derivations in numbers.

The chained ops save about @−2 a hex in time AND space (or n: 4@+52 → 3@+54).

**Order (owner):**

1. Finish the table.
2. Re-check every number and fix it ourselves (the agent, then an independent checker).
3. Apply it to the code: the front-line macros AND every macro that uses them, transitively (a dependency closure).
   Docs only, so every program stays byte-identical (`fjm_identity`).

### 3g2. The whole-stl audit (owner, 2026-10-24) ⏳ after 3g round 1

Every one of the stl's **382 macros** is checked for:

- bugs;
- unhandled or undocumented edge cases;
- an incorrect time/space complexity;
- untested behaviour (named mutants the tests miss).

The spec is `scratchpad/ioapi/cr/stl_audit_spec.md`.

- **Step 0:** a measurement tool `stl_measure.py`, with time per call from executed ops, space per call from k vs
  k+1 images, and an R9 selftest.
- **6 batches**, each a fresh reviewer then the fixer:
  1. runlib / ptrlib / casting / bit memory;
  2. bit/;
  3. hex logics / math / shifts / tables;
  4. hex mul / div / cond_jumps / memory / io / strings;
  5. hex pointers;
  6. screen + cross-cutting checks.
- **Every fix** comes with its test plus a mutant. Programs not using a changed macro stay byte-identical.
- **Estimate: ~1–1.5 days.** It runs after 3g round 1, and it moves phase 5 (the merge into 1.6.0) and the stl area
  of 6 later.

The owner's five rules (section 6) are applied to the new stl code until a round is clean. Then the PR
`stl-additions` → 1.6.0, which I merge (phase 5).

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
| A10 | `FJM_LZMA_FAST` (harness.py) → `lzma_preset`: **preset 1 for day-to-day builds** (13.4 s against `lzma_fast`'s 17.8 s, the same size) and **preset 6 for ship builds**: −10.8% today. Presets 7, 8 and 9 measured −11.1%, −10.9% and −10.9%, no real gain, and they need the fixed reader; preset 6 is readable by every reader. On a quiet box: fast 6.0 s, preset 6 58 s, load 1.03–1.14 s for all. Measured on blocked64, with the control: `lzma_fast` reproduces the stored blob byte for byte | ⏳ after round 1b |
| A11 | fjdoom's header readers (`build._span_words`, `measure_frame`, tools) on `.fjm` v4; the ship builds write v4 | ⏳ after 3h |
| A2 | `fixed_point.fj` deleted → `hex.fixed_mul/div`, `mul_low`, `fixed_mul_low`, `mul_const` | ✅ `79a45aa2` |
| A3 | `read_table*` → `hex.read_entry*` | ✅ `fef88048` |
| A4 | `frame.ptr_index4/5/6` + `ptr_index_fill` → `hex.ptr_index n` | ✅ `a19ef32a`. Found an stl gap: the wide path breaks when `dst == index` (fixed in 3g) |
| A5 | `sim.jump16` → `hex.switch` | ✅ `03008c34` (`SAFE_TABLE_MACROS` → `hex.switch`) |
| A6 | `present.fj` deleted → `stl/screen.fj`; `input.fj` → the stl poll + its bindings | ✅ `9f44d10a` (`end_frame W, 0` prints the same 0xFF 0x1F) |
| A7 | `frame.write_byte_prearmed` → `hex.write_back` (and `read_back` where a prearmed read exists) | ✅ `9b4397cc`: 3 `write_back` sites; 0 `read_back` sites qualify (all follow an `_and_inc`) |
| A8 | `byte.emit` (lut_generator) → `hex.output` low + high nibble | ✅ `686f3ecb` (`hex.print`). Note: `hex.output`'s switch is not a declared table yet, a candidate for `__relocatable__` |
| A9 | Part C's sequential access, where fjdoom walks arrays | ⏳ after 3e |

**Interim E1M1 build after A1–A8 (2026-10-24):** `build/doom_e1m1_adopt1.fjm`, with the OLD heat/census pins.

- m3 88, m2 421 and p2a: PASS.
- gamespeed binding **16,180,820** against blocked64's 16,921,550 (both measured this session): **−4.4% ops**.
- Size **37.95%** (blocked64: 39.13%).
- **Not a speed verdict yet:** that needs msframe on a quiet machine, after 4b's pins are regenerated.
- A1's leftovers in tracked scratchpad were removed (`d6a20a52`).

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

## 5. Phase 5: `stl-additions` into 1.6.0

- I merge it after 3g is clean and 4d is green.
- Then the installed `flipjump-151` fast-forwards to the merged 1.6.0, after ship #1's A/B has been recorded.
- The `cr-main` identity baseline is re-saved at this merge point (gap 5).

---

## 6. Phase 6: the review loop, 1.6.0 → `main` (no merge)

Branch `cr-main` from 1.6.0 (`9f6119c`), worktree `flipjump-crmain`.

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
| 6b | Assembler + blocking pass | ✅ round 1 (`87bcd35`): 4 BLOCKING + 29 MINOR fixed (S2 skipped, +2.1% slower); round 1b (`37fffc5`): all helpers take all flags, `lzma_fast` gone, `lzma_preset` 7–9 readable (8 MiB, then retry at 64 MiB), the pool moved to `table_pool.py` (preprocessor diff 2,023 → 620). Identity BYTE-IDENTICAL 117/117 | next: `pool-relocatable` (3h0), then the gap hunt, then v4 |
| 6c | Native engine, interpreter, CLI | ⏳ | — |
| 6d | IO devices (1.6.0's earlier changes; #375 is already clean) | ⏳ | — |
| 6e | Tests + programs | ⏳ | — |
| 6f | **stl, last**, after phase 5 | ⏳ | — |
| 6x | **Genericity sweep (owner, 2026-10-24)**, cross-cutting, everything 1.6.0 adds plus the stl branches. **(1) A scan:** fjdoom / DOOM / map words; hard-coded widths (32, `w == 32`, `1<<27`, `0x80000000`); fjdoom-tuned sizes and thresholds (span, slot caps, chunk sizes, `16*2*w`, the 2^24 flat threshold); one-device / one-io-mode logic outside the device's module; fjdoom-only defaults (pin heat, spread, census); fjdoom-numbers justifications in comments. **(2) A read-through per hit:** generalise (from `w` / a parameter, tested at w=16/32/64), document as legitimately specific, or reword. **(3) Fixes** on the owning branch, byte-identical without the pool | ✅ the scan (2026-10-24), `scratchpad/ioapi/cr/generic/generic_findings.md`. **No code path checks `w == 32` or a fjdoom name.** G1: 13 fjdoom-justified comments left on cr-main (README, fjm reader/writer, `_fjcore.c`, fjm_run) → 6c; G2/G7 the devices' examples → 6d; G3 `RESERVED_BELOW = 1024` (w-independent?) and G4 fjdoom-tuned pool defaults → the pool's final fix round; G5 the 2^24 flat threshold's reason → 6c; G6 → the stl agent; G8 the design read-through (engine freeze API, pool heat/census knobs, draw_collines) → 6c/6d | — |
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

**The baseline moves (gap 5).** When stl work merges into 1.6.0 and then into `cr-main`, re-save
`crmain_base.json` at that merge commit, before the next fixer round.

---

## 7. After the plan: fjdoom's other branches, shipping, launch

- `w2fix-wip` (`6d940630`) and `soultele-wip` (`9d9297ee`) merge into `m8-episode` after `stl-adopt`. Their
  binaries are rebuilt there. What each level needs is `docs/levels/STATUS.md`.
- **The launch chain (Nov 5):**
  1. the owner's review;
  2. 1.6.0 → `main`;
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
| 1 | The level chain tested the pre-cleanup device | `flipjump-io` fast-forwarded to merged 1.6.0 after E1M2 | ✅ |
| 2 | Pin / heat files are keyed by label names that the adoption renames | regenerate them (4b); judge speed by ms/frame, not ops | ⏳ |
| 3 | 2^27 hard limit vs `pad 16` | size per level right after adoption (4e) | ⏳ |
| 4 | E1M8/E1M9 have known failures | "no new failure" rule (4d) | ⏳ |
| 5 | The `cr-main` identity baseline moves when 1.6.0 changes | re-save at each merge point | ⏳ |
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
| 5 merge `stl-additions` into 1.6.0 | — | Mon ~00:00–06:00 |
| 6f stl area, 6g final proof | — | Mon ~10:00 |
| 3d–3e part C + its testing phase → 1.6.0 | the owner's review | Mon ~14:00+ |
| **The owner's manual review can start** | | **non-stl: Sun evening – Mon; whole branch: Mon** |

---

## 11. Update log

| when | change |
|---|---|
| 2026-10-24 ~01:30 | written from the night's decisions. Status: #374 + #375 merged (1.6.0 = 9f6119c); E1M1 + E1M2 green on the API; part A committed; A1 text done; byte output closed; area 1 round 1 reviewed (4 BLOCKING / 31 MINOR); ship #1 rebuild running |
| 2026-10-24 ~03:00 | ship #1: rebuild BYTE-IDENTICAL (f52751a2bb846c7a); gamespeed re-run (`--validate` only checks the tours); msframe refused a busy box, so it waits for a quiet window. STATUS.md for E1M3-E1M9 written (30fb0a29). Owner's API decisions 1-4 recorded in 6 (round 1b). lzma question open: `lzma_fast` is the match finder, not a preset; fjdoom builds with it, and the shipped bytes depend on it |
| 2026-10-24 ~14:00 | **The version is 1.6.0** (owner), not 1.5.1. The branch `1.6.0` is at 87ba7aa (version bump + two comments); `1.5.1` is deleted once no CI clones it. fjdoom: PR #151 (main: CI pinned to 5af5923, docs say 1.6.0); `io-api`: CI pinned to 87ba7aa, `flipjump>=1.6.0`. This plan was renamed from `flipjump-151-plan.md` |
| 2026-10-24 ~19:00 | **At most 3 branches waiting (owner):** `cr-main` (rounds 1 + 1b) MERGED into 1.6.0 (#376, 6824a23; identity 117/117, unit 1156, run 1305); `stl-seq-ptr` folds into `stl-additions` (one stl branch); v4 and the flat work go on `pool-relocatable`; `io-api` and `cr-minimal` deleted (merged); `lever1-folds-measured`, the June planning branch and `block-pack` kept as `archive/*` tags. Audit batch 1: a real bug in `bit.ascii2hex` (it corrupts its input), 11 front-line rows, 9 missed mutants (`docs/flipjump-audit-batch1.md`) |
