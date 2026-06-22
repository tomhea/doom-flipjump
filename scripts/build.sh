#!/usr/bin/env bash
set -euo pipefail
# M0 toolchain smoke build.
PYTHONIOENCODING=utf-8 python -m doomfj.build
# M11c bake-off: the full-WIDTH-scale full-unroll renderer — writes build/metrics.json with the
# assemble_seconds + assemble_seconds_max (R-2) guard + the D2 verdict (overwrites the smoke metrics).
PYTHONIOENCODING=utf-8 python scripts/m11c_evidence.py
