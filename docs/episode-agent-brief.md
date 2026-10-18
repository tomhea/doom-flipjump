# The episode agents' brief (M8, 2026-10-19)

You are one of several agents working IN PARALLEL toward the owner's goal: a binary for every level E1M1..E1M9
(`docs/episode-plan.md` -- read it, and `CLAUDE.md`, `docs/cr-rules.md`, `docs/level-pipeline.md`). Your cluster is
named in your prompt. Others work on other clusters in their own worktrees at the same time; the integrator merges.

## The rules that keep parallel work from hurting the results

1. **Rule 1 is absolute: ONE heavy job on this 15.6 GB box at a time.** Wrap EVERY heavy command:
   `python scripts/heavy.py <your-name> --log <file> -- <cmd ...>` (waits for `C:\Users\tomhe\Documents\HEAVY.lock`,
   takes it exclusively, releases it). Heavy = any build / assembly, any full-map emission or `scripts/emit_check.py`,
   `scratchpad/cr/emit_baseline.py`, any gate script, msframe, a tests/fj file that runs over ~1 minute, any run of a
   whole test directory. Light (run directly): a single tests/host file, a short tests/fj file, `level_survey.py`.
   Never delete a lock you did not create. Never kill a python process you did not start. Never `python -O`.
2. **Both mirrors.** Every behaviour lands in the fj emitter AND the Python oracle (`src/doomfj/reference_model.py`
   and the model modules it uses) in the same commit; byte-exactness is the contract.
3. **E1M1 and E1M2 do not change** unless your prompt says so: put a new behaviour behind `config.MAP_CONFIG` (a map
   without it emits exactly what it emitted). Prove it once at the end: `heavy.py ... -- python
   scratchpad/cr/emit_baseline.py --check` (E1M1's parts SAME), and for E1M2 a hash comparison of its emitted parts
   before / after (or an existing identity test).
4. **Prove features by RUNNING fj** (tests/fj, a small harness), never a Python model of fj ops, and ship a negative
   control (R9) that a mutation must fail. Host tests for the model side with a control.
5. **The emitter ABI is frozen** (rule 4): fj global labels, macro names and positional parameter lists are not
   renamed. A shared helper change is a fan-out edit (rule 5: grep src/, scratchpad/, tests/).
6. **The survey is the contract**: when your cluster is done, `python scripts/level_survey.py --wad
   assets/freedoom1.wad --matrix E1M3 E1M4 E1M5 E1M6 E1M7 E1M8 E1M9` must no longer show your rows (or show them as
   handled); add a survey check for anything you learn that a future map could trip on, with a host test + control.
7. **Lessons**: in your final report list every mistake / trap you hit that another level or agent could hit, each
   with where it should live (a survey check, an emit_check refusal, a gate, a test).
8. **Git**: commit on your branch in logical steps; messages carry proof numbers; end each with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; stage NAMED files only (never `git add -A scratchpad/`;
   never build/ outputs, census caches, videos); `git push -u origin <your-branch>`; no PR.
9. **Stay in your lane**: touch what your cluster needs. If you must change a shared file another cluster plausibly
   touches (wall_renderer.py, reference_model.py, sim / things / config), keep the edit small and local and say so in
   the report, so the integrator can merge cleanly.

## Report (your final message)
What you built; the files touched (flag shared ones); proofs (test names and counts, controls rejecting, emission
identity); the survey rows cleared; per-frame op cost if you measured one; open problems; lessons (rule 7).
