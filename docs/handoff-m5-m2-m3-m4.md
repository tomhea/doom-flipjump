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

## 2. M5 - the standalone .fjm (no Python)   <- DONE, 2026-08-25

    fj build/doom_e1m1_std.fjm --io pc --flat-max-words 134217728

That is DOOM, out of one file, with no Python in the loop. `--io pc` is the stock CLI mode: a
window for the pixels, live keys in. W/S or the up/down arrows walk, A/D or left/right turn.

This handoff predicted two things about M5 and got one of them right.

**RIGHT: "~35 lines in `ScreenIO.py`".** The shipping renderer presents COLUMN RUN-LISTS (0x0B) and
only this repo's lab device could decode them, so a binary handed to `fj` drew nothing. The decoder
is upstream now (flipjump-151 `19f7da5`): 50 lines of code, 35 of protocol docs.

**WRONG: "Input - no change; the flipjump input device already covers it".** MEASURED: a hosted
frame reads **887 bytes of stdin every frame** - 14 of player state, 600 of thing positions, 150 of
bindings, 123 of visibility flags - and echoes the new state back out. A keyboard device cannot
produce that, and no host exists to write it. *That* was M5, and it is what the `standalone=True`
tier is:

| | hosted | standalone |
|---|---|---|
| player state | read + echoed every frame | BAKED at the player start, then kept across the reset |
| keys | one byte on the wire | `kb.poll` x8, `src/fj/input.fj`, edge-driven persistent flags |
| thing bindings / visibility | fed per frame | baked (nothing moves things until C4) |
| screen init | `init_screen_stream 0` (9 bytes) | stock `init_screen` (8) - what `fj`'s device wants |
| state echo | `0x10` + `0x11` blocks | none |

**THE ONE PLACE A HOLE IN THE RESTORE SET IS THE INTENT.** `selfreset.emit_reset_part` gained
`persist=`, and `build.STANDALONE_PERSIST` names the seven labels the reset must LEAVE ALONE:
`viewx viewy viewangle kb_f kb_b kb_l kb_r`. Everything else about the frame is still residue and
is still restored. It is checked, not trusted: each name must exist in this build's own label table
AND carry cells in the set, or the build refuses.

**The standalone set is RE-KEYED, never re-measured** (section 1's rule). `scratchpad/m5_setfile.py`
takes the certified 448-entry set and makes exactly two edits: drop `wmagic` (no wire, no magic
byte - and the list of names allowed to disappear is CLOSED), and add the six `kb*` globals at
their declared width. Every surviving offset is re-checked against its label's span in the
STANDALONE layout before the fingerprint is recomputed. Result: **12,072 -> 12,082 words over
448 -> 453 entries.** Its `--selftest` has five controls, all refusing.

### The numbers, all measured this session

| | |
|---|---|
| `build/doom_e1m1_std.fjm` | 31,221,481 bytes, span 84,892,508 words, headroom 1.581x |
| M5 gate | **PASS** - 12 frames byte-exact in ONE 561,258,605-op run; `--selftest` PASS |
| smoke gate (no-loop build, spawn frame) | BYTE-EXACT vs the oracle at 39,157,887 ops |
| 0x0B decoder | 20 differential tests + 3 R9 negative controls; real-stream replay 3/3 byte-exact |
| `kb.poll` | 10 tests incl. the phase test and an R9 negative control |

### How it is gated

`scratchpad/m5_gate.py` is not like the gates before it: **nothing is fed in.** The program starts
at the player start it baked, and the only thing crossing the wire is KEY EVENTS. So the gate is
CUMULATIVE - a one-ulp drift in the sim, a wrong cell in the persist set or a mis-decoded keycode
sends the trajectory somewhere the oracle never goes and every later frame differs. The device is
the stock `PcIO` that `--io pc` builds, so what is certified is the object a human runs.

    python scratchpad/m5_gate.py --frames 12          # the real gate
    python scratchpad/m5_gate.py --selftest           # R9: corrupt one oracle frame, must FAIL
    python scratchpad/m5_gate.py --fjm build/doom_e1m1_std_noloop.fjm --smoke

It carries vacuity controls (frames that moved, turned, were changed by collision, and distinct
pictures) because a script that stood still would compare a dozen copies of one picture and pass.

### Rebuilding it

    python scratchpad/ca_labels.py --standalone --out scratchpad/_m5_labels_std.tsv.gz   # ~26 min
    python scratchpad/m5_setfile.py --labels scratchpad/_m5_labels_std.tsv.gz            # seconds
    python scratchpad/m5_build.py                                                        # 4,740 s
    python scratchpad/m5_gate.py --frames 12

`--no-reset` on `m5_build.py` gives the cheap intermediate: one frame, no loop, no restore set -
enough to prove the emit half without the two-pass build.

### Left open

- **The distributable is still the fast-LZMA one.** `doomfj.harness.FJM_LZMA_FAST = False` is
  encoder-only (the program is identical) and the handoff's "21.8 MB instead of 29.0 MB for 93 s"
  is UNVERIFIED for this binary. Cutting it costs a full rebuild, so it was not done for a size
  number nothing depends on yet. Do it when the artifact is actually shipped (M6).
- ⚠ **A finished build process holds its memory.** `m5_build.py` printed its metrics and then sat
  at 6.4 GB, and `ca_labels.py` at 6.9 GB, for minutes afterwards. Rule 1 is about PEAK RSS, and
  "the build printed its results" is NOT "the build released its memory" - check the process is
  gone, not just that the log is complete, before starting the next one.

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
