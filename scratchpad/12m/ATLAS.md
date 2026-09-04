# ATLAS -- the measured pool table

REGENERATE at Phase 0 and at every phase boundary; structural ideas reshape the pools.

Method (section-19): per-op IP profiles (ca2_profile --bucket-bits 6) on ~8 population-spanning
frames of the current best binary, then price each macro region by summing the histogram over
the address interval between its labels, bucketed by the source-line tag in the label path.
Raw profiles and censuses live in scratchpad/12m/atlas/ and are NEVER read whole into context.

## STATUS: not yet built -- this is Phase 0's first deliverable.

Last known pool sizes (median frame, BEFORE the ts round shrank ts_step_faces -- stale, listed
only as a starting hypothesis for where to look):

| pool | then | note |
|---|---|---|
| ts_step_faces | 3.27M | the ts round cut ~0.73M of this; re-measure |
| fixed_mul | 1.76M | P3 target |
| emit_col | 1.71M | P5 target |
| hex.zero | 1.48M | P7 target |
| hex.cmp | 1.12M | P1 target |
| triple_exact_xor (arming) | 0.80M | P2 target |
| hex.mul | 0.60M | P3 |
| project_thing | 0.40M | P1/P4 |
| point_on_side | 0.34M | P4 |
| wedge | 0.33M | P1/P4 |
| hex.div | 0.31M | P3 |
| hex.if | 0.30M | P6 |

Frame population (65 grid points, angle 0, pre-ts-round): min 4.60M, p25 15.49M, median 19.46M,
p75 22.52M, max 38.26M. The spanning frames used by the tuner were (3149,2015), (1357,-289),
(1101,-545), (845,-801), (-416,256). Re-derive on the current binary with frame_costs.py.
