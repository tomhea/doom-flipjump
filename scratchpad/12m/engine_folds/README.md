# Lever 1 (handoff-throughput-plan section 12): the engine loop's branch folds, measured and NOT shipped

Seven cumulative patches to `flipjump-151/flipjump/interpreter/_fjcore.c` at `cac64fd`
(apply in order a..g with `python patch_fold_<x>.py`; each asserts the exact text it rewrites):

| fold | what | hot-path branches after it (w=32, 4-byte cells) |
|---|---|---|
| a | full-span flat array (2^27 cells + a guard cell) at w=32 / cell32 / limit >= 2^27; the three span checks compiled out of that instantiation, with the proof in the source | 9 |
| b | the flip-word sentinel test joins the output test; the flip-target's test is deferred past its store to share one branch with the jump word's (the cold path undoes the store on real garbage) | 7 |
| c | the input test joins the head branch | 6 |
| d | `j == ip` and `j < 2w` become one branch | 5 |
| e | `ops++` strip-mined into the signal-check strip counter | 5 |
| f | the alignment test joins the head branch (full span only) | 4 |
| g | the two tail branches become one | 3 |

Every build passed flipjump-151's `test_native_memory` / `test_interpreter` / `test_fast_run`
(83 tests), `engine_diff.py` against its predecessor (15 edge cases), and `m2_std_gate` on
`blocked25` with the identical 4,432,191,712 ops / 210 frames. `msframe` verdicts (ledger,
2026-09-13 16:40-17:xx): fold a alone NOT SEPARATED (median ratio 1.017); all seven NOT SEPARATED
(1.009 at 5 reps); the same source under MSVC PGO (`pgo_build.py`, hot path fully fall-through)
NOT SEPARATED against the plain build (1.018). The branch count and the layout are not the
engine's floor; nothing here is worth its cost (fold a alone adds ~146 MB resident per process).
The folded source is also preserved as flipjump-151 branch `lever1-folds-measured`.
