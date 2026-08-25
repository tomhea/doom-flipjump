#!/bin/bash
# usage: _h2_apply.sh <prefix-list>   e.g. _h2_apply.sh trb wxr ssc
# Re-applies ROUND 1 (already committed in the .fj files? no -- from git HEAD) plus the named
# round-2 macros, and rebuilds HOISTED_SCRATCH_DECLS accordingly.
set -e
declare -A M=( [trb]="src/fj/frame_render.fj thing_record_body" \
               [wxr]="src/fj/projection.fj wall_x_range_m" \
               [pth]="src/fj/projection.fj project_thing" \
               [ssc]="src/fj/stream_render.fj steps_splice_c" \
               [ssf]="src/fj/stream_render.fj steps_splice_f" \
               [wss]="src/fj/projection.fj wall_scale_setup_m" \
               [sst]="src/fj/projection.fj scalestep" \
               [srw]="src/fj/stream_render.fj sprite_runs_win" \
               [srn]="src/fj/stream_render.fj sprite_runs" \
               [pta]="src/fj/projection.fj point_to_angle" \
               [srd]="src/fj/projection.fj scale_recip_div" \
               [sga]="src/fj/projection.fj scale_from_global_angle" )
cp scratchpad/_h2_bak_frame.fj  src/fj/frame_render.fj
cp scratchpad/_h2_bak_proj.fj   src/fj/projection.fj
cp scratchpad/_h2_bak_stream.fj src/fj/stream_render.fj
: > scratchpad/_h2_decls.txt
for p in "$@"; do
  set -- ${M[$p]}
  timeout 120 python scratchpad/m1_hoist.py --file "$1" --macro "$2" --prefix "$p" >> scratchpad/_h2_decls.txt 2>&1
done
echo "applied: $* -> $(grep -c '^    \"' scratchpad/_h2_decls.txt) round-2 globals"
