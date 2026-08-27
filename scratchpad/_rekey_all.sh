#!/bin/bash
# emit the shipped program -> capture its labels -> re-key the certified set onto them -> add globals
set -e
# ⚠ this runs DETACHED, where PATH is not the interactive shell's: a bare `python`
# died on line 1 with "command not found" and the pipeline silently did nothing.
PY="${PY:-/c/Users/tomhe/AppData/Local/Programs/Python/Python311/python}"
"$PY" -c "import sys" || { echo "no python at $PY"; exit 1; }
echo "=== 1/4 emit ==="
"$PY" scratchpad/_emit_shipped.py
echo "=== 2/4 capture labels ==="
"$PY" scratchpad/_capture_labels.py
echo "=== 3/4 re-key ==="
git show ec05be9:src/doomfj/data/m1_restore_set.json.gz > scratchpad/_rk_in.json.gz
"$PY" scratchpad/ca_remap_set.py --labels scratchpad/_m1_labels_current.tsv.gz \
       --set scratchpad/_rk_in.json.gz --out scratchpad/_rk_out.json.gz
echo "=== 4/4 add globals ==="
"$PY" scratchpad/m1_add_globals.py --labels scratchpad/_m1_labels_current.tsv.gz \
       --set scratchpad/_rk_out.json.gz --out src/doomfj/data/m1_restore_set.json.gz
echo "=== REKEY DONE ==="
