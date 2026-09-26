# S5: the compositor census and the fight line

This is P0 stream S5 (docs/plan-gameplay.md sections 5 and 7). It needs no build, no binary and no
edit to any tracked file. Run everything from the repo root:

| file | what it does | time |
|---|---|---|
| `census_lib.py` | Wires `doomfj.world` to the oracle renderer by swapping hooks (see its docstring). It adds size stand-ins for corpses, drops, fireballs, puffs, blood and exploding barrels: the real freedoom1.wad patch of each thing's current frame and rotation. The oracle renders with the **game tier's keywords** (`RENDER_KW` = deg_gate's = `b0_scenarios.GameOracle`'s, `sky` and `bbox_cull` included). | - |
| `census_control.py` | **The control.** At 11 viewpoints (two of them outdoors) the instrumented renderer is byte-identical to the stock one, and the attributed slot claims sum to the slot arrays. The negative control drops one thing and must change pixels (428 px). It also shows the keywords matter: `sky` off moves 1,966 and 2,367 px at the two outdoor viewpoints, while `bbox_cull` off moves 0 px but adds arrivals. | ~10 s |
| `census.py` | The census. Six staged fights (`--scen`) or S4's set (`--scenarios`), rendered each tic under 9 pictures: `today`, `todayR4`, `game`, the D3 options `a` `b` `c` `d` `abcd`, and `rec` (the recommended set; `--variants` renders a subset). For S4 it runs a **replay control**: the model's final digest must equal the frozen one. | ~0.9-1.4 s/tic |
| `census_skydiff.py` | Compares the census before and after `sky`/`bbox_cull`, frame by frame: the S4 runs whose keys did not change, or (`- -`) the staged fights. Its negative control feeds it a real compositor change and a mutated field. Result: on 7,200 S4 and 10,782 staged records no drawn, aim or seen count moved and no accepted projection changed; only arrivals fell (the cull). | seconds |
| `census_aimdiag.py` | Replays one S4 run and says WHY the picture's aim and the geometric aim disagree at column 80. | ~1 min |
| `census_report.py` | The tables: census counts, the option prices and the fight line (today's column and v2). For S4 it adds the binding effect on the set's own run structure: B0's MEASURED per-run averages (`--b0`, default `scenarios/b0_v1.json`) plus each run's modelled delta, through `gamespeed.binding_speed`. | seconds |

Commands (outputs go to `census_out/`: one JSON line per (frame, picture), plus the run logs and `report_*.txt`):
- `python scratchpad/gp/census_control.py` -> `census_out/control_sky.txt`
- `python scratchpad/gp/census.py --scenarios scratchpad/gp/census_out/s4v1/combat_scenarios_v1.snapshot.json --out scratchpad/gp/census_out/s4v1`
- `python scratchpad/gp/census_report.py --glob "scratchpad/gp/census_out/s4v1/*.jsonl"` -> `census_out/s4v1/report_s4v1.txt`
- `python scratchpad/gp/census.py --out scratchpad/gp/census_out/staged_sky`
- `python scratchpad/gp/census_report.py --glob "scratchpad/gp/census_out/staged_sky/*.jsonl"` -> `census_out/staged_sky/report_staged_sky.txt`
- `python scratchpad/gp/census_skydiff.py scratchpad/gp/census_out/s4 scratchpad/gp/census_out/s4v1 scratchpad/gp/census_out/s4/combat_scenarios_v1.snapshot.json scratchpad/gp/census_out/s4v1/combat_scenarios_v1.snapshot.json scratchpad/gp/census_out/s4_rec` -> `census_out/s4v1/skydiff.txt`
- `python scratchpad/gp/census_skydiff.py scratchpad/gp/census_out scratchpad/gp/census_out/staged_sky - - scratchpad/gp/census_out/staged_rec` -> `census_out/staged_sky/skydiff.txt`
- `python scratchpad/gp/census_aimdiag.py R0-northwest scratchpad/gp/census_out/s4v1/combat_scenarios_v1.snapshot.json` (and R0-south-hall, R2-barrel-hall, R0-courtyard, R2-east-yard) -> `census_out/s4v1/aimdiag.txt`

**The current outputs** are `census_out/s4v2/`: the FROZEN set v2 (843f28a), run by `census_v2.py`
and `census_v2_report.py` -> `report_s4v2.txt`, with `run_s4v2.log` (its 11/11 replay controls),
`fireballs.txt` (the fireball price) and `README.txt`. `census_out/s4v1/` is the v1 DRAFT's census,
kept as the record (the S4 set as landed in 709682d: snapshot sha256
`f2e3e4020654d36b`, git blob `1754f298`, a DRAFT; all 10 runs pass the replay control) and
`census_out/staged_sky/`. **Superseded:** `census_out/*.jsonl`, `staged_rec/`, `s4/` and `s4_rec/`
were rendered without `sky`/`bbox_cull`. `s4/` also used an older draft of the set (sha
`bbea2237dd66f13e`; R0-south-hall and R3-west differ). They are kept only for `census_skydiff.py`.

The unit costs and their provenance are in `census_report.py`'s docstring. Per-thing costs come
from in-game MEASURED means (thing_load, project_thing). Per-column costs are end-to-end, from S6b
(`docs/gp-sprite-column.md`) divided by its 1.70 standalone-to-game factor, which is UNVERIFIED.
Pricing per thing with thing_leaf's 30.2K would double-count the per-column record.
