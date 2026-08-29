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

    fj build/doom_e1m1_menu.fjm --io pc --flat-max-words 134217728

⚠ `doom_e1m1_std.fjm` is the M5-era build and predates M3's `mode` cell, so it is no longer
what this source emits. `doom_e1m1_menu.fjm` supersedes it -- same tier, plus the menu.
(`build/` is gitignored, so a stale artifact there is a local-cache problem, not a shipped one.)

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
| `build/doom_e1m1_std.fjm` (M5-era; superseded) | 31,221,481 bytes, span 84,892,508 words, headroom 1.581x |
| M5 gate | **PASS** - 24 frames byte-exact in ONE 1,131,621,966-op run; `--selftest` PASS |
| what that run exercised | 13 frames MOVED, 8 TURNED, **5 blocked by COLLISION**, 20 of 24 pictures distinct |
| smoke gate (no-loop build, spawn frame) | BYTE-EXACT vs the oracle at 39,157,887 ops |
| 0x0B decoder | 20 differential tests + 3 R9 negative controls; real-stream replay 3/3 byte-exact |
| `kb.poll` | 10 tests incl. the phase test and an R9 negative control |

### How it is gated

`scratchpad/m5_gate.py` is not like the gates before it: **nothing is fed in.** The program starts
at the player start it baked, and the only thing crossing the wire is KEY EVENTS. So the gate is
CUMULATIVE - a one-ulp drift in the sim, a wrong cell in the persist set or a mis-decoded keycode
sends the trajectory somewhere the oracle never goes and every later frame differs. The device is
the stock `PcIO` that `--io pc` builds, so what is certified is the object a human runs.

    python scratchpad/m5_gate.py                      # the real gate (24 frames)
    python scratchpad/m5_gate.py --selftest           # R9: corrupt one oracle frame, must FAIL
    python scratchpad/m5_gate.py --fjm build/doom_e1m1_std_noloop.fjm --smoke

It carries vacuity controls (frames that moved, turned, were changed by COLLISION, and distinct
pictures) because a script that stood still would compare a dozen copies of one picture and pass.

!! THE COLLISION CONTROL EXISTS BECAUSE THE FIRST PASSING VERSION DID NOT HAVE IT. 24 frames, all
byte-exact, `frames COLLISION changed: 0` - the script crossed open courtyard the whole way, so
half the sim was uncovered and the gate said PASS. `scratchpad/_m2_findwall.py` searched every
heading from the spawn with the ORACLE alone (no renders, seconds) and found turn-right x4 blocks
soonest; the script now opens with it and the gate REFUSES a run that never hits geometry.

### Rebuilding it

    python scratchpad/ca_labels.py --standalone --out scratchpad/_m5_labels_std.tsv.gz   # ~26 min
    python scratchpad/m5_setfile.py --labels scratchpad/_m5_labels_std.tsv.gz            # seconds
    python scratchpad/m5_build.py                                                        # 4,740 s
    python scratchpad/m5_gate.py

`--no-reset` on `m5_build.py` gives the cheap intermediate: one frame, no loop, no restore set -
enough to prove the emit half without the two-pass build.

### Left open

- **The distributable is still the fast-LZMA one.** `doomfj.harness.FJM_LZMA_FAST = False` is
  encoder-only (the program is identical) and the handoff's "21.8 MB instead of 29.0 MB for 93 s"
  is UNVERIFIED for this binary. Cutting it costs a full rebuild, so it was not done for a size
  number nothing depends on yet. Do it when the artifact is actually shipped (M6).
- ~~nobody has opened an actual pygame window~~ **CLOSED 2026-08-26.** `scratchpad/play_window.py`
  opens the genuine `--io pc` composition on a real window; five sessions, the last 18 frames /
  702,109,142 ops: menu -> enter -> walk -> turn right -> walk -> turn left -> walk, all correct,
  sky included. ⚠ The INPUT is a scripted key list, not a physical keyboard -- Windows' foreground
  lock stops a background process focusing a window and SDL drops keys for an unfocused one. And
  an external PrintWindow capture is NOT trustworthy for an SDL window (it showed the menu frames
  as pure black while SDL's own surface had them perfectly); dump `window._screen_surface` instead.
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

### THE BUDGET IS RE-DERIVED (2026-08-25). Read this before writing any door code.

The line this section used to carry - *"16-unit quantisation -> 26 distinct heights, which fits the
one-byte pid budget (255 available, 152 used)"* - is **wrong twice**, and the corrections point in
opposite directions. `scratchpad/m2_budget.py` and `scratchpad/m2_bodies.py` do this arithmetic in
seconds, with no build, and both refuse to project unless they first reproduce the shipped
program's own numbers.

**(1) A pid is a (ceiling, floor) PAIR PER SECTOR, not a height.** 13 real doors share 27 heights
at quant 16 but need **94 pids**, not 26. The "26" is the **quant=64** row:

| quant | new pids | of 255 | new half-lists | **new baked bodies** |
|---|---|---|---|---|
| 8 | 185 | **337 - over** | +35,520 | +765 (+9.5%) |
| 16 | 94 | 246 (96.5%) | +18,048 | +664 (+8.2%) |
| 32 | 48 | 200 | +9,216 | +589 (+7.3%) |
| 64 | 25 | 177 | +4,800 | +529 (+6.5%) |

**(2) ... and the pid byte is a RED HERRING.** What the bands-as-code tier actually bakes is a
raw-op handler body per DISTINCT half-list, and identical lists share one. Doors add 62% more
half-lists and only **8% more bodies** - 96% of what a door adds is already in the bank. The body
cost is nearly FLAT in the quantum: smooth doors cost 135 more bodies than chunky ones, +1.7%.
**So there is no cost argument for a coarse door. Pick the quantum for how it looks.**

**(3) What actually binds is the BAND INDEX, and it is a default argument.**
`half-lists = viewz_classes x 2 keys/pid x pids x 2 halves + sky`. MEASURED: 48 viewz classes, so
**each pid costs 192 half-lists**; today 29,952 of a 65,536 cap at pad 32,768 - **2,816 spare, or
14.7 pids**. Every quantum, down to 64, pushes the pad to 65,536, the most 4 nibbles can address.
That cap is `generate_bands_walk_fj(lists, *, index_nibbles=4)` and nothing else; **5 nibbles lifts
it to 2**20** for one extra `hex.xor` per dispatch. What genuinely scales is `pad`, the switch
table - one op per entry, so 32,768 -> 65,536 costs **+65,536 words on an 84.9M-word span
(+0.08%)**.

⚠ **THIS IS THE SAME COUNTER M4 SPENDS** - see section 5.

**RUNG 1 IS DONE (2026-08-25): the cap is cleared.** `scratchpad/m2_widen.py` bakes a real
70,000-half-list walk at 5 nibbles, assembles it (7.9 MB of fj, 16 s) and dispatches into it -
ids 0 / 7 / 65,535 / 65,536 / 69,999 each return their OWN list. 65,535 and 65,536 carry different
shapes on purpose: that pair is what proves bit 17 is decoded, because a 4-nibble truncation would
have turned 65,536 into id 0. `index_nibbles=4` refuses the same input, so the cap is real and the
clearing is meaningful. **Doors are not index-bound at any quantum, and neither is M4.**

The ops/frame half is an UPPER BOUND, not a measurement: one extra `hex.xor` (~19.5 ops) per
`vpb_walk`, called at most twice per region per column, so <= ~640 calls -> <= ~12,500 ops on a
~28M frame (<= 0.045%). Measure it for real in whatever build ships the change.

### The rungs

**R1 - the index cap. DONE** (above): `index_nibbles=5` clears 65,536, assembled and dispatched.

**R2 - a door baked OPEN renders byte-exact. DONE** (commit `638e59c`).
`build/doom_e1m1_doors100.fjm` is E1M1 with all 13 doors at their true open height, built by
handing the emitter the same `sector_heights` override the oracle takes - **no fj code moved**.
Span 85,980,098 words (+1.8M vs shut), 675 s. `scratchpad/m2_gate.py` PASSES: the doors change
2,720 / 2,669 / 698 / 117 / 16 px at the gate's viewpoints and every changed pixel matches the
oracle's, **value for value**. That certifies the render path - pids, band bank, V5 stacked
pieces, collision, thing-liveness - for a door away from its stored position.

⚠ **The gate is a DIFFERENTIAL, and it has to be.** Comparing fj against the doors-open oracle
directly FAILS at (1869,479) with 371 px that have nothing to do with doors: the shipped binary
already differs from that oracle by **378 px** there, because the oracle call certifies the
NON-SIM tier. Disagreements are judged by where they land - outside the standing-delta set is a
door bug, inside it is INHERITED and reported (7 px today) but not judged. Do not "fix" this by
loosening it; fix it by closing the standing delta, which is a separate job.

**R3 - the RUNTIME door.** The measurements that shape it (`scratchpad/m2_segs.py`):

| | |
|---|---|
| segs a door can change at all | **81 of 2,057 = 3.9%** (the handoff said 7.8%) |
| ... whose OWN sector is the door (pid + render consts) | 52 - exactly **4 per door** |
| ... which LOOK AT a door (V5 stacked upper piece) | 29 - **1-3 per door**, and this is the half a player watches move |
| subsectors inside a door sector (walk + thing-liveness) | 13 |
| pids if ALL states coexist | +94 at quant 16 -> 246 of 255 |
| unique baked bodies if all states coexist | +664 (+8.2%); ONE open state costs +242 |

The shape this suggests, given the repo's own idiom (bake-to-code, and R20: dispatch cost scales
with the address's set bits): **bake each affected seg's constant block once per door state and
dispatch on a per-door state cell.** 81 segs x ~9 states, against 2,057 segs of blocks already
emitted, and only the door-touching segs pay anything at runtime. The alternative - making the
constants runtime registers loaded from a height cell - turns every one of those segs' xor_by
involution blocks into loads, which is the thing `_seg_xorby_block` exists to avoid.

⚠ Two things R2 did NOT touch and R3 must: the walk PRUNES a shut door's subsector at compile
time (it cannot, once the door is runtime), and `thing_live_subsectors` calls a shut door
uninhabitable - a closed door is `ceil_h <= floor_h`.

**R4 - the trigger and the state machine** (opening / waiting / closing, use-key on a door
linedef). No measurement here touches it; it is the real bulk of M2 and it is pure fj + oracle
mirror work.

Owner's constraint applies from R3 on: **keep ops/frame at similar cost**, measured against the
sweep median.

WARNING: **the door model was wrong once and the gate passed anyway.** Sweeping floor -> the wad's
ceiling is *zero movement* for a stored-shut door; the 1,451 px it reported came from a **lift**.
The rule is `P_DoorRaise`: a door opens to **`min(neighbouring sector ceiling) - 4`**.

WARNING: `door_gate.py`'s `height_set()` was **dead code with an unclamped rounding rule** -
flooring to a multiple of the quantum lands *below the floor* whenever the floor is not a multiple
of it (floor -128 at quant 24 -> -144). It was the function documented as the pid-cost answer, and
nothing called it. Both it and `door_state` now go through one `quantise()`.

Owner's constraint: **keep ops/frame at similar cost**, measured against the sweep median.

---

## 4. M3 - menu   <- DONE, 2026-08-26

Cheapest content milestone, and M5 made it cheaper still: the standalone binary already has the
two things a menu needs - **persistent state** and **keyboard input**.

**DONE: the menu is a BAKED FRAME** (`src/doomfj/menu.py`, commit in this series). A menu screen is
a picture that never changes and the renderer already presents pictures as 0x0B column run-lists,
so the menu needs no renderer: it is a constant byte stream, and menu-draw is a run of
`stl.output_char`s with compile-time operands.

    MEASURED: 1,172 bytes -> ~2,344 ops/frame, against a world frame's ~28,000,000.
    The menu is ~11,900x cheaper, so THE MODE FLAG IS M3'S ENTIRE COST.

One generator feeds both mirrors (`menu.pixels()` for the oracle, `menu.stream()` for fj, both from
one `_bitmap()`), and `tests/host/test_menu.py` (18 tests) proves they agree by decoding the stream
through the real `InMemoryScreen`. Colours are derived from the wad's PLAYPAL, not picked.

### It is finished

`build/doom_e1m1_menu.fjm` boots into the menu; enter/esc toggles. Span 85,209,916 words, 2,867 s.
`scratchpad/m3_gate.py` PASSES: ONE 347,229,603-op run, **13 frames, every one byte-exact** - menu
frames against `menu.pixels()`, world frames against the oracle at the state the sim reached.

    frame  0 MENU  (-416.000, 256.000)   boots into the menu
    frame  2 world (-416.000, 256.000)   enter -> world
    frame  5 world (-266.000, 256.000)   walking
    frame  6 MENU  (-266.000, 256.000)   enter -> menu, W STILL HELD
    frame  8 MENU  (-266.000, 256.000)   ... and it did not move
    frame  9 world (-216.000, 256.000)   enter -> world, resumes in place

The three properties the gate is built around, none of them visible in a single frame: `mode`
survives the M1 reset (it is in `STANDALONE_PERSIST` - without that it would snap back to 1 every
frame and show the menu forever, one frame after appearing to work); a menu frame does not run the
tic (the branch is BEFORE the sim, which is what makes leaving the menu resume in place); and the
toggle is DOWN-EDGE only (a press delivers a down AND an up event). `--selftest` REJECTED at
frame 0.

The restore set gained `mode`: 12,072 -> 12,084 words over 448 -> 454 entries, re-keyed as always.

Left for M4: the menu's entries currently select nothing. Wiring them to a `level` cell is M4's
rung R3, because it needs more than one level to select.

---

## 5. M4 - three levels

**DECIDED**: three levels in one image (E1M1 + E1M5 + E1M8). The full 9-level episode is **OUT**.
If three does not fit, **scale down rather than push**.

### THE PLAN

**M4 is not one more build - it is the only milestone left that changes the emitter's shape.** Two
emissions cannot be concatenated even with every label namespaced, because each one also contains
the SHARED tables: `palette`, the trig/reciprocal LUTs, the colormap, the texture and flat tables,
the sprite bank, and the `vpb_walk` machinery. Two copies is a duplicate-label error, not a
collision a prefix can fix - and two would not fit anyway, since they are the bulk of the 86M words.

**Already done, all measured, all committed:**

| | |
|---|---|
| the 65,536 band-index cap | **CLEARED** - a real 70,000-half-list walk at 5 nibbles assembles and dispatches (`m2_widen.py`) |
| the label collision surface | **16,412 labels in 17 families** (`m4_labels.py`) |
| the namespacer | `doomfj.mapprefix` - opt-in by construction (empty prefix = identity), 51,787 tokens on the real emission, 20 tests |
| the level-select mechanism | M3's persisted `mode` cell is the same machinery |

**The rungs, in order:**

**R0 - the shared/per-map boundary. NO BUILD.** Emit two DIFFERENT maps and diff the seven parts.
That turns "which blocks are map-derived" from a reading of the emitter into a list from the
emitter's own output. ~15 min of emission, no assembly. Everything below depends on that list, so
it goes first - the same discipline that caught the pid budget (94, not 26) and the label count
(16,412, not 102).

**R1 - a geometry-only emission mode.** `emit_wall_renderer(shared_tables=False)`: maps 2 and 3
emit their `segconsts` + `walk` and nothing else. Gate WITHOUT a build: the label sets of a full
emission and a geometry-only one must intersect in exactly the shared names, and two prefixed
geometry-only emissions must not intersect at all.

**R2 - one bands walk from N maps.** `lines_bank_keys` is per-map today; the union is a
concatenation, with each map's `seg_cvpidx`/`seg_fvpidx` shifted by its base, at
`index_nibbles=5`. This is the piece the cap had to be lifted for - three maps is ~90k half-lists.

**R3 - the `level` cell and the dispatch.** A persisted cell exactly like `mode`, and `main` jumps
to the selected map's walk entry. The menu's entries feed it, which is the whole reason M3 came
first.

**R4 - the build ladder, and do not skip a rung.**
  1. ONE map WITH a prefix - must be byte-exact against the unprefixed build. **This is the proof
     `mapprefix` is sound**, and it is cheap relative to what follows.
  2. TWO maps - finds every collision R1's label check missed, for half the build time of three.
  3. THREE.

⚠ **Span.** One E1M1 is 85.98M words against `RENDER_FLAT_MAX_WORDS` = 134,217,728, and the
per-level increment is somewhere between 3.4% and 93% (below). R0 narrows it; R4.2 settles it. If
the limit must rise it is RAM-only (DESIGN 1.2), but raise it with a measured peak RSS, not on a
failed build. Rule 1 has a new clause too: a finished build holds its memory for minutes after
printing its results.

⚠ **Honest risk.** R1 and R2 are surgery on a 2,900-line emitter in which the part order IS the
contract ("every baked address constant depends on the layout"). Expect
`scratchpad/cr/emit_baseline.py` to be the tool that keeps single-level emission honest
(`emit_hash_vs_head.py` was retired 2026-08-29 -- it compared by calling the same signature on
both sides, which a deleted parameter breaks)
throughout - it has its own negative control and it is fast relative to a build.

### Why the increment is not just "double it"

By emitted text (a proxy; chars are not words):

| part | | size | share |
|---|---|---|---|
| `06_banks` | mixed | 130,590,001 | 89.8% |
| `01_tables` | mixed | 9,981,535 | 6.9% |
| `04_walk` | **MAP** | 3,519,030 | 2.4% |
| `03_segconsts` | **MAP** | 1,379,522 | 0.9% |
| entry/main/state | shared | 18,079 | 0.0% |

Clearly map-specific is only **3.4%**. `06_banks` is the one that matters and it is MIXED: the
bands-as-code bank is map-derived, the **sprite bank is shared**. Hence R0.

### THE BUDGET WAS RE-DERIVED (2026-08-25), and 88.7% was optimistic.

That instruction - *the first task is NOT a build* - was right, and M2's D1/D2 rungs answered it
for M4 as a side effect, because **both milestones spend the same counter**.

MEASURED on the shipped stock-E1M1 program: **29,952 half-lists** at pad 32,768 of a 65,536 cap.
Three levels sum: **29,952 x 3 = 89,856 = 137% of the cap, BEFORE any door.** The "88.7%" was
projected from a smaller per-level count (roughly 19.4k/level - plausibly e1m1-lite, or a figure
from before rung 3a's per-pid bank layout tripled the keys). At the real number, three levels does
not fit 4 nibbles and neither does two-plus-doors.

**But the cap is a default argument, not a law.** `generate_bands_walk_fj(lists, *,
index_nibbles=4)` raises if `4*index_nibbles` cannot address `pad`; nothing else fixes 65,536.
`index_nibbles=5` lifts it to 2**20 for ONE extra `hex.xor` per dispatch, and the thing that
really scales is `pad` itself - one op per entry, so even 131,072 entries is +262,144 words against
an 84.9M-word span.

So the fallback ladder below is **premature - and rung 1 has now cleared the cap**
(`scratchpad/m2_widen.py`, section 3: a real 70,000-half-list walk at 5 nibbles assembles and
dispatches correctly past 65,536). Three levels is **~90k half-lists, which 5 nibbles addresses
with room to spare**, so the reason to scale down is gone. What is still owed for M4 is the cost
side - span, assemble time, and the extra dispatch xor's ops/frame - none of which the ladder
below was ever about.

⚠ Do NOT quote "88.7%" again, and do not scale down before step 1. `scratchpad/m2_budget.py`
prints the live number and reconstructs the emitted total before it will project anything.

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
