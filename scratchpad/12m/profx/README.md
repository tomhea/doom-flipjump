# profx -- the attributing profiler for the game binary

profx charges every op the game executes to the doom code that caused it. That includes ops in the
wflip chains, in the block pool's tables, in the stl runtime and in data reads. It also logs exact
op counts between phase labels. It produced `docs/plan-gameplay.md` section 3. Its `--selftest`
checks the attribution against an op-by-op trace, with an address-only negative control (R9).

Nothing here touches the shipped engine. The instrumented engine is built from flipjump-151's
`_fjcore.c` at `73e09c0` (the source is checked by sha256) and loaded by path.

## Where things go

Sources, this README and small reference outputs (`an_*.txt`, `hotwords_blocked27.json`) live here.
Everything big or derived goes to `$PROFX_WORK` (default `<system temp>/profx`), OUTSIDE the repo:
the engine (`engX/`), the maps, and the dumps. A 10-game run writes about 100 MB.

⚠ `.gitignore` ignores `scratchpad/**/*.json`, so `hotwords_blocked27.json` needs `git add -f`.
`scratchpad/12m/pinreport.py` reads it by default.

## The pipeline

| step | command | what it does |
|---|---|---|
| engine | `python profx.py engine` | patches `_fjcore.c` (`engine.py` + `profx_state.inc.c` + `profx_funcs.inc.c`, anchored) and compiles `<WORK>/engX/_fjcore.pyd` with MSVC Build Tools 18 (`vcvars64.bat`). `python engine.py --write-patch x.patch --no-compile` writes the unified diff. |
| maps | `python profx.py maps` | `maps.py`: the coarse objects (label-name boundaries), every label word, and 35 phase markers, from `scratchpad/12m/atlas/blocked27.labels.tsv.gz` and `build/generated_doom_e1m1_blocked27/` |
| run | `python drive.py games games` | calibration plus gamespeed's 10 games (1,000 game frames). Also `walk N <p>`, `still N <p> [--poke]`, `--stock`, `--trace LO N`, and `--lock PATH` (the binary lock). |
| tables | `phases.py`, `analyze.py`, `counts.py`, `reset_an.py`, `ptloc_an.py` | see below |
| hot words | `python hotwords.py games` | the ~20 hottest shared words, written to `hotwords_blocked27.json` for `scratchpad/12m/pinreport.py` |

**The attribution rule.** Code outside the transparent regions (the stl runtime, the tables and
state parts, the wflip area and the block pool) is opaque. An op in opaque code counts as program
flow if it is labelled, or within 16 words of the last flow op. A flow op that flips becomes the
**owner**. Every other op is charged to the owner:
- the chains, pool tables and stl routines,
- data reads (`;v*dw`),
- far unlabelled ops (shared wflip tails that the assembler parks in other expansions' pad holes).

Phase costs use no attribution at all. Each marker hit logs the op index, so phase costs are exact.

## Reproducing plan section 3 (blocked27, MEASURED 2026-09-26)

```
set PROFX_WORK=<outside the repo>
python profx.py engine && python profx.py maps
python drive.py games games --lock <lock>             # 1,000 frames; op totals = gamespeed's to the op
python drive.py still 75 poke --poke --lock <lock>
python drive.py still 75 still --lock <lock>
```

**Table 1 (objects):**
- `python phases.py games` (see `an_phases.txt`) gives:
  - render walk 12,986,630, split seg_pass2 4,019,353 / ts 2,723,647 / seg_pass1 2,641,860 / BSP nodes 966,608 / thing_leaf_b 966,408 / thing_leaf 583,454 / thing_pass 704,965;
  - collision 1,475,186;
  - bind_things 438,808;
  - m1_reset 249,325;
  - the rest (input, doors, move, view, eye walk) about 50K.
- The plan's 1,475,188 and 438,809 summed rounded segments; these are the exact spans.

**Table 2 (per call):**

| number | command | file |
|---|---|---|
| ptr_index 846; read/write_byte 260 / 504; read_hex 244 (and per nibble); read_byte_and_inc 404 per packed byte; mul_lo 825; fixed_mul_lo 3,381; hex.div 157,155; hex.cmp 40; scmp 249; check_position 575,975; check_line 6,787; thing_load 19,464; emit_col_lines 15,887 | `python analyze.py calls games` | `an_calls.txt` |
| one move try 613,383 (seed walk 35,366) | `phases.py games` | `an_phases.txt` |
| sprite column ~30K = sprite_runs 10,896 + emit_region 12,930 + 6,403 | `python analyze.py fam games stream.emit_col_lines,stream.sprite_runs,stream.emit_region` | `an_fam.txt` |
| BSP node 4,147; thing_leaf 30,197 and thing_leaf_b 15,460 per call | `python counts.py games` | `an_counts.txt` |
| reset 40.8 per cell | `python reset_an.py games` | `an_reset.txt` |
| point location: mean 30,711, median 8,875, max 180,042 (pixels identical to the unpoked control) | `python ptloc_an.py poke still` | `an_ptloc.txt` |

Also here:
- `an_objects.txt`: per-object, per-run and per-frame variance;
- `an_heavy.txt`: the heaviest frames;
- `an_sub.txt`: the big objects split by statement;
- `an_walk200.txt`: msframe's forward walk, 18,221,696 ops per presented frame;
- `an_hotwords.txt`: the hot words;
- `an_heatindex.txt`: the heat-ordered-index ESTIMATE behind `docs/gp-pin-protection.md`;
- `an_pinreport.txt`: `pinreport.py` on blocked27, blocked25 and b26, plus its selftest.

## Selftest

`python profx.py --selftest --lock <lock>` runs the binary twice (menu plus 3 idle frames, 60M ops):
once on the installed engine and once on the profiler with a full trace. It checks:
- **(c)** Nothing it measures changes: op totals, the pixels of all 5 frames, histogram conservation, and trace = histogram.
- **(a)** Owner attribution against the trace, per `sim.bind_things` statement. Every statement of
  200 ops/call or more must be within 5%, and the whole paired sequence within 1%.
  MEASURED: 6 checked, worst +3.3%, sequence -0.07%.
- **(b)** Address-only attribution through the same check must FAIL, and does:
  ptr_index 171 vs 893 ops/call, sequence -76%.

The run is recorded in `an_selftest.txt`.

## Limits

- **The map is written for the game tier.** Its object boundaries are label names (`simcollide`,
  `seg_pass2_leaf` and so on). A tier or map without them makes `maps.py` stop.
- **Per-call costs carry boundary noise.** A statement's first op sits a few ops before its first
  label, so statements under about 200 ops/call carry ±10-30% (see the selftest rows).
- **`analyze.py`'s `fN` file map is blocked27's.** It only prints call sites.
