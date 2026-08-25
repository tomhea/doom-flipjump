# Working in doom-flipjump

DOOM's E1M1 rendered by a FlipJump program — a language whose only instruction is
`a;b` ("flip the bit at `a`, jump to `b`"). Python never draws a pixel: it *writes a program*
(~10⁸ characters), the assembler turns that into a ~50M-word image, and that program renders a
frame. A Python twin — the **oracle** (`src/doomfj/reference_model.py`) — renders the same frame
independently, and the two must agree **byte for byte**.

Read `DESIGN.md` for architecture, `docs/cr-rules.md` (R1–R9) for the review contract, and the
`docs/handoff-*.md` files for per-milestone detail. **★ For what happens next, start at `docs/handoff-m5-m2-m3-m4.md`.**
M1 (the self-resetting loop) and M5 (the standalone `.fjm` — `fj build/doom_e1m1_std.fjm --io pc
--flat-max-words 134217728`, no Python in the loop) are both DONE. Three milestones remain, in the
owner’s order: **M2 doors → M3 menu → M4 levels**, then M6 ship.
`docs/handoff-complete-game.md` is the full roadmap behind it.

---

## The five rules that prevent real damage

**1. ⚠ ONE HEAVY BUILD AT A TIME.** Two concurrent E1M1 builds die silently — exit 255, empty
output, no error. Every gate, bench and heavy test runs solo. If you are about to launch a build
while another runs, don't.
> ⚠ **AND "the build printed its results" is NOT "the build released its memory" (2026-08-25).**
> `m5_build.py` sat at **6.4 GB** and `ca_labels.py` at **6.9 GB** for minutes after printing
> their final line — the interpreter frees an 85M-word image slowly. Rule 1 is about PEAK RSS,
> so check the PROCESS is gone (`wmic process where "name='python.exe'" get ProcessId,WorkingSetSize`),
> not that the log looks complete. Starting the next build on the strength of the log put two
> heavy jobs on the box twice in one session.
>
> **The cause is now known, and it was never an assembler bug: MEMORY EXHAUSTION.** The assembler
> was memory-bound and paged — 129.4 MB of fj source became ~13.6 GB live on a 16.8 GB machine, so
> two at once simply ran the box out of RAM. The 2026-08-20 assembler work (flipjump-151 06385ad +
> 108e391) cut that live set hard, so concurrency *may* now be safe — but **the rule stands until
> someone measures peak RSS of the current build and proves it.** Don't relax it on this note alone.

**2. Byte-exactness is the contract.** A change that moves pixels moves them in *both* mirrors in
the same commit, then re-certifies. "Looks fine" does not exist here. The proof is
`scratchpad/deg_gate.py`: 4 viewpoints, byte-exact **and op counts identical to the digit**.
An op-count change with byte-exact pixels still means you changed structure — investigate it.

**3. Trust the gate; distrust the cheap pre-gate.** Learned the hard way: in one session, four
separate claims of "this transformation is obviously equivalent" were **wrong**, twice about the
checking tools themselves. `deg_gate` was never wrong. So:
- a fast pre-gate is for *saving 20 minutes*, never for *replacing the gate*;
- **a verification tool used as evidence MUST ship a negative control** — a self-test that
  mutates real code and requires the tool to reject it (see R9 in `docs/cr-rules.md`);
- never write "verified"/"identical" in a commit message for something a gate didn't run on.

**4. The emitter ABI is frozen.** The Python emitters generate fj text inside f-strings, so these
are NOT refactorable by rename: fj **global** labels, **macro names**, and **positional parameter
lists**. Only `@`-locals, macro-local labels and comments are free. `scratchpad/cr/alpha_check.py`
enforces exactly this.

**5. Changing a shared helper is a FAN-OUT edit.** Grep `src/`, `scratchpad/`, **and `tests/`** —
missing the `tests/` caller of a changed signature shipped a broken test that only a full run
catches. Prefer changing the helper so a definition *cannot* drift from its call sites (e.g. pass
a full label, not an index that both sides re-derive).

---

## The verification ladder

Run these in order; each is cheaper than the next and rules out a different class of error.

| Check | Cost | Proves |
|---|---|---|
| `scratchpad/cr/alpha_check.py [ref]` | ~1 s | a pass renamed only `@`-locals/labels (rejects op/global/ns/param edits) |
| `scratchpad/cr/expand_check.py <ref> <file> <outer> <sub>` | ~1 s | an extracted sub-macro expands to the exact ops it replaced |
| `python -m pytest tests/host -q` | minutes | host logic. ⚠ CR-2026-08: this was documented as ~1 min with the heavy build test "normally deselected" — it was neither. There was no marker and no `addopts`, so the run walked into the ~70-min `test_build_wall_renderer_e1m1_flat` at 17%. `slow` is now a registered marker excluded by `addopts`; check the **"N deselected"** line to see the filter bound. |
| `scratchpad/deg_gate.py` | was ~20 min | **the real proof**: byte-exact ×4 + op counts to the digit |
| the `steps=False` lines test | was ~9 min | a config the certified gates never build (where a `rep`-gated `werror` break hides) |
| `python -m pytest tests/host -m slow` | was 29:43 | the **shipped** build path — excluded by default, so run it after touching `build.py` |
| `scratchpad/m5_gate.py --frames 12` | 561M ops | the **standalone** binary: 12 frames driven by nothing but scripted keypresses, each byte-exact vs the oracle stepping the same keys from the player start. CUMULATIVE — a one-ulp drift on frame 0 parts the trajectory and every later frame differs. `--smoke` is the cheap no-loop variant. |
| `scratchpad/bench.py …` | varies | op counts per viewpoint; byte-exactness asserted when un-ablated |

⚠ **Every "was" above is a build-dominated cost measured BEFORE 2026-08-20, when the same program
assembled in 1,729 s and now assembles in 559 s (3.1×; 11.3× against the original 6,332 s).** They
are all substantially lower now and none has been re-measured. Read the number the run prints;
do not quote these. Emission (~7 min for the sprite-bank tier) did **not** change and is now the
larger half of most of these.

All three `cr/` tools have self-tests — `alpha_check.py --selftest`, `expand_check.py --selftest`,
`emit_hash.py --selftest`. Run the one you touched. (⚠ CR-2026-08: this line used to claim "both
tools" had them when only `alpha_check` did — a false statement about R9 compliance, in the file
that states R9. If you add a tool whose output you intend to quote as proof, it does not exist
until its `--selftest` does.)

## The generated program

Emitted as **ordered, named parts** (`emit_wall_renderer(..., return_parts=True)` +
`write_program_files`), so the ~55-line program does not share a file with 4.8M lines of baked
data:

```
e1m1_00_entry  e1m1_01_tables  e1m1_02_main(55)  e1m1_03_segconsts
e1m1_04_walk   e1m1_05_state   e1m1_06_banks
```

⚠ **ORDER IS THE CONTRACT.** fj top-level labels are global, so the ordered files are equivalent
to their concatenation — which is what made the split provably safe. Never sort these paths, never
glob them, never reorder the parts: every baked address constant depends on the layout.

## The two tiers

One emitter, two programs, and the difference is only where the world comes from:

- **hosted** (`build_wall_renderer()` defaults) — a Python host writes **887 bytes of state per
  frame** to stdin and reads the new state back. `scripts/walk_e1m1.py` is this.
- **standalone** (`standalone=True`) — no host at all. The player start is BAKED, the keyboard
  device drives the sim (`src/fj/input.fj`), thing bindings and visibility bake, nothing is
  echoed, and the view state + held-key flags SURVIVE the M1 reset (`build.STANDALONE_PERSIST`,
  the one place a hole in the restore set is intended). Run it with
  `fj build/doom_e1m1_std.fjm --io pc --flat-max-words 134217728`.

⚠ They are DIFFERENT PROGRAMS and each has its own restore set (`m1_` / `m5_restore_set.json.gz`);
`build_wall_renderer` picks by tier so they cannot be crossed. Add an emit-shaping flag to BOTH
or neither — three entry points building three renderers is the divergence A0.1 closed.

## Cost model

Ops/frame is the currency (deterministic per viewpoint, so it diffs). Two kinds of cost control,
and the distinction is the repo's hardest-won lesson:
- **Stops** (good): conditions under which further work *provably changes no pixel*.
- **Budgets** (dangerous): counters that cut work off mid-frame. **A budget that binds paints
  wrong pixels.** Surviving budgets are either provably never-binding (asserted at emit time) or
  shed only invisible work.

## Housekeeping

- `scratchpad/` holds hundreds of untracked experiment files. **Never `git add -A scratchpad/`** —
  stage named files only, or you will sweep 35 stray artifacts into a commit.
- Windows console is cp1255: keep probe output ASCII, or redirect to a file.
- Commit messages carry the proof numbers (op counts, hashes, test names), not adjectives.

## Performance Claims
Never quote an ops/frame, speedup, or cost number without re-running the measurement harness in this session. Before reporting any performance win: (1) verify the harness is not measuring zeros or a no-op filter, (2) print the raw baseline and post-change numbers side by side, (3) state the measurement command used. If a number comes from a doc, git log, or memory, label it explicitly as UNVERIFIED and re-measure before acting on it.

## Byte-Exactness Gate
Every renderer/emitter change must be validated byte-exact against the reference output before it is described as done or committed. Run the four-viewpoint gate and diff the emitted bytes; if the diff is non-empty, the change is NOT shipped. Do not use the equivalence checker alone — verify it actually compared every file (print the file count it checked).

## Feature Wiring Checklist
A feature is not 'shipped' until it is wired into the entry point (e.g. walk_e1m1.py) and observable end-to-end from a user-facing run. Before saying a milestone is complete, grep for the new flag/function name in the entry-point script and paste the line that enables it.

## Long-Running Commands
Always bound long commands: use `timeout <N>` on benchmark/test invocations and verify pytest marker filters actually deselect (check the 'N deselected' line) before trusting a scoped run. Never leave a harness running longer than 10 minutes without reporting progress to the user.
