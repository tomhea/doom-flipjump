# HANDOFF: the fj CLARITY PASS + the GENERATED-PROGRAM website

Owner directive (2026-08-09). Two deliverables, in this order. Written for a session with NO
prior context — everything you need is here or pointed at from here. Read this whole file
before doing anything.

---

## 0. Repo state you are inheriting

- Branch `m13opt3-early-out`, tip = the clean-code refactor commit (`74c7f48`, "refactor: the
  CLEAN-CODE PASS"). Working tree should be clean except two stray uncommitted scratchpad
  edits (`rung3a_split.py`, `twosided_proto.py` — old session leftovers, leave them).
- The certified binary is `scratchpad/fjmcache/b_272d37507ca58434.fjm`: 7 bench gates
  byte-exact, 260-frame sweep median 22.99M / mean 22.58M / worst 48.46M ops.
- The 4-viewpoint fast gate is `scratchpad/deg_gate.py` (~20 min build+run, SOLO). Its
  current-certified op counts, **to the digit**:
  - (664,291,0x18000000): 45,208,629
  - (1272,-724,0x40000000): 35,486,777
  - (1869,479,0x80000000): 42,824,933
  - (-416,256,0x0): 33,547,652
- ⚠ NEVER run two heavy fj builds concurrently (silent OOM, exit 255, empty output). One
  build at a time, always.
- The review contract is `docs/cr-rules.md` (R1–R8). The memory files (auto-loaded) hold the
  campaign history; `docs/handoff-visual-features.md` and friends hold feature detail.

## 1. DELIVERABLE A — the fj clarity pass

The hand-written FlipJump library is `src/fj/` (7 files assembled into every build:
`fixed_point.fj`, `present.fj`, `projection.fj`, `frame_render.fj`, `plane_render.fj`,
`plane_bands.fj`, `stream_render.fj`). It is correct and CR'd but reads like tribal
knowledge: dense abbreviations, numbered labels, giant macros, history-laden comments. The
owner wants four improvements — **explicitly NOT a restructure** (the big shared-leaf macros
are load-bearing performance architecture; see the mantra in memory: heavy bodies live in ONE
shared `stl.fcall` leaf because the assembler is ~cubic in unrolled ops).

### A1. A conventions header per fj file

Write the implicit naming conventions down, once per file (a short block comment under the
file's existing header). The conventions that actually hold (verify against the code as you
document them):

- `u…` / `l…` prefixes = upper/lower (ceiling-side / floor-side) halves of a pair.
- `…p1` suffix = value **plus one** (an EXCLUSIVE end row: `uy2p1` = upper piece's y2+1).
- `…b` / `…p` pairs = a table **base** address and a running **pointer** into it
  (`sfb`/`sfp`, `sbb`/`sbp`).
- `…o` suffix on a macro param = an **output** param.
- `…v` = a loaded **value**; `n_…` = a counter; `c…` = a constant register (`cfff`, `czero2`).
- Latches (1-nibble globals): `full` = every column wall-drawn; `tsstop` = attribution can no
  longer change; `tsbstop` = the (never-binding, asserted) budget fuse; `fbspent` = the
  step-face budget filled. Their exact semantics are documented at
  `frame_render.fj::seg_pass1_leaf_body_ts` — point at that, don't duplicate it.
- Macro signature anatomy: positional params, then `@ local, names` (compile-time locals —
  every one must be USED on every rep-gated path or werror fails the build), then
  `< global, names` (external labels the body references).
- Labels are jump targets; the common idiom `hex.cmp a, b, lt, eq, gt` names three of them.
  Numbered label chains (`cw1..cw4`, `ust1..ust3`) are branch ladders — the rename pass (A2)
  should give the load-bearing ones intention names.
- Data cells live after `end:` inside a macro (or after `stl.loop` at top level) — they are
  fj ops that must never execute.

### A2. Local/label renames in the worst offenders

Renaming a macro's `@`-locals and labels changes ZERO assembled ops — names are compile-time
only. **The proof is deg_gate: byte-exact AND op counts identical to the digit** (the four
numbers in §0). That identity is the whole safety argument; if any op count moves, you
changed structure, not names — stop and find out why.

⚠ **Rename ONLY `@`-locals and labels local to a macro.** Do NOT rename:
- **Globals** (`< …` names like `tsstop`, `fbspent`, `seg_lit`, `colst`, `colbuf`, `viewz`,
  `sfflag` …): the Python emitter (`src/doomfj/wall_renderer.py`, also `mapcompiler.py`)
  generates text that references them inside f-strings. Renaming one means coordinated edits
  in the emitters and invalidates the emit-hash safety net. Out of scope for this pass.
- **Macro names and their parameter lists** — same reason (emitters instantiate them by name
  with positional args).
- Anything in `fj_consts.fj` / `memory_map.fj` (generated / consumed by name).

Worst offenders, in priority order (all in `frame_render.fj` unless noted):
1. `ts_step_faces` (~50 locals: `fsv`, `fbp`, `fdb`, `fdv`, `ulipn`, `udng` …)
2. `seg_pass2_leaf_body_lines` (the biggest leaf)
3. `seg_pass1_leaf_body_ts` (`xa`, `xb`, `pm1`, `bcap` are fine; the ladder labels aren't)
4. `lines_step_load` / `lines_steps_load2` / `lines_spr_load` (`stv`, `sbp`, `cpb` …)
5. `stream_render.fj::emit_col_lines` and `flush_frame` (`qlo`, `qbound`, `wlo`, `whi`,
   `cn`, `tn` …)
6. `projection.fj::project_thing` (`trx`, `try8`, `gxt`, `gyt`, `hpxo`, `cvh` …)

Keep renames conservative and consistent with A1's conventions — the goal is that a reader
who has read the conventions header can sight-read any name. e.g. `fsv` → `face_slot_cnt`,
`qlo/qbound` → `ceil_lo/ceil_end`, `cw1..cw4` → `wall_lo_clip/wall_hi_clip/...`. Don't
rename things that are already clear (`x`, `x1`, `x2`, `scale`, `viewangle`).

### A3. Comment triage

Keep, always: the WHY, the invariants, every `⚠` trap, the protocol/wire-format docs, the
complexity notes. Compress: session-history narration ("V5-DROP-P2 (owner's (1210,1187)
field-flip, 2026-08-04)…") down to the technical fact plus a pointer —
`(history: docs/handoff-*.md)`. The comment should teach the invariant, not re-tell the
debugging story. Comments are compile-time only — zero risk — but do this in the SAME commit
as A2 so one deg_gate proves both.

### A4. OPTIONAL inline sub-macro extraction

fj macros are textual expansion: splitting a 300-line body into inline (non-`stl.fcall`)
sub-macros emits the IDENTICAL op stream if the ops and their order are unchanged. Candidate
splits, only where near-symmetric halves exist:
- `ts_step_faces`: the upper-face and lower-face blocks mirror each other.
- `lines_step_load`: the upper/lower read+clip+shade halves.
- `emit_col_lines` / `emit_region`: the ceiling-half vs floor-half walks.

The tax: every local the sub-macro touches must thread through its signature, and werror
demands every param used on every rep-gated path (`rep(flag,k)` gating — beware flag=0
builds; the fbspent regression in memory is the cautionary tale: a build config the gates
don't compile can break silently, so ALSO run the steps=False gate below). If the tax makes a
signature absurd (>15 params), don't split — a labeled section banner comment is the better
tool. This item is optional; A1–A3 are the deliverable.

### A-verification (the whole pass)

1. `python scratchpad/deg_gate.py` — must print BYTE-EXACT ×4 with the §0 op counts to the
   digit. (~20 min, solo.)
2. `python -m pytest "tests/fj/test_lines_render.py::test_e1m1_lines_wpx_ft1_plane_near_byte_exact_vs_oracle" -q`
   — the steps=False config the certified gates don't build (~15 min). Guards tsq/rep-gated
   werror breakage.
3. `python -m pytest tests/host -q --deselect tests/host/test_e1m1_integration.py::test_build_wall_renderer_e1m1_flat`
   (~2 min, 211 tests).
4. If ANY op count differs → you changed structure; bisect the change, or if intentional
   (A4 gone wrong), run the full ladder: bench 7 gates + the 260-frame sweep
   (`scratchpad/bench.py --wall-mode W1R --stack --deg --wad tests/fixtures/e1m1_lite.wad
   --asset tests/fixtures/freedoom_e1m1.wad` + 6 `--vp`s — see git log `902f92e` for the
   exact invocation — then `scratchpad/lite_sweep_csv.py <new b_*.fjm>`).
5. CR the diff with the established loop: write the diff to a file, run a Workflow with two
   review agents (correctness lens / rules lens) + one adversarial verifier per finding, fix
   confirmed items, repeat until clean. Working examples of the exact workflow script:
   `~/.claude/projects/<this project>/…/workflows/scripts/cr-refactor-review-*.js` (or
   reconstruct from the pattern in `scratchpad/cr/` — prep_units.py/extract.py show the
   schemas).
6. Commit with the proof numbers in the message.

Parallelize with agents by FILE (disjoint ownership, like the refactor did): one agent per fj
file works; frame_render.fj is big enough to split by macro-range between two agents ONLY if
their edit regions cannot overlap.

## 2. DELIVERABLE B — REPLACE the onboarding website with a GENERATED-PROGRAM guide

The current page (https://claude.ai/code/artifact/0a947e9a-b8f5-4f9f-9b4d-c0ce8a26fcbf)
explains the host toolchain. **The owner found it uninteresting — wrong subject.** They want
a page explaining the GENERATED FLIPJUMP PROJECT itself: the program the assembler sees, its
files, its macros, what does what, where "main" is, where the "main loop" is. Rebuild the
page around the generated artifact, not the Python that generates it.

### What the page must cover (the owner's own asks first)

1. **Where is "main"?** The assembled program = the ordered include chain
   `fj_consts.fj → fixed_point.fj → present.fj → projection.fj → frame_render.fj →
   plane_render.fj → plane_bands.fj → stream_render.fj → THE EMITTED MAIN` (one generated
   file, cached as `scratchpad/fjmcache/b_<hash>.fj` — ~107M chars). The library files
   define macros only; ALL top-level executable code lives in the emitted main:
   `stl.startup_and_init_all` → read `vx`/`vy`/`viewangle` from stdin
   (`hex.input_dec_int`) → per-frame setup (`proj.wedge_setup`, the descend pre-walk that
   finds the player subsector and sets `viewz`) → `present.begin_frame_collines` → the BSP
   walk → `stream.flush_frame` → end-of-frame byte → `stl.loop` (halt). Then the data
   banks.
2. **Where is the "main loop"? THERE ISN'T ONE IN-PROGRAM — teach this.** One run of the
   binary renders exactly ONE frame and halts (`stl.loop` = self-jump). The frame loop lives
   host-side: the walker re-runs the binary per frame, restoring the memory image each time
   because FlipJump SELF-MODIFIES as it runs (every `wflip`, and the whole per-seg xor_by
   machinery) — a second run on a dirty image dies after ~9 ops. This inverted structure
   (program = pure function of stdin, loop = outside) is one of the most surprising things
   about the project; give it its own section.
3. **The emitted main's anatomy, with REAL excerpts.** Open an actual cached main
   (`scratchpad/fjmcache/b_272d37507ca58434.fj` — regenerate via the config in
   `scratchpad/cr/emit_hash.py` if absent) and quote real snippets, syntax-highlighted and
   annotated line by line:
   - a BSP node block (the inlined side test + near/far branch);
   - one seg's visit: `seg{si}G_xorby` SET call → `seg_pass1_leaf` fcall → `proceed` test →
     `seg{si}R_xorby` → `seg_pass2_leaf` → the CLEAR calls (explain the involution:
     `x ^ v ^ v = x`, why registers must be zero-init, and why SET/CLEAR beats `hex.set`);
   - the stop-latch guards around a marking seg (`tsstop`/`tsbstop`/`fbspent` tests);
   - a slice of a data bank (`;0x2f * dw` rows) with the explanation that a packed byte IS
     one fj op's data bits;
   - a dispatch-table entry and how `hex.` ops jump through truth tables.
4. **The macro library tour, file by file** — for each of the 7 files: its namespace, its
   ~5 most important macros with one-line what-it-does + who calls it (the emitted main?
   another macro?), and the file's one big idea. E.g. `projection.fj` = the oracle's math
   mirrored bit-for-bit (`wall_x_range` is the hot one, `project_thing` is R_ProjectSprite);
   `frame_render.fj` = the per-seg leaf bodies the walk fcalls into; `stream_render.fj` =
   the per-column emit + `flush_frame`'s ditto compression; `present.fj` = the device wire
   protocol (document the 0x0B byte grammar exactly); `plane_bands.fj` = the band-list
   builder; `fixed_point.fj` = the Q16.16 kernels; `plane_render.fj` = the legacy
   framebuffer tier (say so).
5. **The execution model primer** (short): what `a;b` does, what a macro is (compile-time
   textual expansion, not a function), what `stl.fcall`/`fret` cost, why `hex.*` ops need
   `hex.init` tables, `w=32`, what a "word" and `dw` are, and how ops-per-frame maps to
   speed (~220M fj ops/s on the native engine → ~0.15s/frame at the 23M median; ~7 fps).
6. **How to poke at it**: where the cached `.fj`/`.fjm` files live, how to grep a seg's
   block by label, how to run one frame by hand (`fastrun.FjmRunner` + `StreamScreen` with
   `stdin=b"1698\n892\n536870912\n"`), and the sizes table (chars emitted, words assembled,
   assemble minutes, ops/frame).

### Page mechanics

- Source file: keep a copy in the session scratchpad; **republish over the SAME artifact** so
  the owner's link stays valid: pass
  `url: "https://claude.ai/code/artifact/0a947e9a-b8f5-4f9f-9b4d-c0ce8a26fcbf"` to the
  Artifact tool (required from a new conversation — without it you mint a new URL). Keep the
  favicon 👾. Load the artifact-design skill before writing.
- Design: keep the existing visual identity (warm corridor-dark / nukage-green accent /
  monospace-forward headings) — the owner didn't object to the look, only the subject.
- Code excerpts are the star: real generated lines with per-line annotations beat prose.
  Mermaid renders natively for the include-chain/walk diagrams.
- Target the same 15-minute read; assume the reader knows C-level programming but has never
  seen FlipJump.

### B-verification

Have one agent who has NOT read the page attempt three tasks using only the page: (1) find
where execution starts in a cached b_*.fj; (2) explain why there is no loop in the program;
(3) locate which macro paints a wall column's pixels. Fix the page until all three succeed.

## 3. Order of work & scope notes

- Do A before B (B quotes the fj sources; quote them AFTER the renames so the excerpts match
  the tree).
- A1–A3 are one commit (one deg_gate proof); A4, if attempted, is a SEPARATE commit with its
  own proof. B is a page publish, no repo commit needed beyond the source copy if you keep
  one in-repo (optional: docs/onboarding-page.html).
- Update the memory file (e1m1-15m-campaign.md STATE block + MEMORY.md hook) when done:
  the clarity pass proof numbers, and note the artifact URL now shows the generated-program
  guide.
- The owner's standing preferences (from memory): correctness/detail over op budget;
  fix-it-everywhere sweeps over spot fixes; CR loops until clean; report with evidence
  (hashes, op counts, before/after), not adjectives.
