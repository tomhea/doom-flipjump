# Handoff — the road to a complete, standalone DOOM on FlipJump

**Written 2026-08-20**, after the assemble-time campaign closed. Supersedes the scheduling parts of
`docs/handoff-playable.md`; that file's §0 (the metric) and §8 (rung detail) still hold.

This is the **whole remaining program**, in dependency order, with what is done, what is owed, and
what is a decision rather than a task.

---

## 0. What changed, and why the plan changed with it

**The build is 11.3× faster: 6,332 s → 559 s (9 min 19 s), program-identical.**
(flipjump-151 `06385ad` + `108e391`; the `.fjm` decompresses to a byte-identical 314,505,544-byte
image, sha256 `6e996f2a…`.) Details in the `assemble-time-campaign` memory.

Three consequences that **rewrite the roadmap**, not just the schedule:

1. **Multi-level is now affordable.** `tests/host/test_e1m1_integration.py` used to warn that "three
   levels in one image projects to 4-5 hours". At 559 s for one E1M1 and roughly linear scaling,
   three levels projects to **~30 minutes**. Levels moved from "probably never" to "a normal task".
2. **`CLAUDE.md` rule 1 has a known cause.** Concurrent builds died of **memory exhaustion**, not an
   assembler bug. The live set is far smaller now, so concurrency may be safe — **but nobody has
   measured peak RSS of the current build, so the rule stands.** Measuring it is a 10-minute job
   that could double gate throughput (see §6, Q1).
3. **Emission is now the bigger half.** ~7 min to emit vs ~9 min to assemble. Any further build-time
   work should target the *emitter*, and the cheap assembler wins are largely spent (§6).

---

## 1. The spine: why the 9-op wall is the whole game

The single most important structural fact, and the reason the milestones are ordered as they are:

> **The fj program SELF-MODIFIES. Run 2 on a dirty image dies after 9 ops.**

Today the host works around this by restoring a pristine image before every frame — a fixed ~52 ms
memcpy that caps the game at **~19 fps no matter how cheap the frame gets** (`handoff-playable`
§4.2). That workaround has two fatal properties:

- it is the **fps ceiling**, so every op saved in the renderer is wasted below it; and
- **a standalone `.fjm` has no host to do it.** Nothing resets the image. The program must restore
  itself, or it renders exactly one frame and dies.

So "fix the 9-op wall" and "build the self-reset prologue" are the *same task*, and that task is the
gate on **both** remaining headline goals — playable fps, and no-Python standalone. Doors, menu and
levels are content that hangs off a working loop.

**This is why M1 comes first, and the owner's instinct to diagnose it before continuing is right.**

### What is actually known (and what is only assumed)

| | |
|---|---|
| ✅ measured | word 1 (the jump field of the first op) is XORed with 512; word 2 has xor = 3 |
| ✅ measured | restoring exactly those two words gets *past* 9 ops — so they are real |
| ⚠ measured, and damning | …but frame 2 then runs **>560 s against frame 1's 0.5 s**. Those two words are a **symptom**, not the cause. |
| ✅ measured | one frame dirties ~4–5k words of 68,223,650; the union of four very different frames is 6,685; coalescing at gap 256 gives 216 ranges over 0.22 MB (`scratchpad/dirty_census.py --exact`) |
| ❌ **UNVERIFIED** | the stride of `sshead`/`thnext`, which are **74% of the ~2,500 cells**. **Three previous probes disagreed.** |

**Do not write the reset prologue against an assumed stride.** That is the exact shape of failure
this repo keeps hitting (CLAUDE.md rule 3). The first task is a probe with an R9 negative control.

---

## M1 — The self-resetting program *(blocks everything below)*

**Goal:** the program renders frame N+1 correctly, on its own, with no host restore.

**M1a — the stride probe.** Determine the `sshead`/`thnext` stride, with a negative control that
mutates a known-good stride and *requires* the probe to reject it. Three prior probes disagreed;
a fourth opinion without a control is worth nothing. *(hours, no build)*

**M1b — the dirty set from the EMITTER, not from sampling.** `dirty_census` learned its ranges from
4–5 sample frames. That bounds the prize; it does **not** bound the set. A word dirtied outside the
sampled ranges survives into the next frame — and because the program self-modifies, a leak does not
politely produce a wrong pixel, it produces a **different program**. The emitter knows every address
it writes; derive the set there and cross-check it against the census. *(days, no build)*

**M1c — the fj reset prologue.** ~2,500 cells restored in fj at frame start. Cost must be small
against the ~29.4M-op frame. Gate: run the same frame twice and require **identical op counts and
identical pixels**, plus an exact 68M-word walk against the pristine image. *(days, builds)*

**M1d — the internal frame loop.** The program loops instead of the host re-launching it.
**This is the first moment the thing is a game rather than a frame renderer.**

**Payoff:** kills the ~52 ms/frame ceiling → the first honest fps number; unblocks M5 entirely.

---

## M2 — Doors *(the fj half)*

The **gate already exists and is non-vacuous** (`scratchpad/door_gate.py`). That was the hard part
and it is done: with every door and lift open, `deg_gate`'s four certified viewpoints render **0
pixels different**, so the repo could have shipped a completely broken door and every gate would
have passed. Three door viewpoints (2,720 / 2,664 / 693 px) now make it fail when it should.

Owed:
- a compile-time-addressed **dynamic height cell** for the 7.8% of segs touching door sectors;
- 16-unit quantisation → **26 distinct heights**, which fits the one-byte pid budget (255, 152 used);
- the `thing_live_subsectors` predicate fix — a closed door is `ceil_h <= floor_h`.

⚠ **The door model was wrong once and the gate passed anyway.** Sweeping floor → the wad's ceiling is
*zero movement* for a stored-shut door; the 1,451 px it reported came from a **lift**. The rule is
P_DoorRaise: a door opens to `min(neighbouring sector ceiling) − 4`.

Owner's constraint: **keep ops/frame at similar cost.** The sweep median over 260 frames is the
metric; gate viewpoints are worst cases sitting between p90 and p99.

---

## M3 — Menu

Cheapest of the three content milestones and a good confidence-builder after M1.

- Text output already exists (`stl.output_char`), so a menu is a different **frame producer**, not
  new machinery: a mode flag selecting menu-draw vs world-draw.
- Input already works (M14 rung 0). Needs a mode state and a transition.
- **Depends on M1** — a menu that cannot advance to a second frame is a static image.

---

## M4 — More levels — ✅ **DECIDED 2026-08-20: THREE LEVELS, NOT THE FULL EPISODE**

Owner's call, verbatim: *"yes, try 3 levels at first, and not the whole line, if the space is too
big for that."* So: **target three levels in one image (E1M1 + E1M5 + E1M8); the full 9-level
episode is explicitly OUT; and if three does not fit, scale down rather than push.**

⚠ **THE FIRST M4 TASK IS NOT A BUILD — IT IS RE-DERIVING THE BUDGET.** "Three levels = **88.7% of
the 65,536 band-index cap**" is a projection carried over from an earlier session and **has not been
re-measured against the current emitter**. 88.7% leaves **11.3% of margin**: if that projection is
off by even an eighth, three levels does not fit, and you would find out after a ~30-minute build
instead of after an afternoon of arithmetic. Re-derive the per-level band-index count from the
emitter first, then decide.

The fallback ladder, in order, if three does not fit:

| step | what | when to take it |
|---|---|---|
| 1 | 3 levels, full detail | budget re-derived and under ~90% |
| 2 | 3 levels, reduced far-detail on levels 2–3 (the DEG knobs already exist) | over cap by < ~20% |
| 3 | 2 levels, full detail | over cap by more |
| 4 | 1 level + polish | last resort |

Never the full episode — it was measured impossible and the owner has ruled it out.

Build cost is no longer an objection: ~30 min for three levels (was 4–5 hours). Standalone-
compatibility is why they must share one image — a standalone `.fjm` cannot load a wad at runtime.

---

## M5 — The standalone `.fjm` *(no Python)*

- **Input:** no runtime change — the flipjump input device already covers it.
- **Output:** **~35 lines in `ScreenIO.py`** for the 0x0B decoder. This is the "you control fj1.5.1"
  case, and it is small.
- **The loop: entirely M1.** Without the self-reset there is nothing to package.
- Flip `doomfj.harness.FJM_LZMA_FAST` to `False` when cutting the distributable — 21.8 MB instead of
  29.0 MB, costing 93 s of build. It is encoder-only, so this changes nothing but size.

---

## M6 — Ship

Re-certify all gates, run the 260-frame sweep, record the final median, tag, archive the binary.

---

## 2. Dependency graph

```
M1 self-reset ──┬── M2 doors ──┐
   (THE GATE)   ├── M3 menu ───┼── M6 ship
                └── M4 levels ─┘        ▲
                       │                │
                 3 levels (decided) M5 standalone
                 re-derive budget    (needs M1)
                 BEFORE building
```

---

## 3. Loose ends carried forward

- **UNEXPLAINED:** `collide=True` costs **+7.0% median at keys=0** (one opprof run). Nobody has
  explained why colliding against nothing costs 7%. Worth one session before M2 — it is exactly the
  kind of thing that turns out to be a stop that stopped stopping.
- **G1 regression guard** (stop census + emit hash) is designed but **not wired**.
- ~140 CR findings still open in `scratchpad/cr2/findings/`.

---

## 4. The rules that keep biting (do not relearn these)

- **The sweep median over 260 frames is THE metric.** Gate viewpoints overstate the typical frame by
  1.5–1.9×.
- **Measure both sides in-session.** A stale baseline is not a control.
- **Vacuity controls must be two-sided.** This repo has repeatedly shipped a check that passed while
  measuring the wrong thing: the door gate, the tsstop plane gate, and `m14_gate`'s arg-order bug
  that read tics from `argv[1]="--things"` and produced a *vacuous* 8-tic "failure".
- **Count the stops** when touching any prune/gate predicate — a vanished STOP is byte-exact and so
  invisible to `deg_gate`.
- **Stops, not budgets.** A budget that binds paints wrong pixels.
- ⚠ **This machine is not a quiet bench.** Two `vmware-vmx` VMs compete for it; the same code
  measured 758 s and 802 s in consecutive runs. Compare on `time.process_time()`, not wall.
- ⚠ **Never launch a heavy build as `nohup … &`** from the agent harness — the wrapper shell exits,
  the harness reports success, and the build is reaped as an orphan mid-parse.

---

## 5. Build-time facts (2026-08-20, measured)

```
                 ORIGINAL   after 06385ad   FINAL (108e391)
parsing           1,127.0        198.5          169.3
macro resolve     3,077.6        408.9          107.5
labels resolve    1,637.4        802.2          266.0
create binary       158.3        138.0            8.7
TOTAL             6,332 s      1,729 s      559 s wall / 342 s CPU
```
Emission is unchanged at ~7 min and is now the larger half of a full build.

⚠ Every build-dominated cost in `CLAUDE.md`'s verification ladder (`deg_gate` "~20 min", the
`steps=False` test "~9 min", the slow test "29:43") predates this and is **stale in the safe
direction**. None has been re-measured. Read what the run prints.

---

## 6. Remaining build-time levers (honest assessment)

The cheap assembler wins are **spent**. What is left, in expected-value order:

| lever | worth | risk |
|---|---|---|
| **Parser fast path** for trivial lines — 2.1M raw-op + 1.45M bare-label lines are 66% of the file. Could take parsing 169 s → ~60 s. | ~100 s | **high** — must reproduce sly's output exactly |
| Delete `_PrepareMacroCall` (try/finally at 2 call sites; `__exit__` only pops) | ~10 s | low |
| Drop `labels_code_positions` (8.3M-entry dict, duplicate-label error text only) | memory | low, costs error quality |
| wflip chain trie — the key is re-tupled each iteration, O(k²) per wflip | ~10 s | **medium** — the obvious `(word_address, mask)` key **collides** where the address tuple does not, for unaligned wflip addresses. The prefix-closed trie is the sound form. Prove before using. |
| Inline `stl.output_bit` → `stl.IO + b;` (513,056 sites, expands to exactly one op) | ~14 s | low |

**Measured and rejected — do not retry these:**
- **`reserve` for the zero-word runs.** 984,877 `;0 * dw` lines = 18.4% of the file, the most
  attractive-looking target — but they sit in **22,843 runs averaging 43 ops**, only 6 runs ≥ 64.
  It would need ~22,843 segments. Dead.
- **Inlining `bit.if`** (769,584 sites): removes 1.54M expansions but adds ~3.1M lines. **Net worse
  by ~55 s.** Parsing costs ~31 µs/line and macro expansion ~27 µs/expansion — they are nearly
  equal, so line↔expansion trades are a wash in *both* directions. This is why the emitter direction
  is much weaker than it looks.
- `__slots__` on sly's `Token`/`YaccProduction` — already present.
- `gc.freeze()` + freeing the macro tree — no change to peak; the peak is before the frees.

**Q1 (10 minutes, high value):** measure peak RSS of the current build. If it is comfortably under
half of RAM, `CLAUDE.md` rule 1 can be relaxed to two concurrent builds and **every gate day gets
twice as fast** — worth more than any remaining assembler micro-optimisation.

---

## 7. Where to start next session

1. Read this file, then `CLAUDE.md`, then `docs/cr-rules.md`.
2. **M1a**: the `sshead`/`thnext` stride probe, with its R9 negative control.
3. Do **not** write the reset prologue until M1a and M1b agree on the dirty set.
