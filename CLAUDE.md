# Working in doom-flipjump

DOOM's E1M1 rendered by a FlipJump program — a language whose only instruction is
`a;b` ("flip the bit at `a`, jump to `b`"). Python never draws a pixel: it *writes a program*
(~10⁸ characters), the assembler turns that into a ~50M-word image, and that program renders a
frame. A Python twin — the **oracle** (`src/doomfj/reference_model.py`) — renders the same frame
independently, and the two must agree **byte for byte**.

Read `DESIGN.md` for architecture, `docs/cr-rules.md` (R1–R9) for the review contract, and the
`docs/handoff-*.md` files for per-milestone detail.

---

## The five rules that prevent real damage

**1. ⚠ ONE HEAVY BUILD AT A TIME.** Two concurrent E1M1 builds die silently — exit 255, empty
output, no error. Every gate, bench and heavy test runs solo. If you are about to launch a build
while another runs, don't.

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
| `python -m pytest tests/host -q` | ~1 min | host logic (211 tests) |
| `scratchpad/deg_gate.py` | ~20 min | **the real proof**: byte-exact ×4 + op counts to the digit |
| the `steps=False` lines test | ~9 min | a config the certified gates never build (where a `rep`-gated `werror` break hides) |
| `test_build_wall_renderer_e1m1_flat` | ~70 min | the **shipped** build path — normally deselected, so run it after touching `build.py` |
| `scratchpad/bench.py …` | varies | op counts per viewpoint; byte-exactness asserted when un-ablated |

Both `cr/` tools have self-tests — run `alpha_check.py --selftest` after touching either.

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
