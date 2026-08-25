# Handoff — M5 → M2 → M3 → M4 (owner's order, 2026-08-25)

**Start here.** Background in `docs/handoff-complete-game.md` (full roadmap) and
`docs/handoff-m1-reset.md` (M1 detail). This is the short version: what is true now, what to do
next, and the traps that have already cost a session each.

---

## 0. Where we are — M1 IS DONE, and it was the gate on everything

`build_wall_renderer(self_reset=True)` ships a program that restores itself and loops. The host no
longer reloads the image, so the ~52 ms memcpy that capped the game at **~19 fps regardless of
frame cost** is gone, and a standalone `.fjm` is possible at all.

Verified 2026-08-25 (commits `5a6be8d`, `f085cf1`, `232672e`, branch `m13opt3-early-out`):

| | |
|---|---|
| binary | `build/doom_e1m1_loop.fjm`, sha256 `4fad6d12...` |
| **mean whole frame, reset included** | **28,564,109 ops** (260-frame sweep, one run) |
| median frame (reference build) | 27,932,265 - **THE metric** |
| looping overhead | +262,063 = **+0.9%** of the median |
| restore set | 12,072 words / 448 entries, **ZERO `@`-local keys** |
| gates | M1 gate PASS (12 frames byte-exact) + `--selftest` PASS; `deg_gate` 4/4; **sweep 260/260 byte-exact** |
| tests | `tests/host` 287 passed; `tests/fj` 177 passed, 15 skipped |

**Never quote a percentage against gate viewpoints.** They overstate a typical frame by ~1.5x;
that error produced the retired "7.47%". The denominator is the sweep median above.

---

## 1. The rule that will bite you first

**RE-KEY the restore set. NEVER re-derive it from a measurement.**

It is a proven artifact; only its KEYS go stale. A measured set has holes by construction, and
**a hole does not draw wrong pixels - it HANGS the next frame.** Six builds were spent relearning
this. After any change that moves the layout (any `src/fj/` edit, any emitter change):

    bash scratchpad/_rekey_all.sh      # emit -> capture labels -> re-key -> re-attach globals
    bash scratchpad/_m1_finish.sh      # build -> M1 gate -> selftest -> host tests -> tool selftests

`_m1_finish.sh` stage 1 asserts zero `@`-local keys and no holes BEFORE spending 66 minutes on a
build. The two re-key steps are `ca_remap_set.py` then `m1_add_globals.py`, in that order.

Other rules that have already cost real time - details in `CLAUDE.md`:

- **ONE heavy build at a time** (memory exhaustion, not an assembler bug).
- **A shared-helper change is a FAN-OUT edit** - grep `src/`, `scratchpad/`, `tests/host` **and
  `tests/fj`**. Missing `tests/fj` shipped broken tests twice, once in the very commit titled
  "I missed tests/".
- Any program that expands a renderer macro **standalone** must call
  `wall_renderer.hoisted_scratch_fj()` - those macros name hoisted globals in their `<` lists.
- Detached processes do **not** inherit the interactive PATH. Name the interpreter explicitly, and
  verify a background job actually started before reporting it as running.

---

## 2. M5 - the standalone .fjm (no Python)   <- DO THIS FIRST

The smallest thing that converts M1 into the headline result. Everything it needed was M1.

- **Input** - no change; the flipjump input device already covers it.
- **Output** - **~35 lines in `ScreenIO.py`** for the 0x0B decoder. The "you control fj1.5.1" case.
- **The loop** - entirely M1, done.
- Cutting the distributable: flip `doomfj.harness.FJM_LZMA_FAST` to `False` - **21.8 MB instead of
  29.0 MB**, costs 93 s of build. Encoder-only, changes nothing but size.

**Done when:** the `.fjm` runs to a rendered, controllable frame with no Python in the loop, and
the M1 gate still passes.

---

## 3. M2 - doors (the fj half)

**The hard part is already done:** `scratchpad/door_gate.py` exists and is **non-vacuous**. Before
it, with every door and lift open, `deg_gate`'s four viewpoints rendered **0 px different** - the
repo could have shipped a completely broken door and every gate would have passed. Three door
viewpoints (2,720 / 2,664 / 693 px) now fail when they should.

Owed:

- a compile-time-addressed **dynamic height cell** for the 7.8% of segs touching door sectors;
- **16-unit quantisation -> 26 distinct heights**, which fits the one-byte pid budget (255
  available, 152 used);
- the `thing_live_subsectors` predicate fix - a closed door is `ceil_h <= floor_h`.

WARNING: **the door model was wrong once and the gate passed anyway.** Sweeping floor -> the wad's
ceiling is *zero movement* for a stored-shut door; the 1,451 px it reported came from a **lift**.
The rule is `P_DoorRaise`: a door opens to **`min(neighbouring sector ceiling) - 4`**.

Owner's constraint: **keep ops/frame at similar cost**, measured against the sweep median.

---

## 4. M3 - menu

Cheapest content milestone, and the first thing that genuinely *needs* the loop.

- Text output already exists (`stl.output_char`), so a menu is a different **frame producer**, not
  new machinery: a mode flag selecting menu-draw vs world-draw.
- Input already works (M14 rung 0). Needs a mode state and a transition.

---

## 5. M4 - three levels

**DECIDED**: three levels in one image (E1M1 + E1M5 + E1M8). The full 9-level episode is **OUT**.
If three does not fit, **scale down rather than push**.

WARNING: **the first task is NOT a build - it is re-deriving the budget.** "Three levels = 88.7% of
the 65,536 band-index cap" is a projection from an earlier session, **never re-measured against the
current emitter**, and 88.7% leaves only 11.3% of margin. If it is off by an eighth, three levels
does not fit - and you find out after a ~30-minute build instead of after an afternoon of
arithmetic. Re-derive the per-level band-index count first.

At 559 s for one E1M1 and roughly linear scaling, three levels projects to ~30 minutes of build.

---

## 6. Then M6 - ship

Re-certify all gates, re-run the 260-frame sweep, record the final median, tag, archive the binary.

---

## 7. Loose ends

- **The `stl.fcall` early-out check is still untaken** - cheap, needs no build, and this branch is
  literally named `m13opt3-early-out` for it. Take it or drop the name.
- **10 open findings** in `scratchpad/cr2/findings/`.
- `self_reset=False` has **not** been built on the post-hoist tree, so the reset part's own span is
  unmeasured (`DESIGN.md` 1.2 says so rather than estimating it).
- R7: the branch name does not match the milestone. Accepted, not renamed - 350+ commits are pushed.
